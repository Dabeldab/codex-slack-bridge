# AgentChat/coding_agent 2026-07-08T07:36:18.4492029Z
from __future__ import annotations

import json
import re
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any

from .memory import redact_secrets


_TAIL_CACHE_LOCK = Lock()
_TAIL_CACHE: dict[str, tuple[tuple[int, int], tuple[dict[str, Any], ...]]] = {}


def append_chat_event(
    *,
    path: Path,
    source: str,
    agent_name: str,
    role: str,
    text: str,
    conversation_id: str | None = None,
    message_id: str | None = None,
    job_id: str | None = None,
    channel_id: str | None = None,
    thread_ts: str | None = None,
    attachments: list[dict[str, Any]] | None = None,
) -> None:
    clean_text = redact_secrets(text).strip()
    if not clean_text:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "id": uuid.uuid4().hex,
        "atUtc": datetime.now(timezone.utc).isoformat(),
        "source": source,
        "agentName": agent_name,
        "role": role,
        "text": clean_text[:6000],
        "conversationId": conversation_id,
        "messageId": message_id,
        "jobId": job_id,
        "channelId": channel_id,
        "threadTs": thread_ts,
    }
    safe_attachments: list[dict[str, Any]] = []
    for item in (attachments or [])[:5]:
        if not isinstance(item, dict):
            continue
        attachment_id = str(item.get("id") or "").strip().casefold()
        if not re.fullmatch(r"[0-9a-f]{32}", attachment_id):
            continue
        try:
            size = max(0, int(item.get("size") or 0))
        except (TypeError, ValueError):
            continue
        safe_attachments.append(
            {
                "id": attachment_id,
                "name": str(item.get("name") or "attachment").strip()[:160],
                "mimetype": str(item.get("mimetype") or "application/octet-stream").strip()[:160],
                "size": size,
                "sha256": str(item.get("sha256") or "").strip().casefold()[:64],
                "kind": "image" if str(item.get("kind") or "").strip().casefold() == "image" else "file",
            }
        )
    if safe_attachments:
        record["attachments"] = safe_attachments
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")


def format_recent_chat(
    *,
    path: Path,
    agent_name: str,
    current_source: str,
    limit: int = 12,
) -> str:
    events = _recent_events(path=path, agent_name=agent_name, current_source=current_source, limit=limit)
    if not events:
        return ""
    lines = ["Recent cross-surface chat context:"]
    for event in events:
        text = str(_event_field(event, "text") or "").replace("\r\n", " ").replace("\n", " ").strip()
        if len(text) > 700:
            text = text[:700].rstrip() + "..."
        when = _short_time(str(_event_field(event, "atUtc") or ""))
        source = _event_field(event, "source") or "unknown"
        role = _event_field(event, "role") or "message"
        lines.append(f"- [{when} {source} {role}] {text}")
    return "\n".join(lines)


def _recent_events(
    *,
    path: Path,
    agent_name: str,
    current_source: str,
    limit: int,
) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    events: list[dict[str, Any]] = []
    for event in reversed(_tail_json_records(path, max_lines=1000)):
        if str(_event_field(event, "agentName") or "").lower() != agent_name.lower():
            continue
        if str(_event_field(event, "source") or "").lower() == current_source.lower():
            continue
        if str(_event_field(event, "role") or "").lower() == "acknowledgement":
            continue
        events.append(event)
        if len(events) >= limit:
            break
    events.reverse()
    return events


def _tail_json_records(path: Path, *, max_lines: int) -> list[dict[str, Any]]:
    try:
        stat = path.stat()
    except OSError:
        return []
    signature = (stat.st_mtime_ns, stat.st_size)
    try:
        key = str(path.resolve())
    except OSError:
        key = str(path.absolute())
    with _TAIL_CACHE_LOCK:
        cached = _TAIL_CACHE.get(key)
        if cached is not None and cached[0] == signature:
            return list(cached[1])

    try:
        lines = _tail_lines(path, max_lines=max_lines)
    except OSError:
        return []
    records: list[dict[str, Any]] = []
    for line in lines:
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            records.append(item)
    with _TAIL_CACHE_LOCK:
        _TAIL_CACHE[key] = (signature, tuple(records))
    return list(records)


def _tail_lines(path: Path, *, max_lines: int, chunk_size: int = 64 * 1024) -> list[str]:
    """Read only the bounded tail of an append-only JSONL journal."""
    if max_lines <= 0:
        return []
    with path.open("rb") as handle:
        handle.seek(0, 2)
        position = handle.tell()
        chunks: list[bytes] = []
        newline_count = 0
        while position > 0 and newline_count <= max_lines:
            read_size = min(chunk_size, position)
            position -= read_size
            handle.seek(position)
            chunk = handle.read(read_size)
            chunks.append(chunk)
            newline_count += chunk.count(b"\n")
    data = b"".join(reversed(chunks)).decode("utf-8", errors="replace")
    return data.splitlines()[-max_lines:]


def _event_field(event: dict[str, Any], name: str) -> Any:
    """Read a journal field regardless of writer casing.

    The Python bridge writes camelCase keys; the desktop app's
    System.Text.Json writes PascalCase. Both must round-trip.
    """
    if name in event:
        return event[name]
    return event.get(name[0].upper() + name[1:])


def _short_time(value: str) -> str:
    if not value:
        return "unknown"
    try:
        normalized = re.sub(r"(\.\d{6})\d+", r"\1", value.replace("Z", "+00:00"))
        return datetime.fromisoformat(normalized).astimezone().strftime("%Y-%m-%d %H:%M")
    except Exception:
        return time.strftime("%Y-%m-%d %H:%M")
