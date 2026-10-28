from __future__ import annotations

# AgentChat/coding_agent 2026-07-28T04:19:17Z

import copy
import re

import pytest

from scoped_operations_mcp.nova_sql_instyle_demo_rebuild import (
    INVOICE_PRODUCTS_TABLE_NAME,
    FIXED_OPERATION_QUERY_TIMEOUT_SECONDS,
    SOURCE_A_DATABASE,
    SOURCE_A_USERNAME,
    SOURCE_B_DATABASE,
    SOURCE_B_ID_OFFSET,
    SOURCE_B_USERNAME,
    TARGET_DATABASE,
    TARGET_USERNAME,
    ColumnSpec,
    DatabaseSnapshot,
    InstyleDemoRebuildOperation,
    InstyleDemoRebuildScopeError,
    InstyleDemoRebuildUnavailableError,
    LocalProtectedDemoRestoreGateway,
    TableSpec,
    _build_merge_dataset,
    _capture_snapshot,
    _capture_streamed_table_fingerprint,
    _checkpoint,
    _fixed_target_schema_omissions,
    _sha256_json,
    _transform_row,
    _validate_schema_contract,
    _write_json_atomic,
)
from scoped_operations_mcp.nova_sql_instyle_target_restore import (
    PROTECTED_BACKUP_QUERY_TIMEOUT_SECONDS,
    TargetScopedProtectedDemoRestoreGateway,
    _backup_payload,
    _snapshot_hash_from_payload,
)


def _schema_rows():
    return [
        ("dbo", "Products", "ProductID", 1, "int", 0, 1, 0, 0, 0, 1),
        ("dbo", "Products", "ProductName", 2, "varchar", 0, 0, 0, 0, 0, 0),
        ("dbo", "Products", "BarcodeNumber", 3, "varchar", 1, 0, 0, 0, 0, 0),
        ("dbo", "Products", "BarcodeNumber2", 4, "varchar", 1, 0, 0, 0, 0, 0),
        ("dbo", "Products", "SKU", 5, "varchar", 1, 0, 0, 0, 0, 0),
        ("dbo", "Products", "ProductIsAvailable", 6, "bit", 0, 0, 0, 0, 1, 0),
        ("dbo", "Invoice_Products", "InvoiceProductID", 1, "int", 0, 0, 0, 0, 0, 1),
        ("dbo", "Invoice_Products", "InvoiceID", 2, "int", 1, 0, 0, 0, 0, 0),
        ("dbo", "Invoice_Products", "ProductID", 3, "int", 0, 0, 0, 0, 0, 0),
        ("dbo", "Invoice_Products", "Quantity", 4, "int", 0, 0, 0, 0, 1, 0),
    ]


def _foreign_key_rows():
    return [
        ("dbo", "Invoice_Products", "ProductID", "dbo", "Products", "ProductID"),
    ]


def _source_a_rows():
    return {
        "dbo.Products": [
            (10, "Alpha", "111", "", "A", True),
            (20, "Beta", "222", "", "B", True),
        ],
        "dbo.Invoice_Products": [
            (1, 100, 10, 1),
            (2, None, 999, 1),
        ],
    }


def _source_b_rows():
    return {
        "dbo.Products": [
            (30, " Alpha ", "111", "", "a", True),
            (10, "Gamma", "333", "", "G", True),
        ],
        "dbo.Invoice_Products": [
            (2, 200, 10, 2),
        ],
    }


class SnapshotCursor:
    def __init__(self, database_name, table_rows, snapshot_isolation_state=1):
        self.database_name = database_name
        self.table_rows = table_rows
        self.snapshot_isolation_state = snapshot_isolation_state
        self.rows = []
        self.commands = []

    def execute(self, sql, parameters=None):
        self.commands.append((sql, list(parameters or [])))
        normalized = " ".join(str(sql).split())
        upper = normalized.upper()
        if upper == "SELECT DB_NAME()":
            self.rows = [(self.database_name,)]
        elif "FROM SYS.DATABASES" in upper:
            self.rows = [(self.snapshot_isolation_state,)]
        elif "FROM SYS.TABLES T JOIN SYS.SCHEMAS" in upper:
            self.rows = _schema_rows()
        elif "FROM SYS.FOREIGN_KEY_COLUMNS" in upper:
            self.rows = _foreign_key_rows()
        elif upper.startswith(("SET TRANSACTION ISOLATION LEVEL", "BEGIN TRANSACTION")):
            self.rows = []
        elif upper.startswith("SELECT ") and " FROM [DBO].[PRODUCTS]" in upper:
            self.rows = list(self.table_rows["dbo.Products"])
        elif upper.startswith("SELECT ") and " FROM [DBO].[INVOICE_PRODUCTS]" in upper:
            self.rows = list(self.table_rows["dbo.Invoice_Products"])
        else:
            raise AssertionError((sql, parameters))
        return self

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return list(self.rows)


class SnapshotConnection:
    def __init__(self, database_name, table_rows, snapshot_isolation_state=1):
        self.cursor_value = SnapshotCursor(
            database_name,
            table_rows,
            snapshot_isolation_state,
        )
        self.timeout = 0
        self.autocommit = True
        self.closed = False
        self.rollbacks = 0

    def cursor(self):
        return self.cursor_value

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closed = True


class IsolationOrderCursor(SnapshotCursor):
    def __init__(self, database_name, table_rows, events, snapshot_isolation_state):
        super().__init__(
            database_name,
            table_rows,
            snapshot_isolation_state,
        )
        self.events = events

    def execute(self, sql, parameters=None):
        self.events.append(("sql", " ".join(str(sql).split()).upper()))
        return super().execute(sql, parameters)


class IsolationOrderConnection:
    def __init__(self, database_name, table_rows, snapshot_isolation_state=1):
        self.events = []
        self.cursor_value = IsolationOrderCursor(
            database_name,
            table_rows,
            self.events,
            snapshot_isolation_state,
        )
        self.timeout = 0
        self._autocommit = False
        self.closed = False
        self.rollbacks = 0

    @property
    def autocommit(self):
        return self._autocommit

    @autocommit.setter
    def autocommit(self, value):
        self._autocommit = bool(value)
        self.events.append(("autocommit", self._autocommit))

    def cursor(self):
        return self.cursor_value

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closed = True


class SafeRestoreGateway:
    def capability_status(self, *, target_database):
        assert target_database == TARGET_DATABASE
        return {
            "ok": True,
            "contractVersion": "test-v1",
            "completeBackup": True,
            "backupReadback": True,
            "protectedReset": True,
            "rollback": True,
            "applicationLock": True,
            "separateAccountConnections": True,
            "noCrossDatabaseTenantRights": True,
            "directOperations": [],
        }


class ExecutionCursor(SnapshotCursor):
    def __init__(self, state):
        super().__init__(TARGET_DATABASE, state["rows"])
        self.state = state

    def execute(self, sql, parameters=None):
        normalized = " ".join(str(sql).split())
        upper = normalized.upper()
        self.commands.append((sql, list(parameters or [])))
        self.state["events"].append(("sql", normalized))
        if upper == "SELECT DB_NAME()":
            self.rows = [(TARGET_DATABASE,)]
        elif "FROM SYS.DATABASES" in upper:
            self.rows = [(1,)]
        elif "FROM SYS.TABLES T JOIN SYS.SCHEMAS" in upper:
            self.rows = _schema_rows()
        elif "FROM SYS.FOREIGN_KEY_COLUMNS" in upper:
            self.rows = _foreign_key_rows()
        elif "SP_GETAPPLOCK" in upper:
            self.rows = [(0,)]
        elif "SELECT CASE WHEN OBJECT_ID" in upper:
            key = str(list(parameters or [""])[0])
            exists = (
                key == "dbo.__codex_instyle_demo_rebuild_receipts"
                and self.state["durable_table"]
            ) or key in self.state.setdefault("backup_tables", {})
            self.rows = [(1 if exists else 0,)]
        elif upper.startswith("SELECT * INTO [DBO].[__NOVA_REBUILD_BACKUP_"):
            match = re.search(
                r"SELECT \* INTO \[([^\]]+)\]\.\[([^\]]+)\] "
                r"FROM \[([^\]]+)\]\.\[([^\]]+)\]",
                normalized,
                re.IGNORECASE,
            )
            assert match
            backup_key = f"{match.group(1)}.{match.group(2)}"
            source_key = next(
                key
                for key in self.state["rows"]
                if key.casefold()
                == f"{match.group(3)}.{match.group(4)}".casefold()
            )
            self.state.setdefault("backup_tables", {})[backup_key] = copy.deepcopy(
                self.state["rows"][source_key]
            )
            self.rows = []
        elif upper.startswith(
            "SELECT COUNT_BIG(*) FROM [DBO].[__NOVA_REBUILD_BACKUP_"
        ):
            match = re.search(
                r"FROM \[([^\]]+)\]\.\[([^\]]+)\]",
                normalized,
                re.IGNORECASE,
            )
            assert match
            backup_key = next(
                key
                for key in self.state.setdefault("backup_tables", {})
                if key.casefold()
                == f"{match.group(1)}.{match.group(2)}".casefold()
            )
            self.rows = [(len(self.state["backup_tables"][backup_key]),)]
        elif upper.startswith("INSERT INTO [DBO].[") and "__NOVA_REBUILD_BACKUP_" in upper:
            match = re.search(
                r"INSERT INTO \[([^\]]+)\]\.\[([^\]]+)\].* "
                r"FROM \[([^\]]+)\]\.\[([^\]]+)\]",
                normalized,
                re.IGNORECASE,
            )
            assert match
            target_key = next(
                key
                for key in self.state["rows"]
                if key.casefold()
                == f"{match.group(1)}.{match.group(2)}".casefold()
            )
            backup_key = next(
                key
                for key in self.state.setdefault("backup_tables", {})
                if key.casefold()
                == f"{match.group(3)}.{match.group(4)}".casefold()
            )
            self.state["rows"][target_key] = copy.deepcopy(
                self.state["backup_tables"][backup_key]
            )
            self.rows = []
        elif upper.startswith(
            "SELECT [PLANHASH],[STATUS],[READBACKHASH] FROM "
            "[DBO].[__CODEX_INSTYLE_DEMO_REBUILD_RECEIPTS]"
        ):
            key = list(parameters or [])[0]
            receipt = self.state["durable_receipts"].get(key)
            self.rows = (
                [(receipt["planHash"], receipt["status"], receipt["readbackHash"])]
                if receipt
                else []
            )
        elif upper.startswith("IF OBJECT_ID(N'DBO.__CODEX_INSTYLE_DEMO_REBUILD_RECEIPTS'"):
            self.state["durable_table"] = True
            self.rows = []
        elif upper.startswith("INSERT INTO [DBO].[__CODEX_INSTYLE_DEMO_REBUILD_RECEIPTS]"):
            values = list(parameters or [])
            self.state["durable_receipts"][values[0]] = {
                "planHash": values[1],
                "status": values[2],
                "readbackHash": values[3],
            }
            self.rows = []
        elif upper.startswith(
            (
                "SET XACT_ABORT",
                "SET TRANSACTION ISOLATION LEVEL",
                "BEGIN TRANSACTION",
                "SET IDENTITY_INSERT",
                "CREATE TABLE [DBO].[__CODEX_QUARANTINE_",
            )
        ):
            self.rows = []
        elif upper.startswith("DELETE FROM [DBO].[INVOICE_PRODUCTS]"):
            self.state["rows"]["dbo.Invoice_Products"] = []
            self.rows = []
        elif upper.startswith("DELETE FROM [DBO].[PRODUCTS]"):
            self.state["rows"]["dbo.Products"] = []
            self.rows = []
        elif "GROUP BY" in upper and "HAVING COUNT_BIG(*) > 1" in upper:
            self.rows = [(0,)]
        elif "LEFT JOIN" in upper and "IS NULL" in upper:
            self.rows = [(0,)]
        elif upper.startswith("SELECT COUNT_BIG(*) FROM [DBO].[PRODUCTS]"):
            self.rows = [(len(self.state["rows"]["dbo.Products"]),)]
        elif upper.startswith("SELECT COUNT_BIG(*) FROM [DBO].[INVOICE_PRODUCTS]"):
            self.rows = [(len(self.state["rows"]["dbo.Invoice_Products"]),)]
        elif upper.startswith("SELECT COUNT_BIG(*) FROM [DBO].[__CODEX_QUARANTINE_"):
            self.rows = [(len(self.state["quarantine"]),)]
        elif upper.startswith("SELECT ") and " FROM [DBO].[PRODUCTS]" in upper:
            self.rows = list(self.state["rows"]["dbo.Products"])
        elif upper.startswith("SELECT ") and " FROM [DBO].[INVOICE_PRODUCTS]" in upper:
            self.rows = list(self.state["rows"]["dbo.Invoice_Products"])
        else:
            raise AssertionError((sql, parameters))
        return self

    def executemany(self, sql, parameter_rows):
        normalized = " ".join(str(sql).split())
        upper = normalized.upper()
        values = list(parameter_rows)
        self.commands.append((sql, values))
        self.state["events"].append(("executemany", normalized, len(values)))
        if upper.startswith("INSERT INTO [DBO].[PRODUCTS]"):
            self.state["rows"]["dbo.Products"].extend(values)
        elif upper.startswith("INSERT INTO [DBO].[INVOICE_PRODUCTS]"):
            self.state["rows"]["dbo.Invoice_Products"].extend(values)
        elif upper.startswith("INSERT INTO [DBO].[__CODEX_QUARANTINE_"):
            self.state["quarantine"].extend(values)
        else:
            raise AssertionError(sql)
        self.rows = []
        return self


class ExecutionConnection:
    def __init__(self, state):
        self.state = state
        self.cursor_value = ExecutionCursor(state)
        self.timeout = 0
        self.autocommit = False
        self.closed = False

    def cursor(self):
        return self.cursor_value

    def commit(self):
        self.state["commits"] += 1
        self.state["events"].append(("commit",))

    def rollback(self):
        self.state["rollbacks"] += 1
        self.state["events"].append(("rollback",))

    def close(self):
        self.closed = True


class RecordingRestoreGateway(SafeRestoreGateway):
    def __init__(self, state):
        self.state = state

    def create_complete_backup(
        self,
        _connection,
        *,
        target_database,
        idempotency_key,
        plan_hash,
        expected_snapshot_hash,
        required_tables,
    ):
        assert target_database == TARGET_DATABASE
        assert required_tables == ["dbo.Invoice_Products", "dbo.Products"]
        self.state["events"].append(("backup", idempotency_key, plan_hash))
        return {
            "ok": True,
            "complete": True,
            "readbackVerified": True,
            "rollbackAvailable": True,
            "snapshotHash": expected_snapshot_hash,
            "receiptId": "fake-backup-receipt",
        }

    def verify_backup(
        self,
        _connection,
        *,
        target_database,
        backup_receipt,
        expected_snapshot_hash,
    ):
        assert target_database == TARGET_DATABASE
        assert backup_receipt["snapshotHash"] == expected_snapshot_hash
        self.state["events"].append(("backup_verify",))
        return {
            "ok": True,
            "readbackVerified": True,
            "rollbackAvailable": True,
            "receiptId": backup_receipt["receiptId"],
        }

    def reset_target(
        self,
        _connection,
        *,
        target_database,
        idempotency_key,
        plan_hash,
        backup_receipt,
        expected_schema_hash,
    ):
        assert target_database == TARGET_DATABASE
        assert backup_receipt["receiptId"] == "fake-backup-receipt"
        assert any(event[0] == "backup_verify" for event in self.state["events"])
        self.state["events"].append(("reset", idempotency_key, plan_hash))
        self.state["rows"] = {"dbo.Products": [], "dbo.Invoice_Products": []}
        return {
            "ok": True,
            "reset": True,
            "readbackVerified": True,
            "targetReadyForLoad": True,
            "schemaHash": expected_schema_hash,
            "directOperations": [],
        }

    def rollback_target(self, *_args, **_kwargs):
        self.state["events"].append(("protected_rollback",))
        return {"ok": True, "restored": True, "readbackVerified": True}


def _snapshot(database_name, company_username, rows):
    return _capture_snapshot(
        SnapshotConnection(database_name, copy.deepcopy(rows)),
        company_username,
        database_name,
        include_rows=True,
        query_timeout_seconds=30,
    )


def test_fixed_preview_resolves_three_separate_connections_and_is_stable(tmp_path):
    calls = []
    fixtures = {
        SOURCE_A_USERNAME: (SOURCE_A_DATABASE, _source_a_rows()),
        SOURCE_B_USERNAME: (SOURCE_B_DATABASE, _source_b_rows()),
        TARGET_USERNAME: (TARGET_DATABASE, {"dbo.Products": [], "dbo.Invoice_Products": []}),
    }

    def connect(company_username, read_only):
        calls.append((company_username, read_only))
        database, rows = fixtures[company_username]
        return SnapshotConnection(database, copy.deepcopy(rows))

    operation = InstyleDemoRebuildOperation(
        connect=connect,
        state_dir=tmp_path,
        restore_gateway=SafeRestoreGateway(),
    )
    first = operation.preview(idempotency_key="instyle-demo-preview-v1")
    second = operation.preview(idempotency_key="instyle-demo-preview-v1")

    assert calls == [
        (SOURCE_A_USERNAME, True),
        (SOURCE_B_USERNAME, True),
        (TARGET_USERNAME, True),
    ]
    assert first["planHash"] == second["planHash"]
    assert second["idempotentReplay"] is True
    assert first["requiredTableCount"] == 2
    assert first["productDedupeCount"] == 1
    assert first["placeholderProductCount"] == 1
    assert first["quarantinedNullInvoiceIdCount"] == 1
    assert all(
        source["consistencyMode"] == "snapshot"
        for source in first["sources"]
    )
    assert first["callerSelectedAccountsAccepted"] is False
    assert first["arbitrarySqlAccepted"] is False
    assert first["genericExecutorChanged"] is False


def test_fixed_operation_never_inherits_generic_read_timeout(tmp_path):
    operation = InstyleDemoRebuildOperation(
        connect=lambda *_args: pytest.fail("database connection must not be attempted"),
        state_dir=tmp_path,
        restore_gateway=SafeRestoreGateway(),
        query_timeout_seconds=30,
    )

    assert (
        operation._query_timeout_seconds
        == FIXED_OPERATION_QUERY_TIMEOUT_SECONDS
        == 3_600
    )


def test_snapshot_isolation_is_selected_before_transaction_mode_starts():
    connection = IsolationOrderConnection(SOURCE_A_DATABASE, _source_a_rows())

    _capture_snapshot(
        connection,
        SOURCE_A_USERNAME,
        SOURCE_A_DATABASE,
        include_rows=True,
        query_timeout_seconds=30,
    )

    isolation_index = connection.events.index(
        ("sql", "SET TRANSACTION ISOLATION LEVEL SNAPSHOT")
    )
    transaction_mode_index = connection.events.index(("autocommit", False))
    begin_index = connection.events.index(("sql", "BEGIN TRANSACTION"))
    assert connection.events[0] == ("autocommit", True)
    assert isolation_index < transaction_mode_index < begin_index


def test_serializable_capture_is_used_and_released_when_snapshot_isolation_is_off():
    connection = IsolationOrderConnection(
        SOURCE_A_DATABASE,
        _source_a_rows(),
        snapshot_isolation_state=0,
    )

    snapshot = _capture_snapshot(
        connection,
        SOURCE_A_USERNAME,
        SOURCE_A_DATABASE,
        include_rows=True,
        query_timeout_seconds=30,
        keep_transaction_open=True,
    )

    isolation_index = connection.events.index(
        ("sql", "SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
    )
    transaction_mode_index = connection.events.index(("autocommit", False))
    begin_index = connection.events.index(("sql", "BEGIN TRANSACTION"))
    assert isolation_index < transaction_mode_index < begin_index
    assert not any(
        event == ("sql", "SET TRANSACTION ISOLATION LEVEL SNAPSHOT")
        for event in connection.events
    )
    assert snapshot.consistency_mode == "serializable_capture"
    assert connection.rollbacks == 1


def test_streamed_table_uses_bounded_database_fingerprint():
    class FingerprintCursor:
        def __init__(self):
            self.sql = ""

        def execute(self, sql, parameters=None):
            assert parameters is None
            self.sql = " ".join(str(sql).split())
            return self

        def fetchall(self):
            return [(0, 2, 101), (1, 3, -202)]

    spec = TableSpec(
        schema="dbo",
        name="InventoryHistoryItem",
        columns=(
            ColumnSpec("InventoryHistoryItemId", 1, "int", False, True, False, False, False, 1),
            ColumnSpec("OriginalProductId", 2, "int", False, False, False, False, False),
        ),
    )
    cursor = FingerprintCursor()

    count, data_hash = _capture_streamed_table_fingerprint(cursor, spec)

    assert count == 5
    assert re.fullmatch(r"[0-9a-f]{64}", data_hash)
    assert "CHECKSUM_AGG(BINARY_CHECKSUM(" in cursor.sql
    assert "GROUP BY" in cursor.sql


def test_streamed_product_reference_maps_known_and_source_tags_expected_orphans():
    spec = TableSpec(
        schema="dbo",
        name="InventoryHistoryItem",
        columns=(
            ColumnSpec("InventoryHistoryItemId", 1, "int", False, True, False, False, False, 1),
            ColumnSpec("OriginalProductId", 2, "int", False, False, False, False, False),
        ),
    )
    known = _transform_row(
        SOURCE_A_USERNAME,
        {"InventoryHistoryItemId": 10, "OriginalProductId": 20},
        spec,
        spec,
        {(SOURCE_A_USERNAME, 20): 200},
    )
    missing = _transform_row(
        SOURCE_B_USERNAME,
        {"InventoryHistoryItemId": 11, "OriginalProductId": 21},
        spec,
        spec,
        {},
    )

    assert known["OriginalProductId"] == 200
    assert "__expectedProductOrphan" not in known
    assert missing["InventoryHistoryItemId"] == SOURCE_B_ID_OFFSET + 11
    assert missing["OriginalProductId"] == -1_000_000_000 + 21
    assert missing["__expectedProductOrphan"] is True


def test_streamed_target_backup_uses_target_table_without_row_materialization():
    key = "dbo.InventoryHistoryItem"
    spec = TableSpec(
        schema="dbo",
        name="InventoryHistoryItem",
        columns=(
            ColumnSpec("InventoryHistoryItemId", 1, "int", False, True, False, False, False, 1),
            ColumnSpec("OriginalProductId", 2, "int", False, False, False, False, False),
        ),
    )
    schema_hash = "a" * 64
    data_hash = "b" * 64
    snapshot_hash = _sha256_json(
        {
            "databaseName": TARGET_DATABASE,
            "schemaHash": schema_hash,
            "tables": [{"table": key, "rowCount": 30_083_607, "dataHash": data_hash}],
        }
    )
    snapshot = DatabaseSnapshot(
        company_username=TARGET_USERNAME,
        database_name=TARGET_DATABASE,
        captured_at="2026-07-28T00:00:00+00:00",
        schema_hash=schema_hash,
        snapshot_hash=snapshot_hash,
        tables={key: spec},
        table_hashes={key: data_hash},
        row_counts={key: 30_083_607},
        streamed_tables=(key,),
    )

    payload = _backup_payload(
        snapshot,
        [key],
        {key: "dbo.__nova_rebuild_backup_receipt_table"},
    )

    assert payload["tables"][key]["storage"] == "target_table"
    assert "rows" not in payload["tables"][key]
    assert _snapshot_hash_from_payload(payload) == snapshot_hash


def test_protected_backup_hash_preserves_exact_mixed_case_table_order():
    upper = TableSpec(
        schema="dbo",
        name="ZTable",
        columns=(
            ColumnSpec("ID", 1, "int", False, True, False, False, False, 1),
        ),
    )
    lower = TableSpec(
        schema="dbo",
        name="aTable",
        columns=(
            ColumnSpec("ID", 1, "int", False, True, False, False, False, 1),
        ),
    )
    tables = {lower.key: lower, upper.key: upper}
    table_hashes = {
        lower.key: "b" * 64,
        upper.key: "c" * 64,
    }
    row_counts = {
        lower.key: 2,
        upper.key: 1,
    }
    schema_hash = "a" * 64
    snapshot_hash = _sha256_json(
        {
            "databaseName": TARGET_DATABASE,
            "schemaHash": schema_hash,
            "tables": [
                {
                    "table": key,
                    "rowCount": row_counts[key],
                    "dataHash": table_hashes[key],
                }
                for key in sorted(tables)
            ],
        }
    )
    snapshot = DatabaseSnapshot(
        company_username=TARGET_USERNAME,
        database_name=TARGET_DATABASE,
        captured_at="2026-07-28T00:00:00+00:00",
        schema_hash=schema_hash,
        snapshot_hash=snapshot_hash,
        tables=tables,
        table_hashes=table_hashes,
        row_counts=row_counts,
        streamed_tables=tuple(tables),
    )
    payload = _backup_payload(
        snapshot,
        [upper.key, lower.key],
        {
            upper.key: "dbo.__nova_rebuild_backup_upper",
            lower.key: "dbo.__nova_rebuild_backup_lower",
        },
    )

    assert sorted(tables) != sorted(tables, key=str.casefold)
    assert _snapshot_hash_from_payload(payload) == snapshot_hash


def test_source_qualified_mapping_never_matches_product_ids_numerically_across_accounts():
    source_a = _snapshot(SOURCE_A_DATABASE, SOURCE_A_USERNAME, _source_a_rows())
    source_b = _snapshot(SOURCE_B_DATABASE, SOURCE_B_USERNAME, _source_b_rows())
    target = _snapshot(
        TARGET_DATABASE,
        TARGET_USERNAME,
        {"dbo.Products": [], "dbo.Invoice_Products": []},
    )
    required = _validate_schema_contract(source_a, source_b, target)

    dataset = _build_merge_dataset(source_a, source_b, target, required)

    products_key = next(key for key in dataset.rows if key.casefold() == "dbo.products")
    invoices_key = next(key for key in dataset.rows if key.casefold() == "dbo.invoice_products")
    product_rows = dataset.rows[products_key]
    invoice_rows = dataset.rows[invoices_key]
    alpha = next(row for row in product_rows if str(row["ProductName"]).strip().casefold() == "alpha")
    gamma = next(row for row in product_rows if str(row["ProductName"]).strip().casefold() == "gamma")
    missing_product = next(
        row
        for row in product_rows
        if str(row["ProductName"]).startswith("Inactive missing product")
    )
    source_a_invoice = next(row for row in invoice_rows if row["InvoiceProductID"] == 1)
    source_b_invoice = next(
        row for row in invoice_rows if row["InvoiceProductID"] == SOURCE_B_ID_OFFSET + 2
    )

    assert alpha["ProductID"] == 30
    assert gamma["ProductID"] == 10
    assert source_a_invoice["ProductID"] == alpha["ProductID"]
    assert source_b_invoice["ProductID"] == gamma["ProductID"]
    assert source_a_invoice["ProductID"] != source_b_invoice["ProductID"]
    assert missing_product["ProductIsAvailable"] is False
    assert len(dataset.quarantine_rows) == 1
    assert dataset.placeholder_product_count == 1
    assert all(row["ProductID"] != -1 for row in invoice_rows)


def test_only_fixed_original_hours_schema_difference_is_omitted_with_exact_evidence():
    source_a = _snapshot(SOURCE_A_DATABASE, SOURCE_A_USERNAME, _source_a_rows())
    source_b = _snapshot(SOURCE_B_DATABASE, SOURCE_B_USERNAME, _source_b_rows())
    target = _snapshot(
        TARGET_DATABASE,
        TARGET_USERNAME,
        {"dbo.Products": [], "dbo.Invoice_Products": []},
    )
    target_hours = TableSpec(
        schema="dbo",
        name="Employees_Hours",
        columns=(
            ColumnSpec(
                "EmployeeHoursID",
                1,
                "int",
                False,
                True,
                False,
                False,
                False,
                1,
            ),
        ),
    )
    source_hours = TableSpec(
        schema="dbo",
        name="Employees_Hours",
        columns=(
            *target_hours.columns,
            ColumnSpec(
                "OriginalHours",
                2,
                "decimal",
                True,
                False,
                False,
                False,
                False,
            ),
        ),
    )
    source_b.tables[source_hours.key] = source_hours
    source_b.rows[source_hours.key] = [
        {"EmployeeHoursID": 1, "OriginalHours": 8},
        {"EmployeeHoursID": 2, "OriginalHours": None},
    ]
    source_b.row_counts[source_hours.key] = 2
    target.tables[target_hours.key] = target_hours
    target.rows[target_hours.key] = []
    target.row_counts[target_hours.key] = 0

    required = _validate_schema_contract(source_a, source_b, target)
    omissions = _fixed_target_schema_omissions(source_a, source_b, target)

    assert source_hours.key in required
    assert omissions == [
        {
            "sourceCompanyUsername": SOURCE_B_USERNAME,
            "sourceDatabaseName": SOURCE_B_DATABASE,
            "table": "dbo.Employees_Hours",
            "column": "OriginalHours",
            "sourceType": "decimal",
            "nullable": True,
            "sourceRowCount": 2,
            "populatedRowCount": 1,
            "targetDatabaseName": TARGET_DATABASE,
            "targetColumnPresent": False,
            "copyBehavior": (
                "The source rows and all matching Employees_Hours columns remain "
                "in scope; OriginalHours values are not copied because "
                "POS_DEMO_NOVA_CAFE has no such column."
            ),
        }
    ]


def test_fixed_original_hours_omission_fails_closed_if_its_role_changes():
    source_a = _snapshot(SOURCE_A_DATABASE, SOURCE_A_USERNAME, _source_a_rows())
    source_b = _snapshot(SOURCE_B_DATABASE, SOURCE_B_USERNAME, _source_b_rows())
    target = _snapshot(
        TARGET_DATABASE,
        TARGET_USERNAME,
        {"dbo.Products": [], "dbo.Invoice_Products": []},
    )
    source_hours = TableSpec(
        schema="dbo",
        name="Employees_Hours",
        columns=(
            ColumnSpec(
                "OriginalHours",
                1,
                "decimal",
                True,
                False,
                False,
                False,
                False,
                1,
            ),
        ),
    )
    target_hours = TableSpec(
        schema="dbo",
        name="Employees_Hours",
        columns=(),
    )
    source_b.tables[source_hours.key] = source_hours
    target.tables[target_hours.key] = target_hours

    with pytest.raises(
        InstyleDemoRebuildScopeError,
        match="changed type, nullability, key",
    ):
        _validate_schema_contract(source_a, source_b, target)


def test_every_other_source_only_column_still_fails_closed():
    source_a = _snapshot(SOURCE_A_DATABASE, SOURCE_A_USERNAME, _source_a_rows())
    source_b = _snapshot(SOURCE_B_DATABASE, SOURCE_B_USERNAME, _source_b_rows())
    target = _snapshot(
        TARGET_DATABASE,
        TARGET_USERNAME,
        {"dbo.Products": [], "dbo.Invoice_Products": []},
    )
    source_hours = TableSpec(
        schema="dbo",
        name="Employees_Hours",
        columns=(
            ColumnSpec(
                "UnexpectedSourceOnly",
                1,
                "decimal",
                True,
                False,
                False,
                False,
                False,
            ),
        ),
    )
    target_hours = TableSpec(
        schema="dbo",
        name="Employees_Hours",
        columns=(),
    )
    source_b.tables[source_hours.key] = source_hours
    target.tables[target_hours.key] = target_hours

    with pytest.raises(
        InstyleDemoRebuildScopeError,
        match=r"Employees_Hours\.UnexpectedSourceOnly is missing",
    ):
        _validate_schema_contract(source_a, source_b, target)


def test_preview_rejects_any_connection_that_is_not_the_fixed_database(tmp_path):
    def connect(company_username, _read_only):
        rows = _source_a_rows() if company_username == SOURCE_A_USERNAME else _source_b_rows()
        database = "POS_WRONG" if company_username == SOURCE_B_USERNAME else f"POS_{company_username}"
        return SnapshotConnection(database, rows)

    operation = InstyleDemoRebuildOperation(
        connect=connect,
        state_dir=tmp_path,
        restore_gateway=SafeRestoreGateway(),
    )

    with pytest.raises(InstyleDemoRebuildScopeError, match="unexpected database"):
        operation.preview(idempotency_key="instyle-demo-wrong-database-v1")


def test_preview_rejects_restore_gateway_that_uses_unsafe_direct_operations(tmp_path):
    class UnsafeRestoreGateway(SafeRestoreGateway):
        def capability_status(self, *, target_database):
            value = super().capability_status(target_database=target_database)
            value["directOperations"] = ["DELETE", "disable_constraints"]
            return value

    operation = InstyleDemoRebuildOperation(
        connect=lambda *_args: pytest.fail("database connection must not be attempted"),
        state_dir=tmp_path,
        restore_gateway=UnsafeRestoreGateway(),
    )

    with pytest.raises(InstyleDemoRebuildScopeError, match="forbidden direct"):
        operation.preview(idempotency_key="instyle-demo-unsafe-gateway-v1")


def test_execute_rejects_changed_source_snapshot_before_backup(tmp_path):
    fixtures = {
        SOURCE_A_USERNAME: [SOURCE_A_DATABASE, _source_a_rows()],
        SOURCE_B_USERNAME: [SOURCE_B_DATABASE, _source_b_rows()],
        TARGET_USERNAME: [TARGET_DATABASE, {"dbo.Products": [], "dbo.Invoice_Products": []}],
    }

    def connect(company_username, _read_only):
        database, rows = fixtures[company_username]
        return SnapshotConnection(database, copy.deepcopy(rows))

    operation = InstyleDemoRebuildOperation(
        connect=connect,
        state_dir=tmp_path,
        restore_gateway=SafeRestoreGateway(),
    )
    preview = operation.preview(idempotency_key="instyle-demo-source-drift-v1")
    fixtures[SOURCE_B_USERNAME][1]["dbo.Products"].append((77, "Drift", "777", "", "D", True))

    with pytest.raises(InstyleDemoRebuildScopeError, match="source B source snapshot changed"):
        operation.execute(
            idempotency_key="instyle-demo-source-drift-v1",
            preview_hash=preview["planHash"],
        )


def test_execute_requires_exact_preview_hash_and_configured_rollback(tmp_path):
    operation = InstyleDemoRebuildOperation(
        connect=lambda *_args: pytest.fail("database connection must not be attempted"),
        state_dir=tmp_path,
        restore_gateway=None,
    )

    with pytest.raises(InstyleDemoRebuildScopeError, match="exact hash"):
        operation.execute(
            idempotency_key="instyle-demo-invalid-hash-v1",
            preview_hash="not-a-hash",
        )
    with pytest.raises(InstyleDemoRebuildUnavailableError, match="not configured"):
        operation.preview(idempotency_key="instyle-demo-no-rollback-v1")


def test_local_restore_gateway_rejects_non_root_owned_helper_without_running_it(tmp_path):
    helper = tmp_path / "untrusted-helper"
    helper.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    helper.chmod(0o775)
    gateway = LocalProtectedDemoRestoreGateway(helper)

    with pytest.raises(InstyleDemoRebuildUnavailableError, match="ownership or permissions"):
        gateway.capability_status(target_database=TARGET_DATABASE)


def test_target_scoped_restore_gateway_backs_up_resets_and_restores_exact_rows(tmp_path):
    original = {
        "dbo.Products": copy.deepcopy(_source_a_rows()["dbo.Products"]),
        "dbo.Invoice_Products": copy.deepcopy(
            _source_a_rows()["dbo.Invoice_Products"]
        ),
    }
    state = {
        "rows": copy.deepcopy(original),
        "quarantine": [],
        "events": [],
        "commits": 0,
        "rollbacks": 0,
        "durable_table": False,
        "durable_receipts": {},
    }
    connection = ExecutionConnection(state)
    snapshot = _capture_snapshot(
        connection,
        TARGET_USERNAME,
        TARGET_DATABASE,
        include_rows=True,
        query_timeout_seconds=30,
        manage_transaction=False,
    )
    gateway = TargetScopedProtectedDemoRestoreGateway(tmp_path)
    required = ["dbo.Invoice_Products", "dbo.Products"]

    backup = gateway.create_complete_backup(
        connection,
        target_database=TARGET_DATABASE,
        idempotency_key="instyle-protected-gateway-v1",
        plan_hash="a" * 64,
        expected_snapshot_hash=snapshot.snapshot_hash,
        required_tables=required,
    )
    verified = gateway.verify_backup(
        connection,
        target_database=TARGET_DATABASE,
        backup_receipt=backup,
        expected_snapshot_hash=snapshot.snapshot_hash,
    )
    reset = gateway.reset_target(
        connection,
        target_database=TARGET_DATABASE,
        idempotency_key="instyle-protected-gateway-v1",
        plan_hash="a" * 64,
        backup_receipt=backup,
        expected_schema_hash=snapshot.schema_hash,
    )

    assert backup["complete"] is True
    assert backup["readbackVerified"] is True
    assert backup["rollbackAvailable"] is True
    assert verified["readbackVerified"] is True
    assert reset["targetReadyForLoad"] is True
    assert state["rows"] == {
        "dbo.Products": [],
        "dbo.Invoice_Products": [],
    }

    rolled_back = gateway.rollback_target(
        connection,
        target_database=TARGET_DATABASE,
        idempotency_key="instyle-protected-gateway-v1",
        plan_hash="a" * 64,
        backup_receipt=backup,
    )

    assert rolled_back["restored"] is True
    assert rolled_back["readbackVerified"] is True
    assert state["rows"] == original


def test_target_scoped_restore_gateway_never_inherits_generic_read_timeout(tmp_path):
    gateway = TargetScopedProtectedDemoRestoreGateway(
        tmp_path,
        query_timeout_seconds=30,
    )

    assert (
        gateway._query_timeout_seconds
        == PROTECTED_BACKUP_QUERY_TIMEOUT_SECONDS
        == 3_600
    )


def test_target_scoped_restore_gateway_rejects_any_other_database(tmp_path):
    gateway = TargetScopedProtectedDemoRestoreGateway(tmp_path)

    with pytest.raises(InstyleDemoRebuildScopeError, match="fixed"):
        gateway.capability_status(target_database="POS_OTHER")


def test_recover_restores_abandoned_load_without_reading_sources(tmp_path):
    original = {
        "dbo.Products": copy.deepcopy(_source_a_rows()["dbo.Products"]),
        "dbo.Invoice_Products": copy.deepcopy(
            _source_a_rows()["dbo.Invoice_Products"]
        ),
    }
    state = {
        "rows": copy.deepcopy(original),
        "quarantine": [],
        "events": [],
        "commits": 0,
        "rollbacks": 0,
        "durable_table": False,
        "durable_receipts": {},
    }
    fixtures = {
        SOURCE_A_USERNAME: (SOURCE_A_DATABASE, _source_a_rows()),
        SOURCE_B_USERNAME: (SOURCE_B_DATABASE, _source_b_rows()),
    }
    calls = []

    def connect(company_username, read_only):
        calls.append((company_username, read_only))
        if company_username == TARGET_USERNAME:
            return ExecutionConnection(state)
        database, rows = fixtures[company_username]
        return SnapshotConnection(database, copy.deepcopy(rows))

    gateway = TargetScopedProtectedDemoRestoreGateway(tmp_path)
    operation = InstyleDemoRebuildOperation(
        connect=connect,
        state_dir=tmp_path,
        restore_gateway=gateway,
    )
    key = "instyle-demo-abandoned-recovery-v1"
    preview = operation.preview(idempotency_key=key)
    target_connection = ExecutionConnection(state)
    target_snapshot = _capture_snapshot(
        target_connection,
        TARGET_USERNAME,
        TARGET_DATABASE,
        include_rows=True,
        query_timeout_seconds=30,
        manage_transaction=False,
    )
    required = ["dbo.Invoice_Products", "dbo.Products"]
    backup = gateway.create_complete_backup(
        target_connection,
        target_database=TARGET_DATABASE,
        idempotency_key=key,
        plan_hash=preview["planHash"],
        expected_snapshot_hash=target_snapshot.snapshot_hash,
        required_tables=required,
    )
    reset = gateway.reset_target(
        target_connection,
        target_database=TARGET_DATABASE,
        idempotency_key=key,
        plan_hash=preview["planHash"],
        backup_receipt=backup,
        expected_schema_hash=target_snapshot.schema_hash,
    )
    _write_json_atomic(
        operation._checkpoint_path(key),
        _checkpoint(
            key,
            preview["planHash"],
            "load_started",
            backup_receipt=backup,
            reset_receipt=reset,
        ),
    )
    assert state["rows"] == {
        "dbo.Products": [],
        "dbo.Invoice_Products": [],
    }

    calls.clear()
    result = operation.recover(
        idempotency_key=key,
        preview_hash=preview["planHash"],
    )

    assert calls == [(TARGET_USERNAME, False)]
    assert state["rows"] == original
    assert result["status"] == "rolled_back"
    assert result["recoveryAction"] == "protected_backup_restored"
    assert result["sourceDatabasesRead"] is False
    assert result["postWriteReadbackVerified"] is True
    assert result["idempotentReplay"] is False

    calls.clear()
    replay = operation.recover(
        idempotency_key=key,
        preview_hash=preview["planHash"],
    )
    assert calls == []
    assert replay["recoveryAction"] == "none_already_restored"
    assert replay["idempotentReplay"] is True


def test_execute_backs_up_before_reset_loads_in_one_transaction_and_reads_back(tmp_path):
    state = {
        "rows": {"dbo.Products": [], "dbo.Invoice_Products": []},
        "quarantine": [],
        "events": [],
        "commits": 0,
        "rollbacks": 0,
        "durable_table": False,
        "durable_receipts": {},
    }
    fixtures = {
        SOURCE_A_USERNAME: (SOURCE_A_DATABASE, _source_a_rows()),
        SOURCE_B_USERNAME: (SOURCE_B_DATABASE, _source_b_rows()),
    }
    calls = []

    def connect(company_username, read_only):
        calls.append((company_username, read_only))
        if company_username == TARGET_USERNAME:
            return ExecutionConnection(state)
        database, rows = fixtures[company_username]
        return SnapshotConnection(database, copy.deepcopy(rows))

    gateway = RecordingRestoreGateway(state)
    operation = InstyleDemoRebuildOperation(
        connect=connect,
        state_dir=tmp_path,
        restore_gateway=gateway,
    )
    preview = operation.preview(idempotency_key="instyle-demo-execute-v1")
    result = operation.execute(
        idempotency_key="instyle-demo-execute-v1",
        preview_hash=preview["planHash"],
    )

    backup_index = next(index for index, event in enumerate(state["events"]) if event[0] == "backup")
    verify_index = next(index for index, event in enumerate(state["events"]) if event[0] == "backup_verify")
    reset_index = next(index for index, event in enumerate(state["events"]) if event[0] == "reset")
    first_insert_index = next(
        index for index, event in enumerate(state["events"]) if event[0] == "executemany"
    )
    commit_index = next(index for index, event in enumerate(state["events"]) if event[0] == "commit")

    assert backup_index < verify_index < reset_index < first_insert_index < commit_index
    assert state["commits"] == 1
    assert len(state["rows"]["dbo.Products"]) == 4
    assert len(state["rows"]["dbo.Invoice_Products"]) == 2
    assert len(state["quarantine"]) == 1
    assert result["transactionCommitted"] is True
    assert result["postWriteReadbackVerified"] is True
    assert result["durableIdempotencyVerified"] is True
    assert result["idempotentReplay"] is False
    assert not any(event[0] == "protected_rollback" for event in state["events"])
    assert calls.count((SOURCE_A_USERNAME, True)) == 2
    assert calls.count((SOURCE_B_USERNAME, True)) == 2
    assert all(company in {SOURCE_A_USERNAME, SOURCE_B_USERNAME, TARGET_USERNAME} for company, _ in calls)

    operation._receipt_path("instyle-demo-execute-v1").unlink()
    commit_count = state["commits"]
    insert_count = sum(1 for event in state["events"] if event[0] == "executemany")
    recovered = operation.execute(
        idempotency_key="instyle-demo-execute-v1",
        preview_hash=preview["planHash"],
    )
    assert recovered["idempotentReplay"] is True
    assert state["commits"] == commit_count
    assert sum(1 for event in state["events"] if event[0] == "executemany") == insert_count
    assert sum(1 for event in state["events"] if event[0] == "reset") == 1

    event_count = len(state["events"])
    replay = operation.execute(
        idempotency_key="instyle-demo-execute-v1",
        preview_hash=preview["planHash"],
    )
    assert replay["idempotentReplay"] is True
    assert len(state["events"]) == event_count


def test_operation_source_contains_no_delete_drop_alter_or_cross_database_sql():
    source = __import__(
        "scoped_operations_mcp.nova_sql_instyle_demo_rebuild",
        fromlist=["__file__"],
    ).__file__
    text = open(source, encoding="utf-8").read()
    executable_sql = re.findall(r"[\"']((?:SELECT|INSERT|UPDATE|CREATE|SET|BEGIN|DECLARE)[^\"']*)", text, re.I)
    assert executable_sql
    assert not any(re.search(r"\b(?:DELETE|DROP|ALTER)\b", sql, re.I) for sql in executable_sql)
    assert "master.dbo." not in text.casefold()
    assert "use [" not in text.casefold()
    assert INVOICE_PRODUCTS_TABLE_NAME in text
