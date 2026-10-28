from __future__ import annotations

from copy import deepcopy

from scoped_operations_mcp.nova_sql_instyle_demo_rebuild import (
    ColumnSpec,
    DatabaseSnapshot,
    TableSpec,
)
from scoped_operations_mcp.nova_sql_instyle_demo_sync import (
    INVOICE_PRODUCT_INVOICE_REPAIRS,
    OPERATION_NAME,
    SOURCE_B_USERNAME,
    InstyleDemoSyncOperation,
    _apply_fixed_source_repairs,
    _checkpoint_values,
    _cursor_columns,
    _execution_contract,
    _product_key,
    _preview_result,
    _read_product_index_rows,
    _write_json_atomic,
    _without_excluded_tables,
    execution_failure_result,
)


def _column(
    name: str,
    *,
    identity: bool = False,
    primary_key_ordinal: int = 0,
) -> ColumnSpec:
    return ColumnSpec(
        name=name,
        ordinal=1,
        type_name="int",
        nullable=False,
        identity=identity,
        computed=False,
        generated=False,
        has_default=False,
        primary_key_ordinal=primary_key_ordinal,
    )


def test_cursor_uses_declared_primary_key_then_identity_fallback() -> None:
    primary = TableSpec(
        schema="dbo",
        name="Invoices",
        columns=(_column("InvoiceID", primary_key_ordinal=1),),
        foreign_keys=(),
    )
    identity = TableSpec(
        schema="dbo",
        name="Invoice_Employees",
        columns=(_column("Invoice_Employees_ID", identity=True),),
        foreign_keys=(),
    )

    assert [column.name for column in _cursor_columns(primary)] == ["InvoiceID"]
    assert [column.name for column in _cursor_columns(identity)] == [
        "Invoice_Employees_ID"
    ]


def test_product_key_uses_the_fixed_four_normalized_nova_fields() -> None:
    assert _product_key(
        {
            "ProductName": "  Rose ",
            "BarcodeNumber": " abc ",
            "BarcodeNumber2": None,
            "SKU": " sku-1 ",
        }
    ) == ("rose", "abc", "", "sku-1")


def test_product_index_scan_does_not_materialize_large_product_columns() -> None:
    class FakeCursor:
        def __init__(self) -> None:
            self.sql = ""

        def execute(self, sql):
            self.sql = sql
            return self

        def fetchall(self):
            return [(7, "Rose", "A", "B", "S")]

    spec = TableSpec(
        schema="dbo",
        name="Products",
        columns=(
            _column("ProductID", primary_key_ordinal=1),
            _column("ProductName"),
            _column("BarcodeNumber"),
            _column("BarcodeNumber2"),
            _column("SKU"),
            _column("ProductImage"),
        ),
        foreign_keys=(),
    )
    cursor = FakeCursor()

    rows = _read_product_index_rows(cursor, spec)

    assert rows == [
        {
            "ProductID": 7,
            "ProductName": "Rose",
            "BarcodeNumber": "A",
            "BarcodeNumber2": "B",
            "SKU": "S",
        }
    ]
    assert "[ProductImage]" not in cursor.sql


def test_fixed_invoice_product_repairs_change_only_the_copied_source_row() -> None:
    source_row = {
        "Invoice_Products_ID": 158439,
        "InvoiceID": None,
        "ProductID": 25,
    }

    _apply_fixed_source_repairs(
        SOURCE_B_USERNAME,
        "Invoice_Products",
        source_row,
    )

    assert source_row["InvoiceID"] == INVOICE_PRODUCT_INVOICE_REPAIRS[158439]


def test_core_schema_excludes_cold_history_but_keeps_nova_business_tables() -> None:
    products = TableSpec(
        schema="dbo",
        name="Products",
        columns=(_column("ProductID", primary_key_ordinal=1),),
        foreign_keys=(),
    )
    history = TableSpec(
        schema="dbo",
        name="InventoryHistoryItem",
        columns=(_column("InventoryHistoryItemID", primary_key_ordinal=1),),
        foreign_keys=(),
    )
    snapshot = DatabaseSnapshot(
        company_username="DEMO_NOVA_CAFE",
        database_name="POS_DEMO_NOVA_CAFE",
        captured_at="2026-07-28T00:00:00+00:00",
        schema_hash="before",
        snapshot_hash="",
        tables={products.key: products, history.key: history},
        table_hashes={},
        row_counts={},
    )

    core = _without_excluded_tables(snapshot)

    assert list(core.tables) == ["dbo.Products"]
    assert core.schema_hash != "before"


def test_preview_names_only_the_fixed_sync_and_preserved_history_contract() -> None:
    result = _preview_result(
        {
            "operation": OPERATION_NAME,
            "idempotencyKey": "ticket-347073-demo-sync",
            "planHash": "a" * 64,
            "copyMode": "checkpointed_incremental_core",
            "inventoryHistoryItemAction": "preserve_existing_target_rows",
            "target": {
                "productRows": 18_283,
                "invoiceProductRows": 173_453,
                "inventoryHistoryItemRows": 30_083_607,
                "productOrphanRows": 531_695,
                "checkpointRows": 129,
            },
        },
        replay=False,
    )

    assert result["operation"] == "nova_sql_instyle_demo_sync_preview"
    assert result["fixedTarget"] == "DEMO_NOVA_CAFE"
    assert result["sourceDatabasesReadOnly"] is True
    assert result["targetBackupRequired"] is False
    assert result["inventoryHistoryItemAction"] == "preserve_existing_target_rows"
    assert "sql" not in result


def test_checkpoint_values_retain_integer_cursor_contract() -> None:
    assert _checkpoint_values([15, "A"]) == [
        {"type": "int", "value": 15},
        {"type": "string", "value": "A"},
    ]


def test_execution_contract_allows_source_rows_but_not_schema_or_target_drift() -> None:
    manifest = {
        "operation": OPERATION_NAME,
        "sources": [
            {
                "companyUsername": "LE_BOUTIQUE_INSTYLE",
                "databaseName": "POS_LE_BOUTIQUE_INSTYLE",
                "schemaHash": "a" * 64,
                "tables": [
                    {
                        "table": "dbo.Products",
                        "rowCount": 10,
                        "lastKey": [10],
                    }
                ],
            }
        ],
        "target": {"productRows": 18_283, "checkpointHash": "b" * 64},
    }
    source_rows_advanced = deepcopy(manifest)
    source_rows_advanced["sources"][0]["tables"][0]["rowCount"] = 11
    source_rows_advanced["sources"][0]["tables"][0]["lastKey"] = [11]
    source_schema_changed = deepcopy(manifest)
    source_schema_changed["sources"][0]["schemaHash"] = "c" * 64
    target_changed = deepcopy(manifest)
    target_changed["target"]["productRows"] = 18_284

    assert _execution_contract(source_rows_advanced) == _execution_contract(
        manifest
    )
    assert _execution_contract(source_schema_changed) != _execution_contract(
        manifest
    )
    assert _execution_contract(target_changed) != _execution_contract(manifest)


def test_status_proves_an_uncertain_execute_did_not_commit(
    tmp_path,
    monkeypatch,
) -> None:
    class FakeConnection:
        def close(self) -> None:
            return None

    operation = InstyleDemoSyncOperation(
        connect=lambda _company, _read_only: FakeConnection(),
        state_dir=tmp_path,
    )
    key = "ticket-347073-status-test"
    target = {
        "companyUsername": "DEMO_NOVA_CAFE",
        "databaseName": "POS_DEMO_NOVA_CAFE",
        "productRows": 18_283,
        "invoiceProductRows": 173_453,
        "inventoryHistoryItemRows": 30_083_607,
        "checkpointHash": "c" * 64,
        "checkpointRows": 129,
        "productOrphanRows": 531_695,
    }
    sources = [{"databaseName": "POS_LE_BOUTIQUE_INSTYLE"}]
    preview = {
        "operation": OPERATION_NAME,
        "idempotencyKey": key,
        "planHash": "a" * 64,
        "sources": sources,
        "target": target,
    }
    _write_json_atomic(operation._preview_path(key), preview)
    monkeypatch.setattr(
        operation,
        "_build_manifest",
        lambda *_args: {
            "sources": sources,
            "target": target,
        },
    )

    result = operation.status(idempotency_key=key)

    assert result["reconciliationStatus"] == "not_committed"
    assert result["completionReceiptPresent"] is False
    assert result["sourcesUnchanged"] is True
    assert result["targetBaselineUnchanged"] is True
    assert result["safeToRetry"] is True


def test_execute_failure_has_nonblank_bounded_diagnostic_and_status_next_step() -> None:
    result = execution_failure_result(
        idempotency_key="ticket-347073-status-test",
        preview_hash="a" * 64,
        error=MemoryError(),
    )

    assert result["ok"] is False
    assert result["errorType"] == "MemoryError"
    assert result["error"] == "MemoryError()"
    assert result["safeToRetry"] is False
    assert "nova_sql_instyle_demo_sync_status" in result["nextStep"]
