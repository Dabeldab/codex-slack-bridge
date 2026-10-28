from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from codex_slack_bridge import google_drive_tool


def test_auth_command_uses_approved_desktop_client(tmp_path, monkeypatch, capsys):
    client = tmp_path / "desktop-oauth.json"
    client.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(google_drive_tool, "gcloud_binary", lambda: "gcloud.cmd")

    args = google_drive_tool.build_parser().parse_args(
        ["auth-command", "--client-id-file", str(client)]
    )

    assert google_drive_tool.cmd_auth_command(args) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["approved_client"] is True
    assert f"--client-id-file={client.resolve()}" in payload["command"]
    assert "https://www.googleapis.com/auth/drive.readonly" in payload["command"][-1]
    assert "https://www.googleapis.com/auth/documents.readonly" in payload["command"][-1]
    assert "https://www.googleapis.com/auth/spreadsheets.readonly" in payload["command"][-1]


def test_auth_command_rejects_missing_approved_client(tmp_path, monkeypatch):
    monkeypatch.setattr(google_drive_tool, "gcloud_binary", lambda: "gcloud.cmd")
    args = google_drive_tool.build_parser().parse_args(
        ["auth-command", "--client-id-file", str(tmp_path / "missing.json")]
    )

    with pytest.raises(google_drive_tool.DriveToolError, match="was not found"):
        google_drive_tool.cmd_auth_command(args)


def test_access_token_ignores_ambient_service_account_overrides(tmp_path, monkeypatch):
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", "C:/secure/ops-service-account.json")
    monkeypatch.setenv("CLOUDSDK_AUTH_CREDENTIAL_FILE_OVERRIDE", "C:/secure/alternate.json")
    monkeypatch.setenv("CLOUDSDK_AUTH_IMPERSONATE_SERVICE_ACCOUNT", "ops@example.iam.gserviceaccount.com")
    monkeypatch.setenv("CLOUDSDK_CONFIG", "C:/alternate/gcloud")
    local_adc = tmp_path / "gcloud" / "application_default_credentials.json"
    local_adc.parent.mkdir()
    local_adc.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(google_drive_tool, "adc_path", lambda: local_adc)
    captured: dict[str, object] = {}
    request_marker = object()
    credentials = SimpleNamespace(
        valid=False,
        refresh_token="refresh-present",
        token=None,
    )

    def fake_load(path, scopes):
        captured["path"] = path
        captured["scopes"] = scopes
        return credentials

    def fake_refresh(request):
        captured["request"] = request
        credentials.valid = True
        credentials.token = "x" * 40

    credentials.refresh = fake_refresh
    monkeypatch.setattr(
        google_drive_tool.Credentials,
        "from_authorized_user_file",
        fake_load,
    )
    monkeypatch.setattr(google_drive_tool, "Request", lambda: request_marker)

    assert google_drive_tool.access_token() == "x" * 40
    assert captured["path"] == str(local_adc)
    assert captured["scopes"] == google_drive_tool.ADC_SCOPES
    assert captured["request"] is request_marker
