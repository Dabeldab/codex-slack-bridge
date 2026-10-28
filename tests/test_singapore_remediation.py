from __future__ import annotations

# AgentChat/coding_agent 2026-07-13T18:24:18-04:00: verify Singapore failures remain catalog-only without tickets or reviews.

import json
from pathlib import Path
from threading import Lock

import pytest

from codex_slack_bridge.command_center_server import (
    CommandCenterRuntime,
    _carry_forward_singapore_remediation,
    _singapore_ftp_notification_required,
    _singapore_ftp_scan_complete,
    _singapore_ftp_shared_chat_enabled,
    build_ops_singapore_remediation_ticket_prompt,
)
from codex_slack_bridge.singapore_remediation import (
    load_salesforce_identity_map,
    merge_remediation_groups,
    remediation_groups,
)


def _cache() -> dict:
    return {
        "status": "ok",
        "upload": {
            "status": "completed",
            "details": [
                {
                    "sourceMessageId": "auth-message",
                    "sourceThreadId": "auth-thread",
                    "machineId": "5000393",
                    "serverKey": "5000393",
                    "result": "server_auth_blocked",
                    "failureCategory": "authentication",
                    "configuredServer": True,
                    "retiredServer": False,
                },
                {
                    "sourceMessageId": "retired-message",
                    "machineId": "9000087",
                    "serverKey": "9000087",
                    "result": "retired_machine_pending_handoff",
                    "failureCategory": "retired_server",
                    "configuredServer": True,
                    "retiredServer": True,
                    "retirementVerified": True,
                },
                {
                    "sourceMessageId": "transfer-message",
                    "machineId": "6000123",
                    "serverKey": "6000123",
                    "result": "upload_or_verification_failed",
                    "failureCategory": "transfer_or_verification",
                    "configuredServer": True,
                    "retiredServer": False,
                },
                {
                    "sourceMessageId": "unmatched-message",
                    "machineId": "7000123",
                    "machineIds": ["7000123"],
                    "result": "unknown_machine",
                    "failureCategory": "unknown_machine",
                    "configuredServer": False,
                    "retiredServer": False,
                },
                {
                    "sourceMessageId": "ambiguous-unmatched",
                    "machineIds": ["7000123", "7000456"],
                    "result": "unknown_machine",
                    "failureCategory": "unknown_machine",
                    "configuredServer": False,
                    "retiredServer": False,
                },
                {
                    "sourceMessageId": "unsafe-auth",
                    "machineId": "unknown",
                    "result": "server_auth_blocked",
                    "failureCategory": "authentication",
                    "configuredServer": False,
                    "retiredServer": False,
                },
            ],
        },
        "configChanges": {
            "results": [
                {
                    "sourceMessageId": "config-message",
                    "sourceThreadId": "config-thread",
                    "machineId": "1500204",
                    "status": "updated",
                    "requestKind": "existing_config",
                    "configVerified": True,
                    "changedFields": ["host", "password"],
                },
                {
                    "sourceMessageId": "new-interface-message",
                    "sourceThreadId": "new-interface-thread",
                    "machineId": "1700204",
                    "status": "new_interface_request",
                    "requestKind": "new_interface",
                    "configVerified": False,
                    "changedFields": [],
                },
                {
                    "sourceMessageId": "unverified-config",
                    "machineId": "bad",
                    "status": "updated",
                    "configVerified": False,
                },
            ]
        },
        "zoomMessage": {"status": "not_needed"},
        "mailbox": {"status": "completed"},
    }


def test_remediation_groups_enforce_category_evidence_and_stable_keys():
    groups = remediation_groups(_cache())

    assert {group["category"] for group in groups} == {
        "active_auth_failure",
        "active_transfer_failure",
        "new_interface_request",
        "unmatched_mapping",
        "verified_config_change",
    }
    assert not any("retired-message" in group["sourceMessageIds"] for group in groups)
    assert not any("unsafe-auth" in group["sourceMessageIds"] for group in groups)
    assert not any("unverified-config" in group["sourceMessageIds"] for group in groups)
    auth = next(group for group in groups if group["category"] == "active_auth_failure")
    assert auth["machineId"] == "5000393"
    assert auth["sourceMessageIds"] == ["auth-message"]
    transfer = next(group for group in groups if group["category"] == "active_transfer_failure")
    assert transfer["machineId"] == "6000123"
    unmatched = next(group for group in groups if group["category"] == "unmatched_mapping")
    assert unmatched["machineId"] == "7000123"
    assert unmatched["sourceMessageIds"] == ["unmatched-message"]
    assert not any("ambiguous-unmatched" in group["sourceMessageIds"] for group in groups)
    config = next(group for group in groups if group["category"] == "verified_config_change")
    assert config["changedFields"] == ["host", "password"]
    assert config["stableKey"].startswith("singapore-remediation:verified_config_change:1500204:")
    ticket_eligible = next(group for group in groups if group["category"] == "new_interface_request")
    assert ticket_eligible["requestKind"] == "new_interface"
    assert ticket_eligible["status"] == "pending_ticket"
    assert ticket_eligible["sourceMessageIds"] == ["new-interface-message"]
    assert all(
        group["status"] == "cataloged_no_ticket"
        for group in groups
        if group["category"] != "new_interface_request"
    )


def test_automated_failures_are_cataloged_without_ticket_attention():
    cache = _cache()
    cache["configChanges"]["results"] = []
    merge_remediation_groups(cache, remediation_groups(cache))

    assert {group["category"] for group in remediation_groups(cache)} == {
        "active_auth_failure",
        "active_transfer_failure",
        "unmatched_mapping",
    }
    assert all(
        group["status"] == "cataloged_no_ticket"
        for group in cache["remediation"]["groups"]
    )
    assert _singapore_ftp_notification_required(cache) is False


def test_runtime_catalogs_singapore_failures_without_ticket_or_review_handoff(tmp_path):
    runtime = object.__new__(CommandCenterRuntime)
    runtime.singapore_ftp_path = tmp_path / "ops_singapore_ftp.json"
    runtime.singapore_salesforce_identity_map_path = tmp_path / "salesforce-identity-map.json"
    runtime.singapore_salesforce_identity_map_path.write_text("{}", encoding="utf-8")
    runtime._submit_singapore_remediation_ticket = lambda *_args, **_kwargs: (_ for _ in ()).throw(
        AssertionError("Singapore ticket creation must remain disabled")
    )
    cache = _cache()
    cache["upload"]["status"] = "completed_with_issues"
    cache["configChanges"]["results"] = [
        item
        for item in cache["configChanges"]["results"]
        if item.get("status") != "new_interface_request"
    ]

    result = runtime._queue_singapore_remediation(cache)

    assert result["queued"] == 0
    assert result["groups"] == 4
    assert result["ticketEligibleGroups"] == 0
    assert result["cataloged"] > 0
    persisted = json.loads(runtime.singapore_ftp_path.read_text(encoding="utf-8"))
    remediation = persisted["remediation"]
    assert remediation["salesforceTicketingEnabled"] is False
    assert remediation["queuedTicketJobs"] == 0
    assert all(group["status"] == "cataloged_no_ticket" for group in remediation["groups"])
    assert all(group["ticketJobId"] == "" for group in remediation["groups"])
    assert all(group["attempts"] == 0 for group in remediation["groups"])
    assert all(group["nextEligibleAtUtc"] == "" for group in remediation["groups"])
    assert _singapore_ftp_scan_complete(persisted) is True
    assert _singapore_ftp_notification_required(persisted) is False


def test_customer_protocol_failure_still_requires_attention():
    cache = _cache()
    cache["configChanges"]["results"] = []
    cache["automaticReplies"] = {"failedCount": 1}

    assert _singapore_ftp_notification_required(cache) is True


def test_singapore_shared_chat_notifications_are_opt_in():
    assert _singapore_ftp_shared_chat_enabled({}) is False
    assert _singapore_ftp_shared_chat_enabled(
        {"ops_singapore_ftp_shared_chat_notifications_enabled": False}
    ) is False
    assert _singapore_ftp_shared_chat_enabled(
        {"ops_singapore_ftp_shared_chat_notifications_enabled": True}
    ) is True


def test_new_interface_ticket_prompt_requires_documented_salesforce_routes(tmp_path):
    group = next(
        group for group in remediation_groups(_cache()) if group["category"] == "new_interface_request"
    )
    prompt = build_ops_singapore_remediation_ticket_prompt(
        tmp_path / "ticket-result.json",
        group=group,
        ticket_created_by="Command Center",
    )

    assert "docs/agent-tools/salesforce.md" in prompt
    assert "auto-tickets/logmein-connector/src/salesforce_api.py" in prompt
    assert "second-path regroup/read-only capability check" in prompt
    assert "Never use Demo Nova Cafe, a fallback, test, or guessed account" in prompt
    assert "do not modify source, config, tests, or policy files" in prompt
    assert "exact Salesforce lookup for machine id" in prompt
    assert "category is exactly `new_interface_request`" in prompt
    assert "requestKind is `new_interface`" in prompt
    assert "must never create a Salesforce ticket or review packet" in prompt
    assert "retired/deactivated interface notice must be ignored" in prompt
    assert "Keep the stable key and source ids only in the private gateway" in prompt
    assert "Never put stable keys, Gmail message/thread ids" in prompt
    assert "private gateway source receipt" in prompt


def test_private_identity_map_attaches_only_confirmed_sanitized_exact_hints(tmp_path):
    identity_path = tmp_path / "salesforce-identity-map.json"
    identity_path.write_text(
        json.dumps(
            {
                "version": 1,
                "mappings": {
                    "1700204": {
                        "identityStatus": "confirmed_with_alias_mismatch",
                        "salesforce": {
                            "account": {"id": "0018V00002MrKVJQA3", "name": "must-not-leak"},
                            "location": {"id": "a098V000018iMfeQAE", "status": "Active"},
                        },
                        "integration": {"status": ""},
                        "product": {"ticketRecordType": "1. NOVA Classic"},
                        "caveats": ["untrusted_free_text"],
                        "password": "must-not-leak",
                    },
                    "5000393": {
                        "identityStatus": "candidate",
                        "accountId": "001A000000XrMdXIAV",
                        "locationId": "a09A000000fhRp7IAE",
                    },
                },
            }
        ),
        encoding="utf-8",
    )

    identity_map = load_salesforce_identity_map(identity_path)
    groups = remediation_groups(_cache(), identity_map=identity_map)
    hinted = next(group for group in groups if group["machineId"] == "1700204")

    assert identity_map == {
        "1700204": {
            "machineId": "1700204",
            "identityStatus": "confirmed_with_alias_mismatch",
            "accountId": "0018V00002MrKVJQA3",
            "locationId": "a098V000018iMfeQAE",
            "product": "Classic",
            "integrationStatus": "",
            "locationStatus": "Active",
            "caveats": ["alias_mismatch"],
        }
    }
    assert hinted["category"] == "new_interface_request"
    assert hinted["salesforceIdentityHint"] == identity_map["1700204"]

    prompt = build_ops_singapore_remediation_ticket_prompt(
        tmp_path / "ticket-result.json",
        group=hinted,
        ticket_created_by="Command Center",
    )
    assert "0018V00002MrKVJQA3" in prompt
    assert "a098V000018iMfeQAE" in prompt
    assert "`Location.Account__c` equals the exact Account id" in prompt
    assert "must-not-leak" not in prompt


def test_merge_preserves_handoff_state_and_pending_group_blocks_complete():
    cache = _cache()
    groups = remediation_groups(cache)
    pending = next(group for group in groups if group["category"] == "new_interface_request")
    cache["remediation"] = {
        "groups": [
            {
                "stableKey": pending["stableKey"],
                "category": "new_interface_request",
                "status": "ticket_queued",
                "ticketJobId": "job-1",
                "attempts": 2,
                "nextEligibleAtUtc": "2026-07-13T07:00:00+00:00",
            }
        ]
    }

    merge_remediation_groups(cache, groups)

    preserved = next(
        group for group in cache["remediation"]["groups"] if group["stableKey"] == pending["stableKey"]
    )
    assert preserved["status"] == "ticket_queued"
    assert preserved["ticketJobId"] == "job-1"
    assert preserved["attempts"] == 2
    assert preserved["nextEligibleAtUtc"] == "2026-07-13T07:00:00+00:00"
    assert _singapore_ftp_scan_complete(cache) is False


def test_queue_catalogs_operational_groups_and_submits_only_new_interface(tmp_path):
    runtime = object.__new__(CommandCenterRuntime)
    runtime.bridge_root = tmp_path
    runtime.singapore_ftp_path = tmp_path / "ops_singapore_ftp.json"
    runtime.singapore_salesforce_identity_map_path = tmp_path / "missing-identity-map.json"
    runtime.config = type("Config", (), {"defaults": {}})()
    submitted: list[tuple[str, int]] = []
    runtime._submit_singapore_remediation_ticket = (
        lambda group, *, attempt: submitted.append((group["category"], attempt))
        or {"accepted": True, "job_id": "new-interface-ticket-job"}
    )
    cache = _cache()

    result = runtime._queue_singapore_remediation(cache)

    assert submitted == [("new_interface_request", 1)]
    assert result == {
        "queued": 1,
        "groups": 5,
        "ticketEligibleGroups": 1,
        "cataloged": 4,
    }
    groups = cache["remediation"]["groups"]
    assert not any(group["machineId"] == "9000087" for group in groups)
    assert next(group for group in groups if group["category"] == "new_interface_request")[
        "status"
    ] == "ticket_queued"
    assert all(
        group["status"] == "cataloged_no_ticket"
        and group["ticketJobId"] == ""
        and group["attempts"] == 0
        for group in groups
        if group["category"] != "new_interface_request"
    )
    assert cache["remediation"]["salesforceTicketPolicy"] == "new_interface_requests_only"


def test_headless_cache_rewrite_carries_forward_remediation_retry_state():
    previous = {
        "remediation": {
            "schemaVersion": 1,
            "groups": [
                {
                    "stableKey": "singapore-remediation:new_interface_request:2000117:key",
                    "category": "new_interface_request",
                    "status": "ticket_blocked",
                    "attempts": 1,
                }
            ],
        }
    }
    current = {"status": "partial", "upload": {"details": []}}

    returned = _carry_forward_singapore_remediation(current, previous)

    assert returned is current
    assert current["remediation"] == previous["remediation"]


def test_empty_scan_keeps_only_pending_new_interface_retry_state():
    cache = {
        "remediation": {
            "schemaVersion": 1,
            "groups": [
                {
                    "stableKey": "singapore-remediation:new_interface_request:2000117:key",
                    "category": "new_interface_request",
                    "machineId": "2000117",
                    "status": "ticket_queued",
                    "ticketJobId": "ticket-job-2",
                    "attempts": 2,
                    "nextEligibleAtUtc": "2026-07-13T08:00:00+00:00",
                },
                {
                    "stableKey": "singapore-remediation:active_auth_failure:done:key",
                    "category": "active_auth_failure",
                    "status": "ticket_queued",
                },
            ],
        }
    }

    merge_remediation_groups(cache, [])

    assert cache["remediation"]["groups"] == [
        {
            "stableKey": "singapore-remediation:new_interface_request:2000117:key",
            "category": "new_interface_request",
            "machineId": "2000117",
            "status": "ticket_queued",
            "ticketJobId": "ticket-job-2",
            "attempts": 2,
            "nextEligibleAtUtc": "2026-07-13T08:00:00+00:00",
        }
    ]


def test_new_interface_ticket_finalizer_queues_alex_before_grouped_gmail_read(tmp_path):
    runtime = object.__new__(CommandCenterRuntime)
    runtime._lock = Lock()
    runtime.singapore_ftp_path = tmp_path / "ops_singapore_ftp.json"
    output_path = tmp_path / "ticket-result.json"
    stable_key = "singapore-remediation:new_interface_request:5000393:key"
    group = {
        "stableKey": stable_key,
        "category": "new_interface_request",
        "requestKind": "new_interface",
        "machineId": "5000393",
        "sourceMessageIds": ["message-1", "message-2"],
        "sourceThreadIds": ["thread-1"],
        "changedFields": ["host"],
        "status": "ticket_queued",
    }
    runtime._jobs = {
        "ticket-job": {
            "payload": {
                "stableKey": stable_key,
                "remediationGroup": group,
                "outputPath": str(output_path),
            }
        }
    }
    runtime.singapore_ftp_path.write_text(json.dumps({"remediation": {"groups": [group]}}), encoding="utf-8")
    output_path.write_text(
        json.dumps(
            {
                "stableKey": stable_key,
                "status": "ok",
                "result": "created",
                "accountId": "001-account",
                "account": "Real Cafe",
                "ticket": {
                    "id": "a0G-ticket",
                    "number": "347300",
                    "recordType": "1. NOVA Classic",
                    "mainIssue": "Software",
                    "technicalIssue": "Other",
                },
                "blockers": [],
            }
        ),
        encoding="utf-8",
    )
    events: list[str] = []
    runtime._submit_support_email_research = lambda item: events.append("alex") or {
        "accepted": True,
        "job_id": "alex-job",
    }
    runtime._find_review_packet_for_ticket = lambda _ticket_number: None
    runtime._apply_cached_gmail_label_action = lambda *args, **kwargs: events.append(
        f"gmail:{args[0].get('id') or args[0].get('threadId')}"
    ) or {"ok": True, "verified": True, "modifiedCount": 1}

    runtime._finalize_singapore_remediation_ticket("ticket-job")

    assert events == ["alex"]
    updated = json.loads(runtime.singapore_ftp_path.read_text(encoding="utf-8"))["remediation"]["groups"][0]
    assert updated["status"] == "handoff_pending"
    assert updated["alex"]["status"] == "queued"
    assert updated["alex"]["jobId"] == "alex-job"
    assert "gmail" not in updated
    assert "before Gmail acknowledgement" in updated["blocker"]
    assert updated["nextEligibleAtUtc"]


def test_ticket_submit_and_finalizer_fail_closed_for_operational_group(tmp_path):
    runtime = object.__new__(CommandCenterRuntime)
    runtime._lock = Lock()
    runtime.singapore_ftp_path = tmp_path / "ops_singapore_ftp.json"
    output_path = tmp_path / "ticket-result.json"
    stable_key = "singapore-remediation:active_transfer_failure:5000393:key"
    group = {
        "stableKey": stable_key,
        "category": "active_transfer_failure",
        "machineId": "5000393",
        "sourceMessageIds": ["message-1"],
        "sourceThreadIds": ["thread-1"],
        "status": "ticket_queued",
    }
    runtime._jobs = {
        "ticket-job": {
            "payload": {
                "stableKey": stable_key,
                "remediationGroup": group,
                "outputPath": str(output_path),
            }
        }
    }
    runtime.singapore_ftp_path.write_text(json.dumps({"remediation": {"groups": [group]}}), encoding="utf-8")
    runtime._submit_support_email_research = lambda _item: pytest.fail("operational group reached Alex")
    runtime._apply_cached_gmail_label_action = lambda *_args, **_kwargs: pytest.fail(
        "operational group reached Gmail mutation"
    )

    with pytest.raises(ValueError, match="only for explicit new Singapore"):
        runtime._submit_singapore_remediation_ticket(group, attempt=1)

    runtime._finalize_singapore_remediation_ticket("ticket-job")

    updated = json.loads(runtime.singapore_ftp_path.read_text(encoding="utf-8"))["remediation"]["groups"][0]
    assert updated["status"] == "cataloged_no_ticket"
    assert updated["ticketJobId"] == ""
    assert updated["ticket"] == {}
    assert updated["alex"] == {}
    assert updated["gmail"] == {}
    assert updated["nextEligibleAtUtc"] == ""
