from __future__ import annotations

# AgentChat/coding_agent 2026-08-06T12:12:00Z

import json
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[3]


def test_instyle_demo_sync_is_registered_as_fixed_taylor_workflow() -> None:
    pipelines = json.loads(
        (ROOT / "config" / "pipeline-registry.json").read_text(encoding="utf-8")
    )["pipelines"]
    rebuild = pipelines["nova_sql_instyle_demo_sync"]
    text = " ".join(
        rebuild["preferred_entrypoints"]
        + rebuild["avoid_by_default"]
        + rebuild["steps"]
        + rebuild["verification"]
        + rebuild["aliases"]
    )

    assert rebuild["primary_agents"] == ["coding_agent"]
    assert rebuild["requires_tools"] == ["salesforce_coding_ops"]
    for value in (
        "nova_sql_instyle_demo_sync_preview",
        "nova_sql_instyle_demo_sync_status",
        "nova_sql_instyle_demo_sync_execute",
        "instyleDemoSyncConfigured=true",
        "LE_BOUTIQUE_INSTYLE",
        "Instyle_Fragrance",
        "DEMO_NOVA_CAFE",
        "preview_hash",
    ):
        assert value in text

    fast_path = json.loads(
        (ROOT / "config" / "tool-fast-paths.json").read_text(encoding="utf-8")
    )["tools"]["nova_sql"]
    fast_text = " ".join(
        fast_path["safe_actions"]
        + fast_path["requires_authorization_for"]
        + fast_path["fast_start"]
        + fast_path["paths"]
    )
    assert "nova_sql_instyle_demo_sync_execute" in fast_text
    assert "tools/scoped-operations-mcp/docs/instyle-demo-sync.md" in fast_text

    capabilities = yaml.safe_load(
        (ROOT / "config" / "agent-capabilities.yaml").read_text(encoding="utf-8")
    )
    coding_ops = set(capabilities["lanes"]["coding_agent"]["operations"])
    support_ops = set(capabilities["lanes"]["tickets_agent"]["operations"])
    billing_ops = set(capabilities["lanes"]["billing_agent"]["operations"])
    assert "nova_sql.instyle_demo_sync.preview" in coding_ops
    assert "nova_sql.instyle_demo_sync.status" in coding_ops
    assert "nova_sql.instyle_demo_sync.execute" in coding_ops
    assert "nova_sql.instyle_demo_sync.status" not in support_ops
    assert "nova_sql.instyle_demo_sync.status" not in billing_ops
    assert "nova_sql.instyle_demo_sync.execute" not in support_ops
    assert "nova_sql.instyle_demo_sync.execute" not in billing_ops
    assert "nova_sql.data_move.bounded_cross_account_read" in coding_ops
    assert "nova_sql.data_move.guarded_set_based_write" in coding_ops
    assert "nova_sql.data_move.bounded_cross_account_read" not in support_ops
    assert "nova_sql.data_move.bounded_cross_account_read" not in billing_ops
    assert "nova_sql.data_move.guarded_set_based_write" not in support_ops
    assert "nova_sql.data_move.guarded_set_based_write" not in billing_ops

    profile = (ROOT / "profiles" / "coding_agent.md").read_text(encoding="utf-8")
    assert "`nova_sql_instyle_demo_sync` pipeline immediately" in profile
    assert "`nova_sql_data_move_read`" in profile
    assert "Never substitute the generic" in profile


def test_instyle_runway_merge_is_registered_only_for_taylor() -> None:
    pipelines = json.loads(
        (ROOT / "config" / "pipeline-registry.json").read_text(encoding="utf-8")
    )["pipelines"]
    merge = pipelines["nova_sql_instyle_runway_merge"]
    text = " ".join(
        merge["preferred_entrypoints"]
        + merge["avoid_by_default"]
        + merge["steps"]
        + merge["verification"]
        + merge["aliases"]
    )
    for value in (
        "nova_sql_instyle_runway_merge_preview",
        "nova_sql_instyle_runway_merge_status",
        "nova_sql_instyle_runway_merge_execute",
        "instyleRunwayMergeConfigured=true",
        "INSTYLE_RUNWAY",
        "107 inactive placeholders",
        "142 valid historical invoice lines",
        "11 invoice-less rows",
    ):
        assert value in text

    capabilities = yaml.safe_load(
        (ROOT / "config" / "agent-capabilities.yaml").read_text(encoding="utf-8")
    )
    coding_ops = set(capabilities["lanes"]["coding_agent"]["operations"])
    support_ops = set(capabilities["lanes"]["tickets_agent"]["operations"])
    billing_ops = set(capabilities["lanes"]["billing_agent"]["operations"])
    for operation in (
        "nova_sql.instyle_runway_merge.preview",
        "nova_sql.instyle_runway_merge.status",
        "nova_sql.instyle_runway_merge.execute",
    ):
        assert operation in coding_ops
        assert operation not in support_ops
        assert operation not in billing_ops
