# AgentChat/direct_codex 2026-07-14T00:00:00-04:00: durable inbox work ledger and deterministic routing.
# AgentChat/coding_agent 2026-07-14T19:30:00-04:00: acknowledge invoice-thread replies before support intake.
from __future__ import annotations

import json
import math
import re
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import Condition
from typing import Any, Iterable

from .memory import redact_secrets


SCHEMA_VERSION = 1
TERMINAL_STATES = {"complete"}
ACTIONABLE_STATES = {"action_pending"}
MAX_LIVE_DETECTION_LATENCY_MS = 24 * 60 * 60 * 1000
STALE_ACTION_PENDING_SECONDS = 30 * 60
STATE_TRANSITIONS = {
    "detected": {"classified", "complete"},
    "classified": {"assigned", "blocked", "complete"},
    "assigned": {"action_pending", "blocked"},
    "action_pending": {"write_verified", "blocked", "complete"},
    "write_verified": {"complete", "blocked"},
    "blocked": {"classified", "assigned", "action_pending", "complete"},
    "complete": set(),
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_text(value: Any, limit: int) -> str:
    text = " ".join(redact_secrets(str(value or "")).split())
    text = re.sub(
        r"(?i)\b(api[_ -]?key|access[_ -]?key|password|passwd|token|client[_ -]?secret|secret)\s*[:=]\s*[^\s,;]+",
        lambda match: f"{match.group(1)}=[redacted]",
        text,
    )
    text = re.sub(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+", "Bearer [redacted]", text)
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def _safe_identifier(value: Any, limit: int) -> str:
    """Preserve trusted machine identifiers without weakening free-text redaction."""

    text = str(value or "").strip()
    if len(text) <= limit and re.fullmatch(r"[A-Za-z0-9_.:-]*", text):
        return text
    return _safe_text(text, limit)


def _safe_json_value(value: Any, *, depth: int = 0) -> Any:
    if depth >= 6:
        return "[truncated]"
    if isinstance(value, dict):
        return {
            _safe_text(key, 120): _safe_json_value(item, depth=depth + 1)
            for key, item in list(value.items())[:50]
        }
    if isinstance(value, (list, tuple, set)):
        return [_safe_json_value(item, depth=depth + 1) for item in list(value)[:50]]
    if isinstance(value, str):
        return _safe_text(value, 2000)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return _safe_text(value, 1000)


def _json(value: Any, *, limit: int = 12000) -> str:
    rendered = json.dumps(
        _safe_json_value(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    if len(rendered) <= limit:
        return rendered
    return json.dumps({"truncated": True}, separators=(",", ":"))


def _loads(value: Any, fallback: Any) -> Any:
    try:
        parsed = json.loads(str(value or ""))
    except (TypeError, ValueError, json.JSONDecodeError):
        return fallback
    return parsed


@dataclass(frozen=True)
class RouteDecision:
    classification: str
    route: str
    reason: str
    deterministic: bool
    action_required: bool


def classify_inbox_message(
    message: dict[str, Any],
    *,
    trusted_nmi_senders: Iterable[str] = (),
    known_junk_senders: Iterable[str] = (),
) -> RouteDecision:
    """Classify bounded Gmail metadata without treating message text as instructions."""

    sender = str(message.get("from") or "").casefold()
    recipients = " ".join(
        str(message.get(field) or "").casefold()
        for field in ("to", "cc", "deliveredTo")
    )
    subject = str(message.get("subject") or "").casefold()
    snippet = str(message.get("snippet") or "").casefold()
    combined = " ".join((sender, subject, snippet))
    labels = {str(value).strip().upper() for value in (message.get("labelIds") or [])}

    if "INBOX" not in labels or "UNREAD" not in labels:
        return RouteDecision("not_pending", "complete", "Message is not unread in Inbox.", True, False)

    pure_zero_sales_notice = (
        any(token in subject for token in ("zero sale", "zero-sale", "$0"))
        and "non-submission" not in subject
        and "non submission" not in subject
        and "sales submission issue" not in subject
    )
    if pure_zero_sales_notice:
        return RouteDecision(
            "singapore_zero_sales_notice",
            "gmail_cleanup_mark_read",
            "Zero-sale verification belongs to the store owner and requires no Nova action.",
            True,
            True,
        )

    singapore_signal = (
        "integration@novapointofsale.com" in combined
        or "singapore" in combined
        or "non-submission" in combined
        or "non submission" in combined
        or "sales submission issue" in combined
        or ("ftp" in combined and any(token in combined for token in ("upload", "submission", "server", "interface")))
        or ("sftp" in combined and any(token in combined for token in ("upload", "submission", "server", "interface")))
    )
    if singapore_signal:
        retired = any(token in combined for token in ("retired", "deactivated", "deactivate", "retire interface"))
        new_interface = any(
            token in combined
            for token in (
                "create a new interface",
                "create new interface",
                "new integration",
                "new interface",
                "onboard a new",
                "provision a new",
                "set up a new",
                "setup a new",
            )
        ) or (
            "interface" in combined
            and "new" in combined
            and any(token in combined for token in ("create", "build", "add", "provision", "onboard", "set up", "setup"))
        )
        operational = any(
            token in combined
            for token in (
                "failure",
                "failed",
                "status",
                "upload",
                "authentication",
                "password",
                "credential",
                "remediation",
                "retry",
                "update",
                "reactivate",
                "non-submission",
                "non submission",
                "sales submission issue",
            )
        )
        if retired and not "reactivat" in combined:
            return RouteDecision(
                "singapore_retired",
                "complete",
                "Verified retirement wording is handled silently by policy.",
                True,
                False,
            )
        if new_interface and not operational:
            return RouteDecision(
                "singapore_new_interface_request",
                "taylor_support_intake",
                "Explicit brand-new interface request requires bounded account/ticket judgment.",
                True,
                True,
            )
        return RouteDecision(
            "singapore_operation",
            "singapore_runner",
            "Existing-interface or submission work belongs to the deterministic Singapore runner.",
            True,
            True,
        )

    trusted = {str(value).strip().casefold() for value in trusted_nmi_senders if str(value).strip()}
    nmi_sender = any(value and value in sender for value in trusted)
    nmi_content = any(
        token in combined
        for token in ("nmi", "tokenization key", "security key", "api keys", "api key")
    )
    if nmi_sender and nmi_content:
        return RouteDecision(
            "propelr_nmi_setup",
            "propelr_nmi_runner",
            "Trusted Propelr/NMI sender and setup metadata matched.",
            True,
            True,
        )

    salesforce_sender = "salesforce" in sender and any(
        token in sender for token in ("noreply", "no-reply", "notification", "salesforce.com")
    )
    salesforce_notice = salesforce_sender or "salesforce notification" in subject
    if salesforce_notice and re.search(r"\b\d{6}\b", f"{subject} {snippet}"):
        return RouteDecision(
            "salesforce_notification",
            "gmail_cleanup_mark_read",
            "Numbered Salesforce notification is represented by the ticket projection.",
            True,
            True,
        )

    known_junk = {str(value).strip().casefold() for value in known_junk_senders if str(value).strip()}
    if any(value and value in sender for value in known_junk):
        return RouteDecision(
            "known_commercial_noise",
            "gmail_cleanup_archive",
            "Sender matched the explicit local commercial-noise allowlist.",
            True,
            True,
        )

    billing_closure_recipient = "billing@novapointofsale.com" in recipients
    billing_closure_request = bool(
        re.search(
            r"\b(?:cancel(?:led|ing|lation)?|close(?:d|ing)?|closure|"
            r"deactivat(?:e|ed|ing|ion)|discontinu(?:e|ed|ing|ation)|"
            r"terminat(?:e|ed|ing|ion))\b",
            combined,
        )
    )
    if billing_closure_recipient and billing_closure_request:
        return RouteDecision(
            "billing_closure_confirmation",
            "jamie_billing_closure_intake",
            (
                "A customer closure confirmation reached billing. The complete message must be "
                "inspected because account wording can still identify only one location."
            ),
            True,
            True,
        )

    normalized_subject = subject
    while True:
        updated_subject = re.sub(r"^\s*(?:re|fw|fwd)\s*:\s*", "", normalized_subject, count=1)
        if updated_subject == normalized_subject:
            break
        normalized_subject = updated_subject
    automated_sender = any(
        token in sender
        for token in ("noreply", "no-reply", "mailer-daemon", "postmaster")
    )
    if (
        normalized_subject.strip() == "your novapos invoice is ready"
        and not automated_sender
        and not bool(message.get("listUnsubscribe"))
    ):
        return RouteDecision(
            "invoice_reply_acknowledgement",
            "taylor_support_intake",
            "Invoice-thread reply needs an immediate acknowledgement and normal support intake.",
            True,
            True,
        )

    return RouteDecision(
        "support_or_customer_mail",
        "taylor_support_intake",
        "Customer or operational mail requires bounded Taylor judgment.",
        False,
        True,
    )


class InboxLedger:
    """SQLite-backed inbox state machine with bounded local projections and events."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._changed = Condition()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.path), timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=5000")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=FULL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS inbox_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at_utc TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS inbox_items (
                    message_id TEXT PRIMARY KEY,
                    thread_id TEXT NOT NULL DEFAULT '',
                    history_id TEXT NOT NULL DEFAULT '',
                    internal_date_ms INTEGER NOT NULL DEFAULT 0,
                    sender TEXT NOT NULL DEFAULT '',
                    subject TEXT NOT NULL DEFAULT '',
                    snippet TEXT NOT NULL DEFAULT '',
                    label_ids_json TEXT NOT NULL DEFAULT '[]',
                    classification TEXT NOT NULL DEFAULT '',
                    route TEXT NOT NULL DEFAULT '',
                    classification_reason TEXT NOT NULL DEFAULT '',
                    deterministic INTEGER NOT NULL DEFAULT 0,
                    action_required INTEGER NOT NULL DEFAULT 0,
                    state TEXT NOT NULL,
                    assigned_agent TEXT NOT NULL DEFAULT '',
                    assigned_job_id TEXT NOT NULL DEFAULT '',
                    action_key TEXT NOT NULL DEFAULT '',
                    action_result_json TEXT NOT NULL DEFAULT '{}',
                    write_readback_verified INTEGER NOT NULL DEFAULT 0,
                    detection_latency_eligible INTEGER NOT NULL DEFAULT 1,
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    next_attempt_at_utc TEXT NOT NULL DEFAULT '',
                    detected_at_utc TEXT NOT NULL,
                    updated_at_utc TEXT NOT NULL,
                    completed_at_utc TEXT NOT NULL DEFAULT ''
                );
                CREATE INDEX IF NOT EXISTS idx_inbox_items_state
                    ON inbox_items(state, next_attempt_at_utc, internal_date_ms);
                CREATE INDEX IF NOT EXISTS idx_inbox_items_thread
                    ON inbox_items(thread_id, internal_date_ms);
                CREATE TABLE IF NOT EXISTS inbox_events (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    message_id TEXT NOT NULL DEFAULT '',
                    event_type TEXT NOT NULL,
                    from_state TEXT NOT NULL DEFAULT '',
                    to_state TEXT NOT NULL DEFAULT '',
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    created_at_utc TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS inbox_polls (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    started_at_utc TEXT NOT NULL,
                    completed_at_utc TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    status TEXT NOT NULL,
                    messages_seen INTEGER NOT NULL DEFAULT 0,
                    messages_new INTEGER NOT NULL DEFAULT 0,
                    model_jobs_queued INTEGER NOT NULL DEFAULT 0,
                    noop_model_runs_avoided INTEGER NOT NULL DEFAULT 0,
                    error TEXT NOT NULL DEFAULT '',
                    elapsed_ms INTEGER NOT NULL DEFAULT 0
                );
                """
            )
            columns = {
                str(row[1]) for row in connection.execute("PRAGMA table_info(inbox_items)").fetchall()
            }
            if "detection_latency_eligible" not in columns:
                connection.execute(
                    "ALTER TABLE inbox_items ADD COLUMN detection_latency_eligible INTEGER NOT NULL DEFAULT 0"
                )
            connection.execute(
                "UPDATE inbox_items SET detection_latency_eligible=0 "
                "WHERE detection_latency_eligible<>0 AND (internal_date_ms<=0 OR "
                "((CAST(strftime('%s',detected_at_utc) AS INTEGER)*1000)-internal_date_ms)>?)",
                (MAX_LIVE_DETECTION_LATENCY_MS,),
            )
            connection.execute(
                "INSERT INTO inbox_meta(key,value,updated_at_utc) VALUES('schema_version',?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at_utc=excluded.updated_at_utc",
                (str(SCHEMA_VERSION), _utc_now()),
            )

    def quick_check(self) -> str:
        with self._connect() as connection:
            row = connection.execute("PRAGMA quick_check").fetchone()
        return str(row[0] if row else "unknown")

    def get_meta(self, key: str, default: str = "") -> str:
        with self._connect() as connection:
            row = connection.execute("SELECT value FROM inbox_meta WHERE key=?", (str(key),)).fetchone()
        return str(row[0]) if row else default

    def set_meta(self, key: str, value: Any) -> None:
        now = _utc_now()
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO inbox_meta(key,value,updated_at_utc) VALUES(?,?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at_utc=excluded.updated_at_utc",
                (str(key), _safe_text(value, 4000), now),
            )

    def _append_event(
        self,
        connection: sqlite3.Connection,
        *,
        message_id: str,
        event_type: str,
        from_state: str = "",
        to_state: str = "",
        payload: dict[str, Any] | None = None,
    ) -> int:
        cursor = connection.execute(
            "INSERT INTO inbox_events(message_id,event_type,from_state,to_state,payload_json,created_at_utc) "
            "VALUES(?,?,?,?,?,?)",
            (
                _safe_identifier(message_id, 256),
                _safe_identifier(event_type, 120),
                _safe_identifier(from_state, 40),
                _safe_identifier(to_state, 40),
                _json(payload or {}, limit=4000),
                _utc_now(),
            ),
        )
        return int(cursor.lastrowid or 0)

    def _notify(self) -> None:
        with self._changed:
            self._changed.notify_all()

    def upsert_detected(
        self,
        message: dict[str, Any],
        *,
        history_id: str = "",
        measure_detection_latency: bool = True,
    ) -> bool:
        message_id = str(message.get("id") or "").strip()
        if not message_id:
            raise ValueError("Gmail message id is required")
        now = _utc_now()
        label_ids = sorted({str(value).strip().upper() for value in (message.get("labelIds") or []) if str(value).strip()})
        try:
            internal_date_ms = max(0, int(str(message.get("internalDate") or "0")))
        except ValueError:
            internal_date_ms = 0
        detected_latency_ms = max(0, int(time.time() * 1000) - internal_date_ms) if internal_date_ms else 0
        detection_eligible = bool(
            measure_detection_latency
            and internal_date_ms
            and detected_latency_ms <= MAX_LIVE_DETECTION_LATENCY_MS
        )
        inserted = False
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT state FROM inbox_items WHERE message_id=?", (message_id,)
            ).fetchone()
            if existing is None:
                inserted = True
                connection.execute(
                    "INSERT INTO inbox_items(message_id,thread_id,history_id,internal_date_ms,sender,subject,snippet,"
                    "label_ids_json,state,detection_latency_eligible,detected_at_utc,updated_at_utc) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        message_id,
                        _safe_text(message.get("threadId"), 256),
                        _safe_text(history_id or message.get("historyId"), 64),
                        internal_date_ms,
                        _safe_text(message.get("from"), 500),
                        _safe_text(message.get("subject"), 500),
                        _safe_text(message.get("snippet"), 1000),
                        _json(label_ids, limit=1000),
                        "detected",
                        1 if detection_eligible else 0,
                        now,
                        now,
                    ),
                )
                self._append_event(
                    connection,
                    message_id=message_id,
                    event_type="detected",
                    to_state="detected",
                    payload={"threadId": message.get("threadId") or ""},
                )
            else:
                connection.execute(
                    "UPDATE inbox_items SET thread_id=?,history_id=?,internal_date_ms=?,sender=?,subject=?,snippet=?,"
                    "label_ids_json=?,updated_at_utc=? WHERE message_id=?",
                    (
                        _safe_text(message.get("threadId"), 256),
                        _safe_text(history_id or message.get("historyId"), 64),
                        internal_date_ms,
                        _safe_text(message.get("from"), 500),
                        _safe_text(message.get("subject"), 500),
                        _safe_text(message.get("snippet"), 1000),
                        _json(label_ids, limit=1000),
                        now,
                        message_id,
                    ),
                )
        if inserted:
            self._notify()
        return inserted

    def classify(self, message_id: str, decision: RouteDecision) -> None:
        now = _utc_now()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT state FROM inbox_items WHERE message_id=?", (message_id,)
            ).fetchone()
            if row is None:
                raise KeyError(message_id)
            state = str(row["state"])
            if state == "complete":
                return
            connection.execute(
                "UPDATE inbox_items SET classification=?,route=?,classification_reason=?,deterministic=?,"
                "action_required=?,state='classified',updated_at_utc=? WHERE message_id=?",
                (
                    decision.classification,
                    decision.route,
                    _safe_text(decision.reason, 500),
                    1 if decision.deterministic else 0,
                    1 if decision.action_required else 0,
                    now,
                    message_id,
                ),
            )
            self._append_event(
                connection,
                message_id=message_id,
                event_type="classified",
                from_state=state,
                to_state="classified",
                payload={
                    "classification": decision.classification,
                    "route": decision.route,
                    "deterministic": decision.deterministic,
                },
            )
        self._notify()
        if decision.route == "complete":
            self.complete(message_id, result={"reason": decision.reason})

    def transition(
        self,
        message_id: str,
        to_state: str,
        *,
        event_type: str = "state_changed",
        payload: dict[str, Any] | None = None,
        updates: dict[str, Any] | None = None,
    ) -> None:
        destination = str(to_state).strip().lower()
        if destination not in STATE_TRANSITIONS:
            raise ValueError(f"Unknown inbox state: {destination}")
        now = _utc_now()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT * FROM inbox_items WHERE message_id=?", (message_id,)).fetchone()
            if row is None:
                raise KeyError(message_id)
            current = str(row["state"])
            if current == destination:
                return
            if destination not in STATE_TRANSITIONS.get(current, set()):
                raise ValueError(f"Invalid inbox state transition: {current} -> {destination}")
            fields: dict[str, Any] = {"state": destination, "updated_at_utc": now}
            if destination == "complete":
                fields["completed_at_utc"] = now
            allowed_updates = {
                "assigned_agent",
                "assigned_job_id",
                "action_key",
                "action_result_json",
                "write_readback_verified",
                "attempt_count",
                "next_attempt_at_utc",
                "action_required",
            }
            for key, value in (updates or {}).items():
                if key in allowed_updates:
                    fields[key] = value
            assignments = ",".join(f"{key}=?" for key in fields)
            connection.execute(
                f"UPDATE inbox_items SET {assignments} WHERE message_id=?",
                [*fields.values(), message_id],
            )
            self._append_event(
                connection,
                message_id=message_id,
                event_type=event_type,
                from_state=current,
                to_state=destination,
                payload=payload,
            )
        self._notify()

    def mark_assigned(
        self,
        message_ids: Iterable[str],
        *,
        agent: str,
        job_id: str,
        action_key: str,
    ) -> None:
        for message_id in dict.fromkeys(str(value).strip() for value in message_ids if str(value).strip()):
            self.transition(
                message_id,
                "assigned",
                event_type="assigned",
                payload={"agent": agent, "jobId": job_id},
                updates={
                    "assigned_agent": _safe_identifier(agent, 120),
                    "assigned_job_id": _safe_identifier(job_id, 256),
                    "action_key": _safe_identifier(action_key, 256),
                },
            )
            self.transition(
                message_id,
                "action_pending",
                event_type="action_queued",
                payload={"agent": agent, "jobId": job_id},
            )

    def block(self, message_id: str, error: Any, *, retry_after_seconds: int = 60) -> None:
        row = self.item(message_id)
        if not row or row.get("state") == "complete":
            return
        attempts = int(row.get("attemptCount") or 0) + 1
        retry_at = datetime.fromtimestamp(time.time() + max(15, int(retry_after_seconds)), tz=timezone.utc).isoformat()
        self.transition(
            message_id,
            "blocked",
            event_type="blocked",
            payload={"error": _safe_text(error, 500), "attempt": attempts},
            updates={
                "attempt_count": attempts,
                "next_attempt_at_utc": retry_at,
                "action_result_json": _json({"error": _safe_text(error, 500)}),
            },
        )

    def retry_blocked(self, message_id: str) -> None:
        self.transition(message_id, "classified", event_type="retry_ready", updates={"next_attempt_at_utc": ""})

    def repair_legacy_redacted_assignment(self, message_id: str) -> bool:
        """Requeue one legacy row whose trusted job ID was mistaken for a secret."""

        clean_id = _safe_identifier(message_id, 256)
        now = _utc_now()
        with self._connect() as connection:
            row = connection.execute(
                "SELECT state,assigned_job_id FROM inbox_items WHERE message_id=?",
                (clean_id,),
            ).fetchone()
            if (
                row is None
                or str(row["state"] or "") not in {"assigned", "action_pending"}
                or str(row["assigned_job_id"] or "") != "[redacted]"
            ):
                return False
            previous = str(row["state"] or "")
            connection.execute(
                "UPDATE inbox_items SET state='classified',assigned_agent='',assigned_job_id='',action_key='',"
                "next_attempt_at_utc='',action_result_json=?,updated_at_utc=? WHERE message_id=?",
                (
                    _json({"reason": "Legacy redacted assignment identifier was repaired and requeued."}),
                    now,
                    clean_id,
                ),
            )
            self._append_event(
                connection,
                message_id=clean_id,
                event_type="legacy_assignment_repaired",
                from_state=previous,
                to_state="classified",
                payload={"reason": "trusted_job_identifier_redacted"},
            )
        self._notify()
        return True

    def mark_write_verified(self, message_id: str, result: dict[str, Any] | None = None) -> None:
        self.transition(
            message_id,
            "write_verified",
            event_type="write_verified",
            payload={"verified": True},
            updates={
                "write_readback_verified": 1,
                "action_result_json": _json(result or {}),
            },
        )

    def complete(
        self,
        message_id: str,
        *,
        result: dict[str, Any] | None = None,
        write_verified: bool = False,
    ) -> None:
        row = self.item(message_id)
        if not row or row.get("state") == "complete":
            return
        if write_verified and row.get("state") == "action_pending":
            self.mark_write_verified(message_id, result)
            row = self.item(message_id) or row
        self.transition(
            message_id,
            "complete",
            event_type="completed",
            payload={"writeVerified": bool(write_verified)},
            updates={"action_result_json": _json(result or {})},
        )

    def complete_pending_thread(self, thread_id: str, *, except_message_id: str = "", reason: str = "") -> int:
        if not str(thread_id).strip():
            return 0
        completed = 0
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT message_id,state FROM inbox_items WHERE thread_id=? AND message_id<>? AND state<>'complete'",
                (str(thread_id).strip(), str(except_message_id).strip()),
            ).fetchall()
        for row in rows:
            try:
                self.complete(str(row["message_id"]), result={"reason": reason or "Newer thread state superseded item."})
                completed += 1
            except ValueError:
                continue
        return completed

    def apply_support_result(self, result: dict[str, Any]) -> None:
        message_id = str(result.get("sourceEmailId") or result.get("messageId") or result.get("id") or "").strip()
        if not message_id or not self.item(message_id):
            return
        classification = str(result.get("classification") or "").strip().lower()
        outcome = str(result.get("result") or "").strip().lower()
        triage = str(result.get("triageDecision") or result.get("triage_decision") or "").strip().lower()
        gmail = result.get("gmail") if isinstance(result.get("gmail"), dict) else {}
        ticket = result.get("ticket") if isinstance(result.get("ticket"), dict) else {}
        safe_result = {
            "classification": classification,
            "result": outcome,
            "triageDecision": triage,
            "recommendedAction": _safe_text(result.get("recommendedAction"), 1000),
            "recommendedReplyBody": _safe_text(result.get("recommendedReplyBody"), 5000),
            "templateSuggestion": result.get("templateSuggestion") if isinstance(result.get("templateSuggestion"), dict) else {},
            "ticket": {
                "number": _safe_text(ticket.get("number"), 80),
                "recordType": _safe_text(ticket.get("recordType"), 120),
                "verifiedAtUtc": _safe_text(ticket.get("verifiedAtUtc"), 80),
            },
            "gmail": {
                "status": _safe_text(gmail.get("status"), 80),
                "readbackVerified": gmail.get("readbackVerified") is True,
            },
            "blockers": [_safe_text(value, 300) for value in (result.get("blockers") or [])[:5]],
        }
        current_state = str((self.item(message_id) or {}).get("state") or "")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "UPDATE inbox_items SET action_result_json=?,updated_at_utc=? WHERE message_id=?",
                (_json(safe_result), _utc_now(), message_id),
            )
            self._append_event(
                connection,
                message_id=message_id,
                event_type="support_result_projected",
                from_state=current_state,
                to_state=current_state,
                payload={"classification": classification, "result": outcome, "triageDecision": triage},
            )
        self._notify()

        ticket_ready = classification in {"support_request", "singapore_new_interface_request"} and outcome in {
            "created",
            "already_exists",
        }
        if ticket_ready and gmail.get("readbackVerified") is True and str(gmail.get("status") or "").lower() == "marked_read":
            self.complete(message_id, result=safe_result, write_verified=True)
            return
        if classification in {"singapore_operation", "singapore_retired"} and outcome in {"routed", "skipped"}:
            self.complete(message_id, result=safe_result)
            return
        if (
            classification == "non_ticket"
            and triage in {"mark_read", "ignore", "no_action"}
            and gmail.get("readbackVerified") is True
        ):
            self.complete(message_id, result=safe_result, write_verified=True)
            return
        if outcome == "blocked":
            self.block(message_id, "; ".join(safe_result["blockers"]) or "Taylor intake was blocked.")
            return
        if triage in {"reply_needed", "leave_unread", "ticket_needed"}:
            return

    def item(self, message_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM inbox_items WHERE message_id=?", (str(message_id),)).fetchone()
        return self._row(row) if row else None

    def dispatchable(self, *, limit: int = 200) -> list[dict[str, Any]]:
        now = _utc_now()
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM inbox_items WHERE state='classified' OR "
                "(state='blocked' AND (next_attempt_at_utc='' OR next_attempt_at_utc<=?)) "
                "ORDER BY internal_date_ms ASC LIMIT ?",
                (now, max(1, min(int(limit), 1000))),
            ).fetchall()
        values = []
        for row in rows:
            item = self._row(row)
            if item["state"] == "blocked":
                try:
                    self.retry_blocked(item["messageId"])
                except ValueError:
                    continue
                item = self.item(item["messageId"]) or item
            values.append(item)
        return values

    def items_for_job(self, job_id: str, *, route: str = "") -> list[dict[str, Any]]:
        sql = "SELECT * FROM inbox_items WHERE assigned_job_id=?"
        params: list[Any] = [str(job_id)]
        if route:
            sql += " AND route=?"
            params.append(str(route))
        sql += " ORDER BY internal_date_ms ASC"
        with self._connect() as connection:
            rows = connection.execute(sql, params).fetchall()
        return [self._row(row) for row in rows]

    def pending_reconciliation_items(self, *, limit: int = 200) -> list[dict[str, Any]]:
        """Return a bounded oldest-first set whose live mailbox state must be rechecked."""

        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM inbox_items WHERE state='action_pending' "
                "ORDER BY updated_at_utc ASC LIMIT ?",
                (max(1, min(int(limit), 1000)),),
            ).fetchall()
        return [self._row(row) for row in rows]

    def reconcile_pending_message(
        self,
        message: dict[str, Any],
        decision: RouteDecision,
        *,
        requeue_stale: bool,
    ) -> str:
        """Terminalize read mail or safely requeue an orphaned stale assignment."""

        message_id = str(message.get("id") or "").strip()
        if not message_id or not self.item(message_id):
            return "missing"
        self.upsert_detected(message, measure_detection_latency=False)
        labels = {str(value).strip().upper() for value in (message.get("labelIds") or [])}
        if "INBOX" not in labels or "UNREAD" not in labels:
            self.complete(
                message_id,
                result={
                    "reason": "Live Gmail label reconciliation confirmed the message is no longer pending.",
                    "mailboxReadbackVerified": True,
                    "writeAttributedToThisRun": False,
                },
            )
            return "completed_live_readback"
        if decision.route == "complete":
            self.complete(message_id, result={"reason": decision.reason})
            return "completed_policy"
        if not requeue_stale:
            return "active"

        now = _utc_now()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT state FROM inbox_items WHERE message_id=?",
                (message_id,),
            ).fetchone()
            if row is None or str(row["state"]) == "complete":
                return "complete"
            current = str(row["state"])
            if current != "action_pending":
                return current
            connection.execute(
                "UPDATE inbox_items SET classification=?,route=?,classification_reason=?,deterministic=?,"
                "action_required=?,state='classified',assigned_agent='',assigned_job_id='',action_key='',"
                "action_result_json=?,next_attempt_at_utc='',updated_at_utc=? WHERE message_id=?",
                (
                    decision.classification,
                    decision.route,
                    _safe_text(decision.reason, 500),
                    1 if decision.deterministic else 0,
                    1 if decision.action_required else 0,
                    _json({"reason": "Stale terminal or missing assignment requeued after live Gmail readback."}),
                    now,
                    message_id,
                ),
            )
            self._append_event(
                connection,
                message_id=message_id,
                event_type="live_reconciled_retry",
                from_state=current,
                to_state="classified",
                payload={"classification": decision.classification, "route": decision.route},
            )
        self._notify()
        return "requeued"

    def email_watch_projection(self, *, limit: int = 200) -> dict[str, Any]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM inbox_items WHERE state IN ('action_pending','blocked') "
                "AND route IN ('taylor_support_intake','jamie_billing_closure_intake') "
                "ORDER BY internal_date_ms DESC LIMIT ?",
                (max(1, min(int(limit), 1000)),),
            ).fetchall()
        by_thread: dict[str, dict[str, Any]] = {}
        for row in rows:
            item = self._row(row)
            result = item.get("actionResult") or {}
            gmail = result.get("gmail") if isinstance(result.get("gmail"), dict) else {}
            if gmail.get("readbackVerified") is True and str(gmail.get("status") or "").lower() == "marked_read":
                continue
            identity = item.get("threadId") or item.get("messageId")
            if identity in by_thread:
                continue
            labels = {str(value).upper() for value in item.get("labelIds") or []}
            pending = "INBOX" in labels and "UNREAD" in labels
            if not pending:
                continue
            received = ""
            if int(item.get("internalDateMs") or 0) > 0:
                received = datetime.fromtimestamp(int(item["internalDateMs"]) / 1000, tz=timezone.utc).isoformat()
            triage = str(result.get("triageDecision") or "").strip() or "processing"
            billing_closure = (
                str(item.get("route") or "") == "jamie_billing_closure_intake"
            )
            by_thread[identity] = {
                "id": item["messageId"],
                "threadId": item["threadId"],
                "from": item["from"],
                "subject": item["subject"],
                "receivedAt": received,
                "snippet": item["snippet"],
                "sourceLabel": "INBOX",
                "urgency": "normal",
                "triageDecision": triage,
                "recommendedAction": (
                    result.get("recommendedAction")
                    or (
                        "Jamie is matching the closure confirmation to the correct ticket and scope."
                        if billing_closure
                        else "Taylor is processing this new message."
                    )
                ),
                "templateSuggestion": result.get("templateSuggestion") or {},
                "recommendedReplyBody": result.get("recommendedReplyBody") or "",
                "gmailState": {
                    "verified": True,
                    "pending": pending,
                    "inInbox": "INBOX" in labels,
                    "unread": "UNREAD" in labels,
                    "answered": False,
                    "latestDirection": "inbound",
                    "latestMessageId": item["messageId"],
                    "latestIncomingMessageId": item["messageId"],
                    "threadId": item["threadId"],
                    "directToUser": True,
                    "verifiedAtUtc": item["updatedAtUtc"],
                },
                "ledger": {
                    "state": item["state"],
                    "classification": item["classification"],
                    "assignedJobId": item["assignedJobId"],
                },
            }
        emails = list(by_thread.values())
        status = self.status()
        return {
            "ok": status["ok"],
            "status": "ok" if status["ok"] else "degraded",
            "updatedAtUtc": status.get("updatedAtUtc") or "",
            "summary": (
                f"{len(emails)} unread message{'s' if len(emails) != 1 else ''} need a reply or decision."
                if emails
                else "There are no current unread, unanswered action emails."
            ),
            "count": len(emails),
            "emails": emails,
            "source": "inbox_work_ledger",
            "ledger": status,
            "reconciliation": {"status": "ok" if status["ok"] else "degraded"},
        }

    def record_poll(
        self,
        *,
        started_at_utc: str,
        mode: str,
        status: str,
        messages_seen: int,
        messages_new: int,
        model_jobs_queued: int,
        error: str = "",
        elapsed_ms: int = 0,
    ) -> None:
        completed = _utc_now()
        avoided = 1 if status == "ok" and model_jobs_queued == 0 else 0
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO inbox_polls(started_at_utc,completed_at_utc,mode,status,messages_seen,messages_new,"
                "model_jobs_queued,noop_model_runs_avoided,error,elapsed_ms) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    started_at_utc,
                    completed,
                    _safe_identifier(mode, 80),
                    _safe_identifier(status, 80),
                    max(0, int(messages_seen)),
                    max(0, int(messages_new)),
                    max(0, int(model_jobs_queued)),
                    avoided,
                    _safe_text(error, 1000),
                    max(0, int(elapsed_ms)),
                ),
            )
            self._append_event(
                connection,
                message_id="",
                event_type="poll_completed",
                payload={
                    "mode": mode,
                    "status": status,
                    "messagesSeen": messages_seen,
                    "messagesNew": messages_new,
                    "modelJobsQueued": model_jobs_queued,
                },
            )
        self._notify()

    def events_after(self, sequence: int, *, limit: int = 100) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM inbox_events WHERE sequence>? ORDER BY sequence ASC LIMIT ?",
                (max(0, int(sequence)), max(1, min(int(limit), 500))),
            ).fetchall()
        return [
            {
                "sequence": int(row["sequence"]),
                "messageId": str(row["message_id"]),
                "type": str(row["event_type"]),
                "fromState": str(row["from_state"]),
                "toState": str(row["to_state"]),
                "payload": _loads(row["payload_json"], {}),
                "createdAtUtc": str(row["created_at_utc"]),
            }
            for row in rows
        ]

    def wait_for_events(self, sequence: int, *, timeout_seconds: float = 20.0) -> list[dict[str, Any]]:
        events = self.events_after(sequence)
        if events:
            return events
        with self._changed:
            self._changed.wait(timeout=max(0.0, min(float(timeout_seconds), 25.0)))
        return self.events_after(sequence)

    def status(self) -> dict[str, Any]:
        try:
            integrity = self.quick_check()
            with self._connect() as connection:
                states = {
                    str(row["state"]): int(row["count"])
                    for row in connection.execute(
                        "SELECT state,COUNT(*) AS count FROM inbox_items GROUP BY state"
                    ).fetchall()
                }
                latest_poll = connection.execute(
                    "SELECT * FROM inbox_polls ORDER BY id DESC LIMIT 1"
                ).fetchone()
                poll_totals = connection.execute(
                    "SELECT COUNT(*) AS polls,COALESCE(SUM(model_jobs_queued),0) AS model_jobs,"
                    "COALESCE(SUM(noop_model_runs_avoided),0) AS avoided FROM inbox_polls"
                ).fetchone()
                last_event = connection.execute(
                    "SELECT sequence,created_at_utc FROM inbox_events ORDER BY sequence DESC LIMIT 1"
                ).fetchone()
                last_sequence = int(last_event["sequence"] if last_event else 0)
                stale_cutoff = datetime.fromtimestamp(
                    time.time() - STALE_ACTION_PENDING_SECONDS,
                    tz=timezone.utc,
                ).isoformat()
                stale_pending = connection.execute(
                    "SELECT COUNT(*) AS count,MIN(updated_at_utc) AS oldest "
                    "FROM inbox_items WHERE state='action_pending' AND updated_at_utc<=?",
                    (stale_cutoff,),
                ).fetchone()
                latencies = [
                    max(0, int(row["detected_at_ms"]) - int(row["internal_date_ms"] or 0))
                    for row in connection.execute(
                        "SELECT internal_date_ms,CAST(strftime('%s',detected_at_utc) AS INTEGER)*1000 AS detected_at_ms "
                        "FROM inbox_items WHERE internal_date_ms>0 AND detection_latency_eligible=1 "
                        "ORDER BY detected_at_utc DESC LIMIT 500"
                    ).fetchall()
                ]
            latency_p95 = 0
            if latencies:
                ordered = sorted(latencies)
                latency_p95 = ordered[min(len(ordered) - 1, max(0, math.ceil(len(ordered) * 0.95) - 1))]
            stale_count = int(stale_pending["count"] if stale_pending else 0)
            oldest_pending_age_seconds = 0
            if stale_pending and stale_pending["oldest"]:
                try:
                    oldest = datetime.fromisoformat(str(stale_pending["oldest"]).replace("Z", "+00:00"))
                    if oldest.tzinfo is None:
                        oldest = oldest.replace(tzinfo=timezone.utc)
                    oldest_pending_age_seconds = max(0, int(time.time() - oldest.timestamp()))
                except ValueError:
                    oldest_pending_age_seconds = -1
            return {
                "ok": (
                    integrity == "ok"
                    and (latest_poll is None or str(latest_poll["status"]) != "failed")
                    and stale_count == 0
                ),
                "integrity": integrity,
                "states": states,
                "lastSequence": last_sequence,
                "updatedAtUtc": str(last_event["created_at_utc"]) if last_event else "",
                "lastPoll": {
                    "mode": str(latest_poll["mode"]),
                    "status": str(latest_poll["status"]),
                    "messagesSeen": int(latest_poll["messages_seen"]),
                    "messagesNew": int(latest_poll["messages_new"]),
                    "modelJobsQueued": int(latest_poll["model_jobs_queued"]),
                    "elapsedMs": int(latest_poll["elapsed_ms"]),
                    "error": str(latest_poll["error"]),
                }
                if latest_poll
                else {},
                "metrics": {
                    "polls": int(poll_totals["polls"] if poll_totals else 0),
                    "modelJobsQueued": int(poll_totals["model_jobs"] if poll_totals else 0),
                    "noopModelRunsAvoided": int(poll_totals["avoided"] if poll_totals else 0),
                    "detectionLatencyP95Ms": latency_p95,
                    "staleActionPendingCount": stale_count,
                    "oldestActionPendingAgeSeconds": oldest_pending_age_seconds,
                    "staleActionPendingThresholdSeconds": STALE_ACTION_PENDING_SECONDS,
                },
            }
        except sqlite3.Error as exc:
            return {
                "ok": False,
                "integrity": "unavailable",
                "states": {},
                "lastSequence": 0,
                "updatedAtUtc": "",
                "lastPoll": {"status": "failed", "error": _safe_text(exc, 500)},
                "metrics": {},
            }

    @staticmethod
    def _row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "messageId": str(row["message_id"]),
            "threadId": str(row["thread_id"]),
            "historyId": str(row["history_id"]),
            "internalDateMs": int(row["internal_date_ms"] or 0),
            "from": str(row["sender"]),
            "subject": str(row["subject"]),
            "snippet": str(row["snippet"]),
            "labelIds": _loads(row["label_ids_json"], []),
            "classification": str(row["classification"]),
            "route": str(row["route"]),
            "classificationReason": str(row["classification_reason"]),
            "deterministic": bool(row["deterministic"]),
            "actionRequired": bool(row["action_required"]),
            "state": str(row["state"]),
            "assignedAgent": str(row["assigned_agent"]),
            "assignedJobId": str(row["assigned_job_id"]),
            "actionKey": str(row["action_key"]),
            "actionResult": _loads(row["action_result_json"], {}),
            "writeReadbackVerified": bool(row["write_readback_verified"]),
            "attemptCount": int(row["attempt_count"] or 0),
            "nextAttemptAtUtc": str(row["next_attempt_at_utc"]),
            "detectedAtUtc": str(row["detected_at_utc"]),
            "updatedAtUtc": str(row["updated_at_utc"]),
            "completedAtUtc": str(row["completed_at_utc"]),
        }
