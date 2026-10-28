from __future__ import annotations

# AgentChat/coding_agent 2026-07-13T18:24:18-04:00: treat catalog-only Singapore outcomes as terminal workflow state.

import hashlib
import json
import re
from pathlib import Path
from typing import Any

REMEDIATION_CATEGORIES = {
    "active_auth_failure",
    "active_transfer_failure",
    "new_interface_request",
    "unmatched_mapping",
    "verified_config_change",
}
SALESFORCE_ID_RE = re.compile(r"^[A-Za-z0-9]{15}(?:[A-Za-z0-9]{3})?$")
CONFIRMED_IDENTITY_STATUSES = {
    "confirmed",
    "confirmed_with_alias_mismatch",
    "confirmed_with_historic_ticket_location_mismatch",
}
IDENTITY_CAVEATS = {
    "alias_mismatch",
    "historic_location_mismatch_current_wins",
    "integration_retired_location_active_independent",
}
IDENTITY_PRODUCTS = {"Classic", "Wave"}
INTEGRATION_STATUSES = {"active_auth_failure", "retired"}
LOCATION_STATUSES = {"Active", "Inactive"}


def remediation_groups(
    cache: dict[str, Any],
    *,
    identity_map: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    upload = cache.get("upload") if isinstance(cache.get("upload"), dict) else {}
    for detail in upload.get("details") or []:
        if not isinstance(detail, dict):
            continue
        result = _norm(detail.get("result") or detail.get("status"))
        failure_category = _norm(detail.get("failureCategory"))
        configured = detail.get("configuredServer") is True
        retired = detail.get("retiredServer") is True
        if (
            result in {"server_auth_backoff", "server_auth_blocked"}
            and failure_category == "authentication"
            and configured
            and not retired
        ):
            candidates.append(_candidate("active_auth_failure", detail))
        # A verified canonical tombstone is terminal background-service state.
        # Retired interfaces are deliberately absent from remediation groups so
        # they cannot create tickets, reviews, retries, or operator notices.
        elif retired and detail.get("retirementVerified") is True:
            continue
        elif (
            result == "upload_or_verification_failed"
            and failure_category == "transfer_or_verification"
            and configured
            and not retired
        ):
            candidates.append(_candidate("active_transfer_failure", detail))
        elif (
            result in {"no_attachment", "unknown_machine"}
            and not configured
            and _single_machine_identifier(detail)
        ):
            candidates.append(_candidate("unmatched_mapping", detail))

    config_changes = cache.get("configChanges") if isinstance(cache.get("configChanges"), dict) else {}
    for detail in config_changes.get("results") or []:
        if not isinstance(detail, dict):
            continue
        status = _norm(detail.get("status"))
        request_kind = _norm(detail.get("requestKind"))
        if status == "new_interface_request" and request_kind == "new_interface":
            candidate = _candidate("new_interface_request", detail)
            candidate["requestKind"] = "new_interface"
            candidates.append(candidate)
            continue
        if status not in {"updated", "already_current"} or detail.get("configVerified") is not True:
            continue
        candidate = _candidate("verified_config_change", detail)
        candidate["changedFields"] = _identifier_list(detail.get("changedFields"), limit=40)
        candidate["requestKind"] = request_kind
        candidates.append(candidate)

    grouped: dict[tuple[str, str, str], dict[str, Any]] = {}
    for candidate in candidates:
        if not candidate["sourceMessageIds"] and not candidate["sourceThreadIds"]:
            continue
        key = (candidate["category"], candidate["machineId"], candidate["serverKey"])
        group = grouped.setdefault(
            key,
            {
                "category": candidate["category"],
                "machineId": candidate["machineId"],
                "serverKey": candidate["serverKey"],
                "sourceMessageIds": [],
                "sourceThreadIds": [],
                "changedFields": [],
                "requestKind": candidate.get("requestKind") or "",
            },
        )
        for field in ("sourceMessageIds", "sourceThreadIds", "changedFields"):
            for value in candidate.get(field) or []:
                if value and value not in group[field]:
                    group[field].append(value)

    result: list[dict[str, Any]] = []
    for group in grouped.values():
        for field in ("sourceMessageIds", "sourceThreadIds", "changedFields"):
            group[field].sort()
        digest_input = "|".join(
            [
                group["category"],
                group["machineId"],
                group["serverKey"],
                *group["sourceMessageIds"],
                *group["sourceThreadIds"],
            ]
        )
        digest = hashlib.sha256(digest_input.encode("utf-8")).hexdigest()[:24]
        label = _safe_key_part(group["machineId"] or group["serverKey"] or "source")
        group["stableKey"] = f"singapore-remediation:{group['category']}:{label}:{digest}"
        group["status"] = (
            "pending_ticket" if group["category"] == "new_interface_request" else "cataloged_no_ticket"
        )
        identity_machine_id = group["machineId"] or group["serverKey"]
        hint = sanitized_salesforce_identity_hint(
            identity_machine_id,
            (identity_map or {}).get(identity_machine_id),
        )
        if hint:
            group["salesforceIdentityHint"] = hint
        result.append(group)
    return sorted(result, key=lambda item: str(item.get("stableKey") or ""))


def load_salesforce_identity_map(path: Path) -> dict[str, dict[str, Any]]:
    """Load only confirmed, non-secret Salesforce identifiers from private state."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(raw, dict):
        return {}
    if isinstance(raw.get("machines"), dict):
        machines = raw["machines"]
    elif isinstance(raw.get("mappings"), dict):
        machines = raw["mappings"]
    else:
        machines = raw
    result: dict[str, dict[str, Any]] = {}
    for raw_machine_id, raw_hint in sorted(machines.items(), key=lambda item: str(item[0])):
        machine_id = _machine_identifier(raw_machine_id)
        hint = sanitized_salesforce_identity_hint(machine_id, raw_hint)
        if hint:
            result[machine_id] = hint
    return result


def sanitized_salesforce_identity_hint(machine_id: Any, raw_hint: Any) -> dict[str, Any]:
    """Return the deterministic allowlisted identity fields safe for an agent prompt."""
    clean_machine_id = _machine_identifier(machine_id)
    if not clean_machine_id or not isinstance(raw_hint, dict):
        return {}
    hinted_machine_id = _machine_identifier(raw_hint.get("machineId") or clean_machine_id)
    if hinted_machine_id != clean_machine_id:
        return {}
    status = _norm(raw_hint.get("identityStatus"))
    if status not in CONFIRMED_IDENTITY_STATUSES:
        return {}
    salesforce = raw_hint.get("salesforce") if isinstance(raw_hint.get("salesforce"), dict) else {}
    account = salesforce.get("account") if isinstance(salesforce.get("account"), dict) else {}
    location = salesforce.get("location") if isinstance(salesforce.get("location"), dict) else {}
    account_id = _salesforce_id(raw_hint.get("accountId") or account.get("id"))
    location_id = _salesforce_id(raw_hint.get("locationId") or location.get("id"))
    if not account_id or not location_id:
        return {}
    raw_product = raw_hint.get("product")
    if isinstance(raw_product, dict):
        raw_product = raw_product.get("ticketRecordType")
    product_text = str(raw_product or "").strip().lower()
    product = "Classic" if "classic" in product_text else "Wave" if "wave" in product_text else ""
    integration = raw_hint.get("integration") if isinstance(raw_hint.get("integration"), dict) else {}
    integration_status = _norm(raw_hint.get("integrationStatus") or integration.get("status"))
    raw_location_status = str(raw_hint.get("locationStatus") or location.get("status") or "").strip().title()
    location_status = raw_location_status if raw_location_status in LOCATION_STATUSES else ""
    caveat_set = {
        _norm(value)
        for value in (raw_hint.get("caveats") or [])
        if _norm(value) in IDENTITY_CAVEATS
    }
    if status == "confirmed_with_alias_mismatch":
        caveat_set.add("alias_mismatch")
    if status == "confirmed_with_historic_ticket_location_mismatch":
        caveat_set.add("historic_location_mismatch_current_wins")
    if integration_status == "retired" and location_status == "Active":
        caveat_set.add("integration_retired_location_active_independent")
    return {
        "machineId": clean_machine_id,
        "identityStatus": status,
        "accountId": account_id,
        "locationId": location_id,
        "product": product if product in IDENTITY_PRODUCTS else "",
        "integrationStatus": integration_status if integration_status in INTEGRATION_STATUSES else "",
        "locationStatus": location_status,
        "caveats": sorted(caveat_set),
    }


def merge_remediation_groups(cache: dict[str, Any], groups: list[dict[str, Any]]) -> dict[str, Any]:
    remediation = cache.get("remediation") if isinstance(cache.get("remediation"), dict) else {}
    existing = {
        str(item.get("stableKey") or ""): dict(item)
        for item in remediation.get("groups") or []
        if isinstance(item, dict) and str(item.get("stableKey") or "")
    }
    merged: list[dict[str, Any]] = []
    for group in groups:
        stable_key = str(group.get("stableKey") or "")
        prior = existing.get(stable_key) or {}
        current = dict(group)
        if _norm(current.get("category")) == "new_interface_request":
            for field in (
                "status",
                "ticketJobId",
                "ticket",
                "alex",
                "gmail",
                "attempts",
                "nextEligibleAtUtc",
                "updatedAtUtc",
                "blocker",
            ):
                if field in prior:
                    current[field] = prior[field]
        merged.append(current)
    seen = {str(item.get("stableKey") or "") for item in merged}
    for stable_key, prior in existing.items():
        if (
            stable_key in seen
            or _norm(prior.get("status")) == "handoff_complete"
            or _norm(prior.get("category")) != "new_interface_request"
        ):
            continue
        # A transient empty/partial mailbox scan must not erase a retryable or
        # already-queued handoff and reset its attempt/idempotency state.
        merged.append(prior)
    merged.sort(key=lambda item: str(item.get("stableKey") or ""))
    remediation.update({"schemaVersion": 1, "groups": merged})
    cache["remediation"] = remediation
    return cache


def _candidate(category: str, detail: dict[str, Any]) -> dict[str, Any]:
    machine_ids = [
        value for value in (_machine_identifier(item) for item in (detail.get("machineIds") or [])) if value
    ]
    machine_id = _machine_identifier(detail.get("machineId")) or (machine_ids[0] if len(set(machine_ids)) == 1 else "")
    server_keys = _identifier_list(detail.get("serverKeys"))
    server_key = _identifier(detail.get("serverKey")) or (server_keys[0] if len(server_keys) == 1 else "")
    message_id = _identifier(detail.get("sourceMessageId"), limit=300)
    thread_id = _identifier(detail.get("sourceThreadId"), limit=300)
    return {
        "category": category,
        "machineId": machine_id,
        "serverKey": server_key,
        "sourceMessageIds": [message_id] if message_id else [],
        "sourceThreadIds": [thread_id] if thread_id else [],
        "changedFields": [],
    }


def _single_machine_identifier(detail: dict[str, Any]) -> str:
    direct = _machine_identifier(detail.get("machineId"))
    if direct:
        return direct
    machine_ids = [
        machine_id
        for machine_id in (_machine_identifier(value) for value in (detail.get("machineIds") or []))
        if machine_id
    ]
    return machine_ids[0] if len(set(machine_ids)) == 1 else ""


def _identifier_list(value: Any, *, limit: int = 100) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value[:limit]:
        text = _identifier(item)
        if text and text not in result:
            result.append(text)
    return result


def _identifier(value: Any, *, limit: int = 200) -> str:
    return str(value or "").replace("\r", " ").replace("\n", " ").strip()[:limit]


def _machine_identifier(value: Any) -> str:
    text = str(value or "").strip()
    return text if re.fullmatch(r"\d{5,10}", text) else ""


def _salesforce_id(value: Any) -> str:
    text = str(value or "").strip()
    return text if SALESFORCE_ID_RE.fullmatch(text) else ""


def _safe_key_part(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]+", "_", str(value or "")).strip("._")[:60] or "source"


def _norm(value: Any) -> str:
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
