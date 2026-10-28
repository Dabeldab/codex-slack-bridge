from __future__ import annotations

# AgentChat/coding_agent 2026-08-03T19:24:00Z

import hashlib
import json
import re
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


OPERATION_NAME = "oklahoma_hawaii_catalog_replace_v1"
OPERATION_TOOLS = (
    "nova_sql_oklahoma_hawaii_catalog_replace_preview",
    "nova_sql_oklahoma_hawaii_catalog_replace_status",
    "nova_sql_oklahoma_hawaii_catalog_replace_execute",
)
SOURCE_USERNAME = "unique_lifestyle_llc"
SOURCE_DATABASE = "POS_unique_lifestyle_llc"
TARGET_USERNAME = "oklahoma"
TARGET_DATABASE = "POS_oklahoma"
CATEGORY_NAME = "HAWAII"
CATEGORY_ID = 87
REQUIRED_IDEMPOTENCY_KEY = "rory-8702-oklahoma-hawaii-full-replace-v1"
DELETE_POLICY_EXCEPTION = "fixed_oklahoma_hawaii_catalog_replace_only"
CALLER_SELECTED_DELETE_ALLOWED = False
EXPECTED_TARGET_COUNTS = {"products": 723, "categories": 6, "wholesalers": 1}
EXPECTED_SOURCE_COUNTS = {"products": 26, "categories": 1, "wholesalers": 0}
EXPECTED_PRODUCT_ID_COLLISIONS = 0
MAX_CHANGED_ROWS = 1_000
HASH = re.compile(r"^[0-9a-f]{64}$")

PRODUCT_COLUMNS = (
    "ProductID",
    "ProductName",
    "ProductPhoto",
    "ProductDescription",
    "ProductCostPrice",
    "ProductMinPrice",
    "ProductMarkupPrice",
    "ProductIsAvailable",
    "BarcodeNumber",
    "BarcodeNumber2",
    "Color",
    "WholesalerID",
    "ProductComission",
    "Product_CategoryID",
    "IsFixedPrice",
    "Size",
    "Attr",
    "IsDiffTaxRate",
    "DiffTaxRate",
    "IsLockProductMarkupPrice",
    "IsTaxIncluded",
    "SKU",
    "LastPurchaseCostPrice",
    "IsLockProductMinimumPrice",
    "CommissionType",
    "Version",
    "IsTracked",
    "VariantName1",
    "VariantName2",
    "ProductFamilyId",
    "CreatedBy",
    "CreatedOn",
)
CATEGORY_COLUMNS = (
    "Products_CategoryID",
    "Products_CategoryName",
    "ParentID",
    "Products_CategoryPhoto",
    "Version",
)
WHOLESALER_COLUMNS = (
    "WholesalerID",
    "WholesalerName",
    "WholesalerEmail",
    "Version",
)
CHANGED_TABLES = (
    ("dbo.Products", "Products", PRODUCT_COLUMNS, "ProductID"),
    (
        "dbo.Products_Categories",
        "Products_Categories",
        CATEGORY_COLUMNS,
        "Products_CategoryID",
    ),
    (
        "dbo.Products_Wholesalers",
        "Products_Wholesalers",
        WHOLESALER_COLUMNS,
        "WholesalerID",
    ),
)

# This is the complete live-column signature observed before authoring the fixed
# operation. Backup tables are intentionally excluded. A new product/category/
# wholesaler-shaped dependency blocks execution until it is reviewed.
EXPECTED_DEPENDENCY_COLUMNS = frozenset(
    {
        ("dbo", "coupons_products", "categoryid"),
        ("dbo", "coupons_products", "productid"),
        ("dbo", "customerorders_products", "productid"),
        ("dbo", "expenses_categories", "categoryid"),
        ("dbo", "inventory", "productid"),
        ("dbo", "inventory_counts_products", "productid"),
        ("dbo", "inventory_counts_products", "categoryid"),
        ("dbo", "inventory_damage", "productid"),
        ("dbo", "inventory_transactions", "productid"),
        ("dbo", "invoice_products", "productid"),
        ("dbo", "invoice_refunds", "productid"),
        ("dbo", "pending_invoice_product", "productid"),
        ("dbo", "pricelists_items", "productid"),
        ("dbo", "productfamily", "categoryid"),
        ("dbo", "productfavorites", "productid"),
        ("dbo", "products", "productid"),
        ("dbo", "products", "wholesalerid"),
        ("dbo", "products", "product_categoryid"),
        ("dbo", "products_categories", "products_categoryid"),
        ("dbo", "products_wholesalers", "wholesalerid"),
        ("dbo", "quote_products", "productid"),
        ("dbo", "refunds_products", "productid"),
        ("dbo", "storageorders_products", "productid"),
    }
)
EXPECTED_FOREIGN_KEYS = frozenset(
    {
        (
            "dbo",
            "productfavorites",
            "productid",
            "dbo",
            "products",
            "productid",
            "cascade",
        )
    }
)

DEPENDENCY_COLUMN_SQL = """
SELECT s.name, t.name, c.name
FROM sys.tables AS t
JOIN sys.schemas AS s ON s.schema_id=t.schema_id
JOIN sys.columns AS c ON c.object_id=t.object_id
WHERE (
    c.name IN ('ProductID','ProductId','Product_CategoryID','Products_CategoryID','WholesalerID','CategoryID')
)
AND t.name NOT LIKE '__codex_bak[_]%'
ORDER BY s.name,t.name,c.column_id
""".strip()

FOREIGN_KEY_SQL = """
SELECT ps.name, pt.name, pc.name, rs.name, rt.name, rc.name,
       fk.delete_referential_action_desc
FROM sys.foreign_keys AS fk
JOIN sys.foreign_key_columns AS fkc ON fkc.constraint_object_id=fk.object_id
JOIN sys.tables AS pt ON pt.object_id=fkc.parent_object_id
JOIN sys.schemas AS ps ON ps.schema_id=pt.schema_id
JOIN sys.columns AS pc ON pc.object_id=pt.object_id AND pc.column_id=fkc.parent_column_id
JOIN sys.tables AS rt ON rt.object_id=fkc.referenced_object_id
JOIN sys.schemas AS rs ON rs.schema_id=rt.schema_id
JOIN sys.columns AS rc ON rc.object_id=rt.object_id AND rc.column_id=fkc.referenced_column_id
WHERE fk.referenced_object_id IN (
    OBJECT_ID('dbo.Products'),OBJECT_ID('dbo.Products_Categories'),OBJECT_ID('dbo.Products_Wholesalers')
)
ORDER BY ps.name,pt.name,pc.name
""".strip()

EXTERNAL_DEPENDENCY_SQL = """
SELECT 'Coupons_Products.ProductID', COUNT_BIG(*) FROM dbo.Coupons_Products AS d {d_hint} JOIN dbo.Products AS p {p_hint} ON p.ProductID=d.ProductID
UNION ALL SELECT 'CustomerOrders_Products.ProductID', COUNT_BIG(*) FROM dbo.CustomerOrders_Products AS d {d_hint} JOIN dbo.Products AS p {p_hint} ON p.ProductID=d.ProductID
UNION ALL SELECT 'Inventory.ProductID', COUNT_BIG(*) FROM dbo.Inventory AS d {d_hint} JOIN dbo.Products AS p {p_hint} ON p.ProductID=d.ProductID
UNION ALL SELECT 'Inventory_Counts_Products.ProductID', COUNT_BIG(*) FROM dbo.Inventory_Counts_Products AS d {d_hint} JOIN dbo.Products AS p {p_hint} ON p.ProductID=d.ProductID
UNION ALL SELECT 'Inventory_Damage.ProductID', COUNT_BIG(*) FROM dbo.Inventory_Damage AS d {d_hint} JOIN dbo.Products AS p {p_hint} ON p.ProductID=d.ProductID
UNION ALL SELECT 'Inventory_Transactions.ProductID', COUNT_BIG(*) FROM dbo.Inventory_Transactions AS d {d_hint} JOIN dbo.Products AS p {p_hint} ON p.ProductID=d.ProductID
UNION ALL SELECT 'Invoice_Products.ProductID', COUNT_BIG(*) FROM dbo.Invoice_Products AS d {d_hint} JOIN dbo.Products AS p {p_hint} ON p.ProductID=d.ProductID
UNION ALL SELECT 'Invoice_Refunds.ProductID', COUNT_BIG(*) FROM dbo.Invoice_Refunds AS d {d_hint} JOIN dbo.Products AS p {p_hint} ON p.ProductID=d.ProductID
UNION ALL SELECT 'Pending_Invoice_Product.ProductId', COUNT_BIG(*) FROM dbo.Pending_Invoice_Product AS d {d_hint} JOIN dbo.Products AS p {p_hint} ON p.ProductID=d.ProductId
UNION ALL SELECT 'PriceLists_Items.ProductID', COUNT_BIG(*) FROM dbo.PriceLists_Items AS d {d_hint} JOIN dbo.Products AS p {p_hint} ON p.ProductID=d.ProductID
UNION ALL SELECT 'ProductFavorites.ProductId', COUNT_BIG(*) FROM dbo.ProductFavorites AS d {d_hint} JOIN dbo.Products AS p {p_hint} ON p.ProductID=d.ProductId
UNION ALL SELECT 'Quote_Products.ProductId', COUNT_BIG(*) FROM dbo.Quote_Products AS d {d_hint} JOIN dbo.Products AS p {p_hint} ON p.ProductID=d.ProductId
UNION ALL SELECT 'Refunds_Products.ProductID', COUNT_BIG(*) FROM dbo.Refunds_Products AS d {d_hint} JOIN dbo.Products AS p {p_hint} ON p.ProductID=d.ProductID
UNION ALL SELECT 'StorageOrders_Products.ProductID', COUNT_BIG(*) FROM dbo.StorageOrders_Products AS d {d_hint} JOIN dbo.Products AS p {p_hint} ON p.ProductID=d.ProductID
UNION ALL SELECT 'Coupons_Products.CategoryID', COUNT_BIG(*) FROM dbo.Coupons_Products AS d {d_hint} JOIN dbo.Products_Categories AS c {p_hint} ON c.Products_CategoryID=d.CategoryID
UNION ALL SELECT 'Inventory_Counts_Products.CategoryID', COUNT_BIG(*) FROM dbo.Inventory_Counts_Products AS d {d_hint} JOIN dbo.Products_Categories AS c {p_hint} ON c.Products_CategoryID=d.CategoryID
UNION ALL SELECT 'ProductFamily.CategoryID', COUNT_BIG(*) FROM dbo.ProductFamily AS d {d_hint} JOIN dbo.Products_Categories AS c {p_hint} ON c.Products_CategoryID=d.CategoryID
""".strip()

TARGET_COUNT_SQL = """
SELECT
    (SELECT COUNT_BIG(*) FROM dbo.Products {target_hint}) AS Products,
    (SELECT COUNT_BIG(*) FROM dbo.Products_Categories {target_hint}) AS Categories,
    (SELECT COUNT_BIG(*) FROM dbo.Products_Wholesalers {target_hint}) AS Wholesalers
""".strip()

SOURCE_CATEGORY_SQL = f"""
SELECT Products_CategoryID,Products_CategoryName,ParentID,Version
FROM [{SOURCE_DATABASE}].dbo.Products_Categories {{source_hint}}
WHERE UPPER(LTRIM(RTRIM(Products_CategoryName)))='{CATEGORY_NAME}'
ORDER BY Products_CategoryID
""".strip()

SOURCE_SUMMARY_SQL = f"""
SELECT COUNT_BIG(*) AS Products,
       COUNT_BIG(DISTINCT CASE WHEN w.WholesalerID IS NOT NULL THEN w.WholesalerID END) AS RequiredWholesalers,
       SUM(CASE WHEN p.WholesalerID NOT IN (-1,0) AND p.WholesalerID IS NOT NULL AND w.WholesalerID IS NULL THEN 1 ELSE 0 END) AS MissingWholesalerReferences,
       SUM(CASE WHEN p.ProductFamilyId IS NOT NULL THEN 1 ELSE 0 END) AS ProductFamilyReferences,
       SUM(CASE WHEN p.CreatedBy IS NOT NULL THEN 1 ELSE 0 END) AS CreatedByReferences,
       MIN(p.ProductID) AS MinProductID,
       MAX(p.ProductID) AS MaxProductID
FROM [{SOURCE_DATABASE}].dbo.Products AS p {{source_hint}}
LEFT JOIN [{SOURCE_DATABASE}].dbo.Products_Wholesalers AS w {{source_hint}} ON w.WholesalerID=p.WholesalerID
WHERE p.Product_CategoryID={CATEGORY_ID}
""".strip()

COLLISION_SQL = f"""
SELECT COUNT_BIG(*)
FROM [{SOURCE_DATABASE}].dbo.Products AS s {{source_hint}}
JOIN dbo.Products AS t {{target_hint}} ON t.ProductID=s.ProductID
WHERE s.Product_CategoryID={CATEGORY_ID}
""".strip()

TRIGGER_SQL = """
SELECT OBJECT_SCHEMA_NAME(parent_id),OBJECT_NAME(parent_id),name,is_disabled
FROM sys.triggers
WHERE parent_id IN (OBJECT_ID('dbo.Products'),OBJECT_ID('dbo.Products_Categories'),OBJECT_ID('dbo.Products_Wholesalers'))
ORDER BY OBJECT_SCHEMA_NAME(parent_id),OBJECT_NAME(parent_id),name
""".strip()

READBACK_SQL = f"""
SELECT
    (SELECT COUNT_BIG(*) FROM dbo.Products) AS Products,
    (SELECT COUNT_BIG(*) FROM dbo.Products_Categories) AS Categories,
    (SELECT COUNT_BIG(*) FROM dbo.Products_Wholesalers) AS Wholesalers,
    (SELECT COUNT_BIG(*) FROM dbo.Products WHERE Product_CategoryID<>{CATEGORY_ID}) AS NonHawaiiProducts,
    (SELECT COUNT_BIG(*) FROM dbo.Products_Categories WHERE Products_CategoryID<>{CATEGORY_ID} OR UPPER(LTRIM(RTRIM(Products_CategoryName)))<>'{CATEGORY_NAME}') AS NonHawaiiCategories,
    (SELECT COUNT_BIG(*) FROM dbo.Products AS p LEFT JOIN dbo.Products_Categories AS c ON c.Products_CategoryID=p.Product_CategoryID WHERE c.Products_CategoryID IS NULL) AS OrphanCategoryReferences,
    (SELECT COUNT_BIG(*) FROM dbo.Products AS p LEFT JOIN dbo.Products_Wholesalers AS w ON w.WholesalerID=p.WholesalerID WHERE p.WholesalerID NOT IN (-1,0) AND p.WholesalerID IS NOT NULL AND w.WholesalerID IS NULL) AS OrphanWholesalerReferences,
    (SELECT COUNT_BIG(*) FROM dbo.Products WHERE ProductFamilyId IS NOT NULL) AS ProductFamilyReferences,
    (SELECT COUNT_BIG(*) FROM dbo.Products WHERE CreatedBy IS NOT NULL) AS CreatedByReferences,
    (SELECT COUNT_BIG(*) FROM dbo.Products AS t WHERE NOT EXISTS (SELECT 1 FROM [{SOURCE_DATABASE}].dbo.Products AS s WHERE s.ProductID=t.ProductID AND s.Product_CategoryID={CATEGORY_ID})) AS ProductsMissingFromSource,
    (SELECT COUNT_BIG(*) FROM [{SOURCE_DATABASE}].dbo.Products AS s WHERE s.Product_CategoryID={CATEGORY_ID} AND NOT EXISTS (SELECT 1 FROM dbo.Products AS t WHERE t.ProductID=s.ProductID)) AS SourceProductsMissingFromTarget
""".strip()


class OklahomaHawaiiCatalogReplaceScopeError(ValueError):
    """The fixed catalog replacement contract no longer matches live state."""


class OklahomaHawaiiCatalogReplaceUnavailableError(RuntimeError):
    """The fixed catalog replacement provider is unavailable or uncertain."""


class OklahomaHawaiiCatalogReplaceOperation:
    """Replace one fixed empty-use target catalog from one fixed source category."""

    def __init__(
        self,
        *,
        connect: Callable[[bool], Any],
        state_dir: str | Path,
        query_timeout_seconds: int = 120,
    ) -> None:
        self._connect = connect
        self._state_dir = Path(state_dir).expanduser().resolve() / OPERATION_NAME
        self._query_timeout_seconds = max(120, min(int(query_timeout_seconds), 1_800))

    @property
    def configured(self) -> bool:
        return True

    def preview(self, *, idempotency_key: str) -> dict[str, Any]:
        clean_key = _idempotency_key(idempotency_key)
        receipt = _read_json_optional(self._receipt_path(clean_key))
        if receipt:
            with closing(self._connect(True)) as connection:
                readback = _readback(connection.cursor())
            _require_completed_readback(readback)
            return _completed_result(receipt, readback=readback, replay=True)

        with closing(self._connect(True)) as connection:
            _set_timeout(connection, self._query_timeout_seconds)
            manifest = _build_manifest(connection.cursor(), lock_tables=False)
        _validate_manifest(manifest)
        plan_hash = _sha256_json(_execution_contract(clean_key, manifest))
        preview = {
            "operation": OPERATION_NAME,
            "idempotencyKey": clean_key,
            "planHash": plan_hash,
            "fixedSource": SOURCE_USERNAME,
            "fixedSourceDatabase": SOURCE_DATABASE,
            "fixedTarget": TARGET_USERNAME,
            "fixedTargetDatabase": TARGET_DATABASE,
            "fixedCategory": CATEGORY_NAME,
            "sourceDatabaseReadOnlyByOperationPolicy": True,
            "genericDeleteExposed": False,
            "targetBackupsRequired": True,
            "transactionRequired": True,
            "manifest": manifest,
            "previewedAt": datetime.now(timezone.utc).isoformat(),
        }
        existing = _read_json_optional(self._preview_path(clean_key))
        if existing and existing.get("planHash") != plan_hash:
            raise OklahomaHawaiiCatalogReplaceScopeError(
                "live source or target state drifted from the existing fixed preview"
            )
        if not existing:
            _write_json_atomic(self._preview_path(clean_key), preview)
        return _preview_result(existing or preview, replay=bool(existing))

    def status(self, *, idempotency_key: str) -> dict[str, Any]:
        clean_key = _idempotency_key(idempotency_key)
        preview = _read_json_optional(self._preview_path(clean_key))
        receipt = _read_json_optional(self._receipt_path(clean_key))
        with closing(self._connect(True)) as connection:
            _set_timeout(connection, self._query_timeout_seconds)
            readback = _readback(connection.cursor())
        if receipt:
            _require_completed_readback(readback)
            result = _completed_result(receipt, readback=readback, replay=True)
            result.update(
                {
                    "operation": OPERATION_TOOLS[1],
                    "reconciliationStatus": "completed",
                    "safeToRetry": False,
                }
            )
            return result
        if not preview:
            return {
                "ok": True,
                "operation": OPERATION_TOOLS[1],
                "status": "not_previewed",
                "idempotencyKey": clean_key,
                "safeToRetry": False,
            }
        if _is_completed_readback(readback):
            return {
                "ok": True,
                "operation": OPERATION_TOOLS[1],
                "status": "reconciled",
                "idempotencyKey": clean_key,
                "previewHash": preview.get("planHash"),
                "reconciliationStatus": "committed_without_receipt",
                "completionVerified": True,
                "safeToRetry": False,
                "readback": readback,
            }
        try:
            with closing(self._connect(True)) as connection:
                _set_timeout(connection, self._query_timeout_seconds)
                manifest = _build_manifest(connection.cursor(), lock_tables=False)
            unchanged = manifest == preview.get("manifest")
        except Exception:
            unchanged = False
        return {
            "ok": True,
            "operation": OPERATION_TOOLS[1],
            "status": "reconciled",
            "idempotencyKey": clean_key,
            "previewHash": preview.get("planHash"),
            "reconciliationStatus": "not_committed" if unchanged else "target_changed",
            "completionVerified": False,
            "safeToRetry": bool(unchanged),
            "readback": readback,
        }

    def execute(self, *, idempotency_key: str, preview_hash: str) -> dict[str, Any]:
        clean_key = _idempotency_key(idempotency_key)
        clean_hash = _preview_hash(preview_hash)
        receipt = _read_json_optional(self._receipt_path(clean_key))
        if receipt:
            with closing(self._connect(True)) as connection:
                readback = _readback(connection.cursor())
            _require_completed_readback(readback)
            return _completed_result(receipt, readback=readback, replay=True)

        preview = _read_json_optional(self._preview_path(clean_key))
        if not preview or preview.get("planHash") != clean_hash:
            raise OklahomaHawaiiCatalogReplaceScopeError(
                "preview_hash must be the exact hash returned by the fixed preview"
            )

        committed = False
        backup_receipts: list[dict[str, Any]] = []
        mutation_counts: dict[str, int] = {}
        with closing(self._connect(False)) as connection:
            _set_timeout(connection, self._query_timeout_seconds)
            cursor = connection.cursor()
            try:
                cursor.execute("SET XACT_ABORT ON")
                cursor.execute("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
                cursor.execute("BEGIN TRANSACTION")
                _verify_database_binding(cursor)
                _acquire_lock(cursor, clean_key)
                current = _build_manifest(cursor, lock_tables=True)
                _validate_manifest(current)
                if current != preview.get("manifest"):
                    raise OklahomaHawaiiCatalogReplaceScopeError(
                        "source or target drifted from the immutable fixed preview"
                    )

                backup_receipts = _create_backups(cursor, clean_hash, current)
                mutation_counts = _replace_catalog(cursor)
                if sum(mutation_counts.values()) > MAX_CHANGED_ROWS:
                    raise OklahomaHawaiiCatalogReplaceScopeError(
                        "the fixed replacement exceeded its affected-row ceiling"
                    )
                transactional_readback = _readback(cursor)
                _require_completed_readback(transactional_readback)
                connection.commit()
                committed = True
            except Exception:
                if not committed:
                    connection.rollback()
                raise

        with closing(self._connect(True)) as connection:
            _set_timeout(connection, self._query_timeout_seconds)
            final_readback = _readback(connection.cursor())
        _require_completed_readback(final_readback)
        receipt = {
            "operation": OPERATION_NAME,
            "status": "completed",
            "idempotencyKey": clean_key,
            "planHash": clean_hash,
            "fixedSource": SOURCE_USERNAME,
            "fixedTarget": TARGET_USERNAME,
            "fixedCategory": CATEGORY_NAME,
            "sourceDatabaseReadOnlyByOperationPolicy": True,
            "genericDeleteExposed": False,
            "transactionCommitted": True,
            "backups": backup_receipts,
            "mutationCounts": mutation_counts,
            "readback": final_readback,
            "completedAt": datetime.now(timezone.utc).isoformat(),
        }
        try:
            _write_json_atomic(self._receipt_path(clean_key), receipt)
        except Exception as exc:
            raise OklahomaHawaiiCatalogReplaceUnavailableError(
                "catalog replacement committed without a durable receipt; call status and do not retry"
            ) from exc
        return _completed_result(receipt, readback=final_readback, replay=False)

    def _preview_path(self, key: str) -> Path:
        return self._state_dir / f"{hashlib.sha256(key.encode('utf-8')).hexdigest()}.preview.json"

    def _receipt_path(self, key: str) -> Path:
        return self._state_dir / f"{hashlib.sha256(key.encode('utf-8')).hexdigest()}.receipt.json"


def _build_manifest(cursor: Any, *, lock_tables: bool) -> dict[str, Any]:
    _verify_database_binding(cursor)
    source_hint = "WITH (HOLDLOCK,TABLOCK)" if lock_tables else ""
    target_hint = "WITH (UPDLOCK,HOLDLOCK,TABLOCK)" if lock_tables else ""
    dependency_hint = "WITH (HOLDLOCK,TABLOCK)" if lock_tables else ""

    source_schema = _schema_manifest(cursor, SOURCE_DATABASE)
    target_schema = _schema_manifest(cursor, TARGET_DATABASE)

    cursor.execute(SOURCE_CATEGORY_SQL.format(source_hint=source_hint))
    category_rows = [
        [_canonical_value(value) for value in row] for row in cursor.fetchall()
    ]
    cursor.execute(SOURCE_SUMMARY_SQL.format(source_hint=source_hint))
    summary = cursor.fetchone()
    cursor.execute(
        TARGET_COUNT_SQL.format(target_hint=target_hint)
    )
    target_counts_row = cursor.fetchone()
    cursor.execute(
        COLLISION_SQL.format(source_hint=source_hint, target_hint=target_hint)
    )
    collisions = int(cursor.fetchone()[0])
    cursor.execute(TRIGGER_SQL)
    triggers = [list(row) for row in cursor.fetchall()]
    cursor.execute(DEPENDENCY_COLUMN_SQL)
    dependency_columns = sorted(
        (str(row[0]).casefold(), str(row[1]).casefold(), str(row[2]).casefold())
        for row in cursor.fetchall()
    )
    cursor.execute(FOREIGN_KEY_SQL)
    foreign_keys = sorted(
        tuple(str(value).casefold() for value in row) for row in cursor.fetchall()
    )
    cursor.execute(
        EXTERNAL_DEPENDENCY_SQL.format(
            d_hint=dependency_hint,
            p_hint=dependency_hint,
        )
    )
    dependency_counts = {
        str(row[0]): int(row[1]) for row in cursor.fetchall()
    }

    source_fingerprints = {
        "products": _fingerprint(
            cursor,
            SOURCE_DATABASE,
            "Products",
            PRODUCT_COLUMNS,
            "ProductID",
            where=f"Product_CategoryID={CATEGORY_ID}",
            lock_hint=source_hint,
        ),
        "categories": _fingerprint(
            cursor,
            SOURCE_DATABASE,
            "Products_Categories",
            CATEGORY_COLUMNS,
            "Products_CategoryID",
            where=f"Products_CategoryID={CATEGORY_ID} AND UPPER(LTRIM(RTRIM(Products_CategoryName)))='{CATEGORY_NAME}'",
            lock_hint=source_hint,
        ),
        "wholesalers": _fingerprint_required_wholesalers(cursor, source_hint),
    }
    target_fingerprints = {
        "products": _fingerprint(
            cursor,
            TARGET_DATABASE,
            "Products",
            PRODUCT_COLUMNS,
            "ProductID",
            lock_hint=target_hint,
        ),
        "categories": _fingerprint(
            cursor,
            TARGET_DATABASE,
            "Products_Categories",
            CATEGORY_COLUMNS,
            "Products_CategoryID",
            lock_hint=target_hint,
        ),
        "wholesalers": _fingerprint(
            cursor,
            TARGET_DATABASE,
            "Products_Wholesalers",
            WHOLESALER_COLUMNS,
            "WholesalerID",
            lock_hint=target_hint,
        ),
    }

    return {
        "source": {
            "database": SOURCE_DATABASE,
            "categoryRows": category_rows,
            "counts": {
                "products": int(summary[0]),
                "categories": len(category_rows),
                "wholesalers": int(summary[1]),
            },
            "missingWholesalerReferences": int(summary[2] or 0),
            "productFamilyReferences": int(summary[3] or 0),
            "createdByReferences": int(summary[4] or 0),
            "minProductId": int(summary[5]),
            "maxProductId": int(summary[6]),
            "schema": source_schema,
            "fingerprints": source_fingerprints,
        },
        "target": {
            "database": TARGET_DATABASE,
            "counts": {
                "products": int(target_counts_row[0]),
                "categories": int(target_counts_row[1]),
                "wholesalers": int(target_counts_row[2]),
            },
            "productIdCollisions": collisions,
            "schema": target_schema,
            "fingerprints": target_fingerprints,
            "dependencyColumns": [list(row) for row in dependency_columns],
            "foreignKeys": [list(row) for row in foreign_keys],
            "externalDependencyCounts": dependency_counts,
            "triggers": triggers,
        },
    }


def _validate_manifest(manifest: dict[str, Any]) -> None:
    source = manifest.get("source") or {}
    target = manifest.get("target") or {}
    if source.get("database") != SOURCE_DATABASE or target.get("database") != TARGET_DATABASE:
        raise OklahomaHawaiiCatalogReplaceScopeError("fixed database binding failed")
    if source.get("counts") != EXPECTED_SOURCE_COUNTS:
        raise OklahomaHawaiiCatalogReplaceScopeError(
            "source HAWAII counts drifted from the verified preview"
        )
    category_rows = source.get("categoryRows") or []
    if len(category_rows) != 1 or int(category_rows[0][0]) != CATEGORY_ID:
        raise OklahomaHawaiiCatalogReplaceScopeError(
            "the fixed source HAWAII category is missing or ambiguous"
        )
    if str(category_rows[0][1]).strip().upper() != CATEGORY_NAME:
        raise OklahomaHawaiiCatalogReplaceScopeError("the fixed source category name drifted")
    for key in (
        "missingWholesalerReferences",
        "productFamilyReferences",
        "createdByReferences",
    ):
        if int(source.get(key) or 0) != 0:
            raise OklahomaHawaiiCatalogReplaceScopeError(
                f"source HAWAII products contain unsupported {key}"
            )
    if target.get("counts") != EXPECTED_TARGET_COUNTS:
        raise OklahomaHawaiiCatalogReplaceScopeError(
            "target catalog counts drifted from the verified preview"
        )
    if int(target.get("productIdCollisions") or 0) != EXPECTED_PRODUCT_ID_COLLISIONS:
        raise OklahomaHawaiiCatalogReplaceScopeError(
            "source product IDs now collide with the fixed target"
        )
    if target.get("triggers"):
        raise OklahomaHawaiiCatalogReplaceScopeError(
            "a changed target table has an enabled or disabled trigger"
        )
    dependency_columns = frozenset(tuple(row) for row in target.get("dependencyColumns") or [])
    if dependency_columns != EXPECTED_DEPENDENCY_COLUMNS:
        raise OklahomaHawaiiCatalogReplaceScopeError(
            "unexpected product, category, or wholesaler dependency metadata was found"
        )
    foreign_keys = frozenset(tuple(row) for row in target.get("foreignKeys") or [])
    if foreign_keys != EXPECTED_FOREIGN_KEYS:
        raise OklahomaHawaiiCatalogReplaceScopeError(
            "target foreign-key dependencies drifted from the reviewed contract"
        )
    nonzero = {
        name: int(value)
        for name, value in (target.get("externalDependencyCounts") or {}).items()
        if int(value) != 0
    }
    if nonzero:
        raise OklahomaHawaiiCatalogReplaceScopeError(
            "target external product/category dependencies are no longer empty"
        )
    expected_schema = {
        "Products": list(PRODUCT_COLUMNS),
        "Products_Categories": list(CATEGORY_COLUMNS),
        "Products_Wholesalers": list(WHOLESALER_COLUMNS),
    }
    if source.get("schema") != expected_schema or target.get("schema") != expected_schema:
        raise OklahomaHawaiiCatalogReplaceScopeError(
            "source or target catalog schema drifted from the reviewed contract"
        )


def _schema_manifest(cursor: Any, database: str) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for _qualified, table, columns, _key in CHANGED_TABLES:
        cursor.execute(
            f"""
SELECT c.name
FROM [{database}].sys.tables AS t
JOIN [{database}].sys.schemas AS s ON s.schema_id=t.schema_id
JOIN [{database}].sys.columns AS c ON c.object_id=t.object_id
WHERE s.name='dbo' AND t.name=?
ORDER BY c.column_id
""".strip(),
            [table],
        )
        result[table] = [str(row[0]) for row in cursor.fetchall()]
        if result[table] != list(columns):
            raise OklahomaHawaiiCatalogReplaceScopeError(
                f"catalog schema mismatch on {database}.dbo.{table}"
            )
    return result


def _fingerprint(
    cursor: Any,
    database: str,
    table: str,
    columns: tuple[str, ...],
    key_column: str,
    *,
    where: str = "",
    lock_hint: str = "",
) -> str:
    values = []
    for column in columns:
        quoted = f"r.[{column}]"
        if column in {"ProductPhoto", "Products_CategoryPhoto"}:
            values.append(
                "COALESCE(CONVERT(varchar(64),HASHBYTES('SHA2_256',CONVERT(varbinary(max),"
                + quoted
                + ")),2),'<NULL>')"
            )
        else:
            values.append(
                f"COALESCE(CONVERT(nvarchar(max),{quoted},126),N'<NULL>')"
            )
    where_sql = f"WHERE {where}" if where else ""
    cursor.execute(
        f"""
SELECT CONVERT(varchar(64),HASHBYTES('SHA2_256',COALESCE((
    SELECT CONVERT(varchar(64),fingerprints.RowHash,2) AS [text()]
    FROM (
        SELECT r.[{key_column}] AS RowKey,
               HASHBYTES('SHA2_256',CONCAT_WS(N'|',{','.join(values)})) AS RowHash
        FROM [{database}].dbo.[{table}] AS r {lock_hint}
        {where_sql}
    ) AS fingerprints
    ORDER BY fingerprints.RowKey
    FOR XML PATH(''),TYPE
).value('.','varchar(max)'),'EMPTY')),2)
""".strip()
    )
    row = cursor.fetchone()
    value = str(row[0] or "").lower()
    if not HASH.fullmatch(value):
        raise OklahomaHawaiiCatalogReplaceScopeError("catalog fingerprint could not be computed")
    return value


def _fingerprint_required_wholesalers(cursor: Any, source_hint: str) -> str:
    values = ",".join(
        f"COALESCE(CONVERT(nvarchar(max),w.[{column}],126),N'<NULL>')"
        for column in WHOLESALER_COLUMNS
    )
    cursor.execute(
        f"""
SELECT CONVERT(varchar(64),HASHBYTES('SHA2_256',COALESCE((
    SELECT CONVERT(varchar(64),fingerprints.RowHash,2) AS [text()]
    FROM (
        SELECT w.WholesalerID AS RowKey,
               HASHBYTES('SHA2_256',CONCAT_WS(N'|',{values})) AS RowHash
        FROM [{SOURCE_DATABASE}].dbo.Products_Wholesalers AS w {source_hint}
        WHERE EXISTS (
            SELECT 1 FROM [{SOURCE_DATABASE}].dbo.Products AS p {source_hint}
            WHERE p.Product_CategoryID={CATEGORY_ID} AND p.WholesalerID=w.WholesalerID
        )
    ) AS fingerprints
    ORDER BY fingerprints.RowKey
    FOR XML PATH(''),TYPE
).value('.','varchar(max)'),'EMPTY')),2)
""".strip()
    )
    value = str(cursor.fetchone()[0] or "").lower()
    if not HASH.fullmatch(value):
        raise OklahomaHawaiiCatalogReplaceScopeError("wholesaler fingerprint could not be computed")
    return value


def _create_backups(
    cursor: Any,
    preview_hash: str,
    manifest: dict[str, Any],
) -> list[dict[str, Any]]:
    counts = manifest["target"]["counts"]
    receipts: list[dict[str, Any]] = []
    count_keys = {
        "Products": "products",
        "Products_Categories": "categories",
        "Products_Wholesalers": "wholesalers",
    }
    for qualified, table, _columns, _key in CHANGED_TABLES:
        backup_table = f"__codex_bak_{table}_{preview_hash[:12]}"
        full_backup = f"dbo.{backup_table}"
        cursor.execute("SELECT OBJECT_ID(?, 'U')", [full_backup])
        if int(cursor.fetchone()[0] or 0) != 0:
            raise OklahomaHawaiiCatalogReplaceScopeError(
                "an immutable backup name already exists without a completion receipt"
            )
        cursor.execute(f"SELECT * INTO dbo.[{backup_table}] FROM {qualified}")
        cursor.execute(f"SELECT COUNT_BIG(*) FROM dbo.[{backup_table}]")
        actual = int(cursor.fetchone()[0])
        expected = int(counts[count_keys[table]])
        if actual != expected:
            raise OklahomaHawaiiCatalogReplaceScopeError(
                f"full backup verification failed for {qualified}"
            )
        receipts.append(
            {"sourceTable": qualified, "backupTable": full_backup, "rowCount": actual}
        )
    return receipts


def _replace_catalog(cursor: Any) -> dict[str, int]:
    counts: dict[str, int] = {}
    for key, sql, expected in (
        ("deletedProducts", "DELETE FROM dbo.Products", EXPECTED_TARGET_COUNTS["products"]),
        (
            "deletedCategories",
            "DELETE FROM dbo.Products_Categories",
            EXPECTED_TARGET_COUNTS["categories"],
        ),
        (
            "deletedWholesalers",
            "DELETE FROM dbo.Products_Wholesalers",
            EXPECTED_TARGET_COUNTS["wholesalers"],
        ),
    ):
        cursor.execute(sql)
        affected = int(cursor.rowcount)
        if affected != expected:
            raise OklahomaHawaiiCatalogReplaceScopeError(
                f"fixed delete count drifted for {key}"
            )
        counts[key] = affected

    category_columns = _quoted_columns(CATEGORY_COLUMNS)
    cursor.execute("SET IDENTITY_INSERT dbo.Products_Categories ON")
    try:
        cursor.execute(
            f"""
INSERT INTO dbo.Products_Categories ({category_columns})
SELECT {category_columns}
FROM [{SOURCE_DATABASE}].dbo.Products_Categories
WHERE Products_CategoryID={CATEGORY_ID}
  AND UPPER(LTRIM(RTRIM(Products_CategoryName)))='{CATEGORY_NAME}'
""".strip()
        )
        counts["insertedCategories"] = int(cursor.rowcount)
    finally:
        cursor.execute("SET IDENTITY_INSERT dbo.Products_Categories OFF")
    if counts["insertedCategories"] != EXPECTED_SOURCE_COUNTS["categories"]:
        raise OklahomaHawaiiCatalogReplaceScopeError("fixed category insert count drifted")

    wholesaler_columns = _quoted_columns(WHOLESALER_COLUMNS)
    cursor.execute("SET IDENTITY_INSERT dbo.Products_Wholesalers ON")
    try:
        cursor.execute(
            f"""
INSERT INTO dbo.Products_Wholesalers ({wholesaler_columns})
SELECT {','.join('w.[' + column + ']' for column in WHOLESALER_COLUMNS)}
FROM [{SOURCE_DATABASE}].dbo.Products_Wholesalers AS w
WHERE EXISTS (
    SELECT 1 FROM [{SOURCE_DATABASE}].dbo.Products AS p
    WHERE p.Product_CategoryID={CATEGORY_ID} AND p.WholesalerID=w.WholesalerID
)
""".strip()
        )
        counts["insertedWholesalers"] = int(cursor.rowcount)
    finally:
        cursor.execute("SET IDENTITY_INSERT dbo.Products_Wholesalers OFF")
    if counts["insertedWholesalers"] != EXPECTED_SOURCE_COUNTS["wholesalers"]:
        raise OklahomaHawaiiCatalogReplaceScopeError("fixed wholesaler insert count drifted")

    product_columns = _quoted_columns(PRODUCT_COLUMNS)
    cursor.execute("SET IDENTITY_INSERT dbo.Products ON")
    try:
        cursor.execute(
            f"""
INSERT INTO dbo.Products ({product_columns})
SELECT {product_columns}
FROM [{SOURCE_DATABASE}].dbo.Products
WHERE Product_CategoryID={CATEGORY_ID}
""".strip()
        )
        counts["insertedProducts"] = int(cursor.rowcount)
    finally:
        cursor.execute("SET IDENTITY_INSERT dbo.Products OFF")
    if counts["insertedProducts"] != EXPECTED_SOURCE_COUNTS["products"]:
        raise OklahomaHawaiiCatalogReplaceScopeError("fixed product insert count drifted")
    return counts


def _readback(cursor: Any) -> dict[str, int]:
    _verify_database_binding(cursor)
    cursor.execute(READBACK_SQL)
    row = cursor.fetchone()
    keys = (
        "products",
        "categories",
        "wholesalers",
        "nonHawaiiProducts",
        "nonHawaiiCategories",
        "orphanCategoryReferences",
        "orphanWholesalerReferences",
        "productFamilyReferences",
        "createdByReferences",
        "productsMissingFromSource",
        "sourceProductsMissingFromTarget",
    )
    return {key: int(row[index]) for index, key in enumerate(keys)}


def _is_completed_readback(readback: dict[str, int]) -> bool:
    return readback == {
        "products": 26,
        "categories": 1,
        "wholesalers": 0,
        "nonHawaiiProducts": 0,
        "nonHawaiiCategories": 0,
        "orphanCategoryReferences": 0,
        "orphanWholesalerReferences": 0,
        "productFamilyReferences": 0,
        "createdByReferences": 0,
        "productsMissingFromSource": 0,
        "sourceProductsMissingFromTarget": 0,
    }


def _require_completed_readback(readback: dict[str, int]) -> None:
    if not _is_completed_readback(readback):
        raise OklahomaHawaiiCatalogReplaceUnavailableError(
            "authoritative catalog replacement readback did not match the fixed result"
        )


def _verify_database_binding(cursor: Any) -> None:
    cursor.execute("SELECT DB_NAME()")
    if str(cursor.fetchone()[0] or "").casefold() != TARGET_DATABASE.casefold():
        raise OklahomaHawaiiCatalogReplaceScopeError(
            "the fixed catalog replacement is not bound to POS_oklahoma"
        )


def _acquire_lock(cursor: Any, idempotency_key: str) -> None:
    cursor.execute(
        """
DECLARE @result int;
EXEC @result = sys.sp_getapplock
    @Resource=?, @LockMode='Exclusive', @LockOwner='Transaction', @LockTimeout=30000;
SELECT @result;
""".strip(),
        [f"AgentChat:{OPERATION_NAME}:{idempotency_key}"],
    )
    if int(cursor.fetchone()[0]) < 0:
        raise OklahomaHawaiiCatalogReplaceUnavailableError(
            "the fixed catalog replacement could not acquire its transaction lock"
        )


def _execution_contract(key: str, manifest: dict[str, Any]) -> dict[str, Any]:
    return {
        "operation": OPERATION_NAME,
        "fixedSource": SOURCE_USERNAME,
        "fixedTarget": TARGET_USERNAME,
        "fixedCategory": CATEGORY_NAME,
        "idempotencyKey": key,
        "manifest": manifest,
    }


def _preview_result(preview: dict[str, Any], *, replay: bool) -> dict[str, Any]:
    manifest = preview["manifest"]
    return {
        "ok": True,
        "operation": OPERATION_TOOLS[0],
        "status": "preview",
        "idempotentReplay": replay,
        "idempotencyKey": preview["idempotencyKey"],
        "previewHash": preview["planHash"],
        "fixedSource": SOURCE_USERNAME,
        "fixedTarget": TARGET_USERNAME,
        "fixedCategory": CATEGORY_NAME,
        "sourceDatabaseReadOnlyByOperationPolicy": True,
        "genericDeleteExposed": False,
        "transactionRequired": True,
        "targetBackupsRequired": True,
        "beforeCounts": manifest["target"]["counts"],
        "afterCounts": EXPECTED_SOURCE_COUNTS,
        "externalDependencyCounts": manifest["target"]["externalDependencyCounts"],
        "productIdCollisions": manifest["target"]["productIdCollisions"],
    }


def _completed_result(
    receipt: dict[str, Any],
    *,
    readback: dict[str, int],
    replay: bool,
) -> dict[str, Any]:
    return {
        "ok": True,
        "operation": OPERATION_TOOLS[2],
        "status": "completed",
        "idempotentReplay": replay,
        "idempotencyKey": receipt["idempotencyKey"],
        "previewHash": receipt["planHash"],
        "fixedSource": SOURCE_USERNAME,
        "fixedTarget": TARGET_USERNAME,
        "fixedCategory": CATEGORY_NAME,
        "sourceDatabaseReadOnlyByOperationPolicy": True,
        "genericDeleteExposed": False,
        "transactionCommitted": bool(receipt.get("transactionCommitted")),
        "backups": receipt.get("backups") or [],
        "mutationCounts": receipt.get("mutationCounts") or {},
        "postCommitReadbackVerified": True,
        "readback": readback,
    }


def _idempotency_key(value: str) -> str:
    clean = str(value or "").strip()
    if clean != REQUIRED_IDEMPOTENCY_KEY:
        raise OklahomaHawaiiCatalogReplaceScopeError(
            "this fixed operation requires its exact reviewed idempotency key"
        )
    return clean


def _preview_hash(value: str) -> str:
    clean = str(value or "").strip().lower()
    if not HASH.fullmatch(clean):
        raise OklahomaHawaiiCatalogReplaceScopeError("preview_hash is invalid")
    return clean


def _quoted_columns(columns: tuple[str, ...]) -> str:
    return ",".join(f"[{column}]" for column in columns)


def _canonical_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (datetime,)):
        return value.isoformat()
    return str(value)


def _sha256_json(value: Any) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _read_json_optional(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    if not isinstance(value, dict):
        raise OklahomaHawaiiCatalogReplaceUnavailableError(
            "the fixed operation state file is invalid"
        )
    return value


def _write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True),
        encoding="utf-8",
    )
    temporary.replace(path)


def _set_timeout(connection: Any, seconds: int) -> None:
    if hasattr(connection, "timeout"):
        connection.timeout = seconds
