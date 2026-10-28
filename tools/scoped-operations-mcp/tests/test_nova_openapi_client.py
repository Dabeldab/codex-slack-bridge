from __future__ import annotations

import json

import pytest

from scoped_operations_mcp.nova_openapi_client import (
    NovaOpenApiScopeError,
    NovaOpenApiSettings,
    NovaOpenApiUnavailableError,
    ScopedNovaOpenApiClient,
)


class FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload
        self.content = json.dumps(payload).encode("utf-8")

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return self.responses.pop(0)


def _client(responses):
    session = FakeSession(responses)
    client = ScopedNovaOpenApiClient(
        NovaOpenApiSettings(
            base_url="https://openapi.novapointofsale.com",
            username="Demo_Tenant",
            password="not-returned",
        ),
        session=session,
    )
    return client, session


def test_preflight_authenticates_exact_tenant_and_proves_regions_read():
    client, session = _client(
        [
            FakeResponse(200, {"accessToken": "x" * 64, "tokenType": "Bearer", "tenantId": "42"}),
            FakeResponse(200, [{"id": 1, "name": "East"}]),
        ]
    )

    result = client.preflight("Demo_Tenant")

    assert result == {
        "ok": True,
        "companyUsername": "Demo_Tenant",
        "tenantId": "42",
        "regionCount": 1,
        "readVerified": True,
        "accessMode": "typed_read_only",
    }
    assert session.calls[0][1].endswith("/api/auth/login")
    assert session.calls[1][1].endswith("/api/regions")
    assert session.calls[1][2]["headers"]["Authorization"] == "Bearer " + "x" * 64
    assert "not-returned" not in json.dumps(result)


def test_wrong_or_unconfigured_tenant_fails_before_network():
    client, session = _client([])
    with pytest.raises(NovaOpenApiScopeError, match="does not match"):
        client.regions("Different_Tenant")
    assert session.calls == []

    unconfigured = ScopedNovaOpenApiClient(NovaOpenApiSettings())
    with pytest.raises(NovaOpenApiUnavailableError, match="credentials are not configured"):
        unconfigured.regions("Demo_Tenant")


def test_customer_page_is_bounded_to_published_maximum():
    client, session = _client(
        [
            FakeResponse(200, {"accessToken": "y" * 64, "tenantId": "42"}),
            FakeResponse(200, {"items": []}),
        ]
    )

    result = client.customers("Demo_Tenant", page_number=2, page_size=999, search_text="Jasline")

    assert result["ok"] is True
    params = session.calls[1][2]["params"]
    assert params == {"pageNumber": 2, "pageSize": 200, "searchText": "Jasline"}


def test_capabilities_expose_no_write_or_delete_operations():
    client, _session = _client([])
    result = client.capability_status()

    assert result["accessMode"] == "typed_read_only"
    assert result["writeExposed"] is False
    assert result["deleteExposed"] is False
    assert not any(
        marker in operation
        for operation in result["allowedOperations"]
        for marker in ("create", "update", "delete", "adjust", "checkin", "checkout")
    )
