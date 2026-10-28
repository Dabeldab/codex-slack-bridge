from __future__ import annotations

import json
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[3]


def test_table_restore_is_registered_documented_and_taylor_only() -> None:
    pipelines = json.loads(
        (ROOT / "config" / "pipeline-registry.json").read_text(encoding="utf-8")
    )["pipelines"]
    recovery = pipelines["nova_sql_table_restore"]
    recovery_text = " ".join(
        recovery["preferred_entrypoints"]
        + recovery["avoid_by_default"]
        + recovery["steps"]
        + recovery["verification"]
        + recovery["aliases"]
    )

    assert recovery["primary_agents"] == ["coding_agent"]
    assert recovery["requires_tools"] == ["salesforce_coding_ops"]
    for value in (
        "nova_sql_table_restore_preview",
        "nova_sql_table_restore_execute",
        "POS_<company>_RESTORE",
        "preview_hash",
        "unique",
        "backup",
        "isolated",
    ):
        assert value in recovery_text
    assert "raw SQL" in recovery_text

    fast_path = json.loads(
        (ROOT / "config" / "tool-fast-paths.json").read_text(encoding="utf-8")
    )["tools"]["nova_sql"]
    fast_text = " ".join(
        fast_path["safe_actions"]
        + fast_path["requires_authorization_for"]
        + fast_path["fast_start"]
        + fast_path["paths"]
    )
    assert "nova_sql_table_restore_preview" in fast_text
    assert "nova_sql_table_restore_execute" in fast_text

    capabilities = yaml.safe_load(
        (ROOT / "config" / "agent-capabilities.yaml").read_text(encoding="utf-8")
    )
    coding_ops = set(capabilities["lanes"]["coding_agent"]["operations"])
    support_ops = set(capabilities["lanes"]["tickets_agent"]["operations"])
    billing_ops = set(capabilities["lanes"]["billing_agent"]["operations"])
    assert "nova_sql.table_restore.preview" in coding_ops
    assert "nova_sql.table_restore.execute" in coding_ops
    assert "nova_sql.table_restore.execute" not in support_ops
    assert "nova_sql.table_restore.execute" not in billing_ops

    profile = (ROOT / "profiles" / "coding_agent.md").read_text(encoding="utf-8")
    documentation = (ROOT / "docs" / "agent-tools" / "nova-sql.md").read_text(
        encoding="utf-8"
    )
    assert "`nova_sql_table_restore_preview`" in profile
    assert "`nova_sql_table_restore_execute`" in profile
    assert "updatesExistingRowsOnly" not in documentation
    assert "never SQL or a source database name" in documentation
