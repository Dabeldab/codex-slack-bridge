import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[1]
MODULE_PATH = ROOT / "scripts" / "reasoning_relay_workflow.py"
spec = importlib.util.spec_from_file_location("reasoning_relay_workflow", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(module)


def test_parse_response_comment():
    body = module.RESPONSE_MARKER + "\n```json\n" + ('{"protocol_version":1,"direction":"to_runtime","in_reply_to":"relay:request-0001","lane":"tickets_agent","kind":"final_response","text":"COMPLETED\\nDone"}') + "\n```"
    raw = module._parse_response(body)
    assert raw["kind"] == "final_response"


def test_parse_response_requires_protocol_marker():
    assert module._parse_response("hello") is None


def test_parse_response_rejects_unknown_kind():
    body = module.RESPONSE_MARKER + "\n```json\n" + ('{"protocol_version":1,"direction":"to_runtime","in_reply_to":"relay:request-0001","lane":"tickets_agent","kind":"shell"}') + "\n```"
    with pytest.raises(ValueError, match="kind"):
        module._parse_response(body)


def test_publish_skips_deleted_outbound_path(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(module, "_find_relay_pr", lambda repo, token: 123)
    monkeypatch.setattr(module, "_changed_paths", lambda before, after: ["relay/runtime/outbound/relay:request-9999.json"])
    assert module.publish_request_comments("owner/repo", "a", "b", "token") == 0


def test_work_task_instructions_are_request_marker_only():
    instructions = (ROOT / "relay" / "chatgpt" / "WORK_TASK_INSTRUCTIONS.md").read_text(encoding="utf-8")
    assert module.REQUEST_MARKER in instructions
    assert "Never scan for an older pending request as a fallback" in instructions
    assert "ignore response comments" in instructions.lower()
    assert "nova_relay_get_request(request_id)" in instructions
    assert "nova_relay_execute_read_tool" in instructions
    assert "nova_relay_submit_final_response(request_id, text)" in instructions
    assert "Do not post a response comment to GitHub" in instructions
    assert "Otherwise inspect the newest commit update" not in instructions


def test_reasoning_relay_workflow_filters_response_marker_and_allows_actor_variable():
    workflow = (ROOT / ".github" / "workflows" / "chatgpt-reasoning-relay.yml").read_text(encoding="utf-8")
    assert "contains(github.event.comment.body, '<!-- nova-reasoning-relay:v1:response -->')" in workflow
    assert "CHATGPT_RELAY_ALLOWED_ACTORS: ${{ vars.CHATGPT_RELAY_ALLOWED_ACTORS || github.repository_owner }}" in workflow
    assert '--allowed-actor "$CHATGPT_RELAY_ALLOWED_ACTORS"' in workflow
