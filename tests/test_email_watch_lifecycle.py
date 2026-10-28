from __future__ import annotations

import json
import os
import time
from threading import Lock
from types import SimpleNamespace

import pytest

import codex_slack_bridge.command_center_server as command_center_server
from codex_slack_bridge.command_center_server import CommandCenterRuntime
from codex_slack_bridge.drawing_board import DrawingBoardStore


def _gmail_message(
    message_id: str,
    observed_at: int,
    labels: list[str],
    *,
    recipient: str = "darius@example.com",
) -> dict:
    return {
        "id": message_id,
        "internalDate": str(observed_at),
        "labelIds": labels,
        "payload": {
            "headers": [
                {"name": "To", "value": recipient},
                {"name": "Cc", "value": ""},
            ]
        },
    }


def _pending_gmail_state(
    *,
    thread_id: str = "thread-pending",
    message_id: str = "message-pending",
    direct_to_user: bool = True,
) -> dict:
    return {
        "verified": True,
        "pending": True,
        "inInbox": True,
        "unread": True,
        "answered": False,
        "latestDirection": "inbound",
        "latestMessageId": message_id,
        "latestIncomingMessageId": message_id,
        "threadId": thread_id,
        "directToUser": direct_to_user,
        "verifiedAtUtc": "2026-07-14T12:00:00Z",
    }


def _email_record(
    *,
    thread_id: str = "thread-pending",
    message_id: str = "message-pending",
    gmail_state: dict | None = None,
    triage_decision: str = "reply_needed",
) -> dict:
    return {
        "id": message_id,
        "threadId": thread_id,
        "from": "Operations Lead <operations@example.com>",
        "subject": "Complete the quarter-end access review",
        "triageDecision": triage_decision,
        "gmailState": gmail_state
        if gmail_state is not None
        else _pending_gmail_state(thread_id=thread_id, message_id=message_id),
    }


def _drawing_candidate(
    *,
    source_id: str = "message-pending",
    source_thread_id: str = "thread-pending",
    **overrides,
) -> dict:
    candidate = {
        "sourceId": source_id,
        "sourceThreadId": source_thread_id,
        "title": "Complete quarter-end access review",
        "request": "Operations needs Darius to review the quarter-end access exceptions.",
        "requestedOutcome": "Approve or reject every listed access exception before the deadline.",
        "nextAction": "Open the linked exception list and review each requested access change.",
        "ownerAction": "Darius must record an approval or rejection for every exception.",
        "completionCriteria": "Every exception has a recorded decision and the requester is notified.",
        "category": "operational",
        "explicitForDarius": True,
        "actionRequired": True,
        "confidence": 0.96,
        "priority": "high",
    }
    candidate.update(overrides)
    return candidate


@pytest.mark.parametrize(
    ("messages", "expected"),
    [
        (
            [_gmail_message("incoming-read", 100, ["INBOX"])],
            {
                "pending": False,
                "unread": False,
                "answered": False,
                "latestDirection": "inbound",
            },
        ),
        (
            [_gmail_message("incoming-unread", 100, ["INBOX", "UNREAD"])],
            {
                "pending": True,
                "unread": True,
                "answered": False,
                "latestDirection": "inbound",
            },
        ),
        (
            [
                _gmail_message("incoming-unread", 100, ["INBOX", "UNREAD"]),
                _gmail_message("outbound-answer", 200, ["SENT"]),
            ],
            {
                "pending": False,
                "unread": True,
                "answered": True,
                "latestDirection": "outbound",
            },
        ),
        (
            [
                _gmail_message("outbound-answer", 100, ["SENT"]),
                _gmail_message("new-incoming", 200, ["INBOX", "UNREAD"]),
            ],
            {
                "pending": True,
                "unread": True,
                "answered": False,
                "latestDirection": "inbound",
            },
        ),
    ],
)
def test_gmail_thread_state_tracks_latest_non_draft_direction(
    monkeypatch,
    messages,
    expected,
):
    monkeypatch.setattr(
        command_center_server,
        "_gmail_api_get_json",
        lambda _url, *, token: {"messages": messages},
    )

    state = command_center_server._gmail_email_watch_thread_state(
        "oauth-token",
        {"threadId": "thread-1"},
        profile_email="darius@example.com",
    )

    assert state["verified"] is True
    assert state["inInbox"] is True
    assert state["directToUser"] is True
    assert {key: state[key] for key in expected} == expected


def test_gmail_thread_state_ignores_drafts_when_deciding_if_answered(monkeypatch):
    messages = [
        _gmail_message("incoming", 100, ["INBOX", "UNREAD"]),
        _gmail_message("unsent-draft", 200, ["DRAFT"]),
    ]
    monkeypatch.setattr(
        command_center_server,
        "_gmail_api_get_json",
        lambda _url, *, token: {"messages": messages},
    )

    state = command_center_server._gmail_email_watch_thread_state(
        "oauth-token",
        {"threadId": "thread-1"},
        profile_email="darius@example.com",
    )

    assert state["pending"] is True
    assert state["answered"] is False
    assert state["latestMessageId"] == "incoming"


def test_reconciliation_removes_read_or_answered_threads_and_exposes_only_pending(
    tmp_path,
    monkeypatch,
):
    runtime = object.__new__(CommandCenterRuntime)
    runtime.email_watch_path = tmp_path / "ops_email_watch.json"
    runtime.gmail_token_path = tmp_path / "gmail-token.json"
    runtime._lock = Lock()
    runtime.email_watch_path.write_text(
        json.dumps(
            {
                "ok": True,
                "emails": [
                    _email_record(thread_id="thread-pending", message_id="message-pending"),
                    _email_record(thread_id="thread-handled", message_id="message-handled"),
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(command_center_server, "_gmail_access_token", lambda _path: "token")
    monkeypatch.setattr(
        command_center_server,
        "_gmail_profile_email",
        lambda _token: "darius@example.com",
    )

    def fake_thread_state(_token, email, *, profile_email):
        if email["threadId"] == "thread-pending":
            return _pending_gmail_state()
        return {
            **_pending_gmail_state(
                thread_id="thread-handled",
                message_id="message-handled",
            ),
            "pending": False,
            "answered": True,
            "latestDirection": "outbound",
            "latestMessageId": "outbound-answer",
        }

    monkeypatch.setattr(
        command_center_server,
        "_gmail_email_watch_thread_state",
        fake_thread_state,
    )

    result = runtime._reconcile_email_watch_cache_with_gmail()
    raw_cache = json.loads(runtime.email_watch_path.read_text(encoding="utf-8"))
    visible_cache = runtime.email_watch()

    assert result == {
        **result,
        "status": "ok",
        "checked": 2,
        "removed": 1,
        "pending": 1,
    }
    assert [email["threadId"] for email in raw_cache["emails"]] == ["thread-pending"]
    assert raw_cache["emails"][0]["gmailState"]["verified"] is True
    assert [email["threadId"] for email in visible_cache["emails"]] == ["thread-pending"]
    assert visible_cache["count"] == 1


def test_reconciliation_failure_retains_raw_cache_but_fails_closed_in_mail_watch(
    tmp_path,
    monkeypatch,
):
    runtime = object.__new__(CommandCenterRuntime)
    runtime.email_watch_path = tmp_path / "ops_email_watch.json"
    runtime.gmail_token_path = tmp_path / "gmail-token.json"
    runtime._lock = Lock()
    # Even a previously verified row must not remain visible after a current
    # readback failure; its cached business details are retained for retry.
    original = _email_record()
    runtime.email_watch_path.write_text(
        json.dumps({"ok": True, "emails": [original]}),
        encoding="utf-8",
    )

    def unavailable(_path):
        raise RuntimeError("OAuth unavailable")

    monkeypatch.setattr(command_center_server, "_gmail_access_token", unavailable)

    result = runtime._reconcile_email_watch_cache_with_gmail()
    raw_cache = json.loads(runtime.email_watch_path.read_text(encoding="utf-8"))

    assert result["status"] == "unavailable"
    assert len(raw_cache["emails"]) == 1
    assert raw_cache["emails"][0]["threadId"] == original["threadId"]
    assert raw_cache["status"] == "partial"
    assert runtime.email_watch()["emails"] == []


def test_email_watcher_preserves_scan_due_state_when_reconciliation_rewrites_cache(
    tmp_path,
    monkeypatch,
):
    runtime = object.__new__(CommandCenterRuntime)
    runtime.email_watch_path = tmp_path / "ops_email_watch.json"
    runtime.email_watch_path.write_text('{"ok": true, "emails": []}', encoding="utf-8")
    old_timestamp = time.time() - 7200
    os.utime(runtime.email_watch_path, (old_timestamp, old_timestamp))
    runtime.config = SimpleNamespace(defaults={})
    queued: list[bool] = []

    def reconcile_and_rewrite():
        runtime.email_watch_path.write_text(
            '{"ok": true, "emails": [], "reconciliation": {"status": "ok"}}',
            encoding="utf-8",
        )
        return {}

    runtime._reconcile_email_watch_cache_with_gmail = reconcile_and_rewrite
    runtime._sync_drawing_board_candidates = lambda _kind: []
    runtime._active_source_type = lambda _kind: False
    runtime._active_agent_lane = lambda _agent: False
    runtime.submit_email_scan = lambda: queued.append(True) or {"accepted": True}
    monkeypatch.setattr(command_center_server, "_ops_business_hours_open", lambda *_args: True)

    runtime._submit_email_scan_if_idle(3600)

    assert queued == [True]


def test_qualified_email_creates_one_actionable_operator_owned_task(tmp_path):
    runtime = object.__new__(CommandCenterRuntime)
    runtime.email_watch_path = tmp_path / "ops_email_watch.json"
    runtime.schedule_path = tmp_path / "ops_schedule.json"
    runtime.drawing_board = DrawingBoardStore(tmp_path / "drawing-board.sqlite3")
    runtime.email_watch_path.write_text(
        json.dumps(
            {
                "ok": True,
                "emails": [_email_record()],
                "drawingBoardCandidates": [_drawing_candidate()],
            }
        ),
        encoding="utf-8",
    )

    first = runtime._sync_drawing_board_candidates("email")
    history_after_first = runtime.drawing_board.history(first[0]["id"])
    second = runtime._sync_drawing_board_candidates("email")
    tasks = runtime.drawing_board.list_tasks(include_archived=True)
    cache = json.loads(runtime.email_watch_path.read_text(encoding="utf-8"))

    assert len(first) == 1
    assert second == []
    assert len(tasks) == 1
    assert tasks[0]["id"] == first[0]["id"]
    assert runtime.drawing_board.history(tasks[0]["id"]) == history_after_first
    assert tasks[0]["status"] == "ready"
    assert tasks[0]["owner"] == "Darius"
    assert tasks[0]["operator_owned"] is True
    assert tasks[0]["agent_name"] == ""
    assert tasks[0]["actionable"] is True
    assert tasks[0]["missing_actionability_fields"] == []
    assert cache["emails"][0]["drawingBoardTaskId"] == tasks[0]["id"]
    assert cache["drawingBoardCandidates"][0]["drawingBoardTaskId"] == tasks[0]["id"]


def test_newer_inbound_reuses_active_task_and_cannot_duplicate_after_completion(tmp_path):
    runtime = object.__new__(CommandCenterRuntime)
    runtime.email_watch_path = tmp_path / "ops_email_watch.json"
    runtime.schedule_path = tmp_path / "ops_schedule.json"
    runtime.drawing_board = DrawingBoardStore(tmp_path / "drawing-board.sqlite3")
    runtime.email_watch_path.write_text(
        json.dumps(
            {
                "ok": True,
                "emails": [_email_record()],
                "drawingBoardCandidates": [_drawing_candidate()],
            }
        ),
        encoding="utf-8",
    )
    first = runtime._sync_drawing_board_candidates("email")[0]

    newer_email = _email_record(
        thread_id="thread-pending",
        message_id="message-newer",
        gmail_state=_pending_gmail_state(
            thread_id="thread-pending",
            message_id="message-newer",
        ),
    )
    newer_candidate = _drawing_candidate(
        source_id="message-newer",
        source_thread_id="thread-pending",
        requestedOutcome="Approve every new exception added in the follow-up message.",
    )
    runtime.email_watch_path.write_text(
        json.dumps(
            {
                "ok": True,
                "emails": [newer_email],
                "drawingBoardCandidates": [newer_candidate],
            }
        ),
        encoding="utf-8",
    )

    updated = runtime._sync_drawing_board_candidates("email")
    assert [task["id"] for task in updated] == [first["id"]]
    assert runtime.drawing_board.get(first["id"])["source_id"] == "message-newer"
    runtime.drawing_board.update(
        first["id"],
        {"status": "verified_complete", "humanVerified": True},
        actor="operator",
    )

    assert runtime._sync_drawing_board_candidates("email") == []
    assert len(runtime.drawing_board.list_tasks(include_archived=True)) == 1


def test_drawing_board_rejects_contradictory_operator_and_agent_ownership(tmp_path):
    store = DrawingBoardStore(tmp_path / "drawing-board.sqlite3")
    with pytest.raises(ValueError, match="both operator-owned and assigned"):
        store.create(
            {
                "title": "Review operating exception list",
                "description": "Operations requests a decision on every listed exception.",
                "requestedOutcome": "Every exception receives a documented decision.",
                "nextAction": "Open the source list and inspect the first exception.",
                "assigneeAction": "The assigned owner records each required decision.",
                "completionCriteria": "Every exception has a recorded approval or rejection.",
                "owner": "Darius",
                "operatorOwned": True,
                "agentName": "coding_agent",
                "status": "ready",
                "sourceId": "source-1",
            }
        )


@pytest.mark.parametrize(
    ("email_changes", "candidate_changes"),
    [
        ({"triageDecision": "ticket_needed"}, {}),
        ({"gmailState": _pending_gmail_state(direct_to_user=False)}, {}),
        ({"gmailState": {**_pending_gmail_state(), "pending": False, "unread": False}}, {}),
        ({}, {"kind": "failure"}),
        ({}, {"explicitForDarius": False}),
        ({}, {"completionCriteria": ""}),
    ],
)
def test_email_candidate_admission_rejects_non_tasks(
    tmp_path,
    email_changes,
    candidate_changes,
):
    runtime = object.__new__(CommandCenterRuntime)
    runtime.email_watch_path = tmp_path / "ops_email_watch.json"
    runtime.schedule_path = tmp_path / "ops_schedule.json"
    runtime.drawing_board = DrawingBoardStore(tmp_path / "drawing-board.sqlite3")
    runtime.email_watch_path.write_text(
        json.dumps(
            {
                "ok": True,
                "emails": [{**_email_record(), **email_changes}],
                "drawingBoardCandidates": [
                    {**_drawing_candidate(), **candidate_changes}
                ],
            }
        ),
        encoding="utf-8",
    )

    admitted = runtime._sync_drawing_board_candidates("email")

    assert admitted == []
    assert runtime.drawing_board.list_tasks(include_archived=True) == []


def test_meeting_candidate_requires_a_concrete_darius_action(tmp_path):
    runtime = object.__new__(CommandCenterRuntime)
    runtime.email_watch_path = tmp_path / "ops_email_watch.json"
    runtime.schedule_path = tmp_path / "ops_schedule.json"
    runtime.drawing_board = DrawingBoardStore(tmp_path / "drawing-board.sqlite3")
    meeting = {
        "id": "meeting-1",
        "start": "2026-07-15T14:00:00-04:00",
        "organizer": "COO <coo@example.com>",
        "htmlLink": "https://calendar.google.com/calendar/event?eid=meeting-1",
    }
    actionable = _drawing_candidate(
        source_id="meeting-1",
        source_thread_id="",
        sourceStart=meeting["start"],
        title="Prepare operating review decision",
    )
    attendance_only = _drawing_candidate(
        source_id="meeting-1",
        source_thread_id="",
        sourceStart=meeting["start"],
        title="Attend weekly operating review",
        actionRequired=False,
    )
    runtime.schedule_path.write_text(
        json.dumps(
            {
                "ok": True,
                "meetings": [meeting],
                "drawingBoardCandidates": [actionable, attendance_only],
            }
        ),
        encoding="utf-8",
    )

    admitted = runtime._sync_drawing_board_candidates("meeting")
    tasks = runtime.drawing_board.list_tasks(include_archived=True)

    assert len(admitted) == 1
    assert len(tasks) == 1
    assert tasks[0]["source_type"] == "calendar_action"
    assert tasks[0]["source_id"] == "meeting-1"
    assert tasks[0]["operator_owned"] is True
    assert tasks[0]["actionable"] is True
