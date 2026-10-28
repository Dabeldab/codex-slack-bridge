# AgentChat/direct_codex 2026-08-04T16:08:29Z

from __future__ import annotations

from datetime import datetime, timezone

from codex_slack_bridge import support_shift_reminders
from codex_slack_bridge.support_shift_reminders import (
    build_message,
    parse_schedule,
    run_reminders,
)


def _schedule() -> list[list[str]]:
    return [
        [],
        ["", "Monday, August 3", "", "", "Tuesday, August 4"],
        ["Eddie", "", "", "", "", "10:00", "18:00"],
        ["OscarO", "", "20:00", "1:00", "x", "", ""],
        ["Mordi", "", "7:00", "15:00", "", "7:00", "15:00"],
        ["Eduardo", "", "12:00", "20:00", "", "17:00", "1:00"],
        ["Darius", "", "9:00", "18:00", "", "9:00", "18:00"],
    ]


def test_parse_schedule_excludes_darius_and_handles_overnight():
    shifts = parse_schedule(_schedule(), tab="Aug26")

    assert {shift.rep.schedule_name for shift in shifts} == {"Eddie", "OscarO", "Mordi", "Eduardo"}
    overnight = next(shift for shift in shifts if shift.rep.schedule_name == "OscarO")
    assert overnight.start.isoformat() == "2026-08-03T20:00:00-04:00"
    assert overnight.end.isoformat() == "2026-08-04T01:00:00-04:00"


def test_parse_schedule_keeps_weekly_blocks_with_their_own_dates():
    values = _schedule() + [
        [],
        ["", "Monday, August 10"],
        ["Eddie", "", "11:00", "19:00"],
    ]

    shifts = [shift for shift in parse_schedule(values, tab="Aug26") if shift.rep.schedule_name == "Eddie"]

    assert [shift.start.isoformat() for shift in shifts] == [
        "2026-08-04T10:00:00-04:00",
        "2026-08-10T11:00:00-04:00",
    ]


def test_run_sends_one_combined_message_and_persists_all_shift_keys(tmp_path):
    sent: list[str] = []

    result = run_reminders(
        now=datetime(2026, 8, 4, 15, 30, tzinfo=timezone.utc),
        state_path=tmp_path / "state.jsonl",
        cache_path=tmp_path / "cache.json",
        sheet_reader=lambda _tab: _schedule(),
        history_reader=lambda _channel, _start, _end: [],
        sender=lambda message: sent.append(message) or {"ok": True, "messageId": "message-1"},
    )

    assert result["status"] == "sent"
    assert result["reviewReminderCount"] == 2
    assert result["eduardoTicketReminderCount"] == 0
    assert len(sent) == 1
    assert "Eddie" in sent[0]
    assert "Mordi" in sent[0]

    duplicate = run_reminders(
        now=datetime(2026, 8, 4, 15, 45, tzinfo=timezone.utc),
        state_path=tmp_path / "state.jsonl",
        cache_path=tmp_path / "cache.json",
        sheet_reader=lambda _tab: _schedule(),
        history_reader=lambda _channel, _start, _end: [],
        sender=lambda message: sent.append(message) or {"ok": True, "messageId": "message-2"},
    )
    assert duplicate["status"] == "no_reminder_needed"
    assert len(sent) == 1


def test_review_activity_suppresses_rep_but_eduardo_ticket_reminder_remains(tmp_path):
    sent: list[str] = []
    activity = [
        {
            "sender": "eduardo@novapointofsale.com",
            "date_time": "2026-08-04T22:15:00Z",
            "message": "review sent",
        }
    ]

    result = run_reminders(
        now=datetime(2026, 8, 4, 22, 30, tzinfo=timezone.utc),
        state_path=tmp_path / "state.jsonl",
        cache_path=tmp_path / "cache.json",
        sheet_reader=lambda _tab: _schedule(),
        history_reader=lambda _channel, _start, _end: activity,
        sender=lambda message: sent.append(message) or {"ok": True, "messageId": "message-3"},
    )

    assert result["reviewReminderCount"] == 0
    assert result["eduardoTicketReminderCount"] == 1
    assert "Eduardo, please look over the open tickets" in sent[0]
    assert "Eduardo, please make sure" not in sent[0]


def test_dry_run_never_sends(tmp_path):
    called = False

    def sender(_message: str):
        nonlocal called
        called = True
        return {"ok": True, "messageId": "should-not-send"}

    result = run_reminders(
        now=datetime(2026, 8, 4, 15, 30, tzinfo=timezone.utc),
        state_path=tmp_path / "state.jsonl",
        cache_path=tmp_path / "cache.json",
        dry_run=True,
        sheet_reader=lambda _tab: _schedule(),
        history_reader=lambda _channel, _start, _end: [],
        sender=sender,
    )

    assert result["status"] == "dry_run_due"
    assert called is False


def test_message_is_concise():
    message = build_message(names=["Mordi"], remind_eduardo=True)
    assert message == (
        "Hey team, Mordi, please make sure you're sending customer review requests this shift. "
        "Eduardo, please look over the open tickets while you're on."
    )


def test_zoom_recovery_readback_is_limited_to_current_shift(monkeypatch):
    history_calls: list[datetime] = []

    monkeypatch.setattr(support_shift_reminders, "get_zoom_token", lambda: "redacted")

    def history(_channel_id: str, start: datetime, _end: datetime):
        history_calls.append(start)
        return [
            {
                "id": "prior-shift",
                "message": "same reminder",
                "date_time": "2026-08-04T13:00:00Z",
            }
        ]

    monkeypatch.setattr(support_shift_reminders, "_read_zoom_history", history)
    monkeypatch.setattr(
        support_shift_reminders,
        "_zoom_request",
        lambda _token, method, path, **_kwargs: (
            {"ids": ["current-shift"]}
            if method == "POST"
            else {"id": "current-shift", "message": "same reminder"}
        ),
    )
    shift_start = datetime(2026, 8, 4, 14, 0, tzinfo=timezone.utc)

    result = support_shift_reminders._send_zoom_channel_message(
        "same reminder",
        shift_started_at=shift_start,
    )

    assert result == {
        "ok": True,
        "messageId": "current-shift",
        "readbackVerified": True,
    }
    assert history_calls == [shift_start]
