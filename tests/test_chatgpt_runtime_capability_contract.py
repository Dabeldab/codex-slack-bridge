from __future__ import annotations

from pathlib import Path

from codex_slack_bridge.agent_policy import load_capability_contract, validate_runtime_agent_policy
from codex_slack_bridge.config import load_config

REPO_ROOT = Path(__file__).resolve().parents[1]
RELAY_LANES = ("coding_agent", "tickets_agent", "billing_agent")


def test_dual_reasoning_providers_are_allowed_by_capability_contract():
    contract = load_capability_contract(str(REPO_ROOT / "config" / "agent-capabilities.yaml"))
    for lane in RELAY_LANES:
        assert "chatgpt_work_relay" in contract["lanes"][lane]["allowed_providers"]
        assert "codex_cli" in contract["lanes"][lane]["allowed_providers"]
    # raw_codex is the break-glass lane and is never routed to the relay.
    assert contract["lanes"]["raw_codex"].get("allowed_providers") is None


def test_cloud_runtime_defaults_to_codex_and_passes_capability_validation():
    config = load_config(REPO_ROOT / "config" / "agents.chatgpt-runtime.yaml")
    for lane_name in RELAY_LANES:
        agent = dict(config.defaults)
        agent.update(config.agents[lane_name])
        agent.setdefault("agent_capability_contract_path", str(REPO_ROOT / "config" / "agent-capabilities.yaml"))
        assert agent.get("provider") == "codex_cli"
        # Raises PermissionError on drift; a clean return is the assertion.
        validate_runtime_agent_policy(lane_name, agent)


def test_cloud_run_uses_on_demand_provider_readiness_for_cpu_throttling():
    config = load_config(REPO_ROOT / "config" / "agents.cloud-run-chatgpt.yaml")

    assert config.defaults["command_center_provider_readiness_enabled"] is True
    assert config.defaults["command_center_provider_readiness_periodic_enabled"] is False
    assert config.defaults["command_center_provider_readiness_probe_timeout_seconds"] == 20
