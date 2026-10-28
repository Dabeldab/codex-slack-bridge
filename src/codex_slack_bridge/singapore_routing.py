from __future__ import annotations

import re
from enum import Enum
from typing import Any, Mapping


_RUN_WORDS = {
    "check",
    "do",
    "execute",
    "process",
    "rerun",
    "retry",
    "run",
    "scan",
    "start",
}
_SINGAPORE_ALIASES = {
    "singapore",
    "singapor",
    "singapre",
    "singapoor",
    "singpore",
}


class SingaporeIntent(str, Enum):
    """Mutually exclusive routing outcomes for Singapore-related requests."""

    NEW_INTERFACE_TICKET = "new_interface_ticket"
    REACTIVATION = "reactivation"
    ROUTINE_OPERATION = "routine_operation"
    NOT_SINGAPORE = "not_singapore"


_REACTIVATION_PATTERNS = (
    re.compile(r"\breactivate\b", re.IGNORECASE),
    re.compile(r"\bre[ -]?enable\b", re.IGNORECASE),
    re.compile(
        r"\b(?:need|want|request(?:ed|ing)?)\b.{0,50}\breactivat(?:e|ing|ion)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\breactivation\b.{0,30}\b(?:needed|required|requested|approved)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\b(?:enable|resume|restart|restore)\b.{0,60}\b(?:integration|interface)\b", re.IGNORECASE),
    re.compile(r"\b(?:turn|switch)\b.{0,30}\bback\s+on\b", re.IGNORECASE),
    re.compile(r"\bstart\b.{0,60}\b(?:integration|interface)\b.{0,20}\bagain\b", re.IGNORECASE),
)

_NEW_INTERFACE_PATTERNS = (
    re.compile(
        r"\b(?:create|build|implement|provision|onboard|add|set\s*up)\b\s*"
        r"(?:a|an|the)?\s*(?:brand\s+)?(?:new\s+)?(?:singapore\s+)?"
        r"(?:integration|interface)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:start|make|need|want|request(?:ed|ing)?)\b.{0,60}"
        r"\bnew\s+(?:singapore\s+)?(?:integration|interface)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bbrand[-\s]+new\s+(?:singapore\s+)?(?:integration|interface)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bnew\s+(?:singapore\s+)?(?:integration|interface)\b.{0,40}"
        r"\b(?:needed|required|requested|approved)\b",
        re.IGNORECASE,
    ),
)

_OPERATIONAL_ISSUE_PATTERNS = (
    re.compile(r"\bremediation\b", re.IGNORECASE),
    re.compile(
        r"\b(?:authentication|auth|password|credential|token|upload|submission|status)\b"
        r".{0,50}\b(?:fail(?:ed|ure)?|issue|problem|error|blocked?|rejected?|expired?|"
        r"retry|check(?:ed|ing)?|pending|change|update|reset)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:fail(?:ed|ure)?|issue|problem|error|blocked?|rejected?|expired?|retry|"
        r"check(?:ed|ing)?|pending|change|update|reset|new)\b.{0,50}"
        r"\b(?:authentication|auth|password|credential|token|upload|submission|status)\b",
        re.IGNORECASE,
    ),
)

_FAILED_CACHE_STATUSES = {
    "blocked",
    "error",
    "failed",
    "gmail_unavailable",
    "zoom_unavailable",
}


def classify_singapore_intent(text: str) -> SingaporeIntent:
    """Classify intent without treating operational failures as new work.

    Reactivation wins over new-interface wording because an explicit request to
    restore a retired interface is not a request to build a second interface.
    Every other Singapore mention is routine/background-service context.
    """

    normalized = " ".join(str(text or "").split())
    words = re.findall(r"[a-z0-9]+", normalized.lower())
    if not words or not any(_looks_like_singapore(word) for word in words):
        return SingaporeIntent.NOT_SINGAPORE
    if any(pattern.search(normalized) for pattern in _REACTIVATION_PATTERNS):
        return SingaporeIntent.REACTIVATION
    if any(pattern.search(normalized) for pattern in _NEW_INTERFACE_PATTERNS):
        return SingaporeIntent.NEW_INTERFACE_TICKET
    if any(pattern.search(normalized) for pattern in _OPERATIONAL_ISSUE_PATTERNS):
        return SingaporeIntent.ROUTINE_OPERATION
    return SingaporeIntent.ROUTINE_OPERATION


def is_singapore_run_request(text: str) -> bool:
    """Return true only for an explicit operation or reactivation request."""
    intent = classify_singapore_intent(text)
    if intent is SingaporeIntent.REACTIVATION:
        # Reactivation is background-service configuration work, not a ticket
        # or an unconstrained agent task. Route it deterministically even when
        # the request does not also contain a generic run verb.
        return True
    if intent is not SingaporeIntent.ROUTINE_OPERATION:
        return False
    normalized = " ".join(str(text or "").split())
    if re.search(
        r"\bsend\s+(?:the\s+)?singapore(?:\s+routine)?\s+to\s+taylor\b",
        normalized,
        re.IGNORECASE,
    ):
        return True
    words = re.findall(r"[a-z0-9]+", str(text or "").lower())
    if not words or not any(word in _RUN_WORDS for word in words):
        return False
    return True


def format_singapore_chat_outcome(cache: Mapping[str, Any] | None) -> str:
    """Return one allowlisted status line, or blank for verified retired-only work.

    The formatter intentionally ignores summaries, errors, blockers, filenames,
    identifiers, and arbitrary detail text. This keeps credentials and raw
    runtime failures out of chat even when they are present in the cache.
    """

    payload = cache if isinstance(cache, Mapping) else {}
    upload = payload.get("upload") if isinstance(payload.get("upload"), Mapping) else {}
    details = upload.get("details") if isinstance(upload.get("details"), list) else []
    safe_details = [detail for detail in details if isinstance(detail, Mapping)]
    retired_details = [detail for detail in safe_details if _is_verified_retired_detail(detail)]

    config_changes = (
        payload.get("configChanges")
        if isinstance(payload.get("configChanges"), Mapping)
        else {}
    )
    config_updated = _safe_count(config_changes.get("updatedCount"))
    config_already_current = _safe_count(config_changes.get("alreadyCurrentCount"))
    new_interface_requests = _safe_count(config_changes.get("newInterfaceRequestCount"))
    retired_config_ignored = _safe_count(config_changes.get("retiredIgnoredCount"))
    automatic_replies = (
        payload.get("automaticReplies")
        if isinstance(payload.get("automaticReplies"), Mapping)
        else {}
    )
    nonsubmission_count = sum(1 for item in (payload.get("nonsubmissions") or []) if isinstance(item, Mapping))
    unconfigured_count = sum(
        1 for item in (payload.get("unconfiguredNonsubmissions") or []) if isinstance(item, Mapping)
    )
    ignored = payload.get("ignored") if isinstance(payload.get("ignored"), Mapping) else {}
    zero_sales_count = _safe_count(ignored.get("zeroSales"))
    unexplained_upload_failures = max(
        0,
        _safe_count(upload.get("failedMessageCount")) - len(retired_details),
    )
    structured_nonretired_issue = bool(unexplained_upload_failures) or any(
        (
            _safe_count(upload.get("authBlockedServerCount")),
            _safe_count(upload.get("unmatchedMessageCount")),
            _safe_count(config_changes.get("blockedCount")),
            _safe_count(automatic_replies.get("failedCount")),
        )
    )
    if (
        (safe_details or retired_config_ignored)
        and len(retired_details) == len(safe_details)
        and not structured_nonretired_issue
        and not any((config_updated, config_already_current, new_interface_requests))
        and not any((nonsubmission_count, unconfigured_count, zero_sales_count))
    ):
        return ""

    uploaded = _safe_count(upload.get("uploadedCount"))
    already_present = _safe_count(upload.get("skippedCount"))
    detail_failures = sum(
        1
        for detail in safe_details
        if not _is_verified_retired_detail(detail)
        and str(detail.get("result") or detail.get("status") or "").strip().lower()
        not in {"complete", "uploaded", "already_present"}
    )
    reported_failures = max(
        0,
        _safe_count(upload.get("failedMessageCount")) - len(retired_details),
        _safe_count(upload.get("unmatchedMessageCount")),
        _safe_count(upload.get("authBlockedServerCount")),
        _safe_count(config_changes.get("blockedCount")),
        _safe_count(automatic_replies.get("failedCount")),
        detail_failures,
    )

    cache_status = str(payload.get("status") or "").strip().lower()
    has_service_issue = bool(payload.get("blockers") or payload.get("issues")) or cache_status in _FAILED_CACHE_STATUSES
    if not any(
        (
            uploaded,
            already_present,
            reported_failures,
            config_updated,
            config_already_current,
            new_interface_requests,
            nonsubmission_count,
            unconfigured_count,
            zero_sales_count,
            has_service_issue,
        )
    ):
        return ""
    if cache_status in _FAILED_CACHE_STATUSES and not uploaded and not already_present:
        outcome = "FAILED"
    elif reported_failures or cache_status in _FAILED_CACHE_STATUSES | {"partial", "completed_with_issues"}:
        outcome = "PARTIAL"
    else:
        outcome = "SUCCESS"

    facts: list[str] = []
    if uploaded:
        facts.append(f"uploaded={uploaded}")
    if already_present:
        facts.append(f"already_present={already_present}")
    if reported_failures:
        facts.append(f"active_failures={reported_failures}")
    if config_updated:
        facts.append(f"config_updated={config_updated}")
    if config_already_current:
        facts.append(f"config_verified={config_already_current}")
    if new_interface_requests:
        facts.append(f"new_interface_requests={new_interface_requests}")
    if nonsubmission_count:
        facts.append(f"nonsubmissions={nonsubmission_count}")
    if unconfigured_count:
        facts.append(f"unconfigured={unconfigured_count}")
    if zero_sales_count:
        facts.append(f"zero_sales_read={zero_sales_count}")
    if has_service_issue and not reported_failures:
        facts.append("service_issue=1")
    return f"SINGAPORE | {outcome} | {'; '.join(facts)}"


def is_singapore_notification_policy_request(text: str, context: str = "") -> bool:
    """Fence notification/read-policy controls from becoming source-edit jobs."""
    request = " ".join(str(text or "").lower().split())
    combined = f"{request} {' '.join(str(context or '').lower().split())}".strip()
    words = re.findall(r"[a-z0-9]+", combined)
    if not any(_looks_like_singapore(word) for word in words):
        return False
    policy_topic = bool(
        re.search(r"\b(notification|notifications|alert|alerts)\b", combined)
        or re.search(r"\bmark(?:ed|ing)?\s+(?:them\s+)?read\b", combined)
    )
    if not policy_topic:
        return False
    return bool(
        re.search(
            r"\b(?:turn|switch)\s+(?:this|it|them|notifications?|alerts?)\s+off\b"
            r"|\bdisable\b"
            r"|\bsuppress\b"
            r"|\bstop\s+(?:sending|notifying|notifications?|alerts?)\b"
            r"|\b(?:do\s+not|don't|no\s+need\s+to)\s+(?:send|notify|alert)\b"
            r"|\bmark(?:ed|ing)?\s+(?:them\s+)?read\b",
            request,
        )
    )


def _is_verified_retired_detail(detail: Mapping[str, Any]) -> bool:
    result = str(detail.get("result") or detail.get("status") or "").strip().lower()
    return (
        detail.get("retiredServer") is True
        and detail.get("retirementVerified") is True
        and result in {"retired_ignored", "retired_machine_pending_handoff", "retired"}
    )


def _safe_count(value: Any) -> int:
    try:
        return max(0, min(int(value or 0), 1_000_000))
    except (TypeError, ValueError):
        return 0


def _looks_like_singapore(word: str) -> bool:
    if word in _SINGAPORE_ALIASES:
        return True
    # Catch one-character insertions, deletions, substitutions, or adjacent
    # transpositions without turning generic FTP questions into live runs.
    return len(word) >= 7 and _bounded_edit_distance(word, "singapore", maximum=1) <= 1


def _bounded_edit_distance(left: str, right: str, *, maximum: int) -> int:
    if abs(len(left) - len(right)) > maximum:
        return maximum + 1
    previous_previous: list[int] | None = None
    previous = list(range(len(right) + 1))
    for row_index, left_char in enumerate(left, start=1):
        current = [row_index]
        row_minimum = row_index
        for column_index, right_char in enumerate(right, start=1):
            substitution = previous[column_index - 1] + (left_char != right_char)
            value = min(
                previous[column_index] + 1,
                current[column_index - 1] + 1,
                substitution,
            )
            if (
                row_index > 1
                and column_index > 1
                and left_char == right[column_index - 2]
                and left[row_index - 2] == right_char
            ):
                value = min(value, previous_previous[column_index - 2] + 1) if previous_previous else value
            current.append(value)
            row_minimum = min(row_minimum, value)
        if row_minimum > maximum:
            return maximum + 1
        previous_previous, previous = previous, current
    return previous[-1]
