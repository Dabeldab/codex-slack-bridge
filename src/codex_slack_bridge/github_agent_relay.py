from __future__ import annotations

"""Narrow IAM-protected relay from GitHub Actions to private Command Center."""

import argparse
import ipaddress
import json
import logging
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Mapping

LOGGER = logging.getLogger("codex_slack_bridge.github_agent_relay")
MAX_REQUEST_BYTES = 64 * 1024
MAX_RESPONSE_BYTES = 512 * 1024
TASK_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,199}$")
JOB_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{5,239}$")
IAP_AUDIENCE_RE = re.compile(
    r"^projects/\d+/iap_web/cloud_run-[a-z0-9-]+/services/[a-z][a-z0-9-]{1,62}$"
)
ALIASES = {
    "rory": "direct_codex", "direct_codex": "direct_codex",
    "taylor": "coding_agent", "coding": "coding_agent", "coding_agent": "coding_agent",
    "alex": "tickets_agent", "tickets": "tickets_agent", "tickets_agent": "tickets_agent",
    "jamie": "billing_agent", "billing": "billing_agent", "billing_agent": "billing_agent",
    "thor": "claude_agent", "quality": "claude_agent", "claude_agent": "claude_agent",
}
LABELS = {"direct_codex": "Rory", "coding_agent": "Taylor", "tickets_agent": "Alex", "billing_agent": "Jamie", "claude_agent": "Thor"}
TERMINAL = frozenset({"completed", "completed_with_issues", "failed", "blocked", "interrupted", "recovery_review_required", "unclassified", "cancelled", "canceled"})
ALLOWED_PATHS = frozenset({"/health", "/agent-chat/send", "/jobs"})


class RelayConfigurationError(ValueError):
    pass


class RelayRequestError(ValueError):
    pass


class UpstreamError(RuntimeError):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = int(status)


@dataclass(frozen=True)
class RelaySettings:
    upstream_url: str
    token_path: Path
    timeout_seconds: float = 15.0
    upstream_auth_mode: str = "private_bearer"
    iap_audience: str = ""

    @classmethod
    def from_environment(cls) -> "RelaySettings":
        mode = str(os.getenv("COMMAND_CENTER_UPSTREAM_AUTH_MODE", "private_bearer")).strip().casefold()
        if mode == "private_bearer":
            url = _private_upstream(os.getenv("COMMAND_CENTER_UPSTREAM_URL", ""))
            audience = ""
        elif mode in {"cloud_run_iap", "cloud_run_iap_jwt"}:
            url = _cloud_run_iap_upstream(os.getenv("COMMAND_CENTER_UPSTREAM_URL", ""))
            audience = str(os.getenv("COMMAND_CENTER_IAP_AUDIENCE", "")).strip()
            if mode == "cloud_run_iap" and not IAP_AUDIENCE_RE.fullmatch(audience):
                raise RelayConfigurationError("COMMAND_CENTER_IAP_AUDIENCE is invalid")
        else:
            raise RelayConfigurationError("COMMAND_CENTER_UPSTREAM_AUTH_MODE is invalid")
        path = Path(os.getenv("COMMAND_CENTER_UPSTREAM_TOKEN_PATH", "")).expanduser()
        if not path.is_file():
            raise RelayConfigurationError("Command Center token secret is unavailable")
        try:
            timeout = float(os.getenv("COMMAND_CENTER_UPSTREAM_TIMEOUT_SECONDS", "15"))
        except ValueError as exc:
            raise RelayConfigurationError("upstream timeout must be numeric") from exc
        if not 1 <= timeout <= 30:
            raise RelayConfigurationError("upstream timeout must be 1-30 seconds")
        return cls(url, path, timeout, mode, audience)


class CommandCenterRelay:
    def __init__(self, settings: RelaySettings) -> None:
        self.settings = settings
        self._signed_iap_jwt = ""
        self._signed_iap_jwt_expires_at = 0.0

    def health(self) -> dict[str, Any]:
        body = self._request("GET", "/health")
        return {"ok": bool(body.get("ok", True)), "service": "nova-github-agent-relay", "upstreamService": str(body.get("service") or ""), "runtimeMode": str(body.get("runtimeMode") or ""), "externalWritesEnabled": body.get("externalWritesEnabled")}

    def submit(self, raw: Mapping[str, Any]) -> dict[str, Any]:
        task = normalize_task_envelope(raw)
        message = task["instruction"] if not task["title"] else f"{task['title']}\n\n{task['instruction']}"
        payload = {
            "id": task["idempotency_key"], "idempotencyKey": task["idempotency_key"],
            "type": "agent-direct-chat", "agent": task["agent"], "agentName": task["agent"],
            "agentLabel": LABELS[task["agent"]], "message": message, "instruction": message,
            "reasoningProvider": task["reasoning_provider"],
            "attachments": [], "createdAt": task["created_at"], "relayTaskId": task["task_id"],
            "relaySource": "github-actions",
        }
        body = self._request("POST", "/agent-chat/send", payload)
        if body.get("accepted") is False:
            message = str(body.get("message") or "Command Center rejected task")
            if message == "agent_provider_unready":
                # Emit allowlisted backend/status values only, never raw provider diagnostics.
                readiness = body.get("providerReadiness")
                readiness = readiness if isinstance(readiness, Mapping) else {}
                backend = str(readiness.get("provider") or "").strip()
                status = str(readiness.get("status") or "").strip()
                if backend in {"codex_cli", "codex_cli_direct", "chatgpt_relay"} and status in {
                    "not_checked", "not_authenticated", "probe_failed", "probe_in_progress",
                    "probe_timeout", "probe_unavailable", "ready", "unsupported_provider",
                }:
                    message = f"agent_provider_unready: {backend}/{status}"
            raise UpstreamError(409, message)
        job_id = _first(body.get("job_id"), body.get("jobId"), body.get("id"))
        if not JOB_ID_RE.fullmatch(job_id):
            raise UpstreamError(502, "Command Center returned no valid durable job id")
        return {"ok": True, "accepted": True, "task_id": task["task_id"], "job_id": job_id, "bridge_job_id": body.get("bridge_job_id") or body.get("bridgeJobId"), "agent": task["agent"], "agent_label": LABELS[task["agent"]], "reasoning_provider": task["reasoning_provider"], "duplicate": bool(body.get("duplicate")), "status": str(body.get("status") or "queued"), "idempotency_key": task["idempotency_key"]}

    def job(self, job_id: str) -> dict[str, Any]:
        clean = str(job_id or "").strip()
        if not JOB_ID_RE.fullmatch(clean):
            raise RelayRequestError("job id is invalid")
        jobs = self._request("GET", "/jobs?limit=200").get("jobs")
        if not isinstance(jobs, list):
            raise UpstreamError(502, "Command Center jobs response is invalid")
        for item in jobs:
            if isinstance(item, dict) and _job_id(item) == clean:
                return project_job(item)
        raise UpstreamError(404, "job was not found in current Command Center projection")

    def _request(self, method: str, path: str, body: Mapping[str, Any] | None = None) -> dict[str, Any]:
        path = _safe_path(path)
        token = self.settings.token_path.read_text(encoding="utf-8").strip()
        if len(token) < 32 or any(c.isspace() for c in token):
            raise RelayConfigurationError("mounted Command Center token is invalid")
        data = None if body is None else json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode()
        if data is not None and len(data) > MAX_REQUEST_BYTES:
            raise RelayRequestError("serialized task exceeds relay request limit")
        headers = {"Accept": "application/json", "Authorization": f"Bearer {token}", "User-Agent": "nova-github-agent-relay/1"}
        if self.settings.upstream_auth_mode == "cloud_run_iap":
            headers["Proxy-Authorization"] = f"Bearer {self._iap_identity_token()}"
        elif self.settings.upstream_auth_mode == "cloud_run_iap_jwt":
            headers["Proxy-Authorization"] = f"Bearer {self._iap_signed_jwt()}"
        if data is not None:
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(f"{self.settings.upstream_url}{path}", data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=self.settings.timeout_seconds) as response:  # nosec B310 - validated RFC1918 origin
                raw = response.read(MAX_RESPONSE_BYTES + 1)
                if len(raw) > MAX_RESPONSE_BYTES:
                    raise UpstreamError(502, "Command Center response exceeded relay limit")
                parsed = json.loads(raw.decode() or "{}")
                if not isinstance(parsed, dict):
                    raise UpstreamError(502, "Command Center response was not an object")
                return parsed
        except urllib.error.HTTPError as exc:
            raw = exc.read(128 * 1024)
            try:
                parsed = json.loads(raw.decode() or "{}")
            except Exception:
                parsed = {}
            raise UpstreamError(exc.code, str(parsed.get("message") or parsed.get("error") or exc.reason or "upstream request failed")) from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise UpstreamError(502, "private Command Center is unavailable") from exc
        except json.JSONDecodeError as exc:
            raise UpstreamError(502, "Command Center returned invalid JSON") from exc

    def _iap_identity_token(self) -> str:
        query = urllib.parse.urlencode({"audience": self.settings.iap_audience, "format": "full"})
        request = urllib.request.Request(
            "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/identity?" + query,
            headers={"Metadata-Flavor": "Google"},
            method="GET",
        )
        try:
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open(request, timeout=min(self.settings.timeout_seconds, 10)) as response:
                token = response.read(16 * 1024).decode("utf-8").strip()
        except (OSError, urllib.error.URLError, TimeoutError, UnicodeDecodeError) as exc:
            raise UpstreamError(502, "relay could not obtain its IAP identity token") from exc
        if token.count(".") != 2 or len(token) > 16 * 1024:
            raise UpstreamError(502, "relay received an invalid IAP identity token")
        return token

    def _iap_signed_jwt(self) -> str:
        if self._signed_iap_jwt and time.monotonic() < self._signed_iap_jwt_expires_at:
            return self._signed_iap_jwt
        email = self._metadata_text("email")
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{4,28}[a-z0-9]@[a-z0-9.-]+\.iam\.gserviceaccount\.com", email):
            raise UpstreamError(502, "relay received an invalid service identity")
        try:
            access_token = str(json.loads(self._metadata_text("token")).get("access_token") or "")
        except json.JSONDecodeError as exc:
            raise UpstreamError(502, "relay could not read its service access token") from exc
        if len(access_token) < 20 or any(character.isspace() for character in access_token):
            raise UpstreamError(502, "relay received an invalid service access token")
        now = int(time.time())
        claims = json.dumps({"iss": email, "sub": email, "aud": self.settings.upstream_url + "/*", "iat": now, "exp": now + 300}, separators=(",", ":"))
        endpoint = "https://iamcredentials.googleapis.com/v1/projects/-/serviceAccounts/" + urllib.parse.quote(email, safe="@") + ":signJwt"
        request = urllib.request.Request(endpoint, data=json.dumps({"payload": claims}, separators=(",", ":")).encode(), headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json", "Accept": "application/json"}, method="POST")
        try:
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open(request, timeout=min(self.settings.timeout_seconds, 10)) as response:
                signed = str(json.loads(response.read(32 * 1024).decode("utf-8")).get("signedJwt") or "").strip()
        except (OSError, urllib.error.URLError, urllib.error.HTTPError, TimeoutError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise UpstreamError(502, "relay could not create its IAP service JWT") from exc
        if signed.count(".") != 2 or len(signed) > 32 * 1024:
            raise UpstreamError(502, "relay received an invalid IAP service JWT")
        self._signed_iap_jwt = signed
        self._signed_iap_jwt_expires_at = time.monotonic() + 240
        return signed

    @staticmethod
    def _metadata_text(resource: str) -> str:
        request = urllib.request.Request("http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/" + resource, headers={"Metadata-Flavor": "Google"}, method="GET")
        try:
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open(request, timeout=10) as response:
                return response.read(32 * 1024).decode("utf-8").strip()
        except (OSError, urllib.error.URLError, TimeoutError, UnicodeDecodeError) as exc:
            raise UpstreamError(502, "relay could not read its service identity") from exc


def normalize_task_envelope(raw: Mapping[str, Any]) -> dict[str, str]:
    if not isinstance(raw, Mapping) or raw.get("version", 1) != 1:
        raise RelayRequestError("task must be a version 1 JSON object")
    task_id = str(raw.get("task_id") or raw.get("taskId") or "").strip()
    if not TASK_ID_RE.fullmatch(task_id):
        raise RelayRequestError("task_id must be 8-200 safe characters")
    agent = ALIASES.get(str(raw.get("agent") or "direct_codex").strip().casefold())
    if not agent:
        raise RelayRequestError("agent must be Rory, Taylor, Alex, Jamie, Thor, or a canonical lane id")
    title = str(raw.get("title") or "").strip()
    instruction = str(raw.get("instruction") or raw.get("prompt") or "").strip()
    if not instruction:
        raise RelayRequestError("instruction is required")
    if len(title) > 500:
        raise RelayRequestError("title exceeds 500 characters")
    if len(instruction) > 12000:
        raise RelayRequestError("instruction exceeds 12000 characters")
    key = str(raw.get("idempotency_key") or raw.get("idempotencyKey") or f"github-relay:{task_id}").strip()
    if not TASK_ID_RE.fullmatch(key) or len(key) > 200:
        raise RelayRequestError("idempotency_key must be 8-200 safe characters")
    provider_value = raw.get("reasoning_provider", raw.get("reasoningProvider", "codex_cli"))
    if not isinstance(provider_value, str):
        raise RelayRequestError("reasoning_provider must be codex_cli or chatgpt_relay")
    reasoning_provider = provider_value.strip().casefold()
    if reasoning_provider not in {"codex_cli", "chatgpt_relay"}:
        raise RelayRequestError("reasoning_provider must be codex_cli or chatgpt_relay")
    created = str(raw.get("created_at") or raw.get("createdAt") or "").strip() or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    if len(created) > 100 or any(ord(c) < 32 for c in created):
        raise RelayRequestError("created_at is invalid")
    return {"task_id": task_id, "agent": agent, "title": title, "instruction": instruction, "idempotency_key": key, "created_at": created, "reasoning_provider": reasoning_provider}


def project_job(job: Mapping[str, Any]) -> dict[str, Any]:
    status = str(job.get("status") or "queued").strip().casefold() or "queued"
    result = str(job.get("result") or job.get("resultText") or "")
    if len(result) > 250_000:
        result = result[:250_000] + "\n[relay result truncated]"
    return {"ok": True, "job_id": _job_id(job), "bridge_job_id": job.get("bridgeJobId") or job.get("bridge_job_id"), "agent": str(job.get("agentName") or job.get("agent_name") or ""), "source_type": str(job.get("sourceType") or job.get("source_type") or ""), "status": status, "terminal": status in TERMINAL, "result": result, "message": str(job.get("message") or ""), "error": str(job.get("error") or ""), "created_at": str(job.get("createdAtUtc") or job.get("created_at") or ""), "started_at": str(job.get("startedAtUtc") or job.get("started_at") or ""), "completed_at": str(job.get("completedAtUtc") or job.get("completed_at") or "")}


def _first(*values: Any) -> str:
    return next((str(v).strip() for v in values if str(v or "").strip()), "")


def _job_id(job: Mapping[str, Any]) -> str:
    return _first(job.get("id"), job.get("jobId"), job.get("job_id"), job.get("bridgeJobId"), job.get("bridge_job_id"))


def _private_upstream(value: str) -> str:
    try:
        parsed = urllib.parse.urlparse(str(value or "").strip().rstrip("/"))
        address = ipaddress.ip_address(parsed.hostname or "")
    except ValueError as exc:
        raise RelayConfigurationError("COMMAND_CENTER_UPSTREAM_URL must use a literal private IPv4 address") from exc
    if parsed.scheme != "http" or not isinstance(address, ipaddress.IPv4Address) or not address.is_private or address.is_loopback or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in {"", "/"} or parsed.port is None:
        raise RelayConfigurationError("COMMAND_CENTER_UPSTREAM_URL must be one private HTTP IPv4 origin with explicit port")
    return f"http://{address.compressed}:{parsed.port}"


def _validated_private_upstream_url(value: str) -> str:
    return _private_upstream(value)


def _cloud_run_iap_upstream(value: str) -> str:
    try:
        parsed = urllib.parse.urlparse(str(value or "").strip().rstrip("/"))
    except ValueError as exc:
        raise RelayConfigurationError("COMMAND_CENTER_UPSTREAM_URL must be a Cloud Run HTTPS origin") from exc
    hostname = (parsed.hostname or "").casefold()
    if (
        parsed.scheme != "https"
        or not hostname.endswith(".run.app")
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
        or parsed.port not in {None, 443}
    ):
        raise RelayConfigurationError("COMMAND_CENTER_UPSTREAM_URL must be a Cloud Run HTTPS origin")
    return f"https://{hostname}"


def _safe_path(path: str) -> str:
    clean = str(path or "").strip()
    if not clean.startswith("/") or "\\" in clean or "\x00" in clean:
        raise RelayRequestError("upstream path is invalid")
    parsed = urllib.parse.urlsplit(clean)
    if parsed.scheme or parsed.netloc or parsed.fragment or parsed.path not in ALLOWED_PATHS:
        raise RelayRequestError("upstream path is not allowed")
    if parsed.path != "/jobs" and parsed.query:
        raise RelayRequestError("upstream query is not allowed")
    if parsed.path == "/jobs" and parsed.query not in {"", "limit=200"}:
        raise RelayRequestError("jobs query is not allowed")
    return clean


def _safe_upstream_path(path: str) -> str:
    return _safe_path(path)


class Handler(BaseHTTPRequestHandler):
    relay: CommandCenterRelay
    server_version = "NovaGitHubRelay/1"

    def log_message(self, fmt: str, *args: Any) -> None:
        LOGGER.info("%s - %s", self.address_string(), fmt % args)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlsplit(self.path)
        try:
            if parsed.path == "/health" and not parsed.query:
                return self._json(200, self.relay.health())
            if parsed.path.startswith("/v1/jobs/") and not parsed.query:
                return self._json(200, self.relay.job(urllib.parse.unquote(parsed.path[9:])))
            self._json(404, {"ok": False, "message": "not found"})
        except Exception as exc:
            self._error(exc)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlsplit(self.path)
        if parsed.path != "/v1/tasks" or parsed.query:
            return self._json(404, {"ok": False, "message": "not found"})
        try:
            length = int(str(self.headers.get("Content-Length") or "0"))
            if not 2 <= length <= MAX_REQUEST_BYTES:
                raise RelayRequestError("request body size is invalid")
            body = json.loads(self.rfile.read(length).decode())
            if not isinstance(body, dict):
                raise RelayRequestError("request body must be a JSON object")
            self._json(202, self.relay.submit(body))
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            self._error(RelayRequestError(str(exc) or "invalid JSON request"))
        except Exception as exc:
            self._error(exc)

    def _error(self, exc: Exception) -> None:
        if isinstance(exc, RelayRequestError):
            return self._json(400, {"ok": False, "message": str(exc)})
        if isinstance(exc, RelayConfigurationError):
            LOGGER.error("relay config: %s", exc)
            return self._json(503, {"ok": False, "message": "relay configuration unavailable"})
        if isinstance(exc, UpstreamError):
            status = exc.status if exc.status in {400, 404, 409, 423, 429} else 502
            return self._json(status, {"ok": False, "message": str(exc)})
        LOGGER.exception("unhandled relay request")
        self._json(500, {"ok": False, "message": "relay request failed"})

    def _json(self, status: int, body: Mapping[str, Any]) -> None:
        raw = json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode()
        self.send_response(status)
        for key, value in (("Content-Type", "application/json; charset=utf-8"), ("Content-Length", str(len(raw))), ("Cache-Control", "no-store"), ("X-Content-Type-Options", "nosniff")):
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(raw)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default=os.getenv("HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.getenv("PORT", "8080")))
    args = parser.parse_args()
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    relay = CommandCenterRelay(RelaySettings.from_environment())
    handler = type("ConfiguredRelayHandler", (Handler,), {"relay": relay})
    server = ThreadingHTTPServer((args.host, args.port), handler)
    server.daemon_threads = True
    try:
        server.serve_forever(0.5)
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
