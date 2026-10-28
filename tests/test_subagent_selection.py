from pathlib import Path

from codex_slack_bridge.agents import (
    AgentRequest,
    _select_subagents,
    _select_task_skills,
    _resolve_agent_skill_path,
    should_run_subagents,
)
from codex_slack_bridge.config import load_config


SUBAGENTS = [
    {"name": "sql", "triggers": ["sql", "database"]},
    {"name": "salesforce", "triggers": ["salesforce"]},
    {"name": "reviewer", "triggers": []},
    {"name": "browser", "triggers": ["browser"]},
]


def request(text: str) -> AgentRequest:
    return AgentRequest(text=text, channel_id="test", user_id="user", thread_ts="thread")


def test_skill_resolution_falls_back_to_codex_skill_package(tmp_path, monkeypatch):
    codex_home = tmp_path / ".codex"
    packaged = codex_home / "skills" / "prospective-tasks" / "SKILL.md"
    packaged.parent.mkdir(parents=True)
    packaged.write_text("# Prospective Tasks", encoding="utf-8")
    monkeypatch.setenv("CODEX_HOME", str(codex_home))

    resolved = _resolve_agent_skill_path("prospective-tasks", tmp_path / "repo-skills")

    assert resolved == packaged


def test_manual_subagents_select_relevant_roles_instead_of_every_role():
    selected = _select_subagents(SUBAGENTS, 4, request("Use subagents to inspect the SQL database safely"))

    assert [item["name"] for item in selected] == ["sql"]


def test_explicit_all_subagents_preserves_exhaustive_mode():
    selected = _select_subagents(SUBAGENTS, 4, request("!subagents all inspect this issue"))

    assert [item["name"] for item in selected] == ["sql", "salesforce", "reviewer", "browser"]


def test_auto_subagents_cover_diagnostic_and_implementation_work():
    agent = {"subagents_mode": "auto"}

    assert should_run_subagents(agent, request("Diagnose the performance issue"))
    assert should_run_subagents(agent, request("Implement the verified fix"))


def test_subagents_escalate_for_disjoint_work_and_independent_verification():
    selected = _select_subagents(
        SUBAGENTS,
        4,
        request("Inspect the SQL database and Salesforce, then independently verify the live write"),
    )

    assert [item["name"] for item in selected] == ["sql", "salesforce", "reviewer"]


def test_generic_review_word_does_not_create_a_second_workstream():
    selected = _select_subagents(
        SUBAGENTS,
        4,
        request("Use subagents to review the billing workflow"),
    )

    assert [item["name"] for item in selected] == ["reviewer"]


def test_task_skills_include_core_and_at_most_three_matching_skills():
    agent = {
        "core_skills": ["security"],
        "default_skills": ["nova_knowledge", "internet_search"],
        "skills": ["gcp_github", "zoom_workplace", "email_watch"],
        "max_task_skills": 3,
        "skill_triggers": {
            "nova_knowledge": ["nova"],
            "internet_search": ["latest"],
            "gcp_github": ["github"],
            "zoom_workplace": ["zoom"],
            "email_watch": ["email"],
        },
    }

    selected = _select_task_skills(agent, "Find the latest Nova email issue in GitHub and Zoom")

    assert selected == ["security", "nova_knowledge", "internet_search", "gcp_github"]


def test_task_skills_do_not_load_unrelated_configured_skills():
    agent = {
        "core_skills": ["security"],
        "skills": ["zoom_workplace", "email_watch"],
        "skill_triggers": {"zoom_workplace": ["zoom"], "email_watch": ["email"]},
    }

    assert _select_task_skills(agent, "Refactor a local parser") == ["security"]


def test_every_configured_agent_loads_the_single_customer_email_workflow():
    root = Path(__file__).resolve().parents[1]
    config = load_config(root / "config" / "agents.yaml")

    for agent_name in ("direct_codex", "coding_agent", "tickets_agent", "billing_agent", "claude_agent"):
        agent = dict(config.defaults)
        agent.update(config.agents[agent_name])
        selected = _select_task_skills(
            agent,
            "Send a Salesforce email template without removing the letterhead or signature",
        )
        assert "customer_email" in selected, agent_name


def test_operational_agents_load_deep_investigation_for_causal_invoice_work():
    root = Path(__file__).resolve().parents[1]
    config = load_config(root / "config" / "agents.yaml")
    task = "Investigate invoice 12643 and explain the negative spare root cause"

    for agent_name in ("direct_codex", "coding_agent", "tickets_agent", "billing_agent"):
        agent = dict(config.defaults)
        agent.update(config.agents[agent_name])
        selected = _select_task_skills(agent, task)
        assert "deep_operational_investigation" in selected, agent_name

    thor = dict(config.defaults)
    thor.update(config.agents["claude_agent"])
    assert "deep_operational_investigation" not in _select_task_skills(thor, task)


def test_operational_agents_load_acknowledged_handoff_and_never_route_to_rory():
    root = Path(__file__).resolve().parents[1]
    config = load_config(root / "config" / "agents.yaml")
    task = "Hand off this missing tool repair to another agent and require it to be durably acknowledged"

    for agent_name in ("direct_codex", "coding_agent", "tickets_agent", "billing_agent"):
        agent = dict(config.defaults)
        agent.update(config.agents[agent_name])
        selected = _select_task_skills(agent, task)
        assert "acknowledged_agent_handoff" in selected, agent_name

    skill = (root / "skills" / "acknowledged_agent_handoff.md").read_text(encoding="utf-8")
    assert "Never target Rory" in skill
    assert "cannot receive agent communication" in skill
