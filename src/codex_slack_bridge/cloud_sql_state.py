from __future__ import annotations

"""PostgreSQL/Cloud SQL compatibility backend for the durable bridge state.

The existing BridgeState implementation intentionally uses a small SQLite API
surface. This adapter keeps that API intact while translating the SQLite-specific
bits that the state store needs to PostgreSQL, so the Cloud Run migration does
not require a risky rewrite of every state query at once.
"""

import os
import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from threading import RLock
from typing import Any, Iterator

import psycopg2
import psycopg2.errors

from .state import BridgeState


_PROCESS_MIGRATION_LOCK = RLock()
_PLACEHOLDER_RE = re.compile(r"\?")
_AUTOINCREMENT_RE = re.compile(
    r"INTEGER\s+PRIMARY\s+KEY\s+AUTOINCREMENT", re.IGNORECASE
)


class CloudSqlIntegrityError(sqlite3.IntegrityError):
    """Expose PostgreSQL uniqueness violations through the legacy SQLite API."""


class CloudSqlOperationalError(sqlite3.OperationalError):
    """Expose recoverable PostgreSQL DDL races through the legacy SQLite API."""


def cloud_sql_enabled() -> bool:
    return str(os.getenv("NOVA_DATABASE_BACKEND", "")).strip().lower() in {
        "cloudsql",
        "postgres",
        "postgresql",
    }


def _postgres_dsn() -> str:
    explicit = str(os.getenv("NOVA_DATABASE_DSN", "")).strip()
    if explicit:
        return explicit

    socket_path = str(os.getenv("NOVA_DB_SOCKET", "")).strip()
    host = socket_path or str(os.getenv("NOVA_DB_HOST", "")).strip() or "127.0.0.1"
    
    # When using Cloud SQL IAM auth, omit password from DSN entirely.
    # The Cloud SQL proxy handles auth via the service account's IAM token.
    # Only include password if explicitly provided AND not using IAM auth (no socket path).
    password = str(os.getenv("NOVA_DB_PASSWORD", "")).strip()
    use_iam_auth = bool(socket_path)  # socket path = Cloud SQL proxy = IAM auth
    
    params = {
        "dbname": str(os.getenv("NOVA_DB_NAME", "nova")),
        "user": str(os.getenv("NOVA_DB_USER", "postgres")),
        "host": host,
        "port": str(os.getenv("NOVA_DB_PORT", "5432")),
        "connect_timeout": str(os.getenv("NOVA_DB_CONNECT_TIMEOUT_SECONDS", "10")),
        "application_name": "codex-slack-bridge",
    }
    if password and not use_iam_auth:
        params["password"] = password
    
    return " ".join(f"{key}={value!r}" for key, value in params.items() if value != "")


def _translate_sql(sql: str) -> str:
    rendered = str(sql or "")
    compact = rendered.strip().lower()
    if compact.startswith("pragma "):
        return "SELECT 1 WHERE FALSE"
    if compact == "begin immediate":
        return "BEGIN"
    rendered = _AUTOINCREMENT_RE.sub("BIGSERIAL PRIMARY KEY", rendered)
    rendered = rendered.replace("INSERT OR IGNORE", "INSERT")
    rendered = _PLACEHOLDER_RE.sub("%s", rendered)
    if "INSERT INTO desktop_slack_mirrors" in rendered and "ON CONFLICT" not in rendered.upper():
        rendered = rendered.rstrip().rstrip(";") + " ON CONFLICT (event_id) DO NOTHING"
    return rendered


class CloudSqlCursor:
    def __init__(self, connection: "CloudSqlConnection", cursor: Any, *, synthetic_rows: list[tuple[Any, ...]] | None = None):
        self._connection = connection
        self._cursor = cursor
        self._synthetic_rows = synthetic_rows

    def fetchone(self) -> Any:
        if self._synthetic_rows is not None:
            if not self._synthetic_rows:
                return None
            return self._synthetic_rows.pop(0)
        return self._cursor.fetchone()

    def fetchall(self) -> list[Any]:
        if self._synthetic_rows is not None:
            rows = list(self._synthetic_rows)
            self._synthetic_rows.clear()
            return rows
        return list(self._cursor.fetchall())

    def __iter__(self):
        if self._synthetic_rows is not None:
            return iter(self._synthetic_rows)
        return iter(self._cursor)

    @property
    def rowcount(self) -> int:
        if self._synthetic_rows is not None:
            return len(self._synthetic_rows)
        return int(self._cursor.rowcount)

    @property
    def lastrowid(self) -> int | None:
        if self._synthetic_rows is not None:
            return None
        if not self._connection._last_insert_was_serial:
            return None
        with self._connection._raw.cursor() as cursor:
            cursor.execute("SELECT LASTVAL()")
            row = cursor.fetchone()
        return int(row[0]) if row else None

    def close(self) -> None:
        self._cursor.close()


class CloudSqlConnection:
    """Minimal sqlite3.Connection-like facade backed by psycopg2."""

    def __init__(self, raw: Any):
        self.raw = raw
        self._last_rowcount = 0
        self._last_insert_was_serial = False

    def execute(self, sql: str, parameters: Any = ()) -> CloudSqlCursor:
        compact = str(sql or "").strip().lower()
        if compact in {"pragma busy_timeout=5000", "pragma journal_mode=wal", "pragma foreign_keys=on"}:
            return CloudSqlCursor(self, self.raw.cursor(), synthetic_rows=[])
        if compact.startswith("pragma table_info("):
            table_name = str(compact.split("(", 1)[1].split(")", 1)[0]).strip("'\" ")
            cursor = self.raw.cursor()
            cursor.execute(
                """
                SELECT
                    ordinal_position - 1,
                    column_name,
                    data_type,
                    CASE WHEN is_nullable = 'NO' THEN 1 ELSE 0 END,
                    column_default,
                    CASE WHEN EXISTS (
                        SELECT 1
                        FROM information_schema.table_constraints tc
                        JOIN information_schema.key_column_usage kcu
                          ON kcu.constraint_name = tc.constraint_name
                         AND kcu.table_schema = tc.table_schema
                        WHERE tc.constraint_type = 'PRIMARY KEY'
                          AND tc.table_schema = current_schema()
                          AND tc.table_name = %s
                          AND kcu.column_name = c.column_name
                    ) THEN 1 ELSE 0 END
                FROM information_schema.columns c
                WHERE table_schema = current_schema() AND table_name = %s
                ORDER BY ordinal_position
                """,
                (table_name, table_name),
            )
            self._last_rowcount = cursor.rowcount
            return CloudSqlCursor(self, cursor)
        if compact.startswith("select changes()"):
            return CloudSqlCursor(self, self.raw.cursor(), synthetic_rows=[(self._last_rowcount,)])

        translated = _translate_sql(sql)
        cursor = self.raw.cursor()
        try:
            cursor.execute(translated, tuple(parameters or ()))
        except psycopg2.errors.UniqueViolation as exc:
            cursor.close()
            raise CloudSqlIntegrityError(str(exc)) from exc
        except (psycopg2.errors.DuplicateColumn, psycopg2.errors.DuplicateTable) as exc:
            cursor.close()
            raise CloudSqlOperationalError(str(exc)) from exc
        self._last_rowcount = max(0, int(cursor.rowcount))
        self._last_insert_was_serial = bool(translated.lstrip().lower().startswith("insert into jobs"))
        return CloudSqlCursor(self, cursor)

    def executescript(self, script: str) -> CloudSqlCursor:
        last: CloudSqlCursor | None = None
        for statement in str(script).split(";"):
            if statement.strip():
                last = self.execute(statement)
        if last is None:
            return CloudSqlCursor(self, self.raw.cursor(), synthetic_rows=[])
        return last

    def commit(self) -> None:
        self.raw.commit()

    def rollback(self) -> None:
        self.raw.rollback()

    def close(self) -> None:
        self.raw.close()


class CloudSqlBridgeState(BridgeState):
    """Drop-in BridgeState using Cloud SQL/PostgreSQL for durable state."""

    def __init__(self, _path: str = "") -> None:
        self.path = Path("/tmp/nova-cloudsql-state-placeholder")
        self._lock = RLock()
        with _PROCESS_MIGRATION_LOCK:
            self._init_db()

    @contextmanager
    def _connect(self) -> Iterator[CloudSqlConnection]:
        connection = None
        try:
            connection = psycopg2.connect(_postgres_dsn())
            connection.autocommit = False
            yield CloudSqlConnection(connection)
            connection.commit()
        except Exception:
            if connection is not None:
                connection.rollback()
            raise
        finally:
            if connection is not None:
                connection.close()

    @staticmethod
    def _ensure_jobs_column(db: CloudSqlConnection, name: str, column_type: str) -> None:
        columns = {str(row[1]) for row in db.execute("PRAGMA table_info(jobs)").fetchall()}
        if name not in columns:
            try:
                db.execute(f"ALTER TABLE jobs ADD COLUMN {name} {column_type}")
            except CloudSqlOperationalError:
                refreshed = {str(row[1]) for row in db.execute("PRAGMA table_info(jobs)").fetchall()}
                if name not in refreshed:
                    raise


def build_cloud_sql_state(path: str) -> BridgeState:
    if cloud_sql_enabled():
        return CloudSqlBridgeState(path)
    return BridgeState(path)
