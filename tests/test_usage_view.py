from __future__ import annotations

"""Tests for the token-usage view surfaced in the command-center API.

The /usage endpoint aggregates per-job Codex usage into a per-agent total.
These tests exercise the real usage_summary() method against a minimal
jobs() stub (usage_summary only depends on self.jobs() returning job dicts
that may carry a usage blob), keeping the unit test light.
"""

from codex_slack_bridge.command_center_server import CommandCenterRuntime

USAGE = {
    "input_tokens": 2000,
    "cached_input_tokens": 500,
    "output_tokens": 1000,
    "reasoning_output_tokens": 80,
    "total_tokens": 3000,
    "estimated_cost_usd": 0.006,
}


def _stub(jobs):
    stub = object.__new__(CommandCenterRuntime)
    stub.jobs = lambda **kw: {"ok": True, "jobs": jobs, "count": len(jobs)}
    return stub


def test_usage_summary_aggregates_per_agent():
    stub = _stub(
        [
            {"id": "1", "bridgeJobId": 1000, "agentName": "coding_agent", "status": "done", "usage": dict(USAGE)},
            {"id": "2", "bridgeJobId": 1001, "agentName": "billing_agent", "status": "done", "usage": dict(USAGE)},
            {"id": "3", "bridgeJobId": 1002, "agentName": "coding_agent", "status": "done", "usage": dict(USAGE)},
        ]
    )
    summary = stub.usage_summary(limit=200)
    assert summary["ok"] is True
    assert set(summary["perAgent"]) == {"coding_agent", "billing_agent"}
    # coding_agent ran twice => double the single-job usage
    assert summary["perAgent"]["coding_agent"]["total_tokens"] == 6000
    assert summary["perAgent"]["coding_agent"]["input_tokens"] == 4000
    assert summary["perAgent"]["billing_agent"]["total_tokens"] == 3000
    assert summary["total"]["total_tokens"] == 9000
    assert summary["total"]["estimated_cost_usd"] == 0.018
    assert summary["count"] == 3
    assert len(summary["rows"]) == 3


def test_usage_summary_ignores_jobs_without_usage():
    stub = _stub(
        [
            {"id": "1", "bridgeJobId": 1000, "agentName": "coding_agent", "usage": dict(USAGE)},
            {"id": "2", "bridgeJobId": 1001, "agentName": "billing_agent"},  # no usage
            {"id": "3", "bridgeJobId": 1002, "agentName": "tickets_agent", "usage": {}},  # empty usage
        ]
    )
    summary = stub.usage_summary(limit=200)
    assert summary["count"] == 1
    assert set(summary["perAgent"]) == {"coding_agent"}


def test_usage_summary_filters_by_agent():
    stub = _stub(
        [
            {"id": "1", "agentName": "coding_agent", "usage": dict(USAGE)},
            {"id": "2", "agentName": "billing_agent", "usage": dict(USAGE)},
        ]
    )
    filtered = stub.usage_summary(limit=200, agent_name="billing_agent")
    assert filtered["count"] == 1
    assert set(filtered["perAgent"]) == {"billing_agent"}
    # total reflects only the filtered agent's usage
    assert filtered["total"]["total_tokens"] == 3000