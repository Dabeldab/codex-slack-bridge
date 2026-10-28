from __future__ import annotations

"""One-request Actions client; relay performs private polling server-side."""

import argparse
import os
from pathlib import Path

from github_agent_relay_client import (
    bounded_timeout,
    changed_inbox_files,
    load_envelope,
    relay_request,
    safe_task_id_from_path,
    utc_now,
    write_result,
)


def process(path: Path, relay_url: str, token: str, outbox: Path, default_timeout: int) -> Path:
    started = utc_now()
    try:
        envelope = load_envelope(path)
        task_id = str(envelope.get("task_id") or envelope.get("taskId")).strip()
        timeout = bounded_timeout(envelope.get("timeout_seconds", default_timeout))
        envelope["timeout_seconds"] = timeout
        response = relay_request(relay_url, token, "POST", "/v1/tasks", envelope, timeout=timeout + 90)
        job = response.get("job") if isinstance(response.get("job"), dict) else {}
        return write_result(outbox, task_id, {
            "version": 1,
            "task_id": task_id,
            "status": str(job.get("status") or response.get("status") or "unknown").strip().casefold(),
            "relay_status": str(response.get("relay_status") or "completed"),
            "agent": response.get("agent"),
            "agent_label": response.get("agent_label"),
            "job_id": response.get("job_id"),
            "bridge_job_id": response.get("bridge_job_id"),
            "duplicate": bool(response.get("duplicate")),
            "submitted_at": started,
            "completed_at": utc_now(),
            "job": job,
            "error": response.get("error"),
        })
    except Exception as exc:
        task_id = safe_task_id_from_path(path)
        return write_result(outbox, task_id, {
            "version": 1, "task_id": task_id, "status": "relay_error", "relay_status": "error",
            "submitted_at": started, "completed_at": utc_now(), "job": {}, "error": str(exc),
        })


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--relay-url", required=True)
    parser.add_argument("--token", default=os.getenv("RELAY_ID_TOKEN", ""))
    parser.add_argument("--before", default=os.getenv("GITHUB_EVENT_BEFORE", ""))
    parser.add_argument("--after", default=os.getenv("GITHUB_SHA", ""))
    parser.add_argument("--inbox", default="relay/inbox")
    parser.add_argument("--outbox", default="relay/outbox")
    parser.add_argument("--timeout-seconds", type=int, default=900)
    args = parser.parse_args()
    token = str(args.token or "").strip()
    if len(token) < 100:
        raise SystemExit("RELAY_ID_TOKEN is missing or invalid")
    default_timeout = bounded_timeout(args.timeout_seconds)
    inbox, outbox = Path(args.inbox), Path(args.outbox)
    paths = changed_inbox_files(args.before, args.after, inbox)
    if not paths:
        print("No new relay inbox envelopes found.")
        return
    for path in paths:
        print(process(path, args.relay_url, token, outbox, default_timeout))


if __name__ == "__main__":
    main()
