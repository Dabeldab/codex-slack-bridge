from __future__ import annotations

import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event

from codex_slack_bridge.agent_readiness import (
    AgentProviderReadiness,
    sanitize_readiness_snapshot,
)


def _agents() -> dict[str, dict[str, object]]:
    return {
        "claude_agent": {
            "provider": "codex_cli",
            "codex_executable": "/usr/local/bin/codex",
            "codex_command_prefix": [
                "/usr/bin/sudo",
                "-n",
                "-H",
                "-u",
                "nova-claude",
                "--",
            ],
        }
    }


def test_readiness_uses_lane_identity_and_returns_only_sanitized_status():
    calls = []

    def execute(command, timeout):
        calls.append((command, timeout))
        return 0

    probe = AgentProviderReadiness(
        _agents(),
        executor=execute,
        clock=lambda: 1000.0,
    )

    result = probe.ensure_ready("claude_agent")

    assert result == {
        "agentName": "claude_agent",
        "provider": "codex_cli",
        "ready": True,
        "status": "ready",
        "checkedAtUtc": "1970-01-01T00:16:40Z",
        "ageSeconds": 0,
        "stale": False,
    }
    assert calls == [
        (
            [
                "/usr/bin/sudo",
                "-n",
                "-H",
                "-u",
                "nova-claude",
                "--",
                "/usr/local/bin/codex",
                "login",
                "status",
            ],
            10.0,
        )
    ]
    assert "auth" not in repr(result).lower()
    assert "credential" not in repr(result).lower()


def test_readiness_failure_is_cached_briefly_then_reprobed():
    now = [1000.0]
    returncodes = iter([1, 0])
    calls = []

    def execute(command, timeout):
        calls.append(command)
        return next(returncodes)

    probe = AgentProviderReadiness(
        _agents(),
        executor=execute,
        failure_ttl_seconds=30,
        clock=lambda: now[0],
    )

    assert probe.ensure_ready("claude_agent")["status"] == "not_authenticated"
    now[0] += 20
    assert probe.ensure_ready("claude_agent")["status"] == "not_authenticated"
    assert len(calls) == 1
    now[0] += 11
    assert probe.ensure_ready("claude_agent")["status"] == "ready"
    assert len(calls) == 2


def test_readiness_timeout_fails_closed_without_error_text():
    def execute(_command, timeout):
        raise subprocess.TimeoutExpired(cmd=["secret-bearing-command"], timeout=timeout)

    probe = AgentProviderReadiness(_agents(), executor=execute, clock=lambda: 1000.0)

    result = probe.ensure_ready("claude_agent")

    assert result["ready"] is False
    assert result["status"] == "probe_timeout"
    assert "secret" not in repr(result).lower()


def test_probe_failure_state_is_sanitized_and_cached_for_failure_ttl():
    calls = []

    def execute(_command, _timeout):
        calls.append(True)
        raise RuntimeError("credential path C:/secret/auth.json")

    probe = AgentProviderReadiness(
        _agents(),
        executor=execute,
        failure_ttl_seconds=30,
        clock=lambda: 1000.0,
    )

    first = probe.ensure_ready("claude_agent")
    second = probe.ensure_ready("claude_agent")

    assert first["status"] == "probe_failed"
    assert first["stale"] is False
    assert second == first
    assert calls == [True]
    assert "auth.json" not in repr(first)


def test_readiness_snapshot_marks_unprobed_and_unknown_lanes_fail_closed():
    probe = AgentProviderReadiness(_agents(), executor=lambda _command, _timeout: 0)

    snapshot = probe.snapshot()
    unknown = probe.ensure_ready("not_an_agent")

    assert snapshot["claude_agent"]["status"] == "not_checked"
    assert snapshot["claude_agent"]["stale"] is True
    assert unknown["status"] == "unknown_agent"
    assert unknown["ready"] is False


def test_readiness_rejects_unsupported_provider_without_running_a_command():
    calls = []
    probe = AgentProviderReadiness(
        {"legacy": {"provider": "claude_cli"}},
        executor=lambda command, timeout: calls.append((command, timeout)) or 0,
        clock=lambda: 1000.0,
    )

    result = probe.ensure_ready("legacy")

    assert result["ready"] is False
    assert result["status"] == "unsupported_provider"
    assert calls == []


def test_forced_readiness_recheck_does_not_reuse_a_fresh_success():
    returncodes = iter([0, 1])
    calls = []
    probe = AgentProviderReadiness(
        _agents(),
        executor=lambda command, _timeout: calls.append(command) or next(returncodes),
        clock=lambda: 1000.0,
    )

    assert probe.ensure_ready("claude_agent")["ready"] is True
    result = probe.ensure_ready("claude_agent", force_refresh=True)

    assert result["ready"] is False
    assert result["status"] == "not_authenticated"
    assert len(calls) == 2


def test_same_agent_forced_probes_are_single_flight():
    callers_ready = Barrier(2)
    executor_started = Event()
    release_executor = Event()
    calls = []

    def execute(command, _timeout):
        calls.append(command)
        executor_started.set()
        assert release_executor.wait(1)
        return 0

    probe = AgentProviderReadiness(_agents(), executor=execute)

    def check():
        callers_ready.wait()
        return probe.ensure_ready("claude_agent", force_refresh=True)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(check) for _ in range(2)]
        assert executor_started.wait(1)
        deadline = time.monotonic() + 1
        while time.monotonic() < deadline:
            with probe._lock:
                if probe._probe_waiters.get("claude_agent") == 1:
                    break
            time.sleep(0.005)
        with probe._lock:
            assert probe._probe_waiters.get("claude_agent") == 1
        release_executor.set()
        results = [future.result(timeout=1) for future in futures]

    assert len(calls) == 1
    assert all(item["ready"] is True for item in results)


def test_periodic_refresh_reprobes_before_success_ttl_expires():
    probed_at = []

    def execute(_command, _timeout):
        probed_at.append(time.monotonic())
        return 0

    probe = AgentProviderReadiness(
        _agents(),
        executor=execute,
        success_ttl_seconds=0.3,
        failure_ttl_seconds=0.3,
        periodic_max_sleep_seconds=0.02,
    )
    assert probe.start_periodic_refresh() is True
    deadline = time.monotonic() + 1.5
    try:
        while len(probed_at) < 2 and time.monotonic() < deadline:
            time.sleep(0.01)
    finally:
        probe.stop_periodic_refresh(wait=True)

    assert len(probed_at) >= 2
    assert probed_at[1] - probed_at[0] < 0.3


def test_snapshot_sanitizer_drops_unexpected_health_fields_and_states():
    result = sanitize_readiness_snapshot(
        {
            "claude_agent": {
                "agentName": "claude_agent",
                "provider": "codex_cli",
                "ready": True,
                "status": "token=should-not-leak",
                "checkedAtUtc": "not-a-timestamp",
                "ageSeconds": "secret",
                "stale": False,
                "credentialPath": "C:/secret/auth.json",
            }
        }
    )

    assert result == {
        "claude_agent": {
            "agentName": "claude_agent",
            "provider": "codex_cli",
            "ready": False,
            "status": "probe_failed",
            "checkedAtUtc": None,
            "ageSeconds": None,
            "stale": True,
        }
    }
