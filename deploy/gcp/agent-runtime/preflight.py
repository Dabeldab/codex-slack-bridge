from __future__ import annotations

# AgentChat/direct_codex 2026-07-24T13:45:00Z: require Alex's typed weekly
# Salesforce/Zoom reporting surfaces during immutable-release activation.

import asyncio
import importlib.util
import json
import os
import subprocess
import tempfile
import tomllib
from pathlib import Path
from typing import Any
import requests
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from slack_sdk import WebClient

from scoped_operations_mcp.nova_sql_client import ScopedNovaSqlClient
from scoped_operations_mcp.maxio_client import MaxioSettings, ScopedMaxioClient
from scoped_operations_mcp.salesforce_client import ScopedSalesforceClient, SalesforceSettings
from codex_slack_bridge.agent_policy import load_capability_contract
from codex_slack_bridge.agents import AGENT_FILE_DELIVERY_CONTRACT
from codex_slack_bridge.command_center_server import AGENT_CHAT_FILE_EXTENSIONS, AGENT_FILE_RETURN_EXTENSIONS
from codex_slack_bridge.config import load_config


ROOT = Path("/run/nova-secrets")
ZOOM_PREFLIGHT_MARKER = Path("/run/nova-preflight/zoom-passed")
OPTIONAL_SCOPED_MCP_LANES: tuple[str, ...] = ()
OPTIONAL_LIVE_CONNECTORS: tuple[str, ...] = ()
CORE_RUNTIME_CHECKS = ("rory_isolation", "codex_runtime_approval_policy", "agent_file_delivery")
GMAIL_SCOPE = "https://www.googleapis.com/auth/gmail.modify"
GOOGLE_WORKSPACE_SCOPES = [
    "https://mail.google.com/",
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/spreadsheets",
]


def _secret(name: str) -> str:
    value = (ROOT / name).read_text(encoding="utf-8").strip()
    if not value:
        raise RuntimeError(f"required secret is empty: {name}")
    return value


def _probe_slack() -> dict[str, Any]:
    bot = WebClient(token=_secret("slack-bot-token")).auth_test()
    socket = WebClient().apps_connections_open(app_token=_secret("slack-app-token"))
    return {"ok": bool(bot.get("ok") and socket.get("ok") and socket.get("url"))}


def _probe_gmail() -> dict[str, Any]:
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8") as handle:
        handle.write(_secret("gmail-oauth-token"))
        handle.flush()
        credentials = Credentials.from_authorized_user_file(handle.name, [GMAIL_SCOPE])
        if not credentials.valid:
            credentials.refresh(Request())
        response = requests.get(
            "https://gmail.googleapis.com/gmail/v1/users/me/profile",
            headers={"Authorization": f"Bearer {credentials.token}"},
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
    return {"ok": bool(payload.get("emailAddress")), "scope": "gmail.modify"}


def _probe_agent_file_delivery() -> dict[str, Any]:
    config = load_config("/opt/nova/current/config/agents.gcp-runtime.yaml")
    contract = load_capability_contract("/opt/nova/current/config/agent-capabilities.yaml")
    registry = json.loads(
        Path("/opt/nova/current/config/tool-fast-paths.json").read_text(encoding="utf-8")
    )
    tool = (registry.get("tools") or {}).get("agent_file_delivery") or {}
    required_lanes = {
        "direct_codex",
        "raw_codex",
        "tickets_agent",
        "billing_agent",
        "coding_agent",
        "claude_agent",
    }
    capability_ready = all(
        "artifact.file_return_verified"
        in set(((contract.get("lanes") or {}).get(name) or {}).get("operations") or [])
        for name in required_lanes
    )
    registered_lanes = {str(name) for name in tool.get("primary_agents") or []}
    dependencies = {
        name: importlib.util.find_spec(name) is not None
        for name in ("PIL", "docx", "fitz", "openpyxl", "pptx", "pypdf")
    }
    configured_roots = {
        str(item) for item in config.defaults.get("agent_file_return_allowed_roots") or []
    }
    format_ready = {
        ".csv",
        ".docx",
        ".jpg",
        ".pdf",
        ".png",
        ".pptx",
        ".xlsm",
        ".xlsx",
    }.issubset(AGENT_FILE_RETURN_EXTENSIONS)
    inbound_ready = {".docx", ".pdf", ".pptx", ".xls", ".xlsm", ".xlsx"}.issubset(
        AGENT_CHAT_FILE_EXTENSIONS
    )
    ok = bool(
        "BRIDGE_UPLOAD_FILE:" in AGENT_FILE_DELIVERY_CONTRACT
        and capability_ready
        and required_lanes == registered_lanes
        and all(dependencies.values())
        and format_ready
        and inbound_ready
        and int(config.defaults.get("agent_file_return_max_mb") or 0) == 25
        and "/var/lib/nova/broker/maxio-reports" in configured_roots
        and hasattr(WebClient, "files_upload_v2")
        and hasattr(WebClient, "files_info")
    )
    return {
        "ok": ok,
        "gatewayDirectiveConfigured": "BRIDGE_UPLOAD_FILE:" in AGENT_FILE_DELIVERY_CONTRACT,
        "allLanesConfigured": capability_ready and required_lanes == registered_lanes,
        "editingDependenciesReady": all(dependencies.values()),
        "supportedFormatsReady": format_ready and inbound_ready,
        "boundedReturnLimitMb": int(config.defaults.get("agent_file_return_max_mb") or 0),
        "typedReportRootConfigured": "/var/lib/nova/broker/maxio-reports" in configured_roots,
        "slackUploadReadbackReady": hasattr(WebClient, "files_upload_v2") and hasattr(WebClient, "files_info"),
    }


def _probe_google_workspace() -> dict[str, Any]:
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8") as handle:
        handle.write(_secret("google-workspace-adc"))
        handle.flush()
        credentials = Credentials.from_authorized_user_file(handle.name, GOOGLE_WORKSPACE_SCOPES)
        credentials.refresh(Request())
        session = requests.Session()
        headers = {"Authorization": f"Bearer {credentials.token}"}
        gmail = session.get(
            "https://gmail.googleapis.com/gmail/v1/users/me/profile",
            headers=headers,
            timeout=30,
        )
        gmail.raise_for_status()
        drive = session.get(
            "https://www.googleapis.com/drive/v3/about",
            params={"fields": "user,storageQuota"},
            headers=headers,
            timeout=30,
        )
        drive.raise_for_status()
        candidates = session.get(
            "https://www.googleapis.com/drive/v3/files",
            params={
                "q": (
                    "trashed=false and (mimeType='application/vnd.google-apps.spreadsheet' "
                    "or mimeType='application/vnd.google-apps.document')"
                ),
                "fields": "files(id,mimeType)",
                "pageSize": "100",
            },
            headers=headers,
            timeout=30,
        )
        candidates.raise_for_status()
        rows = candidates.json().get("files") or []
        spreadsheet_id = next(
            (str(row.get("id") or "") for row in rows if row.get("mimeType") == "application/vnd.google-apps.spreadsheet"),
            "",
        )
        document_id = next(
            (str(row.get("id") or "") for row in rows if row.get("mimeType") == "application/vnd.google-apps.document"),
            "",
        )
        sheets_ok = False
        docs_ok = False
        if spreadsheet_id:
            response = session.get(
                f"https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}",
                params={"fields": "spreadsheetId"},
                headers=headers,
                timeout=30,
            )
            response.raise_for_status()
            sheets_ok = str(response.json().get("spreadsheetId") or "") == spreadsheet_id
        if document_id:
            response = session.get(
                f"https://docs.googleapis.com/v1/documents/{document_id}",
                headers=headers,
                timeout=30,
            )
            response.raise_for_status()
            docs_ok = str(response.json().get("documentId") or "") == document_id
    scopes = set(credentials.scopes or [])
    full_scopes = set(GOOGLE_WORKSPACE_SCOPES).issubset(scopes)
    return {
        "ok": bool(gmail.json().get("emailAddress") and drive.json().get("user") and sheets_ok and docs_ok and full_scopes),
        "gmail": bool(gmail.json().get("emailAddress")),
        "drive": bool(drive.json().get("user")),
        "sheets": sheets_ok,
        "docs": docs_ok,
        "fullScopes": full_scopes,
    }


def _salesforce_client() -> ScopedSalesforceClient:
    settings = SalesforceSettings._from_values(
        {
            "SALESFORCE_CLIENT_ID": _secret("salesforce-client-id"),
            "SALESFORCE_CLIENT_SECRET": _secret("salesforce-client-secret"),
            "SALESFORCE_LOGIN_URL": _secret("salesforce-login-url"),
            "SALESFORCE_INSTANCE_URL": _secret("salesforce-instance-url"),
            "SALESFORCE_USE_CLIENT_CREDENTIALS": "true",
        }
    )
    return ScopedSalesforceClient(settings)


def _probe_salesforce_and_sql() -> tuple[dict[str, Any], dict[str, Any]]:
    client = _salesforce_client()
    result = client.list_open_tickets(limit=20)
    salesforce = {"ok": bool(result.get("ok")), "accessMode": "typed_operations_only"}
    username = ""
    for record in result.get("records", []):
        account = record.get("Account__r") if isinstance(record.get("Account__r"), dict) else {}
        username = str(account.get("Company_Username__c") or "").strip()
        if username:
            break
    if not username:
        return salesforce, {"ok": False, "status": "no_bounded_preflight_account"}
    preflight = ScopedNovaSqlClient(client).preflight(username)
    return salesforce, {
        "ok": bool(preflight.get("ok")),
        "exactDatabaseBinding": str(preflight.get("databaseName") or "").casefold()
        == f"POS_{username}".casefold(),
        "tableCountPositive": int(preflight.get("tableCount") or 0) > 0,
    }


def _probe_chargify() -> dict[str, Any]:
    result = ScopedMaxioClient(
        MaxioSettings(
            base_url=_secret("chargify-base-url"),
            api_key=_secret("chargify-api-key"),
        )
    ).health()
    return {
        "ok": bool(result.get("ok")),
        "accessMode": str(result.get("accessMode") or ""),
    }


def _codex_identity_readiness(identities: dict[str, bool]) -> dict[str, Any]:
    required_identities = ("rory", "taylor", "alex", "jamie")
    optional_identities = ("thor",)
    missing_required = [
        identity for identity in required_identities if not bool(identities.get(identity))
    ]
    optional_failures = [
        identity for identity in optional_identities if not bool(identities.get(identity))
    ]
    return {
        "ok": not missing_required,
        "degraded": bool(optional_failures),
        "requiredIdentities": list(required_identities),
        "optionalIdentities": list(optional_identities),
        "missingRequiredIdentities": missing_required,
        "optionalFailures": optional_failures,
    }


def _required_optional_readiness(
    results: dict[str, dict[str, Any]],
    *,
    optional_names: tuple[str, ...],
) -> dict[str, Any]:
    optional = list(optional_names)
    required = [name for name in results if name not in optional_names]
    optional_failures = [
        name
        for name in optional
        if name in results and not bool(results.get(name, {}).get("ok"))
    ]
    return {
        "ok": all(bool(results.get(name, {}).get("ok")) for name in required),
        "degraded": bool(optional_failures),
        "required": required,
        "optional": optional,
        "optionalFailures": optional_failures,
    }


def _probe_codex() -> dict[str, Any]:
    identities: dict[str, bool] = {}
    for identity, user in (
        ("rory", "nova-rory"),
        ("thor", "nova-claude"),
        ("taylor", "nova-taylor"),
        ("alex", "nova-alex"),
        ("jamie", "nova-jamie"),
    ):
        home = f"/home/{user}"
        result = subprocess.run(
            ["runuser", "-u", user, "--", "env", f"HOME={home}", "/usr/local/bin/codex", "login", "status"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        combined = f"{result.stdout}\n{result.stderr}"
        identities[identity] = result.returncode == 0 and "Logged in using ChatGPT" in combined
    return {
        **_codex_identity_readiness(identities),
        "method": "chatgpt",
        "identities": identities,
    }


def _probe_rory_isolation() -> dict[str, Any]:
    config = load_config("/opt/nova/current/config/agents.gcp-runtime.yaml")
    contract = load_capability_contract("/opt/nova/current/config/agent-capabilities.yaml")
    rory = config.agents["direct_codex"]
    allowed_user_ids = {
        str(value).strip()
        for value in (rory.get("allowed_user_ids") or [])
        if str(value).strip()
    }
    identity_reuse = []
    for name, agent in config.agents.items():
        if name == "direct_codex":
            continue
        prefix = [str(value) for value in (agent.get("codex_command_prefix") or [])]
        if "nova-rory" in prefix or str(agent.get("runtime_file_group") or "") == "nova-rory":
            identity_reuse.append(name)

    lanes = contract.get("lanes") or {}
    rory_delegates = list((lanes.get("direct_codex") or {}).get("delegates_to") or [])
    rory_limitations = set((lanes.get("direct_codex") or {}).get("limitations") or [])
    expected_rory_delegates = {"coding_agent", "tickets_agent", "billing_agent", "claude_agent"}
    inbound_delegates = sorted(
        name
        for name, lane in lanes.items()
        if name != "direct_codex" and "direct_codex" in set(lane.get("delegates_to") or [])
    )
    rory_policy = tomllib.loads(
        Path("/etc/nova/codex-mcp-policy/rory.toml").read_text(encoding="utf-8")
    )
    rory_servers = rory_policy.get("mcp_servers") or {}
    rory_approvals_preapproved = bool(rory_servers) and all(
        isinstance(server, dict)
        and str(server.get("default_tools_approval_mode") or "").strip() == "approve"
        for server in rory_servers.values()
    )

    credential_path = "/home/nova-rory/.codex/auth.json"
    credential_readable_by = []
    for user in ("nova-runtime", "nova-raw", "nova-claude", "nova-taylor", "nova-alex", "nova-jamie"):
        result = subprocess.run(
            ["runuser", "-u", user, "--", "test", "-r", credential_path],
            capture_output=True,
            timeout=10,
            check=False,
        )
        if result.returncode == 0:
            credential_readable_by.append(user)

    model_users = ("nova-runtime", "nova-rory", "nova-raw", "nova-claude", "nova-taylor", "nova-alex", "nova-jamie")
    operator_secret_paths = (
        "/run/nova-cloud-identity/access-token",
        "/run/nova-secrets/github-user-token",
        "/run/nova-secrets/google-workspace-adc",
        "/run/nova-secrets/salesforce-client-secret",
        "/run/nova-secrets/pos-main-api-cohort-ro",
        "/run/nova-secrets/chargify-api-key",
        "/run/nova-secrets/rescue-password",
        "/run/nova-secrets/zoom-oauth-client-secret",
        "/run/nova-secrets/zoom-singapore-julio-contact",
        "/run/nova-secrets/zoom-internal-wiko-contact",
        "/run/nova-secrets/zoom-s2s-account-id",
        "/run/nova-secrets/zoom-s2s-client-id",
        "/run/nova-secrets/zoom-s2s-client-secret",
        "/run/nova-secrets/command-center-proxy-token",
    )
    operator_secret_readers = []
    for user in model_users:
        for path in operator_secret_paths:
            result = subprocess.run(
                ["runuser", "-u", user, "--", "test", "-r", path],
                capture_output=True,
                timeout=10,
                check=False,
            )
            if result.returncode == 0:
                operator_secret_readers.append(f"{user}:{Path(path).name}")

    unauthorized_operator_broker_users = []
    for user in ("nova-runtime", "nova-raw", "nova-claude", "nova-taylor", "nova-alex", "nova-jamie"):
        result = subprocess.run(
            [
                "runuser", "-u", user, "--", "/usr/bin/sudo", "-n", "-H", "-u", "nova-cloud-broker", "--",
                "/opt/nova/bin/run-operator-broker", "direct_codex",
            ],
            capture_output=True,
            timeout=10,
            check=False,
        )
        if result.returncode == 0:
            unauthorized_operator_broker_users.append(user)

    settings_ok = (
        len(allowed_user_ids) == 1
        and not bool(rory.get("agent_runtime_shared_sessions"))
        and str(rory.get("subagents_mode") or "").strip() == "manual"
        and int(rory.get("max_subagents") or 0) == 0
        and not (rory.get("subagents") or [])
    )
    ok = (
        not identity_reuse
        and set(rory_delegates) == expected_rory_delegates
        and not inbound_delegates
        and "no_inbound_agent_handoffs" in rory_limitations
        and "inbound_tool_repair_only_with_verified_operator_origin" not in rory_limitations
        and "one_supervisor_repair_per_obligation" not in rory_limitations
        and rory_approvals_preapproved
        and not credential_readable_by
        and not operator_secret_readers
        and not unauthorized_operator_broker_users
        and settings_ok
    )
    return {
        "ok": ok,
        "operatorAllowlistCount": len(allowed_user_ids),
        "identityExclusive": not identity_reuse,
        "oneWayOutboundDelegation": (
            set(rory_delegates) == expected_rory_delegates
            and not inbound_delegates
            and "no_inbound_agent_handoffs" in rory_limitations
        ),
        "automaticSupervisorRepairHandoffDisabled": (
            "inbound_tool_repair_only_with_verified_operator_origin" not in rory_limitations
            and "one_supervisor_repair_per_obligation" not in rory_limitations
        ),
        "outboundDelegates": sorted(rory_delegates),
        "mcpServersPreapproved": rory_approvals_preapproved,
        "subagentsDisabled": settings_ok,
        "credentialUnreadableByOtherRuntimeUsers": not credential_readable_by,
        "operatorCredentialsUnreadableByModelUsers": not operator_secret_readers,
        "operatorBrokerExclusive": not unauthorized_operator_broker_users,
    }


async def _mcp_tool_names(
    *,
    model_user: str,
    broker_user: str,
    launcher: str,
    lane: str,
    workspace: str,
) -> set[str]:
    parameters = StdioServerParameters(
        command="/usr/sbin/runuser",
        args=[
            "-u",
            model_user,
            "--",
            "/usr/bin/env",
            f"HOME=/home/{model_user}",
            "/usr/bin/sudo",
            "-n",
            "-H",
            "-u",
            broker_user,
            "--",
            launcher,
            lane,
        ],
        cwd=workspace,
    )
    async with asyncio.timeout(30):
        async with stdio_client(parameters) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                response = await session.list_tools()
    return {tool.name for tool in response.tools}


async def _mcp_call_json(
    *,
    model_user: str,
    broker_user: str,
    launcher: str,
    lane: str,
    workspace: str,
    tool_name: str,
    arguments: dict[str, Any] | None = None,
) -> dict[str, Any]:
    parameters = StdioServerParameters(
        command="/usr/sbin/runuser",
        args=[
            "-u",
            model_user,
            "--",
            "/usr/bin/env",
            f"HOME=/home/{model_user}",
            "/usr/bin/sudo",
            "-n",
            "-H",
            "-u",
            broker_user,
            "--",
            launcher,
            lane,
        ],
        cwd=workspace,
    )
    async with asyncio.timeout(60):
        async with stdio_client(parameters) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                response = await session.call_tool(tool_name, arguments or {})
    if response.isError or not isinstance(response.structuredContent, dict):
        raise RuntimeError(f"broker tool failed: {tool_name}")
    return dict(response.structuredContent)


async def _probe_scoped_mcp_brokers_async() -> dict[str, Any]:
    common_salesforce = {
        "salesforce_capabilities",
        "salesforce_lookup",
        "salesforce_account_360_read",
        "salesforce_ticket_list_open",
        "salesforce_ticket_read",
        "salesforce_ticket_feed_read",
        "salesforce_ticket_email_log_read",
        "salesforce_ticket_internal_note_update",
        "salesforce_ticket_chatter_post",
        "salesforce_ticket_chatter_reply",
        "salesforce_ticket_internal_request_post",
        "salesforce_ticket_contact_email_update",
        "salesforce_ticket_attachment_status",
        "salesforce_ticket_attachment_upload",
        "salesforce_ticket_pdf_status",
        "salesforce_ticket_pdf_upload",
        "salesforce_email_sender_preflight",
        "salesforce_email_template_inventory",
        "salesforce_ticket_template_email_preview",
        "nova_api_capabilities",
        "nova_api_health",
        "nova_api_preflight",
        "nova_api_regions",
        "nova_api_locations_by_region",
        "nova_sql_preflight",
        "nova_billing_locations_read",
        "nova_sql_invoice_spare_investigation",
        "nova_sql_read",
    }
    shared_zoom = {
        "zoom_capabilities",
        "zoom_operator_team_chat_recipient_resolve",
        "zoom_operator_team_chat_send",
        "zoom_team_chat_channels",
        "zoom_team_chat_history",
        "zoom_docs_archives",
        "zoom_docs_archive_content",
        "zoom_ghostbusters_overview_read",
        "zoom_support_queue_metrics",
    }
    thor_salesforce_reads = {
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
    thor_google_support_reads = {
        "google_support_drive_capabilities",
        "google_support_drive_files_list",
        "google_support_drive_file_get",
        "google_support_document_get",
        "google_support_sheet_values_get",
    }
    ticket_writes = {
        "salesforce_ticket_update",
        "salesforce_ticket_resolve",
        "salesforce_ticket_template_email_send",
    }
    monthly_salesforce_alignment = {
        "salesforce_billing_account_read",
        "salesforce_billing_account_locations_read",
        "salesforce_billing_account_orders_read",
        "salesforce_billing_account_flat_rate_update",
        "salesforce_billing_location_rate_update",
        "salesforce_billing_structure_read",
        "salesforce_account_fake_classification_preview",
        "salesforce_account_fake_classification_apply",
        "salesforce_billing_location_alignment_preview",
        "salesforce_billing_location_alignment_apply",
        "salesforce_billing_structure_alignment_preview",
        "salesforce_billing_structure_alignment_apply",
    }
    monthly_maxio_location_organization = {
        "maxio_subscription_creation_preview",
        "maxio_subscription_creation_apply",
        "maxio_location_custom_fields_read",
        "maxio_location_custom_fields_preview",
        "maxio_location_custom_fields_apply",
        "maxio_subscription_location_metadata_read",
        "maxio_subscription_location_mapping_preview",
        "maxio_subscription_location_mapping_apply",
        "maxio_tax_report",
    }
    specs = {
        "salesforce_operator": {
            "model_user": "nova-rory",
            "broker_user": "nova-salesforce-broker",
            "launcher": "/opt/nova/bin/run-salesforce-broker",
            "lane": "direct_codex",
            "workspace": "/srv/nova/workspaces/rory",
            "required": common_salesforce
            | ticket_writes
            | {
                "salesforce_ticket_create",
            },
            "forbidden": {
                "salesforce_account_cancellation_order_apply",
                "salesforce_location_cancellation_order_preview",
                "salesforce_location_cancellation_order_apply",
                "salesforce_account_cancellation_confirmation_email_send",
                "salesforce_billing_closure_email_ticket_create",
                "salesforce_account_cancellation_email_attachment_status",
                "salesforce_account_cancellation_email_attachment_upload",
                "salesforce_account_closure_apply",
                "salesforce_billing_location_rate_update",
                "salesforce_billing_account_flat_rate_update",
                "salesforce_billing_account_flat_rate_clear",
                "salesforce_billing_location_gateway_update",
                "salesforce_reactivation_order_approval_preview",
                "salesforce_reactivation_order_approval_apply",
                "salesforce_location_lifecycle_order_preview",
                "salesforce_location_lifecycle_order_apply",
                "nova_sql_api_customer_email_cohort",
                "nova_sql_execute_guarded",
                "nova_sql_location_region_update",
                "nova_sql_location_layaway_enable",
                "nova_sql_locations_feature_columns_execute",
                "nova_sql_kit_upgrade_preview",
                "nova_sql_kit_upgrade_execute",
                "nova_sql_table_restore_preview",
                "nova_sql_table_restore_execute",
            },
        },
        "salesforce_coding": {
            "model_user": "nova-taylor",
            "broker_user": "nova-salesforce-broker",
            "launcher": "/opt/nova/bin/run-salesforce-broker",
            "lane": "coding_agent",
            "workspace": "/srv/nova/workspaces/taylor",
            "required": common_salesforce
            | ticket_writes
            | monthly_salesforce_alignment
            | {
                "nova_sql_api_customer_email_cohort",
                "nova_sql_execute_guarded",
                "nova_sql_location_region_update",
                "nova_sql_location_layaway_enable",
                "nova_sql_locations_feature_columns_execute",
                "nova_sql_kit_upgrade_preview",
                "nova_sql_kit_upgrade_execute",
                "nova_sql_instyle_demo_sync_preview",
                "nova_sql_instyle_demo_sync_status",
                "nova_sql_instyle_demo_sync_execute",
                "nova_sql_table_restore_preview",
                "nova_sql_table_restore_execute",
                "salesforce_location_lifecycle_order_preview",
                "salesforce_location_lifecycle_order_apply",
                "salesforce_support_email_ticket_create",
            },
            "forbidden": {
                "salesforce_ticket_create",
                "salesforce_order_create",
                "salesforce_location_update",
                "salesforce_account_cancellation_order_apply",
                "salesforce_location_cancellation_order_preview",
                "salesforce_location_cancellation_order_apply",
                "salesforce_account_cancellation_confirmation_email_send",
                "salesforce_account_cancellation_pdf_status",
                "salesforce_billing_closure_email_ticket_create",
                "salesforce_account_cancellation_email_attachment_status",
                "salesforce_account_cancellation_email_attachment_upload",
                "salesforce_account_closure_apply",
                "salesforce_billing_account_flat_rate_clear",
                "salesforce_billing_location_gateway_update",
                "salesforce_reactivation_order_approval_preview",
                "salesforce_reactivation_order_approval_apply",
            },
        },
        "salesforce_support": {
            "model_user": "nova-alex",
            "broker_user": "nova-salesforce-broker",
            "launcher": "/opt/nova/bin/run-salesforce-broker",
            "lane": "tickets_agent",
            "workspace": "/srv/nova/workspaces/alex",
            "required": common_salesforce
            | ticket_writes
            | {
                "salesforce_ticket_create",
                "salesforce_weekly_ticket_totals",
            },
            "forbidden": {
                "salesforce_account_cancellation_order_apply",
                "salesforce_location_cancellation_order_preview",
                "salesforce_location_cancellation_order_apply",
                "salesforce_account_cancellation_confirmation_email_send",
                "salesforce_account_cancellation_pdf_status",
                "salesforce_billing_closure_email_ticket_create",
                "salesforce_account_cancellation_email_attachment_status",
                "salesforce_account_cancellation_email_attachment_upload",
                "salesforce_account_closure_apply",
                "salesforce_billing_location_rate_update",
                "salesforce_billing_account_read",
                "salesforce_billing_account_flat_rate_update",
                "salesforce_billing_account_flat_rate_clear",
                "salesforce_billing_location_gateway_update",
                "salesforce_reactivation_order_approval_preview",
                "salesforce_reactivation_order_approval_apply",
                "salesforce_location_lifecycle_order_preview",
                "salesforce_location_lifecycle_order_apply",
                "nova_sql_api_customer_email_cohort",
                "nova_sql_execute_guarded",
                "nova_sql_location_region_update",
                "nova_sql_location_layaway_enable",
                "nova_sql_locations_feature_columns_execute",
                "nova_sql_kit_upgrade_preview",
                "nova_sql_kit_upgrade_execute",
                "nova_sql_instyle_demo_sync_preview",
                "nova_sql_instyle_demo_sync_status",
                "nova_sql_instyle_demo_sync_execute",
                "nova_sql_table_restore_preview",
                "nova_sql_table_restore_execute",
            },
        },
        "salesforce_billing": {
            "model_user": "nova-jamie",
            "broker_user": "nova-salesforce-broker",
            "launcher": "/opt/nova/bin/run-salesforce-broker",
            "lane": "billing_agent",
            "workspace": "/srv/nova/workspaces/jamie",
            "required": common_salesforce
            | ticket_writes
            | monthly_salesforce_alignment
            | {
                "salesforce_ticket_create",
                "salesforce_account_closure_preview",
                "salesforce_account_closure_apply",
                "salesforce_account_cancellation_order_preview",
                "salesforce_account_cancellation_order_apply",
                "salesforce_location_cancellation_order_preview",
                "salesforce_location_cancellation_order_apply",
                "salesforce_location_lifecycle_order_preview",
                "salesforce_location_lifecycle_order_apply",
                "salesforce_account_cancellation_chatter_post",
                "salesforce_account_cancellation_pdf_status",
                "salesforce_account_cancellation_pdf_upload",
                "salesforce_billing_closure_email_ticket_create",
                "salesforce_account_cancellation_email_attachment_status",
                "salesforce_account_cancellation_email_attachment_upload",
                "salesforce_account_cancellation_confirmation_email_send",
                "salesforce_ticket_update",
                "salesforce_ticket_resolve",
                "salesforce_ticket_template_email_send",
                "salesforce_ticket_credit_confirmation_email_send",
                "salesforce_ticket_refund_confirmation_email_send",
                "salesforce_billing_account_flat_rate_clear",
                "salesforce_billing_location_gateway_update",
            },
            "forbidden": {
                "salesforce_reactivation_order_approval_preview",
                "salesforce_reactivation_order_approval_apply",
                "salesforce_order_create",
                "salesforce_location_update",
                "nova_sql_api_customer_email_cohort",
                "nova_sql_execute_guarded",
                "nova_sql_location_region_update",
                "nova_sql_location_layaway_enable",
                "nova_sql_locations_feature_columns_execute",
                "nova_sql_kit_upgrade_preview",
                "nova_sql_kit_upgrade_execute",
                "nova_sql_instyle_demo_sync_preview",
                "nova_sql_instyle_demo_sync_status",
                "nova_sql_instyle_demo_sync_execute",
                "nova_sql_table_restore_preview",
                "nova_sql_table_restore_execute",
            },
        },
        "salesforce_thor": {
            "model_user": "nova-claude",
            "broker_user": "nova-salesforce-broker",
            "launcher": "/opt/nova/bin/run-salesforce-broker",
            "lane": "claude_agent",
            "workspace": "/srv/nova/workspaces/claude",
            "required": thor_salesforce_reads,
            "forbidden": {
                "salesforce_ticket_create",
                "salesforce_ticket_update",
                "salesforce_ticket_chatter_post",
                "salesforce_ticket_chatter_reply",
                "salesforce_ticket_internal_request_post",
                "salesforce_ticket_resolve",
                "salesforce_ticket_template_email_send",
                "nova_sql_read",
                "nova_sql_execute_guarded",
                "nova_sql_location_region_update",
                "nova_sql_location_layaway_enable",
                "nova_api_preflight",
            },
        },
        "maxio_coding": {
            "model_user": "nova-taylor",
            "broker_user": "nova-maxio-broker",
            "launcher": "/opt/nova/bin/run-maxio-broker",
            "lane": "coding_agent",
            "workspace": "/srv/nova/workspaces/taylor",
            "required": monthly_maxio_location_organization
            | {
                "maxio_capabilities",
                "maxio_health",
                "maxio_customers_search",
                "maxio_customer",
                "maxio_subscription",
                "maxio_component_allocation_preview",
                "maxio_component_allocation_apply",
                "maxio_subscription_account_balances",
                "maxio_manual_service_credit_preview",
                "maxio_manual_service_credit_apply",
                "maxio_component_payment_recovery_preview",
                "maxio_component_payment_recovery_apply",
                "maxio_api_request",
            },
            "forbidden": {
                "maxio_subscription_cancellation_preview",
                "maxio_subscription_cancellation_apply",
                "maxio_subscription_coupon_preview",
                "maxio_subscription_coupon_apply",
                "maxio_subscription_product_change_preview",
                "maxio_subscription_product_change_apply",
                "maxio_nova_integrated_products",
                "maxio_nova_integrated_promo_credit_preview",
                "maxio_nova_integrated_promo_credit_apply",
            },
        },
        "maxio_billing": {
            "model_user": "nova-jamie",
            "broker_user": "nova-maxio-broker",
            "launcher": "/opt/nova/bin/run-maxio-broker",
            "lane": "billing_agent",
            "workspace": "/srv/nova/workspaces/jamie",
            "required": monthly_maxio_location_organization
            | {
                "maxio_capabilities",
                "maxio_health",
                "maxio_customers_search",
                "maxio_customer",
                "maxio_subscription",
                "maxio_component_allocation_preview",
                "maxio_component_allocation_apply",
                "maxio_subscription_account_balances",
                "maxio_manual_service_credit_preview",
                "maxio_manual_service_credit_apply",
                "maxio_component_payment_recovery_preview",
                "maxio_component_payment_recovery_apply",
                "maxio_billing_cycle_recovery_preview",
                "maxio_billing_cycle_recovery_apply",
                "maxio_invoice_refund_preview",
                "maxio_invoice_refund_apply",
                "maxio_subscription_coupon_preview",
                "maxio_subscription_coupon_apply",
                "maxio_subscription_product_change_preview",
                "maxio_subscription_product_change_apply",
                "maxio_nova_integrated_products",
                "maxio_nova_integrated_promo_credit_preview",
                "maxio_nova_integrated_promo_credit_apply",
                "maxio_subscription_cancellation_preview",
                "maxio_subscription_cancellation_apply",
                "maxio_api_request",
            },
            "forbidden": set(),
        },
        "rescue_support": {
            "model_user": "nova-alex",
            "broker_user": "nova-rescue-broker",
            "launcher": "/opt/nova/bin/run-rescue-broker",
            "lane": "tickets_agent",
            "workspace": "/srv/nova/workspaces/alex",
            "required": {
                "rescue_console_status",
                "rescue_list_sessions",
                "rescue_read_chat",
                "rescue_read_performance",
            },
            "forbidden": {"rescue_send_chat", "rescue_assign_session", "rescue_create_pin"},
        },
        "rescue_quality": {
            "model_user": "nova-claude",
            "broker_user": "nova-rescue-broker",
            "launcher": "/opt/nova/bin/run-rescue-broker",
            "lane": "claude_agent",
            "workspace": "/srv/nova/workspaces/claude",
            "required": {
                "rescue_console_status",
                "rescue_list_sessions",
                "rescue_read_chat",
                "rescue_read_performance",
            },
            "forbidden": {
                "rescue_send_chat",
                "rescue_assign_session",
                "rescue_create_pin",
                "rescue_transfer_session",
            },
        },
        "zoom_coding": {
            "model_user": "nova-taylor",
            "broker_user": "nova-zoom-broker",
            "launcher": "/opt/nova/bin/run-zoom-broker",
            "lane": "coding_agent",
            "workspace": "/srv/nova/workspaces/taylor",
            "required": shared_zoom
            | {
                "zoom_health",
                "zoom_support_chat_snapshot",
                "zoom_team_chat_recipient_resolve",
                "zoom_team_chat_send",
                "zoom_ghostbusters_overview_update",
            },
            "forbidden": {"zoom_update", "zoom_delete", "zoom_transfer"},
        },
        "zoom_support": {
            "model_user": "nova-alex",
            "broker_user": "nova-zoom-broker",
            "launcher": "/opt/nova/bin/run-zoom-broker",
            "lane": "tickets_agent",
            "workspace": "/srv/nova/workspaces/alex",
            "required": shared_zoom
            | {
                "zoom_health",
                "zoom_support_chat_snapshot",
                "zoom_team_chat_recipient_resolve",
                "zoom_team_chat_send",
                "zoom_weekly_support_metrics",
                "zoom_weekly_yaron_report_send",
            },
            "forbidden": {"zoom_update", "zoom_delete", "zoom_transfer"},
        },
        "zoom_billing": {
            "model_user": "nova-jamie",
            "broker_user": "nova-zoom-broker",
            "launcher": "/opt/nova/bin/run-zoom-broker",
            "lane": "billing_agent",
            "workspace": "/srv/nova/workspaces/jamie",
            "required": shared_zoom
            | {
                "zoom_health",
                "zoom_team_chat_recipient_resolve",
                "zoom_team_chat_send",
            },
            "forbidden": {
                "zoom_support_chat_snapshot",
                "zoom_weekly_support_metrics",
                "zoom_weekly_yaron_report_send",
                "zoom_update",
                "zoom_delete",
                "zoom_transfer",
            },
        },
        "zoom_quality": {
            "model_user": "nova-claude",
            "broker_user": "nova-zoom-broker",
            "launcher": "/opt/nova/bin/run-zoom-broker",
            "lane": "claude_agent",
            "workspace": "/srv/nova/workspaces/claude",
            "required": shared_zoom
            | {
                "zoom_health",
                "zoom_ghostbusters_overview_update",
                "zoom_quality_voice_engagements",
                "zoom_quality_agent_performance",
                "zoom_quality_engagement_recordings",
                "zoom_quality_transcript",
            },
            "forbidden": {
                "zoom_support_chat_snapshot",
                "zoom_team_chat_recipient_resolve",
                "zoom_team_chat_send",
                "zoom_weekly_support_metrics",
                "zoom_weekly_yaron_report_send",
                "zoom_update",
                "zoom_delete",
                "zoom_transfer",
            },
        },
        "zoom_rory": {
            "model_user": "nova-rory",
            "broker_user": "nova-zoom-broker",
            "launcher": "/opt/nova/bin/run-zoom-broker",
            "lane": "direct_codex",
            "workspace": "/srv/nova/workspaces/rory",
            "required": shared_zoom
            | {
                "zoom_health",
                "zoom_team_chat_recipient_resolve",
                "zoom_team_chat_send",
                "zoom_ghostbusters_overview_update",
            },
            "forbidden": {
                "zoom_support_chat_snapshot",
                "zoom_weekly_support_metrics",
                "zoom_weekly_yaron_report_send",
                "zoom_delete",
                "zoom_transfer",
            },
        },
        "rory_cloud": {
            "model_user": "nova-rory",
            "broker_user": "nova-cloud-broker",
            "launcher": "/opt/nova/bin/run-cloud-ops-broker",
            "lane": "direct_codex",
            "workspace": "/srv/nova/workspaces/rory",
            "required": {
                "gcp_capabilities",
                "gcp_project_status",
                "gcp_list_enabled_services",
                "gcp_search_resources",
                "gcp_list_cloud_run_services",
                "gcp_list_cloud_builds",
                "gcp_list_secret_metadata",
                "gcp_read_recent_logs",
                "github_capabilities",
                "github_list_repositories",
                "github_repository",
                "github_list_pull_requests",
                "github_list_workflow_runs",
                "github_publish_branch",
                "github_open_pull_request",
            },
            "forbidden": {"github_merge_pull_request", "github_delete_repository", "gcp_deploy", "gcp_update_iam"},
        },
        "taylor_cloud": {
            "model_user": "nova-taylor",
            "broker_user": "nova-cloud-broker",
            "launcher": "/opt/nova/bin/run-cloud-ops-broker",
            "lane": "coding_agent",
            "workspace": "/srv/nova/workspaces/taylor",
            "required": {
                "gcp_capabilities",
                "gcp_project_status",
                "gcp_list_enabled_services",
                "gcp_search_resources",
                "gcp_list_cloud_run_services",
                "gcp_list_cloud_builds",
                "gcp_list_secret_metadata",
                "gcp_read_recent_logs",
                "github_capabilities",
                "github_list_repositories",
                "github_repository",
                "github_list_pull_requests",
                "github_list_workflow_runs",
                "github_publish_branch",
                "github_open_pull_request",
                "github_scoped_sql_pull_request_preview",
                "github_scoped_sql_pull_request_merge",
                "gcp_agent_runtime_release_preview",
                "gcp_agent_runtime_release_apply",
                "gcp_agent_runtime_release_status",
            },
            "forbidden": {
                "github_delete_repository",
                "gcp_update_iam",
            },
        },
        "rory_operator": {
            "model_user": "nova-rory",
            "broker_user": "nova-cloud-broker",
            "launcher": "/opt/nova/bin/run-operator-broker",
            "lane": "direct_codex",
            "workspace": "/srv/nova/workspaces/rory",
            "required": {
                "operator_capabilities",
                "command_center_api_request",
                "gcp_api_request",
                "github_api_request",
                "salesforce_api_request",
                "maxio_chargify_api_request",
                "logmein_rescue_api_request",
                "zoom_api_request",
                "google_workspace_api_request",
            },
            "forbidden": set(),
        },
        "google_drive_thor": {
            "model_user": "nova-claude",
            "broker_user": "nova-cloud-broker",
            "launcher": "/opt/nova/bin/run-thor-drive-broker",
            "lane": "claude_agent",
            "workspace": "/srv/nova/workspaces/claude",
            "required": thor_google_support_reads,
            "forbidden": {
                "google_workspace_api_request",
                "github_api_request",
                "gcp_api_request",
                "salesforce_api_request",
                "maxio_chargify_api_request",
                "logmein_rescue_api_request",
                "zoom_api_request",
            },
        },
    }
    lanes: dict[str, Any] = {}
    for name, raw_spec in specs.items():
        spec = dict(raw_spec)
        required = set(spec.pop("required"))
        forbidden = set(spec.pop("forbidden"))
        try:
            names = await _mcp_tool_names(**spec)
            unsafe_maxio_names = {
                tool
                for tool in names
                if name.startswith("maxio_")
                and any(part in tool.casefold() for part in ("delete", "destroy", "purge"))
            }
            missing = required - names
            exposed = (forbidden & names) | unsafe_maxio_names
            operation_ready = True
            if name == "salesforce_coding":
                sql_capabilities = await _mcp_call_json(
                    **spec,
                    tool_name="nova_sql_capabilities",
                )
                operation_ready = bool(
                    sql_capabilities.get("instyleDemoRebuildConfigured")
                    and sql_capabilities.get("tableRestore", {}).get("configured")
                )
            lanes[name] = {
                "ok": not missing and not exposed and operation_ready,
                "toolCount": len(names),
                "requiredToolsPresent": not missing,
                "forbiddenToolsAbsent": not exposed,
                "operationDependenciesReady": operation_ready,
            }
        except Exception as exc:
            lanes[name] = {"ok": False, "errorType": type(exc).__name__}
    readiness = _required_optional_readiness(
        lanes,
        optional_names=OPTIONAL_SCOPED_MCP_LANES,
    )
    return {
        "ok": readiness["ok"],
        "degraded": readiness["degraded"],
        "requiredLanes": readiness["required"],
        "optionalLanes": readiness["optional"],
        "optionalFailures": readiness["optionalFailures"],
        "lanes": lanes,
    }


async def _probe_live_scoped_connectors_async() -> dict[str, Any]:
    specs = {
        "rescue": {
            "model_user": "nova-alex",
            "broker_user": "nova-rescue-broker",
            "launcher": "/opt/nova/bin/run-rescue-broker",
            "lane": "tickets_agent",
            "workspace": "/srv/nova/workspaces/alex",
            "tool_name": "rescue_list_sessions",
        },
        "thor_rescue": {
            "model_user": "nova-claude",
            "broker_user": "nova-rescue-broker",
            "launcher": "/opt/nova/bin/run-rescue-broker",
            "lane": "claude_agent",
            "workspace": "/srv/nova/workspaces/claude",
            "tool_name": "rescue_list_sessions",
        },
        "zoom": {
            "model_user": "nova-alex",
            "broker_user": "nova-zoom-broker",
            "launcher": "/opt/nova/bin/run-zoom-broker",
            "lane": "tickets_agent",
            "workspace": "/srv/nova/workspaces/alex",
            "tool_name": "zoom_health",
        },
        "thor_zoom": {
            "model_user": "nova-claude",
            "broker_user": "nova-zoom-broker",
            "launcher": "/opt/nova/bin/run-zoom-broker",
            "lane": "claude_agent",
            "workspace": "/srv/nova/workspaces/claude",
            "tool_name": "zoom_ghostbusters_overview_read",
        },
        "thor_salesforce": {
            "model_user": "nova-claude",
            "broker_user": "nova-salesforce-broker",
            "launcher": "/opt/nova/bin/run-salesforce-broker",
            "lane": "claude_agent",
            "workspace": "/srv/nova/workspaces/claude",
            "tool_name": "salesforce_capabilities",
        },
        "rory_zoom": {
            "model_user": "nova-rory",
            "broker_user": "nova-zoom-broker",
            "launcher": "/opt/nova/bin/run-zoom-broker",
            "lane": "direct_codex",
            "workspace": "/srv/nova/workspaces/rory",
            "tool_name": "zoom_ghostbusters_overview_read",
        },
        "gcp": {
            "model_user": "nova-rory",
            "broker_user": "nova-cloud-broker",
            "launcher": "/opt/nova/bin/run-cloud-ops-broker",
            "lane": "direct_codex",
            "workspace": "/srv/nova/workspaces/rory",
            "tool_name": "gcp_project_status",
        },
        "github": {
            "model_user": "nova-rory",
            "broker_user": "nova-cloud-broker",
            "launcher": "/opt/nova/bin/run-cloud-ops-broker",
            "lane": "direct_codex",
            "workspace": "/srv/nova/workspaces/rory",
            "tool_name": "github_list_repositories",
            "arguments": {"max_rows": 20},
        },
        "taylor_github": {
            "model_user": "nova-taylor",
            "broker_user": "nova-cloud-broker",
            "launcher": "/opt/nova/bin/run-cloud-ops-broker",
            "lane": "coding_agent",
            "workspace": "/srv/nova/workspaces/taylor",
            "tool_name": "github_capabilities",
        },
        "rory_operator": {
            "model_user": "nova-rory",
            "broker_user": "nova-cloud-broker",
            "launcher": "/opt/nova/bin/run-operator-broker",
            "lane": "direct_codex",
            "workspace": "/srv/nova/workspaces/rory",
            "tool_name": "operator_capabilities",
        },
        "maxio_billing": {
            "model_user": "nova-jamie",
            "broker_user": "nova-maxio-broker",
            "launcher": "/opt/nova/bin/run-maxio-broker",
            "lane": "billing_agent",
            "workspace": "/srv/nova/workspaces/jamie",
            "tool_name": "maxio_capabilities",
        },
    }
    results: dict[str, Any] = {}
    for name, spec in specs.items():
        try:
            payload = await _mcp_call_json(**spec)
            results[name] = {"ok": bool(payload.get("ok"))}
            if name == "rescue":
                results[name]["sessionCount"] = len((payload.get("api") or {}).get("sessions") or [])
            elif name == "github":
                results[name]["repositoryCount"] = int(payload.get("count") or 0)
            elif name == "taylor_github":
                results[name].update(
                    {
                        "accessMode": str(payload.get("accessMode") or ""),
                        "directProtectedBranchWrites": bool(
                            payload.get("directProtectedBranchWrites")
                        ),
                        "mergeToolsExposed": bool(payload.get("mergeToolsExposed")),
                        "inlineFilePayloadsAccepted": bool(
                            payload.get("inlineFilePayloadsAccepted")
                        ),
                        "brokerWorkspaceTraversalRequired": bool(
                            payload.get("brokerWorkspaceTraversalRequired")
                        ),
                    }
                )
                results[name]["ok"] = bool(
                    payload.get("ok")
                    and not payload.get("directProtectedBranchWrites")
                    and payload.get("mergeToolsExposed")
                    and payload.get("inlineFilePayloadsAccepted")
                    and not payload.get("brokerWorkspaceTraversalRequired")
                )
            elif name == "gcp":
                results[name]["projectId"] = str(payload.get("projectId") or "")
            elif name == "rory_operator":
                results[name]["accessMode"] = str(payload.get("accessMode") or "")
            elif name == "maxio_billing":
                results[name].update(
                    {
                        "accessMode": str(payload.get("accessMode") or ""),
                        "mutationExposed": bool(payload.get("mutationExposed")),
                        "deleteExposed": bool(payload.get("deleteExposed")),
                        "typedSubscriptionCancellationExposed": bool(
                            payload.get("typedSubscriptionCancellationExposed")
                        ),
                        "typedPaymentProfileAssignmentExposed": bool(
                            payload.get("typedPaymentProfileAssignmentExposed")
                        ),
                        "typedSecurePaymentUpdateRequestExposed": bool(
                            payload.get("typedSecurePaymentUpdateRequestExposed")
                        ),
                        "typedSubscriptionReactivationExposed": bool(
                            payload.get("typedSubscriptionReactivationExposed")
                        ),
                        "rawPaymentDetailsAccepted": bool(
                            payload.get("rawPaymentDetailsAccepted")
                        ),
                        "permissionAdministrationExposed": bool(
                            payload.get("permissionAdministrationExposed")
                        ),
                    }
                )
                results[name]["ok"] = bool(
                    payload.get("ok")
                    and payload.get("mutationExposed")
                    and not payload.get("deleteExposed")
                    and payload.get("typedSubscriptionCancellationExposed")
                    and payload.get("typedPaymentProfileAssignmentExposed")
                    and payload.get("typedSecurePaymentUpdateRequestExposed")
                    and payload.get("typedSubscriptionReactivationExposed")
                    and not payload.get("rawPaymentDetailsAccepted")
                    and not payload.get("permissionAdministrationExposed")
                )
        except Exception as exc:
            results[name] = {"ok": False, "errorType": type(exc).__name__}
    readiness = _required_optional_readiness(
        results,
        optional_names=OPTIONAL_LIVE_CONNECTORS,
    )
    return {
        "ok": readiness["ok"],
        "degraded": readiness["degraded"],
        "requiredConnectors": readiness["required"],
        "optionalConnectors": readiness["optional"],
        "optionalFailures": readiness["optionalFailures"],
        "connectors": results,
    }


def _probe_live_scoped_connectors() -> dict[str, Any]:
    return asyncio.run(_probe_live_scoped_connectors_async())


def _probe_singapore() -> dict[str, Any]:
    result = subprocess.run(
        [
            "/usr/sbin/runuser",
            "-u",
            "nova-singapore-broker",
            "--",
            "/opt/nova/bin/run-singapore-background",
            "--preflight",
        ],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    if result.returncode != 0:
        return {"ok": False, "errorType": "SingaporePreflightFailed"}
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    return {
        "ok": bool(payload.get("ok") and payload.get("gmailAuthenticated")),
        "configuredServerCount": int(payload.get("configuredServerCount") or 0),
        "activeServerCount": int(payload.get("activeServerCount") or 0),
        "uploadAttempted": False,
        "messageSent": False,
    }


def _probe_codex_runtime_approval_policy() -> dict[str, Any]:
    config = load_config("/opt/nova/current/config/agents.gcp-runtime.yaml")
    specs = {
        "direct_codex": ("rory", "nova-rory", True),
        "raw_codex": ("raw", "nova-raw", False),
        "claude_agent": ("claude", "nova-claude", False),
        "coding_agent": ("taylor", "nova-taylor", True),
        "tickets_agent": ("alex", "nova-alex", True),
        "billing_agent": ("jamie", "nova-jamie", True),
    }
    lanes: dict[str, Any] = {}
    for lane, (template, model_user, write_enabled) in specs.items():
        policy_path = Path(f"/etc/nova/codex-mcp-policy/{template}.toml")
        home_path = Path(f"/home/{model_user}/.codex/config.toml")
        try:
            policy = tomllib.loads(policy_path.read_text(encoding="utf-8"))
            effective = tomllib.loads(home_path.read_text(encoding="utf-8"))
            configured_servers = set((policy.get("mcp_servers") or {}).keys())
            expected_servers = set(config.agents[lane].get("mcp_allowlist") or [])
            same_config = policy == effective
            approval_ok = (
                policy.get("approval_policy") == "never"
                and policy.get("approvals_reviewer") == "user"
            )
            telemetry_disabled = (
                ((policy.get("analytics") or {}).get("enabled") is False)
                and ((policy.get("feedback") or {}).get("enabled") is False)
                and str((policy.get("otel") or {}).get("exporter") or "") == "none"
                and str((policy.get("otel") or {}).get("metrics_exporter") or "") == "none"
                and str((policy.get("otel") or {}).get("trace_exporter") or "") == "none"
                and ((policy.get("otel") or {}).get("log_user_prompt") is False)
            )
            required_preapproved_servers = configured_servers
            server_approvals_ok = required_preapproved_servers <= configured_servers and all(
                str(
                    ((policy.get("mcp_servers") or {}).get(server_name) or {}).get(
                        "default_tools_approval_mode"
                    )
                    or ""
                ).strip()
                == "approve"
                for server_name in required_preapproved_servers
            )
            lanes[lane] = {
                "ok": bool(
                    same_config
                    and configured_servers == expected_servers
                    and approval_ok
                    and telemetry_disabled
                    and server_approvals_ok
                ),
                "effectiveConfigMatchesPolicy": same_config,
                "mcpAllowlistMatches": configured_servers == expected_servers,
                "approvalPolicyMatches": approval_ok,
                "telemetryDisabled": telemetry_disabled,
                "serverApprovalsMatch": server_approvals_ok,
                "requiredPreapprovedServers": sorted(required_preapproved_servers),
                "mcpServerCount": len(configured_servers),
            }
        except Exception as exc:
            lanes[lane] = {"ok": False, "errorType": type(exc).__name__}
    readiness = _required_optional_readiness(
        lanes,
        optional_names=("raw_codex",),
    )
    return {
        "ok": readiness["ok"],
        "degraded": readiness["degraded"],
        "requiredLanes": readiness["required"],
        "optionalLanes": readiness["optional"],
        "optionalFailures": readiness["optionalFailures"],
        "lanes": lanes,
    }


def _runtime_readiness(checks: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Keep the dashboard available while reporting lane/provider degradation."""

    core_failures = [
        name for name in CORE_RUNTIME_CHECKS if not bool(checks.get(name, {}).get("ok"))
    ]
    degraded_checks = [
        name
        for name, value in checks.items()
        if name not in CORE_RUNTIME_CHECKS and not bool(value.get("ok"))
    ]
    return {
        "ok": not core_failures,
        "fullyReady": not core_failures and not degraded_checks,
        "degraded": bool(core_failures or degraded_checks),
        "coreRequiredChecks": list(CORE_RUNTIME_CHECKS),
        "coreFailures": core_failures,
        "degradedChecks": degraded_checks,
    }


def _probe_deterministic_ticket_close() -> dict[str, Any]:
    command = [
        "/usr/sbin/runuser",
        "-u",
        "nova-runtime",
        "--",
        "/usr/bin/sudo",
        "-n",
        "-H",
        "-u",
        "nova-salesforce-broker",
        "--",
        "/opt/nova/bin/run-salesforce-ticket-close",
    ]
    result = subprocess.run(
        command,
        input='{"action":"preflight"}',
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    payload = json.loads(result.stdout.strip().splitlines()[-1]) if result.stdout.strip() else {}
    unauthorized_users = []
    for user in ("nova-rory", "nova-raw", "nova-claude", "nova-taylor", "nova-alex", "nova-jamie"):
        denied = subprocess.run(
            [
                "/usr/sbin/runuser",
                "-u",
                user,
                "--",
                "/usr/bin/sudo",
                "-n",
                "-H",
                "-u",
                "nova-salesforce-broker",
                "--",
                "/opt/nova/bin/run-salesforce-ticket-close",
            ],
            input='{"action":"preflight"}',
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if denied.returncode == 0:
            unauthorized_users.append(user)
    ok = bool(
        result.returncode == 0
        and payload.get("ok")
        and payload.get("accessMode") == "typed_ticket_close_only"
        and payload.get("emailSendExposed") is False
        and not unauthorized_users
    )
    return {
        "ok": ok,
        "runtimeCanInvoke": result.returncode == 0,
        "typedCloseOnly": payload.get("accessMode") == "typed_ticket_close_only",
        "emailSendExposed": bool(payload.get("emailSendExposed")),
        "unauthorizedModelUsersBlocked": not unauthorized_users,
    }


def _probe_deterministic_location_region_update() -> dict[str, Any]:
    launcher = "/opt/nova/bin/run-nova-location-region"
    command = [
        "/usr/sbin/runuser",
        "-u",
        "nova-runtime",
        "--",
        "/usr/bin/sudo",
        "-n",
        "-H",
        "-u",
        "nova-salesforce-broker",
        "--",
        launcher,
    ]
    result = subprocess.run(
        command,
        input='{"action":"preflight"}',
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    payload = (
        json.loads(result.stdout.strip().splitlines()[-1])
        if result.stdout.strip()
        else {}
    )
    unauthorized_users = []
    for user in (
        "nova-rory",
        "nova-raw",
        "nova-claude",
        "nova-taylor",
        "nova-alex",
        "nova-jamie",
    ):
        denied = subprocess.run(
            [
                "/usr/sbin/runuser",
                "-u",
                user,
                "--",
                "/usr/bin/sudo",
                "-n",
                "-H",
                "-u",
                "nova-salesforce-broker",
                "--",
                launcher,
            ],
            input='{"action":"preflight"}',
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if denied.returncode == 0:
            unauthorized_users.append(user)
    ok = bool(
        result.returncode == 0
        and payload.get("ok")
        and payload.get("accessMode")
        == "fixed_location_region_update_only"
        and payload.get("arbitrarySqlAccepted") is False
        and payload.get("deleteExposed") is False
        and not unauthorized_users
    )
    return {
        "ok": ok,
        "runtimeCanInvoke": result.returncode == 0,
        "fixedLocationRegionOnly": payload.get("accessMode")
        == "fixed_location_region_update_only",
        "arbitrarySqlAccepted": payload.get("arbitrarySqlAccepted") is not False,
        "deleteExposed": payload.get("deleteExposed") is not False,
        "unauthorizedModelUsersBlocked": not unauthorized_users,
    }


def _probe_support_email_ticket_readback() -> dict[str, Any]:
    command = [
        "/usr/sbin/runuser",
        "-u",
        "nova-runtime",
        "--",
        "/usr/bin/sudo",
        "-n",
        "-H",
        "-u",
        "nova-salesforce-broker",
        "--",
        "/opt/nova/bin/run-salesforce-support-email-readback",
    ]
    result = subprocess.run(
        command,
        input='{"action":"preflight"}',
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    payload = json.loads(result.stdout.strip().splitlines()[-1]) if result.stdout.strip() else {}
    unauthorized_users = []
    for user in ("nova-rory", "nova-raw", "nova-claude", "nova-taylor", "nova-alex", "nova-jamie"):
        denied = subprocess.run(
            [
                "/usr/sbin/runuser",
                "-u",
                user,
                "--",
                "/usr/bin/sudo",
                "-n",
                "-H",
                "-u",
                "nova-salesforce-broker",
                "--",
                "/opt/nova/bin/run-salesforce-support-email-readback",
            ],
            input='{"action":"preflight"}',
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if denied.returncode == 0:
            unauthorized_users.append(user)
    ok = bool(
        result.returncode == 0
        and payload.get("ok")
        and payload.get("accessMode") == "typed_support_email_ticket_readback_only"
        and payload.get("source") == "nova-runtime:typed-live-salesforce-ticket-readback"
        and payload.get("readOnly") is True
        and payload.get("arbitrarySalesforceAccess") is False
        and payload.get("writesExposed") is False
        and payload.get("emailSendExposed") is False
        and payload.get("customerDataExposed") is False
        and not unauthorized_users
    )
    return {
        "ok": ok,
        "runtimeCanInvoke": result.returncode == 0,
        "typedReadbackOnly": payload.get("accessMode")
        == "typed_support_email_ticket_readback_only",
        "receiptSourceVerified": payload.get("source")
        == "nova-runtime:typed-live-salesforce-ticket-readback",
        "readOnly": payload.get("readOnly") is True,
        "arbitrarySalesforceAccessExposed": payload.get("arbitrarySalesforceAccess") is not False,
        "writesExposed": payload.get("writesExposed") is not False,
        "emailSendExposed": payload.get("emailSendExposed") is not False,
        "customerDataExposed": payload.get("customerDataExposed") is not False,
        "unauthorizedModelUsersBlocked": not unauthorized_users,
    }


def _probe_support_quality_ticket_projection() -> dict[str, Any]:
    launcher = "/opt/nova/bin/run-salesforce-support-quality-projection"
    command = [
        "/usr/sbin/runuser",
        "-u",
        "nova-runtime",
        "--",
        "/usr/bin/sudo",
        "-n",
        "-H",
        "-u",
        "nova-salesforce-broker",
        "--",
        launcher,
    ]
    result = subprocess.run(
        command,
        input='{"action":"preflight"}',
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    payload = json.loads(result.stdout.strip().splitlines()[-1]) if result.stdout.strip() else {}
    unauthorized_users = []
    for user in ("nova-rory", "nova-raw", "nova-claude", "nova-taylor", "nova-alex", "nova-jamie"):
        denied = subprocess.run(
            [
                "/usr/sbin/runuser",
                "-u",
                user,
                "--",
                "/usr/bin/sudo",
                "-n",
                "-H",
                "-u",
                "nova-salesforce-broker",
                "--",
                launcher,
            ],
            input='{"action":"preflight"}',
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if denied.returncode == 0:
            unauthorized_users.append(user)
    ok = bool(
        result.returncode == 0
        and payload.get("ok")
        and payload.get("accessMode")
        == "typed_support_quality_ticket_projection_only"
        and payload.get("source")
        == "nova-runtime:typed-salesforce-support-quality-ticket-projection"
        and payload.get("fixedRosterCount") == 6
        and payload.get("maxWindowDays") == 8
        and payload.get("readOnly") is True
        and payload.get("writesPerformed") is False
        and payload.get("writesExposed") is False
        and payload.get("genericQueryExposed") is False
        and payload.get("ticketContentExposed") is False
        and payload.get("customerDataExposed") is False
        and not unauthorized_users
    )
    return {
        "ok": ok,
        "runtimeCanInvoke": result.returncode == 0,
        "typedProjectionOnly": payload.get("accessMode")
        == "typed_support_quality_ticket_projection_only",
        "receiptSourceVerified": payload.get("source")
        == "nova-runtime:typed-salesforce-support-quality-ticket-projection",
        "fixedRosterCount": payload.get("fixedRosterCount"),
        "maxWindowDays": payload.get("maxWindowDays"),
        "readOnly": payload.get("readOnly") is True,
        "writesPerformed": payload.get("writesPerformed") is True,
        "writesExposed": payload.get("writesExposed") is not False,
        "genericQueryExposed": payload.get("genericQueryExposed") is not False,
        "ticketContentExposed": payload.get("ticketContentExposed") is not False,
        "customerDataExposed": payload.get("customerDataExposed") is not False,
        "unauthorizedModelUsersBlocked": not unauthorized_users,
    }


def _probe_singapore_shared_access() -> dict[str, Any]:
    shared = Path("/var/lib/nova/broker/singapore-shared")
    target = shared / f".preflight-shared-{os.getpid()}.json"
    writer = (
        "import os,sys; from pathlib import Path; "
        "os.umask(0o007); p=Path(sys.argv[1]); "
        "t=p.parent / ('.' + p.name + '.' + str(os.getpid()) + '.tmp'); "
        "t.write_text(sys.argv[2], encoding='utf-8'); os.replace(t,p)"
    )
    results: dict[str, bool] = {}
    try:
        for user in ("nova-singapore-broker", "nova-runtime", "nova-singapore-broker"):
            completed = subprocess.run(
                ["/usr/sbin/runuser", "-u", user, "--", "/usr/bin/python3", "-c", writer, str(target), user],
                capture_output=True,
                timeout=10,
                check=False,
            )
            results[f"{user}:{len(results)}"] = completed.returncode == 0
        final_owner = target.read_text(encoding="utf-8") if target.is_file() else ""
    finally:
        target.unlink(missing_ok=True)
    ok = all(results.values()) and final_owner == "nova-singapore-broker"
    return {
        "ok": ok,
        "brokerRuntimeBrokerReplaceCycle": all(results.values()),
        "finalWriterVerified": final_owner == "nova-singapore-broker",
    }


def _probe_scoped_mcp_brokers() -> dict[str, Any]:
    return asyncio.run(_probe_scoped_mcp_brokers_async())


def main() -> None:
    ZOOM_PREFLIGHT_MARKER.unlink(missing_ok=True)
    checks: dict[str, Any] = {}
    probes = {
        "slack": _probe_slack,
        "gmail": _probe_gmail,
        "agent_file_delivery": _probe_agent_file_delivery,
        "google_workspace": _probe_google_workspace,
        "chargify": _probe_chargify,
        "codex_cli": _probe_codex,
        "rory_isolation": _probe_rory_isolation,
        "codex_runtime_approval_policy": _probe_codex_runtime_approval_policy,
        "scoped_mcp_brokers": _probe_scoped_mcp_brokers,
        "live_scoped_connectors": _probe_live_scoped_connectors,
        "deterministic_ticket_close": _probe_deterministic_ticket_close,
        "deterministic_location_region_update": _probe_deterministic_location_region_update,
        "support_email_ticket_readback": _probe_support_email_ticket_readback,
        "support_quality_ticket_projection": _probe_support_quality_ticket_projection,
        "singapore": _probe_singapore,
        "singapore_shared_access": _probe_singapore_shared_access,
    }
    for name, probe in probes.items():
        try:
            checks[name] = probe()
        except Exception as exc:
            checks[name] = {"ok": False, "errorType": type(exc).__name__}
    try:
        checks["salesforce"], checks["nova_sql"] = _probe_salesforce_and_sql()
    except Exception as exc:
        checks["salesforce"] = {"ok": False, "errorType": type(exc).__name__}
        checks["nova_sql"] = {"ok": False, "blockedBy": "salesforce_or_network"}

    readiness = _runtime_readiness(checks)
    ok = readiness["ok"]
    zoom_ok = bool(
        checks.get("live_scoped_connectors", {})
        .get("connectors", {})
        .get("zoom", {})
        .get("ok")
    )
    if ok and zoom_ok:
        ZOOM_PREFLIGHT_MARKER.touch(mode=0o600)
        ZOOM_PREFLIGHT_MARKER.chmod(0o600)
    print(
        json.dumps(
            {**readiness, "checks": checks},
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
