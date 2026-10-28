from __future__ import annotations

# AgentChat/coding_agent 2026-08-06T11:45:00Z
# AgentChat/coding_agent 2026-08-06T13:12:00Z
# AgentChat/coding_agent 2026-08-06T13:54:59Z

import hashlib
import json
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .instyle_runway_merge_sql_v1 import (
    INSTYLE_RUNWAY_INVENTORY_HISTORY_CATCHUP_SQL_V3,
    INSTYLE_RUNWAY_LOCATION_STATUS_REPAIR_SQL_V2,
    INSTYLE_RUNWAY_MERGE_SQL_V1,
)
from .nova_sql_instyle_demo_rebuild import (
    HASH,
    InstyleDemoRebuildScopeError,
    InstyleDemoRebuildUnavailableError,
    _read_json_optional,
    _read_json_required,
    _write_json_atomic,
)
from .nova_sql_instyle_set_based import (
    EXPECTED_PLACEHOLDER_INVOICE_LINES,
    EXPECTED_PLACEHOLDER_PRODUCTS,
    EXPECTED_QUARANTINED_INVOICE_PRODUCT_ROWS,
    PRODUCT_REFERENCE_COLUMNS,
    SOURCE_A_DATABASE,
    SOURCE_A_USERNAME,
    SOURCE_B_DATABASE,
    SOURCE_B_USERNAME,
    _approved_source_scope,
    _idempotency_key,
    _last_json_result,
    _product_orphan_count,
    _quote_identifier,
    _schema_hash,
    _sha256_json,
    _validate_approved_source_scope,
)


OPERATION_NAME = "instyle_runway_production_merge_v1"
TARGET_DATABASE = "POS_INSTYLE_RUNWAY"
TARGET_USERNAME = "INSTYLE_RUNWAY"
SOURCE_A_ACCOUNT_ID = "0011H00002FSqyvQAD"
SOURCE_B_ACCOUNT_ID = "001A0000013GReJIAW"
TARGET_ACCOUNT_ID = "001Rc00000lKdQOIA0"
EXPECTED_SOURCE_A_LOCATIONS = 24
EXPECTED_SOURCE_B_LOCATIONS = 20
EXPECTED_TARGET_LOCATIONS = 44
EXPECTED_TARGET_REGIONS = 2
PRODUCT_MAP_TABLE = "__codex_instyle_runway_product_map"
BACKUP_MANIFEST_TABLE = "__codex_instyle_runway_backup_manifest"
QUARANTINE_TABLE = "__codex_instyle_runway_invoice_product_quarantine"
RECEIPT_TABLE = "__codex_instyle_runway_merge_receipts"
REPAIR_LOCATION_IDS = (25, 26, 27, 28, 29, 31, 35, 36, 37, 39, 40, 42, 44)
FULL_MERGE_MODE = "full_merge"
LOCATION_STATUS_REPAIR_MODE = "location_status_repair"
INVENTORY_HISTORY_CATCHUP_MODE = "inventory_history_catchup"


class InstyleRunwayMergeOperation:
    """Fixed two-source production merge with immutable preview and readback."""

    def __init__(
        self,
        *,
        connect: Callable[[bool], Any],
        resolve_account: Callable[[str], dict[str, Any]],
        state_dir: str | Path,
        query_timeout_seconds: int = 7_200,
    ) -> None:
        self._connect = connect
        self._resolve_account = resolve_account
        self._state_dir = Path(state_dir).expanduser().resolve() / OPERATION_NAME
        self._query_timeout_seconds = max(600, min(int(query_timeout_seconds), 14_400))

    @property
    def configured(self) -> bool:
        return bool(INSTYLE_RUNWAY_MERGE_SQL_V1.strip())

    def preview(self, *, idempotency_key: str) -> dict[str, Any]:
        clean_key = _idempotency_key(idempotency_key)
        completed = _read_json_optional(self._receipt_path(clean_key))
        if completed:
            return _completed_result(completed, replay=True)
        identities = self._resolved_identities()
        with closing(self._connect(True)) as connection:
            cursor = connection.cursor()
            _set_timeout(cursor, self._query_timeout_seconds)
            baseline = _baseline(cursor)
            _validate_source_scope_and_locations(baseline)
            if _is_clean_target(baseline["targetState"]):
                mode = FULL_MERGE_MODE
                existing_merge = None
            else:
                history_catchup = _inventory_history_catchup_context(cursor)
                if history_catchup is not None:
                    mode = INVENTORY_HISTORY_CATCHUP_MODE
                    existing_merge = history_catchup
                else:
                    mode = LOCATION_STATUS_REPAIR_MODE
                    existing_merge = _location_status_repair_context(
                        cursor, baseline["targetState"]
                    )
        script = _script_for_mode(mode)
        script_hash = hashlib.sha256(script.encode("utf-8")).hexdigest()
        immutable = {
            "version": 3,
            "operation": OPERATION_NAME,
            "mode": mode,
            "idempotencyKey": clean_key,
            "fixedSources": [SOURCE_A_USERNAME, SOURCE_B_USERNAME],
            "fixedTarget": TARGET_USERNAME,
            "accountIdentities": identities,
            "sourceDatabases": [SOURCE_A_DATABASE, SOURCE_B_DATABASE],
            "targetDatabase": TARGET_DATABASE,
            "scriptHash": script_hash,
            "sourceSchemaHashes": baseline["sourceSchemaHashes"],
            "targetSchemaHash": baseline["targetSchemaHash"],
            "sourceTableRows": baseline["sourceTableRows"],
            "sourceCriticalHashes": baseline["sourceCriticalHashes"],
            "sourceDataHash": baseline["sourceDataHash"],
            "targetState": baseline["targetState"],
            "targetStateHash": _sha256_json(baseline["targetState"]),
            "existingMerge": existing_merge,
            "approvedSourceScope": baseline["approvedSourceScope"],
            "locationPlan": {
                "sourceA": {"sourceIds": "1-24", "targetIds": "1-24", "regionId": 1},
                "sourceB": {"sourceIds": "1-20", "targetIds": "25-44", "regionId": 2},
            },
            "productDedupe": (
                "normalized ProductName+BarcodeNumber+BarcodeNumber2+SKU; "
                "highest ProductID wins"
            ),
            "productCrosswalk": "source-qualified immutable",
            "copyMode": "single_database_side_set_based_transaction",
            "sourceDatabasesReadOnly": True,
            "targetBackupRequired": True,
            "targetBackupScope": (
                "all_business_tables"
                if mode == FULL_MERGE_MODE
                else (
                    "full_dbo_InventoryHistoryItem"
                    if mode == INVENTORY_HISTORY_CATCHUP_MODE
                    else "full_dbo_Locations"
                )
            ),
            "transactionRollbackRequired": True,
        }
        plan_hash = _sha256_json(immutable)
        preview = {
            **immutable,
            "planHash": plan_hash,
            "previewedAt": datetime.now(timezone.utc).isoformat(),
        }
        _write_json_atomic(self._preview_path(clean_key), preview)
        return _preview_result(preview, replay=False)

    def status(self, *, idempotency_key: str) -> dict[str, Any]:
        clean_key = _idempotency_key(idempotency_key)
        preview = _read_json_required(self._preview_path(clean_key), "preview")
        receipt = _read_json_optional(self._receipt_path(clean_key))
        mode = str(preview.get("mode") or FULL_MERGE_MODE)
        self._resolved_identities()
        with closing(self._connect(True)) as connection:
            cursor = connection.cursor()
            _set_timeout(cursor, self._query_timeout_seconds)
            readback = _readback_for_mode(
                cursor, preview=preview, idempotency_key=clean_key
            )
            baseline = None if readback["completionVerified"] else _baseline(cursor)
        if receipt and readback["completionVerified"]:
            return _completed_result(receipt, replay=True)
        script_matches = preview.get("scriptHash") == hashlib.sha256(
            _script_for_mode(mode).encode("utf-8")
        ).hexdigest()
        target_matches = bool(
            baseline
            and _sha256_json(baseline["targetState"])
            == preview.get("targetStateHash")
        )
        source_matches = bool(
            baseline and baseline["sourceDataHash"] == preview.get("sourceDataHash")
        )
        return {
            "ok": True,
            "operation": "nova_sql_instyle_runway_merge_status",
            "mode": mode,
            "status": (
                "completion_verified_without_local_receipt"
                if readback["completionVerified"]
                else "not_completed"
            ),
            "idempotencyKey": clean_key,
            "previewHash": preview.get("planHash"),
            "fixedSources": [SOURCE_A_USERNAME, SOURCE_B_USERNAME],
            "fixedTarget": TARGET_USERNAME,
            "sourceDatabasesReadOnly": True,
            "scriptHashMatchesPreview": script_matches,
            "sourceMatchesPreview": source_matches,
            "targetMatchesPreview": target_matches,
            "readback": readback,
            "safeToRetry": bool(
                script_matches
                and source_matches
                and target_matches
                and not readback["completionVerified"]
            ),
        }

    def execute(self, *, idempotency_key: str, preview_hash: str) -> dict[str, Any]:
        clean_key = _idempotency_key(idempotency_key)
        clean_hash = str(preview_hash or "").strip().lower()
        if not HASH.fullmatch(clean_hash):
            raise InstyleDemoRebuildScopeError(
                "preview_hash must be the exact production merge preview hash"
            )
        preview = _read_json_required(self._preview_path(clean_key), "preview")
        if (
            preview.get("operation") != OPERATION_NAME
            or preview.get("idempotencyKey") != clean_key
            or preview.get("planHash") != clean_hash
        ):
            raise InstyleDemoRebuildScopeError(
                "preview hash, idempotency key, or fixed production plan does not match"
            )
        completed = _read_json_optional(self._receipt_path(clean_key))
        if completed:
            return _completed_result(completed, replay=True)
        mode = str(preview.get("mode") or "")
        script = _script_for_mode(mode)
        if hashlib.sha256(script.encode("utf-8")).hexdigest() != preview.get(
            "scriptHash"
        ):
            raise InstyleDemoRebuildScopeError(
                "the packaged production merge changed after preview"
            )
        if self._resolved_identities() != preview.get("accountIdentities"):
            raise InstyleDemoRebuildScopeError(
                "a fixed Salesforce account identity changed after preview"
            )

        started = datetime.now(timezone.utc)
        with closing(self._connect(False)) as connection:
            cursor = connection.cursor()
            _set_timeout(cursor, self._query_timeout_seconds)
            current = _baseline(cursor)
            _validate_source_scope_and_locations(current)
            if current["sourceSchemaHashes"] != preview.get("sourceSchemaHashes"):
                raise InstyleDemoRebuildScopeError(
                    "a fixed source schema changed after preview"
                )
            if current["targetSchemaHash"] != preview.get("targetSchemaHash"):
                raise InstyleDemoRebuildScopeError(
                    "the production target schema changed after preview"
                )
            if current["sourceDataHash"] != preview.get("sourceDataHash"):
                raise InstyleDemoRebuildScopeError(
                    "source business data changed after preview; create a fresh preview"
                )
            if _sha256_json(current["targetState"]) != preview.get("targetStateHash"):
                raise InstyleDemoRebuildScopeError(
                    "the production target changed after preview"
                )
            prefix = (
                "DECLARE @Apply bit=?;"
                "DECLARE @OperatorIdempotencyKey nvarchar(200)=?;"
                "DECLARE @OperatorPlanHash char(64)=?;"
                "DECLARE @ExpectedTargetStateHash char(64)=?;"
            )
            cursor.execute(
                prefix + script,
                1,
                clean_key,
                clean_hash,
                str(preview["targetStateHash"]),
            )
            result = _last_json_result(cursor)
            readback = _readback_for_mode(
                cursor, preview=preview, idempotency_key=clean_key
            )
            if not readback["completionVerified"]:
                raise InstyleDemoRebuildUnavailableError(
                    "production merge committed without exhaustive readback verification"
                )

        receipt = {
            "version": 2,
            "operation": OPERATION_NAME,
            "mode": mode,
            "status": "completed",
            "idempotencyKey": clean_key,
            "planHash": clean_hash,
            "scriptHash": preview["scriptHash"],
            "startedAt": started.isoformat(),
            "completedAt": datetime.now(timezone.utc).isoformat(),
            "fixedSources": [SOURCE_A_USERNAME, SOURCE_B_USERNAME],
            "fixedTarget": TARGET_USERNAME,
            "sourceDatabasesReadOnly": True,
            "targetBackupCreated": True,
            "targetBackupScope": preview.get("targetBackupScope"),
            "targetBackupRequired": True,
            "transactionCommitted": True,
            "sqlResult": result,
            "readback": readback,
            "postWriteReadbackVerified": True,
        }
        _write_json_atomic(self._receipt_path(clean_key), receipt)
        return _completed_result(receipt, replay=False)

    def _resolved_identities(self) -> dict[str, str]:
        expected = {
            SOURCE_A_USERNAME: SOURCE_A_ACCOUNT_ID,
            SOURCE_B_USERNAME: SOURCE_B_ACCOUNT_ID,
            TARGET_USERNAME: TARGET_ACCOUNT_ID,
        }
        resolved: dict[str, str] = {}
        for username, account_id in expected.items():
            record = self._resolve_account(username)
            actual_id = str(record.get("account_id") or record.get("accountId") or "")
            actual_username = str(
                record.get("company_username")
                or record.get("companyUsername")
                or username
            )
            if actual_id != account_id or actual_username.casefold() != username.casefold():
                raise InstyleDemoRebuildScopeError(
                    "a fixed Instyle Salesforce account did not resolve exactly"
                )
            resolved[username] = actual_id
        return resolved

    def _preview_path(self, idempotency_key: str) -> Path:
        return self._state_path("preview", idempotency_key)

    def _receipt_path(self, idempotency_key: str) -> Path:
        return self._state_path("receipt", idempotency_key)

    def _state_path(self, kind: str, idempotency_key: str) -> Path:
        digest = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()
        return self._state_dir / f"{digest}.{kind}.json"


def _baseline(cursor: Any) -> dict[str, Any]:
    row = cursor.execute(
        "SELECT DB_NAME(),DB_ID(?),DB_ID(?),DB_ID(?),HAS_DBACCESS(?),HAS_DBACCESS(?)",
        TARGET_DATABASE,
        SOURCE_A_DATABASE,
        SOURCE_B_DATABASE,
        SOURCE_A_DATABASE,
        SOURCE_B_DATABASE,
    ).fetchone()
    if not row or str(row[0] or "").casefold() != TARGET_DATABASE.casefold():
        raise InstyleDemoRebuildScopeError(
            "developer connection is not bound to the fixed production target"
        )
    if any(value is None for value in row[1:4]) or int(row[4] or 0) != 1 or int(
        row[5] or 0
    ) != 1:
        raise InstyleDemoRebuildUnavailableError(
            "the fixed broker cannot read both sources and the production target"
        )
    source_table_rows = {
        database: _table_rows(cursor, database)
        for database in (SOURCE_A_DATABASE, SOURCE_B_DATABASE)
    }
    critical_hashes = {
        database: {
            "locations": _row_fingerprint(
                cursor,
                database,
                "Locations",
                (
                    "LocationID",
                    "RegionID",
                    "LocationName",
                    "LocationManagerEmployeeID",
                ),
            ),
            "products": _row_fingerprint(
                cursor,
                database,
                "Products",
                (
                    "ProductID",
                    "ProductName",
                    "BarcodeNumber",
                    "BarcodeNumber2",
                    "SKU",
                ),
            ),
            "invoiceProducts": _row_fingerprint(
                cursor,
                database,
                "Invoice_Products",
                ("Invoice_Products_ID", "InvoiceID", "ProductID"),
            ),
        }
        for database in (SOURCE_A_DATABASE, SOURCE_B_DATABASE)
    }
    source_scope = _approved_source_scope(cursor)
    source_data = {
        "tableRows": source_table_rows,
        "criticalHashes": critical_hashes,
        "approvedSourceScope": source_scope,
    }
    return {
        "sourceSchemaHashes": {
            SOURCE_A_DATABASE: _schema_hash(cursor, SOURCE_A_DATABASE),
            SOURCE_B_DATABASE: _schema_hash(cursor, SOURCE_B_DATABASE),
        },
        "targetSchemaHash": _schema_hash(cursor, TARGET_DATABASE),
        "sourceTableRows": source_table_rows,
        "sourceCriticalHashes": critical_hashes,
        "sourceDataHash": _sha256_json(source_data),
        "targetState": _target_state(cursor),
        "approvedSourceScope": source_scope,
    }


def _target_state(cursor: Any) -> dict[str, Any]:
    row = cursor.execute(
        "SELECT "
        "(SELECT COUNT_BIG(*) FROM dbo.Products),"
        "(SELECT COUNT_BIG(*) FROM dbo.Invoices),"
        "(SELECT COUNT_BIG(*) FROM dbo.Invoice_Products),"
        "(SELECT COUNT_BIG(*) FROM dbo.InventoryHistoryItem),"
        "(SELECT COUNT_BIG(*) FROM dbo.Locations),"
        "(SELECT COUNT_BIG(*) FROM dbo.Regions)"
    ).fetchone()
    return {
        "productRows": int(row[0] or 0),
        "invoiceRows": int(row[1] or 0),
        "invoiceProductRows": int(row[2] or 0),
        "inventoryHistoryItemRows": int(row[3] or 0),
        "locations": int(row[4] or 0),
        "regions": int(row[5] or 0),
        "businessTableRows": _table_rows(cursor, TARGET_DATABASE),
        "locationFingerprint": _row_fingerprint(
            cursor,
            TARGET_DATABASE,
            "Locations",
            (
                "LocationID",
                "RegionID",
                "LocationName",
                "LocationManagerEmployeeID",
            ),
        ),
        "regionFingerprint": _row_fingerprint(
            cursor,
            TARGET_DATABASE,
            "Regions",
            ("RegionID", "RegionName"),
        ),
        "mergeArtifactsPresent": any(
            _table_exists(cursor, name)
            for name in (
                PRODUCT_MAP_TABLE,
                BACKUP_MANIFEST_TABLE,
                QUARANTINE_TABLE,
                RECEIPT_TABLE,
            )
        ),
    }


def _is_clean_target(state: dict[str, Any]) -> bool:
    expected = {
        "productRows": 0,
        "invoiceRows": 0,
        "invoiceProductRows": 0,
        "inventoryHistoryItemRows": 0,
        "locations": 18,
        "regions": 1,
    }
    return not state.get("mergeArtifactsPresent") and all(
        int(state.get(key) or 0) == value for key, value in expected.items()
    )


def _validate_clean_target(state: dict[str, Any]) -> None:
    if not _is_clean_target(state):
        raise InstyleDemoRebuildScopeError(
            "the production destination is neither the reviewed clean scaffold nor "
            "the exact repairable completed merge"
        )


def _script_for_mode(mode: str) -> str:
    if mode == FULL_MERGE_MODE:
        return INSTYLE_RUNWAY_MERGE_SQL_V1
    if mode == LOCATION_STATUS_REPAIR_MODE:
        return INSTYLE_RUNWAY_LOCATION_STATUS_REPAIR_SQL_V2
    if mode == INVENTORY_HISTORY_CATCHUP_MODE:
        return INSTYLE_RUNWAY_INVENTORY_HISTORY_CATCHUP_SQL_V3
    raise InstyleDemoRebuildScopeError("the production merge preview mode is invalid")


def _location_status_repair_context(
    cursor: Any, state: dict[str, Any]
) -> dict[str, Any]:
    if int(state.get("locations") or 0) != EXPECTED_TARGET_LOCATIONS or int(
        state.get("regions") or 0
    ) != EXPECTED_TARGET_REGIONS:
        _validate_clean_target(state)
    if not all(
        _table_exists(cursor, table)
        for table in (
            PRODUCT_MAP_TABLE,
            BACKUP_MANIFEST_TABLE,
            QUARANTINE_TABLE,
            RECEIPT_TABLE,
        )
    ):
        raise InstyleDemoRebuildScopeError(
            "the production destination does not contain the complete merge artifacts"
        )
    original_key, original_plan = _existing_merge_identity(cursor)
    original_readback = _completion_readback(
        cursor, idempotency_key=original_key, plan_hash=original_plan
    )
    if not original_readback.get("baseCompletionVerified"):
        raise InstyleDemoRebuildScopeError(
            "the existing production merge failed non-status relationship validation"
        )
    mismatches = _location_status_mismatch_rows(cursor)
    expected = [(location_id, 1, 1_000_000_001) for location_id in REPAIR_LOCATION_IDS]
    if mismatches != expected:
        raise InstyleDemoRebuildScopeError(
            "the existing production merge does not match the reviewed inactive-location defect"
        )
    return {
        "idempotencyKey": original_key,
        "planHash": original_plan,
        "baseCompletionVerified": True,
        "locationStatusMismatchIds": list(REPAIR_LOCATION_IDS),
    }


def _inventory_history_catchup_context(cursor: Any) -> dict[str, Any] | None:
    required_artifacts = (
        PRODUCT_MAP_TABLE,
        BACKUP_MANIFEST_TABLE,
        QUARANTINE_TABLE,
        RECEIPT_TABLE,
    )
    if not all(_table_exists(cursor, table) for table in required_artifacts):
        return None
    original_key, original_plan = _existing_merge_identity(cursor)
    readback = _completion_readback(
        cursor, idempotency_key=original_key, plan_hash=original_plan
    )
    current_history = int(readback.get("inventoryHistoryItemRows") or 0)
    expected_history = int(readback.get("expectedInventoryHistoryItemRows") or 0)
    if current_history >= expected_history:
        return None
    exact_non_history_state = bool(
        readback.get("locations") == EXPECTED_TARGET_LOCATIONS
        and readback.get("regions") == EXPECTED_TARGET_REGIONS
        and readback.get("locationGroupMismatches") == 0
        and readback.get("locationStatusMismatches") == 0
        and readback.get("regionGroupMismatches") == 0
        and readback.get("duplicateNonblankProductKeys") == 0
        and readback.get("productOrphanRows") == 0
        and readback.get("invoiceProductsWithBlankInvoiceId") == 0
        and readback.get("qualifiedPlaceholderProducts")
        == EXPECTED_PLACEHOLDER_PRODUCTS
        and readback.get("qualifiedPlaceholderInvoiceLines")
        == EXPECTED_PLACEHOLDER_INVOICE_LINES
        and readback.get("placeholderRequiredFieldGaps") == 0
        and readback.get("productMapRows") == readback.get("expectedProductMapRows")
        and readback.get("productMapPlanMismatches") == 0
        and readback.get("declaredForeignKeyOrphans") == 0
        and int(readback.get("backupTables") or 0) > 0
        and readback.get("backupRowCountMismatches") == 0
        and readback.get("quarantinedInvoiceProductRows")
        == EXPECTED_QUARANTINED_INVOICE_PRODUCT_ROWS
        and readback.get("durableReceiptVerified") is True
    )
    if not exact_non_history_state:
        raise InstyleDemoRebuildScopeError(
            "the existing production merge has changes outside the fixed "
            "inventory-history catch-up scope"
        )
    return {
        "idempotencyKey": original_key,
        "planHash": original_plan,
        "nonHistoryCompletionVerified": True,
        "inventoryHistoryItemRows": current_history,
        "expectedInventoryHistoryItemRows": expected_history,
        "missingInventoryHistoryItemRows": expected_history - current_history,
    }


def _existing_merge_identity(cursor: Any) -> tuple[str, str]:
    plans = cursor.execute(
        f"SELECT PlanHash,COUNT_BIG(*) FROM dbo.{PRODUCT_MAP_TABLE} "
        "GROUP BY PlanHash ORDER BY PlanHash"
    ).fetchall()
    if len(plans) != 1 or not HASH.fullmatch(str(plans[0][0] or "").lower()):
        raise InstyleDemoRebuildScopeError(
            "the immutable production product crosswalk has no single source plan"
        )
    plan_hash = str(plans[0][0]).lower()
    receipts = cursor.execute(
        f"SELECT IdempotencyKey FROM dbo.{RECEIPT_TABLE} "
        "WHERE PlanHash=? AND CompletedAtUtc IS NOT NULL ORDER BY StartedAtUtc",
        plan_hash,
    ).fetchall()
    if len(receipts) != 1 or not str(receipts[0][0] or "").strip():
        raise InstyleDemoRebuildScopeError(
            "the immutable production merge receipt is not unique"
        )
    return str(receipts[0][0]), plan_hash


def _location_status_mismatch_rows(cursor: Any) -> list[tuple[int, int | None, int | None]]:
    rows = cursor.execute(
        "SELECT TargetLocationID,SourceManagerID,TargetManagerID FROM ("
        "SELECT s.LocationID TargetLocationID,"
        "s.LocationManagerEmployeeID SourceManagerID,"
        "t.LocationManagerEmployeeID TargetManagerID "
        "FROM [POS_LE_BOUTIQUE_INSTYLE].dbo.Locations s "
        "LEFT JOIN dbo.Locations t ON t.LocationID=s.LocationID "
        "WHERE t.LocationID IS NULL OR "
        "ISNULL(t.LocationManagerEmployeeID,-2147483648)<>"
        "ISNULL(s.LocationManagerEmployeeID,-2147483648) "
        "UNION ALL "
        "SELECT s.LocationID+24,"
        "CASE WHEN s.LocationManagerEmployeeID=1 THEN 1 "
        "WHEN s.LocationManagerEmployeeID>1 "
        "THEN s.LocationManagerEmployeeID+1000000000 "
        "ELSE s.LocationManagerEmployeeID END,"
        "t.LocationManagerEmployeeID "
        "FROM [POS_Instyle_Fragrance].dbo.Locations s "
        "LEFT JOIN dbo.Locations t ON t.LocationID=s.LocationID+24 "
        "WHERE t.LocationID IS NULL OR "
        "ISNULL(t.LocationManagerEmployeeID,-2147483648)<>"
        "ISNULL(CASE WHEN s.LocationManagerEmployeeID=1 THEN 1 "
        "WHEN s.LocationManagerEmployeeID>1 "
        "THEN s.LocationManagerEmployeeID+1000000000 "
        "ELSE s.LocationManagerEmployeeID END,-2147483648)"
        ") mismatches ORDER BY TargetLocationID"
    ).fetchall()
    return [
        (
            int(location_id),
            None if source_manager is None else int(source_manager),
            None if target_manager is None else int(target_manager),
        )
        for location_id, source_manager, target_manager in rows
    ]


def _validate_source_scope_and_locations(baseline: dict[str, Any]) -> None:
    _validate_approved_source_scope(baseline["approvedSourceScope"])
    source_rows = baseline["sourceTableRows"]
    if int(source_rows[SOURCE_A_DATABASE].get("Locations") or 0) != (
        EXPECTED_SOURCE_A_LOCATIONS
    ):
        raise InstyleDemoRebuildScopeError("source A no longer has exactly 24 locations")
    if int(source_rows[SOURCE_B_DATABASE].get("Locations") or 0) != (
        EXPECTED_SOURCE_B_LOCATIONS
    ):
        raise InstyleDemoRebuildScopeError("source B no longer has exactly 20 locations")


def _table_rows(cursor: Any, database: str) -> dict[str, int]:
    quoted = _quote_identifier(database)
    rows = cursor.execute(
        "SELECT t.name,SUM(CONVERT(bigint,p.rows)) "
        f"FROM {quoted}.sys.tables t "
        f"JOIN {quoted}.sys.schemas s ON s.schema_id=t.schema_id AND s.name=N'dbo' "
        f"JOIN {quoted}.sys.partitions p ON p.object_id=t.object_id "
        "AND p.index_id IN(0,1) WHERE t.is_ms_shipped=0 "
        "AND t.name<>N'Log4Net' AND t.name NOT LIKE N'__codex[_]%' "
        "AND t.name NOT LIKE N'__nova[_]%' GROUP BY t.name ORDER BY t.name"
    ).fetchall()
    return {str(name): int(count or 0) for name, count in rows}


def _row_fingerprint(
    cursor: Any,
    database: str,
    table: str,
    columns: tuple[str, ...],
) -> str:
    quoted_database = _quote_identifier(database)
    selected = ",".join(_quote_identifier(column) for column in columns)
    order_by = _quote_identifier(columns[0])
    result = cursor.execute(
        f"SELECT {selected} FROM {quoted_database}.dbo.{_quote_identifier(table)} "
        f"ORDER BY {order_by}"
    )
    digest = hashlib.sha256()
    while True:
        rows = result.fetchmany(2_000)
        if not rows:
            break
        for row in rows:
            digest.update(
                json.dumps(
                    [None if value is None else str(value) for value in row],
                    ensure_ascii=False,
                    separators=(",", ":"),
                ).encode("utf-8")
            )
            digest.update(b"\n")
    return digest.hexdigest()


def _table_exists(cursor: Any, table: str) -> bool:
    return bool(
        cursor.execute(
            "SELECT CASE WHEN OBJECT_ID(?,N'U') IS NULL THEN 0 ELSE 1 END",
            f"dbo.{table}",
        ).fetchone()[0]
    )


def _completion_readback(
    cursor: Any,
    *,
    idempotency_key: str,
    plan_hash: str,
) -> dict[str, Any]:
    state = cursor.execute(
        "SELECT "
        "(SELECT COUNT_BIG(*) FROM dbo.Products),"
        "(SELECT COUNT_BIG(*) FROM dbo.Invoice_Products),"
        "(SELECT COUNT_BIG(*) FROM dbo.InventoryHistoryItem),"
        "(SELECT COUNT_BIG(*) FROM dbo.Locations),"
        "(SELECT COUNT_BIG(*) FROM dbo.Regions),"
        "(SELECT COUNT_BIG(*) FROM dbo.Invoice_Products WHERE InvoiceID IS NULL)"
    ).fetchone()
    artifacts = all(
        _table_exists(cursor, table)
        for table in (
            PRODUCT_MAP_TABLE,
            BACKUP_MANIFEST_TABLE,
            QUARANTINE_TABLE,
            RECEIPT_TABLE,
        )
    )
    if not artifacts:
        return {
            "completionVerified": False,
            "mergeArtifactsPresent": False,
            "locations": int(state[3] or 0),
            "regions": int(state[4] or 0),
        }
    map_row = cursor.execute(
        f"SELECT COUNT_BIG(*),SUM(CASE WHEN IsPlaceholder=1 THEN 1 ELSE 0 END),"
        f"SUM(CASE WHEN PlanHash<>? THEN 1 ELSE 0 END) FROM dbo.{PRODUCT_MAP_TABLE}",
        plan_hash,
    ).fetchone()
    source_product_rows = sum(
        int(
            cursor.execute(
                f"SELECT COUNT_BIG(*) FROM {_quote_identifier(database)}.dbo.Products"
            ).fetchone()[0]
            or 0
        )
        for database in (SOURCE_A_DATABASE, SOURCE_B_DATABASE)
    )
    location_mismatches = int(
        cursor.execute(
            "SELECT "
            "(SELECT COUNT_BIG(*) FROM [POS_LE_BOUTIQUE_INSTYLE].dbo.Locations s "
            "LEFT JOIN dbo.Locations t ON t.LocationID=s.LocationID "
            "WHERE t.LocationID IS NULL OR t.RegionID<>1 "
            "OR ISNULL(t.LocationName,N'')<>ISNULL(s.LocationName,N''))+"
            "(SELECT COUNT_BIG(*) FROM [POS_Instyle_Fragrance].dbo.Locations s "
            "LEFT JOIN dbo.Locations t ON t.LocationID=s.LocationID+24 "
            "WHERE t.LocationID IS NULL OR t.RegionID<>2 "
            "OR ISNULL(t.LocationName,N'')<>ISNULL(s.LocationName,N''))"
        ).fetchone()[0]
        or 0
    )
    location_status_mismatches = len(_location_status_mismatch_rows(cursor))
    region_mismatches = int(
        cursor.execute(
            "SELECT COUNT_BIG(*) FROM dbo.Regions WHERE "
            "(RegionID=1 AND RegionName<>N'LE BOUTIQUE INSTYLE') OR "
            "(RegionID=2 AND RegionName<>N'Instyle Fragrance') OR RegionID NOT IN(1,2)"
        ).fetchone()[0]
        or 0
    )
    placeholder_lines = int(
        cursor.execute(
            f"SELECT COUNT_BIG(*) FROM dbo.Invoice_Products ip JOIN dbo.{PRODUCT_MAP_TABLE} m "
            "ON m.TargetProductID=ip.ProductID WHERE m.IsPlaceholder=1"
        ).fetchone()[0]
        or 0
    )
    placeholder_gaps = int(
        cursor.execute(
            f"SELECT COUNT_BIG(*) FROM dbo.{PRODUCT_MAP_TABLE} m "
            "JOIN dbo.Products p ON p.ProductID=m.TargetProductID "
            "WHERE m.IsPlaceholder=1 AND ("
            "NULLIF(LTRIM(RTRIM(p.ProductName)),N'') IS NULL OR "
            "NULLIF(LTRIM(RTRIM(p.SKU)),N'') IS NULL OR "
            "NULLIF(LTRIM(RTRIM(p.BarcodeNumber)),N'') IS NULL)"
        ).fetchone()[0]
        or 0
    )
    duplicate_keys = _duplicate_product_keys(cursor)
    product_orphans = _product_orphan_count(cursor)
    source_history = sum(
        int(
            cursor.execute(
                f"SELECT COUNT_BIG(*) FROM {_quote_identifier(database)}.dbo.InventoryHistoryItem"
            ).fetchone()[0]
            or 0
        )
        for database in (SOURCE_A_DATABASE, SOURCE_B_DATABASE)
    )
    backup = cursor.execute(
        f"SELECT COUNT_BIG(*),SUM(CASE WHEN SourceRows<>BackupRows THEN 1 ELSE 0 END) "
        f"FROM dbo.{BACKUP_MANIFEST_TABLE} WHERE PlanHash=?",
        plan_hash,
    ).fetchone()
    quarantined = int(
        cursor.execute(
            f"SELECT COUNT_BIG(*) FROM dbo.{QUARANTINE_TABLE} WHERE PlanHash=?",
            plan_hash,
        ).fetchone()[0]
        or 0
    )
    durable_receipt = bool(
        cursor.execute(
            f"SELECT COUNT_BIG(*) FROM dbo.{RECEIPT_TABLE} "
            "WHERE IdempotencyKey=? AND PlanHash=? AND CompletedAtUtc IS NOT NULL",
            idempotency_key,
            plan_hash,
        ).fetchone()[0]
    )
    declared_orphans = _declared_foreign_key_orphans(cursor)
    result = {
        "productRows": int(state[0] or 0),
        "invoiceProductRows": int(state[1] or 0),
        "inventoryHistoryItemRows": int(state[2] or 0),
        "expectedInventoryHistoryItemRows": source_history,
        "locations": int(state[3] or 0),
        "regions": int(state[4] or 0),
        "invoiceProductsWithBlankInvoiceId": int(state[5] or 0),
        "productMapRows": int(map_row[0] or 0),
        "expectedProductMapRows": source_product_rows + EXPECTED_PLACEHOLDER_PRODUCTS,
        "qualifiedPlaceholderProducts": int(map_row[1] or 0),
        "productMapPlanMismatches": int(map_row[2] or 0),
        "qualifiedPlaceholderInvoiceLines": placeholder_lines,
        "placeholderRequiredFieldGaps": placeholder_gaps,
        "duplicateNonblankProductKeys": duplicate_keys,
        "productOrphanRows": product_orphans,
        "locationGroupMismatches": location_mismatches,
        "locationStatusMismatches": location_status_mismatches,
        "regionGroupMismatches": region_mismatches,
        "declaredForeignKeyOrphans": declared_orphans,
        "backupTables": int(backup[0] or 0),
        "backupRowCountMismatches": int(backup[1] or 0),
        "quarantinedInvoiceProductRows": quarantined,
        "durableReceiptVerified": durable_receipt,
        "mergeArtifactsPresent": True,
    }
    result["baseCompletionVerified"] = bool(
        result["locations"] == EXPECTED_TARGET_LOCATIONS
        and result["regions"] == EXPECTED_TARGET_REGIONS
        and location_mismatches == 0
        and region_mismatches == 0
        and duplicate_keys == 0
        and product_orphans == 0
        and result["invoiceProductsWithBlankInvoiceId"] == 0
        and result["qualifiedPlaceholderProducts"] == EXPECTED_PLACEHOLDER_PRODUCTS
        and placeholder_lines == EXPECTED_PLACEHOLDER_INVOICE_LINES
        and placeholder_gaps == 0
        and result["productMapRows"] == result["expectedProductMapRows"]
        and result["productMapPlanMismatches"] == 0
        and result["inventoryHistoryItemRows"] == source_history
        and declared_orphans == 0
        and result["backupTables"] > 0
        and result["backupRowCountMismatches"] == 0
        and quarantined == EXPECTED_QUARANTINED_INVOICE_PRODUCT_ROWS
        and durable_receipt
    )
    result["completionVerified"] = bool(
        result["baseCompletionVerified"] and location_status_mismatches == 0
    )
    return result


def _readback_for_mode(
    cursor: Any,
    *,
    preview: dict[str, Any],
    idempotency_key: str,
) -> dict[str, Any]:
    plan_hash = str(preview.get("planHash") or "")
    mode = str(preview.get("mode") or FULL_MERGE_MODE)
    if mode == FULL_MERGE_MODE:
        return _completion_readback(
            cursor, idempotency_key=idempotency_key, plan_hash=plan_hash
        )
    if mode == INVENTORY_HISTORY_CATCHUP_MODE:
        existing = preview.get("existingMerge")
        if not isinstance(existing, dict):
            raise InstyleDemoRebuildScopeError(
                "the catch-up preview is missing the immutable original merge identity"
            )
        original_key = str(existing.get("idempotencyKey") or "")
        original_plan = str(existing.get("planHash") or "").lower()
        if not original_key or not HASH.fullmatch(original_plan):
            raise InstyleDemoRebuildScopeError(
                "the catch-up preview original merge identity is invalid"
            )
        original = _completion_readback(
            cursor, idempotency_key=original_key, plan_hash=original_plan
        )
        backup = cursor.execute(
            f"SELECT COUNT_BIG(*),"
            "SUM(CASE WHEN SourceRows<>BackupRows THEN 1 ELSE 0 END),"
            "SUM(BackupRows) "
            f"FROM dbo.{BACKUP_MANIFEST_TABLE} "
            "WHERE PlanHash=? AND SourceTable=N'InventoryHistoryItem'",
            plan_hash,
        ).fetchone()
        durable_receipt = bool(
            cursor.execute(
                f"SELECT COUNT_BIG(*) FROM dbo.{RECEIPT_TABLE} "
                "WHERE IdempotencyKey=? AND PlanHash=? AND CompletedAtUtc IS NOT NULL",
                idempotency_key,
                plan_hash,
            ).fetchone()[0]
        )
        target_state = preview.get("targetState")
        expected_backup_rows = int(
            target_state.get("inventoryHistoryItemRows") or 0
        ) if isinstance(target_state, dict) else 0
        result = {
            "inventoryHistoryItemRows": original.get("inventoryHistoryItemRows"),
            "expectedInventoryHistoryItemRows": original.get(
                "expectedInventoryHistoryItemRows"
            ),
            "originalMergeCompletionVerified": original.get("completionVerified"),
            "productOrphanRows": original.get("productOrphanRows"),
            "declaredForeignKeyOrphans": original.get("declaredForeignKeyOrphans"),
            "locationGroupMismatches": original.get("locationGroupMismatches"),
            "locationStatusMismatches": original.get("locationStatusMismatches"),
            "regionGroupMismatches": original.get("regionGroupMismatches"),
            "catchupBackupTables": int(backup[0] or 0),
            "catchupBackupRowCountMismatches": int(backup[1] or 0),
            "catchupBackupRows": int(backup[2] or 0),
            "expectedCatchupBackupRows": expected_backup_rows,
            "durableCatchupReceiptVerified": durable_receipt,
            "sourceDatabasesReadOnly": True,
        }
        result["completionVerified"] = bool(
            original.get("completionVerified")
            and result["inventoryHistoryItemRows"]
            == result["expectedInventoryHistoryItemRows"]
            and result["catchupBackupTables"] == 1
            and result["catchupBackupRowCountMismatches"] == 0
            and result["catchupBackupRows"] == expected_backup_rows
            and durable_receipt
        )
        return result
    if mode != LOCATION_STATUS_REPAIR_MODE:
        raise InstyleDemoRebuildScopeError("the production merge preview mode is invalid")
    existing = preview.get("existingMerge")
    if not isinstance(existing, dict):
        raise InstyleDemoRebuildScopeError(
            "the repair preview is missing the immutable original merge identity"
        )
    original_key = str(existing.get("idempotencyKey") or "")
    original_plan = str(existing.get("planHash") or "").lower()
    if not original_key or not HASH.fullmatch(original_plan):
        raise InstyleDemoRebuildScopeError(
            "the repair preview original merge identity is invalid"
        )
    original = _completion_readback(
        cursor, idempotency_key=original_key, plan_hash=original_plan
    )
    backup = cursor.execute(
        f"SELECT COUNT_BIG(*),"
        "SUM(CASE WHEN SourceRows<>BackupRows THEN 1 ELSE 0 END),"
        "SUM(BackupRows) "
        f"FROM dbo.{BACKUP_MANIFEST_TABLE} "
        "WHERE PlanHash=? AND SourceTable=N'Locations'",
        plan_hash,
    ).fetchone()
    durable_receipt = bool(
        cursor.execute(
            f"SELECT COUNT_BIG(*) FROM dbo.{RECEIPT_TABLE} "
            "WHERE IdempotencyKey=? AND PlanHash=? AND CompletedAtUtc IS NOT NULL",
            idempotency_key,
            plan_hash,
        ).fetchone()[0]
    )
    mismatch_rows = _location_status_mismatch_rows(cursor)
    result = {
        "locations": original.get("locations"),
        "regions": original.get("regions"),
        "locationStatusMismatches": len(mismatch_rows),
        "locationStatusMismatchIds": [row[0] for row in mismatch_rows],
        "originalMergeCompletionVerified": original.get("completionVerified"),
        "productOrphanRows": original.get("productOrphanRows"),
        "declaredForeignKeyOrphans": original.get("declaredForeignKeyOrphans"),
        "duplicateNonblankProductKeys": original.get("duplicateNonblankProductKeys"),
        "qualifiedPlaceholderProducts": original.get("qualifiedPlaceholderProducts"),
        "qualifiedPlaceholderInvoiceLines": original.get(
            "qualifiedPlaceholderInvoiceLines"
        ),
        "quarantinedInvoiceProductRows": original.get(
            "quarantinedInvoiceProductRows"
        ),
        "inventoryHistoryItemRows": original.get("inventoryHistoryItemRows"),
        "expectedInventoryHistoryItemRows": original.get(
            "expectedInventoryHistoryItemRows"
        ),
        "repairBackupTables": int(backup[0] or 0),
        "repairBackupRowCountMismatches": int(backup[1] or 0),
        "repairBackupRows": int(backup[2] or 0),
        "durableRepairReceiptVerified": durable_receipt,
        "sourceDatabasesReadOnly": True,
    }
    result["completionVerified"] = bool(
        original.get("completionVerified")
        and not mismatch_rows
        and result["repairBackupTables"] == 1
        and result["repairBackupRowCountMismatches"] == 0
        and result["repairBackupRows"] == EXPECTED_TARGET_LOCATIONS
        and durable_receipt
    )
    return result


def _duplicate_product_keys(cursor: Any) -> int:
    return int(
        cursor.execute(
            "SELECT COUNT_BIG(*) FROM (SELECT "
            "LOWER(LTRIM(RTRIM(ISNULL(ProductName,N'')))) n,"
            "LOWER(REPLACE(LTRIM(RTRIM(ISNULL(BarcodeNumber,N''))),N' ',N'')) b1,"
            "LOWER(REPLACE(LTRIM(RTRIM(ISNULL(BarcodeNumber2,N''))),N' ',N'')) b2,"
            "LOWER(REPLACE(LTRIM(RTRIM(ISNULL(SKU,N''))),N' ',N'')) sku "
            "FROM dbo.Products GROUP BY "
            "LOWER(LTRIM(RTRIM(ISNULL(ProductName,N'')))),"
            "LOWER(REPLACE(LTRIM(RTRIM(ISNULL(BarcodeNumber,N''))),N' ',N'')),"
            "LOWER(REPLACE(LTRIM(RTRIM(ISNULL(BarcodeNumber2,N''))),N' ',N'')),"
            "LOWER(REPLACE(LTRIM(RTRIM(ISNULL(SKU,N''))),N' ',N'')) "
            "HAVING COUNT_BIG(*)>1 AND NOT("
            "LOWER(LTRIM(RTRIM(ISNULL(ProductName,N''))))=N'' AND "
            "LOWER(REPLACE(LTRIM(RTRIM(ISNULL(BarcodeNumber,N''))),N' ',N''))=N'' AND "
            "LOWER(REPLACE(LTRIM(RTRIM(ISNULL(BarcodeNumber2,N''))),N' ',N''))=N'' AND "
            "LOWER(REPLACE(LTRIM(RTRIM(ISNULL(SKU,N''))),N' ',N''))=N'')) d"
        ).fetchone()[0]
        or 0
    )


def _declared_foreign_key_orphans(cursor: Any) -> int:
    rows = cursor.execute(
        "SELECT fk.object_id,ct.name,pt.name,fkc.constraint_column_id,"
        "cc.name,pc.name FROM sys.foreign_keys fk "
        "JOIN sys.tables ct ON ct.object_id=fk.parent_object_id "
        "JOIN sys.tables pt ON pt.object_id=fk.referenced_object_id "
        "JOIN sys.foreign_key_columns fkc ON fkc.constraint_object_id=fk.object_id "
        "JOIN sys.columns cc ON cc.object_id=fkc.parent_object_id "
        "AND cc.column_id=fkc.parent_column_id "
        "JOIN sys.columns pc ON pc.object_id=fkc.referenced_object_id "
        "AND pc.column_id=fkc.referenced_column_id "
        "WHERE fk.is_disabled=0 AND fk.is_ms_shipped=0 "
        "ORDER BY fk.object_id,fkc.constraint_column_id"
    ).fetchall()
    groups: dict[tuple[int, str, str], list[tuple[str, str]]] = {}
    for object_id, child, parent, _ordinal, child_column, parent_column in rows:
        groups.setdefault((int(object_id), str(child), str(parent)), []).append(
            (str(child_column), str(parent_column))
        )
    product_pairs = {(table, column) for table, column in PRODUCT_REFERENCE_COLUMNS}
    total = 0
    for (_object_id, child, parent), columns in groups.items():
        if parent == "Products" and any(
            (child, child_column) in product_pairs for child_column, _ in columns
        ):
            continue
        join = " AND ".join(
            f"p.{_quote_identifier(parent_column)}=c.{_quote_identifier(child_column)}"
            for child_column, parent_column in columns
        )
        required = " AND ".join(
            f"c.{_quote_identifier(child_column)} IS NOT NULL"
            for child_column, _ in columns
        )
        presence = f"p.{_quote_identifier(columns[0][1])} IS NULL"
        total += int(
            cursor.execute(
                f"SELECT COUNT_BIG(*) FROM dbo.{_quote_identifier(child)} c "
                f"LEFT JOIN dbo.{_quote_identifier(parent)} p ON {join} "
                f"WHERE {required} AND {presence}"
            ).fetchone()[0]
            or 0
        )
    return total


def _set_timeout(cursor: Any, seconds: int) -> None:
    if hasattr(cursor, "timeout"):
        cursor.timeout = seconds


def _preview_result(preview: dict[str, Any], *, replay: bool) -> dict[str, Any]:
    return {
        "ok": True,
        "operation": "nova_sql_instyle_runway_merge_preview",
        "status": "previewed",
        "replay": replay,
        "mode": preview.get("mode"),
        "idempotencyKey": preview.get("idempotencyKey"),
        "previewHash": preview.get("planHash"),
        "fixedSources": preview.get("fixedSources"),
        "fixedTarget": preview.get("fixedTarget"),
        "sourceDatabasesReadOnly": True,
        "targetBackupRequired": True,
        "targetBackupScope": preview.get("targetBackupScope"),
        "copyMode": preview.get("copyMode"),
        "targetBaseline": preview.get("targetState"),
        "sourceTableRows": preview.get("sourceTableRows"),
        "approvedSourceScope": preview.get("approvedSourceScope"),
        "locationPlan": preview.get("locationPlan"),
        "productDedupe": preview.get("productDedupe"),
        "productCrosswalk": preview.get("productCrosswalk"),
        "locationStatusMismatchIds": (
            (preview.get("existingMerge") or {}).get("locationStatusMismatchIds")
            if isinstance(preview.get("existingMerge"), dict)
            else []
        ),
        "nextStep": (
            "Call nova_sql_instyle_runway_merge_execute with the same idempotency "
            "key and exact preview hash."
        ),
    }


def _completed_result(receipt: dict[str, Any], *, replay: bool) -> dict[str, Any]:
    return {
        "ok": True,
        "operation": "nova_sql_instyle_runway_merge_execute",
        "status": receipt.get("status"),
        "replay": replay,
        "idempotencyKey": receipt.get("idempotencyKey"),
        "previewHash": receipt.get("planHash"),
        "fixedSources": receipt.get("fixedSources"),
        "fixedTarget": receipt.get("fixedTarget"),
        "sourceDatabasesReadOnly": True,
        "targetBackupCreated": receipt.get("targetBackupCreated"),
        "targetBackupRequired": True,
        "transactionCommitted": receipt.get("transactionCommitted"),
        "sqlResult": receipt.get("sqlResult"),
        "readback": receipt.get("readback"),
        "postWriteReadbackVerified": receipt.get("postWriteReadbackVerified"),
    }


def execution_failure_result(
    *, idempotency_key: str, preview_hash: str, error: Exception
) -> dict[str, Any]:
    return {
        "ok": False,
        "operation": "nova_sql_instyle_runway_merge_execute",
        "status": "execution_failed_reconciliation_required",
        "idempotencyKey": str(idempotency_key or ""),
        "previewHash": str(preview_hash or ""),
        "errorType": type(error).__name__,
        "error": str(error) or repr(error),
        "fixedSources": [SOURCE_A_USERNAME, SOURCE_B_USERNAME],
        "fixedTarget": TARGET_USERNAME,
        "sourceDatabasesReadOnly": True,
        "nextStep": (
            "Call nova_sql_instyle_runway_merge_status with this idempotency key "
            "before any retry."
        ),
    }
