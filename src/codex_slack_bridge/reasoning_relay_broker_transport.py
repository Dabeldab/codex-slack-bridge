from __future__ import annotations

import json
import os
import shlex
import subprocess
import time
from typing import Any

from .reasoning_relay_protocol import RelayRequest, RelayResponse


class BrokeredGitHubReasoningRelayTransport:
    """GitHub mailbox transport whose credentials remain inside nova-cloud-broker."""

    def __init__(self, command: list[str], *, poll_seconds: float = 2.0) -> None:
        if not command:
            raise RuntimeError("reasoning relay broker command is empty")
        self.command = list(command)
        self.poll_seconds = max(0.5, min(float(poll_seconds), 30.0))

    @classmethod
    def from_environment(cls) -> "BrokeredGitHubReasoningRelayTransport":
        raw = str(os.getenv("REASONING_RELAY_BROKER_COMMAND") or "").strip()
        if not raw:
            raise RuntimeError("REASONING_RELAY_BROKER_COMMAND is required")
        return cls(
            shlex.split(raw),
            poll_seconds=float(os.getenv("REASONING_RELAY_POLL_SECONDS") or 2.0),
        )

    def _call(self, payload: dict[str, Any], *, timeout: float = 60.0) -> dict[str, Any]:
        action = str(payload.get("action") or "unknown").strip() or "unknown"
        timeout_seconds = max(1.0, float(timeout))
        try:
            completed = subprocess.run(
                self.command,
                input=(json.dumps(payload, ensure_ascii=True, separators=(",", ":")) + "\n").encode("utf-8"),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(
                f"reasoning relay broker action {action!r} timed out after {timeout_seconds:.1f} seconds"
            ) from exc
        text = completed.stdout.decode("utf-8", errors="replace").strip()
        try:
            response = json.loads(text) if text else {}
        except json.JSONDecodeError as exc:
            raise RuntimeError("reasoning relay broker returned invalid JSON") from exc
        if completed.returncode != 0 or not isinstance(response, dict) or response.get("ok") is not True:
            message = str(response.get("error") if isinstance(response, dict) else "").strip()
            if not message:
                message = completed.stderr.decode("utf-8", errors="replace").strip()
            raise RuntimeError((message or "reasoning relay broker failed")[:1200])
        return response

    def health(self) -> dict[str, Any]:
        # A broker health request can require a fresh GitHub App installation
        # token plus repository/ref reads. Keep the outer subprocess budget
        # larger than the individual 30s HTTP timeouts used by the broker.
        return dict(self._call({"action": "health"}, timeout=120.0).get("health") or {})

    def ensure_pull_request(self) -> dict[str, Any]:
        return dict(self._call({"action": "ensure_pull_request"}, timeout=150.0).get("pullRequest") or {})

    def publish(self, request: RelayRequest) -> str:
        response = self._call({"action": "publish", "request": request.to_dict()}, timeout=150.0)
        return str(response.get("path") or "")

    def wait_response(self, request: RelayRequest, *, timeout_seconds: float) -> RelayResponse:
        deadline = time.monotonic() + max(1.0, float(timeout_seconds))
        while True:
            response = self._call(
                {"action": "read_response", "request": request.to_dict()},
                timeout=120.0,
            )
            if response.get("found"):
                raw = response.get("response")
                if not isinstance(raw, dict):
                    raise RuntimeError("reasoning relay broker response must be an object")
                return RelayResponse.from_dict(raw, expected_request=request)
            if time.monotonic() >= deadline:
                raise TimeoutError(f"Timed out waiting for ChatGPT relay response to {request.message_id}")
            time.sleep(self.poll_seconds)

    def cleanup(self, request: RelayRequest) -> None:
        # Cleanup can perform multiple GitHub content reads/deletes after
        # obtaining a fresh installation token in the broker subprocess.
        self._call({"action": "cleanup", "request": request.to_dict()}, timeout=150.0)
