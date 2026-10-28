from __future__ import annotations

import logging

"""Production reasoning runtime: GitHub credentials remain broker-only."""

from . import reasoning_relay_runtime as _base
from .reasoning_relay_broker_transport import BrokeredGitHubReasoningRelayTransport


logger = logging.getLogger(__name__)


def _safe_log_value(value: object, *, limit: int = 200) -> str:
    return str(value or "").replace("\r", " ").replace("\n", " ")[:limit]


class _BrokeredSettings:
    @classmethod
    def from_environment(cls):
        return None


class _BrokeredTransportFactory:
    def __new__(cls, _settings=None):
        # Cloud Run performs a relay health check once during instance startup.
        # Repeating the same GitHub App/token preflight for every agent job adds
        # multiple network round trips before a request can even be published
        # and was causing healthy jobs to fail on a 30-second wrapper timeout.
        transport = BrokeredGitHubReasoningRelayTransport.from_environment()
        logger.info("reasoning relay broker transport initialized for agent job")
        return transport


# Each agent job runs in its own disposable worker process, so this replacement
# is process-local and cannot affect another job or the Command Center parent.
_base.GitHubRelaySettings = _BrokeredSettings
_base.GitHubReasoningRelayTransport = _BrokeredTransportFactory
run_reasoning_relay_agent = _base.run_reasoning_relay_agent
