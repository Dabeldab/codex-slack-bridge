from __future__ import annotations

# AgentChat/coding_agent 2026-08-05T10:32:03Z

import hashlib
import json
import re
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .instyle_demo_merge_sql_v2 import INSTYLE_DEMO_MERGE_SQL_V2
from .nova_sql_instyle_demo_rebuild import (
    HASH,
    IDEMPOTENCY_KEY,
    InstyleDemoRebuildScopeError,
    InstyleDemoRebuildUnavailableError,
    _read_json_optional,
    _read_json_required,
    _write_json_atomic,
)


OPERATION_NAME = "instyle_demo_set_based_sql_v1"
SOURCE_A_DATABASE = "POS_LE_BOUTIQUE_INSTYLE"
SOURCE_B_DATABASE = "POS_Instyle_Fragrance"
TARGET_DATABASE = "POS_DEMO_NOVA_CAFE"
SOURCE_A_USERNAME = "LE_BOUTIQUE_INSTYLE"
SOURCE_B_USERNAME = "Instyle_Fragrance"
TARGET_USERNAME = "DEMO_NOVA_CAFE"
SQL_RESOURCE = Path(__file__).with_name("sql") / "instyle_demo_merge.sql"
PRODUCT_REFERENCE_COLUMNS = (
    ("Coupons_Products", "ProductID"),
    ("CustomerOrders_Products", "ProductID"),
    ("Inventory", "ProductID"),
    ("Inventory_Counts_Products", "ProductID"),
    ("Inventory_Damage", "ProductID"),
    ("Inventory_Transactions", "ProductID"),
    ("InventoryHistoryItem", "OriginalProductID"),
    ("Invoice_Products", "ProductID"),
    ("Invoice_Refunds", "ProductID"),
    ("Pending_Invoice_Product", "ProductID"),
    ("PriceLists_Items", "ProductID"),
    ("ProductFavorites", "ProductID"),
    ("Quote_Products", "ProductID"),
    ("Refunds_Products", "ProductID"),
    ("StorageOrders_Products", "ProductID"),
)
EXPECTED_PLACEHOLDER_PRODUCTS = 107
EXPECTED_PLACEHOLDER_INVOICE_LINES = 142
EXPECTED_QUARANTINED_INVOICE_PRODUCT_ROWS = 11
APPROVED_PARTIAL_TARGET_STATE = {
    "productRows": 37,
    "invoiceProductRows": 174_026,
    "locations": 44,
    "regions": 4,
    "productMapRows": 80_983,
    "invoiceProductsWithBlankInvoiceId": 0,
}
APPROVED_PARTIAL_PLACEHOLDER_PRODUCTS = 15_272
APPROVED_PARTIAL_PLACEHOLDER_INVOICE_LINES = 137
APPROVED_PARTIAL_PREVIEW_HASH = (
    "91404f8bdbddbb1315ff8d160dbe316e06343557593c03a1886bde65a62b3bb0"
)


class SetBasedInstyleDemoSyncOperation:
    """Run the fixed Instyle merge as one database-side set-based SQL batch."""

    def __init__(
        self,
        *,
        connect: Callable[[bool], Any],
        state_dir: str | Path,
        sql_resource: str | Path = SQL_RESOURCE,
        query_timeout_seconds: int = 3_600,
    ) -> None:
        self._connect = connect
        self._state_dir = Path(state_dir).expanduser().resolve() / OPERATION_NAME
        self._sql_resource = Path(sql_resource).expanduser().resolve()
        self._query_timeout_seconds = max(300, min(int(query_timeout_seconds), 7_200))

    @property
    def configured(self) -> bool:
        return bool(INSTYLE_DEMO_MERGE_SQL_V2.strip())

    def preview(self, *, idempotency_key: str) -> dict[str, Any]:
        clean_key = _idempotency_key(idempotency_key)
        existing = _read_json_optional(self._preview_path(clean_key))
        script = self._script()
        script_hash = hashlib.sha256(script.encode("utf-8")).hexdigest()
        if existing and existing.get("scriptHash") == script_hash:
            return _preview_result(existing, replay=True)
        completed = _read_json_optional(self._receipt_path(clean_key))
        if completed:
            return _completed_result(completed, replay=True)
        approved_partial_recovery = False
        with closing(self._connect(True)) as connection:
            cursor = connection.cursor()
            baseline = _baseline(cursor)
            _validate_approved_source_scope(baseline["approvedSourceScope"])
            if existing and _sha256_json(
                baseline["targetState"]
            ) != existing.get("targetStateHash"):
                readback = _completion_readback(cursor)
                approved_partial_recovery = _is_approved_partial_target_recovery(
                    existing=existing,
                    idempotency_key=clean_key,
                    baseline=baseline,
                    readback=readback,
                )
                if not approved_partial_recovery:
                    raise InstyleDemoRebuildScopeError(
                        "the fixed SQL contract changed after the target baseline; "
                        "reconcile status before refreshing this preview"
                    )
        immutable = {
            "version": 1,
            "operation": OPERATION_NAME,
            "idempotencyKey": clean_key,
            "fixedSources": [SOURCE_A_USERNAME, SOURCE_B_USERNAME],
            "fixedTarget": TARGET_USERNAME,
            "sourceDatabases": [SOURCE_A_DATABASE, SOURCE_B_DATABASE],
            "targetDatabase": TARGET_DATABASE,
            "scriptHash": script_hash,
            "sourceSchemaHashes": baseline["sourceSchemaHashes"],
            "targetSchemaHash": baseline["targetSchemaHash"],
            "targetState": baseline["targetState"],
            "targetStateHash": _sha256_json(baseline["targetState"]),
            "sourceRows": baseline["sourceRows"],
            "approvedSourceScope": baseline["approvedSourceScope"],
            "copyMode": "single_database_side_set_based_sql",
            "coldHistoryAction": "copy_missing_rows_set_based",
            "sourceDmlStatements": 0,
            "targetBackupRequired": False,
        }
        if approved_partial_recovery:
            immutable["recoveryMode"] = "approved_partial_target_rebase_v1"
            immutable["recoveryFromPreviewHash"] = existing.get("planHash")
        plan_hash = _sha256_json(immutable)
        preview = {
            **immutable,
            "planHash": plan_hash,
            "previewedAt": datetime.now(timezone.utc).isoformat(),
        }
        if existing:
            preview["supersededPreviewHash"] = existing.get("planHash")
        _write_json_atomic(self._preview_path(clean_key), preview)
        return _preview_result(preview, replay=False)

    def status(self, *, idempotency_key: str) -> dict[str, Any]:
        clean_key = _idempotency_key(idempotency_key)
        preview = _read_json_required(self._preview_path(clean_key), "preview")
        receipt = _read_json_optional(self._receipt_path(clean_key))
        with closing(self._connect(True)) as connection:
            baseline = _baseline(connection.cursor())
            readback = _completion_readback(connection.cursor())
        if receipt:
            return _completed_result(receipt, replay=True)
        script_hash_matches = preview.get("scriptHash") == hashlib.sha256(
            self._script().encode("utf-8")
        ).hexdigest()
        target_matches = (
            _sha256_json(baseline["targetState"])
            == preview.get("targetStateHash")
        )
        return {
            "ok": True,
            "operation": "nova_sql_instyle_demo_sync_status",
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
            "targetMatchesPreview": target_matches,
            "scriptHashMatchesPreview": script_hash_matches,
            "approvedSourceScope": baseline["approvedSourceScope"],
            "readback": readback,
            "safeToRetry": bool(
                script_hash_matches
                and target_matches
                and not readback["completionVerified"]
            ),
        }

    def execute(
        self,
        *,
        idempotency_key: str,
        preview_hash: str,
    ) -> dict[str, Any]:
        clean_key = _idempotency_key(idempotency_key)
        clean_hash = str(preview_hash or "").strip().lower()
        if not HASH.fullmatch(clean_hash):
            raise InstyleDemoRebuildScopeError(
                "preview_hash must be the exact hash returned by "
                "nova_sql_instyle_demo_sync_preview"
            )
        preview = _read_json_required(self._preview_path(clean_key), "preview")
        if (
            preview.get("operation") != OPERATION_NAME
            or preview.get("idempotencyKey") != clean_key
            or preview.get("planHash") != clean_hash
        ):
            raise InstyleDemoRebuildScopeError(
                "preview hash, idempotency key, or fixed SQL plan does not match"
            )
        completed = _read_json_optional(self._receipt_path(clean_key))
        if completed:
            return _completed_result(completed, replay=True)

        script = self._script()
        if hashlib.sha256(script.encode("utf-8")).hexdigest() != preview.get(
            "scriptHash"
        ):
            raise InstyleDemoRebuildScopeError(
                "the packaged SQL script changed after preview; create a new preview"
            )

        with closing(self._connect(False)) as connection:
            cursor = connection.cursor()
            if hasattr(cursor, "timeout"):
                cursor.timeout = self._query_timeout_seconds
            current = _baseline(cursor)
            if current["targetSchemaHash"] != preview.get("targetSchemaHash"):
                raise InstyleDemoRebuildScopeError(
                    "the demo target schema changed after preview"
                )
            if current["sourceSchemaHashes"] != preview.get("sourceSchemaHashes"):
                raise InstyleDemoRebuildScopeError(
                    "a fixed source schema changed after preview"
                )
            if current["approvedSourceScope"] != preview.get(
                "approvedSourceScope"
            ):
                raise InstyleDemoRebuildScopeError(
                    "the approved 107-product/142-line source scope changed "
                    "after preview"
                )
            _validate_approved_source_scope(current["approvedSourceScope"])
            if _sha256_json(current["targetState"]) != preview.get(
                "targetStateHash"
            ):
                raise InstyleDemoRebuildScopeError(
                    "the demo target changed after preview; create a new preview"
                )
            started = datetime.now(timezone.utc)
            parameter_prefix = (
                "DECLARE @Apply bit=?;"
                "DECLARE @OperatorIdempotencyKey nvarchar(200)=?;"
                "DECLARE @OperatorPlanHash char(64)=?;"
                "DECLARE @ExpectedTargetStateHash char(64)=?;"
            )
            cursor.execute(
                parameter_prefix + script,
                1,
                clean_key,
                clean_hash,
                str(preview["targetStateHash"]),
            )
            result = _last_json_result(cursor)
            readback = _completion_readback(cursor)
            if not readback["completionVerified"]:
                raise InstyleDemoRebuildUnavailableError(
                    "set-based SQL completed without passing final Nova readback"
                )

        receipt = {
            "version": 1,
            "operation": OPERATION_NAME,
            "status": "completed",
            "idempotencyKey": clean_key,
            "planHash": clean_hash,
            "scriptHash": preview["scriptHash"],
            "startedAt": started.isoformat(),
            "completedAt": datetime.now(timezone.utc).isoformat(),
            "fixedSources": [SOURCE_A_USERNAME, SOURCE_B_USERNAME],
            "fixedTarget": TARGET_USERNAME,
            "sourceDatabasesReadOnly": True,
            "targetBackupCreated": False,
            "targetBackupRequired": False,
            "copyMode": "single_database_side_set_based_sql",
            "sqlResult": result,
            "readback": readback,
            "postWriteReadbackVerified": True,
        }
        _write_json_atomic(self._receipt_path(clean_key), receipt)
        return _completed_result(receipt, replay=False)

    def _script(self) -> str:
        if not INSTYLE_DEMO_MERGE_SQL_V2.strip():
            raise InstyleDemoRebuildUnavailableError(
                "the fixed set-based Instyle SQL resource is unavailable"
            )
        return INSTYLE_DEMO_MERGE_SQL_V2

    def _preview_path(self, idempotency_key: str) -> Path:
        return self._state_path("preview", idempotency_key)

    def _receipt_path(self, idempotency_key: str) -> Path:
        return self._state_path("receipt", idempotency_key)

    def _state_path(self, kind: str, idempotency_key: str) -> Path:
        digest = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()
        return self._state_dir / f"{digest}.{kind}.json"


def _baseline(cursor: Any) -> dict[str, Any]:
    row = cursor.execute(
        "SELECT DB_NAME(),DB_ID(?),DB_ID(?),DB_ID(?),"
        "HAS_DBACCESS(?),HAS_DBACCESS(?)",
        TARGET_DATABASE,
        SOURCE_A_DATABASE,
        SOURCE_B_DATABASE,
        SOURCE_A_DATABASE,
        SOURCE_B_DATABASE,
    ).fetchone()
    if not row or str(row[0] or "").casefold() != TARGET_DATABASE.casefold():
        raise InstyleDemoRebuildScopeError(
            "developer connection is not bound to the fixed demo target"
        )
    if any(value is None for value in row[1:4]) or int(row[4] or 0) != 1 or int(
        row[5] or 0
    ) != 1:
        raise InstyleDemoRebuildUnavailableError(
            "the fixed developer broker cannot read both Instyle sources and the demo target"
        )
    source_hashes = {
        SOURCE_A_DATABASE: _schema_hash(cursor, SOURCE_A_DATABASE),
        SOURCE_B_DATABASE: _schema_hash(cursor, SOURCE_B_DATABASE),
    }
    target_schema_hash = _schema_hash(cursor, TARGET_DATABASE)
    state_row = cursor.execute(
        "SELECT "
        "(SELECT COUNT_BIG(*) FROM dbo.Products),"
        "(SELECT COUNT_BIG(*) FROM dbo.Invoice_Products),"
        "(SELECT COUNT_BIG(*) FROM dbo.InventoryHistoryItem),"
        "(SELECT COUNT_BIG(*) FROM dbo.Locations),"
        "(SELECT COUNT_BIG(*) FROM dbo.Regions)"
    ).fetchone()
    product_map_rows = _optional_product_map_rows(cursor)
    target_state = {
        "productRows": int(state_row[0] or 0),
        "invoiceProductRows": int(state_row[1] or 0),
        "inventoryHistoryItemRows": int(state_row[2] or 0),
        "locations": int(state_row[3] or 0),
        "regions": int(state_row[4] or 0),
        "productMapRows": product_map_rows,
        "invoiceProductsWithBlankInvoiceId": int(
            cursor.execute(
                "SELECT COUNT_BIG(*) FROM dbo.Invoice_Products WHERE InvoiceID IS NULL"
            ).fetchone()[0]
            or 0
        ),
    }
    return {
        "sourceSchemaHashes": source_hashes,
        "targetSchemaHash": target_schema_hash,
        "targetState": target_state,
        "sourceRows": {
            database: _estimated_rows(cursor, database)
            for database in (SOURCE_A_DATABASE, SOURCE_B_DATABASE)
        },
        "approvedSourceScope": _approved_source_scope(cursor),
    }


def _approved_source_scope(cursor: Any) -> dict[str, Any]:
    by_source: dict[str, dict[str, int]] = {}
    for database in (SOURCE_A_DATABASE, SOURCE_B_DATABASE):
        quoted = _quote_identifier(database)
        qualified = cursor.execute(
            "SELECT COUNT_BIG(*),COUNT_BIG(DISTINCT ip.ProductID) "
            f"FROM {quoted}.dbo.Invoice_Products ip "
            f"JOIN {quoted}.dbo.Invoices i ON i.InvoiceID=ip.InvoiceID "
            f"LEFT JOIN {quoted}.dbo.Products p ON p.ProductID=ip.ProductID "
            "WHERE ip.ProductID>0 AND p.ProductID IS NULL"
        ).fetchone()
        quarantined = cursor.execute(
            "SELECT COUNT_BIG(*) "
            f"FROM {quoted}.dbo.Invoice_Products ip "
            f"LEFT JOIN {quoted}.dbo.Invoices i ON i.InvoiceID=ip.InvoiceID "
            "WHERE ip.InvoiceID IS NULL OR i.InvoiceID IS NULL"
        ).fetchone()
        by_source[database] = {
            "qualifiedInvoiceLines": int(qualified[0] or 0),
            "qualifiedPlaceholderProducts": int(qualified[1] or 0),
            "quarantinedInvoiceProductRows": int(quarantined[0] or 0),
        }
    return {
        "bySource": by_source,
        "qualifiedInvoiceLines": sum(
            item["qualifiedInvoiceLines"] for item in by_source.values()
        ),
        "qualifiedPlaceholderProducts": sum(
            item["qualifiedPlaceholderProducts"] for item in by_source.values()
        ),
        "quarantinedInvoiceProductRows": sum(
            item["quarantinedInvoiceProductRows"] for item in by_source.values()
        ),
    }


def _validate_approved_source_scope(scope: dict[str, Any]) -> None:
    if int(scope.get("qualifiedPlaceholderProducts") or 0) != (
        EXPECTED_PLACEHOLDER_PRODUCTS
    ):
        raise InstyleDemoRebuildScopeError(
            "the fixed source no longer has exactly 107 approved missing "
            "invoice products"
        )
    if int(scope.get("qualifiedInvoiceLines") or 0) != (
        EXPECTED_PLACEHOLDER_INVOICE_LINES
    ):
        raise InstyleDemoRebuildScopeError(
            "the fixed source no longer has exactly 142 approved invoice lines"
        )
    if int(scope.get("quarantinedInvoiceProductRows") or 0) != (
        EXPECTED_QUARANTINED_INVOICE_PRODUCT_ROWS
    ):
        raise InstyleDemoRebuildScopeError(
            "the fixed source no longer has exactly 11 quarantined "
            "invoice-less rows"
        )


def _is_approved_partial_target_recovery(
    *,
    existing: dict[str, Any],
    idempotency_key: str,
    baseline: dict[str, Any],
    readback: dict[str, Any],
) -> bool:
    """Recognize only the reviewed incomplete demo state from the prior run."""
    state = baseline.get("targetState") or {}
    approved_scope = baseline.get("approvedSourceScope") or {}
    return bool(
        existing.get("operation") == OPERATION_NAME
        and existing.get("idempotencyKey") == idempotency_key
        and existing.get("planHash") == APPROVED_PARTIAL_PREVIEW_HASH
        and existing.get("fixedSources")
        == [SOURCE_A_USERNAME, SOURCE_B_USERNAME]
        and existing.get("fixedTarget") == TARGET_USERNAME
        and (
            existing.get("approvedSourceScope") in (None, approved_scope)
        )
        and all(
            int(state.get(key) or 0) == expected
            for key, expected in APPROVED_PARTIAL_TARGET_STATE.items()
        )
        and bool(readback.get("productMapPresent"))
        and not bool(readback.get("completionVerified"))
        and bool(readback.get("inventoryHistoryCoverageCurrent"))
        and int(readback.get("duplicateNonblankProductKeys") or 0) == 0
        and int(readback.get("invoiceProductsWithBlankInvoiceId") or 0) == 0
        and int(readback.get("placeholderRequiredFieldGaps") or 0) == 0
        and int(readback.get("productOrphanRows") or 0) > 0
        and int(readback.get("qualifiedPlaceholderProducts") or 0)
        == APPROVED_PARTIAL_PLACEHOLDER_PRODUCTS
        and int(readback.get("qualifiedPlaceholderInvoiceLines") or 0)
        == APPROVED_PARTIAL_PLACEHOLDER_INVOICE_LINES
        and int(readback.get("quarantinedInvoiceProductRows") or 0)
        == EXPECTED_QUARANTINED_INVOICE_PRODUCT_ROWS
    )


def _optional_product_map_rows(cursor: Any) -> int:
    exists = bool(
        cursor.execute(
            "SELECT CASE WHEN OBJECT_ID('dbo.__codex_instyle_core_product_map','U') "
            "IS NULL THEN 0 ELSE 1 END"
        ).fetchone()[0]
    )
    if not exists:
        return 0
    return int(
        cursor.execute(
            "SELECT COUNT_BIG(*) FROM dbo.__codex_instyle_core_product_map"
        ).fetchone()[0]
        or 0
    )


def _schema_hash(cursor: Any, database: str) -> str:
    quoted = _quote_identifier(database)
    rows = cursor.execute(
        "SELECT s.name,t.name,c.column_id,c.name,ty.name,"
        "c.max_length,c.precision,c.scale,c.is_nullable,c.is_identity,"
        "c.is_computed,c.generated_always_type "
        f"FROM {quoted}.sys.tables t "
        f"JOIN {quoted}.sys.schemas s ON s.schema_id=t.schema_id "
        f"JOIN {quoted}.sys.columns c ON c.object_id=t.object_id "
        f"JOIN {quoted}.sys.types ty ON ty.user_type_id=c.user_type_id "
        "WHERE t.is_ms_shipped=0 "
        "ORDER BY s.name,t.name,c.column_id"
    ).fetchall()
    serialized = json.dumps(
        [[str(item) if item is not None else "" for item in row] for row in rows],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    value = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    if not HASH.fullmatch(value):
        raise InstyleDemoRebuildUnavailableError(
            f"could not fingerprint fixed database {database}"
        )
    return value


def _estimated_rows(cursor: Any, database: str) -> dict[str, int]:
    quoted = _quote_identifier(database)
    row = cursor.execute(
        "SELECT "
        "SUM(CASE WHEN t.name NOT IN ('Log4Net') THEN p.rows ELSE 0 END),"
        "SUM(CASE WHEN t.name='InventoryHistoryItem' THEN p.rows ELSE 0 END),"
        "SUM(CASE WHEN t.name='Products' THEN p.rows ELSE 0 END) "
        f"FROM {quoted}.sys.tables t "
        f"JOIN {quoted}.sys.partitions p ON p.object_id=t.object_id "
        "AND p.index_id IN (0,1) WHERE t.is_ms_shipped=0"
    ).fetchone()
    return {
        "businessRows": int(row[0] or 0),
        "inventoryHistoryItemRows": int(row[1] or 0),
        "productRows": int(row[2] or 0),
    }


def _completion_readback(cursor: Any) -> dict[str, Any]:
    row = cursor.execute(
        "SELECT "
        "(SELECT COUNT_BIG(*) FROM dbo.Products),"
        "(SELECT COUNT_BIG(*) FROM dbo.Invoice_Products),"
        "(SELECT COUNT_BIG(*) FROM dbo.InventoryHistoryItem),"
        "(SELECT COUNT_BIG(*) FROM dbo.Locations),"
        "(SELECT COUNT_BIG(*) FROM dbo.Regions),"
        "(SELECT COUNT_BIG(*) FROM dbo.Invoice_Products WHERE InvoiceID IS NULL)"
    ).fetchone()
    duplicates = int(
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
    map_exists = bool(
        cursor.execute(
            "SELECT CASE WHEN OBJECT_ID('dbo.__codex_instyle_core_product_map','U') "
            "IS NULL THEN 0 ELSE 1 END"
        ).fetchone()[0]
    )
    placeholder_gaps = None
    if map_exists:
        placeholder_gaps = int(
            cursor.execute(
                "SELECT COUNT_BIG(*) FROM dbo.__codex_instyle_core_product_map m "
                "JOIN dbo.Products p ON p.ProductID=m.TargetProductID "
                "WHERE m.IsPlaceholder=1 AND ("
                "NULLIF(LTRIM(RTRIM(p.ProductName)),'') IS NULL OR "
                "NULLIF(LTRIM(RTRIM(p.SKU)),'') IS NULL OR "
                "NULLIF(LTRIM(RTRIM(p.BarcodeNumber)),'') IS NULL)"
            ).fetchone()[0]
            or 0
        )
    placeholder_products = None
    placeholder_invoice_lines = None
    if map_exists:
        placeholder_products = int(
            cursor.execute(
                "SELECT COUNT_BIG(*) "
                "FROM dbo.__codex_instyle_core_product_map "
                "WHERE IsPlaceholder=1"
            ).fetchone()[0]
            or 0
        )
        placeholder_invoice_lines = int(
            cursor.execute(
                "SELECT COUNT_BIG(*) FROM dbo.Invoice_Products ip "
                "JOIN dbo.__codex_instyle_core_product_map m "
                "ON m.TargetProductID=ip.ProductID "
                "WHERE m.IsPlaceholder=1"
            ).fetchone()[0]
            or 0
        )
    orphan_rows = _product_orphan_count(cursor)
    source_history = sum(
        _estimated_rows(cursor, database)["inventoryHistoryItemRows"]
        for database in (SOURCE_A_DATABASE, SOURCE_B_DATABASE)
    )
    source_scope = _approved_source_scope(cursor)
    result = {
        "productRows": int(row[0] or 0),
        "invoiceProductRows": int(row[1] or 0),
        "inventoryHistoryItemRows": int(row[2] or 0),
        "locations": int(row[3] or 0),
        "regions": int(row[4] or 0),
        "invoiceProductsWithBlankInvoiceId": int(row[5] or 0),
        "duplicateNonblankProductKeys": duplicates,
        "productOrphanRows": orphan_rows,
        "placeholderRequiredFieldGaps": placeholder_gaps,
        "qualifiedPlaceholderProducts": placeholder_products,
        "qualifiedPlaceholderInvoiceLines": placeholder_invoice_lines,
        "quarantinedInvoiceProductRows": source_scope[
            "quarantinedInvoiceProductRows"
        ],
        "expectedInventoryHistoryItemRows": source_history,
        "inventoryHistoryCoverageCurrent": int(row[2] or 0) >= source_history,
        "productMapPresent": map_exists,
    }
    result["completionVerified"] = bool(
        map_exists
        and duplicates == 0
        and orphan_rows == 0
        and int(row[5] or 0) == 0
        and placeholder_gaps == 0
        and placeholder_products == EXPECTED_PLACEHOLDER_PRODUCTS
        and placeholder_invoice_lines == EXPECTED_PLACEHOLDER_INVOICE_LINES
        and source_scope["quarantinedInvoiceProductRows"]
        == EXPECTED_QUARANTINED_INVOICE_PRODUCT_ROWS
        and int(row[3] or 0) == 44
        and int(row[4] or 0) == 4
    )
    return result


def _product_orphan_count(cursor: Any) -> int:
    total = 0
    for table, column in PRODUCT_REFERENCE_COLUMNS:
        row = cursor.execute(
            "SELECT CASE WHEN OBJECT_ID(?, 'U') IS NULL THEN 0 ELSE 1 END",
            f"dbo.{table}",
        ).fetchone()
        if not row or int(row[0] or 0) != 1:
            continue
        total += int(
            cursor.execute(
                f"SELECT COUNT_BIG(*) FROM dbo.{_quote_identifier(table)} x "
                f"LEFT JOIN dbo.Products p ON p.ProductID=x.{_quote_identifier(column)} "
                f"WHERE x.{_quote_identifier(column)}>0 AND p.ProductID IS NULL"
            ).fetchone()[0]
            or 0
        )
    return total


def _last_json_result(cursor: Any) -> dict[str, Any]:
    result: dict[str, Any] = {}
    while True:
        if cursor.description:
            columns = [str(item[0]) for item in cursor.description]
            rows = cursor.fetchall()
            if rows and "ResultJson" in columns:
                raw = rows[-1][columns.index("ResultJson")]
                if raw:
                    result = json.loads(str(raw))
        if not cursor.nextset():
            break
    return result


def _idempotency_key(value: str) -> str:
    clean = str(value or "").strip()
    if not IDEMPOTENCY_KEY.fullmatch(clean):
        raise InstyleDemoRebuildScopeError(
            "idempotency_key must be a stable 8-200 character operation identifier"
        )
    return clean


def _sha256_json(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()


def _quote_identifier(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,127}", value):
        raise InstyleDemoRebuildScopeError("fixed SQL identifier is invalid")
    return "[" + value.replace("]", "]]") + "]"


def _preview_result(preview: dict[str, Any], *, replay: bool) -> dict[str, Any]:
    return {
        "ok": True,
        "operation": "nova_sql_instyle_demo_sync_preview",
        "status": "previewed",
        "replay": replay,
        "idempotencyKey": preview.get("idempotencyKey"),
        "previewHash": preview.get("planHash"),
        "fixedSources": preview.get("fixedSources"),
        "fixedTarget": preview.get("fixedTarget"),
        "sourceDatabasesReadOnly": True,
        "targetBackupRequired": False,
        "copyMode": preview.get("copyMode"),
        "coldHistoryAction": preview.get("coldHistoryAction"),
        "targetBaseline": preview.get("targetState"),
        "sourceRows": preview.get("sourceRows"),
        "approvedSourceScope": preview.get("approvedSourceScope"),
        "nextStep": (
            "Call nova_sql_instyle_demo_sync_execute with this same idempotency "
            "key and exact preview hash."
        ),
    }


def _completed_result(receipt: dict[str, Any], *, replay: bool) -> dict[str, Any]:
    return {
        "ok": True,
        "operation": "nova_sql_instyle_demo_sync_execute",
        "status": receipt.get("status"),
        "replay": replay,
        "idempotencyKey": receipt.get("idempotencyKey"),
        "previewHash": receipt.get("planHash"),
        "fixedSources": receipt.get("fixedSources"),
        "fixedTarget": receipt.get("fixedTarget"),
        "sourceDatabasesReadOnly": receipt.get("sourceDatabasesReadOnly"),
        "targetBackupCreated": receipt.get("targetBackupCreated"),
        "targetBackupRequired": receipt.get("targetBackupRequired"),
        "copyMode": receipt.get("copyMode"),
        "sqlResult": receipt.get("sqlResult"),
        "readback": receipt.get("readback"),
        "postWriteReadbackVerified": receipt.get("postWriteReadbackVerified"),
    }


def execution_failure_result(
    *,
    idempotency_key: str,
    preview_hash: str,
    error: Exception,
) -> dict[str, Any]:
    return {
        "ok": False,
        "operation": "nova_sql_instyle_demo_sync_execute",
        "status": "execution_failed_reconciliation_required",
        "idempotencyKey": str(idempotency_key or ""),
        "previewHash": str(preview_hash or ""),
        "errorType": type(error).__name__,
        "error": str(error) or repr(error),
        "fixedSources": [SOURCE_A_USERNAME, SOURCE_B_USERNAME],
        "fixedTarget": TARGET_USERNAME,
        "sourceDatabasesReadOnly": True,
        "nextStep": (
            "Call nova_sql_instyle_demo_sync_status with this idempotency key "
            "before any retry."
        ),
    }
