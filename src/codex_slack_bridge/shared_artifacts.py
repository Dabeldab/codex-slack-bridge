# AgentChat/coding_agent 2026-07-08T07:36:18.4492029Z
# AgentChat/direct_codex 2026-07-14T17:58:31-04:00: expose bounded job artifact lookup for Drawing Board work products.
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any


_TAIL_CACHE_LOCK = Lock()
_TAIL_CACHE: dict[str, tuple[tuple[int, int], tuple[dict[str, Any], ...]]] = {}


def register_artifact(
    *,
    index_path: Path,
    file_path: Path,
    agent_name: str,
    source: str,
    purpose: str,
    signature: str = "",
    conversation_id: str | None = None,
    message_id: str | None = None,
    job_id: str | None = None,
    idempotency_key: str | None = None,
) -> str | None:
    try:
        resolved = file_path.resolve(strict=True)
    except OSError:
        return None
    if not resolved.is_file():
        return None

    index_path.parent.mkdir(parents=True, exist_ok=True)
    digest = _sha256(resolved)
    clean_idempotency_key = str(idempotency_key or "").strip()
    if clean_idempotency_key:
        existing = _artifact_by_idempotency_key(index_path, clean_idempotency_key)
        if existing:
            return str(existing.get("id") or "") or None
    elif _already_indexed(index_path, str(resolved), digest):
        return None

    artifact_id = uuid.uuid4().hex
    record = {
        "id": artifact_id,
        "atUtc": datetime.now(timezone.utc).isoformat(),
        "source": source,
        "agentName": agent_name,
        "purpose": purpose,
        "path": str(resolved),
        "name": resolved.name,
        "extension": resolved.suffix.lower(),
        "sizeBytes": resolved.stat().st_size,
        "sha256": digest,
        "signature": signature,
        "conversationId": conversation_id,
        "messageId": message_id,
        "jobId": job_id,
        "idempotencyKey": clean_idempotency_key or None,
    }
    with index_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
    return artifact_id


def format_recent_artifacts(
    *,
    index_path: Path,
    agent_name: str,
    limit: int = 10,
) -> str:
    artifacts = recent_artifacts(index_path=index_path, agent_name=agent_name, limit=limit)
    if not artifacts:
        return ""
    lines = ["Recent shared artifacts:"]
    for artifact in artifacts:
        path = artifact.get("path") or ""
        purpose = artifact.get("purpose") or "artifact"
        source = artifact.get("source") or "unknown"
        name = artifact.get("name") or Path(str(path)).name
        lines.append(f"- [{source}; {purpose}] {name}: {path}")
    return "\n".join(lines)


def recent_artifacts(
    *,
    index_path: Path,
    agent_name: str,
    limit: int = 10,
) -> list[dict[str, Any]]:
    artifacts: list[dict[str, Any]] = []
    for item in reversed(_tail_json_records(index_path, max_lines=1000)):
        item_agent = str(item.get("agentName") or "")
        if item_agent and item_agent.lower() not in {agent_name.lower(), "global"}:
            continue
        artifacts.append(item)
        if len(artifacts) >= limit:
            break
    artifacts.reverse()
    return artifacts


def artifacts_for_job(
    *,
    index_path: Path,
    job_id: str | int,
    agent_name: str = "",
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Return registered artifacts for one completed job without scanning the full journal."""
    expected_job = str(job_id or "").strip()
    expected_agent = str(agent_name or "").strip().casefold()
    if not expected_job:
        return []
    matches: list[dict[str, Any]] = []
    for item in reversed(_tail_json_records(index_path, max_lines=2000)):
        if str(item.get("jobId") or "").strip() != expected_job:
            continue
        if expected_agent and str(item.get("agentName") or "").strip().casefold() != expected_agent:
            continue
        matches.append(item)
        if len(matches) >= max(1, min(int(limit), 100)):
            break
    matches.reverse()
    return matches


def artifact_by_id(*, index_path: Path, artifact_id: str) -> dict[str, Any] | None:
    expected = str(artifact_id or "").strip().casefold()
    if not expected:
        return None
    for item in reversed(_tail_json_records(index_path, max_lines=2000)):
        if str(item.get("id") or "").strip().casefold() == expected:
            return item
    return None


def _already_indexed(index_path: Path, resolved_path: str, digest: str) -> bool:
    for item in reversed(_tail_json_records(index_path, max_lines=1000)):
        if item.get("path") == resolved_path and item.get("sha256") == digest:
            return True
    return False


def _artifact_by_idempotency_key(index_path: Path, idempotency_key: str) -> dict[str, Any] | None:
    expected = str(idempotency_key or "").strip()
    if not expected:
        return None
    for item in reversed(_tail_json_records(index_path, max_lines=2000)):
        if str(item.get("idempotencyKey") or "").strip() == expected:
            return item
    return None


def _tail_json_records(path: Path, *, max_lines: int) -> list[dict[str, Any]]:
    """Return a cached, bounded JSONL tail instead of rescanning the journal."""
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


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
