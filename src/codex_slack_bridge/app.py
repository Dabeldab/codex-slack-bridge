from __future__ import annotations

# AgentChat/coding_agent 2026-07-11T14:04:00-04:00: recover deduplicated desktop-to-Slack messages across restarts.
# AgentChat/direct_codex 2026-07-12T00:06:00-04:00: add hourly orchestration recovery and a lightweight Slack heartbeat.
# AgentChat/direct_codex 2026-07-13T00:16:00-04:00: add durable lane recovery and supervised worker fencing.
# AgentChat/coding_agent 2026-07-13T00:56:02-04:00: make Slack admission and watchdog recovery fail closed.
# AgentChat/direct_codex 2026-07-13T01:28:53-04:00: optimize bounded Slack attachment ingest and intent routing.
# AgentChat/direct_codex 2026-07-27T22:55:00Z: retry terminal Slack feedback from a durable delivery outbox.
# AgentChat/coding_agent 2026-07-30T17:15:00Z: bounded recovery, tracked handoff continuation, and verified route reuse.
# AgentChat/coding_agent 2026-07-30T17:30:00Z: keep compatibility runtime IDs out of public Slack labels.

import json
import logging
import os
import re
import subprocess
import time
import ctypes
import urllib.error
import urllib.parse
import urllib.request
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from threading import Event, Lock, Thread, Timer
from typing import Any

from dotenv import load_dotenv
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

from .agent_outcomes import AgentOutcome, AgentOutcomeStatus, classify_agent_outcome, first_nonempty_line
from .agent_runtime import runtime_identity, session_store_from_agent
from .agents import AgentRequest, agent_job_process_status, cancel_agent_job, grant_agent_file_access, run_agent_isolated
from .cleanup import cleanup_sandbox_junk
from .command_center_auth import read_command_center_bearer
from .config import BridgeConfig, ChannelRoute, load_config
from .cognitive_memory import CognitiveMemoryStore
from .fast_responder import try_fast_response
from .learning_registry import LearningProposalRegistry, ObservationOutcome
from .memory import MemoryStore, redact_secrets
from .observability import build_system_status, format_system_status_for_slack, reconcile_system_jobs
from .safety import sign_trusted_message
from .shared_artifacts import artifacts_for_job, format_recent_artifacts, register_artifact
from .shared_chat import append_chat_event, format_recent_chat
from .singapore_routing import (
    SingaporeIntent,
    classify_singapore_intent,
    is_singapore_notification_policy_request,
    is_singapore_run_request,
)
from .slack_files import (
    RETURN_FILE_EXTENSIONS,
    _validate_downloaded_content,
    download_event_files,
    event_has_files,
    file_sha256,
    format_files_for_prompt,
    split_upload_directives,
)
from .slack_text import chunk_for_slack, format_queued_steering_prompt, parse_steer_command, strip_bot_mentions
from .state import BridgeState
from .web_search import is_web_search_command, run_public_web_search, web_search_query
from .worker_reliability import (
    VERIFIED_ROUTE_RECEIPT_MARKER,
    VerifiedRouteReceipt,
    VerifiedRouteStore,
    bounded_retry_delays,
    classify_retryable_failure,
    execute_bounded_attempts,
    extract_verified_route_receipt,
    recovery_continuation_guidance,
)


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
LOGGER = logging.getLogger("codex_slack_bridge")
EXECUTOR: ThreadPoolExecutor | None = None
STATE: BridgeState | None = None
MEMORY: MemoryStore | None = None
COGNITIVE_MEMORY: CognitiveMemoryStore | None = None
LEARNING: LearningProposalRegistry | None = None
VERIFIED_ROUTES: VerifiedRouteStore | None = None
CHANNEL_LOCKS: dict[str, Lock] = {}
CHANNEL_LOCKS_LOCK = Lock()
AGENT_RUN_LOCKS: dict[str, Lock] = {}
AGENT_RUN_LOCKS_LOCK = Lock()
ACTIVE_JOB_IDS: set[int] = set()
ACTIVE_JOB_IDS_LOCK = Lock()
ACTIVE_JOB_CONTEXT: dict[int, tuple[str, str]] = {}
ACTIVE_JOB_FUTURES: dict[int, Future[Any]] = {}
ACTIVE_JOB_RETRY_TIMERS: dict[int, Timer] = {}
ACTIVE_JOB_CANCEL_REQUESTED_AT: dict[int, float] = {}
CANCELLED_JOB_IDS: set[int] = set()
RECOVERY_REVIEW_JOB_IDS: set[int] = set()
RUNTIME_INSTANCE_ID = f"slack:{os.getpid()}:{uuid.uuid4().hex[:12]}"
SLACK_CLIENT: Any | None = None
SLACK_CONFIG: BridgeConfig | None = None
STARTED_AT = time.time()


def _try_deterministic_location_region_update(
    config: BridgeConfig,
    request: AgentRequest,
) -> str | None:
    """Execute one exact Taylor-owned RegionId request before any model run."""

    if (
        request.job_id is None
        or request.authority_kind != "operator"
        or request.is_steering
        or (request.slack_event and event_has_files(request.slack_event))
    ):
        return None
    from .command_center_server import (
        _direct_location_region_update_request,
        _verified_location_region_result,
    )

    message = str(request.task_text or request.text or "").strip()
    target = _direct_location_region_update_request(message)
    if target is None:
        return None
    target["idempotencyKey"] = f"bridge-job:{request.job_id}"
    executor = str(
        (config.defaults or {}).get("nova_location_region_executor")
        or "/opt/nova/bin/run-nova-location-region"
    ).strip()
    completed = subprocess.run(
        [
            "/usr/bin/sudo",
            "-n",
            "-H",
            "-u",
            "nova-salesforce-broker",
            "--",
            executor,
        ],
        cwd="/",
        input=json.dumps(
            {"action": "update_location_region", **target},
            ensure_ascii=False,
        ),
        text=True,
        capture_output=True,
        timeout=180,
    )
    stdout = str(completed.stdout or "").strip()
    try:
        result = json.loads(stdout.splitlines()[-1]) if stdout else {}
    except (IndexError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            "deterministic location-region update returned invalid output"
        ) from exc
    if not _verified_location_region_result(result, target):
        error_type = str(result.get("errorType") or "UnverifiedLocationRegion")
        raise RuntimeError(
            f"deterministic location-region update stopped safely: {error_type}"
        )
    no_op = bool(result.get("noOp"))
    return (
        "COMPLETED\n"
        f"LocationId {target['locationId']} is verified at RegionId "
        f"{target['regionId']} in POS_{target['companyUsername']}. "
        + (
            "The requested state already existed, so no duplicate update ran."
            if no_op
            else "Taylor's typed broker committed the update once with backup and readback."
        )
    )

GENERIC_ATTACHMENT_TEXT_RE = re.compile(
    r"^\s*(?:user uploaded slack file\(s\).*|here(?:'s| is) (?:the |a )?file|here it is|"
    r"see (?:the )?attach(?:ed|ment)|attach(?:ed|ment)|file attach(?:ed|ment))\s*[.!]*\s*$",
    re.IGNORECASE,
)
READ_ONLY_ATTACHMENT_INTENT_RE = re.compile(
    r"\b(review|analy[sz]e|inspect|check|compare|summari[sz]e|extract|read|look at|explain|identify|find)\b",
    re.IGNORECASE,
)
MUTATING_ATTACHMENT_INTENT_RE = re.compile(
    r"\b(send|post|reply|forward|delete|remove|refund|credit|charge|close|create|update|edit|change|"
    r"upload|submit|deploy|restart|install|write|patch|merge|commit|push|execute|run)\b",
    re.IGNORECASE,
)
SINGAPORE_REACTIVATION_TARGET_RE = re.compile(
    r"\b(?:machine(?:\s+id)?|tenant(?:\s+id)?|server(?:\s+(?:key|id))?|interface(?:\s+id)?)"
    r"\s*(?:[:#=-]\s*)?(\d{5,10})\b",
    re.IGNORECASE,
)


# AgentChat/direct_codex 2026-07-11T14:25:00-04:00: prevent duplicate Slack gateways without periodic lock sweeping.
class SlackBridgeSingleInstanceGuard:
    """Keep one Slack bridge process in the current Windows session."""

    ERROR_ALREADY_EXISTS = 183
    MUTEX_NAME = r"Local\NovaOpsCodexSlackBridge"

    def __init__(self) -> None:
        self._handle: int | None = None
        if os.name != "nt":
            return
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.argtypes = (ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p)
        kernel32.CreateMutexW.restype = ctypes.c_void_p
        kernel32.CloseHandle.argtypes = (ctypes.c_void_p,)
        kernel32.CloseHandle.restype = ctypes.c_bool
        ctypes.set_last_error(0)
        handle = kernel32.CreateMutexW(None, False, self.MUTEX_NAME)
        error = ctypes.get_last_error()
        if not handle:
            raise OSError(error, f"Unable to create Slack bridge instance mutex {self.MUTEX_NAME}")
        if error == self.ERROR_ALREADY_EXISTS:
            kernel32.CloseHandle(handle)
            raise RuntimeError("A Codex Slack bridge instance is already running")
        self._handle = int(handle)
        self._kernel32 = kernel32

    def close(self) -> None:
        if self._handle is None:
            return
        self._kernel32.CloseHandle(ctypes.c_void_p(self._handle))
        self._handle = None

    def __enter__(self) -> "SlackBridgeSingleInstanceGuard":
        return self

    def __exit__(self, *_exc: Any) -> None:
        self.close()


def main() -> None:
    global SLACK_CLIENT, SLACK_CONFIG
    with SlackBridgeSingleInstanceGuard():
        config_path = os.getenv("BRIDGE_CONFIG", "config/agents.yaml")
        _load_runtime_env_files(Path(config_path))
        config_path = os.getenv("BRIDGE_CONFIG", config_path)
        config = load_config(config_path)
        configure_runtime(config)

        bot_token = _required_env("SLACK_BOT_TOKEN")
        app_token = _required_env("SLACK_APP_TOKEN")

        slack_app = App(token=bot_token)
        SLACK_CLIENT = slack_app.client
        SLACK_CONFIG = config
        register_handlers(slack_app, config)
        _recover_queued_slack_jobs(config, slack_app.client)
        _deliver_pending_terminal_slack_feedback(config, slack_app.client)
        start_slack_heartbeat_if_enabled(slack_app, config)
        start_polling_if_enabled(slack_app, config)
        start_desktop_slack_mirror_if_enabled(slack_app, config)
        LOGGER.info("Starting Codex Slack Bridge with config %s", Path(config_path).resolve())
        SocketModeHandler(slack_app, app_token).start()


def _load_runtime_env_files(config_path: Path) -> None:
    # AgentChat/coding_agent 2026-07-08T20:02:14Z: keep Slack env loading aligned with desktop Agent Chat.
    resolved_config = config_path.resolve()
    bridge_root = resolved_config.parent.parent if resolved_config.parent.name.lower() == "config" else Path.cwd().resolve()
    for env_path in (
        bridge_root / "config" / "ops.env",
        bridge_root / ".env",
        bridge_root / "config" / "logmein-rescue.env",
    ):
        if env_path.exists():
            load_dotenv(env_path, override=False)


def configure_runtime(config: BridgeConfig) -> None:
    global EXECUTOR, STATE, MEMORY, COGNITIVE_MEMORY, LEARNING, VERIFIED_ROUTES
    max_workers = int(config.defaults.get("max_workers", 3))
    EXECUTOR = ThreadPoolExecutor(max_workers=max_workers)
    state_db = str(config.defaults.get("state_db", "data/bridge.sqlite3"))
    STATE = BridgeState(state_db)
    VERIFIED_ROUTES = VerifiedRouteStore(
        _resolve_runtime_path(
            str(
                config.defaults.get(
                    "verified_route_store_path",
                    "data/agent_runtime/verified_routes.sqlite3",
                )
            )
        ),
        pipeline_registry_path=_resolve_runtime_path(
            str(config.defaults.get("pipeline_registry_path", "config/pipeline-registry.json"))
        ),
        tool_registry_path=_resolve_runtime_path(
            str(config.defaults.get("tool_fast_paths_path", "config/tool-fast-paths.json"))
        ),
    )
    MEMORY = MemoryStore(config)
    COGNITIVE_MEMORY = CognitiveMemoryStore(
        _resolve_runtime_path(
            str(config.defaults.get("cognitive_memory_sqlite_path", "data/cognitive_memory.sqlite3"))
        ),
        max_summary_chars=int(config.defaults.get("cognitive_memory_max_summary_chars", 1600)),
    )
    quarantined = COGNITIVE_MEMORY.quarantine_misclassified_outcome_episodes()
    if quarantined:
        LOGGER.warning("Quarantined %s legacy unresolved cognitive episode(s)", quarantined)
    LEARNING = (
        LearningProposalRegistry(
            _resolve_runtime_path(
                str(config.defaults.get("learning_registry_sqlite_path", "data/learning_registry.sqlite3"))
            ),
            capability_policy=_learning_capability_policy(config),
        )
        if _truthy(config.defaults.get("learning_registry_enabled", True))
        else None
    )
    # A previous process cannot still own a running attempt because the
    # single-instance guard has admitted this process. Recover model-agent work
    # with a same-surface readback continuation; deterministic/transient work
    # remains quarantined.
    for row in STATE.list_jobs(statuses={"queued", "running"}, limit=500):
        if str(row.get("channel_id") or "") == "command_center":
            continue
        job_id = int(row.get("id") or 0)
        status = str(row.get("status") or "").lower()
        policy = str(row.get("recovery_policy") or "").lower()
        stage = str(row.get("runtime_stage") or "").lower()
        if stage == "handoff_acknowledged":
            continue
        if policy == "review_required":
            STATE.mark_recovery_review_required(
                job_id,
                "The queued request contained attachment or transient context that cannot be replayed safely.",
            )
        elif status == "running":
            STATE.requeue_for_recovery(
                job_id,
                "The prior Slack worker ended after this job started.",
                recovery_policy="same_surface_readback_first",
            )
    if _truthy(config.defaults.get("agent_runtime_monitor_enabled", False)):
        Thread(
            target=_slack_runtime_health_watch,
            args=(config,),
            name="slack-runtime-health-watch",
            daemon=True,
        ).start()
    else:
        # A startup pass can temporarily retain an orphan whose session was
        # updated just before a restart. Recheck once after that grace period
        # without paying for a permanent 60-second polling loop.
        Thread(
            target=_slack_startup_reconciliation_once,
            args=(config,),
            name="slack-startup-reconciliation",
            daemon=True,
        ).start()


def _slack_startup_reconciliation_once(config: BridgeConfig) -> None:
    default_delay = max(
        float(config.defaults.get("job_reconciliation_stale_seconds", 300)),
        float(config.defaults.get("job_reconciliation_session_grace_seconds", 300)),
    ) + 5.0
    delay = max(
        1.0,
        float(config.defaults.get("agent_runtime_startup_reconcile_delay_seconds", default_delay)),
    )
    LOGGER.info("One-time Slack startup reconciliation scheduled in %.1f seconds", delay)
    time.sleep(delay)
    _reconcile_slack_runtime_health_once(config)


def _slack_runtime_health_watch(config: BridgeConfig) -> None:
    """Reconcile Slack-owned jobs on the configured low-frequency watchdog cadence."""
    interval = max(15, int(config.defaults.get("agent_runtime_monitor_interval_seconds", 60)))
    LOGGER.info("Slack orchestration watchdog enabled at %.1fs interval", interval)
    while True:
        time.sleep(interval)
        try:
            _reconcile_slack_runtime_health_once(config)
        except Exception:
            LOGGER.exception("Slack runtime health reconciliation failed")


def _reconcile_slack_runtime_health_once(config: BridgeConfig) -> None:
    if STATE is None:
        return
    now = time.time()
    no_child_grace = max(30, int(config.defaults.get("agent_runtime_no_child_grace_seconds", 120)))
    cancel_grace = max(15, int(config.defaults.get("agent_runtime_cancel_grace_seconds", 45)))
    live_job_ids: set[int] = set()
    restart_required = False
    active_rows = [
        row
        for row in STATE.list_jobs(statuses={"queued", "running"}, limit=500)
        if str(row.get("channel_id") or "") != "command_center"
    ]
    with ACTIVE_JOB_IDS_LOCK:
        scheduler_ids = set(ACTIVE_JOB_IDS)
        scheduler_futures = dict(ACTIVE_JOB_FUTURES)
        retry_timers = dict(ACTIVE_JOB_RETRY_TIMERS)
    for row in active_rows:
        job_id = int(row.get("id") or 0)
        status = str(row.get("status") or "").lower()
        runtime_stage = str(row.get("runtime_stage") or "").lower()
        recovery_policy = str(row.get("recovery_policy") or "").lower()
        if status == "running" and runtime_stage == "handoff_acknowledged":
            # Command Center owns the acknowledged child and will terminalize
            # this Slack origin only when the child's receipt returns.
            live_job_ids.add(job_id)
            continue
        future = scheduler_futures.get(job_id)
        future_live = future is not None and not future.done()
        retry_timer = retry_timers.get(job_id)
        retry_live = retry_timer is not None and retry_timer.is_alive()
        process = agent_job_process_status(job_id)
        process_live = int(process.get("alive") or 0) > 0
        if status == "queued":
            if job_id in scheduler_ids and (future_live or retry_live or process_live):
                live_job_ids.add(job_id)
            elif job_id in scheduler_ids:
                LOGGER.error("Removing ghost Slack scheduler bookkeeping for queued job %s", job_id)
                _clear_active_slack_job(job_id)
            continue

        started_at = float(row.get("started_at") or row.get("created_at") or now)
        attempt_age = max(0.0, now - started_at)
        attempt_deadline = _slack_attempt_deadline_seconds(config, row)
        deadline_expired = attempt_age > attempt_deadline
        if job_id in RECOVERY_REVIEW_JOB_IDS:
            cancel_age = now - float(ACTIVE_JOB_CANCEL_REQUESTED_AT.get(job_id) or now)
            if job_id in scheduler_ids and cancel_age <= cancel_grace:
                live_job_ids.add(job_id)
                continue
            if recovery_policy == "review_required":
                STATE.mark_recovery_review_required(
                    job_id,
                    "The Slack worker ended with transient input that cannot be replayed safely.",
                )
            else:
                STATE.requeue_for_recovery(
                    job_id,
                    "The Slack worker remained active after cancellation; the supervised bridge is recycling.",
                    recovery_policy="same_surface_readback_first",
                    runtime_instance_id=RUNTIME_INSTANCE_ID,
                )
            _clear_active_slack_job(job_id)
            restart_required = True
            continue

        if job_id in scheduler_ids and process_live and not deadline_expired:
            live_job_ids.add(job_id)
            continue
        stage_updated_at = float(row.get("stage_updated_at") or row.get("started_at") or row.get("created_at") or now)
        stage_age = max(0.0, now - stage_updated_at)
        if job_id in scheduler_ids and not deadline_expired and (future_live or retry_live) and stage_age <= no_child_grace:
            live_job_ids.add(job_id)
            continue
        RECOVERY_REVIEW_JOB_IDS.add(job_id)
        CANCELLED_JOB_IDS.add(job_id)
        ACTIVE_JOB_CANCEL_REQUESTED_AT[job_id] = now
        stage = "cancelling_attempt_deadline" if deadline_expired else "cancelling_dead_or_stalled_worker"
        STATE.update_runtime_stage(job_id, stage, runtime_instance_id=RUNTIME_INSTANCE_ID)
        cancel_agent_job(job_id)
        if deadline_expired:
            LOGGER.error(
                "Watchdog fenced Slack job %s after its %.1fs absolute attempt deadline (age %.1fs)",
                job_id,
                attempt_deadline,
                attempt_age,
            )
        else:
            LOGGER.error("Watchdog fenced stalled Slack job %s after %.1fs without a live worker", job_id, stage_age)
        live_job_ids.add(job_id)

    if not restart_required:
        _recover_queued_slack_jobs(config, SLACK_CLIENT)
    if SLACK_CLIENT is not None:
        _deliver_pending_terminal_slack_feedback(config, SLACK_CLIENT)
    with ACTIVE_JOB_IDS_LOCK:
        for job_id, future in ACTIVE_JOB_FUTURES.items():
            if job_id in ACTIVE_JOB_IDS and not future.done():
                live_job_ids.add(job_id)

    channel_ids = set(config.channels)
    channel_ids.update(STATE.active_channel_ids(exclude={"command_center"}))
    for channel_id in sorted(channel_ids):
        result = reconcile_system_jobs(
            config,
            STATE,
            runtime_job_ids=live_job_ids,
            authoritative=True,
            channel_id=channel_id,
        )
        if result.get("changed") or (result.get("evidence") or {}).get("removedStaleLocks"):
            LOGGER.warning("Slack runtime health reconciliation for %s: %s", channel_id, redact_secrets(json.dumps(result)))
    if restart_required:
        _force_supervised_restart("stalled Slack worker did not exit after cancellation")


def _recover_queued_slack_jobs(config: BridgeConfig, client: Any | None) -> int:
    """Run durable queued work, including fenced readback-first continuations."""
    if STATE is None or EXECUTOR is None or client is None:
        return 0
    recovered = 0
    rows = sorted(
        (
            row
            for row in STATE.list_jobs(statuses={"queued"}, limit=500)
            if str(row.get("channel_id") or "") != "command_center"
        ),
        key=lambda row: float(row.get("created_at") or 0),
    )
    for row in rows:
        job_id = int(row.get("id") or 0)
        with ACTIVE_JOB_IDS_LOCK:
            if job_id in ACTIVE_JOB_IDS:
                continue
        policy = str(row.get("recovery_policy") or "queued_replay").strip().lower()
        if policy == "review_required":
            STATE.mark_recovery_review_required(
                job_id,
                "Queued request cannot be replayed because its transient input was not durable.",
            )
            continue
        recovery_count = max(0, int(row.get("recovery_count") or 0))
        max_attempts = max(
            1,
            min(int(config.defaults.get("agent_worker_max_attempts", 3)), 5),
        )
        if recovery_count >= max_attempts:
            STATE.mark_recovery_review_required(
                job_id,
                "The bounded restart-recovery budget is exhausted; same-surface readback is still required.",
            )
            continue
        agent_name = str(row.get("agent_name") or "")
        if agent_name not in config.agents:
            STATE.mark_recovery_review_required(job_id, f"Configured agent {agent_name or 'unknown'} is unavailable.")
            continue
        agent = dict(config.defaults)
        agent.update(config.agents[agent_name])
        channel_id = str(row.get("channel_id") or "")
        thread_ts = str(row.get("thread_ts") or "")
        user_id = str(row.get("user_id") or "")
        text = str(row.get("request_text") or "")
        progress_ts = None
        if config.defaults.get("progress_message_enabled", True):
            try:
                response = client.chat_postMessage(
                    channel=channel_id,
                    text=f"`{agent_name}` automatically recovered queued job `{job_id}` and is starting it now.",
                    **_reply_target(config, thread_ts),
                )
                progress_ts = response.get("ts")
            except Exception:
                LOGGER.exception("Could not post recovery progress for queued job %s", job_id)
        request = AgentRequest(
            text=text,
            channel_id=channel_id,
            user_id=user_id,
            thread_ts=thread_ts,
            job_id=job_id,
            surface="slack",
            conversation_id=_slack_conversation_id(channel_id, thread_ts),
            authority_kind="operator",
            message_signature=sign_trusted_message(
                agent=agent,
                text=text,
                source="slack",
                actor=user_id,
                channel_id=channel_id,
                thread_ts=thread_ts,
                authority_kind="operator",
            ),
            runtime_guidance=(
                recovery_continuation_guidance(
                    attempt=recovery_count + 1,
                    max_attempts=max_attempts,
                    idempotency_key=f"bridge-job:{job_id}",
                    reason=str(
                        row.get("reconciliation_reason")
                        or "The prior Slack worker ended before a terminal result."
                    ),
                    recovered_after_restart=True,
                )
                if recovery_count
                else ""
            ),
        )
        with ACTIVE_JOB_IDS_LOCK:
            ACTIVE_JOB_IDS.add(job_id)
            ACTIVE_JOB_CONTEXT[job_id] = (channel_id, agent_name)
        STATE.update_runtime_stage(job_id, "recovered_waiting_lane")
        _submit_slack_job_future(
            config,
            agent_name,
            agent,
            request,
            client,
            int(config.defaults.get("max_slack_message_chars", 3900)),
            progress_ts,
        )
        recovered += 1
    return recovered


def _submit_slack_job_future(
    config: BridgeConfig,
    agent_name: str,
    agent: dict[str, Any],
    request: AgentRequest,
    client: Any,
    max_chars: int,
    progress_ts: str | None,
) -> Future[Any] | None:
    try:
        if EXECUTOR is None:
            raise RuntimeError("Slack executor is unavailable")
        future = EXECUTOR.submit(
            _run_and_reply,
            config,
            agent_name,
            agent,
            request,
            client,
            max_chars,
            progress_ts,
        )
    except Exception as exc:
        job_id = request.job_id
        LOGGER.exception("Could not submit Slack job %s to the executor", job_id)
        if job_id is not None:
            if STATE is not None:
                STATE.requeue_for_recovery(
                    job_id,
                    f"Slack scheduler admission failed: {redact_secrets(str(exc))}",
                    recovery_policy="same_surface_readback_first",
                )
            try:
                client.chat_postMessage(
                    channel=request.channel_id,
                    text=f"`{agent_name}` kept this request queued for automatic recovery.",
                    **_reply_target(config, request.thread_ts),
                )
            except Exception:
                LOGGER.exception("Could not post Slack scheduler failure for job %s", job_id)
            _clear_active_slack_job(job_id)
        return None
    if request.job_id is not None:
        with ACTIVE_JOB_IDS_LOCK:
            ACTIVE_JOB_FUTURES[request.job_id] = future
        future.add_done_callback(lambda completed, job_id=request.job_id: _slack_job_future_done(job_id, completed))
    return future


def _slack_job_future_done(job_id: int, future: Future[Any]) -> None:
    with ACTIVE_JOB_IDS_LOCK:
        if ACTIVE_JOB_FUTURES.get(job_id) is future:
            ACTIVE_JOB_FUTURES.pop(job_id, None)
    try:
        exc = future.exception()
    except Exception as callback_error:
        exc = callback_error
    if exc is None:
        return
    LOGGER.error(
        "Slack job %s future escaped normal cleanup: %s",
        job_id,
        exc,
        exc_info=(type(exc), exc, exc.__traceback__),
    )
    if STATE is not None:
        if job_id in RECOVERY_REVIEW_JOB_IDS:
            durable = STATE.jobs_by_ids({job_id}).get(job_id, {})
            if str(durable.get("recovery_policy") or "").lower() == "review_required":
                STATE.mark_recovery_review_required(
                    job_id,
                    "The watchdog fenced work with transient input that cannot be replayed safely.",
                )
            else:
                STATE.requeue_for_recovery(
                    job_id,
                    "The watchdog fenced the Slack worker after scheduler failure.",
                    recovery_policy="same_surface_readback_first",
                    runtime_instance_id=RUNTIME_INSTANCE_ID,
                )
        else:
            STATE.mark_failed(
                job_id,
                f"Slack scheduler failed: {exc}",
                runtime_instance_id=RUNTIME_INSTANCE_ID,
                review_required=False,
            )
    with ACTIVE_JOB_IDS_LOCK:
        ACTIVE_JOB_IDS.discard(job_id)
        ACTIVE_JOB_CONTEXT.pop(job_id, None)
        CANCELLED_JOB_IDS.discard(job_id)
        RECOVERY_REVIEW_JOB_IDS.discard(job_id)
        ACTIVE_JOB_CANCEL_REQUESTED_AT.pop(job_id, None)


def _supervised_restart_request_path() -> Path:
    raw_path = "data/agent_runtime/restart_request.json"
    if SLACK_CONFIG is not None:
        raw_path = str(
            SLACK_CONFIG.defaults.get("agent_runtime_restart_request_path")
            or raw_path
        )
    return _resolve_runtime_path(raw_path)


def _force_supervised_restart(reason: str) -> None:
    if SLACK_CONFIG is not None and not _truthy(
        SLACK_CONFIG.defaults.get("agent_runtime_forced_restart_enabled", True)
    ):
        LOGGER.critical("Supervised restart required but disabled: %s", reason)
        return
    if STATE is not None:
        for row in STATE.list_jobs(statuses={"running"}, limit=500):
            if str(row.get("channel_id") or "") == "command_center":
                continue
            if str(row.get("runtime_stage") or "").lower() == "handoff_acknowledged":
                continue
            job_id = int(row.get("id") or 0)
            if str(row.get("recovery_policy") or "").lower() == "review_required":
                STATE.mark_recovery_review_required(
                    job_id,
                    "The Slack gateway recycled with transient input that cannot be replayed safely.",
                )
            else:
                STATE.requeue_for_recovery(
                    job_id,
                    "The Slack gateway recycled while this started job was active.",
                    recovery_policy="same_surface_readback_first",
                    runtime_instance_id=RUNTIME_INSTANCE_ID,
                )
    audit_path = _supervised_restart_request_path()
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "signature": "AgentChat/direct_codex 2026-07-13T00:16:00-04:00",
        "requestedAtUtc": datetime.utcnow().isoformat() + "Z",
        "runtimeInstanceId": RUNTIME_INSTANCE_ID,
        "reason": str(reason)[:500],
    }
    temporary = audit_path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    os.replace(temporary, audit_path)
    LOGGER.critical("Exiting for supervised Slack bridge recovery: %s", reason)
    os._exit(75)


def start_slack_heartbeat_if_enabled(slack_app: App, config: BridgeConfig) -> None:
    """Start a read-only Slack API heartbeat; history polling remains the delivery fallback."""
    if not _truthy(config.defaults.get("slack_heartbeat_enabled", True)):
        return
    Thread(
        target=_slack_heartbeat_forever,
        args=(slack_app, config),
        name="slack-api-heartbeat",
        daemon=True,
    ).start()


def _slack_heartbeat_forever(slack_app: App, config: BridgeConfig) -> None:
    interval = max(60, int(config.defaults.get("slack_heartbeat_interval_seconds", 300)))
    LOGGER.info("Slack API heartbeat enabled at %.1fs interval", interval)
    while True:
        _slack_heartbeat_once(slack_app)
        time.sleep(interval)


def _slack_heartbeat_once(slack_app: App) -> bool:
    try:
        response = slack_app.client.auth_test()
        if not response.get("ok", False):
            LOGGER.warning("Slack API heartbeat returned a non-OK response")
            return False
        LOGGER.info("Slack API heartbeat healthy")
        return True
    except Exception as exc:
        LOGGER.warning("Slack API heartbeat failed: %s", redact_secrets(str(exc)))
        return False


def register_handlers(slack_app: App, config: BridgeConfig) -> None:
    @slack_app.command("/btw")
    @slack_app.command("/steer")
    def handle_steer_command(ack: Any, body: dict[str, Any], client: Any) -> None:
        command_name = str(body.get("command") or "/steer").strip().lower()
        if command_name not in {"/btw", "/steer"}:
            command_name = "/steer"
        channel_id = str(body.get("channel_id") or "").strip()
        user_id = str(body.get("user_id") or "").strip()
        steer_text = str(body.get("text") or "").strip()
        route = config.channels.get(channel_id)
        if route is None:
            ack(
                response_type="ephemeral",
                text="No agent is configured for this Slack channel, so nothing was queued.",
            )
            return
        agent = dict(config.defaults)
        agent.update(config.agents.get(route.agent_name, {}))
        allowed_user_ids = {str(uid) for uid in (agent.get("allowed_user_ids") or [])}
        if not allowed_user_ids or user_id not in allowed_user_ids:
            ack(response_type="ephemeral", text="You are not authorized to steer this agent.")
            return
        if not steer_text:
            ack(response_type="ephemeral", text=f"Usage: {command_name} <guidance for the agent>")
            return

        trigger_id = str(body.get("trigger_id") or "").strip()
        command_event_id = f"slash:{command_name}:{trigger_id}" if trigger_id else ""
        if STATE is not None and command_event_id and not STATE.record_event_once(command_event_id):
            ack(response_type="ephemeral", text=f"Steering guidance is already queued for `{route.agent_name}`.")
            return

        ack(
            response_type="ephemeral",
            text=(
                f"Accepted steering guidance for `{route.agent_name}` as a separate queued follow-up. "
                "It does not interrupt an in-flight turn."
            ),
        )
        command_ts = f"{time.time():.6f}"
        _queue_request(
            config,
            route,
            {"event_id": command_event_id or f"slash:{command_name}:{command_ts}"},
            {
                "channel": channel_id,
                "user": user_id,
                "ts": command_ts,
                "_force_top_level": True,
                "text": f"{command_name} {steer_text}",
            },
            client,
        )

    @slack_app.event("app_mention")
    def handle_app_mention(body: dict[str, Any], event: dict[str, Any], client: Any) -> None:
        if _already_seen(body):
            return
        route = _route_for_event(config, event, mentioned=True)
        if route:
            _queue_request(config, route, body, event, client)

    @slack_app.event("message")
    def handle_message(body: dict[str, Any], event: dict[str, Any], client: Any) -> None:
        if _already_seen(body) or _is_ignored_message(event):
            return
        route = _route_for_event(config, event, mentioned=False)
        if route:
            _queue_request(config, route, body, event, client)


def start_polling_if_enabled(slack_app: App, config: BridgeConfig) -> None:
    if not config.defaults.get("polling_enabled", False):
        return
    thread = Thread(
        target=_poll_channels_forever,
        args=(slack_app, config),
        name="slack-history-poller",
        daemon=True,
    )
    thread.start()


# AgentChat/coding_agent 2026-07-09T00:52:46Z: mirror desktop Agent Chat messages into Slack out-of-band.
def start_desktop_slack_mirror_if_enabled(slack_app: App, config: BridgeConfig) -> None:
    if not config.defaults.get("desktop_slack_mirror_enabled", False):
        return
    thread = Thread(
        target=_mirror_desktop_chat_forever,
        args=(slack_app.client, config),
        name="desktop-slack-mirror",
        daemon=True,
    )
    thread.start()


def _poll_channels_forever(slack_app: App, config: BridgeConfig) -> None:
    interval = float(config.defaults.get("poll_interval_seconds", 5))
    LOGGER.info("Slack history polling enabled at %.1fs interval", interval)
    while True:
        try:
            _poll_channels_once(slack_app, config)
        except Exception:
            LOGGER.exception("Slack polling pass failed")
        time.sleep(interval)


def _poll_channels_once(slack_app: App, config: BridgeConfig) -> None:
    client = slack_app.client
    history_limit = int(config.defaults.get("poll_history_limit", 10))
    startup_lookback = float(config.defaults.get("poll_startup_lookback_seconds", 0))
    oldest_allowed_ts = STARTED_AT - startup_lookback
    for channel_id, route in config.channels.items():
        try:
            response = client.conversations_history(channel=channel_id, limit=history_limit)
        except Exception as exc:
            LOGGER.warning("Could not poll channel %s: %s", channel_id, exc)
            continue

        messages = sorted(response.get("messages") or [], key=lambda message: float(message["ts"]))
        for message in messages:
            if float(message.get("ts", "0")) < oldest_allowed_ts:
                continue
            if _is_ignored_message(message):
                continue
            text = strip_bot_mentions(message.get("text") or "")
            if not text and not message.get("files"):
                continue
            if route.listen != "all_messages" and not _message_mentions_bot(client, message):
                continue
            _queue_request(
                config,
                route,
                {"event_id": f"poll:{channel_id}:{message.get('ts')}"},
                message,
                client,
            )


def _mirror_desktop_chat_forever(client: Any, config: BridgeConfig) -> None:
    interval = float(config.defaults.get("desktop_slack_mirror_interval_seconds", 2))
    startup_lookback = float(config.defaults.get("desktop_slack_mirror_startup_lookback_seconds", 86400))
    oldest_allowed_at = STARTED_AT - startup_lookback
    LOGGER.info("Desktop-to-Slack mirror enabled at %.1fs interval", interval)
    while True:
        try:
            _mirror_desktop_chat_once(client, config, oldest_allowed_at=oldest_allowed_at)
        except Exception:
            LOGGER.exception("Desktop-to-Slack mirror pass failed")
        time.sleep(interval)


def _mirror_desktop_chat_once(
    client: Any,
    config: BridgeConfig,
    *,
    oldest_allowed_at: float | None = None,
) -> int:
    if STATE is None:
        raise RuntimeError("Bridge state is not configured")

    path = _shared_chat_path(config)
    if not path.exists():
        return 0

    roles = _desktop_slack_mirror_roles(config)
    sources = _desktop_slack_mirror_sources(config)
    max_events = int(config.defaults.get("desktop_slack_mirror_max_events_per_pass", 25))
    scan_lines = int(config.defaults.get("desktop_slack_mirror_scan_lines", 1000))
    max_chars = int(config.defaults.get("max_slack_message_chars", 3900))
    mirrored = 0
    for event in _read_shared_chat_events(path, line_limit=scan_lines):
        if mirrored >= max_events:
            break
        if str(_shared_event_field(event, "source") or "").lower() not in sources:
            continue
        role = str(_shared_event_field(event, "role") or "").lower()
        if role not in roles:
            continue
        event_time = _shared_event_time(event)
        if oldest_allowed_at is not None and event_time is not None and event_time < oldest_allowed_at:
            continue
        event_id = str(_shared_event_field(event, "id") or "")
        if not event_id or STATE.has_desktop_slack_mirror(event_id):
            continue
        if _is_internal_failure_mirror_event(event):
            # Consume the event without broadcasting it to the per-agent Slack
            # channel. Its originating direct chat/review surface remains the
            # sole communication destination.
            STATE.record_desktop_slack_mirror(event_id, "suppressed_internal_failure", "")
            continue
        agent_name = str(_shared_event_field(event, "agentName") or "")
        channel_id = _desktop_slack_mirror_channel_for_agent(config, agent_name)
        if not channel_id:
            continue
        text = _format_desktop_slack_mirror_text(event)
        if not text:
            continue

        message_ts = None
        for chunk in chunk_for_slack(text, max_chars):
            response = client.chat_postMessage(channel=channel_id, text=chunk)
            message_ts = message_ts or response.get("ts")
        STATE.record_desktop_slack_mirror(event_id, channel_id, str(message_ts or ""))
        mirrored += 1
    return mirrored


def _read_shared_chat_events(path: Path, *, line_limit: int) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []

    events: list[dict[str, Any]] = []
    for line in lines[-line_limit:]:
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict):
            events.append(event)
    return events


def _desktop_slack_mirror_roles(config: BridgeConfig) -> set[str]:
    raw = config.defaults.get("desktop_slack_mirror_roles", ["user", "assistant"])
    if not isinstance(raw, list):
        return {"user", "assistant"}
    return {str(role).lower() for role in raw if str(role).strip()}


def _desktop_slack_mirror_sources(config: BridgeConfig) -> set[str]:
    raw = config.defaults.get("desktop_slack_mirror_sources", ["desktop", "command_center"])
    if not isinstance(raw, list):
        return {"desktop", "command_center"}
    return {str(source).lower() for source in raw if str(source).strip()}


def _desktop_slack_mirror_channel_for_agent(config: BridgeConfig, agent_name: str) -> str | None:
    if not agent_name:
        return None
    raw_map = config.defaults.get("desktop_slack_mirror_channels") or {}
    if isinstance(raw_map, dict):
        mapped = raw_map.get(agent_name) or raw_map.get(agent_name.lower())
        if mapped:
            return str(mapped)
    for channel_id, route in config.channels.items():
        if route.agent_name.lower() == agent_name.lower():
            return channel_id
    return None


def _format_desktop_slack_mirror_text(event: dict[str, Any]) -> str:
    agent_name = str(_shared_event_field(event, "agentName") or "agent")
    role = str(_shared_event_field(event, "role") or "message").lower()
    source = str(_shared_event_field(event, "source") or "shared").lower()
    text = _public_agent_display_text(
        agent_name,
        redact_secrets(str(_shared_event_field(event, "text") or "")).strip(),
    )
    if not text:
        return ""
    title = "assistant" if role == "assistant" else "user" if role == "user" else role
    source_label = "Command Center" if source == "command_center" else "Agent Chat desktop" if source == "desktop" else source.replace("_", " ").title()
    return f"*{source_label} {title}* (`{public_agent_name(agent_name)}`):\n{text}"


def _is_internal_failure_mirror_event(event: dict[str, Any]) -> bool:
    if str(_shared_event_field(event, "role") or "").strip().lower() != "assistant":
        return False
    text = str(_shared_event_field(event, "text") or "").strip()
    if re.match(r"^(?:FAILED|BLOCKED|COMPLETED_WITH_ISSUES)(?:\b|\s*[:\-—])", text, re.IGNORECASE):
        return True
    normalized = text.casefold()
    return any(
        marker in normalized
        for marker in (
            "command center job failed",
            "codex run failed",
            "check the bridge console logs",
            "traceback (most recent call last)",
        )
    )


def _shared_event_field(event: dict[str, Any], name: str) -> Any:
    if name in event:
        return event[name]
    return event.get(name[0].upper() + name[1:])


def _shared_event_time(event: dict[str, Any]) -> float | None:
    raw = _shared_event_field(event, "atUtc")
    if isinstance(raw, (int, float)):
        return float(raw)
    if not isinstance(raw, str) or not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _message_mentions_bot(client: Any, message: dict[str, Any]) -> bool:
    try:
        bot_user_id = client.auth_test().get("user_id")
    except Exception:
        return False
    return bool(bot_user_id and f"<@{bot_user_id}>" in (message.get("text") or ""))


def _route_for_event(
    config: BridgeConfig,
    event: dict[str, Any],
    *,
    mentioned: bool,
) -> ChannelRoute | None:
    channel_id = event.get("channel")
    if not channel_id:
        return None

    route = config.channels.get(channel_id)
    if route:
        if route.listen == "all_messages" or mentioned:
            return route
        return None

    if mentioned and "default_agent" in config.defaults:
        default_agent = str(config.defaults["default_agent"])
        return ChannelRoute(channel_id=channel_id, agent_name=default_agent, listen="mention")

    return None


def _singapore_reactivation_metadata(text: str) -> dict[str, Any] | None:
    """Build the only reactivation metadata allowed across the Slack boundary."""

    if classify_singapore_intent(text) is not SingaporeIntent.REACTIVATION:
        return None
    machine_ids = {
        match.group(1)
        for match in SINGAPORE_REACTIVATION_TARGET_RE.finditer(str(text or ""))
    }
    if len(machine_ids) != 1:
        return None
    machine_id = next(iter(machine_ids))
    return {
        "schemaVersion": 1,
        "requestKind": "reactivation",
        "action": "reactivate",
        "targetType": "machine_id",
        "machineId": machine_id,
    }


def _queue_request(
    config: BridgeConfig,
    route: ChannelRoute,
    body: dict[str, Any],
    event: dict[str, Any],
    client: Any,
) -> None:
    if EXECUTOR is None or STATE is None:
        raise RuntimeError("Bridge runtime is not configured")

    user_id = event.get("user") or ""
    # Deny-by-default: agents run with broad local access and touch billing,
    # so an empty allowlist means nobody is authorized (not everybody).
    agent_cfg = dict(config.defaults)
    agent_cfg.update(config.agents.get(route.agent_name, {}))
    allowed_user_ids = {str(uid) for uid in (agent_cfg.get("allowed_user_ids") or [])}
    if not allowed_user_ids:
        LOGGER.warning(
            "Denying %s in %s: allowed_user_ids is empty. Add approved Slack "
            "user IDs under defaults or the agent in config/agents.yaml.",
            user_id,
            route.channel_id,
        )
        return
    if user_id not in allowed_user_ids:
        LOGGER.info("Ignoring unauthorized user %s in %s", user_id, route.channel_id)
        return

    text = strip_bot_mentions(event.get("text") or "")
    has_files = event_has_files(event)
    if not text and has_files:
        text = "User uploaded Slack file(s). Inspect the attached file context and local file paths."
    if not text:
        return
    if not STATE.record_message_once(route.channel_id, event.get("ts")):
        LOGGER.debug("Ignoring duplicate Slack message %s/%s", route.channel_id, event.get("ts"))
        return

    thread_ts = "" if event.get("_force_top_level") else (event.get("thread_ts") or event.get("ts"))
    if text.strip().lower() in {"stop", "cancel", "stop current job", "cancel current job"}:
        stopped = _cancel_active_slack_jobs(route.channel_id, route.agent_name)
        client.chat_postMessage(
            channel=route.channel_id,
            text=(f"Stopping `{route.agent_name}` job(s): {', '.join(str(value) for value in stopped)}." if stopped else f"No active `{route.agent_name}` job is running in this channel."),
            **_reply_target(config, thread_ts),
        )
        return
    steer_command, _ = parse_steer_command(text)
    trusted_text = format_queued_steering_prompt(text) if steer_command else text
    agent = dict(config.defaults)
    agent.update(config.agents[route.agent_name])
    if _handle_memory_command(config, route, client, thread_ts, user_id, text):
        return
    if _handle_prospective_command(config, route, client, thread_ts, user_id, text):
        return
    if _handle_agent_session_command(config, route, client, thread_ts, user_id, text, agent):
        return
    if _handle_status_command(config, route, client, thread_ts, text):
        return
    if is_web_search_command(text):
        _queue_web_search(config, route, client, thread_ts, user_id, text)
        return
    if is_singapore_notification_policy_request(text):
        client.chat_postMessage(
            channel=route.channel_id,
            text=(
                "Singapore operational results stay in the private background-service lane and never create "
                "Salesforce tickets or Needs Review packets. Taylor can post a compact sanitized outcome in "
                "direct Agent Chat. Verified retired interfaces stay silent unless reactivation is requested; "
                "only an explicit brand-new integration/interface request may create a ticket."
            ),
            **_reply_target(config, thread_ts),
        )
        return
    if is_singapore_run_request(text):
        idempotency_key = f"ops-singapore-ftp-slack:{body.get('event_id') or event.get('ts') or uuid.uuid4().hex}"
        request_payload: dict[str, Any] = {
            "idempotencyKey": idempotency_key[:180],
            "requestedBy": str(user_id)[:120],
            "source": "slack",
        }
        if classify_singapore_intent(text) is SingaporeIntent.REACTIVATION:
            reactivation = _singapore_reactivation_metadata(text)
            if reactivation is None:
                client.chat_postMessage(
                    channel=route.channel_id,
                    text=(
                        "Singapore reactivation was not queued. Include one exact 5-10 digit machine ID "
                        "using a label such as `machine 5000393`; ambiguous or unlabeled targets fail closed."
                    ),
                    **_reply_target(config, thread_ts),
                )
                return
            request_payload["singaporeRequest"] = reactivation
        try:
            response = _command_center_json(
                config,
                "POST",
                "/ops/singapore-ftp/scan",
                request_payload,
            )
            job_id = str(response.get("job_id") or "").strip()
            duplicate = bool(response.get("duplicate"))
            message = (
                f"Singapore routine was already queued as `{job_id}`."
                if duplicate and job_id
                else f"Queued the Singapore routine directly as `{job_id}`."
                if job_id
                else "Queued the Singapore routine directly."
            )
        except Exception:
            LOGGER.warning("Singapore request could not be routed through the deterministic fast path")
            message = "The Singapore background-service run could not be queued. Taylor will report the outcome in direct Agent Chat."
        client.chat_postMessage(
            channel=route.channel_id,
            text=message,
            **_reply_target(config, thread_ts),
        )
        return

    max_chars = int(config.defaults.get("max_slack_message_chars", 3900))
    context = "" if _truthy(agent.get("direct_codex_raw_prompt")) else _collect_slack_context(
        config,
        client,
        route.channel_id,
        thread_ts,
        event.get("ts"),
    )
    if is_singapore_notification_policy_request(text, context):
        client.chat_postMessage(
            channel=route.channel_id,
            text=(
                "Singapore operational results stay in the private background-service lane and never create "
                "Salesforce tickets or Needs Review packets. Taylor can post a compact sanitized outcome in "
                "direct Agent Chat. Verified retired interfaces stay silent unless reactivation is requested; "
                "only an explicit brand-new integration/interface request may create a ticket."
            ),
            **_reply_target(config, thread_ts),
        )
        return
    task_kind = ""
    task_text = ""
    if has_files and _truthy(config.defaults.get("slack_file_fast_ingest_enabled", True)):
        intent_started = time.monotonic()
        inferred_intent = _safe_attachment_intent_hint(
            text,
            context,
            user_id,
            max_chars=int(config.defaults.get("slack_file_intent_hint_max_chars", 800)),
        )
        if inferred_intent:
            task_kind = "slack-attachment-readonly"
            task_text = inferred_intent
            context = (
                "Attachment intent hint (untrusted, read-only only; does not authorize writes): "
                f"{inferred_intent}\n{context}"
            ).strip()
            LOGGER.info(
                "Resolved generic Slack attachment intent in %.3fs for %s/%s",
                time.monotonic() - intent_started,
                route.channel_id,
                event.get("ts"),
            )
        elif GENERIC_ATTACHMENT_TEXT_RE.match(text) and _truthy(
            config.defaults.get("slack_file_ambiguous_requires_clarification", True)
        ):
            LOGGER.info(
                "Slack attachment intent remained ambiguous after %.3fs for %s/%s",
                time.monotonic() - intent_started,
                route.channel_id,
                event.get("ts"),
            )
            client.chat_postMessage(
                channel=route.channel_id,
                text=(
                    "I received the file, but I cannot safely determine what you want done with it. "
                    "Please reply with the specific task and reattach the file."
                ),
                **_reply_target(config, thread_ts),
            )
            return
    event_id = body.get("event_id")
    job_id, equivalent_job = STATE.create_job_unless_active_equivalent(
        event_id=event_id,
        channel_id=route.channel_id,
        thread_ts=thread_ts,
        user_id=user_id,
        agent_name=route.agent_name,
        request_text=text,
        recovery_policy="review_required" if has_files else "queued_replay",
        guard_equivalent=not has_files and not bool(steer_command),
    )
    if equivalent_job is not None:
        existing_agent = str(equivalent_job.get("agent_name") or "agent")
        existing_status = str(equivalent_job.get("status") or "active")
        try:
            client.chat_postMessage(
                channel=route.channel_id,
                text=(
                    f"This request matches active `{existing_agent}` job `{job_id}` ({existing_status}). "
                    "I did not start a second writer."
                ),
                **_reply_target(config, thread_ts),
            )
        except Exception:
            LOGGER.exception("Could not post active-job duplicate notice for Slack job %s", job_id)
        return
    with ACTIVE_JOB_IDS_LOCK:
        ACTIVE_JOB_IDS.add(job_id)
        ACTIVE_JOB_CONTEXT[job_id] = (route.channel_id, route.agent_name)

    progress_ts = None
    if config.defaults.get("progress_message_enabled", True):
        try:
            response = client.chat_postMessage(
                channel=route.channel_id,
                text=_progress_text(route.agent_name, user_id, job_id, 0),
                **_reply_target(config, thread_ts),
            )
            progress_ts = response.get("ts")
        except Exception:
            LOGGER.exception("Could not post initial progress message for Slack job %s; continuing without it", job_id)

    request = AgentRequest(
        text=trusted_text,
        channel_id=route.channel_id,
        user_id=user_id,
        thread_ts=thread_ts,
        context=context,
        slack_event=event,
        job_id=job_id,
        task_kind=task_kind,
        task_text=task_text,
        surface="slack",
        conversation_id=_slack_conversation_id(route.channel_id, thread_ts),
        authority_kind="operator",
        message_signature=sign_trusted_message(
            agent=agent,
            text=trusted_text,
            source="slack",
            actor=user_id,
            channel_id=route.channel_id,
            thread_ts=thread_ts,
            authority_kind="operator",
        ),
        is_steering=bool(steer_command),
    )
    _submit_slack_job_future(
        config,
        route.agent_name,
        agent,
        request,
        client,
        max_chars,
        progress_ts,
    )


def _run_and_reply_legacy(
    config: BridgeConfig,
    agent_name: str,
    agent: dict[str, Any],
    request: AgentRequest,
    client: Any,
    max_chars: int,
    progress_ts: str | None,
) -> None:
    if STATE is None:
        raise RuntimeError("Bridge state is not configured")
    if request.job_id is not None and request.job_id in CANCELLED_JOB_IDS:
        STATE.mark_cancelled(request.job_id, "Operator cancelled the queued agent job.")
        with ACTIVE_JOB_IDS_LOCK:
            ACTIVE_JOB_IDS.discard(request.job_id)
            ACTIVE_JOB_CONTEXT.pop(request.job_id, None)
            CANCELLED_JOB_IDS.discard(request.job_id)
        return
    lock = _channel_lock(request.channel_id) if config.defaults.get("serialize_channel_runs", True) else None
    agent_lock = _agent_run_lock(agent_name)
    acquired_channel = lock is None or lock.acquire(blocking=False)
    acquired_agent = acquired_channel and agent_lock.acquire(blocking=False)
    if not acquired_channel or not acquired_agent:
        if acquired_channel and lock is not None:
            lock.release()
        timer = Timer(
            1.0,
            lambda: EXECUTOR.submit(
                _run_and_reply,
                config,
                agent_name,
                agent,
                request,
                client,
                max_chars,
                progress_ts,
            ) if EXECUTOR is not None else None,
        )
        timer.daemon = True
        timer.start()
        return
    stop_progress = Event()
    heartbeat = None
    if progress_ts:
        heartbeat = Thread(
            target=_progress_heartbeat,
            args=(config, client, request, agent_name, progress_ts, stop_progress),
            name=f"progress-{request.job_id or 'unknown'}",
            daemon=True,
        )
        heartbeat.start()
    agent_request = request
    try:
        _append_shared_chat_event(config, agent_name, request, role="user", text=request.text)
        if progress_ts and request.slack_event and event_has_files(request.slack_event):
            client.chat_update(
                channel=request.channel_id,
                ts=progress_ts,
                text=f"`{agent_name}` is reading Slack file(s) for <@{request.user_id}> `{request.job_id}`...",
            )
        agent_request = _prepare_agent_request(config, agent_name, agent, request, client)
    except Exception:
        LOGGER.exception("Could not prepare Slack files or memory for job %s", request.job_id)
        agent_request = replace(
            request,
            files_context=(
                "Attached Slack files:\n"
                "- File processing failed before the agent run. Check bridge logs; local file decoding may need attention."
            ),
            slack_event=None,
        )
    try:
        if request.job_id is not None and request.job_id in CANCELLED_JOB_IDS:
            STATE.mark_cancelled(request.job_id, "Operator cancelled the agent job before model start.")
            return
        if request.job_id is not None:
            STATE.mark_started(request.job_id)
        run_started = time.time() - 2
        deterministic_fast = (
            _try_deterministic_location_region_update(config, agent_request)
            if not agent_request.is_steering
            else None
        )
        fast = None
        if deterministic_fast is None and not agent_request.is_steering:
            try:
                fast = try_fast_response(
                    agent_name=agent_name,
                    agent=agent,
                    request=agent_request,
                    context=_fast_responder_context(agent_name, agent, "Slack"),
                )
            except Exception:
                LOGGER.exception("Fast responder failed for Slack job %s; falling back to main agent", request.job_id)
        if deterministic_fast is not None:
            result = deterministic_fast
            LOGGER.info(
                "Deterministic location-region broker answered Slack job %s",
                request.job_id,
            )
        elif fast is not None:
            result = fast.answer
            LOGGER.info("Fast responder answered Slack job %s for %s with %s", request.job_id, agent_name, fast.model)
        else:
            result = run_agent(agent_name, agent, agent_request)
        outcome = _classify_runtime_result(result, fast_response=fast is not None)
        if outcome.transport_failure:
            raise RuntimeError(_agent_result_failure_message(result) or "Agent worker failed before returning a result.")
        cancelled = request.job_id is not None and request.job_id in CANCELLED_JOB_IDS
        if not cancelled:
            result, outcome = _prepare_slack_delivery_result(
                config,
                agent_name,
                agent,
                client,
                agent_request,
                result,
                outcome,
            )
            result, outcome = _route_slack_result_handoff(
                config,
                agent_name,
                agent_request,
                result,
                outcome,
            )
        handoff_pending = _is_pending_handoff_result(result)
        if request.job_id is not None:
            if cancelled:
                STATE.mark_interrupted(request.job_id, "Operator stopped the active agent job.")
                result = "BLOCKED\nStopped by the operator before completion."
            elif handoff_pending:
                STATE.update_runtime_stage(
                    request.job_id,
                    "handoff_acknowledged",
                )
            else:
                STATE.mark_outcome(
                    request.job_id,
                    outcome.normalized_status,
                    result_text=redact_secrets(result),
                    review_reason=_outcome_review_reason(outcome, result),
                    # A reported completion is still unverified. Independent
                    # readback is required before it can become trusted learning.
                    learning_eligible=False,
                    # Slack agent work is a direct conversation. A blocker stays
                    # in that Slack thread and must not become a dashboard packet.
                    review_required=False,
                )
        if deterministic_fast is None and fast is None and not cancelled:
            _store_learning_observation(agent_name, agent_request, result, outcome, surface="slack")
            _cleanup_recent_sandbox_junk(config, agent_name, agent, agent_request, run_started)
            _register_recent_sandbox_artifacts(config, agent_name, agent, agent_request, run_started)
        _append_shared_chat_event(config, agent_name, agent_request, role="assistant", text=result)
    except Exception:
        LOGGER.exception("Agent %s failed", agent_name)
        result = f"`{agent_name}` failed. Check the bridge console logs."
        if request.job_id is not None:
            STATE.mark_failed(request.job_id, result, review_required=False)
    finally:
        if lock:
            lock.release()
        agent_lock.release()
        stop_progress.set()
        if request.job_id is not None:
            with ACTIVE_JOB_IDS_LOCK:
                ACTIVE_JOB_IDS.discard(request.job_id)
                ACTIVE_JOB_CONTEXT.pop(request.job_id, None)
                CANCELLED_JOB_IDS.discard(request.job_id)

    if not result.strip():
        result = "BLOCKED\nAgent returned no final response."

    _deliver_slack_job_feedback(
        config,
        client,
        job_id=request.job_id,
        agent_name=agent_name,
        channel_id=request.channel_id,
        thread_ts=agent_request.thread_ts,
        user_id=agent_request.user_id,
        result=result,
        max_chars=max_chars,
        progress_ts=progress_ts,
    )


def _run_and_reply(
    config: BridgeConfig,
    agent_name: str,
    agent: dict[str, Any],
    request: AgentRequest,
    client: Any,
    max_chars: int,
    progress_ts: str | None,
) -> None:
    """Execute one atomically claimed Slack job and fence every late result."""
    if STATE is None:
        raise RuntimeError("Bridge state is not configured")
    job_id = request.job_id
    if job_id is not None and job_id in CANCELLED_JOB_IDS:
        if job_id in RECOVERY_REVIEW_JOB_IDS:
            STATE.requeue_for_recovery(
                job_id,
                "Watchdog fenced the job before model start.",
                recovery_policy="same_surface_readback_first",
            )
        else:
            STATE.mark_cancelled(job_id, "Operator cancelled the queued agent job.")
        _clear_active_slack_job(job_id)
        return

    channel_lock = _channel_lock(request.channel_id) if config.defaults.get("serialize_channel_runs", True) else None
    agent_lock = _agent_run_lock(agent_name)
    acquired_channel = channel_lock is None or channel_lock.acquire(blocking=False)
    acquired_agent = acquired_channel and agent_lock.acquire(blocking=False)
    if not acquired_channel or not acquired_agent:
        if acquired_channel and channel_lock is not None:
            channel_lock.release()
        if job_id is not None:
            STATE.update_runtime_stage(job_id, "queued_waiting_lane")
        timer = Timer(
            1.0,
            _retry_slack_job_after_lane_wait,
            args=(config, agent_name, agent, request, client, max_chars, progress_ts),
        )
        timer.daemon = True
        if job_id is not None:
            with ACTIVE_JOB_IDS_LOCK:
                previous = ACTIVE_JOB_RETRY_TIMERS.get(job_id)
                if previous is not None:
                    previous.cancel()
                ACTIVE_JOB_RETRY_TIMERS[job_id] = timer
        timer.start()
        return

    stop_progress = Event()
    agent_request = request
    result = ""
    publish_result = False
    handoff_pending = False
    route_receipt: VerifiedRouteReceipt | None = None
    route_store = VERIFIED_ROUTES
    try:
        if job_id is not None and not STATE.mark_started(
            job_id,
            runtime_instance_id=RUNTIME_INSTANCE_ID,
            stage="preparing",
        ):
            return
        heartbeat = Thread(
            target=_progress_heartbeat,
            args=(config, client, request, agent_name, progress_ts, stop_progress),
            name=f"progress-{job_id or 'unknown'}",
            daemon=True,
        )
        heartbeat.start()
        try:
            _append_shared_chat_event(config, agent_name, request, role="user", text=request.text)
            attachment_ingest = bool(request.slack_event and event_has_files(request.slack_event))
            ingest_started = time.monotonic()
            if attachment_ingest:
                if job_id is not None:
                    STATE.update_runtime_stage(
                        job_id,
                        "attachment_ingest",
                        runtime_instance_id=RUNTIME_INSTANCE_ID,
                    )
                if progress_ts:
                    client.chat_update(
                        channel=request.channel_id,
                        ts=progress_ts,
                        text=f"`{agent_name}` is reading Slack file(s) for <@{request.user_id}> `{job_id}`...",
                    )
            agent_request = _prepare_agent_request(config, agent_name, agent, request, client)
            if route_store is not None:
                try:
                    route_match = route_store.match(
                        query=agent_request.task_text or agent_request.text,
                        agent_name=agent_name,
                    )
                except Exception:
                    route_match = None
                    LOGGER.exception("Verified route lookup failed for Slack job %s", job_id)
                if route_match is not None:
                    agent_request = replace(
                        agent_request,
                        runtime_guidance="\n\n".join(
                            part
                            for part in (
                                agent_request.runtime_guidance,
                                route_match.guidance(),
                            )
                            if str(part or "").strip()
                        ),
                    )
            if attachment_ingest:
                elapsed = time.monotonic() - ingest_started
                target = float(config.defaults.get("slack_file_ingest_target_seconds", 10))
                log = LOGGER.warning if elapsed > target else LOGGER.info
                log("Slack attachment ingest for job %s completed in %.3fs", job_id, elapsed)
        except Exception:
            LOGGER.exception("Could not prepare Slack files or memory for job %s", job_id)
            agent_request = replace(
                request,
                files_context=(
                    "Attached Slack files:\n"
                    "- File processing failed before the agent run. Check bridge logs; local file decoding may need attention."
                ),
                slack_event=None,
            )

        run_started = time.time() - 2
        deterministic_fast = (
            _try_deterministic_location_region_update(config, agent_request)
            if not agent_request.is_steering
            else None
        )
        fast = None
        if deterministic_fast is None and not agent_request.is_steering:
            try:
                if job_id is not None:
                    STATE.update_runtime_stage(
                        job_id,
                        "fast_response_check",
                        runtime_instance_id=RUNTIME_INSTANCE_ID,
                    )
                fast = try_fast_response(
                    agent_name=agent_name,
                    agent=agent,
                    request=agent_request,
                    context=_fast_responder_context(agent_name, agent, "Slack"),
                )
            except Exception:
                LOGGER.exception("Fast responder failed for Slack job %s; falling back to main agent", job_id)
        if deterministic_fast is not None:
            result = deterministic_fast
            LOGGER.info(
                "Deterministic location-region broker answered Slack job %s",
                job_id,
            )
        elif fast is not None:
            result = fast.answer
            LOGGER.info("Fast responder answered Slack job %s for %s with %s", job_id, agent_name, fast.model)
        else:
            if job_id is not None:
                STATE.update_runtime_stage(
                    job_id,
                    "running_isolated_agent",
                    runtime_instance_id=RUNTIME_INSTANCE_ID,
                )
            worker_max_attempts = max(
                1,
                min(int(config.defaults.get("agent_worker_max_attempts", 3)), 5),
            )
            prior_attempts = 0
            if job_id is not None:
                jobs_by_ids = getattr(STATE, "jobs_by_ids", None)
                durable = (
                    jobs_by_ids({job_id}).get(job_id, {})
                    if callable(jobs_by_ids)
                    else {}
                )
                prior_attempts = max(0, int(durable.get("recovery_count") or 0))
            if prior_attempts >= worker_max_attempts:
                raise RuntimeError(
                    f"Worker retry budget exhausted after {prior_attempts} recovery attempts."
                )

            def run_attempt(_attempt: int, recovery_guidance: str) -> str:
                guidance = "\n\n".join(
                    part
                    for part in (
                        agent_request.runtime_guidance,
                        recovery_guidance,
                    )
                    if str(part or "").strip()
                )
                return run_agent_isolated(
                    agent_name,
                    agent,
                    replace(agent_request, runtime_guidance=guidance),
                )

            def attempt_progress(event: str, attempt: int, _decision: Any) -> None:
                if job_id is None:
                    return
                stage = {
                    "attempt_started": f"running_model_attempt_{attempt}",
                    "attempt_failed": f"retryable_failure_attempt_{attempt}",
                    "retry_backoff": f"retry_backoff_after_attempt_{attempt}",
                    "attempt_completed": f"model_attempt_{attempt}_completed",
                }.get(event, "running_isolated_agent")
                STATE.update_runtime_stage(
                    job_id,
                    stage,
                    runtime_instance_id=RUNTIME_INSTANCE_ID,
                )

            attempt_result = execute_bounded_attempts(
                run_attempt,
                max_attempts=worker_max_attempts - prior_attempts,
                retry_delays=bounded_retry_delays(
                    config.defaults,
                    max_attempts=worker_max_attempts - prior_attempts,
                ),
                idempotency_key=f"bridge-job:{job_id}" if job_id is not None else "",
                recovered_after_restart=bool(prior_attempts),
                attempt_offset=prior_attempts,
                on_progress=attempt_progress,
            )
            result = attempt_result.result
            try:
                result, route_receipt = extract_verified_route_receipt(result)
            except ValueError as exc:
                LOGGER.warning(
                    "Ignored invalid verified route receipt for Slack job %s: %s",
                    job_id,
                    redact_secrets(str(exc)),
                )
                result = re.sub(
                    rf"^[ \t]*{re.escape(VERIFIED_ROUTE_RECEIPT_MARKER)}[^\r\n]*$",
                    "",
                    result,
                    flags=re.MULTILINE,
                ).strip()
        outcome = _classify_runtime_result(result, fast_response=fast is not None)
        if outcome.transport_failure:
            raise RuntimeError(_agent_result_failure_message(result) or "Agent worker failed before returning a result.")

        cancelled = job_id is not None and job_id in CANCELLED_JOB_IDS
        if not cancelled:
            result, outcome = _prepare_slack_delivery_result(
                config,
                agent_name,
                agent,
                client,
                agent_request,
                result,
                outcome,
            )
            result, outcome = _route_slack_result_handoff(
                config,
                agent_name,
                agent_request,
                result,
                outcome,
            )
            handoff_pending = _is_pending_handoff_result(result)
        if job_id is not None:
            if job_id in RECOVERY_REVIEW_JOB_IDS:
                durable = STATE.jobs_by_ids({job_id}).get(job_id, {})
                if str(durable.get("recovery_policy") or "").lower() == "review_required":
                    STATE.mark_recovery_review_required(
                        job_id,
                        "Watchdog fenced work with transient input that cannot be replayed safely.",
                    )
                else:
                    STATE.requeue_for_recovery(
                        job_id,
                        "Watchdog fenced this started job after worker-health loss.",
                        recovery_policy="same_surface_readback_first",
                        runtime_instance_id=RUNTIME_INSTANCE_ID,
                    )
                return
            if cancelled:
                STATE.mark_interrupted(job_id, "Operator stopped the active agent job.")
                result = "BLOCKED\nStopped by the operator before completion."
            elif handoff_pending:
                if not STATE.update_runtime_stage(
                    job_id,
                    "handoff_acknowledged",
                    runtime_instance_id=RUNTIME_INSTANCE_ID,
                ):
                    LOGGER.warning(
                        "Discarded handoff acknowledgement from fenced Slack job %s",
                        job_id,
                    )
                    return
            elif not STATE.mark_outcome(
                job_id,
                outcome.normalized_status,
                result_text=redact_secrets(result),
                review_reason=_outcome_review_reason(outcome, result),
                runtime_instance_id=RUNTIME_INSTANCE_ID,
                # A reported completion is still unverified. Independent
                # readback is required before it can become trusted learning.
                learning_eligible=False,
                # Slack agent work is a direct conversation. A blocker stays
                # in that Slack thread and must not become a dashboard packet.
                review_required=False,
            ):
                LOGGER.warning("Discarded late result from fenced Slack job %s", job_id)
                return
        if (
            route_receipt is not None
            and route_store is not None
            and outcome.business_success
            and not handoff_pending
        ):
            try:
                route_store.record_success(
                    query=agent_request.task_text or agent_request.text,
                    agent_name=agent_name,
                    receipt=route_receipt,
                    source_job_id=f"slack:{job_id}" if job_id is not None else "slack",
                )
            except Exception:
                LOGGER.exception(
                    "Verified route receipt was not persisted for Slack job %s",
                    job_id,
                )
        if (
            deterministic_fast is None
            and fast is None
            and not cancelled
            and not handoff_pending
        ):
            _store_learning_observation(agent_name, agent_request, result, outcome, surface="slack")
            _cleanup_recent_sandbox_junk(config, agent_name, agent, agent_request, run_started)
            _register_recent_sandbox_artifacts(config, agent_name, agent, agent_request, run_started)
        _append_shared_chat_event(config, agent_name, agent_request, role="assistant", text=result)
        publish_result = True
    except Exception as exc:
        LOGGER.exception("Agent %s failed", agent_name)
        result = f"`{agent_name}` failed. Check the bridge console logs."
        if job_id is None:
            publish_result = True
        elif job_id in RECOVERY_REVIEW_JOB_IDS or classify_retryable_failure(exc).retryable:
            STATE.mark_recovery_review_required(
                job_id,
                "Bounded worker recovery ended without authoritative same-surface readback.",
            )
            publish_result = False
        else:
            publish_result = STATE.mark_failed(
                job_id,
                f"{result} {exc}",
                runtime_instance_id=RUNTIME_INSTANCE_ID,
                review_required=False,
            )
    finally:
        if acquired_channel and channel_lock is not None:
            channel_lock.release()
        if acquired_agent:
            agent_lock.release()
        stop_progress.set()
        if job_id is not None:
            _clear_active_slack_job(job_id)

    if not publish_result:
        return
    if not result.strip():
        result = "BLOCKED\nAgent returned no final response."
    _deliver_slack_job_feedback(
        config,
        client,
        job_id=job_id,
        agent_name=agent_name,
        channel_id=request.channel_id,
        thread_ts=agent_request.thread_ts,
        user_id=agent_request.user_id,
        result=result,
        max_chars=max_chars,
        progress_ts=progress_ts,
    )


def _clear_active_slack_job(job_id: int) -> None:
    with ACTIVE_JOB_IDS_LOCK:
        retry_timer = ACTIVE_JOB_RETRY_TIMERS.pop(job_id, None)
        if retry_timer is not None:
            retry_timer.cancel()
        ACTIVE_JOB_IDS.discard(job_id)
        ACTIVE_JOB_CONTEXT.pop(job_id, None)
        ACTIVE_JOB_FUTURES.pop(job_id, None)
        CANCELLED_JOB_IDS.discard(job_id)
        RECOVERY_REVIEW_JOB_IDS.discard(job_id)
        ACTIVE_JOB_CANCEL_REQUESTED_AT.pop(job_id, None)


def _deliver_slack_job_feedback(
    config: BridgeConfig,
    client: Any,
    *,
    job_id: int | None,
    agent_name: str,
    channel_id: str,
    thread_ts: str,
    user_id: str,
    result: str,
    max_chars: int,
    progress_ts: str | None,
) -> None:
    """Deliver one final response and confirm its durable outbox entry."""

    delivery = _public_agent_display_text(
        agent_name,
        str(result or "").strip() or "BLOCKED\nAgent returned no final response.",
    )
    if not config.defaults.get("reply_in_thread", False):
        job_ref = f"job `{job_id}`" if job_id is not None else "job"
        delivery = f"`{public_agent_name(agent_name)}` {job_ref} for <@{user_id}>:\n{delivery}"
    chunks = chunk_for_slack(delivery, max_chars)
    try:
        if progress_ts:
            client.chat_update(channel=channel_id, ts=progress_ts, text=chunks[0])
            chunks = chunks[1:]
        for index, chunk in enumerate(chunks):
            kwargs = _reply_target(config, thread_ts)
            if job_id is not None:
                kwargs["client_msg_id"] = str(
                    uuid.uuid5(uuid.NAMESPACE_URL, f"nova-slack-job:{job_id}:final:{index}")
                )
            client.chat_postMessage(channel=channel_id, text=chunk, **kwargs)
    except Exception as exc:
        if STATE is not None and job_id is not None and hasattr(STATE, "mark_delivery_failed"):
            STATE.mark_delivery_failed(job_id, redact_secrets(str(exc)))
        raise
    if STATE is not None and job_id is not None and hasattr(STATE, "mark_delivery_succeeded"):
        STATE.mark_delivery_succeeded(job_id)


def _deliver_pending_terminal_slack_feedback(config: BridgeConfig, client: Any) -> int:
    """Retry terminal job feedback left pending by a crash or Slack outage."""

    if STATE is None or not hasattr(STATE, "list_pending_terminal_deliveries"):
        return 0
    delivered = 0
    for row in STATE.list_pending_terminal_deliveries(limit=100):
        job_id = int(row["id"])
        status = str(row.get("status") or "blocked").strip().upper()
        result = str(row.get("result_text") or "").strip()
        if not result:
            reason = str(
                row.get("reconciliation_reason")
                or row.get("error")
                or "The runtime ended before the job returned a final response."
            ).strip()
            result = (
                f"BLOCKED\nJob {job_id} did not complete cleanly. {reason} "
                "The failure was recovered and feedback delivery is active."
            )
        elif first_nonempty_line(result).strip().upper() not in {
            "COMPLETED",
            "COMPLETED_WITH_ISSUES",
            "BLOCKED",
            "FAILED",
        }:
            result = f"{status if status in {'COMPLETED', 'COMPLETED_WITH_ISSUES', 'BLOCKED', 'FAILED'} else 'BLOCKED'}\n{result}"
        try:
            _deliver_slack_job_feedback(
                config,
                client,
                job_id=job_id,
                agent_name=str(row.get("agent_name") or "agent"),
                channel_id=str(row.get("channel_id") or ""),
                thread_ts=str(row.get("thread_ts") or ""),
                user_id=str(row.get("user_id") or ""),
                result=result,
                max_chars=int(config.defaults.get("max_slack_message_chars", 3900)),
                progress_ts=None,
            )
            delivered += 1
        except Exception:
            LOGGER.exception("Could not deliver pending terminal feedback for Slack job %s", job_id)
    return delivered


def _retry_slack_job_after_lane_wait(
    config: BridgeConfig,
    agent_name: str,
    agent: dict[str, Any],
    request: AgentRequest,
    client: Any,
    max_chars: int,
    progress_ts: str | None,
) -> None:
    job_id = request.job_id
    if job_id is not None:
        with ACTIVE_JOB_IDS_LOCK:
            ACTIVE_JOB_RETRY_TIMERS.pop(job_id, None)
            if job_id not in ACTIVE_JOB_IDS:
                return
    _submit_slack_job_future(config, agent_name, agent, request, client, max_chars, progress_ts)


def _slack_attempt_deadline_seconds(config: BridgeConfig, row: dict[str, object]) -> float:
    agent = dict(config.defaults)
    agent.update(config.agents.get(str(row.get("agent_name") or ""), {}))
    task_timeout = max(30, int(agent.get("timeout_seconds") or 600))
    subagent_timeout = max(0, int(agent.get("subagent_timeout_seconds") or 0))
    grace = max(30, int(agent.get("agent_runtime_attempt_deadline_grace_seconds") or 120))
    derived = task_timeout + subagent_timeout + grace
    configured_cap = max(30, int(agent.get("agent_job_hard_timeout_seconds") or derived))
    return float(min(derived, configured_cap))


def _agent_result_failure_message(text: str) -> str:
    first_line = next((line.strip() for line in str(text or "").splitlines() if line.strip()), "")
    normalized = first_line.casefold()
    prefixes = (
        "codex run failed",
        "codex could not complete",
        "codex run timed out",
        "claude run failed",
        "claude run timed out",
        "agent worker exceeded",
    )
    return redact_secrets(first_line)[:800] if any(normalized.startswith(prefix) for prefix in prefixes) else ""


def _classify_runtime_result(text: str, *, fast_response: bool = False) -> AgentOutcome:
    """Classify durable work conservatively while preserving harmless fast replies."""

    if fast_response:
        # The read-only fast responder returns user-facing prose, not managed
        # outcome markers. It cannot perform or verify live work and is never
        # eligible for procedural learning.
        return AgentOutcome(AgentOutcomeStatus.COMPLETED)
    return classify_agent_outcome(text)


def _outcome_review_reason(outcome: AgentOutcome, text: str) -> str:
    if not outcome.needs_review:
        return ""
    first_line = redact_secrets(first_nonempty_line(text))[:800]
    if outcome.status is AgentOutcomeStatus.UNCLASSIFIED:
        return f"Agent response omitted a valid leading outcome marker. {first_line}".strip()
    return first_line or f"Agent reported {outcome.normalized_status}."


def _prepare_slack_delivery_result(
    config: BridgeConfig,
    agent_name: str,
    agent: dict[str, Any],
    client: Any,
    request: AgentRequest,
    result: str,
    outcome: AgentOutcome,
) -> tuple[str, AgentOutcome]:
    """Complete requested file delivery before committing the job outcome."""

    clean_result, upload_paths = split_upload_directives(result)
    upload_notes = _upload_directed_files(
        config,
        agent_name,
        agent,
        client,
        request,
        upload_paths,
    )
    safe_notes = [redact_secrets(note) for note in upload_notes]
    if safe_notes:
        clean_result = (clean_result.rstrip() + "\n\n" + "\n".join(safe_notes)).strip()
    upload_issues = [note for note in safe_notes if not note.startswith("Uploaded file:")]
    if upload_issues and outcome.business_success:
        clean_result = (
            "COMPLETED_WITH_ISSUES: The agent completed its main work, but requested "
            "Slack file delivery was not fully successful.\n\n"
            f"{clean_result}"
        ).strip()
        outcome = AgentOutcome(AgentOutcomeStatus.COMPLETED_WITH_ISSUES)
    return clean_result, outcome


def _already_seen(body: dict[str, Any]) -> bool:
    if STATE is None:
        return False
    return not STATE.record_event_once(body.get("event_id"))


def _channel_lock(channel_id: str) -> Lock:
    with CHANNEL_LOCKS_LOCK:
        if channel_id not in CHANNEL_LOCKS:
            CHANNEL_LOCKS[channel_id] = Lock()
        return CHANNEL_LOCKS[channel_id]


def _agent_run_lock(agent_name: str) -> Lock:
    with AGENT_RUN_LOCKS_LOCK:
        if agent_name not in AGENT_RUN_LOCKS:
            AGENT_RUN_LOCKS[agent_name] = Lock()
        return AGENT_RUN_LOCKS[agent_name]


def _cancel_active_slack_jobs(channel_id: str, agent_name: str) -> list[int]:
    stopped: list[int] = []
    with ACTIVE_JOB_IDS_LOCK:
        candidates = [
            job_id
            for job_id, context in ACTIVE_JOB_CONTEXT.items()
            if context == (channel_id, agent_name)
        ]
        CANCELLED_JOB_IDS.update(candidates)
    for job_id in candidates:
        if cancel_agent_job(job_id):
            stopped.append(job_id)
        elif STATE is not None:
            # A queued job has no child process yet; remove it from the durable
            # active set so admission retries become a harmless no-op.
            STATE.mark_cancelled(job_id, "Operator cancelled the queued agent job.")
            stopped.append(job_id)
    return stopped


def _is_ignored_message(event: dict[str, Any]) -> bool:
    subtype = event.get("subtype")
    if subtype == "file_share" and event.get("files") and event.get("user") is not None:
        return False
    return bool(
        event.get("bot_id")
        or subtype
        or event.get("user") is None
        or (event.get("text") is None and not event.get("files"))
    )


def _collect_slack_context(
    config: BridgeConfig,
    client: Any,
    channel_id: str,
    thread_ts: str,
    current_ts: str | None,
) -> str:
    max_messages = int(config.defaults.get("max_context_messages", 20))
    char_limit = int(config.defaults.get("context_char_limit", 24000))
    if max_messages <= 0 or char_limit <= 0:
        return ""

    messages_by_ts: dict[str, dict[str, Any]] = {}
    try:
        history = client.conversations_history(
            channel=channel_id,
            limit=max_messages,
            latest=current_ts,
            inclusive=False,
        )
    except Exception as exc:
        LOGGER.warning("Could not collect Slack channel context for %s: %s", channel_id, exc)
        history = {}

    for message in history.get("messages") or []:
        ts = str(message.get("ts") or "")
        if ts and ts != current_ts:
            messages_by_ts[ts] = message

    if thread_ts and current_ts and thread_ts != current_ts:
        try:
            replies = client.conversations_replies(
                channel=channel_id,
                ts=thread_ts,
                limit=max_messages,
            )
        except Exception as exc:
            LOGGER.warning("Could not collect Slack thread context for %s/%s: %s", channel_id, thread_ts, exc)
            replies = {}

        for message in replies.get("messages") or []:
            ts = str(message.get("ts") or "")
            if ts and ts != current_ts:
                messages_by_ts[ts] = message

    lines: list[str] = []
    messages = sorted(messages_by_ts.values(), key=lambda item: float(item.get("ts", "0")))
    for message in messages[-max_messages:]:
        line = _format_context_message(message)
        if line:
            lines.append(line)

    context = "\n".join(lines)
    if len(context) > char_limit:
        return context[-char_limit:]
    return context


def _safe_attachment_intent_hint(text: str, context: str, user_id: str, *, max_chars: int) -> str:
    """Reuse only a bounded, same-user, explicitly read-only thread instruction."""
    if not GENERIC_ATTACHMENT_TEXT_RE.match(text or ""):
        return ""
    speaker = f"<@{user_id}>:"
    for raw_line in reversed((context or "").splitlines()):
        line = raw_line.strip()
        if not line.startswith(speaker):
            continue
        candidate = re.sub(r"\s*\[files:.*?\]\s*$", "", line[len(speaker):].strip()).strip()
        if not candidate or GENERIC_ATTACHMENT_TEXT_RE.match(candidate):
            continue
        candidate = candidate[: max(1, max_chars)].strip()
        if READ_ONLY_ATTACHMENT_INTENT_RE.search(candidate) and not MUTATING_ATTACHMENT_INTENT_RE.search(candidate):
            return candidate
        return ""
    return ""


def _format_context_message(message: dict[str, Any]) -> str:
    text = strip_bot_mentions(message.get("text") or "").strip()
    if _is_progress_message_text(text):
        return ""

    file_bits: list[str] = []
    for item in message.get("files") or []:
        if not isinstance(item, dict):
            continue
        name = item.get("name") or item.get("title") or item.get("id") or "file"
        mimetype = item.get("mimetype") or item.get("filetype") or "unknown"
        file_bits.append(f"{name} ({mimetype})")
    if file_bits:
        text = (text + " " if text else "") + "[files: " + "; ".join(file_bits[:5]) + "]"
    if not text:
        return ""

    user = message.get("user")
    if user:
        speaker = f"<@{user}>"
    elif message.get("bot_id"):
        speaker = f"bot:{message.get('bot_id')}"
    else:
        speaker = "unknown"
    return f"{speaker}: {text}"


def _is_progress_message_text(text: str) -> bool:
    return " is writing for " in text or " is reading Slack file(s) for " in text


def _prepare_agent_request(
    config: BridgeConfig,
    agent_name: str,
    agent: dict[str, Any],
    request: AgentRequest,
    client: Any,
) -> AgentRequest:
    downloaded_files = []
    if request.slack_event:
        downloaded_files = download_event_files(config=config, event=request.slack_event, client=client)
    grant_agent_file_access(
        agent,
        [str(item.get("local_path") or "") for item in downloaded_files if item.get("local_path")],
        allowed_roots=[str(config.defaults.get("slack_file_download_dir", "data/slack_files"))],
    )
    files_context = format_files_for_prompt(downloaded_files)
    image_paths = tuple(
        str(item.get("local_path") or "")
        for item in downloaded_files
        if str(item.get("mimetype") or "").lower().startswith("image/")
        and str(item.get("local_path") or "").strip()
    )
    if _truthy(agent.get("direct_codex_raw_prompt")):
        return replace(
            request,
            context="",
            memory="",
            files_context=files_context,
            image_paths=image_paths,
            slack_event=None,
        )
    memory_context = _retrieve_agent_memory(
        config,
        agent_name,
        agent,
        request.text,
        "\n".join(part for part in (request.context, files_context) if part),
    )
    shared_context = _shared_runtime_context(config, agent_name)
    return replace(
        request,
        memory="\n\n".join(part for part in (memory_context, shared_context) if part.strip()),
        files_context=files_context,
        image_paths=image_paths,
        slack_event=None,
    )


def _handle_memory_command(
    config: BridgeConfig,
    route: ChannelRoute,
    client: Any,
    thread_ts: str,
    user_id: str,
    text: str,
) -> bool:
    if MEMORY is None or not config.defaults.get("memory_enabled", True):
        return False

    stripped = text.strip()
    lowered = stripped.lower()
    if lowered.startswith("!remember-global "):
        memory_text = stripped[len("!remember-global ") :].strip()
        memory_id = MEMORY.remember(
            agent_name=str(config.defaults.get("memory_global_agent", "global")),
            text=memory_text,
            source=f"slack:{route.channel_id}:{user_id}",
            tags=["manual", "global"],
            importance=2.0,
        )
        client.chat_postMessage(
            channel=route.channel_id,
            text=f"Remembered globally: `{memory_id}`",
            **_reply_target(config, thread_ts),
        )
        return True

    if lowered.startswith("!remember "):
        memory_text = stripped[len("!remember ") :].strip()
        memory_id = MEMORY.remember(
            agent_name=route.agent_name,
            text=memory_text,
            source=f"slack:{route.channel_id}:{user_id}",
            tags=["manual"],
            importance=2.0,
        )
        client.chat_postMessage(
            channel=route.channel_id,
            text=f"Remembered for `{route.agent_name}`: `{memory_id}`",
            **_reply_target(config, thread_ts),
        )
        return True

    if lowered == "!memory" or lowered.startswith("!memory "):
        query = stripped[len("!memory") :].strip()
        limit = int(config.defaults.get("memory_top_k", 8))
        if query:
            memories = MEMORY.retrieve(agent_name=route.agent_name, query=query, top_k=limit)
        else:
            memories = MEMORY.recent(agent_name=route.agent_name, limit=limit)
        client.chat_postMessage(
            channel=route.channel_id,
            text=_format_memory_results(route.agent_name, memories),
            **_reply_target(config, thread_ts),
        )
        return True

    return False


def _handle_prospective_command(
    config: BridgeConfig,
    route: ChannelRoute,
    client: Any,
    thread_ts: str,
    user_id: str,
    text: str,
) -> bool:
    stripped = text.strip()
    lowered = stripped.lower()
    if lowered == "!reminders":
        try:
            response = _command_center_json(config, "GET", "/prospective/tasks?status=active&limit=25")
            tasks = list(response.get("tasks") or [])
            lines = ["Active reminders:"]
            for task in tasks:
                lines.append(
                    f"- `{str(task.get('id') or '')[:8]}` {task.get('next_scheduled_at') or 'unscheduled'} - {task.get('title') or 'Reminder'}"
                )
            if not tasks:
                lines.append("- None")
            reply = "\n".join(lines)
        except Exception as exc:
            LOGGER.exception("Could not list prospective tasks")
            reply = f"Could not list reminders: {exc}"
        client.chat_postMessage(channel=route.channel_id, text=reply, **_reply_target(config, thread_ts))
        return True

    if lowered.startswith("!cancel-reminder "):
        task_id = stripped[len("!cancel-reminder ") :].strip()
        try:
            response = _command_center_json(
                config,
                "POST",
                "/prospective/tasks/cancel",
                {"taskId": task_id},
            )
            task = dict(response.get("task") or {})
            reply = f"Cancelled reminder `{str(task.get('id') or task_id)[:8]}`."
        except Exception as exc:
            LOGGER.exception("Could not cancel prospective task")
            reply = f"Could not cancel reminder: {exc}"
        client.chat_postMessage(channel=route.channel_id, text=reply, **_reply_target(config, thread_ts))
        return True

    if lowered == "!remind" or lowered.startswith("!remind "):
        value = stripped[len("!remind") :].strip()
        if "|" not in value:
            reply = "Use `!remind <when> | <message>`, for example `!remind Monday at 10am | Review the Chargify upgrade`."
        else:
            due_text, reminder_text = (part.strip() for part in value.split("|", 1))
            try:
                response = _command_center_json(
                    config,
                    "POST",
                    "/prospective/tasks",
                    {
                        "due": due_text,
                        "title": reminder_text,
                        "timezone": str(config.defaults.get("prospective_timezone", "America/New_York")),
                        "channelId": route.channel_id,
                        "userId": user_id,
                        "createdBy": f"slack:{route.channel_id}:{user_id}",
                    },
                )
                task = dict(response.get("task") or {})
                reply = (
                    f"Reminder created for `{task.get('next_scheduled_at')}` "
                    f"({task.get('timezone')}). ID: `{str(task.get('id') or '')}`"
                )
            except Exception as exc:
                LOGGER.exception("Could not create prospective task")
                reply = f"Could not create reminder: {exc}"
        client.chat_postMessage(channel=route.channel_id, text=reply, **_reply_target(config, thread_ts))
        return True

    return False


def _handle_agent_session_command(
    config: BridgeConfig,
    route: ChannelRoute,
    client: Any,
    thread_ts: str,
    user_id: str,
    text: str,
    agent: dict[str, Any],
) -> bool:
    stripped = text.strip()
    lowered = stripped.lower()
    if lowered not in {"!agent-session", "!session", "!reset-agent-session", "!reset-session"}:
        return False

    store = session_store_from_agent(agent)
    conversation_id = _slack_conversation_id(route.channel_id, thread_ts)
    identity = runtime_identity(
        agent_name=route.agent_name,
        agent=agent,
        surface="slack",
        conversation_id=conversation_id,
    )
    if lowered in {"!reset-agent-session", "!reset-session"}:
        store.clear(
            agent_name=route.agent_name,
            surface=identity.surface,
            conversation_id=identity.conversation_id,
            provider=str(agent.get("provider") or "codex_cli"),
            workspace=str(agent.get("workspace_root") or ""),
            note=f"reset by {user_id}",
        )
        scope = "shared Slack/Agent Chat session" if identity.shared else "persistent session"
        client.chat_postMessage(
            channel=route.channel_id,
            text=f"Reset {scope} for `{route.agent_name}`. The next run starts fresh.",
            **_reply_target(config, thread_ts),
        )
        return True

    record = store.get(
        agent_name=route.agent_name,
        surface=identity.surface,
        conversation_id=identity.conversation_id,
    )
    if not record:
        scope = "shared Slack/Agent Chat session" if identity.shared else "this Slack thread"
        text_out = f"No active persistent session is recorded for `{route.agent_name}` in {scope}."
    else:
        scope = "shared Slack/Agent Chat session" if identity.shared else "this Slack thread"
        text_out = (
            f"Persistent session for `{route.agent_name}` in {scope}:\n"
            f"- session: `{record.session_id}`\n"
            f"- status: `{record.status}`\n"
            f"- runtime key: `{record.surface}:{record.conversation_id}`\n"
            f"- workspace: `{record.workspace}`"
        )
    client.chat_postMessage(
        channel=route.channel_id,
        text=text_out,
        **_reply_target(config, thread_ts),
    )
    return True


def _handle_status_command(
    config: BridgeConfig,
    route: ChannelRoute,
    client: Any,
    thread_ts: str,
    text: str,
) -> bool:
    if STATE is None:
        return False
    lowered = text.strip().lower()
    if lowered not in {"!agent-status", "!agents-status", "!system-status", "!bridge-status", "!jobs"}:
        return False

    limit = int(config.defaults.get("status_command_job_limit", 20))
    with ACTIVE_JOB_IDS_LOCK:
        live_job_ids = set(ACTIVE_JOB_IDS)
    for channel_id in config.channels:
        reconcile_system_jobs(
            config,
            STATE,
            runtime_job_ids=live_job_ids,
            authoritative=True,
            channel_id=channel_id,
        )
    snapshot = build_system_status(
        config,
        STATE,
        bridge_started_at=STARTED_AT,
        limit=limit,
    )
    response = format_system_status_for_slack(snapshot)
    max_chars = int(config.defaults.get("max_slack_message_chars", 3900))
    for chunk in chunk_for_slack(response, max_chars):
        client.chat_postMessage(
            channel=route.channel_id,
            text=chunk,
            **_reply_target(config, thread_ts),
        )
    return True


def _queue_web_search(
    config: BridgeConfig,
    route: ChannelRoute,
    client: Any,
    thread_ts: str,
    user_id: str,
    text: str,
) -> None:
    if EXECUTOR is None:
        raise RuntimeError("Bridge runtime is not configured")

    response = client.chat_postMessage(
        channel=route.channel_id,
        text=f"Searching the public web for <@{user_id}>...",
        **_reply_target(config, thread_ts),
    )
    progress_ts = response.get("ts")
    EXECUTOR.submit(
        _run_web_search_and_reply,
        config,
        route.channel_id,
        thread_ts,
        progress_ts,
        web_search_query(text),
    )


def _run_web_search_and_reply(
    config: BridgeConfig,
    channel_id: str,
    thread_ts: str,
    progress_ts: str | None,
    query: str,
) -> None:
    result = run_public_web_search(config, query)
    max_chars = int(config.defaults.get("max_slack_message_chars", 3900))
    chunks = chunk_for_slack(result, max_chars)
    client = None
    try:
        from slack_sdk import WebClient

        token = os.getenv("SLACK_BOT_TOKEN")
        if token:
            client = WebClient(token=token)
    except Exception:
        LOGGER.exception("Could not create Slack client for web search reply")

    if client is None:
        LOGGER.error("Web search result could not be posted because Slack client was unavailable")
        return

    if progress_ts:
        try:
            client.chat_update(channel=channel_id, ts=progress_ts, text=chunks[0])
            chunks = chunks[1:]
        except Exception:
            LOGGER.exception("Could not update web search progress message")

    for chunk in chunks:
        client.chat_postMessage(channel=channel_id, text=chunk, **_reply_target(config, thread_ts))


def _retrieve_agent_memory(
    config: BridgeConfig,
    agent_name: str,
    agent: dict[str, Any],
    text: str,
    context: str,
) -> str:
    query = f"{text}\n{context}"
    parts: list[str] = []
    if MEMORY is not None and config.defaults.get("memory_enabled", True):
        top_k = int(agent.get("memory_top_k", config.defaults.get("memory_top_k", 8)))
        semantic = MEMORY.format_for_prompt(agent_name=agent_name, query=query, top_k=top_k)
        if semantic:
            parts.append(semantic)
    if COGNITIVE_MEMORY is not None and _truthy(config.defaults.get("cognitive_memory_enabled", True)):
        episodes = COGNITIVE_MEMORY.retrieve_episodes(
            query=query,
            top_k=max(1, int(config.defaults.get("cognitive_memory_top_k", 3))),
            agent_names=[agent_name, str(config.defaults.get("memory_global_agent", "global"))],
        )
        formatted = _format_cognitive_episodes(episodes)
        if formatted:
            parts.append(formatted)
    return "\n\n".join(parts)


def _shared_runtime_context(config: BridgeConfig, agent_name: str) -> str:
    chat_limit = int(config.defaults.get("shared_chat_recent_events", 12))
    artifact_limit = int(config.defaults.get("artifact_recent_count", 10))
    chat = format_recent_chat(
        path=_shared_chat_path(config),
        agent_name=agent_name,
        current_source="slack",
        limit=chat_limit,
    )
    artifacts = format_recent_artifacts(
        index_path=_artifact_index_path(config),
        agent_name=agent_name,
        limit=artifact_limit,
    )
    return "\n\n".join(part for part in (chat, artifacts) if part.strip())


def _fast_responder_context(agent_name: str, agent: dict[str, Any], surface: str) -> str:
    return "\n".join(
        [
            f"Surface: {surface}",
            f"Agent lane: {agent_name}",
            f"Delegated work model: {agent.get('model') or 'configured default'}",
            f"Delegated work reasoning effort: {agent.get('effort') or 'configured default'}",
            f"Persistent sessions enabled: {bool(agent.get('persistent_agent_sessions', True))}",
            f"Shared runtime sessions enabled: {bool(agent.get('agent_runtime_shared_sessions', False))}",
            "Messages that require tools, files, live systems, customer data, billing, SQL, Salesforce, Zoom admin, or verification are delegated to the persistent high-effort agent.",
        ]
    )


def _append_shared_chat_event(
    config: BridgeConfig,
    agent_name: str,
    request: AgentRequest,
    *,
    role: str,
    text: str,
) -> None:
    try:
        append_chat_event(
            path=_shared_chat_path(config),
            source="slack",
            agent_name=agent_name,
            role=role,
            text=text,
            job_id=request.job_id,
            channel_id=request.channel_id,
            thread_ts=request.thread_ts,
        )
    except Exception:
        LOGGER.exception("Could not append shared chat event for %s", agent_name)


def _register_recent_sandbox_artifacts(
    config: BridgeConfig,
    agent_name: str,
    agent: dict[str, Any],
    request: AgentRequest,
    started_at: float,
) -> None:
    sandbox = _agent_sandbox_dir(config, agent_name, agent)
    if not sandbox.exists():
        return
    registered = 0
    try:
        for path in list(sandbox.rglob("*"))[:500]:
            if not path.is_file():
                continue
            try:
                if path.stat().st_mtime < started_at:
                    continue
            except OSError:
                continue
            artifact_id = register_artifact(
                index_path=_artifact_index_path(config),
                file_path=path,
                agent_name=agent_name,
                source="slack",
                purpose="sandbox-output",
                signature=str(agent.get("signature") or f"AgentChat/{agent_name}"),
                job_id=request.job_id,
            )
            if artifact_id:
                registered += 1
        if registered:
            LOGGER.info("Indexed %s sandbox artifact(s) for %s", registered, agent_name)
    except Exception:
        LOGGER.exception("Could not index sandbox artifacts for %s", agent_name)


def _cleanup_recent_sandbox_junk(
    config: BridgeConfig,
    agent_name: str,
    agent: dict[str, Any],
    request: AgentRequest,
    started_at: float,
) -> None:
    if not _truthy(agent.get("agent_sandbox_cleanup_enabled", config.defaults.get("agent_sandbox_cleanup_enabled", True))):
        return
    sandbox = _agent_sandbox_dir(config, agent_name, agent)
    log_path = _resolve_runtime_path(
        str(agent.get("agent_sandbox_cleanup_log_path") or config.defaults.get("agent_sandbox_cleanup_log_path") or "logs/cleanup/agent_sandbox_cleanup.jsonl")
    )
    removed = cleanup_sandbox_junk(
        sandbox,
        agent_name=agent_name,
        source="slack",
        job_id=str(request.job_id or ""),
        created_after=started_at,
        log_path=log_path,
    )
    if removed:
        LOGGER.info("Cleaned %s disposable sandbox item(s) for %s", removed, agent_name)


def _store_interaction_memory(
    config: BridgeConfig,
    agent_name: str,
    request: AgentRequest,
    result: str,
    *,
    verified: bool = False,
) -> None:
    text = (
        f"Slack channel: {request.channel_id}\n"
        f"User request: {request.text.strip()}\n"
        f"Agent answer: {result.strip()}"
    )
    if verified and MEMORY is not None and config.defaults.get("memory_auto_store", True):
        MEMORY.remember(
            agent_name=agent_name,
            text=redact_secrets(text),
            source=f"job:{request.job_id or 'unknown'}",
            tags=["interaction"],
            importance=1.0,
        )
    if verified and COGNITIVE_MEMORY is not None and _truthy(config.defaults.get("cognitive_memory_enabled", True)):
        try:
            COGNITIVE_MEMORY.append_episode(
                agent_name=agent_name,
                summary=(
                    f"Request: {redact_secrets(request.text).strip()[:700]}\n"
                    f"Outcome: {redact_secrets(result).strip()[:700]}"
                ),
                intent=str(request.task_kind or "slack_interaction"),
                systems=_systems_from_text(text),
                source="slack_completed_job",
                evidence={"job_id": request.job_id, "completion": "agent_run_completed"},
                metadata={"channel_id": request.channel_id, "surface": "slack"},
                verified=True,
                episode_key=f"slack:{request.job_id or request.channel_id + ':' + request.thread_ts}",
            )
        except Exception:
            LOGGER.exception("Could not store cognitive episode for Slack job %s", request.job_id)


def _learning_capability_policy(config: BridgeConfig) -> dict[str, set[str]]:
    policy: dict[str, set[str]] = {}
    for agent_name, agent in config.agents.items():
        names = {
            f"skill:{str(skill).strip().lower()}"
            for skill in (agent.get("skills") or [])
            if str(skill).strip()
        }
        names.update({"memory:read", "artifact:read"})
        policy[str(agent_name)] = names
    return policy


def _learning_observation_outcome(outcome: AgentOutcome) -> ObservationOutcome:
    return {
        AgentOutcomeStatus.COMPLETED: ObservationOutcome.COMPLETED_UNVERIFIED,
        AgentOutcomeStatus.COMPLETED_WITH_ISSUES: ObservationOutcome.COMPLETED_WITH_ISSUES,
        AgentOutcomeStatus.BLOCKED: ObservationOutcome.BLOCKED,
        AgentOutcomeStatus.FAILED: ObservationOutcome.FAILED,
        AgentOutcomeStatus.UNCLASSIFIED: ObservationOutcome.UNCLASSIFIED,
    }[outcome.status]


def _store_learning_observation(
    agent_name: str,
    request: AgentRequest,
    result: str,
    outcome: AgentOutcome,
    *,
    surface: str,
) -> None:
    if LEARNING is None:
        return
    source_job_id = str(request.job_id or f"{request.channel_id}:{request.thread_ts}")
    safe_request = redact_secrets(request.task_text or request.text).strip()[:900]
    safe_result = redact_secrets(result).strip()[:900]
    try:
        LEARNING.append_observation(
            observation_key=f"{surface}:{source_job_id}:{outcome.normalized_status}",
            source_job_id=source_job_id,
            agent_name=agent_name,
            lane=agent_name,
            outcome=_learning_observation_outcome(outcome),
            summary=f"Request: {safe_request}\nOutcome: {safe_result}",
            systems=_systems_from_text(f"{safe_request}\n{safe_result}"),
            evidence={
                "job_id": request.job_id,
                "reported_outcome": outcome.normalized_status,
                "needs_review": outcome.needs_review,
            },
            provenance={
                "surface": surface,
                "task_kind": request.task_kind,
                "channel_id": request.channel_id,
            },
        )
    except Exception:
        LOGGER.exception("Could not store learning observation for Slack job %s", request.job_id)


def _format_memory_results(agent_name: str, memories: list[dict[str, Any]]) -> str:
    public_name = public_agent_name(agent_name)
    if not memories:
        return f"No memories found for `{public_name}`."
    lines = [f"Memory for `{public_name}`:"]
    for item in memories:
        memory_id = str(item.get("id") or "")[:8]
        source = _public_agent_display_text(agent_name, item.get("source") or "memory")
        text = _public_agent_display_text(
            agent_name,
            str(item.get("text") or "").replace("\n", " "),
        )
        if len(text) > 500:
            text = text[:500].rstrip() + "..."
        lines.append(f"- `{memory_id}` [{source}] {text}")
    return "\n".join(lines)


def _upload_directed_files(
    config: BridgeConfig,
    agent_name: str,
    agent: dict[str, Any],
    client: Any,
    request: AgentRequest,
    paths: list[str],
) -> list[str]:
    if not paths:
        return []
    if not config.defaults.get("slack_file_uploads_enabled", True):
        return ["File upload requested, but Slack uploads are disabled in bridge config."]

    allowed_roots = _upload_allowed_roots(config, agent)
    try:
        max_files = max(1, min(int(config.defaults.get("slack_file_max_uploads_per_response", 5)), 5))
    except (TypeError, ValueError):
        max_files = 5
    try:
        max_bytes = int(float(config.defaults.get("slack_file_max_upload_mb", 25)) * 1024 * 1024)
    except (TypeError, ValueError):
        max_bytes = 25 * 1024 * 1024
    notes: list[str] = []
    if len(paths) > max_files:
        notes.append(f"File upload limited to the first {max_files} requested files.")
    seen_paths: set[str] = set()
    for raw_path in paths[:max_files]:
        path = Path(raw_path).expanduser()
        if not path.is_absolute():
            workspace = Path(str(agent.get("workspace_root") or "."))
            path = workspace / path
        try:
            resolved = path.resolve(strict=True)
        except OSError as exc:
            notes.append(f"Upload skipped: `{raw_path}` could not be read ({exc}).")
            continue
        if not resolved.is_file():
            notes.append(f"Upload skipped: `{resolved}` is not a file.")
            continue
        resolved_key = str(resolved).casefold()
        if resolved_key in seen_paths:
            continue
        seen_paths.add(resolved_key)
        if not _path_is_under_any(resolved, allowed_roots):
            notes.append(f"Upload blocked by allow-list: `{resolved}`.")
            continue
        if resolved.suffix.casefold() not in RETURN_FILE_EXTENSIONS:
            notes.append(f"Upload blocked for unsupported file type: `{resolved.name}`.")
            continue
        size_bytes = resolved.stat().st_size
        if not 0 < size_bytes <= max_bytes:
            notes.append(f"Upload blocked by the {max_bytes // (1024 * 1024)} MB file size limit: `{resolved.name}`.")
            continue
        try:
            _validate_downloaded_content(resolved, "")
        except ValueError:
            notes.append(f"Upload blocked because file bytes did not match the extension: `{resolved.name}`.")
            continue
        digest = file_sha256(resolved)
        prior = next(
            (
                item
                for item in artifacts_for_job(
                    index_path=_artifact_index_path(config),
                    job_id=str(request.job_id or ""),
                    agent_name=agent_name,
                    limit=100,
                )
                if str(item.get("purpose") or "") == "slack-upload"
                and str(item.get("sha256") or "") == digest
                and str(item.get("name") or "") == resolved.name
            ),
            None,
        )
        if prior is not None:
            notes.append(f"Uploaded file: `{resolved.name}` (already delivered)")
            continue

        try:
            response = client.files_upload_v2(
                channel=request.channel_id,
                file=str(resolved),
                title=resolved.name,
                thread_ts=request.thread_ts or None,
            )
            file_id = _verified_slack_upload_file_id(client, response)
            artifact_id = register_artifact(
                index_path=_artifact_index_path(config),
                file_path=resolved,
                agent_name=agent_name,
                source="slack",
                purpose="slack-upload",
                signature=str(agent.get("signature") or f"AgentChat/{agent_name}"),
                job_id=request.job_id,
                idempotency_key=(
                    f"slack-upload:{request.job_id or request.thread_ts}:{agent_name}:{digest}:{resolved.name.casefold()}"
                ),
            )
            if not artifact_id:
                raise RuntimeError("The Slack upload succeeded, but its local delivery receipt was not recorded.")
            notes.append(f"Uploaded file: `{resolved.name}` (verified `{file_id}`)")
        except Exception as exc:
            LOGGER.exception("Slack file upload failed for %s", resolved)
            notes.append(f"Upload failed for `{resolved.name}`: {exc}")
    return notes


def _verified_slack_upload_file_id(client: Any, response: Any) -> str:
    payload = _slack_response_payload(response)
    if payload.get("ok") is not True:
        raise RuntimeError("Slack did not accept the file upload.")
    candidates = payload.get("files") if isinstance(payload.get("files"), list) else []
    if isinstance(payload.get("file"), dict):
        candidates = [payload["file"], *candidates]
    file_id = next(
        (
            str(item.get("id") or "").strip()
            for item in candidates
            if isinstance(item, dict) and str(item.get("id") or "").strip()
        ),
        "",
    )
    if not file_id:
        raise RuntimeError("Slack accepted the request without a durable file receipt.")
    if not hasattr(client, "files_info"):
        raise RuntimeError("Slack file readback is unavailable.")
    readback = _slack_response_payload(client.files_info(file=file_id))
    returned_id = str((readback.get("file") or {}).get("id") or "").strip()
    if readback.get("ok") is not True or returned_id != file_id:
        raise RuntimeError("Slack file readback did not confirm the uploaded file.")
    return file_id


# AgentChat/direct_codex 2026-08-06T18:35:00Z: normalize Slack SDK responses before upload readback.
def _slack_response_payload(response: Any) -> dict[str, Any]:
    if response is None:
        return {}
    if isinstance(response, dict):
        return dict(response)
    data = getattr(response, "data", None)
    if isinstance(data, dict):
        return dict(data)
    raise RuntimeError("Slack returned an unreadable response payload.")


def _upload_allowed_roots(config: BridgeConfig, agent: dict[str, Any]) -> list[Path]:
    raw_roots = list(config.defaults.get("slack_file_upload_allowed_roots") or [])
    raw_roots.append(str(agent.get("workspace_root") or "."))
    raw_roots.append(str(config.defaults.get("slack_file_download_dir", "data/slack_files")))
    raw_roots.append(str(config.defaults.get("slack_file_output_dir", "data/generated_files")))

    roots: list[Path] = []
    for raw in raw_roots:
        try:
            root = Path(str(raw)).expanduser()
            if not root.is_absolute():
                root = Path.cwd() / root
            roots.append(root.resolve())
        except OSError:
            continue
    return roots


def _path_is_under_any(path: Path, roots: list[Path]) -> bool:
    for root in roots:
        try:
            path.relative_to(root)
            return True
        except ValueError:
            continue
    return False


def _shared_chat_path(config: BridgeConfig) -> Path:
    return _resolve_runtime_path(str(config.defaults.get("shared_chat_log_path", "data/shared_chat/events.jsonl")))


def _artifact_index_path(config: BridgeConfig) -> Path:
    return _resolve_runtime_path(str(config.defaults.get("artifact_index_path", "data/agent_artifacts/index.jsonl")))


def _slack_conversation_id(channel_id: str, thread_ts: str) -> str:
    return f"{channel_id}:{thread_ts}"


def _agent_sandbox_dir(config: BridgeConfig, agent_name: str, agent: dict[str, Any]) -> Path:
    root = str(agent.get("agent_sandbox_root") or config.defaults.get("agent_sandbox_root") or "data/agent_sandboxes")
    return _resolve_runtime_path(root) / _safe_path_name(agent_name)


def _resolve_runtime_path(raw: str) -> Path:
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    return path


def _command_center_json(
    config: BridgeConfig,
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    base_url = str(
        config.defaults.get("command_center_url")
        or os.getenv("COMMAND_CENTER_URL")
        or "http://127.0.0.1:17866"
    ).rstrip("/")
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json; charset=utf-8"}
    token_path = str(
        config.defaults.get("command_center_session_token_path")
        or os.getenv("COMMAND_CENTER_SESSION_TOKEN_PATH")
        or r"%LOCALAPPDATA%\NovaOpsCommandCenter\session.token"
    )
    bearer = read_command_center_bearer(token_path)
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"
    request = urllib.request.Request(
        f"{base_url}{path}",
        data=data,
        method=method.upper(),
        headers=headers,
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            detail = json.loads(exc.read().decode("utf-8")).get("message")
        except Exception:
            detail = str(exc)
        raise RuntimeError(str(detail or exc)) from exc
    if not isinstance(result, dict) or not result.get("ok", False):
        raise RuntimeError(str((result or {}).get("message") or "Command Center request failed"))
    return result


def _route_slack_result_handoff(
    config: BridgeConfig,
    agent_name: str,
    request: AgentRequest,
    result: str,
    outcome: AgentOutcome,
) -> tuple[str, AgentOutcome]:
    """Consume one operator-authorized handoff marker through Command Center."""

    marker = "TAYLOR_HANDOFF_REQUEST:"
    if marker not in str(result or ""):
        return result, outcome

    try:
        if request.authority_kind != "operator":
            raise RuntimeError("Slack handoffs require verified operator authority.")
        if request.job_id is None or int(request.job_id) <= 0:
            raise RuntimeError("Slack handoffs require a durable source job.")
        payload = {
            "sourceAgent": agent_name,
            "sourceJobId": f"slack:{int(request.job_id)}",
            "sourceBridgeJobId": int(request.job_id),
            "originRequest": str(request.text or "")[:12000],
            "sourceResult": str(result or "")[:12000],
            "authorityKind": request.authority_kind,
        }
        attempt_result = execute_bounded_attempts(
            lambda _attempt, _guidance: json.dumps(
                _command_center_json(
                    config,
                    "POST",
                    "/agent-handoff/slack",
                    payload,
                ),
                sort_keys=True,
            ),
            max_attempts=3,
            retry_delays=bounded_retry_delays(config.defaults, max_attempts=3),
            idempotency_key=f"slack-handoff:{int(request.job_id)}",
        )
        response = json.loads(attempt_result.result)
        if not bool(response.get("accepted")):
            raise RuntimeError(
                str(response.get("message") or "Command Center did not accept the handoff.")
            )
        status = str(response.get("status") or "").strip().lower()
        terminal_duplicate = bool(response.get("duplicate")) and status in {
            "completed",
            "completed_with_issues",
            "blocked",
            "failed",
        }
        if not terminal_duplicate and not bool(response.get("handoffAcknowledged")):
            raise RuntimeError("The receiving lane did not durably acknowledge the handoff.")
        routed_result = str(response.get("result") or "").strip()
        if not routed_result:
            raise RuntimeError("Command Center returned no tracked handoff receipt.")
    except Exception as exc:
        routed_result = (
            "FAILED\nCross-lane handoff was not durably acknowledged after "
            f"bounded retries: {redact_secrets(str(exc))}"
        ).strip()
    return routed_result, _classify_runtime_result(routed_result)


def _is_pending_handoff_result(result: str) -> bool:
    """Identify Command Center's nonterminal receiving-lane acknowledgement."""

    lowered = str(result or "").casefold()
    return (
        first_nonempty_line(result).strip().upper() == "COMPLETED_WITH_ISSUES"
        and "business work is not complete until the target job finishes" in lowered
    )


def _format_cognitive_episodes(episodes: list[dict[str, Any]]) -> str:
    if not episodes:
        return ""
    lines = ["Relevant historical episodes (completed transcripts, not proof that external facts are still current):"]
    for episode in episodes[:3]:
        summary = " ".join(str(episode.get("summary") or "").split())
        if len(summary) > 650:
            summary = summary[:647].rstrip() + "..."
        lines.append(f"- {summary}")
    return "\n".join(lines)


def _systems_from_text(text: str) -> list[str]:
    lowered = str(text or "").lower()
    cues = {
        "salesforce": ("salesforce", "soql", "ticket"),
        "maxio": ("maxio", "chargify", "subscription", "component allocation"),
        "nova": ("nova", "backoffice", "pos_"),
        "gmail": ("gmail", "email", "mailbox"),
        "zoom": ("zoom", "contact center", "team chat"),
        "slack": ("slack",),
        "github": ("github", "pull request", "repository"),
    }
    return sorted(name for name, terms in cues.items() if any(term in lowered for term in terms))


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _safe_path_name(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in value).strip("._") or "agent"


def _reply_target(config: BridgeConfig, thread_ts: str) -> dict[str, str]:
    if config.defaults.get("reply_in_thread", False) and thread_ts:
        return {"thread_ts": thread_ts}
    return {}


def _progress_text(agent_name: str, user_id: str, job_id: int, tick: int) -> str:
    dots = "." * ((tick % 3) + 1)
    return f"`{public_agent_name(agent_name)}` is writing for <@{user_id}> `{job_id}`{dots}"


def public_agent_name(agent_name: str) -> str:
    """Return the public label while preserving internal runtime identifiers."""

    normalized = str(agent_name or "").strip()
    if normalized.casefold() == "claude_agent":
        return "Thor"
    return normalized or "agent"


def _public_agent_display_text(agent_name: str, text: Any) -> str:
    """Sanitize compatibility names only in user-visible agent output."""

    rendered = str(text or "")
    if str(agent_name or "").strip().casefold() != "claude_agent":
        return rendered
    return re.sub(
        r"(?<![\w])(?:Claude Agent|claude_agent)(?![\w])",
        "Thor",
        rendered,
        flags=re.IGNORECASE,
    )


def _progress_heartbeat(
    config: BridgeConfig,
    client: Any,
    request: AgentRequest,
    agent_name: str,
    progress_ts: str | None,
    stop_progress: Event,
) -> None:
    interval = float(config.defaults.get("progress_update_seconds", 15))
    tick = 1
    while not stop_progress.wait(interval):
        if STATE is not None and request.job_id is not None:
            if not STATE.heartbeat_job(request.job_id, runtime_instance_id=RUNTIME_INSTANCE_ID):
                return
        if not progress_ts:
            continue
        try:
            client.chat_update(
                channel=request.channel_id,
                ts=progress_ts,
                text=_progress_text(agent_name, request.user_id, request.job_id or 0, tick),
            )
            tick += 1
        except Exception:
            LOGGER.exception("Could not update progress heartbeat for job %s", request.job_id)
            return


def _required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


if __name__ == "__main__":
    main()
# AgentChat/security 2026-07-08: allowlist enforcement added.
