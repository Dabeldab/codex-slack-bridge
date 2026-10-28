"""Safe Codex failure categories; raw provider diagnostics stay in private traces."""
from __future__ import annotations

from typing import Any


def classify_codex_failure(returncode: int | None, details: str, *, timed_out: bool = False) -> str:
    if timed_out:
        return "worker_timeout"
    text = str(details or "").casefold()
    categories = (
        ("cloud_config_timeout", ("timed out waiting for cloud config bundle",)),
        ("cli_argument_error", ("unexpected argument", "unrecognized argument", "unknown option", "invalid value for")),
        ("model_unavailable", ("unsupported model", "model is not supported", "model not found", "model_not_found", "does not exist or you do not have access")),
        ("authentication_error", ("unauthorized", "authentication failed", "not logged in", "login required", "token expired", "refresh token", "invalid_grant")),
        ("usage_limit", ("rate limit", "rate_limit", "quota", "exhausted", "usage limit", "too many requests")),
        ("context_limit", ("context window exceeded", "context length exceeded", "prompt is too long", "input is too large")),
        ("session_unavailable", ("session not found", "could not find session", "failed to load session")),
        ("configuration_error", ("error loading config", "failed to load config", "error parsing config", "invalid configuration", "missing field `transport`")),
        ("transport_error", ("connection refused", "connection reset", "network is unreachable", "error sending request", "tls handshake")),
    )
    for category, patterns in categories:
        if any(pattern in text for pattern in patterns):
            return category
    if returncode is not None and returncode < 0:
        return "worker_signal"
    return "worker_exit"


def codex_failure_summary(returncode: int, details: str) -> str:
    category = classify_codex_failure(returncode, details)
    # Fixed text only: provider output may contain credentials or customer content.
    return (
        f"Codex could not complete this run (exit {returncode}; category={category}). "
        "Completion was not verified. Inspect the private process trace before retrying."
    )


def require_complete_codex_result(result: Any) -> None:
    """A timed-out model turn must never enter success or automatic retry handling."""
    if result.timed_out:
        raise RuntimeError(
            "Codex worker timed out (category=worker_timeout). Completion was not verified; "
            "reconcile the private action log before retrying."
        )
