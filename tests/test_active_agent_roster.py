from __future__ import annotations

from pathlib import Path
import re
from types import SimpleNamespace

import pytest
import yaml

from codex_slack_bridge.config import load_config, require_active_agent

ROOT = Path(__file__).resolve().parents[1]
ACTIVE = {"coding_agent", "billing_agent", "tickets_agent"}
RETIRED = ("direct_codex", "claude_agent", "raw_codex")


@pytest.mark.parametrize("filename", ["agents.chatgpt-runtime.yaml", "agents.cloud-run-chatgpt.yaml"])
def test_production_roster_and_channels_contain_only_three_agents(filename):
    config = load_config(ROOT / "config" / filename)
    assert set(config.agents) == ACTIVE
    assert {route.agent_name for route in config.channels.values()} == ACTIVE
    assert config.defaults["ops_weekly_support_quality_enabled"] is False
    # Production agents run autonomous local Codex CLI as the primary lane
    # (the ChatGPT Work/GitHub relay remains the ad-hoc/fallback).
    assert all(config.agents[name]["provider"] == "codex_cli" for name in ACTIVE)


def test_three_agents_do_not_inherit_rory_permissions():
    before = load_config(ROOT / "config" / "agents.gcp-runtime.yaml")
    after = load_config(ROOT / "config" / "agents.cloud-run-chatgpt.yaml")
    for name in ACTIVE:
        assert after.agents[name]["mcp_allowlist"] == before.agents[name]["mcp_allowlist"]
        assert "rory_operator_ops" not in after.agents[name]["mcp_allowlist"]
        assert "salesforce_operator_ops" not in after.agents[name]["mcp_allowlist"]


@pytest.mark.parametrize("name", RETIRED)
def test_inactive_policy_fails_before_provider_or_contract_loading(name, monkeypatch):
    from codex_slack_bridge import agent_policy

    def forbidden(*args, **kwargs):
        raise AssertionError("Retired agent must not load a capability contract")

    monkeypatch.setattr(agent_policy, "load_capability_contract", forbidden)
    with pytest.raises(PermissionError, match="disabled"):
        agent_policy.validate_runtime_agent_policy(name, {
            "active_agents": sorted(ACTIVE),
            "provider": "chatgpt_work_relay",
            "agent_capability_contract_path": "/must/not/read",
        })


def test_disabled_provider_is_rejected_even_without_an_explicit_roster():
    with pytest.raises(PermissionError, match="disabled"):
        require_active_agent("claude_agent", {"provider": "disabled"})


@pytest.mark.parametrize("name", RETIRED)
def test_direct_submission_cannot_allocate_a_job_for_retired_agent(name):
    from codex_slack_bridge.command_center_server import CommandCenterRuntime

    runtime = CommandCenterRuntime.__new__(CommandCenterRuntime)
    runtime.config = SimpleNamespace(agents={item: {} for item in ACTIVE})
    # No queue, worker pool, or persistence is initialized. Rejection must be first.
    with pytest.raises(ValueError, match="disabled or not configured"):
        runtime.submit_prompt(
            agent_name=name,
            prompt="Read-only status check",
            payload={},
            source_type="agent-direct-chat",
        )


@pytest.mark.parametrize("name", RETIRED)
def test_old_mailbox_request_cannot_revive_retired_lane(name, monkeypatch):
    monkeypatch.setenv("NOVA_CONTROL_MCP_AUTH_MODE", "cloudrun_iam")
    from codex_slack_bridge import nova_control_mcp as control
    from codex_slack_bridge.reasoning_relay_protocol import RelayRequest

    config = load_config(ROOT / "config" / "agents.cloud-run-chatgpt.yaml")
    request = RelayRequest.create(
        lane=name, kind="reasoning_request", conversation_id="retirement-test",
        job_id=1, payload={}, message_id=f"{name}:retirementtest001",
    )
    monkeypatch.setattr(control, "_bridge_config", lambda: config)
    monkeypatch.setattr(control, "_relay_transport", lambda: SimpleNamespace(_get_json=lambda path: request.to_dict()))

    def forbidden(*args, **kwargs):
        raise AssertionError("Retired lane must be rejected before claim/tool handling")

    monkeypatch.setattr(control, "verify_relay_authorization_claim", forbidden)
    with pytest.raises(PermissionError, match="lane is not configured"):
        control.nova_relay_get_request(request.message_id)


def test_scheduler_builds_only_effective_active_lanes():
    from codex_slack_bridge.lane_scheduler import build_lane_configs_from_agents_yaml

    lanes = build_lane_configs_from_agents_yaml(str(ROOT / "config" / "agents.cloud-run-chatgpt.yaml"))
    assert {lane.lane_key for lane in lanes} == {"coding", "billing", "tickets"}
    assert len(lanes) == 3


def test_inheritance_cannot_reintroduce_retired_channels_or_quality_watcher(tmp_path):
    agents = {name: {"provider": "chatgpt_work_relay"} for name in ACTIVE | set(RETIRED)}
    base = {
        "defaults": {"ops_weekly_support_quality_enabled": True},
        "agents": agents,
        "channels": {f"channel-{name}": {"agent": name} for name in agents},
    }
    (tmp_path / "base.yaml").write_text(yaml.safe_dump(base), encoding="utf-8")
    (tmp_path / "overlay.yaml").write_text(yaml.safe_dump({
        "extends": "base.yaml", "defaults": {"active_agents": sorted(ACTIVE)},
    }), encoding="utf-8")
    config = load_config(tmp_path / "overlay.yaml")
    assert set(config.agents) == ACTIVE
    assert len(config.channels) == 3
    assert config.defaults["ops_weekly_support_quality_enabled"] is False


@pytest.mark.parametrize("roster", [[], "tickets_agent", ["missing"], ["tickets_agent", "tickets_agent"], [True], [" tickets_agent"]])
def test_invalid_roster_fails_closed(tmp_path, roster):
    path = tmp_path / "agents.yaml"
    path.write_text(yaml.safe_dump({
        "defaults": {"active_agents": roster},
        "agents": {"tickets_agent": {"provider": "chatgpt_work_relay"}},
    }), encoding="utf-8")
    with pytest.raises(ValueError, match="active_agents"):
        load_config(path)


def test_dashboard_active_roster_and_assignments_have_only_three_agents():
    source = (ROOT / "kanban-command-center/app.js").read_text(encoding="utf-8")
    roster = re.search(r"const agentRoster = \[(.*?)\n\];", source, re.DOTALL)
    assert roster is not None
    assert set(re.findall(r'agentName: "([^"]+)"', roster.group(1))) == ACTIVE
    assignments = re.search(r"const dispatchAgentMap = \{(.*?)\n\};", source, re.DOTALL)
    assert assignments is not None
    assert set(re.findall(r': "([^"]+)"', assignments.group(1))) == ACTIVE
    html = (ROOT / "kanban-command-center/index.html").read_text(encoding="utf-8")
    assert not re.search(r'data-(?:agent|dispatch-agent)="(?:claude|thor|rory|direct_codex|claude_agent)"', html)
    fallback = (ROOT / "kanban-command-center/ticket-data.js").read_text(encoding="utf-8")
    assert 'agent: "claude"' not in fallback


def test_image_does_not_provision_retired_workspaces():
    dockerfile = (ROOT / "deploy/gcp/Dockerfile.cloud-run-chatgpt").read_text(encoding="utf-8")
    for name in ("rory", "claude"):
        assert f"/tmp/nova-cloud-run/workspaces/{name}" not in dockerfile
    for name in ("taylor", "jamie", "alex"):
        assert f"/tmp/nova-cloud-run/workspaces/{name}" in dockerfile
