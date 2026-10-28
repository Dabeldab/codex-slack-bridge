from __future__ import annotations

"""Compatibility surface for Command Center observability.

The runtime has two observability concerns that evolved independently:
- durable bridge/job/session reconciliation and human-readable system status
- orchestration health for lanes, handoffs, worker pools, and Cloud SQL

A production-readiness change replaced the first implementation with the second,
while callers still imported both APIs from this module.  Keep the public import
surface stable and compose the two implementations explicitly.
"""

from .system_observability import (
    ACTIVE_JOB_STATUSES,
    build_system_status,
    format_system_status_for_slack,
    reconcile_system_jobs,
)
from .orchestration_observability import (
    ObservabilityCollector,
    OrchestrationHealth,
    create_observability_collector,
    register_observability_endpoints,
)

__all__ = [
    "ACTIVE_JOB_STATUSES",
    "ObservabilityCollector",
    "OrchestrationHealth",
    "build_system_status",
    "create_observability_collector",
    "format_system_status_for_slack",
    "reconcile_system_jobs",
    "register_observability_endpoints",
]
