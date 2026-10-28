from __future__ import annotations

# AgentChat/direct_codex 2026-07-13T18:45:00-04:00: require explicit review routing for terminal outcomes.
# AgentChat/direct_codex 2026-07-14T14:45:00-04:00: retain audit history when policy resolves a stale review.
# AgentChat/direct_codex 2026-07-27T22:55:00Z: persist terminal Slack feedback until delivery is confirmed.

import sqlite3
import json
import re
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from threading import Lock
from typing import Any

# AgentChat/direct_codex 2026-07-13T00:16:00-04:00: fence stale workers and persist recovery metadata.
# AgentChat/coding_agent 2026-07-13T00:52:00-04:00: expose authoritative job rows for command-center projection repair.
# AgentChat/coding_agent 2026-07-13T12:05:00-04:00: baseline Needs Review without importing historical terminal jobs.
# AgentChat/coding_agent 2026-07-30T17:15:00Z: requeue recoverable worker attempts without clearing idempotency history.


ACTIVE_JOB_STATUSES = {"queued", "running"}
REVIEW_REQUIRED_JOB_STATUSES = {
    "blocked",
    "completed_with_issues",
    "failed",
    "interrupted",
    "recovery_review_required",
    "unclassified",
}
RECONCILIATION_TERMINAL_STATUSES = {
    "blocked",
    "cancelled",
    "completed",
    "completed_with_issues",
    "failed",
    "interrupted",
    "recovery_review_required",
    "superseded",
    "unclassified",
}
ACTIVE_REQUEST_PREFIX_MIN_CHARS = 48
ACTIVE_REQUEST_PREFIX_MIN_TOKENS = 8
ACTIVE_REQUEST_PREFIX_MIN_RATIO = 0.80


def normalize_active_request(text: str) -> str:
    """Normalize operator text for a narrow active-job duplicate check."""
    return " ".join(re.sub(r"[^a-z0-9]+", " ", str(text or "").casefold()).split())


def active_requests_equivalent(left: str, right: str) -> bool:
    """Match exact or near-identical prefix requests without collapsing distinct work."""
    normalized_left = normalize_active_request(left)
    normalized_right = normalize_active_request(right)
    if not normalized_left or not normalized_right:
        return False
    if normalized_left == normalized_right:
        return True
    shorter, longer = sorted((normalized_left, normalized_right), key=len)
    if len(shorter) < ACTIVE_REQUEST_PREFIX_MIN_CHARS:
        return False
    if len(shorter.split()) < ACTIVE_REQUEST_PREFIX_MIN_TOKENS:
        return False
    if len(shorter) / len(longer) < ACTIVE_REQUEST_PREFIX_MIN_RATIO:
        return False
    return longer.startswith(shorter + " ")


class BridgeState:
    def __init__(self, path: str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()
        self._init_db()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path)
        connection.execute("PRAGMA busy_timeout=5000")
        connection.execute("PRAGMA journal_mode=WAL")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _init_db(self) -> None:
        with self._connect() as db:
            # Slack and Command Center can start together against this file.
            # Serialize schema inspection/ALTER work at the database boundary.
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS slack_events (
                    event_id TEXT PRIMARY KEY,
                    received_at REAL NOT NULL
                )
                """
            )
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT,
                    channel_id TEXT NOT NULL,
                    thread_ts TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    agent_name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    request_text TEXT NOT NULL,
                    error TEXT,
                    created_at REAL NOT NULL,
                    started_at REAL,
                    completed_at REAL
                )
                """
            )
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS slack_messages (
                    channel_id TEXT NOT NULL,
                    message_ts TEXT NOT NULL,
                    received_at REAL NOT NULL,
                    PRIMARY KEY(channel_id, message_ts)
                )
                """
            )
            # AgentChat/coding_agent 2026-07-09T00:52:46Z: dedupe desktop-to-Slack mirror posts.
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS desktop_slack_mirrors (
                    event_id TEXT PRIMARY KEY,
                    channel_id TEXT NOT NULL,
                    message_ts TEXT,
                    mirrored_at REAL NOT NULL
                )
                """
            )
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS state_migrations (
                    name TEXT PRIMARY KEY,
                    applied_at REAL NOT NULL
                )
                """
            )
            self._ensure_jobs_column(db, "reconciled_at", "REAL")
            self._ensure_jobs_column(db, "reconciliation_reason", "TEXT")
            self._ensure_jobs_column(db, "runtime_instance_id", "TEXT")
            self._ensure_jobs_column(db, "runtime_stage", "TEXT")
            self._ensure_jobs_column(db, "stage_updated_at", "REAL")
            self._ensure_jobs_column(db, "heartbeat_at", "REAL")
            self._ensure_jobs_column(db, "recovery_policy", "TEXT")
            self._ensure_jobs_column(db, "recovery_count", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_jobs_column(db, "result_text", "TEXT")
            self._ensure_jobs_column(db, "needs_review", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_jobs_column(db, "review_reason", "TEXT")
            self._ensure_jobs_column(db, "reviewed_at", "REAL")
            self._ensure_jobs_column(db, "review_resolution", "TEXT")
            self._ensure_jobs_column(db, "learning_eligible", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_jobs_column(db, "review_version", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_jobs_column(db, "review_status", "TEXT")
            self._ensure_jobs_column(db, "last_followup_job_id", "INTEGER")
            self._ensure_jobs_column(db, "last_followup_result", "TEXT")
            self._ensure_jobs_column(db, "review_updated_at", "REAL")
            self._ensure_jobs_column(db, "active_followup_job_id", "INTEGER")
            self._ensure_jobs_column(db, "delivery_status", "TEXT NOT NULL DEFAULT 'delivered'")
            self._ensure_jobs_column(db, "delivery_attempts", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_jobs_column(db, "delivery_last_error", "TEXT")
            self._ensure_jobs_column(db, "delivered_at", "REAL")
            self._ensure_jobs_column(db, "usage_json", "TEXT")
            delivery_migration = "slack_terminal_delivery_outbox_v1"
            if db.execute(
                "SELECT 1 FROM state_migrations WHERE name = ?",
                (delivery_migration,),
            ).fetchone() is None:
                # Historical terminal rows predate delivery tracking and must not
                # be replayed. Active work is the only legacy state that can still
                # become terminal without having produced a final Slack response.
                db.execute(
                    """
                    UPDATE jobs
                    SET delivery_status = CASE
                            WHEN lower(status) IN ('queued', 'running') THEN 'pending'
                            ELSE 'delivered'
                        END,
                        delivered_at = CASE
                            WHEN lower(status) IN ('queued', 'running') THEN NULL
                            ELSE COALESCE(delivered_at, completed_at, created_at)
                        END
                    """
                )
                db.execute(
                    "INSERT INTO state_migrations(name, applied_at) VALUES (?, ?)",
                    (delivery_migration, time.time()),
                )
            db.execute(
                """
                UPDATE jobs
                SET needs_review = 1,
                    review_reason = COALESCE(NULLIF(review_reason, ''), error, reconciliation_reason, status),
                    review_status = COALESCE(NULLIF(review_status, ''), 'needs_review'),
                    review_updated_at = COALESCE(review_updated_at, completed_at, created_at),
                    learning_eligible = 0
                WHERE lower(status) IN ('interrupted', 'recovery_review_required')
                  AND reviewed_at IS NULL
                """
            )
            migration_name = "needs_review_live_baseline_v1"
            already_baselined = db.execute(
                "SELECT 1 FROM state_migrations WHERE name = ?",
                (migration_name,),
            ).fetchone()
            if already_baselined is None:
                now = time.time()
                db.execute(
                    """
                    UPDATE jobs
                    SET needs_review = 0,
                        reviewed_at = COALESCE(reviewed_at, ?),
                        review_resolution = CASE
                            WHEN COALESCE(review_resolution, '') = ''
                            THEN 'Historical terminal job predates Needs Review activation; administratively baselined without changing its outcome.'
                            ELSE review_resolution
                        END,
                        review_status = 'resolved',
                        review_updated_at = ?,
                        active_followup_job_id = NULL
                    WHERE needs_review = 1 AND reviewed_at IS NULL
                    """,
                    (now, now),
                )
                db.execute(
                    "INSERT INTO state_migrations(name, applied_at) VALUES (?, ?)",
                    (migration_name, now),
                )

    @staticmethod
    def _ensure_jobs_column(db: sqlite3.Connection, name: str, column_type: str) -> None:
        columns = {str(row[1]) for row in db.execute("PRAGMA table_info(jobs)").fetchall()}
        if name not in columns:
            try:
                db.execute(f"ALTER TABLE jobs ADD COLUMN {name} {column_type}")
            except sqlite3.OperationalError:
                # Defensive rolling-start fallback if another process completed
                # the identical migration just before this transaction acquired.
                refreshed = {str(row[1]) for row in db.execute("PRAGMA table_info(jobs)").fetchall()}
                if name not in refreshed:
                    raise

    def record_event_once(self, event_id: str | None) -> bool:
        if not event_id:
            return True
        with self._lock, self._connect() as db:
            try:
                db.execute(
                    "INSERT INTO slack_events(event_id, received_at) VALUES (?, ?)",
                    (event_id, time.time()),
                )
                return True
            except sqlite3.IntegrityError:
                return False

    def create_job(
        self,
        *,
        event_id: str | None,
        channel_id: str,
        thread_ts: str,
        user_id: str,
        agent_name: str,
        request_text: str,
        recovery_policy: str = "",
    ) -> int:
        job_id, _existing = self.create_job_unless_active_equivalent(
            event_id=event_id,
            channel_id=channel_id,
            thread_ts=thread_ts,
            user_id=user_id,
            agent_name=agent_name,
            request_text=request_text,
            recovery_policy=recovery_policy,
            guard_equivalent=False,
        )
        return job_id

    def create_job_unless_active_equivalent(
        self,
        *,
        event_id: str | None,
        channel_id: str,
        thread_ts: str,
        user_id: str,
        agent_name: str,
        request_text: str,
        recovery_policy: str = "",
        guard_equivalent: bool = True,
    ) -> tuple[int, dict[str, object] | None]:
        """Atomically reject a same-user request equivalent to queued/running work."""
        with self._lock, self._connect() as db:
            if guard_equivalent and str(user_id or "").strip():
                rows = db.execute(
                    """
                    SELECT id, channel_id, agent_name, status, request_text
                    FROM jobs
                    WHERE user_id = ? AND lower(status) IN ('queued', 'running')
                    ORDER BY created_at DESC, id DESC
                    """,
                    (str(user_id),),
                ).fetchall()
                for row in rows:
                    if active_requests_equivalent(request_text, str(row[4] or "")):
                        existing = {
                            "id": int(row[0]),
                            "channel_id": str(row[1] or ""),
                            "agent_name": str(row[2] or ""),
                            "status": str(row[3] or ""),
                            "request_text": str(row[4] or ""),
                        }
                        return int(row[0]), existing
            cursor = db.execute(
                """
                INSERT INTO jobs(
                    event_id, channel_id, thread_ts, user_id, agent_name,
                    status, request_text, created_at, recovery_policy, delivery_status
                )
                VALUES (?, ?, ?, ?, ?, 'queued', ?, ?, ?, 'pending')
                """,
                (
                    event_id,
                    channel_id,
                    thread_ts,
                    user_id,
                    agent_name,
                    request_text,
                    time.time(),
                    str(recovery_policy or "")[:80],
                ),
            )
            return int(cursor.lastrowid), None

    def list_pending_terminal_deliveries(self, *, limit: int = 100) -> list[dict[str, object]]:
        """Return terminal Slack jobs whose final feedback is not confirmed delivered."""

        terminal = tuple(sorted(RECONCILIATION_TERMINAL_STATUSES))
        placeholders = ",".join("?" for _ in terminal)
        with self._lock, self._connect() as db:
            rows = db.execute(
                f"""
                SELECT id, channel_id, thread_ts, user_id, agent_name, status,
                       result_text, error, reconciliation_reason, delivery_attempts
                FROM jobs
                WHERE channel_id != 'command_center'
                  AND lower(status) IN ({placeholders})
                  AND lower(COALESCE(delivery_status, 'pending')) != 'delivered'
                ORDER BY COALESCE(completed_at, created_at), id
                LIMIT ?
                """,
                (*terminal, max(1, min(int(limit or 100), 500))),
            ).fetchall()
        return [
            {
                "id": int(row[0]),
                "channel_id": str(row[1] or ""),
                "thread_ts": str(row[2] or ""),
                "user_id": str(row[3] or ""),
                "agent_name": str(row[4] or ""),
                "status": str(row[5] or ""),
                "result_text": str(row[6] or ""),
                "error": str(row[7] or ""),
                "reconciliation_reason": str(row[8] or ""),
                "delivery_attempts": int(row[9] or 0),
            }
            for row in rows
        ]

    def mark_delivery_succeeded(self, job_id: int) -> None:
        with self._lock, self._connect() as db:
            db.execute(
                """
                UPDATE jobs
                SET delivery_status = 'delivered', delivered_at = ?,
                    delivery_last_error = ''
                WHERE id = ?
                """,
                (time.time(), int(job_id)),
            )

    def mark_delivery_pending(self, job_id: int) -> None:
        """Queue fresh terminal feedback without counting a delivery failure."""

        with self._lock, self._connect() as db:
            db.execute(
                """
                UPDATE jobs
                SET delivery_status = 'pending', delivered_at = NULL,
                    delivery_last_error = ''
                WHERE id = ?
                """,
                (int(job_id),),
            )

    def mark_delivery_failed(self, job_id: int, error: str) -> None:
        with self._lock, self._connect() as db:
            db.execute(
                """
                UPDATE jobs
                SET delivery_status = 'pending',
                    delivery_attempts = COALESCE(delivery_attempts, 0) + 1,
                    delivery_last_error = ?
                WHERE id = ?
                """,
                (str(error or "Slack delivery failed")[:1000], int(job_id)),
            )

    def record_message_once(self, channel_id: str | None, message_ts: str | None) -> bool:
        if not channel_id or not message_ts:
            return True
        with self._lock, self._connect() as db:
            try:
                db.execute(
                    """
                    INSERT INTO slack_messages(channel_id, message_ts, received_at)
                    VALUES (?, ?, ?)
                    """,
                    (channel_id, message_ts, time.time()),
                )
                return True
            except sqlite3.IntegrityError:
                return False

    def has_desktop_slack_mirror(self, event_id: str | None) -> bool:
        if not event_id:
            return False
        with self._lock, self._connect() as db:
            row = db.execute(
                "SELECT 1 FROM desktop_slack_mirrors WHERE event_id = ?",
                (event_id,),
            ).fetchone()
            return row is not None

    def record_desktop_slack_mirror(
        self,
        event_id: str | None,
        channel_id: str,
        message_ts: str | None,
    ) -> None:
        if not event_id:
            return
        with self._lock, self._connect() as db:
            db.execute(
                """
                INSERT OR IGNORE INTO desktop_slack_mirrors(
                    event_id, channel_id, message_ts, mirrored_at
                )
                VALUES (?, ?, ?, ?)
                """,
                (event_id, channel_id, message_ts, time.time()),
            )

    def mark_started(self, job_id: int, *, runtime_instance_id: str = "", stage: str = "running") -> bool:
        now = time.time()
        with self._lock, self._connect() as db:
            db.execute(
                """
                UPDATE jobs
                SET status = 'running', started_at = ?, runtime_instance_id = ?,
                    runtime_stage = ?, stage_updated_at = ?, heartbeat_at = ?
                WHERE id = ? AND lower(status) = 'queued'
                """,
                (now, str(runtime_instance_id or "")[:120], str(stage or "running")[:120], now, now, job_id),
            )
            return bool(db.execute("SELECT changes()").fetchone()[0])

    def mark_completed(self, job_id: int, *, runtime_instance_id: str = "") -> bool:
        return self.mark_outcome(
            job_id,
            "completed",
            runtime_instance_id=runtime_instance_id,
            learning_eligible=False,
        )

    def mark_outcome(
        self,
        job_id: int,
        status: str,
        *,
        result_text: str = "",
        review_reason: str = "",
        runtime_instance_id: str = "",
        learning_eligible: bool = False,
        review_required: bool | None = None,
    ) -> bool:
        """Persist a typed business outcome without collapsing review states.

        Only an explicit ``completed`` outcome may be learning eligible. Terminal
        outcomes enter Needs Review only when the caller explicitly requests it;
        ordinary failures stay on their originating chat/status surface.
        """

        normalized = str(status or "").strip().lower()
        allowed = {"completed", "completed_with_issues", "blocked", "failed", "unclassified"}
        if normalized not in allowed:
            raise ValueError(f"Unsupported agent outcome status: {status}")
        # A failed execution is not an operator decision. Keep its original
        # request/result on the job and originating conversation instead of
        # projecting it into a context-losing review task.
        needs_review = bool(review_required) and normalized != "failed"
        eligible = bool(learning_eligible and normalized == "completed")
        now = time.time()
        where = "id = ? AND lower(status) = 'running'"
        values: list[object] = [
            normalized,
            now,
            now,
            normalized,
            str(result_text or "")[:12000],
            int(needs_review),
            str(review_reason or "")[:2000] if needs_review else "",
            int(eligible),
            job_id,
        ]
        if runtime_instance_id:
            where += " AND runtime_instance_id = ?"
            values.append(str(runtime_instance_id)[:120])
        with self._lock, self._connect() as db:
            db.execute(
                f"""
                UPDATE jobs
                SET status = ?, completed_at = ?, heartbeat_at = ?, runtime_stage = ?,
                    result_text = ?, needs_review = ?, review_reason = ?,
                    reviewed_at = NULL, review_resolution = '', learning_eligible = ?,
                    review_status = ?, review_updated_at = ?, review_version = 0,
                    last_followup_job_id = NULL, last_followup_result = '',
                    active_followup_job_id = NULL
                WHERE {where}
                """,
                [
                    *values[:8],
                    "needs_review" if needs_review else "",
                    now if needs_review else None,
                    *values[8:],
                ],
            )
            return bool(db.execute("SELECT changes()").fetchone()[0])

    def update_job_usage(self, job_id: int, usage: dict | None) -> None:
        """Persist exact token/cost metadata on the job record.

        usage is stored as a JSON blob in the usage_json column. Empty or
        missing metadata is ignored so ordinary relay runs (which may not
        expose exact usage) leave the field null rather than fabricating data.
        """
        if not job_id or not usage:
            return
        with self._lock, self._connect() as db:
            db.execute(
                "UPDATE jobs SET usage_json = ? WHERE id = ?",
                (json.dumps(usage, ensure_ascii=True, default=str)[:12000], int(job_id)),
            )

    def get_job_usage(self, job_id: int) -> dict:
        """Return the persisted usage metadata dict for a job (empty if none)."""
        try:
            with self._lock, self._connect() as db:
                row = db.execute(
                    "SELECT usage_json FROM jobs WHERE id = ?", (int(job_id),)
                ).fetchone()
        except Exception:
            return {}
        if not row or not row[0]:
            return {}
        try:
            value = json.loads(row[0])
        except (json.JSONDecodeError, TypeError):
            return {}
        return value if isinstance(value, dict) else {}

    def mark_failed(
        self,
        job_id: int,
        error: str,
        *,
        runtime_instance_id: str = "",
        review_required: bool = False,
    ) -> bool:
        # Failed workers remain visible on their original job/chat surface.
        # Needs Review is reserved for blocked work and explicit decisions.
        needs_review = False
        now = time.time()
        where = "id = ? AND lower(status) IN ('queued', 'running')"
        params: list[object] = [
            error[:2000],
            now,
            now,
            "failed",
            str(error or "")[:12000],
            int(needs_review),
            error[:2000] if needs_review else "",
            "needs_review" if needs_review else "",
            now if needs_review else None,
            job_id,
        ]
        if runtime_instance_id:
            where += " AND (runtime_instance_id = ? OR runtime_instance_id IS NULL OR runtime_instance_id = '')"
            params.append(str(runtime_instance_id)[:120])
        with self._lock, self._connect() as db:
            db.execute(
                f"""
                UPDATE jobs
                SET status = 'failed', error = ?, completed_at = ?,
                    heartbeat_at = ?, runtime_stage = ?, result_text = ?,
                    needs_review = ?, review_reason = ?, reviewed_at = NULL,
                    review_resolution = '', learning_eligible = 0,
                    review_status = ?, review_updated_at = ?,
                    review_version = 0, last_followup_job_id = NULL,
                    last_followup_result = '', active_followup_job_id = NULL
                WHERE {where}
                """,
                params,
            )
            return bool(db.execute("SELECT changes()").fetchone()[0])

    def mark_review_resolved(
        self,
        job_id: int,
        *,
        resolution: str = "",
        expected_review_version: int | None = None,
        expected_active_child_id: int | None = None,
    ) -> bool:
        """Close a review obligation while retaining the original outcome audit."""

        now = time.time()
        clean_resolution = str(resolution or "")[:2000]
        clauses: list[str] = []
        params: list[object] = [now, clean_resolution, now, job_id]
        if expected_review_version is not None:
            clauses.append("COALESCE(review_version, 0) = ?")
            params.append(max(0, int(expected_review_version)))
        if expected_active_child_id is not None:
            clauses.append("(active_followup_job_id = ? OR active_followup_job_id IS NULL)")
            params.append(int(expected_active_child_id))
        extra_where = "" if not clauses else " AND " + " AND ".join(clauses)
        with self._lock, self._connect() as db:
            db.execute(
                f"""
                UPDATE jobs
                SET needs_review = 0, reviewed_at = ?,
                    review_resolution = ?, review_status = 'resolved',
                    review_updated_at = ?, active_followup_job_id = NULL
                WHERE id = ? AND needs_review = 1
                  {extra_where}
                """,
                params,
            )
            return bool(db.execute("SELECT changes()").fetchone()[0])

    def mark_review_followup_queued(
        self,
        job_id: int,
        child_job_id: int,
        *,
        expected_review_version: int | None = None,
    ) -> bool:
        """Link one active follow-up attempt to an open parent review."""

        now = time.time()
        version_clause = ""
        params: list[object] = [now, int(child_job_id), int(job_id)]
        if expected_review_version is not None:
            version_clause = " AND COALESCE(review_version, 0) = ?"
            params.append(max(0, int(expected_review_version)))
        with self._lock, self._connect() as db:
            db.execute(
                f"""
                UPDATE jobs
                SET review_status = 'followup_queued', review_updated_at = ?,
                    active_followup_job_id = ?
                WHERE id = ? AND needs_review = 1 AND reviewed_at IS NULL
                  AND (
                    active_followup_job_id IS NULL
                    OR active_followup_job_id = ?
                    OR NOT EXISTS (
                        SELECT 1 FROM jobs AS active_child
                        WHERE active_child.id = jobs.active_followup_job_id
                          AND lower(active_child.status) IN ('queued', 'running')
                    )
                  )
                  {version_clause}
                """,
                [*params[:3], int(child_job_id), *params[3:]],
            )
            return bool(db.execute("SELECT changes()").fetchone()[0])

    def record_review_followup(
        self,
        job_id: int,
        *,
        child_job_id: int,
        child_status: str,
        result_text: str,
        ready_to_resolve: bool = False,
        expected_review_version: int | None = None,
    ) -> bool:
        """Merge a child attempt into its parent review without losing history."""

        now = time.time()
        review_status = "ready_to_resolve" if ready_to_resolve else "needs_review"
        version_clause = ""
        params: list[object] = [
            review_status,
            now,
            int(child_job_id),
            str(result_text or "")[:12000],
            str(child_status or "").strip().lower(),
            str(result_text or "")[:2000],
            int(job_id),
            int(child_job_id),
        ]
        if expected_review_version is not None:
            version_clause = " AND COALESCE(review_version, 0) = ?"
            params.append(max(0, int(expected_review_version)))
        with self._lock, self._connect() as db:
            db.execute(
                f"""
                UPDATE jobs
                SET review_version = COALESCE(review_version, 0) + 1,
                    review_status = ?, review_updated_at = ?,
                    last_followup_job_id = ?, last_followup_result = ?,
                    active_followup_job_id = NULL,
                    review_reason = CASE
                        WHEN ? = 'completed' THEN review_reason
                        ELSE COALESCE(NULLIF(?, ''), review_reason)
                    END
                WHERE id = ? AND needs_review = 1 AND reviewed_at IS NULL
                  AND (active_followup_job_id = ? OR active_followup_job_id IS NULL)
                  {version_clause}
                """,
                params,
            )
            return bool(db.execute("SELECT changes()").fetchone()[0])

    def reclassify_completed_outcome(
        self,
        job_id: int,
        status: str,
        *,
        result_text: str = "",
        review_reason: str = "",
        review_required: bool = True,
    ) -> bool:
        """Correct a legacy outcome while retaining any resolved review audit."""

        normalized = str(status or "").strip().lower()
        if normalized not in {"blocked", "completed_with_issues", "failed"}:
            raise ValueError(f"Unsupported legacy outcome correction: {status}")
        needs_review = bool(review_required) and normalized != "failed"
        now = time.time()
        with self._lock, self._connect() as db:
            existing = db.execute(
                "SELECT needs_review FROM jobs WHERE id = ? AND lower(status) IN ('completed', ?)",
                (job_id, normalized),
            ).fetchone()
            had_review = bool(existing and existing[0])
            resolved_by_policy = had_review and not needs_review
            reviewed_at = now if resolved_by_policy else None
            review_resolution = (
                "Automatically resolved: the durable result is not eligible for Needs Review under the current policy."
                if resolved_by_policy
                else ""
            )
            review_status = "resolved" if resolved_by_policy else ("needs_review" if needs_review else "")
            review_updated_at = now if (resolved_by_policy or needs_review) else None
            db.execute(
                """
                UPDATE jobs
                SET status = ?, runtime_stage = ?, result_text = ?, needs_review = ?,
                    review_reason = ?, reviewed_at = ?, review_resolution = ?,
                    learning_eligible = 0, reconciled_at = ?,
                    reconciliation_reason = 'Reclassified from durable agent outcome text.',
                    review_status = ?, review_updated_at = ?,
                    review_version = 0, last_followup_job_id = NULL,
                    last_followup_result = '', active_followup_job_id = NULL
                WHERE id = ? AND lower(status) IN ('completed', ?)
                """,
                (
                    normalized,
                    normalized,
                    str(result_text or "")[:12000],
                    int(needs_review),
                    str(review_reason or normalized)[:2000] if needs_review else "",
                    reviewed_at,
                    review_resolution,
                    now,
                    review_status,
                    review_updated_at,
                    job_id,
                    normalized,
                ),
            )
            return bool(db.execute("SELECT changes()").fetchone()[0])

    def list_review_jobs(self, *, limit: int = 200, offset: int = 0) -> list[dict[str, object]]:
        """Return unresolved business outcomes in newest-first follow-up order."""

        limit = max(1, min(int(limit or 200), 1000))
        offset = max(0, int(offset or 0))
        with self._lock, self._connect() as db:
            rows = db.execute(
                """
                SELECT
                    id, event_id, channel_id, thread_ts, user_id, agent_name,
                    status, request_text, error, created_at, started_at, completed_at,
                    reconciled_at, reconciliation_reason, runtime_instance_id,
                    runtime_stage, stage_updated_at, heartbeat_at, recovery_policy,
                    recovery_count, result_text, needs_review, review_reason,
                    reviewed_at, learning_eligible, review_resolution,
                    review_version, review_status, last_followup_job_id,
                    last_followup_result, review_updated_at, active_followup_job_id,
                    COALESCE((
                        SELECT lower(child.status) FROM jobs AS child
                        WHERE child.id = jobs.active_followup_job_id
                    ), ''),
                    COALESCE((
                        SELECT child.agent_name FROM jobs AS child
                        WHERE child.id = jobs.active_followup_job_id
                    ), ''),
                    COALESCE((
                        SELECT child.agent_name FROM jobs AS child
                        WHERE child.id = jobs.last_followup_job_id
                    ), '')
                FROM jobs
                WHERE needs_review = 1 AND reviewed_at IS NULL
                ORDER BY completed_at DESC, created_at DESC
                LIMIT ? OFFSET ?
                """,
                (limit, offset),
            ).fetchall()
        return [_job_row_dict(row) for row in rows]

    def update_runtime_stage(
        self,
        job_id: int,
        stage: str,
        *,
        runtime_instance_id: str = "",
        heartbeat: bool = True,
    ) -> bool:
        now = time.time()
        fields = ["runtime_stage = ?", "stage_updated_at = ?"]
        values: list[object] = [str(stage or "")[:120], now]
        if heartbeat:
            fields.append("heartbeat_at = ?")
            values.append(now)
        where = "id = ? AND lower(status) IN ('queued', 'running')"
        values.append(job_id)
        if runtime_instance_id:
            where += " AND (runtime_instance_id = ? OR runtime_instance_id IS NULL OR runtime_instance_id = '')"
            values.append(str(runtime_instance_id)[:120])
        with self._lock, self._connect() as db:
            db.execute(f"UPDATE jobs SET {', '.join(fields)} WHERE {where}", values)
            return bool(db.execute("SELECT changes()").fetchone()[0])

    def heartbeat_job(self, job_id: int, *, runtime_instance_id: str = "") -> bool:
        values: list[object] = [time.time(), job_id]
        where = "id = ? AND lower(status) = 'running'"
        if runtime_instance_id:
            where += " AND runtime_instance_id = ?"
            values.append(str(runtime_instance_id)[:120])
        with self._lock, self._connect() as db:
            db.execute(f"UPDATE jobs SET heartbeat_at = ? WHERE {where}", values)
            return bool(db.execute("SELECT changes()").fetchone()[0])

    def requeue_for_recovery(
        self,
        job_id: int,
        reason: str,
        *,
        recovery_policy: str = "same_surface_readback_first",
        runtime_instance_id: str = "",
    ) -> bool:
        """Fence a lost attempt and retain the same durable obligation for recovery."""

        now = time.time()
        clean_reason = str(reason or "Recoverable worker interruption.")[:2000]
        where = "id = ? AND lower(status) IN ('queued', 'running')"
        values: list[object] = [
            clean_reason,
            str(recovery_policy or "same_surface_readback_first")[:80],
            now,
            now,
            job_id,
        ]
        if runtime_instance_id:
            where += " AND (runtime_instance_id = ? OR runtime_instance_id IS NULL OR runtime_instance_id = '')"
            values.append(str(runtime_instance_id)[:120])
        with self._lock, self._connect() as db:
            db.execute(
                f"""
                UPDATE jobs
                SET status = 'queued', started_at = NULL, completed_at = NULL,
                    reconciled_at = ?, reconciliation_reason = ?,
                    runtime_instance_id = '', runtime_stage = 'recovery_queued',
                    stage_updated_at = ?, heartbeat_at = ?,
                    recovery_policy = ?, recovery_count = COALESCE(recovery_count, 0) + 1,
                    error = '', result_text = '', needs_review = 0,
                    review_reason = '', reviewed_at = NULL, review_resolution = '',
                    learning_eligible = 0, review_status = '', review_updated_at = NULL,
                    active_followup_job_id = NULL
                WHERE {where}
                """,
                [
                    now,
                    clean_reason,
                    now,
                    now,
                    str(recovery_policy or "same_surface_readback_first")[:80],
                    job_id,
                    *values[5:],
                ],
            )
            return bool(db.execute("SELECT changes()").fetchone()[0])

    def mark_superseded(self, job_id: int, reason: str = "Superseded by newer queued work.") -> None:
        self._mark_reconciled_terminal(job_id, "superseded", reason)

    def mark_interrupted(self, job_id: int, reason: str = "Runtime ended before the job reported completion.") -> None:
        self._mark_reconciled_terminal(job_id, "interrupted", reason)

    def mark_cancelled(self, job_id: int, reason: str = "Operator cancelled the job before model execution.") -> None:
        """Close a never-started/operator-cancelled attempt without opening review."""

        self._mark_reconciled_terminal(job_id, "cancelled", reason)

    def mark_recovery_review_required(
        self,
        job_id: int,
        reason: str = "Interrupted work may have crossed an external write boundary; verify before replay.",
    ) -> None:
        self._mark_reconciled_terminal(job_id, "recovery_review_required", reason)

    def reconcile_active_jobs(
        self,
        *,
        live_job_ids: set[int] | None,
        terminal_statuses: dict[int, str] | None = None,
        protected_job_ids: set[int] | None = None,
        recovery_review_job_ids: set[int] | None = None,
        channel_id: str | None = None,
        stale_after_seconds: float = 300,
        authoritative: bool = False,
        now: float | None = None,
        reasons: dict[int, str] | None = None,
    ) -> dict[str, Any]:
        """Reconcile the durable ledger against an authoritative runtime snapshot.

        Explicit terminal evidence is always safe to apply. Absence is only treated
        as evidence when ``authoritative`` is true and ``live_job_ids`` was supplied;
        this prevents a partial status reader from killing legitimate work.
        """

        observed_at = float(now if now is not None else time.time())
        live_ids = {int(value) for value in (live_job_ids or set())}
        protected_ids = {int(value) for value in (protected_job_ids or set())}
        review_ids = {int(value) for value in (recovery_review_job_ids or set())}
        reason_by_id = {int(key): str(value) for key, value in (reasons or {}).items()}
        explicit_terminal: dict[int, str] = {}
        for raw_id, raw_status in (terminal_statuses or {}).items():
            status = str(raw_status or "").strip().lower()
            if status in RECONCILIATION_TERMINAL_STATUSES:
                explicit_terminal[int(raw_id)] = status

        where = "WHERE lower(status) IN ('queued', 'running')"
        params: list[object] = []
        if channel_id is not None:
            where += " AND channel_id = ?"
            params.append(str(channel_id))

        changed: list[dict[str, Any]] = []
        retained: list[int] = []
        deferred: list[int] = []
        with self._lock, self._connect() as db:
            rows = db.execute(
                f"SELECT id, status, created_at, started_at FROM jobs {where} ORDER BY id",
                params,
            ).fetchall()
            for raw_id, raw_status, created_at, started_at in rows:
                job_id = int(raw_id)
                old_status = str(raw_status or "").lower()
                new_status = explicit_terminal.get(job_id)
                reason = reason_by_id.get(job_id, "")

                if job_id in review_ids:
                    new_status = "recovery_review_required"
                    reason = reason or "Interrupted work requires write-boundary verification before replay."
                elif new_status is not None:
                    reason = reason or f"Runtime job record reported terminal status {new_status}."
                elif job_id in live_ids or job_id in protected_ids:
                    retained.append(job_id)
                    continue
                elif not authoritative or live_job_ids is None:
                    deferred.append(job_id)
                    continue
                else:
                    basis = float(started_at or created_at or observed_at)
                    age = max(0.0, observed_at - basis)
                    if age < max(0.0, float(stale_after_seconds)):
                        deferred.append(job_id)
                        continue
                    if old_status == "running":
                        new_status = "interrupted"
                        reason = reason or "No live scheduler, process lock, recovery, or recent session evidence remained."
                    else:
                        new_status = "superseded"
                        reason = reason or "Queued job was absent from the authoritative scheduler snapshot."

                db.execute(
                    """
                    UPDATE jobs
                    SET status = ?, completed_at = ?,
                        reconciled_at = ?, reconciliation_reason = ?,
                        runtime_stage = ?, heartbeat_at = ?,
                        recovery_count = COALESCE(recovery_count, 0) + 1,
                        needs_review = ?, review_reason = ?, learning_eligible = 0,
                        review_status = ?, review_updated_at = ?,
                        active_followup_job_id = NULL
                    WHERE id = ? AND lower(status) IN ('queued', 'running')
                    """,
                    (
                        new_status,
                        observed_at,
                        observed_at,
                        reason[:2000],
                        new_status,
                        observed_at,
                        int(new_status in REVIEW_REQUIRED_JOB_STATUSES),
                        reason[:2000] if new_status in REVIEW_REQUIRED_JOB_STATUSES else "",
                        "needs_review" if new_status in REVIEW_REQUIRED_JOB_STATUSES else "",
                        observed_at if new_status in REVIEW_REQUIRED_JOB_STATUSES else None,
                        job_id,
                    ),
                )
                if db.execute("SELECT changes()").fetchone()[0]:
                    changed.append({"id": job_id, "from": old_status, "to": new_status, "reason": reason})

        return {
            "authoritative": bool(authoritative and live_job_ids is not None),
            "changed": changed,
            "retainedJobIds": retained,
            "deferredJobIds": deferred,
            "observedAt": observed_at,
        }

    def _mark_reconciled_terminal(self, job_id: int, status: str, reason: str) -> None:
        normalized = str(status or "").strip().lower()
        if normalized not in RECONCILIATION_TERMINAL_STATUSES:
            raise ValueError(f"Unsupported terminal job status: {status}")
        now = time.time()
        clean_reason = str(reason or "")[:2000]
        with self._lock, self._connect() as db:
            db.execute(
                """
                UPDATE jobs
                SET status = ?, completed_at = ?,
                    reconciled_at = ?, reconciliation_reason = ?,
                    runtime_stage = ?, heartbeat_at = ?, recovery_count = COALESCE(recovery_count, 0) + 1,
                    needs_review = ?, review_reason = ?, learning_eligible = 0
                    , review_status = ?, review_updated_at = ?, active_followup_job_id = NULL
                WHERE id = ? AND lower(status) IN ('queued', 'running')
                """,
                (
                    normalized,
                    now,
                    now,
                    clean_reason,
                    normalized,
                    now,
                    int(normalized in REVIEW_REQUIRED_JOB_STATUSES),
                    clean_reason if normalized in REVIEW_REQUIRED_JOB_STATUSES else "",
                    "needs_review" if normalized in REVIEW_REQUIRED_JOB_STATUSES else "",
                    now if normalized in REVIEW_REQUIRED_JOB_STATUSES else None,
                    job_id,
                ),
            )

    def list_jobs(self, *, statuses: set[str] | None = None, limit: int = 50) -> list[dict[str, object]]:
        limit = max(1, min(int(limit or 50), 500))
        where = ""
        params: list[object] = []
        if statuses:
            clean_statuses = sorted(str(status).strip().lower() for status in statuses if str(status).strip())
            if clean_statuses:
                placeholders = ", ".join("?" for _ in clean_statuses)
                where = f"WHERE lower(status) IN ({placeholders})"
                params.extend(clean_statuses)
        params.append(limit)
        with self._lock, self._connect() as db:
            rows = db.execute(
                f"""
                SELECT
                    id, event_id, channel_id, thread_ts, user_id, agent_name,
                    status, request_text, error, created_at, started_at, completed_at,
                    reconciled_at, reconciliation_reason, runtime_instance_id,
                    runtime_stage, stage_updated_at, heartbeat_at, recovery_policy,
                    recovery_count, result_text, needs_review, review_reason,
                    reviewed_at, learning_eligible, review_resolution,
                    review_version, review_status, last_followup_job_id,
                    last_followup_result, review_updated_at, active_followup_job_id,
                    COALESCE((
                        SELECT lower(child.status) FROM jobs AS child
                        WHERE child.id = jobs.active_followup_job_id
                    ), ''),
                    COALESCE((
                        SELECT child.agent_name FROM jobs AS child
                        WHERE child.id = jobs.active_followup_job_id
                    ), ''),
                    COALESCE((
                        SELECT child.agent_name FROM jobs AS child
                        WHERE child.id = jobs.last_followup_job_id
                    ), '')
                FROM jobs
                {where}
                ORDER BY created_at DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [_job_row_dict(row) for row in rows]

    def jobs_by_ids(self, job_ids: set[int]) -> dict[int, dict[str, object]]:
        """Read selected durable jobs in bounded batches for projection repair."""
        pending = sorted({int(job_id) for job_id in job_ids if int(job_id) > 0})
        if not pending:
            return {}
        answer: dict[int, dict[str, object]] = {}
        with self._lock, self._connect() as db:
            for offset in range(0, len(pending), 400):
                batch = pending[offset : offset + 400]
                placeholders = ", ".join("?" for _ in batch)
                rows = db.execute(
                    f"""
                    SELECT
                        id, event_id, channel_id, thread_ts, user_id, agent_name,
                        status, request_text, error, created_at, started_at, completed_at,
                        reconciled_at, reconciliation_reason, runtime_instance_id,
                        runtime_stage, stage_updated_at, heartbeat_at, recovery_policy,
                        recovery_count, result_text, needs_review, review_reason,
                        reviewed_at, learning_eligible, review_resolution,
                        review_version, review_status, last_followup_job_id,
                        last_followup_result, review_updated_at, active_followup_job_id,
                        COALESCE((
                            SELECT lower(child.status) FROM jobs AS child
                            WHERE child.id = jobs.active_followup_job_id
                        ), ''),
                        COALESCE((
                            SELECT child.agent_name FROM jobs AS child
                            WHERE child.id = jobs.active_followup_job_id
                        ), ''),
                        COALESCE((
                            SELECT child.agent_name FROM jobs AS child
                            WHERE child.id = jobs.last_followup_job_id
                        ), '')
                    FROM jobs
                    WHERE id IN ({placeholders})
                    """,
                    batch,
                ).fetchall()
                for row in rows:
                    answer[int(row[0])] = _job_row_dict(row)
        return answer

    def job_by_event_id(self, event_id: str) -> dict[str, object] | None:
        """Read one exact durable job by its external command-center ID."""

        clean_event_id = str(event_id or "").strip()
        if not clean_event_id:
            return None
        with self._lock, self._connect() as db:
            row = db.execute(
                "SELECT id FROM jobs WHERE event_id = ? LIMIT 1",
                (clean_event_id,),
            ).fetchone()
        if row is None:
            return None
        return self.jobs_by_ids({int(row[0])}).get(int(row[0]))

    def active_channel_ids(self, *, exclude: set[str] | None = None) -> list[str]:
        excluded = {str(value) for value in (exclude or set())}
        with self._lock, self._connect() as db:
            rows = db.execute(
                "SELECT DISTINCT channel_id FROM jobs WHERE lower(status) IN ('queued', 'running') ORDER BY channel_id"
            ).fetchall()
        return [str(row[0]) for row in rows if str(row[0]) not in excluded]

    def job_counts(self) -> dict[str, int]:
        with self._lock, self._connect() as db:
            rows = db.execute(
                """
                SELECT lower(status), COUNT(*)
                FROM jobs
                GROUP BY lower(status)
                """
            ).fetchall()
        return {str(status or "unknown"): int(count) for status, count in rows}

    def _mark_terminal_owned(self, job_id: int, status: str, *, runtime_instance_id: str = "") -> bool:
        now = time.time()
        where = "id = ? AND lower(status) = 'running'"
        values: list[object] = [status, now, now, status, job_id]
        if runtime_instance_id:
            where += " AND runtime_instance_id = ?"
            values.append(str(runtime_instance_id)[:120])
        with self._lock, self._connect() as db:
            db.execute(
                f"""
                UPDATE jobs
                SET status = ?, completed_at = ?, heartbeat_at = ?, runtime_stage = ?
                WHERE {where}
                """,
                values,
            )
            return bool(db.execute("SELECT changes()").fetchone()[0])


def _job_row_dict(row: sqlite3.Row | tuple[object, ...]) -> dict[str, object]:
    return {
        "id": row[0],
        "event_id": row[1],
        "channel_id": row[2],
        "thread_ts": row[3],
        "user_id": row[4],
        "agent_name": row[5],
        "status": row[6],
        "request_text": row[7],
        "error": row[8],
        "created_at": row[9],
        "started_at": row[10],
        "completed_at": row[11],
        "reconciled_at": row[12],
        "reconciliation_reason": row[13],
        "runtime_instance_id": row[14],
        "runtime_stage": row[15],
        "stage_updated_at": row[16],
        "heartbeat_at": row[17],
        "recovery_policy": row[18],
        "recovery_count": row[19],
        "result_text": row[20] or "",
        "needs_review": bool(row[21]),
        "review_reason": row[22] or "",
        "reviewed_at": row[23],
        "learning_eligible": bool(row[24]),
        "review_resolution": row[25] or "",
        "review_version": int(row[26] or 0),
        "review_status": row[27] or "",
        "last_followup_job_id": row[28],
        "last_followup_result": row[29] or "",
        "review_updated_at": row[30],
        "active_followup_job_id": row[31],
        "active_followup_status": row[32] or "",
        "active_followup_agent": row[33] or "",
        "last_followup_agent": row[34] or "",
    }
