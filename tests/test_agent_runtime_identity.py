# AgentChat/direct_codex 2026-07-29T20:35:00-04:00
from codex_slack_bridge.agent_runtime import runtime_identity


def test_model_variant_keeps_separate_shared_warm_sessions():
    agent = {
        "agent_runtime_shared_sessions": True,
        "agent_runtime_session_scope": "agent",
    }
    fast = runtime_identity(
        agent_name="coding_agent",
        agent=agent,
        surface="command_center",
        conversation_id="job-1",
        variant="gpt-5.6-terra",
    )
    quality = runtime_identity(
        agent_name="coding_agent",
        agent=agent,
        surface="command_center",
        conversation_id="job-2",
        variant="gpt-5.6-sol",
    )
    assert fast.surface == "shared"
    assert fast.conversation_id == "agent:coding_agent:variant:gpt-5.6-terra"
    assert quality.conversation_id == "agent:coding_agent:variant:gpt-5.6-sol"


def test_legacy_session_identity_is_unchanged_without_variant():
    identity = runtime_identity(
        agent_name="coding_agent",
        agent={"agent_runtime_shared_sessions": True},
        surface="slack",
        conversation_id="C1:T1",
    )
    assert identity.conversation_id == "agent:coding_agent"
