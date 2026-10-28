# AgentChat/coding_agent 2026-07-10T17:32:00-04:00
# AgentChat/coding_agent 2026-07-10T17:46:00-04:00
# AgentChat/coding_agent 2026-07-10T18:40:26-04:00
# AgentChat/tickets_agent 2026-07-10T19:24:00-04:00
# AgentChat/coding_agent 2026-07-11T05:15:00-04:00
# AgentChat/direct_codex 2026-07-13T00:16:00-04:00
# AgentChat/direct_codex 2026-07-14T14:45:00-04:00: verify Jamie loads the corrected billing-location workflow.
# AgentChat/coding_agent 2026-07-13T11:45:00-04:00
import json
import subprocess
from pathlib import Path
from threading import Event
from types import SimpleNamespace

import codex_slack_bridge.agents as agents_module

from codex_slack_bridge.agents import (
    TOOL_SELECTION_CONTRACT,
    FINAL_OUTCOME_REPORTING,
    SHARED_AGENT_BEHAVIOR,
    TECH_SUPPORT_TEAM_IDENTITY,
    WARM_SESSION_TASK_REMINDER,
    AgentRequest,
    CodexProcessResult,
    _capability_inventory_block,
    _direct_codex_prompt,
    _pipeline_registry_block,
    _prompt_fingerprint,
    _normalize_unattended_mcp_approval_message,
    _looks_like_retryable_cloud_config_bundle_timeout,
    _looks_like_retryable_pre_session_codex_exit,
    _tool_fast_paths_block,
    build_main_prompt,
    build_codex_command,
    build_static_prompt,
    select_task_timeout,
    run_codex_cli,
    _watch_codex_final_output,
    cancel_agent_job,
)


def test_unattended_mcp_rejection_does_not_claim_the_operator_cancelled():
    message = _normalize_unattended_mcp_approval_message(
        "salesforce_ticket_resolve failed: user cancelled MCP tool call"
    )

    assert "user cancelled" not in message.lower()
    assert "approval was unavailable or rejected" in message
    assert "no write was confirmed" in message
from codex_slack_bridge.config import load_config


def test_second_pipe_timeout_never_falls_back_to_unbounded_communicate(monkeypatch):
    class Stream:
        def __init__(self):
            self.closed = False

        def close(self):
            self.closed = True

    class FakeProcess:
        pid = 4244

        def __init__(self):
            self.communicate_calls = []
            self.wait_calls = []
            self.stdin = Stream()
            self.stdout = Stream()
            self.stderr = Stream()

        def communicate(self, input=None, timeout=None):
            self.communicate_calls.append(timeout)
            raise subprocess.TimeoutExpired(["codex"], timeout, output=b"partial", stderr=b"held")

        def wait(self, timeout=None):
            self.wait_calls.append(timeout)
            raise subprocess.TimeoutExpired(["codex"], timeout)

    process = FakeProcess()
    terminated = []
    monkeypatch.setattr(agents_module, "_terminate_process_tree", lambda item: terminated.append(item.pid))

    stdout, stderr = agents_module._terminate_and_collect_bounded(
        process,
        subprocess.TimeoutExpired(["codex"], 1, output=b"first", stderr=b"error"),
        drain_timeout=0.1,
    )

    assert stdout == b"partial"
    assert stderr == b"held"
    assert process.communicate_calls == [0.1]
    assert process.wait_calls == [5]
    assert terminated == [4244, 4244]
    assert process.stdin.closed and process.stdout.closed and process.stderr.closed


def test_isolated_worker_uses_framed_result_when_child_writes_incidental_output(monkeypatch):
    class FakeProcess:
        pid = 4245
        returncode = 0

        def communicate(self, input=None, timeout=None):
            assert input and timeout
            return b"incidental output\n__CODEX_AGENT_RESULT__{\"ok\":true,\"result\":\"done\"}", b""

    process = FakeProcess()
    popen_kwargs = {}

    def fake_popen(*args, **kwargs):
        popen_kwargs.update(kwargs)
        return process

    monkeypatch.setattr(agents_module.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(agents_module, "_register_agent_process", lambda *args, **kwargs: None)
    monkeypatch.setattr(agents_module, "_unregister_agent_process", lambda *args, **kwargs: None)

    result = agents_module.run_agent_isolated(
        "coding_agent",
        {"timeout_seconds": 30, "agent_job_hard_timeout_seconds": 60},
        AgentRequest(text="test", channel_id="C", user_id="U", thread_ts="", job_id=7),
    )

    assert result == "done"
    assert "env" not in popen_kwargs


def test_cloud_config_cold_start_timeout_retries_with_bounded_backoff_before_session_or_output(
    tmp_path, monkeypatch
):
    attempts = []
    sleeps = []

    def fake_run_codex_process(command, *_args, **_kwargs):
        attempts.append(list(command))
        output_path = Path(command[-1].split("=", 1)[1])
        output_path.unlink(missing_ok=True)
        if len(attempts) < 4:
            return CodexProcessResult(
                final_text="Codex could not complete this run.",
                returncode=1,
                stdout="",
                stderr="Error: timed out waiting for cloud config bundle after 15s",
                session_id="",
                final_message="",
            )
        return CodexProcessResult(
            final_text="COMPLETED\n\nThe fourth process succeeded.",
            returncode=0,
            stdout="",
            stderr="session id: 019f9000-0000-7000-8000-000000000001",
            session_id="019f9000-0000-7000-8000-000000000001",
            final_message="COMPLETED\n\nThe fourth process succeeded.",
        )

    monkeypatch.setattr(
        agents_module,
        "_require_request_authority",
        lambda *_args, **_kwargs: SimpleNamespace(trusted=True, operator_authorized=True),
    )
    monkeypatch.setattr(agents_module, "build_child_process_env", lambda *_args, **_kwargs: ({}, object()))
    monkeypatch.setattr(agents_module, "run_codex_process", fake_run_codex_process)
    monkeypatch.setattr(agents_module.time, "sleep", lambda seconds: sleeps.append(seconds))
    agent = {
        "provider": "codex_cli_direct",
        "workspace_root": str(tmp_path),
        "sandbox": "read-only",
        "timeout_seconds": 30,
        "persistent_agent_sessions": False,
        "ephemeral": True,
    }

    result = run_codex_cli(
        "raw_codex",
        agent,
        AgentRequest(text="report health", channel_id="direct", user_id="user", thread_ts="task"),
        direct_session=True,
    )

    assert result == "COMPLETED\n\nThe fourth process succeeded."
    assert len(attempts) == 4
    assert sleeps == [2.0, 5.0, 10.0]


def test_cloud_config_timeout_is_not_retryable_after_session_or_output():
    base = {
        "final_text": "failed",
        "returncode": 1,
        "stdout": "",
        "stderr": "Error: timed out waiting for cloud config bundle after 15s",
        "session_id": "",
        "final_message": "",
    }

    assert _looks_like_retryable_cloud_config_bundle_timeout(CodexProcessResult(**base)) is True
    assert (
        _looks_like_retryable_cloud_config_bundle_timeout(
            CodexProcessResult(**{**base, "session_id": "019f9000-0000-7000-8000-000000000002"})
        )
        is False
    )
    assert (
        _looks_like_retryable_cloud_config_bundle_timeout(
            CodexProcessResult(**{**base, "stdout": "tool activity started"})
        )
        is False
    )
    assert (
        _looks_like_retryable_cloud_config_bundle_timeout(
            CodexProcessResult(**{**base, "final_message": "BLOCKED"})
        )
        is False
    )


def test_any_pre_session_codex_exit_is_retryable_once_without_model_or_tool_output():
    base = {
        "final_text": "Codex could not complete this run.",
        "returncode": 1,
        "stdout": "",
        "stderr": "",
        "session_id": "",
        "final_message": "",
    }

    assert _looks_like_retryable_pre_session_codex_exit(CodexProcessResult(**base)) is True
    assert _looks_like_retryable_pre_session_codex_exit(
        CodexProcessResult(**{**base, "stderr": "runtime initialization failed"})
    ) is True
    assert _looks_like_retryable_pre_session_codex_exit(
        CodexProcessResult(**{**base, "session_id": "019f9000-0000-7000-8000-000000000003"})
    ) is False
    assert _looks_like_retryable_pre_session_codex_exit(
        CodexProcessResult(**{**base, "stdout": "tool call started"})
    ) is False


def test_cancel_agent_job_terminates_only_the_registered_job(monkeypatch):
    class FakeProcess:
        def poll(self):
            return None

    process = FakeProcess()
    agents_module.ACTIVE_AGENT_PROCESSES[71] = process
    terminated = []
    monkeypatch.setattr(agents_module, "_terminate_process_tree", lambda item: terminated.append(item))
    try:
        assert cancel_agent_job(71) is True
        assert cancel_agent_job(72) is False
        assert terminated == [process]
    finally:
        agents_module.ACTIVE_AGENT_PROCESSES.clear()


def test_codex_final_output_watchdog_releases_lingering_process(tmp_path, monkeypatch):
    output_path = tmp_path / "final.txt"
    output_path.write_text("COMPLETED - work is done", encoding="utf-8")

    class FakeProcess:
        pid = 4243

        def poll(self):
            return None

    process = FakeProcess()
    stop_event = Event()
    terminated_event = Event()
    terminated = []
    monkeypatch.setattr(agents_module, "_terminate_process_tree", lambda item: terminated.append(item.pid))

    _watch_codex_final_output(
        process,
        str(output_path),
        stop_event,
        terminated_event,
        grace_seconds=0,
        poll_seconds=0.01,
    )

    assert terminated_event.is_set()
    assert terminated == [4243]


def test_tool_contract_makes_browser_the_last_resort():
    assert "purpose-built MCP/app connector" in TOOL_SELECTION_CONTRACT
    assert "native service API" in TOOL_SELECTION_CONTRACT
    assert "(4) browser automation" in TOOL_SELECTION_CONTRACT
    assert "Maxio/Chargify, API/connector use is mandatory" in TOOL_SELECTION_CONTRACT


def test_managed_agents_must_report_one_explicit_final_outcome():
    assert "`COMPLETED`" in FINAL_OUTCOME_REPORTING
    assert "`COMPLETED_WITH_ISSUES`" in FINAL_OUTCOME_REPORTING
    assert "`BLOCKED`" in FINAL_OUTCOME_REPORTING
    assert "`FAILED`" in FINAL_OUTCOME_REPORTING
    assert "exactly one outcome" in FINAL_OUTCOME_REPORTING
    assert FINAL_OUTCOME_REPORTING in WARM_SESSION_TASK_REMINDER

    config = load_config("config/agents.yaml")
    for name, raw_agent in config.agents.items():
        agent = {**config.defaults, **raw_agent, "name": name}
        if agent.get("provider") == "codex_cli_direct" and agent.get("direct_codex_raw_prompt") is True:
            direct = _direct_codex_prompt(
                AgentRequest(text="check status", channel_id="direct", user_id="user", thread_ts="task")
            )
            assert direct == "check status", name
            assert FINAL_OUTCOME_REPORTING.strip() not in direct, name
            continue
        static = build_static_prompt(name, str(agent.get("prompt_prefix") or ""), agent)
        assert FINAL_OUTCOME_REPORTING in static, name


def test_managed_agents_share_persistence_and_voice_behavior():
    assert "every required in-scope platform" in SHARED_AGENT_BEHAVIOR
    assert "Darius's speech pattern" in SHARED_AGENT_BEHAVIOR
    assert "Alex" in SHARED_AGENT_BEHAVIOR
    assert "Taylor communicates as a woman" in SHARED_AGENT_BEHAVIOR
    assert "Continuous workflow improvement for every Agent Chat agent" in SHARED_AGENT_BEHAVIOR
    assert "create or narrowly update the smallest useful reusable workflow" in SHARED_AGENT_BEHAVIOR
    assert "Register reusable artifacts in the shared artifact index" in SHARED_AGENT_BEHAVIOR
    assert "must never broaden an agent's existing capabilities" in SHARED_AGENT_BEHAVIOR
    assert "Salesforce ticket updates are for human-useful business results only" in SHARED_AGENT_BEHAVIOR
    assert "source message or thread IDs" in SHARED_AGENT_BEHAVIOR
    assert "Do not append a second technical audit paragraph" in SHARED_AGENT_BEHAVIOR
    assert "Never post a failure, permission, validation, tool, or recovery blocker" in SHARED_AGENT_BEHAVIOR
    assert "Technical Notes / Description are initial-ticket content only" in SHARED_AGENT_BEHAVIOR
    assert "The ticket already contains the original request, prior comments, and customer context" in SHARED_AGENT_BEHAVIOR
    assert "Never fill Cause, Resolution, or Next steps merely to complete a format" in SHARED_AGENT_BEHAVIOR
    assert "`API pricing email sent.`" in SHARED_AGENT_BEHAVIOR
    assert "materially changes urgency" in SHARED_AGENT_BEHAVIOR
    assert "Never record routine positive, neutral, satisfied, or generic sentiment" in SHARED_AGENT_BEHAVIOR
    assert "Autogenerated LogMeIn ticket context" in SHARED_AGENT_BEHAVIOR
    assert "connector-generated at session close" in SHARED_AGENT_BEHAVIOR
    assert "must not be treated as the owner of connector cleanup" in SHARED_AGENT_BEHAVIOR
    assert "scan the complete customer-authored chat" in SHARED_AGENT_BEHAVIOR
    assert "Do not use a fixed chat-line position" in SHARED_AGENT_BEHAVIOR
    assert "required How Contacted/Contact Method ticket field" in SHARED_AGENT_BEHAVIOR
    assert "ticket's internal notes" not in SHARED_AGENT_BEHAVIOR
    assert "salesforce_ticket_internal_request_post" in SHARED_AGENT_BEHAVIOR
    assert "Julio and Wiko are the only employee-request DM exceptions" in SHARED_AGENT_BEHAVIOR
    assert "Never direct-message Leo" in SHARED_AGENT_BEHAVIOR
    assert "review every ticket individually" in SHARED_AGENT_BEHAVIOR
    assert "Never classify tickets from a queue, subject, age, or status alone" in SHARED_AGENT_BEHAVIOR
    assert "Customer confirmation is not required" in SHARED_AGENT_BEHAVIOR
    assert "specific callback, contact, or follow-up arrangement" in SHARED_AGENT_BEHAVIOR
    assert "salesforce_ticket_chatter_reply" in SHARED_AGENT_BEHAVIOR
    assert "supply the same `feed_element_id` to `salesforce_ticket_resolve`" in SHARED_AGENT_BEHAVIOR
    assert "latest top-level posts and nested replies" in SHARED_AGENT_BEHAVIOR
    assert "never post the same fact or outcome twice" in SHARED_AGENT_BEHAVIOR
    assert "Closing a ticket does not require a Chatter note" in SHARED_AGENT_BEHAVIOR
    assert "close silently" in SHARED_AGENT_BEHAVIOR
    assert "Customer email drafts and sends contain only customer-relevant facts" in SHARED_AGENT_BEHAVIOR
    assert "If Nova caused the issue" in SHARED_AGENT_BEHAVIOR
    assert "outside service, configuration, or user action" in SHARED_AGENT_BEHAVIOR
    assert "Never invent a cause" in SHARED_AGENT_BEHAVIOR
    assert (
        "Hey Leo, Collagen Aesthetics doesn't have a card on file and they're "
        "gonna go inactive again soon."
    ) in SHARED_AGENT_BEHAVIOR

    config = load_config("config/agents.yaml")
    assert {"security", "nova_voice"} <= set(config.defaults["core_skills"])
    for name, raw_agent in config.agents.items():
        if raw_agent.get("provider") == "codex_cli_direct" and raw_agent.get("direct_codex_raw_prompt") is True:
            continue
        agent = {**config.defaults, **raw_agent, "name": name}
        static = build_static_prompt(name, str(agent.get("prompt_prefix") or ""), agent)
        assert SHARED_AGENT_BEHAVIOR in static, name
        skills = agents_module._skills_block(agent, "message Leo about an account")
        assert "## nova_voice" in skills, name
        assert "Collagen Aesthetics" in skills, name


def test_internal_employee_request_registry_is_salesforce_first_and_dm_bounded():
    registry = json.loads(
        Path("config/pipeline-registry.json").read_text(encoding="utf-8")
    )["pipelines"]
    workflow = registry["internal_staff_request"]
    assert workflow["primary_agents"] == [
        "coding_agent",
        "tickets_agent",
        "billing_agent",
    ]
    assert "salesforce_ticket_internal_request_post" in workflow["requires_tools"]
    workflow_text = " ".join(
        [
            *workflow["preferred_entrypoints"],
            *workflow["avoid_by_default"],
            *workflow["steps"],
            *workflow["verification"],
        ]
    )
    assert "Only Julio or Wiko" in workflow_text
    assert "direct messages to Leo or another Salesforce user" in workflow_text
    assert "real Chatter mention" in workflow_text
    assert "first-message-of-day greeting" in workflow_text

    zoom = registry["zoom_team_chat_direct_message"]
    assert zoom["display_name"] == "Julio/Wiko Zoom Request Message"
    assert "message a zoom user" not in zoom["aliases"]
    zoom_text = " ".join(
        [
            *zoom["preferred_entrypoints"],
            *zoom["avoid_by_default"],
            *zoom["steps"],
        ]
    )
    assert "configured:julio or configured:wiko" in zoom_text
    assert "any recipient other than Julio or Wiko" in zoom_text

    fast_paths = json.loads(
        Path("config/tool-fast-paths.json").read_text(encoding="utf-8")
    )["tools"]
    zoom_credentials = fast_paths["zoom"]["credentials"]
    required_names = {
        name
        for group in zoom_credentials["required_any"]
        for name in group
    }
    assert {
        "ZOOM_ACCOUNT_ID",
        "ZOOM_CLIENT_ID",
        "ZOOM_CLIENT_SECRET",
        "ZOOM_SINGAPORE_JULIO_CONTACT",
        "ZOOM_INTERNAL_REQUEST_WIKO_CONTACT",
    } <= required_names
    assert "ZOOM_INTERNAL_REQUEST_WIKO_CONTACT" not in zoom_credentials["optional"]


def test_sql_audit_details_stay_internal_not_in_salesforce_updates():
    config = load_config("config/agents.yaml")
    taylor = {**config.defaults, **config.agents["coding_agent"]}
    taylor_prompt = " ".join(str(taylor.get("prompt_prefix") or "").split())
    assert "guarded receipt and private agent memory" in taylor_prompt
    assert "Never put database or backup names" in taylor_prompt
    assert "short human-useful business result" in taylor_prompt

    registry = json.loads(Path("config/pipeline-registry.json").read_text(encoding="utf-8"))
    verification = " ".join(registry["pipelines"]["nova_sql_guarded_write"]["verification"])
    assert "only in the guarded receipt and private agent memory" in verification
    assert "source message IDs" in verification
    assert "scope disclaimers" in verification


def test_salesforce_ticket_review_registry_requires_individual_disposition_and_threaded_updates():
    pipelines = json.loads(Path("config/pipeline-registry.json").read_text(encoding="utf-8"))[
        "pipelines"
    ]
    review = pipelines["salesforce_ticket_investigation"]
    aliases = set(review["aliases"])
    steps = " ".join(review["steps"])
    verification = " ".join(review["verification"])

    assert {
        "review all tickets",
        "review open tickets",
        "review support tickets",
        "review billing tickets",
        "ticket audit",
    } <= aliases
    assert "open every ticket individually" in steps
    assert "never use a sample" in steps
    assert "Customer confirmation is not required" in steps
    assert "specific callback, contact, or follow-up arrangement" in steps
    assert "salesforce_ticket_chatter_reply" in steps
    assert "reconcile its support/billing queue or review card" in steps
    assert "account for every ticket in the established set" in verification
    assert "nested comment" in verification
    assert "without update sections" in steps


def test_billing_subscription_repair_registry_exposes_four_verified_modes():
    pipelines = json.loads(Path("config/pipeline-registry.json").read_text(encoding="utf-8"))[
        "pipelines"
    ]
    repair = pipelines["billing_subscription_repair"]
    aliases = set(repair["aliases"])

    assert repair["primary_agents"] == ["billing_agent"]
    assert repair["requires_tools"] == ["salesforce", "chargify"]
    assert {
        "upgrade no charge",
        "downgrade no charge",
        "downgrade no credit",
        "upgrade with credit",
        "downgrade with credit",
    } <= aliases
    steps = " ".join(repair["steps"])
    assert "maxio_component_allocation_preview" in steps
    assert "maxio_component_allocation_apply" in steps
    assert "maxio_manual_service_credit_preview/apply" in steps
    assert "maxio_billing_cycle_recovery_preview/apply" in steps
    assert "salesforce_billing_account_orders_read" in steps
    assert "keep Jamie's parent job active" in steps
    assert "Create or reuse one privately idempotent 3. Billing ticket" in steps
    assert "keep the idempotency/source key out of Salesforce ticket fields" in steps
    assert "automatic charge, credit, or proration" in " ".join(repair["verification"])

    fast_paths = json.loads(
        Path("config/tool-fast-paths.json").read_text(encoding="utf-8")
    )["tools"]["chargify"]
    fast_start = " ".join(fast_paths["fast_start"])
    assert "maxio_capabilities" in fast_start
    assert "subscriptionRepairModes" in fast_start
    assert "maxio_subscription_account_balances" in fast_start
    assert "maxio_billing_cycle_recovery_preview/apply" in fast_start
    assert "keep Jamie's parent job active" in fast_start


# AgentChat/direct_codex 2026-07-31T00:00:00-04:00: keep short rate/promo
# tickets bound to the complete cross-system workflow and one outcome-only note.
def test_billing_rate_and_promotion_registry_is_complete_for_brief_tickets():
    pipelines = json.loads(Path("config/pipeline-registry.json").read_text(encoding="utf-8"))[
        "pipelines"
    ]
    workflow = pipelines["billing_rate_or_promotion_change"]
    aliases = set(workflow["aliases"])
    text = " ".join(
        workflow["preferred_entrypoints"]
        + workflow["avoid_by_default"]
        + workflow["steps"]
        + workflow["verification"]
    )

    assert workflow["primary_agents"] == ["billing_agent"]
    assert workflow["requires_tools"] == ["salesforce", "chargify"]
    assert {"rate change", "promotion", "promo", "coupon", "3 months free"} <= aliases
    assert "ticket brevity does not narrow the standard" in text
    assert "maxio_subscription_coupon_preview/apply" in text
    assert "maxio_subscription_product_change_preview/apply" in text
    assert "GSPayTech Sub text and Account Payments Partner are not provider evidence" in text
    assert "Worldpay, Creditcall, Authorize.net, or Propelr" in text
    assert "no fallback is allowed" in text
    assert "maxio_nova_integrated_products" in text
    assert "never set or copy an Account flat rate unless the ticket explicitly requests one" in text
    assert "Salesforce Location Bill Amount" in text
    assert "salesforce_billing_location_gateway_update" in text
    assert "invoice consequence" in text
    assert "salesforce_ticket_resolve" in text
    assert "salesforce_ticket_chatter_post" in text
    assert "never both" in text
    assert "never narrate tools" in text

    config = load_config("config/agents.yaml")
    jamie = {**config.defaults, **config.agents["billing_agent"], "name": "billing_agent"}
    static = build_static_prompt(
        "billing_agent",
        str(jamie.get("prompt_prefix") or ""),
        jamie,
    )
    static_text = " ".join(static.split())
    assert "Ticket brevity does not narrow that workflow" in static_text
    assert "maxio_subscription_coupon_preview/apply" in static_text
    assert "maxio_subscription_product_change_preview/apply" in static_text
    assert "A promotion never implies an Account" in static_text
    assert "flat rate or a location-rate change" in static_text
    assert "merchant provider is required" in static_text
    assert "never infer a fallback" in static_text
    assert "never call both for the same outcome" in static_text
    assert "Never narrate tools, checks, permissions" in static_text

    fast_path = json.loads(
        Path("config/tool-fast-paths.json").read_text(encoding="utf-8")
    )["tools"]["chargify"]
    fast_text = " ".join(fast_path["fast_start"])
    assert "generic maxio_api_request cannot do either" in fast_text
    assert "Account metadata are not provider evidence" in fast_text
    assert "there is no fallback" in fast_text
    assert "current-invoice disposition" in fast_text


def test_additional_trial_location_registry_enforces_full_lifecycle():
    pipelines = json.loads(Path("config/pipeline-registry.json").read_text(encoding="utf-8"))[
        "pipelines"
    ]
    workflow = pipelines["billing_additional_trial_location"]
    text = " ".join(
        workflow["preferred_entrypoints"]
        + workflow["avoid_by_default"]
        + workflow["steps"]
        + workflow["verification"]
    )

    assert workflow["primary_agents"] == ["billing_agent"]
    assert workflow["handoff_agents"] == ["coding_agent"]
    assert workflow["requires_tools"] == ["salesforce", "chargify", "nova_sql"]
    assert "Worldpay, Creditcall, Authorize.net, and Propelr" in text
    assert "ask when it is absent" in text
    assert "maxio_nova_integrated_promo_credit_preview/apply" in text
    assert "9999 cents" in text
    assert "Account.Flat_Rate_Amount__c unchanged" in text
    assert "Within the 3-months" in text
    assert "reactivation always uses Re-activate an Existing Location" in text
    assert "Only a brand-new additional location" in text
    assert "Account.CreatedDate plus three calendar months" in text
    assert "Terms Agreed is not a classification date" in text
    assert "Existing and (New) Additional Customer Order" in text
    assert "New Customer Order" in text
    assert "no ProcessInstance" in text
    assert "Keep Jamie's parent job active" in text
    assert "ticket leaves all agent lanes" in text

def test_salesforce_template_email_registry_loads_exact_tools_without_discovery():
    tools = json.loads(Path("config/tool-fast-paths.json").read_text(encoding="utf-8"))[
        "tools"
    ]
    pipelines = json.loads(
        Path("config/pipeline-registry.json").read_text(encoding="utf-8")
    )["pipelines"]
    route = tools["salesforce_template_email"]
    pipeline = pipelines["salesforce_approved_template_email"]

    assert route["primary_agents"] == [
        "direct_codex",
        "tickets_agent",
        "billing_agent",
        "coding_agent",
    ]
    route_text = " ".join(
        [route["first_action"]]
        + route["fast_start"]
        + route["never_allowed"]
        + route["known_notes"]
    )
    for required in (
        "salesforce_email_template_inventory",
        "salesforce_ticket_email_log_read",
        "salesforce_ticket_template_email_preview",
        "salesforce_ticket_template_email_send",
        "salesforce_ticket_company_credentials_email_preview/send",
        "support@novapointofsale.com",
        "billing@novapointofsale.com",
        "EmailMessage.FromAddress",
        "approved_sendable",
        "content_pending",
    ):
        assert required in route_text

    assert pipeline["requires_tools"] == ["salesforce_template_email"]
    pipeline_text = " ".join(
        pipeline["preferred_entrypoints"]
        + pipeline["avoid_by_default"]
        + pipeline["steps"]
        + pipeline["verification"]
    )
    assert "ticket 347370" in pipeline_text
    assert "rendered credential body" in pipeline_text
    assert "support one-off route is available" in pipeline_text
    assert "billing one-off route remains unavailable" in pipeline_text
    assert "Izhak Musli" in pipeline_text
    assert "proactive ticket email from" in pipeline_text

    config = load_config("config/agents.yaml")
    for agent_name in ("tickets_agent", "billing_agent", "coding_agent"):
        agent = {**config.defaults, **config.agents[agent_name], "name": agent_name}
        query = "send this customer a Salesforce template email"
        assert "[salesforce_template_email]" in _tool_fast_paths_block(agent, query)
        assert (
            "[salesforce_approved_template_email]"
            in _pipeline_registry_block(agent, query)
        )

    thor = {
        **config.defaults,
        **config.agents["claude_agent"],
        "name": "claude_agent",
    }
    assert "[salesforce_template_email]" not in _tool_fast_paths_block(
        thor,
        "send this customer a Salesforce template email",
    )


def test_monthly_billing_alignment_registry_is_repeatable_for_jamie_and_taylor():
    pipelines = json.loads(Path("config/pipeline-registry.json").read_text(encoding="utf-8"))[
        "pipelines"
    ]
    audit = pipelines["monthly_billing_alignment_audit"]
    text = " ".join(
        audit["preferred_entrypoints"]
        + audit["avoid_by_default"]
        + audit["steps"]
        + audit["verification"]
    )

    assert audit["primary_agents"] == ["billing_agent", "coding_agent"]
    assert audit["requires_tools"] == ["salesforce", "chargify", "nova_sql"]
    for tool_name in (
        "salesforce_account_fake_classification_preview/apply",
        "salesforce_billing_location_alignment_preview/apply",
        "salesforce_billing_structure_alignment_preview/apply",
        "nova_billing_locations_read",
        "maxio_subscription_creation_preview/apply",
        "maxio_location_custom_fields_read",
        "maxio_subscription_location_mapping_preview/apply",
    ):
        assert tool_name in text
    assert "absent Maxio location metadata" in text
    assert "preapproved execution" in text


def test_managed_agents_identify_as_one_tech_support_team():
    assert "member of Nova's Tech Support department" in TECH_SUPPORT_TEAM_IDENTITY
    assert "assigned responsibilities" in TECH_SUPPORT_TEAM_IDENTITY
    assert "not a separate job identity" in TECH_SUPPORT_TEAM_IDENTITY
    assert "the Google Cloud agent" in TECH_SUPPORT_TEAM_IDENTITY

    config = load_config("config/agents.yaml")
    for name, raw_agent in config.agents.items():
        if raw_agent.get("provider") == "codex_cli_direct" and raw_agent.get("direct_codex_raw_prompt") is True:
            continue
        agent = {**config.defaults, **raw_agent, "name": name}
        static = build_static_prompt(name, str(agent.get("prompt_prefix") or ""), agent)
        assert TECH_SUPPORT_TEAM_IDENTITY in static, name

    expected_profile_identity = {
        "coding_agent": "You are Taylor, a member of Nova's Tech Support department.",
        "claude_agent": "You are Thor, a member of Nova's Tech Support department.",
        "tickets_agent": "You are Alex, a member of Nova's Tech Support department.",
        "billing_agent": "You are Jamie, a member of Nova's Tech Support department.",
    }
    for name, expected in expected_profile_identity.items():
        profile = Path(config.agents[name]["profile_file"]).read_text(encoding="utf-8")
        assert expected in profile, name
        assert "assigned responsibilities" in " ".join(profile.split()), name

    desktop_source = Path("agent-chat-desktop/MainWindow.xaml.cs").read_text(encoding="utf-8")
    assert "front desk for Nova's Tech Support team" in desktop_source
    assert "what its role is" in desktop_source
    assert "assigned responsibilities within Tech Support" in desktop_source

    handbook = Path("docs/agent-responsibilities/README.md").read_text(encoding="utf-8")
    assert "| Team identity | Assigned responsibilities |" in handbook
    assert handbook.count("| Nova Tech Support |") >= 5
    for relative_path in (
        "TAYLOR_CODING_AGENT.md",
        "THOR_AGENT.md",
        "ALEX_TICKETS_AGENT.md",
        "JAMIE_BILLING_AGENT.md",
        "DIRECT_CODEX.md",
    ):
        text = Path("docs/agent-responsibilities", relative_path).read_text(encoding="utf-8")
        assert "Team identity: Nova Tech Support" in text, relative_path
        assert "Assigned responsibilities:" in text, relative_path


def test_thor_quality_registry_uses_bounded_evidence_and_explicit_zoom_paths():
    config = load_config("config/agents.yaml")
    tools = json.loads(Path("config/tool-fast-paths.json").read_text(encoding="utf-8"))["tools"]
    pipelines = json.loads(Path("config/pipeline-registry.json").read_text(encoding="utf-8"))["pipelines"]

    assert config.defaults["ops_weekly_support_quality_enabled"] is True
    assert config.defaults["ops_weekly_support_quality_weekday"] == "Wednesday"
    assert config.defaults["ops_weekly_support_quality_local_time"] == "09:00"
    assert config.defaults["ops_weekly_support_quality_timezone"] == "America/New_York"
    quality_tool = tools["support_quality"]
    assert quality_tool["primary_agents"] == ["claude_agent"]
    assert "Salesforce ticket mutation or ticket work" in quality_tool["never_allowed"]
    assert any(
        "Salesforce ticket, feed, and email-log evidence" in action
        for action in quality_tool["safe_actions"]
    )
    assert any(
        "explicitly operator-requested Zoom message" in action
        for action in quality_tool["safe_actions"]
    )
    assert "Zoom administration or arbitrary URL" in quality_tool["never_allowed"]
    assert "ops-weekly-support-quality only" in quality_tool["fast_start"][-1]
    assert "do not emit the managed weekly marker" in quality_tool["fast_start"][-1]
    thor_profile = Path("profiles/claude_agent.md").read_text(encoding="utf-8")
    assert "ops-weekly-support-quality" in thor_profile
    assert "do not emit" in thor_profile
    assert "COMPLETED_WITH_ISSUES" in thor_profile
    quality_pipeline = pipelines["weekly_support_quality"]
    assert quality_pipeline["primary_agents"] == ["claude_agent"]
    assert quality_pipeline["requires_tools"] == ["support_quality", "logmein_rescue"]
    assert quality_pipeline["result_contract"]["marker"] == "THOR_SUPPORT_QUALITY_RESULT:"
    assert quality_pipeline["result_contract"]["schema_version"] == 1
    assert "ticketId" in quality_pipeline["result_contract"]["forbidden_fields"]
    assert "providerReceipt" in quality_pipeline["result_contract"]["forbidden_fields"]


def test_direct_codex_channel_uses_managed_general_purpose_lane_with_raw_escape_hatch():
    config = load_config("config/agents.yaml")
    route = config.channels["C0BFLRN96DP"]
    direct = {**config.defaults, **config.agents["direct_codex"]}
    raw = {**config.defaults, **config.agents["raw_codex"]}

    assert route.agent_name == "direct_codex"
    assert route.listen == "all_messages"
    assert direct["provider"] == "codex_cli"
    assert direct.get("direct_codex_raw_prompt", False) is False
    assert direct["persistent_agent_sessions"] is True
    assert direct["agent_runtime_shared_sessions"] is False
    assert direct["fast_responder_enabled"] is False
    assert direct["memory_top_k"] == 4
    assert direct["subagents_mode"] == "manual"
    assert direct["max_subagents"] == 0
    assert raw["provider"] == "codex_cli_direct"
    assert raw["direct_codex_raw_prompt"] is True
    assert raw["memory_top_k"] == 0
    assert raw["max_subagents"] == 0


def test_rescue_console_mcp_is_read_only_for_alex_and_thor_not_taylor_or_jamie(tmp_path):
    config = load_config("config/agents.yaml")
    alex = {**config.defaults, **config.agents["tickets_agent"]}
    thor = {**config.defaults, **config.agents["claude_agent"]}
    taylor = {**config.defaults, **config.agents["coding_agent"]}
    jamie = {**config.defaults, **config.agents["billing_agent"]}
    direct = {**config.defaults, **config.agents["direct_codex"]}

    assert "rescue_console" not in (alex.get("disabled_mcp_servers") or [])
    assert "rescue_console" in thor["mcp_allowlist"]
    assert "zoom_quality_ops" in thor["mcp_allowlist"]
    assert thor["sandbox"] == "read-only"
    assert "rescue_console" in taylor["disabled_mcp_servers"]
    assert "rescue_console" in jamie["disabled_mcp_servers"]
    assert "rescue_console" not in (direct.get("disabled_mcp_servers") or [])

    mcp_config = tmp_path / "config.toml"
    mcp_config.write_text(
        "[mcp_servers.rescue_console]\ncommand = 'fixture'\n",
        encoding="utf-8",
    )
    taylor["codex_mcp_config_path"] = str(mcp_config)
    agents_module._configured_codex_mcp_servers.cache_clear()

    command = build_codex_command(
        workspace=tmp_path,
        sandbox="read-only",
        timeout=30,
        output_path=str(tmp_path / "out.txt"),
        ephemeral=True,
        agent=taylor,
    )
    assert "mcp_servers.rescue_console.enabled=false" in command


def test_jamie_loads_billing_location_reconciliation_skill():
    config = load_config("config/agents.yaml")
    jamie = {**config.defaults, **config.agents["billing_agent"]}

    assert "billing-location-reconciliation" in jamie["skills"]


def test_operational_lanes_load_fast_execution_and_lane_relevant_skills():
    config = load_config("config/agents.yaml")
    assert "fast_effective_execution" in config.defaults["core_skills"]

    for name in (
        "direct_codex",
        "coding_agent",
        "claude_agent",
        "tickets_agent",
        "billing_agent",
    ):
        agent = {**config.defaults, **config.agents[name], "name": name}
        loaded = agents_module._skills_block(
            agent,
            "Use Google Drive Nova evidence to draft the exact customer email.",
        )
        assert "## fast_effective_execution" in loaded, name
        assert "shortest verified route" in loaded, name

    assert {"google_drive", "nova_knowledge"} <= set(
        config.agents["claude_agent"]["skills"]
    )
    assert {"customer_email", "nova_knowledge"} <= set(
        config.agents["tickets_agent"]["skills"]
    )
    assert {"customer_email", "nova_knowledge"} <= set(
        config.agents["billing_agent"]["skills"]
    )


def test_direct_codex_prompt_passes_user_text_without_agent_scaffolding():
    request = AgentRequest(
        text="Please inspect the bridge and tell me what is wrong.",
        channel_id="C0BFLRN96DP",
        user_id="U0ANMFH59U0",
        thread_ts="1.0",
        context="INJECTED THREAD CONTEXT",
        memory="INJECTED AGENT MEMORY",
        files_context="Attached Slack files:\n- C:/Users/redma/data/slack_files/example.txt",
    )

    prompt = _direct_codex_prompt(request)

    assert prompt.startswith(request.text)
    assert "C:/Users/redma/data/slack_files/example.txt" in prompt
    assert "INJECTED THREAD CONTEXT" not in prompt
    assert "INJECTED AGENT MEMORY" not in prompt
    assert "Agent profile" not in prompt
    assert "TRUSTED_INSTRUCTION" not in prompt
    assert FINAL_OUTCOME_REPORTING.strip() not in prompt


def test_ephemeral_nonpersistent_jobs_never_resume_a_codex_session(tmp_path, monkeypatch):
    commands = []

    def fake_run_codex_process(command, *_args, **_kwargs):
        commands.append(list(command))
        output_path = Path(command[-1].split("=", 1)[1])
        output_path.unlink(missing_ok=True)
        return CodexProcessResult(
            final_text="done",
            returncode=0,
            stdout="",
            stderr="",
            session_id="new-session-that-must-not-be-reused",
        )

    monkeypatch.setattr(
        agents_module,
        "_require_request_authority",
        lambda *_args, **_kwargs: SimpleNamespace(trusted=True, operator_authorized=True),
    )
    monkeypatch.setattr(agents_module, "build_child_process_env", lambda *_args, **_kwargs: ({}, object()))
    monkeypatch.setattr(agents_module, "assess_live_write_request", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(agents_module, "trusted_message_policy_block", lambda *_args, **_kwargs: "")
    monkeypatch.setattr(agents_module, "child_env_policy_block", lambda *_args, **_kwargs: "")
    monkeypatch.setattr(agents_module, "live_write_policy_block", lambda *_args, **_kwargs: "")
    monkeypatch.setattr(agents_module, "run_subagents", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(
        agents_module,
        "session_store_from_agent",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("session store must not be read")),
    )
    monkeypatch.setattr(agents_module, "run_codex_process", fake_run_codex_process)
    agent = {
        "provider": "codex_cli",
        "workspace_root": str(tmp_path),
        "sandbox": "read-only",
        "timeout_seconds": 30,
        "persistent_agent_sessions": False,
        "warm_session_prompt_cache": False,
        "agent_runtime_shared_sessions": False,
        "agent_runtime_session_scope": "conversation",
        "ephemeral": True,
    }

    for job_id, source_type in ((1, "ops-email-watch"), (2, "ops-singapore-remediation-ticket")):
        assert run_codex_cli(
            "coding_agent",
            agent,
            AgentRequest(
                text=f"run {source_type}",
                channel_id="command_center",
                user_id="local_command_center",
                thread_ts=f"job-{job_id}",
                job_id=job_id,
                surface="command_center",
                conversation_id=f"command_center:coding_agent:{source_type}:job-{job_id}",
                task_kind=source_type,
            ),
        ) == "done"

    assert len(commands) == 2
    assert all(command[:3] == ["codex", "exec", "--cd"] for command in commands)
    assert all("resume" not in command for command in commands)
    assert all("--ephemeral" in command for command in commands)


def test_explicit_live_write_runs_in_primary_lane_without_read_only_subagent(tmp_path, monkeypatch):
    subagent_calls = []
    monkeypatch.setattr(
        agents_module,
        "_require_request_authority",
        lambda *_args, **_kwargs: SimpleNamespace(trusted=True, operator_authorized=True),
    )
    monkeypatch.setattr(agents_module, "build_child_process_env", lambda *_args, **_kwargs: ({}, object()))
    monkeypatch.setattr(
        agents_module,
        "_assess_request_live_write",
        lambda *_args, **_kwargs: SimpleNamespace(explicitly_authorized=True),
    )
    monkeypatch.setattr(agents_module, "trusted_message_policy_block", lambda *_args, **_kwargs: "")
    monkeypatch.setattr(agents_module, "child_env_policy_block", lambda *_args, **_kwargs: "")
    monkeypatch.setattr(agents_module, "live_write_policy_block", lambda *_args, **_kwargs: "")
    monkeypatch.setattr(
        agents_module,
        "run_subagents",
        lambda *_args, **_kwargs: subagent_calls.append(True) or [("scout", "read only")],
    )
    monkeypatch.setattr(
        agents_module,
        "run_codex_process",
        lambda *_args, **_kwargs: CodexProcessResult(
            final_text="COMPLETED\nPrimary lane executed the typed write.",
            returncode=0,
            stdout="",
            stderr="",
            session_id="",
            final_message="COMPLETED\nPrimary lane executed the typed write.",
        ),
    )

    result = run_codex_cli(
        "coding_agent",
        {
            "provider": "codex_cli",
            "workspace_root": str(tmp_path),
            "sandbox": "danger-full-access",
            "timeout_seconds": 30,
            "persistent_agent_sessions": False,
            "ephemeral": True,
            "subagents_mode": "auto",
            "subagents": [{"name": "sql", "triggers": ["sql"]}],
        },
        AgentRequest(
            text="Execute the authorized guarded SQL rebuild.",
            task_text="Execute the authorized guarded SQL rebuild.",
            channel_id="command_center",
            user_id="local_command_center",
            thread_ts="write-job",
            surface="command_center",
        ),
    )

    assert result.startswith("COMPLETED")
    assert subagent_calls == []


def test_capability_inventory_counts_secure_vault_credentials(tmp_path):
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    (vault_root / "vault.json").write_text(
        json.dumps(
            {
                "entries": {
                    "CHARGIFY_API_KEY": {"ciphertext": "not-read-by-inventory"},
                    "CHARGIFY_BASE_URL": {"ciphertext": "not-read-by-inventory"},
                }
            }
        ),
        encoding="utf-8",
    )
    known_path = tmp_path / "routes.py"
    known_path.write_text("# known client", encoding="utf-8")
    registry_path = tmp_path / "tool-fast-paths.json"
    registry_path.write_text(
        json.dumps(
            {
                "tools": {
                    "chargify": {
                        "display_name": "Chargify / Maxio",
                        "aliases": ["maxio", "billing"],
                        "primary_agents": ["billing_agent"],
                        "first_action": "Use the native API.",
                        "credentials": {
                            "required_any": [
                                ["CHARGIFY_API_KEY", "MAXIO_API_KEY"],
                                ["CHARGIFY_BASE_URL", "CHARGIFY_SUBDOMAIN"],
                            ]
                        },
                        "paths": [str(known_path)],
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    block = _capability_inventory_block(
        {
            "name": "billing_agent",
            "credential_vault_path": str(vault_root),
            "tool_fast_paths_path": str(registry_path),
        },
        "remove a Chargify payment profile",
    )

    assert "configured in env/vault" in block
    assert "known paths present 1/1" in block
    assert "not-read-by-inventory" not in block


def test_warm_prompt_omits_static_profile_but_keeps_dynamic_safety_and_task(tmp_path):
    profile = tmp_path / "profile.md"
    profile.write_text("STATIC PROFILE CONTENT", encoding="utf-8")
    registry = tmp_path / "tools.json"
    registry.write_text('{"global_rules": [], "tools": {}}', encoding="utf-8")
    agent = {
        "name": "coding_agent",
        "provider": "codex_cli",
        "model": "test-model",
        "effort": "low",
        "profile_file": str(profile),
        "tool_fast_paths_path": str(registry),
        "credential_vault_path": str(tmp_path / "vault"),
        "agent_sandbox_root": str(tmp_path / "sandboxes"),
    }
    request = AgentRequest(
        text="inspect the current task",
        channel_id="command_center",
        user_id="local",
        thread_ts="job-1",
    )
    static = build_static_prompt("coding_agent", "STATIC PREFIX", agent)

    cold = build_main_prompt("coding_agent", "STATIC PREFIX", agent, request, [], "DYNAMIC SAFETY\n", static_prompt=static)
    warm = build_main_prompt(
        "coding_agent",
        "STATIC PREFIX",
        agent,
        request,
        [],
        "DYNAMIC SAFETY\n",
        include_static=False,
        static_prompt=static,
    )

    assert "STATIC PREFIX" in cold
    assert "STATIC PROFILE CONTENT" in cold
    assert "STATIC PREFIX" not in warm
    assert "STATIC PROFILE CONTENT" not in warm
    assert "Warm-session task rules" in warm
    assert "DYNAMIC SAFETY" in warm
    assert "Reasoning effort for this task is low" in warm
    assert "inspect the current task" in warm


def test_task_effort_does_not_invalidate_static_prompt_fingerprint(tmp_path):
    base_agent = {
        "name": "billing_agent",
        "provider": "codex_cli",
        "model": "test-model",
        "tool_fast_paths_path": str(tmp_path / "missing-registry.json"),
        "credential_vault_path": str(tmp_path / "vault"),
        "agent_sandbox_root": str(tmp_path / "sandboxes"),
    }
    low = {**base_agent, "effort": "low"}
    high = {**base_agent, "effort": "high"}
    low_static = build_static_prompt("billing_agent", "same prefix", low)
    high_static = build_static_prompt("billing_agent", "same prefix", high)

    assert low_static == high_static
    assert _prompt_fingerprint(low_static, agent=low, workspace=tmp_path) == _prompt_fingerprint(
        high_static,
        agent=high,
        workspace=tmp_path,
    )


def test_long_running_task_gets_extended_watchdog_without_changing_normal_timeout():
    agent = {"timeout_seconds": 2400, "timeout_long_seconds": 3600}
    long_request = AgentRequest(
        text="Fully build the toolbox and run the end-to-end account merge integration test.",
        channel_id="command_center",
        user_id="local",
        thread_ts="long",
    )
    normal_request = AgentRequest(
        text="Check the current ticket status.",
        channel_id="command_center",
        user_id="local",
        thread_ts="normal",
    )

    assert select_task_timeout(agent, long_request) == 3600
    assert select_task_timeout(agent, normal_request) == 2400


def test_configured_agent_timeouts_allow_long_running_work():
    config = load_config("config/agents.yaml")

    assert config.agents["coding_agent"]["timeout_seconds"] == 2400
    assert config.agents["claude_agent"]["timeout_seconds"] == 2400
    assert config.agents["billing_agent"]["timeout_seconds"] == 2400
    assert config.agents["tickets_agent"]["timeout_seconds"] == 3600
    assert config.agents["direct_codex"]["timeout_seconds"] >= 2400


def test_tickets_agent_effective_timeout_is_one_hour():
    config = load_config("config/agents.yaml")
    agent = {**config.defaults, **config.agents["tickets_agent"]}
    request = AgentRequest(
        text="Resume the full account merge copy.",
        channel_id="C0BFNKX43FW",
        user_id="U0ANMFH59U0",
        thread_ts="timeout-check",
    )

    assert agent["timeout_seconds"] == 3600
    assert agent["timeout_long_seconds"] == 3600
    assert select_task_timeout(agent, request) == 3600


def test_runbook_index_is_static_and_relevant_service_card_is_lazy_loaded(tmp_path):
    index = tmp_path / "INDEX.md"
    index.write_text("CACHED RUNBOOK INDEX", encoding="utf-8")
    card = tmp_path / "chargify.md"
    card.write_text("CANONICAL CHARGIFY OPERATION CARD", encoding="utf-8")
    registry = tmp_path / "tools.json"
    registry.write_text(
        json.dumps(
            {
                "global_rules": [],
                "tools": {
                    "chargify": {
                        "display_name": "Chargify",
                        "aliases": ["maxio", "billing"],
                        "primary_agents": ["billing_agent"],
                        "documentation": str(card),
                        "paths": [str(card)],
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    agent = {
        "name": "billing_agent",
        "provider": "codex_cli",
        "model": "test-model",
        "tool_fast_paths_path": str(registry),
        "agent_tool_docs_index_path": str(index),
        "credential_vault_path": str(tmp_path / "vault"),
        "agent_sandbox_root": str(tmp_path / "sandboxes"),
    }
    request = AgentRequest(
        text="deactivate this Maxio subscription",
        task_text="deactivate this Maxio subscription",
        channel_id="command_center",
        user_id="local",
        thread_ts="job-1",
    )
    static = build_static_prompt("billing_agent", "prefix", agent)
    warm = build_main_prompt(
        "billing_agent",
        "prefix",
        agent,
        request,
        [],
        include_static=False,
        static_prompt=static,
    )

    assert "CACHED RUNBOOK INDEX" in static
    assert "CANONICAL CHARGIFY OPERATION CARD" not in static
    assert "CANONICAL CHARGIFY OPERATION CARD" in warm
    assert "CACHED RUNBOOK INDEX" not in warm


def test_all_agent_instruction_sources_use_verified_task_authority_without_known_conflicts():
    config = load_config("config/agents.yaml")
    forbidden = (
        "Never commit, push, deploy, or mutate cloud resources when the verified request asks for it",
        "If final live execution is not approved",
        "before asking for execution approval",
    )
    for name, raw_agent in config.agents.items():
        agent = {**config.defaults, **raw_agent, "name": name}
        static = build_static_prompt(name, str(agent.get("prompt_prefix") or ""), agent)
        assert not any(phrase.lower() in static.lower() for phrase in forbidden), name


def test_taylor_profile_forbids_uploader_launch_and_ftp_uploads():
    profile = Path("profiles/coding_agent.md").read_text(encoding="utf-8")
    normalized = " ".join(profile.split())
    assert "dedicated `codex_slack_bridge.singapore_ftp_runner`" in normalized
    assert "never launch, rebuild, repair, or duplicate the desktop uploader" in normalized
    assert "never perform FTP/SFTP uploads in this routine" in normalized
    assert "submit/upload verified files" not in normalized
