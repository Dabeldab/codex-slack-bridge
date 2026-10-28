from __future__ import annotations

import getpass
import hmac
import json
import os
import secrets
import stat
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from email.message import Message
from http.cookies import CookieError, SimpleCookie
from pathlib import Path
from threading import Lock
from typing import Any, Callable, Iterable, Mapping


SESSION_COOKIE = "NovaCommandCenterSession"
CSRF_COOKIE = "NovaCommandCenterCsrf"
CSRF_HEADER = "X-Nova-CSRF"
OAUTH_STATE_COOKIE = "NovaCommandCenterOAuthState"


class GoogleOAuthConfigurationError(ValueError):
    """Raised when cloud Google authentication is not configured fail-closed."""


class GoogleOAuthError(RuntimeError):
    """Raised when Google authentication cannot be completed safely."""


class GoogleOAuthAccessDenied(GoogleOAuthError):
    """Raised when a verified Google identity is not explicitly allowlisted."""


@dataclass(frozen=True)
class GoogleOAuthConfig:
    client_id: str
    client_secret: str = field(repr=False)
    redirect_uri: str
    public_origin: str
    allowed_emails: frozenset[str]
    state_ttl_seconds: int = 10 * 60
    secure_cookies: bool = True

    @classmethod
    def from_environment(cls, environment: Mapping[str, str] | None = None) -> "GoogleOAuthConfig":
        source = os.environ if environment is None else environment
        client_id = str(source.get("GOOGLE_CLIENT_ID") or "").strip()
        client_secret = str(source.get("GOOGLE_CLIENT_SECRET") or "").strip()
        redirect_uri = str(source.get("GOOGLE_REDIRECT_URI") or "").strip()
        public_origin = str(source.get("COMMAND_CENTER_PUBLIC_ORIGIN") or "").strip().rstrip("/")
        allowed_emails = frozenset(
            item.strip().casefold()
            for item in str(source.get("GOOGLE_OAUTH_ALLOWED_EMAILS") or "").split(",")
            if item.strip()
        )

        missing = [
            name
            for name, value in (
                ("GOOGLE_CLIENT_ID", client_id),
                ("GOOGLE_CLIENT_SECRET", client_secret),
                ("GOOGLE_REDIRECT_URI", redirect_uri),
                ("COMMAND_CENTER_PUBLIC_ORIGIN", public_origin),
                ("GOOGLE_OAUTH_ALLOWED_EMAILS", allowed_emails),
            )
            if not value
        ]
        if missing:
            raise GoogleOAuthConfigurationError(
                "Google authentication is enabled but required settings are missing: " + ", ".join(missing)
            )
        if not client_id.endswith(".apps.googleusercontent.com"):
            raise GoogleOAuthConfigurationError("GOOGLE_CLIENT_ID is not a Google web application client ID")
        for email in allowed_emails:
            if email.count("@") != 1 or any(character.isspace() for character in email) or "*" in email:
                raise GoogleOAuthConfigurationError(
                    "GOOGLE_OAUTH_ALLOWED_EMAILS must contain exact email addresses without wildcards"
                )

        redirect = _validated_web_url(redirect_uri, setting_name="GOOGLE_REDIRECT_URI", allow_path=True)
        origin = _validated_web_url(public_origin, setting_name="COMMAND_CENTER_PUBLIC_ORIGIN", allow_path=False)
        redirect_origin = _url_origin(redirect)
        if redirect_origin != _url_origin(origin):
            raise GoogleOAuthConfigurationError(
                "GOOGLE_REDIRECT_URI and COMMAND_CENTER_PUBLIC_ORIGIN must use the same exact origin"
            )
        if redirect.path != "/auth/google/callback" or redirect.query or redirect.fragment:
            raise GoogleOAuthConfigurationError(
                "GOOGLE_REDIRECT_URI must end exactly with /auth/google/callback and contain no query or fragment"
            )
        loopback = _is_loopback_hostname(redirect.hostname or "")
        if redirect.scheme != "https" and not loopback:
            raise GoogleOAuthConfigurationError("Google OAuth requires HTTPS except for localhost development")

        return cls(
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri=redirect_uri,
            public_origin=public_origin,
            allowed_emails=allowed_emails,
            secure_cookies=not loopback,
        )


@dataclass(frozen=True)
class GoogleOAuthPrincipal:
    subject: str
    email: str
    name: str = ""


class GoogleOAuthClient:
    """Google authorization-code client with cryptographic ID-token verification."""

    authorization_endpoint = "https://accounts.google.com/o/oauth2/v2/auth"
    # This is Google's public OAuth token endpoint, not a credential.
    token_endpoint = "https://oauth2.googleapis.com/token"  # nosec B105

    def __init__(
        self,
        config: GoogleOAuthConfig,
        *,
        token_exchange: Callable[[str], Mapping[str, Any]] | None = None,
        id_token_verifier: Callable[[str, str], Mapping[str, Any]] | None = None,
    ) -> None:
        self.config = config
        self._token_exchange = token_exchange or self._exchange_token
        self._id_token_verifier = id_token_verifier or self._verify_id_token

    def authorization_url(self, state: str) -> str:
        params = {
            "client_id": self.config.client_id,
            "redirect_uri": self.config.redirect_uri,
            "response_type": "code",
            "scope": "openid email profile",
            "state": state,
            "prompt": "select_account",
        }
        return f"{self.authorization_endpoint}?{urllib.parse.urlencode(params)}"

    def exchange_code(self, code: str) -> GoogleOAuthPrincipal:
        clean_code = str(code or "").strip()
        if not clean_code:
            raise GoogleOAuthError("Google did not return an authorization code")
        token_payload = self._token_exchange(clean_code)
        raw_id_token = str(token_payload.get("id_token") or "").strip()
        if not raw_id_token:
            raise GoogleOAuthError("Google did not return an ID token")
        claims = self._id_token_verifier(raw_id_token, self.config.client_id)
        issuer = str(claims.get("iss") or "")
        if issuer not in {"accounts.google.com", "https://accounts.google.com"}:
            raise GoogleOAuthError("Google ID token issuer is invalid")
        if claims.get("email_verified") is not True:
            raise GoogleOAuthAccessDenied("Google account email is not verified")
        subject = str(claims.get("sub") or "").strip()
        email = str(claims.get("email") or "").strip().casefold()
        if not subject or not email:
            raise GoogleOAuthError("Google ID token is missing required identity claims")
        if email not in self.config.allowed_emails:
            raise GoogleOAuthAccessDenied("This Google account is not authorized for Nova Command Center")
        return GoogleOAuthPrincipal(subject=subject, email=email, name=str(claims.get("name") or "").strip())

    def _exchange_token(self, code: str) -> Mapping[str, Any]:
        parsed_endpoint = urllib.parse.urlparse(self.token_endpoint)
        if (
            parsed_endpoint.scheme != "https"
            or parsed_endpoint.hostname != "oauth2.googleapis.com"
            or parsed_endpoint.path != "/token"
            or parsed_endpoint.query
            or parsed_endpoint.fragment
        ):
            raise GoogleOAuthConfigurationError("Google token endpoint is not the expected HTTPS endpoint")
        body = urllib.parse.urlencode(
            {
                "code": code,
                "client_id": self.config.client_id,
                "client_secret": self.config.client_secret,
                "redirect_uri": self.config.redirect_uri,
                "grant_type": "authorization_code",
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            self.token_endpoint,
            data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
            method="POST",
        )
        try:
            # The request URL is the exact HTTPS Google token endpoint validated above.
            with urllib.request.urlopen(request, timeout=15) as response:  # nosec B310
                payload = json.loads(response.read(128 * 1024).decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise GoogleOAuthError("Google token exchange failed") from exc
        if not isinstance(payload, dict):
            raise GoogleOAuthError("Google token response is invalid")
        if payload.get("error"):
            raise GoogleOAuthError("Google rejected the authorization code")
        return payload

    @staticmethod
    def _verify_id_token(raw_id_token: str, audience: str) -> Mapping[str, Any]:
        try:
            from google.auth.transport.requests import Request as GoogleRequest
            from google.oauth2 import id_token as google_id_token

            claims = google_id_token.verify_oauth2_token(raw_id_token, GoogleRequest(), audience=audience)
        except Exception as exc:
            raise GoogleOAuthError("Google ID token verification failed") from exc
        if not isinstance(claims, dict):
            raise GoogleOAuthError("Google ID token claims are invalid")
        return claims


@dataclass(frozen=True)
class CommandCenterIdentity:
    mode: str
    session_id: str = ""
    csrf_token: str = ""
    email: str = ""
    subject: str = ""


@dataclass(frozen=True)
class _SessionRecord:
    csrf_token: str
    expires_at: float
    mode: str
    email: str = ""
    subject: str = ""


@dataclass(frozen=True)
class _OAuthStateRecord:
    expires_at: float


class CommandCenterAccess:
    """Per-launch bearer plus short-lived browser sessions for the loopback API."""

    def __init__(
        self,
        *,
        token_path: str | os.PathLike[str],
        allowed_origins: Iterable[str],
        session_ttl_seconds: int = 8 * 60 * 60,
        google_oauth: GoogleOAuthClient | None = None,
        trusted_bearer_path: str | os.PathLike[str] | None = None,
    ) -> None:
        self.token_path = _expanded_path(token_path)
        self.allowed_origins = frozenset(str(value).rstrip("/") for value in allowed_origins if str(value).strip())
        self.session_ttl_seconds = max(300, min(int(session_ttl_seconds), 24 * 60 * 60))
        self.google_oauth = google_oauth
        self.google_enabled = google_oauth is not None
        self.secure_cookies = bool(google_oauth and google_oauth.config.secure_cookies)
        self._bearer = secrets.token_urlsafe(48)
        self._trusted_bearer_path = (
            _expanded_path(trusted_bearer_path) if trusted_bearer_path else None
        )
        self._trusted_bearer = (
            _read_trusted_bearer(self._trusted_bearer_path)
            if self._trusted_bearer_path is not None
            else ""
        )
        self._sessions: dict[str, _SessionRecord] = {}
        self._oauth_states: dict[str, _OAuthStateRecord] = {}
        self._lock = Lock()
        _write_private_token(self.token_path, self._bearer)

    @property
    def trusted_bearer_enabled(self) -> bool:
        return bool(self._trusted_bearer)

    def close(self) -> None:
        """Remove only this process's token, never a newer replacement token."""

        with self._lock:
            self._sessions.clear()
            self._oauth_states.clear()

        try:
            current = self.token_path.read_text(encoding="utf-8").strip()
        except OSError:
            return
        if hmac.compare_digest(current, self._bearer):
            try:
                self.token_path.unlink()
            except OSError:
                pass

    def is_allowed_origin(self, origin: str | None) -> bool:
        clean = str(origin or "").rstrip("/")
        return bool(clean) and clean != "null" and clean in self.allowed_origins

    def issue_dashboard_session(self) -> list[str]:
        if self.google_enabled:
            raise GoogleOAuthError("Google-authenticated sessions must be issued by the OAuth callback")
        return self._issue_session(mode="dashboard_session")

    def begin_google_login(self) -> tuple[str, str]:
        if self.google_oauth is None:
            raise GoogleOAuthConfigurationError("Google authentication is not enabled")
        now = time.monotonic()
        state = secrets.token_urlsafe(32)
        with self._lock:
            self._prune_locked(now)
            if len(self._oauth_states) >= 128:
                oldest = min(self._oauth_states, key=lambda key: self._oauth_states[key].expires_at)
                self._oauth_states.pop(oldest, None)
            self._oauth_states[state] = _OAuthStateRecord(
                expires_at=now + self.google_oauth.config.state_ttl_seconds
            )
        cookie = self._cookie(
            OAUTH_STATE_COOKIE,
            state,
            max_age=self.google_oauth.config.state_ttl_seconds,
            path="/auth/google",
            http_only=True,
        )
        return self.google_oauth.authorization_url(state), cookie

    def complete_google_login(self, *, code: str, state: str, cookie_header: str) -> list[str]:
        if self.google_oauth is None:
            raise GoogleOAuthConfigurationError("Google authentication is not enabled")
        self._consume_oauth_state(state=state, cookie_header=cookie_header)
        principal = self.google_oauth.exchange_code(code)
        return [
            *self._issue_session(
                mode="google_session",
                email=principal.email,
                subject=principal.subject,
            ),
            self._clear_cookie(OAUTH_STATE_COOKIE, path="/auth/google", http_only=True),
        ]

    def reject_google_callback(self, *, state: str, cookie_header: str) -> str:
        self._consume_oauth_state(state=state, cookie_header=cookie_header)
        return self.clear_google_state_cookie()

    def clear_google_state_cookie(self) -> str:
        return self._clear_cookie(OAUTH_STATE_COOKIE, path="/auth/google", http_only=True)

    def logout(self, headers: Message) -> list[str]:
        identity = self.authenticate(headers)
        if identity is not None and identity.session_id:
            with self._lock:
                self._sessions.pop(identity.session_id, None)
        return [
            self._clear_cookie(SESSION_COOKIE, http_only=True),
            self._clear_cookie(CSRF_COOKIE),
        ]

    def public_identity(self, identity: CommandCenterIdentity) -> dict[str, str]:
        return {
            "mode": identity.mode,
            "email": identity.email,
        }

    def _issue_session(self, *, mode: str, email: str = "", subject: str = "") -> list[str]:
        now = time.monotonic()
        session_id = secrets.token_urlsafe(36)
        csrf_token = secrets.token_urlsafe(32)
        with self._lock:
            self._prune_locked(now)
            if len(self._sessions) >= 64:
                oldest = min(self._sessions, key=lambda key: self._sessions[key].expires_at)
                self._sessions.pop(oldest, None)
            self._sessions[session_id] = _SessionRecord(
                csrf_token=csrf_token,
                expires_at=now + self.session_ttl_seconds,
                mode=mode,
                email=email,
                subject=subject,
            )
        return [
            self._cookie(SESSION_COOKIE, session_id, max_age=self.session_ttl_seconds, http_only=True),
            self._cookie(CSRF_COOKIE, csrf_token, max_age=self.session_ttl_seconds),
        ]

    def authenticate(self, headers: Message) -> CommandCenterIdentity | None:
        authorization = str(headers.get("Authorization") or "").strip()
        if authorization.startswith("Bearer "):
            candidate = authorization[7:].strip()
            local_match = bool(candidate) and hmac.compare_digest(candidate, self._bearer)
            trusted_match = bool(candidate and self._trusted_bearer) and hmac.compare_digest(
                candidate,
                self._trusted_bearer,
            )
            if local_match or trusted_match:
                return CommandCenterIdentity(mode="internal_bearer")

        cookie_header = str(headers.get("Cookie") or "")
        try:
            cookies = SimpleCookie()
            cookies.load(cookie_header)
            session_id = cookies[SESSION_COOKIE].value if SESSION_COOKIE in cookies else ""
        except (CookieError, KeyError):
            return None
        if not session_id:
            return None
        now = time.monotonic()
        with self._lock:
            self._prune_locked(now)
            session = self._sessions.get(session_id)
        if session is None:
            return None
        return CommandCenterIdentity(
            mode=session.mode,
            session_id=session_id,
            csrf_token=session.csrf_token,
            email=session.email,
            subject=session.subject,
        )

    def csrf_valid(self, identity: CommandCenterIdentity, headers: Message) -> bool:
        if identity.mode == "internal_bearer":
            return True
        supplied = str(headers.get(CSRF_HEADER) or "").strip()
        return bool(supplied) and hmac.compare_digest(supplied, identity.csrf_token)

    def _prune_locked(self, now: float) -> None:
        expired = [key for key, record in self._sessions.items() if record.expires_at <= now]
        for key in expired:
            self._sessions.pop(key, None)
        expired_states = [key for key, record in self._oauth_states.items() if record.expires_at <= now]
        for key in expired_states:
            self._oauth_states.pop(key, None)

    def _consume_oauth_state(self, *, state: str, cookie_header: str) -> None:
        clean_state = str(state or "").strip()
        cookie_state = _cookie_value(cookie_header, OAUTH_STATE_COOKIE)
        if not clean_state or not cookie_state or not hmac.compare_digest(clean_state, cookie_state):
            raise GoogleOAuthError("Google OAuth state validation failed")
        now = time.monotonic()
        with self._lock:
            self._prune_locked(now)
            record = self._oauth_states.pop(clean_state, None)
        if record is None or record.expires_at <= now:
            raise GoogleOAuthError("Google OAuth state is invalid, expired, or already used")

    def _cookie(
        self,
        name: str,
        value: str,
        *,
        max_age: int,
        path: str = "/",
        http_only: bool = False,
    ) -> str:
        parts = [
            f"{name}={value}",
            f"Path={path}",
            f"Max-Age={max(0, int(max_age))}",
            "SameSite=Lax",
        ]
        if http_only:
            parts.append("HttpOnly")
        if self.secure_cookies:
            parts.append("Secure")
        return "; ".join(parts)

    def _clear_cookie(self, name: str, *, path: str = "/", http_only: bool = False) -> str:
        return self._cookie(name, "", max_age=0, path=path, http_only=http_only)


def read_command_center_bearer(path: str | os.PathLike[str]) -> str:
    """Read the internal bearer for a trusted local bridge/supervisor client."""

    try:
        token = _expanded_path(path).read_text(encoding="utf-8").strip()
    except OSError:
        return ""
    return token if len(token) >= 32 else ""


def _read_trusted_bearer(path: Path) -> str:
    try:
        token = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise GoogleOAuthConfigurationError(
            "The trusted Command Center proxy bearer is unavailable"
        ) from exc
    if not 32 <= len(token) <= 512 or any(character.isspace() for character in token):
        raise GoogleOAuthConfigurationError(
            "The trusted Command Center proxy bearer is invalid"
        )
    return token


def _cookie_value(cookie_header: str, name: str) -> str:
    try:
        cookies = SimpleCookie()
        cookies.load(str(cookie_header or ""))
        return cookies[name].value if name in cookies else ""
    except (CookieError, KeyError):
        return ""


def _validated_web_url(value: str, *, setting_name: str, allow_path: bool) -> urllib.parse.ParseResult:
    try:
        parsed = urllib.parse.urlparse(value)
        port = parsed.port
    except (ValueError, TypeError) as exc:
        raise GoogleOAuthConfigurationError(f"{setting_name} is not a valid URL") from exc
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise GoogleOAuthConfigurationError(f"{setting_name} must be an absolute HTTP(S) URL")
    if parsed.username or parsed.password:
        raise GoogleOAuthConfigurationError(f"{setting_name} must not include user information")
    if parsed.fragment:
        raise GoogleOAuthConfigurationError(f"{setting_name} must not include a fragment")
    if not allow_path and (parsed.path not in {"", "/"} or parsed.query):
        raise GoogleOAuthConfigurationError(f"{setting_name} must be an origin without a path or query")
    if port is not None and not 1 <= port <= 65535:
        raise GoogleOAuthConfigurationError(f"{setting_name} contains an invalid port")
    return parsed


def _url_origin(parsed: urllib.parse.ParseResult) -> str:
    host = (parsed.hostname or "").casefold()
    if ":" in host:
        host = f"[{host}]"
    port = parsed.port
    default_port = 443 if parsed.scheme == "https" else 80
    port_suffix = f":{port}" if port is not None and port != default_port else ""
    return f"{parsed.scheme.casefold()}://{host}{port_suffix}"


def _is_loopback_hostname(hostname: str) -> bool:
    clean = str(hostname or "").strip().casefold()
    if clean == "localhost":
        return True
    try:
        import ipaddress

        return ipaddress.ip_address(clean).is_loopback
    except ValueError:
        return False


def _expanded_path(path: str | os.PathLike[str]) -> Path:
    return Path(os.path.expandvars(os.path.expanduser(str(path)))).resolve()


def _write_private_token(path: Path, token: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{secrets.token_hex(6)}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(token)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, stat.S_IRUSR | stat.S_IWUSR)
        _harden_windows_acl(temporary)
        os.replace(temporary, path)
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
        _harden_windows_acl(path)
    finally:
        try:
            temporary.unlink()
        except OSError:
            pass


def _harden_windows_acl(path: Path) -> None:
    if os.name != "nt":
        return
    try:
        identity = subprocess.check_output(
            ["whoami"],
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
        ).strip()
    except (OSError, subprocess.SubprocessError):
        identity = getpass.getuser()
    grants = [f"{identity}:(R,W)", "*S-1-5-18:(F)", "*S-1-5-32-544:(F)"]
    result = subprocess.run(
        ["icacls", str(path), "/inheritance:r", "/grant:r", *grants],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if result.returncode != 0:
        raise OSError("Unable to restrict the Command Center bearer file ACL")
    subprocess.run(
        ["icacls", str(path), "/remove:g", "CodexSandboxUsers"],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
