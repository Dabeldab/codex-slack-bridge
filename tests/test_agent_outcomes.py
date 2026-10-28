import pytest

from codex_slack_bridge.agent_outcomes import (
    AgentOutcomeStatus,
    TRANSPORT_FAILURE_PREFIXES,
    classify_agent_outcome,
    is_transport_failure,
)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("COMPLETED", AgentOutcomeStatus.COMPLETED),
        ("completed: verified", AgentOutcomeStatus.COMPLETED),
        ("CoMpLeTeD — verified", AgentOutcomeStatus.COMPLETED),
        ("\n  COMPLETED\nDetails", AgentOutcomeStatus.COMPLETED),
        ("COMPLETED_WITH_ISSUES", AgentOutcomeStatus.COMPLETED_WITH_ISSUES),
        ("completed_with_issues - follow-up remains", AgentOutcomeStatus.COMPLETED_WITH_ISSUES),
        ("BLOCKED: credential missing", AgentOutcomeStatus.BLOCKED),
        ("failed. No safe path remains.", AgentOutcomeStatus.FAILED),
    ],
)
def test_classifies_exact_or_leading_outcome_marker_case_insensitively(text, expected):
    outcome = classify_agent_outcome(text)

    assert outcome.status is expected
    assert outcome.normalized_status == expected.value
    assert outcome.transport_failure is False


@pytest.mark.parametrize(
    "text",
    [
        "",
        None,
        "The task is COMPLETED.",
        "Result: BLOCKED",
        "COMPLETEDLY",
        "COMPLETED_WITH_ISSUES_RETRYING",
        "COMPLETED WITH ISSUES",
        "COMPLETED-WITH-ISSUES",
        "FAILEDOVER",
        "**COMPLETED**",
        '"BLOCKED" because access is missing',
    ],
)
def test_ambiguous_or_nonleading_markers_remain_unclassified(text):
    outcome = classify_agent_outcome(text)

    assert outcome.status is AgentOutcomeStatus.UNCLASSIFIED
    assert outcome.business_success is False
    assert outcome.needs_review is True
    assert outcome.learning_eligible is False


@pytest.mark.parametrize("prefix", TRANSPORT_FAILURE_PREFIXES)
def test_preserves_known_transport_failure_prefixes(prefix):
    text = f"\n{prefix.upper()} after 300 seconds.\nDiagnostic details"

    assert is_transport_failure(text) is True
    outcome = classify_agent_outcome(text)
    assert outcome.status is AgentOutcomeStatus.FAILED
    assert outcome.transport_failure is True
    assert outcome.business_success is False
    assert outcome.needs_review is True
    assert outcome.learning_eligible is False


@pytest.mark.parametrize(
    ("marker", "business_success", "needs_review", "learning_eligible"),
    [
        ("COMPLETED", True, False, True),
        ("COMPLETED_WITH_ISSUES", False, True, False),
        ("BLOCKED", False, True, False),
        ("FAILED", False, True, False),
        ("No explicit outcome", False, True, False),
    ],
)
def test_safe_downstream_dispositions(
    marker,
    business_success,
    needs_review,
    learning_eligible,
):
    outcome = classify_agent_outcome(marker)

    assert outcome.business_success is business_success
    assert outcome.needs_review is needs_review
    assert outcome.learning_eligible is learning_eligible


def test_transport_failure_detection_does_not_search_later_narrative():
    text = "COMPLETED — verified\nA prior Codex run timed out before this retry."

    assert is_transport_failure(text) is False
    assert classify_agent_outcome(text).status is AgentOutcomeStatus.COMPLETED


@pytest.mark.parametrize(
    "text",
    [
        "COMPLETED\nNo. The work is not complete yet. Tickets 347488 and 347464 are still open.",
        "COMPLETED: summary\nThe request remains pending with the receiving lane.",
        "COMPLETED\nWe were unable to finish the task.",
    ],
)
def test_completed_marker_is_rejected_when_narrative_explicitly_says_work_is_incomplete(text):
    outcome = classify_agent_outcome(text)

    assert outcome.status is AgentOutcomeStatus.UNCLASSIFIED
    assert outcome.business_success is False
    assert outcome.needs_review is True
    assert outcome.learning_eligible is False


def test_completed_marker_allows_historical_incomplete_attempt_when_current_run_is_verified():
    outcome = classify_agent_outcome(
        "COMPLETED\nThe prior attempt was not complete; this run is now verified."
    )

    assert outcome.status is AgentOutcomeStatus.COMPLETED
    assert outcome.business_success is True


def test_completed_read_only_investigation_may_leave_business_ticket_open():
    outcome = classify_agent_outcome(
        "COMPLETED Ticket 347073 remains open for Development Service planning. "
        "The read-only investigation is complete and no writes were made."
    )

    assert outcome.status is AgentOutcomeStatus.COMPLETED
    assert outcome.business_success is True
