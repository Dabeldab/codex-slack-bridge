from __future__ import annotations

import http.client
import json
import socket
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from threading import Thread
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest

from codex_slack_bridge.command_center_auth import (
    CommandCenterAccess,
    GoogleOAuthClient,
    GoogleOAuthConfig,
    GoogleOAuthConfigurationError,
    read_command_center_bearer,
)
from codex_slack_bridge.command_center_server import BoundedThreadingHTTPServer, make_handler
from codex_slack_bridge.config import load_config


ROOT = Path(__file__).resolve().parents[1]


class FakeRuntime:
    bridge_root = ROOT
    shadow_mode = False

    @staticmethod
    def health():
        return {"ok": True, "service": "nova-ops-command-center"}

    @staticmethod
    def jobs(*, active_only: bool, source_type: str, limit: int):
        return {"ok": True, "jobs": [], "limit": limit}

    @staticmethod
    def submit(payload):
        return {"ok": True, "accepted": True, "payloadType": payload.get("type", "")}


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


@contextmanager
def _running_gateway(
    tmp_path: Path,
    *,
    google_claims: dict | None = None,
    runtime=None,
    trusted_bearer_path: Path | None = None,
):
    port = _free_port()
    origin = f"http://127.0.0.1:{port}"
    token_path = tmp_path / "command-center.token"
    google_oauth = None
    if google_claims is not None:
        google_oauth = GoogleOAuthClient(
            GoogleOAuthConfig(
                client_id="test-client.apps.googleusercontent.com",
                client_secret="test-secret",
                redirect_uri=f"{origin}/auth/google/callback",
                public_origin=origin,
                allowed_emails=frozenset({"owner@example.com"}),
                secure_cookies=True,
            ),
            token_exchange=lambda code: {"id_token": f"verified:{code}"},
            id_token_verifier=lambda _token, _audience: dict(google_claims),
        )
    access = CommandCenterAccess(
        token_path=token_path,
        allowed_origins={origin},
        google_oauth=google_oauth,
        trusted_bearer_path=trusted_bearer_path,
    )
    server = BoundedThreadingHTTPServer(
        ("127.0.0.1", port),
        make_handler(runtime or FakeRuntime(), access),
        max_request_threads=4,
    )
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield port, origin, token_path
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        access.close()


def _request(port: int, method: str, path: str, *, headers=None, body: str | None = None):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        connection.request(method, path, body=body, headers=headers or {})
        response = connection.getresponse()
        payload = response.read()
        return response.status, response.getheaders(), payload
    finally:
        connection.close()


@contextmanager
def _running_failed_health_upstream():
    class FailedHealthHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            body = json.dumps({"ok": False, "service": "private-runtime"}).encode("utf-8")
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, _format: str, *_args) -> None:
            return

    port = _free_port()
    server = BoundedThreadingHTTPServer(
        ("127.0.0.1", port),
        FailedHealthHandler,
        max_request_threads=2,
    )
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield port
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _set_cookies(headers) -> list[str]:
    return [value for name, value in headers if name.casefold() == "set-cookie"]


def _cookie_header(headers) -> str:
    return "; ".join(value.split(";", 1)[0] for value in _set_cookies(headers))


def test_sensitive_api_requires_authentication_and_never_allows_null_origin(tmp_path):
    with _running_gateway(tmp_path) as (port, _origin, _token_path):
        status, headers, _body = _request(port, "GET", "/jobs?limit=1")
        header_map = dict(headers)
        assert status == 401
        assert header_map["Cache-Control"] == "no-store"
        assert "Access-Control-Allow-Origin" not in header_map

        status, headers, _body = _request(
            port,
            "GET",
            "/jobs?limit=1",
            headers={"Origin": "null"},
        )
        assert status == 403
        assert "Access-Control-Allow-Origin" not in dict(headers)


def test_dashboard_session_reads_and_csrf_protects_mutations(tmp_path):
    with _running_gateway(tmp_path) as (port, origin, _token_path):
        status, headers, _body = _request(port, "GET", "/dashboard/")
        assert status == 200
        cookies = [value.split(";", 1)[0] for name, value in headers if name.casefold() == "set-cookie"]
        cookie_header = "; ".join(cookies)
        csrf_cookie = next(value for value in cookies if value.startswith("NovaCommandCenterCsrf="))
        csrf = csrf_cookie.split("=", 1)[1]

        status, headers, body = _request(
            port,
            "GET",
            "/jobs?limit=1",
            headers={"Cookie": cookie_header},
        )
        assert status == 200
        assert dict(headers)["Cache-Control"] == "no-store"
        assert json.loads(body)["ok"] is True

        payload = json.dumps({"type": "test"})
        common = {"Cookie": cookie_header, "Content-Type": "application/json"}
        status, _headers, _body = _request(port, "POST", "/dispatch", headers=common, body=payload)
        assert status == 403

        status, _headers, _body = _request(
            port,
            "POST",
            "/dispatch",
            headers={**common, "Origin": origin},
            body=payload,
        )
        assert status == 403

        status, headers, body = _request(
            port,
            "POST",
            "/dispatch",
            headers={**common, "Origin": origin, "X-Nova-CSRF": csrf},
            body=payload,
        )
        assert status == 202
        assert dict(headers)["Access-Control-Allow-Origin"] == origin
        assert dict(headers)["Access-Control-Allow-Credentials"] == "true"
        assert json.loads(body)["accepted"] is True


def test_internal_bearer_supports_trusted_non_browser_clients(tmp_path):
    with _running_gateway(tmp_path) as (port, _origin, token_path):
        bearer = read_command_center_bearer(token_path)
        headers = {"Authorization": f"Bearer {bearer}", "Content-Type": "application/json"}
        status, _headers, body = _request(
            port,
            "POST",
            "/dispatch",
            headers=headers,
            body=json.dumps({"type": "internal-test"}),
        )
        assert status == 202
        assert json.loads(body)["payloadType"] == "internal-test"


def test_private_proxy_bearer_is_accepted_without_replacing_local_bearer(tmp_path):
    proxy_token_path = tmp_path / "private-proxy.token"
    proxy_token_path.write_text("p" * 64, encoding="utf-8")
    with _running_gateway(
        tmp_path,
        trusted_bearer_path=proxy_token_path,
    ) as (port, _origin, local_token_path):
        assert read_command_center_bearer(local_token_path) != "p" * 64
        status, _headers, body = _request(
            port,
            "POST",
            "/dispatch",
            headers={
                "Authorization": f"Bearer {'p' * 64}",
                "Content-Type": "application/json",
            },
            body=json.dumps({"type": "private-proxy-test"}),
        )
        assert status == 202
        assert json.loads(body)["payloadType"] == "private-proxy-test"


def test_authenticated_shadow_proxies_reads_and_mutations_to_private_runtime(tmp_path):
    upstream_root = tmp_path / "upstream"
    cloud_root = tmp_path / "cloud"
    with _running_gateway(upstream_root) as (upstream_port, _upstream_origin, upstream_token_path):
        class CloudProxyRuntime(FakeRuntime):
            shadow_mode = True

            def __init__(self):
                self.config = SimpleNamespace(
                    defaults={
                        "command_center_upstream_url": f"http://127.0.0.1:{upstream_port}",
                        "command_center_upstream_token_path": str(upstream_token_path),
                    }
                )

        with _running_gateway(cloud_root, runtime=CloudProxyRuntime()) as (port, origin, _token_path):
            status, _headers, body = _request(port, "GET", "/healthz")
            assert status == 200
            assert json.loads(body)["upstream"] is True

            status, headers, _body = _request(port, "GET", "/dashboard/")
            assert status == 200
            cookies = [
                value.split(";", 1)[0]
                for name, value in headers
                if name.casefold() == "set-cookie"
            ]
            cookie_header = "; ".join(cookies)
            csrf = next(
                value.split("=", 1)[1]
                for value in cookies
                if value.startswith("NovaCommandCenterCsrf=")
            )

            status, _headers, body = _request(
                port,
                "GET",
                "/jobs?limit=1",
                headers={"Cookie": cookie_header},
            )
            assert status == 200
            assert json.loads(body)["jobs"] == []

            status, headers, body = _request(
                port,
                "POST",
                "/dispatch",
                headers={
                    "Cookie": cookie_header,
                    "Origin": origin,
                    "Content-Type": "application/json",
                    "X-Nova-CSRF": csrf,
                },
                body=json.dumps({"type": "proxied-browser-test"}),
            )
            assert status == 202
            assert dict(headers)["Access-Control-Allow-Origin"] == origin
            assert json.loads(body)["payloadType"] == "proxied-browser-test"


def test_cloud_gateway_health_fails_when_private_runtime_is_unreachable(tmp_path):
    upstream_root = tmp_path / "upstream"
    with _running_gateway(upstream_root) as (
        upstream_port,
        _upstream_origin,
        upstream_token_path,
    ):
        upstream_token = upstream_token_path.read_text(encoding="utf-8")
    stable_token_path = tmp_path / "stopped-upstream.token"
    stable_token_path.write_text(upstream_token, encoding="utf-8")

    class CloudProxyRuntime(FakeRuntime):
        shadow_mode = True

        def __init__(self):
            self.config = SimpleNamespace(
                defaults={
                    "command_center_upstream_url": (
                        f"http://127.0.0.1:{upstream_port}"
                    ),
                    "command_center_upstream_token_path": str(stable_token_path),
                    "command_center_upstream_timeout_seconds": 5,
                }
            )

    with _running_gateway(
        tmp_path / "cloud",
        runtime=CloudProxyRuntime(),
    ) as (port, _origin, _token_path):
        status, _headers, body = _request(port, "GET", "/healthz")

    assert status == 503
    assert json.loads(body) == {
        "ok": False,
        "service": "nova-ops-command-center",
        "gateway": True,
        "upstream": False,
    }


def test_cloud_gateway_health_normalizes_private_runtime_server_error(tmp_path):
    token_path = tmp_path / "failed-upstream.token"
    token_path.write_text("u" * 64, encoding="utf-8")

    with _running_failed_health_upstream() as upstream_port:
        class CloudProxyRuntime(FakeRuntime):
            shadow_mode = True

            def __init__(self):
                self.config = SimpleNamespace(
                    defaults={
                        "command_center_upstream_url": (
                            f"http://127.0.0.1:{upstream_port}"
                        ),
                        "command_center_upstream_token_path": str(token_path),
                        "command_center_upstream_timeout_seconds": 5,
                    }
                )

        with _running_gateway(
            tmp_path / "cloud",
            runtime=CloudProxyRuntime(),
        ) as (port, _origin, _token_path):
            status, _headers, body = _request(port, "GET", "/healthz")

    assert status == 503
    assert json.loads(body) == {
        "ok": False,
        "service": "nova-ops-command-center",
        "gateway": True,
        "upstream": False,
    }


def test_google_oauth_is_fail_closed_and_uses_one_time_state(tmp_path):
    claims = {
        "iss": "https://accounts.google.com",
        "sub": "google-subject-123",
        "email": "owner@example.com",
        "email_verified": True,
        "name": "Nova Owner",
    }
    with _running_gateway(tmp_path, google_claims=claims) as (port, origin, _token_path):
        status, headers, _body = _request(port, "GET", "/")
        assert status == 303
        assert dict(headers)["Location"] == f"{origin}/auth/google/login"

        status, headers, _body = _request(port, "GET", "/dashboard/")
        assert status == 303
        assert dict(headers)["Location"] == f"{origin}/auth/google/login"
        assert not any(cookie.startswith("NovaCommandCenterSession=") for cookie in _set_cookies(headers))

        status, headers, _body = _request(port, "GET", "/auth/google/login")
        assert status == 302
        authorization_url = dict(headers)["Location"]
        parsed_authorization = urlparse(authorization_url)
        assert parsed_authorization.scheme == "https"
        assert parsed_authorization.hostname == "accounts.google.com"
        params = parse_qs(parsed_authorization.query)
        assert params["scope"] == ["openid email profile"]
        state = params["state"][0]
        state_cookie = next(
            cookie for cookie in _set_cookies(headers) if cookie.startswith("NovaCommandCenterOAuthState=")
        )
        assert "HttpOnly" in state_cookie
        assert "Secure" in state_cookie
        assert "SameSite=Lax" in state_cookie

        callback_cookie = state_cookie.split(";", 1)[0]
        status, headers, _body = _request(
            port,
            "GET",
            f"/auth/google/callback?code=one-time-code&state={state}",
            headers={"Cookie": callback_cookie},
        )
        assert status == 303
        assert dict(headers)["Location"] == "/dashboard/"
        callback_cookies = _set_cookies(headers)
        assert any(cookie.startswith("NovaCommandCenterSession=") for cookie in callback_cookies)
        assert any(cookie.startswith("NovaCommandCenterCsrf=") for cookie in callback_cookies)
        assert all("Secure" in cookie for cookie in callback_cookies)

        authenticated_cookie = _cookie_header(headers)
        csrf_cookie = next(
            cookie for cookie in callback_cookies if cookie.startswith("NovaCommandCenterCsrf=")
        )
        csrf_token = csrf_cookie.split(";", 1)[0].split("=", 1)[1]

        status, _headers, body = _request(
            port,
            "GET",
            "/auth/session",
            headers={"Cookie": authenticated_cookie},
        )
        assert status == 200
        assert json.loads(body)["identity"] == {"mode": "google_session", "email": "owner@example.com"}

        status, headers, _body = _request(
            port,
            "GET",
            "/dashboard/",
            headers={"Cookie": authenticated_cookie},
        )
        assert status == 200
        header_map = dict(headers)
        assert header_map["Strict-Transport-Security"].startswith("max-age=31536000")
        assert "default-src 'self'" in header_map["Content-Security-Policy"]
        assert "script-src 'self'" in header_map["Content-Security-Policy"]
        assert "https://sdk.scdn.co" not in header_map["Content-Security-Policy"]
        assert "connect-src 'self'" in header_map["Content-Security-Policy"]
        assert "frame-src" not in header_map["Content-Security-Policy"]
        assert "https://*" not in header_map["Content-Security-Policy"]
        assert not any(cookie.startswith("NovaCommandCenterSession=") for cookie in _set_cookies(headers))

        status, _headers, _body = _request(
            port,
            "POST",
            "/dispatch",
            headers={
                "Cookie": authenticated_cookie,
                "Origin": origin,
                "Content-Type": "application/json",
            },
            body=json.dumps({"type": "cloud-browser"}),
        )
        assert status == 403
        status, _headers, body = _request(
            port,
            "POST",
            "/dispatch",
            headers={
                "Cookie": authenticated_cookie,
                "Origin": origin,
                "Content-Type": "application/json",
                "X-Nova-CSRF": csrf_token,
            },
            body=json.dumps({"type": "cloud-browser"}),
        )
        assert status == 202
        assert json.loads(body)["payloadType"] == "cloud-browser"

        status, _headers, _body = _request(
            port,
            "GET",
            f"/auth/google/callback?code=replay&state={state}",
            headers={"Cookie": callback_cookie},
        )
        assert status == 400

        status, headers, body = _request(
            port,
            "POST",
            "/auth/logout",
            headers={
                "Cookie": authenticated_cookie,
                "Origin": origin,
                "X-Nova-CSRF": csrf_token,
            },
        )
        assert status == 200
        assert json.loads(body)["signedOut"] is True
        assert all("Max-Age=0" in cookie for cookie in _set_cookies(headers))

        status, _headers, _body = _request(
            port,
            "GET",
            "/jobs?limit=1",
            headers={"Cookie": authenticated_cookie},
        )
        assert status == 401


def test_google_oauth_denies_verified_but_unlisted_email(tmp_path):
    outsider_claims = {
        "iss": "accounts.google.com",
        "sub": "outsider-subject",
        "email": "outsider@example.com",
        "email_verified": True,
    }
    with _running_gateway(tmp_path, google_claims=outsider_claims) as (port, _origin, _token_path):
        status, headers, _body = _request(port, "GET", "/auth/google/login")
        assert status == 302
        state = parse_qs(urlparse(dict(headers)["Location"]).query)["state"][0]
        state_cookie = _cookie_header(headers)

        status, headers, body = _request(
            port,
            "GET",
            f"/auth/google/callback?code=outsider&state={state}",
            headers={"Cookie": state_cookie},
        )
        assert status == 403
        assert b"not authorized" in body
        assert not any(cookie.startswith("NovaCommandCenterSession=") for cookie in _set_cookies(headers))


def test_google_oauth_environment_requires_exact_allowlist_and_https():
    base = {
        "GOOGLE_CLIENT_ID": "client.apps.googleusercontent.com",
        "GOOGLE_CLIENT_SECRET": "secret",
        "GOOGLE_REDIRECT_URI": "https://command.example.com/auth/google/callback",
        "COMMAND_CENTER_PUBLIC_ORIGIN": "https://command.example.com",
    }
    with pytest.raises(GoogleOAuthConfigurationError, match="GOOGLE_OAUTH_ALLOWED_EMAILS"):
        GoogleOAuthConfig.from_environment(base)

    with pytest.raises(GoogleOAuthConfigurationError, match="exact email"):
        GoogleOAuthConfig.from_environment({**base, "GOOGLE_OAUTH_ALLOWED_EMAILS": "*@example.com"})

    with pytest.raises(GoogleOAuthConfigurationError, match="HTTPS"):
        GoogleOAuthConfig.from_environment(
            {
                **base,
                "GOOGLE_REDIRECT_URI": "http://command.example.com/auth/google/callback",
                "COMMAND_CENTER_PUBLIC_ORIGIN": "http://command.example.com",
                "GOOGLE_OAUTH_ALLOWED_EMAILS": "owner@example.com",
            }
        )

    local = GoogleOAuthConfig.from_environment(
        {
            **base,
            "GOOGLE_REDIRECT_URI": "http://localhost:17866/auth/google/callback",
            "COMMAND_CENTER_PUBLIC_ORIGIN": "http://localhost:17866",
            "GOOGLE_OAUTH_ALLOWED_EMAILS": "Owner@Example.com",
        }
    )
    assert local.allowed_emails == frozenset({"owner@example.com"})
    assert local.secure_cookies is False


def test_shadow_mode_blocks_even_authenticated_internal_mutations(tmp_path):
    class ShadowRuntime(FakeRuntime):
        shadow_mode = True

        def __init__(self):
            self.submit_count = 0

        def submit(self, payload):
            self.submit_count += 1
            return super().submit(payload)

    runtime = ShadowRuntime()
    with _running_gateway(tmp_path, runtime=runtime) as (port, _origin, token_path):
        bearer = read_command_center_bearer(token_path)
        status, _headers, body = _request(
            port,
            "POST",
            "/dispatch",
            headers={"Authorization": f"Bearer {bearer}", "Content-Type": "application/json"},
            body=json.dumps({"type": "must-not-run"}),
        )
        assert status == 423
        assert json.loads(body)["accepted"] is False
        assert runtime.submit_count == 0


def test_committed_cloud_config_has_no_agents_or_background_writers():
    config = load_config(ROOT / "config" / "agents.cloud-shadow.yaml")
    assert config.agents == {}
    assert config.channels == {}
    assert config.defaults["runtime_mode"] == "shadow"
    assert config.defaults["command_center_auth_enabled"] is True
    assert config.defaults["command_center_google_auth_enabled"] is True
    for key in (
        "agent_runtime_monitor_enabled",
        "ops_inbox_ledger_enabled",
        "ops_support_email_intake_enabled",
        "ops_email_watch_enabled",
        "ops_schedule_watch_enabled",
        "ops_ticket_refresh_enabled",
        "ops_salesforce_delta_enabled",
        "ops_kpi_dashboard_enabled",
        "ops_propelr_nmi_enabled",
        "ops_singapore_ftp_enabled",
        "ops_weekly_yaron_report_enabled",
        "ops_zoom_chat_monitor_enabled",
        "prospective_enabled",
        "drawing_board_digest_enabled",
    ):
        assert config.defaults[key] is False
