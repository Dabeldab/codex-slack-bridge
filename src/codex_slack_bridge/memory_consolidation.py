"""Deterministic memory consolidation and curation proposals.

This module deliberately does not write memory.  It turns observations into
reviewable proposals that can be passed to :class:`MemoryStore` only when the
proposal is safe.  Keeping the decision layer pure makes consolidation easy to
replay, audit, and test.
"""

from __future__ import annotations

import math
import json
import re
import time
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Iterable, Mapping, Sequence


DAY_SECONDS = 24 * 60 * 60
TOKEN_RE = re.compile(r"[a-z0-9]+")
TEMPORAL_RE = re.compile(r"\b(today|tomorrow|this week|until|temporary|for now|currently)\b", re.I)
PREFERENCE_RE = re.compile(r"\b(i prefer|user prefers?|always wants?|do not|don't|avoid|default to)\b", re.I)
PROCEDURE_RE = re.compile(r"\b(workflow|runbook|procedure|steps?|first .+ then|when .+ (?:then|must))\b", re.I)


class MemoryKind(str, Enum):
    ONE_OFF = "one_off"
    SEMANTIC = "semantic"
    PROCEDURAL = "procedural"
    PREFERENCE = "preference"
    TEMPORARY = "temporary"


class ProposalAction(str, Enum):
    REMEMBER = "remember"
    SUPERSEDE = "supersede"
    CONFLICT_REVIEW = "conflict_review"
    REINFORCE = "reinforce"
    HOLD = "hold"


class Authority(str, Enum):
    DIRECT_USER = "direct_user"
    OPERATOR = "operator"
    VERIFIED_SYSTEM = "verified_system"
    TRUSTED_SOURCE = "trusted_source"
    AGENT_OBSERVATION = "agent_observation"
    UNVERIFIED = "unverified"


AUTHORITY_WEIGHT = {
    Authority.DIRECT_USER: 1.0,
    Authority.OPERATOR: 0.95,
    Authority.VERIFIED_SYSTEM: 0.90,
    Authority.TRUSTED_SOURCE: 0.80,
    Authority.AGENT_OBSERVATION: 0.55,
    Authority.UNVERIFIED: 0.30,
}


@dataclass(frozen=True)
class MemoryCandidate:
    text: str
    agent_name: str
    source: str
    topic: str = ""
    kind_hint: MemoryKind | str | None = None
    authority: Authority | str = Authority.AGENT_OBSERVATION
    confidence: float = 0.5
    occurrences: int = 1
    verified: bool = False
    high_risk: bool = False
    helpful_count: int = 0
    rehearsal_count: int = 0
    tags: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    correction_of: tuple[str, ...] = ()
    conflicts_with: tuple[str, ...] = ()
    expires_at: float | datetime | None = None
    source_version: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MemoryEpisode:
    """A completed task's proposed memories, kept together for provenance."""

    episode_id: str
    candidates: tuple[MemoryCandidate, ...]
    occurred_at: float | None = None


@dataclass(frozen=True)
class ConsolidationPolicy:
    min_confidence: float = 0.70
    min_authority: float = 0.55
    min_recurrence: int = 2
    preference_min_confidence: float = 0.70
    high_risk_min_confidence: float = 0.90
    one_off_ttl_days: int = 14
    temporary_ttl_days: int = 30
    max_temporary_ttl_days: int = 365
    inactive_decay_days: int = 180


@dataclass(frozen=True)
class MemoryProposal:
    action: ProposalAction
    kind: MemoryKind
    candidate: MemoryCandidate
    confidence: float
    importance: float
    reasons: tuple[str, ...]
    expires_at: float | None = None
    supersedes: tuple[str, ...] = ()
    conflicts_with: tuple[str, ...] = ()
    requires_review: bool = False

    @property
    def safe_to_apply(self) -> bool:
        return self.action in {ProposalAction.REMEMBER, ProposalAction.SUPERSEDE} and not self.requires_review

    def memory_store_operation(self) -> dict[str, Any] | None:
        """Return a call description for MemoryStore, or ``None`` if unsafe.

        Consumers should still decide when to execute the call.  A conflict,
        hold, or review-required proposal is intentionally not representable as
        a write operation.
        """

        if self.action == ProposalAction.REINFORCE:
            memory_id = str(self.candidate.metadata.get("existing_memory_id") or "").strip()
            if memory_id and self.candidate.helpful_count > 0:
                return {"method": "record_feedback", "kwargs": {"memory_id": memory_id, "helpful": True}}
            return None
        if not self.safe_to_apply:
            return None
        metadata = dict(self.candidate.metadata)
        metadata.update(
            {
                "memory_kind": self.kind.value,
                "consolidation_confidence": round(self.confidence, 6),
                "occurrences": self.candidate.occurrences,
                "rehearsal_count": self.candidate.rehearsal_count,
            }
        )
        if self.candidate.topic:
            metadata.setdefault("topic", self.candidate.topic)
        kwargs: dict[str, Any] = {
            "agent_name": self.candidate.agent_name,
            "text": self.candidate.text,
            "source": self.candidate.source,
            "tags": list(self.candidate.tags),
            "importance": self.importance,
            "source_version": self.candidate.source_version,
            "expires_at": self.expires_at,
            "metadata": metadata,
        }
        if self.action == ProposalAction.SUPERSEDE:
            kwargs["supersedes"] = list(self.supersedes)
        return {"method": "remember", "kwargs": kwargs}

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action.value,
            "kind": self.kind.value,
            "text": self.candidate.text,
            "agent_name": self.candidate.agent_name,
            "source": self.candidate.source,
            "topic": self.candidate.topic,
            "confidence": self.confidence,
            "importance": self.importance,
            "reasons": list(self.reasons),
            "expires_at": self.expires_at,
            "supersedes": list(self.supersedes),
            "conflicts_with": list(self.conflicts_with),
            "requires_review": self.requires_review,
            "safe_to_apply": self.safe_to_apply,
        }


@dataclass(frozen=True)
class RetentionDecision:
    action: str
    strength: float
    reason: str
    next_review_at: float | None = None


class MemoryConsolidator:
    def __init__(self, policy: ConsolidationPolicy | None = None) -> None:
        self.policy = policy or ConsolidationPolicy()

    def consolidate(
        self,
        items: Iterable[MemoryCandidate | MemoryEpisode],
        *,
        existing_memories: Iterable[Mapping[str, Any]] = (),
        now: float | None = None,
    ) -> list[MemoryProposal]:
        current_time = time.time() if now is None else float(now)
        candidates = self._flatten(items)
        grouped = self._deduplicate(candidates)
        existing = list(existing_memories)
        existing_by_text = {
            (str(row.get("agent_name", "")).lower(), _normalize_text(str(row.get("text", "")))): row
            for row in existing
            if row.get("text")
        }
        existing_by_topic: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
        for row in existing:
            topic = _existing_topic(row)
            if topic:
                existing_by_topic.setdefault((str(row.get("agent_name", "")).lower(), topic), []).append(row)

        proposals: list[MemoryProposal] = []
        topic_groups: dict[tuple[str, str], list[MemoryCandidate]] = {}
        for candidate in grouped:
            if candidate.topic and not candidate.correction_of:
                topic_groups.setdefault((candidate.agent_name.lower(), _normalize_topic(candidate.topic)), []).append(candidate)

        for candidate in grouped:
            exact = existing_by_text.get((candidate.agent_name.lower(), _normalize_text(candidate.text)))
            if exact is not None and self._is_unverified_high_risk(candidate):
                proposals.append(
                    self._proposal(
                        candidate,
                        ProposalAction.HOLD,
                        self.classify(candidate),
                        current_time,
                        ("unverified high-risk claims cannot strengthen existing memory",),
                        requires_review=True,
                    )
                )
                continue
            if exact is not None:
                proposals.append(self._reinforcement(candidate, exact))
                continue

            topic_key = (candidate.agent_name.lower(), _normalize_topic(candidate.topic))
            sibling_conflicts = [
                other for other in topic_groups.get(topic_key, ()) if _normalize_text(other.text) != _normalize_text(candidate.text)
            ]
            stored_conflicts = [
                row
                for row in existing_by_topic.get(topic_key, ())
                if _normalize_text(str(row.get("text", ""))) != _normalize_text(candidate.text)
            ]
            declared_conflicts = tuple(candidate.conflicts_with)
            discovered_conflicts = tuple(
                str(row.get("id")) for row in stored_conflicts if str(row.get("id") or "").strip()
            )

            if candidate.correction_of:
                proposals.append(self._correction_proposal(candidate, current_time))
            elif sibling_conflicts or stored_conflicts or declared_conflicts:
                conflicts = tuple(dict.fromkeys((*declared_conflicts, *discovered_conflicts)))
                proposals.append(
                    self._proposal(
                        candidate,
                        action=ProposalAction.CONFLICT_REVIEW,
                        kind=self.classify(candidate),
                        now=current_time,
                        reasons=("same topic has materially different guidance",),
                        conflicts_with=conflicts,
                        requires_review=True,
                    )
                )
            else:
                proposals.append(self._promotion_proposal(candidate, current_time))

        return sorted(proposals, key=_proposal_sort_key)

    def classify(self, candidate: MemoryCandidate) -> MemoryKind:
        if candidate.kind_hint is not None:
            try:
                return MemoryKind(str(candidate.kind_hint).lower())
            except ValueError:
                if isinstance(candidate.kind_hint, MemoryKind):
                    return candidate.kind_hint
        tags = {tag.strip().lower() for tag in candidate.tags}
        text = candidate.text.strip()
        if candidate.expires_at is not None or "temporary" in tags or TEMPORAL_RE.search(text):
            return MemoryKind.TEMPORARY
        if "preference" in tags or PREFERENCE_RE.search(text):
            return MemoryKind.PREFERENCE
        if "procedure" in tags or "workflow" in tags or PROCEDURE_RE.search(text):
            return MemoryKind.PROCEDURAL
        if candidate.occurrences >= self.policy.min_recurrence or candidate.verified or "fact" in tags:
            return MemoryKind.SEMANTIC
        return MemoryKind.ONE_OFF

    def retention_decision(self, record: Mapping[str, Any], *, now: float | None = None) -> RetentionDecision:
        """Assess whether an existing memory should be retained, decayed, or archived."""

        current_time = time.time() if now is None else float(now)
        if record.get("superseded_by") or int(record.get("stale_count") or 0) > 0:
            return RetentionDecision("archive", 0.0, "superseded or explicitly stale")
        expiry = _timestamp(record.get("expires_at"))
        if expiry is not None and expiry <= current_time:
            return RetentionDecision("archive", 0.0, "expired")

        helpful = int(record.get("helpful_count") or _feedback_value(record, "helpful"))
        unhelpful = int(record.get("unhelpful_count") or _feedback_value(record, "unhelpful"))
        rehearsal = int(record.get("rehearsal_count") or _metadata_value(record, "rehearsal_count") or 0)
        importance = _clamp(float(record.get("importance", 0.5)), 0.0, 1.0)
        strength = _clamp(importance + min(helpful, 5) * 0.06 + min(rehearsal, 8) * 0.025 - min(unhelpful, 5) * 0.10)
        last_used = _timestamp(record.get("last_rehearsed_at")) or _timestamp(record.get("updated_at"))
        last_used = last_used or _timestamp(record.get("created_at")) or current_time
        inactive_days = max(0.0, (current_time - last_used) / DAY_SECONDS)
        protected_days = self.policy.inactive_decay_days * (1.0 + min(helpful + rehearsal, 8) * 0.25)
        if unhelpful > helpful and inactive_days >= 30:
            return RetentionDecision("decay", strength, "unhelpful feedback outweighs helpful use", current_time)
        if inactive_days > protected_days and strength < 0.75:
            return RetentionDecision("decay", strength, "low-value memory has not been rehearsed", current_time)
        next_review = current_time + max(30, int(protected_days - inactive_days)) * DAY_SECONDS
        return RetentionDecision("retain", strength, "recent use or positive rehearsal supports retention", next_review)

    def _flatten(self, items: Iterable[MemoryCandidate | MemoryEpisode]) -> list[MemoryCandidate]:
        flattened: list[MemoryCandidate] = []
        for item in items:
            if isinstance(item, MemoryCandidate):
                flattened.append(item)
                continue
            if not isinstance(item, MemoryEpisode):
                raise TypeError(f"Unsupported consolidation item: {type(item).__name__}")
            for candidate in item.candidates:
                evidence = tuple(dict.fromkeys((*candidate.evidence_ids, item.episode_id)))
                metadata = dict(candidate.metadata)
                if item.occurred_at is not None:
                    metadata.setdefault("episode_occurred_at", item.occurred_at)
                flattened.append(replace(candidate, evidence_ids=evidence, metadata=metadata))
        return flattened

    def _deduplicate(self, candidates: Sequence[MemoryCandidate]) -> list[MemoryCandidate]:
        groups: dict[tuple[str, str, str], list[MemoryCandidate]] = {}
        for candidate in candidates:
            clean = candidate.text.strip()
            if not clean:
                continue
            key = (candidate.agent_name.lower(), candidate.source.lower(), _normalize_text(clean))
            groups.setdefault(key, []).append(replace(candidate, text=clean))

        merged: list[MemoryCandidate] = []
        for key in sorted(groups):
            rows = sorted(groups[key], key=_candidate_sort_key)
            authority = max((_authority(row.authority) for row in rows), key=lambda value: AUTHORITY_WEIGHT[value])
            total_occurrences = sum(max(1, row.occurrences) for row in rows)
            weighted_confidence = sum(_clamp(row.confidence) * max(1, row.occurrences) for row in rows) / total_occurrences
            base = rows[0]
            merged.append(
                replace(
                    base,
                    topic=next((row.topic for row in rows if row.topic), base.topic),
                    kind_hint=next((row.kind_hint for row in rows if row.kind_hint is not None), base.kind_hint),
                    authority=authority,
                    confidence=weighted_confidence,
                    occurrences=total_occurrences,
                    verified=any(row.verified for row in rows),
                    high_risk=any(row.high_risk for row in rows),
                    helpful_count=sum(max(0, row.helpful_count) for row in rows),
                    rehearsal_count=sum(max(0, row.rehearsal_count) for row in rows) + max(0, len(rows) - 1),
                    tags=tuple(sorted({tag.strip() for row in rows for tag in row.tags if tag.strip()})),
                    evidence_ids=tuple(sorted({eid.strip() for row in rows for eid in row.evidence_ids if eid.strip()})),
                    correction_of=tuple(sorted({mid.strip() for row in rows for mid in row.correction_of if mid.strip()})),
                    conflicts_with=tuple(sorted({mid.strip() for row in rows for mid in row.conflicts_with if mid.strip()})),
                    expires_at=_earliest_expiry(row.expires_at for row in rows),
                    metadata=_merge_metadata(rows),
                )
            )
        return merged

    def _promotion_proposal(self, candidate: MemoryCandidate, now: float) -> MemoryProposal:
        kind = self.classify(candidate)
        authority = _authority(candidate.authority)
        reasons: list[str] = []
        requires_recurrence = kind in {MemoryKind.SEMANTIC, MemoryKind.PROCEDURAL}
        recurrence_ok = candidate.occurrences >= self.policy.min_recurrence or candidate.verified
        preference_ok = kind != MemoryKind.PREFERENCE or (
            authority in {Authority.DIRECT_USER, Authority.OPERATOR} and candidate.confidence >= self.policy.preference_min_confidence
        ) or recurrence_ok

        if self._is_unverified_high_risk(candidate):
            reasons.append("unverified high-risk claims are never auto-promoted")
            return self._proposal(candidate, ProposalAction.HOLD, kind, now, tuple(reasons), requires_review=True)
        if candidate.confidence < self.policy.min_confidence:
            reasons.append("confidence is below the promotion threshold")
        if AUTHORITY_WEIGHT[authority] < self.policy.min_authority:
            reasons.append("source authority is below the promotion threshold")
        if requires_recurrence and not recurrence_ok:
            reasons.append("semantic or procedural guidance has not recurred or been verified")
        if not preference_ok:
            reasons.append("preference was not stated by the user/operator or repeated")
        if reasons:
            return self._proposal(candidate, ProposalAction.HOLD, kind, now, tuple(reasons), requires_review=True)

        reasons.append("candidate meets confidence, authority, and recurrence policy")
        return self._proposal(candidate, ProposalAction.REMEMBER, kind, now, tuple(reasons))

    def _correction_proposal(self, candidate: MemoryCandidate, now: float) -> MemoryProposal:
        promoted = self._promotion_proposal(candidate, now)
        if promoted.action != ProposalAction.REMEMBER:
            return replace(
                promoted,
                action=ProposalAction.CONFLICT_REVIEW,
                conflicts_with=candidate.correction_of,
                reasons=(*promoted.reasons, "correction is not sufficiently verified for supersession"),
                requires_review=True,
            )
        return replace(
            promoted,
            action=ProposalAction.SUPERSEDE,
            supersedes=tuple(dict.fromkeys(candidate.correction_of)),
            reasons=("explicit correction proposes atomic supersession", *promoted.reasons),
        )

    def _verified_high_risk(self, candidate: MemoryCandidate) -> bool:
        authority = _authority(candidate.authority)
        return (
            candidate.verified
            and candidate.confidence >= self.policy.high_risk_min_confidence
            and authority in {Authority.DIRECT_USER, Authority.OPERATOR, Authority.VERIFIED_SYSTEM}
        )

    def _is_unverified_high_risk(self, candidate: MemoryCandidate) -> bool:
        risk_tags = {tag.strip().lower().replace("-", "_") for tag in candidate.tags}
        high_risk = candidate.high_risk or bool(
            risk_tags & {"high_risk", "financial_write", "credential", "destructive"}
        )
        return high_risk and not self._verified_high_risk(candidate)

    def _reinforcement(self, candidate: MemoryCandidate, existing: Mapping[str, Any]) -> MemoryProposal:
        metadata = dict(candidate.metadata)
        metadata["existing_memory_id"] = str(existing.get("id") or "")
        reinforced = replace(candidate, metadata=metadata)
        return MemoryProposal(
            action=ProposalAction.REINFORCE,
            kind=self.classify(candidate),
            candidate=reinforced,
            confidence=_clamp(candidate.confidence),
            importance=self._importance(candidate),
            reasons=("exact existing memory was rehearsed; avoid a duplicate write",),
        )

    def _proposal(
        self,
        candidate: MemoryCandidate,
        action: ProposalAction,
        kind: MemoryKind,
        now: float,
        reasons: tuple[str, ...],
        *,
        conflicts_with: tuple[str, ...] = (),
        requires_review: bool = False,
    ) -> MemoryProposal:
        return MemoryProposal(
            action=action,
            kind=kind,
            candidate=candidate,
            confidence=_clamp(candidate.confidence),
            importance=self._importance(candidate),
            reasons=reasons,
            expires_at=self._expiry(candidate, kind, now),
            conflicts_with=conflicts_with,
            requires_review=requires_review,
        )

    def _importance(self, candidate: MemoryCandidate) -> float:
        authority = AUTHORITY_WEIGHT[_authority(candidate.authority)]
        recurrence = min(1.0, math.log2(max(1, candidate.occurrences) + 1) / 3.0)
        feedback = min(candidate.helpful_count, 5) * 0.04 + min(candidate.rehearsal_count, 8) * 0.02
        return round(_clamp(0.40 * candidate.confidence + 0.30 * authority + 0.20 * recurrence + feedback), 6)

    def _expiry(self, candidate: MemoryCandidate, kind: MemoryKind, now: float) -> float | None:
        explicit = _timestamp(candidate.expires_at)
        if explicit is not None:
            return min(explicit, now + self.policy.max_temporary_ttl_days * DAY_SECONDS)
        strengthening = 1.0 + min(candidate.helpful_count, 4) * 0.75 + min(candidate.rehearsal_count, 4) * 0.50
        if kind == MemoryKind.ONE_OFF:
            return now + self.policy.one_off_ttl_days * strengthening * DAY_SECONDS
        if kind == MemoryKind.TEMPORARY:
            return now + self.policy.temporary_ttl_days * strengthening * DAY_SECONDS
        return None


def _normalize_text(text: str) -> str:
    return " ".join(TOKEN_RE.findall(text.lower()))


def _normalize_topic(topic: str) -> str:
    return _normalize_text(topic)


def _authority(value: Authority | str) -> Authority:
    if isinstance(value, Authority):
        return value
    try:
        return Authority(str(value).lower())
    except ValueError:
        return Authority.UNVERIFIED


def _timestamp(value: Any) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        dt = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _earliest_expiry(values: Iterable[Any]) -> float | None:
    expiries = [timestamp for value in values if (timestamp := _timestamp(value)) is not None]
    return min(expiries) if expiries else None


def _candidate_sort_key(candidate: MemoryCandidate) -> tuple[Any, ...]:
    return (
        -AUTHORITY_WEIGHT[_authority(candidate.authority)],
        -int(candidate.verified),
        -candidate.confidence,
        candidate.text.lower(),
        candidate.topic.lower(),
        str(candidate.source_version or ""),
        tuple(sorted(candidate.evidence_ids)),
        json.dumps(dict(candidate.metadata), sort_keys=True, default=str, separators=(",", ":")),
    )


def _proposal_sort_key(proposal: MemoryProposal) -> tuple[Any, ...]:
    return (
        proposal.candidate.agent_name.lower(),
        _normalize_topic(proposal.candidate.topic),
        _normalize_text(proposal.candidate.text),
        proposal.action.value,
    )


def _merge_metadata(rows: Sequence[MemoryCandidate]) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for row in reversed(rows):
        merged.update(dict(row.metadata))
    return merged


def _existing_topic(row: Mapping[str, Any]) -> str:
    metadata = row.get("metadata")
    if not isinstance(metadata, Mapping):
        metadata = {}
    return _normalize_topic(str(metadata.get("topic") or metadata.get("conflict_key") or row.get("topic") or ""))


def _metadata_value(record: Mapping[str, Any], key: str) -> Any:
    metadata = record.get("metadata")
    return metadata.get(key) if isinstance(metadata, Mapping) else None


def _feedback_value(record: Mapping[str, Any], key: str) -> Any:
    feedback = record.get("feedback")
    return feedback.get(key) if isinstance(feedback, Mapping) else 0


def _clamp(value: float, minimum: float = 0.0, maximum: float = 1.0) -> float:
    return max(minimum, min(maximum, float(value)))
