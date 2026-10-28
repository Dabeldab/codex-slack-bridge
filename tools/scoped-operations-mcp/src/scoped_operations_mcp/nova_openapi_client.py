from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Any
from urllib.parse import urlparse

import requests


EXACT_USERNAME = re.compile(r"^[A-Za-z0-9_]{1,80}$")
ALLOWED_API_HOSTS = frozenset({"openapi.novapointofsale.com"})
DEFAULT_BASE_URL = "https://openapi.novapointofsale.com"


class NovaOpenApiScopeError(ValueError):
    """A request exceeded the fixed read-only Nova OpenAPI scope."""


class NovaOpenApiUnavailableError(RuntimeError):
    """The Nova OpenAPI provider or configured tenant credential is unavailable."""


@dataclass(frozen=True)
class NovaOpenApiSettings:
    base_url: str = DEFAULT_BASE_URL
    username: str = ""
    password: str = ""
    timeout_seconds: int = 20

    @classmethod
    def from_environment(cls) -> "NovaOpenApiSettings":
        base_url = str(os.getenv("NOVA_OPENAPI_BASE_URL") or DEFAULT_BASE_URL).strip().rstrip("/")
        username = str(os.getenv("NOVA_OPENAPI_USERNAME") or "").strip()
        password = str(os.getenv("NOVA_OPENAPI_PASSWORD") or "")
        credential_file = str(os.getenv("NOVA_OPENAPI_CREDENTIAL_FILE") or "").strip()
        if credential_file:
            path = Path(os.path.expandvars(os.path.expanduser(credential_file))).resolve()
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError, TypeError) as exc:
                raise NovaOpenApiUnavailableError("Nova OpenAPI credential file could not be loaded") from exc
            if not isinstance(payload, dict):
                raise NovaOpenApiUnavailableError("Nova OpenAPI credential file must contain one object")
            username = str(payload.get("username") or "").strip()
            password = str(payload.get("password") or "")
        return cls(
            base_url=base_url,
            username=username,
            password=password,
            timeout_seconds=max(5, min(int(os.getenv("NOVA_OPENAPI_TIMEOUT_SECONDS") or 20), 60)),
        )


class ScopedNovaOpenApiClient:
    """Read-only, exact-tenant client for the published Nova OpenAPI surface."""

    def __init__(
        self,
        settings: NovaOpenApiSettings | None = None,
        *,
        session: requests.Session | None = None,
    ) -> None:
        self.settings = settings or NovaOpenApiSettings.from_environment()
        parsed = urlparse(self.settings.base_url)
        if parsed.scheme != "https" or parsed.hostname not in ALLOWED_API_HOSTS or parsed.query or parsed.fragment:
            raise NovaOpenApiScopeError("Nova OpenAPI base URL is not an approved production endpoint")
        self.session = session or requests.Session()
        self._token = ""
        self._tenant_id = ""
        self._expires_at = 0.0
        self._lock = RLock()

    def capability_status(self) -> dict[str, Any]:
        return {
            "ok": True,
            "accessMode": "typed_read_only",
            "baseUrl": self.settings.base_url,
            "credentialsConfigured": bool(self.settings.username and self.settings.password),
            "configuredCompanyUsername": self.settings.username if self.settings.username else "",
            "allowedOperations": [
                "health",
                "preflight",
                "regions",
                "locations_by_region",
                "location_general_settings",
                "location_preferences",
                "customers",
                "customer",
                "products",
                "product",
                "inventory",
                "invoices",
                "invoice",
                "invoice_payments",
                "users",
            ],
            "writeExposed": False,
            "deleteExposed": False,
            "fallback": "Use bounded Nova SQL reads when an exact tenant API preflight is unavailable.",
        }

    def health(self) -> dict[str, Any]:
        response = self._raw_request("GET", "/api/health", authenticated=False)
        payload = _json_object(response)
        return {
            "ok": response.status_code == 200,
            "statusCode": response.status_code,
            "providerStatus": _short(payload.get("status"), 80),
            "message": _short(payload.get("message"), 240),
        }

    def preflight(self, company_username: str) -> dict[str, Any]:
        username = self._exact_tenant(company_username)
        _token, tenant_id = self._authenticate(username, force=True)
        regions = self._get(username, "/api/regions")
        region_rows = _rows(regions)
        return {
            "ok": True,
            "companyUsername": username,
            "tenantId": tenant_id,
            "regionCount": len(region_rows),
            "readVerified": True,
            "accessMode": "typed_read_only",
        }

    def regions(self, company_username: str) -> dict[str, Any]:
        username = self._exact_tenant(company_username)
        payload = self._get(username, "/api/regions")
        return _read_result(username, "regions", payload)

    def locations_by_region(self, company_username: str, region_id: int, *, include_all: bool = False) -> dict[str, Any]:
        username = self._exact_tenant(company_username)
        region = _positive_int(region_id, "region_id")
        payload = self._get(
            username,
            f"/api/locations/{region}/locationsbyregion",
            params={"all": bool(include_all)},
        )
        return _read_result(username, "locations_by_region", payload)

    def location_general_settings(self, company_username: str, location_id: int) -> dict[str, Any]:
        return self._read_by_integer_id(company_username, "location_general_settings", "/api/locations/{id}/generalsettings", location_id)

    def location_preferences(self, company_username: str, location_id: int) -> dict[str, Any]:
        return self._read_by_integer_id(company_username, "location_preferences", "/api/locations/{id}/preferences", location_id)

    def customers(
        self,
        company_username: str,
        *,
        page_number: int = 1,
        page_size: int = 100,
        search_text: str = "",
        region_id: int | None = None,
        location_id: int | None = None,
    ) -> dict[str, Any]:
        params = _page_params(page_number, page_size)
        _optional_text(params, "searchText", search_text, 200)
        _optional_positive_int(params, "regionId", region_id)
        _optional_positive_int(params, "locationId", location_id)
        return self._paged(company_username, "customers", "/api/customers", params)

    def customer(self, company_username: str, customer_id: int) -> dict[str, Any]:
        return self._read_by_integer_id(company_username, "customer", "/api/customers/{id}", customer_id)

    def products(
        self,
        company_username: str,
        *,
        page_number: int = 1,
        page_size: int = 100,
        search_text: str = "",
        category_id: int | None = None,
    ) -> dict[str, Any]:
        params = _page_params(page_number, page_size)
        _optional_text(params, "searchText", search_text, 200)
        _optional_positive_int(params, "categoryId", category_id)
        return self._paged(company_username, "products", "/api/products", params)

    def product(self, company_username: str, product_id: int) -> dict[str, Any]:
        return self._read_by_integer_id(company_username, "product", "/api/products/{id}", product_id)

    def inventory(
        self,
        company_username: str,
        *,
        page_number: int = 1,
        page_size: int = 100,
        product_id: int | None = None,
        location_id: int | None = None,
        only_low_stock: bool = False,
    ) -> dict[str, Any]:
        params = _page_params(page_number, page_size)
        _optional_positive_int(params, "productId", product_id)
        _optional_positive_int(params, "locationId", location_id)
        if only_low_stock:
            params["onlyLowStock"] = True
        return self._paged(company_username, "inventory", "/api/inventory", params)

    def invoices(
        self,
        company_username: str,
        *,
        page_number: int = 1,
        page_size: int = 100,
        customer_id: int | None = None,
        location_id: int | None = None,
        region_id: int | None = None,
        start_date_utc: str = "",
        end_date_utc: str = "",
    ) -> dict[str, Any]:
        params = _page_params(page_number, page_size)
        _optional_positive_int(params, "customerId", customer_id)
        _optional_positive_int(params, "locationId", location_id)
        _optional_positive_int(params, "regionId", region_id)
        _optional_iso_timestamp(params, "startDateUtc", start_date_utc)
        _optional_iso_timestamp(params, "endDateUtc", end_date_utc)
        return self._paged(company_username, "invoices", "/api/invoices", params)

    def invoice(self, company_username: str, invoice_id: int) -> dict[str, Any]:
        return self._read_by_integer_id(company_username, "invoice", "/api/invoices/{id}", invoice_id)

    def invoice_payments(self, company_username: str, invoice_id: int) -> dict[str, Any]:
        return self._read_by_integer_id(company_username, "invoice_payments", "/api/invoices/{id}/payments", invoice_id)

    def users(
        self,
        company_username: str,
        *,
        page_number: int = 1,
        page_size: int = 100,
        search_text: str = "",
        region_id: int | None = None,
        is_employed: bool | None = None,
    ) -> dict[str, Any]:
        params = _page_params(page_number, page_size)
        _optional_text(params, "searchText", search_text, 200)
        _optional_positive_int(params, "regionId", region_id)
        if is_employed is not None:
            params["isEmployed"] = bool(is_employed)
        return self._paged(company_username, "users", "/api/users", params)

    def _read_by_integer_id(self, company_username: str, operation: str, template: str, value: int) -> dict[str, Any]:
        username = self._exact_tenant(company_username)
        identifier = _positive_int(value, operation + "_id")
        payload = self._get(username, template.format(id=identifier))
        return _read_result(username, operation, payload)

    def _paged(self, company_username: str, operation: str, path: str, params: dict[str, Any]) -> dict[str, Any]:
        username = self._exact_tenant(company_username)
        payload = self._get(username, path, params=params)
        return _read_result(username, operation, payload)

    def _exact_tenant(self, company_username: str) -> str:
        clean = str(company_username or "").strip()
        if not EXACT_USERNAME.fullmatch(clean):
            raise NovaOpenApiScopeError("company_username must be one exact Nova account name")
        if not self.settings.username or not self.settings.password:
            raise NovaOpenApiUnavailableError("Nova OpenAPI tenant credentials are not configured")
        if clean.casefold() != self.settings.username.casefold():
            raise NovaOpenApiScopeError("company_username does not match the configured Nova OpenAPI tenant")
        return self.settings.username

    def _authenticate(self, username: str, *, force: bool = False) -> tuple[str, str]:
        with self._lock:
            if not force and self._token and self._expires_at > time.time():
                return self._token, self._tenant_id
            response = self._raw_request(
                "POST",
                "/api/auth/login",
                authenticated=False,
                json_body={"username": username, "password": self.settings.password},
            )
            if response.status_code != 200:
                raise NovaOpenApiUnavailableError(
                    f"Nova OpenAPI tenant authentication failed with status {response.status_code}"
                )
            payload = _json_object(response)
            token = str(payload.get("accessToken") or "")
            tenant_id = str(payload.get("tenantId") or "")
            if len(token) < 32 or not tenant_id:
                raise NovaOpenApiUnavailableError("Nova OpenAPI login response was incomplete")
            self._token = token
            self._tenant_id = tenant_id
            self._expires_at = time.time() + 50 * 60
            return token, tenant_id

    def _get(self, username: str, path: str, *, params: dict[str, Any] | None = None) -> Any:
        token, _tenant_id = self._authenticate(username)
        response = self._raw_request("GET", path, token=token, params=params)
        if response.status_code == 401:
            token, _tenant_id = self._authenticate(username, force=True)
            response = self._raw_request("GET", path, token=token, params=params)
        if response.status_code != 200:
            raise NovaOpenApiUnavailableError(
                f"Nova OpenAPI read failed with status {response.status_code}"
            )
        return _bounded(_json_value(response))

    def _raw_request(
        self,
        method: str,
        path: str,
        *,
        authenticated: bool = True,
        token: str = "",
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> requests.Response:
        # Public methods construct every path; this rejects URL/query injection if a future caller regresses.
        if not re.fullmatch(r"/api/[A-Za-z0-9_/-]{1,200}", path):
            raise NovaOpenApiScopeError("Nova OpenAPI path is outside the fixed API scope")
        headers = {"Accept": "application/json"}
        if authenticated:
            if not token:
                raise NovaOpenApiUnavailableError("Nova OpenAPI bearer is unavailable")
            headers["Authorization"] = f"Bearer {token}"
        response: requests.Response | None = None
        for attempt in range(3):
            response = self.session.request(
                method,
                f"{self.settings.base_url}{path}",
                headers=headers,
                params=params,
                json=json_body,
                timeout=self.settings.timeout_seconds,
            )
            if response.status_code != 503 or method != "GET" or attempt >= 2:
                break
            time.sleep(0.25 * (2**attempt))
        if response is None:
            raise NovaOpenApiUnavailableError("Nova OpenAPI returned no response")
        if len(response.content) > 5 * 1024 * 1024:
            raise NovaOpenApiUnavailableError("Nova OpenAPI response exceeded the fixed size limit")
        return response


def _page_params(page_number: int, page_size: int) -> dict[str, Any]:
    return {
        "pageNumber": max(1, int(page_number)),
        "pageSize": max(1, min(int(page_size), 200)),
    }


def _positive_int(value: Any, label: str) -> int:
    try:
        clean = int(value)
    except (TypeError, ValueError) as exc:
        raise NovaOpenApiScopeError(f"{label} must be a positive integer") from exc
    if clean <= 0:
        raise NovaOpenApiScopeError(f"{label} must be a positive integer")
    return clean


def _optional_positive_int(params: dict[str, Any], name: str, value: Any) -> None:
    if value is not None:
        params[name] = _positive_int(value, name)


def _optional_text(params: dict[str, Any], name: str, value: str, maximum: int) -> None:
    clean = str(value or "").strip()
    if clean:
        if len(clean) > maximum:
            raise NovaOpenApiScopeError(f"{name} exceeds {maximum} characters")
        params[name] = clean


def _optional_iso_timestamp(params: dict[str, Any], name: str, value: str) -> None:
    clean = str(value or "").strip()
    if clean:
        if len(clean) > 40 or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T[0-9:.+-]+Z?", clean):
            raise NovaOpenApiScopeError(f"{name} must be an ISO-8601 timestamp")
        params[name] = clean


def _json_object(response: requests.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except (TypeError, ValueError) as exc:
        raise NovaOpenApiUnavailableError("Nova OpenAPI returned invalid JSON") from exc
    return payload if isinstance(payload, dict) else {}


def _json_value(response: requests.Response) -> Any:
    try:
        return response.json()
    except (TypeError, ValueError) as exc:
        raise NovaOpenApiUnavailableError("Nova OpenAPI returned invalid JSON") from exc


def _rows(payload: Any) -> list[Any]:
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        return []
    for key in ("items", "data", "records", "results"):
        if isinstance(payload.get(key), list):
            return payload[key]
    return []


def _read_result(company_username: str, operation: str, payload: Any) -> dict[str, Any]:
    rows = _rows(payload)
    return {
        "ok": True,
        "companyUsername": company_username,
        "operation": operation,
        "rowCount": len(rows) if rows else (1 if isinstance(payload, dict) else 0),
        "data": payload,
    }


def _bounded(value: Any, depth: int = 0) -> Any:
    if depth > 8:
        return "<truncated>"
    if isinstance(value, dict):
        return {
            str(key)[:120]: _bounded(child, depth + 1)
            for key, child in list(value.items())[:300]
        }
    if isinstance(value, list):
        return [_bounded(child, depth + 1) for child in value[:200]]
    if isinstance(value, str):
        return value[:131_072]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)[:2_000]


def _short(value: Any, maximum: int) -> str:
    return str(value or "").strip()[:maximum]
