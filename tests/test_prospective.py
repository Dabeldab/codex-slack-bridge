from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
import pytest

from codex_slack_bridge.prospective import ProspectiveStore, parse_due_expression


def dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def test_create_is_idempotent_and_additive_to_existing_database(tmp_path):
    path = tmp_path / "bridge.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE existing_data (value TEXT)")
        db.execute("INSERT INTO existing_data VALUES ('preserved')")

    store = ProspectiveStore(path)
    first = store.create(
        title="Resume Chargify MCP upgrade",
        due_at="2026-07-13T10:00:00-04:00",
        timezone_name="America/New_York",
        payload={"channel": "slack"},
        idempotency_key="chargify-monday",
    )
    second = store.create(
        title="different retry payload is ignored",
        due_at="2027-01-01T00:00:00Z",
        payload={},
        idempotency_key="chargify-monday",
    )

    assert first == second
    assert first["next_scheduled_at"] == "2026-07-13T14:00:00Z"
    assert first["timezone"] == "America/New_York"
    assert first["next_occurrence"]["idempotency_key"].startswith("prospective:")
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT value FROM existing_data").fetchone()[0] == "preserved"


def test_due_claim_deliver_is_restart_safe_and_idempotent(tmp_path):
    path = tmp_path / "prospective.sqlite3"
    store = ProspectiveStore(path)
    task = store.create(title="do it", due_at="2026-07-13T14:00:00Z", idempotency_key="one")

    assert store.list_due(now="2026-07-13T13:59:59Z") == []
    due = store.list_due(now="2026-07-13T14:00:00Z")
    assert [item["id"] for item in due] == [task["next_occurrence"]["id"]]

    first_claim = store.claim_due("worker-a", now="2026-07-13T14:00:00Z", lease_seconds=30)[0]
    assert store.claim_due("worker-b", now="2026-07-13T14:00:29Z") == []

    restarted = ProspectiveStore(path)
    second_claim = restarted.claim_due("worker-b", now="2026-07-13T14:00:31Z")[0]
    assert second_claim["id"] == first_claim["id"]
    assert second_claim["idempotency_key"] == first_claim["idempotency_key"]
    assert second_claim["lease_token"] != first_claim["lease_token"]
    assert second_claim["attempt_count"] == 2

    with pytest.raises(ValueError):
        restarted.deliver(second_claim["id"], first_claim["lease_token"])
    delivered = restarted.deliver(
        second_claim["id"], second_claim["lease_token"], result={"message_ts": "123"}
    )
    assert delivered["status"] == "delivered"
    assert restarted.deliver(second_claim["id"], "already-cleared")["status"] == "delivered"
    assert restarted.get(task["id"])["status"] == "completed"
    assert restarted.claim_due("worker-c", now="2026-07-14T00:00:00Z") == []


def test_atomic_claim_has_one_winner(tmp_path):
    path = tmp_path / "prospective.sqlite3"
    ProspectiveStore(path).create(title="race", due_at="2026-01-01T00:00:00Z")

    def claim(worker: str):
        return ProspectiveStore(path).claim_due(worker, now="2026-01-01T00:00:01Z")

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(claim, ["a", "b"]))
    assert sorted(len(result) for result in results) == [0, 1]


@pytest.mark.parametrize(
    ("recurrence", "due", "delivered_at", "expected"),
    [
        ("daily", "2026-03-07T09:00:00-05:00", "2026-03-07T14:00:00Z", "2026-03-08T13:00:00Z"),
        ("weekly", "2026-03-02T10:00:00-05:00", "2026-03-02T15:00:00Z", "2026-03-09T14:00:00Z"),
        ("weekdays", "2026-07-10T10:00:00-04:00", "2026-07-10T14:00:00Z", "2026-07-13T14:00:00Z"),
        ({"kind": "interval", "interval": 7200}, "2026-07-10T14:00:00Z", "2026-07-10T14:00:00Z", "2026-07-10T16:00:00Z"),
    ],
)
def test_recurrence_advances_from_scheduled_time_and_respects_local_dst(
    tmp_path, recurrence, due, delivered_at, expected
):
    store = ProspectiveStore(tmp_path / "prospective.sqlite3")
    task = store.create(
        title="recurring",
        due_at=due,
        timezone_name="America/New_York",
        recurrence=recurrence,
    )
    claim = store.claim_due("worker", now=delivered_at)[0]
    store.deliver(claim["id"], claim["lease_token"], now=delivered_at)
    updated = store.get(task["id"])
    assert updated["status"] == "active"
    assert updated["next_scheduled_at"] == expected


def test_overdue_skip_catches_up_recurring_task_without_delivery(tmp_path):
    store = ProspectiveStore(tmp_path / "prospective.sqlite3")
    task = store.create(
        title="weekday digest",
        due_at="2026-07-06T10:00:00-04:00",
        timezone_name="America/New_York",
        recurrence="weekdays",
        overdue_policy="skip",
        max_lateness_seconds=3600,
    )

    # Four old weekday occurrences are skipped; Friday's occurrence is due now.
    claimed = store.claim_due("worker", now="2026-07-10T10:00:00-04:00")
    assert len(claimed) == 1
    assert claimed[0]["scheduled_at"] == "2026-07-10T14:00:00Z"
    assert claimed[0]["attempt_count"] == 1
    with sqlite3.connect(store.path) as db:
        assert db.execute(
            "SELECT count(*) FROM prospective_occurrences WHERE task_id = ? AND status = 'skipped'",
            (task["id"],),
        ).fetchone()[0] == 4


def test_fail_can_retry_same_occurrence_or_advance_after_terminal_failure(tmp_path):
    store = ProspectiveStore(tmp_path / "prospective.sqlite3")
    task = store.create(
        title="daily",
        due_at="2026-07-10T10:00:00-04:00",
        timezone_name="America/New_York",
        recurrence="daily",
    )
    first = store.claim_due("a", now="2026-07-10T14:00:00Z")[0]
    pending = store.fail(
        first["id"],
        first["lease_token"],
        "temporary",
        retry_at="2026-07-10T14:10:00Z",
        now="2026-07-10T14:00:01Z",
    )
    assert pending["status"] == "pending"
    assert store.claim_due("b", now="2026-07-10T14:09:59Z") == []
    retry = store.claim_due("b", now="2026-07-10T14:10:00Z")[0]
    assert retry["idempotency_key"] == first["idempotency_key"]
    failed = store.fail(retry["id"], retry["lease_token"], "permanent", now="2026-07-10T14:10:01Z")
    assert failed["status"] == "failed"
    assert store.get(task["id"])["next_scheduled_at"] == "2026-07-11T14:00:00Z"


def test_cancel_and_reschedule_invalidate_active_claim(tmp_path):
    store = ProspectiveStore(tmp_path / "prospective.sqlite3")
    task = store.create(title="move me", due_at="2026-07-13T14:00:00Z")
    claimed = store.claim_due("worker", now="2026-07-13T14:00:00Z")[0]
    moved = store.reschedule(task["id"], "2026-07-14T15:00:00Z", now="2026-07-13T14:00:01Z")
    assert moved["next_scheduled_at"] == "2026-07-14T15:00:00Z"
    with pytest.raises(ValueError):
        store.deliver(claimed["id"], claimed["lease_token"])

    cancelled = store.cancel(task["id"], now="2026-07-13T14:00:02Z")
    assert cancelled["status"] == "cancelled"
    assert cancelled["next_scheduled_at"] is None
    assert store.cancel(task["id"])["status"] == "cancelled"
    assert store.list_due(now="2026-08-01T00:00:00Z") == []


def test_reschedule_to_same_time_reuses_stable_occurrence_after_cancel(tmp_path):
    store = ProspectiveStore(tmp_path / "prospective.sqlite3")
    task = store.create(title="same", due_at="2026-07-13T14:00:00Z")
    occurrence = task["next_occurrence"]
    store.cancel(task["id"])
    moved = store.reschedule(task["id"], "2026-07-13T14:00:00Z")
    assert moved["next_occurrence"]["id"] == occurrence["id"]
    assert moved["next_occurrence"]["idempotency_key"] == occurrence["idempotency_key"]
    assert moved["next_occurrence"]["status"] == "pending"


def test_rejects_naive_datetimes_invalid_timezone_and_invalid_skip_policy(tmp_path):
    store = ProspectiveStore(tmp_path / "prospective.sqlite3")
    with pytest.raises(ValueError, match="timezone-aware"):
        store.create(title="bad", due_at=datetime(2026, 1, 1))
    with pytest.raises(ValueError, match="unknown timezone"):
        store.create(title="bad", due_at=datetime.now(UTC), timezone_name="Mars/Olympus")
    with pytest.raises(ValueError, match="requires max_lateness"):
        store.create(title="bad", due_at=datetime.now(UTC), overdue_policy="skip")


def test_list_and_read_occurrence(tmp_path):
    store = ProspectiveStore(tmp_path / "prospective.sqlite3")
    task = store.create(
        title="remember",
        due_at="2026-07-13T10:00:00-04:00",
        timezone_name="America/New_York",
        payload={"agent": "direct_codex"},
    )
    assert [item["id"] for item in store.list_tasks(status="active")] == [task["id"]]
    occurrence = store.get_occurrence(task["next_occurrence"]["id"])
    assert occurrence["title"] == "remember"
    assert occurrence["payload"] == {"agent": "direct_codex"}


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("2026-07-13T10:00:00-04:00", "2026-07-13T14:00:00Z"),
        ("2026-07-13 10:00", "2026-07-13T14:00:00Z"),
        ("today at 3pm", "2026-07-10T19:00:00Z"),
        ("tomorrow 09:30", "2026-07-11T13:30:00Z"),
        ("Monday at 10am", "2026-07-13T14:00:00Z"),
        ("next Friday 2:15 PM", "2026-07-17T18:15:00Z"),
    ],
)
def test_parse_due_expression_exact_forms(expression, expected):
    parsed = parse_due_expression(expression, now="2026-07-10T12:00:00-04:00")
    assert parsed.astimezone(UTC).isoformat().replace("+00:00", "Z") == expected


@pytest.mark.parametrize("expression", ["", "Monday", "10am", "2026-07-13", "sometime next week", "7/13 10am"])
def test_parse_due_expression_rejects_ambiguous_forms(expression):
    with pytest.raises(ValueError, match="required|ambiguous"):
        parse_due_expression(expression, now="2026-07-10T12:00:00-04:00")


def test_parse_due_expression_rejects_dst_gap_and_fold():
    with pytest.raises(ValueError, match="daylight saving"):
        parse_due_expression("2026-03-08 02:30", now="2026-01-01T00:00:00Z")
    with pytest.raises(ValueError, match="daylight saving"):
        parse_due_expression("2026-11-01 01:30", now="2026-01-01T00:00:00Z")
