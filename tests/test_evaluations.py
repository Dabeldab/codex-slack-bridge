from __future__ import annotations

from pathlib import Path

from codex_slack_bridge.evaluations import append_feedback, run_evaluations


def test_agent_quality_golden_cases_pass():
    root = Path(__file__).resolve().parents[1]
    result = run_evaluations(root / "config" / "agents.yaml", root / "evals" / "agent_quality.json")
    assert result["ok"] is True, result
    assert result["failed"] == 0


def test_feedback_log_accepts_only_bounded_categories(tmp_path):
    path = tmp_path / "feedback.jsonl"
    append_feedback(path, case_name="case", category="too_slow", note="queued too long")
    assert '"category": "too_slow"' in path.read_text(encoding="utf-8")
