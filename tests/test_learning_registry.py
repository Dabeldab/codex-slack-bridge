from __future__ import annotations

import sqlite3

import pytest

from codex_slack_bridge.learning_registry import (
    LearningIntegrityError,
    LearningProposalRegistry,
    ObservationOutcome,
    SkillCandidateState,
)


NOW = 1_800_000_000.0
SECRET = "sk-abcdefghijklmnopqrstuvwxyz123456"


def _registry(tmp_path):
    return LearningProposalRegistry(
        tmp_path / "learning.sqlite3",
        capability_policy={
            "coding_agent": {"repo.read", "repo.write"},
            "tickets_agent": {"salesforce.read"},
        },
    )


def _verified_observation(registry, *, key="job-1", summary="Verified safe workflow"):
    return registry.append_observation(
        observation_key=key,
        source_job_id=key,
        agent_name="coding_agent",
        lane="coding",
        outcome=ObservationOutcome.COMPLETED_VERIFIED,
        summary=summary,
        systems=["github"],
        capabilities_used=["repo.read"],
        evidence={"job": key},
        verification_evidence={"tests": "passed", "readback": True},
        provenance={"commit": "abc123"},
        occurred_at=NOW,
    )


def _candidate(registry, observation_id, **overrides):
    values = {
        "skill_key": "safe-repo-workflow",
        "owner_agent": "coding_agent",
        "owner_lane": "coding",
        "title": "Safe repository workflow",
        "description": "A proposed repository procedure.",
        "instructions": "Read the repository, make a narrow change, and run tests.",
        "requested_capabilities": ["repo.read"],
        "source_observation_ids": [observation_id],
        "created_by": "learning-reviewer",
        "provenance": {"proposal_reason": "repeated verified success"},
    }
    values.update(overrides)
    return registry.propose_skill_candidate(**values)


def test_legacy_observation_schema_migrates_without_losing_rows(tmp_path):
    sqlite_path = tmp_path / "learning.sqlite3"
    with sqlite3.connect(sqlite_path) as db:
        db.executescript(
            """
            CREATE TABLE learning_observations (
                id TEXT PRIMARY KEY,
                observation_key TEXT NOT NULL UNIQUE,
                source_job_id TEXT NOT NULL,
                agent_name TEXT NOT NULL,
                lane TEXT NOT NULL,
                outcome TEXT NOT NULL CHECK (
                    outcome IN (
                        'completed_verified', 'completed_with_issues',
                        'blocked', 'failed'
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
            """
        )
        db.execute(
            """
            INSERT INTO learning_observations (
                id, observation_key, source_job_id, agent_name, lane, outcome,
                summary, systems_json, capabilities_used_json, evidence_json,
                verification_evidence_json, provenance_json, occurred_at,
                recorded_at, content_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "legacy-row",
                "legacy-blocked",
                "legacy-job",
                "coding_agent",
                "coding",
                "blocked",
                "Legacy blocker remains review-only.",
                "[]",
                "[]",
                "{}",
                "[]",
                "{}",
                NOW,
                NOW,
                "legacy-content-hash",
            ),
        )

    registry = LearningProposalRegistry(
        sqlite_path,
        capability_policy={"coding_agent": {"repo.read", "repo.write"}},
    )

    with sqlite3.connect(sqlite_path) as db:
        legacy = db.execute(
            """
            SELECT id, observation_key, source_job_id, outcome, summary
            FROM learning_observations
            WHERE id='legacy-row'
            """
        ).fetchone()
        schema_sql = db.execute(
            """
            SELECT sql FROM sqlite_master
            WHERE type='table' AND name='learning_observations'
            """
        ).fetchone()[0]

    assert legacy == (
        "legacy-row",
        "legacy-blocked",
        "legacy-job",
        "blocked",
        "Legacy blocker remains review-only.",
    )
    assert "completed_unverified" in schema_sql
    assert "unclassified" in schema_sql

    completed_unverified = registry.append_observation(
        observation_key="new-completed-unverified",
        source_job_id="new-job-1",
        agent_name="coding_agent",
        lane="coding",
        outcome=ObservationOutcome.COMPLETED_UNVERIFIED,
        summary="The agent reported completion without independent readback.",
        occurred_at=NOW + 1,
    )
    unclassified = registry.append_observation(
        observation_key="new-unclassified",
        source_job_id="new-job-2",
        agent_name="coding_agent",
        lane="coding",
        outcome=ObservationOutcome.UNCLASSIFIED,
        summary="The agent omitted a valid leading outcome marker.",
        occurred_at=NOW + 2,
    )

    assert completed_unverified.outcome is ObservationOutcome.COMPLETED_UNVERIFIED
    assert unclassified.outcome is ObservationOutcome.UNCLASSIFIED


def test_observations_are_redacted_hashed_and_database_immutable(tmp_path):
    registry = _registry(tmp_path)
    observation = registry.append_observation(
        observation_key="secret-job",
        source_job_id="job-secret",
        agent_name="coding_agent",
        lane="coding",
        outcome="completed_verified",
        summary=f"Used credential {SECRET} for person@example.com",
        evidence={"token": SECRET, "contact": "person@example.com"},
        verification_evidence={"readback": f"passed with {SECRET}"},
        provenance={"operator": "person@example.com"},
        occurred_at=NOW,
    )

    assert observation.eligible_for_skill_proposal is True
    assert SECRET not in observation.summary
    assert "person@example.com" not in observation.summary
    assert len(observation.content_hash) == 64
    assert registry.get_observation(observation.id) == observation

    with sqlite3.connect(registry.sqlite_path) as db:
        dump = "\n".join(db.iterdump())
        assert SECRET not in dump
        assert "person@example.com" not in dump
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            db.execute(
                "UPDATE learning_observations SET summary='changed' WHERE id=?",
                (observation.id,),
            )
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            db.execute("DELETE FROM learning_observations WHERE id=?", (observation.id,))


def test_observation_key_is_idempotent_but_cannot_be_rebound(tmp_path):
    registry = _registry(tmp_path)
    original = _verified_observation(registry)
    repeated = _verified_observation(registry)

    assert repeated == original
    with pytest.raises(ValueError, match="different content"):
        _verified_observation(registry, summary="A conflicting result")

    implicit_time = registry.append_observation(
        observation_key="implicit-time",
        source_job_id="implicit-time",
        agent_name="coding_agent",
        lane="coding",
        outcome="completed_verified",
        summary="Verified without a caller-supplied timestamp.",
        verification_evidence={"readback": True},
    )
    repeated_implicit_time = registry.append_observation(
        observation_key="implicit-time",
        source_job_id="implicit-time",
        agent_name="coding_agent",
        lane="coding",
        outcome="completed_verified",
        summary="Verified without a caller-supplied timestamp.",
        verification_evidence={"readback": True},
    )
    assert repeated_implicit_time == implicit_time


def test_only_completed_verified_observations_can_seed_candidates(tmp_path):
    registry = _registry(tmp_path)
    blocked = registry.append_observation(
        observation_key="blocked-1",
        source_job_id="blocked-1",
        agent_name="coding_agent",
        lane="coding",
        outcome=ObservationOutcome.BLOCKED,
        summary="Dependency access is unavailable.",
        evidence={"blocker": "missing access"},
        occurred_at=NOW,
    )
    issues = registry.append_observation(
        observation_key="issues-1",
        source_job_id="issues-1",
        agent_name="coding_agent",
        lane="coding",
        outcome=ObservationOutcome.COMPLETED_WITH_ISSUES,
        summary="Code changed but readback was not possible.",
        evidence={"followup": "readback required"},
        occurred_at=NOW,
    )

    assert blocked.eligible_for_skill_proposal is False
    assert issues.eligible_for_skill_proposal is False
    assert registry.list_observations(eligible_for_skill_proposal=True) == []
    with pytest.raises(ValueError, match="completed_verified"):
        _candidate(registry, blocked.id)
    with pytest.raises(ValueError, match="verification_evidence"):
        registry.append_observation(
            observation_key="false-success",
            source_job_id="false-success",
            agent_name="coding_agent",
            lane="coding",
            outcome=ObservationOutcome.COMPLETED_VERIFIED,
            summary="Claimed success without proof.",
            occurred_at=NOW,
        )
    with pytest.raises(ValueError, match="reserved"):
        registry.append_observation(
            observation_key="blocked-with-proof",
            source_job_id="blocked-with-proof",
            agent_name="coding_agent",
            lane="coding",
            outcome=ObservationOutcome.BLOCKED,
            summary="Still blocked.",
            verification_evidence={"readback": True},
            occurred_at=NOW,
        )


def test_candidate_is_quarantined_versioned_and_cannot_broaden_capabilities(tmp_path):
    registry = _registry(tmp_path)
    observation = _verified_observation(registry)
    first = _candidate(
        registry,
        observation.id,
        instructions=f"Read the repository; never copy credential {SECRET}.",
        provenance={"proposer": "person@example.com"},
    )

    assert first.version == 1
    assert first.state is SkillCandidateState.DRAFT
    assert first.requested_capabilities == ("repo.read",)
    assert first.capability_ceiling == ("repo.read", "repo.write")
    assert len(first.capability_policy_hash) == 64
    assert len(first.content_hash) == 64
    assert SECRET not in first.instructions
    assert "person@example.com" not in str(first.provenance)

    with pytest.raises(ValueError, match="would broaden"):
        registry.propose_skill_candidate(
            skill_key="network-enabled-skill",
            owner_agent="coding_agent",
            owner_lane="coding",
            title="Unsafe proposal",
            description="Requests an unavailable capability.",
            instructions="Use the network.",
            requested_capabilities=["network.write"],
            source_observation_ids=[observation.id],
            created_by="learning-reviewer",
        )
    with pytest.raises(ValueError, match="parent's capabilities"):
        _candidate(
            registry,
            observation.id,
            instructions="Read and write the repository.",
            requested_capabilities=["repo.read", "repo.write"],
        )

    second = _candidate(
        registry,
        observation.id,
        instructions="Read the repository and prepare a report only.",
    )
    assert second.version == 2
    assert second.parent_candidate_id == first.id


def test_candidate_state_machine_requires_review_evidence_and_hash_chains_history(tmp_path):
    registry = _registry(tmp_path)
    observation = _verified_observation(registry)
    candidate = _candidate(registry, observation.id)

    with pytest.raises(ValueError, match="invalid"):
        registry.transition_candidate(
            candidate.id,
            SkillCandidateState.ACTIVE,
            actor="operator",
            rationale="skip review",
            evidence={"request": "activate"},
        )
    candidate = registry.transition_candidate(
        candidate.id,
        "evaluating",
        actor="evaluator",
        rationale="begin offline evaluation",
    )
    with pytest.raises(ValueError, match="requires evidence"):
        registry.transition_candidate(
            candidate.id,
            "approved",
            actor="reviewer",
            rationale="looks good",
        )
    candidate = registry.transition_candidate(
        candidate.id,
        "approved",
        actor="reviewer",
        rationale="evaluation passed",
        evidence={"evaluation_suite": "12/12"},
    )
    candidate = registry.transition_candidate(
        candidate.id,
        "canary",
        actor="operator",
        rationale="approved for bounded canary",
        evidence={"scope": "read-only shadow"},
    )
    candidate = registry.transition_candidate(
        candidate.id,
        "active",
        actor="operator",
        rationale="canary met success criteria",
        evidence={"canary_runs": 20, "regressions": 0},
    )

    assert candidate.state is SkillCandidateState.ACTIVE
    history = registry.candidate_history(candidate.id)
    assert [event.to_state for event in history] == [
        SkillCandidateState.DRAFT,
        SkillCandidateState.EVALUATING,
        SkillCandidateState.APPROVED,
        SkillCandidateState.CANARY,
        SkillCandidateState.ACTIVE,
    ]
    assert history[0].previous_event_hash is None
    assert all(
        history[index].previous_event_hash == history[index - 1].event_hash
        for index in range(1, len(history))
    )


def test_candidate_content_and_history_are_immutable_but_state_can_transition(tmp_path):
    registry = _registry(tmp_path)
    observation = _verified_observation(registry)
    candidate = _candidate(registry, observation.id)

    with sqlite3.connect(registry.sqlite_path) as db:
        with pytest.raises(sqlite3.IntegrityError, match="new version"):
            db.execute(
                "UPDATE learning_skill_candidates SET instructions='changed' WHERE id=?",
                (candidate.id,),
            )
        with pytest.raises(sqlite3.IntegrityError, match="cannot be deleted"):
            db.execute(
                "DELETE FROM learning_skill_candidates WHERE id=?", (candidate.id,)
            )
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            db.execute(
                "DELETE FROM learning_skill_transitions WHERE candidate_id=?",
                (candidate.id,),
            )
        with pytest.raises(sqlite3.IntegrityError, match="audited transition"):
            db.execute(
                "UPDATE learning_skill_candidates SET state='active' WHERE id=?",
                (candidate.id,),
            )

    changed = registry.transition_candidate(
        candidate.id,
        "retired",
        actor="reviewer",
        rationale="proposal is no longer needed",
    )
    assert changed.state is SkillCandidateState.RETIRED


def test_content_hash_detects_out_of_band_tampering(tmp_path):
    registry = _registry(tmp_path)
    observation = _verified_observation(registry)

    with sqlite3.connect(registry.sqlite_path) as db:
        db.execute("DROP TRIGGER learning_observations_no_update")
        db.execute(
            "UPDATE learning_observations SET summary='tampered' WHERE id=?",
            (observation.id,),
        )

    with pytest.raises(LearningIntegrityError, match="hash mismatch"):
        registry.get_observation(observation.id)


def test_registry_never_materializes_candidates_into_active_skill_directories(tmp_path):
    active_skills = tmp_path / "active-skills"
    active_skills.mkdir()
    sentinel = active_skills / "KEEP.txt"
    sentinel.write_text("unchanged", encoding="utf-8")
    registry = _registry(tmp_path)
    observation = _verified_observation(registry)
    candidate = _candidate(registry, observation.id)

    assert registry.get_candidate(candidate.id) == candidate
    assert [path.name for path in active_skills.iterdir()] == ["KEEP.txt"]
    assert sentinel.read_text(encoding="utf-8") == "unchanged"
