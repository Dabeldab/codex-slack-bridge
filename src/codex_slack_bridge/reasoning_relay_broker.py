from __future__ import annotations

import json
import os
import sys
from typing import Any

from .reasoning_relay_protocol import RelayRequest
from .reasoning_relay_transport import GitHubReasoningRelayTransport, GitHubRelaySettings

MAX_INPUT_BYTES = 512_000


def _response(payload: dict[str, Any], *, code: int = 0) -> int:
    sys.stdout.write(json.dumps(payload, ensure_ascii=True, separators=(",", ":")) + "\n")
    sys.stdout.flush()
    return code


def _transport() -> GitHubReasoningRelayTransport:
    os.environ.setdefault("REASONING_RELAY_REPOSITORY", "dariusmakesstuff/codex-slack-bridge")
    os.environ.setdefault("REASONING_RELAY_BRANCH", "reasoning-relay-bus")
    return GitHubReasoningRelayTransport(GitHubRelaySettings.from_environment())


def main() -> int:
    raw = sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)
    if len(raw) > MAX_INPUT_BYTES:
        return _response({"ok": False, "error": "request_too_large"}, code=64)
    try:
        request = json.loads(raw.decode("utf-8"))
        if not isinstance(request, dict):
            raise ValueError("request must be an object")
        action = str(request.get("action") or "").strip()
        transport = _transport()
        if action == "health":
            payload = transport.health()
            return _response({"ok": bool(payload.get("ok")), "health": payload})
        if action == "ensure_pull_request":
            return _response({"ok": True, "pullRequest": transport.ensure_pull_request()})
        if action == "publish":
            relay = RelayRequest.from_dict(request.get("request") or {})
            return _response({"ok": True, "path": transport.publish(relay)})
        if action == "read_response":
            relay = RelayRequest.from_dict(request.get("request") or {})
            path = f"relay/runtime/inbound/{relay.message_id}.json"
            payload = transport._get_json(path)  # broker owns the fixed mailbox path
            return _response({"ok": True, "found": payload is not None, "response": payload})
        if action == "cleanup":
            relay = RelayRequest.from_dict(request.get("request") or {})
            transport.cleanup(relay)
            return _response({"ok": True})
        raise ValueError("unsupported action")
    except Exception as exc:
        return _response({"ok": False, "error": f"{type(exc).__name__}: {exc}"[:1000]}, code=1)


if __name__ == "__main__":
    raise SystemExit(main())
