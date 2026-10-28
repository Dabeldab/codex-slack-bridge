from __future__ import annotations

"""Long-request relay entrypoint that keeps GitHub auth out of polling loops."""

import argparse
import json
import logging
import os
import time
import urllib.parse
from http.server import ThreadingHTTPServer
from typing import Any, Callable

from .github_agent_relay import (
    MAX_REQUEST_BYTES,
    CommandCenterRelay,
    Handler,
    RelayConfigurationError,
    RelayRequestError,
    RelaySettings,
    UpstreamError,
)

LOGGER = logging.getLogger("codex_slack_bridge.github_agent_relay_wait")


def task_timeout(value: Any) -> int:
    try:
        timeout = int(value)
    except (TypeError, ValueError) as exc:
        raise RelayRequestError("timeout_seconds must be an integer") from exc
    if not 30 <= timeout <= 1800:
        raise RelayRequestError("timeout_seconds must be between 30 and 1800")
    return timeout


class WaitRelay(CommandCenterRelay):
    def run(
        self,
        raw: dict[str, Any],
        *,
        heartbeat: Callable[[], None] | None = None,
    ) -> dict[str, Any]:
        receipt = self.submit(raw)
        timeout = task_timeout(raw.get("timeout_seconds", 900))
        deadline = time.monotonic() + timeout
        last: dict[str, Any] = {}
        keepalive = heartbeat or (lambda: None)
        keepalive()
        while time.monotonic() < deadline:
            try:
                last = self.job(receipt["job_id"])
            except UpstreamError as exc:
                if exc.status != 404:
                    raise
                time.sleep(3)
                continue
            if last.get("terminal"):
                return {**receipt, "relay_status": "completed", "job": last, "error": None}
            keepalive()
            time.sleep(3)
        return {
            **receipt,
            "relay_status": "timeout",
            "job": last,
            "error": f"task did not reach a terminal state within {timeout} seconds",
        }


class WaitHandler(Handler):
    relay: WaitRelay

    def do_POST(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlsplit(self.path)
        if parsed.path != "/v1/tasks" or parsed.query:
            return self._json(404, {"ok": False, "message": "not found"})
        streaming = False
        try:
            length = int(str(self.headers.get("Content-Length") or "0"))
            if not 2 <= length <= MAX_REQUEST_BYTES:
                raise RelayRequestError("request body size is invalid")
            body = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(body, dict):
                raise RelayRequestError("request body must be a JSON object")
            # Send headers before the long private poll and stream harmless JSON
            # whitespace as a heartbeat. Some GitHub-hosted runner paths close
            # an otherwise healthy HTTP response after five idle minutes.
            self.send_response(200)
            for key, value in (
                ("Content-Type", "application/json; charset=utf-8"),
                ("Cache-Control", "no-store"),
                ("X-Content-Type-Options", "nosniff"),
                ("Connection", "close"),
            ):
                self.send_header(key, value)
            self.end_headers()
            self.close_connection = True
            streaming = True

            def heartbeat() -> None:
                self.wfile.write(b" ")
                self.wfile.flush()

            self._stream_json(self.relay.run(body, heartbeat=heartbeat))
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            error = RelayRequestError(str(exc) or "invalid JSON request")
            self._stream_error(error) if streaming else self._error(error)
        except (RelayRequestError, RelayConfigurationError, UpstreamError) as exc:
            self._stream_error(exc) if streaming else self._error(exc)
        except (BrokenPipeError, ConnectionResetError):
            LOGGER.warning("relay client disconnected before the terminal result")
        except Exception as exc:
            LOGGER.exception("unhandled wait relay request")
            self._stream_error(exc) if streaming else self._error(exc)

    def _stream_error(self, exc: Exception) -> None:
        if isinstance(exc, (RelayRequestError, UpstreamError)):
            message = str(exc)
        elif isinstance(exc, RelayConfigurationError):
            message = "relay configuration unavailable"
        else:
            message = "relay request failed"
        self._stream_json({"ok": False, "relay_status": "error", "message": message})

    def _stream_json(self, body: dict[str, Any]) -> None:
        self.wfile.write(json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
        self.wfile.flush()


def main() -> None:
    parser = argparse.ArgumentParser(description="Nova GitHub long-request relay")
    parser.add_argument("--host", default=os.getenv("HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.getenv("PORT", "8080")))
    args = parser.parse_args()
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    relay = WaitRelay(RelaySettings.from_environment())
    handler = type("ConfiguredWaitRelayHandler", (WaitHandler,), {"relay": relay})
    server = ThreadingHTTPServer((args.host, args.port), handler)
    server.daemon_threads = True
    try:
        server.serve_forever(0.5)
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
