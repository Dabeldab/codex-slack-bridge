from pathlib import Path

import yaml

# AgentChat/direct_codex 2026-07-13T00:16:00-04:00
# AgentChat/coding_agent 2026-07-30T17:15:00Z: verify Slack recovery and acknowledged handoff continuation.
from codex_slack_bridge import app as slack_app_module
from codex_slack_bridge.agents import AgentRequest
from codex_slack_bridge.config import BridgeConfig, ChannelRoute
from codex_slack_bridge.slack_text import format_queued_steering_prompt, parse_steer_command


class FakeSlackApp:
    def __init__(self):
        self.commands = {}
        self.events = {}

    def command(self, name):
        def decorator(handler):
            self.commands[name] = handler
            return handler

        return decorator

    def event(self, name):
        def decorator(handler):
            self.events[name] = handler
            return handler

        return decorator


class FakeBridgeState:
    def __init__(self):
        self.started = []
        self.completed = []
        self.failed = []

    def mark_started(self, job_id, **_kwargs):
        self.started.append(job_id)
        return True

    def mark_completed(self, job_id, **_kwargs):
        self.completed.append(job_id)
        return True

    def mark_outcome(self, job_id, status, **_kwargs):
        if status == "completed":
            self.completed.append(job_id)
        elif status == "failed":
            self.failed.append((job_id, _kwargs.get("review_reason") or _kwargs.get("result_text") or ""))
        return True

    def mark_failed(self, job_id, error, **_kwargs):
        self.failed.append((job_id, error))
        return True

    def update_runtime_stage(self, *_args, **_kwargs):
        return True

    def heartbeat_job(self, *_args, **_kwargs):
        return True


class FakeClient:
    def __init__(self):
        self.messages = []

    def chat_postMessage(self, **kwargs):
        self.messages.append(kwargs)
        return {"ts": "posted"}


def test_parse_steer_command_accepts_btw_and_steer_aliases():
    assert parse_steer_command("/btw check the latest reply") == ("btw", "check the latest reply")
    assert parse_steer_command("/STEER: check the latest reply") == ("steer", "check the latest reply")
    assert parse_steer_command("normal message") == ("", "normal message")


def test_format_queued_steering_prompt_is_explicit_about_delivery_semantics():
    prompt = format_queued_steering_prompt("/steer focus on the failing tests")

    assert "Operator steering note (/steer): focus on the failing tests" in prompt
    assert "separate queued follow-up after any in-flight lane work" in prompt
    assert "did not inject it into an already in-flight turn" in prompt


def test_slack_steer_command_routes_to_the_agent_assigned_to_the_channel(monkeypatch):
    fake_app = FakeSlackApp()
    config = BridgeConfig(
        defaults={},
        channels={"C123": ChannelRoute(channel_id="C123", agent_name="coding_agent", listen="mention")},
        agents={"coding_agent": {"allowed_user_ids": ["U123"]}},
    )
    queued = []
    monkeypatch.setattr(slack_app_module, "_queue_request", lambda *args: queued.append(args))
    slack_app_module.register_handlers(fake_app, config)
    acknowledgements = []

    fake_app.commands["/steer"](
        lambda **kwargs: acknowledgements.append(kwargs),
        {
            "channel_id": "C123",
            "user_id": "U123",
            "text": "focus on the failing tests",
            "trigger_id": "trigger-1",
        },
        object(),
    )

    assert acknowledgements == [
        {
            "response_type": "ephemeral",
            "text": (
                "Accepted steering guidance for `coding_agent` as a separate queued follow-up. "
                "It does not interrupt an in-flight turn."
            ),
        }
    ]
    assert len(queued) == 1
    assert queued[0][1].agent_name == "coding_agent"
    assert queued[0][2]["event_id"] == "slash:/steer:trigger-1"
    assert queued[0][3]["text"] == "/steer focus on the failing tests"
    assert queued[0][3]["_force_top_level"] is True


def test_slack_manifest_registers_steer_and_commands_scope():
    manifest_path = Path(__file__).resolve().parents[1] / "slack-app-manifest.yaml"
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))

    assert any(item.get("command") == "/steer" for item in manifest["features"]["slash_commands"])
    assert any(item.get("command") == "/btw" for item in manifest["features"]["slash_commands"])
    assert "commands" in manifest["oauth_config"]["scopes"]["bot"]


def test_slack_btw_slash_command_is_a_registered_steer_alias(monkeypatch):
    fake_app = FakeSlackApp()
    config = BridgeConfig(
        defaults={},
        channels={"C123": ChannelRoute(channel_id="C123", agent_name="coding_agent", listen="mention")},
        agents={"coding_agent": {"allowed_user_ids": ["U123"]}},
    )
    queued = []
    monkeypatch.setattr(slack_app_module, "_queue_request", lambda *args: queued.append(args))
    slack_app_module.register_handlers(fake_app, config)

    fake_app.commands["/btw"](
        lambda **_kwargs: None,
        {
            "command": "/btw",
            "channel_id": "C123",
            "user_id": "U123",
            "text": "use the latest reply",
            "trigger_id": "trigger-btw",
        },
        object(),
    )

    assert queued[0][2]["event_id"] == "slash:/btw:trigger-btw"
    assert queued[0][3]["text"] == "/btw use the latest reply"


def test_slack_steering_bypasses_fast_responder_and_uses_main_lane(monkeypatch):
    state = FakeBridgeState()
    client = FakeClient()
    request = AgentRequest(
        text="Operator steering note (/steer): focus on the failing tests",
        channel_id="C123",
        user_id="U123",
        thread_ts="",
        job_id=42,
        surface="slack",
        conversation_id="C123:",
        is_steering=True,
    )
    config = BridgeConfig(
        defaults={"serialize_channel_runs": False, "reply_in_thread": True},
        channels={},
        agents={},
    )
    main_lane_calls = []
    monkeypatch.setattr(slack_app_module, "STATE", state)
    monkeypatch.setattr(slack_app_module, "_append_shared_chat_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(slack_app_module, "_prepare_agent_request", lambda *args, **kwargs: request)
    monkeypatch.setattr(
        slack_app_module,
        "try_fast_response",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("fast responder must not run")),
    )
    monkeypatch.setattr(
        slack_app_module,
        "run_agent_isolated",
        lambda *args, **kwargs: main_lane_calls.append(args) or "COMPLETED: main lane result",
    )
    monkeypatch.setattr(slack_app_module, "_store_interaction_memory", lambda *args, **kwargs: None)
    monkeypatch.setattr(slack_app_module, "_cleanup_recent_sandbox_junk", lambda *args, **kwargs: None)
    monkeypatch.setattr(slack_app_module, "_register_recent_sandbox_artifacts", lambda *args, **kwargs: None)

    slack_app_module._run_and_reply(config, "coding_agent", {}, request, client, 3900, None)

    assert len(main_lane_calls) == 1
    assert state.started == [42]
    assert state.completed == [42]
    assert state.failed == []
    assert client.messages[0]["text"].endswith("main lane result")
    assert "thread_ts" not in client.messages[0]


def test_slack_result_handoff_is_consumed_once_and_reclassified(monkeypatch):
    request = AgentRequest(
        text="Pass the verified repair to Taylor.",
        channel_id="C123",
        user_id="U123",
        thread_ts="",
        job_id=4360,
        surface="slack",
        conversation_id="C123:",
        authority_kind="operator",
    )
    calls = []

    def fake_command_center(_config, method, path, payload):
        calls.append((method, path, payload))
        return {
            "ok": True,
            "accepted": True,
            "job_id": "handoff-queued-1",
            "status": "queued",
            "handoffAcknowledged": True,
            "result": (
                "COMPLETED_WITH_ISSUES\n"
                "The receiving lane acknowledged handoff job handoff-queued-1. "
                "The requested business work is not complete until the target job finishes."
            ),
        }

    monkeypatch.setattr(slack_app_module, "_command_center_json", fake_command_center)
    result, outcome = slack_app_module._route_slack_result_handoff(
        BridgeConfig(defaults={}, channels={}, agents={}),
        "direct_codex",
        request,
        (
            "BLOCKED\nTaylor owns the guarded writer.\n"
            'TAYLOR_HANDOFF_REQUEST: {"targetAgent":"coding_agent",'
            '"requestedTask":"Execute the authorized repair."}'
        ),
        slack_app_module._classify_runtime_result("BLOCKED\nTaylor owns the guarded writer."),
    )

    assert result.startswith("COMPLETED_WITH_ISSUES")
    assert outcome.normalized_status == "completed_with_issues"
    assert calls == [
        (
            "POST",
            "/agent-handoff/slack",
            {
                "sourceAgent": "direct_codex",
                "sourceJobId": "slack:4360",
                "sourceBridgeJobId": 4360,
                "originRequest": "Pass the verified repair to Taylor.",
                "sourceResult": (
                    "BLOCKED\nTaylor owns the guarded writer.\n"
                    'TAYLOR_HANDOFF_REQUEST: {"targetAgent":"coding_agent",'
                    '"requestedTask":"Execute the authorized repair."}'
                ),
                "authorityKind": "operator",
            },
        )
    ]


def test_slack_result_handoff_failure_strips_marker_and_fails_closed(monkeypatch):
    request = AgentRequest(
        text="Pass this to Taylor.",
        channel_id="C123",
        user_id="U123",
        thread_ts="",
        job_id=4360,
        surface="slack",
        conversation_id="C123:",
        authority_kind="operator",
    )
    monkeypatch.setattr(
        slack_app_module,
        "_command_center_json",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("router unavailable")),
    )

    result, outcome = slack_app_module._route_slack_result_handoff(
        BridgeConfig(defaults={}, channels={}, agents={}),
        "direct_codex",
        request,
        (
            "BLOCKED\nTaylor owns the guarded writer.\n"
            'TAYLOR_HANDOFF_REQUEST: {"targetAgent":"coding_agent",'
            '"requestedTask":"Execute the authorized repair."}'
        ),
        slack_app_module._classify_runtime_result("BLOCKED\nTaylor owns the guarded writer."),
    )

    assert "TAYLOR_HANDOFF_REQUEST" not in result
    assert "not durably acknowledged after bounded retries: router unavailable" in result
    assert outcome.normalized_status == "failed"
