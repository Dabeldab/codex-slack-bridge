"""Conservative classification for final agent outcomes.

This module separates an agent's reported business outcome from transport-level
worker failures.  It intentionally does not infer success from otherwise
positive prose: a managed agent must lead its first non-empty line with one of
the supported outcome markers.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re


class AgentOutcomeStatus(str, Enum):
    """Normalized business outcomes emitted by managed agents."""

    COMPLETED = "completed"
    COMPLETED_WITH_ISSUES = "completed_with_issues"
    BLOCKED = "blocked"
    FAILED = "failed"
    UNCLASSIFIED = "unclassified"


@dataclass(frozen=True, slots=True)
class AgentOutcome:
    """A classified final response and its safe downstream dispositions."""

    status: AgentOutcomeStatus
    transport_failure: bool = False

    @property
    def normalized_status(self) -> str:
        """Return the stable string representation used by durable stores."""

        return self.status.value

    @property
    def business_success(self) -> bool:
        """Whether the response represents an unqualified business success."""

        return self.status is AgentOutcomeStatus.COMPLETED and not self.transport_failure

    @property
    def needs_review(self) -> bool:
        """Whether the result must remain visible for review or follow-up."""

        return not self.business_success

    @property
    def learning_eligible(self) -> bool:
        """Whether outcome status permits learning from the run.

        This is status-level eligibility only.  Callers must still require any
        workflow-specific readback or verification evidence before learning.
        """

        return self.business_success


# Keep the union of failure prefixes recognized by the Slack and Command Center
# runtimes.  They remain prefix matches to preserve the existing behavior.
TRANSPORT_FAILURE_PREFIXES = (
    "codex run failed",
    "codex could not complete",
    "codex run timed out",
    "claude run failed",
    "claude run timed out",
    "agent worker exceeded",
)


_OUTCOME_MARKER = re.compile(
    r"^(?P<status>COMPLETED_WITH_ISSUES|COMPLETED|BLOCKED|FAILED)"
    r"(?=$|[\s:;,.!?\u2013\u2014])",
    flags=re.IGNORECASE,
)
_AMBIGUOUS_COMPLETED_PREFIX = re.compile(
    r"^COMPLETED[\s-]+WITH[\s_-]+ISSUES\b",
    flags=re.IGNORECASE,
)
_COMPLETED_CONTRADICTION = re.compile(
    r"(?:\b(?:is|are|work|request|task)\s+not\s+"
    r"(?:fully\s+)?(?:complete|completed|finished|done)\b|"
    r"\b(?:work|request|task)\b.{0,80}\b"
    r"(?:still\s+(?:open|pending|incomplete|unfinished)|remain(?:s|ing)?\s+"
    r"(?:open|pending|incomplete|unfinished))\b|"
    r"\b(?:unable|failed)\s+to\s+(?:complete|finish)\b)",
    flags=re.IGNORECASE | re.DOTALL,
)


def first_nonempty_line(text: object) -> str:
    """Return the first non-empty stripped line from an arbitrary result."""

    return next((line.strip() for line in str(text or "").splitlines() if line.strip()), "")


def is_transport_failure(text: object) -> bool:
    """Return whether ``text`` begins with a known worker failure message."""

    first_line = first_nonempty_line(text).casefold()
    return any(first_line.startswith(prefix) for prefix in TRANSPORT_FAILURE_PREFIXES)


def classify_agent_outcome(text: object) -> AgentOutcome:
    """Classify a final agent response without guessing from narrative prose.

    A transport failure is always ``failed``.  Otherwise, only a supported
    marker at the start of the first non-empty line is accepted.  Missing,
    malformed, quoted, or merely mentioned markers remain ``unclassified`` so
    they cannot silently count as completion.
    """

    if is_transport_failure(text):
        return AgentOutcome(AgentOutcomeStatus.FAILED, transport_failure=True)

    first_line = first_nonempty_line(text)
    if _AMBIGUOUS_COMPLETED_PREFIX.match(first_line):
        return AgentOutcome(AgentOutcomeStatus.UNCLASSIFIED)

    match = _OUTCOME_MARKER.match(first_line)
    if match is None:
        return AgentOutcome(AgentOutcomeStatus.UNCLASSIFIED)

    status = AgentOutcomeStatus(match.group("status").casefold())
    if status is AgentOutcomeStatus.COMPLETED and _COMPLETED_CONTRADICTION.search(
        str(text or "")[:6000]
    ):
        return AgentOutcome(AgentOutcomeStatus.UNCLASSIFIED)
    return AgentOutcome(status)


__all__ = [
    "AgentOutcome",
    "AgentOutcomeStatus",
    "TRANSPORT_FAILURE_PREFIXES",
    "classify_agent_outcome",
    "first_nonempty_line",
    "is_transport_failure",
]
