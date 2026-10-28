from __future__ import annotations

import pytest

from scoped_operations_mcp.salesforce_client import (
    SalesforceScopeError,
    ScopedSalesforceClient,
)
from scoped_operations_mcp.salesforce_support_email_readback_cli import (
    READBACK_SOURCE,
    execute_billing_closure_email_ticket_readback,
    execute_support_email_ticket_readback,
)


TICKET_ID = "a0G000000000001AAA"
ACCOUNT_ID = "001000000000001AAA"


class FakeSalesforce:
    def __init__(self, *, source_key: str = "support-email:message-1", closed: bool = False):
        self.source_key = source_key
        self.closed = closed
        self.calls = []

    def verify_support_email_ticket_claim(self, **claim):
        self.calls.append(claim)
        return {
            "ticketIdMatches": True,
            "ticketNumberMatches": True,
            "accountIdMatches": True,
            "accountEligible": True,
            "recordTypeMatches": True,
            "sourceKeyMatches": self.source_key == "support-email:message-1",
            "isClosed": self.closed,
        }


def _payload() -> dict:
    return {
        "action": "read_support_email_ticket",
        "ticketId": TICKET_ID,
        "ticketNumber": "347314",
        "accountId": ACCOUNT_ID,
        "recordType": "1. NOVA Classic",
        "sourceEmailId": "message-1",
        "sourceKey": "support-email:message-1",
    }


def test_support_email_readback_returns_only_bounded_verified_receipt():
    client = FakeSalesforce()

    result = execute_support_email_ticket_readback(_payload(), client=client)

    assert result == {
        "ok": True,
        "action": "read_support_email_ticket",
        "status": "verified",
        "verified": True,
        "source": READBACK_SOURCE,
        "checkedAtUtc": result["checkedAtUtc"],
        "ticketId": TICKET_ID,
        "ticketNumber": "347314",
        "accountId": ACCOUNT_ID,
        "accountEligible": True,
        "recordType": "1. NOVA Classic",
        "sourceEmailId": "message-1",
        "sourceKey": "support-email:message-1",
        "isClosed": False,
        "reasonCodes": [],
        "readOnly": True,
        "writesPerformed": False,
        "emailSent": False,
    }
    assert client.calls == [
        {
            "ticket_id": TICKET_ID,
            "ticket_number": "347314",
            "account_id": ACCOUNT_ID,
            "record_type": "1. NOVA Classic",
            "source_key": "support-email:message-1",
            "allowed_record_types": frozenset(
                {"1. NOVA Classic", "2. Nova Wave"}
            ),
        }
    ]
    serialized = str(result)
    assert "Description" not in serialized
    assert "customer@example.com" not in serialized
    assert "Customer text" not in serialized


def test_support_email_readback_rejects_source_key_mismatch_without_exposing_ticket_text():
    result = execute_support_email_ticket_readback(
        _payload(),
        client=FakeSalesforce(source_key="support-email:different-message"),
    )

    assert result["status"] == "mismatch"
    assert result["verified"] is False
    assert result["reasonCodes"] == ["source_key_mismatch"]
    assert "different-message" not in str(result)


def test_support_email_readback_reports_exact_closed_ticket_as_closed():
    result = execute_support_email_ticket_readback(
        _payload(),
        client=FakeSalesforce(closed=True),
    )

    assert result["status"] == "closed"
    assert result["verified"] is False
    assert result["isClosed"] is True
    assert result["reasonCodes"] == ["ticket_closed"]


def test_support_email_readback_preflight_exposes_no_generic_read_write_or_send():
    result = execute_support_email_ticket_readback({"action": "preflight"})

    assert result["accessMode"] == "typed_support_email_ticket_readback_only"
    assert result["source"] == READBACK_SOURCE
    assert result["readOnly"] is True
    assert result["arbitrarySalesforceAccess"] is False
    assert result["writesExposed"] is False
    assert result["emailSendExposed"] is False
    assert result["customerDataExposed"] is False


def test_support_email_readback_rejects_extra_fields_and_nonexact_source_key():
    with pytest.raises(SalesforceScopeError, match="Unsupported"):
        execute_support_email_ticket_readback(
            {**_payload(), "query": "SELECT Description__c FROM NovaPOS_Ticket__c"},
            client=FakeSalesforce(),
        )
    with pytest.raises(SalesforceScopeError, match="sourceKey"):
        execute_support_email_ticket_readback(
            {**_payload(), "sourceKey": "support-email:other"},
            client=FakeSalesforce(),
        )


def test_client_comparison_uses_fixed_fields_and_does_not_return_description():
    client = object.__new__(ScopedSalesforceClient)
    queries = []

    def query(soql):
        queries.append(soql)
        return {
            "records": [
                {
                    "Id": TICKET_ID,
                    "Name": "347314",
                    "Account__c": ACCOUNT_ID,
                    "Account__r": {
                        "Id": ACCOUNT_ID,
                        "Name": "Kay's Cafe",
                        "Fake_Account__c": False,
                    },
                    "RecordType": {"Name": "1. NOVA Classic"},
                    "Is_Closed__c": False,
                    "Description__c": (
                        "Secret customer narrative.\n"
                        "Source key: support-email:message-1"
                    ),
                }
            ]
        }

    client._query = query
    client._support_email_ticket_journal_matches = (
        lambda *_args, **_kwargs: True
    )
    result = client.verify_support_email_ticket_claim(
        ticket_id=TICKET_ID,
        ticket_number="347314",
        account_id=ACCOUNT_ID,
        record_type="1. NOVA Classic",
        source_key="support-email:message-1",
        allowed_record_types={"1. NOVA Classic", "2. Nova Wave"},
    )

    assert result == {
        "ticketIdMatches": True,
        "ticketNumberMatches": True,
        "accountIdMatches": True,
        "accountEligible": True,
        "recordTypeMatches": True,
        "sourceKeyMatches": True,
        "isClosed": False,
    }
    assert len(queries) == 1
    assert "WHERE Id = 'a0G000000000001AAA' LIMIT 1" in queries[0]
    assert "Account__r.Name" in queries[0]
    assert "Account__r.Fake_Account__c" in queries[0]
    assert "Description__c" not in queries[0]
    assert "Secret customer narrative" not in str(result)
    assert "Description__c" not in str(result)


def test_support_email_readback_rejects_provider_ineligible_account():
    class IneligibleSalesforce(FakeSalesforce):
        def verify_support_email_ticket_claim(self, **claim):
            comparison = super().verify_support_email_ticket_claim(**claim)
            comparison["accountEligible"] = False
            return comparison

    result = execute_support_email_ticket_readback(
        _payload(),
        client=IneligibleSalesforce(),
    )

    assert result["status"] == "mismatch"
    assert result["verified"] is False
    assert result["accountEligible"] is False
    assert result["reasonCodes"] == ["account_ineligible"]


def test_client_comparison_requires_private_source_journal_match():
    client = object.__new__(ScopedSalesforceClient)
    client._query = lambda _soql: {
        "records": [
            {
                "Id": TICKET_ID,
                "Name": "347314",
                "Account__c": ACCOUNT_ID,
                "Account__r": {
                    "Id": ACCOUNT_ID,
                    "Name": "Kay's Cafe",
                    "Fake_Account__c": False,
                },
                "RecordType": {"Name": "1. NOVA Classic"},
                "Is_Closed__c": False,
                "Description__c": (
                    "Customer narrative.\n"
                    "Source key: support-email:message-1\n"
                    "Source key: support-email:other-message"
                ),
            }
        ]
    }
    client._support_email_ticket_journal_matches = (
        lambda *_args, **_kwargs: False
    )

    result = client.verify_support_email_ticket_claim(
        ticket_id=TICKET_ID,
        ticket_number="347314",
        account_id=ACCOUNT_ID,
        record_type="1. NOVA Classic",
        source_key="support-email:message-1",
        allowed_record_types={"1. NOVA Classic", "2. Nova Wave"},
    )

    assert result["accountEligible"] is True
    assert result["sourceKeyMatches"] is False


def test_billing_closure_email_readback_verifies_ticket_and_exact_eml_digest():
    class BillingClosureSalesforce:
        def verify_billing_closure_email_ticket_claim(self, **claim):
            assert claim["source_key"] == "billing-closure-email:message-1"
            assert claim["file_name"] == "billing-close-confirmation-message-1.eml"
            assert claim["sha256"] == "a" * 64
            return {
                "ticketIdMatches": True,
                "ticketNumberMatches": True,
                "accountIdMatches": True,
                "accountEligible": True,
                "recordTypeMatches": True,
                "sourceKeyMatches": True,
                "attachmentDigestMatches": True,
                "attachmentTitleConflict": False,
                "isClosed": False,
            }

    result = execute_billing_closure_email_ticket_readback(
        {
            "action": "read_billing_closure_email_ticket",
            "ticketId": TICKET_ID,
            "ticketNumber": "347314",
            "accountId": ACCOUNT_ID,
            "recordType": "3. Billing",
            "sourceEmailId": "message-1",
            "sourceKey": "billing-closure-email:message-1",
            "fileName": "billing-close-confirmation-message-1.eml",
            "sha256": "a" * 64,
        },
        client=BillingClosureSalesforce(),
    )

    assert result["verified"] is True
    assert result["attachmentVerified"] is True
    assert result["reasonCodes"] == []
    assert "customer" not in str(result).casefold()


def test_billing_closure_email_readback_fails_closed_on_attachment_mismatch():
    class MissingAttachmentSalesforce:
        def verify_billing_closure_email_ticket_claim(self, **_claim):
            return {
                "ticketIdMatches": True,
                "ticketNumberMatches": True,
                "accountIdMatches": True,
                "accountEligible": True,
                "recordTypeMatches": True,
                "sourceKeyMatches": True,
                "attachmentDigestMatches": False,
                "attachmentTitleConflict": False,
                "isClosed": False,
            }

    result = execute_billing_closure_email_ticket_readback(
        {
            "action": "read_billing_closure_email_ticket",
            "ticketId": TICKET_ID,
            "ticketNumber": "347314",
            "accountId": ACCOUNT_ID,
            "recordType": "3. Billing",
            "sourceEmailId": "message-1",
            "sourceKey": "",
            "fileName": "billing-close-confirmation-message-1.eml",
            "sha256": "b" * 64,
        },
        client=MissingAttachmentSalesforce(),
    )

    assert result["verified"] is False
    assert result["reasonCodes"] == ["attachment_digest_mismatch"]
