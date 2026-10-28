from __future__ import annotations

import hashlib
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier, Lock
from typing import Any, Callable

import pytest

from scoped_operations_mcp.salesforce_client import (
    BILLING_ORG_WIDE_EMAIL_ADDRESS,
    CREDENTIALS_AUTHORIZED_RECIPIENTS,
    CREDENTIALS_TEMPLATE_DEVELOPER_NAME,
    CREDENTIALS_TEMPLATE_ID,
    CREDENTIALS_TEMPLATE_NAME,
    CREDENTIALS_TEMPLATE_SUBJECT,
    CREDENTIALS_TICKET_ID,
    SUPPORT_ORG_WIDE_EMAIL_ADDRESS,
    ScopedSalesforceClient,
    SalesforceSettings,
    SalesforceUnavailableError,
)


TICKET_ID = "a0G000000000000AAA"
ACCOUNT_ID = "001000000000001AAA"
CONTACT_ID = "003000000000001AAA"
TEMPLATE_ID = "00X000000000001AAA"
BRAND_TEMPLATE_ID = "016A0000000ChpTIAS"
RECIPIENT = "customer@example.com"


class SimulatedProcessCrash(RuntimeError):
    pass


def _client(journal_path: Path) -> ScopedSalesforceClient:
    return ScopedSalesforceClient(
        SalesforceSettings(
            "https://example.invalid",
            "https://login.invalid",
            "",
            "",
            "",
            "",
            "token",
            False,
            journal_path=journal_path,
        )
    )


def _sender() -> dict[str, str]:
    return {
        "department": "billing",
        "orgWideEmailAddressId": "0D2000000000001AAA",
        "address": BILLING_ORG_WIDE_EMAIL_ADDRESS,
        "senderType": "OrgWideEmailAddress",
        "senderPolicy": "department_org_wide",
    }


def _support_sender() -> dict[str, str]:
    return {
        "department": "support",
        "orgWideEmailAddressId": "0D2000000000002AAA",
        "address": SUPPORT_ORG_WIDE_EMAIL_ADDRESS,
        "senderType": "OrgWideEmailAddress",
        "senderPolicy": "department_org_wide",
    }


def _targets() -> dict[str, Any]:
    return {
        "accountId": ACCOUNT_ID,
        "accountName": "LEJAIM SPA",
        "primaryContactId": CONTACT_ID,
        "primaryRecipient": RECIPIENT,
        "primarySendContactId": CONTACT_ID,
        "renderContactId": CONTACT_ID,
        "additionalRecipients": [],
        "recipients": [RECIPIENT],
    }


def _approved_prepared(situation: str, subject: str) -> dict[str, Any]:
    html = (
        '<body styleInsert="1"><img src="ImageServer">'
        "Hello, verified account update for LEJAIM SPA ticket 347191. "
        "The Nova Support Team</body>"
    )
    plain = (
        "Hello, verified account update for LEJAIM SPA ticket 347191. "
        "The Nova Support Team"
    )
    return {
        "ticketId": TICKET_ID,
        "situation": situation,
        "templateId": TEMPLATE_ID,
        "templateName": "Approved template",
        "templateDeveloperName": "Approved_Template",
        "subject": subject,
        "brandTemplateId": BRAND_TEMPLATE_ID,
        "renderedPreview": {
            "subject": subject,
            "htmlBody": html,
            "plainTextBody": plain,
        },
        "previewSummary": {
            "verified": True,
            "htmlSha256": hashlib.sha256(html.encode("utf-8")).hexdigest(),
            "plainTextSha256": hashlib.sha256(plain.encode("utf-8")).hexdigest(),
        },
        "targets": _targets(),
        "sender": _sender(),
        "requiredFragments": ["LEJAIM SPA", "347191"],
        "customized": False,
    }


def _configure_route(
    monkeypatch: pytest.MonkeyPatch,
    client: ScopedSalesforceClient,
    route: str,
) -> tuple[Callable[[], dict[str, Any]], str, str]:
    if route == "credentials":
        prepared = {
            "ticketId": CREDENTIALS_TICKET_ID,
            "ticketNumber": "347370",
            "situation": "company_credentials_347370",
            "templateId": CREDENTIALS_TEMPLATE_ID,
            "templateName": CREDENTIALS_TEMPLATE_NAME,
            "templateDeveloperName": CREDENTIALS_TEMPLATE_DEVELOPER_NAME,
            "subject": CREDENTIALS_TEMPLATE_SUBJECT,
            "renderedPreview": {
                "subject": CREDENTIALS_TEMPLATE_SUBJECT,
                "htmlBody": "<p>Redacted credential template body.</p>",
                "plainTextBody": "Redacted credential template body.",
            },
            "validation": {"verified": True},
            "recipients": list(CREDENTIALS_AUTHORIZED_RECIPIENTS),
            "sender": _support_sender(),
        }
        monkeypatch.setattr(
            client,
            "_prepare_ticket_company_credentials_email",
            lambda **_kwargs: dict(prepared),
        )
        return (
            lambda: client.send_ticket_company_credentials_email(
                ticket_id=CREDENTIALS_TICKET_ID,
                requested_recipients=list(CREDENTIALS_AUTHORIZED_RECIPIENTS),
                lane="tickets_agent",
            ),
            "_matching_ticket_sensitive_email",
            "$0.00",
        )

    if route == "general":
        subject = "NovaPOS Billing Inquiry Update"
        prepared = _approved_prepared("billing_inquiry_update", subject)
        monkeypatch.setattr(
            client,
            "_prepare_ticket_template_email",
            lambda **_kwargs: dict(prepared),
        )
        return (
            lambda: client.send_ticket_template_email(
                ticket_id=TICKET_ID,
                situation="billing_inquiry_update",
                details={
                    "last4Digits": "2828",
                    "message": "The verified account update is complete.",
                },
                lane="billing_agent",
            ),
            "_matching_ticket_template_email",
            "$0.00",
        )

    if route == "cancellation":
        subject = "Your NOVA POS account has been closed"
        ticket = {
            "Id": TICKET_ID,
            "Name": "347191",
            "Account__c": ACCOUNT_ID,
        }
        monkeypatch.setattr(
            client,
            "_assert_account_cancellation_ticket",
            lambda *_args: dict(ticket),
        )
        monkeypatch.setattr(
            client,
            "_query",
            lambda _soql: {
                "records": [
                    {
                        "Id": ACCOUNT_ID,
                        "Name": "LEJAIM SPA",
                        "Status__c": "Inactive",
                        "NovaPOS_Active__c": 0,
                        "Email_Address__c": RECIPIENT,
                        "PrimaryContact__c": CONTACT_ID,
                        "PrimaryContact__r": {
                            "Id": CONTACT_ID,
                            "Name": "Customer",
                            "FirstName": "Customer",
                            "Email": RECIPIENT,
                        },
                    }
                ]
            },
        )
        monkeypatch.setattr(
            client,
            "read_account_locations",
            lambda _account_id: {
                "records": [
                    {
                        "Id": "a0L000000000001AAA",
                        "Location_ID__c": 1,
                        "Status__c": "Inactive",
                        "Chargify_Subscription_ID__c": 8001,
                    }
                ]
            },
        )
        monkeypatch.setattr(
            client,
            "read_account_orders",
            lambda _account_id: {
                "records": [
                    {
                        "Id": "a0O000000000001AAA",
                        "Total_Number_of_Locations_for_this_order__c": -1,
                        "Location_I_D__c": "1",
                        "Chargify_Subscription_ID__c": 8001,
                        "Contract_Name__c": "-1 Location. Billing Automation Order",
                        "Description__c": (
                            "Account cancellation under ticket 347191. Locations: 1. "
                            "Chargify subscription: 8001. "
                            f"Maxio location-component evidence: {'a' * 64}"
                        ),
                    }
                ]
            },
        )
        monkeypatch.setattr(client, "_billing_confirmation_targets", lambda _ticket: _targets())
        monkeypatch.setattr(
            client,
            "_resolve_approved_email_template",
            lambda *_args, **_kwargs: {
                "templateId": TEMPLATE_ID,
                "templateName": "NovaPOS Account Cancellation Confirmed",
                "templateDeveloperName": "NovaPOS_Account_Cancellation_Confirmed",
                "subject": subject,
                "brandTemplateId": BRAND_TEMPLATE_ID,
            },
        )
        monkeypatch.setattr(client, "_resolve_department_sender", lambda _department: _sender())
        prepared = _approved_prepared("account_cancellation_confirmed", subject)
        monkeypatch.setattr(
            client,
            "_render_stored_email_template",
            lambda **_kwargs: dict(prepared["renderedPreview"]),
        )
        return (
            lambda: client.send_account_cancellation_confirmation_email(
                TICKET_ID,
                ACCOUNT_ID,
            ),
            "_matching_ticket_template_email",
            "$0.00",
        )

    amount = "$20.00" if route == "credit" else "$144.99"
    subject = (
        "Your Nova account credit has been approved"
        if route == "credit"
        else "Your Nova refund has been submitted"
    )
    developer_name = (
        "Credit_was_applied_to_your_account"
        if route == "credit"
        else "A_Refund_was_Submitted"
    )
    amount_cents = 2_000 if route == "credit" else 14_499
    monkeypatch.setattr(client, "_assert_ticket_scope", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        client,
        "read_ticket",
        lambda _ticket_id: {
            "ok": True,
            "record": {
                "Account__c": ACCOUNT_ID,
                "Contact__c": CONTACT_ID,
                "Credit_Amount__c": 20.0,
            },
        },
    )
    monkeypatch.setattr(client, "_billing_confirmation_targets", lambda _ticket: _targets())
    monkeypatch.setattr(
        client,
        "_resolve_approved_email_template",
        lambda *_args, **_kwargs: {
            "templateId": TEMPLATE_ID,
            "templateName": "Approved billing confirmation",
            "templateDeveloperName": developer_name,
            "subject": subject,
            "brandTemplateId": BRAND_TEMPLATE_ID,
        },
    )
    monkeypatch.setattr(client, "_resolve_department_sender", lambda _department: _sender())
    monkeypatch.setattr(
        client,
        "_render_stored_email_template",
        lambda **_kwargs: {
            "subject": subject,
            "htmlBody": (
                '<body styleInsert="1"><img src="ImageServer">'
                f"Hello, confirmed amount: {amount}. The Nova Support Team</body>"
            ),
            "plainTextBody": (
                f"Hello, confirmed amount: {amount}. The Nova Support Team"
            ),
        },
    )
    if route == "credit":
        invoke = lambda: client.send_ticket_credit_confirmation_email(
            ticket_id=TICKET_ID,
            credit_amount_cents=amount_cents,
            allowed_record_types={"3. Billing"},
        )
    else:
        invoke = lambda: client.send_ticket_refund_confirmation_email(
            ticket_id=TICKET_ID,
            refund_amount_cents=amount_cents,
            allowed_record_types={"3. Billing"},
        )
    return invoke, "_matching_ticket_refund_confirmation", amount


def _install_email_surface(
    monkeypatch: pytest.MonkeyPatch,
    client: ScopedSalesforceClient,
    *,
    matcher_name: str,
    amount: str,
    state: dict[str, Any],
) -> None:
    def matching(
        ticket_id: str,
        *,
        recipient: str,
        subject: str,
        expected_from_address: str,
        **_kwargs: Any,
    ) -> dict[str, Any] | None:
        if state["precheckFailures"]:
            state["precheckFailures"] -= 1
            raise SalesforceUnavailableError("transient EmailMessage precheck failure")
        if not state["providerAccepted"]:
            return None
        if state["crashReadbacks"]:
            state["crashReadbacks"] -= 1
            raise SimulatedProcessCrash("after provider acceptance, before readback")
        body = (
            f"Confirmed amount: {amount}"
            if matcher_name == "_matching_ticket_refund_confirmation"
            else "LEJAIM SPA ticket 347191"
        )
        return {
            "Id": "02s000000000001AAA",
            "Subject": subject,
            "ToAddress": recipient,
            "TextBody": body,
            "Incoming": False,
            "Status": "3",
            "RelatedToId": ticket_id,
            "FromAddress": expected_from_address,
        }

    def request(method: str, path: str, *, params=None, json=None):
            if method == "GET" and path.startswith("/sobjects/NovaPOS_Ticket__c/"):
                return {
                    "Id": "a0G000000000000AAA",
                    "Name": "347191",
                    "Account__c": "001000000000001AAA",
                    "Contact__c": "003000000000001AAA",
                    "Description__c": "Cancel all service.",
                    "Email_Address_to_Send_Ticket__c": "test@example.com",
                    "Account_s_Email_Address__c": "primary@example.com",
                }
            assert method == "POST"
            assert path == "/actions/standard/emailSimple"
            with state["lock"]:
                state["providerCalls"] += 1
            time.sleep(state["providerDelay"])
            state["providerAccepted"] = True
            return [
                {"actionName": "emailSimple", "errors": None, "isSuccess": True}
                for _ in json["inputs"]
            ]

    monkeypatch.setattr(client, matcher_name, matching)
    monkeypatch.setattr(client, "_request", request)


@pytest.mark.parametrize(
    "route",
    ["general", "cancellation", "credit", "refund", "credentials"],
)
def test_approved_email_route_recovers_crash_after_provider_without_duplicate_send(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    route: str,
) -> None:
    client = _client(tmp_path / f"{route}.jsonl")
    invoke, matcher_name, amount = _configure_route(monkeypatch, client, route)
    state = {
        "providerAccepted": False,
        "providerCalls": 0,
        "providerDelay": 0.0,
        "crashReadbacks": 1,
        "precheckFailures": 0,
        "lock": Lock(),
    }
    _install_email_surface(
        monkeypatch,
        client,
        matcher_name=matcher_name,
        amount=amount,
        state=state,
    )

    with pytest.raises(SimulatedProcessCrash, match="after provider acceptance"):
        invoke()

    recovered = invoke()

    assert state["providerCalls"] == 1
    assert recovered["sent"] is False
    assert recovered["duplicate"] is True
    assert recovered["replayed"] is True
    assert recovered["writesPerformed"] is False
    assert recovered["deliveryVerified"] is True
    assert recovered["recoveredFromEmailMessageReadback"] is True
    journal = (tmp_path / f"{route}.jsonl").read_text(encoding="utf-8")
    assert '"status":"pending"' in journal
    assert '"status":"accepted"' in journal


@pytest.mark.parametrize(
    "route",
    ["general", "cancellation", "credit", "refund", "credentials"],
)
def test_approved_email_route_serializes_concurrent_identical_sends(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    route: str,
) -> None:
    client = _client(tmp_path / f"{route}.jsonl")
    invoke, matcher_name, amount = _configure_route(monkeypatch, client, route)
    state = {
        "providerAccepted": False,
        "providerCalls": 0,
        "providerDelay": 0.05,
        "crashReadbacks": 0,
        "precheckFailures": 0,
        "lock": Lock(),
    }
    _install_email_surface(
        monkeypatch,
        client,
        matcher_name=matcher_name,
        amount=amount,
        state=state,
    )
    start = Barrier(2)

    def concurrent_send() -> dict[str, Any]:
        start.wait()
        return invoke()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _index: concurrent_send(), range(2)))

    assert state["providerCalls"] == 1
    assert sum(result["sent"] is True for result in results) == 1
    assert sum(result["replayed"] is True for result in results) == 1
    assert {result["idempotencyKey"] for result in results} == {
        results[0]["idempotencyKey"]
    }


@pytest.mark.parametrize(
    "route",
    ["general", "cancellation", "credit", "refund", "credentials"],
)
def test_approved_email_route_precheck_failure_is_safely_retryable_before_provider(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    route: str,
) -> None:
    client = _client(tmp_path / f"{route}.jsonl")
    invoke, matcher_name, amount = _configure_route(monkeypatch, client, route)
    state = {
        "providerAccepted": False,
        "providerCalls": 0,
        "providerDelay": 0.0,
        "crashReadbacks": 0,
        "precheckFailures": 1,
        "lock": Lock(),
    }
    _install_email_surface(
        monkeypatch,
        client,
        matcher_name=matcher_name,
        amount=amount,
        state=state,
    )

    with pytest.raises(
        SalesforceUnavailableError,
        match="transient EmailMessage precheck failure",
    ):
        invoke()
    assert state["providerCalls"] == 0

    result = invoke()

    assert state["providerCalls"] == 1
    assert result["sent"] is True
    assert result["replayed"] is False
    journal = (tmp_path / f"{route}.jsonl").read_text(encoding="utf-8")
    assert '"providerAttempted":false' in journal
    assert '"providerAttempted":true' in journal


@pytest.mark.parametrize("status,to_address", [("2", RECIPIENT), ("3", f"{RECIPIENT};other@example.com")])
def test_authoritative_email_match_requires_sent_status_and_exact_single_recipient(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    status: str,
    to_address: str,
) -> None:
    client = _client(tmp_path / "exact-readback.jsonl")
    record = {
        "Id": "02s000000000001AAA",
        "Subject": "Approved subject",
        "ToAddress": to_address,
        "TextBody": "LEJAIM SPA ticket 347191 confirmed amount: $20.00",
        "Incoming": False,
        "Status": status,
        "RelatedToId": TICKET_ID,
        "FromAddress": BILLING_ORG_WIDE_EMAIL_ADDRESS,
    }
    monkeypatch.setattr(
        client,
        "_ticket_email_records",
        lambda *_args, **_kwargs: [dict(record)],
    )

    assert (
        client._matching_ticket_template_email(
            TICKET_ID,
            recipient=RECIPIENT,
            subject="Approved subject",
            required_fragments=["LEJAIM SPA", "347191"],
            expected_from_address=BILLING_ORG_WIDE_EMAIL_ADDRESS,
        )
        is None
    )
    assert (
        client._matching_ticket_refund_confirmation(
            TICKET_ID,
            recipient=RECIPIENT,
            subject="Approved subject",
            expected_amount="$20.00",
            expected_from_address=BILLING_ORG_WIDE_EMAIL_ADDRESS,
        )
        is None
    )
    assert (
        client._matching_ticket_sensitive_email(
            TICKET_ID,
            recipient=RECIPIENT,
            subject="Approved subject",
            expected_from_address=BILLING_ORG_WIDE_EMAIL_ADDRESS,
        )
        is None
    )


def test_pending_email_without_complete_readback_remains_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    client = _client(tmp_path / "fail-closed.jsonl")
    invoke, matcher_name, amount = _configure_route(monkeypatch, client, "general")
    state = {
        "providerAccepted": False,
        "providerCalls": 0,
        "providerDelay": 0.0,
        "crashReadbacks": 1,
        "precheckFailures": 0,
        "lock": Lock(),
    }
    _install_email_surface(
        monkeypatch,
        client,
        matcher_name=matcher_name,
        amount=amount,
        state=state,
    )
    with pytest.raises(SimulatedProcessCrash):
        invoke()

    monkeypatch.setattr(
        client,
        "_reconcile_approved_ticket_template_delivery",
        lambda _prepared: None,
    )
    with pytest.raises(
        SalesforceUnavailableError,
        match="no send retry was attempted",
    ):
        invoke()

    assert state["providerCalls"] == 1
