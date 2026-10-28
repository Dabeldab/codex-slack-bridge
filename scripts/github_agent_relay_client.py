from __future__ import annotations

"""GitHub Actions client for the Nova GitHub agent relay."""

import argparse
import json
import os
import re
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

TASK_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,199}$")
TERMINAL_STATUSES = {
    "completed",
    "completed_with_issues",
    "failed",
    "blocked",
    "interrupted",
    "recovery_review_required",
    "unclassified",
    "cancelled",
    "canceled",
}


class RelayClientError(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_envelope(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RelayClientError(f"{path}: invalid JSON envelope") from exc
    if not isinstance(payload, dict):
        raise RelayClientError(f"{path}: envelope must be a JSON object")
    task_id = str(payload.get("task_id") or payload.get("taskId") or "").strip()
    if not TASK_ID_RE.fullmatch(task_id):
        raise RelayClientError(f"{path}: task_id must be 8-200 safe characters")
    return payload


def relay_request(
    relay_url: str,
    token: str,
    method: str,
    path: str,
    payload: Mapping[str, Any] | None = None,
    timeout: float = 30.0,
) -> dict[str, Any]:
    base = relay_url.rstrip("/")
    parsed = urllib.parse.urlparse(base)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise RelayClientError("relay URL must be an HTTPS origin")
    data = None
    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {token}",
        "User-Agent": "nova-github-relay-action/1",
    }
    if payload is not None:
        data = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(f"{base}{path}", data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # nosec B310 - exact configured HTTPS relay origin
            raw = response.read(512 * 1024)
            body = json.loads(raw.decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        raw = exc.read(128 * 1024)
        try:
            body = json.loads(raw.decode("utf-8") or "{}")
        except Exception:
            body = {}
        raise RelayClientError(
            f"relay HTTP {exc.code}: {body.get('message') or exc.reason or 'request failed'}"
        ) from exc
    except (urllib.error.URLError, TimeoutError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RelayClientError(f"relay request failed: {exc}") from exc
    if not isinstance(body, dict):
        raise RelayClientError("relay response was not a JSON object")
    if body.get("ok") is False:
        raise RelayClientError(str(body.get("message") or "relay rejected request"))
    return body


def process_envelope(
    path: Path,
    *,
    relay_url: str,
    token: str,
    outbox_dir: Path,
    default_timeout_seconds: int,
    poll_seconds: float,
) -> Path:
    started_at = utc_now()
    try:
        envelope = load_envelope(path)
        task_id = str(envelope.get("task_id") or envelope.get("taskId")).strip()
        timeout_seconds = bounded_timeout(
            envelope.get("timeout_seconds", default_timeout_seconds)
        )
        receipt = relay_request(relay_url, token, "POST", "/v1/tasks", envelope)
        job_id = str(receipt.get("job_id") or "").strip()
        if not job_id:
            raise RelayClientError("relay accepted task without job_id")
        deadline = time.monotonic() + timeout_seconds
        last_job: dict[str, Any] = {}
        while time.monotonic() < deadline:
            try:
                last_job = relay_request(
                    relay_url,
                    token,
                    "GET",
                    f"/v1/jobs/{urllib.parse.quote(job_id, safe='._:-')}",
                )
            except RelayClientError as exc:
                # The durable projection can lag the submit response briefly.
                if "HTTP 404" not in str(exc):
                    raise
                time.sleep(poll_seconds)
                continue
            status = str(last_job.get("status") or "queued").strip().casefold()
            if bool(last_job.get("terminal")) or status in TERMINAL_STATUSES:
                result = {
                    "version": 1,
                    "task_id": task_id,
                    "status": status,
                    "relay_status": "completed",
                    "agent": receipt.get("agent"),
                    "agent_label": receipt.get("agent_label"),
                    "job_id": job_id,
                    "bridge_job_id": receipt.get("bridge_job_id"),
                    "duplicate": bool(receipt.get("duplicate")),
                    "submitted_at": started_at,
                    "completed_at": utc_now(),
                    "job": last_job,
                    "error": None,
                }
                return write_result(outbox_dir, task_id, result)
            time.sleep(poll_seconds)
        result = {
            "version": 1,
            "task_id": task_id,
            "status": str(last_job.get("status") or "timeout"),
            "relay_status": "timeout",
            "agent": receipt.get("agent"),
            "agent_label": receipt.get("agent_label"),
            "job_id": job_id,
            "bridge_job_id": receipt.get("bridge_job_id"),
            "duplicate": bool(receipt.get("duplicate")),
            "submitted_at": started_at,
            "completed_at": utc_now(),
            "job": last_job,
            "error": f"task did not reach a terminal Command Center state within {timeout_seconds} seconds",
        }
        return write_result(outbox_dir, task_id, result)
    except Exception as exc:
        fallback_id = safe_task_id_from_path(path)
        result = {
            "version": 1,
            "task_id": fallback_id,
            "status": "relay_error",
            "relay_status": "error",
            "submitted_at": started_at,
            "completed_at": utc_now(),
            "job": {},
            "error": str(exc),
        }
        return write_result(outbox_dir, fallback_id, result)


def bounded_timeout(value: Any) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise RelayClientError("timeout_seconds must be an integer") from exc
    if parsed < 30 or parsed > 1800:
        raise RelayClientError("timeout_seconds must be between 30 and 1800")
    return parsed


def safe_task_id_from_path(path: Path) -> str:
    stem = re.sub(r"[^A-Za-z0-9._:-]+", "-", path.stem).strip("-._:")
    if len(stem) < 8:
        stem = f"relay-{stem or 'error'}-{int(time.time())}"
    return stem[:200]


def write_result(outbox_dir: Path, task_id: str, result: Mapping[str, Any]) -> Path:
    if not TASK_ID_RE.fullmatch(task_id):
        task_id = safe_task_id_from_path(Path(task_id))
    outbox_dir.mkdir(parents=True, exist_ok=True)
    destination = outbox_dir / f"{task_id}.json"
    temporary = destination.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(destination)
    return destination


def changed_inbox_files(before: str, after: str, inbox_dir: Path) -> list[Path]:
    clean_before = str(before or "").strip()
    clean_after = str(after or "HEAD").strip() or "HEAD"
    if not re.fullmatch(r"[0-9a-fA-F]{40}", clean_after):
        raise RelayClientError("after SHA is invalid")
    all_zero = bool(clean_before) and set(clean_before) == {"0"}
    if all_zero or not re.fullmatch(r"[0-9a-fA-F]{40}", clean_before):
        candidates = sorted(inbox_dir.glob("*.json"))
        return [path for path in candidates if path.is_file()]
    command = [
        "git",
        "diff",
        "--name-only",
        "--diff-filter=AM",
        clean_before,
        clean_after,
        "--",
        str(inbox_dir / "*.json"),
    ]
    completed = subprocess.run(command, check=True, text=True, capture_output=True)
    paths: list[Path] = []
    for raw in completed.stdout.splitlines():
        path = Path(raw.strip())
        if path.suffix == ".json" and path.parent == inbox_dir and path.is_file():
            paths.append(path)
    return sorted(set(paths))


def main() -> None:
    parser = argparse.ArgumentParser(description="Process GitHub relay inbox envelopes")
    parser.add_argument("--relay-url", required=True)
    parser.add_argument("--token", default=os.getenv("RELAY_ID_TOKEN", ""))
    parser.add_argument("--before", default=os.getenv("GITHUB_EVENT_BEFORE", ""))
    parser.add_argument("--after", default=os.getenv("GITHUB_SHA", ""))
    parser.add_argument("--inbox", default="relay/inbox")
    parser.add_argument("--outbox", default="relay/outbox")
    parser.add_argument("--timeout-seconds", type=int, default=900)
    parser.add_argument("--poll-seconds", type=float, default=3.0)
    args = parser.parse_args()

    token = str(args.token or "").strip()
    if len(token) < 100:
        raise SystemExit("RELAY_ID_TOKEN is missing or invalid")
    timeout = bounded_timeout(args.timeout_seconds)
    poll_seconds = max(1.0, min(float(args.poll_seconds), 30.0))
    inbox_dir = Path(args.inbox)
    outbox_dir = Path(args.outbox)
    paths = changed_inbox_files(args.before, args.after, inbox_dir)
    if not paths:
        print("No new relay inbox envelopes found.")
        return

    outputs: list[Path] = []
    for path in paths:
        print(f"Processing {path}")
        outputs.append(
            process_envelope(
                path,
                relay_url=args.relay_url,
                token=token,
                outbox_dir=outbox_dir,
                default_timeout_seconds=timeout,
                poll_seconds=poll_seconds,
            )
        )
    print("Relay results written:")
    for path in outputs:
        print(path)


if __name__ == "__main__":
    main()
