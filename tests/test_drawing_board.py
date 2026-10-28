from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

import codex_slack_bridge.command_center_server as command_center_server
from codex_slack_bridge.command_center_server import CommandCenterRuntime
from codex_slack_bridge.drawing_board import DrawingBoardStore
from codex_slack_bridge.shared_artifacts import register_artifact

# AgentChat/direct_codex 2026-07-14T17:58:31-04:00: verify reversible Drawing Board routing and linked work products.


def _actionable_payload(title: str = "Investigate Petra revenue discrepancy", **overrides):
    payload = {
        "title": title,
        "description": "Finance needs the reported discrepancy reconciled to the source records.",
        "requestedOutcome": "Return the reconciled total and identify the exact cause of any difference.",
        "nextAction": "Open the referenced account records and compare the stated reporting period.",
        "assigneeAction": "Alex must compare invoice and payment evidence and return the supported conclusion.",
        "completionCriteria": "The response cites source record IDs, period totals, and the reconciled difference.",
        "agentName": "tickets_agent",
        "sourceType": "salesforce_ticket",
        "sourceId": "347200",
        "owner": "Alex",
        "requester": "Finance",
    }
    payload.update(overrides)
    return payload


def test_create_is_idempotent_and_preserves_enriched_source_view(tmp_path):
    store = DrawingBoardStore(tmp_path / "drawing-board.sqlite3")
    payload = _actionable_payload(
        status="ready",
        priority="high",
        sourceType="gmail",
        sourceId="message-123",
        sourceUrl="https://mail.google.com/mail/#all/message-123",
        idempotencyKey="petra-revenue-discrepancy",
    )

    created = store.create(payload)
    duplicate = store.create({**payload, "description": "must not overwrite"})

    assert duplicate["id"] == created["id"]
    assert duplicate["description"] == payload["description"]
    assert duplicate["sources"] == created["sources"]
    assert duplicate["sources"][0]["source_id"] == "message-123"
    assert len(store.history(created["id"])) == 1


def test_completion_requires_proof_or_explicit_human_verification(tmp_path):
    store = DrawingBoardStore(tmp_path / "drawing-board.sqlite3")
    task = store.create({"title": "Confirm tax configuration"})

    with pytest.raises(ValueError, match="requires evidence or human verification"):
        store.update(task["id"], {"status": "verified_complete"})

    awaiting_review = store.add_evidence(
        task["id"],
        summary="Agent found the tenant configuration screen.",
        evidence_kind="agent_report",
        external_id="job-7",
        verified=False,
        created_by="billing_agent",
    )
    assert awaiting_review["status"] == "drawing"
    assert awaiting_review["evidence_records"][0]["verified"] is False

    completed = store.update(
        task["id"],
        {"status": "verified_complete", "humanVerified": True},
        actor="operator",
    )
    assert completed["status"] == "verified_complete"
    assert completed["human_verified"] is True
    assert completed["completed_at"] is not None
    assert completed["evidence_records"] == awaiting_review["evidence_records"]


def test_verified_evidence_completes_task_and_is_immutable_audit_record(tmp_path):
    store = DrawingBoardStore(tmp_path / "drawing-board.sqlite3")
    task = store.create(
        _actionable_payload("Validate Texas partial-tax test", status="in_progress")
    )

    completed = store.add_evidence(
        task["id"],
        summary="$100 controlled invoice produced an $80 taxable base.",
        evidence_kind="billing_test",
        source_url="https://example.test/audit/tx-100",
        verified=True,
        created_by="operator",
    )

    assert completed["status"] == "verified_complete"
    assert completed["completed_at"] is not None
    assert completed["evidence_records"] == [
        {
            **completed["evidence_records"][0],
            "evidence_kind": "billing_test",
            "summary": "$100 controlled invoice produced an $80 taxable base.",
            "source_url": "https://example.test/audit/tx-100",
            "verified": True,
            "created_by": "operator",
        }
    ]
    assert [event["action"] for event in store.history(task["id"])] == [
        "created",
        "evidence_added",
    ]


def test_dispatch_updates_lane_and_deduplicates_dispatch_record(tmp_path):
    store = DrawingBoardStore(tmp_path / "drawing-board.sqlite3")
    task = store.create(_actionable_payload(status="ready"))

    store.record_dispatch(
        task["id"],
        job_key="job-key-1",
        bridge_job_id=42,
        agent_name="tickets_agent",
    )
    store.record_dispatch(
        task["id"],
        job_key="job-key-1",
        bridge_job_id=42,
        agent_name="tickets_agent",
    )

    dispatched = store.get(task["id"])
    assert dispatched is not None
    assert dispatched["status"] == "in_progress"
    assert len(dispatched["dispatches"]) == 1


def test_brief_reports_due_soon_waiting_and_evidence_lanes(tmp_path):
    store = DrawingBoardStore(tmp_path / "drawing-board.sqlite3")
    now = datetime.now(UTC)
    store.create(_actionable_payload("Due today", status="ready", dueAt=(now + timedelta(hours=3)).isoformat()))
    store.create(_actionable_payload("Waiting on Finance", status="waiting", sourceId="finance-thread"))
    store.create(_actionable_payload("Needs proof attached", status="evidence_required", sourceId="job-7"))
    store.create(
        {
            "title": "Already done",
            "status": "verified_complete",
            "humanVerified": True,
        }
    )

    brief = store.brief(now=now.timestamp())

    assert brief["counts"] == {
        "active": 3,
        "drafts": 0,
        "due_soon": 1,
        "stale": 0,
        "waiting": 1,
        "evidence_required": 1,
        "verified_complete": 1,
    }
    assert [task["title"] for task in brief["due_soon"]] == ["Due today"]


def test_vague_draft_cannot_enter_an_active_lane_or_dispatch(tmp_path):
    store = DrawingBoardStore(tmp_path / "drawing-board.sqlite3")
    draft = store.create(
        {
            "title": "Map Maxio tax output into the corporate tax reporting system",
            "agentName": "billing_agent",
            "nextAction": "Send to Jamie",
        }
    )

    assert draft["status"] == "drawing"
    assert draft["actionable"] is False
    assert set(draft["missing_actionability_fields"]) >= {
        "business_request",
        "requested_outcome",
        "assignee_action",
        "source_or_evidence",
        "completion_criteria",
    }
    with pytest.raises(ValueError, match="brief is not actionable"):
        store.update(draft["id"], {"status": "ready"})
    with pytest.raises(ValueError, match="must be ready before dispatch"):
        store.record_dispatch(
            draft["id"],
            job_key="job-vague",
            bridge_job_id=17,
            agent_name="billing_agent",
        )


def test_incomplete_card_can_be_dismissed_without_false_completion(tmp_path):
    store = DrawingBoardStore(tmp_path / "drawing-board.sqlite3")
    draft = store.create({"title": "Unclear imported assignment"})

    dismissed = store.update(draft["id"], {"status": "archived"}, actor="operator")

    assert dismissed["status"] == "archived"
    assert dismissed["human_verified"] is False
    assert dismissed["completed_at"] is None
    assert store.list_tasks() == []
    assert store.list_tasks(statuses=["archived"])[0]["id"] == draft["id"]


def test_operator_reminder_needs_only_a_clear_title_and_owner(tmp_path):
    store = DrawingBoardStore(tmp_path / "drawing-board.sqlite3")

    task = store.create(
        {
            "title": "Complete team one-on-ones",
            "owner": "Darius",
            "operatorOwned": True,
            "status": "ready",
            "dueAt": "2026-07-17T17:00:00-04:00",
        }
    )

    assert task["actionable"] is True
    assert task["status"] == "ready"
    assert task["agent_name"] == ""
    completed = store.update(
        task["id"],
        {"status": "verified_complete", "humanVerified": True},
        actor="Darius",
    )
    assert completed["status"] == "verified_complete"


@pytest.mark.parametrize(
    "marker",
    [
        {"sourceType": "status_telemetry"},
        {"taskKind": "agent_failure"},
        {"outcomeStatus": "blocked"},
    ],
)
def test_failure_blocker_and_status_telemetry_are_rejected_at_admission(tmp_path, marker):
    store = DrawingBoardStore(tmp_path / "drawing-board.sqlite3")

    with pytest.raises(ValueError, match="not failures, blockers, or status telemetry"):
        store.create({**_actionable_payload(), **marker})


def test_only_successful_agent_result_advances_to_evidence_review(tmp_path):
    runtime = object.__new__(CommandCenterRuntime)
    runtime.drawing_board = DrawingBoardStore(tmp_path / "drawing-board.sqlite3")
    runtime.config = SimpleNamespace(agents={"tickets_agent": {}})
    task = runtime.drawing_board.create(_actionable_payload(status="ready"))
    captured = {}

    def fake_submit_prompt(**kwargs):
        captured.update(kwargs)
        return {"accepted": True, "job_id": "job-42", "bridge_job_id": 42}

    runtime.submit_prompt = fake_submit_prompt
    dispatched = runtime.drawing_board_dispatch({"taskId": task["id"]})

    assert dispatched["task"]["status"] == "in_progress"
    assert "Business request:" in captured["prompt"]
    assert "Required outcome:" in captured["prompt"]
    assert "Your expected action:" in captured["prompt"]
    assert "Completion criteria:" in captured["prompt"]

    runtime._sync_drawing_board_after_job(
        {"drawingBoardTaskId": task["id"]},
        "tickets_agent",
        "BLOCKED: source records were unavailable",
        "job-42",
    )
    blocked = runtime.drawing_board.get(task["id"])
    assert blocked["status"] == "in_progress"
    assert blocked["evidence_records"] == []

    runtime._sync_drawing_board_after_job(
        {"drawingBoardTaskId": task["id"]},
        "tickets_agent",
        "COMPLETED: reconciled source records are attached",
        "job-42",
    )
    ready_for_proof = runtime.drawing_board.get(task["id"])
    assert ready_for_proof["status"] == "waiting"
    assert len(ready_for_proof["evidence_records"]) == 1


def test_completed_task_can_return_to_todo_and_clears_completion_flag(tmp_path):
    store = DrawingBoardStore(tmp_path / "drawing-board.sqlite3")
    task = store.create(_actionable_payload(status="ready"))
    completed = store.update(
        task["id"],
        {"status": "verified_complete", "humanVerified": True},
        actor="Darius",
    )

    returned = store.update(completed["id"], {"status": "ready"}, actor="Darius")

    assert returned["status"] == "ready"
    assert returned["human_verified"] is False
    assert returned["completed_at"] is None
    assert returned["evidence_records"] == completed["evidence_records"]


def test_successful_agent_job_attaches_registered_work_products(tmp_path):
    runtime = object.__new__(CommandCenterRuntime)
    runtime.bridge_root = tmp_path
    runtime.drawing_board = DrawingBoardStore(tmp_path / "data" / "drawing-board.sqlite3")
    runtime.config = SimpleNamespace(
        agents={"tickets_agent": {}},
        defaults={
            "artifact_index_path": "data/agent_artifacts/index.jsonl",
            "agent_sandbox_root": "data/agent_sandboxes",
        },
    )
    task = runtime.drawing_board.create(_actionable_payload(status="ready"))
    runtime.drawing_board.record_dispatch(
        task["id"],
        job_key="job-42",
        bridge_job_id=42,
        agent_name="tickets_agent",
    )
    work_product = tmp_path / "data" / "agent_sandboxes" / "tickets_agent" / "quality-review.docx"
    work_product.parent.mkdir(parents=True)
    work_product.write_bytes(b"synthetic work product")
    index_path = tmp_path / "data" / "agent_artifacts" / "index.jsonl"
    artifact_id = register_artifact(
        index_path=index_path,
        file_path=work_product,
        agent_name="tickets_agent",
        source="command_center",
        purpose="sandbox-output",
        job_id="42",
    )

    runtime._sync_drawing_board_after_job(
        {"drawingBoardTaskId": task["id"]},
        "tickets_agent",
        "COMPLETED: quality review is ready",
        "job-42",
    )

    updated = runtime.drawing_board.get(task["id"])
    assert updated["status"] == "waiting"
    assert [item["evidence_kind"] for item in updated["evidence_records"]] == [
        "agent_report",
        "work_product",
    ]
    attachment = updated["evidence_records"][1]
    assert attachment["external_id"] == artifact_id
    assert attachment["source_url"] == f"/ops/drawing-board/artifacts/{artifact_id}"
    resolved, name, content_type = runtime.drawing_board_artifact(str(artifact_id))
    assert resolved == work_product.resolve()
    assert name == "quality-review.docx"
    assert content_type


def test_startup_demotes_legacy_nonactionable_active_card_to_draft(tmp_path):
    path = tmp_path / "drawing-board.sqlite3"
    store = DrawingBoardStore(path)
    task = store.create({"title": "Send to Jamie"})
    with store._connect() as db:
        db.execute("UPDATE drawing_board_tasks SET status='ready' WHERE id=?", (task["id"],))

    reconciled = DrawingBoardStore(path).get(task["id"])

    assert reconciled["status"] == "drawing"
    assert reconciled["actionable"] is False
    assert store.history(task["id"])[-1]["action"] == "actionability_demoted"


@pytest.mark.parametrize("field,value", [("status", "done-ish"), ("priority", "critical")])
def test_create_rejects_unknown_lane_values(tmp_path, field, value):
    store = DrawingBoardStore(tmp_path / "drawing-board.sqlite3")

    with pytest.raises(ValueError):
        store.create({"title": "Bad task", field: value})


def test_digest_watcher_submits_once_per_local_weekday(tmp_path, monkeypatch):
    runtime = object.__new__(CommandCenterRuntime)
    runtime.config = SimpleNamespace(
        defaults={
            "drawing_board_digest_timezone": "America/New_York",
            "drawing_board_digest_weekdays_only": True,
            "drawing_board_digest_local_time": "09:15",
        }
    )
    runtime.drawing_board_digest_state_path = tmp_path / "drawing-board-digest.json"
    runtime._active_source_type = lambda _source_type: False
    submissions = []

    def fake_submit(*, idempotency_key=""):
        submissions.append(idempotency_key)
        return {"accepted": True, "job_id": "job-123"}

    runtime.submit_drawing_board_digest = fake_submit
    monkeypatch.setattr(
        command_center_server,
        "_schedule_watch_local_now",
        lambda _timezone_name: datetime(2026, 7, 13, 9, 15, tzinfo=UTC),
    )

    runtime._submit_drawing_board_digest_if_due(900)
    runtime._submit_drawing_board_digest_if_due(900)

    assert submissions == ["drawing-board-digest:2026-07-13"]
    state = json.loads(runtime.drawing_board_digest_state_path.read_text(encoding="utf-8"))
    assert state["lastDigestLocalDate"] == "2026-07-13"
    assert state["jobId"] == "job-123"


@pytest.mark.parametrize(
    "local_now",
    [
        datetime(2026, 7, 13, 9, 14, tzinfo=UTC),
        datetime(2026, 7, 11, 10, 0, tzinfo=UTC),
    ],
)
def test_digest_watcher_skips_before_due_time_and_on_weekends(tmp_path, monkeypatch, local_now):
    runtime = object.__new__(CommandCenterRuntime)
    runtime.config = SimpleNamespace(
        defaults={
            "drawing_board_digest_timezone": "America/New_York",
            "drawing_board_digest_weekdays_only": True,
            "drawing_board_digest_local_time": "09:15",
        }
    )
    runtime.drawing_board_digest_state_path = tmp_path / "drawing-board-digest.json"
    runtime._active_source_type = lambda _source_type: False
    runtime.submit_drawing_board_digest = lambda **_kwargs: pytest.fail("digest should not submit")
    monkeypatch.setattr(
        command_center_server,
        "_schedule_watch_local_now",
        lambda _timezone_name: local_now,
    )

    runtime._submit_drawing_board_digest_if_due(900)

    assert not runtime.drawing_board_digest_state_path.exists()
