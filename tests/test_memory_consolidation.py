from datetime import datetime, timezone

from codex_slack_bridge.memory_consolidation import (
    Authority,
    MemoryCandidate,
    MemoryConsolidator,
    MemoryEpisode,
    MemoryKind,
    ProposalAction,
)


NOW = 1_800_000_000.0


def candidate(text: str, **overrides):
    values = {
        "text": text,
        "agent_name": "general",
        "source": "task-journal",
        "confidence": 0.85,
        "authority": Authority.TRUSTED_SOURCE,
    }
    values.update(overrides)
    return MemoryCandidate(**values)


def test_repeated_candidates_are_deduplicated_and_promoted_deterministically():
    consolidator = MemoryConsolidator()
    first = candidate(
        "Maxio reads must precede billing mutations.",
        topic="maxio-write-safety",
        confidence=0.80,
        evidence_ids=("episode-b",),
    )
    second = candidate(
        " maxio reads must precede billing mutations! ",
        topic="maxio-write-safety",
        confidence=0.90,
        authority=Authority.VERIFIED_SYSTEM,
        evidence_ids=("episode-a",),
    )

    forward = consolidator.consolidate([first, second], now=NOW)
    reverse = consolidator.consolidate([second, first], now=NOW)

    assert [proposal.to_dict() for proposal in forward] == [proposal.to_dict() for proposal in reverse]
    assert len(forward) == 1
    proposal = forward[0]
    assert proposal.action == ProposalAction.REMEMBER
    assert proposal.kind == MemoryKind.SEMANTIC
    assert proposal.candidate.occurrences == 2
    assert proposal.candidate.rehearsal_count == 1
    assert proposal.candidate.evidence_ids == ("episode-a", "episode-b")
    operation = proposal.memory_store_operation()
    assert operation["method"] == "remember"
    assert operation["kwargs"]["metadata"]["occurrences"] == 2


def test_episode_provenance_is_added_without_changing_source_candidate():
    item = candidate("The customer requested CSV output.", authority=Authority.DIRECT_USER)
    episode = MemoryEpisode("job-42", (item,), occurred_at=NOW - 60)

    proposal = MemoryConsolidator().consolidate([episode], now=NOW)[0]

    assert proposal.candidate.evidence_ids == ("job-42",)
    assert proposal.candidate.metadata["episode_occurred_at"] == NOW - 60
    assert item.evidence_ids == ()


def test_unverified_high_risk_fact_is_never_auto_promoted_even_when_repeated():
    item = candidate(
        "Refunding this subscription is always safe.",
        high_risk=True,
        occurrences=20,
        confidence=1.0,
        authority=Authority.UNVERIFIED,
    )

    proposal = MemoryConsolidator().consolidate([item], now=NOW)[0]

    assert proposal.action == ProposalAction.HOLD
    assert proposal.requires_review is True
    assert proposal.safe_to_apply is False
    assert proposal.memory_store_operation() is None
    assert "high-risk" in " ".join(proposal.reasons)


def test_verified_high_risk_fact_requires_strong_authority_and_confidence():
    item = candidate(
        "Verified billing preview is required before a refund.",
        high_risk=True,
        verified=True,
        confidence=0.96,
        authority=Authority.VERIFIED_SYSTEM,
    )

    proposal = MemoryConsolidator().consolidate([item], now=NOW)[0]

    assert proposal.action == ProposalAction.REMEMBER
    assert proposal.safe_to_apply is True


def test_explicit_verified_correction_proposes_atomic_supersession():
    correction = candidate(
        "Use the Topic column for tracker topics.",
        topic="tracker-topic-column",
        kind_hint=MemoryKind.PREFERENCE,
        authority=Authority.DIRECT_USER,
        confidence=0.99,
        verified=True,
        correction_of=("old-memory",),
    )

    proposal = MemoryConsolidator().consolidate([correction], now=NOW)[0]
    operation = proposal.memory_store_operation()

    assert proposal.action == ProposalAction.SUPERSEDE
    assert proposal.supersedes == ("old-memory",)
    assert operation["method"] == "remember"
    assert operation["kwargs"]["supersedes"] == ["old-memory"]


def test_uncertain_correction_becomes_conflict_review_not_write():
    correction = candidate(
        "Skip billing readback checks.",
        topic="billing-readback",
        confidence=0.45,
        authority=Authority.AGENT_OBSERVATION,
        correction_of=("verified-rule",),
    )

    proposal = MemoryConsolidator().consolidate([correction], now=NOW)[0]

    assert proposal.action == ProposalAction.CONFLICT_REVIEW
    assert proposal.conflicts_with == ("verified-rule",)
    assert proposal.requires_review is True
    assert proposal.memory_store_operation() is None


def test_different_guidance_for_same_topic_proposes_conflict_review():
    existing = [
        {
            "id": "current-rule",
            "agent_name": "general",
            "text": "Poll every two hours.",
            "metadata": {"topic": "card-email-frequency"},
        }
    ]
    new = candidate("Poll every five minutes.", topic="card-email-frequency", occurrences=3)

    proposal = MemoryConsolidator().consolidate([new], existing_memories=existing, now=NOW)[0]

    assert proposal.action == ProposalAction.CONFLICT_REVIEW
    assert proposal.conflicts_with == ("current-rule",)
    assert proposal.safe_to_apply is False


def test_temporary_and_one_off_memories_expire_while_durable_memory_does_not():
    explicit_expiry = datetime.fromtimestamp(NOW + 3600, timezone.utc)
    items = [
        candidate("For now use the staging endpoint.", expires_at=explicit_expiry),
        candidate("Customer requested a one-time export."),
        candidate("Verified account identifiers are exact-match keys.", verified=True),
    ]

    proposals = {proposal.kind: proposal for proposal in MemoryConsolidator().consolidate(items, now=NOW)}

    assert proposals[MemoryKind.TEMPORARY].expires_at == NOW + 3600
    assert proposals[MemoryKind.ONE_OFF].expires_at == NOW + 14 * 86400
    assert proposals[MemoryKind.SEMANTIC].expires_at is None


def test_rehearsal_and_helpful_feedback_strengthen_importance_and_retention():
    consolidator = MemoryConsolidator()
    weak = candidate("Use readback verification.", occurrences=2)
    strong = candidate(
        "Use readback verification.",
        occurrences=2,
        helpful_count=3,
        rehearsal_count=4,
    )

    weak_proposal = consolidator.consolidate([weak], now=NOW)[0]
    strong_proposal = consolidator.consolidate([strong], now=NOW)[0]
    old_timestamp = NOW - 250 * 86400
    weak_retention = consolidator.retention_decision(
        {"importance": 0.4, "updated_at": old_timestamp}, now=NOW
    )
    strong_retention = consolidator.retention_decision(
        {
            "importance": 0.4,
            "updated_at": old_timestamp,
            "helpful_count": 4,
            "rehearsal_count": 4,
        },
        now=NOW,
    )

    assert strong_proposal.importance > weak_proposal.importance
    assert weak_retention.action == "decay"
    assert strong_retention.action == "retain"
    assert strong_retention.strength > weak_retention.strength


def test_exact_existing_memory_becomes_reinforcement_without_duplicate_write():
    item = candidate("Use read-only discovery first.", helpful_count=1)
    existing = [{"id": "memory-7", "agent_name": "general", "text": "Use read-only discovery first!"}]

    proposal = MemoryConsolidator().consolidate([item], existing_memories=existing, now=NOW)[0]

    assert proposal.action == ProposalAction.REINFORCE
    assert proposal.memory_store_operation() == {
        "method": "record_feedback",
        "kwargs": {"memory_id": "memory-7", "helpful": True},
    }


def test_unverified_high_risk_repetition_cannot_strengthen_existing_memory():
    item = candidate(
        "Refunding without preview is safe.",
        tags=("financial_write",),
        helpful_count=4,
        authority=Authority.UNVERIFIED,
    )
    existing = [{"id": "memory-8", "agent_name": "general", "text": item.text}]

    proposal = MemoryConsolidator().consolidate([item], existing_memories=existing, now=NOW)[0]

    assert proposal.action == ProposalAction.HOLD
    assert proposal.memory_store_operation() is None


def test_expired_or_superseded_records_are_archived_by_retention_policy():
    consolidator = MemoryConsolidator()

    assert consolidator.retention_decision({"expires_at": NOW - 1}, now=NOW).action == "archive"
    assert consolidator.retention_decision({"superseded_by": "new"}, now=NOW).action == "archive"
