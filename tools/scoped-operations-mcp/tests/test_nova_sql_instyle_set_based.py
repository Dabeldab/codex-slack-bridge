from __future__ import annotations

# AgentChat/coding_agent 2026-08-05T10:32:03Z

import hashlib
import json
import re
from pathlib import Path

from scoped_operations_mcp.instyle_demo_merge_sql_v2 import (
    INSTYLE_DEMO_MERGE_SQL_V2,
)
from scoped_operations_mcp.nova_sql_instyle_set_based import (
    APPROVED_PARTIAL_PLACEHOLDER_INVOICE_LINES,
    APPROVED_PARTIAL_PLACEHOLDER_PRODUCTS,
    APPROVED_PARTIAL_PREVIEW_HASH,
    APPROVED_PARTIAL_TARGET_STATE,
    EXPECTED_PLACEHOLDER_INVOICE_LINES,
    EXPECTED_PLACEHOLDER_PRODUCTS,
    EXPECTED_QUARANTINED_INVOICE_PRODUCT_ROWS,
    OPERATION_NAME,
    SOURCE_A_DATABASE,
    SOURCE_B_DATABASE,
    SQL_RESOURCE,
    TARGET_DATABASE,
    SetBasedInstyleDemoSyncOperation,
    _is_approved_partial_target_recovery,
    _optional_product_map_rows,
    _preview_result,
    _schema_hash,
    _validate_approved_source_scope,
)


ROOT = Path(__file__).resolve().parents[3]


def _sql() -> str:
    return INSTYLE_DEMO_MERGE_SQL_V2


def test_set_based_operation_packages_one_fixed_sql_resource(tmp_path: Path) -> None:
    operation = SetBasedInstyleDemoSyncOperation(
        connect=lambda _read_only: None,
        state_dir=tmp_path,
    )

    assert operation.configured is True
    assert OPERATION_NAME == "instyle_demo_set_based_sql_v1"
    assert SOURCE_A_DATABASE in _sql()
    assert SOURCE_B_DATABASE in _sql()
    assert TARGET_DATABASE in _sql()
    assert INSTYLE_DEMO_MERGE_SQL_V2.strip()

    pyproject = (
        ROOT / "tools" / "scoped-operations-mcp" / "pyproject.toml"
    ).read_text(encoding="utf-8")
    assert 'scoped_operations_mcp = ["sql/*.sql"]' in pyproject


def test_sql_is_database_side_and_copies_cold_history() -> None:
    sql = _sql()

    assert "INSERT ... SELECT" in sql
    assert "InventoryHistoryItem" in sql
    assert "copy and remapping on SQL Server" in sql
    assert "fetchmany" not in sql
    assert "executemany" not in sql
    assert "@SourceA sysname=N'POS_LE_BOUTIQUE_INSTYLE'" in sql
    assert "@SourceB sysname=N'POS_Instyle_Fragrance'" in sql
    assert "@Target sysname=N'POS_DEMO_NOVA_CAFE'" in sql
    assert "BEGIN TRANSACTION" in sql
    assert "COMMIT TRANSACTION" in sql
    assert "IF @@TRANCOUNT>0 ROLLBACK TRANSACTION" in sql


def test_sql_supports_the_live_compatibility_level_100() -> None:
    sql = _sql()

    assert "STRING_AGG" not in sql
    assert "WITHIN GROUP" not in sql
    assert "FOR XML PATH" in sql


def test_generated_product_mappings_use_the_declared_execution_parameter() -> None:
    sql = _sql()

    assert sql.count("pm.SourceTag=@SourceTag") == 2
    assert "pm.SourceTag=@Tag" not in sql
    assert sql.count("N'@SourceTag char(1),@RowsOut bigint OUTPUT'") == 2


def test_existing_orphan_repair_uses_one_indexable_product_map_key() -> None:
    sql = _sql()
    repair = sql.split("DECLARE RepairCursor", 1)[1].split(
        "CLOSE RepairCursor", 1
    )[0]

    assert "m.SourceTag=CASE" in repair
    assert "m.SourceProductID=CONVERT(int,CASE" in repair
    assert "OR (m.SourceTag" not in repair
    assert "LEFT JOIN #ProductMap m" in repair
    assert "-2000000000" in repair


def test_live_scope_is_invoice_qualified_and_quarantines_blank_links() -> None:
    sql = _sql()

    assert EXPECTED_PLACEHOLDER_PRODUCTS == 107
    assert EXPECTED_PLACEHOLDER_INVOICE_LINES == 142
    assert EXPECTED_QUARANTINED_INVOICE_PRODUCT_ROWS == 11
    assert "@QualifiedPlaceholderProducts<>107" in sql
    assert "@QualifiedPlaceholderInvoiceLines<>142" in sql
    assert "@QuarantinedInvoiceProductRows<>11" in sql
    assert "JOIN '+QUOTENAME(@SourceDB)+N'.dbo.Invoices i" in sql
    assert "ip.InvoiceID IS NULL OR i.InvoiceID IS NULL" in sql
    assert "SET @SourceScopePredicate=N's.InvoiceID IS NOT NULL AND EXISTS(" in sql
    assert "UPDATE dbo.Invoice_Products" not in sql


def test_approved_source_scope_validator_requires_exact_live_counts() -> None:
    scope = {
        "qualifiedPlaceholderProducts": 107,
        "qualifiedInvoiceLines": 142,
        "quarantinedInvoiceProductRows": 11,
    }

    _validate_approved_source_scope(scope)

    for key in scope:
        changed = dict(scope)
        changed[key] += 1
        try:
            _validate_approved_source_scope(changed)
        except Exception as error:
            assert "fixed source" in str(error)
        else:
            raise AssertionError(f"{key} drift was not rejected")


def test_partial_recovery_accepts_only_the_reviewed_incomplete_demo_state() -> None:
    idempotency_key = "rory-recover-copy-jobs-347551-347626-347072-347073-v1"
    scope = {
        "qualifiedPlaceholderProducts": 107,
        "qualifiedInvoiceLines": 142,
        "quarantinedInvoiceProductRows": 11,
    }
    existing = {
        "operation": OPERATION_NAME,
        "idempotencyKey": idempotency_key,
        "planHash": APPROVED_PARTIAL_PREVIEW_HASH,
        "fixedSources": ["LE_BOUTIQUE_INSTYLE", "Instyle_Fragrance"],
        "fixedTarget": "DEMO_NOVA_CAFE",
        "approvedSourceScope": scope,
    }
    baseline = {
        "targetState": {
            **APPROVED_PARTIAL_TARGET_STATE,
            "inventoryHistoryItemRows": 39_233_593,
        },
        "approvedSourceScope": scope,
    }
    readback = {
        "productMapPresent": True,
        "completionVerified": False,
        "inventoryHistoryCoverageCurrent": True,
        "duplicateNonblankProductKeys": 0,
        "invoiceProductsWithBlankInvoiceId": 0,
        "placeholderRequiredFieldGaps": 0,
        "productOrphanRows": 41_802_886,
        "qualifiedPlaceholderProducts": APPROVED_PARTIAL_PLACEHOLDER_PRODUCTS,
        "qualifiedPlaceholderInvoiceLines": (
            APPROVED_PARTIAL_PLACEHOLDER_INVOICE_LINES
        ),
        "quarantinedInvoiceProductRows": 11,
    }

    assert _is_approved_partial_target_recovery(
        existing=existing,
        idempotency_key=idempotency_key,
        baseline=baseline,
        readback=readback,
    )

    for section, key in (
        (baseline["targetState"], "productMapRows"),
        (readback, "qualifiedPlaceholderProducts"),
        (readback, "productOrphanRows"),
    ):
        original = section[key]
        section[key] = 0
        assert not _is_approved_partial_target_recovery(
            existing=existing,
            idempotency_key=idempotency_key,
            baseline=baseline,
            readback=readback,
        )
        section[key] = original


def test_completion_aggregates_do_not_emit_null_elimination_warning() -> None:
    sql = _sql()

    assert "COUNT(DISTINCT CASE WHEN RowsInserted>0" not in sql
    assert "SELECT @ChangedTables=COUNT(DISTINCT TableName)" in sql
    assert "WHERE RowsInserted>0;" in sql


def test_live_keyless_tables_use_their_verified_nova_row_ids() -> None:
    sql = _sql()

    for table, column in (
        ("Change_Log", "Change_LogID"),
        ("Employees_CheckInOut", "Employees_CheckInOutID"),
        ("Invoice_Employees", "Invoice_Employees_ID"),
        ("Invoice_Payments", "Invoice_Payments_ID"),
        ("Refunds_Payments", "Id"),
        ("Refunds_Products", "Id"),
    ):
        assert f"@CopyTable='{table}'" in sql
        assert f"INSERT #KeyPlan VALUES(1,'{column}')" in sql
    assert "A configured source row key contains null." in sql
    assert "A configured source row key is not unique." in sql
    assert "HAVING COUNT_BIG(*)>1" in sql
    assert ";THROW 53128" not in sql
    assert ";THROW 53129" not in sql


def test_duplicate_alert_assignments_preserve_source_multiplicity() -> None:
    sql = _sql()

    alerts_override = sql.split(
        "@CopyTable='Alerts_History_Employees'", 1
    )[1].split("@CopyTable='Employees_Regions'", 1)[0]
    assert "SET @AllowDuplicateKey=1" in alerts_override
    assert "WITH SourceRanked AS" in sql
    assert "WITH SourceRanked AS" not in alerts_override
    assert "ROW_NUMBER() OVER(" in sql
    assert "PARTITION BY '+@MultiplicityColumns" in sql
    assert "@KeyColumns+N',[WasSentTo]'" in sql
    assert "t.[WasSentTo]=s.[WasSentTo]" in sql
    assert "t.[WasSentTo] IS NULL AND s.[WasSentTo] IS NULL" in sql
    assert "__codex_occurrence_ordinal" in sql
    assert "t.__codex_occurrence_ordinal=s.__codex_occurrence_ordinal" in sql
    assert "IF @AllowDuplicateKey=0" in sql
    assert "WHERE TableName='Alerts_History_Employees'" in sql
    assert "AND ColumnName='AlertsHistoryId'" in sql


def test_schema_hash_is_ordered_in_python_without_string_agg() -> None:
    class Cursor:
        sql = ""

        def execute(self, sql: str):
            self.sql = sql
            return self

        @staticmethod
        def fetchall():
            return [
                (
                    "dbo",
                    "Products",
                    1,
                    "ProductID",
                    "int",
                    4,
                    10,
                    0,
                    False,
                    True,
                    False,
                    0,
                ),
                (
                    "dbo",
                    "Products",
                    2,
                    "ProductName",
                    "nvarchar",
                    200,
                    0,
                    0,
                    True,
                    False,
                    False,
                    0,
                ),
            ]

    cursor = Cursor()
    expected_payload = json.dumps(
        [
            [
                "dbo",
                "Products",
                "1",
                "ProductID",
                "int",
                "4",
                "10",
                "0",
                "False",
                "True",
                "False",
                "0",
            ],
            [
                "dbo",
                "Products",
                "2",
                "ProductName",
                "nvarchar",
                "200",
                "0",
                "0",
                "True",
                "False",
                "False",
                "0",
            ],
        ],
        ensure_ascii=False,
        separators=(",", ":"),
    )

    assert _schema_hash(cursor, TARGET_DATABASE) == hashlib.sha256(
        expected_payload.encode("utf-8")
    ).hexdigest()
    assert "ORDER BY s.name,t.name,c.column_id" in cursor.sql
    assert "STRING_AGG" not in cursor.sql


def test_missing_optional_product_map_does_not_compile_a_count_query() -> None:
    class Result:
        @staticmethod
        def fetchone():
            return (0,)

    class Cursor:
        statements: list[str] = []

        def execute(self, sql: str):
            self.statements.append(sql)
            return Result()

    cursor = Cursor()

    assert _optional_product_map_rows(cursor) == 0
    assert len(cursor.statements) == 1
    assert "OBJECT_ID" in cursor.statements[0]
    assert "COUNT_BIG" not in cursor.statements[0]


def test_sql_never_targets_a_source_database_for_dml() -> None:
    sql = _sql()
    source_literals = (
        "POS_LE_BOUTIQUE_INSTYLE",
        "POS_Instyle_Fragrance",
    )
    direct_source_dml = re.compile(
        r"\b(?:INSERT(?:\s+INTO)?|UPDATE|DELETE(?:\s+FROM)?|TRUNCATE\s+TABLE|"
        r"DROP\s+TABLE|ALTER\s+TABLE)\s+"
        r"(?:\[?POS_LE_BOUTIQUE_INSTYLE\]?|\[?POS_Instyle_Fragrance\]?)\.",
        re.IGNORECASE,
    )

    assert not direct_source_dml.search(sql)
    for source in source_literals:
        assert f"DECLARE @Source" in sql
        assert source in sql


def test_preview_result_exposes_contract_not_sql_or_credentials() -> None:
    result = _preview_result(
        {
            "operation": OPERATION_NAME,
            "idempotencyKey": "ticket-347073-set-based-demo",
            "planHash": "a" * 64,
            "fixedSources": ["LE_BOUTIQUE_INSTYLE", "Instyle_Fragrance"],
            "fixedTarget": "DEMO_NOVA_CAFE",
            "sourceRows": {},
            "targetState": {},
            "copyMode": "single_database_side_set_based_sql",
            "coldHistoryAction": "copy_missing_rows_set_based",
            "targetBackupRequired": False,
        },
        replay=False,
    )

    flattened = repr(result).casefold()
    assert result["operation"] == "nova_sql_instyle_demo_sync_preview"
    assert result["copyMode"] == "single_database_side_set_based_sql"
    assert result["targetBackupRequired"] is False
    assert "sql_resource" not in flattened
    assert "password" not in flattened
    assert "connection" not in flattened


def test_developer_secret_files_are_mounted_only_for_taylors_broker_lane() -> None:
    provision = (
        ROOT / "deploy" / "gcp" / "agent-runtime" / "provision-private-runtime.ps1"
    ).read_text(encoding="utf-8")
    launcher = (
        ROOT / "deploy" / "gcp" / "agent-runtime" / "run-salesforce-broker.sh"
    ).read_text(encoding="utf-8")

    assert "nova-agents-novapos-developer-username" in provision
    assert "nova-agents-novapos-developer-password" in provision
    assert 'owner = "nova-salesforce-broker"' in provision
    coding_guard = 'if [ "$lane" = coding_agent ]; then'
    assert launcher.count(coding_guard) == 1
    guarded = launcher.split(coding_guard, 1)[1].rsplit("\nfi", 1)[0]
    assert "NOVA_SQL_DEVELOPER_USERNAME_FILE" in guarded
    assert "NOVA_SQL_DEVELOPER_PASSWORD_FILE" in guarded
