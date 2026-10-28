from __future__ import annotations

from pathlib import Path

import pytest

from scoped_operations_mcp.nova_sql_client import NovaSqlScopeError, ScopedNovaSqlClient
from scoped_operations_mcp.nova_sql_table_restore import (
    ColumnMetadata,
    NovaSqlTableRestoreOperation,
    NovaSqlTableRestoreScopeError,
    RestoreRequest,
    TEMP_TABLE,
    TableSnapshot,
    _analyze,
    _plan,
    _request,
    _update_sql,
)


class FakeSalesforce:
    def _resolve_nova_sql_account(self, company_username):
        return {"company_username": company_username, "password": "safe-test-password"}


class FakeConnection:
    autocommit = False


class RestoreCursor:
    timeout = 0
    fast_executemany = False
    rowcount = -1

    def __init__(self, database, state):
        self.database = database
        self.state = state
        self.rows = []

    def execute(self, sql, parameters=None):
        parameters = list(parameters or [])
        normalized = " ".join(str(sql).split())
        upper = normalized.upper()
        self.state["commands"].append((self.database, normalized, parameters))
        self.rows = []
        self.rowcount = -1

        if upper == "SELECT DB_NAME()":
            self.rows = [(self.database,)]
        elif "FROM SYS.TABLES T JOIN SYS.SCHEMAS" in upper:
            self.rows = [(101, 0, 0, 0)]
        elif "FROM SYS.TRIGGERS" in upper and "PARENT_CLASS=0" in upper:
            self.rows = [(0,)]
        elif "HAS_PERMS_BY_NAME" in upper:
            self.rows = [(1,)]
        elif "FROM SYS.COLUMNS C JOIN SYS.TYPES" in upper:
            names = parameters[1:]
            self.rows = [
                (
                    index + 1,
                    name,
                    "int",
                    4,
                    10,
                    0,
                    0,
                    0,
                    0,
                    0,
                    0,
                )
                for index, name in enumerate(names)
            ]
        elif upper.startswith("SELECT COUNT_BIG(*) FROM [DBO].[INVOICE_EMPLOYEES]"):
            self.rows = [(len(self.state["rows"][self.database]),)]
        elif upper.startswith("SELECT COUNT_BIG(*) FROM [DBO].[__CODEX_BAK_"):
            backup = _table_name_from_from_clause(normalized)
            self.rows = [(len(self.state["backups"][backup]),)]
        elif upper.startswith(
            "SELECT [INVOICEID],[INVOICE_EMPLOYEES_ID],[EMPLOYEEID] "
            "FROM [DBO].[INVOICE_EMPLOYEES]"
        ):
            self.rows = sorted(
                [
                    (row["InvoiceID"], row["Invoice_Employees_ID"], row["EmployeeID"])
                    for row in self.state["rows"][self.database]
                ]
            )
        elif upper.startswith("SELECT TOP (0)") and f"INTO {TEMP_TABLE.upper()}" in upper:
            self.state["temp"] = []
        elif "SP_GETAPPLOCK" in upper:
            self.rows = [(0,)]
        elif "OBJECT_ID(?,'U')" in upper:
            self.rows = [(1 if parameters[0] in self.state["backups"] else 0,)]
        elif upper.startswith("SELECT * INTO [DBO].[__CODEX_BAK_"):
            backup = _table_name_from_into_clause(normalized)
            self.state["backups"][backup] = [
                dict(row) for row in self.state["rows"][self.database]
            ]
        elif upper.startswith("UPDATE TARGET SET"):
            source = {
                (row[0], row[1]): row[2]
                for row in self.state["temp"]
            }
            affected = 0
            for row in self.state["rows"][self.database]:
                key = (row["InvoiceID"], row["Invoice_Employees_ID"])
                if key in source and row["EmployeeID"] != source[key]:
                    row["EmployeeID"] = source[key]
                    affected += 1
            self.rowcount = affected
        elif upper.startswith("SET XACT_ABORT ON"):
            pass
        else:
            raise AssertionError((normalized, parameters))
        return self

    def executemany(self, sql, rows):
        assert sql.startswith("INSERT INTO #NovaRestoreSource")
        self.state["temp"] = [tuple(row) for row in rows]
        return self

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return list(self.rows)

    def fetchmany(self, count):
        return list(self.rows[:count])


class RestoreConnection:
    autocommit = False

    def __init__(self, database, state):
        self.state = state
        self._cursor = RestoreCursor(database, state)
        self.timeout = 0

    def cursor(self):
        return self._cursor

    def commit(self):
        self.state["commits"] += 1

    def rollback(self):
        self.state["rollbacks"] += 1

    def close(self):
        pass


def _table_name_from_into_clause(sql):
    marker = "INTO [dbo].["
    start = sql.index(marker) + len(marker)
    return f"dbo.{sql[start:sql.index(']', start)]}"


def _table_name_from_from_clause(sql):
    marker = "FROM [dbo].["
    start = sql.index(marker) + len(marker)
    return f"dbo.{sql[start:sql.index(']', start)]}"


def _column(name: str) -> ColumnMetadata:
    return ColumnMetadata(
        name=name,
        type_name="int",
        max_length=4,
        precision=10,
        scale=0,
        nullable=False,
        identity=False,
        computed=False,
        generated_always_type=0,
        user_type=False,
    )


def _restore_request() -> RestoreRequest:
    return _request(
        company_username="Kento",
        schema_name="dbo",
        table_name="Invoice_Employees",
        key_columns=["InvoiceID", "Invoice_Employees_ID"],
        restore_columns=["EmployeeID"],
        idempotency_key="kento-invoice-employees-restore-v1",
    )


def _snapshot(database: str, rows, *, table_rows=None) -> TableSnapshot:
    row_tuple = tuple(tuple(row) for row in rows)
    return TableSnapshot(
        database_name=database,
        table_row_count=len(row_tuple) if table_rows is None else table_rows,
        columns=(
            _column("InvoiceID"),
            _column("Invoice_Employees_ID"),
            _column("EmployeeID"),
        ),
        rows=row_tuple,
        projection_hash=f"{database}-hash",
    )


@pytest.mark.parametrize(
    "kwargs",
    [
        {"table_name": "Invoice_Employees; DROP TABLE dbo.Users"},
        {"schema_name": "dbo.other"},
        {"key_columns": ["InvoiceID", "InvoiceID"]},
        {"key_columns": ["EmployeePassword"]},
        {"restore_columns": ["ApiToken"]},
        {"restore_columns": ["EmployeeID", "InvoiceID"]},
    ],
)
def test_request_rejects_sql_fragments_duplicates_secrets_and_key_overlap(kwargs):
    values = {
        "company_username": "Kento",
        "schema_name": "dbo",
        "table_name": "Invoice_Employees",
        "key_columns": ["InvoiceID"],
        "restore_columns": ["EmployeeID"],
        "idempotency_key": "kento-invoice-employees-restore-v1",
    }
    values.update(kwargs)
    with pytest.raises(NovaSqlTableRestoreScopeError):
        _request(**values)


def test_analysis_updates_only_shared_mismatches_and_preserves_unmatched_rows():
    request = _restore_request()
    source = _snapshot(
        request.source_database,
        [
            (100, 1, 7),
            (100, 2, 8),
            (101, 3, 9),
        ],
    )
    target = _snapshot(
        request.target_database,
        [
            (100, 1, None),
            (100, 2, 8),
            (102, 4, 10),
        ],
    )

    analysis = _analyze(request, source, target)
    plan = _plan(request, source, target, analysis)

    assert analysis == {
        "sourceTableRowCount": 3,
        "targetTableRowCount": 3,
        "sourceProjectionRowCount": 3,
        "targetProjectionRowCount": 3,
        "sharedRowCount": 2,
        "sourceOnlyRowCount": 1,
        "targetOnlyRowCount": 1,
        "candidateRowCount": 1,
        "alreadyMatchingRowCount": 1,
    }
    assert plan["sourceDatabase"] == "POS_Kento_RESTORE"
    assert plan["targetDatabase"] == "POS_Kento"
    assert plan["candidateRowCount"] == 1
    assert plan["backupTable"].startswith("dbo.__codex_bak_Invoice_Employees_")


def test_analysis_rejects_nonunique_or_null_keys():
    request = _restore_request()
    target = _snapshot(request.target_database, [(100, 1, None)])

    with pytest.raises(NovaSqlTableRestoreScopeError, match="not unique"):
        _analyze(
            request,
            _snapshot(request.source_database, [(100, 1, 7), (100, 1, 8)]),
            target,
        )
    with pytest.raises(NovaSqlTableRestoreScopeError, match="null key"):
        _analyze(
            request,
            _snapshot(request.source_database, [(100, None, 7)]),
            target,
        )


def test_generated_update_uses_only_target_and_broker_temp_table():
    sql = _update_sql(_restore_request())

    assert sql.startswith("UPDATE target SET target.[EmployeeID]=source.[EmployeeID]")
    assert "FROM [dbo].[Invoice_Employees] AS target" in sql
    assert "JOIN #NovaRestoreSource AS source" in sql
    assert "target.[InvoiceID]=source.[InvoiceID]" in sql
    assert "target.[Invoice_Employees_ID]=source.[Invoice_Employees_ID]" in sql
    assert " WHERE " in sql
    assert "_RESTORE" not in sql
    assert "DELETE" not in sql
    assert "INSERT" not in sql
    assert "MERGE" not in sql


def test_client_connection_binding_allows_only_live_and_fixed_restore_database(tmp_path):
    connection_strings = []
    client = ScopedNovaSqlClient(
        FakeSalesforce(),
        connect_factory=lambda value: connection_strings.append(value) or FakeConnection(),
        drivers_factory=lambda: ["ODBC Driver 18 for SQL Server"],
        write_enabled=True,
        write_state_dir=tmp_path,
    )

    client._connect_database("Kento", "POS_Kento", read_only=False)
    client._connect_database("Kento", "POS_Kento_RESTORE", read_only=True)

    assert "DATABASE=POS_Kento;" in connection_strings[0]
    assert "ApplicationIntent=ReadWrite;" in connection_strings[0]
    assert "DATABASE=POS_Kento_RESTORE;" in connection_strings[1]
    assert "ApplicationIntent=ReadOnly;" in connection_strings[1]
    with pytest.raises(NovaSqlScopeError):
        client._connect_database("Kento", "POS_Other", read_only=True)


def test_capabilities_report_no_sql_delete_insert_or_merge(tmp_path: Path):
    operation = NovaSqlTableRestoreOperation(
        connect_database=lambda *_args: None,
        state_dir=tmp_path,
    )

    capabilities = operation.capabilities()

    assert capabilities["callerSqlAccepted"] is False
    assert capabilities["updatesExistingRowsOnly"] is True
    assert capabilities["deleteAllowed"] is False
    assert capabilities["insertAllowed"] is False
    assert capabilities["mergeAllowed"] is False
    assert capabilities["fullTargetBackupRequired"] is True


def test_preview_execute_and_replay_restore_only_selected_columns(tmp_path):
    source_database = "POS_Kento_RESTORE"
    target_database = "POS_Kento"
    state = {
        "rows": {
            source_database: [
                {"InvoiceID": 100, "Invoice_Employees_ID": 1, "EmployeeID": 7, "Other": "source-a"},
                {"InvoiceID": 100, "Invoice_Employees_ID": 2, "EmployeeID": 8, "Other": "source-b"},
                {"InvoiceID": 101, "Invoice_Employees_ID": 3, "EmployeeID": 9, "Other": "source-only"},
            ],
            target_database: [
                {"InvoiceID": 100, "Invoice_Employees_ID": 1, "EmployeeID": None, "Other": "live-a"},
                {"InvoiceID": 100, "Invoice_Employees_ID": 2, "EmployeeID": 8, "Other": "live-b"},
                {"InvoiceID": 102, "Invoice_Employees_ID": 4, "EmployeeID": 10, "Other": "target-only"},
            ],
        },
        "backups": {},
        "temp": [],
        "commands": [],
        "commits": 0,
        "rollbacks": 0,
    }
    operation = NovaSqlTableRestoreOperation(
        connect_database=lambda _company, database, _read_only: RestoreConnection(database, state),
        state_dir=tmp_path,
    )
    inputs = {
        "company_username": "Kento",
        "schema_name": "dbo",
        "table_name": "Invoice_Employees",
        "key_columns": ["InvoiceID", "Invoice_Employees_ID"],
        "restore_columns": ["EmployeeID"],
        "idempotency_key": "kento-invoice-employees-restore-execute-v1",
    }

    preview = operation.preview(**inputs)
    result = operation.execute(
        **inputs,
        preview_hash=preview["plan"]["planHash"],
    )
    replay = operation.execute(
        **inputs,
        preview_hash=preview["plan"]["planHash"],
    )

    assert preview["analysis"]["candidateRowCount"] == 1
    assert preview["analysis"]["sourceOnlyRowCount"] == 1
    assert preview["analysis"]["targetOnlyRowCount"] == 1
    assert result["status"] == "completed"
    assert result["affectedRows"] == 1
    assert result["remainingMismatches"] == 0
    assert result["transactionCommitted"] is True
    assert result["postCommitReadbackVerified"] is True
    assert replay["idempotentReplay"] is True
    assert state["commits"] == 1
    assert len(state["backups"]) == 1
    assert len(next(iter(state["backups"].values()))) == 3
    assert state["rows"][target_database] == [
        {"InvoiceID": 100, "Invoice_Employees_ID": 1, "EmployeeID": 7, "Other": "live-a"},
        {"InvoiceID": 100, "Invoice_Employees_ID": 2, "EmployeeID": 8, "Other": "live-b"},
        {"InvoiceID": 102, "Invoice_Employees_ID": 4, "EmployeeID": 10, "Other": "target-only"},
    ]
