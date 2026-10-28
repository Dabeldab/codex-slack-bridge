from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from codex_slack_bridge.agents import AGENT_FILE_DELIVERY_CONTRACT, AgentRequest, build_static_prompt
from codex_slack_bridge.app import _upload_directed_files
from codex_slack_bridge.command_center_server import (
    CommandCenterRuntime,
    _read_direct_agent_chat_events,
)
from codex_slack_bridge.shared_chat import append_chat_event


def _runtime(tmp_path: Path) -> tuple[CommandCenterRuntime, dict[str, object], Path]:
    runtime = object.__new__(CommandCenterRuntime)
    runtime.bridge_root = tmp_path
    sandbox = tmp_path / "sandboxes" / "coding_agent"
    sandbox.mkdir(parents=True)
    defaults = {
        "agent_sandbox_root": str(tmp_path / "sandboxes"),
        "agent_file_return_max_mb": 25,
        "artifact_index_path": str(tmp_path / "artifacts.jsonl"),
    }
    runtime.config = SimpleNamespace(
        defaults=defaults,
        agents={"coding_agent": {"signature": "AgentChat/coding_agent"}},
    )
    agent = {**defaults, **runtime.config.agents["coding_agent"]}
    return runtime, agent, sandbox


def _request(job_id: int = 42) -> AgentRequest:
    return AgentRequest(
        text="Make the report and send it back.",
        channel_id="command_center",
        user_id="operator",
        thread_ts="cc-job",
        job_id=job_id,
        surface="agent_chat",
        conversation_id="command_center:coding_agent",
    )


def test_every_agent_prompt_receives_the_file_delivery_contract(tmp_path: Path) -> None:
    assert "BRIDGE_UPLOAD_FILE" in AGENT_FILE_DELIVERY_CONTRACT
    assert "Preserve the original attachment" in AGENT_FILE_DELIVERY_CONTRACT
    assert "BRIDGE_UPLOAD_FILE" in build_static_prompt(
        "coding_agent",
        "You are Taylor.",
        {"name": "coding_agent", "workspace_root": str(tmp_path)},
    )


def test_command_center_returns_verified_file_and_reuses_idempotent_receipt(tmp_path: Path) -> None:
    runtime, agent, sandbox = _runtime(tmp_path)
    report = sandbox / "Account Review.csv"
    report.write_text("Account,Total\nNova Cafe,10.00\n", encoding="utf-8")
    result = f"COMPLETED\nThe report is attached.\nBRIDGE_UPLOAD_FILE: {report}"

    clean, attachments = runtime._prepare_agent_file_delivery(
        "coding_agent", agent, _request(), result
    )
    repeated_clean, repeated = runtime._prepare_agent_file_delivery(
        "coding_agent", agent, _request(), result
    )

    assert clean == "COMPLETED\nThe report is attached."
    assert repeated_clean == clean
    assert len(attachments) == 1
    assert repeated[0]["id"] == attachments[0]["id"]
    assert attachments[0]["downloadUrl"].endswith(attachments[0]["id"])
    resolved, name, mimetype = runtime.agent_chat_artifact(attachments[0]["id"])
    assert resolved == report.resolve()
    assert name == "Account Review.csv"
    assert mimetype == "text/csv"


def test_command_center_blocks_file_outside_output_roots_and_marks_issue(tmp_path: Path) -> None:
    runtime, agent, _sandbox = _runtime(tmp_path)
    private = tmp_path / "private.env"
    private.write_text("SECRET=value", encoding="utf-8")

    clean, attachments = runtime._prepare_agent_file_delivery(
        "coding_agent",
        agent,
        _request(),
        f"COMPLETED\nDone.\nBRIDGE_UPLOAD_FILE: {private}",
    )

    assert attachments == []
    assert clean.startswith("COMPLETED_WITH_ISSUES")
    assert "outside the approved agent output directories" in clean
    assert "SECRET=value" not in clean


def test_returned_files_round_trip_through_direct_chat_projection(tmp_path: Path) -> None:
    chat_path = tmp_path / "events.jsonl"
    jobs_dir = tmp_path / "jobs"
    jobs_dir.mkdir()
    (jobs_dir / "cc-job.json").write_text(
        json.dumps({"id": "cc-job", "sourceType": "agent-direct-chat"}),
        encoding="utf-8",
    )
    attachment_id = "a" * 32
    append_chat_event(
        path=chat_path,
        source="command_center",
        agent_name="coding_agent",
        role="assistant",
        text="COMPLETED\nAttached.",
        job_id="42",
        thread_ts="cc-job",
        attachments=[
            {
                "id": attachment_id,
                "name": "finished.xlsx",
                "mimetype": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                "size": 321,
                "sha256": "b" * 64,
                "kind": "file",
                "path": "must-not-leak",
            }
        ],
    )

    events = _read_direct_agent_chat_events(
        path=chat_path,
        jobs_dir=jobs_dir,
        agent_name="coding_agent",
        limit=20,
    )

    assert events[0]["attachments"][0]["downloadUrl"] == f"/agent-chat/artifacts/{attachment_id}"
    assert "path" not in events[0]["attachments"][0]


def test_command_center_accepts_signature_checked_legacy_excel_input(tmp_path: Path) -> None:
    runtime = object.__new__(CommandCenterRuntime)
    runtime.agent_chat_attachment_root = tmp_path.resolve()
    runtime.agent_chat_attachment_root.mkdir(parents=True, exist_ok=True)
    body = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"legacy workbook"

    public = runtime.store_agent_chat_attachment(
        body,
        content_type="application/vnd.ms-excel",
        name="original.xls",
    )

    assert public["name"] == "original.xls"
    assert runtime._resolve_agent_chat_attachments({"attachments": [public]})[0]["sha256"]


class _SlackClient:
    def __init__(self) -> None:
        self.uploads: list[dict[str, object]] = []
        self.readbacks: list[str] = []

    def files_upload_v2(self, **kwargs):
        self.uploads.append(kwargs)
        return {"ok": True, "files": [{"id": "F123"}]}

    def files_info(self, *, file: str):
        self.readbacks.append(file)
        return {"ok": True, "file": {"id": file}}


class _SlackSdkResponseLike:
    def __init__(self, data: dict[str, object]) -> None:
        self.data = data

    def __iter__(self):
        return iter(self.data)


class _SlackSdkResponseClient(_SlackClient):
    def files_upload_v2(self, **kwargs):
        self.uploads.append(kwargs)
        return _SlackSdkResponseLike({"ok": True, "files": [{"id": "F456"}]})

    def files_info(self, *, file: str):
        self.readbacks.append(file)
        return _SlackSdkResponseLike({"ok": True, "file": {"id": file}})


def test_slack_returns_file_in_originating_thread_with_readback(tmp_path: Path) -> None:
    output = tmp_path / "generated"
    output.mkdir()
    report = output / "report.csv"
    report.write_text("a,b\n1,2\n", encoding="utf-8")
    config = SimpleNamespace(
        defaults={
            "slack_file_uploads_enabled": True,
            "slack_file_max_uploads_per_response": 5,
            "slack_file_max_upload_mb": 25,
            "slack_file_upload_allowed_roots": [str(output)],
            "slack_file_output_dir": str(output),
            "slack_file_download_dir": str(tmp_path / "downloads"),
            "artifact_index_path": str(tmp_path / "artifacts.jsonl"),
        }
    )
    client = _SlackClient()
    request = AgentRequest(
        text="send the report",
        channel_id="C123",
        user_id="U123",
        thread_ts="123.456",
        job_id=91,
    )

    notes = _upload_directed_files(
        config,
        "coding_agent",
        {"workspace_root": str(output), "signature": "AgentChat/coding_agent"},
        client,
        request,
        [str(report)],
    )

    assert notes == ["Uploaded file: `report.csv` (verified `F123`)"]
    assert client.uploads[0]["thread_ts"] == "123.456"
    assert client.readbacks == ["F123"]


def test_slack_sdk_response_object_is_normalized_before_readback(tmp_path: Path) -> None:
    output = tmp_path / "generated"
    output.mkdir()
    report = output / "report.csv"
    report.write_text("a,b\n1,2\n", encoding="utf-8")
    config = SimpleNamespace(
        defaults={
            "slack_file_uploads_enabled": True,
            "slack_file_max_uploads_per_response": 5,
            "slack_file_max_upload_mb": 25,
            "slack_file_upload_allowed_roots": [str(output)],
            "slack_file_output_dir": str(output),
            "slack_file_download_dir": str(tmp_path / "downloads"),
            "artifact_index_path": str(tmp_path / "artifacts.jsonl"),
        }
    )
    client = _SlackSdkResponseClient()
    request = AgentRequest(
        text="send the report",
        channel_id="C123",
        user_id="U123",
        thread_ts="123.456",
        job_id=92,
    )

    notes = _upload_directed_files(
        config,
        "direct_codex",
        {"workspace_root": str(output), "signature": "AgentChat/direct_codex"},
        client,
        request,
        [str(report)],
    )

    assert notes == ["Uploaded file: `report.csv` (verified `F456`)"]
    assert client.readbacks == ["F456"]


def test_file_delivery_is_registered_for_every_lane() -> None:
    root = Path(__file__).resolve().parents[1]
    registry = json.loads((root / "config/tool-fast-paths.json").read_text(encoding="utf-8"))
    tool = registry["tools"]["agent_file_delivery"]
    assert set(tool["primary_agents"]) == {
        "direct_codex",
        "raw_codex",
        "tickets_agent",
        "billing_agent",
        "coding_agent",
        "claude_agent",
    }
    capability_text = (root / "config/agent-capabilities.yaml").read_text(encoding="utf-8")
    assert capability_text.count("artifact.file_return_verified") == 6
    preflight = (root / "deploy/gcp/agent-runtime/preflight.py").read_text(encoding="utf-8")
    assert '"agent_file_delivery": _probe_agent_file_delivery' in preflight
    assert '"agent_file_delivery")' in preflight
    for dependency in ("PIL", "docx", "fitz", "openpyxl", "pptx", "pypdf"):
        assert f'"{dependency}"' in preflight
