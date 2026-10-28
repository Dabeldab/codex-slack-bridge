# AgentChat/direct_codex 2026-07-14T02:35:00-04:00: verify dedicated inbox-lane admission.
# AgentChat/coding_agent 2026-07-14T17:45:00-04:00: verify disabled billing reconciliation cannot dispatch or recover.
# AgentChat/direct_codex 2026-07-14T18:21:07-04:00: verify retired reconciliation cannot be re-enabled or submitted.
# AgentChat/direct_codex 2026-07-28T19:00:00-04:00: verify proactive ticket jobs are source-bound read-only.
# AgentChat/coding_agent 2026-07-30T17:15:00Z: verify bounded worker and restart recovery.
from __future__ import annotations

import json
import time
import urllib.request
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer
from pathlib import Path
from threading import Event, Lock, Thread, current_thread
from types import SimpleNamespace

import codex_slack_bridge.command_center_server as command_center_server
from codex_slack_bridge.command_center_server import (
    CommandCenterRuntime,
    RESTART_RECOVERY_WARNING,
    make_handler,
)


def test_active_salesforce_resource_checks_batched_account_ids():
    runtime = object.__new__(CommandCenterRuntime)
    runtime._lock = Lock()
    runtime._jobs = {
        "batch": {
            "status": "queued",
            "payload": {"accountId": "", "accountIds": ["001first", "001second"]},
        }
    }

    assert runtime._active_salesforce_resource("001second")
    assert not runtime._active_salesforce_resource("001missing")


def test_salesforce_billing_dispatch_stays_retired_even_if_legacy_config_is_true():
    class Ledger:
        def __init__(self):
            self.retired = 0

        def dispatchable_tickets(self):
            return []

        def retire_billing_work(self):
            self.retired += 1
            return 33

    runtime = object.__new__(CommandCenterRuntime)
    runtime._lock = Lock()
    runtime._jobs = {}
    runtime.salesforce_work_ledger = Ledger()
    runtime.config = SimpleNamespace(
        defaults={"ops_salesforce_billing_reconciliation_enabled": True}, agents={}
    )
    runtime.submit_prompt = lambda **_kwargs: (_ for _ in ()).throw(AssertionError("must not dispatch"))

    assert runtime._dispatch_salesforce_work() == (0, 0)
    assert runtime.salesforce_work_ledger.retired == 1


def test_disabled_salesforce_billing_dispatch_retires_backlog():
    class Ledger:
        def __init__(self):
            self.retired = 0

        def dispatchable_tickets(self):
            return []

        def retire_billing_work(self):
            self.retired += 1
            return 4

    runtime = object.__new__(CommandCenterRuntime)
    runtime._lock = Lock()
    runtime._jobs = {}
    runtime.salesforce_work_ledger = Ledger()
    runtime.config = SimpleNamespace(
        defaults={"ops_salesforce_billing_reconciliation_enabled": False}, agents={}
    )
    runtime.submit_prompt = lambda **_kwargs: (_ for _ in ()).throw(AssertionError("must not dispatch"))

    assert runtime._dispatch_salesforce_work() == (0, 0)
    assert runtime.salesforce_work_ledger.retired == 1


def test_retired_billing_reconciliation_source_is_rejected_before_job_creation(tmp_path):
    runtime = _runtime(tmp_path)
    runtime.config = SimpleNamespace(defaults={}, agents={"billing_agent": {}})
    try:
        result = runtime.submit_prompt(
            agent_name="billing_agent",
            prompt="legacy reconciliation",
            payload={"type": "salesforce-billing-location-reconciliation"},
            source_type="ops-salesforce-billing-reconciliation",
        )
        assert result == {
            "accepted": False,
            "message": "source_retired",
            "agentName": "billing_agent",
            "sourceType": "ops-salesforce-billing-reconciliation",
        }
        assert runtime._jobs == {}
        assert list(runtime.jobs_dir.glob("*.json")) == []
    finally:
        runtime.executor.shutdown(wait=True)

# AgentChat/coding_agent 2026-07-11T11:32:00-04:00
# AgentChat/direct_codex 2026-07-13T00:16:00-04:00
# AgentChat/coding_agent 2026-07-13T00:52:00-04:00


class _State:
    def __init__(self) -> None:
        self.transitions: list[tuple[str, int]] = []
        self.rows: dict[int, dict] = {}
        self.start_allowed = True
        self.finalization_claim_allowed = True
        self.outcome_allowed = True
        self.review_required: dict[int, bool | None] = {}

    def mark_started(self, job_id: int, **_kwargs) -> bool:
        self.transitions.append(("running", job_id))
        return self.start_allowed

    def mark_completed(self, job_id: int, **_kwargs) -> bool:
        self.transitions.append(("completed", job_id))
        if job_id in self.rows:
            self.rows[job_id]["status"] = "completed"
        return True

    def mark_outcome(self, job_id: int, status: str, **_kwargs) -> bool:
        self.transitions.append((status, job_id))
        self.review_required[job_id] = _kwargs.get("review_required")
        if not self.outcome_allowed:
            return False
        if job_id in self.rows:
            self.rows[job_id]["status"] = status
        return True

    def update_runtime_stage(self, job_id: int, stage: str, **_kwargs) -> bool:
        self.transitions.append((stage, job_id))
        return self.finalization_claim_allowed

    def mark_failed(self, job_id: int, _error: str, **_kwargs) -> bool:
        self.transitions.append(("failed", job_id))
        self.review_required[job_id] = _kwargs.get("review_required")
        if job_id in self.rows:
            self.rows[job_id]["status"] = "failed"
        return True

    def mark_recovery_review_required(self, job_id: int, _reason: str) -> None:
        self.transitions.append(("recovery_review_required", job_id))
        if job_id in self.rows:
            self.rows[job_id]["status"] = "recovery_review_required"

    def requeue_for_recovery(
        self,
        job_id: int,
        _reason: str,
        *,
        recovery_policy: str = "same_surface_readback_first",
        **_kwargs,
    ) -> bool:
        self.transitions.append(("recovery_queued", job_id))
        if job_id in self.rows:
            self.rows[job_id]["status"] = "queued"
            self.rows[job_id]["runtime_stage"] = "recovery_queued"
            self.rows[job_id]["recovery_policy"] = recovery_policy
            self.rows[job_id]["recovery_count"] = int(
                self.rows[job_id].get("recovery_count") or 0
            ) + 1
        return True

    def heartbeat_job(self, _job_id: int, **_kwargs) -> bool:
        return True

    def mark_cancelled(self, job_id: int, _reason: str) -> None:
        self.transitions.append(("cancelled", job_id))
        if job_id in self.rows:
            self.rows[job_id]["status"] = "cancelled"

    def jobs_by_ids(self, job_ids: set[int]) -> dict[int, dict]:
        return {job_id: dict(self.rows[job_id]) for job_id in job_ids if job_id in self.rows}

    def job_by_event_id(self, event_id: str) -> dict | None:
        for row in self.rows.values():
            if str(row.get("event_id") or "") == str(event_id or ""):
                return dict(row)
        return None

    def list_jobs(self, *, statuses: set[str] | None = None, limit: int = 50) -> list[dict]:
        rows = list(self.rows.values())
        if statuses:
            rows = [row for row in rows if str(row.get("status") or "") in statuses]
        return [dict(row) for row in rows[:limit]]


def _runtime(tmp_path: Path, *, max_workers: int = 2) -> CommandCenterRuntime:
    runtime = object.__new__(CommandCenterRuntime)
    runtime.instance_id = "test-runtime"
    runtime.max_workers = max_workers
    runtime.executor = ThreadPoolExecutor(max_workers=max_workers)
    runtime.jobs_dir = tmp_path / "jobs"
    runtime.jobs_dir.mkdir(parents=True, exist_ok=True)
    runtime.pause_manifest_path = tmp_path / "restart_manifest.json"
    runtime._jobs = {}
    runtime._futures = {}
    runtime._watchdog_no_child_seen_at = {}
    runtime._watchdog_cancel_requested_at = {}
    runtime._lock = Lock()
    runtime._lane_queues = {}
    runtime._lane_running = set()
    runtime._work_items = {}
    runtime._inflight_count = 0
    runtime._background_inflight_count = 0
    runtime._queue_sequence = 0
    runtime._paused = False
    runtime._recovering_manifest = False
    runtime._pause_manifest = {}
    runtime._watch_stop = Event()
    runtime.state = _State()
    runtime.config = SimpleNamespace(defaults={}, agents={})
    return runtime


def _add_job(
    runtime: CommandCenterRuntime,
    job_id: str,
    agent_name: str,
    *,
    source_type: str = "dispatch",
    payload: dict | None = None,
    status: str = "queued",
) -> None:
    record = {
        "id": job_id,
        "bridgeJobId": len(runtime._jobs) + 1,
        "status": status,
        "phase": status,
        "agentName": agent_name,
        "sourceType": source_type,
        "createdAtUtc": "2026-07-10T12:00:00+00:00",
        "updatedAtUtc": "2026-07-10T12:00:00+00:00",
        "payload": payload or {},
        "prompt": f"run {job_id}",
        "runnerType": "agent",
    }
    runtime._jobs[job_id] = record
    runtime._write_job(record)
    runtime._schedule_job(job_id, {"runnerType": "agent"})


def _wait_for(predicate, timeout: float = 2.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("condition was not reached before timeout")


def test_runtime_monitor_does_not_treat_completed_future_as_live(tmp_path, monkeypatch):
    runtime = _runtime(tmp_path)
    runtime._jobs = {
        "live": {"id": "live", "bridgeJobId": 11, "status": "running"},
        "dead": {"id": "dead", "bridgeJobId": 12, "status": "running"},
    }
    live_future: Future[str] = Future()
    dead_future: Future[str] = Future()
    dead_future.set_result("done")
    runtime._futures = {"live": live_future, "dead": dead_future}
    captured = {}

    def fake_reconcile(_config, _state, **kwargs):
        captured.update(kwargs)
        return {"changed": [], "evidence": {}}

    monkeypatch.setattr("codex_slack_bridge.command_center_server.reconcile_system_jobs", fake_reconcile)
    monkeypatch.setattr(
        "codex_slack_bridge.command_center_server.agent_job_process_status",
        lambda job_id: {"registered": 1, "alive": 1 if job_id == 11 else 0, "exited": 0},
    )

    runtime._reconcile_runtime_health(60)

    assert captured["runtime_job_ids"] == {11}
    assert captured["authoritative"] is True
    runtime.executor.shutdown(wait=True)


def test_runtime_monitor_repairs_stale_admission_state_and_rekicks_waiters(tmp_path):
    runtime = _runtime(tmp_path, max_workers=2)
    live_future: Future[str] = Future()
    runtime._jobs = {
        "live": {
            "id": "live",
            "status": "running",
            "agentName": "coding_agent",
            "sourceType": "agent-direct-chat",
            "laneKey": "coding_agent:interactive",
            "laneClass": "interactive",
        },
        "refresh": {
            "id": "refresh",
            "status": "queued",
            "phase": "waiting_agent_lane",
            "agentName": "tickets_agent",
            "sourceType": "ops-ticket-refresh",
            "laneKey": "tickets_agent:background",
            "laneClass": "background",
        },
    }
    runtime._futures = {"live": live_future}
    runtime._lane_queues = {"tickets_agent:background": ["refresh"]}
    runtime._lane_running = {"tickets_agent:background", "ghost:interactive"}
    runtime._inflight_count = 3
    runtime._background_inflight_count = 2
    dispatches: list[bool] = []
    runtime._dispatch_ready_jobs = lambda: dispatches.append(True)

    result = runtime._reconcile_scheduler_admission_bookkeeping()

    assert result["changed"] is True
    assert result["queuedJobs"] == 1
    assert result["staleLanesRemoved"] == ["ghost:interactive", "tickets_agent:background"]
    assert result["missingLanesRestored"] == ["coding_agent:interactive"]
    assert runtime._lane_running == {"coding_agent:interactive"}
    assert runtime._inflight_count == 1
    assert runtime._background_inflight_count == 0
    assert dispatches == [True]
    runtime.executor.shutdown(wait=True)


def test_runtime_monitor_fences_dead_child_then_requests_supervised_restart(tmp_path, monkeypatch):
    runtime = _runtime(tmp_path)
    old = "2026-07-10T12:00:00+00:00"
    runtime._jobs = {
        "stalled": {
            "id": "stalled",
            "bridgeJobId": 41,
            "status": "running",
            "phase": "running_model",
            "agentName": "agent_a",
            "laneKey": "agent_a:interactive",
            "runnerType": "agent",
            "admittedAtUtc": old,
            "updatedAtUtc": old,
        }
    }
    future: Future[str] = Future()
    runtime._futures = {"stalled": future}
    cancelled: list[int] = []
    restarts: list[str] = []
    monkeypatch.setattr(
        "codex_slack_bridge.command_center_server.agent_job_process_status",
        lambda _job_id: {"registered": 1, "alive": 0, "exited": 1},
    )
    monkeypatch.setattr(
        "codex_slack_bridge.command_center_server.cancel_agent_job",
        lambda job_id: cancelled.append(job_id) or True,
    )
    monkeypatch.setattr(
        "codex_slack_bridge.command_center_server.reconcile_system_jobs",
        lambda *_args, **_kwargs: {"changed": [], "evidence": {}},
    )
    monkeypatch.setattr(runtime, "_force_supervised_restart", restarts.append)

    runtime._reconcile_runtime_health(30)
    assert cancelled == []
    assert runtime._jobs["stalled"]["phase"] == "running_model"

    runtime._watchdog_no_child_seen_at["stalled"] = time.time() - 30
    runtime._reconcile_runtime_health(30)
    assert cancelled == [41]
    assert runtime._jobs["stalled"]["phase"] == "cancelling_dead_or_stalled_worker"
    assert restarts == []

    runtime._watchdog_cancel_requested_at["stalled"] = time.time() - 60
    runtime._reconcile_runtime_health(30)
    assert runtime._jobs["stalled"]["status"] == "queued"
    assert runtime._jobs["stalled"]["phase"] == "restart_recovery_queued"
    assert ("recovery_queued", 41) in runtime.state.transitions
    assert restarts == ["stalled command-center worker did not exit after cancellation"]
    future.set_result("stopped")
    runtime.executor.shutdown(wait=True)


def test_runtime_monitor_allows_normal_result_drain_after_worker_exit(tmp_path, monkeypatch):
    runtime = _runtime(tmp_path)
    old = "2026-07-10T12:00:00+00:00"
    runtime._jobs = {
        "finishing": {
            "id": "finishing",
            "bridgeJobId": 42,
            "status": "running",
            "phase": "running_model",
            "agentName": "agent_a",
            "laneKey": "agent_a:interactive",
            "runnerType": "agent",
            "admittedAtUtc": old,
            "updatedAtUtc": old,
        }
    }
    future: Future[str] = Future()
    runtime._futures = {"finishing": future}
    cancelled: list[int] = []
    monkeypatch.setattr(
        "codex_slack_bridge.command_center_server.agent_job_process_status",
        lambda _job_id: {"registered": 0, "alive": 0, "exited": 0},
    )
    monkeypatch.setattr(
        "codex_slack_bridge.command_center_server.cancel_agent_job",
        lambda job_id: cancelled.append(job_id) or True,
    )
    monkeypatch.setattr(
        "codex_slack_bridge.command_center_server.reconcile_system_jobs",
        lambda *_args, **_kwargs: {"changed": [], "evidence": {}},
    )

    runtime._reconcile_runtime_health(30)

    assert cancelled == []
    assert "finishing" in runtime._watchdog_no_child_seen_at
    assert runtime._jobs["finishing"]["phase"] == "running_model"

    future.set_result("COMPLETED")
    runtime._reconcile_runtime_health(30)

    assert cancelled == []
    assert "finishing" not in runtime._watchdog_no_child_seen_at
    assert "finishing" not in runtime._watchdog_cancel_requested_at
    runtime.executor.shutdown(wait=True)


def test_runtime_monitor_never_fences_terminal_job_with_pending_finalizers(tmp_path, monkeypatch):
    runtime = _runtime(tmp_path)
    old = "2026-07-10T12:00:00+00:00"
    runtime._jobs = {
        "finalizing": {
            "id": "finalizing",
            "bridgeJobId": 43,
            "status": "completed",
            "phase": "completed",
            "agentName": "agent_a",
            "laneKey": "agent_a:interactive",
            "runnerType": "agent",
            "admittedAtUtc": old,
            "updatedAtUtc": old,
        }
    }
    future: Future[str] = Future()
    runtime._futures = {"finalizing": future}
    runtime._watchdog_no_child_seen_at["finalizing"] = time.time() - 300
    runtime._watchdog_cancel_requested_at["finalizing"] = time.time() - 300
    cancelled: list[int] = []
    monkeypatch.setattr(
        "codex_slack_bridge.command_center_server.agent_job_process_status",
        lambda _job_id: {"registered": 0, "alive": 0, "exited": 0},
    )
    monkeypatch.setattr(
        "codex_slack_bridge.command_center_server.cancel_agent_job",
        lambda job_id: cancelled.append(job_id) or True,
    )
    monkeypatch.setattr(
        "codex_slack_bridge.command_center_server.reconcile_system_jobs",
        lambda *_args, **_kwargs: {"changed": [], "evidence": {}},
    )

    runtime._reconcile_runtime_health(30)

    assert cancelled == []
    assert runtime._jobs["finalizing"]["status"] == "completed"
    assert "finalizing" not in runtime._watchdog_no_child_seen_at
    assert "finalizing" not in runtime._watchdog_cancel_requested_at
    future.set_result("COMPLETED")
    runtime.executor.shutdown(wait=True)


def test_same_agent_waiters_do_not_consume_global_workers(tmp_path):
    runtime = _runtime(tmp_path, max_workers=2)
    started: list[str] = []
    releases = {job_id: Event() for job_id in ("a1", "a2", "b1", "c1")}

    def fake_run(_agent_name, _prompt, job_key, _bridge_job_id):
        started.append(job_key)
        runtime._update_job(job_key, status="running", phase="running_model")
        releases[job_key].wait(2)
        runtime._update_job(job_key, status="completed", phase="completed")
        return job_key

    runtime._run_job = fake_run
    try:
        _add_job(runtime, "a1", "agent_a")
        _add_job(runtime, "a2", "agent_a")
        _add_job(runtime, "b1", "agent_b")
        _add_job(runtime, "c1", "agent_c")
        _wait_for(lambda: set(started) == {"a1", "b1"})
        assert "a2" not in runtime._futures
        assert runtime._inflight_count == 2
        assert runtime._jobs["a2"]["phase"] == "waiting_agent_lane"
        assert runtime._jobs["c1"]["phase"] == "waiting_worker"

        releases["a1"].set()
        _wait_for(lambda: "a2" in started)
        assert started.index("a2") > started.index("a1")
    finally:
        for release in releases.values():
            release.set()
        runtime.executor.shutdown(wait=True)


def test_background_lane_does_not_block_same_agent_interactive_work(tmp_path):
    runtime = _runtime(tmp_path, max_workers=2)
    started: list[str] = []
    releases = {job_id: Event() for job_id in ("background", "interactive")}

    def fake_run(_agent_name, _prompt, job_key, _bridge_job_id):
        started.append(job_key)
        runtime._update_job(job_key, status="running", phase="running_model")
        releases[job_key].wait(2)
        runtime._update_job(job_key, status="completed", phase="completed")
        return job_key

    runtime._run_job = fake_run
    try:
        _add_job(runtime, "background", "agent_a", source_type="ops-email-watch")
        _add_job(runtime, "interactive", "agent_a", source_type="agent-direct-chat")
        _wait_for(lambda: set(started) == {"background", "interactive"})
        assert runtime._jobs["background"]["laneKey"] == "agent_a:background"
        assert runtime._jobs["interactive"]["laneKey"] == "agent_a:interactive"
    finally:
        for release in releases.values():
            release.set()
        runtime.executor.shutdown(wait=True)


def test_inbox_lane_does_not_wait_behind_same_agent_background_work(tmp_path):
    runtime = _runtime(tmp_path, max_workers=2)
    started: list[str] = []
    releases = {job_id: Event() for job_id in ("background", "inbox")}

    def fake_run(_agent_name, _prompt, job_key, _bridge_job_id):
        started.append(job_key)
        runtime._update_job(job_key, status="running", phase="running_model")
        releases[job_key].wait(2)
        runtime._update_job(job_key, status="completed", phase="completed")
        return job_key

    runtime._run_job = fake_run
    try:
        _add_job(runtime, "background", "agent_a", source_type="ops-kpi-dashboard")
        _add_job(runtime, "inbox", "agent_a", source_type="ops-support-email-intake")
        _wait_for(lambda: set(started) == {"background", "inbox"})
        assert runtime._jobs["background"]["laneKey"] == "agent_a:background"
        assert runtime._jobs["inbox"]["laneKey"] == "agent_a:inbox"
        assert runtime._jobs["inbox"]["queuePriority"] < runtime._jobs["background"]["queuePriority"]
    finally:
        for release in releases.values():
            release.set()
        runtime.executor.shutdown(wait=True)


def test_singapore_service_lane_runs_when_background_capacity_is_full(tmp_path):
    runtime = _runtime(tmp_path, max_workers=3)
    started: list[str] = []
    releases = {job_id: Event() for job_id in ("kpi", "tickets", "singapore")}

    def fake_run(_agent_name, _prompt, job_key, _bridge_job_id):
        started.append(job_key)
        runtime._update_job(job_key, status="running", phase="running_model")
        releases[job_key].wait(2)
        runtime._update_job(job_key, status="completed", phase="completed")
        return job_key

    runtime._run_job = fake_run
    try:
        _add_job(runtime, "kpi", "coding_agent", source_type="ops-kpi-dashboard")
        _add_job(runtime, "tickets", "tickets_agent", source_type="ops-ticket-refresh")
        _wait_for(lambda: set(started) == {"kpi", "tickets"})
        assert runtime._background_inflight_count == 2

        _add_job(runtime, "singapore", "coding_agent", source_type="ops-singapore-ftp")
        _wait_for(lambda: set(started) == {"kpi", "tickets", "singapore"})
        assert runtime._jobs["singapore"]["laneKey"] == "coding_agent:service"
        assert runtime._jobs["singapore"]["laneClass"] == "service"
        assert runtime._background_inflight_count == 2
    finally:
        for release in releases.values():
            release.set()
        runtime.executor.shutdown(wait=True)


def test_background_refresh_queue_keeps_only_newest_same_source(tmp_path):
    runtime = _runtime(tmp_path, max_workers=2)
    runtime._paused = True
    try:
        _add_job(runtime, "old", "agent_a", source_type="ops-kpi-dashboard")
        _add_job(runtime, "new", "agent_a", source_type="ops-kpi-dashboard")
        assert runtime._jobs["old"]["status"] == "superseded"
        assert runtime._jobs["old"]["supersededBy"] == "new"
        assert runtime._lane_queues["agent_a:background"] == ["new"]
    finally:
        runtime.executor.shutdown(wait=True)


def test_operator_priority_is_stable_and_does_not_preempt_running_work(tmp_path):
    runtime = _runtime(tmp_path, max_workers=1)
    runtime._paused = True
    started: list[str] = []

    def fake_run(_agent_name, _prompt, job_key, _bridge_job_id):
        started.append(job_key)
        runtime._update_job(job_key, status="completed", phase="completed")
        return job_key

    runtime._run_job = fake_run
    try:
        _add_job(runtime, "background", "agent_a", source_type="ops-email-watch")
        _add_job(runtime, "dispatch", "agent_a", source_type="dispatch")
        _add_job(
            runtime,
            "steer",
            "agent_a",
            source_type="agent-direct-chat",
            payload={"instruction": "/steer use the newest readback"},
        )
        runtime.resume()
        _wait_for(lambda: len(started) == 3)
        assert started == ["steer", "dispatch", "background"]
    finally:
        runtime.executor.shutdown(wait=True)


def test_acknowledged_operator_handoff_runs_before_new_dispatches(tmp_path):
    runtime = _runtime(tmp_path, max_workers=1)
    runtime._paused = True
    started: list[str] = []

    def fake_run(_agent_name, _prompt, job_key, _bridge_job_id):
        started.append(job_key)
        runtime._update_job(job_key, status="completed", phase="completed")
        return job_key

    runtime._run_job = fake_run
    try:
        # Queue the new dispatch first to prove the operator continuation is
        # selected by authority, not merely by FIFO sequence.
        _add_job(runtime, "dispatch", "billing_agent", source_type="dispatch")
        _add_job(runtime, "handoff", "billing_agent", source_type="agent-handoff")
        _add_job(
            runtime,
            "operator-handoff",
            "billing_agent",
            source_type="agent-handoff-operator-continuation",
            payload={"operatorContinuation": True},
        )
        _add_job(
            runtime,
            "read-only-handoff",
            "billing_agent",
            source_type="agent-handoff-read-only",
            payload={"enforcedReadOnly": True},
        )

        runtime.resume()

        _wait_for(lambda: len(started) == 4)
        assert started == [
            "operator-handoff",
            "dispatch",
            "handoff",
            "read-only-handoff",
        ]
    finally:
        runtime.executor.shutdown(wait=True)


def test_restart_recovers_only_manifest_jobs_and_guards_interrupted_running_work(tmp_path):
    before = _runtime(tmp_path, max_workers=1)
    before._paused = True
    queued = {
        "id": "queued",
        "bridgeJobId": 1,
        "status": "queued",
        "phase": "waiting_agent_lane",
        "agentName": "agent_a",
        "sourceType": "dispatch",
        "payload": {},
        "prompt": "queued prompt",
        "runnerType": "agent",
    }
    running = {
        **queued,
        "id": "running",
        "bridgeJobId": 2,
        "status": "running",
        "phase": "running_model",
        "prompt": "possibly wrote externally",
    }
    before._jobs = {"queued": queued, "running": running}
    before._write_job(queued)
    before._write_job(running)
    (before.jobs_dir / "stale.json").write_text(
        json.dumps({**queued, "id": "stale", "bridgeJobId": 3}),
        encoding="utf-8",
    )
    before._persist_pause_manifest(reason="test restart", resume_after_restart=False)

    after = _runtime(tmp_path, max_workers=1)
    try:
        after._recover_pause_manifest()
        assert set(after._jobs) == {"queued", "running"}
        assert after._paused is True
        assert after._jobs["running"]["status"] == "queued"
        assert after._jobs["running"]["phase"] == "paused"
        assert after._jobs["running"]["recoveryContinuation"][
            "exactTargetReadbackRequired"
        ] is True
        assert after._jobs["running"]["interruptedAtRestart"] is True
        assert after._jobs["running"]["restartRecoveryWarning"] == RESTART_RECOVERY_WARNING
        assert "running" in after._work_items
        assert after._pause_manifest["reviewRequiredJobIds"] == []
        assert "stale" not in after._jobs
    finally:
        before.executor.shutdown(wait=True)
        after.executor.shutdown(wait=True)


def test_restart_quarantines_interrupted_fast_path_instead_of_replaying(tmp_path):
    before = _runtime(tmp_path, max_workers=1)
    before._paused = True
    running = {
        "id": "fast-running",
        "bridgeJobId": 9,
        "status": "running",
        "phase": "running_fast_path",
        "agentName": "coding_agent",
        "sourceType": "ops-singapore-ftp",
        "payload": {},
        "prompt": "possibly sent externally",
        "runnerType": "singapore_fast_path",
        "runnerArgs": {},
    }
    before._jobs = {"fast-running": running}
    before._write_job(running)
    before._persist_pause_manifest(reason="test restart", resume_after_restart=True)

    after = _runtime(tmp_path, max_workers=1)
    try:
        after._recover_pause_manifest()
        assert after._jobs["fast-running"]["status"] == "recovery_review_required"
        assert after._jobs["fast-running"]["phase"] == "recovery_review_required"
        assert "fast-running" not in after._work_items
        assert after._pause_manifest["state"] == "recovery_complete"
        assert after._pause_manifest["reviewRequiredJobIds"] == ["fast-running"]
    finally:
        before.executor.shutdown(wait=True)
        after.executor.shutdown(wait=True)


def test_active_recovery_manifest_survives_second_restart_until_terminal(tmp_path):
    before = _runtime(tmp_path, max_workers=1)
    before._paused = True
    queued = {
        "id": "queued",
        "bridgeJobId": 1,
        "status": "queued",
        "phase": "waiting_agent_lane",
        "agentName": "agent_a",
        "sourceType": "dispatch",
        "payload": {},
        "prompt": "queued prompt",
        "runnerType": "agent",
    }
    before._jobs = {"queued": queued}
    before._write_job(queued)
    before._persist_pause_manifest(reason="test restart", resume_after_restart=False)

    first = _runtime(tmp_path, max_workers=1)
    second = _runtime(tmp_path, max_workers=1)
    try:
        first._recover_pause_manifest()
        assert first._pause_manifest["state"] == "active_recovery"
        second._recover_pause_manifest()
        assert "queued" in second._jobs
        assert second._pause_manifest["state"] == "active_recovery"
        second._update_job("queued", status="completed", phase="completed")
        assert second._pause_manifest["state"] == "recovery_complete"
    finally:
        before.executor.shutdown(wait=True)
        first.executor.shutdown(wait=True)
        second.executor.shutdown(wait=True)


def test_recovery_progress_ignores_jobs_already_skipped_as_terminal(tmp_path):
    runtime = _runtime(tmp_path)
    runtime._pause_manifest = {
        "state": "active_recovery",
        "jobs": [{"id": "already-done", "status": "running"}],
        "skippedTerminalJobIds": ["already-done"],
    }
    try:
        runtime._refresh_recovery_manifest_progress()
        assert runtime._pause_manifest["state"] == "recovery_complete"
        assert runtime._pause_manifest["pendingRecoveryJobIds"] == []
    finally:
        runtime.executor.shutdown(wait=True)


def test_read_repairs_terminal_projection_and_excludes_it_from_active_jobs(tmp_path):
    runtime = _runtime(tmp_path)
    record = {
        "id": "stale-running",
        "bridgeJobId": 7,
        "status": "running",
        "phase": "running_model",
        "agentName": "agent_a",
        "sourceType": "agent-direct-chat",
        "createdAtUtc": "2026-07-10T12:00:00+00:00",
        "updatedAtUtc": "2026-07-10T12:00:00+00:00",
    }
    runtime._jobs[record["id"]] = dict(record)
    runtime._write_job(record)
    runtime.state.rows[7] = {
        "id": 7,
        "event_id": record["id"],
        "channel_id": "command_center",
        "status": "completed",
        "completed_at": time.time(),
        "reconciled_at": None,
        "reconciliation_reason": "",
        "error": "",
        "recovery_count": 0,
    }
    try:
        repaired = runtime.job(record["id"])
        assert repaired is not None
        assert repaired["status"] == "completed"
        assert repaired["phase"] == "completed"
        assert json.loads((runtime.jobs_dir / "stale-running.json").read_text(encoding="utf-8"))["status"] == "completed"
        assert runtime.jobs(active_only=True)["jobs"] == []
    finally:
        runtime.executor.shutdown(wait=True)


def test_projection_repairs_interrupted_and_superseded_terminal_states(tmp_path):
    runtime = _runtime(tmp_path)
    records = []
    for bridge_job_id, status in ((8, "interrupted"), (9, "superseded")):
        record = {
            "id": f"job-{bridge_job_id}",
            "bridgeJobId": bridge_job_id,
            "status": "running" if status == "interrupted" else "queued",
            "phase": "running_model" if status == "interrupted" else "waiting_worker",
            "agentName": "agent_a",
            "sourceType": "dispatch",
        }
        records.append(record)
        runtime._write_job(record)
        runtime.state.rows[bridge_job_id] = {
            "id": bridge_job_id,
            "event_id": record["id"],
            "channel_id": "command_center",
            "status": status,
            "completed_at": time.time(),
            "reconciled_at": time.time(),
            "reconciliation_reason": f"ledger says {status}",
            "error": "",
            "recovery_count": 1,
        }
    try:
        repaired, count = runtime._repair_terminal_projections(records, persist=True)
        assert count == 2
        assert [item["status"] for item in repaired] == ["interrupted", "superseded"]
    finally:
        runtime.executor.shutdown(wait=True)


def test_completed_job_stays_locally_terminal_when_noncritical_postprocessing_fails(tmp_path, monkeypatch):
    runtime = _runtime(tmp_path)
    runtime.config = SimpleNamespace(defaults={}, agents={"agent_a": {}})
    runtime._jobs["job"] = {
        "id": "job",
        "bridgeJobId": 10,
        "status": "queued",
        "phase": "queued",
        "agentName": "agent_a",
        "sourceType": "dispatch",
        "payload": {},
        "prompt": "do work",
    }
    runtime.state.rows[10] = {
        "id": 10,
        "event_id": "job",
        "channel_id": "command_center",
        "status": "queued",
    }
    runtime._runtime_memory = lambda *_args: ""
    runtime._store_cognitive_episode = lambda **_kwargs: None
    runtime._append_chat = lambda *_args, **_kwargs: None
    runtime._register_recent_artifacts = lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("artifact failure"))
    runtime._sync_review_packet_after_job = lambda *_args, **_kwargs: None
    runtime._sync_drawing_board_after_job = lambda *_args, **_kwargs: None
    monkeypatch.setattr("codex_slack_bridge.command_center_server.sign_trusted_message", lambda **_kwargs: "signature")
    result = "COMPLETED: done"
    monkeypatch.setattr("codex_slack_bridge.command_center_server.run_agent_isolated", lambda *_args, **_kwargs: result)
    try:
        assert runtime._run_job("agent_a", "do work", "job", 10) == result
        assert runtime._jobs["job"]["status"] == "completed"
        assert runtime._jobs["job"]["result"] == result
        assert ("completed", 10) in runtime.state.transitions
        assert not any(status == "failed" for status, _job_id in runtime.state.transitions)
    finally:
        runtime.executor.shutdown(wait=True)


def test_acknowledged_handoff_keeps_origin_running_until_child_receipt(
    tmp_path,
    monkeypatch,
):
    runtime = _runtime(tmp_path)
    runtime.config = SimpleNamespace(defaults={}, agents={"agent_a": {}})
    runtime._jobs["job"] = {
        "id": "job",
        "bridgeJobId": 10,
        "status": "queued",
        "phase": "queued",
        "agentName": "agent_a",
        "sourceType": "dispatch",
        "payload": {"idempotencyKey": "origin-key"},
        "prompt": "finish through the owning lane",
    }
    runtime.state.rows[10] = {
        "id": 10,
        "event_id": "job",
        "channel_id": "command_center",
        "status": "queued",
    }
    runtime._runtime_memory = lambda *_args: ""
    runtime._store_cognitive_episode = lambda **_kwargs: None
    runtime._append_chat = lambda *_args, **_kwargs: None
    runtime._register_recent_artifacts = lambda *_args, **_kwargs: None
    runtime._sync_review_packet_after_job = lambda *_args, **_kwargs: None
    runtime._sync_drawing_board_after_job = lambda *_args, **_kwargs: None
    runtime._submit_taylor_handoff = lambda **_kwargs: {
        "accepted": True,
        "duplicate": False,
        "status": "queued",
        "job_id": "child-job",
        "agentName": "billing_agent",
        "handoffAcknowledged": True,
        "handoffAcknowledgedAtUtc": "2026-07-30T17:15:00Z",
        "handoffAcknowledgedByAgent": "billing_agent",
        "handoffAcknowledgement": "Receiving lane acknowledged the child.",
    }
    monkeypatch.setattr(
        command_center_server,
        "sign_trusted_message",
        lambda **_kwargs: "signature",
    )
    monkeypatch.setattr(
        command_center_server,
        "run_agent_isolated",
        lambda *_args, **_kwargs: (
            "COMPLETED_WITH_ISSUES\nThe billing lane must finish the work.\n"
            'TAYLOR_HANDOFF_REQUEST: {"targetAgent":"billing_agent",'
            '"requestedTask":"Complete the original authorized work.",'
            '"reason":"The required capability belongs to billing."}'
        ),
    )
    try:
        result = runtime._run_job(
            "agent_a",
            "finish through the owning lane",
            "job",
            10,
        )

        assert result.startswith("COMPLETED_WITH_ISSUES")
        assert runtime._jobs["job"]["status"] == "running"
        assert runtime._jobs["job"]["phase"] == "handoff_acknowledged"
        assert runtime._jobs["job"]["handoffChildJobId"] == "child-job"
        assert ("handoff_acknowledged", 10) in runtime.state.transitions
        assert not any(
            status in {"completed", "completed_with_issues", "blocked", "failed"}
            for status, _job_id in runtime.state.transitions
        )
    finally:
        runtime.executor.shutdown(wait=True)


def test_operator_handoff_uses_verified_email_gateway_for_custom_domain(
    tmp_path,
    monkeypatch,
):
    runtime = _runtime(tmp_path)
    runtime.config = SimpleNamespace(defaults={}, agents={"coding_agent": {}})
    attachment = {
        "id": "a" * 32,
        "name": "Valiant_Price_Lists_By_Location_347420.xlsx",
        "mimetype": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "size": 7527727,
        "sha256": "b" * 64,
        "local_path": str(tmp_path / "Valiant_Price_Lists_By_Location_347420.xlsx"),
    }
    runtime._jobs["job"] = {
        "id": "job",
        "bridgeJobId": 10,
        "status": "queued",
        "phase": "queued",
        "agentName": "coding_agent",
        "sourceType": "agent-handoff-operator-continuation",
        "payload": {
            "type": "agent-handoff",
            "sourceAgent": "tickets_agent",
            "originRequest": (
                "Redo the Valiant workbook and email it to michael@armgmnt.com."
            ),
            "operatorContinuation": True,
            "attachments": [{"id": "a" * 32}],
        },
        "prompt": "complete the tracked handoff",
    }
    runtime.state.rows[10] = {
        "id": 10,
        "event_id": "job",
        "channel_id": "command_center",
        "status": "queued",
    }
    runtime._runtime_memory = lambda *_args: ""
    runtime._resolve_agent_chat_attachments = lambda _payload: [attachment]
    runtime.agent_chat_attachment_root = tmp_path
    runtime._store_cognitive_episode = lambda **_kwargs: None
    runtime._append_chat = lambda *_args, **_kwargs: None
    runtime._register_recent_artifacts = lambda *_args, **_kwargs: None
    runtime._sync_review_packet_after_job = lambda *_args, **_kwargs: None
    runtime._sync_drawing_board_after_job = lambda *_args, **_kwargs: None
    runtime._finalize_handoff_parent = lambda *_args, **_kwargs: None
    captured_requests = []
    captured_deliveries = []
    monkeypatch.setattr(
        command_center_server,
        "sign_trusted_message",
        lambda **_kwargs: "signature",
    )
    monkeypatch.setattr(
        command_center_server,
        "grant_agent_file_access",
        lambda *_args, **_kwargs: None,
    )

    def fake_agent(_agent_name, _agent, request):
        captured_requests.append(request)
        return (
            "COMPLETED\n"
            'VERIFIED_EMAIL_DELIVERY_REQUEST: {"recipient":"michael@armgmnt.com",'
            '"subject":"Valiant price lists by location",'
            '"body":"Hi Michael,\\n\\nAttached are the requested price lists.",'
            '"attachmentNames":["Valiant_Price_Lists_By_Location_347420.xlsx"]}'
        )

    monkeypatch.setattr(command_center_server, "run_agent_isolated", fake_agent)

    def fake_delivery(**kwargs):
        captured_deliveries.append(kwargs)
        return {
            "ok": True,
            "sent": True,
            "duplicate": False,
            "recipient": "michael@armgmnt.com",
            "subject": "Valiant price lists by location",
            "attachmentNames": ["Valiant_Price_Lists_By_Location_347420.xlsx"],
            "sentMessageId": "sent-123",
            "threadId": "thread-123",
            "idempotencyKey": "verified-email:job:test",
            "signatureSource": "gmail_send_as",
            "readbackVerified": True,
        }

    runtime._submit_verified_email_delivery = fake_delivery
    try:
        result = runtime._run_job("coding_agent", "complete the tracked handoff", "job", 10)
        assert result == (
            "COMPLETED\nEmail sent and verified to michael@armgmnt.com with 1 attachment."
        )
        assert "michael@armgmnt.com" in captured_requests[0].context
        assert "generic Gmail connector" in captured_requests[0].context
        assert captured_deliveries[0]["attachments"] == [attachment]
        assert runtime._jobs["job"]["verifiedEmailDelivery"]["readbackVerified"] is True
        assert runtime._jobs["job"]["status"] == "completed"
    finally:
        runtime.executor.shutdown(wait=True)


def test_queued_agent_rechecks_readiness_and_blocks_before_provider_invocation(
    tmp_path,
    monkeypatch,
):
    class Readiness:
        def __init__(self):
            self.calls = []

        def ensure_ready(self, agent_name, *, force_refresh=False):
            self.calls.append((agent_name, force_refresh))
            return {
                "agentName": agent_name,
                "provider": "codex_cli",
                "ready": False,
                "status": "not_authenticated",
                "checkedAtUtc": "2026-07-28T20:00:00Z",
                "ageSeconds": 0,
                "stale": False,
            }

    runtime = _runtime(tmp_path)
    readiness = Readiness()
    runtime.agent_provider_readiness = readiness
    runtime.config = SimpleNamespace(
        defaults={},
        agents={"agent_a": {"provider": "codex_cli"}},
    )
    runtime._jobs["job"] = {
        "id": "job",
        "bridgeJobId": 11,
        "status": "queued",
        "phase": "queued",
        "agentName": "agent_a",
        "sourceType": "agent-direct-chat",
        "idempotencyKey": "provider-retry:test",
        "createdAtUtc": "2026-07-28T20:00:00Z",
        "payload": {"attachments": [{"id": "attachment-1"}]},
        "prompt": "do provider work",
    }
    runtime.state.rows[11] = {
        "id": 11,
        "event_id": "job",
        "channel_id": "command_center",
        "status": "queued",
    }
    runtime._runtime_memory = lambda *_args: ""
    runtime._resolve_agent_chat_attachments = lambda _payload: [
        {
            "id": "attachment-1",
            "name": "evidence.txt",
            "mimetype": "text/plain",
            "size": 8,
            "sha256": "a" * 64,
            "local_path": str(tmp_path / "evidence.txt"),
        }
    ]
    runtime.agent_chat_attachment_root = tmp_path
    chats = []
    runtime._append_chat = lambda *args, **kwargs: chats.append((args, kwargs))
    monkeypatch.setattr(
        command_center_server,
        "sign_trusted_message",
        lambda **_kwargs: "signature",
    )
    provider_calls = []
    access_grants = []
    monkeypatch.setattr(
        command_center_server,
        "grant_agent_file_access",
        lambda *_args, **_kwargs: access_grants.append(True),
    )
    monkeypatch.setattr(
        command_center_server,
        "run_agent_isolated",
        lambda *_args, **_kwargs: provider_calls.append(True) or "COMPLETED",
    )

    try:
        result = runtime._run_job("agent_a", "do provider work", "job", 11)
        record = runtime._jobs["job"]

        assert result.startswith("BLOCKED\nProvider readiness changed before invocation.")
        assert readiness.calls == [("agent_a", True)]
        assert provider_calls == []
        assert access_grants == []
        assert record["status"] == "blocked"
        assert record["phase"] == "blocked_provider_unready_before_invocation"
        assert record["retryable"] is True
        assert record["retryReason"] == "agent_provider_unready"
        assert record["providerInvocationStarted"] is False
        assert record["providerReadiness"]["status"] == "not_authenticated"
        assert record["needsReview"] is False
        assert ("blocked", 11) in runtime.state.transitions
        assert chats
        assert not command_center_server._job_is_duplicate(
            record,
            "provider-retry:test",
            "agent-direct-chat",
            600,
        )
    finally:
        runtime.executor.shutdown(wait=True)


def _support_intake_worker_result(message_id: str = "message-1") -> str:
    payload = {
        "ok": True,
        "schemaVersion": 1,
        "status": "ok",
        "summary": "Created and verified one support ticket.",
        "emails": [
            {
                "sourceEmailId": message_id,
                "threadId": "thread-1",
                "from": "Kay <kay@example.com>",
                "subject": "Register issue",
                "receivedAt": "2026-07-28T12:00:00Z",
                "classification": "support_request",
                "result": "created",
                "triageDecision": "ticket_needed",
                "recommendedAction": "Research the verified ticket.",
                "templateSuggestion": {"name": "", "reason": ""},
                "recommendedReplyBody": "",
                "accountId": "001-account",
                "account": "Kay's Cafe",
                "ticket": {
                    "id": "a0G-ticket",
                    "number": "347200",
                    "url": "https://salesforce.example/a0G-ticket",
                    "recordType": "1. NOVA Classic",
                    "mainIssue": "Software",
                    "technicalIssue": "Other",
                    "verifiedAtUtc": "2026-07-28T12:05:00Z",
                },
                "machineId": "",
                "changedServerFields": [],
                "blockers": [],
            }
        ],
    }
    return (
        "COMPLETED\n"
        f"{command_center_server.OPS_SUPPORT_EMAIL_INTAKE_RESULT_MARKER} "
        f"{json.dumps(payload, separators=(',', ':'))}"
    )


def _attach_runtime_salesforce_readback(cache: dict) -> dict:
    item = cache["emails"][0]
    ticket = item["ticket"]
    item["salesforceReadback"] = {
        "status": "verified",
        "verified": True,
        "source": "nova-runtime:typed-live-salesforce-ticket-readback",
        "checkedAtUtc": "2026-07-28T12:06:00Z",
        "ticketId": ticket["id"],
        "ticketNumber": ticket["number"],
        "accountId": item["accountId"],
        "accountEligible": True,
        "recordType": ticket["recordType"],
        "sourceEmailId": item["sourceEmailId"],
        "sourceKey": f"support-email:{item['sourceEmailId']}",
        "isClosed": False,
        "reasonCodes": [],
        "reason": "",
    }
    item["runtimeAction"] = {"status": "ready", "reason": ""}
    cache["status"] = "ok"
    cache["runtimeStatus"] = {
        "status": "ok",
        "blockedTicketCount": 0,
        "salesforceTicketReadback": "verified",
        "reason": "",
    }
    return command_center_server._seal_ops_support_email_intake_publication(cache)


def _configure_support_intake_job_runtime(runtime, tmp_path):
    runtime.config = SimpleNamespace(defaults={}, agents={"coding_agent": {}})
    runtime.support_email_intake_path = tmp_path / "private" / "ops_support_email_intake.json"
    runtime._jobs["support-job"] = {
        "id": "support-job",
        "bridgeJobId": 12,
        "status": "queued",
        "phase": "queued",
        "agentName": "coding_agent",
        "sourceType": "ops-support-email-intake",
        "idempotencyKey": "support-email:test",
        "payload": {
            "type": "ops-support-email-intake",
            "gmailQuery": "in:inbox is:unread",
            "messageIds": ["message-1"],
        },
        "prompt": "intake email",
    }
    runtime.state.rows[12] = {
        "id": 12,
        "event_id": "support-job",
        "channel_id": "command_center",
        "status": "queued",
    }
    runtime._runtime_memory = lambda *_args: ""
    runtime._append_chat = lambda *_args, **_kwargs: None
    runtime._register_recent_artifacts = lambda *_args, **_kwargs: None
    runtime._sync_review_packet_after_job = lambda *_args, **_kwargs: None
    runtime._sync_drawing_board_after_job = lambda *_args, **_kwargs: None


def test_support_intake_run_publishes_before_alex_gmail_and_ledger(tmp_path, monkeypatch):
    runtime = _runtime(tmp_path)
    _configure_support_intake_job_runtime(runtime, tmp_path)
    events = []

    class Ledger:
        def apply_support_result(self, item):
            assert item["gmail"]["readbackVerified"] is True
            events.append("ledger")

    runtime.inbox_ledger = Ledger()
    runtime._submit_support_email_research = lambda _item: (
        events.append("alex") or {"accepted": True, "job_id": "alex-job"}
    )
    runtime._apply_cached_gmail_label_action = lambda *_args, **_kwargs: (
        events.append("gmail") or {"ok": True, "verified": True}
    )
    runtime._readback_support_email_ticket_claim = lambda item: (
        events.append("salesforce") or _attach_runtime_salesforce_readback(
            {"emails": [item]}
        )["emails"][0]["salesforceReadback"]
    )
    expected_action_key = command_center_server._support_email_research_action_key(
        {
            "sourceKey": "support-email:message-1",
            "sourceEmailId": "message-1",
            "threadId": "thread-1",
            "ticket": {"id": "a0G-ticket", "number": "347200"},
        }
    )
    runtime.job = lambda job_id: {
        "id": job_id,
        "agentName": "tickets_agent",
        "sourceType": "ops-support-email-research",
        "idempotencyKey": expected_action_key,
    }
    real_durable_write = command_center_server._write_cached_json_durable
    def tracked_durable_write(path, data):
        readback = real_durable_write(path, data)
        events.append("publish" if "publish" not in events else "receipt")
        return readback

    monkeypatch.setattr(command_center_server, "_write_cached_json_durable", tracked_durable_write)
    monkeypatch.setattr(command_center_server, "sign_trusted_message", lambda **_kwargs: "signature")
    result = _support_intake_worker_result()
    monkeypatch.setattr(command_center_server, "run_agent_isolated", lambda *_args, **_kwargs: result)
    try:
        assert runtime._run_job("coding_agent", "intake email", "support-job", 12) == result
        assert events[0] == "publish"
        assert (
            events.index("publish")
            < events.index("salesforce")
            < events.index("alex")
            < events.index("gmail")
            < events.index("ledger")
        )
        receipt_indexes = [
            index for index, event in enumerate(events) if event == "receipt"
        ]
        assert (
            events.index("salesforce")
            < receipt_indexes[0]
            < events.index("alex")
            < receipt_indexes[1]
            < events.index("gmail")
        )
        cache = json.loads(runtime.support_email_intake_path.read_text(encoding="utf-8"))
        command_center_server._verify_ops_support_email_intake_publication(cache)
        assert cache["publication"]["publisher"] == "nova-runtime"
        assert cache["emails"][0]["gmail"]["readbackVerified"] is True
        assert runtime._jobs["support-job"]["status"] == "completed"
    finally:
        runtime.executor.shutdown(wait=True)


def test_support_intake_stale_finalization_fence_allows_publication_but_zero_effects(
    tmp_path,
    monkeypatch,
):
    runtime = _runtime(tmp_path)
    _configure_support_intake_job_runtime(runtime, tmp_path)
    runtime.state.finalization_claim_allowed = False
    runtime.state.outcome_allowed = False
    effects = []
    runtime.inbox_ledger = None
    runtime._submit_support_email_research = lambda _item: effects.append("alex")
    runtime._apply_cached_gmail_label_action = lambda *_args, **_kwargs: effects.append("gmail")
    runtime._readback_support_email_ticket_claim = lambda _item: effects.append(
        "salesforce"
    )
    monkeypatch.setattr(command_center_server, "sign_trusted_message", lambda **_kwargs: "signature")
    monkeypatch.setattr(
        command_center_server,
        "run_agent_isolated",
        lambda *_args, **_kwargs: _support_intake_worker_result(),
    )
    try:
        result = runtime._run_job("coding_agent", "intake email", "support-job", 12)
        assert result == "Discarded stale command-center result after recovery fencing."
        assert effects == []
        published = json.loads(runtime.support_email_intake_path.read_text(encoding="utf-8"))
        command_center_server._verify_ops_support_email_intake_publication(published)
        assert published["publication"]["jobId"] == "support-job"
    finally:
        runtime.executor.shutdown(wait=True)


def test_support_intake_invalid_result_blocks_same_ledger_identity_without_effects(tmp_path, monkeypatch):
    runtime = _runtime(tmp_path)
    _configure_support_intake_job_runtime(runtime, tmp_path)
    blocked = []

    class Ledger:
        def items_for_job(self, job_id, *, route):
            assert job_id == "support-job"
            assert route == "taylor_support_intake"
            return [{"messageId": "message-1"}]

        def block(self, message_id, error, *, retry_after_seconds):
            blocked.append((message_id, error, retry_after_seconds))

    runtime.inbox_ledger = Ledger()
    runtime._submit_support_email_research = lambda _item: (_ for _ in ()).throw(
        AssertionError("Alex cannot run before publication")
    )
    runtime._apply_cached_gmail_label_action = lambda *_args, **_kwargs: (_ for _ in ()).throw(
        AssertionError("Gmail cannot run before publication")
    )
    monkeypatch.setattr(command_center_server, "sign_trusted_message", lambda **_kwargs: "signature")
    monkeypatch.setattr(
        command_center_server,
        "run_agent_isolated",
        lambda *_args, **_kwargs: "COMPLETED\nMissing the structured result.",
    )
    try:
        result = runtime._run_job("coding_agent", "intake email", "support-job", 12)
        assert "result publication failed" in result
        assert runtime._jobs["support-job"]["status"] == "failed"
        assert blocked[0][0] == "message-1"
        assert blocked[0][2] == 60
        assert runtime._jobs["support-job"]["retryableFailureKind"] == "support_email_publication"
        assert runtime._jobs["support-job"]["retryAfterSeconds"] == 60
        assert runtime.support_email_intake_path.exists() is False
    finally:
        runtime.executor.shutdown(wait=True)


def test_support_intake_cache_merge_and_receipt_update_are_serialized_and_durable(
    tmp_path,
    monkeypatch,
):
    runtime = _runtime(tmp_path)
    _configure_support_intake_job_runtime(runtime, tmp_path)
    runtime._jobs["alex-job"] = {
        "id": "alex-job",
        "sourceType": "ops-support-email-research",
        "agentName": "tickets_agent",
        "createdAtUtc": "2026-07-28T12:07:00Z",
        "idempotencyKey": "support-email-research:test",
        "payload": {
            "supportEmailSourceKey": "support-email:message-1",
            "supportEmailMessageId": "message-1",
            "ticketNumber": "347200",
        },
    }
    runtime._find_review_packet_for_ticket = lambda _ticket: {"id": "review-1"}
    first_write_entered = Event()
    release_first_write = Event()
    real_durable_write = command_center_server._write_cached_json_durable
    write_count = []

    def interleaved_write(path, data):
        write_count.append(str((data.get("publication") or {}).get("id") or "legacy"))
        if len(write_count) == 1:
            first_write_entered.set()
            assert release_first_write.wait(2)
        return real_durable_write(path, data)

    monkeypatch.setattr(command_center_server, "_write_cached_json_durable", interleaved_write)
    publication_result = {}
    publication_error = []

    def publish():
        try:
            publication_result.update(
                runtime._publish_support_email_intake_result(
                    _support_intake_worker_result(),
                    job_key="support-job",
                    job_record=runtime._jobs["support-job"],
                )
            )
        except Exception as exc:  # pragma: no cover - asserted below
            publication_error.append(exc)

    publish_thread = Thread(target=publish)
    publish_thread.start()
    assert first_write_entered.wait(2)
    review_thread = Thread(
        target=runtime._record_support_email_review_ready,
        args=("alex-job",),
    )
    review_thread.start()
    time.sleep(0.05)
    assert review_thread.is_alive()
    release_first_write.set()
    publish_thread.join(2)
    review_thread.join(2)

    assert publication_error == []
    assert not publish_thread.is_alive()
    assert not review_thread.is_alive()
    cache = json.loads(runtime.support_email_intake_path.read_text(encoding="utf-8"))
    command_center_server._verify_ops_support_email_intake_publication(cache)
    assert cache["publication"]["id"] == publication_result["publication"]["id"]
    assert cache["emails"][0]["alex"]["status"] == "review_ready"
    assert cache["emails"][0]["alex"]["reviewPacketId"] == "review-1"
    assert len(write_count) == 2
    runtime.executor.shutdown(wait=True)


def test_ticket_refresh_with_issues_promotes_valid_current_cache(tmp_path, monkeypatch):
    runtime = _runtime(tmp_path)
    runtime.config = SimpleNamespace(defaults={}, agents={"agent_a": {}})
    runtime.tickets_path = tmp_path / "private" / "ops_tickets.json"
    runtime.ticket_refresh_output_root = tmp_path / "alex-output"
    runtime.ticket_refresh_output_root.mkdir()
    output_path = runtime.ticket_refresh_output_root / "ops_tickets.refresh.json"
    generated_at = datetime.now(timezone.utc).isoformat()
    output_path.write_text(
        json.dumps(
            {
                "ok": True,
                "status": "partial",
                "updatedAtUtc": generated_at,
                "source": "Salesforce live query",
                "total": 1,
                "columns": [{"id": "support", "tickets": [{"number": "347300"}]}],
            }
        ),
        encoding="utf-8",
    )
    runtime._jobs["refresh"] = {
        "id": "refresh",
        "bridgeJobId": 11,
        "status": "queued",
        "phase": "queued",
        "createdAtUtc": generated_at,
        "agentName": "agent_a",
        "sourceType": "ops-ticket-refresh",
        "payload": {"outputPath": str(output_path)},
        "prompt": "refresh tickets",
    }
    runtime.state.rows[11] = {
        "id": 11,
        "event_id": "refresh",
        "channel_id": "command_center",
        "status": "queued",
    }
    runtime._runtime_memory = lambda *_args: ""
    runtime._store_cognitive_episode = lambda **_kwargs: None
    runtime._append_chat = lambda *_args, **_kwargs: None
    runtime._register_recent_artifacts = lambda *_args, **_kwargs: None
    runtime._sync_review_packet_after_job = lambda *_args, **_kwargs: None
    runtime._sync_drawing_board_after_job = lambda *_args, **_kwargs: None
    runtime._ingest_ticket_projection_work = lambda: 0
    runtime._reconcile_closed_ticket_reviews = lambda: 0
    runtime._queue_resolved_open_tickets_for_closure = lambda: 0
    monkeypatch.setattr(
        "codex_slack_bridge.command_center_server.sign_trusted_message",
        lambda **_kwargs: "signature",
    )
    result = "COMPLETED_WITH_ISSUES\nA secondary query was unavailable."
    monkeypatch.setattr(
        "codex_slack_bridge.command_center_server.run_agent_isolated",
        lambda *_args, **_kwargs: result,
    )
    try:
        assert runtime._run_job("agent_a", "refresh tickets", "refresh", 11) == result
        promoted = json.loads(runtime.tickets_path.read_text(encoding="utf-8"))
        assert promoted["status"] == "partial"
        assert promoted["total"] == 1
        assert output_path.exists() is False
        assert runtime._jobs["refresh"]["status"] == "completed_with_issues"
    finally:
        runtime.executor.shutdown(wait=True)


def test_background_and_write_bearing_jobs_use_fresh_job_unique_sessions(tmp_path, monkeypatch):
    runtime = _runtime(tmp_path)
    runtime.config = SimpleNamespace(
        defaults={
            "persistent_agent_sessions": True,
            "warm_session_prompt_cache": True,
            "agent_runtime_shared_sessions": True,
            "agent_runtime_session_scope": "agent",
            "ephemeral": False,
            "sandbox": "danger-full-access",
        },
        agents={"agent_a": {}},
    )
    sources = (
        "ops-email-watch",
        "ops-support-email-research",
        "ops-singapore-remediation-ticket",
        "ops-salesforce-ticket-investigation",
    )
    for bridge_job_id, source_type in enumerate(sources, start=20):
        job_key = f"job-{bridge_job_id}"
        runtime._jobs[job_key] = {
            "id": job_key,
            "bridgeJobId": bridge_job_id,
            "status": "queued",
            "phase": "queued",
            "agentName": "agent_a",
            "sourceType": source_type,
            "payload": {
                "type": source_type,
                **(
                    {
                        "stableKey": "singapore-remediation:new_interface_request:test:key",
                        "remediationGroup": {
                            "stableKey": "singapore-remediation:new_interface_request:test:key",
                            "category": "new_interface_request",
                            "requestKind": "new_interface",
                        },
                    }
                    if source_type == "ops-singapore-remediation-ticket"
                    else {}
                ),
            },
            "prompt": f"run {source_type}",
        }
        runtime.state.rows[bridge_job_id] = {
            "id": bridge_job_id,
            "event_id": job_key,
            "channel_id": "command_center",
            "status": "queued",
        }

    runtime._runtime_memory = lambda *_args: ""
    runtime._store_cognitive_episode = lambda **_kwargs: None
    runtime._append_chat = lambda *_args, **_kwargs: None
    runtime._register_recent_artifacts = lambda *_args, **_kwargs: None
    runtime._sync_review_packet_after_job = lambda *_args, **_kwargs: None
    runtime._sync_drawing_board_after_job = lambda *_args, **_kwargs: None
    runtime._apply_email_watch_pending_mailbox_actions = lambda: None
    runtime._record_support_email_review_ready = lambda *_args: None
    runtime._finalize_singapore_remediation_ticket = lambda *_args: None
    captured = []

    def fake_run(agent_name, agent, request):
        captured.append((agent_name, dict(agent), request))
        return "COMPLETED: done"

    monkeypatch.setattr("codex_slack_bridge.command_center_server.sign_trusted_message", lambda **_kwargs: "signature")
    monkeypatch.setattr("codex_slack_bridge.command_center_server.run_agent_isolated", fake_run)
    try:
        for bridge_job_id, source_type in enumerate(sources, start=20):
            assert runtime._run_job(
                "agent_a",
                f"run {source_type}",
                f"job-{bridge_job_id}",
                bridge_job_id,
            ) == "COMPLETED: done"

        assert len(captured) == len(sources)
        assert len({item[2].conversation_id for item in captured}) == len(sources)
        for (_agent_name, agent, request), source_type in zip(captured, sources):
            assert agent["persistent_agent_sessions"] is False
            assert agent["warm_session_prompt_cache"] is False
            assert agent["agent_runtime_shared_sessions"] is False
            assert agent["agent_runtime_session_scope"] == "conversation"
            assert agent["ephemeral"] is True
            if source_type == "ops-salesforce-ticket-investigation":
                assert agent["sandbox"] == "read-only"
            assert source_type in request.conversation_id
            assert str(request.job_id) in request.conversation_id
    finally:
        runtime.executor.shutdown(wait=True)


def test_singapore_ticket_precursor_blockers_and_failures_never_enter_review(tmp_path, monkeypatch):
    runtime = _runtime(tmp_path)
    runtime.config = SimpleNamespace(defaults={}, agents={"agent_a": {}})
    eligible_group = {
        "stableKey": "singapore-remediation:new_interface_request:test:key",
        "category": "new_interface_request",
        "requestKind": "new_interface",
    }
    for bridge_job_id, job_key in ((31, "blocked-ticket"), (32, "failed-ticket")):
        runtime._jobs[job_key] = {
            "id": job_key,
            "bridgeJobId": bridge_job_id,
            "status": "queued",
            "phase": "queued",
            "agentName": "agent_a",
            "sourceType": "ops-singapore-remediation-ticket",
            "payload": {
                "stableKey": eligible_group["stableKey"],
                "remediationGroup": dict(eligible_group),
            },
            "prompt": "create the verified new-interface ticket",
        }
        runtime.state.rows[bridge_job_id] = {
            "id": bridge_job_id,
            "event_id": job_key,
            "channel_id": "command_center",
            "status": "queued",
        }

    runtime._runtime_memory = lambda *_args: ""
    runtime._store_learning_observation = lambda *_args, **_kwargs: None
    runtime._append_chat = lambda *_args, **_kwargs: None
    runtime._register_recent_artifacts = lambda *_args, **_kwargs: None
    runtime._sync_review_packet_after_job = lambda *_args, **_kwargs: None
    runtime._sync_drawing_board_after_job = lambda *_args, **_kwargs: None
    monkeypatch.setattr(
        "codex_slack_bridge.command_center_server.sign_trusted_message",
        lambda **_kwargs: "signature",
    )

    outcomes = iter(("BLOCKED: ticket lookup needs more evidence", RuntimeError("worker unavailable")))

    def fake_run(*_args, **_kwargs):
        outcome = next(outcomes)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr("codex_slack_bridge.command_center_server.run_agent_isolated", fake_run)
    try:
        blocked = runtime._run_job("agent_a", "blocked", "blocked-ticket", 31)
        failed = runtime._run_job("agent_a", "failed", "failed-ticket", 32)

        assert blocked.startswith("BLOCKED:")
        assert "command center job failed" in failed
        assert runtime.state.review_required == {31: False, 32: False}
        assert runtime._jobs["blocked-ticket"]["needsReview"] is False
        assert runtime._jobs["blocked-ticket"]["reviewReason"] == ""
        assert runtime._jobs["failed-ticket"]["needsReview"] is False
        assert runtime._jobs["failed-ticket"]["reviewReason"] == ""
    finally:
        runtime.executor.shutdown(wait=True)


def test_no_manifest_recovery_readmits_queued_once_and_quarantines_running(tmp_path):
    runtime = _runtime(tmp_path)
    runtime.config = SimpleNamespace(defaults={}, agents={"agent_a": {}})
    queued = {
        "id": "queued",
        "bridgeJobId": 11,
        "status": "queued",
        "phase": "queued",
        "agentName": "agent_a",
        "sourceType": "dispatch",
        "prompt": "queued work",
        "payload": {},
        "runnerType": "agent",
    }
    running = {**queued, "id": "running", "bridgeJobId": 12, "status": "running", "phase": "running_model"}
    terminal = {**queued, "id": "terminal", "bridgeJobId": 13, "status": "completed", "phase": "completed"}
    for record in (queued, running, terminal):
        runtime._write_job(record)
    (runtime.jobs_dir / "corrupt.json").write_text("{not-json", encoding="utf-8")
    runtime.state.rows = {
        11: {"id": 11, "event_id": "queued", "channel_id": "command_center", "status": "queued"},
        12: {"id": 12, "event_id": "running", "channel_id": "command_center", "status": "running"},
        13: {"id": 13, "event_id": "terminal", "channel_id": "command_center", "status": "completed"},
        14: {"id": 14, "event_id": "corrupt", "channel_id": "command_center", "status": "queued"},
    }
    scheduled: list[str] = []
    runtime._schedule_job = lambda job_key, _work_item: scheduled.append(job_key)
    try:
        runtime._recover_unmanaged_durable_jobs()
        runtime._recover_unmanaged_durable_jobs()
        assert scheduled == ["running", "queued"]
        assert runtime._jobs["running"]["status"] == "queued"
        assert runtime._jobs["running"]["phase"] == "restart_recovery_queued"
        assert "terminal" not in runtime._jobs
        assert "corrupt" not in runtime._jobs
        assert ("recovery_queued", 12) in runtime.state.transitions
    finally:
        runtime.executor.shutdown(wait=True)


def test_restart_manifest_closes_handoff_parent_when_durable_child_is_terminal(tmp_path):
    runtime = _runtime(tmp_path)
    runtime.config = SimpleNamespace(defaults={}, agents={"coding_agent": {}})
    runtime._append_chat = lambda *_args, **_kwargs: None
    parent = {
        "id": "stale-parent",
        "bridgeJobId": 61,
        "status": "running",
        "phase": "handoff_acknowledged",
        "agentName": "coding_agent",
        "sourceType": "agent-handoff-operator-continuation",
        "handoffTargetAgent": "billing_agent",
        "handoffChildJobId": "terminal-child",
        "payload": {
            "sourceAgent": "billing_agent",
            "sourceJobId": "origin-job",
            "sourceBridgeJobId": 60,
            "originAgent": "billing_agent",
            "originJobId": "origin-job",
            "originBridgeJobId": 60,
        },
        "prompt": "continue through the owning lane",
        "runnerType": "agent",
    }
    runtime._write_job(parent)
    runtime.state.rows = {
        61: {
            "id": 61,
            "event_id": "stale-parent",
            "channel_id": "command_center",
            "status": "running",
        },
        62: {
            "id": 62,
            "event_id": "terminal-child",
            "channel_id": "command_center",
            "agent_name": "billing_agent",
            "status": "failed",
            "completed_at": 1785880800.0,
            "result_text": "FAILED\nThe bounded continuation depth was exhausted.",
        },
    }
    runtime.pause_manifest_path.write_text(
        json.dumps(
            {
                "state": "paused",
                "resumeAfterRestart": True,
                "pendingRecoveryJobIds": ["stale-parent"],
                "jobs": [parent],
            }
        ),
        encoding="utf-8",
    )
    try:
        runtime._recover_pause_manifest()

        assert runtime._jobs["stale-parent"]["status"] == "failed"
        assert runtime._jobs["stale-parent"]["phase"] == "failed"
        assert runtime._jobs["stale-parent"]["handoffTerminalChildJobId"] == "terminal-child"
        assert runtime.state.rows[61]["status"] == "failed"
        manifest = json.loads(runtime.pause_manifest_path.read_text(encoding="utf-8"))
        assert manifest["state"] == "recovery_complete"
        assert manifest["recoveredJobIds"] == []
        assert manifest["skippedTerminalJobIds"] == ["stale-parent"]
    finally:
        runtime.executor.shutdown(wait=True)


def test_no_manifest_recovery_cancels_disabled_billing_reconciliation(tmp_path):
    runtime = _runtime(tmp_path)
    runtime.config = SimpleNamespace(
        defaults={"ops_salesforce_billing_reconciliation_enabled": False},
        agents={"billing_agent": {}},
    )
    record = {
        "id": "billing-reconcile",
        "bridgeJobId": 21,
        "status": "queued",
        "phase": "queued",
        "agentName": "billing_agent",
        "sourceType": "ops-salesforce-billing-reconciliation",
        "prompt": "reconcile",
        "payload": {},
        "runnerType": "agent",
    }
    runtime._write_job(record)
    runtime.state.rows[21] = {
        "id": 21,
        "event_id": "billing-reconcile",
        "channel_id": "command_center",
        "status": "queued",
    }
    runtime._schedule_job = lambda *_args, **_kwargs: (_ for _ in ()).throw(
        AssertionError("disabled routine must not recover")
    )
    try:
        runtime._recover_unmanaged_durable_jobs()
        assert runtime._jobs["billing-reconcile"]["status"] == "cancelled"
        assert runtime.state.rows[21]["status"] == "cancelled"
        assert ("cancelled", 21) in runtime.state.transitions
    finally:
        runtime.executor.shutdown(wait=True)


def test_executor_submit_failure_rolls_back_lane_and_terminalizes_job(tmp_path):
    runtime = _runtime(tmp_path)
    runtime.executor.shutdown(wait=True)

    class RejectingExecutor:
        def submit(self, *_args, **_kwargs):
            raise RuntimeError("executor unavailable")

    runtime.executor = RejectingExecutor()
    record = {
        "id": "rejected",
        "bridgeJobId": 15,
        "status": "queued",
        "phase": "queued",
        "agentName": "agent_a",
        "sourceType": "dispatch",
        "prompt": "work",
        "runnerType": "agent",
    }
    runtime._jobs[record["id"]] = record
    runtime._schedule_job(record["id"], {"runnerType": "agent"})
    assert runtime._jobs["rejected"]["status"] == "failed"
    assert runtime._inflight_count == 0
    assert runtime._lane_running == set()
    assert runtime._futures == {}
    assert ("failed", 15) in runtime.state.transitions
    assert runtime._jobs["rejected"]["needsReview"] is False
    assert runtime.state.review_required[15] is False


def test_direct_chat_executor_failure_stays_in_chat_without_review(tmp_path):
    runtime = _runtime(tmp_path)
    runtime.executor.shutdown(wait=True)

    class RejectingExecutor:
        def submit(self, *_args, **_kwargs):
            raise RuntimeError("executor unavailable")

    runtime.executor = RejectingExecutor()
    chat_events: list[tuple[str, str]] = []
    runtime._append_chat = lambda _agent, role, text, _job, _bridge, **_kwargs: chat_events.append((role, text))
    record = {
        "id": "direct-rejected",
        "bridgeJobId": 115,
        "status": "queued",
        "phase": "queued",
        "agentName": "agent_a",
        "sourceType": "agent-direct-chat",
        "prompt": "work",
        "runnerType": "agent",
    }
    runtime._jobs[record["id"]] = record

    runtime._schedule_job(record["id"], {"runnerType": "agent"})

    assert runtime._jobs["direct-rejected"]["status"] == "failed"
    assert runtime._jobs["direct-rejected"]["needsReview"] is False
    assert runtime.state.review_required[115] is False
    assert len(chat_events) == 1
    assert chat_events[0][0] == "assistant"
    assert chat_events[0][1].startswith("FAILED")


def test_singapore_rejected_start_terminalizes_without_review_packet(tmp_path):
    runtime = _runtime(tmp_path)
    runtime.state.start_allowed = False
    runtime._jobs["singapore"] = {
        "id": "singapore",
        "bridgeJobId": 16,
        "status": "queued",
        "phase": "queued",
        "agentName": "coding_agent",
        "sourceType": "ops-singapore-ftp",
        "runnerType": "singapore_fast_path",
    }
    runtime.state.rows[16] = {
        "id": 16,
        "event_id": "singapore",
        "channel_id": "command_center",
        "status": "queued",
    }
    try:
        result = runtime._run_singapore_ftp_fast_job(
            "singapore",
            16,
            "uploader",
            "state",
            "servers",
            [],
            False,
            "ops.env",
            "julio",
        )
        assert result == "Discarded stale Singapore FTP attempt before start."
        assert runtime._jobs["singapore"]["status"] == "recovery_review_required"
        assert runtime._jobs["singapore"].get("needsReview") in {None, False}
        assert runtime.state.review_required.get(16) is not True
    finally:
        runtime.executor.shutdown(wait=True)


def test_paused_watcher_loop_does_not_invoke_submission_target(tmp_path):
    runtime = _runtime(tmp_path)
    runtime._paused = True
    calls: list[int] = []
    thread = Thread(
        target=runtime._watch_forever,
        args=("ops-test-watch", 0, 0.01, calls.append),
        daemon=True,
    )
    thread.start()
    time.sleep(0.05)
    runtime._watch_stop.set()
    thread.join(timeout=1)
    try:
        assert calls == []
    finally:
        runtime.executor.shutdown(wait=True)


def test_closed_automation_window_does_not_invoke_background_target(tmp_path, monkeypatch):
    runtime = _runtime(tmp_path)
    calls: list[int] = []
    monkeypatch.setattr(command_center_server, "automation_window_open", lambda _defaults: False)
    thread = Thread(
        target=runtime._watch_forever,
        args=("ops-test-watch", 0, 0.01, calls.append),
        daemon=True,
    )
    thread.start()
    time.sleep(0.05)
    runtime._watch_stop.set()
    thread.join(timeout=1)
    try:
        assert calls == []
    finally:
        runtime.executor.shutdown(wait=True)


def test_runtime_health_watcher_bypasses_closed_automation_window(tmp_path, monkeypatch):
    runtime = _runtime(tmp_path)
    calls: list[int] = []
    monkeypatch.setattr(command_center_server, "automation_window_open", lambda _defaults: False)
    thread = Thread(
        target=runtime._watch_forever,
        args=("agent-runtime-health-watch", 0, 0.01, calls.append, True, True),
        daemon=True,
    )
    thread.start()
    time.sleep(0.05)
    runtime._watch_stop.set()
    thread.join(timeout=1)
    try:
        assert calls
    finally:
        runtime.executor.shutdown(wait=True)


def test_open_background_watcher_marks_submitted_work_as_unattended(tmp_path, monkeypatch):
    runtime = _runtime(tmp_path)
    markers: list[bool] = []
    monkeypatch.setattr(runtime, "_unattended_automation_open", lambda: True)

    def target(_interval):
        markers.append(bool(getattr(current_thread(), "nova_unattended_automation", False)))
        runtime._watch_stop.set()

    try:
        runtime._watch_forever("ops-test-watch", 0, 0.01, target)
        assert markers == [True]
        assert not bool(getattr(current_thread(), "nova_unattended_automation", False))
    finally:
        runtime.executor.shutdown(wait=True)


def test_queued_unattended_work_waits_outside_window(tmp_path, monkeypatch):
    runtime = _runtime(tmp_path)
    monkeypatch.setattr(runtime, "_unattended_automation_open", lambda: False)
    runtime._jobs["auto"] = {
        "id": "auto",
        "status": "queued",
        "agentName": "coding_agent",
        "sourceType": "ops-kpi-dashboard",
        "payload": {},
    }
    thread = current_thread()
    prior_marker = getattr(thread, "nova_unattended_automation", False)
    thread.nova_unattended_automation = True
    try:
        runtime._schedule_job("auto", {"runnerType": "agent"})
        assert runtime._jobs["auto"]["unattendedAutomation"] is True
        assert runtime._jobs["auto"]["phase"] == "waiting_automation_window"
        assert "auto" not in runtime._futures
        assert "auto" in runtime._lane_queues["coding_agent:background"]
    finally:
        thread.nova_unattended_automation = prior_marker
        runtime.executor.shutdown(wait=True)


def test_manual_background_run_remains_admissible_outside_window(tmp_path, monkeypatch):
    runtime = _runtime(tmp_path)
    original_executor = runtime.executor
    original_executor.shutdown(wait=True)
    submitted: list[tuple[object, str]] = []

    class PendingExecutor:
        def submit(self, callback, job_key):
            submitted.append((callback, job_key))
            return Future()

    runtime.executor = PendingExecutor()
    monkeypatch.setattr(runtime, "_unattended_automation_open", lambda: False)
    runtime._jobs["manual"] = {
        "id": "manual",
        "status": "queued",
        "agentName": "coding_agent",
        "sourceType": "ops-kpi-dashboard",
        "payload": {},
    }

    runtime._schedule_job("manual", {"runnerType": "agent"})

    assert runtime._jobs["manual"]["unattendedAutomation"] is False
    assert runtime._jobs["manual"]["phase"] == "admitted_to_worker"
    assert submitted and submitted[0][1] == "manual"


def test_pause_resume_and_status_http_endpoints():
    calls: list[tuple[str, object]] = []

    class Runtime:
        def runtime_control_status(self):
            return {"ok": True, "paused": True}

        def pause_for_restart(self, *, reason, resume_after_restart):
            calls.append((reason, resume_after_restart))
            return {"ok": True, "paused": True}

        def resume(self):
            calls.append(("resume", None))
            return {"ok": True, "paused": False}

    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(Runtime()))
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        with urllib.request.urlopen(f"{base_url}/runtime/pause/status", timeout=2) as response:
            assert json.load(response)["paused"] is True
        pause_request = urllib.request.Request(
            f"{base_url}/runtime/pause",
            data=json.dumps({"reason": "deploy", "resumeAfterRestart": True}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(pause_request, timeout=2) as response:
            assert json.load(response)["paused"] is True
        resume_request = urllib.request.Request(f"{base_url}/runtime/resume", data=b"{}", method="POST")
        with urllib.request.urlopen(resume_request, timeout=2) as response:
            assert json.load(response)["paused"] is False
        assert calls == [("deploy", True), ("resume", None)]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
