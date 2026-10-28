from __future__ import annotations

# AgentChat/coding_agent 2026-08-05T21:27:50Z

import hashlib
import json
import os
import re
import threading
import time
from collections import deque
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterator, Mapping
from urllib.parse import urlparse

import requests

from .maxio_tax_report import resolve_report_period, transform_invoices, write_tax_report


MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_REQUEST_BYTES = 1024 * 1024
COMPONENT_PAGE_SIZE = 100
MAX_COMPONENT_ROWS = 1000
INVOICE_UID = re.compile(r"^[A-Za-z0-9_-]{1,100}$")
COUPON_CODE = re.compile(r"^[A-Za-z0-9%@+_.-]{1,100}$")
IDEMPOTENCY_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,239}$")
TICKET_NUMBER = re.compile(r"^[0-9]{4,12}$")
ALLOWED_METHODS = frozenset({"GET", "POST", "PUT", "PATCH"})
READ_METHODS = frozenset({"GET"})
PRIVILEGED_PATH_PARTS = frozenset(
    {
        "api-keys",
        "api_keys",
        "credentials",
        "integrations",
        "oauth",
        "permissions",
        "roles",
        "settings",
        "sites",
        "users",
        "webhooks",
    }
)
DESTRUCTIVE_PATH_PARTS = frozenset({"delete", "destroy", "hard-delete", "purge"})
LOCAL_OPERATION_LOCK = threading.RLock()
ALLOCATION_FINANCIAL_CONTROLS = {
    "upgrade_charge": "none",
    "downgrade_credit": "none",
    "proration_upgrade_scheme": "no-prorate",
    "proration_downgrade_scheme": "none",
}
COMPONENT_PAYMENT_RECOVERY_CONTROLS = {
    "stage": {
        "upgrade_charge": "none",
        "downgrade_credit": "none",
        "proration_upgrade_scheme": "no-prorate",
        "proration_downgrade_scheme": "none",
        "payment_collection_method": "automatic",
        "initiate_dunning": False,
    },
    "charge": {
        "upgrade_charge": "full",
        "downgrade_credit": "none",
        "proration_upgrade_scheme": "no-prorate",
        "proration_downgrade_scheme": "none",
        "payment_collection_method": "automatic",
        "initiate_dunning": True,
    },
    "normalize": {
        "upgrade_charge": "none",
        "downgrade_credit": "none",
        "proration_upgrade_scheme": "no-prorate",
        "proration_downgrade_scheme": "none",
        "payment_collection_method": "automatic",
        "initiate_dunning": False,
    },
}
FINANCIAL_MUTATION_PATHS = (
    (re.compile(r"^/subscriptions\.json$"), "subscription_creation"),
    (
        re.compile(r"^/subscriptions/[0-9]+/allocations\.json$"),
        frozenset({"component_allocation", "component_payment_recovery"}),
    ),
    (
        re.compile(r"^/subscriptions/[0-9]+/charges\.json$"),
        frozenset({"partial_location_collection", "billing_cycle_recovery"}),
    ),
    (
        re.compile(r"^/subscriptions/[0-9]+/service_credits\.json$"),
        frozenset(
            {
                "manual_service_credit",
                "nova_integrated_promo_credit",
                "subscription_no_charge_reactivation",
            }
        ),
    ),
    (re.compile(r"^/subscriptions/[0-9]+/add_coupon\.json$"), "subscription_coupon"),
    (re.compile(r"^/invoices/[A-Za-z0-9_-]+/refunds\.json$"), "invoice_refund"),
    (re.compile(r"^/invoices/[A-Za-z0-9_-]+/void\.json$"), "invoice_void"),
    (
        re.compile(r"^/subscriptions/[0-9]+/reactivate\.json$"),
        frozenset(
            {"subscription_reactivation", "subscription_no_charge_reactivation"}
        ),
    ),
)
SUBSCRIPTION_UPDATE_PATH = re.compile(r"^/subscriptions/[0-9]+\.json$")
SUBSCRIPTION_PRODUCT_FIELDS = frozenset(
    {"product_id", "product_handle", "product_price_point_id"}
)
TYPED_NONFINANCIAL_MUTATION_PATHS = (
    (re.compile(r"^/subscriptions/metafields\.json$"), "location_custom_fields"),
    (re.compile(r"^/subscriptions/[0-9]+/metadata\.json$"), "location_metadata"),
    (
        re.compile(
            r"^/subscriptions/[0-9]+/payment_profiles/[0-9]+/change_payment_profile\.json$"
        ),
        "subscription_payment_profile_assignment",
    ),
    (
        re.compile(r"^/subscriptions/[0-9]+/request_payment_profiles_update\.json$"),
        "payment_profile_update_request",
    ),
)
ALWAYS_BLOCKED_FINANCIAL_MUTATION_PATHS = (
    re.compile(r"^/subscriptions/[0-9]+/service_credit_deductions\.json$"),
    re.compile(r"^/invoices/[A-Za-z0-9_-]+/credit_notes\.json$"),
    re.compile(r"^/invoices/[A-Za-z0-9_-]+/payments\.json$"),
)
CANCELED_SUBSCRIPTION_STATES = frozenset({"canceled", "cancelled"})
LOCATION_CUSTOM_FIELD_DEFINITIONS = (
    {
        "name": "Locations",
        "input_type": "text",
        "scope": {"csv": "1", "invoices": "0", "statements": "0", "portal": "0"},
    },
    {
        "name": "LocationComponentMap",
        "input_type": "text",
        "scope": {"csv": "1", "invoices": "0", "statements": "0", "portal": "0"},
    },
    {
        "name": "LocationNameMap",
        "input_type": "text",
        "scope": {"csv": "1", "invoices": "0", "statements": "0", "portal": "0"},
    },
    {
        "name": "LocationNamesDisplay",
        "input_type": "text",
        "scope": {"csv": "1", "invoices": "1", "statements": "1", "portal": "0"},
    },
)
LOCATION_CUSTOM_FIELD_NAMES = tuple(row["name"] for row in LOCATION_CUSTOM_FIELD_DEFINITIONS)
NOVA_INTEGRATED_MERCHANT_PROVIDERS = (
    "Worldpay",
    "Creditcall",
    "Authorize.net",
    "Propelr",
)

try:  # Linux production lock; Windows uses process-local serialization in tests.
    import fcntl
except ImportError:  # pragma: no cover - exercised by production Linux.
    fcntl = None  # type: ignore[assignment]


class MaxioScopeError(ValueError):
    """A request exceeded the fixed scoped Maxio operations."""


class MaxioUnavailableError(RuntimeError):
    """The scoped Maxio connection is unavailable."""


@dataclass(frozen=True)
class MaxioSettings:
    base_url: str
    api_key: str
    journal_path: Path = Path("/var/lib/nova/broker/maxio/operations.jsonl")
    report_output_dir: Path = Path("/var/lib/nova/broker/maxio-reports")

    @classmethod
    def from_environment(cls) -> "MaxioSettings":
        base_url = (os.getenv("CHARGIFY_BASE_URL") or os.getenv("CHARGIFY_SUBDOMAIN") or "").strip()
        if base_url and "://" not in base_url:
            base_url = f"https://{base_url}"
        return cls(
            base_url=base_url.rstrip("/"),
            api_key=(os.getenv("CHARGIFY_API_KEY") or os.getenv("MAXIO_API_KEY") or "").strip(),
            journal_path=Path(
                os.getenv("MAXIO_OPERATION_JOURNAL_PATH")
                or "/var/lib/nova/broker/maxio/operations.jsonl"
            ),
            report_output_dir=Path(
                os.getenv("MAXIO_REPORT_OUTPUT_DIR")
                or "/var/lib/nova/broker/maxio-reports"
            ),
        )


class ScopedMaxioClient:
    """Maxio client for bounded reads and journaled typed operations."""

    def __init__(self, settings: MaxioSettings, *, session: requests.Session | None = None) -> None:
        self.settings = settings
        self.session = session or requests.Session()

    def capability_status(self) -> dict[str, Any]:
        return {
            "ok": True,
            "accessMode": "bounded_reads_and_guarded_typed_writes",
            "credentialsConfigured": bool(self.settings.base_url and self.settings.api_key),
            "deleteExposed": False,
            "typedSubscriptionCancellationExposed": True,
            "genericHttpExposed": False,
            "mutationExposed": True,
            "permissionAdministrationExposed": False,
        }

    def health(self) -> dict[str, Any]:
        self._get("/subscriptions.json", params={"page": 1, "per_page": 1})
        return {"ok": True, "accessMode": "bounded_reads_and_guarded_typed_writes"}

    def customers_by_reference(self, reference: str, *, max_rows: int = 25) -> dict[str, Any]:
        clean_reference = _bounded_text(reference, "reference", 100)
        payload = self._get("/customers/lookup.json", params={"reference": clean_reference})
        return {
            "ok": True,
            "operation": "customers_by_reference",
            "records": [payload],
            "returned": 1,
            "truncated": False,
        }

    def customers_search(self, query: str, *, max_rows: int = 25) -> dict[str, Any]:
        clean_query = _bounded_text(query, "query", 200)
        rows = _bounded_rows(max_rows)
        payload = self._get(
            "/customers.json",
            params={"q": clean_query, "page": 1, "per_page": rows},
        )
        return _collection(payload, max_rows=rows, operation="customers_search")

    def customer(self, customer_id: int) -> dict[str, Any]:
        return self._single(
            f"/customers/{_positive_id(customer_id, 'customer_id')}.json",
            operation="customer",
        )

    def subscriptions_by_customer(self, customer_id: int, *, max_rows: int = 50) -> dict[str, Any]:
        rows = _bounded_rows(max_rows)
        payload = self._get(
            "/subscriptions.json",
            params={"customer_id": _positive_id(customer_id, "customer_id"), "page": 1, "per_page": rows},
        )
        return _collection(payload, max_rows=rows, operation="subscriptions_by_customer")

    def subscription(self, subscription_id: int) -> dict[str, Any]:
        return self._single(
            f"/subscriptions/{_positive_id(subscription_id, 'subscription_id')}.json",
            operation="subscription",
        )

    def nova_integrated_products(self, max_rows: int = 200) -> dict[str, Any]:
        """Read active zero-base-price Nova Integrated products and provider matches."""

        clean_limit = max(1, min(int(max_rows), 200))
        payload = self._get(
            "/products.json",
            params={"page": 1, "per_page": clean_limit, "include_archived": False},
        )
        products: list[dict[str, Any]] = []
        for product in _wrapped_records(payload, "product")[:clean_limit]:
            name = str(product.get("name") or "").strip()
            handle = str(product.get("handle") or "").strip()
            normalized = re.sub(r"[^a-z0-9]+", " ", f"{name} {handle}".casefold()).strip()
            if "nova integrated" not in normalized or product.get("archived_at"):
                continue
            try:
                base_price_cents = _product_base_price_cents(product)
            except MaxioUnavailableError:
                continue
            if base_price_cents != 0:
                continue
            products.append(
                {
                    "id": _required_integer_field(product, ("id",), "product ID"),
                    "name": name,
                    "handle": handle,
                    "merchantProvider": _product_merchant_provider(name, handle),
                    "basePriceCents": base_price_cents,
                    "interval": str(product.get("interval") or "").strip(),
                    "intervalUnit": str(product.get("interval_unit") or "").strip(),
                }
            )
        return {
            "ok": True,
            "operation": "nova_integrated_products",
            "allowedMerchantProviders": list(NOVA_INTEGRATED_MERCHANT_PROVIDERS),
            "products": sorted(
                [row for row in products if row["merchantProvider"]],
                key=lambda row: (row["merchantProvider"], row["id"]),
            ),
            "unmatchedProducts": sorted(
                [row for row in products if not row["merchantProvider"]],
                key=lambda row: row["id"],
            ),
            "fallbackProviderAllowed": False,
            "writesPerformed": False,
        }

    def subscription_creation_preview(
        self,
        customer_id: int,
        customer_reference: str,
        payment_profile_id: int,
        product_id: int,
        component_id: int,
        component_quantity: int,
        monthly_rate_cents: int,
        next_billing_at: str,
        ticket_number: str,
    ) -> dict[str, Any]:
        """Preview one future-billed monthly subscription with no initial financial effect."""

        plan = self._subscription_creation_plan(
            customer_id,
            customer_reference,
            payment_profile_id,
            product_id,
            component_id,
            component_quantity,
            monthly_rate_cents,
            next_billing_at,
            ticket_number,
        )
        return {
            "ok": True,
            "status": "preview",
            **plan,
            "previewHash": _plan_hash(plan),
            "applyRequired": plan["existingSubscription"] is None,
            "providerRequest": {
                "method": "POST",
                "path": "/subscriptions.json",
                "body": plan["providerPayload"],
            },
            "initialChargeAuthorized": False,
            "initialPaymentAuthorized": False,
            "creditAuthorized": False,
            "refundAuthorized": False,
            "prorationAuthorized": False,
            "financialEffectsAuthorized": False,
            "writesPerformed": False,
        }

    def apply_subscription_creation(
        self,
        customer_id: int,
        customer_reference: str,
        payment_profile_id: int,
        product_id: int,
        component_id: int,
        component_quantity: int,
        monthly_rate_cents: int,
        next_billing_at: str,
        ticket_number: str,
        *,
        preview_hash: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        """Create one unchanged future-billed subscription and verify it without charging now."""

        preview = self.subscription_creation_preview(
            customer_id,
            customer_reference,
            payment_profile_id,
            product_id,
            component_id,
            component_quantity,
            monthly_rate_cents,
            next_billing_at,
            ticket_number,
        )
        clean_hash = _required_preview_hash(preview_hash, preview["previewHash"])
        clean_key = _required_idempotency_key(idempotency_key)
        if not preview["applyRequired"]:
            return {
                **preview,
                "status": "completed",
                "updated": False,
                "duplicate": True,
                "verified": True,
                "idempotencyKey": clean_key,
                "readback": preview["existingSubscription"],
            }
        result = self.api_request(
            "POST",
            "/subscriptions.json",
            json_body=preview["providerPayload"],
            idempotency_key=clean_key,
            _typed_financial_operation="subscription_creation",
        )
        if not result.get("ok"):
            return {
                **preview,
                "status": "failed",
                "updated": False,
                "verified": False,
                "idempotencyKey": clean_key,
                "providerResult": result,
            }
        created = _subscription_record(result.get("body"))
        created_id = _required_integer_field(created, ("id",), "created subscription ID")
        readback = _subscription_record(
            self._get(f"/subscriptions/{created_id}.json")
        )
        self._verify_created_subscription(preview, readback)
        quantities = _component_quantities(
            self._get(
                f"/subscriptions/{created_id}/components.json",
                params={"page": 1, "per_page": 100},
            )
        )
        if quantities.get(preview["component"]["id"]) != preview["component"]["quantity"]:
            raise MaxioUnavailableError(
                "Maxio created the subscription but component readback did not match; "
                "do not retry until the subscription reference is read again"
            )
        balances = self.subscription_account_balances(created_id)["balances"]
        if (
            balances["openInvoiceBalanceCents"] != 0
            or balances["pendingInvoiceBalanceCents"] != 0
        ):
            raise MaxioUnavailableError(
                "Maxio created the future-billed subscription but its invoice balance was not zero; "
                "do not retry"
            )
        return {
            **preview,
            "status": "completed",
            "updated": True,
            "duplicate": bool(result.get("duplicate")),
            "verified": True,
            "idempotencyKey": clean_key,
            "subscriptionId": created_id,
            "readback": readback,
            "componentReadback": {
                "componentId": preview["component"]["id"],
                "allocatedQuantity": quantities[preview["component"]["id"]],
            },
            "balanceReadback": balances,
            "initialChargeAuthorized": False,
            "initialPaymentAuthorized": False,
            "financialEffectsAuthorized": False,
        }

    def location_custom_fields(self) -> dict[str, Any]:
        """Read the fixed site-level subscription metafield definitions used by Rainfall."""

        payload = self._get(
            "/subscriptions/metafields.json",
            params={"page": 1, "per_page": 200},
        )
        records = _metafield_records(payload)
        selected = [
            record
            for record in records
            if str(record.get("name") or "") in LOCATION_CUSTOM_FIELD_NAMES
        ]
        return {
            "ok": True,
            "operation": "location_custom_fields",
            "records": selected,
            "definedNames": sorted(str(record.get("name") or "") for record in selected),
            "requiredNames": list(LOCATION_CUSTOM_FIELD_NAMES),
            "readOnly": True,
            "writesPerformed": False,
        }

    def location_custom_fields_preview(self, ticket_number: str) -> dict[str, Any]:
        """Preview creation of only missing fixed subscription custom-field definitions."""

        clean_ticket = _ticket_number(ticket_number)
        current = self.location_custom_fields()
        existing = set(current["definedNames"])
        missing = [
            dict(definition)
            for definition in LOCATION_CUSTOM_FIELD_DEFINITIONS
            if definition["name"] not in existing
        ]
        plan = {
            "operation": "maxio_location_custom_fields",
            "ticketNumber": clean_ticket,
            "existingNames": sorted(existing),
            "missingDefinitions": missing,
            "requiredNames": list(LOCATION_CUSTOM_FIELD_NAMES),
        }
        return {
            "ok": True,
            "status": "preview",
            **plan,
            "previewHash": _plan_hash(plan),
            "applyRequired": bool(missing),
            "financialEffectsAuthorized": False,
            "writesPerformed": False,
        }

    def apply_location_custom_fields(
        self,
        ticket_number: str,
        *,
        preview_hash: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        """Create only missing fixed custom fields and verify all four definitions."""

        clean_key = _required_idempotency_key(idempotency_key)
        preview = self.location_custom_fields_preview(ticket_number)
        clean_hash = _required_preview_hash(preview_hash, preview["previewHash"])
        if not preview["applyRequired"]:
            return {
                **preview,
                "status": "completed",
                "updated": False,
                "duplicate": True,
                "verified": True,
                "idempotencyKey": clean_key,
                "readback": self.location_custom_fields(),
            }
        result = self.api_request(
            "POST",
            "/subscriptions/metafields.json",
            json_body={"metafields": preview["missingDefinitions"]},
            idempotency_key=clean_key,
            _typed_financial_operation="location_custom_fields",
        )
        if not result.get("ok"):
            return {
                **result,
                "verified": False,
                "previewHash": clean_hash,
                "financialEffectsAuthorized": False,
            }
        readback = self.location_custom_fields()
        if set(LOCATION_CUSTOM_FIELD_NAMES) - set(readback["definedNames"]):
            raise MaxioUnavailableError(
                "Maxio custom-field definition readback did not match; "
                "do not retry until the site definitions are read again"
            )
        return {
            **preview,
            "status": "completed",
            "updated": True,
            "duplicate": bool(result.get("duplicate")),
            "verified": True,
            "idempotencyKey": clean_key,
            "previewHash": clean_hash,
            "readback": readback,
            "financialEffectsAuthorized": False,
        }

    def subscription_location_metadata(self, subscription_id: int) -> dict[str, Any]:
        """Read the fixed location-to-component metadata for one exact subscription."""

        clean_subscription_id = _positive_id(subscription_id, "subscription_id")
        payload = self._get(
            f"/subscriptions/{clean_subscription_id}/metadata.json",
            params={"page": 1, "per_page": 200},
        )
        records = _metadata_records(payload)
        selected = [
            record
            for record in records
            if str(record.get("name") or "") in LOCATION_CUSTOM_FIELD_NAMES
        ]
        values = _unique_metadata_values(selected)
        return {
            "ok": True,
            "operation": "subscription_location_metadata",
            "subscriptionId": clean_subscription_id,
            "records": selected,
            "values": values,
            "missingNames": sorted(set(LOCATION_CUSTOM_FIELD_NAMES) - set(values)),
            "readOnly": True,
            "writesPerformed": False,
        }

    def subscription_location_mapping_preview(
        self,
        subscription_id: int,
        locations: list[dict[str, Any]],
        ticket_number: str,
    ) -> dict[str, Any]:
        """Preview a complete, verified location/component/name mapping with no billing effect."""

        clean_subscription_id = _positive_id(subscription_id, "subscription_id")
        clean_ticket = _ticket_number(ticket_number)
        normalized = _location_mapping_rows(locations)
        components_payload = self._get(
            f"/subscriptions/{clean_subscription_id}/components.json",
            params={"page": 1, "per_page": 100},
        )
        quantities = _component_quantities(components_payload)
        mapped_counts: dict[int, int] = {}
        for row in normalized:
            component_id = row["componentId"]
            if component_id not in quantities:
                raise MaxioScopeError(
                    f"component_id {component_id} is not present on subscription {clean_subscription_id}"
                )
            mapped_counts[component_id] = mapped_counts.get(component_id, 0) + 1
        mismatched = {
            component_id: {
                "mappedLocations": count,
                "allocatedQuantity": quantities[component_id],
            }
            for component_id, count in mapped_counts.items()
            if quantities[component_id] != count
        }
        if mismatched:
            raise MaxioScopeError(
                "location mappings must exactly match current component allocations; "
                f"repair allocations first: {mismatched}"
            )
        definitions = self.location_custom_fields()
        missing_definitions = sorted(
            set(LOCATION_CUSTOM_FIELD_NAMES) - set(definitions["definedNames"])
        )
        if missing_definitions:
            raise MaxioScopeError(
                "required Maxio custom fields are missing; run "
                f"maxio_location_custom_fields_preview/apply first: {missing_definitions}"
            )
        desired = _location_metadata_values(normalized)
        current = self.subscription_location_metadata(clean_subscription_id)
        changes = [
            {
                "name": name,
                "before": current["values"].get(name),
                "desired": desired[name],
            }
            for name in LOCATION_CUSTOM_FIELD_NAMES
            if current["values"].get(name) != desired[name]
        ]
        plan = {
            "operation": "maxio_subscription_location_mapping",
            "ticketNumber": clean_ticket,
            "subscriptionId": clean_subscription_id,
            "locations": normalized,
            "componentAllocationQuantities": {
                str(key): value for key, value in sorted(quantities.items())
            },
            "desiredMetadata": desired,
            "changes": changes,
        }
        return {
            "ok": True,
            "status": "preview",
            **plan,
            "previewHash": _plan_hash(plan),
            "applyRequired": bool(changes),
            "financialEffectsAuthorized": False,
            "writesPerformed": False,
        }

    def apply_subscription_location_mapping(
        self,
        subscription_id: int,
        locations: list[dict[str, Any]],
        ticket_number: str,
        *,
        preview_hash: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        """Apply one unchanged complete location mapping and verify all fixed metadata values."""

        clean_key = _required_idempotency_key(idempotency_key)
        preview = self.subscription_location_mapping_preview(
            subscription_id,
            locations,
            ticket_number,
        )
        clean_hash = _required_preview_hash(preview_hash, preview["previewHash"])
        if not preview["applyRequired"]:
            return {
                **preview,
                "status": "completed",
                "updated": False,
                "duplicate": True,
                "verified": True,
                "idempotencyKey": clean_key,
                "readback": self.subscription_location_metadata(subscription_id),
            }
        provider_results: list[dict[str, Any]] = []
        for index, change in enumerate(preview["changes"], start=1):
            derived_key = f"{clean_key}:{index}"
            if len(derived_key) > 240:
                derived_key = f"{clean_key[:170]}:{index}:{clean_hash[:32]}"
            result = self.api_request(
                "POST",
                f"/subscriptions/{preview['subscriptionId']}/metadata.json",
                json_body={
                    "metadata": {
                        "name": change["name"],
                        "value": change["desired"],
                    }
                },
                idempotency_key=derived_key,
                _typed_financial_operation="location_metadata",
            )
            provider_results.append(result)
            if not result.get("ok"):
                return {
                    **preview,
                    "status": "incomplete",
                    "updated": False,
                    "verified": False,
                    "idempotencyKey": clean_key,
                    "providerResults": provider_results,
                    "financialEffectsAuthorized": False,
                }
        readback = self.subscription_location_metadata(preview["subscriptionId"])
        if any(
            readback["values"].get(name) != desired
            for name, desired in preview["desiredMetadata"].items()
        ):
            raise MaxioUnavailableError(
                "Maxio subscription metadata readback did not match; "
                "do not retry until the subscription metadata is read again"
            )
        return {
            **preview,
            "status": "completed",
            "updated": True,
            "duplicate": all(bool(row.get("duplicate")) for row in provider_results),
            "verified": True,
            "idempotencyKey": clean_key,
            "providerResults": provider_results,
            "readback": readback,
            "financialEffectsAuthorized": False,
        }

    def subscription_cancellation_preview(
        self,
        subscription_id: int,
        ticket_number: str,
        reason: str,
    ) -> dict[str, Any]:
        """Preview one immediate cancellation without changing Maxio."""

        plan = self._subscription_cancellation_plan(subscription_id, ticket_number, reason)
        return {
            "ok": True,
            "status": "preview",
            "previewHash": plan["previewHash"],
            "subscriptionId": plan["subscriptionId"],
            "ticketNumber": plan["ticketNumber"],
            "customer": plan["customer"],
            "product": plan["product"],
            "currentState": plan["currentState"],
            "currentBalanceCents": plan["currentBalanceCents"],
            "nextAssessmentAt": plan["nextAssessmentAt"],
            "existingScheduledCancellation": plan["existingScheduledCancellation"],
            "cancellationMessage": plan["cancellationMessage"],
            "componentDeallocationSummary": plan["componentDeallocationSummary"],
            "locationComponentDeallocationCount": plan[
                "componentDeallocationSummary"
            ]["locationComponentDeallocationCount"],
            "timing": "immediate",
            "providerRequest": {
                "method": "DELETE",
                "path": f"/subscriptions/{plan['subscriptionId']}.json",
                "scheduleParametersOmitted": True,
            },
            "financialEffectsAuthorized": False,
            "automaticRefundAuthorized": False,
            "automaticCreditAuthorized": False,
            "invoiceVoidAuthorized": False,
            "customerEmailAuthorized": False,
            "applyRequired": plan["applyRequired"],
        }

    def apply_subscription_cancellation(
        self,
        subscription_id: int,
        ticket_number: str,
        reason: str,
        *,
        preview_hash: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        """Cancel one unchanged, zero-balance subscription immediately and verify it."""

        plan = self._subscription_cancellation_plan(subscription_id, ticket_number, reason)
        clean_hash = str(preview_hash or "").strip().lower()
        clean_key = str(idempotency_key or "").strip()
        if not IDEMPOTENCY_KEY.fullmatch(clean_key):
            raise MaxioScopeError("mutations require an idempotency_key of 8-240 safe characters")
        if not plan["applyRequired"]:
            return {
                "ok": True,
                "updated": False,
                "duplicate": True,
                "verified": True,
                "subscriptionId": plan["subscriptionId"],
                "ticketNumber": plan["ticketNumber"],
                "idempotencyKey": clean_key,
                "previewHash": plan["previewHash"],
                "requestedPreviewHash": clean_hash,
                "readback": plan["readback"],
                "componentDeallocationSummary": plan[
                    "componentDeallocationSummary"
                ],
                "locationComponentDeallocationCount": plan[
                    "componentDeallocationSummary"
                ]["locationComponentDeallocationCount"],
                "financialEffectsAuthorized": False,
                "customerEmailAuthorized": False,
            }
        if not re.fullmatch(r"[0-9a-f]{64}", clean_hash) or clean_hash != plan["previewHash"]:
            raise MaxioScopeError(
                "preview_hash does not match the current subscription state and cancellation request"
            )
        if plan["currentBalanceCents"] != 0:
            raise MaxioScopeError(
                "immediate subscription cancellation requires a verified zero balance; "
                "resolve the balance separately before cancellation"
            )

        result = self._cancel_subscription(
            plan["subscriptionId"],
            cancellation_message=plan["cancellationMessage"],
            idempotency_key=clean_key,
        )
        if not result.get("ok"):
            return {
                **result,
                "verified": False,
                "subscriptionId": plan["subscriptionId"],
                "ticketNumber": plan["ticketNumber"],
                "previewHash": clean_hash,
            }

        readback_plan = self._subscription_cancellation_plan(
            subscription_id,
            ticket_number,
            reason,
        )
        if readback_plan["applyRequired"]:
            raise MaxioUnavailableError(
                "Maxio cancellation readback did not show a canceled subscription; "
                "do not retry until the subscription is read again"
            )
        message_verified = (
            str(readback_plan["readback"].get("cancellation_message") or "").strip()
            == plan["cancellationMessage"]
        )
        return {
            "ok": True,
            "updated": not bool(result.get("duplicate")),
            "duplicate": bool(result.get("duplicate")),
            "verified": True,
            "subscriptionId": plan["subscriptionId"],
            "ticketNumber": plan["ticketNumber"],
            "idempotencyKey": clean_key,
            "previewHash": clean_hash,
            "timing": "immediate",
            "cancellationMessageVerified": message_verified,
            "readback": readback_plan["readback"],
            "componentDeallocationSummary": plan["componentDeallocationSummary"],
            "locationComponentDeallocationCount": plan[
                "componentDeallocationSummary"
            ]["locationComponentDeallocationCount"],
            "financialEffectsAuthorized": False,
            "customerEmailAuthorized": False,
        }

    # AgentChat/coding_agent 2026-08-07T13:31:00Z: keep the ordinary
    # zero-balance guard intact and provide a separate, fail-closed route for
    # terminating past-due service while retaining the exact open receivable.
    def past_due_subscription_cancellation_preview(
        self,
        subscription_id: int,
        ticket_number: str,
        reason: str,
    ) -> dict[str, Any]:
        """Preview cancellation of past-due service without changing its invoice."""

        plan = self._past_due_subscription_cancellation_plan(
            subscription_id,
            ticket_number,
            reason,
        )
        return {
            "ok": True,
            "status": "preview" if plan["applyRequired"] else "already_canceled",
            "previewHash": plan["previewHash"],
            "subscriptionId": plan["subscriptionId"],
            "ticketNumber": plan["ticketNumber"],
            "customer": plan["customer"],
            "product": plan["product"],
            "currentState": plan["currentState"],
            "balances": plan["balances"],
            "openInvoices": plan["openInvoices"],
            "cancellationMessage": plan["cancellationMessage"],
            "componentDeallocationSummary": plan["componentDeallocationSummary"],
            "timing": "immediate",
            "providerRequest": {
                "method": "DELETE",
                "path": f"/subscriptions/{plan['subscriptionId']}.json",
                "scheduleParametersOmitted": True,
            },
            "preserveOpenInvoiceRequired": True,
            "automaticRefundAuthorized": False,
            "automaticCreditAuthorized": False,
            "invoiceVoidAuthorized": False,
            "paymentRetryAuthorized": False,
            "customerEmailAuthorized": False,
            "applyRequired": plan["applyRequired"],
        }

    def apply_past_due_subscription_cancellation(
        self,
        subscription_id: int,
        ticket_number: str,
        reason: str,
        *,
        preview_hash: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        """Cancel past-due service and prove its receivable is unchanged."""

        plan = self._past_due_subscription_cancellation_plan(
            subscription_id,
            ticket_number,
            reason,
        )
        clean_hash = str(preview_hash or "").strip().lower()
        clean_key = str(idempotency_key or "").strip()
        if not IDEMPOTENCY_KEY.fullmatch(clean_key):
            raise MaxioScopeError("mutations require an idempotency_key of 8-240 safe characters")
        if not plan["applyRequired"]:
            return {
                "ok": True,
                "updated": False,
                "duplicate": True,
                "verified": True,
                "subscriptionId": plan["subscriptionId"],
                "ticketNumber": plan["ticketNumber"],
                "idempotencyKey": clean_key,
                "previewHash": plan["previewHash"],
                "requestedPreviewHash": clean_hash,
                "readback": plan["readback"],
                "balances": plan["balances"],
                "openInvoices": plan["openInvoices"],
                "openInvoicePreserved": True,
                "financialEffectsAuthorized": False,
            }
        if not re.fullmatch(r"[0-9a-f]{64}", clean_hash) or clean_hash != plan["previewHash"]:
            raise MaxioScopeError(
                "preview_hash does not match the current past-due subscription and receivable"
            )

        result = self._cancel_subscription(
            plan["subscriptionId"],
            cancellation_message=plan["cancellationMessage"],
            idempotency_key=clean_key,
        )
        if not result.get("ok"):
            return {
                **result,
                "verified": False,
                "subscriptionId": plan["subscriptionId"],
                "ticketNumber": plan["ticketNumber"],
                "previewHash": clean_hash,
            }

        readback_plan = self._past_due_subscription_cancellation_plan(
            subscription_id,
            ticket_number,
            reason,
        )
        if readback_plan["applyRequired"]:
            raise MaxioUnavailableError(
                "Maxio cancellation readback did not show a canceled subscription; "
                "do not retry until the subscription is read again"
            )
        if readback_plan["balances"] != plan["balances"]:
            raise MaxioUnavailableError(
                "the subscription canceled but its account balances changed; do not retry"
            )
        if readback_plan["openInvoices"] != plan["openInvoices"]:
            raise MaxioUnavailableError(
                "the subscription canceled but its open invoice changed; do not retry"
            )
        message_verified = (
            str(readback_plan["readback"].get("cancellation_message") or "").strip()
            == plan["cancellationMessage"]
        )
        return {
            "ok": True,
            "updated": not bool(result.get("duplicate")),
            "duplicate": bool(result.get("duplicate")),
            "verified": True,
            "subscriptionId": plan["subscriptionId"],
            "ticketNumber": plan["ticketNumber"],
            "idempotencyKey": clean_key,
            "previewHash": clean_hash,
            "timing": "immediate",
            "cancellationMessageVerified": message_verified,
            "readback": readback_plan["readback"],
            "balances": readback_plan["balances"],
            "openInvoices": readback_plan["openInvoices"],
            "openInvoicePreserved": True,
            "componentDeallocationSummary": plan["componentDeallocationSummary"],
            "financialEffectsAuthorized": False,
            "automaticRefundAuthorized": False,
            "automaticCreditAuthorized": False,
            "invoiceVoidAuthorized": False,
            "paymentRetryAuthorized": False,
            "customerEmailAuthorized": False,
        }

    def subscription_components(self, subscription_id: int, *, max_rows: int = 100) -> dict[str, Any]:
        rows = _bounded_rows(max_rows, ceiling=100)
        payload = self._get(
            f"/subscriptions/{_positive_id(subscription_id, 'subscription_id')}/components.json",
            params={"page": 1, "per_page": rows},
        )
        return _collection(payload, max_rows=rows, operation="subscription_components")

    def location_allocation_reconciliation(
        self,
        subscription_ids: list[int],
    ) -> dict[str, Any]:
        """Read complete location-component totals across exact Maxio subscriptions."""

        if not isinstance(subscription_ids, list) or not subscription_ids or len(subscription_ids) > 100:
            raise MaxioScopeError(
                "subscription_ids must contain 1-100 exact subscription IDs"
            )
        clean_ids: list[int] = []
        seen: set[int] = set()
        for raw in subscription_ids:
            clean_text = str(raw or "").strip()
            if isinstance(raw, bool) or not re.fullmatch(r"[1-9][0-9]*", clean_text):
                raise MaxioScopeError(
                    "subscription_ids must contain exact positive integers"
                )
            clean_id = int(clean_text)
            if clean_id in seen:
                raise MaxioScopeError("subscription_ids cannot contain duplicates")
            seen.add(clean_id)
            clean_ids.append(clean_id)

        subscriptions: list[dict[str, Any]] = []
        for subscription_id in sorted(clean_ids):
            record = _subscription_record(
                self._get(f"/subscriptions/{subscription_id}.json")
            )
            readback_id = _numeric_api_id(record.get("id"))
            if readback_id != subscription_id:
                raise MaxioUnavailableError(
                    "Maxio subscription reconciliation readback did not match the requested ID"
                )
            state = str(record.get("state") or "").strip().casefold()
            if not state:
                raise MaxioUnavailableError(
                    "Maxio subscription reconciliation readback omitted state"
                )
            component_summary = _component_deallocation_summary(
                self._subscription_component_rows(subscription_id)
            )
            closed = state in CANCELED_SUBSCRIPTION_STATES or state == "expired"
            subscriptions.append(
                {
                    "subscriptionId": subscription_id,
                    "state": state,
                    "closed": closed,
                    "locationComponentQuantity": int(
                        component_summary["locationComponentDeallocationCount"]
                    ),
                    "storageComponentQuantity": int(
                        component_summary["storageComponentDeallocationCount"]
                    ),
                    "otherComponentQuantity": int(
                        component_summary["otherComponentDeallocationCount"]
                    ),
                    "componentInventoryComplete": bool(
                        component_summary["componentInventoryComplete"]
                    ),
                }
            )

        open_rows = [row for row in subscriptions if not row["closed"]]
        hash_payload = {
            "subscriptionIds": sorted(clean_ids),
            "subscriptions": subscriptions,
            "openSubscriptionIds": [
                int(row["subscriptionId"]) for row in open_rows
            ],
            "openLocationComponentQuantity": sum(
                int(row["locationComponentQuantity"]) for row in open_rows
            ),
        }
        snapshot_hash = hashlib.sha256(
            json.dumps(
                hash_payload,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
            ).encode("utf-8")
        ).hexdigest()
        return {
            "ok": True,
            "verified": True,
            "accessMode": "complete_read_only",
            **hash_payload,
            "allComponentInventoriesComplete": all(
                bool(row["componentInventoryComplete"]) for row in subscriptions
            ),
            "allSubscriptionsClosed": not open_rows,
            "snapshotHash": snapshot_hash,
            "writesPerformed": False,
        }

    def component_allocation_preview(
        self,
        subscription_id: int,
        allocations: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Preview one fixed no-charge/no-credit component allocation plan."""

        plan = self._component_allocation_plan(subscription_id, allocations)
        provider_preview: Any = None
        if plan["changes"]:
            provider_preview = self._post_preview(
                f"/subscriptions/{plan['subscriptionId']}/allocations/preview.json",
                {
                    "allocations": [
                        {
                            "component_id": row["componentId"],
                            "quantity": row["desiredQuantity"],
                            "previous_quantity": row["currentQuantity"],
                        }
                        for row in plan["changes"]
                    ],
                    "upgrade_charge": ALLOCATION_FINANCIAL_CONTROLS["upgrade_charge"],
                    "downgrade_credit": ALLOCATION_FINANCIAL_CONTROLS["downgrade_credit"],
                },
            )
        return {
            "ok": True,
            "status": "preview",
            "previewHash": plan["previewHash"],
            "subscriptionId": plan["subscriptionId"],
            "changes": plan["changes"],
            "unchanged": plan["unchanged"],
            "componentDeallocationSummary": plan["componentDeallocationSummary"],
            "locationComponentDeallocationCount": plan[
                "componentDeallocationSummary"
            ]["locationComponentDeallocationCount"],
            "changeDirection": _allocation_direction(plan["changes"]),
            "financialControls": dict(ALLOCATION_FINANCIAL_CONTROLS),
            "providerPreview": provider_preview,
            "chargeAuthorized": False,
            "creditAuthorized": False,
            "manualCreditRequiresSeparatePreviewAndApply": True,
            "applyRequired": bool(plan["changes"]),
        }

    def apply_component_allocation(
        self,
        subscription_id: int,
        allocations: list[dict[str, Any]],
        *,
        preview_hash: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        """Apply an exact previewed allocation plan and verify component quantities."""

        plan = self._component_allocation_plan(subscription_id, allocations)
        clean_hash = str(preview_hash or "").strip().lower()
        clean_key = str(idempotency_key or "").strip()
        if not IDEMPOTENCY_KEY.fullmatch(clean_key):
            raise MaxioScopeError("mutations require an idempotency_key of 8-240 safe characters")
        if not re.fullmatch(r"[0-9a-f]{64}", clean_hash) or clean_hash != plan["previewHash"]:
            raise MaxioScopeError(
                "preview_hash does not match the current component quantities and desired allocation"
            )
        if not plan["changes"]:
            return {
                "ok": True,
                "updated": False,
                "duplicate": True,
                "verified": True,
                "previewHash": clean_hash,
                "idempotencyKey": clean_key,
                "subscriptionId": plan["subscriptionId"],
                "changes": [],
                "unchanged": plan["unchanged"],
                "componentDeallocationSummary": plan[
                    "componentDeallocationSummary"
                ],
                "locationComponentDeallocationCount": plan[
                    "componentDeallocationSummary"
                ]["locationComponentDeallocationCount"],
                "changeDirection": "unchanged",
                "financialControls": dict(ALLOCATION_FINANCIAL_CONTROLS),
                "financialEffectsAuthorized": False,
                "manualCreditRequiresSeparatePreviewAndApply": True,
            }

        body = {
            "allocations": [
                {
                    "component_id": row["componentId"],
                    "quantity": row["desiredQuantity"],
                    "previous_quantity": row["currentQuantity"],
                }
                for row in plan["changes"]
            ],
            **ALLOCATION_FINANCIAL_CONTROLS,
        }
        result = self.api_request(
            "POST",
            f"/subscriptions/{plan['subscriptionId']}/allocations.json",
            json_body=body,
            idempotency_key=clean_key,
            _typed_financial_operation="component_allocation",
        )
        if not result.get("ok"):
            return {
                **result,
                "verified": False,
                "previewHash": clean_hash,
                "financialControls": dict(ALLOCATION_FINANCIAL_CONTROLS),
            }

        readback_plan = self._component_allocation_plan(subscription_id, allocations)
        if readback_plan["changes"]:
            raise MaxioUnavailableError(
                "Maxio allocation readback did not match; do not retry until the subscription is read again"
            )
        return {
            "ok": True,
            "updated": True,
            "duplicate": bool(result.get("duplicate")),
            "verified": True,
            "previewHash": clean_hash,
            "idempotencyKey": clean_key,
            "subscriptionId": plan["subscriptionId"],
            "applied": plan["changes"],
            "readback": readback_plan["unchanged"],
            "componentDeallocationSummary": plan["componentDeallocationSummary"],
            "locationComponentDeallocationCount": plan[
                "componentDeallocationSummary"
            ]["locationComponentDeallocationCount"],
            "changeDirection": _allocation_direction(plan["changes"]),
            "financialControls": dict(ALLOCATION_FINANCIAL_CONTROLS),
            "financialEffectsAuthorized": False,
            "manualCreditRequiresSeparatePreviewAndApply": True,
            "financialReadbackRequired": True,
        }

    def component_payment_recovery_preview(
        self,
        subscription_id: int,
        component_id: int,
        recovery_location_ids: list[int],
        recovery_charge_quantity: int,
        unit_rate_cents: int,
        authorized_amount_cents: int,
        ticket_number: str,
    ) -> dict[str, Any]:
        """Preview one isolated allocation-based recovery with fixed dunning controls."""

        plan = self._component_payment_recovery_plan(
            subscription_id,
            component_id,
            recovery_location_ids,
            recovery_charge_quantity,
            unit_rate_cents,
            authorized_amount_cents,
            ticket_number,
        )
        return {
            "ok": True,
            "status": "previous_attempt" if plan["priorChargeAttempt"] else "preview",
            "previewHash": plan["previewHash"],
            "subscriptionId": plan["subscriptionId"],
            "componentId": plan["componentId"],
            "ticketNumber": plan["ticketNumber"],
            "recoveryLocationIds": plan["recoveryLocationIds"],
            "recurringQuantity": plan["recurringQuantity"],
            "stagedQuantity": plan["stagedQuantity"],
            "recoveryChargeQuantity": plan["recoveryChargeQuantity"],
            "unitRateCents": plan["unitRateCents"],
            "authorizedAmountCents": plan["authorizedAmountCents"],
            "paymentProfile": plan["paymentProfile"],
            "balances": plan["balances"],
            "financialControls": plan["financialControls"],
            "providerStagePreview": plan["providerStagePreview"],
            "providerChargePreview": plan["providerChargePreview"],
            "providerChargePreviewTotalCents": plan[
                "providerChargePreviewTotalCents"
            ],
            "priorChargeAttempt": plan["priorChargeAttempt"],
            "sameSubscriptionAllowed": True,
            "otherLocationsExposedToDunning": False,
            "separateSubscriptionRequiredWhenScopeDiffers": True,
            "successfulPaymentRequiredForActivation": True,
            "recurringQuantityWillBeRestoredAfterSuccessfulPaymentOnly": True,
            "downstreamActivationAllowed": False,
            "directOneTimeChargeUsed": False,
            "applyRequired": plan["priorChargeAttempt"] is None,
            "writesPerformed": False,
        }

    def apply_component_payment_recovery(
        self,
        subscription_id: int,
        component_id: int,
        recovery_location_ids: list[int],
        recovery_charge_quantity: int,
        unit_rate_cents: int,
        authorized_amount_cents: int,
        ticket_number: str,
        *,
        preview_hash: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        """Stage, charge with full allocation+dunning, normalize, and verify once."""

        plan = self._component_payment_recovery_plan(
            subscription_id,
            component_id,
            recovery_location_ids,
            recovery_charge_quantity,
            unit_rate_cents,
            authorized_amount_cents,
            ticket_number,
        )
        clean_hash = _required_preview_hash(preview_hash, plan["previewHash"])
        clean_key = _required_idempotency_key(idempotency_key)
        path = f"/subscriptions/{plan['subscriptionId']}/allocations.json"
        baseline_transaction_ids = {
            int(row["id"]) for row in plan["transactions"]
        }

        if plan["priorChargeAttempt"] is not None:
            current_quantity = self._component_quantity(
                plan["subscriptionId"], plan["componentId"]
            )
            if current_quantity != plan["stagedQuantity"]:
                self._set_component_payment_recovery_quantity(
                    plan,
                    current_quantity=current_quantity,
                    desired_quantity=plan["stagedQuantity"],
                    idempotency_key=_phase_idempotency_key(clean_key, "normalize"),
                )
            balances = self.subscription_account_balances(plan["subscriptionId"])[
                "balances"
            ]
            return {
                "ok": False,
                "status": "previous_attempt_not_retried",
                "attempted": True,
                "updated": False,
                "duplicate": True,
                "verified": self._component_quantity(
                    plan["subscriptionId"], plan["componentId"]
                )
                == plan["stagedQuantity"],
                "retryAllowed": False,
                "subscriptionId": plan["subscriptionId"],
                "componentId": plan["componentId"],
                "ticketNumber": plan["ticketNumber"],
                "recoveryLocationIds": plan["recoveryLocationIds"],
                "authorizedAmountCents": plan["authorizedAmountCents"],
                "recurringQuantity": plan["recurringQuantity"],
                "recurringQuantityRestored": False,
                "serviceQuantity": plan["stagedQuantity"],
                "successfulPaymentVerified": False,
                "downstreamActivationAllowed": False,
                "balances": balances,
                "previewHash": clean_hash,
                "idempotencyKey": clean_key,
                "financialControls": plan["financialControls"],
                "directOneTimeChargeUsed": False,
                "reason": (
                    "This exact allocation recovery was already attempted without a durable "
                    "paid-result receipt. Service was left deallocated and no second "
                    "collection was sent."
                ),
            }

        stage_result = self.api_request(
            "POST",
            path,
            json_body=plan["providerStageAllocation"],
            idempotency_key=_phase_idempotency_key(clean_key, "stage"),
            _typed_financial_operation="component_payment_recovery",
        )
        if not stage_result.get("ok"):
            current_quantity = self._component_quantity(
                plan["subscriptionId"], plan["componentId"]
            )
            if current_quantity not in {
                plan["recurringQuantity"],
                plan["stagedQuantity"],
            }:
                raise MaxioUnavailableError(
                    "the no-credit recovery downgrade failed with an unexpected allocation; "
                    "read the subscription before retrying"
                )
            if current_quantity == plan["stagedQuantity"]:
                self._set_component_payment_recovery_quantity(
                    plan,
                    current_quantity=current_quantity,
                    desired_quantity=plan["recurringQuantity"],
                    idempotency_key=_phase_idempotency_key(clean_key, "normalize"),
                )
                current_quantity = self._component_quantity(
                    plan["subscriptionId"], plan["componentId"]
                )
            return {
                **stage_result,
                "status": "stage_rejected",
                "verified": current_quantity == plan["recurringQuantity"],
                "retryAllowed": current_quantity == plan["recurringQuantity"],
                "subscriptionId": plan["subscriptionId"],
                "componentId": plan["componentId"],
                "previewHash": clean_hash,
                "idempotencyKey": clean_key,
                "financialControls": plan["financialControls"],
            }
        if self._component_quantity(plan["subscriptionId"], plan["componentId"]) != plan[
            "stagedQuantity"
        ]:
            raise MaxioUnavailableError(
                "the no-credit recovery downgrade was not verified; do not start the charge"
            )
        stage_balances = self.subscription_account_balances(plan["subscriptionId"])[
            "balances"
        ]
        if not _all_balances_zero(stage_balances):
            raise MaxioUnavailableError(
                "the recovery downgrade created a financial balance; do not start the charge"
            )

        charge_result = self.api_request(
            "POST",
            path,
            json_body=plan["providerChargeAllocation"],
            idempotency_key=_phase_idempotency_key(clean_key, "charge"),
            _typed_financial_operation="component_payment_recovery",
        )
        current_quantity = self._component_quantity(
            plan["subscriptionId"], plan["componentId"]
        )
        if current_quantity not in {
            plan["stagedQuantity"],
            plan["recoveryChargeQuantity"],
            plan["recurringQuantity"],
        }:
            raise MaxioUnavailableError(
                "the full-charge allocation returned an unexpected component quantity; "
                "do not retry or normalize automatically"
            )
        return self._component_payment_recovery_result(
            plan,
            baseline_transaction_ids=baseline_transaction_ids,
            preview_hash=clean_hash,
            idempotency_key=clean_key,
            provider_result=charge_result,
        )

    def _component_quantity(self, subscription_id: int, component_id: int) -> int:
        quantities = _component_quantities(
            self._get(
                f"/subscriptions/{int(subscription_id)}/components.json",
                params={"page": 1, "per_page": 200},
            )
        )
        if int(component_id) not in quantities:
            raise MaxioUnavailableError(
                "Maxio component readback omitted the recovery component"
            )
        return int(quantities[int(component_id)])

    def _set_component_payment_recovery_quantity(
        self,
        plan: Mapping[str, Any],
        *,
        current_quantity: int,
        desired_quantity: int,
        idempotency_key: str,
    ) -> None:
        if int(current_quantity) == int(desired_quantity):
            return
        body = {
            "allocations": [
                {
                    "component_id": int(plan["componentId"]),
                    "quantity": int(desired_quantity),
                    "previous_quantity": int(current_quantity),
                }
            ],
            **COMPONENT_PAYMENT_RECOVERY_CONTROLS["normalize"],
        }
        result = self.api_request(
            "POST",
            f"/subscriptions/{int(plan['subscriptionId'])}/allocations.json",
            json_body=body,
            idempotency_key=idempotency_key,
            _typed_financial_operation="component_payment_recovery",
        )
        if not result.get("ok"):
            raise MaxioUnavailableError(
                "the recovery charge was attempted but the payment-gated service allocation "
                "could not be set safely; do not retry the charge"
            )
        if self._component_quantity(plan["subscriptionId"], plan["componentId"]) != int(
            desired_quantity
        ):
            raise MaxioUnavailableError(
                "the payment-gated service allocation did not read back; do not retry"
            )

    def _component_payment_recovery_result(
        self,
        plan: Mapping[str, Any],
        *,
        baseline_transaction_ids: set[int],
        preview_hash: str,
        idempotency_key: str,
        provider_result: Mapping[str, Any],
    ) -> dict[str, Any]:
        subscription = _subscription_record(
            self._get(f"/subscriptions/{int(plan['subscriptionId'])}.json")
        )
        state = str(subscription.get("state") or "").strip().casefold()
        charge_quantity = self._component_quantity(
            int(plan["subscriptionId"]), int(plan["componentId"])
        )
        if charge_quantity not in {
            int(plan["stagedQuantity"]),
            int(plan["recoveryChargeQuantity"]),
            int(plan["recurringQuantity"]),
        }:
            raise MaxioUnavailableError(
                "the recovery allocation is outside the payment-gated states; do not retry"
            )
        balances = self.subscription_account_balances(int(plan["subscriptionId"]))[
            "balances"
        ]
        transactions = self._component_payment_recovery_transactions(
            int(plan["subscriptionId"])
        )
        new_transactions = [
            row for row in transactions if int(row["id"]) not in baseline_transaction_ids
        ]
        successful_charges = [
            row
            for row in new_transactions
            if row["transactionType"] == "charge"
            and row["success"]
            and int(row["amountCents"]) == int(plan["authorizedAmountCents"])
        ]
        successful_collections = [
            evidence
            for charge in successful_charges
            if (evidence := _successful_collection_evidence(charge, new_transactions))
            is not None
        ]
        failed_payments = [
            row
            for row in new_transactions
            if row["transactionType"] == "payment"
            and not row["success"]
            and int(row["amountCents"]) == int(plan["authorizedAmountCents"])
        ]
        common = {
            "subscriptionId": int(plan["subscriptionId"]),
            "componentId": int(plan["componentId"]),
            "ticketNumber": str(plan["ticketNumber"]),
            "recoveryLocationIds": list(plan["recoveryLocationIds"]),
            "recoveryChargeQuantity": int(plan["recoveryChargeQuantity"]),
            "unitRateCents": int(plan["unitRateCents"]),
            "authorizedAmountCents": int(plan["authorizedAmountCents"]),
            "recurringQuantity": int(plan["recurringQuantity"]),
            "otherLocationsExposedToDunning": False,
            "directOneTimeChargeUsed": False,
            "retryAllowed": False,
            "previewHash": preview_hash,
            "idempotencyKey": idempotency_key,
            "subscriptionState": state,
            "balances": balances,
            "newTransactions": new_transactions,
            "financialControls": plan["financialControls"],
            "providerStatusCode": provider_result.get("statusCode"),
            "providerResult": provider_result.get("body"),
        }
        if len(successful_collections) == 1:
            if not _all_balances_zero(balances):
                raise MaxioUnavailableError(
                    "the recovery payment succeeded but a financial balance remains; do not retry"
                )
            self._set_component_payment_recovery_quantity(
                plan,
                current_quantity=charge_quantity,
                desired_quantity=int(plan["recurringQuantity"]),
                idempotency_key=_phase_idempotency_key(idempotency_key, "activate"),
            )
            return {
                "ok": True,
                "status": "collected",
                "attempted": True,
                "updated": True,
                "duplicate": bool(provider_result.get("duplicate")),
                "verified": True,
                "dunningInitiated": False,
                "recurringQuantityRestored": True,
                "serviceQuantity": int(plan["recurringQuantity"]),
                "successfulPaymentVerified": True,
                "downstreamActivationAllowed": True,
                "collection": successful_collections[0],
                **common,
            }
        if len(successful_collections) > 1:
            raise MaxioUnavailableError(
                "multiple matching recovery collections were found; reconcile Maxio before continuing"
            )
        self._set_component_payment_recovery_quantity(
            plan,
            current_quantity=charge_quantity,
            desired_quantity=int(plan["stagedQuantity"]),
            idempotency_key=_phase_idempotency_key(idempotency_key, "deactivate"),
        )
        fail_closed = {
            "recurringQuantityRestored": False,
            "serviceQuantity": int(plan["stagedQuantity"]),
            "successfulPaymentVerified": False,
            "downstreamActivationAllowed": False,
        }
        if failed_payments:
            other_balances = {
                key: value
                for key, value in balances.items()
                if key != "openInvoiceBalanceCents"
            }
            if (
                int(balances.get("openInvoiceBalanceCents", -1))
                != int(plan["authorizedAmountCents"])
                or not _all_balances_zero(other_balances)
                or state not in {"past_due", "unpaid", "canceled", "cancelled"}
            ):
                raise MaxioUnavailableError(
                    "the failed recovery payment did not verify dunning with exactly the "
                    "authorized open invoice and every other balance clear; do not retry"
                )
            return {
                "ok": False,
                "status": "dunning_initiated",
                "attempted": True,
                "updated": True,
                "duplicate": bool(provider_result.get("duplicate")),
                "verified": True,
                "dunningInitiated": True,
                "failedPayments": failed_payments,
                **fail_closed,
                **common,
            }
        pending_balance = int(balances.get("pendingInvoiceBalanceCents", 0))
        open_balance = int(balances.get("openInvoiceBalanceCents", 0))
        other_balances = {
            key: value
            for key, value in balances.items()
            if key not in {"openInvoiceBalanceCents", "pendingInvoiceBalanceCents"}
        }
        if (
            pending_balance + open_balance == int(plan["authorizedAmountCents"])
            and not _all_balances_zero(other_balances)
        ):
            raise MaxioUnavailableError(
                "the pending recovery invoice left another financial balance; do not retry"
            )
        if pending_balance + open_balance == int(plan["authorizedAmountCents"]):
            return {
                "ok": False,
                "status": "pending_collection",
                "attempted": True,
                "updated": True,
                "duplicate": bool(provider_result.get("duplicate")),
                "verified": True,
                "dunningInitiated": state in {"past_due", "unpaid"},
                **fail_closed,
                **common,
            }
        if not provider_result.get("ok") and _all_balances_zero(balances):
            return {
                "ok": False,
                "status": "provider_rejected_no_charge",
                "attempted": True,
                "updated": False,
                "duplicate": bool(provider_result.get("duplicate")),
                "verified": True,
                "dunningInitiated": False,
                **fail_closed,
                **common,
            }
        raise MaxioUnavailableError(
            "the full-charge allocation outcome could not be verified; do not retry"
        )

    def _component_payment_recovery_transactions(
        self, subscription_id: int
    ) -> list[dict[str, Any]]:
        return _transaction_records(
            self._get(
                f"/subscriptions/{int(subscription_id)}/transactions.json",
                params={"page": 1, "per_page": 200, "direction": "desc"},
            )
        )

    def payment_profiles_by_customer(self, customer_id: int, *, max_rows: int = 50) -> dict[str, Any]:
        rows = _bounded_rows(max_rows)
        payload = self._get(
            "/payment_profiles.json",
            params={"customer_id": _positive_id(customer_id, "customer_id"), "page": 1, "per_page": rows},
        )
        return _collection(payload, max_rows=rows, operation="payment_profiles_by_customer")

    def subscription_payment_profile_assignment_preview(
        self,
        subscription_id: int,
        customer_id: int,
        payment_profile_id: int,
        ticket_number: str,
    ) -> dict[str, Any]:
        """Preview assigning one existing customer-owned profile to one exact subscription."""

        context = self._subscription_payment_context(
            subscription_id,
            customer_id,
            payment_profile_id,
        )
        plan = {
            "operation": "maxio_subscription_payment_profile_assignment",
            "ticketNumber": _ticket_number(ticket_number),
            "subscriptionId": context["subscriptionId"],
            "customerId": context["customerId"],
            "paymentProfileId": context["paymentProfileId"],
            "currentPaymentProfileId": context["currentPaymentProfileId"],
            "currentState": context["currentState"],
            "targetPaymentProfile": context["targetPaymentProfile"],
        }
        return {
            "ok": True,
            "status": "preview",
            **plan,
            "previewHash": _plan_hash(plan),
            "applyRequired": context["currentPaymentProfileId"] != context["paymentProfileId"],
            "rawPaymentDetailsAccepted": False,
            "writesPerformed": False,
        }

    def apply_subscription_payment_profile_assignment(
        self,
        subscription_id: int,
        customer_id: int,
        payment_profile_id: int,
        ticket_number: str,
        *,
        preview_hash: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        """Assign one unchanged existing payment profile and verify subscription readback."""

        preview = self.subscription_payment_profile_assignment_preview(
            subscription_id,
            customer_id,
            payment_profile_id,
            ticket_number,
        )
        clean_key = _required_idempotency_key(idempotency_key)
        if not preview["applyRequired"]:
            return {
                **preview,
                "status": "completed",
                "updated": False,
                "duplicate": True,
                "verified": True,
                "retryAllowed": False,
                "idempotencyKey": clean_key,
            }
        clean_hash = _required_preview_hash(preview_hash, preview["previewHash"])
        result = self.api_request(
            "POST",
            (
                f"/subscriptions/{preview['subscriptionId']}/payment_profiles/"
                f"{preview['paymentProfileId']}/change_payment_profile.json"
            ),
            idempotency_key=clean_key,
            _typed_financial_operation="subscription_payment_profile_assignment",
        )
        provider_status_code = result.get("statusCode") or (
            (result.get("prior") or {}).get("statusCode")
            if isinstance(result.get("prior"), Mapping)
            else None
        )
        if not result.get("ok"):
            return {
                **preview,
                "status": "failed",
                "updated": False,
                "verified": False,
                "retryAllowed": False,
                "idempotencyKey": clean_key,
                "providerStatusCode": provider_status_code,
                "providerErrors": _provider_error_messages(result.get("body")),
                "assignmentMethod": "change_default_payment_profile",
            }
        readback = _subscription_record(
            self._get(f"/subscriptions/{preview['subscriptionId']}.json")
        )
        readback_profile_id = _subscription_payment_profile_id(readback)
        if readback_profile_id != preview["paymentProfileId"]:
            raise MaxioUnavailableError(
                "Maxio accepted the payment-profile assignment but subscription readback did not match; "
                "do not retry until the subscription is read again"
            )
        return {
            **preview,
            "status": "completed",
            "updated": True,
            "duplicate": bool(result.get("duplicate")),
            "verified": True,
            "idempotencyKey": clean_key,
            "previewHash": clean_hash,
            "readbackPaymentProfileId": readback_profile_id,
            "providerStatusCode": provider_status_code,
            "assignmentMethod": "change_default_payment_profile",
        }

    def payment_profile_update_request_preview(
        self,
        subscription_id: int,
        customer_id: int,
        ticket_number: str,
    ) -> dict[str, Any]:
        """Preview Maxio's secure customer payment-update email for one subscription."""

        clean_subscription_id = _positive_id(subscription_id, "subscription_id")
        clean_customer_id = _positive_id(customer_id, "customer_id")
        subscription = _subscription_record(
            self._get(f"/subscriptions/{clean_subscription_id}.json")
        )
        actual_customer_id = _subscription_customer_id(subscription)
        if actual_customer_id != clean_customer_id:
            raise MaxioScopeError("subscription_id belongs to a different Maxio customer")
        customer = subscription.get("customer") if isinstance(subscription.get("customer"), Mapping) else {}
        email = str(customer.get("email") or "").strip()
        if not email or "@" not in email:
            raise MaxioScopeError(
                "the exact Maxio customer does not have a usable email for a secure payment update"
            )
        plan = {
            "operation": "maxio_payment_profile_update_request",
            "ticketNumber": _ticket_number(ticket_number),
            "subscriptionId": clean_subscription_id,
            "customerId": clean_customer_id,
            "customerEmail": _masked_email(email),
            "currentState": str(subscription.get("state") or "").strip().casefold(),
        }
        return {
            "ok": True,
            "status": "preview",
            **plan,
            "previewHash": _plan_hash(plan),
            "applyRequired": True,
            "deliverySurface": "maxio_secure_payment_update_email",
            "rawPaymentDetailsAccepted": False,
            "writesPerformed": False,
        }

    def apply_payment_profile_update_request(
        self,
        subscription_id: int,
        customer_id: int,
        ticket_number: str,
        *,
        preview_hash: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        """Send Maxio's secure payment-update email once and retain the ticket for follow-up."""

        preview = self.payment_profile_update_request_preview(
            subscription_id,
            customer_id,
            ticket_number,
        )
        clean_hash = _required_preview_hash(preview_hash, preview["previewHash"])
        clean_key = _required_idempotency_key(idempotency_key)
        result = self.api_request(
            "POST",
            f"/subscriptions/{preview['subscriptionId']}/request_payment_profiles_update.json",
            idempotency_key=clean_key,
            _typed_financial_operation="payment_profile_update_request",
        )
        return {
            **preview,
            "ok": bool(result.get("ok")),
            "status": "completed" if result.get("ok") else "failed",
            "updated": bool(result.get("ok") and not result.get("duplicate")),
            "duplicate": bool(result.get("duplicate")),
            "verified": bool(result.get("ok")),
            "retryAllowed": False,
            "idempotencyKey": clean_key,
            "previewHash": clean_hash,
            "providerStatusCode": result.get("statusCode"),
            "followupRequired": bool(result.get("ok")),
            "nextStep": (
                "Keep the Billing ticket open. On the next review, detect the new customer-owned "
                "payment profile, assign it to the exact subscription, then run reactivation preview/apply."
                if result.get("ok")
                else "Read the subscription and provider result before any new send attempt."
            ),
        }

    def subscription_reactivation_preview(
        self,
        subscription_id: int,
        customer_id: int,
        payment_profile_id: int,
        reactivation_mode: str,
        authorized_charge_cents: int,
        ticket_number: str,
    ) -> dict[str, Any]:
        """Preview a ticket-authorized reactivation against the exact active payment profile."""

        context = self._subscription_payment_context(
            subscription_id,
            customer_id,
            payment_profile_id,
        )
        mode = str(reactivation_mode or "").strip().casefold()
        if mode not in {"new_billing_period", "resume_only"}:
            raise MaxioScopeError(
                "reactivation_mode must be new_billing_period or resume_only"
            )
        state = context["currentState"]
        apply_required = state not in {"active", "trialing"}
        if apply_required and state not in {"canceled", "cancelled", "unpaid", "trial_ended"}:
            raise MaxioScopeError(
                "subscription reactivation requires canceled, unpaid, or trial_ended state"
            )
        subscription = context["subscription"]
        recurring_cents = _numeric_api_nonnegative(
            subscription.get("current_billing_amount_in_cents")
            if subscription.get("current_billing_amount_in_cents") is not None
            else subscription.get("product_price_in_cents")
        )
        balance_cents = _numeric_api_nonnegative(subscription.get("balance_in_cents"))
        expected_charge_cents = recurring_cents if mode == "new_billing_period" else balance_cents
        clean_authorized_charge = _nonnegative_cents(
            authorized_charge_cents,
            "authorized_charge_cents",
        )
        if apply_required and clean_authorized_charge != expected_charge_cents:
            raise MaxioScopeError(
                "authorized_charge_cents must match the exact current reactivation charge preview"
            )
        if apply_required and clean_authorized_charge <= 0:
            raise MaxioScopeError(
                "reactivation requires a positive authorized charge so activation can be payment-gated"
            )
        provider_body: dict[str, Any]
        if mode == "resume_only":
            provider_body = {
                "resume": {"require_resume": True},
                "preserve_balance": True,
                "include_trial": False,
                "use_credits_and_prepayments": False,
            }
        else:
            provider_body = {
                "resume": False,
                "preserve_balance": False,
                "include_trial": False,
                "use_credits_and_prepayments": False,
            }
            if str(subscription.get("snap_day") or "").strip():
                provider_body["calendar_billing"] = {"reactivation_charge": "immediate"}
        transactions = self._component_payment_recovery_transactions(
            context["subscriptionId"]
        )
        plan = {
            "operation": "maxio_subscription_reactivation",
            "ticketNumber": _ticket_number(ticket_number),
            "subscriptionId": context["subscriptionId"],
            "customerId": context["customerId"],
            "paymentProfileId": context["paymentProfileId"],
            "currentState": state,
            "reactivationMode": mode,
            "currentBalanceCents": balance_cents,
            "currentBillingAmountCents": recurring_cents,
            "authorizedChargeCents": clean_authorized_charge,
            "providerPayload": provider_body,
            "transactionIds": [row["id"] for row in transactions],
        }
        return {
            "ok": True,
            "status": "preview",
            **plan,
            "previewHash": _plan_hash(plan),
            "applyRequired": apply_required,
            "paymentAttemptExpected": apply_required,
            "successfulPaymentRequiredForActivation": True,
            "downstreamActivationAllowed": False,
            "writesPerformed": False,
        }

    def apply_subscription_reactivation(
        self,
        subscription_id: int,
        customer_id: int,
        payment_profile_id: int,
        reactivation_mode: str,
        authorized_charge_cents: int,
        ticket_number: str,
        *,
        preview_hash: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        """Reactivate once and allow downstream activation only after exact payment evidence."""

        clean_key = _required_idempotency_key(idempotency_key)
        clean_subscription_id = _positive_id(subscription_id, "subscription_id")
        requested_preview_hash = str(preview_hash or "").strip().lower()
        if not re.fullmatch(r"[0-9a-f]{64}", requested_preview_hash):
            raise MaxioScopeError("preview_hash must be the exact 64-character plan hash")
        receipt_path = (
            f"/subscriptions/{clean_subscription_id}/reactivation-payment-gate"
        )
        receipt_key = _phase_idempotency_key(clean_key, "gate-result")
        receipt_hash = _plan_hash(
            {
                "operation": "maxio_subscription_reactivation_payment_gate_result",
                "subscriptionId": clean_subscription_id,
                "customerId": _positive_id(customer_id, "customer_id"),
                "paymentProfileId": _positive_id(
                    payment_profile_id, "payment_profile_id"
                ),
                "reactivationMode": str(reactivation_mode or "")
                .strip()
                .casefold(),
                "authorizedChargeCents": _nonnegative_cents(
                    authorized_charge_cents, "authorized_charge_cents"
                ),
                "ticketNumber": _ticket_number(ticket_number),
                "previewHash": requested_preview_hash,
            }
        )
        prior_receipt = self._prior_operation(
            receipt_key,
            "RESULT",
            receipt_path,
            receipt_hash,
        )
        if prior_receipt is not None:
            evidence = prior_receipt.get("evidence")
            if (
                prior_receipt.get("status") != "accepted"
                or not isinstance(evidence, Mapping)
            ):
                raise MaxioUnavailableError(
                    "the prior reactivation payment-gate receipt was incomplete; do not retry"
                )
            return {
                **dict(evidence),
                "duplicate": True,
                "updated": False,
                "idempotencyKey": clean_key,
            }

        attempt_path = (
            f"/subscriptions/{clean_subscription_id}/reactivation-payment-attempt"
        )
        attempt_key = _phase_idempotency_key(clean_key, "attempt")
        attempt_hash = _plan_hash(
            {
                "operation": "maxio_subscription_reactivation_payment_attempt",
                "subscriptionId": clean_subscription_id,
                "customerId": _positive_id(customer_id, "customer_id"),
                "paymentProfileId": _positive_id(
                    payment_profile_id, "payment_profile_id"
                ),
                "reactivationMode": str(reactivation_mode or "")
                .strip()
                .casefold(),
                "authorizedChargeCents": _nonnegative_cents(
                    authorized_charge_cents, "authorized_charge_cents"
                ),
                "ticketNumber": _ticket_number(ticket_number),
                "previewHash": requested_preview_hash,
            }
        )
        prior_attempt = self._prior_operation(
            attempt_key,
            "ATTEMPT",
            attempt_path,
            attempt_hash,
        )
        recovered_attempt = prior_attempt is not None
        if prior_attempt is not None:
            attempt_evidence = prior_attempt.get("evidence")
            stored_preview = (
                attempt_evidence.get("preview")
                if isinstance(attempt_evidence, Mapping)
                else None
            )
            stored_baseline_ids = (
                attempt_evidence.get("baselineTransactionIds")
                if isinstance(attempt_evidence, Mapping)
                else None
            )
            if (
                prior_attempt.get("status") != "accepted"
                or not isinstance(stored_preview, Mapping)
                or not isinstance(stored_baseline_ids, list)
                or str(stored_preview.get("previewHash") or "").strip().lower()
                != requested_preview_hash
                or int(stored_preview.get("subscriptionId") or 0)
                != clean_subscription_id
                or stored_preview.get("applyRequired") is not True
            ):
                raise MaxioUnavailableError(
                    "the prior reactivation attempt baseline was invalid; do not retry"
                )
            try:
                baseline_transaction_ids = {
                    _positive_id(value, "baseline transaction ID")
                    for value in stored_baseline_ids
                }
            except MaxioScopeError as exc:
                raise MaxioUnavailableError(
                    "the prior reactivation attempt baseline was invalid; do not retry"
                ) from exc
            preview = dict(stored_preview)
            clean_hash = requested_preview_hash
        else:
            preview = self.subscription_reactivation_preview(
                subscription_id,
                customer_id,
                payment_profile_id,
                reactivation_mode,
                authorized_charge_cents,
                ticket_number,
            )
            if preview["applyRequired"]:
                clean_hash = _required_preview_hash(
                    preview_hash, preview["previewHash"]
                )
                baseline_transaction_ids = {
                    int(value) for value in preview["transactionIds"]
                }
                self._journal(
                    "accepted",
                    attempt_key,
                    "ATTEMPT",
                    attempt_path,
                    attempt_hash,
                    {
                        "preview": dict(preview),
                        "baselineTransactionIds": sorted(
                            baseline_transaction_ids
                        ),
                    },
                )

        if not preview["applyRequired"]:
            blocked = {
                **preview,
                "ok": False,
                "status": "already_active_payment_unverified",
                "updated": False,
                "duplicate": True,
                "verified": False,
                "retryAllowed": False,
                "idempotencyKey": clean_key,
                "successfulPaymentVerified": False,
                "downstreamActivationAllowed": False,
                "reason": (
                    "The subscription is already active, but this operation did not verify "
                    "the required charge and payment. No downstream activation is allowed."
                ),
            }
            self._journal(
                "accepted",
                receipt_key,
                "RESULT",
                receipt_path,
                receipt_hash,
                blocked,
            )
            return blocked
        provider_path = (
            f"/subscriptions/{preview['subscriptionId']}/reactivate.json"
        )
        provider_key = _phase_idempotency_key(clean_key, "provider")
        provider_request_hash = _api_request_hash(
            "PUT",
            provider_path,
            {},
            preview["providerPayload"],
        )
        if recovered_attempt:
            result = {
                "ok": False,
                "duplicate": True,
                "statusCode": None,
            }
        else:
            result = self.api_request(
                "PUT",
                provider_path,
                json_body=preview["providerPayload"],
                idempotency_key=provider_key,
                _typed_financial_operation="subscription_reactivation",
            )
        provider_receipt = self._prior_operation(
            provider_key,
            "PUT",
            provider_path,
            provider_request_hash,
        )
        provider_receipt_status = str(
            (provider_receipt or {}).get("status") or "not_recorded"
        )
        provider_receipt_evidence = (
            provider_receipt.get("evidence")
            if isinstance(provider_receipt, Mapping)
            and isinstance(provider_receipt.get("evidence"), Mapping)
            else {}
        )
        provider_status_code = (
            provider_receipt_evidence.get("statusCode")
            if provider_receipt_evidence
            else result.get("statusCode")
        )
        readback = _subscription_record(
            self._get(f"/subscriptions/{preview['subscriptionId']}.json")
        )
        readback_state = str(readback.get("state") or "").strip().casefold()
        readback_profile_id = _subscription_payment_profile_id(readback)
        transactions = self._component_payment_recovery_transactions(
            preview["subscriptionId"]
        )
        new_transactions = [
            row
            for row in transactions
            if int(row["id"]) not in baseline_transaction_ids
        ]
        successful_charges = [
            row
            for row in new_transactions
            if row["transactionType"] == "charge"
            and row["success"]
            and int(row["amountCents"]) == preview["authorizedChargeCents"]
        ]
        successful_collections = [
            evidence
            for charge in successful_charges
            if (
                evidence := _successful_collection_evidence(
                    charge, new_transactions
                )
            )
            is not None
        ]
        failed_payments = [
            row
            for row in new_transactions
            if row["transactionType"] == "payment"
            and not row["success"]
            and int(row["amountCents"]) == preview["authorizedChargeCents"]
        ]
        if len(successful_collections) > 1:
            raise MaxioUnavailableError(
                "multiple matching reactivation collections were found; do not retry"
            )
        balances = self.subscription_account_balances(preview["subscriptionId"])[
            "balances"
        ]
        verified = (
            provider_receipt_status in {"accepted", "pending"}
            and len(successful_collections) == 1
            and readback_state in {"active", "trialing"}
            and readback_profile_id == preview["paymentProfileId"]
            and _all_balances_zero(balances)
        )
        rollback_performed = False
        if not verified and readback_state in {"active", "trialing"}:
            rollback = self._cancel_subscription(
                preview["subscriptionId"],
                cancellation_message=(
                    f"Ticket {preview['ticketNumber']}: reactivation payment gate failed"
                ),
                idempotency_key=_phase_idempotency_key(clean_key, "rollback"),
            )
            if not rollback.get("ok"):
                raise MaxioUnavailableError(
                    "reactivation payment was not verified and the active subscription could not "
                    "be returned to a canceled state; do not retry"
                )
            rollback_readback = _subscription_record(
                self._get(f"/subscriptions/{preview['subscriptionId']}.json")
            )
            readback_state = str(
                rollback_readback.get("state") or ""
            ).strip().casefold()
            if readback_state not in CANCELED_SUBSCRIPTION_STATES:
                raise MaxioUnavailableError(
                    "reactivation payment was not verified and canceled-state rollback did not "
                    "read back; do not retry"
                )
            rollback_performed = True
        if verified:
            final = {
                **preview,
                "ok": True,
                "status": "collected_and_reactivated",
                "updated": not recovered_attempt
                and not bool(result.get("duplicate")),
                "duplicate": recovered_attempt or bool(result.get("duplicate")),
                "verified": True,
                "retryAllowed": False,
                "idempotencyKey": clean_key,
                "previewHash": clean_hash,
                "providerStatusCode": provider_status_code,
                "providerReceiptStatus": provider_receipt_status,
                "providerCallSkippedOnRecovery": recovered_attempt,
                "readbackState": readback_state,
                "readbackPaymentProfileId": readback_profile_id,
                "successfulPaymentVerified": True,
                "successfulCollection": successful_collections[0],
                "balances": balances,
                "newTransactions": new_transactions,
                "rollbackPerformed": False,
                "downstreamActivationAllowed": True,
            }
        else:
            final = {
                **preview,
                "ok": False,
                "status": "declined" if failed_payments else "payment_not_verified",
                "updated": rollback_performed,
                "duplicate": bool(result.get("duplicate")),
                "verified": bool(failed_payments) and readback_state in CANCELED_SUBSCRIPTION_STATES,
                "retryAllowed": False,
                "idempotencyKey": clean_key,
                "previewHash": clean_hash,
                "providerStatusCode": provider_status_code,
                "providerReceiptStatus": provider_receipt_status,
                "providerCallSkippedOnRecovery": recovered_attempt,
                "readbackState": readback_state,
                "readbackPaymentProfileId": readback_profile_id,
                "successfulPaymentVerified": False,
                "failedPayments": failed_payments,
                "balances": balances,
                "newTransactions": new_transactions,
                "rollbackPerformed": rollback_performed,
                "downstreamActivationAllowed": False,
                "reason": (
                    "The payment was declined; the subscription remains inactive and no "
                    "downstream location or account activation is allowed."
                    if failed_payments
                    else "A linked successful charge and payment were not verified; the "
                    "subscription remains inactive and downstream activation is blocked."
                ),
            }
        self._journal(
            "accepted",
            receipt_key,
            "RESULT",
            receipt_path,
            receipt_hash,
            final,
        )
        return final

    def subscription_no_charge_reactivation_preview(
        self,
        subscription_id: int,
        customer_id: int,
        waived_charge_cents: int,
        next_billing_at: str,
        ticket_number: str,
    ) -> dict[str, Any]:
        """Preview a ticket-authorized reactivation fully covered by one service credit."""

        clean_subscription_id = _positive_id(subscription_id, "subscription_id")
        clean_customer_id = _positive_id(customer_id, "customer_id")
        clean_ticket = _ticket_number(ticket_number)
        clean_next_billing_at, next_billing_datetime = _future_billing_timestamp(
            next_billing_at
        )
        subscription = _subscription_record(
            self._get(f"/subscriptions/{clean_subscription_id}.json")
        )
        if _required_integer_field(subscription, ("id",), "subscription ID") != clean_subscription_id:
            raise MaxioUnavailableError(
                "Maxio subscription response did not match the requested ID"
            )
        if _subscription_customer_id(subscription) != clean_customer_id:
            raise MaxioScopeError(
                "subscription_id belongs to a different Maxio customer"
            )
        state = str(subscription.get("state") or "").strip().casefold()
        apply_required = state not in {"active", "trialing"}
        if apply_required and state not in CANCELED_SUBSCRIPTION_STATES:
            raise MaxioScopeError(
                "no-charge reactivation requires an exactly canceled subscription"
            )
        recurring_cents = _numeric_api_nonnegative(
            subscription.get("current_billing_amount_in_cents")
            if subscription.get("current_billing_amount_in_cents") is not None
            else subscription.get("product_price_in_cents")
        )
        clean_waived_charge = _positive_cents(
            waived_charge_cents,
            "waived_charge_cents",
        )
        if apply_required and clean_waived_charge != recurring_cents:
            raise MaxioScopeError(
                "waived_charge_cents must match the exact current reactivation charge"
            )
        balances = self.subscription_account_balances(clean_subscription_id)[
            "balances"
        ]
        if apply_required and not _all_balances_zero(balances):
            raise MaxioScopeError(
                "no-charge reactivation requires zero starting invoice, credit, and prepayment balances"
            )
        transactions = self._component_payment_recovery_transactions(
            clean_subscription_id
        )
        provider_payload = {
            "resume": False,
            "preserve_balance": False,
            "include_trial": False,
            "use_credits_and_prepayments": True,
        }
        plan = {
            "operation": "maxio_subscription_no_charge_reactivation",
            "ticketNumber": clean_ticket,
            "subscriptionId": clean_subscription_id,
            "customerId": clean_customer_id,
            "currentState": state,
            "currentBillingAmountCents": recurring_cents,
            "waivedChargeCents": clean_waived_charge,
            "customerChargeCents": 0,
            "currentBalances": balances,
            "currentNextBillingAt": str(
                subscription.get("next_assessment_at")
                or subscription.get("next_billing_at")
                or ""
            ),
            "nextBillingAt": clean_next_billing_at,
            "nextBillingAtEpoch": int(next_billing_datetime.timestamp()),
            "serviceCreditMemo": f"Ticket {clean_ticket}: no-charge reactivation",
            "providerPayload": provider_payload,
            "transactionIds": [row["id"] for row in transactions],
        }
        return {
            "ok": True,
            "status": "preview" if apply_required else "already_active",
            **plan,
            "previewHash": _plan_hash(plan),
            "applyRequired": apply_required,
            "paymentAttemptExpected": False,
            "successfulPaymentRequiredForActivation": False,
            "serviceCreditCoversReactivationCharge": True,
            "downstreamActivationAllowed": False,
            "writesPerformed": False,
        }

    def apply_subscription_no_charge_reactivation(
        self,
        subscription_id: int,
        customer_id: int,
        waived_charge_cents: int,
        next_billing_at: str,
        ticket_number: str,
        *,
        preview_hash: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        """Credit, reactivate, align the future bill date, and verify the complete result."""

        clean_key = _required_idempotency_key(idempotency_key)
        clean_subscription_id = _positive_id(subscription_id, "subscription_id")
        requested_preview_hash = str(preview_hash or "").strip().lower()
        if not re.fullmatch(r"[0-9a-f]{64}", requested_preview_hash):
            raise MaxioScopeError(
                "preview_hash must be the exact 64-character plan hash"
            )
        receipt_path = (
            f"/subscriptions/{clean_subscription_id}/no-charge-reactivation-result"
        )
        receipt_key = _phase_idempotency_key(clean_key, "result")
        receipt_hash = _plan_hash(
            {
                "operation": "maxio_subscription_no_charge_reactivation_result",
                "subscriptionId": clean_subscription_id,
                "customerId": _positive_id(customer_id, "customer_id"),
                "waivedChargeCents": _positive_cents(
                    waived_charge_cents,
                    "waived_charge_cents",
                ),
                "nextBillingAt": str(next_billing_at or "").strip(),
                "ticketNumber": _ticket_number(ticket_number),
                "previewHash": requested_preview_hash,
            }
        )
        prior_receipt = self._prior_operation(
            receipt_key,
            "RESULT",
            receipt_path,
            receipt_hash,
        )
        if prior_receipt is not None:
            evidence = prior_receipt.get("evidence")
            if (
                prior_receipt.get("status") != "accepted"
                or not isinstance(evidence, Mapping)
            ):
                raise MaxioUnavailableError(
                    "the prior no-charge reactivation receipt was incomplete; do not retry"
                )
            return {
                **dict(evidence),
                "duplicate": True,
                "updated": False,
                "idempotencyKey": clean_key,
            }

        attempt_path = (
            f"/subscriptions/{clean_subscription_id}/no-charge-reactivation-attempt"
        )
        attempt_key = _phase_idempotency_key(clean_key, "attempt")
        attempt_hash = _plan_hash(
            {
                "operation": "maxio_subscription_no_charge_reactivation_attempt",
                "subscriptionId": clean_subscription_id,
                "previewHash": requested_preview_hash,
            }
        )
        prior_attempt = self._prior_operation(
            attempt_key,
            "ATTEMPT",
            attempt_path,
            attempt_hash,
        )
        if prior_attempt is not None:
            evidence = prior_attempt.get("evidence")
            stored_preview = (
                evidence.get("preview") if isinstance(evidence, Mapping) else None
            )
            if (
                prior_attempt.get("status") != "accepted"
                or not isinstance(stored_preview, Mapping)
                or str(stored_preview.get("previewHash") or "").strip().lower()
                != requested_preview_hash
            ):
                raise MaxioUnavailableError(
                    "the prior no-charge reactivation attempt baseline was invalid; do not retry"
                )
            preview = dict(stored_preview)
        else:
            preview = self.subscription_no_charge_reactivation_preview(
                subscription_id,
                customer_id,
                waived_charge_cents,
                next_billing_at,
                ticket_number,
            )
            _required_preview_hash(preview_hash, preview["previewHash"])
            if not preview["applyRequired"]:
                return {
                    **preview,
                    "ok": False,
                    "verified": False,
                    "updated": False,
                    "duplicate": True,
                    "retryAllowed": False,
                    "idempotencyKey": clean_key,
                    "reason": (
                        "The subscription is already active; this operation did not issue "
                        "a credit or verify the requested reactivation."
                    ),
                }
            self._journal(
                "accepted",
                attempt_key,
                "ATTEMPT",
                attempt_path,
                attempt_hash,
                {"preview": dict(preview)},
            )

        phase_subscription = _subscription_record(
            self._get(f"/subscriptions/{clean_subscription_id}.json")
        )
        phase_state = str(phase_subscription.get("state") or "").strip().casefold()
        phase_balances = self.subscription_account_balances(clean_subscription_id)[
            "balances"
        ]
        credit_already_consumed = (
            phase_state in {"active", "trialing"}
            and _all_balances_zero(phase_balances)
        )
        existing_credit_cents = int(phase_balances["serviceCreditBalanceCents"])
        if credit_already_consumed:
            credit_result = {"ok": True, "duplicate": True, "recoveredByReadback": True}
            after_credit_balances = phase_balances
        elif existing_credit_cents == int(preview["waivedChargeCents"]):
            credit_result = {"ok": True, "duplicate": True, "recoveredByReadback": True}
            after_credit_balances = phase_balances
        elif existing_credit_cents == 0 and phase_state in CANCELED_SUBSCRIPTION_STATES:
            credit_result = self.api_request(
                "POST",
                f"/subscriptions/{clean_subscription_id}/service_credits.json",
                json_body={
                    "service_credit": {
                        "amount": _currency_amount(preview["waivedChargeCents"]),
                        "memo": preview["serviceCreditMemo"],
                    }
                },
                idempotency_key=_phase_idempotency_key(clean_key, "credit"),
                _typed_financial_operation="subscription_no_charge_reactivation",
            )
            if not credit_result.get("ok"):
                final = {
                    **preview,
                    "ok": False,
                    "status": "service_credit_failed",
                    "updated": False,
                    "verified": False,
                    "retryAllowed": False,
                    "idempotencyKey": clean_key,
                    "downstreamActivationAllowed": False,
                    "providerStatusCode": credit_result.get("statusCode"),
                }
                self._journal(
                    "accepted",
                    receipt_key,
                    "RESULT",
                    receipt_path,
                    receipt_hash,
                    final,
                )
                return final
            after_credit_balances = self.subscription_account_balances(
                clean_subscription_id
            )["balances"]
        else:
            raise MaxioUnavailableError(
                "the no-charge reactivation phase readback was neither an exact pending credit "
                "nor a fully consumed active result; do not retry"
            )
        if not credit_already_consumed and int(
            after_credit_balances["serviceCreditBalanceCents"]
        ) != int(preview["waivedChargeCents"]):
            raise MaxioUnavailableError(
                "Maxio accepted the no-charge reactivation credit but its exact balance did not read back; "
                "do not retry"
            )

        if credit_already_consumed:
            reactivation_result = {
                "ok": True,
                "duplicate": True,
                "recoveredByReadback": True,
            }
        else:
            reactivation_result = self.api_request(
                "PUT",
                f"/subscriptions/{clean_subscription_id}/reactivate.json",
                json_body=preview["providerPayload"],
                idempotency_key=_phase_idempotency_key(clean_key, "reactivate"),
                _typed_financial_operation="subscription_no_charge_reactivation",
            )
            if not reactivation_result.get("ok"):
                reactivation_readback = _subscription_record(
                    self._get(f"/subscriptions/{clean_subscription_id}.json")
                )
                reactivation_state = str(
                    reactivation_readback.get("state") or ""
                ).strip().casefold()
                reactivation_balances = self.subscription_account_balances(
                    clean_subscription_id
                )["balances"]
                if not (
                    reactivation_state in {"active", "trialing"}
                    and _all_balances_zero(reactivation_balances)
                ):
                    final = {
                        **preview,
                        "ok": False,
                        "status": "reactivation_failed_after_credit",
                        "updated": bool(not credit_result.get("duplicate")),
                        "verified": False,
                        "retryAllowed": False,
                        "idempotencyKey": clean_key,
                        "afterCreditBalances": after_credit_balances,
                        "downstreamActivationAllowed": False,
                        "providerStatusCode": reactivation_result.get("statusCode"),
                    }
                    self._journal(
                        "accepted",
                        receipt_key,
                        "RESULT",
                        receipt_path,
                        receipt_hash,
                        final,
                    )
                    return final
                reactivation_result = {
                    "ok": True,
                    "duplicate": True,
                    "recoveredByReadback": True,
                }

        expected_next = datetime.fromtimestamp(
            int(preview["nextBillingAtEpoch"]),
            tz=timezone.utc,
        )
        predate_readback = _subscription_record(
            self._get(f"/subscriptions/{clean_subscription_id}.json")
        )
        existing_next_value = (
            predate_readback.get("next_assessment_at")
            or predate_readback.get("next_billing_at")
        )
        existing_next_matches = False
        if existing_next_value:
            existing_next = _parse_api_datetime(
                existing_next_value,
                "subscription next billing timestamp",
            )
            existing_next_matches = (
                abs((existing_next - expected_next).total_seconds()) <= 60
            )
        if existing_next_matches:
            billing_date_result = {
                "ok": True,
                "duplicate": True,
                "recoveredByReadback": True,
            }
        else:
            billing_date_result = self.api_request(
                "PUT",
                f"/subscriptions/{clean_subscription_id}.json",
                json_body={
                    "subscription": {"next_billing_at": preview["nextBillingAt"]}
                },
                idempotency_key=_phase_idempotency_key(clean_key, "billing-date"),
                _typed_financial_operation="subscription_no_charge_reactivation",
            )
        readback = _subscription_record(
            self._get(f"/subscriptions/{clean_subscription_id}.json")
        )
        readback_state = str(readback.get("state") or "").strip().casefold()
        readback_customer_id = _subscription_customer_id(readback)
        readback_next = _parse_api_datetime(
            readback.get("next_assessment_at") or readback.get("next_billing_at"),
            "subscription next billing timestamp",
        )
        balances = self.subscription_account_balances(clean_subscription_id)[
            "balances"
        ]
        verified = (
            bool(billing_date_result.get("ok"))
            and readback_state in {"active", "trialing"}
            and readback_customer_id == preview["customerId"]
            and abs((readback_next - expected_next).total_seconds()) <= 60
            and _all_balances_zero(balances)
        )
        if not verified:
            raise MaxioUnavailableError(
                "no-charge reactivation did not read back the exact active state, zero balances, "
                "and future billing date; do not activate downstream"
            )
        final = {
            **preview,
            "ok": True,
            "status": "credited_reactivated_and_scheduled",
            "updated": not (
                bool(credit_result.get("duplicate"))
                and bool(reactivation_result.get("duplicate"))
                and bool(billing_date_result.get("duplicate"))
            ),
            "duplicate": bool(
                credit_result.get("duplicate")
                and reactivation_result.get("duplicate")
                and billing_date_result.get("duplicate")
            ),
            "verified": True,
            "retryAllowed": False,
            "idempotencyKey": clean_key,
            "previewHash": requested_preview_hash,
            "readbackState": readback_state,
            "readbackCustomerId": readback_customer_id,
            "readbackNextBillingAt": readback_next.isoformat(),
            "serviceCreditIssuedCents": preview["waivedChargeCents"],
            "serviceCreditConsumedCents": preview["waivedChargeCents"],
            "customerChargeCents": 0,
            "successfulPaymentVerified": False,
            "balances": balances,
            "downstreamActivationAllowed": True,
        }
        self._journal(
            "accepted",
            receipt_key,
            "RESULT",
            receipt_path,
            receipt_hash,
            final,
        )
        return final

    def _subscription_payment_context(
        self,
        subscription_id: int,
        customer_id: int,
        payment_profile_id: int,
    ) -> dict[str, Any]:
        clean_subscription_id = _positive_id(subscription_id, "subscription_id")
        clean_customer_id = _positive_id(customer_id, "customer_id")
        clean_profile_id = _positive_id(payment_profile_id, "payment_profile_id")
        subscription = _subscription_record(
            self._get(f"/subscriptions/{clean_subscription_id}.json")
        )
        if _required_integer_field(subscription, ("id",), "subscription ID") != clean_subscription_id:
            raise MaxioUnavailableError("Maxio subscription response did not match the requested ID")
        if _subscription_customer_id(subscription) != clean_customer_id:
            raise MaxioScopeError("subscription_id belongs to a different Maxio customer")
        profiles = _wrapped_records(
            self._get(
                "/payment_profiles.json",
                params={"customer_id": clean_customer_id, "page": 1, "per_page": 200},
            ),
            "payment_profile",
        )
        selected = [row for row in profiles if _numeric_api_id(row.get("id")) == clean_profile_id]
        if len(selected) != 1:
            raise MaxioScopeError(
                "payment_profile_id did not resolve exactly under the Maxio customer"
            )
        profile = selected[0]
        if _numeric_api_id(profile.get("customer_id")) != clean_customer_id:
            raise MaxioScopeError("payment_profile_id belongs to a different Maxio customer")
        if profile.get("disabled_at") or profile.get("disabled") is True:
            raise MaxioScopeError("payment_profile_id is disabled")
        _assert_payment_profile_not_expired(profile)
        current_profile_id = _optional_subscription_payment_profile_id(subscription)
        product = subscription.get("product")
        product_record = product if isinstance(product, Mapping) else {}
        if (
            current_profile_id != clean_profile_id
            and product_record.get("require_billing_address") is True
        ):
            missing_address_fields = _missing_payment_profile_billing_address_fields(
                profile
            )
            if missing_address_fields:
                raise MaxioScopeError(
                    "payment_profile_id is missing the complete billing address required "
                    "by this subscription: " + ", ".join(missing_address_fields)
                )
        return {
            "subscriptionId": clean_subscription_id,
            "customerId": clean_customer_id,
            "paymentProfileId": clean_profile_id,
            "currentPaymentProfileId": current_profile_id,
            "currentState": str(subscription.get("state") or "").strip().casefold(),
            "targetPaymentProfile": _public_payment_profile(profile),
            "subscription": subscription,
        }

    def invoices_by_customer(self, customer_id: int, *, max_rows: int = 50) -> dict[str, Any]:
        rows = _bounded_rows(max_rows)
        payload = self._get(
            "/invoices.json",
            params={"customer_ids": _positive_id(customer_id, "customer_id"), "page": 1, "per_page": rows},
        )
        return _collection(payload, max_rows=rows, operation="invoices_by_customer")

    def tax_report(
        self,
        *,
        month: str = "",
        start_date: str = "",
        end_date: str = "",
    ) -> dict[str, Any]:
        """Generate one validated Excel tax report from paginated Maxio invoices."""
        start, end = resolve_report_period(
            month=month,
            start_date=start_date,
            end_date=end_date,
        )
        invoices: list[dict[str, Any]] = []
        page_size = 200
        for page in range(1, 51):
            payload = self._get(
                "/invoices.json",
                params={
                    "date_field": "issue_date",
                    "start_date": start.isoformat(),
                    "end_date": end.isoformat(),
                    "direction": "asc",
                    "page": page,
                    "per_page": page_size,
                },
            )
            collection = payload.get("invoices") if isinstance(payload, Mapping) else payload
            batch = _wrapped_records(collection, "invoice")
            invoices.extend(batch)
            if len(batch) < page_size:
                break
        else:
            raise MaxioUnavailableError("Maxio tax-report pagination exceeded 10,000 invoices")
        rows = transform_invoices(invoices, start, end)
        return write_tax_report(rows, start, end, self.settings.report_output_dir)

    def invoice(self, invoice_uid: str) -> dict[str, Any]:
        clean_uid = str(invoice_uid or "").strip()
        if not INVOICE_UID.fullmatch(clean_uid):
            raise MaxioScopeError("invoice_uid must be one exact Maxio invoice UID")
        return self._single(f"/invoices/{clean_uid}.json", operation="invoice")

    def subscription_account_balances(self, subscription_id: int) -> dict[str, Any]:
        clean_subscription_id = _positive_id(subscription_id, "subscription_id")
        payload = self._get(f"/subscriptions/{clean_subscription_id}/account_balances.json")
        return {
            "ok": True,
            "operation": "subscription_account_balances",
            "subscriptionId": clean_subscription_id,
            "balances": _account_balances(payload),
        }

    # AgentChat/direct_codex 2026-07-31T00:00:00-04:00: make promotions a typed,
    # ticket-bound financial operation instead of a generic API mutation.
    def subscription_coupon_preview(
        self,
        subscription_id: int,
        coupon_code: str,
        ticket_number: str,
    ) -> dict[str, Any]:
        """Preview one exact coupon on one subscription without changing billing."""

        plan = self._subscription_coupon_plan(subscription_id, coupon_code, ticket_number)
        return {
            "ok": True,
            "status": "already_applied" if plan["existingCoupon"] else "preview",
            "previewHash": plan["previewHash"],
            "subscriptionId": plan["subscriptionId"],
            "ticketNumber": plan["ticketNumber"],
            "coupon": plan["coupon"],
            "currentCouponCodes": plan["currentCouponCodes"],
            "applyRequired": not bool(plan["existingCoupon"]),
            "writesPerformed": False,
            "existingInvoiceAdjustmentIncluded": False,
            "refundIncluded": False,
            "serviceCreditIncluded": False,
            "invoiceDispositionRequired": bool(plan["balances"]["openInvoiceBalanceCents"]),
            "balances": plan["balances"],
        }

    def apply_subscription_coupon(
        self,
        subscription_id: int,
        coupon_code: str,
        ticket_number: str,
        *,
        preview_hash: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        """Apply one exact previewed coupon and verify subscription readback."""

        plan = self._subscription_coupon_plan(subscription_id, coupon_code, ticket_number)
        clean_hash = _required_preview_hash(preview_hash, plan["previewHash"])
        clean_key = _required_idempotency_key(idempotency_key)
        if plan["existingCoupon"]:
            return {
                "ok": True,
                "status": "already_applied",
                "updated": False,
                "duplicate": True,
                "verified": True,
                "subscriptionId": plan["subscriptionId"],
                "ticketNumber": plan["ticketNumber"],
                "coupon": plan["coupon"],
                "couponCodes": plan["currentCouponCodes"],
                "previewHash": clean_hash,
                "idempotencyKey": clean_key,
                "balances": plan["balances"],
                "invoiceDispositionRequired": bool(plan["balances"]["openInvoiceBalanceCents"]),
            }

        result = self.api_request(
            "POST",
            f"/subscriptions/{plan['subscriptionId']}/add_coupon.json",
            json_body={"codes": [plan["coupon"]["code"]]},
            idempotency_key=clean_key,
            _typed_financial_operation="subscription_coupon",
        )
        if not result.get("ok"):
            return {
                **result,
                "verified": False,
                "subscriptionId": plan["subscriptionId"],
                "ticketNumber": plan["ticketNumber"],
                "coupon": plan["coupon"],
                "previewHash": clean_hash,
            }

        readback = _subscription_record(
            self._get(f"/subscriptions/{plan['subscriptionId']}.json")
        )
        coupon_codes = _subscription_coupon_codes(readback)
        if plan["coupon"]["code"].casefold() not in {
            code.casefold() for code in coupon_codes
        }:
            raise MaxioUnavailableError(
                "Maxio accepted the coupon but subscription readback did not contain it; "
                "do not retry until the subscription is reconciled"
            )
        balances = self.subscription_account_balances(plan["subscriptionId"])["balances"]
        return {
            "ok": True,
            "status": "applied",
            "updated": not bool(result.get("duplicate")),
            "duplicate": bool(result.get("duplicate")),
            "verified": True,
            "subscriptionId": plan["subscriptionId"],
            "ticketNumber": plan["ticketNumber"],
            "coupon": plan["coupon"],
            "couponCodes": coupon_codes,
            "previewHash": clean_hash,
            "idempotencyKey": clean_key,
            "balances": balances,
            "invoiceDispositionRequired": bool(balances["openInvoiceBalanceCents"]),
            "existingInvoiceAdjustmentIncluded": False,
            "refundIncluded": False,
            "serviceCreditIncluded": False,
            "providerResult": result.get("body"),
        }

    def subscription_product_change_preview(
        self,
        subscription_id: int,
        product_id: int,
        ticket_number: str,
    ) -> dict[str, Any]:
        """Preview one same-family Nova Integrated product change with no proration."""

        plan = self._subscription_product_change_plan(
            subscription_id,
            product_id,
            ticket_number,
        )
        return {
            "ok": True,
            "status": "already_configured" if plan["duplicate"] else "preview",
            **plan,
            "applyRequired": not plan["duplicate"],
            "providerRequest": {
                "method": "PUT",
                "path": f"/subscriptions/{plan['subscriptionId']}.json",
                "body": {"subscription": {"product_id": plan["targetProduct"]["id"]}},
            },
            "automaticChargeAuthorized": False,
            "automaticCreditAuthorized": False,
            "prorationAuthorized": False,
            "couponChangeAuthorized": False,
            "componentChangeAuthorized": False,
            "invoiceAdjustmentAuthorized": False,
            "writesPerformed": False,
        }

    def apply_subscription_product_change(
        self,
        subscription_id: int,
        product_id: int,
        ticket_number: str,
        *,
        preview_hash: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        """Apply one unchanged product preview and prove billing state was preserved."""

        plan = self._subscription_product_change_plan(
            subscription_id,
            product_id,
            ticket_number,
        )
        clean_hash = _required_preview_hash(preview_hash, plan["previewHash"])
        clean_key = _required_idempotency_key(idempotency_key)
        if plan["duplicate"]:
            return {
                "ok": True,
                "status": "already_configured",
                "updated": False,
                "duplicate": True,
                "verified": True,
                **plan,
                "previewHash": clean_hash,
                "idempotencyKey": clean_key,
            }

        result = self.api_request(
            "PUT",
            f"/subscriptions/{plan['subscriptionId']}.json",
            json_body={"subscription": {"product_id": plan["targetProduct"]["id"]}},
            idempotency_key=clean_key,
            _typed_financial_operation="subscription_product_change",
        )
        if not result.get("ok"):
            return {
                **result,
                "verified": False,
                "subscriptionId": plan["subscriptionId"],
                "ticketNumber": plan["ticketNumber"],
                "targetProduct": plan["targetProduct"],
                "previewHash": clean_hash,
            }

        subscription = _subscription_record(
            self._get(f"/subscriptions/{plan['subscriptionId']}.json")
        )
        readback_product = _subscription_product_summary(subscription)
        if readback_product["id"] != plan["targetProduct"]["id"]:
            raise MaxioUnavailableError(
                "Maxio accepted the product change but readback did not match; do not retry"
            )
        readback_coupons = _subscription_coupon_codes(subscription)
        readback_allocations = _nonzero_component_allocations(
            self._subscription_component_rows(plan["subscriptionId"])
        )
        readback_balances = self.subscription_account_balances(plan["subscriptionId"])[
            "balances"
        ]
        readback_period = _subscription_period_summary(subscription)
        if readback_coupons != plan["currentCouponCodes"]:
            raise MaxioUnavailableError(
                "Maxio product change altered coupons; do not retry until reconciled"
            )
        if readback_allocations != plan["nonzeroComponentAllocations"]:
            raise MaxioUnavailableError(
                "Maxio product change altered component allocations; do not retry until reconciled"
            )
        if readback_balances != plan["balances"]:
            raise MaxioUnavailableError(
                "Maxio product change altered balances; do not retry until reconciled"
            )
        if readback_period != plan["billingPeriod"]:
            raise MaxioUnavailableError(
                "Maxio product change altered the billing period; do not retry until reconciled"
            )
        return {
            "ok": True,
            "status": "applied",
            "updated": not bool(result.get("duplicate")),
            "duplicate": bool(result.get("duplicate")),
            "verified": True,
            "subscriptionId": plan["subscriptionId"],
            "ticketNumber": plan["ticketNumber"],
            "previousProduct": plan["currentProduct"],
            "product": readback_product,
            "couponCodes": readback_coupons,
            "nonzeroComponentAllocations": readback_allocations,
            "balances": readback_balances,
            "billingPeriod": readback_period,
            "previewHash": clean_hash,
            "idempotencyKey": clean_key,
            "automaticChargeApplied": False,
            "automaticCreditApplied": False,
            "prorationApplied": False,
            "invoiceAdjustmentApplied": False,
            "providerResult": result.get("body"),
        }

    def manual_service_credit_preview(
        self,
        subscription_id: int,
        amount_cents: int,
        ticket_number: str,
    ) -> dict[str, Any]:
        """Preview a separately calculated service credit without changing allocations."""

        plan = self._manual_service_credit_plan(subscription_id, amount_cents, ticket_number)
        return {
            "ok": True,
            "status": "preview",
            "previewHash": plan["previewHash"],
            "subscriptionId": plan["subscriptionId"],
            "ticketNumber": plan["ticketNumber"],
            "amountCents": plan["amountCents"],
            "memo": plan["memo"],
            "currentServiceCreditBalanceCents": plan["currentServiceCreditBalanceCents"],
            "expectedServiceCreditBalanceCents": plan["expectedServiceCreditBalanceCents"],
            "allocationChangeIncluded": False,
            "invoiceApplicationIncluded": False,
            "applyRequired": True,
        }

    def apply_manual_service_credit(
        self,
        subscription_id: int,
        amount_cents: int,
        ticket_number: str,
        *,
        preview_hash: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        """Issue one exact previewed service credit and verify its account balance."""

        plan = self._manual_service_credit_plan(subscription_id, amount_cents, ticket_number)
        clean_hash = _required_preview_hash(preview_hash, plan["previewHash"])
        clean_key = _required_idempotency_key(idempotency_key)
        result = self.api_request(
            "POST",
            f"/subscriptions/{plan['subscriptionId']}/service_credits.json",
            json_body={
                "service_credit": {
                    "amount": _currency_amount(plan["amountCents"]),
                    "memo": plan["memo"],
                }
            },
            idempotency_key=clean_key,
            _typed_financial_operation="manual_service_credit",
        )
        if not result.get("ok"):
            return {
                **result,
                "verified": False,
                "previewHash": clean_hash,
                "amountCents": plan["amountCents"],
            }

        readback = self.subscription_account_balances(plan["subscriptionId"])["balances"]
        actual_balance = int(readback["serviceCreditBalanceCents"])
        if actual_balance != plan["expectedServiceCreditBalanceCents"]:
            raise MaxioUnavailableError(
                "Maxio accepted the service credit but the exact account-balance increase was not verified; "
                "do not retry until the subscription is read again"
            )
        return {
            "ok": True,
            "updated": not bool(result.get("duplicate")),
            "duplicate": bool(result.get("duplicate")),
            "verified": True,
            "previewHash": clean_hash,
            "idempotencyKey": clean_key,
            "subscriptionId": plan["subscriptionId"],
            "ticketNumber": plan["ticketNumber"],
            "amountCents": plan["amountCents"],
            "memo": plan["memo"],
            "beforeServiceCreditBalanceCents": plan["currentServiceCreditBalanceCents"],
            "afterServiceCreditBalanceCents": actual_balance,
            "allocationChangeIncluded": False,
            "invoiceApplicationIncluded": False,
            "providerResult": result.get("body"),
        }

    def nova_integrated_promo_credit_preview(
        self,
        subscription_id: int,
        location_id: int,
        merchant_provider: str,
        monthly_rate_cents: int,
        ticket_number: str,
    ) -> dict[str, Any]:
        """Preview the fixed three-month credit for one isolated Nova Integrated location."""

        plan = self._nova_integrated_promo_credit_plan(
            subscription_id,
            location_id,
            merchant_provider,
            monthly_rate_cents,
            ticket_number,
        )
        return {
            "ok": True,
            "status": "already_applied" if plan["existingPromoCredit"] else "preview",
            **plan,
            "applyRequired": not bool(plan["existingPromoCredit"]),
            "writesPerformed": False,
            "invoiceApplicationIncluded": False,
            "accountFlatRateMutationIncluded": False,
        }

    def apply_nova_integrated_promo_credit(
        self,
        subscription_id: int,
        location_id: int,
        merchant_provider: str,
        monthly_rate_cents: int,
        ticket_number: str,
        *,
        preview_hash: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        """Issue one unchanged Nova Integrated Promo credit and verify the exact balance."""

        plan = self._nova_integrated_promo_credit_plan(
            subscription_id,
            location_id,
            merchant_provider,
            monthly_rate_cents,
            ticket_number,
        )
        clean_hash = _required_preview_hash(preview_hash, plan["previewHash"])
        clean_key = _required_idempotency_key(idempotency_key)
        if plan["existingPromoCredit"]:
            return {
                "ok": True,
                "status": "already_applied",
                "updated": False,
                "duplicate": True,
                "verified": True,
                **plan,
                "previewHash": clean_hash,
                "idempotencyKey": clean_key,
                "invoiceApplicationIncluded": False,
                "accountFlatRateMutationIncluded": False,
            }

        result = self.api_request(
            "POST",
            f"/subscriptions/{plan['subscriptionId']}/service_credits.json",
            json_body={
                "service_credit": {
                    "amount": _currency_amount(plan["creditAmountCents"]),
                    "memo": plan["memo"],
                }
            },
            idempotency_key=clean_key,
            _typed_financial_operation="nova_integrated_promo_credit",
        )
        if not result.get("ok"):
            return {
                **result,
                "verified": False,
                "previewHash": clean_hash,
                "creditAmountCents": plan["creditAmountCents"],
            }
        balances = self.subscription_account_balances(plan["subscriptionId"])["balances"]
        actual_balance = int(balances["serviceCreditBalanceCents"])
        if actual_balance != plan["expectedServiceCreditBalanceCents"]:
            raise MaxioUnavailableError(
                "Maxio accepted the Nova Integrated Promo credit but its exact balance increase "
                "was not verified; read the subscription before any retry"
            )
        return {
            "ok": True,
            "status": "applied",
            "updated": not bool(result.get("duplicate")),
            "duplicate": bool(result.get("duplicate")),
            "verified": True,
            **plan,
            "previewHash": clean_hash,
            "idempotencyKey": clean_key,
            "afterServiceCreditBalanceCents": actual_balance,
            "invoiceApplicationIncluded": False,
            "accountFlatRateMutationIncluded": False,
            "providerResult": result.get("body"),
        }

    def partial_location_collection_preview(
        self,
        subscription_id: int,
        location_count: int,
        unit_rate_cents: int,
        authorized_amount_cents: int,
        service_period_start: str,
        service_period_end: str,
        ticket_number: str,
    ) -> dict[str, Any]:
        """Preview one exact, immediate collection for omitted locations."""

        plan = self._partial_location_collection_plan(
            subscription_id,
            location_count,
            unit_rate_cents,
            authorized_amount_cents,
            service_period_start,
            service_period_end,
            ticket_number,
        )
        return {
            "ok": True,
            "status": "already_collected" if plan["existingSuccessfulCollection"] else "preview",
            "previewHash": plan["previewHash"],
            "subscriptionId": plan["subscriptionId"],
            "ticketNumber": plan["ticketNumber"],
            "locationCount": plan["locationCount"],
            "totalActiveLocations": plan["totalActiveLocations"],
            "componentId": plan["componentId"],
            "unitRateCents": plan["unitRateCents"],
            "authorizedAmountCents": plan["authorizedAmountCents"],
            "servicePeriodStart": plan["servicePeriodStart"],
            "servicePeriodEnd": plan["servicePeriodEnd"],
            "memo": plan["memo"],
            "currentBillingAmountCents": plan["currentBillingAmountCents"],
            "nextAssessmentAt": plan["nextAssessmentAt"],
            "balances": plan["balances"],
            "paymentProfile": plan["paymentProfile"],
            "collectionControls": plan["collectionControls"],
            "existingSuccessfulCollection": plan["existingSuccessfulCollection"],
            "applyRequired": not bool(plan["existingSuccessfulCollection"]),
            "writesPerformed": False,
        }

    def apply_partial_location_collection(
        self,
        subscription_id: int,
        location_count: int,
        unit_rate_cents: int,
        authorized_amount_cents: int,
        service_period_start: str,
        service_period_end: str,
        ticket_number: str,
        *,
        preview_hash: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        """Attempt one exact previewed collection and verify transactions and balances."""

        clean_key = _required_idempotency_key(idempotency_key)
        plan = self._partial_location_collection_plan(
            subscription_id,
            location_count,
            unit_rate_cents,
            authorized_amount_cents,
            service_period_start,
            service_period_end,
            ticket_number,
        )
        clean_hash = str(preview_hash or "").strip().lower()
        if not re.fullmatch(r"[0-9a-f]{64}", clean_hash):
            raise MaxioScopeError("preview_hash must be one exact 64-character SHA-256 value")

        if plan["existingSuccessfulCollection"]:
            return self._partial_location_collection_result(
                plan,
                preview_hash=clean_hash,
                idempotency_key=clean_key,
                duplicate=True,
                provider_result=None,
            )

        body = {"charge": dict(plan["providerCharge"])}
        path = f"/subscriptions/{plan['subscriptionId']}/charges.json"
        request_hash = _api_request_hash("POST", path, {}, body)
        prior_request = self._prior_request_operation("POST", path, request_hash)
        if prior_request:
            if prior_request["status"] == "pending":
                raise MaxioScopeError(
                    "this exact partial-location collection has an uncertain pending outcome; "
                    "do not retry until Maxio transactions and balances are reconciled"
                )
            readback = self._partial_location_collection_plan(
                subscription_id,
                location_count,
                unit_rate_cents,
                authorized_amount_cents,
                service_period_start,
                service_period_end,
                ticket_number,
            )
            if readback["existingSuccessfulCollection"]:
                return self._partial_location_collection_result(
                    readback,
                    preview_hash=clean_hash,
                    idempotency_key=clean_key,
                    duplicate=True,
                    provider_result=None,
                )
            return {
                "ok": False,
                "status": "previous_attempt_not_retried",
                "attempted": True,
                "updated": False,
                "duplicate": True,
                "verified": _all_balances_zero(readback["balances"]),
                "retryAllowed": False,
                "subscriptionId": readback["subscriptionId"],
                "ticketNumber": readback["ticketNumber"],
                "authorizedAmountCents": readback["authorizedAmountCents"],
                "memo": readback["memo"],
                "previewHash": clean_hash,
                "idempotencyKey": clean_key,
                "balances": readback["balances"],
                "providerStatusCode": (prior_request.get("evidence") or {}).get("statusCode"),
                "reason": (
                    "The exact provider request was already attempted and was not verified as collected; "
                    "a second collection attempt is blocked."
                ),
            }

        clean_hash = _required_preview_hash(clean_hash, plan["previewHash"])
        result = self.api_request(
            "POST",
            path,
            json_body=body,
            idempotency_key=clean_key,
            _typed_financial_operation="partial_location_collection",
        )
        readback = self._partial_location_collection_plan(
            subscription_id,
            location_count,
            unit_rate_cents,
            authorized_amount_cents,
            service_period_start,
            service_period_end,
            ticket_number,
        )
        if readback["existingSuccessfulCollection"]:
            return self._partial_location_collection_result(
                readback,
                preview_hash=clean_hash,
                idempotency_key=clean_key,
                duplicate=bool(result.get("duplicate")),
                provider_result=result,
            )
        if not _all_balances_zero(readback["balances"]):
            raise MaxioUnavailableError(
                "the collection was not verified and account balances changed; "
                "do not retry until Maxio is reconciled"
            )
        new_transactions = [
            row
            for row in readback["transactions"]
            if row["id"] not in set(plan["transactionIds"])
        ]
        failed_payments = [
            row
            for row in new_transactions
            if row["transactionType"] == "payment"
            and row["amountCents"] == plan["authorizedAmountCents"]
            and not row["success"]
        ]
        return {
            "ok": False,
            "status": "declined" if failed_payments else "provider_rejected",
            "attempted": True,
            "updated": False,
            "duplicate": bool(result.get("duplicate")),
            "verified": bool(failed_payments),
            "retryAllowed": False,
            "subscriptionId": plan["subscriptionId"],
            "ticketNumber": plan["ticketNumber"],
            "authorizedAmountCents": plan["authorizedAmountCents"],
            "memo": plan["memo"],
            "previewHash": clean_hash,
            "idempotencyKey": clean_key,
            "balances": readback["balances"],
            "newTransactions": new_transactions,
            "providerStatusCode": result.get("statusCode"),
            "providerResult": result.get("body"),
            "reason": (
                "The payment was declined and no charge accrued; a second attempt is blocked."
                if failed_payments
                else "Maxio did not produce a verified charge and payment; a second attempt is blocked."
            ),
        }

    def invoice_refund_preview(
        self,
        invoice_uid: str,
        payment_id: int,
        refund_amount_cents: int,
        ticket_number: str,
    ) -> dict[str, Any]:
        """Preview one exact invoice-payment refund without changing Maxio."""

        plan = self._invoice_refund_plan(
            invoice_uid,
            payment_id,
            refund_amount_cents,
            ticket_number,
        )
        return {
            "ok": True,
            "status": "already_refunded" if plan["existingRefund"] else "preview",
            "previewHash": plan["previewHash"],
            "invoiceUid": plan["invoiceUid"],
            "invoiceNumber": plan["invoiceNumber"],
            "subscriptionId": plan["subscriptionId"],
            "ticketNumber": plan["ticketNumber"],
            "paymentId": plan["paymentId"],
            "paymentAppliedAmountCents": plan["paymentAppliedAmountCents"],
            "previousRefundedForPaymentCents": plan["previousRefundedForPaymentCents"],
            "remainingRefundableForPaymentCents": plan["remainingRefundableForPaymentCents"],
            "refundAmountCents": plan["refundAmountCents"],
            "memo": plan["memo"],
            "invoiceStatus": plan["invoiceStatus"],
            "invoiceRefundAmountCents": plan["invoiceRefundAmountCents"],
            "refundControls": plan["refundControls"],
            "existingRefund": plan["existingRefund"],
            "applyRequired": not bool(plan["existingRefund"]),
            "writesPerformed": False,
        }

    def apply_invoice_refund(
        self,
        invoice_uid: str,
        payment_id: int,
        refund_amount_cents: int,
        ticket_number: str,
        *,
        preview_hash: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        """Refund one exact previewed invoice payment and verify invoice readback."""

        clean_key = _required_idempotency_key(idempotency_key)
        plan = self._invoice_refund_plan(
            invoice_uid,
            payment_id,
            refund_amount_cents,
            ticket_number,
        )
        clean_hash = str(preview_hash or "").strip().lower()
        if not re.fullmatch(r"[0-9a-f]{64}", clean_hash):
            raise MaxioScopeError("preview_hash must be one exact 64-character SHA-256 value")
        if plan["existingRefund"]:
            return self._invoice_refund_result(
                plan,
                preview_hash=clean_hash,
                idempotency_key=clean_key,
                duplicate=True,
                provider_result=None,
            )

        body = {"refund": dict(plan["providerRefund"])}
        path = f"/invoices/{plan['invoiceUid']}/refunds.json"
        request_hash = _api_request_hash("POST", path, {}, body)
        prior_request = self._prior_request_operation("POST", path, request_hash)
        if prior_request:
            if prior_request["status"] == "pending":
                raise MaxioScopeError(
                    "this exact invoice refund has an uncertain pending outcome; do not retry "
                    "until the invoice is reconciled"
                )
            readback = self._invoice_refund_plan(
                invoice_uid,
                payment_id,
                refund_amount_cents,
                ticket_number,
            )
            if readback["existingRefund"]:
                return self._invoice_refund_result(
                    readback,
                    preview_hash=clean_hash,
                    idempotency_key=clean_key,
                    duplicate=True,
                    provider_result=None,
                )
            return {
                "ok": False,
                "status": "previous_attempt_not_retried",
                "attempted": True,
                "updated": False,
                "duplicate": True,
                "verified": False,
                "retryAllowed": False,
                "invoiceUid": readback["invoiceUid"],
                "invoiceNumber": readback["invoiceNumber"],
                "paymentId": readback["paymentId"],
                "refundAmountCents": readback["refundAmountCents"],
                "memo": readback["memo"],
                "previewHash": clean_hash,
                "idempotencyKey": clean_key,
                "providerStatusCode": (prior_request.get("evidence") or {}).get("statusCode"),
                "reason": (
                    "The exact provider request was already attempted and was not verified as "
                    "refunded; a second refund attempt is blocked."
                ),
            }

        clean_hash = _required_preview_hash(clean_hash, plan["previewHash"])
        result = self.api_request(
            "POST",
            path,
            json_body=body,
            idempotency_key=clean_key,
            _typed_financial_operation="invoice_refund",
        )
        readback = self._invoice_refund_plan(
            invoice_uid,
            payment_id,
            refund_amount_cents,
            ticket_number,
        )
        if readback["existingRefund"]:
            return self._invoice_refund_result(
                readback,
                preview_hash=clean_hash,
                idempotency_key=clean_key,
                duplicate=bool(result.get("duplicate")),
                provider_result=result,
            )
        return {
            "ok": False,
            "status": "provider_rejected",
            "attempted": True,
            "updated": False,
            "duplicate": bool(result.get("duplicate")),
            "verified": False,
            "retryAllowed": False,
            "invoiceUid": plan["invoiceUid"],
            "invoiceNumber": plan["invoiceNumber"],
            "paymentId": plan["paymentId"],
            "refundAmountCents": plan["refundAmountCents"],
            "memo": plan["memo"],
            "previewHash": clean_hash,
            "idempotencyKey": clean_key,
            "providerStatusCode": result.get("statusCode"),
            "providerResult": result.get("body"),
            "reason": (
                "Maxio did not produce exact refund readback; a second attempt is blocked."
            ),
        }


    def invoice_void_preview(
        self,
        invoice_uid: str,
        ticket_number: str,
        reason: str,
    ) -> dict[str, Any]:
        """Preview voiding one open/canceled invoice without changing Maxio."""
        plan = self._invoice_void_plan(invoice_uid, ticket_number, reason)
        return {
            "ok": True,
            "status": "preview",
            "previewHash": plan["previewHash"],
            "invoiceUid": plan["invoiceUid"],
            "invoiceNumber": plan["invoiceNumber"],
            "subscriptionId": plan["subscriptionId"],
            "invoiceStatus": plan["invoiceStatus"],
            "ticketNumber": plan["ticketNumber"],
            "reason": plan["reason"],
            "memo": plan["memo"],
            "applyRequired": plan["applyRequired"],
            "writesPerformed": False,
        }

    def apply_invoice_void(
        self,
        invoice_uid: str,
        ticket_number: str,
        reason: str,
        *,
        preview_hash: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        """Void one exact previewed open/canceled invoice and verify invoice readback."""
        clean_key = _required_idempotency_key(idempotency_key)
        plan = self._invoice_void_plan(invoice_uid, ticket_number, reason)
        clean_hash = str(preview_hash or "").strip().lower()
        if not re.fullmatch(r"[0-9a-f]{64}", clean_hash):
            raise MaxioScopeError("preview_hash must be one exact 64-character SHA-256 value")
        if not plan["applyRequired"]:
            return self._invoice_void_result(
                plan,
                preview_hash=clean_hash,
                idempotency_key=clean_key,
                duplicate=True,
                provider_result=None,
            )

        body = {"void": {"reason": plan["reason"]}}
        path = f"/invoices/{plan['invoiceUid']}/void.json"
        request_hash = _api_request_hash("POST", path, {}, body)
        prior_request = self._prior_request_operation("POST", path, request_hash)
        if prior_request:
            if prior_request["status"] == "pending":
                raise MaxioScopeError(
                    "this exact invoice void has an uncertain pending outcome; do not retry "
                    "until the invoice is reconciled"
                )
            readback = self._invoice_void_plan(invoice_uid, ticket_number, reason)
            if not readback["applyRequired"]:
                return self._invoice_void_result(
                    readback,
                    preview_hash=clean_hash,
                    idempotency_key=clean_key,
                    duplicate=True,
                    provider_result=None,
                )
            return {
                "ok": False,
                "status": "previous_attempt_not_retried",
                "attempted": True,
                "updated": False,
                "duplicate": True,
                "verified": False,
                "retryAllowed": False,
                "invoiceUid": readback["invoiceUid"],
                "invoiceNumber": readback["invoiceNumber"],
                "previewHash": clean_hash,
                "idempotencyKey": clean_key,
                "providerStatusCode": (prior_request.get("evidence") or {}).get("statusCode"),
                "reason": (
                    "The exact provider request was already attempted and was not verified as "
                    "voided; a second void attempt is blocked."
                ),
            }

        clean_hash = _required_preview_hash(clean_hash, plan["previewHash"])
        result = self.api_request(
            "POST",
            path,
            json_body=body,
            idempotency_key=clean_key,
            _typed_financial_operation="invoice_void",
        )
        readback = self._invoice_void_plan(invoice_uid, ticket_number, reason)
        if not readback["applyRequired"]:
            return self._invoice_void_result(
                readback,
                preview_hash=clean_hash,
                idempotency_key=clean_key,
                duplicate=bool(result.get("duplicate")),
                provider_result=result,
            )
        return {
            "ok": False,
            "status": "provider_rejected",
            "attempted": True,
            "updated": False,
            "duplicate": bool(result.get("duplicate")),
            "verified": False,
            "retryAllowed": False,
            "invoiceUid": readback["invoiceUid"],
            "invoiceNumber": readback["invoiceNumber"],
            "previewHash": clean_hash,
            "idempotencyKey": clean_key,
            "providerStatusCode": result.get("statusCode"),
            "providerResult": result.get("body"),
            "reason": (
                "Maxio did not produce exact void readback; a second attempt is blocked."
            ),
        }

    def billing_cycle_recovery_preview(
        self,
        subscription_id: int,
        cycle_count: int,
        cycle_amount_cents: int,
        authorized_amount_cents: int,
        service_period_start: str,
        service_period_end: str,
        ticket_number: str,
        decline_action: str = "no_accrual",
    ) -> dict[str, Any]:
        """Preview one exact collection for previously missed monthly cycles."""

        plan = self._billing_cycle_recovery_plan(
            subscription_id,
            cycle_count,
            cycle_amount_cents,
            authorized_amount_cents,
            service_period_start,
            service_period_end,
            ticket_number,
            decline_action,
        )
        return {
            "ok": True,
            "status": "already_collected" if plan["existingSuccessfulCollection"] else "preview",
            "previewHash": plan["previewHash"],
            "subscriptionId": plan["subscriptionId"],
            "ticketNumber": plan["ticketNumber"],
            "declineAction": plan["declineAction"],
            "cycleCount": plan["cycleCount"],
            "cycleAmountCents": plan["cycleAmountCents"],
            "authorizedAmountCents": plan["authorizedAmountCents"],
            "servicePeriodStart": plan["servicePeriodStart"],
            "servicePeriodEnd": plan["servicePeriodEnd"],
            "memo": plan["memo"],
            "currentBillingAmountCents": plan["currentBillingAmountCents"],
            "currentPeriodStart": plan["currentPeriodStart"],
            "currentPeriodEnd": plan["currentPeriodEnd"],
            "currentPeriodOverlapDays": plan["currentPeriodOverlapDays"],
            "nextAssessmentAt": plan["nextAssessmentAt"],
            "balances": plan["balances"],
            "paymentProfile": plan["paymentProfile"],
            "collectionControls": plan["collectionControls"],
            "existingSuccessfulCollection": plan["existingSuccessfulCollection"],
            "applyRequired": not bool(plan["existingSuccessfulCollection"]),
            "writesPerformed": False,
        }

    def apply_billing_cycle_recovery(
        self,
        subscription_id: int,
        cycle_count: int,
        cycle_amount_cents: int,
        authorized_amount_cents: int,
        service_period_start: str,
        service_period_end: str,
        ticket_number: str,
        *,
        preview_hash: str,
        idempotency_key: str,
        decline_action: str = "no_accrual",
    ) -> dict[str, Any]:
        """Attempt one exact historical-cycle collection with no automatic retry."""

        clean_key = _required_idempotency_key(idempotency_key)
        plan = self._billing_cycle_recovery_plan(
            subscription_id,
            cycle_count,
            cycle_amount_cents,
            authorized_amount_cents,
            service_period_start,
            service_period_end,
            ticket_number,
            decline_action,
        )
        clean_hash = str(preview_hash or "").strip().lower()
        if not re.fullmatch(r"[0-9a-f]{64}", clean_hash):
            raise MaxioScopeError("preview_hash must be one exact 64-character SHA-256 value")

        if plan["existingSuccessfulCollection"]:
            return self._billing_cycle_recovery_result(
                plan,
                preview_hash=clean_hash,
                idempotency_key=clean_key,
                duplicate=True,
                provider_result=None,
            )

        body = {"charge": dict(plan["providerCharge"])}
        path = f"/subscriptions/{plan['subscriptionId']}/charges.json"
        request_hash = _api_request_hash("POST", path, {}, body)
        prior_request = self._prior_request_operation("POST", path, request_hash)
        if prior_request:
            if prior_request["status"] == "pending":
                raise MaxioScopeError(
                    "this exact billing-cycle recovery has an uncertain pending outcome; "
                    "do not retry until Maxio transactions and balances are reconciled"
                )
            readback = self._billing_cycle_recovery_plan(
                subscription_id,
                cycle_count,
                cycle_amount_cents,
                authorized_amount_cents,
                service_period_start,
                service_period_end,
                ticket_number,
                decline_action,
            )
            if readback["existingSuccessfulCollection"]:
                return self._billing_cycle_recovery_result(
                    readback,
                    preview_hash=clean_hash,
                    idempotency_key=clean_key,
                    duplicate=True,
                    provider_result=None,
                )
            return {
                "ok": False,
                "status": "previous_attempt_not_retried",
                "attempted": True,
                "updated": False,
                "duplicate": True,
                "verified": _all_balances_zero(readback["balances"]),
                "retryAllowed": False,
                "subscriptionId": readback["subscriptionId"],
                "ticketNumber": readback["ticketNumber"],
                "authorizedAmountCents": readback["authorizedAmountCents"],
                "memo": readback["memo"],
                "previewHash": clean_hash,
                "idempotencyKey": clean_key,
                "balances": readback["balances"],
                "providerStatusCode": (prior_request.get("evidence") or {}).get("statusCode"),
                "reason": (
                    "The exact provider request was already attempted and was not verified as "
                    "collected; a second collection attempt is blocked."
                ),
            }

        clean_hash = _required_preview_hash(clean_hash, plan["previewHash"])
        result = self.api_request(
            "POST",
            path,
            json_body=body,
            idempotency_key=clean_key,
            _typed_financial_operation="billing_cycle_recovery",
        )
        if plan["declineAction"] == "preserve_open_invoice":
            readback = self._billing_cycle_recovery_attempt_readback(plan)
        else:
            readback = self._billing_cycle_recovery_plan(
                subscription_id,
                cycle_count,
                cycle_amount_cents,
                authorized_amount_cents,
                service_period_start,
                service_period_end,
                ticket_number,
                decline_action,
            )
        if readback["existingSuccessfulCollection"]:
            return self._billing_cycle_recovery_result(
                readback,
                preview_hash=clean_hash,
                idempotency_key=clean_key,
                duplicate=bool(result.get("duplicate")),
                provider_result=result,
            )
        new_transactions = [
            row
            for row in readback["transactions"]
            if row["id"] not in set(plan["transactionIds"])
        ]
        failed_payments = [
            row
            for row in new_transactions
            if row["transactionType"] == "payment"
            and row["amountCents"] == plan["authorizedAmountCents"]
            and not row["success"]
        ]
        if plan["declineAction"] == "preserve_open_invoice" and failed_payments:
            balances = readback["balances"]
            expected_open_invoice = int(plan["authorizedAmountCents"])
            other_balances = {
                key: value
                for key, value in balances.items()
                if key != "openInvoiceBalanceCents"
            }
            if (
                int(balances.get("openInvoiceBalanceCents", -1)) != expected_open_invoice
                or not _all_balances_zero(other_balances)
            ):
                raise MaxioUnavailableError(
                    "the declined collection did not preserve exactly one authorized open "
                    "invoice with all other balances zero; do not retry"
                )
            return {
                "ok": False,
                "status": "declined_open_invoice_preserved",
                "attempted": True,
                "updated": True,
                "duplicate": bool(result.get("duplicate")),
                "verified": True,
                "retryAllowed": False,
                "subscriptionId": plan["subscriptionId"],
                "ticketNumber": plan["ticketNumber"],
                "declineAction": plan["declineAction"],
                "authorizedAmountCents": plan["authorizedAmountCents"],
                "memo": plan["memo"],
                "previewHash": clean_hash,
                "idempotencyKey": clean_key,
                "balances": balances,
                "newTransactions": new_transactions,
                "providerStatusCode": result.get("statusCode"),
                "providerResult": result.get("body"),
                "reason": (
                    "The payment was declined, the exact authorized open invoice was "
                    "preserved, and a second attempt is blocked."
                ),
            }
        if not _all_balances_zero(readback["balances"]):
            raise MaxioUnavailableError(
                "the collection was not verified and account balances changed; "
                "do not retry until Maxio is reconciled"
            )
        return {
            "ok": False,
            "status": "declined" if failed_payments else "provider_rejected",
            "attempted": True,
            "updated": False,
            "duplicate": bool(result.get("duplicate")),
            "verified": bool(failed_payments),
            "retryAllowed": False,
            "subscriptionId": plan["subscriptionId"],
            "ticketNumber": plan["ticketNumber"],
            "declineAction": plan["declineAction"],
            "authorizedAmountCents": plan["authorizedAmountCents"],
            "memo": plan["memo"],
            "previewHash": clean_hash,
            "idempotencyKey": clean_key,
            "balances": readback["balances"],
            "newTransactions": new_transactions,
            "providerStatusCode": result.get("statusCode"),
            "providerResult": result.get("body"),
            "reason": (
                "The payment was declined and no charge accrued; a second attempt is blocked."
                if failed_payments
                else "Maxio did not produce a verified charge and payment; a second attempt is blocked."
            ),
        }

    def api_request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json_body: Any = None,
        idempotency_key: str = "",
        _typed_financial_operation: str = "",
    ) -> dict[str, Any]:
        """Call one bounded Maxio path; mutations are non-delete and journaled."""

        clean_method = str(method or "GET").strip().upper()
        if clean_method not in ALLOWED_METHODS:
            raise MaxioScopeError("method must be GET, POST, PUT, or PATCH; deletion is unavailable")
        clean_path = _safe_api_path(path)
        clean_params = _bounded_mapping(params or {}, "params")
        encoded_body = _encoded_json(json_body)
        mutating = clean_method not in READ_METHODS
        if mutating:
            _validate_mutation_path(
                clean_path,
                json_body=json_body,
                typed_financial_operation=_typed_financial_operation,
            )
        key = str(idempotency_key or "").strip()
        if mutating and not IDEMPOTENCY_KEY.fullmatch(key):
            raise MaxioScopeError("mutations require an idempotency_key of 8-240 safe characters")

        base_url = self._validated_base_url()
        if not self.settings.api_key:
            raise MaxioUnavailableError("Maxio broker credentials are not configured")

        request_hash = _api_request_hash(
            clean_method,
            clean_path,
            clean_params,
            json_body,
        )
        lock = self._operation_lock() if mutating else nullcontext()
        with lock:
            if mutating:
                prior = self._prior_operation(key, clean_method, clean_path, request_hash)
                if prior:
                    if prior["status"] == "pending":
                        raise MaxioScopeError(
                            "idempotency_key has an uncertain pending outcome; read back the target before any retry"
                        )
                    return {
                        "ok": prior["status"] == "accepted",
                        "duplicate": True,
                        "idempotencyKey": key,
                        "prior": prior.get("evidence") or {},
                    }
                self._journal("pending", key, clean_method, clean_path, request_hash, {})

            try:
                response = self.session.request(
                    clean_method,
                    f"{base_url}{clean_path}",
                    params=clean_params,
                    json=json_body if encoded_body is not None else None,
                    auth=(self.settings.api_key, "x"),
                    headers={"Accept": "application/json", "User-Agent": "nova-scoped-maxio/2"},
                    timeout=60,
                )
            except requests.RequestException as exc:
                raise MaxioUnavailableError(
                    "Maxio request failed before a provider response was received"
                ) from exc

            content = bytes(response.content or b"")
            if len(content) > MAX_RESPONSE_BYTES:
                raise MaxioUnavailableError("Maxio response exceeded the bounded response limit")
            status_code = int(response.status_code)
            ok = 200 <= status_code < 300
            body: Any = None
            if content:
                try:
                    body = response.json()
                except ValueError:
                    body = {"message": "Maxio returned a non-JSON response"}
            result = {
                "ok": ok,
                "duplicate": False,
                "method": clean_method,
                "path": clean_path,
                "statusCode": status_code,
                "body": body,
            }
            if mutating:
                evidence = {"statusCode": status_code}
                self._journal(
                    "accepted" if ok else "failed",
                    key,
                    clean_method,
                    clean_path,
                    request_hash,
                    evidence,
                )
                result["idempotencyKey"] = key
                result["readbackRequired"] = ok
            return result

    def _component_allocation_plan(
        self,
        subscription_id: int,
        allocations: list[dict[str, Any]],
    ) -> dict[str, Any]:
        clean_subscription_id = _positive_id(subscription_id, "subscription_id")
        targets = _allocation_targets(allocations)
        payload = self._subscription_component_rows(clean_subscription_id)
        current = _component_quantities(payload)
        changes: list[dict[str, int]] = []
        unchanged: list[dict[str, int]] = []
        for target in targets:
            component_id = target["componentId"]
            if component_id not in current:
                raise MaxioScopeError(
                    f"component_id {component_id} is not present on subscription {clean_subscription_id}"
                )
            row = {
                "componentId": component_id,
                "currentQuantity": current[component_id],
                "desiredQuantity": target["desiredQuantity"],
            }
            (unchanged if row["currentQuantity"] == row["desiredQuantity"] else changes).append(row)
        hash_payload = {
            "subscriptionId": clean_subscription_id,
            "targets": [*changes, *unchanged],
            "componentDeallocationSummary": _component_deallocation_summary(
                payload,
                desired_quantities={
                    row["componentId"]: row["desiredQuantity"]
                    for row in [*changes, *unchanged]
                },
            ),
            "financialControls": ALLOCATION_FINANCIAL_CONTROLS,
        }
        preview_hash = hashlib.sha256(
            json.dumps(hash_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return {
            "subscriptionId": clean_subscription_id,
            "changes": changes,
            "unchanged": unchanged,
            "componentDeallocationSummary": hash_payload[
                "componentDeallocationSummary"
            ],
            "previewHash": preview_hash,
        }

    def _component_payment_recovery_plan(
        self,
        subscription_id: int,
        component_id: int,
        recovery_location_ids: list[int],
        recovery_charge_quantity: int,
        unit_rate_cents: int,
        authorized_amount_cents: int,
        ticket_number: str,
    ) -> dict[str, Any]:
        clean_subscription_id = _positive_id(subscription_id, "subscription_id")
        clean_component_id = _positive_id(component_id, "component_id")
        clean_location_ids = _exact_positive_id_list(
            recovery_location_ids,
            "recovery_location_ids",
            ceiling=500,
        )
        clean_charge_quantity = _bounded_positive_count(
            recovery_charge_quantity,
            "recovery_charge_quantity",
            1_200,
        )
        clean_rate = _positive_cents(unit_rate_cents, "unit_rate_cents")
        clean_amount = _positive_cents(
            authorized_amount_cents,
            "authorized_amount_cents",
        )
        if clean_charge_quantity * clean_rate != clean_amount:
            raise MaxioScopeError(
                "authorized_amount_cents must exactly equal recovery_charge_quantity "
                "multiplied by unit_rate_cents"
            )
        clean_ticket = _ticket_number(ticket_number)

        subscription = _subscription_record(
            self._get(f"/subscriptions/{clean_subscription_id}.json")
        )
        if _required_integer_field(subscription, ("id",), "subscription ID") != clean_subscription_id:
            raise MaxioUnavailableError(
                "Maxio subscription response did not match the recovery subscription"
            )
        payment_collection_method = str(
            subscription.get("payment_collection_method") or ""
        ).strip().casefold()
        if payment_collection_method != "automatic":
            raise MaxioScopeError(
                "component payment recovery requires automatic payment collection"
            )

        metadata = self.subscription_location_metadata(clean_subscription_id)
        location_state = _verified_location_metadata(metadata["values"])
        if location_state["locationIds"] != clean_location_ids:
            raise MaxioScopeError(
                "the recovery locations must exactly equal every location on the target "
                "subscription; create and link an isolated subscription before charging a subset"
            )
        mapped_component_ids = set(location_state["componentMap"].values())
        if mapped_component_ids != {clean_component_id}:
            raise MaxioScopeError(
                "every recovery location must map to the exact recovery component"
            )
        recurring_quantity = len(clean_location_ids)
        current_quantity = self._component_quantity(
            clean_subscription_id,
            clean_component_id,
        )

        component = _wrapped_record(
            self._get(f"/components/{clean_component_id}.json"),
            "component",
            "component",
        )
        if _required_integer_field(component, ("id",), "component ID") != clean_component_id:
            raise MaxioUnavailableError(
                "Maxio component response did not match the recovery component"
            )
        actual_rate = _decimal_dollars_to_cents(
            component.get("unit_price"),
            "component unit price",
        )
        if actual_rate != clean_rate:
            raise MaxioScopeError(
                "unit_rate_cents does not match the exact Maxio component price"
            )
        if component.get("archived_at"):
            raise MaxioScopeError("the recovery component is archived")

        customer = (
            subscription.get("customer")
            if isinstance(subscription.get("customer"), Mapping)
            else {}
        )
        customer_id = _numeric_api_id(
            customer.get("id") or subscription.get("customer_id")
        )
        nested_profile = (
            subscription.get("payment_profile")
            if isinstance(subscription.get("payment_profile"), Mapping)
            else subscription.get("credit_card")
            if isinstance(subscription.get("credit_card"), Mapping)
            else {}
        )
        profile_id = _numeric_api_id(
            nested_profile.get("id") or subscription.get("payment_profile_id")
        )
        if customer_id is None or profile_id is None:
            raise MaxioScopeError(
                "the recovery subscription does not expose one exact customer and payment profile"
            )
        profiles = _wrapped_records(
            self._get(
                "/payment_profiles.json",
                params={"customer_id": customer_id, "page": 1, "per_page": 200},
            ),
            "payment_profile",
        )
        selected_profiles = [
            row for row in profiles if _numeric_api_id(row.get("id")) == profile_id
        ]
        if len(selected_profiles) != 1:
            raise MaxioScopeError(
                "the recovery payment profile did not resolve exactly under its customer"
            )
        payment_profile = selected_profiles[0]
        if payment_profile.get("disabled_at"):
            raise MaxioScopeError("the recovery payment profile is disabled")
        _assert_payment_profile_not_expired(payment_profile)

        balances = self.subscription_account_balances(clean_subscription_id)["balances"]
        transactions = self._component_payment_recovery_transactions(
            clean_subscription_id
        )
        stage_body = {
            "allocations": [
                {
                    "component_id": clean_component_id,
                    "quantity": 0,
                    "previous_quantity": recurring_quantity,
                }
            ],
            **COMPONENT_PAYMENT_RECOVERY_CONTROLS["stage"],
        }
        charge_body = {
            "allocations": [
                {
                    "component_id": clean_component_id,
                    "quantity": clean_charge_quantity,
                    "previous_quantity": 0,
                }
            ],
            **COMPONENT_PAYMENT_RECOVERY_CONTROLS["charge"],
        }
        path = f"/subscriptions/{clean_subscription_id}/allocations.json"
        charge_request_hash = _api_request_hash("POST", path, {}, charge_body)
        prior_charge_attempt = self._prior_request_operation(
            "POST",
            path,
            charge_request_hash,
        )
        if prior_charge_attempt is None:
            if str(subscription.get("state") or "").strip().casefold() != "active":
                raise MaxioScopeError(
                    "a new component payment recovery requires an active subscription"
                )
            if current_quantity != recurring_quantity:
                raise MaxioScopeError(
                    "the component allocation does not equal the exact isolated recovery "
                    "location count"
                )
            if not _all_balances_zero(balances):
                raise MaxioScopeError(
                    "component payment recovery requires zero starting invoice, discount, "
                    "credit, and prepayment balances"
                )
            provider_stage_preview = self._post_preview(
                f"/subscriptions/{clean_subscription_id}/allocations/preview.json",
                stage_body,
            )
            stage_preview_total = _allocation_preview_total_cents(
                provider_stage_preview
            )
            if stage_preview_total != 0:
                raise MaxioScopeError(
                    "the no-credit downgrade preview produced a financial effect"
                )
            provider_charge_preview_body = {
                "allocations": [
                    {
                        "component_id": clean_component_id,
                        "quantity": recurring_quantity + clean_charge_quantity,
                        "previous_quantity": recurring_quantity,
                    }
                ],
                **COMPONENT_PAYMENT_RECOVERY_CONTROLS["charge"],
            }
            provider_charge_preview = self._post_preview(
                f"/subscriptions/{clean_subscription_id}/allocations/preview.json",
                provider_charge_preview_body,
            )
            provider_charge_preview_total = _allocation_preview_total_cents(
                provider_charge_preview
            )
            if provider_charge_preview_total != clean_amount:
                raise MaxioScopeError(
                    "the full-charge allocation preview does not equal the exact authorized amount"
                )
        else:
            if current_quantity not in {0, clean_charge_quantity, recurring_quantity}:
                raise MaxioUnavailableError(
                    "a prior recovery attempt left an unexpected component quantity; "
                    "do not retry"
                )
            provider_stage_preview = None
            provider_charge_preview = None
            provider_charge_preview_total = clean_amount

        financial_controls = {
            "stage": dict(COMPONENT_PAYMENT_RECOVERY_CONTROLS["stage"]),
            "charge": dict(COMPONENT_PAYMENT_RECOVERY_CONTROLS["charge"]),
            "normalize": dict(COMPONENT_PAYMENT_RECOVERY_CONTROLS["normalize"]),
        }
        hash_payload = {
            "operation": "maxio_component_payment_recovery",
            "subscriptionId": clean_subscription_id,
            "componentId": clean_component_id,
            "ticketNumber": clean_ticket,
            "recoveryLocationIds": clean_location_ids,
            "recurringQuantity": recurring_quantity,
            "stagedQuantity": 0,
            "recoveryChargeQuantity": clean_charge_quantity,
            "unitRateCents": clean_rate,
            "authorizedAmountCents": clean_amount,
            "paymentProfileId": profile_id,
            "financialControls": financial_controls,
        }
        return {
            **hash_payload,
            "previewHash": _plan_hash(hash_payload),
            "currentQuantity": current_quantity,
            "balances": balances,
            "transactions": transactions,
            "paymentProfile": {
                "id": profile_id,
                "paymentType": str(payment_profile.get("payment_type") or ""),
                "expirationMonth": payment_profile.get("expiration_month"),
                "expirationYear": payment_profile.get("expiration_year"),
            },
            "providerStageAllocation": stage_body,
            "providerChargeAllocation": charge_body,
            "providerStagePreview": provider_stage_preview,
            "providerChargePreview": provider_charge_preview,
            "providerChargePreviewTotalCents": provider_charge_preview_total,
            "priorChargeAttempt": prior_charge_attempt,
        }

    def _subscription_component_rows(self, subscription_id: int) -> list[Any]:
        clean_subscription_id = _positive_id(subscription_id, "subscription_id")
        rows: list[Any] = []
        first_page_signature: tuple[tuple[int, int], ...] | None = None
        page_count = MAX_COMPONENT_ROWS // COMPONENT_PAGE_SIZE
        for page in range(1, page_count + 1):
            payload = self._get(
                f"/subscriptions/{clean_subscription_id}/components.json",
                params={"page": page, "per_page": COMPONENT_PAGE_SIZE},
            )
            if not isinstance(payload, list):
                raise MaxioUnavailableError(
                    "Maxio component response had an unexpected shape"
                )
            if not payload:
                return rows
            page_signature = tuple(sorted(_component_quantities(payload).items()))
            if page > 1 and page_signature == first_page_signature:
                # Maxio's subscription-components endpoint can ignore page and
                # per_page and return the entire inventory on every request.
                # A repeated second page proves that behavior and must not be
                # appended or mistaken for an inventory exceeding the bound.
                return rows
            if page == 1:
                first_page_signature = page_signature
            rows.extend(payload)
            if len(payload) < COMPONENT_PAGE_SIZE:
                return rows
        raise MaxioUnavailableError(
            f"Maxio component inventory exceeded the {MAX_COMPONENT_ROWS}-row safety limit"
        )

    def _subscription_creation_plan(
        self,
        customer_id: int,
        customer_reference: str,
        payment_profile_id: int,
        product_id: int,
        component_id: int,
        component_quantity: int,
        monthly_rate_cents: int,
        next_billing_at: str,
        ticket_number: str,
    ) -> dict[str, Any]:
        clean_customer_id = _positive_id(customer_id, "customer_id")
        clean_reference = _bounded_text(customer_reference, "customer_reference", 100)
        clean_profile_id = _positive_id(payment_profile_id, "payment_profile_id")
        clean_product_id = _positive_id(product_id, "product_id")
        clean_component_id = _positive_id(component_id, "component_id")
        clean_quantity = _positive_id(component_quantity, "component_quantity")
        if clean_quantity > 500:
            raise MaxioScopeError("component_quantity must be between 1 and 500")
        clean_rate_cents = _positive_cents(monthly_rate_cents, "monthly_rate_cents")
        clean_ticket = _ticket_number(ticket_number)
        clean_next_billing_at, next_billing_datetime = _future_billing_timestamp(
            next_billing_at
        )

        customer = _wrapped_record(
            self._get(f"/customers/{clean_customer_id}.json"),
            "customer",
            "customer",
        )
        if _required_integer_field(customer, ("id",), "customer ID") != clean_customer_id:
            raise MaxioUnavailableError("Maxio customer readback did not match the requested ID")
        if str(customer.get("reference") or "").strip().casefold() != clean_reference.casefold():
            raise MaxioScopeError(
                "customer_reference does not match the exact Maxio customer"
            )

        profiles_payload = self._get(
            "/payment_profiles.json",
            params={"customer_id": clean_customer_id, "page": 1, "per_page": 200},
        )
        profiles = _wrapped_records(profiles_payload, "payment_profile")
        selected_profiles = [
            record
            for record in profiles
            if _numeric_api_id(record.get("id")) == clean_profile_id
        ]
        if len(selected_profiles) != 1:
            raise MaxioScopeError(
                "payment_profile_id did not resolve exactly under the Maxio customer"
            )
        profile = selected_profiles[0]
        if _numeric_api_id(profile.get("customer_id")) not in {None, clean_customer_id}:
            raise MaxioScopeError("payment_profile_id belongs to a different Maxio customer")
        _assert_payment_profile_not_expired(profile)

        product = _wrapped_record(
            self._get(f"/products/{clean_product_id}.json"),
            "product",
            "product",
        )
        if _required_integer_field(product, ("id",), "product ID") != clean_product_id:
            raise MaxioUnavailableError("Maxio product readback did not match the requested ID")
        if (
            _numeric_api_id(product.get("interval")) != 1
            or str(product.get("interval_unit") or "").strip().casefold() != "month"
        ):
            raise MaxioScopeError("subscription creation is limited to one-month products")
        if product.get("archived_at"):
            raise MaxioScopeError("product_id is archived")

        component = _wrapped_record(
            self._get(f"/components/{clean_component_id}.json"),
            "component",
            "component",
        )
        if _required_integer_field(component, ("id",), "component ID") != clean_component_id:
            raise MaxioUnavailableError("Maxio component readback did not match the requested ID")
        component_rate_cents = _decimal_dollars_to_cents(
            component.get("unit_price"),
            "component unit price",
        )
        if component_rate_cents != clean_rate_cents:
            raise MaxioScopeError(
                "monthly_rate_cents does not match the exact Maxio component unit price"
            )
        if component.get("archived_at"):
            raise MaxioScopeError("component_id is archived")

        subscription_reference = _subscription_creation_reference(
            clean_ticket,
            clean_reference,
        )
        subscriptions_payload = self._get(
            "/subscriptions.json",
            params={"customer_id": clean_customer_id, "page": 1, "per_page": 200},
        )
        subscriptions = _wrapped_records(subscriptions_payload, "subscription")
        reference_matches = [
            record
            for record in subscriptions
            if str(record.get("reference") or "").strip().casefold()
            == subscription_reference.casefold()
        ]
        if len(reference_matches) > 1:
            raise MaxioScopeError(
                "multiple Maxio subscriptions use the fixed audit reference; resolve duplicates first"
            )
        existing = reference_matches[0] if reference_matches else None
        provider_payload = {
            "subscription": {
                "customer_id": clean_customer_id,
                "payment_profile_id": clean_profile_id,
                "product_id": clean_product_id,
                "next_billing_at": clean_next_billing_at,
                "reference": subscription_reference,
                "components": [
                    {
                        "component_id": clean_component_id,
                        "allocated_quantity": clean_quantity,
                    }
                ],
            }
        }
        plan = {
            "operation": "maxio_subscription_creation",
            "ticketNumber": clean_ticket,
            "customer": {
                "id": clean_customer_id,
                "reference": str(customer.get("reference") or ""),
                "organization": str(customer.get("organization") or ""),
            },
            "paymentProfile": {
                "id": clean_profile_id,
                "paymentType": str(profile.get("payment_type") or ""),
                "expirationMonth": profile.get("expiration_month"),
                "expirationYear": profile.get("expiration_year"),
            },
            "product": {
                "id": clean_product_id,
                "name": str(product.get("name") or ""),
                "handle": str(product.get("handle") or ""),
                "interval": "1 month",
            },
            "component": {
                "id": clean_component_id,
                "name": str(component.get("name") or ""),
                "quantity": clean_quantity,
                "unitPriceCents": component_rate_cents,
            },
            "nextBillingAt": clean_next_billing_at,
            "nextBillingAtEpoch": int(next_billing_datetime.timestamp()),
            "subscriptionReference": subscription_reference,
            "existingSubscription": existing,
            "providerPayload": provider_payload,
            "futureBillingRequired": True,
            "financialControls": {
                "initialCharge": "none_before_next_billing_at",
                "initialPayment": "none_before_next_billing_at",
                "credit": "none",
                "refund": "none",
                "proration": "none",
            },
        }
        if existing is not None:
            self._verify_created_subscription(plan, existing)
        return plan

    def _verify_created_subscription(
        self,
        plan: Mapping[str, Any],
        readback: Mapping[str, Any],
    ) -> None:
        customer = readback.get("customer") if isinstance(readback.get("customer"), Mapping) else {}
        product = readback.get("product") if isinstance(readback.get("product"), Mapping) else {}
        payment_profile = (
            readback.get("payment_profile")
            if isinstance(readback.get("payment_profile"), Mapping)
            else readback.get("credit_card")
            if isinstance(readback.get("credit_card"), Mapping)
            else {}
        )
        checks = (
            (
                _numeric_api_id(customer.get("id") or readback.get("customer_id")),
                int(plan["customer"]["id"]),
                "customer",
            ),
            (
                _numeric_api_id(product.get("id") or readback.get("product_id")),
                int(plan["product"]["id"]),
                "product",
            ),
            (
                _numeric_api_id(
                    payment_profile.get("id") or readback.get("payment_profile_id")
                ),
                int(plan["paymentProfile"]["id"]),
                "payment profile",
            ),
        )
        for actual, expected, label in checks:
            if actual != expected:
                raise MaxioUnavailableError(
                    f"Maxio subscription {label} readback did not match; do not retry"
                )
        if (
            str(readback.get("reference") or "").strip().casefold()
            != str(plan["subscriptionReference"]).casefold()
        ):
            raise MaxioUnavailableError(
                "Maxio subscription reference readback did not match; do not retry"
            )
        readback_next = _parse_api_datetime(
            readback.get("next_assessment_at") or readback.get("next_billing_at"),
            "subscription next billing timestamp",
        )
        expected_next = datetime.fromtimestamp(
            int(plan["nextBillingAtEpoch"]),
            tz=timezone.utc,
        )
        if abs((readback_next - expected_next).total_seconds()) > 60:
            raise MaxioUnavailableError(
                "Maxio subscription next-billing readback did not match; do not retry"
            )

    def _manual_service_credit_plan(
        self,
        subscription_id: int,
        amount_cents: int,
        ticket_number: str,
    ) -> dict[str, Any]:
        clean_subscription_id = _positive_id(subscription_id, "subscription_id")
        clean_amount = _positive_cents(amount_cents, "amount_cents")
        clean_ticket = _ticket_number(ticket_number)
        balances = self.subscription_account_balances(clean_subscription_id)["balances"]
        current_balance = int(balances["serviceCreditBalanceCents"])
        memo = f"Ticket {clean_ticket}: manually validated service credit"
        hash_payload = {
            "subscriptionId": clean_subscription_id,
            "ticketNumber": clean_ticket,
            "amountCents": clean_amount,
            "memo": memo,
            "currentServiceCreditBalanceCents": current_balance,
            "allocationChangeIncluded": False,
            "invoiceApplicationIncluded": False,
        }
        return {
            **hash_payload,
            "expectedServiceCreditBalanceCents": current_balance + clean_amount,
            "previewHash": _plan_hash(hash_payload),
        }

    def _nova_integrated_promo_credit_plan(
        self,
        subscription_id: int,
        location_id: int,
        merchant_provider: str,
        monthly_rate_cents: int,
        ticket_number: str,
    ) -> dict[str, Any]:
        clean_subscription_id = _positive_id(subscription_id, "subscription_id")
        clean_location_id = _positive_id(location_id, "location_id")
        clean_provider = _merchant_provider(merchant_provider)
        clean_rate = _positive_cents(monthly_rate_cents, "monthly_rate_cents")
        clean_ticket = _ticket_number(ticket_number)
        credit_amount = clean_rate * 3
        memo = f"Nova Integrated Promo | Ticket {clean_ticket} | Location {clean_location_id}"

        subscription = _subscription_record(
            self._get(f"/subscriptions/{clean_subscription_id}.json")
        )
        if _numeric_api_id(subscription.get("id")) != clean_subscription_id:
            raise MaxioUnavailableError(
                "Maxio subscription response did not match the requested subscription"
            )
        state = str(subscription.get("state") or "").strip().casefold()
        if state not in {"active", "trial", "trialing"}:
            raise MaxioScopeError(
                "Nova Integrated Promo requires an active or trialing isolated subscription"
            )
        product = _subscription_product_summary(subscription)
        product_provider = _product_merchant_provider(product["name"], product["handle"])
        if product_provider != clean_provider:
            raise MaxioScopeError(
                "subscription product does not match the selected merchant_provider; "
                "change and verify the Nova Integrated product first"
            )

        metadata = self.subscription_location_metadata(clean_subscription_id)
        location_state = _verified_location_metadata(metadata["values"])
        if location_state["locationIds"] != [clean_location_id]:
            raise MaxioScopeError(
                "Nova Integrated Promo credit requires one isolated subscription containing "
                "only the exact location"
            )
        component_ids = set(location_state["componentMap"].values())
        if len(component_ids) != 1:
            raise MaxioScopeError(
                "Nova Integrated Promo location metadata must map to exactly one component"
            )
        component_id = next(iter(component_ids))
        component_payload = self._get(
            f"/subscriptions/{clean_subscription_id}/components.json",
            params={"page": 1, "per_page": 200},
        )
        quantities = _component_quantities(component_payload)
        if quantities.get(component_id) != 1:
            raise MaxioScopeError(
                "Nova Integrated Promo requires an exact one-location component allocation"
            )
        component = _wrapped_record(
            self._get(f"/components/{component_id}.json"),
            "component",
            "component",
        )
        component_rate = _component_unit_rate_cents(component)
        if component_rate != clean_rate:
            raise MaxioScopeError(
                "monthly_rate_cents must match the exact isolated location component rate"
            )

        balances = self.subscription_account_balances(clean_subscription_id)["balances"]
        current_balance = int(balances["serviceCreditBalanceCents"])
        history_payload = self._get(
            f"/subscriptions/{clean_subscription_id}/service_credits/list.json",
            params={"page": 1, "per_page": 200},
        )
        history = _service_credit_history(history_payload)
        matching = [
            row
            for row in history
            if row["memo"] == memo and row["amountCents"] == credit_amount
        ]
        if len(matching) > 1:
            raise MaxioScopeError(
                "multiple matching Nova Integrated Promo credits exist; reconcile before continuing"
            )
        existing = matching[0] if matching else None
        if current_balance > 0 and existing is None:
            raise MaxioScopeError(
                "the isolated subscription already has a different service-credit balance; "
                "do not mix it with the Nova Integrated Promo"
            )
        expected_balance = current_balance if existing else current_balance + credit_amount
        hash_payload = {
            "operation": "maxio_nova_integrated_promo_credit",
            "subscriptionId": clean_subscription_id,
            "locationId": clean_location_id,
            "merchantProvider": clean_provider,
            "product": product,
            "componentId": component_id,
            "componentQuantity": quantities[component_id],
            "monthlyRateCents": clean_rate,
            "freeMonths": 3,
            "creditAmountCents": credit_amount,
            "ticketNumber": clean_ticket,
            "memo": memo,
            "currentServiceCreditBalanceCents": current_balance,
            "existingPromoCredit": existing,
            "metadataVerified": True,
            "componentAllocationVerified": True,
            "accountFlatRateMutationIncluded": False,
        }
        return {
            **hash_payload,
            "expectedServiceCreditBalanceCents": expected_balance,
            "previewHash": _plan_hash(hash_payload),
        }

    def _subscription_coupon_plan(
        self,
        subscription_id: int,
        coupon_code: str,
        ticket_number: str,
    ) -> dict[str, Any]:
        clean_subscription_id = _positive_id(subscription_id, "subscription_id")
        clean_code = _coupon_code(coupon_code)
        clean_ticket = _ticket_number(ticket_number)
        subscription = _subscription_record(
            self._get(f"/subscriptions/{clean_subscription_id}.json")
        )
        returned_id = _numeric_api_id(subscription.get("id"))
        if returned_id != clean_subscription_id:
            raise MaxioUnavailableError(
                "Maxio subscription response did not match the requested subscription"
            )
        state = str(subscription.get("state") or "").strip().casefold()
        if state not in {"active", "past_due"}:
            raise MaxioScopeError(
                "subscription coupon requires an active or past-due subscription"
            )
        product_family_id = _subscription_product_family_id(subscription)
        coupon = _wrapped_record(
            self._get(
                "/coupons/find.json",
                params={"code": clean_code, "product_family_id": product_family_id},
            ),
            "coupon",
            "coupon",
        )
        returned_code = _coupon_code(coupon.get("code"))
        if returned_code.casefold() != clean_code.casefold():
            raise MaxioUnavailableError(
                "Maxio coupon response did not match the requested code"
            )
        returned_family_id = _numeric_api_id(coupon.get("product_family_id"))
        if returned_family_id != product_family_id:
            raise MaxioScopeError(
                "coupon does not belong to the subscription product family"
            )
        if str(coupon.get("archived_at") or "").strip():
            raise MaxioScopeError("coupon is archived")
        today = datetime.now(timezone.utc).date()
        start_date = _optional_api_date(coupon.get("start_date"), "coupon start date")
        end_date = _optional_api_date(coupon.get("end_date"), "coupon end date")
        if start_date and start_date > today:
            raise MaxioScopeError("coupon is not active yet")
        if end_date and end_date < today:
            raise MaxioScopeError("coupon is expired")
        amount_cents = _numeric_api_nonnegative(coupon.get("amount_in_cents"))
        try:
            percentage = Decimal(str(coupon.get("percentage") or "0"))
        except Exception as exc:
            raise MaxioUnavailableError("Maxio returned an invalid coupon percentage") from exc
        if amount_cents <= 0 and percentage <= 0:
            raise MaxioScopeError("coupon must have a positive amount or percentage")
        current_codes = _subscription_coupon_codes(subscription)
        existing_coupon = next(
            (code for code in current_codes if code.casefold() == clean_code.casefold()),
            None,
        )
        balances = self.subscription_account_balances(clean_subscription_id)["balances"]
        coupon_summary = {
            "id": _positive_id(coupon.get("id"), "coupon id"),
            "code": returned_code,
            "name": str(coupon.get("name") or "").strip(),
            "productFamilyId": product_family_id,
            "amountCents": amount_cents,
            "percentage": format(percentage.normalize(), "f") if percentage else "0",
            "durationPeriodCount": _numeric_api_nonnegative(
                coupon.get("duration_period_count")
            ),
            "durationInterval": _numeric_api_nonnegative(coupon.get("duration_interval")),
            "durationIntervalUnit": str(coupon.get("duration_interval_unit") or "").strip(),
            "stackable": bool(coupon.get("stackable")),
            "startDate": start_date.isoformat() if start_date else None,
            "endDate": end_date.isoformat() if end_date else None,
        }
        hash_payload = {
            "operation": "maxio_subscription_coupon",
            "subscriptionId": clean_subscription_id,
            "subscriptionState": state,
            "ticketNumber": clean_ticket,
            "coupon": coupon_summary,
            "currentCouponCodes": current_codes,
            "balances": balances,
            "existingCoupon": existing_coupon,
            "existingInvoiceAdjustmentIncluded": False,
            "refundIncluded": False,
            "serviceCreditIncluded": False,
        }
        return {**hash_payload, "previewHash": _plan_hash(hash_payload)}

    def _subscription_product_change_plan(
        self,
        subscription_id: int,
        product_id: int,
        ticket_number: str,
    ) -> dict[str, Any]:
        clean_subscription_id = _positive_id(subscription_id, "subscription_id")
        clean_product_id = _positive_id(product_id, "product_id")
        clean_ticket = _ticket_number(ticket_number)
        subscription = _subscription_record(
            self._get(f"/subscriptions/{clean_subscription_id}.json")
        )
        if _numeric_api_id(subscription.get("id")) != clean_subscription_id:
            raise MaxioUnavailableError(
                "Maxio subscription response did not match the requested subscription"
            )
        state = str(subscription.get("state") or "").strip().casefold()
        if state not in {"active", "past_due"}:
            raise MaxioScopeError(
                "subscription product change requires an active or past-due subscription"
            )
        current_product = _subscription_product_summary(subscription)
        current_family_id = _subscription_product_family_id(subscription)
        target = _wrapped_record(
            self._get(f"/products/{clean_product_id}.json"),
            "product",
            "product",
        )
        if _numeric_api_id(target.get("id")) != clean_product_id:
            raise MaxioUnavailableError(
                "Maxio product response did not match the requested product"
            )
        target_family_id = _product_family_id(target)
        if target_family_id != current_family_id:
            raise MaxioScopeError(
                "target product must belong to the subscription product family"
            )
        if str(target.get("archived_at") or "").strip():
            raise MaxioScopeError("target product is archived")
        if (
            _numeric_api_id(target.get("interval")) != 1
            or str(target.get("interval_unit") or "").strip().casefold() != "month"
        ):
            raise MaxioScopeError("target product must bill once per month")
        target_name = str(target.get("name") or "").strip()
        if "nova integrated" not in re.sub(r"[^a-z0-9]+", " ", target_name.casefold()):
            raise MaxioScopeError("target product must be a Nova Integrated product")
        if _product_base_price_cents(target) != 0:
            raise MaxioScopeError(
                "target Nova Integrated product must have a zero-dollar base price"
            )
        target_product = {
            "id": clean_product_id,
            "name": target_name,
            "handle": str(target.get("handle") or "").strip(),
            "productFamilyId": target_family_id,
            "interval": 1,
            "intervalUnit": "month",
            "basePriceCents": 0,
        }
        allocations = _nonzero_component_allocations(
            self._subscription_component_rows(clean_subscription_id)
        )
        balances = self.subscription_account_balances(clean_subscription_id)["balances"]
        hash_payload = {
            "operation": "maxio_subscription_product_change",
            "subscriptionId": clean_subscription_id,
            "subscriptionState": state,
            "ticketNumber": clean_ticket,
            "currentProduct": current_product,
            "targetProduct": target_product,
            "currentCouponCodes": _subscription_coupon_codes(subscription),
            "nonzeroComponentAllocations": allocations,
            "balances": balances,
            "billingPeriod": _subscription_period_summary(subscription),
            "duplicate": current_product["id"] == clean_product_id,
            "automaticChargeAuthorized": False,
            "automaticCreditAuthorized": False,
            "prorationAuthorized": False,
            "couponChangeAuthorized": False,
            "componentChangeAuthorized": False,
            "invoiceAdjustmentAuthorized": False,
        }
        return {**hash_payload, "previewHash": _plan_hash(hash_payload)}

    def _invoice_refund_plan(
        self,
        invoice_uid: str,
        payment_id: int,
        refund_amount_cents: int,
        ticket_number: str,
    ) -> dict[str, Any]:
        clean_uid = str(invoice_uid or "").strip()
        if not INVOICE_UID.fullmatch(clean_uid):
            raise MaxioScopeError("invoice_uid must be one exact Maxio invoice UID")
        clean_payment_id = _positive_id(payment_id, "payment_id")
        clean_amount = _positive_cents(refund_amount_cents, "refund_amount_cents")
        clean_ticket = _ticket_number(ticket_number)
        invoice = _wrapped_record(
            self._get(f"/invoices/{clean_uid}.json"),
            "invoice",
            "invoice",
        )
        returned_uid = str(invoice.get("uid") or "").strip()
        if returned_uid != clean_uid:
            raise MaxioUnavailableError("Maxio invoice response did not match the requested UID")
        invoice_status = str(invoice.get("status") or "").strip().casefold()
        if invoice_status not in {"paid", "partial"}:
            raise MaxioScopeError("invoice refund requires a paid or partially paid invoice")
        subscription_id = _required_integer_field(
            invoice,
            ("subscription_id", "group_primary_subscription_id"),
            "invoice subscription ID",
        )
        invoice_number = str(invoice.get("number") or "").strip()
        if not invoice_number:
            raise MaxioUnavailableError("Maxio invoice response omitted the invoice number")
        currency = str(invoice.get("currency") or "").strip().upper()
        if currency and currency != "USD":
            raise MaxioScopeError("invoice refund is limited to USD invoices")

        payments = [
            dict(row)
            for row in (invoice.get("payments") or [])
            if isinstance(row, Mapping)
        ]
        matching_payments = [
            row
            for row in payments
            if _numeric_api_id(row.get("transaction_id") or row.get("payment_id"))
            == clean_payment_id
        ]
        if len(matching_payments) != 1:
            raise MaxioScopeError(
                "payment_id must resolve to exactly one payment on the exact invoice"
            )
        payment = matching_payments[0]
        payment_amount = _decimal_dollars_to_cents(
            payment.get("applied_amount") or payment.get("original_amount"),
            "invoice payment applied amount",
        )

        refunds = [
            dict(row)
            for row in (invoice.get("refunds") or [])
            if isinstance(row, Mapping)
        ]
        payment_refunds = [
            row
            for row in refunds
            if _numeric_api_id(row.get("payment_id")) == clean_payment_id
        ]
        previous_refunded = sum(
            _nonnegative_decimal_dollars_to_cents(
                row.get("applied_amount") or row.get("amount") or "0",
                "invoice refund applied amount",
            )
            for row in payment_refunds
        )
        remaining_refundable = payment_amount - previous_refunded
        if remaining_refundable < 0:
            raise MaxioUnavailableError(
                "Maxio invoice refunds exceed the selected payment amount"
            )
        memo = f"Ticket {clean_ticket}: approved invoice refund"
        existing_matches = [
            row
            for row in payment_refunds
            if str(row.get("memo") or "").strip() == memo
            and _nonnegative_decimal_dollars_to_cents(
                row.get("applied_amount") or row.get("amount") or "0",
                "invoice refund applied amount",
            )
            == clean_amount
        ]
        if len(existing_matches) > 1:
            raise MaxioScopeError(
                "multiple matching invoice refunds exist; reconcile Maxio before continuing"
            )
        existing_refund = existing_matches[0] if existing_matches else None
        if not existing_refund and clean_amount > remaining_refundable:
            raise MaxioScopeError(
                "refund_amount_cents exceeds the selected payment's remaining refundable amount"
            )
        invoice_refund_amount = _nonnegative_decimal_dollars_to_cents(
            invoice.get("refund_amount") or "0",
            "invoice refund amount",
        )
        refund_controls = {
            "external": False,
            "applyCredit": False,
            "voidInvoice": False,
            "ticketBoundMemo": True,
            "retryAfterAttempt": False,
            "customerEmail": False,
            "subscriptionCancellation": False,
        }
        hash_payload = {
            "operation": "maxio_invoice_refund",
            "invoiceUid": clean_uid,
            "invoiceNumber": invoice_number,
            "subscriptionId": subscription_id,
            "ticketNumber": clean_ticket,
            "paymentId": clean_payment_id,
            "paymentAppliedAmountCents": payment_amount,
            "previousRefundedForPaymentCents": previous_refunded,
            "remainingRefundableForPaymentCents": remaining_refundable,
            "refundAmountCents": clean_amount,
            "memo": memo,
            "invoiceStatus": invoice_status,
            "invoiceRefundAmountCents": invoice_refund_amount,
            "refundControls": refund_controls,
            "existingRefund": existing_refund,
        }
        return {
            **hash_payload,
            "previewHash": _plan_hash(hash_payload),
            "providerRefund": {
                "amount": _currency_amount(clean_amount),
                "memo": memo,
                "payment_id": clean_payment_id,
                "external": False,
                "apply_credit": False,
                "void_invoice": False,
            },
        }

    def _invoice_refund_result(
        self,
        plan: Mapping[str, Any],
        *,
        preview_hash: str,
        idempotency_key: str,
        duplicate: bool,
        provider_result: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        refund = plan.get("existingRefund")
        if not isinstance(refund, Mapping):
            raise MaxioUnavailableError("Maxio did not return the exact invoice refund")
        invoice_refund_amount = int(plan["invoiceRefundAmountCents"])
        return {
            "ok": True,
            "status": "refunded",
            "attempted": not duplicate,
            "updated": not duplicate,
            "duplicate": duplicate,
            "verified": True,
            "retryAllowed": False,
            "invoiceUid": plan["invoiceUid"],
            "invoiceNumber": plan["invoiceNumber"],
            "subscriptionId": plan["subscriptionId"],
            "ticketNumber": plan["ticketNumber"],
            "paymentId": plan["paymentId"],
            "refundAmountCents": plan["refundAmountCents"],
            "memo": plan["memo"],
            "previewHash": preview_hash,
            "idempotencyKey": idempotency_key,
            "refund": dict(refund),
            "invoiceRefundAmountCents": invoice_refund_amount,
            "subscriptionCancellationIncluded": False,
            "customerEmailIncluded": False,
            "providerStatusCode": provider_result.get("statusCode") if provider_result else None,
        }


    def _invoice_void_plan(
        self,
        invoice_uid: str,
        ticket_number: str,
        reason: str,
    ) -> dict[str, Any]:
        clean_uid = str(invoice_uid or "").strip()
        if not INVOICE_UID.fullmatch(clean_uid):
            raise MaxioScopeError("invoice_uid must be one exact Maxio invoice UID")
        clean_ticket = _ticket_number(ticket_number)
        clean_reason = _bounded_text(reason, "reason", 350)
        if not clean_reason:
            raise MaxioScopeError("reason must not be empty")
        invoice = _wrapped_record(
            self._get(f"/invoices/{clean_uid}.json"),
            "invoice",
            "invoice",
        )
        returned_uid = str(invoice.get("uid") or "").strip()
        if returned_uid != clean_uid:
            raise MaxioUnavailableError("Maxio invoice response did not match the requested UID")
        invoice_status = str(invoice.get("status") or "").strip().casefold()
        if invoice_status not in {"open", "canceled", "cancelled", "voided"}:
            raise MaxioScopeError("invoice void requires an open, canceled, or voided invoice")
        subscription_id = _required_integer_field(
            invoice,
            ("subscription_id", "group_primary_subscription_id"),
            "invoice subscription ID",
        )
        invoice_number = str(invoice.get("number") or "").strip()
        if not invoice_number:
            raise MaxioUnavailableError("Maxio invoice response omitted the invoice number")
        currency = str(invoice.get("currency") or "").strip().upper()
        if currency and currency != "USD":
            raise MaxioScopeError("invoice void is limited to USD invoices")
        due_cents = _nonnegative_decimal_dollars_to_cents(
            invoice.get("due_amount") or "0",
            "invoice due amount",
        )
        memo = f"Ticket {clean_ticket}: approved invoice void"
        hash_payload = {
            "operation": "maxio_invoice_void",
            "invoiceUid": clean_uid,
            "invoiceNumber": invoice_number,
            "subscriptionId": subscription_id,
            "ticketNumber": clean_ticket,
            "invoiceStatus": invoice_status,
            "dueAmountCents": due_cents,
            "reason": clean_reason,
            "memo": memo,
        }
        return {
            **hash_payload,
            "previewHash": _plan_hash(hash_payload),
            "providerVoid": {
                "reason": clean_reason,
            },
            "applyRequired": invoice_status == "open",
        }

    def _invoice_void_result(
        self,
        plan: Mapping[str, Any],
        *,
        preview_hash: str,
        idempotency_key: str,
        duplicate: bool,
        provider_result: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        return {
            "ok": True,
            "status": "voided",
            "attempted": not duplicate,
            "updated": not duplicate,
            "duplicate": duplicate,
            "verified": True,
            "retryAllowed": False,
            "invoiceUid": plan["invoiceUid"],
            "invoiceNumber": plan["invoiceNumber"],
            "subscriptionId": plan["subscriptionId"],
            "ticketNumber": plan["ticketNumber"],
            "reason": plan["reason"],
            "memo": plan["memo"],
            "previewHash": preview_hash,
            "idempotencyKey": idempotency_key,
            "invoiceStatus": plan["invoiceStatus"],
            "dueAmountCents": plan["dueAmountCents"],
            "subscriptionCancellationIncluded": False,
            "customerEmailIncluded": False,
            "providerStatusCode": provider_result.get("statusCode") if provider_result else None,
        }

    def _billing_cycle_recovery_plan(
        self,
        subscription_id: int,
        cycle_count: int,
        cycle_amount_cents: int,
        authorized_amount_cents: int,
        service_period_start: str,
        service_period_end: str,
        ticket_number: str,
        decline_action: str = "no_accrual",
    ) -> dict[str, Any]:
        clean_subscription_id = _positive_id(subscription_id, "subscription_id")
        clean_cycle_count = _bounded_positive_count(cycle_count, "cycle_count", 12)
        clean_cycle_amount = _positive_cents(cycle_amount_cents, "cycle_amount_cents")
        clean_authorized_amount = _positive_cents(
            authorized_amount_cents,
            "authorized_amount_cents",
        )
        if clean_cycle_count * clean_cycle_amount != clean_authorized_amount:
            raise MaxioScopeError(
                "authorized_amount_cents must exactly equal cycle_count multiplied by "
                "cycle_amount_cents"
            )
        clean_start = _required_api_date(service_period_start, "service_period_start")
        clean_end = _required_api_date(service_period_end, "service_period_end")
        start_date = date.fromisoformat(clean_start)
        end_date = date.fromisoformat(clean_end)
        span_days = (end_date - start_date).days
        if span_days <= 0:
            raise MaxioScopeError("service_period_end must be after service_period_start")
        if not 20 * clean_cycle_count <= span_days <= 40 * clean_cycle_count:
            raise MaxioScopeError(
                "service period length must match the explicitly authorized monthly cycle count"
            )
        clean_ticket = _ticket_number(ticket_number)
        clean_decline_action = str(decline_action or "").strip().casefold()
        if clean_decline_action not in {"no_accrual", "preserve_open_invoice"}:
            raise MaxioScopeError(
                "decline_action must be no_accrual or preserve_open_invoice"
            )

        subscription = _subscription_record(
            self._get(f"/subscriptions/{clean_subscription_id}.json")
        )
        if _required_integer_field(subscription, ("id",), "subscription ID") != clean_subscription_id:
            raise MaxioUnavailableError("Maxio subscription response did not match the requested ID")
        if str(subscription.get("state") or "").strip().casefold() != "active":
            raise MaxioScopeError("billing-cycle recovery requires an active subscription")
        if (
            str(subscription.get("payment_collection_method") or "").strip().casefold()
            != "automatic"
        ):
            raise MaxioScopeError("billing-cycle recovery requires automatic payment collection")
        subscription_balance = _required_integer_field(
            subscription,
            ("balance_in_cents", "current_balance_in_cents"),
            "subscription balance",
        )
        if subscription_balance != 0:
            raise MaxioScopeError("billing-cycle recovery requires a zero subscription balance")
        current_period_start = _required_api_date(
            subscription.get("current_period_started_at"),
            "subscription current period start",
        )
        next_assessment_at = str(
            subscription.get("next_assessment_at")
            or subscription.get("next_billing_at")
            or ""
        ).strip()
        if not next_assessment_at:
            raise MaxioUnavailableError("Maxio subscription omitted the next assessment timestamp")
        current_period_end = _required_api_date(
            subscription.get("current_period_ends_at") or next_assessment_at,
            "subscription current period end",
        )
        current_period_start_date = date.fromisoformat(current_period_start)
        current_period_end_date = date.fromisoformat(current_period_end)
        overlap_days = max((end_date - current_period_start_date).days, 0)
        if overlap_days:
            if end_date > current_period_end_date:
                raise MaxioScopeError(
                    "billing-cycle recovery may overlap only an unbilled replacement-subscription "
                    "stub ending at the current period end"
                )
            if overlap_days > 14:
                raise MaxioScopeError(
                    "billing-cycle recovery current-period overlap is limited to a replacement "
                    "subscription stub of 14 days or fewer"
                )
        if (date.fromisoformat(current_period_start) - start_date).days > 400:
            raise MaxioScopeError("billing-cycle recovery is limited to the prior 400 days")
        current_billing_amount = _required_integer_field(
            subscription,
            ("current_billing_amount_in_cents",),
            "current billing amount",
        )
        if current_billing_amount != clean_cycle_amount:
            raise MaxioScopeError(
                "cycle_amount_cents must exactly match the current subscription billing amount"
            )

        customer = (
            subscription.get("customer")
            if isinstance(subscription.get("customer"), Mapping)
            else {}
        )
        customer_id = _numeric_api_id(customer.get("id") or subscription.get("customer_id"))
        nested_profile = (
            subscription.get("payment_profile")
            if isinstance(subscription.get("payment_profile"), Mapping)
            else subscription.get("credit_card")
            if isinstance(subscription.get("credit_card"), Mapping)
            else {}
        )
        profile_id = _numeric_api_id(
            nested_profile.get("id") or subscription.get("payment_profile_id")
        )
        if customer_id is None or profile_id is None:
            raise MaxioScopeError(
                "subscription does not expose one exact customer and payment profile"
            )
        profiles = _wrapped_records(
            self._get(
                "/payment_profiles.json",
                params={"customer_id": customer_id, "page": 1, "per_page": 200},
            ),
            "payment_profile",
        )
        selected_profiles = [
            row for row in profiles if _numeric_api_id(row.get("id")) == profile_id
        ]
        if len(selected_profiles) != 1:
            raise MaxioScopeError(
                "the subscription payment profile did not resolve exactly under its customer"
            )
        payment_profile = selected_profiles[0]
        if payment_profile.get("disabled_at"):
            raise MaxioScopeError("the subscription payment profile is disabled")
        _assert_payment_profile_not_expired(payment_profile)

        balances = self.subscription_account_balances(clean_subscription_id)["balances"]
        if not _all_balances_zero(balances):
            raise MaxioScopeError(
                "billing-cycle recovery requires zero invoice, discount, credit, and "
                "prepayment balances"
            )

        memo = (
            f"Ticket {clean_ticket}: missed billing cycle recovery "
            f"{clean_cycle_count} x {_currency_amount(clean_cycle_amount)} "
            f"for {clean_start} through {clean_end}"
        )
        provider_charge = {
            "amount_in_cents": clean_authorized_amount,
            "memo": memo,
            "delay_capture": False,
            "accrue_on_failure": clean_decline_action == "preserve_open_invoice",
            "use_negative_balance": False,
            "taxable": False,
            "payment_collection_method": "automatic",
            "period_range_start": clean_start,
            "period_range_end": clean_end,
        }
        transaction_until = (datetime.now(timezone.utc).date() + timedelta(days=1)).isoformat()
        transactions = _transaction_records(
            self._get(
                f"/subscriptions/{clean_subscription_id}/transactions.json",
                params={
                    "page": 1,
                    "per_page": 200,
                    "since_date": clean_start,
                    "until_date": transaction_until,
                    "direction": "desc",
                },
            )
        )
        matching_charges = [
            row
            for row in transactions
            if row["transactionType"] == "charge"
            and row["amountCents"] == clean_authorized_amount
            and row["memo"] == memo
            and row["success"]
        ]
        if len(matching_charges) > 1:
            raise MaxioScopeError(
                "multiple matching billing-cycle recovery charges exist; reconcile Maxio "
                "before continuing"
            )
        existing_collection = (
            _successful_collection_evidence(matching_charges[0], transactions)
            if matching_charges
            else None
        )
        if matching_charges and existing_collection is None:
            raise MaxioUnavailableError(
                "a matching billing-cycle recovery charge exists but its linked successful "
                "payment was not verified; do not retry"
            )
        overlap_transaction_ids: list[int] = []
        if overlap_days:
            existing_collection_ids = set()
            if isinstance(existing_collection, Mapping):
                existing_collection_ids = {
                    int(existing_collection["charge"]["id"]),
                    int(existing_collection["payment"]["id"]),
                }
            for row in transactions:
                if (
                    int(row["id"]) in existing_collection_ids
                    or not row["success"]
                    or row["amountCents"] <= 0
                    or row["transactionType"] not in {"charge", "payment"}
                ):
                    continue
                try:
                    transaction_date = date.fromisoformat(
                        _required_api_date(row["createdAt"], "transaction created_at")
                    )
                except MaxioScopeError as exc:
                    raise MaxioUnavailableError(
                        "Maxio transaction history cannot prove the replacement stub is unbilled"
                    ) from exc
                if current_period_start_date <= transaction_date < end_date:
                    overlap_transaction_ids.append(int(row["id"]))
            if overlap_transaction_ids:
                raise MaxioScopeError(
                    "billing-cycle recovery replacement-subscription stub already has a "
                    "successful charge or payment"
                )
        collection_controls = {
            "delayCapture": False,
            "accrueOnFailure": clean_decline_action == "preserve_open_invoice",
            "useNegativeBalance": False,
            "taxable": False,
            "paymentCollectionMethod": "automatic",
            "allocationChange": False,
            "retryAfterAttempt": False,
            "replacementStubOverlapDays": overlap_days,
            "replacementStubMustBeUnbilled": True,
        }
        hash_payload = {
            "operation": "maxio_billing_cycle_recovery",
            "subscriptionId": clean_subscription_id,
            "ticketNumber": clean_ticket,
            "declineAction": clean_decline_action,
            "cycleCount": clean_cycle_count,
            "cycleAmountCents": clean_cycle_amount,
            "authorizedAmountCents": clean_authorized_amount,
            "servicePeriodStart": clean_start,
            "servicePeriodEnd": clean_end,
            "currentPeriodStart": current_period_start,
            "currentPeriodEnd": current_period_end,
            "currentPeriodOverlapDays": overlap_days,
            "memo": memo,
            "currentBillingAmountCents": current_billing_amount,
            "nextAssessmentAt": next_assessment_at,
            "subscriptionUpdatedAt": str(subscription.get("updated_at") or ""),
            "paymentProfileId": profile_id,
            "balances": balances,
            "collectionControls": collection_controls,
            "transactionIds": [row["id"] for row in transactions],
            "overlapTransactionIds": overlap_transaction_ids,
            "existingSuccessfulCollection": existing_collection,
        }
        return {
            **hash_payload,
            "previewHash": _plan_hash(hash_payload),
            "providerCharge": provider_charge,
            "paymentProfile": {
                "id": profile_id,
                "paymentType": str(payment_profile.get("payment_type") or ""),
                "expirationMonth": payment_profile.get("expiration_month"),
                "expirationYear": payment_profile.get("expiration_year"),
            },
            "transactions": transactions,
        }

    def _billing_cycle_recovery_attempt_readback(
        self,
        plan: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Read a recovery attempt without requiring the post-decline balance to be zero."""

        transaction_until = (datetime.now(timezone.utc).date() + timedelta(days=1)).isoformat()
        transactions = _transaction_records(
            self._get(
                f"/subscriptions/{int(plan['subscriptionId'])}/transactions.json",
                params={
                    "page": 1,
                    "per_page": 200,
                    "since_date": str(plan["servicePeriodStart"]),
                    "until_date": transaction_until,
                    "direction": "desc",
                },
            )
        )
        matching_charges = [
            row
            for row in transactions
            if row["transactionType"] == "charge"
            and row["amountCents"] == int(plan["authorizedAmountCents"])
            and row["memo"] == str(plan["memo"])
            and row["success"]
        ]
        if len(matching_charges) > 1:
            raise MaxioScopeError(
                "multiple matching billing-cycle recovery charges exist; reconcile Maxio "
                "before continuing"
            )
        existing_collection = (
            _successful_collection_evidence(matching_charges[0], transactions)
            if matching_charges
            else None
        )
        balances = self.subscription_account_balances(int(plan["subscriptionId"]))["balances"]
        return {
            **dict(plan),
            "transactions": transactions,
            "transactionIds": [row["id"] for row in transactions],
            "balances": balances,
            "existingSuccessfulCollection": existing_collection,
        }

    def _billing_cycle_recovery_result(
        self,
        plan: Mapping[str, Any],
        *,
        preview_hash: str,
        idempotency_key: str,
        duplicate: bool,
        provider_result: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        evidence = plan.get("existingSuccessfulCollection")
        if not isinstance(evidence, Mapping):
            raise MaxioUnavailableError(
                "Maxio did not return a linked successful charge and payment"
            )
        if not _all_balances_zero(plan["balances"]):
            raise MaxioUnavailableError(
                "the collection transactions succeeded but zero account balances were not verified"
            )
        return {
            "ok": True,
            "status": "collected",
            "attempted": not duplicate,
            "updated": not duplicate,
            "duplicate": duplicate,
            "verified": True,
            "retryAllowed": False,
            "subscriptionId": plan["subscriptionId"],
            "ticketNumber": plan["ticketNumber"],
            "declineAction": plan["declineAction"],
            "cycleCount": plan["cycleCount"],
            "cycleAmountCents": plan["cycleAmountCents"],
            "authorizedAmountCents": plan["authorizedAmountCents"],
            "servicePeriodStart": plan["servicePeriodStart"],
            "servicePeriodEnd": plan["servicePeriodEnd"],
            "memo": plan["memo"],
            "previewHash": preview_hash,
            "idempotencyKey": idempotency_key,
            "chargeTransaction": evidence["charge"],
            "paymentTransaction": evidence["payment"],
            "balances": plan["balances"],
            "currentBillingAmountCents": plan["currentBillingAmountCents"],
            "nextAssessmentAt": plan["nextAssessmentAt"],
            "providerStatusCode": provider_result.get("statusCode") if provider_result else None,
        }

    def _partial_location_collection_plan(
        self,
        subscription_id: int,
        location_count: int,
        unit_rate_cents: int,
        authorized_amount_cents: int,
        service_period_start: str,
        service_period_end: str,
        ticket_number: str,
    ) -> dict[str, Any]:
        clean_subscription_id = _positive_id(subscription_id, "subscription_id")
        clean_location_count = _bounded_positive_count(location_count, "location_count", 500)
        clean_unit_rate = _positive_cents(unit_rate_cents, "unit_rate_cents")
        clean_authorized_amount = _positive_cents(
            authorized_amount_cents,
            "authorized_amount_cents",
        )
        if clean_location_count * clean_unit_rate != clean_authorized_amount:
            raise MaxioScopeError(
                "authorized_amount_cents must exactly equal location_count multiplied by unit_rate_cents"
            )
        clean_start = _required_api_date(service_period_start, "service_period_start")
        clean_end = _required_api_date(service_period_end, "service_period_end")
        if clean_end <= clean_start:
            raise MaxioScopeError("service_period_end must be after service_period_start")
        clean_ticket = _ticket_number(ticket_number)

        subscription = _subscription_record(
            self._get(f"/subscriptions/{clean_subscription_id}.json")
        )
        if _required_integer_field(subscription, ("id",), "subscription ID") != clean_subscription_id:
            raise MaxioUnavailableError("Maxio subscription response did not match the requested ID")
        if str(subscription.get("state") or "").strip().casefold() != "active":
            raise MaxioScopeError("partial-location collection requires an active subscription")
        if (
            str(subscription.get("payment_collection_method") or "").strip().casefold()
            != "automatic"
        ):
            raise MaxioScopeError(
                "partial-location collection requires automatic payment collection"
            )
        subscription_balance = _required_integer_field(
            subscription,
            ("balance_in_cents", "current_balance_in_cents"),
            "subscription balance",
        )
        if subscription_balance != 0:
            raise MaxioScopeError(
                "partial-location collection requires a zero subscription balance"
            )
        current_period_start = _required_api_date(
            subscription.get("current_period_started_at"),
            "subscription current period start",
        )
        current_period_end = _required_api_date(
            subscription.get("current_period_ends_at"),
            "subscription current period end",
        )
        if (clean_start, clean_end) != (current_period_start, current_period_end):
            raise MaxioScopeError(
                "service period must exactly match the subscription's current billing period"
            )
        next_assessment_at = str(
            subscription.get("next_assessment_at")
            or subscription.get("next_billing_at")
            or ""
        ).strip()
        if not next_assessment_at:
            raise MaxioUnavailableError("Maxio subscription omitted the next assessment timestamp")

        customer = (
            subscription.get("customer")
            if isinstance(subscription.get("customer"), Mapping)
            else {}
        )
        customer_id = _numeric_api_id(customer.get("id") or subscription.get("customer_id"))
        nested_profile = (
            subscription.get("payment_profile")
            if isinstance(subscription.get("payment_profile"), Mapping)
            else subscription.get("credit_card")
            if isinstance(subscription.get("credit_card"), Mapping)
            else {}
        )
        profile_id = _numeric_api_id(
            nested_profile.get("id") or subscription.get("payment_profile_id")
        )
        if customer_id is None or profile_id is None:
            raise MaxioScopeError(
                "subscription does not expose one exact customer and payment profile"
            )
        profiles = _wrapped_records(
            self._get(
                "/payment_profiles.json",
                params={"customer_id": customer_id, "page": 1, "per_page": 200},
            ),
            "payment_profile",
        )
        selected_profiles = [
            row for row in profiles if _numeric_api_id(row.get("id")) == profile_id
        ]
        if len(selected_profiles) != 1:
            raise MaxioScopeError(
                "the subscription payment profile did not resolve exactly under its customer"
            )
        payment_profile = selected_profiles[0]
        if payment_profile.get("disabled_at"):
            raise MaxioScopeError("the subscription payment profile is disabled")
        _assert_payment_profile_not_expired(payment_profile)

        balances = self.subscription_account_balances(clean_subscription_id)["balances"]
        if not _all_balances_zero(balances):
            raise MaxioScopeError(
                "partial-location collection requires zero invoice, discount, credit, and prepayment balances"
            )

        metadata = self.subscription_location_metadata(clean_subscription_id)
        location_state = _verified_location_metadata(metadata["values"])
        total_locations = len(location_state["locationIds"])
        if clean_location_count >= total_locations:
            raise MaxioScopeError(
                "location_count must be smaller than the verified active location count"
            )
        component_ids = set(location_state["componentMap"].values())
        if len(component_ids) != 1:
            raise MaxioScopeError(
                "partial-location collection requires all active locations to use one component"
            )
        component_id = next(iter(component_ids))
        component_payload = self._get(
            f"/subscriptions/{clean_subscription_id}/components.json",
            params={"page": 1, "per_page": 200},
        )
        quantities = _component_quantities(component_payload)
        if quantities.get(component_id) != total_locations:
            raise MaxioScopeError(
                "the location map does not match the current component allocation"
            )
        component = _wrapped_record(
            self._get(f"/components/{component_id}.json"),
            "component",
            "component",
        )
        if _required_integer_field(component, ("id",), "component ID") != component_id:
            raise MaxioUnavailableError("Maxio component response did not match the location map")
        actual_unit_rate = _decimal_dollars_to_cents(
            component.get("unit_price"),
            "component unit price",
        )
        if actual_unit_rate != clean_unit_rate:
            raise MaxioScopeError(
                "unit_rate_cents does not match the active location component price"
            )
        current_billing_amount = _required_integer_field(
            subscription,
            ("current_billing_amount_in_cents",),
            "current billing amount",
        )
        if current_billing_amount != total_locations * clean_unit_rate:
            raise MaxioScopeError(
                "current subscription billing amount does not equal active locations multiplied by unit rate"
            )

        memo = (
            f"Ticket {clean_ticket}: partial location recovery "
            f"{clean_location_count} x {_currency_amount(clean_unit_rate)} "
            f"for {clean_start} through {clean_end}"
        )
        provider_charge = {
            "amount_in_cents": clean_authorized_amount,
            "memo": memo,
            "delay_capture": False,
            "accrue_on_failure": False,
            "use_negative_balance": False,
            "taxable": False,
            "payment_collection_method": "automatic",
            "period_range_start": clean_start,
            "period_range_end": clean_end,
        }
        transactions = _transaction_records(
            self._get(
                f"/subscriptions/{clean_subscription_id}/transactions.json",
                params={
                    "page": 1,
                    "per_page": 200,
                    "since_date": clean_start,
                    "until_date": clean_end,
                    "direction": "desc",
                },
            )
        )
        matching_charges = [
            row
            for row in transactions
            if row["transactionType"] == "charge"
            and row["amountCents"] == clean_authorized_amount
            and row["memo"] == memo
            and row["success"]
        ]
        if len(matching_charges) > 1:
            raise MaxioScopeError(
                "multiple matching partial-location charges exist; reconcile Maxio before continuing"
            )
        existing_collection = (
            _successful_collection_evidence(matching_charges[0], transactions)
            if matching_charges
            else None
        )
        if matching_charges and existing_collection is None:
            raise MaxioUnavailableError(
                "a matching partial-location charge exists but its linked successful payment "
                "was not verified; do not retry"
            )
        collection_controls = {
            "delayCapture": False,
            "accrueOnFailure": False,
            "useNegativeBalance": False,
            "taxable": False,
            "paymentCollectionMethod": "automatic",
            "allocationChange": False,
            "retryAfterAttempt": False,
        }
        hash_payload = {
            "operation": "maxio_partial_location_collection",
            "subscriptionId": clean_subscription_id,
            "ticketNumber": clean_ticket,
            "locationCount": clean_location_count,
            "totalActiveLocations": total_locations,
            "locationIds": location_state["locationIds"],
            "componentId": component_id,
            "allocatedQuantity": quantities[component_id],
            "unitRateCents": clean_unit_rate,
            "authorizedAmountCents": clean_authorized_amount,
            "servicePeriodStart": clean_start,
            "servicePeriodEnd": clean_end,
            "memo": memo,
            "currentBillingAmountCents": current_billing_amount,
            "nextAssessmentAt": next_assessment_at,
            "subscriptionUpdatedAt": str(subscription.get("updated_at") or ""),
            "paymentProfileId": profile_id,
            "balances": balances,
            "collectionControls": collection_controls,
            "transactionIds": [row["id"] for row in transactions],
            "existingSuccessfulCollection": existing_collection,
        }
        return {
            **hash_payload,
            "previewHash": _plan_hash(hash_payload),
            "providerCharge": provider_charge,
            "paymentProfile": {
                "id": profile_id,
                "paymentType": str(payment_profile.get("payment_type") or ""),
                "expirationMonth": payment_profile.get("expiration_month"),
                "expirationYear": payment_profile.get("expiration_year"),
            },
            "transactions": transactions,
        }

    def _partial_location_collection_result(
        self,
        plan: Mapping[str, Any],
        *,
        preview_hash: str,
        idempotency_key: str,
        duplicate: bool,
        provider_result: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        evidence = plan.get("existingSuccessfulCollection")
        if not isinstance(evidence, Mapping):
            raise MaxioUnavailableError(
                "Maxio did not return a linked successful charge and payment"
            )
        if not _all_balances_zero(plan["balances"]):
            raise MaxioUnavailableError(
                "the collection transactions succeeded but zero account balances were not verified"
            )
        return {
            "ok": True,
            "status": "collected",
            "attempted": not duplicate,
            "updated": not duplicate,
            "duplicate": duplicate,
            "verified": True,
            "retryAllowed": False,
            "subscriptionId": plan["subscriptionId"],
            "ticketNumber": plan["ticketNumber"],
            "locationCount": plan["locationCount"],
            "authorizedAmountCents": plan["authorizedAmountCents"],
            "memo": plan["memo"],
            "previewHash": preview_hash,
            "idempotencyKey": idempotency_key,
            "chargeTransaction": evidence["charge"],
            "paymentTransaction": evidence["payment"],
            "balances": plan["balances"],
            "allocationVerified": True,
            "currentBillingAmountCents": plan["currentBillingAmountCents"],
            "nextAssessmentAt": plan["nextAssessmentAt"],
            "providerStatusCode": provider_result.get("statusCode") if provider_result else None,
        }

    def _subscription_cancellation_plan(
        self,
        subscription_id: int,
        ticket_number: str,
        reason: str,
    ) -> dict[str, Any]:
        clean_subscription_id = _positive_id(subscription_id, "subscription_id")
        clean_ticket = str(ticket_number or "").strip()
        if not TICKET_NUMBER.fullmatch(clean_ticket):
            raise MaxioScopeError("ticket_number must be 4-12 digits")
        clean_reason = _bounded_text(reason, "reason", 350)
        cancellation_message = f"Ticket {clean_ticket}: {clean_reason}"
        payload = self._get(f"/subscriptions/{clean_subscription_id}.json")
        record = _subscription_record(payload)
        try:
            returned_id = int(record.get("id"))
        except (TypeError, ValueError) as exc:
            raise MaxioUnavailableError("Maxio subscription response did not include an exact ID") from exc
        if returned_id != clean_subscription_id:
            raise MaxioUnavailableError("Maxio subscription response did not match the requested ID")
        current_state = str(record.get("state") or "").strip().casefold()
        if not current_state:
            raise MaxioUnavailableError("Maxio subscription response did not include a state")
        balance_cents = _required_integer_field(
            record,
            ("balance_in_cents", "current_balance_in_cents"),
            "subscription balance",
        )
        customer = record.get("customer") if isinstance(record.get("customer"), dict) else {}
        product = record.get("product") if isinstance(record.get("product"), dict) else {}
        apply_required = current_state not in CANCELED_SUBSCRIPTION_STATES
        component_deallocation_summary = _component_deallocation_summary(
            self._subscription_component_rows(clean_subscription_id)
        )
        existing_schedule = {
            "cancelAtEndOfPeriod": bool(record.get("cancel_at_end_of_period")),
            "delayedCancelAt": str(record.get("delayed_cancel_at") or ""),
        }
        hash_payload = {
            "subscriptionId": clean_subscription_id,
            "ticketNumber": clean_ticket,
            "cancellationMessage": cancellation_message,
            "currentState": current_state,
            "currentBalanceCents": balance_cents,
            "updatedAt": str(record.get("updated_at") or ""),
            "canceledAt": str(record.get("canceled_at") or ""),
            "nextAssessmentAt": str(record.get("next_assessment_at") or record.get("next_billing_at") or ""),
            "existingScheduledCancellation": existing_schedule,
            "componentDeallocationSummary": component_deallocation_summary,
            "timing": "immediate",
            "scheduleParametersOmitted": True,
        }
        preview_hash = hashlib.sha256(
            json.dumps(hash_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return {
            "subscriptionId": clean_subscription_id,
            "ticketNumber": clean_ticket,
            "cancellationMessage": cancellation_message,
            "currentState": current_state,
            "currentBalanceCents": balance_cents,
            "nextAssessmentAt": hash_payload["nextAssessmentAt"],
            "existingScheduledCancellation": existing_schedule,
            "componentDeallocationSummary": component_deallocation_summary,
            "customer": {
                "id": customer.get("id"),
                "reference": str(customer.get("reference") or ""),
                "organization": str(customer.get("organization") or ""),
            },
            "product": {
                "id": product.get("id"),
                "name": str(product.get("name") or ""),
                "handle": str(product.get("handle") or ""),
            },
            "applyRequired": apply_required,
            "previewHash": preview_hash,
            "readback": record,
        }

    def _past_due_subscription_cancellation_plan(
        self,
        subscription_id: int,
        ticket_number: str,
        reason: str,
    ) -> dict[str, Any]:
        clean_subscription_id = _positive_id(subscription_id, "subscription_id")
        clean_ticket = str(ticket_number or "").strip()
        if not TICKET_NUMBER.fullmatch(clean_ticket):
            raise MaxioScopeError("ticket_number must be 4-12 digits")
        clean_reason = _bounded_text(reason, "reason", 350)
        cancellation_message = f"Ticket {clean_ticket}: {clean_reason}"
        record = _subscription_record(
            self._get(f"/subscriptions/{clean_subscription_id}.json")
        )
        try:
            returned_id = int(record.get("id"))
        except (TypeError, ValueError) as exc:
            raise MaxioUnavailableError(
                "Maxio subscription response did not include an exact ID"
            ) from exc
        if returned_id != clean_subscription_id:
            raise MaxioUnavailableError(
                "Maxio subscription response did not match the requested ID"
            )
        state = str(record.get("state") or "").strip().casefold()
        if state not in {"past_due", "unpaid", *CANCELED_SUBSCRIPTION_STATES}:
            raise MaxioScopeError(
                "past-due cancellation requires a past_due, unpaid, or already canceled subscription"
            )
        customer = record.get("customer") if isinstance(record.get("customer"), dict) else {}
        customer_id = _positive_id(customer.get("id"), "subscription customer id")
        balances = self.subscription_account_balances(clean_subscription_id)["balances"]
        open_balance = int(balances.get("openInvoiceBalanceCents", 0))
        other_balances = {
            key: value
            for key, value in balances.items()
            if key != "openInvoiceBalanceCents"
        }
        if open_balance <= 0 or not _all_balances_zero(other_balances):
            raise MaxioScopeError(
                "past-due cancellation requires one positive open-invoice balance and every other balance clear"
            )
        open_invoices = self._subscription_open_invoice_snapshot(
            clean_subscription_id,
            customer_id,
        )
        if sum(int(row["dueAmountCents"]) for row in open_invoices) != open_balance:
            raise MaxioScopeError(
                "open invoice totals do not match the subscription balance; reconcile before cancellation"
            )
        product = record.get("product") if isinstance(record.get("product"), dict) else {}
        component_summary = _component_deallocation_summary(
            self._subscription_component_rows(clean_subscription_id)
        )
        apply_required = state not in CANCELED_SUBSCRIPTION_STATES
        hash_payload = {
            "subscriptionId": clean_subscription_id,
            "ticketNumber": clean_ticket,
            "cancellationMessage": cancellation_message,
            "currentState": state,
            "updatedAt": str(record.get("updated_at") or ""),
            "canceledAt": str(record.get("canceled_at") or ""),
            "balances": balances,
            "openInvoices": open_invoices,
            "componentDeallocationSummary": component_summary,
            "timing": "immediate",
            "preserveOpenInvoiceRequired": True,
        }
        preview_hash = hashlib.sha256(
            json.dumps(hash_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return {
            "subscriptionId": clean_subscription_id,
            "ticketNumber": clean_ticket,
            "cancellationMessage": cancellation_message,
            "currentState": state,
            "balances": balances,
            "openInvoices": open_invoices,
            "componentDeallocationSummary": component_summary,
            "customer": {
                "id": customer_id,
                "reference": str(customer.get("reference") or ""),
                "organization": str(customer.get("organization") or ""),
            },
            "product": {
                "id": product.get("id"),
                "name": str(product.get("name") or ""),
                "handle": str(product.get("handle") or ""),
            },
            "applyRequired": apply_required,
            "previewHash": preview_hash,
            "readback": record,
        }

    def _subscription_open_invoice_snapshot(
        self,
        subscription_id: int,
        customer_id: int,
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        page_size = 200
        for page in range(1, 11):
            payload = self._get(
                "/invoices.json",
                params={
                    "subscription_id": subscription_id,
                    "customer_ids": customer_id,
                    "page": page,
                    "per_page": page_size,
                },
            )
            collection = payload.get("invoices") if isinstance(payload, Mapping) else payload
            batch = _wrapped_records(collection, "invoice")
            for invoice in batch:
                returned_subscription_id = invoice.get("subscription_id")
                if returned_subscription_id is not None and int(returned_subscription_id) != subscription_id:
                    raise MaxioUnavailableError(
                        "Maxio returned an invoice for a different subscription"
                    )
                due_cents = (
                    _nonnegative_cents(invoice.get("due_amount_in_cents"), "invoice due amount")
                    if invoice.get("due_amount_in_cents") is not None
                    else _nonnegative_decimal_dollars_to_cents(
                        invoice.get("due_amount"),
                        "invoice due amount",
                    )
                )
                if due_cents <= 0:
                    continue
                uid = str(invoice.get("uid") or "").strip()
                if not INVOICE_UID.fullmatch(uid):
                    raise MaxioUnavailableError(
                        "Maxio open invoice response did not include one exact UID"
                    )
                rows.append(
                    {
                        "uid": uid,
                        "number": str(invoice.get("number") or ""),
                        "status": str(invoice.get("status") or "").strip().casefold(),
                        "dueAmountCents": due_cents,
                        "totalAmountCents": (
                            _nonnegative_cents(
                                invoice.get("total_amount_in_cents"),
                                "invoice total amount",
                            )
                            if invoice.get("total_amount_in_cents") is not None
                            else _nonnegative_decimal_dollars_to_cents(
                                invoice.get("total_amount"),
                                "invoice total amount",
                            )
                        ),
                    }
                )
            if len(batch) < page_size:
                break
        else:
            raise MaxioUnavailableError(
                "Maxio open-invoice pagination exceeded 2,000 invoices"
            )
        if not rows:
            raise MaxioScopeError(
                "past-due cancellation requires at least one exact open invoice"
            )
        return sorted(rows, key=lambda row: row["uid"])

    def _cancel_subscription(
        self,
        subscription_id: int,
        *,
        cancellation_message: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        """Call only Maxio's cancellation endpoint; this never deletes subscription history."""

        clean_subscription_id = _positive_id(subscription_id, "subscription_id")
        clean_message = _bounded_text(cancellation_message, "cancellation_message", 500)
        clean_key = str(idempotency_key or "").strip()
        if not IDEMPOTENCY_KEY.fullmatch(clean_key):
            raise MaxioScopeError("mutations require an idempotency_key of 8-240 safe characters")
        method = "DELETE"
        path = f"/subscriptions/{clean_subscription_id}.json"
        body = {"subscription": {"cancellation_message": clean_message}}
        request_hash = hashlib.sha256(
            json.dumps(
                {"method": method, "path": path, "params": {}, "body": body},
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        base_url = self._validated_base_url()
        if not self.settings.api_key:
            raise MaxioUnavailableError("Maxio broker credentials are not configured")

        with self._operation_lock():
            prior = self._prior_operation(clean_key, method, path, request_hash)
            if prior:
                if prior["status"] == "pending":
                    raise MaxioScopeError(
                        "idempotency_key has an uncertain pending outcome; "
                        "read back the subscription before any retry"
                    )
                return {
                    "ok": prior["status"] == "accepted",
                    "duplicate": True,
                    "idempotencyKey": clean_key,
                    "prior": prior.get("evidence") or {},
                }
            self._journal("pending", clean_key, method, path, request_hash, {})
            try:
                response = self.session.request(
                    method,
                    f"{base_url}{path}",
                    json=body,
                    auth=(self.settings.api_key, "x"),
                    headers={"Accept": "application/json", "User-Agent": "nova-scoped-maxio/2"},
                    timeout=60,
                )
            except requests.RequestException as exc:
                raise MaxioUnavailableError(
                    "Maxio cancellation failed before a provider response was received"
                ) from exc

            content = bytes(response.content or b"")
            if len(content) > MAX_RESPONSE_BYTES:
                raise MaxioUnavailableError("Maxio cancellation response exceeded the bounded response limit")
            status_code = int(response.status_code)
            ok = 200 <= status_code < 300
            response_body: Any = None
            if content:
                try:
                    response_body = response.json()
                except ValueError:
                    response_body = {"message": "Maxio returned a non-JSON response"}
            evidence = {"statusCode": status_code}
            self._journal(
                "accepted" if ok else "failed",
                clean_key,
                method,
                path,
                request_hash,
                evidence,
            )
            return {
                "ok": ok,
                "duplicate": False,
                "method": method,
                "path": path,
                "statusCode": status_code,
                "body": response_body,
                "idempotencyKey": clean_key,
                "readbackRequired": ok,
            }

    def _post_preview(self, path: str, json_body: dict[str, Any]) -> Any:
        clean_path = _safe_api_path(path)
        _encoded_json(json_body)
        base_url = self._validated_base_url()
        if not self.settings.api_key:
            raise MaxioUnavailableError("Maxio broker credentials are not configured")
        try:
            response = self.session.request(
                "POST",
                f"{base_url}{clean_path}",
                json=json_body,
                auth=(self.settings.api_key, "x"),
                headers={"Accept": "application/json", "User-Agent": "nova-scoped-maxio/2"},
                timeout=60,
            )
            response.raise_for_status()
            content = bytes(response.content or b"")
            if len(content) > MAX_RESPONSE_BYTES:
                raise MaxioUnavailableError("Maxio preview response exceeded the bounded response limit")
            return response.json() if content else None
        except MaxioUnavailableError:
            raise
        except requests.RequestException as exc:
            raise MaxioUnavailableError("Maxio allocation preview request failed") from exc
        except (TypeError, ValueError) as exc:
            raise MaxioUnavailableError("Maxio allocation preview returned invalid JSON") from exc

    def _single(self, path: str, *, operation: str) -> dict[str, Any]:
        return {"ok": True, "operation": operation, "record": self._get(path)}

    def _get(self, path: str, *, params: dict[str, Any] | None = None) -> Any:
        base_url = self._validated_base_url()
        if not self.settings.api_key:
            raise MaxioUnavailableError("Maxio broker credentials are not configured")
        try:
            response = self.session.get(
                f"{base_url}{path}",
                params=params or {},
                auth=(self.settings.api_key, "x"),
                headers={"Accept": "application/json", "User-Agent": "nova-scoped-maxio/1"},
                timeout=30,
            )
            response.raise_for_status()
            content = response.content
            if len(content) > MAX_RESPONSE_BYTES:
                raise MaxioUnavailableError("Maxio response exceeded the bounded response limit")
            return response.json()
        except MaxioUnavailableError:
            raise
        except requests.RequestException as exc:
            raise MaxioUnavailableError("Maxio request failed") from exc
        except ValueError as exc:
            raise MaxioUnavailableError("Maxio returned an invalid JSON response") from exc

    def _validated_base_url(self) -> str:
        parsed = urlparse(self.settings.base_url)
        hostname = (parsed.hostname or "").lower()
        approved_host = (
            hostname == "chargify.com"
            or hostname.endswith(".chargify.com")
            or hostname == "maxio.com"
            or hostname.endswith(".maxio.com")
        )
        if parsed.scheme != "https" or not approved_host or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise MaxioUnavailableError("Maxio base URL is outside the approved HTTPS host boundary")
        return self.settings.base_url

    def _prior_operation(
        self,
        key: str,
        method: str,
        path: str,
        request_hash: str,
    ) -> dict[str, Any] | None:
        journal = self.settings.journal_path
        if not journal.is_file():
            return None
        with journal.open("r", encoding="utf-8") as handle:
            recent = deque(handle, maxlen=5000)
        for line in reversed(recent):
            try:
                row = json.loads(line)
            except (TypeError, ValueError):
                continue
            if row.get("idempotencyKey") != key:
                continue
            if any(
                row.get(field) != expected
                for field, expected in (
                    ("method", method),
                    ("path", path),
                    ("requestHash", request_hash),
                )
            ):
                raise MaxioScopeError("idempotency_key was already used for a different Maxio operation")
            return row
        return None

    def _prior_request_operation(
        self,
        method: str,
        path: str,
        request_hash: str,
    ) -> dict[str, Any] | None:
        journal = self.settings.journal_path
        if not journal.is_file():
            return None
        with journal.open("r", encoding="utf-8") as handle:
            recent = deque(handle, maxlen=5000)
        for line in reversed(recent):
            try:
                row = json.loads(line)
            except (TypeError, ValueError):
                continue
            if (
                row.get("method") == method
                and row.get("path") == path
                and row.get("requestHash") == request_hash
            ):
                return row
        return None

    @contextmanager
    def _operation_lock(self) -> Iterator[None]:
        lock_path = Path(f"{self.settings.journal_path}.lock")
        lock_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        with LOCAL_OPERATION_LOCK, os.fdopen(descriptor, "a+b") as handle:
            try:
                if fcntl is not None:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                yield
            finally:
                if fcntl is not None:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def _journal(
        self,
        status: str,
        key: str,
        method: str,
        path: str,
        request_hash: str,
        evidence: dict[str, Any],
    ) -> None:
        journal = self.settings.journal_path
        journal.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        record = {
            "time": int(time.time()),
            "status": status,
            "idempotencyKey": key,
            "method": method,
            "path": path,
            "requestHash": request_hash,
            "evidence": evidence,
        }
        descriptor = os.open(journal, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
        with os.fdopen(descriptor, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
            handle.flush()
            os.fsync(handle.fileno())


def _subscription_record(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise MaxioUnavailableError("Maxio subscription response had an unexpected shape")
    wrapped = payload.get("subscription")
    record = wrapped if isinstance(wrapped, Mapping) else payload
    return dict(record)


def _subscription_customer_id(subscription: Mapping[str, Any]) -> int:
    customer = subscription.get("customer")
    customer_record = customer if isinstance(customer, Mapping) else {}
    customer_id = _numeric_api_id(
        customer_record.get("id") or subscription.get("customer_id")
    )
    if customer_id is None:
        raise MaxioUnavailableError("Maxio subscription response omitted the customer ID")
    return customer_id


def _optional_subscription_payment_profile_id(
    subscription: Mapping[str, Any],
) -> int | None:
    profile = subscription.get("payment_profile")
    profile_record = profile if isinstance(profile, Mapping) else {}
    credit_card = subscription.get("credit_card")
    credit_card_record = credit_card if isinstance(credit_card, Mapping) else {}
    bank_account = subscription.get("bank_account")
    bank_account_record = bank_account if isinstance(bank_account, Mapping) else {}
    return _numeric_api_id(
        profile_record.get("id")
        or subscription.get("payment_profile_id")
        or credit_card_record.get("id")
        or bank_account_record.get("id")
    )


def _subscription_payment_profile_id(subscription: Mapping[str, Any]) -> int:
    profile_id = _optional_subscription_payment_profile_id(subscription)
    if profile_id is None:
        raise MaxioUnavailableError(
            "Maxio subscription response omitted the active payment profile ID"
        )
    return profile_id


def _public_payment_profile(profile: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "id": _required_integer_field(profile, ("id",), "payment profile ID"),
        "customerId": _required_integer_field(
            profile,
            ("customer_id",),
            "payment profile customer ID",
        ),
        "paymentType": str(profile.get("payment_type") or "").strip(),
        "maskedNumber": str(
            profile.get("masked_card_number")
            or profile.get("masked_bank_account_number")
            or ""
        ).strip(),
        "expirationMonth": profile.get("expiration_month"),
        "expirationYear": profile.get("expiration_year"),
        "disabled": bool(profile.get("disabled_at") or profile.get("disabled") is True),
    }


def _masked_email(value: str) -> str:
    local, separator, domain = str(value or "").strip().partition("@")
    if not separator or not local or not domain:
        return ""
    visible = local[:1]
    return f"{visible}{'*' * max(2, len(local) - 1)}@{domain}"


def _subscription_product_family_id(subscription: Mapping[str, Any]) -> int:
    product = subscription.get("product")
    product_record = product if isinstance(product, Mapping) else {}
    family = product_record.get("product_family")
    family_record = family if isinstance(family, Mapping) else {}
    for value in (
        family_record.get("id"),
        product_record.get("product_family_id"),
        subscription.get("product_family_id"),
    ):
        family_id = _numeric_api_id(value)
        if family_id:
            return family_id
    raise MaxioUnavailableError(
        "Maxio subscription response omitted the product family required to validate the coupon"
    )


def _product_family_id(product: Mapping[str, Any]) -> int:
    family = product.get("product_family")
    family_record = family if isinstance(family, Mapping) else {}
    for value in (family_record.get("id"), product.get("product_family_id")):
        family_id = _numeric_api_id(value)
        if family_id:
            return family_id
    raise MaxioUnavailableError("Maxio product response omitted the product family")


def _subscription_product_summary(subscription: Mapping[str, Any]) -> dict[str, Any]:
    product = subscription.get("product")
    product_record = product if isinstance(product, Mapping) else {}
    product_id = _numeric_api_id(product_record.get("id") or subscription.get("product_id"))
    if product_id is None:
        raise MaxioUnavailableError("Maxio subscription response omitted the product ID")
    return {
        "id": product_id,
        "name": str(product_record.get("name") or "").strip(),
        "handle": str(product_record.get("handle") or "").strip(),
        "productFamilyId": _subscription_product_family_id(subscription),
    }


def _subscription_period_summary(subscription: Mapping[str, Any]) -> dict[str, Any]:
    return {
        field: subscription.get(field)
        for field in (
            "current_period_started_at",
            "current_period_ends_at",
            "next_assessment_at",
        )
    }


def _product_base_price_cents(product: Mapping[str, Any]) -> int:
    if product.get("price_in_cents") is not None:
        return _numeric_api_nonnegative(product.get("price_in_cents"))
    if product.get("price") is not None:
        return _nonnegative_decimal_dollars_to_cents(product.get("price"), "product base price")
    price_point = product.get("default_product_price_point")
    if isinstance(price_point, Mapping):
        if price_point.get("price_in_cents") is not None:
            return _numeric_api_nonnegative(price_point.get("price_in_cents"))
        if price_point.get("price") is not None:
            return _nonnegative_decimal_dollars_to_cents(
                price_point.get("price"),
                "product base price",
            )
    raise MaxioUnavailableError("Maxio product response omitted the base price")


def _merchant_provider(value: Any) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "", str(value or "").casefold())
    aliases = {
        "worldpay": "Worldpay",
        "creditcall": "Creditcall",
        "authorizenet": "Authorize.net",
        "propelr": "Propelr",
    }
    provider = aliases.get(normalized)
    if provider is None:
        raise MaxioScopeError(
            "merchant_provider is required and must be one of: "
            + ", ".join(NOVA_INTEGRATED_MERCHANT_PROVIDERS)
        )
    return provider


def _product_merchant_provider(name: Any, handle: Any) -> str:
    normalized = re.sub(
        r"[^a-z0-9]+",
        " ",
        f"{str(name or '')} {str(handle or '')}".casefold(),
    ).strip()
    if re.search(r"\b(worldpay|tripos)\b", normalized):
        return "Worldpay"
    if re.search(r"\b(creditcall|credit call|chipdna)\b", normalized):
        return "Creditcall"
    if re.search(r"\b(authorize net|authorizenet|augusta)\b", normalized):
        return "Authorize.net"
    if re.search(r"\bpropelr\b", normalized):
        return "Propelr"
    return ""


def _component_unit_rate_cents(component: Mapping[str, Any]) -> int:
    if component.get("unit_price_in_cents") is not None:
        return _numeric_api_nonnegative(component.get("unit_price_in_cents"))
    if component.get("unit_price") is not None:
        return _decimal_dollars_to_cents(component.get("unit_price"), "component unit price")
    price_point = component.get("default_price_point")
    if isinstance(price_point, Mapping):
        if price_point.get("price_in_cents") is not None:
            return _numeric_api_nonnegative(price_point.get("price_in_cents"))
        if price_point.get("price") is not None:
            return _decimal_dollars_to_cents(
                price_point.get("price"),
                "component unit price",
            )
    raise MaxioUnavailableError("Maxio component response omitted the unit price")


def _service_credit_history(payload: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for record in _wrapped_records(payload, "service_credit"):
        amount_value = record.get("amount_in_cents")
        if amount_value is None and record.get("amount") is not None:
            try:
                amount_value = _decimal_dollars_to_cents(
                    record.get("amount"),
                    "service credit amount",
                )
            except MaxioScopeError:
                continue
        try:
            amount_cents = int(amount_value)
        except (TypeError, ValueError):
            continue
        memo = str(
            record.get("memo")
            or record.get("description")
            or record.get("reason")
            or ""
        ).strip()
        rows.append(
            {
                "id": _numeric_api_id(record.get("id")),
                "amountCents": amount_cents,
                "memo": memo,
                "createdAt": str(record.get("created_at") or ""),
            }
        )
    return rows


def _nonzero_component_allocations(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, list):
        raise MaxioUnavailableError("Maxio component response had an unexpected shape")
    allocations: list[dict[str, Any]] = []
    for raw in payload:
        if not isinstance(raw, Mapping):
            continue
        nested = raw.get("component")
        component = nested if isinstance(nested, Mapping) else raw
        component_id = _numeric_api_id(component.get("id") or raw.get("component_id"))
        quantity = _numeric_api_nonnegative(
            raw.get("allocated_quantity", raw.get("quantity", 0))
        )
        if component_id is None or quantity <= 0:
            continue
        allocations.append(
            {
                "componentId": component_id,
                "name": str(component.get("name") or "").strip(),
                "quantity": quantity,
            }
        )
    return sorted(allocations, key=lambda row: row["componentId"])


def _subscription_coupon_codes(subscription: Mapping[str, Any]) -> list[str]:
    candidates: list[Any] = []
    if isinstance(subscription.get("coupon_codes"), list):
        candidates.extend(subscription["coupon_codes"])
    if subscription.get("coupon_code"):
        candidates.append(subscription["coupon_code"])
    coupons = subscription.get("coupons")
    if isinstance(coupons, list):
        for row in coupons:
            if isinstance(row, Mapping):
                nested = row.get("coupon")
                record = nested if isinstance(nested, Mapping) else row
                candidates.append(record.get("code"))
    result: list[str] = []
    seen: set[str] = set()
    for value in candidates:
        if value is None:
            continue
        code = _coupon_code(value)
        key = code.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(code)
    return result


def _wrapped_record(payload: Any, key: str, label: str) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise MaxioUnavailableError(f"Maxio {label} response had an unexpected shape")
    nested = payload.get(key)
    record = nested if isinstance(nested, Mapping) else payload
    return dict(record)


def _wrapped_records(payload: Any, key: str) -> list[dict[str, Any]]:
    if not isinstance(payload, list):
        raise MaxioUnavailableError("Maxio collection response had an unexpected shape")
    records: list[dict[str, Any]] = []
    for raw in payload[:200]:
        if not isinstance(raw, Mapping):
            continue
        nested = raw.get(key)
        records.append(dict(nested) if isinstance(nested, Mapping) else dict(raw))
    return records


def _numeric_api_id(value: Any) -> int | None:
    if value is None or value == "" or isinstance(value, bool):
        return None
    try:
        clean = int(value)
    except (TypeError, ValueError):
        return None
    return clean if clean > 0 else None


def _numeric_api_nonnegative(value: Any) -> int:
    if value is None or value == "" or isinstance(value, bool):
        return 0
    try:
        clean = int(value)
    except (TypeError, ValueError) as exc:
        raise MaxioUnavailableError("Maxio response returned an invalid non-negative integer") from exc
    if clean < 0:
        raise MaxioUnavailableError("Maxio response returned a negative value")
    return clean


def _optional_api_date(value: Any, label: str) -> date | None:
    clean = str(value or "").strip()
    if not clean:
        return None
    try:
        return date.fromisoformat(clean[:10])
    except ValueError as exc:
        raise MaxioUnavailableError(f"Maxio response returned an invalid {label}") from exc


def _parse_api_datetime(value: Any, label: str) -> datetime:
    clean = str(value or "").strip()
    if not clean:
        raise MaxioUnavailableError(f"Maxio response omitted {label}")
    normalized = clean[:-1] + "+00:00" if clean.endswith("Z") else clean
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise MaxioUnavailableError(f"Maxio response returned an invalid {label}") from exc
    if parsed.tzinfo is None:
        raise MaxioUnavailableError(f"Maxio response returned a timezone-free {label}")
    return parsed.astimezone(timezone.utc)


def _future_billing_timestamp(value: Any) -> tuple[str, datetime]:
    clean = str(value or "").strip()
    normalized = clean[:-1] + "+00:00" if clean.endswith("Z") else clean
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise MaxioScopeError(
            "next_billing_at must be one ISO-8601 timestamp with a timezone"
        ) from exc
    if parsed.tzinfo is None:
        raise MaxioScopeError("next_billing_at must include a timezone")
    parsed_utc = parsed.astimezone(timezone.utc)
    now = datetime.now(timezone.utc)
    if parsed_utc < now + timedelta(minutes=15):
        raise MaxioScopeError(
            "next_billing_at must be at least 15 minutes in the future so creation cannot bill now"
        )
    if parsed_utc > now + timedelta(days=62):
        raise MaxioScopeError(
            "next_billing_at must be within 62 days for this monthly repair workflow"
        )
    return parsed_utc.isoformat(timespec="seconds"), parsed_utc


def _decimal_dollars_to_cents(value: Any, label: str) -> int:
    try:
        cents = int(
            (Decimal(str(value)) * Decimal(100)).quantize(Decimal("1"))
        )
    except Exception as exc:
        raise MaxioUnavailableError(f"Maxio returned an invalid {label}") from exc
    if cents <= 0:
        raise MaxioScopeError(f"{label} must be positive")
    return cents


def _nonnegative_decimal_dollars_to_cents(value: Any, label: str) -> int:
    try:
        cents = int((Decimal(str(value)) * Decimal(100)).quantize(Decimal("1")))
    except Exception as exc:
        raise MaxioUnavailableError(f"Maxio returned an invalid {label}") from exc
    if cents < 0:
        raise MaxioUnavailableError(f"Maxio returned a negative {label}")
    return cents


def _assert_payment_profile_not_expired(profile: Mapping[str, Any]) -> None:
    month = _numeric_api_id(profile.get("expiration_month"))
    year = _numeric_api_id(profile.get("expiration_year"))
    if month is None or year is None:
        return
    if month > 12:
        raise MaxioUnavailableError("Maxio payment profile returned an invalid expiration month")
    now = datetime.now(timezone.utc)
    if (year, month) < (now.year, now.month):
        raise MaxioScopeError("payment_profile_id is expired")


def _missing_payment_profile_billing_address_fields(
    profile: Mapping[str, Any],
) -> list[str]:
    required = {
        "billing address": "billing_address",
        "billing city": "billing_city",
        "billing postal code": "billing_zip",
        "billing country": "billing_country",
    }
    missing = [
        label
        for label, field in required.items()
        if not str(profile.get(field) or "").strip()
    ]
    country = str(profile.get("billing_country") or "").strip().casefold()
    if country in {"us", "usa", "united states", "ca", "canada"} and not str(
        profile.get("billing_state") or ""
    ).strip():
        missing.append("billing state or province")
    return missing


def _provider_error_messages(body: Any) -> list[str]:
    if not isinstance(body, Mapping):
        return []
    values: list[Any] = []
    for field in ("errors", "error", "message"):
        value = body.get(field)
        if isinstance(value, list):
            values.extend(value)
        elif value is not None:
            values.append(value)
    messages: list[str] = []
    for value in values[:5]:
        clean = re.sub(r"\s+", " ", str(value or "")).strip()
        if clean:
            messages.append(clean[:500])
    return messages


def _subscription_creation_reference(ticket_number: str, customer_reference: str) -> str:
    safe_reference = re.sub(
        r"[^A-Za-z0-9_-]+",
        "-",
        str(customer_reference or "").strip(),
    ).strip("-_")
    value = f"nova-audit-{ticket_number}-{safe_reference}"[:100]
    if not safe_reference or len(value) < 8:
        raise MaxioScopeError("customer_reference cannot form a safe subscription reference")
    return value


def _required_integer_field(
    record: Mapping[str, Any],
    fields: tuple[str, ...],
    label: str,
) -> int:
    value: Any = None
    found = False
    for field in fields:
        if field in record and record.get(field) is not None:
            value = record.get(field)
            found = True
            break
    if not found:
        raise MaxioUnavailableError(f"Maxio response did not include {label}")
    try:
        clean = int(value)
    except (TypeError, ValueError) as exc:
        raise MaxioUnavailableError(f"Maxio response returned an invalid {label}") from exc
    if isinstance(value, bool):
        raise MaxioUnavailableError(f"Maxio response returned an invalid {label}")
    return clean


def _positive_id(value: int, name: str) -> int:
    try:
        clean = int(value)
    except (TypeError, ValueError) as exc:
        raise MaxioScopeError(f"{name} must be a positive integer") from exc
    if clean <= 0:
        raise MaxioScopeError(f"{name} must be a positive integer")
    return clean


def _exact_positive_id_list(value: Any, name: str, *, ceiling: int) -> list[int]:
    if not isinstance(value, list) or not value or len(value) > ceiling:
        raise MaxioScopeError(f"{name} must contain 1-{ceiling} exact positive integers")
    clean = [_positive_id(item, name) for item in value]
    if len(set(clean)) != len(clean):
        raise MaxioScopeError(f"{name} cannot contain duplicates")
    return sorted(clean)


def _phase_idempotency_key(base: str, phase: str) -> str:
    clean_base = _required_idempotency_key(base)
    clean_phase = str(phase or "").strip().casefold()
    if not re.fullmatch(r"[a-z0-9_-]{2,24}", clean_phase):
        raise MaxioScopeError("recovery phase must be one fixed safe value")
    candidate = f"{clean_base}-{clean_phase}"
    if len(candidate) <= 240:
        return candidate
    digest = hashlib.sha256(candidate.encode("utf-8")).hexdigest()[:16]
    return f"{clean_base[:198]}-{clean_phase}-{digest}"


def _bounded_text(value: str, name: str, limit: int) -> str:
    clean = str(value or "").strip()
    if not clean or len(clean) > limit or any(character in clean for character in "\r\n\0"):
        raise MaxioScopeError(f"{name} is required and must be at most {limit} characters")
    return clean


def _safe_api_path(value: str) -> str:
    clean = str(value or "").strip()
    if (
        not clean.startswith("/")
        or clean.startswith("//")
        or len(clean) > 500
        or not clean.endswith(".json")
        or ".." in clean
        or "://" in clean
        or any(character in clean for character in "\r\n\0?#")
    ):
        raise MaxioScopeError("path must be one absolute Maxio JSON API path without a query string")
    return clean


def _validate_mutation_path(
    path: str,
    *,
    json_body: Any = None,
    typed_financial_operation: str = "",
) -> None:
    parts = {part.casefold() for part in path.removesuffix(".json").split("/") if part}
    if parts & DESTRUCTIVE_PATH_PARTS:
        raise MaxioScopeError("record deletion and destructive Maxio operations are unavailable")
    if parts & PRIVILEGED_PATH_PARTS:
        raise MaxioScopeError(
            "Maxio permission, identity, credential, and site administration is unavailable"
        )
    if any(pattern.fullmatch(path) for pattern in ALWAYS_BLOCKED_FINANCIAL_MUTATION_PATHS):
        raise MaxioScopeError(
            "this financial path is unavailable; use the typed no-credit allocation and manual-credit tools"
        )
    if re.fullmatch(
        r"/subscriptions/[0-9]+/payment_profiles/[0-9]+/change_payment_profile\.json",
        path,
    ) and typed_financial_operation != "subscription_payment_profile_assignment":
        raise MaxioScopeError(
            "generic subscription payment-profile assignment is unavailable; use the "
            "typed payment-profile preview/apply operation"
        )
    if SUBSCRIPTION_UPDATE_PATH.fullmatch(path):
        subscription_body = (
            json_body.get("subscription")
            if isinstance(json_body, Mapping)
            else None
        )
        subscription_fields = (
            set(subscription_body)
            if isinstance(subscription_body, Mapping)
            else set()
        )
        changes_product = bool(subscription_fields & SUBSCRIPTION_PRODUCT_FIELDS)
        changes_payment_profile = "payment_profile_id" in subscription_fields
        if changes_product and typed_financial_operation != "subscription_product_change":
            raise MaxioScopeError(
                "generic subscription product changes are unavailable; use the typed product-change preview/apply operation"
            )
        if typed_financial_operation == "subscription_product_change" and subscription_fields != {"product_id"}:
            raise MaxioScopeError(
                "typed subscription product changes may set only subscription.product_id"
            )
        if typed_financial_operation == "subscription_no_charge_reactivation":
            if subscription_fields != {"next_billing_at"}:
                raise MaxioScopeError(
                    "typed no-charge reactivation billing alignment may set only "
                    "subscription.next_billing_at"
                )
        if changes_payment_profile:
            raise MaxioScopeError(
                "subscription.payment_profile_id is not a supported Maxio update field; "
                "use the typed payment-profile preview/apply operation"
            )
    for pattern, required_operation in TYPED_NONFINANCIAL_MUTATION_PATHS:
        if not pattern.fullmatch(path):
            continue
        if typed_financial_operation != required_operation:
            raise MaxioScopeError(
                "generic custom-field mutations are unavailable; use the typed location-mapping tools"
            )
        return
    for pattern, required_operation in FINANCIAL_MUTATION_PATHS:
        if not pattern.fullmatch(path):
            continue
        allowed_operations = (
            {required_operation}
            if isinstance(required_operation, str)
            else set(required_operation)
        )
        if typed_financial_operation not in allowed_operations:
            raise MaxioScopeError(
                "generic financial mutations are unavailable; use the matching typed preview/apply operation"
            )
        return


def _bounded_mapping(value: Mapping[str, Any], name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise MaxioScopeError(f"{name} must be an object")
    clean = dict(value)
    encoded = json.dumps(clean, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    if len(encoded) > MAX_REQUEST_BYTES:
        raise MaxioScopeError(f"{name} exceeded the bounded request limit")
    return clean


def _encoded_json(value: Any) -> bytes | None:
    if value is None:
        return None
    try:
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise MaxioScopeError("json_body must be JSON serializable") from exc
    if len(encoded) > MAX_REQUEST_BYTES:
        raise MaxioScopeError("json_body exceeded the bounded request limit")
    return encoded


def _bounded_rows(value: int, *, ceiling: int = 50) -> int:
    try:
        clean = int(value)
    except (TypeError, ValueError) as exc:
        raise MaxioScopeError("max_rows must be an integer") from exc
    return max(1, min(clean, ceiling))


def _positive_cents(value: Any, name: str) -> int:
    if isinstance(value, bool):
        raise MaxioScopeError(f"{name} must be a positive integer number of cents")
    try:
        clean = int(value)
    except (TypeError, ValueError) as exc:
        raise MaxioScopeError(f"{name} must be a positive integer number of cents") from exc
    if clean < 1 or clean > 100_000_000:
        raise MaxioScopeError(f"{name} must be between 1 and 100000000")
    return clean


def _nonnegative_cents(value: Any, name: str) -> int:
    if isinstance(value, bool):
        raise MaxioScopeError(f"{name} must be a non-negative integer number of cents")
    try:
        clean = int(value)
    except (TypeError, ValueError) as exc:
        raise MaxioScopeError(
            f"{name} must be a non-negative integer number of cents"
        ) from exc
    if clean < 0 or clean > 100_000_000:
        raise MaxioScopeError(f"{name} must be between 0 and 100000000")
    return clean


def _ticket_number(value: Any) -> str:
    clean = str(value or "").strip()
    if not TICKET_NUMBER.fullmatch(clean):
        raise MaxioScopeError("ticket_number must be 4-12 digits")
    return clean


def _coupon_code(value: Any) -> str:
    clean = str(value or "").strip()
    if not COUPON_CODE.fullmatch(clean):
        raise MaxioScopeError(
            "coupon_code must be 1-100 letters, numbers, or approved coupon punctuation"
        )
    return clean


def _required_idempotency_key(value: Any) -> str:
    clean = str(value or "").strip()
    if not IDEMPOTENCY_KEY.fullmatch(clean):
        raise MaxioScopeError("mutations require an idempotency_key of 8-240 safe characters")
    return clean


def _required_preview_hash(value: Any, expected: str) -> str:
    clean = str(value or "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", clean) or clean != expected:
        raise MaxioScopeError("preview_hash does not match the current verified financial state")
    return clean


def _api_request_hash(
    method: str,
    path: str,
    params: Mapping[str, Any],
    body: Any,
) -> str:
    return hashlib.sha256(
        json.dumps(
            {
                "method": method,
                "path": path,
                "params": dict(params),
                "body": body,
            },
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()


def _plan_hash(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(dict(value), sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _currency_amount(amount_cents: int) -> str:
    return f"{Decimal(int(amount_cents)) / Decimal(100):.2f}"


def _bounded_positive_count(value: Any, name: str, ceiling: int) -> int:
    if isinstance(value, bool):
        raise MaxioScopeError(f"{name} must be a positive integer")
    try:
        clean = int(value)
    except (TypeError, ValueError) as exc:
        raise MaxioScopeError(f"{name} must be a positive integer") from exc
    if clean < 1 or clean > ceiling:
        raise MaxioScopeError(f"{name} must be between 1 and {ceiling}")
    return clean


def _required_api_date(value: Any, label: str) -> str:
    clean = str(value or "").strip()
    if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", clean):
        if "T" in clean:
            clean = clean.split("T", 1)[0]
        elif " " in clean:
            clean = clean.split(" ", 1)[0]
    try:
        parsed = date.fromisoformat(clean)
    except ValueError as exc:
        raise MaxioScopeError(f"{label} must be a valid YYYY-MM-DD date") from exc
    return parsed.isoformat()


def _all_balances_zero(balances: Mapping[str, Any]) -> bool:
    try:
        return bool(balances) and all(int(value) == 0 for value in balances.values())
    except (TypeError, ValueError):
        return False


def _account_balances(payload: Any) -> dict[str, int]:
    if not isinstance(payload, Mapping):
        raise MaxioUnavailableError("Maxio account-balance response had an unexpected shape")
    fields = {
        "openInvoiceBalanceCents": "open_invoices",
        "pendingInvoiceBalanceCents": "pending_invoices",
        "pendingDiscountBalanceCents": "pending_discounts",
        "serviceCreditBalanceCents": "service_credits",
        "prepaymentBalanceCents": "prepayments",
    }
    balances: dict[str, int] = {}
    for output_name, source_name in fields.items():
        source = payload.get(source_name)
        if not isinstance(source, Mapping):
            raise MaxioUnavailableError(
                f"Maxio account-balance response omitted {source_name}"
            )
        balances[output_name] = _required_integer_field(
            source,
            ("balance_in_cents",),
            source_name.replace("_", " "),
        )
    return balances


def _allocation_preview_total_cents(payload: Any) -> int:
    if not isinstance(payload, Mapping):
        raise MaxioUnavailableError(
            "Maxio allocation preview did not return a verifiable total"
        )
    candidates: list[Mapping[str, Any]] = [payload]
    for key in ("allocation_preview", "preview"):
        nested = payload.get(key)
        if isinstance(nested, Mapping):
            candidates.insert(0, nested)
    for candidate in candidates:
        for key in ("total_in_cents", "total_amount_in_cents", "amount_in_cents"):
            if candidate.get(key) is None:
                continue
            try:
                total = int(candidate[key])
            except (TypeError, ValueError) as exc:
                raise MaxioUnavailableError(
                    "Maxio allocation preview returned an invalid total"
                ) from exc
            if total < 0:
                raise MaxioUnavailableError(
                    "Maxio allocation preview returned a negative total"
                )
            return total
    raise MaxioUnavailableError(
        "Maxio allocation preview omitted its exact total in cents"
    )


def _verified_location_metadata(values: Any) -> dict[str, Any]:
    if not isinstance(values, Mapping):
        raise MaxioUnavailableError("Maxio location metadata values had an unexpected shape")
    missing = sorted(set(LOCATION_CUSTOM_FIELD_NAMES) - set(values))
    if missing:
        raise MaxioScopeError(
            f"subscription location metadata is incomplete: {missing}"
        )
    raw_ids = [token.strip() for token in str(values["Locations"]).split(",")]
    try:
        location_ids = [_positive_id(token, "location metadata ID") for token in raw_ids]
    except MaxioScopeError:
        raise
    if len(set(location_ids)) != len(location_ids) or not location_ids:
        raise MaxioScopeError("subscription location metadata contains duplicate or missing IDs")
    try:
        raw_component_map = json.loads(str(values["LocationComponentMap"]))
        raw_name_map = json.loads(str(values["LocationNameMap"]))
    except (TypeError, ValueError) as exc:
        raise MaxioScopeError("subscription location maps are not valid JSON") from exc
    if not isinstance(raw_component_map, Mapping) or not isinstance(raw_name_map, Mapping):
        raise MaxioScopeError("subscription location maps must be JSON objects")
    expected_keys = {str(location_id) for location_id in location_ids}
    if set(raw_component_map) != expected_keys or set(raw_name_map) != expected_keys:
        raise MaxioScopeError(
            "subscription location IDs, component map, and name map do not match exactly"
        )
    component_map = {
        str(key): _positive_id(value, "location component ID")
        for key, value in raw_component_map.items()
    }
    if any(not str(value or "").strip() for value in raw_name_map.values()):
        raise MaxioScopeError("subscription location name map contains an empty name")
    expected_display = ", ".join(str(raw_name_map[str(value)]).strip() for value in location_ids)
    if str(values["LocationNamesDisplay"]).strip() != expected_display:
        raise MaxioScopeError(
            "subscription location display names do not match the location name map"
        )
    return {
        "locationIds": sorted(location_ids),
        "componentMap": component_map,
    }


def _transaction_records(payload: Any) -> list[dict[str, Any]]:
    records = _wrapped_records(payload, "transaction")
    transactions: list[dict[str, Any]] = []
    for record in records:
        transaction_id = _numeric_api_id(record.get("id"))
        if transaction_id is None:
            continue
        amount = record.get("amount_in_cents")
        try:
            amount_cents = int(amount)
        except (TypeError, ValueError):
            continue
        transactions.append(
            {
                "id": transaction_id,
                "transactionType": str(
                    record.get("transaction_type") or record.get("type") or ""
                ).strip().casefold(),
                "success": bool(record.get("success")),
                "amountCents": amount_cents,
                "memo": str(record.get("memo") or ""),
                "paymentId": _numeric_api_id(record.get("payment_id")),
                "createdAt": str(record.get("created_at") or ""),
            }
        )
    return transactions


def _successful_collection_evidence(
    charge: Mapping[str, Any],
    transactions: list[dict[str, Any]],
) -> dict[str, Any] | None:
    payment_id = _numeric_api_id(charge.get("paymentId"))
    if payment_id is None:
        return None
    payments = [
        row
        for row in transactions
        if row["id"] == payment_id
        and row["transactionType"] == "payment"
        and row["amountCents"] == int(charge["amountCents"])
        and row["success"]
    ]
    if len(payments) != 1:
        return None
    return {"charge": dict(charge), "payment": payments[0]}


def _allocation_targets(value: list[dict[str, Any]]) -> list[dict[str, int]]:
    if not isinstance(value, list) or not value or len(value) > 50:
        raise MaxioScopeError("allocations must contain 1-50 component targets")
    targets: list[dict[str, int]] = []
    seen: set[int] = set()
    for row in value:
        if not isinstance(row, Mapping) or set(row) != {"component_id", "quantity"}:
            raise MaxioScopeError("each allocation must contain only component_id and quantity")
        component_id = _positive_id(row["component_id"], "component_id")
        try:
            quantity = int(row["quantity"])
        except (TypeError, ValueError) as exc:
            raise MaxioScopeError("allocation quantity must be a non-negative integer") from exc
        if isinstance(row["quantity"], bool) or quantity < 0 or quantity > 100_000:
            raise MaxioScopeError("allocation quantity must be between 0 and 100000")
        if component_id in seen:
            raise MaxioScopeError("component_id may appear only once per allocation plan")
        seen.add(component_id)
        targets.append({"componentId": component_id, "desiredQuantity": quantity})
    return sorted(targets, key=lambda item: item["componentId"])


def _allocation_direction(changes: list[dict[str, int]]) -> str:
    directions = {
        "upgrade" if row["desiredQuantity"] > row["currentQuantity"] else "downgrade"
        for row in changes
        if row["desiredQuantity"] != row["currentQuantity"]
    }
    if not directions:
        return "unchanged"
    if len(directions) == 1:
        return next(iter(directions))
    return "mixed"


def _component_deallocation_summary(
    payload: Any,
    *,
    desired_quantities: Mapping[int, int] | None = None,
) -> dict[str, Any]:
    if not isinstance(payload, list):
        raise MaxioUnavailableError("Maxio component response had an unexpected shape")
    deallocations: list[dict[str, Any]] = []
    counts = {"location": 0, "storage": 0, "other": 0}
    seen_component_ids: set[int] = set()
    for raw in payload:
        if not isinstance(raw, Mapping):
            raise MaxioUnavailableError(
                "Maxio component inventory contained a malformed row"
            )
        allocation = (
            raw.get("allocation")
            if isinstance(raw.get("allocation"), Mapping)
            else {}
        )
        component = (
            raw.get("component")
            if isinstance(raw.get("component"), Mapping)
            else {}
        )
        component_value = raw.get("component_id")
        if component_value is None:
            component_value = allocation.get("component_id")
        if component_value is None:
            component_value = component.get("component_id")
        if component_value is None:
            component_value = component.get("id")
        quantity_value = raw.get("allocated_quantity")
        if quantity_value is None:
            quantity_value = allocation.get("quantity")
        if quantity_value is None:
            quantity_value = raw.get("quantity")
        if quantity_value is None:
            quantity_value = component.get("allocated_quantity")
        try:
            component_id = int(component_value)
            current_quantity = int(quantity_value)
        except (TypeError, ValueError) as exc:
            raise MaxioUnavailableError(
                "Maxio component inventory omitted an exact component ID or quantity"
            ) from exc
        if component_id <= 0 or current_quantity < 0:
            raise MaxioUnavailableError(
                "Maxio component inventory contained an invalid component ID or quantity"
            )
        if component_id in seen_component_ids:
            raise MaxioUnavailableError(
                "Maxio component inventory contained a duplicate component ID"
            )
        seen_component_ids.add(component_id)
        desired_quantity = (
            int(desired_quantities.get(component_id, current_quantity))
            if desired_quantities is not None
            else 0
        )
        if desired_quantity < 0:
            raise MaxioUnavailableError(
                "Maxio component deallocation plan contained a negative desired quantity"
            )
        deallocated_quantity = max(current_quantity - desired_quantity, 0)
        if deallocated_quantity == 0:
            continue
        name = str(component.get("name") or raw.get("name") or "").strip()
        unit_name = str(
            component.get("unit_name") or raw.get("unit_name") or ""
        ).strip()
        if not name and not unit_name:
            raise MaxioUnavailableError(
                "Maxio component inventory omitted the component name needed for "
                "location classification"
            )
        category = _component_billing_category(name, unit_name)
        counts[category] += deallocated_quantity
        deallocations.append(
            {
                "componentId": component_id,
                "componentName": name,
                "unitName": unit_name,
                "category": category,
                "currentQuantity": current_quantity,
                "desiredQuantity": desired_quantity,
                "deallocatedQuantity": deallocated_quantity,
            }
        )
    return {
        "locationComponentDeallocationCount": counts["location"],
        "storageComponentDeallocationCount": counts["storage"],
        "otherComponentDeallocationCount": counts["other"],
        "componentInventoryComplete": True,
        "componentDeallocations": sorted(
            deallocations,
            key=lambda row: int(row["componentId"]),
        ),
    }


def _component_billing_category(name: str, unit_name: str) -> str:
    normalized = " ".join(
        part for part in (str(name or "").casefold(), str(unit_name or "").casefold()) if part
    )
    if re.search(r"\bstorages?\b", normalized):
        return "storage"
    if re.search(r"\blocations?\b", normalized):
        return "location"
    return "other"


def _component_quantities(payload: Any) -> dict[int, int]:
    if not isinstance(payload, list):
        raise MaxioUnavailableError("Maxio component response had an unexpected shape")
    quantities: dict[int, int] = {}
    for raw in payload:
        if not isinstance(raw, Mapping):
            continue
        allocation = raw.get("allocation") if isinstance(raw.get("allocation"), Mapping) else {}
        component = raw.get("component") if isinstance(raw.get("component"), Mapping) else {}
        component_value = raw.get("component_id")
        if component_value is None:
            component_value = allocation.get("component_id")
        if component_value is None:
            component_value = component.get("component_id")
        if component_value is None:
            component_value = component.get("id")
        quantity_value = raw.get("allocated_quantity")
        if quantity_value is None:
            quantity_value = allocation.get("quantity")
        if quantity_value is None:
            quantity_value = raw.get("quantity")
        if quantity_value is None:
            quantity_value = component.get("allocated_quantity")
        try:
            component_id = int(component_value)
            quantity = int(quantity_value)
        except (TypeError, ValueError):
            continue
        if component_id > 0 and quantity >= 0:
            quantities[component_id] = quantity
    if not quantities:
        raise MaxioUnavailableError("Maxio component response contained no usable component allocations")
    return quantities


def _metafield_records(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        raw_records = payload
    elif isinstance(payload, Mapping):
        raw = payload.get("metafields")
        raw_records = raw if isinstance(raw, list) else []
    else:
        raise MaxioUnavailableError("Maxio metafield response had an unexpected shape")
    records: list[dict[str, Any]] = []
    for raw in raw_records[:200]:
        if not isinstance(raw, Mapping):
            continue
        nested = raw.get("metafield")
        record = dict(nested) if isinstance(nested, Mapping) else dict(raw)
        name = str(record.get("name") or "").strip()
        if name:
            record["name"] = name
            records.append(record)
    return records


def _metadata_records(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        raw_records = payload
    elif isinstance(payload, Mapping):
        raw = payload.get("metadata")
        raw_records = raw if isinstance(raw, list) else []
    else:
        raise MaxioUnavailableError("Maxio metadata response had an unexpected shape")
    records: list[dict[str, Any]] = []
    for raw in raw_records[:200]:
        if not isinstance(raw, Mapping):
            continue
        nested = raw.get("metadata")
        record = dict(nested) if isinstance(nested, Mapping) else dict(raw)
        if record.get("deleted_at"):
            continue
        name = str(record.get("name") or "").strip()
        if name:
            record["name"] = name
            record["value"] = str(record.get("value") or "")
            records.append(record)
    return records


def _unique_metadata_values(records: list[dict[str, Any]]) -> dict[str, str]:
    values: dict[str, str] = {}
    for record in records:
        name = str(record.get("name") or "")
        value = str(record.get("value") or "")
        if name in values and values[name] != value:
            raise MaxioScopeError(
                f"subscription has multiple active metadata values for {name}; resolve duplicates first"
            )
        values[name] = value
    return values


def _location_mapping_rows(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not value or len(value) > 500:
        raise MaxioScopeError("locations must contain 1-500 exact mapping rows")
    rows: list[dict[str, Any]] = []
    seen: set[int] = set()
    for raw in value:
        if not isinstance(raw, Mapping):
            raise MaxioScopeError("each location mapping must be an object")
        if set(raw) != {"location_id", "location_name", "component_id"}:
            raise MaxioScopeError(
                "each location mapping must contain only location_id, location_name, and component_id"
            )
        location_id = _positive_id(raw.get("location_id"), "location_id")
        component_id = _positive_id(raw.get("component_id"), "component_id")
        location_name = _bounded_text(str(raw.get("location_name") or ""), "location_name", 255)
        if location_id in seen:
            raise MaxioScopeError("location_id may appear only once in a mapping")
        seen.add(location_id)
        rows.append(
            {
                "locationId": location_id,
                "locationName": location_name,
                "componentId": component_id,
            }
        )
    return sorted(rows, key=lambda row: (row["locationId"], row["componentId"]))


def _location_metadata_values(rows: list[dict[str, Any]]) -> dict[str, str]:
    component_map = {
        str(row["locationId"]): row["componentId"]
        for row in rows
    }
    name_map = {
        str(row["locationId"]): row["locationName"]
        for row in rows
    }
    values = {
        "Locations": ",".join(str(row["locationId"]) for row in rows),
        "LocationComponentMap": json.dumps(
            component_map,
            sort_keys=True,
            separators=(",", ":"),
        ),
        "LocationNameMap": json.dumps(
            name_map,
            sort_keys=True,
            separators=(",", ":"),
        ),
        "LocationNamesDisplay": ", ".join(row["locationName"] for row in rows),
    }
    if any(len(value.encode("utf-8")) > 100_000 for value in values.values()):
        raise MaxioScopeError("location metadata exceeded the bounded value limit")
    return values


def _collection(payload: Any, *, max_rows: int, operation: str) -> dict[str, Any]:
    if not isinstance(payload, list):
        raise MaxioUnavailableError("Maxio collection response had an unexpected shape")
    records = payload[:max_rows]
    return {
        "ok": True,
        "operation": operation,
        "records": records,
        "returned": len(records),
        "truncated": len(payload) > len(records),
    }
