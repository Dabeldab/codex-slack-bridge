# AgentChat/coding_agent 2026-07-10T16:19:20-04:00
# AgentChat/direct_codex 2026-07-13T01:28:53-04:00: verify bounded Slack attachment effort routing.
from codex_slack_bridge.agents import AgentRequest, select_task_effort, select_task_model


def request(text: str, *, task_kind: str = "", task_text: str = "") -> AgentRequest:
    return AgentRequest(
        text=text,
        channel_id="command_center",
        user_id="local_command_center",
        thread_ts="job-1",
        task_kind=task_kind,
        task_text=task_text,
    )


def test_simple_question_uses_low_effort():
    agent = {"effort": "xhigh", "effort_default": "medium", "effort_min": "low", "effort_autoscale": True}
    assert select_task_effort("coding_agent", agent, request("what is Jamie doing right now?")) == "low"


def test_known_bounded_routine_uses_medium_effort():
    agent = {"effort": "xhigh", "effort_default": "medium", "effort_min": "low", "effort_autoscale": True}
    assert select_task_effort("coding_agent", agent, request("run the singapore routine now")) == "medium"


def test_readonly_slack_attachment_uses_medium_effort():
    agent = {"effort": "xhigh", "effort_default": "medium", "effort_min": "low"}
    req = AgentRequest(
        text="Here is the file",
        channel_id="C",
        user_id="U",
        thread_ts="",
        task_kind="slack-attachment-readonly",
        task_text="Please review and summarize this report",
    )
    assert select_task_effort("coding_agent", agent, req) == "medium"


def test_live_write_uses_at_least_high_effort():
    agent = {"effort": "xhigh", "effort_default": "medium", "effort_min": "low", "effort_autoscale": True}
    assert select_task_effort("coding_agent", agent, request("delete card 0136 and create the ticket")) == "high"


def test_complex_engineering_uses_coding_agent_maximum():
    agent = {"effort": "xhigh", "effort_default": "medium", "effort_min": "low", "effort_autoscale": True}
    assert select_task_effort("coding_agent", agent, request("debug and repair the race condition")) == "xhigh"


def test_non_coding_lane_is_capped_at_configured_maximum():
    agent = {"effort": "high", "effort_default": "medium", "effort_min": "low", "effort_autoscale": True}
    assert select_task_effort("billing_agent", agent, request("implement a new reconciliation system")) == "high"


def test_command_center_task_text_avoids_policy_boilerplate_overclassification():
    agent = {"effort": "xhigh", "effort_default": "medium", "effort_min": "low", "effort_autoscale": True}
    req = request(
        "Long generated prompt mentioning send, delete, deploy, and every safety policy.",
        task_kind="ops-email-watch",
        task_text="scan the inbox and report what needs attention",
    )
    assert select_task_effort("coding_agent", agent, req) == "medium"


def model_agent(**overrides):
    agent = {
        "name": "coding_agent",
        "model": "gpt-5.6-sol",
        "model_autoselect": True,
        "model_fast": "gpt-5.6-terra",
        "model_quality": "gpt-5.6-sol",
    }
    agent.update(overrides)
    return agent


def test_simple_question_uses_fast_model():
    assert (
        select_task_model(
            "coding_agent",
            model_agent(),
            request("what is Jamie doing right now?"),
        )
        == "gpt-5.6-terra"
    )


def test_live_write_uses_quality_model():
    assert (
        select_task_model(
            "billing_agent",
            model_agent(name="billing_agent"),
            request("collect the partial location balance in Maxio"),
        )
        == "gpt-5.6-sol"
    )


def test_complex_task_uses_quality_model():
    assert (
        select_task_model(
            "coding_agent",
            model_agent(),
            request("debug and repair the cross-system race condition"),
        )
        == "gpt-5.6-sol"
    )


def test_attachment_uses_quality_model():
    req = AgentRequest(
        text="review this",
        channel_id="command_center",
        user_id="local_command_center",
        thread_ts="job-1",
        files_context="report.pdf",
    )
    assert select_task_model("coding_agent", model_agent(), req) == "gpt-5.6-sol"


def test_model_autoselect_can_be_disabled_without_changing_configured_model():
    assert (
        select_task_model(
            "coding_agent",
            model_agent(model="custom-model", model_autoselect=False),
            request("what is the status?"),
        )
        == "custom-model"
    )
