from __future__ import annotations

from types import SimpleNamespace

import pytest

from codex_slack_bridge import command_center_server
from codex_slack_bridge.command_center_server import (
    CommandCenterRuntime,
    build_ops_billing_closure_email_intake_prompt,
)


MESSAGE_ID = "19e8f10b1bab335b"
ATTACHMENT = {
    "name": f"billing-close-confirmation-{MESSAGE_ID}.eml",
    "sha256": "a" * 64,
    "size": 2048,
}


def _processed_result(*, scope: str = "location") -> str:
    location_ids = ["a1L000000000001AAA"] if scope == "location" else []
    payload = {
        "schemaVersion": 1,
        "status": "processed",
        "sourceEmailId": MESSAGE_ID,
        "scope": scope,
        "accountId": "001000000000001AAA",
        "locationIds": location_ids,
        "ticket": {
            "id": "a0G000000000001AAA",
            "number": "347500",
            "recordType": "3. Billing",
            "origin": "created_or_reused_source_key",
            "sourceKey": f"billing-closure-email:{MESSAGE_ID}",
        },
        "attachment": {
            "fileName": ATTACHMENT["name"],
            "sha256": ATTACHMENT["sha256"],
            "verified": True,
        },
        "summary": "Customer requested closure of one verified location.",
        "blockers": [],
    }
    return (
        "COMPLETED\n"
        f"{command_center_server.OPS_BILLING_CLOSURE_EMAIL_RESULT_MARKER} "
        f"{command_center_server.json.dumps(payload, separators=(',', ':'))}"
    )


def test_billing_closure_prompt_requires_body_scope_inspection_and_prohibits_cancellation():
    prompt = build_ops_billing_closure_email_intake_prompt(
        message_id=MESSAGE_ID,
        thread_id="thread-1",
        sender="Customer <customer@example.com>",
        subject="Close account",
        attachment=ATTACHMENT,
    )

    assert "Never classify from the subject alone" in prompt
    assert "`this location`" in prompt
    assert "strict subset" in prompt
    assert "Ambiguous scope is not a reason to omit the ticket or evidence" in prompt
    assert "Do not close an Account or Location" in prompt
    assert "salesforce_account_cancellation_email_attachment_upload" in prompt


def test_billing_closure_result_validation_accepts_location_scope_with_exact_eml():
    result_text = _processed_result()

    normalized = command_center_server._validate_ops_billing_closure_email_result(
        command_center_server._extract_ops_billing_closure_email_result(result_text),
        expected_message_id=MESSAGE_ID,
        expected_attachment={
            "fileName": ATTACHMENT["name"],
            "sha256": ATTACHMENT["sha256"],
        },
        outcome=command_center_server.classify_agent_outcome(result_text),
    )

    assert normalized["scope"] == "location"
    assert normalized["locationIds"] == ["a1L000000000001AAA"]
    assert normalized["attachment"]["verified"] is True


def test_billing_closure_result_validation_rejects_location_scope_without_location_id():
    result_text = _processed_result(scope="account").replace(
        '"scope":"account"',
        '"scope":"location"',
    )

    with pytest.raises(ValueError, match="at least one verified location"):
        command_center_server._validate_ops_billing_closure_email_result(
            command_center_server._extract_ops_billing_closure_email_result(
                result_text
            ),
            expected_message_id=MESSAGE_ID,
            expected_attachment={
                "fileName": ATTACHMENT["name"],
                "sha256": ATTACHMENT["sha256"],
            },
            outcome=command_center_server.classify_agent_outcome(result_text),
        )


def test_billing_closure_finalizer_marks_only_after_independent_salesforce_readback():
    runtime = object.__new__(CommandCenterRuntime)
    runtime.config = SimpleNamespace(defaults={})
    completed = []
    updates = []
    gmail_calls = []
    runtime.inbox_ledger = SimpleNamespace(
        complete=lambda message_id, **kwargs: completed.append((message_id, kwargs)),
        block=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("processed item should not be blocked")
        ),
    )
    runtime._update_job = lambda job_key, **fields: updates.append((job_key, fields))
    runtime._readback_billing_closure_email_ticket = lambda _item: {
        "verified": True,
        "status": "verified",
        "attachmentVerified": True,
    }

    def apply_labels(cached_email, **kwargs):
        gmail_calls.append((cached_email, kwargs))
        return {"ok": True, "verified": True}

    runtime._apply_cached_gmail_label_action = apply_labels
    job_record = {
        "payload": {
            "sourceEmailId": MESSAGE_ID,
            "threadId": "thread-1",
            "from": "Customer <customer@example.com>",
            "subject": "Close account",
            "evidence": {
                "fileName": ATTACHMENT["name"],
                "sha256": ATTACHMENT["sha256"],
            },
        }
    }

    receipt = runtime._finalize_billing_closure_email_intake(
        _processed_result(),
        job_key="job-1",
        job_record=job_record,
    )

    assert receipt["status"] == "processed"
    assert gmail_calls[0][1]["remove_label_ids"] == ["UNREAD"]
    assert gmail_calls[0][1]["prefer_thread"] is False
    assert completed[0][0] == MESSAGE_ID
    assert completed[0][1]["write_verified"] is True
    assert updates[0][1]["billingClosureEmailReceipt"]["gmail"][
        "readbackVerified"
    ] is True


def test_billing_closure_finalizer_leaves_gmail_untouched_when_salesforce_readback_fails():
    runtime = object.__new__(CommandCenterRuntime)
    runtime.config = SimpleNamespace(defaults={})
    runtime.inbox_ledger = None
    runtime._readback_billing_closure_email_ticket = lambda _item: {
        "verified": False,
        "status": "mismatch",
    }
    runtime._apply_cached_gmail_label_action = lambda *_args, **_kwargs: (
        _ for _ in ()
    ).throw(AssertionError("Gmail must remain untouched"))

    with pytest.raises(RuntimeError, match="Independent Salesforce readback"):
        runtime._finalize_billing_closure_email_intake(
            _processed_result(),
            job_key="job-1",
            job_record={
                "payload": {
                    "sourceEmailId": MESSAGE_ID,
                    "evidence": {
                        "fileName": ATTACHMENT["name"],
                        "sha256": ATTACHMENT["sha256"],
                    },
                }
            },
        )
