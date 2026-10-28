from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any

from .nova_sql_client import (
    NovaSqlScopeError,
    NovaSqlSettings,
    NovaSqlUnavailableError,
    ScopedNovaSqlClient,
)
from .salesforce_client import SalesforceSettings, ScopedSalesforceClient


IDEMPOTENCY_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9:._/-]{7,199}$")
COMPANY_USERNAME = re.compile(r"^[A-Za-z0-9_]{1,80}$")
MAX_STDIN_BYTES = 16_384


def execute_location_region_update(
    payload: dict[str, Any],
    *,
    client: ScopedNovaSqlClient,
) -> dict[str, Any]:
    action = str(payload.get("action") or "update_location_region").strip().casefold()
    if action == "preflight":
        return {
            "ok": True,
            "action": "preflight",
            "lane": "coding_agent",
            "accessMode": "fixed_location_region_update_only",
            "arbitrarySqlAccepted": False,
            "deleteExposed": False,
        }
    if action != "update_location_region":
        raise NovaSqlScopeError("Unsupported deterministic Nova SQL action")

    company_username = str(payload.get("companyUsername") or "").strip()
    if not COMPANY_USERNAME.fullmatch(company_username):
        raise NovaSqlScopeError("companyUsername is invalid")
    idempotency_key = str(payload.get("idempotencyKey") or "").strip()
    if not IDEMPOTENCY_KEY.fullmatch(idempotency_key):
        raise NovaSqlScopeError("idempotencyKey is invalid")
    try:
        location_id = int(payload.get("locationId"))
        region_id = int(payload.get("regionId"))
    except (TypeError, ValueError) as exc:
        raise NovaSqlScopeError("locationId and regionId must be positive integers") from exc

    return client.update_location_region(
        company_username=company_username,
        location_id=location_id,
        region_id=region_id,
        idempotency_key=idempotency_key,
    )


def _client_from_environment() -> ScopedNovaSqlClient:
    salesforce = ScopedSalesforceClient(SalesforceSettings.from_environment())
    settings = NovaSqlSettings(
        server=os.getenv(
            "NOVA_SQL_SERVER",
            "cluster.novapointofsale.com,6682",
        ).strip(),
        driver=os.getenv("NOVA_SQL_DRIVER", "").strip(),
    )
    write_state_dir = os.getenv("NOVA_SQL_WRITE_STATE_DIR") or None
    return ScopedNovaSqlClient(
        salesforce,
        settings,
        write_enabled=True,
        write_state_dir=(
            write_state_dir
            or Path(os.getenv("LOCALAPPDATA") or ".")
            / "NovaSqlGuardedExecutor"
        ),
    )


def main() -> int:
    raw = sys.stdin.buffer.read(MAX_STDIN_BYTES + 1)
    if len(raw) > MAX_STDIN_BYTES:
        print(
            json.dumps(
                {"ok": False, "errorType": "InputTooLarge"},
                separators=(",", ":"),
            )
        )
        return 64
    try:
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, dict):
            raise NovaSqlScopeError("Input must be a JSON object")
        result = execute_location_region_update(
            payload,
            client=_client_from_environment(),
        )
    except (NovaSqlScopeError, NovaSqlUnavailableError) as exc:
        result = {
            "ok": False,
            "errorType": type(exc).__name__,
            "message": str(exc),
        }
    except Exception as exc:
        result = {"ok": False, "errorType": type(exc).__name__}
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
