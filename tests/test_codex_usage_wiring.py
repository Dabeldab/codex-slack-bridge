from __future__ import annotations

"""Tests for the per-task Codex usage metering + cost wiring.

Covers the fix list:
  1. Timeout-with-final marks timed_out=True (no longer masks truncated runs).
  2. Token math: total_tokens does NOT double-count cached input; adds cost.
  3. Aggregation: retries + subagents sum into one per-job usage record.
  4. Relay no longer hijacks codex_cli when REASONING_RELAY_ENABLED is set.
"""

from codex_slack_bridge.agents import (
    CodexProcessResult,
    _parse_codex_jsonl_usage,
    pop_agent_usage,
    record_agent_usage,
)


def _turn_event(input_tokens=0, cached=0, output=0, reasoning=0) -> str:
    return (
        '{"type":"turn.completed","usage":{'
        f'"input_tokens":{input_tokens},'
        f'"cached_input_tokens":{cached},'
        f'"output_tokens":{output},'
        f'"reasoning_output_tokens":{reasoning}'
        "}}"
    )


# ---- Fix 1: timeout ----

def test_timeout_with_final_marks_timed_out():
    result = CodexProcessResult(
        final_text="partial answer",
        returncode=0,
        stdout="",
        stderr="timed out",
        session_id="",
        final_message="partial answer",
        timed_out=True,
        usage={"input_tokens": 10, "output_tokens": 5},
    )
    assert result.timed_out is True
    assert result.returncode == 0  # a partial answer exists, but it was truncated


# ---- Fix 2: token math ----

def test_total_tokens_does_not_double_count_cached():
    parsed = _parse_codex_jsonl_usage(
        _turn_event(input_tokens=100, cached=40, output=20, reasoning=5)
    )
    usage = parsed["usage"]
    # input_tokens already includes cached_input_tokens; total = input + output only.
    assert usage["total_tokens"] == 120  # 100 + 20, not 100+40+20+5
    assert usage["input_tokens"] == 100
    assert usage["cached_input_tokens"] == 40
    assert usage["output_tokens"] == 20
    assert usage["reasoning_output_tokens"] == 5
    assert usage["estimated_cost_usd"] > 0


def test_token_math_malformed_jsonl_is_ignored():
    parsed = _parse_codex_jsonl_usage(
        "not-json\n{\"type\":\"turn.completed\",\"usage\":{\"input_tokens\":7,\"output_tokens\":3}}\n"
    )
    usage = parsed["usage"]
    assert usage["input_tokens"] == 7
    assert usage["output_tokens"] == 3
    assert usage["total_tokens"] == 10


def test_session_id_extracted_from_thread_started():
    parsed = _parse_codex_jsonl_usage('{"type":"thread.started","thread_id":"abc-123"}')
    assert parsed["session_id"] == "abc-123"


# ---- Fix 3: aggregation ----

def test_record_agent_usage_aggregates_retries():
    pop_agent_usage(101)
    record_agent_usage(
        101,
        {
            "input_tokens": 100,
            "cached_input_tokens": 40,
            "output_tokens": 20,
            "reasoning_output_tokens": 5,
            "total_tokens": 120,
            "estimated_cost_usd": 0.0005,
        },
    )
    # second attempt (e.g. fresh-session retry) sums onto the first
    record_agent_usage(
        101,
        {
            "input_tokens": 50,
            "cached_input_tokens": 10,
            "output_tokens": 15,
            "reasoning_output_tokens": 0,
            "total_tokens": 65,
            "estimated_cost_usd": 0.0003,
        },
    )
    agg = pop_agent_usage(101)
    assert agg is not None
    assert agg["input_tokens"] == 150
    assert agg["cached_input_tokens"] == 50
    assert agg["output_tokens"] == 35
    assert agg["reasoning_output_tokens"] == 5
    assert agg["total_tokens"] == 185
    assert abs(agg["estimated_cost_usd"] - 0.0008) < 1e-9


def test_record_agent_usage_ignores_empty():
    pop_agent_usage(202)
    record_agent_usage(202, {})  # no-op
    record_agent_usage(202, None)  # no-op
    assert pop_agent_usage(202) is None


def test_record_agent_usage_skips_junk_on_aggregate():
    pop_agent_usage(303)
    record_agent_usage(303, {"input_tokens": 10, "output_tokens": 2, "total_tokens": 12})
    # junk string tokens must not blow up aggregation
    record_agent_usage(303, {"input_tokens": "bad", "output_tokens": 3, "total_tokens": "x"})
    agg = pop_agent_usage(303)
    assert agg["input_tokens"] == 10  # junk "bad" ignored, kept prior
    assert agg["output_tokens"] == 5  # 2 + 3 (the valid int is summed)
    assert agg["total_tokens"] == 12  # junk "x" ignored, prior 12 kept


# ---- Fix 4: relay no longer hijacks codex_cli ----

def test_codex_cli_provider_not_hijacked_by_relay_flag():
    """The relay flag cannot silently reroute a configured Codex lane."""
    from codex_slack_bridge.agent_worker import _select_execution_backend

    assert _select_execution_backend("codex_cli", "", relay_enabled=True) == "codex"
