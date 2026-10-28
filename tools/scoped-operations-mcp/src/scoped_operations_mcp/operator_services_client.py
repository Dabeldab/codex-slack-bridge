from __future__ import annotations

# AgentChat/direct_codex 2026-08-07T14:14:00Z

import base64
import hashlib
import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests
from google.auth.transport.requests import AuthorizedSession
from google.oauth2.credentials import Credentials


ALLOWED_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "POST", "PUT", "PATCH", "DELETE"})
READ_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
IDEMPOTENCY_RE = re.compile(r"^[A-Za-z0-9._:-]{8,240}$")
GCP_HOST_RE = re.compile(r"^[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?\.googleapis\.com$")
MAX_RESPONSE_BYTES = 10 * 1024 * 1024
WORKSPACE_SCOPES = (
    "https://mail.google.com/",
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/spreadsheets",
)
WORKSPACE_BASES = {
    "docs": "https://docs.googleapis.com/v1",
    "drive": "https://www.googleapis.com/drive/v3",
    "drive_upload": "https://www.googleapis.com/upload/drive/v3",
    "gmail": "https://gmail.googleapis.com/gmail/v1",
    "sheets": "https://sheets.googleapis.com/v4",
}


class OperatorRequestError(ValueError):
    """The operator request could not be represented safely."""


@dataclass(frozen=True)
class OperatorSettings:
    gcp_access_token_path: Path
    github_user_token_path: Path
    google_workspace_adc_path: Path
    command_center_token_path: Path
    journal_path: Path

    @classmethod
    def from_environment(cls) -> "OperatorSettings":
        settings = cls(
            gcp_access_token_path=Path(os.getenv("GCP_RORY_ACCESS_TOKEN_PATH", "")).expanduser(),
            github_user_token_path=Path(os.getenv("RORY_GITHUB_USER_TOKEN_PATH", "")).expanduser(),
            google_workspace_adc_path=Path(os.getenv("RORY_GOOGLE_WORKSPACE_ADC_PATH", "")).expanduser(),
            command_center_token_path=Path(
                os.getenv("RORY_COMMAND_CENTER_TOKEN_PATH", "")
            ).expanduser(),
            journal_path=Path(
                os.getenv("RORY_OPERATOR_JOURNAL_PATH", "/var/lib/nova/broker/cloud/operator-writes.jsonl")
            ).expanduser(),
        )
        for label, path in (
            ("Google Cloud token", settings.gcp_access_token_path),
            ("GitHub user token", settings.github_user_token_path),
            ("Google Workspace ADC", settings.google_workspace_adc_path),
            ("Command Center token", settings.command_center_token_path),
        ):
            if not path.is_file():
                raise RuntimeError(f"Rory operator {label} is unavailable")
        return settings

    @classmethod
    def workspace_reads_from_environment(cls) -> "OperatorSettings":
        """Build the least-privilege settings needed by Thor's GET-only broker."""

        workspace_path = Path(
            os.getenv("RORY_GOOGLE_WORKSPACE_ADC_PATH", "")
        ).expanduser()
        if not workspace_path.is_file():
            raise RuntimeError("Thor support Drive Google Workspace ADC is unavailable")
        unused = Path(os.devnull)
        return cls(
            gcp_access_token_path=unused,
            github_user_token_path=unused,
            google_workspace_adc_path=workspace_path,
            command_center_token_path=unused,
            journal_path=unused,
        )


class RoryOperatorClient:
    """Provider-native operator access isolated behind Rory's broker identity.

    This class intentionally does not contain a provider action allowlist. The
    authenticated provider account remains the authority boundary. Network
    targets stay pinned to each provider to prevent the generic request tools
    from becoming an SSRF or arbitrary credential-forwarding surface.
    """

    def __init__(self, settings: OperatorSettings, *, session: requests.Session | None = None) -> None:
        self.settings = settings
        self.session = session or requests.Session()
        self._salesforce_token = ""
        self._salesforce_instance = ""
        self._salesforce_expires_at = 0.0
        self._zoom_token = ""
        self._zoom_expires_at = 0.0
        self._workspace_session: AuthorizedSession | None = None
        self._rescue_session: requests.Session | None = None

    def capabilities(self) -> dict[str, Any]:
        return {
            "ok": True,
            "accessMode": "operator_unrestricted_within_authenticated_provider_accounts",
            "brokerAuthenticationMaterialDirectlyExposedToModel": False,
            "gcpSecretManagerPayloadAccess": True,
            "mutationJournal": True,
            "idempotencyRequiredForMutations": True,
            "typedSalesforceLifecycleOrderWritesEnforced": True,
            "agentOrchestration": {
                "authorized": True,
                "controlPlane": "authenticated_command_center_loopback_api",
                "scope": "all_configured_agents",
                "capabilities": [
                    "health_and_readiness",
                    "job_and_result_inspection",
                    "operator_authorized_dispatch",
                    "tracked_handoffs",
                    "restart_pause_and_resume",
                ],
                "agentMessagesGrantAuthority": False,
            },
            "agentCapabilityAdministration": {
                "authorized": True,
                "authoritySource": "authenticated_operator_exact_request_only",
                "implementationSurfaces": ["github_operator_api", "gcp_project_owner_api"],
                "requires": [
                    "before_state",
                    "least_privilege_contract_change",
                    "policy_and_broker_tests",
                    "immutable_build",
                    "guarded_runtime_promotion",
                    "all_lane_readback",
                ],
                "delegatedAuthorityAccepted": False,
                "agentSelfServiceGrantsAccepted": False,
            },
            "providers": {
                "gcp": "project_owner_api",
                "github": "operator_user_token_api",
                "salesforce": "connected_app_native_api",
                "maxioChargify": "account_native_api",
                "logMeInRescue": "account_native_api",
                "zoom": "account_oauth_native_api",
                "googleWorkspace": ["gmail", "drive", "docs", "sheets"],
                "commandCenter": "all_agent_control_plane",
            },
            "googleWorkspaceScopes": list(WORKSPACE_SCOPES),
        }

    def command_center_request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: Any = None,
        raw_body_base64: str = "",
        content_type: str = "application/json",
        idempotency_key: str = "",
    ) -> dict[str, Any]:
        """Call the authenticated private Command Center control plane."""

        token = _read_secret(
            self.settings.command_center_token_path,
            "Command Center token",
        )
        return self._request(
            "command_center",
            method,
            f"http://127.0.0.1:17866{_path(path)}",
            params=params,
            json_body=json_body,
            raw_body_base64=raw_body_base64,
            content_type=content_type,
            headers={"Authorization": f"Bearer {token}"},
            idempotency_key=idempotency_key,
        )

    def gcp_request(
        self,
        host: str,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: Any = None,
        raw_body_base64: str = "",
        content_type: str = "application/json",
        idempotency_key: str = "",
    ) -> dict[str, Any]:
        clean_host = str(host or "").strip().casefold()
        if not GCP_HOST_RE.fullmatch(clean_host):
            raise OperatorRequestError("host must be an exact googleapis.com API hostname")
        token = _read_secret(self.settings.gcp_access_token_path, "Google Cloud token")
        return self._request(
            "gcp",
            method,
            f"https://{clean_host}{_path(path)}",
            params=params,
            json_body=json_body,
            raw_body_base64=raw_body_base64,
            content_type=content_type,
            headers={"Authorization": f"Bearer {token}"},
            idempotency_key=idempotency_key,
        )

    def github_request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: Any = None,
        raw_body_base64: str = "",
        content_type: str = "application/json",
        idempotency_key: str = "",
    ) -> dict[str, Any]:
        token = _read_secret(self.settings.github_user_token_path, "GitHub user token")
        return self._request(
            "github",
            method,
            f"https://api.github.com{_path(path)}",
            params=params,
            json_body=json_body,
            raw_body_base64=raw_body_base64,
            content_type=content_type,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {token}",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            idempotency_key=idempotency_key,
        )

    def salesforce_request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: Any = None,
        raw_body_base64: str = "",
        content_type: str = "application/json",
        idempotency_key: str = "",
    ) -> dict[str, Any]:
        clean_method = str(method or "GET").strip().upper()
        clean_path = _path(path)
        if _targets_salesforce_lifecycle_order(
            clean_method,
            clean_path,
            json_body,
            raw_body_base64,
        ):
            raise OperatorRequestError(
                "generic NovaPOS Order mutations are unavailable; use "
                "salesforce_location_lifecycle_order_preview/apply so the three-month "
                "classification is enforced"
            )
        token, instance = self._salesforce_auth()
        return self._request(
            "salesforce",
            clean_method,
            f"{instance}{clean_path}",
            params=params,
            json_body=json_body,
            raw_body_base64=raw_body_base64,
            content_type=content_type,
            headers={"Authorization": f"Bearer {token}"},
            idempotency_key=idempotency_key,
        )

    def maxio_request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: Any = None,
        raw_body_base64: str = "",
        content_type: str = "application/json",
        idempotency_key: str = "",
    ) -> dict[str, Any]:
        base = _provider_base(os.getenv("CHARGIFY_BASE_URL") or os.getenv("CHARGIFY_SUBDOMAIN") or "", ("chargify.com", "maxio.com"))
        key = str(os.getenv("CHARGIFY_API_KEY") or os.getenv("MAXIO_API_KEY") or "").strip()
        if not key:
            raise RuntimeError("Maxio/Chargify credentials are unavailable")
        return self._request(
            "maxio_chargify",
            method,
            f"{base}{_path(path)}",
            params=params,
            json_body=json_body,
            raw_body_base64=raw_body_base64,
            content_type=content_type,
            auth=(key, "x"),
            idempotency_key=idempotency_key,
        )

    def rescue_request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: Any = None,
        raw_body_base64: str = "",
        content_type: str = "application/json",
        idempotency_key: str = "",
    ) -> dict[str, Any]:
        session, base = self._rescue_auth()
        return self._request(
            "logmein_rescue",
            method,
            f"{base}{_path(path)}",
            params=params,
            json_body=json_body,
            raw_body_base64=raw_body_base64,
            content_type=content_type,
            session=session,
            idempotency_key=idempotency_key,
        )

    def zoom_request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: Any = None,
        raw_body_base64: str = "",
        content_type: str = "application/json",
        idempotency_key: str = "",
    ) -> dict[str, Any]:
        return self._request(
            "zoom",
            method,
            # Zoom REST endpoints are rooted at /v2.  Omitting the version
            # silently lands on the public web host and returns HTML instead
            # of an authenticated API response.
            f"https://api.zoom.us/v2{_path(path)}",
            params=params,
            json_body=json_body,
            raw_body_base64=raw_body_base64,
            content_type=content_type,
            headers={"Authorization": f"Bearer {self._zoom_auth()}"},
            idempotency_key=idempotency_key,
        )

    def workspace_request(
        self,
        service: str,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: Any = None,
        raw_body_base64: str = "",
        content_type: str = "application/json",
        idempotency_key: str = "",
    ) -> dict[str, Any]:
        clean_service = str(service or "").strip().casefold()
        base = WORKSPACE_BASES.get(clean_service)
        if not base:
            raise OperatorRequestError("service must be gmail, drive, drive_upload, docs, or sheets")
        if self._workspace_session is None:
            credentials = Credentials.from_authorized_user_file(
                str(self.settings.google_workspace_adc_path),
                scopes=list(WORKSPACE_SCOPES),
            )
            self._workspace_session = AuthorizedSession(credentials)
        return self._request(
            f"google_workspace_{clean_service}",
            method,
            f"{base}{_path(path)}",
            params=params,
            json_body=json_body,
            raw_body_base64=raw_body_base64,
            content_type=content_type,
            session=self._workspace_session,
            idempotency_key=idempotency_key,
        )

    def _request(
        self,
        provider: str,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None,
        json_body: Any,
        raw_body_base64: str,
        content_type: str,
        idempotency_key: str,
        headers: dict[str, str] | None = None,
        auth: tuple[str, str] | None = None,
        session: Any | None = None,
    ) -> dict[str, Any]:
        clean_method = str(method or "GET").strip().upper()
        if clean_method not in ALLOWED_METHODS:
            raise OperatorRequestError("method is unsupported")
        if json_body is not None and raw_body_base64:
            raise OperatorRequestError("json_body and raw_body_base64 are mutually exclusive")
        key = str(idempotency_key or "").strip()
        mutating = clean_method not in READ_METHODS
        if mutating and not IDEMPOTENCY_RE.fullmatch(key):
            raise OperatorRequestError("mutations require an idempotency_key of 8-240 safe characters")
        body = _decode_body(raw_body_base64)
        request_hash = _request_hash(params or {}, json_body, raw_body_base64)
        if mutating:
            duplicate = self._verified_operation(key, provider, clean_method, url, request_hash)
            if duplicate:
                return {"ok": True, "duplicate": True, "idempotencyKey": key, "prior": duplicate}
            self._journal("pending", key, provider, clean_method, url, request_hash, {})

        request_headers = {"Accept": "application/json", "User-Agent": "nova-rory-operator/1"}
        request_headers.update(headers or {})
        kwargs: dict[str, Any] = {
            "params": params or {},
            "headers": request_headers,
            "auth": auth,
            "timeout": 60,
        }
        if json_body is not None:
            kwargs["json"] = json_body
        elif body is not None:
            request_headers["Content-Type"] = str(content_type or "application/octet-stream")[:200]
            kwargs["data"] = body
        response = (session or self.session).request(clean_method, url, **kwargs)
        result = _response(response)
        if mutating:
            self._journal(
                "verified" if result["ok"] else "failed",
                key,
                provider,
                clean_method,
                url,
                request_hash,
                {"statusCode": result["statusCode"], "location": result.get("location", "")},
            )
            result["idempotencyKey"] = key
        return result

    def _salesforce_auth(self) -> tuple[str, str]:
        if self._salesforce_token and time.time() < self._salesforce_expires_at - 120:
            return self._salesforce_token, self._salesforce_instance
        client_id = str(os.getenv("SALESFORCE_CLIENT_ID") or "").strip()
        secret = str(os.getenv("SALESFORCE_CLIENT_SECRET") or "").strip()
        login = _provider_base(os.getenv("SALESFORCE_LOGIN_URL") or "", ("salesforce.com",))
        if not client_id or not secret:
            raise RuntimeError("Salesforce credentials are unavailable")
        response = self.session.post(
            f"{login}/services/oauth2/token",
            data={"grant_type": "client_credentials", "client_id": client_id, "client_secret": secret},
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        token = str(payload.get("access_token") or "")
        instance = _provider_base(payload.get("instance_url") or os.getenv("SALESFORCE_INSTANCE_URL") or "", ("salesforce.com",))
        if not token:
            raise RuntimeError("Salesforce did not return an access token")
        self._salesforce_token = token
        self._salesforce_instance = instance
        self._salesforce_expires_at = time.time() + 20 * 60
        return token, instance

    def _zoom_auth(self) -> str:
        if self._zoom_token and time.time() < self._zoom_expires_at - 120:
            return self._zoom_token
        client_id = str(os.getenv("ZOOM_OAUTH_CLIENT_ID") or "").strip()
        client_secret = str(os.getenv("ZOOM_OAUTH_CLIENT_SECRET") or "").strip()
        refresh_token = str(os.getenv("ZOOM_OAUTH_REFRESH_TOKEN") or "").strip()
        if not client_id or not client_secret or not refresh_token:
            raise RuntimeError("Zoom credentials are unavailable")
        response = self.session.post(
            "https://zoom.us/oauth/token",
            params={"grant_type": "refresh_token", "refresh_token": refresh_token},
            auth=(client_id, client_secret),
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        token = str(payload.get("access_token") or "")
        if not token:
            raise RuntimeError("Zoom did not return an access token")
        self._zoom_token = token
        self._zoom_expires_at = time.time() + int(payload.get("expires_in") or 3600)
        return token

    def _rescue_auth(self) -> tuple[requests.Session, str]:
        base = _provider_base(os.getenv("RESCUE_BASE") or "https://secure.logmeinrescue.com/API", ("logmeinrescue.com",))
        if self._rescue_session is not None:
            return self._rescue_session, base
        user = str(os.getenv("RESCUE_USER") or os.getenv("RESCUE_EMAIL") or "").strip()
        password = str(os.getenv("RESCUE_PASS") or os.getenv("RESCUE_PWD") or "").strip()
        if not user or not password:
            raise RuntimeError("LogMeIn Rescue credentials are unavailable")
        session = requests.Session()
        response = session.post(f"{base}/login.aspx", data={"email": user, "pwd": password}, timeout=30)
        response.raise_for_status()
        if not str(response.text or "").strip().upper().startswith("OK"):
            raise RuntimeError("LogMeIn Rescue login failed")
        self._rescue_session = session
        return session, base

    def _verified_operation(
        self,
        key: str,
        provider: str,
        method: str,
        url: str,
        request_hash: str,
    ) -> dict[str, Any] | None:
        path = self.settings.journal_path
        if not path.is_file():
            return None
        for line in reversed(path.read_text(encoding="utf-8").splitlines()[-5000:]):
            try:
                row = json.loads(line)
            except (TypeError, ValueError):
                continue
            if row.get("idempotencyKey") != key:
                continue
            if any(row.get(name) != value for name, value in (
                ("provider", provider), ("method", method), ("target", url), ("requestHash", request_hash)
            )):
                raise OperatorRequestError("idempotency_key was already used for a different operation")
            if row.get("status") == "verified":
                return {"status": "verified", **(row.get("evidence") or {})}
        return None

    def _journal(
        self,
        status: str,
        key: str,
        provider: str,
        method: str,
        url: str,
        request_hash: str,
        evidence: dict[str, Any],
    ) -> None:
        path = self.settings.journal_path
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        record = {
            "time": int(time.time()),
            "status": status,
            "idempotencyKey": key,
            "provider": provider,
            "method": method,
            "target": url,
            "requestHash": request_hash,
            "evidence": evidence,
        }
        descriptor = os.open(path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
        with os.fdopen(descriptor, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
            handle.flush()
            os.fsync(handle.fileno())


def _read_secret(path: Path, label: str) -> str:
    value = path.read_text(encoding="utf-8").strip()
    if not value or len(value) > 64_000:
        raise RuntimeError(f"Rory operator {label} is invalid")
    return value


def _path(value: str) -> str:
    clean = str(value or "").strip()
    if not clean.startswith("/") or "\x00" in clean or any(character in clean for character in "\r\n"):
        raise OperatorRequestError("path must be an absolute provider API path")
    if clean.startswith("//") or "://" in clean:
        raise OperatorRequestError("path cannot override the provider host")
    return clean


def _provider_base(value: str, approved_suffixes: tuple[str, ...]) -> str:
    clean = str(value or "").strip().rstrip("/")
    if clean and "://" not in clean:
        clean = f"https://{clean}"
    parsed = urlparse(clean)
    host = str(parsed.hostname or "").casefold()
    if (
        parsed.scheme != "https"
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or not any(host == suffix or host.endswith(f".{suffix}") for suffix in approved_suffixes)
    ):
        raise OperatorRequestError("provider base URL is outside its authenticated HTTPS boundary")
    return clean


def _decode_body(value: str) -> bytes | None:
    clean = str(value or "").strip()
    if not clean:
        return None
    try:
        payload = base64.b64decode(clean, validate=True)
    except ValueError as exc:
        raise OperatorRequestError("raw_body_base64 is invalid") from exc
    if len(payload) > MAX_RESPONSE_BYTES:
        raise OperatorRequestError("request body exceeded 10 MB")
    return payload


def _targets_salesforce_lifecycle_order(
    method: str,
    path: str,
    json_body: Any,
    raw_body_base64: str,
) -> bool:
    if method in READ_METHODS:
        return False
    marker = "novapos_order__c"
    if marker in path.casefold():
        return True

    def contains_marker(value: Any) -> bool:
        if isinstance(value, str):
            return marker in value.casefold()
        if isinstance(value, dict):
            return any(
                contains_marker(key) or contains_marker(item)
                for key, item in value.items()
            )
        if isinstance(value, (list, tuple)):
            return any(contains_marker(item) for item in value)
        return False

    if contains_marker(json_body):
        return True
    raw_body = _decode_body(raw_body_base64)
    return raw_body is not None and marker.encode("ascii") in raw_body.lower()


def _request_hash(params: dict[str, Any], json_body: Any, raw_body_base64: str) -> str:
    canonical = json.dumps(
        {"params": params, "json": json_body, "rawSha256": hashlib.sha256(raw_body_base64.encode()).hexdigest()},
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode()
    return hashlib.sha256(canonical).hexdigest()


def _response(response: requests.Response) -> dict[str, Any]:
    content = bytes(response.content or b"")
    if len(content) > MAX_RESPONSE_BYTES:
        raise RuntimeError("provider response exceeded 10 MB")
    content_type = str(response.headers.get("Content-Type") or "").split(";", 1)[0].strip().casefold()
    body: Any = None
    if content:
        if content_type.endswith("json") or "+json" in content_type:
            try:
                body = response.json()
            except ValueError:
                body = content.decode("utf-8", errors="replace")
        elif content_type.startswith("text/") or content_type in {"application/xml", "application/soap+xml"}:
            body = content.decode("utf-8", errors="replace")
        else:
            body = {"encoding": "base64", "data": base64.b64encode(content).decode("ascii")}
    return {
        "ok": 200 <= int(response.status_code) < 300,
        "statusCode": int(response.status_code),
        "contentType": content_type,
        "location": str(response.headers.get("Location") or "")[:2000],
        "etag": str(response.headers.get("ETag") or "")[:500],
        "body": body,
    }
