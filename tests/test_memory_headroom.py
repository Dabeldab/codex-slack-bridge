import json
import time
from pathlib import Path

from codex_slack_bridge import desktop_memory_json, shared_artifacts, shared_chat
from codex_slack_bridge.config import load_config
from codex_slack_bridge.memory import MemoryStore


def test_general_lane_has_adaptive_memory_and_raw_escape_hatch():
    config = load_config("config/agents.yaml")
    general = {**config.defaults, **config.agents["direct_codex"]}
    raw = {**config.defaults, **config.agents["raw_codex"]}

    assert config.channels["C0BFLRN96DP"].agent_name == "direct_codex"
    assert general["provider"] == "codex_cli"
    assert general.get("direct_codex_raw_prompt") is not True
    assert general["effort"] == "xhigh"
    assert general["effort_autoscale"] is True
    assert general["memory_top_k"] == 4
    assert general["subagents_mode"] == "manual"
    assert general["max_subagents"] == 0
    assert raw["provider"] == "codex_cli_direct"
    assert raw["direct_codex_raw_prompt"] is True
    assert raw["memory_top_k"] == 0
    assert raw["max_subagents"] == 0


def test_defaults_use_socket_mode_recovery_polling_and_adaptive_recall():
    defaults = load_config("config/agents.yaml").defaults

    assert defaults["polling_enabled"] is True
    assert defaults["poll_interval_seconds"] >= 60
    assert defaults["memory_top_k"] in {3, 4}
    assert defaults["memory_adaptive_top_k"] is True
    assert defaults["memory_deep_top_k"] > defaults["memory_top_k"]


def test_memory_limit_expands_only_for_deep_work():
    store = MemoryStore.__new__(MemoryStore)
    store.default_top_k = 4
    store.adaptive_top_k = True
    store.deep_top_k = 10

    assert store._retrieval_limit("What is the current status?", None) == 4
    assert store._retrieval_limit("status context " * 500, None) == 4
    assert store._retrieval_limit("Diagnose and implement the root cause fix", None) == 10


def test_desktop_json_reuses_parsed_records_until_file_changes(tmp_path, monkeypatch):
    path = tmp_path / "memory_vectors.json"
    path.write_text(json.dumps([{"Id": "one"}]), encoding="utf-8")
    reads = 0
    original = Path.read_text

    def counted_read_text(self, *args, **kwargs):
        nonlocal reads
        if self == path:
            reads += 1
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", counted_read_text)
    assert desktop_memory_json.load_desktop_records(path)[0]["Id"] == "one"
    assert desktop_memory_json.load_desktop_records(path)[0]["Id"] == "one"
    assert reads == 1

    time.sleep(0.002)
    path.write_text(json.dumps([{"Id": "one"}, {"Id": "two"}]), encoding="utf-8")
    assert len(desktop_memory_json.load_desktop_records(path)) == 2
    assert reads == 2


def test_shared_chat_tail_is_cached_by_file_signature(tmp_path, monkeypatch):
    path = tmp_path / "events.jsonl"
    path.write_text('{"agentName":"general","source":"desktop","text":"one"}\n', encoding="utf-8")
    calls = 0
    original = shared_chat._tail_lines

    def counted_tail(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(shared_chat, "_tail_lines", counted_tail)
    assert len(shared_chat._tail_json_records(path, max_lines=1000)) == 1
    assert len(shared_chat._tail_json_records(path, max_lines=1000)) == 1
    assert calls == 1

    with path.open("a", encoding="utf-8") as handle:
        handle.write('{"agentName":"general","source":"desktop","text":"two"}\n')
    assert len(shared_chat._tail_json_records(path, max_lines=1000)) == 2
    assert calls == 2


def test_shared_chat_acknowledgements_are_not_added_to_agent_context(tmp_path):
    path = tmp_path / "events.jsonl"
    path.write_text(
        "\n".join(
            [
                '{"agentName":"coding_agent","source":"command_center","role":"user","text":"Check the gateway"}',
                '{"agentName":"coding_agent","source":"command_center","role":"acknowledgement","text":"Got it - starting now."}',
            ]
        ),
        encoding="utf-8",
    )

    context = shared_chat.format_recent_chat(
        path=path,
        agent_name="coding_agent",
        current_source="slack",
        limit=12,
    )

    assert "Check the gateway" in context
    assert "starting now" not in context


def test_shared_artifact_tail_is_cached_by_file_signature(tmp_path, monkeypatch):
    path = tmp_path / "index.jsonl"
    path.write_text('{"agentName":"general","path":"one"}\n', encoding="utf-8")
    calls = 0
    original = shared_artifacts._tail_lines

    def counted_tail(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(shared_artifacts, "_tail_lines", counted_tail)
    assert len(shared_artifacts._tail_json_records(path, max_lines=1000)) == 1
    assert len(shared_artifacts._tail_json_records(path, max_lines=1000)) == 1
    assert calls == 1

    with path.open("a", encoding="utf-8") as handle:
        handle.write('{"agentName":"general","path":"two"}\n')
    assert len(shared_artifacts._tail_json_records(path, max_lines=1000)) == 2
    assert calls == 2
