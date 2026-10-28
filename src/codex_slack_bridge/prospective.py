from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import uuid
from datetime import UTC, date, datetime, time as datetime_time, timedelta, tzinfo
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

try:  # Windows Python often has no system IANA database; dateutil carries one.
    from dateutil.tz import datetime_ambiguous, datetime_exists, gettz
except ImportError:  # pragma: no cover - exercised only in unusually minimal installs
    datetime_ambiguous = datetime_exists = gettz = None


ACTIVE_TASK = "active"
TERMINAL_TASK_STATUSES = {"cancelled", "completed"}
RECURRENCE_KINDS = {"once", "daily", "weekly", "weekdays", "interval"}
OVERDUE_POLICIES = {"deliver", "skip"}


class ProspectiveStore:
    """Durable prospective-memory store backed by SQLite.

    Delivery is coordinated using occurrence leases.  The occurrence's
    ``idempotency_key`` is stable across lease expiry and process restarts and
    must be passed to side-effecting delivery adapters for end-to-end dedupe.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA busy_timeout=5000")
        db.execute("PRAGMA foreign_keys=ON")
        return db

    def _init_db(self) -> None:
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS prospective_tasks (
                    id TEXT PRIMARY KEY,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    title TEXT NOT NULL,
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    timezone TEXT NOT NULL,
                    recurrence_kind TEXT NOT NULL DEFAULT 'once',
                    recurrence_interval INTEGER,
                    next_scheduled_at REAL,
                    status TEXT NOT NULL DEFAULT 'active',
                    overdue_policy TEXT NOT NULL DEFAULT 'deliver',
                    max_lateness_seconds REAL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    cancelled_at REAL
                );

                CREATE TABLE IF NOT EXISTS prospective_occurrences (
                    id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL REFERENCES prospective_tasks(id),
                    idempotency_key TEXT NOT NULL UNIQUE,
                    scheduled_at REAL NOT NULL,
                    available_at REAL NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    lease_owner TEXT,
                    lease_token TEXT,
                    lease_expires_at REAL,
                    delivered_at REAL,
                    result_json TEXT,
                    last_error TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    UNIQUE(task_id, scheduled_at)
                );

                CREATE INDEX IF NOT EXISTS idx_prospective_tasks_status_next
                    ON prospective_tasks(status, next_scheduled_at);
                CREATE INDEX IF NOT EXISTS idx_prospective_occurrences_due
                    ON prospective_occurrences(status, available_at, scheduled_at);
                CREATE INDEX IF NOT EXISTS idx_prospective_occurrences_task
                    ON prospective_occurrences(task_id, scheduled_at);
                """
            )

    def create(
        self,
        *,
        title: str,
        due_at: datetime | str,
        timezone_name: str | None = None,
        payload: dict[str, Any] | None = None,
        recurrence: str | dict[str, Any] | None = None,
        idempotency_key: str | None = None,
        overdue_policy: str = "deliver",
        max_lateness_seconds: float | None = None,
        now: datetime | str | None = None,
    ) -> dict[str, Any]:
        clean_title = str(title or "").strip()
        if not clean_title:
            raise ValueError("title is required")
        due = _aware_datetime(due_at, "due_at")
        tz_name, _ = _resolve_timezone(timezone_name, due)
        kind, recurrence_interval = _normalize_recurrence(recurrence)
        policy = str(overdue_policy or "deliver").strip().lower()
        if policy not in OVERDUE_POLICIES:
            raise ValueError(f"overdue_policy must be one of {sorted(OVERDUE_POLICIES)}")
        if max_lateness_seconds is not None and float(max_lateness_seconds) < 0:
            raise ValueError("max_lateness_seconds cannot be negative")
        if policy == "skip" and max_lateness_seconds is None:
            raise ValueError("skip overdue_policy requires max_lateness_seconds")

        payload_value = dict(payload or {})
        due_utc = due.astimezone(UTC)
        created = _aware_datetime(now, "now") if now is not None else datetime.now(UTC)
        explicit_key = str(idempotency_key or "").strip()
        stable_key = explicit_key or _task_key(
            clean_title,
            due_utc,
            tz_name,
            kind,
            recurrence_interval,
            payload_value,
        )
        task_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"prospective-task:{stable_key}"))
        timestamp = created.timestamp()
        scheduled = due_utc.timestamp()

        with self._transaction() as db:
            existing = db.execute(
                "SELECT * FROM prospective_tasks WHERE idempotency_key = ?",
                (stable_key,),
            ).fetchone()
            if existing is not None:
                return self._task_dict(db, existing)
            db.execute(
                """
                INSERT INTO prospective_tasks(
                    id, idempotency_key, title, payload_json, timezone,
                    recurrence_kind, recurrence_interval, next_scheduled_at,
                    status, overdue_policy, max_lateness_seconds,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?, ?)
                """,
                (
                    task_id,
                    stable_key,
                    clean_title,
                    _json(payload_value),
                    tz_name,
                    kind,
                    recurrence_interval,
                    scheduled,
                    policy,
                    float(max_lateness_seconds) if max_lateness_seconds is not None else None,
                    timestamp,
                    timestamp,
                ),
            )
            self._insert_occurrence(db, task_id, scheduled, timestamp)
            row = db.execute("SELECT * FROM prospective_tasks WHERE id = ?", (task_id,)).fetchone()
            assert row is not None
            return self._task_dict(db, row)

    def get(self, task_id: str) -> dict[str, Any] | None:
        with self._connect() as db:
            row = db.execute("SELECT * FROM prospective_tasks WHERE id = ?", (str(task_id),)).fetchone()
            return self._task_dict(db, row) if row is not None else None

    def get_occurrence(self, occurrence_id: str) -> dict[str, Any] | None:
        with self._connect() as db:
            row = db.execute(
                """
                SELECT o.*, t.title, t.payload_json, t.timezone,
                       t.recurrence_kind, t.recurrence_interval
                FROM prospective_occurrences o
                JOIN prospective_tasks t ON t.id = o.task_id
                WHERE o.id = ?
                """,
                (str(occurrence_id),),
            ).fetchone()
            return _occurrence_dict(row) if row is not None else None

    def list_tasks(self, *, status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        safe_limit = max(1, min(int(limit), 1000))
        with self._connect() as db:
            if status:
                rows = db.execute(
                    "SELECT * FROM prospective_tasks WHERE status = ? ORDER BY created_at DESC LIMIT ?",
                    (str(status), safe_limit),
                ).fetchall()
            else:
                rows = db.execute(
                    "SELECT * FROM prospective_tasks ORDER BY created_at DESC LIMIT ?",
                    (safe_limit,),
                ).fetchall()
            return [self._task_dict(db, row) for row in rows]

    def list_due(
        self,
        *,
        now: datetime | str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        observed = _aware_datetime(now, "now") if now is not None else datetime.now(UTC)
        safe_limit = max(1, min(int(limit), 1000))
        with self._connect() as db:
            rows = db.execute(
                """
                SELECT o.*, t.title, t.payload_json, t.timezone,
                       t.recurrence_kind, t.recurrence_interval,
                       t.max_lateness_seconds, t.overdue_policy
                FROM prospective_occurrences o
                JOIN prospective_tasks t ON t.id = o.task_id
                WHERE t.status = 'active'
                  AND o.available_at <= ?
                  AND (
                    o.status = 'pending'
                    OR (o.status = 'claimed' AND o.lease_expires_at <= ?)
                  )
                ORDER BY o.scheduled_at, o.created_at
                LIMIT ?
                """,
                (observed.timestamp(), observed.timestamp(), safe_limit),
            ).fetchall()
            return [_occurrence_dict(row, now_timestamp=observed.timestamp()) for row in rows]

    def reschedule(
        self,
        task_id: str,
        due_at: datetime | str,
        *,
        timezone_name: str | None = None,
        now: datetime | str | None = None,
    ) -> dict[str, Any]:
        due = _aware_datetime(due_at, "due_at")
        changed = _aware_datetime(now, "now") if now is not None else datetime.now(UTC)
        with self._transaction() as db:
            row = db.execute("SELECT * FROM prospective_tasks WHERE id = ?", (str(task_id),)).fetchone()
            if row is None:
                raise KeyError(task_id)
            tz_name, _ = _resolve_timezone(timezone_name or str(row["timezone"]), due)
            scheduled = due.astimezone(UTC).timestamp()
            stamp = changed.timestamp()
            target_occurrence = db.execute(
                "SELECT * FROM prospective_occurrences WHERE task_id = ? AND scheduled_at = ?",
                (str(task_id), scheduled),
            ).fetchone()
            if target_occurrence is not None and str(target_occurrence["status"]) in {
                "delivered",
                "failed",
                "skipped",
            }:
                raise ValueError("that task occurrence is already terminal; choose a different due time")
            db.execute(
                """
                UPDATE prospective_occurrences
                SET status = 'cancelled', lease_owner = NULL, lease_token = NULL,
                    lease_expires_at = NULL, updated_at = ?
                WHERE task_id = ? AND status IN ('pending', 'claimed')
                """,
                (stamp, str(task_id)),
            )
            db.execute(
                """
                UPDATE prospective_tasks
                SET timezone = ?, next_scheduled_at = ?, status = 'active',
                    cancelled_at = NULL, updated_at = ?
                WHERE id = ?
                """,
                (tz_name, scheduled, stamp, str(task_id)),
            )
            self._insert_occurrence(db, str(task_id), scheduled, stamp)
            # INSERT OR IGNORE deliberately preserves the occurrence identity and
            # delivery key when a cancelled/pending occurrence is rescheduled to
            # the same time.
            db.execute(
                """
                UPDATE prospective_occurrences
                SET status = 'pending', available_at = ?, lease_owner = NULL,
                    lease_token = NULL, lease_expires_at = NULL, updated_at = ?
                WHERE task_id = ? AND scheduled_at = ?
                  AND status IN ('cancelled', 'pending', 'claimed')
                """,
                (scheduled, stamp, str(task_id), scheduled),
            )
            updated = db.execute("SELECT * FROM prospective_tasks WHERE id = ?", (str(task_id),)).fetchone()
            assert updated is not None
            return self._task_dict(db, updated)

    def cancel(self, task_id: str, *, now: datetime | str | None = None) -> dict[str, Any]:
        changed = _aware_datetime(now, "now") if now is not None else datetime.now(UTC)
        stamp = changed.timestamp()
        with self._transaction() as db:
            row = db.execute("SELECT * FROM prospective_tasks WHERE id = ?", (str(task_id),)).fetchone()
            if row is None:
                raise KeyError(task_id)
            if str(row["status"]) != "cancelled":
                db.execute(
                    """
                    UPDATE prospective_tasks
                    SET status = 'cancelled', next_scheduled_at = NULL,
                        cancelled_at = ?, updated_at = ? WHERE id = ?
                    """,
                    (stamp, stamp, str(task_id)),
                )
                db.execute(
                    """
                    UPDATE prospective_occurrences
                    SET status = 'cancelled', lease_owner = NULL, lease_token = NULL,
                        lease_expires_at = NULL, updated_at = ?
                    WHERE task_id = ? AND status IN ('pending', 'claimed')
                    """,
                    (stamp, str(task_id)),
                )
            updated = db.execute("SELECT * FROM prospective_tasks WHERE id = ?", (str(task_id),)).fetchone()
            assert updated is not None
            return self._task_dict(db, updated)

    def claim_due(
        self,
        worker_id: str,
        *,
        now: datetime | str | None = None,
        lease_seconds: float = 300,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        owner = str(worker_id or "").strip()
        if not owner:
            raise ValueError("worker_id is required")
        if float(lease_seconds) <= 0:
            raise ValueError("lease_seconds must be positive")
        observed = _aware_datetime(now, "now") if now is not None else datetime.now(UTC)
        stamp = observed.timestamp()
        safe_limit = max(1, min(int(limit), 1000))
        claimed: list[dict[str, Any]] = []

        with self._transaction() as db:
            # More rows may be examined than returned because overdue skip-policy
            # occurrences are advanced without being handed to a worker.
            for _ in range(10000):
                row = db.execute(
                    """
                    SELECT o.*, t.title, t.payload_json, t.timezone,
                           t.recurrence_kind, t.recurrence_interval,
                           t.max_lateness_seconds, t.overdue_policy
                    FROM prospective_occurrences o
                    JOIN prospective_tasks t ON t.id = o.task_id
                    WHERE t.status = 'active'
                      AND o.available_at <= ?
                      AND (
                        o.status = 'pending'
                        OR (o.status = 'claimed' AND o.lease_expires_at <= ?)
                      )
                    ORDER BY o.scheduled_at, o.created_at
                    LIMIT 1
                    """,
                    (stamp, stamp),
                ).fetchone()
                if row is None:
                    break
                lateness = max(0.0, stamp - float(row["scheduled_at"]))
                max_lateness = row["max_lateness_seconds"]
                if (
                    str(row["overdue_policy"]) == "skip"
                    and max_lateness is not None
                    and lateness > float(max_lateness)
                ):
                    db.execute(
                        """
                        UPDATE prospective_occurrences
                        SET status = 'skipped', lease_owner = NULL, lease_token = NULL,
                            lease_expires_at = NULL, last_error = ?, updated_at = ?
                        WHERE id = ?
                        """,
                        (f"overdue by {lateness:.3f} seconds", stamp, str(row["id"])),
                    )
                    self._advance_after_terminal(db, row, stamp)
                    continue

                token = uuid.uuid4().hex
                db.execute(
                    """
                    UPDATE prospective_occurrences
                    SET status = 'claimed', attempt_count = attempt_count + 1,
                        lease_owner = ?, lease_token = ?, lease_expires_at = ?,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (owner, token, stamp + float(lease_seconds), stamp, str(row["id"])),
                )
                refreshed = db.execute(
                    """
                    SELECT o.*, t.title, t.payload_json, t.timezone,
                           t.recurrence_kind, t.recurrence_interval,
                           t.max_lateness_seconds, t.overdue_policy
                    FROM prospective_occurrences o
                    JOIN prospective_tasks t ON t.id = o.task_id
                    WHERE o.id = ?
                    """,
                    (str(row["id"]),),
                ).fetchone()
                assert refreshed is not None
                claimed.append(_occurrence_dict(refreshed, now_timestamp=stamp))
                if len(claimed) >= safe_limit:
                    break
        return claimed

    def deliver(
        self,
        occurrence_id: str,
        lease_token: str,
        *,
        result: dict[str, Any] | None = None,
        now: datetime | str | None = None,
    ) -> dict[str, Any]:
        delivered = _aware_datetime(now, "now") if now is not None else datetime.now(UTC)
        stamp = delivered.timestamp()
        with self._transaction() as db:
            row = self._occurrence_join(db, occurrence_id)
            if row is None:
                raise KeyError(occurrence_id)
            if str(row["status"]) == "delivered":
                return _occurrence_dict(row)
            self._validate_claim(row, lease_token)
            db.execute(
                """
                UPDATE prospective_occurrences
                SET status = 'delivered', delivered_at = ?, result_json = ?,
                    last_error = NULL, lease_owner = NULL, lease_token = NULL,
                    lease_expires_at = NULL, updated_at = ?
                WHERE id = ?
                """,
                (stamp, _json(dict(result or {})), stamp, str(occurrence_id)),
            )
            self._advance_after_terminal(db, row, stamp)
            refreshed = self._occurrence_join(db, occurrence_id)
            assert refreshed is not None
            return _occurrence_dict(refreshed)

    def fail(
        self,
        occurrence_id: str,
        lease_token: str,
        error: str,
        *,
        retry_at: datetime | str | None = None,
        now: datetime | str | None = None,
    ) -> dict[str, Any]:
        changed = _aware_datetime(now, "now") if now is not None else datetime.now(UTC)
        stamp = changed.timestamp()
        retry = _aware_datetime(retry_at, "retry_at") if retry_at is not None else None
        with self._transaction() as db:
            row = self._occurrence_join(db, occurrence_id)
            if row is None:
                raise KeyError(occurrence_id)
            if str(row["status"]) == "failed":
                return _occurrence_dict(row)
            self._validate_claim(row, lease_token)
            if retry is not None:
                db.execute(
                    """
                    UPDATE prospective_occurrences
                    SET status = 'pending', available_at = ?, last_error = ?,
                        lease_owner = NULL, lease_token = NULL,
                        lease_expires_at = NULL, updated_at = ?
                    WHERE id = ?
                    """,
                    (retry.timestamp(), str(error or "")[:4000], stamp, str(occurrence_id)),
                )
            else:
                db.execute(
                    """
                    UPDATE prospective_occurrences
                    SET status = 'failed', last_error = ?, lease_owner = NULL,
                        lease_token = NULL, lease_expires_at = NULL, updated_at = ?
                    WHERE id = ?
                    """,
                    (str(error or "")[:4000], stamp, str(occurrence_id)),
                )
                self._advance_after_terminal(db, row, stamp)
            refreshed = self._occurrence_join(db, occurrence_id)
            assert refreshed is not None
            return _occurrence_dict(refreshed)

    def _transaction(self):
        return _ImmediateTransaction(self._connect())

    def _insert_occurrence(
        self,
        db: sqlite3.Connection,
        task_id: str,
        scheduled_at: float,
        created_at: float,
    ) -> None:
        identity = f"prospective-occurrence:{task_id}:{scheduled_at:.6f}"
        occurrence_id = str(uuid.uuid5(uuid.NAMESPACE_URL, identity))
        delivery_key = "prospective:" + hashlib.sha256(identity.encode("utf-8")).hexdigest()
        db.execute(
            """
            INSERT OR IGNORE INTO prospective_occurrences(
                id, task_id, idempotency_key, scheduled_at, available_at,
                status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, 'pending', ?, ?)
            """,
            (
                occurrence_id,
                task_id,
                delivery_key,
                scheduled_at,
                scheduled_at,
                created_at,
                created_at,
            ),
        )

    def _advance_after_terminal(
        self,
        db: sqlite3.Connection,
        occurrence: sqlite3.Row,
        changed_at: float,
    ) -> None:
        task_id = str(occurrence["task_id"])
        task = db.execute("SELECT * FROM prospective_tasks WHERE id = ?", (task_id,)).fetchone()
        if task is None or str(task["status"]) != ACTIVE_TASK:
            return
        kind = str(task["recurrence_kind"])
        if kind == "once":
            db.execute(
                """
                UPDATE prospective_tasks
                SET status = 'completed', next_scheduled_at = NULL, updated_at = ?
                WHERE id = ?
                """,
                (changed_at, task_id),
            )
            return
        next_at = _next_scheduled_timestamp(
            float(occurrence["scheduled_at"]),
            str(task["timezone"]),
            kind,
            int(task["recurrence_interval"] or 1),
        )
        db.execute(
            "UPDATE prospective_tasks SET next_scheduled_at = ?, updated_at = ? WHERE id = ?",
            (next_at, changed_at, task_id),
        )
        self._insert_occurrence(db, task_id, next_at, changed_at)

    def _task_dict(self, db: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
        occurrence = None
        if row["next_scheduled_at"] is not None:
            occurrence = db.execute(
                """
                SELECT * FROM prospective_occurrences
                WHERE task_id = ? AND scheduled_at = ? LIMIT 1
                """,
                (str(row["id"]), float(row["next_scheduled_at"])),
            ).fetchone()
        return {
            "id": str(row["id"]),
            "idempotency_key": str(row["idempotency_key"]),
            "title": str(row["title"]),
            "payload": _load_json(row["payload_json"]),
            "timezone": str(row["timezone"]),
            "recurrence": {
                "kind": str(row["recurrence_kind"]),
                "interval": int(row["recurrence_interval"] or 1),
            },
            "next_scheduled_at": _iso(row["next_scheduled_at"]),
            "status": str(row["status"]),
            "overdue_policy": str(row["overdue_policy"]),
            "max_lateness_seconds": row["max_lateness_seconds"],
            "created_at": _iso(row["created_at"]),
            "updated_at": _iso(row["updated_at"]),
            "cancelled_at": _iso(row["cancelled_at"]),
            "next_occurrence": _occurrence_dict(occurrence) if occurrence is not None else None,
        }

    def _occurrence_join(self, db: sqlite3.Connection, occurrence_id: str) -> sqlite3.Row | None:
        return db.execute(
            """
            SELECT o.*, t.title, t.payload_json, t.timezone,
                   t.recurrence_kind, t.recurrence_interval,
                   t.max_lateness_seconds, t.overdue_policy
            FROM prospective_occurrences o
            JOIN prospective_tasks t ON t.id = o.task_id
            WHERE o.id = ?
            """,
            (str(occurrence_id),),
        ).fetchone()

    @staticmethod
    def _validate_claim(row: sqlite3.Row, lease_token: str) -> None:
        if str(row["status"]) != "claimed" or not lease_token or str(row["lease_token"] or "") != str(lease_token):
            raise ValueError("occurrence is not held by this lease token")


class _ImmediateTransaction:
    def __init__(self, db: sqlite3.Connection) -> None:
        self.db = db

    def __enter__(self) -> sqlite3.Connection:
        self.db.execute("BEGIN IMMEDIATE")
        return self.db

    def __exit__(self, exc_type, exc, traceback) -> None:
        try:
            self.db.execute("COMMIT" if exc_type is None else "ROLLBACK")
        finally:
            self.db.close()


def _aware_datetime(value: datetime | str | None, field: str) -> datetime:
    if isinstance(value, str):
        clean = value.strip().replace("Z", "+00:00")
        try:
            value = datetime.fromisoformat(clean)
        except ValueError as exc:
            raise ValueError(f"{field} must be an ISO-8601 datetime") from exc
    if not isinstance(value, datetime):
        raise TypeError(f"{field} must be a datetime or ISO-8601 string")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
    return value


def _timezone(name: str) -> tzinfo:
    if name.upper() == "UTC":
        return UTC
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError as exc:
        fallback = gettz(name) if gettz is not None else None
        if fallback is not None:
            return fallback
        raise ValueError(f"unknown timezone: {name}") from exc


def _resolve_timezone(name: str | None, due: datetime) -> tuple[str, tzinfo]:
    clean = str(name or "").strip()
    if not clean:
        clean = str(getattr(due.tzinfo, "key", "") or "")
    if not clean:
        offset = due.utcoffset()
        if offset == timedelta(0):
            return "UTC", UTC
        raise ValueError("timezone_name is required for a non-UTC fixed-offset datetime")
    return clean, _timezone(clean)


def _normalize_recurrence(value: str | dict[str, Any] | None) -> tuple[str, int | None]:
    if value is None:
        return "once", None
    if isinstance(value, str):
        kind = value.strip().lower()
        interval = 1
    elif isinstance(value, dict):
        kind = str(value.get("kind") or value.get("type") or "once").strip().lower()
        interval = int(value.get("interval") or value.get("every") or 1)
    else:
        raise TypeError("recurrence must be a string, mapping, or None")
    if kind not in RECURRENCE_KINDS:
        raise ValueError(f"recurrence kind must be one of {sorted(RECURRENCE_KINDS)}")
    if interval <= 0:
        raise ValueError("recurrence interval must be positive")
    if kind != "interval" and interval != 1:
        raise ValueError("only interval recurrence accepts an interval greater than one")
    return kind, (interval if kind != "once" else None)


def _next_scheduled_timestamp(scheduled_at: float, timezone_name: str, kind: str, interval: int) -> float:
    scheduled_utc = datetime.fromtimestamp(scheduled_at, UTC)
    if kind == "interval":
        return (scheduled_utc + timedelta(seconds=interval)).timestamp()
    timezone = _timezone(timezone_name)
    local = scheduled_utc.astimezone(timezone)
    if kind == "daily":
        target_date = local.date() + timedelta(days=1)
    elif kind == "weekly":
        target_date = local.date() + timedelta(days=7)
    elif kind == "weekdays":
        target_date = local.date() + timedelta(days=1)
        while target_date.weekday() >= 5:
            target_date += timedelta(days=1)
    else:
        raise ValueError(f"unsupported recurrence kind: {kind}")
    next_local = datetime.combine(target_date, local.timetz().replace(tzinfo=None), tzinfo=timezone)
    return next_local.astimezone(UTC).timestamp()


_WEEKDAYS = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}
_TIME_PATTERN = r"(?:[01]?\d|2[0-3]):[0-5]\d|(?:1[0-2]|0?[1-9])(?::[0-5]\d)?\s*(?:am|pm)"


def parse_due_expression(
    expression: str,
    *,
    now: datetime | str | None = None,
    timezone_name: str = "America/New_York",
) -> datetime:
    """Parse deliberately narrow reminder dates without model interpretation.

    Accepted forms are ISO date-times, ``today``/``tomorrow`` plus a time,
    and weekday names (optionally prefixed by ``next``) plus a 12- or 24-hour
    time.  Inputs missing either a date or time are rejected as ambiguous.
    """

    value = re.sub(r"\s+", " ", str(expression or "").strip())
    if not value:
        raise ValueError("due expression is required")
    timezone = _timezone(str(timezone_name or "America/New_York").strip())
    observed = _aware_datetime(now, "now") if now is not None else datetime.now(UTC)
    local_now = observed.astimezone(timezone)

    iso_match = re.fullmatch(
        r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:\d{2})?",
        value,
        flags=re.IGNORECASE,
    )
    if iso_match:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00").replace("z", "+00:00"))
        if parsed.tzinfo is not None:
            return parsed
        return _validated_local_datetime(parsed.date(), parsed.time(), timezone)

    natural = re.fullmatch(
        rf"(?P<day>today|tomorrow|(?:(?P<next>next)\s+)?(?P<weekday>{'|'.join(_WEEKDAYS)}))"
        rf"(?:\s+at)?\s+(?P<time>{_TIME_PATTERN})",
        value,
        flags=re.IGNORECASE,
    )
    if natural:
        day_text = natural.group("day").lower()
        if day_text == "today":
            target_date = local_now.date()
        elif day_text == "tomorrow":
            target_date = local_now.date() + timedelta(days=1)
        else:
            target_weekday = _WEEKDAYS[natural.group("weekday").lower()]
            days_ahead = (target_weekday - local_now.weekday()) % 7
            target_time = _parse_time(natural.group("time"))
            if natural.group("next"):
                days_ahead = days_ahead or 7
            elif days_ahead == 0 and target_time <= local_now.timetz().replace(tzinfo=None):
                days_ahead = 7
            target_date = local_now.date() + timedelta(days=days_ahead)
            return _validated_local_datetime(target_date, target_time, timezone)
        return _validated_local_datetime(target_date, _parse_time(natural.group("time")), timezone)

    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError("ambiguous due expression: ISO date is missing a time")
    if re.fullmatch(_TIME_PATTERN, value, flags=re.IGNORECASE):
        raise ValueError("ambiguous due expression: time is missing a date")
    if value.lower() in {"today", "tomorrow", *_WEEKDAYS.keys()} or re.fullmatch(
        rf"next\s+(?:{'|'.join(_WEEKDAYS)})", value, flags=re.IGNORECASE
    ):
        raise ValueError("ambiguous due expression: day is missing a time")
    raise ValueError(
        "ambiguous due expression; use an ISO date-time or today/tomorrow/weekday plus an exact time"
    )


def _parse_time(value: str) -> datetime_time:
    clean = re.sub(r"\s+", "", value.strip().lower())
    if clean.endswith(("am", "pm")):
        meridiem = clean[-2:]
        parts = clean[:-2].split(":")
        hour = int(parts[0]) % 12
        if meridiem == "pm":
            hour += 12
        minute = int(parts[1]) if len(parts) > 1 else 0
        return datetime_time(hour, minute)
    hour, minute = clean.split(":", 1)
    return datetime_time(int(hour), int(minute))


def _validated_local_datetime(target_date: date, target_time: datetime_time, timezone: tzinfo) -> datetime:
    candidate = datetime.combine(target_date, target_time, tzinfo=timezone)
    if datetime_exists is not None and not datetime_exists(candidate):
        raise ValueError("due time does not exist in the selected timezone because of daylight saving time")
    if datetime_ambiguous is not None and datetime_ambiguous(candidate):
        raise ValueError("due time is ambiguous in the selected timezone because of daylight saving time")
    # A stdlib-only fallback still detects nonexistent local wall times.
    round_trip = candidate.astimezone(UTC).astimezone(timezone)
    if round_trip.replace(tzinfo=None) != candidate.replace(tzinfo=None):
        raise ValueError("due time does not exist in the selected timezone because of daylight saving time")
    return candidate


def _task_key(
    title: str,
    due_at: datetime,
    timezone_name: str,
    kind: str,
    interval: int | None,
    payload: dict[str, Any],
) -> str:
    material = _json(
        {
            "title": title,
            "due_at": due_at.isoformat(),
            "timezone": timezone_name,
            "recurrence": {"kind": kind, "interval": interval},
            "payload": payload,
        }
    )
    return "prospective-task:" + hashlib.sha256(material.encode("utf-8")).hexdigest()


def _occurrence_dict(row: sqlite3.Row, *, now_timestamp: float | None = None) -> dict[str, Any]:
    scheduled = float(row["scheduled_at"])
    result = {
        "id": str(row["id"]),
        "task_id": str(row["task_id"]),
        "idempotency_key": str(row["idempotency_key"]),
        "scheduled_at": _iso(scheduled),
        "available_at": _iso(row["available_at"]),
        "status": str(row["status"]),
        "attempt_count": int(row["attempt_count"]),
        "lease_owner": row["lease_owner"],
        "lease_token": row["lease_token"],
        "lease_expires_at": _iso(row["lease_expires_at"]),
        "delivered_at": _iso(row["delivered_at"]),
        "result": _load_json(row["result_json"]),
        "last_error": row["last_error"],
    }
    keys = set(row.keys())
    if "title" in keys:
        result.update(
            {
                "title": str(row["title"]),
                "payload": _load_json(row["payload_json"]),
                "timezone": str(row["timezone"]),
                "recurrence": {
                    "kind": str(row["recurrence_kind"]),
                    "interval": int(row["recurrence_interval"] or 1),
                },
            }
        )
    if now_timestamp is not None:
        result["overdue_seconds"] = max(0.0, float(now_timestamp) - scheduled)
    return result


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _load_json(value: Any) -> dict[str, Any]:
    if not value:
        return {}
    try:
        parsed = json.loads(str(value))
        return parsed if isinstance(parsed, dict) else {}
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    return datetime.fromtimestamp(float(value), UTC).isoformat().replace("+00:00", "Z")
