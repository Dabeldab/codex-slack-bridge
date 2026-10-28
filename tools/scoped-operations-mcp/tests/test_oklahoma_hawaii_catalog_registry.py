from __future__ import annotations

# AgentChat/coding_agent 2026-08-03T19:41:00Z

import json
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[3]


def test_oklahoma_hawaii_catalog_replacement_is_fixed_to_taylor() -> None:
    pipelines = json.loads(
        (ROOT / "config" / "pipeline-registry.json").read_text(encoding="utf-8")
    )["pipelines"]
    fixed = pipelines["nova_sql_oklahoma_hawaii_catalog_replace"]
    text = " ".join(
        fixed["preferred_entrypoints"]
        + fixed["avoid_by_default"]
        + fixed["steps"]
        + fixed["verification"]
        + fixed["aliases"]
    )
    assert fixed["primary_agents"] == ["coding_agent"]
    assert fixed["requires_tools"] == ["salesforce_coding_ops"]
    for value in (
        "nova_sql_oklahoma_hawaii_catalog_replace_preview",
        "nova_sql_oklahoma_hawaii_catalog_replace_status",
        "nova_sql_oklahoma_hawaii_catalog_replace_execute",
        "unique_lifestyle_llc",
        "oklahoma",
        "HAWAII",
        "rory-8702-oklahoma-hawaii-full-replace-v1",
    ):
        assert value in text

    fast_path = json.loads(
        (ROOT / "config" / "tool-fast-paths.json").read_text(encoding="utf-8")
    )["tools"]["nova_sql"]
    fast_text = " ".join(
        fast_path["safe_actions"]
        + fast_path["requires_authorization_for"]
        + fast_path["never_allowed"]
        + fast_path["fast_start"]
    )
    assert "nova_sql_oklahoma_hawaii_catalog_replace_execute" in fast_text
    assert "generic or caller-selected DELETE" in fast_text

    capabilities = yaml.safe_load(
        (ROOT / "config" / "agent-capabilities.yaml").read_text(encoding="utf-8")
    )
    coding = capabilities["lanes"]["coding_agent"]
    coding_ops = set(coding["operations"])
    support_ops = set(capabilities["lanes"]["tickets_agent"]["operations"])
    billing_ops = set(capabilities["lanes"]["billing_agent"]["operations"])
    for suffix in ("preview", "status", "execute"):
        operation = f"nova_sql.oklahoma_hawaii_catalog_replace.{suffix}"
        assert operation in coding_ops
        assert operation not in support_ops
        assert operation not in billing_ops
    assert "no_delete_sql" in coding["limitations"]
    assert (
        "fixed_oklahoma_hawaii_catalog_replace_is_only_delete_exception"
        in coding["limitations"]
    )
