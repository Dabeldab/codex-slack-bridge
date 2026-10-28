"""Offline worker regressions. Every process and response is a synthetic fixture."""
from __future__ import annotations

import json
import subprocess
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from codex_slack_bridge import agents
from codex_slack_bridge.codex_failure import classify_codex_failure, codex_failure_summary


def process_fixture(monkeypatch, tmp_path, *, timed_out=False, final_message="", stdout="", stderr="", returncode=0):
    process = Mock(pid=12345, returncode=returncode)
    if timed_out:
        process.communicate.side_effect = subprocess.TimeoutExpired("fixture", 1, output=stdout.encode(), stderr=stderr.encode())
    else:
        process.communicate.return_value = (stdout.encode(), stderr.encode())
    monkeypatch.setattr(agents.subprocess, "Popen", Mock(return_value=process))
    monkeypatch.setattr(agents, "Thread", Mock())
    monkeypatch.setattr(agents, "_register_agent_process", Mock())
    cleanup = Mock()
    monkeypatch.setattr(agents, "_unregister_agent_process", cleanup)
    monkeypatch.setattr(agents, "_terminate_and_collect_bounded", Mock(return_value=(stdout.encode(), stderr.encode())))
    monkeypatch.setattr(agents, "_read_output_file", Mock(return_value=final_message))
    trace = Mock()
    monkeypatch.setattr(agents, "_write_process_trace", trace)
    result = agents.run_codex_process(["fixture", "__output_path=" + str(tmp_path / "final.txt")], tmp_path, "synthetic task", 1, job_id=42, attempt=2)
    cleanup.assert_called_once_with(42, process)
    return result, trace


@pytest.mark.parametrize("partial", ["", "Partial fixture response."])
def test_timeout_is_incomplete(monkeypatch, tmp_path, partial):
    result, trace = process_fixture(monkeypatch, tmp_path, timed_out=True, final_message=partial)
    assert result.timed_out
    assert result.returncode is None
    assert result.final_message == partial
    assert result.usage == {}
    assert "timed out" in result.final_text
    assert trace.call_args.kwargs["returncode"] is None
    assert trace.call_args.kwargs["timed_out"] is True
    assert trace.call_args.kwargs["job_id"] == 42
    assert trace.call_args.kwargs["attempt"] == 2


def test_timeout_preserves_drained_usage(monkeypatch, tmp_path):
    stdout = '\n'.join([json.dumps({"type": "thread.started", "thread_id": "fixture-session"}), json.dumps({"type": "turn.completed", "usage": {"input_tokens": 9, "output_tokens": 3}})])
    result, _ = process_fixture(monkeypatch, tmp_path, timed_out=True, stdout=stdout)
    assert result.session_id == "fixture-session"
    assert result.usage["input_tokens"] == 9
    assert result.usage["output_tokens"] == 3
    assert result.returncode is None


def test_success_is_unchanged(monkeypatch, tmp_path):
    result, trace = process_fixture(monkeypatch, tmp_path, final_message="Fixture complete")
    assert result.returncode == 0
    assert result.final_text == "Fixture complete"
    assert not result.timed_out
    assert trace.call_args.kwargs["job_id"] == 42


def test_stdout_failure_is_not_hidden_by_stderr_warning(monkeypatch, tmp_path):
    result, _ = process_fixture(monkeypatch, tmp_path, returncode=1, stderr="startup warning", stdout="unsupported model fixture")
    assert "category=model_unavailable" in result.final_text
    assert "fixture" not in result.final_text


@pytest.mark.parametrize("returncode", [0, None, 1])
def test_caller_stops_timeout_before_retry(monkeypatch, tmp_path, returncode):
    request = agents.AgentRequest(text="synthetic request", channel_id="test", user_id="test", thread_ts="test", job_id=42)
    result = agents.CodexProcessResult(final_text="partial", returncode=returncode, stdout="", stderr="quota exhausted", session_id="", timed_out=True)
    run = Mock(return_value=result)
    monkeypatch.setattr(agents, "run_codex_process", run)
    monkeypatch.setattr(agents, "_require_request_authority", Mock(return_value=SimpleNamespace(operator_authorized=True)))
    monkeypatch.setattr(agents, "build_child_process_env", Mock(return_value=({}, None)))
    monkeypatch.setattr(agents, "_codex_fallback_home", Mock(return_value="fixture-fallback"))
    monkeypatch.setattr(agents, "persistent_sessions_enabled", Mock(return_value=False))
    monkeypatch.setattr(agents, "build_codex_command", Mock(return_value=["fixture"]))
    monkeypatch.setattr(agents, "record_agent_usage", Mock())
    with pytest.raises(RuntimeError, match="category=worker_timeout"):
        agents.run_codex_cli("tickets_agent", {"workspace_root": str(tmp_path)}, request, direct_session=True)
    assert run.call_count == 1
    assert run.call_args.kwargs["attempt"] == 1


@pytest.mark.parametrize("details,category", [
    ("unexpected argument --fixture", "cli_argument_error"),
    ("unsupported model fixture", "model_unavailable"),
    ("authentication failed", "authentication_error"),
    ("quota exhausted", "usage_limit"),
    ("context window exceeded", "context_limit"),
    ("session not found", "session_unavailable"),
    ("error loading config", "configuration_error"),
    ("connection refused", "transport_error"),
    ("timed out waiting for cloud config bundle after 15s", "cloud_config_timeout"),
    ("unrecognized failure", "worker_exit"),
])
def test_categories_do_not_echo_raw_diagnostics(details, category):
    result = codex_failure_summary(1, details + " example-diagnostic-marker")
    assert "category=" + category in result
    assert "example-diagnostic-marker" not in result
    assert "discarded" not in result


def test_timeout_category_overrides_incidental_text():
    assert classify_codex_failure(None, "quota exhausted", timed_out=True) == "worker_timeout"


def test_signal_category():
    assert classify_codex_failure(-9, "") == "worker_signal"


def test_trace_correlation(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_RUN_TRACE_DIR", str(tmp_path))
    monkeypatch.setenv("K_REVISION", "nova-test-00001")
    agents._write_process_trace(provider="codex", workspace=tmp_path, command=["codex"], returncode=None, stdout="", stderr="", final_message="", job_id=42, attempt=3, timed_out=True)
    record = json.loads(next(tmp_path.glob("*.jsonl")).read_text().splitlines()[0])
    assert record["jobId"] == 42
    assert record["attempt"] == 3
    assert record["servingRevision"] == "nova-test-00001"
    assert record["failureCategory"] == "worker_timeout"
    assert record["returncode"] is None


def test_trace_write_failure_is_observable(monkeypatch, tmp_path, caplog):
    path = tmp_path / "not-a-directory"
    path.write_text("fixture")
    monkeypatch.setenv("AGENT_RUN_TRACE_DIR", str(path / "child"))
    agents._write_process_trace(provider="codex", workspace=tmp_path, command=[], returncode=1, stdout="", stderr="", final_message="")
    assert "agent_process_trace_write_failed" in caplog.text
