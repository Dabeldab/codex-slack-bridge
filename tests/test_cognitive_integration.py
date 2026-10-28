import sqlite3

import pytest

from codex_slack_bridge.app import _format_cognitive_episodes as format_slack_episodes
from codex_slack_bridge.cognitive_memory import CognitiveMemoryStore
from codex_slack_bridge.command_center_server import (
    _format_cognitive_episodes as format_command_center_episodes,
)


def _store(tmp_path):
    return CognitiveMemoryStore(tmp_path / "cognitive.sqlite3")


def test_episode_retrieval_is_scoped_to_requested_agent_lanes(tmp_path):
    store = _store(tmp_path)
    billing = store.append_episode(
        agent_name="billing_agent",
        summary="Verified Maxio allocation reconciliation for the customer.",
    )
    global_episode = store.append_episode(
        agent_name="global",
        summary="Verified global Maxio reconciliation preference.",
    )
    store.append_episode(
        agent_name="coding_agent",
        summary="Verified Maxio reconciliation implementation detail.",
    )

    results = store.retrieve_episodes(
        query="Maxio reconciliation",
        agent_names=["billing_agent", "global"],
    )

    assert {item["id"] for item in results} == {billing, global_episode}
    assert {item["agent_name"] for item in results} == {"billing_agent", "global"}


def test_query_only_retrieval_excludes_zero_lexical_overlap(tmp_path):
    store = _store(tmp_path)
    store.append_episode(
        agent_name="billing_agent",
        summary="Verified a Salesforce billing schedule readback.",
    )

    assert store.retrieve_episodes(
        query="Singapore FTP submission",
        agent_names=["billing_agent"],
    ) == []


def test_episode_key_is_deterministic_and_idempotent(tmp_path):
    store = _store(tmp_path)
    first = store.append_episode(
        agent_name="tickets_agent",
        summary="Verified the original ticket outcome.",
        episode_key="command-center:job-42",
    )
    second = store.append_episode(
        agent_name="tickets_agent",
        summary="A replay must not create a second episode.",
        episode_key="command-center:job-42",
    )

    assert second == first
    with sqlite3.connect(tmp_path / "cognitive.sqlite3") as db:
        assert db.execute("SELECT COUNT(*) FROM cognitive_episodes").fetchone()[0] == 1
        assert db.execute(
            "SELECT summary FROM cognitive_episodes WHERE id = ?", (first,)
        ).fetchone()[0] == "Verified the original ticket outcome."


@pytest.mark.parametrize(
    "formatter",
    [format_slack_episodes, format_command_center_episodes],
)
def test_prompt_formatting_labels_history_and_caps_episode_content(formatter):
    episodes = [
        {"summary": "word " * 300},
        {"summary": "second relevant episode"},
        {"summary": "third relevant episode"},
        {"summary": "must not enter the prompt"},
    ]

    formatted = formatter(episodes)
    lines = formatted.splitlines()

    assert "historical episodes" in lines[0].lower()
    assert "not proof" in lines[0].lower()
    assert len(lines) == 4
    assert all(len(line.removeprefix("- ")) <= 650 for line in lines[1:])
    assert lines[1].endswith("...")
    assert "must not enter the prompt" not in formatted
