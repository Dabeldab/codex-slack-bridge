from __future__ import annotations

import json
import threading
from http.server import ThreadingHTTPServer
from types import SimpleNamespace

import pytest

from codex_slack_bridge import app as slack_app
from codex_slack_bridge.command_center_server import (
    CommandCenterRuntime,
    _dispatch_ticket_close_request,
    _direct_location_region_update_request,
    _direct_ticket_close_request,
    _singapore_chat_delivery_text,
    make_handler,
)
from codex_slack_bridge.config import BridgeConfig, ChannelRoute
from codex_slack_bridge.singapore_routing import (
    SingaporeIntent,
    classify_singapore_intent,
    format_singapore_chat_outcome,
    is_singapore_notification_policy_request,
    is_singapore_run_request,
)
from codex_slack_bridge.state import BridgeState


def test_run_request_matcher_handles_typo_without_matching_discussion():
    assert is_singapore_run_request("please run the singpore routine now") is True
    assert is_singapore_run_request("retry singpaore ftp") is True
    assert is_singapore_run_request("process the Singapore integration emails") is True
    assert is_singapore_run_request("send singapore to taylor") is True
    assert is_singapore_run_request("send the Singapore routine to Taylor") is True
    assert is_singapore_run_request("why did the Singapore routine fail?") is False
    assert is_singapore_run_request("run the FTP report") is False
    assert is_singapore_run_request("Reactivate the retired Singapore interface") is True
    assert is_singapore_run_request("Why was the Singapore interface reactivated yesterday?") is False


def test_exact_typed_ticket_close_routes_to_deterministic_alex_fast_path():
    runtime = object.__new__(CommandCenterRuntime)
    runtime.config = SimpleNamespace(agents={"tickets_agent": {}})
    runtime._resolve_agent_chat_attachments = lambda _payload: []
    captured = []
    runtime._submit_ticket_close_fast_job = lambda **kwargs: captured.append(kwargs) or {
        "accepted": True,
        "job_id": "close-job",
    }
    runtime.submit_prompt = lambda **_kwargs: pytest.fail("generic agent was queued")

    result = runtime.submit_direct_chat(
        {
            "agent": "alex",
            "message": "close ticket 347314: Customer confirmed the issue is resolved",
            "idempotencyKey": "close-chat-347314",
        }
    )

    assert result["routed"] == "salesforce_ticket_close_fast_path"
    assert captured[0]["request"] == {
        "ticketNumber": "347314",
        "resolutionNote": "Customer confirmed the issue is resolved",
        "idempotencyKey": "close-chat-347314",
    }


def test_exact_location_region_change_routes_to_taylor_deterministic_fast_path():
    runtime = object.__new__(CommandCenterRuntime)
    runtime.config = SimpleNamespace(
        agents={"direct_codex": {}, "coding_agent": {}},
        defaults={},
    )
    runtime.resolve_agent = lambda _payload: "direct_codex"
    runtime._resolve_agent_chat_attachments = lambda _payload: []
    captured = []
    runtime._submit_location_region_fast_job = (
        lambda **kwargs: captured.append(kwargs)
        or {"accepted": True, "job_id": "region-job"}
    )
    runtime.submit_prompt = lambda **_kwargs: pytest.fail(
        "generic agent was queued"
    )

    result = runtime.submit_direct_chat(
        {
            "agent": "rory",
            "message": (
                "In database pos_shoe_mgk_brandon, begin one transaction; "
                "update dbo.Locations so RegionId = 6 where LocationId = 41; "
                "commit; make no other changes."
            ),
            "idempotencyKey": "bridge-job:6226",
        }
    )

    assert result["routed"] == "nova_location_region_fast_path"
    assert captured[0]["request"] == {
        "companyUsername": "shoe_mgk_brandon",
        "locationId": 41,
        "regionId": 6,
        "idempotencyKey": "bridge-job:6226",
    }


@pytest.mark.parametrize(
    "message",
    (
        "Why did the RegionId update for LocationId 41 in database POS_Test fail?",
        "Do not update dbo.Locations RegionId 6 for LocationId 41 in database POS_Test.",
        "Preview setting RegionId 6 for LocationId 41 in database POS_Test.",
        "Update RegionId 6 in database POS_Test.",
        (
            "Update dbo.Locations RegionId 6 for LocationId 41 in database "
            "POS_Test and database POS_Other."
        ),
    ),
)
def test_location_region_fast_path_rejects_discussion_negation_and_ambiguity(
    message,
):
    assert _direct_location_region_update_request(message) is None


def test_slack_exact_location_region_change_uses_runtime_broker_before_model(
    monkeypatch,
):
    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["payload"] = json.loads(kwargs["input"])
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps(
                {
                    "ok": True,
                    "status": "completed",
                    "accessMode": "fixed_location_region_update",
                    "companyUsername": "shoe_mgk_brandon",
                    "locationId": 41,
                    "regionId": 6,
                    "readback": {"locationId": 41, "regionId": 6},
                    "postCommitReadbackVerified": True,
                    "arbitrarySqlAccepted": False,
                    "noOp": False,
                }
            ),
        )

    monkeypatch.setattr(slack_app.subprocess, "run", fake_run)
    result = slack_app._try_deterministic_location_region_update(
        SimpleNamespace(
            defaults={
                "nova_location_region_executor": "/opt/nova/bin/run-nova-location-region"
            }
        ),
        SimpleNamespace(
            job_id=6226,
            authority_kind="operator",
            is_steering=False,
            slack_event=None,
            task_text=(
                "In database pos_shoe_mgk_brandon update dbo.Locations "
                "set RegionId = 6 where LocationId = 41."
            ),
            text="",
        ),
    )

    assert result.startswith("COMPLETED\n")
    assert "Taylor's typed broker committed" in result
    assert captured["payload"] == {
        "action": "update_location_region",
        "companyUsername": "shoe_mgk_brandon",
        "locationId": 41,
        "regionId": 6,
        "idempotencyKey": "bridge-job:6226",
    }
    assert captured["command"][-1] == "/opt/nova/bin/run-nova-location-region"


def test_ticket_card_close_routes_to_deterministic_alex_fast_path():
    runtime = object.__new__(CommandCenterRuntime)
    runtime.config = SimpleNamespace(agents={"tickets_agent": {}})
    runtime.resolve_agent = lambda _payload: "tickets_agent"
    captured = []
    runtime._submit_ticket_close_fast_job = lambda **kwargs: captured.append(kwargs) or {
        "accepted": True,
        "job_id": "close-job",
    }
    runtime.submit_prompt = lambda **_kwargs: pytest.fail("generic agent was queued")

    result = runtime.submit(
        {
            "agentName": "tickets_agent",
            "ticketNumber": "347350",
            "instruction": "The account work is complete. Please close the ticket.",
            "idempotencyKey": "dispatch-347350-close",
        }
    )

    assert result["routed"] == "salesforce_ticket_close_fast_path"
    assert captured[0]["source_type"] == "dispatch"
    assert captured[0]["request"] == {
        "ticketNumber": "347350",
        "resolutionNote": "Issue resolved. No further follow-up is required.",
        "idempotencyKey": "dispatch-347350-close",
    }


@pytest.mark.parametrize(
    "message",
    (
        "do not close ticket 347314",
        "why did closing ticket 347314 fail?",
        "can you close ticket 347314?",
        "close the tickets",
    ),
)
def test_ticket_close_fast_path_rejects_negation_discussion_and_ambiguity(message):
    assert _direct_ticket_close_request(message) is None


@pytest.mark.parametrize(
    ("message", "ticket_number"),
    (
        ("close it 347314", "347314"),
        ("this ticket should be closed 347185", "347185"),
        ("ticket 347316 needs to be closed", "347316"),
        ("This was completed on 7/22. Please close ticket 346765.", "346765"),
        (
            "Close ticket 347185 now. This is the safe retry of the operator direct close instruction.",
            "347185",
        ),
    ),
)
def test_common_direct_close_wording_uses_deterministic_fast_path(message, ticket_number):
    request = _direct_ticket_close_request(message)

    assert request == {
        "ticketNumber": ticket_number,
        "resolutionNote": "Issue resolved. No further follow-up is required.",
    }


@pytest.mark.parametrize(
    "instruction",
    (
        "this was completed on 7/22. please close the ticket",
        "The account is closed and the customer was emailed. Please close the ticket.",
        "close it",
        "this ticket should be closed",
        "this ticket should be closed 347350",
    ),
)
def test_ticket_card_close_instruction_uses_selected_ticket(instruction):
    request = _dispatch_ticket_close_request(
        {
            "ticketNumber": "347350",
            "instruction": instruction,
        }
    )

    assert request == {
        "ticketNumber": "347350",
        "resolutionNote": "Issue resolved. No further follow-up is required.",
    }


@pytest.mark.parametrize(
    "instruction",
    (
        "do not close the ticket",
        "investigate why this ticket is open",
        "if the customer confirms, close the ticket",
        "review the ticket before closing it",
        "can you close the ticket?",
        "close ticket 347351",
    ),
)
def test_ticket_card_close_instruction_rejects_negation_conditions_and_ambiguity(instruction):
    assert (
        _dispatch_ticket_close_request(
            {
                "ticketNumber": "347350",
                "instruction": instruction,
            }
        )
        is None
    )


def test_intent_classifier_routes_only_new_interfaces_to_ticket_intake():
    assert (
        classify_singapore_intent("Please start a new Singapore integration for this customer")
        is SingaporeIntent.NEW_INTERFACE_TICKET
    )
    assert (
        classify_singapore_intent("Build a new Singapore interface for the new location")
        is SingaporeIntent.NEW_INTERFACE_TICKET
    )
    assert (
        classify_singapore_intent("Please add Singapore integration for Acme")
        is SingaporeIntent.NEW_INTERFACE_TICKET
    )
    assert (
        classify_singapore_intent(
            "Build a brand-new Singapore interface even though authentication is failing"
        )
        is SingaporeIntent.NEW_INTERFACE_TICKET
    )
    assert (
        classify_singapore_intent(
            "A brand-new Singapore integration is required because the upload is failing"
        )
        is SingaporeIntent.NEW_INTERFACE_TICKET
    )
    assert is_singapore_run_request("Please start a new Singapore integration") is False


def test_intent_classifier_keeps_existing_interface_operations_out_of_new_ticket_route():
    routine_requests = (
        "Singapore authentication failed for the existing interface",
        "Check the Singapore upload status",
        "Retry Singapore upload remediation",
        "Apply a new password to the Singapore integration",
        "New Singapore integration authentication issue",
        "New Singapore interface upload failure",
        "Check the new Singapore integration status",
        "Why did the Singapore routine fail?",
    )
    for request in routine_requests:
        assert classify_singapore_intent(request) is SingaporeIntent.ROUTINE_OPERATION


def test_intent_classifier_separates_reactivation_and_non_singapore_work():
    assert (
        classify_singapore_intent(
            "Reactivate the retired Singapore interface even though authentication failed"
        )
        is SingaporeIntent.REACTIVATION
    )
    assert (
        classify_singapore_intent("Start the Singapore integration again")
        is SingaporeIntent.REACTIVATION
    )
    assert (
        classify_singapore_intent("Singapore reactivation is requested for the retired interface")
        is SingaporeIntent.REACTIVATION
    )
    assert (
        classify_singapore_intent("Why was the Singapore interface reactivated yesterday?")
        is SingaporeIntent.ROUTINE_OPERATION
    )
    assert classify_singapore_intent("Create a new Malaysia interface") is SingaporeIntent.NOT_SINGAPORE


def test_chat_formatter_suppresses_verified_retired_only_outcomes():
    cache = {
        "status": "partial",
        "summary": "password=should-never-appear",
        "blockers": ["legacy auth blocker password=should-never-appear"],
        "issues": ["legacy upload failure token=should-never-appear"],
        "upload": {
            "status": "completed_with_issues",
            "failedMessageCount": 1,
            "details": [
                {
                    "result": "retired_machine_pending_handoff",
                    "retiredServer": True,
                    "retirementVerified": True,
                    "machineId": "sensitive-identifier",
                    "error": "raw failure text",
                }
            ],
        },
    }

    assert format_singapore_chat_outcome(cache) == ""
    assert format_singapore_chat_outcome(
        {
            "status": "blocked",
            "blockers": ["legacy retired-interface blocker"],
            "issues": ["legacy retired-interface issue"],
            "upload": {"details": []},
            "configChanges": {"retiredIgnoredCount": 1},
        }
    ) == ""


def test_chat_formatter_suppresses_no_work_outcomes():
    assert format_singapore_chat_outcome({"status": "ok", "upload": {"details": []}}) == ""


def test_chat_formatter_uses_only_allowlisted_counts_and_never_raw_failure_text():
    cache = {
        "status": "partial",
        "summary": "Authentication failed for host secret.example using password=hunter2",
        "blockers": ["Traceback: token=super-secret"],
        "upload": {
            "uploadedCount": 2,
            "skippedCount": 1,
            "failedMessageCount": 2,
            "authBlockedServerCount": 1,
            "details": [
                {
                    "result": "retired_machine_pending_handoff",
                    "retiredServer": True,
                    "retirementVerified": True,
                },
                {
                    "result": "server_auth_blocked",
                    "retiredServer": False,
                    "reason": "username=admin password=hunter2",
                },
            ],
        },
    }

    message = format_singapore_chat_outcome(cache)

    assert message == "SINGAPORE | PARTIAL | uploaded=2; already_present=1; active_failures=1"
    assert "secret" not in message.lower()
    assert "password" not in message.lower()
    assert "traceback" not in message.lower()


def test_chat_formatter_reports_success_and_sanitizes_blocked_runtime_failures():
    assert format_singapore_chat_outcome(
        {"status": "ok", "upload": {"uploadedCount": 3, "skippedCount": 2, "details": []}}
    ) == "SINGAPORE | SUCCESS | uploaded=3; already_present=2"

    blocked = format_singapore_chat_outcome(
        {
            "status": "blocked",
            "summary": "C:/private/servers.json failed with access_token=abc",
            "error": "raw stack trace",
            "upload": {"details": []},
        }
    )
    assert blocked == "SINGAPORE | FAILED | service_issue=1"
    assert "servers.json" not in blocked
    assert "token" not in blocked.lower()


def test_chat_formatter_reports_submission_and_zero_sales_counts_without_identifiers():
    message = format_singapore_chat_outcome(
        {
            "status": "partial",
            "nonsubmissions": [{"machineId": "secret-1"}, {"machineId": "secret-2"}],
            "unconfiguredNonsubmissions": [{"machineId": "secret-3"}],
            "ignored": {"zeroSales": 2},
            "issues": ["unconfigured"],
            "upload": {"details": []},
        }
    )

    assert message == (
        "SINGAPORE | PARTIAL | nonsubmissions=2; unconfigured=1; "
        "zero_sales_read=2; service_issue=1"
    )
    assert "secret" not in message


def test_notification_policy_matcher_handles_direct_and_thread_continuation():
    assert is_singapore_notification_policy_request(
        "No need to send notifications on the Singapore failures. Mark them read."
    ) is True
    assert is_singapore_notification_policy_request(
        "Please turn this off",
        "Earlier operator message: stop Singapore failure notifications",
    ) is True
    assert is_singapore_notification_policy_request("Why was the Singapore upload rejected?") is False


def test_agent_chat_routes_run_request_to_fast_path():
    runtime = object.__new__(CommandCenterRuntime)
    runtime.config = SimpleNamespace(agents={"tickets_agent": {}})
    runtime._lock = threading.Lock()
    runtime._jobs = {}
    captured: list[dict[str, object]] = []
    chat_events: list[tuple[str, str, bool]] = []

    def fake_submit_singapore_ftp_scan(
        idempotency_key="",
        singapore_request=None,
        direct_chat_request=False,
    ):
        captured.append(
            {
                "idempotencyKey": idempotency_key,
                "singaporeRequest": singapore_request,
                "directChatRequest": direct_chat_request,
            }
        )
        runtime._jobs["fast-job"] = {
            "id": "fast-job",
            "bridgeJobId": 7,
            "payload": {"directChatRequest": direct_chat_request},
        }
        return {"accepted": True, "job_id": "fast-job", "bridge_job_id": 7}

    runtime.submit_singapore_ftp_scan = fake_submit_singapore_ftp_scan
    runtime._write_job = lambda _record: None
    runtime._append_chat = (
        lambda _agent, role, text, _job, _bridge, force=False: chat_events.append((role, text, force))
    )
    runtime.submit_prompt = lambda **_kwargs: (_ for _ in ()).throw(AssertionError("generic agent was queued"))

    response = runtime.submit_direct_chat(
        {
            "agent": "alex",
            "message": "please run the singpore routine now",
            "idempotencyKey": "chat-turn-1",
        }
    )

    assert response["job_id"] == "fast-job"
    assert response["routed"] == "singapore_fast_path"
    assert captured == [
        {
            "idempotencyKey": "chat-turn-1",
            "singaporeRequest": None,
            "directChatRequest": True,
        }
    ]
    assert chat_events == [
        ("user", "Run the Singapore background service.", True),
        ("acknowledgement", "Got it — I received your message and I’m getting started.", True),
    ]


def test_agent_chat_routes_reactivation_to_deterministic_fast_path():
    runtime = object.__new__(CommandCenterRuntime)
    runtime.config = SimpleNamespace(agents={"tickets_agent": {}})
    runtime._lock = threading.Lock()
    runtime._jobs = {}
    captured: list[dict[str, object]] = []
    chat_events: list[str] = []

    def fake_submit_singapore_ftp_scan(
        idempotency_key="",
        singapore_request=None,
        direct_chat_request=False,
    ):
        captured.append(
            {
                "idempotencyKey": idempotency_key,
                "singaporeRequest": singapore_request,
                "directChatRequest": direct_chat_request,
            }
        )
        runtime._jobs["reactivation-job"] = {
            "id": "reactivation-job",
            "bridgeJobId": 8,
            "payload": {"directChatRequest": direct_chat_request},
        }
        return {"accepted": True, "job_id": "reactivation-job", "bridge_job_id": 8}

    runtime.submit_singapore_ftp_scan = fake_submit_singapore_ftp_scan
    runtime._write_job = lambda _record: None
    runtime._append_chat = (
        lambda _agent, _role, text, _job, _bridge, **_kwargs: chat_events.append(text)
    )
    runtime.submit_prompt = lambda **_kwargs: (_ for _ in ()).throw(AssertionError("generic agent was queued"))

    response = runtime.submit_direct_chat(
        {
            "agent": "alex",
            "message": (
                "Reactivate the retired Singapore interface for machine 5000393; "
                "password=hunter2 token=raw-secret"
            ),
            "idempotencyKey": "chat-reactivation-1",
        }
    )

    assert response["job_id"] == "reactivation-job"
    assert response["routed"] == "singapore_fast_path"
    assert captured == [
        {
            "idempotencyKey": "chat-reactivation-1",
            "singaporeRequest": {
                "schemaVersion": 1,
                "requestKind": "reactivation",
                "action": "reactivate",
                "targetType": "machine_id",
                "machineId": "5000393",
            },
            "directChatRequest": True,
        }
    ]
    assert "hunter2" not in repr(captured)
    assert "raw-secret" not in repr(captured)
    assert "hunter2" not in repr(chat_events)
    assert "raw-secret" not in repr(chat_events)


def test_direct_singapore_chat_always_receives_terminal_result_while_unchanged_background_scan_stays_quiet():
    cache = {"status": "ok", "upload": {"uploadedCount": 0, "failedMessageCount": 0}}

    assert _singapore_chat_delivery_text(
        result="SINGAPORE | SUCCESS | background service completed",
        chat_outcome="",
        cache=cache,
        previous_cache=dict(cache),
        direct_chat_requested=True,
    ) == "SINGAPORE | SUCCESS | background service completed"
    assert _singapore_chat_delivery_text(
        result="SINGAPORE | SUCCESS | background service completed",
        chat_outcome="",
        cache=cache,
        previous_cache=dict(cache),
        direct_chat_requested=False,
    ) == ""


def test_agent_chat_reactivation_fails_closed_without_one_labeled_target():
    runtime = object.__new__(CommandCenterRuntime)
    runtime.config = SimpleNamespace(agents={"tickets_agent": {}})
    runtime.submit_singapore_ftp_scan = lambda **_kwargs: pytest.fail("scan was queued")

    with pytest.raises(ValueError, match="one exact labeled 5-10 digit machine ID"):
        runtime.submit_direct_chat(
            {
                "agent": "alex",
                "message": "Reactivate the retired Singapore interface",
                "idempotencyKey": "chat-reactivation-missing-target",
            }
        )


@pytest.mark.parametrize(
    ("event_id", "text", "reactivation_machine_id"),
    [
        ("slack-run-event-1", "run singpore routine", None),
        (
            "slack-reactivation-event-1",
            "Reactivate the retired Singapore interface for machine 5000393; password=hunter2 token=raw-secret",
            "5000393",
        ),
    ],
)
def test_slack_operation_and_reactivation_post_to_command_center_without_general_job(
    tmp_path,
    monkeypatch,
    event_id,
    text,
    reactivation_machine_id,
):
    state = BridgeState(str(tmp_path / "bridge.sqlite3"))
    config = BridgeConfig(
        defaults={"allowed_user_ids": ["operator"], "progress_message_enabled": False},
        channels={},
        agents={"tickets_agent": {"allowed_user_ids": ["operator"]}},
    )
    route = ChannelRoute(channel_id="support", agent_name="tickets_agent", listen="all_messages")
    calls = []

    class Client:
        def __init__(self):
            self.messages = []

        def chat_postMessage(self, **kwargs):
            self.messages.append(kwargs)
            return {"ts": "reply"}

    client = Client()
    monkeypatch.setattr(slack_app, "STATE", state)
    monkeypatch.setattr(slack_app, "EXECUTOR", object())
    monkeypatch.setattr(
        slack_app,
        "_command_center_json",
        lambda config, method, path, payload=None: calls.append((method, path, payload))
        or {"ok": True, "accepted": True, "job_id": "fast-job"},
    )

    slack_app._queue_request(
        config,
        route,
        {"event_id": event_id},
        {"channel": "support", "user": "operator", "ts": "1.0", "text": text},
        client,
    )

    assert calls[0][0:2] == ("POST", "/ops/singapore-ftp/scan")
    assert calls[0][2]["idempotencyKey"] == f"ops-singapore-ftp-slack:{event_id}"
    if reactivation_machine_id:
        assert calls[0][2]["singaporeRequest"] == {
            "schemaVersion": 1,
            "requestKind": "reactivation",
            "action": "reactivate",
            "targetType": "machine_id",
            "machineId": reactivation_machine_id,
        }
        serialized_payload = repr(calls[0][2]).lower()
        assert "hunter2" not in serialized_payload
        assert "raw-secret" not in serialized_payload
        assert "password" not in serialized_payload
        assert "token" not in serialized_payload
    else:
        assert "singaporeRequest" not in calls[0][2]
    assert state.list_jobs(limit=10) == []
    assert "Queued the Singapore routine directly" in client.messages[0]["text"]


def test_slack_reactivation_fails_closed_without_one_labeled_machine_id(tmp_path, monkeypatch):
    state = BridgeState(str(tmp_path / "bridge.sqlite3"))
    config = BridgeConfig(
        defaults={"allowed_user_ids": ["operator"], "progress_message_enabled": False},
        channels={},
        agents={"tickets_agent": {"allowed_user_ids": ["operator"]}},
    )
    route = ChannelRoute(channel_id="support", agent_name="tickets_agent", listen="all_messages")

    class Client:
        def __init__(self):
            self.messages = []

        def chat_postMessage(self, **kwargs):
            self.messages.append(kwargs)
            return {"ts": "reply"}

    client = Client()
    monkeypatch.setattr(slack_app, "STATE", state)
    monkeypatch.setattr(slack_app, "EXECUTOR", object())
    monkeypatch.setattr(
        slack_app,
        "_command_center_json",
        lambda *_args, **_kwargs: pytest.fail("ambiguous reactivation reached the server"),
    )

    slack_app._queue_request(
        config,
        route,
        {"event_id": "slack-reactivation-missing-target"},
        {
            "channel": "support",
            "user": "operator",
            "ts": "1.5",
            "text": "Reactivate the retired Singapore interface",
        },
        client,
    )

    assert state.list_jobs(limit=10) == []
    assert "was not queued" in client.messages[0]["text"]
    assert "exact 5-10 digit machine ID" in client.messages[0]["text"]


def test_reactivation_metadata_requires_one_explicit_machine_target():
    assert slack_app._singapore_reactivation_metadata(
        "Please reactivate Singapore server key 5000393"
    ) == {
        "schemaVersion": 1,
        "requestKind": "reactivation",
        "action": "reactivate",
        "targetType": "machine_id",
        "machineId": "5000393",
    }
    assert slack_app._singapore_reactivation_metadata(
        "Reactivate the retired Singapore interface"
    ) is None
    assert slack_app._singapore_reactivation_metadata(
        "Reactivate Singapore machine 5000393 and machine 6000123"
    ) is None
    assert slack_app._singapore_reactivation_metadata(
        "Run Singapore for machine 5000393"
    ) is None


def test_slack_singapore_queue_failure_log_is_metadata_only(tmp_path, monkeypatch, caplog):
    state = BridgeState(str(tmp_path / "bridge.sqlite3"))
    config = BridgeConfig(
        defaults={"allowed_user_ids": ["operator"], "progress_message_enabled": False},
        channels={},
        agents={"coding_agent": {"allowed_user_ids": ["operator"]}},
    )
    route = ChannelRoute(channel_id="engineering", agent_name="coding_agent", listen="all_messages")

    class Client:
        def __init__(self):
            self.messages = []

        def chat_postMessage(self, **kwargs):
            self.messages.append(kwargs)
            return {"ts": "reply"}

    def fail_with_sensitive_detail(*_args, **_kwargs):
        raise RuntimeError("token=raw-secret C:/private/state/servers.json")

    client = Client()
    monkeypatch.setattr(slack_app, "STATE", state)
    monkeypatch.setattr(slack_app, "EXECUTOR", object())
    monkeypatch.setattr(slack_app, "_command_center_json", fail_with_sensitive_detail)

    with caplog.at_level("WARNING", logger=slack_app.LOGGER.name):
        slack_app._queue_request(
            config,
            route,
            {"event_id": "slack-failure-1"},
            {"channel": "engineering", "user": "operator", "ts": "3.0", "text": "run singapore routine"},
            client,
        )

    assert "Singapore request could not be routed through the deterministic fast path" in caplog.text
    assert "raw-secret" not in caplog.text
    assert "servers.json" not in caplog.text
    assert "raw-secret" not in client.messages[0]["text"]


def test_slack_notification_policy_request_does_not_start_source_writer(tmp_path, monkeypatch):
    state = BridgeState(str(tmp_path / "bridge.sqlite3"))
    config = BridgeConfig(
        defaults={"allowed_user_ids": ["operator"], "progress_message_enabled": False},
        channels={},
        agents={"coding_agent": {"allowed_user_ids": ["operator"]}},
    )
    route = ChannelRoute(channel_id="engineering", agent_name="coding_agent", listen="all_messages")

    class Client:
        def __init__(self):
            self.messages = []

        def chat_postMessage(self, **kwargs):
            self.messages.append(kwargs)
            return {"ts": "reply"}

    client = Client()
    monkeypatch.setattr(slack_app, "STATE", state)
    monkeypatch.setattr(slack_app, "EXECUTOR", object())

    slack_app._queue_request(
        config,
        route,
        {"event_id": "policy-event-1"},
        {
            "channel": "engineering",
            "user": "operator",
            "ts": "2.0",
            "text": "No need to send notifications on the Singapore failures. Mark them read.",
        },
        client,
    )

    assert state.list_jobs(limit=10) == []
    reply = client.messages[0]["text"]
    assert "never create Salesforce tickets or Needs Review packets" in reply
    assert "Verified retired interfaces stay silent" in reply
    assert "only an explicit brand-new integration/interface request may create a ticket" in reply


def test_singapore_scan_http_response_is_accepted_by_slack_client():
    class Runtime:
        def __init__(self) -> None:
            self.keys: list[str] = []

        def submit_singapore_ftp_scan(self, idempotency_key: str = "") -> dict[str, object]:
            self.keys.append(idempotency_key)
            return {"accepted": True, "job_id": "fast-job"}

    runtime = Runtime()
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(runtime))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        config = BridgeConfig(
            defaults={"command_center_url": f"http://127.0.0.1:{server.server_port}"},
            channels={},
            agents={},
        )
        response = slack_app._command_center_json(
            config,
            "POST",
            "/ops/singapore-ftp/scan",
            {"idempotencyKey": "slack-event-2"},
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert response == {"accepted": True, "job_id": "fast-job", "ok": True}
    assert runtime.keys == ["slack-event-2"]
