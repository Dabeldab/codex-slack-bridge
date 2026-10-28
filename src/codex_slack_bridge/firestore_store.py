"""Durable Firestore-backed store for the Nova Command Center.

Supports Cloud Run scale-to-zero by persisting two collections that must
survive instance teardown:

  * ``tickets``  -- the kanban board (support / billing / review columns).
  * ``job_usage`` -- per-job token/cost history tracked over time.

Design constraints (user-directed):

  * Must survive scale-to-zero (no ephemeral container disk).
  * Must be the most cost-efficient option -- no always-on compute.  The board
    and usage volumes are tiny (dozens to low hundreds of rows per day), far
    inside Firestore's free tier (50K reads / 20K writes / 1GiB per day).
  * Must not raise costs on schedules/on-demand runs -- Firestore has no warm
    instance and bills only what is used.

This module is OPT-IN via ``FIRESTORE_ENABLED``.  When disabled, or when
Firestore is unreachable/unconfigured, every method degrades gracefully so the
existing ephemeral JSON/SQLite paths keep working.  A write-budget cap prevents
a runaway refresh from blowing past the free tier.
"""

from __future__ import annotations

import os
import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, Iterable, Optional

try:  # optional dependency -- import fails cleanly when not installed
    from google.cloud import firestore
    from google.cloud.firestore import Client as FirestoreClient
except Exception:  # pragma: no cover - depends on environment
    firestore = None
    FirestoreClient = None  # type: ignore[misc, assignment]

_UTC = timezone.utc

# Free-tier guardrails (Firestore native-mode daily free tier).
# Keep writes per refresh well inside the 20K/day free allocation.
DEFAULT_MAX_WRITES_PER_REFRESH = 1000
DEFAULT_MAX_DOCUMENT_BYTES = 1 << 18  # 256 KiB, far under the 1 MiB limit

_ENABLED = os.getenv("FIRESTORE_ENABLED", "").strip().lower() in {"1", "true", "yes", "on"}
_PROJECT = os.getenv("FIRESTORE_PROJECT_ID", "").strip() or os.getenv("GOOGLE_CLOUD_PROJECT", "").strip()
_EMULATOR = os.getenv("FIRESTORE_EMULATOR_HOST", "").strip() or os.getenv("DATASTORE_EMULATOR_HOST", "").strip()


def _now_iso() -> str:
    return datetime.now(_UTC).isoformat(timespec="milliseconds")


def firestore_enabled() -> bool:
    """True only when the Firestore backend is both enabled and importable."""
    if not _ENABLED or firestore is None:
        return False
    # Emulator mode can run without a real project.
    if _EMULATOR:
        return True
    return bool(_PROJECT)


def firestore_reason() -> str:
    """Human-readable reason the Firestore backend is off (for logs)."""
    if firestore is None:
        return "google-cloud-firestore package not installed"
    if not _ENABLED:
        return "FIRESTORE_ENABLED is not set"
    if not _PROJECT and not _EMULATOR:
        return "no FIRESTORE_PROJECT_ID / GOOGLE_CLOUD_PROJECT / emulator configured"
    return "ok"


class FirestoreStore:
    """Thin, budget-capped Firestore facade for tickets + job_usage."""

    TICKETS_COLLECTION = "tickets"
    USAGE_COLLECTION = "job_usage"

    def __init__(
        self,
        *,
        project: str = "",
        emulator: bool = False,
        max_writes_per_refresh: int = DEFAULT_MAX_WRITES_PER_REFRESH,
        enabled: Optional[bool] = None,
    ) -> None:
        self._lock = threading.RLock()
        self._max_writes = int(max_writes_per_refresh)
        self._enabled = firestore_enabled() if enabled is None else bool(enabled)
        self._client: Optional[FirestoreClient] = None
        self._reported_unavailable = False
        self._project = project or _PROJECT
        self._emulator = emulator or bool(_EMULATOR)
        if self._enabled and firestore is not None:
            try:
                # For emulator runs the SDK reads DATASTORE_EMULATOR_HOST /
                # FIRESTORE_EMULATOR_HOST from the environment automatically.
                self._client = firestore.Client(project=self._project or None)
            except Exception:
                self._client = None
                self._enabled = False

    # -- availability -----------------------------------------------------

    @property
    def available(self) -> bool:
        return bool(self._enabled and self._client is not None)

    def mark_attempted(self) -> None:
        """Log once that Firestore is configured but not usable."""
        if not self._reported_unavailable:
            self._reported_unavailable = True

    # -- helpers ----------------------------------------------------------

    def _collection(self, name: str):
        if not self.available:
            raise RuntimeError("FirestoreStore is not available")
        return self._client.collection(name)

    @staticmethod
    def _coerce_doc(data: dict) -> dict:
        """Make values Firestore-serializable (drop bytes/non-serializable)."""
        out: Dict[str, Any] = {}
        for key, value in data.items():
            if isinstance(value, bytes):
                continue
            if value is None or isinstance(value, (str, int, float, bool)):
                out[key] = value
            elif isinstance(value, dict):
                out[key] = FirestoreStore._coerce_doc(value)
            elif isinstance(value, (list, tuple)):
                out[key] = [
                    FirestoreStore._coerce_doc(item) if isinstance(item, dict)
                    else item
                    for item in value
                    if not isinstance(item, bytes)
                ]
            else:
                out[key] = str(value)
        return out

    def _write_budget(self, count: int) -> bool:
        """Return False (and no-op) when a refresh would exceed the write budget."""
        return 0 < int(count) <= self._max_writes

    # -- tickets board ----------------------------------------------------

    def upsert_tickets(self, tickets: Iterable[dict], *, ticket_id_key: str = "id") -> dict[str, Any]:
        """Incrementally write board tickets, returning a write summary.

        New/updated documents are set (overwrite).  ``closed`` boolean flags
        documents that should be surfaced as closed without deleting history.
        """
        tickets = list(tickets)
        if not self.available:
            return {"ok": False, "reason": firestore_reason(), "written": 0, "skipped": 0}
        if not self._write_budget(len(tickets)):
            self.mark_attempted()
            return {
                "ok": False,
                "reason": f"write budget exceeded ({len(tickets)} > {self._max_writes})",
                "written": 0,
                "skipped": 0,
            }
        coll = self._collection(self.TICKETS_COLLECTION)
        written = 0
        for ticket in tickets:
            doc_id = str(ticket.get(ticket_id_key) or ticket.get("number") or "").strip()
            if not doc_id:
                continue
            doc_data = self._coerce_doc({**ticket, "last_seen_at": ticket.get("last_seen_at") or _now_iso()})
            is_closed = bool(ticket.get("is_closed") or ticket.get("isClosed"))
            doc_data["is_closed"] = is_closed
            doc_data["isClosed"] = is_closed
            coll.document(doc_id).set(doc_data, merge=True)
            written += 1
        return {"ok": True, "written": written, "skipped": len(tickets) - written}

    def list_tickets(self, *, lane: str = "", include_closed: bool = False, limit: int = 500) -> list[dict]:
        if not self.available:
            return []
        coll = self._collection(self.TICKETS_COLLECTION)
        docs = list(coll.limit(max(1, min(int(limit), 1000))).stream())
        rows = [dict(doc.to_dict() or {}, id=doc.id) for doc in docs]
        if lane:
            rows = [row for row in rows if str(row.get("lane") or "") == lane]
        if not include_closed:
            rows = [row for row in rows if not bool(row.get("is_closed") or row.get("isClosed"))]
        return rows

    def set_ticket_closed(self, ticket_number: str, *, closed_at: str = "") -> bool:
        if not self.available or not str(ticket_number or "").strip():
            return False
        coll = self._collection(self.TICKETS_COLLECTION)
        coll.document(str(ticket_number).strip()).set(
            {"is_closed": True, "closed_at": closed_at or _now_iso()},
            merge=True,
        )
        return True

    def delete_tickets_missing(
        self,
        active_numbers: Iterable[str],
        collect: Optional[list] = None,
    ) -> dict[str, Any]:
        """Mark closed any board ticket that no longer appears in the live query.

        Incremental staleness: a ticket that stops appearing in ``list_open_tickets``
        is aged/closed rather than requiring a full rewrite.  When ``collect`` is
        a list, each newly closed ticket document is appended to it so callers
        can learn from the resolution without another read.
        """
        if not self.available:
            return {"ok": False, "reason": firestore_reason(), "closed": 0}
        active = {str(n).strip() for n in active_numbers if str(n or "").strip()}
        coll = self._collection(self.TICKETS_COLLECTION)
        # Stream the small board collection instead of querying one spelling of
        # the closed flag.  Older writers used ``isClosed`` while the durable
        # store originally queried only ``is_closed``, leaving legacy rows
        # permanently outside reconciliation.
        docs = list(coll.stream())
        budget = self._max_writes
        closed = 0
        for doc in docs:
            data = dict(doc.to_dict() or {})
            if bool(data.get("is_closed") or data.get("isClosed")):
                continue
            number = str(data.get("number") or doc.id).strip()
            if number in active:
                continue
            if closed >= budget:
                break
            closed_at = _now_iso()
            if collect is not None:
                collect.append({**data, "id": doc.id, "closedAt": closed_at})
            doc.reference.update(
                {
                    "is_closed": True,
                    "isClosed": True,
                    "closed_at": closed_at,
                    "closedAt": closed_at,
                }
            )
            closed += 1
        return {"ok": True, "closed": closed}

    # -- proactive ticket reconnaissance ---------------------------------

    def claim_ticket_recon(
        self,
        ticket_id: str,
        *,
        fingerprint: str,
        agent_name: str,
        ticket_number: str,
        stale_after_seconds: int = 7200,
    ) -> bool:
        """Atomically claim one changed ticket for an agent investigation.

        The claim lives on the durable ticket document so Cloud Run Job
        retries, overlapping scheduler executions, and instance replacement do
        not spend another reasoning turn on an unchanged ticket.  A claim that
        never reaches a terminal state becomes retryable after the bounded
        stale interval.
        """

        clean_id = str(ticket_id or "").strip()
        clean_fingerprint = str(fingerprint or "").strip()
        if not self.available or not clean_id or not clean_fingerprint or firestore is None:
            return False
        reference = self._collection(self.TICKETS_COLLECTION).document(clean_id)
        transaction = self._client.transaction()

        @firestore.transactional
        def _claim(txn):
            snapshot = reference.get(transaction=txn)
            current = dict(snapshot.to_dict() or {}) if snapshot.exists else {}
            same_version = str(current.get("reconFingerprint") or "") == clean_fingerprint
            state = str(current.get("reconState") or "").strip().lower()
            claimed_at = str(current.get("reconUpdatedAt") or "").strip()
            stale = True
            if claimed_at:
                try:
                    parsed = datetime.fromisoformat(claimed_at.replace("Z", "+00:00"))
                    stale = datetime.now(_UTC) - parsed.astimezone(_UTC) > timedelta(
                        seconds=max(300, int(stale_after_seconds))
                    )
                except ValueError:
                    stale = True
            if same_version and state in {"completed", "needs_attention", "claimed", "running", "failed"}:
                if state in {"completed", "needs_attention"} or not stale:
                    return False
            now = _now_iso()
            txn.set(
                reference,
                {
                    "reconFingerprint": clean_fingerprint,
                    "reconState": "claimed",
                    "reconAgentName": str(agent_name or ""),
                    "reconTicketNumber": str(ticket_number or ""),
                    "reconUpdatedAt": now,
                    "reconResult": "",
                    "reconJobId": "",
                },
                merge=True,
            )
            return True

        return bool(_claim(transaction))

    def complete_ticket_recon(
        self,
        ticket_id: str,
        *,
        fingerprint: str,
        state: str,
        result: str = "",
        job_id: str = "",
    ) -> bool:
        """Persist a private terminal investigation result for the current version."""

        clean_id = str(ticket_id or "").strip()
        clean_fingerprint = str(fingerprint or "").strip()
        if not self.available or not clean_id or not clean_fingerprint or firestore is None:
            return False
        reference = self._collection(self.TICKETS_COLLECTION).document(clean_id)
        transaction = self._client.transaction()

        @firestore.transactional
        def _complete(txn):
            snapshot = reference.get(transaction=txn)
            current = dict(snapshot.to_dict() or {}) if snapshot.exists else {}
            if str(current.get("reconFingerprint") or "") != clean_fingerprint:
                return False
            clean_state = str(state or "failed").strip().lower()
            txn.set(
                reference,
                {
                    "reconState": clean_state,
                    "reconUpdatedAt": _now_iso(),
                    "reconCompletedAt": _now_iso() if clean_state == "completed" else "",
                    "reconResult": str(result or "")[:24000],
                    "reconJobId": str(job_id or "")[:240],
                },
                merge=True,
            )
            return True

        return bool(_complete(transaction))

    # -- generic documents (resolution memory / playbooks) ----------------

    def doc_get(self, collection: str, doc_id: str) -> Optional[dict]:
        if not self.available or not str(doc_id or "").strip():
            return None
        snapshot = self._collection(collection).document(str(doc_id)).get()
        return dict(snapshot.to_dict() or {}) if snapshot.exists else None

    def doc_put(self, collection: str, doc_id: str, data: dict) -> bool:
        if not self.available or not str(doc_id or "").strip() or not data:
            return False
        self._collection(collection).document(str(doc_id)).set(self._coerce_doc(dict(data)), merge=True)
        return True

    def doc_list(self, collection: str, *, limit: int = 500) -> list[dict]:
        if not self.available:
            return []
        docs = self._collection(collection).limit(max(1, min(int(limit), 1000))).stream()
        return [dict(doc.to_dict() or {}, id=doc.id) for doc in docs]

    # -- job usage history -------------------------------------------------

    def upsert_job_usage(self, job_id: int, usage: dict) -> bool:
        """Persist one job's token/cost usage durably for time-tracking."""
        if not job_id or not usage or not self.available:
            return False
        coll = self._collection(self.USAGE_COLLECTION)
        data = self._coerce_doc(
            {
                **usage,
                "job_id": int(job_id),
                "recorded_at": usage.get("recorded_at") or _now_iso(),
            }
        )
        coll.document(str(int(job_id))).set(data, merge=True)
        return True

    def list_usage_history(
        self,
        *,
        agent_name: str = "",
        limit: int = 500,
        since_iso: str = "",
    ) -> list[dict]:
        if not self.available:
            return []
        coll = self._collection(self.USAGE_COLLECTION)
        query = coll
        if agent_name:
            query = query.where("agentName", "==", agent_name)
        docs = list(query.limit(max(1, min(int(limit), 2000))).stream())
        rows = []
        for doc in docs:
            data = dict(doc.to_dict() or {})
            if since_iso and str(data.get("recorded_at") or "") < since_iso:
                continue
            rows.append(data)
        rows.sort(key=lambda r: str(r.get("recorded_at") or ""))
        return rows

    def usage_totals(
        self,
        *,
        agent_name: str = "",
        since_iso: str = "",
        limit: int = 2000,
    ) -> dict[str, Any]:
        """Aggregate token/cost totals from durable history (per agent and total)."""
        rows = self.list_usage_history(agent_name=agent_name, limit=limit, since_iso=since_iso)
        totals: Dict[str, Dict[str, float]] = {}
        grand = {"input_tokens": 0.0, "cached_input_tokens": 0.0, "output_tokens": 0.0,
                 "reasoning_output_tokens": 0.0, "total_tokens": 0.0, "estimated_cost_usd": 0.0}
        for row in rows:
            agent = str(row.get("agentName") or "unknown")
            bucket = totals.setdefault(
                agent,
                {"input_tokens": 0.0, "cached_input_tokens": 0.0, "output_tokens": 0.0,
                 "reasoning_output_tokens": 0.0, "total_tokens": 0.0, "estimated_cost_usd": 0.0},
            )
            for key in grand:
                value = row.get(key)
                if isinstance(value, (int, float)):
                    bucket[key] = float(bucket.get(key, 0.0)) + float(value)
                    grand[key] = float(grand.get(key, 0.0)) + float(value)
        return {
            "ok": True,
            "source": "firestore" if self.available else firestore_reason(),
            "count": len(rows),
            "perAgent": totals,
            "total": grand,
        }


def build_firestore_store() -> FirestoreStore:
    """Build the store for the runtime, honoring env config."""
    return FirestoreStore(
        project=os.getenv("FIRESTORE_PROJECT_ID", "").strip(),
        emulator=bool(os.getenv("FIRESTORE_EMULATOR_HOST", "")),
        max_writes_per_refresh=int(
            os.getenv("FIRESTORE_MAX_WRITES_PER_REFRESH", str(DEFAULT_MAX_WRITES_PER_REFRESH))
        ),
    )
