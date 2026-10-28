import sqlite3
import time

import pytest

from codex_slack_bridge.config import BridgeConfig
from codex_slack_bridge.command_center_server import CommandCenterRuntime
from codex_slack_bridge.memory import MemoryStore, _normalize_lance_score


def _store(tmp_path) -> MemoryStore:
    return MemoryStore(
        BridgeConfig(
            defaults={
                "memory_enabled": True,
                "memory_backend": "sqlite",
                "memory_sqlite_path": str(tmp_path / "memory.sqlite3"),
                "memory_desktop_json_mirror": False,
                "memory_top_k": 8,
            },
            channels={},
            agents={},
        )
    )


def test_lancedb_distance_is_normalized_as_higher_is_better():
    assert _normalize_lance_score({"_distance": 0.0}) == 1.0
    assert _normalize_lance_score({"_distance": 0.25}) > _normalize_lance_score({"_distance": 2.0})
    assert 0.0 <= _normalize_lance_score({"_score": 12.0}) <= 1.0


def test_expired_and_stale_memories_are_not_retrieved(tmp_path):
    store = _store(tmp_path)
    expired_id = store.remember(
        agent_name="general",
        text="Chargify obsolete endpoint details",
        source="runbook",
        expires_at=time.time() - 1,
    )
    stale_id = store.remember(
        agent_name="general",
        text="Chargify stale authentication details",
        source="runbook",
    )
    active_id = store.remember(
        agent_name="general",
        text="Chargify current authentication workflow",
        source="runbook",
    )

    assert expired_id and stale_id and active_id
    assert store.record_feedback(stale_id, stale=True)
    results = store.retrieve(agent_name="general", query="Chargify authentication endpoint details")
    assert [row["id"] for row in results] == [active_id]


def test_supersession_is_atomic_and_cross_agent_safe(tmp_path):
    store = _store(tmp_path)
    old_id = store.remember(
        agent_name="billing",
        text="Use the legacy Chargify route",
        source="billing-runbook",
        source_version="1",
    )
    new_id = store.remember(
        agent_name="billing",
        text="Use the current Maxio route",
        source="billing-runbook",
        source_version="2",
        supersedes=old_id,
        metadata={"owner": "billing-platform", "verified": True},
    )
    assert old_id and new_id
    results = store.retrieve(agent_name="billing", query="Chargify Maxio route")
    assert [row["id"] for row in results] == [new_id]
    assert results[0]["source_version"] == "2"
    assert results[0]["metadata"]["verified"] is True

    with pytest.raises(ValueError, match="already superseded"):
        store.remember(
            agent_name="billing",
            text="Competing route",
            source="billing-runbook",
            supersedes=old_id,
        )
    exported = {row["id"]: row for row in store.export_sqlite_rows()}
    assert len(exported) == 2
    assert exported[old_id]["superseded_by"] == new_id


def test_feedback_changes_rank_without_rewriting_evidence(tmp_path):
    store = _store(tmp_path)
    first = store.remember(
        agent_name="general",
        text="Card services onboarding verification alpha",
        source="operator-note",
    )
    second = store.remember(
        agent_name="general",
        text="Card services onboarding verification beta",
        source="operator-note",
    )
    assert first and second
    assert store.record_feedback(first, helpful=True)
    assert store.record_feedback(second, helpful=False)

    results = store.retrieve(agent_name="general", query="card services onboarding verification")
    assert results[0]["id"] == first
    assert results[0]["feedback"]["helpful"] == 1
    assert next(row for row in results if row["id"] == second)["feedback"]["unhelpful"] == 1


def test_existing_sqlite_schema_is_migrated_in_place(tmp_path):
    path = tmp_path / "memory.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute(
            """
            CREATE TABLE memories (
                id TEXT PRIMARY KEY, agent_name TEXT NOT NULL, text TEXT NOT NULL,
                source TEXT NOT NULL, tags_json TEXT NOT NULL,
                importance REAL NOT NULL, created_at REAL NOT NULL
            )
            """
        )
        db.execute(
            "INSERT INTO memories VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("legacy", "general", "legacy migration evidence", "legacy", "[]", 1.0, time.time()),
        )

    store = _store(tmp_path)
    assert store.retrieve(agent_name="general", query="legacy migration evidence")[0]["id"] == "legacy"
    assert store.record_feedback("legacy", helpful=True)


def test_command_center_exposes_memory_feedback_without_rewriting_evidence():
    class FakeMemory:
        def __init__(self):
            self.calls = []

        def recent(self, *, agent_name, limit):
            return [{"id": "memory-1", "agent_name": agent_name, "text": "current rule"}][:limit]

        def record_feedback(self, memory_id, *, helpful=None, stale=False):
            self.calls.append((memory_id, helpful, stale))
            return memory_id == "memory-1"

    runtime = object.__new__(CommandCenterRuntime)
    runtime.config = type("Config", (), {"agents": {"coding_agent": {}}})()
    runtime.memory = FakeMemory()

    assert runtime.memory_recent(agent_name="coding_agent", limit=5)["count"] == 1
    result = runtime.memory_feedback({"memoryId": "memory-1", "stale": True})
    assert result["stale"] is True
    assert runtime.memory.calls == [("memory-1", None, True)]


def test_desktop_mirror_retrieval_returns_canonical_sqlite_id_for_feedback(tmp_path):
    store = MemoryStore(
        BridgeConfig(
            defaults={
                "memory_enabled": True,
                "memory_backend": "sqlite",
                "memory_sqlite_path": str(tmp_path / "memory.sqlite3"),
                "memory_desktop_json_mirror": True,
                "memory_desktop_json_path": str(tmp_path / "desktop.json"),
                "memory_top_k": 8,
            },
            channels={},
            agents={},
        )
    )
    memory_id = store.remember(
        agent_name="general",
        text="Canonical feedback target for Maxio guidance",
        source="operator-note",
    )
    retrieved = store.retrieve(agent_name="general", query="Maxio guidance")
    assert retrieved[0]["id"] == memory_id
    assert store.record_feedback(retrieved[0]["id"], helpful=True) is True


def test_same_topic_memories_are_flagged_for_conflict_review_until_superseded(tmp_path):
    store = _store(tmp_path)
    first = store.remember(
        agent_name="general",
        text="Use the System column for tracker topics.",
        source="tracker-rules",
        metadata={"topic": "tracker-topic-column"},
    )
    second = store.remember(
        agent_name="general",
        text="Use the Topic column for tracker topics.",
        source="tracker-rules",
        metadata={"topic": "tracker-topic-column"},
    )
    assert first and second
    result = next(item for item in store.retrieve(agent_name="general", query="tracker topic column") if item["id"] == second)
    assert result["metadata"]["conflict_detected"] is True
    assert first in result["metadata"]["conflicts_with"]
