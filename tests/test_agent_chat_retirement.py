# AgentChat/direct_codex 2026-07-17T17:32:53-04:00: verify the desktop client stays retired while Command Center mirroring remains.
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def _config(path: str) -> dict:
    return yaml.safe_load((ROOT / path).read_text(encoding="utf-8"))


def test_desktop_agent_chat_launch_and_build_fail_closed() -> None:
    for relative_path in ("scripts/start-agent-chat.ps1", "scripts/build-agent-chat.ps1"):
        script = (ROOT / relative_path).read_text(encoding="utf-8")
        assert 'throw "Agent Chat Desktop is retired.' in script
        assert "Start-Process" not in script
        assert "dotnet publish" not in script


def test_only_command_center_events_are_mirrored_to_slack() -> None:
    for relative_path in ("config/agents.yaml", "config/agents.example.yaml"):
        defaults = _config(relative_path)["defaults"]
        assert defaults["desktop_slack_mirror_enabled"] is True
        assert defaults["desktop_slack_mirror_sources"] == ["command_center"]


def test_readme_no_longer_advertises_desktop_launch() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "The standalone Agent Chat desktop client is retired." in readme
    assert "powershell -ExecutionPolicy Bypass -File .\\scripts\\start-agent-chat.ps1" not in readme
