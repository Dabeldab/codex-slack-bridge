"""Quarantined learning observations and skill proposals.

This module is deliberately disconnected from agent execution and active skill
directories.  It persists redacted, immutable learning evidence and reviewable
skill candidates in SQLite, but it has no API that installs, exports, or loads a
candidate as an instruction.  Runtime integration must live in a separate,
explicitly reviewed layer.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from threading import RLock
from typing import Any, Iterable, Mapping, Sequence

from .memory import redact_secrets

# AgentChat/direct_codex 2026-07-14T15:56:53-04:00: keep customer contact data out of reusable learning artifacts only.
_PRIVATE_CONTACT_RE = re.compile(
    r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b|"
    r"\b(?:\+?1[-.\s]?)?(?:\(?\d{3}\)?[-.\s]?)\d{3}[-.\s]?\d{4}\b"
)


_SAFE_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_.:-]{0,127}$")


class ObservationOutcome(str, Enum):
    """Business outcomes that are explicit enough to support safe learning."""

    COMPLETED_VERIFIED = "completed_verified"
    COMPLETED_UNVERIFIED = "completed_unverified"
    COMPLETED_WITH_ISSUES = "completed_with_issues"
    BLOCKED = "blocked"
    FAILED = "failed"
    UNCLASSIFIED = "unclassified"


class SkillCandidateState(str, Enum):
    DRAFT = "draft"
    EVALUATING = "evaluating"
    APPROVED = "approved"
    CANARY = "canary"
    ACTIVE = "active"
    RETIRED = "retired"
    ROLLED_BACK = "rolled_back"


_TRANSITIONS: Mapping[SkillCandidateState, frozenset[SkillCandidateState]] = {
    SkillCandidateState.DRAFT: frozenset(
        {SkillCandidateState.EVALUATING, SkillCandidateState.RETIRED}
    ),
    SkillCandidateState.EVALUATING: frozenset(
        {SkillCandidateState.APPROVED, SkillCandidateState.RETIRED}
    ),
    SkillCandidateState.APPROVED: frozenset(
        {SkillCandidateState.CANARY, SkillCandidateState.RETIRED}
    ),
    SkillCandidateState.CANARY: frozenset(
        {
            SkillCandidateState.ACTIVE,
            SkillCandidateState.ROLLED_BACK,
            SkillCandidateState.RETIRED,
        }
    ),
    SkillCandidateState.ACTIVE: frozenset(
        {SkillCandidateState.ROLLED_BACK, SkillCandidateState.RETIRED}
    ),
    SkillCandidateState.RETIRED: frozenset(),
    SkillCandidateState.ROLLED_BACK: frozenset(),
}

_EVIDENCE_REQUIRED_STATES = {
    SkillCandidateState.APPROVED,
    SkillCandidateState.CANARY,
    SkillCandidateState.ACTIVE,
}


class LearningIntegrityError(RuntimeError):
    """Raised when persisted learning data does not match its content hash."""


@dataclass(frozen=True)
class LearningObservation:
    id: str
    observation_key: str
    source_job_id: str
    agent_name: str
    lane: str
    outcome: ObservationOutcome
    summary: str
    systems: tuple[str, ...]
    capabilities_used: tuple[str, ...]
    evidence: Mapping[str, Any]
    verification_evidence: Mapping[str, Any]
    provenance: Mapping[str, Any]
    occurred_at: float
    recorded_at: float
    content_hash: str

    @property
    def eligible_for_skill_proposal(self) -> bool:
        return self.outcome is ObservationOutcome.COMPLETED_VERIFIED and bool(
            self.verification_evidence
        )


@dataclass(frozen=True)
class SkillCandidate:
    id: str
    skill_key: str
    version: int
    state: SkillCandidateState
    owner_agent: str
    owner_lane: str
    title: str
    description: str
    instructions: str
    requested_capabilities: tuple[str, ...]
    capability_ceiling: tuple[str, ...]
    capability_policy_hash: str
    source_observation_ids: tuple[str, ...]
    parent_candidate_id: str | None
    created_by: str
    provenance: Mapping[str, Any]
    content_hash: str
    created_at: float
    updated_at: float


@dataclass(frozen=True)
class SkillCandidateTransition:
    sequence: int
    event_id: str
    candidate_id: str
    from_state: SkillCandidateState | None
    to_state: SkillCandidateState
    actor: str
    rationale: str
    evidence: Mapping[str, Any]
    previous_event_hash: str | None
    event_hash: str
    created_at: float


class LearningProposalRegistry:
    """Append-only evidence and proposal registry backed by SQLite.

    ``capability_policy`` is trusted configuration supplied by the host, not by
    an agent-generated proposal.  A candidate must remain within that ceiling;
    later versions must also remain within their parent candidate's narrower
    capability set.  Lifecycle states are review metadata only—even ``active``
    does not install or execute content.  This store never writes to a skill
    directory.
    """

    def __init__(
        self,
        sqlite_path: str | Path,
        *,
        capability_policy: Mapping[str, Iterable[str]],
        max_summary_chars: int = 2_000,
        max_instructions_chars: int = 30_000,
    ) -> None:
        self.sqlite_path = Path(sqlite_path)
        self.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        self.max_summary_chars = max(200, int(max_summary_chars))
        self.max_instructions_chars = max(1_000, int(max_instructions_chars))
        self._capability_policy = {
            _safe_name(agent, "capability policy agent"): frozenset(
                _capability_set(capabilities)
            )
            for agent, capabilities in capability_policy.items()
        }
        self._lock = RLock()
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.sqlite_path, timeout=5.0)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA busy_timeout=5000")
        db.execute("PRAGMA foreign_keys=ON")
        return db

    def _init_schema(self) -> None:
        with self._lock, self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS learning_observations (
                    id TEXT PRIMARY KEY,
                    observation_key TEXT NOT NULL UNIQUE,
                    source_job_id TEXT NOT NULL,
                    agent_name TEXT NOT NULL,
                    lane TEXT NOT NULL,
                    outcome TEXT NOT NULL CHECK (
                        outcome IN (
                            'completed_verified', 'completed_unverified',
                            'completed_with_issues', 'blocked', 'failed',
                            'unclassified'
                        )
                    ),
                    summary TEXT NOT NULL,
                    systems_json TEXT NOT NULL,
                    capabilities_used_json TEXT NOT NULL,
                    evidence_json TEXT NOT NULL,
                    verification_evidence_json TEXT NOT NULL,
                    provenance_json TEXT NOT NULL,
                    occurred_at REAL NOT NULL,
                    recorded_at REAL NOT NULL,
                    content_hash TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_learning_observations_outcome_time
                    ON learning_observations(outcome, occurred_at DESC);

                CREATE TRIGGER IF NOT EXISTS learning_observations_no_update
                BEFORE UPDATE ON learning_observations
                BEGIN
                    SELECT RAISE(ABORT, 'learning observations are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS learning_observations_no_delete
                BEFORE DELETE ON learning_observations
                BEGIN
                    SELECT RAISE(ABORT, 'learning observations are immutable');
                END;

                CREATE TABLE IF NOT EXISTS learning_skill_candidates (
                    id TEXT PRIMARY KEY,
                    skill_key TEXT NOT NULL,
                    version INTEGER NOT NULL CHECK (version > 0),
                    state TEXT NOT NULL CHECK (
                        state IN (
                            'draft', 'evaluating', 'approved', 'canary',
                            'active', 'retired', 'rolled_back'
                        )
                    ),
                    owner_agent TEXT NOT NULL,
                    owner_lane TEXT NOT NULL,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL,
                    instructions TEXT NOT NULL,
                    requested_capabilities_json TEXT NOT NULL,
                    capability_ceiling_json TEXT NOT NULL,
                    capability_policy_hash TEXT NOT NULL,
                    source_observation_ids_json TEXT NOT NULL,
                    parent_candidate_id TEXT REFERENCES learning_skill_candidates(id),
                    created_by TEXT NOT NULL,
                    provenance_json TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    UNIQUE(skill_key, version)
                );
                CREATE INDEX IF NOT EXISTS idx_learning_candidates_state
                    ON learning_skill_candidates(state, skill_key, version DESC);

                CREATE TRIGGER IF NOT EXISTS learning_candidates_content_immutable
                BEFORE UPDATE ON learning_skill_candidates
                WHEN
                    NEW.id IS NOT OLD.id OR
                    NEW.skill_key IS NOT OLD.skill_key OR
                    NEW.version IS NOT OLD.version OR
                    NEW.owner_agent IS NOT OLD.owner_agent OR
                    NEW.owner_lane IS NOT OLD.owner_lane OR
                    NEW.title IS NOT OLD.title OR
                    NEW.description IS NOT OLD.description OR
                    NEW.instructions IS NOT OLD.instructions OR
                    NEW.requested_capabilities_json IS NOT OLD.requested_capabilities_json OR
                    NEW.capability_ceiling_json IS NOT OLD.capability_ceiling_json OR
                    NEW.capability_policy_hash IS NOT OLD.capability_policy_hash OR
                    NEW.source_observation_ids_json IS NOT OLD.source_observation_ids_json OR
                    NEW.parent_candidate_id IS NOT OLD.parent_candidate_id OR
                    NEW.created_by IS NOT OLD.created_by OR
                    NEW.provenance_json IS NOT OLD.provenance_json OR
                    NEW.content_hash IS NOT OLD.content_hash OR
                    NEW.created_at IS NOT OLD.created_at
                BEGIN
                    SELECT RAISE(ABORT, 'skill candidate content is immutable; create a new version');
                END;
                CREATE TRIGGER IF NOT EXISTS learning_candidates_state_requires_transition
                BEFORE UPDATE OF state ON learning_skill_candidates
                WHEN NEW.state IS NOT OLD.state AND NOT EXISTS (
                    SELECT 1 FROM learning_skill_transitions
                    WHERE candidate_id=OLD.id
                      AND from_state=OLD.state
                      AND to_state=NEW.state
                      AND created_at=NEW.updated_at
                )
                BEGIN
                    SELECT RAISE(ABORT, 'skill candidate state requires an audited transition');
                END;
                CREATE TRIGGER IF NOT EXISTS learning_candidates_timestamp_requires_state
                BEFORE UPDATE OF updated_at ON learning_skill_candidates
                WHEN NEW.updated_at IS NOT OLD.updated_at AND NEW.state IS OLD.state
                BEGIN
                    SELECT RAISE(ABORT, 'candidate timestamps change only with state transitions');
                END;
                CREATE TRIGGER IF NOT EXISTS learning_candidates_no_delete
                BEFORE DELETE ON learning_skill_candidates
                BEGIN
                    SELECT RAISE(ABORT, 'skill candidates cannot be deleted');
                END;

                CREATE TABLE IF NOT EXISTS learning_skill_transitions (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT NOT NULL UNIQUE,
                    candidate_id TEXT NOT NULL REFERENCES learning_skill_candidates(id),
                    from_state TEXT,
                    to_state TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    rationale TEXT NOT NULL,
                    evidence_json TEXT NOT NULL,
                    previous_event_hash TEXT,
                    event_hash TEXT NOT NULL,
                    created_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_learning_transitions_candidate
                    ON learning_skill_transitions(candidate_id, sequence);

                CREATE TRIGGER IF NOT EXISTS learning_transitions_no_update
                BEFORE UPDATE ON learning_skill_transitions
                BEGIN
                    SELECT RAISE(ABORT, 'skill transition history is immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS learning_transitions_no_delete
                BEFORE DELETE ON learning_skill_transitions
                BEGIN
                    SELECT RAISE(ABORT, 'skill transition history is immutable');
                END;
                """
            )
            self._migrate_observation_schema(db)

    @staticmethod
    def _migrate_observation_schema(db: sqlite3.Connection) -> None:
        """Widen the immutable outcome constraint without losing observations."""

        db.execute(
            """
            CREATE TABLE IF NOT EXISTS learning_schema_versions (
                component TEXT PRIMARY KEY,
                version INTEGER NOT NULL,
                updated_at REAL NOT NULL
            )
            """
        )
        row = db.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='learning_observations'"
        ).fetchone()
        table_sql = str(row[0] or "").casefold() if row is not None else ""
        if "completed_unverified" not in table_sql or "unclassified" not in table_sql:
            db.commit()
            db.executescript(
                """
                BEGIN IMMEDIATE;
                DROP TRIGGER IF EXISTS learning_observations_no_update;
                DROP TRIGGER IF EXISTS learning_observations_no_delete;
                DROP INDEX IF EXISTS idx_learning_observations_outcome_time;
                DROP TABLE IF EXISTS learning_observations_v2;

                CREATE TABLE learning_observations_v2 (
                    id TEXT PRIMARY KEY,
                    observation_key TEXT NOT NULL UNIQUE,
                    source_job_id TEXT NOT NULL,
                    agent_name TEXT NOT NULL,
                    lane TEXT NOT NULL,
                    outcome TEXT NOT NULL CHECK (
                        outcome IN (
                            'completed_verified', 'completed_unverified',
                            'completed_with_issues', 'blocked', 'failed',
                            'unclassified'
                        )
                    ),
                    summary TEXT NOT NULL,
                    systems_json TEXT NOT NULL,
                    capabilities_used_json TEXT NOT NULL,
                    evidence_json TEXT NOT NULL,
                    verification_evidence_json TEXT NOT NULL,
                    provenance_json TEXT NOT NULL,
                    occurred_at REAL NOT NULL,
                    recorded_at REAL NOT NULL,
                    content_hash TEXT NOT NULL
                );
                INSERT INTO learning_observations_v2
                SELECT * FROM learning_observations;
                DROP TABLE learning_observations;
                ALTER TABLE learning_observations_v2 RENAME TO learning_observations;

                CREATE INDEX idx_learning_observations_outcome_time
                    ON learning_observations(outcome, occurred_at DESC);
                CREATE TRIGGER learning_observations_no_update
                BEFORE UPDATE ON learning_observations
                BEGIN
                    SELECT RAISE(ABORT, 'learning observations are immutable');
                END;
                CREATE TRIGGER learning_observations_no_delete
                BEFORE DELETE ON learning_observations
                BEGIN
                    SELECT RAISE(ABORT, 'learning observations are immutable');
                END;
                COMMIT;
                """
            )
        db.execute(
            """
            INSERT INTO learning_schema_versions(component, version, updated_at)
            VALUES ('observations', 2, ?)
            ON CONFLICT(component) DO UPDATE SET
                version=excluded.version,
                updated_at=excluded.updated_at
            """,
            (time.time(),),
        )

    def append_observation(
        self,
        *,
        observation_key: str,
        source_job_id: str,
        agent_name: str,
        lane: str,
        outcome: ObservationOutcome | str,
        summary: str,
        systems: Sequence[str] = (),
        capabilities_used: Sequence[str] = (),
        evidence: Mapping[str, Any] | None = None,
        verification_evidence: Mapping[str, Any] | None = None,
        provenance: Mapping[str, Any] | None = None,
        occurred_at: float | str | datetime | None = None,
    ) -> LearningObservation:
        safe_key = _required_redacted(observation_key, "observation_key", max_chars=500)
        safe_source_job = _required_redacted(source_job_id, "source_job_id", max_chars=500)
        safe_agent = _safe_name(agent_name, "agent_name")
        safe_lane = _safe_name(lane, "lane")
        parsed_outcome = _enum_value(ObservationOutcome, outcome, "outcome")
        safe_summary = _redacted_text(summary, "summary", max_chars=self.max_summary_chars)
        safe_systems = _safe_name_set(systems, "system")
        safe_capabilities = _capability_set(capabilities_used)
        safe_evidence = _sanitized_mapping(evidence)
        safe_verification = _sanitized_mapping(verification_evidence)
        safe_provenance = _sanitized_mapping(provenance)
        if parsed_outcome is ObservationOutcome.COMPLETED_VERIFIED and not safe_verification:
            raise ValueError(
                "completed_verified observations require verification_evidence"
            )
        if parsed_outcome is not ObservationOutcome.COMPLETED_VERIFIED and safe_verification:
            raise ValueError(
                "verification_evidence is reserved for completed_verified observations"
            )

        explicit_occurred_at = occurred_at is not None
        occurred = _timestamp(occurred_at) or time.time()
        recorded = time.time()
        observation_id = str(
            uuid.uuid5(uuid.NAMESPACE_URL, f"learning-observation:{safe_key}")
        )
        payload = {
            "id": observation_id,
            "observation_key": safe_key,
            "source_job_id": safe_source_job,
            "agent_name": safe_agent,
            "lane": safe_lane,
            "outcome": parsed_outcome.value,
            "summary": safe_summary,
            "systems": list(safe_systems),
            "capabilities_used": list(safe_capabilities),
            "evidence": safe_evidence,
            "verification_evidence": safe_verification,
            "provenance": safe_provenance,
            "occurred_at": occurred,
            "recorded_at": recorded,
        }
        content_hash = _digest(payload)
        with self._lock, self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute(
                "SELECT * FROM learning_observations WHERE observation_key=?",
                (safe_key,),
            ).fetchone()
            if existing is not None:
                result = self._decode_observation(existing)
                comparison_occurred = occurred if explicit_occurred_at else result.occurred_at
                if _observation_semantic_payload(result) != _observation_semantic_payload_from_values(
                    source_job_id=safe_source_job,
                    agent_name=safe_agent,
                    lane=safe_lane,
                    outcome=parsed_outcome,
                    summary=safe_summary,
                    systems=safe_systems,
                    capabilities_used=safe_capabilities,
                    evidence=safe_evidence,
                    verification_evidence=safe_verification,
                    provenance=safe_provenance,
                    occurred_at=comparison_occurred,
                ):
                    raise ValueError("observation_key is already bound to different content")
                db.commit()
                return result
            db.execute(
                """
                INSERT INTO learning_observations(
                    id, observation_key, source_job_id, agent_name, lane, outcome,
                    summary, systems_json, capabilities_used_json, evidence_json,
                    verification_evidence_json, provenance_json, occurred_at,
                    recorded_at, content_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    observation_id,
                    safe_key,
                    safe_source_job,
                    safe_agent,
                    safe_lane,
                    parsed_outcome.value,
                    safe_summary,
                    _json(safe_systems),
                    _json(safe_capabilities),
                    _json(safe_evidence),
                    _json(safe_verification),
                    _json(safe_provenance),
                    occurred,
                    recorded,
                    content_hash,
                ),
            )
            row = db.execute(
                "SELECT * FROM learning_observations WHERE id=?", (observation_id,)
            ).fetchone()
            db.commit()
        assert row is not None
        return self._decode_observation(row)

    def get_observation(self, observation_id: str) -> LearningObservation | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM learning_observations WHERE id=?", (str(observation_id),)
            ).fetchone()
        return self._decode_observation(row) if row is not None else None

    def list_observations(
        self,
        *,
        outcome: ObservationOutcome | str | None = None,
        eligible_for_skill_proposal: bool = False,
        limit: int = 100,
    ) -> list[LearningObservation]:
        clauses: list[str] = []
        values: list[Any] = []
        if outcome is not None:
            clauses.append("outcome=?")
            values.append(_enum_value(ObservationOutcome, outcome, "outcome").value)
        if eligible_for_skill_proposal:
            clauses.extend(
                ["outcome='completed_verified'", "verification_evidence_json != '{}'"]
            )
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        values.append(max(1, min(int(limit), 1_000)))
        with self._connect() as db:
            rows = db.execute(
                f"SELECT * FROM learning_observations {where} "
                "ORDER BY occurred_at DESC, id LIMIT ?",
                values,
            ).fetchall()
        return [self._decode_observation(row) for row in rows]

    def propose_skill_candidate(
        self,
        *,
        skill_key: str,
        owner_agent: str,
        owner_lane: str,
        title: str,
        description: str,
        instructions: str,
        requested_capabilities: Sequence[str],
        source_observation_ids: Sequence[str],
        created_by: str,
        provenance: Mapping[str, Any] | None = None,
        parent_candidate_id: str | None = None,
    ) -> SkillCandidate:
        safe_key = _safe_name(skill_key, "skill_key")
        safe_owner = _safe_name(owner_agent, "owner_agent")
        safe_lane = _safe_name(owner_lane, "owner_lane")
        safe_title = _redacted_text(title, "title", max_chars=200)
        safe_description = _redacted_text(
            description, "description", max_chars=4_000
        )
        safe_instructions = _redacted_text(
            instructions, "instructions", max_chars=self.max_instructions_chars
        )
        safe_created_by = _required_redacted(
            created_by, "created_by", max_chars=500
        )
        safe_provenance = _sanitized_mapping(provenance)
        requested = _capability_set(requested_capabilities)
        source_ids = tuple(dict.fromkeys(str(item).strip() for item in source_observation_ids))
        if not source_ids or any(not item for item in source_ids):
            raise ValueError("source_observation_ids must contain at least one id")

        ceiling = self._capability_policy.get(safe_owner)
        if ceiling is None:
            raise ValueError(f"No trusted capability policy exists for {safe_owner!r}")
        excess = set(requested) - set(ceiling)
        if excess:
            raise ValueError(
                f"candidate would broaden {safe_owner} capabilities: {sorted(excess)}"
            )
        safe_ceiling = tuple(sorted(ceiling))
        policy_hash = _digest(
            {"owner_agent": safe_owner, "capability_ceiling": list(safe_ceiling)}
        )

        now = time.time()
        with self._lock, self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            observations = self._required_observations(db, source_ids)
            ineligible = [
                observation.id
                for observation in observations
                if not observation.eligible_for_skill_proposal
            ]
            if ineligible:
                raise ValueError(
                    "skill candidates require completed_verified source observations; "
                    f"ineligible: {sorted(ineligible)}"
                )

            latest_row = db.execute(
                """
                SELECT * FROM learning_skill_candidates
                WHERE skill_key=? ORDER BY version DESC LIMIT 1
                """,
                (safe_key,),
            ).fetchone()
            parent: SkillCandidate | None = None
            if latest_row is not None:
                latest = self._decode_candidate(latest_row)
                requested_parent_id = str(parent_candidate_id or latest.id)
                if requested_parent_id != latest.id:
                    raise ValueError("a new version must descend from the latest candidate")
                parent = latest
                if parent.owner_agent != safe_owner or parent.owner_lane != safe_lane:
                    raise ValueError("candidate ownership cannot change across versions")
                broadened = set(requested) - set(parent.requested_capabilities)
                if broadened:
                    raise ValueError(
                        "a new candidate version cannot broaden its parent's capabilities: "
                        f"{sorted(broadened)}"
                    )
                version = parent.version + 1
            else:
                if parent_candidate_id:
                    raise ValueError("parent_candidate_id is invalid for a first version")
                version = 1

            candidate_id = str(uuid.uuid4())
            parent_id = parent.id if parent is not None else None
            payload = {
                "id": candidate_id,
                "skill_key": safe_key,
                "version": version,
                "owner_agent": safe_owner,
                "owner_lane": safe_lane,
                "title": safe_title,
                "description": safe_description,
                "instructions": safe_instructions,
                "requested_capabilities": list(requested),
                "capability_ceiling": list(safe_ceiling),
                "capability_policy_hash": policy_hash,
                "source_observation_ids": list(source_ids),
                "parent_candidate_id": parent_id,
                "created_by": safe_created_by,
                "provenance": safe_provenance,
            }
            content_hash = _digest(payload)
            db.execute(
                """
                INSERT INTO learning_skill_candidates(
                    id, skill_key, version, state, owner_agent, owner_lane, title,
                    description, instructions, requested_capabilities_json,
                    capability_ceiling_json, capability_policy_hash,
                    source_observation_ids_json, parent_candidate_id, created_by,
                    provenance_json, content_hash, created_at, updated_at
                ) VALUES (?, ?, ?, 'draft', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    candidate_id,
                    safe_key,
                    version,
                    safe_owner,
                    safe_lane,
                    safe_title,
                    safe_description,
                    safe_instructions,
                    _json(requested),
                    _json(safe_ceiling),
                    policy_hash,
                    _json(source_ids),
                    parent_id,
                    safe_created_by,
                    _json(safe_provenance),
                    content_hash,
                    now,
                    now,
                ),
            )
            self._insert_transition(
                db,
                candidate_id=candidate_id,
                from_state=None,
                to_state=SkillCandidateState.DRAFT,
                actor=safe_created_by,
                rationale="candidate proposed",
                evidence={"content_hash": content_hash},
                now=now,
            )
            row = db.execute(
                "SELECT * FROM learning_skill_candidates WHERE id=?", (candidate_id,)
            ).fetchone()
            db.commit()
        assert row is not None
        return self._decode_candidate(row)

    def transition_candidate(
        self,
        candidate_id: str,
        to_state: SkillCandidateState | str,
        *,
        actor: str,
        rationale: str,
        evidence: Mapping[str, Any] | None = None,
    ) -> SkillCandidate:
        target = _enum_value(SkillCandidateState, to_state, "to_state")
        safe_actor = _required_redacted(actor, "actor", max_chars=500)
        safe_rationale = _redacted_text(rationale, "rationale", max_chars=4_000)
        safe_evidence = _sanitized_mapping(evidence)
        if target in _EVIDENCE_REQUIRED_STATES and not safe_evidence:
            raise ValueError(f"transition to {target.value} requires evidence")

        now = time.time()
        with self._lock, self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT * FROM learning_skill_candidates WHERE id=?",
                (str(candidate_id),),
            ).fetchone()
            if row is None:
                raise KeyError(candidate_id)
            candidate = self._decode_candidate(row)
            if target not in _TRANSITIONS[candidate.state]:
                raise ValueError(
                    f"invalid skill candidate transition: {candidate.state.value} -> {target.value}"
                )
            self._insert_transition(
                db,
                candidate_id=candidate.id,
                from_state=candidate.state,
                to_state=target,
                actor=safe_actor,
                rationale=safe_rationale,
                evidence=safe_evidence,
                now=now,
            )
            db.execute(
                "UPDATE learning_skill_candidates SET state=?, updated_at=? WHERE id=?",
                (target.value, now, candidate.id),
            )
            updated = db.execute(
                "SELECT * FROM learning_skill_candidates WHERE id=?", (candidate.id,)
            ).fetchone()
            db.commit()
        assert updated is not None
        return self._decode_candidate(updated)

    def get_candidate(self, candidate_id: str) -> SkillCandidate | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM learning_skill_candidates WHERE id=?",
                (str(candidate_id),),
            ).fetchone()
        return self._decode_candidate(row) if row is not None else None

    def list_candidates(
        self,
        *,
        state: SkillCandidateState | str | None = None,
        skill_key: str | None = None,
        limit: int = 100,
    ) -> list[SkillCandidate]:
        clauses: list[str] = []
        values: list[Any] = []
        if state is not None:
            clauses.append("state=?")
            values.append(_enum_value(SkillCandidateState, state, "state").value)
        if skill_key is not None:
            clauses.append("skill_key=?")
            values.append(_safe_name(skill_key, "skill_key"))
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        values.append(max(1, min(int(limit), 1_000)))
        with self._connect() as db:
            rows = db.execute(
                f"SELECT * FROM learning_skill_candidates {where} "
                "ORDER BY skill_key, version DESC LIMIT ?",
                values,
            ).fetchall()
        return [self._decode_candidate(row) for row in rows]

    def candidate_history(self, candidate_id: str) -> list[SkillCandidateTransition]:
        with self._connect() as db:
            rows = db.execute(
                """
                SELECT * FROM learning_skill_transitions
                WHERE candidate_id=? ORDER BY sequence
                """,
                (str(candidate_id),),
            ).fetchall()
        history = [self._decode_transition(row) for row in rows]
        previous_hash: str | None = None
        for transition in history:
            payload = _transition_payload(transition, previous_hash)
            if transition.previous_event_hash != previous_hash:
                raise LearningIntegrityError(
                    f"broken transition hash chain for candidate {candidate_id}"
                )
            if _digest(payload) != transition.event_hash:
                raise LearningIntegrityError(
                    f"transition hash mismatch for event {transition.event_id}"
                )
            previous_hash = transition.event_hash
        return history

    def _required_observations(
        self, db: sqlite3.Connection, observation_ids: Sequence[str]
    ) -> list[LearningObservation]:
        placeholders = ",".join("?" for _ in observation_ids)
        rows = db.execute(
            f"SELECT * FROM learning_observations WHERE id IN ({placeholders})",
            list(observation_ids),
        ).fetchall()
        by_id = {str(row["id"]): row for row in rows}
        missing = [item for item in observation_ids if item not in by_id]
        if missing:
            raise ValueError(f"unknown source observation: {missing[0]}")
        return [self._decode_observation(by_id[item]) for item in observation_ids]

    def _insert_transition(
        self,
        db: sqlite3.Connection,
        *,
        candidate_id: str,
        from_state: SkillCandidateState | None,
        to_state: SkillCandidateState,
        actor: str,
        rationale: str,
        evidence: Mapping[str, Any],
        now: float,
    ) -> None:
        previous = db.execute(
            """
            SELECT event_hash FROM learning_skill_transitions
            WHERE candidate_id=? ORDER BY sequence DESC LIMIT 1
            """,
            (candidate_id,),
        ).fetchone()
        previous_hash = str(previous["event_hash"]) if previous is not None else None
        event_id = str(uuid.uuid4())
        values = {
            "event_id": event_id,
            "candidate_id": candidate_id,
            "from_state": from_state.value if from_state else None,
            "to_state": to_state.value,
            "actor": actor,
            "rationale": rationale,
            "evidence": dict(evidence),
            "previous_event_hash": previous_hash,
            "created_at": now,
        }
        event_hash = _digest(values)
        db.execute(
            """
            INSERT INTO learning_skill_transitions(
                event_id, candidate_id, from_state, to_state, actor, rationale,
                evidence_json, previous_event_hash, event_hash, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                candidate_id,
                values["from_state"],
                to_state.value,
                actor,
                rationale,
                _json(evidence),
                previous_hash,
                event_hash,
                now,
            ),
        )

    @staticmethod
    def _decode_observation(row: sqlite3.Row) -> LearningObservation:
        observation = LearningObservation(
            id=str(row["id"]),
            observation_key=str(row["observation_key"]),
            source_job_id=str(row["source_job_id"]),
            agent_name=str(row["agent_name"]),
            lane=str(row["lane"]),
            outcome=ObservationOutcome(str(row["outcome"])),
            summary=str(row["summary"]),
            systems=tuple(json.loads(row["systems_json"])),
            capabilities_used=tuple(json.loads(row["capabilities_used_json"])),
            evidence=json.loads(row["evidence_json"]),
            verification_evidence=json.loads(row["verification_evidence_json"]),
            provenance=json.loads(row["provenance_json"]),
            occurred_at=float(row["occurred_at"]),
            recorded_at=float(row["recorded_at"]),
            content_hash=str(row["content_hash"]),
        )
        payload = {
            "id": observation.id,
            "observation_key": observation.observation_key,
            **_observation_semantic_payload(observation),
            "recorded_at": observation.recorded_at,
        }
        if _digest(payload) != observation.content_hash:
            raise LearningIntegrityError(
                f"learning observation hash mismatch: {observation.id}"
            )
        return observation

    @staticmethod
    def _decode_candidate(row: sqlite3.Row) -> SkillCandidate:
        candidate = SkillCandidate(
            id=str(row["id"]),
            skill_key=str(row["skill_key"]),
            version=int(row["version"]),
            state=SkillCandidateState(str(row["state"])),
            owner_agent=str(row["owner_agent"]),
            owner_lane=str(row["owner_lane"]),
            title=str(row["title"]),
            description=str(row["description"]),
            instructions=str(row["instructions"]),
            requested_capabilities=tuple(
                json.loads(row["requested_capabilities_json"])
            ),
            capability_ceiling=tuple(json.loads(row["capability_ceiling_json"])),
            capability_policy_hash=str(row["capability_policy_hash"]),
            source_observation_ids=tuple(
                json.loads(row["source_observation_ids_json"])
            ),
            parent_candidate_id=(
                str(row["parent_candidate_id"])
                if row["parent_candidate_id"] is not None
                else None
            ),
            created_by=str(row["created_by"]),
            provenance=json.loads(row["provenance_json"]),
            content_hash=str(row["content_hash"]),
            created_at=float(row["created_at"]),
            updated_at=float(row["updated_at"]),
        )
        payload = {
            "id": candidate.id,
            "skill_key": candidate.skill_key,
            "version": candidate.version,
            "owner_agent": candidate.owner_agent,
            "owner_lane": candidate.owner_lane,
            "title": candidate.title,
            "description": candidate.description,
            "instructions": candidate.instructions,
            "requested_capabilities": list(candidate.requested_capabilities),
            "capability_ceiling": list(candidate.capability_ceiling),
            "capability_policy_hash": candidate.capability_policy_hash,
            "source_observation_ids": list(candidate.source_observation_ids),
            "parent_candidate_id": candidate.parent_candidate_id,
            "created_by": candidate.created_by,
            "provenance": candidate.provenance,
        }
        if _digest(payload) != candidate.content_hash:
            raise LearningIntegrityError(
                f"skill candidate hash mismatch: {candidate.id}"
            )
        expected_policy_hash = _digest(
            {
                "owner_agent": candidate.owner_agent,
                "capability_ceiling": list(candidate.capability_ceiling),
            }
        )
        if expected_policy_hash != candidate.capability_policy_hash:
            raise LearningIntegrityError(
                f"capability policy hash mismatch: {candidate.id}"
            )
        return candidate

    @staticmethod
    def _decode_transition(row: sqlite3.Row) -> SkillCandidateTransition:
        return SkillCandidateTransition(
            sequence=int(row["sequence"]),
            event_id=str(row["event_id"]),
            candidate_id=str(row["candidate_id"]),
            from_state=(
                SkillCandidateState(str(row["from_state"]))
                if row["from_state"] is not None
                else None
            ),
            to_state=SkillCandidateState(str(row["to_state"])),
            actor=str(row["actor"]),
            rationale=str(row["rationale"]),
            evidence=json.loads(row["evidence_json"]),
            previous_event_hash=(
                str(row["previous_event_hash"])
                if row["previous_event_hash"] is not None
                else None
            ),
            event_hash=str(row["event_hash"]),
            created_at=float(row["created_at"]),
        )


def _observation_semantic_payload(observation: LearningObservation) -> dict[str, Any]:
    return {
        "source_job_id": observation.source_job_id,
        "agent_name": observation.agent_name,
        "lane": observation.lane,
        "outcome": observation.outcome.value,
        "summary": observation.summary,
        "systems": list(observation.systems),
        "capabilities_used": list(observation.capabilities_used),
        "evidence": observation.evidence,
        "verification_evidence": observation.verification_evidence,
        "provenance": observation.provenance,
        "occurred_at": observation.occurred_at,
    }


def _observation_semantic_payload_from_values(
    *,
    source_job_id: str,
    agent_name: str,
    lane: str,
    outcome: ObservationOutcome,
    summary: str,
    systems: Sequence[str],
    capabilities_used: Sequence[str],
    evidence: Mapping[str, Any],
    verification_evidence: Mapping[str, Any],
    provenance: Mapping[str, Any],
    occurred_at: float,
) -> dict[str, Any]:
    return {
        "source_job_id": source_job_id,
        "agent_name": agent_name,
        "lane": lane,
        "outcome": outcome.value,
        "summary": summary,
        "systems": list(systems),
        "capabilities_used": list(capabilities_used),
        "evidence": evidence,
        "verification_evidence": verification_evidence,
        "provenance": provenance,
        "occurred_at": occurred_at,
    }


def _transition_payload(
    transition: SkillCandidateTransition, previous_hash: str | None
) -> dict[str, Any]:
    return {
        "event_id": transition.event_id,
        "candidate_id": transition.candidate_id,
        "from_state": transition.from_state.value if transition.from_state else None,
        "to_state": transition.to_state.value,
        "actor": transition.actor,
        "rationale": transition.rationale,
        "evidence": dict(transition.evidence),
        "previous_event_hash": previous_hash,
        "created_at": transition.created_at,
    }


def _enum_value(enum_type: type[Enum], value: Enum | str, label: str) -> Any:
    try:
        return enum_type(value.value if isinstance(value, Enum) else str(value).strip().casefold())
    except ValueError as exc:
        options = sorted(item.value for item in enum_type)
        raise ValueError(f"{label} must be one of {options}") from exc


def _safe_name(value: str, label: str) -> str:
    clean = str(value or "").strip().casefold()
    if not _SAFE_NAME_RE.fullmatch(clean):
        raise ValueError(
            f"{label} must match {_SAFE_NAME_RE.pattern!r}"
        )
    return clean


def _safe_name_set(values: Iterable[str], label: str) -> tuple[str, ...]:
    return tuple(sorted({_safe_name(value, label) for value in values}))


def _capability_set(values: Iterable[str]) -> tuple[str, ...]:
    return _safe_name_set(values, "capability")


def _required_redacted(value: str, label: str, *, max_chars: int) -> str:
    clean = _redact_learning_private_data(str(value or "")).strip()
    if not clean:
        raise ValueError(f"{label} is required")
    if len(clean) > max_chars:
        raise ValueError(f"{label} is too long")
    return clean


def _redacted_text(value: str, label: str, *, max_chars: int) -> str:
    return _required_redacted(value, label, max_chars=max_chars)


def _sanitized_mapping(value: Mapping[str, Any] | None) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ValueError("structured learning data must be a mapping")
    sanitized = _sanitize_json(value)
    assert isinstance(sanitized, dict)
    return sanitized


def _sanitize_json(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return _redact_learning_private_data(value)
    if isinstance(value, Mapping):
        return {
            _redact_learning_private_data(str(key)): _sanitize_json(child)
            for key, child in value.items()
        }
    if isinstance(value, (list, tuple, set)):
        return [_sanitize_json(child) for child in value]
    return _redact_learning_private_data(str(value))


def _redact_learning_private_data(value: str) -> str:
    """Reusable workflows must not retain customer-private contact details."""
    return _PRIVATE_CONTACT_RE.sub("[redacted]", redact_secrets(value))


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _digest(value: Any) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _timestamp(value: float | str | datetime | None) -> float | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.timestamp()
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    try:
        return float(text)
    except ValueError:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
