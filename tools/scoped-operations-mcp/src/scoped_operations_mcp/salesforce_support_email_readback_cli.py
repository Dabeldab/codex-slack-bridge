from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from typing import Any, Collection

from .salesforce_client import (
    SalesforceScopeError,
    SalesforceSettings,
    SalesforceUnavailableError,
    ScopedSalesforceClient,
)


SUPPORT_TICKET_RECORD_TYPES = frozenset({"1. NOVA Classic", "2. Nova Wave"})
BILLING_CLOSURE_TICKET_RECORD_TYPES = frozenset(
    {"1. NOVA Classic", "2. Nova Wave", "3. Billing"}
)
READBACK_SOURCE = "nova-runtime:typed-live-salesforce-ticket-readback"
SALESFORCE_ID = re.compile(r"^[A-Za-z0-9]{15}(?:[A-Za-z0-9]{3})?$")
TICKET_NUMBER = re.compile(r"^\d{5,12}$")
SOURCE_EMAIL_ID = re.compile(r"^[A-Za-z0-9._:@+-]{1,186}$")
MAX_STDIN_BYTES = 8_192
READ_ACTION_FIELDS = frozenset(
    {
        "action",
        "ticketId",
        "ticketNumber",
        "accountId",
        "recordType",
        "sourceEmailId",
        "sourceKey",
    }
)
BILLING_CLOSURE_READ_ACTION_FIELDS = frozenset(
    {
        "action",
        "ticketId",
        "ticketNumber",
        "accountId",
        "recordType",
        "sourceEmailId",
        "sourceKey",
        "fileName",
        "sha256",
    }
)


def _required_salesforce_id(value: Any, field: str) -> str:
    clean = str(value or "").strip()
    if not SALESFORCE_ID.fullmatch(clean):
        raise SalesforceScopeError(f"{field} must be a 15- or 18-character Salesforce id")
    return clean


def _required_source_email_id(value: Any) -> str:
    clean = str(value or "").strip()
    if not SOURCE_EMAIL_ID.fullmatch(clean):
        raise SalesforceScopeError("sourceEmailId is invalid")
    return clean


def _checked_at_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def execute_support_email_ticket_readback(
    payload: dict[str, Any],
    *,
    client: ScopedSalesforceClient | None = None,
    allowed_record_types: Collection[str] = SUPPORT_TICKET_RECORD_TYPES,
) -> dict[str, Any]:
    """Read and compare one exact support-email ticket without exposing its contents."""

    action = str(payload.get("action") or "read_support_email_ticket").strip().casefold()
    if action == "preflight":
        if set(payload) - {"action"}:
            raise SalesforceScopeError("Preflight accepts only the action field")
        return {
            "ok": True,
            "action": "preflight",
            "accessMode": "typed_support_email_ticket_readback_only",
            "source": READBACK_SOURCE,
            "allowedRecordTypes": sorted(allowed_record_types),
            "readOnly": True,
            "arbitrarySalesforceAccess": False,
            "writesExposed": False,
            "emailSendExposed": False,
            "customerDataExposed": False,
            "supportedActions": [
                "read_support_email_ticket",
                "read_billing_closure_email_ticket",
            ],
        }
    if action == "read_billing_closure_email_ticket":
        return execute_billing_closure_email_ticket_readback(
            payload,
            client=client,
        )
    if action != "read_support_email_ticket":
        raise SalesforceScopeError("Unsupported deterministic Salesforce action")
    if set(payload) - READ_ACTION_FIELDS:
        raise SalesforceScopeError("Unsupported support-email ticket readback field")

    ticket_id = _required_salesforce_id(payload.get("ticketId"), "ticketId")
    ticket_number = str(payload.get("ticketNumber") or "").strip()
    if not TICKET_NUMBER.fullmatch(ticket_number):
        raise SalesforceScopeError("ticketNumber must be 5-12 digits")
    account_id = _required_salesforce_id(payload.get("accountId"), "accountId")
    record_type = str(payload.get("recordType") or "").strip()
    if record_type not in frozenset(allowed_record_types):
        raise SalesforceScopeError("recordType must be an exact support ticket record type")
    source_email_id = _required_source_email_id(payload.get("sourceEmailId"))
    source_key = str(payload.get("sourceKey") or "").strip()
    expected_source_key = f"support-email:{source_email_id}"
    if source_key != expected_source_key:
        raise SalesforceScopeError("sourceKey must exactly match support-email:<sourceEmailId>")

    salesforce = client or ScopedSalesforceClient(SalesforceSettings.from_environment())
    comparison = salesforce.verify_support_email_ticket_claim(
        ticket_id=ticket_id,
        ticket_number=ticket_number,
        account_id=account_id,
        record_type=record_type,
        source_key=source_key,
        allowed_record_types=allowed_record_types,
    )
    if not isinstance(comparison, dict):
        raise SalesforceUnavailableError("Salesforce ticket readback was incomplete")
    is_closed = comparison.get("isClosed")

    reason_codes: list[str] = []
    if comparison.get("ticketIdMatches") is not True:
        reason_codes.append("ticket_id_mismatch")
    if comparison.get("ticketNumberMatches") is not True:
        reason_codes.append("ticket_number_mismatch")
    if comparison.get("accountIdMatches") is not True:
        reason_codes.append("account_id_mismatch")
    if comparison.get("accountEligible") is not True:
        reason_codes.append("account_ineligible")
    if comparison.get("recordTypeMatches") is not True:
        reason_codes.append("record_type_mismatch")
    if comparison.get("sourceKeyMatches") is not True:
        reason_codes.append("source_key_mismatch")
    if not isinstance(is_closed, bool):
        reason_codes.append("open_status_unavailable")
    elif is_closed:
        reason_codes.append("ticket_closed")

    if "open_status_unavailable" in reason_codes:
        status = "unavailable"
    elif reason_codes == ["ticket_closed"]:
        status = "closed"
    elif reason_codes:
        status = "mismatch"
    else:
        status = "verified"

    return {
        "ok": status != "unavailable",
        "action": "read_support_email_ticket",
        "status": status,
        "verified": status == "verified",
        "source": READBACK_SOURCE,
        "checkedAtUtc": _checked_at_utc(),
        "ticketId": ticket_id,
        "ticketNumber": ticket_number,
        "accountId": account_id,
        "accountEligible": comparison.get("accountEligible") is True,
        "recordType": record_type,
        "sourceEmailId": source_email_id,
        "sourceKey": source_key,
        "isClosed": is_closed if isinstance(is_closed, bool) else None,
        "reasonCodes": reason_codes,
        "readOnly": True,
        "writesPerformed": False,
        "emailSent": False,
    }


def execute_billing_closure_email_ticket_readback(
    payload: dict[str, Any],
    *,
    client: ScopedSalesforceClient | None = None,
) -> dict[str, Any]:
    """Read one exact closure ticket plus EML digest without exposing contents."""

    if set(payload) - BILLING_CLOSURE_READ_ACTION_FIELDS:
        raise SalesforceScopeError("Unsupported billing-closure email readback field")
    ticket_id = _required_salesforce_id(payload.get("ticketId"), "ticketId")
    ticket_number = str(payload.get("ticketNumber") or "").strip()
    if not TICKET_NUMBER.fullmatch(ticket_number):
        raise SalesforceScopeError("ticketNumber must be 5-12 digits")
    account_id = _required_salesforce_id(payload.get("accountId"), "accountId")
    record_type = str(payload.get("recordType") or "").strip()
    if record_type not in BILLING_CLOSURE_TICKET_RECORD_TYPES:
        raise SalesforceScopeError("recordType is outside the closure-email ticket scope")
    source_email_id = _required_source_email_id(payload.get("sourceEmailId"))
    source_key = str(payload.get("sourceKey") or "").strip()
    if source_key and source_key != f"billing-closure-email:{source_email_id}":
        raise SalesforceScopeError(
            "sourceKey must be blank or exactly match billing-closure-email:<sourceEmailId>"
        )
    file_name = str(payload.get("fileName") or "").strip()
    if (
        not file_name
        or len(file_name) > 180
        or "/" in file_name
        or "\\" in file_name
        or not file_name.casefold().endswith(".eml")
    ):
        raise SalesforceScopeError("fileName must be one bounded EML base name")
    sha256 = str(payload.get("sha256") or "").strip().lower()
    if not re.fullmatch(r"[a-f0-9]{64}", sha256):
        raise SalesforceScopeError("sha256 must be an exact lowercase digest")

    salesforce = client or ScopedSalesforceClient(SalesforceSettings.from_environment())
    comparison = salesforce.verify_billing_closure_email_ticket_claim(
        ticket_id=ticket_id,
        ticket_number=ticket_number,
        account_id=account_id,
        record_type=record_type,
        source_key=source_key,
        file_name=file_name,
        sha256=sha256,
    )
    if not isinstance(comparison, dict):
        raise SalesforceUnavailableError("Salesforce closure-email readback was incomplete")
    is_closed = comparison.get("isClosed")
    reason_codes: list[str] = []
    for field, reason in (
        ("ticketIdMatches", "ticket_id_mismatch"),
        ("ticketNumberMatches", "ticket_number_mismatch"),
        ("accountIdMatches", "account_id_mismatch"),
        ("accountEligible", "account_ineligible"),
        ("recordTypeMatches", "record_type_mismatch"),
        ("sourceKeyMatches", "source_key_mismatch"),
        ("attachmentDigestMatches", "attachment_digest_mismatch"),
    ):
        if comparison.get(field) is not True:
            reason_codes.append(reason)
    if comparison.get("attachmentTitleConflict") is True:
        reason_codes.append("attachment_title_conflict")
    if not isinstance(is_closed, bool):
        reason_codes.append("open_status_unavailable")
    elif is_closed:
        reason_codes.append("ticket_closed")

    if "open_status_unavailable" in reason_codes:
        status = "unavailable"
    elif reason_codes == ["ticket_closed"]:
        status = "closed"
    elif reason_codes:
        status = "mismatch"
    else:
        status = "verified"
    return {
        "ok": status != "unavailable",
        "action": "read_billing_closure_email_ticket",
        "status": status,
        "verified": status == "verified",
        "source": READBACK_SOURCE,
        "checkedAtUtc": _checked_at_utc(),
        "ticketId": ticket_id,
        "ticketNumber": ticket_number,
        "accountId": account_id,
        "accountEligible": comparison.get("accountEligible") is True,
        "recordType": record_type,
        "sourceEmailId": source_email_id,
        "sourceKey": source_key,
        "fileName": file_name,
        "sha256": sha256,
        "attachmentVerified": comparison.get("attachmentDigestMatches") is True,
        "isClosed": is_closed if isinstance(is_closed, bool) else None,
        "reasonCodes": reason_codes,
        "readOnly": True,
        "writesPerformed": False,
        "emailSent": False,
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
        result = execute_support_email_ticket_readback(payload)
    except (SalesforceScopeError, SalesforceUnavailableError) as exc:
        result = {"ok": False, "errorType": type(exc).__name__}
    except Exception as exc:  # Provider failures may contain customer or credential data.
        result = {"ok": False, "errorType": type(exc).__name__}
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
