from dataclasses import replace

import pytest

from codex_slack_bridge.reasoning_relay_claims import (
    attach_relay_authorization_claim,
    verify_relay_authorization_claim,
)
from codex_slack_bridge.reasoning_relay_protocol import RelayRequest


def _agent(tmp_path):
    key_path = tmp_path / "operator.key"
    key_path.write_bytes(b"k" * 64)
    return {"operator_message_signing_key_path": str(key_path)}


def _request():
    return RelayRequest.create(
        lane="tickets_agent",
        kind="reasoning_request",
        conversation_id="command_center:tickets_agent:interactive",
        job_id=123,
        payload={
            "trusted_instruction": "Read ticket 123.",
            "trusted_authority": {
                "kind": "operator",
                "surface": "command_center",
                "write_authorized": False,
            },
            "allowed_tool_servers": ["salesforce_support_ops", "local_workspace"],
        },
        message_id="tickets_agent:12345678",
    )


def test_runtime_claim_round_trip(tmp_path):
    agent = _agent(tmp_path)
    request = attach_relay_authorization_claim(_request(), agent=agent)

    verify_relay_authorization_claim(request, agent=agent)

    assert request.payload["runtime_claim"]["version"] == 1
    assert request.payload["runtime_claim"]["signature"].startswith("v1:")


def test_runtime_claim_rejects_write_authorization_tampering(tmp_path):
    agent = _agent(tmp_path)
    request = attach_relay_authorization_claim(_request(), agent=agent)
    payload = dict(request.payload)
    authority = dict(payload["trusted_authority"])
    authority["write_authorized"] = True
    payload["trusted_authority"] = authority
    tampered = replace(request, payload=payload)

    with pytest.raises(PermissionError, match="authorization claim is invalid"):
        verify_relay_authorization_claim(tampered, agent=agent)
