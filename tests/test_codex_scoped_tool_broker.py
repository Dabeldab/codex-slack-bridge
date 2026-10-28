from __future__ import annotations

import json
import os
import subprocess
import sys

from codex_slack_bridge.agents import _codex_mcp_config_overrides
from codex_slack_bridge.agent_worker import _bounded_tool_inventory
from codex_slack_bridge.codex_tool_broker import _BrokerTCPServer


class _FakeBroker:
    def list_tools(self, server: str, *, limit: int) -> dict:
        assert server == "salesforce_support_ops"
        assert limit == 100
        return {
            "tools": [
                {
                    "name": "salesforce_ticket_list_open",
                    "description": "bounded read",
                    "inputSchema": {"type": "object"},
                    "annotations": {"readOnlyHint": True},
                }
            ]
        }

    def execute(self, server: str, tool: str, arguments: dict, *, allow_write: bool) -> dict:
        assert server == "salesforce_support_ops"
        assert tool == "salesforce_ticket_list_open"
        assert arguments == {"limit": 5}
        assert allow_write is False
        return {"result": {"content": [{"type": "text", "text": "count=5"}]}}


def test_codex_proxy_forwards_only_to_ephemeral_parent_broker() -> None:
    import secrets
    import threading

    proof = secrets.token_urlsafe(24)
    server = _BrokerTCPServer(_FakeBroker(), proof=proof, allow_write=False)  # type: ignore[arg-type]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    env = dict(os.environ)
    env["NOVA_CODEX_BROKER_ENDPOINT"] = f"{host}:{port}"
    env["NOVA_CODEX_BROKER_PROOF"] = proof
    requests = "\n".join(
        [
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}),
            json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
            json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}),
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "tools/call",
                    "params": {"name": "salesforce_ticket_list_open", "arguments": {"limit": 5}},
                }
            ),
        ]
    ) + "\n"
    try:
        completed = subprocess.run(
            [sys.executable, "-m", "codex_slack_bridge.codex_mcp_proxy", "salesforce_support_ops"],
            input=requests,
            text=True,
            capture_output=True,
            env=env,
            timeout=10,
            check=True,
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
    responses = [json.loads(line) for line in completed.stdout.splitlines()]
    assert responses[1]["result"]["tools"][0]["name"] == "salesforce_ticket_list_open"
    assert responses[2]["result"]["content"][0]["text"] == "count=5"


def test_broker_cli_uses_the_same_scoped_parent_capability() -> None:
    import secrets
    import threading

    proof = secrets.token_urlsafe(24)
    server = _BrokerTCPServer(_FakeBroker(), proof=proof, allow_write=False)  # type: ignore[arg-type]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    env = dict(os.environ)
    env["NOVA_CODEX_BROKER_ENDPOINT"] = f"{host}:{port}"
    env["NOVA_CODEX_BROKER_PROOF"] = proof
    try:
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "codex_slack_bridge.codex_broker_cli",
                "call",
                "salesforce_support_ops",
                "salesforce_ticket_list_open",
                '{"limit":5}',
            ],
            text=True,
            capture_output=True,
            env=env,
            timeout=10,
            check=True,
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
    result = json.loads(completed.stdout)
    assert result["content"][0]["text"] == "count=5"


def test_parent_broker_filters_and_enforces_bounded_tool_inventory() -> None:
    import secrets
    import socket
    import threading

    proof = secrets.token_urlsafe(24)
    server = _BrokerTCPServer(
        _FakeBroker(),
        proof=proof,
        allow_write=False,
        allowed_tools={"salesforce_support_ops": {"different_tool"}},
    )  # type: ignore[arg-type]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    try:
        with socket.create_connection((host, port), timeout=5) as connection:
            reader = connection.makefile("r", encoding="utf-8")
            writer = connection.makefile("w", encoding="utf-8")
            writer.write(
                json.dumps(
                    {
                        "proof": proof,
                        "server": "salesforce_support_ops",
                        "method": "tools/list",
                        "params": {},
                    }
                )
                + "\n"
            )
            writer.flush()
            listed = json.loads(reader.readline())
            assert listed["ok"] is True
            assert listed["result"]["tools"] == []

        with socket.create_connection((host, port), timeout=5) as connection:
            reader = connection.makefile("r", encoding="utf-8")
            writer = connection.makefile("w", encoding="utf-8")
            writer.write(
                json.dumps(
                    {
                        "proof": proof,
                        "server": "salesforce_support_ops",
                        "method": "tools/call",
                        "params": {
                            "name": "salesforce_ticket_list_open",
                            "arguments": {"limit": 5},
                        },
                    }
                )
                + "\n"
            )
            writer.flush()
            denied = json.loads(reader.readline())
            assert denied["ok"] is False
            assert "bounded inventory" in denied["error"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_proactive_ticket_recon_gets_bounded_tools_without_reducing_normal_tasks() -> None:
    alex = _bounded_tool_inventory("tickets_agent", "ops-salesforce-ticket-investigation")
    jamie = _bounded_tool_inventory("billing_agent", "ops-salesforce-ticket-investigation")

    assert alex is not None
    assert set(alex) == {"salesforce_support_ops", "rescue_console"}
    assert "salesforce_ticket_read" in alex["salesforce_support_ops"]
    assert jamie is not None
    assert set(jamie) == {"salesforce_billing_ops", "maxio_billing_ops"}
    assert "maxio_invoice_refund_preview" in jamie["maxio_billing_ops"]
    assert _bounded_tool_inventory("tickets_agent", "direct-message") is None
    assert _bounded_tool_inventory("unknown_agent", "ops-salesforce-ticket-investigation") is None


def test_lane_mcp_config_is_reduced_to_allowlisted_cli_overrides(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("NOVA_CODEX_BROKER_ENDPOINT", "127.0.0.1:12345")
    monkeypatch.setenv("NOVA_CODEX_BROKER_PROOF", "job-scoped-proof")
    path = tmp_path / "alex.toml"
    path.write_text(
        """
[mcp_servers.salesforce_support_ops]
command = "/usr/local/bin/python"
args = ["-m", "codex_slack_bridge.codex_mcp_proxy", "salesforce_support_ops"]
env_vars = ["NOVA_CODEX_BROKER_ENDPOINT", "NOVA_CODEX_BROKER_PROOF"]

[mcp_servers.forbidden]
command = "forbidden"
""",
        encoding="utf-8",
    )
    overrides = dict(
        _codex_mcp_config_overrides(
            {
                "codex_mcp_config_path": str(path),
                "mcp_allowlist": ["salesforce_support_ops"],
            }
        )
    )
    assert overrides["mcp_servers.salesforce_support_ops.command"] == '"/usr/local/bin/python"'
    assert "NOVA_CODEX_BROKER_PROOF" in overrides[
        "mcp_servers.salesforce_support_ops.env_vars"
    ]
    assert overrides["mcp_servers.salesforce_support_ops.env"] == (
        '{NOVA_CODEX_BROKER_ENDPOINT="127.0.0.1:12345",'
        'NOVA_CODEX_BROKER_PROOF="job-scoped-proof"}'
    )
    assert not any("forbidden" in key for key in overrides)
