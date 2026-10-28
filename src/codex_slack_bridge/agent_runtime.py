from __future__ import annotations

# AgentChat/coding_agent 2026-07-10T17:07:00-04:00: version warm sessions by their static prompt fingerprint.
# AgentChat/coding_agent 2026-07-11T11:32:00-04:00: make runtime-lock recovery PID-safe and observable.
# AgentChat/coding_agent 2026-07-11T11:45:00-04:00: serialize and compact the cross-process session registry.

import json
import os
import re
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Any

# AgentChat/direct_codex 2026-07-13T00:16:00-04:00: keep shared-session locks owned by the gateway attempt.

from .config import expand_env


SESSION_ID_RE = re.compile(r"\bsession id:\s*([0-9a-fA-F]{8}-[0-9a-fA-F-]{27,})", re.IGNORECASE)
SESSION_STORE_COMPACT_BYTES = 1024 * 1024


@dataclass(frozen=True)
class AgentSessionRecord:
    key: str
    agent_name: str
    surface: str
    conversation_id: str
    provider: str
    workspace: str
    session_id: str
    status: str
    updated_at: float
    job_id: int | None = None
    model: str = ""
    effort: str = ""
    prompt_fingerprint: str = ""
    note: str = ""


@dataclass(frozen=True)
class AgentRuntimeIdentity:
    surface: str
    conversation_id: str
    original_surface: str
    original_conversation_id: str
    shared: bool


class AgentSessionStore:
    def __init__(self, path: str | Path) -> None:
        self.path = _resolve_runtime_path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()

    @staticmethod
    def key(agent_name: str, surface: str, conversation_id: str) -> str:
        return f"{_safe_part(agent_name)}::{_safe_part(surface)}::{conversation_id.strip()}"

    def get(self, *, agent_name: str, surface: str, conversation_id: str) -> AgentSessionRecord | None:
        key = self.key(agent_name, surface, conversation_id)
        latest: AgentSessionRecord | None = None
        for record in self._read_records():
            if record.key == key:
                latest = record
        if latest and latest.status != "cleared" and latest.session_id:
            return latest
        return None

    def upsert(
        self,
        *,
        agent_name: str,
        surface: str,
        conversation_id: str,
        provider: str,
        workspace: str,
        session_id: str,
        status: str,
        job_id: int | None = None,
        model: str = "",
        effort: str = "",
        prompt_fingerprint: str = "",
        note: str = "",
    ) -> None:
        record = {
            "schemaVersion": 2,
            "key": self.key(agent_name, surface, conversation_id),
            "agentName": agent_name,
            "surface": surface,
            "conversationId": conversation_id,
            "provider": provider,
            "workspace": workspace,
            "sessionId": session_id,
            "status": status,
            "jobId": job_id,
            "model": model,
            "effort": effort,
            "promptFingerprint": prompt_fingerprint,
            "note": note,
            # Keep the cross-surface registry compatible with desktop clients
            # that historically modeled this field as an integer epoch value.
            "updatedAt": int(time.time()),
            "updatedAtUtc": _utc_now_iso(),
        }
        self._append(record)

    def clear(
        self,
        *,
        agent_name: str,
        surface: str,
        conversation_id: str,
        provider: str = "codex_cli",
        workspace: str = "",
        job_id: int | None = None,
        note: str = "cleared",
    ) -> None:
        self.upsert(
            agent_name=agent_name,
            surface=surface,
            conversation_id=conversation_id,
            provider=provider,
            workspace=workspace,
            session_id="",
            status="cleared",
            job_id=job_id,
            note=note,
        )

    def latest_records(self, *, limit: int | None = None) -> list[AgentSessionRecord]:
        latest: dict[str, AgentSessionRecord] = {}
        for record in self._read_records():
            latest[record.key] = record
        records = sorted(latest.values(), key=lambda item: item.updated_at, reverse=True)
        if limit is not None:
            return records[: max(0, int(limit))]
        return records

    def _append(self, record: dict[str, Any]) -> None:
        line = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
        with self._lock:
            with _cross_process_file_guard(self.path.with_suffix(self.path.suffix + ".lock")):
                with self.path.open("a", encoding="utf-8") as handle:
                    handle.write(line + "\n")
                    handle.flush()
                    os.fsync(handle.fileno())
                if self.path.stat().st_size >= SESSION_STORE_COMPACT_BYTES:
                    self._compact_locked()

    def _compact_locked(self) -> None:
        latest = {record.key: record for record in self._read_records() if record.key}
        temp_path = self.path.with_suffix(self.path.suffix + f".{os.getpid()}.tmp")
        try:
            with temp_path.open("w", encoding="utf-8") as handle:
                for record in sorted(latest.values(), key=lambda item: item.updated_at):
                    handle.write(json.dumps(_session_record_dict(record), ensure_ascii=False, separators=(",", ":")) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, self.path)
        finally:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass

    def _read_records(self) -> list[AgentSessionRecord]:
        if not self.path.exists():
            return []
        records: list[AgentSessionRecord] = []
        try:
            lines = self.path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return []
        for line in lines:
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            records.append(
                AgentSessionRecord(
                    key=str(item.get("key") or ""),
                    agent_name=str(item.get("agentName") or ""),
                    surface=str(item.get("surface") or ""),
                    conversation_id=str(item.get("conversationId") or ""),
                    provider=str(item.get("provider") or ""),
                    workspace=str(item.get("workspace") or ""),
                    session_id=str(item.get("sessionId") or ""),
                    status=str(item.get("status") or ""),
                    updated_at=float(item.get("updatedAt") or 0),
                    job_id=_optional_int(item.get("jobId")),
                    model=str(item.get("model") or ""),
                    effort=str(item.get("effort") or ""),
                    prompt_fingerprint=str(item.get("promptFingerprint") or ""),
                    note=str(item.get("note") or ""),
                )
            )
        return records


@contextmanager
def _cross_process_file_guard(path: Path):
    """Serialize session appends and compaction across bridge processes."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:  # pragma: no cover - Windows is the production runtime.
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _session_record_dict(record: AgentSessionRecord) -> dict[str, Any]:
    return {
        "schemaVersion": 2,
        "key": record.key,
        "agentName": record.agent_name,
        "surface": record.surface,
        "conversationId": record.conversation_id,
        "provider": record.provider,
        "workspace": record.workspace,
        "sessionId": record.session_id,
        "status": record.status,
        "jobId": record.job_id,
        "model": record.model,
        "effort": record.effort,
        "promptFingerprint": record.prompt_fingerprint,
        "note": record.note,
        "updatedAt": int(record.updated_at),
        "updatedAtUtc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(record.updated_at)),
    }


def extract_codex_session_id(*parts: str) -> str:
    for part in parts:
        match = SESSION_ID_RE.search(part or "")
        if match:
            return match.group(1).lower()
    return ""


def session_store_from_agent(agent: dict[str, Any]) -> AgentSessionStore:
    raw = str(agent.get("agent_runtime_session_store_path") or "data/agent_runtime/sessions.jsonl")
    return AgentSessionStore(raw)


def runtime_identity(
    *,
    agent_name: str,
    agent: dict[str, Any],
    surface: str,
    conversation_id: str,
    variant: str = "",
) -> AgentRuntimeIdentity:
    raw_scope = str(agent.get("agent_runtime_session_scope") or "").strip().lower()
    shared = _truthy(agent.get("agent_runtime_shared_sessions", False)) or raw_scope in {
        "agent",
        "agent_lane",
        "lane",
        "shared",
        "shared_agent",
    }
    clean_conversation_id = conversation_id.strip()
    clean_variant = _safe_part(variant.strip()) if variant.strip() else ""
    if shared:
        return AgentRuntimeIdentity(
            surface="shared",
            conversation_id=(
                f"agent:{agent_name}:variant:{clean_variant}"
                if clean_variant
                else f"agent:{agent_name}"
            ),
            original_surface=surface,
            original_conversation_id=clean_conversation_id,
            shared=True,
        )
    return AgentRuntimeIdentity(
        surface=surface,
        conversation_id=(
            f"{clean_conversation_id}:variant:{clean_variant}"
            if clean_variant
            else clean_conversation_id
        ),
        original_surface=surface,
        original_conversation_id=clean_conversation_id,
        shared=False,
    )


def runtime_lock_root_from_agent(agent: dict[str, Any]) -> Path:
    raw = str(agent.get("agent_runtime_lock_root") or "data/agent_runtime/locks")
    return _resolve_runtime_path(raw)


def cleanup_stale_runtime_locks(root: Path, *, stale_seconds: int) -> list[dict[str, Any]]:
    """Remove recoverable orphan locks and return secret-free owner evidence."""
    removed: list[dict[str, Any]] = []
    try:
        paths = sorted(path for path in root.glob("*.lock") if path.is_file())
    except OSError:
        return removed
    for path in paths:
        owner: dict[str, Any] = {}
        pid: int | None = None
        try:
            item = json.loads(path.read_text(encoding="utf-8", errors="replace"))
            if isinstance(item, dict):
                pid = _optional_int(item.get("pid"))
                raw_owner = item.get("owner")
                if isinstance(raw_owner, dict):
                    owner = dict(raw_owner)
        except (OSError, json.JSONDecodeError):
            pass
        if _remove_stale_lock(path, stale_seconds):
            removed.append({"name": path.name, "path": str(path), "pid": pid, "owner": owner})
    return removed


class AgentRuntimeLock:
    def __init__(self, path: Path, token: str) -> None:
        self.path = path
        self.token = token
        self.acquired = False

    @classmethod
    def acquire(
        cls,
        *,
        root: Path,
        lock_key: str,
        owner: dict[str, Any],
        wait_seconds: int,
        stale_seconds: int,
        poll_seconds: float = 1.0,
    ) -> "AgentRuntimeLock":
        root.mkdir(parents=True, exist_ok=True)
        token = f"{os.getpid()}-{time.time_ns()}"
        path = root / f"{_safe_part(lock_key)}.lock"
        deadline = time.time() + max(1, wait_seconds)
        lock = cls(path, token)
        while True:
            try:
                record = {
                    "schemaVersion": 1,
                    "token": token,
                    "pid": os.getpid(),
                    "processStartedAt": _process_started_at(os.getpid()),
                    "owner": owner,
                    "createdAt": time.time(),
                    "createdAtUtc": _utc_now_iso(),
                }
                fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                try:
                    with os.fdopen(fd, "w", encoding="utf-8") as handle:
                        handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")))
                        handle.write("\n")
                except Exception:
                    try:
                        os.close(fd)
                    except OSError:
                        pass
                    raise
                lock.acquired = True
                return lock
            except FileExistsError:
                if _remove_stale_lock(path, stale_seconds):
                    continue
                if time.time() >= deadline:
                    raise TimeoutError(f"Timed out waiting for agent runtime lock: {path}")
                time.sleep(max(0.2, poll_seconds))

    def release(self) -> None:
        if not self.acquired:
            return
        try:
            raw = self.path.read_text(encoding="utf-8", errors="replace")
            if f'"token":"{self.token}"' in raw or f'"token": "{self.token}"' in raw:
                self.path.unlink(missing_ok=True)
        except OSError:
            pass
        finally:
            self.acquired = False

    def set_child_process(self, pid: int) -> None:
        """Bind the lock to the disposable CLI child that is doing the work."""
        if not self.acquired or pid <= 0:
            return
        try:
            raw = self.path.read_text(encoding="utf-8", errors="replace")
            item = json.loads(raw)
            if not isinstance(item, dict) or str(item.get("token") or "") != self.token:
                return
            item["childPid"] = pid
            item["childProcessStartedAt"] = _process_started_at(pid)
            replacement = json.dumps(item, ensure_ascii=False, separators=(",", ":")) + "\n"
            # The token check prevents one job from updating a successor's lock.
            if self.path.read_text(encoding="utf-8", errors="replace") != raw:
                return
            self.path.write_text(replacement, encoding="utf-8")
        except (OSError, json.JSONDecodeError):
            return

    def __enter__(self) -> "AgentRuntimeLock":
        return self

    def __exit__(self, _exc_type: Any, _exc: Any, _tb: Any) -> None:
        self.release()


def persistent_sessions_enabled(agent: dict[str, Any], *, ephemeral: bool) -> bool:
    return bool(agent.get("persistent_agent_sessions", True)) and not ephemeral


def looks_like_missing_session(stderr: str, stdout: str = "") -> bool:
    text = f"{stderr}\n{stdout}".lower()
    needles = (
        "session not found",
        "no session",
        "could not find session",
        "unknown session",
        "not a saved session",
        "failed to load session",
    )
    return any(needle in text for needle in needles)


def looks_like_poisoned_resume(stderr: str, stdout: str = "", final_message: str = "") -> bool:
    """Detect a resumed Codex session that exits during context/bootstrap loading."""
    if str(stdout or "").strip() or str(final_message or "").strip():
        return False
    text = str(stderr or "").lower()
    explicit = (
        "context window exceeded",
        "context length exceeded",
        "prompt is too long",
        "input is too large",
        "conversation is too long",
        "failed to compact",
    )
    if any(needle in text for needle in explicit):
        return True
    # Codex 0.144 can print only the resumed session header and a truncated copy
    # of the prompt before returning 1, with no actual response or error line.
    return bool(SESSION_ID_RE.search(text)) and "openai codex v" in text and "[truncated]" in text


def _resolve_runtime_path(path: str | Path) -> Path:
    value = Path(str(expand_env(path))).expanduser()
    if not value.is_absolute():
        value = Path.cwd() / value
    return value.resolve()


def _safe_part(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in value.strip())
    return cleaned or "unknown"


def _optional_int(value: Any) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _remove_stale_lock(path: Path, stale_seconds: int) -> bool:
    """Remove a lock only when its owner is dead, or it is unreadable and old.

    A live process is never evicted by age.  This is deliberately conservative:
    long Codex runs are valid, and deleting their lock would allow duplicate work.
    """
    try:
        stat = path.stat()
    except OSError:
        return True
    lock_age = time.time() - stat.st_mtime
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
        item = json.loads(raw)
    except (OSError, json.JSONDecodeError):
        item = None

    if isinstance(item, dict):
        # The gateway owns the session lease. A direct CLI child can exit while
        # the gateway is still draining output and fencing the attempt; treating
        # that child exit as lock authority permits a second writer into the same
        # shared session. Child health is watchdog evidence only.
        owner_pid = _optional_int(item.get("pid"))
        owner_started_at = _optional_float(item.get("processStartedAt"))
        if owner_pid:
            if _process_matches(owner_pid, owner_started_at):
                return False
            # Give a newly-created lock time to finish being written and become
            # visible to process inspection before declaring its owner dead.
            if lock_age < 30:
                return False
        elif lock_age < max(30, stale_seconds):
            return False
    elif lock_age < max(30, stale_seconds):
        return False

    try:
        # Do not unlink a replacement lock created after our inspection.
        if path.read_text(encoding="utf-8", errors="replace") != raw:
            return False
        path.unlink(missing_ok=True)
        return True
    except OSError:
        return False


def _lock_owner_process_exited(path: Path) -> bool:
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
        item = json.loads(raw)
        owner_pid = int(item.get("pid") or 0)
        owner_started_at = _optional_float(item.get("processStartedAt"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return False
    if owner_pid <= 0:
        return False
    return not _process_matches(owner_pid, owner_started_at)


def _process_matches(pid: int, expected_started_at: float | None) -> bool:
    if not _process_exists(pid):
        return False
    if expected_started_at is None:
        return True
    actual_started_at = _process_started_at(pid)
    if actual_started_at is None:
        # Failure to inspect a live process is not evidence that it is stale.
        return True
    return abs(actual_started_at - expected_started_at) <= 2.0


def _process_started_at(pid: int) -> float | None:
    if os.name != "nt":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = ctypes.windll.kernel32.OpenProcess(
            PROCESS_QUERY_LIMITED_INFORMATION,
            False,
            wintypes.DWORD(pid),
        )
        if not handle:
            return None
        try:
            creation = wintypes.FILETIME()
            exit_time = wintypes.FILETIME()
            kernel = wintypes.FILETIME()
            user = wintypes.FILETIME()
            if not ctypes.windll.kernel32.GetProcessTimes(
                handle,
                ctypes.byref(creation),
                ctypes.byref(exit_time),
                ctypes.byref(kernel),
                ctypes.byref(user),
            ):
                return None
            ticks = (creation.dwHighDateTime << 32) | creation.dwLowDateTime
            return (ticks - 116444736000000000) / 10_000_000
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
    except Exception:
        return None


def _process_exists(pid: int) -> bool:
    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes

            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            handle = ctypes.windll.kernel32.OpenProcess(
                PROCESS_QUERY_LIMITED_INFORMATION,
                False,
                wintypes.DWORD(pid),
            )
            if not handle:
                return False
            try:
                exit_code = wintypes.DWORD()
                if not ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                    return False
                return exit_code.value == 259
            finally:
                ctypes.windll.kernel32.CloseHandle(handle)
        except Exception:
            return True
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return True


def _utc_now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _optional_float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None
