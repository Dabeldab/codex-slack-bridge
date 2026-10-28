from __future__ import annotations

"""Ephemeral, lane-scoped tool broker for isolated Codex CLI workers.

The Codex child keeps a scrubbed environment.  This broker stays in the
supervising worker (where Secret Manager values are available), restores only
the credential family required by the selected typed MCP, and exposes a
loopback-only capability scoped to one job.
"""

import json
import secrets
import socketserver
import threading
from contextlib import AbstractContextManager
from typing import Any, Collection, Mapping

from .reasoning_relay_mcp import DEFAULT_SERVER_SPECS, ReasoningRelayToolBroker


class _BrokerHandler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        owner: "_BrokerTCPServer" = self.server  # type: ignore[assignment]
        raw = self.rfile.readline(2_000_001)
        if not raw or len(raw) > 2_000_000:
            return
        try:
            request = json.loads(raw.decode("utf-8"))
            if not isinstance(request, dict) or not secrets.compare_digest(
                str(request.get("proof") or ""), owner.proof
            ):
                raise PermissionError("invalid broker proof")
            server = str(request.get("server") or "").strip()
            method = str(request.get("method") or "").strip()
            params = request.get("params") if isinstance(request.get("params"), dict) else {}
            if method == "tools/list":
                listed = owner.broker.list_tools(server, limit=100)
                rows = listed.get("tools") or []
                allowed = owner.allowed_tools.get(server)
                if allowed is not None:
                    rows = [row for row in rows if str(row.get("name") or "") in allowed]
                result: Mapping[str, Any] = {"tools": rows}
            elif method == "tools/call":
                tool = str(params.get("name") or "").strip()
                allowed = owner.allowed_tools.get(server)
                if allowed is not None and tool not in allowed:
                    raise PermissionError("tool is outside this job's bounded inventory")
                arguments = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
                executed = owner.broker.execute(
                    server, tool, arguments, allow_write=owner.allow_write
                )
                result = executed.get("result") if isinstance(executed.get("result"), dict) else {}
            else:
                raise ValueError("unsupported broker method")
            response = {"ok": True, "result": result}
        except Exception as exc:
            response = {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:1200]}
        self.wfile.write(
            (json.dumps(response, ensure_ascii=True, separators=(",", ":")) + "\n").encode("utf-8")
        )


class _BrokerTCPServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = False
    daemon_threads = True

    def __init__(
        self,
        broker: ReasoningRelayToolBroker,
        *,
        proof: str,
        allow_write: bool,
        allowed_tools: Mapping[str, Collection[str]] | None = None,
    ) -> None:
        super().__init__(("127.0.0.1", 0), _BrokerHandler)
        self.broker = broker
        self.proof = proof
        self.allow_write = allow_write
        self.allowed_tools = {
            str(server): frozenset(str(tool) for tool in tools)
            for server, tools in (allowed_tools or {}).items()
        }


class ScopedToolBrokerServer(AbstractContextManager[dict[str, str]]):
    def __init__(
        self,
        *,
        lane: str,
        allowed_servers: list[str] | tuple[str, ...],
        child_env: Mapping[str, str],
        config_path: str | None,
        allow_write: bool,
        allowed_tools: Mapping[str, Collection[str]] | None = None,
    ) -> None:
        broker = ReasoningRelayToolBroker(
            lane=lane,
            allowed_servers=allowed_servers,
            child_env=child_env,
            # The lane TOML points Codex at this proxy. The privileged parent
            # must use native typed-server specs, not recursively launch the
            # proxy command from that same file or a shared CODEX_HOME.
            server_specs=DEFAULT_SERVER_SPECS,
        )
        self._proof = secrets.token_urlsafe(32)
        self._server = _BrokerTCPServer(
            broker,
            proof=self._proof,
            allow_write=allow_write,
            allowed_tools=allowed_tools,
        )
        self._thread: threading.Thread | None = None

    def __enter__(self) -> dict[str, str]:
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="codex-scoped-tool-broker",
            daemon=True,
        )
        self._thread.start()
        host, port = self._server.server_address
        return {
            "NOVA_CODEX_BROKER_ENDPOINT": f"{host}:{port}",
            # PROOF deliberately avoids secret-like env naming. The value is
            # job-local, expires with this worker, and cannot exceed the signed
            # lane/authority enforced by the parent broker.
            "NOVA_CODEX_BROKER_PROOF": self._proof,
        }

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self._server.shutdown()
        self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=2)

