"""Fail-closed scaffolding for brokered, non-exportable credential use.

This module deliberately does not expose a ``get_secret`` API.  An untrusted
caller may request only a configured operation.  Trusted, code-registered
handlers receive a short-lived :class:`SecretLease` and return operation data.
For a hard security boundary the broker must run outside the agent's OS
identity/process; this module is the contract for that service boundary.
"""

from __future__ import annotations

import math
import os
import re
import threading
import time
from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from types import MappingProxyType
from typing import Any, Protocol, TypeVar, runtime_checkable

import yaml

# AgentChat/direct_codex 2026-07-14T17:58:00Z: fail closed on Salesforce and Maxio/Chargify record deletion.
# AgentChat/direct_codex 2026-07-22T00:00:00-04:00: allow scoped lane writes while keeping credential and permission administration unavailable.


class SecretBrokerError(RuntimeError):
    """Base class for safe-to-return broker errors."""


class SecretBrokerConfigError(ValueError):
    """Raised when broker configuration fails closed."""


class BrokerDisabledError(SecretBrokerError):
    """Raised when the broker has not been explicitly enabled."""


class OperationNotAllowedError(SecretBrokerError):
    """Raised for an unknown, disabled, or malformed operation request."""


class ProviderUnavailableError(SecretBrokerError):
    """Raised when an approved credential provider cannot issue a lease."""


class OperationFailedError(SecretBrokerError):
    """Raised without carrying provider or handler exception details."""


_T = TypeVar("_T")
_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_.-]{1,127}$")
_REQUEST_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_ARGUMENT_NAME = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_RESOURCE_ID = re.compile(r"^[A-Za-z0-9_-]{1,255}$")
_ENVIRONMENT_NAME = re.compile(r"^[A-Z_][A-Z0-9_]{0,127}$")
_PROJECT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9:._-]{0,127}$")
_MAX_RESPONSE_BYTES = 256 * 1024
_MAX_RESPONSE_DEPTH = 12
_MAX_RESPONSE_ITEMS = 4096
_ENFORCED_READ_ONLY_SOURCE_TYPES = frozenset(
    {
        "agent-handoff-read-only",
        "ops-salesforce-ticket-investigation",
    }
)
_READ_ONLY_OPERATION_TOKENS = frozenset(
    {
        "audit",
        "check",
        "describe",
        "find",
        "get",
        "inspect",
        "inventory",
        "list",
        "lookup",
        "preview",
        "query",
        "read",
        "report",
        "resolve",
        "search",
        "select",
        "status",
        "verify",
    }
)
_MUTATING_OPERATION_TOKENS = frozenset(
    {
        "apply",
        "assign",
        "cancel",
        "cancellation",
        "charge",
        "close",
        "closure",
        "create",
        "credit",
        "deliver",
        "edit",
        "email",
        "insert",
        "patch",
        "post",
        "put",
        "reactivate",
        "refund",
        "send",
        "submit",
        "sync",
        "update",
        "upload",
        "void",
        "write",
    }
)

_LITERAL_SECRET_FIELDS = {
    "api_key",
    "access_token",
    "client_secret",
    "credential_json",
    "credentials_json",
    "password",
    "passwd",
    "private_key",
    "refresh_token",
    "secret_value",
    "token",
    "value",
}
_EXECUTABLE_FIELDS = {
    "callable",
    "cmd",
    "command",
    "entrypoint",
    "executable",
    "function",
    "handler",
    "module",
    "powershell",
    "python",
    "script",
    "shell",
}


class SecretLease:
    """A zero-on-close credential lease for trusted operation handlers only."""

    __slots__ = ("_buffer", "_closed", "provider_id")

    def __init__(self, value: str | bytes | bytearray, *, provider_id: str) -> None:
        encoded = value.encode("utf-8") if isinstance(value, str) else bytes(value)
        if not encoded:
            raise ProviderUnavailableError("Credential provider returned an empty value")
        self._buffer = bytearray(encoded)
        self._closed = False
        self.provider_id = provider_id

    @property
    def closed(self) -> bool:
        return self._closed

    def use_text(self, consumer: Callable[[str], _T]) -> _T:
        """Use the leased value inside trusted code without returning it directly."""

        if self._closed:
            raise SecretBrokerError("Credential lease is closed")
        value = self._buffer.decode("utf-8")
        try:
            return consumer(value)
        finally:
            value = ""

    def close(self) -> None:
        if not self._closed:
            for index in range(len(self._buffer)):
                self._buffer[index] = 0
            self._buffer.clear()
            self._closed = True

    def _appears_in(self, value: str | bytes) -> bool:
        """Return whether a response scalar contains this lease's raw bytes."""

        if self._closed:
            raise SecretBrokerError("Credential lease is closed")
        candidate = value.encode("utf-8") if isinstance(value, str) else value
        return bool(self._buffer) and bytes(self._buffer) in candidate

    def __enter__(self) -> SecretLease:
        if self._closed:
            raise SecretBrokerError("Credential lease is closed")
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def __repr__(self) -> str:
        return f"<SecretLease provider={self.provider_id!r} value=<redacted> closed={self._closed}>"

    def __str__(self) -> str:
        return "<SecretLease redacted>"

    def __reduce__(self) -> object:
        raise TypeError("Secret leases cannot be serialized")


@dataclass(frozen=True, slots=True, repr=False)
class SecretReference:
    provider_id: str
    resource_id: str
    version: int | None = None

    def __repr__(self) -> str:
        return (
            f"<SecretReference provider={self.provider_id!r} "
            f"version_pinned={self.version is not None}>"
        )


@runtime_checkable
class SecretProvider(Protocol):
    """Provider contract implemented only inside the trusted broker process."""

    @property
    def provider_id(self) -> str: ...

    @property
    def kind(self) -> str: ...

    @property
    def enabled(self) -> bool: ...

    @property
    def initialized(self) -> bool: ...

    def lease(self, reference: SecretReference) -> SecretLease: ...


class EnvironmentSecretProvider:
    """Transitional local provider; it is never enabled implicitly."""

    kind = "environment_transitional"

    def __init__(
        self,
        provider_id: str,
        *,
        enabled: bool = False,
        environment: Mapping[str, str] | None = None,
    ) -> None:
        self._provider_id = provider_id
        self._enabled = enabled
        self._environment = environment if environment is not None else os.environ

    @property
    def provider_id(self) -> str:
        return self._provider_id

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def initialized(self) -> bool:
        return True

    def lease(self, reference: SecretReference) -> SecretLease:
        if not self.enabled:
            raise ProviderUnavailableError("Credential provider is disabled")
        if (
            reference.provider_id != self.provider_id
            or reference.version is not None
            or not _ENVIRONMENT_NAME.fullmatch(reference.resource_id)
        ):
            raise ProviderUnavailableError("Credential reference is invalid for this provider")
        value = self._environment.get(reference.resource_id)
        if not value:
            raise ProviderUnavailableError("Configured environment credential is unavailable")
        return SecretLease(value, provider_id=self.provider_id)

    def __repr__(self) -> str:
        return f"<EnvironmentSecretProvider id={self.provider_id!r} enabled={self.enabled}>"


class GoogleSecretManagerProvider:
    """Lazy Google Secret Manager provider requiring a numeric version pin."""

    kind = "google_secret_manager"

    def __init__(
        self,
        provider_id: str,
        project_id: str,
        *,
        enabled: bool = False,
        client_factory: Callable[[], Any] | None = None,
    ) -> None:
        self._provider_id = provider_id
        self._project_id = project_id
        self._enabled = enabled
        self._client_factory = client_factory
        self._client: Any | None = None
        self._lock = threading.Lock()

    @property
    def provider_id(self) -> str:
        return self._provider_id

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def initialized(self) -> bool:
        return self._client is not None

    def lease(self, reference: SecretReference) -> SecretLease:
        if not self.enabled:
            raise ProviderUnavailableError("Credential provider is disabled")
        if (
            reference.provider_id != self.provider_id
            or reference.version is None
            or reference.version < 1
            or not _RESOURCE_ID.fullmatch(reference.resource_id)
        ):
            raise ProviderUnavailableError("Google Secret Manager reference must use a pinned version")
        name = (
            f"projects/{self._project_id}/secrets/{reference.resource_id}"
            f"/versions/{reference.version}"
        )
        try:
            response = self._get_client().access_secret_version(request={"name": name})
            response_payload = response.payload
            payload = response_payload.data
            if not isinstance(payload, (bytes, bytearray)):
                raise ProviderUnavailableError("Google Secret Manager returned an invalid payload")
            expected_crc32c = getattr(response_payload, "data_crc32c", None)
            if expected_crc32c is not None:
                _verify_crc32c(bytes(payload), expected_crc32c)
        except ProviderUnavailableError:
            raise
        except Exception:
            raise ProviderUnavailableError("Google Secret Manager access failed") from None
        return SecretLease(payload, provider_id=self.provider_id)

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        with self._lock:
            if self._client is None:
                factory = self._client_factory
                if factory is None:
                    try:
                        from google.cloud import secretmanager  # type: ignore[import-not-found]
                    except ImportError:
                        raise ProviderUnavailableError(
                            "Google Secret Manager client library is not installed"
                        ) from None
                    factory = secretmanager.SecretManagerServiceClient
                try:
                    self._client = factory()
                except Exception:
                    raise ProviderUnavailableError(
                        "Google Secret Manager client initialization failed"
                    ) from None
        return self._client

    def __repr__(self) -> str:
        return (
            f"<GoogleSecretManagerProvider id={self.provider_id!r} "
            f"enabled={self.enabled} initialized={self.initialized}>"
        )


@dataclass(frozen=True, slots=True)
class ProviderDefinition:
    provider_id: str
    kind: str
    enabled: bool
    project_id: str | None = None


@dataclass(frozen=True, slots=True)
class OperationPolicy:
    name: str
    enabled: bool
    reference: SecretReference
    allowed_agents: frozenset[str]
    required_arguments: frozenset[str]
    optional_arguments: frozenset[str]


@dataclass(frozen=True, slots=True)
class BrokerConfig:
    enabled: bool
    providers: Mapping[str, ProviderDefinition]
    operations: Mapping[str, OperationPolicy]


@dataclass(frozen=True, slots=True, repr=False)
class OperationRequest:
    """Authenticated invocation metadata plus non-audited operation arguments.

    ``agent_name`` must be set by the broker's authenticated transport rather
    than accepted from agent-authored payload text.
    """

    operation: str
    agent_name: str
    job_id: str
    request_id: str
    arguments: Mapping[str, Any] = field(default_factory=dict)
    source_type: str = ""

    def __post_init__(self) -> None:
        if not _IDENTIFIER.fullmatch(self.operation):
            raise OperationNotAllowedError("Operation name is invalid")
        if not _IDENTIFIER.fullmatch(self.agent_name):
            raise OperationNotAllowedError("Agent name is invalid")
        if not _REQUEST_ID.fullmatch(self.job_id):
            raise OperationNotAllowedError("Job id is invalid")
        if not _REQUEST_ID.fullmatch(self.request_id):
            raise OperationNotAllowedError("Request id is invalid")
        if self.source_type and not _REQUEST_ID.fullmatch(self.source_type):
            raise OperationNotAllowedError("Source type is invalid")
        if not isinstance(self.arguments, Mapping) or not all(
            isinstance(key, str) for key in self.arguments
        ):
            raise OperationNotAllowedError("Operation arguments must be a string-keyed map")
        object.__setattr__(self, "arguments", MappingProxyType(dict(self.arguments)))

    def __repr__(self) -> str:
        return (
            f"<OperationRequest operation={self.operation!r} agent={self.agent_name!r} "
            f"job_id={self.job_id!r} request_id={self.request_id!r}>"
        )

    __str__ = __repr__


@dataclass(frozen=True, slots=True, repr=False)
class OperationResponse:
    operation: str
    agent_name: str
    job_id: str
    request_id: str
    data: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "data", MappingProxyType(dict(self.data)))

    def __repr__(self) -> str:
        return (
            f"<OperationResponse operation={self.operation!r} agent={self.agent_name!r} "
            f"job_id={self.job_id!r} request_id={self.request_id!r}>"
        )

    __str__ = __repr__


class OperationHandler(Protocol):
    def __call__(
        self, request: OperationRequest, credential: SecretLease
    ) -> Mapping[str, Any]: ...


@dataclass(frozen=True, slots=True)
class AuditEvent:
    occurred_at: str
    agent_name: str
    job_id: str
    request_id: str
    operation: str
    provider_id: str | None
    outcome: str
    duration_ms: int


@dataclass(frozen=True, slots=True)
class ProviderStatus:
    provider_id: str
    kind: str
    enabled: bool
    initialized: bool


@dataclass(frozen=True, slots=True)
class BrokerStatus:
    enabled: bool
    provider_count: int
    operation_count: int
    registered_handler_count: int
    providers: tuple[ProviderStatus, ...]


class SecretBroker:
    """Invoke code-registered operations; never return a credential directly."""

    def __init__(
        self,
        config: BrokerConfig,
        providers: Mapping[str, SecretProvider],
        handlers: Mapping[str, OperationHandler],
        *,
        audit_sink: Callable[[AuditEvent], None] | None = None,
        audit_capacity: int = 1000,
    ) -> None:
        if audit_capacity < 1:
            raise ValueError("audit_capacity must be positive")
        unknown_handlers = set(handlers) - set(config.operations)
        if unknown_handlers:
            raise SecretBrokerConfigError("A handler is registered outside the operation allowlist")
        for provider_id, provider in providers.items():
            definition = config.providers.get(provider_id)
            if (
                definition is None
                or provider.provider_id != provider_id
                or provider.kind != definition.kind
            ):
                raise SecretBrokerConfigError("Provider registration does not match configuration")
        missing = {
            policy.reference.provider_id
            for policy in config.operations.values()
            if policy.reference.provider_id not in providers
        }
        if missing:
            raise SecretBrokerConfigError("An operation references an unavailable provider")
        self._config = config
        self._providers = dict(providers)
        self._handlers = dict(handlers)
        self._audit_sink = audit_sink
        self._audit: deque[AuditEvent] = deque(maxlen=audit_capacity)
        self._audit_lock = threading.Lock()

    def status(self) -> BrokerStatus:
        """Return fixed metadata only; never query or identify a secret."""

        providers = tuple(
            ProviderStatus(
                provider_id=provider_id,
                kind=self._config.providers[provider_id].kind,
                enabled=bool(provider.enabled),
                initialized=bool(provider.initialized),
            )
            for provider_id, provider in sorted(self._providers.items())
        )
        return BrokerStatus(
            enabled=self._config.enabled,
            provider_count=len(self._providers),
            operation_count=len(self._config.operations),
            registered_handler_count=len(self._handlers),
            providers=providers,
        )

    def audit_events(self) -> tuple[AuditEvent, ...]:
        with self._audit_lock:
            return tuple(self._audit)

    def invoke(self, request: OperationRequest) -> OperationResponse:
        started = time.monotonic()
        policy = self._config.operations.get(request.operation)
        provider_id = policy.reference.provider_id if policy else None
        try:
            if not self._config.enabled:
                raise BrokerDisabledError("Secret broker is disabled")
            if policy is None or not policy.enabled:
                raise OperationNotAllowedError("Operation is not allowlisted")
            if request.agent_name not in policy.allowed_agents:
                raise OperationNotAllowedError("Agent is not allowed to invoke this operation")
            if _is_forbidden_service_delete_request(
                request.operation,
                request.arguments,
                policy.reference.resource_id,
            ):
                raise OperationNotAllowedError(
                    "Salesforce and Maxio/Chargify record deletion is permanently denied"
                )
            if _is_enforced_read_only_operation_request(request):
                raise OperationNotAllowedError(
                    "This automatic ticket investigation and every inherited handoff are read-only; "
                    "an explicit operator-approved job is required for external writes"
                )
            self._validate_arguments(policy, request.arguments)
            handler = self._handlers.get(policy.name)
            if handler is None:
                raise OperationNotAllowedError("Operation handler is not registered")
            provider = self._providers[policy.reference.provider_id]
            with provider.lease(policy.reference) as credential:
                try:
                    data = handler(request, credential)
                    _validate_response_data(data, credential)
                except Exception:
                    raise OperationFailedError("Brokered operation failed") from None
            response = OperationResponse(
                request.operation,
                request.agent_name,
                request.job_id,
                request.request_id,
                data,
            )
        except (BrokerDisabledError, OperationNotAllowedError) as exc:
            self._record_audit(request, provider_id, "denied", started)
            raise exc
        except ProviderUnavailableError:
            self._record_audit(request, provider_id, "provider_unavailable", started)
            raise ProviderUnavailableError("Credential provider is unavailable") from None
        except OperationFailedError as exc:
            self._record_audit(request, provider_id, "failed", started)
            raise exc
        except Exception:
            self._record_audit(request, provider_id, "failed", started)
            raise OperationFailedError("Brokered operation failed") from None
        self._record_audit(request, provider_id, "succeeded", started)
        return response

    @staticmethod
    def _validate_arguments(policy: OperationPolicy, arguments: Mapping[str, Any]) -> None:
        supplied = set(arguments)
        if not policy.required_arguments.issubset(supplied):
            raise OperationNotAllowedError("Required operation argument is missing")
        allowed = policy.required_arguments | policy.optional_arguments
        if not supplied.issubset(allowed):
            raise OperationNotAllowedError("Operation argument is not allowlisted")

    def _record_audit(
        self,
        request: OperationRequest,
        provider_id: str | None,
        outcome: str,
        started: float,
    ) -> None:
        event = AuditEvent(
            occurred_at=datetime.now(UTC).isoformat(),
            agent_name=request.agent_name,
            job_id=request.job_id,
            request_id=request.request_id,
            operation=request.operation,
            provider_id=provider_id,
            outcome=outcome,
            duration_ms=max(0, round((time.monotonic() - started) * 1000)),
        )
        with self._audit_lock:
            self._audit.append(event)
        if self._audit_sink is not None:
            try:
                self._audit_sink(event)
            except Exception:
                pass


def load_secret_broker_config(source: str | os.PathLike[str] | Mapping[str, Any]) -> BrokerConfig:
    """Load and strictly validate a secret-free broker policy."""

    if isinstance(source, Mapping):
        raw: Any = dict(source)
    else:
        path = Path(source)
        if not path.exists():
            raise FileNotFoundError(f"Secret broker config not found: {path}")
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    root = _as_map(raw, "config")
    _reject_forbidden_fields(root)
    _reject_unknown_fields(root, {"schema_version", "enabled", "providers", "operations"}, "config")
    if root.get("schema_version") != 1:
        raise SecretBrokerConfigError("schema_version must be 1")
    enabled = _as_bool(root.get("enabled", False), "config.enabled")

    provider_rows = _as_map(root.get("providers", {}), "config.providers")
    providers: dict[str, ProviderDefinition] = {}
    for provider_id, value in provider_rows.items():
        _validate_identifier(provider_id, "provider id")
        row = _as_map(value, f"providers.{provider_id}")
        kind = row.get("type")
        if kind == "google_secret_manager":
            _reject_unknown_fields(row, {"type", "enabled", "project_id"}, f"providers.{provider_id}")
            project_id = _required_string(row.get("project_id"), f"providers.{provider_id}.project_id")
            if not _PROJECT_ID.fullmatch(project_id):
                raise SecretBrokerConfigError("Google Secret Manager project id is invalid")
            providers[provider_id] = ProviderDefinition(
                provider_id,
                kind,
                _as_bool(row.get("enabled", False), f"providers.{provider_id}.enabled"),
                project_id,
            )
        elif kind == "environment":
            _reject_unknown_fields(row, {"type", "enabled", "transitional"}, f"providers.{provider_id}")
            if row.get("transitional") is not True:
                raise SecretBrokerConfigError("Environment providers must be marked transitional")
            providers[provider_id] = ProviderDefinition(
                provider_id,
                "environment_transitional",
                _as_bool(row.get("enabled", False), f"providers.{provider_id}.enabled"),
            )
        else:
            raise SecretBrokerConfigError("Provider type is not supported")

    operation_rows = _as_map(root.get("operations", {}), "config.operations")
    operations: dict[str, OperationPolicy] = {}
    for operation_name, value in operation_rows.items():
        _validate_identifier(operation_name, "operation")
        if _is_secret_export_operation(operation_name):
            raise SecretBrokerConfigError("Generic secret retrieval operations are forbidden")
        row = _as_map(value, f"operations.{operation_name}")
        _reject_unknown_fields(
            row,
            {"enabled", "provider", "reference", "allowed_agents", "arguments"},
            f"operations.{operation_name}",
        )
        provider_id = _required_string(row.get("provider"), f"operations.{operation_name}.provider")
        definition = providers.get(provider_id)
        if definition is None:
            raise SecretBrokerConfigError("Operation references an unknown provider")
        reference_row = _as_map(row.get("reference"), f"operations.{operation_name}.reference")
        if definition.kind == "google_secret_manager":
            _reject_unknown_fields(
                reference_row, {"secret_id", "version"}, f"operations.{operation_name}.reference"
            )
            resource_id = _required_string(
                reference_row.get("secret_id"), f"operations.{operation_name}.reference.secret_id"
            )
            if not _RESOURCE_ID.fullmatch(resource_id):
                raise SecretBrokerConfigError("Google Secret Manager secret id is invalid")
            version = _pinned_version(reference_row.get("version"))
        else:
            _reject_unknown_fields(
                reference_row,
                {"environment_variable"},
                f"operations.{operation_name}.reference",
            )
            resource_id = _required_string(
                reference_row.get("environment_variable"),
                f"operations.{operation_name}.reference.environment_variable",
            )
            if not _ENVIRONMENT_NAME.fullmatch(resource_id):
                raise SecretBrokerConfigError("Environment variable name is invalid")
            version = None
        if _is_forbidden_service_delete_request(operation_name, {}, resource_id):
            raise SecretBrokerConfigError(
                "Salesforce and Maxio/Chargify record deletion operations are forbidden"
            )
        arguments = _as_map(row.get("arguments", {}), f"operations.{operation_name}.arguments")
        _reject_unknown_fields(arguments, {"required", "optional"}, f"operations.{operation_name}.arguments")
        required = _argument_set(arguments.get("required", []), "required argument")
        optional = _argument_set(arguments.get("optional", []), "optional argument")
        if required & optional:
            raise SecretBrokerConfigError("Operation argument cannot be both required and optional")
        allowed_agents = _identifier_set(
            row.get("allowed_agents"), f"operations.{operation_name}.allowed_agents"
        )
        operations[operation_name] = OperationPolicy(
            name=operation_name,
            enabled=_as_bool(row.get("enabled", False), f"operations.{operation_name}.enabled"),
            reference=SecretReference(provider_id, resource_id, version),
            allowed_agents=allowed_agents,
            required_arguments=required,
            optional_arguments=optional,
        )

    return BrokerConfig(
        enabled=enabled,
        providers=MappingProxyType(providers),
        operations=MappingProxyType(operations),
    )


def build_secret_broker(
    source: str | os.PathLike[str] | Mapping[str, Any],
    handlers: Mapping[str, OperationHandler],
    *,
    environment: Mapping[str, str] | None = None,
    google_client_factories: Mapping[str, Callable[[], Any]] | None = None,
    provider_overrides: Mapping[str, SecretProvider] | None = None,
    audit_sink: Callable[[AuditEvent], None] | None = None,
) -> SecretBroker:
    """Build providers lazily from validated configuration."""

    config = load_secret_broker_config(source)
    overrides = dict(provider_overrides or {})
    if set(overrides) - set(config.providers):
        raise SecretBrokerConfigError("Provider override is not configured")
    factories = google_client_factories or {}
    if set(factories) - set(config.providers):
        raise SecretBrokerConfigError("Google client factory is not configured")
    providers: dict[str, SecretProvider] = {}
    for provider_id, definition in config.providers.items():
        if provider_id in overrides:
            providers[provider_id] = overrides[provider_id]
        elif definition.kind == "google_secret_manager":
            providers[provider_id] = GoogleSecretManagerProvider(
                provider_id,
                definition.project_id or "",
                enabled=definition.enabled,
                client_factory=factories.get(provider_id),
            )
        else:
            providers[provider_id] = EnvironmentSecretProvider(
                provider_id,
                enabled=definition.enabled,
                environment=environment,
            )
    return SecretBroker(config, providers, handlers, audit_sink=audit_sink)


def _verify_crc32c(payload: bytes, expected: Any) -> None:
    """Verify Secret Manager's integrity field without an eager dependency."""

    try:
        import google_crc32c  # type: ignore[import-not-found]
    except ImportError:
        raise ProviderUnavailableError("CRC32C verification support is unavailable") from None
    try:
        if isinstance(expected, bool):
            raise ValueError
        expected_value = int(expected)
        actual_value = int(google_crc32c.value(payload))
    except Exception:
        raise ProviderUnavailableError("Google Secret Manager returned invalid CRC32C metadata") from None
    if expected_value < 0 or actual_value != expected_value:
        raise ProviderUnavailableError("Google Secret Manager payload integrity check failed")


def _validate_response_data(data: Any, credential: SecretLease) -> None:
    """Accept bounded JSON-like data and reject accidental credential export."""

    if not isinstance(data, Mapping):
        raise OperationFailedError("Brokered operation returned an invalid response")
    total_bytes = 0
    total_items = 0
    active_containers: set[int] = set()

    def account(size: int) -> None:
        nonlocal total_bytes, total_items
        total_bytes += size + 8
        total_items += 1
        if total_bytes > _MAX_RESPONSE_BYTES or total_items > _MAX_RESPONSE_ITEMS:
            raise OperationFailedError("Brokered operation response exceeds its size limit")

    def visit(value: Any, depth: int) -> None:
        if depth > _MAX_RESPONSE_DEPTH:
            raise OperationFailedError("Brokered operation response is too deeply nested")
        if isinstance(value, str):
            encoded = value.encode("utf-8")
            if credential._appears_in(value):
                raise OperationFailedError("Brokered operation attempted to export a credential")
            account(len(encoded))
            return
        if isinstance(value, bytes):
            if credential._appears_in(value):
                raise OperationFailedError("Brokered operation attempted to export a credential")
            account(len(value))
            return
        if value is None or isinstance(value, bool):
            account(1)
            return
        if isinstance(value, int):
            account(max(1, (abs(value).bit_length() + 7) // 8))
            return
        if isinstance(value, float):
            if not math.isfinite(value):
                raise OperationFailedError("Brokered operation returned a non-finite number")
            account(8)
            return
        if isinstance(value, Mapping):
            identity = id(value)
            if identity in active_containers:
                raise OperationFailedError("Brokered operation returned a cyclic response")
            active_containers.add(identity)
            account(0)
            try:
                for key, child in value.items():
                    if not isinstance(key, str):
                        raise OperationFailedError(
                            "Brokered operation response keys must be strings"
                        )
                    visit(key, depth + 1)
                    visit(child, depth + 1)
            finally:
                active_containers.remove(identity)
            return
        if isinstance(value, (list, tuple)):
            identity = id(value)
            if identity in active_containers:
                raise OperationFailedError("Brokered operation returned a cyclic response")
            active_containers.add(identity)
            account(0)
            try:
                for child in value:
                    visit(child, depth + 1)
            finally:
                active_containers.remove(identity)
            return
        raise OperationFailedError("Brokered operation returned an unsupported response type")

    visit(data, 0)


def _reject_forbidden_fields(value: Any, path: str = "config") -> None:
    if isinstance(value, Mapping):
        for raw_key, child in value.items():
            if not isinstance(raw_key, str):
                raise SecretBrokerConfigError(f"{path} contains a non-string field")
            normalized = raw_key.strip().lower().replace("-", "_")
            if normalized in _LITERAL_SECRET_FIELDS:
                raise SecretBrokerConfigError(f"Literal secret field is forbidden: {path}.{raw_key}")
            if normalized in _EXECUTABLE_FIELDS:
                raise SecretBrokerConfigError(f"Executable field is forbidden: {path}.{raw_key}")
            _reject_forbidden_fields(child, f"{path}.{raw_key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_forbidden_fields(child, f"{path}[{index}]")


def _is_secret_export_operation(name: str) -> bool:
    tokens = set(re.split(r"[._-]+", name.lower()))
    if tokens & {"secret", "secrets", "credential", "credentials"} and tokens & {
        "access",
        "dump",
        "export",
        "get",
        "read",
        "reveal",
        "show",
    }:
        return True
    collapsed = re.sub(r"[._-]", "", name.lower())
    return any(
        marker in collapsed
        for marker in (
            "getsecret",
            "readsecret",
            "revealsecret",
            "exportsecret",
            "getcredential",
        )
    )


def _is_forbidden_service_delete_request(
    operation: str,
    arguments: Mapping[str, Any],
    credential_resource: str,
) -> bool:
    service_text = f"{operation} {credential_resource}".lower()
    if not any(marker in service_text for marker in ("salesforce", "chargify", "maxio")):
        return False

    destructive = {
        "delete",
        "destroy",
        "erase",
        "harddelete",
        "hard_delete",
        "purge",
        "emptyrecyclebin",
        "empty_recycle_bin",
    }
    operation_tokens = set(re.split(r"[._:/-]+", operation.lower()))
    collapsed_operation = re.sub(r"[._:/-]", "", operation.lower())
    if operation_tokens & destructive or any(token in collapsed_operation for token in destructive):
        return True

    def contains_delete(value: Any, key: str = "") -> bool:
        normalized_key = key.strip().lower().replace("-", "_")
        if isinstance(value, Mapping):
            return any(contains_delete(child, str(child_key)) for child_key, child in value.items())
        if isinstance(value, (list, tuple)):
            return any(contains_delete(child, key) for child in value)
        if not isinstance(value, str):
            return False
        normalized = value.strip().lower()
        collapsed = re.sub(r"[\s._:/-]", "", normalized)
        if normalized_key in {"method", "http_method"} and normalized == "delete":
            return True
        if normalized_key in {"action", "operation", "mode"} and (
            normalized in destructive or collapsed in destructive
        ):
            return True
        if normalized_key in {"body", "payload", "path", "relative_path", "url"}:
            return bool(
                re.search(
                    r"(?:^|[/{\s\"':._-])(delete|destroy|erase|hard[_-]?delete|purge|empty[_-]?recycle[_-]?bin)(?:$|[}/?&\s\"':._-])",
                    normalized,
                )
            )
        return False

    return contains_delete(arguments)


def _is_enforced_read_only_operation_request(
    request: OperationRequest,
) -> bool:
    """Fail closed on brokered writes from automatic ticket review authority."""

    if str(request.source_type or "").strip().lower() not in _ENFORCED_READ_ONLY_SOURCE_TYPES:
        return False

    operation_tokens = {
        token
        for token in re.split(r"[^a-z0-9]+", str(request.operation or "").lower())
        if token
    }
    explicit_http_read = False

    def arguments_request_mutation(value: Any, key: str = "") -> bool:
        nonlocal explicit_http_read
        normalized_key = str(key or "").strip().lower().replace("-", "_")
        if isinstance(value, Mapping):
            return any(
                arguments_request_mutation(child, str(child_key))
                for child_key, child in value.items()
            )
        if isinstance(value, (list, tuple)):
            return any(arguments_request_mutation(child, key) for child in value)
        if not isinstance(value, str):
            return False

        normalized = value.strip().lower()
        if normalized_key in {"method", "http_method"}:
            if normalized in {"get", "head", "options"}:
                explicit_http_read = True
                return False
            return True
        if normalized_key in {"action", "mode", "operation"}:
            value_tokens = {
                token for token in re.split(r"[^a-z0-9]+", normalized) if token
            }
            return bool(value_tokens & _MUTATING_OPERATION_TOKENS)
        return False

    if arguments_request_mutation(request.arguments):
        return True
    if explicit_http_read:
        return False
    if "preview" in operation_tokens:
        return False
    if operation_tokens & _MUTATING_OPERATION_TOKENS:
        return True
    if operation_tokens & _READ_ONLY_OPERATION_TOKENS:
        return False

    # Broker operations are credential-bearing external calls. An unknown
    # operation is therefore denied for this source instead of guessing that
    # it is safe from its resource name or caller-supplied arguments.
    return True


def _pinned_version(value: Any) -> int:
    if isinstance(value, bool):
        raise SecretBrokerConfigError("Secret version must be a positive numeric pin")
    if isinstance(value, int):
        version = value
    elif isinstance(value, str) and value.isascii() and value.isdigit():
        version = int(value)
    else:
        raise SecretBrokerConfigError("Secret version must be a positive numeric pin; latest is forbidden")
    if version < 1:
        raise SecretBrokerConfigError("Secret version must be a positive numeric pin")
    return version


def _argument_set(value: Any, label: str) -> frozenset[str]:
    if not isinstance(value, list):
        raise SecretBrokerConfigError(f"{label} list is invalid")
    names: set[str] = set()
    for name in value:
        if not isinstance(name, str) or not _ARGUMENT_NAME.fullmatch(name):
            raise SecretBrokerConfigError(f"{label} name is invalid")
        if name in names:
            raise SecretBrokerConfigError(f"{label} is duplicated")
        names.add(name)
    return frozenset(names)


def _identifier_set(value: Any, path: str) -> frozenset[str]:
    if not isinstance(value, list) or not value:
        raise SecretBrokerConfigError(f"{path} must be a non-empty list")
    names: set[str] = set()
    for name in value:
        if not isinstance(name, str) or not _IDENTIFIER.fullmatch(name):
            raise SecretBrokerConfigError(f"{path} contains an invalid agent name")
        if name in names:
            raise SecretBrokerConfigError(f"{path} contains a duplicate agent name")
        names.add(name)
    return frozenset(names)


def _validate_identifier(value: Any, label: str) -> None:
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
        raise SecretBrokerConfigError(f"{label} is invalid")


def _as_map(value: Any, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise SecretBrokerConfigError(f"{path} must be a map")
    if not all(isinstance(key, str) for key in value):
        raise SecretBrokerConfigError(f"{path} must have string fields")
    return value


def _as_bool(value: Any, path: str) -> bool:
    if not isinstance(value, bool):
        raise SecretBrokerConfigError(f"{path} must be true or false")
    return value


def _required_string(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise SecretBrokerConfigError(f"{path} must be a non-empty string")
    return value


def _reject_unknown_fields(value: Mapping[str, Any], allowed: set[str], path: str) -> None:
    if set(value) - allowed:
        raise SecretBrokerConfigError(f"{path} contains an unsupported field")
