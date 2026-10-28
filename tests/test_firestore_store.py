"""Tests for the durable Firestore-backed store and /usage/history path.

The real ``google-cloud-firestore`` client is not required to run these tests.
They exercise:
  * the pure serialization/budget/enabled logic in ``FirestoreStore``
  * the ``usage_history()`` runtime fallback to the live summary when
    Firestore is not enabled (so the endpoint never breaks without it)
  * the deterministic ticket-packet mapping used by the no-LLM board refresh

No network calls are made; no Firestore emulator is required.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from codex_slack_bridge.command_center_server import CommandCenterRuntime
from codex_slack_bridge.firestore_store import (
    DEFAULT_MAX_WRITES_PER_REFRESH,
    FirestoreStore,
)

USAGE = {
    "input_tokens": 2000,
    "cached_input_tokens": 500,
    "output_tokens": 1000,
    "reasoning_output_tokens": 80,
    "total_tokens": 3000,
    "estimated_cost_usd": 0.006,
}


# -- FirestoreStore pure logic -------------------------------------------


def test_coerce_doc_strips_bytes_and_serializes() -> None:
    store = FirestoreStore(enabled=False)
    out = store._coerce_doc(
        {
            "plain": "text",
            "count": 3,
            "flag": True,
            "blob": b"\x00\x01",
            "nested": {"inner": 1, "bytes": b"\xff"},
            "items": [{"a": 1}, b"\x00", None],
            "unknown": object(),
        }
    )
    assert out["plain"] == "text"
    assert out["count"] == 3
    assert out["flag"] is True
    assert "blob" not in out
    assert out["nested"] == {"inner": 1}
    assert out["items"] == [{"a": 1}, None]  # None preserved; bytes stripped
    assert isinstance(out["unknown"], str)  # non-serializable coerced to str


def test_coerce_doc_preserves_scalars() -> None:
    store = FirestoreStore(enabled=False)
    out = store._coerce_doc({"a": None, "b": 0, "c": "", "d": False})
    assert out["a"] is None
    assert out["b"] == 0
    assert out["c"] == ""
    assert out["d"] is False


def test_write_budget_respects_free_tier_cap() -> None:
    store = FirestoreStore(enabled=False, max_writes_per_refresh=100)
    assert store._write_budget(0) is False
    assert store._write_budget(1) is True
    assert store._write_budget(99) is True
    assert store._write_budget(100) is True
    assert store._write_budget(101) is False
    assert store._write_budget(-5) is False


def test_write_budget_default_is_1000() -> None:
    assert DEFAULT_MAX_WRITES_PER_REFRESH == 1000


def test_disabled_store_returns_safe_noops() -> None:
    store = FirestoreStore(enabled=False)
    assert store.available is False
    assert store.upsert_tickets([{"id": "1"}])["ok"] is False
    assert store.upsert_job_usage(1, dict(USAGE)) is False
    assert store.list_tickets() == []
    assert store.list_usage_history() == []
    assert store.delete_tickets_missing({"1"})["ok"] is False
    totals = store.usage_totals()
    assert totals["ok"] is True
    assert totals["perAgent"] == {}
    assert totals["total"]["total_tokens"] == 0.0


def test_ticket_reconciliation_supports_record_id_documents_and_legacy_closed_flag() -> None:
    updates: dict[str, dict] = {}

    class _Reference:
        def __init__(self, doc_id):
            self.doc_id = doc_id

        def update(self, value):
            updates[self.doc_id] = value

    class _Document:
        def __init__(self, doc_id, data):
            self.id = doc_id
            self._data = data
            self.reference = _Reference(doc_id)

        def to_dict(self):
            return self._data

    docs = [
        _Document("a0A-record-open", {"number": "348001", "isClosed": False}),
        _Document("a0A-record-stale", {"number": "347999", "isClosed": False}),
        _Document("a0A-record-closed", {"number": "347998", "isClosed": True}),
    ]

    class _Collection:
        def stream(self):
            return iter(docs)

    store = FirestoreStore(enabled=False)
    store._enabled = True
    store._client = object()
    store._collection = lambda _name: _Collection()

    result = store.delete_tickets_missing({"348001"})

    assert result == {"ok": True, "closed": 1}
    assert set(updates) == {"a0A-record-stale"}
    assert updates["a0A-record-stale"]["is_closed"] is True
    assert updates["a0A-record-stale"]["isClosed"] is True


def test_usage_totals_aggregates_rows() -> None:
    # usage_totals only depends on list_usage_history and available; exercise
    # it against a minimal fake that exposes just those two attributes.
    import types

    class _FakeStore:
        available = True

        def list_usage_history(self, *, agent_name="", limit=2000, since_iso=""):
            return [
                {"agentName": "coding_agent", **USAGE},
                {"agentName": "billing_agent", "total_tokens": 500, "estimated_cost_usd": 0.001},
            ]

    fake = _FakeStore()
    totals = types.MethodType(FirestoreStore.usage_totals, fake)(agent_name="", since_iso="", limit=2000)
    assert totals["ok"] is True
    assert totals["perAgent"]["coding_agent"]["total_tokens"] == 3000
    assert totals["perAgent"]["billing_agent"]["total_tokens"] == 500
    assert totals["total"]["total_tokens"] == 3500


def test_manual_ticket_refresh_uses_deterministic_path() -> None:
    runtime = object.__new__(CommandCenterRuntime)
    runtime.refresh_ticket_board_deterministic = lambda: {
        "ok": True,
        "status": "ok",
        "total": 8,
        "deterministic": True,
    }

    result = runtime.submit_ticket_refresh()

    assert result["accepted"] is True
    assert result["completed"] is True
    assert result["deterministic"] is True
    assert result["total"] == 8


def test_ticket_recon_skips_unchanged_claims_and_reaches_next_ticket(tmp_path) -> None:
    runtime = object.__new__(CommandCenterRuntime)
    runtime.config = SimpleNamespace(
        defaults={
            "ops_ticket_recon_enabled": True,
            "ops_ticket_recon_max_per_run": 1,
            "ops_ticket_recon_job_timeout_seconds": 60,
            "ops_ticket_recon_retry_seconds": 7200,
        },
        agents={"tickets_agent": {}},
    )
    runtime.tickets_path = tmp_path / "ops_tickets.json"
    runtime.tickets_path.write_text(
        json.dumps(
            {
                "columns": [
                    {
                        "key": "support",
                        "tickets": [
                            {"id": "old", "number": "100", "lane": "support", "updatedAt": "1"},
                            {"id": "new", "number": "101", "lane": "support", "updatedAt": "2"},
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    class _Store:
        available = True

        def __init__(self):
            self.claimed = []
            self.completed = []

        def claim_ticket_recon(self, ticket_id, **kwargs):
            self.claimed.append(ticket_id)
            return ticket_id == "new"

        def complete_ticket_recon(self, ticket_id, **kwargs):
            self.completed.append((ticket_id, kwargs["state"]))
            return True

    store = _Store()
    runtime.firestore_store = store
    runtime.submit_prompt = lambda **kwargs: {"accepted": True, "job_id": "job-101"}
    runtime.job = lambda _job_id: {"status": "completed", "result": "solution plan"}

    result = runtime.run_ticket_recon_batch()

    assert store.claimed == ["old", "new"]
    assert result["considered"] == 2
    assert result["claimed"] == 1
    assert result["completed"] == 1
    assert store.completed[-1] == ("new", "completed")


# -- usage_history() runtime fallback -------------------------------------


def _runtime_stub(jobs):
    stub = object.__new__(CommandCenterRuntime)
    stub.jobs = lambda **kw: {"ok": True, "jobs": jobs, "count": len(jobs)}
    # Firestore disabled -> usage_history must fall back to the live summary.
    stub.firestore_store = FirestoreStore(enabled=False)
    return stub


def test_usage_history_falls_back_to_live_when_firestore_disabled() -> None:
    stub = _runtime_stub(
        [
            {"id": "1", "bridgeJobId": 1000, "agentName": "coding_agent", "status": "done", "usage": dict(USAGE)},
            {"id": "2", "bridgeJobId": 1001, "agentName": "billing_agent", "status": "done", "usage": dict(USAGE)},
        ]
    )
    result = stub.usage_history(limit=500)
    assert result["ok"] is True
    assert result["source"] == "live"
    assert result["durable"] is False
    assert result["count"] == 2
    assert result["total"]["total_tokens"] == 6000


def test_usage_history_respects_agent_filter() -> None:
    stub = _runtime_stub(
        [
            {"id": "1", "bridgeJobId": 1000, "agentName": "coding_agent", "status": "done", "usage": dict(USAGE)},
            {"id": "2", "bridgeJobId": 1001, "agentName": "billing_agent", "status": "done", "usage": dict(USAGE)},
        ]
    )
    result = stub.usage_history(limit=500, agent_name="billing_agent")
    assert result["count"] == 1
    assert set(result["perAgent"]) == {"billing_agent"}


def test_usage_history_empty_when_no_usage() -> None:
    stub = _runtime_stub([{"id": "1", "bridgeJobId": 1000, "agentName": "coding_agent"}])
    result = stub.usage_history(limit=500)
    assert result["ok"] is True
    assert result["count"] == 0
    assert result["total"]["total_tokens"] == 0.0


def test_command_center_persists_usage_with_agent_attribution() -> None:
    source = (
        Path(__file__).parents[1]
        / "src"
        / "codex_slack_bridge"
        / "command_center_server.py"
    ).read_text(encoding="utf-8")
    assert '_usage = {**_usage, "agentName": agent_name}' in source


# -- deterministic ticket-packet mapping ----------------------------------


def test_build_ticket_packet_maps_fields() -> None:
    stub = object.__new__(CommandCenterRuntime)
    stub.firestore_store = FirestoreStore(enabled=False)

    class _Client:
        def read_ticket_feed(self, ticket_id, limit=8):
            raise RuntimeError("unavailable")  # must be swallowed

    record = {
        "Id": "001xx",
        "Name": "NVA-1001",
        "CreatedDate": "2026-10-01T00:00:00Z",
        "Status__c": "Open",
        "Tech_Main_Issue__c": "Hardware",
        "Technical_Issue__c": "Printer offline",
        "Description__c": "Printer stopped responding after restart.",
        "RecordType": {"Name": "Nova Wave Support"},
        "Account__c": "001-account",
        "Account__r": {"Name": "Acme Corp"},
        "CreatedBy": {"Name": "Support Desk"},
        "Owner": {"Name": "Alex"},
        "Rescue_Session_ID__c": "123456789",
    }
    packet = stub._build_ticket_packet(
        record,
        _Client(),
        ticket_id="001xx",
        lane="support",
        rescue_session={
            "sessionId": "123456789",
            "status": "Closed",
            "technician": "Taylor",
            "location": "Front register",
        },
    )
    assert packet["id"] == "001xx"
    assert packet["number"] == "NVA-1001"
    assert packet["account"] == "Acme Corp"
    assert packet["accountId"] == "001-account"
    assert packet["daysActive"] >= 0
    assert packet["openedBy"] == "Support Desk"
    assert packet["owner"] == "Alex"
    assert packet["mainIssue"] == "Hardware"
    assert packet["technicalIssue"] == "Printer offline"
    assert packet["notesFull"] == "Printer stopped responding after restart."
    assert packet["logmeinSessionId"] == "123456789"
    assert packet["sessionHistorySummary"] == "Closed · Taylor · Front register"
    assert packet["sessionHistoryItems"][0]["sessionId"] == "123456789"
    assert packet["status"] == "Open"
    assert packet["lane"] == "support"
    assert packet["url"] == "https://nova.my.salesforce.com/001xx"
    assert packet["last_seen_at"]
    # The feed failure was swallowed -> no chatter keys added.
    assert "chatterItems" not in packet


def test_ticket_packet_is_json_serializable() -> None:
    stub = object.__new__(CommandCenterRuntime)
    stub.firestore_store = FirestoreStore(enabled=False)

    class _Client:
        def read_ticket_feed(self, ticket_id, limit=8):
            return {"items": [{"id": ticket_id, "text": "hello", "x": b"bytes"}]}

    record = {"Id": "001yy", "Name": "NVA-1002"}
    packet = stub._build_ticket_packet(record, _Client(), ticket_id="001yy", lane="billing")
    json.dumps(packet)  # must not raise (bytes already coerced to str by feed mapping)
    assert packet["chatterSummary"] == "1 recent comment(s)"
