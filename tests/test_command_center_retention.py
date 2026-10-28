from __future__ import annotations

import json
import os
from pathlib import Path
from threading import Lock
from types import SimpleNamespace

import pytest

from codex_slack_bridge.command_center_server import CommandCenterRuntime


def test_terminal_job_projection_retention_preserves_active_jobs_and_writes_receipt(tmp_path: Path) -> None:
    runtime = CommandCenterRuntime.__new__(CommandCenterRuntime)
    runtime.jobs_dir = tmp_path / "jobs"
    runtime.jobs_dir.mkdir()
    runtime.command_center_data_root = tmp_path / "command-center"
    runtime.config = SimpleNamespace(
        defaults={
            "command_center_job_retention_count": 100,
            "command_center_job_retention_days": 30_000,
        }
    )
    runtime._lock = Lock()
    runtime._jobs = {}
    runtime._last_job_cleanup_at_monotonic = 0.0

    for index in range(105):
        job_id = f"terminal-{index:03d}"
        record = {"id": job_id, "status": "completed"}
        path = runtime.jobs_dir / f"{job_id}.json"
        path.write_text(json.dumps(record), encoding="utf-8")
        os.utime(path, (1_700_000_000 + index, 1_700_000_000 + index))
        runtime._jobs[job_id] = record

    active_id = "queued-preserved"
    active = {"id": active_id, "status": "queued"}
    active_path = runtime.jobs_dir / f"{active_id}.json"
    active_path.write_text(json.dumps(active), encoding="utf-8")
    os.utime(active_path, (1_600_000_000, 1_600_000_000))
    runtime._jobs[active_id] = active

    result = runtime._cleanup_terminal_job_files(force=True)

    assert result["removedFiles"] == 5
    assert active_path.exists()
    assert runtime._jobs[active_id]["status"] == "queued"
    assert len(list(runtime.jobs_dir.glob("*.json"))) == 101
    receipt = runtime.command_center_data_root / "cleanup" / "command_center_retention.jsonl"
    assert json.loads(receipt.read_text(encoding="utf-8").splitlines()[-1])["removedFiles"] == 5


def test_handoff_attachment_paths_are_staged_from_source_lane_only(tmp_path: Path) -> None:
    runtime = CommandCenterRuntime.__new__(CommandCenterRuntime)
    workspace = tmp_path / "workspaces" / "jamie"
    workspace.mkdir(parents=True)
    runtime.bridge_root = tmp_path
    runtime.agent_chat_attachment_root = tmp_path / "attachments"
    runtime.agent_chat_attachment_root.mkdir()
    runtime.config = SimpleNamespace(
        defaults={"agent_sandbox_root": str(tmp_path / "sandboxes")},
        agents={"billing_agent": {"workspace_root": str(workspace)}},
    )
    source = workspace / "Cancellation NOVA.pdf"
    source.write_bytes(b"%PDF-1.7\nverified cancellation\n%%EOF")

    staged = runtime._stage_handoff_attachment_paths("billing_agent", [str(source)])

    assert len(staged) == 1
    assert staged[0]["name"] == source.name
    assert staged[0]["kind"] == "file"
    assert runtime._resolve_agent_chat_attachments({"attachments": staged})[0]["sha256"] == staged[0]["sha256"]

    escaped = tmp_path / "outside.pdf"
    escaped.write_bytes(b"%PDF-1.7\noutside\n%%EOF")
    with pytest.raises(ValueError, match="escaped the source lane workspace"):
        runtime._stage_handoff_attachment_paths("billing_agent", [str(escaped)])


def test_handoff_stages_sql_plan_as_verified_plain_text(tmp_path: Path) -> None:
    runtime = CommandCenterRuntime.__new__(CommandCenterRuntime)
    workspace = tmp_path / "workspaces" / "alex"
    workspace.mkdir(parents=True)
    runtime.bridge_root = tmp_path
    runtime.agent_chat_attachment_root = tmp_path / "attachments"
    runtime.agent_chat_attachment_root.mkdir()
    runtime.config = SimpleNamespace(
        defaults={"agent_sandbox_root": str(tmp_path / "sandboxes")},
        agents={"tickets_agent": {"workspace_root": str(workspace)}},
    )
    source = workspace / "account_copy_plan.sql"
    source.write_text("SELECT COUNT_BIG(*) FROM dbo.Products;\n", encoding="utf-8")

    staged = runtime._stage_handoff_attachment_paths("tickets_agent", [str(source)])

    assert len(staged) == 1
    assert staged[0]["name"] == source.name
    assert staged[0]["mimetype"] == "text/plain"
    resolved = runtime._resolve_agent_chat_attachments({"attachments": staged})
    assert resolved[0]["extension"] == ".sql"
    assert resolved[0]["sha256"] == staged[0]["sha256"]
