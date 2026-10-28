from __future__ import annotations

import json
import subprocess

import pytest

from codex_slack_bridge.reasoning_relay_broker_transport import BrokeredGitHubReasoningRelayTransport
from codex_slack_bridge.reasoning_relay_protocol import RelayRequest


class Completed:
    def __init__(self, payload, returncode=0, stderr=b""):
        self.returncode = returncode
        self.stdout = (json.dumps(payload) + "\n").encode()
        self.stderr = stderr


def test_brokered_transport_publish_does_not_need_github_credentials(monkeypatch):
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, json.loads(kwargs["input"].decode()), kwargs["timeout"]))
        return Completed({"ok": True, "path": "relay/runtime/outbound/example.json"})

    monkeypatch.setattr("subprocess.run", fake_run)
    transport = BrokeredGitHubReasoningRelayTransport(["relay-broker"])
    request = RelayRequest.create(
        lane="tickets_agent",
        kind="reasoning_request",
        conversation_id="conversation",
        job_id=1,
        payload={"hello": "world"},
        message_id="relay:12345678",
    )
    assert transport.publish(request).endswith("example.json")
    assert calls[0][0] == ["relay-broker"]
    assert calls[0][1]["action"] == "publish"
    assert calls[0][1]["request"]["message_id"] == request.message_id
    assert calls[0][2] == 150.0


def test_brokered_transport_health_uses_short_preflight_timeout(monkeypatch):
    seen = {}

    def fake_run(command, **kwargs):
        seen["command"] = command
        seen["timeout"] = kwargs["timeout"]
        return Completed(
            {
                "ok": True,
                "health": {
                    "ok": True,
                    "repository": "dariusmakesstuff/codex-slack-bridge",
                    "branch": "reasoning-relay-bus",
                    "branchExists": True,
                },
            }
        )

    monkeypatch.setattr("subprocess.run", fake_run)
    transport = BrokeredGitHubReasoningRelayTransport(["relay-broker"])
    health = transport.health()
    assert health["ok"] is True
    assert seen["command"] == ["relay-broker"]
    assert seen["timeout"] == 120.0


def test_brokered_transport_timeout_identifies_action(monkeypatch):
    def fake_run(command, **kwargs):
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])

    monkeypatch.setattr("subprocess.run", fake_run)
    transport = BrokeredGitHubReasoningRelayTransport(["relay-broker"])
    with pytest.raises(RuntimeError, match=r"action 'health' timed out after 120\.0 seconds"):
        transport.health()


def test_brokered_transport_fails_closed_on_broker_error(monkeypatch):
    monkeypatch.setattr(
        "subprocess.run",
        lambda *args, **kwargs: Completed({"ok": False, "error": "denied"}, returncode=1),
    )
    transport = BrokeredGitHubReasoningRelayTransport(["relay-broker"])
    with pytest.raises(RuntimeError, match="denied"):
        transport.health()



def test_brokered_transport_cleanup_allows_github_round_trips(monkeypatch):
    seen = {}

    def fake_run(command, **kwargs):
        seen["timeout"] = kwargs["timeout"]
        return Completed({"ok": True})

    monkeypatch.setattr("subprocess.run", fake_run)
    transport = BrokeredGitHubReasoningRelayTransport(["relay-broker"])
    request = RelayRequest.create(
        lane="tickets_agent",
        kind="reasoning_request",
        conversation_id="conversation",
        job_id=1,
        payload={"hello": "world"},
        message_id="relay:cleanup123",
    )
    transport.cleanup(request)
    assert seen["timeout"] == 150.0
