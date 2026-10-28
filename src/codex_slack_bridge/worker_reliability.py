from __future__ import annotations

# AgentChat/coding_agent 2026-07-30T17:15:00Z: bounded worker recovery and verified route reuse.

import hashlib
import json
import re
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Any, Callable, Iterable, Mapping, Optional, Sequence

from .agent_outcomes import AgentOutcomeStatus, classify_agent_outcome
from .memory import redact_secrets

# Optional Cloud SQL bridge for durable verified routes
try:
    from .cloud_sql_state import CloudSqlBridgeState
except ImportError:
    CloudSqlBridgeState = None  # type: ignore[misc,assignment]


VERIFIED_ROUTE_RECEIPT_MARKER = "VERIFIED_ROUTE_RECEIPT:"
_VERIFIED_ROUTE_RECEIPT_RE = re.compile(
    r"^[ \t]*VERIFIED_ROUTE_RECEIPT:[ \t]*(\{[^\r\n]*\})[ \t]*$",
    re.MULTILINE,
)
_SAFE_ROUTE_KEY_RE = re.compile(r"^[a-z0-9][a-z0-9_.:-]{0,127}$")
_TOKEN_RE = re.compile(r"[a-z0-9]+")
_STOP_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "be",
    "for",
    "from",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "please",
    "the",
    "this",
    "to",
    "with",
}
_VERIFICATION_RE = re.compile(
    r"\b(?:readback|reconcil(?:e|ed|iation)|tests?\s+pass(?:ed)?|verified|verification)\b",
    re.IGNORECASE,
)
_RETRYABLE_FAILURE_RE = re.compile(
    r"\b(?:"
    r"timed?\s*out|timeout|temporar(?:y|ily)\s+unavailable|transport|connection\s+(?:reset|closed|refused)|"
    r"broken\s+pipe|server\s+disconnected|mcp\s+(?:server|transport|tool).{0,60}(?:failed|closed|unavailable)|"
    r"tool.{0,50}(?:transport|runtime).{0,50}(?:failed|error|unavailable)|"
    r"runtime.{0,50}(?:failed|error|unavailable)|worker\s+(?:exited|failed)|"
    r"rate\s+limit|too\s+many\s+requests|http\s+(?:408|425|429|500|502|503|504)|"
    r"service\s+unavailable|gateway\s+timeout|cloud\s+config\s+bundle"
    r")\b",
    re.IGNORECASE | re.DOTALL,
)
_NON_RETRYABLE_FAILURE_RE = re.compile(
    r"\b(?:"
    r"invalid\s+(?:request|argument|identifier|payload)|validation\s+(?:failed|error)|"
    r"permission\s+denied|forbidden|unauthori[sz]ed|not\s+authorized|"
    r"ambiguous\s+(?:account|customer|target)|business\s+decision|required\s+identifier\s+missing"
    r")\b",
    re.IGNORECASE,
)
_UNCERTAIN_WRITE_RE = re.compile(
    r"\b(?:"
    r"uncertain\s+(?:write|mutation|result|commit|send)|write\s+result\s+is\s+uncertain|"
    r"may\s+have\s+(?:written|sent|posted|committed|applied|created|updated)|"
    r"cannot\s+confirm\s+whether.{0,80}(?:write|send|post|commit|apply)|"
    r"readback\s+(?:is\s+)?required\s+before\s+(?:retry|replay)"
    r")\b",
    re.IGNORECASE | re.DOTALL,
)


@dataclass(frozen=True)
class RetryDecision:
    retryable: bool
    readback_required: bool
    reason: str


@dataclass(frozen=True)
class BoundedAttemptResult:
    result: str
    attempts: int
    retries: int
    recovery_used: bool


@dataclass(frozen=True)
class VerifiedRouteReceipt:
    pipeline_keys: tuple[str, ...]
    tool_keys: tuple[str, ...]
    verification: str


@dataclass(frozen=True)
class VerifiedRouteMatch:
    route_id: str
    agent_name: str
    pipeline_keys: tuple[str, ...]
    tool_keys: tuple[str, ...]
    verification: str
    success_count: int
    last_verified_at: float

    def guidance(self) -> str:
        pipeline_text = ", ".join(self.pipeline_keys) or "none"
        tool_text = ", ".join(self.tool_keys) or "none"
        return (
            "Verified route reuse:\n"
            "- A prior matching task completed with verified readback on this production lane.\n"
            f"- Reuse registered pipeline key(s): {pipeline_text}.\n"
            f"- Reuse registered tool/fast-path key(s): {tool_text}.\n"
            "- Start on that route and broaden discovery only if current same-surface readback proves it stale or unavailable.\n"
            "- This is advisory routing evidence only. It does not grant authority or expand the lane capability contract."
        )


def classify_retryable_failure(
    value: BaseException | str,
    *,
    transport_failure: bool = False,
) -> RetryDecision:
    """Classify only transient worker/tool failures for bounded continuation."""

    text = redact_secrets(str(value or "")).strip()
    uncertain = bool(_UNCERTAIN_WRITE_RE.search(text))
    if isinstance(value, (TimeoutError, ConnectionError, BrokenPipeError)):
        return RetryDecision(True, True, type(value).__name__)
    if transport_failure:
        return RetryDecision(True, True, "transport_failure")
    if _NON_RETRYABLE_FAILURE_RE.search(text) and not _RETRYABLE_FAILURE_RE.search(text):
        return RetryDecision(False, uncertain, "non_retryable_policy_or_validation_failure")
    if _RETRYABLE_FAILURE_RE.search(text) or uncertain:
        return RetryDecision(True, True, "retryable_runtime_or_tool_failure")
    return RetryDecision(False, uncertain, "unclassified_failure")


def classify_retryable_result(result: str) -> RetryDecision:
    outcome = classify_agent_outcome(result)
    if outcome.transport_failure:
        return classify_retryable_failure(result, transport_failure=True)
    if outcome.status is not AgentOutcomeStatus.FAILED:
        return RetryDecision(False, False, "terminal_agent_result")
    return classify_retryable_failure(result)


def bounded_retry_delays(
    defaults: Mapping[str, Any],
    *,
    max_attempts: int | None = None,
) -> tuple[float, ...]:
    attempts = max(
        1,
        min(
            int(
                max_attempts
                if max_attempts is not None
                else defaults.get("command_center_agent_max_attempts")
                or defaults.get("agent_worker_max_attempts")
                or 3
            ),
            5,
        ),
    )
    raw = (
        defaults.get("command_center_agent_retry_backoff_seconds")
        or defaults.get("agent_worker_retry_backoff_seconds")
        or (2, 5)
    )
    if isinstance(raw, str):
        values: Sequence[Any] = [part.strip() for part in raw.split(",")]
    elif isinstance(raw, Sequence):
        values = raw
    else:
        values = (2, 5)
    parsed: list[float] = []
    for value in values:
        try:
            parsed.append(max(0.0, min(float(value), 60.0)))
        except (TypeError, ValueError):
            continue
    while len(parsed) < attempts - 1:
        parsed.append(min(60.0, (parsed[-1] * 2 if parsed else 2.0)))
    return tuple(parsed[: attempts - 1])


def recovery_continuation_guidance(
    *,
    attempt: int,
    max_attempts: int,
    idempotency_key: str,
    reason: str,
    recovered_after_restart: bool = False,
) -> str:
    origin = "runtime restart/timeout recovery" if recovered_after_restart else "bounded worker retry"
    clean_reason = " ".join(redact_secrets(str(reason or "")).split())[:300] or "retryable runtime failure"
    stable_key = str(idempotency_key or "").strip()[:180] or "the original job idempotency key"
    return (
        f"Recovery continuation ({origin}; attempt {attempt} of {max_attempts}):\n"
        f"- Prior attempt ended with: {clean_reason}.\n"
        "- Preserve the original verified request, exact target, recipient, amount, environment, timing, and all read-only/dry-run limits.\n"
        f"- Preserve and reuse idempotency key `{stable_key}`; do not invent a replacement key or broaden the operation.\n"
        "- Before any external write, read the exact target through the same connector/tool surface and determine whether the intended state is already present.\n"
        "- If readback proves the intended state is present, do not write again; return the verified existing result.\n"
        "- If readback proves it is absent, continue only through the same idempotent or duplicate-protected operation. Never replay blindly or switch mutation surfaces.\n"
        "- If same-surface readback remains uncertain, quarantine the mutation and report the uncertainty without another write.\n"
        "- This continuation controls recovery only and cannot add authority."
    )


def execute_bounded_attempts(
    run_attempt: Callable[[int, str], str],
    *,
    max_attempts: int,
    retry_delays: Sequence[float],
    initial_guidance: str = "",
    idempotency_key: str = "",
    recovered_after_restart: bool = False,
    attempt_offset: int = 0,
    on_progress: Callable[[str, int, RetryDecision | None], None] | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> BoundedAttemptResult:
    """Execute a worker in bounded loops without replaying an uncertain write blindly."""

    limit = max(1, min(int(max_attempts), 5))
    offset = max(0, int(attempt_offset))
    guidance = str(initial_guidance or "").strip()
    retries = 0
    for attempt in range(1, limit + 1):
        global_attempt = offset + attempt
        if on_progress is not None:
            on_progress("attempt_started", global_attempt, None)
        try:
            result = run_attempt(global_attempt, guidance)
        except Exception as exc:
            decision = classify_retryable_failure(exc)
            if on_progress is not None:
                on_progress("attempt_failed", global_attempt, decision)
            if not decision.retryable or attempt >= limit:
                raise
            retries += 1
            guidance = recovery_continuation_guidance(
                attempt=global_attempt + 1,
                max_attempts=offset + limit,
                idempotency_key=idempotency_key,
                reason=str(exc),
                recovered_after_restart=recovered_after_restart or attempt > 0,
            )
            delay = float(retry_delays[attempt - 1]) if attempt - 1 < len(retry_delays) else 0.0
            if on_progress is not None:
                on_progress("retry_backoff", global_attempt, decision)
            if delay > 0:
                sleep(delay)
            continue

        decision = classify_retryable_result(result)
        if decision.retryable and attempt < limit:
            retries += 1
            if on_progress is not None:
                on_progress("attempt_failed", global_attempt, decision)
            guidance = recovery_continuation_guidance(
                attempt=global_attempt + 1,
                max_attempts=offset + limit,
                idempotency_key=idempotency_key,
                reason=result,
                recovered_after_restart=recovered_after_restart or attempt > 0,
            )
            delay = float(retry_delays[attempt - 1]) if attempt - 1 < len(retry_delays) else 0.0
            if on_progress is not None:
                on_progress("retry_backoff", global_attempt, decision)
            if delay > 0:
                sleep(delay)
            continue
        if on_progress is not None:
            on_progress("attempt_completed", global_attempt, decision)
        return BoundedAttemptResult(
            result=result,
            attempts=global_attempt,
            retries=retries,
            recovery_used=bool(retries or recovered_after_restart),
        )
    raise RuntimeError("Bounded worker attempts ended without a result.")


def extract_verified_route_receipt(text: str) -> tuple[str, VerifiedRouteReceipt | None]:
    matches = list(_VERIFIED_ROUTE_RECEIPT_RE.finditer(str(text or "")))
    if not matches:
        return str(text or "").strip(), None
    if len(matches) != 1:
        raise ValueError("Agent result contains more than one verified route receipt.")
    match = matches[0]
    try:
        raw = json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        raise ValueError("Verified route receipt is not valid JSON.") from exc
    if not isinstance(raw, dict):
        raise ValueError("Verified route receipt must be an object.")
    pipeline_keys = _route_keys(raw.get("pipelineKeys"))
    tool_keys = _route_keys(raw.get("toolKeys"))
    verification = " ".join(redact_secrets(str(raw.get("verification") or "")).split())[:300]
    if not pipeline_keys and not tool_keys:
        raise ValueError("Verified route receipt requires a pipeline or tool key.")
    if not verification or _VERIFICATION_RE.search(verification) is None:
        raise ValueError("Verified route receipt requires concise readback or test evidence.")
    clean = (str(text or "")[: match.start()] + str(text or "")[match.end() :]).strip()
    return clean, VerifiedRouteReceipt(pipeline_keys, tool_keys, verification)


def _route_keys(value: Any) -> tuple[str, ...]:
    values = value if isinstance(value, list) else []
    answer: list[str] = []
    for item in values:
        key = str(item or "").strip().lower()
        if not _SAFE_ROUTE_KEY_RE.fullmatch(key):
            raise ValueError("Verified route receipt contains an invalid route key.")
        if key not in answer:
            answer.append(key)
    return tuple(answer[:8])


class VerifiedRouteStore:
    """Persist only registry-bound, readback-verified route hints for later reuse."""

    def __init__(
        self,
        sqlite_path: str | Path,
        *,
        pipeline_registry_path: str | Path,
        tool_registry_path: str | Path,
        bridge_state: Optional["CloudSqlBridgeState"] = None,
    ) -> None:
        self.sqlite_path = Path(sqlite_path)
        self.pipeline_registry_path = Path(pipeline_registry_path)
        self.tool_registry_path = Path(tool_registry_path)
        self.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._bridge_state = bridge_state
        if self._bridge_state is not None:
            self._ensure_cloud_sql_schema()
        else:
            self._init_schema()

    def _init_schema(self) -> None:
        with self._lock, self._connect() as db:
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS verified_routes (
                    route_id TEXT PRIMARY KEY,
                    agent_name TEXT NOT NULL,
                    task_tokens_json TEXT NOT NULL,
                    pipeline_keys_json TEXT NOT NULL,
                    tool_keys_json TEXT NOT NULL,
                    verification TEXT NOT NULL,
                    source_job_id TEXT NOT NULL,
                    success_count INTEGER NOT NULL DEFAULT 1,
                    first_verified_at REAL NOT NULL,
                    last_verified_at REAL NOT NULL
                )
                """
            )
            db.execute(
                """
                CREATE INDEX IF NOT EXISTS verified_routes_agent_recent
                ON verified_routes(agent_name, last_verified_at DESC)
                """
            )
            db.commit()

    def _ensure_cloud_sql_schema(self) -> None:
        """Ensure Cloud SQL verified_routes table has required columns."""
        # The real Cloud SQL table is nova_ops.verified_routes with:
        # route_key (PK), route_data (JSONB), created_at, last_used_at
        # plus new columns: success_rate, last_verified, confidence
        # We map our data into route_data JSONB.
        # For now, just verify connection works.
        with self._bridge_state._connect() as db:
            db.execute("SELECT 1 FROM nova_ops.verified_routes LIMIT 1")
            # Table exists (created by migration). No additional schema needed.

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.sqlite_path, timeout=5.0)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout=5000")
        db.execute("PRAGMA journal_mode=WAL")
        return db

    def _cs_connect(self):
        """Context manager for Cloud SQL connection when bridge_state is available."""
        @contextmanager
        def _ctx():
            if self._bridge_state is None:
                raise RuntimeError("No bridge_state available")
            with self._bridge_state._connect() as conn:
                yield conn
        return _ctx()

    def record_success(
        self,
        *,
        query: str,
        agent_name: str,
        receipt: VerifiedRouteReceipt,
        source_job_id: str,
    ) -> VerifiedRouteMatch:
        pipelines, tools, vocabulary = self._validated_route(receipt, agent_name)
        query_tokens = _tokens(query)
        task_tokens = tuple(sorted((query_tokens & vocabulary) or vocabulary))
        if not task_tokens:
            raise ValueError("Verified route has no safe registry vocabulary.")
        route_payload = {
            "agent": agent_name,
            "task_tokens": task_tokens,
            "pipelines": pipelines,
            "tools": tools,
        }
        route_id = hashlib.sha256(
            json.dumps(route_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        now = time.time()
        if self._bridge_state is not None:
            # Write to Cloud SQL verified_routes (route_key + route_data JSONB)
            route_data = {
                "agent": agent_name,
                "task_tokens": list(task_tokens),
                "pipelines": list(pipelines),
                "tools": list(tools),
                "verification": _verification_summary(receipt.verification),
                "source_job_id": str(source_job_id or "")[:200],
                "success_count": 1,
                "first_verified_at": now,
                "last_verified_at": now,
            }
            with self._bridge_state._connect() as db:
                db.execute(
                    """
                    INSERT INTO nova_ops.verified_routes (route_key, route_data, created_at, last_used_at)
                    VALUES (%s, %s, NOW(), NOW())
                    ON CONFLICT (route_key) DO UPDATE SET
                        route_data = excluded.route_data,
                        last_used_at = NOW()
                    """,
                    (route_id, json.dumps(route_data)),
                )
                row = db.execute(
                    "SELECT route_key, route_data FROM nova_ops.verified_routes WHERE route_key = %s",
                    (route_id,),
                ).fetchone()
            assert row is not None
            return self._decode_cs_match(row)
        else:
            with self._lock, self._connect() as db:
                db.execute("BEGIN IMMEDIATE")
                db.execute(
                    """
                    INSERT INTO verified_routes(
                        route_id, agent_name, task_tokens_json, pipeline_keys_json,
                        tool_keys_json, verification, source_job_id, success_count,
                        first_verified_at, last_verified_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
                    ON CONFLICT(route_id) DO UPDATE SET
                        verification=excluded.verification,
                        source_job_id=excluded.source_job_id,
                        success_count=verified_routes.success_count + 1,
                        last_verified_at=excluded.last_verified_at
                    """,
                    (
                        route_id,
                        agent_name,
                        json.dumps(task_tokens, separators=(",", ":")),
                        json.dumps(pipelines, separators=(",", ":")),
                        json.dumps(tools, separators=(",", ":")),
                        _verification_summary(receipt.verification),
                        str(source_job_id or "")[:200],
                        now,
                        now,
                    ),
                )
                row = db.execute(
                    "SELECT * FROM verified_routes WHERE route_id=?",
                    (route_id,),
                ).fetchone()
                db.commit()
            assert row is not None
            return self._decode_match(row)

    def match(self, *, query: str, agent_name: str) -> VerifiedRouteMatch | None:
        query_tokens = _tokens(query)
        if not query_tokens:
            return None
        if self._bridge_state is not None:
            with self._bridge_state._connect() as db:
                rows = db.execute(
                    """
                    SELECT route_key, route_data FROM nova_ops.verified_routes
                    WHERE route_data->>'agent' = %s
                    ORDER BY last_used_at DESC
                    LIMIT 200
                    """,
                    (str(agent_name or "").strip(),),
                ).fetchall()
            best: tuple[float, VerifiedRouteMatch] | None = None
            for row in rows:
                rd = row[1] if isinstance(row[1], dict) else json.loads(row[1])
                task_tokens = set(rd.get("task_tokens", []))
                if not task_tokens:
                    continue
                overlap = len(task_tokens & query_tokens)
                coverage = overlap / len(task_tokens)
                if overlap < min(2, len(task_tokens)) or coverage < 0.6:
                    continue
                candidate = self._decode_cs_match(row)
                score = coverage + min(overlap, 6) / 10 + min(candidate.success_count, 5) / 100
                if best is None or score > best[0]:
                    best = (score, candidate)
            return best[1] if best else None
        else:
            with self._lock, self._connect() as db:
                rows = db.execute(
                    """
                    SELECT * FROM verified_routes
                    WHERE agent_name=?
                    ORDER BY last_verified_at DESC
                    LIMIT 200
                    """,
                    (str(agent_name or "").strip(),),
                ).fetchall()
            best: tuple[float, VerifiedRouteMatch] | None = None
            for row in rows:
                task_tokens = set(json.loads(str(row["task_tokens_json"] or "[]")))
                if not task_tokens:
                    continue
                overlap = len(task_tokens & query_tokens)
                coverage = overlap / len(task_tokens)
                if overlap < min(2, len(task_tokens)) or coverage < 0.6:
                    continue
                candidate = self._decode_match(row)
                score = coverage + min(overlap, 6) / 10 + min(candidate.success_count, 5) / 100
                if best is None or score > best[0]:
                    best = (score, candidate)
            return best[1] if best else None

    def _validated_route(
        self,
        receipt: VerifiedRouteReceipt,
        agent_name: str,
    ) -> tuple[tuple[str, ...], tuple[str, ...], set[str]]:
        pipelines_raw = _registry_items(self.pipeline_registry_path, "pipelines")
        tools_raw = _registry_items(self.tool_registry_path, "tools")
        vocabulary: set[str] = set()
        pipelines: list[str] = []
        tools: list[str] = []
        for key in receipt.pipeline_keys:
            raw = pipelines_raw.get(key)
            if not isinstance(raw, dict) or not _route_owned_by(raw, agent_name):
                raise ValueError(f"Pipeline route is not registry-bound to {agent_name}: {key}")
            pipelines.append(key)
            vocabulary.update(_route_vocabulary(key, raw))
        for key in receipt.tool_keys:
            raw = tools_raw.get(key)
            if not isinstance(raw, dict) or not _route_owned_by(raw, agent_name):
                raise ValueError(f"Tool route is not registry-bound to {agent_name}: {key}")
            tools.append(key)
            vocabulary.update(_route_vocabulary(key, raw))
        return tuple(pipelines), tuple(tools), vocabulary

    @staticmethod
    def _decode_match(row: sqlite3.Row) -> VerifiedRouteMatch:
        return VerifiedRouteMatch(
            route_id=str(row["route_id"]),
            agent_name=str(row["agent_name"]),
            pipeline_keys=tuple(json.loads(str(row["pipeline_keys_json"] or "[]"))),
            tool_keys=tuple(json.loads(str(row["tool_keys_json"] or "[]"))),
            verification=str(row["verification"] or ""),
            success_count=int(row["success_count"] or 0),
            last_verified_at=float(row["last_verified_at"] or 0),
        )

    def _decode_cs_match(self, row: tuple) -> VerifiedRouteMatch:
        route_key, route_data = row[0], row[1]
        if isinstance(route_data, str):
            route_data = json.loads(route_data)
        return VerifiedRouteMatch(
            route_id=str(route_key),
            agent_name=str(route_data.get("agent", "")),
            pipeline_keys=tuple(route_data.get("pipelines", [])),
            tool_keys=tuple(route_data.get("tools", [])),
            verification=str(route_data.get("verification", "")),
            success_count=int(route_data.get("success_count", 0)),
            last_verified_at=float(route_data.get("last_verified_at", 0)),
        )


def _registry_items(path: Path, key: str) -> dict[str, Any]:
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    values = parsed.get(key) if isinstance(parsed, dict) else {}
    return {str(name).lower(): raw for name, raw in values.items()} if isinstance(values, dict) else {}


def _route_owned_by(raw: Mapping[str, Any], agent_name: str) -> bool:
    owners = {str(item).strip() for item in raw.get("primary_agents") or [] if str(item).strip()}
    return not owners or str(agent_name or "").strip() in owners


def _route_vocabulary(key: str, raw: Mapping[str, Any]) -> set[str]:
    values: Iterable[Any] = (
        key,
        raw.get("display_name") or "",
        *(raw.get("aliases") or []),
        raw.get("use_when") or "",
    )
    return {token for value in values for token in _tokens(str(value))}


def _tokens(value: str) -> set[str]:
    return {
        token
        for token in _TOKEN_RE.findall(str(value or "").casefold())
        if token not in _STOP_WORDS and not token.isdigit() and len(token) > 1
    }


def _verification_summary(value: str) -> str:
    """Retain only a non-customer verification class in reusable routing state."""

    lowered = str(value or "").casefold()
    if "test" in lowered and ("pass" in lowered or "verified" in lowered):
        return "focused tests passed"
    if "readback" in lowered or "reconcil" in lowered:
        return "same-surface readback verified"
    return "verification confirmed"