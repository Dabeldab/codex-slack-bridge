"""One-shot Salesforce to Firestore ticket-board synchronization.

This is the Cloud Run Job entry point used by Cloud Scheduler.  It keeps the
15-minute refresh independent of a web-service instance being warm and never
invokes a reasoning provider.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from .command_center_server import CommandCenterRuntime


def _stage_codex_auth() -> None:
    """Materialize the mounted OAuth secret without logging its contents."""

    payload = os.getenv("CODEX_CLI_OAUTH") or ""
    if not payload.strip():
        return
    codex_home = Path(os.getenv("CODEX_HOME") or "/home/nova/.codex")
    codex_home.mkdir(parents=True, exist_ok=True)
    auth_path = codex_home / "auth.json"
    auth_path.write_bytes(payload.encode("utf-8"))
    auth_path.chmod(0o600)


def main() -> None:
    os.environ["COMMAND_CENTER_DISABLE_WATCHERS"] = "1"
    _stage_codex_auth()
    config_path = Path(
        os.getenv("BRIDGE_CONFIG") or "/app/config/agents.cloud-run-chatgpt.yaml"
    )
    runtime = CommandCenterRuntime(config_path)
    try:
        result = runtime.refresh_ticket_board_deterministic()
        safe_result = {
            key: result.get(key)
            for key in ("ok", "status", "total", "source", "deterministic")
        }
        firestore_result = result.get("firestore")
        if isinstance(firestore_result, dict):
            safe_result["firestore"] = {
                key: firestore_result.get(key)
                for key in ("ok", "written", "skipped", "closed")
                if key in firestore_result
            }
        if result.get("ok"):
            recon = runtime.run_ticket_recon_batch()
            safe_result["recon"] = {
                key: recon.get(key)
                for key in (
                    "ok",
                    "enabled",
                    "considered",
                    "claimed",
                    "completed",
                    "needsAttention",
                    "failed",
                )
                if key in recon
            }
        print(json.dumps(safe_result, sort_keys=True))
        if not result.get("ok"):
            raise SystemExit(1)
    finally:
        runtime.shutdown()


if __name__ == "__main__":
    main()
