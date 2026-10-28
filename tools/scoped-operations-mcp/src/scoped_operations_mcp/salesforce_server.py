from __future__ import annotations

# AgentChat/coding_agent 2026-08-03T23:30:00Z
# AgentChat/coding_agent 2026-08-03T22:55:08Z
# AgentChat/coding_agent 2026-08-06T11:52:00Z
# AgentChat/coding_agent 2026-08-06T16:20:00Z

# AgentChat/coding_agent 2026-07-26T00:51:47Z
# AgentChat/coding_agent 2026-07-23T20:26:28Z: add the fixed Instyle demo rebuild.

import os
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from .nova_openapi_client import ScopedNovaOpenApiClient
from .nova_sql_client import NovaSqlSettings, ScopedNovaSqlClient
from .nova_sql_instyle_demo_rebuild import LocalProtectedDemoRestoreGateway
from .nova_sql_instyle_target_restore import TargetScopedProtectedDemoRestoreGateway
from .salesforce_client import (
    FORBIDDEN_AGENT_ORDER_TYPE_LABEL,
    LOCATION_LIFECYCLE_ORDER_TYPE_LABELS,
    NOVA_INTEGRATED_MERCHANT_PROVIDERS,
    ScopedSalesforceClient,
    SalesforceScopeError,
    SalesforceSettings,
    ticket_chatter_update_body,
)

# AgentChat/direct_codex 2026-07-24T13:45:00Z: expose the fixed weekly
# Classic/Wave aggregate to the support lane without adding arbitrary SOQL.

ALLOWED_LANES = frozenset(
    {"direct_codex", "coding_agent", "tickets_agent", "billing_agent", "claude_agent"}
)
READ = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=True)
WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=True)
GUARDED_WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=True)
FIXED_DESTRUCTIVE_WRITE = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=True,
    idempotentHint=True,
    openWorldHint=True,
)

COMMON_CAPABILITIES = (
    "salesforce_capabilities",
    "salesforce_explain_limitation",
    "salesforce_lookup",
    "salesforce_account_360_read",
    "salesforce_ticket_list_open",
    "salesforce_ticket_read",
    "salesforce_ticket_feed_read",
    "salesforce_ticket_email_log_read",
    "salesforce_email_sender_preflight",
    "salesforce_email_template_inventory",
    "salesforce_ticket_template_email_preview",
    "nova_sql_capabilities",
    "nova_sql_preflight",
    "nova_billing_locations_read",
    "nova_sql_invoice_spare_investigation",
    "nova_sql_read",
    "nova_api_capabilities",
    "nova_api_health",
    "nova_api_preflight",
    "nova_api_regions",
    "nova_api_locations_by_region",
    "nova_api_location_general_settings",
    "nova_api_location_preferences",
    "nova_api_customers",
    "nova_api_customer",
    "nova_api_products",
    "nova_api_product",
    "nova_api_inventory",
    "nova_api_invoices",
    "nova_api_invoice",
    "nova_api_invoice_payments",
    "nova_api_users",
)
TICKET_WRITE_CAPABILITIES = (
    "salesforce_ticket_update",
    "salesforce_ticket_internal_note_update",
    "salesforce_ticket_chatter_post",
    "salesforce_ticket_chatter_reply",
    "salesforce_ticket_internal_request_post",
    "salesforce_ticket_resolve",
    "salesforce_ticket_template_email_send",
)
SUPPORT_CREDENTIAL_EMAIL_CAPABILITIES = (
    "salesforce_ticket_company_credentials_email_preview",
    "salesforce_ticket_company_credentials_email_send",
)
TICKET_CREATE_CAPABILITY = ("salesforce_ticket_create",)
SUPPORT_EMAIL_TICKET_CREATE_CAPABILITY = (
    "salesforce_support_email_ticket_create",
)
BILLING_CLOSURE_EMAIL_CAPABILITIES = (
    "salesforce_billing_closure_email_ticket_create",
    "salesforce_account_cancellation_email_attachment_status",
    "salesforce_account_cancellation_email_attachment_upload",
)
TICKET_EVIDENCE_CAPABILITIES = (
    "salesforce_ticket_contact_email_update",
    "salesforce_ticket_attachment_status",
    "salesforce_ticket_attachment_upload",
    "salesforce_ticket_pdf_status",
    "salesforce_ticket_pdf_upload",
)
BILLING_SHARED_CAPABILITIES = (
    "salesforce_billing_account_read",
    "salesforce_billing_account_locations_read",
    "salesforce_billing_account_orders_read",
    "salesforce_billing_account_flat_rate_update",
    "salesforce_billing_location_rate_update",
    "salesforce_billing_structure_read",
    "salesforce_billing_structure_alignment_preview",
    "salesforce_billing_structure_alignment_apply",
    "salesforce_billing_location_alignment_preview",
    "salesforce_billing_location_alignment_apply",
    "salesforce_account_fake_classification_preview",
    "salesforce_account_fake_classification_apply",
)
BILLING_OBJECT_CAPABILITIES = (
    "salesforce_billing_account_flat_rate_clear",
    "salesforce_billing_location_gateway_update",
    "salesforce_account_closure_preview",
    "salesforce_account_closure_apply",
    "salesforce_account_cancellation_order_preview",
    "salesforce_account_cancellation_order_apply",
    "salesforce_location_cancellation_order_preview",
    "salesforce_location_cancellation_order_apply",
    "salesforce_cancellation_order_reason_update",
    "salesforce_email_template_html_update",
    "salesforce_account_cancellation_chatter_post",
    "salesforce_account_cancellation_finalize",
    "salesforce_account_cancellation_pdf_status",
    "salesforce_account_cancellation_pdf_upload",
    "salesforce_account_cancellation_confirmation_email_send",
    "salesforce_ticket_credit_confirmation_email_send",
    "salesforce_ticket_refund_confirmation_email_send",
)
LOCATION_LIFECYCLE_ORDER_CAPABILITIES = (
    "salesforce_location_lifecycle_order_preview",
    "salesforce_location_lifecycle_order_apply",
)
BILLING_PAYMENT_REDACTION_CAPABILITIES = (
    "salesforce_payment_card_ticket_redaction_preview",
    "salesforce_payment_card_ticket_redaction_apply",
)
TAYLOR_SQL_WRITE_CAPABILITIES = (
    "nova_sql_write_preview",
    "nova_sql_execute_guarded",
    "nova_sql_account_copy_preview",
    "nova_sql_account_copy_status",
    "nova_sql_account_copy_execute",
    "nova_sql_location_region_update",
    "nova_sql_location_reactivation_update",
    "nova_sql_location_layaway_enable",
    "nova_sql_locations_feature_columns_preview",
    "nova_sql_locations_feature_columns_execute",
    "nova_sql_kit_upgrade_preview",
    "nova_sql_kit_upgrade_execute",
    "nova_sql_table_restore_preview",
    "nova_sql_table_restore_execute",
    "nova_sql_instyle_demo_sync_preview",
    "nova_sql_instyle_demo_sync_status",
    "nova_sql_instyle_demo_sync_execute",
    "nova_sql_instyle_runway_merge_preview",
    "nova_sql_instyle_runway_merge_status",
    "nova_sql_instyle_runway_merge_execute",
    "nova_sql_oklahoma_hawaii_catalog_replace_preview",
    "nova_sql_oklahoma_hawaii_catalog_replace_status",
    "nova_sql_oklahoma_hawaii_catalog_replace_execute",
)
TAYLOR_SQL_READ_CAPABILITIES = (
    "nova_sql_api_customer_email_cohort",
    "nova_sql_data_move_read",
)
LANE_TICKET_RECORD_TYPES = {
    "direct_codex": frozenset({"1. NOVA Classic", "2. Nova Wave", "3. Billing"}),
    "tickets_agent": frozenset({"1. NOVA Classic", "2. Nova Wave"}),
    "billing_agent": frozenset({"3. Billing"}),
    "coding_agent": frozenset({"1. NOVA Classic", "2. Nova Wave"}),
    "claude_agent": frozenset(),
}
LANE_TICKET_READ_RECORD_TYPES = {
    "direct_codex": frozenset({"1. NOVA Classic", "2. Nova Wave", "3. Billing"}),
    # Alex owns the combined Command Center board projection. This read-only
    # exception prevents billing rows from requiring an unsafe cross-sandbox
    # cache handoff; ticket writes remain governed by LANE_TICKET_RECORD_TYPES.
    "tickets_agent": frozenset({"1. NOVA Classic", "2. Nova Wave", "3. Billing"}),
    "billing_agent": frozenset({"3. Billing"}),
    "coding_agent": frozenset({"1. NOVA Classic", "2. Nova Wave"}),
    "claude_agent": frozenset({"1. NOVA Classic", "2. Nova Wave", "3. Billing"}),
}

PERMANENTLY_UNAVAILABLE = (
    "Apex execution",
    "arbitrary Salesforce REST or SOQL",
    "deletion or recycle-bin operations",
    "Flow or workflow creation and editing",
    "Metadata and Tooling APIs",
    "object, field, layout, profile, permission, role, user, or org-setting administration",
    "arbitrary recipient-supplied email sends",
    "freehand Salesforce email subjects or bodies",
)


def _build_thor_salesforce_mcp(client: ScopedSalesforceClient) -> FastMCP:
    """Expose ticket evidence to Thor without any Salesforce or Nova mutation."""

    readable_types = LANE_TICKET_READ_RECORD_TYPES["claude_agent"]
    operations = [
        "salesforce_capabilities",
        "salesforce_explain_limitation",
        "salesforce_lookup",
        "salesforce_account_360_read",
        "salesforce_ticket_list_open",
        "salesforce_weekly_ticket_totals",
        "salesforce_ticket_read",
        "salesforce_ticket_feed_read",
        "salesforce_ticket_email_log_read",
    ]
    mcp = FastMCP(
        "Salesforce Scoped Operations (claude_agent)",
        instructions=(
            "Thor may read bounded Nova Classic, Nova Wave, and Billing ticket evidence "
            "for support-quality and initiative context. This connection exposes no ticket "
            "write, email send, Salesforce administration, Nova SQL, or Nova API operation. "
            "Public overview summaries must not include customer, ticket, person-specific, "
            "one-on-one, HR, performance, or credential material."
        ),
        json_response=True,
        stateless_http=True,
    )

    @mcp.tool(annotations=READ)
    def salesforce_capabilities() -> dict[str, Any]:
        """List Thor's bounded read-only Salesforce ticket evidence operations."""
        return {
            "ok": True,
            "lane": "claude_agent",
            "operations": operations,
            "ticketRecordTypes": sorted(readable_types),
            "ticketWriteRecordTypes": [],
            "mutationToolsExposed": False,
            "mayChangeAccess": False,
            "provider": client.capability_status(),
        }

    @mcp.tool(annotations=READ)
    def salesforce_explain_limitation(requested_action: str) -> dict[str, Any]:
        """Explain that Thor's Salesforce connection is read-only."""
        return {
            "ok": True,
            "available": False,
            "requestedAction": str(requested_action or "").strip()[:500],
            "reason": "Thor's Salesforce connection exposes bounded ticket evidence reads only.",
            "mayChangeAccess": False,
        }

    @mcp.tool(annotations=READ)
    def salesforce_lookup(
        kind: str,
        value: str,
        account_id: str = "",
        limit: int = 10,
    ) -> dict[str, Any]:
        """Look up one ticket, account, contact, location, or order."""
        return client.lookup(kind, value, account_id=account_id, limit=limit)

    @mcp.tool(annotations=READ)
    def salesforce_account_360_read(
        search: str,
        contacts_limit: int = 100,
        locations_limit: int = 250,
        tickets_limit: int = 250,
    ) -> dict[str, Any]:
        """Resolve one account and return its bounded read view."""
        return client.read_account_360(
            search,
            contacts_limit=contacts_limit,
            locations_limit=locations_limit,
            tickets_limit=tickets_limit,
        )

    @mcp.tool(annotations=READ)
    def salesforce_ticket_list_open(limit: int = 200) -> dict[str, Any]:
        """List bounded open ticket rows across all Nova ticket record types."""
        clean_limit = max(1, min(int(limit), 500))
        result = client.list_open_tickets(limit=500)
        records = []
        for record in result.get("records", []):
            if not isinstance(record, dict):
                continue
            record_type = (
                record.get("RecordType")
                if isinstance(record.get("RecordType"), dict)
                else {}
            )
            if str(record_type.get("Name") or "") in readable_types:
                records.append(record)
            if len(records) >= clean_limit:
                break
        return {
            **result,
            "records": records,
            "count": len(records),
            "rowCeiling": clean_limit,
            "lane": "claude_agent",
            "ticketRecordTypes": sorted(readable_types),
            "ticketWriteRecordTypes": [],
        }

    @mcp.tool(annotations=READ)
    def salesforce_weekly_ticket_totals(
        start_utc: str,
        end_utc: str,
    ) -> dict[str, Any]:
        """Count all Classic and Wave tickets in one bounded UTC report window."""
        return client.weekly_ticket_totals(
            start_utc=start_utc,
            end_utc=end_utc,
        )

    @mcp.tool(annotations=READ)
    def salesforce_ticket_read(ticket_id: str) -> dict[str, Any]:
        """Read one exact Nova ticket."""
        return client.read_ticket(ticket_id)

    @mcp.tool(annotations=READ)
    def salesforce_ticket_feed_read(
        ticket_id: str,
        limit: int = 8,
    ) -> dict[str, Any]:
        """Read one ticket's bounded recent Chatter feed."""
        return client.read_ticket_feed(ticket_id, limit=limit)

    @mcp.tool(annotations=READ)
    def salesforce_ticket_email_log_read(
        ticket_id: str,
        limit: int = 10,
    ) -> dict[str, Any]:
        """Read one ticket's bounded outbound email receipts."""
        return client.read_ticket_email_log(ticket_id, limit=limit)

    return mcp


def build_mcp(
    lane: str,
    client: ScopedSalesforceClient,
    nova_sql_client: ScopedNovaSqlClient | None = None,
    nova_api_client: ScopedNovaOpenApiClient | None = None,
) -> FastMCP:
    clean_lane = str(lane or "").strip()
    if clean_lane not in ALLOWED_LANES:
        raise RuntimeError("Salesforce scoped MCP requires a fixed approved agent lane")
    if clean_lane == "claude_agent":
        return _build_thor_salesforce_mcp(client)
    sql_client = nova_sql_client or ScopedNovaSqlClient(client, write_enabled=clean_lane == "coding_agent")
    api_client = nova_api_client or ScopedNovaOpenApiClient()
    ticket_record_types = LANE_TICKET_RECORD_TYPES[clean_lane]
    ticket_read_record_types = LANE_TICKET_READ_RECORD_TYPES[clean_lane]
    lane_capabilities = [*COMMON_CAPABILITIES, *TICKET_WRITE_CAPABILITIES]
    if clean_lane == "tickets_agent":
        lane_capabilities.append("salesforce_weekly_ticket_totals")
    if clean_lane in {"direct_codex", "tickets_agent", "billing_agent"}:
        lane_capabilities.extend(TICKET_CREATE_CAPABILITY)
    if clean_lane == "coding_agent":
        lane_capabilities.extend(SUPPORT_EMAIL_TICKET_CREATE_CAPABILITY)
    if clean_lane in {"direct_codex", "tickets_agent"}:
        lane_capabilities.extend(SUPPORT_CREDENTIAL_EMAIL_CAPABILITIES)
    lane_capabilities.extend(TICKET_EVIDENCE_CAPABILITIES)
    if clean_lane in {"billing_agent", "coding_agent"}:
        lane_capabilities.extend(BILLING_SHARED_CAPABILITIES)
    if clean_lane == "direct_codex":
        lane_capabilities.extend(LOCATION_LIFECYCLE_ORDER_CAPABILITIES)
    if clean_lane == "billing_agent":
        lane_capabilities.extend(BILLING_OBJECT_CAPABILITIES)
        lane_capabilities.extend(BILLING_CLOSURE_EMAIL_CAPABILITIES)
        lane_capabilities.extend(LOCATION_LIFECYCLE_ORDER_CAPABILITIES)
        lane_capabilities.extend(BILLING_PAYMENT_REDACTION_CAPABILITIES)
    if clean_lane == "coding_agent":
        lane_capabilities.extend(LOCATION_LIFECYCLE_ORDER_CAPABILITIES)
        lane_capabilities.extend(TAYLOR_SQL_READ_CAPABILITIES)
        lane_capabilities.extend(TAYLOR_SQL_WRITE_CAPABILITIES)
    mcp = FastMCP(
        f"Salesforce Scoped Operations ({clean_lane})",
        instructions=(
            "Use only the listed Nova business operations. This connection contains no generic Salesforce query, "
            "REST, Apex, Flow, Metadata, Tooling, setup, permission, or deletion capability. If an "
            "operation is unavailable, explain the limitation and route it to the owning administrator; "
            "never attempt to change this MCP's access. Nova SQL mutations are owned only by Taylor "
            "(coding_agent), and her guarded executor rejects destructive SQL and backs up every permanent "
            "target table before UPDATE or INSERT. It supports target-bound, set-based INSERT SELECT and "
            "UPDATE FROM JOIN reads from explicitly previewed Nova source accounts, parameterized ranges, "
            "local staging, UPDATE-then-INSERT upserts, and guarded identity insert. Source writes, unlisted "
            "databases, linked servers, and tenant-login cross-database access are rejected. "
            "For recurring account copies, use the schema-aware account-copy preview, status, and execute tools. "
            "They accept exact accounts, business tables, typed filters, match keys, column selections, and "
            "relationship declarations but no SQL. The broker discovers live schemas, deduplicates stable business "
            "keys, remaps integer identities with relationship crosswalks, blocks secrets, stores an immutable plan, "
            "backs up every changed target table, and rejects drift or orphaned references. "
            "Arbitrary ALTER remains rejected; the only schema exception "
            "is the typed, no-SQL-input dbo.Locations feature-column migration. Taylor also has one fixed "
            "location layaway enablement operation: callers provide only an exact company, LocationId list, "
            "and idempotency key; the broker owns the 90-day expiration, locked expiration-date flag, "
            "10-percent minimum, approved disclaimer, full Locations_Layaways backup, upsert, and readback. "
            "Taylor also has one fixed "
            "table-recovery operation that copies explicitly selected, non-secret columns from the internally "
            "resolved POS_<company>_RESTORE database into uniquely matched existing rows in the live table; "
            "it accepts no SQL and requires preview hash, full target backup, transaction, and readback. "
            "Taylor also has one fixed two-source Instyle set-based SQL copy whose only target is "
            "DEMO_NOVA_CAFE. It accepts no account, database, table, row, mapping, or SQL input; "
            "both sources stay read-only, and missing business rows including InventoryHistoryItem "
            "are copied by SQL Server with product dedupe and product-reference repair in the target "
            "transaction. Python never transports business rows. "
            "Taylor also has one destructive fixed catalog replacement whose only source is "
            "unique_lifestyle_llc, only target is oklahoma, and only category is HAWAII. It "
            "accepts no caller-selected database, category, table, mapping, row, or SQL input; "
            "the preview requires exact reviewed counts and zero external dependencies, the "
            "execute creates immutable full target backups and commits delete-and-copy in one "
            "transaction, and post-commit readback must prove the fixed final catalog. Generic "
            "DELETE remains unavailable. "
            "Salesforce ticket writes are "
            "checked immediately against this lane's fixed ticket record types. Support/engineering lanes cannot "
            "write billing tickets, and the billing lane cannot write support tickets except through the fixed "
            "account-cancellation Chatter/PDF/customer-EML evidence tools. Prefer the typed read-only "
            "Nova OpenAPI only after nova_api_preflight succeeds for the exact tenant. If it does not, retain the "
            "bounded Nova SQL read fallback. Salesforce customer emails must use the approved template inventory, "
            "server-side preview, and situation-based send tools; freehand subjects and bodies are unavailable. "
            "Internal employee requests use the action-owning ticket and "
            "salesforce_ticket_internal_request_post with one brief conversational message and a stable "
            "idempotency key. That tool creates a real mention and owns the first daily greeting; plain @Name "
            "text is not a handoff. Julio and Wiko request DMs use their separate configured Zoom aliases. "
            "This MCP exposes no Nova OpenAPI writes or deletes."
        ),
        json_response=True,
        stateless_http=True,
    )

    @mcp.tool(annotations=READ)
    def salesforce_capabilities() -> dict[str, Any]:
        """List this lane's actual typed Salesforce operations and permanent limitations."""
        return {
            "ok": True,
            "lane": clean_lane,
            "operations": lane_capabilities,
            "ticketRecordTypes": sorted(ticket_record_types),
            "billingAlignmentFeatures": {
                "stagedLocationLifecycleThenLinks": clean_lane
                in {"billing_agent", "coding_agent"},
                "exactPerSubscriptionStructureSelectors": clean_lane
                in {"billing_agent", "coding_agent"},
                "preservesNonemptyScheduleOwners": clean_lane
                in {"billing_agent", "coding_agent"},
            },
            "locationLifecycleOrderPolicy": {
                "exposed": clean_lane in {"direct_codex", "billing_agent", "coding_agent"},
                "allowedOrderTypes": dict(LOCATION_LIFECYCLE_ORDER_TYPE_LABELS),
                "withinThreeMonthsExistingOrderTypes": {
                    "add_additional_location": "New Location",
                },
                "reactivationAlwaysUses": "Re-activate an Existing Location",
                "classificationDatePriority": ["CreatedDate"],
                "forbiddenOrderType": FORBIDDEN_AGENT_ORDER_TYPE_LABEL,
                "merchantProviders": list(NOVA_INTEGRATED_MERCHANT_PROVIDERS),
                "approvalFlowAllowed": False,
                "reactivationFromDeclineAllowed": False,
                "locationReactivatedInNovaPosAllowed": False,
                "accountActivatedInNovaPosAllowed": False,
                "accountFlatRateMutationAllowed": False,
            },
            "paymentCardTicketRedactionExposed": clean_lane == "billing_agent",
            "permanentlyUnavailable": list(PERMANENTLY_UNAVAILABLE),
            "mayChangeAccess": False,
            "provider": client.capability_status(),
        }

    @mcp.tool(annotations=READ)
    def salesforce_explain_limitation(requested_action: str) -> dict[str, Any]:
        """Explain that an unsupported Salesforce action is outside this connection's fixed scope."""
        return {
            "ok": True,
            "available": False,
            "requestedAction": str(requested_action or "").strip()[:500],
            "reason": (
                "This agent does not have the API/MCP capability for that Salesforce action. "
                "Its connection is fixed to the operations and ticket record types reported by "
                "salesforce_capabilities. The agent cannot change or expand its own access."
            ),
            "mayChangeAccess": False,
        }

    @mcp.tool(annotations=READ)
    def nova_sql_capabilities() -> dict[str, Any]:
        """Report this lane's bounded Nova SQL readiness without exposing credentials."""
        return sql_client.capability_status()

    @mcp.tool(annotations=READ)
    def nova_sql_preflight(company_username: str) -> dict[str, Any]:
        """Verify one exact POS company database and return only bounded schema counts."""
        return sql_client.preflight(company_username)

    @mcp.tool(annotations=READ)
    def nova_billing_locations_read(company_username: str) -> dict[str, Any]:
        """Read the fixed current-location projection used by Nova BillingAutomation."""
        return sql_client.billing_locations(company_username)

    @mcp.tool(annotations=READ)
    def nova_sql_invoice_spare_investigation(
        company_username: str,
        invoice_id: int,
    ) -> dict[str, Any]:
        """Deeply reconcile one invoice, related spare transfers, lines, discounts, and payments."""
        return sql_client.invoice_spare_investigation(company_username, invoice_id)

    @mcp.tool(annotations=READ)
    def nova_sql_read(
        company_username: str,
        sql: str,
        parameters: list[Any] | None = None,
        max_rows: int = 100,
    ) -> dict[str, Any]:
        """Run one bounded SELECT against the exact POS company database; writes and protected columns are rejected."""
        return sql_client.read(company_username, sql, parameters, max_rows=max_rows)

    if clean_lane == "coding_agent":

        @mcp.tool(annotations=READ)
        def nova_sql_api_customer_email_cohort() -> dict[str, Any]:
            """Read Taylor's fixed verified API-customer recipient cohort; exposes no SQL input and sends no email."""
            return sql_client.api_customer_email_cohort()

    @mcp.tool(annotations=READ)
    def nova_api_capabilities() -> dict[str, Any]:
        """Report the production Nova OpenAPI read-only scope and exact-tenant credential readiness."""
        return api_client.capability_status()

    @mcp.tool(annotations=READ)
    def nova_api_health() -> dict[str, Any]:
        """Verify the public production Nova OpenAPI service without accessing tenant data."""
        return api_client.health()

    @mcp.tool(annotations=READ)
    def nova_api_preflight(company_username: str) -> dict[str, Any]:
        """Authenticate one exact configured API tenant and prove a bounded regions read succeeds."""
        return api_client.preflight(company_username)

    @mcp.tool(annotations=READ)
    def nova_api_regions(company_username: str) -> dict[str, Any]:
        """Read regions for the exact preflighted Nova API tenant."""
        return api_client.regions(company_username)

    @mcp.tool(annotations=READ)
    def nova_api_locations_by_region(
        company_username: str,
        region_id: int,
        include_all: bool = False,
    ) -> dict[str, Any]:
        """Read locations in one exact region for the configured API tenant."""
        return api_client.locations_by_region(company_username, region_id, include_all=include_all)

    @mcp.tool(annotations=READ)
    def nova_api_location_general_settings(company_username: str, location_id: int) -> dict[str, Any]:
        """Read one location's general settings through the Nova API."""
        return api_client.location_general_settings(company_username, location_id)

    @mcp.tool(annotations=READ)
    def nova_api_location_preferences(company_username: str, location_id: int) -> dict[str, Any]:
        """Read one location's preferences through the Nova API."""
        return api_client.location_preferences(company_username, location_id)

    @mcp.tool(annotations=READ)
    def nova_api_customers(
        company_username: str,
        page_number: int = 1,
        page_size: int = 100,
        search_text: str = "",
        region_id: int | None = None,
        location_id: int | None = None,
    ) -> dict[str, Any]:
        """Read one bounded customer page through the Nova API."""
        return api_client.customers(
            company_username,
            page_number=page_number,
            page_size=page_size,
            search_text=search_text,
            region_id=region_id,
            location_id=location_id,
        )

    @mcp.tool(annotations=READ)
    def nova_api_customer(company_username: str, customer_id: int) -> dict[str, Any]:
        """Read one exact customer through the Nova API."""
        return api_client.customer(company_username, customer_id)

    @mcp.tool(annotations=READ)
    def nova_api_products(
        company_username: str,
        page_number: int = 1,
        page_size: int = 100,
        search_text: str = "",
        category_id: int | None = None,
    ) -> dict[str, Any]:
        """Read one bounded product page through the Nova API."""
        return api_client.products(
            company_username,
            page_number=page_number,
            page_size=page_size,
            search_text=search_text,
            category_id=category_id,
        )

    @mcp.tool(annotations=READ)
    def nova_api_product(company_username: str, product_id: int) -> dict[str, Any]:
        """Read one exact product through the Nova API."""
        return api_client.product(company_username, product_id)

    @mcp.tool(annotations=READ)
    def nova_api_inventory(
        company_username: str,
        page_number: int = 1,
        page_size: int = 100,
        product_id: int | None = None,
        location_id: int | None = None,
        only_low_stock: bool = False,
    ) -> dict[str, Any]:
        """Read one bounded inventory page through the Nova API."""
        return api_client.inventory(
            company_username,
            page_number=page_number,
            page_size=page_size,
            product_id=product_id,
            location_id=location_id,
            only_low_stock=only_low_stock,
        )

    @mcp.tool(annotations=READ)
    def nova_api_invoices(
        company_username: str,
        page_number: int = 1,
        page_size: int = 100,
        customer_id: int | None = None,
        location_id: int | None = None,
        region_id: int | None = None,
        start_date_utc: str = "",
        end_date_utc: str = "",
    ) -> dict[str, Any]:
        """Read one bounded invoice page through the Nova API."""
        return api_client.invoices(
            company_username,
            page_number=page_number,
            page_size=page_size,
            customer_id=customer_id,
            location_id=location_id,
            region_id=region_id,
            start_date_utc=start_date_utc,
            end_date_utc=end_date_utc,
        )

    @mcp.tool(annotations=READ)
    def nova_api_invoice(company_username: str, invoice_id: int) -> dict[str, Any]:
        """Read one exact invoice through the Nova API."""
        return api_client.invoice(company_username, invoice_id)

    @mcp.tool(annotations=READ)
    def nova_api_invoice_payments(company_username: str, invoice_id: int) -> dict[str, Any]:
        """Read payments for one exact invoice through the Nova API."""
        return api_client.invoice_payments(company_username, invoice_id)

    @mcp.tool(annotations=READ)
    def nova_api_users(
        company_username: str,
        page_number: int = 1,
        page_size: int = 100,
        search_text: str = "",
        region_id: int | None = None,
        is_employed: bool | None = None,
    ) -> dict[str, Any]:
        """Read one bounded user page through the Nova API."""
        return api_client.users(
            company_username,
            page_number=page_number,
            page_size=page_size,
            search_text=search_text,
            region_id=region_id,
            is_employed=is_employed,
        )

    if clean_lane == "coding_agent":

        @mcp.tool(annotations=READ)
        def nova_sql_data_move_read(
            target_company_username: str,
            source_company_usernames: list[str],
            sql: str,
            parameters: list[Any] | None = None,
            max_rows: int = 100,
        ) -> dict[str, Any]:
            """Read a bounded cross-account candidate projection using only the exact target and explicitly allowlisted Nova sources."""
            return sql_client.data_move_read(
                target_company_username=target_company_username,
                source_company_usernames=source_company_usernames,
                sql=sql,
                parameters=parameters,
                max_rows=max_rows,
            )

        @mcp.tool(annotations=READ)
        def nova_sql_write_preview(
            company_username: str,
            statements: list[dict[str, Any]],
            verification_sql: str,
            expected_affected_rows: int,
            expected_verification_value: int,
            idempotency_key: str,
            verification_parameters: list[Any] | None = None,
            source_company_usernames: list[str] | None = None,
        ) -> dict[str, Any]:
            """Validate Taylor's local or cross-account set-based UPDATE/INSERT/temp-table plan and mandatory target backups; change no rows."""
            return sql_client.preview_write(
                company_username=company_username,
                statements=statements,
                verification_sql=verification_sql,
                verification_parameters=verification_parameters,
                expected_affected_rows=expected_affected_rows,
                expected_verification_value=expected_verification_value,
                idempotency_key=idempotency_key,
                source_company_usernames=source_company_usernames,
            )

        @mcp.tool(annotations=GUARDED_WRITE)
        def nova_sql_execute_guarded(
            company_username: str,
            statements: list[dict[str, Any]],
            verification_sql: str,
            expected_affected_rows: int,
            expected_verification_value: int,
            idempotency_key: str,
            preview_hash: str,
            verification_parameters: list[Any] | None = None,
            source_company_usernames: list[str] | None = None,
        ) -> dict[str, Any]:
            """Execute Taylor's previewed local or cross-account set-based plan after backing up every permanent target; source writes and DELETE/DROP are impossible."""
            return sql_client.execute_guarded_write(
                company_username=company_username,
                statements=statements,
                verification_sql=verification_sql,
                verification_parameters=verification_parameters,
                expected_affected_rows=expected_affected_rows,
                expected_verification_value=expected_verification_value,
                idempotency_key=idempotency_key,
                preview_hash=preview_hash,
                source_company_usernames=source_company_usernames,
            )

        @mcp.tool(annotations=READ)
        def nova_sql_account_copy_preview(
            source_company_username: str,
            target_company_username: str,
            tables: list[dict[str, Any]],
            idempotency_key: str,
            ticket_number: str = "",
        ) -> dict[str, Any]:
            """Build an immutable schema-aware account-copy plan from typed table scopes and relationships; accepts no SQL and changes no rows."""
            return sql_client.preview_account_copy(
                source_company_username=source_company_username,
                target_company_username=target_company_username,
                tables=tables,
                idempotency_key=idempotency_key,
                ticket_number=ticket_number,
            )

        @mcp.tool(annotations=READ)
        def nova_sql_account_copy_status(plan_id: str) -> dict[str, Any]:
            """Read the durable state of one immutable account-copy plan before retrying any uncertain execution."""
            return sql_client.account_copy_status(plan_id=plan_id)

        @mcp.tool(annotations=GUARDED_WRITE)
        def nova_sql_account_copy_execute(plan_id: str) -> dict[str, Any]:
            """Execute only one approved immutable account-copy plan with full target backups, one transaction, and relationship readback."""
            return sql_client.execute_account_copy(plan_id=plan_id)

        @mcp.tool(annotations=READ)
        def nova_sql_ticket_347534_invoice_repair_preview(
            idempotency_key: str,
        ) -> dict[str, Any]:
            """Preview the fixed repair that removes only ticket 347534 invoices copied from source Location 3 while preserving invoice 73242."""
            return sql_client.preview_ticket_347534_invoice_repair(
                idempotency_key=idempotency_key,
            )

        @mcp.tool(annotations=READ)
        def nova_sql_ticket_347534_invoice_repair_status(
            idempotency_key: str,
        ) -> dict[str, Any]:
            """Read durable state for the fixed ticket 347534 invoice repair before any retry."""
            return sql_client.status_ticket_347534_invoice_repair(
                idempotency_key=idempotency_key,
            )

        @mcp.tool(annotations=GUARDED_WRITE)
        def nova_sql_ticket_347534_invoice_repair_execute(
            idempotency_key: str,
            preview_hash: str,
        ) -> dict[str, Any]:
            """Execute the fixed reviewed repair with full target backups, one transaction, and protected-invoice readback; accepts no SQL or caller-selected scope."""
            return sql_client.execute_ticket_347534_invoice_repair(
                idempotency_key=idempotency_key,
                preview_hash=preview_hash,
            )

        @mcp.tool(annotations=GUARDED_WRITE)
        def nova_sql_location_region_update(
            company_username: str,
            location_id: int,
            region_id: int,
            idempotency_key: str,
        ) -> dict[str, Any]:
            """Set one exact location RegionId with a full Locations backup and verified readback; accepts no SQL."""
            return sql_client.update_location_region(
                company_username=company_username,
                location_id=location_id,
                region_id=region_id,
                idempotency_key=idempotency_key,
            )

        @mcp.tool(annotations=GUARDED_WRITE)
        def nova_sql_location_reactivation_update(
            company_username: str,
            location_id: int,
            idempotency_key: str,
        ) -> dict[str, Any]:
            """Change one exact location manager employee from 1 to 0 with a full Locations backup and verified readback; accepts no SQL."""
            return sql_client.update_location_reactivation(
                company_username=company_username,
                location_id=location_id,
                idempotency_key=idempotency_key,
            )

        @mcp.tool(annotations=GUARDED_WRITE)
        def nova_sql_location_layaway_enable(
            company_username: str,
            location_ids: list[int],
            idempotency_key: str,
        ) -> dict[str, Any]:
            """Enable layaway for exact locations with fixed 90/0/10 settings and disclaimer; accepts no SQL or caller-selected defaults."""
            return sql_client.enable_location_layaways(
                company_username=company_username,
                location_ids=location_ids,
                idempotency_key=idempotency_key,
            )

        @mcp.tool(annotations=READ)
        def nova_sql_locations_feature_columns_preview(
            company_username: str,
            idempotency_key: str,
        ) -> dict[str, Any]:
            """Preview Taylor's fixed five-column dbo.Locations migration; accepts no caller-supplied SQL."""
            return sql_client.preview_locations_feature_columns_migration(
                company_username=company_username,
                idempotency_key=idempotency_key,
            )

        @mcp.tool(annotations=GUARDED_WRITE)
        def nova_sql_locations_feature_columns_execute(
            company_username: str,
            idempotency_key: str,
            preview_hash: str,
        ) -> dict[str, Any]:
            """Back up dbo.Locations, add only the five approved nullable columns, and verify exact definitions."""
            return sql_client.execute_locations_feature_columns_migration(
                company_username=company_username,
                idempotency_key=idempotency_key,
                preview_hash=preview_hash,
            )

        @mcp.tool(annotations=READ)
        def nova_sql_kit_upgrade_preview(
            company_username: str,
            idempotency_key: str,
        ) -> dict[str, Any]:
            """Preview the fixed Kit upgrade for one exact Salesforce-resolved company username."""
            return sql_client.preview_kit_upgrade(
                company_username=company_username,
                idempotency_key=idempotency_key,
            )

        @mcp.tool(annotations=GUARDED_WRITE)
        def nova_sql_kit_upgrade_execute(
            company_username: str,
            idempotency_key: str,
            preview_hash: str,
        ) -> dict[str, Any]:
            """Back up exact-account dbo.Kit, add only 15 approved nullable columns, and verify readback."""
            return sql_client.execute_kit_upgrade(
                company_username=company_username,
                idempotency_key=idempotency_key,
                preview_hash=preview_hash,
            )

        @mcp.tool(annotations=READ)
        def nova_sql_table_restore_preview(
            company_username: str,
            schema_name: str,
            table_name: str,
            key_columns: list[str],
            restore_columns: list[str],
            idempotency_key: str,
        ) -> dict[str, Any]:
            """Preview selected-column recovery from the fixed POS_<company>_RESTORE copy; accepts no SQL."""
            return sql_client.preview_table_restore(
                company_username=company_username,
                schema_name=schema_name,
                table_name=table_name,
                key_columns=key_columns,
                restore_columns=restore_columns,
                idempotency_key=idempotency_key,
            )

        @mcp.tool(annotations=GUARDED_WRITE)
        def nova_sql_table_restore_execute(
            company_username: str,
            schema_name: str,
            table_name: str,
            key_columns: list[str],
            restore_columns: list[str],
            idempotency_key: str,
            preview_hash: str,
        ) -> dict[str, Any]:
            """Restore only the previewed columns on uniquely matched existing rows after a full target backup."""
            return sql_client.execute_table_restore(
                company_username=company_username,
                schema_name=schema_name,
                table_name=table_name,
                key_columns=key_columns,
                restore_columns=restore_columns,
                idempotency_key=idempotency_key,
                preview_hash=preview_hash,
            )

        @mcp.tool(annotations=READ)
        def nova_sql_instyle_demo_sync_preview(
            idempotency_key: str,
        ) -> dict[str, Any]:
            """Preview the fixed set-based SQL Instyle sync into DEMO_NOVA_CAFE; accepts no SQL or account input."""
            return sql_client.preview_instyle_demo_sync(
                idempotency_key=idempotency_key,
            )

        @mcp.tool(annotations=READ)
        def nova_sql_instyle_demo_sync_status(
            idempotency_key: str,
        ) -> dict[str, Any]:
            """Read-only reconciliation for an uncertain fixed Instyle demo execute; required before any retry."""
            return sql_client.status_instyle_demo_sync(
                idempotency_key=idempotency_key,
            )

        @mcp.tool(annotations=GUARDED_WRITE)
        def nova_sql_instyle_demo_sync_execute(
            idempotency_key: str,
            preview_hash: str,
        ) -> dict[str, Any]:
            """Execute the exact previewed incremental sync; preserve demo history and keep both sources read-only."""
            return sql_client.execute_instyle_demo_sync(
                idempotency_key=idempotency_key,
                preview_hash=preview_hash,
            )

        @mcp.tool(annotations=READ)
        def nova_sql_instyle_runway_merge_preview(
            idempotency_key: str,
        ) -> dict[str, Any]:
            """Preview the fixed production merge into INSTYLE_RUNWAY; accepts no account, mapping, or SQL input."""
            return sql_client.preview_instyle_runway_merge(
                idempotency_key=idempotency_key,
            )

        @mcp.tool(annotations=READ)
        def nova_sql_instyle_runway_merge_status(
            idempotency_key: str,
        ) -> dict[str, Any]:
            """Read-only reconciliation for an uncertain fixed Instyle Runway merge."""
            return sql_client.status_instyle_runway_merge(
                idempotency_key=idempotency_key,
            )

        @mcp.tool(annotations=GUARDED_WRITE)
        def nova_sql_instyle_runway_merge_execute(
            idempotency_key: str,
            preview_hash: str,
        ) -> dict[str, Any]:
            """Execute the exact production preview with backups, rollback, and exhaustive readback."""
            return sql_client.execute_instyle_runway_merge(
                idempotency_key=idempotency_key,
                preview_hash=preview_hash,
            )

        @mcp.tool(annotations=READ)
        def nova_sql_oklahoma_hawaii_catalog_replace_preview(
            idempotency_key: str,
        ) -> dict[str, Any]:
            """Preview the no-input fixed HAWAII catalog replacement into Oklahoma."""
            return sql_client.preview_oklahoma_hawaii_catalog_replace(
                idempotency_key=idempotency_key,
            )

        @mcp.tool(annotations=READ)
        def nova_sql_oklahoma_hawaii_catalog_replace_status(
            idempotency_key: str,
        ) -> dict[str, Any]:
            """Reconcile one uncertain fixed Oklahoma HAWAII catalog replacement."""
            return sql_client.status_oklahoma_hawaii_catalog_replace(
                idempotency_key=idempotency_key,
            )

        @mcp.tool(annotations=FIXED_DESTRUCTIVE_WRITE)
        def nova_sql_oklahoma_hawaii_catalog_replace_execute(
            idempotency_key: str,
            preview_hash: str,
        ) -> dict[str, Any]:
            """Atomically replace only Oklahoma's catalog from Unique Lifestyle HAWAII after full backups."""
            return sql_client.execute_oklahoma_hawaii_catalog_replace(
                idempotency_key=idempotency_key,
                preview_hash=preview_hash,
            )

    @mcp.tool(annotations=READ)
    def salesforce_lookup(kind: str, value: str, account_id: str = "", limit: int = 10) -> dict[str, Any]:
        """Look up a ticket, account, contact, location, or order through fixed queries."""
        return client.lookup(kind, value, account_id=account_id, limit=limit)

    @mcp.tool(annotations=READ)
    def salesforce_account_360_read(
        search: str,
        contacts_limit: int = 100,
        locations_limit: int = 250,
        tickets_limit: int = 250,
    ) -> dict[str, Any]:
        """Resolve one account from an account, contact, location, or ticket identity and return its full read view."""
        return client.read_account_360(
            search,
            contacts_limit=contacts_limit,
            locations_limit=locations_limit,
            tickets_limit=tickets_limit,
        )

    @mcp.tool(annotations=READ)
    def salesforce_ticket_list_open(limit: int = 200) -> dict[str, Any]:
        """List this lane's bounded open board records; Alex may read Billing rows but cannot write them."""
        clean_limit = max(1, min(int(limit), 500))
        result = client.list_open_tickets(limit=500)
        records = []
        for record in result.get("records", []):
            if not isinstance(record, dict):
                continue
            record_type = record.get("RecordType") if isinstance(record.get("RecordType"), dict) else {}
            if str(record_type.get("Name") or "") in ticket_read_record_types:
                records.append(record)
            if len(records) >= clean_limit:
                break
        return {
            **result,
            "records": records,
            "count": len(records),
            "rowCeiling": clean_limit,
            "lane": clean_lane,
            "ticketRecordTypes": sorted(ticket_read_record_types),
            "ticketWriteRecordTypes": sorted(ticket_record_types),
        }

    if clean_lane == "tickets_agent":

        @mcp.tool(annotations=READ)
        def salesforce_weekly_ticket_totals(start_utc: str, end_utc: str) -> dict[str, Any]:
            """Count all Classic/Wave tickets in one bounded UTC report window."""
            return client.weekly_ticket_totals(start_utc=start_utc, end_utc=end_utc)

    @mcp.tool(annotations=READ)
    def salesforce_ticket_read(ticket_id: str) -> dict[str, Any]:
        """Read one exact NovaPOS_Ticket__c record."""
        return client.read_ticket(ticket_id)

    @mcp.tool(annotations=READ)
    def salesforce_ticket_feed_read(ticket_id: str, limit: int = 8) -> dict[str, Any]:
        """Read a bounded recent Chatter feed for one exact NovaPOS_Ticket__c record."""
        return client.read_ticket_feed(ticket_id, limit=limit)

    @mcp.tool(annotations=READ)
    def salesforce_ticket_email_log_read(ticket_id: str, limit: int = 10) -> dict[str, Any]:
        """Read bounded outbound EmailMessage receipts for one exact ticket before retrying a send."""
        return client.read_ticket_email_log(ticket_id, limit=limit)

    @mcp.tool(annotations=READ)
    def salesforce_email_sender_preflight() -> dict[str, Any]:
        """Check only the fixed support, billing, and reply-only Darius Org-Wide Email policies."""
        return client.email_sender_preflight()

    @mcp.tool(annotations=READ)
    def salesforce_email_template_inventory() -> dict[str, Any]:
        """Classify all approved-folder templates and canonical pending workflows for this exact lane."""
        return client.approved_email_template_inventory(lane=clean_lane)

    @mcp.tool(annotations=READ)
    def salesforce_ticket_template_email_preview(
        ticket_id: str,
        situation: str,
        details: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Preview one lane-owned template with its fixed department sender; no sender override exists."""
        return client.preview_ticket_template_email(
            ticket_id=ticket_id,
            situation=situation,
            details=details,
            lane=clean_lane,
            allowed_record_types=ticket_record_types,
        )

    if clean_lane in {"direct_codex", "tickets_agent"}:

        @mcp.tool(annotations=READ)
        def salesforce_ticket_company_credentials_email_preview(
            ticket_id: str,
            requested_recipients: list[str],
        ) -> dict[str, Any]:
            """Preview only ticket 347370's fixed credential template; returns no body, hashes, or secret fragments."""
            return client.preview_ticket_company_credentials_email(
                ticket_id=ticket_id,
                requested_recipients=requested_recipients,
                lane=clean_lane,
                allowed_record_types=ticket_record_types,
            )

    if clean_lane in {"direct_codex", "tickets_agent", "billing_agent"}:

        @mcp.tool(annotations=WRITE)
        def salesforce_ticket_create(
            account_id: str,
            description: str,
            contact_id: str = "",
            location_id: str = "",
            record_type_id: str = "",
            main_issue: str = "",
            technical_issue: str = "",
            customer_contact_method: str = "",
        ) -> dict[str, Any]:
            """Create one lane-owned ticket with record-type enforcement and readback."""
            return client.create_ticket(
                account_id=account_id,
                description=description,
                contact_id=contact_id,
                location_id=location_id,
                record_type_id=record_type_id,
                main_issue=main_issue,
                technical_issue=technical_issue,
                customer_contact_method=customer_contact_method,
                allowed_record_types=ticket_record_types,
            )

    if clean_lane == "coding_agent":

        @mcp.tool(annotations=GUARDED_WRITE)
        def salesforce_support_email_ticket_create(
            account_id: str,
            description: str,
            source_email_id: str,
            source_key: str,
            record_type_id: str,
            contact_id: str = "",
            location_id: str = "",
            main_issue: str = "",
            technical_issue: str = "",
            customer_contact_method: str = "",
        ) -> dict[str, Any]:
            """Create or reuse one journaled support-email ticket with server-owned creator and readback."""

            ticket_created_by = str(
                os.getenv("SALESFORCE_SUPPORT_EMAIL_TICKET_CREATED_BY") or ""
            ).strip()
            if ticket_created_by != "Darius Parlor":
                raise SalesforceScopeError(
                    "The server-owned support-email ticket creator is not configured."
                )
            return client.create_support_email_ticket(
                account_id=account_id,
                description=description,
                source_email_id=source_email_id,
                source_key=source_key,
                record_type_id=record_type_id,
                contact_id=contact_id,
                location_id=location_id,
                main_issue=main_issue,
                technical_issue=technical_issue,
                customer_contact_method=customer_contact_method,
                ticket_created_by=ticket_created_by,
                allowed_record_types=ticket_record_types,
            )

    if clean_lane == "billing_agent":

        @mcp.tool(annotations=GUARDED_WRITE)
        def salesforce_billing_closure_email_ticket_create(
            account_id: str,
            description: str,
            source_email_id: str,
            source_key: str,
            contact_id: str = "",
            location_id: str = "",
            main_issue: str = "",
            technical_issue: str = "",
            customer_contact_method: str = "",
        ) -> dict[str, Any]:
            """Create or reuse one journaled Billing ticket for an exact closure-confirmation email."""

            ticket_created_by = str(
                os.getenv("SALESFORCE_BILLING_EMAIL_TICKET_CREATED_BY")
                or os.getenv("SALESFORCE_SUPPORT_EMAIL_TICKET_CREATED_BY")
                or ""
            ).strip()
            if ticket_created_by != "Darius Parlor":
                raise SalesforceScopeError(
                    "The server-owned billing-email ticket creator is not configured."
                )
            return client.create_billing_closure_email_ticket(
                account_id=account_id,
                description=description,
                source_email_id=source_email_id,
                source_key=source_key,
                contact_id=contact_id,
                location_id=location_id,
                main_issue=main_issue,
                technical_issue=technical_issue,
                customer_contact_method=customer_contact_method,
                ticket_created_by=ticket_created_by,
                allowed_record_types=ticket_record_types,
            )

        @mcp.tool(annotations=READ)
        def salesforce_payment_card_ticket_redaction_preview(
            ticket_id: str,
        ) -> dict[str, Any]:
            """Preview clearing fixed card fields and redacting raw card text on one Billing ticket."""

            return client.payment_card_ticket_redaction_preview(ticket_id)

        @mcp.tool(annotations=GUARDED_WRITE)
        def salesforce_payment_card_ticket_redaction_apply(
            ticket_id: str,
            preview_hash: str,
            idempotency_key: str,
        ) -> dict[str, Any]:
            """Redact one unchanged Billing ticket plan and verify sensitive payment data is absent."""

            return client.apply_payment_card_ticket_redaction(
                ticket_id,
                preview_hash=preview_hash,
                idempotency_key=idempotency_key,
            )

    @mcp.tool(annotations=WRITE)
    def salesforce_ticket_update(ticket_id: str, fields: dict[str, Any]) -> dict[str, Any]:
        """Update one ticket using the server-side ticket field allowlist and read it back."""
        return client.update_ticket(ticket_id, fields, allowed_record_types=ticket_record_types)

    @mcp.tool(annotations=GUARDED_WRITE)
    def salesforce_ticket_internal_note_update(
        ticket_id: str,
        cause: str = "",
        resolution: str = "",
        next_steps: str = "",
        priority_context: str = "",
        update: str = "",
    ) -> dict[str, Any]:
        """Legacy Chatter alias; post only a net-new update, never Technical Notes."""
        return client.update_ticket_internal_note(
            ticket_id,
            ticket_chatter_update_body(
                cause,
                resolution,
                next_steps,
                priority_context,
                update=update,
            ),
            allowed_record_types=ticket_record_types,
        )

    @mcp.tool(annotations=GUARDED_WRITE)
    def salesforce_ticket_chatter_post(
        ticket_id: str,
        cause: str = "",
        resolution: str = "",
        next_steps: str = "",
        priority_context: str = "",
        update: str = "",
    ) -> dict[str, Any]:
        """Post only net-new resolution progress, action, insight, or follow-up."""
        return client.post_ticket_chatter(
            ticket_id,
            ticket_chatter_update_body(
                cause,
                resolution,
                next_steps,
                priority_context,
                update=update,
            ),
            allowed_record_types=ticket_record_types,
        )

    @mcp.tool(annotations=GUARDED_WRITE)
    def salesforce_ticket_chatter_reply(
        ticket_id: str,
        feed_element_id: str,
        cause: str = "",
        resolution: str = "",
        next_steps: str = "",
        priority_context: str = "",
        update: str = "",
    ) -> dict[str, Any]:
        """Reply to one relevant existing ticket post with a net-new update."""
        return client.reply_ticket_chatter(
            ticket_id,
            feed_element_id,
            ticket_chatter_update_body(
                cause,
                resolution,
                next_steps,
                priority_context,
                update=update,
            ),
            allowed_record_types=ticket_record_types,
        )

    @mcp.tool(annotations=GUARDED_WRITE)
    def salesforce_ticket_internal_request_post(
        ticket_id: str,
        exact_user: str,
        message: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        """Post one brief employee request with a real Salesforce @mention and verified readback."""
        return client.post_ticket_internal_request(
            ticket_id,
            exact_user,
            message,
            idempotency_key,
            allowed_record_types=ticket_record_types,
        )

    @mcp.tool(annotations=GUARDED_WRITE)
    def salesforce_ticket_resolve(
        ticket_id: str,
        feed_element_id: str = "",
        cause: str = "",
        resolution: str = "",
        next_steps: str = "",
        priority_context: str = "",
        update: str = "",
    ) -> dict[str, Any]:
        """Close with readback; add Chatter only when a net-new update is supplied."""
        note = ""
        if any(str(value or "").strip() for value in (cause, resolution, next_steps, priority_context, update)):
            note = ticket_chatter_update_body(
                cause,
                resolution,
                next_steps,
                priority_context,
                update=update,
            )
        return client.resolve_ticket(
            ticket_id,
            note,
            reply_to_feed_element_id=feed_element_id,
            allowed_record_types=ticket_record_types,
        )

    if clean_lane in ALLOWED_LANES:

        @mcp.tool(annotations=GUARDED_WRITE)
        def salesforce_ticket_contact_email_update(
            ticket_id: str,
            contact_id: str,
            email: str,
            idempotency_key: str,
        ) -> dict[str, Any]:
            """Set only the already-linked Contact email and verify exact readback."""
            return client.update_ticket_contact_email(
                ticket_id,
                contact_id,
                email,
                idempotency_key=idempotency_key,
                allowed_record_types=ticket_record_types,
            )

        @mcp.tool(annotations=READ)
        def salesforce_ticket_attachment_status(
            ticket_id: str,
            file_name: str,
            sha256: str,
        ) -> dict[str, Any]:
            """Check an exact safe attachment digest against one lane-owned ticket without writing."""
            return client.ticket_attachment_status(
                ticket_id,
                file_name,
                sha256,
                allowed_record_types=ticket_record_types,
            )

        @mcp.tool(annotations=GUARDED_WRITE)
        def salesforce_ticket_attachment_upload(
            ticket_id: str,
            file_name: str,
            content_base64: str,
            sha256: str,
            idempotency_key: str,
        ) -> dict[str, Any]:
            """Attach one verified safe file to a lane-owned ticket with digest readback."""
            return client.upload_ticket_attachment(
                ticket_id,
                file_name,
                content_base64,
                sha256,
                idempotency_key=idempotency_key,
                allowed_record_types=ticket_record_types,
            )

        @mcp.tool(annotations=READ)
        def salesforce_ticket_pdf_status(
            ticket_id: str,
            file_name: str,
            sha256: str,
        ) -> dict[str, Any]:
            """Check an exact PDF digest against one lane-owned ticket without writing."""
            return client.ticket_pdf_status(
                ticket_id,
                file_name,
                sha256,
                allowed_record_types=ticket_record_types,
            )

        @mcp.tool(annotations=GUARDED_WRITE)
        def salesforce_ticket_pdf_upload(
            ticket_id: str,
            file_name: str,
            content_base64: str,
            sha256: str,
            idempotency_key: str,
        ) -> dict[str, Any]:
            """Attach one verified PDF to a lane-owned ticket with digest readback."""
            return client.upload_ticket_pdf(
                ticket_id,
                file_name,
                content_base64,
                sha256,
                idempotency_key=idempotency_key,
                allowed_record_types=ticket_record_types,
            )

    if clean_lane in {"direct_codex", "billing_agent", "coding_agent"}:

        @mcp.tool(annotations=READ)
        def salesforce_location_lifecycle_order_preview(
            ticket_id: str,
            account_id: str,
            salesforce_location_ids: list[str],
            action: str,
            chargify_subscription_id: int,
            monthly_rate_cents: int = 9999,
            merchant_provider: str = "",
        ) -> dict[str, Any]:
            """Preview a correctly classified reactivation or additional-location order with no approval."""
            return client.location_lifecycle_order_preview(
                ticket_id,
                account_id,
                salesforce_location_ids,
                action,
                chargify_subscription_id,
                monthly_rate_cents=monthly_rate_cents,
                merchant_provider=merchant_provider,
            )

        @mcp.tool(annotations=GUARDED_WRITE)
        def salesforce_location_lifecycle_order_apply(
            ticket_id: str,
            account_id: str,
            salesforce_location_ids: list[str],
            action: str,
            chargify_subscription_id: int,
            idempotency_key: str,
            preview_hash: str,
            monthly_rate_cents: int = 9999,
            merchant_provider: str = "",
        ) -> dict[str, Any]:
            """Create or reclassify one unchanged lifecycle order and verify no approval was submitted."""
            return client.apply_location_lifecycle_order(
                ticket_id,
                account_id,
                salesforce_location_ids,
                action,
                chargify_subscription_id,
                idempotency_key=idempotency_key,
                preview_hash=preview_hash,
                monthly_rate_cents=monthly_rate_cents,
                merchant_provider=merchant_provider,
            )

    if clean_lane == "coding_agent":

        @mcp.tool(annotations=READ)
        def salesforce_billing_account_read(account_id: str) -> dict[str, Any]:
            """Read one exact Account's billing rate fields used to select the Maxio location component."""
            return client.read_billing_account(account_id)

        @mcp.tool(annotations=READ)
        def salesforce_billing_account_locations_read(
            account_id: str,
            limit: int = 500,
        ) -> dict[str, Any]:
            """Read one Account's Salesforce locations, lifecycle state, rates, and Maxio links."""
            return client.read_account_locations(account_id, limit=limit)

        @mcp.tool(annotations=READ)
        def salesforce_billing_account_orders_read(
            account_id: str,
            limit: int = 100,
        ) -> dict[str, Any]:
            """Read one Account's NovaPOS orders and approval evidence."""
            return client.read_account_orders(account_id, limit=limit)

        @mcp.tool(annotations=GUARDED_WRITE)
        def salesforce_billing_account_flat_rate_update(
            account_id: str,
            monthly_rate_cents: int,
            idempotency_key: str,
        ) -> dict[str, Any]:
            """Set only Account.Flat_Rate_Amount__c in integer cents and verify it."""
            return client.update_billing_account_flat_rate(
                account_id,
                monthly_rate_cents,
                idempotency_key=idempotency_key,
            )

        @mcp.tool(annotations=GUARDED_WRITE)
        def salesforce_billing_location_rate_update(
            location_id: str,
            monthly_rate_cents: int,
            idempotency_key: str,
        ) -> dict[str, Any]:
            """Set only one Salesforce location's Bill Amount in cents and verify it."""
            return client.update_billing_location_rate(
                location_id,
                monthly_rate_cents,
                idempotency_key=idempotency_key,
            )

    if clean_lane in {"billing_agent", "coding_agent"}:

        @mcp.tool(annotations=READ)
        def salesforce_billing_structure_read(account_id: str) -> dict[str, Any]:
            """Read all bounded Billing Account and Billing Schedule rows for one exact Account."""
            return client.read_billing_structure(account_id)

        @mcp.tool(annotations=READ)
        def salesforce_billing_schedule_date_preview(
            ticket_id: str,
            account_id: str,
            billing_schedule_id: str,
            subscription_id: int,
            start_date: str,
        ) -> dict[str, Any]:
            """Preview changing only one exact Billing Schedule Start_Date__c."""
            return client.billing_schedule_date_preview(
                ticket_id,
                account_id,
                billing_schedule_id,
                subscription_id,
                start_date,
            )

        @mcp.tool(annotations=GUARDED_WRITE)
        def salesforce_billing_schedule_date_apply(
            ticket_id: str,
            account_id: str,
            billing_schedule_id: str,
            subscription_id: int,
            start_date: str,
            preview_hash: str,
            idempotency_key: str,
        ) -> dict[str, Any]:
            """Apply one unchanged date-only schedule plan and verify the exact field."""
            return client.apply_billing_schedule_date(
                ticket_id,
                account_id,
                billing_schedule_id,
                subscription_id,
                start_date,
                preview_hash=preview_hash,
                idempotency_key=idempotency_key,
            )

        @mcp.tool(annotations=READ)
        def salesforce_account_fake_classification_preview(
            ticket_id: str,
            account_id: str,
            nova_id: str,
            is_fake: bool,
        ) -> dict[str, Any]:
            """Preview Account.Fake_Account__c after exact Nova ID and Billing-ticket checks."""
            return client.account_fake_classification_preview(
                ticket_id,
                account_id,
                nova_id,
                is_fake=is_fake,
            )

        @mcp.tool(annotations=GUARDED_WRITE)
        def salesforce_account_fake_classification_apply(
            ticket_id: str,
            account_id: str,
            nova_id: str,
            is_fake: bool,
            preview_hash: str,
            idempotency_key: str,
        ) -> dict[str, Any]:
            """Apply one unchanged fake/real classification and verify Account.Fake_Account__c."""
            return client.apply_account_fake_classification(
                ticket_id,
                account_id,
                nova_id,
                is_fake=is_fake,
                preview_hash=preview_hash,
                idempotency_key=idempotency_key,
            )

        @mcp.tool(annotations=READ)
        def salesforce_billing_location_alignment_preview(
            ticket_id: str,
            account_id: str,
            location_id: str,
            nova_location_id: int,
            desired_status: str,
            monthly_rate_cents: int | None = None,
            chargify_subscription_id: int | None = None,
            billing_schedule_id: str = "",
            clear_subscription_link: bool = False,
            clear_schedule_link: bool = False,
            billing_exception: str = "",
        ) -> dict[str, Any]:
            """Preview one exact location's status, rate, Maxio link, and schedule link."""
            return client.billing_location_alignment_preview(
                ticket_id,
                account_id,
                location_id,
                nova_location_id,
                desired_status=desired_status,
                monthly_rate_cents=monthly_rate_cents,
                chargify_subscription_id=chargify_subscription_id,
                billing_schedule_id=billing_schedule_id,
                clear_subscription_link=clear_subscription_link,
                clear_schedule_link=clear_schedule_link,
                billing_exception=billing_exception,
            )

        @mcp.tool(annotations=GUARDED_WRITE)
        def salesforce_billing_location_alignment_apply(
            ticket_id: str,
            account_id: str,
            location_id: str,
            nova_location_id: int,
            desired_status: str,
            preview_hash: str,
            idempotency_key: str,
            monthly_rate_cents: int | None = None,
            chargify_subscription_id: int | None = None,
            billing_schedule_id: str = "",
            clear_subscription_link: bool = False,
            clear_schedule_link: bool = False,
            billing_exception: str = "",
        ) -> dict[str, Any]:
            """Apply one unchanged location plan and verify every requested field."""
            return client.apply_billing_location_alignment(
                ticket_id,
                account_id,
                location_id,
                nova_location_id,
                desired_status=desired_status,
                monthly_rate_cents=monthly_rate_cents,
                chargify_subscription_id=chargify_subscription_id,
                billing_schedule_id=billing_schedule_id,
                clear_subscription_link=clear_subscription_link,
                clear_schedule_link=clear_schedule_link,
                billing_exception=billing_exception,
                preview_hash=preview_hash,
                idempotency_key=idempotency_key,
            )

        @mcp.tool(annotations=READ)
        def salesforce_billing_structure_alignment_preview(
            ticket_id: str,
            account_id: str,
            maxio_customer_id: int,
            payment_profile_id: int | None,
            subscription_id: int,
            subscription_state: str,
            bill_amount_cents: int,
            start_date: str,
            nova_location_ids: list[int],
            salesforce_location_ids: list[str] | None = None,
            billing_account_id: str = "",
            billing_schedule_id: str = "",
        ) -> dict[str, Any]:
            """Preview idempotent Billing Account/Schedule creation and location linking."""
            return client.billing_structure_alignment_preview(
                ticket_id,
                account_id,
                maxio_customer_id=maxio_customer_id,
                payment_profile_id=payment_profile_id,
                subscription_id=subscription_id,
                subscription_state=subscription_state,
                bill_amount_cents=bill_amount_cents,
                start_date=start_date,
                nova_location_ids=nova_location_ids,
                salesforce_location_ids=salesforce_location_ids,
                billing_account_id=billing_account_id,
                billing_schedule_id=billing_schedule_id,
            )

        @mcp.tool(annotations=GUARDED_WRITE)
        def salesforce_billing_structure_alignment_apply(
            ticket_id: str,
            account_id: str,
            maxio_customer_id: int,
            payment_profile_id: int | None,
            subscription_id: int,
            subscription_state: str,
            bill_amount_cents: int,
            start_date: str,
            nova_location_ids: list[int],
            preview_hash: str,
            idempotency_key: str,
            salesforce_location_ids: list[str] | None = None,
            billing_account_id: str = "",
            billing_schedule_id: str = "",
        ) -> dict[str, Any]:
            """Create or sync one Billing Account/Schedule, link locations, and verify all rows."""
            return client.apply_billing_structure_alignment(
                ticket_id,
                account_id,
                maxio_customer_id=maxio_customer_id,
                payment_profile_id=payment_profile_id,
                subscription_id=subscription_id,
                subscription_state=subscription_state,
                bill_amount_cents=bill_amount_cents,
                start_date=start_date,
                nova_location_ids=nova_location_ids,
                preview_hash=preview_hash,
                idempotency_key=idempotency_key,
                salesforce_location_ids=salesforce_location_ids,
                billing_account_id=billing_account_id,
                billing_schedule_id=billing_schedule_id,
            )

    if clean_lane == "billing_agent":

        @mcp.tool(annotations=READ)
        def salesforce_billing_account_read(account_id: str) -> dict[str, Any]:
            """Read one exact Account's billing rate fields used to select the Maxio location component."""
            return client.read_billing_account(account_id)

        @mcp.tool(annotations=READ)
        def salesforce_billing_account_locations_read(
            account_id: str,
            limit: int = 500,
        ) -> dict[str, Any]:
            """Read one Account's Salesforce locations, lifecycle state, rates, and Maxio links."""
            return client.read_account_locations(account_id, limit=limit)

        @mcp.tool(annotations=READ)
        def salesforce_billing_account_orders_read(
            account_id: str,
            limit: int = 100,
        ) -> dict[str, Any]:
            """Read one Account's NovaPOS orders and approval evidence."""
            return client.read_account_orders(account_id, limit=limit)

        @mcp.tool(annotations=GUARDED_WRITE)
        def salesforce_billing_account_flat_rate_update(
            account_id: str,
            monthly_rate_cents: int,
            idempotency_key: str,
        ) -> dict[str, Any]:
            """Set only Account.Flat_Rate_Amount__c in integer cents, skipping an existing value and reading it back."""
            return client.update_billing_account_flat_rate(
                account_id,
                monthly_rate_cents,
                idempotency_key=idempotency_key,
            )

        @mcp.tool(annotations=GUARDED_WRITE)
        def salesforce_billing_location_rate_update(
            location_id: str,
            monthly_rate_cents: int,
            idempotency_key: str,
        ) -> dict[str, Any]:
            """Set only one Salesforce location's Bill Amount in cents and verify it by readback."""
            return client.update_billing_location_rate(
                location_id,
                monthly_rate_cents,
                idempotency_key=idempotency_key,
            )

        @mcp.tool(annotations=GUARDED_WRITE)
        def salesforce_billing_account_flat_rate_clear(
            account_id: str,
            expected_current_rate_cents: int,
            idempotency_key: str,
        ) -> dict[str, Any]:
            """Clear one exact Account flat rate only when its current cents match the expectation."""
            return client.clear_billing_account_flat_rate(
                account_id,
                expected_current_rate_cents,
                idempotency_key=idempotency_key,
            )

        @mcp.tool(annotations=GUARDED_WRITE)
        def salesforce_billing_location_gateway_update(
            location_id: str,
            integrated: bool,
            idempotency_key: str,
        ) -> dict[str, Any]:
            """Set one location's Nova Integrated gateway flag and verify exact readback."""
            return client.update_billing_location_gateway(
                location_id,
                integrated,
                idempotency_key=idempotency_key,
            )

        @mcp.tool(annotations=READ)
        def salesforce_account_closure_preview(
            ticket_id: str,
            account_id: str,
            closed_nova_location_ids: list[int],
            nova_active_location_ids: list[int],
            maxio_reconciliation_evidence: dict[str, Any],
        ) -> dict[str, Any]:
            """Preview Account deactivation after exact Nova, Salesforce, Maxio, and order reconciliation."""
            return client.account_closure_preview(
                ticket_id,
                account_id,
                closed_nova_location_ids,
                nova_active_location_ids,
                maxio_reconciliation_evidence,
            )

        @mcp.tool(annotations=GUARDED_WRITE)
        def salesforce_account_closure_apply(
            ticket_id: str,
            account_id: str,
            closed_nova_location_ids: list[int],
            nova_active_location_ids: list[int],
            maxio_reconciliation_evidence: dict[str, Any],
            idempotency_key: str,
            preview_hash: str,
        ) -> dict[str, Any]:
            """Apply editable Account status and read calculated lifecycle fields back."""
            return client.apply_account_closure(
                ticket_id,
                account_id,
                closed_nova_location_ids,
                nova_active_location_ids,
                maxio_reconciliation_evidence,
                idempotency_key=idempotency_key,
                preview_hash=preview_hash,
            )

        @mcp.tool(annotations=READ)
        def salesforce_account_cancellation_order_preview(
            ticket_id: str,
            account_id: str,
            salesforce_location_ids: list[str],
            official_nova_location_ids: list[int],
            maxio_deallocation_evidence: list[dict[str, Any]],
            cancellation_reason: str,
            notes: str = "",
        ) -> dict[str, Any]:
            """Preview exact location-only deallocations as one full-account order per subscription."""
            return client.cancellation_order_preview(
                ticket_id,
                account_id,
                salesforce_location_ids,
                official_nova_location_ids,
                maxio_deallocation_evidence,
                cancellation_reason,
                notes=notes,
            )

        @mcp.tool(annotations=GUARDED_WRITE)
        def salesforce_account_cancellation_order_apply(
            ticket_id: str,
            account_id: str,
            salesforce_location_ids: list[str],
            official_nova_location_ids: list[int],
            maxio_deallocation_evidence: list[dict[str, Any]],
            cancellation_reason: str,
            idempotency_key: str,
            preview_hash: str,
            notes: str = "",
        ) -> dict[str, Any]:
            """Create one cancellation order per subscription and verify every provider disposition."""
            return client.apply_cancellation_order(
                ticket_id,
                account_id,
                salesforce_location_ids,
                official_nova_location_ids,
                maxio_deallocation_evidence,
                cancellation_reason,
                notes=notes,
                idempotency_key=idempotency_key,
                preview_hash=preview_hash,
            )

        @mcp.tool(annotations=GUARDED_WRITE)
        def salesforce_cancellation_order_reason_update(
            order_id: str,
            reason: str,
            idempotency_key: str,
        ) -> dict[str, Any]:
            """Set only the cancellation reason on one existing Cancellation Order and verify exact readback."""
            return client.update_cancellation_order_reason(
                order_id,
                reason,
                idempotency_key=idempotency_key,
            )

        @mcp.tool(annotations=GUARDED_WRITE)
        def salesforce_email_template_html_update(
            template_id: str,
            html_value: str,
            idempotency_key: str,
        ) -> dict[str, Any]:
            """Replace one curated email template's HTML body, keeping approved content, and verify exact readback."""
            return client.update_email_template_html(
                template_id,
                html_value,
                idempotency_key=idempotency_key,
            )

        @mcp.tool(annotations=READ)
        def salesforce_location_cancellation_order_preview(
            ticket_id: str,
            account_id: str,
            salesforce_location_ids: list[str],
            maxio_deallocation_evidence: list[dict[str, Any]],
            cancellation_reason: str,
            notes: str = "",
        ) -> dict[str, Any]:
            """Preview exact closed locations as one subscription-linked order per subscription."""
            return client.location_cancellation_order_preview(
                ticket_id,
                account_id,
                salesforce_location_ids,
                maxio_deallocation_evidence,
                cancellation_reason,
                notes=notes,
            )

        @mcp.tool(annotations=GUARDED_WRITE)
        def salesforce_location_cancellation_order_apply(
            ticket_id: str,
            account_id: str,
            salesforce_location_ids: list[str],
            maxio_deallocation_evidence: list[dict[str, Any]],
            cancellation_reason: str,
            idempotency_key: str,
            preview_hash: str,
            notes: str = "",
        ) -> dict[str, Any]:
            """Create one exact partial-closure order per subscription and verify every readback."""
            return client.apply_location_cancellation_order(
                ticket_id,
                account_id,
                salesforce_location_ids,
                maxio_deallocation_evidence,
                cancellation_reason,
                notes=notes,
                idempotency_key=idempotency_key,
                preview_hash=preview_hash,
            )

        @mcp.tool(annotations=GUARDED_WRITE)
        def salesforce_account_cancellation_chatter_post(
            ticket_id: str,
            account_id: str,
            cause: str = "",
            resolution: str = "",
            next_steps: str = "",
            priority_context: str = "",
            update: str = "",
        ) -> dict[str, Any]:
            """Post only a net-new useful cancellation update to the verified ticket."""
            return client.post_account_cancellation_chatter(
                ticket_id,
                account_id,
                ticket_chatter_update_body(
                    cause,
                    resolution,
                    next_steps,
                    priority_context,
                    update=update,
                ),
            )

        @mcp.tool(annotations=READ)
        def salesforce_account_cancellation_pdf_status(
            ticket_id: str,
            account_id: str,
            file_name: str,
            sha256: str,
        ) -> dict[str, Any]:
            """Preflight an exact cancellation PDF against ticket attachments without writing."""
            return client.account_cancellation_pdf_status(ticket_id, account_id, file_name, sha256)

        @mcp.tool(annotations=GUARDED_WRITE)
        def salesforce_account_cancellation_pdf_upload(
            ticket_id: str,
            account_id: str,
            file_name: str,
            content_base64: str,
            sha256: str,
            idempotency_key: str,
        ) -> dict[str, Any]:
            """Attach one verified cancellation PDF to the exact cancellation ticket and verify its digest."""
            return client.upload_account_cancellation_pdf(
                ticket_id,
                account_id,
                file_name,
                content_base64,
                sha256,
                idempotency_key=idempotency_key,
            )

        @mcp.tool(annotations=READ)
        def salesforce_account_cancellation_email_attachment_status(
            ticket_id: str,
            account_id: str,
            file_name: str,
            sha256: str,
        ) -> dict[str, Any]:
            """Check one exact customer closure-confirmation EML on a verified cross-lane ticket."""
            return client.account_cancellation_email_attachment_status(
                ticket_id,
                account_id,
                file_name,
                sha256,
            )

        @mcp.tool(annotations=GUARDED_WRITE)
        def salesforce_account_cancellation_email_attachment_upload(
            ticket_id: str,
            account_id: str,
            file_name: str,
            content_base64: str,
            sha256: str,
            idempotency_key: str,
        ) -> dict[str, Any]:
            """Attach one exact customer closure-confirmation EML with digest readback."""
            return client.upload_account_cancellation_email_attachment(
                ticket_id,
                account_id,
                file_name,
                content_base64,
                sha256,
                idempotency_key=idempotency_key,
            )

        @mcp.tool(annotations=GUARDED_WRITE)
        def salesforce_account_cancellation_confirmation_email_send(
            ticket_id: str,
            account_id: str,
        ) -> dict[str, Any]:
            """Send the fixed closure notice to the Account primary Contact and ticket-listed customer emails."""
            return client.send_account_cancellation_confirmation_email(ticket_id, account_id)

        @mcp.tool(annotations=GUARDED_WRITE)
        def salesforce_account_cancellation_finalize(
            ticket_id: str,
            account_id: str,
            feed_element_id: str = "",
            update: str = "",
        ) -> dict[str, Any]:
            """Send the fixed notice once, add only a net-new update, and close a verified cancellation ticket."""
            note = (
                ticket_chatter_update_body("", "", "", "", update=update)
                if str(update or "").strip()
                else ""
            )
            return client.finalize_account_cancellation(
                ticket_id,
                account_id,
                note,
                reply_to_feed_element_id=feed_element_id,
            )

        @mcp.tool(annotations=GUARDED_WRITE)
        def salesforce_ticket_credit_confirmation_email_send(
            ticket_id: str,
            credit_amount_cents: int,
        ) -> dict[str, Any]:
            """Send the approved credit template to the Account primary recipient and ticket-listed emails."""
            return client.send_ticket_credit_confirmation_email(
                ticket_id=ticket_id,
                credit_amount_cents=credit_amount_cents,
                allowed_record_types=ticket_record_types,
            )

        @mcp.tool(annotations=GUARDED_WRITE)
        def salesforce_ticket_refund_confirmation_email_send(
            ticket_id: str,
            refund_amount_cents: int,
        ) -> dict[str, Any]:
            """Send the approved refund template to the Account primary recipient and ticket-listed emails."""
            return client.send_ticket_refund_confirmation_email(
                ticket_id=ticket_id,
                refund_amount_cents=refund_amount_cents,
                allowed_record_types=ticket_record_types,
            )

    @mcp.tool(annotations=GUARDED_WRITE)
    def salesforce_ticket_template_email_send(
        ticket_id: str,
        situation: str,
        details: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Send one lane-owned template from its fixed support/billing address with FromAddress readback."""
        return client.send_ticket_template_email(
            ticket_id=ticket_id,
            situation=situation,
            details=details,
            lane=clean_lane,
            allowed_record_types=ticket_record_types,
        )

    if clean_lane in {"direct_codex", "tickets_agent"}:

        @mcp.tool(annotations=GUARDED_WRITE)
        def salesforce_ticket_company_credentials_email_send(
            ticket_id: str,
            requested_recipients: list[str],
        ) -> dict[str, Any]:
            """Send only ticket 347370's fixed credential template to its exact two authorized recipients."""
            return client.send_ticket_company_credentials_email(
                ticket_id=ticket_id,
                requested_recipients=requested_recipients,
                lane=clean_lane,
                allowed_record_types=ticket_record_types,
            )

    return mcp


def main() -> None:
    lane = os.getenv("SCOPED_AGENT_LANE", "").strip()
    configured_env_file = os.getenv("SALESFORCE_ENV_FILE", "").strip()
    local_default = Path(
        r"C:\Users\redma\Workworkworkworkworkwork\auto-tickets\logmein-connector\.env"
    )
    if configured_env_file:
        env_file = Path(os.path.expandvars(os.path.expanduser(configured_env_file))).resolve()
        settings = SalesforceSettings.from_env_file(env_file)
    elif local_default.is_file():
        settings = SalesforceSettings.from_env_file(local_default)
    else:
        settings = SalesforceSettings.from_environment()
    salesforce_client = ScopedSalesforceClient(settings)
    sql_settings = NovaSqlSettings(
        server=os.getenv("NOVA_SQL_SERVER", "cluster.novapointofsale.com,6682").strip(),
        driver=os.getenv("NOVA_SQL_DRIVER", "").strip(),
        api_cohort_credential_file=os.getenv("NOVA_POS_MAIN_API_COHORT_CREDENTIAL_FILE", "").strip(),
        developer_username_file=os.getenv(
            "NOVA_SQL_DEVELOPER_USERNAME_FILE", ""
        ).strip(),
        developer_password_file=os.getenv(
            "NOVA_SQL_DEVELOPER_PASSWORD_FILE", ""
        ).strip(),
    )
    write_state_dir = os.getenv("NOVA_SQL_WRITE_STATE_DIR") or None
    restore_gateway = LocalProtectedDemoRestoreGateway.from_environment()
    if lane == "coding_agent" and restore_gateway is None:
        restore_gateway = TargetScopedProtectedDemoRestoreGateway(
            write_state_dir or Path(os.getenv("LOCALAPPDATA") or ".") / "NovaSqlGuardedExecutor",
            query_timeout_seconds=sql_settings.query_timeout_seconds,
        )
    build_mcp(
        lane,
        salesforce_client,
        ScopedNovaSqlClient(
            salesforce_client,
            sql_settings,
            write_enabled=lane == "coding_agent",
            write_state_dir=write_state_dir,
            instyle_demo_restore_gateway=restore_gateway,
        ),
    ).run(transport="stdio")


if __name__ == "__main__":
    main()
