# AgentChat/coding_agent 2026-07-10T12:24:00-04:00: redact generic gateway credential labels.
# AgentChat/coding_agent 2026-07-10T12:31:00-04:00: redact standalone long gateway keys.
# AgentChat/coding_agent 2026-07-10T12:42:00-04:00: redact compact gateway key labels.
# AgentChat/direct_codex 2026-07-14T15:56:53-04:00: preserve customer contact identifiers while retaining payment and credential redaction.
from __future__ import annotations

import hashlib
import json
import logging
import math
import re
import sqlite3
import time
import uuid
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Any

from .config import BridgeConfig
from .desktop_memory_json import (
    load_desktop_records,
    parse_desktop_timestamp,
    remember_desktop_json,
    retrieve_desktop_json,
)


LOGGER = logging.getLogger("codex_slack_bridge.memory")
TOKEN_RE = re.compile(r"[a-zA-Z0-9_.$/-]+")
DEEP_MEMORY_RE = re.compile(
    r"\b(deep|thorough|root\s+cause|end[-\s]?to[-\s]?end|implement|refactor|migrate|"
    r"reconcile|security\s+audit|performance\s+audit|multi[-\s]?system|diagnos)\w*\b",
    re.IGNORECASE,
)
SECRET_PATTERNS = (
    re.compile(r"xox[baprs]-[A-Za-z0-9-]+"),
    re.compile(r"xapp-[A-Za-z0-9-]+"),
    re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
    re.compile(r"(?i)(client[_ -]?secret\s*[:=]\s*)[A-Za-z0-9_-]{16,}"),
    re.compile(
        r"(?im)^(\s*(?:nmi\s*)?(?:api|security|tokenization|gateway)\s*key\s*[:=]\s*)[^\r\n]+"
    ),
    re.compile(
        r"(?im)^(\s*(?:account\s+token|acceptor\s+id|terminal\s+id|merchant\s+id|mid)\s*[:=]\s*)[^\r\n]+"
    ),
    re.compile(r"(?i)((?:cvv|cvc|card\s+security\s+code)\s*[:=]\s*)\d{3,4}"),
    re.compile(r"(?i)((?:card\s+expir(?:y|ation)|expiry)\s*[:=]\s*)(?:0[1-9]|1[0-2])\s*[/.-]\s*\d{2,4}"),
    re.compile(r"(?i)((?:bank\s+account|routing\s+number)\s*[:=]\s*)\d[\d -]{3,}"),
    re.compile(r"(?m)^(\s*)[A-Za-z0-9_-]{24,}\s*$"),
)
PAYMENT_CARD_CANDIDATE_RE = re.compile(r"(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)")


class MemoryStore:
    def __init__(self, config: BridgeConfig) -> None:
        defaults = config.defaults
        self.enabled = bool(defaults.get("memory_enabled", True))
        self.backend = str(defaults.get("memory_backend", "auto")).lower()
        self.sqlite_path = Path(str(defaults.get("memory_sqlite_path", "data/memory.sqlite3")))
        self.lancedb_path = Path(str(defaults.get("memory_lancedb_path", "data/lancedb")))
        self.desktop_json_path = Path(str(defaults.get("desktop_vector_memory_path", "data/desktop_chat/memory_vectors.json")))
        self.desktop_json_mirror = bool(defaults.get("memory_desktop_json_mirror", True))
        self.table_name = str(defaults.get("memory_table", "agent_memory"))
        self.dimensions = int(defaults.get("memory_hash_dimensions", 384))
        self.default_top_k = int(defaults.get("memory_top_k", 8))
        self.adaptive_top_k = bool(defaults.get("memory_adaptive_top_k", True))
        self.deep_top_k = int(defaults.get("memory_deep_top_k", max(8, self.default_top_k)))
        self.global_agent = str(defaults.get("memory_global_agent", "global"))
        self.max_store_chars = int(defaults.get("memory_max_store_chars", 6000))
        self._lock = Lock()
        self._lancedb_table: Any | None = None
        self._lancedb_available = False
        self._desktop_sync_sig: tuple[int, int] | None = None
        self._desktop_records: list[dict[str, Any]] = []
        self._known_fingerprints: set[str] | None = None

        if self.enabled:
            self.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
            self._init_sqlite()
            self._init_lancedb()
            self._sync_from_desktop_json()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.sqlite_path)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=5000")
        return connection

    def _init_sqlite(self) -> None:
        with self._connect() as db:
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS memories (
                    id TEXT PRIMARY KEY,
                    agent_name TEXT NOT NULL,
                    text TEXT NOT NULL,
                    source TEXT NOT NULL,
                    tags_json TEXT NOT NULL,
                    importance REAL NOT NULL,
                    created_at REAL NOT NULL
                )
                """
            )
            # Serialize additive migrations across the Slack, desktop, and
            # Command Center processes that may start at nearly the same time.
            db.execute("BEGIN IMMEDIATE")
            # Lifecycle fields are additive so databases created by older
            # bridge versions remain valid. SQLite cannot add several columns
            # in one statement, hence the small idempotent migration loop.
            columns = {str(row[1]) for row in db.execute("PRAGMA table_info(memories)")}
            migrations = {
                "fingerprint": "TEXT",
                "source_version": "TEXT",
                "metadata_json": "TEXT NOT NULL DEFAULT '{}'",
                "expires_at": "REAL",
                "superseded_by": "TEXT",
                "helpful_count": "INTEGER NOT NULL DEFAULT 0",
                "unhelpful_count": "INTEGER NOT NULL DEFAULT 0",
                "stale_count": "INTEGER NOT NULL DEFAULT 0",
                "updated_at": "REAL",
            }
            for name, definition in migrations.items():
                if name not in columns:
                    db.execute(f"ALTER TABLE memories ADD COLUMN {name} {definition}")
            db.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_memories_fingerprint
                ON memories(fingerprint)
                """
            )
            rows = db.execute(
                """
                SELECT id, agent_name, source, text
                FROM memories
                WHERE fingerprint IS NULL OR fingerprint = ''
                """
            ).fetchall()
            db.executemany(
                "UPDATE memories SET fingerprint = ?, updated_at = COALESCE(updated_at, created_at) WHERE id = ?",
                [(_memory_fingerprint(agent, source, text), memory_id) for memory_id, agent, source, text in rows],
            )
            db.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_memories_agent_created
                ON memories(agent_name, created_at DESC)
                """
            )

    def _init_lancedb(self) -> None:
        if self.backend not in {"auto", "lancedb"}:
            return
        try:
            import lancedb  # type: ignore[import-not-found]
        except Exception as exc:
            if self.backend == "lancedb":
                LOGGER.warning("LanceDB requested but unavailable: %s", exc)
            return

        try:
            self.lancedb_path.mkdir(parents=True, exist_ok=True)
            db = lancedb.connect(str(self.lancedb_path))
            if self.table_name in db.table_names():
                self._lancedb_table = db.open_table(self.table_name)
            self._lancedb_available = True
        except Exception:
            LOGGER.exception("Could not initialize LanceDB memory index")
            self._lancedb_available = False

    def remember(
        self,
        *,
        agent_name: str,
        text: str,
        source: str,
        tags: list[str] | None = None,
        importance: float = 1.0,
        source_version: str | None = None,
        expires_at: float | str | datetime | None = None,
        supersedes: str | list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str | None:
        if not self.enabled:
            return None
        clean_text = redact_secrets(text).strip()
        if not clean_text:
            return None
        if len(clean_text) > self.max_store_chars:
            clean_text = clean_text[: self.max_store_chars].rstrip() + "\n[truncated]"

        # Import any desktop-side additions before mirroring this write. When
        # the file is unchanged this is an mtime check only, not an 8+ MB scan.
        if self.desktop_json_mirror:
            self._sync_from_desktop_json()

        memory_id = str(uuid.uuid4())
        created_at = time.time()
        tag_list = tags or []
        fingerprint = _memory_fingerprint(agent_name, source, clean_text)
        expiry = _coerce_timestamp(expires_at)
        replacement_targets = [supersedes] if isinstance(supersedes, str) else list(supersedes or [])
        replacement_targets = list(dict.fromkeys(target.strip() for target in replacement_targets if target.strip()))
        metadata_record = dict(metadata or {})
        with self._lock, self._connect() as db:
            if not replacement_targets:
                duplicate = db.execute(
                    """
                    SELECT id FROM memories
                    WHERE fingerprint = ?
                      AND superseded_by IS NULL
                      AND stale_count = 0
                      AND (expires_at IS NULL OR expires_at > ?)
                    ORDER BY created_at DESC LIMIT 1
                    """,
                    (fingerprint, created_at),
                ).fetchone()
                if duplicate:
                    return str(duplicate[0])

            for target_id in replacement_targets:
                target = db.execute(
                    "SELECT agent_name, superseded_by FROM memories WHERE id = ?",
                    (target_id,),
                ).fetchone()
                if target is None:
                    raise ValueError(f"Cannot supersede unknown memory: {target_id}")
                if str(target[0]).lower() != agent_name.lower():
                    raise ValueError(f"Cannot supersede memory owned by another agent: {target_id}")
                if target[1]:
                    raise ValueError(f"Memory is already superseded: {target_id}")
            conflict_key = str(metadata_record.get("conflict_key") or metadata_record.get("topic") or "").strip()
            if conflict_key and not replacement_targets:
                candidates = db.execute(
                    """
                    SELECT id, metadata_json FROM memories
                    WHERE agent_name = ? AND source = ?
                      AND superseded_by IS NULL AND stale_count = 0
                      AND (expires_at IS NULL OR expires_at > ?)
                    """,
                    (agent_name, source, created_at),
                ).fetchall()
                conflicts: list[str] = []
                for candidate_id, candidate_metadata_json in candidates:
                    try:
                        candidate_metadata = json.loads(candidate_metadata_json or "{}")
                    except (TypeError, ValueError):
                        candidate_metadata = {}
                    candidate_key = str(
                        candidate_metadata.get("conflict_key") or candidate_metadata.get("topic") or ""
                    ).strip()
                    if candidate_key and candidate_key.lower() == conflict_key.lower():
                        conflicts.append(str(candidate_id))
                if conflicts:
                    metadata_record["conflict_detected"] = True
                    metadata_record["conflicts_with"] = conflicts
            metadata_json = json.dumps(metadata_record, sort_keys=True)
            db.execute(
                """
                INSERT INTO memories(
                    id, agent_name, text, source, tags_json, importance, created_at,
                    fingerprint, source_version, metadata_json, expires_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    memory_id,
                    agent_name,
                    clean_text,
                    source,
                    json.dumps(tag_list),
                    float(importance),
                    created_at,
                    fingerprint,
                    str(source_version).strip() if source_version is not None else None,
                    metadata_json,
                    expiry,
                    created_at,
                ),
            )
            if replacement_targets:
                db.executemany(
                    "UPDATE memories SET superseded_by = ?, updated_at = ? WHERE id = ?",
                    [(memory_id, created_at, target_id) for target_id in replacement_targets],
                )
            if self._known_fingerprints is not None:
                self._known_fingerprints.add(_memory_fingerprint(agent_name, source, clean_text))

        self._remember_lancedb(
            {
                "id": memory_id,
                "agent_name": agent_name,
                "text": clean_text,
                "source": source,
                "tags": ",".join(tag_list),
                "importance": float(importance),
                "created_at": created_at,
                "vector": hash_embedding(clean_text, self.dimensions),
            }
        )
        if self.desktop_json_mirror:
            try:
                mirrored_id = remember_desktop_json(
                    path=self.desktop_json_path,
                    agent_name=agent_name,
                    text=clean_text,
                    source=source,
                    tags=tag_list,
                    importance=float(importance),
                )
                if mirrored_id:
                    # remember_desktop_json already refreshed its parsed-file
                    # cache. Adopt that state so the next retrieval does not
                    # iterate every record merely to rediscover this write.
                    self._refresh_desktop_cache_state()
            except Exception:
                LOGGER.exception("Could not mirror memory to desktop JSON store")
        return memory_id

    def _remember_lancedb(self, record: dict[str, Any]) -> None:
        if not self._lancedb_available:
            return
        try:
            if self._lancedb_table is None:
                import lancedb  # type: ignore[import-not-found]

                db = lancedb.connect(str(self.lancedb_path))
                self._lancedb_table = db.create_table(self.table_name, data=[record])
            else:
                self._lancedb_table.add([record])
        except Exception:
            LOGGER.exception("Could not write memory to LanceDB; SQLite memory was preserved")
            self._lancedb_available = False

    def retrieve(self, *, agent_name: str, query: str, top_k: int | None = None) -> list[dict[str, Any]]:
        if not self.enabled:
            return []
        clean_query = redact_secrets(query).strip()
        if not clean_query:
            return []
        limit = self._retrieval_limit(clean_query, top_k)
        # Lifecycle filtering happens after vector retrieval. Oversampling
        # prevents retired candidates near the top of an old LanceDB index
        # from crowding active memories out of the final result.
        candidate_limit = max(limit, limit * 4)

        desktop_records = self._sync_from_desktop_json()
        desktop_results = retrieve_desktop_json(
            path=self.desktop_json_path,
            agent_name=agent_name,
            global_agent=self.global_agent,
            query=clean_query,
            top_k=candidate_limit,
            records=desktop_records,
        )
        desktop_results = self._apply_lifecycle(
            agent_name,
            _normalize_result_scores(desktop_results, backend="desktop"),
        )
        lancedb_results = self._apply_lifecycle(
            agent_name,
            self._retrieve_lancedb(agent_name, clean_query, candidate_limit),
        )
        if lancedb_results:
            return _merge_memory_results(lancedb_results, desktop_results, limit)
        sqlite_results = self._retrieve_sqlite(agent_name, clean_query, candidate_limit)
        return _merge_memory_results(sqlite_results, desktop_results, limit)

    def recent(self, *, agent_name: str, limit: int | None = None) -> list[dict[str, Any]]:
        if not self.enabled:
            return []
        self._sync_from_desktop_json()
        row_limit = limit or self.default_top_k
        with self._lock, self._connect() as db:
            rows = db.execute(
                """
                SELECT id, agent_name, text, source, tags_json, importance, created_at
                FROM memories
                WHERE agent_name IN (?, ?)
                  AND superseded_by IS NULL
                  AND stale_count = 0
                  AND (expires_at IS NULL OR expires_at > ?)
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (agent_name, self.global_agent, time.time(), row_limit),
            ).fetchall()
        return [
            {
                "id": memory_id,
                "agent_name": row_agent,
                "text": text,
                "source": source,
                "tags": ",".join(json.loads(tags_json or "[]")),
                "score": importance,
            }
            for memory_id, row_agent, text, source, tags_json, importance, _created_at in rows
        ]

    def record_feedback(
        self,
        memory_id: str,
        *,
        helpful: bool | None = None,
        stale: bool = False,
    ) -> bool:
        """Record lightweight user/operator feedback without rewriting memory.

        A stale vote immediately retires the record from retrieval. Helpful and
        unhelpful votes adjust ranking while preserving the original evidence.
        """
        if not self.enabled or (helpful is None and not stale):
            return False
        helpful_delta = 1 if helpful is True else 0
        unhelpful_delta = 1 if helpful is False else 0
        stale_delta = 1 if stale else 0
        with self._lock, self._connect() as db:
            cursor = db.execute(
                """
                UPDATE memories
                SET helpful_count = helpful_count + ?,
                    unhelpful_count = unhelpful_count + ?,
                    stale_count = stale_count + ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (helpful_delta, unhelpful_delta, stale_delta, time.time(), memory_id),
            )
            return cursor.rowcount > 0

    def _apply_lifecycle(
        self,
        agent_name: str,
        results: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if not results:
            return []
        ids = {str(item.get("id") or "") for item in results if item.get("id")}
        fingerprints = {
            _memory_fingerprint(
                str(item.get("agent_name") or agent_name),
                str(item.get("source") or ""),
                str(item.get("text") or ""),
            )
            for item in results
        }
        id_placeholders = ",".join("?" for _ in ids) or "NULL"
        fp_placeholders = ",".join("?" for _ in fingerprints) or "NULL"
        with self._lock, self._connect() as db:
            rows = db.execute(
                f"""
                SELECT id, fingerprint, source_version, metadata_json, expires_at,
                       superseded_by, helpful_count, unhelpful_count, stale_count
                FROM memories
                WHERE agent_name IN (?, ?)
                  AND (id IN ({id_placeholders}) OR fingerprint IN ({fp_placeholders}))
                ORDER BY created_at DESC
                """,
                (agent_name, self.global_agent, *ids, *fingerprints),
            ).fetchall()
        by_id: dict[str, tuple[Any, ...]] = {}
        by_fingerprint: dict[str, tuple[Any, ...]] = {}
        for row in rows:
            by_id.setdefault(str(row[0]), row)
            by_fingerprint.setdefault(str(row[1] or ""), row)

        now = time.time()
        active: list[dict[str, Any]] = []
        for result in results:
            fingerprint = _memory_fingerprint(
                str(result.get("agent_name") or agent_name),
                str(result.get("source") or ""),
                str(result.get("text") or ""),
            )
            lifecycle = by_id.get(str(result.get("id") or "")) or by_fingerprint.get(fingerprint)
            if lifecycle is None:
                active.append(result)
                continue
            expires_at, superseded_by = lifecycle[4], lifecycle[5]
            helpful, unhelpful, stale_count = int(lifecycle[6] or 0), int(lifecycle[7] or 0), int(lifecycle[8] or 0)
            if superseded_by or stale_count or (expires_at is not None and float(expires_at) <= now):
                continue
            enriched = dict(result)
            # Desktop mirrors intentionally have their own transport IDs. Once
            # matched by fingerprint, return the canonical SQLite ID so feedback
            # and supersession always target the durable record.
            enriched["id"] = str(lifecycle[0])
            enriched["source_version"] = lifecycle[2]
            try:
                enriched["metadata"] = json.loads(lifecycle[3] or "{}")
            except (TypeError, ValueError):
                enriched["metadata"] = {}
            enriched["expires_at"] = expires_at
            enriched["feedback"] = {
                "helpful": helpful,
                "unhelpful": unhelpful,
                "stale": stale_count,
            }
            base_score = _clamp01(enriched.get("score"))
            boost = min(helpful, 5) * 0.02
            penalty = min(unhelpful, 5) * 0.08
            enriched["score"] = _clamp01(base_score + boost - penalty)
            active.append(enriched)
        active.sort(key=lambda item: float(item.get("score") or 0), reverse=True)
        return active

    def _sync_from_desktop_json(self) -> list[dict[str, Any]]:
        """Import desktop-written memories into SQLite (canonical store).

        The desktop app writes data/desktop_chat/memory_vectors.json directly;
        this pulls any records SQLite has not seen yet so both surfaces share
        one brain. Records are deduplicated by a fingerprint of
        (agent, source, text) — the same composition the JSON mirror uses —
        so Slack-originated mirrors are never re-imported.
        """
        if not self.enabled or not self.desktop_json_mirror:
            return []
        try:
            stat = self.desktop_json_path.stat()
        except OSError:
            return []
        signature = (stat.st_mtime_ns, stat.st_size)
        if signature == self._desktop_sync_sig:
            return self._desktop_records
        try:
            records = load_desktop_records(self.desktop_json_path)
        except Exception:
            LOGGER.exception("Could not read desktop JSON memory store for sync")
            return self._desktop_records
        if not records:
            self._desktop_records = []
            self._desktop_sync_sig = signature
            return []

        imported: list[dict[str, Any]] = []
        try:
            with self._lock, self._connect() as db:
                if self._known_fingerprints is None:
                    rows = db.execute("SELECT agent_name, source, text FROM memories").fetchall()
                    self._known_fingerprints = {
                        _memory_fingerprint(agent, source, text) for agent, source, text in rows
                    }
                known = self._known_fingerprints
                for record in records:
                    agent_name = str(record.get("AgentName") or "").strip()
                    raw_text = str(record.get("Text") or "")
                    clean_text = redact_secrets(raw_text).strip()
                    if not agent_name or not clean_text:
                        continue
                    if len(clean_text) > self.max_store_chars:
                        clean_text = clean_text[: self.max_store_chars].rstrip() + "\n[truncated]"
                    source = str(record.get("Source") or "desktop-json")
                    fingerprint = _memory_fingerprint(agent_name, source, clean_text)
                    if fingerprint in known:
                        continue
                    known.add(fingerprint)
                    tags = [str(tag) for tag in (record.get("Tags") or []) if str(tag).strip()]
                    try:
                        importance = float(record.get("Importance") or 1.0)
                    except (TypeError, ValueError):
                        importance = 1.0
                    created_at = parse_desktop_timestamp(str(record.get("CreatedAt") or "")) or time.time()
                    memory_id = str(record.get("Id") or "").strip() or str(uuid.uuid4())
                    db.execute(
                        """
                        INSERT OR IGNORE INTO memories(
                            id, agent_name, text, source, tags_json, importance, created_at,
                            fingerprint, updated_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            memory_id,
                            agent_name,
                            clean_text,
                            source,
                            json.dumps(tags),
                            importance,
                            created_at,
                            fingerprint,
                            created_at,
                        ),
                    )
                    imported.append(
                        {
                            "id": memory_id,
                            "agent_name": agent_name,
                            "text": clean_text,
                            "source": source,
                            "tags": ",".join(tags),
                            "importance": importance,
                            "created_at": created_at,
                        }
                    )
        except Exception:
            LOGGER.exception("Could not import desktop JSON memories into SQLite")
            return self._desktop_records

        for item in imported:
            self._remember_lancedb({**item, "vector": hash_embedding(str(item["text"]), self.dimensions)})
        self._desktop_records = records
        self._desktop_sync_sig = signature
        if imported:
            LOGGER.info("Imported %s desktop memory record(s) into SQLite", len(imported))
        return records

    def _retrieval_limit(self, query: str, requested: int | None) -> int:
        """Use a compact ordinary context and reserve extra recall for deep work."""
        ordinary = max(1, int(requested or self.default_top_k))
        if not self.adaptive_top_k:
            return ordinary
        # The caller may append a long Slack thread to an otherwise ordinary
        # question, so length alone is not a reliable signal for deep work.
        if DEEP_MEMORY_RE.search(query):
            return max(ordinary, self.deep_top_k)
        return ordinary

    def _refresh_desktop_cache_state(self) -> None:
        """Adopt a stable cached desktop snapshot without reparsing the JSON."""
        for _attempt in range(2):
            try:
                before = self.desktop_json_path.stat()
                records = load_desktop_records(self.desktop_json_path)
                after = self.desktop_json_path.stat()
            except OSError:
                return
            before_signature = (before.st_mtime_ns, before.st_size)
            after_signature = (after.st_mtime_ns, after.st_size)
            if before_signature == after_signature:
                self._desktop_records = records
                self._desktop_sync_sig = after_signature
                return
        # A concurrent writer kept moving the file. Force a normal sync on the
        # next retrieval rather than associating stale records with a new mtime.
        self._desktop_sync_sig = None

    def _retrieve_lancedb(
        self,
        agent_name: str,
        query: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        if not self._lancedb_available or self._lancedb_table is None:
            return []
        safe_agent = sql_literal(agent_name)
        safe_global = sql_literal(self.global_agent)
        where = f"agent_name IN ({safe_agent}, {safe_global})"
        try:
            rows = (
                self._lancedb_table.search(hash_embedding(query, self.dimensions))
                .where(where)
                .limit(limit)
                .to_list()
            )
        except Exception:
            LOGGER.exception("LanceDB memory retrieval failed; falling back to SQLite")
            return []
        results = [
            {
                "id": row.get("id"),
                "agent_name": row.get("agent_name"),
                "text": row.get("text", ""),
                "source": row.get("source", ""),
                "tags": row.get("tags", ""),
                "score": _normalize_lance_score(row),
                "score_backend": "lancedb",
            }
            for row in rows
        ]
        return results

    def _retrieve_sqlite(
        self,
        agent_name: str,
        query: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        query_terms = set(tokenize(query))
        if not query_terms:
            return []
        with self._lock, self._connect() as db:
            rows = db.execute(
                """
                SELECT id, agent_name, text, source, tags_json, importance, created_at,
                       source_version, metadata_json, expires_at, helpful_count,
                       unhelpful_count
                FROM memories
                WHERE agent_name IN (?, ?)
                  AND superseded_by IS NULL
                  AND stale_count = 0
                  AND (expires_at IS NULL OR expires_at > ?)
                ORDER BY created_at DESC
                LIMIT 300
                """,
                (agent_name, self.global_agent, time.time()),
            ).fetchall()

        now = time.time()
        scored: list[dict[str, Any]] = []
        for (
            memory_id,
            row_agent,
            text,
            source,
            tags_json,
            importance,
            created_at,
            source_version,
            metadata_json,
            expires_at,
            helpful_count,
            unhelpful_count,
        ) in rows:
            terms = set(tokenize(text))
            intersection = len(query_terms & terms)
            if intersection == 0:
                continue
            age_days = max((now - float(created_at)) / 86400, 0)
            recency = 1 / (1 + age_days / 30)
            query_coverage = intersection / max(len(query_terms), 1)
            union = len(query_terms | terms)
            jaccard = intersection / max(union, 1)
            normalized_importance = max(float(importance), 0.0) / (1 + max(float(importance), 0.0))
            score = (
                query_coverage * 0.55
                + jaccard * 0.15
                + normalized_importance * 0.20
                + recency * 0.10
                + min(int(helpful_count or 0), 5) * 0.02
                - min(int(unhelpful_count or 0), 5) * 0.08
            )
            try:
                metadata = json.loads(metadata_json or "{}")
            except (TypeError, ValueError):
                metadata = {}
            scored.append(
                {
                    "id": memory_id,
                    "agent_name": row_agent,
                    "text": text,
                    "source": source,
                    "tags": ",".join(json.loads(tags_json or "[]")),
                    "score": _clamp01(score),
                    "score_backend": "sqlite",
                    "source_version": source_version,
                    "metadata": metadata,
                    "expires_at": expires_at,
                    "feedback": {
                        "helpful": int(helpful_count or 0),
                        "unhelpful": int(unhelpful_count or 0),
                        "stale": 0,
                    },
                }
            )
        scored.sort(key=lambda item: item["score"], reverse=True)
        return scored[:limit]

    def export_sqlite_rows(self) -> list[dict[str, Any]]:
        if not self.enabled:
            return []
        self._sync_from_desktop_json()
        with self._lock, self._connect() as db:
            rows = db.execute(
                """
                SELECT id, agent_name, text, source, tags_json, importance, created_at,
                       source_version, metadata_json, expires_at, superseded_by,
                       helpful_count, unhelpful_count, stale_count, updated_at
                FROM memories
                ORDER BY created_at ASC
                """
            ).fetchall()
        exported: list[dict[str, Any]] = []
        for (
            memory_id,
            row_agent,
            text,
            source,
            tags_json,
            importance,
            created_at,
            source_version,
            metadata_json,
            expires_at,
            superseded_by,
            helpful_count,
            unhelpful_count,
            stale_count,
            updated_at,
        ) in rows:
            try:
                metadata = json.loads(metadata_json or "{}")
            except (TypeError, ValueError):
                metadata = {}
            exported.append({
                "id": memory_id,
                "agent_name": row_agent,
                "text": text,
                "source": source,
                "tags": json.loads(tags_json or "[]"),
                "importance": importance,
                "created_at": created_at,
                "source_version": source_version,
                "metadata": metadata,
                "expires_at": expires_at,
                "superseded_by": superseded_by,
                "feedback": {
                    "helpful": int(helpful_count or 0),
                    "unhelpful": int(unhelpful_count or 0),
                    "stale": int(stale_count or 0),
                },
                "updated_at": updated_at,
            })
        return exported

    def format_for_prompt(self, *, agent_name: str, query: str, top_k: int | None = None) -> str:
        memories = self.retrieve(agent_name=agent_name, query=query, top_k=top_k)
        if not memories:
            return ""
        lines = ["Long-term agent memory:"]
        for item in memories:
            source = item.get("source") or "memory"
            memory_id = str(item.get("id") or "").strip()
            source_version = str(item.get("source_version") or "").strip()
            if source_version:
                source = f"{source}@{source_version}"
            text = str(item.get("text") or "").strip()
            if text:
                label = f"memory:{memory_id}|{source}" if memory_id else str(source)
                if bool((item.get("metadata") or {}).get("conflict_detected")):
                    label += "|conflict-review"
                lines.append(f"- [{label}] {text}")
        return "\n".join(lines)


def tokenize(text: str) -> list[str]:
    return [match.group(0).lower() for match in TOKEN_RE.finditer(text)]


def hash_embedding(text: str, dimensions: int) -> list[float]:
    vector = [0.0] * dimensions
    for token in tokenize(text):
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
        value = int.from_bytes(digest, "little", signed=False)
        index = value % dimensions
        sign = -1.0 if value & (1 << 63) else 1.0
        vector[index] += sign
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0:
        return vector
    return [value / norm for value in vector]


def redact_secrets(text: str) -> str:
    redacted = text
    for pattern in SECRET_PATTERNS:
        redacted = pattern.sub(lambda match: f"{match.group(1) if match.groups() else ''}[redacted]", redacted)
    return PAYMENT_CARD_CANDIDATE_RE.sub(_redact_valid_payment_card, redacted)


def _redact_valid_payment_card(match: re.Match[str]) -> str:
    """Mask card PANs without treating phone numbers or business IDs as cards."""
    candidate = match.group(0)
    digits = re.sub(r"\D", "", candidate)
    if not 13 <= len(digits) <= 19 or not _passes_luhn_check(digits):
        return candidate
    return "[redacted]"


def _passes_luhn_check(digits: str) -> bool:
    total = 0
    parity = len(digits) % 2
    for index, character in enumerate(digits):
        value = int(character)
        if index % 2 == parity:
            value *= 2
            if value > 9:
                value -= 9
        total += value
    return total % 10 == 0


def _memory_fingerprint(agent_name: str, source: str, text: str) -> str:
    """Same composition as the desktop JSON store's Fingerprint field."""
    return hashlib.sha256(f"{agent_name}\n{source}\n{text}".encode("utf-8")).hexdigest().upper()


def _coerce_timestamp(value: float | str | datetime | None) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.timestamp()
    if isinstance(value, (int, float)):
        return float(value)
    normalized = str(value).strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized).timestamp()
    except ValueError as exc:
        raise ValueError(f"Invalid memory expiry timestamp: {value}") from exc


def _clamp01(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(number):
        return 0.0
    return min(max(number, 0.0), 1.0)


def _normalize_lance_score(row: dict[str, Any]) -> float:
    """Convert LanceDB's lower-is-better distance into higher-is-better relevance."""
    if row.get("_distance") is not None:
        try:
            distance = max(float(row["_distance"]), 0.0)
        except (TypeError, ValueError):
            return 0.0
        # Works for non-negative L2/cosine distances and preserves ordering.
        return 1.0 / (1.0 + distance)
    raw_score = row.get("_score", 0.0)
    try:
        score = float(raw_score)
    except (TypeError, ValueError):
        return 0.0
    # Some Lance full-text APIs expose an unbounded relevance score.
    if score > 1.0:
        return score / (1.0 + score)
    return _clamp01(score)


def _normalize_result_scores(
    results: list[dict[str, Any]],
    *,
    backend: str,
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for item in results:
        row = dict(item)
        row["score"] = _clamp01(row.get("score"))
        row["score_backend"] = backend
        normalized.append(row)
    return normalized


def sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _merge_memory_results(
    first: list[dict[str, Any]],
    second: list[dict[str, Any]],
    limit: int,
) -> list[dict[str, Any]]:
    seen: set[str] = set()
    merged: list[dict[str, Any]] = []
    for item in sorted(first + second, key=lambda row: float(row.get("score") or 0), reverse=True):
        # Mirrored SQLite/desktop records intentionally have different IDs.
        # Deduplicate their shared evidence rather than showing it twice.
        key = _memory_fingerprint(
            str(item.get("agent_name") or ""),
            str(item.get("source") or ""),
            str(item.get("text") or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        merged.append(item)
        if len(merged) >= limit:
            break
    return merged
