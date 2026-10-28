from __future__ import annotations

import json
import re

import pytest

from scoped_operations_mcp.salesforce_client import (
    SUPPORT_QUALITY_TICKET_FIELDS,
    SUPPORT_QUALITY_TICKET_RECORD_TYPES,
    SalesforceScopeError,
    ScopedSalesforceClient,
)
from scoped_operations_mcp.salesforce_support_quality_projection_cli import (
    ACTION,
    FIXED_ROSTER_PAYLOAD,
    SOURCE,
    execute_support_quality_ticket_projection,
)


START = "2026-07-20T04:00:00Z"
END = "2026-07-27T04:00:00Z"
TICKET_ONE = "a0G000000000001AAA"
TICKET_TWO = "a0G000000000002AAA"
TICKET_THREE = "a0G000000000003AAA"


def _payload() -> dict:
    return {
        "action": ACTION,
        "startUtc": START,
        "endUtc": END,
        "roster": [dict(item) for item in FIXED_ROSTER_PAYLOAD],
    }


def _records() -> list[dict]:
    return [
        {
            "Id": TICKET_ONE,
            "Name": "347999",
            "Account__c": "001000000000001AAA",
            "RecordType": {"Name": "1. NOVA Classic"},
            "CreatedDate": "2026-07-21T14:00:00Z",
            "Is_Closed__c": True,
            "Ticket_Closed_Date__c": "2026-07-22",
            "Ticket_Created_by__c": "Darius Parlor",
            "Ticket_Closed_by_Rep__c": "Oscar Ocampo",
            "Owner": {"Name": "Not A Roster Member", "Email": "owner@example.com"},
            "CreatedBy": {"Name": "Eddie Talal"},
            "Description__c": (
                "Customer Jane Doe called from 212-555-0123. "
                "https://customer.example/private"
            ),
            "Tech_Main_Issue__c": "Jane Doe",
            "Technical_Issue__c": "Gateway Setup",
            "NOVA_Wave_Issue__c": "",
            "NOVA_Wave_Technical_Issue__c": "",
        },
        {
            "Id": TICKET_TWO,
            "Name": "348000",
            "Account__r": {"Name": "Private Customer LLC"},
            "Contact__r": {"Email": "customer@example.com"},
            "RecordType": {"Name": "2. Nova Wave"},
            "CreatedDate": "2026-07-23T10:00:00+00:00",
            "Is_Closed__c": False,
            "Ticket_Closed_Date__c": "",
            "Ticket_Created_by__c": "",
            "Ticket_Closed_by_Rep__c": "",
            "Owner": {"Name": "Mordi"},
            "CreatedBy": {"Name": "Unmapped User"},
            "Description__c": "",
            "Tech_Main_Issue__c": "",
            "Technical_Issue__c": "",
            "NOVA_Wave_Issue__c": "Register",
            "NOVA_Wave_Technical_Issue__c": "password=do-not-return",
        },
        {
            "Id": TICKET_THREE,
            "Name": "348001",
            "RecordType": {"Name": "1. NOVA Classic"},
            "CreatedDate": "2026-07-24T11:00:00Z",
            "Is_Closed__c": False,
            "Ticket_Created_by__c": "Someone Outside The Fixed Roster",
            "Ticket_Closed_by_Rep__c": "",
            "Owner": {"Name": "Another User"},
            "CreatedBy": {"Name": "Another User"},
            "Description__c": "Raw internal notes must never escape.",
            "Tech_Main_Issue__c": "Software",
        },
    ]


class FakeSalesforce:
    def __init__(self, records: list[dict] | None = None):
        self.records = list(records if records is not None else _records())
        self.calls: list[dict] = []
        self.write_calls: list[dict] = []

    def support_quality_ticket_projection_rows(self, **window):
        self.calls.append(window)
        return {
            "startUtc": window["start_utc"],
            "endUtc": window["end_utc"],
            "records": list(self.records),
            "rowCeiling": 2000,
            "rowLimitReached": False,
            "readOnly": True,
            "writesPerformed": False,
        }


def test_preflight_exposes_only_fixed_read_only_projection_contract():
    result = execute_support_quality_ticket_projection({"action": "preflight"})

    assert result == {
        "ok": True,
        "action": "preflight",
        "accessMode": "typed_support_quality_ticket_projection_only",
        "source": SOURCE,
        "allowedRecordTypes": list(SUPPORT_QUALITY_TICKET_RECORD_TYPES),
        "fixedRosterCount": 6,
        "maxWindowDays": 8,
        "readOnly": True,
        "writesPerformed": False,
        "writesExposed": False,
        "genericQueryExposed": False,
        "ticketContentExposed": False,
        "customerDataExposed": False,
    }


def test_projection_is_fixed_roster_sanitized_and_per_rep():
    client = FakeSalesforce()

    result = execute_support_quality_ticket_projection(_payload(), client=client)

    assert client.calls == [{"start_utc": START, "end_utc": END}]
    assert client.write_calls == []
    assert result["readOnly"] is True
    assert result["writesPerformed"] is False
    assert result["window"] == {"startUtc": START, "endUtc": END}
    assert result["recordTypes"] == ["1. NOVA Classic", "2. Nova Wave"]
    assert result["coverage"] == {
        "ticketCount": 3,
        "mappedTicketCount": 2,
        "unmappedTicketCount": 1,
        "discardedSourceRowCount": 0,
        "representativesCoveredCount": 4,
        "rowLimitReached": False,
    }

    by_id = {item["id"]: item for item in result["representatives"]}
    darius = by_id["sD6yCgsRRniBcQVeyzuxwQ"]
    assert darius["ticketCount"] == 1
    assert darius["closedCount"] == 1
    assert darius["closureMetadataPresentCount"] == 1
    assert darius["documentationPresentCount"] == 1
    assert darius["categoryPresentCount"] == 1
    assert darius["attributionCounts"]["ticketCreatedBy"] == 1
    assert darius["issueCategories"] == [
        "classicMain:present",
        "classicTechnical:present",
    ]
    assert darius["evidenceReferences"][0].startswith("ticket:")

    mordi = by_id["fjeUhJqaQROv4cHXUvdoqw"]
    assert mordi["ticketCount"] == 1
    assert mordi["openCount"] == 1
    assert mordi["missingDocumentationCount"] == 1
    assert mordi["attributionCounts"]["owner"] == 1
    assert mordi["issueCategories"] == [
        "waveMain:present",
        "waveTechnical:present",
    ]

    rendered = json.dumps(result, sort_keys=True)
    for forbidden in (
        TICKET_ONE,
        TICKET_TWO,
        TICKET_THREE,
        "347999",
        "348000",
        "348001",
        "001000000000001AAA",
        "Private Customer LLC",
        "Jane Doe",
        "212-555-0123",
        "customer@example.com",
        "owner@example.com",
        "https://customer.example/private",
        "Raw internal notes",
        "password=do-not-return",
        "Gateway Setup",
        "Register",
    ):
        assert forbidden not in rendered


def test_ticket_evidence_references_are_deterministic_and_opaque():
    forward = execute_support_quality_ticket_projection(
        _payload(),
        client=FakeSalesforce(_records()),
    )
    reverse = execute_support_quality_ticket_projection(
        _payload(),
        client=FakeSalesforce(list(reversed(_records()))),
    )

    forward_references = {
        item["id"]: item["evidenceReferences"]
        for item in forward["representatives"]
    }
    reverse_references = {
        item["id"]: item["evidenceReferences"]
        for item in reverse["representatives"]
    }
    assert forward_references == reverse_references
    all_references = {
        reference
        for values in forward_references.values()
        for reference in values
    }
    assert all(
        re.fullmatch(r"ticket:[0-9a-f]{24}", reference)
        for reference in all_references
    )
    assert not any(ticket_id in str(all_references) for ticket_id in (TICKET_ONE, TICKET_TWO))


@pytest.mark.parametrize(
    "change,match",
    [
        ({"endUtc": "2026-07-29T04:00:01Z"}, "8 days"),
        ({"startUtc": "2026-07-20T00:00:00-04:00"}, "UTC"),
        ({"query": "SELECT Id FROM Account"}, "fixed fields"),
    ],
)
def test_projection_rejects_non_server_window_and_arbitrary_fields(change, match):
    payload = _payload()
    payload.update(change)

    with pytest.raises(SalesforceScopeError, match=match):
        execute_support_quality_ticket_projection(payload, client=FakeSalesforce())


def test_projection_rejects_any_roster_change_before_salesforce_read():
    client = FakeSalesforce()
    payload = _payload()
    payload["roster"][0]["name"] = "Different Person"

    with pytest.raises(SalesforceScopeError, match="fixed server roster"):
        execute_support_quality_ticket_projection(payload, client=client)

    assert client.calls == []
    assert client.write_calls == []


def test_client_uses_only_fixed_fields_window_and_support_record_types():
    client = object.__new__(ScopedSalesforceClient)
    queries: list[str] = []

    def query(soql):
        queries.append(soql)
        return {"records": _records()}

    client._query = query
    result = client.support_quality_ticket_projection_rows(
        start_utc=START,
        end_utc=END,
    )

    assert len(queries) == 1
    query_text = queries[0]
    assert query_text.startswith(f"SELECT {SUPPORT_QUALITY_TICKET_FIELDS} ")
    assert "FROM NovaPOS_Ticket__c" in query_text
    assert f"CreatedDate >= {START}" in query_text
    assert f"CreatedDate < {END}" in query_text
    assert "RecordType.Name IN ('1. NOVA Classic','2. Nova Wave')" in query_text
    assert "ORDER BY CreatedDate ASC, Id ASC LIMIT 2000" in query_text
    for forbidden in (
        "Account__c",
        "Contact__c",
        "Account__r",
        "Contact__r",
        "Email",
        "Phone",
        "Name,Account",
        "Billing_Notes_Internal__c",
    ):
        assert forbidden not in query_text
    assert result["readOnly"] is True
    assert result["writesPerformed"] is False
    assert result["records"] == _records()


def test_client_rejects_non_utc_or_oversized_window_before_query():
    client = object.__new__(ScopedSalesforceClient)
    queries: list[str] = []
    client._query = queries.append

    with pytest.raises(SalesforceScopeError, match="must be UTC"):
        client.support_quality_ticket_projection_rows(
            start_utc="2026-07-20T00:00:00-04:00",
            end_utc=END,
        )
    with pytest.raises(SalesforceScopeError, match="8 days"):
        client.support_quality_ticket_projection_rows(
            start_utc=START,
            end_utc="2026-07-28T04:00:01Z",
        )

    assert queries == []
