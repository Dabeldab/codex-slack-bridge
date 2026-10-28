import pytest

from codex_slack_bridge.github_agent_relay import RelayRequestError
from codex_slack_bridge.github_agent_relay_wait import WaitRelay, task_timeout


def test_task_timeout_is_bounded_for_cloud_run_request():
    assert task_timeout(30) == 30
    assert task_timeout("900") == 900
    assert task_timeout(1800) == 1800
    for value in (29, 1801, "nope"):
        with pytest.raises(RelayRequestError):
            task_timeout(value)


def test_wait_relay_returns_terminal_job_without_external_reauthentication():
    relay = WaitRelay(None)
    relay.submit = lambda raw: {
        "ok": True,
        "task_id": raw["task_id"],
        "job_id": "job-123456",
        "agent": "direct_codex",
        "agent_label": "Rory",
        "status": "queued",
    }
    relay.job = lambda job_id: {
        "ok": True,
        "job_id": job_id,
        "status": "completed",
        "terminal": True,
        "result": "COMPLETED\nHealthy.",
    }
    heartbeats = []
    result = relay.run(
        {"task_id": "chatgpt-20260917-002", "timeout_seconds": 30},
        heartbeat=lambda: heartbeats.append(True),
    )
    assert result["relay_status"] == "completed"
    assert result["job"]["result"] == "COMPLETED\nHealthy."
    assert heartbeats == [True]
