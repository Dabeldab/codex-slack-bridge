import json
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

# AgentChat/direct_codex 2026-07-16T10:30:00-04:00: verify daily auth acknowledgement and retirement policy.

import pytest

import codex_slack_bridge.singapore_ftp_runner as singapore_runner
from codex_slack_bridge.singapore_routing import format_singapore_chat_outcome

from codex_slack_bridge.singapore_ftp_runner import (
    _acknowledge_auth_failure_sources,
    _authenticate_gmail_noninteractive,
    _build_cache,
    _build_zoom_message,
    _completed_source_message_ids,
    _delivery_date_key,
    _format_short_dates,
    _mark_gmail_messages_read_verified,
    _partition_mixed_source_items,
    _partition_date_delivery_items,
    _prior_delivery_for_batch,
    _prior_zoom_delivery,
    _read_non_submission_outbox,
    _read_pending_gmail_read_ids,
    _read_processed_message_ids,
    _read_date_delivery_history,
    _record_date_delivery,
    _safe_upload_details,
    _send_zoom_message,
    _select_zoom_delivery_batch,
    _write_non_submission_outbox,
    _write_processed_message_ids,
    _write_date_delivery_history,
    _update_retirement_evidence_and_apply,
    acknowledge_cached_auth_failures,
    apply_server_patch,
)


def test_unreadable_prior_cache_produces_safe_blocked_result_instead_of_crashing(tmp_path, monkeypatch):
    output = tmp_path / "ops_singapore_ftp.json"
    monkeypatch.setattr(
        singapore_runner,
        "_preserved_remediation",
        lambda _path: (_ for _ in ()).throw(PermissionError("private path")),
    )

    result = singapore_runner.run_singapore_ftp_fast(
        uploader_root=str(tmp_path / "component"),
        state_dir=tmp_path / "state",
        server_config_path=tmp_path / "state" / "servers.json",
        output_path=output,
    )

    assert result["status"] == "blocked"
    assert result["blockers"] == ["background_service_blocked"]
    assert "private path" not in output.read_text(encoding="utf-8")


def test_nonsubmission_item_preserves_all_source_message_ids():
    item = singapore_runner._nonsubmission_item(
        SimpleNamespace(
            message_id="message-2",
            message_ids=["message-1", "message-2"],
            subject="Non Submission",
            email_date="today",
            mall="Mall",
            shop="Shop",
            machine_id="5000640",
            missing_dates=[date(2026, 7, 10)],
        )
    )

    assert item["sourceEmailIds"] == ["message-1", "message-2"]


def test_cloud_preflight_authenticates_and_counts_without_upload_or_send(tmp_path, monkeypatch):
    root = tmp_path / "component"
    state = tmp_path / "state"
    catalog = tmp_path / "servers.json"
    root.mkdir()
    catalog.write_text("{}", encoding="utf-8")

    class Execute:
        @staticmethod
        def execute():
            return {"emailAddress": "support@example.com"}

    class Users:
        @staticmethod
        def getProfile(*, userId):
            assert userId == "me"
            return Execute()

    class Gmail:
        @staticmethod
        def users():
            return Users()

    server_utils = SimpleNamespace(
        load_servers=lambda _path: {
            "active": {"host": "example"},
            "retired": {"retired": True},
        },
        is_retired_server=lambda row: bool(row.get("retired")),
    )
    monkeypatch.setattr(singapore_runner, "_ensure_private_state", lambda *_args: None)
    monkeypatch.setattr(
        singapore_runner,
        "_load_parser_modules",
        lambda *_args: {"gmail_client": object(), "server_utils": server_utils},
    )
    monkeypatch.setattr(singapore_runner, "_configure_private_state", lambda *_args: None)
    monkeypatch.setattr(singapore_runner, "_authenticate_gmail_noninteractive", lambda *_args: Gmail())
    monkeypatch.setattr(
        singapore_runner,
        "run_singapore_ftp_fast",
        lambda *_args, **_kwargs: pytest.fail("preflight attempted the live workflow"),
    )

    result = singapore_runner.preflight_singapore_runtime(
        uploader_root=root,
        state_dir=state,
        server_config_path=catalog,
    )

    assert result == {
        "status": "ready",
        "gmailAuthenticated": True,
        "configuredServerCount": 2,
        "activeServerCount": 1,
        "uploadAttempted": False,
        "messageSent": False,
    }


def test_processed_nonsubmission_journal_round_trips_message_ids(tmp_path):
    path = tmp_path / "processed.json"

    _write_processed_message_ids(
        path,
        {"message-2", "message-1"},
        delivery={"recipient": "Julio", "status": "sent", "sent": True, "messageId": "zoom-1"},
        pending_gmail_read_ids={"message-2"},
    )

    assert _read_processed_message_ids(path) == {"message-1", "message-2"}
    assert _read_pending_gmail_read_ids(path) == {"message-2"}
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["version"] == 2
    assert payload["lastVerifiedDelivery"] == {
        "recipient": "Julio",
        "status": "sent",
        "sent": True,
        "messageId": "zoom-1",
        "sentAtUtc": "",
    }


def test_zoom_journal_seeds_date_level_delivery_history_and_latest_parent(tmp_path):
    journal = tmp_path / "zoom-team-chat-messages.jsonl"
    journal.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "status": "sent",
                        "messageId": "zoom-1",
                        "messageBody": (
                            "Hey Julio, can you please resubmit these Singapore "
                            "integrations? 8000640: 7/26. Thanks."
                        ),
                        "sentAtUtc": "2026-07-29T18:14:13Z",
                    }
                ),
                json.dumps(
                    {
                        "status": "sent",
                        "messageId": "zoom-2",
                        "messageBody": (
                            "can you please resubmit these Singapore integrations? "
                            "8000640: 7/26. Thanks."
                        ),
                        "sentAtUtc": "2026-07-30T00:19:24Z",
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    history = _read_date_delivery_history(
        tmp_path / "date-deliveries.json",
        team_chat_journal_path=journal,
    )

    assert history["dates"]["8000640|2026-07-26"]["threadRootMessageId"] == "zoom-2"


def test_zoom_history_ignores_an_unrelated_machine_date_message(tmp_path):
    journal = tmp_path / "zoom-team-chat-messages.jsonl"
    journal.write_text(
        json.dumps(
            {
                "status": "sent",
                "messageId": "unrelated-1",
                "messageBody": "Please check machine 8000640: 7/26. Thanks.",
                "sentAtUtc": "2026-07-30T12:00:00+00:00",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    history = _read_date_delivery_history(
        tmp_path / "missing-date-history.json",
        team_chat_journal_path=journal,
    )

    assert history["dates"] == {}


def test_date_level_partition_uses_reminder_for_prior_date_and_new_send_for_new_date():
    item = {
        "machineId": "8000640",
        "dates": ["2026-07-26", "2026-07-27"],
        "sourceEmailIds": ["gmail-new"],
    }
    history = {
        "dates": {
            "8000640|2026-07-26": {
                "machineId": "8000640",
                "date": "2026-07-26",
                "threadRootMessageId": "zoom-prior",
                "acknowledgedSourceMessageIds": ["gmail-old"],
            }
        }
    }

    new_items, reminders = _partition_date_delivery_items([item], history)

    assert new_items == [{**item, "dates": ["2026-07-27"]}]
    assert reminders == {
        "zoom-prior": [{**item, "dates": ["2026-07-26"]}]
    }


def test_date_delivery_acknowledges_source_only_after_new_and_reminder_actions():
    item = {
        "machineId": "8000640",
        "dates": ["2026-07-26", "2026-07-27"],
        "sourceEmailIds": ["gmail-new"],
    }
    history = {
        "dates": {
            "8000640|2026-07-26": {
                "machineId": "8000640",
                "date": "2026-07-26",
                "threadRootMessageId": "zoom-prior",
                "acknowledgedSourceMessageIds": [],
            }
        }
    }
    _record_date_delivery(
        history,
        items=[{**item, "dates": ["2026-07-27"]}],
        delivery={"messageId": "zoom-new", "sentAtUtc": "2026-07-30T12:00:00Z"},
    )
    assert _completed_source_message_ids([item], history) == set()

    _record_date_delivery(
        history,
        items=[{**item, "dates": ["2026-07-26"]}],
        delivery={"messageId": "zoom-reminder", "sentAtUtc": "2026-07-30T12:01:00Z"},
        reply_to_message_id="zoom-prior",
        reminder=True,
    )

    assert _completed_source_message_ids([item], history) == {"gmail-new"}
    assert (
        history["dates"][_delivery_date_key("8000640", "2026-07-26")][
            "threadRootMessageId"
        ]
        == "zoom-prior"
    )


def test_processed_journal_preserves_delivery_while_gmail_retry_set_changes(tmp_path):
    path = tmp_path / "processed.json"
    delivery = {
        "recipient": "Julio",
        "status": "sent",
        "sent": True,
        "messageId": "zoom-1",
    }
    _write_processed_message_ids(
        path,
        {"message-1", "message-2"},
        delivery=delivery,
        pending_gmail_read_ids={"message-1", "message-2"},
    )

    _write_processed_message_ids(
        path,
        {"message-1", "message-2"},
        pending_gmail_read_ids={"message-2"},
    )

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["gmailReadPendingMessageIds"] == ["message-2"]
    assert payload["lastVerifiedDelivery"]["messageId"] == "zoom-1"


def test_first_zero_sales_only_journal_write_does_not_require_prior_file(tmp_path):
    path = tmp_path / "processed.json"

    _write_processed_message_ids(
        path,
        {"zero-sales-message-1"},
        pending_gmail_read_ids=set(),
    )

    assert _read_processed_message_ids(path) == {"zero-sales-message-1"}
    assert _read_pending_gmail_read_ids(path) == set()


def test_corrupt_processed_journal_blocks_instead_of_failing_open(tmp_path):
    path = tmp_path / "processed.json"
    path.write_text("{not-json", encoding="utf-8")

    with pytest.raises(RuntimeError, match="refusing to rediscover or resend"):
        _read_processed_message_ids(path)
    with pytest.raises(RuntimeError, match="refusing to rediscover or resend"):
        _read_pending_gmail_read_ids(path)
    with pytest.raises(RuntimeError, match="refusing to rediscover or resend"):
        _write_processed_message_ids(
            path,
            {"message-1"},
            pending_gmail_read_ids=set(),
        )

    assert path.read_text(encoding="utf-8") == "{not-json"


def test_upload_details_keep_handoff_ids_and_drop_connection_secrets():
    details = _safe_upload_details(
        {
            "messageResults": [
                {
                    "sourceMessageId": "message-1",
                    "sourceThreadId": "thread-1",
                    "machineId": "5000393",
                    "serverKey": "5000393",
                    "result": "server_auth_blocked",
                    "failureCategory": "authentication",
                    "configuredServer": True,
                    "retiredServer": False,
                    "retryAfterUtc": "2026-07-13T06:00:00Z",
                    "circuitState": "open",
                    "filename": "secret.csv",
                    "host": "secret.example",
                    "username": "secret-user",
                    "remotePath": "/secret/path",
                    "hash": "secret-hash",
                }
            ]
        }
    )

    assert details[0]["sourceMessageId"] == "message-1"
    assert details[0]["failureCategory"] == "authentication"
    assert details[0]["configuredServer"] is True
    assert not {"filename", "host", "username", "remotePath", "hash"}.intersection(details[0])


def test_cache_catalogs_verified_existing_config_change_without_ticket_flags(tmp_path):
    cache = _build_cache(
        root=tmp_path / "repo",
        private_state=tmp_path / "state",
        server_config_path=tmp_path / "state" / "servers.json",
        items=[],
        zoom_result={"status": "not_needed", "sent": False},
        source_message_ids=[],
        marked_read_count=0,
        blockers=[],
        upload_result={
            "status": "complete",
            "uploadedFiles": 0,
            "alreadyPresentFiles": 0,
            "markedReadMessages": 0,
            "failedMessages": 0,
            "unmatchedMessages": 0,
            "authBlockedServers": 0,
            "catalogStatusCounts": {"working": 2},
            "autoReply": {"matched": 0, "replied": 0, "failed": 0, "markedRead": 0},
        },
        config_change_results=[
            {
                "sourceMessageId": "message-1",
                "sourceThreadId": "thread-1",
                "machineId": "5000393",
                "status": "updated",
                "requestKind": "existing_config",
                "reason": "",
                "changedFields": ["host", "password", "port"],
                "configVerified": True,
                "markedRead": True,
                "gmailReadbackVerified": True,
                "gmailReadbackStatus": "verified_read",
            }
        ],
        non_submission_reviewed=False,
    )

    assert cache["status"] == "ok"
    assert cache["configChanges"]["verifiedCount"] == 1
    assert cache["configChanges"]["results"][0]["changedFields"] == ["host", "password", "port"]
    assert cache["configChanges"]["results"][0]["requestKind"] == "existing_config"
    assert cache["configChanges"]["markedReadCount"] == 1
    assert cache["configChanges"]["gmailReadbackFailedCount"] == 0
    assert cache["configChanges"]["retryableCount"] == 0
    assert cache["configChanges"]["results"][0]["gmailReadbackVerified"] is True
    assert cache["configChanges"]["results"][0]["gmailReadbackStatus"] == "verified_read"
    assert cache["configChanges"]["results"][0]["retryable"] is False
    assert cache["integrationCatalog"]["statusCounts"] == {"working": 2}
    assert "path" not in cache["integrationCatalog"]
    assert "moduleRoot" not in cache
    assert "stateDir" not in cache
    assert "serverConfigPath" not in cache
    assert cache["approvedActions"]["queueSalesforceTicketsForOperationalOutcomes"] is False
    assert cache["approvedActions"]["queueNeedsReviewForOperationalOutcomes"] is False
    assert cache["approvedActions"]["queueTicketOnlyForExplicitNewInterfaceRequest"] is True


def test_blocked_cache_drops_exception_text_and_private_paths(tmp_path):
    cache = singapore_runner._blocked_cache(
        tmp_path / "private-uploader",
        tmp_path / "private-state",
        "Julio",
        RuntimeError(f"token=secret-value path={tmp_path / 'private-state' / 'servers.json'}"),
    )

    serialized = json.dumps(cache)
    assert "secret-value" not in serialized
    assert str(tmp_path) not in serialized
    assert "servers.json" not in serialized
    assert "RuntimeError" not in serialized
    assert cache["blockers"] == ["background_service_blocked"]


def test_config_change_sanitizer_passes_new_interface_and_readback_without_external_secrets():
    results = singapore_runner._safe_config_change_results(
        [
            {
                "sourceMessageId": "message-2",
                "sourceThreadId": "thread-2",
                "machineId": "2000117",
                "status": "new_interface_request",
                "requestKind": "new_interface",
                "reason": "host=secret.example password=hunter2 token=super-secret",
                "password": "hunter2",
                "host": "secret.example",
                "gmailReadbackVerified": True,
                "gmailReadbackStatus": "verified_read",
            }
        ]
    )

    assert results == [
        {
            "sourceMessageId": "message-2",
            "sourceThreadId": "thread-2",
            "machineId": "2000117",
            "status": "new_interface_request",
            "requestKind": "new_interface",
            "reason": "",
            "changedFields": [],
            "configVerified": False,
            "retryable": False,
            "createdServer": False,
            "authBackoffCleared": False,
            "markedRead": False,
            "gmailReadbackVerified": True,
            "gmailReadbackStatus": "verified_read",
        }
    ]
    serialized = json.dumps(results).lower()
    assert "hunter2" not in serialized
    assert "secret.example" not in serialized
    assert "super-secret" not in serialized


def test_requested_reactivation_without_matching_trusted_source_is_retryable():
    results = []

    singapore_runner._ensure_requested_reactivation_outcome(results, "5000393")

    assert results == [
        {
            "sourceMessageId": "",
            "sourceThreadId": "",
            "machineId": "5000393",
            "status": "blocked",
            "requestKind": "reactivation",
            "reason": "",
            "changedFields": [],
            "configVerified": False,
            "retryable": True,
            "createdServer": False,
            "authBackoffCleared": False,
            "markedRead": False,
            "gmailReadbackVerified": False,
            "gmailReadbackStatus": "not_attempted",
        }
    ]
    safe = singapore_runner._safe_config_change_results(results)
    assert safe[0]["status"] == "blocked"
    assert safe[0]["retryable"] is True
    assert safe[0]["requestKind"] == "reactivation"


def test_requested_reactivation_uses_matching_result_without_synthetic_duplicate():
    results = [
        {
            "machineId": "5000393",
            "status": "updated",
            "requestKind": "reactivation",
            "configVerified": True,
        }
    ]

    singapore_runner._ensure_requested_reactivation_outcome(results, "5000393")

    assert len(results) == 1
    assert results[0]["status"] == "updated"
    with pytest.raises(ValueError, match="reactivation target is invalid"):
        singapore_runner._validated_reactivation_target("5000393 password=hunter2")


def test_unverified_config_success_claims_are_retryable_blockers_not_chat_success(tmp_path):
    cache = _build_cache(
        root=tmp_path / "repo",
        private_state=tmp_path / "state",
        server_config_path=tmp_path / "state" / "servers.json",
        items=[],
        zoom_result={"status": "not_needed", "sent": False},
        source_message_ids=[],
        marked_read_count=0,
        blockers=[],
        upload_result={
            "status": "complete",
            "uploadedFiles": 0,
            "alreadyPresentFiles": 0,
            "markedReadMessages": 0,
            "failedMessages": 0,
            "unmatchedMessages": 0,
            "authBlockedServers": 0,
            "catalogStatusCounts": {},
            "autoReply": {"matched": 0, "replied": 0, "failed": 0, "markedRead": 0},
        },
        config_change_results=[
            {"status": "updated", "configVerified": False, "requestKind": "existing_config"},
            {"status": "already_current", "configVerified": "true", "requestKind": "existing_config"},
            {"status": "already_active", "requestKind": "reactivation"},
        ],
        non_submission_reviewed=False,
    )

    changes = cache["configChanges"]
    assert cache["status"] == "partial"
    assert changes["status"] == "completed_with_issues"
    assert changes["verifiedCount"] == 0
    assert changes["updatedCount"] == 0
    assert changes["alreadyCurrentCount"] == 0
    assert changes["retryableCount"] == 3
    assert changes["blockedCount"] == 3
    assert [item["status"] for item in changes["results"]] == ["blocked", "blocked", "blocked"]
    assert all(item["configVerified"] is False for item in changes["results"])
    assert all(item["retryable"] is True for item in changes["results"])
    assert "remain retryable" in cache["issues"][0]

    chat_outcome = format_singapore_chat_outcome(cache)
    assert "SINGAPORE | PARTIAL" in chat_outcome
    assert "SUCCESS" not in chat_outcome
    assert "config_updated" not in chat_outcome
    assert "config_verified" not in chat_outcome


def test_unverified_new_interface_and_retired_results_keep_their_policy_semantics(tmp_path):
    cache = _build_cache(
        root=tmp_path / "repo",
        private_state=tmp_path / "state",
        server_config_path=tmp_path / "state" / "servers.json",
        items=[],
        zoom_result={"status": "not_needed", "sent": False},
        source_message_ids=[],
        marked_read_count=0,
        blockers=[],
        upload_result={
            "status": "complete",
            "uploadedFiles": 0,
            "alreadyPresentFiles": 0,
            "markedReadMessages": 0,
            "failedMessages": 0,
            "unmatchedMessages": 0,
            "authBlockedServers": 0,
            "catalogStatusCounts": {},
            "autoReply": {"matched": 0, "replied": 0, "failed": 0, "markedRead": 0},
        },
        config_change_results=[
            {
                "status": "new_interface_request",
                "requestKind": "new_interface",
                "configVerified": False,
            },
            {
                "status": "retired_interface_ignored",
                "requestKind": "existing_config",
                "configVerified": False,
            },
        ],
        non_submission_reviewed=False,
    )

    changes = cache["configChanges"]
    assert cache["status"] == "ok"
    assert changes["newInterfaceRequestCount"] == 1
    assert changes["retiredIgnoredCount"] == 1
    assert changes["blockedCount"] == 0
    assert changes["retryableCount"] == 0
    assert [item["status"] for item in changes["results"]] == [
        "new_interface_request",
        "retired_interface_ignored",
    ]


def test_cache_catalogs_incomplete_upload_without_ticket_or_review_handoff(tmp_path):
    cache = _build_cache(
        root=tmp_path / "repo",
        private_state=tmp_path / "state",
        server_config_path=tmp_path / "state" / "servers.json",
        items=[],
        zoom_result={"status": "not_needed", "sent": False},
        source_message_ids=[],
        marked_read_count=0,
        blockers=[],
        upload_result={
            "status": "complete_with_issues",
            "uploadedFiles": 0,
            "alreadyPresentFiles": 0,
            "markedReadMessages": 0,
            "gmailReadbackFailedMessages": 0,
            "failedMessages": 1,
            "unmatchedMessages": 1,
            "authBlockedServers": 1,
            "catalogStatusCounts": {"authorization_failed": 1, "unresolved": 1},
            "autoReply": {"matched": 0, "replied": 0, "failed": 0, "markedRead": 0},
            "messageResults": [],
        },
        config_change_results=[],
        non_submission_reviewed=False,
    )

    assert cache["status"] == "partial"
    assert cache["upload"]["status"] == "completed_with_issues"
    assert cache["mailbox"]["status"] == "completed"
    assert cache["mailbox"]["markedReadCount"] == 0
    assert "upload source message(s) remain incomplete" in cache["issues"][0]
    assert "Catalogued 2 incomplete background-service outcome(s)" in cache["summary"]
    assert "no Salesforce ticket or Needs Review packet was created" in cache["summary"]


def test_cache_counts_persisted_auth_backoff_as_active_auth_circuit(tmp_path):
    cache = _build_cache(
        root=tmp_path / "repo",
        private_state=tmp_path / "state",
        server_config_path=tmp_path / "state" / "servers.json",
        items=[],
        zoom_result={"status": "not_needed", "sent": False},
        source_message_ids=[],
        marked_read_count=0,
        blockers=[],
        upload_result={
            "status": "complete_with_issues",
            "uploadedFiles": 0,
            "alreadyPresentFiles": 0,
            "markedReadMessages": 0,
            "gmailReadbackFailedMessages": 0,
            "failedMessages": 2,
            "unmatchedMessages": 0,
            "authBlockedServers": 0,
            "authBackoffServers": 2,
            "catalogStatusCounts": {"authorization_failed": 2},
            "autoReply": {"matched": 0, "replied": 0, "failed": 0, "markedRead": 0},
            "messageResults": [],
        },
        config_change_results=[],
        non_submission_reviewed=False,
    )

    assert cache["upload"]["authBlockedServerCount"] == 2
    assert "2 server authentication circuit(s) are active" in cache["issues"][0]
    assert "Authentication-failure sources are marked read" in cache["summary"]
    assert "Outbound failure notifications are suppressed" in cache["summary"]
    assert cache["approvedActions"]["gmailMarkReadAutomatedFailures"] is True
    assert cache["approvedActions"]["queueTicketAndAlexForIncompleteSources"] is False
    assert cache["approvedActions"]["catalogIncompleteSourcesForTaylorStatus"] is True
    assert cache["approvedActions"]["queueSalesforceTicketsForOperationalOutcomes"] is False
    assert cache["approvedActions"]["queueNeedsReviewForOperationalOutcomes"] is False
    assert cache["approvedActions"]["queueTicketOnlyForExplicitNewInterfaceRequest"] is True
    assert cache["approvedActions"]["directChatSanitizedOutcomes"] is True
    assert cache["approvedActions"]["ignoreVerifiedRetiredInterfaces"] is True
    assert "notifications" not in cache


def test_non_submission_sources_are_marked_and_read_back_individually():
    messages = {
        "m1": {"labelIds": ["INBOX", "UNREAD"]},
        "m2": {"labelIds": ["INBOX", "UNREAD"]},
    }

    def mark_messages_as_read(_service, message_ids):
        if message_ids == ["m1"]:
            messages["m1"]["labelIds"].remove("UNREAD")
        return 1

    gmail = SimpleNamespace(
        get_message=lambda _service, message_id: messages[message_id],
        mark_messages_as_read=mark_messages_as_read,
    )

    result = _mark_gmail_messages_read_verified(object(), ["m1", "m2"], gmail)

    assert result == [
        {"messageId": "m1", "status": "verified_read", "markedRead": True, "readbackVerified": True},
        {"messageId": "m2", "status": "still_unread", "markedRead": False, "readbackVerified": False},
    ]


def test_cache_reports_verified_zero_sales_cleanup_without_julio_message(tmp_path):
    cache = _build_cache(
        root=tmp_path / "repo",
        private_state=tmp_path / "state",
        server_config_path=tmp_path / "state" / "servers.json",
        items=[],
        zoom_result={"status": "not_needed", "sent": False},
        source_message_ids=[],
        marked_read_count=1,
        blockers=[],
        upload_result={
            "status": "complete",
            "uploadedFiles": 0,
            "alreadyPresentFiles": 0,
            "markedReadMessages": 0,
            "failedMessages": 0,
            "unmatchedMessages": 0,
            "authBlockedServers": 0,
            "catalogStatusCounts": {},
            "autoReply": {"matched": 0, "replied": 0, "failed": 0, "markedRead": 0},
        },
        config_change_results=[],
        non_submission_reviewed=True,
        mailbox_details=[
            {
                "messageId": "zero-1",
                "kind": "zero_sales",
                "status": "verified_read",
                "markedRead": True,
                "readbackVerified": True,
            }
        ],
        zero_sales_count=1,
    )

    assert cache["status"] == "ok"
    assert cache["ignored"]["zeroSales"] == 1
    assert cache["mailbox"]["details"][0]["kind"] == "zero_sales"
    assert cache["mailbox"]["markedReadCount"] == 1
    assert "Auto-read 1 pure zero-sale notice" in cache["summary"]
    assert cache["approvedActions"]["gmailMarkReadZeroSalesNotices"] is True


def test_authentication_failures_are_catalogued_then_marked_read_with_readback():
    messages = {"m1": {"labelIds": ["INBOX", "UNREAD"]}}

    def mark_messages_as_read(_service, message_ids):
        messages[message_ids[0]]["labelIds"].remove("UNREAD")
        return 1

    gmail = SimpleNamespace(
        get_message=lambda _service, message_id: messages[message_id],
        mark_messages_as_read=mark_messages_as_read,
    )
    upload = {
        "markedReadMessages": 0,
        "gmailReadbackFailedMessages": 0,
        "messageResults": [
            {
                "sourceMessageId": "m1",
                "result": "server_auth_backoff",
                "failureCategory": "authentication",
                "serverKey": "8000860",
            }
        ],
    }

    readback = _acknowledge_auth_failure_sources(object(), upload, gmail)

    assert readback[0]["readbackVerified"] is True
    assert upload["markedReadMessages"] == 1
    assert upload["gmailReadbackFailedMessages"] == 0
    assert upload["messageResults"][0]["markedRead"] is True


def test_cached_auth_acknowledgement_is_gmail_only_and_persists_readback(tmp_path, monkeypatch):
    root = tmp_path / "uploader"
    state = tmp_path / "state"
    root.mkdir()
    state.mkdir()
    for name in ("servers.json", "credentials.json", "token.json"):
        (state / name).write_text("{}", encoding="utf-8")
    journal_path = state / "headless-upload-journal.json"
    journal_path.write_text(
        json.dumps(
            {
                "markedReadMessages": 0,
                "gmailReadbackFailedMessages": 0,
                "messageResults": [
                    {
                        "sourceMessageId": "m1",
                        "serverKey": "8000860",
                        "result": "server_auth_blocked",
                        "failureCategory": "authentication",
                    },
                    {
                        "sourceMessageId": "m2",
                        "serverKey": "8000861",
                        "result": "upload_or_verification_failed",
                        "failureCategory": "transfer_or_verification",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    messages = {"m1": {"labelIds": ["UNREAD"]}, "m2": {"labelIds": ["UNREAD"]}}

    def mark(_service, message_ids):
        messages[message_ids[0]]["labelIds"].remove("UNREAD")

    gmail = SimpleNamespace(
        get_app_dir=lambda: "",
        get_message=lambda _service, message_id: messages[message_id],
        mark_messages_as_read=mark,
    )
    server_utils = SimpleNamespace(get_app_dir=lambda: "")
    monkeypatch.setattr(singapore_runner, "_load_parser_modules", lambda _root: {"gmail_client": gmail, "server_utils": server_utils})
    monkeypatch.setattr(singapore_runner, "_authenticate_gmail_noninteractive", lambda *_args: object())

    result = acknowledge_cached_auth_failures(uploader_root=root, state_dir=state)

    assert result["verifiedReadCount"] == 1
    assert "UNREAD" not in messages["m1"]["labelIds"]
    assert "UNREAD" in messages["m2"]["labelIds"]
    persisted = json.loads(journal_path.read_text(encoding="utf-8"))
    assert persisted["messageResults"][0]["gmailReadbackVerified"] is True


def test_retirement_requires_90_days_without_success_or_customer_contact(tmp_path):
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    servers_path = state_dir / "servers.json"
    servers_path.write_text(
        json.dumps({"8000860": {"type": "sftp", "host": "private", "password": "secret"}}),
        encoding="utf-8",
    )
    now = datetime(2026, 7, 16, 15, tzinfo=timezone.utc)
    old = (now - timedelta(days=91)).isoformat().replace("+00:00", "Z")
    (state_dir / "singapore-retirement-evidence.json").write_text(
        json.dumps(
            {
                "entries": {
                    "8000860": {
                        "observationStartedAtUtc": old,
                        "lastVerifiedSuccessAtUtc": old,
                        "lastCustomerContactAtUtc": old,
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    upload = {
        "messageResults": [
            {
                "sourceMessageId": "m1",
                "serverKey": "8000860",
                "result": "server_auth_backoff",
                "failureCategory": "authentication",
            }
        ]
    }

    result = _update_retirement_evidence_and_apply(
        private_state=state_dir,
        server_config_path=servers_path,
        upload_result=upload,
        config_change_results=[],
        now=now,
    )

    assert result["eligibleCount"] == 1
    assert result["retiredCount"] == 1
    retired = json.loads(servers_path.read_text(encoding="utf-8"))["8000860"]
    assert retired["retired"] is True
    assert retired["status"] == "retired"
    assert "host" not in retired and "password" not in retired


def test_recent_customer_contact_resets_retirement_clock(tmp_path):
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    servers_path = state_dir / "servers.json"
    servers_path.write_text(json.dumps({"8000860": {"type": "sftp"}}), encoding="utf-8")
    now = datetime(2026, 7, 16, 15, tzinfo=timezone.utc)
    old = (now - timedelta(days=91)).isoformat().replace("+00:00", "Z")
    (state_dir / "singapore-retirement-evidence.json").write_text(
        json.dumps({"entries": {"8000860": {"observationStartedAtUtc": old}}}),
        encoding="utf-8",
    )
    upload = {
        "messageResults": [
            {"serverKey": "8000860", "failureCategory": "authentication", "result": "server_auth_backoff"}
        ]
    }
    contact = [{"machineId": "8000860", "requestKind": "reactivation", "status": "blocked"}]

    result = _update_retirement_evidence_and_apply(
        private_state=state_dir,
        server_config_path=servers_path,
        upload_result=upload,
        config_change_results=contact,
        now=now,
    )

    assert result["eligibleCount"] == 0
    assert json.loads(servers_path.read_text(encoding="utf-8"))["8000860"].get("retired") is not True


def test_verified_zoom_delivery_is_reused_for_gmail_retry_without_resend(tmp_path):
    output = tmp_path / "cache.json"
    output.write_text(
        json.dumps(
            {
                "zoomMessage": {
                    "status": "sent",
                    "sent": True,
                    "messageId": "zoom-1",
                    "messageBody": "exact body",
                }
            }
        ),
        encoding="utf-8",
    )

    assert _prior_zoom_delivery(output, "exact body")["messageId"] == "zoom-1"
    assert _prior_zoom_delivery(output, "different body") is None


def test_missing_or_invalid_prior_cache_has_no_legacy_zoom_delivery(tmp_path):
    output = tmp_path / "cache.json"

    assert _prior_zoom_delivery(output, "exact body") is None

    output.write_text("{not-json", encoding="utf-8")
    assert _prior_zoom_delivery(output, "exact body") is None


def test_short_dates_collapse_contiguous_same_month_ranges():
    assert _format_short_dates(
        [date(2026, 5, 10), date(2026, 5, 11), date(2026, 5, 12), date(2026, 5, 15), date(2026, 7, 4)]
    ) == "5/10-12, 5/15, 7/4"


def test_zoom_message_contains_only_machine_ids_and_dates():
    message = _build_zoom_message(
        [{"machineId": "8000640", "dates": ["2026-05-10", "2026-05-11", "2026-07-04"], "subject": "ignored"}]
    )
    assert message.startswith("Hey Julio, can you please resubmit these Singapore integrations")
    assert "8000640: 5/10-11, 7/4" in message
    assert "subject" not in message
    assert message.count("\n") <= 1
    assert len(message) <= 600


def test_current_non_submission_backlog_fits_typed_zoom_message_contract():
    message = _build_zoom_message(
        [
            {"machineId": "6000433", "dates": ["2026-07-22", "2026-07-26"]},
            {"machineId": "41000046", "dates": ["2026-07-26"]},
            {"machineId": "6000999", "dates": ["2026-07-20", "2026-07-26"]},
            {"machineId": "17000037", "dates": ["2026-07-26"]},
            {"machineId": "8000816", "dates": ["2026-07-16", "2026-07-26"]},
            {"machineId": "8000627", "dates": ["2026-07-26"]},
            {"machineId": "5000640", "dates": ["2026-07-26"]},
            {"machineId": "8000755", "dates": ["2026-07-26"]},
        ]
    )

    assert message.count("\n") <= 1
    assert len(message) <= 600


def test_large_backlog_is_split_into_one_source_safe_bounded_cycle():
    items = [
        {
            "machineId": f"8000{index:04d}",
            "dates": ["2026-07-26"],
            "sourceEmailId": f"message-{index}",
            "sourceEmailIds": [f"message-{index}"],
        }
        for index in range(50)
    ]

    selected, deferred, unresolved = _select_zoom_delivery_batch(items)

    assert selected
    assert deferred
    assert unresolved == []
    assert len(_build_zoom_message(selected)) <= 600
    selected_sources = {
        value for item in selected for value in item["sourceEmailIds"]
    }
    deferred_sources = {
        value for item in deferred for value in item["sourceEmailIds"]
    }
    assert selected_sources.isdisjoint(deferred_sources)
    assert len(selected) + len(deferred) == len(items)


def test_source_linked_rows_are_never_split_across_zoom_cycles():
    linked = [
        {
            "machineId": "8000640",
            "dates": ["2026-07-25"],
            "sourceEmailIds": ["shared-message"],
        },
        {
            "machineId": "8000641",
            "dates": ["2026-07-26"],
            "sourceEmailIds": ["shared-message"],
        },
    ]
    extras = [
        {
            "machineId": f"9000{index:04d}",
            "dates": ["2026-07-26"],
            "sourceEmailIds": [f"extra-{index}"],
        }
        for index in range(50)
    ]

    selected, deferred, unresolved = _select_zoom_delivery_batch(linked + extras)

    assert unresolved == []
    selected_ids = {item["machineId"] for item in selected}
    deferred_ids = {item["machineId"] for item in deferred}
    assert {"8000640", "8000641"} <= selected_ids or {
        "8000640",
        "8000641",
    } <= deferred_ids


def test_mixed_configured_and_unconfigured_source_is_withheld_as_one_unit():
    configured = [
        {
            "machineId": "8000640",
            "dates": ["2026-07-26"],
            "sourceEmailIds": ["mixed-message"],
        },
        {
            "machineId": "8000755",
            "dates": ["2026-07-26"],
            "sourceEmailIds": ["safe-message"],
        },
    ]
    unconfigured = [
        {
            "machineId": "9999999",
            "dates": ["2026-07-26"],
            "sourceEmailIds": ["mixed-message"],
        }
    ]

    eligible, unresolved = _partition_mixed_source_items(
        configured,
        unconfigured,
    )

    assert [item["machineId"] for item in eligible] == ["8000755"]
    assert [item["machineId"] for item in unresolved] == ["8000640"]
    assert unresolved[0]["status"] == "mixed_configured_unconfigured_source"


def test_oversized_or_missing_source_does_not_starve_unrelated_valid_rows():
    oversized = [
        {
            "machineId": f"7000{index:04d}",
            "dates": ["2026-07-26"],
            "sourceEmailIds": ["one-large-message"],
        }
        for index in range(50)
    ]
    valid = {
        "machineId": "8000640",
        "dates": ["2026-07-26"],
        "sourceEmailIds": ["safe-message"],
    }
    missing_source = {
        "machineId": "8000755",
        "dates": ["2026-07-26"],
        "sourceEmailIds": [],
    }

    selected, deferred, unresolved = _select_zoom_delivery_batch(
        [*oversized, valid, missing_source]
    )

    assert [item["machineId"] for item in selected] == ["8000640"]
    assert deferred == []
    assert {item["status"] for item in unresolved} == {
        "missing_source_message_id",
        "oversized_source_group",
    }
    assert len(unresolved) == 51


def test_zoom_outbox_binds_exact_sources_body_and_verified_delivery(tmp_path):
    path = tmp_path / "non-submission-outbox.json"
    items = [
        {
            "machineId": "8000640",
            "dates": ["2026-07-26"],
            "sourceEmailId": "message-1",
            "sourceEmailIds": ["message-1"],
        }
    ]
    message = _build_zoom_message(items)

    pending = _write_non_submission_outbox(
        path,
        items=items,
        message=message,
        status="pending",
    )
    verified = _write_non_submission_outbox(
        path,
        items=items,
        message=message,
        status="verified",
        delivery={
            "ok": True,
            "sent": True,
            "status": "sent",
            "messageId": "zoom-message-1",
            "messageBody": message,
            "readbackVerified": True,
            "senderReadbackVerified": True,
            "recipientReadbackVerified": True,
        },
    )

    assert pending["sourceMessageIds"] == ["message-1"]
    assert pending["renderYear"] == datetime.now().year
    assert verified["createdAtUtc"] == pending["createdAtUtc"]
    assert verified["delivery"]["messageId"] == "zoom-message-1"
    assert _read_non_submission_outbox(path)["message"] == message


def test_pending_outbox_preserves_legacy_receipt_for_restart_reconciliation(
    tmp_path,
):
    path = tmp_path / "non-submission-outbox.json"
    output = tmp_path / "ops_singapore_ftp.json"
    items = [
        {
            "machineId": "8000640",
            "dates": ["2026-07-26"],
            "sourceEmailIds": ["message-1"],
        }
    ]
    message = _build_zoom_message(items, render_year=2026)
    legacy = {
        "ok": True,
        "sent": True,
        "status": "sent",
        "channel": "zoom",
        "messageId": "zoom-message-1",
        "messageBody": message,
    }
    _write_non_submission_outbox(
        path,
        items=items,
        message=message,
        status="pending",
        delivery=legacy,
        render_year=2026,
    )

    receipt = _prior_delivery_for_batch(
        active_outbox=_read_non_submission_outbox(path),
        output_path=output,
        message=message,
    )

    assert receipt["messageId"] == "zoom-message-1"
    assert receipt["status"] == "sent"


def test_zoom_outbox_validation_uses_persisted_render_year(tmp_path):
    path = tmp_path / "non-submission-outbox.json"
    items = [
        {
            "machineId": "8000640",
            "dates": ["2026-12-31"],
            "sourceEmailIds": ["message-1"],
        }
    ]
    message = _build_zoom_message(items, render_year=2026)
    assert message != _build_zoom_message(items, render_year=2027)

    _write_non_submission_outbox(
        path,
        items=items,
        message=message,
        status="pending",
        render_year=2026,
    )

    assert _read_non_submission_outbox(path)["message"] == message


def test_corrupt_zoom_outbox_blocks_new_delivery(tmp_path):
    path = tmp_path / "non-submission-outbox.json"
    path.write_text("{not-json", encoding="utf-8")

    with pytest.raises(RuntimeError, match="refusing to create a second"):
        _read_non_submission_outbox(path)


def test_zoom_typed_sender_uses_private_journals_julio_and_stable_idempotency(tmp_path, monkeypatch):
    private_state = tmp_path / "private"
    private_state.mkdir()
    ops_env = private_state / "ops.env"
    ops_env.write_text("", encoding="utf-8")
    team_chat_journal = private_state / "zoom-team-chat-messages.jsonl"
    communication_journal = private_state / "internal-communications.jsonl"
    factory_calls = []
    send_calls = []

    class FakeClient:
        def team_chat_send(self, **kwargs):
            send_calls.append(kwargs)
            return {
                "ok": True,
                "sent": True,
                "status": "sent",
                "messageId": "zoom-message-1",
                "messageBody": kwargs["message"],
                "readbackVerified": True,
                "senderReadbackVerified": True,
                "recipientReadbackVerified": True,
            }

    def fake_factory(*, team_chat_journal_path, internal_communication_journal_path):
        factory_calls.append((team_chat_journal_path, internal_communication_journal_path))
        return FakeClient()

    monkeypatch.setattr(singapore_runner, "_build_singapore_zoom_client", fake_factory)

    # A fixed Monday 11:00 UTC so the weekend gate never interferes with the
    # send/idempotency behavior under test.
    monday_11am = datetime(2026, 10, 12, 11, 0, tzinfo=timezone.utc)
    first = _send_zoom_message(
        message="resubmit tenants",
        recipient_hint="Julio",
        ops_env_path=ops_env,
        team_chat_journal_path=team_chat_journal,
        internal_communication_journal_path=communication_journal,
        now=monday_11am,
    )
    second = _send_zoom_message(
        message="resubmit tenants",
        recipient_hint="Julio",
        ops_env_path=ops_env,
        team_chat_journal_path=team_chat_journal,
        internal_communication_journal_path=communication_journal,
        now=monday_11am,
    )

    assert first["sent"] is True
    assert second["sent"] is True
    assert factory_calls == [
        (team_chat_journal.resolve(), communication_journal.resolve()),
        (team_chat_journal.resolve(), communication_journal.resolve()),
    ]
    assert [call["exact_recipient"] for call in send_calls] == [
        "configured:julio",
        "configured:julio",
    ]
    assert send_calls[0]["idempotency_key"] == send_calls[1]["idempotency_key"]
    assert send_calls[0]["idempotency_key"].startswith("singapore-nonsubmission:")
    assert send_calls[0]["sender_lane"] == "coding_agent"
    assert "Singapore non-submission batch" in send_calls[0]["authorization_context"]


def test_zoom_reminder_replies_to_prior_message_with_source_stable_idempotency(
    tmp_path,
    monkeypatch,
):
    calls = []

    class FakeClient:
        def team_chat_send(self, **kwargs):
            calls.append(kwargs)
            return {
                "ok": True,
                "sent": True,
                "status": "sent",
                "messageId": "zoom-reminder",
                "messageBody": kwargs["message"],
                "replyMainMessageId": kwargs["reply_main_message_id"],
                "readbackVerified": True,
                "senderReadbackVerified": True,
                "recipientReadbackVerified": True,
            }

    monkeypatch.setattr(
        singapore_runner,
        "_build_singapore_zoom_client",
        lambda **_kwargs: FakeClient(),
    )

    result = _send_zoom_message(
        message=singapore_runner.SINGAPORE_REMINDER_MESSAGE,
        recipient_hint="Julio",
        ops_env_path=tmp_path / "ops.env",
        reply_to_message_id="zoom-prior",
        idempotency_context="gmail-new|8000640|2026-07-26",
        now=datetime(2026, 10, 12, 11, 0, tzinfo=timezone.utc),
    )

    assert result["sent"] is True
    assert calls[0]["reply_main_message_id"] == "zoom-prior"
    assert calls[0]["idempotency_key"].startswith(
        "singapore-nonsubmission-reminder:"
    )
    assert "reminder reply" in calls[0]["authorization_context"]


def test_zoom_verified_legacy_receipt_is_reused_without_resend(tmp_path, monkeypatch):
    factory_calls = []

    class FakeClient:
        @staticmethod
        def team_chat_verify_existing(**kwargs):
            return {
                "ok": True,
                "sent": True,
                "status": "sent",
                "messageId": kwargs["message_id"],
                "messageBody": kwargs["message"],
                "readbackVerified": True,
                "senderReadbackVerified": True,
                "recipientReadbackVerified": True,
            }

    monkeypatch.setattr(
        singapore_runner,
        "_build_singapore_zoom_client",
        lambda **kwargs: (factory_calls.append(kwargs), FakeClient())[1],
    )

    result = _send_zoom_message(
        message="resubmit tenants",
        recipient_hint="Julio",
        ops_env_path=tmp_path / "ops.env",
        prior_delivery={
            "channel": "zoom",
            "status": "sent",
            "sent": True,
            "messageId": "legacy-verified-message",
            "messageBody": "resubmit tenants",
        },
        now=datetime(2026, 10, 12, 11, 0, tzinfo=timezone.utc),
    )

    assert result["ok"] is True
    assert result["sent"] is True
    assert result["readbackVerified"] is True
    assert result["senderReadbackVerified"] is True
    assert result["recipientReadbackVerified"] is True
    assert result["duplicatePrevented"] is True
    assert result["legacyReceiptReused"] is True
    assert len(factory_calls) == 1


def test_zoom_unverified_legacy_receipt_is_not_resent(tmp_path, monkeypatch):
    factory_calls = []

    class FakeClient:
        @staticmethod
        def team_chat_verify_existing(**kwargs):
            return {
                "ok": False,
                "sent": False,
                "status": "sent_unverified",
                "messageId": kwargs["message_id"],
                "messageBody": kwargs["message"],
                "readbackVerified": False,
                "senderReadbackVerified": False,
                "recipientReadbackVerified": False,
                "retryAllowed": False,
            }

    monkeypatch.setattr(
        singapore_runner,
        "_build_singapore_zoom_client",
        lambda **kwargs: (factory_calls.append(kwargs), FakeClient())[1],
    )

    result = _send_zoom_message(
        message="resubmit tenants",
        recipient_hint="Julio",
        ops_env_path=tmp_path / "ops.env",
        prior_delivery={
            "channel": "zoom",
            "status": "sent_unverified",
            "sent": False,
            "messageId": "legacy-unverified-message",
            "messageBody": "resubmit tenants",
        },
        now=datetime(2026, 10, 12, 11, 0, tzinfo=timezone.utc),
    )

    assert result["ok"] is False
    assert result["sent"] is False
    assert result["status"] == "sent_unverified"
    assert result["retryAllowed"] is False
    assert "will not be sent again" in result["notes"]
    assert len(factory_calls) == 1


@pytest.mark.parametrize(
    "typed_result",
    [
        {
            "ok": True,
            "sent": True,
            "status": "sent",
            "messageId": "zoom-message-1",
            "readbackVerified": False,
            "senderReadbackVerified": True,
            "recipientReadbackVerified": True,
        },
        {
            "ok": True,
            "sent": True,
            "status": "sent",
            "messageId": "zoom-message-1",
            "readbackVerified": True,
            "senderReadbackVerified": True,
            "recipientReadbackVerified": False,
        },
        {
            "ok": True,
            "sent": True,
            "status": "sent",
            "messageId": "zoom-message-1",
            "readbackVerified": True,
            "senderReadbackVerified": False,
            "recipientReadbackVerified": True,
        },
    ],
    ids=[
        "message-readback-missing",
        "recipient-readback-missing",
        "sender-readback-missing",
    ],
)
def test_zoom_typed_sender_requires_message_sender_and_recipient_readback(
    tmp_path,
    monkeypatch,
    typed_result,
):
    class FakeClient:
        def team_chat_send(self, **_kwargs):
            return dict(typed_result)

    monkeypatch.setattr(
        singapore_runner,
        "_build_singapore_zoom_client",
        lambda **_kwargs: FakeClient(),
    )

    result = _send_zoom_message(
        message="resubmit tenants",
        recipient_hint="Julio",
        ops_env_path=tmp_path / "ops.env",
        now=datetime(2026, 10, 12, 11, 0, tzinfo=timezone.utc),
    )

    assert result["sent"] is False
    assert "typed message, sender, and recipient readback" in result["notes"]


def test_zoom_typed_sender_rejects_non_julio_before_client_creation(tmp_path, monkeypatch):
    factory_calls = []
    monkeypatch.setattr(
        singapore_runner,
        "_build_singapore_zoom_client",
        lambda **kwargs: factory_calls.append(kwargs),
    )

    result = _send_zoom_message(
        message="resubmit tenants",
        recipient_hint="Taylor",
        ops_env_path=tmp_path / "ops.env",
    )

    assert result["status"] == "blocked"
    assert result["sent"] is False
    assert "configured:julio" in result["notes"]
    assert factory_calls == []


def test_julio_delivery_policy_is_zoom_only():
    assert singapore_runner.APPROVED_ACTIONS["sendZoomMessageToVerifiedJulio"] is True
    assert singapore_runner.APPROVED_ACTIONS["sendGmailFallbackToVerifiedJulio"] is False
    assert not hasattr(singapore_runner, "_send_julio_gmail_fallback")


def test_zoom_weekend_gate_blocks_weekend_and_allows_weekday(tmp_path, monkeypatch):
    send_calls = []

    class FakeClient:
        def team_chat_send(self, **kwargs):
            send_calls.append(kwargs)
            return {
                "ok": True,
                "sent": True,
                "status": "sent",
                "messageId": "zoom-message-1",
                "messageBody": kwargs["message"],
                "readbackVerified": True,
                "senderReadbackVerified": True,
                "recipientReadbackVerified": True,
            }

    monkeypatch.setattr(
        singapore_runner, "_build_singapore_zoom_client", lambda **_kwargs: FakeClient()
    )
    # The nightly run fires at 23:00 ET. On a Sunday that is already the
    # following weekday in UTC (Mon 03:00 UTC), so the gate must judge the
    # New York date, not the UTC one.
    sunday_night = datetime(2026, 10, 12, 3, 0, tzinfo=timezone.utc)  # = Sun 23:00 EDT
    sunday = _send_zoom_message(
        message="resubmit tenants",
        recipient_hint="Julio",
        ops_env_path=tmp_path / "ops.env",
        now=sunday_night,
    )
    assert sunday["status"] == "blocked"
    assert sunday["sent"] is False
    assert "weekend" in sunday["notes"]

    saturday = _send_zoom_message(
        message="resubmit tenants",
        recipient_hint="Julio",
        ops_env_path=tmp_path / "ops.env",
        now=datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc),
    )
    assert saturday["status"] == "blocked"
    assert saturday["sent"] is False

    monday = _send_zoom_message(
        message="resubmit tenants",
        recipient_hint="Julio",
        ops_env_path=tmp_path / "ops.env",
        now=datetime(2026, 10, 12, 11, 0, tzinfo=timezone.utc),
    )
    assert monday["sent"] is True
    assert len(send_calls) == 1
    assert send_calls[0]["exact_recipient"] == "configured:julio"


def test_server_patch_updates_only_target_entry_and_creates_backup(tmp_path):
    state = tmp_path / "private"
    state.mkdir()
    (state / "servers.json").write_text(
        json.dumps({"8000640": {"type": "sftp", "host": "old"}, "9000001": {"type": "ftp", "host": "keep"}}),
        encoding="utf-8",
    )
    patch = state / "verified-patch.json"
    patch.write_text(
        json.dumps({"action": "upsert", "key": "8000640", "server": {"host": "new", "port": 2222}}),
        encoding="utf-8",
    )

    result = apply_server_patch(state_dir=state, patch_path=patch)
    servers = json.loads((state / "servers.json").read_text(encoding="utf-8"))

    assert result == {"ok": True, "status": "updated", "key": "8000640", "changedFields": ["host", "port"]}
    assert servers["8000640"] == {"type": "sftp", "host": "new", "port": 2222}
    assert servers["9000001"] == {"type": "ftp", "host": "keep"}
    assert len(list((state / "backups").glob("servers-*.json"))) == 1


def test_headless_gmail_auth_never_starts_interactive_flow(tmp_path):
    (tmp_path / "token.json").write_text("{}", encoding="utf-8")
    credentials = SimpleNamespace(valid=False, expired=False, refresh_token=None)
    credential_factory = SimpleNamespace(from_authorized_user_file=lambda *_args: credentials)
    gmail_module = SimpleNamespace(
        Credentials=credential_factory,
        SCOPES=["gmail.modify"],
        Request=lambda: object(),
        build=lambda *_args, **_kwargs: pytest.fail("build must not run"),
    )

    with pytest.raises(RuntimeError, match="interactive reauthentication"):
        _authenticate_gmail_noninteractive(tmp_path, gmail_module)
