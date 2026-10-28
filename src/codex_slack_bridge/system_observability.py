from __future__ import annotations

# AgentChat/coding_agent 2026-07-11T11:32:00-04:00: proactively recover dead runtime locks and stale job state.

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .agent_display import public_agent_name
# AgentChat/direct_codex 2026-07-13T00:16:00-04:00: separate gateway lease health from child-process health.

from .agent_runtime import cleanup_stale_runtime_locks, runtime_lock_root_from_agent, session_store_from_agent
from .config import BridgeConfig
from .memory import redact_secrets
from .state import BridgeState


ACTIVE_JOB_STATUSES = {"queued", "running"}


def build_system_status(
    config: BridgeConfig,
    state: BridgeState,
    *,
    bridge_started_at: float | None = None,
    command_center_jobs: list[dict[str, Any]] | None = None,
    live_bridge_job_ids: set[int] | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    limit = max(1, min(int(limit or 20), 100))
    now = time.time()
    reconciliation = None
    if live_bridge_job_ids is not None:
        reconciliation = reconcile_system_jobs(
            config,
            state,
            runtime_job_ids=live_bridge_job_ids,
            command_center_jobs=command_center_jobs,
            authoritative=True,
            channel_id="command_center",
            now=now,
        )
    agents = _agent_summaries(config)
    active_jobs = [_format_bridge_job(row, now) for row in state.list_jobs(statuses=ACTIVE_JOB_STATUSES, limit=limit)]
    recent_jobs = [_format_bridge_job(row, now) for row in state.list_jobs(limit=limit)]
    snapshot = {
        "ok": True,
        "service": "codex-agent-system",
        "generatedAtUtc": _utc_now(),
        "uptimeSeconds": int(now - bridge_started_at) if bridge_started_at is not None else None,
        "workerCapacity": int(config.defaults.get("max_workers", 3)),
        "agents": agents,
        "bridgeJobs": {
            "counts": state.job_counts(),
            "active": active_jobs,
            "recent": recent_jobs,
        },
        "sessions": _session_summaries(config, limit=limit),
        "locks": _lock_summaries(config, now=now),
    }
    if reconciliation is not None:
        snapshot["reconciliation"] = reconciliation
    if command_center_jobs is not None:
        snapshot["commandCenterJobs"] = {
            "active": [
                _format_command_center_job(job, now)
                for job in command_center_jobs
                if str(job.get("status") or "").lower() in ACTIVE_JOB_STATUSES
            ][:limit],
            "recent": [_format_command_center_job(job, now) for job in command_center_jobs[:limit]],
        }
    return snapshot


def reconcile_system_jobs(
    config: BridgeConfig,
    state: BridgeState,
    *,
    runtime_job_ids: set[int] | None,
    command_center_jobs: list[dict[str, Any]] | None = None,
    authoritative: bool = False,
    channel_id: str | None = "command_center",
    stale_after_seconds: float | None = None,
    now: float | None = None,
) -> dict[str, Any]:
    """Build conservative job evidence and reconcile the durable bridge ledger.

    Scheduler membership and a live lock PID are strong evidence. A recently
    updated session or an active pause/recovery manifest only protects a job
    temporarily. Persisted terminal command-center records are terminal truth.
    """

    observed_at = float(now if now is not None else time.time())
    stale_after = float(
        stale_after_seconds
        if stale_after_seconds is not None
        else config.defaults.get("job_reconciliation_stale_seconds", 300)
    )
    live_ids = {_optional_int(value) for value in (runtime_job_ids or set())}
    strong_live_ids = {value for value in live_ids if value is not None}
    protected_ids: set[int] = set()
    review_ids: set[int] = set()
    terminal_statuses: dict[int, str] = {}
    reasons: dict[int, str] = {}

    removed_locks = _recover_stale_runtime_locks(config)
    removed_lock_job_ids = {
        value
        for lock in removed_locks
        for value in [_optional_int((lock.get("owner") or {}).get("jobId") if isinstance(lock.get("owner"), dict) else None)]
        if value is not None
    }
    _mark_interrupted_sessions(config, removed_lock_job_ids)

    locks = _lock_summaries(config, now=observed_at)
    for lock in locks:
        owner = lock.get("owner") if isinstance(lock.get("owner"), dict) else {}
        job_id = _optional_int(owner.get("jobId"))
        if job_id is not None and lock.get("ownerProcessAlive") is True:
            strong_live_ids.add(job_id)

    session_grace = float(config.defaults.get("job_reconciliation_session_grace_seconds", stale_after))
    for session in _session_summaries(config, limit=500):
        job_id = _optional_int(session.get("jobId"))
        age = _optional_float(session.get("ageSeconds"))
        status = str(session.get("status") or "").strip().lower()
        if job_id is not None and status in {"queued", "running", "resuming"} and age is not None and age <= session_grace:
            protected_ids.add(job_id)

    external_to_bridge: dict[str, int] = {}
    for job in command_center_jobs or []:
        if not isinstance(job, dict):
            continue
        job_id = _optional_int(job.get("bridgeJobId") or job.get("bridge_job_id"))
        if job_id is None:
            continue
        external_id = str(job.get("id") or "")
        if external_id:
            external_to_bridge[external_id] = job_id
        status = str(job.get("status") or "").strip().lower()
        if status in {
            "blocked",
            "cancelled",
            "completed",
            "completed_with_issues",
            "failed",
            "interrupted",
            "recovery_review_required",
            "superseded",
            "unclassified",
        }:
            terminal_statuses[job_id] = status
            reasons[job_id] = f"Command-center job {external_id or job_id} reported {status}."

    manifest = _recovery_manifest(config)
    captured_by_external: dict[str, int] = {}
    for captured in manifest.get("jobs") or []:
        if not isinstance(captured, dict):
            continue
        external_id = str(captured.get("id") or "")
        bridge_id = _optional_int(captured.get("bridgeJobId") or captured.get("bridge_job_id"))
        if bridge_id is None:
            bridge_id = external_to_bridge.get(external_id)
        if bridge_id is not None and external_id:
            captured_by_external[external_id] = bridge_id

    for external_id in manifest.get("reviewRequiredJobIds") or []:
        bridge_id = captured_by_external.get(str(external_id)) or external_to_bridge.get(str(external_id))
        if bridge_id is not None:
            review_ids.add(bridge_id)
            reasons[bridge_id] = f"Restart recovery marked command-center job {external_id} for operator review."

    if str(manifest.get("state") or "") in {"paused", "active_recovery"}:
        recovery_ids = set(str(value) for value in (manifest.get("pendingRecoveryJobIds") or []))
        recovery_ids.update(str(value) for value in (manifest.get("recoveredJobIds") or []))
        if str(manifest.get("state") or "") == "paused":
            recovery_ids.update(captured_by_external)
        for external_id in recovery_ids:
            bridge_id = captured_by_external.get(external_id) or external_to_bridge.get(external_id)
            if bridge_id is not None:
                protected_ids.add(bridge_id)

    result = state.reconcile_active_jobs(
        live_job_ids=strong_live_ids if runtime_job_ids is not None else None,
        terminal_statuses=terminal_statuses,
        protected_job_ids=protected_ids,
        recovery_review_job_ids=review_ids,
        channel_id=channel_id,
        stale_after_seconds=stale_after,
        authoritative=authoritative,
        now=observed_at,
        reasons=reasons,
    )
    result["evidence"] = {
        "schedulerJobIds": sorted(value for value in live_ids if value is not None),
        "liveLockJobIds": sorted(strong_live_ids - {value for value in live_ids if value is not None}),
        "recentSessionJobIds": sorted(protected_ids),
        "terminalJobIds": sorted(terminal_statuses),
        "recoveryReviewJobIds": sorted(review_ids),
        "removedStaleLockJobIds": sorted(removed_lock_job_ids),
        "removedStaleLocks": sorted(str(lock.get("name") or "") for lock in removed_locks),
    }
    return result


def format_system_status_for_slack(snapshot: dict[str, Any]) -> str:
    bridge_jobs = snapshot.get("bridgeJobs") if isinstance(snapshot.get("bridgeJobs"), dict) else {}
    active_jobs = bridge_jobs.get("active") if isinstance(bridge_jobs.get("active"), list) else []
    recent_jobs = bridge_jobs.get("recent") if isinstance(bridge_jobs.get("recent"), list) else []
    sessions = snapshot.get("sessions") if isinstance(snapshot.get("sessions"), list) else []
    locks = snapshot.get("locks") if isinstance(snapshot.get("locks"), list) else []
    agents = snapshot.get("agents") if isinstance(snapshot.get("agents"), list) else []
    counts = bridge_jobs.get("counts") if isinstance(bridge_jobs.get("counts"), dict) else {}
    reconciliation = snapshot.get("reconciliation") if isinstance(snapshot.get("reconciliation"), dict) else {}

    active_count = len(active_jobs)
    worker_capacity = snapshot.get("workerCapacity") or "?"
    uptime = _age_label(snapshot.get("uptimeSeconds")) if snapshot.get("uptimeSeconds") is not None else "unknown"

    lines = [
        "*Agent system status*",
        f"- Active bridge jobs: `{active_count}` / `{worker_capacity}` worker slots; uptime `{uptime}`",
        f"- Job counts: {_format_counts(counts)}",
    ]
    reconciled = reconciliation.get("changed") if isinstance(reconciliation.get("changed"), list) else []
    if reconciled:
        transitions: dict[str, int] = {}
        for item in reconciled:
            if not isinstance(item, dict):
                continue
            label = f"{item.get('from') or 'unknown'}->{item.get('to') or 'unknown'}"
            transitions[label] = transitions.get(label, 0) + 1
        lines.append(f"- Reconciled stale ledger entries: {_format_counts(transitions)}")

    if active_jobs:
        lines.append("\n*Active jobs*")
        for job in active_jobs[:8]:
            lines.append(
                f"- `#{job.get('id')}` `{public_agent_name(job.get('agentName'))}` {job.get('status')} "
                f"for `{_surface_label(job)}`; age `{_age_label(job.get('ageSeconds'))}`; "
                f"{_compact(str(job.get('request') or ''), 110)}"
            )
    else:
        lines.append("\n*Active jobs*\n- None recorded in the bridge job store.")

    live_locks = [lock for lock in locks if lock.get("exists")]
    if live_locks:
        lines.append("\n*Runtime locks*")
        for lock in live_locks[:8]:
            owner = lock.get("owner") if isinstance(lock.get("owner"), dict) else {}
            owner_bits = [
                public_agent_name(owner.get("agentName"), fallback="").strip(),
                str(owner.get("surface") or "").strip(),
                str(owner.get("jobId") or "").strip(),
            ]
            owner_text = " / ".join(part for part in owner_bits if part) or "unknown owner"
            live_text = "live pid" if lock.get("processAlive") else "pid not live/unknown"
            lines.append(
                f"- `{lock.get('name')}` held `{_age_label(lock.get('ageSeconds'))}` by {owner_text} ({live_text})"
            )
    else:
        lines.append("\n*Runtime locks*\n- None currently held.")

    if sessions:
        lines.append("\n*Persistent sessions*")
        for session in sessions[:8]:
            session_id = str(session.get("sessionId") or "")
            session_short = session_id[:8] if session_id else "none"
            lines.append(
                f"- `{public_agent_name(session.get('agentName'))}` `{session.get('status')}` session `{session_short}` "
                f"updated `{_age_label(session.get('ageSeconds'))}`; {session.get('surface')}:{session.get('conversationId')}"
            )
    else:
        lines.append("\n*Persistent sessions*\n- No session records found.")

    if agents:
        lines.append("\n*Configured agents*")
        agent_bits = [
            f"`{public_agent_name(agent.get('name'))}` {agent.get('provider')} / {agent.get('sandbox')}"
            for agent in agents[:8]
        ]
        lines.append("- " + "; ".join(agent_bits))

    failures = [
        job for job in recent_jobs
        if str(job.get("status") or "").lower() in {
            "blocked",
            "completed_with_issues",
            "failed",
            "interrupted",
            "recovery_review_required",
            "unclassified",
        }
    ]
    if failures:
        lines.append("\n*Recent review/failure outcomes*")
        for job in failures[:3]:
            lines.append(
                f"- `#{job.get('id')}` `{public_agent_name(job.get('agentName'))}` "
                f"`{job.get('status')}` "
                f"{_compact(str(job.get('reviewReason') or job.get('error') or job.get('result') or job.get('request') or ''), 140)}"
            )

    return "\n".join(lines)


def _agent_summaries(config: BridgeConfig) -> list[dict[str, Any]]:
    agents: list[dict[str, Any]] = []
    for name, raw_agent in sorted(config.agents.items()):
        agent = dict(config.defaults)
        agent.update(raw_agent)
        agents.append(
            {
                "name": name,
                "provider": str(agent.get("provider") or ""),
                "workspaceRoot": str(agent.get("workspace_root") or ""),
                "sandbox": str(agent.get("sandbox") or ""),
                "persistentSessions": bool(agent.get("persistent_agent_sessions", True)),
                "sharedRuntimeSessions": bool(agent.get("agent_runtime_shared_sessions", False))
                or str(agent.get("agent_runtime_session_scope") or "").strip().lower()
                in {"agent", "agent_lane", "lane", "shared", "shared_agent"},
                "timeoutSeconds": _optional_int(agent.get("timeout_seconds")),
            }
        )
    return agents


def _session_summaries(config: BridgeConfig, *, limit: int) -> list[dict[str, Any]]:
    now = time.time()
    records_by_key: dict[str, dict[str, Any]] = {}
    for _name, agent in _merged_agents(config):
        try:
            store = session_store_from_agent(agent)
            for record in store.latest_records(limit=limit):
                records_by_key[record.key] = {
                    "key": record.key,
                    "agentName": record.agent_name,
                    "surface": record.surface,
                    "conversationId": record.conversation_id,
                    "provider": record.provider,
                    "workspace": record.workspace,
                    "sessionId": record.session_id,
                    "status": record.status,
                    "updatedAt": record.updated_at,
                    "updatedAtUtc": _iso_from_epoch(record.updated_at),
                    "ageSeconds": max(0, int(now - record.updated_at)) if record.updated_at else None,
                    "jobId": record.job_id,
                    "model": record.model,
                    "effort": record.effort,
                    "note": record.note,
                    "storePath": str(store.path),
                }
        except Exception:
            continue
    return sorted(records_by_key.values(), key=lambda item: float(item.get("updatedAt") or 0), reverse=True)[:limit]


def _lock_summaries(config: BridgeConfig, *, now: float) -> list[dict[str, Any]]:
    roots: dict[str, int] = {}
    for _name, agent in _merged_agents(config):
        try:
            root = runtime_lock_root_from_agent(agent)
            stale_seconds = int(agent.get("agent_runtime_lock_stale_seconds") or 7200)
            roots[str(root)] = max(roots.get(str(root), 0), stale_seconds)
        except Exception:
            continue

    locks: list[dict[str, Any]] = []
    for raw_root, stale_seconds in roots.items():
        root = Path(raw_root)
        try:
            paths = sorted(path for path in root.glob("*.lock") if path.is_file())
        except OSError:
            continue
        for path in paths:
            locks.append(_lock_summary(path, now=now, stale_seconds=stale_seconds))
    return sorted(locks, key=lambda item: float(item.get("ageSeconds") or 0), reverse=True)


def _recover_stale_runtime_locks(config: BridgeConfig) -> list[dict[str, Any]]:
    roots: dict[str, int] = {}
    for _name, agent in _merged_agents(config):
        try:
            root = runtime_lock_root_from_agent(agent)
            stale_seconds = int(agent.get("agent_runtime_lock_stale_seconds") or 7200)
            roots[str(root)] = max(roots.get(str(root), 0), stale_seconds)
        except Exception:
            continue
    removed: list[dict[str, Any]] = []
    for raw_root, stale_seconds in roots.items():
        removed.extend(cleanup_stale_runtime_locks(Path(raw_root), stale_seconds=stale_seconds))
    return removed


def _mark_interrupted_sessions(config: BridgeConfig, job_ids: set[int]) -> None:
    if not job_ids:
        return
    seen_stores: set[str] = set()
    for _name, agent in _merged_agents(config):
        try:
            store = session_store_from_agent(agent)
            if str(store.path) in seen_stores:
                continue
            seen_stores.add(str(store.path))
            for record in store.latest_records(limit=500):
                if record.job_id not in job_ids or record.status not in {"queued", "running", "resuming"}:
                    continue
                store.upsert(
                    agent_name=record.agent_name,
                    surface=record.surface,
                    conversation_id=record.conversation_id,
                    provider=record.provider,
                    workspace=record.workspace,
                    session_id=record.session_id,
                    status="interrupted",
                    job_id=record.job_id,
                    model=record.model,
                    effort=record.effort,
                    prompt_fingerprint=record.prompt_fingerprint,
                    note="owner process exited; safe to resume on the next authorized job",
                )
        except Exception:
            continue


def _recovery_manifest(config: BridgeConfig) -> dict[str, Any]:
    raw_path = str(
        config.defaults.get("command_center_pause_manifest_path")
        or "data/command_center/restart_manifest.json"
    )
    path = Path(os.path.expandvars(os.path.expanduser(raw_path)))
    try:
        item = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError):
        return {}
    return item if isinstance(item, dict) else {}


def _lock_summary(path: Path, *, now: float, stale_seconds: int) -> dict[str, Any]:
    try:
        stat = path.stat()
        age_seconds = max(0, int(now - stat.st_mtime))
    except OSError:
        stat = None
        age_seconds = None

    owner: dict[str, Any] = {}
    token = ""
    owner_pid: int | None = None
    owner_process_alive: bool | None = None
    child_pid: int | None = None
    child_process_alive: bool | None = None
    try:
        item = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        if isinstance(item, dict):
            token = str(item.get("token") or "")
            raw_owner = item.get("owner")
            if isinstance(raw_owner, dict):
                owner = raw_owner
            owner_pid = _optional_int(item.get("pid"))
            child_pid = _optional_int(item.get("childPid"))
            if owner_pid is not None:
                owner_process_alive = _process_exists(owner_pid)
            if child_pid is not None:
                child_process_alive = _process_exists(child_pid)
    except (OSError, json.JSONDecodeError):
        pass

    return {
        "name": path.name,
        "path": str(path),
        "exists": path.exists(),
        "token": token[:16],
        "pid": owner_pid,
        "processAlive": owner_process_alive,
        "ownerPid": owner_pid,
        "ownerProcessAlive": owner_process_alive,
        "childPid": child_pid,
        "childProcessAlive": child_process_alive,
        "owner": owner,
        "createdAtUtc": _iso_from_epoch(stat.st_ctime) if stat else "",
        "updatedAtUtc": _iso_from_epoch(stat.st_mtime) if stat else "",
        "ageSeconds": age_seconds,
        "staleAfterSeconds": stale_seconds,
        "staleByAge": age_seconds is not None and age_seconds >= stale_seconds,
    }


def _format_bridge_job(row: dict[str, object], now: float) -> dict[str, Any]:
    created_at = _optional_float(row.get("created_at"))
    started_at = _optional_float(row.get("started_at"))
    completed_at = _optional_float(row.get("completed_at"))
    reconciled_at = _optional_float(row.get("reconciled_at"))
    stage_updated_at = _optional_float(row.get("stage_updated_at"))
    heartbeat_at = _optional_float(row.get("heartbeat_at"))
    basis = started_at or created_at or now
    return {
        "id": row.get("id"),
        "eventId": row.get("event_id"),
        "channelId": row.get("channel_id"),
        "threadTs": row.get("thread_ts"),
        "userId": row.get("user_id"),
        "agentName": row.get("agent_name"),
        "status": row.get("status"),
        "request": _compact(redact_secrets(str(row.get("request_text") or "")), 500),
        "error": _compact(redact_secrets(str(row.get("error") or "")), 500),
        "result": _compact(redact_secrets(str(row.get("result_text") or "")), 1200),
        "needsReview": bool(row.get("needs_review")),
        "reviewReason": _compact(redact_secrets(str(row.get("review_reason") or "")), 500),
        "reviewedAtUtc": _iso_from_epoch(_optional_float(row.get("reviewed_at"))),
        "reviewResolution": _compact(redact_secrets(str(row.get("review_resolution") or "")), 500),
        "learningEligible": bool(row.get("learning_eligible")),
        "createdAt": created_at,
        "createdAtUtc": _iso_from_epoch(created_at),
        "startedAt": started_at,
        "startedAtUtc": _iso_from_epoch(started_at),
        "completedAt": completed_at,
        "completedAtUtc": _iso_from_epoch(completed_at),
        "reconciledAt": reconciled_at,
        "reconciledAtUtc": _iso_from_epoch(reconciled_at),
        "reconciliationReason": _compact(redact_secrets(str(row.get("reconciliation_reason") or "")), 500),
        "runtimeInstanceId": str(row.get("runtime_instance_id") or ""),
        "runtimeStage": str(row.get("runtime_stage") or ""),
        "stageAgeSeconds": max(0, int(now - stage_updated_at)) if stage_updated_at else None,
        "heartbeatAgeSeconds": max(0, int(now - heartbeat_at)) if heartbeat_at else None,
        "recoveryPolicy": str(row.get("recovery_policy") or ""),
        "recoveryCount": int(row.get("recovery_count") or 0),
        "ageSeconds": max(0, int(now - basis)) if basis else None,
    }


def _format_command_center_job(job: dict[str, Any], now: float) -> dict[str, Any]:
    created_at = _parse_iso(job.get("createdAtUtc"))
    updated_at = _parse_iso(job.get("updatedAtUtc"))
    basis = updated_at or created_at or now
    payload = job.get("payload") if isinstance(job.get("payload"), dict) else {}
    return {
        "id": str(job.get("id") or ""),
        "bridgeJobId": job.get("bridgeJobId") or job.get("bridge_job_id"),
        "agentName": str(job.get("agentName") or ""),
        "sourceType": str(job.get("sourceType") or ""),
        "status": str(job.get("status") or "queued"),
        "phase": str(job.get("phase") or ""),
        "laneKey": str(job.get("laneKey") or ""),
        "recoveryCount": int(job.get("recoveryCount") or 0),
        "title": _compact(str(payload.get("taskTitle") or payload.get("ticketNumber") or payload.get("type") or ""), 160),
        "prompt": _compact(redact_secrets(str(job.get("prompt") or "")), 500),
        "error": _compact(redact_secrets(str(job.get("error") or "")), 500),
        "result": _compact(redact_secrets(str(job.get("result") or "")), 1200),
        "needsReview": bool(job.get("needsReview")),
        "reviewReason": _compact(redact_secrets(str(job.get("reviewReason") or "")), 500),
        "learningEligible": bool(job.get("learningEligible")),
        "createdAtUtc": str(job.get("createdAtUtc") or ""),
        "updatedAtUtc": str(job.get("updatedAtUtc") or ""),
        "ageSeconds": max(0, int(now - basis)) if basis else None,
    }


def _merged_agents(config: BridgeConfig) -> list[tuple[str, dict[str, Any]]]:
    merged = []
    for name, raw_agent in sorted(config.agents.items()):
        agent = dict(config.defaults)
        agent.update(raw_agent)
        agent["name"] = name
        merged.append((name, agent))
    return merged


def _surface_label(job: dict[str, Any]) -> str:
    channel_id = str(job.get("channelId") or "")
    if channel_id == "command_center":
        return "command_center"
    return channel_id or "unknown"


def _format_counts(counts: dict[str, Any]) -> str:
    if not counts:
        return "`none`"
    order = [
        "queued",
        "running",
        "blocked",
        "completed_with_issues",
        "unclassified",
        "failed",
        "completed",
    ]
    parts = []
    for key in order:
        if key in counts:
            parts.append(f"{key}={counts[key]}")
    for key, value in sorted(counts.items()):
        if key not in order:
            parts.append(f"{key}={value}")
    return "`" + ", ".join(parts) + "`"


def _compact(text: str, limit: int) -> str:
    normalized = " ".join(text.replace("\r", " ").replace("\n", " ").split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: max(0, limit - 3)].rstrip() + "..."


def _age_label(value: Any) -> str:
    seconds = _optional_int(value)
    if seconds is None:
        return "unknown"
    if seconds < 60:
        return f"{seconds}s"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m"
    hours = minutes // 60
    if hours < 48:
        return f"{hours}h {minutes % 60}m"
    days = hours // 24
    return f"{days}d {hours % 24}h"


def _parse_iso(value: Any) -> float | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _iso_from_epoch(value: float | int | None) -> str:
    if value is None:
        return ""
    try:
        return datetime.fromtimestamp(float(value), tz=timezone.utc).isoformat()
    except (OSError, OverflowError, TypeError, ValueError):
        return ""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _optional_float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _optional_int(value: Any) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _process_exists(pid: int) -> bool:
    if pid <= 0:
        return False
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
            return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
