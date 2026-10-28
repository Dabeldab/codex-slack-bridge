from __future__ import annotations

"""Minimal stdio MCP proxy for the parent worker's scoped tool broker."""

import json
import os
import socket
import sys
from typing import Any


PROTOCOL_VERSION = "2025-06-18"


def _broker_call(server: str, method: str, params: dict[str, Any]) -> dict[str, Any]:
    endpoint = str(os.getenv("NOVA_CODEX_BROKER_ENDPOINT") or "").strip()
    proof = str(os.getenv("NOVA_CODEX_BROKER_PROOF") or "").strip()
    if not endpoint or not proof or ":" not in endpoint:
        raise RuntimeError("scoped tool broker is unavailable")
    host, raw_port = endpoint.rsplit(":", 1)
    payload = {
        "proof": proof,
        "server": server,
        "method": method,
        "params": params,
    }
    with socket.create_connection((host, int(raw_port)), timeout=10) as client:
        client.settimeout(300)
        client.sendall(
            (json.dumps(payload, ensure_ascii=True, separators=(",", ":")) + "\n").encode("utf-8")
        )
        response_file = client.makefile("rb")
        raw = response_file.readline(2_000_001)
    response = json.loads(raw.decode("utf-8")) if raw else {}
    if not isinstance(response, dict) or not response.get("ok"):
        raise RuntimeError(str(response.get("error") or "scoped broker request failed")[:1200])
    result = response.get("result")
    return dict(result) if isinstance(result, dict) else {}


def _reply(request_id: Any, *, result: Any = None, error: str = "") -> None:
    if error:
        body = {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32000, "message": error[:1200]}}
    else:
        body = {"jsonrpc": "2.0", "id": request_id, "result": result}
    sys.stdout.write(json.dumps(body, ensure_ascii=True, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def main() -> int:
    server = str(sys.argv[1] if len(sys.argv) > 1 else "").strip()
    if not server:
        return 64
    for raw in sys.stdin:
        try:
            request = json.loads(raw)
            if not isinstance(request, dict):
                continue
            request_id = request.get("id")
            method = str(request.get("method") or "")
            params = request.get("params") if isinstance(request.get("params"), dict) else {}
            if request_id is None:
                continue
            if method == "initialize":
                _reply(
                    request_id,
                    result={
                        "protocolVersion": PROTOCOL_VERSION,
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": f"nova-{server}-proxy", "version": "1.0.0"},
                    },
                )
            elif method in {"tools/list", "tools/call"}:
                _reply(request_id, result=_broker_call(server, method, params))
            elif method == "ping":
                _reply(request_id, result={})
            else:
                _reply(request_id, error="unsupported MCP method")
        except Exception as exc:
            request_id = request.get("id") if isinstance(locals().get("request"), dict) else None
            if request_id is not None:
                _reply(request_id, error=f"{type(exc).__name__}: {exc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

