from pathlib import Path

from codex_slack_bridge.agent_readiness import AgentProviderReadiness


def _agent():
    return {"claude_agent": {"provider": "codex_cli", "codex_executable": "/bin/codex"}}


def test_legacy_readiness_still_uses_codex_probe(monkeypatch):
    monkeypatch.delenv("REASONING_RELAY_ENABLED", raising=False)
    calls = []
    probe = AgentProviderReadiness(_agent(), executor=lambda cmd, timeout: calls.append(cmd) or 0, clock=lambda: 1000.0)
    result = probe.ensure_ready("claude_agent")
    assert result["provider"] == "codex_cli"
    assert result["ready"] is True
    assert calls == [["/bin/codex", "login", "status"]]


def test_explicit_relay_readiness_never_calls_codex(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("REASONING_RELAY_ENABLED", "true")
    for name in ("app-id", "install-id", "key.pem"):
        (tmp_path / name).write_text("x", encoding="utf-8")
    monkeypatch.setenv("GITHUB_APP_ID_PATH", str(tmp_path / "app-id"))
    monkeypatch.setenv("GITHUB_APP_INSTALLATION_ID_PATH", str(tmp_path / "install-id"))
    monkeypatch.setenv("GITHUB_APP_PRIVATE_KEY_PATH", str(tmp_path / "key.pem"))
    monkeypatch.setenv("GITHUB_ALLOWED_REPOSITORIES", "dariusmakesstuff/codex-slack-bridge")
    calls = []
    probe = AgentProviderReadiness(_agent(), executor=lambda cmd, timeout: calls.append(cmd) or 0, clock=lambda: 1000.0)
    result = probe.ensure_ready_for("claude_agent", "chatgpt_relay")
    assert result["provider"] == "chatgpt_relay"
    assert result["ready"] is True
    assert calls == []


def test_raw_codex_is_disabled_in_relay_mode(monkeypatch):
    monkeypatch.setenv("REASONING_RELAY_ENABLED", "true")
    probe = AgentProviderReadiness({"raw_codex": {"provider": "codex_cli_direct"}}, clock=lambda: 1000.0)
    result = probe.ensure_ready("raw_codex")
    assert result["provider"] == "disabled"
    assert result["status"] == "disabled"
    assert result["ready"] is False
