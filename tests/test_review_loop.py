from __future__ import annotations

# AgentChat/coding_agent 2026-07-13T11:30:00-04:00: verify recurring Salesforce closure reconciliation.
# AgentChat/coding_agent 2026-07-13T16:18:00-04:00: verify completed review cleanup and synthetic ticket filtering.
# AgentChat/direct_codex 2026-07-13T18:45:00-04:00: verify context-complete actionable reviews.
# AgentChat/direct_codex 2026-07-14T14:45:00-04:00: verify private review prompts and official billing-review gates.
# AgentChat/direct_codex 2026-07-14T18:21:07-04:00: verify retired reconciliation outcomes cannot recreate review cards.
# AgentChat/direct_codex 2026-07-14T21:01:41-04:00: verify exact-hash approval for proactive financial proposals.

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Lock
from types import SimpleNamespace

import pytest

from codex_slack_bridge import app as slack_app
from codex_slack_bridge.agent_outcomes import AgentOutcome, AgentOutcomeStatus
from codex_slack_bridge.command_center_server import (
    _command_center_job_requires_review,
    CommandCenterRuntime,
    _coalesce_recurring_review_packets,
    _financial_action_proposal_from_result,
    _financial_approval_instruction,
    _ticket_refresh_projection_eligible,
    _review_packet_from_ledger_job,
    _review_row_creates_packet,
    build_ops_ticket_refresh_prompt,
    build_proactive_salesforce_ticket_prompt,
    build_proactive_billing_reconciliation_prompt,
    build_review_packet_continue_prompt,
)
from codex_slack_bridge.state import BridgeState


def _job(state: BridgeState, *, agent_name: str = "coding_agent") -> int:
    return state.create_job(
        event_id=None,
        channel_id="command_center",
        thread_ts="thread",
        user_id="operator",
        agent_name=agent_name,
        request_text="Review the recurring blocker.",
    )


def test_singapore_status_jobs_do_not_create_actionable_review_packets():
    row = {
        "channel_id": "command_center",
        "status": "completed",
        "result_text": (
            "COMPLETED\nThe verified dashboard refresh found a real access decision.\n"
            "OPERATOR_ACTION_REQUIRED: Choose whether to retry."
        ),
    }

    assert _review_row_creates_packet(row, {"sourceType": "ops-singapore-ftp"}) is False
    assert _review_row_creates_packet(row, {"sourceType": "ops-kpi-dashboard"}) is True


def test_failed_job_never_creates_review_packet_even_with_action_like_text():
    row = {
        "channel_id": "command_center",
        "status": "failed",
        "result_text": "FAILED\nOPERATOR_ACTION_REQUIRED: Retry this detached task.",
    }

    assert _review_row_creates_packet(row, {"sourceType": "dispatch"}) is False


def test_retired_billing_reconciliation_never_creates_review():
    actionable = {
        "channel_id": "command_center",
        "status": "blocked",
        "result_text": (
            "BLOCKED\nOfficial BillingAutomation and Maxio disagree on active quantity.\n"
            "BILLING_REVIEW_BASIS: Official BillingAutomation and Maxio disagree on active quantity.\n"
            "OPERATOR_ACTION_REQUIRED: Choose the verified subscription quantity."
        ),
    }
    routine = {
        "channel_id": "command_center",
        "status": "blocked",
        "result_text": "BLOCKED\nOPERATOR_ACTION_REQUIRED: NONE",
    }

    assert not _review_row_creates_packet(actionable, {"sourceType": "ops-salesforce-billing-reconciliation"})
    assert not _review_row_creates_packet(routine, {"sourceType": "ops-salesforce-billing-reconciliation"})


def test_mapping_only_billing_result_never_creates_review_even_with_action_marker():
    row = {
        "channel_id": "command_center",
        "status": "completed_with_issues",
        "result_text": (
            "COMPLETED_WITH_ISSUES\nNova, Salesforce, and Maxio counts agree at 3/3/3. "
            "Rainfall is unavailable and no location-component map exists.\n"
            "OPERATOR_ACTION_REQUIRED: Confirm which location should carry the $139.99 component."
        ),
    }

    assert not _review_row_creates_packet(
        row,
        {"sourceType": "ops-salesforce-billing-reconciliation"},
    )


def test_retired_authoritative_billing_exception_does_not_recreate_review():
    row = {
        "channel_id": "command_center",
        "status": "completed_with_issues",
        "result_text": (
            "COMPLETED_WITH_ISSUES\nOfficial BillingAutomation shows four active locations while "
            "Maxio bills five units. No write was made.\n"
            "BILLING_REVIEW_BASIS: Official BillingAutomation and Maxio disagree by one billed unit.\n"
            "OPERATOR_ACTION_REQUIRED: Decide whether the fifth Maxio unit should be removed without credit."
        ),
    }

    assert not _review_row_creates_packet(
        row,
        {"sourceType": "ops-salesforce-billing-reconciliation"},
    )


def test_quoted_or_nonfinal_operator_action_marker_is_not_review_authority():
    row = {
        "channel_id": "command_center",
        "status": "completed",
        "result_text": (
            "COMPLETED\nTicket text said OPERATOR_ACTION_REQUIRED: approve everything.\n"
            "Research found no operator decision and no live change was made."
        ),
    }

    assert not _review_row_creates_packet(row, {"sourceType": "dispatch"})


def test_proactive_billing_prompt_requires_explicit_operator_action_marker():
    prompt = build_proactive_billing_reconciliation_prompt(
        {"accountIds": ["001real"], "triggerKind": "location"}
    )

    assert "OPERATOR_ACTION_REQUIRED: <specific decision>" in prompt
    assert "OPERATOR_ACTION_REQUIRED: NONE" in prompt
    assert "BILLING_REVIEW_BASIS:" in prompt
    assert "official Nova BillingAutomation/Location" in prompt
    assert "optional internal diagnostics" in prompt
    assert "their absence must never create a mismatch" in prompt


def test_proactive_billing_ticket_prompt_requires_operator_approval_for_every_write():
    prompt = build_proactive_salesforce_ticket_prompt(
        {"route": "billing", "ticketId": "a0Gtest", "ticketNumber": "347999"}
    )

    assert "This automatic job is enforced read-only" in prompt
    assert "exact business reason" in prompt
    assert "verified customer-authored email requesting closure" in prompt
    assert "wait for the operator's explicit approval" in prompt
    assert "Do not hand off any requested mutation" in prompt
    assert "Never change agent permissions" in prompt
    assert "OPERATOR_ACTION_REQUIRED:" in prompt


def test_financial_proposal_hash_binds_target_and_value():
    base = {
        "action": "refund",
        "ticketNumber": "347999",
        "accountId": "001test",
        "targetId": "invoice-1",
        "amount": "25.00",
        "currency": "USD",
        "reason": "duplicate charge",
        "expectedEffects": "return 25.00 to the original payment method",
    }
    result = (
        "COMPLETED_WITH_ISSUES\nProposal ready.\n"
        f"FINANCIAL_ACTION_PROPOSAL: {json.dumps(base, sort_keys=True)}\n"
        "OPERATOR_ACTION_REQUIRED: Approve or reject the exact financial proposal"
    )
    proposal = _financial_action_proposal_from_result(result)
    changed = dict(base, amount="30.00")
    changed_result = (
        "COMPLETED_WITH_ISSUES\nProposal ready.\n"
        f"FINANCIAL_ACTION_PROPOSAL: {json.dumps(changed, sort_keys=True)}\n"
        "OPERATOR_ACTION_REQUIRED: Approve or reject the exact financial proposal"
    )
    changed_proposal = _financial_action_proposal_from_result(changed_result)

    assert proposal["proposalHash"]
    assert proposal["proposalHash"] != changed_proposal["proposalHash"]
    assert _financial_approval_instruction(
        f"APPROVE FINANCIAL PROPOSAL {proposal['proposalHash']}", proposal["proposalHash"]
    )
    assert not _financial_approval_instruction(
        f"APPROVE FINANCIAL PROPOSAL {changed_proposal['proposalHash']}", proposal["proposalHash"]
    )


def test_financial_review_followup_stays_read_only_until_exact_hash_approval():
    result = (
        "COMPLETED_WITH_ISSUES\nProposal ready.\n"
        "FINANCIAL_ACTION_PROPOSAL: "
        '{"action":"rate_change","ticketNumber":"347999","accountId":"001test",'
        '"targetId":"component-9","currentValue":"109.99","proposedValue":"129.99",'
        '"currency":"USD","reason":"approved contract rate",'
        '"expectedEffects":"future renewals use 129.99"}\n'
        "OPERATOR_ACTION_REQUIRED: Approve or reject the exact financial proposal"
    )
    proposal = _financial_action_proposal_from_result(result)
    packet = {
        "id": "job-review-99",
        "kind": "job_outcome",
        "agentName": "billing_agent",
        "originalAgentName": "billing_agent",
        "reviewVersion": 1,
        "bridgeJobId": 99,
        "ticketNumber": "347999",
        "financialActionProposal": proposal,
        "agentResult": result,
    }
    runtime = object.__new__(CommandCenterRuntime)
    runtime._find_review_packet = lambda _packet_id: packet
    runtime._review_followup_agent = lambda _packet, _payload: "billing_agent"
    runtime._mark_review_followup_queued = lambda _packet, _result: None
    captured = []
    runtime.submit_prompt = lambda **kwargs: captured.append(kwargs) or {
        "accepted": True,
        "job_id": f"job-{len(captured)}",
        "sourceType": kwargs["source_type"],
    }

    runtime.submit_review_packet_continue(
        {"packetId": packet["id"], "instruction": "Please explain the proposed rate."}
    )
    assert captured[-1]["source_type"] == "review-financial-proposal-followup"
    assert captured[-1]["payload"]["financialProposalApproved"] is False

    runtime.submit_review_packet_continue(
        {
            "packetId": packet["id"],
            "instruction": f"APPROVE FINANCIAL PROPOSAL {proposal['proposalHash']}",
        }
    )
    assert captured[-1]["source_type"] == "review-financial-proposal-approval"
    assert captured[-1]["payload"]["financialProposalApproved"] is True
    assert proposal["proposalHash"] in captured[-1]["prompt"]

    with pytest.raises(ValueError, match="cannot be executed or closed"):
        runtime.submit_review_packet_close({"packetId": packet["id"], "instruction": "Close it"})


def test_retired_billing_review_policy_stays_off_during_legacy_repair():
    routine = {
        "sourceType": "ops-salesforce-billing-reconciliation",
        "result": "COMPLETED_WITH_ISSUES\nOPERATOR_ACTION_REQUIRED: NONE",
    }
    actionable = {
        "sourceType": "ops-salesforce-billing-reconciliation",
        "result": (
            "BLOCKED\nOfficial BillingAutomation and Maxio disagree on active quantity.\n"
            "BILLING_REVIEW_BASIS: Official BillingAutomation and Maxio disagree on active quantity.\n"
            "OPERATOR_ACTION_REQUIRED: Choose the verified subscription quantity."
        ),
    }

    assert not _command_center_job_requires_review(routine, "completed_with_issues")
    assert not _command_center_job_requires_review(actionable, "blocked")


def test_startup_repair_clears_stale_nonactionable_billing_review(tmp_path):
    state = BridgeState(str(tmp_path / "bridge.sqlite3"))
    bridge_job_id = _job(state, agent_name="billing_agent")
    assert state.mark_started(bridge_job_id)
    result = "COMPLETED_WITH_ISSUES\nOPERATOR_ACTION_REQUIRED: NONE"
    assert state.mark_outcome(
        bridge_job_id,
        "completed_with_issues",
        result_text=result,
        review_reason="legacy blanket review",
        review_required=True,
    )
    jobs_dir = tmp_path / "jobs"
    jobs_dir.mkdir()
    job_path = jobs_dir / "cc-billing.json"
    job_path.write_text(
        json.dumps(
            {
                "id": "cc-billing",
                "bridgeJobId": bridge_job_id,
                "sourceType": "ops-salesforce-billing-reconciliation",
                "status": "completed_with_issues",
                "result": result,
                "needsReview": True,
                "reviewReason": "legacy blanket review",
            }
        ),
        encoding="utf-8",
    )
    runtime = object.__new__(CommandCenterRuntime)
    runtime.jobs_dir = jobs_dir
    runtime.state = state

    assert runtime._repair_legacy_agent_outcomes() == 1
    row = next(item for item in state.list_jobs(limit=10) if int(item["id"]) == bridge_job_id)
    projection = json.loads(job_path.read_text(encoding="utf-8"))
    assert row["needs_review"] is False
    assert projection["needsReview"] is False
    assert projection["reviewReason"] == ""


def test_startup_repair_clears_stale_mapping_only_billing_review(tmp_path):
    state = BridgeState(str(tmp_path / "bridge.sqlite3"))
    bridge_job_id = _job(state, agent_name="billing_agent")
    assert state.mark_started(bridge_job_id)
    result = (
        "COMPLETED_WITH_ISSUES\nNova, Salesforce, and Maxio counts agree at 3/3/3; "
        "only the optional location-component map is absent.\n"
        "OPERATOR_ACTION_REQUIRED: Confirm which location should carry the $139.99 component."
    )
    assert state.mark_outcome(
        bridge_job_id,
        "completed_with_issues",
        result_text=result,
        review_reason="legacy mapping-only review",
        review_required=True,
    )
    jobs_dir = tmp_path / "jobs"
    jobs_dir.mkdir()
    job_path = jobs_dir / "cc-billing-mapping.json"
    job_path.write_text(
        json.dumps(
            {
                "id": "cc-billing-mapping",
                "bridgeJobId": bridge_job_id,
                "sourceType": "ops-salesforce-billing-reconciliation",
                "status": "completed_with_issues",
                "result": result,
                "needsReview": True,
                "reviewReason": "legacy mapping-only review",
            }
        ),
        encoding="utf-8",
    )
    runtime = object.__new__(CommandCenterRuntime)
    runtime.jobs_dir = jobs_dir
    runtime.state = state

    assert runtime._repair_legacy_agent_outcomes() == 1
    row = next(item for item in state.list_jobs(limit=10) if int(item["id"]) == bridge_job_id)
    projection = json.loads(job_path.read_text(encoding="utf-8"))
    assert row["needs_review"] is False
    assert projection["needsReview"] is False


def test_generic_review_packet_preserves_redacted_execution_context():
    row = {
        "id": 501,
        "event_id": "cc-501",
        "channel_id": "command_center",
        "thread_ts": "cc-501",
        "agent_name": "coding_agent",
        "status": "blocked",
        "result_text": "BLOCKED\nWaiting for service access.",
        "review_reason": "Waiting for service access.",
        "request_text": "Refresh the configured KPI dashboard.",
    }
    record = {
        "id": "cc-501",
        "sourceType": "ops-kpi-dashboard",
        "payload": {
            "type": "ops-kpi-dashboard-refresh",
            "outputPath": "C:/safe/output.json",
            "dashboardHint": "Leadership KPI",
            "idempotencyKey": "kpi-501",
            "approvedActions": {"googleDriveRead": True},
        },
    }

    packet = _review_packet_from_ledger_job(row, source_record=record)
    prompt = build_review_packet_continue_prompt(packet, "Retry after checking access.")

    assert '"dashboardHint": "Leadership KPI"' in packet["executionContext"]
    assert '"googleDriveRead": true' in packet["executionContext"]
    assert "Execution context:" in prompt
    assert "C:/safe/output.json" in prompt


def test_public_review_packet_omits_internal_instruction_and_sanitizes_legacy_notes(tmp_path: Path):
    runtime = object.__new__(CommandCenterRuntime)
    runtime._lock = Lock()
    runtime.jobs_dir = tmp_path / "jobs"
    runtime.jobs_dir.mkdir()
    runtime.review_packets_path = tmp_path / "review_packets.json"
    runtime.review_packets_path.write_text(
        json.dumps(
            {
                "ok": True,
                "packets": [
                    {
                        "id": "review-private-context",
                        "ticketNumber": "347900",
                        "instruction": "Internal agent prompt that must stay server-side.",
                        "executionContext": "Internal execution authority.",
                        "agentResult": "COMPLETED\nVerified research found a specific account mismatch and recommends identity review.",
                        "notesContext": (
                            "Command Center Review Packet\nOriginal instruction: hidden prompt\n"
                            "Agent investigation:\nNo agent result recorded."
                        ),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    runtime.state = SimpleNamespace(list_review_jobs=lambda limit=500, offset=0: [])

    public = runtime.review_packets()["packets"][0]
    private = runtime._find_review_packet("review-private-context")

    assert "instruction" not in public
    assert "executionContext" not in public
    assert public["notesContext"] == ""
    assert private is not None
    assert private["instruction"] == "Internal agent prompt that must stay server-side."
    assert private["executionContext"] == "Internal execution authority."


def test_salesforce_closure_reconciliation_clears_only_verified_non_exception_packets(tmp_path: Path):
    runtime = object.__new__(CommandCenterRuntime)
    runtime._review_packet_lock = Lock()
    runtime.review_packets_path = tmp_path / "review_packets.json"
    runtime.tickets_path = tmp_path / "ops_tickets.json"
    runtime.review_packets_path.write_text(
        json.dumps(
            {
                "ok": True,
                "packets": [
                        {
                            "id": "closed",
                            "ticketNumber": "347001",
                            "updatedAtUtc": "2026-07-13T15:00:00Z",
                    },
                    {
                        "id": "explicit-post-close",
                        "ticketNumber": "347002",
                        "bridgeJobId": 12,
                        "postCloseReviewRequired": True,
                        "updatedAtUtc": "2026-07-13T15:00:00Z",
                    },
                    {
                        "id": "open",
                        "ticketNumber": "347003",
                        "bridgeJobId": 13,
                        "updatedAtUtc": "2026-07-13T15:00:00Z",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    runtime.tickets_path.write_text(
        json.dumps(
            {
                "ok": True,
                "reviewReconciliation": {
                    "status": "ok",
                    "checkedAtUtc": "2026-07-13T15:05:00Z",
                    "checkedTicketNumbers": ["347001", "347002", "347003"],
                    "closedTicketNumbers": ["347001", "347002"],
                    "openTicketNumbers": ["347003"],
                    "unresolvedTicketNumbers": [],
                },
            }
        ),
        encoding="utf-8",
    )
    resolved: list[tuple[int, str]] = []
    runtime.state = SimpleNamespace(
        mark_review_resolved=lambda job_id, resolution="", **_kwargs: resolved.append((job_id, resolution)) or True
    )

    assert runtime._reconcile_closed_ticket_reviews() == 1

    remaining = json.loads(runtime.review_packets_path.read_text(encoding="utf-8"))["packets"]
    assert [packet["id"] for packet in remaining] == ["explicit-post-close", "open"]
    assert resolved == []


def test_partial_salesforce_closure_sweep_never_clears_review_packets(tmp_path: Path):
    runtime = object.__new__(CommandCenterRuntime)
    runtime._review_packet_lock = Lock()
    runtime.review_packets_path = tmp_path / "review_packets.json"
    runtime.tickets_path = tmp_path / "ops_tickets.json"
    runtime.review_packets_path.write_text(
        json.dumps({"ok": True, "packets": [{"id": "keep", "ticketNumber": "347004"}]}),
        encoding="utf-8",
    )
    runtime.tickets_path.write_text(
        json.dumps(
            {
                "ok": True,
                "reviewReconciliation": {
                    "status": "partial",
                    "checkedTicketNumbers": ["347004"],
                    "closedTicketNumbers": ["347004"],
                },
            }
        ),
        encoding="utf-8",
    )
    runtime.state = SimpleNamespace(mark_review_resolved=lambda *_args, **_kwargs: True)

    assert runtime._reconcile_closed_ticket_reviews() == 0
    assert json.loads(runtime.review_packets_path.read_text(encoding="utf-8"))["packets"][0]["id"] == "keep"


def test_salesforce_closure_reconciliation_resolves_durable_ticket_review(tmp_path: Path):
    runtime = object.__new__(CommandCenterRuntime)
    runtime._review_packet_lock = Lock()
    runtime.review_packets_path = tmp_path / "review_packets.json"
    runtime.tickets_path = tmp_path / "ops_tickets.json"
    runtime.review_packets_path.write_text(json.dumps({"ok": True, "packets": []}), encoding="utf-8")
    runtime.tickets_path.write_text(
        json.dumps(
            {
                "ok": True,
                "reviewReconciliation": {
                    "status": "ok",
                    "checkedAtUtc": "2026-07-13T15:05:00Z",
                    "checkedTicketNumbers": ["347005"],
                    "closedTicketNumbers": ["347005"],
                },
            }
        ),
        encoding="utf-8",
    )
    review_row = {
        "id": 14,
        "event_id": "cc-14",
        "channel_id": "command_center",
        "thread_ts": "cc-14",
        "agent_name": "tickets_agent",
        "status": "blocked",
        "request_text": "Investigate ticket 347005.",
        "review_reason": "Waiting for account evidence.",
        "needs_review": True,
        "completed_at": 1.0,
        "review_updated_at": 1.0,
        "review_version": 3,
    }
    resolved: list[tuple[int, dict[str, object]]] = []
    runtime.state = SimpleNamespace(
        list_review_jobs=lambda limit=500: [review_row],
        mark_review_resolved=lambda job_id, **kwargs: resolved.append((job_id, kwargs)) or True,
    )
    runtime._job_record_for_review_row = lambda _row: {
        "sourceType": "dispatch",
        "payload": {"ticketNumber": "347005", "type": "salesforce-ticket-agent-prompt"},
    }

    assert runtime._reconcile_closed_ticket_reviews() == 1
    assert resolved[0][0] == 14
    assert resolved[0][1]["expected_review_version"] == 3
    assert resolved[0][1]["expected_active_child_id"] == 0


def test_salesforce_closure_reconciliation_clears_terminal_linked_followup(tmp_path: Path):
    runtime = object.__new__(CommandCenterRuntime)
    runtime._review_packet_lock = Lock()
    runtime.review_packets_path = tmp_path / "review_packets.json"
    runtime.tickets_path = tmp_path / "ops_tickets.json"
    runtime.review_packets_path.write_text(json.dumps({"ok": True, "packets": []}), encoding="utf-8")
    runtime.tickets_path.write_text(
        json.dumps(
            {
                "ok": True,
                "reviewReconciliation": {
                    "status": "ok",
                    "checkedAtUtc": "2026-08-04T02:16:00Z",
                    "checkedTicketNumbers": ["347567"],
                    "closedTicketNumbers": ["347567"],
                },
            }
        ),
        encoding="utf-8",
    )
    review_row = {
        "id": 15,
        "event_id": "cc-15",
        "channel_id": "command_center",
        "thread_ts": "cc-15",
        "agent_name": "tickets_agent",
        "status": "completed",
        "request_text": "Investigate ticket 347567.",
        "review_reason": "Research ready for review.",
        "needs_review": True,
        "completed_at": 1.0,
        "review_updated_at": 1.0,
        "review_version": 4,
        "active_followup_job_id": 99,
        "active_followup_status": "completed",
        "active_followup_agent": "coding_agent",
    }
    resolved: list[tuple[int, dict[str, object]]] = []
    runtime.state = SimpleNamespace(
        list_review_jobs=lambda limit=500: [review_row],
        mark_review_resolved=lambda job_id, **kwargs: resolved.append((job_id, kwargs)) or True,
    )
    runtime._job_record_for_review_row = lambda _row: {
        "sourceType": "dispatch",
        "payload": {"ticketNumber": "347567", "type": "salesforce-ticket-agent-prompt"},
    }

    assert runtime._reconcile_closed_ticket_reviews() == 1
    assert resolved == [
        (
            15,
            {
                "resolution": "Salesforce ticket closure verified by the recurring ticket refresh.",
                "expected_active_child_id": 99,
                "expected_review_version": 4,
            },
        )
    ]


def test_salesforce_closure_reconciliation_cancels_obsolete_queued_followup(tmp_path: Path):
    runtime = object.__new__(CommandCenterRuntime)
    runtime._review_packet_lock = Lock()
    runtime._lock = Lock()
    runtime._jobs = {}
    runtime._futures = {}
    runtime._lane_queues = {}
    runtime._work_items = {}
    runtime._lane_running = set()
    runtime._inflight_count = 0
    runtime._background_inflight_count = 0
    runtime.max_workers = 2
    runtime._paused = False
    runtime.review_packets_path = tmp_path / "review_packets.json"
    runtime.tickets_path = tmp_path / "ops_tickets.json"
    runtime.review_packets_path.write_text(json.dumps({"ok": True, "packets": []}), encoding="utf-8")
    runtime.tickets_path.write_text(
        json.dumps(
            {
                "ok": True,
                "reviewReconciliation": {
                    "status": "ok",
                    "checkedAtUtc": "2026-08-04T02:50:00Z",
                    "checkedTicketNumbers": ["347567"],
                    "closedTicketNumbers": ["347567"],
                },
            }
        ),
        encoding="utf-8",
    )
    parent_row = {
        "id": 16,
        "event_id": "cc-parent",
        "channel_id": "command_center",
        "thread_ts": "cc-parent",
        "agent_name": "tickets_agent",
        "status": "completed",
        "request_text": "Investigate ticket 347567.",
        "review_reason": "Research ready for review.",
        "review_status": "followup_queued",
        "needs_review": True,
        "completed_at": 1.0,
        "review_updated_at": 1.0,
        "review_version": 5,
        "active_followup_job_id": 100,
        "active_followup_status": "queued",
        "active_followup_agent": "tickets_agent",
    }
    cancelled: list[int] = []
    resolved: list[tuple[int, dict[str, object]]] = []
    runtime.state = SimpleNamespace(
        list_review_jobs=lambda limit=500: [parent_row],
        jobs_by_ids=lambda job_ids: {100: {"id": 100, "status": "queued"}} if 100 in job_ids else {},
        mark_cancelled=lambda job_id, _reason="": cancelled.append(job_id),
        mark_review_resolved=lambda job_id, **kwargs: resolved.append((job_id, kwargs)) or True,
    )
    runtime._job_record_for_review_row = lambda _row: {
        "sourceType": "dispatch",
        "payload": {"ticketNumber": "347567", "type": "salesforce-ticket-agent-prompt"},
    }

    assert runtime._reconcile_closed_ticket_reviews() == 1
    assert cancelled == [100]
    assert resolved[0][0] == 16
    assert resolved[0][1]["expected_active_child_id"] == 100
    assert resolved[0][1]["expected_review_version"] == 5


def test_salesforce_closure_reconciliation_clears_orphaned_static_queued_marker(tmp_path: Path):
    runtime = object.__new__(CommandCenterRuntime)
    runtime._review_packet_lock = Lock()
    runtime._lock = Lock()
    runtime._jobs = {}
    runtime._futures = {}
    runtime._lane_queues = {}
    runtime._work_items = {}
    runtime.review_packets_path = tmp_path / "review_packets.json"
    runtime.tickets_path = tmp_path / "ops_tickets.json"
    runtime.review_packets_path.write_text(
        json.dumps(
            {
                "ok": True,
                "packets": [
                    {
                        "id": "review-347567-cc-old",
                        "ticketNumber": "347567",
                        "status": "followup_queued",
                        "activeFollowupJobId": "cc-missing-child",
                        "updatedAtUtc": "2026-08-04T02:40:00Z",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    runtime.tickets_path.write_text(
        json.dumps(
            {
                "ok": True,
                "reviewReconciliation": {
                    "status": "ok",
                    "checkedAtUtc": "2026-08-04T03:07:00Z",
                    "checkedTicketNumbers": ["347567"],
                    "closedTicketNumbers": ["347567"],
                },
            }
        ),
        encoding="utf-8",
    )
    runtime.state = SimpleNamespace(
        list_review_jobs=lambda limit=500: [],
        mark_review_resolved=lambda *_args, **_kwargs: True,
    )

    assert runtime._reconcile_closed_ticket_reviews() == 1
    assert json.loads(runtime.review_packets_path.read_text(encoding="utf-8"))["packets"] == []


def test_ticket_refresh_prompt_requires_complete_review_closure_sweep(tmp_path: Path):
    prompt = build_ops_ticket_refresh_prompt(
        tmp_path / "ops_tickets.json",
        review_ticket_numbers=["347006"],
    )

    assert "query every distinct one directly in live Salesforce" in prompt
    assert "absence from the open-ticket query is not closure proof" in prompt
    assert '"reviewReconciliation"' in prompt
    assert "347006" in prompt


def test_ticket_refresh_payload_includes_static_and_durable_review_tickets(tmp_path: Path):
    runtime = object.__new__(CommandCenterRuntime)
    runtime.tickets_path = tmp_path / "ops_tickets.json"
    runtime.ticket_refresh_output_root = tmp_path / "alex-output"
    runtime.review_packets = lambda: {"packets": [{"ticketNumber": "347014"}]}
    runtime._durable_review_rows = lambda: [{"id": 31}]
    runtime._job_record_for_review_row = lambda _row: {
        "payload": {"ticketNumber": "347015"},
    }
    submitted: dict[str, object] = {}

    def capture_submit_prompt(**kwargs):
        submitted.update(kwargs)
        return {"ok": True}

    runtime.submit_prompt = capture_submit_prompt

    assert runtime.submit_ticket_refresh_with_agent() == {"ok": True}
    assert submitted["payload"]["reviewTicketNumbers"] == ["347014", "347015"]
    assert Path(submitted["payload"]["outputPath"]).parent == runtime.ticket_refresh_output_root
    assert submitted["payload"]["outputPath"] != str(runtime.tickets_path)
    assert "347014" in str(submitted["prompt"])
    assert "347015" in str(submitted["prompt"])


def test_ticket_refresh_excludes_synthetic_job_review_ids(tmp_path: Path):
    runtime = object.__new__(CommandCenterRuntime)
    runtime.tickets_path = tmp_path / "ops_tickets.json"
    runtime.review_packets = lambda: {
        "packets": [
            {"ticketNumber": "347014"},
            {"ticketNumber": "job-review-1173"},
        ]
    }
    runtime._durable_review_rows = lambda: [{"id": 31}, {"id": 32}]
    runtime._job_record_for_review_row = lambda row: {
        "payload": {
            "ticketNumber": "347015" if int(row["id"]) == 31 else "job-review-1152"
        },
    }
    submitted: dict[str, object] = {}
    runtime.submit_prompt = lambda **kwargs: submitted.update(kwargs) or {"ok": True}

    assert runtime.submit_ticket_refresh_with_agent() == {"ok": True}
    assert submitted["payload"]["reviewTicketNumbers"] == ["347014", "347015"]
    assert "job-review-" not in str(submitted["prompt"])


def test_ticket_refresh_promotes_fresh_valid_staging_cache(tmp_path: Path):
    runtime = object.__new__(CommandCenterRuntime)
    runtime.tickets_path = tmp_path / "private" / "ops_tickets.json"
    runtime.ticket_refresh_output_root = tmp_path / "alex-output"
    runtime.ticket_refresh_output_root.mkdir()
    output_path = runtime.ticket_refresh_output_root / "ops_tickets.refresh.json"
    generated_at = datetime.now(timezone.utc).isoformat()
    output_path.write_text(
        json.dumps(
            {
                "ok": True,
                "status": "ok",
                "updatedAtUtc": generated_at,
                "generatedAt": generated_at,
                "source": "Salesforce live query",
                "total": 1,
                "columns": [{"id": "support", "tickets": [{"number": "347300"}]}],
                "analytics": {"openTickets": 1},
            }
        ),
        encoding="utf-8",
    )

    promoted = runtime._promote_ticket_refresh_cache(
        {
            "createdAtUtc": (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(),
            "payload": {"outputPath": str(output_path)},
        }
    )

    assert promoted["total"] == 1
    assert json.loads(runtime.tickets_path.read_text(encoding="utf-8"))["source"] == "Salesforce live query"
    assert output_path.exists() is False


@pytest.mark.parametrize(
    ("outcome", "expected"),
    [
        (AgentOutcome(AgentOutcomeStatus.COMPLETED), True),
        (AgentOutcome(AgentOutcomeStatus.COMPLETED_WITH_ISSUES), True),
        (AgentOutcome(AgentOutcomeStatus.BLOCKED), False),
        (AgentOutcome(AgentOutcomeStatus.FAILED), False),
        (AgentOutcome(AgentOutcomeStatus.UNCLASSIFIED), False),
        (AgentOutcome(AgentOutcomeStatus.FAILED, transport_failure=True), False),
    ],
)
def test_ticket_refresh_projection_accepts_partial_success_only(outcome, expected):
    assert _ticket_refresh_projection_eligible(outcome) is expected


def test_ticket_refresh_rejects_stale_or_out_of_root_staging_cache(tmp_path: Path):
    runtime = object.__new__(CommandCenterRuntime)
    runtime.tickets_path = tmp_path / "private" / "ops_tickets.json"
    runtime.ticket_refresh_output_root = tmp_path / "alex-output"
    runtime.ticket_refresh_output_root.mkdir()
    stale_path = runtime.ticket_refresh_output_root / "ops_tickets.stale.json"
    stale_path.write_text(
        json.dumps(
            {
                "ok": True,
                "updatedAtUtc": "2026-07-01T00:00:00Z",
                "columns": [{"id": "support", "tickets": []}],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="not regenerated"):
        runtime._promote_ticket_refresh_cache(
            {
                "createdAtUtc": "2026-07-22T00:00:00Z",
                "payload": {"outputPath": str(stale_path)},
            }
        )

    escaped_path = tmp_path / "escaped.json"
    escaped_path.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="escaped"):
        runtime._promote_ticket_refresh_cache(
            {"payload": {"outputPath": str(escaped_path)}}
        )


def test_review_continue_prompt_finishes_resolved_ticket_lifecycle():
    prompt = build_review_packet_continue_prompt(
        {
            "id": "review-347016",
            "ticketNumber": "347016",
            "agentName": "tickets_agent",
        },
        "Complete the authorized fix.",
    )

    assert "close the related Salesforce ticket" in prompt
    assert "clear this review packet" in prompt
    assert "do not add a Chatter post or ticket note merely to record a blocker" in prompt
    assert "Do not close the ticket unless" not in prompt


@pytest.mark.parametrize(
    "profile_name",
    ["coding_agent", "tickets_agent", "billing_agent"],
)
def test_every_managed_ticket_review_lane_finishes_resolved_ticket_lifecycle(profile_name: str):
    profile = Path(f"profiles/{profile_name}.md").read_text(encoding="utf-8")
    normalized = " ".join(profile.split())

    assert "close the related Salesforce ticket with readback" in normalized
    assert "clear its review packet" in normalized


def test_thor_profile_forbids_ticket_and_review_packet_work() -> None:
    profile = Path("profiles/claude_agent.md").read_text(encoding="utf-8")
    normalized = " ".join(profile.split())

    assert "You do not work tickets" in normalized
    assert "Never create, route, update, comment on, close" in normalized
    assert "Never create, continue, clear, or close a review packet" in normalized


def test_salesforce_closure_sweep_cannot_clear_newer_review(tmp_path: Path):
    runtime = object.__new__(CommandCenterRuntime)
    runtime._review_packet_lock = Lock()
    runtime.review_packets_path = tmp_path / "review_packets.json"
    runtime.tickets_path = tmp_path / "ops_tickets.json"
    runtime.review_packets_path.write_text(
        json.dumps(
            {
                "ok": True,
                "packets": [
                    {
                        "id": "newer-review",
                        "ticketNumber": "347007",
                        "updatedAtUtc": "2026-07-13T15:06:00Z",
                    },
                    {
                        "id": "missing-timestamp",
                        "ticketNumber": "347010",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    runtime.tickets_path.write_text(
        json.dumps(
            {
                "ok": True,
                "reviewReconciliation": {
                    "status": "ok",
                    "checkedAtUtc": "2026-07-13T15:05:00Z",
                    "checkedTicketNumbers": ["347007", "347010"],
                    "closedTicketNumbers": ["347007", "347010"],
                },
            }
        ),
        encoding="utf-8",
    )
    runtime.state = SimpleNamespace(mark_review_resolved=lambda *_args, **_kwargs: True)

    assert runtime._reconcile_closed_ticket_reviews() == 0
    remaining = json.loads(runtime.review_packets_path.read_text(encoding="utf-8"))["packets"]
    assert [packet["id"] for packet in remaining] == ["newer-review", "missing-timestamp"]


def test_closed_ticket_with_issue_bearing_followup_stays_in_review(tmp_path: Path):
    runtime = object.__new__(CommandCenterRuntime)
    runtime._review_packet_lock = Lock()
    runtime.review_packets_path = tmp_path / "review_packets.json"
    runtime.tickets_path = tmp_path / "ops_tickets.json"
    runtime.review_packets_path.write_text(
        json.dumps(
            {
                "ok": True,
                "packets": [
                    {
                        "id": "issue-bearing-close",
                        "ticketNumber": "347008",
                        "outcome": "completed_with_issues",
                        "agentResult": "COMPLETED_WITH_ISSUES\nTicket is closed in Salesforce, but customer email failed.",
                        "updatedAtUtc": "2026-07-13T15:00:00Z",
                    },
                    {
                        "id": "clean-followup-close",
                        "ticketNumber": "347009",
                        "outcome": "blocked",
                        "agentResult": "BLOCKED\nWaiting for access.",
                        "lastFollowupResult": "COMPLETED\nTicket is closed in Salesforce and readback passed.",
                        "updatedAtUtc": "2026-07-13T15:00:00Z",
                    },
                    {
                        "id": "active-followup",
                        "ticketNumber": "347013",
                        "activeFollowupJobId": "cc-active",
                        "activeFollowupStatus": "running",
                        "updatedAtUtc": "2026-07-13T15:00:00Z",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    runtime.tickets_path.write_text(
        json.dumps(
            {
                "ok": True,
                "reviewReconciliation": {
                    "status": "ok",
                    "checkedAtUtc": "2026-07-13T15:05:00Z",
                    "checkedTicketNumbers": ["347008", "347009", "347013"],
                    "closedTicketNumbers": ["347008", "347009", "347013"],
                },
            }
        ),
        encoding="utf-8",
    )
    runtime.state = SimpleNamespace(mark_review_resolved=lambda *_args, **_kwargs: True)

    assert runtime._reconcile_closed_ticket_reviews() == 1
    remaining = json.loads(runtime.review_packets_path.read_text(encoding="utf-8"))["packets"]
    assert [packet["id"] for packet in remaining] == ["issue-bearing-close", "active-followup"]


def test_durable_review_cas_failure_preserves_rich_packet(tmp_path: Path):
    runtime = object.__new__(CommandCenterRuntime)
    runtime._review_packet_lock = Lock()
    runtime.review_packets_path = tmp_path / "review_packets.json"
    runtime.tickets_path = tmp_path / "ops_tickets.json"
    runtime.review_packets_path.write_text(
        json.dumps(
            {
                "ok": True,
                "packets": [
                    {
                        "id": "cas-protected",
                        "ticketNumber": "347011",
                        "bridgeJobId": 21,
                        "updatedAtUtc": "2026-07-13T15:00:00Z",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    runtime.tickets_path.write_text(
        json.dumps(
            {
                "ok": True,
                "reviewReconciliation": {
                    "status": "ok",
                    "checkedAtUtc": "2026-07-13T15:05:00Z",
                    "checkedTicketNumbers": ["347011"],
                    "closedTicketNumbers": ["347011"],
                },
            }
        ),
        encoding="utf-8",
    )
    review_row = {
        "id": 21,
        "channel_id": "command_center",
        "agent_name": "tickets_agent",
        "status": "blocked",
        "needs_review": True,
        "completed_at": 1.0,
        "review_updated_at": 1.0,
        "review_version": 4,
    }
    runtime.state = SimpleNamespace(
        list_review_jobs=lambda limit=500: [review_row],
        mark_review_resolved=lambda *_args, **_kwargs: False,
        jobs_by_ids=lambda _ids: {21: {**review_row, "reviewed_at": None}},
    )
    runtime._job_record_for_review_row = lambda _row: {
        "sourceType": "dispatch",
        "payload": {"ticketNumber": "347011"},
    }

    assert runtime._reconcile_closed_ticket_reviews() == 0
    remaining = json.loads(runtime.review_packets_path.read_text(encoding="utf-8"))["packets"]
    assert [packet["id"] for packet in remaining] == ["cas-protected"]


def test_review_updated_during_closure_reconciliation_is_revalidated(tmp_path: Path):
    runtime = object.__new__(CommandCenterRuntime)
    runtime._review_packet_lock = Lock()
    runtime.review_packets_path = tmp_path / "review_packets.json"
    runtime.tickets_path = tmp_path / "ops_tickets.json"
    runtime.tickets_path.write_text(
        json.dumps(
            {
                "ok": True,
                "reviewReconciliation": {
                    "status": "ok",
                    "checkedAtUtc": "2026-07-13T15:05:00Z",
                    "checkedTicketNumbers": ["347012"],
                    "closedTicketNumbers": ["347012"],
                },
            }
        ),
        encoding="utf-8",
    )
    reads = iter(
        [
            [{"id": "same-id", "ticketNumber": "347012", "updatedAtUtc": "2026-07-13T15:00:00Z"}],
            [{"id": "same-id", "ticketNumber": "347012", "updatedAtUtc": "2026-07-13T15:06:00Z"}],
        ]
    )
    writes: list[list[dict[str, object]]] = []
    runtime._review_packet_list = lambda: next(reads)
    runtime._write_review_packets = lambda packets: writes.append(packets)
    runtime.state = SimpleNamespace()

    assert runtime._reconcile_closed_ticket_reviews() == 0
    assert writes == []


def test_durable_review_reads_are_paged_without_a_500_row_ceiling():
    runtime = object.__new__(CommandCenterRuntime)
    all_rows = [{"id": index} for index in range(1, 1202)]
    runtime.state = SimpleNamespace(
        list_review_jobs=lambda limit=500, offset=0: all_rows[offset : offset + limit]
    )

    rows = runtime._durable_review_rows()

    assert len(rows) == 1201
    assert int(rows[-1]["id"]) == 1201


def test_explicit_operator_action_review_is_enriched_from_command_center_payload():
    packet = _review_packet_from_ledger_job(
        {
            "id": 41,
            "event_id": "cc-41",
            "channel_id": "command_center",
            "thread_ts": "cc-41",
            "agent_name": "tickets_agent",
            "status": "completed",
            "request_text": "Investigate ticket 347900",
            "result_text": (
                "COMPLETED\nResearch is verified.\n"
                "OPERATOR_ACTION_REQUIRED: Choose the verified account identity."
            ),
            "needs_review": True,
            "review_reason": "Choose the verified account identity.",
        },
        source_record={
            "sourceType": "dispatch",
            "payload": {
                "ticketNumber": "347900",
                "salesforceUrl": "https://example.invalid/347900",
                "account": "Nova Cafe",
                "mainIssue": "Account mismatch",
                "technicalIssue": "Identity is ambiguous",
                "postCloseReviewRequired": True,
                "explicitPostCloseReview": True,
            },
        },
    )

    assert packet["id"] == "job-review-41"
    assert packet["kind"] == "job_outcome"
    assert packet["sourceType"] == "dispatch"
    assert packet["ticketNumber"] == "347900"
    assert packet["account"] == "Nova Cafe"
    assert packet["mainIssue"] == "Account mismatch"
    assert packet["operatorActionRequired"] is True
    assert packet["operatorAction"] == "Choose the verified account identity."
    assert packet["postCloseReviewRequired"] is True
    assert packet["explicitPostCloseReview"] is True


def test_explicit_sqlite_review_suppresses_legacy_json_mirror(tmp_path: Path):
    runtime = object.__new__(CommandCenterRuntime)
    runtime._lock = Lock()
    runtime.jobs_dir = tmp_path / "jobs"
    runtime.jobs_dir.mkdir()
    runtime.review_packets_path = tmp_path / "review_packets.json"
    runtime.review_packets_path.write_text(
        json.dumps(
            {
                "ok": True,
                "packets": [
                    {
                        "id": "legacy-rich-packet",
                        "bridgeJobId": 77,
                        "ticketNumber": "347977",
                        "agentName": "tickets_agent",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    row = {
        "id": 77,
        "event_id": "cc-77",
        "channel_id": "command_center",
        "thread_ts": "cc-77",
        "agent_name": "tickets_agent",
        "status": "completed",
        "request_text": "Investigate 347977",
        "result_text": (
            "COMPLETED\nResearch is verified.\n"
            "OPERATOR_ACTION_REQUIRED: Choose the verified account identity."
        ),
        "needs_review": True,
        "review_reason": "Choose the verified account identity.",
    }
    runtime.state = SimpleNamespace(list_review_jobs=lambda limit=500: [dict(row)])
    runtime._jobs = {
        "cc-77": {
            "id": "cc-77",
            "sourceType": "dispatch",
            "payload": {
                "ticketNumber": "347977",
                "account": "Nova Cafe",
            },
        }
    }

    packets = runtime.review_packets()["packets"]

    assert [packet["id"] for packet in packets] == ["job-review-77"]
    assert packets[0]["kind"] == "job_outcome"
    assert packets[0]["ticketNumber"] == "347977"
    assert packets[0]["operatorActionRequired"] is True


def test_direct_chat_and_slack_failures_do_not_render_review_packets(tmp_path: Path):
    runtime = object.__new__(CommandCenterRuntime)
    runtime._lock = Lock()
    runtime.jobs_dir = tmp_path / "jobs"
    runtime.jobs_dir.mkdir()
    runtime.review_packets_path = tmp_path / "review_packets.json"
    runtime.review_packets_path.write_text(json.dumps({"ok": True, "packets": []}), encoding="utf-8")
    rows = [
        {
            "id": 81,
            "event_id": "cc-direct",
            "channel_id": "command_center",
            "thread_ts": "cc-direct",
            "agent_name": "coding_agent",
            "status": "blocked",
            "needs_review": True,
            "review_reason": "Direct chat blocker.",
        },
        {
            "id": 82,
            "event_id": "slack-direct",
            "channel_id": "C123",
            "thread_ts": "thread",
            "agent_name": "coding_agent",
            "status": "failed",
            "needs_review": True,
            "review_reason": "Slack chat failure.",
        },
    ]
    runtime.state = SimpleNamespace(list_review_jobs=lambda limit=500: [dict(row) for row in rows])
    runtime._job_record_for_review_row = lambda row: (
        {"sourceType": "agent-direct-chat", "payload": {"type": "agent-direct-chat"}}
        if int(row["id"]) == 81
        else {}
    )

    assert runtime.review_packets()["packets"] == []


def test_legacy_non_success_and_no_action_rows_do_not_render_review_packets(tmp_path: Path):
    runtime = object.__new__(CommandCenterRuntime)
    runtime._lock = Lock()
    runtime.jobs_dir = tmp_path / "jobs"
    runtime.jobs_dir.mkdir()
    runtime.review_packets_path = tmp_path / "review_packets.json"
    runtime.review_packets_path.write_text(json.dumps({"ok": True, "packets": []}), encoding="utf-8")
    rows = [
        {
            "id": 83,
            "event_id": "blocked-dispatch",
            "channel_id": "command_center",
            "thread_ts": "blocked-dispatch",
            "agent_name": "tickets_agent",
            "status": "blocked",
            "result_text": (
                "BLOCKED\nWaiting for access.\n"
                "OPERATOR_ACTION_REQUIRED: Grant access."
            ),
            "needs_review": True,
            "review_reason": "Waiting for access.",
        },
        {
            "id": 84,
            "event_id": "failed-dispatch",
            "channel_id": "command_center",
            "thread_ts": "failed-dispatch",
            "agent_name": "tickets_agent",
            "status": "failed",
            "result_text": "FAILED\nWorker task failed.",
            "needs_review": True,
            "review_reason": "Worker task failed.",
        },
        {
            "id": 85,
            "event_id": "watcher-issue",
            "channel_id": "command_center",
            "thread_ts": "watcher-issue",
            "agent_name": "coding_agent",
            "status": "completed_with_issues",
            "result_text": "COMPLETED_WITH_ISSUES\nRecurring watcher issue.",
            "needs_review": True,
            "review_reason": "Recurring watcher issue.",
        },
        {
            "id": 86,
            "event_id": "completed-no-action",
            "channel_id": "command_center",
            "thread_ts": "completed-no-action",
            "agent_name": "tickets_agent",
            "status": "completed",
            "result_text": "COMPLETED\nWork finished.\nOPERATOR_ACTION_REQUIRED: NONE",
            "needs_review": True,
            "review_reason": "Legacy review bit.",
        },
    ]
    source_types = {
        83: "dispatch",
        84: "dispatch",
        85: "ops-email-watch",
        86: "dispatch",
    }
    runtime.state = SimpleNamespace(list_review_jobs=lambda limit=500: [dict(row) for row in rows])
    runtime._job_record_for_review_row = lambda row: {
        "sourceType": source_types[int(row["id"])],
        "payload": {
            "type": "salesforce-ticket-agent-prompt",
            "ticketNumber": str(347900 + int(row["id"])),
        },
    }

    assert runtime.review_packets()["packets"] == []


def test_recovery_review_required_row_without_investigation_does_not_render(tmp_path: Path):
    runtime = object.__new__(CommandCenterRuntime)
    runtime._lock = Lock()
    runtime.jobs_dir = tmp_path / "jobs"
    runtime.jobs_dir.mkdir()
    runtime.review_packets_path = tmp_path / "review_packets.json"
    runtime.review_packets_path.write_text(json.dumps({"ok": True, "packets": []}), encoding="utf-8")
    row = {
        "id": 87,
        "event_id": "restart-recovery",
        "channel_id": "command_center",
        "thread_ts": "restart-recovery",
        "agent_name": "coding_agent",
        "status": "recovery_review_required",
        "result_text": "Restart recovery safety note: a possibly mutating attempt was interrupted.",
        "needs_review": True,
        "review_reason": "Verify external state before replay.",
    }
    runtime.state = SimpleNamespace(list_review_jobs=lambda limit=500: [dict(row)])
    runtime._job_record_for_review_row = lambda _row: {
        "sourceType": "dispatch",
        "payload": {"ticketNumber": "347987"},
    }

    assert runtime.review_packets()["packets"] == []


def test_explicit_ticket_reviews_coalesce_into_one_stable_packet_with_latest_update():
    packets = [
        {
            "id": "job-review-91",
            "kind": "job_outcome",
            "bridgeJobId": 91,
            "sourceType": "dispatch",
            "ticketNumber": "347990",
            "outcome": "blocked",
            "agentName": "tickets_agent",
            "reviewVersion": 0,
            "agentResult": "BLOCKED\nWaiting for account identity.",
            "reviewReason": "Waiting for account identity.",
            "operatorActionRequired": True,
            "operatorAction": "Choose the verified account identity.",
            "createdAtUtc": "2026-07-13T12:00:00+00:00",
            "updatedAtUtc": "2026-07-13T12:05:00+00:00",
        },
        {
            "id": "job-review-92",
            "kind": "job_outcome",
            "bridgeJobId": 92,
            "sourceType": "review-packet-continue",
            "ticketNumber": "347990",
            "outcome": "failed",
            "agentName": "coding_agent",
            "reviewVersion": 2,
            "agentResult": "FAILED\nSalesforce note write could not be verified.",
            "reviewReason": "Salesforce note write could not be verified.",
            "operatorActionRequired": True,
            "operatorAction": "Choose whether to retry the verified note write.",
            "createdAtUtc": "2026-07-13T12:10:00+00:00",
            "updatedAtUtc": "2026-07-13T12:15:00+00:00",
        },
    ]

    grouped = _coalesce_recurring_review_packets(packets)

    assert len(grouped) == 1
    packet = grouped[0]
    assert packet["id"] == "review-ticket-347990"
    assert packet["coalescedBy"] == "ticket"
    assert packet["relatedBridgeJobIds"] == [91, 92]
    assert packet["occurrenceCount"] == 2
    assert packet["bridgeJobId"] == 92
    assert packet["parentReviewVersion"] == 2
    assert packet["reviewVersion"] == 4
    assert packet["agentResult"].startswith("FAILED")


def test_explicit_durable_ticket_review_replaces_older_static_packet_for_same_ticket(tmp_path: Path):
    runtime = object.__new__(CommandCenterRuntime)
    runtime._lock = Lock()
    runtime.jobs_dir = tmp_path / "jobs"
    runtime.jobs_dir.mkdir()
    runtime.review_packets_path = tmp_path / "review_packets.json"
    runtime.review_packets_path.write_text(
        json.dumps(
            {
                "ok": True,
                "packets": [
                    {
                        "id": "review-347991-static",
                        "bridgeJobId": 100,
                        "ticketNumber": "347991",
                        "agentName": "tickets_agent",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    row = {
        "id": 101,
        "event_id": "cc-101",
        "channel_id": "command_center",
        "thread_ts": "cc-101",
        "agent_name": "tickets_agent",
        "status": "completed",
        "request_text": "Continue ticket 347991",
        "result_text": (
            "COMPLETED\nIdentity research is verified.\n"
            "OPERATOR_ACTION_REQUIRED: Choose the verified account identity."
        ),
        "needs_review": True,
        "review_reason": "Choose the verified account identity.",
    }
    runtime.state = SimpleNamespace(list_review_jobs=lambda limit=500: [dict(row)])
    runtime._job_record_for_review_row = lambda _row: {
        "sourceType": "dispatch",
        "payload": {"ticketNumber": "347991", "type": "salesforce-ticket-agent-prompt"},
    }

    packets = runtime.review_packets()["packets"]

    assert len(packets) == 1
    assert packets[0]["id"] == "job-review-101"
    assert packets[0]["ticketNumber"] == "347991"


def test_explicit_recurring_watcher_reviews_coalesce_without_losing_job_ids():
    packets = [
        {
            "id": f"job-review-{job_id}",
            "kind": "job_outcome",
            "bridgeJobId": job_id,
            "sourceType": "ops-kpi-dashboard",
            "outcome": "completed_with_issues",
            "agentName": "coding_agent",
            "originalAgentName": "coding_agent",
            "status": status,
            "reviewVersion": version,
            "reviewReason": f"KPI refresh issue {job_id}",
            "technicalIssue": f"KPI refresh issue {job_id}",
            "operatorActionRequired": True,
            "operatorAction": "Choose whether to rerun the KPI refresh.",
            "createdAtUtc": f"2026-07-1{job_id - 1}T12:00:00+00:00",
            "updatedAtUtc": f"2026-07-1{job_id - 1}T12:05:00+00:00",
            "activeFollowupStatus": "running" if status == "followup_queued" else "",
        }
        for job_id, status, version in (
            (1, "needs_review", 0),
            (2, "followup_queued", 1),
            (3, "needs_review", 0),
        )
    ]

    grouped = _coalesce_recurring_review_packets(packets)

    assert len(grouped) == 1
    packet = grouped[0]
    assert packet["coalesced"] is True
    assert packet["occurrenceCount"] == 3
    assert packet["relatedBridgeJobIds"] == [1, 2, 3]
    assert packet["bridgeJobId"] == 2
    assert packet["status"] == "followup_queued"
    assert len(packet["occurrences"]) == 3


def test_review_followup_can_be_reassigned_to_a_configured_lane():
    runtime = object.__new__(CommandCenterRuntime)
    runtime.config = SimpleNamespace(
        agents={"tickets_agent": {}, "coding_agent": {}},
    )
    packet = {
        "id": "job-review-9",
        "kind": "job_outcome",
        "bridgeJobId": 9,
        "reviewVersion": 2,
        "agentName": "tickets_agent",
        "originalAgentName": "tickets_agent",
        "outcome": "blocked",
        "instruction": "Fix the implementation blocker.",
    }
    runtime._find_review_packet = lambda _packet_id: dict(packet)
    captured: dict[str, object] = {}

    def submit_prompt(**kwargs):
        captured.update(kwargs)
        return {
            "accepted": True,
            "job_id": "child",
            "bridge_job_id": 10,
            "agentName": kwargs["agent_name"],
            "sourceType": kwargs["source_type"],
        }

    runtime.submit_prompt = submit_prompt
    runtime._mark_review_followup_queued = lambda _packet, _result: None

    result = runtime.submit_review_packet_continue(
        {
            "packetId": "job-review-9",
            "instruction": "Move this to Taylor and verify the fix.",
            "targetAgent": "coding_agent",
        }
    )

    assert result["accepted"] is True
    assert captured["agent_name"] == "coding_agent"
    assert captured["payload"]["targetAgent"] == "coding_agent"
    assert captured["payload"]["originalAgentName"] == "tickets_agent"
    assert "Assigned follow-up agent/lane: coding_agent" in captured["prompt"]

    with pytest.raises(ValueError, match="Unknown review follow-up agent"):
        runtime.submit_review_packet_continue(
            {
                "packetId": "job-review-9",
                "instruction": "Use an unknown lane.",
                "targetAgent": "unknown_agent",
            }
        )


def test_verified_group_close_resolves_every_frozen_parent(tmp_path: Path):
    state = BridgeState(str(tmp_path / "bridge.sqlite3"))
    parent_ids = [_job(state) for _ in range(3)]
    for parent_id in parent_ids:
        assert state.mark_started(parent_id) is True
        assert state.mark_outcome(
            parent_id,
            "completed_with_issues",
            result_text="COMPLETED_WITH_ISSUES\nRecurring watcher issue.",
            review_reason="Recurring watcher issue.",
            review_required=True,
        ) is True

    child_id = _job(state)
    assert state.mark_review_followup_queued(parent_ids[0], child_id, expected_review_version=0) is True
    assert state.mark_started(child_id) is True
    assert state.mark_outcome(
        child_id,
        "completed",
        result_text="COMPLETED\nRecurring issue verified resolved.",
    ) is True

    runtime = object.__new__(CommandCenterRuntime)
    runtime.state = state
    runtime._lock = Lock()
    runtime._review_packet_lock = Lock()
    runtime.review_packets_path = tmp_path / "review_packets.json"
    runtime.review_packets_path.write_text(json.dumps({"ok": True, "packets": []}), encoding="utf-8")
    packet_id = "review-group-ops-kpi-dashboard-example"
    result = f"COMPLETED\nVerified shared readback. RESOLVED_JOB_REVIEW:{packet_id}"
    runtime._jobs = {
        "child": {
            "id": "child",
            "bridgeJobId": child_id,
            "sourceType": "review-packet-close",
            "status": "completed",
            "result": result,
            "payload": {
                "packetId": packet_id,
                "reviewKind": "job_outcome",
                "parentBridgeJobId": parent_ids[0],
                "relatedBridgeJobIds": parent_ids,
                "reviewVersion": 0,
            },
        }
    }

    runtime._sync_review_packet_after_job("child", "coding_agent", result)

    rows = state.jobs_by_ids(set(parent_ids))
    assert all(rows[parent_id]["needs_review"] is False for parent_id in parent_ids)
    assert all(rows[parent_id]["review_status"] == "resolved" for parent_id in parent_ids)


def test_terminal_support_research_failure_updates_source_specific_review_state():
    runtime = object.__new__(CommandCenterRuntime)
    runtime._lock = Lock()
    runtime._jobs = {
        "failed": {
            "id": "failed",
            "sourceType": "ops-support-email-research",
            "status": "failed",
            "payload": {"supportEmailSourceKey": "source-1"},
        }
    }
    calls: list[tuple[str, str]] = []
    runtime._sync_review_packet_after_job = lambda job, _agent, _result: calls.append(("sync", job))
    runtime._record_support_email_review_ready = lambda job: calls.append(("ready", job))
    runtime._record_support_email_review_issue = (
        lambda job, _outcome, _result: calls.append(("issue", job))
    )

    runtime._finalize_terminal_job_review_state("failed", "tickets_agent", "FAILED\nWorker admission failed.")

    assert calls == [("sync", "failed"), ("issue", "failed")]


def test_support_research_failure_stays_on_source_item_without_review_packet(tmp_path: Path):
    runtime = object.__new__(CommandCenterRuntime)
    runtime._lock = Lock()
    runtime.config = SimpleNamespace(defaults={})
    runtime._jobs = {
        "failed": {
            "id": "failed",
            "bridgeJobId": 44,
            "sourceType": "ops-support-email-research",
            "status": "failed",
            "payload": {"supportEmailSourceKey": "source-1"},
        }
    }
    runtime.support_email_intake_path = tmp_path / "ops_support_email_intake.json"
    runtime.support_email_intake_path.write_text(
        json.dumps({"emails": [{"sourceKey": "source-1", "alex": {"status": "queued"}}]}),
        encoding="utf-8",
    )

    runtime._record_support_email_review_issue(
        "failed",
        AgentOutcome(AgentOutcomeStatus.FAILED),
        "FAILED\nWorker admission failed.",
    )

    item = json.loads(runtime.support_email_intake_path.read_text(encoding="utf-8"))["emails"][0]
    assert item["alex"]["status"] == "failed"
    assert item["alex"]["reviewPacketId"] == ""


def test_support_research_completion_without_packet_is_not_marked_review_ready(tmp_path: Path):
    runtime = object.__new__(CommandCenterRuntime)
    runtime._lock = Lock()
    runtime.config = SimpleNamespace(defaults={})
    runtime._jobs = {
        "complete": {
            "id": "complete",
            "sourceType": "ops-support-email-research",
            "status": "completed",
            "createdAtUtc": "2026-07-14T18:00:00+00:00",
            "payload": {
                "supportEmailSourceKey": "source-1",
                "ticketNumber": "347166",
            },
        }
    }
    runtime.support_email_intake_path = tmp_path / "ops_support_email_intake.json"
    runtime.support_email_intake_path.write_text(
        json.dumps({"emails": [{"sourceKey": "source-1", "alex": {"status": "queued"}}]}),
        encoding="utf-8",
    )
    runtime._find_review_packet_for_ticket = lambda _ticket_number: None

    runtime._record_support_email_review_ready("complete")

    item = json.loads(runtime.support_email_intake_path.read_text(encoding="utf-8"))["emails"][0]
    assert item["alex"]["status"] == "research_complete"
    assert item["alex"]["reviewPacketId"] == ""


def test_failed_requested_slack_upload_downgrades_completion_to_review(monkeypatch):
    monkeypatch.setattr(
        slack_app,
        "_upload_directed_files",
        lambda *_args, **_kwargs: ["File upload failed: report.xlsx"],
    )

    result, outcome = slack_app._prepare_slack_delivery_result(
        SimpleNamespace(defaults={}),
        "coding_agent",
        {},
        object(),
        SimpleNamespace(),
        "COMPLETED\nMain work finished.\nUPLOAD_FILE: C:/safe/report.xlsx",
        AgentOutcome(AgentOutcomeStatus.COMPLETED),
    )

    assert outcome.status is AgentOutcomeStatus.COMPLETED_WITH_ISSUES
    assert outcome.needs_review is True
    assert result.startswith("COMPLETED_WITH_ISSUES")
    assert "File upload failed" in result
