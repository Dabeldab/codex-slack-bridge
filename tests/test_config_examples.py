from pathlib import Path

import pytest

from codex_slack_bridge.config import load_config


def test_committed_agent_configs_load_and_routes_reference_known_agents() -> None:
    root = Path(__file__).resolve().parents[1]

    for relative_path in ("config/agents.yaml", "config/agents.example.yaml"):
        config = load_config(root / relative_path)

        assert config.agents
        assert config.channels
        assert all(route.agent_name in config.agents for route in config.channels.values())
        assert config.defaults["agent_child_env_secret_mode"] == "scrub"
        # AgentChat/direct_codex 2026-07-15T03:27:38-04:00: trusted work uses scoped stores/brokers, not ambient secrets.
        assert config.defaults["agent_child_env_secret_mode"] == "scrub"
        assert config.defaults["agent_trusted_child_env_secret_mode"] == "scrub"
        assert config.defaults["agent_child_env_secret_allowlist"] == []
        assert config.defaults["credential_vault_path"]
        assert config.defaults["credential_vault_tool"]
        assert config.defaults["google_drive_adc_path"]
        assert config.defaults["automation_window_enabled"] is True
        assert config.defaults["automation_window_timezone"] == "America/New_York"
        assert config.defaults["automation_window_local_start"] == "08:00"
        assert config.defaults["automation_window_local_end"] == "19:00"


def test_gcp_runtime_overlay_inherits_roster_and_replaces_private_paths() -> None:
    root = Path(__file__).resolve().parents[1]
    config = load_config(root / "config" / "agents.gcp-runtime.yaml")

    assert config.defaults["runtime_mode"] == "primary"
    assert config.defaults["automation_window_enabled"] is True
    assert config.defaults["automation_window_local_start"] == "08:00"
    assert config.defaults["automation_window_local_end"] == "19:00"
    assert config.defaults["ops_singapore_ftp_local_hour"] == 8
    assert config.defaults["suppress_private_runtime_paths"] is True
    assert config.defaults["credential_vault_tool"] == ""
    assert set(config.channels) == set(load_config(root / "config" / "agents.yaml").channels)
    assert config.agents["direct_codex"]["workspace_root"] == "/srv/nova/workspaces/rory"
    assert config.agents["direct_codex"]["allowed_user_ids"] == ["U0ANMFH59U0"]
    assert "rory_operator_ops" in config.agents["direct_codex"]["mcp_allowlist"]
    assert "zoom_operator_ops" in config.agents["direct_codex"]["mcp_allowlist"]
    assert config.agents["raw_codex"]["workspace_root"] == "/srv/nova/workspaces/raw"
    assert config.agents["raw_codex"]["codex_command_prefix"][-2:] == ["nova-raw", "--"]
    assert config.agents["claude_agent"]["codex_command_prefix"][-2:] == ["nova-claude", "--"]
    assert config.agents["claude_agent"]["provider"] == "codex_cli"
    assert config.agents["claude_agent"]["sandbox"] == "read-only"
    assert config.agents["claude_agent"]["model"] == "gpt-5.6-terra"
    assert config.agents["claude_agent"]["effort"] == "medium"
    assert config.agents["claude_agent"]["mcp_allowlist"] == [
        "rescue_console",
        "zoom_quality_ops",
        "salesforce_ticket_reads",
        "google_drive_support_reads",
    ]
    assert config.agents["coding_agent"]["codex_command_prefix"][-2:] == ["nova-taylor", "--"]


def test_config_extends_rejects_cycles(tmp_path: Path) -> None:
    first = tmp_path / "first.yaml"
    second = tmp_path / "second.yaml"
    first.write_text("extends: second.yaml\n", encoding="utf-8")
    second.write_text("extends: first.yaml\n", encoding="utf-8")

    with pytest.raises(ValueError, match="extends cycle"):
        load_config(first)


def test_example_config_contains_the_complete_runtime_roster() -> None:
    root = Path(__file__).resolve().parents[1]
    config = load_config(root / "config/agents.example.yaml")

    assert set(config.agents) == {
        "direct_codex",
        "raw_codex",
        "coding_agent",
        "claude_agent",
        "tickets_agent",
        "billing_agent",
    }

    for name in ("direct_codex", "coding_agent", "claude_agent", "tickets_agent", "billing_agent"):
        prefix = config.agents[name]["prompt_prefix"]
        assert "member of Nova's Tech Support team" in prefix, name
        assert "assigned responsibilit" in " ".join(prefix.split()), name
    assert config.defaults["ops_weekly_support_quality_enabled"] is True
    assert config.defaults["ops_weekly_support_quality_weekday"] == "Wednesday"
    assert config.defaults["ops_weekly_support_quality_local_time"] == "09:00"
    assert config.defaults["ops_weekly_support_quality_timezone"] == "America/New_York"
