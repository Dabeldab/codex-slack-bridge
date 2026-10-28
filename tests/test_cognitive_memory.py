import sqlite3
import threading
import time

import pytest

from codex_slack_bridge.cognitive_memory import CognitiveMemoryStore


def _store(tmp_path):
    return CognitiveMemoryStore(tmp_path / "memory.sqlite3")


def test_verified_episode_and_entity_graph_retrieval(tmp_path):
    store = _store(tmp_path)
    account = store.upsert_entity(
        entity_type="salesforce_account", canonical_name="Acme Coffee", aliases=["SF-001"],
        evidence={"source": "readback"},
    )
    subscription = store.upsert_entity(
        entity_type="maxio_subscription", canonical_name="Subscription 42", aliases=["SUB-42"]
    )
    store.link_entities(account, subscription, "billed_by", confidence=0.95, evidence={"verified": True})
    episode = store.append_episode(
        agent_name="billing", summary="Verified the subscription allocation by API readback.",
        intent="reconcile", systems=["Salesforce", "Maxio"], entity_links=[account],
        evidence={"job": "safe-reference"},
    )

    found = store.lookup_identifier("sf-001")
    assert found[0]["id"] == account
    neighbors = store.associative_neighbors(account)
    assert neighbors[0]["entity_id"] == subscription
    results = store.retrieve_episodes(identifiers=["SUB-42"], intent="reconcile", systems=["maxio"])
    assert results[0]["id"] == episode
    assert results[0]["entity_links"][0]["entity_id"] == account


def test_unverified_episode_is_rejected_and_secrets_are_not_stored(tmp_path):
    store = _store(tmp_path)
    with pytest.raises(ValueError, match="verified"):
        store.append_episode(agent_name="general", summary="A guess", verified=False)

    secret = "sk-abcdefghijklmnopqrstuvwxyz123456"
    entity = store.upsert_entity(entity_type="customer", canonical_name="Customer", aliases=[secret])
    episode = store.append_episode(
        agent_name="general", summary=f"Credential was {secret}", evidence={"credential": secret}
    )
    assert store.lookup_identifier(secret)[0]["id"] == entity
    with sqlite3.connect(tmp_path / "memory.sqlite3") as db:
        dump = " ".join(str(value) for row in db.iterdump() for value in [row])
    assert secret not in dump
    assert "[redacted]" in dump.casefold()
    assert episode


def test_entity_updates_are_audited_and_expired_state_is_filtered(tmp_path):
    store = _store(tmp_path)
    entity = store.upsert_entity(entity_type="account", canonical_name="Northwind", aliases=["NW-7"])
    store.upsert_entity(
        entity_type="account", canonical_name="Northwind", aliases=["NW-7"],
        confidence=0.7, status="disputed", evidence={"reason": "conflicting source"},
    )
    history = store.audit_history("entity", entity)
    assert [row["action"] for row in history] == ["created", "updated"]
    assert history[0]["snapshot"]["status"] == "active"
    assert history[1]["snapshot"]["status"] == "disputed"
    assert store.lookup_identifier("NW-7") == []

    expired = store.upsert_entity(
        entity_type="account", canonical_name="Old Co", aliases=["OLD-1"], fresh_until=time.time() - 1
    )
    assert store.lookup_identifier("OLD-1") == []
    assert store.lookup_identifier("OLD-1", include_inactive=True)[0]["id"] == expired


def test_associative_spreading_is_bounded_and_ranked(tmp_path):
    store = _store(tmp_path)
    a = store.upsert_entity(entity_type="account", canonical_name="A")
    b = store.upsert_entity(entity_type="subscription", canonical_name="B")
    c = store.upsert_entity(entity_type="location", canonical_name="C")
    d = store.upsert_entity(entity_type="contact", canonical_name="D")
    store.link_entities(a, b, "subscription", confidence=1.0)
    store.link_entities(b, c, "location", confidence=0.9)
    store.link_entities(c, d, "contact", confidence=1.0)
    found = store.associative_neighbors(a, max_depth=2, min_confidence=0.1)
    assert [row["entity_id"] for row in found] == [b, c]
    assert found[0]["score"] > found[1]["score"]


def test_intent_system_time_and_freshness_filters(tmp_path):
    store = _store(tmp_path)
    entity = store.upsert_entity(entity_type="account", canonical_name="Timely", aliases=["TIME-1"])
    now = time.time()
    wanted = store.append_episode(
        agent_name="ops", summary="Recent reconciliation", intent="reconcile", systems=["maxio"],
        entity_links=[entity], occurred_at=now - 10,
    )
    store.append_episode(
        agent_name="ops", summary="Old reconciliation", intent="reconcile", systems=["maxio"],
        entity_links=[entity], occurred_at=now - 10000,
    )
    store.append_episode(
        agent_name="ops", summary="Expired reconciliation", intent="reconcile", systems=["maxio"],
        entity_links=[entity], fresh_until=now - 1,
    )
    results = store.retrieve_episodes(
        identifiers=["TIME-1"], intent="reconcile", systems=["maxio"], since=now - 100, at_time=now
    )
    assert [row["id"] for row in results] == [wanted]


def test_threaded_appends_do_not_lose_episodes(tmp_path):
    store = _store(tmp_path)
    errors = []

    def append(index):
        try:
            store.append_episode(agent_name="general", summary=f"Verified outcome {index}")
        except Exception as exc:  # pragma: no cover - assertion reports details
            errors.append(exc)

    threads = [threading.Thread(target=append, args=(index,)) for index in range(12)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []
    with sqlite3.connect(tmp_path / "memory.sqlite3") as db:
        assert db.execute("SELECT COUNT(*) FROM cognitive_episodes").fetchone()[0] == 12


def test_runtime_completion_without_independent_readback_is_quarantined(tmp_path):
    store = _store(tmp_path)
    episode_id = store.append_episode(
        agent_name="coding_agent",
        summary="Outcome: completed\nAgent reported the task complete.",
        source="command_center_completed_job",
        evidence={"completion": "agent_run_completed"},
    )

    assert store.quarantine_misclassified_outcome_episodes() == 1
    assert store.retrieve_episodes(intent="") == []
    with sqlite3.connect(tmp_path / "memory.sqlite3") as db:
        status = db.execute(
            "SELECT status FROM cognitive_episodes WHERE id=?",
            (episode_id,),
        ).fetchone()[0]
    assert status == "review_only"
    assert store.audit_history("episode", episode_id)[-1]["action"] == "quarantined_unverified_runtime_episode"


def test_runtime_completion_with_independent_readback_remains_verified(tmp_path):
    store = _store(tmp_path)
    episode_id = store.append_episode(
        agent_name="billing_agent",
        summary="Outcome: completed\nAllocation equality was read back from both systems.",
        source="command_center_completed_job",
        evidence={
            "completion": "agent_run_completed",
            "independent_readback": True,
        },
    )

    assert store.quarantine_misclassified_outcome_episodes() == 0
    retrieved = store.retrieve_episodes(intent="")
    assert [episode["id"] for episode in retrieved] == [episode_id]
