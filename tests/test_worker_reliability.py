"""Focused reliability policy tests.

AgentChat/coding_agent 2026-07-30T17:15:00Z
"""

from __future__ import annotations

import json

import pytest

from codex_slack_bridge.agents import SHARED_AGENT_BEHAVIOR
from codex_slack_bridge.config import load_config
from codex_slack_bridge.worker_reliability import (
    VerifiedRouteReceipt,
    VerifiedRouteStore,
    execute_bounded_attempts,
    extract_verified_route_receipt,
)


PRODUCTION_LANES = {
    "direct_codex",
    "coding_agent",
    "tickets_agent",
    "billing_agent",
    "claude_agent",
}


def test_every_production_lane_uses_bounded_workers_and_shared_recovery_policy():
    config = load_config("config/agents.yaml")

    assert int(config.defaults["max_workers"]) == 3
    assert int(config.defaults["agent_worker_max_attempts"]) == 3
    # Command Center work survives up to four readback-first restart
    # continuations. This stays within the worker's hard ceiling of five and
    # does not widen the ordinary Slack worker retry budget.
    assert int(config.defaults["command_center_agent_max_attempts"]) == 5
    assert PRODUCTION_LANES <= set(config.agents)
    assert "bounded retries" in SHARED_AGENT_BEHAVIOR
    assert "same-surface readback" in SHARED_AGENT_BEHAVIOR
    assert "keep the originating obligation open" in SHARED_AGENT_BEHAVIOR


def test_retryable_transport_failure_continues_with_readback_guidance():
    calls: list[tuple[int, str]] = []
    sleeps: list[float] = []

    def attempt(number: int, guidance: str) -> str:
        calls.append((number, guidance))
        if number == 1:
            raise TimeoutError("tool transport timed out")
        return "COMPLETED\nSame-surface readback verified the requested state."

    result = execute_bounded_attempts(
        attempt,
        max_attempts=3,
        retry_delays=(0.25, 0.5),
        idempotency_key="stable-key",
        on_progress=lambda *_args: None,
        sleep=sleeps.append,
    )

    assert result.result.startswith("COMPLETED")
    assert result.attempts == 2
    assert result.retries == 1
    assert sleeps == [0.25]
    assert calls[0][1] == ""
    assert "same connector/tool surface" in calls[1][1]
    assert "stable-key" in calls[1][1]
    assert "Never replay blindly" in calls[1][1]


def test_uncertain_write_readback_prevents_duplicate_write():
    target = {"applied": False}
    writes = 0
    guidance_seen = ""

    def attempt(number: int, guidance: str) -> str:
        nonlocal writes, guidance_seen
        guidance_seen = guidance
        if not target["applied"]:
            writes += 1
            target["applied"] = True
            return "FAILED\nThe write result is uncertain; readback is required before retry."
        assert number == 2
        assert "read the exact target through the same connector/tool surface" in guidance
        return "COMPLETED\nReadback proves the intended state is already present."

    result = execute_bounded_attempts(
        attempt,
        max_attempts=3,
        retry_delays=(0, 0),
        idempotency_key="one-write-key",
        sleep=lambda _delay: None,
    )

    assert result.result.startswith("COMPLETED")
    assert result.retries == 1
    assert writes == 1
    assert "do not write again" in guidance_seen


def test_retry_budget_is_bounded():
    attempts: list[int] = []

    def attempt(number: int, _guidance: str) -> str:
        attempts.append(number)
        raise ConnectionError("transport connection reset")

    with pytest.raises(ConnectionError):
        execute_bounded_attempts(
            attempt,
            max_attempts=3,
            retry_delays=(0, 0),
            idempotency_key="bounded-key",
            sleep=lambda _delay: None,
        )

    assert attempts == [1, 2, 3]


def test_verified_route_receipt_is_stripped_and_persisted_without_customer_text(tmp_path):
    pipelines = tmp_path / "pipelines.json"
    tools = tmp_path / "tools.json"
    pipelines.write_text(
        json.dumps(
            {
                "pipelines": {
                    "sql_repair": {
                        "display_name": "Nova SQL repair",
                        "aliases": ["SQL repair"],
                        "use_when": "repair Nova SQL data",
                        "primary_agents": ["coding_agent"],
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    tools.write_text(
        json.dumps(
            {
                "tools": {
                    "nova_sql": {
                        "display_name": "Nova SQL",
                        "aliases": ["SQL"],
                        "use_when": "Nova SQL repair",
                        "primary_agents": ["coding_agent"],
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    result, receipt = extract_verified_route_receipt(
        "COMPLETED\nDone.\n"
        'VERIFIED_ROUTE_RECEIPT: {"pipelineKeys":["sql_repair"],'
        '"toolKeys":["nova_sql"],'
        '"verification":"Same-surface readback verified Secret Customer"}'
    )

    assert result == "COMPLETED\nDone."
    assert receipt is not None
    store_path = tmp_path / "routes.sqlite3"
    first = VerifiedRouteStore(
        store_path,
        pipeline_registry_path=pipelines,
        tool_registry_path=tools,
    )
    recorded = first.record_success(
        query="Run the Nova SQL repair for Secret Customer",
        agent_name="coding_agent",
        receipt=receipt,
        source_job_id="job-1",
    )
    second = VerifiedRouteStore(
        store_path,
        pipeline_registry_path=pipelines,
        tool_registry_path=tools,
    )
    matched = second.match(
        query="Please repeat the Nova SQL repair",
        agent_name="coding_agent",
    )

    assert matched is not None
    assert matched.route_id == recorded.route_id
    assert matched.pipeline_keys == ("sql_repair",)
    assert matched.tool_keys == ("nova_sql",)
    assert matched.verification == "same-surface readback verified"
    assert b"Secret Customer" not in store_path.read_bytes()
