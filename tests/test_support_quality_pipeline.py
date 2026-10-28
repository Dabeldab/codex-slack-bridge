from __future__ import annotations

import copy
import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from codex_slack_bridge import command_center_server
from codex_slack_bridge.command_center_server import (
    CommandCenterRuntime,
    THOR_SUPPORT_QUALITY_MEASURES,
    _build_weekly_support_quality_publication,
    _extract_thor_support_quality_result,
    _load_weekly_support_quality_roster,
    _unavailable_thor_ticket_projection,
    _validate_thor_ticket_projection_receipt,
    _validate_thor_support_quality_result,
    _validated_weekly_support_quality_window,
    _verify_weekly_support_quality_publication,
    _weekly_support_quality_completion_result,
    _weekly_support_quality_prior_summaries,
    _weekly_support_quality_publication_matches,
    _weekly_support_quality_window_key,
    _write_weekly_support_quality_watch_attempt_state,
    _write_weekly_support_quality_watch_verified_state,
    build_ops_weekly_support_quality_prompt,
)


ROSTER_PATH = Path("config/zoom-weekly-support-agents.json")


def _window(
    start: str = "2026-07-14T04:00:00+00:00",
    end: str = "2026-07-21T04:00:00+00:00",
) -> dict:
    return _validated_weekly_support_quality_window(
        start_utc=start,
        end_utc=end,
        timezone_name="America/New_York",
        now=datetime(2026, 7, 28, 18, tzinfo=timezone.utc),
    )


def _result(
    window: dict,
    roster: list[dict[str, str]],
    *,
    status: str = "complete",
    ticket_projection: dict | None = None,
) -> dict:
    blocked = status == "blocked"
    partial = status == "partial"
    projection = ticket_projection or (
        _unavailable_thor_ticket_projection(window=window, roster=roster)
        if blocked
        else _ticket_projection(window, roster)
    )
    projection_by_id = {
        item["id"]: item for item in projection["representatives"]
    }
    representatives = []
    for index, identity in enumerate(roster):
        ticket_refs = projection_by_id[identity["id"]]["evidenceReferences"]
        sample_count = 0 if blocked else 1 + len(ticket_refs)
        evidence = [] if blocked else [f"zoom:eng-{index + 1}", *ticket_refs]
        representatives.append(
            {
                **identity,
                "auditedSampleCount": sample_count,
                "measures": {
                    name: {
                        "score": None if blocked else 4.0,
                        "sampleSize": sample_count,
                    }
                    for name in THOR_SUPPORT_QUALITY_MEASURES
                },
                "strengths": [] if blocked else ["Explains the next step clearly"],
                "coachingGaps": [],
                "evidenceReferences": evidence,
            }
        )
    if blocked:
        coverage = {
            "zoomEngagementCount": 0,
            "zoomTranscriptAvailableCount": 0,
            "zoomTranscriptAuditedCount": 0,
            "zoomMissingTranscriptCount": 0,
            "rescueSessionCount": 0,
            "rescueSessionAuditedCount": 0,
            "salesforceTicketCount": 0,
            "salesforceMappedTicketCount": 0,
            "salesforceUnmappedTicketCount": 0,
            "salesforceTicketAuditedCount": 0,
            "sourceGaps": [
                "Zoom quality evidence was unavailable",
                "Rescue quality evidence was unavailable",
                *projection["sourceGaps"],
            ],
        }
        source_health = {
            "zoom": {
                "state": "unavailable",
                "gaps": ["Zoom quality evidence was unavailable"],
            },
            "rescue": {
                "state": "unavailable",
                "gaps": ["Rescue quality evidence was unavailable"],
            },
            "salesforce": {
                "state": projection["status"],
                "gaps": projection["sourceGaps"],
            },
        }
        agenda = []
    elif partial:
        coverage = {
            "zoomEngagementCount": 6,
            "zoomTranscriptAvailableCount": 5,
            "zoomTranscriptAuditedCount": 5,
            "zoomMissingTranscriptCount": 1,
            "rescueSessionCount": 1,
            "rescueSessionAuditedCount": 1,
            "salesforceTicketCount": projection["coverage"]["ticketCount"],
            "salesforceMappedTicketCount": projection["coverage"]["mappedTicketCount"],
            "salesforceUnmappedTicketCount": projection["coverage"]["unmappedTicketCount"],
            "salesforceTicketAuditedCount": projection["coverage"]["mappedTicketCount"],
            "sourceGaps": [
                "One Zoom transcript was unavailable",
                *projection["sourceGaps"],
            ],
        }
        source_health = {
            "zoom": {
                "state": "degraded",
                "gaps": ["One Zoom transcript was unavailable"],
            },
            "rescue": {"state": "ok", "gaps": []},
            "salesforce": {
                "state": projection["status"],
                "gaps": projection["sourceGaps"],
            },
        }
        agenda = [
            {
                "order": 1,
                "topic": "Troubleshooting consistency",
                "objective": "Agree on the diagnostic sequence for the support team",
                "evidenceReferences": ["zoom:eng-1"],
            }
        ]
    else:
        coverage = {
            "zoomEngagementCount": 6,
            "zoomTranscriptAvailableCount": 6,
            "zoomTranscriptAuditedCount": 6,
            "zoomMissingTranscriptCount": 0,
            "rescueSessionCount": 0,
            "rescueSessionAuditedCount": 0,
            "salesforceTicketCount": projection["coverage"]["ticketCount"],
            "salesforceMappedTicketCount": projection["coverage"]["mappedTicketCount"],
            "salesforceUnmappedTicketCount": projection["coverage"]["unmappedTicketCount"],
            "salesforceTicketAuditedCount": projection["coverage"]["mappedTicketCount"],
            "sourceGaps": list(projection["sourceGaps"]),
        }
        source_health = {
            "zoom": {"state": "ok", "gaps": []},
            "rescue": {"state": "ok", "gaps": []},
            "salesforce": {
                "state": projection["status"],
                "gaps": projection["sourceGaps"],
            },
        }
        agenda = [
            {
                "order": 1,
                "topic": "Troubleshooting consistency",
                "objective": "Confirm the diagnostic sequence used by the support team",
                "evidenceReferences": ["zoom:eng-1"],
            }
        ]
    return {
        "schemaVersion": 1,
        "status": status,
        "window": {
            "startUtc": window["startUtc"],
            "endUtc": window["endUtc"],
        },
        "coverage": coverage,
        "representatives": representatives,
        "unresolvedTopics": [],
        "knowledgeGaps": [],
        "professionalismGaps": [],
        "agenda": agenda,
        "sourceHealth": source_health,
    }


def _ticket_projection(
    window: dict,
    roster: list[dict[str, str]],
) -> dict:
    representatives = []
    for index, identity in enumerate(roster):
        reference = f"ticket:{index + 1:024x}"
        representatives.append(
            {
                **identity,
                "ticketCount": 1,
                "openCount": 0,
                "closedCount": 1,
                "closureMetadataPresentCount": 1,
                "documentationPresentCount": 1,
                "categoryPresentCount": 1,
                "missingDocumentationCount": 0,
                "missingCategoryCount": 0,
                "attributionCounts": {
                    "ticketCreatedBy": 1,
                    "ticketClosedBy": 1,
                    "owner": 1,
                    "createdBy": 1,
                },
                "issueCategories": ["classicMain:present"],
                "evidenceReferences": [reference],
            }
        )
    return {
        "schemaVersion": 1,
        "status": "ok",
        "source": "nova-runtime:typed-salesforce-support-quality-ticket-projection",
        "window": {
            "startUtc": window["startUtc"],
            "endUtc": window["endUtc"],
        },
        "recordTypes": ["1. NOVA Classic", "2. Nova Wave"],
        "coverage": {
            "ticketCount": 6,
            "mappedTicketCount": 6,
            "unmappedTicketCount": 0,
            "discardedSourceRowCount": 0,
            "representativesCoveredCount": 6,
            "rowLimitReached": False,
        },
        "representatives": representatives,
        "sourceGaps": [],
        "readOnly": True,
        "writesPerformed": False,
    }


def _ticket_projection_receipt(
    window: dict,
    roster: list[dict[str, str]],
) -> dict:
    projection = _ticket_projection(window, roster)
    return {
        "ok": True,
        "action": "read_support_quality_ticket_projection",
        "source": projection["source"],
        "window": projection["window"],
        "recordTypes": projection["recordTypes"],
        "coverage": projection["coverage"],
        "representatives": projection["representatives"],
        "readOnly": True,
        "writesPerformed": False,
    }


def test_default_weekly_support_quality_window_is_completed_local_week():
    window = _validated_weekly_support_quality_window(
        timezone_name="America/New_York",
        now=datetime(2026, 7, 28, 18, tzinfo=timezone.utc),
    )

    assert window["startDate"] == "2026-07-21"
    assert window["endDate"] == "2026-07-28"
    assert window["startUtc"] == "2026-07-21T04:00:00+00:00"
    assert window["endUtc"] == "2026-07-28T04:00:00+00:00"


def test_gateway_ticket_projection_receipt_is_exact_roster_opaque_and_sanitized():
    roster = _load_weekly_support_quality_roster(ROSTER_PATH)
    window = _window()
    normalized = _validate_thor_ticket_projection_receipt(
        _ticket_projection_receipt(window, roster),
        expected_window=window,
        expected_roster=roster,
    )

    assert normalized == _ticket_projection(window, roster)
    rendered = json.dumps(normalized)
    assert "ticket:000000000000000000000001" in rendered
    assert "NovaPOS_Ticket__c" not in rendered
    assert "Description__c" not in rendered
    assert "customer@example.com" not in rendered


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: value["coverage"].update({"mappedTicketCount": 5}),
        lambda value: value["representatives"][0].update(
            {"name": "Different Representative"}
        ),
        lambda value: value["representatives"][0].update(
            {"evidenceReferences": ["ticket:a0G000000000001AAA"]}
        ),
        lambda value: value["representatives"][0].update(
            {"issueCategories": ["classicMain:Customer Name"]}
        ),
        lambda value: value.update({"customer": "Private Customer"}),
        lambda value: value.update({"writesPerformed": True}),
    ],
)
def test_gateway_ticket_projection_receipt_rejects_spoofing_or_raw_data(mutate):
    roster = _load_weekly_support_quality_roster(ROSTER_PATH)
    window = _window()
    receipt = _ticket_projection_receipt(window, roster)
    mutate(receipt)

    with pytest.raises(ValueError):
        _validate_thor_ticket_projection_receipt(
            receipt,
            expected_window=window,
            expected_roster=roster,
        )


def test_command_center_invokes_runtime_only_projection_with_exact_server_input(
    monkeypatch,
):
    roster = _load_weekly_support_quality_roster(ROSTER_PATH)
    window = _window()
    runtime = object.__new__(CommandCenterRuntime)
    runtime.config = SimpleNamespace(
        defaults={
            "ops_weekly_support_quality_salesforce_projection_executor":
                "/opt/nova/bin/run-salesforce-support-quality-projection"
        }
    )
    captured = {}

    def run(command, **kwargs):
        captured["command"] = command
        captured["payload"] = json.loads(kwargs["input"])
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps(_ticket_projection_receipt(window, roster)),
            stderr="",
        )

    monkeypatch.setattr(command_center_server.subprocess, "run", run)

    projection = runtime._read_weekly_support_quality_ticket_projection(
        window=window,
        roster=roster,
    )

    assert captured["command"] == [
        "/usr/bin/sudo",
        "-n",
        "-H",
        "-u",
        "nova-salesforce-broker",
        "--",
        "/opt/nova/bin/run-salesforce-support-quality-projection",
    ]
    assert captured["payload"] == {
        "action": "read_support_quality_ticket_projection",
        "startUtc": window["startUtc"],
        "endUtc": window["endUtc"],
        "roster": roster,
    }
    assert projection == _ticket_projection(window, roster)


def test_command_center_projection_failure_becomes_sanitized_unavailable_gap(
    monkeypatch,
):
    roster = _load_weekly_support_quality_roster(ROSTER_PATH)
    window = _window()
    runtime = object.__new__(CommandCenterRuntime)
    runtime.config = SimpleNamespace(
        defaults={
            "ops_weekly_support_quality_salesforce_projection_executor":
                "/opt/nova/bin/run-salesforce-support-quality-projection"
        }
    )
    monkeypatch.setattr(
        command_center_server.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=1,
            stdout='{"ok":false,"errorType":"SalesforceUnavailableError"}',
            stderr="provider response with customer@example.com",
        ),
    )

    projection = runtime._read_weekly_support_quality_ticket_projection(
        window=window,
        roster=roster,
    )

    assert projection == _unavailable_thor_ticket_projection(
        window=window,
        roster=roster,
    )
    assert "customer@example.com" not in json.dumps(projection)


@pytest.mark.parametrize(
    ("start", "end"),
    [
        ("", "2026-07-21T04:00:00+00:00"),
        ("2026-07-15T04:00:00+00:00", "2026-07-21T04:00:00+00:00"),
        ("2026-07-14T05:00:00+00:00", "2026-07-21T04:00:00+00:00"),
        ("2026-07-21T04:00:00+00:00", "2026-07-14T04:00:00+00:00"),
    ],
)
def test_weekly_support_quality_window_rejects_unbounded_ranges(start, end):
    with pytest.raises(ValueError):
        _validated_weekly_support_quality_window(
            start_utc=start,
            end_utc=end,
            timezone_name="America/New_York",
            now=datetime(2026, 7, 28, 18, tzinfo=timezone.utc),
        )


def test_roster_and_prompt_are_fixed_read_only_contract():
    roster = _load_weekly_support_quality_roster(ROSTER_PATH)
    window = _window()
    prompt = build_ops_weekly_support_quality_prompt(
        window=window,
        roster=roster,
        prior_summaries=[],
        ticket_projection=_ticket_projection(window, roster),
    )

    assert len(roster) == 6
    assert "Support Dashboard Calls" in prompt
    assert "Return exactly one single-line marker" in prompt
    assert "Do not work tickets" in prompt
    assert "zoom_quality_transcript" in prompt
    assert "rescue_read_chat" in prompt
    assert "Gateway-supplied sanitized Salesforce" in prompt
    assert "ticket:000000000000000000000001" in prompt
    assert "never attempt a ticket lookup" in prompt


def test_valid_complete_result_is_published_verified_and_compacted():
    roster = _load_weekly_support_quality_roster(ROSTER_PATH)
    window = _window()
    raw = _result(window, roster)
    line = "THOR_SUPPORT_QUALITY_RESULT: " + json.dumps(raw, separators=(",", ":"))

    extracted = _extract_thor_support_quality_result(line)
    normalized = _validate_thor_support_quality_result(
        extracted,
        expected_window=window,
        expected_roster=roster,
        expected_ticket_projection=_ticket_projection(window, roster),
    )
    publication = _build_weekly_support_quality_publication(
        normalized,
        previous={},
        job_key="job-1",
        idempotency_key="ops-weekly-support-quality:test-1",
        history_limit=8,
    )

    _verify_weekly_support_quality_publication(publication)
    assert _weekly_support_quality_publication_matches(
        publication,
        _weekly_support_quality_window_key(window),
    )
    completion = _weekly_support_quality_completion_result(publication)
    assert completion.startswith("COMPLETED\n")
    assert "Troubleshooting consistency" in completion
    assert line not in json.dumps(publication)


@pytest.mark.parametrize("status", ["partial", "blocked"])
def test_partial_and_blocked_results_map_to_deterministic_outcomes(status):
    roster = _load_weekly_support_quality_roster(ROSTER_PATH)
    window = _window()
    projection = (
        _unavailable_thor_ticket_projection(window=window, roster=roster)
        if status == "blocked"
        else _ticket_projection(window, roster)
    )
    normalized = _validate_thor_support_quality_result(
        _result(window, roster, status=status, ticket_projection=projection),
        expected_window=window,
        expected_roster=roster,
        expected_ticket_projection=projection,
    )
    publication = _build_weekly_support_quality_publication(
        normalized,
        previous={},
        job_key=f"job-{status}",
        idempotency_key=f"ops-weekly-support-quality:{status}",
        history_limit=8,
    )

    expected = "COMPLETED_WITH_ISSUES" if status == "partial" else "BLOCKED"
    assert _weekly_support_quality_completion_result(publication).startswith(expected)


def test_salesforce_projection_unavailable_allows_only_explicit_partial_gap():
    roster = _load_weekly_support_quality_roster(ROSTER_PATH)
    window = _window()
    projection = _unavailable_thor_ticket_projection(
        window=window,
        roster=roster,
    )
    raw = _result(
        window,
        roster,
        status="partial",
        ticket_projection=projection,
    )

    normalized = _validate_thor_support_quality_result(
        raw,
        expected_window=window,
        expected_roster=roster,
        expected_ticket_projection=projection,
    )

    assert normalized["status"] == "partial"
    assert normalized["sourceHealth"]["salesforce"] == {
        "state": "unavailable",
        "gaps": ["Salesforce ticket quality projection unavailable"],
    }
    assert (
        "Salesforce ticket quality projection unavailable"
        in normalized["coverage"]["sourceGaps"]
    )

    spoofed = copy.deepcopy(raw)
    spoofed["sourceHealth"]["salesforce"] = {"state": "ok", "gaps": []}
    with pytest.raises(ValueError, match="Salesforce source health"):
        _validate_thor_support_quality_result(
            spoofed,
            expected_window=window,
            expected_roster=roster,
            expected_ticket_projection=projection,
        )


def test_publication_carries_only_verified_distinct_prior_windows():
    roster = _load_weekly_support_quality_roster(ROSTER_PATH)
    first_window = _window()
    first = _validate_thor_support_quality_result(
        _result(first_window, roster),
        expected_window=first_window,
        expected_roster=roster,
        expected_ticket_projection=_ticket_projection(first_window, roster),
    )
    first_publication = _build_weekly_support_quality_publication(
        first,
        previous={},
        job_key="job-first",
        idempotency_key="ops-weekly-support-quality:first",
        history_limit=8,
    )
    second_window = _window(
        "2026-07-21T04:00:00+00:00",
        "2026-07-28T04:00:00+00:00",
    )
    second = _validate_thor_support_quality_result(
        _result(second_window, roster),
        expected_window=second_window,
        expected_roster=roster,
        expected_ticket_projection=_ticket_projection(second_window, roster),
    )
    second_publication = _build_weekly_support_quality_publication(
        second,
        previous=first_publication,
        job_key="job-second",
        idempotency_key="ops-weekly-support-quality:second",
        history_limit=8,
    )

    priors = _weekly_support_quality_prior_summaries(second_publication, limit=8)
    assert [item["window"] for item in priors] == [
        second["window"],
        first["window"],
    ]
    tampered = copy.deepcopy(second_publication)
    tampered["current"]["status"] = "blocked"
    assert _weekly_support_quality_prior_summaries(tampered, limit=8) == []


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: value.update({"rawTranscript": "raw customer text"}),
        lambda value: value["agenda"][0].update(
            {"objective": "Password: Summer2026!"}
        ),
        lambda value: value["agenda"][0].update(
            {"objective": "Email the customer at person@example.com"}
        ),
        lambda value: value["representatives"][0].update(
            {"id": "not-the-fixed-id"}
        ),
        lambda value: value["coverage"].update(
            {"zoomTranscriptAuditedCount": 7}
        ),
    ],
)
def test_result_rejects_raw_sensitive_spoofed_or_inconsistent_content(mutate):
    roster = _load_weekly_support_quality_roster(ROSTER_PATH)
    window = _window()
    raw = _result(window, roster)
    mutate(raw)

    with pytest.raises(ValueError):
        _validate_thor_support_quality_result(
            raw,
            expected_window=window,
            expected_roster=roster,
            expected_ticket_projection=_ticket_projection(window, roster),
        )


FORGED_TICKET_REFERENCE = "ticket:ffffffffffffffffffffffff"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value, roster: value["unresolvedTopics"].append(
            {
                "topic": "Forged unresolved evidence",
                "firstSeenWindow": "2026-07-14",
                "lastSeenWindow": "2026-07-21",
                "priorSummaryReferences": [],
                "evidenceReferences": [FORGED_TICKET_REFERENCE],
                "reason": "Requires verified follow-up",
            }
        ),
        lambda value, roster: value["knowledgeGaps"].append(
            {
                "theme": "Forged knowledge evidence",
                "affectedRepresentativeIds": [roster[0]["id"]],
                "evidenceReferences": [FORGED_TICKET_REFERENCE],
            }
        ),
        lambda value, roster: value["professionalismGaps"].append(
            {
                "theme": "Forged professionalism evidence",
                "affectedRepresentativeIds": [roster[0]["id"]],
                "evidenceReferences": [FORGED_TICKET_REFERENCE],
            }
        ),
        lambda value, roster: value["agenda"][0].update(
            {"evidenceReferences": [FORGED_TICKET_REFERENCE]}
        ),
    ],
)
def test_result_rejects_forged_ticket_refs_in_every_output_collection(mutate):
    roster = _load_weekly_support_quality_roster(ROSTER_PATH)
    window = _window()
    raw = _result(window, roster)
    mutate(raw, roster)

    with pytest.raises(ValueError, match="outside the gateway projection"):
        _validate_thor_support_quality_result(
            raw,
            expected_window=window,
            expected_roster=roster,
            expected_ticket_projection=_ticket_projection(window, roster),
        )


def test_non_ticket_references_remain_source_scoped():
    roster = _load_weekly_support_quality_roster(ROSTER_PATH)
    window = _window()
    raw = _result(window, roster)
    raw["unresolvedTopics"].append(
        {
            "topic": "Prior topic",
            "firstSeenWindow": "2026-07-14",
            "lastSeenWindow": "2026-07-21",
            "priorSummaryReferences": ["zoom:eng-1"],
            "evidenceReferences": [],
            "reason": "Still unresolved",
        }
    )

    with pytest.raises(ValueError, match="only prior references"):
        _validate_thor_support_quality_result(
            raw,
            expected_window=window,
            expected_roster=roster,
            expected_ticket_projection=_ticket_projection(window, roster),
        )


def test_result_marker_rejects_narrative_or_duplicate_output():
    roster = _load_weekly_support_quality_roster(ROSTER_PATH)
    raw_line = "THOR_SUPPORT_QUALITY_RESULT: " + json.dumps(
        _result(_window(), roster),
        separators=(",", ":"),
    )
    with pytest.raises(ValueError):
        _extract_thor_support_quality_result("COMPLETED\n" + raw_line)
    with pytest.raises(ValueError):
        _extract_thor_support_quality_result(raw_line + "\n" + raw_line)


def test_weekly_watch_state_uses_verified_durable_publication(tmp_path):
    roster = _load_weekly_support_quality_roster(ROSTER_PATH)
    window = _window()
    normalized = _validate_thor_support_quality_result(
        _result(window, roster),
        expected_window=window,
        expected_roster=roster,
        expected_ticket_projection=_ticket_projection(window, roster),
    )
    publication = _build_weekly_support_quality_publication(
        normalized,
        previous={},
        job_key="job-watch",
        idempotency_key="ops-weekly-support-quality:watch",
        history_limit=8,
    )
    state_path = tmp_path / "state.json"
    local_now = datetime(2026, 7, 28, 8, tzinfo=timezone.utc)
    _write_weekly_support_quality_watch_attempt_state(
        state_path,
        state={},
        scan_key=_weekly_support_quality_window_key(window),
        local_now=local_now,
        window=window,
        result={"job_id": "job-watch"},
        attempt_count=1,
    )
    _write_weekly_support_quality_watch_verified_state(
        state_path,
        state=json.loads(state_path.read_text(encoding="utf-8")),
        scan_key=_weekly_support_quality_window_key(window),
        local_now=local_now,
        window=window,
        job_id="job-watch",
        report=publication,
    )

    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["status"] == "verified"
    assert state["lastPublicationVerified"] is True
    assert state["lastContentSha256"] == publication["publication"]["contentSha256"]
