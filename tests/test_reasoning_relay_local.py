from pathlib import Path

import pytest

from codex_slack_bridge.reasoning_relay_local import LocalWorkspaceBroker


def make_broker(tmp_path: Path, lane: str = "coding_agent") -> LocalWorkspaceBroker:
    workspace = tmp_path / "work"
    workspace.mkdir()
    return LocalWorkspaceBroker(lane=lane, agent={"workspace_root": str(workspace), "agent_sandbox_root": str(tmp_path / "sandboxes")}, child_env={})


def test_local_broker_reads_and_writes_only_with_authority(tmp_path):
    broker = make_broker(tmp_path)
    root = tmp_path / "work"
    (root / "hello.txt").write_text("hello world", encoding="utf-8")
    assert broker.execute("read_text", {"path": "hello.txt"}, allow_write=False)["text"] == "hello world"
    with pytest.raises(PermissionError):
        broker.execute("write_text", {"path": "new.txt", "content": "x"}, allow_write=False)
    assert broker.execute("write_text", {"path": "new.txt", "content": "x"}, allow_write=True)["ok"] is True


def test_local_broker_blocks_secret_paths(tmp_path):
    broker = make_broker(tmp_path)
    root = tmp_path / "work"
    (root / ".env").write_text("SECRET=x", encoding="utf-8")
    with pytest.raises(PermissionError):
        broker.execute("read_text", {"path": ".env"}, allow_write=False)


def test_specialist_cannot_write_workspace(tmp_path):
    broker = make_broker(tmp_path, lane="tickets_agent")
    with pytest.raises(PermissionError):
        broker.execute("write_text", {"path": "x.txt", "content": "x"}, allow_write=True)
