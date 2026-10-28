from __future__ import annotations

import hashlib
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from typing import Any

from .salesforce_client import (
    SUPPORT_QUALITY_TICKET_RECORD_TYPES,
    SalesforceScopeError,
    SalesforceSettings,
    SalesforceUnavailableError,
    ScopedSalesforceClient,
)


ACTION = "read_support_quality_ticket_projection"
SOURCE = "nova-runtime:typed-salesforce-support-quality-ticket-projection"
MAX_STDIN_BYTES = 32_768
MAX_WINDOW = timedelta(days=8)
READ_FIELDS = frozenset({"action", "startUtc", "endUtc", "roster"})
SALESFORCE_ID = re.compile(r"^[A-Za-z0-9]{15}(?:[A-Za-z0-9]{3})?$")

FIXED_ROSTER: tuple[tuple[str, str], ...] = (
    ("fjeUhJqaQROv4cHXUvdoqw", "Mordi Tech Support"),
    ("sD6yCgsRRniBcQVeyzuxwQ", "Darius Parlor - Nova Point of Sale"),
    ("ugVg1tUbRGukSXAlfwt5qQ", "Eddie Talal"),
    ("ZpCvM1zHTtGhhWw17ojXlA", "Oscar Ocampo"),
    ("rFkPTVXzQ4uk8tOMHaVQew", "Eduardo Brambila"),
    ("BJrCRiG_SbiGqy0Wgk--yw", "Oscar Umana"),
)
FIXED_ROSTER_PAYLOAD = tuple(
    {"id": representative_id, "name": name}
    for representative_id, name in FIXED_ROSTER
)
REPRESENTATIVE_ALIASES: dict[str, tuple[str, ...]] = {
    "fjeUhJqaQROv4cHXUvdoqw": ("Mordi Tech Support", "Mordi"),
    "sD6yCgsRRniBcQVeyzuxwQ": (
        "Darius Parlor - Nova Point of Sale",
        "Darius Parlor",
    ),
    "ugVg1tUbRGukSXAlfwt5qQ": ("Eddie Talal",),
    "ZpCvM1zHTtGhhWw17ojXlA": ("Oscar Ocampo",),
    "rFkPTVXzQ4uk8tOMHaVQew": ("Eduardo Brambila",),
    "BJrCRiG_SbiGqy0Wgk--yw": ("Oscar Umana",),
}
REP_FIELDS: tuple[tuple[str, str], ...] = (
    ("ticketCreatedBy", "Ticket_Created_by__c"),
    ("ticketClosedBy", "Ticket_Closed_by_Rep__c"),
    ("owner", "Owner"),
    ("createdBy", "CreatedBy"),
)
CATEGORY_FIELDS: tuple[tuple[str, str], ...] = (
    ("classicMain", "Tech_Main_Issue__c"),
    ("classicTechnical", "Technical_Issue__c"),
    ("waveMain", "NOVA_Wave_Issue__c"),
    ("waveTechnical", "NOVA_Wave_Technical_Issue__c"),
)


def _normalized_name(value: Any) -> str:
    text = " ".join(str(value or "").strip().casefold().split())
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def _alias_index() -> dict[str, str]:
    aliases: dict[str, str] = {}
    for representative_id, names in REPRESENTATIVE_ALIASES.items():
        for name in names:
            normalized = _normalized_name(name)
            if not normalized or (
                normalized in aliases and aliases[normalized] != representative_id
            ):
                raise RuntimeError("Support Quality representative aliases are ambiguous")
            aliases[normalized] = representative_id
    return aliases


ALIAS_TO_REPRESENTATIVE = _alias_index()


def _strict_utc(value: Any, field: str) -> tuple[str, datetime]:
    text = str(value or "").strip()
    if not text or len(text) > 80:
        raise SalesforceScopeError(f"{field} must be a bounded UTC timestamp")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SalesforceScopeError(f"{field} must be an ISO-8601 UTC timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise SalesforceScopeError(f"{field} must include an explicit UTC offset")
    normalized = parsed.astimezone(timezone.utc).replace(microsecond=0)
    return normalized.strftime("%Y-%m-%dT%H:%M:%SZ"), normalized


def _validate_roster(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list) or len(value) != len(FIXED_ROSTER_PAYLOAD):
        raise SalesforceScopeError("roster must be the exact fixed six-person roster")
    normalized: list[dict[str, str]] = []
    for index, (item, expected) in enumerate(zip(value, FIXED_ROSTER_PAYLOAD)):
        if not isinstance(item, dict) or set(item) != {"id", "name"}:
            raise SalesforceScopeError(f"roster[{index}] has an unsupported schema")
        candidate = {
            "id": str(item.get("id") or "").strip(),
            "name": str(item.get("name") or "").strip(),
        }
        if candidate != expected:
            raise SalesforceScopeError("roster must exactly match the fixed server roster")
        normalized.append(candidate)
    return normalized


def _relationship_name(record: dict[str, Any], field: str) -> str:
    value = record.get(field)
    if isinstance(value, dict):
        return str(value.get("Name") or "")
    return str(value or "")


def _representative_matches(record: dict[str, Any]) -> dict[str, set[str]]:
    matches: dict[str, set[str]] = {}
    for output_field, source_field in REP_FIELDS:
        raw = (
            _relationship_name(record, source_field)
            if source_field in {"Owner", "CreatedBy"}
            else str(record.get(source_field) or "")
        )
        representative_id = ALIAS_TO_REPRESENTATIVE.get(_normalized_name(raw))
        if representative_id:
            matches.setdefault(representative_id, set()).add(output_field)
    return matches


def _safe_category_label(kind: str, value: Any) -> str:
    # The category fields may be configurable Salesforce text/picklists. Do not
    # trust even a short value as non-customer data; expose only which fixed
    # server-owned category field was populated.
    return f"{kind}:present" if str(value or "").strip() else ""


def _ticket_reference(
    ticket_id: str,
    *,
    start_utc: str,
    end_utc: str,
) -> str:
    material = "\x00".join(
        ("support-quality-ticket-v1", start_utc, end_utc, ticket_id)
    )
    return f"ticket:{hashlib.sha256(material.encode('utf-8')).hexdigest()[:24]}"


def _empty_representative(identity: dict[str, str]) -> dict[str, Any]:
    return {
        **identity,
        "ticketCount": 0,
        "openCount": 0,
        "closedCount": 0,
        "closureMetadataPresentCount": 0,
        "documentationPresentCount": 0,
        "categoryPresentCount": 0,
        "missingDocumentationCount": 0,
        "missingCategoryCount": 0,
        "attributionCounts": {
            "ticketCreatedBy": 0,
            "ticketClosedBy": 0,
            "owner": 0,
            "createdBy": 0,
        },
        "issueCategories": [],
        "evidenceReferences": [],
    }


def execute_support_quality_ticket_projection(
    payload: dict[str, Any],
    *,
    client: ScopedSalesforceClient | None = None,
) -> dict[str, Any]:
    """Build a sanitized, read-only ticket-quality projection for Thor."""

    action = str(payload.get("action") or "").strip()
    if action == "preflight":
        if set(payload) != {"action"}:
            raise SalesforceScopeError("Preflight accepts only the action field")
        return {
            "ok": True,
            "action": "preflight",
            "accessMode": "typed_support_quality_ticket_projection_only",
            "source": SOURCE,
            "allowedRecordTypes": list(SUPPORT_QUALITY_TICKET_RECORD_TYPES),
            "fixedRosterCount": len(FIXED_ROSTER),
            "maxWindowDays": 8,
            "readOnly": True,
            "writesPerformed": False,
            "writesExposed": False,
            "genericQueryExposed": False,
            "ticketContentExposed": False,
            "customerDataExposed": False,
        }
    if action != ACTION:
        raise SalesforceScopeError("Unsupported deterministic Salesforce action")
    if set(payload) != READ_FIELDS:
        raise SalesforceScopeError("Support Quality projection requires only fixed fields")

    start_utc, start_value = _strict_utc(payload.get("startUtc"), "startUtc")
    end_utc, end_value = _strict_utc(payload.get("endUtc"), "endUtc")
    if end_value <= start_value:
        raise SalesforceScopeError("endUtc must be after startUtc")
    if end_value - start_value > MAX_WINDOW:
        raise SalesforceScopeError("Support Quality projection is limited to 8 days")
    roster = _validate_roster(payload.get("roster"))

    salesforce = client or ScopedSalesforceClient(SalesforceSettings.from_environment())
    source = salesforce.support_quality_ticket_projection_rows(
        start_utc=start_utc,
        end_utc=end_utc,
    )
    if not isinstance(source, dict) or not isinstance(source.get("records"), list):
        raise SalesforceUnavailableError("Salesforce Support Quality projection was incomplete")

    representatives = {
        identity["id"]: _empty_representative(identity)
        for identity in roster
    }
    categories: dict[str, set[str]] = {
        identity["id"]: set()
        for identity in roster
    }
    evidence: dict[str, set[str]] = {
        identity["id"]: set()
        for identity in roster
    }
    accepted_tickets = 0
    mapped_tickets = 0
    unmapped_tickets = 0
    discarded_rows = 0

    for raw in source.get("records", []):
        if not isinstance(raw, dict):
            discarded_rows += 1
            continue
        ticket_id = str(raw.get("Id") or "").strip()
        record_type = (
            raw.get("RecordType")
            if isinstance(raw.get("RecordType"), dict)
            else {}
        )
        record_type_name = str(record_type.get("Name") or "").strip()
        try:
            _, created_at = _strict_utc(raw.get("CreatedDate"), "CreatedDate")
        except SalesforceScopeError:
            discarded_rows += 1
            continue
        if (
            not SALESFORCE_ID.fullmatch(ticket_id)
            or record_type_name not in SUPPORT_QUALITY_TICKET_RECORD_TYPES
            or created_at < start_value
            or created_at >= end_value
        ):
            discarded_rows += 1
            continue

        accepted_tickets += 1
        matches = _representative_matches(raw)
        if not matches:
            unmapped_tickets += 1
            continue
        mapped_tickets += 1
        reference = _ticket_reference(
            ticket_id,
            start_utc=start_utc,
            end_utc=end_utc,
        )
        is_closed = raw.get("Is_Closed__c") is True
        documentation_present = bool(str(raw.get("Description__c") or "").strip())
        category_labels = {
            label
            for kind, field in CATEGORY_FIELDS
            if (label := _safe_category_label(kind, raw.get(field)))
        }
        category_present = bool(category_labels)
        closure_metadata_present = bool(
            is_closed
            and str(raw.get("Ticket_Closed_Date__c") or "").strip()
            and str(raw.get("Ticket_Closed_by_Rep__c") or "").strip()
        )

        for representative_id, attribution_fields in matches.items():
            result = representatives[representative_id]
            result["ticketCount"] += 1
            result["closedCount" if is_closed else "openCount"] += 1
            result["closureMetadataPresentCount"] += int(closure_metadata_present)
            result["documentationPresentCount"] += int(documentation_present)
            result["categoryPresentCount"] += int(category_present)
            result["missingDocumentationCount"] += int(not documentation_present)
            result["missingCategoryCount"] += int(not category_present)
            for field in attribution_fields:
                result["attributionCounts"][field] += 1
            categories[representative_id].update(category_labels)
            evidence[representative_id].add(reference)

    for representative_id, result in representatives.items():
        result["issueCategories"] = sorted(categories[representative_id])
        result["evidenceReferences"] = sorted(evidence[representative_id])

    row_limit_reached = source.get("rowLimitReached") is True
    return {
        "ok": True,
        "action": ACTION,
        "source": SOURCE,
        "window": {"startUtc": start_utc, "endUtc": end_utc},
        "recordTypes": list(SUPPORT_QUALITY_TICKET_RECORD_TYPES),
        "coverage": {
            "ticketCount": accepted_tickets,
            "mappedTicketCount": mapped_tickets,
            "unmappedTicketCount": unmapped_tickets,
            "discardedSourceRowCount": discarded_rows,
            "representativesCoveredCount": sum(
                result["ticketCount"] > 0 for result in representatives.values()
            ),
            "rowLimitReached": row_limit_reached,
        },
        "representatives": list(representatives.values()),
        "readOnly": True,
        "writesPerformed": False,
    }


def main() -> int:
    raw = sys.stdin.buffer.read(MAX_STDIN_BYTES + 1)
    if len(raw) > MAX_STDIN_BYTES:
        print(json.dumps({"ok": False, "errorType": "InputTooLarge"}, separators=(",", ":")))
        return 64
    try:
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, dict):
            raise SalesforceScopeError("Input must be a JSON object")
        result = execute_support_quality_ticket_projection(payload)
    except (SalesforceScopeError, SalesforceUnavailableError) as exc:
        result = {"ok": False, "errorType": type(exc).__name__}
    except Exception as exc:  # Provider errors may contain customer or credential data.
        result = {"ok": False, "errorType": type(exc).__name__}
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
