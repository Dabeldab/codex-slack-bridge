#!/usr/bin/env python3
"""Phase 1E: Observability baseline — /healthz/orchestration endpoint.

Provides a unified health/observability endpoint exposing:
- Lane queue depths and scheduling stats
- Handoff pipeline latency (p50, p95, p99) and stale counts
- Worker pool saturation
- Verified route hit rates
- Agent session heartbeats
- Database connection pool health
"""

from __future__ import annotations

import json
import time
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from threading import RLock

try:
    from .cloud_sql_state import CloudSqlBridgeState
except ImportError:
    CloudSqlBridgeState = None  # type: ignore[misc,assignment]

try:
    from .lane_scheduler import LaneScheduler
except ImportError:
    LaneScheduler = None  # type: ignore[misc,assignment]

try:
    from .handoff_protocol import HandoffManager
except ImportError:
    HandoffManager = None  # type: ignore[misc,assignment]

try:
    from .worker_reliability import VerifiedRouteStore
except ImportError:
    VerifiedRouteStore = None  # type: ignore[misc,assignment]


@dataclass
class OrchestrationHealth:
    """Aggregated health snapshot."""
    timestamp: float
    status: str  # "healthy", "degraded", "critical"
    
    # Lane scheduler
    lane_stats: Dict[str, Any] = field(default_factory=dict)
    total_queued: int = 0
    total_running: int = 0
    
    # Handoff pipeline
    handoff_stats: Dict[str, Any] = field(default_factory=dict)
    stale_handoffs: int = 0
    handoff_latency_p50: float = 0.0
    handoff_latency_p95: float = 0.0
    handoff_latency_p99: float = 0.0
    
    # Verified routes
    verified_route_stats: Dict[str, Any] = field(default_factory=dict)
    
    # Worker pool
    worker_pool_stats: Dict[str, Any] = field(default_factory=dict)
    
    # Database
    db_pool_stats: Dict[str, Any] = field(default_factory=dict)
    
    # Agent sessions
    agent_sessions: Dict[str, Any] = field(default_factory=dict)
    
    # Issues
    warnings: List[str] = field(default_factory=list)
    critical_issues: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "timestamp_iso": datetime.fromtimestamp(self.timestamp).isoformat(),
            "status": self.status,
            "lanes": self.lane_stats,
            "total_queued": self.total_queued,
            "total_running": self.total_running,
            "handoffs": self.handoff_stats,
            "stale_handoffs": self.stale_handoffs,
            "handoff_latency": {
                "p50_ms": self.handoff_latency_p50 * 1000,
                "p95_ms": self.handoff_latency_p95 * 1000,
                "p99_ms": self.handoff_latency_p99 * 1000,
            },
            "verified_routes": self.verified_route_stats,
            "worker_pool": self.worker_pool_stats,
            "db_pool": self.db_pool_stats,
            "agent_sessions": self.agent_sessions,
            "warnings": self.warnings,
            "critical_issues": self.critical_issues,
        }
    
    def to_json(self) -> str:
        return json.dumps(self.to_dict(), separators=(",", ":"))


class ObservabilityCollector:
    """
    Collects orchestration health metrics from all subsystems.
    
    Designed to be instantiated once per process and queried by the
    /healthz/orchestration HTTP endpoint.
    """
    
    def __init__(
        self,
        *,
        bridge_state: Optional["CloudSqlBridgeState"] = None,
        lane_scheduler: Optional["LaneScheduler"] = None,
        handoff_manager: Optional["HandoffManager"] = None,
        verified_route_store: Optional["VerifiedRouteStore"] = None,
        worker_pool_executor=None,  # ThreadPoolExecutor from command_center_server
    ) -> None:
        self._bridge_state = bridge_state
        self._lane_scheduler = lane_scheduler
        self._handoff_manager = handoff_manager
        self._verified_route_store = verified_route_store
        self._worker_pool = worker_pool_executor
        self._lock = RLock()
        self._last_collection: Optional[OrchestrationHealth] = None
        self._collection_interval = 5.0  # seconds
        self._collector_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
    
    def collect(self) -> OrchestrationHealth:
        """Collect a full health snapshot."""
        now = time.time()
        health = OrchestrationHealth(timestamp=now, status="healthy")
        
        # Collect from each subsystem
        self._collect_lane_stats(health)
        self._collect_handoff_stats(health)
        self._collect_verified_route_stats(health)
        self._collect_worker_pool_stats(health)
        self._collect_db_pool_stats(health)
        self._collect_agent_sessions(health)
        
        # Determine overall status
        if health.critical_issues:
            health.status = "critical"
        elif health.warnings:
            health.status = "degraded"
        
        with self._lock:
            self._last_collection = health
        
        return health
    
    def get_latest(self) -> Optional[OrchestrationHealth]:
        with self._lock:
            return self._last_collection
    
    def start_background_collection(self) -> None:
        """Start background collection thread."""
        if self._collector_thread and self._collector_thread.is_alive():
            return
        self._stop_event.clear()
        self._collector_thread = threading.Thread(target=self._collection_loop, daemon=True)
        self._collector_thread.start()
    
    def stop_background_collection(self) -> None:
        self._stop_event.set()
        if self._collector_thread:
            self._collector_thread.join(timeout=2.0)
    
    def _collection_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self.collect()
            except Exception:
                pass  # Don't crash the collector
            self._stop_event.wait(self._collection_interval)
    
    # ---------- Subsystem collectors ----------
    
    def _collect_lane_stats(self, health: OrchestrationHealth) -> None:
        if self._lane_scheduler is None:
            health.warnings.append("LaneScheduler not available")
            return
        
        try:
            stats = self._lane_scheduler.get_all_stats()
            health.lane_stats = stats.get("lanes", {})
            
            total_queued = sum(ls.get("queued", 0) for ls in health.lane_stats.values())
            total_running = sum(ls.get("running", 0) for ls in health.lane_stats.values())
            health.total_queued = total_queued
            health.total_running = total_running
            
            # Check for saturation
            for lk, ls in health.lane_stats.items():
                max_cc = ls.get("max_concurrent", 1)
                running = ls.get("running", 0)
                queued = ls.get("queued", 0)
                if running >= max_cc and queued > 10:
                    health.warnings.append(f"Lane {lk} saturated: {running}/{max_cc} running, {queued} queued")
                if running >= max_cc and queued > 50:
                    health.critical_issues.append(f"Lane {lk} critically backed up: {queued} queued")
        except Exception as e:
            health.warnings.append(f"Lane stats collection failed: {e}")
    
    def _collect_handoff_stats(self, health: OrchestrationHealth) -> None:
        if self._handoff_manager is None or self._bridge_state is None:
            health.warnings.append("HandoffManager or bridge_state not available")
            return
        
        try:
            # Get handoff manager stats
            mgr_stats = self._handoff_manager.get_stats()
            health.handoff_stats = mgr_stats
            
            # Query detailed latency percentiles from DB
            with self._bridge_state._connect() as db:
                # Stale handoffs (pending > 30s)
                stale_result = db.execute(
                    """
                    SELECT COUNT(*) FROM nova_ops.handoffs
                    WHERE status = 'pending' 
                    AND ack_deadline < NOW() - INTERVAL '30 seconds'
                    AND created_at > NOW() - INTERVAL '1 hour'
                    """
                ).fetchone()
                health.stale_handoffs = stale_result[0] if stale_result else 0
                
                if health.stale_handoffs > 0:
                    health.warnings.append(f"{health.stale_handoffs} stale handoffs awaiting ACK")
                if health.stale_handoffs > 10:
                    health.critical_issues.append(f"{health.stale_handoffs} stale handoffs — pipeline blocked")
                
                # Latency percentiles (completed handoffs in last hour)
                latency_rows = db.execute(
                    """
                    SELECT 
                        EXTRACT(EPOCH FROM (acknowledged_at - created_at)) as ack_latency,
                        EXTRACT(EPOCH FROM (completed_at - created_at)) as total_latency
                    FROM nova_ops.handoffs
                    WHERE status IN ('completed', 'failed')
                    AND created_at > NOW() - INTERVAL '1 hour'
                    AND acknowledged_at IS NOT NULL
                    ORDER BY ack_latency
                    """
                ).fetchall()
                
                if latency_rows:
                    ack_latencies = [r[0] for r in latency_rows if r[0] is not None]
                    total_latencies = [r[1] for r in latency_rows if r[1] is not None]
                    
                    if ack_latencies:
                        health.handoff_latency_p50 = self._percentile(ack_latencies, 50)
                        health.handoff_latency_p95 = self._percentile(ack_latencies, 95)
                        health.handoff_latency_p99 = self._percentile(ack_latencies, 99)
                    
                    if total_latencies:
                        health.handoff_stats["total_latency_p50_ms"] = self._percentile(total_latencies, 50) * 1000
                        health.handoff_stats["total_latency_p95_ms"] = self._percentile(total_latencies, 95) * 1000
        except Exception as e:
            health.warnings.append(f"Handoff stats collection failed: {e}")
    
    def _collect_verified_route_stats(self, health: OrchestrationHealth) -> None:
        if self._verified_route_store is None or self._bridge_state is None:
            return
        
        try:
            with self._bridge_state._connect() as db:
                # Count routes per agent
                rows = db.execute(
                    """
                    SELECT route_data->>'agent' as agent, COUNT(*) as cnt,
                           AVG((route_data->>'success_count')::int) as avg_success
                    FROM nova_ops.verified_routes
                    GROUP BY route_data->>'agent'
                    """
                ).fetchall()
                
                stats = {}
                for agent, cnt, avg_succ in rows:
                    stats[agent] = {"route_count": cnt, "avg_success_count": float(avg_succ or 0)}
                
                health.verified_route_stats = stats
        except Exception:
            pass  # Non-critical
    
    def _collect_worker_pool_stats(self, health: OrchestrationHealth) -> None:
        if self._worker_pool is None:
            health.warnings.append("Worker pool executor not available")
            return
        
        try:
            # ThreadPoolExecutor doesn't expose queue depth directly
            # We can infer from thread count
            health.worker_pool_stats = {
                "max_workers": getattr(self._worker_pool, "_max_workers", "unknown"),
                "active_threads": len(getattr(self._worker_pool, "_threads", set())),
                "idle_threads": len(getattr(self._worker_pool, "_idle", [])),
            }
            
            # If we have access to internal queue
            work_queue = getattr(self._worker_pool, "_work_queue", None)
            if work_queue:
                health.worker_pool_stats["pending_tasks"] = work_queue.qsize()
                if work_queue.qsize() > 100:
                    health.warnings.append(f"Worker pool queue backing up: {work_queue.qsize()} tasks")
        except Exception as e:
            health.warnings.append(f"Worker pool stats failed: {e}")
    
    def _collect_db_pool_stats(self, health: OrchestrationHealth) -> None:
        if self._bridge_state is None:
            return
        
        try:
            pool = getattr(self._bridge_state, "_pool", None)
            if pool:
                health.db_pool_stats = {
                    "minconn": pool.minconn,
                    "maxconn": pool.maxconn,
                    "available": len(pool._pool) if hasattr(pool, "_pool") else "unknown",
                    "in_use": pool.maxconn - len(pool._pool) if hasattr(pool, "_pool") else "unknown",
                }
                
                # Check for exhaustion
                if hasattr(pool, "_pool") and len(pool._pool) == 0:
                    health.critical_issues.append("Database connection pool exhausted")
        except Exception as e:
            health.warnings.append(f"DB pool stats failed: {e}")
    
    def _collect_agent_sessions(self, health: OrchestrationHealth) -> None:
        if self._bridge_state is None:
            return
        
        try:
            with self._bridge_state._connect() as db:
                rows = db.execute(
                    """
                    SELECT agent, COUNT(*) as session_count,
                           MAX(EXTRACT(EPOCH FROM (NOW() - updated_at))) as max_staleness_sec
                    FROM nova_ops.agent_sessions
                    GROUP BY agent
                    """
                ).fetchall()
                
                stats = {}
                for agent, cnt, staleness in rows:
                    stats[agent] = {
                        "active_sessions": cnt,
                        "max_staleness_seconds": float(staleness or 0),
                    }
                    if staleness and staleness > 300:  # 5 minutes
                        health.warnings.append(f"Agent {agent} session stale: {staleness:.0f}s")
                
                health.agent_sessions = stats
        except Exception:
            pass
    
    @staticmethod
    def _percentile(values: List[float], p: int) -> float:
        if not values:
            return 0.0
        idx = int(len(values) * p / 100)
        return values[min(idx, len(values) - 1)]


# ---------- HTTP endpoint integration (for command_center_server) ----------

def register_observability_endpoints(app, collector: ObservabilityCollector) -> None:
    """Register /healthz/orchestration and related endpoints on a Flask/FastAPI app."""
    
    # Try to detect framework
    try:
        from flask import jsonify, Response
        _HAS_FLASK = True
    except ImportError:
        _HAS_FLASK = False
    
    try:
        from fastapi import FastAPI
        _HAS_FASTAPI = True
    except ImportError:
        _HAS_FASTAPI = False
    
    def orchestration_health():
        health = collector.collect()
        return health.to_dict()
    
    def orchestration_health_json():
        health = collector.collect()
        return health.to_json()
    
    if _HAS_FLASK:
        # Flask
        @app.route("/healthz/orchestration")
        def flask_health():
            from flask import jsonify
            return jsonify(orchestration_health())
        
        @app.route("/healthz/orchestration/json")
        def flask_health_json():
            from flask import Response
            return Response(orchestration_health_json(), mimetype="application/json")
    
    elif _HAS_FASTAPI:
        # FastAPI
        @app.get("/healthz/orchestration")
        async def fastapi_health():
            return orchestration_health()
        
        @app.get("/healthz/orchestration/json")
        async def fastapi_health_json():
            from fastapi.responses import Response
            return Response(content=orchestration_health_json(), media_type="application/json")
    
    else:
        # Generic WSGI/ASGI — user must wire manually
        pass


# ---------- Convenience factory ----------

def create_observability_collector(
    *,
    bridge_state: Optional["CloudSqlBridgeState"] = None,
    agents_yaml_path: Optional[str] = None,
    worker_pool_executor=None,
) -> ObservabilityCollector:
    """Factory that wires all subsystems together."""
    
    lane_scheduler = None
    handoff_manager = None
    verified_route_store = None
    
    if bridge_state is not None:
        handoff_manager = HandoffManager(bridge_state=bridge_state)
    
    if agents_yaml_path and LaneScheduler is not None:
        try:
            from .lane_scheduler import build_lane_configs_from_agents_yaml
            configs = build_lane_configs_from_agents_yaml(agents_yaml_path)
            lane_scheduler = LaneScheduler(configs, bridge_state=bridge_state)
            lane_scheduler.load_from_db()
        except Exception:
            pass
    
    if bridge_state is not None and VerifiedRouteStore is not None:
        try:
            # Need to import the registry paths from config
            import os
            base = os.path.dirname(os.path.dirname(__file__))
            verified_route_store = VerifiedRouteStore(
                sqlite_path=os.path.join(base, "data", "verified_routes.sqlite3"),
                pipeline_registry_path=os.path.join(base, "config", "pipelines.yaml"),
                tool_registry_path=os.path.join(base, "config", "tools.yaml"),
                bridge_state=bridge_state,
            )
        except Exception:
            pass
    
    collector = ObservabilityCollector(
        bridge_state=bridge_state,
        lane_scheduler=lane_scheduler,
        handoff_manager=handoff_manager,
        verified_route_store=verified_route_store,
        worker_pool_executor=worker_pool_executor,
    )
    
    return collector