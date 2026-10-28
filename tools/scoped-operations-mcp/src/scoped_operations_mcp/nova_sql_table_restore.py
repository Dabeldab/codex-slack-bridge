from __future__ import annotations

import hashlib
import json
import os
import re
from contextlib import closing
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable


IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_$#@]{0,127}$")
IDEMPOTENCY_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{7,199}$")
PROTECTED_COLUMN = re.compile(
    r"(?:password|passcode|secret|securitykey|api_?key|token|authorization|cookie|"
    r"deviceconfig|merchantnumber|merchanttransid|merchantloginid|employee_ssn)",
    re.IGNORECASE,
)
MAX_KEY_COLUMNS = 8
MAX_RESTORE_COLUMNS = 16
MAX_SNAPSHOT_ROWS = 250_000
MAX_AFFECTED_ROWS = 10_000
TEMP_TABLE = "#NovaRestoreSource"
OPERATION = "nova_sql_table_restore_v1"


class NovaSqlTableRestoreScopeError(ValueError):
    """The requested restore exceeds the fixed table-recovery boundary."""


class NovaSqlTableRestoreUnavailableError(RuntimeError):
    """The fixed table-recovery dependency or readback is unavailable."""


@dataclass(frozen=True)
class RestoreRequest:
    company_username: str
    schema_name: str
    table_name: str
    key_columns: tuple[str, ...]
    restore_columns: tuple[str, ...]
    idempotency_key: str

    @property
    def target_database(self) -> str:
        return f"POS_{self.company_username}"

    @property
    def source_database(self) -> str:
        return f"POS_{self.company_username}_RESTORE"

    @property
    def qualified_table(self) -> str:
        return f"{self.schema_name}.{self.table_name}"


@dataclass(frozen=True)
class ColumnMetadata:
    name: str
    type_name: str
    max_length: int
    precision: int
    scale: int
    nullable: bool
    identity: bool
    computed: bool
    generated_always_type: int
    user_type: bool

    def signature(self) -> tuple[Any, ...]:
        return (
            self.name.casefold(),
            self.type_name.casefold(),
            self.max_length,
            self.precision,
            self.scale,
            self.nullable,
            self.identity,
            self.computed,
            self.generated_always_type,
            self.user_type,
        )


@dataclass(frozen=True)
class TableSnapshot:
    database_name: str
    table_row_count: int
    columns: tuple[ColumnMetadata, ...]
    rows: tuple[tuple[Any, ...], ...]
    projection_hash: str


class NovaSqlTableRestoreOperation:
    """Restore selected columns from POS_<company>_RESTORE into the live table.

    This operation exposes identifiers and column lists, never SQL. It updates
    only existing rows with an exact unique-key match, creates a complete copy
    of the live target before the update, and performs no INSERT/DELETE/MERGE.
    """

    def __init__(
        self,
        *,
        connect_database: Callable[[str, str, bool], Any],
        state_dir: str | Path,
        query_timeout_seconds: int = 120,
    ) -> None:
        self._connect_database = connect_database
        self._state_dir = Path(state_dir).expanduser().resolve() / "table-restore"
        self._query_timeout_seconds = max(30, int(query_timeout_seconds))

    def capabilities(self) -> dict[str, Any]:
        return {
            "configured": True,
            "operation": OPERATION,
            "sourceDatabaseConvention": "POS_<company_username>_RESTORE",
            "targetDatabaseConvention": "POS_<company_username>",
            "updatesExistingRowsOnly": True,
            "callerSqlAccepted": False,
            "deleteAllowed": False,
            "insertAllowed": False,
            "mergeAllowed": False,
            "fullTargetBackupRequired": True,
            "previewHashRequired": True,
            "uniqueKeyRequired": True,
            "maximumKeyColumns": MAX_KEY_COLUMNS,
            "maximumRestoreColumns": MAX_RESTORE_COLUMNS,
            "maximumSnapshotRowsPerTable": MAX_SNAPSHOT_ROWS,
            "maximumAffectedRows": MAX_AFFECTED_ROWS,
        }

    def preview(
        self,
        *,
        company_username: str,
        schema_name: str,
        table_name: str,
        key_columns: list[str],
        restore_columns: list[str],
        idempotency_key: str,
    ) -> dict[str, Any]:
        request = _request(
            company_username=company_username,
            schema_name=schema_name,
            table_name=table_name,
            key_columns=key_columns,
            restore_columns=restore_columns,
            idempotency_key=idempotency_key,
        )
        source = self._snapshot(request, source=True, read_only=True)
        target = self._snapshot(request, source=False, read_only=True)
        analysis = _analyze(request, source, target)
        plan = _plan(request, source, target, analysis)
        return _preview_result(request, source, target, analysis, plan)

    def execute(
        self,
        *,
        company_username: str,
        schema_name: str,
        table_name: str,
        key_columns: list[str],
        restore_columns: list[str],
        idempotency_key: str,
        preview_hash: str,
    ) -> dict[str, Any]:
        request = _request(
            company_username=company_username,
            schema_name=schema_name,
            table_name=table_name,
            key_columns=key_columns,
            restore_columns=restore_columns,
            idempotency_key=idempotency_key,
        )
        clean_hash = str(preview_hash or "").strip().lower()
        if not re.fullmatch(r"[0-9a-f]{64}", clean_hash):
            raise NovaSqlTableRestoreScopeError(
                "preview_hash must be the exact SHA-256 returned by the preview"
            )

        receipt_path = _receipt_path(self._state_dir, request.idempotency_key)
        existing = _read_receipt(receipt_path)
        if existing:
            return self._replay(request, clean_hash, existing)

        preview = self.preview(
            company_username=request.company_username,
            schema_name=request.schema_name,
            table_name=request.table_name,
            key_columns=list(request.key_columns),
            restore_columns=list(request.restore_columns),
            idempotency_key=request.idempotency_key,
        )
        plan = dict(preview["plan"])
        if str(plan["planHash"]) != clean_hash:
            raise NovaSqlTableRestoreScopeError(
                "restore source or live target changed after preview"
            )
        expected_affected = int(plan["candidateRowCount"])
        if expected_affected == 0:
            return {
                **preview,
                "status": "already_aligned",
                "transactionCommitted": False,
                "postCommitReadbackVerified": True,
                "idempotentReplay": False,
            }

        pending = {
            "version": 1,
            "status": "pending",
            "operation": OPERATION,
            "idempotencyKey": request.idempotency_key,
            "planHash": clean_hash,
            "companyUsername": request.company_username,
            "targetDatabase": request.target_database,
            "sourceDatabase": request.source_database,
            "table": request.qualified_table,
            "keyColumns": list(request.key_columns),
            "restoreColumns": list(request.restore_columns),
            "expectedAffectedRows": expected_affected,
            "backupTable": plan["backupTable"],
            "createdAtUtc": datetime.now(timezone.utc).isoformat(),
        }
        _write_receipt(receipt_path, pending)

        source = self._snapshot(request, source=True, read_only=True)
        if source.projection_hash != str(plan["sourceProjectionHash"]):
            raise NovaSqlTableRestoreScopeError(
                "restore source changed before execution; do not reuse this preview"
            )

        committed = False
        affected_rows = 0
        post_commit_hash = ""
        with closing(
            self._connect_database(
                request.company_username,
                request.target_database,
                False,
            )
        ) as connection:
            connection.timeout = self._query_timeout_seconds
            cursor = connection.cursor()
            try:
                cursor.execute("SET XACT_ABORT ON")
                target_metadata = _inspect_table(
                    cursor,
                    request,
                    expected_database=request.target_database,
                    target=True,
                )
                _require_compatible_columns(request, source.columns, target_metadata["columns"])
                _stage_source(cursor, request, source)
                _acquire_lock(cursor, request)
                target = _snapshot_from_cursor(
                    cursor,
                    request,
                    expected_database=request.target_database,
                    target=True,
                    lock_target=True,
                    metadata=target_metadata,
                )
                analysis = _analyze(request, source, target)
                locked_plan = _plan(request, source, target, analysis)
                if locked_plan["planHash"] != clean_hash:
                    raise NovaSqlTableRestoreScopeError(
                        "restore source or live target changed before the locked write"
                    )
                if analysis["candidateRowCount"] != expected_affected:
                    raise NovaSqlTableRestoreScopeError(
                        "locked affected-row count differs from the approved preview"
                    )

                backup_table = str(locked_plan["backupTable"])
                if _table_exists(cursor, backup_table):
                    raise NovaSqlTableRestoreUnavailableError(
                        "deterministic target backup already exists without a completed receipt"
                    )
                _create_and_verify_backup(
                    cursor,
                    request,
                    backup_table=backup_table,
                    expected_rows=target.table_row_count,
                )

                cursor.execute(_update_sql(request))
                affected_rows = int(getattr(cursor, "rowcount", -1))
                if affected_rows != expected_affected:
                    raise NovaSqlTableRestoreUnavailableError(
                        "affected-row count did not match the locked preview"
                    )

                target_after = _snapshot_from_cursor(
                    cursor,
                    request,
                    expected_database=request.target_database,
                    target=True,
                    lock_target=False,
                    metadata=target_metadata,
                )
                after_analysis = _analyze(request, source, target_after)
                if after_analysis["candidateRowCount"] != 0:
                    raise NovaSqlTableRestoreUnavailableError(
                        "pre-commit restore-column readback did not match the source"
                    )
                if target_after.table_row_count != target.table_row_count:
                    raise NovaSqlTableRestoreUnavailableError(
                        "live target row count changed during recovery"
                    )
                post_commit_hash = target_after.projection_hash
                connection.commit()
                committed = True
            except Exception:
                if not committed:
                    try:
                        connection.rollback()
                    except Exception:
                        pass
                raise

        source_readback = self._snapshot(request, source=True, read_only=True)
        target_readback = self._snapshot(request, source=False, read_only=True)
        final_analysis = _analyze(request, source_readback, target_readback)
        if (
            final_analysis["candidateRowCount"] != 0
            or target_readback.projection_hash != post_commit_hash
        ):
            receipt = {
                **pending,
                "status": "committed_readback_failed",
                "affectedRows": affected_rows,
                "completedAtUtc": datetime.now(timezone.utc).isoformat(),
            }
            _write_receipt(receipt_path, receipt)
            raise NovaSqlTableRestoreUnavailableError(
                "table recovery committed but final readback failed; do not retry"
            )

        receipt = {
            **pending,
            "status": "completed",
            "affectedRows": affected_rows,
            "sourceRows": source_readback.table_row_count,
            "targetRows": target_readback.table_row_count,
            "remainingMismatches": final_analysis["candidateRowCount"],
            "sourceOnlyRowsPreserved": final_analysis["sourceOnlyRowCount"],
            "targetOnlyRowsPreserved": final_analysis["targetOnlyRowCount"],
            "transactionCommitted": True,
            "postCommitReadbackVerified": True,
            "completedAtUtc": datetime.now(timezone.utc).isoformat(),
        }
        _write_receipt(receipt_path, receipt)
        return {**receipt, "idempotentReplay": False}

    def _snapshot(
        self,
        request: RestoreRequest,
        *,
        source: bool,
        read_only: bool,
    ) -> TableSnapshot:
        database = request.source_database if source else request.target_database
        with closing(
            self._connect_database(request.company_username, database, read_only)
        ) as connection:
            connection.timeout = self._query_timeout_seconds
            cursor = connection.cursor()
            metadata = _inspect_table(
                cursor,
                request,
                expected_database=database,
                target=not source,
            )
            return _snapshot_from_cursor(
                cursor,
                request,
                expected_database=database,
                target=not source,
                lock_target=False,
                metadata=metadata,
            )

    def _replay(
        self,
        request: RestoreRequest,
        preview_hash: str,
        receipt: dict[str, Any],
    ) -> dict[str, Any]:
        if (
            receipt.get("status") != "completed"
            or receipt.get("planHash") != preview_hash
            or receipt.get("companyUsername") != request.company_username
            or receipt.get("table") != request.qualified_table
            or tuple(receipt.get("keyColumns") or ()) != request.key_columns
            or tuple(receipt.get("restoreColumns") or ()) != request.restore_columns
        ):
            raise NovaSqlTableRestoreUnavailableError(
                "an incomplete or mismatched recovery receipt exists; do not retry"
            )
        source = self._snapshot(request, source=True, read_only=True)
        target = self._snapshot(request, source=False, read_only=True)
        analysis = _analyze(request, source, target)
        if analysis["candidateRowCount"] != 0:
            raise NovaSqlTableRestoreUnavailableError(
                "completed receipt exists but live readback no longer matches the restore source"
            )
        return {
            **receipt,
            "idempotentReplay": True,
            "postCommitReadbackVerified": True,
        }


def _request(
    *,
    company_username: str,
    schema_name: str,
    table_name: str,
    key_columns: list[str],
    restore_columns: list[str],
    idempotency_key: str,
) -> RestoreRequest:
    company = str(company_username or "").strip()
    if company.lower().startswith("pos_"):
        company = company[4:]
    if not IDENTIFIER.fullmatch(company):
        raise NovaSqlTableRestoreScopeError(
            "company_username must be one exact Nova company username"
        )
    schema = _identifier(schema_name, "schema_name")
    table = _identifier(table_name, "table_name")
    keys = _column_list(key_columns, "key_columns", MAX_KEY_COLUMNS)
    restore = _column_list(
        restore_columns,
        "restore_columns",
        MAX_RESTORE_COLUMNS,
    )
    overlap = {value.casefold() for value in keys} & {
        value.casefold() for value in restore
    }
    if overlap:
        raise NovaSqlTableRestoreScopeError(
            "key_columns and restore_columns must be disjoint"
        )
    if any(PROTECTED_COLUMN.search(value) for value in (*keys, *restore)):
        raise NovaSqlTableRestoreScopeError(
            "protected credential or secret columns cannot be used for table recovery"
        )
    key = str(idempotency_key or "").strip()
    if not IDEMPOTENCY_KEY.fullmatch(key):
        raise NovaSqlTableRestoreScopeError(
            "idempotency_key must be a stable 8-200 character operation identifier"
        )
    return RestoreRequest(
        company_username=company,
        schema_name=schema,
        table_name=table,
        key_columns=keys,
        restore_columns=restore,
        idempotency_key=key,
    )


def _identifier(value: Any, label: str) -> str:
    clean = str(value or "").strip()
    if not IDENTIFIER.fullmatch(clean):
        raise NovaSqlTableRestoreScopeError(
            f"{label} must be one unqualified SQL identifier"
        )
    return clean


def _column_list(values: Any, label: str, maximum: int) -> tuple[str, ...]:
    if not isinstance(values, list) or not 1 <= len(values) <= maximum:
        raise NovaSqlTableRestoreScopeError(
            f"{label} must contain between 1 and {maximum} identifiers"
        )
    clean = tuple(_identifier(value, label) for value in values)
    if len({value.casefold() for value in clean}) != len(clean):
        raise NovaSqlTableRestoreScopeError(f"{label} contains a duplicate identifier")
    return clean


def _quoted(value: str) -> str:
    if not IDENTIFIER.fullmatch(value):
        raise NovaSqlTableRestoreScopeError("SQL identifier is invalid")
    return f"[{value}]"


def _qualified(request: RestoreRequest) -> str:
    return f"{_quoted(request.schema_name)}.{_quoted(request.table_name)}"


def _inspect_table(
    cursor: Any,
    request: RestoreRequest,
    *,
    expected_database: str,
    target: bool,
) -> dict[str, Any]:
    binding = cursor.execute("SELECT DB_NAME()").fetchone()
    actual = str(binding[0] or "") if binding else ""
    if actual.casefold() != expected_database.casefold():
        raise NovaSqlTableRestoreUnavailableError(
            "table recovery connected to an unexpected database"
        )

    metadata = cursor.execute(
        "SELECT t.object_id,t.temporal_type,"
        "(SELECT COUNT_BIG(*) FROM sys.triggers tr "
        " WHERE tr.parent_id=t.object_id AND tr.is_disabled=0),"
        "(SELECT COUNT_BIG(*) FROM sys.foreign_keys fk "
        " WHERE fk.referenced_object_id=t.object_id "
        " AND fk.is_disabled=0 AND fk.update_referential_action<>0) "
        "FROM sys.tables t JOIN sys.schemas s ON s.schema_id=t.schema_id "
        "WHERE s.name=? AND t.name=?",
        [request.schema_name, request.table_name],
    ).fetchone()
    if not metadata:
        raise NovaSqlTableRestoreScopeError(
            f"{request.qualified_table} is not an accessible base table"
        )
    object_id = int(metadata[0])
    if target:
        if int(metadata[1] or 0):
            raise NovaSqlTableRestoreScopeError(
                "temporal targets are unavailable because recovery may change a history table"
            )
        if int(metadata[2] or 0):
            raise NovaSqlTableRestoreScopeError(
                "targets with enabled DML triggers are unavailable"
            )
        if int(metadata[3] or 0):
            raise NovaSqlTableRestoreScopeError(
                "targets with cascading updates are unavailable"
            )
        ddl = cursor.execute(
            "SELECT COUNT_BIG(*) FROM sys.triggers "
            "WHERE parent_class=0 AND is_disabled=0"
        ).fetchone()
        if ddl and int(ddl[0] or 0):
            raise NovaSqlTableRestoreScopeError(
                "the target database has an enabled DDL trigger"
            )
        _require_target_permissions(cursor, request)

    requested = (*request.key_columns, *request.restore_columns)
    placeholders = ",".join("?" for _ in requested)
    cursor.execute(
        "SELECT c.column_id,c.name,LOWER(ty.name),c.max_length,c.precision,c.scale,"
        "c.is_nullable,c.is_identity,c.is_computed,c.generated_always_type,"
        "CASE WHEN c.user_type_id=c.system_type_id THEN 0 ELSE 1 END "
        "FROM sys.columns c JOIN sys.types ty ON ty.user_type_id=c.user_type_id "
        f"WHERE c.object_id=? AND c.name IN ({placeholders}) ORDER BY c.column_id",
        [object_id, *requested],
    )
    columns = tuple(
        ColumnMetadata(
            name=str(row[1]),
            type_name=str(row[2]),
            max_length=int(row[3]),
            precision=int(row[4]),
            scale=int(row[5]),
            nullable=bool(row[6]),
            identity=bool(row[7]),
            computed=bool(row[8]),
            generated_always_type=int(row[9] or 0),
            user_type=bool(row[10]),
        )
        for row in cursor.fetchall()
    )
    by_name = {column.name.casefold(): column for column in columns}
    missing = [name for name in requested if name.casefold() not in by_name]
    if missing:
        raise NovaSqlTableRestoreScopeError(
            f"requested columns are missing: {', '.join(missing)}"
        )
    ordered = tuple(by_name[name.casefold()] for name in requested)
    restore_names = {name.casefold() for name in request.restore_columns}
    for column in ordered:
        if column.name.casefold() not in restore_names:
            continue
        if (
            column.identity
            or column.computed
            or column.generated_always_type
            or column.type_name.casefold() in {"timestamp", "rowversion"}
            or column.user_type
        ):
            raise NovaSqlTableRestoreScopeError(
                f"restore column {column.name} is not directly updateable"
            )
    return {"objectId": object_id, "columns": ordered}


def _require_target_permissions(cursor: Any, request: RestoreRequest) -> None:
    checks = (
        (
            "CREATE TABLE",
            "SELECT HAS_PERMS_BY_NAME(DB_NAME(),'DATABASE','CREATE TABLE')",
            [],
        ),
        (
            f"ALTER on schema {request.schema_name}",
            "SELECT HAS_PERMS_BY_NAME(?,'SCHEMA','ALTER')",
            [request.schema_name],
        ),
        (
            f"SELECT on {request.qualified_table}",
            "SELECT HAS_PERMS_BY_NAME(?,'OBJECT','SELECT')",
            [request.qualified_table],
        ),
        (
            f"UPDATE on {request.qualified_table}",
            "SELECT HAS_PERMS_BY_NAME(?,'OBJECT','UPDATE')",
            [request.qualified_table],
        ),
    )
    for label, sql, parameters in checks:
        row = cursor.execute(sql, parameters).fetchone()
        if not row or int(row[0] or 0) != 1:
            raise NovaSqlTableRestoreScopeError(f"Nova login lacks required {label}")


def _snapshot_from_cursor(
    cursor: Any,
    request: RestoreRequest,
    *,
    expected_database: str,
    target: bool,
    lock_target: bool,
    metadata: dict[str, Any],
) -> TableSnapshot:
    binding = cursor.execute("SELECT DB_NAME()").fetchone()
    actual = str(binding[0] or "") if binding else ""
    if actual.casefold() != expected_database.casefold():
        raise NovaSqlTableRestoreUnavailableError(
            "table snapshot connected to an unexpected database"
        )
    table_sql = _qualified(request)
    row_count_row = cursor.execute(
        f"SELECT COUNT_BIG(*) FROM {table_sql}"
    ).fetchone()
    table_row_count = int(row_count_row[0] or 0) if row_count_row else 0
    if table_row_count > MAX_SNAPSHOT_ROWS:
        raise NovaSqlTableRestoreScopeError(
            f"table recovery snapshot exceeds {MAX_SNAPSHOT_ROWS} rows"
        )

    projection = (*request.key_columns, *request.restore_columns)
    columns_sql = ",".join(_quoted(column) for column in projection)
    order_sql = ",".join(_quoted(column) for column in request.key_columns)
    lock_sql = " WITH (HOLDLOCK,TABLOCKX)" if lock_target and target else ""
    cursor.execute(
        f"SELECT {columns_sql} FROM {table_sql}{lock_sql} ORDER BY {order_sql}"
    )
    rows = tuple(tuple(row) for row in cursor.fetchmany(MAX_SNAPSHOT_ROWS + 1))
    if len(rows) > MAX_SNAPSHOT_ROWS:
        raise NovaSqlTableRestoreScopeError(
            f"table recovery snapshot exceeds {MAX_SNAPSHOT_ROWS} rows"
        )
    return TableSnapshot(
        database_name=actual,
        table_row_count=table_row_count,
        columns=tuple(metadata["columns"]),
        rows=rows,
        projection_hash=_projection_hash(rows),
    )


def _projection_hash(rows: tuple[tuple[Any, ...], ...]) -> str:
    payload = [[_canonical(value) for value in row] for row in rows]
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _canonical(value: Any) -> Any:
    if isinstance(value, Decimal):
        return {"type": "decimal", "value": str(value)}
    if isinstance(value, datetime):
        return {"type": "datetime", "value": value.isoformat()}
    if isinstance(value, date):
        return {"type": "date", "value": value.isoformat()}
    if isinstance(value, bytes):
        return {"type": "bytes", "value": value.hex()}
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    return {"type": type(value).__name__, "value": str(value)}


def _require_compatible_columns(
    request: RestoreRequest,
    source: tuple[ColumnMetadata, ...],
    target: tuple[ColumnMetadata, ...],
) -> None:
    if len(source) != len(target):
        raise NovaSqlTableRestoreScopeError("source and target column sets differ")
    for source_column, target_column in zip(source, target, strict=True):
        if source_column.signature() != target_column.signature():
            raise NovaSqlTableRestoreScopeError(
                f"source and target metadata differ for {source_column.name}"
            )
    expected = tuple(
        name.casefold()
        for name in (*request.key_columns, *request.restore_columns)
    )
    actual = tuple(column.name.casefold() for column in source)
    if actual != expected:
        raise NovaSqlTableRestoreScopeError(
            "source and target columns did not preserve the requested order"
        )


def _analyze(
    request: RestoreRequest,
    source: TableSnapshot,
    target: TableSnapshot,
) -> dict[str, Any]:
    _require_compatible_columns(request, source.columns, target.columns)
    key_count = len(request.key_columns)
    source_map = _row_map(source.rows, key_count, "restore source")
    target_map = _row_map(target.rows, key_count, "live target")
    source_keys = set(source_map)
    target_keys = set(target_map)
    shared = source_keys & target_keys
    candidates = [
        key
        for key in shared
        if target_map[key][key_count:] != source_map[key][key_count:]
    ]
    if len(candidates) > MAX_AFFECTED_ROWS:
        raise NovaSqlTableRestoreScopeError(
            f"table recovery would exceed {MAX_AFFECTED_ROWS} affected rows"
        )
    return {
        "sourceTableRowCount": source.table_row_count,
        "targetTableRowCount": target.table_row_count,
        "sourceProjectionRowCount": len(source.rows),
        "targetProjectionRowCount": len(target.rows),
        "sharedRowCount": len(shared),
        "sourceOnlyRowCount": len(source_keys - target_keys),
        "targetOnlyRowCount": len(target_keys - source_keys),
        "candidateRowCount": len(candidates),
        "alreadyMatchingRowCount": len(shared) - len(candidates),
    }


def _row_map(
    rows: tuple[tuple[Any, ...], ...],
    key_count: int,
    label: str,
) -> dict[tuple[Any, ...], tuple[Any, ...]]:
    result: dict[tuple[Any, ...], tuple[Any, ...]] = {}
    for row in rows:
        key = tuple(row[:key_count])
        if any(value is None for value in key):
            raise NovaSqlTableRestoreScopeError(f"{label} contains a null key value")
        if key in result:
            raise NovaSqlTableRestoreScopeError(
                f"{label} key columns are not unique"
            )
        result[key] = row
    return result


def _plan(
    request: RestoreRequest,
    source: TableSnapshot,
    target: TableSnapshot,
    analysis: dict[str, Any],
) -> dict[str, Any]:
    immutable = {
        "version": 1,
        "operation": OPERATION,
        "companyUsername": request.company_username,
        "targetDatabase": request.target_database,
        "sourceDatabase": request.source_database,
        "table": request.qualified_table,
        "keyColumns": list(request.key_columns),
        "restoreColumns": list(request.restore_columns),
        "sourceProjectionHash": source.projection_hash,
        "targetProjectionHash": target.projection_hash,
        "sourceTableRowCount": analysis["sourceTableRowCount"],
        "targetTableRowCount": analysis["targetTableRowCount"],
        "sharedRowCount": analysis["sharedRowCount"],
        "sourceOnlyRowCount": analysis["sourceOnlyRowCount"],
        "targetOnlyRowCount": analysis["targetOnlyRowCount"],
        "candidateRowCount": analysis["candidateRowCount"],
        "idempotencyKey": request.idempotency_key,
    }
    plan_hash = hashlib.sha256(
        json.dumps(immutable, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    backup_base = f"__codex_bak_{request.table_name[:80]}_{plan_hash[:12]}"
    return {
        **immutable,
        "planHash": plan_hash,
        "backupTable": f"{request.schema_name}.{backup_base}",
    }


def _preview_result(
    request: RestoreRequest,
    source: TableSnapshot,
    target: TableSnapshot,
    analysis: dict[str, Any],
    plan: dict[str, Any],
) -> dict[str, Any]:
    return {
        "ok": True,
        "status": "preview",
        "accessMode": "fixed_table_restore_preview",
        "writesPerformed": False,
        "companyUsername": request.company_username,
        "targetDatabase": request.target_database,
        "sourceDatabase": request.source_database,
        "sourceDatabaseResolvedInternally": True,
        "table": request.qualified_table,
        "keyColumns": list(request.key_columns),
        "restoreColumns": list(request.restore_columns),
        "analysis": analysis,
        "plan": plan,
        "sourceCredentialExposed": False,
        "callerSqlAccepted": False,
        "existingBusinessTablesAffected": (
            [request.qualified_table] if analysis["candidateRowCount"] else []
        ),
        "fullTargetBackupRequired": bool(analysis["candidateRowCount"]),
        "sourceProjectionHash": source.projection_hash,
        "targetProjectionHash": target.projection_hash,
    }


def _stage_source(
    cursor: Any,
    request: RestoreRequest,
    source: TableSnapshot,
) -> None:
    projection = (*request.key_columns, *request.restore_columns)
    columns_sql = ",".join(_quoted(column) for column in projection)
    target_sql = _qualified(request)
    cursor.execute(
        f"SELECT TOP (0) {columns_sql} INTO {TEMP_TABLE} "
        f"FROM {target_sql} AS seed "
        "CROSS JOIN (SELECT 1 AS identity_strip) AS identity_strip"
    )
    placeholders = ",".join("?" for _ in projection)
    insert_sql = f"INSERT INTO {TEMP_TABLE} ({columns_sql}) VALUES ({placeholders})"
    if hasattr(cursor, "fast_executemany"):
        cursor.fast_executemany = True
    cursor.executemany(insert_sql, list(source.rows))


def _acquire_lock(cursor: Any, request: RestoreRequest) -> None:
    resource = f"NovaSqlTableRestore:{request.target_database}:{request.qualified_table}"[:240]
    row = cursor.execute(
        "DECLARE @result int; "
        "EXEC @result=sys.sp_getapplock @Resource=?,@LockMode='Exclusive',"
        "@LockOwner='Transaction',@LockTimeout=30000; SELECT @result",
        [resource],
    ).fetchone()
    result = int(row[0]) if row and row[0] is not None else -999
    if result < 0:
        raise NovaSqlTableRestoreUnavailableError(
            "another guarded table recovery currently holds the target lock"
        )


def _update_sql(request: RestoreRequest) -> str:
    target_sql = _qualified(request)
    assignments = ",".join(
        f"target.{_quoted(column)}=source.{_quoted(column)}"
        for column in request.restore_columns
    )
    joins = " AND ".join(
        f"target.{_quoted(column)}=source.{_quoted(column)}"
        for column in request.key_columns
    )
    differences = " OR ".join(
        "("
        f"target.{_quoted(column)}<>source.{_quoted(column)} "
        f"OR (target.{_quoted(column)} IS NULL AND source.{_quoted(column)} IS NOT NULL) "
        f"OR (target.{_quoted(column)} IS NOT NULL AND source.{_quoted(column)} IS NULL)"
        ")"
        for column in request.restore_columns
    )
    return (
        f"UPDATE target SET {assignments} FROM {target_sql} AS target "
        f"JOIN {TEMP_TABLE} AS source ON {joins} WHERE {differences}"
    )


def _table_exists(cursor: Any, qualified_table: str) -> bool:
    row = cursor.execute(
        "SELECT CASE WHEN OBJECT_ID(?,'U') IS NULL THEN 0 ELSE 1 END",
        [qualified_table],
    ).fetchone()
    return bool(row and int(row[0] or 0))


def _create_and_verify_backup(
    cursor: Any,
    request: RestoreRequest,
    *,
    backup_table: str,
    expected_rows: int,
) -> None:
    schema, table = backup_table.split(".", 1)
    backup_sql = f"{_quoted(schema)}.{_quoted(table)}"
    target_sql = _qualified(request)
    cursor.execute(
        f"SELECT * INTO {backup_sql} FROM {target_sql} WITH (HOLDLOCK,TABLOCKX)"
    )
    row = cursor.execute(f"SELECT COUNT_BIG(*) FROM {backup_sql}").fetchone()
    actual = int(row[0] or 0) if row else -1
    if actual != expected_rows:
        raise NovaSqlTableRestoreUnavailableError(
            "complete target backup row-count verification failed"
        )


def _receipt_path(state_dir: Path, idempotency_key: str) -> Path:
    state_dir.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()
    return state_dir / f"{digest}.json"


def _read_receipt(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise NovaSqlTableRestoreUnavailableError(
            "table recovery receipt is unreadable; do not retry"
        ) from exc
    if not isinstance(value, dict):
        raise NovaSqlTableRestoreUnavailableError(
            "table recovery receipt is invalid; do not retry"
        )
    return value


def _write_receipt(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_suffix(".tmp")
    try:
        temporary.write_text(
            json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=True),
            encoding="utf-8",
        )
        os.replace(temporary, path)
    except Exception as exc:
        raise NovaSqlTableRestoreUnavailableError(
            "table recovery receipt could not be persisted"
        ) from exc
