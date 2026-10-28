from __future__ import annotations

# AgentChat/coding_agent 2026-08-05T21:27:50Z

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from scoped_operations_mcp.maxio_client import (
    MaxioScopeError,
    MaxioSettings,
    MaxioUnavailableError,
    ScopedMaxioClient,
)
from scoped_operations_mcp.maxio_server import build_mcp


class FakeResponse:
    def __init__(self, payload, *, status_code: int = 200) -> None:
        self.payload = payload
        self.status_code = status_code
        self.content = b"" if payload is None else json.dumps(payload).encode("utf-8")

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError("request failed")

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, payload) -> None:
        self.payload = payload
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append(("GET", url, kwargs))
        return FakeResponse(self.payload)

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return FakeResponse(self.payload)


class AllocationSession:
    def __init__(self) -> None:
        self.quantities = {85644: 1, 85645: 0}
        self.calls = []

    def _components(self):
        return [
            {
                "component": {"id": component_id, "name": f"Location {component_id}"},
                "component_id": component_id,
                "allocated_quantity": quantity,
            }
            for component_id, quantity in sorted(self.quantities.items())
        ]

    def get(self, url, **kwargs):
        self.calls.append(("GET", url, kwargs))
        if url.endswith("/components.json"):
            return FakeResponse(self._components())
        raise AssertionError(url)

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        if url.endswith("/allocations/preview.json"):
            return FakeResponse({"allocation_preview": {"total_in_cents": 0}})
        if url.endswith("/allocations.json"):
            for row in kwargs["json"]["allocations"]:
                self.quantities[int(row["component_id"])] = int(row["quantity"])
            return FakeResponse({"ok": True})
        raise AssertionError(url)


class LocationMetadataSession:
    def __init__(self) -> None:
        self.calls = []
        self.definitions = []
        self.metadata = {}
        self.quantities = {85644: 2}

    def get(self, url, **kwargs):
        self.calls.append(("GET", url, kwargs))
        if url.endswith("/subscriptions/metafields.json"):
            return FakeResponse({"metafields": list(self.definitions)})
        if url.endswith("/subscriptions/77/metadata.json"):
            return FakeResponse(
                {
                    "metadata": [
                        {"id": index, "name": name, "value": value}
                        for index, (name, value) in enumerate(
                            sorted(self.metadata.items()),
                            start=1,
                        )
                    ]
                }
            )
        if url.endswith("/subscriptions/77/components.json"):
            return FakeResponse(
                [
                    {
                        "component": {"id": component_id, "name": "Location"},
                        "allocated_quantity": quantity,
                    }
                    for component_id, quantity in self.quantities.items()
                ]
            )
        raise AssertionError(url)

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        if method == "POST" and url.endswith("/subscriptions/metafields.json"):
            rows = kwargs["json"]["metafields"]
            self.definitions.extend(dict(row) for row in rows)
            return FakeResponse(rows)
        if method == "POST" and url.endswith("/subscriptions/77/metadata.json"):
            row = kwargs["json"]["metadata"]
            self.metadata[str(row["name"])] = str(row["value"])
            return FakeResponse({"metadata": dict(row)})
        raise AssertionError((method, url))


class CancellationSession:
    def __init__(self, *, balance_in_cents: int = 0) -> None:
        self.calls = []
        self.component_quantities = {
            85644: 1,
            85731: 17,
            862616: 2,
        }
        self.subscription = {
            "id": 77,
            "state": "active",
            "balance_in_cents": balance_in_cents,
            "updated_at": "2026-07-23T12:00:00-04:00",
            "canceled_at": None,
            "cancellation_message": None,
            "cancel_at_end_of_period": False,
            "delayed_cancel_at": None,
            "next_assessment_at": "2026-08-06T12:00:00-04:00",
            "customer": {
                "id": 9945500,
                "reference": "LEJAIM_SPA",
                "organization": "LEJAIM SPA",
            },
            "product": {"id": 12, "name": "Nova POS", "handle": "nova-pos"},
        }

    def get(self, url, **kwargs):
        self.calls.append(("GET", url, kwargs))
        if url.endswith("/subscriptions/77.json"):
            return FakeResponse({"subscription": dict(self.subscription)})
        if url.endswith("/subscriptions/77/components.json"):
            definitions = {
                85644: ("$129.99 Location", "$129.99 location"),
                85731: ("Storage", "storage"),
                862616: ("$50 API Access", "$50 API Access"),
            }
            return FakeResponse(
                [
                    {
                        "component": {
                            "component_id": component_id,
                            "name": definitions[component_id][0],
                            "unit_name": definitions[component_id][1],
                            "allocated_quantity": quantity,
                        }
                    }
                    for component_id, quantity in sorted(
                        self.component_quantities.items()
                    )
                ]
            )
        raise AssertionError(url)

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        if method == "DELETE" and url.endswith("/subscriptions/77.json"):
            self.subscription.update(
                {
                    "state": "canceled",
                    "updated_at": "2026-07-23T13:30:00-04:00",
                    "canceled_at": "2026-07-23T13:30:00-04:00",
                    "cancellation_message": kwargs["json"]["subscription"]["cancellation_message"],
                }
            )
            self.component_quantities = {
                component_id: 0 for component_id in self.component_quantities
            }
            return FakeResponse({"subscription": dict(self.subscription)})
        raise AssertionError((method, url))


# AgentChat/coding_agent 2026-08-07T13:31:00Z
class PastDueCancellationSession(CancellationSession):
    def __init__(self, *, change_invoice_on_cancel: bool = False) -> None:
        super().__init__(balance_in_cents=11_999)
        self.subscription["state"] = "past_due"
        self.change_invoice_on_cancel = change_invoice_on_cancel
        self.invoice = {
            "uid": "inv_347667",
            "number": "INV-347667",
            "subscription_id": 77,
            "status": "open",
            "due_amount": "119.99",
            "total_amount": "119.99",
        }

    def get(self, url, **kwargs):
        self.calls.append(("GET", url, kwargs))
        if url.endswith("/subscriptions/77.json"):
            return FakeResponse({"subscription": dict(self.subscription)})
        if url.endswith("/subscriptions/77/components.json"):
            definitions = {
                85644: ("$129.99 Location", "$129.99 location"),
                85731: ("Storage", "storage"),
                862616: ("$50 API Access", "$50 API Access"),
            }
            return FakeResponse(
                [
                    {
                        "component": {
                            "component_id": component_id,
                            "name": definitions[component_id][0],
                            "unit_name": definitions[component_id][1],
                            "allocated_quantity": quantity,
                        }
                    }
                    for component_id, quantity in sorted(
                        self.component_quantities.items()
                    )
                ]
            )
        if url.endswith("/subscriptions/77/account_balances.json"):
            return FakeResponse(
                {
                    "open_invoices": {"balance_in_cents": 11_999},
                    "pending_invoices": {"balance_in_cents": 0},
                    "pending_discounts": {"balance_in_cents": 0},
                    "service_credits": {"balance_in_cents": 0},
                    "prepayments": {"balance_in_cents": 0},
                }
            )
        if url.endswith("/invoices.json"):
            assert kwargs["params"] == {
                "subscription_id": 77,
                "customer_ids": 9945500,
                "page": 1,
                "per_page": 200,
            }
            return FakeResponse({"invoices": [{"invoice": dict(self.invoice)}]})
        raise AssertionError(url)

    def request(self, method, url, **kwargs):
        response = super().request(method, url, **kwargs)
        if self.change_invoice_on_cancel:
            self.invoice["status"] = "voided"
            self.invoice["due_amount"] = "0.00"
        return response


class SubscriptionCreationSession:
    def __init__(self) -> None:
        self.calls = []
        self.created = None
        self.expiration_year = datetime.now(timezone.utc).year + 3

    def get(self, url, **kwargs):
        self.calls.append(("GET", url, kwargs))
        if url.endswith("/customers/9001.json"):
            return FakeResponse(
                {"customer": {"id": 9001, "reference": "A-1567396", "organization": "Soleil SLP"}}
            )
        if url.endswith("/payment_profiles.json"):
            return FakeResponse(
                [
                    {
                        "payment_profile": {
                            "id": 7001,
                            "customer_id": 9001,
                            "payment_type": "credit_card",
                            "expiration_month": 12,
                            "expiration_year": self.expiration_year,
                        }
                    }
                ]
            )
        if url.endswith("/products/3655664.json"):
            return FakeResponse(
                {
                    "product": {
                        "id": 3655664,
                        "name": "Nova Basic Monthly",
                        "handle": "basic",
                        "interval": 1,
                        "interval_unit": "month",
                        "archived_at": None,
                    }
                }
            )
        if url.endswith("/components/85654.json"):
            return FakeResponse(
                {
                    "component": {
                        "id": 85654,
                        "name": "$139.99 Location",
                        "unit_price": "139.99",
                        "archived_at": None,
                    }
                }
            )
        if url.endswith("/subscriptions.json"):
            return FakeResponse([] if self.created is None else [dict(self.created)])
        if url.endswith("/subscriptions/8801.json"):
            return FakeResponse({"subscription": dict(self.created)})
        if url.endswith("/subscriptions/8801/components.json"):
            return FakeResponse(
                [
                    {
                        "component": {"id": 85654, "name": "$139.99 Location"},
                        "allocated_quantity": 1,
                    }
                ]
            )
        if url.endswith("/subscriptions/8801/account_balances.json"):
            return FakeResponse(
                {
                    "open_invoices": {"balance_in_cents": 0},
                    "pending_invoices": {"balance_in_cents": 0},
                    "pending_discounts": {"balance_in_cents": 0},
                    "service_credits": {"balance_in_cents": 0},
                    "prepayments": {"balance_in_cents": 0},
                }
            )
        raise AssertionError(url)

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        if method == "POST" and url.endswith("/subscriptions.json"):
            payload = kwargs["json"]["subscription"]
            self.created = {
                "id": 8801,
                "state": "active",
                "reference": payload["reference"],
                "next_assessment_at": payload["next_billing_at"],
                "customer": {"id": payload["customer_id"]},
                "product": {"id": payload["product_id"]},
                "payment_profile": {"id": payload["payment_profile_id"]},
            }
            return FakeResponse({"subscription": dict(self.created)}, status_code=201)
        raise AssertionError((method, url))


class PaymentReactivationSession:
    def __init__(
        self,
        *,
        current_profile_id: int = 7001,
        decline: bool = False,
        omit_collection: bool = False,
        reject_change_without_current: bool = False,
    ) -> None:
        self.calls = []
        self.decline = decline
        self.omit_collection = omit_collection
        self.reject_change_without_current = reject_change_without_current
        self.transactions = [
            {
                "transaction": {
                    "id": 600,
                    "subscription_id": 77,
                    "transaction_type": "payment",
                    "success": True,
                    "amount_in_cents": 12_999,
                    "memo": "Prior billing cycle",
                    "created_at": "2026-07-03T09:00:00-04:00",
                }
            }
        ]
        self.subscription = {
            "id": 77,
            "state": "canceled",
            "balance_in_cents": 0,
            "current_billing_amount_in_cents": 12_999,
            "snap_day": None,
            "customer": {
                "id": 9001,
                "email": "billing@example.com",
                "reference": "A-1567396",
            },
            "payment_profile": {"id": current_profile_id},
        }
        expiration_year = datetime.now(timezone.utc).year + 3
        self.profiles = [
            {
                "payment_profile": {
                    "id": profile_id,
                    "customer_id": 9001,
                    "payment_type": "credit_card",
                    "masked_card_number": f"XXXX-XXXX-XXXX-{profile_id % 10000:04d}",
                    "expiration_month": 12,
                    "expiration_year": expiration_year,
                    "disabled": False,
                }
            }
            for profile_id in (7001, 7002)
        ]

    def get(self, url, **kwargs):
        self.calls.append(("GET", url, kwargs))
        if url.endswith("/subscriptions/77.json"):
            return FakeResponse({"subscription": dict(self.subscription)})
        if url.endswith("/payment_profiles.json"):
            return FakeResponse(list(self.profiles))
        if url.endswith("/subscriptions/77/transactions.json"):
            return FakeResponse(list(reversed(self.transactions)))
        if url.endswith("/subscriptions/77/account_balances.json"):
            return FakeResponse(
                {
                    "open_invoices": {"balance_in_cents": 0},
                    "pending_invoices": {"balance_in_cents": 0},
                    "pending_discounts": {"balance_in_cents": 0},
                    "service_credits": {"balance_in_cents": 0},
                    "prepayments": {"balance_in_cents": 0},
                }
            )
        raise AssertionError(url)

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        if method == "POST" and url.endswith(
            "/subscriptions/77/payment_profiles/7002/change_payment_profile.json"
        ):
            if (
                self.reject_change_without_current
                and not self.subscription.get("payment_profile")
            ):
                return FakeResponse(
                    {"errors": ["A current payment profile is required"]},
                    status_code=422,
                )
            self.subscription["payment_profile"] = {"id": 7002}
            return FakeResponse(self.profiles[1], status_code=201)
        if method == "PUT" and url.endswith("/subscriptions/77.json"):
            payment_profile_id = kwargs["json"]["subscription"]["payment_profile_id"]
            self.subscription["payment_profile"] = {"id": payment_profile_id}
            return FakeResponse(
                {"subscription": dict(self.subscription)},
                status_code=200,
            )
        if method == "POST" and url.endswith(
            "/subscriptions/77/request_payment_profiles_update.json"
        ):
            return FakeResponse(None, status_code=201)
        if method == "PUT" and url.endswith("/subscriptions/77/reactivate.json"):
            self.subscription["state"] = "active"
            self.subscription["canceled_at"] = None
            if self.decline:
                self.transactions.append(
                    {
                        "transaction": {
                            "id": 702,
                            "subscription_id": 77,
                            "transaction_type": "payment",
                            "success": False,
                            "amount_in_cents": 12_999,
                            "memo": "Reactivation payment",
                            "created_at": "2026-08-03T19:30:00-04:00",
                        }
                    }
                )
                return FakeResponse({"errors": ["payment declined"]}, status_code=422)
            if not self.omit_collection:
                self.transactions.extend(
                    [
                        {
                            "transaction": {
                                "id": 701,
                                "subscription_id": 77,
                                "transaction_type": "charge",
                                "success": True,
                                "amount_in_cents": 12_999,
                                "payment_id": 702,
                                "memo": "Reactivation charge",
                                "created_at": "2026-08-03T19:30:00-04:00",
                            }
                        },
                        {
                            "transaction": {
                                "id": 702,
                                "subscription_id": 77,
                                "transaction_type": "payment",
                                "success": True,
                                "amount_in_cents": 12_999,
                                "memo": "Reactivation payment",
                                "created_at": "2026-08-03T19:30:01-04:00",
                            }
                        },
                    ]
                )
            return FakeResponse({"subscription": dict(self.subscription)})
        if method == "DELETE" and url.endswith("/subscriptions/77.json"):
            self.subscription["state"] = "canceled"
            self.subscription["canceled_at"] = "2026-08-03T19:31:00-04:00"
            return FakeResponse({"subscription": dict(self.subscription)})
        raise AssertionError((method, url))


class NoChargeReactivationSession:
    def __init__(self) -> None:
        self.calls = []
        self.service_credit_balance_in_cents = 0
        self.subscription = {
            "id": 77,
            "state": "canceled",
            "balance_in_cents": 0,
            "current_billing_amount_in_cents": 13_999,
            "next_assessment_at": "2026-08-01T12:00:00+00:00",
            "customer": {"id": 9001, "reference": "REPAIR_IT"},
        }

    def _balances(self):
        return {
            "open_invoices": {"balance_in_cents": 0},
            "pending_invoices": {"balance_in_cents": 0},
            "pending_discounts": {"balance_in_cents": 0},
            "service_credits": {
                "balance_in_cents": self.service_credit_balance_in_cents
            },
            "prepayments": {"balance_in_cents": 0},
        }

    def get(self, url, **kwargs):
        self.calls.append(("GET", url, kwargs))
        if url.endswith("/subscriptions/77.json"):
            return FakeResponse({"subscription": dict(self.subscription)})
        if url.endswith("/subscriptions/77/account_balances.json"):
            return FakeResponse(self._balances())
        if url.endswith("/subscriptions/77/transactions.json"):
            return FakeResponse([])
        raise AssertionError(url)

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        if method == "POST" and url.endswith(
            "/subscriptions/77/service_credits.json"
        ):
            amount = int(
                round(float(kwargs["json"]["service_credit"]["amount"]) * 100)
            )
            self.service_credit_balance_in_cents += amount
            return FakeResponse({"id": 801, "amount_in_cents": amount}, status_code=201)
        if method == "PUT" and url.endswith("/subscriptions/77/reactivate.json"):
            assert kwargs["json"] == {
                "resume": False,
                "preserve_balance": False,
                "include_trial": False,
                "use_credits_and_prepayments": True,
            }
            self.subscription["state"] = "active"
            self.service_credit_balance_in_cents = 0
            return FakeResponse({"subscription": dict(self.subscription)})
        if method == "PUT" and url.endswith("/subscriptions/77.json"):
            self.subscription["next_assessment_at"] = kwargs["json"]["subscription"][
                "next_billing_at"
            ]
            return FakeResponse({"subscription": dict(self.subscription)})
        raise AssertionError((method, url))


class FinancialWorkflowSession:
    def __init__(self) -> None:
        self.calls = []
        self.service_credit_balance_in_cents = 0

    def _balances(self):
        return {
            "open_invoices": {"balance_in_cents": 100_000},
            "pending_invoices": {"balance_in_cents": 0},
            "pending_discounts": {"balance_in_cents": 0},
            "service_credits": {"balance_in_cents": self.service_credit_balance_in_cents},
            "prepayments": {"balance_in_cents": 0},
        }

    def get(self, url, **kwargs):
        self.calls.append(("GET", url, kwargs))
        if url.endswith("/subscriptions/77/account_balances.json"):
            return FakeResponse(self._balances())
        raise AssertionError(url)

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        if method == "POST" and url.endswith("/subscriptions/77/service_credits.json"):
            amount = int(round(float(kwargs["json"]["service_credit"]["amount"]) * 100))
            self.service_credit_balance_in_cents += amount
            return FakeResponse(
                {
                    "id": 101,
                    "amount_in_cents": amount,
                    "ending_balance_in_cents": self.service_credit_balance_in_cents,
                },
                status_code=201,
            )
        raise AssertionError((method, url))


class NovaIntegratedPromoSession:
    def __init__(self) -> None:
        self.calls = []
        self.service_credit_balance_in_cents = 0
        self.service_credits = []
        self.subscription = {
            "id": 77,
            "state": "active",
            "product": {
                "id": 4922746,
                "name": "Nova Integrated Worldpay",
                "handle": "nova-integrated-worldpay",
                "product_family": {"id": 4, "name": "Nova POS"},
            },
        }

    def _balances(self):
        return {
            "open_invoices": {"balance_in_cents": 0},
            "pending_invoices": {"balance_in_cents": 0},
            "pending_discounts": {"balance_in_cents": 0},
            "service_credits": {
                "balance_in_cents": self.service_credit_balance_in_cents
            },
            "prepayments": {"balance_in_cents": 0},
        }

    def get(self, url, **kwargs):
        self.calls.append(("GET", url, kwargs))
        if url.endswith("/products.json"):
            return FakeResponse(
                [
                    {
                        "product": {
                            "id": 4922746,
                            "name": "Nova Integrated Worldpay",
                            "handle": "nova-integrated-worldpay",
                            "price_in_cents": 0,
                            "interval": 1,
                            "interval_unit": "month",
                        }
                    },
                    {
                        "product": {
                            "id": 4922747,
                            "name": "Nova Integrated CreditCall",
                            "handle": "nova-integrated-creditcall",
                            "price_in_cents": 0,
                        }
                    },
                    {
                        "product": {
                            "id": 4922748,
                            "name": "Nova Integrated Authorize.net",
                            "handle": "nova-integrated-authorize-net",
                            "price_in_cents": 0,
                        }
                    },
                    {
                        "product": {
                            "id": 7099465,
                            "name": "Nova Integrated - Propelr",
                            "handle": "nova-integrated-propelr",
                            "price_in_cents": 0,
                        }
                    },
                    {
                        "product": {
                            "id": 999,
                            "name": "Nova Integrated GSPaytech",
                            "handle": "nova-integrated-gspaytech",
                            "price_in_cents": 0,
                        }
                    },
                ]
            )
        if url.endswith("/subscriptions/77.json"):
            return FakeResponse({"subscription": dict(self.subscription)})
        if url.endswith("/subscriptions/77/metadata.json"):
            return FakeResponse(
                [
                    {"name": "Locations", "value": "1"},
                    {"name": "LocationComponentMap", "value": '{"1":85653}'},
                    {"name": "LocationNameMap", "value": '{"1":"Main"}'},
                    {"name": "LocationNamesDisplay", "value": "Main"},
                ]
            )
        if url.endswith("/subscriptions/77/components.json"):
            return FakeResponse(
                [
                    {
                        "component_id": 85653,
                        "allocated_quantity": 1,
                        "component": {
                            "id": 85653,
                            "name": "Locations",
                            "unit_name": "location",
                        },
                    }
                ]
            )
        if url.endswith("/components/85653.json"):
            return FakeResponse(
                {
                    "component": {
                        "id": 85653,
                        "name": "Locations",
                        "unit_price": "99.99",
                    }
                }
            )
        if url.endswith("/subscriptions/77/account_balances.json"):
            return FakeResponse(self._balances())
        if url.endswith("/subscriptions/77/service_credits/list.json"):
            return FakeResponse(list(self.service_credits))
        raise AssertionError(url)

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        if method == "POST" and url.endswith("/subscriptions/77/service_credits.json"):
            credit = kwargs["json"]["service_credit"]
            amount = int(round(float(credit["amount"]) * 100))
            self.service_credit_balance_in_cents += amount
            row = {
                "service_credit": {
                    "id": 501,
                    "amount_in_cents": amount,
                    "memo": credit["memo"],
                }
            }
            self.service_credits.append(row)
            return FakeResponse(row, status_code=201)
        raise AssertionError((method, url))


# AgentChat/direct_codex 2026-07-31T00:00:00-04:00: prove that promotions use
# one ticket-bound preview/apply/readback path and cannot fall through generic API writes.
class SubscriptionCouponSession:
    def __init__(self) -> None:
        self.calls = []
        self.coupon_codes = []
        self.subscription = {
            "id": 77,
            "state": "past_due",
            "coupon_code": None,
            "coupon_codes": self.coupon_codes,
            "product": {
                "id": 12,
                "name": "GSPayTech Sub-Free Integration",
                "product_family": {"id": 4, "name": "Billing Plans"},
            },
        }
        self.coupon = {
            "id": 67,
            "name": "Three Months Free",
            "code": "3FREE",
            "amount_in_cents": None,
            "product_family_id": 4,
            "start_date": "2026-01-01T00:00:00-05:00",
            "end_date": None,
            "percentage": "100.0",
            "duration_period_count": 3,
            "duration_interval": 1,
            "duration_interval_unit": "month",
            "archived_at": None,
            "stackable": False,
        }

    def get(self, url, **kwargs):
        self.calls.append(("GET", url, kwargs))
        if url.endswith("/subscriptions/77.json"):
            return FakeResponse({"subscription": dict(self.subscription)})
        if url.endswith("/coupons/find.json"):
            assert kwargs["params"] == {"code": "3FREE", "product_family_id": 4}
            return FakeResponse({"coupon": dict(self.coupon)})
        if url.endswith("/subscriptions/77/account_balances.json"):
            return FakeResponse(
                {
                    "open_invoices": {"balance_in_cents": 13_999},
                    "pending_invoices": {"balance_in_cents": 0},
                    "pending_discounts": {"balance_in_cents": 0},
                    "service_credits": {"balance_in_cents": 0},
                    "prepayments": {"balance_in_cents": 0},
                }
            )
        raise AssertionError(url)

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        if method == "POST" and url.endswith("/subscriptions/77/add_coupon.json"):
            assert kwargs["json"] == {"codes": ["3FREE"]}
            self.coupon_codes[:] = ["3FREE"]
            return FakeResponse({"subscription": dict(self.subscription)})
        raise AssertionError((method, url))


class SubscriptionProductChangeSession:
    def __init__(self) -> None:
        self.calls = []
        self.subscription = {
            "id": 77,
            "state": "past_due",
            "coupon_codes": ["3FREE"],
            "current_period_started_at": "2026-07-01T00:00:00-04:00",
            "current_period_ends_at": "2026-08-01T00:00:00-04:00",
            "next_assessment_at": "2026-08-01T00:00:00-04:00",
            "product": {
                "id": 12,
                "name": "Nova Integrated GSPaytech",
                "handle": "gspaytech-promo",
                "product_family": {"id": 4, "name": "Nova POS"},
            },
        }
        self.target = {
            "id": 99,
            "name": "Nova Integrated - Propelr",
            "handle": "nova-integrated-porpelr",
            "product_family": {"id": 4, "name": "Nova POS"},
            "interval": 1,
            "interval_unit": "month",
            "price_in_cents": 0,
            "archived_at": None,
        }
        self.components = [
            {
                "component": {"id": 85653, "name": "$99.99 Location"},
                "allocated_quantity": 1,
            },
            {
                "component": {"id": 85654, "name": "$139.99 Location"},
                "allocated_quantity": 0,
            },
        ]

    def _balances(self):
        return {
            "open_invoices": {"balance_in_cents": 13_999},
            "pending_invoices": {"balance_in_cents": 0},
            "pending_discounts": {"balance_in_cents": 0},
            "service_credits": {"balance_in_cents": 0},
            "prepayments": {"balance_in_cents": 0},
        }

    def get(self, url, **kwargs):
        self.calls.append(("GET", url, kwargs))
        if url.endswith("/subscriptions/77.json"):
            return FakeResponse({"subscription": dict(self.subscription)})
        if url.endswith("/products/99.json"):
            return FakeResponse({"product": dict(self.target)})
        if url.endswith("/subscriptions/77/components.json"):
            return FakeResponse(list(self.components))
        if url.endswith("/subscriptions/77/account_balances.json"):
            return FakeResponse(self._balances())
        raise AssertionError(url)

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        if method == "PUT" and url.endswith("/subscriptions/77.json"):
            assert kwargs["json"] == {"subscription": {"product_id": 99}}
            self.subscription["product"] = {
                "id": 99,
                "name": self.target["name"],
                "handle": self.target["handle"],
                "product_family": dict(self.target["product_family"]),
            }
            return FakeResponse({"subscription": dict(self.subscription)})
        raise AssertionError((method, url))


class PartialLocationCollectionSession:
    def __init__(self, *, decline: bool = False) -> None:
        self.calls = []
        self.decline = decline
        self.open_invoice_balance_in_cents = 0
        self.expiration_year = datetime.now(timezone.utc).year + 3
        self.subscription = {
            "id": 77,
            "state": "active",
            "balance_in_cents": 0,
            "current_billing_amount_in_cents": 67_495,
            "payment_collection_method": "automatic",
            "current_period_started_at": "2026-07-02T00:00:00-04:00",
            "current_period_ends_at": "2026-08-02T00:00:00-04:00",
            "next_assessment_at": "2026-08-02T00:00:00-04:00",
            "updated_at": "2026-07-29T08:00:00-04:00",
            "customer": {"id": 9001, "reference": "NATURES_WELL"},
            "payment_profile": {"id": 7001},
        }
        component_map = {str(value): 1538219 for value in (13, 14, 19, 25, 1029)}
        name_map = {str(value): f"Location {value}" for value in (13, 14, 19, 25, 1029)}
        self.metadata = {
            "Locations": "13,14,19,25,1029",
            "LocationComponentMap": json.dumps(component_map, separators=(",", ":")),
            "LocationNameMap": json.dumps(name_map, separators=(",", ":")),
            "LocationNamesDisplay": ", ".join(name_map.values()),
        }
        self.transactions = [
            {
                "transaction": {
                    "id": 900,
                    "subscription_id": 77,
                    "transaction_type": "payment",
                    "success": True,
                    "amount_in_cents": 12_999,
                    "memo": "July renewal payment",
                    "created_at": "2026-07-04T08:00:00-04:00",
                }
            }
        ]

    def _balances(self):
        return {
            "open_invoices": {"balance_in_cents": self.open_invoice_balance_in_cents},
            "pending_invoices": {"balance_in_cents": 0},
            "pending_discounts": {"balance_in_cents": 0},
            "service_credits": {"balance_in_cents": 0},
            "prepayments": {"balance_in_cents": 0},
        }

    def get(self, url, **kwargs):
        self.calls.append(("GET", url, kwargs))
        if url.endswith("/subscriptions/77.json"):
            return FakeResponse({"subscription": dict(self.subscription)})
        if url.endswith("/payment_profiles.json"):
            return FakeResponse(
                [
                    {
                        "payment_profile": {
                            "id": 7001,
                            "customer_id": 9001,
                            "payment_type": "credit_card",
                            "expiration_month": 12,
                            "expiration_year": self.expiration_year,
                            "disabled_at": None,
                        }
                    }
                ]
            )
        if url.endswith("/subscriptions/77/account_balances.json"):
            return FakeResponse(self._balances())
        if url.endswith("/subscriptions/77/metadata.json"):
            return FakeResponse(
                {
                    "metadata": [
                        {"id": index, "name": name, "value": value}
                        for index, (name, value) in enumerate(self.metadata.items(), start=1)
                    ]
                }
            )
        if url.endswith("/subscriptions/77/components.json"):
            return FakeResponse(
                [
                    {
                        "component": {"id": 1538219, "name": "134.99 NOVA Location"},
                        "allocated_quantity": 5,
                    }
                ]
            )
        if url.endswith("/components/1538219.json"):
            return FakeResponse(
                {
                    "component": {
                        "id": 1538219,
                        "name": "134.99 NOVA Location",
                        "unit_price": "134.99",
                    }
                }
            )
        if url.endswith("/subscriptions/77/transactions.json"):
            return FakeResponse(list(reversed(self.transactions)))
        raise AssertionError(url)

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        if method != "POST" or not url.endswith("/subscriptions/77/charges.json"):
            raise AssertionError((method, url))
        charge = kwargs["json"]["charge"]
        if self.decline:
            if charge["accrue_on_failure"]:
                self.open_invoice_balance_in_cents = charge["amount_in_cents"]
            self.transactions.append(
                {
                    "transaction": {
                        "id": 902,
                        "subscription_id": 77,
                        "transaction_type": "payment",
                        "success": False,
                        "amount_in_cents": charge["amount_in_cents"],
                        "memo": "Partial location recovery payment",
                        "created_at": "2026-07-29T09:00:00-04:00",
                    }
                }
            )
            return FakeResponse({"errors": ["payment declined"]}, status_code=422)
        payment_id = 902
        self.transactions.extend(
            [
                {
                    "transaction": {
                        "id": 901,
                        "subscription_id": 77,
                        "transaction_type": "charge",
                        "success": True,
                        "amount_in_cents": charge["amount_in_cents"],
                        "memo": charge["memo"],
                        "payment_id": payment_id,
                        "created_at": "2026-07-29T09:00:00-04:00",
                    }
                },
                {
                    "transaction": {
                        "id": payment_id,
                        "subscription_id": 77,
                        "transaction_type": "payment",
                        "success": True,
                        "amount_in_cents": charge["amount_in_cents"],
                        "memo": "Partial location recovery payment",
                        "created_at": "2026-07-29T09:00:01-04:00",
                    }
                },
            ]
        )
        return FakeResponse(
            {
                "charge": {
                    "id": 901,
                    "success": True,
                    "amount_in_cents": charge["amount_in_cents"],
                    "memo": charge["memo"],
                    "payment_id": payment_id,
                }
            },
            status_code=201,
        )


class ComponentPaymentRecoverySession:
    def __init__(
        self,
        *,
        decline: bool = False,
        pending: bool = False,
        location_ids: tuple[int, ...] = (1,),
        reject_stage_after_apply: bool = False,
    ) -> None:
        self.calls = []
        self.decline = decline
        self.pending = pending
        self.reject_stage_after_apply = reject_stage_after_apply
        self.quantity = len(location_ids)
        self.location_ids = tuple(location_ids)
        self.open_invoice_balance_in_cents = 0
        self.pending_invoice_balance_in_cents = 0
        self.expiration_year = datetime.now(timezone.utc).year + 3
        self.subscription = {
            "id": 77,
            "state": "active",
            "balance_in_cents": 0,
            "current_billing_amount_in_cents": len(location_ids) * 11_999,
            "payment_collection_method": "automatic",
            "updated_at": "2026-07-31T09:00:00-04:00",
            "customer": {"id": 9001, "reference": "LA_CASA_DEL_PERFUME"},
            "payment_profile": {"id": 7001},
        }
        component_map = {str(value): 85644 for value in location_ids}
        name_map = {str(value): f"Location {value}" for value in location_ids}
        self.metadata = {
            "Locations": ",".join(str(value) for value in location_ids),
            "LocationComponentMap": json.dumps(component_map, separators=(",", ":")),
            "LocationNameMap": json.dumps(name_map, separators=(",", ":")),
            "LocationNamesDisplay": ", ".join(name_map.values()),
        }
        self.transactions = [
            {
                "transaction": {
                    "id": 900,
                    "subscription_id": 77,
                    "transaction_type": "payment",
                    "success": True,
                    "amount_in_cents": 11_999,
                    "memo": "Prior renewal",
                    "created_at": "2026-06-30T09:00:00-04:00",
                }
            }
        ]

    def _balances(self):
        return {
            "open_invoices": {"balance_in_cents": self.open_invoice_balance_in_cents},
            "pending_invoices": {"balance_in_cents": self.pending_invoice_balance_in_cents},
            "pending_discounts": {"balance_in_cents": 0},
            "service_credits": {"balance_in_cents": 0},
            "prepayments": {"balance_in_cents": 0},
        }

    def get(self, url, **kwargs):
        self.calls.append(("GET", url, kwargs))
        if url.endswith("/subscriptions/77.json"):
            return FakeResponse({"subscription": dict(self.subscription)})
        if url.endswith("/subscriptions/77/metadata.json"):
            return FakeResponse(
                {
                    "metadata": [
                        {"id": index, "name": name, "value": value}
                        for index, (name, value) in enumerate(self.metadata.items(), start=1)
                    ]
                }
            )
        if url.endswith("/subscriptions/77/components.json"):
            return FakeResponse(
                [
                    {
                        "component": {"id": 85644, "name": "$119.99 Location"},
                        "component_id": 85644,
                        "allocated_quantity": self.quantity,
                    }
                ]
            )
        if url.endswith("/components/85644.json"):
            return FakeResponse(
                {
                    "component": {
                        "id": 85644,
                        "name": "$119.99 Location",
                        "unit_price": "119.99",
                        "archived_at": None,
                    }
                }
            )
        if url.endswith("/payment_profiles.json"):
            return FakeResponse(
                [
                    {
                        "payment_profile": {
                            "id": 7001,
                            "customer_id": 9001,
                            "payment_type": "credit_card",
                            "expiration_month": 12,
                            "expiration_year": self.expiration_year,
                            "disabled_at": None,
                        }
                    }
                ]
            )
        if url.endswith("/subscriptions/77/account_balances.json"):
            return FakeResponse(self._balances())
        if url.endswith("/subscriptions/77/transactions.json"):
            return FakeResponse(list(reversed(self.transactions)))
        raise AssertionError(url)

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        if method != "POST":
            raise AssertionError((method, url))
        if url.endswith("/allocations/preview.json"):
            body = kwargs["json"]
            if body["upgrade_charge"] == "full":
                delta = int(body["allocations"][0]["quantity"]) - int(
                    body["allocations"][0]["previous_quantity"]
                )
                return FakeResponse(
                    {"allocation_preview": {"total_in_cents": delta * 11_999}}
                )
            return FakeResponse({"allocation_preview": {"total_in_cents": 0}})
        if not url.endswith("/allocations.json"):
            raise AssertionError((method, url))
        body = kwargs["json"]
        row = body["allocations"][0]
        self.quantity = int(row["quantity"])
        if body["upgrade_charge"] != "full":
            if self.reject_stage_after_apply and self.quantity == 0:
                return FakeResponse(
                    {"errors": ["stage rejected after allocation changed"]},
                    status_code=422,
                )
            return FakeResponse({"allocations": [dict(row)]})
        amount = (int(row["quantity"]) - int(row["previous_quantity"])) * 11_999
        if self.pending:
            self.pending_invoice_balance_in_cents = amount
            return FakeResponse({"allocation": dict(row), "payment": "pending"})
        if self.decline:
            self.subscription["state"] = "past_due"
            self.open_invoice_balance_in_cents = amount
            self.transactions.append(
                {
                    "transaction": {
                        "id": 902,
                        "subscription_id": 77,
                        "transaction_type": "payment",
                        "success": False,
                        "amount_in_cents": amount,
                        "memo": "Allocation payment failed",
                        "created_at": "2026-07-31T10:00:00-04:00",
                    }
                }
            )
            return FakeResponse({"allocation": dict(row), "payment": "failed"})
        self.transactions.extend(
            [
                {
                    "transaction": {
                        "id": 901,
                        "subscription_id": 77,
                        "transaction_type": "charge",
                        "success": True,
                        "amount_in_cents": amount,
                        "memo": "Full component allocation charge",
                        "payment_id": 902,
                        "created_at": "2026-07-31T10:00:00-04:00",
                    }
                },
                {
                    "transaction": {
                        "id": 902,
                        "subscription_id": 77,
                        "transaction_type": "payment",
                        "success": True,
                        "amount_in_cents": amount,
                        "memo": "Allocation payment",
                        "created_at": "2026-07-31T10:00:01-04:00",
                    }
                },
            ]
        )
        return FakeResponse({"allocation": dict(row), "payment": "paid"})


class InvoiceRefundSession:
    def __init__(self) -> None:
        self.calls = []
        self.invoice = {
            "uid": "inv_ticket347463",
            "number": "7788",
            "subscription_id": 77,
            "status": "paid",
            "currency": "USD",
            "paid_amount": "129.99",
            "refund_amount": "0.00",
            "due_amount": "0.00",
            "payments": [
                {
                    "transaction_id": 501,
                    "original_amount": "129.99",
                    "applied_amount": "129.99",
                }
            ],
            "refunds": [],
        }

    def get(self, url, **kwargs):
        self.calls.append(("GET", url, kwargs))
        if url.endswith("/invoices/inv_ticket347463.json"):
            return FakeResponse(dict(self.invoice))
        raise AssertionError(url)

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        if method != "POST" or not url.endswith(
            "/invoices/inv_ticket347463/refunds.json"
        ):
            raise AssertionError((method, url))
        refund = kwargs["json"]["refund"]
        self.invoice["refunds"] = [
            *self.invoice["refunds"],
            {
                "transaction_id": 601,
                "payment_id": refund["payment_id"],
                "memo": refund["memo"],
                "original_amount": "129.99",
                "applied_amount": refund["amount"],
            },
        ]
        self.invoice["refund_amount"] = refund["amount"]
        return FakeResponse(dict(self.invoice))


def _client(payload=None, *, journal_path: Path | None = None) -> tuple[ScopedMaxioClient, FakeSession]:
    session = FakeSession([] if payload is None else payload)
    settings = MaxioSettings(
        "https://example.chargify.com",
        "secret",
        journal_path or Path("/tmp/nova-maxio-test-journal.jsonl"),
    )
    return ScopedMaxioClient(settings, session=session), session


def test_environment_aliases_are_supported(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CHARGIFY_BASE_URL", raising=False)
    monkeypatch.delenv("CHARGIFY_API_KEY", raising=False)
    monkeypatch.setenv("CHARGIFY_SUBDOMAIN", "example.chargify.com")
    monkeypatch.setenv("MAXIO_API_KEY", "secret")
    settings = MaxioSettings.from_environment()
    assert settings.base_url == "https://example.chargify.com"
    assert settings.api_key == "secret"


def test_client_uses_exact_reference_lookup_and_bounded_search() -> None:
    client, session = _client({"customer": {"id": 7}})
    result = client.customers_by_reference("POS_Example", max_rows=5)
    assert result["ok"] is True
    assert session.calls[0][1] == "https://example.chargify.com/customers/lookup.json"
    assert session.calls[0][2]["params"]["reference"] == "POS_Example"
    assert session.calls[0][2]["auth"] == ("secret", "x")
    client, session = _client([{"customer": {"id": 7}}])
    assert client.customers_search("billing@example.com", max_rows=5)["returned"] == 1
    assert session.calls[0][2]["params"]["q"] == "billing@example.com"
    assert not hasattr(client, "delete")


def test_host_boundary_rejects_unapproved_url() -> None:
    client = ScopedMaxioClient(MaxioSettings("https://evil.example", "secret"), session=FakeSession([]))
    with pytest.raises(MaxioUnavailableError, match="approved HTTPS host"):
        client.health()


def test_identifiers_and_rows_are_bounded() -> None:
    client, session = _client([])
    client.subscriptions_by_customer(7, max_rows=999)
    assert session.calls[0][2]["params"]["per_page"] == 50
    with pytest.raises(MaxioScopeError):
        client.customer(0)
    with pytest.raises(MaxioScopeError):
        client.invoice("../unsafe")


def test_mcp_rejects_non_billing_lanes_and_exposes_guarded_non_delete_operations() -> None:
    client, _ = _client([])
    with pytest.raises(RuntimeError, match="fixed billing or coding lane"):
        build_mcp("tickets_agent", client)
    mcp = build_mcp("billing_agent", client)
    names = set(mcp._tool_manager._tools)
    assert "maxio_health" in names
    assert "maxio_customers_search" in names
    assert "maxio_api_request" in names
    assert "maxio_tax_report" in names
    assert "maxio_component_allocation_preview" in names
    assert "maxio_component_allocation_apply" in names
    assert "maxio_location_custom_fields_read" in names
    assert "maxio_location_custom_fields_preview" in names
    assert "maxio_location_custom_fields_apply" in names
    assert "maxio_subscription_location_metadata_read" in names
    assert "maxio_subscription_location_mapping_preview" in names
    assert "maxio_subscription_location_mapping_apply" in names
    assert "maxio_location_allocation_reconciliation_read" in names
    assert "maxio_manual_service_credit_preview" in names
    assert "maxio_manual_service_credit_apply" in names
    assert "maxio_subscription_coupon_preview" in names
    assert "maxio_subscription_coupon_apply" in names
    assert "maxio_subscription_product_change_preview" in names
    assert "maxio_subscription_product_change_apply" in names
    assert "maxio_subscription_payment_profile_assignment_preview" in names
    assert "maxio_subscription_payment_profile_assignment_apply" in names
    assert "maxio_payment_profile_update_request_preview" in names
    assert "maxio_payment_profile_update_request_apply" in names
    assert "maxio_subscription_reactivation_preview" in names
    assert "maxio_subscription_reactivation_apply" in names
    assert "maxio_component_payment_recovery_preview" in names
    assert "maxio_component_payment_recovery_apply" in names
    assert "maxio_partial_location_collection_preview" not in names
    assert "maxio_billing_cycle_recovery_preview" in names
    assert "maxio_billing_cycle_recovery_apply" in names
    assert "maxio_subscription_cancellation_preview" in names
    assert "maxio_subscription_cancellation_apply" in names
    assert all("delete" not in name for name in names)
    coding_names = set(build_mcp("coding_agent", client)._tool_manager._tools)
    assert "maxio_tax_report" in coding_names
    assert "maxio_subscription_cancellation_preview" not in coding_names
    assert "maxio_subscription_cancellation_apply" not in coding_names
    assert "maxio_subscription_reactivation_preview" not in coding_names
    assert "maxio_subscription_reactivation_apply" not in coding_names
    assert "maxio_subscription_coupon_preview" not in coding_names
    assert "maxio_subscription_coupon_apply" not in coding_names
    assert "maxio_subscription_product_change_preview" not in coding_names
    assert "maxio_subscription_product_change_apply" not in coding_names
    assert "maxio_billing_cycle_recovery_preview" not in coding_names
    assert "maxio_billing_cycle_recovery_apply" not in coding_names


def test_billing_capabilities_describe_full_rainfall_customer_portal_workflow() -> None:
    client, _ = _client([])
    mcp = build_mcp("billing_agent", client)

    result = mcp._tool_manager._tools["maxio_capabilities"].fn()

    workflows = result["rainfallCustomerPortalWorkflows"]
    assert "account_and_subscription_lookup" in workflows
    assert "add_close_or_reactivate_billed_locations" in workflows
    assert "component_and_rate_normalization" in workflows
    assert "payment_profile_read_and_assignment" in workflows
    assert "payment_retry" in workflows
    assert "invoice_read_and_delivery" in workflows
    assert "immediate_zero_balance_subscription_cancellation" in workflows
    assert "salesforce_location_order_account_and_ticket_completion" in workflows
    repair_modes = result["subscriptionRepairModes"]
    assert set(repair_modes) == {
        "upgrade_no_charge",
        "downgrade_no_credit",
        "upgrade_with_credit",
        "downgrade_with_credit",
    }
    assert repair_modes["upgrade_no_charge"]["toolSequence"] == [
        "maxio_component_allocation_preview",
        "maxio_component_allocation_apply",
        "maxio_subscription_account_balances",
    ]
    assert repair_modes["downgrade_with_credit"]["toolSequence"] == [
        "maxio_component_allocation_preview",
        "maxio_component_allocation_apply",
        "maxio_manual_service_credit_preview",
        "maxio_manual_service_credit_apply",
        "maxio_subscription_account_balances",
    ]
    assert repair_modes["upgrade_with_credit"]["creditRequiresExactAuthorizedCents"] is True
    assert result["subscriptionRepairRequiresBillingTicketBeforeWrite"] is True
    assert result["typedSubscriptionCouponExposed"] is True
    assert result["typedSubscriptionProductChangeExposed"] is True
    assert result["typedPaymentProfileAssignmentExposed"] is True
    assert result["typedSecurePaymentUpdateRequestExposed"] is True
    assert result["typedSubscriptionReactivationExposed"] is True
    assert result["rawPaymentDetailsAccepted"] is False
    assert result["subscriptionCouponRequiresInvoiceDisposition"] is True
    assert "maxio_subscription_coupon_preview" in result["operations"]
    assert "maxio_subscription_coupon_apply" in result["operations"]
    assert "maxio_subscription_payment_profile_assignment_apply" in result["operations"]
    assert "maxio_payment_profile_update_request_apply" in result["operations"]
    assert "maxio_subscription_reactivation_apply" in result["operations"]
    assert result["locationMappingCustomFields"] == [
        "Locations",
        "LocationComponentMap",
        "LocationNameMap",
        "LocationNamesDisplay",
    ]
    assert result["locationMappingIsOrganizationalNotAuthoritativeForActiveLocationCount"] is True
    assert "maxio_location_allocation_reconciliation_read" in result["operations"]
    assert result["automaticAllocationChargesOrCreditsExposed"] is True
    assert result["automaticAllocationFinancialEffectsRestrictedToComponentPaymentRecovery"] is True
    assert result["automaticAllocationCreditExposed"] is False
    assert result["typedComponentPaymentRecoveryExposed"] is True
    assert result["componentPaymentRecoveryUsesAllocation"] is True
    assert result["componentPaymentRecoveryDowngradeCredit"] == "none"
    assert result["componentPaymentRecoveryUpgradeCharge"] == "full"
    assert result["componentPaymentRecoveryInitiatesDunningOnFailure"] is True
    assert result["componentPaymentRecoveryRequiresExactLocationIsolation"] is True
    assert result["componentPaymentRecoveryRestoresRecurringQuantity"] is True
    assert result["typedBillingCycleRecoveryExposed"] is True
    assert result["billingCycleRecoveryCanPreserveDeclinedOpenInvoice"] is True
    assert result["billingCycleRecoveryRequiresExistingVerifiedSubscription"] is True
    assert result["billingCycleRecoveryRetryAfterAttemptExposed"] is False
    assert result["genericOneTimeChargeExposed"] is False
    assert result["directOneTimeRecoveryChargeExposed"] is True
    assert "maxio_billing_cycle_recovery_preview" in result["operations"]
    assert "maxio_billing_cycle_recovery_apply" in result["operations"]
    assert result["componentPaymentRecoveryRetryAfterAttemptExposed"] is False
    assert result["writesRequireExplicitAuthorization"] is True
    assert result["arbitraryProviderAccess"] is False


def test_subscription_coupon_is_previewed_ticket_bound_verified_and_idempotent(
    tmp_path: Path,
) -> None:
    session = SubscriptionCouponSession()
    client = ScopedMaxioClient(
        MaxioSettings(
            "https://example.chargify.com",
            "secret",
            tmp_path / "journal.jsonl",
        ),
        session=session,
    )

    preview = client.subscription_coupon_preview(77, "3FREE", "347519")
    assert preview["status"] == "preview"
    assert preview["coupon"] == {
        "id": 67,
        "code": "3FREE",
        "name": "Three Months Free",
        "productFamilyId": 4,
        "amountCents": 0,
        "percentage": "100",
        "durationPeriodCount": 3,
        "durationInterval": 1,
        "durationIntervalUnit": "month",
        "stackable": False,
        "startDate": "2026-01-01",
        "endDate": None,
    }
    assert preview["invoiceDispositionRequired"] is True
    assert preview["existingInvoiceAdjustmentIncluded"] is False
    assert preview["refundIncluded"] is False
    assert preview["serviceCreditIncluded"] is False

    applied = client.apply_subscription_coupon(
        77,
        "3FREE",
        "347519",
        preview_hash=preview["previewHash"],
        idempotency_key="ticket-347519-subscription-77-promo-3free",
    )
    assert applied["status"] == "applied"
    assert applied["verified"] is True
    assert applied["couponCodes"] == ["3FREE"]
    assert applied["invoiceDispositionRequired"] is True
    post_calls = [
        call for call in session.calls if call[0] == "POST" and call[1].endswith("/add_coupon.json")
    ]
    assert len(post_calls) == 1

    duplicate_preview = client.subscription_coupon_preview(77, "3FREE", "347519")
    assert duplicate_preview["status"] == "already_applied"
    duplicate = client.apply_subscription_coupon(
        77,
        "3FREE",
        "347519",
        preview_hash=duplicate_preview["previewHash"],
        idempotency_key="ticket-347519-subscription-77-promo-3free-repeat",
    )
    assert duplicate["status"] == "already_applied"
    assert duplicate["duplicate"] is True
    assert len(
        [
            call
            for call in session.calls
            if call[0] == "POST" and call[1].endswith("/add_coupon.json")
        ]
    ) == 1


def test_subscription_product_change_is_same_family_previewed_and_preserves_billing(
    tmp_path: Path,
) -> None:
    session = SubscriptionProductChangeSession()
    client = ScopedMaxioClient(
        MaxioSettings(
            "https://example.chargify.com",
            "secret",
            tmp_path / "journal.jsonl",
        ),
        session=session,
    )

    preview = client.subscription_product_change_preview(77, 99, "347519")
    assert preview["status"] == "preview"
    assert preview["currentProduct"]["name"] == "Nova Integrated GSPaytech"
    assert preview["targetProduct"] == {
        "id": 99,
        "name": "Nova Integrated - Propelr",
        "handle": "nova-integrated-porpelr",
        "productFamilyId": 4,
        "interval": 1,
        "intervalUnit": "month",
        "basePriceCents": 0,
    }
    assert preview["currentCouponCodes"] == ["3FREE"]
    assert preview["nonzeroComponentAllocations"] == [
        {"componentId": 85653, "name": "$99.99 Location", "quantity": 1}
    ]
    assert preview["balances"]["openInvoiceBalanceCents"] == 13_999
    assert preview["automaticChargeAuthorized"] is False
    assert preview["prorationAuthorized"] is False

    applied = client.apply_subscription_product_change(
        77,
        99,
        "347519",
        preview_hash=preview["previewHash"],
        idempotency_key="ticket-347519-subscription-77-product-propelr",
    )
    assert applied["status"] == "applied"
    assert applied["verified"] is True
    assert applied["product"]["id"] == 99
    assert applied["couponCodes"] == ["3FREE"]
    assert applied["nonzeroComponentAllocations"] == preview[
        "nonzeroComponentAllocations"
    ]
    assert applied["balances"] == preview["balances"]
    assert applied["billingPeriod"] == preview["billingPeriod"]
    assert len([call for call in session.calls if call[0] == "PUT"]) == 1

    duplicate_preview = client.subscription_product_change_preview(77, 99, "347519")
    duplicate = client.apply_subscription_product_change(
        77,
        99,
        "347519",
        preview_hash=duplicate_preview["previewHash"],
        idempotency_key="ticket-347519-subscription-77-product-propelr-repeat",
    )
    assert duplicate["status"] == "already_configured"
    assert duplicate["duplicate"] is True
    assert len([call for call in session.calls if call[0] == "PUT"]) == 1


def test_generic_subscription_update_cannot_change_product(tmp_path: Path) -> None:
    client, _session = _client({}, journal_path=tmp_path / "journal.jsonl")
    with pytest.raises(MaxioScopeError, match="typed product-change"):
        client.api_request(
            "PUT",
            "/subscriptions/77.json",
            json_body={"subscription": {"product_id": 99}},
            idempotency_key="ticket-347519-generic-product-change",
        )


def test_location_custom_fields_and_mapping_are_fixed_previewed_and_verified(
    tmp_path: Path,
) -> None:
    session = LocationMetadataSession()
    client = ScopedMaxioClient(
        MaxioSettings(
            "https://example.chargify.com",
            "secret",
            tmp_path / "journal.jsonl",
        ),
        session=session,
    )
    fields_preview = client.location_custom_fields_preview("347402")
    assert [row["name"] for row in fields_preview["missingDefinitions"]] == [
        "Locations",
        "LocationComponentMap",
        "LocationNameMap",
        "LocationNamesDisplay",
    ]
    fields_result = client.apply_location_custom_fields(
        "347402",
        preview_hash=fields_preview["previewHash"],
        idempotency_key="ticket-347402-maxio-location-fields",
    )
    assert fields_result["verified"] is True
    assert fields_result["readback"]["definedNames"] == [
        "LocationComponentMap",
        "LocationNameMap",
        "LocationNamesDisplay",
        "Locations",
    ]

    locations = [
        {"location_id": 2, "location_name": "Downtown", "component_id": 85644},
        {"location_id": 7, "location_name": "Uptown", "component_id": 85644},
    ]
    mapping_preview = client.subscription_location_mapping_preview(
        77,
        locations,
        "347402",
    )
    assert mapping_preview["desiredMetadata"]["Locations"] == "2,7"
    assert mapping_preview["desiredMetadata"]["LocationComponentMap"] == (
        '{"2":85644,"7":85644}'
    )
    mapping_result = client.apply_subscription_location_mapping(
        77,
        locations,
        "347402",
        preview_hash=mapping_preview["previewHash"],
        idempotency_key="ticket-347402-sub-77-location-map",
    )
    assert mapping_result["verified"] is True
    assert mapping_result["readback"]["values"] == mapping_preview["desiredMetadata"]
    metadata_posts = [
        call
        for call in session.calls
        if call[0] == "POST" and call[1].endswith("/subscriptions/77/metadata.json")
    ]
    assert len(metadata_posts) == 4


def test_location_mapping_requires_allocations_to_match_and_blocks_generic_metadata(
    tmp_path: Path,
) -> None:
    session = LocationMetadataSession()
    session.definitions = [
        {"name": name, "input_type": "text"}
        for name in (
            "Locations",
            "LocationComponentMap",
            "LocationNameMap",
            "LocationNamesDisplay",
        )
    ]
    client = ScopedMaxioClient(
        MaxioSettings(
            "https://example.chargify.com",
            "secret",
            tmp_path / "journal.jsonl",
        ),
        session=session,
    )
    with pytest.raises(MaxioScopeError, match="repair allocations first"):
        client.subscription_location_mapping_preview(
            77,
            [{"location_id": 2, "location_name": "Downtown", "component_id": 85644}],
            "347402",
        )
    with pytest.raises(MaxioScopeError, match="typed location-mapping"):
        client.api_request(
            "POST",
            "/subscriptions/77/metadata.json",
            json_body={"metadata": {"name": "arbitrary", "value": "unsafe"}},
            idempotency_key="ticket-347402-generic-metadata",
        )


def test_subscription_cancellation_is_immediate_journaled_and_verified(tmp_path: Path) -> None:
    session = CancellationSession()
    client = ScopedMaxioClient(
        MaxioSettings(
            "https://example.chargify.com",
            "secret",
            tmp_path / "journal.jsonl",
        ),
        session=session,
    )

    preview = client.subscription_cancellation_preview(
        77,
        "347191",
        "Customer requested cancellation of all Nova POS services.",
    )

    assert preview["status"] == "preview"
    assert preview["currentState"] == "active"
    assert preview["currentBalanceCents"] == 0
    assert preview["timing"] == "immediate"
    assert preview["providerRequest"] == {
        "method": "DELETE",
        "path": "/subscriptions/77.json",
        "scheduleParametersOmitted": True,
    }
    assert preview["automaticRefundAuthorized"] is False
    assert preview["automaticCreditAuthorized"] is False
    assert preview["invoiceVoidAuthorized"] is False
    assert preview["customerEmailAuthorized"] is False
    assert preview["locationComponentDeallocationCount"] == 1
    assert preview["componentDeallocationSummary"][
        "storageComponentDeallocationCount"
    ] == 17
    assert preview["componentDeallocationSummary"][
        "otherComponentDeallocationCount"
    ] == 2

    applied = client.apply_subscription_cancellation(
        77,
        "347191",
        "Customer requested cancellation of all Nova POS services.",
        preview_hash=preview["previewHash"],
        idempotency_key="ticket-347191-subscription-77-cancel-v1",
    )

    assert applied["updated"] is True
    assert applied["verified"] is True
    assert applied["readback"]["state"] == "canceled"
    assert applied["cancellationMessageVerified"] is True
    assert applied["locationComponentDeallocationCount"] == 1
    assert applied["componentDeallocationSummary"][
        "storageComponentDeallocationCount"
    ] == 17
    delete_calls = [call for call in session.calls if call[0] == "DELETE"]
    assert len(delete_calls) == 1
    assert delete_calls[0][1] == "https://example.chargify.com/subscriptions/77.json"
    assert delete_calls[0][2]["json"] == {
        "subscription": {
            "cancellation_message": (
                "Ticket 347191: Customer requested cancellation of all Nova POS services."
            )
        }
    }
    assert "cancel_at_end_of_period" not in delete_calls[0][2]["json"]["subscription"]

    duplicate = client.apply_subscription_cancellation(
        77,
        "347191",
        "Customer requested cancellation of all Nova POS services.",
        preview_hash=preview["previewHash"],
        idempotency_key="ticket-347191-subscription-77-cancel-v1",
    )
    assert duplicate["updated"] is False
    assert duplicate["duplicate"] is True
    assert duplicate["verified"] is True
    assert len([call for call in session.calls if call[0] == "DELETE"]) == 1


def test_subscription_cancellation_requires_zero_balance_and_exact_preview(tmp_path: Path) -> None:
    session = CancellationSession(balance_in_cents=12999)
    client = ScopedMaxioClient(
        MaxioSettings(
            "https://example.chargify.com",
            "secret",
            tmp_path / "journal.jsonl",
        ),
        session=session,
    )
    preview = client.subscription_cancellation_preview(77, "347191", "Close the account.")

    with pytest.raises(MaxioScopeError, match="verified zero balance"):
        client.apply_subscription_cancellation(
            77,
            "347191",
            "Close the account.",
            preview_hash=preview["previewHash"],
            idempotency_key="ticket-347191-subscription-77-cancel-v1",
        )
    with pytest.raises(MaxioScopeError, match="preview_hash"):
        client.apply_subscription_cancellation(
            77,
            "347191",
            "A different cancellation reason.",
            preview_hash=preview["previewHash"],
            idempotency_key="ticket-347191-subscription-77-cancel-v2",
        )
    assert not [call for call in session.calls if call[0] == "DELETE"]


def test_past_due_cancellation_preserves_open_invoice_and_balance(tmp_path: Path) -> None:
    session = PastDueCancellationSession()
    client = ScopedMaxioClient(
        MaxioSettings(
            "https://example.chargify.com",
            "secret",
            tmp_path / "journal.jsonl",
        ),
        session=session,
    )
    reason = "Payment extension expired; close service and preserve the receivable."
    preview = client.past_due_subscription_cancellation_preview(77, "347667", reason)

    assert preview["status"] == "preview"
    assert preview["currentState"] == "past_due"
    assert preview["balances"]["openInvoiceBalanceCents"] == 11_999
    assert preview["openInvoices"] == [
        {
            "uid": "inv_347667",
            "number": "INV-347667",
            "status": "open",
            "dueAmountCents": 11_999,
            "totalAmountCents": 11_999,
        }
    ]
    assert preview["preserveOpenInvoiceRequired"] is True
    assert preview["invoiceVoidAuthorized"] is False
    assert preview["automaticCreditAuthorized"] is False
    assert preview["paymentRetryAuthorized"] is False

    applied = client.apply_past_due_subscription_cancellation(
        77,
        "347667",
        reason,
        preview_hash=preview["previewHash"],
        idempotency_key="ticket-347667-past-due-cancel-v1",
    )

    assert applied["updated"] is True
    assert applied["verified"] is True
    assert applied["readback"]["state"] == "canceled"
    assert applied["balances"] == preview["balances"]
    assert applied["openInvoices"] == preview["openInvoices"]
    assert applied["openInvoicePreserved"] is True
    assert len([call for call in session.calls if call[0] == "DELETE"]) == 1


def test_past_due_cancellation_fails_closed_if_invoice_changes(tmp_path: Path) -> None:
    session = PastDueCancellationSession(change_invoice_on_cancel=True)
    client = ScopedMaxioClient(
        MaxioSettings(
            "https://example.chargify.com",
            "secret",
            tmp_path / "journal.jsonl",
        ),
        session=session,
    )
    reason = "Payment extension expired; close service and preserve the receivable."
    preview = client.past_due_subscription_cancellation_preview(77, "347667", reason)

    with pytest.raises(MaxioScopeError, match="at least one exact open invoice"):
        client.apply_past_due_subscription_cancellation(
            77,
            "347667",
            reason,
            preview_hash=preview["previewHash"],
            idempotency_key="ticket-347667-past-due-cancel-changed-invoice-v1",
        )
    assert len([call for call in session.calls if call[0] == "DELETE"]) == 1


def test_location_allocation_reconciliation_counts_only_open_location_components(
    tmp_path: Path,
) -> None:
    class ReconciliationSession:
        def __init__(self) -> None:
            self.states = {77: "active", 88: "canceled"}
            self.calls = []

        def get(self, url, **kwargs):
            self.calls.append(("GET", url, kwargs))
            for subscription_id in (77, 88):
                if url.endswith(f"/subscriptions/{subscription_id}.json"):
                    return FakeResponse(
                        {
                            "subscription": {
                                "id": subscription_id,
                                "state": self.states[subscription_id],
                            }
                        }
                    )
                if url.endswith(f"/subscriptions/{subscription_id}/components.json"):
                    location_quantity = 2 if subscription_id == 77 else 3
                    return FakeResponse(
                        [
                            {
                                "component": {
                                    "id": subscription_id * 100,
                                    "name": "$129.99 Locations",
                                    "unit_name": "location",
                                },
                                "allocated_quantity": location_quantity,
                            },
                            {
                                "component": {
                                    "id": subscription_id * 100 + 1,
                                    "name": "Storage",
                                    "unit_name": "storage",
                                },
                                "allocated_quantity": 5,
                            },
                        ]
                    )
            raise AssertionError((url, kwargs))

    session = ReconciliationSession()
    client = ScopedMaxioClient(
        MaxioSettings(
            "https://example.chargify.com",
            "secret",
            tmp_path / "journal.jsonl",
        ),
        session=session,
    )

    before = client.location_allocation_reconciliation([88, 77])

    assert before["subscriptionIds"] == [77, 88]
    assert before["openSubscriptionIds"] == [77]
    assert before["openLocationComponentQuantity"] == 2
    assert before["subscriptions"][0]["storageComponentQuantity"] == 5
    assert before["allComponentInventoriesComplete"] is True
    assert before["allSubscriptionsClosed"] is False
    assert len(before["snapshotHash"]) == 64
    assert before["writesPerformed"] is False

    session.states[77] = "canceled"
    after = client.location_allocation_reconciliation([77, 88])

    assert after["openSubscriptionIds"] == []
    assert after["openLocationComponentQuantity"] == 0
    assert after["allSubscriptionsClosed"] is True
    assert after["snapshotHash"] != before["snapshotHash"]


def test_subscription_cancellation_paginates_complete_component_inventory(
    tmp_path: Path,
) -> None:
    class PaginatedCancellationSession(CancellationSession):
        def get(self, url, **kwargs):
            self.calls.append(("GET", url, kwargs))
            if url.endswith("/subscriptions/77.json"):
                return FakeResponse({"subscription": dict(self.subscription)})
            if url.endswith("/subscriptions/77/components.json"):
                page = int(kwargs["params"]["page"])
                if page == 1:
                    return FakeResponse(
                        [
                            {
                                "component": {
                                    "component_id": 900000 + index,
                                    "name": f"Archived option {index}",
                                    "allocated_quantity": 0,
                                }
                            }
                            for index in range(100)
                        ]
                    )
                if page == 2:
                    return FakeResponse(
                        [
                            {
                                "component": {
                                    "component_id": 85644,
                                    "name": "$129.99 Location",
                                    "allocated_quantity": 1,
                                }
                            }
                        ]
                    )
            raise AssertionError((url, kwargs))

    session = PaginatedCancellationSession()
    client = ScopedMaxioClient(
        MaxioSettings(
            "https://example.chargify.com",
            "secret",
            tmp_path / "journal.jsonl",
        ),
        session=session,
    )

    preview = client.subscription_cancellation_preview(
        77,
        "347191",
        "Customer requested cancellation.",
    )

    component_pages = [
        call[2]["params"]["page"]
        for call in session.calls
        if call[1].endswith("/subscriptions/77/components.json")
    ]
    assert component_pages == [1, 2]
    assert preview["locationComponentDeallocationCount"] == 1
    assert preview["componentDeallocationSummary"]["componentInventoryComplete"] is True


def test_subscription_cancellation_accepts_maxio_unpaginated_component_inventory(
    tmp_path: Path,
) -> None:
    class UnpaginatedCancellationSession(CancellationSession):
        def get(self, url, **kwargs):
            self.calls.append(("GET", url, kwargs))
            if url.endswith("/subscriptions/77.json"):
                return FakeResponse({"subscription": dict(self.subscription)})
            if url.endswith("/subscriptions/77/components.json"):
                return FakeResponse(
                    [
                        {
                            "component": {
                                "component_id": 900000 + index,
                                "name": f"Archived option {index}",
                                "allocated_quantity": 0,
                            }
                        }
                        for index in range(153)
                    ]
                    + [
                        {
                            "component": {
                                "component_id": 85644,
                                "name": "$129.99 Location",
                                "allocated_quantity": 1,
                            }
                        }
                    ]
                )
            raise AssertionError((url, kwargs))

    session = UnpaginatedCancellationSession()
    client = ScopedMaxioClient(
        MaxioSettings(
            "https://example.chargify.com",
            "secret",
            tmp_path / "journal.jsonl",
        ),
        session=session,
    )

    preview = client.subscription_cancellation_preview(
        77,
        "347191",
        "Customer requested cancellation.",
    )

    component_pages = [
        call[2]["params"]["page"]
        for call in session.calls
        if call[1].endswith("/subscriptions/77/components.json")
    ]
    assert component_pages == [1, 2]
    assert preview["locationComponentDeallocationCount"] == 1
    assert len(
        preview["componentDeallocationSummary"]["componentDeallocations"]
    ) == 1


def test_component_allocation_tools_fix_financial_controls_and_require_preview(tmp_path: Path) -> None:
    session = AllocationSession()
    client = ScopedMaxioClient(
        MaxioSettings(
            "https://example.chargify.com",
            "secret",
            tmp_path / "journal.jsonl",
        ),
        session=session,
    )

    preview = client.component_allocation_preview(
        77,
        [{"component_id": 85644, "quantity": 2}],
    )

    assert preview["status"] == "preview"
    assert preview["changes"] == [
        {"componentId": 85644, "currentQuantity": 1, "desiredQuantity": 2}
    ]
    assert preview["changeDirection"] == "upgrade"
    assert preview["manualCreditRequiresSeparatePreviewAndApply"] is True
    assert preview["financialControls"] == {
        "upgrade_charge": "none",
        "downgrade_credit": "none",
        "proration_upgrade_scheme": "no-prorate",
        "proration_downgrade_scheme": "none",
    }
    preview_call = next(call for call in session.calls if call[1].endswith("/allocations/preview.json"))
    assert preview_call[2]["json"]["upgrade_charge"] == "none"
    assert preview_call[2]["json"]["downgrade_credit"] == "none"
    assert "proration_upgrade_scheme" not in preview_call[2]["json"]

    applied = client.apply_component_allocation(
        77,
        [{"component_id": 85644, "quantity": 2}],
        preview_hash=preview["previewHash"],
        idempotency_key="ticket-347308-sub-77-allocation",
    )

    assert applied["updated"] is True
    assert applied["verified"] is True
    assert applied["changeDirection"] == "upgrade"
    assert applied["financialEffectsAuthorized"] is False
    assert applied["manualCreditRequiresSeparatePreviewAndApply"] is True
    assert applied["financialReadbackRequired"] is True
    assert session.quantities[85644] == 2
    downgrade_preview = client.component_allocation_preview(
        77,
        [{"component_id": 85644, "quantity": 1}],
    )
    assert downgrade_preview["changeDirection"] == "downgrade"
    assert downgrade_preview["locationComponentDeallocationCount"] == 1
    assert downgrade_preview["componentDeallocationSummary"][
        "storageComponentDeallocationCount"
    ] == 0
    apply_call = next(
        call
        for call in session.calls
        if call[1].endswith("/allocations.json") and not call[1].endswith("/allocations/preview.json")
    )
    assert apply_call[2]["json"] == {
        "allocations": [
            {
                "component_id": 85644,
                "quantity": 2,
                "previous_quantity": 1,
            }
        ],
        "upgrade_charge": "none",
        "downgrade_credit": "none",
        "proration_upgrade_scheme": "no-prorate",
        "proration_downgrade_scheme": "none",
    }


def test_component_allocation_preview_accepts_live_nested_component_shape() -> None:
    client, _ = _client(
        [
            {
                "component": {
                    "id": 1812690207,
                    "component_id": 85654,
                    "name": "$139.99 Location",
                    "allocated_quantity": 0,
                }
            }
        ]
    )

    preview = client.component_allocation_preview(
        93250402,
        [{"component_id": 85654, "quantity": 1}],
    )

    assert preview["changes"] == [
        {"componentId": 85654, "currentQuantity": 0, "desiredQuantity": 1}
    ]
    assert preview["changeDirection"] == "upgrade"
    assert preview["locationComponentDeallocationCount"] == 0
    assert preview["financialControls"]["upgrade_charge"] == "none"
    assert preview["financialControls"]["downgrade_credit"] == "none"


def test_component_allocation_apply_rejects_stale_preview_and_caller_controls(tmp_path: Path) -> None:
    session = AllocationSession()
    client = ScopedMaxioClient(
        MaxioSettings(
            "https://example.chargify.com",
            "secret",
            tmp_path / "journal.jsonl",
        ),
        session=session,
    )
    preview = client.component_allocation_preview(
        77,
        [{"component_id": 85644, "quantity": 2}],
    )
    session.quantities[85644] = 3

    with pytest.raises(MaxioScopeError, match="preview_hash"):
        client.apply_component_allocation(
            77,
            [{"component_id": 85644, "quantity": 2}],
            preview_hash=preview["previewHash"],
            idempotency_key="ticket-347308-sub-77-allocation",
        )
    with pytest.raises(MaxioScopeError, match="only component_id and quantity"):
        client.component_allocation_preview(
            77,
            [
                {
                    "component_id": 85644,
                    "quantity": 2,
                    "upgrade_charge": "full",
                }
            ],
        )


def test_component_allocation_tool_schema_exposes_no_financial_switches() -> None:
    client, _ = _client([])
    mcp = build_mcp("billing_agent", client)
    preview = mcp._tool_manager._tools["maxio_component_allocation_preview"]
    apply = mcp._tool_manager._tools["maxio_component_allocation_apply"]

    assert set(preview.parameters["properties"]) == {"subscription_id", "allocations"}
    assert set(apply.parameters["properties"]) == {
        "subscription_id",
        "allocations",
        "preview_hash",
        "idempotency_key",
    }
    assert preview.annotations.readOnlyHint is True
    assert apply.annotations.readOnlyHint is False
    assert apply.annotations.idempotentHint is True


def test_future_billed_subscription_creation_is_previewed_journaled_and_verified(
    tmp_path: Path,
) -> None:
    session = SubscriptionCreationSession()
    client = ScopedMaxioClient(
        MaxioSettings(
            "https://example.chargify.com",
            "secret",
            tmp_path / "maxio.jsonl",
        ),
        session=session,
    )
    next_billing_at = (
        datetime.now(timezone.utc) + timedelta(days=14)
    ).isoformat(timespec="seconds")
    preview = client.subscription_creation_preview(
        9001,
        "A-1567396",
        7001,
        3655664,
        85654,
        1,
        13_999,
        next_billing_at,
        "347395",
    )
    applied = client.apply_subscription_creation(
        9001,
        "A-1567396",
        7001,
        3655664,
        85654,
        1,
        13_999,
        next_billing_at,
        "347395",
        preview_hash=preview["previewHash"],
        idempotency_key="ticket-347395-subscription-create-v1",
    )

    assert preview["applyRequired"] is True
    assert preview["initialChargeAuthorized"] is False
    assert preview["providerRequest"]["body"]["subscription"]["components"] == [
        {"component_id": 85654, "allocated_quantity": 1}
    ]
    assert applied["verified"] is True
    assert applied["subscriptionId"] == 8801
    assert applied["balanceReadback"]["openInvoiceBalanceCents"] == 0
    assert applied["componentReadback"] == {
        "componentId": 85654,
        "allocatedQuantity": 1,
    }
    journal = (tmp_path / "maxio.jsonl").read_text(encoding="utf-8")
    assert '"status":"pending"' in journal
    assert '"status":"accepted"' in journal


def test_subscription_creation_rejects_expired_payment_profile_and_immediate_billing(
    tmp_path: Path,
) -> None:
    session = SubscriptionCreationSession()
    client = ScopedMaxioClient(
        MaxioSettings(
            "https://example.chargify.com",
            "secret",
            tmp_path / "maxio.jsonl",
        ),
        session=session,
    )
    with pytest.raises(MaxioScopeError, match="15 minutes"):
        client.subscription_creation_preview(
            9001,
            "A-1567396",
            7001,
            3655664,
            85654,
            1,
            13_999,
            datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "347395",
        )
    session.expiration_year = datetime.now(timezone.utc).year - 1
    with pytest.raises(MaxioScopeError, match="expired"):
        client.subscription_creation_preview(
            9001,
            "A-1567396",
            7001,
            3655664,
            85654,
            1,
            13_999,
            (datetime.now(timezone.utc) + timedelta(days=14)).isoformat(
                timespec="seconds"
            ),
            "347395",
        )


def test_subscription_creation_tools_are_registered_for_billing_and_coding() -> None:
    for lane in ("billing_agent", "coding_agent"):
        mcp = build_mcp(lane, _client()[0])
        names = set(mcp._tool_manager._tools)
        assert "maxio_subscription_creation_preview" in names
        assert "maxio_subscription_creation_apply" in names


def test_payment_profile_assignment_is_customer_scoped_and_verified(tmp_path: Path) -> None:
    session = PaymentReactivationSession()
    client = ScopedMaxioClient(
        MaxioSettings(
            base_url="https://example.chargify.com",
            api_key="secret",
            journal_path=tmp_path / "journal.jsonl",
        ),
        session=session,
    )

    preview = client.subscription_payment_profile_assignment_preview(
        77, 9001, 7002, "347607"
    )
    assert preview["applyRequired"] is True
    assert preview["targetPaymentProfile"]["maskedNumber"].endswith("7002")
    assert preview["rawPaymentDetailsAccepted"] is False

    applied = client.apply_subscription_payment_profile_assignment(
        77,
        9001,
        7002,
        "347607",
        preview_hash=preview["previewHash"],
        idempotency_key="ticket-347607-profile-v1",
    )
    assert applied["verified"] is True
    assert applied["readbackPaymentProfileId"] == 7002
    assert session.subscription["payment_profile"]["id"] == 7002
    duplicate = client.apply_subscription_payment_profile_assignment(
        77,
        9001,
        7002,
        "347607",
        preview_hash=preview["previewHash"],
        idempotency_key="ticket-347607-profile-v1",
    )
    assert duplicate["duplicate"] is True
    assert duplicate["updated"] is False

    with pytest.raises(MaxioScopeError, match="different Maxio customer"):
        client.subscription_payment_profile_assignment_preview(77, 9999, 7002, "347607")


def test_payment_profile_assignment_surfaces_provider_rejection_without_unsupported_fallback(
    tmp_path: Path,
) -> None:
    session = PaymentReactivationSession(reject_change_without_current=True)
    session.subscription.pop("payment_profile")
    client = ScopedMaxioClient(
        MaxioSettings(
            base_url="https://example.chargify.com",
            api_key="secret",
            journal_path=tmp_path / "journal.jsonl",
        ),
        session=session,
    )

    preview = client.subscription_payment_profile_assignment_preview(
        77, 9001, 7002, "347697"
    )
    assert preview["currentPaymentProfileId"] is None
    assert preview["applyRequired"] is True

    applied = client.apply_subscription_payment_profile_assignment(
        77,
        9001,
        7002,
        "347697",
        preview_hash=preview["previewHash"],
        idempotency_key="ticket-347697-profile-v1",
    )
    assert applied["verified"] is False
    assert applied["status"] == "failed"
    assert applied["assignmentMethod"] == "change_default_payment_profile"
    assert applied["providerStatusCode"] == 422
    assert applied["providerErrors"] == ["A current payment profile is required"]
    assert [
        (method, url.rsplit("/", 1)[-1])
        for method, url, _kwargs in session.calls
        if method in {"POST", "PUT"}
    ] == [
        ("POST", "change_payment_profile.json"),
    ]


def test_payment_profile_assignment_requires_complete_billing_address_when_product_does(
    tmp_path: Path,
) -> None:
    session = PaymentReactivationSession()
    session.subscription["product"] = {"id": 44, "require_billing_address": True}
    session.profiles[1]["payment_profile"].update(
        {
            "billing_address": "1 Main St",
            "billing_city": "Example",
            "billing_zip": "10001",
            "billing_country": "",
        }
    )
    client = ScopedMaxioClient(
        MaxioSettings(
            base_url="https://example.chargify.com",
            api_key="secret",
            journal_path=tmp_path / "journal.jsonl",
        ),
        session=session,
    )

    with pytest.raises(MaxioScopeError, match="billing country"):
        client.subscription_payment_profile_assignment_preview(
            77, 9001, 7002, "347697"
        )

    assert not any(method in {"POST", "PUT"} for method, _url, _kwargs in session.calls)


def test_payment_profile_assignment_allows_incomplete_address_noop_readback(
    tmp_path: Path,
) -> None:
    session = PaymentReactivationSession(current_profile_id=7002)
    session.subscription["product"] = {"id": 44, "require_billing_address": True}
    client = ScopedMaxioClient(
        MaxioSettings(
            base_url="https://example.chargify.com",
            api_key="secret",
            journal_path=tmp_path / "journal.jsonl",
        ),
        session=session,
    )

    preview = client.subscription_payment_profile_assignment_preview(
        77, 9001, 7002, "347697"
    )

    assert preview["applyRequired"] is False
    assert preview["currentPaymentProfileId"] == 7002


@pytest.mark.parametrize("profile_field", ["credit_card", "bank_account"])
def test_payment_profile_assignment_reads_maxio_payment_method_shapes(
    tmp_path: Path,
    profile_field: str,
) -> None:
    session = PaymentReactivationSession()
    session.subscription.pop("payment_profile")
    session.subscription[profile_field] = {"id": 7002}
    client = ScopedMaxioClient(
        MaxioSettings(
            base_url="https://example.chargify.com",
            api_key="secret",
            journal_path=tmp_path / f"{profile_field}.jsonl",
        ),
        session=session,
    )

    preview = client.subscription_payment_profile_assignment_preview(
        77, 9001, 7002, "347697"
    )

    assert preview["currentPaymentProfileId"] == 7002
    assert preview["applyRequired"] is False


def test_secure_payment_update_request_returns_followup_without_raw_card_data(
    tmp_path: Path,
) -> None:
    session = PaymentReactivationSession()
    client = ScopedMaxioClient(
        MaxioSettings(
            base_url="https://example.chargify.com",
            api_key="secret",
            journal_path=tmp_path / "journal.jsonl",
        ),
        session=session,
    )

    preview = client.payment_profile_update_request_preview(77, 9001, "347607")
    assert preview["customerEmail"] == "b******@example.com"
    assert preview["rawPaymentDetailsAccepted"] is False
    applied = client.apply_payment_profile_update_request(
        77,
        9001,
        "347607",
        preview_hash=preview["previewHash"],
        idempotency_key="ticket-347607-update-email-v1",
    )
    assert applied["verified"] is True
    assert applied["followupRequired"] is True
    assert applied["retryAllowed"] is False


def test_subscription_reactivation_is_previewed_charged_once_and_verified(
    tmp_path: Path,
) -> None:
    session = PaymentReactivationSession(current_profile_id=7002)
    client = ScopedMaxioClient(
        MaxioSettings(
            base_url="https://example.chargify.com",
            api_key="secret",
            journal_path=tmp_path / "journal.jsonl",
        ),
        session=session,
    )

    preview = client.subscription_reactivation_preview(
        77, 9001, 7002, "new_billing_period", 12_999, "347607"
    )
    assert preview["applyRequired"] is True
    assert preview["paymentAttemptExpected"] is True
    applied = client.apply_subscription_reactivation(
        77,
        9001,
        7002,
        "new_billing_period",
        12_999,
        "347607",
        preview_hash=preview["previewHash"],
        idempotency_key="ticket-347607-reactivate-v1",
    )
    assert applied["verified"] is True
    assert applied["successfulPaymentVerified"] is True
    assert applied["downstreamActivationAllowed"] is True
    assert applied["status"] == "collected_and_reactivated"
    assert applied["readbackState"] == "active"
    assert applied["retryAllowed"] is False
    duplicate = client.apply_subscription_reactivation(
        77,
        9001,
        7002,
        "new_billing_period",
        12_999,
        "347607",
        preview_hash=preview["previewHash"],
        idempotency_key="ticket-347607-reactivate-v1",
    )
    assert duplicate["duplicate"] is True
    assert duplicate["updated"] is False
    assert sum(
        method == "PUT" and url.endswith("/subscriptions/77/reactivate.json")
        for method, url, _kwargs in session.calls
    ) == 1
    assert not any(
        method == "DELETE" and url.endswith("/subscriptions/77.json")
        for method, url, _kwargs in session.calls
    )

    failed_session = PaymentReactivationSession(current_profile_id=7002)
    failed_client = ScopedMaxioClient(
        MaxioSettings(
            base_url="https://example.chargify.com",
            api_key="secret",
            journal_path=tmp_path / "failed.jsonl",
        ),
        session=failed_session,
    )
    with pytest.raises(MaxioScopeError, match="authorized_charge_cents"):
        failed_client.subscription_reactivation_preview(
            77, 9001, 7002, "new_billing_period", 0, "347607"
        )


def test_no_charge_reactivation_uses_one_credit_and_verifies_future_billing(
    tmp_path: Path,
) -> None:
    session = NoChargeReactivationSession()
    client = ScopedMaxioClient(
        MaxioSettings(
            base_url="https://example.chargify.com",
            api_key="secret",
            journal_path=tmp_path / "no-charge-reactivation.jsonl",
        ),
        session=session,
    )
    next_billing_at = (
        datetime.now(timezone.utc) + timedelta(days=5)
    ).isoformat(timespec="seconds")

    preview = client.subscription_no_charge_reactivation_preview(
        77,
        9001,
        13_999,
        next_billing_at,
        "347630",
    )
    assert preview["applyRequired"] is True
    assert preview["customerChargeCents"] == 0
    assert preview["paymentAttemptExpected"] is False
    assert preview["serviceCreditCoversReactivationCharge"] is True

    applied = client.apply_subscription_no_charge_reactivation(
        77,
        9001,
        13_999,
        next_billing_at,
        "347630",
        preview_hash=preview["previewHash"],
        idempotency_key="ticket-347630-no-charge-reactivation-v1",
    )
    assert applied["verified"] is True
    assert applied["status"] == "credited_reactivated_and_scheduled"
    assert applied["readbackState"] == "active"
    assert applied["customerChargeCents"] == 0
    assert applied["serviceCreditIssuedCents"] == 13_999
    assert applied["serviceCreditConsumedCents"] == 13_999
    assert applied["downstreamActivationAllowed"] is True
    assert applied["balances"]["serviceCreditBalanceCents"] == 0

    duplicate = client.apply_subscription_no_charge_reactivation(
        77,
        9001,
        13_999,
        next_billing_at,
        "347630",
        preview_hash=preview["previewHash"],
        idempotency_key="ticket-347630-no-charge-reactivation-v1",
    )
    assert duplicate["duplicate"] is True
    assert duplicate["updated"] is False
    assert sum(
        method == "POST" and url.endswith("/subscriptions/77/service_credits.json")
        for method, url, _kwargs in session.calls
    ) == 1
    assert sum(
        method == "PUT" and url.endswith("/subscriptions/77/reactivate.json")
        for method, url, _kwargs in session.calls
    ) == 1
    assert sum(
        method == "PUT" and url.endswith("/subscriptions/77.json")
        for method, url, _kwargs in session.calls
    ) == 1


def test_no_charge_reactivation_rejects_wrong_waiver_and_nonzero_starting_balance(
    tmp_path: Path,
) -> None:
    session = NoChargeReactivationSession()
    client = ScopedMaxioClient(
        MaxioSettings(
            base_url="https://example.chargify.com",
            api_key="secret",
            journal_path=tmp_path / "no-charge-rejections.jsonl",
        ),
        session=session,
    )
    next_billing_at = (
        datetime.now(timezone.utc) + timedelta(days=5)
    ).isoformat(timespec="seconds")

    with pytest.raises(MaxioScopeError, match="exact current reactivation charge"):
        client.subscription_no_charge_reactivation_preview(
            77,
            9001,
            9_999,
            next_billing_at,
            "347630",
        )
    session.service_credit_balance_in_cents = 100
    with pytest.raises(MaxioScopeError, match="zero starting"):
        client.subscription_no_charge_reactivation_preview(
            77,
            9001,
            13_999,
            next_billing_at,
            "347630",
        )


@pytest.mark.parametrize("decline,omit_collection", [(True, False), (False, True)])
def test_subscription_reactivation_fails_closed_without_successful_payment(
    tmp_path: Path,
    decline: bool,
    omit_collection: bool,
) -> None:
    session = PaymentReactivationSession(
        current_profile_id=7002,
        decline=decline,
        omit_collection=omit_collection,
    )
    client = ScopedMaxioClient(
        MaxioSettings(
            base_url="https://example.chargify.com",
            api_key="secret",
            journal_path=tmp_path / "failed-reactivation.jsonl",
        ),
        session=session,
    )
    preview = client.subscription_reactivation_preview(
        77, 9001, 7002, "new_billing_period", 12_999, "347607"
    )

    result = client.apply_subscription_reactivation(
        77,
        9001,
        7002,
        "new_billing_period",
        12_999,
        "347607",
        preview_hash=preview["previewHash"],
        idempotency_key="ticket-347607-fail-closed-v1",
    )

    assert result["ok"] is False
    assert result["successfulPaymentVerified"] is False
    assert result["downstreamActivationAllowed"] is False
    assert result["rollbackPerformed"] is True
    assert result["readbackState"] == "canceled"
    assert result["retryAllowed"] is False
    assert sum(
        method == "PUT" and url.endswith("/subscriptions/77/reactivate.json")
        for method, url, _kwargs in session.calls
    ) == 1
    assert sum(
        method == "DELETE" and url.endswith("/subscriptions/77.json")
        for method, url, _kwargs in session.calls
    ) == 1

    duplicate = client.apply_subscription_reactivation(
        77,
        9001,
        7002,
        "new_billing_period",
        12_999,
        "347607",
        preview_hash=preview["previewHash"],
        idempotency_key="ticket-347607-fail-closed-v1",
    )
    assert duplicate["duplicate"] is True
    assert duplicate["downstreamActivationAllowed"] is False
    assert sum(
        method == "PUT" and url.endswith("/subscriptions/77/reactivate.json")
        for method, url, _kwargs in session.calls
    ) == 1


def test_subscription_reactivation_recovers_after_provider_success_without_second_charge(
    monkeypatch,
    tmp_path: Path,
) -> None:
    session = PaymentReactivationSession(current_profile_id=7002)
    client = ScopedMaxioClient(
        MaxioSettings(
            base_url="https://example.chargify.com",
            api_key="secret",
            journal_path=tmp_path / "restart-recovery.jsonl",
        ),
        session=session,
    )
    preview = client.subscription_reactivation_preview(
        77, 9001, 7002, "new_billing_period", 12_999, "347607"
    )
    original_journal = client._journal
    failed_final_receipt = False

    def interrupt_after_provider(status, key, method, path, request_hash, evidence):
        nonlocal failed_final_receipt
        if method == "RESULT" and not failed_final_receipt:
            failed_final_receipt = True
            raise RuntimeError("simulated restart before final gate receipt")
        return original_journal(status, key, method, path, request_hash, evidence)

    monkeypatch.setattr(client, "_journal", interrupt_after_provider)
    with pytest.raises(RuntimeError, match="simulated restart"):
        client.apply_subscription_reactivation(
            77,
            9001,
            7002,
            "new_billing_period",
            12_999,
            "347607",
            preview_hash=preview["previewHash"],
            idempotency_key="ticket-347607-restart-recovery-v1",
        )
    monkeypatch.setattr(client, "_journal", original_journal)

    recovered = client.apply_subscription_reactivation(
        77,
        9001,
        7002,
        "new_billing_period",
        12_999,
        "347607",
        preview_hash=preview["previewHash"],
        idempotency_key="ticket-347607-restart-recovery-v1",
    )

    assert recovered["verified"] is True
    assert recovered["successfulPaymentVerified"] is True
    assert recovered["downstreamActivationAllowed"] is True
    assert recovered["providerCallSkippedOnRecovery"] is True
    assert recovered["providerReceiptStatus"] == "accepted"
    assert recovered["duplicate"] is True
    assert recovered["updated"] is False
    assert sum(
        method == "PUT" and url.endswith("/subscriptions/77/reactivate.json")
        for method, url, _kwargs in session.calls
    ) == 1
    assert not any(
        method == "DELETE" and url.endswith("/subscriptions/77.json")
        for method, url, _kwargs in session.calls
    )


def test_subscription_reactivation_recovery_never_starts_an_unrecorded_second_attempt(
    monkeypatch,
    tmp_path: Path,
) -> None:
    session = PaymentReactivationSession(current_profile_id=7002)
    client = ScopedMaxioClient(
        MaxioSettings(
            base_url="https://example.chargify.com",
            api_key="secret",
            journal_path=tmp_path / "pre-provider-recovery.jsonl",
        ),
        session=session,
    )
    preview = client.subscription_reactivation_preview(
        77, 9001, 7002, "new_billing_period", 12_999, "347607"
    )
    original_api_request = client.api_request

    def interrupt_before_provider(*_args, **_kwargs):
        raise MaxioUnavailableError("simulated restart before provider call")

    monkeypatch.setattr(client, "api_request", interrupt_before_provider)
    with pytest.raises(MaxioUnavailableError, match="before provider call"):
        client.apply_subscription_reactivation(
            77,
            9001,
            7002,
            "new_billing_period",
            12_999,
            "347607",
            preview_hash=preview["previewHash"],
            idempotency_key="ticket-347607-pre-provider-v1",
        )
    monkeypatch.setattr(client, "api_request", original_api_request)

    recovered = client.apply_subscription_reactivation(
        77,
        9001,
        7002,
        "new_billing_period",
        12_999,
        "347607",
        preview_hash=preview["previewHash"],
        idempotency_key="ticket-347607-pre-provider-v1",
    )

    assert recovered["ok"] is False
    assert recovered["status"] == "payment_not_verified"
    assert recovered["downstreamActivationAllowed"] is False
    assert recovered["providerCallSkippedOnRecovery"] is True
    assert recovered["providerReceiptStatus"] == "not_recorded"
    assert recovered["retryAllowed"] is False
    assert not any(
        method == "PUT" and url.endswith("/subscriptions/77/reactivate.json")
        for method, url, _kwargs in session.calls
    )


def test_payment_and_reactivation_tools_are_billing_only() -> None:
    client, _ = _client({})
    billing = build_mcp("billing_agent", client)
    coding = build_mcp("coding_agent", client)
    tool_names = {
        "maxio_subscription_payment_profile_assignment_preview",
        "maxio_subscription_payment_profile_assignment_apply",
        "maxio_payment_profile_update_request_preview",
        "maxio_payment_profile_update_request_apply",
        "maxio_subscription_reactivation_preview",
        "maxio_subscription_reactivation_apply",
        "maxio_subscription_no_charge_reactivation_preview",
        "maxio_subscription_no_charge_reactivation_apply",
        "maxio_nova_integrated_products",
        "maxio_nova_integrated_promo_credit_preview",
        "maxio_nova_integrated_promo_credit_apply",
    }
    assert tool_names.issubset(billing._tool_manager._tools)
    assert not tool_names.intersection(coding._tool_manager._tools)


def test_manual_credit_is_separate_exact_and_verified_for_next_invoice(
    tmp_path: Path,
) -> None:
    session = FinancialWorkflowSession()
    client = ScopedMaxioClient(
        MaxioSettings(
            "https://example.chargify.com",
            "secret",
            tmp_path / "journal.jsonl",
        ),
        session=session,
    )

    credit_preview = client.manual_service_credit_preview(77, 27_998, "347333")
    assert credit_preview["currentServiceCreditBalanceCents"] == 0
    assert credit_preview["expectedServiceCreditBalanceCents"] == 27_998
    assert credit_preview["allocationChangeIncluded"] is False
    assert credit_preview["invoiceApplicationIncluded"] is False

    credit = client.apply_manual_service_credit(
        77,
        27_998,
        "347333",
        preview_hash=credit_preview["previewHash"],
        idempotency_key="ticket-347333-manual-credit-27998",
    )
    assert credit["verified"] is True
    assert credit["afterServiceCreditBalanceCents"] == 27_998
    issue_call = next(call for call in session.calls if call[1].endswith("/service_credits.json"))
    assert issue_call[2]["json"] == {
        "service_credit": {
            "amount": "279.98",
            "memo": "Ticket 347333: manually validated service credit",
        }
    }
    assert credit["invoiceApplicationIncluded"] is False
    assert all(not call[1].endswith("/payments.json") for call in session.calls)


def test_nova_integrated_product_catalog_has_only_the_four_allowed_providers(
    tmp_path: Path,
) -> None:
    session = NovaIntegratedPromoSession()
    client = ScopedMaxioClient(
        MaxioSettings(
            "https://example.chargify.com",
            "secret",
            tmp_path / "journal.jsonl",
        ),
        session=session,
    )

    catalog = client.nova_integrated_products()

    assert catalog["allowedMerchantProviders"] == [
        "Worldpay",
        "Creditcall",
        "Authorize.net",
        "Propelr",
    ]
    assert {row["merchantProvider"] for row in catalog["products"]} == {
        "Worldpay",
        "Creditcall",
        "Authorize.net",
        "Propelr",
    }
    assert [row["name"] for row in catalog["unmatchedProducts"]] == [
        "Nova Integrated GSPaytech"
    ]
    assert catalog["fallbackProviderAllowed"] is False


def test_nova_integrated_promo_credit_is_location_isolated_ticket_bound_and_verified(
    tmp_path: Path,
) -> None:
    session = NovaIntegratedPromoSession()
    client = ScopedMaxioClient(
        MaxioSettings(
            "https://example.chargify.com",
            "secret",
            tmp_path / "journal.jsonl",
        ),
        session=session,
    )

    preview = client.nova_integrated_promo_credit_preview(
        77,
        1,
        "Worldpay",
        9_999,
        "347353",
    )
    assert preview["creditAmountCents"] == 29_997
    assert preview["freeMonths"] == 3
    assert preview["componentQuantity"] == 1
    assert preview["memo"] == "Nova Integrated Promo | Ticket 347353 | Location 1"
    assert preview["accountFlatRateMutationIncluded"] is False

    result = client.apply_nova_integrated_promo_credit(
        77,
        1,
        "Worldpay",
        9_999,
        "347353",
        preview_hash=preview["previewHash"],
        idempotency_key="ticket-347353-location-1-promo-credit-v1",
    )
    assert result["verified"] is True
    assert result["afterServiceCreditBalanceCents"] == 29_997
    issue_call = next(
        call
        for call in session.calls
        if call[0] == "POST" and call[1].endswith("/service_credits.json")
    )
    assert issue_call[2]["json"] == {
        "service_credit": {
            "amount": "299.97",
            "memo": "Nova Integrated Promo | Ticket 347353 | Location 1",
        }
    }

    duplicate = client.nova_integrated_promo_credit_preview(
        77,
        1,
        "Worldpay",
        9_999,
        "347353",
    )
    assert duplicate["status"] == "already_applied"
    assert duplicate["applyRequired"] is False


def test_nova_integrated_promo_rejects_missing_provider_and_rate_mismatch(
    tmp_path: Path,
) -> None:
    client = ScopedMaxioClient(
        MaxioSettings(
            "https://example.chargify.com",
            "secret",
            tmp_path / "journal.jsonl",
        ),
        session=NovaIntegratedPromoSession(),
    )

    with pytest.raises(MaxioScopeError, match="merchant_provider is required"):
        client.nova_integrated_promo_credit_preview(77, 1, "", 9_999, "347353")
    with pytest.raises(MaxioScopeError, match="must match the exact"):
        client.nova_integrated_promo_credit_preview(
            77,
            1,
            "Worldpay",
            12_999,
            "347353",
        )


def test_partial_location_collection_is_exact_previewed_and_verified(
    tmp_path: Path,
) -> None:
    session = PartialLocationCollectionSession()
    client = ScopedMaxioClient(
        MaxioSettings(
            "https://example.chargify.com",
            "secret",
            tmp_path / "journal.jsonl",
        ),
        session=session,
    )

    preview = client.partial_location_collection_preview(
        77,
        3,
        13_499,
        40_497,
        "2026-07-02",
        "2026-08-02",
        "347465",
    )
    assert preview["applyRequired"] is True
    assert preview["totalActiveLocations"] == 5
    assert preview["componentId"] == 1538219
    assert preview["balances"] == {
        "openInvoiceBalanceCents": 0,
        "pendingInvoiceBalanceCents": 0,
        "pendingDiscountBalanceCents": 0,
        "serviceCreditBalanceCents": 0,
        "prepaymentBalanceCents": 0,
    }
    assert preview["collectionControls"] == {
        "delayCapture": False,
        "accrueOnFailure": False,
        "useNegativeBalance": False,
        "taxable": False,
        "paymentCollectionMethod": "automatic",
        "allocationChange": False,
        "retryAfterAttempt": False,
    }

    applied = client.apply_partial_location_collection(
        77,
        3,
        13_499,
        40_497,
        "2026-07-02",
        "2026-08-02",
        "347465",
        preview_hash=preview["previewHash"],
        idempotency_key="ticket-347465-partial-location-collection-v1",
    )
    assert applied["ok"] is True
    assert applied["verified"] is True
    assert applied["status"] == "collected"
    assert applied["chargeTransaction"]["id"] == 901
    assert applied["paymentTransaction"]["id"] == 902
    assert applied["balances"] == preview["balances"]
    issue_calls = [
        call for call in session.calls if call[1].endswith("/subscriptions/77/charges.json")
    ]
    assert len(issue_calls) == 1
    assert issue_calls[0][2]["json"] == {
        "charge": {
            "amount_in_cents": 40_497,
            "memo": (
                "Ticket 347465: partial location recovery 3 x 134.99 "
                "for 2026-07-02 through 2026-08-02"
            ),
            "delay_capture": False,
            "accrue_on_failure": False,
            "use_negative_balance": False,
            "taxable": False,
            "payment_collection_method": "automatic",
            "period_range_start": "2026-07-02",
            "period_range_end": "2026-08-02",
        }
    }
    duplicate = client.apply_partial_location_collection(
        77,
        3,
        13_499,
        40_497,
        "2026-07-02",
        "2026-08-02",
        "347465",
        preview_hash=preview["previewHash"],
        idempotency_key="ticket-347465-partial-location-collection-v2",
    )
    assert duplicate["ok"] is True
    assert duplicate["duplicate"] is True
    assert len(
        [call for call in session.calls if call[1].endswith("/subscriptions/77/charges.json")]
    ) == 1


def test_partial_location_collection_decline_never_accrues_or_retries(
    tmp_path: Path,
) -> None:
    session = PartialLocationCollectionSession(decline=True)
    client = ScopedMaxioClient(
        MaxioSettings(
            "https://example.chargify.com",
            "secret",
            tmp_path / "journal.jsonl",
        ),
        session=session,
    )
    preview = client.partial_location_collection_preview(
        77, 3, 13_499, 40_497, "2026-07-02", "2026-08-02", "347465"
    )
    declined = client.apply_partial_location_collection(
        77,
        3,
        13_499,
        40_497,
        "2026-07-02",
        "2026-08-02",
        "347465",
        preview_hash=preview["previewHash"],
        idempotency_key="ticket-347465-partial-location-decline-v1",
    )
    assert declined["ok"] is False
    assert declined["status"] == "declined"
    assert declined["verified"] is True
    assert declined["retryAllowed"] is False
    assert all(value == 0 for value in declined["balances"].values())

    new_preview = client.partial_location_collection_preview(
        77, 3, 13_499, 40_497, "2026-07-02", "2026-08-02", "347465"
    )
    blocked = client.apply_partial_location_collection(
        77,
        3,
        13_499,
        40_497,
        "2026-07-02",
        "2026-08-02",
        "347465",
        preview_hash=new_preview["previewHash"],
        idempotency_key="ticket-347465-partial-location-decline-v2",
    )
    assert blocked["status"] == "previous_attempt_not_retried"
    assert blocked["retryAllowed"] is False
    assert len(
        [call for call in session.calls if call[1].endswith("/subscriptions/77/charges.json")]
    ) == 1


def test_partial_location_collection_rejects_amount_and_state_mismatches(
    tmp_path: Path,
) -> None:
    session = PartialLocationCollectionSession()
    client = ScopedMaxioClient(
        MaxioSettings(
            "https://example.chargify.com",
            "secret",
            tmp_path / "journal.jsonl",
        ),
        session=session,
    )
    with pytest.raises(MaxioScopeError, match="multiplied"):
        client.partial_location_collection_preview(
            77, 3, 13_499, 40_496, "2026-07-02", "2026-08-02", "347465"
        )
    session.subscription["current_billing_amount_in_cents"] = 67_494
    with pytest.raises(MaxioScopeError, match="current subscription billing amount"):
        client.partial_location_collection_preview(
            77, 3, 13_499, 40_497, "2026-07-02", "2026-08-02", "347465"
        )


def test_billing_cycle_recovery_is_exact_historical_previewed_and_verified(
    tmp_path: Path,
) -> None:
    session = PartialLocationCollectionSession()
    client = ScopedMaxioClient(
        MaxioSettings(
            "https://example.chargify.com",
            "secret",
            tmp_path / "journal.jsonl",
        ),
        session=session,
    )

    preview = client.billing_cycle_recovery_preview(
        77,
        2,
        67_495,
        134_990,
        "2026-05-02",
        "2026-07-02",
        "347464",
    )
    assert preview["status"] == "preview"
    assert preview["applyRequired"] is True
    assert preview["cycleCount"] == 2
    assert preview["cycleAmountCents"] == 67_495
    assert preview["currentPeriodStart"] == "2026-07-02"
    assert preview["collectionControls"]["retryAfterAttempt"] is False

    applied = client.apply_billing_cycle_recovery(
        77,
        2,
        67_495,
        134_990,
        "2026-05-02",
        "2026-07-02",
        "347464",
        preview_hash=preview["previewHash"],
        idempotency_key="ticket-347464-billing-cycle-recovery-v1",
    )
    assert applied["ok"] is True
    assert applied["verified"] is True
    assert applied["status"] == "collected"
    assert applied["chargeTransaction"]["id"] == 901
    assert applied["paymentTransaction"]["id"] == 902
    issue_calls = [
        call for call in session.calls if call[1].endswith("/subscriptions/77/charges.json")
    ]
    assert len(issue_calls) == 1
    assert issue_calls[0][2]["json"] == {
        "charge": {
            "amount_in_cents": 134_990,
            "memo": (
                "Ticket 347464: missed billing cycle recovery 2 x 674.95 "
                "for 2026-05-02 through 2026-07-02"
            ),
            "delay_capture": False,
            "accrue_on_failure": False,
            "use_negative_balance": False,
            "taxable": False,
            "payment_collection_method": "automatic",
            "period_range_start": "2026-05-02",
            "period_range_end": "2026-07-02",
        }
    }

    duplicate = client.apply_billing_cycle_recovery(
        77,
        2,
        67_495,
        134_990,
        "2026-05-02",
        "2026-07-02",
        "347464",
        preview_hash=preview["previewHash"],
        idempotency_key="ticket-347464-billing-cycle-recovery-v2",
    )
    assert duplicate["ok"] is True
    assert duplicate["duplicate"] is True
    assert len(
        [call for call in session.calls if call[1].endswith("/subscriptions/77/charges.json")]
    ) == 1


def test_billing_cycle_recovery_rejects_amount_period_and_current_rate_mismatches(
    tmp_path: Path,
) -> None:
    session = PartialLocationCollectionSession()
    client = ScopedMaxioClient(
        MaxioSettings(
            "https://example.chargify.com",
            "secret",
            tmp_path / "journal.jsonl",
        ),
        session=session,
    )
    with pytest.raises(MaxioScopeError, match="multiplied"):
        client.billing_cycle_recovery_preview(
            77, 2, 67_495, 134_989, "2026-05-02", "2026-07-02", "347464"
        )
    with pytest.raises(MaxioScopeError, match="14 days or fewer"):
        client.billing_cycle_recovery_preview(
            77, 1, 67_495, 67_495, "2026-07-02", "2026-08-02", "347464"
        )
    with pytest.raises(MaxioScopeError, match="monthly cycle count"):
        client.billing_cycle_recovery_preview(
            77, 2, 67_495, 134_990, "2026-06-01", "2026-07-02", "347464"
        )
    with pytest.raises(MaxioScopeError, match="current subscription billing amount"):
        client.billing_cycle_recovery_preview(
            77, 2, 11_999, 23_998, "2026-05-02", "2026-07-02", "347464"
        )


def test_billing_cycle_recovery_allows_only_an_unbilled_replacement_stub(
    tmp_path: Path,
) -> None:
    session = PartialLocationCollectionSession()
    session.subscription.update(
        {
            "current_billing_amount_in_cents": 13_999,
            "current_period_started_at": "2026-07-29T00:00:00-04:00",
            "current_period_ends_at": "2026-08-04T00:00:00-04:00",
            "next_assessment_at": "2026-08-04T00:00:00-04:00",
        }
    )
    session.transactions = []
    client = ScopedMaxioClient(
        MaxioSettings(
            "https://example.chargify.com",
            "secret",
            tmp_path / "journal.jsonl",
        ),
        session=session,
    )

    preview = client.billing_cycle_recovery_preview(
        77,
        2,
        13_999,
        27_998,
        "2026-06-04",
        "2026-08-04",
        "347460",
    )

    assert preview["currentPeriodOverlapDays"] == 6
    assert preview["collectionControls"]["replacementStubMustBeUnbilled"] is True
    assert preview["collectionControls"]["replacementStubOverlapDays"] == 6

    applied = client.apply_billing_cycle_recovery(
        77,
        2,
        13_999,
        27_998,
        "2026-06-04",
        "2026-08-04",
        "347460",
        preview_hash=preview["previewHash"],
        idempotency_key="ticket-347460-billing-cycle-recovery-v1",
    )
    assert applied["verified"] is True
    duplicate = client.apply_billing_cycle_recovery(
        77,
        2,
        13_999,
        27_998,
        "2026-06-04",
        "2026-08-04",
        "347460",
        preview_hash=preview["previewHash"],
        idempotency_key="ticket-347460-billing-cycle-recovery-v2",
    )
    assert duplicate["duplicate"] is True

    paid_stub_session = PartialLocationCollectionSession()
    paid_stub_session.subscription.update(session.subscription)
    paid_stub_session.transactions = [
        {
            "transaction": {
                "id": 905,
                "subscription_id": 77,
                "transaction_type": "payment",
                "success": True,
                "amount_in_cents": 1_999,
                "memo": "Replacement subscription stub payment",
                "created_at": "2026-07-29T08:00:00-04:00",
            }
        }
    ]
    paid_stub_client = ScopedMaxioClient(
        MaxioSettings(
            "https://example.chargify.com",
            "secret",
            tmp_path / "paid-stub-journal.jsonl",
        ),
        session=paid_stub_session,
    )
    with pytest.raises(MaxioScopeError, match="already has a successful"):
        paid_stub_client.billing_cycle_recovery_preview(
            77,
            2,
            13_999,
            27_998,
            "2026-06-04",
            "2026-08-04",
            "347460",
        )


def test_billing_cycle_recovery_can_preserve_exact_open_invoice_on_decline(
    tmp_path: Path,
) -> None:
    session = PartialLocationCollectionSession(decline=True)
    client = ScopedMaxioClient(
        MaxioSettings(
            "https://example.chargify.com",
            "secret",
            tmp_path / "journal.jsonl",
        ),
        session=session,
    )
    preview = client.billing_cycle_recovery_preview(
        77,
        2,
        67_495,
        134_990,
        "2026-05-02",
        "2026-07-02",
        "347464",
        "preserve_open_invoice",
    )
    assert preview["declineAction"] == "preserve_open_invoice"
    assert preview["collectionControls"]["accrueOnFailure"] is True

    result = client.apply_billing_cycle_recovery(
        77,
        2,
        67_495,
        134_990,
        "2026-05-02",
        "2026-07-02",
        "347464",
        preview_hash=preview["previewHash"],
        idempotency_key="ticket-347464-preserve-open-invoice-v1",
        decline_action="preserve_open_invoice",
    )

    assert result["status"] == "declined_open_invoice_preserved"
    assert result["verified"] is True
    assert result["retryAllowed"] is False
    assert result["balances"]["openInvoiceBalanceCents"] == 134_990
    assert all(
        value == 0
        for key, value in result["balances"].items()
        if key != "openInvoiceBalanceCents"
    )


def test_billing_cycle_recovery_tool_forces_decline_invoice_and_activation_gate(
    tmp_path: Path,
) -> None:
    session = PartialLocationCollectionSession(decline=True)
    client = ScopedMaxioClient(
        MaxioSettings(
            "https://example.chargify.com",
            "secret",
            tmp_path / "journal.jsonl",
        ),
        session=session,
    )
    mcp = build_mcp("billing_agent", client)
    preview_tool = mcp._tool_manager._tools["maxio_billing_cycle_recovery_preview"]
    apply_tool = mcp._tool_manager._tools["maxio_billing_cycle_recovery_apply"]

    preview = preview_tool.fn(
        77,
        2,
        67_495,
        134_990,
        "2026-05-02",
        "2026-07-02",
        "347464",
    )
    assert preview["declineAction"] == "preserve_open_invoice"
    assert "decline_action" not in preview_tool.parameters["properties"]

    result = apply_tool.fn(
        77,
        2,
        67_495,
        134_990,
        "2026-05-02",
        "2026-07-02",
        "347464",
        preview["previewHash"],
        "ticket-347464-tool-preserve-open-v1",
    )

    assert result["status"] == "declined_open_invoice_preserved"
    assert result["paymentConfirmed"] is False
    assert result["downstreamActivationAllowed"] is False
    assert result["locationActivationBlocked"] is True
    assert result["retryAllowed"] is False


def test_component_payment_recovery_uses_no_credit_full_charge_and_restores_quantity(
    tmp_path: Path,
) -> None:
    session = ComponentPaymentRecoverySession()
    client = ScopedMaxioClient(
        MaxioSettings(
            "https://example.chargify.com",
            "secret",
            tmp_path / "journal.jsonl",
        ),
        session=session,
    )

    preview = client.component_payment_recovery_preview(
        77,
        85644,
        [1],
        2,
        11_999,
        23_998,
        "347464",
    )

    assert preview["status"] == "preview"
    assert preview["recurringQuantity"] == 1
    assert preview["stagedQuantity"] == 0
    assert preview["recoveryChargeQuantity"] == 2
    assert preview["providerChargePreviewTotalCents"] == 23_998
    assert preview["otherLocationsExposedToDunning"] is False
    assert preview["directOneTimeChargeUsed"] is False

    result = client.apply_component_payment_recovery(
        77,
        85644,
        [1],
        2,
        11_999,
        23_998,
        "347464",
        preview_hash=preview["previewHash"],
        idempotency_key="ticket-347464-component-recovery-v1",
    )

    assert result["status"] == "collected"
    assert result["verified"] is True
    assert result["recurringQuantityRestored"] is True
    assert result["successfulPaymentVerified"] is True
    assert result["downstreamActivationAllowed"] is True
    assert result["directOneTimeChargeUsed"] is False
    assert session.quantity == 1
    allocation_calls = [
        call
        for call in session.calls
        if call[0] == "POST" and call[1].endswith("/allocations.json")
    ]
    assert [call[2]["json"]["allocations"][0]["quantity"] for call in allocation_calls] == [
        0,
        2,
        1,
    ]
    assert allocation_calls[0][2]["json"]["downgrade_credit"] == "none"
    assert allocation_calls[1][2]["json"]["upgrade_charge"] == "full"
    assert allocation_calls[1][2]["json"]["initiate_dunning"] is True
    assert allocation_calls[2][2]["json"]["downgrade_credit"] == "none"
    assert not any(call[1].endswith("/charges.json") for call in session.calls)


def test_component_payment_recovery_decline_initiates_dunning_and_isolates_scope(
    tmp_path: Path,
) -> None:
    session = ComponentPaymentRecoverySession(decline=True)
    client = ScopedMaxioClient(
        MaxioSettings(
            "https://example.chargify.com",
            "secret",
            tmp_path / "journal.jsonl",
        ),
        session=session,
    )
    preview = client.component_payment_recovery_preview(
        77, 85644, [1], 2, 11_999, 23_998, "347464"
    )

    result = client.apply_component_payment_recovery(
        77,
        85644,
        [1],
        2,
        11_999,
        23_998,
        "347464",
        preview_hash=preview["previewHash"],
        idempotency_key="ticket-347464-component-recovery-v1",
    )

    assert result["status"] == "dunning_initiated"
    assert result["verified"] is True
    assert result["dunningInitiated"] is True
    assert result["subscriptionState"] == "past_due"
    assert result["balances"]["openInvoiceBalanceCents"] == 23_998
    assert result["recurringQuantityRestored"] is False
    assert result["successfulPaymentVerified"] is False
    assert result["downstreamActivationAllowed"] is False
    assert result["serviceQuantity"] == 0
    assert session.quantity == 0


def test_component_payment_recovery_pending_collection_fails_closed(
    tmp_path: Path,
) -> None:
    session = ComponentPaymentRecoverySession(pending=True)
    client = ScopedMaxioClient(
        MaxioSettings(
            "https://example.chargify.com",
            "secret",
            tmp_path / "journal.jsonl",
        ),
        session=session,
    )
    preview = client.component_payment_recovery_preview(
        77, 85644, [1], 2, 11_999, 23_998, "347607"
    )

    result = client.apply_component_payment_recovery(
        77,
        85644,
        [1],
        2,
        11_999,
        23_998,
        "347607",
        preview_hash=preview["previewHash"],
        idempotency_key="ticket-347607-component-recovery-pending-v1",
    )

    assert result["status"] == "pending_collection"
    assert result["verified"] is True
    assert result["successfulPaymentVerified"] is False
    assert result["downstreamActivationAllowed"] is False
    assert result["recurringQuantityRestored"] is False
    assert result["serviceQuantity"] == 0
    assert session.quantity == 0
    assert result["balances"]["pendingInvoiceBalanceCents"] == 23_998

    shared_session = ComponentPaymentRecoverySession(location_ids=(1, 2))
    shared_client = ScopedMaxioClient(
        MaxioSettings(
            "https://example.chargify.com",
            "secret",
            tmp_path / "shared-journal.jsonl",
        ),
        session=shared_session,
    )
    with pytest.raises(MaxioScopeError, match="isolated subscription"):
        shared_client.component_payment_recovery_preview(
            77, 85644, [1], 1, 11_999, 11_999, "347464"
        )


def test_component_payment_recovery_restores_quantity_when_stage_is_rejected_after_apply(
    tmp_path: Path,
) -> None:
    session = ComponentPaymentRecoverySession(reject_stage_after_apply=True)
    client = ScopedMaxioClient(
        MaxioSettings(
            "https://example.chargify.com",
            "secret",
            tmp_path / "journal.jsonl",
        ),
        session=session,
    )
    preview = client.component_payment_recovery_preview(
        77, 85644, [1], 2, 11_999, 23_998, "347464"
    )

    result = client.apply_component_payment_recovery(
        77,
        85644,
        [1],
        2,
        11_999,
        23_998,
        "347464",
        preview_hash=preview["previewHash"],
        idempotency_key="ticket-347464-component-recovery-stage-rejected-v1",
    )

    assert result["status"] == "stage_rejected"
    assert result["verified"] is True
    assert result["retryAllowed"] is True
    assert session.quantity == 1
    allocation_calls = [
        call
        for call in session.calls
        if call[0] == "POST" and call[1].endswith("/allocations.json")
    ]
    assert [call[2]["json"]["allocations"][0]["quantity"] for call in allocation_calls] == [
        0,
        1,
    ]
    assert all(call[2]["json"]["upgrade_charge"] == "none" for call in allocation_calls)


def test_invoice_refund_is_exact_previewed_verified_and_never_voids(
    tmp_path: Path,
) -> None:
    session = InvoiceRefundSession()
    client = ScopedMaxioClient(
        MaxioSettings(
            "https://example.chargify.com",
            "secret",
            tmp_path / "journal.jsonl",
        ),
        session=session,
    )
    preview = client.invoice_refund_preview(
        "inv_ticket347463",
        501,
        12_999,
        "347463",
    )
    assert preview["status"] == "preview"
    assert preview["remainingRefundableForPaymentCents"] == 12_999
    assert preview["refundControls"] == {
        "external": False,
        "applyCredit": False,
        "voidInvoice": False,
        "ticketBoundMemo": True,
        "retryAfterAttempt": False,
        "customerEmail": False,
        "subscriptionCancellation": False,
    }

    applied = client.apply_invoice_refund(
        "inv_ticket347463",
        501,
        12_999,
        "347463",
        preview_hash=preview["previewHash"],
        idempotency_key="ticket-347463-invoice-refund-v1",
    )
    assert applied["ok"] is True
    assert applied["verified"] is True
    assert applied["status"] == "refunded"
    assert applied["invoiceRefundAmountCents"] == 12_999
    assert applied["subscriptionCancellationIncluded"] is False
    assert applied["customerEmailIncluded"] is False
    calls = [
        call for call in session.calls if call[1].endswith("/refunds.json")
    ]
    assert len(calls) == 1
    assert calls[0][2]["json"] == {
        "refund": {
            "amount": "129.99",
            "memo": "Ticket 347463: approved invoice refund",
            "payment_id": 501,
            "external": False,
            "apply_credit": False,
            "void_invoice": False,
        }
    }

    duplicate = client.apply_invoice_refund(
        "inv_ticket347463",
        501,
        12_999,
        "347463",
        preview_hash=preview["previewHash"],
        idempotency_key="ticket-347463-invoice-refund-v2",
    )
    assert duplicate["ok"] is True
    assert duplicate["duplicate"] is True
    assert len(
        [call for call in session.calls if call[1].endswith("/refunds.json")]
    ) == 1


def test_invoice_refund_rejects_wrong_payment_and_over_refund(tmp_path: Path) -> None:
    session = InvoiceRefundSession()
    client = ScopedMaxioClient(
        MaxioSettings(
            "https://example.chargify.com",
            "secret",
            tmp_path / "journal.jsonl",
        ),
        session=session,
    )
    with pytest.raises(MaxioScopeError, match="exactly one payment"):
        client.invoice_refund_preview("inv_ticket347463", 999, 1_000, "347463")
    with pytest.raises(MaxioScopeError, match="remaining refundable"):
        client.invoice_refund_preview("inv_ticket347463", 501, 13_000, "347463")


@pytest.mark.parametrize(
    ("path", "body"),
    [
        (
            "/subscriptions/77/allocations.json",
            {"allocations": [], "downgrade_credit": "full"},
        ),
        (
            "/subscriptions/77/service_credits.json",
            {"service_credit": {"amount": "10.00"}},
        ),
        (
            "/subscriptions/77/charges.json",
            {"charge": {"amount_in_cents": 1000, "memo": "unsafe generic charge"}},
        ),
        (
            "/subscriptions/77/service_credit_deductions.json",
            {"service_credit": {"amount": "10.00"}},
        ),
        (
            "/subscriptions/77/add_coupon.json",
            {"codes": ["3FREE"]},
        ),
        (
            "/invoices/inv_ticket347333/payments.json",
            {"type": "service_credit", "payment": {"amount": "10.00"}},
        ),
        (
            "/invoices/inv_ticket347333/credit_notes.json",
            {"credit_note": {"memo": "unsafe generic credit"}},
        ),
        (
            "/invoices/inv_ticket347463/refunds.json",
            {"refund": {"amount": "129.99", "payment_id": 501}},
        ),
    ],
)
def test_generic_api_cannot_bypass_typed_allocation_and_credit_workflow(
    tmp_path: Path,
    path: str,
    body: dict,
) -> None:
    client, _ = _client({}, journal_path=tmp_path / "journal.jsonl")
    with pytest.raises(MaxioScopeError, match="typed|financial path"):
        client.api_request(
            "POST",
            path,
            json_body=body,
            idempotency_key="ticket-347333-generic-financial",
        )


def test_manual_credit_tool_schemas_expose_no_allocation_or_credit_mode_switches() -> None:
    client, _ = _client([])
    mcp = build_mcp("billing_agent", client)
    credit_preview = mcp._tool_manager._tools["maxio_manual_service_credit_preview"]
    credit_apply = mcp._tool_manager._tools["maxio_manual_service_credit_apply"]

    assert set(credit_preview.parameters["properties"]) == {
        "subscription_id",
        "amount_cents",
        "ticket_number",
    }
    assert set(credit_apply.parameters["properties"]) == {
        "subscription_id",
        "amount_cents",
        "ticket_number",
        "preview_hash",
        "idempotency_key",
    }
    assert credit_preview.annotations.readOnlyHint is True
    assert credit_apply.annotations.readOnlyHint is False


def test_component_payment_recovery_tool_schemas_are_fixed_for_both_lanes() -> None:
    expected_preview = {
        "subscription_id",
        "component_id",
        "recovery_location_ids",
        "recovery_charge_quantity",
        "unit_rate_cents",
        "authorized_amount_cents",
        "ticket_number",
    }
    for lane in ("billing_agent", "coding_agent"):
        mcp = build_mcp(lane, _client()[0])
        preview = mcp._tool_manager._tools["maxio_component_payment_recovery_preview"]
        apply = mcp._tool_manager._tools["maxio_component_payment_recovery_apply"]
        assert set(preview.parameters["properties"]) == expected_preview
        assert set(apply.parameters["properties"]) == expected_preview | {
            "preview_hash",
            "idempotency_key",
        }
        assert preview.annotations.readOnlyHint is True
        assert apply.annotations.readOnlyHint is False
        assert apply.annotations.idempotentHint is True


def test_invoice_refund_tool_schema_is_billing_only_and_has_no_effect_switches() -> None:
    billing = build_mcp("billing_agent", _client()[0])
    coding = build_mcp("coding_agent", _client()[0])
    preview = billing._tool_manager._tools["maxio_invoice_refund_preview"]
    apply = billing._tool_manager._tools["maxio_invoice_refund_apply"]
    assert set(preview.parameters["properties"]) == {
        "invoice_uid",
        "payment_id",
        "refund_amount_cents",
        "ticket_number",
    }
    assert set(apply.parameters["properties"]) == {
        "invoice_uid",
        "payment_id",
        "refund_amount_cents",
        "ticket_number",
        "preview_hash",
        "idempotency_key",
    }
    assert "maxio_invoice_refund_preview" not in coding._tool_manager._tools
    assert "maxio_invoice_refund_apply" not in coding._tool_manager._tools
    assert preview.annotations.readOnlyHint is True
    assert apply.annotations.readOnlyHint is False


def test_subscription_coupon_tool_schema_is_billing_only_and_has_no_effect_switches() -> None:
    billing = build_mcp("billing_agent", _client()[0])
    coding = build_mcp("coding_agent", _client()[0])
    preview = billing._tool_manager._tools["maxio_subscription_coupon_preview"]
    apply = billing._tool_manager._tools["maxio_subscription_coupon_apply"]
    assert set(preview.parameters["properties"]) == {
        "subscription_id",
        "coupon_code",
        "ticket_number",
    }
    assert set(apply.parameters["properties"]) == {
        "subscription_id",
        "coupon_code",
        "ticket_number",
        "preview_hash",
        "idempotency_key",
    }
    assert "maxio_subscription_coupon_preview" not in coding._tool_manager._tools
    assert "maxio_subscription_coupon_apply" not in coding._tool_manager._tools
    assert preview.annotations.readOnlyHint is True
    assert apply.annotations.readOnlyHint is False


def test_subscription_product_change_tool_schema_is_billing_only() -> None:
    billing = build_mcp("billing_agent", _client()[0])
    coding = build_mcp("coding_agent", _client()[0])
    preview = billing._tool_manager._tools[
        "maxio_subscription_product_change_preview"
    ]
    apply = billing._tool_manager._tools[
        "maxio_subscription_product_change_apply"
    ]
    assert set(preview.parameters["properties"]) == {
        "subscription_id",
        "product_id",
        "ticket_number",
    }
    assert set(apply.parameters["properties"]) == {
        "subscription_id",
        "product_id",
        "ticket_number",
        "preview_hash",
        "idempotency_key",
    }
    assert "maxio_subscription_product_change_preview" not in coding._tool_manager._tools
    assert "maxio_subscription_product_change_apply" not in coding._tool_manager._tools
    assert preview.annotations.readOnlyHint is True
    assert apply.annotations.readOnlyHint is False
    assert apply.annotations.idempotentHint is True


def test_cancellation_tool_schema_is_billing_only_and_has_no_financial_switches() -> None:
    client, _ = _client([])
    billing = build_mcp("billing_agent", client)
    coding = build_mcp("coding_agent", client)
    preview = billing._tool_manager._tools["maxio_subscription_cancellation_preview"]
    apply = billing._tool_manager._tools["maxio_subscription_cancellation_apply"]

    assert set(preview.parameters["properties"]) == {"subscription_id", "ticket_number", "reason"}
    assert set(apply.parameters["properties"]) == {
        "subscription_id",
        "ticket_number",
        "reason",
        "preview_hash",
        "idempotency_key",
    }
    assert preview.annotations.readOnlyHint is True
    assert apply.annotations.readOnlyHint is False
    assert apply.annotations.destructiveHint is True
    assert apply.annotations.idempotentHint is True
    assert "maxio_subscription_cancellation_apply" not in coding._tool_manager._tools


def test_past_due_cancellation_tool_schema_is_shared_and_has_no_financial_switches() -> None:
    client, _ = _client([])
    billing = build_mcp("billing_agent", client)
    coding = build_mcp("coding_agent", client)
    for server in (billing, coding):
        preview = server._tool_manager._tools[
            "maxio_past_due_subscription_cancellation_preview"
        ]
        apply = server._tool_manager._tools[
            "maxio_past_due_subscription_cancellation_apply"
        ]
        assert set(preview.parameters["properties"]) == {
            "subscription_id",
            "ticket_number",
            "reason",
        }
        assert set(apply.parameters["properties"]) == {
            "subscription_id",
            "ticket_number",
            "reason",
            "preview_hash",
            "idempotency_key",
        }
        assert preview.annotations.readOnlyHint is True
        assert apply.annotations.readOnlyHint is False
        assert apply.annotations.destructiveHint is True
        assert apply.annotations.idempotentHint is True


def test_guarded_write_requires_idempotency_and_rejects_delete(tmp_path: Path) -> None:
    client, session = _client({"subscription": {"id": 7}}, journal_path=tmp_path / "journal.jsonl")
    with pytest.raises(MaxioScopeError, match="idempotency_key"):
        client.api_request("PUT", "/subscriptions/7.json", json_body={"subscription": {"receives_invoice_emails": True}})
    with pytest.raises(MaxioScopeError, match="deletion is unavailable"):
        client.api_request("DELETE", "/subscriptions/7.json", idempotency_key="ticket-347258-delete")

    result = client.api_request(
        "PUT",
        "/subscriptions/7.json",
        json_body={"subscription": {"receives_invoice_emails": True}},
        idempotency_key="ticket-347258-invoice-email-v1",
    )
    assert result["ok"] is True
    assert result["readbackRequired"] is True
    assert session.calls[-1][0] == "PUT"
    assert client.api_request(
        "PUT",
        "/subscriptions/7.json",
        json_body={"subscription": {"receives_invoice_emails": True}},
        idempotency_key="ticket-347258-invoice-email-v1",
    )["duplicate"] is True


def test_generic_api_cannot_attach_subscription_payment_profile(tmp_path: Path) -> None:
    client, session = _client({}, journal_path=tmp_path / "journal.jsonl")

    with pytest.raises(MaxioScopeError, match="not a supported Maxio update field"):
        client.api_request(
            "PUT",
            "/subscriptions/77.json",
            json_body={"subscription": {"payment_profile_id": 7002}},
            idempotency_key="ticket-347697-generic-profile-v1",
        )

    assert session.calls == []


def test_generic_api_cannot_change_subscription_payment_profile(tmp_path: Path) -> None:
    client, session = _client({}, journal_path=tmp_path / "journal.jsonl")

    with pytest.raises(MaxioScopeError, match="typed payment-profile"):
        client.api_request(
            "POST",
            "/subscriptions/77/payment_profiles/7002/change_payment_profile.json",
            idempotency_key="ticket-347697-generic-profile-change-v1",
        )

    assert session.calls == []


@pytest.mark.parametrize(
    "method,path",
    [
        (
            "POST",
            "/subscriptions/77/payment_profiles/7002/change_payment_profile.json",
        ),
        ("POST", "/subscriptions/77/request_payment_profiles_update.json"),
        ("PUT", "/subscriptions/77/reactivate.json"),
    ],
)
def test_generic_api_cannot_bypass_payment_and_reactivation_tools(
    tmp_path: Path,
    method: str,
    path: str,
) -> None:
    client, _ = _client({}, journal_path=tmp_path / "journal.jsonl")
    with pytest.raises(MaxioScopeError, match="typed|matching"):
        client.api_request(
            method,
            path,
            idempotency_key="ticket-347607-generic-v1",
        )


@pytest.mark.parametrize(
    "path",
    [
        "/users/1.json",
        "/roles/1.json",
        "/permissions/1.json",
        "/api_keys/1.json",
        "/sites/1.json",
        "/webhooks/1.json",
        "/customers/1/purge.json",
    ],
)
def test_guarded_write_rejects_permission_admin_and_destructive_paths(
    tmp_path: Path,
    path: str,
) -> None:
    client, _ = _client({}, journal_path=tmp_path / "journal.jsonl")
    with pytest.raises(MaxioScopeError, match="unavailable"):
        client.api_request(
            "PUT",
            path,
            json_body={"value": True},
            idempotency_key="ticket-347258-privileged-v1",
        )


def test_guarded_write_rejects_provider_host_override_and_key_reuse(tmp_path: Path) -> None:
    client, _ = _client({}, journal_path=tmp_path / "journal.jsonl")
    with pytest.raises(MaxioScopeError, match="absolute Maxio JSON API path"):
        client.api_request("POST", "https://evil.example/customers.json", idempotency_key="ticket-347258-write")
    client.api_request(
        "PATCH",
        "/customers/7.json",
        json_body={"customer": {"email": "billing@example.com"}},
        idempotency_key="ticket-347258-customer-v1",
    )
    with pytest.raises(MaxioScopeError, match="different Maxio operation"):
        client.api_request(
            "PATCH",
            "/customers/8.json",
            json_body={"customer": {"email": "billing@example.com"}},
            idempotency_key="ticket-347258-customer-v1",
        )
