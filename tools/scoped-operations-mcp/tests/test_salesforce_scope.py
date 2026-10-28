from __future__ import annotations

# AgentChat/coding_agent 2026-08-06T16:20:00Z
# AgentChat/coding_agent 2026-08-07T12:42:00Z

# AgentChat/coding_agent 2026-08-03T23:30:00Z
# AgentChat/coding_agent 2026-08-03T22:55:08Z

# AgentChat/coding_agent 2026-07-26T00:51:47Z
# AgentChat/coding_agent 2026-07-23T20:26:28Z: verify the fixed Instyle demo rebuild.

import base64
import hashlib
import json
import time
from collections.abc import AsyncGenerator
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from threading import Barrier, Lock

import pytest
import yaml
from mcp.client.session import ClientSession
from mcp.shared.memory import create_connected_server_and_client_session

import scoped_operations_mcp.salesforce_client as salesforce_client_module
from scoped_operations_mcp.salesforce_client import (
    ACCOUNT_360_CONTACT_FIELDS,
    BILLING_ORG_WIDE_EMAIL_ADDRESS,
    BILLING_INQUIRY_ACCOUNT_PLACEHOLDER,
    BILLING_INQUIRY_LAST4_PLACEHOLDER,
    BILLING_INQUIRY_MESSAGE_PLACEHOLDER,
    CANONICAL_PENDING_EMAIL_WORKFLOWS,
    CREDENTIALS_AUTHORIZED_RECIPIENTS,
    CREDENTIALS_EXCLUDED_RECIPIENTS,
    CREDENTIALS_TEMPLATE_DEVELOPER_NAME,
    CREDENTIALS_TEMPLATE_ID,
    CREDENTIALS_TEMPLATE_NAME,
    CREDENTIALS_TEMPLATE_SUBJECT,
    CREDENTIALS_TICKET_ID,
    DARIUS_ORG_WIDE_EMAIL_ADDRESS,
    DIRECT_DARIUS_REPLY_SENDER_POLICY,
    EMAIL_TEMPLATE_CLASS_APPROVED,
    EMAIL_TEMPLATE_CLASS_BROKEN,
    EMAIL_TEMPLATE_CLASS_CONTENT_PENDING,
    EMAIL_TEMPLATE_CLASS_MISSING,
    EMAIL_TEMPLATE_CLASS_REJECTED,
    EMAIL_TEMPLATE_REGISTRY,
    LOCATION_UPDATE_FIELDS,
    ORDER_CREATE_FIELDS,
    SUPPORT_ONE_OFF_MESSAGE_PLACEHOLDER,
    SUPPORT_ONE_OFF_TEMPLATE_DEVELOPER_NAME,
    SUPPORT_ONE_OFF_TEMPLATE_NAME,
    SUPPORT_ONE_OFF_TEMPLATE_SUBJECT,
    SUPPORT_ORG_WIDE_EMAIL_ADDRESS,
    TICKET_UPDATE_FIELDS,
    ScopedSalesforceClient,
    SalesforceDefinitiveRejectionError,
    SalesforceScopeError,
    SalesforceSettings,
    SalesforceUnavailableError,
    _canonical_mailbox_list,
    _canonical_single_mailbox,
    _bounded_support_one_off_message,
    ticket_chatter_update_body,
    _validate_billing_inquiry_insert,
    _verified_ticket_additional_emails,
)
from scoped_operations_mcp.salesforce_server import (
    LANE_TICKET_READ_RECORD_TYPES,
    LANE_TICKET_RECORD_TYPES,
    build_mcp,
)


class FakeClient:
    @staticmethod
    def capability_status():
        return {"ok": True, "accessMode": "typed_operations_only"}

    def __getattr__(self, name):
        return lambda *args, **kwargs: {"ok": True, "operation": name}


class RecordingTicketCreateClient(FakeClient):
    def __init__(self):
        self.create_calls = []

    def create_support_email_ticket(self, **kwargs):
        self.create_calls.append(kwargs)
        return {
            "ok": True,
            "created": True,
            "verified": True,
            "ticketId": "a0G000000000001AAA",
            "ticketNumber": "347314",
            "accountId": kwargs["account_id"],
            "accountEligible": True,
            "recordTypeId": kwargs["record_type_id"],
            "recordType": "1. NOVA Classic",
            "sourceEmailId": kwargs["source_email_id"],
            "sourceKey": kwargs["source_key"],
            "ticketCreatedBy": kwargs["ticket_created_by"],
            "isClosed": False,
        }

    def create_billing_closure_email_ticket(self, **kwargs):
        self.create_calls.append(kwargs)
        return {
            "ok": True,
            "created": True,
            "verified": True,
            "ticketId": "a0G000000000002AAA",
            "ticketNumber": "347500",
            "accountId": kwargs["account_id"],
            "accountEligible": True,
            "recordType": "3. Billing",
            "sourceEmailId": kwargs["source_email_id"],
            "sourceKey": kwargs["source_key"],
            "ticketCreatedBy": kwargs["ticket_created_by"],
            "isClosed": False,
        }


class BoardFakeClient(FakeClient):
    @staticmethod
    def list_open_tickets(*, limit=500):
        return {
            "ok": True,
            "records": [
                {"Id": "a0G000000000001", "Name": "1", "RecordType": {"Name": "1. NOVA Classic"}},
                {"Id": "a0G000000000002", "Name": "2", "RecordType": {"Name": "3. Billing"}},
            ],
            "count": 2,
            "rowCeiling": limit,
        }


class FakeNovaSqlClient:
    @staticmethod
    def capability_status():
        return {"ok": True, "accessMode": "bounded_read_only"}

    def preflight(self, company_username):
        return {"ok": True, "companyUsername": company_username}

    def billing_locations(self, company_username):
        return {
            "ok": True,
            "companyUsername": company_username,
            "activeNonStorageLocationIds": [],
        }

    def read(self, company_username, sql, parameters=None, *, max_rows=100):
        return {"ok": True, "companyUsername": company_username, "rowCount": 0}

    def api_customer_email_cohort(self):
        return {"ok": True, "verified": True, "recipientCount": 0, "emailSent": False}

    def data_move_read(self, **kwargs):
        return {
            "ok": True,
            "targetCompanyUsername": kwargs["target_company_username"],
            "sourceCompanyUsernames": kwargs["source_company_usernames"],
            "rowCount": 0,
        }

    def preview_write(self, **kwargs):
        return {"ok": True, "status": "preview", "companyUsername": kwargs["company_username"]}

    def execute_guarded_write(self, **kwargs):
        return {"ok": True, "status": "completed", "companyUsername": kwargs["company_username"]}

    def preview_ticket_347534_invoice_repair(self, **kwargs):
        return {"ok": True, "status": "preview", **kwargs}

    def status_ticket_347534_invoice_repair(self, **kwargs):
        return {"ok": True, "status": "previewed", **kwargs}

    def execute_ticket_347534_invoice_repair(self, **kwargs):
        return {"ok": True, "status": "completed", **kwargs}

    def update_location_region(self, **kwargs):
        return {"ok": True, "status": "completed", **kwargs}

    def update_location_reactivation(self, **kwargs):
        return {"ok": True, "status": "completed", **kwargs}

    def enable_location_layaways(self, **kwargs):
        return {"ok": True, "status": "completed", **kwargs}

    def preview_locations_feature_columns_migration(self, **kwargs):
        return {"ok": True, "status": "preview", "companyUsername": kwargs["company_username"]}

    def execute_locations_feature_columns_migration(self, **kwargs):
        return {"ok": True, "status": "completed", "companyUsername": kwargs["company_username"]}

    def preview_kit_upgrade(self, **kwargs):
        return {"ok": True, "status": "preview", "fixedSchemaContract": True, **kwargs}

    def execute_kit_upgrade(self, **kwargs):
        return {"ok": True, "status": "completed", "fixedSchemaContract": True, **kwargs}

    def preview_table_restore(self, **kwargs):
        return {
            "ok": True,
            "status": "preview",
            "companyUsername": kwargs["company_username"],
            "table": f"{kwargs['schema_name']}.{kwargs['table_name']}",
        }

    def execute_table_restore(self, **kwargs):
        return {
            "ok": True,
            "status": "completed",
            "companyUsername": kwargs["company_username"],
            "table": f"{kwargs['schema_name']}.{kwargs['table_name']}",
        }

    def preview_instyle_demo_sync(self, **kwargs):
        return {
            "ok": True,
            "status": "preview",
            "operation": "nova_sql_instyle_demo_sync_preview",
            "idempotencyKey": kwargs["idempotency_key"],
        }

    def status_instyle_demo_sync(self, **kwargs):
        return {
            "ok": True,
            "status": "reconciled",
            "operation": "nova_sql_instyle_demo_sync_status",
            "idempotencyKey": kwargs["idempotency_key"],
        }

    def execute_instyle_demo_sync(self, **kwargs):
        return {
            "ok": True,
            "status": "completed",
            "operation": "nova_sql_instyle_demo_sync_execute",
            "idempotencyKey": kwargs["idempotency_key"],
        }


class FakeNovaApiClient:
    @staticmethod
    def capability_status():
        return {"ok": True, "accessMode": "typed_read_only", "writeExposed": False}

    @staticmethod
    def health():
        return {"ok": True, "statusCode": 200}

    def __getattr__(self, name):
        return lambda *args, **kwargs: {"ok": True, "operation": name}


@pytest.fixture
def anyio_backend():
    return "asyncio"


def test_salesforce_settings_can_be_supplied_by_an_isolated_broker_environment(monkeypatch) -> None:
    monkeypatch.setenv("SALESFORCE_INSTANCE_URL", "https://example.my.salesforce.com")
    monkeypatch.setenv("SALESFORCE_LOGIN_URL", "https://login.salesforce.com")
    monkeypatch.setenv("SALESFORCE_CLIENT_ID", "client-id")
    monkeypatch.setenv("SALESFORCE_CLIENT_SECRET", "client-secret")
    monkeypatch.setenv("SALESFORCE_USE_CLIENT_CREDENTIALS", "true")

    settings = SalesforceSettings.from_environment()

    assert settings.instance_url == "https://example.my.salesforce.com"
    assert settings.login_url == "https://login.salesforce.com"
    assert settings.client_id == "client-id"
    assert settings.client_secret == "client-secret"
    assert settings.use_client_credentials is True


@pytest.fixture
async def client_session() -> AsyncGenerator[ClientSession]:
    async with create_connected_server_and_client_session(
        build_mcp("tickets_agent", FakeClient(), FakeNovaSqlClient(), FakeNovaApiClient()),
        raise_exceptions=True,
    ) as session:
        yield session


@pytest.fixture
async def coding_client_session() -> AsyncGenerator[ClientSession]:
    async with create_connected_server_and_client_session(
        build_mcp("coding_agent", FakeClient(), FakeNovaSqlClient(), FakeNovaApiClient()),
        raise_exceptions=True,
    ) as session:
        yield session


@pytest.fixture
async def billing_client_session() -> AsyncGenerator[ClientSession]:
    async with create_connected_server_and_client_session(
        build_mcp("billing_agent", FakeClient(), FakeNovaSqlClient(), FakeNovaApiClient()),
        raise_exceptions=True,
    ) as session:
        yield session


@pytest.mark.anyio
async def test_server_exposes_only_typed_business_operations(client_session):
    response = await client_session.list_tools()
    names = {tool.name for tool in response.tools}
    tools = {tool.name: tool for tool in response.tools}

    assert names == {
        "salesforce_capabilities",
        "salesforce_explain_limitation",
        "salesforce_lookup",
        "salesforce_account_360_read",
        "salesforce_ticket_list_open",
        "salesforce_weekly_ticket_totals",
        "salesforce_ticket_read",
        "salesforce_ticket_feed_read",
        "salesforce_ticket_email_log_read",
        "salesforce_email_sender_preflight",
        "salesforce_email_template_inventory",
        "salesforce_ticket_template_email_preview",
        "salesforce_ticket_company_credentials_email_preview",
        "salesforce_ticket_create",
        "salesforce_ticket_update",
        "salesforce_ticket_internal_note_update",
        "salesforce_ticket_chatter_post",
        "salesforce_ticket_chatter_reply",
        "salesforce_ticket_internal_request_post",
        "salesforce_ticket_resolve",
        "salesforce_ticket_contact_email_update",
        "salesforce_ticket_attachment_status",
        "salesforce_ticket_attachment_upload",
        "salesforce_ticket_pdf_status",
        "salesforce_ticket_pdf_upload",
        "salesforce_ticket_template_email_send",
        "salesforce_ticket_company_credentials_email_send",
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
    }
    internal_request_schema = tools[
        "salesforce_ticket_internal_request_post"
    ].inputSchema
    assert set(internal_request_schema["properties"]) == {
        "ticket_id",
        "exact_user",
        "message",
        "idempotency_key",
    }
    assert set(internal_request_schema["required"]) == {
        "ticket_id",
        "exact_user",
        "message",
        "idempotency_key",
    }
    assert "source_key" not in tools[
        "salesforce_ticket_create"
    ].inputSchema["properties"]
    assert "first_message_today" not in internal_request_schema["properties"]
    forbidden = ("delete", "metadata", "tooling", "apex", "flow", "workflow", "permission", "setup", "soql", "rest")
    assert not any(marker in name.lower() for name in names for marker in forbidden)


@pytest.mark.anyio
async def test_salesforce_write_tools_are_split_by_lane(
    client_session,
    billing_client_session,
    coding_client_session,
):
    support = {tool.name for tool in (await client_session.list_tools()).tools}
    billing = {tool.name for tool in (await billing_client_session.list_tools()).tools}
    coding = {tool.name for tool in (await coding_client_session.list_tools()).tools}

    assert "salesforce_ticket_create" in support
    assert "salesforce_ticket_create" in billing
    assert "salesforce_ticket_create" not in coding
    assert "salesforce_support_email_ticket_create" in coding
    assert "salesforce_support_email_ticket_create" not in support
    assert "salesforce_support_email_ticket_create" not in billing
    assert "salesforce_order_create" not in support
    assert "salesforce_location_update" not in support
    assert "salesforce_billing_account_read" not in support
    assert "salesforce_billing_account_flat_rate_update" not in support
    assert "salesforce_account_cancellation_order_apply" not in support
    assert "salesforce_order_create" not in billing
    assert "salesforce_location_update" not in billing
    assert "salesforce_billing_account_read" in billing
    assert "salesforce_billing_account_flat_rate_update" in billing
    assert "salesforce_billing_account_locations_read" in billing
    assert "salesforce_billing_account_orders_read" in billing
    assert "salesforce_billing_location_rate_update" in billing
    assert "salesforce_billing_account_flat_rate_clear" in billing
    assert "salesforce_billing_location_gateway_update" in billing
    assert "salesforce_billing_account_flat_rate_clear" not in coding
    assert "salesforce_billing_location_gateway_update" not in coding
    assert "salesforce_billing_account_flat_rate_clear" not in support
    assert "salesforce_billing_location_gateway_update" not in support
    assert "salesforce_account_closure_preview" in billing
    assert "salesforce_account_closure_apply" in billing
    assert "salesforce_account_cancellation_order_preview" in billing
    assert "salesforce_account_cancellation_order_apply" in billing
    assert "salesforce_location_cancellation_order_preview" in billing
    assert "salesforce_location_cancellation_order_apply" in billing
    assert "salesforce_cancellation_order_reason_update" in billing
    assert "salesforce_cancellation_order_reason_update" not in support
    assert "salesforce_cancellation_order_reason_update" not in coding
    assert "salesforce_email_template_html_update" in billing
    assert "salesforce_email_template_html_update" not in support
    assert "salesforce_email_template_html_update" not in coding
    assert "salesforce_location_lifecycle_order_preview" in billing
    assert "salesforce_location_lifecycle_order_apply" in billing
    assert "salesforce_reactivation_order_approval_preview" not in billing
    assert "salesforce_reactivation_order_approval_apply" not in billing
    assert "salesforce_account_cancellation_chatter_post" in billing
    assert "salesforce_account_cancellation_pdf_status" in billing
    assert "salesforce_account_cancellation_pdf_upload" in billing
    assert "salesforce_billing_closure_email_ticket_create" in billing
    assert "salesforce_account_cancellation_email_attachment_status" in billing
    assert "salesforce_account_cancellation_email_attachment_upload" in billing
    assert "salesforce_account_cancellation_confirmation_email_send" in billing
    assert "salesforce_account_cancellation_finalize" in billing
    assert "salesforce_ticket_credit_confirmation_email_send" in billing
    assert "salesforce_ticket_refund_confirmation_email_send" in billing
    assert "salesforce_ticket_credit_confirmation_email_send" not in support
    assert "salesforce_ticket_credit_confirmation_email_send" not in coding
    assert "salesforce_ticket_refund_confirmation_email_send" not in support
    assert "salesforce_ticket_refund_confirmation_email_send" not in coding
    assert "salesforce_order_create" not in coding
    assert "salesforce_location_update" not in coding
    for name in (
        "salesforce_billing_account_read",
        "salesforce_billing_account_locations_read",
        "salesforce_billing_account_orders_read",
        "salesforce_billing_account_flat_rate_update",
        "salesforce_billing_location_rate_update",
        "salesforce_billing_structure_read",
        "salesforce_billing_schedule_date_preview",
        "salesforce_billing_schedule_date_apply",
        "salesforce_billing_structure_alignment_preview",
        "salesforce_billing_structure_alignment_apply",
        "salesforce_billing_location_alignment_preview",
        "salesforce_billing_location_alignment_apply",
        "salesforce_account_fake_classification_preview",
        "salesforce_account_fake_classification_apply",
    ):
        assert name in billing
        assert name in coding
        assert name not in support
    assert "salesforce_account_cancellation_order_apply" not in coding
    assert "salesforce_location_cancellation_order_preview" not in coding
    assert "salesforce_location_cancellation_order_apply" not in coding
    assert "salesforce_location_lifecycle_order_preview" in coding
    assert "salesforce_location_lifecycle_order_apply" in coding
    assert "salesforce_reactivation_order_approval_preview" not in coding
    assert "salesforce_reactivation_order_approval_apply" not in coding
    assert "salesforce_account_cancellation_pdf_status" not in coding
    assert "salesforce_billing_closure_email_ticket_create" not in support
    assert "salesforce_billing_closure_email_ticket_create" not in coding
    assert "salesforce_account_cancellation_email_attachment_status" not in support
    assert "salesforce_account_cancellation_email_attachment_status" not in coding
    assert "salesforce_account_cancellation_email_attachment_upload" not in support
    assert "salesforce_account_cancellation_email_attachment_upload" not in coding
    assert "salesforce_account_cancellation_confirmation_email_send" not in support
    assert "salesforce_account_cancellation_confirmation_email_send" not in coding
    assert "salesforce_account_cancellation_finalize" not in support
    assert "salesforce_account_cancellation_finalize" not in coding
    assert "salesforce_ticket_chatter_post" in support
    assert "salesforce_ticket_chatter_post" in billing
    assert "salesforce_ticket_chatter_post" in coding
    assert "salesforce_ticket_chatter_reply" in support
    assert "salesforce_ticket_chatter_reply" in billing
    assert "salesforce_ticket_chatter_reply" in coding
    assert "salesforce_ticket_internal_request_post" in support
    assert "salesforce_ticket_internal_request_post" in billing
    assert "salesforce_ticket_internal_request_post" in coding
    assert "salesforce_location_lifecycle_order_apply" not in support
    for name in (
        "salesforce_ticket_contact_email_update",
        "salesforce_ticket_attachment_status",
        "salesforce_ticket_attachment_upload",
        "salesforce_ticket_pdf_status",
        "salesforce_ticket_pdf_upload",
    ):
        assert name in support
        assert name in billing
        assert name in coding


@pytest.mark.anyio
async def test_taylor_ticket_create_is_only_source_keyed_classic_wave_with_readback(
    monkeypatch,
):
    monkeypatch.setenv(
        "SALESFORCE_SUPPORT_EMAIL_TICKET_CREATED_BY",
        "Darius Parlor",
    )
    salesforce = RecordingTicketCreateClient()
    async with create_connected_server_and_client_session(
        build_mcp(
            "coding_agent",
            salesforce,
            FakeNovaSqlClient(),
            FakeNovaApiClient(),
        ),
        raise_exceptions=True,
    ) as session:
        tools = {tool.name: tool for tool in (await session.list_tools()).tools}
        response = await session.call_tool(
            "salesforce_support_email_ticket_create",
            {
                "account_id": "001000000000001AAA",
                "description": "Register will not complete a sale.",
                "source_email_id": "message-1",
                "source_key": "support-email:message-1",
                "record_type_id": "012000000000001AAA",
                "main_issue": "Software",
                "technical_issue": "Other",
            },
        )

    assert response.isError is False
    assert response.structuredContent["created"] is True
    assert response.structuredContent["ticketId"] == "a0G000000000001AAA"
    assert response.structuredContent["ticketCreatedBy"] == "Darius Parlor"
    assert response.structuredContent["accountEligible"] is True
    assert salesforce.create_calls == [
        {
            "account_id": "001000000000001AAA",
            "description": "Register will not complete a sale.",
            "source_email_id": "message-1",
            "source_key": "support-email:message-1",
            "contact_id": "",
            "location_id": "",
            "record_type_id": "012000000000001AAA",
            "main_issue": "Software",
            "technical_issue": "Other",
            "customer_contact_method": "",
            "ticket_created_by": "Darius Parlor",
            "allowed_record_types": frozenset(
                {"1. NOVA Classic", "2. Nova Wave"}
            ),
        }
    ]
    assert set(
        tools["salesforce_support_email_ticket_create"].inputSchema["properties"]
    ) == {
        "account_id",
        "description",
        "source_email_id",
        "source_key",
        "contact_id",
        "location_id",
        "record_type_id",
        "main_issue",
        "technical_issue",
        "customer_contact_method",
    }
    assert "salesforce_ticket_create" not in tools
    coding_salesforce_tools = {
        name for name in tools if name.startswith("salesforce_")
    }
    assert "salesforce_order_create" not in coding_salesforce_tools
    assert "salesforce_location_update" not in coding_salesforce_tools
    assert not any(
        marker in name
        for name in coding_salesforce_tools
        for marker in ("admin", "metadata", "soql", "rest", "apex", "flow")
    )
    assert LANE_TICKET_RECORD_TYPES["coding_agent"] == frozenset(
        {"1. NOVA Classic", "2. Nova Wave"}
    )
    assert LANE_TICKET_RECORD_TYPES["billing_agent"] == frozenset({"3. Billing"})


@pytest.mark.anyio
async def test_jamie_billing_closure_email_create_owns_record_type_and_source_key(
    monkeypatch,
):
    monkeypatch.setenv(
        "SALESFORCE_SUPPORT_EMAIL_TICKET_CREATED_BY",
        "Darius Parlor",
    )
    salesforce = RecordingTicketCreateClient()
    async with create_connected_server_and_client_session(
        build_mcp(
            "billing_agent",
            salesforce,
            FakeNovaSqlClient(),
            FakeNovaApiClient(),
        ),
        raise_exceptions=True,
    ) as session:
        tools = {tool.name: tool for tool in (await session.list_tools()).tools}
        response = await session.call_tool(
            "salesforce_billing_closure_email_ticket_create",
            {
                "account_id": "001000000000001AAA",
                "description": "Customer requested one location cancellation.",
                "source_email_id": "message-1",
                "source_key": "billing-closure-email:message-1",
                "location_id": "a0L000000000001AAA",
                "customer_contact_method": "Email",
            },
        )

    assert response.isError is False
    assert response.structuredContent["recordType"] == "3. Billing"
    assert response.structuredContent["sourceKey"] == (
        "billing-closure-email:message-1"
    )
    assert salesforce.create_calls == [
        {
            "account_id": "001000000000001AAA",
            "description": "Customer requested one location cancellation.",
            "source_email_id": "message-1",
            "source_key": "billing-closure-email:message-1",
            "contact_id": "",
            "location_id": "a0L000000000001AAA",
            "main_issue": "",
            "technical_issue": "",
            "customer_contact_method": "Email",
            "ticket_created_by": "Darius Parlor",
            "allowed_record_types": frozenset({"3. Billing"}),
        }
    ]
    schema = tools[
        "salesforce_billing_closure_email_ticket_create"
    ].inputSchema
    assert "record_type_id" not in schema["properties"]


@pytest.mark.anyio
async def test_ticket_create_capability_contract_matches_specialist_lane_inventory(
    client_session,
    billing_client_session,
    coding_client_session,
):
    contract_path = (
        Path(__file__).resolve().parents[3] / "config" / "agent-capabilities.yaml"
    )
    contract = yaml.safe_load(contract_path.read_text(encoding="utf-8"))
    sessions = {
        "tickets_agent": client_session,
        "billing_agent": billing_client_session,
        "coding_agent": coding_client_session,
    }
    generic_actual_lanes = {
        lane
        for lane, session in sessions.items()
        if "salesforce_ticket_create"
        in {tool.name for tool in (await session.list_tools()).tools}
    }
    generic_declared_lanes = {
        lane
        for lane in sessions
        if "salesforce.ticket.create"
        in set(contract["lanes"][lane]["operations"])
    }
    dedicated_actual_lanes = {
        lane
        for lane, session in sessions.items()
        if "salesforce_support_email_ticket_create"
        in {tool.name for tool in (await session.list_tools()).tools}
    }
    dedicated_declared_lanes = {
        lane
        for lane in sessions
        if "salesforce.support_email_ticket.create_verified"
        in set(contract["lanes"][lane]["operations"])
    }

    assert generic_actual_lanes == generic_declared_lanes == {
        "tickets_agent",
        "billing_agent",
    }
    assert dedicated_actual_lanes == dedicated_declared_lanes == {"coding_agent"}


@pytest.mark.anyio
async def test_billing_confirmation_capability_contract_matches_actual_mcp_inventory(
    client_session,
    billing_client_session,
    coding_client_session,
):
    contract_path = (
        Path(__file__).resolve().parents[3] / "config" / "agent-capabilities.yaml"
    )
    contract = yaml.safe_load(contract_path.read_text(encoding="utf-8"))
    actual_tools_by_lane = {
        "tickets_agent": {
            tool.name for tool in (await client_session.list_tools()).tools
        },
        "billing_agent": {
            tool.name for tool in (await billing_client_session.list_tools()).tools
        },
        "coding_agent": {
            tool.name for tool in (await coding_client_session.list_tools()).tools
        },
    }

    semantic_to_mcp_tool = {
        "salesforce.ticket_email.send_credit_confirmation_template": (
            "salesforce_ticket_credit_confirmation_email_send"
        ),
        "salesforce.ticket_email.send_refund_confirmation_template": (
            "salesforce_ticket_refund_confirmation_email_send"
        ),
        "salesforce.billing_closure_email_ticket.create_verified": (
            "salesforce_billing_closure_email_ticket_create"
        ),
        "salesforce.account_cancellation_email_attachment.status_read": (
            "salesforce_account_cancellation_email_attachment_status"
        ),
        "salesforce.account_cancellation_email_attachment.upload_verified": (
            "salesforce_account_cancellation_email_attachment_upload"
        ),
    }
    for semantic_operation, mcp_tool in semantic_to_mcp_tool.items():
        declared_lanes = {
            lane_name
            for lane_name in actual_tools_by_lane
            if semantic_operation in set(contract["lanes"][lane_name]["operations"])
        }
        actual_lanes = {
            lane_name
            for lane_name, tool_names in actual_tools_by_lane.items()
            if mcp_tool in tool_names
        }

        assert declared_lanes == actual_lanes == {"billing_agent"}


@pytest.mark.anyio
async def test_nova_sql_tools_are_read_only_bounded_operations(client_session):
    response = await client_session.list_tools()
    tools = {tool.name: tool for tool in response.tools}

    assert tools["nova_sql_capabilities"].annotations.readOnlyHint is True
    assert tools["nova_sql_preflight"].annotations.readOnlyHint is True
    assert tools["nova_billing_locations_read"].annotations.readOnlyHint is True
    assert set(tools["nova_billing_locations_read"].inputSchema["properties"]) == {
        "company_username"
    }
    assert tools["nova_sql_invoice_spare_investigation"].annotations.readOnlyHint is True
    assert set(
        tools["nova_sql_invoice_spare_investigation"].inputSchema["properties"]
    ) == {"company_username", "invoice_id"}
    assert tools["nova_sql_read"].annotations.readOnlyHint is True
    assert set(tools["nova_sql_read"].inputSchema["properties"]) == {
        "company_username",
        "sql",
        "parameters",
        "max_rows",
    }


@pytest.mark.anyio
async def test_nova_api_tools_are_typed_read_only_and_have_no_mutation_surface(client_session):
    tools = {tool.name: tool for tool in (await client_session.list_tools()).tools}
    api_tools = {name: tool for name, tool in tools.items() if name.startswith("nova_api_")}

    assert api_tools
    assert all(tool.annotations.readOnlyHint is True for tool in api_tools.values())
    assert not any(
        marker in name
        for name in api_tools
        for marker in ("create", "update", "delete", "adjust", "checkin", "checkout")
    )
    assert set(tools["nova_api_preflight"].inputSchema["properties"]) == {"company_username"}


@pytest.mark.anyio
async def test_guarded_sql_write_tools_are_exposed_only_to_taylor(
    coding_client_session,
    client_session,
    billing_client_session,
):
    coding_tools = {tool.name: tool for tool in (await coding_client_session.list_tools()).tools}
    support_names = {tool.name for tool in (await client_session.list_tools()).tools}
    billing_names = {tool.name for tool in (await billing_client_session.list_tools()).tools}

    assert "nova_sql_write_preview" in coding_tools
    assert "nova_sql_execute_guarded" in coding_tools
    assert "nova_sql_account_copy_preview" in coding_tools
    assert "nova_sql_account_copy_status" in coding_tools
    assert "nova_sql_account_copy_execute" in coding_tools
    assert "nova_sql_ticket_347534_invoice_repair_preview" in coding_tools
    assert "nova_sql_ticket_347534_invoice_repair_status" in coding_tools
    assert "nova_sql_ticket_347534_invoice_repair_execute" in coding_tools
    assert "nova_sql_location_region_update" in coding_tools
    assert "nova_sql_location_reactivation_update" in coding_tools
    assert "nova_sql_location_layaway_enable" in coding_tools
    assert "nova_sql_data_move_read" in coding_tools
    assert "nova_sql_locations_feature_columns_preview" in coding_tools
    assert "nova_sql_locations_feature_columns_execute" in coding_tools
    assert "nova_sql_kit_upgrade_preview" in coding_tools
    assert "nova_sql_kit_upgrade_execute" in coding_tools
    assert "nova_sql_table_restore_preview" in coding_tools
    assert "nova_sql_table_restore_execute" in coding_tools
    assert "nova_sql_instyle_demo_sync_preview" in coding_tools
    assert "nova_sql_instyle_demo_sync_status" in coding_tools
    assert "nova_sql_instyle_demo_sync_execute" in coding_tools
    assert "nova_sql_oklahoma_hawaii_catalog_replace_preview" in coding_tools
    assert "nova_sql_oklahoma_hawaii_catalog_replace_status" in coding_tools
    assert "nova_sql_oklahoma_hawaii_catalog_replace_execute" in coding_tools
    assert coding_tools["nova_sql_write_preview"].annotations.readOnlyHint is True
    assert coding_tools["nova_sql_data_move_read"].annotations.readOnlyHint is True
    assert coding_tools["nova_sql_execute_guarded"].annotations.readOnlyHint is False
    assert coding_tools["nova_sql_execute_guarded"].annotations.idempotentHint is True
    account_copy_preview = coding_tools["nova_sql_account_copy_preview"]
    account_copy_status = coding_tools["nova_sql_account_copy_status"]
    account_copy_execute = coding_tools["nova_sql_account_copy_execute"]
    assert account_copy_preview.annotations.readOnlyHint is True
    assert account_copy_status.annotations.readOnlyHint is True
    assert account_copy_execute.annotations.readOnlyHint is False
    assert account_copy_execute.annotations.idempotentHint is True
    assert set(account_copy_preview.inputSchema["properties"]) == {
        "source_company_username",
        "target_company_username",
        "tables",
        "idempotency_key",
        "ticket_number",
    }
    assert set(account_copy_execute.inputSchema["properties"]) == {"plan_id"}
    assert "sql" not in account_copy_preview.inputSchema["properties"]
    assert "sql" not in account_copy_execute.inputSchema["properties"]
    ticket_repair_preview = coding_tools["nova_sql_ticket_347534_invoice_repair_preview"]
    ticket_repair_execute = coding_tools["nova_sql_ticket_347534_invoice_repair_execute"]
    assert ticket_repair_preview.annotations.readOnlyHint is True
    assert ticket_repair_execute.annotations.readOnlyHint is False
    assert ticket_repair_execute.annotations.idempotentHint is True
    assert set(ticket_repair_preview.inputSchema["properties"]) == {"idempotency_key"}
    assert set(ticket_repair_execute.inputSchema["properties"]) == {
        "idempotency_key",
        "preview_hash",
    }
    location_region = coding_tools["nova_sql_location_region_update"]
    assert location_region.annotations.readOnlyHint is False
    assert location_region.annotations.idempotentHint is True
    assert set(location_region.inputSchema["properties"]) == {
        "company_username",
        "location_id",
        "region_id",
        "idempotency_key",
    }
    assert "sql" not in location_region.inputSchema["properties"]
    location_reactivation = coding_tools["nova_sql_location_reactivation_update"]
    assert location_reactivation.annotations.readOnlyHint is False
    assert location_reactivation.annotations.idempotentHint is True
    assert set(location_reactivation.inputSchema["properties"]) == {
        "company_username",
        "location_id",
        "idempotency_key",
    }
    assert "sql" not in location_reactivation.inputSchema["properties"]
    location_layaway = coding_tools["nova_sql_location_layaway_enable"]
    assert location_layaway.annotations.readOnlyHint is False
    assert location_layaway.annotations.idempotentHint is True
    assert set(location_layaway.inputSchema["properties"]) == {
        "company_username",
        "location_ids",
        "idempotency_key",
    }
    assert "sql" not in location_layaway.inputSchema["properties"]
    assert "expiration_day" not in location_layaway.inputSchema["properties"]
    assert "disclaimer" not in location_layaway.inputSchema["properties"]
    assert "preview_hash" in coding_tools["nova_sql_execute_guarded"].inputSchema["properties"]
    assert (
        "source_company_usernames"
        in coding_tools["nova_sql_write_preview"].inputSchema["properties"]
    )
    assert (
        "source_company_usernames"
        in coding_tools["nova_sql_execute_guarded"].inputSchema["properties"]
    )
    fixed_preview = coding_tools["nova_sql_locations_feature_columns_preview"]
    fixed_execute = coding_tools["nova_sql_locations_feature_columns_execute"]
    assert fixed_preview.annotations.readOnlyHint is True
    assert fixed_execute.annotations.readOnlyHint is False
    assert fixed_execute.annotations.idempotentHint is True
    assert set(fixed_preview.inputSchema["properties"]) == {"company_username", "idempotency_key"}
    assert set(fixed_execute.inputSchema["properties"]) == {
        "company_username",
        "idempotency_key",
        "preview_hash",
    }
    assert "sql" not in fixed_preview.inputSchema["properties"]
    assert "sql" not in fixed_execute.inputSchema["properties"]
    kit_preview = coding_tools["nova_sql_kit_upgrade_preview"]
    kit_execute = coding_tools["nova_sql_kit_upgrade_execute"]
    assert kit_preview.annotations.readOnlyHint is True
    assert kit_execute.annotations.readOnlyHint is False
    assert kit_execute.annotations.idempotentHint is True
    assert set(kit_preview.inputSchema["properties"]) == {"company_username", "idempotency_key"}
    assert set(kit_execute.inputSchema["properties"]) == {
        "company_username",
        "idempotency_key",
        "preview_hash",
    }
    assert not {"sql", "database", "table", "columns", "types"} & set(
        kit_execute.inputSchema["properties"]
    )
    restore_preview = coding_tools["nova_sql_table_restore_preview"]
    restore_execute = coding_tools["nova_sql_table_restore_execute"]
    assert restore_preview.annotations.readOnlyHint is True
    assert restore_execute.annotations.readOnlyHint is False
    assert restore_execute.annotations.idempotentHint is True
    assert set(restore_preview.inputSchema["properties"]) == {
        "company_username",
        "schema_name",
        "table_name",
        "key_columns",
        "restore_columns",
        "idempotency_key",
    }
    assert set(restore_execute.inputSchema["properties"]) == {
        "company_username",
        "schema_name",
        "table_name",
        "key_columns",
        "restore_columns",
        "idempotency_key",
        "preview_hash",
    }
    assert "sql" not in restore_preview.inputSchema["properties"]
    assert "sql" not in restore_execute.inputSchema["properties"]
    rebuild_preview = coding_tools["nova_sql_instyle_demo_sync_preview"]
    rebuild_status = coding_tools["nova_sql_instyle_demo_sync_status"]
    rebuild_execute = coding_tools["nova_sql_instyle_demo_sync_execute"]
    assert rebuild_preview.annotations.readOnlyHint is True
    assert rebuild_status.annotations.readOnlyHint is True
    assert rebuild_execute.annotations.readOnlyHint is False
    assert rebuild_execute.annotations.idempotentHint is True
    assert set(rebuild_preview.inputSchema["properties"]) == {"idempotency_key"}
    assert set(rebuild_status.inputSchema["properties"]) == {"idempotency_key"}
    assert set(rebuild_execute.inputSchema["properties"]) == {
        "idempotency_key",
        "preview_hash",
    }
    assert not {
        "sql",
        "company_username",
        "source",
        "target",
        "database",
        "table",
    } & set(rebuild_preview.inputSchema["properties"])
    assert not {
        "sql",
        "company_username",
        "source",
        "target",
        "database",
        "table",
    } & set(rebuild_execute.inputSchema["properties"])
    catalog_preview = coding_tools["nova_sql_oklahoma_hawaii_catalog_replace_preview"]
    catalog_status = coding_tools["nova_sql_oklahoma_hawaii_catalog_replace_status"]
    catalog_execute = coding_tools["nova_sql_oklahoma_hawaii_catalog_replace_execute"]
    assert catalog_preview.annotations.readOnlyHint is True
    assert catalog_status.annotations.readOnlyHint is True
    assert catalog_execute.annotations.readOnlyHint is False
    assert catalog_execute.annotations.destructiveHint is True
    assert catalog_execute.annotations.idempotentHint is True
    assert set(catalog_preview.inputSchema["properties"]) == {"idempotency_key"}
    assert set(catalog_status.inputSchema["properties"]) == {"idempotency_key"}
    assert set(catalog_execute.inputSchema["properties"]) == {
        "idempotency_key",
        "preview_hash",
    }
    assert not {
        "sql",
        "company_username",
        "source",
        "target",
        "database",
        "category",
        "table",
        "mapping",
        "row",
    } & set(catalog_execute.inputSchema["properties"])
    assert "nova_sql_write_preview" not in support_names
    assert "nova_sql_execute_guarded" not in support_names
    assert "nova_sql_account_copy_preview" not in support_names
    assert "nova_sql_account_copy_status" not in support_names
    assert "nova_sql_account_copy_execute" not in support_names
    assert "nova_sql_location_region_update" not in support_names
    assert "nova_sql_location_reactivation_update" not in support_names
    assert "nova_sql_location_layaway_enable" not in support_names
    assert "nova_sql_data_move_read" not in support_names
    assert "nova_sql_locations_feature_columns_preview" not in support_names
    assert "nova_sql_locations_feature_columns_execute" not in support_names
    assert "nova_sql_kit_upgrade_preview" not in support_names
    assert "nova_sql_kit_upgrade_execute" not in support_names
    assert "nova_sql_table_restore_preview" not in support_names
    assert "nova_sql_table_restore_execute" not in support_names
    assert "nova_sql_instyle_demo_sync_preview" not in support_names
    assert "nova_sql_instyle_demo_sync_status" not in support_names
    assert "nova_sql_instyle_demo_sync_execute" not in support_names
    assert "nova_sql_oklahoma_hawaii_catalog_replace_preview" not in support_names
    assert "nova_sql_oklahoma_hawaii_catalog_replace_status" not in support_names
    assert "nova_sql_oklahoma_hawaii_catalog_replace_execute" not in support_names
    assert "nova_sql_instyle_demo_sync_preview" not in billing_names
    assert "nova_sql_instyle_demo_sync_status" not in billing_names
    assert "nova_sql_instyle_demo_sync_execute" not in billing_names
    assert "nova_sql_oklahoma_hawaii_catalog_replace_preview" not in billing_names
    assert "nova_sql_oklahoma_hawaii_catalog_replace_status" not in billing_names
    assert "nova_sql_oklahoma_hawaii_catalog_replace_execute" not in billing_names
    assert "nova_sql_table_restore_preview" not in billing_names
    assert "nova_sql_table_restore_execute" not in billing_names
    assert "nova_sql_kit_upgrade_preview" not in billing_names
    assert "nova_sql_kit_upgrade_execute" not in billing_names
    assert "nova_sql_location_region_update" not in billing_names
    assert "nova_sql_location_reactivation_update" not in billing_names
    assert "nova_sql_location_layaway_enable" not in billing_names
    assert "nova_sql_account_copy_preview" not in billing_names
    assert "nova_sql_account_copy_status" not in billing_names
    assert "nova_sql_account_copy_execute" not in billing_names


@pytest.mark.anyio
async def test_api_customer_email_cohort_is_fixed_read_only_and_taylor_only(
    coding_client_session,
    client_session,
    billing_client_session,
):
    coding_tools = {tool.name: tool for tool in (await coding_client_session.list_tools()).tools}
    support_names = {tool.name for tool in (await client_session.list_tools()).tools}
    billing_names = {tool.name for tool in (await billing_client_session.list_tools()).tools}
    tool = coding_tools["nova_sql_api_customer_email_cohort"]

    assert tool.annotations.readOnlyHint is True
    assert tool.annotations.destructiveHint is False
    assert tool.inputSchema["properties"] == {}
    assert "nova_sql_api_customer_email_cohort" not in support_names
    assert "nova_sql_api_customer_email_cohort" not in billing_names

    response = await coding_client_session.call_tool("nova_sql_api_customer_email_cohort", {})
    assert response.isError is False
    assert response.structuredContent["verified"] is True
    assert response.structuredContent["emailSent"] is False


@pytest.mark.anyio
async def test_capabilities_are_agent_visible_and_immutable(client_session):
    response = await client_session.call_tool("salesforce_capabilities", {})

    assert response.isError is False
    assert response.structuredContent["mayChangeAccess"] is False
    assert response.structuredContent["provider"]["accessMode"] == "typed_operations_only"
    assert response.structuredContent["permanentlyUnavailable"]
    assert response.structuredContent["ticketRecordTypes"] == ["1. NOVA Classic", "2. Nova Wave"]


@pytest.mark.anyio
async def test_billing_alignment_features_and_exact_selectors_are_exposed_to_both_lanes(
    billing_client_session,
    coding_client_session,
):
    for session in (billing_client_session, coding_client_session):
        capabilities = await session.call_tool("salesforce_capabilities", {})
        assert capabilities.isError is False
        assert capabilities.structuredContent["billingAlignmentFeatures"] == {
            "stagedLocationLifecycleThenLinks": True,
            "exactPerSubscriptionStructureSelectors": True,
            "preservesNonemptyScheduleOwners": True,
        }
        assert capabilities.structuredContent["locationLifecycleOrderPolicy"] == {
            "exposed": True,
            "allowedOrderTypes": {
                "reactivate_existing_location": "Re-activate an Existing Location",
                "within_3_months": "Within the 3-months",
                "existing_additional": "Existing and (New) Additional Customer Order",
            },
            "withinThreeMonthsExistingOrderTypes": {
                "add_additional_location": "New Location",
            },
            "reactivationAlwaysUses": "Re-activate an Existing Location",
            "classificationDatePriority": ["CreatedDate"],
            "forbiddenOrderType": "New Customer Order",
            "merchantProviders": ["Worldpay", "Creditcall", "Authorize.net", "Propelr"],
            "approvalFlowAllowed": False,
            "reactivationFromDeclineAllowed": False,
            "locationReactivatedInNovaPosAllowed": False,
            "accountActivatedInNovaPosAllowed": False,
            "accountFlatRateMutationAllowed": False,
        }
        tools = {tool.name: tool for tool in (await session.list_tools()).tools}
        for name in (
            "salesforce_billing_structure_alignment_preview",
            "salesforce_billing_structure_alignment_apply",
        ):
            properties = tools[name].inputSchema["properties"]
            assert "billing_account_id" in properties
            assert "billing_schedule_id" in properties


@pytest.mark.anyio
async def test_account_360_is_read_only_and_exposed_to_every_interactive_lane(client_session):
    tool = next(
        item
        for item in (await client_session.list_tools()).tools
        if item.name == "salesforce_account_360_read"
    )

    assert tool.annotations.readOnlyHint is True
    assert tool.annotations.destructiveHint is False
    assert set(tool.inputSchema["properties"]) == {
        "search",
        "contacts_limit",
        "locations_limit",
        "tickets_limit",
    }
    for lane in ("direct_codex", "coding_agent", "tickets_agent", "billing_agent"):
        names = set(
            build_mcp(
                lane,
                FakeClient(),
                FakeNovaSqlClient(),
                FakeNovaApiClient(),
            )._tool_manager._tools
        )
        assert "salesforce_account_360_read" in names


def test_account_360_resolves_ticket_to_full_account_relationship_view(monkeypatch):
    client = _client()
    queries = []
    account_id = "001000000000001AAA"
    primary_contact_id = "003000000000001AAA"

    def fake_query(soql):
        queries.append(soql)
        if "FROM Account" in soql and "Company_Username__c =" in soql:
            return {"records": []}
        if "FROM Contact" in soql and "AccountId != null" in soql:
            return {"records": []}
        if "FROM NovaPOS_Location__c" in soql and "Account__c != null" in soql:
            return {"records": []}
        if "FROM NovaPOS_Ticket__c" in soql and "Account__c != null" in soql:
            return {
                "records": [
                    {"Id": "a0G000000000001AAA", "Name": "347191", "Account__c": account_id}
                ]
            }
        if "FROM Account" in soql and "Id IN" in soql:
            return {
                "records": [
                    {
                        "Id": account_id,
                        "Name": "LEJAIM SPA",
                        "Company_Username__c": "LEJAIM_SPA",
                        "PrimaryContact__c": primary_contact_id,
                        "OwnerId": "005000000000001AAA",
                        "Owner": {"Name": "Salesforce Owner", "Email": "owner@example.com"},
                        "Nova_Account_Manager__c": "005000000000002AAA",
                        "Nova_Account_Manager__r": {
                            "Name": "Nova Manager",
                            "Email": "manager@example.com",
                        },
                        "PrimaryContact__r": {
                            "Id": primary_contact_id,
                            "Name": "Gerardo Bermea",
                            "Email": "gerardo@example.com",
                        },
                    }
                ]
            }
        if "FROM Contact" in soql and f"AccountId = '{account_id}'" in soql:
            return {
                "records": [
                    {
                        "Id": primary_contact_id,
                        "Name": "Gerardo Bermea",
                        "AccountId": account_id,
                        "Email": "gerardo@example.com",
                    },
                    {
                        "Id": "003000000000002AAA",
                        "Name": "Operations",
                        "AccountId": account_id,
                        "Email": "ops@example.com",
                    },
                ]
            }
        if "FROM NovaPOS_Location__c" in soql and f"Account__c = '{account_id}'" in soql:
            return {
                "records": [
                    {
                        "Id": "a0L000000000001AAA",
                        "Name": "LEJAIM SPA",
                        "Account__c": account_id,
                        "Location_ID__c": 1,
                        "Status__c": "Storage",
                    }
                ]
            }
        if "FROM NovaPOS_Ticket__c" in soql and f"Account__c = '{account_id}'" in soql:
            return {
                "records": [
                    {
                        "Id": "a0G000000000001AAA",
                        "Name": "347191",
                        "Account__c": account_id,
                        "Is_Closed__c": True,
                    }
                ]
            }
        raise AssertionError(soql)

    monkeypatch.setattr(client, "_query", fake_query)

    result = client.read_account_360("347191")

    assert result["resolved"] is True
    assert result["resolutionSource"] == "ticket"
    assert result["account"]["Company_Username__c"] == "LEJAIM_SPA"
    assert result["owner"]["Name"] == "Salesforce Owner"
    assert result["novaAccountManager"]["Name"] == "Nova Manager"
    assert result["primaryContact"]["Id"] == primary_contact_id
    assert result["contacts"][0]["isPrimaryContact"] is True
    assert result["contacts"][1]["isPrimaryContact"] is False
    assert result["locations"][0]["Status__c"] == "Storage"
    assert result["tickets"][0]["Name"] == "347191"
    assert result["counts"] == {
        "contactsReturned": 2,
        "locationsReturned": 1,
        "ticketsReturned": 1,
    }
    assert result["readOnly"] is True
    assert result["writesPerformed"] is False
    assert all(
        not any(marker in query.casefold() for marker in (" update ", " insert ", " delete ", " upsert "))
        for query in queries
    )
    assert "Department" not in ACCOUNT_360_CONTACT_FIELDS


def test_account_360_returns_candidates_instead_of_guessing_ambiguous_account(monkeypatch):
    client = _client()
    queries = []

    def fake_query(soql):
        queries.append(soql)
        if "FROM Account" in soql:
            return {
                "records": [
                    {
                        "Id": "001000000000001AAA",
                        "Name": "Instyle Fragrance",
                        "Company_Username__c": "instyle_fragrance",
                        "Phone": "555-0101",
                    },
                    {
                        "Id": "001000000000002AAA",
                        "Name": "Le Boutique Instyle",
                        "Company_Username__c": "le_boutique_instyle",
                        "Phone": "555-0102",
                    },
                ]
            }
        return {"records": []}

    monkeypatch.setattr(client, "_query", fake_query)

    result = client.read_account_360("Instyle")

    assert result["resolved"] is False
    assert result["reason"] == "ambiguous_account_matches"
    assert result["candidateCount"] == 2
    assert {item["companyUsername"] for item in result["candidates"]} == {
        "instyle_fragrance",
        "le_boutique_instyle",
    }
    assert len(queries) == 4
    assert result["writesPerformed"] is False


@pytest.mark.anyio
async def test_email_tools_allow_only_fixed_situation_details_and_no_freehand_content(
    client_session,
):
    response = await client_session.list_tools()
    tool = next(
        item
        for item in response.tools
        if item.name == "salesforce_ticket_template_email_send"
    )
    properties = tool.inputSchema["properties"]

    assert set(properties) == {"ticket_id", "situation", "details"}
    assert "recipient" not in properties
    assert "contact_id" not in properties
    assert "subject" not in properties
    assert "body" not in properties
    assert tool.annotations.readOnlyHint is False
    assert tool.annotations.idempotentHint is True

    inventory_tool = next(
        item
        for item in response.tools
        if item.name == "salesforce_email_template_inventory"
    )
    assert inventory_tool.inputSchema["properties"] == {}
    assert inventory_tool.annotations.readOnlyHint is True

    preview_tool = next(
        item
        for item in response.tools
        if item.name == "salesforce_ticket_template_email_preview"
    )
    assert set(preview_tool.inputSchema["properties"]) == {
        "ticket_id",
        "situation",
        "details",
    }
    assert preview_tool.annotations.readOnlyHint is True

    assert not any(item.name == "salesforce_ticket_email_send" for item in response.tools)

    resolve_tool = next(item for item in response.tools if item.name == "salesforce_ticket_resolve")
    assert set(resolve_tool.inputSchema["properties"]) == {
        "ticket_id",
        "feed_element_id",
        "cause",
        "resolution",
        "next_steps",
        "priority_context",
        "update",
    }
    assert set(resolve_tool.inputSchema["required"]) == {"ticket_id"}
    assert resolve_tool.annotations.readOnlyHint is False
    assert resolve_tool.annotations.idempotentHint is True

    chatter_tool = next(
        item for item in response.tools if item.name == "salesforce_ticket_chatter_post"
    )
    assert set(chatter_tool.inputSchema["properties"]) == {
        "ticket_id",
        "cause",
        "resolution",
        "next_steps",
        "priority_context",
        "update",
    }
    assert set(chatter_tool.inputSchema["required"]) == {"ticket_id"}
    assert "body" not in chatter_tool.inputSchema["properties"]

    reply_tool = next(
        item for item in response.tools if item.name == "salesforce_ticket_chatter_reply"
    )
    assert set(reply_tool.inputSchema["properties"]) == {
        "ticket_id",
        "feed_element_id",
        "cause",
        "resolution",
        "next_steps",
        "priority_context",
        "update",
    }
    assert set(reply_tool.inputSchema["required"]) == {"ticket_id", "feed_element_id"}
    assert "body" not in reply_tool.inputSchema["properties"]

    note_tool = next(item for item in response.tools if item.name == "salesforce_ticket_internal_note_update")
    assert set(note_tool.inputSchema["properties"]) == {
        "ticket_id",
        "cause",
        "resolution",
        "next_steps",
        "priority_context",
        "update",
    }
    assert set(note_tool.inputSchema["required"]) == {"ticket_id"}
    assert "note" not in note_tool.inputSchema["properties"]
    assert note_tool.annotations.readOnlyHint is False
    assert note_tool.annotations.idempotentHint is True

    email_log_tool = next(item for item in response.tools if item.name == "salesforce_ticket_email_log_read")
    assert email_log_tool.annotations.readOnlyHint is True


@pytest.mark.anyio
async def test_sensitive_credentials_tools_are_support_only_and_have_no_secret_inputs(
    client_session,
    billing_client_session,
    coding_client_session,
):
    support_tools = {
        item.name: item for item in (await client_session.list_tools()).tools
    }
    billing_names = {
        item.name for item in (await billing_client_session.list_tools()).tools
    }
    coding_names = {
        item.name for item in (await coding_client_session.list_tools()).tools
    }

    for name, read_only in (
        ("salesforce_ticket_company_credentials_email_preview", True),
        ("salesforce_ticket_company_credentials_email_send", False),
    ):
        tool = support_tools[name]
        assert set(tool.inputSchema["properties"]) == {
            "ticket_id",
            "requested_recipients",
        }
        assert "body" not in tool.inputSchema["properties"]
        assert "subject" not in tool.inputSchema["properties"]
        assert "template_id" not in tool.inputSchema["properties"]
        assert "sender" not in tool.inputSchema["properties"]
        assert tool.annotations.readOnlyHint is read_only
        assert name not in billing_names
        assert name not in coding_names


@pytest.mark.anyio
async def test_refund_template_email_is_billing_only_and_has_no_content_override(
    billing_client_session,
):
    response = await billing_client_session.list_tools()
    tool = next(
        item
        for item in response.tools
        if item.name == "salesforce_ticket_refund_confirmation_email_send"
    )

    assert set(tool.inputSchema["properties"]) == {"ticket_id", "refund_amount_cents"}
    assert tool.annotations.readOnlyHint is False
    assert tool.annotations.idempotentHint is True

    credit_tool = next(
        item
        for item in response.tools
        if item.name == "salesforce_ticket_credit_confirmation_email_send"
    )
    assert set(credit_tool.inputSchema["properties"]) == {"ticket_id", "credit_amount_cents"}
    assert credit_tool.annotations.readOnlyHint is False
    assert credit_tool.annotations.idempotentHint is True


@pytest.mark.anyio
async def test_account_cancellation_confirmation_email_is_primary_contact_owned_and_fixed(
    billing_client_session,
):
    response = await billing_client_session.list_tools()
    tool = next(
        item
        for item in response.tools
        if item.name == "salesforce_account_cancellation_confirmation_email_send"
    )

    assert set(tool.inputSchema["properties"]) == {"ticket_id", "account_id"}
    assert "recipient" not in tool.inputSchema["properties"]
    assert "subject" not in tool.inputSchema["properties"]
    assert "body" not in tool.inputSchema["properties"]
    assert tool.annotations.readOnlyHint is False
    assert tool.annotations.idempotentHint is True

    finalize = next(
        item
        for item in response.tools
        if item.name == "salesforce_account_cancellation_finalize"
    )
    assert set(finalize.inputSchema["properties"]) == {
        "ticket_id",
        "account_id",
        "feed_element_id",
        "update",
    }
    assert set(finalize.inputSchema["required"]) == {"ticket_id", "account_id"}
    assert finalize.annotations.readOnlyHint is False
    assert finalize.annotations.idempotentHint is True


def test_account_cancellation_finalize_uses_cross_lane_guard_email_and_resolve(
    monkeypatch,
):
    client = _client()
    ticket_id = "a0G000000000001AAA"
    account_id = "001000000000001AAA"
    calls: list[tuple[str, object]] = []

    monkeypatch.setattr(
        client,
        "_assert_account_cancellation_ticket",
        lambda ticket, account: calls.append(("guard", (ticket, account))) or {"Id": ticket},
    )
    monkeypatch.setattr(
        client,
        "send_account_cancellation_confirmation_email",
        lambda ticket, account: calls.append(("email", (ticket, account)))
        or {"ok": True, "verified": True, "sent": False, "duplicate": True},
    )
    monkeypatch.setattr(
        client,
        "resolve_ticket",
        lambda ticket, note, **kwargs: calls.append(
            ("resolve", (ticket, note, kwargs))
        )
        or {"ok": True, "verified": True, "closed": True, "updated": True},
    )

    result = client.finalize_account_cancellation(
        ticket_id,
        account_id,
        "Account closed and confirmation sent.",
        reply_to_feed_element_id="0D5000000000001AAA",
    )

    assert result["verified"] is True
    assert [name for name, _value in calls] == ["guard", "email", "resolve"]
    _name, resolve_args = calls[-1]
    assert resolve_args[2]["allowed_record_types"] is None
    assert resolve_args[2]["reply_to_feed_element_id"] == "0D5000000000001AAA"


@pytest.mark.anyio
async def test_cancellation_order_tools_require_exact_locations_and_maxio_evidence(
    billing_client_session,
):
    tools = {
        item.name: item for item in (await billing_client_session.list_tools()).tools
    }
    for name in ("salesforce_account_cancellation_order_preview",):
        tool = tools[name]
        assert set(tool.inputSchema["properties"]) == {
            "ticket_id",
            "account_id",
            "salesforce_location_ids",
            "official_nova_location_ids",
            "maxio_deallocation_evidence",
            "cancellation_reason",
            "notes",
        }
        assert set(tool.inputSchema["required"]) == {
            "ticket_id",
            "account_id",
            "salesforce_location_ids",
            "official_nova_location_ids",
            "maxio_deallocation_evidence",
            "cancellation_reason",
        }
        assert tool.annotations.readOnlyHint is True

    location_preview = tools["salesforce_location_cancellation_order_preview"]
    assert set(location_preview.inputSchema["properties"]) == {
        "ticket_id",
        "account_id",
        "salesforce_location_ids",
        "maxio_deallocation_evidence",
        "cancellation_reason",
        "notes",
    }
    assert "official_nova_location_ids" not in location_preview.inputSchema["properties"]

    for name in ("salesforce_account_cancellation_order_apply",):
        tool = tools[name]
        assert set(tool.inputSchema["properties"]) == {
            "ticket_id",
            "account_id",
            "salesforce_location_ids",
            "official_nova_location_ids",
            "maxio_deallocation_evidence",
            "cancellation_reason",
            "idempotency_key",
            "preview_hash",
            "notes",
        }
        assert {
            "salesforce_location_ids",
            "official_nova_location_ids",
            "maxio_deallocation_evidence",
            "idempotency_key",
            "preview_hash",
        }.issubset(set(tool.inputSchema["required"]))
        assert tool.annotations.readOnlyHint is False
        assert tool.annotations.idempotentHint is True

    location_apply = tools["salesforce_location_cancellation_order_apply"]
    assert "official_nova_location_ids" not in location_apply.inputSchema["properties"]
    assert {
        "salesforce_location_ids",
        "maxio_deallocation_evidence",
        "idempotency_key",
        "preview_hash",
    }.issubset(set(location_apply.inputSchema["required"]))

    closure_preview = tools["salesforce_account_closure_preview"]
    assert set(closure_preview.inputSchema["required"]) == {
        "ticket_id",
        "account_id",
        "closed_nova_location_ids",
        "nova_active_location_ids",
        "maxio_reconciliation_evidence",
    }
    closure_apply = tools["salesforce_account_closure_apply"]
    assert {
        "closed_nova_location_ids",
        "nova_active_location_ids",
        "maxio_reconciliation_evidence",
        "idempotency_key",
        "preview_hash",
    }.issubset(set(closure_apply.inputSchema["required"]))


@pytest.mark.anyio
async def test_sender_preflight_is_read_only_and_has_no_sender_selector_inputs(
    client_session,
):
    response = await client_session.list_tools()
    tool = next(
        item
        for item in response.tools
        if item.name == "salesforce_email_sender_preflight"
    )
    names = {item.name for item in response.tools}

    assert tool.inputSchema["properties"] == {}
    assert tool.annotations.readOnlyHint is True
    assert tool.annotations.destructiveHint is False
    assert not any("direct_darius" in name and "email_" in name for name in names)
    forbidden_sender_inputs = {
        "sender",
        "senderAddress",
        "senderType",
        "orgWideEmailAddressId",
        "fromAddress",
    }
    for candidate in response.tools:
        if candidate.name in {
            "salesforce_ticket_template_email_preview",
            "salesforce_ticket_template_email_send",
            "salesforce_ticket_company_credentials_email_preview",
            "salesforce_ticket_company_credentials_email_send",
        }:
            assert forbidden_sender_inputs.isdisjoint(
                candidate.inputSchema["properties"]
            )


def test_approved_template_inventory_maps_fixed_situations_without_returning_bodies(
    monkeypatch,
):
    client = _client()
    monkeypatch.setattr(
        client,
        "_query",
        lambda soql: {
            "records": [
                {
                    "Id": "00X000000000001AAA",
                    "Name": "NovaPOS Billing Inquiry Update",
                    "DeveloperName": "NovaPOS_Billing_Inquiry_Update",
                    "FolderId": "00lA0000001VKQq",
                    "TemplateType": "html",
                    "IsActive": True,
                    "Subject": "NovaPOS Billing Inquiry Update",
                    "BrandTemplateId": "016A0000000ChpTIAS",
                    "Description": "Approved template",
                    "LastModifiedDate": "2026-07-24T20:00:00.000+0000",
                }
            ]
        }
        if "FROM EmailTemplate" in soql
        else (_ for _ in ()).throw(AssertionError(soql)),
    )

    result = client.approved_email_template_inventory()

    assert result["verified"] is True
    assert result["freehandSubjectAllowed"] is False
    assert result["freehandBodyAllowed"] is False
    assert result["templates"][0]["situation"] == "billing_inquiry_update"
    assert result["templates"][0]["sendEnabled"] is True
    assert result["templates"][0]["classification"] == EMAIL_TEMPLATE_CLASS_APPROVED
    assert result["templates"][0]["department"] == "billing"
    assert result["templates"][0]["senderPolicy"] == "department_org_wide"
    assert result["templates"][0]["recipientPolicy"] == "ticket_contact"
    assert result["templates"][0]["sensitivity"] == "standard"
    assert result["templates"][0]["previewTool"] == "salesforce_ticket_template_email_preview"
    assert result["templates"][0]["owningLanes"] == ["direct_codex", "billing_agent"]
    assert result["templates"][0]["requiredDetails"] == ["last4Digits", "message"]
    assert "HtmlValue" not in result["templates"][0]
    assert "Body" not in result["templates"][0]
    pending = {item["situation"]: item for item in result["templates"]}
    assert pending["support_unhappy_goodbye"]["classification"] == EMAIL_TEMPLATE_CLASS_BROKEN
    assert pending["account_in_decline"]["classification"] == EMAIL_TEMPLATE_CLASS_CONTENT_PENDING
    assert pending["next_billing_date_notification"]["classification"] == EMAIL_TEMPLATE_CLASS_MISSING
    assert pending["support_one_off_message"]["classification"] == EMAIL_TEMPLATE_CLASS_MISSING
    assert pending["billing_one_off_message"]["classification"] == EMAIL_TEMPLATE_CLASS_MISSING
    assert pending["direct_darius_inbound_reply"]["classification"] == EMAIL_TEMPLATE_CLASS_MISSING
    assert pending["direct_darius_inbound_reply"]["sendTool"] is None
    assert (
        pending["direct_darius_inbound_reply"]["senderPolicy"]
        == DIRECT_DARIUS_REPLY_SENDER_POLICY
    )
    assert all(not item["sendEnabled"] for key, item in pending.items() if key in {
        workflow["situation"] for workflow in CANONICAL_PENDING_EMAIL_WORKFLOWS
    })


def test_email_registry_uses_exact_identity_and_complete_server_owned_policy():
    required = {
        "classification",
        "department",
        "detailFields",
        "recipientPolicy",
        "senderPolicy",
        "sensitivity",
        "previewTool",
        "sendTool",
        "owningLanes",
    }
    for identity, spec in EMAIL_TEMPLATE_REGISTRY.items():
        assert identity == (spec["folderId"], spec["developerName"])
        assert required <= set(spec)
        assert spec["classification"] == EMAIL_TEMPLATE_CLASS_APPROVED
        assert spec["senderPolicy"] == "department_org_wide"
        assert spec["department"] in {"support", "billing"}
        assert spec["owningLanes"]

    pending = {
        workflow["situation"]: workflow
        for workflow in CANONICAL_PENDING_EMAIL_WORKFLOWS
    }
    assert {
        "case_update",
        "api_access_credentials",
        "api_capabilities_update_july_2026",
        "requested_documents_attached",
        "support_ticket_created",
        "support_ticket_closed",
        "support_unable_to_reach_customer",
        "support_unhappy_goodbye",
        "nova_wave_new_account_welcome",
        "api_write_capabilities",
        "software_billing_issue_notification",
        "accessing_billing_automation",
        "account_is_closed",
        "account_in_decline",
        "account_in_decline_spanish",
        "new_location_added",
        "new_storage_location_added",
        "closing_or_deactivating_location_or_account",
        "payment_information_update_required",
        "future_credit_applied",
        "refund_credit_approved_notification",
        "refund_policy_cancelled_locations",
        "decline_extension_approved",
        "next_billing_date_notification",
        "generic_pending_reply",
        "billing_one_off_message",
        "direct_darius_inbound_reply",
    } == set(pending)
    assert pending["billing_one_off_message"]["sendTool"] is None
    assert pending["billing_one_off_message"]["detailFields"] == ("message",)
    support_one_off = EMAIL_TEMPLATE_REGISTRY[
        ("00lA0000000peVU", SUPPORT_ONE_OFF_TEMPLATE_DEVELOPER_NAME)
    ]
    assert support_one_off["situation"] == "support_one_off_message"
    assert support_one_off["detailFields"] == ("message",)
    assert support_one_off["recipientPolicy"] == "ticket_contact"
    assert support_one_off["owningLanes"] == (
        "direct_codex",
        "tickets_agent",
        "coding_agent",
    )
    direct_darius = pending["direct_darius_inbound_reply"]
    assert direct_darius["classification"] == EMAIL_TEMPLATE_CLASS_MISSING
    assert direct_darius["department"] == "direct_darius_reply"
    assert direct_darius["senderPolicy"] == DIRECT_DARIUS_REPLY_SENDER_POLICY
    assert direct_darius["recipientPolicy"] == "exact_inbound_emailmessage_from_address"
    assert direct_darius["owningLanes"] == ("direct_codex",)
    assert direct_darius["acceptedNames"] == ()
    assert direct_darius["previewTool"] is None
    assert direct_darius["sendTool"] is None
    assert "no exact approved stored reply template" in direct_darius["rejectionReason"]
    assert (
        "Your Request is Currently Pending – NovaPOS"
        in pending["generic_pending_reply"]["acceptedNames"]
    )
    api_intro = EMAIL_TEMPLATE_REGISTRY[
        ("00lA0000000peVU", "NovaPOS_API_Intro")
    ]
    assert api_intro["folderId"] == "00lA0000000peVU"
    assert api_intro["expectedTemplateId"] == "00XRc000007pDs1MAE"
    assert api_intro["department"] == "billing"
    assert api_intro["recipientPolicy"] == "account_primary_only"
    assert api_intro["owningLanes"] == ("direct_codex", "billing_agent")
    assert api_intro["requiredBodyFragments"] == (
        "14-day trial period",
        "one-time setup fee of $100",
        "monthly usage fee of $50",
    )


def test_api_intro_inventory_is_sendable_only_to_billing_owners(monkeypatch):
    client = _client()
    monkeypatch.setattr(
        client,
        "_query",
        lambda _soql: {
            "records": [
                {
                    "Id": "00XRc000007pDs1MAE",
                    "Name": "NovaPOS API Intro",
                    "DeveloperName": "NovaPOS_API_Intro",
                    "FolderId": "00lA0000000peVUIAY",
                    "TemplateType": "html",
                    "IsActive": True,
                    "Subject": "NovaPOS API access information",
                    "BrandTemplateId": "016A0000000ChpTIAS",
                    "Description": "Owner-approved API introduction.",
                    "LastModifiedDate": "2026-08-03T17:00:00.000+0000",
                }
            ]
        },
    )

    billing = client.approved_email_template_inventory(lane="billing_agent")
    support = client.approved_email_template_inventory(lane="tickets_agent")
    billing_api = next(
        item for item in billing["templates"] if item["situation"] == "api_intro"
    )
    support_api = next(
        item for item in support["templates"] if item["situation"] == "api_intro"
    )

    assert billing_api["classification"] == EMAIL_TEMPLATE_CLASS_APPROVED
    assert billing_api["registrySendable"] is True
    assert billing_api["availableToLane"] is True
    assert billing_api["recipientPolicy"] == "account_primary_only"
    assert billing_api["requiredDetails"] == []
    assert support_api["registrySendable"] is True
    assert support_api["availableToLane"] is False


def test_api_intro_preview_drops_ticket_listed_additional_recipients(monkeypatch):
    client = _client()
    ticket_id = "a0G000000000000AAA"
    primary_contact_id = "003000000000001AAA"
    verified_fragments = []
    monkeypatch.setattr(client, "_assert_ticket_scope", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        client,
        "read_ticket",
        lambda _ticket_id: {
            "ok": True,
            "record": {
                "Id": ticket_id,
                "Account__c": "001000000000001AAA",
                "Contact__c": "003000000000002AAA",
            },
        },
    )
    monkeypatch.setattr(
        client,
        "_billing_confirmation_targets",
        lambda _ticket: {
            "accountId": "001000000000001AAA",
            "accountName": "Customer Account",
            "primaryContactId": primary_contact_id,
            "primaryRecipient": "primary@example.com",
            "primarySendContactId": primary_contact_id,
            "renderContactId": primary_contact_id,
            "additionalRecipients": ["listed@example.com"],
            "recipients": ["primary@example.com", "listed@example.com"],
        },
    )
    monkeypatch.setattr(
        client,
        "_ticket_contact_template_targets",
        lambda _ticket: pytest.fail("API intro must not use the inactive ticket Contact"),
    )
    monkeypatch.setattr(
        client,
        "_resolve_approved_email_template",
        lambda *_args, **_kwargs: {
            "templateId": "00XRc000007pDs1MAE",
            "templateName": "NovaPOS API Intro",
            "templateDeveloperName": "NovaPOS_API_Intro",
            "subject": "NovaPOS API access information",
            "brandTemplateId": "016A0000000ChpTIAS",
        },
    )
    monkeypatch.setattr(
        client,
        "_resolve_department_sender",
        lambda _department: {
            "department": "billing",
            "orgWideEmailAddressId": "0D2000000000001AAA",
            "address": BILLING_ORG_WIDE_EMAIL_ADDRESS,
            "senderType": "OrgWideEmailAddress",
            "senderPolicy": "department_org_wide",
        },
    )
    monkeypatch.setattr(
        client,
        "_render_stored_email_template",
        lambda **_kwargs: {
            "subject": "NovaPOS API access information",
            "htmlBody": '<body styleInsert="1"><img src="ImageServer">API access</body>',
            "plainTextBody": "API access is available for approved customer workflows.",
        },
    )
    def verify_preview(_preview, **kwargs):
        verified_fragments.extend(kwargs["required_fragments"])
        return {"verified": True}

    monkeypatch.setattr(
        salesforce_client_module,
        "_verify_approved_template_preview",
        verify_preview,
    )

    prepared = client._prepare_ticket_template_email(
        ticket_id=ticket_id,
        situation="api_intro",
        details={},
        lane="billing_agent",
        allowed_record_types={"3. Billing"},
    )

    assert prepared["targets"]["primaryRecipient"] == "primary@example.com"
    assert prepared["targets"]["recipients"] == ["primary@example.com"]
    assert prepared["targets"]["additionalRecipients"] == []
    assert prepared["sender"]["address"] == BILLING_ORG_WIDE_EMAIL_ADDRESS
    assert verified_fragments == [
        "14-day trial period",
        "one-time setup fee of $100",
        "monthly usage fee of $50",
    ]


def test_template_inventory_fails_closed_for_ambiguous_exact_identity(monkeypatch):
    client = _client()
    template = {
        "Name": "NovaPOS Billing Inquiry Update",
        "DeveloperName": "NovaPOS_Billing_Inquiry_Update",
        "FolderId": "00lA0000001VKQq",
        "TemplateType": "html",
        "IsActive": True,
        "Subject": "NovaPOS Billing Inquiry Update",
        "BrandTemplateId": "016A0000000ChpTIAS",
        "Description": "duplicate",
        "LastModifiedDate": "2026-07-28T20:00:00.000+0000",
    }
    monkeypatch.setattr(
        client,
        "_query",
        lambda _soql: {
            "records": [
                {**template, "Id": "00X000000000001AAA"},
                {**template, "Id": "00X000000000002AAA"},
            ]
        },
    )

    result = client.approved_email_template_inventory(lane="billing_agent")
    matches = [
        item
        for item in result["templates"]
        if item["developerName"] == "NovaPOS_Billing_Inquiry_Update"
    ]

    assert len(matches) == 2
    assert all(item["classification"] == EMAIL_TEMPLATE_CLASS_BROKEN for item in matches)
    assert all(item["sendEnabled"] is False for item in matches)


@pytest.mark.parametrize(
    ("name", "developer_name", "subject", "description"),
    [
        ("[Internal] Case Routing Notice", "Case_Routing_Notice", "Legacy notice", ""),
        (
            "Legacy Customer Notice",
            "Legacy_Customer_Notice",
            "Legacy notice",
            "Deprecated - do not use",
        ),
        ("Obsolete Billing Notice", "Obsolete_Billing_Notice", "Legacy notice", ""),
        ("Legacy Notice", "Legacy_Notice", "[Internal] Account details", ""),
    ],
)
def test_template_inventory_emits_curated_rejected_classification_for_explicit_markers(
    monkeypatch,
    name,
    developer_name,
    subject,
    description,
):
    client = _client()
    monkeypatch.setattr(
        client,
        "_query",
        lambda _soql: {
            "records": [
                {
                    "Id": "00X000000000009AAA",
                    "Name": name,
                    "DeveloperName": developer_name,
                    "FolderId": "00lA0000000peVU",
                    "TemplateType": "html",
                    "IsActive": True,
                    "Subject": subject,
                    "BrandTemplateId": "016A0000000ChpTIAS",
                    "Description": description,
                    "LastModifiedDate": "2026-07-28T20:00:00.000+0000",
                }
            ]
        },
    )

    result = client.approved_email_template_inventory(lane="tickets_agent")
    rejected = next(item for item in result["templates"] if item["id"])

    assert rejected["classification"] == EMAIL_TEMPLATE_CLASS_REJECTED
    assert rejected["registrySendable"] is False
    assert rejected["availableToLane"] is False
    assert rejected["sendEnabled"] is False
    assert "not customer-sendable" in rejected["classificationReason"]


@pytest.mark.parametrize(
    ("lane", "situation"),
    [
        ("tickets_agent", "billing_inquiry_update"),
        ("coding_agent", "account_close_request"),
    ],
)
def test_support_lanes_cannot_use_billing_template_routes_without_network(
    monkeypatch,
    lane,
    situation,
):
    client = _client()
    monkeypatch.setattr(
        client,
        "read_ticket",
        lambda *_args, **_kwargs: pytest.fail("wrong-lane route reached Salesforce"),
    )

    with pytest.raises(SalesforceScopeError, match="different department lane"):
        client.preview_ticket_template_email(
            ticket_id="a0G000000000000AAA",
            situation=situation,
            details=(
                {"last4Digits": "2828", "message": "A bounded update."}
                if situation == "billing_inquiry_update"
                else {}
            ),
            lane=lane,
        )


def test_billing_lane_cannot_use_sensitive_support_route_without_network(monkeypatch):
    client = _client()
    monkeypatch.setattr(
        client,
        "read_ticket",
        lambda *_args, **_kwargs: pytest.fail("wrong-lane route reached Salesforce"),
    )

    with pytest.raises(SalesforceScopeError, match="different department lane"):
        client.preview_ticket_company_credentials_email(
            ticket_id=CREDENTIALS_TICKET_ID,
            requested_recipients=list(CREDENTIALS_AUTHORIZED_RECIPIENTS),
            lane="billing_agent",
        )


def test_department_sender_resolution_is_exact_unique_and_profile_usable(monkeypatch):
    client = _client()
    queries = []

    def fake_query(soql):
        queries.append(soql)
        return {
            "records": [
                {
                    "Id": "0D2000000000001AAA",
                    "Address": SUPPORT_ORG_WIDE_EMAIL_ADDRESS,
                    "DisplayName": "Nova Support",
                    "IsAllowAllProfiles": True,
                }
            ]
        }

    monkeypatch.setattr(client, "_query", fake_query)

    result = client._resolve_department_sender("support")

    assert result["address"] == SUPPORT_ORG_WIDE_EMAIL_ADDRESS
    assert result["senderType"] == "OrgWideEmailAddress"
    assert (
        result["providerVerificationBoundary"]
        == "email_action_acceptance_and_emailmessage_from_address_readback"
    )
    assert f"Address = '{SUPPORT_ORG_WIDE_EMAIL_ADDRESS}'" in queries[0]
    assert "LIMIT 2" in queries[0]


def test_email_sender_preflight_is_bounded_to_the_three_fixed_addresses(monkeypatch):
    client = _client()
    queries = []
    records = {
        SUPPORT_ORG_WIDE_EMAIL_ADDRESS: {
            "Id": "0D2000000000001AAA",
            "Address": SUPPORT_ORG_WIDE_EMAIL_ADDRESS,
            "DisplayName": "Nova Support",
            "IsAllowAllProfiles": True,
        },
        BILLING_ORG_WIDE_EMAIL_ADDRESS: {
            "Id": "0D2000000000002AAA",
            "Address": BILLING_ORG_WIDE_EMAIL_ADDRESS,
            "DisplayName": "Nova Billing",
            "IsAllowAllProfiles": True,
        },
        DARIUS_ORG_WIDE_EMAIL_ADDRESS: {
            "Id": "0D2000000000003AAA",
            "Address": DARIUS_ORG_WIDE_EMAIL_ADDRESS,
            "DisplayName": "Darius",
            "IsAllowAllProfiles": True,
        },
    }

    def fake_query(soql):
        queries.append(soql)
        address = next(address for address in records if f"Address = '{address}'" in soql)
        return {"records": [records[address]]}

    monkeypatch.setattr(client, "_query", fake_query)

    result = client.email_sender_preflight()

    assert result["allRequiredReady"] is True
    assert result["callerSelectedSenderAllowed"] is False
    assert result["readOnly"] is True
    assert result["writesPerformed"] is False
    assert {item["address"] for item in result["senders"]} == set(records)
    direct = next(
        item for item in result["senders"] if item["policy"] == "direct_darius_reply"
    )
    assert direct["senderPolicy"] == DIRECT_DARIUS_REPLY_SENDER_POLICY
    assert direct["allowedUse"] == "exact_inbound_emailmessage_reply_only"
    assert direct["proactiveAllowed"] is False
    assert all("orgWideEmailAddressId" not in item for item in result["senders"])
    assert len(queries) == 3
    assert all("FROM OrgWideEmailAddress" in query and "LIMIT 2" in query for query in queries)


def test_email_sender_preflight_reports_missing_or_restricted_without_writes(monkeypatch):
    client = _client()

    def fake_query(soql):
        if SUPPORT_ORG_WIDE_EMAIL_ADDRESS in soql:
            return {"records": []}
        if BILLING_ORG_WIDE_EMAIL_ADDRESS in soql:
            return {
                "records": [
                    {
                        "Id": "0D2000000000002AAA",
                        "Address": BILLING_ORG_WIDE_EMAIL_ADDRESS,
                        "IsAllowAllProfiles": False,
                    }
                ]
            }
        return {
            "records": [
                {
                    "Id": "0D2000000000003AAA",
                    "Address": DARIUS_ORG_WIDE_EMAIL_ADDRESS,
                    "IsAllowAllProfiles": True,
                },
                {
                    "Id": "0D2000000000004AAA",
                    "Address": DARIUS_ORG_WIDE_EMAIL_ADDRESS,
                    "IsAllowAllProfiles": True,
                },
            ]
        }

    monkeypatch.setattr(client, "_query", fake_query)

    result = client.email_sender_preflight()
    by_policy = {item["policy"]: item for item in result["senders"]}

    assert result["allRequiredReady"] is False
    assert by_policy["support"]["reason"] == "required address did not resolve uniquely"
    assert by_policy["billing"]["reason"] == (
        "required address is not available to every executing profile"
    )
    assert by_policy["direct_darius_reply"]["unique"] is False
    assert by_policy["direct_darius_reply"]["ready"] is False
    assert result["writesPerformed"] is False


def test_direct_darius_reply_sender_requires_exact_inbound_thread_and_recipient(
    monkeypatch,
):
    client = _client()
    ticket_id = "a0G000000000001AAA"
    email_message_id = "02s000000000001AAA"
    queries = []

    def fake_query(soql):
        queries.append(soql)
        if "FROM EmailMessage" in soql:
            return {
                "records": [
                    {
                        "Id": email_message_id,
                        "RelatedToId": ticket_id,
                        "Incoming": True,
                        "FromAddress": "Customer <CUSTOMER@Example.COM>",
                        "ToAddress": (
                            f"Darius <{DARIUS_ORG_WIDE_EMAIL_ADDRESS}>; "
                            "second-recipient@example.com"
                        ),
                    }
                ]
            }
        if "FROM OrgWideEmailAddress" in soql:
            return {
                "records": [
                    {
                        "Id": "0D2000000000003AAA",
                        "Address": DARIUS_ORG_WIDE_EMAIL_ADDRESS,
                        "DisplayName": "Darius",
                        "IsAllowAllProfiles": True,
                    }
                ]
            }
        raise AssertionError(soql)

    monkeypatch.setattr(client, "_query", fake_query)

    result = client._resolve_direct_darius_reply_sender(
        ticket_id=ticket_id,
        inbound_email_message_id=email_message_id,
        recipient="CUSTOMER@example.com",
        lane="direct_codex",
    )

    assert result["address"] == DARIUS_ORG_WIDE_EMAIL_ADDRESS
    assert result["senderPolicy"] == DIRECT_DARIUS_REPLY_SENDER_POLICY
    assert result["recipient"] == "customer@example.com"
    assert result["recipientSource"] == "inbound_emailmessage_from_address"
    assert result["inboundEmailMessageId"] == email_message_id
    assert result["replyOnly"] is True
    assert f"WHERE Id = '{email_message_id}' LIMIT 2" in queries[0]
    assert f"Address = '{DARIUS_ORG_WIDE_EMAIL_ADDRESS}'" in queries[1]


@pytest.mark.parametrize(
    ("record_patch", "recipient", "error"),
    [
        (
            {"RelatedToId": "a0G000000000002AAA"},
            "customer@example.com",
            "not related to the exact ticket",
        ),
        (
            {"Incoming": False},
            "customer@example.com",
            "requires an inbound",
        ),
        (
            {"ToAddress": SUPPORT_ORG_WIDE_EMAIL_ADDRESS},
            "customer@example.com",
            "not addressed directly to Darius",
        ),
        (
            {
                "ToAddress": (
                    f'"{DARIUS_ORG_WIDE_EMAIL_ADDRESS}" <attacker@example.com>'
                )
            },
            "customer@example.com",
            "not addressed directly to Darius",
        ),
        (
            {
                "ToAddress": "other@example.com",
                "CcAddress": DARIUS_ORG_WIDE_EMAIL_ADDRESS,
            },
            "customer@example.com",
            "not addressed directly to Darius",
        ),
        (
            {
                "ToAddress": "other@example.com",
                "BccAddress": DARIUS_ORG_WIDE_EMAIL_ADDRESS,
            },
            "customer@example.com",
            "not addressed directly to Darius",
        ),
        (
            {},
            "unrelated@example.com",
            "must match the inbound EmailMessage sender",
        ),
        (
            {"FromAddress": SUPPORT_ORG_WIDE_EMAIL_ADDRESS},
            SUPPORT_ORG_WIDE_EMAIL_ADDRESS,
            "verified external sender",
        ),
        (
            {"FromAddress": "employee@mail.novapointofsale.com"},
            "employee@mail.novapointofsale.com",
            "verified external sender",
        ),
        (
            {"FromAddress": "darius@novapointofsale.com."},
            "darius@novapointofsale.com",
            "verified external sender",
        ),
        (
            {"FromAddress": "customer@example.com;"},
            "customer@example.com",
            "verified external sender",
        ),
        (
            {"FromAddress": "customer@example.com,attacker@example.com"},
            "customer@example.com",
            "verified external sender",
        ),
        (
            {"FromAddress": "customer@example.com,"},
            "customer@example.com",
            "verified external sender",
        ),
        (
            {"FromAddress": "customer@example.com garbage"},
            "customer@example.com",
            "verified external sender",
        ),
    ],
)
def test_direct_darius_reply_sender_rejects_wrong_thread_or_recipient(
    monkeypatch,
    record_patch,
    recipient,
    error,
):
    client = _client()
    ticket_id = "a0G000000000001AAA"
    email_message_id = "02s000000000001AAA"
    record = {
        "Id": email_message_id,
        "RelatedToId": ticket_id,
        "Incoming": True,
        "FromAddress": "customer@example.com",
        "ToAddress": DARIUS_ORG_WIDE_EMAIL_ADDRESS,
        **record_patch,
    }
    monkeypatch.setattr(client, "_query", lambda _soql: {"records": [record]})

    with pytest.raises(SalesforceScopeError, match=error):
        client._resolve_direct_darius_reply_sender(
            ticket_id=ticket_id,
            inbound_email_message_id=email_message_id,
            recipient=recipient,
            lane="direct_codex",
        )


def test_direct_darius_mailbox_parsing_uses_python311_compatible_positional_calls(
    monkeypatch,
):
    real_getaddresses = salesforce_client_module.getaddresses
    real_parseaddr = salesforce_client_module.parseaddr
    calls = []

    def python311_getaddresses(values, /):
        calls.append("getaddresses")
        return real_getaddresses(values)

    def python311_parseaddr(value, /):
        calls.append("parseaddr")
        return real_parseaddr(value)

    monkeypatch.setattr(
        salesforce_client_module,
        "getaddresses",
        python311_getaddresses,
    )
    monkeypatch.setattr(
        salesforce_client_module,
        "parseaddr",
        python311_parseaddr,
    )

    assert (
        _canonical_single_mailbox("Customer <CUSTOMER@Example.COM>")
        == "customer@example.com"
    )
    assert _canonical_single_mailbox("customer@example.com;") is None
    assert _canonical_single_mailbox("customer@example.com garbage") is None
    assert _canonical_mailbox_list(
        f'"{DARIUS_ORG_WIDE_EMAIL_ADDRESS}" <attacker@example.com>',
        allow_semicolon_separator=True,
    ) == frozenset({"attacker@example.com"})
    assert calls.count("getaddresses") == 3
    assert calls.count("parseaddr") == 2


@pytest.mark.parametrize(
    "records",
    [
        [],
        [
            {
                "Id": "02s000000000001AAA",
                "RelatedToId": "a0G000000000001AAA",
                "Incoming": True,
                "FromAddress": "customer@example.com",
                "ToAddress": DARIUS_ORG_WIDE_EMAIL_ADDRESS,
            },
            {
                "Id": "02s000000000002AAA",
                "RelatedToId": "a0G000000000001AAA",
                "Incoming": True,
                "FromAddress": "customer@example.com",
                "ToAddress": DARIUS_ORG_WIDE_EMAIL_ADDRESS,
            },
        ],
    ],
)
def test_direct_darius_reply_sender_requires_one_exact_inbound_record(
    monkeypatch,
    records,
):
    client = _client()
    monkeypatch.setattr(client, "_query", lambda _soql: {"records": records})

    with pytest.raises(SalesforceUnavailableError, match="did not resolve uniquely"):
        client._resolve_direct_darius_reply_sender(
            ticket_id="a0G000000000001AAA",
            inbound_email_message_id="02s000000000001AAA",
            recipient="customer@example.com",
            lane="direct_codex",
        )


@pytest.mark.parametrize("lane", ["tickets_agent", "billing_agent", "coding_agent"])
def test_department_lanes_cannot_select_direct_darius_sender_without_network(
    monkeypatch,
    lane,
):
    client = _client()
    monkeypatch.setattr(
        client,
        "_query",
        lambda _soql: pytest.fail("wrong lane reached Salesforce"),
    )

    with pytest.raises(SalesforceScopeError, match="direct operator lane"):
        client._resolve_direct_darius_reply_sender(
            ticket_id="a0G000000000001AAA",
            inbound_email_message_id="02s000000000001AAA",
            recipient="customer@example.com",
            lane=lane,
        )


def test_department_sender_policy_cannot_select_darius_or_proactively_resolve_reply(
    monkeypatch,
):
    client = _client()
    monkeypatch.setattr(
        client,
        "_query",
        lambda _soql: pytest.fail("unapproved sender selection reached Salesforce"),
    )

    with pytest.raises(SalesforceScopeError, match="not approved"):
        client._resolve_department_sender("darius")
    with pytest.raises(
        SalesforceScopeError,
        match="inbound_email_message_id must be a Salesforce record id",
    ):
        client._resolve_direct_darius_reply_sender(
            ticket_id="a0G000000000001AAA",
            inbound_email_message_id="",
            recipient="customer@example.com",
            lane="direct_codex",
        )


@pytest.mark.parametrize(
    "records",
    [
        [],
        [
            {
                "Id": "0D2000000000001AAA",
                "Address": SUPPORT_ORG_WIDE_EMAIL_ADDRESS,
                "IsAllowAllProfiles": True,
            },
            {
                "Id": "0D2000000000002AAA",
                "Address": SUPPORT_ORG_WIDE_EMAIL_ADDRESS,
                "IsAllowAllProfiles": True,
            },
        ],
    ],
)
def test_department_sender_resolution_rejects_missing_or_ambiguous(monkeypatch, records):
    client = _client()
    monkeypatch.setattr(client, "_query", lambda _soql: {"records": records})

    with pytest.raises(SalesforceUnavailableError, match="did not resolve uniquely"):
        client._resolve_department_sender("support")


def test_department_sender_resolution_rejects_profile_restricted_address(monkeypatch):
    client = _client()
    monkeypatch.setattr(
        client,
        "_query",
        lambda _soql: {
            "records": [
                {
                    "Id": "0D2000000000001AAA",
                    "Address": BILLING_ORG_WIDE_EMAIL_ADDRESS,
                    "IsAllowAllProfiles": False,
                }
            ]
        },
    )

    with pytest.raises(SalesforceUnavailableError, match="not available"):
        client._resolve_department_sender("billing")


def test_duplicate_matching_requires_expected_from_address(monkeypatch):
    client = _client()
    ticket_id = "a0G000000000000AAA"
    base = {
        "Subject": "NovaPOS Billing Inquiry Update",
        "ToAddress": "customer@example.com",
        "TextBody": "The bounded verified update fragment appears here.",
        "Incoming": False,
        "Status": "3",
    }
    monkeypatch.setattr(
        client,
        "_ticket_email_records",
        lambda *_args, **_kwargs: [
            {**base, "Id": "02s000000000001AAA", "FromAddress": "darius@novapointofsale.com"},
            {
                **base,
                "Id": "02s000000000002AAA",
                "FromAddress": BILLING_ORG_WIDE_EMAIL_ADDRESS,
            },
        ],
    )

    match = client._matching_ticket_template_email(
        ticket_id,
        recipient="customer@example.com",
        subject="NovaPOS Billing Inquiry Update",
        required_fragments=["bounded verified update fragment"],
        expected_from_address=BILLING_ORG_WIDE_EMAIL_ADDRESS,
    )

    assert match["Id"] == "02s000000000002AAA"


def test_post_send_readback_rejects_wrong_from_address(monkeypatch):
    client = _client()
    ticket_id = "a0G000000000000AAA"
    recipient = "customer@example.com"
    provider_called = {"value": False}

    def fake_request(method, path, *, params=None, json=None):
        assert method == "POST"
        assert path == "/actions/standard/emailSimple"
        provider_called["value"] = True
        return [{"actionName": "emailSimple", "errors": None, "isSuccess": True}]

    def fake_match(
        matched_ticket_id,
        *,
        recipient,
        subject,
        required_fragments,
        expected_from_address,
    ):
        if not provider_called["value"]:
            return None
        return {
            "Id": "02s000000000009AAA",
            "Subject": subject,
            "ToAddress": recipient,
            "TextBody": "The verified update fragment appears here.",
            "Incoming": False,
            "Status": "3",
            "RelatedToId": matched_ticket_id,
            "FromAddress": "darius@novapointofsale.com",
        }

    monkeypatch.setattr(client, "_request", fake_request)
    monkeypatch.setattr(client, "_matching_ticket_template_email", fake_match)
    prepared = {
        "ticketId": ticket_id,
        "subject": "NovaPOS Billing Inquiry Update",
        "templateId": "00X000000000001AAA",
        "renderedPreview": {
            "htmlBody": "<p>The verified update fragment appears here.</p>",
            "plainTextBody": "The verified update fragment appears here.",
        },
        "targets": {
            "accountId": "001000000000001AAA",
            "primaryContactId": "003000000000001AAA",
            "primaryRecipient": recipient,
            "primarySendContactId": "003000000000001AAA",
            "additionalRecipients": [],
            "recipients": [recipient],
        },
        "sender": {
            "department": "billing",
            "address": BILLING_ORG_WIDE_EMAIL_ADDRESS,
            "senderType": "OrgWideEmailAddress",
            "senderPolicy": "department_org_wide",
        },
        "requiredFragments": ["verified update fragment"],
        "customized": True,
    }

    with pytest.raises(
        SalesforceUnavailableError,
        match="FromAddress did not match department sender policy",
    ):
        client._deliver_approved_ticket_template(prepared)


def test_billing_inquiry_template_inserts_only_update_and_preserves_letterhead(
    monkeypatch,
    tmp_path,
):
    client = _client(tmp_path / "salesforce-operations.jsonl")
    sent = {"value": False}
    provider = {}
    ticket_id = "a0G000000000000AAA"
    contact_id = "003000000000000AAA"
    account_id = "001000000000000AAA"
    message = "The duplicate charge was refunded and the invoice now has no amount due."
    monkeypatch.setattr(client, "_assert_ticket_scope", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        client,
        "read_ticket",
        lambda _ticket_id: {
            "ok": True,
            "record": {
                "Contact__c": contact_id,
                "Account__c": account_id,
            },
        },
    )
    def fake_request(method, path, *, params=None, json=None):
        if method == "GET" and path == f"/sobjects/Contact/{contact_id}":
            return {"Id": contact_id, "Email": "customer@example.com"}
        if method == "POST" and path == "/actions/standard/emailSimple":
            provider["payload"] = json
            sent["value"] = True
            return [{"actionName": "emailSimple", "errors": None, "isSuccess": True}]
        raise AssertionError((method, path))

    monkeypatch.setattr(client, "_request", fake_request)

    def fake_query(soql):
        if "FROM Account" in soql:
            return {"records": [{"Id": account_id, "Name": "Customer Account"}]}
        raise AssertionError(soql)

    monkeypatch.setattr(client, "_query", fake_query)
    monkeypatch.setattr(
        client,
        "_resolve_approved_email_template",
        lambda _situation, **_kwargs: {
            "templateId": "00X000000000001AAA",
            "templateName": "NovaPOS Billing Inquiry Update",
            "templateDeveloperName": "NovaPOS_Billing_Inquiry_Update",
            "subject": "NovaPOS Billing Inquiry Update",
            "brandTemplateId": "016A0000000ChpTIAS",
        },
    )
    monkeypatch.setattr(
        client,
        "_resolve_department_sender",
        lambda _department: {
            "department": "billing",
            "orgWideEmailAddressId": "0D2000000000001AAA",
            "address": BILLING_ORG_WIDE_EMAIL_ADDRESS,
            "senderType": "OrgWideEmailAddress",
            "senderPolicy": "department_org_wide",
        },
    )
    html = (
        '<body styleInsert="1"><img src="ImageServer">'
        "Hello,<p>[Account Name]</p><p>[Last 4 Digits]</p>"
        f"<p>{BILLING_INQUIRY_MESSAGE_PLACEHOLDER}</p>"
        "The Nova Support Team billing@novapointofsale.com</body>"
    )
    plain = (
        "Hello,\n[Account Name]\n[Last 4 Digits]\n"
        f"{BILLING_INQUIRY_MESSAGE_PLACEHOLDER}\n"
        "The Nova Support Team\nbilling@novapointofsale.com"
    )
    monkeypatch.setattr(
        client,
        "_render_stored_email_template",
        lambda **_kwargs: {
            "subject": "NovaPOS Billing Inquiry Update",
            "htmlBody": html,
            "plainTextBody": plain,
        },
    )
    monkeypatch.setattr(
        client,
        "_matching_ticket_template_email",
        lambda ticket_id, *, recipient, subject, required_fragments, expected_from_address: (
            {
                "Id": "02s000000000002AAA",
                "Subject": subject,
                "ToAddress": recipient,
                "TextBody": " ".join(required_fragments),
                "Incoming": False,
                "Status": "3",
                "RelatedToId": ticket_id,
                "FromAddress": expected_from_address,
            }
            if sent["value"]
            else None
        ),
    )

    preview = client.preview_ticket_template_email(
        ticket_id=ticket_id,
        situation="billing_inquiry_update",
        details={"last4Digits": "2828", "message": message},
    )
    result = client.send_ticket_template_email(
        ticket_id=ticket_id,
        situation="billing_inquiry_update",
        details={"last4Digits": "2828", "message": message},
    )
    replay = client.send_ticket_template_email(
        ticket_id=ticket_id,
        situation="billing_inquiry_update",
        details={"last4Digits": "2828", "message": message},
    )

    assert preview["sent"] is False
    assert "Customer Account" in preview["plainTextBody"]
    assert "2828" in preview["plainTextBody"]
    assert preview["plainTextBody"].count(message) == 1
    assert "[Account Name]" not in preview["plainTextBody"]
    inputs = provider["payload"]["inputs"][0]
    assert inputs["recipientId"] == contact_id
    assert inputs["emailSubject"] == "NovaPOS Billing Inquiry Update"
    assert inputs["senderType"] == "OrgWideEmailAddress"
    assert inputs["senderAddress"] == BILLING_ORG_WIDE_EMAIL_ADDRESS
    assert "styleInsert" in inputs["emailBody"]
    assert "ImageServer" in inputs["emailBody"]
    assert "emailTemplateId" not in inputs
    assert result["sent"] is True
    assert result["deliveryVerified"] is True
    assert result["fromAddress"] == BILLING_ORG_WIDE_EMAIL_ADDRESS
    assert result["freehandBodyAccepted"] is False
    assert result["replayed"] is False
    assert replay["sent"] is False
    assert replay["duplicate"] is True
    assert replay["replayed"] is True
    assert replay["idempotencyKey"] == result["idempotencyKey"]


def test_support_one_off_preview_uses_fixed_template_recipient_and_team_signature(
    monkeypatch,
):
    client = _client()
    ticket_id = "a0G000000000000AAA"
    contact_id = "003000000000000AAA"
    message = (
        "We added the ability to print the refund policy. Please install this update "
        "on every location computer: "
        "https://pos.novapointofsale.com/novapos/Alpha-Smart-Discount/setup.exe"
    )
    monkeypatch.setattr(client, "_assert_ticket_scope", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        client,
        "read_ticket",
        lambda _ticket_id: {
            "ok": True,
            "record": {
                "Id": ticket_id,
                "Contact__c": contact_id,
                "Account__c": "001000000000000AAA",
            },
        },
    )
    monkeypatch.setattr(
        client,
        "_ticket_contact_template_targets",
        lambda _ticket: {
            "accountId": "001000000000000AAA",
            "accountName": "Fragrance Appeal",
            "primaryContactId": contact_id,
            "primaryRecipient": "jay@example.com",
            "primarySendContactId": contact_id,
            "renderContactId": contact_id,
            "additionalRecipients": [],
            "recipients": ["jay@example.com"],
        },
    )
    monkeypatch.setattr(
        client,
        "_resolve_approved_email_template",
        lambda _situation, **_kwargs: {
            "templateId": "00X000000000099AAA",
            "templateName": SUPPORT_ONE_OFF_TEMPLATE_NAME,
            "templateDeveloperName": SUPPORT_ONE_OFF_TEMPLATE_DEVELOPER_NAME,
            "subject": SUPPORT_ONE_OFF_TEMPLATE_SUBJECT,
            "brandTemplateId": "016A0000000ChpTIAS",
        },
    )
    monkeypatch.setattr(
        client,
        "_resolve_department_sender",
        lambda _department: {
            "department": "support",
            "orgWideEmailAddressId": "0D2000000000001AAA",
            "address": SUPPORT_ORG_WIDE_EMAIL_ADDRESS,
            "senderType": "OrgWideEmailAddress",
            "senderPolicy": "department_org_wide",
        },
    )
    monkeypatch.setattr(
        client,
        "_render_stored_email_template",
        lambda **_kwargs: {
            "subject": SUPPORT_ONE_OFF_TEMPLATE_SUBJECT,
            "htmlBody": (
                '<body styleInsert="1"><img src="ImageServer">Hello Jay,<p>'
                f"{SUPPORT_ONE_OFF_MESSAGE_PLACEHOLDER}</p>Thank you,<br>Izhak Musli</body>"
            ),
            "plainTextBody": (
                "Hello Jay,\n\n"
                f"{SUPPORT_ONE_OFF_MESSAGE_PLACEHOLDER}\n\n"
                "Thank you,\nIzhak Musli"
            ),
        },
    )

    result = client.preview_ticket_template_email(
        ticket_id=ticket_id,
        situation="support_one_off_message",
        details={"message": message},
        lane="tickets_agent",
    )

    assert result["sent"] is False
    assert result["writesPerformed"] is False
    assert result["subject"] == SUPPORT_ONE_OFF_TEMPLATE_SUBJECT
    assert result["primaryRecipient"] == "jay@example.com"
    assert result["fromAddress"] == SUPPORT_ORG_WIDE_EMAIL_ADDRESS
    assert result["plainTextBody"].count(message) == 1
    assert result["plainTextBody"].count("Nova Point of Sale Support") == 1
    assert "Izhak Musli" not in result["plainTextBody"]
    assert SUPPORT_ONE_OFF_MESSAGE_PLACEHOLDER not in result["plainTextBody"]


@pytest.mark.parametrize(
    "message",
    [
        "Hello Jay, the update is ready.",
        "The update is ready. Thank you, Izhak Musli",
        "Please email person@example.com for help.",
        "Install <strong>this update</strong>.",
        "Install https://example.com/setup.exe on each computer.",
        "Install http://pos.novapointofsale.com/setup.exe on each computer.",
        "The value is {!Contact.FirstName}.",
    ],
)
def test_support_one_off_message_rejects_wrapper_html_email_and_unapproved_links(message):
    with pytest.raises(SalesforceScopeError):
        _bounded_support_one_off_message(message)


def test_support_one_off_message_allows_nova_owned_https_download():
    message = (
        "Install the update on each location computer: "
        "https://pos.novapointofsale.com/novapos/Alpha-Smart-Discount/setup.exe"
    )
    assert _bounded_support_one_off_message(message) == message


def test_general_template_send_serializes_concurrent_identical_retries(
    monkeypatch,
    tmp_path,
):
    client = _client(tmp_path / "salesforce-operations.jsonl")
    recipient = "customer@example.com"
    prepared = {
        "ticketId": "a0G000000000000AAA",
        "situation": "billing_inquiry_update",
        "templateId": "00X000000000001AAA",
        "templateName": "NovaPOS Billing Inquiry Update",
        "templateDeveloperName": "NovaPOS_Billing_Inquiry_Update",
        "subject": "NovaPOS Billing Inquiry Update",
        "brandTemplateId": "016A0000000ChpTIAS",
        "renderedPreview": {
            "subject": "NovaPOS Billing Inquiry Update",
            "htmlBody": "<p>A verified update.</p>",
            "plainTextBody": "A verified update.",
        },
        "previewSummary": {
            "verified": True,
            "htmlSha256": hashlib.sha256(b"html").hexdigest(),
            "plainTextSha256": hashlib.sha256(b"plain").hexdigest(),
        },
        "targets": {
            "accountId": "001000000000001AAA",
            "primaryContactId": "003000000000001AAA",
            "primaryRecipient": recipient,
            "primarySendContactId": "003000000000001AAA",
            "additionalRecipients": [],
            "recipients": [recipient],
        },
        "sender": {
            "department": "billing",
            "address": BILLING_ORG_WIDE_EMAIL_ADDRESS,
            "senderType": "OrgWideEmailAddress",
            "senderPolicy": "department_org_wide",
        },
        "requiredFragments": ["verified update"],
        "customized": True,
    }
    calls = {"count": 0}
    calls_lock = Lock()
    start = Barrier(2)

    monkeypatch.setattr(
        client,
        "_prepare_ticket_template_email",
        lambda **_kwargs: prepared,
    )

    def fake_delivery(_prepared, **_kwargs):
        with calls_lock:
            calls["count"] += 1
        time.sleep(0.05)
        return {
            "ok": True,
            "accepted": True,
            "sent": True,
            "duplicate": False,
            "verified": True,
            "deliveryVerified": True,
            "ticketId": prepared["ticketId"],
            "recipients": [recipient],
            "fromAddress": BILLING_ORG_WIDE_EMAIL_ADDRESS,
        }

    monkeypatch.setattr(client, "_deliver_approved_ticket_template", fake_delivery)

    def send():
        start.wait()
        return client.send_ticket_template_email(
            ticket_id=prepared["ticketId"],
            situation=prepared["situation"],
            details={"last4Digits": "2828", "message": "A verified update."},
            lane="billing_agent",
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _index: send(), range(2)))

    assert calls["count"] == 1
    assert sum(result["sent"] is True for result in results) == 1
    assert sum(result["replayed"] is True for result in results) == 1
    assert {result["idempotencyKey"] for result in results} == {
        results[0]["idempotencyKey"]
    }


def test_freehand_ticket_email_is_rejected_without_network():
    with pytest.raises(SalesforceScopeError, match="Freehand Salesforce ticket email is disabled"):
        _client().send_ticket_email(
            ticket_id="a0G000000000000AAA",
            subject="Unapproved subject",
            body="Unapproved body",
        )


def test_billing_inquiry_insert_rejects_duplicated_template_details(monkeypatch):
    client = _client()
    monkeypatch.setattr(client, "_assert_ticket_scope", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        client,
        "read_ticket",
        lambda _ticket_id: {
            "ok": True,
            "record": {
                "Contact__c": "003000000000000AAA",
                "Account__c": "001000000000000AAA",
            },
        },
    )
    monkeypatch.setattr(
        client,
        "_ticket_contact_template_targets",
        lambda _ticket: {
            "accountId": "001000000000000AAA",
            "accountName": "",
            "primaryContactId": "003000000000000AAA",
            "primaryRecipient": "customer@example.com",
            "primarySendContactId": "003000000000000AAA",
            "renderContactId": "003000000000000AAA",
            "additionalRecipients": [],
            "recipients": ["customer@example.com"],
        },
    )
    monkeypatch.setattr(
        client,
        "_resolve_approved_email_template",
        lambda _situation, **_kwargs: {
            "templateId": "00X000000000001AAA",
            "templateName": "NovaPOS Billing Inquiry Update",
            "templateDeveloperName": "NovaPOS_Billing_Inquiry_Update",
            "subject": "NovaPOS Billing Inquiry Update",
            "brandTemplateId": "016A0000000ChpTIAS",
        },
    )
    monkeypatch.setattr(
        client,
        "_resolve_department_sender",
        lambda _department: {
            "department": "billing",
            "orgWideEmailAddressId": "0D2000000000001AAA",
            "address": BILLING_ORG_WIDE_EMAIL_ADDRESS,
            "senderType": "OrgWideEmailAddress",
            "senderPolicy": "department_org_wide",
        },
    )
    monkeypatch.setattr(
        client,
        "_render_stored_email_template",
        lambda **_kwargs: {
            "subject": "NovaPOS Billing Inquiry Update",
            "htmlBody": (
                '<body styleInsert="1"><img src="ImageServer">'
                f"{BILLING_INQUIRY_ACCOUNT_PLACEHOLDER}"
                f"{BILLING_INQUIRY_LAST4_PLACEHOLDER}"
                f"{BILLING_INQUIRY_MESSAGE_PLACEHOLDER}</body>"
            ),
            "plainTextBody": (
                f"{BILLING_INQUIRY_ACCOUNT_PLACEHOLDER}\n"
                f"{BILLING_INQUIRY_LAST4_PLACEHOLDER}\n"
                f"{BILLING_INQUIRY_MESSAGE_PLACEHOLDER}"
            ),
        },
    )
    monkeypatch.setattr(
        client,
        "_query",
        lambda _soql: {
            "records": [{"Id": "001000000000000AAA", "Name": "Customer Account"}]
        },
    )

    with pytest.raises(SalesforceScopeError, match="message must contain only the billing update"):
        client.preview_ticket_template_email(
            ticket_id="a0G000000000000AAA",
            situation="billing_inquiry_update",
            details={
                "last4Digits": "2828",
                "message": "Hi Customer Account, card ending 2828 was updated. Thank you.",
            },
        )


@pytest.mark.parametrize(
    "message",
    [
        "<strong>The account was reviewed.</strong>",
        "Please contact support@novapointofsale.com for the update.",
        "The value is {!Account.Name}.",
        "Regards, Nova Support",
    ],
)
def test_editable_message_validator_rejects_html_tokens_and_signature_boilerplate(message):
    with pytest.raises(SalesforceScopeError):
        _validate_billing_inquiry_insert(
            message,
            account_name="Customer Account",
            last4="2828",
        )


def _stub_ticket_347370_credentials_preview(monkeypatch, client, *, include_evidence=True):
    evidence = (
        "Send credentials only to avi55katz@hotmail.com and cam.a.courtney@gmail.com. "
        "Do not send to realtor@oksanapiven.com or oksanapiven@yahoo.com."
        if include_evidence
        else "Customer requested credentials, but the destination is not recorded."
    )
    monkeypatch.setattr(client, "_assert_ticket_scope", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        client,
        "read_ticket",
        lambda _ticket_id: {
            "ok": True,
            "record": {
                "Id": CREDENTIALS_TICKET_ID,
                "Name": "347370",
                "Contact__c": "003000000000001AAA",
                "Description__c": evidence,
                "Email_Address_to_Send_Ticket__c": "",
                "Notes_Send_To_Client__c": "",
            },
        },
    )
    monkeypatch.setattr(
        client,
        "_resolve_approved_email_template",
        lambda _situation, **_kwargs: {
            "templateId": CREDENTIALS_TEMPLATE_ID,
            "templateName": CREDENTIALS_TEMPLATE_NAME,
            "templateDeveloperName": CREDENTIALS_TEMPLATE_DEVELOPER_NAME,
            "subject": CREDENTIALS_TEMPLATE_SUBJECT,
            "brandTemplateId": "016A0000000ChpTIAS",
        },
    )
    monkeypatch.setattr(
        client,
        "_resolve_department_sender",
        lambda _department: {
            "department": "support",
            "orgWideEmailAddressId": "0D2000000000001AAA",
            "address": SUPPORT_ORG_WIDE_EMAIL_ADDRESS,
            "senderType": "OrgWideEmailAddress",
            "senderPolicy": "department_org_wide",
        },
    )
    monkeypatch.setattr(
        client,
        "_render_stored_email_template",
        lambda **_kwargs: {
            "subject": CREDENTIALS_TEMPLATE_SUBJECT,
            "htmlBody": (
                '<body styleInsert="1"><img src="ImageServer">'
                "Hello Customer, Company Username: classic-shop "
                "Password: SuperSecretCredential "
                "The Nova Support Team support@novapointofsale.com</body>"
            ),
            "plainTextBody": (
                "Hello Customer,\nCompany Username: classic-shop\n"
                "Password: SuperSecretCredential\n"
                "The Nova Support Team\nsupport@novapointofsale.com"
            ),
        },
    )


def test_ticket_347370_sensitive_preview_is_fully_redacted(monkeypatch):
    client = _client()
    _stub_ticket_347370_credentials_preview(monkeypatch, client)

    result = client.preview_ticket_company_credentials_email(
        ticket_id=CREDENTIALS_TICKET_ID,
        requested_recipients=list(reversed(CREDENTIALS_AUTHORIZED_RECIPIENTS)),
        lane="tickets_agent",
        allowed_record_types={"1. NOVA Classic", "2. Nova Wave"},
    )

    serialized = repr(result)
    assert result["recipients"] == list(CREDENTIALS_AUTHORIZED_RECIPIENTS)
    assert result["fromAddress"] == SUPPORT_ORG_WIDE_EMAIL_ADDRESS
    assert result["writesPerformed"] is False
    assert result["credentialMaterialReturned"] is False
    assert result["bodyReturned"] is False
    assert result["fingerprintsReturned"] is False
    for forbidden in (
        "classic-shop",
        "SuperSecretCredential",
        "plainTextBody",
        "htmlBody",
        "Sha256",
        "Length",
    ):
        assert forbidden not in serialized


@pytest.mark.parametrize(
    "requested",
    [
        [CREDENTIALS_AUTHORIZED_RECIPIENTS[0]],
        [
            CREDENTIALS_AUTHORIZED_RECIPIENTS[0],
            next(iter(CREDENTIALS_EXCLUDED_RECIPIENTS)),
        ],
        [
            CREDENTIALS_AUTHORIZED_RECIPIENTS[0],
            "unrequested@example.com",
        ],
    ],
)
def test_ticket_347370_rejects_incomplete_excluded_or_unrequested_recipient_lists(
    monkeypatch,
    requested,
):
    client = _client()
    _stub_ticket_347370_credentials_preview(monkeypatch, client)

    with pytest.raises(SalesforceScopeError, match="requested_recipients"):
        client.preview_ticket_company_credentials_email(
            ticket_id=CREDENTIALS_TICKET_ID,
            requested_recipients=requested,
            lane="tickets_agent",
        )


def test_ticket_347370_requires_positive_recipient_evidence(monkeypatch):
    client = _client()
    _stub_ticket_347370_credentials_preview(
        monkeypatch,
        client,
        include_evidence=False,
    )

    with pytest.raises(SalesforceScopeError, match="positive evidence"):
        client.preview_ticket_company_credentials_email(
            ticket_id=CREDENTIALS_TICKET_ID,
            requested_recipients=list(CREDENTIALS_AUTHORIZED_RECIPIENTS),
            lane="tickets_agent",
        )


def test_ticket_347370_requires_exact_email_tokens_as_recipient_evidence(monkeypatch):
    client = _client()
    _stub_ticket_347370_credentials_preview(monkeypatch, client)
    original_read_ticket = client.read_ticket

    def embedded_evidence(ticket_id):
        result = original_read_ticket(ticket_id)
        record = dict(result["record"])
        record["Description__c"] = "Requested: " + " and ".join(
            f"prefix{recipient}" for recipient in CREDENTIALS_AUTHORIZED_RECIPIENTS
        )
        return {"ok": True, "record": record}

    monkeypatch.setattr(client, "read_ticket", embedded_evidence)

    with pytest.raises(SalesforceScopeError, match="positive evidence"):
        client.preview_ticket_company_credentials_email(
            ticket_id=CREDENTIALS_TICKET_ID,
            requested_recipients=list(CREDENTIALS_AUTHORIZED_RECIPIENTS),
            lane="tickets_agent",
        )


@pytest.mark.parametrize(
    "evidence",
    [
        (
            "Do not send credentials to avi55katz@hotmail.com or "
            "cam.a.courtney@gmail.com."
        ),
        (
            "Credentials are not authorized for avi55katz@hotmail.com and "
            "cam.a.courtney@gmail.com."
        ),
        (
            "Exclude avi55katz@hotmail.com and cam.a.courtney@gmail.com "
            "from credential delivery."
        ),
        (
            "Customer history lists avi55katz@hotmail.com and "
            "cam.a.courtney@gmail.com."
        ),
        (
            "Send credentials to avi55katz@hotmail.com. Do not send credentials "
            "to cam.a.courtney@gmail.com."
        ),
        (
            "Send credentials to avi55katz@hotmail.com and "
            "cam.a.courtney@gmail.com. Correction: do not send credentials "
            "to avi55katz@hotmail.com; send credentials only to "
            "cam.a.courtney@gmail.com."
        ),
        (
            "Do not send credentials to avi55katz@hotmail.com. Correction: "
            "send credentials to avi55katz@hotmail.com and "
            "cam.a.courtney@gmail.com."
        ),
    ],
)
def test_ticket_347370_rejects_negated_or_nonpositive_recipient_evidence(
    monkeypatch,
    evidence,
):
    client = _client()
    _stub_ticket_347370_credentials_preview(monkeypatch, client)
    original_read_ticket = client.read_ticket

    def ticket_with_nonpositive_evidence(ticket_id):
        result = original_read_ticket(ticket_id)
        record = dict(result["record"])
        record["Description__c"] = evidence
        return {"ok": True, "record": record}

    monkeypatch.setattr(client, "read_ticket", ticket_with_nonpositive_evidence)

    with pytest.raises(SalesforceScopeError, match="positive evidence"):
        client.preview_ticket_company_credentials_email(
            ticket_id=CREDENTIALS_TICKET_ID,
            requested_recipients=list(CREDENTIALS_AUTHORIZED_RECIPIENTS),
            lane="tickets_agent",
        )


def test_ticket_347370_send_is_redacted_sender_verified_and_idempotent(
    monkeypatch,
    tmp_path,
):
    client = ScopedSalesforceClient(
        SalesforceSettings(
            "https://example.invalid",
            "https://login.invalid",
            "",
            "",
            "",
            "",
            "token",
            False,
            journal_path=tmp_path / "salesforce-operations.jsonl",
        )
    )
    _stub_ticket_347370_credentials_preview(monkeypatch, client)
    delivery = {"sent": False, "calls": 0, "inputs": []}

    def fake_matching(
        ticket_id,
        *,
        recipient,
        subject,
        expected_from_address,
    ):
        if not delivery["sent"]:
            return None
        return {
            "Id": f"02s-{recipient}",
            "Subject": subject,
            "ToAddress": recipient,
            "FromAddress": expected_from_address,
            "Incoming": False,
            "Status": "3",
            "RelatedToId": ticket_id,
        }

    def fake_request(method, path, *, params=None, json=None):
        assert method == "POST"
        assert path == "/actions/standard/emailSimple"
        delivery["calls"] += 1
        delivery["inputs"] = list(json["inputs"])
        delivery["sent"] = True
        return [
            {"actionName": "emailSimple", "errors": None, "isSuccess": True}
            for _ in json["inputs"]
        ]

    monkeypatch.setattr(client, "_matching_ticket_sensitive_email", fake_matching)
    monkeypatch.setattr(client, "_request", fake_request)

    first = client.send_ticket_company_credentials_email(
        ticket_id=CREDENTIALS_TICKET_ID,
        requested_recipients=list(CREDENTIALS_AUTHORIZED_RECIPIENTS),
        lane="tickets_agent",
    )
    second = client.send_ticket_company_credentials_email(
        ticket_id=CREDENTIALS_TICKET_ID,
        requested_recipients=list(CREDENTIALS_AUTHORIZED_RECIPIENTS),
        lane="tickets_agent",
    )

    assert delivery["calls"] == 1
    assert {
        item["emailAddresses"] for item in delivery["inputs"]
    } == set(CREDENTIALS_AUTHORIZED_RECIPIENTS)
    assert all(
        item["senderType"] == "OrgWideEmailAddress"
        and item["senderAddress"] == SUPPORT_ORG_WIDE_EMAIL_ADDRESS
        and item["relatedRecordId"] == CREDENTIALS_TICKET_ID
        and item["logEmailOnSend"] is True
        for item in delivery["inputs"]
    )
    assert not set(CREDENTIALS_EXCLUDED_RECIPIENTS).intersection(
        item["emailAddresses"] for item in delivery["inputs"]
    )
    assert first["sent"] is True
    assert first["duplicate"] is False
    assert first["fromAddress"] == SUPPORT_ORG_WIDE_EMAIL_ADDRESS
    assert first["deliveryVerified"] is True
    assert second["sent"] is False
    assert second["duplicate"] is True
    for receipt in (first, second):
        serialized = repr(receipt)
        assert "classic-shop" not in serialized
        assert "SuperSecretCredential" not in serialized
        assert "htmlSha256" not in serialized
        assert "plainTextBody" not in serialized
        assert all(
            item["FromAddress"] == SUPPORT_ORG_WIDE_EMAIL_ADDRESS
            for item in receipt["emailMessages"]
        )


def test_ticket_additional_recipients_require_positive_send_evidence():
    result = _verified_ticket_additional_emails(
        {
            "Email_Address_to_Send_Ticket__c": "alternate@example.com",
            "Account_s_Email_Address__c": "primary@example.com",
            "Description__c": (
                "Cancel all service. Notify extra.customer@example.com and "
                "ignore internal@novapointofsale.com."
            ),
            "Notes_Send_To_Client__c": (
                "Customer also requested notice at billing@example.com."
            ),
        },
        exclude={"primary@example.com"},
    )

    assert result == [
        "alternate@example.com",
        "billing@example.com",
        "extra.customer@example.com",
    ]


@pytest.mark.parametrize(
    "ticket",
    [
        {
            "Description__c": (
                "Do not send billing details to wrong.person@example.com."
            )
        },
        {"Description__c": "email@example.com"},
        {"Description__c": "Customer email: alternate@example.com"},
        {"Description__c": "From: quoted.vendor@example.com"},
        {
            "Description__c": (
                "Quoted vendor history: send billing confirmations to "
                "old.vendor@example.com."
            )
        },
        {
            "Description__c": (
                "-----Original Message-----\n"
                "Please send billing statement to old.vendor@example.com."
            )
        },
        {
            "Description__c": (
                "Forwarded message\n"
                "Please send billing statement to old.vendor@example.com."
            )
        },
        {
            "Description__c": (
                "From: Old Vendor\nSent: yesterday\nSubject: Old request\n"
                "Please send billing statement to old.vendor@example.com."
            )
        },
        {
            "Notes_Send_To_Client__c": (
                "Signature\nPlease send billing statement to "
                "signature.address@example.com."
            )
        },
        {
            "Notes_Send_To_Client__c": (
                "Regards,\nEmail: signature.address@example.com"
            )
        },
        {
            "Email_Address_to_Send_Ticket__c": "wrong.person@example.com",
            "Description__c": (
                "Correction: do not send any billing details to "
                "wrong.person@example.com."
            ),
        },
    ],
)
def test_ticket_additional_recipients_reject_negative_history_and_signatures(ticket):
    assert _verified_ticket_additional_emails(ticket) == []


def test_ticket_additional_recipient_exclusion_is_address_specific():
    result = _verified_ticket_additional_emails(
        {
            "Description__c": (
                "Notify approved@example.com and ignore wrong.person@example.com."
            )
        }
    )

    assert result == ["approved@example.com"]


def test_account_cancellation_confirmation_uses_primary_contact_and_ticket_customer_emails(
    monkeypatch,
    tmp_path,
):
    client = _client(tmp_path / "cancellation-email-operations.jsonl")
    ticket_id = "a0G000000000001AAA"
    account_id = "001000000000001AAA"
    primary_contact_id = "003000000000001AAA"
    sent = {"value": False}
    provider_inputs = []
    ticket = {
        "Id": ticket_id,
        "Name": "347191",
        "Account__c": account_id,
        "Description__c": (
            "Cancel all service. Notify extra.customer@example.com and "
            "ignore internal@novapointofsale.com."
        ),
        "Email_Address_to_Send_Ticket__c": "alternate@example.com",
        "Account_s_Email_Address__c": "primary@example.com",
    }
    monkeypatch.setattr(
        client,
        "_assert_account_cancellation_ticket",
        lambda _ticket_id, _account_id: dict(ticket),
    )
    monkeypatch.setattr(
            client,
            "_query",
            lambda soql: (
                {
                    "records": [
                        {
                            "Id": account_id,
                            "Name": "LEJAIM SPA",
                            "Status__c": "Inactive",
                            "NovaPOS_Active__c": 0,
                            "Email_Address__c": "account@example.com",
                            "PrimaryContact__c": primary_contact_id,
                            "PrimaryContact__r": {
                                "Id": primary_contact_id,
                                "Name": "Gerardo Bermea",
                                "FirstName": "Gerardo",
                                "Email": "primary@example.com",
                            },
                        }
                    ]
                }
                if "FROM Account" in soql
                else {
                    "records": [
                        {
                            "Id": "003000000000001AAA",
                            "AccountId": account_id,
                        }
                    ]
                }
                if "FROM Contact" in soql
                else {
                    "records": [
                        {
                            "Id": "00XRc0000083lH7MAI",
                            "Name": "NovaPOS Account Cancellation Confirmed",
                            "DeveloperName": "NovaPOS_Account_Cancellation_Confirmed",
                            "FolderId": "00lA0000001VKQq",
                            "TemplateType": "html",
                            "IsActive": True,
                            "Subject": "Your NOVA POS account has been closed",
                            "BrandTemplateId": "016A0000000ChpTIAS",
                        },
                    ]
                }
                if "FROM EmailTemplate" in soql
                else pytest.fail(soql)
            ),
        )
    monkeypatch.setattr(
        client,
        "read_account_locations",
        lambda _account_id: {
            "records": [
                {
                    "Id": "a0L000000000001AAA",
                    "Location_ID__c": 1,
                    "Status__c": "Inactive",
                    "Chargify_Subscription_ID__c": 8001,
                },
                {
                    "Id": "a0L000000000000AAA",
                    "Name": "Historical Storage",
                    "Location_ID__c": None,
                    "Status__c": "Storage",
                    "Chargify_Subscription_ID__c": None,
                }
            ]
        },
    )
    monkeypatch.setattr(
        client,
        "read_account_orders",
        lambda _account_id: {
            "records": [
                {
                    "Id": "a0O000000000001AAA",
                    "Total_Number_of_Locations_for_this_order__c": -1,
                    "Location_I_D__c": "1",
                    "Chargify_Subscription_ID__c": 8001,
                    "Contract_Name__c": "-1 Location. Billing Automation Order",
                    "Description__c": (
                        "Account cancellation under ticket 347191. Locations: 1. "
                        "Chargify subscription: 8001. "
                        f"Maxio location-component evidence: {'a' * 64}"
                    ),
                }
            ]
        },
    )

    def fake_matching(
        _ticket_id,
        *,
        recipient,
        subject,
        required_fragments,
        expected_from_address,
    ):
        if not sent["value"]:
            return None
        return {
            "Id": f"02s-{recipient}",
            "Subject": subject,
            "ToAddress": recipient,
            "TextBody": " ".join(required_fragments),
            "Incoming": False,
            "Status": "3",
            "RelatedToId": ticket_id,
            "FromAddress": expected_from_address,
        }

    monkeypatch.setattr(client, "_matching_ticket_template_email", fake_matching)
    monkeypatch.setattr(
        client,
        "_resolve_department_sender",
        lambda _department: {
            "department": "billing",
            "orgWideEmailAddressId": "0D2000000000001AAA",
            "address": BILLING_ORG_WIDE_EMAIL_ADDRESS,
            "senderType": "OrgWideEmailAddress",
            "senderPolicy": "department_org_wide",
        },
    )
    monkeypatch.setattr(
        client,
        "_render_stored_email_template",
        lambda **_kwargs: {
            "subject": "Your NOVA POS account has been closed",
            "htmlBody": (
                '<body styleInsert="1"><img src="ImageServer">'
                "Hello Gerardo, This confirms that the NOVA POS account LEJAIM SPA "
                "has been closed as requested. Reference: Ticket 347191 "
                "The Nova Support Team billing@novapointofsale.com</body>"
            ),
            "plainTextBody": (
                "Hello Gerardo,\nThis confirms that the NOVA POS account LEJAIM SPA "
                "has been closed as requested.\nReference: Ticket 347191\n"
                "The Nova Support Team\nbilling@novapointofsale.com"
            ),
        },
    )

    def fake_request(method, path, **kwargs):
            if method == "GET" and path.startswith("/sobjects/NovaPOS_Ticket__c/"):
                return {
                    "Id": ticket_id,
                    "Name": "347191",
                    "Account__c": account_id,
                    "Contact__c": primary_contact_id,
                    "Description__c": (
                        "Cancel all service. Notify extra.customer@example.com and "
                        "ignore internal@novapointofsale.com."
                    ),
                    "Email_Address_to_Send_Ticket__c": "alternate@example.com",
                    "Account_s_Email_Address__c": "primary@example.com",
                }
            assert method == "POST"
            assert path == "/actions/standard/emailSimple"
            provider_inputs.extend(kwargs["json"]["inputs"])
            sent["value"] = True
            return [
                {"actionName": "emailSimple", "errors": None, "isSuccess": True}
                for _ in provider_inputs
            ]

    monkeypatch.setattr(client, "_request", fake_request)

    result = client.send_account_cancellation_confirmation_email(ticket_id, account_id)

    assert result["sent"] is True
    assert result["verified"] is True
    assert result["primaryRecipient"] == "primary@example.com"
    assert result["additionalRecipients"] == [
        "alternate@example.com",
        "extra.customer@example.com",
    ]
    assert result["callerSelectedRecipients"] is False
    assert result["callerSelectedContent"] is False
    assert result["callerSelectedTemplate"] is False
    assert provider_inputs[0]["recipientId"] == primary_contact_id
    assert "emailTemplateId" not in provider_inputs[0]
    assert "emailAddresses" not in provider_inputs[0]
    assert {
        item["emailAddresses"]
        for item in provider_inputs[1:]
    } == {"alternate@example.com", "extra.customer@example.com"}
    assert all(item["relatedRecordId"] == ticket_id for item in provider_inputs)
    assert all(item["logEmailOnSend"] is True for item in provider_inputs)
    assert all(item["senderType"] == "OrgWideEmailAddress" for item in provider_inputs)
    assert all(
        item["senderAddress"] == BILLING_ORG_WIDE_EMAIL_ADDRESS
        for item in provider_inputs
    )
    assert provider_inputs[0]["emailSubject"] == "Your NOVA POS account has been closed"
    assert all(
        "has been closed as requested" in item["emailBody"]
        for item in provider_inputs
    )
    assert all("Nova POS Team" in item["emailBody"] for item in provider_inputs)
    assert all("The Nova Support Team" not in item["emailBody"] for item in provider_inputs)
    assert "internal@novapointofsale.com" not in result["recipients"]
    assert len(result["emailMessages"]) == 3
    assert result["templatePreview"]["letterheadIncluded"] is True
    assert result["fromAddress"] == BILLING_ORG_WIDE_EMAIL_ADDRESS
    assert result["cancellationOrderIds"] == ["a0O000000000001AAA"]
    assert result["cancellationOrderCount"] == 1
    assert result["oneOrderPerSubscriptionVerified"] is True


def test_account_cancellation_confirmation_requires_inactive_account(monkeypatch):
    client = _client()
    monkeypatch.setattr(
        client,
        "_assert_account_cancellation_ticket",
        lambda *_args: {
            "Id": "a0G000000000001AAA",
            "Name": "347191",
            "Account__c": "001000000000001AAA",
            "Description__c": "Cancel account.",
        },
    )
    monkeypatch.setattr(
        client,
        "_query",
        lambda _soql: {
            "records": [
                {
                    "Id": "001000000000001AAA",
                    "Name": "LEJAIM SPA",
                    "Status__c": "Active",
                    "PrimaryContact__c": "003000000000001AAA",
                    "PrimaryContact__r": {
                        "Id": "003000000000001AAA",
                        "Email": "primary@example.com",
                    },
                }
            ]
        },
    )

    with pytest.raises(SalesforceScopeError, match="status Inactive"):
        client.send_account_cancellation_confirmation_email(
            "a0G000000000001AAA",
            "001000000000001AAA",
        )


def test_account_cancellation_confirmation_requires_exact_order_per_subscription(
    monkeypatch,
):
    client = _client()
    ticket_id = "a0G000000000001AAA"
    account_id = "001000000000001AAA"
    monkeypatch.setattr(
        client,
        "_assert_account_cancellation_ticket",
        lambda *_args: {
            "Id": ticket_id,
            "Name": "347191",
            "Account__c": account_id,
            "Description__c": "Cancel account.",
        },
    )
    monkeypatch.setattr(
        client,
        "_query",
        lambda _soql: {
            "records": [
                {
                    "Id": account_id,
                    "Name": "LEJAIM SPA",
                    "Status__c": "Inactive",
                    "PrimaryContact__c": "003000000000001AAA",
                    "PrimaryContact__r": {
                        "Id": "003000000000001AAA",
                        "Email": "primary@example.com",
                    },
                }
            ]
        },
    )
    monkeypatch.setattr(
        client,
        "read_account_locations",
        lambda _account_id: {
            "records": [
                {
                    "Id": "a0L000000000001AAA",
                    "Location_ID__c": 1,
                    "Status__c": "Inactive",
                    "Chargify_Subscription_ID__c": 8001,
                },
                {
                    "Id": "a0L000000000002AAA",
                    "Location_ID__c": 2,
                    "Status__c": "Inactive",
                    "Chargify_Subscription_ID__c": 9002,
                },
            ]
        },
    )
    monkeypatch.setattr(
        client,
        "read_account_orders",
        lambda _account_id: {
            "records": [
                {
                    "Id": "a0O000000000001AAA",
                    "Total_Number_of_Locations_for_this_order__c": -1,
                    "Location_I_D__c": "1",
                    "Chargify_Subscription_ID__c": 8001,
                    "Contract_Name__c": "-1 Location. Billing Automation Order",
                    "Description__c": (
                        "Account cancellation under ticket 347191. Locations: 1. "
                        "Chargify subscription: 8001. "
                        f"Maxio location-component evidence: {'a' * 64}"
                    ),
                },
                {
                    "Id": "a0O000000000002AAA",
                    "Total_Number_of_Locations_for_this_order__c": -1,
                    "Location_I_D__c": "2",
                    "Chargify_Subscription_ID__c": 8001,
                    "Contract_Name__c": "-1 Location. Billing Automation Order",
                    "Description__c": (
                        "Account cancellation under ticket 347191. Locations: 2. "
                        "Chargify subscription: 8001. "
                        f"Maxio location-component evidence: {'b' * 64}"
                    ),
                },
            ]
        },
    )

    with pytest.raises(
        SalesforceScopeError,
        match="subscription grouping was not exact",
    ):
        client.send_account_cancellation_confirmation_email(ticket_id, account_id)


def test_refund_confirmation_email_uses_fixed_template_contact_and_readback(
    monkeypatch,
    tmp_path,
):
    client = _client(tmp_path / "refund-email-operations.jsonl")
    sent = {}
    monkeypatch.setattr(client, "_assert_ticket_scope", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        client,
        "read_ticket",
        lambda _ticket_id: {
            "ok": True,
            "record": {
                "Account__c": "001000000000001AAA",
                "Contact__c": "003000000000009AAA",
                "Description__c": "Customer also requested notice at billing@example.com.",
            },
        },
    )

    def fake_request(method, path, *, params=None, json=None):
        if method == "POST" and path == "/actions/standard/emailSimple":
            sent["payload"] = json
            return [
                {"actionName": "emailSimple", "errors": None, "isSuccess": True}
                for _ in json["inputs"]
            ]
        raise AssertionError((method, path))

    def fake_query(soql):
        if "FROM Account" in soql:
            return {
                "records": [
                    {
                        "Id": "001000000000001AAA",
                        "Name": "Customer Account",
                        "Email_Address__c": "account@example.com",
                        "PrimaryContact__c": "003000000000001AAA",
                        "PrimaryContact__r": {
                            "Id": "003000000000001AAA",
                            "Name": "Primary Contact",
                            "Email": "primary@example.com",
                        },
                    }
                ]
            }
        if "FROM EmailTemplate" in soql:
            assert "A_Refund_was_Submitted" in soql
            return {
                "records": [
                    {
                        "Id": "00X1H000001uw4hUAA",
                        "Name": "A Refund was Submitted",
                        "DeveloperName": "A_Refund_was_Submitted",
                        "FolderId": "00lA0000001VKQq",
                        "TemplateType": "html",
                        "IsActive": True,
                        "Subject": "Your Nova refund has been submitted",
                        "BrandTemplateId": "016A0000000ChpTIAS",
                    }
                ]
            }
        raise AssertionError(soql)

    monkeypatch.setattr(client, "_request", fake_request)
    monkeypatch.setattr(client, "_query", fake_query)
    monkeypatch.setattr(
        client,
        "_resolve_department_sender",
        lambda _department: {
            "department": "billing",
            "orgWideEmailAddressId": "0D2000000000001AAA",
            "address": BILLING_ORG_WIDE_EMAIL_ADDRESS,
            "senderType": "OrgWideEmailAddress",
            "senderPolicy": "department_org_wide",
        },
    )
    monkeypatch.setattr(
        client,
        "_matching_ticket_refund_confirmation",
        lambda ticket_id, *, recipient, subject, expected_amount, expected_from_address: (
            {
                "Id": f"02s-{recipient}",
                "Subject": subject,
                "ToAddress": recipient,
                "TextBody": f"Refund amount: {expected_amount}",
                "Incoming": False,
                "Status": "3",
                "RelatedToId": ticket_id,
                "FromAddress": expected_from_address,
            }
            if sent
            else None
        ),
    )
    monkeypatch.setattr(
        client,
        "_render_stored_email_template",
        lambda **_kwargs: {
            "subject": "Your Nova refund has been submitted",
            "htmlBody": (
                '<body styleInsert="1"><img src="ImageServer">Hello, '
                "Refund amount: $144.99 The Nova Support Team</body>"
            ),
            "plainTextBody": "Hello,\nRefund amount: $144.99\nThe Nova Support Team",
        },
    )

    result = client.send_ticket_refund_confirmation_email(
        ticket_id="a0G000000000000",
        refund_amount_cents=14_499,
        allowed_record_types={"3. Billing"},
    )

    inputs = sent["payload"]["inputs"]
    assert inputs[0] == {
        "recipientId": "003000000000001AAA",
        "emailSubject": "Your Nova refund has been submitted",
        "emailBody": (
            '<body styleInsert="1"><img src="ImageServer">Hello, '
            "Refund amount: $144.99 Nova POS Team</body>"
        ),
        "relatedRecordId": "a0G000000000000",
        "logEmailOnSend": True,
        "senderType": "OrgWideEmailAddress",
        "senderAddress": BILLING_ORG_WIDE_EMAIL_ADDRESS,
    }
    assert inputs[1]["emailAddresses"] == "billing@example.com"
    assert inputs[1]["emailSubject"] == "Your Nova refund has been submitted"
    assert all(item["senderType"] == "OrgWideEmailAddress" for item in inputs)
    assert all(item["senderAddress"] == BILLING_ORG_WIDE_EMAIL_ADDRESS for item in inputs)
    assert "Refund amount: $144.99" in inputs[1]["emailBody"]
    assert result["sent"] is True
    assert result["duplicate"] is False
    assert result["deliveryVerified"] is True
    assert result["refundAmount"] == "$144.99"
    assert result["templatePreview"]["letterheadIncluded"] is True
    assert result["templateDeveloperName"] == "A_Refund_was_Submitted"
    assert result["primaryRecipient"] == "primary@example.com"
    assert result["additionalRecipients"] == ["billing@example.com"]
    assert len(result["emailMessages"]) == 2
    assert result["fromAddress"] == BILLING_ORG_WIDE_EMAIL_ADDRESS


def test_credit_confirmation_requires_matching_ticket_amount_and_fixed_template(
    monkeypatch,
    tmp_path,
):
    client = _client(tmp_path / "credit-email-operations.jsonl")
    sent = {}
    monkeypatch.setattr(client, "_assert_ticket_scope", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        client,
        "read_ticket",
        lambda _ticket_id: {
            "ok": True,
            "record": {
                "Account__c": "001000000000001AAA",
                "Contact__c": "003000000000009AAA",
                "Credit_Amount__c": 20.0,
                "Email_Address_to_Send_Ticket__c": "customer.request@example.com",
            },
        },
    )

    def fake_request(method, path, *, params=None, json=None):
        if method == "POST" and path == "/actions/standard/emailSimple":
            sent["payload"] = json
            return [
                {"actionName": "emailSimple", "errors": None, "isSuccess": True}
                for _ in json["inputs"]
            ]
        raise AssertionError((method, path))

    def fake_query(soql):
        if "FROM Account" in soql:
            return {
                "records": [
                    {
                        "Id": "001000000000001AAA",
                        "Name": "Customer Account",
                        "Email_Address__c": "account@example.com",
                        "PrimaryContact__c": "003000000000001AAA",
                        "PrimaryContact__r": {
                            "Id": "003000000000001AAA",
                            "Name": "Primary Contact",
                            "Email": "primary@example.com",
                        },
                    }
                ]
            }
        if "FROM EmailTemplate" in soql:
            assert "Credit_was_applied_to_your_account" in soql
            return {
                "records": [
                    {
                        "Id": "00XA0000001WukHMAS",
                        "Name": "Credit was applied to your account",
                        "DeveloperName": "Credit_was_applied_to_your_account",
                        "FolderId": "00lA0000001VKQq",
                        "TemplateType": "html",
                        "IsActive": True,
                        "Subject": "Your Nova account credit has been approved",
                        "BrandTemplateId": "016A0000000ChpTIAS",
                    }
                ]
            }
        raise AssertionError(soql)

    monkeypatch.setattr(client, "_request", fake_request)
    monkeypatch.setattr(client, "_query", fake_query)
    monkeypatch.setattr(
        client,
        "_resolve_department_sender",
        lambda _department: {
            "department": "billing",
            "orgWideEmailAddressId": "0D2000000000001AAA",
            "address": BILLING_ORG_WIDE_EMAIL_ADDRESS,
            "senderType": "OrgWideEmailAddress",
            "senderPolicy": "department_org_wide",
        },
    )
    monkeypatch.setattr(
        client,
        "_matching_ticket_refund_confirmation",
        lambda ticket_id, *, recipient, subject, expected_amount, expected_from_address: (
            {
                "Id": f"02s-{recipient}",
                "Subject": subject,
                "ToAddress": recipient,
                "TextBody": f"Credit amount: {expected_amount}",
                "Incoming": False,
                "Status": "3",
                "RelatedToId": ticket_id,
                "FromAddress": expected_from_address,
            }
            if sent
            else None
        ),
    )
    monkeypatch.setattr(
        client,
        "_render_stored_email_template",
        lambda **_kwargs: {
            "subject": "Your Nova account credit has been approved",
            "htmlBody": (
                '<body styleInsert="1"><img src="ImageServer">Hello, '
                "Credit amount: $20.00 The Nova Support Team</body>"
            ),
            "plainTextBody": "Hello,\nCredit amount: $20.00\nThe Nova Support Team",
        },
    )

    result = client.send_ticket_credit_confirmation_email(
        ticket_id="a0G000000000000",
        credit_amount_cents=2_000,
        allowed_record_types={"3. Billing"},
    )

    assert "emailTemplateId" not in sent["payload"]["inputs"][0]
    assert sent["payload"]["inputs"][0]["emailSubject"] == (
        "Your Nova account credit has been approved"
    )
    assert "Nova POS Team" in sent["payload"]["inputs"][0]["emailBody"]
    assert "The Nova Support Team" not in sent["payload"]["inputs"][0]["emailBody"]
    assert sent["payload"]["inputs"][1]["emailAddresses"] == "customer.request@example.com"
    assert all(
        item["senderType"] == "OrgWideEmailAddress"
        and item["senderAddress"] == BILLING_ORG_WIDE_EMAIL_ADDRESS
        for item in sent["payload"]["inputs"]
    )
    assert result["sent"] is True
    assert result["creditAmount"] == "$20.00"
    assert result["templatePreview"]["letterheadIncluded"] is True
    assert result["primaryRecipient"] == "primary@example.com"
    assert result["additionalRecipients"] == ["customer.request@example.com"]
    assert result["fromAddress"] == BILLING_ORG_WIDE_EMAIL_ADDRESS


def test_ticket_closed_by_rep_falls_back_when_ticket_opener_is_not_active(monkeypatch):
    client = _client()
    monkeypatch.setattr(
        client,
        "ticket_scope",
        lambda _ticket_id: {
            "ticketId": "a0G000000000000",
            "recordTypeId": "012000000000000",
            "recordTypeName": "1. NOVA Classic",
        },
    )
    monkeypatch.setattr(client, "_ticket_opener_name", lambda _ticket_id: "Eddie Talal")
    monkeypatch.setattr(
        client,
        "_request",
        lambda method, path, **_kwargs: {
            "values": [
                {"value": "Eddie Talal", "active": False},
                {"value": "Darius Parlor", "active": True},
            ]
        },
    )

    assert (
        client._resolve_ticket_closed_by_rep("a0G000000000000", "")
        == "Darius Parlor"
    )


def test_ticket_closed_by_rep_preserves_an_existing_active_value(monkeypatch):
    client = _client()
    monkeypatch.setattr(
        client,
        "ticket_scope",
        lambda _ticket_id: {
            "ticketId": "a0G000000000000",
            "recordTypeId": "012000000000000",
            "recordTypeName": "1. NOVA Classic",
        },
    )
    monkeypatch.setattr(
        client,
        "_ticket_opener_name",
        lambda _ticket_id: pytest.fail("active existing closure rep should be reused"),
    )
    monkeypatch.setattr(
        client,
        "_request",
        lambda method, path, **_kwargs: {
            "values": [{"value": "Oscar Ocampo", "active": True}]
        },
    )

    assert (
        client._resolve_ticket_closed_by_rep(
            "a0G000000000000",
            "Oscar Ocampo",
        )
        == "Oscar Ocampo"
    )


def test_ticket_closed_by_rep_fails_before_write_without_a_safe_active_value(monkeypatch):
    client = _client()
    monkeypatch.setattr(
        client,
        "ticket_scope",
        lambda _ticket_id: {
            "ticketId": "a0G000000000000",
            "recordTypeId": "012000000000000",
            "recordTypeName": "1. NOVA Classic",
        },
    )
    monkeypatch.setattr(client, "_ticket_opener_name", lambda _ticket_id: "Eddie Talal")
    monkeypatch.setattr(
        client,
        "_request",
        lambda method, path, **_kwargs: {
            "values": [{"value": "Eddie Talal", "active": False}]
        },
    )

    with pytest.raises(SalesforceScopeError, match="No safe active"):
        client._resolve_ticket_closed_by_rep("a0G000000000000", "")


def test_ticket_resolve_closes_then_posts_chatter_without_description_patch(monkeypatch):
    client = _client()
    reads = iter(
        [
            {"Contact__c": "003000000000000", "Description__c": "Original", "Is_Closed__c": False},
            {
                "Contact__c": "003000000000000",
                "Description__c": "Original",
                "Is_Closed__c": True,
                "Ticket_Closed_Date__c": "2026-07-16T18:15:46.000+0000",
            },
        ]
    )
    monkeypatch.setattr(client, "read_ticket", lambda _ticket_id: {"ok": True, "record": next(reads)})
    monkeypatch.setattr(
        client,
        "_resolve_ticket_closed_by_rep",
        lambda *_args, **_kwargs: "Darius Parlor",
    )
    queries = iter(
        [
            {
                "records": [
                    {
                        "Id": "a0G000000000000",
                        "Is_Closed__c": True,
                        "Ticket_Closed_Date__c": "2026-07-16T18:15:46.000+0000",
                        "Ticket_Closed_by_Rep__c": "Darius Parlor",
                    }
                ]
            },
        ]
    )
    monkeypatch.setattr(client, "_query", lambda _soql: next(queries))
    events = []
    monkeypatch.setattr(
        client,
        "post_ticket_chatter",
        lambda *_args, **_kwargs: events.append("chatter")
        or {
            "ok": True,
            "posted": True,
            "duplicate": False,
            "verified": True,
        },
    )
    patched = {}

    def fake_request(method, path, *, params=None, json=None):
        events.append("patch")
        patched.update(method=method, path=path, payload=json)
        return {}

    monkeypatch.setattr(client, "_request", fake_request)

    result = client.resolve_ticket("a0G000000000000", "Resolution complete.")

    assert patched["method"] == "PATCH"
    assert "Description__c" not in patched["payload"]
    assert patched["payload"]["Is_Closed__c"] is True
    assert patched["payload"]["Ticket_Closed_Date__c"].endswith("Z")
    assert patched["payload"]["Ticket_Closed_by_Rep__c"] == "Darius Parlor"
    assert result["closed"] is True
    assert result["resolutionPresent"] is True
    assert result["resolutionSurface"] == "Chatter"
    assert events == ["patch", "chatter"]


def test_ticket_resolve_can_close_without_manufacturing_chatter(monkeypatch):
    client = _client()
    reads = iter(
        [
            {"Is_Closed__c": False},
            {
                "Is_Closed__c": True,
                "Ticket_Closed_Date__c": "2026-08-03T16:00:00.000+0000",
                "Ticket_Closed_by_Rep__c": "Darius Parlor",
            },
        ]
    )
    monkeypatch.setattr(client, "read_ticket", lambda _ticket_id: {"ok": True, "record": next(reads)})
    monkeypatch.setattr(
        client,
        "_resolve_ticket_closed_by_rep",
        lambda *_args, **_kwargs: "Darius Parlor",
    )
    queries = iter(
        [
            {
                "records": [
                    {
                        "Id": "a0G000000000000",
                        "Is_Closed__c": True,
                        "Ticket_Closed_Date__c": "2026-08-03T16:00:00.000+0000",
                        "Ticket_Closed_by_Rep__c": "Darius Parlor",
                    }
                ]
            },
        ]
    )
    monkeypatch.setattr(client, "_query", lambda _soql: next(queries))
    monkeypatch.setattr(
        client,
        "post_ticket_chatter",
        lambda *_args, **_kwargs: pytest.fail("empty closure must not create Chatter"),
    )
    patched = {}
    monkeypatch.setattr(
        client,
        "_request",
        lambda method, path, **kwargs: patched.update(
            method=method,
            path=path,
            payload=kwargs.get("json"),
        )
        or {},
    )

    result = client.resolve_ticket("a0G000000000000", "")

    assert patched["payload"]["Is_Closed__c"] is True
    assert result["closed"] is True
    assert result["updated"] is True
    assert result["resolutionPresent"] is False
    assert result["resolutionSurface"] == "None"
    assert result["chatter"]["omitted"] is True


def test_ticket_resolve_can_reply_to_existing_post_while_closing(monkeypatch):
    client = _client()
    monkeypatch.setattr(
        client,
        "read_ticket_feed",
        lambda *_args, **_kwargs: {
            "ok": True,
            "elements": [{"id": "0D5A00000000001", "body": {"text": "Reader issue"}}],
        },
    )
    reads = iter(
        [
            {"Is_Closed__c": False},
            {
                "Is_Closed__c": True,
                "Ticket_Closed_Date__c": "2026-08-03T16:00:00.000+0000",
                "Ticket_Closed_by_Rep__c": "Darius Parlor",
            },
        ]
    )
    monkeypatch.setattr(client, "read_ticket", lambda _ticket_id: {"ok": True, "record": next(reads)})
    monkeypatch.setattr(
        client,
        "_resolve_ticket_closed_by_rep",
        lambda *_args, **_kwargs: "Darius Parlor",
    )
    queries = iter(
        [
            {
                "records": [
                    {
                        "Id": "a0G000000000000",
                        "Is_Closed__c": True,
                        "Ticket_Closed_Date__c": "2026-08-03T16:00:00.000+0000",
                        "Ticket_Closed_by_Rep__c": "Darius Parlor",
                    }
                ]
            },
        ]
    )
    monkeypatch.setattr(client, "_query", lambda _soql: next(queries))
    monkeypatch.setattr(client, "_request", lambda *_args, **_kwargs: {})
    replies = []
    monkeypatch.setattr(
        client,
        "reply_ticket_chatter",
        lambda ticket_id, feed_element_id, note, **_kwargs: replies.append(
            (ticket_id, feed_element_id, note)
        )
        or {"ok": True, "posted": True, "duplicate": False, "verified": True},
    )
    monkeypatch.setattr(
        client,
        "post_ticket_chatter",
        lambda *_args, **_kwargs: pytest.fail("threaded closure must not post at top level"),
    )

    result = client.resolve_ticket(
        "a0G000000000000",
        "Reader driver updated.",
        reply_to_feed_element_id="0D5A00000000001",
    )

    assert replies == [
        ("a0G000000000000", "0D5A00000000001", "Reader driver updated.")
    ]
    assert result["closed"] is True
    assert result["resolutionPresent"] is True
    assert result["resolutionSurface"] == "ChatterReply"


def test_ticket_resolve_rejects_wrong_reply_parent_before_closing(monkeypatch):
    client = _client()
    monkeypatch.setattr(client, "_assert_ticket_scope", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        client,
        "read_ticket_feed",
        lambda *_args, **_kwargs: {
            "ok": True,
            "elements": [{"id": "0D5A00000000002", "body": {"text": "Different post"}}],
        },
    )
    monkeypatch.setattr(
        client,
        "read_ticket",
        lambda *_args, **_kwargs: pytest.fail("ticket must not close before parent verification"),
    )
    monkeypatch.setattr(
        client,
        "_request",
        lambda *_args, **_kwargs: pytest.fail("ticket must not close before parent verification"),
    )

    with pytest.raises(SalesforceScopeError, match="not found on the specified ticket"):
        client.resolve_ticket(
            "a0G000000000000",
            "Reader driver updated.",
            reply_to_feed_element_id="0D5A00000000001",
        )


def test_ticket_chatter_post_writes_once_and_verifies(monkeypatch):
    client = _client()
    feeds = iter(
        [
            {
                "ok": True,
                "elements": [],
            },
            {
                "ok": True,
                "elements": [
                    {
                        "id": "0D5A00000000001",
                        "body": {
                            "messageSegments": [
                                {"type": "Text", "text": "Verify drivers, then check the reader light."}
                            ]
                        },
                    }
                ],
            },
        ]
    )
    monkeypatch.setattr(client, "_assert_ticket_scope", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(client, "read_ticket_feed", lambda *_args, **_kwargs: next(feeds))
    patched = {}

    def fake_request(method, path, *, params=None, json=None):
        patched.update(method=method, path=path, payload=json)
        return {}

    monkeypatch.setattr(client, "_request", fake_request)

    result = client.post_ticket_chatter(
        "a0G000000000000",
        "Verify drivers, then check the reader light.",
    )

    assert patched["method"] == "POST"
    assert patched["path"] == "/chatter/feed-elements"
    assert patched["payload"] == {
        "body": {
            "messageSegments": [
                {"type": "Text", "text": "Verify drivers, then check the reader light."}
            ]
        },
        "feedElementType": "FeedItem",
        "subjectId": "a0G000000000000",
    }
    assert result["posted"] is True
    assert result["verified"] is True


def test_ticket_chatter_reply_writes_under_verified_parent_and_reads_back(monkeypatch):
    client = _client()
    parent_id = "0D5A00000000001"
    reply_text = "Reader driver updated; reconnect and test one sale."
    feeds = iter(
        [
            {
                "ok": True,
                "elements": [
                    {
                        "id": parent_id,
                        "body": {"text": "The reader still disconnects."},
                        "capabilities": {"comments": {"page": {"items": []}}},
                    }
                ],
            },
            {
                "ok": True,
                "elements": [
                    {
                        "id": parent_id,
                        "body": {"text": "The reader still disconnects."},
                        "capabilities": {
                            "comments": {
                                "page": {
                                    "items": [
                                        {"id": "0D7A00000000001", "body": {"text": reply_text}}
                                    ]
                                }
                            }
                        },
                    }
                ],
            },
        ]
    )
    monkeypatch.setattr(client, "_assert_ticket_scope", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(client, "read_ticket_feed", lambda *_args, **_kwargs: next(feeds))
    posted = {}

    def fake_request(method, path, *, params=None, json=None):
        posted.update(method=method, path=path, payload=json)
        return {"id": "0D7A00000000001"}

    monkeypatch.setattr(client, "_request", fake_request)

    result = client.reply_ticket_chatter(
        "a0G000000000000",
        parent_id,
        reply_text,
    )

    assert posted == {
        "method": "POST",
        "path": f"/chatter/feed-elements/{parent_id}/capabilities/comments/items",
        "payload": {
            "body": {"messageSegments": [{"type": "Text", "text": reply_text}]}
        },
    }
    assert result["posted"] is True
    assert result["verified"] is True
    assert result["parentFeedElementId"] == parent_id


def test_ticket_chatter_reply_rejects_parent_from_another_ticket(monkeypatch):
    client = _client()
    monkeypatch.setattr(client, "_assert_ticket_scope", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        client,
        "read_ticket_feed",
        lambda *_args, **_kwargs: {
            "ok": True,
            "elements": [{"id": "0D5A00000000002", "body": {"text": "Different post"}}],
        },
    )
    monkeypatch.setattr(
        client,
        "_request",
        lambda *_args, **_kwargs: pytest.fail("an unverified parent must not be used"),
    )

    with pytest.raises(SalesforceScopeError, match="not found on the specified ticket"):
        client.reply_ticket_chatter(
            "a0G000000000000",
            "0D5A00000000001",
            "Reader driver updated.",
        )


def test_ticket_chatter_nested_reply_blocks_duplicate_post_or_reply(monkeypatch):
    client = _client()
    parent_id = "0D5A00000000001"
    existing_text = "Reader driver updated."
    feed = {
        "ok": True,
        "elements": [
            {
                "id": parent_id,
                "body": {"text": "The reader still disconnects."},
                "capabilities": {
                    "comments": {
                        "page": {
                            "items": [
                                {"id": "0D7A00000000001", "body": {"text": existing_text}}
                            ]
                        }
                    }
                },
            }
        ],
    }
    monkeypatch.setattr(client, "_assert_ticket_scope", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(client, "read_ticket_feed", lambda *_args, **_kwargs: feed)
    monkeypatch.setattr(
        client,
        "_request",
        lambda *_args, **_kwargs: pytest.fail("duplicate Chatter must not be posted"),
    )

    top_level = client.post_ticket_chatter("a0G000000000000", existing_text)
    nested = client.reply_ticket_chatter(
        "a0G000000000000",
        parent_id,
        existing_text,
    )

    assert top_level["duplicate"] is True
    assert top_level["posted"] is False
    assert nested["duplicate"] is True
    assert nested["posted"] is False


def test_ticket_internal_request_tags_user_and_greets_only_first_message_today(
    tmp_path: Path,
    monkeypatch,
):
    client = _client(
        tmp_path / "salesforce-operations.jsonl",
        internal_communication_journal_path=tmp_path / "internal-requests.jsonl",
    )
    monkeypatch.setattr(client, "_assert_ticket_scope", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        client,
        "_query",
        lambda soql: {
            "records": [
                {
                    "Id": "005000000000001",
                    "Name": "Leo Example",
                    "FirstName": "Leo",
                    "LastName": "Example",
                    "Email": "leo@novapointofsale.com",
                    "IsActive": True,
                }
            ]
        }
        if "FROM User" in soql and "FirstName = 'Leo'" in soql
        else pytest.fail(f"unexpected query: {soql}"),
    )
    posted: list[dict] = []

    def feed(*_args, **_kwargs):
        return {
            "ok": True,
            "elements": [
                {
                    "id": f"0D5A0000000000{index}",
                    "body": {
                        "messageSegments": [
                            (
                                {
                                    "type": "Mention",
                                    "record": {
                                        "id": segment["id"],
                                        "name": "Leo Example",
                                    },
                                }
                                if segment.get("type") == "Mention"
                                else dict(segment)
                            )
                            for segment in payload["body"]["messageSegments"]
                        ]
                    },
                }
                for index, payload in enumerate(posted, start=1)
            ],
        }

    def write(method, path, *, params=None, json=None):
        assert method == "POST"
        assert path == "/chatter/feed-elements"
        posted.append(json)
        return {"id": f"0D5A0000000000{len(posted)}"}

    monkeypatch.setattr(client, "read_ticket_feed", feed)
    monkeypatch.setattr(client, "_request", write)

    first = client.post_ticket_internal_request(
        "a0G000000000000",
        "Leo",
        (
            "Hey Leo, Collagen Aesthetics doesn’t have a card on file and "
            "they’re gonna go inactive again soon."
        ),
        "internal-request-347461-leo-card",
    )
    second = client.post_ticket_internal_request(
        "a0G000000000000",
        "Leo",
        "The customer is ready for the secure payment-method update.",
        "internal-request-347461-leo-followup",
    )
    restored_days: list[str] = []
    monkeypatch.setattr(
        salesforce_client_module,
        "restore_verified_internal_request_day",
        lambda _recipient, **kwargs: restored_days.append(
            kwargs["verified_local_date"]
        )
        or True,
    )
    replay = client.post_ticket_internal_request(
        "a0G000000000000",
        "Leo",
        (
            "Hey Leo, Collagen Aesthetics doesn’t have a card on file and "
            "they’re gonna go inactive again soon."
        ),
        "internal-request-347461-leo-card",
    )

    assert posted[0]["body"]["messageSegments"] == [
        {"type": "Text", "text": "Hey "},
        {"type": "Mention", "id": "005000000000001"},
        {
            "type": "Text",
            "text": (
                ", Collagen Aesthetics doesn’t have a card on file and "
                "they’re gonna go inactive again soon."
            ),
        },
    ]
    assert posted[1]["body"]["messageSegments"] == [
        {"type": "Mention", "id": "005000000000001"},
        {
            "type": "Text",
            "text": " The customer is ready for the secure payment-method update.",
        },
    ]
    assert first["posted"] is True
    assert first["recipient"] == {"name": "Leo Example", "tagged": True}
    assert first["firstMessageGreetingIncluded"] is True
    assert second["firstMessageGreetingIncluded"] is False
    assert replay["posted"] is False
    assert replay["duplicate"] is True
    assert replay["replayed"] is True
    assert restored_days == [first["internalRequestLocalDate"]]
    assert len(posted) == 2


def test_ticket_internal_request_serializes_concurrent_identical_posts(
    tmp_path: Path,
    monkeypatch,
):
    client = _client(
        tmp_path / "salesforce-operations.jsonl",
        internal_communication_journal_path=tmp_path / "internal-requests.jsonl",
    )
    monkeypatch.setattr(client, "_assert_ticket_scope", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        client,
        "_query",
        lambda _soql: {
            "records": [
                {
                    "Id": "005000000000001",
                    "Name": "Leo Example",
                    "FirstName": "Leo",
                    "LastName": "Example",
                    "Email": "leo@novapointofsale.com",
                    "IsActive": True,
                }
            ]
        },
    )
    posted: list[dict] = []
    start = Barrier(2)

    def feed(*_args, **_kwargs):
        return {
            "ok": True,
            "elements": [
                {
                    "id": "0D5A00000000001",
                    "body": {
                        "messageSegments": [
                            {"type": "Text", "text": "Hey "},
                            {
                                "type": "Mention",
                                "record": {
                                    "id": "005000000000001",
                                    "name": "Leo Example",
                                },
                            },
                            {
                                "type": "Text",
                                "text": (
                                    ", Collagen Aesthetics doesn't have a card on "
                                    "file and they're gonna go inactive again soon."
                                ),
                            },
                        ]
                    },
                }
            ]
            if posted
            else [],
        }

    def write(_method, _path, **_kwargs):
        posted.append(_kwargs["json"])
        time.sleep(0.05)
        return {"id": "0D5A00000000001"}

    monkeypatch.setattr(client, "read_ticket_feed", feed)
    monkeypatch.setattr(client, "_request", write)

    def send():
        start.wait()
        return client.post_ticket_internal_request(
            "a0G000000000000",
            "Leo",
            (
                "Collagen Aesthetics doesn't have a card on file and they're "
                "gonna go inactive again soon."
            ),
            "internal-request-347461-leo-concurrent",
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _index: send(), range(2)))

    assert len(posted) == 1
    assert sorted(result["posted"] for result in results) == [False, True]
    assert all(result["verified"] is True for result in results)
    assert sum(result.get("replayed") is True for result in results) == 1
    assert len(
        (tmp_path / "internal-requests.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ) == 1


@pytest.mark.parametrize(
    "records",
    (
        [
            {
                "Id": "005000000000001",
                "Name": "Leo External",
                "FirstName": "Leo",
                "Email": "leo@example.com",
                "IsActive": True,
            }
        ],
        [
            {
                "Id": "005000000000001",
                "Name": "Leo One",
                "FirstName": "Leo",
                "Email": "leo.one@novapointofsale.com",
                "IsActive": True,
            },
            {
                "Id": "005000000000002",
                "Name": "Leo Two",
                "FirstName": "Leo",
                "Email": "leo.two@novapointofsale.com",
                "IsActive": True,
            },
        ],
    ),
)
def test_ticket_internal_request_rejects_external_or_ambiguous_user(
    tmp_path: Path,
    monkeypatch,
    records,
):
    client = _client(
        tmp_path / "salesforce-operations.jsonl",
        internal_communication_journal_path=tmp_path / "internal-requests.jsonl",
    )
    monkeypatch.setattr(client, "_assert_ticket_scope", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(client, "_query", lambda _soql: {"records": records})
    monkeypatch.setattr(
        client,
        "_request",
        lambda *_args, **_kwargs: pytest.fail("an unresolved employee must not be tagged"),
    )

    with pytest.raises(SalesforceScopeError, match="exactly one active Nova"):
        client.post_ticket_internal_request(
            "a0G000000000000",
            "Leo",
            "Please check the account.",
            "internal-request-347461-invalid-user",
        )


@pytest.mark.parametrize(
    "body",
    (
        "Salesforce validation rejected the required closure fields.",
        "EmailMessage 02sRc00000gJQ9wIAG was verified by readback.",
        "The Maxio subscription 93515397 was updated.",
        "The connector lacks permission; please complete the field and close the ticket.",
    ),
)
def test_ticket_chatter_rejects_internal_provider_and_recovery_details(monkeypatch, body):
    client = _client()
    monkeypatch.setattr(client, "_assert_ticket_scope", lambda *_args, **_kwargs: None)

    with pytest.raises(SalesforceScopeError, match="plain customer outcome"):
        client.post_ticket_chatter("a0G000000000000", body)


def test_ticket_chatter_structured_update_focuses_on_cause_resolution_and_next_steps():
    body = ticket_chatter_update_body(
        "Invoice #28779 was recorded under Total External Credit instead of Total Checks.",
        "The refund method was corrected to Total Checks and will appear correctly in the end-of-day report.",
        "Complete and verify the internal billing adjustment.",
    )

    assert body == (
        "Cause: Invoice #28779 was recorded under Total External Credit instead of Total Checks.\n"
        "Resolution: The refund method was corrected to Total Checks and will appear correctly "
        "in the end-of-day report.\n"
        "Next steps: Complete and verify the internal billing adjustment."
    )
    assert "Customer Rachel" not in body
    assert "sentiment" not in body


def test_ticket_chatter_plain_update_posts_only_the_one_new_fact():
    body = ticket_chatter_update_body(update="API pricing email sent.")

    assert body == "API pricing email sent."
    assert "Cause:" not in body
    assert "Resolution:" not in body
    assert "Next steps:" not in body


def test_ticket_chatter_omits_unneeded_structured_sections():
    body = ticket_chatter_update_body(
        resolution="The remaining invoice balance was cleared; nothing is due."
    )

    assert body == "The remaining invoice balance was cleared; nothing is due."


@pytest.mark.parametrize(
    "kwargs",
    (
        {},
        {"cause": "Not yet confirmed."},
        {"resolution": "Not yet resolved."},
        {"next_steps": "No further action is required."},
    ),
)
def test_ticket_chatter_rejects_empty_or_filler_only_updates(kwargs):
    with pytest.raises(SalesforceScopeError, match="new information|net-new"):
        ticket_chatter_update_body(**kwargs)


def test_ticket_chatter_rejects_mixed_plain_and_structured_updates():
    with pytest.raises(SalesforceScopeError, match="cannot be combined"):
        ticket_chatter_update_body(
            resolution="The issue was corrected.",
            update="API pricing email sent.",
        )


# AgentChat/direct_codex 2026-07-31T00:00:00-04:00: keep billing outcomes
# concise while preserving the exact rate, promotion term, and invoice disposition.
def test_ticket_chatter_structured_update_allows_rate_promo_and_refund_outcomes():
    promo = ticket_chatter_update_body(
        "The approved promotion and resulting recurring rate were not fully reflected in billing.",
        "Three months free is active. The recurring rate and Location 1 bill amount are $99.99; "
        "the prior invoice remains under its existing adjustment.",
        "Confirm the first $99.99 renewal.",
    )
    refund = ticket_chatter_update_body(
        "The settled invoice included an amount that was no longer due.",
        "$129.99 was refunded. Invoice: https://novapos.chargifypay.com/invoice/inv_123?token=safe",
        "Allow 5-10 business days for the bank to post the refund.",
    )

    assert "Three months free is active" in promo
    assert "Location 1 bill amount are $99.99" in promo
    assert "https://novapos.chargifypay.com/invoice/inv_123?token=safe" in refund
    assert "Maxio" not in promo
    assert "Salesforce" not in promo
    assert "tool" not in promo.casefold()


@pytest.mark.parametrize(
    "body",
    (
        (
            "Customer Rachel from Forest Hill Cosmetic Clinic needed to change the refund method. "
            "The technician confirmed the change and this left the customer with positive sentiment."
        ),
        "The internal request was created and the customer was satisfied.",
        "Cause: The customer requested a refund-method change.\nResolution: Pending.\nNext steps: Review it.",
    ),
)
def test_ticket_chatter_rejects_ticket_recap_process_narration_and_routine_sentiment(
    monkeypatch,
    body,
):
    client = _client()
    monkeypatch.setattr(client, "_assert_ticket_scope", lambda *_args, **_kwargs: None)

    with pytest.raises(SalesforceScopeError, match="must not repeat the ticket request"):
        client.post_ticket_chatter("a0G000000000000", body)


def test_ticket_chatter_rejects_upset_customer_without_material_handling_change(monkeypatch):
    client = _client()
    monkeypatch.setattr(client, "_assert_ticket_scope", lambda *_args, **_kwargs: None)

    with pytest.raises(SalesforceScopeError, match="materially changes priority or handling"):
        client.post_ticket_chatter(
            "a0G000000000000",
            "Cause: The payment result is inconsistent.\n"
            "Resolution: Not yet resolved.\n"
            "Next steps: Verify the payment state.\n"
            "Priority/handling: The customer was upset.",
        )


def test_ticket_chatter_allows_upset_customer_when_priority_materially_changes():
    body = ticket_chatter_update_body(
        "The payment result is inconsistent.",
        "A second verification still shows the same mismatch.",
        "Verify the payment state and contact the customer today.",
        "The customer was upset, so priority was raised and the issue was escalated to a supervisor.",
    )

    assert "Priority/handling:" in body
    assert "priority was raised" in body


def test_ticket_chatter_strips_redundant_timestamp_before_post(monkeypatch):
    client = _client()
    clean_body = "The account is closed and no amount is due."
    feeds = iter(
        [
            {"ok": True, "elements": []},
            {
                "ok": True,
                "elements": [
                    {
                        "id": "0D5A00000000004",
                        "body": {"text": clean_body},
                    }
                ],
            },
        ]
    )
    monkeypatch.setattr(client, "_assert_ticket_scope", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(client, "read_ticket_feed", lambda *_args, **_kwargs: next(feeds))
    posted = {}
    monkeypatch.setattr(
        client,
        "_request",
        lambda method, path, **kwargs: posted.update(
            method=method,
            path=path,
            payload=kwargs.get("json"),
        )
        or {"id": "0D5A00000000004"},
    )

    result = client.post_ticket_chatter(
        "a0G000000000000",
        f"2026-07-24 21:17:02 UTC — {clean_body}",
    )

    assert posted["payload"]["body"]["messageSegments"][0]["text"] == clean_body
    assert result["verified"] is True


def test_ticket_chatter_allows_refunded_chargify_invoice_link(monkeypatch):
    client = _client()
    body = (
        "The refund is complete and the invoice has no amount due. "
        "https://example.chargify.com/invoices/260583"
    )
    feeds = iter(
        [
            {"ok": True, "elements": []},
            {"ok": True, "elements": [{"id": "0D5A00000000005", "body": {"text": body}}]},
        ]
    )
    monkeypatch.setattr(client, "_assert_ticket_scope", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(client, "read_ticket_feed", lambda *_args, **_kwargs: next(feeds))
    monkeypatch.setattr(client, "_request", lambda *_args, **_kwargs: {"id": "0D5A00000000005"})

    result = client.post_ticket_chatter("a0G000000000000", body)

    assert result["verified"] is True


def test_ticket_chatter_duplicate_matches_salesforce_html_entities(monkeypatch):
    client = _client()
    monkeypatch.setattr(client, "_assert_ticket_scope", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        client,
        "read_ticket_feed",
        lambda *_args, **_kwargs: {
            "ok": True,
            "elements": [
                {
                    "id": "0D5A00000000002",
                    "body": {
                        "messageSegments": [
                            {"type": "Text", "text": "Closed at the operator&#39;s request."}
                        ]
                    },
                }
            ],
        },
    )
    monkeypatch.setattr(
        client,
        "_request",
        lambda *_args, **_kwargs: pytest.fail("duplicate Chatter must not be posted"),
    )

    result = client.post_ticket_chatter(
        "a0G000000000000",
        "Closed at the operator's request.",
    )

    assert result["posted"] is False
    assert result["duplicate"] is True
    assert result["verified"] is True


def test_ticket_chatter_waits_for_eventual_feed_readback(monkeypatch):
    client = _client()
    feeds = iter(
        [
            {"ok": True, "elements": []},
            {"ok": True, "elements": []},
            {
                "ok": True,
                "elements": [
                    {
                        "id": "0D5A00000000003",
                        "body": {"text": "Closed at the operator&#39;s request."},
                    }
                ],
            },
        ]
    )
    monkeypatch.setattr(client, "_assert_ticket_scope", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(client, "read_ticket_feed", lambda *_args, **_kwargs: next(feeds))
    monkeypatch.setattr(client, "_request", lambda *_args, **_kwargs: {"id": "0D5A00000000003"})
    monkeypatch.setattr("scoped_operations_mcp.salesforce_client.time.sleep", lambda _seconds: None)

    result = client.post_ticket_chatter(
        "a0G000000000000",
        "Closed at the operator's request.",
    )

    assert result["posted"] is True
    assert result["verified"] is True


def test_api_customer_email_cohort_enforces_account_location_and_email_filters(monkeypatch):
    client = _client()
    queries = []

    def fake_query(soql):
        queries.append(soql)
        if "FROM Account" in soql:
            return {
                "records": [
                    {
                        "Id": "001000000000001AAA",
                        "Name": "Kento Salon",
                        "Company_Username__c": "Kento",
                        "Email_Address__c": "Owner@Example.com",
                        "recurly__Email__c": "billing@example.com",
                        "NovaPOS_Active__c": 2,
                        "Account_Blocked__c": False,
                        "Database_Deleted__c": False,
                        "Fake_Account__c": False,
                    },
                    {
                        "Id": "001000000000002AAA",
                        "Name": "Second Salon",
                        "Company_Username__c": "Second",
                        "Email_Address__c": "owner@example.com",
                        "recurly__Email__c": "",
                        "NovaPOS_Active__c": 1,
                        "Account_Blocked__c": False,
                        "Database_Deleted__c": False,
                        "Fake_Account__c": False,
                    },
                    {
                        "Id": "001000000000003AAA",
                        "Name": "Inactive Salon",
                        "Company_Username__c": "Inactive",
                        "Email_Address__c": "inactive@example.com",
                        "NovaPOS_Active__c": 0,
                        "Account_Blocked__c": False,
                        "Database_Deleted__c": False,
                        "Fake_Account__c": False,
                    },
                ]
            }
        if "FROM NovaPOS_Location__c" in soql:
            return {
                "records": [
                    {"Account__c": "001000000000001AAA", "activeLocationCount": 2},
                    {"Account__c": "001000000000002AAA", "activeLocationCount": 1},
                ]
            }
        raise AssertionError(soql)

    monkeypatch.setattr(client, "_query", fake_query)
    result = client.api_customer_email_cohort(
        [
            {"companyUsername": "Kento", "databaseName": "POS_Kento", "apiExpirationDate": "2027-01-01"},
            {"companyUsername": "Second", "databaseName": "POS_Second", "apiExpirationDate": "2027-02-01"},
            {"companyUsername": "Inactive", "databaseName": "POS_Inactive", "apiExpirationDate": "2027-03-01"},
        ]
    )

    assert result["verified"] is True
    assert result["eligibleAccountCount"] == 2
    assert result["recipientCount"] == 1
    assert result["recipients"][0]["emailAddress"] == "Owner@Example.com"
    assert len(result["recipients"][0]["accounts"]) == 2
    assert result["exclusions"]["inactiveAccount"] == 1
    assert "Status__c = 'Active'" in queries[1]
    assert "NovaPOS_Active__c" in queries[0]
    assert all("ApiPassword" not in query for query in queries)


def test_ticket_internal_note_legacy_alias_routes_to_chatter(monkeypatch):
    client = _client()
    monkeypatch.setattr(
        client,
        "post_ticket_chatter",
        lambda *_args, **_kwargs: {
            "ok": True,
            "posted": False,
            "duplicate": True,
            "verified": True,
        },
    )

    result = client.update_ticket_internal_note(
        "a0G000000000000",
        "Verify drivers, then check the reader light.",
    )

    assert result["duplicate"] is True
    assert result["verified"] is True
    assert result["field"] == "Chatter"
    assert result["legacyAlias"] is True


def test_ticket_write_record_type_policy_fails_before_patch(monkeypatch):
    client = _client()
    requests = []
    monkeypatch.setattr(
        client,
        "_query",
        lambda _soql: {
            "records": [
                {
                    "Id": "a0G000000000001",
                    "RecordTypeId": "012000000000001",
                    "RecordType": {"Name": "3. Billing"},
                }
            ]
        },
    )
    monkeypatch.setattr(
        client,
        "_request",
        lambda *args, **kwargs: requests.append((args, kwargs)) or {},
    )

    with pytest.raises(SalesforceScopeError, match="outside this agent lane"):
        client.update_ticket(
            "a0G000000000001",
            {"Description__c": "support update"},
            allowed_record_types={"1. NOVA Classic", "2. Nova Wave"},
        )

    assert requests == []


def test_ticket_create_record_type_policy_fails_before_insert(monkeypatch):
    client = _client()
    requests = []
    monkeypatch.setattr(
        client,
        "_query",
        lambda _soql: {
            "records": [
                {
                    "Id": "012000000000001",
                    "Name": "3. Billing",
                    "SObjectType": "NovaPOS_Ticket__c",
                }
            ]
        },
    )
    monkeypatch.setattr(
        client,
        "_request",
        lambda *args, **kwargs: requests.append((args, kwargs)) or {},
    )

    with pytest.raises(SalesforceScopeError, match="outside this agent lane"):
        client.create_ticket(
            account_id="001000000000001",
            description="support ticket",
            record_type_id="012000000000001",
            allowed_record_types={"1. NOVA Classic", "2. Nova Wave"},
        )

    assert requests == []


def test_taylor_support_ticket_create_scope_rejects_billing_before_insert(
    monkeypatch,
    tmp_path,
):
    client = _client(tmp_path / "salesforce-operations.jsonl")
    requests = []
    monkeypatch.setattr(
        client,
        "_query",
        lambda _soql: {
            "records": [
                {
                    "Id": "012000000000001",
                    "Name": "3. Billing",
                    "SObjectType": "NovaPOS_Ticket__c",
                }
            ]
        },
    )
    monkeypatch.setattr(
        client,
        "_request",
        lambda *args, **kwargs: requests.append((args, kwargs)) or {},
    )

    with pytest.raises(SalesforceScopeError, match="outside this agent lane"):
        client.create_support_email_ticket(
            account_id="001000000000001",
            description="Attempted Billing ticket from Taylor.",
            record_type_id="012000000000001",
            source_email_id="message-1",
            source_key="support-email:message-1",
            ticket_created_by="Darius Parlor",
            allowed_record_types=LANE_TICKET_RECORD_TYPES["coding_agent"],
        )

    assert requests == []


def _install_support_email_create_provider(
    monkeypatch,
    client,
    *,
    account_name="Kay's Cafe",
    fake_account=False,
    contact_account_id="001000000000001AAA",
    location_account_id="001000000000001AAA",
    fail_search_once=False,
    fail_ticket_readback_after_post_once=False,
    reject_post_once=False,
    record_type_name="1. NOVA Classic",
):
    account_id = "001000000000001AAA"
    record_type_id = "012000000000001AAA"
    ticket_id = "a0G000000000001AAA"
    state = {
        "ticket": None,
        "postCalls": 0,
        "searchCalls": 0,
        "queries": [],
        "requests": [],
        "failSearchOnce": fail_search_once,
        "failTicketReadbackOnce": fail_ticket_readback_after_post_once,
        "rejectPostOnce": reject_post_once,
        "committedPosts": 0,
    }

    def fake_query(soql):
        state["queries"].append(soql)
        if "FROM RecordType" in soql:
            return {
                "records": [
                    {
                        "Id": record_type_id,
                        "Name": record_type_name,
                        "SObjectType": "NovaPOS_Ticket__c",
                    }
                ]
            }
        if "FROM Account " in soql:
            return {
                "records": [
                    {
                        "Id": account_id,
                        "Name": account_name,
                        "Fake_Account__c": fake_account,
                    }
                ]
            }
        if "FROM Contact " in soql:
            return {
                "records": [
                    {
                        "Id": "003000000000001AAA",
                        "AccountId": contact_account_id,
                    }
                ]
            }
        if "FROM NovaPOS_Location__c " in soql:
            return {
                "records": [
                    {
                        "Id": "a0L000000000001AAA",
                        "Account__c": location_account_id,
                    }
                ]
            }
        if "FROM NovaPOS_Ticket__c " in soql:
            if state["ticket"] is not None and state["failTicketReadbackOnce"]:
                state["failTicketReadbackOnce"] = False
                raise SalesforceUnavailableError("ticket readback unavailable")
            return {
                "records": [dict(state["ticket"])]
                if isinstance(state["ticket"], dict)
                else []
            }
        raise AssertionError(f"Unexpected SOQL: {soql}")

    def fake_request(method, path, *, params=None, json=None):
        state["requests"].append(
            {"method": method, "path": path, "params": params, "json": json}
        )
        if method == "GET" and path.startswith(
            "/ui-api/object-info/NovaPOS_Ticket__c/picklist-values/"
        ):
            return {"values": [{"value": "Darius Parlor", "active": True}]}
        if method == "GET" and path == "/search":
            state["searchCalls"] += 1
            if state["failSearchOnce"]:
                state["failSearchOnce"] = False
                raise SalesforceUnavailableError("source lookup unavailable")
            return {
                "searchRecords": [{"Id": ticket_id}]
                if isinstance(state["ticket"], dict)
                else []
            }
        if method == "POST" and path == "/sobjects/NovaPOS_Ticket__c":
            state["postCalls"] += 1
            if state["rejectPostOnce"]:
                state["rejectPostOnce"] = False
                raise SalesforceDefinitiveRejectionError(
                    400,
                    "definitive provider rejection",
                )
            state["committedPosts"] += 1
            state["ticket"] = {
                "Id": ticket_id,
                "Name": "347314",
                "Account__c": json["Account__c"],
                "Account__r": {
                    "Id": json["Account__c"],
                    "Name": account_name,
                    "Fake_Account__c": fake_account,
                },
                "Contact__c": json.get("Contact__c"),
                "NovaPOS_Location__c": json.get("NovaPOS_Location__c"),
                "RecordTypeId": json["RecordTypeId"],
                "RecordType": {"Name": record_type_name},
                "Is_Closed__c": False,
                "Ticket_Created_by__c": json["Ticket_Created_by__c"],
                "Tech_Main_Issue__c": json.get("Tech_Main_Issue__c"),
                "Technical_Issue__c": json.get("Technical_Issue__c"),
                "Customer_Contact__c": json.get("Customer_Contact__c"),
                "Description__c": json["Description__c"],
            }
            return {"id": ticket_id}
        raise AssertionError(f"Unexpected request: {method} {path}")

    monkeypatch.setattr(client, "_query", fake_query)
    monkeypatch.setattr(client, "_request", fake_request)
    return state


def _create_support_email_ticket(client, **overrides):
    arguments = {
        "account_id": "001000000000001AAA",
        "description": "Register will not complete a sale.",
        "source_email_id": "message-1",
        "source_key": "support-email:message-1",
        "record_type_id": "012000000000001AAA",
        "ticket_created_by": "Darius Parlor",
        "main_issue": "Software",
        "technical_issue": "Other",
        "allowed_record_types": LANE_TICKET_RECORD_TYPES["coding_agent"],
    }
    arguments.update(overrides)
    return client.create_support_email_ticket(**arguments)


def test_support_email_ticket_create_is_journaled_source_keyed_and_read_back(
    monkeypatch,
    tmp_path,
):
    journal = tmp_path / "salesforce-operations.jsonl"
    client = _client(journal)
    state = _install_support_email_create_provider(monkeypatch, client)

    result = _create_support_email_ticket(client)

    assert result["created"] is True
    assert result["verified"] is True
    assert result["accountEligible"] is True
    assert result["ticketCreatedBy"] == "Darius Parlor"
    assert result["sourceKey"] == "support-email:message-1"
    assert result["writesPerformed"] is True
    assert state["postCalls"] == 1
    post = next(
        request
        for request in state["requests"]
        if request["method"] == "POST"
    )
    assert post["json"]["Ticket_Created_by__c"] == "Darius Parlor"
    assert post["json"]["Description__c"] == (
        "Register will not complete a sale."
    )
    assert "Source key:" not in post["json"]["Description__c"]
    assert not any(
        request["path"] == "/search"
        for request in state["requests"]
    )
    comparison = client.verify_support_email_ticket_claim(
        ticket_id=result["ticketId"],
        ticket_number=result["ticketNumber"],
        account_id=result["accountId"],
        record_type=result["recordType"],
        source_key=result["sourceKey"],
        allowed_record_types=LANE_TICKET_RECORD_TYPES["coding_agent"],
    )
    assert comparison["sourceKeyMatches"] is True
    serialized = repr(result)
    journal_text = journal.read_text(encoding="utf-8")
    for forbidden in ("Register will not complete", "Kay's Cafe", "Description__c"):
        assert forbidden not in serialized
        assert forbidden not in journal_text


def test_billing_closure_email_ticket_create_resolves_billing_type_and_reuses_source_namespace(
    monkeypatch,
    tmp_path,
):
    client = _client(tmp_path / "salesforce-operations.jsonl")
    state = _install_support_email_create_provider(
        monkeypatch,
        client,
        record_type_name="3. Billing",
    )

    result = client.create_billing_closure_email_ticket(
        account_id="001000000000001AAA",
        description="Customer requested one location cancellation.",
        source_email_id="message-1",
        source_key="billing-closure-email:message-1",
        ticket_created_by="Darius Parlor",
        location_id="a0L000000000001AAA",
        customer_contact_method="Email",
        allowed_record_types={"3. Billing"},
    )

    assert result["created"] is True
    assert result["verified"] is True
    assert result["recordType"] == "3. Billing"
    assert result["sourceKey"] == "billing-closure-email:message-1"
    assert state["postCalls"] == 1
    post = next(
        request for request in state["requests"] if request["method"] == "POST"
    )
    assert post["json"]["Description__c"] == (
        "Customer requested one location cancellation."
    )
    assert "Source key:" not in post["json"]["Description__c"]


def test_account_cancellation_email_attachment_upload_is_exact_eml_and_cross_lane(
    monkeypatch,
):
    client = _client()
    calls = []
    monkeypatch.setattr(
        client,
        "_assert_account_cancellation_ticket",
        lambda ticket_id, account_id: {
            "Id": ticket_id,
            "Account__c": account_id,
            "RecordType": {"Name": "1. NOVA Classic"},
        },
    )
    monkeypatch.setattr(
        client,
        "upload_ticket_attachment",
        lambda *args, **kwargs: calls.append((args, kwargs))
        or {
            "ok": True,
            "verified": True,
            "uploaded": True,
            "ticketId": args[0],
            "sha256": args[3],
        },
    )

    result = client.upload_account_cancellation_email_attachment(
        "a0G000000000001AAA",
        "001000000000001AAA",
        "billing-close-confirmation-message-1.eml",
        "RnJvbTogY3VzdG9tZXJAZXhhbXBsZS5jb20NCg0KQ2xvc2UgdGhpcyBsb2NhdGlvbi4=",
        "a" * 64,
        idempotency_key="billing-closure-email-attachment:message-1",
    )

    assert result["accountId"] == "001000000000001AAA"
    assert calls[0][0][1].endswith(".eml")
    assert calls[0][1]["allowed_record_types"] == {
        "1. NOVA Classic",
        "2. Nova Wave",
        "3. Billing",
    }
    with pytest.raises(SalesforceScopeError, match="EML"):
        client.upload_account_cancellation_email_attachment(
            "a0G000000000001AAA",
            "001000000000001AAA",
            "confirmation.pdf",
            "JVBERi0xLjQ=",
            "b" * 64,
            idempotency_key="billing-closure-email-attachment:message-2",
        )


def test_support_email_ticket_create_concurrent_replay_posts_once(
    monkeypatch,
    tmp_path,
):
    client = _client(tmp_path / "salesforce-operations.jsonl")
    state = _install_support_email_create_provider(monkeypatch, client)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _value: _create_support_email_ticket(client), range(2)))

    assert state["postCalls"] == 1
    assert all(result["verified"] is True for result in results)
    assert sorted(result["created"] for result in results) == [False, True]
    replay = next(result for result in results if not result["created"])
    assert replay["duplicate"] is True
    assert replay["replayed"] is True
    assert replay["writesPerformed"] is False


def test_support_email_ticket_create_does_not_search_salesforce_for_private_source_key(
    monkeypatch,
    tmp_path,
):
    journal = tmp_path / "salesforce-operations.jsonl"
    client = _client(journal)
    state = _install_support_email_create_provider(
        monkeypatch,
        client,
        fail_search_once=True,
    )

    result = _create_support_email_ticket(client)

    assert result["verified"] is True
    assert state["searchCalls"] == 0
    assert state["postCalls"] == 1
    assert journal.exists()


def test_support_email_ticket_post_success_readback_failure_recovers_without_duplicate(
    monkeypatch,
    tmp_path,
):
    client = _client(tmp_path / "salesforce-operations.jsonl")
    state = _install_support_email_create_provider(
        monkeypatch,
        client,
        fail_ticket_readback_after_post_once=True,
    )

    with pytest.raises(SalesforceUnavailableError, match="ticket readback"):
        _create_support_email_ticket(client)
    recovered = _create_support_email_ticket(client)

    assert state["postCalls"] == 1
    assert recovered["verified"] is True
    assert recovered["created"] is False
    assert recovered["duplicate"] is True
    assert recovered["replayed"] is True


def test_support_email_ticket_pending_recovery_rejects_description_reclassification(
    monkeypatch,
    tmp_path,
):
    client = _client(tmp_path / "salesforce-operations.jsonl")
    state = _install_support_email_create_provider(
        monkeypatch,
        client,
        fail_ticket_readback_after_post_once=True,
    )

    with pytest.raises(SalesforceUnavailableError, match="ticket readback"):
        _create_support_email_ticket(
            client,
            description="Initial support-email classification.",
        )
    with pytest.raises(
        SalesforceUnavailableError,
        match="live readback did not match",
    ):
        _create_support_email_ticket(
            client,
            description="Corrected support-email classification.",
        )

    assert state["postCalls"] == 1


def test_support_email_ticket_abandoned_prewrite_plan_can_be_corrected(
    monkeypatch,
    tmp_path,
):
    journal = tmp_path / "salesforce-operations.jsonl"
    client = _client(journal)
    state = _install_support_email_create_provider(monkeypatch, client)
    source_key = "support-email:message-1"
    idempotency_key = (
        "support-email-ticket-create:"
        + hashlib.sha256(source_key.encode("utf-8")).hexdigest()[:32]
    )
    client._journal_salesforce_operation(
        "pending",
        idempotency_key,
        "support_email_ticket_create",
        source_key,
        "a" * 64,
        {"postAttempted": False},
    )

    recovered = _create_support_email_ticket(
        client,
        description="Corrected pre-write support-email classification.",
    )

    assert recovered["created"] is True
    assert recovered["verified"] is True
    assert state["postCalls"] == 1


def test_support_email_ticket_old_unknown_post_requires_review_not_endless_retry(
    monkeypatch,
    tmp_path,
):
    journal = tmp_path / "salesforce-operations.jsonl"
    client = _client(journal)
    state = _install_support_email_create_provider(monkeypatch, client)
    source_key = "support-email:message-1"
    idempotency_key = (
        "support-email-ticket-create:"
        + hashlib.sha256(source_key.encode("utf-8")).hexdigest()[:32]
    )
    journal.write_text(
        json.dumps(
            {
                "time": int(time.time()) - 901,
                "status": "pending",
                "idempotencyKey": idempotency_key,
                "operation": "support_email_ticket_create",
                "target": source_key,
                "planHash": "a" * 64,
                "evidence": {"postAttempted": True},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    result = _create_support_email_ticket(client)

    assert result["status"] == "uncertain"
    assert result["retryable"] is False
    assert result["requiresReview"] is True
    assert result["retryAfterSeconds"] == 0
    assert result["reasonCode"] == "post_outcome_plan_changed"
    assert state["searchCalls"] == 0
    assert state["postCalls"] == 0


def test_support_email_ticket_definitive_rejection_is_retryable_without_uncertain_pending(
    monkeypatch,
    tmp_path,
):
    client = _client(tmp_path / "salesforce-operations.jsonl")
    state = _install_support_email_create_provider(
        monkeypatch,
        client,
        reject_post_once=True,
    )

    rejected = _create_support_email_ticket(client)
    recovered = _create_support_email_ticket(client)

    assert rejected["status"] == "rejected"
    assert rejected["retryable"] is True
    assert rejected["reasonCode"] == "provider_rejected_no_commit"
    assert rejected["writesPerformed"] is False
    assert recovered["verified"] is True
    assert recovered["created"] is True
    assert state["postCalls"] == 2
    assert state["committedPosts"] == 1


@pytest.mark.parametrize(
    ("account_name", "fake_account"),
    [
        ("Demo Nova Cafe", False),
        ("Customer fallback", False),
        ("Template Shop", False),
        ("Kay's Cafe", True),
    ],
)
def test_support_email_ticket_create_rejects_provider_ineligible_account_before_write(
    monkeypatch,
    tmp_path,
    account_name,
    fake_account,
):
    client = _client(tmp_path / "salesforce-operations.jsonl")
    state = _install_support_email_create_provider(
        monkeypatch,
        client,
        account_name=account_name,
        fake_account=fake_account,
    )

    with pytest.raises(SalesforceScopeError, match="Account is not eligible"):
        _create_support_email_ticket(client)

    assert state["postCalls"] == 0


@pytest.mark.parametrize(
    ("field", "value", "provider_kwargs"),
    [
        (
            "contact_id",
            "003000000000001AAA",
            {"contact_account_id": "001000000000999AAA"},
        ),
        (
            "location_id",
            "a0L000000000001AAA",
            {"location_account_id": "001000000000999AAA"},
        ),
    ],
)
def test_support_email_ticket_create_rejects_cross_account_contact_or_location(
    monkeypatch,
    tmp_path,
    field,
    value,
    provider_kwargs,
):
    client = _client(tmp_path / "salesforce-operations.jsonl")
    state = _install_support_email_create_provider(
        monkeypatch,
        client,
        **provider_kwargs,
    )

    with pytest.raises(SalesforceScopeError, match="not linked"):
        _create_support_email_ticket(client, **{field: value})

    assert state["postCalls"] == 0


def test_support_email_ticket_create_rejects_caller_source_marker_before_provider(
    monkeypatch,
    tmp_path,
):
    client = _client(tmp_path / "salesforce-operations.jsonl")
    calls = []
    monkeypatch.setattr(client, "_query", lambda *_args: calls.append("query"))
    monkeypatch.setattr(client, "_request", lambda *_args, **_kwargs: calls.append("request"))

    with pytest.raises(SalesforceScopeError, match="must not contain a Source key"):
        _create_support_email_ticket(
            client,
            description="Register issue\nSource key: support-email:attacker",
        )

    assert calls == []


def test_support_email_ticket_source_id_boundary_matches_journal_target(
    monkeypatch,
    tmp_path,
):
    client = _client(tmp_path / "salesforce-operations.jsonl")
    state = _install_support_email_create_provider(monkeypatch, client)
    source_email_id = "x" * 186
    source_key = f"support-email:{source_email_id}"

    result = _create_support_email_ticket(
        client,
        source_email_id=source_email_id,
        source_key=source_key,
    )

    assert len(source_key) == 200
    assert result["sourceKey"] == source_key
    assert result["verified"] is True
    assert state["postCalls"] == 1

    calls = []
    invalid = _client(tmp_path / "invalid-operations.jsonl")
    monkeypatch.setattr(invalid, "_query", lambda *_args: calls.append("query"))
    monkeypatch.setattr(
        invalid,
        "_request",
        lambda *_args, **_kwargs: calls.append("request"),
    )
    too_long_id = "x" * 187
    with pytest.raises(SalesforceScopeError, match="source_email_id is invalid"):
        _create_support_email_ticket(
            invalid,
            source_email_id=too_long_id,
            source_key=f"support-email:{too_long_id}",
        )
    assert calls == []


def test_support_email_ticket_readback_rejects_description_mutation():
    client = object.__new__(ScopedSalesforceClient)
    expected = {
        "accountId": "001000000000001AAA",
        "contactId": "",
        "locationId": "",
        "recordTypeId": "012000000000001AAA",
        "recordType": "1. NOVA Classic",
        "mainIssue": "Software",
        "technicalIssue": "Other",
        "customerContactMethod": "",
        "ticketCreatedBy": "Darius Parlor",
        "accountEligible": True,
        "sourceEmailId": "message-1",
        "sourceKey": "support-email:message-1",
        "description": "Register issue",
    }
    record = {
        "Id": "a0G000000000001AAA",
        "Name": "347314",
        "Account__c": expected["accountId"],
        "Account__r": {
            "Id": expected["accountId"],
            "Name": "Kay's Cafe",
            "Fake_Account__c": False,
        },
        "RecordTypeId": expected["recordTypeId"],
        "RecordType": {"Name": expected["recordType"]},
        "Is_Closed__c": False,
        "Ticket_Created_by__c": expected["ticketCreatedBy"],
        "Tech_Main_Issue__c": expected["mainIssue"],
        "Technical_Issue__c": expected["technicalIssue"],
        "Description__c": (
            "Register issue\n"
            "Source key: support-email:message-1\n"
            "Source key: support-email:message-2"
        ),
    }

    receipt = client._support_email_ticket_creation_receipt(
        record,
        expected=expected,
    )

    assert receipt["verified"] is False
    assert "description" in receipt["mismatchFields"]


def test_support_email_ticket_readback_accepts_exact_legacy_trailing_source_marker():
    client = object.__new__(ScopedSalesforceClient)
    expected = {
        "accountId": "001000000000001AAA",
        "contactId": "",
        "locationId": "",
        "recordTypeId": "012000000000001AAA",
        "recordType": "1. NOVA Classic",
        "mainIssue": "Software",
        "technicalIssue": "Other",
        "customerContactMethod": "",
        "ticketCreatedBy": "Darius Parlor",
        "accountEligible": True,
        "sourceEmailId": "message-1",
        "sourceKey": "support-email:message-1",
        "description": "Register issue",
    }
    record = {
        "Id": "a0G000000000001AAA",
        "Name": "347314",
        "Account__c": expected["accountId"],
        "Account__r": {
            "Id": expected["accountId"],
            "Name": "Kay's Cafe",
            "Fake_Account__c": False,
        },
        "Contact__c": "",
        "NovaPOS_Location__c": "",
        "RecordTypeId": expected["recordTypeId"],
        "RecordType": {"Name": expected["recordType"]},
        "Is_Closed__c": False,
        "Ticket_Created_by__c": expected["ticketCreatedBy"],
        "Tech_Main_Issue__c": expected["mainIssue"],
        "Technical_Issue__c": expected["technicalIssue"],
        "Customer_Contact__c": "",
        "Description__c": (
            "Register issue\n\nSource key: support-email:message-1"
        ),
    }

    receipt = client._support_email_ticket_creation_receipt(
        record,
        expected=expected,
    )

    assert receipt["verified"] is True
    assert receipt["mismatchFields"] == []


def test_generic_ticket_create_rejects_source_key_before_write(monkeypatch):
    client = _client()
    sent = {}

    def fake_request(method, path, *, json=None, **_kwargs):
        assert method == "POST"
        assert path == "/sobjects/NovaPOS_Ticket__c"
        sent["payload"] = json
        return {"id": "a0G000000000000"}

    monkeypatch.setattr(client, "_request", fake_request)
    with pytest.raises(
        SalesforceScopeError,
        match="private intake metadata",
    ):
        client.create_ticket(
            account_id="001000000000001",
            description="Printer is offline.",
            source_key="gmail:message-123",
        )

    assert sent == {}


def test_ticket_contact_email_update_is_linked_scoped_and_verified(monkeypatch):
    client = _client()
    ticket_id = "a0G000000000001AAA"
    account_id = "001000000000001AAA"
    contact_id = "003000000000001AAA"
    state = {"Email": ""}
    monkeypatch.setattr(client, "_assert_ticket_scope", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        client,
        "read_ticket",
        lambda _ticket_id: {
            "ok": True,
            "record": {
                "Id": ticket_id,
                "Account__c": account_id,
                "Contact__c": contact_id,
            },
        },
    )

    def fake_request(method, path, **kwargs):
        assert path == f"/sobjects/Contact/{contact_id}"
        if method == "PATCH":
            state["Email"] = kwargs["json"]["Email"]
            return {}
        assert method == "GET"
        return {"Id": contact_id, "AccountId": account_id, "Email": state["Email"]}

    monkeypatch.setattr(client, "_request", fake_request)
    result = client.update_ticket_contact_email(
        ticket_id,
        contact_id,
        "owner@example.com",
        idempotency_key="ticket-contact-email-347251",
        allowed_record_types={"1. NOVA Classic"},
    )

    assert result["updated"] is True
    assert result["verified"] is True
    assert result["readback"]["Email"] == "owner@example.com"


def test_cancellation_order_reason_update_is_cancellation_scoped_alias_resolved_and_verified(monkeypatch):
    client = _client()
    order_id = "a0C000000000001AAA"
    account_id = "001000000000001AAA"
    record_type_id = "012000000000002AAA"
    state = {"Reason_for_cancellation__c": "End of Lease"}
    monkeypatch.setattr(
        client,
        "_resolve_cancellation_order_record_type",
        lambda: {
            "Id": record_type_id,
            "Name": "Existing Customer Cancellation Order",
            "DeveloperName": "Existing_Customer_Cancellation_Order",
        },
    )

    def fake_picklist(_record_type_id, field_name, requested_value, **_kwargs):
        assert field_name == "Reason_for_cancellation__c"
        return {"switched to a competitor": "Pricing (Moved to Competition)"}.get(
            requested_value, requested_value
        )

    monkeypatch.setattr(client, "_resolve_order_picklist_value", fake_picklist)
    base = {
        "Id": order_id,
        "Name": "C-066885-202610",
        "Account__c": account_id,
        "RecordTypeId": record_type_id,
        "Order_Type_Formula__c": "Cancellation Order",
        "Location_I_D__c": "1",
        "Chargify_Subscription_ID__c": 94189135,
        "Reason_for_cancellation__c": state["Reason_for_cancellation__c"],
    }

    def fake_request(method, path, **kwargs):
        assert path == f"/sobjects/NovaPOS_Order__c/{order_id}"
        if method == "PATCH":
            state["Reason_for_cancellation__c"] = kwargs["json"]["Reason_for_cancellation__c"]
            return {}
        assert method == "GET"
        return dict(base, Reason_for_cancellation__c=state["Reason_for_cancellation__c"])

    monkeypatch.setattr(client, "_request", fake_request)

    result = client.update_cancellation_order_reason(
        order_id,
        "switched to a competitor",
        idempotency_key="cancellation-order-reason-349219",
    )

    assert result["updated"] is True
    assert result["verified"] is True
    assert result["beforeReason"] == "End of Lease"
    assert result["reason"] == "Pricing (Moved to Competition)"
    assert result["readback"]["Reason_for_cancellation__c"] == "Pricing (Moved to Competition)"
    assert state["Reason_for_cancellation__c"] == "Pricing (Moved to Competition)"

    repeat = client.update_cancellation_order_reason(
        order_id,
        "switched to a competitor",
        idempotency_key="cancellation-order-reason-349219",
    )

    assert repeat["updated"] is False
    assert repeat["duplicate"] is True
    assert repeat["verified"] is True
    assert repeat["reason"] == "Pricing (Moved to Competition)"


def test_cancellation_order_reason_update_rejects_non_cancellation_order(monkeypatch):
    client = _client()
    order_id = "a0C000000000002AAA"

    def fake_request(method, path, **kwargs):
        assert path == f"/sobjects/NovaPOS_Order__c/{order_id}"
        assert method == "GET"
        return {
            "Id": order_id,
            "Account__c": "001000000000001AAA",
            "RecordTypeId": "012000000000003AAA",
            "Order_Type_Formula__c": "Sales Order",
            "Reason_for_cancellation__c": "",
        }

    monkeypatch.setattr(client, "_request", fake_request)

    with pytest.raises(SalesforceScopeError, match="not an existing Cancellation Order"):
        client.update_cancellation_order_reason(
            order_id,
            "End of Lease",
            idempotency_key="cancellation-order-reason-not-a-close-order",
        )


def test_cancellation_order_reason_update_requires_active_picklist_value(monkeypatch):
    client = _client()
    order_id = "a0C000000000003AAA"
    record_type_id = "012000000000002AAA"

    def fake_request(method, path, **kwargs):
        assert method == "GET"
        assert path == f"/sobjects/NovaPOS_Order__c/{order_id}"
        return {
            "Id": order_id,
            "Account__c": "001000000000001AAA",
            "RecordTypeId": record_type_id,
            "Order_Type_Formula__c": "Cancellation Order",
            "Reason_for_cancellation__c": "End of Lease",
        }

    monkeypatch.setattr(client, "_request", fake_request)
    monkeypatch.setattr(
        client,
        "_resolve_cancellation_order_record_type",
        lambda: {
            "Id": record_type_id,
            "Name": "Existing Customer Cancellation Order",
            "DeveloperName": "Existing_Customer_Cancellation_Order",
        },
    )
    monkeypatch.setattr(client, "_resolve_order_picklist_value", lambda *a, **k: (_ for _ in ()).throw(SalesforceScopeError("value not allowed")))

    with pytest.raises(SalesforceScopeError, match="not allowed"):
        client.update_cancellation_order_reason(
            order_id,
            "Made up reason",
            idempotency_key="cancellation-order-reason-bad-value",
        )


def _api_intro_html_stub() -> str:
    signup = 'https://rainfall-3qcpmfwo7a-vp.a.run.app/nova-api/signup'
    return (
        "<html><body>"
        "<p>API access includes: A 14-day trial period. "
        "After the trial, API access is available with a one-time setup fee of $100 "
        "and a monthly usage fee of $50.</p>"
        '<p><a href="' + signup + '">Sign up</a></p>'
        '<p><a href="https://rainfall-3qcpmfwo7a-vp.a.run.app/nova-api/resources">resources</a></p>'
        "</body></html>"
    )


def test_email_template_html_update_is_curated_fragment_checked_and_verified(monkeypatch):
    client = _client()
    template_id = "00XRc000007pDs1MAE"
    old_html = _api_intro_html_stub()
    new_html = old_html.replace(
        '<p><a href="https://rainfall-3qcpmfwo7a-vp.a.run.app/nova-api/signup">Sign up</a></p>',
        '<p><a href="https://rainfall-3qcpmfwo7a-vp.a.run.app/nova-api/signup" '
        'style="display: inline-block; padding: 13px 28px; border-radius: 6px; '
        'background-color: #D71920; color: #ffffff;">Sign up</a></p>',
    )
    assert new_html != old_html
    state = {"HtmlValue": old_html}
    base = {
        "Id": template_id,
        "Name": "NovaPOS API Intro",
        "DeveloperName": "NovaPOS_API_Intro",
        "FolderId": "00lA0000000peVUIAY",
        "Subject": "NovaPOS API access information",
    }

    def fake_request(method, path, **kwargs):
        assert path == f"/sobjects/EmailTemplate/{template_id}"
        if method == "PATCH":
            state["HtmlValue"] = kwargs["json"]["HtmlValue"]
            return {}
        assert method == "GET"
        return dict(base, HtmlValue=state["HtmlValue"])

    monkeypatch.setattr(client, "_request", fake_request)

    result = client.update_email_template_html(
        template_id,
        new_html,
        idempotency_key="api-intro-cta-button-349131",
    )

    assert result["updated"] is True
    assert result["verified"] is True
    assert result["duplicate"] is False
    assert result["situation"] == "api_intro"
    assert result["beforeSha256"] != result["afterSha256"]
    assert state["HtmlValue"] == new_html

    repeat = client.update_email_template_html(
        template_id,
        new_html,
        idempotency_key="api-intro-cta-button-349131",
    )

    assert repeat["updated"] is False
    assert repeat["duplicate"] is True
    assert repeat["verified"] is True


def test_email_template_html_update_rejects_non_curated_template(monkeypatch):
    client = _client()
    template_id = "00XRc0000099zzzMA9"

    def fake_request(method, path, **kwargs):
        assert method == "GET"
        return {
            "Id": template_id,
            "Name": "Some employee copy",
            "DeveloperName": "Some_Employee_Copy",
            "FolderId": "00lA0000000peVUIAY",
            "Subject": "Whatever",
            "HtmlValue": "<html><body>old</body></html>",
        }

    monkeypatch.setattr(client, "_request", fake_request)

    with pytest.raises(SalesforceScopeError, match="curated template"):
        client.update_email_template_html(
            template_id,
            "<html><body><p>one-time setup fee of $100</p></body></html>",
            idempotency_key="api-intro-non-curated-reject",
        )


def test_email_template_html_update_rejects_dropped_required_content(monkeypatch):
    client = _client()
    template_id = "00XRc000007pDs1MAE"
    base = {
        "Id": template_id,
        "Name": "NovaPOS API Intro",
        "DeveloperName": "NovaPOS_API_Intro",
        "FolderId": "00lA0000000peVUIAY",
        "Subject": "NovaPOS API access information",
        "HtmlValue": _api_intro_html_stub(),
    }

    def fake_request(method, path, **kwargs):
        assert method == "GET"
        return dict(base)

    monkeypatch.setattr(client, "_request", fake_request)
    stripped = _api_intro_html_stub().replace("one-time setup fee of $100 ", "")

    with pytest.raises(SalesforceScopeError, match="dropped required approved content"):
        client.update_email_template_html(
            template_id,
            stripped,
            idempotency_key="api-intro-dropped-fragment-reject",
        )


def test_ticket_pdf_upload_is_lane_scoped_and_digest_verified(monkeypatch):
    client = _client()
    ticket_id = "a0G000000000001AAA"
    content = b"%PDF-1.7\nverified ticket evidence\n%%EOF"
    digest = hashlib.sha256(content).hexdigest()
    version_id = "068000000000001AAA"
    records = []
    monkeypatch.setattr(client, "_assert_ticket_scope", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(client, "_ticket_content_versions", lambda _ticket_id: list(records))
    monkeypatch.setattr(client, "_request_bytes", lambda _path: content)

    def fake_request(method, path, **kwargs):
        assert method == "POST"
        assert path == "/sobjects/ContentVersion"
        assert kwargs["json"]["FirstPublishLocationId"] == ticket_id
        records.append(
            {
                "Id": version_id,
                "Title": "customer evidence",
                "ContentSize": len(content),
            }
        )
        return {"id": version_id, "success": True}

    monkeypatch.setattr(client, "_request", fake_request)
    result = client.upload_ticket_pdf(
        ticket_id,
        "customer evidence.pdf",
        base64.b64encode(content).decode("ascii"),
        digest,
        idempotency_key="ticket-pdf-347191-evidence",
        allowed_record_types={"1. NOVA Classic"},
    )

    assert result["uploaded"] is True
    assert result["verified"] is True
    assert result["sha256"] == digest


def test_ticket_attachment_upload_accepts_safe_email_evidence_with_digest_readback(monkeypatch):
    client = _client()
    ticket_id = "a0G000000000001AAA"
    content = b"From: owner@example.com\r\nSubject: Cancellation request\r\n\r\nPlease cancel service."
    digest = hashlib.sha256(content).hexdigest()
    version_id = "068000000000002AAA"
    records = []
    monkeypatch.setattr(client, "_assert_ticket_scope", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(client, "_ticket_content_versions", lambda _ticket_id: list(records))
    monkeypatch.setattr(client, "_request_bytes", lambda _path: content)

    def fake_request(method, path, **kwargs):
        assert method == "POST"
        assert path == "/sobjects/ContentVersion"
        records.append(
            {
                "Id": version_id,
                "Title": "cancellation request",
                "ContentSize": len(content),
            }
        )
        return {"id": version_id, "success": True}

    monkeypatch.setattr(client, "_request", fake_request)
    result = client.upload_ticket_attachment(
        ticket_id,
        "cancellation request.eml",
        base64.b64encode(content).decode("ascii"),
        digest,
        idempotency_key="ticket-attachment-347191-email",
        allowed_record_types={"1. NOVA Classic"},
    )

    assert result["uploaded"] is True
    assert result["verified"] is True
    assert result["sha256"] == digest


def test_existing_ticket_description_and_technical_notes_updates_are_rejected(monkeypatch):
    client = _client()
    monkeypatch.setattr(client, "_assert_ticket_scope", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        client,
        "_request",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("must not patch")),
    )

    with pytest.raises(SalesforceScopeError, match="must be posted to Chatter"):
        client.update_ticket("a0G000000000000", {"Technical_Notes__c": "Internal note"})
    with pytest.raises(SalesforceScopeError, match="must be posted to Chatter"):
        client.update_ticket("a0G000000000000", {"Description__c": "Internal note"})


def test_payment_card_ticket_redaction_is_billing_only_idempotent_and_verified(
    monkeypatch,
    tmp_path,
):
    ticket_id = "a0G000000000000AAA"
    state = {
        "Id": ticket_id,
        "Name": "347607",
        "LastModifiedDate": "2026-08-03T22:00:00.000+0000",
        "Payment_Method__c": "credit card",
        "Last_4_digits_on_Credit_Card__c": "1111",
        "Name_on_Card__c": "Example Customer",
        "CC_Experation_Date__c": "12/29",
        "CVV__c": "123",
        "Street_Address_I__c": "100 Example Street",
        "Billing_Street_Address_II__c": "Suite 1",
        "CIty__c": "Example City",
        "State__c": "FL",
        "Country__c": "US",
        "Billing_Zipcode__c": "33101",
        "Description__c": (
            "Card number: 4111 1111 1111 1111 | CVV: 123 | Exp: 12/29 | "
            "Name on card: Example Customer"
        ),
        "Billing_Notes_Internal__c": "Billing address: 100 Example Street",
        "Notes_Send_To_Client__c": None,
        "Technical_Notes__c": None,
    }
    client = _client(journal_path=tmp_path / "salesforce.jsonl")
    monkeypatch.setattr(client, "_assert_ticket_scope", lambda *_args, **_kwargs: None)

    def redaction_query(soql):
        assert "Technical_Notes__c" not in soql
        assert "Description__c" in soql
        return {"records": [dict(state)]}

    monkeypatch.setattr(client, "_query", redaction_query)

    patch_calls = []

    def fake_request(method, path, **kwargs):
        assert method == "PATCH"
        assert path.endswith(ticket_id)
        patch_calls.append(dict(kwargs["json"]))
        state.update(kwargs["json"])
        state["LastModifiedDate"] = "2026-08-03T22:01:00.000+0000"
        return {"id": ticket_id, "success": True}

    monkeypatch.setattr(client, "_request", fake_request)

    preview = client.payment_card_ticket_redaction_preview(ticket_id)
    serialized_preview = json.dumps(preview)
    for secret in (
        "4111 1111 1111 1111",
        "Example Customer",
        "100 Example Street",
        '"CVV__c": "123"',
    ):
        assert secret not in serialized_preview
    assert preview["redactionRequired"] is True

    applied = client.apply_payment_card_ticket_redaction(
        ticket_id,
        preview_hash=preview["planHash"],
        idempotency_key="ticket-347607-payment-redaction-v1",
    )
    assert applied["verified"] is True
    assert applied["readback"] == {
        "paymentCardFieldsCleared": True,
        "rawCardTextAbsent": True,
    }
    assert len(patch_calls) == 1
    assert all(state[field] is None for field in (
        "Payment_Method__c",
        "Last_4_digits_on_Credit_Card__c",
        "Name_on_Card__c",
        "CC_Experation_Date__c",
        "CVV__c",
        "Street_Address_I__c",
        "Billing_Street_Address_II__c",
        "CIty__c",
        "State__c",
        "Country__c",
        "Billing_Zipcode__c",
    ))
    assert "4111" not in state["Description__c"]
    assert "123" not in state["Description__c"]
    assert "100 Example Street" not in state["Billing_Notes_Internal__c"]

    duplicate = client.apply_payment_card_ticket_redaction(
        ticket_id,
        preview_hash=preview["planHash"],
        idempotency_key="ticket-347607-payment-redaction-v1",
    )
    assert duplicate["duplicate"] is True
    assert len(patch_calls) == 1

    billing_tools = set(
        build_mcp(
            "billing_agent",
            FakeClient(),
            FakeNovaSqlClient(),
            FakeNovaApiClient(),
        )._tool_manager._tools
    )
    coding_tools = set(
        build_mcp(
            "coding_agent",
            FakeClient(),
            FakeNovaSqlClient(),
            FakeNovaApiClient(),
        )._tool_manager._tools
    )
    expected = {
        "salesforce_payment_card_ticket_redaction_preview",
        "salesforce_payment_card_ticket_redaction_apply",
    }
    assert expected.issubset(billing_tools)
    assert not expected.intersection(coding_tools)


def _client(
    journal_path: Path | None = None,
    *,
    internal_communication_journal_path: Path | None = None,
) -> ScopedSalesforceClient:
    return ScopedSalesforceClient(
        SalesforceSettings(
            "https://example.invalid",
            "https://login.invalid",
            "",
            "",
            "",
            "",
            "token",
            False,
            journal_path=journal_path
            or Path("/var/lib/nova/broker/salesforce/operations.jsonl"),
        ),
        internal_communication_journal_path=internal_communication_journal_path,
    )


def test_billing_schedule_date_is_previewed_and_applied_as_one_field(
    monkeypatch,
    tmp_path,
):
    client = _client(tmp_path / "salesforce-operations.jsonl")
    ticket_id = "a0G000000000001AAA"
    account_id = "001000000000001AAA"
    schedule_id = "a0S000000000001AAA"
    subscription_id = 93687042
    state = {"Start_Date__c": "2026-08-13"}
    patches = []

    monkeypatch.setattr(
        client,
        "_assert_operational_ticket_account",
        lambda requested_ticket_id, requested_account_id: {
            "Id": requested_ticket_id,
            "Name": "347703",
            "Account__c": requested_account_id,
        },
    )
    monkeypatch.setattr(
        client,
        "_read_billing_schedule",
        lambda requested_schedule_id: {
            "Id": requested_schedule_id,
            "Account__c": account_id,
            "Chargify_Subscription_ID__c": str(subscription_id),
            "Billing_Circle_Schedule_ID__c": str(subscription_id),
            **state,
        },
    )

    def fake_request(method, path, **kwargs):
        assert method == "PATCH"
        assert path.endswith(schedule_id)
        assert kwargs["json"] == {"Start_Date__c": "2026-09-02"}
        patches.append(dict(kwargs["json"]))
        state.update(kwargs["json"])
        return {}

    monkeypatch.setattr(client, "_request", fake_request)

    preview = client.billing_schedule_date_preview(
        ticket_id,
        account_id,
        schedule_id,
        subscription_id,
        "2026-09-02",
    )
    assert preview["before"] == {"Start_Date__c": "2026-08-13"}
    assert preview["desired"] == {"Start_Date__c": "2026-09-02"}
    assert preview["duplicate"] is False

    result = client.apply_billing_schedule_date(
        ticket_id,
        account_id,
        schedule_id,
        subscription_id,
        "2026-09-02",
        preview_hash=preview["planHash"],
        idempotency_key="ticket-347703-schedule-date-20260902-v1",
    )

    assert patches == [{"Start_Date__c": "2026-09-02"}]
    assert result["updated"] is True
    assert result["verified"] is True
    assert result["readback"]["Start_Date__c"] == "2026-09-02"


def test_weekly_ticket_totals_are_exact_unfiltered_aggregates(monkeypatch):
    client = _client()

    def fake_query(soql):
        assert "CreatedDate >= 2026-07-17T04:00:00Z" in soql
        assert "CreatedDate < 2026-07-24T04:00:00Z" in soql
        assert "Is_Closed__c" not in soql
        assert "Account__c" not in soql
        return {
            "records": [
                {"record_type": "1. NOVA Classic", "total": 123},
                {"record_type": "2. Nova Wave", "total": 7},
            ]
        }

    monkeypatch.setattr(client, "_query", fake_query)

    result = client.weekly_ticket_totals(
        start_utc="2026-07-17T04:00:00Z",
        end_utc="2026-07-24T04:00:00Z",
    )

    assert result["novaClassic"] == 123
    assert result["novaWave"] == 7
    assert result["total"] == 130


def test_billing_account_flat_rate_update_is_exact_idempotent_and_verified(monkeypatch):
    client = _client()
    state = {"rate": 149.99}
    patches = []

    def fake_query(soql):
        assert "FROM Account WHERE Id = '001000000000001AAA' LIMIT 1" in soql
        assert "Flat_Rate_Amount__c" in soql
        assert "Payments_Partner__c" in soql
        return {
            "records": [
                {
                    "Id": "001000000000001AAA",
                    "Name": "BEEco",
                    "Company_Username__c": "BEEco",
                    "Flat_Rate_Amount__c": state["rate"],
                    "Monthly_Revenue_per_Location__c": None,
                    "Base_Location_Price__c": None,
                    "Payments_Partner__c": "Propelr",
                    "NovaPOS_Active__c": 2,
                    "Status__c": "New Web Account",
                    "Real_Account_Status__c": None,
                }
            ]
        }

    def fake_request(method, path, **kwargs):
        assert method == "PATCH"
        assert path == "/sobjects/Account/001000000000001AAA"
        assert kwargs["json"] == {"Flat_Rate_Amount__c": 139.99}
        patches.append(kwargs["json"])
        state["rate"] = kwargs["json"]["Flat_Rate_Amount__c"]
        return {}

    monkeypatch.setattr(client, "_query", fake_query)
    monkeypatch.setattr(client, "_request", fake_request)

    result = client.update_billing_account_flat_rate(
        "001000000000001AAA",
        13_999,
        idempotency_key="ticket-347308-account-rate-beeco",
    )
    duplicate = client.update_billing_account_flat_rate(
        "001000000000001AAA",
        13_999,
        idempotency_key="ticket-347308-account-rate-beeco",
    )

    assert result["updated"] is True
    assert result["verified"] is True
    assert result["before"]["Flat_Rate_Amount__c"] == 149.99
    assert result["readback"]["Flat_Rate_Amount__c"] == 139.99
    assert duplicate["updated"] is False
    assert duplicate["duplicate"] is True
    assert len(patches) == 1


def test_billing_account_flat_rate_update_rejects_bad_key_and_amount():
    client = _client()
    with pytest.raises(SalesforceScopeError, match="idempotency_key"):
        client.update_billing_account_flat_rate(
            "001000000000001AAA",
            13_999,
            idempotency_key="short",
        )
    with pytest.raises(SalesforceScopeError, match="between"):
        client.update_billing_account_flat_rate(
            "001000000000001AAA",
            -1,
            idempotency_key="ticket-347308-account-rate-beeco",
        )


def test_billing_account_flat_rate_update_allows_intentional_zero(monkeypatch):
    client = _client()
    state = {"rate": 109.99}
    monkeypatch.setattr(
        client,
        "read_billing_account",
        lambda _account_id: {
            "record": {
                "Id": "001000000000001AAA",
                "Flat_Rate_Amount__c": state["rate"],
            }
        },
    )

    def fake_request(method, path, **kwargs):
        assert method == "PATCH"
        assert path == "/sobjects/Account/001000000000001AAA"
        assert kwargs["json"] == {"Flat_Rate_Amount__c": 0.0}
        state["rate"] = 0.0
        return {}

    monkeypatch.setattr(client, "_request", fake_request)
    result = client.update_billing_account_flat_rate(
        "001000000000001AAA",
        0,
        idempotency_key="ticket-347308-intentional-free",
    )

    assert result["updated"] is True
    assert result["verified"] is True
    assert result["monthlyRateCents"] == 0


def test_billing_location_rate_update_is_typed_idempotent_and_verified(monkeypatch):
    client = _client()
    state = {"rate": 149.99}
    patches = []

    def fake_lookup(kind, value, **_kwargs):
        assert kind == "location"
        return {
            "records": [
                {
                    "Id": value,
                    "Account__c": "001000000000001AAA",
                    "Bill_Amount__c": state["rate"],
                }
            ]
        }

    def fake_request(method, path, **kwargs):
        assert method == "PATCH"
        assert path == "/sobjects/NovaPOS_Location__c/a0L000000000001AAA"
        patches.append(kwargs["json"])
        state["rate"] = kwargs["json"]["Bill_Amount__c"]
        return {}

    monkeypatch.setattr(client, "lookup", fake_lookup)
    monkeypatch.setattr(client, "_request", fake_request)
    result = client.update_billing_location_rate(
        "a0L000000000001AAA",
        13_999,
        idempotency_key="ticket-347308-location-rate-one",
    )
    duplicate = client.update_billing_location_rate(
        "a0L000000000001AAA",
        13_999,
        idempotency_key="ticket-347308-location-rate-one",
    )

    assert result["updated"] is True
    assert result["readback"]["Bill_Amount__c"] == 139.99
    assert duplicate["duplicate"] is True
    assert patches == [{"Bill_Amount__c": 139.99}]


def test_billing_account_flat_rate_clear_requires_expected_value_and_reads_back_null(
    monkeypatch,
    tmp_path,
):
    client = _client(journal_path=tmp_path / "salesforce.jsonl")
    state = {"rate": 99.99}
    patches = []
    monkeypatch.setattr(
        client,
        "read_billing_account",
        lambda _account_id: {
            "record": {
                "Id": "001000000000001AAA",
                "Flat_Rate_Amount__c": state["rate"],
                "Payments_Partner__c": "Propelr",
            }
        },
    )

    def fake_request(method, path, **kwargs):
        assert method == "PATCH"
        assert path == "/sobjects/Account/001000000000001AAA"
        assert kwargs["json"] == {"Flat_Rate_Amount__c": None}
        patches.append(kwargs["json"])
        state["rate"] = None
        return {}

    monkeypatch.setattr(client, "_request", fake_request)
    result = client.clear_billing_account_flat_rate(
        "001000000000001AAA",
        9_999,
        idempotency_key="ticket-347519-clear-unintended-account-flat-rate",
    )
    duplicate = client.clear_billing_account_flat_rate(
        "001000000000001AAA",
        9_999,
        idempotency_key="ticket-347519-clear-unintended-account-flat-rate-repeat",
    )

    assert result["updated"] is True
    assert result["verified"] is True
    assert result["readback"]["Flat_Rate_Amount__c"] is None
    assert duplicate["duplicate"] is True
    assert patches == [{"Flat_Rate_Amount__c": None}]


def test_billing_account_flat_rate_clear_rejects_changed_value(monkeypatch, tmp_path):
    client = _client(journal_path=tmp_path / "salesforce.jsonl")
    monkeypatch.setattr(
        client,
        "read_billing_account",
        lambda _account_id: {
            "record": {"Id": "001000000000001AAA", "Flat_Rate_Amount__c": 139.99}
        },
    )
    with pytest.raises(SalesforceScopeError, match="no longer matches"):
        client.clear_billing_account_flat_rate(
            "001000000000001AAA",
            9_999,
            idempotency_key="ticket-347519-clear-unintended-account-flat-rate",
        )


def test_billing_location_gateway_update_is_exact_and_verified(monkeypatch, tmp_path):
    client = _client(journal_path=tmp_path / "salesforce.jsonl")
    state = {"integrated": False}
    patches = []

    def fake_lookup(kind, value, **_kwargs):
        assert kind == "location"
        return {
            "records": [
                {
                    "Id": value,
                    "Account__c": "001000000000001AAA",
                    "Is_Location_on_GSPayTech_Gateway__c": state["integrated"],
                }
            ]
        }

    def fake_request(method, path, **kwargs):
        assert method == "PATCH"
        assert path == "/sobjects/NovaPOS_Location__c/a0L000000000001AAA"
        assert kwargs["json"] == {"Is_Location_on_GSPayTech_Gateway__c": True}
        patches.append(kwargs["json"])
        state["integrated"] = True
        return {}

    monkeypatch.setattr(client, "lookup", fake_lookup)
    monkeypatch.setattr(client, "_request", fake_request)
    result = client.update_billing_location_gateway(
        "a0L000000000001AAA",
        True,
        idempotency_key="ticket-347519-location-one-integrated-gateway",
    )
    duplicate = client.update_billing_location_gateway(
        "a0L000000000001AAA",
        True,
        idempotency_key="ticket-347519-location-one-integrated-gateway-repeat",
    )

    assert result["updated"] is True
    assert result["verified"] is True
    assert result["readback"]["Is_Location_on_GSPayTech_Gateway__c"] is True
    assert duplicate["duplicate"] is True
    assert patches == [{"Is_Location_on_GSPayTech_Gateway__c": True}]


def test_account_lookup_resolves_exact_nova_id_without_name_discovery(monkeypatch):
    client = _client()
    queries = []

    def fake_query(soql):
        queries.append(soql)
        return {
            "records": [
                {
                    "Id": "001000000000001AAA",
                    "Name": "Internal QA",
                    "Company_Username__c": "qa_internal",
                    "Nova_ID__c": "A-1564705",
                    "Phone": None,
                }
            ]
        }

    monkeypatch.setattr(client, "_query", fake_query)
    result = client.lookup("account", "A-1564705")

    assert result["records"][0]["Nova_ID__c"] == "A-1564705"
    assert "WHERE Nova_ID__c = 'A-1564705'" in queries[0]
    assert "Name LIKE" not in queries[0]


def test_fake_account_classification_is_ticket_bound_previewed_and_journaled(
    monkeypatch,
    tmp_path,
):
    client = ScopedSalesforceClient(
        SalesforceSettings(
            "https://example.invalid",
            "https://login.invalid",
            "",
            "",
            "",
            "",
            "token",
            False,
            journal_path=tmp_path / "salesforce.jsonl",
        )
    )
    account = {
        "Id": "001000000000001AAA",
        "Name": "Internal QA",
        "Nova_ID__c": "A-1563638",
        "Fake_Account__c": False,
    }
    patches = []
    monkeypatch.setattr(
        client,
        "_assert_billing_ticket_account",
        lambda ticket_id, account_id: {
            "Id": ticket_id,
            "Name": "347400",
            "Account__c": account_id,
        },
    )
    monkeypatch.setattr(
        client,
        "read_billing_account",
        lambda _account_id: {"record": dict(account)},
    )

    def fake_request(method, path, **kwargs):
        assert method == "PATCH"
        assert path == "/sobjects/Account/001000000000001AAA"
        patches.append(kwargs["json"])
        account.update(kwargs["json"])
        return {}

    monkeypatch.setattr(client, "_request", fake_request)
    preview = client.account_fake_classification_preview(
        "a0G000000000001AAA",
        account["Id"],
        "A-1563638",
        is_fake=True,
    )
    applied = client.apply_account_fake_classification(
        "a0G000000000001AAA",
        account["Id"],
        "A-1563638",
        is_fake=True,
        preview_hash=preview["planHash"],
        idempotency_key="ticket-347400-account-a1563638-fake",
    )

    assert applied["verified"] is True
    assert applied["readback"]["Fake_Account__c"] is True
    assert patches == [{"Fake_Account__c": True}]
    journal = (tmp_path / "salesforce.jsonl").read_text(encoding="utf-8")
    assert '"status":"pending"' in journal
    assert '"status":"accepted"' in journal


def test_location_alignment_supports_verified_intentional_free_location(
    monkeypatch,
    tmp_path,
):
    client = ScopedSalesforceClient(
        SalesforceSettings(
            "https://example.invalid",
            "https://login.invalid",
            "",
            "",
            "",
            "",
            "token",
            False,
            journal_path=tmp_path / "salesforce.jsonl",
        )
    )
    location = {
        "Id": "a0L000000000001AAA",
        "Account__c": "001000000000001AAA",
        "Location_ID__c": 7,
        "Status__c": "Inactive",
        "Bill_Amount__c": 139.99,
        "Chargify_Subscription_ID__c": None,
        "NovaPOS_Billing_Schedule__c": None,
    }
    monkeypatch.setattr(
        client,
        "_assert_operational_ticket_account",
        lambda ticket_id, account_id: {"Id": ticket_id, "Account__c": account_id},
    )
    monkeypatch.setattr(
        client,
        "lookup",
        lambda *_args, **_kwargs: {"records": [dict(location)]},
    )

    def fake_request(method, path, **kwargs):
        assert method == "PATCH"
        assert path.endswith(location["Id"])
        location.update(kwargs["json"])
        return {}

    monkeypatch.setattr(client, "_request", fake_request)
    with pytest.raises(SalesforceScopeError, match="intentional_free"):
        client.billing_location_alignment_preview(
            "a0G000000000001AAA",
            location["Account__c"],
            location["Id"],
            7,
            desired_status="Active",
            monthly_rate_cents=0,
        )
    preview = client.billing_location_alignment_preview(
        "a0G000000000001AAA",
        location["Account__c"],
        location["Id"],
        7,
        desired_status="Active",
        monthly_rate_cents=0,
        billing_exception="intentional_free",
    )
    applied = client.apply_billing_location_alignment(
        "a0G000000000001AAA",
        location["Account__c"],
        location["Id"],
        7,
        desired_status="Active",
        monthly_rate_cents=0,
        billing_exception="intentional_free",
        preview_hash=preview["planHash"],
        idempotency_key="ticket-347400-location-7-intentional-free",
    )

    assert applied["verified"] is True
    assert applied["readback"]["Status__c"] == "Active"
    assert applied["readback"]["Bill_Amount__c"] == 0.0


# AgentChat/direct_codex 2026-07-29T14:35:00Z: guard inactive location writes from obsolete Salesforce automation.
def test_location_alignment_stages_deactivation_guards_before_lifecycle(
    monkeypatch,
    tmp_path,
):
    client = ScopedSalesforceClient(
        SalesforceSettings(
            "https://example.invalid",
            "https://login.invalid",
            "",
            "",
            "",
            "",
            "token",
            False,
            journal_path=tmp_path / "salesforce.jsonl",
        )
    )
    location = {
        "Id": "a0L000000000001AAA",
        "Account__c": "001000000000001AAA",
        "Location_ID__c": 2,
        "Status__c": "Active",
        "Bill_Amount__c": 99.99,
        "Chargify_Subscription_ID__c": "92394271",
        "NovaPOS_Billing_Schedule__c": "a0S000000000001AAA",
        "Is_Location_on_GSPayTech_Gateway__c": True,
    }
    patches = []
    monkeypatch.setattr(
        client,
        "_assert_operational_ticket_account",
        lambda ticket_id, account_id: {"Id": ticket_id, "Account__c": account_id},
    )
    monkeypatch.setattr(
        client,
        "lookup",
        lambda *_args, **_kwargs: {"records": [dict(location)]},
    )

    def fake_request(method, path, **kwargs):
        assert method == "PATCH"
        assert path.endswith(location["Id"])
        payload = dict(kwargs["json"])
        if payload.get("Status__c") == "Inactive":
            assert location["Is_Location_on_GSPayTech_Gateway__c"] is False
        patches.append(payload)
        location.update(payload)
        return {}

    monkeypatch.setattr(client, "_request", fake_request)
    preview = client.billing_location_alignment_preview(
        "a0G000000000001AAA",
        location["Account__c"],
        location["Id"],
        2,
        desired_status="Inactive",
        clear_subscription_link=True,
        clear_schedule_link=True,
    )
    applied = client.apply_billing_location_alignment(
        "a0G000000000001AAA",
        location["Account__c"],
        location["Id"],
        2,
        desired_status="Inactive",
        clear_subscription_link=True,
        clear_schedule_link=True,
        preview_hash=preview["planHash"],
        idempotency_key="ticket-347394-location-2-staged",
    )

    assert preview["stagedChanges"] == [
        {
            "name": "deactivation_guards",
            "desired": {
                "Is_Location_on_GSPayTech_Gateway__c": False,
                "Chargify_Subscription_ID__c": None,
                "NovaPOS_Billing_Schedule__c": None,
            },
        },
        {"name": "lifecycle", "desired": {"Status__c": "Inactive"}},
    ]
    assert patches == [
        {
            "Is_Location_on_GSPayTech_Gateway__c": False,
            "Chargify_Subscription_ID__c": None,
            "NovaPOS_Billing_Schedule__c": None,
        },
        {"Status__c": "Inactive"},
    ]
    assert applied["completedStages"] == ["deactivation_guards", "lifecycle"]
    assert applied["readback"]["Status__c"] == "Inactive"
    assert applied["readback"]["Is_Location_on_GSPayTech_Gateway__c"] is False
    assert applied["readback"]["Chargify_Subscription_ID__c"] is None
    assert applied["readback"]["NovaPOS_Billing_Schedule__c"] is None

def test_billing_structure_preview_creates_missing_account_schedule_and_links(monkeypatch):
    client = _client()
    monkeypatch.setattr(
        client,
        "_assert_operational_ticket_account",
        lambda ticket_id, account_id: {
            "Id": ticket_id,
            "Name": "347401",
            "Account__c": account_id,
        },
    )
    monkeypatch.setattr(
        client,
        "read_billing_account",
        lambda _account_id: {
            "record": {
                "Id": "001000000000001AAA",
                "Name": "Palm Beach Cosmetics",
            }
        },
    )
    monkeypatch.setattr(
        client,
        "read_billing_structure",
        lambda _account_id: {
            "billingAccounts": [],
            "billingSchedules": [],
            "optionalBillingFieldsAvailable": True,
        },
    )
    monkeypatch.setattr(
        client,
        "read_account_locations",
        lambda _account_id, limit=500: {
            "records": [
                {
                    "Id": "a0L000000000001AAA",
                    "Account__c": "001000000000001AAA",
                    "Location_ID__c": 3,
                    "Chargify_Subscription_ID__c": None,
                    "NovaPOS_Billing_Schedule__c": None,
                }
            ]
        },
    )

    preview = client.billing_structure_alignment_preview(
        "a0G000000000001AAA",
        "001000000000001AAA",
        maxio_customer_id=9001,
        payment_profile_id=7001,
        subscription_id=8001,
        subscription_state="active",
        bill_amount_cents=10_999,
        start_date="2026-08-01",
        nova_location_ids=[3],
    )

    assert preview["billingAccount"]["create"] is True
    assert preview["billingSchedule"]["create"] is True
    assert preview["billingSchedule"]["desired"]["Bill_Amount__c"] == 109.99
    assert preview["locationChanges"][0]["novaLocationId"] == 3
    assert preview["financialEffectsAuthorized"] is False


def test_billing_structure_allows_missing_profile_when_optional_field_is_unavailable(
    monkeypatch,
):
    client = _client()
    account_id = "001000000000001AAA"
    billing_account_id = "a0B000000000001AAA"
    billing_schedule_id = "a0S000000000001AAA"
    location_id = "a0L000000000001AAA"
    monkeypatch.setattr(
        client,
        "_assert_operational_ticket_account",
        lambda ticket_id, requested_account_id: {
            "Id": ticket_id,
            "Name": "347688",
            "Account__c": requested_account_id,
        },
    )
    monkeypatch.setattr(
        client,
        "read_billing_account",
        lambda _account_id: {"record": {"Id": account_id, "Name": "KDA Group LLC"}},
    )
    monkeypatch.setattr(
        client,
        "read_billing_structure",
        lambda _account_id: {
            "billingAccounts": [
                {
                    "Id": billing_account_id,
                    "Account__c": account_id,
                    "Billing_Circle_Client_ID__c": None,
                    "Status__c": "Trial",
                }
            ],
            "billingSchedules": [
                {
                    "Id": billing_schedule_id,
                    "NovaPOS_Billing_Account__c": billing_account_id,
                    "Chargify_Subscription_ID__c": 93720300,
                    "Billing_Circle_Schedule_ID__c": 93720300,
                    "Bill_Amount__c": 139.99,
                    "Start_Date__c": "2026-08-15",
                }
            ],
            "optionalBillingFieldsAvailable": False,
        },
    )
    monkeypatch.setattr(
        client,
        "read_account_locations",
        lambda _account_id, limit=500: {
            "records": [
                {
                    "Id": location_id,
                    "Account__c": account_id,
                    "Location_ID__c": 3,
                    "Chargify_Subscription_ID__c": "93720300",
                    "NovaPOS_Billing_Schedule__c": billing_schedule_id,
                }
            ]
        },
    )

    preview = client.billing_structure_alignment_preview(
        "a0G000000000001AAA",
        account_id,
        maxio_customer_id=9001,
        payment_profile_id=None,
        subscription_id=93720300,
        subscription_state="active",
        bill_amount_cents=10_999,
        start_date="2026-08-15",
        nova_location_ids=[3],
        billing_account_id=billing_account_id,
        billing_schedule_id=billing_schedule_id,
    )

    assert preview["paymentProfileId"] is None
    assert preview["billingSchedule"]["changes"]["Bill_Amount__c"] == 109.99
    assert "Chargify_Payment_Profile_ID__c" not in preview["billingAccount"]["desired"]


def test_billing_structure_requires_profile_when_optional_field_is_available(monkeypatch):
    client = _client()
    account_id = "001000000000001AAA"
    monkeypatch.setattr(
        client,
        "_assert_operational_ticket_account",
        lambda ticket_id, requested_account_id: {
            "Id": ticket_id,
            "Name": "347688",
            "Account__c": requested_account_id,
        },
    )
    monkeypatch.setattr(
        client,
        "read_billing_account",
        lambda _account_id: {"record": {"Id": account_id, "Name": "KDA Group LLC"}},
    )
    monkeypatch.setattr(
        client,
        "read_billing_structure",
        lambda _account_id: {
            "billingAccounts": [],
            "billingSchedules": [],
            "optionalBillingFieldsAvailable": True,
        },
    )

    with pytest.raises(SalesforceScopeError, match="payment_profile_id is required"):
        client.billing_structure_alignment_preview(
            "a0G000000000001AAA",
            account_id,
            maxio_customer_id=9001,
            payment_profile_id=None,
            subscription_id=93720300,
            subscription_state="active",
            bill_amount_cents=10_999,
            start_date="2026-08-15",
            nova_location_ids=[3],
        )


def test_billing_structure_requires_exact_selectors_and_preserves_nonempty_shared_customer_owner(
    monkeypatch,
):
    client = _client()
    account_id = "001000000000001AAA"
    target_account_id = "a0B000000000001AAA"
    canonical_account_id = "a0B000000000002AAA"
    target_schedule_id = "a0S000000000001AAA"
    canonical_schedule_id = "a0S000000000002AAA"
    location_id = "a0L000000000001AAA"
    monkeypatch.setattr(
        client,
        "_assert_operational_ticket_account",
        lambda ticket_id, requested_account_id: {
            "Id": ticket_id,
            "Name": "347396",
            "Account__c": requested_account_id,
        },
    )
    monkeypatch.setattr(
        client,
        "read_billing_account",
        lambda _account_id: {
            "record": {
                "Id": account_id,
                "Name": "unique lifestyle llc",
            }
        },
    )
    monkeypatch.setattr(
        client,
        "read_billing_structure",
        lambda _account_id: {
            "billingAccounts": [
                {
                    "Id": target_account_id,
                    "Account__c": account_id,
                    "Name": "unique lifestyle llc",
                    "Billing_Circle_Client_ID__c": 60128193,
                    "Status__c": "Trial",
                },
                {
                    "Id": canonical_account_id,
                    "Account__c": account_id,
                    "Name": "unique lifestyle llc 92346505",
                    "Billing_Circle_Client_ID__c": 11225503,
                    "Status__c": "Active",
                },
            ],
            "billingSchedules": [
                {
                    "Id": target_schedule_id,
                    "NovaPOS_Billing_Account__c": target_account_id,
                    "Chargify_Subscription_ID__c": 77321773,
                    "Billing_Circle_Schedule_ID__c": 77321773,
                    "Name": "77321773",
                    "Title__c": "77321773",
                    "Schedule_Interval__c": "unknown",
                    "Bill_Amount__c": 139.99,
                    "Start_Date__c": "2024-08-16",
                    "Type__c": None,
                },
                {
                    "Id": canonical_schedule_id,
                    "NovaPOS_Billing_Account__c": canonical_account_id,
                    "Chargify_Subscription_ID__c": 92346505,
                    "Billing_Circle_Schedule_ID__c": 92346505,
                    "Name": "92346505",
                    "Title__c": "92346505",
                    "Schedule_Interval__c": "monthly",
                    "Bill_Amount__c": 279.98,
                    "Start_Date__c": "2026-07-03",
                    "Type__c": "subscription",
                },
            ],
            "optionalBillingFieldsAvailable": False,
        },
    )
    monkeypatch.setattr(
        client,
        "read_account_locations",
        lambda _account_id, limit=500: {
            "records": [
                {
                    "Id": location_id,
                    "Location_ID__c": 17,
                    "Chargify_Subscription_ID__c": "77321773",
                    "NovaPOS_Billing_Schedule__c": target_schedule_id,
                }
            ]
        },
    )

    with pytest.raises(SalesforceScopeError, match="requires exact"):
        client.billing_structure_alignment_preview(
            "a0G000000000001AAA",
            account_id,
            maxio_customer_id=11225503,
            payment_profile_id=60128193,
            subscription_id=77321773,
            subscription_state="active",
            bill_amount_cents=13_999,
            start_date="2026-07-03",
            nova_location_ids=[17],
        )

    preview = client.billing_structure_alignment_preview(
        "a0G000000000001AAA",
        account_id,
        maxio_customer_id=11225503,
        payment_profile_id=60128193,
        subscription_id=77321773,
        subscription_state="active",
        bill_amount_cents=13_999,
        start_date="2026-07-03",
        nova_location_ids=[17],
        billing_account_id=target_account_id,
        billing_schedule_id=target_schedule_id,
    )

    assert preview["customerIdOwnershipMode"] == "preserve_schedule_owners"
    assert preview["billingAccountSelector"] == target_account_id
    assert preview["billingScheduleSelector"] == target_schedule_id
    assert (
        preview["billingAccount"]["desired"]["Billing_Circle_Client_ID__c"]
        == 60128193
    )
    assert preview["detachedBillingAccounts"] == []
    assert preview["preservedBillingAccounts"] == [
        {
            "billingAccountId": canonical_account_id,
            "billingCircleClientId": 11225503,
            "scheduleIds": [canonical_schedule_id],
            "subscriptionIds": [92346505],
        }
    ]
    assert preview["billingSchedule"]["changes"] == {
        "Schedule_Interval__c": "monthly",
        "Start_Date__c": "2026-07-03",
        "Type__c": "subscription",
    }


def test_billing_structure_reuses_existing_schedule_parent_and_detaches_empty_partial_account(
    monkeypatch,
):
    client = _client()
    account_id = "001000000000001AAA"
    canonical_id = "a0B000000000001AAA"
    partial_id = "a0B000000000002AAA"
    schedule_id = "a0S000000000001AAA"
    monkeypatch.setattr(
        client,
        "_assert_operational_ticket_account",
        lambda ticket_id, requested_account_id: {
            "Id": ticket_id,
            "Name": "347392",
            "Account__c": requested_account_id,
        },
    )
    monkeypatch.setattr(
        client,
        "read_billing_account",
        lambda _account_id: {
            "record": {
                "Id": account_id,
                "Name": "HRCR",
            }
        },
    )
    monkeypatch.setattr(
        client,
        "read_billing_structure",
        lambda _account_id: {
            "billingAccounts": [
                {
                    "Id": canonical_id,
                    "Name": "HRCR",
                    "Account__c": account_id,
                    "Billing_Circle_Client_ID__c": 67394090,
                    "Status__c": "Trial",
                },
                {
                    "Id": partial_id,
                    "Name": "HRCR 90373807",
                    "Account__c": account_id,
                    "Billing_Circle_Client_ID__c": 32240775,
                    "Status__c": "Active",
                },
            ],
            "billingSchedules": [
                {
                    "Id": schedule_id,
                    "NovaPOS_Billing_Account__c": canonical_id,
                    "Chargify_Subscription_ID__c": 90373807,
                    "Billing_Circle_Schedule_ID__c": 90373807,
                    "Bill_Amount__c": 1099.90,
                    "Schedule_Interval__c": "monthly",
                    "Start_Date__c": "2026-03-02",
                    "Name": "90373807",
                    "Title__c": "90373807",
                    "Type__c": "subscription",
                }
            ],
            "optionalBillingFieldsAvailable": False,
        },
    )
    monkeypatch.setattr(
        client,
        "read_account_locations",
        lambda _account_id, limit=500: {
            "records": [
                {
                    "Id": "a0L000000000001AAA",
                    "Location_ID__c": 1,
                    "Chargify_Subscription_ID__c": "90373807",
                    "NovaPOS_Billing_Schedule__c": schedule_id,
                }
            ]
        },
    )

    preview = client.billing_structure_alignment_preview(
        "a0G000000000001AAA",
        account_id,
        maxio_customer_id=32240775,
        payment_profile_id=69500976,
        subscription_id=90373807,
        subscription_state="active",
        bill_amount_cents=98_991,
        start_date="2026-03-02",
        nova_location_ids=[1],
    )

    assert preview["billingAccount"]["create"] is False
    assert preview["billingAccount"]["existingId"] == canonical_id
    assert preview["billingAccount"]["changes"]["Billing_Circle_Client_ID__c"] == 32240775
    assert preview["billingSchedule"]["existingId"] == schedule_id
    assert preview["billingSchedule"]["create"] is False
    assert preview["billingSchedule"]["changes"] == {"Bill_Amount__c": 989.91}
    assert preview["detachedBillingAccounts"] == [
        {
            "billingAccountId": partial_id,
            "before": {
                "Billing_Circle_Client_ID__c": 32240775,
                "Status__c": "Active",
            },
            "desired": {
                "Billing_Circle_Client_ID__c": None,
                "Status__c": "Inactive",
            },
        }
    ]


def test_billing_structure_apply_detaches_unique_id_owner_before_syncing_canonical_account(
    monkeypatch,
    tmp_path,
):
    client = ScopedSalesforceClient(
        SalesforceSettings(
            "https://example.invalid",
            "https://login.invalid",
            "",
            "",
            "",
            "",
            "token",
            False,
            journal_path=tmp_path / "salesforce.jsonl",
        )
    )
    account_id = "001000000000001AAA"
    canonical_id = "a0B000000000001AAA"
    partial_id = "a0B000000000002AAA"
    schedule_id = "a0S000000000001AAA"
    location_id = "a0L000000000001AAA"
    plan_hash = "a" * 64
    preview = {
        "ok": True,
        "status": "preview",
        "planHash": plan_hash,
        "duplicate": False,
        "accountId": account_id,
        "subscriptionId": 90373807,
        "novaLocationIds": [1],
        "salesforceLocationIds": [location_id],
        "optionalBillingFieldsAvailable": False,
        "billingAccount": {
            "existingId": canonical_id,
            "create": False,
            "changes": {
                "Billing_Circle_Client_ID__c": 32240775,
                "Status__c": "Active",
            },
            "desired": {
                "Account__c": account_id,
                "Name": "HRCR 90373807",
                "Billing_Circle_Client_ID__c": 32240775,
                "Status__c": "Active",
            },
        },
        "detachedBillingAccounts": [
            {
                "billingAccountId": partial_id,
                "desired": {
                    "Billing_Circle_Client_ID__c": None,
                    "Status__c": "Inactive",
                },
            }
        ],
        "preservedBillingAccounts": [],
        "billingSchedule": {
            "existingId": schedule_id,
            "create": False,
            "changes": {"Bill_Amount__c": 989.91},
            "desired": {
                "NovaPOS_Billing_Account__c": canonical_id,
                "Name": "90373807",
                "Title__c": "90373807",
                "Schedule_Interval__c": "monthly",
                "Bill_Amount__c": 989.91,
                "Start_Date__c": "2026-03-02",
                "Billing_Circle_Schedule_ID__c": 90373807,
                "Chargify_Subscription_ID__c": 90373807,
                "Type__c": "subscription",
            },
        },
        "locationChanges": [],
    }
    monkeypatch.setattr(
        client,
        "billing_structure_alignment_preview",
        lambda *_args, **_kwargs: preview,
    )
    calls = []

    def fake_request(method, path, **kwargs):
        calls.append((method, path, kwargs.get("json")))
        if path.endswith(canonical_id):
            assert any(previous[1].endswith(partial_id) for previous in calls[:-1])
        return {}

    monkeypatch.setattr(client, "_request", fake_request)
    monkeypatch.setattr(
        client,
        "_read_billing_schedule",
        lambda _schedule_id: {"NovaPOS_Billing_Account__c": canonical_id},
    )
    monkeypatch.setattr(
        client,
        "read_billing_structure",
        lambda _account_id: {
            "billingAccounts": [
                dict(preview["billingAccount"]["desired"], Id=canonical_id),
                {
                    "Id": partial_id,
                    "Billing_Circle_Client_ID__c": None,
                    "Status__c": "Inactive",
                },
            ],
            "billingSchedules": [
                dict(preview["billingSchedule"]["desired"], Id=schedule_id)
            ],
        },
    )
    monkeypatch.setattr(
        client,
        "read_account_locations",
        lambda _account_id, limit=500: {
            "records": [
                {
                    "Id": location_id,
                    "Location_ID__c": 1,
                    "Chargify_Subscription_ID__c": "90373807",
                    "NovaPOS_Billing_Schedule__c": schedule_id,
                }
            ]
        },
    )

    result = client.apply_billing_structure_alignment(
        "a0G000000000001AAA",
        account_id,
        maxio_customer_id=32240775,
        payment_profile_id=69500976,
        subscription_id=90373807,
        subscription_state="active",
        bill_amount_cents=98_991,
        start_date="2026-03-02",
        nova_location_ids=[1],
        preview_hash=plan_hash,
        idempotency_key="ticket-347392-hrcr-structure-v4",
    )

    assert calls[0][1].endswith(partial_id)
    assert calls[1][1].endswith(canonical_id)
    assert result["verified"] is True
    assert result["detachedBillingAccountsVerified"] == [partial_id]


def test_billing_structure_accepts_exact_record_selector_for_duplicate_nova_id(
    monkeypatch,
):
    client = _client()
    account_id = "001000000000001AAA"
    billing_account_id = "a0B000000000001AAA"
    schedule_id = "a0S000000000001AAA"
    first_location_id = "a0L000000000001AAA"
    selected_location_id = "a0L000000000002AAA"
    monkeypatch.setattr(
        client,
        "_assert_operational_ticket_account",
        lambda ticket_id, requested_account_id: {
            "Id": ticket_id,
            "Name": "347391",
            "Account__c": requested_account_id,
        },
    )
    monkeypatch.setattr(
        client,
        "read_billing_account",
        lambda _account_id: {
            "record": {
                "Id": account_id,
                "Name": "natures well",
            }
        },
    )
    monkeypatch.setattr(
        client,
        "read_billing_structure",
        lambda _account_id: {
            "billingAccounts": [
                {
                    "Id": billing_account_id,
                    "Name": "natures well 8001",
                    "Account__c": account_id,
                    "Billing_Circle_Client_ID__c": 9001,
                    "Status__c": "Active",
                }
            ],
            "billingSchedules": [
                {
                    "Id": schedule_id,
                    "NovaPOS_Billing_Account__c": billing_account_id,
                    "Chargify_Subscription_ID__c": 8001,
                    "Billing_Circle_Schedule_ID__c": 8001,
                    "Bill_Amount__c": 674.95,
                    "Schedule_Interval__c": "monthly",
                    "Start_Date__c": "2026-07-01",
                    "Name": "8001",
                    "Title__c": "8001",
                    "Type__c": "subscription",
                }
            ],
            "optionalBillingFieldsAvailable": False,
        },
    )
    duplicate_locations = [
        {
            "Id": first_location_id,
            "Name": "Old duplicate",
            "Location_ID__c": 25,
            "Chargify_Subscription_ID__c": None,
            "NovaPOS_Billing_Schedule__c": None,
        },
        {
            "Id": selected_location_id,
            "Name": "Verified official location",
            "Location_ID__c": 25,
            "Chargify_Subscription_ID__c": None,
            "NovaPOS_Billing_Schedule__c": None,
        },
    ]
    monkeypatch.setattr(
        client,
        "read_account_locations",
        lambda _account_id, limit=500: {"records": duplicate_locations},
    )

    with pytest.raises(SalesforceScopeError, match="salesforce_location_ids"):
        client.billing_structure_alignment_preview(
            "a0G000000000001AAA",
            account_id,
            maxio_customer_id=9001,
            payment_profile_id=7001,
            subscription_id=8001,
            subscription_state="active",
            bill_amount_cents=67_495,
            start_date="2026-07-01",
            nova_location_ids=[25],
        )

    preview = client.billing_structure_alignment_preview(
        "a0G000000000001AAA",
        account_id,
        maxio_customer_id=9001,
        payment_profile_id=7001,
        subscription_id=8001,
        subscription_state="active",
        bill_amount_cents=67_495,
        start_date="2026-07-01",
        nova_location_ids=[25],
        salesforce_location_ids=[selected_location_id],
    )

    assert preview["salesforceLocationIds"] == [selected_location_id]
    assert preview["locationChanges"][0]["locationId"] == selected_location_id


def test_billing_structure_read_falls_back_when_optional_rainfall_fields_are_unavailable(
    monkeypatch,
):
    client = _client()
    queries = []

    def fake_query(soql):
        queries.append(soql)
        if "FROM NovaPOS_Billing_Account__c" in soql:
            if "Chargify_Payment_Profile_ID__c" in soql:
                raise SalesforceUnavailableError("optional field is not readable")
            return {
                "records": [
                    {
                        "Id": "a0B000000000001AAA",
                        "Name": "Palm Beach Cosmetics 8001",
                        "Account__c": "001000000000001AAA",
                        "Billing_Circle_Client_ID__c": 9001,
                        "Status__c": "Active",
                    }
                ]
            }
        if "FROM NovaPOS_Billing_Schedule__c" in soql:
            return {"records": []}
        raise AssertionError(soql)

    monkeypatch.setattr(client, "_query", fake_query)
    result = client.read_billing_structure("001000000000001AAA")

    assert result["optionalBillingFieldsAvailable"] is False
    assert result["counts"] == {"billingAccounts": 1, "billingSchedules": 0}
    assert len(queries) == 3


def test_account_closure_requires_inactive_locations_then_reads_back(monkeypatch):
    client = _client()
    account = {
        "Id": "001000000000001AAA",
        "Company_Username__c": "LEJAIM_SPA",
        "Status__c": "New Web Account",
        "Real_Account_Status__c": None,
        "NovaPOS_Active__c": 0,
    }
    monkeypatch.setattr(
        client,
        "read_ticket",
        lambda _ticket_id: {
            "record": {
                "Id": "a0G000000000001AAA",
                "Name": "347191",
                "Account__c": account["Id"],
                "Description__c": "Please cancel all NOVA POS service; all locations closed.",
            }
        },
    )
    monkeypatch.setattr(client, "read_billing_account", lambda _account_id: {"record": dict(account)})
    monkeypatch.setattr(
        client,
        "read_account_locations",
        lambda _account_id: {
            "records": [
                {
                    "Id": "a0L000000000001AAA",
                    "Name": "Main Store",
                    "Location_ID__c": 2,
                    "Status__c": "Inactive",
                },
                {
                    "Id": "a0L000000000002AAA",
                    "Name": "Storage",
                    "Location_ID__c": 4,
                    "Status__c": "Storage",
                },
            ]
        },
    )
    monkeypatch.setattr(
        client,
        "read_account_orders",
        lambda _account_id: {
            "records": [
                {
                    "Id": "a0O000000000001AAA",
                    "Contract_Name__c": "-1 Location. Billing Automation Order",
                    "Description__c": (
                        "Account cancellation under ticket 347191. Locations: 2. "
                        "Chargify subscription: 33583448. "
                        f"Maxio location-component evidence: {'a' * 64}"
                    ),
                    "Location_I_D__c": "2",
                    "Chargify_Subscription_ID__c": 33583448,
                    "Total_Number_of_Locations_for_this_order__c": -1,
                }
            ]
        },
    )

    def fake_request(method, path, **kwargs):
        assert method == "PATCH"
        assert path == "/sobjects/Account/001000000000001AAA"
        account.update(kwargs["json"])
        return {}

    monkeypatch.setattr(client, "_request", fake_request)
    reconciliation = {
        "subscription_ids": [33583448],
        "open_subscription_ids": [],
        "open_location_component_count": 0,
        "maxio_snapshot_hash": "b" * 64,
    }
    preview = client.account_closure_preview(
        "a0G000000000001AAA",
        account["Id"],
        [2],
        [],
        reconciliation,
    )
    result = client.apply_account_closure(
        "a0G000000000001AAA",
        account["Id"],
        [2],
        [],
        reconciliation,
        idempotency_key="ticket-347191-account-close",
        preview_hash=preview["planHash"],
    )

    assert preview["writesPerformed"] is False
    assert preview["desired"] == {"Status__c": "Inactive"}
    assert preview["totalLocationCount"] == 1
    assert preview["locationOrderQuantityTotal"] == 1
    assert preview["locationOrderCoverageVerified"] is True
    assert preview["crossSystemLocationCountsMatch"] is True
    assert result["updated"] is True
    assert result["readback"]["Status__c"] == "Inactive"
    assert result["readback"]["Real_Account_Status__c"] is None


def test_account_closure_accepts_truncated_told_me_to_close_it_request(monkeypatch):
    client = _client()
    account_id = "001000000000001AAA"
    monkeypatch.setattr(
        client,
        "read_ticket",
        lambda _ticket_id: {
            "record": {
                "Id": "a0G000000000001AAA",
                "Account__c": account_id,
                "Description__c": (
                    "old me to close it, Said the business did not work out and "
                    "that he has not used NOVA."
                ),
                "Reason_for_closing_the_account__c": None,
                "Accounts_or_Order_Issue__c": None,
            }
        },
    )

    ticket = client._assert_account_cancellation_ticket(
        "a0G000000000001AAA",
        account_id,
    )

    assert ticket["Account__c"] == account_id


def test_account_closure_truncated_phrase_remains_fail_closed(monkeypatch):
    client = _client()
    account_id = "001000000000001AAA"
    monkeypatch.setattr(
        client,
        "read_ticket",
        lambda _ticket_id: {
            "record": {
                "Id": "a0G000000000001AAA",
                "Account__c": account_id,
                "Description__c": "The old computer was close to the register.",
                "Reason_for_closing_the_account__c": None,
                "Accounts_or_Order_Issue__c": None,
            }
        },
    )

    with pytest.raises(
        SalesforceScopeError,
        match="verified account-cancellation request",
    ):
        client._assert_account_cancellation_ticket(
            "a0G000000000001AAA",
            account_id,
        )


def test_account_closure_rejects_incomplete_orders_and_cross_system_mismatch(
    monkeypatch,
):
    client = _client()
    account_id = "001000000000001AAA"
    monkeypatch.setattr(
        client,
        "_assert_account_cancellation_ticket",
        lambda ticket_id, requested_account_id: {
            "Id": ticket_id,
            "Name": "347600",
            "Account__c": requested_account_id,
        },
    )
    monkeypatch.setattr(
        client,
        "read_billing_account",
        lambda _account_id: {
            "record": {
                "Id": account_id,
                "Company_Username__c": "TWO_SHOPS",
                "Status__c": "Active",
            }
        },
    )
    monkeypatch.setattr(
        client,
        "read_account_locations",
        lambda _account_id: {
            "records": [
                {
                    "Id": "a0L000000000001AAA",
                    "Name": "Shop 2",
                    "Location_ID__c": 2,
                    "Status__c": "Inactive",
                },
                {
                    "Id": "a0L000000000002AAA",
                    "Name": "Shop 4",
                    "Location_ID__c": 4,
                    "Status__c": "Inactive",
                },
            ]
        },
    )
    orders = [
        {
            "Id": "a0O000000000001AAA",
            "Contract_Name__c": "-1 Location. Billing Automation Order",
            "Description__c": (
                "Account cancellation under ticket 347600. Locations: 2. "
                "Chargify subscription: 8001. "
                f"Maxio location-component evidence: {'a' * 64}"
            ),
            "Location_I_D__c": "2",
            "Chargify_Subscription_ID__c": 8001,
            "Total_Number_of_Locations_for_this_order__c": -1,
        }
    ]
    monkeypatch.setattr(
        client,
        "read_account_orders",
        lambda _account_id: {"records": list(orders)},
    )
    closed_evidence = {
        "subscription_ids": [8001, 9002],
        "open_subscription_ids": [],
        "open_location_component_count": 0,
        "maxio_snapshot_hash": "c" * 64,
    }

    with pytest.raises(SalesforceScopeError, match="location total does not match"):
        client.account_closure_preview(
            "a0G000000000001AAA",
            account_id,
            [2, 4],
            [],
            closed_evidence,
        )

    orders.append(
        {
            "Id": "a0O000000000002AAA",
            "Contract_Name__c": "-1 Location. Billing Automation Order",
            "Description__c": (
                "Account cancellation under ticket 347600. Locations: 4. "
                "Chargify subscription: 9002. "
                f"Maxio location-component evidence: {'b' * 64}"
            ),
            "Location_I_D__c": "4",
            "Chargify_Subscription_ID__c": 9002,
            "Total_Number_of_Locations_for_this_order__c": -1,
        }
    )
    with pytest.raises(SalesforceScopeError, match="zero active non-storage"):
        client.account_closure_preview(
            "a0G000000000001AAA",
            account_id,
            [2, 4],
            [4],
            closed_evidence,
        )
    with pytest.raises(SalesforceScopeError, match="no open subscriptions"):
        client.account_closure_preview(
            "a0G000000000001AAA",
            account_id,
            [2, 4],
            [],
            {
                "subscription_ids": [8001, 9002],
                "open_subscription_ids": [9002],
                "open_location_component_count": 1,
                "maxio_snapshot_hash": "d" * 64,
            },
        )


def test_cancellation_order_apply_creates_once_submits_approval_and_reads_back(
    monkeypatch,
    tmp_path,
):
    client = _client(tmp_path / "salesforce.jsonl")
    account_id = "001000000000001AAA"
    ticket_id = "a0G000000000001AAA"
    order_id = "a0O000000000001AAA"
    approval_state = {"submitted": False}
    requests = []
    monkeypatch.setattr(
        client,
        "_assert_account_cancellation_ticket",
        lambda _ticket_id, _account_id: {
            "Id": ticket_id,
            "Name": "347191",
            "Account__c": account_id,
            "Description__c": "Cancel account.",
        },
    )
    monkeypatch.setattr(
        client,
        "read_billing_account",
        lambda _account_id: {
            "record": {
                "Id": account_id,
                "Company_Username__c": "LEJAIM_SPA",
                "OwnerId": "005000000000001AAA",
            }
        },
    )
    monkeypatch.setattr(
        client,
        "read_account_locations",
        lambda _account_id: {
            "records": [
                {
                    "Id": "a0L000000000001AAA",
                    "Location_ID__c": 4.0,
                    "Status__c": "Storage",
                    "Chargify_Subscription_ID__c": "33583448",
                },
                {
                    "Id": "a0L000000000002AAA",
                    "Location_ID__c": "2.0",
                    "Status__c": "Inactive",
                    "Chargify_Subscription_ID__c": "33583448",
                },
            ]
        },
    )
    monkeypatch.setattr(
        client,
        "_resolve_cancellation_order_record_type",
        lambda: {
            "Id": "012000000000001AAA",
            "Name": "Existing Customer Cancellation Order",
            "DeveloperName": "Existing_Customer_Cancellation_Order",
        },
    )
    monkeypatch.setattr(
        client,
        "_resolve_order_picklist_value",
        lambda _record_type_id, field_name, _requested, **_kwargs: (
            "Business Closed"
            if field_name == "Reason_for_cancellation__c"
            else None
        ),
    )
    monkeypatch.setattr(client, "read_account_orders", lambda _account_id: {"records": []})
    monkeypatch.setattr(
        client,
        "_order_approval_state",
        lambda _order_id: {
            "submitted": approval_state["submitted"],
            "status": "Pending" if approval_state["submitted"] else "",
            "records": [{"Id": "04g000000000001AAA"}] if approval_state["submitted"] else [],
        },
    )
    monkeypatch.setattr(
        client,
        "lookup",
        lambda kind, value, **_kwargs: {
            "records": [
                {
                    "Id": value,
                    "Account__c": account_id,
                    "RecordTypeId": "012000000000001AAA",
                    "Contract_Name__c": "-1 Location. Billing Automation Order",
                    "Description__c": (
                        "Account cancellation under ticket 347191. Locations: 2. "
                        "Chargify subscription: 33583448. "
                        f"Maxio location-component evidence: {'a' * 64}"
                    ),
                    "Reason_for_cancellation__c": "Business Closed",
                    "Location_I_D__c": "2",
                    "Chargify_Subscription_ID__c": "33583448",
                    "Total_Number_of_Locations_for_this_order__c": -1.0,
                }
            ]
            if kind == "order"
            else []
        },
    )

    def fake_request(method, path, **kwargs):
        requests.append((method, path, kwargs.get("json")))
        if path == "/sobjects/NovaPOS_Order__c":
            return {"id": order_id, "success": True}
        if path == "/process/approvals/":
            approval_state["submitted"] = True
            return [{"success": True, "entityId": order_id}]
        raise AssertionError(path)

    monkeypatch.setattr(client, "_request", fake_request)
    with pytest.raises(
        SalesforceScopeError,
        match="exactly match the official Nova",
    ):
        client.cancellation_order_preview(
            ticket_id,
            account_id,
            ["a0L000000000002AAA"],
            [2, 3],
            [
                {
                    "subscription_id": 33583448,
                    "location_component_deallocation_count": 1,
                    "maxio_preview_hash": "a" * 64,
                }
            ],
            "Business Closed",
        )
    with pytest.raises(
        SalesforceScopeError,
        match="Maxio location-component deallocation count",
    ):
        client.cancellation_order_preview(
            ticket_id,
            account_id,
            ["a0L000000000002AAA"],
            [2],
            [
                {
                    "subscription_id": 33583448,
                    "location_component_deallocation_count": 18,
                    "maxio_preview_hash": "a" * 64,
                }
            ],
            "Business Closed",
            notes="Cancellation NOVA.pdf received.",
        )
    with pytest.raises(SalesforceScopeError, match="storage row"):
        client.cancellation_order_preview(
            ticket_id,
            account_id,
            ["a0L000000000001AAA"],
            [4],
            [
                {
                    "subscription_id": 33583448,
                    "location_component_deallocation_count": 1,
                    "maxio_preview_hash": "a" * 64,
                }
            ],
            "Business Closed",
            notes="Cancellation NOVA.pdf received.",
        )
    preview = client.cancellation_order_preview(
        ticket_id,
        account_id,
        ["a0L000000000002AAA"],
        [2],
        [
            {
                "subscription_id": 33583448,
                "location_component_deallocation_count": 1,
                "maxio_preview_hash": "a" * 64,
            }
        ],
        "Business Closed",
        notes="Cancellation NOVA.pdf received.",
    )
    result = client.apply_cancellation_order(
        ticket_id,
        account_id,
        ["a0L000000000002AAA"],
        [2],
        [
            {
                "subscription_id": 33583448,
                "location_component_deallocation_count": 1,
                "maxio_preview_hash": "a" * 64,
            }
        ],
        "Business Closed",
        notes="Cancellation NOVA.pdf received.",
        idempotency_key="ticket-347191-cancellation-order",
        preview_hash=preview["planHash"],
    )

    assert preview["orderFields"]["Location_I_D__c"] == "2"
    assert preview["orderFields"]["Chargify_Subscription_ID__c"] == 33583448
    assert preview["orderFields"]["Total_Number_of_Locations_for_this_order__c"] == -1
    assert preview["orderFields"]["Contract_Name__c"] == (
        "-1 Location. Billing Automation Order"
    )
    assert preview["locationComponentDeallocationCount"] == 1
    assert preview["totalLocationCount"] == 1
    assert preview["locationOrderQuantityTotal"] == 1
    assert preview["locationOrderCoverageVerified"] is True
    assert preview["orderCount"] == 1
    assert preview["oneOrderPerSubscription"] is True
    assert "Existing_Order_Type__c" not in preview["orderFields"]
    assert result["created"] is True
    assert result["approvalSubmitted"] is True
    assert result["approvalApplicable"] is True
    assert result["approvalDisposition"] == "submitted"
    assert [path for _, path, _ in requests] == [
        "/sobjects/NovaPOS_Order__c",
        "/process/approvals/",
    ]


def test_location_cancellation_preview_groups_exact_locations_one_order_per_subscription(
    monkeypatch,
):
    client = _client()
    account_id = "001000000000001AAA"
    ticket_id = "a0G000000000001AAA"
    selected_ids = [
        "a0L000000000001AAA",
        "a0L000000000002AAA",
        "a0L000000000003AAA",
    ]
    monkeypatch.setattr(
        client,
        "_assert_account_cancellation_ticket",
        lambda _ticket_id, _account_id: {
            "Id": ticket_id,
            "Name": "347500",
            "Account__c": account_id,
            "Description__c": "Close locations 2, 4, and 8.",
        },
    )
    monkeypatch.setattr(
        client,
        "read_billing_account",
        lambda _account_id: {
            "record": {
                "Id": account_id,
                "Company_Username__c": "MULTI_SHOP",
                "OwnerId": "005000000000001AAA",
            }
        },
    )
    monkeypatch.setattr(
        client,
        "read_account_locations",
        lambda _account_id: {
            "records": [
                {
                    "Id": selected_ids[0],
                    "Location_ID__c": 2,
                    "Status__c": "Inactive",
                    "Chargify_Subscription_ID__c": "8001",
                },
                {
                    "Id": selected_ids[1],
                    "Location_ID__c": 4,
                    "Status__c": "Inactive",
                    "Chargify_Subscription_ID__c": 8001.0,
                },
                {
                    "Id": selected_ids[2],
                    "Location_ID__c": 8,
                    "Status__c": "Inactive",
                    "Chargify_Subscription_ID__c": "9002",
                },
                {
                    "Id": "a0L000000000004AAA",
                    "Location_ID__c": 10,
                    "Status__c": "Active",
                    "Chargify_Subscription_ID__c": "9002",
                },
            ]
        },
    )
    monkeypatch.setattr(
        client,
        "_resolve_cancellation_order_record_type",
        lambda: {
            "Id": "012000000000001AAA",
            "Name": "Existing Customer Cancellation Order",
            "DeveloperName": "Existing_Customer_Cancellation_Order",
        },
    )
    monkeypatch.setattr(
        client,
        "_resolve_order_picklist_value",
        lambda _record_type_id, field_name, _requested, **_kwargs: (
            "Business / Location Closing"
            if field_name == "Reason_for_cancellation__c"
            else None
        ),
    )
    monkeypatch.setattr(
        client,
        "read_account_orders",
        lambda _account_id: {
            "records": [
                {
                    "Id": "a0O000000000001AAA",
                    "RecordTypeId": "012000000000001AAA",
                    "Reason_for_cancellation__c": "Business / Location Closing",
                    "Location_I_D__c": "2,4",
                    "Chargify_Subscription_ID__c": "8001",
                    "Total_Number_of_Locations_for_this_order__c": -18,
                    "Contract_Name__c": "-18 Locations. Billing Automation Order",
                    "Description__c": (
                        "Location cancellation under ticket 347500. Locations: 2,4. "
                        "Chargify subscription: 8001. "
                        f"Maxio location-component evidence: {'a' * 64}"
                    ),
                },
                {
                    "Id": "a0O000000000098AAA",
                    "RecordTypeId": "012000000000001AAA",
                    "Reason_for_cancellation__c": "Business / Location Closing",
                    "Location_I_D__c": "8,not-a-location",
                    "Chargify_Subscription_ID__c": "9002",
                },
                {
                    "Id": "a0O000000000099AAA",
                    "RecordTypeId": "012000000000001AAA",
                    "Reason_for_cancellation__c": "Business / Location Closing",
                    "Location_I_D__c": "8",
                    "Chargify_Subscription_ID__c": None,
                },
            ]
        },
    )

    preview = client.location_cancellation_order_preview(
        ticket_id,
        account_id,
        selected_ids,
        [
            {
                "subscription_id": 8001,
                "location_component_deallocation_count": 2,
                "maxio_preview_hash": "a" * 64,
            },
            {
                "subscription_id": 9002,
                "location_component_deallocation_count": 1,
                "maxio_preview_hash": "b" * 64,
            },
        ],
        "Business Closed",
    )

    assert preview["scope"] == "location"
    assert preview["orderCount"] == 2
    assert preview["subscriptionIds"] == [8001, 9002]
    assert preview["remainingActiveLocationRecordIds"] == [
        "a0L000000000004AAA"
    ]
    assert preview["orders"][0]["locationIds"] == ["2", "4"]
    assert preview["orders"][0]["orderFields"]["Chargify_Subscription_ID__c"] == 8001
    assert preview["orders"][0]["duplicateOrder"] is None
    assert preview["orders"][0]["orderFields"]["Contract_Name__c"] == (
        "-2 Locations. Billing Automation Order"
    )
    assert preview["orders"][1]["locationIds"] == ["8"]
    assert preview["orders"][1]["orderFields"]["Chargify_Subscription_ID__c"] == 9002
    assert preview["orders"][1]["duplicateOrder"] is None
    assert "orderFields" not in preview


def test_location_cancellation_preview_rejects_missing_subscription_and_last_location(
    monkeypatch,
):
    client = _client()
    account_id = "001000000000001AAA"
    selected_id = "a0L000000000001AAA"
    monkeypatch.setattr(
        client,
        "_assert_account_cancellation_ticket",
        lambda ticket_id, requested_account_id: {
            "Id": ticket_id,
            "Name": "347500",
            "Account__c": requested_account_id,
        },
    )
    monkeypatch.setattr(
        client,
        "read_billing_account",
        lambda _account_id: {"record": {"Id": account_id}},
    )
    locations = [
        {
            "Id": selected_id,
            "Location_ID__c": 2,
            "Status__c": "Inactive",
            "Chargify_Subscription_ID__c": None,
        },
        {
            "Id": "a0L000000000002AAA",
            "Location_ID__c": 4,
            "Status__c": "Active",
            "Chargify_Subscription_ID__c": "8001",
        },
    ]
    monkeypatch.setattr(
        client,
        "read_account_locations",
        lambda _account_id: {"records": list(locations)},
    )

    with pytest.raises(SalesforceScopeError, match="missing it"):
        client.location_cancellation_order_preview(
            "a0G000000000001AAA",
            account_id,
            [selected_id],
            [
                {
                    "subscription_id": 8001,
                    "location_component_deallocation_count": 1,
                    "maxio_preview_hash": "a" * 64,
                }
            ],
            "Business Closed",
        )

    locations[0]["Chargify_Subscription_ID__c"] = "8001"
    locations[1]["Status__c"] = "Inactive"
    with pytest.raises(SalesforceScopeError, match="full-account"):
        client.location_cancellation_order_preview(
            "a0G000000000001AAA",
            account_id,
            [selected_id],
            [
                {
                    "subscription_id": 8001,
                    "location_component_deallocation_count": 1,
                    "maxio_preview_hash": "a" * 64,
                }
            ],
            "Business Closed",
        )


def test_full_account_cancellation_apply_creates_separate_verified_orders_per_subscription(
    monkeypatch,
    tmp_path,
):
    client = _client(tmp_path / "salesforce.jsonl")
    account_id = "001000000000001AAA"
    ticket_id = "a0G000000000001AAA"
    order_ids = iter(["a0O000000000001AAA", "a0O000000000002AAA"])
    created_fields: dict[str, dict] = {}
    approval_state: dict[str, bool] = {}
    monkeypatch.setattr(
        client,
        "_assert_account_cancellation_ticket",
        lambda _ticket_id, _account_id: {
            "Id": ticket_id,
            "Name": "347501",
            "Account__c": account_id,
        },
    )
    monkeypatch.setattr(
        client,
        "read_billing_account",
        lambda _account_id: {
            "record": {
                "Id": account_id,
                "Company_Username__c": "MULTI_SHOP",
                "OwnerId": "005000000000001AAA",
            }
        },
    )
    monkeypatch.setattr(
        client,
        "read_account_locations",
        lambda _account_id: {
            "records": [
                {
                    "Id": "a0L000000000001AAA",
                    "Location_ID__c": 2,
                    "Status__c": "Inactive",
                    "Chargify_Subscription_ID__c": "8001",
                },
                {
                    "Id": "a0L000000000002AAA",
                    "Location_ID__c": 4,
                    "Status__c": "Inactive",
                    "Chargify_Subscription_ID__c": "9002",
                },
            ]
        },
    )
    monkeypatch.setattr(
        client,
        "_resolve_cancellation_order_record_type",
        lambda: {
            "Id": "012000000000001AAA",
            "Name": "Existing Customer Cancellation Order",
            "DeveloperName": "Existing_Customer_Cancellation_Order",
        },
    )
    monkeypatch.setattr(
        client,
        "_resolve_order_picklist_value",
        lambda _record_type_id, field_name, _requested, **_kwargs: (
            "Business / Location Closing"
            if field_name == "Reason_for_cancellation__c"
            else None
        ),
    )
    monkeypatch.setattr(client, "read_account_orders", lambda _account_id: {"records": []})
    monkeypatch.setattr(
        client,
        "_order_approval_state",
        lambda order_id: {
            "submitted": approval_state.get(order_id, False),
            "status": "Pending" if approval_state.get(order_id, False) else "",
            "records": (
                [{"Id": f"04g{order_id[-6:]}"}]
                if approval_state.get(order_id, False)
                else []
            ),
        },
    )
    monkeypatch.setattr(
        client,
        "lookup",
        lambda kind, value, **_kwargs: {
            "records": [{"Id": value, **created_fields[value]}]
            if kind == "order" and value in created_fields
            else []
        },
    )

    def fake_request(method, path, **kwargs):
        if method == "POST" and path == "/sobjects/NovaPOS_Order__c":
            order_id = next(order_ids)
            created_fields[order_id] = dict(kwargs["json"])
            approval_state[order_id] = False
            return {"id": order_id, "success": True}
        if method == "POST" and path == "/process/approvals/":
            order_id = kwargs["json"]["requests"][0]["contextId"]
            approval_state[order_id] = True
            return [{"success": True, "entityId": order_id}]
        raise AssertionError((method, path))

    monkeypatch.setattr(client, "_request", fake_request)
    preview = client.cancellation_order_preview(
        ticket_id,
        account_id,
        [
            "a0L000000000001AAA",
            "a0L000000000002AAA",
        ],
        [2, 4],
        [
            {
                "subscription_id": 8001,
                "location_component_deallocation_count": 1,
                "maxio_preview_hash": "a" * 64,
            },
            {
                "subscription_id": 9002,
                "location_component_deallocation_count": 1,
                "maxio_preview_hash": "b" * 64,
            },
        ],
        "Business Closed",
    )
    result = client.apply_cancellation_order(
        ticket_id,
        account_id,
        [
            "a0L000000000001AAA",
            "a0L000000000002AAA",
        ],
        [2, 4],
        [
            {
                "subscription_id": 8001,
                "location_component_deallocation_count": 1,
                "maxio_preview_hash": "a" * 64,
            },
            {
                "subscription_id": 9002,
                "location_component_deallocation_count": 1,
                "maxio_preview_hash": "b" * 64,
            },
        ],
        "Business Closed",
        idempotency_key="ticket-347501-cancellation-orders",
        preview_hash=preview["planHash"],
    )

    assert preview["orderCount"] == 2
    assert [row["subscriptionId"] for row in preview["orders"]] == [8001, 9002]
    assert result["createdCount"] == 2
    assert result["duplicateCount"] == 0
    assert result["allOrdersSubscriptionLinked"] is True
    assert [row["subscriptionId"] for row in result["orders"]] == [8001, 9002]
    assert all(row["approvalDisposition"] == "submitted" for row in result["orders"])
    assert {
        int(fields["Chargify_Subscription_ID__c"])
        for fields in created_fields.values()
    } == {8001, 9002}


def test_generic_order_create_rejects_cancellation_payload(monkeypatch):
    client = _client()
    monkeypatch.setattr(
        client,
        "_request",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("generic cancellation order must not be written")
        ),
    )

    with pytest.raises(SalesforceScopeError, match="typed account- or location-cancellation"):
        client.create_order(
            {
                "Account__c": "001000000000001AAA",
                "Reason_for_cancellation__c": "Business / Location Closing",
                "Location_I_D__c": "2",
                "Chargify_Subscription_ID__c": 8001,
                "Total_Number_of_Locations_for_this_order__c": -1,
            }
        )


def test_generic_order_create_permanently_rejects_new_customer_order(monkeypatch):
    client = _client()
    monkeypatch.setattr(
        client,
        "_request",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("New Customer Order must never be written by an agent")
        ),
    )

    with pytest.raises(SalesforceScopeError, match="reserved for the website's first order"):
        client.create_order(
            {
                "Account__c": "001000000000001AAA",
                "Existing_Order_Type__c": "New Customer Order",
            }
        )


def test_generic_order_create_rejects_reactivation_from_decline_field(monkeypatch):
    client = _client()
    monkeypatch.setattr(
        client,
        "_request",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("Reactivation from Decline must never be written")
        ),
    )

    with pytest.raises(SalesforceScopeError, match="not allowed"):
        client.create_order(
            {
                "Account__c": "001000000000001AAA",
                "Existing_Order_Type__c": "Re-activate an Existing Location",
                "Reactivation_from_Decline__c": True,
            }
        )


def test_cancellation_order_apply_accepts_exact_no_applicable_process_with_order_readback(
    monkeypatch,
    tmp_path,
):
    client = _client(tmp_path / "salesforce.jsonl")
    order_id = "a0O000000000001AAA"
    order_fields = {
        "Account__c": "001000000000001AAA",
        "RecordTypeId": "012000000000001AAA",
        "Contract_Name__c": "-1 Location. Billing Automation Order",
        "Description__c": (
            "Account cancellation under ticket 347191. Locations: 2. "
            "Chargify subscription: 33583448. "
            f"Maxio location-component evidence: {'a' * 64}"
        ),
        "Reason_for_cancellation__c": "Business Closed",
        "Location_I_D__c": "2",
        "Chargify_Subscription_ID__c": 33583448,
        "Total_Number_of_Locations_for_this_order__c": -1,
    }
    preview = {
        "ok": True,
        "status": "preview",
        "verified": True,
        "scope": "account",
        "accountId": "001000000000001AAA",
        "ticketNumber": "347191",
        "planHash": "a" * 64,
        "orders": [
            {
                "subscriptionId": 33583448,
                "locationRecordIds": ["a0L000000000001AAA"],
                "locationIds": ["2"],
                "orderFields": order_fields,
                "duplicateOrder": {"Id": order_id},
            }
        ],
        "writesPerformed": False,
    }
    monkeypatch.setattr(client, "cancellation_order_preview", lambda *_args, **_kwargs: preview)
    monkeypatch.setattr(
        client,
        "_order_approval_state",
        lambda _order_id: {"submitted": False, "status": "", "records": []},
    )
    monkeypatch.setattr(
        client,
        "lookup",
        lambda kind, value, **_kwargs: {
            "records": [
                {
                    "Id": value,
                    "Name": "C-066068-202607",
                    **order_fields,
                }
            ]
            if kind == "order"
            else []
        },
    )

    def fake_request(method, path, **_kwargs):
        assert method == "POST"
        assert path == "/process/approvals/"
        raise SalesforceUnavailableError(
            "Salesforce operation failed with status 400 (NO_APPLICABLE_PROCESS)"
        )

    monkeypatch.setattr(client, "_request", fake_request)

    result = client.apply_cancellation_order(
        "a0G000000000001AAA",
        "001000000000001AAA",
        ["a0L000000000001AAA"],
        [2],
        [
            {
                "subscription_id": 33583448,
                "location_component_deallocation_count": 1,
                "maxio_preview_hash": "a" * 64,
            }
        ],
        "Business Closed",
        idempotency_key="ticket-347191-existing-order",
        preview_hash="a" * 64,
    )

    assert result["created"] is False
    assert result["duplicate"] is True
    assert result["approvalSubmitted"] is False
    assert result["approvalApplicable"] is False
    assert result["approvalDisposition"] == "not_applicable"
    assert result["providerResult"]["errorCode"] == "NO_APPLICABLE_PROCESS"
    assert result["readback"]["Id"] == order_id


def test_cancellation_order_apply_repairs_blank_evidence_on_exact_existing_order(
    monkeypatch,
    tmp_path,
):
    client = _client(tmp_path / "salesforce.jsonl")
    account_id = "001000000000001AAA"
    ticket_id = "a0G000000000001AAA"
    order_id = "a0O000000000001AAA"
    location_id = "a0L000000000001AAA"
    order = {
        "Id": order_id,
        "Account__c": account_id,
        "RecordTypeId": "012000000000001AAA",
        "Contract_Name__c": "-1 Location. Billing Automation Order",
        "Description__c": "",
        "Reason_for_cancellation__c": "Business Closed",
        "Location_I_D__c": "1",
        "Chargify_Subscription_ID__c": 33583448,
        "Total_Number_of_Locations_for_this_order__c": -1,
    }
    requests = []
    monkeypatch.setattr(
        client,
        "_assert_account_cancellation_ticket",
        lambda _ticket_id, _account_id: {
            "Id": ticket_id,
            "Name": "347695",
            "Account__c": account_id,
            "Description__c": "Cancel account.",
        },
    )
    monkeypatch.setattr(
        client,
        "read_billing_account",
        lambda _account_id: {
            "record": {
                "Id": account_id,
                "Company_Username__c": "DABBLEDABS",
                "OwnerId": "005000000000001AAA",
            }
        },
    )
    monkeypatch.setattr(
        client,
        "read_account_locations",
        lambda _account_id: {
            "records": [
                {
                    "Id": location_id,
                    "Location_ID__c": "1",
                    "Status__c": "Inactive",
                    "Chargify_Subscription_ID__c": "33583448",
                }
            ]
        },
    )
    monkeypatch.setattr(
        client,
        "_resolve_cancellation_order_record_type",
        lambda: {
            "Id": "012000000000001AAA",
            "Name": "Existing Customer Cancellation Order",
            "DeveloperName": "Existing_Customer_Cancellation_Order",
        },
    )
    monkeypatch.setattr(
        client,
        "_resolve_order_picklist_value",
        lambda _record_type_id, field_name, _requested, **_kwargs: (
            "Business Closed"
            if field_name == "Reason_for_cancellation__c"
            else None
        ),
    )
    monkeypatch.setattr(
        client,
        "read_account_orders",
        lambda _account_id: {"records": [dict(order)]},
    )
    monkeypatch.setattr(
        client,
        "_order_approval_state",
        lambda _order_id: {
            "submitted": True,
            "status": "Pending",
            "records": [{"Id": "04g000000000001AAA"}],
        },
    )
    monkeypatch.setattr(
        client,
        "lookup",
        lambda kind, value, **_kwargs: {
            "records": [dict(order)] if kind == "order" and value == order_id else []
        },
    )

    def fake_request(method, path, **kwargs):
        requests.append((method, path, kwargs.get("json")))
        assert method == "PATCH"
        assert path == f"/sobjects/NovaPOS_Order__c/{order_id}"
        assert set(kwargs["json"]) == {"Description__c"}
        order.update(kwargs["json"])
        return {}

    monkeypatch.setattr(client, "_request", fake_request)
    deallocation = [
        {
            "subscription_id": 33583448,
            "location_component_deallocation_count": 1,
            "maxio_preview_hash": "a" * 64,
        }
    ]
    order["Description__c"] = "Legacy note without ticket or Maxio evidence."
    with pytest.raises(SalesforceScopeError, match="different nonblank evidence"):
        client.cancellation_order_preview(
            ticket_id,
            account_id,
            [location_id],
            [1],
            deallocation,
            "Business Closed",
        )
    order["Description__c"] = ""
    preview = client.cancellation_order_preview(
        ticket_id,
        account_id,
        [location_id],
        [1],
        deallocation,
        "Business Closed",
    )

    assert preview["duplicateOrder"] is None
    assert preview["evidenceRepairOrder"]["Id"] == order_id
    assert preview["evidenceRepairCount"] == 1

    result = client.apply_cancellation_order(
        ticket_id,
        account_id,
        [location_id],
        [1],
        deallocation,
        "Business Closed",
        idempotency_key="ticket-347695-existing-order-evidence-repair",
        preview_hash=preview["planHash"],
    )

    assert requests == [
        (
            "PATCH",
            f"/sobjects/NovaPOS_Order__c/{order_id}",
            {"Description__c": preview["orderFields"]["Description__c"]},
        )
    ]
    assert result["created"] is False
    assert result["updated"] is True
    assert result["duplicate"] is False
    assert result["evidenceRepairedCount"] == 1
    assert result["orders"][0]["evidenceRepaired"] is True
    assert "ticket 347695" in result["readback"]["Description__c"]
    assert "Maxio location-component evidence" in result["readback"]["Description__c"]


def _configure_location_lifecycle_order(
    monkeypatch,
    client,
    *,
    integrated=True,
    rate=99.99,
    created_date="2026-07-01T12:00:00.000+0000",
    terms_agreed_on="2026-07-01T12:00:00.000+0000",
    ticket_record_type="3. Billing",
):
    ticket_id = "a0G000000000001AAA"
    account_id = "001000000000001AAA"
    location_record_id = "a0L000000000001AAA"
    order_record_type_id = "012000000000001AAA"
    subscription_id = 93250402
    created_orders = []
    classifications = []
    monkeypatch.setattr(
        client,
        "ticket_scope",
        lambda _ticket_id: {
            "ticketId": ticket_id,
            "recordTypeId": "012000000000009AAA",
            "recordTypeName": ticket_record_type,
        },
    )
    monkeypatch.setattr(
        client,
        "read_ticket",
        lambda _ticket_id: {
            "record": {"Id": ticket_id, "Name": "347353", "Account__c": account_id}
        },
    )

    def fake_query(soql):
        if "FROM Account" in soql:
            return {
                "records": [
                    {
                        "Id": account_id,
                        "Name": "Example Account",
                        "CreatedDate": created_date,
                        "Terms_agreed_on__c": terms_agreed_on,
                        "OwnerId": "005000000000001AAA",
                        "Nova_Account_Manager__c": None,
                        "Flat_Rate_Amount__c": None,
                    }
                ]
            }
        if "FROM NovaPOS_Location__c" in soql:
            return {
                "records": [
                    {
                        "Id": location_record_id,
                        "Name": "Location 1",
                        "Account__c": account_id,
                        "Location_ID__c": 1,
                        "Status__c": "Active",
                        "Bill_Amount__c": rate,
                        "Chargify_Subscription_ID__c": subscription_id,
                        "NovaPOS_Billing_Schedule__c": "a1B000000000001AAA",
                        "Is_Location_on_GSPayTech_Gateway__c": integrated,
                    }
                ]
            }
        raise AssertionError(soql)

    def resolve_record_type(classification):
        classifications.append(classification)
        return {
            "Id": order_record_type_id,
            "Name": classification,
            "DeveloperName": classification,
        }

    order_type_labels = {
        "reactivate_existing_location": "Re-activate an Existing Location",
        "within_3_months": {
            "reactivate_existing_location": "Re-activate an Existing Location",
            "add_additional_location": "New Location",
        },
        "existing_additional": "Existing and (New) Additional Customer Order",
    }
    monkeypatch.setattr(client, "_query", fake_query)
    monkeypatch.setattr(client, "read_account_orders", lambda _account_id: {"records": []})
    monkeypatch.setattr(client, "_resolve_location_lifecycle_order_record_type", resolve_record_type)
    monkeypatch.setattr(
        client,
        "_resolve_location_lifecycle_order_type",
        lambda _record_type_id, classification, action: (
            order_type_labels[classification][action]
            if isinstance(order_type_labels[classification], dict)
            else order_type_labels[classification]
        ),
    )
    monkeypatch.setattr(
        client,
        "_order_approval_state",
        lambda _order_id: {"submitted": False, "status": "", "records": []},
    )

    def fake_request(method, path, **kwargs):
        assert method == "POST"
        assert path == "/sobjects/NovaPOS_Order__c"
        created_orders.append(dict(kwargs["json"]))
        return {"id": "a0O000000000001AAA"}

    monkeypatch.setattr(client, "_request", fake_request)
    monkeypatch.setattr(
        client,
        "lookup",
        lambda _kind, _record_id, limit=1: {
            "records": [{"Id": _record_id, **created_orders[-1]}]
        },
    )
    return {
        "ticket_id": ticket_id,
        "account_id": account_id,
        "location_record_id": location_record_id,
        "subscription_id": subscription_id,
        "created_orders": created_orders,
        "classifications": classifications,
    }


def test_reactivation_order_approval_is_permanently_disabled():
    client = _client()
    with pytest.raises(SalesforceScopeError, match="approval is prohibited"):
        client.reactivation_order_approval_preview(
            "a0G000000000001AAA",
            "a0O000000000001AAA",
        )
    with pytest.raises(SalesforceScopeError, match="approval is prohibited"):
        client.apply_reactivation_order_approval(
            "a0G000000000001AAA",
            "a0O000000000001AAA",
            idempotency_key="ticket-347353-retired-approval",
            preview_hash="a" * 64,
        )


@pytest.mark.parametrize(
    "ticket_record_type",
    ["1. NOVA Classic", "2. Nova Wave", "3. Billing"],
)
def test_location_lifecycle_order_accepts_every_customer_operation_ticket_type(
    monkeypatch,
    ticket_record_type,
):
    client = _client()
    state = _configure_location_lifecycle_order(
        monkeypatch,
        client,
        ticket_record_type=ticket_record_type,
    )

    preview = client.location_lifecycle_order_preview(
        state["ticket_id"],
        state["account_id"],
        [state["location_record_id"]],
        "reactivate_existing_location",
        state["subscription_id"],
    )

    assert preview["ticketId"] == state["ticket_id"]
    assert preview["accountId"] == state["account_id"]


def test_location_lifecycle_order_rejects_non_customer_operation_ticket_type(monkeypatch):
    client = _client()
    state = _configure_location_lifecycle_order(
        monkeypatch,
        client,
        ticket_record_type="Account Management",
    )

    with pytest.raises(SalesforceScopeError, match="outside this agent lane"):
        client.location_lifecycle_order_preview(
            state["ticket_id"],
            state["account_id"],
            [state["location_record_id"]],
            "reactivate_existing_location",
            state["subscription_id"],
        )


def test_reactivation_lifecycle_order_populates_required_fields_and_never_submits_approval(
    monkeypatch,
    tmp_path,
):
    client = _client(tmp_path / "salesforce.jsonl")
    state = _configure_location_lifecycle_order(monkeypatch, client)
    monkeypatch.setattr(
        salesforce_client_module,
        "_within_first_three_calendar_months",
        lambda *_args: pytest.fail("reactivations must not use the three-month classifier"),
    )
    preview = client.location_lifecycle_order_preview(
        state["ticket_id"],
        state["account_id"],
        [state["location_record_id"]],
        "reactivate_existing_location",
        state["subscription_id"],
    )
    result = client.apply_location_lifecycle_order(
        state["ticket_id"],
        state["account_id"],
        [state["location_record_id"]],
        "reactivate_existing_location",
        state["subscription_id"],
        preview_hash=preview["previewHash"],
        idempotency_key="ticket-347353-reactivation-order-v1",
    )

    fields = state["created_orders"][0]
    assert fields["Existing_Order_Type__c"] == "Re-activate an Existing Location"
    assert preview["classification"] == "reactivate_existing_location"
    assert preview["classificationDateField"] == "CreatedDate"
    assert preview["withinFirstThreeCalendarMonths"] is False
    assert fields["Location_I_D__c"] == "1"
    assert fields["Chargify_Subscription_ID__c"] == state["subscription_id"]
    assert fields["Total_Number_of_Locations_for_this_order__c"] == 1
    assert fields["Billing_Start_Date1__c"]
    assert "Reactivation_from_Decline__c" not in fields
    assert "Location_Reactivated_in_NovaPOS__c" not in fields
    assert "Account_Activated_in_NovaPOS__c" not in fields
    assert result["approvalSubmitted"] is False
    assert result["approvalSubmissionProhibited"] is True
    assert result["verified"] is True


def test_lifecycle_order_reclassifies_one_exact_wrong_record_without_creating_duplicate(
    monkeypatch,
    tmp_path,
):
    client = _client(tmp_path / "salesforce.jsonl")
    state = _configure_location_lifecycle_order(monkeypatch, client)
    monkeypatch.setattr(
        salesforce_client_module,
        "_within_first_three_calendar_months",
        lambda _created, _action: True,
    )
    wrong_order = {
        "Id": "a0O000000000001AAA",
        "Account__c": state["account_id"],
        "RecordTypeId": "012000000000099AAA",
        "Description__c": "Ticket 347353. Reactivated locations 1.",
        "Existing_Order_Type__c": "Re-activate an Existing Location",
        "Location_I_D__c": "1",
        "Chargify_Subscription_ID__c": state["subscription_id"],
        "Total_Number_of_Locations_for_this_order__c": 1,
        "Billing_Start_Date1__c": datetime.now(timezone.utc).date().isoformat(),
        "approval": {"submitted": False, "status": "", "records": []},
    }
    monkeypatch.setattr(
        client,
        "read_account_orders",
        lambda _account_id: {"records": [dict(wrong_order)]},
    )
    writes = []

    def reclassification_request(method, path, **kwargs):
        assert method == "PATCH"
        assert path == "/sobjects/NovaPOS_Order__c/a0O000000000001AAA"
        writes.append(dict(kwargs["json"]))
        wrong_order.update(kwargs["json"])
        return {"id": wrong_order["Id"], "success": True}

    monkeypatch.setattr(client, "_request", reclassification_request)
    monkeypatch.setattr(
        client,
        "lookup",
        lambda _kind, _record_id, limit=1: {"records": [dict(wrong_order)]},
    )

    preview = client.location_lifecycle_order_preview(
        state["ticket_id"],
        state["account_id"],
        [state["location_record_id"]],
        "reactivate_existing_location",
        state["subscription_id"],
    )
    assert preview["status"] == "reclassification_preview"
    assert preview["orderToReclassify"]["Id"] == wrong_order["Id"]

    result = client.apply_location_lifecycle_order(
        state["ticket_id"],
        state["account_id"],
        [state["location_record_id"]],
        "reactivate_existing_location",
        state["subscription_id"],
        preview_hash=preview["previewHash"],
        idempotency_key="ticket-347353-reclassify-order-v1",
    )

    assert writes == [
        {
            "RecordTypeId": "012000000000001AAA",
            "Existing_Order_Type__c": "Re-activate an Existing Location",
        }
    ]
    assert result["created"] is False
    assert result["reclassified"] is True
    assert result["orderId"] == wrong_order["Id"]
    assert result["verified"] is True


def test_location_lifecycle_duplicate_identity_survives_next_day_without_crossing_tickets():
    expected = {
        "Account__c": "001000000000001AAA",
        "RecordTypeId": "012000000000001AAA",
        "Description__c": "Ticket 347353. Reactivated locations 1.",
        "Existing_Order_Type__c": "Re-activate an Existing Location",
        "Location_I_D__c": "1",
        "Chargify_Subscription_ID__c": 93250402,
        "Total_Number_of_Locations_for_this_order__c": 1,
        "Billing_Start_Date1__c": "2026-08-04",
    }
    next_day = {**expected, "Billing_Start_Date1__c": "2026-08-05"}

    assert not ScopedSalesforceClient._location_lifecycle_order_readback_matches(
        next_day,
        expected,
    )
    assert ScopedSalesforceClient._location_lifecycle_order_readback_matches(
        next_day,
        expected,
        allow_different_billing_date=True,
    )
    assert not ScopedSalesforceClient._location_lifecycle_order_readback_matches(
        {**next_day, "Description__c": "Ticket 347354. Reactivated locations 1."},
        expected,
        allow_different_billing_date=True,
    )


def test_additional_location_requires_provider_and_uses_age_based_order_type(monkeypatch):
    client = _client()
    state = _configure_location_lifecycle_order(monkeypatch, client)
    monkeypatch.setattr(
        salesforce_client_module,
        "_within_first_three_calendar_months",
        lambda _created, _action: True,
    )
    with pytest.raises(SalesforceScopeError, match="merchant_provider is required"):
        client.location_lifecycle_order_preview(
            state["ticket_id"],
            state["account_id"],
            [state["location_record_id"]],
            "add_additional_location",
            state["subscription_id"],
        )

    preview = client.location_lifecycle_order_preview(
        state["ticket_id"],
        state["account_id"],
        [state["location_record_id"]],
        "add_additional_location",
        state["subscription_id"],
        merchant_provider="Worldpay",
    )
    assert preview["classification"] == "within_3_months"
    assert preview["orderType"] == "New Location"
    assert preview["monthlyRateCents"] == 9999
    assert preview["accountFlatRateMutationIncluded"] is False
    assert preview["newCustomerOrderAllowed"] is False

    monkeypatch.setattr(
        salesforce_client_module,
        "_within_first_three_calendar_months",
        lambda _created, _action: False,
    )
    older = client.location_lifecycle_order_preview(
        state["ticket_id"],
        state["account_id"],
        [state["location_record_id"]],
        "add_additional_location",
        state["subscription_id"],
        merchant_provider="Propelr",
    )
    assert older["classification"] == "existing_additional"
    assert older["orderType"] == "Existing and (New) Additional Customer Order"
    assert "New Customer" not in older["orderType"]


def test_additional_location_classifier_uses_created_date_and_ignores_terms_agreed(
    monkeypatch,
):
    client = _client()
    state = _configure_location_lifecycle_order(
        monkeypatch,
        client,
        created_date="2025-01-10T10:00:00.000+0000",
        terms_agreed_on="2026-07-21T20:32:43.000+0000",
    )
    captured = {}

    def classify(started_at, _action_at):
        captured["startedAt"] = started_at
        return True

    monkeypatch.setattr(
        salesforce_client_module,
        "_within_first_three_calendar_months",
        classify,
    )
    preview = client.location_lifecycle_order_preview(
        state["ticket_id"],
        state["account_id"],
        [state["location_record_id"]],
        "add_additional_location",
        state["subscription_id"],
        merchant_provider="Worldpay",
    )

    assert captured["startedAt"] == datetime(2025, 1, 10, 10, 0, tzinfo=timezone.utc)
    assert preview["classificationDateField"] == "CreatedDate"
    assert preview["classification"] == "within_3_months"
    assert preview["orderType"] == "New Location"


def test_three_calendar_month_classifier_has_exact_boundary_and_month_end_behavior():
    created = datetime(2026, 1, 31, 15, 0, tzinfo=timezone.utc)
    assert salesforce_client_module._within_first_three_calendar_months(
        created,
        datetime(2026, 4, 30, 14, 59, 59, tzinfo=timezone.utc),
    )
    assert not salesforce_client_module._within_first_three_calendar_months(
        created,
        datetime(2026, 4, 30, 15, 0, tzinfo=timezone.utc),
    )


def test_within_three_month_record_type_is_only_for_a_new_location(
    monkeypatch,
):
    client = _client()

    def fake_request(method, path, **_kwargs):
        assert method == "GET"
        assert path.endswith("/Existing_Order_Type__c")
        return {
            "values": [
                {"active": True, "label": "New Location", "value": "New Location"},
                {
                    "active": True,
                    "label": "Re-activate an Existing Location",
                    "value": "Re-activate an Existing Location",
                },
            ]
        }

    monkeypatch.setattr(client, "_request", fake_request)

    assert client._resolve_location_lifecycle_order_type(
        "012000000000001AAA",
        "within_3_months",
        "add_additional_location",
    ) == "New Location"


def test_cancellation_order_picklist_uses_live_business_closing_alias_and_omits_unrelated_type(monkeypatch):
    client = _client()

    def fake_request(method, path, **_kwargs):
        assert method == "GET"
        if path.endswith("/Reason_for_cancellation__c"):
            return {
                "values": [
                    {
                        "active": True,
                        "label": "Business / Location Closing",
                        "value": "Business / Location Closing",
                    }
                ]
            }
        if path.endswith("/Existing_Order_Type__c"):
            return {
                "values": [
                    {"active": True, "label": "New Location", "value": "New Location"},
                    {
                        "active": True,
                        "label": "Re-activate an Existing Location",
                        "value": "Re-activate an Existing Location",
                    },
                ]
            }
        raise AssertionError(path)

    monkeypatch.setattr(client, "_request", fake_request)

    assert (
        client._resolve_order_picklist_value(
            "012000000000001AAA",
            "Reason_for_cancellation__c",
            "Business Closed",
        )
        == "Business / Location Closing"
    )
    assert (
        client._resolve_order_picklist_value(
            "012000000000001AAA",
            "Existing_Order_Type__c",
            "Existing Customer Cancellation Order",
            required=False,
        )
        is None
    )


def test_account_cancellation_pdf_upload_verifies_signature_digest_and_readback(monkeypatch):
    client = _client()
    content = b"%PDF-1.7\nverified cancellation\n%%EOF"
    digest = hashlib.sha256(content).hexdigest()
    version_id = "068000000000001AAA"
    records = []
    monkeypatch.setattr(
        client,
        "_assert_account_cancellation_ticket",
        lambda _ticket_id, _account_id: {
            "Id": "a0G000000000001AAA",
            "Account__c": "001000000000001AAA",
            "Description__c": "Cancel account.",
        },
    )
    monkeypatch.setattr(client, "_ticket_content_versions", lambda _ticket_id: list(records))
    monkeypatch.setattr(client, "_request_bytes", lambda _path: content)

    def fake_request(method, path, **kwargs):
        assert method == "POST"
        assert path == "/sobjects/ContentVersion"
        assert kwargs["json"]["FirstPublishLocationId"] == "a0G000000000001AAA"
        records.append(
            {
                "Id": version_id,
                "Title": "Cancellation NOVA",
                "ContentSize": len(content),
            }
        )
        return {"id": version_id, "success": True}

    monkeypatch.setattr(client, "_request", fake_request)
    result = client.upload_account_cancellation_pdf(
        "a0G000000000001AAA",
        "001000000000001AAA",
        "Cancellation NOVA.pdf",
        base64.b64encode(content).decode("ascii"),
        digest,
        idempotency_key="ticket-347191-cancellation-pdf",
    )

    assert result["uploaded"] is True
    assert result["verified"] is True
    assert result["sha256"] == digest


def test_account_cancellation_pdf_status_verifies_exact_digest_without_writing(monkeypatch):
    client = _client()
    content = b"%PDF-1.7\nverified cancellation\n%%EOF"
    digest = hashlib.sha256(content).hexdigest()
    monkeypatch.setattr(
        client,
        "_assert_account_cancellation_ticket",
        lambda _ticket_id, _account_id: {
            "Id": "a0G000000000001AAA",
            "Account__c": "001000000000001AAA",
        },
    )
    monkeypatch.setattr(
        client,
        "_ticket_content_versions",
        lambda _ticket_id: [
            {
                "Id": "068000000000001AAA",
                "Title": "Cancellation NOVA",
                "ContentSize": len(content),
            }
        ],
    )
    monkeypatch.setattr(client, "_request_bytes", lambda _path: content)
    monkeypatch.setattr(
        client,
        "_request",
        lambda *_args, **_kwargs: pytest.fail("status must not perform a write"),
    )

    result = client.account_cancellation_pdf_status(
        "a0G000000000001AAA",
        "001000000000001AAA",
        "Cancellation NOVA.pdf",
        digest,
    )

    assert result["verified"] is True
    assert result["duplicate"] is True
    assert result["conflictingTitle"] is False
    assert result["writesPerformed"] is False
    assert result["contentVersion"]["sha256"] == digest


def test_account_cancellation_pdf_rejects_non_pdf_before_network(monkeypatch):
    client = _client()
    monkeypatch.setattr(
        client,
        "_assert_account_cancellation_ticket",
        lambda *_args: {"Id": "a0G000000000001AAA"},
    )
    content = b"not a pdf"
    with pytest.raises(SalesforceScopeError, match="signature"):
        client.upload_account_cancellation_pdf(
            "a0G000000000001AAA",
            "001000000000001AAA",
            "Cancellation NOVA.pdf",
            base64.b64encode(content).decode("ascii"),
            hashlib.sha256(content).hexdigest(),
            idempotency_key="ticket-347191-cancellation-pdf",
        )


@pytest.mark.parametrize(
    ("method", "args"),
    [
        ("update_ticket", ("a0G000000000000", {"OwnerId": "005000000000000"})),
        ("update_location", ("a0L000000000000", {"Bill_Amount__c": 0})),
        ("create_order", ({"SetupOwnerId": "005000000000000"},)),
    ],
)
def test_forbidden_fields_fail_before_network(method, args):
    with pytest.raises(SalesforceScopeError, match="field is not allowed"):
        getattr(_client(), method)(*args)


def test_allowlists_exclude_admin_and_financial_fields():
    combined = TICKET_UPDATE_FIELDS | LOCATION_UPDATE_FIELDS | ORDER_CREATE_FIELDS
    assert "OwnerId" not in combined
    assert "ProfileId" not in combined
    assert "PermissionSetId" not in combined
    assert "Bill_Amount__c" not in LOCATION_UPDATE_FIELDS
    assert not any("Flow" in field or "Workflow" in field for field in combined)


def test_invalid_lane_is_rejected_before_server_start():
    with pytest.raises(RuntimeError, match="fixed approved agent lane"):
        build_mcp("raw_codex", FakeClient())


def test_rory_operator_lane_has_ticket_attachment_and_email_handoff_tools():
    names = set(
        build_mcp(
            "direct_codex",
            FakeClient(),
            FakeNovaSqlClient(),
            FakeNovaApiClient(),
        )._tool_manager._tools
    )

    assert {
        "salesforce_ticket_create",
        "salesforce_ticket_attachment_status",
        "salesforce_ticket_attachment_upload",
        "salesforce_ticket_contact_email_update",
        "salesforce_email_template_inventory",
        "salesforce_ticket_template_email_preview",
        "salesforce_ticket_template_email_send",
        "salesforce_ticket_company_credentials_email_preview",
        "salesforce_ticket_company_credentials_email_send",
        "salesforce_location_lifecycle_order_preview",
        "salesforce_location_lifecycle_order_apply",
    } <= names


def test_thor_salesforce_lane_exposes_only_bounded_ticket_evidence_reads():
    names = set(build_mcp("claude_agent", FakeClient())._tool_manager._tools)

    assert names == {
        "salesforce_capabilities",
        "salesforce_explain_limitation",
        "salesforce_lookup",
        "salesforce_account_360_read",
        "salesforce_ticket_list_open",
        "salesforce_weekly_ticket_totals",
        "salesforce_ticket_read",
        "salesforce_ticket_feed_read",
        "salesforce_ticket_email_log_read",
    }
    assert not any(
        name.startswith("nova_sql_")
        or name.startswith("nova_api_")
        or name.endswith("_send")
        or name.endswith("_update")
        or name.endswith("_create")
        for name in names
    )


def test_alex_board_read_includes_billing_without_expanding_ticket_writes():
    assert LANE_TICKET_READ_RECORD_TYPES["tickets_agent"] == frozenset(
        {"1. NOVA Classic", "2. Nova Wave", "3. Billing"}
    )
    assert LANE_TICKET_RECORD_TYPES["tickets_agent"] == frozenset(
        {"1. NOVA Classic", "2. Nova Wave"}
    )
    assert LANE_TICKET_READ_RECORD_TYPES["billing_agent"] == frozenset({"3. Billing"})
    assert LANE_TICKET_RECORD_TYPES["billing_agent"] == frozenset({"3. Billing"})


@pytest.mark.anyio
async def test_alex_open_board_tool_returns_support_and_billing_but_billing_lane_stays_billing_only():
    async with create_connected_server_and_client_session(
        build_mcp("tickets_agent", BoardFakeClient(), FakeNovaSqlClient(), FakeNovaApiClient()),
        raise_exceptions=True,
    ) as support_session:
        support_response = await support_session.call_tool("salesforce_ticket_list_open", {})
    async with create_connected_server_and_client_session(
        build_mcp("billing_agent", BoardFakeClient(), FakeNovaSqlClient(), FakeNovaApiClient()),
        raise_exceptions=True,
    ) as billing_session:
        billing_response = await billing_session.call_tool("salesforce_ticket_list_open", {})

    assert [record["Name"] for record in support_response.structuredContent["records"]] == ["1", "2"]
    assert support_response.structuredContent["ticketRecordTypes"] == [
        "1. NOVA Classic",
        "2. Nova Wave",
        "3. Billing",
    ]
    assert support_response.structuredContent["ticketWriteRecordTypes"] == [
        "1. NOVA Classic",
        "2. Nova Wave",
    ]
    assert [record["Name"] for record in billing_response.structuredContent["records"]] == ["2"]
    assert billing_response.structuredContent["ticketWriteRecordTypes"] == ["3. Billing"]


def test_open_ticket_list_is_fixed_bounded_and_filters_forbidden_board_rows(monkeypatch):
    client = _client()
    captured = {}

    def fake_query(soql):
        captured["soql"] = soql
        return {
            "records": [
                {
                    "Id": "a0G000000000001",
                    "Name": "1",
                    "RecordType": {"Name": "1. NOVA Classic"},
                    "Account__r": {"Name": "Real Store", "Company_Username__c": "real"},
                    "Technical_Issue__c": "Hardware",
                },
                {
                    "Id": "a0G000000000002",
                    "Name": "2",
                    "RecordType": {"Name": "1. NOVA Classic"},
                    "Account__r": {"Name": "Demo Nova Cafe", "Company_Username__c": "demo"},
                    "Technical_Issue__c": "Hardware",
                },
                {
                    "Id": "a0G000000000003",
                    "Name": "3",
                    "RecordType": {"Name": "2. Nova Wave"},
                    "Account__r": {"Name": "Real Store", "Company_Username__c": "real"},
                    "NOVA_Wave_Technical_Issue__c": "Bug",
                },
            ]
        }

    monkeypatch.setattr(client, "_query", fake_query)
    result = client.list_open_tickets(limit=9999)

    assert result["count"] == 1
    assert result["records"][0]["Name"] == "1"
    assert result["rowCeiling"] == 500
    assert result["sourceRowCeiling"] == 2000
    assert "Is_Closed__c = false" in captured["soql"]
    assert "ORDER BY CreatedDate DESC LIMIT 2000" in captured["soql"]


def test_ticket_feed_read_is_exact_and_bounded(monkeypatch):
    client = _client()
    captured = {}

    def fake_request(method, path, *, params=None, json=None):
        captured.update(method=method, path=path, params=params)
        return {
            "elements": [
                {
                    "id": str(index),
                    "actor": {"id": "005000000000001AAA", "displayName": "Owner"},
                    "body": {"text": "Question"},
                    "capabilities": {
                        "comments": {
                            "page": {
                                "items": [
                                    {
                                        "id": f"comment-{index}",
                                        "createdDate": "2026-07-30T06:09:32.000Z",
                                        "body": {"text": "$1k and $50 monthly."},
                                        "user": {
                                            "id": "005000000000002AAA",
                                            "displayName": "Approver",
                                            "photo": {"fullEmailPhotoUrl": "not returned"},
                                        },
                                    }
                                ]
                            }
                        }
                    },
                }
                for index in range(30)
            ]
        }

    monkeypatch.setattr(client, "_request", fake_request)
    result = client.read_ticket_feed("a0G000000000000", limit=999)

    assert result["count"] == 20
    assert len(result["elements"]) == 20
    assert len(result["posts"]) == 20
    assert result["posts"][0]["comments"][0]["text"] == "$1k and $50 monthly."
    assert result["posts"][0]["comments"][0]["author"] == {
        "id": "005000000000002AAA",
        "name": "Approver",
        "active": None,
    }
    assert "photo" not in repr(result["posts"])
    assert captured["method"] == "GET"
    assert captured["path"] == "/chatter/feeds/record/a0G000000000000/feed-elements"
    assert captured["params"] == {"pageSize": 20}
