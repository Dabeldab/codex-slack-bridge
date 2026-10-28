#!/usr/bin/env python3
"""Phase 1D: HandoffEnvelope — structured handoff protocol.

Defines a formal envelope for inter-agent handoffs with:
- Explicit acknowledgment protocol (ACK/NACK with deadlines)
- Handoff depth tracking (max 3 hops)
- Idempotency keys for exactly-once semantics
- Structured payload with typed fields
- Observability: latency tracking, stale detection
"""

from __future__ import annotations

import json
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, Optional, Literal
from threading import RLock

try:
    from .cloud_sql_state import CloudSqlBridgeState
except ImportError:
    CloudSqlBridgeState = None  # type: ignore[misc,assignment]


class HandoffStatus(str, Enum):
    PENDING = "pending"
    ACKNOWLEDGED = "acknowledged"
    COMPLETED = "completed"
    FAILED = "failed"
    EXPIRED = "expired"
    NACKED = "nacked"


class HandoffType(str, Enum):
    ESCALATION = "escalation"          # e.g., tickets -> billing
    DELEGATION = "delegation"          # e.g., claude -> jamie (research)
    REVIEW = "review"                  # e.g., any -> tickets (review gate)
    CONTINUATION = "continuation"      # same agent, next step


@dataclass(frozen=True)
class HandoffEnvelope:
    """
    Immutable handoff envelope — the wire format for inter-agent transfers.
    
    All fields are required for auditability and exactly-once processing.
    """
    # Identity
    handoff_id: str                    # UUID v4
    parent_job_id: str                 # originating job idempotency_key
    child_job_id: str                  # new job idempotency_key
    handoff_depth: int                 # 1, 2, or 3 (MAX_HANDOFF_DEPTH = 3)
    
    # Routing
    from_agent: str                    # e.g., "tickets", "claude"
    to_agent: str                      # e.g., "billing", "jamie"
    handoff_type: HandoffType
    
    # Payload (structured, not free text)
    summary: str                       # one-line human summary
    reason: str                        # why this handoff is needed
    required_capabilities: tuple[str, ...]  # what the target agent must support
    context: Dict[str, Any]            # arbitrary JSON context
    
    # Protocol
    ack_deadline: float                # Unix timestamp — ACK must arrive by then
    envelope_version: int = 1          # for future schema evolution
    
    # Idempotency
    idempotency_key: str = field(default_factory=lambda: f"handoff-{uuid.uuid4().hex[:16]}")
    
    # Metadata
    created_at: float = field(default_factory=time.time)
    trace_id: Optional[str] = None
    
    MAX_HANDOFF_DEPTH = 3
    DEFAULT_ACK_TIMEOUT_SECONDS = 30.0
    
    @classmethod
    def create(
        cls,
        *,
        parent_job_id: str,
        child_job_id: str,
        from_agent: str,
        to_agent: str,
        handoff_type: HandoffType,
        summary: str,
        reason: str,
        required_capabilities: tuple[str, ...] = (),
        context: Optional[Dict[str, Any]] = None,
        handoff_depth: int = 1,
        ack_timeout_seconds: float = DEFAULT_ACK_TIMEOUT_SECONDS,
        trace_id: Optional[str] = None,
    ) -> "HandoffEnvelope":
        """Factory method with validation."""
        if handoff_depth > cls.MAX_HANDOFF_DEPTH:
            raise ValueError(f"handoff_depth {handoff_depth} exceeds MAX_HANDOFF_DEPTH={cls.MAX_HANDOFF_DEPTH}")
        if from_agent == to_agent and handoff_type != HandoffType.CONTINUATION:
            raise ValueError("Same-agent handoff only allowed for CONTINUATION type")
        
        now = time.time()
        return cls(
            handoff_id=f"hf-{uuid.uuid4().hex[:16]}",
            parent_job_id=parent_job_id,
            child_job_id=child_job_id,
            handoff_depth=handoff_depth,
            from_agent=from_agent,
            to_agent=to_agent,
            handoff_type=handoff_type,
            summary=summary,
            reason=reason,
            required_capabilities=required_capabilities,
            context=context or {},
            ack_deadline=now + ack_timeout_seconds,
            trace_id=trace_id,
        )
    
    def to_json(self) -> str:
        """Serialize for wire transport (Slack, DB, etc.)."""
        d = asdict(self)
        d["handoff_type"] = self.handoff_type.value
        d["required_capabilities"] = list(self.required_capabilities)
        return json.dumps(d, separators=(",", ":"), sort_keys=True)
    
    @classmethod
    def from_json(cls, json_str: str) -> "HandoffEnvelope":
        """Deserialize from wire format."""
        d = json.loads(json_str)
        d["handoff_type"] = HandoffType(d["handoff_type"])
        d["required_capabilities"] = tuple(d.get("required_capabilities", []))
        return cls(**d)
    
    def is_expired(self, now: Optional[float] = None) -> bool:
        return (now or time.time()) > self.ack_deadline


@dataclass
class HandoffRecord:
    """Mutable runtime record for a handoff (stored in DB)."""
    envelope: HandoffEnvelope
    status: HandoffStatus = HandoffStatus.PENDING
    acknowledged_at: Optional[float] = None
    completed_at: Optional[float] = None
    error: Optional[str] = None
    ack_payload: Optional[Dict[str, Any]] = None
    retry_count: int = 0
    
    def to_db_row(self) -> Dict[str, Any]:
        """Convert to DB row for nova_ops.handoffs."""
        e = self.envelope
        return {
            "handoff_id": e.handoff_id,
            "parent_job_id": e.parent_job_id,
            "child_job_id": e.child_job_id,
            "from_agent": e.from_agent,
            "to_agent": e.to_agent,
            "status": self.status.value,
            "handoff_type": e.handoff_type.value,
            "handoff_depth": e.handoff_depth,
            "summary": e.summary,
            "reason": e.reason,
            "required_capabilities": json.dumps(list(e.required_capabilities)),
            "context": json.dumps(e.context),
            "ack_deadline": datetime.fromtimestamp(e.ack_deadline),
            "envelope_version": e.envelope_version,
            "idempotency_key": e.idempotency_key,
            "trace_id": e.trace_id,
            "acknowledged_at": datetime.fromtimestamp(self.acknowledged_at) if self.acknowledged_at else None,
            "completed_at": datetime.fromtimestamp(self.completed_at) if self.completed_at else None,
            "error": self.error,
            "ack_payload": json.dumps(self.ack_payload) if self.ack_payload else None,
            "retry_count": self.retry_count,
            "created_at": datetime.fromtimestamp(e.created_at),
        }


class HandoffManager:
    """
    Manages the handoff lifecycle with Cloud SQL persistence.
    
    Protocol:
    1. Producer calls create_handoff() → writes PENDING record, returns envelope
    2. Consumer calls acknowledge_handoff() → updates to ACKNOWLEDGED, returns success
    3. Consumer calls complete_handoff() / fail_handoff() → updates to COMPLETED/FAILED
    4. Background reaper calls reap_expired() → marks expired PENDING as EXPIRED
    """
    
    def __init__(self, bridge_state: Optional["CloudSqlBridgeState"] = None) -> None:
        self._bridge_state = bridge_state
        self._lock = RLock()
        self._pending_acks: Dict[str, HandoffRecord] = {}  # in-memory index for fast lookup
    
    def create_handoff(self, envelope: HandoffEnvelope) -> HandoffEnvelope:
        """Persist a new PENDING handoff and return the envelope."""
        if self._bridge_state is None:
            raise RuntimeError("HandoffManager requires CloudSqlBridgeState")
        
        record = HandoffRecord(envelope=envelope)
        
        with self._bridge_state._connect() as db:
            row = record.to_db_row()
            db.execute(
                """
                INSERT INTO nova_ops.handoffs (
                    handoff_id, parent_job_id, child_job_id, from_agent, to_agent,
                    status, handoff_type, handoff_depth, summary, reason,
                    required_capabilities, context, ack_deadline, envelope_version,
                    idempotency_key, trace_id, created_at
                ) VALUES (
                    %(handoff_id)s, %(parent_job_id)s, %(child_job_id)s, %(from_agent)s, %(to_agent)s,
                    %(status)s, %(handoff_type)s, %(handoff_depth)s, %(summary)s, %(reason)s,
                    %(required_capabilities)s, %(context)s, %(ack_deadline)s, %(envelope_version)s,
                    %(idempotency_key)s, %(trace_id)s, %(created_at)s
                )
                """,
                row,
            )
        
        with self._lock:
            self._pending_acks[envelope.handoff_id] = record
        
        return envelope
    
    def acknowledge_handoff(
        self,
        handoff_id: str,
        ack_payload: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Mark handoff as ACKNOWLEDGED by the target agent."""
        if self._bridge_state is None:
            return False
        
        with self._bridge_state._connect() as db:
            result = db.execute(
                """
                UPDATE nova_ops.handoffs
                SET status = 'acknowledged', acknowledged_at = NOW(), ack_payload = %s
                WHERE handoff_id = %s AND status = 'pending'
                """,
                (json.dumps(ack_payload) if ack_payload else None, handoff_id),
            )
            updated = result.rowcount > 0
        
        if updated:
            with self._lock:
                if handoff_id in self._pending_acks:
                    self._pending_acks[handoff_id].status = HandoffStatus.ACKNOWLEDGED
                    self._pending_acks[handoff_id].acknowledged_at = time.time()
                    self._pending_acks[handoff_id].ack_payload = ack_payload
        
        return updated
    
    def complete_handoff(self, handoff_id: str) -> bool:
        """Mark handoff as COMPLETED (child job finished successfully)."""
        if self._bridge_state is None:
            return False
        
        with self._bridge_state._connect() as db:
            result = db.execute(
                """
                UPDATE nova_ops.handoffs
                SET status = 'completed', completed_at = NOW()
                WHERE handoff_id = %s AND status IN ('pending', 'acknowledged')
                """,
                (handoff_id,),
            )
            updated = result.rowcount > 0
        
        with self._lock:
            if handoff_id in self._pending_acks:
                self._pending_acks[handoff_id].status = HandoffStatus.COMPLETED
                self._pending_acks[handoff_id].completed_at = time.time()
                # Keep for stale detection, but could remove
        
        return updated
    
    def fail_handoff(self, handoff_id: str, error: str) -> bool:
        """Mark handoff as FAILED."""
        if self._bridge_state is None:
            return False
        
        with self._bridge_state._connect() as db:
            result = db.execute(
                """
                UPDATE nova_ops.handoffs
                SET status = 'failed', completed_at = NOW(), error = %s
                WHERE handoff_id = %s AND status IN ('pending', 'acknowledged')
                """,
                (error, handoff_id),
            )
            updated = result.rowcount > 0
        
        with self._lock:
            if handoff_id in self._pending_acks:
                self._pending_acks[handoff_id].status = HandoffStatus.FAILED
                self._pending_acks[handoff_id].completed_at = time.time()
                self._pending_acks[handoff_id].error = error
        
        return updated
    
    def nack_handoff(self, handoff_id: str, reason: str) -> bool:
        """Negative acknowledgment — target agent cannot handle this."""
        if self._bridge_state is None:
            return False
        
        with self._bridge_state._connect() as db:
            result = db.execute(
                """
                UPDATE nova_ops.handoffs
                SET status = 'nacked', completed_at = NOW(), error = %s
                WHERE handoff_id = %s AND status = 'pending'
                """,
                (reason, handoff_id),
            )
            updated = result.rowcount > 0
        
        with self._lock:
            if handoff_id in self._pending_acks:
                self._pending_acks[handoff_id].status = HandoffStatus.NACKED
                self._pending_acks[handoff_id].completed_at = time.time()
                self._pending_acks[handoff_id].error = reason
        
        return updated
    
    def get_handoff(self, handoff_id: str) -> Optional[HandoffRecord]:
        """Get handoff record by ID."""
        with self._lock:
            if handoff_id in self._pending_acks:
                return self._pending_acks[handoff_id]
        
        if self._bridge_state is None:
            return None
        
        with self._bridge_state._connect() as db:
            row = db.execute(
                "SELECT * FROM nova_ops.handoffs WHERE handoff_id = %s",
                (handoff_id,),
            ).fetchone()
        
        if row is None:
            return None
        
        return self._row_to_record(row)
    
    def get_pending_for_agent(self, agent: str) -> list[HandoffRecord]:
        """Get all PENDING handoffs targeting an agent."""
        if self._bridge_state is None:
            return []
        
        with self._bridge_state._connect() as db:
            rows = db.execute(
                "SELECT * FROM nova_ops.handoffs WHERE to_agent = %s AND status = 'pending' ORDER BY created_at",
                (agent,),
            ).fetchall()
        
        return [self._row_to_record(row) for row in rows]
    
    def reap_expired(self, now: Optional[float] = None) -> int:
        """Mark expired PENDING handoffs as EXPIRED. Returns count."""
        now = now or time.time()
        if self._bridge_state is None:
            return 0
        
        deadline = datetime.fromtimestamp(now)
        with self._bridge_state._connect() as db:
            result = db.execute(
                """
                UPDATE nova_ops.handoffs
                SET status = 'expired', completed_at = NOW(), error = 'ACK deadline expired'
                WHERE status = 'pending' AND ack_deadline < %s
                """,
                (deadline,),
            )
            count = result.rowcount
        
        with self._lock:
            expired_ids = [hid for hid, rec in self._pending_acks.items() 
                          if rec.status == HandoffStatus.PENDING and rec.envelope.is_expired(now)]
            for hid in expired_ids:
                self._pending_acks[hid].status = HandoffStatus.EXPIRED
                self._pending_acks[hid].error = "ACK deadline expired"
        
        return count
    
    def get_stats(self) -> Dict[str, Any]:
        """Observability: handoff pipeline stats."""
        if self._bridge_state is None:
            return {"error": "no bridge_state"}
        
        with self._bridge_state._connect() as db:
            rows = db.execute(
                """
                SELECT status, COUNT(*), 
                       AVG(EXTRACT(EPOCH FROM (acknowledged_at - created_at))) as avg_ack_latency,
                       AVG(EXTRACT(EPOCH FROM (completed_at - created_at))) as avg_total_latency
                FROM nova_ops.handoffs
                WHERE created_at > NOW() - INTERVAL '1 hour'
                GROUP BY status
                """
            ).fetchall()
        
        stats = {row[0]: {"count": row[1], "avg_ack_latency": row[2], "avg_total_latency": row[3]} for row in rows}
        stats["pending_count"] = len([r for r in self._pending_acks.values() if r.status == HandoffStatus.PENDING])
        return stats
    
    def _row_to_record(self, row: tuple) -> HandoffRecord:
        """Convert DB row to HandoffRecord."""
        # row indices from SELECT * on nova_ops.handoffs
        envelope = HandoffEnvelope(
            handoff_id=row[0],
            parent_job_id=row[1],
            child_job_id=row[2],
            from_agent=row[3],
            to_agent=row[4],
            handoff_type=HandoffType(row[6]),
            handoff_depth=row[7],
            summary=row[8],
            reason=row[9],
            required_capabilities=tuple(json.loads(row[10] or "[]")),
            context=json.loads(row[11] or "{}"),
            ack_deadline=row[12].timestamp() if row[12] else 0,
            envelope_version=row[13],
            idempotency_key=row[14],
            trace_id=row[15],
            created_at=row[17].timestamp() if row[17] else 0,
        )
        record = HandoffRecord(envelope=envelope)
        record.status = HandoffStatus(row[5])
        record.acknowledged_at = row[16].timestamp() if row[16] else None
        record.completed_at = row[18].timestamp() if row[18] else None
        record.error = row[19]
        record.ack_payload = json.loads(row[20]) if row[20] else None
        record.retry_count = row[21] if len(row) > 21 else 0
        return record


# ---------- Integration helpers for command_center_server ----------

def create_taylor_handoff(
    manager: HandoffManager,
    *,
    parent_job_id: str,
    child_job_id: str,
    summary: str,
    reason: str,
    context: Optional[Dict[str, Any]] = None,
    trace_id: Optional[str] = None,
) -> HandoffEnvelope:
    """Create the standard TAYLOR_HANDOFF (tickets -> billing escalation)."""
    envelope = HandoffEnvelope.create(
        parent_job_id=parent_job_id,
        child_job_id=child_job_id,
        from_agent="tickets",
        to_agent="billing",
        handoff_type=HandoffType.ESCALATION,
        summary=summary,
        reason=reason,
        required_capabilities=("billing_write", "salesforce_access"),
        context=context,
        handoff_depth=1,
        trace_id=trace_id,
    )
    return manager.create_handoff(envelope)


def create_review_handoff(
    manager: HandoffManager,
    *,
    parent_job_id: str,
    child_job_id: str,
    from_agent: str,
    summary: str,
    reason: str,
    context: Optional[Dict[str, Any]] = None,
    trace_id: Optional[str] = None,
) -> HandoffEnvelope:
    """Create a review-gate handoff (any agent -> tickets for approval)."""
    envelope = HandoffEnvelope.create(
        parent_job_id=parent_job_id,
        child_job_id=child_job_id,
        from_agent=from_agent,
        to_agent="tickets",
        handoff_type=HandoffType.REVIEW,
        summary=summary,
        reason=reason,
        required_capabilities=("approval_gate",),
        context=context,
        handoff_depth=1,
        trace_id=trace_id,
    )
    return manager.create_handoff(envelope)