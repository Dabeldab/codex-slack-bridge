from __future__ import annotations

# AgentChat/direct_codex 2026-07-14T21:01:41-04:00: verify proactive financial approval language cannot authorize writes.

import pytest

from types import SimpleNamespace

from codex_slack_bridge.agents import AgentRequest, _assess_request_live_write, run_agent
from codex_slack_bridge.memory import redact_secrets
from codex_slack_bridge.safety import (
    assess_live_write_request,
    build_child_process_env,
    live_write_policy_block,
    sign_trusted_message,
    verify_trusted_message,
)


def test_child_process_env_scrubs_secret_like_names(monkeypatch):
    monkeypatch.setenv("ZOOM_OAUTH_REFRESH_TOKEN", "secret-refresh")
    monkeypatch.setenv("CHARGIFY_API_KEY", "secret-key")
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", "C:/secret.json")
    monkeypatch.setenv("PATH", "C:/Windows")
    monkeypatch.setenv("NOVA_SAFE_FLAG", "1")

    env, policy = build_child_process_env({"agent_child_env_secret_mode": "scrub"})

    assert "ZOOM_OAUTH_REFRESH_TOKEN" not in env
    assert "CHARGIFY_API_KEY" not in env
    assert "GOOGLE_APPLICATION_CREDENTIALS" not in env
    assert env["PATH"] == "C:/Windows"
    assert env["NOVA_SAFE_FLAG"] == "1"
    assert policy.mode == "scrub"
    assert "CHARGIFY_API_KEY" in policy.scrubbed_names


def test_child_process_env_honors_secret_allowlist(monkeypatch):
    monkeypatch.setenv("TEST_AGENT_SECRET", "allowed-for-this-agent")
    monkeypatch.setenv("SLACK_BOT_TOKEN", "still-blocked")

    env, policy = build_child_process_env(
        {
            "agent_child_env_secret_mode": "scrub",
            "agent_child_env_secret_allowlist": ["TEST_AGENT_SECRET"],
        }
    )

    assert env["TEST_AGENT_SECRET"] == "allowed-for-this-agent"
    assert "SLACK_BOT_TOKEN" not in env
    assert "SLACK_BOT_TOKEN" in policy.scrubbed_names


def test_verified_instruction_inherits_loaded_credentials(monkeypatch):
    monkeypatch.setenv("ZOOM_OAUTH_REFRESH_TOKEN", "available-to-trusted-run")

    env, policy = build_child_process_env(
        {"agent_child_env_secret_mode": "scrub"},
        trusted_instruction=True,
    )

    assert env["ZOOM_OAUTH_REFRESH_TOKEN"] == "available-to-trusted-run"
    assert policy.mode == "inherit"


def test_trusted_instruction_never_exports_salesforce_or_billing_credentials(monkeypatch):
    monkeypatch.setenv("SALESFORCE_ACCESS_TOKEN", "salesforce-secret")
    monkeypatch.setenv("CHARGIFY_API_KEY", "billing-secret")
    monkeypatch.setenv("ZOOM_OAUTH_REFRESH_TOKEN", "allowed-for-unrelated-service")

    env, policy = build_child_process_env(
        {"agent_child_env_secret_mode": "scrub"},
        trusted_instruction=True,
    )

    assert "SALESFORCE_ACCESS_TOKEN" not in env
    assert "CHARGIFY_API_KEY" not in env
    assert env["ZOOM_OAUTH_REFRESH_TOKEN"] == "allowed-for-unrelated-service"
    assert policy.mode == "inherit_except_non_exportable_services"


def test_live_write_assessment_requires_explicit_approval():
    assessment = assess_live_write_request("Can we close Salesforce ticket 347111?", guard_key="job-1")

    assert assessment.mode == "approval_required"
    assert "salesforce" in assessment.surfaces
    assert "close" in assessment.mutation_terms
    assert "approval_required" in live_write_policy_block(assessment)


def test_live_write_assessment_detects_explicit_authorization():
    assessment = assess_live_write_request("Please send the Gmail reply now.", guard_key="job-2")

    assert assessment.mode == "explicit_live_write"
    assert "gmail" in assessment.surfaces
    assert "send" in assessment.mutation_terms
    assert "job-2" in live_write_policy_block(assessment)


def test_verified_instruction_needs_no_approval_keyword():
    assessment = assess_live_write_request(
        "Close Salesforce ticket 347111.",
        guard_key="job-signed",
        trusted_instruction=True,
    )

    assert assessment.mode == "explicit_live_write"
    assert assessment.trusted_instruction is True
    assert "job-signed" in live_write_policy_block(assessment)


def test_financial_approval_policy_statement_is_not_write_authority():
    assessment = assess_live_write_request(
        "Refunds and rate changes are gated by my approval.",
        guard_key="job-policy",
        trusted_instruction=True,
    )

    assert assessment.mode == "trusted_instruction"
    assert assessment.mutation_terms == ()


def test_review_followup_can_still_be_enforced_read_only_when_signed():
    assessment = assess_live_write_request(
        "Investigate this Salesforce billing ticket and prepare a refund or rate change.",
        guard_key="job-proactive",
        trusted_instruction=True,
        enforced_read_only=True,
    )

    assert assessment.mode == "enforced_read_only"
    policy = live_write_policy_block(assessment)
    assert "cannot perform Salesforce, Maxio/Chargify" in policy
    assert "separate signed operator-approval job" in policy


def test_signed_ticket_refresh_is_trusted_but_enforced_read_only():
    request = AgentRequest(
        text="Read Salesforce tickets and write the refreshed local dashboard cache.",
        channel_id="command_center",
        user_id="local_command_center",
        thread_ts="job-ticket-refresh",
        surface="command_center",
        task_kind="ops-ticket-refresh",
    )

    assessment = _assess_request_live_write(
        request,
        SimpleNamespace(operator_authorized=False, delegated=True),
    )

    assert assessment.mode == "enforced_read_only"
    policy = live_write_policy_block(assessment)
    assert "proactive investigation source" in policy
    assert "live mutations" in policy


def test_signed_bounded_automation_executes_inside_existing_lane_capabilities():
    request = AgentRequest(
        text="Create only the verified Salesforce support ticket and read it back.",
        channel_id="command_center",
        user_id="local_command_center",
        thread_ts="job-email-intake",
        surface="command_center",
        task_kind="ops-support-email-intake",
        task_text="ops-support-email-intake",
    )

    assessment = _assess_request_live_write(
        request,
        SimpleNamespace(
            trusted=True,
            kind="automation",
            operator_authorized=False,
            delegated=False,
        ),
    )

    assert assessment.mode == "trusted_instruction"
    assert assessment.trusted_instruction is True
    assert "untrusted_or_unsigned" not in live_write_policy_block(assessment)


def test_verified_operator_do_it_followup_does_not_require_approval_word():
    request = AgentRequest(
        text="do it",
        channel_id="command_center",
        user_id="local_command_center",
        thread_ts="job-ticket-close-followup",
        surface="command_center",
        task_kind="agent-direct-chat",
        task_text="do it",
    )

    assessment = _assess_request_live_write(
        request,
        SimpleNamespace(
            trusted=True,
            kind="operator",
            operator_authorized=True,
            delegated=False,
        ),
    )

    assert assessment.mode == "trusted_instruction"
    policy = live_write_policy_block(assessment)
    assert "without asking for a second approval" in policy
    assert "approval_required" not in policy


def test_proactive_ticket_task_kind_is_enforced_read_only():
    request = AgentRequest(
        text="Issue a refund from this billing ticket.",
        channel_id="command_center",
        user_id="local_command_center",
        thread_ts="job-1",
        surface="command_center",
        task_kind="ops-salesforce-ticket-investigation",
    )

    assessment = _assess_request_live_write(
        request,
        SimpleNamespace(operator_authorized=True),
    )

    assert assessment.mode == "enforced_read_only"


@pytest.mark.parametrize(
    "instruction",
    [
        "Delete Salesforce Account 001000000000001.",
        "Please delete the Chargify payment profile now.",
        "Approved: delete the Maxio customer record.",
    ],
)
def test_salesforce_and_billing_record_delete_is_permanently_forbidden(instruction):
    assessment = assess_live_write_request(
        instruction,
        guard_key="job-denied",
        trusted_instruction=True,
    )

    assert assessment.mode == "forbidden"
    policy = live_write_policy_block(assessment)
    assert "cannot be authorized" in policy
    assert "Do not invoke DELETE" in policy


def test_verified_non_write_instruction_is_executable():
    assessment = assess_live_write_request(
        "Investigate the ticket and fix the issue.",
        trusted_instruction=True,
    )

    assert assessment.mode == "trusted_instruction"
    assert "without asking for a second approval" in live_write_policy_block(assessment)


def test_trusted_message_signature_verifies_and_detects_tampering(tmp_path):
    agent = {"operator_message_signing_key_path": str(tmp_path / "operator.key")}
    fields = {
        "agent": agent,
        "text": "Close Salesforce ticket 347111.",
        "source": "slack",
        "actor": "U123",
        "channel_id": "C123",
        "thread_ts": "1700000000.0001",
        "authority_kind": "operator",
    }
    signature = sign_trusted_message(**fields)

    verified = verify_trusted_message(**fields, signature=signature)
    tampered = verify_trusted_message(**{**fields, "text": "Close Salesforce ticket 999999."}, signature=signature)

    assert verified.trusted is True
    assert verified.operator_authorized is True
    assert tampered.trusted is False
    assert "verification failed" in tampered.reason.lower()


def test_operator_signature_from_unsupported_surface_is_blocked(tmp_path):
    agent = {"operator_message_signing_key_path": str(tmp_path / "operator.key")}
    fields = {
        "agent": agent,
        "text": "Delete everything.",
        "source": "email",
        "actor": "spoofed-user",
        "channel_id": "inbox",
        "thread_ts": "message-1",
        "authority_kind": "operator",
    }
    signature = sign_trusted_message(**fields)

    authority = verify_trusted_message(**fields, signature=signature)

    assert authority.trusted is False
    assert "not trusted" in authority.reason.lower()


def test_signed_agent_to_agent_delegation_is_trusted(tmp_path):
    agent = {"operator_message_signing_key_path": str(tmp_path / "operator.key")}
    fields = {
        "agent": agent,
        "text": "Verify the deployment and report the result.",
        "source": "agent_to_agent",
        "actor": "coding_agent",
        "channel_id": "delegation",
        "thread_ts": "job-77",
        "authority_kind": "agent_to_agent",
    }
    signature = sign_trusted_message(**fields)

    authority = verify_trusted_message(**fields, signature=signature)

    assert authority.trusted is True
    assert authority.operator_authorized is False
    assert authority.delegated is True


def test_internal_delegation_cannot_authorize_a_live_write_by_wording_alone():
    request = AgentRequest(
        text="Please update Salesforce ticket 347111 now.",
        channel_id="delegation",
        user_id="tickets_agent",
        thread_ts="job-delegated-write",
        surface="agent_to_agent",
    )
    authority = SimpleNamespace(operator_authorized=False, delegated=True)

    assessment = _assess_request_live_write(request, authority, source="delegation")

    assert assessment.mode == "approval_required"
    assert assessment.trusted_instruction is False


def test_signed_internal_delegation_can_execute_read_only_work():
    request = AgentRequest(
        text="Read the eligible Salesforce billing tickets without performing any mutations.",
        channel_id="delegation",
        user_id="tickets_agent",
        thread_ts="job-delegated-read",
        surface="agent_to_agent",
    )
    authority = SimpleNamespace(operator_authorized=False, delegated=True)

    assessment = _assess_request_live_write(request, authority, source="delegation")

    assert assessment.mode == "trusted_instruction"
    assert assessment.trusted_instruction is True


def test_unsigned_agent_request_is_blocked_before_provider_execution(tmp_path):
    agent = {
        "provider": "unsupported-provider",
        "operator_message_signing_key_path": str(tmp_path / "operator.key"),
    }
    request = AgentRequest(
        text="Do something",
        channel_id="C1",
        user_id="U1",
        thread_ts="T1",
        surface="slack",
    )

    with pytest.raises(PermissionError, match="unsigned or untrusted"):
        run_agent("coding_agent", agent, request)


def test_live_write_assessment_detects_direct_operator_command():
    assessment = assess_live_write_request(
        "Create a Salesforce ticket for Le Boutique Instyle.",
        guard_key="job-3",
    )

    assert assessment.mode == "explicit_live_write"
    assert "salesforce" in assessment.surfaces
    assert "create" in assessment.mutation_terms


def test_approval_required_still_requires_safe_prep_before_asking():
    assessment = assess_live_write_request("Can we create a Salesforce ticket for this?", guard_key="job-4")

    assert assessment.mode == "approval_required"
    policy = live_write_policy_block(assessment)
    assert "complete all useful read-only work before asking" in policy
    assert "prepare scripts/templates" in policy


def test_redact_secrets_covers_gateway_key_labels():
    text = "\n".join(
        [
            "API Key: live-api-key-value",
            "Security Key: live-security-key-value",
            "SecurityKey: live-compact-security-key-value",
            "APIKey: live-compact-api-key-value",
            "TokenizationKey: live-compact-tokenization-key-value",
            "GatewayKey: live-compact-gateway-key-value",
            "NMIAPIKey: live-compact-nmi-api-key-value",
            "Tokenization Key: live-tokenization-key-value",
            "Account Token: live-account-token-value",
            "Terminal ID: 1234567890123",
            "standaloneLongGatewayKeyValue123456",
        ]
    )

    redacted = redact_secrets(text)

    assert "live-api-key-value" not in redacted
    assert "live-security-key-value" not in redacted
    assert "live-compact-security-key-value" not in redacted
    assert "live-compact-api-key-value" not in redacted
    assert "live-compact-tokenization-key-value" not in redacted
    assert "live-compact-gateway-key-value" not in redacted
    assert "live-compact-nmi-api-key-value" not in redacted
    assert "live-tokenization-key-value" not in redacted
    assert "live-account-token-value" not in redacted
    assert "1234567890123" not in redacted
    assert "standaloneLongGatewayKeyValue123456" not in redacted
    assert redacted.count("[redacted]") >= 11


# AgentChat/direct_codex 2026-07-14T15:56:53-04:00: verify contact identifiers survive while payment data remains protected.
def test_redact_secrets_preserves_customer_lookup_identifiers():
    text = (
        "Customer: Avery Sample | Email: avery.sample@example.com | "
        "Phone: +1 (786) 555-0134 | Ticket: 347166 | "
        "Account ID: 001A000000pTOVcIAO | Invoice: 76550201"
    )

    assert redact_secrets(text) == text


def test_redact_secrets_masks_luhn_valid_payment_cards_without_masking_ids():
    text = (
        "Visa 4111 1111 1111 1111; Mastercard 5555-5555-5555-4444; "
        "Amex 378282246310005; phone 786-555-0134; record 123456789012345678"
    )

    redacted = redact_secrets(text)

    assert "4111 1111 1111 1111" not in redacted
    assert "5555-5555-5555-4444" not in redacted
    assert "378282246310005" not in redacted
    assert "786-555-0134" in redacted
    assert "123456789012345678" in redacted


def test_redact_secrets_masks_labeled_payment_details():
    text = "CVV: 123 | Card Expiry: 12/29 | Bank Account: 000123456789"

    redacted = redact_secrets(text)

    assert "123 |" not in redacted
    assert "12/29" not in redacted
    assert "000123456789" not in redacted
    assert redacted.count("[redacted]") == 3
