# AgentChat/direct_codex 2026-07-14T10:45:00-04:00: Salesforce delta ledger safety and routing tests.
# AgentChat/coding_agent 2026-07-14T17:45:00-04:00: verify disabled reconciliation backlog retirement.
from __future__ import annotations

from codex_slack_bridge.salesforce_work_ledger import (
    SalesforceWorkLedger,
    account_is_excluded,
    material_ticket_hash,
    ticket_is_terminal,
    ticket_route,
    ticket_route_for_ticket,
)


def _ticket(**updates):
    value = {
        "Id": "a001ticket",
        "Name": "347999",
        "RecordTypeName": "1. NOVA Classic",
        "Account__c": "001account",
        "SystemModstamp": "2026-07-14T14:00:00.000Z",
        "Is_Closed__c": False,
        "Description__c": "Printer does not work",
    }
    value.update(updates)
    return value


def test_routes_support_and_billing_to_expected_agents():
    assert ticket_route("1. NOVA Classic") == ("support", "tickets_agent")
    assert ticket_route("2. Nova Wave") == ("support", "tickets_agent")
    assert ticket_route("3. Billing") == ("billing", "billing_agent")
    assert ticket_route("5. Development") == ("ignored", "")


def test_closed_nova_classic_account_cancellation_routes_to_billing_until_processed(tmp_path):
    cancellation = _ticket(
        Is_Closed__c=True,
        Description__c="Customer requests cancellation of all NOVA POS service because every location closed.",
        Accounts_or_Order_Issue__c="Account",
    )

    assert ticket_route_for_ticket(cancellation) == ("billing", "billing_agent")
    assert ticket_is_terminal(cancellation) is False

    ledger = SalesforceWorkLedger(tmp_path / "salesforce.sqlite3")
    assert ledger.ingest_tickets([cancellation]) == 1
    [work] = ledger.dispatchable_tickets()
    assert work["assigned_agent"] == "billing_agent"


def test_closed_ordinary_support_ticket_remains_terminal():
    ticket = _ticket(Is_Closed__c=True, Description__c="Printer was power cycled and is working.")
    assert ticket_route_for_ticket(ticket) == ("support", "tickets_agent")
    assert ticket_is_terminal(ticket) is True


def test_account_exclusion_uses_markers_not_substrings():
    assert account_is_excluded("Demo Nova Cafe", "")
    assert account_is_excluded("Real Store", "template_account")
    assert account_is_excluded("Test Store", "real")
    assert not account_is_excluded("Contest Retail", "latest_fashion")


def test_exact_replay_deduplicates_but_new_salesforce_version_dispatches(tmp_path):
    ledger = SalesforceWorkLedger(tmp_path / "salesforce.sqlite3")
    first = _ticket()
    assert ledger.ingest_tickets([first]) == 1
    assert len(ledger.dispatchable_tickets()) == 1
    assert ledger.ingest_tickets([dict(first)]) == 0
    newer_stamp = _ticket(SystemModstamp="2026-07-14T14:05:00.000Z")
    assert material_ticket_hash(first) != material_ticket_hash(newer_stamp)
    assert ledger.ingest_tickets([newer_stamp]) == 1


def test_material_ticket_update_dispatches_one_new_version(tmp_path):
    ledger = SalesforceWorkLedger(tmp_path / "salesforce.sqlite3")
    assert ledger.ingest_tickets([_ticket()]) == 1
    row = ledger.dispatchable_tickets()[0]
    ledger.mark_assigned("ticket", row["ticket_id"], "job-one")
    ledger.finish_job("job-one", handled=True)
    assert ledger.dispatchable_tickets() == []
    assert ledger.ingest_tickets([_ticket(Description__c="Printer and scanner fail")]) == 1
    assert len(ledger.dispatchable_tickets()) == 1


def test_closed_ticket_is_not_dispatched(tmp_path):
    ledger = SalesforceWorkLedger(tmp_path / "salesforce.sqlite3")
    assert ledger.ingest_tickets([_ticket(Is_Closed__c=True)]) == 1
    assert ledger.dispatchable_tickets() == []


def test_billing_account_exclusions_and_version_idempotency(tmp_path):
    ledger = SalesforceWorkLedger(tmp_path / "salesforce.sqlite3")
    rows = [
        {
            "accountId": "001real",
            "name": "Real Retail",
            "triggerKind": "location+order",
            "locationModstamp": "2026-07-14T14:00:00Z",
            "orderModstamp": "2026-07-14T14:00:01Z",
        },
        {
            "accountId": "001demo",
            "name": "Demo Store",
            "triggerKind": "location",
            "locationModstamp": "2026-07-14T14:00:00Z",
        },
    ]
    assert ledger.ingest_billing_accounts(rows) == 2
    assert [row["account_id"] for row in ledger.dispatchable_billing()] == ["001real"]
    assert ledger.ingest_billing_accounts(rows) == 0
    ledger.mark_assigned("billing", "001real", "billing-job")
    ledger.finish_job("billing-job", handled=True)
    assert ledger.dispatchable_billing() == []


def test_failed_job_returns_work_to_dispatch_queue(tmp_path):
    ledger = SalesforceWorkLedger(tmp_path / "salesforce.sqlite3")
    ledger.ingest_tickets([_ticket()])
    ledger.mark_assigned("ticket", "a001ticket", "job-failed")
    ledger.finish_job("job-failed", handled=False)
    assert len(ledger.dispatchable_tickets()) == 1


def test_ticket_projection_detects_context_change_without_storing_body(tmp_path):
    ledger = SalesforceWorkLedger(tmp_path / "salesforce.sqlite3")
    projected = {
        "id": "a001ticket",
        "number": "347999",
        "recordType": "1. NOVA Classic",
        "updatedAt": "2026-07-14T14:00:00Z",
        "notesFull": "customer-private diagnostic detail",
        "chatterItems": [{"id": "feed-one", "body": "internal note"}],
        "sessionHistoryItems": [],
        "isClosed": False,
    }
    assert ledger.ingest_ticket_projection([projected]) == 1
    item = ledger.dispatchable_tickets()[0]
    ledger.mark_assigned("ticket", item["ticket_id"], "context-job")
    ledger.finish_job("context-job", handled=True)
    assert ledger.ingest_ticket_projection([projected]) == 0
    changed = dict(projected, chatterItems=[{"id": "feed-two", "body": "new note"}])
    assert ledger.ingest_ticket_projection([changed]) == 1
    assert len(ledger.dispatchable_tickets()) == 1
    raw_db = (tmp_path / "salesforce.sqlite3").read_bytes()
    assert b"customer-private diagnostic detail" not in raw_db
    assert b"internal note" not in raw_db


def test_one_billing_job_can_complete_a_bounded_account_batch(tmp_path):
    ledger = SalesforceWorkLedger(tmp_path / "salesforce.sqlite3")
    rows = [
        {"accountId": f"001{index}", "triggerKind": "location", "locationModstamp": str(index)}
        for index in range(3)
    ]
    ledger.ingest_billing_accounts(rows)
    for row in ledger.dispatchable_billing():
        ledger.mark_assigned("billing", row["account_id"], "batch-job")
    ledger.finish_job("batch-job", handled=True)
    assert ledger.dispatchable_billing() == []


def test_command_center_job_key_is_not_secret_scrubbed(tmp_path):
    ledger = SalesforceWorkLedger(tmp_path / "salesforce.sqlite3")
    ledger.ingest_billing_accounts(
        [{"accountId": "001real", "triggerKind": "location", "locationModstamp": "one"}]
    )
    job_id = "cc-20260714T141835Z-5aa95f1e7a"
    ledger.mark_assigned("billing", "001real", job_id)
    ledger.finish_job(job_id, handled=True)
    assert ledger.dispatchable_billing() == []
    assert ledger.status()["billingStates"] == {"complete": 1}


def test_blocked_billing_version_is_handled_without_immediate_redispatch(tmp_path):
    ledger = SalesforceWorkLedger(tmp_path / "salesforce.sqlite3")
    ledger.ingest_billing_accounts(
        [{"accountId": "001real", "triggerKind": "location", "locationModstamp": "one"}]
    )
    ledger.mark_assigned("billing", "001real", "cc-blocked-job")
    ledger.finish_job("cc-blocked-job", handled=True, needs_review=True)
    assert ledger.dispatchable_billing() == []
    assert ledger.status()["billingStates"] == {"action_pending": 1}


def test_retire_billing_work_terminalizes_pending_and_assigned_versions(tmp_path):
    ledger = SalesforceWorkLedger(tmp_path / "salesforce.sqlite3")
    ledger.ingest_billing_accounts(
        [
            {"accountId": "001queued", "triggerKind": "location", "locationModstamp": "one"},
            {"accountId": "001assigned", "triggerKind": "order", "orderModstamp": "two"},
        ]
    )
    ledger.mark_assigned("billing", "001assigned", "cc-assigned")

    assert ledger.retire_billing_work() == 2
    assert ledger.dispatchable_billing() == []
    assert ledger.status()["billingStates"] == {"complete": 2}


def test_repair_redacted_assignment_returns_current_version_to_queue(tmp_path):
    ledger = SalesforceWorkLedger(tmp_path / "salesforce.sqlite3")
    ledger.ingest_billing_accounts(
        [{"accountId": "001real", "triggerKind": "location", "locationModstamp": "one"}]
    )
    with ledger._connect() as connection:
        connection.execute(
            "UPDATE sf_billing_work SET state='investigating', assigned_job_id='[redacted]'"
        )
    assert ledger.repair_redacted_assignments() == {"ticket": 0, "billing": 1}
    assert [row["account_id"] for row in ledger.dispatchable_billing()] == ["001real"]
