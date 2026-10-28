# AgentChat/direct_codex 2026-07-14T00:00:00-04:00: verify incremental inbox routing, state fencing, and SSE security.
# AgentChat/coding_agent 2026-07-14T19:30:00-04:00: verify invoice acknowledgement routing and guarded dispatch.
from __future__ import annotations

import urllib.error
import urllib.request
import sqlite3
import time
from http.server import ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from types import SimpleNamespace

import pytest

from codex_slack_bridge import command_center_server
from codex_slack_bridge.command_center_server import CommandCenterRuntime, make_handler
from codex_slack_bridge.inbox_ledger import InboxLedger, RouteDecision, classify_inbox_message


def _message(
    message_id: str = "message-1",
    *,
    thread_id: str = "thread-1",
    sender: str = "Customer <customer@example.com>",
    subject: str = "Need help with Nova",
    snippet: str = "Please help with this issue.",
    labels: list[str] | None = None,
    to: str = "",
) -> dict:
    return {
        "id": message_id,
        "threadId": thread_id,
        "historyId": "101",
        "internalDate": "1784000000000",
        "labelIds": labels if labels is not None else ["INBOX", "UNREAD"],
        "from": sender,
        "to": to,
        "subject": subject,
        "snippet": snippet,
    }


@pytest.mark.parametrize(
    ("message", "classification", "route"),
    [
        (
            _message(sender="integration@novapointofsale.com", subject="Singapore FTP upload failed"),
            "singapore_operation",
            "singapore_runner",
        ),
        (
            _message(sender="integration@novapointofsale.com", subject="Please create a new Singapore interface"),
            "singapore_new_interface_request",
            "taylor_support_intake",
        ),
        (
            _message(sender="integration@novapointofsale.com", subject="Singapore interface retired"),
            "singapore_retired",
            "complete",
        ),
        (
            _message(subject="RE: Suntec shops | Sales submission issue", snippet="Please review the tenant table."),
            "singapore_operation",
            "singapore_runner",
        ),
        (
            _message(subject="Suntec | Shop | 8000760 | $0 Zero Sales Submission"),
            "singapore_zero_sales_notice",
            "gmail_cleanup_mark_read",
        ),
        (
            _message(sender="notify@salesforce.com", subject="Salesforce notification for ticket 347000"),
            "salesforce_notification",
            "gmail_cleanup_mark_read",
        ),
        (
            _message(sender="Customer <customer@example.com>", subject="Re: Your NovaPOS invoice is ready"),
            "invoice_reply_acknowledgement",
            "taylor_support_intake",
        ),
        (
            _message(
                to="Nova Billing <billing@novapointofsale.com>",
                subject="Account closure",
                snippet="Please stop billing for this specific location.",
            ),
            "billing_closure_confirmation",
            "jamie_billing_closure_intake",
        ),
    ],
)
def test_deterministic_classifier_routes_known_mail(message, classification, route):
    decision = classify_inbox_message(message)

    assert decision.classification == classification
    assert decision.route == route
    assert decision.deterministic is True


def test_classifier_requires_trusted_sender_for_nmi():
    untrusted = classify_inbox_message(
        _message(sender="stranger@example.com", subject="NMI API Key setup"),
        trusted_nmi_senders={"trusted@example.com"},
    )
    trusted = classify_inbox_message(
        _message(sender="Trusted <trusted@example.com>", subject="NMI API Key setup"),
        trusted_nmi_senders={"trusted@example.com"},
    )

    assert untrusted.route == "taylor_support_intake"
    assert trusted.route == "propelr_nmi_runner"


def test_invoice_acknowledgement_excludes_automated_senders():
    decision = classify_inbox_message(
        _message(sender="No Reply <no-reply@example.com>", subject="Re: Your NovaPOS invoice is ready")
    )

    assert decision.classification == "support_or_customer_mail"
    assert decision.route == "taylor_support_intake"


def test_billing_closure_classifier_requires_billing_recipient_and_closure_context():
    ordinary_support = classify_inbox_message(
        _message(
            to="support@novapointofsale.com",
            subject="Please close this account",
            snippet="The following location has shut down.",
        )
    )
    billing_question = classify_inbox_message(
        _message(
            to="billing@novapointofsale.com",
            subject="Account billing question",
            snippet="Please explain this invoice.",
        )
    )

    assert ordinary_support.route == "taylor_support_intake"
    assert billing_question.route == "taylor_support_intake"


def test_only_explicitly_allowlisted_commercial_sender_is_archived():
    message = _message(sender="Offers <offers@vendor.example>", subject="Weekly offers")

    uncertain = classify_inbox_message(message)
    allowlisted = classify_inbox_message(message, known_junk_senders={"offers@vendor.example"})

    assert uncertain.route == "taylor_support_intake"
    assert allowlisted.route == "gmail_cleanup_archive"


def test_replaying_same_message_is_idempotent_and_state_is_durable(tmp_path):
    ledger = InboxLedger(tmp_path / "inbox.sqlite3")
    message = _message()

    assert ledger.upsert_detected(message, history_id="101") is True
    ledger.classify(
        message["id"],
        RouteDecision("support_or_customer_mail", "taylor_support_intake", "Needs judgment.", False, True),
    )
    ledger.mark_assigned(
        [message["id"]],
        agent="coding_agent",
        job_id="job-1",
        action_key="action-1",
    )
    assert ledger.upsert_detected(message, history_id="102") is False

    reopened = InboxLedger(tmp_path / "inbox.sqlite3")
    item = reopened.item(message["id"])
    events = reopened.events_after(0)

    assert item["state"] == "action_pending"
    assert item["assignedJobId"] == "job-1"
    assert [event["type"] for event in events].count("detected") == 1
    assert [event["toState"] for event in events if event["toState"]] == [
        "detected",
        "classified",
        "assigned",
        "action_pending",
    ]


def test_publication_failure_retry_preserves_message_identity_and_reuses_action_key(tmp_path):
    ledger = InboxLedger(tmp_path / "inbox.sqlite3")
    message = _message()
    decision = RouteDecision(
        "support_or_customer_mail",
        "taylor_support_intake",
        "Needs judgment.",
        False,
        True,
    )
    ledger.upsert_detected(message)
    ledger.classify(message["id"], decision)
    ledger.mark_assigned(
        [message["id"]],
        agent="coding_agent",
        job_id="failed-publication-job",
        action_key="inbox-ledger:support:stable",
    )
    ledger.block(message["id"], "Result publication failed.", retry_after_seconds=60)
    with sqlite3.connect(ledger.path) as connection:
        connection.execute(
            "UPDATE inbox_items SET next_attempt_at_utc='2026-01-01T00:00:00+00:00' WHERE message_id=?",
            (message["id"],),
        )

    retry = ledger.dispatchable()

    assert [item["messageId"] for item in retry] == [message["id"]]
    assert retry[0]["state"] == "classified"
    assert retry[0]["actionKey"] == "inbox-ledger:support:stable"
    ledger.mark_assigned(
        [message["id"]],
        agent="coding_agent",
        job_id="retry-publication-job",
        action_key="inbox-ledger:support:stable",
    )
    assert ledger.upsert_detected(message) is False
    item = ledger.item(message["id"])
    assert item["state"] == "action_pending"
    assert item["assignedJobId"] == "retry-publication-job"
    assert item["actionKey"] == "inbox-ledger:support:stable"
    assert [event["type"] for event in ledger.events_after(0)].count("detected") == 1


def test_live_label_reconciliation_completes_read_pending_mail_without_claiming_our_write(tmp_path):
    ledger = InboxLedger(tmp_path / "inbox.sqlite3")
    message = _message()
    ledger.upsert_detected(message)
    ledger.classify(message["id"], classify_inbox_message(message))
    ledger.mark_assigned(
        [message["id"]],
        agent="coding_agent",
        job_id="old-job",
        action_key="old-action",
    )
    read_message = {**message, "labelIds": ["INBOX"]}

    outcome = ledger.reconcile_pending_message(
        read_message,
        classify_inbox_message(read_message),
        requeue_stale=False,
    )

    item = ledger.item(message["id"])
    assert outcome == "completed_live_readback"
    assert item["state"] == "complete"
    assert item["writeReadbackVerified"] is False
    assert item["actionResult"]["mailboxReadbackVerified"] is True


def test_stale_pending_mail_is_reclassified_from_current_subject_before_retry(tmp_path):
    ledger = InboxLedger(tmp_path / "inbox.sqlite3")
    message = _message(subject="Please review")
    ledger.upsert_detected(message)
    ledger.classify(message["id"], classify_inbox_message(message))
    ledger.mark_assigned(
        [message["id"]],
        agent="coding_agent",
        job_id="terminal-job",
        action_key="old-action",
    )
    current = {**message, "subject": "RE: Three stores | Sales submission issue"}

    outcome = ledger.reconcile_pending_message(
        current,
        classify_inbox_message(current),
        requeue_stale=True,
    )

    item = ledger.item(message["id"])
    assert outcome == "requeued"
    assert item["state"] == "classified"
    assert item["classification"] == "singapore_operation"
    assert item["route"] == "singapore_runner"
    assert item["assignedJobId"] == ""


def test_historical_message_is_excluded_from_live_detection_latency(tmp_path):
    ledger = InboxLedger(tmp_path / "inbox.sqlite3")
    message = {**_message(), "internalDate": "1"}

    ledger.upsert_detected(message, measure_detection_latency=True)

    assert ledger.status()["metrics"]["detectionLatencyP95Ms"] == 0


def test_stale_action_pending_degrades_health(tmp_path):
    ledger = InboxLedger(tmp_path / "inbox.sqlite3")
    message = _message()
    ledger.upsert_detected(message)
    ledger.classify(message["id"], classify_inbox_message(message))
    ledger.mark_assigned(
        [message["id"]],
        agent="coding_agent",
        job_id="missing-job",
        action_key="stale-action",
    )
    with sqlite3.connect(ledger.path) as connection:
        connection.execute(
            "UPDATE inbox_items SET updated_at_utc='2026-01-01T00:00:00+00:00' WHERE message_id=?",
            (message["id"],),
        )

    status = ledger.status()

    assert status["ok"] is False
    assert status["metrics"]["staleActionPendingCount"] == 1
    assert status["metrics"]["oldestActionPendingAgeSeconds"] > 0


def test_ledger_redacts_credential_like_snippets(tmp_path):
    ledger = InboxLedger(tmp_path / "inbox.sqlite3")
    message = _message(snippet="API_KEY=do-not-store-this-value")

    ledger.upsert_detected(message)

    assert "do-not-store-this-value" not in ledger.item(message["id"])["snippet"]


def test_sqlite_busy_timeout_survives_a_short_writer_lock(tmp_path):
    ledger = InboxLedger(tmp_path / "inbox.sqlite3")
    blocker = sqlite3.connect(str(ledger.path), timeout=1)
    blocker.execute("BEGIN IMMEDIATE")
    completed = []

    worker = Thread(target=lambda: (ledger.set_meta("lock-test", "ok"), completed.append(True)))
    worker.start()
    time.sleep(0.1)
    blocker.rollback()
    blocker.close()
    worker.join(timeout=3)

    assert completed == [True]
    assert ledger.get_meta("lock-test") == "ok"


def test_support_result_completes_only_after_verified_mailbox_readback(tmp_path):
    ledger = InboxLedger(tmp_path / "inbox.sqlite3")
    message = _message()
    ledger.upsert_detected(message)
    ledger.classify(
        message["id"],
        RouteDecision("support_or_customer_mail", "taylor_support_intake", "Needs judgment.", False, True),
    )
    ledger.mark_assigned([message["id"]], agent="coding_agent", job_id="job-1", action_key="key")

    ledger.apply_support_result(
        {
            "sourceEmailId": message["id"],
            "classification": "support_request",
            "result": "created",
            "triageDecision": "ticket_needed",
            "ticket": {"number": "347001", "verifiedAtUtc": "2026-07-14T00:00:00Z"},
            "gmail": {"status": "unread", "readbackVerified": False},
        }
    )
    assert ledger.item(message["id"])["state"] == "action_pending"

    ledger.apply_support_result(
        {
            "sourceEmailId": message["id"],
            "classification": "support_request",
            "result": "created",
            "triageDecision": "ticket_needed",
            "ticket": {"number": "347001", "verifiedAtUtc": "2026-07-14T00:00:00Z"},
            "gmail": {"status": "marked_read", "readbackVerified": True},
        }
    )
    completed = ledger.item(message["id"])
    assert completed["state"] == "complete"
    assert completed["writeReadbackVerified"] is True


def test_reply_projection_emits_event_without_waiting_for_next_poll(tmp_path):
    ledger = InboxLedger(tmp_path / "inbox.sqlite3")
    message = _message()
    ledger.upsert_detected(message)
    ledger.classify(
        message["id"],
        RouteDecision("support_or_customer_mail", "taylor_support_intake", "Needs judgment.", False, True),
    )
    ledger.mark_assigned([message["id"]], agent="coding_agent", job_id="job-1", action_key="key")
    sequence = ledger.status()["lastSequence"]

    ledger.apply_support_result(
        {
            "sourceEmailId": message["id"],
            "classification": "non_ticket",
            "result": "skipped",
            "triageDecision": "reply_needed",
            "recommendedAction": "Reply to the customer.",
            "recommendedReplyBody": "Thanks for reaching out. We can help with that.",
            "gmail": {"status": "unread", "readbackVerified": False},
        }
    )

    events = ledger.events_after(sequence)
    projection = ledger.email_watch_projection()
    assert events[0]["type"] == "support_result_projected"
    assert projection["emails"][0]["recommendedReplyBody"].startswith("Thanks for reaching out")


def test_blocked_support_result_with_leave_unread_is_retryable(tmp_path):
    ledger = InboxLedger(tmp_path / "inbox.sqlite3")
    message = _message()
    ledger.upsert_detected(message)
    ledger.classify(
        message["id"],
        RouteDecision("support_or_customer_mail", "taylor_support_intake", "Needs judgment.", False, True),
    )
    ledger.mark_assigned([message["id"]], agent="coding_agent", job_id="job-1", action_key="key")

    ledger.apply_support_result(
        {
            "sourceEmailId": message["id"],
            "classification": "non_ticket",
            "result": "blocked",
            "triageDecision": "leave_unread",
            "gmail": {"status": "unread", "readbackVerified": False},
            "blockers": ["Gmail readback was temporarily unavailable."],
        }
    )

    blocked = ledger.item(message["id"])
    assert blocked["state"] == "blocked"
    assert blocked["attemptCount"] == 1
    assert blocked["nextAttemptAtUtc"]


def _collector_runtime(tmp_path: Path) -> CommandCenterRuntime:
    runtime = object.__new__(CommandCenterRuntime)
    runtime.config = SimpleNamespace(
        defaults={
            "ops_inbox_ledger_enabled": True,
            "ops_inbox_ledger_query": "in:inbox is:unread -in:spam -in:trash",
            "ops_inbox_ledger_max_results": 100,
        }
    )
    runtime.inbox_ledger = InboxLedger(tmp_path / "inbox.sqlite3")
    runtime.gmail_token_path = tmp_path / "token.json"
    runtime.email_send_journal_path = tmp_path / "email_send_journal.json"
    runtime.capability_router = SimpleNamespace(record_success=lambda *_args, **_kwargs: None, record_failure=lambda *_args, **_kwargs: None)
    runtime.submit_support_email_intake_calls = []

    def submit_support_email_intake(**kwargs):
        runtime.submit_support_email_intake_calls.append(kwargs)
        return {"accepted": True, "job_id": "support-job", "duplicate": False}

    runtime.submit_support_email_intake = submit_support_email_intake
    runtime.submit_propelr_nmi_setup = lambda _payload: {"accepted": True, "job_id": "nmi-job"}
    runtime.submit_singapore_ftp_scan = lambda **_kwargs: {"accepted": True, "job_id": "singapore-job"}
    return runtime


def test_invoice_reply_acknowledges_before_normal_support_intake(tmp_path, monkeypatch):
    runtime = _collector_runtime(tmp_path)
    message = _message(subject="Re: Your NovaPOS invoice is ready")
    runtime.inbox_ledger.upsert_detected(message)
    runtime.inbox_ledger.classify(message["id"], classify_inbox_message(message))
    events = []
    captured = {}

    def fake_send(**kwargs):
        events.append("acknowledgement")
        captured.update(kwargs)
        return {"id": "sent-1", "threadId": message["threadId"], "verified": True}

    def fake_submit(**kwargs):
        events.append("support_intake")
        return {"accepted": True, "job_id": "support-job", "duplicate": False}

    monkeypatch.setattr(command_center_server, "_gmail_send_signature_preserving_reply", fake_send)
    runtime.submit_support_email_intake = fake_submit

    assert runtime._dispatch_inbox_ledger_items() == 1
    assert events == ["acknowledgement", "support_intake"]
    assert captured["require_matching_recipient"] is True
    assert captured["reply_all"] is False
    assert captured["body"] == command_center_server.INVOICE_REPLY_ACKNOWLEDGEMENT_BODY
    assert captured["idempotency_key"] == f"inbox-ledger:invoice-ack:{message['id']}"
    assert runtime.inbox_ledger.item(message["id"])["state"] == "action_pending"


def test_incremental_collector_replay_queues_one_model_job(tmp_path, monkeypatch):
    runtime = _collector_runtime(tmp_path)
    message = _message()
    monkeypatch.setattr(command_center_server, "_gmail_access_token", lambda _path: "token")
    monkeypatch.setattr(
        command_center_server,
        "_gmail_api_get_json_with_retry",
        lambda *_args, **_kwargs: {"emailAddress": "owner@example.com", "historyId": "200"},
    )
    monkeypatch.setattr(command_center_server, "_gmail_search_message_ids_paginated", lambda *_args, **_kwargs: [message["id"]])
    monkeypatch.setattr(command_center_server, "_gmail_history_message_ids", lambda *_args, **_kwargs: [message["id"]])
    monkeypatch.setattr(command_center_server, "_gmail_message_metadata", lambda *_args, **_kwargs: dict(message))

    first = runtime.collect_inbox_now()
    second = runtime.collect_inbox_now()

    assert first["modelJobsQueued"] == 1
    assert second["modelJobsQueued"] == 0
    assert len(runtime.submit_support_email_intake_calls) == 1
    assert runtime.inbox_ledger.status()["metrics"]["noopModelRunsAvoided"] == 1


def test_billing_closure_email_is_staged_and_assigned_to_jamie(tmp_path):
    runtime = _collector_runtime(tmp_path)
    message = _message(
        to="billing@novapointofsale.com",
        subject="Account closure",
        snippet="Please close the following location only.",
    )
    runtime.inbox_ledger.upsert_detected(message)
    runtime.inbox_ledger.classify(message["id"], classify_inbox_message(message))
    staged = []
    submitted = []
    runtime._stage_billing_closure_email_evidence = (
        lambda item: staged.append(item)
        or {
            "id": "a" * 32,
            "name": f"billing-close-confirmation-{message['id']}.eml",
            "mimetype": "text/plain",
            "size": 1024,
            "sha256": "b" * 64,
            "kind": "file",
        }
    )
    runtime.submit_billing_closure_email_intake = (
        lambda **kwargs: submitted.append(kwargs)
        or {
            "accepted": True,
            "job_id": "billing-closure-job",
            "duplicate": False,
        }
    )

    assert runtime._dispatch_inbox_ledger_items() == 1
    assert staged[0]["messageId"] == message["id"]
    assert submitted[0]["idempotency_key"] == (
        f"inbox-ledger:billing-closure:{message['id']}"
    )
    item = runtime.inbox_ledger.item(message["id"])
    assert item["state"] == "action_pending"
    assert item["assignedAgent"] == "billing_agent"
    assert item["assignedJobId"] == "billing-closure-job"
    projection = runtime.inbox_ledger.email_watch_projection()
    assert projection["emails"][0]["id"] == message["id"]
    assert projection["emails"][0]["recommendedAction"].startswith(
        "Jamie is matching"
    )


def test_expired_history_runs_bounded_reconciliation_before_checkpoint(tmp_path, monkeypatch):
    runtime = _collector_runtime(tmp_path)
    runtime.inbox_ledger.set_meta("gmail_history_id", "expired")
    message = _message()
    monkeypatch.setattr(command_center_server, "_gmail_access_token", lambda _path: "token")
    monkeypatch.setattr(
        command_center_server,
        "_gmail_api_get_json_with_retry",
        lambda *_args, **_kwargs: {"emailAddress": "owner@example.com", "historyId": "300"},
    )
    monkeypatch.setattr(
        command_center_server,
        "_gmail_history_message_ids",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            urllib.error.HTTPError("https://gmail.example/history", 404, "expired", None, None)
        ),
    )
    monkeypatch.setattr(command_center_server, "_gmail_search_message_ids_paginated", lambda *_args, **_kwargs: [message["id"]])
    monkeypatch.setattr(command_center_server, "_gmail_message_metadata", lambda *_args, **_kwargs: dict(message))

    result = runtime.collect_inbox_now()

    assert result["mode"] == "history_gap_reconciliation"
    assert runtime.inbox_ledger.get_meta("gmail_history_id") == "300"


def test_fetch_failure_does_not_advance_history_checkpoint(tmp_path, monkeypatch):
    runtime = _collector_runtime(tmp_path)
    monkeypatch.setattr(command_center_server, "_gmail_access_token", lambda _path: "token")
    monkeypatch.setattr(
        command_center_server,
        "_gmail_api_get_json_with_retry",
        lambda *_args, **_kwargs: {"emailAddress": "owner@example.com", "historyId": "400"},
    )
    monkeypatch.setattr(command_center_server, "_gmail_search_message_ids_paginated", lambda *_args, **_kwargs: ["m1"])
    monkeypatch.setattr(
        command_center_server,
        "_gmail_message_metadata",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("temporary Gmail failure")),
    )

    with pytest.raises(RuntimeError, match="temporary Gmail failure"):
        runtime.collect_inbox_now()

    assert runtime.inbox_ledger.get_meta("gmail_history_id") == ""
    assert runtime.inbox_ledger.status()["lastPoll"]["status"] == "failed"


def test_transient_gmail_read_retries_are_bounded(monkeypatch):
    calls = []
    sleeps = []

    def fake_get(_url, *, token):
        calls.append(token)
        if len(calls) < 3:
            raise urllib.error.HTTPError("https://gmail.example", 429, "rate limited", None, None)
        return {"ok": True}

    monkeypatch.setattr(command_center_server, "_gmail_api_get_json", fake_get)
    monkeypatch.setattr(command_center_server.time, "sleep", lambda seconds: sleeps.append(seconds))

    result = command_center_server._gmail_api_get_json_with_retry("https://gmail.example", token="token")

    assert result == {"ok": True}
    assert len(calls) == 3
    assert sleeps == [0.25, 0.5]


def test_retrying_native_cleanup_reads_before_any_second_write(tmp_path, monkeypatch):
    runtime = _collector_runtime(tmp_path)
    message = _message(sender="notify@salesforce.com", subject="Salesforce notification 347000")
    runtime.inbox_ledger.upsert_detected(message)
    runtime.inbox_ledger.classify(
        message["id"],
        RouteDecision("salesforce_notification", "gmail_cleanup_mark_read", "Known notice.", True, True),
    )
    monkeypatch.setattr(command_center_server, "_gmail_access_token", lambda _path: "token")
    monkeypatch.setattr(command_center_server, "_gmail_profile_email", lambda _token: "owner@example.com")
    monkeypatch.setattr(
        command_center_server,
        "_gmail_email_watch_thread_state",
        lambda *_args, **_kwargs: {"verified": True, "unread": False, "inInbox": True},
    )
    runtime._apply_cached_gmail_label_action = lambda *_args, **_kwargs: (_ for _ in ()).throw(
        AssertionError("duplicate Gmail write attempted")
    )

    assert runtime._dispatch_inbox_ledger_items() == 0
    assert runtime.inbox_ledger.item(message["id"])["state"] == "complete"


def test_singapore_inbox_item_is_classified_but_deferred_to_daily_watch(tmp_path):
    runtime = _collector_runtime(tmp_path)
    submitted = []
    runtime.submit_singapore_ftp_scan = lambda **kwargs: submitted.append(kwargs) or {
        "accepted": True,
        "job_id": "unexpected",
    }
    message = _message(
        sender="integration@novapointofsale.com",
        subject="Singapore FTP upload failed",
    )
    runtime.inbox_ledger.upsert_detected(message)
    runtime.inbox_ledger.classify(message["id"], classify_inbox_message(message))

    assert runtime._dispatch_inbox_ledger_items() == 0
    assert submitted == []
    assert runtime.inbox_ledger.item(message["id"])["state"] == "classified"


def test_singapore_fast_job_claims_current_ledger_batch_before_running(tmp_path):
    runtime = _collector_runtime(tmp_path)
    message = _message(
        sender="sgpos_support@capitaland.com",
        subject="Raffles City : nectarlife (5700768)- Non Submission July 2026",
    )
    runtime.inbox_ledger.upsert_detected(message)
    runtime.inbox_ledger.classify(message["id"], classify_inbox_message(message))

    runtime._assign_singapore_runner_inbox_items(
        "cc-20260717T201756Z-555d7dacc6",
        action_key="inbox-ledger:singapore:manual-nonsubmission-parserfix-2026-07-17-v1",
    )

    item = runtime.inbox_ledger.item(message["id"])
    assert item["state"] == "action_pending"
    assert item["assignedAgent"] == "coding_agent"
    assert item["assignedJobId"] == "cc-20260717T201756Z-555d7dacc6"
    assert item["actionKey"] == "inbox-ledger:singapore:manual-nonsubmission-parserfix-2026-07-17-v1"


def test_legacy_redacted_assignment_can_be_requeued_once(tmp_path):
    ledger = InboxLedger(tmp_path / "inbox.sqlite3")
    message = _message(
        sender="sgpos_support@capitaland.com",
        subject="Raffles City : nectarlife (5700768)- Non Submission July 2026",
    )
    ledger.upsert_detected(message)
    ledger.classify(message["id"], classify_inbox_message(message))
    ledger.mark_assigned(
        [message["id"]],
        agent="coding_agent",
        job_id="cc-20260717T201756Z-555d7dacc6",
        action_key="inbox-ledger:singapore:test",
    )
    with ledger._connect() as connection:
        connection.execute(
            "UPDATE inbox_items SET assigned_job_id='[redacted]' WHERE message_id=?",
            (message["id"],),
        )

    assert ledger.repair_legacy_redacted_assignment(message["id"]) is True
    item = ledger.item(message["id"])
    assert item["state"] == "classified"
    assert item["assignedJobId"] == ""
    assert ledger.repair_legacy_redacted_assignment(message["id"]) is False


def test_ledger_collector_excludes_legacy_email_writers_but_keeps_singapore(tmp_path, monkeypatch):
    runtime = object.__new__(CommandCenterRuntime)
    runtime.config = SimpleNamespace(
        defaults={
            "ops_inbox_ledger_enabled": True,
            "ops_email_watch_enabled": True,
            "ops_support_email_intake_enabled": True,
            "ops_propelr_nmi_enabled": True,
            "ops_singapore_ftp_enabled": True,
            "ops_schedule_watch_enabled": False,
            "ops_ticket_refresh_enabled": False,
            "ops_kpi_dashboard_enabled": False,
            "ops_weekly_yaron_report_enabled": False,
            "prospective_enabled": False,
            "drawing_board_digest_enabled": False,
            "ops_zoom_chat_monitor_enabled": False,
        }
    )
    runtime.inbox_ledger = InboxLedger(tmp_path / "inbox.sqlite3")
    captured = []
    runtime._start_watcher = lambda **kwargs: captured.append(kwargs)
    monkeypatch.delenv("COMMAND_CENTER_DISABLE_WATCHERS", raising=False)

    runtime._start_background_watchers()

    assert [item["name"] for item in captured] == [
        "ops-inbox-ledger-collector",
        "ops-singapore-ftp-watch",
    ]
    assert captured[0]["interval_seconds"] == 10
    assert captured[0]["minimum_interval_seconds"] == 5
    assert captured[1]["target"].__name__ == "_submit_singapore_ftp_scan_if_due"


def test_ledger_disabled_restores_legacy_email_watchers(monkeypatch):
    runtime = object.__new__(CommandCenterRuntime)
    runtime.config = SimpleNamespace(
        defaults={
            "ops_inbox_ledger_enabled": False,
            "ops_email_watch_enabled": True,
            "ops_support_email_intake_enabled": True,
            "ops_propelr_nmi_enabled": True,
            "ops_singapore_ftp_enabled": True,
            "ops_schedule_watch_enabled": False,
            "ops_ticket_refresh_enabled": False,
            "ops_kpi_dashboard_enabled": False,
            "ops_weekly_yaron_report_enabled": False,
            "prospective_enabled": False,
            "drawing_board_digest_enabled": False,
            "ops_zoom_chat_monitor_enabled": False,
        }
    )
    runtime.inbox_ledger = None
    captured = []
    runtime._start_watcher = lambda **kwargs: captured.append(kwargs["name"])
    monkeypatch.delenv("COMMAND_CENTER_DISABLE_WATCHERS", raising=False)

    runtime._start_background_watchers()

    assert captured == [
        "ops-support-email-intake-watch",
        "ops-email-watch",
        "ops-propelr-nmi-watch",
        "ops-singapore-ftp-watch",
    ]


def test_sse_endpoint_is_loopback_and_origin_restricted():
    runtime = SimpleNamespace(
        inbox_ledger_events=lambda sequence, timeout_seconds=20: [
            {"sequence": sequence + 1, "type": "classified", "payload": {}, "messageId": "m1"}
        ]
    )
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(runtime))
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}/ops/inbox-ledger/events?after=0&timeout=0"
    try:
        bad = urllib.request.Request(url, headers={"Origin": "https://evil.example"})
        with pytest.raises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(bad, timeout=3)
        assert caught.value.code == 403

        with urllib.request.urlopen(url, timeout=3) as response:
            body = response.read().decode("utf-8")
            assert response.headers.get_content_type() == "text/event-stream"
            assert "event: inbox" in body
            assert "id: 1" in body
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
