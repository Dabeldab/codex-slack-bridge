from __future__ import annotations

import json
import os
import sqlite3
import time
from concurrent.futures import Future
from dataclasses import replace

import pytest

# AgentChat/direct_codex 2026-07-14T14:45:00-04:00: verify review-policy resolution audit retention.
# AgentChat/coding_agent 2026-07-11T11:32:00-04:00
# AgentChat/direct_codex 2026-07-13T00:16:00-04:00
# AgentChat/coding_agent 2026-07-13T00:56:02-04:00
# AgentChat/direct_codex 2026-07-13T01:28:53-04:00
# AgentChat/coding_agent 2026-07-13T12:05:00-04:00
# AgentChat/direct_codex 2026-07-27T22:55:00Z: verify durable terminal Slack feedback recovery.
# AgentChat/coding_agent 2026-07-30T17:15:00Z: verify readback-first recovery keeps one durable obligation.
from codex_slack_bridge.agent_runtime import AgentSessionStore
from codex_slack_bridge.config import BridgeConfig, ChannelRoute
from codex_slack_bridge.observability import build_system_status, reconcile_system_jobs
from codex_slack_bridge.state import BridgeState, active_requests_equivalent
import codex_slack_bridge.app as slack_app


def _job(state: BridgeState, *, status: str = "queued", channel_id: str = "command_center") -> int:
    job_id = state.create_job(
        event_id=f"event-{status}-{channel_id}",
        channel_id=channel_id,
        thread_ts="thread",
        user_id="user",
        agent_name="coding_agent",
        request_text="test request",
    )
    if status == "running":
        state.mark_started(job_id)
    return job_id


def _config(tmp_path) -> BridgeConfig:
    return BridgeConfig(
        defaults={
            "agent_runtime_session_store_path": str(tmp_path / "sessions.jsonl"),
            "agent_runtime_lock_root": str(tmp_path / "locks"),
            "agent_runtime_shared_sessions": True,
            "agent_runtime_session_scope": "agent",
            "command_center_pause_manifest_path": str(tmp_path / "restart_manifest.json"),
            "job_reconciliation_stale_seconds": 0,
            "job_reconciliation_session_grace_seconds": 300,
        },
        channels={},
        agents={"coding_agent": {"provider": "codex_cli", "workspace_root": str(tmp_path)}},
    )


def test_slack_supervised_restart_request_uses_configured_runtime_path(
    monkeypatch, tmp_path
) -> None:
    expected = tmp_path / "agent_runtime" / "restart_request.json"
    config = BridgeConfig(
        defaults={"agent_runtime_restart_request_path": str(expected)},
        channels={},
        agents={},
    )
    monkeypatch.setattr(slack_app, "SLACK_CONFIG", config)

    assert slack_app._supervised_restart_request_path() == expected


def test_reconcile_requires_authoritative_absence_before_inferring_stale(tmp_path):
    state = BridgeState(str(tmp_path / "bridge.sqlite3"))
    queued = _job(state)
    running = _job(state, status="running")

    result = state.reconcile_active_jobs(
        live_job_ids=set(),
        authoritative=False,
        stale_after_seconds=0,
        now=100,
    )

    assert result["changed"] == []
    assert set(result["deferredJobIds"]) == {queued, running}
    assert state.job_counts() == {"queued": 1, "running": 1}


def test_job_by_event_id_returns_one_exact_durable_job(tmp_path):
    state = BridgeState(str(tmp_path / "bridge.sqlite3"))
    job_id = state.create_job(
        event_id="handoff-child",
        channel_id="command_center",
        thread_ts="thread",
        user_id="user",
        agent_name="billing_agent",
        request_text="continue verified work",
    )
    state.mark_started(job_id)
    state.mark_outcome(job_id, "failed", result_text="FAILED\nTyped readback failed.")

    record = state.job_by_event_id("handoff-child")

    assert record is not None
    assert record["id"] == job_id
    assert record["status"] == "failed"
    assert record["result_text"].startswith("FAILED")
    assert state.job_by_event_id("missing") is None


def test_authoritative_reconcile_marks_orphans_and_preserves_evidence(tmp_path):
    state = BridgeState(str(tmp_path / "bridge.sqlite3"))
    queued = _job(state)
    running = _job(state, status="running")
    live = _job(state, status="running")
    protected = _job(state)

    result = state.reconcile_active_jobs(
        live_job_ids={live},
        protected_job_ids={protected},
        authoritative=True,
        stale_after_seconds=0,
        now=1_000_000,
    )

    assert {(item["id"], item["to"]) for item in result["changed"]} == {
        (queued, "superseded"),
        (running, "interrupted"),
    }
    assert set(result["retainedJobIds"]) == {live, protected}
    rows = {int(row["id"]): row for row in state.list_jobs(limit=10)}
    assert rows[queued]["reconciliation_reason"]
    assert rows[running]["completed_at"] == 1_000_000


def test_terminal_slack_feedback_remains_pending_until_delivery_confirmation(tmp_path):
    state = BridgeState(str(tmp_path / "bridge.sqlite3"))
    job_id = state.create_job(
        event_id="delivery-outbox",
        channel_id="C123",
        thread_ts="thread",
        user_id="U123",
        agent_name="direct_codex",
        request_text="complete this",
    )
    state.mark_started(job_id)
    state.mark_recovery_review_required(job_id, "Runtime restarted during the active job.")

    pending = state.list_pending_terminal_deliveries()

    assert [row["id"] for row in pending] == [job_id]
    assert pending[0]["status"] == "recovery_review_required"
    state.mark_delivery_failed(job_id, "temporary Slack outage")
    assert state.list_pending_terminal_deliveries()[0]["delivery_attempts"] == 1
    state.mark_delivery_succeeded(job_id)
    assert state.list_pending_terminal_deliveries() == []


def test_pending_terminal_slack_feedback_is_posted_and_confirmed(monkeypatch, tmp_path):
    state = BridgeState(str(tmp_path / "bridge.sqlite3"))
    job_id = state.create_job(
        event_id="delivery-retry",
        channel_id="C123",
        thread_ts="",
        user_id="U123",
        agent_name="direct_codex",
        request_text="complete this",
    )
    state.mark_started(job_id)
    state.mark_recovery_review_required(job_id, "Runtime restarted during the active job.")

    class Client:
        def __init__(self) -> None:
            self.messages = []

        def chat_postMessage(self, **kwargs):
            self.messages.append(kwargs)
            return {"ok": True, "ts": "1.0"}

    client = Client()
    config = BridgeConfig(
        defaults={"reply_in_thread": False, "max_slack_message_chars": 3900},
        channels={},
        agents={},
    )
    monkeypatch.setattr(slack_app, "STATE", state)

    assert slack_app._deliver_pending_terminal_slack_feedback(config, client) == 1
    assert len(client.messages) == 1
    assert f"job `{job_id}`" in client.messages[0]["text"]
    assert client.messages[0]["client_msg_id"]
    assert state.list_pending_terminal_deliveries() == []


def test_explicit_terminal_and_review_evidence_apply_without_absence_inference(tmp_path):
    state = BridgeState(str(tmp_path / "bridge.sqlite3"))
    completed = _job(state, status="running")
    review = _job(state, status="running")
    untouched = _job(state)

    result = state.reconcile_active_jobs(
        live_job_ids=None,
        terminal_statuses={completed: "completed"},
        recovery_review_job_ids={review},
        authoritative=False,
        now=1234,
    )

    assert {(item["id"], item["to"]) for item in result["changed"]} == {
        (completed, "completed"),
        (review, "recovery_review_required"),
    }
    assert result["deferredJobIds"] == [untouched]


def test_recovery_fence_prevents_late_worker_completion(tmp_path):
    state = BridgeState(str(tmp_path / "bridge.sqlite3"))
    job_id = _job(state)

    assert state.mark_started(job_id, runtime_instance_id="attempt-a", stage="running") is True
    state.mark_recovery_review_required(job_id, "worker lost")

    assert state.mark_completed(job_id, runtime_instance_id="attempt-a") is False
    assert state.mark_failed(job_id, "late failure", runtime_instance_id="attempt-a") is False
    row = state.list_jobs(limit=1)[0]
    assert row["status"] == "recovery_review_required"
    assert row["recovery_count"] == 1


def test_requeue_for_recovery_preserves_job_and_reclaims_once(tmp_path):
    state = BridgeState(str(tmp_path / "bridge.sqlite3"))
    job_id = state.create_job(
        event_id="stable-event",
        channel_id="C123",
        thread_ts="thread",
        user_id="U123",
        agent_name="coding_agent",
        request_text="apply the exact authorized change",
        recovery_policy="queued_replay",
    )
    assert state.mark_started(
        job_id,
        runtime_instance_id="runtime-a",
        stage="running_model_attempt_1",
    )

    assert state.requeue_for_recovery(
        job_id,
        "worker timed out",
        recovery_policy="same_surface_readback_first",
        runtime_instance_id="runtime-a",
    )
    row = state.jobs_by_ids({job_id})[job_id]

    assert row["id"] == job_id
    assert row["event_id"] == "stable-event"
    assert row["request_text"] == "apply the exact authorized change"
    assert row["status"] == "queued"
    assert row["runtime_stage"] == "recovery_queued"
    assert row["recovery_policy"] == "same_surface_readback_first"
    assert row["recovery_count"] == 1
    assert state.mark_started(
        job_id,
        runtime_instance_id="runtime-b",
        stage="recovery_readback",
    )
    assert not state.mark_started(
        job_id,
        runtime_instance_id="runtime-c",
        stage="duplicate",
    )


def test_terminal_child_receipt_can_reopen_slack_delivery_outbox(tmp_path):
    state = BridgeState(str(tmp_path / "bridge.sqlite3"))
    job_id = state.create_job(
        event_id="handoff-origin",
        channel_id="C123",
        thread_ts="thread",
        user_id="U123",
        agent_name="tickets_agent",
        request_text="complete through the owning lane",
    )
    assert state.mark_started(job_id)
    assert state.update_runtime_stage(job_id, "handoff_acknowledged")
    state.mark_delivery_succeeded(job_id)

    assert state.mark_outcome(
        job_id,
        "completed",
        result_text="COMPLETED\nThe receiving lane returned verified readback.",
    )
    state.mark_delivery_pending(job_id)

    pending = state.list_pending_terminal_deliveries()
    assert [row["id"] for row in pending] == [job_id]
    assert pending[0]["result_text"].startswith("COMPLETED")


def test_queued_job_claim_is_compare_and_set(tmp_path):
    state = BridgeState(str(tmp_path / "bridge.sqlite3"))
    job_id = _job(state)

    assert state.mark_started(job_id, runtime_instance_id="attempt-a") is True
    assert state.mark_started(job_id, runtime_instance_id="attempt-b") is False
    row = state.list_jobs(limit=1)[0]
    assert row["runtime_instance_id"] == "attempt-a"


def test_reconcile_system_jobs_uses_scheduler_live_lock_session_and_manifest(tmp_path):
    config = _config(tmp_path)
    state = BridgeState(str(tmp_path / "bridge.sqlite3"))
    scheduler = _job(state, status="running")
    lock_job = _job(state, status="running")
    session_job = _job(state, status="running")
    review_job = _job(state, status="running")
    orphan = _job(state, status="running")

    lock_root = tmp_path / "locks"
    lock_root.mkdir()
    (lock_root / "coding_agent.lock").write_text(
        json.dumps({"pid": os.getpid(), "owner": {"jobId": lock_job}}),
        encoding="utf-8",
    )
    AgentSessionStore(tmp_path / "sessions.jsonl").upsert(
        agent_name="coding_agent",
        surface="shared",
        conversation_id="agent:coding_agent",
        provider="codex_cli",
        workspace=str(tmp_path),
        session_id="session",
        status="running",
        job_id=session_job,
    )
    (tmp_path / "restart_manifest.json").write_text(
        json.dumps(
            {
                "state": "active_recovery",
                "jobs": [{"id": "cc-review", "bridgeJobId": review_job}],
                "reviewRequiredJobIds": ["cc-review"],
            }
        ),
        encoding="utf-8",
    )

    result = reconcile_system_jobs(
        config,
        state,
        runtime_job_ids={scheduler},
        authoritative=True,
        stale_after_seconds=0,
    )

    assert result["evidence"]["schedulerJobIds"] == [scheduler]
    assert result["evidence"]["liveLockJobIds"] == [lock_job]
    assert session_job in result["evidence"]["recentSessionJobIds"]
    assert review_job in result["evidence"]["recoveryReviewJobIds"]
    rows = {int(row["id"]): row for row in state.list_jobs(limit=10)}
    assert rows[scheduler]["status"] == "running"
    assert rows[lock_job]["status"] == "running"
    assert rows[session_job]["status"] == "running"
    assert rows[review_job]["status"] == "recovery_review_required"
    assert rows[orphan]["status"] == "interrupted"


def test_status_reconciles_before_reporting_counts_when_runtime_ids_are_supplied(tmp_path):
    config = _config(tmp_path)
    state = BridgeState(str(tmp_path / "bridge.sqlite3"))
    orphan = _job(state, status="running")

    snapshot = build_system_status(
        config,
        state,
        live_bridge_job_ids=set(),
        command_center_jobs=[],
        limit=10,
    )

    assert snapshot["reconciliation"]["changed"][0]["id"] == orphan
    assert snapshot["bridgeJobs"]["active"] == []
    assert snapshot["bridgeJobs"]["counts"]["interrupted"] == 1


def test_reconcile_removes_dead_lock_and_marks_job_and_session_interrupted(tmp_path, monkeypatch):
    config = _config(tmp_path)
    state = BridgeState(str(tmp_path / "bridge.sqlite3"))
    orphan = _job(state, status="running")
    lock_root = tmp_path / "locks"
    lock_root.mkdir()
    lock_path = lock_root / "coding_agent.lock"
    lock_path.write_text(
        json.dumps({"pid": 999999, "owner": {"jobId": orphan, "agentName": "coding_agent"}}),
        encoding="utf-8",
    )
    old_time = time.time() - 35
    os.utime(lock_path, (old_time, old_time))
    AgentSessionStore(tmp_path / "sessions.jsonl").upsert(
        agent_name="coding_agent",
        surface="shared",
        conversation_id="agent:coding_agent",
        provider="codex_cli",
        workspace=str(tmp_path),
        session_id="resume-me",
        status="running",
        job_id=orphan,
    )
    monkeypatch.setattr("codex_slack_bridge.agent_runtime._process_exists", lambda pid: False)

    result = reconcile_system_jobs(
        config,
        state,
        runtime_job_ids=set(),
        authoritative=True,
        stale_after_seconds=0,
    )

    assert not lock_path.exists()
    assert result["evidence"]["removedStaleLockJobIds"] == [orphan]
    assert state.list_jobs(limit=1)[0]["status"] == "interrupted"
    session = AgentSessionStore(tmp_path / "sessions.jsonl").get(
        agent_name="coding_agent",
        surface="shared",
        conversation_id="agent:coding_agent",
    )
    assert session is not None
    assert session.status == "interrupted"
    assert session.session_id == "resume-me"


def test_slack_runtime_monitor_reconciles_configured_and_fallback_channels(tmp_path, monkeypatch):
    config = replace(_config(tmp_path), channels={"channel-a": object(), "channel-b": object()})
    state = BridgeState(str(tmp_path / "slack.sqlite3"))
    configured = _job(state, channel_id="channel-a")
    fallback = _job(state, channel_id="channel-fallback")
    _job(state, channel_id="command_center")
    monkeypatch.setattr(slack_app, "STATE", state)
    monkeypatch.setattr(slack_app, "ACTIVE_JOB_IDS", {configured, fallback})
    monkeypatch.setattr(slack_app, "ACTIVE_JOB_FUTURES", {configured: Future(), fallback: Future()})
    monkeypatch.setattr(slack_app, "ACTIVE_JOB_RETRY_TIMERS", {})
    monkeypatch.setattr(slack_app, "SLACK_CLIENT", None)
    calls = []

    def fake_reconcile(_config, _state, **kwargs):
        calls.append(kwargs)
        return {"changed": [], "evidence": {}}

    monkeypatch.setattr(slack_app, "reconcile_system_jobs", fake_reconcile)

    slack_app._reconcile_slack_runtime_health_once(config)

    assert [call["channel_id"] for call in calls] == ["channel-a", "channel-b", "channel-fallback"]
    assert all(call["runtime_job_ids"] == {configured, fallback} for call in calls)
    assert all(call["authoritative"] is True for call in calls)


def test_slack_runtime_monitor_drops_queued_ghost_without_scheduler_evidence(tmp_path, monkeypatch):
    config = _config(tmp_path)
    state = BridgeState(str(tmp_path / "slack.sqlite3"))
    ghost = _job(state, channel_id="channel-fallback")
    monkeypatch.setattr(slack_app, "STATE", state)
    monkeypatch.setattr(slack_app, "ACTIVE_JOB_IDS", {ghost})
    monkeypatch.setattr(slack_app, "ACTIVE_JOB_CONTEXT", {ghost: ("channel-fallback", "coding_agent")})
    monkeypatch.setattr(slack_app, "ACTIVE_JOB_FUTURES", {})
    monkeypatch.setattr(slack_app, "ACTIVE_JOB_RETRY_TIMERS", {})
    monkeypatch.setattr(slack_app, "ACTIVE_JOB_CANCEL_REQUESTED_AT", {})
    monkeypatch.setattr(slack_app, "CANCELLED_JOB_IDS", set())
    monkeypatch.setattr(slack_app, "RECOVERY_REVIEW_JOB_IDS", set())
    monkeypatch.setattr(slack_app, "SLACK_CLIENT", None)
    monkeypatch.setattr(
        slack_app,
        "agent_job_process_status",
        lambda _job_id: {"registered": 0, "alive": 0, "exited": 0},
    )

    slack_app._reconcile_slack_runtime_health_once(config)

    assert ghost not in slack_app.ACTIVE_JOB_IDS
    assert ghost not in slack_app.ACTIVE_JOB_CONTEXT
    assert state.list_jobs(limit=1)[0]["status"] == "superseded"


def test_slack_watchdog_uses_absolute_attempt_deadline_even_with_live_worker_and_fresh_heartbeat(
    tmp_path,
    monkeypatch,
):
    config = _config(tmp_path)
    config.defaults.update(
        {
            "timeout_seconds": 30,
            "subagent_timeout_seconds": 0,
            "agent_runtime_attempt_deadline_grace_seconds": 30,
            "agent_job_hard_timeout_seconds": 60,
            "agent_runtime_cancel_grace_seconds": 15,
        }
    )
    state = BridgeState(str(tmp_path / "slack.sqlite3"))
    job_id = state.create_job(
        event_id="deadline",
        channel_id="channel-fallback",
        thread_ts="thread",
        user_id="operator",
        agent_name="coding_agent",
        request_text="bounded work",
    )
    assert state.mark_started(job_id, runtime_instance_id=slack_app.RUNTIME_INSTANCE_ID, stage="running")
    now = time.time()
    with sqlite3.connect(state.path) as db:
        db.execute(
            "UPDATE jobs SET started_at = ?, stage_updated_at = ?, heartbeat_at = ? WHERE id = ?",
            (now - 61, now, now, job_id),
        )

    future: Future[str] = Future()
    cancelled = []
    restarts = []
    monkeypatch.setattr(slack_app, "STATE", state)
    monkeypatch.setattr(slack_app, "ACTIVE_JOB_IDS", {job_id})
    monkeypatch.setattr(slack_app, "ACTIVE_JOB_CONTEXT", {job_id: ("channel-fallback", "coding_agent")})
    monkeypatch.setattr(slack_app, "ACTIVE_JOB_FUTURES", {job_id: future})
    monkeypatch.setattr(slack_app, "ACTIVE_JOB_RETRY_TIMERS", {})
    monkeypatch.setattr(slack_app, "ACTIVE_JOB_CANCEL_REQUESTED_AT", {})
    monkeypatch.setattr(slack_app, "CANCELLED_JOB_IDS", set())
    monkeypatch.setattr(slack_app, "RECOVERY_REVIEW_JOB_IDS", set())
    monkeypatch.setattr(slack_app, "SLACK_CLIENT", None)
    monkeypatch.setattr(
        slack_app,
        "agent_job_process_status",
        lambda _job_id: {"registered": 1, "alive": 1, "exited": 0},
    )
    monkeypatch.setattr(slack_app, "cancel_agent_job", lambda value: cancelled.append(value) or True)
    monkeypatch.setattr(slack_app, "_force_supervised_restart", restarts.append)
    monkeypatch.setattr(
        slack_app,
        "reconcile_system_jobs",
        lambda *_args, **_kwargs: {"changed": [], "evidence": {}},
    )

    slack_app._reconcile_slack_runtime_health_once(config)

    assert cancelled == [job_id]
    assert state.list_jobs(limit=1)[0]["runtime_stage"] == "cancelling_attempt_deadline"
    assert restarts == []

    slack_app.ACTIVE_JOB_CANCEL_REQUESTED_AT[job_id] = time.time() - 30
    slack_app._reconcile_slack_runtime_health_once(config)

    recovered = state.list_jobs(limit=1)[0]
    assert recovered["status"] == "queued"
    assert recovered["runtime_stage"] == "recovery_queued"
    assert recovered["recovery_policy"] == "same_surface_readback_first"
    assert restarts == ["stalled Slack worker did not exit after cancellation"]


def test_slack_progress_post_failure_still_submits_job(tmp_path, monkeypatch):
    state = BridgeState(str(tmp_path / "slack.sqlite3"))
    config = _config(tmp_path)
    config.defaults.update(
        {
            "allowed_user_ids": ["operator"],
            "max_context_messages": 0,
            "progress_message_enabled": True,
        }
    )
    route = ChannelRoute(channel_id="channel", agent_name="coding_agent", listen="all_messages")

    class Client:
        def chat_postMessage(self, **_kwargs):
            raise RuntimeError("Slack progress unavailable")

    class Executor:
        def __init__(self):
            self.calls = []

        def submit(self, *args):
            self.calls.append(args)
            return Future()

    executor = Executor()
    monkeypatch.setattr(slack_app, "STATE", state)
    monkeypatch.setattr(slack_app, "EXECUTOR", executor)
    monkeypatch.setattr(slack_app, "ACTIVE_JOB_IDS", set())
    monkeypatch.setattr(slack_app, "ACTIVE_JOB_CONTEXT", {})
    monkeypatch.setattr(slack_app, "ACTIVE_JOB_FUTURES", {})
    monkeypatch.setattr(slack_app, "ACTIVE_JOB_RETRY_TIMERS", {})
    monkeypatch.setattr(slack_app, "sign_trusted_message", lambda **_kwargs: "signed")

    slack_app._queue_request(
        config,
        route,
        {"event_id": "progress-failure"},
        {"channel": "channel", "user": "operator", "ts": "1.0", "text": "do work"},
        Client(),
    )

    row = state.list_jobs(limit=1)[0]
    job_id = int(row["id"])
    assert row["status"] == "queued"
    assert len(executor.calls) == 1
    assert job_id in slack_app.ACTIVE_JOB_IDS
    assert job_id in slack_app.ACTIVE_JOB_FUTURES


def test_active_request_equivalence_is_narrow_and_prefix_aware():
    base = "Please process the pending mailbox failures and mark each source read after verified remediation handoff"

    assert active_requests_equivalent(base, base.upper() + "!!!")
    assert active_requests_equivalent(base, base + " right away please")
    assert not active_requests_equivalent(base, "Please investigate the unrelated monthly billing reconciliation report")
    assert not active_requests_equivalent("check this request", "check this request for a different customer")


def test_slack_cross_channel_equivalent_active_request_does_not_start_second_writer(tmp_path, monkeypatch):
    state = BridgeState(str(tmp_path / "slack.sqlite3"))
    config = _config(tmp_path)
    config.defaults.update(
        {
            "allowed_user_ids": ["operator"],
            "max_context_messages": 0,
            "progress_message_enabled": False,
        }
    )
    coding_route = ChannelRoute(channel_id="coding-channel", agent_name="coding_agent", listen="all_messages")
    tickets_route = ChannelRoute(channel_id="tickets-channel", agent_name="tickets_agent", listen="all_messages")
    config.agents["tickets_agent"] = {"provider": "codex_cli", "workspace_root": str(tmp_path)}

    class Client:
        def __init__(self):
            self.posts = []

        def chat_postMessage(self, **kwargs):
            self.posts.append(kwargs)
            return {"ts": f"reply-{len(self.posts)}"}

    client = Client()
    submitted = []
    monkeypatch.setattr(slack_app, "STATE", state)
    monkeypatch.setattr(slack_app, "EXECUTOR", object())
    monkeypatch.setattr(slack_app, "ACTIVE_JOB_IDS", set())
    monkeypatch.setattr(slack_app, "ACTIVE_JOB_CONTEXT", {})
    monkeypatch.setattr(slack_app, "sign_trusted_message", lambda **_kwargs: "signed")
    monkeypatch.setattr(slack_app, "_collect_slack_context", lambda *_args: "")
    monkeypatch.setattr(slack_app, "_submit_slack_job_future", lambda *_args: submitted.append(_args[3]))

    base = "Please process the pending mailbox failures and mark each source read after verified remediation handoff"
    slack_app._queue_request(
        config,
        tickets_route,
        {"event_id": "first-event"},
        {"channel": "tickets-channel", "user": "operator", "ts": "10.0", "text": base},
        client,
    )
    slack_app._queue_request(
        config,
        coding_route,
        {"event_id": "second-event"},
        {"channel": "coding-channel", "user": "operator", "ts": "11.0", "text": base + " right away please"},
        client,
    )

    assert len(submitted) == 1
    assert len(state.list_jobs(limit=10)) == 1
    assert any("did not start a second writer" in post["text"] for post in client.posts)

    slack_app._queue_request(
        config,
        coding_route,
        {"event_id": "different-event"},
        {
            "channel": "coding-channel",
            "user": "operator",
            "ts": "12.0",
            "text": "Please investigate the unrelated monthly billing reconciliation report",
        },
        client,
    )

    assert len(submitted) == 2
    assert len(state.list_jobs(limit=10)) == 2


def test_generic_attachment_reuses_safe_same_user_intent_at_medium_effort(tmp_path, monkeypatch):
    state = BridgeState(str(tmp_path / "slack.sqlite3"))
    config = _config(tmp_path)
    config.defaults.update({"allowed_user_ids": ["operator"], "progress_message_enabled": False})
    route = ChannelRoute(channel_id="channel", agent_name="coding_agent", listen="all_messages")
    submitted = []
    monkeypatch.setattr(slack_app, "STATE", state)
    monkeypatch.setattr(slack_app, "EXECUTOR", object())
    monkeypatch.setattr(slack_app, "ACTIVE_JOB_IDS", set())
    monkeypatch.setattr(slack_app, "ACTIVE_JOB_CONTEXT", {})
    monkeypatch.setattr(slack_app, "sign_trusted_message", lambda **_kwargs: "signed")
    monkeypatch.setattr(
        slack_app,
        "_collect_slack_context",
        lambda *_args: "<@operator>: Please review and summarize this report",
    )
    monkeypatch.setattr(
        slack_app,
        "_submit_slack_job_future",
        lambda *_args: submitted.append(_args[3]),
    )

    slack_app._queue_request(
        config,
        route,
        {"event_id": "attachment-safe"},
        {
            "channel": "channel",
            "user": "operator",
            "ts": "3.0",
            "text": "Here is the file",
            "files": [{"id": "F1", "name": "report.pdf", "mimetype": "application/pdf"}],
        },
        object(),
    )

    assert len(submitted) == 1
    request = submitted[0]
    assert request.text == "Here is the file"
    assert request.task_kind == "slack-attachment-readonly"
    assert request.task_text == "Please review and summarize this report"
    assert "does not authorize writes" in request.context


def test_ambiguous_attachment_requests_clarification_once_without_agent_job(tmp_path, monkeypatch):
    state = BridgeState(str(tmp_path / "slack.sqlite3"))
    config = _config(tmp_path)
    config.defaults.update({"allowed_user_ids": ["operator"], "progress_message_enabled": False})
    route = ChannelRoute(channel_id="channel", agent_name="coding_agent", listen="all_messages")

    class Client:
        def __init__(self):
            self.posts = []

        def chat_postMessage(self, **kwargs):
            self.posts.append(kwargs)
            return {"ts": "reply"}

    client = Client()
    monkeypatch.setattr(slack_app, "STATE", state)
    monkeypatch.setattr(slack_app, "EXECUTOR", object())
    monkeypatch.setattr(slack_app, "_collect_slack_context", lambda *_args: "")

    event = {
        "channel": "channel",
        "user": "operator",
        "ts": "4.0",
        "text": "Here is the file",
        "files": [{"id": "F2", "name": "report.pdf", "mimetype": "application/pdf"}],
    }
    slack_app._queue_request(config, route, {"event_id": "attachment-ambiguous"}, event, client)
    slack_app._queue_request(config, route, {"event_id": "attachment-ambiguous"}, event, client)

    assert len(client.posts) == 1
    assert "specific task" in client.posts[0]["text"]
    assert state.list_jobs(limit=10) == []


def test_slack_executor_submit_failure_requeues_job_and_clears_scheduler_state(tmp_path, monkeypatch):
    state = BridgeState(str(tmp_path / "slack.sqlite3"))
    config = _config(tmp_path)
    config.defaults.update(
        {
            "allowed_user_ids": ["operator"],
            "max_context_messages": 0,
            "progress_message_enabled": False,
        }
    )
    route = ChannelRoute(channel_id="channel", agent_name="coding_agent", listen="all_messages")

    class Executor:
        def submit(self, *_args):
            raise RuntimeError("executor stopped")

    monkeypatch.setattr(slack_app, "STATE", state)
    monkeypatch.setattr(slack_app, "EXECUTOR", Executor())
    monkeypatch.setattr(slack_app, "ACTIVE_JOB_IDS", set())
    monkeypatch.setattr(slack_app, "ACTIVE_JOB_CONTEXT", {})
    monkeypatch.setattr(slack_app, "ACTIVE_JOB_FUTURES", {})
    monkeypatch.setattr(slack_app, "ACTIVE_JOB_RETRY_TIMERS", {})
    monkeypatch.setattr(slack_app, "ACTIVE_JOB_CANCEL_REQUESTED_AT", {})
    monkeypatch.setattr(slack_app, "CANCELLED_JOB_IDS", set())
    monkeypatch.setattr(slack_app, "RECOVERY_REVIEW_JOB_IDS", set())
    monkeypatch.setattr(slack_app, "sign_trusted_message", lambda **_kwargs: "signed")

    slack_app._queue_request(
        config,
        route,
        {"event_id": "submit-failure"},
        {"channel": "channel", "user": "operator", "ts": "2.0", "text": "do work"},
        object(),
    )

    row = state.list_jobs(limit=1)[0]
    job_id = int(row["id"])
    assert row["status"] == "queued"
    assert row["runtime_stage"] == "recovery_queued"
    assert row["recovery_policy"] == "same_surface_readback_first"
    assert "executor stopped" in str(row["reconciliation_reason"])
    assert job_id not in slack_app.ACTIVE_JOB_IDS
    assert job_id not in slack_app.ACTIVE_JOB_CONTEXT
    assert job_id not in slack_app.ACTIVE_JOB_FUTURES


def test_slack_heartbeat_reports_health_without_posting_messages():
    class Client:
        def __init__(self):
            self.calls = 0

        def auth_test(self):
            self.calls += 1
            return {"ok": True}

    client = Client()
    slack = type("Slack", (), {"client": client})()

    assert slack_app._slack_heartbeat_once(slack) is True
    assert client.calls == 1


def test_slack_heartbeat_failure_is_nonfatal():
    class Client:
        def auth_test(self):
            raise RuntimeError("transport unavailable")

    slack = type("Slack", (), {"client": Client()})()

    assert slack_app._slack_heartbeat_once(slack) is False


def test_slack_recovery_replays_durable_queued_job_once(tmp_path, monkeypatch):
    state = BridgeState(str(tmp_path / "bridge.sqlite3"))
    job_id = state.create_job(
        event_id="recover-once",
        channel_id="channel-fallback",
        thread_ts="thread",
        user_id="operator",
        agent_name="coding_agent",
        request_text="safe queued request",
        recovery_policy="queued_replay",
    )
    config = _config(tmp_path)

    class Client:
        def chat_postMessage(self, **kwargs):
            return {"ts": "progress"}

    submitted = []
    monkeypatch.setattr(slack_app, "STATE", state)
    monkeypatch.setattr(slack_app, "EXECUTOR", object())
    monkeypatch.setattr(slack_app, "ACTIVE_JOB_IDS", set())
    monkeypatch.setattr(slack_app, "ACTIVE_JOB_CONTEXT", {})
    monkeypatch.setattr(slack_app, "ACTIVE_JOB_FUTURES", {})
    monkeypatch.setattr(slack_app, "sign_trusted_message", lambda **kwargs: "signed")
    monkeypatch.setattr(
        slack_app,
        "_submit_slack_job_future",
        lambda *args: submitted.append(args[3]),
    )

    assert slack_app._recover_queued_slack_jobs(config, Client()) == 1
    assert slack_app._recover_queued_slack_jobs(config, Client()) == 0
    assert [request.job_id for request in submitted] == [job_id]
    row = state.list_jobs(statuses={"queued"}, limit=10)[0]
    assert row["runtime_stage"] == "recovered_waiting_lane"


def test_slack_startup_reconciliation_runs_once_after_session_grace(tmp_path, monkeypatch):
    config = _config(tmp_path)
    sleeps = []
    reconciled = []
    monkeypatch.setattr(slack_app.time, "sleep", lambda seconds: sleeps.append(seconds))
    monkeypatch.setattr(slack_app, "_reconcile_slack_runtime_health_once", lambda value: reconciled.append(value))

    slack_app._slack_startup_reconciliation_once(config)

    assert sleeps == [305.0]
    assert reconciled == [config]


def test_slack_bridge_instance_guard_rejects_duplicate_on_windows():
    if os.name != "nt":
        return
    guard_type = slack_app.SlackBridgeSingleInstanceGuard
    original_name = guard_type.MUTEX_NAME
    guard_type.MUTEX_NAME = rf"Local\CodexSlackBridgeTest_{os.getpid()}"
    first = guard_type()
    try:
        try:
            guard_type()
        except RuntimeError:
            pass
        else:
            raise AssertionError("duplicate Slack bridge instance was accepted")
    finally:
        first.close()
        replacement = guard_type()
        replacement.close()
        guard_type.MUTEX_NAME = original_name


def test_terminal_helpers_are_idempotent_and_channel_scope_is_respected(tmp_path):
    state = BridgeState(str(tmp_path / "bridge.sqlite3"))
    command_center = _job(state)
    slack = _job(state, channel_id="C123")

    state.mark_superseded(command_center, "coalesced")
    state.mark_interrupted(command_center, "must not overwrite terminal state")
    state.reconcile_active_jobs(
        live_job_ids=set(),
        authoritative=True,
        channel_id="command_center",
        stale_after_seconds=0,
        now=1_000_000,
    )

    rows = {int(row["id"]): row for row in state.list_jobs(limit=10)}
    assert rows[command_center]["status"] == "superseded"
    assert rows[command_center]["reconciliation_reason"] == "coalesced"
    assert rows[slack]["status"] == "queued"


def test_typed_non_success_outcomes_do_not_require_review_by_default(tmp_path):
    state = BridgeState(str(tmp_path / "bridge.sqlite3"))
    expected_results = {
        "blocked": "BLOCKED — waiting on the customer",
        "completed_with_issues": "COMPLETED_WITH_ISSUES — follow-up is still required",
        "failed": "FAILED — worker task failed",
    }

    job_ids = {}
    for status, result_text in expected_results.items():
        job_id = _job(state, status="running")
        job_ids[status] = job_id
        assert state.mark_outcome(
            job_id,
            status,
            result_text=result_text,
            review_reason=result_text,
            learning_eligible=True,
        ) is True

    rows = {int(row["id"]): row for row in state.list_jobs(limit=10)}
    review_ids = {int(row["id"]) for row in state.list_review_jobs(limit=10)}
    for status, job_id in job_ids.items():
        row = rows[job_id]
        assert row["status"] == status
        assert row["result_text"] == expected_results[status]
        assert row["needs_review"] is False
        assert row["review_status"] == ""
        assert row["review_reason"] == ""
        assert row["learning_eligible"] is False
        assert job_id not in review_ids


@pytest.mark.parametrize("status", ["blocked", "completed_with_issues"])
def test_typed_non_success_outcome_can_explicitly_opt_in_to_review(tmp_path, status):
    state = BridgeState(str(tmp_path / f"{status}.sqlite3"))
    job_id = _job(state, status="running")
    result_text = f"{status.upper()} — operator decision required"

    assert state.mark_outcome(
        job_id,
        status,
        result_text=result_text,
        review_reason="Operator must approve the verified action.",
        review_required=True,
    ) is True

    row = next(row for row in state.list_jobs(limit=10) if int(row["id"]) == job_id)
    assert row["status"] == status
    assert row["needs_review"] is True
    assert row["review_status"] == "needs_review"
    assert row["review_reason"] == "Operator must approve the verified action."
    assert [int(review["id"]) for review in state.list_review_jobs(limit=10)] == [job_id]


def test_failed_outcome_cannot_create_a_review_task_even_when_requested(tmp_path):
    state = BridgeState(str(tmp_path / "failed.sqlite3"))
    reported_failure_id = _job(state, status="running")
    worker_failure_id = _job(state, status="running")

    assert state.mark_outcome(
        reported_failure_id,
        "failed",
        result_text="FAILED\nWorker could not complete the original instruction.",
        review_reason="Do not convert this into a separate task.",
        review_required=True,
    ) is True
    assert state.mark_failed(
        worker_failure_id,
        "Worker crashed while handling the original instruction.",
        review_required=True,
    ) is True

    rows = {int(row["id"]): row for row in state.list_jobs(limit=10)}
    for job_id in (reported_failure_id, worker_failure_id):
        assert rows[job_id]["status"] == "failed"
        assert rows[job_id]["needs_review"] is False
        assert rows[job_id]["review_status"] == ""
        assert rows[job_id]["review_reason"] == ""
    assert state.list_review_jobs(limit=10) == []


def test_non_actionable_terminal_outcomes_stay_out_of_review_after_reopen(tmp_path):
    path = tmp_path / "terminal-reopen.sqlite3"
    state = BridgeState(str(path))
    job_ids = []
    for status in ("blocked", "completed_with_issues", "failed", "unclassified"):
        job_id = _job(state, status="running")
        job_ids.append(job_id)
        assert state.mark_outcome(
            job_id,
            status,
            result_text=f"{status.upper()}\nOPERATOR_ACTION_REQUIRED: NONE",
        ) is True

    reopened = BridgeState(str(path))
    rows = {int(row["id"]): row for row in reopened.list_jobs(limit=20)}
    assert reopened.list_review_jobs(limit=20) == []
    assert all(rows[job_id]["needs_review"] is False for job_id in job_ids)


def test_same_status_reclassification_can_clear_an_obsolete_review_flag(tmp_path):
    state = BridgeState(str(tmp_path / "same-status.sqlite3"))
    job_id = _job(state, status="running")
    assert state.mark_outcome(
        job_id,
        "completed_with_issues",
        result_text="COMPLETED_WITH_ISSUES\nOPERATOR_ACTION_REQUIRED: NONE",
        review_reason="legacy blanket review",
        review_required=True,
    ) is True

    assert state.reclassify_completed_outcome(
        job_id,
        "completed_with_issues",
        result_text="COMPLETED_WITH_ISSUES\nOPERATOR_ACTION_REQUIRED: NONE",
        review_required=False,
    ) is True
    row = next(row for row in state.list_jobs(limit=10) if int(row["id"]) == job_id)
    assert row["needs_review"] is False
    assert row["review_status"] == "resolved"
    assert row["review_resolution"].startswith("Automatically resolved:")


def test_direct_chat_terminal_outcomes_can_be_recorded_without_review_packets(tmp_path):
    state = BridgeState(str(tmp_path / "bridge.sqlite3"))
    blocked_id = _job(state, status="running")
    failed_id = _job(state, status="running")

    assert state.mark_outcome(
        blocked_id,
        "blocked",
        result_text="BLOCKED\nReported in the originating chat.",
        review_reason="Reported in chat only.",
    ) is True
    assert state.mark_failed(
        failed_id,
        "Worker could not start.",
    ) is True

    rows = {int(row["id"]): row for row in state.list_jobs(limit=10)}
    assert rows[blocked_id]["status"] == "blocked"
    assert rows[failed_id]["status"] == "failed"
    assert rows[blocked_id]["needs_review"] is False
    assert rows[failed_id]["needs_review"] is False
    assert rows[blocked_id]["review_reason"] == ""
    assert rows[failed_id]["review_reason"] == ""
    assert state.list_review_jobs(limit=10) == []


def test_completed_unverified_outcome_is_not_learning_eligible(tmp_path):
    state = BridgeState(str(tmp_path / "bridge.sqlite3"))
    job_id = _job(state, status="running")

    assert state.mark_outcome(
        job_id,
        "completed",
        result_text="COMPLETED — agent reported completion",
        learning_eligible=False,
    ) is True

    row = next(row for row in state.list_jobs(limit=10) if int(row["id"]) == job_id)
    assert row["status"] == "completed"
    assert row["needs_review"] is False
    assert row["learning_eligible"] is False
    assert all(int(review["id"]) != job_id for review in state.list_review_jobs(limit=10))


def test_resolved_review_survives_state_reopen(tmp_path):
    path = tmp_path / "bridge.sqlite3"
    state = BridgeState(str(path))
    job_id = _job(state, status="running")
    assert state.mark_outcome(
        job_id,
        "blocked",
        result_text="BLOCKED — dependency unavailable",
        review_reason="dependency unavailable",
        review_required=True,
    ) is True
    assert state.mark_review_resolved(job_id, resolution="Operator verified the dependency was restored.") is True

    reopened = BridgeState(str(path))
    row = next(row for row in reopened.list_jobs(limit=10) if int(row["id"]) == job_id)
    assert row["status"] == "blocked"
    assert row["needs_review"] is False
    assert row["review_status"] == "resolved"
    assert row["reviewed_at"] is not None
    assert row["review_resolution"] == "Operator verified the dependency was restored."
    assert all(int(review["id"]) != job_id for review in reopened.list_review_jobs(limit=10))


def test_legacy_interrupted_job_is_backfilled_for_review(tmp_path):
    path = tmp_path / "bridge.sqlite3"
    state = BridgeState(str(path))
    job_id = _job(state, status="running")
    with sqlite3.connect(path) as db:
        db.execute(
            """
            UPDATE jobs
            SET status='interrupted', completed_at=?, reconciliation_reason=?,
                needs_review=0, review_reason='', review_status='', reviewed_at=NULL
            WHERE id=?
            """,
            (time.time(), "No live runtime evidence remained.", job_id),
        )

    reopened = BridgeState(str(path))
    row = next(row for row in reopened.list_review_jobs(limit=10) if int(row["id"]) == job_id)
    assert row["status"] == "interrupted"
    assert row["needs_review"] is True
    assert row["review_status"] == "needs_review"
    assert row["review_reason"] == "No live runtime evidence remained."


def test_existing_review_rows_are_baselined_once_without_hiding_new_reviews(tmp_path):
    path = tmp_path / "bridge.sqlite3"
    state = BridgeState(str(path))
    legacy_job_id = _job(state, status="running")
    assert state.mark_outcome(
        legacy_job_id,
        "completed_with_issues",
        result_text="COMPLETED_WITH_ISSUES - historical run",
        review_reason="historical run",
        review_required=True,
    ) is True

    with sqlite3.connect(path) as db:
        db.execute("DELETE FROM state_migrations WHERE name = 'needs_review_live_baseline_v1'")

    reopened = BridgeState(str(path))
    legacy_row = next(row for row in reopened.list_jobs(limit=10) if int(row["id"]) == legacy_job_id)
    assert legacy_row["needs_review"] is False
    assert legacy_row["review_status"] == "resolved"
    assert legacy_row["reviewed_at"] is not None

    new_job_id = _job(reopened, status="running")
    assert reopened.mark_outcome(
        new_job_id,
        "blocked",
        result_text="BLOCKED - new dependency",
        review_reason="new dependency",
        review_required=True,
    ) is True
    reopened_again = BridgeState(str(path))
    review_ids = {int(row["id"]) for row in reopened_again.list_review_jobs(limit=10)}
    assert legacy_job_id not in review_ids
    assert new_job_id in review_ids


def test_review_followup_compare_and_set_rejects_stale_version_and_child(tmp_path):
    state = BridgeState(str(tmp_path / "bridge.sqlite3"))
    parent_id = _job(state, status="running")
    assert state.mark_outcome(
        parent_id,
        "blocked",
        result_text="BLOCKED — first dependency",
        review_reason="first dependency",
        review_required=True,
    ) is True
    first_child_id = _job(state)
    second_child_id = _job(state)

    assert state.mark_review_followup_queued(
        parent_id,
        first_child_id,
        expected_review_version=0,
    ) is True
    assert state.mark_review_followup_queued(
        parent_id,
        second_child_id,
        expected_review_version=0,
    ) is False
    assert state.record_review_followup(
        parent_id,
        child_job_id=second_child_id,
        child_status="failed",
        result_text="FAILED — wrong child",
        expected_review_version=0,
    ) is False

    assert state.mark_started(first_child_id) is True
    assert state.mark_outcome(
        first_child_id,
        "completed",
        result_text="COMPLETED — first follow-up finished",
    ) is True
    assert state.record_review_followup(
        parent_id,
        child_job_id=first_child_id,
        child_status="completed",
        result_text="COMPLETED — first follow-up finished",
        expected_review_version=0,
    ) is True

    assert state.mark_review_followup_queued(
        parent_id,
        second_child_id,
        expected_review_version=0,
    ) is False
    assert state.mark_review_followup_queued(
        parent_id,
        second_child_id,
        expected_review_version=1,
    ) is True
    assert state.record_review_followup(
        parent_id,
        child_job_id=first_child_id,
        child_status="completed",
        result_text="COMPLETED — stale child replay",
        expected_review_version=1,
    ) is False
    assert state.record_review_followup(
        parent_id,
        child_job_id=second_child_id,
        child_status="failed",
        result_text="FAILED — stale version replay",
        expected_review_version=0,
    ) is False

    parent = next(row for row in state.list_review_jobs(limit=10) if int(row["id"]) == parent_id)
    assert parent["review_version"] == 1
    assert parent["active_followup_job_id"] == second_child_id
    assert parent["last_followup_job_id"] == first_child_id
