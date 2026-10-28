from __future__ import annotations

from dataclasses import dataclass
import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
import tomllib
from pathlib import Path
from typing import Any, Mapping


MCP_PROTOCOL_VERSION = "2025-06-18"
SERVER_NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,100}$")
TOOL_NAME_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,160}$")


@dataclass(frozen=True)
class MCPServerSpec:
    command: str
    args: tuple[str, ...] = ()


SERVER_SECRET_ENV_PREFIXES: dict[str, tuple[str, ...]] = {
    # These values are restored only inside the typed MCP subprocess. They are
    # intentionally absent from the model/local-workspace child environment.
    "rescue_console": ("RESCUE_", "LOGMEIN_"),
    "salesforce_support_ops": ("SALESFORCE_", "SF_"),
    "salesforce_billing_ops": ("SALESFORCE_", "SF_"),
    "salesforce_coding_ops": ("SALESFORCE_", "SF_", "NOVA_SQL_", "NOVA_POS_MAIN_API_COHORT_"),
    "salesforce_operator_ops": ("SALESFORCE_", "SF_", "NOVA_SQL_", "NOVA_POS_MAIN_API_COHORT_"),
    "salesforce_ticket_reads": ("SALESFORCE_", "SF_"),
    "maxio_billing_ops": ("MAXIO_", "CHARGIFY_"),
    "maxio_coding_ops": ("MAXIO_", "CHARGIFY_"),
    "maxio_operator_ops": ("MAXIO_", "CHARGIFY_"),
    "zoom_support_ops": ("ZOOM_",),
    "zoom_billing_ops": ("ZOOM_",),
    "zoom_coding_ops": ("ZOOM_",),
    "zoom_operator_ops": ("ZOOM_",),
    "zoom_quality_ops": ("ZOOM_",),
}


DEFAULT_SERVER_SPECS: dict[str, MCPServerSpec] = {
    "rescue_console": MCPServerSpec(sys.executable, ("-m", "rescue_console_mcp.server")),
    "salesforce_support_ops": MCPServerSpec(sys.executable, ("-m", "scoped_operations_mcp.salesforce_server")),
    "salesforce_billing_ops": MCPServerSpec(sys.executable, ("-m", "scoped_operations_mcp.salesforce_server")),
    "salesforce_coding_ops": MCPServerSpec(sys.executable, ("-m", "scoped_operations_mcp.salesforce_server")),
    "salesforce_operator_ops": MCPServerSpec(sys.executable, ("-m", "scoped_operations_mcp.salesforce_server")),
    "salesforce_ticket_reads": MCPServerSpec(sys.executable, ("-m", "scoped_operations_mcp.salesforce_server")),
    "maxio_billing_ops": MCPServerSpec(sys.executable, ("-m", "scoped_operations_mcp.maxio_server")),
    "maxio_coding_ops": MCPServerSpec(sys.executable, ("-m", "scoped_operations_mcp.maxio_server")),
    "maxio_operator_ops": MCPServerSpec(sys.executable, ("-m", "scoped_operations_mcp.maxio_server")),
    "zoom_support_ops": MCPServerSpec(sys.executable, ("-m", "scoped_operations_mcp.zoom_server")),
    "zoom_billing_ops": MCPServerSpec(sys.executable, ("-m", "scoped_operations_mcp.zoom_server")),
    "zoom_coding_ops": MCPServerSpec(sys.executable, ("-m", "scoped_operations_mcp.zoom_server")),
    "zoom_operator_ops": MCPServerSpec(sys.executable, ("-m", "scoped_operations_mcp.zoom_server")),
    "zoom_quality_ops": MCPServerSpec(sys.executable, ("-m", "scoped_operations_mcp.zoom_server")),
    "gcp_github_ops": MCPServerSpec(sys.executable, ("-m", "scoped_operations_mcp.cloud_ops_server")),
    "rory_operator_ops": MCPServerSpec(sys.executable, ("-m", "scoped_operations_mcp.operator_services_server")),
    "google_drive_support_reads": MCPServerSpec(sys.executable, ("-m", "scoped_operations_mcp.operator_services_server")),
}


def _configured_server_specs(config_path: str | None) -> dict[str, MCPServerSpec]:
    specs = dict(DEFAULT_SERVER_SPECS)
    candidates: list[Path] = []
    if config_path:
        candidates.append(Path(os.path.expandvars(os.path.expanduser(config_path))))
    codex_home = str(os.getenv("CODEX_HOME") or "").strip()
    if codex_home:
        candidates.append(Path(os.path.expandvars(os.path.expanduser(codex_home))) / "config.toml")
    for path in candidates:
        if not path.is_file():
            continue
        try:
            parsed = tomllib.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, tomllib.TOMLDecodeError):
            continue
        rows = parsed.get("mcp_servers") if isinstance(parsed, dict) else None
        if not isinstance(rows, dict):
            continue
        for name, row in rows.items():
            if not isinstance(row, dict):
                continue
            command = str(row.get("command") or "").strip()
            raw_args = row.get("args") or []
            if not command or not isinstance(raw_args, list):
                continue
            args = tuple(str(item) for item in raw_args)
            specs[str(name)] = MCPServerSpec(command, args)
        break
    return specs



class MCPProtocolError(RuntimeError):
    pass


class MCPStdioClient:
    """Small dependency-free MCP stdio client for list/call tool operations."""

    def __init__(
        self,
        spec: MCPServerSpec,
        *,
        env: Mapping[str, str],
        cwd: str | None = None,
        timeout_seconds: float = 60.0,
    ) -> None:
        self.spec = spec
        self.env = dict(env)
        self.cwd = cwd
        self.timeout_seconds = max(1.0, float(timeout_seconds))
        self.process: subprocess.Popen[str] | None = None
        self._messages: queue.Queue[dict[str, Any] | BaseException] = queue.Queue()
        self._reader_thread: threading.Thread | None = None
        self._request_id = 0

    def __enter__(self) -> "MCPStdioClient":
        self.process = subprocess.Popen(
            [self.spec.command, *self.spec.args],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=self.env,
            cwd=self.cwd,
            bufsize=1,
            creationflags=(
                int(getattr(subprocess, "CREATE_NO_WINDOW", 0))
                if os.name == "nt"
                else 0
            ),
        )
        self._reader_thread = threading.Thread(target=self._reader, name="relay-mcp-reader", daemon=True)
        self._reader_thread.start()
        initialized = self._request(
            "initialize",
            {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "nova-reasoning-relay", "version": "1.0"},
            },
        )
        if not isinstance(initialized, Mapping):
            raise MCPProtocolError("MCP initialize returned an invalid result")
        self._notify("notifications/initialized", {})
        return self

    def __exit__(self, *_exc: Any) -> None:
        process = self.process
        if process is None:
            return
        try:
            if process.stdin is not None:
                process.stdin.close()
        except OSError:
            pass
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
        self.process = None

    def _reader(self) -> None:
        assert self.process is not None and self.process.stdout is not None
        try:
            for line in self.process.stdout:
                clean = line.strip()
                if not clean:
                    continue
                try:
                    payload = json.loads(clean)
                except json.JSONDecodeError:
                    continue
                if isinstance(payload, dict):
                    self._messages.put(payload)
        except BaseException as exc:  # pragma: no cover - defensive I/O path.
            self._messages.put(exc)

    def _send(self, payload: Mapping[str, Any]) -> None:
        if self.process is None or self.process.stdin is None:
            raise MCPProtocolError("MCP process is unavailable")
        self.process.stdin.write(json.dumps(dict(payload), ensure_ascii=False, separators=(",", ":")) + "\n")
        self.process.stdin.flush()

    def _notify(self, method: str, params: Mapping[str, Any]) -> None:
        self._send({"jsonrpc": "2.0", "method": method, "params": dict(params)})

    def _request(self, method: str, params: Mapping[str, Any]) -> Any:
        self._request_id += 1
        request_id = self._request_id
        self._send({"jsonrpc": "2.0", "id": request_id, "method": method, "params": dict(params)})
        deadline = time.monotonic() + self.timeout_seconds
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"MCP request timed out: {method}")
            try:
                message = self._messages.get(timeout=min(remaining, 0.5))
            except queue.Empty:
                if self.process is not None and self.process.poll() is not None:
                    stderr = ""
                    if self.process.stderr is not None:
                        try:
                            stderr = self.process.stderr.read()[-1200:]
                        except OSError:
                            pass
                    raise MCPProtocolError(f"MCP server exited before {method}: {stderr}")
                continue
            if isinstance(message, BaseException):
                raise MCPProtocolError(f"MCP reader failed: {message}") from message
            if message.get("id") != request_id:
                continue
            if isinstance(message.get("error"), Mapping):
                error = message["error"]
                raise MCPProtocolError(str(error.get("message") or "MCP request failed")[:1200])
            return message.get("result")

    def list_tools(self) -> list[dict[str, Any]]:
        result = self._request("tools/list", {})
        rows = result.get("tools") if isinstance(result, Mapping) else None
        if not isinstance(rows, list):
            raise MCPProtocolError("MCP tools/list returned an invalid result")
        return [dict(row) for row in rows if isinstance(row, Mapping)]

    def call_tool(self, name: str, arguments: Mapping[str, Any]) -> dict[str, Any]:
        result = self._request("tools/call", {"name": name, "arguments": dict(arguments)})
        if not isinstance(result, Mapping):
            raise MCPProtocolError("MCP tools/call returned an invalid result")
        return dict(result)


class ReasoningRelayToolBroker:
    def __init__(
        self,
        *,
        lane: str,
        allowed_servers: list[str] | tuple[str, ...],
        child_env: Mapping[str, str],
        cwd: str | None = None,
        server_specs: Mapping[str, MCPServerSpec] | None = None,
        config_path: str | None = None,
    ) -> None:
        self.lane = str(lane or "").strip()
        specs = dict(server_specs) if server_specs is not None else _configured_server_specs(config_path)
        allowed: dict[str, MCPServerSpec] = {}
        for name in allowed_servers:
            clean = str(name or "").strip()
            if clean in specs:
                allowed[clean] = specs[clean]
        self._servers = allowed
        self.child_env = dict(child_env)
        self.child_env["SCOPED_AGENT_LANE"] = self.lane
        self.cwd = cwd

    @property
    def server_names(self) -> tuple[str, ...]:
        return tuple(sorted(self._servers))

    def _spec(self, server: str) -> MCPServerSpec:
        clean = str(server or "").strip()
        if not SERVER_NAME_RE.fullmatch(clean) or clean not in self._servers:
            raise PermissionError("requested MCP server is not allowed for this lane")
        return self._servers[clean]

    def _env_for_server(self, server: str) -> dict[str, str]:
        """Restore only the service credentials needed by the selected typed MCP."""
        clean = str(server or "").strip()
        env = dict(self.child_env)
        prefixes = SERVER_SECRET_ENV_PREFIXES.get(clean, ())
        if not prefixes:
            return env
        for name, value in os.environ.items():
            upper = name.upper()
            if any(upper.startswith(prefix) for prefix in prefixes):
                env[name] = value
        return env

    def list_tools(self, server: str, *, query: str = "", limit: int = 40) -> dict[str, Any]:
        spec = self._spec(server)
        with MCPStdioClient(spec, env=self._env_for_server(server), cwd=self.cwd, timeout_seconds=45) as client:
            rows = client.list_tools()
        needle = str(query or "").strip().casefold()
        compact: list[dict[str, Any]] = []
        for row in rows:
            name = str(row.get("name") or "")
            description = str(row.get("description") or "")
            if needle and needle not in f"{name} {description}".casefold():
                continue
            compact.append(
                {
                    "name": name,
                    "description": description[:1000],
                    "inputSchema": row.get("inputSchema") if isinstance(row.get("inputSchema"), Mapping) else {},
                    "annotations": row.get("annotations") if isinstance(row.get("annotations"), Mapping) else {},
                }
            )
            if len(compact) >= max(1, min(int(limit), 100)):
                break
        return {"ok": True, "server": server, "tools": compact, "count": len(compact)}

    def execute(
        self,
        server: str,
        tool: str,
        arguments: Mapping[str, Any],
        *,
        allow_write: bool,
    ) -> dict[str, Any]:
        if not TOOL_NAME_RE.fullmatch(str(tool or "").strip()):
            raise ValueError("tool name is invalid")
        spec = self._spec(server)
        with MCPStdioClient(spec, env=self._env_for_server(server), cwd=self.cwd, timeout_seconds=120) as client:
            tools = client.list_tools()
            match = next((row for row in tools if str(row.get("name") or "") == tool), None)
            if match is None:
                raise ValueError("tool is not exposed by the selected MCP server")
            annotations = match.get("annotations") if isinstance(match.get("annotations"), Mapping) else {}
            read_only = bool(annotations.get("readOnlyHint"))
            if not read_only and not allow_write:
                raise PermissionError("the trusted request did not authorize a live write")
            result = client.call_tool(tool, arguments)
        return {"ok": True, "server": server, "tool": tool, "result": result}
