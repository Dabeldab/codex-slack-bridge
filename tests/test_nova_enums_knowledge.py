from __future__ import annotations

# AgentChat/direct_codex 2026-07-27T21:24:14Z

from pathlib import Path

from codex_slack_bridge.config import BridgeConfig
from codex_slack_bridge.knowledge_ingest import chunk_text, iter_documents, normalize_text
from codex_slack_bridge.memory import MemoryStore


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "knowledge_sources" / "general" / "nova_database" / "nova_enums.md"


def test_nova_enum_reference_is_complete_and_retrievable_by_every_lane(tmp_path: Path) -> None:
    documents = list(iter_documents(SOURCE))
    assert len(documents) == 1
    assert documents[0].product_lane == "general"

    text = normalize_text(documents[0].text)
    expected_mappings = {
        "Invoice_Exchange": "5",
        "InvoiceEmployeeNonCommissionChanged": "8",
        "Canceled": "2",
        "InventoryCountNotCreatedOnSchedule": "26",
        "StellarManualRefundAmount": "27",
    }
    for name, value in expected_mappings.items():
        assert name in text
        assert value in text

    config = BridgeConfig(
        defaults={
            "memory_enabled": True,
            "memory_backend": "sqlite",
            "memory_sqlite_path": str(tmp_path / "memory.sqlite3"),
            "desktop_vector_memory_path": str(tmp_path / "memory_vectors.json"),
            "memory_desktop_json_mirror": False,
            "memory_global_agent": "global",
            "memory_top_k": 4,
        },
        channels={},
        agents={},
    )
    memory = MemoryStore(config)
    chunks = list(chunk_text(text, max_words=700, overlap_words=120))
    assert chunks
    for index, chunk in enumerate(chunks, start=1):
        memory.remember(
            agent_name="global",
            text=chunk,
            source=f"kb:nova_enums.md#{index}",
            tags=["nova", "database", "enums", "knowledgebase", "product_lane:general"],
            importance=3.0,
        )

    for lane in (
        "direct_codex",
        "raw_codex",
        "claude_agent",
        "coding_agent",
        "tickets_agent",
        "billing_agent",
    ):
        results = memory.retrieve(agent_name=lane, query="StellarManualRefundAmount enum value")
        assert results
        assert any(
            result["agent_name"] == "global" and "StellarManualRefundAmount" in result["text"]
            for result in results
        )


def test_private_runtime_bootstrap_ingests_enum_reference_idempotently() -> None:
    bootstrap = (
        ROOT / "deploy" / "gcp" / "agent-runtime" / "bootstrap-private-runtime.sh"
    ).read_text(encoding="utf-8")

    assert "NOVA_ENUMS_STATE_SOURCE" in bootstrap
    assert 'cmp -s "$NOVA_ENUMS_RELEASE_SOURCE" "$NOVA_ENUMS_STATE_SOURCE"' in bootstrap
    assert "-m codex_slack_bridge.knowledge_ingest" in bootstrap
    assert "--agent global" in bootstrap
    assert "--tags nova,database,enums" in bootstrap
