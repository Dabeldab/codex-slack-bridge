from __future__ import annotations

import base64
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import time
from typing import Any, Mapping

import requests
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

from .reasoning_relay_protocol import RelayRequest, RelayResponse


REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}$")
BRANCH_RE = re.compile(r"^[A-Za-z0-9._/-]{1,180}$")


@dataclass(frozen=True)
class GitHubRelaySettings:
    repository: str
    branch: str
    app_id_path: Path
    installation_id_path: Path
    private_key_path: Path
    poll_seconds: float = 2.0

    @classmethod
    def from_environment(cls) -> "GitHubRelaySettings":
        repository = str(os.getenv("REASONING_RELAY_REPOSITORY") or "dariusmakesstuff/codex-slack-bridge").strip()
        branch = str(os.getenv("REASONING_RELAY_BRANCH") or "reasoning-relay-bus").strip()
        if not REPOSITORY_RE.fullmatch(repository):
            raise RuntimeError("REASONING_RELAY_REPOSITORY is invalid")
        if not BRANCH_RE.fullmatch(branch) or ".." in branch:
            raise RuntimeError("REASONING_RELAY_BRANCH is invalid")
        allowed = {
            item.strip().casefold()
            for item in str(os.getenv("GITHUB_ALLOWED_REPOSITORIES") or "").split(",")
            if item.strip()
        }
        if allowed and repository.casefold() not in allowed:
            raise RuntimeError("reasoning relay repository is outside GITHUB_ALLOWED_REPOSITORIES")
        settings = cls(
            repository=repository,
            branch=branch,
            app_id_path=Path(os.getenv("GITHUB_APP_ID_PATH", "")).expanduser(),
            installation_id_path=Path(os.getenv("GITHUB_APP_INSTALLATION_ID_PATH", "")).expanduser(),
            private_key_path=Path(os.getenv("GITHUB_APP_PRIVATE_KEY_PATH", "")).expanduser(),
            poll_seconds=max(0.5, min(float(os.getenv("REASONING_RELAY_POLL_SECONDS") or 2.0), 30.0)),
        )
        for path in (settings.app_id_path, settings.installation_id_path, settings.private_key_path):
            if not path.is_file():
                raise RuntimeError("GitHub App credential files for reasoning relay are unavailable")
        return settings


class GitHubReasoningRelayTransport:
    def __init__(self, settings: GitHubRelaySettings, *, session: requests.Session | None = None) -> None:
        self.settings = settings
        self._session = session or requests.Session()
        self._token = ""
        self._token_expires_at = 0.0

    @property
    def repository(self) -> str:
        return self.settings.repository

    @property
    def branch(self) -> str:
        return self.settings.branch

    def health(self) -> dict[str, Any]:
        metadata = self._api("GET", f"/repos/{self.repository}")
        ref = self._api_optional("GET", f"/repos/{self.repository}/git/ref/heads/{self.branch}")
        return {
            "ok": True,
            "repository": str(metadata.get("full_name") or ""),
            "branch": self.branch,
            "branchExists": bool(ref),
        }

    def ensure_branch(self) -> str:
        existing = self._api_optional("GET", f"/repos/{self.repository}/git/ref/heads/{self.branch}")
        if existing:
            return str((existing.get("object") or {}).get("sha") or "")
        metadata = self._api("GET", f"/repos/{self.repository}")
        default_branch = str(metadata.get("default_branch") or "main")
        base = self._api("GET", f"/repos/{self.repository}/git/ref/heads/{default_branch}")
        sha = str((base.get("object") or {}).get("sha") or "")
        if not sha:
            raise RuntimeError("GitHub relay base branch could not be resolved")
        created = self._api(
            "POST",
            f"/repos/{self.repository}/git/refs",
            json={"ref": f"refs/heads/{self.branch}", "sha": sha},
        )
        return str((created.get("object") or {}).get("sha") or sha)

    def ensure_pull_request(self) -> dict[str, Any]:
        self.ensure_branch()
        self._ensure_bootstrap_file()
        owner = self.repository.split("/", 1)[0]
        rows = self._api(
            "GET",
            f"/repos/{self.repository}/pulls",
            params={"state": "open", "head": f"{owner}:{self.branch}", "per_page": 20},
        )
        if rows:
            row = rows[0]
            return {"number": int(row.get("number") or 0), "htmlUrl": str(row.get("html_url") or ""), "status": "existing"}
        metadata = self._api("GET", f"/repos/{self.repository}")
        created = self._api(
            "POST",
            f"/repos/{self.repository}/pulls",
            json={
                "title": "Nova Reasoning Relay (do not merge)",
                "body": (
                    "Long-lived machine mailbox for ChatGPT Work reasoning events. "
                    "Do not merge or close while the relay is enabled."
                ),
                "head": self.branch,
                "base": str(metadata.get("default_branch") or "main"),
            },
        )
        return {"number": int(created.get("number") or 0), "htmlUrl": str(created.get("html_url") or ""), "status": "created"}

    def publish(self, request: RelayRequest) -> str:
        self.ensure_branch()
        path = f"relay/runtime/outbound/{request.message_id}.json"
        self._put_json(path, request.to_dict())
        return path

    def wait_response(self, request: RelayRequest, *, timeout_seconds: float) -> RelayResponse:
        path = f"relay/runtime/inbound/{request.message_id}.json"
        deadline = time.monotonic() + max(1.0, float(timeout_seconds))
        while True:
            raw = self._get_json(path)
            if raw is not None:
                return RelayResponse.from_dict(raw, expected_request=request)
            if time.monotonic() >= deadline:
                raise TimeoutError(f"Timed out waiting for ChatGPT relay response to {request.message_id}")
            time.sleep(self.settings.poll_seconds)

    def cleanup(self, request: RelayRequest) -> None:
        for path in (
            f"relay/runtime/outbound/{request.message_id}.json",
            f"relay/runtime/inbound/{request.message_id}.json",
        ):
            try:
                self._delete_path(path)
            except Exception:
                pass

    def _ensure_bootstrap_file(self) -> None:
        path = "relay/runtime/README.md"
        if self._get_content(path) is not None:
            return
        content = (
            "# Runtime Reasoning Relay\n\n"
            "This branch is a transient mailbox for the Nova Command Center ChatGPT Work relay.\n"
            "The long-lived pull request for this branch must remain open while the relay is enabled.\n"
        ).encode("utf-8")
        self._put_bytes(path, content, "relay: initialize reasoning mailbox")

    def _get_json(self, path: str) -> dict[str, Any] | None:
        payload = self._get_content(path)
        if payload is None:
            return None
        try:
            decoded = base64.b64decode(str(payload.get("content") or "")).decode("utf-8")
            parsed = json.loads(decoded)
        except (ValueError, UnicodeError, json.JSONDecodeError) as exc:
            raise RuntimeError("GitHub relay mailbox contained invalid JSON") from exc
        if not isinstance(parsed, dict):
            raise RuntimeError("GitHub relay mailbox payload must be an object")
        return parsed

    def _put_json(self, path: str, payload: Mapping[str, Any]) -> None:
        encoded = (json.dumps(dict(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
        self._put_bytes(path, encoded, f"relay: {path.rsplit('/', 1)[-1]}")

    def _put_bytes(self, path: str, content: bytes, message: str) -> None:
        existing = self._get_content(path)
        if existing is not None:
            current = base64.b64decode(str(existing.get("content") or ""))
            if current == content:
                return
            raise RuntimeError("reasoning relay attempted to overwrite an existing mailbox message")
        body = {
            "message": message[:200],
            "content": base64.b64encode(content).decode("ascii"),
            "branch": self.branch,
        }
        last_error: Exception | None = None
        for delay in (0.0, 0.5, 1.5, 3.0):
            if delay:
                time.sleep(delay)
            try:
                self._api("PUT", f"/repos/{self.repository}/contents/{path}", json=body)
                return
            except requests.HTTPError as exc:
                last_error = exc
                if exc.response is None or exc.response.status_code not in {409, 422}:
                    raise
                if self._get_content(path) is not None:
                    return
        raise RuntimeError("GitHub relay write conflicted repeatedly") from last_error

    def _delete_path(self, path: str) -> None:
        existing = self._get_content(path)
        if existing is None:
            return
        sha = str(existing.get("sha") or "")
        if not sha:
            return
        self._api(
            "DELETE",
            f"/repos/{self.repository}/contents/{path}",
            json={"message": f"relay: consume {path.rsplit('/', 1)[-1]}", "sha": sha, "branch": self.branch},
        )

    def _get_content(self, path: str) -> dict[str, Any] | None:
        value = self._api_optional(
            "GET",
            f"/repos/{self.repository}/contents/{path}",
            params={"ref": self.branch},
        )
        return value if isinstance(value, dict) else None

    def _api_optional(self, method: str, path: str, **kwargs: Any) -> Any:
        response = self._request(method, path, **kwargs)
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response.json() if response.content else {}

    def _api(self, method: str, path: str, **kwargs: Any) -> Any:
        response = self._request(method, path, **kwargs)
        response.raise_for_status()
        if not response.content:
            return {}
        payload = response.json()
        if not isinstance(payload, (dict, list)):
            raise RuntimeError("GitHub relay returned an unexpected response")
        return payload

    def _request(self, method: str, path: str, **kwargs: Any) -> requests.Response:
        token = self._installation_token()
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "nova-reasoning-relay/1.0",
        }
        headers.update(kwargs.pop("headers", {}) or {})
        return self._session.request(
            method,
            f"https://api.github.com{path}",
            headers=headers,
            timeout=30,
            **kwargs,
        )

    def _installation_token(self) -> str:
        now = time.time()
        if self._token and now < self._token_expires_at - 60:
            return self._token
        app_jwt = self._app_jwt()
        installation_id = self.settings.installation_id_path.read_text(encoding="utf-8").strip()
        response = self._session.post(
            f"https://api.github.com/app/installations/{installation_id}/access_tokens",
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {app_jwt}",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "nova-reasoning-relay/1.0",
            },
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        token = str(payload.get("token") or "")
        if not token:
            raise RuntimeError("GitHub App did not return an installation token")
        self._token = token
        self._token_expires_at = now + 3000
        return token

    def _app_jwt(self) -> str:
        app_id = self.settings.app_id_path.read_text(encoding="utf-8").strip()
        key_bytes = self.settings.private_key_path.read_bytes()
        private_key = serialization.load_pem_private_key(key_bytes, password=None)
        now = int(time.time())
        header = {"alg": "RS256", "typ": "JWT"}
        payload = {"iat": now - 60, "exp": now + 540, "iss": app_id}

        def b64(value: bytes) -> bytes:
            return base64.urlsafe_b64encode(value).rstrip(b"=")

        signing_input = b".".join(
            (
                b64(json.dumps(header, separators=(",", ":")).encode("utf-8")),
                b64(json.dumps(payload, separators=(",", ":")).encode("utf-8")),
            )
        )
        signature = private_key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
        return (signing_input + b"." + b64(signature)).decode("ascii")
