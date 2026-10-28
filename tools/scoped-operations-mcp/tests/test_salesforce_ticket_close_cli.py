from __future__ import annotations

import pytest

from scoped_operations_mcp.salesforce_client import SalesforceScopeError
from scoped_operations_mcp.salesforce_ticket_close_cli import execute_ticket_close


class FakeSalesforce:
    def __init__(self):
        self.calls = []

    def lookup(self, kind, value, *, limit=10):
        self.calls.append(("lookup", kind, value, limit))
        return {"records": [{"Id": "a0G000000000001AAA", "Name": value}]}

    def resolve_ticket(self, ticket_id, note, *, allowed_record_types):
        self.calls.append(("resolve", ticket_id, note, frozenset(allowed_record_types)))
        return {
            "ok": True,
            "updated": True,
            "duplicate": False,
            "closed": True,
            "resolutionPresent": True,
            "readback": {"Ticket_Closed_Date__c": "2026-07-22T23:00:00.000+0000"},
        }


def test_deterministic_close_resolves_exact_ticket_and_returns_bounded_readback():
    client = FakeSalesforce()

    result = execute_ticket_close(
        {
            "action": "close_ticket",
            "ticketNumber": "347314",
            "resolutionNote": "Closed at the operator's request.",
            "idempotencyKey": "salesforce-ticket-close:347314:test",
        },
        client=client,
    )

    assert result == {
        "ok": True,
        "action": "close_ticket",
        "ticketNumber": "347314",
        "ticketId": "a0G000000000001AAA",
        "idempotencyKey": "salesforce-ticket-close:347314:test",
        "updated": True,
        "duplicate": False,
        "closed": True,
        "resolutionPresent": True,
        "resolutionSurface": "Chatter",
        "ticketClosedDate": "2026-07-22T23:00:00.000+0000",
        "emailSent": False,
    }
    assert client.calls[0] == ("lookup", "ticket", "347314", 3)
    assert client.calls[1][0:3] == (
        "resolve",
        "a0G000000000001AAA",
        "Closed at the operator's request.",
    )
    assert client.calls[1][3] == frozenset({"1. NOVA Classic", "2. Nova Wave"})


def test_deterministic_close_rejects_ambiguous_ticket_number_before_write():
    client = FakeSalesforce()
    client.lookup = lambda *_args, **_kwargs: {"records": []}

    with pytest.raises(SalesforceScopeError, match="exactly one"):
        execute_ticket_close(
            {
                "ticketNumber": "347314",
                "resolutionNote": "Closed.",
                "idempotencyKey": "salesforce-ticket-close:347314:test",
            },
            client=client,
        )


def test_deterministic_close_preflight_exposes_no_send_or_generic_access():
    result = execute_ticket_close({"action": "preflight"})

    assert result["accessMode"] == "typed_ticket_close_only"
    assert result["arbitrarySalesforceAccess"] is False
    assert result["emailSendExposed"] is False
