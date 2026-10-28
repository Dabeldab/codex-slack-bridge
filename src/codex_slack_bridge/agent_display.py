from __future__ import annotations

import re
from typing import Any


_PUBLIC_AGENT_NAMES = {
    # Keep the compatibility lane ID in persisted jobs, routing, and capability
    # contracts. Only presentation surfaces translate it to Thor.
    "claude_agent": "Thor",
}
_THOR_LEGACY_REFERENCE_RE = re.compile(
    r"(?<![A-Za-z0-9])claude(?:[_ -]+)agent(?![A-Za-z0-9])",
    re.IGNORECASE,
)


def public_agent_name(value: Any, *, fallback: str = "agent") -> str:
    """Return the canonical user-facing name without changing the runtime ID."""

    name = str(value or "").strip()
    if not name:
        return fallback
    return _PUBLIC_AGENT_NAMES.get(name.casefold(), name)


def publicize_agent_references(value: Any) -> str:
    """Remove legacy Thor runtime labels from user-facing text."""

    return _THOR_LEGACY_REFERENCE_RE.sub("Thor", str(value or ""))
