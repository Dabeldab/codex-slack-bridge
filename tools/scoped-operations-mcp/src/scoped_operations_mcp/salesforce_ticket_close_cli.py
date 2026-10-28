from __future__ import annotations

import json
import re
import sys
from typing import Any, Collection

from .salesforce_client import (
    SalesforceScopeError,
    SalesforceSettings,
    SalesforceUnavailableError,
    ScopedSalesforceClient,
    ticket_chatter_update_body,
)


SUPPORT_TICKET_RECORD_TYPES = frozenset({"1. NOVA Classic", "2. Nova Wave"})
TICKET_NUMBER = re.compile(r"^\d{5,12}$")
IDEMPOTENCY_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9:._-]{0,239}$")
MAX_STDIN_BYTES = 16_384


def execute_ticket_close(
    payload: dict[str, Any],
    *,
    client: ScopedSalesforceClient | None = None,
    allowed_record_types: Collection[str] = SUPPORT_TICKET_RECORD_TYPES,
) -> dict[str, Any]:
    """Execute the one deterministic support-ticket close operation."""

    action = str(payload.get("action") or "close_ticket").strip().casefold()
    if action == "preflight":
        return {
            "ok": True,
            "action": "preflight",
            "lane": "tickets_agent",
            "accessMode": "typed_ticket_close_only",
            "allowedRecordTypes": sorted(allowed_record_types),
            "arbitrarySalesforceAccess": False,
            "emailSendExposed": False,
        }
    if action != "close_ticket":
        raise SalesforceScopeError("Unsupported deterministic Salesforce action")

    ticket_number = str(payload.get("ticketNumber") or "").strip()
    if not TICKET_NUMBER.fullmatch(ticket_number):
        raise SalesforceScopeError("ticketNumber must be 5-12 digits")
    resolution_note = str(payload.get("resolutionNote") or "").strip()
    if not resolution_note or len(resolution_note) > 700:
        raise SalesforceScopeError("resolutionNote must contain 1-700 characters")
    idempotency_key = str(payload.get("idempotencyKey") or "").strip()
    if not IDEMPOTENCY_KEY.fullmatch(idempotency_key):
        raise SalesforceScopeError("idempotencyKey is invalid")

    salesforce = client or ScopedSalesforceClient(SalesforceSettings.from_environment())
    lookup = salesforce.lookup("ticket", ticket_number, limit=3)
    matches = [
        record
        for record in (lookup.get("records") or [])
        if isinstance(record, dict) and str(record.get("Name") or "").strip() == ticket_number
    ]
    if len(matches) != 1:
        raise SalesforceScopeError("ticketNumber did not resolve to exactly one Salesforce ticket")
    ticket_id = str(matches[0].get("Id") or "").strip()

    # resolve_ticket performs a fresh scope/read check, duplicate Chatter
    # precheck, the close mutation, and authoritative readback.
    result = salesforce.resolve_ticket(
        ticket_id,
        ticket_chatter_update_body(
            update=resolution_note,
        ),
        allowed_record_types=allowed_record_types,
    )
    if result.get("closed") is not True or result.get("resolutionPresent") is not True:
        raise SalesforceUnavailableError("Ticket close readback was not verified")
    readback = result.get("readback") if isinstance(result.get("readback"), dict) else {}
    return {
        "ok": True,
        "action": "close_ticket",
        "ticketNumber": ticket_number,
        "ticketId": ticket_id,
        "idempotencyKey": idempotency_key,
        "updated": bool(result.get("updated")),
        "duplicate": bool(result.get("duplicate")),
        "closed": True,
        "resolutionPresent": True,
        "resolutionSurface": "Chatter",
        "ticketClosedDate": str(readback.get("Ticket_Closed_Date__c") or ""),
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
        result = execute_ticket_close(payload)
    except (SalesforceScopeError, SalesforceUnavailableError) as exc:
        result = {"ok": False, "errorType": type(exc).__name__, "message": str(exc)}
    except Exception as exc:  # Provider messages may contain sensitive data.
        result = {"ok": False, "errorType": type(exc).__name__}
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
