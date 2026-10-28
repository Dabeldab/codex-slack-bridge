from pathlib import Path

import pytest

from codex_slack_bridge.github_agent_relay import (
    CommandCenterRelay,
    RelayConfigurationError,
    RelayRequestError,
    RelaySettings,
    _cloud_run_iap_upstream,
    _safe_upstream_path,
    _validated_private_upstream_url,
    normalize_task_envelope,
    project_job,
)


def test_relay_envelope_normalizes_named_agents_and_stable_idempotency():
    payload = normalize_task_envelope(
        {
            "version": 1,
            "task_id": "chatgpt-20260917-001",
            "agent": "Rory",
            "title": "Inspect runtime",
            "instruction": "Read health and report only.",
            "created_at": "2026-09-17T17:00:00Z",
        }
    )
    assert payload["agent"] == "direct_codex"
    assert payload["idempotency_key"] == "github-relay:chatgpt-20260917-001"
    assert payload["reasoning_provider"] == "codex_cli"


@pytest.mark.parametrize("agent", ["rory", "taylor", "alex", "jamie", "thor"])
def test_relay_supports_all_operator_visible_lanes(agent):
    payload = normalize_task_envelope(
        {
            "task_id": f"relay-{agent}-20260917",
            "agent": agent,
            "instruction": "Report current status.",
        }
    )
    assert payload["agent"]


def test_relay_rejects_unknown_agent_and_unbounded_instruction():
    with pytest.raises(RelayRequestError, match="agent must be"):
        normalize_task_envelope(
            {
                "task_id": "relay-unknown-20260917",
                "agent": "raw_codex",
                "instruction": "status",
            }
        )
    with pytest.raises(RelayRequestError, match="12000"):
        normalize_task_envelope(
            {
                "task_id": "relay-long-20260917",
                "agent": "rory",
                "instruction": "x" * 12001,
            }
        )


def test_private_upstream_requires_literal_rfc1918_http_origin():
    assert _validated_private_upstream_url("http://10.42.0.2:17866") == "http://10.42.0.2:17866"
    for value in (
        "https://10.42.0.2:17866",
        "http://127.0.0.1:17866",
        "http://example.com:17866",
        "http://8.8.8.8:17866",
        "http://10.42.0.2:17866/path",
    ):
        with pytest.raises(RelayConfigurationError):
            _validated_private_upstream_url(value)


def test_cloud_run_iap_upstream_requires_exact_https_run_origin():
    assert _cloud_run_iap_upstream("https://nova-command-center-shadow-3qcpmfwo7a-uc.a.run.app") == "https://nova-command-center-shadow-3qcpmfwo7a-uc.a.run.app"
    for value in (
        "http://nova-command-center-shadow-3qcpmfwo7a-uc.a.run.app",
        "https://example.com",
        "https://nova-command-center-shadow-3qcpmfwo7a-uc.a.run.app/path",
    ):
        with pytest.raises(RelayConfigurationError):
            _cloud_run_iap_upstream(value)


def test_iap_mode_requires_resource_audience_and_token_file(monkeypatch, tmp_path):
    token_path = tmp_path / "relay.token"
    token_path.write_text("x" * 32, encoding="utf-8")
    monkeypatch.setenv("COMMAND_CENTER_UPSTREAM_AUTH_MODE", "cloud_run_iap")
    monkeypatch.setenv("COMMAND_CENTER_UPSTREAM_URL", "https://nova-command-center-shadow-3qcpmfwo7a-uc.a.run.app")
    monkeypatch.setenv("COMMAND_CENTER_IAP_AUDIENCE", "projects/63366976264/iap_web/cloud_run-us-central1/services/nova-command-center-shadow")
    monkeypatch.setenv("COMMAND_CENTER_UPSTREAM_TOKEN_PATH", str(token_path))
    settings = RelaySettings.from_environment()
    assert settings.upstream_auth_mode == "cloud_run_iap"


def test_iap_jwt_mode_uses_cloud_run_origin_without_oidc_client(monkeypatch, tmp_path):
    token_path = tmp_path / "relay.token"
    token_path.write_text("x" * 32, encoding="utf-8")
    monkeypatch.setenv("COMMAND_CENTER_UPSTREAM_AUTH_MODE", "cloud_run_iap_jwt")
    monkeypatch.setenv("COMMAND_CENTER_UPSTREAM_URL", "https://nova-command-center-shadow-3qcpmfwo7a-uc.a.run.app")
    monkeypatch.delenv("COMMAND_CENTER_IAP_AUDIENCE", raising=False)
    monkeypatch.setenv("COMMAND_CENTER_UPSTREAM_TOKEN_PATH", str(token_path))
    settings = RelaySettings.from_environment()
    assert settings.upstream_auth_mode == "cloud_run_iap_jwt"


def test_relay_upstream_path_is_allowlisted_not_generic_proxy():
    assert _safe_upstream_path("/health") == "/health"
    assert _safe_upstream_path("/agent-chat/send") == "/agent-chat/send"
    assert _safe_upstream_path("/jobs?limit=200") == "/jobs?limit=200"
    with pytest.raises(RelayRequestError):
        _safe_upstream_path("/ops/email-watch/send-reply")
    with pytest.raises(RelayRequestError):
        _safe_upstream_path("/jobs?limit=10000")


@pytest.mark.parametrize(
    ("provider_field", "expected"),
    [
        ({}, "codex_cli"),
        ({"reasoning_provider": "codex_cli"}, "codex_cli"),
        ({"reasoning_provider": "chatgpt_relay"}, "chatgpt_relay"),
        ({"reasoningProvider": "chatgpt_relay"}, "chatgpt_relay"),
    ],
)
def test_relay_defaults_to_codex_and_allows_explicit_chatgpt(tmp_path, monkeypatch, provider_field, expected):
    token_path = tmp_path / "relay.token"
    token_path.write_text("x" * 32, encoding="utf-8")
    relay = CommandCenterRelay(RelaySettings("http://10.42.0.2:17866", token_path))
    captured = {}

    def request(_method, _path, body=None):
        captured["body"] = body
        return {"job_id": "job-123456"}

    monkeypatch.setattr(relay, "_request", request)
    response = relay.submit({
        "task_id": "relay-provider-20261013", "agent": "alex",
        "instruction": "Read-only backend health", **provider_field,
    })
    assert response["accepted"] is True
    assert captured["body"]["reasoningProvider"] == expected
    assert response["reasoning_provider"] == expected


@pytest.mark.parametrize("invalid", ["auto", "codex_cli_direct", "chatgpt_work_relay", "", 123, None, {}])
def test_relay_rejects_unapproved_reasoning_backends(invalid):
    with pytest.raises(RelayRequestError, match="reasoning_provider"):
        normalize_task_envelope({
            "task_id": "relay-provider-bad-20261013", "agent": "alex",
            "instruction": "health", "reasoning_provider": invalid,
        })


def test_provider_unready_error_contains_only_allowlisted_diagnostics(tmp_path, monkeypatch):
    from codex_slack_bridge.github_agent_relay import UpstreamError

    token_path = tmp_path / "relay.token"
    token_path.write_text("x" * 32, encoding="utf-8")
    relay = CommandCenterRelay(RelaySettings("http://10.42.0.2:17866", token_path))
    monkeypatch.setattr(relay, "_request", lambda *_args, **_kwargs: {
        "accepted": False, "message": "agent_provider_unready",
        "providerReadiness": {"provider": "codex_cli", "status": "not_authenticated"},
    })
    with pytest.raises(UpstreamError, match="codex_cli/not_authenticated"):
        relay.submit({"task_id": "relay-provider-unready-20261013", "agent": "alex", "instruction": "status"})


def test_job_projection_keeps_result_and_terminal_state_but_not_payload():
    projected = project_job(
        {
            "id": "job-123456",
            "bridgeJobId": 42,
            "agentName": "direct_codex",
            "sourceType": "agent-direct-chat",
            "status": "completed",
            "result": "COMPLETED\nHealthy.",
            "payload": {"instruction": "secret-looking operator prompt"},
        }
    )
    assert projected["terminal"] is True
    assert projected["result"] == "COMPLETED\nHealthy."
    assert "payload" not in projected
