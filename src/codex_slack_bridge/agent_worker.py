from __future__ import annotations

# Disposable per-job worker boundary. Codex and optional reasoning relay coexist.

import json
import os
import sys
from contextlib import nullcontext
from typing import Any

from .agents import (
    AgentRequest,
    _assess_request_live_write,
    _redact_trace,
    _require_request_authority,
    pop_agent_usage,
    run_agent,
)
from .codex_tool_broker import ScopedToolBrokerServer
from .safety import build_child_process_env


PROACTIVE_TICKET_TOOL_ALLOWLISTS: dict[str, dict[str, tuple[str, ...]]] = {
    "tickets_agent": {
        "salesforce_support_ops": (
            "salesforce_capabilities",
            "salesforce_lookup",
            "salesforce_account_360_read",
            "salesforce_ticket_read",
            "salesforce_ticket_feed_read",
            "salesforce_ticket_email_log_read",
            "nova_sql_capabilities",
            "nova_sql_preflight",
            "nova_sql_invoice_spare_investigation",
            "nova_sql_read",
        ),
        "rescue_console": (
            "rescue_console_status",
            "rescue_list_sessions",
            "rescue_read_chat",
            "rescue_read_performance",
        ),
    },
    "billing_agent": {
        "salesforce_billing_ops": (
            "salesforce_capabilities",
            "salesforce_lookup",
            "salesforce_account_360_read",
            "salesforce_ticket_read",
            "salesforce_ticket_feed_read",
            "salesforce_ticket_email_log_read",
            "nova_billing_locations_read",
            "salesforce_billing_account_read",
            "salesforce_billing_account_locations_read",
            "salesforce_billing_account_orders_read",
            "salesforce_billing_structure_read",
            "salesforce_location_lifecycle_order_preview",
            "salesforce_billing_schedule_date_preview",
            "salesforce_billing_location_alignment_preview",
            "salesforce_billing_structure_alignment_preview",
            "salesforce_account_closure_preview",
            "salesforce_account_cancellation_order_preview",
            "salesforce_location_cancellation_order_preview",
            "salesforce_account_cancellation_pdf_status",
            "salesforce_account_cancellation_email_attachment_status",
        ),
        "maxio_billing_ops": (
            "maxio_capabilities",
            "maxio_health",
            "maxio_customers_by_reference",
            "maxio_customers_search",
            "maxio_customer",
            "maxio_subscriptions_by_customer",
            "maxio_subscription",
            "maxio_subscription_components",
            "maxio_payment_profiles_by_customer",
            "maxio_invoices_by_customer",
            "maxio_invoice",
            "maxio_subscription_account_balances",
            "maxio_location_allocation_reconciliation_read",
            "maxio_subscription_creation_preview",
            "maxio_component_allocation_preview",
            "maxio_manual_service_credit_preview",
            "maxio_component_payment_recovery_preview",
            "maxio_subscription_payment_profile_assignment_preview",
            "maxio_payment_profile_update_request_preview",
            "maxio_subscription_reactivation_preview",
            "maxio_subscription_no_charge_reactivation_preview",
            "maxio_subscription_cancellation_preview",
            "maxio_invoice_refund_preview",
            "maxio_subscription_coupon_preview",
            "maxio_subscription_product_change_preview",
            "maxio_nova_integrated_promo_credit_preview",
            "maxio_billing_cycle_recovery_preview",
        ),
    },
}


def _bounded_tool_inventory(agent_name: str, task_kind: str) -> dict[str, tuple[str, ...]] | None:
    if str(task_kind or "").strip() != "ops-salesforce-ticket-investigation":
        return None
    return PROACTIVE_TICKET_TOOL_ALLOWLISTS.get(str(agent_name or "").strip())


def _relay_enabled() -> bool:
    return str(os.getenv("REASONING_RELAY_ENABLED") or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }

def _select_execution_backend(
    provider: str, requested: str, *, relay_enabled: bool
) -> str:
    """Choose one backend without allowing the relay flag to hijack Codex."""
    configured = str(provider or "").strip().lower()
    requested = str(requested or "").strip().lower()
    codex_providers = {"codex_cli", "codex_cli_direct"}
    relay_providers = {"chatgpt_work_relay", "chatgpt_relay"}
    if configured not in codex_providers | relay_providers:
        raise ValueError("Agent provider is not available for execution")
    if requested not in {"", "codex_cli", "chatgpt_relay"}:
        raise ValueError("Unsupported reasoning provider override")
    if requested == "chatgpt_relay":
        if not relay_enabled:
            raise RuntimeError("ChatGPT reasoning relay is not enabled")
        return "relay"
    if requested == "codex_cli":
        if configured not in codex_providers:
            raise PermissionError("Codex CLI is not configured for this agent")
        return "codex"
    # An environment flag enables optional relay availability only.
    return "relay" if configured in relay_providers else "codex"


def main() -> None:
    try:
        payload = json.loads(sys.stdin.buffer.read().decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("Agent worker payload must be an object.")
        agent_name = str(payload.get("agentName") or "").strip()
        agent = payload.get("agent") if isinstance(payload.get("agent"), dict) else {}
        request_payload = payload.get("request") if isinstance(payload.get("request"), dict) else {}
        request = AgentRequest(**_request_fields(request_payload))
        provider = str(agent.get("provider") or "").strip()
        backend = _select_execution_backend(
            provider,
            request.reasoning_provider,
            relay_enabled=_relay_enabled(),
        )
        if backend == "relay":
            # The brokered relay has the same signed instruction and lane policy.
            # A failed relay never silently falls back to Codex for this job.
            from .reasoning_relay_runtime_secure import run_reasoning_relay_agent

            result = run_reasoning_relay_agent(agent_name, agent, request)
        else:
            configured = dict(agent)
            configured.setdefault("name", agent_name)
            authority = _require_request_authority(configured, request)
            child_env, _policy = build_child_process_env(
                configured, trusted_instruction=authority.operator_authorized
            )
            live_write = _assess_request_live_write(request, authority)
            allowed_servers = tuple(
                str(item) for item in configured.get("mcp_allowlist") or []
            )
            config_path = str(
                configured.get("mcp_config_path")
                or configured.get("codex_mcp_config_path")
                or ""
            ).strip() or None
            broker_context = (
                ScopedToolBrokerServer(
                    lane=agent_name,
                    allowed_servers=allowed_servers,
                    child_env=child_env,
                    config_path=config_path,
                    allow_write=bool(live_write.explicitly_authorized),
                    allowed_tools=_bounded_tool_inventory(agent_name, request.task_kind),
                )
                if allowed_servers
                else nullcontext({})
            )
            with broker_context as broker_env:
                previous = {name: os.environ.get(name) for name in broker_env}
                os.environ.update(broker_env)
                try:
                    result = run_agent(agent_name, configured, request)
                finally:
                    for name, value in previous.items():
                        if value is None:
                            os.environ.pop(name, None)
                        else:
                            os.environ[name] = value
        usage = pop_agent_usage(request.job_id) or {}
        response: dict[str, Any] = {"ok": True, "result": result, "usage": usage}
    except Exception as exc:
        response = {
            "ok": False,
            "error": _redact_trace(f"{type(exc).__name__}: {exc}")[:1600],
        }
    # Compatibility envelope retained for the parent worker protocol only.
    sys.stdout.write(_serialize_response(response))
    sys.stdout.flush()


def _serialize_response(response: dict[str, Any]) -> str:
    return "__CODEX_AGENT_RESULT__" + json.dumps(response, ensure_ascii=True)


def _request_fields(payload: dict[str, Any]) -> dict[str, Any]:
    allowed = set(AgentRequest.__dataclass_fields__)
    return {key: value for key, value in payload.items() if key in allowed}


if __name__ == "__main__":
    main()
