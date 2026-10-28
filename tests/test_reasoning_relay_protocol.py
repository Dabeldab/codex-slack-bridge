import pytest

from codex_slack_bridge.reasoning_relay_protocol import RelayRequest, RelayResponse


def test_response_must_match_pending_request():
    request = RelayRequest.create(lane="tickets_agent", kind="reasoning_request", conversation_id="command-center:abc", job_id=42, payload={"trusted_instruction": "check ticket"}, message_id="relay:request-0001")
    response = RelayResponse.from_dict({"protocol_version": 1, "direction": "to_runtime", "in_reply_to": request.message_id, "lane": "tickets_agent", "kind": "final_response", "created_at": "2026-09-17T18:00:00Z", "text": "COMPLETED\nDone."}, expected_request=request)
    assert response.text.startswith("COMPLETED")


def test_cross_lane_response_is_rejected():
    request = RelayRequest.create(lane="billing_agent", kind="reasoning_request", conversation_id="command-center:abc", job_id=43, payload={}, message_id="relay:request-0002")
    with pytest.raises(ValueError, match="lane"):
        RelayResponse.from_dict({"protocol_version": 1, "direction": "to_runtime", "in_reply_to": request.message_id, "lane": "coding_agent", "kind": "final_response", "text": "COMPLETED\nNope."}, expected_request=request)
