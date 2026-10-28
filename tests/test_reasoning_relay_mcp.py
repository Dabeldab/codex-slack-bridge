import pytest

from codex_slack_bridge.reasoning_relay_mcp import MCPServerSpec, ReasoningRelayToolBroker


def test_server_allowlist_is_reduction_only():
    broker = ReasoningRelayToolBroker(lane="tickets_agent", allowed_servers=["salesforce_support_ops", "made_up"], child_env={}, server_specs={"salesforce_support_ops": MCPServerSpec("noop")})
    assert broker.server_names == ("salesforce_support_ops",)
    with pytest.raises(PermissionError):
        broker._spec("made_up")


def test_configured_mcp_command_overrides_fallback(tmp_path):
    config = tmp_path / "config.toml"
    config.write_text('[mcp_servers.salesforce_support_ops]\ncommand = "/usr/bin/sudo"\nargs = ["-u", "broker", "--", "runner"]\n', encoding="utf-8")
    broker = ReasoningRelayToolBroker(lane="tickets_agent", allowed_servers=["salesforce_support_ops"], child_env={}, config_path=str(config))
    spec = broker._spec("salesforce_support_ops")
    assert spec.command == "/usr/bin/sudo"
    assert spec.args[-1] == "runner"



def test_typed_mcp_rehydrates_only_its_service_credentials(monkeypatch):
    monkeypatch.setenv("SALESFORCE_CLIENT_ID", "client-id")
    monkeypatch.setenv("SALESFORCE_CLIENT_SECRET", "client-secret")
    monkeypatch.setenv("RESCUE_USER", "rescue-user")
    broker = ReasoningRelayToolBroker(
        lane="tickets_agent",
        allowed_servers=["salesforce_support_ops", "rescue_console"],
        child_env={"PATH": "/usr/bin"},
        server_specs={
            "salesforce_support_ops": MCPServerSpec("noop"),
            "rescue_console": MCPServerSpec("noop"),
        },
    )

    salesforce_env = broker._env_for_server("salesforce_support_ops")
    assert salesforce_env["SALESFORCE_CLIENT_ID"] == "client-id"
    assert salesforce_env["SALESFORCE_CLIENT_SECRET"] == "client-secret"
    assert "RESCUE_USER" not in salesforce_env

    rescue_env = broker._env_for_server("rescue_console")
    assert rescue_env["RESCUE_USER"] == "rescue-user"
    assert "SALESFORCE_CLIENT_SECRET" not in rescue_env
