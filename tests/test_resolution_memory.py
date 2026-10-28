"""Tests for the durable resolution memory and read-only playbook loop."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from codex_slack_bridge.agent_policy import _without_disabled_surfaces
from codex_slack_bridge.command_center_server import CommandCenterRuntime
from codex_slack_bridge.config import load_config
from codex_slack_bridge.firestore_store import FirestoreStore
from codex_slack_bridge.resolution_memory import (
    PLAYBOOKS,
    RESOLUTIONS,
    MemoryDocStore,
    ResolutionMemory,
    build_digest,
    build_guidance,
    redact,
)

RESULT_TEMPLATE = (
    "Verified current state: Rescue session shows receipt printer {n} offline after the driver update.\n"
    "Root cause: the Star TSP100 driver was missing from the register terminal, confirmed in Nova SQL device table.\n"
    "Readback: verify the printer prints a test receipt from the register after the driver check.\n"
    "Update the Salesforce ticket and send the customer an email about the fix.\n"
    "Refund the customer for the on-site visit.\n"
    "OPERATOR_ACTION_REQUIRED: NONE\n"
)


def _doc(number: str, *, lane: str = "support", main: str = "Hardware", tech: str = "Printer", **extra):
    base = {
        "id": f"id-{number}",
        "number": number,
        "lane": lane,
        "recordType": "2. Nova Wave",
        "mainIssue": main,
        "technicalIssue": tech,
        "reconState": "completed",
        "reconFingerprint": f"fp-{number}",
        "reconResult": RESULT_TEMPLATE.format(n=number),
        "account": "Acme Bakery",
        "contact": "Jane Roe",
    }
    base.update(extra)
    return base


def _memory() -> tuple[ResolutionMemory, MemoryDocStore]:
    store = MemoryDocStore()
    return ResolutionMemory(store), store


# -- text hygiene ----------------------------------------------------------


def test_redact_strips_secrets_contacts_numbers_and_known_names() -> None:
    text = "Jane Roe (jane@acme.com, 555-123-4567) card 4111111111111111 token=abc123 at Acme Bakery"
    out = redact(text, scrub=["Jane Roe", "Acme Bakery"])
    assert "jane@acme.com" not in out
    assert "555-123-4567" not in out
    assert "4111111111111111" not in out
    assert "abc123" not in out
    assert "Jane Roe" not in out and "Acme Bakery" not in out


def test_digest_keeps_diagnosis_and_drops_write_shaped_lines() -> None:
    digest = build_digest(RESULT_TEMPLATE.format(n="1"), scrub=["Acme Bakery"])
    assert "Root cause" in digest
    assert "Readback" in digest
    lowered = digest.lower()
    for forbidden in ("refund", "salesforce ticket", "send the customer", "operator_action_required"):
        assert forbidden not in lowered


# -- capture / recall ------------------------------------------------------


def test_capture_then_recall_is_lane_scoped_and_excludes_the_same_ticket() -> None:
    memory, store = _memory()
    assert memory.capture_closed([_doc("101")]) == 1
    saved = store.doc_get(RESOLUTIONS, "id-101")
    assert saved["status"] == "closed"
    assert "Acme Bakery" not in json.dumps(saved) and "Jane Roe" not in json.dumps(saved)

    ticket = {"id": "id-999", "lane": "support", "mainIssue": "Hardware", "technicalIssue": "Printer",
              "notesPreview": "receipt printer offline"}
    recall = memory.recall(ticket)
    assert "Closed ticket 101" in recall.block
    assert "read-only evidence" in recall.block
    assert recall.resolution_ids == ["id-101"]

    same = dict(ticket, id="id-101")
    assert memory.recall(same).block == ""
    assert memory.recall(dict(ticket, lane="billing")).block == ""


def test_capture_is_idempotent_and_skips_uninvestigated_tickets() -> None:
    memory, _store = _memory()
    assert memory.capture_closed([_doc("101")]) == 1
    assert memory.capture_closed([_doc("101")]) == 0
    assert memory.capture_closed([_doc("102", reconState="failed")]) == 0
    assert memory.capture_closed([_doc("103", reconResult="")]) == 0


# -- playbooks: draft, promote, rollback ------------------------------------


def _seed(memory: ResolutionMemory, count: int, *, playbook_ids=()):
    docs = [_doc(str(200 + i), reconPlaybookIds=list(playbook_ids)) for i in range(count)]
    memory.capture_closed(docs)


def test_playbook_needs_three_distinct_tickets_and_is_read_only_guidance() -> None:
    memory, store = _memory()
    _seed(memory, 2)
    assert memory.refresh_playbooks()["drafted"] == 0
    _seed(memory, 3)
    assert memory.refresh_playbooks()["drafted"] == 1
    playbook = store.doc_list(PLAYBOOKS)[0]
    assert playbook["state"] == "canary"
    assert playbook["readOnly"] is True
    assert not ({"mcp_allowlist", "operations", "capabilities", "tools"} & set(playbook))
    lowered = playbook["guidance"].lower()
    assert "root cause" in lowered
    for forbidden in ("refund", "send", "update the salesforce", "close"):
        assert forbidden not in lowered


def test_playbook_is_served_then_promoted_after_clean_closes() -> None:
    memory, store = _memory()
    _seed(memory, 3)
    memory.refresh_playbooks()
    playbook_id = store.doc_list(PLAYBOOKS)[0]["id"]

    ticket = {"id": "new-1", "lane": "support", "mainIssue": "Hardware", "technicalIssue": "Printer",
              "notesPreview": "receipt printer offline"}
    recall = memory.recall(ticket)
    assert recall.playbook_ids == [playbook_id]
    assert "Playbook [canary]" in recall.block
    assert store.doc_get(PLAYBOOKS, playbook_id)["servedCount"] == 1

    memory.capture_closed([_doc("301", reconPlaybookIds=[playbook_id]),
                           _doc("302", reconPlaybookIds=[playbook_id])])
    memory.refresh_playbooks()
    assert store.doc_get(PLAYBOOKS, playbook_id)["state"] == "active"


def test_reopen_unverifies_the_resolution_and_rolls_back_a_canary() -> None:
    memory, store = _memory()
    _seed(memory, 3)
    memory.refresh_playbooks()
    playbook_id = store.doc_list(PLAYBOOKS)[0]["id"]
    memory.capture_closed([_doc("401", reconPlaybookIds=[playbook_id])])

    assert memory.note_reopened(["id-401"]) == 1
    assert store.doc_get(RESOLUTIONS, "id-401")["status"] == "reopened"
    rolled = store.doc_get(PLAYBOOKS, playbook_id)
    assert rolled["state"] == "rolled_back"

    ticket = {"id": "n", "lane": "support", "mainIssue": "Hardware", "technicalIssue": "Printer",
              "notesPreview": "receipt printer offline"}
    assert playbook_id not in memory.recall(ticket).playbook_ids
    # Rolled-back guidance returns only after real new supporting evidence.
    memory.refresh_playbooks()
    assert store.doc_get(PLAYBOOKS, playbook_id)["state"] == "rolled_back"


def test_active_playbook_survives_one_strike_but_not_two() -> None:
    memory, store = _memory()
    _seed(memory, 3)
    memory.refresh_playbooks()
    playbook_id = store.doc_list(PLAYBOOKS)[0]["id"]
    store.doc_put(PLAYBOOKS, playbook_id, {"state": "active"})
    memory.capture_closed([_doc("501", reconPlaybookIds=[playbook_id]),
                           _doc("502", reconPlaybookIds=[playbook_id])])
    memory.note_reopened(["id-501"])
    assert store.doc_get(PLAYBOOKS, playbook_id)["state"] == "active"
    memory.note_reopened(["id-502"])
    assert store.doc_get(PLAYBOOKS, playbook_id)["state"] == "rolled_back"


def test_lifecycle_marks_stale_then_archived_by_idle_time() -> None:
    memory, store = _memory()
    old = (datetime.now(timezone.utc) - timedelta(days=40)).isoformat()
    older = (datetime.now(timezone.utc) - timedelta(days=100)).isoformat()
    store.doc_put(PLAYBOOKS, "a", {"state": "active", "lane": "support", "updatedAt": old})
    store.doc_put(PLAYBOOKS, "b", {"state": "canary", "lane": "support", "updatedAt": older})
    store.doc_put(PLAYBOOKS, "c", {"state": "active", "lane": "support",
                                   "updatedAt": older, "lastServedAt": datetime.now(timezone.utc).isoformat()})
    summary = memory.apply_lifecycle()
    assert summary == {"stale": 1, "archived": 1}
    assert store.doc_get(PLAYBOOKS, "a")["state"] == "stale"
    assert store.doc_get(PLAYBOOKS, "b")["state"] == "archived"
    assert store.doc_get(PLAYBOOKS, "c")["state"] == "active"


def test_guidance_requires_recurring_lines() -> None:
    assert build_guidance(["Root cause: unique line number one about a thing"]) == ""


# -- fail-safe -------------------------------------------------------------


class _BrokenStore:
    def doc_get(self, *_a, **_k):
        raise RuntimeError("firestore down")

    doc_put = doc_list = doc_get


def test_every_operation_degrades_to_a_noop_when_the_store_fails() -> None:
    memory = ResolutionMemory(_BrokenStore())
    ticket = {"id": "1", "lane": "support", "mainIssue": "Hardware"}
    assert memory.recall(ticket).block == ""
    assert memory.capture_closed([_doc("1")]) == 0
    assert memory.note_reopened(["1"]) == 0
    assert memory.refresh_playbooks() == {"drafted": 0, "updated": 0, "promoted": 0}
    assert memory.apply_lifecycle() == {"stale": 0, "archived": 0}


def test_disabled_or_missing_store_is_a_noop() -> None:
    assert ResolutionMemory(None).recall({"mainIssue": "x"}).block == ""
    assert ResolutionMemory(MemoryDocStore(), enabled=False).capture_closed([_doc("1")]) == 0


# -- runtime wiring --------------------------------------------------------


def test_recon_prompt_includes_recall_and_records_served_playbooks(tmp_path) -> None:
    memory, store = _memory()
    _seed(memory, 3)
    memory.refresh_playbooks()
    playbook_id = store.doc_list(PLAYBOOKS)[0]["id"]

    runtime = object.__new__(CommandCenterRuntime)
    runtime.config = SimpleNamespace(
        defaults={"ops_ticket_recon_enabled": True, "ops_ticket_recon_max_per_run": 1,
                  "ops_ticket_recon_job_timeout_seconds": 60},
        agents={"tickets_agent": {}},
    )
    runtime.tickets_path = tmp_path / "ops_tickets.json"
    runtime.tickets_path.write_text(json.dumps({"columns": [{"key": "support", "tickets": [
        {"id": "live-1", "number": "900", "lane": "support", "updatedAt": "1",
         "mainIssue": "Hardware", "technicalIssue": "Printer", "notesPreview": "receipt printer offline"}]}]}),
        encoding="utf-8")

    puts: list = []

    class _Store:
        available = True
        TICKETS_COLLECTION = "tickets"

        def claim_ticket_recon(self, *_a, **_k):
            return True

        def complete_ticket_recon(self, *_a, **_k):
            return True

        def doc_put(self, collection, doc_id, data):
            puts.append((collection, doc_id, data))
            return True

    runtime.firestore_store = _Store()
    runtime.resolution_memory = memory
    prompts: list[str] = []

    def _submit(**kwargs):
        prompts.append(kwargs["prompt"])
        return {"accepted": True, "job_id": "job-900"}

    runtime.submit_prompt = _submit
    runtime.job = lambda _id: {"status": "completed", "result": "plan"}

    result = runtime.run_ticket_recon_batch()

    assert result["completed"] == 1
    assert "Prior knowledge for this ticket" in prompts[0]
    assert "OPERATOR_ACTION_REQUIRED" in prompts[0]
    assert ("tickets", "live-1", {"reconPlaybookIds": [playbook_id]}) in puts


def test_board_refresh_learning_hook_never_raises() -> None:
    runtime = object.__new__(CommandCenterRuntime)
    runtime.resolution_memory = ResolutionMemory(_BrokenStore())
    runtime._learn_from_board_refresh([_doc("1")], ["id-1"])
    runtime.resolution_memory = None
    runtime._learn_from_board_refresh([_doc("1")], ["id-1"])


def test_board_refresh_scans_collections_only_when_evidence_changed() -> None:
    calls = {"refresh": 0, "lifecycle": 0}

    class _Counting(ResolutionMemory):
        def refresh_playbooks(self):
            calls["refresh"] += 1
            return {"drafted": 0, "updated": 0, "promoted": 0}

        def apply_lifecycle(self, **_kw):
            calls["lifecycle"] += 1
            return {"stale": 0, "archived": 0}

    runtime = object.__new__(CommandCenterRuntime)
    runtime.resolution_memory = _Counting(MemoryDocStore())
    runtime._learn_from_board_refresh([], ["id-1"])
    runtime._learn_from_board_refresh([], ["id-1"])
    assert calls == {"refresh": 0, "lifecycle": 1}  # quiet refreshes do no scans; lifecycle is throttled
    runtime._learn_from_board_refresh([_doc("1")], ["id-2"])
    assert calls["refresh"] == 1 and calls["lifecycle"] == 1


def test_delete_tickets_missing_collects_closed_docs_without_changing_its_result() -> None:
    updates: dict = {}

    class _Ref:
        def __init__(self, key):
            self.key = key

        def update(self, data):
            updates[self.key] = data

    class _Snap:
        def __init__(self, key, data):
            self.id, self._d, self.reference = key, data, _Ref(key)

        def to_dict(self):
            return self._d

    docs = [_Snap("gone", {"number": "1", "reconResult": "x"}), _Snap("kept", {"number": "2"})]

    class _Coll:
        def stream(self):
            return iter(docs)

    store = FirestoreStore(enabled=False)
    store._enabled = True
    store._client = object()
    store._collection = lambda _n: _Coll()
    collected: list = []
    assert store.delete_tickets_missing({"2"}, collect=collected) == {"ok": True, "closed": 1}
    assert [d["id"] for d in collected] == ["gone"] and collected[0]["reconResult"] == "x"
    assert "closedAt" in collected[0]


# -- Gmail retirement filters ----------------------------------------------


def test_disabled_surfaces_only_narrow_the_lane() -> None:
    lane = {
        "read_surfaces": ["salesforce", "gmail"],
        "write_surfaces": ["gmail", "zoom"],
        "operations": ["gmail.read", "gmail.authorized_write", "salesforce.ticket.read", "gmailish.keep"],
        "limitations": ["no_capability_changes"],
        "mcp_allowlist": ["x"],
    }
    narrowed = _without_disabled_surfaces(lane, ["gmail"])
    assert narrowed["read_surfaces"] == ["salesforce"]
    assert narrowed["write_surfaces"] == ["zoom"]
    assert narrowed["operations"] == ["salesforce.ticket.read", "gmailish.keep"]
    assert narrowed["limitations"] == lane["limitations"] and narrowed["mcp_allowlist"] == ["x"]
    assert _without_disabled_surfaces(lane, None) is lane
    assert lane["operations"][0] == "gmail.read"  # original untouched


def test_config_disabled_skills_are_removed_from_every_agent(tmp_path: Path) -> None:
    config = tmp_path / "agents.yaml"
    config.write_text(yaml.safe_dump({
        "defaults": {"disabled_skills": ["email_watch"]},
        "agents": {"a": {"skills": ["email_watch", "customer_email"]}, "b": {"skills": ["email_watch"]}, "c": {}},
        "channels": {},
    }), encoding="utf-8")
    loaded = load_config(config)
    assert loaded.agents["a"]["skills"] == ["customer_email"]
    assert loaded.agents["b"]["skills"] == []
    assert "skills" not in loaded.agents["c"]


@pytest.mark.parametrize("agent", ["coding_agent", "billing_agent", "tickets_agent"])
def test_production_overlay_retires_gmail_for_every_active_lane(agent: str) -> None:
    from codex_slack_bridge.agent_policy import validate_runtime_agent_policy

    root = Path(__file__).resolve().parents[1]
    config = load_config(root / "config" / "agents.cloud-run-chatgpt.yaml")
    settings = {**config.defaults, **config.agents[agent]}
    settings["agent_capability_contract_path"] = str(root / "config" / "agent-capabilities.yaml")
    lane = validate_runtime_agent_policy(agent, settings)
    assert "gmail" not in (lane.get("read_surfaces") or []) + (lane.get("write_surfaces") or [])
    assert not [op for op in lane["operations"] if op.startswith("gmail.")]
    assert "email_watch" not in config.agents[agent].get("skills", [])
    assert config.defaults["resolution_memory_enabled"] is True


# -- shipped curated KB ------------------------------------------------------

from codex_slack_bridge.resolution_memory import KnowledgeBase, kb_lane, load_knowledge_base  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]


def _kb(tmp_path: Path) -> KnowledgeBase:
    docs = {
        "wave.md": ("Wave printer setup", "nova_wave", ["printer", "receipt"], "Wave only: pair the receipt printer in Back Office Settings.\n\nUnrelated paragraph about reports."),
        "classic.md": ("Classic printer setup", "nova_classic", ["printer", "receipt"], "Classic only: install the printer driver from the Nova Classic folder."),
        "general.md": ("General printer troubleshooting", "general", ["printer", "offline"], "Power cycle the printer, then check the cable and retry a test receipt."),
        "billing.md": ("Billing printer invoice", "billing", ["printer", "invoice"], "Billing only: invoice printer charges are handled by Jamie."),
    }
    entries = []
    for name, (title, lane, keywords, body) in docs.items():
        (tmp_path / name).write_text(body, encoding="utf-8")
        entries.append({"path": name, "title": title, "lane": lane, "keywords": keywords, "priority": 50})
    (tmp_path / "kb_index.json").write_text(json.dumps({"entries": entries}), encoding="utf-8")
    return KnowledgeBase(tmp_path)


def test_kb_lane_mapping() -> None:
    assert kb_lane({"lane": "billing"}) == "billing"
    assert kb_lane({"lane": "support", "recordType": "2. Nova Wave"}) == "nova_wave"
    assert kb_lane({"lane": "support", "recordType": "1. NOVA Classic"}) == "nova_classic"
    assert kb_lane({"lane": "support", "recordType": ""}) == ""


def test_kb_search_is_lane_isolated(tmp_path: Path) -> None:
    kb = _kb(tmp_path)
    wave = " ".join(title for title, _ in kb.search("printer receipt offline", "nova_wave", limit=5))
    assert "Wave printer setup" in wave and "General printer" in wave
    assert "Classic" not in wave and "Billing" not in wave
    classic = " ".join(title for title, _ in kb.search("printer receipt offline", "nova_classic", limit=5))
    assert "Classic printer setup" in classic and "Wave" not in classic
    billing = " ".join(title for title, _ in kb.search("printer invoice", "billing", limit=5))
    assert "Billing printer invoice" in billing and "Wave" not in billing
    # Unknown product lane never receives billing-only guidance.
    assert "Billing" not in " ".join(title for title, _ in kb.search("printer invoice", "", limit=5))


def test_kb_excerpt_prefers_the_relevant_paragraph(tmp_path: Path) -> None:
    kb = _kb(tmp_path)
    (_title, excerpt) = kb.search("pair receipt printer", "nova_wave", limit=1)[0]
    assert "Back Office Settings" in excerpt


def test_recall_serves_kb_even_without_a_learning_store(tmp_path: Path) -> None:
    memory = ResolutionMemory(None, knowledge=_kb(tmp_path))
    ticket = {"id": "t1", "lane": "support", "recordType": "2. Nova Wave", "mainIssue": "Hardware",
              "technicalIssue": "Printer", "notesPreview": "receipt printer offline"}
    recall = memory.recall(ticket)
    assert "KB article 'Wave printer setup'" in recall.block
    assert "Classic only" not in recall.block
    assert recall.playbook_ids == []
    # Without a store there is nothing to learn into: every learning call is a no-op.
    assert memory.capture_closed([_doc("1")]) == 0
    assert memory.note_reopened(["id-1"]) == 0
    assert memory.refresh_playbooks() == {"drafted": 0, "updated": 0, "promoted": 0}


def test_shipped_kb_loads_and_answers_a_real_wave_hardware_question() -> None:
    kb = load_knowledge_base()
    assert kb is not None and kb.size >= 100
    hits = kb.search("printer offline receipt not printing", "nova_wave")
    assert hits and all(excerpt.strip() for _title, excerpt in hits)
    billing_titles = {t for t, _ in kb.search("printer offline receipt not printing", "nova_wave", limit=10)}
    assert not any("invoice" in t.lower() and "billing" in t.lower() for t in billing_titles)


def test_shipped_kb_has_no_secrets_or_customer_contacts() -> None:
    import re

    allowed = {"donotreply@novapointofsale.com", "billing@novapointofsale.com", "support@novapointofsale.com"}
    email = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+[.][A-Za-z]{2,}")
    for path in (REPO_ROOT / "knowledge_base").rglob("*.md"):
        text = path.read_text(encoding="utf-8", errors="replace")
        assert set(email.findall(text)) <= allowed, path.name
        assert "BEGIN PRIVATE KEY" not in text and "xoxb-" not in text, path.name


def test_production_image_ships_skills_and_knowledge_base() -> None:
    dockerfile = (REPO_ROOT / "deploy" / "gcp" / "Dockerfile.cloud-run-chatgpt").read_text(encoding="utf-8")
    assert "COPY skills ./skills" in dockerfile
    assert "COPY knowledge_base ./knowledge_base" in dockerfile
    dockerignore = (REPO_ROOT / ".dockerignore").read_text(encoding="utf-8").split()
    assert "skills" not in dockerignore and "knowledge_base" not in dockerignore
    assert (REPO_ROOT / "skills" / "security.md").is_file()
    assert (REPO_ROOT / "knowledge_base" / "kb_index.json").is_file()


# -- learning metrics --------------------------------------------------------


def test_capture_records_hours_to_close() -> None:
    memory, store = _memory()
    memory.capture_closed([_doc("601", createdAt="2026-10-10T08:00:00+00:00", closedAt="2026-10-10T20:30:00+00:00")])
    assert store.doc_get(RESOLUTIONS, "id-601")["hoursToClose"] == 12.5
    memory.capture_closed([_doc("602")])
    assert store.doc_get(RESOLUTIONS, "id-602")["hoursToClose"] is None


def test_metrics_report_reopen_rate_close_time_playbooks_and_recalls(tmp_path: Path) -> None:
    memory = ResolutionMemory(MemoryDocStore(), knowledge=_kb(tmp_path))
    store = memory._store
    for number, hours in (("701", 2), ("702", 4), ("703", 10)):
        memory.capture_closed([_doc(number, createdAt="2026-10-10T00:00:00+00:00",
                                    closedAt=f"2026-10-10T{hours:02d}:00:00+00:00")])
    memory.capture_closed([_doc("704", lane="billing", main="Subscription", tech="Rate")])
    memory.note_reopened(["id-703"])
    memory.refresh_playbooks()
    ticket = {"id": "n", "lane": "support", "recordType": "2. Nova Wave", "mainIssue": "Hardware",
              "technicalIssue": "Printer", "notesPreview": "receipt printer offline"}
    memory.recall(ticket)

    metrics = memory.metrics()
    support = metrics["lanes"]["support"]
    assert metrics["knowledgeBaseEntries"] == 4
    assert support["resolutionsCaptured"] == 3
    assert support["reopened"] == 1 and support["reopenRate"] == round(1 / 3, 3)
    assert support["medianHoursToClose"] == 4
    assert support["recalls"] == 1 and support["recallsWithKb"] == 1
    assert metrics["lanes"]["billing"]["resolutionsCaptured"] == 1
    assert metrics["lanes"]["billing"]["reopenRate"] == 0.0
    assert store.doc_get("learning_stats", "recall-support")["recalls"] == 1


def test_metrics_are_safe_when_disabled_or_store_fails() -> None:
    assert ResolutionMemory(None).metrics() == {"enabled": False, "knowledgeBaseEntries": 0}
    broken = ResolutionMemory(_BrokenStore()).metrics()
    assert broken["enabled"] is True and "lanes" not in broken


def test_learning_metrics_endpoint_payload() -> None:
    runtime = object.__new__(CommandCenterRuntime)
    assert runtime.learning_metrics() == {"ok": True, "enabled": False}
    runtime.resolution_memory = ResolutionMemory(MemoryDocStore())
    payload = runtime.learning_metrics()
    assert payload["ok"] is True and payload["lanes"]["support"]["recalls"] == 0
