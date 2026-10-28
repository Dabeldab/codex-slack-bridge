"""Episodic and relational memory primitives.

This module deliberately does not perform model inference.  It stores compact,
verified episodes and an entity graph which callers can use as retrieval cues.
Sensitive aliases are indexed by digest, allowing exact lookup without retaining
the original identifier.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
import time
import uuid
from collections import deque
from datetime import datetime
from pathlib import Path
from threading import RLock
from typing import Any, Iterable, Mapping, Sequence

from .memory import redact_secrets


_TOKEN_RE = re.compile(r"[a-zA-Z0-9_./:-]+")
_VALID_STATUS = {"active", "inactive", "stale", "disputed", "superseded"}


class CognitiveMemoryStore:
    """Thread/process-safe SQLite store for episodic and relational memory."""

    def __init__(self, sqlite_path: str | Path, *, max_summary_chars: int = 1600) -> None:
        self.sqlite_path = Path(sqlite_path)
        self.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        self.max_summary_chars = max(200, int(max_summary_chars))
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
        # All objects are additive and use names specific to this subsystem, so
        # it is safe to initialize beside an older semantic-memory schema.
        with self._lock, self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS cognitive_episodes (
                    id TEXT PRIMARY KEY,
                    agent_name TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    intent TEXT NOT NULL DEFAULT '',
                    systems_json TEXT NOT NULL DEFAULT '[]',
                    status TEXT NOT NULL DEFAULT 'verified',
                    occurred_at REAL NOT NULL,
                    recorded_at REAL NOT NULL,
                    fresh_until REAL,
                    source TEXT NOT NULL,
                    evidence_json TEXT NOT NULL DEFAULT '{}',
                    metadata_json TEXT NOT NULL DEFAULT '{}'
                );
                CREATE INDEX IF NOT EXISTS idx_cognitive_episodes_time
                    ON cognitive_episodes(occurred_at DESC);
                CREATE INDEX IF NOT EXISTS idx_cognitive_episodes_intent
                    ON cognitive_episodes(intent, occurred_at DESC);

                CREATE TABLE IF NOT EXISTS cognitive_entities (
                    id TEXT PRIMARY KEY,
                    entity_type TEXT NOT NULL,
                    canonical_name TEXT NOT NULL,
                    canonical_hash TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    status TEXT NOT NULL,
                    source TEXT NOT NULL,
                    evidence_json TEXT NOT NULL DEFAULT '{}',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    first_seen_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    fresh_until REAL,
                    UNIQUE(entity_type, canonical_hash)
                );
                CREATE INDEX IF NOT EXISTS idx_cognitive_entities_status
                    ON cognitive_entities(status, entity_type);

                CREATE TABLE IF NOT EXISTS cognitive_entity_aliases (
                    id TEXT PRIMARY KEY,
                    entity_id TEXT NOT NULL REFERENCES cognitive_entities(id),
                    alias_hash TEXT NOT NULL,
                    display_alias TEXT NOT NULL,
                    alias_type TEXT NOT NULL DEFAULT 'identifier',
                    confidence REAL NOT NULL,
                    status TEXT NOT NULL,
                    evidence_json TEXT NOT NULL DEFAULT '{}',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    fresh_until REAL,
                    UNIQUE(alias_hash, alias_type)
                );
                CREATE INDEX IF NOT EXISTS idx_cognitive_alias_entity
                    ON cognitive_entity_aliases(entity_id);

                CREATE TABLE IF NOT EXISTS cognitive_relationships (
                    id TEXT PRIMARY KEY,
                    source_entity_id TEXT NOT NULL REFERENCES cognitive_entities(id),
                    target_entity_id TEXT NOT NULL REFERENCES cognitive_entities(id),
                    relationship_type TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    status TEXT NOT NULL,
                    source TEXT NOT NULL,
                    evidence_json TEXT NOT NULL DEFAULT '{}',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    fresh_until REAL,
                    UNIQUE(source_entity_id, target_entity_id, relationship_type)
                );
                CREATE INDEX IF NOT EXISTS idx_cognitive_rel_source
                    ON cognitive_relationships(source_entity_id, status);
                CREATE INDEX IF NOT EXISTS idx_cognitive_rel_target
                    ON cognitive_relationships(target_entity_id, status);

                CREATE TABLE IF NOT EXISTS cognitive_episode_entities (
                    episode_id TEXT NOT NULL REFERENCES cognitive_episodes(id),
                    entity_id TEXT NOT NULL REFERENCES cognitive_entities(id),
                    role TEXT NOT NULL DEFAULT 'subject',
                    confidence REAL NOT NULL,
                    evidence_json TEXT NOT NULL DEFAULT '{}',
                    created_at REAL NOT NULL,
                    PRIMARY KEY(episode_id, entity_id, role)
                );
                CREATE INDEX IF NOT EXISTS idx_cognitive_episode_entity
                    ON cognitive_episode_entities(entity_id, episode_id);

                CREATE TABLE IF NOT EXISTS cognitive_audit_log (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT NOT NULL UNIQUE,
                    object_type TEXT NOT NULL,
                    object_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    snapshot_json TEXT NOT NULL,
                    created_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_cognitive_audit_object
                    ON cognitive_audit_log(object_type, object_id, sequence);
                """
            )

    def upsert_entity(
        self,
        *,
        entity_type: str,
        canonical_name: str,
        aliases: Sequence[str | Mapping[str, Any]] | None = None,
        confidence: float = 1.0,
        status: str = "active",
        source: str = "operator",
        evidence: Any = None,
        fresh_until: float | str | datetime | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> str:
        entity_type = _safe_required(entity_type, "entity_type")
        raw_name = _required_short(canonical_name, "canonical_name", max_chars=500)
        confidence = _confidence(confidence)
        status = _status(status)
        now = time.time()
        name_hash = _identifier_hash(raw_name)
        safe_name = _safe_identifier_display(raw_name)
        evidence_json = _safe_json(evidence or {})
        metadata_json = _safe_json(dict(metadata or {}))
        safe_source = _safe_required(source, "source", max_chars=500)
        expiry = _timestamp(fresh_until)

        with self._lock, self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute(
                "SELECT id, first_seen_at FROM cognitive_entities WHERE entity_type = ? AND canonical_hash = ?",
                (entity_type.casefold(), name_hash),
            ).fetchone()
            entity_id = str(existing["id"]) if existing else str(uuid.uuid4())
            if existing:
                db.execute(
                    """UPDATE cognitive_entities SET canonical_name=?, confidence=?, status=?, source=?,
                       evidence_json=?, metadata_json=?, updated_at=?, fresh_until=? WHERE id=?""",
                    (safe_name, confidence, status, safe_source, evidence_json, metadata_json, now, expiry, entity_id),
                )
                action = "updated"
            else:
                db.execute(
                    """INSERT INTO cognitive_entities VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (entity_id, entity_type.casefold(), safe_name, name_hash, confidence, status, safe_source,
                     evidence_json, metadata_json, now, now, expiry),
                )
                action = "created"

            all_aliases: list[str | Mapping[str, Any]] = [
                {"value": raw_name, "type": "canonical", "confidence": confidence}
            ]
            all_aliases.extend(aliases or [])
            for alias in all_aliases:
                self._upsert_alias(db, entity_id, alias, status=status, evidence=evidence, fresh_until=expiry, now=now)
            self._audit(db, "entity", entity_id, action, self._entity_row(db, entity_id), now)
            db.commit()
        return entity_id

    def _upsert_alias(
        self,
        db: sqlite3.Connection,
        entity_id: str,
        alias: str | Mapping[str, Any],
        *,
        status: str,
        evidence: Any,
        fresh_until: float | None,
        now: float,
    ) -> None:
        record = dict(alias) if isinstance(alias, Mapping) else {"value": alias}
        raw_value = _required_short(str(record.get("value") or ""), "alias", max_chars=1000)
        alias_type = _safe_required(str(record.get("type") or "identifier"), "alias_type")
        digest = _identifier_hash(raw_value)
        owner = db.execute(
            "SELECT id, entity_id FROM cognitive_entity_aliases WHERE alias_hash=? AND alias_type=?",
            (digest, alias_type.casefold()),
        ).fetchone()
        if owner and str(owner["entity_id"]) != entity_id:
            raise ValueError("Identifier alias is already linked to another entity")
        alias_id = str(uuid.uuid4())
        alias_confidence = _confidence(record.get("confidence", 1.0))
        alias_status = _status(str(record.get("status") or status))
        alias_evidence = _safe_json(record.get("evidence", evidence or {}))
        alias_expiry = _timestamp(record.get("fresh_until")) if record.get("fresh_until") is not None else fresh_until
        db.execute(
            """INSERT INTO cognitive_entity_aliases(
                   id, entity_id, alias_hash, display_alias, alias_type, confidence, status,
                   evidence_json, created_at, updated_at, fresh_until
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(alias_hash, alias_type) DO UPDATE SET
                   confidence=excluded.confidence, status=excluded.status,
                   evidence_json=excluded.evidence_json, updated_at=excluded.updated_at,
                   fresh_until=excluded.fresh_until""",
            (alias_id, entity_id, digest, _safe_identifier_display(raw_value), alias_type.casefold(),
             alias_confidence, alias_status, alias_evidence, now, now, alias_expiry),
        )
        stored = dict(db.execute(
            "SELECT * FROM cognitive_entity_aliases WHERE alias_hash=? AND alias_type=?",
            (digest, alias_type.casefold()),
        ).fetchone())
        self._audit(db, "entity_alias", str(stored["id"]), "updated" if owner else "created", stored, now)

    def link_entities(
        self,
        source_entity_id: str,
        target_entity_id: str,
        relationship_type: str,
        *,
        confidence: float = 1.0,
        status: str = "active",
        source: str = "operator",
        evidence: Any = None,
        fresh_until: float | str | datetime | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> str:
        if source_entity_id == target_entity_id:
            raise ValueError("A relationship must connect two different entities")
        relationship_type = _safe_required(relationship_type, "relationship_type")
        safe_source = _safe_required(source, "source", max_chars=500)
        now = time.time()
        with self._lock, self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._require_entities(db, [source_entity_id, target_entity_id])
            existing = db.execute(
                """SELECT id FROM cognitive_relationships
                   WHERE source_entity_id=? AND target_entity_id=? AND relationship_type=?""",
                (source_entity_id, target_entity_id, relationship_type.casefold()),
            ).fetchone()
            relationship_id = str(existing["id"]) if existing else str(uuid.uuid4())
            values = (
                _confidence(confidence), _status(status), safe_source, _safe_json(evidence or {}),
                _safe_json(dict(metadata or {})), now, _timestamp(fresh_until), relationship_id,
            )
            if existing:
                db.execute(
                    """UPDATE cognitive_relationships SET confidence=?, status=?, source=?, evidence_json=?,
                       metadata_json=?, updated_at=?, fresh_until=? WHERE id=?""",
                    values,
                )
                action = "updated"
            else:
                db.execute(
                    """INSERT INTO cognitive_relationships VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (relationship_id, source_entity_id, target_entity_id, relationship_type.casefold(),
                     _confidence(confidence), _status(status), safe_source, _safe_json(evidence or {}),
                     _safe_json(dict(metadata or {})), now, now, _timestamp(fresh_until)),
                )
                action = "created"
            row = dict(db.execute("SELECT * FROM cognitive_relationships WHERE id=?", (relationship_id,)).fetchone())
            self._audit(db, "relationship", relationship_id, action, row, now)
            db.commit()
        return relationship_id

    def append_episode(
        self,
        *,
        agent_name: str,
        summary: str,
        intent: str = "",
        systems: Sequence[str] | None = None,
        entity_links: Sequence[str | Mapping[str, Any]] | None = None,
        occurred_at: float | str | datetime | None = None,
        source: str = "verified-job",
        evidence: Any = None,
        fresh_until: float | str | datetime | None = None,
        metadata: Mapping[str, Any] | None = None,
        verified: bool = True,
        episode_key: str | None = None,
    ) -> str:
        if not verified:
            raise ValueError("Only verified outcomes may be appended as episodes")
        safe_summary = redact_secrets(str(summary)).strip()
        if not safe_summary:
            raise ValueError("summary is required")
        if len(safe_summary) > self.max_summary_chars:
            safe_summary = safe_summary[: self.max_summary_chars].rstrip() + " [truncated]"
        stable_key = str(episode_key or "").strip()
        episode_id = (
            str(uuid.uuid5(uuid.NAMESPACE_URL, f"cognitive-episode:{stable_key}"))
            if stable_key
            else str(uuid.uuid4())
        )
        now = time.time()
        occurred = _timestamp(occurred_at) or now
        system_list = sorted({_safe_required(item, "system").casefold() for item in systems or []})
        links = list(entity_links or [])
        with self._lock, self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if stable_key and db.execute("SELECT 1 FROM cognitive_episodes WHERE id=?", (episode_id,)).fetchone():
                db.commit()
                return episode_id
            db.execute(
                """INSERT INTO cognitive_episodes VALUES (?, ?, ?, ?, ?, 'verified', ?, ?, ?, ?, ?, ?)""",
                (episode_id, _safe_required(agent_name, "agent_name"), safe_summary,
                 redact_secrets(str(intent).strip()).casefold(), json.dumps(system_list), occurred, now,
                 _timestamp(fresh_until), _safe_required(source, "source", max_chars=500), _safe_json(evidence or {}),
                 _safe_json(dict(metadata or {}))),
            )
            for link in links:
                record = dict(link) if isinstance(link, Mapping) else {"entity_id": link}
                self._insert_episode_link(db, episode_id, record, now)
            snapshot = dict(db.execute("SELECT * FROM cognitive_episodes WHERE id=?", (episode_id,)).fetchone())
            self._audit(db, "episode", episode_id, "appended", snapshot, now)
            db.commit()
        return episode_id

    def quarantine_misclassified_outcome_episodes(self) -> int:
        """Retire legacy runtime attempts that lacked independent verification.

        Older runtime callers treated process completion as business verification.
        Preserve those episodes and their audit history, but exclude them from
        retrieval so they cannot teach future agents an unverified procedure.
        """

        markers = (
            "\noutcome: blocked",
            "\noutcome: completed_with_issues",
            "\noutcome: failed",
        )
        now = time.time()
        with self._lock, self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            rows = db.execute(
                "SELECT * FROM cognitive_episodes WHERE status='verified'"
            ).fetchall()
            quarantined = 0
            for row in rows:
                normalized = str(row["summary"] or "").casefold()
                try:
                    evidence = json.loads(str(row["evidence_json"] or "{}"))
                except (TypeError, ValueError, json.JSONDecodeError):
                    evidence = {}
                runtime_completion_only = (
                    isinstance(evidence, dict)
                    and str(evidence.get("completion") or "").strip().casefold()
                    == "agent_run_completed"
                    and not _has_independent_readback(evidence)
                )
                if not runtime_completion_only and not any(marker in normalized for marker in markers):
                    continue
                db.execute(
                    "UPDATE cognitive_episodes SET status='review_only' WHERE id=? AND status='verified'",
                    (row["id"],),
                )
                if not db.execute("SELECT changes()").fetchone()[0]:
                    continue
                snapshot = dict(row)
                snapshot["status"] = "review_only"
                self._audit(db, "episode", str(row["id"]), "quarantined_unverified_runtime_episode", snapshot, now)
                quarantined += 1
            db.commit()
        return quarantined

    def link_episode_entity(
        self,
        episode_id: str,
        entity_id: str,
        *,
        role: str = "subject",
        confidence: float = 1.0,
        evidence: Any = None,
    ) -> None:
        now = time.time()
        with self._lock, self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if not db.execute("SELECT 1 FROM cognitive_episodes WHERE id=?", (episode_id,)).fetchone():
                raise ValueError(f"Unknown episode: {episode_id}")
            self._insert_episode_link(db, episode_id, {
                "entity_id": entity_id, "role": role, "confidence": confidence, "evidence": evidence or {}
            }, now)
            self._audit(db, "episode", episode_id, "entity_linked", {"entity_id": entity_id, "role": role}, now)
            db.commit()

    def _insert_episode_link(self, db: sqlite3.Connection, episode_id: str, record: Mapping[str, Any], now: float) -> None:
        entity_id = str(record.get("entity_id") or record.get("id") or "").strip()
        self._require_entities(db, [entity_id])
        cursor = db.execute(
            """INSERT OR IGNORE INTO cognitive_episode_entities
               VALUES (?, ?, ?, ?, ?, ?)""",
            (episode_id, entity_id, _safe_required(str(record.get("role") or "subject"), "role").casefold(),
             _confidence(record.get("confidence", 1.0)), _safe_json(record.get("evidence") or {}), now),
        )
        if cursor.rowcount:
            link_id = f"{episode_id}:{entity_id}:{str(record.get('role') or 'subject').casefold()}"
            self._audit(db, "episode_entity", link_id, "created", {
                "episode_id": episode_id,
                "entity_id": entity_id,
                "role": str(record.get("role") or "subject").casefold(),
                "confidence": _confidence(record.get("confidence", 1.0)),
            }, now)

    def lookup_identifier(
        self,
        identifier: str,
        *,
        entity_type: str | None = None,
        include_inactive: bool = False,
        at_time: float | None = None,
    ) -> list[dict[str, Any]]:
        now = at_time or time.time()
        clauses = ["a.alias_hash = ?"]
        values: list[Any] = [_identifier_hash(_required_short(identifier, "identifier", max_chars=1000))]
        if entity_type:
            clauses.append("e.entity_type = ?")
            values.append(entity_type.casefold())
        if not include_inactive:
            clauses.extend([
                "e.status = 'active'", "a.status = 'active'",
                "(e.fresh_until IS NULL OR e.fresh_until > ?)",
                "(a.fresh_until IS NULL OR a.fresh_until > ?)",
            ])
            values.extend([now, now])
        with self._connect() as db:
            rows = db.execute(
                f"""SELECT e.*, a.alias_type, a.confidence AS alias_confidence,
                            a.display_alias, a.fresh_until AS alias_fresh_until
                     FROM cognitive_entity_aliases a
                     JOIN cognitive_entities e ON e.id=a.entity_id
                     WHERE {' AND '.join(clauses)}
                     ORDER BY a.confidence DESC, e.confidence DESC""",
                values,
            ).fetchall()
        return [_decode_entity(row) for row in rows]

    def associative_neighbors(
        self,
        entity_id: str,
        *,
        max_depth: int = 2,
        min_confidence: float = 0.25,
        relationship_types: Iterable[str] | None = None,
        at_time: float | None = None,
    ) -> list[dict[str, Any]]:
        max_depth = min(max(int(max_depth), 0), 5)
        now = at_time or time.time()
        allowed = {item.casefold() for item in relationship_types or []}
        results: dict[str, dict[str, Any]] = {}
        queue: deque[tuple[str, float, int, list[str], list[str]]] = deque([(entity_id, 1.0, 0, [entity_id], [])])
        best = {entity_id: 1.0}
        with self._connect() as db:
            self._require_entities(db, [entity_id])
            while queue:
                current, path_score, depth, path, rel_path = queue.popleft()
                if depth >= max_depth:
                    continue
                rows = db.execute(
                    """SELECT * FROM cognitive_relationships
                       WHERE status='active' AND (fresh_until IS NULL OR fresh_until > ?)
                         AND (source_entity_id=? OR target_entity_id=?)""",
                    (now, current, current),
                ).fetchall()
                for row in rows:
                    rel_type = str(row["relationship_type"])
                    if allowed and rel_type not in allowed:
                        continue
                    neighbor = str(row["target_entity_id"] if row["source_entity_id"] == current else row["source_entity_id"])
                    if neighbor in path:
                        continue
                    # Confidence compounds along a path; hop decay keeps broad
                    # graph associations from outranking exact identifiers.
                    score = path_score * float(row["confidence"]) * 0.82
                    if score < min_confidence or score <= best.get(neighbor, 0.0):
                        continue
                    best[neighbor] = score
                    next_path = [*path, neighbor]
                    next_rel_path = [*rel_path, rel_type]
                    results[neighbor] = {
                        "entity_id": neighbor, "score": round(score, 6), "depth": depth + 1,
                        "path": next_path, "relationship_types": next_rel_path,
                    }
                    queue.append((neighbor, score, depth + 1, next_path, next_rel_path))
            if results:
                placeholders = ",".join("?" for _ in results)
                for row in db.execute(f"SELECT * FROM cognitive_entities WHERE id IN ({placeholders})", list(results)):
                    results[str(row["id"])]["entity"] = _decode_entity(row)
        return sorted(results.values(), key=lambda item: (-item["score"], item["depth"], item["entity_id"]))

    def retrieve_episodes(
        self,
        *,
        identifiers: Sequence[str] | None = None,
        entity_ids: Sequence[str] | None = None,
        intent: str | None = None,
        systems: Sequence[str] | None = None,
        query: str = "",
        since: float | str | datetime | None = None,
        until: float | str | datetime | None = None,
        max_depth: int = 2,
        top_k: int = 8,
        at_time: float | None = None,
        agent_names: Sequence[str] | None = None,
    ) -> list[dict[str, Any]]:
        now = at_time or time.time()
        cue_scores: dict[str, float] = {str(item): 1.0 for item in entity_ids or []}
        for identifier in identifiers or []:
            for match in self.lookup_identifier(identifier, at_time=now):
                cue_scores[str(match["id"])] = max(cue_scores.get(str(match["id"]), 0.0), 1.0)
        for seed_id in list(cue_scores):
            for neighbor in self.associative_neighbors(seed_id, max_depth=max_depth, at_time=now):
                neighbor_id = str(neighbor["entity_id"])
                cue_scores[neighbor_id] = max(cue_scores.get(neighbor_id, 0.0), float(neighbor["score"]))

        clauses = ["e.status='verified'", "(e.fresh_until IS NULL OR e.fresh_until > ?)"]
        values: list[Any] = [now]
        if intent:
            clauses.append("e.intent = ?")
            values.append(intent.strip().casefold())
        scoped_agents = sorted({str(item).strip() for item in agent_names or [] if str(item).strip()})
        if scoped_agents:
            placeholders = ",".join("?" for _ in scoped_agents)
            clauses.append(f"e.agent_name IN ({placeholders})")
            values.extend(scoped_agents)
        if since is not None:
            clauses.append("e.occurred_at >= ?")
            values.append(_timestamp(since))
        if until is not None:
            clauses.append("e.occurred_at <= ?")
            values.append(_timestamp(until))
        with self._connect() as db:
            rows = db.execute(
                f"SELECT e.* FROM cognitive_episodes e WHERE {' AND '.join(clauses)} ORDER BY e.occurred_at DESC",
                values,
            ).fetchall()
            results: list[dict[str, Any]] = []
            requested_systems = {item.casefold() for item in systems or []}
            query_tokens = _tokens(query)
            for row in rows:
                episode = _decode_episode(row)
                episode_systems = set(episode["systems"])
                if requested_systems and not requested_systems.intersection(episode_systems):
                    continue
                links = db.execute(
                    "SELECT entity_id, role, confidence FROM cognitive_episode_entities WHERE episode_id=?",
                    (episode["id"],),
                ).fetchall()
                linked_scores = [cue_scores.get(str(link["entity_id"]), 0.0) * float(link["confidence"]) for link in links]
                entity_score = max(linked_scores, default=0.0)
                lexical = _jaccard(query_tokens, _tokens(episode["summary"])) if query_tokens else 0.0
                if cue_scores and entity_score <= 0 and lexical <= 0:
                    continue
                if query_tokens and not cue_scores and lexical <= 0:
                    continue
                age_days = max(0.0, (now - float(episode["occurred_at"])) / 86400.0)
                recency = math.exp(-age_days / 180.0)
                intent_score = 1.0 if intent and episode["intent"] == intent.casefold() else 0.0
                system_score = 1.0 if requested_systems and requested_systems.intersection(episode_systems) else 0.0
                score = 0.52 * entity_score + 0.20 * lexical + 0.10 * intent_score + 0.08 * system_score + 0.10 * recency
                episode["score"] = round(score, 6)
                episode["entity_links"] = [dict(item) for item in links]
                results.append(episode)
        results.sort(key=lambda item: (-item["score"], -item["occurred_at"], item["id"]))
        return results[: max(1, min(int(top_k), 100))]

    def audit_history(self, object_type: str, object_id: str) -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute(
                """SELECT * FROM cognitive_audit_log WHERE object_type=? AND object_id=? ORDER BY sequence""",
                (object_type, object_id),
            ).fetchall()
        return [{**dict(row), "snapshot": json.loads(row["snapshot_json"])} for row in rows]

    @staticmethod
    def _audit(db: sqlite3.Connection, object_type: str, object_id: str, action: str, snapshot: Any, now: float) -> None:
        db.execute(
            "INSERT INTO cognitive_audit_log(event_id, object_type, object_id, action, snapshot_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (str(uuid.uuid4()), object_type, object_id, action, _safe_json(snapshot), now),
        )

    @staticmethod
    def _require_entities(db: sqlite3.Connection, entity_ids: Sequence[str]) -> None:
        if not entity_ids or any(not entity_id for entity_id in entity_ids):
            raise ValueError("entity_id is required")
        placeholders = ",".join("?" for _ in entity_ids)
        found = {str(row[0]) for row in db.execute(f"SELECT id FROM cognitive_entities WHERE id IN ({placeholders})", list(entity_ids))}
        missing = set(entity_ids) - found
        if missing:
            raise ValueError(f"Unknown entity: {sorted(missing)[0]}")

    @staticmethod
    def _entity_row(db: sqlite3.Connection, entity_id: str) -> dict[str, Any]:
        return dict(db.execute("SELECT * FROM cognitive_entities WHERE id=?", (entity_id,)).fetchone())


def _identifier_hash(value: str) -> str:
    return hashlib.sha256(value.strip().casefold().encode("utf-8")).hexdigest()


def _safe_identifier_display(value: str) -> str:
    redacted = redact_secrets(value).strip()
    return redacted if redacted == value.strip() else "[sensitive identifier]"


def _safe_json(value: Any) -> str:
    # Redact leaf strings rather than serialized JSON. Applying phone/card
    # patterns to a whole JSON document can accidentally match timestamps and
    # corrupt otherwise valid JSON syntax.
    def sanitize(item: Any) -> Any:
        if item is None or isinstance(item, (bool, int, float)):
            return item
        if isinstance(item, str):
            return redact_secrets(item)
        if isinstance(item, Mapping):
            return {str(key): sanitize(child) for key, child in item.items()}
        if isinstance(item, (list, tuple, set)):
            return [sanitize(child) for child in item]
        return redact_secrets(str(item))

    return json.dumps(sanitize(value), sort_keys=True, ensure_ascii=False)


def _has_independent_readback(evidence: Mapping[str, Any]) -> bool:
    if any(
        evidence.get(key) is True
        for key in ("independent_readback", "post_write_readback", "host_verified")
    ):
        return True
    for key in ("verification_evidence", "readback_evidence"):
        value = evidence.get(key)
        if isinstance(value, Mapping) and value:
            return True
        if isinstance(value, (list, tuple)) and value:
            return True
    return False


def _required_short(value: str, label: str, *, max_chars: int = 120) -> str:
    clean = str(value).strip()
    if not clean:
        raise ValueError(f"{label} is required")
    if len(clean) > max_chars:
        raise ValueError(f"{label} is too long")
    return clean


def _safe_required(value: str, label: str, *, max_chars: int = 120) -> str:
    return redact_secrets(_required_short(value, label, max_chars=max_chars)).strip()


def _confidence(value: Any) -> float:
    result = float(value)
    if not 0.0 <= result <= 1.0:
        raise ValueError("confidence must be between 0 and 1")
    return result


def _status(value: str) -> str:
    result = str(value).strip().casefold()
    if result not in _VALID_STATUS:
        raise ValueError(f"status must be one of {sorted(_VALID_STATUS)}")
    return result


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


def _decode_entity(row: sqlite3.Row) -> dict[str, Any]:
    result = dict(row)
    result["evidence"] = json.loads(result.pop("evidence_json", "{}"))
    result["metadata"] = json.loads(result.pop("metadata_json", "{}"))
    result.pop("canonical_hash", None)
    return result


def _decode_episode(row: sqlite3.Row) -> dict[str, Any]:
    result = dict(row)
    result["systems"] = json.loads(result.pop("systems_json", "[]"))
    result["evidence"] = json.loads(result.pop("evidence_json", "{}"))
    result["metadata"] = json.loads(result.pop("metadata_json", "{}"))
    return result


def _tokens(text: str) -> set[str]:
    return {token.casefold() for token in _TOKEN_RE.findall(text) if len(token) > 1}


def _jaccard(left: set[str], right: set[str]) -> float:
    return len(left & right) / len(left | right) if left and right else 0.0
