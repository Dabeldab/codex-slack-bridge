from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

import codex_slack_bridge.command_center_server as command_center_server
from codex_slack_bridge.command_center_server import CommandCenterRuntime
from codex_slack_bridge.prospective import ProspectiveStore


def _runtime(tmp_path, *, defaults=None, channels=None) -> CommandCenterRuntime:
    runtime = object.__new__(CommandCenterRuntime)
    runtime.config = SimpleNamespace(
        defaults={
            "prospective_timezone": "UTC",
            "allowed_user_ids": ["U1"],
            **(defaults or {}),
        },
        channels=channels if channels is not None else {"C1": "direct_codex"},
        agents={
            "coding_agent": {},
            "tickets_agent": {},
            "billing_agent": {},
            "direct_codex": {},
            "claude_agent": {},
        },
    )
    runtime.prospective = ProspectiveStore(tmp_path / "prospective.sqlite3")
    runtime._prospective_worker_id = "test-worker"
    return runtime


def test_runtime_create_list_cancel_and_reschedule(tmp_path):
    runtime = _runtime(tmp_path)
    created = runtime.prospective_create(
        {
            "title": "Resume Chargify MCP rollout",
            "dueAt": "2099-07-13T10:00:00Z",
            "channelId": "C1",
            "userId": "U1",
            "createdBy": "slack:U1",
            "idempotencyKey": "chargify-rollout",
        }
    )

    assert created["ok"] is True
    assert created["task"]["payload"] == {
        "channel_id": "C1",
        "user_id": "U1",
        "message": "Resume Chargify MCP rollout",
        "notify_only": True,
        "created_by": "slack:U1",
        "task_type": "reminder",
    }
    listed = runtime.prospective_tasks(status="active")
    assert listed["count"] == 1
    assert listed["tasks"][0]["id"] == created["task"]["id"]

    moved = runtime.prospective_reschedule(
        {"taskId": created["task"]["id"], "due": "2099-07-14T11:30:00Z"}
    )
    assert moved["task"]["next_scheduled_at"] == "2099-07-14T11:30:00Z"

    cancelled = runtime.prospective_cancel({"id": created["task"]["id"]})
    assert cancelled["task"]["status"] == "cancelled"
    assert runtime.prospective_tasks(status="active")["count"] == 0
    assert runtime.prospective_tasks(status="cancelled")["count"] == 1


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({"due": "2099-01-01T10:00:00Z", "channelId": "C1"}, "title is required"),
        ({"title": "missing due", "channelId": "C1"}, "dueAt or due is required"),
        ({"title": "missing channel", "due": "2099-01-01T10:00:00Z"}, "channelId is required"),
        (
            {"title": "unknown channel", "due": "2099-01-01T10:00:00Z", "channelId": "C2"},
            "not a configured agent channel",
        ),
        (
            {
                "title": "unknown operator",
                "due": "2099-01-01T10:00:00Z",
                "channelId": "C1",
                "userId": "U2",
            },
            "not an allowed operator",
        ),
    ],
)
def test_runtime_create_validates_destination_operator_and_required_fields(tmp_path, payload, message):
    runtime = _runtime(tmp_path)
    with pytest.raises(ValueError, match=message):
        runtime.prospective_create(payload)


def test_runtime_cancel_and_reschedule_validate_required_fields(tmp_path):
    runtime = _runtime(tmp_path)
    with pytest.raises(ValueError, match="taskId is required"):
        runtime.prospective_cancel({})
    with pytest.raises(ValueError, match="taskId is required"):
        runtime.prospective_reschedule({"due": "2099-01-01T10:00:00Z"})
    with pytest.raises(ValueError, match="dueAt or due is required"):
        runtime.prospective_reschedule({"taskId": "task"})


def test_runtime_creates_agent_dispatch_without_slack_destination(tmp_path):
    runtime = _runtime(tmp_path, channels={})
    created = runtime.prospective_create(
        {
            "taskType": "agent_dispatch",
            "agentName": "taylor",
            "title": "Copy ticket 347626 account",
            "instruction": "Perform the verified account copy requested by ticket 347626.",
            "ticketNumber": "347626",
            "dueAt": "2099-07-13T00:00:00-04:00",
            "timezone": "America/New_York",
            "idempotencyKey": "ticket-347626-midnight",
        }
    )

    task = created["task"]
    assert task["next_scheduled_at"] == "2099-07-13T04:00:00Z"
    assert task["payload"] == {
        "task_type": "agent_dispatch",
        "agent_name": "coding_agent",
        "instruction": "Perform the verified account copy requested by ticket 347626.",
        "dispatch_type": "salesforce-ticket-agent-prompt",
        "ticket_number": "347626",
        "salesforce_url": "",
        "account": "",
        "opened_by": "",
        "record_type": "",
        "main_issue": "",
        "technical_issue": "",
        "notes_context": "",
        "created_by": "command_center",
    }


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (
            {
                "taskType": "agent_dispatch",
                "agentName": "unknown",
                "title": "task",
                "instruction": "do it",
                "dueAt": "2099-01-01T10:00:00Z",
            },
            "not a configured agent",
        ),
        (
            {
                "taskType": "agent_dispatch",
                "agentName": "taylor",
                "title": "task",
                "dueAt": "2099-01-01T10:00:00Z",
            },
            "instruction is required",
        ),
    ],
)
def test_runtime_agent_dispatch_validates_target_and_instruction(tmp_path, payload, message):
    runtime = _runtime(tmp_path)
    with pytest.raises(ValueError, match=message):
        runtime.prospective_create(payload)


def test_due_agent_dispatch_is_queued_once_with_durable_readback(tmp_path):
    runtime = _runtime(tmp_path)
    task = runtime.prospective_create(
        {
            "taskType": "agent_dispatch",
            "agentName": "taylor",
            "title": "Copy one account",
            "instruction": "Copy the verified source account into the verified target account.",
            "ticketNumber": "347626",
            "dueAt": "2000-01-01T00:00:00Z",
            "idempotencyKey": "scheduled-copy-347626",
        }
    )["task"]
    occurrence_id = task["next_occurrence"]["id"]
    occurrence_key = task["next_occurrence"]["idempotency_key"]
    submissions = []

    def submit_prompt(**kwargs):
        submissions.append(kwargs)
        return {
            "accepted": True,
            "message": "queued",
            "job_id": "cc-scheduled",
            "bridge_job_id": 123,
            "agentName": kwargs["agent_name"],
        }

    runtime.submit_prompt = submit_prompt
    runtime.job = lambda _job_id: {
        "id": "cc-scheduled",
        "sourceType": "prospective-agent-dispatch",
        "idempotencyKey": occurrence_key,
        "agentName": "coding_agent",
        "status": "queued",
    }

    runtime._deliver_due_prospective_tasks(5)
    runtime._deliver_due_prospective_tasks(5)

    assert len(submissions) == 1
    assert submissions[0]["source_type"] == "prospective-agent-dispatch"
    assert submissions[0]["payload"]["idempotencyKey"] == occurrence_key
    assert submissions[0]["payload"]["ticketNumber"] == "347626"
    delivered = runtime.prospective.get_occurrence(occurrence_id)
    assert delivered["status"] == "delivered"
    assert delivered["result"] == {
        "job_id": "cc-scheduled",
        "bridge_job_id": 123,
        "agent_name": "coding_agent",
        "source_type": "prospective-agent-dispatch",
        "idempotency_key": occurrence_key,
        "duplicate": False,
        "readback_status": "queued",
    }


def test_transient_delivery_failure_requeues_same_occurrence(tmp_path):
    runtime = _runtime(
        tmp_path,
        defaults={
            "prospective_lease_seconds": 1,
            "prospective_retry_seconds": 1,
            "prospective_delivery_batch_size": 1,
        },
    )
    task = runtime.prospective.create(
        title="Retry me",
        due_at="2000-01-01T00:00:00Z",
        payload={"channel_id": "C1", "message": "Retry me"},
    )
    occurrence_id = task["next_occurrence"]["id"]
    stable_key = task["next_occurrence"]["idempotency_key"]
    runtime._post_prospective_reminder = lambda _occurrence: (_ for _ in ()).throw(RuntimeError("Slack unavailable"))

    before = datetime.now(UTC)
    runtime._deliver_due_prospective_tasks(5)
    after = datetime.now(UTC)

    occurrence = runtime.prospective.get_occurrence(occurrence_id)
    assert occurrence["status"] == "pending"
    assert occurrence["idempotency_key"] == stable_key
    assert occurrence["attempt_count"] == 1
    assert occurrence["last_error"] == "Slack unavailable"
    available_at = datetime.fromisoformat(occurrence["available_at"].replace("Z", "+00:00"))
    # Runtime clamps both retry and lease configuration to at least 30 seconds.
    assert before + timedelta(seconds=29) <= available_at <= after + timedelta(seconds=31)
    assert runtime.prospective.claim_due("too-soon", now=before + timedelta(seconds=29)) == []
    retry = runtime.prospective.claim_due("retry-worker", now=after + timedelta(seconds=31))[0]
    assert retry["id"] == occurrence_id
    assert retry["idempotency_key"] == stable_key


def test_slack_post_uses_stable_occurrence_id_as_client_msg_id(tmp_path, monkeypatch):
    runtime = _runtime(tmp_path)
    monkeypatch.setenv("SLACK_BOT_TOKEN", "test-token")
    request_bodies: list[dict] = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self):
            return json.dumps({"ok": True, "channel": "C1", "ts": "123.456"}).encode("utf-8")

    def fake_urlopen(request, timeout):
        assert timeout == 20
        request_bodies.append(json.loads(request.data.decode("utf-8")))
        return Response()

    monkeypatch.setattr(command_center_server.urllib.request, "urlopen", fake_urlopen)
    occurrence = {
        "id": "cab09dbb-5fb1-5ab7-9e3d-68ed1706dd6e",
        "idempotency_key": "prospective:stable-key",
        "title": "Check the upgrade",
        "payload": {"channel_id": "C1", "user_id": "U1"},
    }

    first = runtime._post_prospective_reminder(occurrence)
    second = runtime._post_prospective_reminder(dict(occurrence))

    assert [body["client_msg_id"] for body in request_bodies] == [occurrence["id"], occurrence["id"]]
    assert request_bodies[0]["text"] == "<@U1> Reminder: Check the upgrade"
    assert first == second == {
        "channel": "C1",
        "message_ts": "123.456",
        "idempotency_key": "prospective:stable-key",
    }


def test_start_watcher_enforces_prospective_five_second_minimum(tmp_path, monkeypatch):
    runtime = _runtime(tmp_path, defaults={"ops_watch_initial_delay_seconds": 0})
    constructed = []

    class FakeThread:
        def __init__(self, **kwargs):
            constructed.append(kwargs)

        def start(self):
            constructed[-1]["started"] = True

    monkeypatch.setattr(command_center_server, "Thread", FakeThread)
    runtime._start_watcher(
        name="prospective-reminder-watch",
        interval_seconds=1,
        target=runtime._deliver_due_prospective_tasks,
        minimum_interval_seconds=5,
    )

    assert len(constructed) == 1
    assert constructed[0]["args"][1:3] == (5, 5)
    assert constructed[0]["started"] is True
