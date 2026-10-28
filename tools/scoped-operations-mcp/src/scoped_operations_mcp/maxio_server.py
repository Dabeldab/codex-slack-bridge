from __future__ import annotations

# AgentChat/coding_agent 2026-08-03T23:30:00Z

import os
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from .maxio_client import MaxioSettings, ScopedMaxioClient


ALLOWED_LANES = frozenset({"coding_agent", "billing_agent"})
READ = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=True)
GUARDED_WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=True)
CANCELLATION_WRITE = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=True,
    idempotentHint=True,
    openWorldHint=True,
)


def _subscription_repair_modes() -> dict[str, dict[str, Any]]:
    allocation_tools = [
        "maxio_component_allocation_preview",
        "maxio_component_allocation_apply",
        "maxio_subscription_account_balances",
    ]
    credit_tools = [
        "maxio_component_allocation_preview",
        "maxio_component_allocation_apply",
        "maxio_manual_service_credit_preview",
        "maxio_manual_service_credit_apply",
        "maxio_subscription_account_balances",
    ]
    return {
        "upgrade_no_charge": {
            "allocationDirection": "upgrade",
            "toolSequence": allocation_tools,
            "providerAutomaticCharge": False,
            "providerAutomaticCredit": False,
            "manualServiceCredit": False,
        },
        "downgrade_no_credit": {
            "allocationDirection": "downgrade",
            "toolSequence": allocation_tools,
            "providerAutomaticCharge": False,
            "providerAutomaticCredit": False,
            "manualServiceCredit": False,
        },
        "upgrade_with_credit": {
            "allocationDirection": "upgrade",
            "toolSequence": credit_tools,
            "providerAutomaticCharge": False,
            "providerAutomaticCredit": False,
            "manualServiceCredit": True,
            "creditRequiresExactAuthorizedCents": True,
        },
        "downgrade_with_credit": {
            "allocationDirection": "downgrade",
            "toolSequence": credit_tools,
            "providerAutomaticCharge": False,
            "providerAutomaticCredit": False,
            "manualServiceCredit": True,
            "creditRequiresExactAuthorizedCents": True,
        },
    }


def build_mcp(lane: str, client: ScopedMaxioClient) -> FastMCP:
    clean_lane = str(lane or "").strip()
    if clean_lane not in ALLOWED_LANES:
        raise RuntimeError("Maxio scoped MCP requires a fixed billing or coding lane")
    mcp = FastMCP(
        f"Maxio Scoped Operations ({clean_lane})",
        instructions=(
            "This broker exposes bounded Maxio reads plus guarded typed billing operations for the fixed billing "
            "and coding lanes. Mutations require a stable idempotency key, "
            "are journaled before execution, and require authoritative readback before completion or retry. "
            "Every component upgrade or downgrade first uses the allocation preview/apply pair with automatic "
            "charge, credit, and proration disabled. A separately authorized upgrade-with-credit or "
            "downgrade-with-credit then uses the manual service-credit preview/apply pair with an exact amount "
            "in cents and a Billing ticket; credit is never inferred from the allocation. Generic allocation, "
            "credit-note, service-credit, coupon, charge, and invoice-payment writes are blocked. Jamie has a "
            "ticket-bound coupon preview/apply pair that verifies the coupon definition, product family, subscription "
            "readback, balances, and whether a separate invoice disposition is still required. Component payment "
            "recovery uses one isolated, ticket-bound allocation pair: downgrade the exact recovery locations with "
            "no credit, reallocate the exact authorized charge quantity with full upgrade charge and dunning enabled, "
            "then restore the recurring quantity with no credit. A target subscription may contain only the recovery "
            "locations; otherwise the caller must first create and link a separate subscription. Jamie also has a "
            "ticket-bound billing-cycle recovery pair for an account that first needs a future-billed replacement "
            "subscription: create and verify the subscription with no initial charge, then make exactly one immediate "
            "authorized collection attempt with accrue-on-failure enabled. A successful result requires a linked "
            "charge and payment plus zero balances. A decline preserves exactly the authorized open invoice, blocks "
            "all downstream location activation, and cannot be retried. Generic one-time charges remain unavailable. "
            "When a Billing ticket explicitly authorizes reactivation with no customer charge and one future bill "
            "date, Jamie uses the separate no-charge reactivation preview/apply pair. It requires zero starting "
            "balances, issues exactly one ticket-bound service credit equal to the current reactivation charge, "
            "consumes it during resume, sets the exact future bill date, and permits downstream activation only "
            "after active state, zero balances, exact customer identity, and the bill date all read back. "
            "Jamie's billing lane also has a payment-ID-bound invoice-refund preview/apply pair with exact amount, "
            "ticket memo, no credit, no void, no external refund, exact invoice readback, and no retry after any attempt. "
            "Every additional location is a Nova Integrated Promo workflow. The merchant provider is required and "
            "limited to Worldpay, Creditcall, Authorize.net, or Propelr. The dedicated promo-credit pair requires "
            "one isolated mapped location, its exact component rate, a matching Nova Integrated product, and creates "
            "only a three-month service credit whose short memo contains the Billing ticket and location. "
            "Generic DELETE and record removal remain unavailable. Jamie's billing lane has one narrow "
            "preview/apply subscription-cancellation operation that calls Maxio's documented cancellation "
            "endpoint, preserves subscription history, requires a zero balance, and cannot refund, credit, "
            "void an invoice, schedule a cancellation, or send email. The fixed subscription-creation pair "
            "requires an exact customer, current payment profile, one-month product, exact component/rate, "
            "and a future next_billing_at so it cannot create an initial charge or payment. No credential, permission "
            "administration, or provider-host override is exposed. Resolve the exact customer and target "
            "before a mutation and keep every write within the verified request or signed ticket assignment."
        ),
        json_response=True,
        stateless_http=True,
    )

    @mcp.tool(annotations=READ)
    def maxio_capabilities() -> dict[str, Any]:
        """Report this lane's bounded read and guarded typed Maxio scope."""
        operations = [
            "maxio_health",
            "maxio_customers_by_reference",
            "maxio_customers_search",
            "maxio_customer",
            "maxio_subscriptions_by_customer",
            "maxio_subscription",
            "maxio_subscription_creation_preview",
            "maxio_subscription_creation_apply",
            "maxio_location_custom_fields_read",
            "maxio_location_custom_fields_preview",
            "maxio_location_custom_fields_apply",
            "maxio_subscription_location_metadata_read",
            "maxio_subscription_location_mapping_preview",
            "maxio_subscription_location_mapping_apply",
            "maxio_subscription_components",
            "maxio_location_allocation_reconciliation_read",
            "maxio_component_allocation_preview",
            "maxio_component_allocation_apply",
            "maxio_payment_profiles_by_customer",
            "maxio_invoices_by_customer",
            "maxio_invoice",
            "maxio_tax_report",
            "maxio_subscription_account_balances",
            "maxio_manual_service_credit_preview",
            "maxio_manual_service_credit_apply",
            "maxio_component_payment_recovery_preview",
            "maxio_component_payment_recovery_apply",
            "maxio_past_due_subscription_cancellation_preview",
            "maxio_past_due_subscription_cancellation_apply",
            "maxio_api_request",
        ]
        if clean_lane == "billing_agent":
            operations.extend(
                [
                    "maxio_subscription_cancellation_preview",
                    "maxio_subscription_cancellation_apply",
                    "maxio_invoice_refund_preview",
                    "maxio_invoice_refund_apply",
                    "maxio_invoice_void_preview",
                    "maxio_invoice_void_apply",
                    "maxio_subscription_coupon_preview",
                    "maxio_subscription_coupon_apply",
                    "maxio_subscription_product_change_preview",
                    "maxio_subscription_product_change_apply",
                    "maxio_nova_integrated_products",
                    "maxio_nova_integrated_promo_credit_preview",
                    "maxio_nova_integrated_promo_credit_apply",
                    "maxio_subscription_payment_profile_assignment_preview",
                    "maxio_subscription_payment_profile_assignment_apply",
                    "maxio_payment_profile_update_request_preview",
                    "maxio_payment_profile_update_request_apply",
                    "maxio_subscription_reactivation_preview",
                    "maxio_subscription_reactivation_apply",
                    "maxio_subscription_no_charge_reactivation_preview",
                    "maxio_subscription_no_charge_reactivation_apply",
                    "maxio_billing_cycle_recovery_preview",
                    "maxio_billing_cycle_recovery_apply",
                ]
            )
        return {
            **client.capability_status(),
            "lane": clean_lane,
            "operations": operations,
            "rainfallCustomerPortalWorkflows": (
                [
                    "account_and_subscription_lookup",
                    "add_close_or_reactivate_billed_locations",
                    "component_and_rate_normalization",
                    "payment_profile_read_and_assignment",
                    "payment_retry",
                    "invoice_read_and_delivery",
                    "refund_credit_or_void_when_explicitly_authorized",
                    "immediate_zero_balance_subscription_cancellation",
                    "salesforce_location_order_account_and_ticket_completion",
                ]
                if clean_lane == "billing_agent"
                else [
                    "integration_diagnosis",
                    "bounded_maxio_read",
                    "guarded_non_delete_api_operation",
                    "component_allocation_repair",
                ]
            ),
            "typedSubscriptionCancellationExposed": clean_lane == "billing_agent",
            "typedPastDueSubscriptionCancellationExposed": True,
            "typedSubscriptionCouponExposed": clean_lane == "billing_agent",
            "typedSubscriptionProductChangeExposed": clean_lane == "billing_agent",
            "typedNovaIntegratedPromoCreditExposed": clean_lane == "billing_agent",
            "novaIntegratedPromoMerchantProviders": [
                "Worldpay",
                "Creditcall",
                "Authorize.net",
                "Propelr",
            ],
            "novaIntegratedPromoRequiresIsolatedLocation": True,
            "novaIntegratedPromoFreeMonths": 3,
            "novaIntegratedPromoDefaultMonthlyRateCents": 9999,
            "novaIntegratedPromoAccountFlatRateMutationExposed": False,
            "typedPaymentProfileAssignmentExposed": clean_lane == "billing_agent",
            "typedSecurePaymentUpdateRequestExposed": clean_lane == "billing_agent",
            "typedSubscriptionReactivationExposed": clean_lane == "billing_agent",
            "typedNoChargeSubscriptionReactivationExposed": clean_lane
            == "billing_agent",
            "noChargeReactivationRequiresZeroStartingBalances": True,
            "noChargeReactivationUsesExactServiceCredit": True,
            "noChargeReactivationRequiresFutureBillingDateReadback": True,
            "noChargeReactivationCustomerChargeCents": 0,
            "subscriptionReactivationRequiresLinkedSuccessfulChargeAndPayment": clean_lane
            == "billing_agent",
            "subscriptionReactivationFailClosedRollback": clean_lane
            == "billing_agent",
            "rawPaymentDetailsAccepted": False,
            "subscriptionCouponRequiresInvoiceDisposition": True,
            "typedFutureBilledSubscriptionCreationExposed": True,
            "subscriptionRepairModes": _subscription_repair_modes(),
            "subscriptionRepairRequiresBillingTicketBeforeWrite": True,
            "locationMappingCustomFields": [
                "Locations",
                "LocationComponentMap",
                "LocationNameMap",
                "LocationNamesDisplay",
            ],
            "locationMappingIsOrganizationalNotAuthoritativeForActiveLocationCount": True,
            "automaticAllocationChargesOrCreditsExposed": True,
            "automaticAllocationFinancialEffectsRestrictedToComponentPaymentRecovery": True,
            "automaticAllocationCreditExposed": False,
            "typedComponentPaymentRecoveryExposed": True,
            "componentPaymentRecoveryUsesAllocation": True,
            "componentPaymentRecoveryDowngradeCredit": "none",
            "componentPaymentRecoveryUpgradeCharge": "full",
            "componentPaymentRecoveryInitiatesDunningOnFailure": True,
            "componentPaymentRecoveryRequiresExactLocationIsolation": True,
            "componentPaymentRecoveryRestoresRecurringQuantity": True,
            "typedBillingCycleRecoveryExposed": clean_lane == "billing_agent",
            "billingCycleRecoveryCanPreserveDeclinedOpenInvoice": clean_lane
            == "billing_agent",
            "billingCycleRecoveryRequiresExistingVerifiedSubscription": True,
            "billingCycleRecoveryRetryAfterAttemptExposed": False,
            "genericOneTimeChargeExposed": False,
            "directOneTimeRecoveryChargeExposed": clean_lane == "billing_agent",
            "componentPaymentRecoveryRetryAfterAttemptExposed": False,
            "writesRequireExplicitAuthorization": True,
            "arbitraryProviderAccess": False,
            "mayChangeAccess": False,
        }

    @mcp.tool(annotations=READ)
    def maxio_health() -> dict[str, Any]:
        """Verify the fixed Maxio credential with one bounded subscription read."""
        return client.health()

    @mcp.tool(annotations=READ)
    def maxio_customers_by_reference(reference: str, max_rows: int = 25) -> dict[str, Any]:
        """Find exactly one Maxio customer using its unique reference."""
        return client.customers_by_reference(reference, max_rows=max_rows)

    @mcp.tool(annotations=READ)
    def maxio_customers_search(query: str, max_rows: int = 25) -> dict[str, Any]:
        """Search customers by email, ID, reference, name, or organization."""
        return client.customers_search(query, max_rows=max_rows)

    @mcp.tool(annotations=READ)
    def maxio_customer(customer_id: int) -> dict[str, Any]:
        """Read one exact Maxio customer."""
        return client.customer(customer_id)

    @mcp.tool(annotations=READ)
    def maxio_subscriptions_by_customer(customer_id: int, max_rows: int = 50) -> dict[str, Any]:
        """Read a bounded subscription list for one exact Maxio customer."""
        return client.subscriptions_by_customer(customer_id, max_rows=max_rows)

    @mcp.tool(annotations=READ)
    def maxio_subscription(subscription_id: int) -> dict[str, Any]:
        """Read one exact Maxio subscription."""
        return client.subscription(subscription_id)

    @mcp.tool(annotations=READ)
    def maxio_subscription_creation_preview(
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
        """Preview one future-billed monthly subscription with no initial charge, payment, credit, or proration."""
        return client.subscription_creation_preview(
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

    @mcp.tool(annotations=GUARDED_WRITE)
    def maxio_subscription_creation_apply(
        customer_id: int,
        customer_reference: str,
        payment_profile_id: int,
        product_id: int,
        component_id: int,
        component_quantity: int,
        monthly_rate_cents: int,
        next_billing_at: str,
        ticket_number: str,
        preview_hash: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        """Create one unchanged future-billed subscription and verify identity, allocation, date, and zero invoice balance."""
        return client.apply_subscription_creation(
            customer_id,
            customer_reference,
            payment_profile_id,
            product_id,
            component_id,
            component_quantity,
            monthly_rate_cents,
            next_billing_at,
            ticket_number,
            preview_hash=preview_hash,
            idempotency_key=idempotency_key,
        )

    @mcp.tool(annotations=READ)
    def maxio_location_custom_fields_read() -> dict[str, Any]:
        """Read the four fixed site-level subscription custom fields used for location organization."""
        return client.location_custom_fields()

    @mcp.tool(annotations=READ)
    def maxio_location_custom_fields_preview(ticket_number: str) -> dict[str, Any]:
        """Preview creation of only missing fixed location custom-field definitions."""
        return client.location_custom_fields_preview(ticket_number)

    @mcp.tool(annotations=GUARDED_WRITE)
    def maxio_location_custom_fields_apply(
        ticket_number: str,
        preview_hash: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        """Create only missing fixed location custom fields and verify all four definitions."""
        return client.apply_location_custom_fields(
            ticket_number,
            preview_hash=preview_hash,
            idempotency_key=idempotency_key,
        )

    @mcp.tool(annotations=READ)
    def maxio_subscription_location_metadata_read(subscription_id: int) -> dict[str, Any]:
        """Read only the fixed location/component/name metadata for one exact subscription."""
        return client.subscription_location_metadata(subscription_id)

    @mcp.tool(annotations=READ)
    def maxio_subscription_location_mapping_preview(
        subscription_id: int,
        locations: list[dict[str, Any]],
        ticket_number: str,
    ) -> dict[str, Any]:
        """Preview complete location metadata after exact allocation and custom-field checks."""
        return client.subscription_location_mapping_preview(
            subscription_id,
            locations,
            ticket_number,
        )

    @mcp.tool(annotations=GUARDED_WRITE)
    def maxio_subscription_location_mapping_apply(
        subscription_id: int,
        locations: list[dict[str, Any]],
        ticket_number: str,
        preview_hash: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        """Apply one complete unchanged mapping and verify every fixed metadata value."""
        return client.apply_subscription_location_mapping(
            subscription_id,
            locations,
            ticket_number,
            preview_hash=preview_hash,
            idempotency_key=idempotency_key,
        )

    # AgentChat/coding_agent 2026-08-07T13:31:00Z: a distinct typed path keeps
    # the original zero-balance cancellation contract unchanged while allowing
    # either owning lane to preserve a verified past-due receivable.
    @mcp.tool(annotations=READ)
    def maxio_past_due_subscription_cancellation_preview(
        subscription_id: int,
        ticket_number: str,
        reason: str,
    ) -> dict[str, Any]:
        """Preview immediate past-due cancellation with exact invoice preservation."""
        return client.past_due_subscription_cancellation_preview(
            subscription_id,
            ticket_number,
            reason,
        )

    @mcp.tool(annotations=CANCELLATION_WRITE)
    def maxio_past_due_subscription_cancellation_apply(
        subscription_id: int,
        ticket_number: str,
        reason: str,
        preview_hash: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        """Cancel past-due service and verify every open-invoice field is unchanged."""
        return client.apply_past_due_subscription_cancellation(
            subscription_id,
            ticket_number,
            reason,
            preview_hash=preview_hash,
            idempotency_key=idempotency_key,
        )

    if clean_lane == "billing_agent":

        @mcp.tool(annotations=READ)
        def maxio_nova_integrated_products(max_rows: int = 200) -> dict[str, Any]:
            """List active zero-base-price Nova Integrated products for the four allowed providers."""
            return client.nova_integrated_products(max_rows=max_rows)

        @mcp.tool(annotations=READ)
        def maxio_subscription_payment_profile_assignment_preview(
            subscription_id: int,
            customer_id: int,
            payment_profile_id: int,
            ticket_number: str,
        ) -> dict[str, Any]:
            """Preview assigning one existing customer-owned payment profile to one subscription."""
            return client.subscription_payment_profile_assignment_preview(
                subscription_id,
                customer_id,
                payment_profile_id,
                ticket_number,
            )

        @mcp.tool(annotations=GUARDED_WRITE)
        def maxio_subscription_payment_profile_assignment_apply(
            subscription_id: int,
            customer_id: int,
            payment_profile_id: int,
            ticket_number: str,
            preview_hash: str,
            idempotency_key: str,
        ) -> dict[str, Any]:
            """Assign one unchanged existing profile and verify subscription readback."""
            return client.apply_subscription_payment_profile_assignment(
                subscription_id,
                customer_id,
                payment_profile_id,
                ticket_number,
                preview_hash=preview_hash,
                idempotency_key=idempotency_key,
            )

        @mcp.tool(annotations=READ)
        def maxio_payment_profile_update_request_preview(
            subscription_id: int,
            customer_id: int,
            ticket_number: str,
        ) -> dict[str, Any]:
            """Preview Maxio's secure customer payment-update email without exposing card data."""
            return client.payment_profile_update_request_preview(
                subscription_id,
                customer_id,
                ticket_number,
            )

        @mcp.tool(annotations=GUARDED_WRITE)
        def maxio_payment_profile_update_request_apply(
            subscription_id: int,
            customer_id: int,
            ticket_number: str,
            preview_hash: str,
            idempotency_key: str,
        ) -> dict[str, Any]:
            """Send Maxio's secure payment-update email once and return a follow-up obligation."""
            return client.apply_payment_profile_update_request(
                subscription_id,
                customer_id,
                ticket_number,
                preview_hash=preview_hash,
                idempotency_key=idempotency_key,
            )

        @mcp.tool(annotations=READ)
        def maxio_subscription_reactivation_preview(
            subscription_id: int,
            customer_id: int,
            payment_profile_id: int,
            reactivation_mode: str,
            authorized_charge_cents: int,
            ticket_number: str,
        ) -> dict[str, Any]:
            """Preview exact-customer reactivation and its expected charge without writing."""
            return client.subscription_reactivation_preview(
                subscription_id,
                customer_id,
                payment_profile_id,
                reactivation_mode,
                authorized_charge_cents,
                ticket_number,
            )

        @mcp.tool(annotations=GUARDED_WRITE)
        def maxio_subscription_reactivation_apply(
            subscription_id: int,
            customer_id: int,
            payment_profile_id: int,
            reactivation_mode: str,
            authorized_charge_cents: int,
            ticket_number: str,
            preview_hash: str,
            idempotency_key: str,
        ) -> dict[str, Any]:
            """Attempt one charge; permit activation only after exact linked payment readback."""
            return client.apply_subscription_reactivation(
                subscription_id,
                customer_id,
                payment_profile_id,
                reactivation_mode,
                authorized_charge_cents,
                ticket_number,
                preview_hash=preview_hash,
                idempotency_key=idempotency_key,
            )

        @mcp.tool(annotations=READ)
        def maxio_subscription_no_charge_reactivation_preview(
            subscription_id: int,
            customer_id: int,
            waived_charge_cents: int,
            next_billing_at: str,
            ticket_number: str,
        ) -> dict[str, Any]:
            """Preview a service-credit-covered reactivation with one exact future bill date."""
            return client.subscription_no_charge_reactivation_preview(
                subscription_id,
                customer_id,
                waived_charge_cents,
                next_billing_at,
                ticket_number,
            )

        @mcp.tool(annotations=GUARDED_WRITE)
        def maxio_subscription_no_charge_reactivation_apply(
            subscription_id: int,
            customer_id: int,
            waived_charge_cents: int,
            next_billing_at: str,
            ticket_number: str,
            preview_hash: str,
            idempotency_key: str,
        ) -> dict[str, Any]:
            """Credit, reactivate, set the future bill date, and verify zero customer charge."""
            return client.apply_subscription_no_charge_reactivation(
                subscription_id,
                customer_id,
                waived_charge_cents,
                next_billing_at,
                ticket_number,
                preview_hash=preview_hash,
                idempotency_key=idempotency_key,
            )

        @mcp.tool(annotations=READ)
        def maxio_subscription_cancellation_preview(
            subscription_id: int,
            ticket_number: str,
            reason: str,
        ) -> dict[str, Any]:
            """Preview an immediate zero-balance cancellation without refund, credit, void, schedule, or email."""
            return client.subscription_cancellation_preview(
                subscription_id,
                ticket_number,
                reason,
            )

        @mcp.tool(annotations=CANCELLATION_WRITE)
        def maxio_subscription_cancellation_apply(
            subscription_id: int,
            ticket_number: str,
            reason: str,
            preview_hash: str,
            idempotency_key: str,
        ) -> dict[str, Any]:
            """Apply one unchanged previewed immediate cancellation and verify the canceled state."""
            return client.apply_subscription_cancellation(
                subscription_id,
                ticket_number,
                reason,
                preview_hash=preview_hash,
                idempotency_key=idempotency_key,
            )

        @mcp.tool(annotations=READ)
        def maxio_invoice_refund_preview(
            invoice_uid: str,
            payment_id: int,
            refund_amount_cents: int,
            ticket_number: str,
        ) -> dict[str, Any]:
            """Preview one exact ticket-authorized refund against one invoice payment."""
            return client.invoice_refund_preview(
                invoice_uid,
                payment_id,
                refund_amount_cents,
                ticket_number,
            )

        @mcp.tool(annotations=GUARDED_WRITE)
        def maxio_invoice_refund_apply(
            invoice_uid: str,
            payment_id: int,
            refund_amount_cents: int,
            ticket_number: str,
            preview_hash: str,
            idempotency_key: str,
        ) -> dict[str, Any]:
            """Refund one unchanged invoice payment and verify exact invoice readback."""
            return client.apply_invoice_refund(
                invoice_uid,
                payment_id,
                refund_amount_cents,
                ticket_number,
                preview_hash=preview_hash,
                idempotency_key=idempotency_key,
            )

        @mcp.tool(annotations=GUARDED_WRITE)
        def maxio_invoice_void_preview(
            invoice_uid: str,
            ticket_number: str,
            reason: str,
        ) -> dict[str, Any]:
            """Preview voiding one open/canceled invoice without changing Maxio."""
            return client.invoice_void_preview(
                invoice_uid,
                ticket_number,
                reason,
            )

        @mcp.tool(annotations=GUARDED_WRITE)
        def maxio_invoice_void_apply(
            invoice_uid: str,
            ticket_number: str,
            reason: str,
            preview_hash: str,
            idempotency_key: str,
        ) -> dict[str, Any]:
            """Void one open/canceled invoice and verify exact invoice readback."""
            return client.apply_invoice_void(
                invoice_uid,
                ticket_number,
                reason,
                preview_hash=preview_hash,
                idempotency_key=idempotency_key,
            )

        # AgentChat/direct_codex 2026-07-31T00:00:00-04:00: expose promotions        # AgentChat/direct_codex 2026-07-31T00:00:00-04:00: expose promotions
        # only to Jamie through a preview/apply/readback contract.
        @mcp.tool(annotations=READ)
        def maxio_subscription_coupon_preview(
            subscription_id: int,
            coupon_code: str,
            ticket_number: str,
        ) -> dict[str, Any]:
            """Preview one exact ticket-authorized coupon and report any open-invoice disposition."""
            return client.subscription_coupon_preview(
                subscription_id,
                coupon_code,
                ticket_number,
            )

        @mcp.tool(annotations=GUARDED_WRITE)
        def maxio_subscription_coupon_apply(
            subscription_id: int,
            coupon_code: str,
            ticket_number: str,
            preview_hash: str,
            idempotency_key: str,
        ) -> dict[str, Any]:
            """Apply one unchanged coupon preview and verify exact subscription coupon readback."""
            return client.apply_subscription_coupon(
                subscription_id,
                coupon_code,
                ticket_number,
                preview_hash=preview_hash,
                idempotency_key=idempotency_key,
            )

        @mcp.tool(annotations=READ)
        def maxio_subscription_product_change_preview(
            subscription_id: int,
            product_id: int,
            ticket_number: str,
        ) -> dict[str, Any]:
            """Preview one same-family zero-base-price Nova Integrated product change."""
            return client.subscription_product_change_preview(
                subscription_id,
                product_id,
                ticket_number,
            )

        @mcp.tool(annotations=GUARDED_WRITE)
        def maxio_subscription_product_change_apply(
            subscription_id: int,
            product_id: int,
            ticket_number: str,
            preview_hash: str,
            idempotency_key: str,
        ) -> dict[str, Any]:
            """Apply one product change and verify coupons, components, balances, and dates stayed unchanged."""
            return client.apply_subscription_product_change(
                subscription_id,
                product_id,
                ticket_number,
                preview_hash=preview_hash,
                idempotency_key=idempotency_key,
            )

        @mcp.tool(annotations=READ)
        def maxio_nova_integrated_promo_credit_preview(
            subscription_id: int,
            location_id: int,
            merchant_provider: str,
            monthly_rate_cents: int,
            ticket_number: str,
        ) -> dict[str, Any]:
            """Preview exactly three free months for one isolated Nova Integrated location."""
            return client.nova_integrated_promo_credit_preview(
                subscription_id,
                location_id,
                merchant_provider,
                monthly_rate_cents,
                ticket_number,
            )

        @mcp.tool(annotations=GUARDED_WRITE)
        def maxio_nova_integrated_promo_credit_apply(
            subscription_id: int,
            location_id: int,
            merchant_provider: str,
            monthly_rate_cents: int,
            ticket_number: str,
            preview_hash: str,
            idempotency_key: str,
        ) -> dict[str, Any]:
            """Apply one ticket-bound Nova Integrated Promo credit and verify exact balance readback."""
            return client.apply_nova_integrated_promo_credit(
                subscription_id,
                location_id,
                merchant_provider,
                monthly_rate_cents,
                ticket_number,
                preview_hash=preview_hash,
                idempotency_key=idempotency_key,
            )

    @mcp.tool(annotations=READ)
    def maxio_subscription_components(subscription_id: int, max_rows: int = 100) -> dict[str, Any]:
        """Read bounded component state for one exact Maxio subscription."""
        return client.subscription_components(subscription_id, max_rows=max_rows)

    @mcp.tool(annotations=READ)
    def maxio_location_allocation_reconciliation_read(
        subscription_ids: list[int],
    ) -> dict[str, Any]:
        """Read complete location-only quantities and open state across exact subscriptions."""
        return client.location_allocation_reconciliation(subscription_ids)

    @mcp.tool(annotations=READ)
    def maxio_component_allocation_preview(
        subscription_id: int,
        allocations: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Preview an upgrade, downgrade, or mixed component repair with every automatic financial effect off."""
        return client.component_allocation_preview(subscription_id, allocations)

    @mcp.tool(annotations=GUARDED_WRITE)
    def maxio_component_allocation_apply(
        subscription_id: int,
        allocations: list[dict[str, Any]],
        preview_hash: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        """Apply one unchanged allocation preview with no charge/credit, then verify exact component quantities."""
        return client.apply_component_allocation(
            subscription_id,
            allocations,
            preview_hash=preview_hash,
            idempotency_key=idempotency_key,
        )

    @mcp.tool(annotations=READ)
    def maxio_payment_profiles_by_customer(customer_id: int, max_rows: int = 50) -> dict[str, Any]:
        """Read bounded payment-profile metadata for one exact Maxio customer."""
        return client.payment_profiles_by_customer(customer_id, max_rows=max_rows)

    @mcp.tool(annotations=READ)
    def maxio_invoices_by_customer(customer_id: int, max_rows: int = 50) -> dict[str, Any]:
        """Read a bounded invoice list for one exact Maxio customer."""
        return client.invoices_by_customer(customer_id, max_rows=max_rows)

    @mcp.tool(annotations=READ)
    def maxio_invoice(invoice_uid: str) -> dict[str, Any]:
        """Read one exact Maxio invoice by UID."""
        return client.invoice(invoice_uid)

    @mcp.tool(annotations=READ)
    def maxio_tax_report(
        month: str = "",
        start_date: str = "",
        end_date: str = "",
    ) -> dict[str, Any]:
        """Create a plain Excel tax report for the prior month, YYYY-MM month, or inclusive YYYY-MM-DD range."""
        return client.tax_report(
            month=month,
            start_date=start_date,
            end_date=end_date,
        )

    @mcp.tool(annotations=READ)
    def maxio_subscription_account_balances(subscription_id: int) -> dict[str, Any]:
        """Read exact open-invoice, service-credit, prepayment, and pending balances."""
        return client.subscription_account_balances(subscription_id)

    @mcp.tool(annotations=READ)
    def maxio_manual_service_credit_preview(
        subscription_id: int,
        amount_cents: int,
        ticket_number: str,
    ) -> dict[str, Any]:
        """Preview an exact separately authorized credit after a verified no-financial-effect upgrade or downgrade."""
        return client.manual_service_credit_preview(subscription_id, amount_cents, ticket_number)

    @mcp.tool(annotations=GUARDED_WRITE)
    def maxio_manual_service_credit_apply(
        subscription_id: int,
        amount_cents: int,
        ticket_number: str,
        preview_hash: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        """Issue one separately previewed exact credit and verify its balance; never changes allocations or invoices."""
        return client.apply_manual_service_credit(
            subscription_id,
            amount_cents,
            ticket_number,
            preview_hash=preview_hash,
            idempotency_key=idempotency_key,
        )

    @mcp.tool(annotations=READ)
    def maxio_component_payment_recovery_preview(
        subscription_id: int,
        component_id: int,
        recovery_location_ids: list[int],
        recovery_charge_quantity: int,
        unit_rate_cents: int,
        authorized_amount_cents: int,
        ticket_number: str,
    ) -> dict[str, Any]:
        """Preview one isolated no-credit downgrade and full-charge reallocation with dunning."""
        return client.component_payment_recovery_preview(
            subscription_id,
            component_id,
            recovery_location_ids,
            recovery_charge_quantity,
            unit_rate_cents,
            authorized_amount_cents,
            ticket_number,
        )

    @mcp.tool(annotations=GUARDED_WRITE)
    def maxio_component_payment_recovery_apply(
        subscription_id: int,
        component_id: int,
        recovery_location_ids: list[int],
        recovery_charge_quantity: int,
        unit_rate_cents: int,
        authorized_amount_cents: int,
        ticket_number: str,
        preview_hash: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        """Apply the unchanged isolated allocation recovery and verify payment or dunning."""
        return client.apply_component_payment_recovery(
            subscription_id,
            component_id,
            recovery_location_ids,
            recovery_charge_quantity,
            unit_rate_cents,
            authorized_amount_cents,
            ticket_number,
            preview_hash=preview_hash,
            idempotency_key=idempotency_key,
        )

    if clean_lane == "billing_agent":

        @mcp.tool(annotations=READ)
        def maxio_billing_cycle_recovery_preview(
            subscription_id: int,
            cycle_count: int,
            cycle_amount_cents: int,
            authorized_amount_cents: int,
            service_period_start: str,
            service_period_end: str,
            ticket_number: str,
        ) -> dict[str, Any]:
            """Preview one exact immediate collection with an authorized open invoice preserved on decline."""
            return client.billing_cycle_recovery_preview(
                subscription_id,
                cycle_count,
                cycle_amount_cents,
                authorized_amount_cents,
                service_period_start,
                service_period_end,
                ticket_number,
                decline_action="preserve_open_invoice",
            )

        @mcp.tool(annotations=GUARDED_WRITE)
        def maxio_billing_cycle_recovery_apply(
            subscription_id: int,
            cycle_count: int,
            cycle_amount_cents: int,
            authorized_amount_cents: int,
            service_period_start: str,
            service_period_end: str,
            ticket_number: str,
            preview_hash: str,
            idempotency_key: str,
        ) -> dict[str, Any]:
            """Attempt one exact collection, verify paid or declined state, and permanently block a second attempt."""
            result = client.apply_billing_cycle_recovery(
                subscription_id,
                cycle_count,
                cycle_amount_cents,
                authorized_amount_cents,
                service_period_start,
                service_period_end,
                ticket_number,
                preview_hash=preview_hash,
                idempotency_key=idempotency_key,
                decline_action="preserve_open_invoice",
            )
            paid = bool(result.get("ok")) and str(result.get("status") or "") == "collected"
            return {
                **result,
                "paymentConfirmed": paid,
                "downstreamActivationAllowed": paid,
                "locationActivationBlocked": not paid,
            }

    @mcp.tool(annotations=GUARDED_WRITE)
    def maxio_api_request(
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        json_body: Any = None,
        idempotency_key: str = "",
    ) -> dict[str, Any]:
        """Call one non-financial Maxio JSON path; typed tools own allocations, coupons, and credits."""
        return client.api_request(
            method,
            path,
            params=params,
            json_body=json_body,
            idempotency_key=idempotency_key,
        )

    return mcp


def main() -> None:
    lane = os.getenv("SCOPED_AGENT_LANE", "").strip()
    build_mcp(lane, ScopedMaxioClient(MaxioSettings.from_environment())).run(transport="stdio")


if __name__ == "__main__":
    main()
