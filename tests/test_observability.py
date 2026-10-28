from __future__ import annotations

import json
import os

from codex_slack_bridge.agent_runtime import AgentSessionStore
from codex_slack_bridge.config import BridgeConfig
from codex_slack_bridge.observability import build_system_status, format_system_status_for_slack
from codex_slack_bridge.state import BridgeState


def _config(tmp_path):
    return BridgeConfig(
        defaults={
            "max_workers": 2,
            "agent_runtime_session_store_path": str(tmp_path / "sessions.jsonl"),
            "agent_runtime_lock_root": str(tmp_path / "locks"),
            "agent_runtime_shared_sessions": True,
            "agent_runtime_session_scope": "agent",
            "agent_runtime_lock_stale_seconds": 7200,
        },
        channels={},
        agents={
            "coding_agent": {
                "provider": "codex_cli",
                "workspace_root": str(tmp_path),
                "sandbox": "danger-full-access",
            }
        },
    )


def test_system_status_includes_active_jobs_and_sessions(tmp_path):
    config = _config(tmp_path)
    state = BridgeState(str(tmp_path / "bridge.sqlite3"))
    job_id = state.create_job(
        event_id="event-1",
        channel_id="C123",
        thread_ts="123.456",
        user_id="U123",
        agent_name="coding_agent",
        request_text="Check the deployment status",
    )
    state.mark_started(job_id)

    AgentSessionStore(tmp_path / "sessions.jsonl").upsert(
        agent_name="coding_agent",
        surface="shared",
        conversation_id="agent:coding_agent",
        provider="codex_cli",
        workspace=str(tmp_path),
        session_id="12345678-1234-1234-1234-123456789abc",
        status="running",
        job_id=job_id,
    )

    snapshot = build_system_status(config, state, bridge_started_at=0, limit=10)
    text = format_system_status_for_slack(snapshot)

    assert snapshot["bridgeJobs"]["counts"]["running"] == 1
    assert snapshot["bridgeJobs"]["active"][0]["agentName"] == "coding_agent"
    assert snapshot["sessions"][0]["sessionId"].startswith("12345678")
    assert "Active bridge jobs" in text
    assert "coding_agent" in text
    assert "Check the deployment status" in text


def test_system_status_includes_runtime_lock_owner(tmp_path):
    config = _config(tmp_path)
    state = BridgeState(str(tmp_path / "bridge.sqlite3"))
    lock_root = tmp_path / "locks"
    lock_root.mkdir()
    lock_path = lock_root / "coding_agent__shared__agent_coding_agent.lock"
    lock_path.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "token": "token-123",
                "pid": os.getpid(),
                "owner": {
                    "agentName": "coding_agent",
                    "surface": "slack",
                    "jobId": 42,
                },
            }
        ),
        encoding="utf-8",
    )

    snapshot = build_system_status(config, state, limit=10)
    text = format_system_status_for_slack(snapshot)

    assert snapshot["locks"][0]["owner"]["agentName"] == "coding_agent"
    assert snapshot["locks"][0]["processAlive"] is True
    assert "Runtime locks" in text
    assert "coding_agent" in text


def test_system_status_uses_thor_public_name_without_changing_snapshot(tmp_path):
    config = BridgeConfig(
        defaults={
            "max_workers": 2,
            "agent_runtime_session_store_path": str(tmp_path / "sessions.jsonl"),
            "agent_runtime_lock_root": str(tmp_path / "locks"),
            "agent_runtime_shared_sessions": True,
            "agent_runtime_session_scope": "agent",
            "agent_runtime_lock_stale_seconds": 7200,
        },
        channels={},
        agents={
            "claude_agent": {
                "provider": "codex_cli",
                "workspace_root": str(tmp_path),
                "sandbox": "read-only",
            }
        },
    )
    state = BridgeState(str(tmp_path / "bridge.sqlite3"))
    job_id = state.create_job(
        event_id="event-thor",
        channel_id="C-THOR",
        thread_ts="",
        user_id="U123",
        agent_name="claude_agent",
        request_text="Confirm Thor status",
    )
    state.mark_started(job_id)

    snapshot = build_system_status(config, state, bridge_started_at=0, limit=10)
    text = format_system_status_for_slack(snapshot)

    assert snapshot["bridgeJobs"]["active"][0]["agentName"] == "claude_agent"
    assert "`Thor`" in text
    assert "claude_agent" not in text.casefold()
    assert "claude agent" not in text.casefold()
