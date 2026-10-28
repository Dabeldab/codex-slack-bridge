# AgentChat/coding_agent 2026-07-08T07:36:18.4492029Z
from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import re
import tempfile
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from threading import Lock
from typing import Any, Iterator


LOGGER = logging.getLogger("codex_slack_bridge.desktop_memory_json")
TOKEN_RE = re.compile(r"[a-zA-Z0-9_.$/-]+")
DIMENSIONS = 384
MAX_TEXT_CHARS = 6000
LOCK_TIMEOUT_SECONDS = 2.0
LOCK_STALE_SECONDS = 10.0
_CACHE_LOCK = Lock()
_RECORD_CACHE: dict[str, tuple[tuple[int, int], tuple[dict[str, Any], ...]]] = {}


def remember_desktop_json(
    *,
    path: Path,
    agent_name: str,
    text: str,
    source: str,
    tags: list[str] | None = None,
    importance: float = 1.0,
) -> str | None:
    clean_text = text.strip()
    if not clean_text:
        return None
    if len(clean_text) > MAX_TEXT_CHARS:
        clean_text = clean_text[:MAX_TEXT_CHARS].rstrip() + "\n[truncated]"

    path.parent.mkdir(parents=True, exist_ok=True)
    fingerprint = _fingerprint(f"{agent_name}\n{source}\n{clean_text}")
    with _file_lock(path):
        records = _try_load(path)
        if records is None:
            # The file exists but could not be parsed (most likely a concurrent
            # non-atomic write from the desktop app). Never clobber it.
            LOGGER.warning("Desktop memory JSON unreadable; skipping write to avoid clobbering: %s", path)
            return None
        if any(str(record.get("Fingerprint") or "") == fingerprint for record in records):
            return None

        memory_id = uuid.uuid4().hex
        records.append(
            {
                "Id": memory_id,
                "AgentName": agent_name,
                "Text": clean_text,
                "Source": source,
                "Tags": list(tags or []),
                "Importance": float(importance),
                "CreatedAt": _dotnet_timestamp(),
                "Vector": hash_embedding(clean_text),
                "Fingerprint": fingerprint,
            }
        )
        _save_atomic(path, records)
    return memory_id


def retrieve_desktop_json(
    *,
    path: Path,
    agent_name: str,
    global_agent: str,
    query: str,
    top_k: int,
    records: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    clean_query = query.strip()
    if not clean_query or not path.exists():
        return []

    query_vector = hash_embedding(clean_query)
    query_lane = _infer_product_lane(clean_query)
    now = time.time()
    results: list[dict[str, Any]] = []
    for record in records if records is not None else _load(path):
        row_agent = str(record.get("AgentName") or "")
        if row_agent.lower() not in {agent_name.lower(), global_agent.lower()}:
            continue
        if not _should_include_for_lane(record, query_lane):
            continue
        text = str(record.get("Text") or "")
        vector = record.get("Vector") or []
        if not text or not isinstance(vector, list):
            continue
        created_at = _parse_dotnet_timestamp(str(record.get("CreatedAt") or ""))
        age_days = max((now - created_at) / 86400, 0)
        recency = 1 / (1 + age_days / 45)
        importance = _float(record.get("Importance"), 1.0)
        lane_boost = 0.08 if _is_knowledge_base(record) and query_lane != "general" and _product_lane(record) == query_lane else 0.0
        score = _dot(query_vector, [_float(value, 0.0) for value in vector]) + lane_boost + (importance * 0.04) + (recency * 0.02)
        if score <= 0.04:
            continue
        tags = record.get("Tags") or []
        results.append(
            {
                "id": record.get("Id"),
                "agent_name": row_agent,
                "text": text,
                "source": record.get("Source") or "desktop-json",
                "tags": ",".join(str(tag) for tag in tags if str(tag).strip()),
                "score": score,
            }
        )
    results.sort(key=lambda item: float(item.get("score") or 0), reverse=True)
    return results[: max(1, top_k)]


def sync_sqlite_rows_to_desktop_json(
    *,
    path: Path,
    rows: list[dict[str, Any]],
) -> int:
    stored = 0
    for row in rows:
        memory_id = remember_desktop_json(
            path=path,
            agent_name=str(row.get("agent_name") or ""),
            text=str(row.get("text") or ""),
            source=str(row.get("source") or "sqlite-memory"),
            tags=list(row.get("tags") or []),
            importance=float(row.get("importance") or 1.0),
        )
        if memory_id:
            stored += 1
    return stored


def hash_embedding(text: str, dimensions: int = DIMENSIONS) -> list[float]:
    vector = [0.0] * dimensions
    for token in _tokenize(text):
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        value = int.from_bytes(digest[:8], "little", signed=False)
        index = value % dimensions
        sign = 1.0 if (value & (1 << 63)) == 0 else -1.0
        vector[index] += sign
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0:
        return vector
    return [value / norm for value in vector]


def load_desktop_records(path: Path) -> list[dict[str, Any]]:
    """Public read of the desktop vector store (tolerant of concurrent writers)."""
    return _load(path)


def parse_desktop_timestamp(value: str) -> float:
    """Public parse of the .NET-style CreatedAt timestamps used in the store."""
    return _parse_dotnet_timestamp(value)


def _load(path: Path) -> list[dict[str, Any]]:
    records = _try_load(path)
    return records if records is not None else []


def _try_load(path: Path, attempts: int = 3) -> list[dict[str, Any]] | None:
    """Load the store; returns None when the file exists but is unreadable.

    The desktop app writes this file non-atomically, so a read can catch it
    mid-write. Retry briefly before giving up.
    """
    if not path.exists():
        return []
    for attempt in range(attempts):
        try:
            signature = _file_signature(path)
            cached = _cached_records(path, signature)
            if cached is not None:
                return cached
            data = json.loads(path.read_text(encoding="utf-8-sig"))
        except FileNotFoundError:
            return []
        except Exception:
            if attempt + 1 < attempts:
                time.sleep(0.08 * (attempt + 1))
            continue
        if not isinstance(data, list):
            return None
        records = [record for record in data if isinstance(record, dict)]
        _cache_records(path, signature, records)
        return list(records)
    return None


@contextmanager
def _file_lock(path: Path) -> Iterator[None]:
    """Best-effort cross-process lock via an exclusive sibling .lock file."""
    lock_path = path.with_name(path.name + ".lock")
    deadline = time.time() + LOCK_TIMEOUT_SECONDS
    acquired = False
    while True:
        try:
            handle = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(handle)
            acquired = True
            break
        except FileExistsError:
            try:
                if time.time() - lock_path.stat().st_mtime > LOCK_STALE_SECONDS:
                    lock_path.unlink(missing_ok=True)
                    continue
            except OSError:
                pass
            if time.time() >= deadline:
                break  # proceed unlocked rather than dropping the memory
            time.sleep(0.05)
        except OSError:
            break
    try:
        yield
    finally:
        if acquired:
            try:
                lock_path.unlink(missing_ok=True)
            except OSError:
                pass


def _save_atomic(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(records, handle, indent=2)
        handle.write("\n")
        temp_name = handle.name
    temp_path = Path(temp_name)
    for attempt in range(4):
        try:
            temp_path.replace(path)
            _cache_records(path, _file_signature(path), records)
            return
        except OSError:
            # Windows can refuse the replace while the desktop app holds the
            # file open; retry briefly before surfacing the error.
            if attempt == 3:
                temp_path.unlink(missing_ok=True)
                raise
            time.sleep(0.1 * (attempt + 1))


def _tokenize(text: str) -> list[str]:
    return [match.group(0).lower() for match in TOKEN_RE.finditer(text)]


def _fingerprint(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest().upper()


def _dot(left: list[float], right: list[float]) -> float:
    return sum(a * b for a, b in zip(left, right))


def _dotnet_timestamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + f".{int((time.time() % 1) * 1_000_0000):07d}+00:00"


def _parse_dotnet_timestamp(value: str) -> float:
    if not value:
        return 0.0
    normalized = re.sub(r"(\.\d{6})\d+", r"\1", value.replace("Z", "+00:00"))
    try:
        from datetime import datetime

        return datetime.fromisoformat(normalized).timestamp()
    except Exception:
        return 0.0


def _infer_product_lane(text: str) -> str:
    raw = text.lower()
    compact = re.sub(r"[^a-z0-9]+", "_", raw).strip("_")
    if any(term in compact for term in ("nova_wave",)) or any(term in raw for term in ("nova wave", "wave backoffice", "super nova", "nextgen", "next gen")):
        return "nova_wave"
    if any(term in compact for term in ("nova_classic",)) or any(term in raw for term in ("nova classic", "novapos", "nova pos", "sales screen")):
        return "nova_classic"
    if any(term in raw for term in ("billing", "chargify", "maxio", "subscription", "past due", "payment method")):
        return "billing"
    return "general"


def _should_include_for_lane(record: dict[str, Any], query_lane: str) -> bool:
    if not _is_knowledge_base(record):
        return True
    record_lane = _product_lane(record)
    if query_lane == "general":
        return record_lane == "general"
    return record_lane in {query_lane, "general"}


def _is_knowledge_base(record: dict[str, Any]) -> bool:
    return any(str(tag).lower() == "knowledgebase" for tag in record.get("Tags") or [])


def _product_lane(record: dict[str, Any]) -> str:
    for tag in record.get("Tags") or []:
        raw = str(tag)
        if raw.lower().startswith("product_lane:"):
            lane = raw.split(":", 1)[1].strip().lower()
            if lane in {"nova_wave", "nova_classic", "billing", "general"}:
                return lane
    return "general"


def _float(value: Any, fallback: float) -> float:
    try:
        return float(value)
    except Exception:
        return fallback


def _file_signature(path: Path) -> tuple[int, int]:
    stat = path.stat()
    return stat.st_mtime_ns, stat.st_size


def _cache_key(path: Path) -> str:
    try:
        return str(path.resolve())
    except OSError:
        return str(path.absolute())


def _cached_records(path: Path, signature: tuple[int, int]) -> list[dict[str, Any]] | None:
    with _CACHE_LOCK:
        cached = _RECORD_CACHE.get(_cache_key(path))
        if cached is None or cached[0] != signature:
            return None
        # Callers may append to the list during a mirrored write. Keep the
        # cached tuple immutable while reusing the parsed record dictionaries.
        return list(cached[1])


def _cache_records(path: Path, signature: tuple[int, int], records: list[dict[str, Any]]) -> None:
    with _CACHE_LOCK:
        _RECORD_CACHE[_cache_key(path)] = (signature, tuple(records))
