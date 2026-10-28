# AgentChat/direct_codex 2026-07-29T20:35:00-04:00
from __future__ import annotations

import json

from codex_slack_bridge.execution_navigator import ExecutionNavigator


def _registries(tmp_path):
    pipeline_path = tmp_path / "pipelines.json"
    tool_path = tmp_path / "tools.json"
    pipeline_path.write_text(
        json.dumps(
            {
                "pipelines": {
                    "route_and_scope": {
                        "display_name": "Route And Scope",
                        "aliases": ["route"],
                    },
                    "billing_subscription_repair": {
                        "display_name": "Billing Subscription Repair",
                        "aliases": ["partial location collection", "subscription repair"],
                        "use_when": "Correct Maxio component allocations.",
                        "primary_agents": ["billing_agent"],
                        "requires_tools": ["salesforce", "chargify"],
                    },
                }
            }
        ),
        encoding="utf-8",
    )
    tool_path.write_text(
        json.dumps(
            {
                "tools": {
                    "salesforce": {
                        "display_name": "Salesforce",
                        "aliases": ["ticket"],
                        "primary_agents": ["billing_agent"],
                    },
                    "chargify": {
                        "display_name": "Chargify / Maxio",
                        "aliases": ["maxio", "subscription"],
                        "primary_agents": ["billing_agent"],
                    },
                    "gmail": {
                        "display_name": "Gmail",
                        "aliases": ["email"],
                        "primary_agents": ["coding_agent"],
                    },
                }
            }
        ),
        encoding="utf-8",
    )
    return pipeline_path, tool_path


def test_navigator_puts_pipeline_dependencies_at_hand(tmp_path):
    pipeline_path, tool_path = _registries(tmp_path)
    plan = ExecutionNavigator(pipeline_path, tool_path).plan(
        "perform the partial location collection",
        agent_name="billing_agent",
    )
    assert plan.confidence == "high"
    assert [item.key for item in plan.pipelines] == ["billing_subscription_repair"]
    assert {item.key for item in plan.tools} == {"salesforce", "chargify"}
    assert plan.demand == "high_risk"
    assert plan.recommended_model_class == "quality"


def test_navigator_does_not_present_excluded_tool_or_pipeline(tmp_path):
    pipeline_path, tool_path = _registries(tmp_path)
    plan = ExecutionNavigator(pipeline_path, tool_path).plan(
        "perform the partial location collection",
        agent_name="billing_agent",
        excluded_tools={"chargify"},
    )
    assert not plan.pipelines
    assert all(item.key != "chargify" for item in plan.tools)


def test_unknown_request_keeps_discovery_as_bounded_fallback(tmp_path):
    pipeline_path, tool_path = _registries(tmp_path)
    plan = ExecutionNavigator(pipeline_path, tool_path).plan(
        "explain the unfamiliar cobalt condition",
        agent_name="coding_agent",
    )
    assert plan.confidence == "low"
    assert plan.discovery_fallback is True
    assert plan.recommended_model_class == "quality"


def test_simple_question_does_not_trigger_discovery(tmp_path):
    pipeline_path, tool_path = _registries(tmp_path)
    plan = ExecutionNavigator(pipeline_path, tool_path).plan(
        "what is Alex doing right now?",
        agent_name="coding_agent",
    )
    assert plan.demand == "simple"
    assert plan.discovery_fallback is False
    assert plan.recommended_model_class == "fast"
