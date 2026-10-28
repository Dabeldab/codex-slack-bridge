import json
import os
import time

# AgentChat/coding_agent 2026-07-11T11:32:00-04:00
# AgentChat/direct_codex 2026-07-13T00:16:00-04:00

from codex_slack_bridge import agent_runtime


def test_remove_stale_lock_removes_exited_owner_after_short_grace(tmp_path, monkeypatch):
    lock_path = tmp_path / "coding_agent.lock"
    lock_path.write_text(
        json.dumps({"schemaVersion": 1, "pid": 999999, "token": "dead-owner"}),
        encoding="utf-8",
    )
    old_time = time.time() - 35
    os.utime(lock_path, (old_time, old_time))
    monkeypatch.setattr(agent_runtime, "_process_exists", lambda pid: False)

    assert agent_runtime._remove_stale_lock(lock_path, stale_seconds=7200) is True
    assert not lock_path.exists()


def test_remove_stale_lock_keeps_recent_dead_owner_during_grace(tmp_path, monkeypatch):
    lock_path = tmp_path / "coding_agent.lock"
    lock_path.write_text(
        json.dumps({"schemaVersion": 1, "pid": 999999, "token": "dead-owner"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(agent_runtime, "_process_exists", lambda pid: False)

    assert agent_runtime._remove_stale_lock(lock_path, stale_seconds=7200) is False
    assert lock_path.exists()


def test_remove_stale_lock_keeps_live_owner_until_full_stale_timeout(tmp_path, monkeypatch):
    lock_path = tmp_path / "coding_agent.lock"
    lock_path.write_text(
        json.dumps({"schemaVersion": 1, "pid": os.getpid(), "token": "live-owner"}),
        encoding="utf-8",
    )
    old_time = time.time() - 35
    os.utime(lock_path, (old_time, old_time))
    monkeypatch.setattr(agent_runtime, "_process_exists", lambda pid: True)

    assert agent_runtime._remove_stale_lock(lock_path, stale_seconds=7200) is False
    assert lock_path.exists()


def test_remove_stale_lock_never_evicts_live_owner_by_age(tmp_path, monkeypatch):
    lock_path = tmp_path / "coding_agent.lock"
    lock_path.write_text(
        json.dumps({"schemaVersion": 1, "pid": os.getpid(), "token": "live-owner"}),
        encoding="utf-8",
    )
    old_time = time.time() - 10_000
    os.utime(lock_path, (old_time, old_time))
    monkeypatch.setattr(agent_runtime, "_process_exists", lambda pid: True)

    assert agent_runtime._remove_stale_lock(lock_path, stale_seconds=60) is False
    assert lock_path.exists()


def test_remove_stale_lock_detects_reused_pid_from_process_start(tmp_path, monkeypatch):
    lock_path = tmp_path / "coding_agent.lock"
    lock_path.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "pid": os.getpid(),
                "processStartedAt": 100.0,
                "token": "old-process",
            }
        ),
        encoding="utf-8",
    )
    old_time = time.time() - 35
    os.utime(lock_path, (old_time, old_time))
    monkeypatch.setattr(agent_runtime, "_process_exists", lambda pid: True)
    monkeypatch.setattr(agent_runtime, "_process_started_at", lambda pid: 200.0)

    assert agent_runtime._remove_stale_lock(lock_path, stale_seconds=7200) is True
    assert not lock_path.exists()


def test_remove_stale_lock_keeps_gateway_lease_when_only_cli_child_is_dead(tmp_path, monkeypatch):
    lock_path = tmp_path / "coding_agent.lock"
    lock_path.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "pid": os.getpid(),
                "processStartedAt": 100.0,
                "childPid": 424242,
                "childProcessStartedAt": 200.0,
                "token": "dead-child",
            }
        ),
        encoding="utf-8",
    )
    old_time = time.time() - 35
    os.utime(lock_path, (old_time, old_time))
    monkeypatch.setattr(
        agent_runtime,
        "_process_matches",
        lambda pid, started_at: pid == os.getpid(),
    )

    assert agent_runtime._remove_stale_lock(lock_path, stale_seconds=7200) is False
    assert lock_path.exists()


def test_runtime_lock_records_cli_child_process(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_runtime, "_process_started_at", lambda pid: float(pid))
    lock = agent_runtime.AgentRuntimeLock.acquire(
        root=tmp_path,
        lock_key="coding-agent",
        owner={"jobId": 7},
        wait_seconds=1,
        stale_seconds=60,
    )
    lock.set_child_process(4242)

    item = json.loads(lock.path.read_text(encoding="utf-8"))
    assert item["childPid"] == 4242
    assert item["childProcessStartedAt"] == 4242.0
    lock.release()


def test_remove_stale_lock_keeps_malformed_lock_until_configured_timeout(tmp_path):
    lock_path = tmp_path / "coding_agent.lock"
    lock_path.write_text(json.dumps({"schemaVersion": 1, "token": "partial"}), encoding="utf-8")
    old_time = time.time() - 35
    os.utime(lock_path, (old_time, old_time))

    assert agent_runtime._remove_stale_lock(lock_path, stale_seconds=7200) is False
    assert lock_path.exists()


def test_session_store_round_trips_static_prompt_fingerprint(tmp_path):
    store = agent_runtime.AgentSessionStore(tmp_path / "sessions.jsonl")
    store.upsert(
        agent_name="coding_agent",
        surface="shared",
        conversation_id="agent:coding_agent",
        provider="codex_cli",
        workspace=str(tmp_path),
        session_id="session-123",
        status="completed",
        prompt_fingerprint="fingerprint-abc",
    )

    record = store.get(
        agent_name="coding_agent",
        surface="shared",
        conversation_id="agent:coding_agent",
    )

    assert record is not None
    assert record.prompt_fingerprint == "fingerprint-abc"


def test_session_store_compacts_to_latest_record_per_runtime_key(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_runtime, "SESSION_STORE_COMPACT_BYTES", 1)
    store = agent_runtime.AgentSessionStore(tmp_path / "sessions.jsonl")
    for status in ("queued", "running", "completed"):
        store.upsert(
            agent_name="coding_agent",
            surface="shared",
            conversation_id="agent:coding_agent",
            provider="codex_cli",
            workspace=str(tmp_path),
            session_id="session-123",
            status=status,
        )

    lines = store.path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["status"] == "completed"


def test_poisoned_resume_detects_truncated_session_bootstrap_without_response():
    stderr = """OpenAI Codex v0.144.1
session id: 019f4446-3de0-76d0-a261-4032fdfb3562
user
very large prior prompt
[truncated]"""

    assert agent_runtime.looks_like_poisoned_resume(stderr, "", "") is True
    assert agent_runtime.looks_like_poisoned_resume(stderr, "completed", "") is False
    assert agent_runtime.looks_like_poisoned_resume(stderr, "", "completed") is False
