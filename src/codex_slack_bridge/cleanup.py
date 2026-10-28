# AgentChat/coding_agent 2026-07-10T00:42:00Z
from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


JUNK_DIR_NAMES = {
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".cache",
    "tmp",
    "temp",
    "scratch",
}

JUNK_FILE_NAMES = {
    ".DS_Store",
    "Thumbs.db",
}

JUNK_SUFFIXES = {
    ".pyc",
    ".pyo",
    ".tmp",
    ".temp",
    ".bak",
    ".orig",
    ".old",
    ".swp",
    ".swo",
}

JUNK_NAME_PREFIXES = (
    "tmp-",
    "tmp_",
    "temp-",
    "temp_",
    "scratch-",
    "scratch_",
)

JUNK_IMAGE_PREFIXES = (
    "screenshot",
    "screen",
    "edge-screen",
)


def cleanup_sandbox_junk(
    sandbox: Path,
    *,
    agent_name: str,
    source: str,
    job_id: str = "",
    created_after: float | None = None,
    log_path: Path | None = None,
) -> int:
    """Remove disposable files from one agent sandbox and audit every deletion."""
    try:
        root = sandbox.resolve()
    except OSError:
        return 0
    if not root.exists() or not root.is_dir():
        return 0

    removed = 0
    for path in sorted(root.rglob("*"), key=lambda item: len(item.parts), reverse=True):
        try:
            resolved = path.resolve()
            resolved.relative_to(root)
        except (OSError, ValueError):
            continue
        if created_after is not None and _mtime(resolved) < created_after:
            continue
        try:
            if resolved.is_dir() and resolved.name in JUNK_DIR_NAMES:
                shutil.rmtree(resolved)
                removed += 1
                _write_cleanup_log(log_path, agent_name, source, job_id, resolved, "remove_dir", "sandbox_junk_dir")
                continue
            if resolved.is_file() and _is_junk_file(resolved):
                resolved.unlink()
                removed += 1
                _write_cleanup_log(log_path, agent_name, source, job_id, resolved, "remove_file", "sandbox_junk_file")
        except OSError:
            continue
    return removed


def _is_junk_file(path: Path) -> bool:
    name = path.name
    lower_name = name.lower()
    suffix = path.suffix.lower()
    if name in JUNK_FILE_NAMES or suffix in JUNK_SUFFIXES:
        return True
    if lower_name.startswith(JUNK_NAME_PREFIXES):
        return True
    if suffix in {".png", ".jpg", ".jpeg"} and lower_name.startswith(JUNK_IMAGE_PREFIXES):
        return True
    return False


def _mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _write_cleanup_log(
    log_path: Path | None,
    agent_name: str,
    source: str,
    job_id: str,
    path: Path,
    action: str,
    reason: str,
) -> None:
    if log_path is None:
        return
    record: dict[str, Any] = {
        "atUtc": datetime.now(timezone.utc).isoformat(),
        "agentName": agent_name,
        "source": source,
        "jobId": job_id,
        "action": action,
        "reason": reason,
        "path": str(path),
    }
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        return
