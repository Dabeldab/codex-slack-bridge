#!/usr/bin/env python3
"""Phase 1C: LaneScheduler — weighted fair queuing for agent lanes.

This module provides a production-grade lane scheduler that:
- Enforces per-lane weights and priorities
- Prevents noisy-neighbor starvation via deficit round-robin
- Provides observability hooks for queue depths, wait times, throughput
- Integrates with Cloud SQL for durable queue state
"""

from __future__ import annotations

import json
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from threading import RLock
from typing import Any, Dict, List, Optional, Tuple

try:
    from .cloud_sql_state import CloudSqlBridgeState
except ImportError:
    CloudSqlBridgeState = None  # type: ignore[misc,assignment]


@dataclass(frozen=True)
class LaneConfig:
    """Configuration for a single agent lane."""
    lane_key: str                    # e.g., "tickets", "billing", "claude"
    weight: int = 1                  # relative weight for fair queuing (1-100)
    max_concurrent: int = 1          # max jobs running simultaneously
    priority_boost: int = 0          # static priority boost (0-10)
    timeout_seconds: int = 300       # job timeout
    retry_limit: int = 3             # max retries per job
    backoff_base_seconds: float = 2.0


@dataclass
class QueuedJob:
    """A job waiting in a lane queue."""
    job_id: str
    lane_key: str
    weight: int = 1
    priority: int = 0
    enqueued_at: float = field(default_factory=time.time)
    payload: Dict[str, Any] = field(default_factory=dict)
    trace_id: Optional[str] = None


@dataclass
class LaneState:
    """Runtime state for a single lane."""
    config: LaneConfig
    running: int = 0
    deficit: int = 0                 # DRR deficit counter
    last_scheduled: float = 0
    total_scheduled: int = 0
    total_completed: int = 0
    total_failed: int = 0


class LaneScheduler:
    """
    Weighted fair queuing scheduler for agent lanes.
    
    Uses Deficit Round Robin (DRR) to ensure:
    - Lanes get proportional throughput based on weight
    - High-priority jobs jump ahead within their lane
    - No lane can starve others (bounded max deficit)
    """
    
    def __init__(
        self,
        lane_configs: List[LaneConfig],
        *,
        bridge_state: Optional["CloudSqlBridgeState"] = None,
        quantum: int = 1000,         # DRR quantum (deficit increment per round)
        max_deficit_factor: int = 10, # max deficit = weight * max_deficit_factor
    ) -> None:
        self._lock = RLock()
        self._lanes: Dict[str, LaneState] = {
            lc.lane_key: LaneState(config=lc) for lc in lane_configs
        }
        self._quantum = quantum
        self._max_deficit_factor = max_deficit_factor
        self._bridge_state = bridge_state
        
        # In-memory queue per lane (backed by Cloud SQL if available)
        self._queues: Dict[str, List[QueuedJob]] = {lk: [] for lk in self._lanes}
        
        # Observability
        self._enqueue_count = 0
        self._dequeue_count = 0
        self._requeue_count = 0
        
    # ---------- Public API ----------
    
    def enqueue(self, job: QueuedJob) -> bool:
        """Add a job to its lane queue. Returns True if enqueued."""
        with self._lock:
            if job.lane_key not in self._lanes:
                return False
            # Insert by priority (highest first), then FIFO
            queue = self._queues[job.lane_key]
            insert_idx = 0
            for i, qj in enumerate(queue):
                if qj.priority > job.priority:
                    insert_idx = i + 1
                elif qj.priority == job.priority and qj.enqueued_at <= job.enqueued_at:
                    insert_idx = i + 1
                else:
                    break
            queue.insert(insert_idx, job)
            self._enqueue_count += 1
            self._persist_queue(job.lane_key)
            return True
    
    def dequeue(self, lane_key: str) -> Optional[QueuedJob]:
        """Pop the next job from a specific lane (for lane-dedicated workers)."""
        with self._lock:
            return self._dequeue_from_lane(lane_key)
    
    def dequeue_any(self) -> Optional[Tuple[str, QueuedJob]]:
        """
        Fairly select the next lane and dequeue its highest-priority job.
        Returns (lane_key, job) or None if all queues empty.
        Uses Deficit Round Robin across lanes.
        """
        with self._lock:
            # Find eligible lanes (have jobs, not at max_concurrent)
            eligible = [
                (lk, ls) for lk, ls in self._lanes.items()
                if self._queues[lk] and ls.running < ls.config.max_concurrent
            ]
            if not eligible:
                return None
            
            # DRR selection
            best_lane = None
            best_deficit = -1
            
            for lk, ls in eligible:
                ls.deficit += ls.config.weight * self._quantum
                max_deficit = ls.config.weight * self._quantum * self._max_deficit_factor
                if ls.deficit > max_deficit:
                    ls.deficit = max_deficit
                if ls.deficit > best_deficit:
                    best_deficit = ls.deficit
                    best_lane = lk
            
            if best_lane is None:
                return None
            
            # Consume deficit for the job we're about to run
            ls = self._lanes[best_lane]
            job = self._queues[best_lane][0]
            ls.deficit -= job.weight * self._quantum
            ls.running += 1
            ls.last_scheduled = time.time()
            ls.total_scheduled += 1
            
            dequeued = self._queues[best_lane].pop(0)
            self._dequeue_count += 1
            self._persist_queue(best_lane)
            return best_lane, dequeued
    
    def mark_running(self, lane_key: str, job_id: str) -> bool:
        """Mark a job as running (for external dispatchers)."""
        with self._lock:
            if lane_key not in self._lanes:
                return False
            ls = self._lanes[lane_key]
            if ls.running >= ls.config.max_concurrent:
                return False
            ls.running += 1
            ls.last_scheduled = time.time()
            ls.total_scheduled += 1
            return True
    
    def mark_completed(self, lane_key: str, success: bool = True) -> None:
        """Mark a job as completed/failed."""
        with self._lock:
            if lane_key not in self._lanes:
                return
            ls = self._lanes[lane_key]
            ls.running = max(0, ls.running - 1)
            if success:
                ls.total_completed += 1
            else:
                ls.total_failed += 1
    
    def requeue(self, job: QueuedJob) -> bool:
        """Requeue a job (e.g., after retryable failure)."""
        with self._lock:
            if job.lane_key not in self._lanes:
                return False
            job.enqueued_at = time.time()  # fresh timestamp for FIFO
            self._requeue_count += 1
            return self.enqueue(job)
    
    def get_queue_depth(self, lane_key: str) -> int:
        with self._lock:
            return len(self._queues.get(lane_key, []))
    
    def get_lane_stats(self, lane_key: str) -> Dict[str, Any]:
        with self._lock:
            ls = self._lanes.get(lane_key)
            if not ls:
                return {}
            return {
                "lane_key": lane_key,
                "weight": ls.config.weight,
                "max_concurrent": ls.config.max_concurrent,
                "running": ls.running,
                "queued": len(self._queues.get(lane_key, [])),
                "deficit": ls.deficit,
                "total_scheduled": ls.total_scheduled,
                "total_completed": ls.total_completed,
                "total_failed": ls.total_failed,
                "success_rate": (
                    ls.total_completed / max(1, ls.total_scheduled)
                ) if ls.total_scheduled > 0 else 0.0,
            }
    
    def get_all_stats(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "lanes": {lk: self.get_lane_stats(lk) for lk in self._lanes},
                "total_enqueued": self._enqueue_count,
                "total_dequeued": self._dequeue_count,
                "total_requeued": self._requeue_count,
                "quantum": self._quantum,
            }
    
    # ---------- Persistence (Cloud SQL) ----------
    
    def _persist_queue(self, lane_key: str) -> None:
        """Persist queue state to Cloud SQL lane_queue_items table."""
        if self._bridge_state is None:
            return
        try:
            with self._bridge_state._connect() as db:
                # Upsert lane_queues summary row
                queue = self._queues[lane_key]
                queue_json = json.dumps([
                    {
                        "job_id": q.job_id,
                        "weight": q.weight,
                        "priority": q.priority,
                        "enqueued_at": q.enqueued_at,
                        "trace_id": q.trace_id,
                    }
                    for q in queue
                ])
                db.execute(
                    """
                    INSERT INTO nova_ops.lane_queues (agent, queue, updated_at)
                    VALUES (%s, %s, NOW())
                    ON CONFLICT (agent) DO UPDATE SET
                        queue = EXCLUDED.queue,
                        updated_at = NOW()
                    """,
                    (lane_key, queue_json),
                )
                # Also upsert individual items for queryability
                for q in queue:
                    db.execute(
                        """
                        INSERT INTO nova_ops.lane_queue_items
                            (lane_key, job_id, weight, priority, enqueued_at)
                        VALUES (%s, %s, %s, %s, to_timestamp(%s))
                        ON CONFLICT (lane_key, job_id) DO UPDATE SET
                            weight = EXCLUDED.weight,
                            priority = EXCLUDED.priority,
                            enqueued_at = EXCLUDED.enqueued_at
                        """,
                        (lane_key, q.job_id, q.weight, q.priority, q.enqueued_at),
                    )
        except Exception:
            # Don't let persistence failures block scheduling
            pass
    
    def load_from_db(self) -> None:
        """Load queue state from Cloud SQL on startup."""
        if self._bridge_state is None:
            return
        try:
            with self._bridge_state._connect() as db:
                rows = db.execute(
                    "SELECT lane_key, job_id, weight, priority, EXTRACT(EPOCH FROM enqueued_at) "
                    "FROM nova_ops.lane_queue_items ORDER BY lane_key, priority DESC, enqueued_at"
                ).fetchall()
                for lk, jid, wt, prio, enq in rows:
                    if lk in self._lanes:
                        self._queues[lk].append(QueuedJob(
                            job_id=jid,
                            lane_key=lk,
                            weight=wt,
                            priority=prio,
                            enqueued_at=enq,
                        ))
        except Exception:
            pass
    
    # ---------- Internal ----------
    
    def _dequeue_from_lane(self, lane_key: str) -> Optional[QueuedJob]:
        queue = self._queues.get(lane_key)
        if not queue:
            return None
        job = queue.pop(0)
        self._dequeue_count += 1
        self._persist_queue(lane_key)
        return job


# ---------- Factory from agents.yaml ----------

def build_lane_configs_from_agents_yaml(agents_path: str) -> List[LaneConfig]:
    """Build lanes from the effective inherited roster, not raw YAML keys."""
    from .config import load_config
    import yaml
    with open(agents_path, "r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}
    if isinstance(raw.get("agents"), list):
        # Preserve standalone legacy scheduler fixtures; production uses maps.
        entries = [(str(row.get("name") or row.get("lane") or ""), row)
                   for row in raw["agents"] if isinstance(row, dict)]
        active = (raw.get("defaults") or {}).get("active_agents")
        if active is not None:
            entries = [(name, row) for name, row in entries if name in active]
    else:
        config = load_config(agents_path)
        entries = list(config.agents.items())
    configs = []
    for name, agent in entries:
        if str(agent.get("provider") or "").lower() == "disabled":
            continue
        lane = str(agent.get("lane") or name.removesuffix("_agent"))
        if not lane:
            raise ValueError("Scheduler lane name is empty")
        customer_lane = lane in {"tickets", "billing"}
        configs.append(LaneConfig(
            lane_key=lane,
            weight=10 if customer_lane else 5,
            max_concurrent=2 if customer_lane else 1,
            priority_boost=2 if customer_lane else 0,
        ))
    return configs


@contextmanager
def create_scheduler(
    agents_yaml_path: str,
    *,
    bridge_state: Optional["CloudSqlBridgeState"] = None,
) -> LaneScheduler:
    """Context manager for LaneScheduler lifecycle."""
    configs = build_lane_configs_from_agents_yaml(agents_yaml_path)
    scheduler = LaneScheduler(configs, bridge_state=bridge_state)
    scheduler.load_from_db()
    try:
        yield scheduler
    finally:
        # Persist final state
        for lk in scheduler._lanes:
            scheduler._persist_queue(lk)