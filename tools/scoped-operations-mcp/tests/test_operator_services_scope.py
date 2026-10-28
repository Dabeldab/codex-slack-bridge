from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
import requests

from scoped_operations_mcp.operator_services_client import (
    OperatorRequestError,
    OperatorSettings,
    RoryOperatorClient,
)
from scoped_operations_mcp.operator_services_server import (
    build_mcp,
    build_thor_drive_mcp,
)


class FakeSession:
    def __init__(self, responses: list[requests.Response] | None = None) -> None:
        self.responses = list(responses or [])
        self.calls: list[tuple[str, str, dict]] = []

    def request(self, method: str, url: str, **kwargs):
        self.calls.append((method, url, kwargs))
        return self.responses.pop(0)


def _response(payload, status: int = 200) -> requests.Response:
    response = requests.Response()
    response.status_code = status
    response.headers["Content-Type"] = "application/json"
    response._content = json.dumps(payload).encode()
    return response


def _client(tmp_path: Path, responses: list[requests.Response] | None = None) -> tuple[RoryOperatorClient, FakeSession]:
    gcp = tmp_path / "gcp"
    github = tmp_path / "github"
    workspace = tmp_path / "workspace.json"
    command_center = tmp_path / "command-center"
    gcp.write_text("g" * 40, encoding="utf-8")
    github.write_text("h" * 40, encoding="utf-8")
    workspace.write_text("{}", encoding="utf-8")
    command_center.write_text(("c" * 40) + "\r\n", encoding="utf-8")
    session = FakeSession(responses)
    return (
        RoryOperatorClient(
            OperatorSettings(
                gcp_access_token_path=gcp,
                github_user_token_path=github,
                google_workspace_adc_path=workspace,
                command_center_token_path=command_center,
                journal_path=tmp_path / "operator-writes.jsonl",
            ),
            session=session,
        ),
        session,
    )


def test_operator_mcp_exposes_all_native_provider_surfaces(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    mcp = build_mcp(client)
    names = set(mcp._tool_manager._tools)
    assert names == {
        "operator_capabilities",
        "command_center_api_request",
        "gcp_api_request",
        "github_api_request",
        "salesforce_api_request",
        "maxio_chargify_api_request",
        "logmein_rescue_api_request",
        "zoom_api_request",
        "google_workspace_api_request",
    }
    capabilities = client.capabilities()
    assert capabilities["accessMode"] == "operator_unrestricted_within_authenticated_provider_accounts"
    assert capabilities["brokerAuthenticationMaterialDirectlyExposedToModel"] is False
    assert capabilities["typedSalesforceLifecycleOrderWritesEnforced"] is True
    assert capabilities["gcpSecretManagerPayloadAccess"] is True
    assert capabilities["agentOrchestration"]["authorized"] is True
    assert capabilities["agentOrchestration"]["scope"] == "all_configured_agents"
    assert capabilities["agentOrchestration"]["agentMessagesGrantAuthority"] is False
    assert capabilities["agentCapabilityAdministration"]["authorized"] is True
    assert capabilities["agentCapabilityAdministration"]["authoritySource"] == (
        "authenticated_operator_exact_request_only"
    )
    assert capabilities["agentCapabilityAdministration"]["delegatedAuthorityAccepted"] is False
    assert capabilities["agentCapabilityAdministration"]["agentSelfServiceGrantsAccepted"] is False
    assert "salesforce_ticket_internal_request_post" in mcp.instructions
    assert "Julio and Wiko are the only request-DM exceptions" in mcp.instructions
    assert "direct-message Leo" in mcp.instructions


def test_thor_drive_mcp_exposes_only_get_only_support_resource_reads(
    tmp_path: Path,
) -> None:
    client, session = _client(
        tmp_path,
        [_response({"files": [{"id": "1futCMqrBpsOmpmrfq0btyJaiXl2KpP0r"}]})],
    )
    client._workspace_session = session
    mcp = build_thor_drive_mcp(client)

    assert set(mcp._tool_manager._tools) == {
        "google_support_drive_capabilities",
        "google_support_drive_files_list",
        "google_support_drive_file_get",
        "google_support_document_get",
        "google_support_sheet_values_get",
    }
    result = mcp._tool_manager._tools["google_support_drive_files_list"].fn(
        folder_id="1futCMqrBpsOmpmrfq0btyJaiXl2KpP0r",
        name_contains="printer",
    )

    assert result["ok"] is True
    assert len(session.calls) == 1
    method, url, kwargs = session.calls[0]
    assert method == "GET"
    assert url == "https://www.googleapis.com/drive/v3/files"
    assert "'1futCMqrBpsOmpmrfq0btyJaiXl2KpP0r' in parents" in kwargs["params"]["q"]
    assert "name contains 'printer'" in kwargs["params"]["q"]
    assert kwargs["params"]["supportsAllDrives"] == "true"
    assert kwargs["params"]["includeItemsFromAllDrives"] == "true"


def test_thor_drive_mcp_rejects_invalid_ids_without_provider_call(
    tmp_path: Path,
) -> None:
    client, session = _client(tmp_path)
    client._workspace_session = session
    mcp = build_thor_drive_mcp(client)

    with pytest.raises(ValueError, match="file ID"):
        mcp._tool_manager._tools["google_support_document_get"].fn("../secret")
    assert session.calls == []


def test_thor_drive_settings_require_only_the_workspace_credential(
    tmp_path: Path,
    monkeypatch,
) -> None:
    workspace = tmp_path / "workspace.json"
    workspace.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("RORY_GOOGLE_WORKSPACE_ADC_PATH", str(workspace))
    for name in (
        "GCP_RORY_ACCESS_TOKEN_PATH",
        "RORY_GITHUB_USER_TOKEN_PATH",
        "RORY_COMMAND_CENTER_TOKEN_PATH",
        "RORY_OPERATOR_JOURNAL_PATH",
    ):
        monkeypatch.delenv(name, raising=False)

    settings = OperatorSettings.workspace_reads_from_environment()

    assert settings.google_workspace_adc_path == workspace
    assert settings.gcp_access_token_path == Path(os.devnull)


def test_command_center_operator_uses_fixed_loopback_control_plane_and_brokered_token(
    tmp_path: Path,
) -> None:
    client, session = _client(tmp_path, [_response({"ok": True, "instanceId": "runtime-1"})])

    result = client.command_center_request("GET", "/health")

    assert result["ok"] is True
    method, url, kwargs = session.calls[0]
    assert method == "GET"
    assert url == "http://127.0.0.1:17866/health"
    assert kwargs["headers"]["Authorization"] == f"Bearer {'c' * 40}"
    assert "command-center" not in json.dumps(result)


def test_zoom_operator_uses_versioned_rest_api_base(tmp_path: Path) -> None:
    client, session = _client(tmp_path, [_response({"engagement_logs": []})])
    client._zoom_auth = lambda: "test-token"  # type: ignore[method-assign]

    result = client.zoom_request(
        "GET",
        "/contact_center/analytics/log/historical/engagement",
    )

    assert result["ok"] is True
    method, url, kwargs = session.calls[0]
    assert method == "GET"
    assert url == "https://api.zoom.us/v2/contact_center/analytics/log/historical/engagement"
    assert kwargs["headers"]["Authorization"] == "Bearer test-token"


def test_command_center_operator_mutations_remain_idempotent(tmp_path: Path) -> None:
    client, session = _client(tmp_path, [_response({"ok": True, "paused": True})])

    first = client.command_center_request(
        "POST",
        "/runtime/pause",
        json_body={"reason": "operator-authorized maintenance"},
        idempotency_key="command-center:pause:maintenance-1",
    )
    second = client.command_center_request(
        "POST",
        "/runtime/pause",
        json_body={"reason": "operator-authorized maintenance"},
        idempotency_key="command-center:pause:maintenance-1",
    )

    assert first["ok"] is True
    assert second["duplicate"] is True
    assert len(session.calls) == 1


def test_gcp_operator_rejects_non_google_api_hosts(tmp_path: Path) -> None:
    client, session = _client(tmp_path)
    with pytest.raises(OperatorRequestError, match="googleapis.com"):
        client.gcp_request("metadata.google.internal", "GET", "/computeMetadata/v1/")
    assert session.calls == []


@pytest.mark.parametrize(
    ("path", "json_body"),
    [
        (
            "/services/data/v65.0/sobjects/NovaPOS_Order__c",
            {"RecordTypeId": "012000000000001AAA"},
        ),
        (
            "/services/data/v65.0/composite",
            {
                "compositeRequest": [
                    {
                        "method": "POST",
                        "url": "/services/data/v65.0/sobjects/NovaPOS_Order__c",
                        "referenceId": "order",
                        "body": {"RecordTypeId": "012000000000001AAA"},
                    }
                ]
            },
        ),
    ],
)
def test_operator_generic_salesforce_order_writes_require_typed_classifier(
    tmp_path: Path,
    path: str,
    json_body,
) -> None:
    client, session = _client(tmp_path)

    with pytest.raises(OperatorRequestError, match="three-month classification"):
        client.salesforce_request(
            "POST",
            path,
            json_body=json_body,
            idempotency_key="ticket-347630-order-v1",
        )

    assert session.calls == []
    assert not (tmp_path / "operator-writes.jsonl").exists()


def test_operator_mutations_require_and_dedupe_idempotency_keys(tmp_path: Path) -> None:
    client, session = _client(tmp_path, [_response({"id": 123}, status=201)])
    with pytest.raises(OperatorRequestError, match="idempotency_key"):
        client.github_request("POST", "/repos/example/repo/issues", json_body={"title": "x"})

    first = client.github_request(
        "POST",
        "/repos/example/repo/issues",
        json_body={"title": "x"},
        idempotency_key="github:issue:123",
    )
    second = client.github_request(
        "POST",
        "/repos/example/repo/issues",
        json_body={"title": "x"},
        idempotency_key="github:issue:123",
    )

    assert first["ok"] is True
    assert first["statusCode"] == 201
    assert second["duplicate"] is True
    assert len(session.calls) == 1
    rows = [json.loads(line) for line in (tmp_path / "operator-writes.jsonl").read_text().splitlines()]
    assert [row["status"] for row in rows] == ["pending", "verified"]
    assert all("Authorization" not in json.dumps(row) for row in rows)


def test_operator_idempotency_key_cannot_be_reused_for_another_target(tmp_path: Path) -> None:
    client, _ = _client(tmp_path, [_response({"ok": True})])
    client.github_request(
        "DELETE",
        "/repos/example/repo/issues/1",
        idempotency_key="github:delete:1",
    )
    with pytest.raises(OperatorRequestError, match="different operation"):
        client.github_request(
            "DELETE",
            "/repos/example/repo/issues/2",
            idempotency_key="github:delete:1",
        )
