from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Event, Lock, Thread
from typing import Any, Callable, Mapping


ProbeExecutor = Callable[[list[str], float], int]

CODEX_PROVIDERS = frozenset({"codex_cli", "codex_cli_direct"})
RELAY_PROVIDERS = frozenset({"chatgpt_work_relay", "chatgpt_relay"})
PUBLIC_PROVIDERS = frozenset({*CODEX_PROVIDERS, *RELAY_PROVIDERS, "disabled"})
PUBLIC_READINESS_STATUSES = frozenset({"not_checked", "not_authenticated", "probe_failed", "probe_in_progress", "probe_timeout", "probe_unavailable", "ready", "unknown_agent", "unsupported_provider", "disabled"})
_PUBLIC_AGENT_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,79}$", re.IGNORECASE)


def _truthy(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _relay_enabled() -> bool:
    return _truthy(os.getenv("REASONING_RELAY_ENABLED"))


def _relay_paths_ready() -> bool:
    repository = str(os.getenv("REASONING_RELAY_REPOSITORY") or "dariusmakesstuff/codex-slack-bridge").strip()
    branch = str(os.getenv("REASONING_RELAY_BRANCH") or "reasoning-relay-bus").strip()
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}", repository):
        return False
    if not re.fullmatch(r"[A-Za-z0-9._/-]{1,180}", branch) or ".." in branch:
        return False
    for name in ("GITHUB_APP_ID_PATH", "GITHUB_APP_INSTALLATION_ID_PATH", "GITHUB_APP_PRIVATE_KEY_PATH"):
        raw = os.path.expandvars(os.path.expanduser(str(os.getenv(name) or "").strip()))
        if not raw or not Path(raw).is_file():
            return False
    allowed = {item.strip().casefold() for item in str(os.getenv("GITHUB_ALLOWED_REPOSITORIES") or "").split(",") if item.strip()}
    return not allowed or repository.casefold() in allowed


def _effective_provider(agent_name: str, agent: Mapping[str, Any]) -> str:
    configured = str(agent.get("provider") or "").strip()
    if agent_name == "raw_codex" and configured in {"disabled", *CODEX_PROVIDERS, *RELAY_PROVIDERS}:
        return "disabled"
    if configured in RELAY_PROVIDERS:
        return "chatgpt_relay"
    return configured


def _utc_from_epoch(value: float) -> str:
    return datetime.fromtimestamp(value, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def _default_probe_executor(command: list[str], timeout_seconds: float) -> int:
    completed = subprocess.run(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=timeout_seconds, check=False)
    return int(completed.returncode)


def _public_agent_name(value: Any) -> str:
    name = str(value or "").strip()
    return name if _PUBLIC_AGENT_NAME_RE.fullmatch(name) else ""


def _public_provider(value: Any) -> str:
    provider = str(value or "").strip()
    if not provider:
        return ""
    return provider if provider in PUBLIC_PROVIDERS else "unsupported"


def _public_checked_at(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return None
        return _utc_from_epoch(parsed.timestamp())
    except (OSError, OverflowError, ValueError):
        return None


def sanitize_readiness_status(item: Mapping[str, Any] | None, *, agent_name: str = "") -> dict[str, Any]:
    raw = item if isinstance(item, Mapping) else {}
    name = _public_agent_name(agent_name) or _public_agent_name(raw.get("agentName"))
    status = str(raw.get("status") or "probe_failed").strip().lower()
    invalid_status = status not in PUBLIC_READINESS_STATUSES
    if invalid_status:
        status = "probe_failed"
    checked_at = _public_checked_at(raw.get("checkedAtUtc"))
    try:
        age_seconds = max(0, min(int(raw.get("ageSeconds")), 2_147_483_647))
    except (TypeError, ValueError):
        age_seconds = None
    if checked_at is None:
        age_seconds = None
    stale = bool(raw.get("stale")) or checked_at is None
    ready = bool(raw.get("ready")) and status == "ready"
    if invalid_status or status in {"probe_in_progress", "unknown_agent", "disabled"}:
        ready = False
        stale = True if status in {"probe_in_progress", "unknown_agent"} else stale
    return {"agentName": name, "provider": _public_provider(raw.get("provider")), "ready": ready, "status": status, "checkedAtUtc": checked_at, "ageSeconds": age_seconds, "stale": stale}


def sanitize_readiness_snapshot(snapshot: Mapping[str, Mapping[str, Any]] | None) -> dict[str, dict[str, Any]]:
    if not isinstance(snapshot, Mapping):
        return {}
    sanitized: dict[str, dict[str, Any]] = {}
    for raw_name, raw_item in snapshot.items():
        name = _public_agent_name(raw_name)
        if name:
            sanitized[name] = sanitize_readiness_status(raw_item, agent_name=name)
    return sanitized


class AgentProviderReadiness:
    """Cache secret-free provider readiness without touching Codex for relay lanes."""

    def __init__(self, agents: Mapping[str, Mapping[str, Any]], *, success_ttl_seconds: float = 300, failure_ttl_seconds: float = 30, probe_timeout_seconds: float = 10, executor: ProbeExecutor | None = None, clock: Callable[[], float] = time.time, refresh_ahead_fraction: float = 0.25, periodic_max_sleep_seconds: float = 30, max_parallel_probes: int = 4) -> None:
        self._agents = {str(name): dict(agent) for name, agent in agents.items()}
        self._success_ttl_seconds = max(0.1, float(success_ttl_seconds))
        self._failure_ttl_seconds = max(0.1, float(failure_ttl_seconds))
        self._probe_timeout_seconds = max(0.1, float(probe_timeout_seconds))
        self._refresh_ahead_fraction = min(0.9, max(0.05, float(refresh_ahead_fraction)))
        self._periodic_max_sleep_seconds = max(0.05, float(periodic_max_sleep_seconds))
        self._max_parallel_probes = max(1, min(int(max_parallel_probes), 16))
        self._executor = executor or _default_probe_executor
        self._clock = clock
        self._lock = Lock()
        self._cache: dict[str, dict[str, Any]] = {}
        self._probe_events: dict[str, Event] = {}
        self._probe_waiters: dict[str, int] = {}
        self._refresh_thread: Thread | None = None
        self._periodic_thread: Thread | None = None
        self._periodic_stop = Event()

    def snapshot(self) -> dict[str, dict[str, Any]]:
        return sanitize_readiness_snapshot({name: self.status(name, refresh_if_stale=False) for name in sorted(self._agents)})

    def status(self, agent_name: str, *, refresh_if_stale: bool = True) -> dict[str, Any]:
        name = str(agent_name or "").strip()
        if name not in self._agents:
            return sanitize_readiness_status({"agentName": name, "provider": "", "ready": False, "status": "unknown_agent", "checkedAtUtc": None, "ageSeconds": None, "stale": True}, agent_name=name)
        cached = self._cached_status(name)
        if refresh_if_stale and (cached is None or cached["stale"]):
            return self._probe(name)
        if cached is not None:
            if refresh_if_stale and self._is_refresh_due(name):
                self.refresh_due_async()
            return cached
        return self._unprobed_status(name)

    def ensure_ready(self, agent_name: str, *, force_refresh: bool = False) -> dict[str, Any]:
        if force_refresh and str(agent_name or "").strip() in self._agents:
            return self._probe(str(agent_name).strip())
        return self.status(agent_name, refresh_if_stale=True)

    def ensure_ready_for(
        self, agent_name: str, requested_provider: str = "", *, force_refresh: bool = False
    ) -> dict[str, Any]:
        """Probe the backend selected for this job, not a global relay flag.

        Relay readiness checks transport configuration, not whether an
        independent ChatGPT consumer is currently waking.
        """
        name = str(agent_name or "").strip()
        requested = str(requested_provider or "").strip().lower()
        if not requested:
            return self.ensure_ready(name, force_refresh=force_refresh)
        agent = self._agents.get(name)
        if not agent:
            return self.status(name, refresh_if_stale=False)
        configured = _effective_provider(name, agent)
        allowed = (requested == "codex_cli" and configured in CODEX_PROVIDERS) or (
            requested == "chatgpt_relay"
            and configured in CODEX_PROVIDERS | RELAY_PROVIDERS
        )
        if not allowed:
            result = {
                "agentName": name, "provider": requested, "ready": False,
                "status": "unsupported_provider", "checkedAtUtc": None,
                "ageSeconds": None, "stale": True,
            }
            return sanitize_readiness_status(result, agent_name=name)
        if requested == "codex_cli":
            return self.ensure_ready(name, force_refresh=force_refresh)
        ready = _relay_enabled() and _relay_paths_ready()
        return sanitize_readiness_status({
            "agentName": name, "provider": "chatgpt_relay", "ready": ready,
            "status": "ready" if ready else "probe_unavailable",
            "checkedAtUtc": _utc_from_epoch(self._clock()),
            "ageSeconds": 0, "stale": False,
        }, agent_name=name)

    def refresh_all(self) -> dict[str, dict[str, Any]]:
        return self._refresh_agents(sorted(self._agents))

    def refresh_due(self) -> dict[str, dict[str, Any]]:
        return self._refresh_agents([name for name in sorted(self._agents) if self._is_refresh_due(name)])

    def _refresh_agents(self, agent_names: list[str]) -> dict[str, dict[str, Any]]:
        if not agent_names:
            return {}
        if len(agent_names) == 1:
            name = agent_names[0]
            return {name: self._probe(name)}
        with ThreadPoolExecutor(max_workers=min(self._max_parallel_probes, len(agent_names)), thread_name_prefix="agent-provider-probe") as executor:
            futures = {name: executor.submit(self._probe, name) for name in agent_names}
            return {name: futures[name].result() for name in agent_names}

    def refresh_all_async(self) -> bool:
        return self._start_refresh_thread(self.refresh_all, "agent-provider-readiness")

    def refresh_due_async(self) -> bool:
        return self._start_refresh_thread(self.refresh_due, "agent-provider-readiness-due")

    def start_periodic_refresh(self) -> bool:
        with self._lock:
            if self._periodic_thread is not None and self._periodic_thread.is_alive():
                return False
            self._periodic_stop.clear()
            thread = Thread(target=self._periodic_refresh_loop, name="agent-provider-readiness-periodic", daemon=True)
            self._periodic_thread = thread
            thread.start()
        return True

    def stop_periodic_refresh(self, *, wait: bool = False) -> None:
        self._periodic_stop.set()
        with self._lock:
            thread = self._periodic_thread
        if wait and thread is not None and thread.is_alive():
            thread.join(timeout=self._probe_timeout_seconds + 1.0)

    def _start_refresh_thread(self, target: Callable[[], Any], name: str) -> bool:
        with self._lock:
            if self._refresh_thread is not None and self._refresh_thread.is_alive():
                return False
            thread = Thread(target=target, name=name, daemon=True)
            self._refresh_thread = thread
            thread.start()
        return True

    def _periodic_refresh_loop(self) -> None:
        self.refresh_all()
        while not self._periodic_stop.is_set():
            if self._periodic_stop.wait(self._next_refresh_delay()):
                return
            self.refresh_due()

    def _next_refresh_delay(self) -> float:
        now = self._clock()
        with self._lock:
            items = {name: dict(self._cache[name]) for name in self._agents if name in self._cache}
        if len(items) != len(self._agents):
            return 0.05
        delays = []
        for item in items.values():
            ttl = self._ttl_for_item(item)
            refresh_at = float(item["checkedAtEpoch"]) + ttl * (1.0 - self._refresh_ahead_fraction)
            delays.append(max(0.05, refresh_at - now))
        return min(min(delays), self._periodic_max_sleep_seconds) if delays else self._periodic_max_sleep_seconds

    def _is_refresh_due(self, agent_name: str) -> bool:
        with self._lock:
            raw = self._cache.get(agent_name)
            item = dict(raw) if raw is not None else None
        if item is None:
            return True
        age = max(0.0, self._clock() - float(item["checkedAtEpoch"]))
        return age >= self._ttl_for_item(item) * (1.0 - self._refresh_ahead_fraction)

    def _ttl_for_item(self, item: Mapping[str, Any]) -> float:
        return self._success_ttl_seconds if bool(item.get("ready")) else self._failure_ttl_seconds

    def _cached_status(self, agent_name: str) -> dict[str, Any] | None:
        with self._lock:
            raw = self._cache.get(agent_name)
            item = dict(raw) if raw is not None else None
        if item is None:
            return None
        age = max(0.0, self._clock() - float(item["checkedAtEpoch"]))
        ttl = self._ttl_for_item(item)
        return self._public_status(item, age_seconds=age, stale=age >= ttl)

    def _unprobed_status(self, agent_name: str) -> dict[str, Any]:
        agent = self._agents[agent_name]
        return sanitize_readiness_status({"agentName": agent_name, "provider": _effective_provider(agent_name, agent), "ready": False, "status": "not_checked", "checkedAtUtc": None, "ageSeconds": None, "stale": True}, agent_name=agent_name)

    def _probe(self, agent_name: str) -> dict[str, Any]:
        with self._lock:
            event = self._probe_events.get(agent_name)
            owns_probe = event is None
            if owns_probe:
                event = Event()
                self._probe_events[agent_name] = event
            else:
                self._probe_waiters[agent_name] = self._probe_waiters.get(agent_name, 0) + 1
        if not owns_probe:
            assert event is not None
            try:
                if not event.wait(timeout=self._probe_timeout_seconds + 0.5):
                    return self._transient_status(agent_name, "probe_in_progress")
                cached = self._cached_status(agent_name)
                return cached or self._transient_status(agent_name, "probe_failed")
            finally:
                with self._lock:
                    remaining = self._probe_waiters.get(agent_name, 1) - 1
                    if remaining > 0:
                        self._probe_waiters[agent_name] = remaining
                    else:
                        self._probe_waiters.pop(agent_name, None)

        agent = self._agents[agent_name]
        configured_provider = str(agent.get("provider") or "").strip()
        provider = _effective_provider(agent_name, agent)
        ready = False
        status = "unsupported_provider"
        try:
            if provider == "disabled":
                status = "disabled"
            elif configured_provider in RELAY_PROVIDERS:
                ready = _relay_paths_ready()
                status = "ready" if ready else "probe_unavailable"
            elif configured_provider in CODEX_PROVIDERS:
                command = self._codex_status_command(agent)
                returncode = self._executor(command, self._probe_timeout_seconds)
                ready = returncode == 0
                status = "ready" if ready else "not_authenticated"
        except subprocess.TimeoutExpired:
            status = "probe_timeout"
        except (FileNotFoundError, PermissionError):
            status = "probe_unavailable"
        except Exception:
            status = "probe_failed"

        item = {"agentName": agent_name, "provider": provider, "ready": ready, "status": status, "checkedAtEpoch": self._clock()}
        with self._lock:
            self._cache[agent_name] = item
            completed = self._probe_events.pop(agent_name, None)
            if completed is not None:
                completed.set()
        return self._public_status(item, age_seconds=0.0, stale=False)

    def _transient_status(self, agent_name: str, status: str) -> dict[str, Any]:
        cached = self._cached_status(agent_name)
        if cached is not None:
            return sanitize_readiness_status({**cached, "ready": False, "status": status, "stale": True}, agent_name=agent_name)
        agent = self._agents[agent_name]
        return sanitize_readiness_status({"agentName": agent_name, "provider": _effective_provider(agent_name, agent), "ready": False, "status": status, "checkedAtUtc": None, "ageSeconds": None, "stale": True}, agent_name=agent_name)

    @staticmethod
    def _codex_status_command(agent: Mapping[str, Any]) -> list[str]:
        executable = os.path.expandvars(str(agent.get("codex_executable") or "codex").strip())
        if not executable:
            raise ValueError("codex executable is empty")
        raw_prefix = agent.get("codex_command_prefix") or []
        if not isinstance(raw_prefix, list):
            raise TypeError("codex command prefix must be a list")
        prefix = [os.path.expandvars(str(part).strip()) for part in raw_prefix if str(part).strip()]
        return [*prefix, executable, "login", "status"]

    @staticmethod
    def _public_status(item: Mapping[str, Any], *, age_seconds: float, stale: bool) -> dict[str, Any]:
        checked_at = float(item["checkedAtEpoch"])
        return sanitize_readiness_status({"agentName": item.get("agentName"), "provider": item.get("provider"), "ready": item.get("ready"), "status": item.get("status"), "checkedAtUtc": _utc_from_epoch(checked_at), "ageSeconds": int(age_seconds), "stale": bool(stale)})
