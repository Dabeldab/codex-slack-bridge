from __future__ import annotations

import json
import sqlite3
import time
import uuid
from pathlib import Path
from threading import RLock
from typing import Any, Mapping, Sequence

# AgentChat/coding_agent 2026-07-14T12:20:00-04:00: support lightweight operator reminders alongside strict agent briefs.
# AgentChat/direct_codex 2026-07-14T17:58:31-04:00: support backward workflow movement and visible agent work products.


STATUSES = {
    "drawing",
    "ready",
    "in_progress",
    "waiting",
    "evidence_required",
    "verified_complete",
    "archived",
}
PRIORITIES = {"low", "normal", "high", "urgent"}
ACTIVE_STATUSES = {"ready", "in_progress", "waiting", "evidence_required"}
NON_TASK_SOURCE_TYPES = {
    "agent_failure",
    "agent_status",
    "background_status",
    "blocker",
    "failure",
    "healthcheck",
    "job_failure",
    "job_status",
    "monitor",
    "monitoring",
    "runtime_failure",
    "status",
    "status_telemetry",
    "telemetry",
    "watcher",
}
NON_TASK_KINDS = NON_TASK_SOURCE_TYPES | {
    "diagnostic",
    "error",
    "incident_update",
    "progress_update",
    "system_event",
}
GENERIC_BRIEF_TEXT = {
    "assign this",
    "do this",
    "figure it out",
    "fix it",
    "follow up",
    "handle it",
    "handle this",
    "investigate",
    "look into it",
    "review",
    "send to agent",
    "send to alex",
    "send to jamie",
    "send to taylor",
    "take a look",
}


class DrawingBoardStore:
    """Durable commitments and evidence-backed completion tracking."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA busy_timeout=5000")
        return db

    def _init_db(self) -> None:
        with self._lock, self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS drawing_board_tasks (
                    id TEXT PRIMARY KEY,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'drawing',
                    priority TEXT NOT NULL DEFAULT 'normal',
                    owner TEXT NOT NULL DEFAULT '',
                    agent_name TEXT NOT NULL DEFAULT '',
                    operator_owned INTEGER NOT NULL DEFAULT 0,
                    requester TEXT NOT NULL DEFAULT '',
                    due_at REAL,
                    source_type TEXT NOT NULL DEFAULT '',
                    source_url TEXT NOT NULL DEFAULT '',
                    source_id TEXT NOT NULL DEFAULT '',
                    source_thread_id TEXT NOT NULL DEFAULT '',
                    waiting_on TEXT NOT NULL DEFAULT '',
                    next_action TEXT NOT NULL DEFAULT '',
                    requested_outcome TEXT NOT NULL DEFAULT '',
                    assignee_action TEXT NOT NULL DEFAULT '',
                    completion_criteria TEXT NOT NULL DEFAULT '',
                    evidence_json TEXT NOT NULL DEFAULT '[]',
                    checklist_json TEXT NOT NULL DEFAULT '[]',
                    recurrence TEXT NOT NULL DEFAULT '',
                    tags_json TEXT NOT NULL DEFAULT '[]',
                    confidence REAL NOT NULL DEFAULT 1.0,
                    human_verified INTEGER NOT NULL DEFAULT 0,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    completed_at REAL
                );
                CREATE INDEX IF NOT EXISTS idx_drawing_board_status_priority
                    ON drawing_board_tasks(status, priority, updated_at DESC);
                CREATE INDEX IF NOT EXISTS idx_drawing_board_due
                    ON drawing_board_tasks(due_at, status);

                CREATE TABLE IF NOT EXISTS drawing_board_events (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT NOT NULL UNIQUE,
                    task_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    details_json TEXT NOT NULL DEFAULT '{}',
                    created_at REAL NOT NULL,
                    FOREIGN KEY(task_id) REFERENCES drawing_board_tasks(id)
                );
                CREATE INDEX IF NOT EXISTS idx_drawing_board_events_task
                    ON drawing_board_events(task_id, sequence);

                CREATE TABLE IF NOT EXISTS drawing_board_sources (
                    id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    source_kind TEXT NOT NULL,
                    source_id TEXT NOT NULL DEFAULT '',
                    source_url TEXT NOT NULL DEFAULT '',
                    source_title TEXT NOT NULL DEFAULT '',
                    excerpt TEXT NOT NULL DEFAULT '',
                    occurred_at REAL,
                    created_at REAL NOT NULL,
                    UNIQUE(task_id, source_kind, source_id, source_url),
                    FOREIGN KEY(task_id) REFERENCES drawing_board_tasks(id)
                );

                CREATE TABLE IF NOT EXISTS drawing_board_evidence (
                    id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    evidence_kind TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    source_url TEXT NOT NULL DEFAULT '',
                    external_id TEXT NOT NULL DEFAULT '',
                    verified INTEGER NOT NULL DEFAULT 0,
                    created_by TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    FOREIGN KEY(task_id) REFERENCES drawing_board_tasks(id)
                );
                CREATE INDEX IF NOT EXISTS idx_drawing_board_evidence_task
                    ON drawing_board_evidence(task_id, created_at);

                CREATE TABLE IF NOT EXISTS drawing_board_dispatches (
                    task_id TEXT NOT NULL,
                    job_key TEXT NOT NULL,
                    bridge_job_id INTEGER NOT NULL,
                    agent_name TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    PRIMARY KEY(task_id, job_key),
                    FOREIGN KEY(task_id) REFERENCES drawing_board_tasks(id)
                );
                """
            )
            self._ensure_task_columns(db)
            self._reconcile_legacy_actionability(db)

    @staticmethod
    def _ensure_task_columns(db: sqlite3.Connection) -> None:
        columns = {
            str(row["name"])
            for row in db.execute("PRAGMA table_info(drawing_board_tasks)").fetchall()
        }
        for column in ("requested_outcome", "assignee_action", "completion_criteria"):
            if column not in columns:
                db.execute(
                    f"ALTER TABLE drawing_board_tasks ADD COLUMN {column} TEXT NOT NULL DEFAULT ''"
                )
        if "operator_owned" not in columns:
            db.execute(
                "ALTER TABLE drawing_board_tasks ADD COLUMN operator_owned INTEGER NOT NULL DEFAULT 0"
            )

    def _reconcile_legacy_actionability(self, db: sqlite3.Connection) -> None:
        """Demote legacy active cards that cannot explain executable work."""

        rows = db.execute(
            "SELECT * FROM drawing_board_tasks WHERE status IN ('ready', 'in_progress', 'waiting', 'evidence_required')"
        ).fetchall()
        now = time.time()
        for row in rows:
            task = _decode(row)
            task["sources"] = [
                dict(source)
                for source in db.execute(
                    "SELECT * FROM drawing_board_sources WHERE task_id=?", (task["id"],)
                ).fetchall()
            ]
            task["evidence_records"] = [
                dict(evidence)
                for evidence in db.execute(
                    "SELECT * FROM drawing_board_evidence WHERE task_id=?", (task["id"],)
                ).fetchall()
            ]
            actionability = drawing_task_actionability(task)
            if actionability["actionable"]:
                continue
            target = "archived" if drawing_payload_is_telemetry(task) else "drawing"
            db.execute(
                "UPDATE drawing_board_tasks SET status=?, completed_at=NULL, updated_at=? WHERE id=?",
                (target, now, task["id"]),
            )
            self._event(
                db,
                task["id"],
                "actionability_demoted",
                "drawing_board_migration",
                {
                    "from_status": task["status"],
                    "to_status": target,
                    "missing": actionability["missing_actionability_fields"],
                },
                now,
            )

    def create(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        if drawing_payload_is_telemetry(payload):
            raise ValueError(
                "Drawing Board tasks must be support or business requests, not failures, blockers, or status telemetry"
            )
        title = str(payload.get("title") or "").strip()
        if not title:
            raise ValueError("title is required")
        status = _status(payload.get("status", "drawing"))
        priority = _priority(payload.get("priority", "normal"))
        key = str(payload.get("idempotency_key") or payload.get("idempotencyKey") or "").strip()
        if not key:
            key = f"drawing-board:{uuid.uuid5(uuid.NAMESPACE_URL, title.casefold())}"
        task_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"drawing-board-task:{key}"))
        now = time.time()
        values = {
            "description": _short(payload.get("description"), 12000),
            "owner": _short(payload.get("owner"), 300),
            "agent_name": _short(payload.get("agent_name") or payload.get("agentName"), 200),
            "operator_owned": 1 if bool(payload.get("operator_owned") or payload.get("operatorOwned")) else 0,
            "requester": _short(payload.get("requester"), 300),
            "due_at": _timestamp(payload.get("due_at") or payload.get("dueAt")),
            "source_type": _short(payload.get("source_type") or payload.get("sourceType"), 200),
            "source_url": _short(payload.get("source_url") or payload.get("sourceUrl"), 2000),
            "source_id": _short(payload.get("source_id") or payload.get("sourceId"), 500),
            "source_thread_id": _short(payload.get("source_thread_id") or payload.get("sourceThreadId"), 500),
            "waiting_on": _short(payload.get("waiting_on") or payload.get("waitingOn"), 500),
            "next_action": _short(payload.get("next_action") or payload.get("nextAction"), 4000),
            "requested_outcome": _short(
                payload.get("requested_outcome") or payload.get("requestedOutcome"), 4000
            ),
            "assignee_action": _short(
                payload.get("assignee_action") or payload.get("assigneeAction"), 4000
            ),
            "completion_criteria": _short(
                payload.get("completion_criteria") or payload.get("completionCriteria"), 4000
            ),
            "evidence_json": _json_list(payload.get("evidence")),
            "checklist_json": _json_list(payload.get("checklist")),
            "recurrence": _short(payload.get("recurrence"), 300),
            "tags_json": _json_list(payload.get("tags")),
            "confidence": _confidence(payload.get("confidence", 1.0)),
            "human_verified": 1 if bool(payload.get("human_verified") or payload.get("humanVerified")) else 0,
        }
        candidate = {
            "title": title[:1000],
            "status": status,
            **values,
            "evidence": json.loads(values["evidence_json"]),
            "checklist": json.loads(values["checklist_json"]),
        }
        _require_single_ownership_mode(candidate)
        if status in ACTIVE_STATUSES:
            _require_actionable_task(candidate)
        with self._lock, self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute(
                "SELECT * FROM drawing_board_tasks WHERE idempotency_key=?", (key,)
            ).fetchone()
            if existing is not None:
                db.commit()
                return self._enrich(_decode(existing))
            db.execute(
                """
                INSERT INTO drawing_board_tasks(
                    id, idempotency_key, title, description, status, priority,
                    owner, agent_name, operator_owned, requester, due_at, source_type, source_url,
                    source_id, source_thread_id, waiting_on, next_action,
                    requested_outcome, assignee_action, completion_criteria,
                    evidence_json, checklist_json, recurrence, tags_json,
                    confidence, human_verified, created_at, updated_at, completed_at
                ) VALUES (
                    :id, :idempotency_key, :title, :description, :status, :priority,
                    :owner, :agent_name, :operator_owned, :requester, :due_at, :source_type, :source_url,
                    :source_id, :source_thread_id, :waiting_on, :next_action,
                    :requested_outcome, :assignee_action, :completion_criteria,
                    :evidence_json, :checklist_json, :recurrence, :tags_json,
                    :confidence, :human_verified, :created_at, :updated_at, NULL
                )
                """,
                {
                    "id": task_id,
                    "idempotency_key": key,
                    "title": title[:1000],
                    "status": status,
                    "priority": priority,
                    "created_at": now,
                    "updated_at": now,
                    **values,
                },
            )
            self._event(db, task_id, "created", str(payload.get("actor") or "operator"), values, now)
            self._insert_source(
                db,
                task_id,
                {
                    "source_kind": values["source_type"],
                    "source_id": values["source_id"],
                    "source_url": values["source_url"],
                    "source_title": title,
                    "excerpt": values["description"][:1000],
                },
                now,
            )
            row = db.execute("SELECT * FROM drawing_board_tasks WHERE id=?", (task_id,)).fetchone()
            db.commit()
        assert row is not None
        return self._enrich(_decode(row))

    def get(self, task_id: str) -> dict[str, Any] | None:
        with self._connect() as db:
            row = db.execute("SELECT * FROM drawing_board_tasks WHERE id=?", (str(task_id),)).fetchone()
        return self._enrich(_decode(row)) if row is not None else None

    def list_tasks(
        self,
        *,
        statuses: Sequence[str] | None = None,
        agent_name: str = "",
        include_archived: bool = False,
        limit: int = 250,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        values: list[Any] = []
        if statuses:
            clean = [_status(item) for item in statuses]
            clauses.append("status IN (%s)" % ",".join("?" for _ in clean))
            values.extend(clean)
        elif not include_archived:
            clauses.append("status != 'archived'")
        if agent_name:
            clauses.append("agent_name=?")
            values.append(agent_name)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        values.append(max(1, min(int(limit), 1000)))
        with self._connect() as db:
            rows = db.execute(
                f"""
                SELECT * FROM drawing_board_tasks {where}
                ORDER BY
                    CASE priority WHEN 'urgent' THEN 0 WHEN 'high' THEN 1 WHEN 'normal' THEN 2 ELSE 3 END,
                    CASE WHEN due_at IS NULL THEN 1 ELSE 0 END, due_at, updated_at DESC
                LIMIT ?
                """,
                values,
            ).fetchall()
        return [self._enrich(_decode(row)) for row in rows]

    def update(self, task_id: str, changes: Mapping[str, Any], *, actor: str = "operator") -> dict[str, Any]:
        allowed = {
            "title": ("title", lambda value: _required(value, "title", 1000)),
            "description": ("description", lambda value: _short(value, 12000)),
            "status": ("status", _status),
            "priority": ("priority", _priority),
            "owner": ("owner", lambda value: _short(value, 300)),
            "requester": ("requester", lambda value: _short(value, 300)),
            "agent_name": ("agent_name", lambda value: _short(value, 200)),
            "agentName": ("agent_name", lambda value: _short(value, 200)),
            "operator_owned": ("operator_owned", lambda value: 1 if bool(value) else 0),
            "operatorOwned": ("operator_owned", lambda value: 1 if bool(value) else 0),
            "due_at": ("due_at", _timestamp),
            "dueAt": ("due_at", _timestamp),
            "waiting_on": ("waiting_on", lambda value: _short(value, 500)),
            "waitingOn": ("waiting_on", lambda value: _short(value, 500)),
            "next_action": ("next_action", lambda value: _short(value, 4000)),
            "nextAction": ("next_action", lambda value: _short(value, 4000)),
            "requested_outcome": ("requested_outcome", lambda value: _short(value, 4000)),
            "requestedOutcome": ("requested_outcome", lambda value: _short(value, 4000)),
            "assignee_action": ("assignee_action", lambda value: _short(value, 4000)),
            "assigneeAction": ("assignee_action", lambda value: _short(value, 4000)),
            "completion_criteria": ("completion_criteria", lambda value: _short(value, 4000)),
            "completionCriteria": ("completion_criteria", lambda value: _short(value, 4000)),
            "source_type": ("source_type", lambda value: _short(value, 200)),
            "sourceType": ("source_type", lambda value: _short(value, 200)),
            "source_url": ("source_url", lambda value: _short(value, 2000)),
            "sourceUrl": ("source_url", lambda value: _short(value, 2000)),
            "source_id": ("source_id", lambda value: _short(value, 500)),
            "sourceId": ("source_id", lambda value: _short(value, 500)),
            "source_thread_id": ("source_thread_id", lambda value: _short(value, 500)),
            "sourceThreadId": ("source_thread_id", lambda value: _short(value, 500)),
            "evidence": ("evidence_json", _json_list),
            "checklist": ("checklist_json", _json_list),
            "recurrence": ("recurrence", lambda value: _short(value, 300)),
            "tags": ("tags_json", _json_list),
            "confidence": ("confidence", _confidence),
            "human_verified": ("human_verified", lambda value: 1 if bool(value) else 0),
            "humanVerified": ("human_verified", lambda value: 1 if bool(value) else 0),
        }
        updates: dict[str, Any] = {}
        for key, value in changes.items():
            if key in allowed:
                column, transform = allowed[key]
                updates[column] = transform(value)
        if not updates:
            raise ValueError("No supported task fields were supplied")
        if updates.get("status") == "verified_complete" and not (
            updates.get("human_verified") or changes.get("evidence")
        ):
            raise ValueError("verified completion requires evidence or human verification")
        now = time.time()
        updates["updated_at"] = now
        if updates.get("status") == "verified_complete":
            updates["completed_at"] = now
        elif "status" in updates:
            updates["completed_at"] = None
            updates["human_verified"] = 0
        assignment = ", ".join(f"{column}=?" for column in updates)
        with self._lock, self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute(
                "SELECT * FROM drawing_board_tasks WHERE id=?", (task_id,)
            ).fetchone()
            if existing is None:
                raise KeyError(task_id)
            candidate = _decode(existing)
            candidate["sources"] = [
                dict(source)
                for source in db.execute(
                    "SELECT * FROM drawing_board_sources WHERE task_id=?", (task_id,)
                ).fetchall()
            ]
            candidate["evidence_records"] = [
                dict(evidence)
                for evidence in db.execute(
                    "SELECT * FROM drawing_board_evidence WHERE task_id=?", (task_id,)
                ).fetchall()
            ]
            for column, value in updates.items():
                if column == "evidence_json":
                    candidate["evidence"] = json.loads(str(value) or "[]")
                elif column == "checklist_json":
                    candidate["checklist"] = json.loads(str(value) or "[]")
                else:
                    candidate[column] = value
            if drawing_payload_is_telemetry(candidate):
                raise ValueError(
                    "Drawing Board tasks must be support or business requests, not failures, blockers, or status telemetry"
                )
            _require_single_ownership_mode(candidate)
            if candidate.get("status") in ACTIVE_STATUSES:
                _require_actionable_task(candidate)
            db.execute(
                f"UPDATE drawing_board_tasks SET {assignment} WHERE id=?",
                [*updates.values(), task_id],
            )
            if {"source_type", "source_id", "source_url", "source_thread_id"}.intersection(updates):
                self._insert_source(
                    db,
                    task_id,
                    {
                        "source_kind": candidate.get("source_type"),
                        "source_id": candidate.get("source_id"),
                        "source_url": candidate.get("source_url"),
                        "source_title": candidate.get("title"),
                        "excerpt": candidate.get("description"),
                    },
                    now,
                )
            self._event(db, task_id, "updated", actor, updates, now)
            row = db.execute("SELECT * FROM drawing_board_tasks WHERE id=?", (task_id,)).fetchone()
            db.commit()
        assert row is not None
        return self._enrich(_decode(row))

    def add_source(self, task_id: str, source: Mapping[str, Any], *, actor: str = "operator") -> dict[str, Any]:
        now = time.time()
        with self._lock, self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM drawing_board_tasks WHERE id=?", (task_id,)).fetchone() is None:
                raise KeyError(task_id)
            self._insert_source(db, task_id, source, now)
            db.execute("UPDATE drawing_board_tasks SET updated_at=? WHERE id=?", (now, task_id))
            self._event(db, task_id, "source_added", actor, dict(source), now)
            db.commit()
        result = self.get(task_id)
        assert result is not None
        return result

    def add_evidence(
        self,
        task_id: str,
        *,
        summary: str,
        evidence_kind: str = "agent_report",
        source_url: str = "",
        external_id: str = "",
        verified: bool = False,
        advance_to_review: bool = False,
        created_by: str = "agent",
    ) -> dict[str, Any]:
        clean_summary = _required(summary, "summary", 12000)
        now = time.time()
        evidence_id = str(uuid.uuid4())
        with self._lock, self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            task_row = db.execute(
                "SELECT * FROM drawing_board_tasks WHERE id=?", (task_id,)
            ).fetchone()
            if task_row is None:
                raise KeyError(task_id)
            db.execute(
                """
                INSERT INTO drawing_board_evidence(
                    id, task_id, evidence_kind, summary, source_url, external_id,
                    verified, created_by, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    evidence_id,
                    task_id,
                    _short(evidence_kind, 200),
                    clean_summary,
                    _short(source_url, 2000),
                    _short(external_id, 500),
                    1 if verified else 0,
                    _short(created_by, 300),
                    now,
                ),
            )
            current_status = str(task_row["status"] or "drawing")
            target_status = current_status
            completed_at = task_row["completed_at"]
            if verified:
                target_status = "verified_complete"
                completed_at = now
            elif advance_to_review and current_status == "in_progress":
                candidate = _decode(task_row)
                candidate["evidence_records"] = [{"summary": clean_summary}]
                candidate["sources"] = [
                    dict(source)
                    for source in db.execute(
                        "SELECT * FROM drawing_board_sources WHERE task_id=?", (task_id,)
                    ).fetchall()
                ]
                _require_actionable_task(candidate)
                target_status = "waiting"
                completed_at = None
            db.execute(
                "UPDATE drawing_board_tasks SET status=?, updated_at=?, completed_at=? WHERE id=?",
                (target_status, now, completed_at, task_id),
            )
            self._event(
                db,
                task_id,
                "evidence_added",
                created_by,
                {
                    "evidence_id": evidence_id,
                    "verified": verified,
                    "review_ready": bool(advance_to_review and target_status == "waiting"),
                    "kind": evidence_kind,
                },
                now,
            )
            db.commit()
        result = self.get(task_id)
        assert result is not None
        return result

    def has_evidence_external_id(self, external_id: str, *, evidence_kind: str = "") -> bool:
        clean_external_id = _short(external_id, 500)
        if not clean_external_id:
            return False
        query = "SELECT 1 FROM drawing_board_evidence WHERE external_id=?"
        values: list[Any] = [clean_external_id]
        if evidence_kind:
            query += " AND evidence_kind=?"
            values.append(_short(evidence_kind, 200))
        with self._connect() as db:
            return db.execute(query, values).fetchone() is not None

    def record_dispatch(
        self,
        task_id: str,
        *,
        job_key: str,
        bridge_job_id: int,
        agent_name: str,
    ) -> None:
        now = time.time()
        with self._lock, self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            task_row = db.execute(
                "SELECT * FROM drawing_board_tasks WHERE id=?", (task_id,)
            ).fetchone()
            if task_row is None:
                raise KeyError(task_id)
            if db.execute(
                "SELECT 1 FROM drawing_board_dispatches WHERE task_id=? AND job_key=?",
                (task_id, job_key),
            ).fetchone() is not None:
                db.commit()
                return
            task = _decode(task_row)
            task["sources"] = [
                dict(source)
                for source in db.execute(
                    "SELECT * FROM drawing_board_sources WHERE task_id=?", (task_id,)
                ).fetchall()
            ]
            task["evidence_records"] = [
                dict(evidence)
                for evidence in db.execute(
                    "SELECT * FROM drawing_board_evidence WHERE task_id=?", (task_id,)
                ).fetchall()
            ]
            if task["status"] != "ready":
                raise ValueError("Drawing Board task must be ready before dispatch")
            _require_actionable_task(task)
            if _short(agent_name, 200) != task.get("agent_name"):
                raise ValueError("Dispatch agent must match the actionable brief assignee")
            db.execute(
                "INSERT OR IGNORE INTO drawing_board_dispatches VALUES (?, ?, ?, ?, ?)",
                (task_id, job_key, int(bridge_job_id), agent_name, now),
            )
            db.execute(
                "UPDATE drawing_board_tasks SET status='in_progress', agent_name=?, updated_at=? WHERE id=?",
                (agent_name, now, task_id),
            )
            self._event(
                db,
                task_id,
                "dispatched",
                agent_name,
                {"job_key": job_key, "bridge_job_id": bridge_job_id},
                now,
            )
            db.commit()

    def history(self, task_id: str) -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM drawing_board_events WHERE task_id=? ORDER BY sequence", (task_id,)
            ).fetchall()
        return [
            {**dict(row), "details": json.loads(str(row["details_json"]) or "{}")}
            for row in rows
        ]

    def _enrich(self, item: dict[str, Any]) -> dict[str, Any]:
        with self._connect() as db:
            sources = db.execute(
                "SELECT * FROM drawing_board_sources WHERE task_id=? ORDER BY created_at", (item["id"],)
            ).fetchall()
            evidence = db.execute(
                "SELECT * FROM drawing_board_evidence WHERE task_id=? ORDER BY created_at", (item["id"],)
            ).fetchall()
            dispatches = db.execute(
                "SELECT * FROM drawing_board_dispatches WHERE task_id=? ORDER BY created_at", (item["id"],)
            ).fetchall()
        item["sources"] = [dict(row) for row in sources]
        item["evidence_records"] = [
            {**dict(row), "verified": bool(row["verified"])} for row in evidence
        ]
        item["dispatches"] = [dict(row) for row in dispatches]
        item.update(drawing_task_actionability(item))
        return item

    @staticmethod
    def _insert_source(
        db: sqlite3.Connection,
        task_id: str,
        source: Mapping[str, Any],
        now: float,
    ) -> None:
        source_kind = _short(source.get("source_kind") or source.get("sourceKind"), 200)
        source_id = _short(source.get("source_id") or source.get("sourceId"), 500)
        source_url = _short(source.get("source_url") or source.get("sourceUrl"), 2000)
        if not (source_kind or source_id or source_url):
            return
        db.execute(
            """
            INSERT OR IGNORE INTO drawing_board_sources(
                id, task_id, source_kind, source_id, source_url, source_title,
                excerpt, occurred_at, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid.uuid4()),
                task_id,
                source_kind,
                source_id,
                source_url,
                _short(source.get("source_title") or source.get("sourceTitle"), 1000),
                _short(source.get("excerpt"), 4000),
                _timestamp(source.get("occurred_at") or source.get("occurredAt")),
                now,
            ),
        )

    def brief(self, *, now: float | None = None) -> dict[str, Any]:
        observed = time.time() if now is None else float(now)
        tasks = self.list_tasks(limit=500)
        active = [
            task
            for task in tasks
            if task["status"] in ACTIVE_STATUSES and task.get("actionable") is True
        ]
        drafts = [task for task in tasks if task["status"] == "drawing"]
        due_soon = [
            task for task in active
            if task["due_at_timestamp"] is not None
            and float(task["due_at_timestamp"]) <= observed + 86400
        ]
        stale = [task for task in active if observed - float(task["updated_at_timestamp"]) >= 2 * 86400]
        return {
            "counts": {
                "active": len(active),
                "drafts": len(drafts),
                "due_soon": len(due_soon),
                "stale": len(stale),
                "waiting": sum(task["status"] == "waiting" for task in active),
                "evidence_required": sum(task["status"] == "evidence_required" for task in active),
                "verified_complete": sum(task["status"] == "verified_complete" for task in tasks),
            },
            "due_soon": due_soon[:10],
            "stale": stale[:10],
            "active": active[:25],
            "drafts": drafts[:25],
        }

    @staticmethod
    def _event(
        db: sqlite3.Connection,
        task_id: str,
        action: str,
        actor: str,
        details: Mapping[str, Any],
        created_at: float,
    ) -> None:
        db.execute(
            "INSERT INTO drawing_board_events(event_id, task_id, action, actor, details_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (str(uuid.uuid4()), task_id, action, actor[:300], json.dumps(dict(details), default=str), created_at),
        )


def _decode(row: sqlite3.Row) -> dict[str, Any]:
    item = dict(row)
    item["evidence"] = json.loads(item.pop("evidence_json") or "[]")
    item["checklist"] = json.loads(item.pop("checklist_json") or "[]")
    item["tags"] = json.loads(item.pop("tags_json") or "[]")
    item["human_verified"] = bool(item["human_verified"])
    item["operator_owned"] = bool(item.get("operator_owned"))
    for key in ("due_at", "created_at", "updated_at", "completed_at"):
        timestamp = item.get(key)
        item[f"{key}_timestamp"] = timestamp
        item[key] = _iso(timestamp)
    return item


def drawing_task_actionability(task: Mapping[str, Any]) -> dict[str, Any]:
    """Return the executable-brief contract for one Drawing Board task."""

    missing: list[str] = []
    if not _substantive_text(task.get("title"), minimum_words=2):
        missing.append("task_summary")
    operator_owned = bool(task.get("operator_owned") or task.get("operatorOwned"))
    operator_owner = _short(task.get("owner"), 300)
    if operator_owned:
        if not operator_owner:
            missing.append("assignee")
        reasons: list[str] = []
        if drawing_payload_is_telemetry(task):
            reasons.append("failure, blocker, or status telemetry is not a Drawing Board task")
        actionable = not missing and not reasons
        return {
            "actionable": actionable,
            "actionability_state": "actionable" if actionable else "draft",
            "missing_actionability_fields": missing,
            "actionability_reasons": reasons,
        }
    if not _substantive_text(task.get("description"), minimum_words=3):
        missing.append("business_request")
    if not _substantive_text(task.get("requested_outcome"), minimum_words=3):
        missing.append("requested_outcome")
    if not _substantive_text(task.get("next_action"), minimum_words=3):
        missing.append("next_action")
    if not _substantive_text(task.get("assignee_action"), minimum_words=3):
        missing.append("assignee_action")
    if not _short(task.get("agent_name") or task.get("agentName"), 200) and not (
        operator_owned and operator_owner
    ):
        missing.append("assignee")
    if not _task_has_source_or_evidence(task):
        missing.append("source_or_evidence")
    if not (
        _substantive_text(task.get("completion_criteria"), minimum_words=3)
        or any(_substantive_text(item, minimum_words=3) for item in _safe_list(task.get("checklist")))
    ):
        missing.append("completion_criteria")

    reasons: list[str] = []
    if drawing_payload_is_telemetry(task):
        reasons.append("failure, blocker, or status telemetry is not a Drawing Board task")
    actionable = not missing and not reasons
    return {
        "actionable": actionable,
        "actionability_state": "actionable" if actionable else "draft",
        "missing_actionability_fields": missing,
        "actionability_reasons": reasons,
    }


def drawing_payload_is_telemetry(payload: Mapping[str, Any]) -> bool:
    """Reject machine outcomes and diagnostics as task-admission sources."""

    for key in (
        "kind",
        "task_kind",
        "taskKind",
        "category",
        "classification",
        "event_type",
        "eventType",
    ):
        if _normalized_kind(payload.get(key)) in NON_TASK_KINDS:
            return True
    if _normalized_kind(payload.get("source_type") or payload.get("sourceType")) in NON_TASK_SOURCE_TYPES:
        return True
    for key in ("outcome_status", "outcomeStatus", "job_status", "jobStatus", "result_status", "resultStatus"):
        if _normalized_kind(payload.get(key)) in {"blocked", "error", "failed", "failure"}:
            return True
    return any(
        bool(payload.get(key))
        for key in ("is_telemetry", "isTelemetry", "status_only", "statusOnly")
    )


def _require_actionable_task(task: Mapping[str, Any]) -> None:
    actionability = drawing_task_actionability(task)
    if actionability["actionable"]:
        return
    details = [*actionability["missing_actionability_fields"], *actionability["actionability_reasons"]]
    raise ValueError(f"Drawing Board brief is not actionable: {', '.join(details)}")


def _require_single_ownership_mode(task: Mapping[str, Any]) -> None:
    if bool(task.get("operator_owned") or task.get("operatorOwned")) and _short(
        task.get("agent_name") or task.get("agentName"), 200
    ):
        raise ValueError("Drawing Board task cannot be both operator-owned and assigned to an agent")


def _task_has_source_or_evidence(task: Mapping[str, Any]) -> bool:
    if any(
        _short(task.get(key), 2000)
        for key in ("source_url", "sourceUrl", "source_id", "sourceId", "source_thread_id", "sourceThreadId")
    ):
        return True
    if any(_substantive_text(item, minimum_words=2) for item in _safe_list(task.get("evidence"))):
        return True
    for source in _safe_list(task.get("sources")):
        if isinstance(source, Mapping) and any(
            _short(source.get(key), 2000)
            for key in ("source_url", "source_id", "excerpt", "external_id")
        ):
            return True
    for evidence in _safe_list(task.get("evidence_records")):
        if isinstance(evidence, Mapping) and any(
            _short(evidence.get(key), 12000)
            for key in ("summary", "source_url", "external_id")
        ):
            return True
    return False


def _substantive_text(value: Any, *, minimum_words: int) -> bool:
    text = " ".join(str(value or "").strip().split())
    if len(text) < 8:
        return False
    normalized = " ".join("".join(char if char.isalnum() else " " for char in text.casefold()).split())
    if normalized in GENERIC_BRIEF_TEXT:
        return False
    words = [word for word in normalized.split() if any(char.isalpha() for char in word)]
    return len(words) >= minimum_words


def _safe_list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, (list, tuple)) else []


def _normalized_kind(value: Any) -> str:
    return "_".join(str(value or "").strip().casefold().replace("-", " ").split())


def _status(value: Any) -> str:
    status = str(value or "drawing").strip().lower()
    if status not in STATUSES:
        raise ValueError(f"status must be one of {sorted(STATUSES)}")
    return status


def _priority(value: Any) -> str:
    priority = str(value or "normal").strip().lower()
    if priority not in PRIORITIES:
        raise ValueError(f"priority must be one of {sorted(PRIORITIES)}")
    return priority


def _short(value: Any, limit: int) -> str:
    return str(value or "").strip()[:limit]


def _required(value: Any, label: str, limit: int) -> str:
    result = _short(value, limit)
    if not result:
        raise ValueError(f"{label} is required")
    return result


def _json_list(value: Any) -> str:
    if value is None:
        result: list[Any] = []
    elif isinstance(value, (list, tuple)):
        result = list(value)
    else:
        raise ValueError("expected a list")
    return json.dumps(result, ensure_ascii=False, default=str)


def _confidence(value: Any) -> float:
    return max(0.0, min(float(value), 1.0))


def _timestamp(value: Any) -> float | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    from datetime import datetime

    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamps must include a timezone")
    return parsed.timestamp()


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    from datetime import UTC, datetime

    return datetime.fromtimestamp(float(value), tz=UTC).isoformat().replace("+00:00", "Z")
