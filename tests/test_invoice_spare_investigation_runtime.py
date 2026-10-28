from __future__ import annotations

import json
from pathlib import Path

import yaml

from codex_slack_bridge.agents import SHARED_AGENT_BEHAVIOR, STATIC_PROMPT_SCHEMA_VERSION


ROOT = Path(__file__).resolve().parents[1]
OPERATION = "nova_sql.invoice_spare.deep_read"
TOOL = "nova_sql_invoice_spare_investigation"


def test_business_lanes_receive_deep_spare_investigation_capability() -> None:
    capabilities = yaml.safe_load(
        (ROOT / "config/agent-capabilities.yaml").read_text(encoding="utf-8")
    )

    for lane in ("coding_agent", "tickets_agent", "billing_agent"):
        assert OPERATION in capabilities["lanes"][lane]["operations"]
    assert OPERATION not in capabilities["lanes"]["claude_agent"]["operations"]


def test_spare_investigation_is_routed_to_the_typed_read_first() -> None:
    fast_paths = json.loads(
        (ROOT / "config/tool-fast-paths.json").read_text(encoding="utf-8")
    )
    pipelines = json.loads(
        (ROOT / "config/pipeline-registry.json").read_text(encoding="utf-8")
    )
    nova_sql = fast_paths["tools"]["nova_sql"]
    pipeline = pipelines["pipelines"]["nova_sql_invoice_spare_investigation"]

    assert {"spare", "spare invoice", "minimum price approval"}.issubset(
        nova_sql["aliases"]
    )
    assert TOOL in nova_sql["fast_start"][0]
    assert pipeline["requires_tools"] == [TOOL]
    assert set(pipeline["primary_agents"]) == {
        "coding_agent",
        "tickets_agent",
        "billing_agent",
    }
    assert any("discount times quantity" in step for step in pipeline["steps"])
    assert any("stored facts" in item for item in pipeline["verification"])


def test_agent_reasoning_and_runtime_preflight_enforce_the_deep_contract() -> None:
    preflight = (ROOT / "deploy/gcp/agent-runtime/preflight.py").read_text(
        encoding="utf-8"
    )
    runbook = (ROOT / "docs/agent-tools/nova-invoice-spare.md").read_text(
        encoding="utf-8"
    )
    platform_map = (ROOT / "docs/AGENT_PLATFORM_MAP.md").read_text(encoding="utf-8")

    assert STATIC_PROMPT_SCHEMA_VERSION >= 14
    assert TOOL in SHARED_AGENT_BEHAVIOR
    assert "ProductDiscount * Quantity" in SHARED_AGENT_BEHAVIOR
    assert "stored facts" in SHARED_AGENT_BEHAVIOR
    assert "but not the minimum price used when the invoice was" in runbook
    assert "sale own spare + full available source-invoice spare >= 0" in runbook
    assert TOOL in platform_map
    assert f'"{TOOL}"' in preflight
