from __future__ import annotations

# AgentChat/direct_codex 2026-07-14T21:01:41-04:00: verify proactive billing-ticket writes fail closed in the broker.

import sys
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace

import pytest

from codex_slack_bridge.secret_broker import (
    BrokerDisabledError,
    EnvironmentSecretProvider,
    GoogleSecretManagerProvider,
    OperationFailedError,
    OperationNotAllowedError,
    OperationRequest,
    ProviderUnavailableError,
    SecretBrokerConfigError,
    SecretLease,
    SecretReference,
    build_secret_broker,
    load_secret_broker_config,
)


def _environment_config(*, enabled: bool = True, operation_enabled: bool = True):
    return {
        "schema_version": 1,
        "enabled": enabled,
        "providers": {
            "local-transition": {
                "type": "environment",
                "enabled": True,
                "transitional": True,
            }
        },
        "operations": {
            "service.perform_action": {
                "enabled": operation_enabled,
                "provider": "local-transition",
                "allowed_agents": ["taylor"],
                "reference": {"environment_variable": "SERVICE_CREDENTIAL"},
                "arguments": {"required": ["record_id"], "optional": ["dry_run"]},
            }
        },
    }


def _google_config(*, provider_enabled: bool = True):
    return {
        "schema_version": 1,
        "enabled": True,
        "providers": {
            "google-primary": {
                "type": "google_secret_manager",
                "enabled": provider_enabled,
                "project_id": "supportkpis",
            }
        },
        "operations": {
            "service.perform_action": {
                "enabled": True,
                "provider": "google-primary",
                "allowed_agents": ["taylor"],
                "reference": {"secret_id": "service-oauth", "version": "7"},
                "arguments": {"required": ["record_id"]},
            }
        },
    }


def _request(operation, request_id, arguments, *, agent_name="taylor", job_id="job-1"):
    return OperationRequest(operation, agent_name, job_id, request_id, arguments)


def test_secret_lease_redacts_string_repr_and_zeroes_on_close():
    lease = SecretLease("never-print-this-value", provider_id="provider-a")

    assert "never-print-this-value" not in repr(lease)
    assert "never-print-this-value" not in str(lease)
    assert "redacted" in str(lease).lower()
    assert lease.use_text(lambda value: value.endswith("value")) is True

    lease.close()
    assert lease.closed is True
    with pytest.raises(Exception, match="closed"):
        lease.use_text(lambda value: value)
    with pytest.raises(TypeError, match="cannot be serialized"):
        lease.__reduce__()


@pytest.mark.parametrize(
    "source_type",
    ["ops-salesforce-ticket-investigation", "agent-handoff-read-only"],
)
def test_broker_denies_automatic_ticket_writes_but_allows_reads(source_type):
    config = _environment_config()
    policy = config["operations"].pop("service.perform_action")
    config["operations"]["maxio.refund"] = policy
    config["operations"]["maxio.read_invoice"] = policy
    broker = build_secret_broker(
        config,
        {
            "maxio.refund": lambda request, credential: {"ok": True},
            "maxio.read_invoice": lambda request, credential: {"ok": True},
        },
        environment={"SERVICE_CREDENTIAL": "credential"},
    )
    write = OperationRequest(
        "maxio.refund",
        "taylor",
        "job-1",
        "request-refund",
        {"record_id": "invoice-1"},
        source_type,
    )
    allowed = OperationRequest(
        "maxio.read_invoice",
        "taylor",
        "job-1",
        "request-read",
        {"record_id": "invoice-1"},
        source_type,
    )

    with pytest.raises(OperationNotAllowedError, match="read-only"):
        broker.invoke(write)
    assert broker.invoke(allowed).data == {"ok": True}


def test_broker_allows_preview_but_denies_generic_post_for_automatic_ticket_source():
    config = _environment_config()
    policy = config["operations"].pop("service.perform_action")
    policy["arguments"]["optional"].append("http_method")
    config["operations"]["maxio.subscription_cancellation.preview"] = policy
    config["operations"]["maxio.api_request"] = policy
    broker = build_secret_broker(
        config,
        {
            "maxio.subscription_cancellation.preview": lambda request, credential: {"ok": True},
            "maxio.api_request": lambda request, credential: {"ok": True},
        },
        environment={"SERVICE_CREDENTIAL": "credential"},
    )
    preview = OperationRequest(
        "maxio.subscription_cancellation.preview",
        "taylor",
        "job-1",
        "request-preview",
        {"record_id": "subscription-1"},
        "ops-salesforce-ticket-investigation",
    )
    post = OperationRequest(
        "maxio.api_request",
        "taylor",
        "job-1",
        "request-post",
        {"record_id": "subscription-1", "http_method": "POST"},
        "ops-salesforce-ticket-investigation",
    )

    assert broker.invoke(preview).data == {"ok": True}
    with pytest.raises(OperationNotAllowedError, match="read-only"):
        broker.invoke(post)


@pytest.mark.parametrize(
    "field",
    ["value", "password", "refresh_token", "api-key", "client_secret", "private_key"],
)
def test_config_rejects_literal_secret_fields_at_any_depth(field):
    config = _environment_config()
    config["operations"]["service.perform_action"]["reference"][field] = "do-not-store"

    with pytest.raises(SecretBrokerConfigError, match="Literal secret field"):
        load_secret_broker_config(config)


@pytest.mark.parametrize("field", ["command", "script", "handler", "module", "callable"])
def test_config_rejects_configured_executable_fields(field):
    config = _environment_config()
    config["operations"]["service.perform_action"][field] = "arbitrary.code"

    with pytest.raises(SecretBrokerConfigError, match="Executable field"):
        load_secret_broker_config(config)


@pytest.mark.parametrize("version", ["latest", "stable", 0, -1, True, "1.0"])
def test_google_provider_requires_a_positive_numeric_version_pin(version):
    config = _google_config()
    config["operations"]["service.perform_action"]["reference"]["version"] = version

    with pytest.raises(SecretBrokerConfigError, match="numeric pin"):
        load_secret_broker_config(config)


@pytest.mark.parametrize(
    "operation", ["secret.get", "get_secret", "credentials.export", "read-secret"]
)
def test_config_rejects_generic_secret_retrieval_operations(operation):
    config = _environment_config()
    config["operations"] = {operation: config["operations"].pop("service.perform_action")}

    with pytest.raises(SecretBrokerConfigError, match="retrieval operations"):
        load_secret_broker_config(config)


@pytest.mark.parametrize(
    ("operation", "credential_name"),
    [
        ("salesforce.delete_record", "SALESFORCE_ACCESS_TOKEN"),
        ("maxio.hard-delete", "MAXIO_API_KEY"),
        ("chargify.purge_customer", "CHARGIFY_API_KEY"),
    ],
)
def test_config_rejects_salesforce_and_billing_delete_operations(operation, credential_name):
    config = _environment_config()
    row = config["operations"].pop("service.perform_action")
    row["reference"]["environment_variable"] = credential_name
    config["operations"] = {operation: row}

    with pytest.raises(SecretBrokerConfigError, match="record deletion operations are forbidden"):
        load_secret_broker_config(config)


@pytest.mark.parametrize(
    "arguments",
    [
        {"record_id": "record-1", "method": "DELETE"},
        {"record_id": "record-1", "operation": "hard_delete"},
        {"record_id": "record-1", "path": "/customers/1/purge.json"},
    ],
)
def test_broker_denies_indirect_billing_delete_before_credential_access(arguments):
    config = _environment_config()
    row = config["operations"].pop("service.perform_action")
    row["reference"]["environment_variable"] = "CHARGIFY_API_KEY"
    row["arguments"]["optional"] = ["method", "operation", "path"]
    config["operations"] = {"chargify.perform_action": row}
    provider_calls = 0

    class FakeProvider:
        provider_id = "local-transition"
        kind = "environment_transitional"
        enabled = True
        initialized = True

        def lease(self, reference):
            nonlocal provider_calls
            provider_calls += 1
            return SecretLease("credential", provider_id=self.provider_id)

    broker = build_secret_broker(
        config,
        {"chargify.perform_action": lambda request, credential: {"ok": True}},
        provider_overrides={"local-transition": FakeProvider()},
    )

    with pytest.raises(OperationNotAllowedError, match="permanently denied"):
        broker.invoke(_request("chargify.perform_action", "request-delete", arguments))
    assert provider_calls == 0


@pytest.mark.parametrize("allowed_agents", [None, [], ["*"], ["taylor", "taylor"]])
def test_config_requires_explicit_valid_allowed_agents(allowed_agents):
    config = _environment_config()
    if allowed_agents is None:
        config["operations"]["service.perform_action"].pop("allowed_agents")
    else:
        config["operations"]["service.perform_action"]["allowed_agents"] = allowed_agents

    with pytest.raises(SecretBrokerConfigError, match="allowed_agents"):
        load_secret_broker_config(config)


def test_disabled_broker_never_reads_provider_or_calls_handler():
    provider_calls = 0
    handler_calls = 0

    class FakeProvider:
        provider_id = "local-transition"
        kind = "environment_transitional"
        enabled = True
        initialized = True

        def lease(self, reference):
            nonlocal provider_calls
            provider_calls += 1
            return SecretLease("credential", provider_id=self.provider_id)

    def handler(request, credential):
        nonlocal handler_calls
        handler_calls += 1
        return {"ok": True}

    broker = build_secret_broker(
        _environment_config(enabled=False),
        {"service.perform_action": handler},
        provider_overrides={"local-transition": FakeProvider()},
    )

    with pytest.raises(BrokerDisabledError):
        broker.invoke(
            _request("service.perform_action", "request-1", {"record_id": "record-1"})
        )

    assert provider_calls == 0
    assert handler_calls == 0
    assert broker.audit_events()[0].outcome == "denied"


def test_wrong_agent_is_denied_before_provider_access():
    provider_calls = 0

    class FakeProvider:
        provider_id = "local-transition"
        kind = "environment_transitional"
        enabled = True
        initialized = True

        def lease(self, reference):
            nonlocal provider_calls
            provider_calls += 1
            return SecretLease("credential", provider_id=self.provider_id)

    broker = build_secret_broker(
        _environment_config(),
        {"service.perform_action": lambda request, credential: {"ok": True}},
        provider_overrides={"local-transition": FakeProvider()},
    )

    with pytest.raises(OperationNotAllowedError, match="Agent is not allowed"):
        broker.invoke(
            _request(
                "service.perform_action",
                "request-wrong-agent",
                {"record_id": "record-1"},
                agent_name="general",
            )
        )

    assert provider_calls == 0
    event = broker.audit_events()[0]
    assert event.agent_name == "general"
    assert event.job_id == "job-1"
    assert event.request_id == "request-wrong-agent"
    assert event.outcome == "denied"


def test_allowlisted_operation_uses_transitional_environment_without_exporting_credential():
    observed = []

    def handler(request, credential):
        authenticated = credential.use_text(lambda value: value == "local-secret-material")
        observed.append((request.arguments["record_id"], authenticated))
        return {"updated": True}

    broker = build_secret_broker(
        _environment_config(),
        {"service.perform_action": handler},
        environment={"SERVICE_CREDENTIAL": "local-secret-material"},
    )
    response = broker.invoke(
        _request("service.perform_action", "request-2", {"record_id": "record-2"})
    )

    assert response.data == {"updated": True}
    assert response.agent_name == "taylor"
    assert response.job_id == "job-1"
    assert response.request_id == "request-2"
    assert observed == [("record-2", True)]
    assert "local-secret-material" not in repr(response)
    assert "SERVICE_CREDENTIAL" not in repr(broker.status())
    assert "local-secret-material" not in repr(broker.audit_events())


def test_unknown_operation_and_arguments_fail_before_credential_access():
    broker = build_secret_broker(
        _environment_config(),
        {"service.perform_action": lambda request, credential: {"ok": True}},
        environment={"SERVICE_CREDENTIAL": "credential"},
    )

    with pytest.raises(OperationNotAllowedError, match="not allowlisted"):
        broker.invoke(_request("service.unknown_action", "request-3", {}))
    with pytest.raises(OperationNotAllowedError, match="Required"):
        broker.invoke(_request("service.perform_action", "request-4", {}))
    with pytest.raises(OperationNotAllowedError, match="argument is not allowlisted"):
        broker.invoke(
            _request(
                "service.perform_action",
                "request-5",
                {"record_id": "record-5", "command": "whoami"},
            )
        )


def test_handler_errors_are_replaced_with_non_sensitive_failure():
    secret = "sensitive-provider-message"

    def handler(request, credential):
        raise RuntimeError(secret)

    broker = build_secret_broker(
        _environment_config(),
        {"service.perform_action": handler},
        environment={"SERVICE_CREDENTIAL": "credential"},
    )

    with pytest.raises(OperationFailedError) as raised:
        broker.invoke(
            _request("service.perform_action", "request-6", {"record_id": "record-6"})
        )

    assert secret not in str(raised.value)
    assert secret not in repr(broker.audit_events())


@pytest.mark.parametrize("return_bytes", [False, True])
def test_handler_cannot_return_the_leased_secret_in_strings_or_bytes(return_bytes):
    def leaking_handler(request, credential):
        raw_value = credential.use_text(lambda value: value)
        returned_value = (
            raw_value.encode("utf-8") if return_bytes else f"prefix-{raw_value}-suffix"
        )
        return {"debug": returned_value}

    broker = build_secret_broker(
        _environment_config(),
        {"service.perform_action": leaking_handler},
        environment={"SERVICE_CREDENTIAL": "sentinel-lease-secret"},
    )

    with pytest.raises(OperationFailedError) as raised:
        broker.invoke(
            _request("service.perform_action", "request-leak", {"record_id": "record-leak"})
        )

    assert "sentinel-lease-secret" not in str(raised.value)
    assert broker.audit_events()[0].outcome == "failed"
    assert "sentinel-lease-secret" not in repr(broker.audit_events())


@pytest.mark.parametrize(
    "response_data",
    [
        {"payload": "x" * (256 * 1024 + 1)},
        {"unsupported": object()},
        {"not_finite": float("inf")},
    ],
)
def test_handler_response_is_type_and_size_bounded(response_data):
    broker = build_secret_broker(
        _environment_config(),
        {"service.perform_action": lambda request, credential: response_data},
        environment={"SERVICE_CREDENTIAL": "credential"},
    )

    with pytest.raises(OperationFailedError, match="Brokered operation failed"):
        broker.invoke(
            _request("service.perform_action", "request-bounds", {"record_id": "record-bounds"})
        )


def test_google_provider_is_lazy_and_verifies_crc32c_without_cloud_call(monkeypatch):
    requested_names = []
    factory_calls = 0
    crc_calls = []
    monkeypatch.delitem(sys.modules, "google_crc32c", raising=False)

    class FakeClient:
        def access_secret_version(self, *, request):
            requested_names.append(request["name"])
            return SimpleNamespace(
                payload=SimpleNamespace(data=b"cloud-secret-material", data_crc32c=4242)
            )

    def client_factory():
        nonlocal factory_calls
        factory_calls += 1
        return FakeClient()

    def handler(request, credential):
        return {"authenticated": credential.use_text(lambda value: value.startswith("cloud-"))}

    broker = build_secret_broker(
        _google_config(),
        {"service.perform_action": handler},
        google_client_factories={"google-primary": client_factory},
    )

    assert factory_calls == 0
    assert broker.status().providers[0].initialized is False
    assert "google_crc32c" not in sys.modules
    monkeypatch.setitem(
        sys.modules,
        "google_crc32c",
        SimpleNamespace(value=lambda payload: crc_calls.append(payload) or 4242),
    )
    response = broker.invoke(
        _request("service.perform_action", "request-7", {"record_id": "record-7"})
    )

    assert response.data == {"authenticated": True}
    assert factory_calls == 1
    assert crc_calls == [b"cloud-secret-material"]
    assert requested_names == ["projects/supportkpis/secrets/service-oauth/versions/7"]
    assert broker.status().providers[0].initialized is True


def test_google_provider_fails_closed_on_crc32c_mismatch(monkeypatch):
    handler_calls = 0

    class FakeClient:
        def access_secret_version(self, *, request):
            return SimpleNamespace(payload=SimpleNamespace(data=b"credential", data_crc32c=10))

    monkeypatch.setitem(sys.modules, "google_crc32c", SimpleNamespace(value=lambda payload: 11))

    def handler(request, credential):
        nonlocal handler_calls
        handler_calls += 1
        return {"ok": True}

    broker = build_secret_broker(
        _google_config(),
        {"service.perform_action": handler},
        google_client_factories={"google-primary": FakeClient},
    )

    with pytest.raises(ProviderUnavailableError, match="unavailable"):
        broker.invoke(
            _request("service.perform_action", "request-crc", {"record_id": "record-crc"})
        )

    assert handler_calls == 0
    assert broker.audit_events()[0].outcome == "provider_unavailable"


def test_disabled_google_provider_does_not_initialize_client():
    factory_calls = 0

    def client_factory():
        nonlocal factory_calls
        factory_calls += 1
        raise AssertionError("must stay lazy")

    broker = build_secret_broker(
        _google_config(provider_enabled=False),
        {"service.perform_action": lambda request, credential: {"ok": True}},
        google_client_factories={"google-primary": client_factory},
    )

    with pytest.raises(ProviderUnavailableError, match="unavailable"):
        broker.invoke(
            _request("service.perform_action", "request-8", {"record_id": "record-8"})
        )
    assert factory_calls == 0


def test_status_and_audit_are_metadata_only_even_when_arguments_contain_sensitive_text():
    sensitive = "customer-secret-in-request"
    sink_events = []
    config = _environment_config()
    config["operations"]["service.perform_action"]["arguments"]["optional"].append("note")
    broker = build_secret_broker(
        config,
        {"service.perform_action": lambda request, credential: {"ok": True}},
        environment={"SERVICE_CREDENTIAL": "provider-secret"},
        audit_sink=sink_events.append,
    )
    request = _request(
        "service.perform_action",
        "request-9",
        {"record_id": "record-9", "note": sensitive},
    )

    broker.invoke(request)
    serialized = repr(asdict(broker.status())) + repr([asdict(event) for event in sink_events])

    assert sensitive not in repr(request)
    assert sensitive not in serialized
    assert "provider-secret" not in serialized
    assert set(asdict(sink_events[0])) == {
        "occurred_at",
        "agent_name",
        "job_id",
        "request_id",
        "operation",
        "provider_id",
        "outcome",
        "duration_ms",
    }


def test_example_config_is_valid_and_disabled_by_default():
    root = Path(__file__).resolve().parents[1]
    config = load_secret_broker_config(root / "config" / "secret-broker.example.yaml")

    assert config.enabled is False
    assert all(provider.enabled is False for provider in config.providers.values())
    assert all(operation.enabled is False for operation in config.operations.values())


def test_direct_providers_still_enforce_reference_types():
    environment = EnvironmentSecretProvider(
        "local-transition", enabled=True, environment={"SERVICE_CREDENTIAL": "value"}
    )
    google = GoogleSecretManagerProvider("google-primary", "supportkpis", enabled=False)

    with pytest.raises(ProviderUnavailableError, match="invalid"):
        environment.lease(SecretReference("local-transition", "SERVICE_CREDENTIAL", 1))
    with pytest.raises(ProviderUnavailableError, match="disabled"):
        google.lease(SecretReference("google-primary", "service-oauth", 1))
