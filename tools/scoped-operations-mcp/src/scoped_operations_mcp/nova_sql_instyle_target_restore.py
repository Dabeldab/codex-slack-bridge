from __future__ import annotations

# AgentChat/coding_agent 2026-07-28T04:19:17Z: target-scoped protected
# backup/reset/rollback implementation for the fixed Instyle demo rebuild.

import base64
import hashlib
import json
import os
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

from .nova_sql_instyle_demo_rebuild import (
    MAX_BATCH_ROWS,
    OPERATION_NAME,
    TARGET_DATABASE,
    TARGET_USERNAME,
    DatabaseSnapshot,
    InstyleDemoRebuildScopeError,
    InstyleDemoRebuildUnavailableError,
    _canonical_row_json,
    _canonical_value,
    _capture_schema,
    _capture_snapshot,
    _dependency_order,
    _has_row_key,
    _quote_identifier,
    _quote_table,
    _read_json_required,
    _row_value,
    _set_timeout,
    _sha256_json,
    _verify_database_binding,
    _write_json_atomic,
)


CONTRACT_VERSION = "target-scoped-complete-backup-v2"
BACKUP_VERSION = 2
PROTECTED_BACKUP_QUERY_TIMEOUT_SECONDS = 3_600


class TargetScopedProtectedDemoRestoreGateway:
    """Protect the fixed demo reset with a complete private row backup.

    The gateway receives only the target-scoped tenant connection already
    resolved by the broker. It never opens another database connection and
    accepts no caller-selected account, database, table, or SQL.
    """

    def __init__(
        self,
        state_dir: str | Path,
        *,
        query_timeout_seconds: int = 900,
    ) -> None:
        self._backup_dir = (
            Path(state_dir).expanduser().resolve()
            / OPERATION_NAME
            / "protected-backups"
        )
        # A target-scoped SELECT INTO for the 30M-row InventoryHistoryItem table
        # is a fixed part of this operation. Never inherit the generic 30-second
        # bounded-read timeout for that protected backup copy.
        self._query_timeout_seconds = max(
            PROTECTED_BACKUP_QUERY_TIMEOUT_SECONDS,
            min(int(query_timeout_seconds), PROTECTED_BACKUP_QUERY_TIMEOUT_SECONDS),
        )

    def capability_status(self, *, target_database: str) -> dict[str, Any]:
        _fixed_target(target_database)
        return {
            "ok": True,
            "contractVersion": CONTRACT_VERSION,
            "completeBackup": True,
            "backupReadback": True,
            "protectedReset": True,
            "rollback": True,
            "applicationLock": True,
            "separateAccountConnections": True,
            "noCrossDatabaseTenantRights": True,
            "backupStorage": "target_scoped_internal_tables_with_private_receipt",
            "directOperations": ["fixed_target_row_clear"],
        }

    def create_complete_backup(
        self,
        connection: Any,
        *,
        target_database: str,
        idempotency_key: str,
        plan_hash: str,
        expected_snapshot_hash: str,
        required_tables: list[str],
    ) -> dict[str, Any]:
        _fixed_target(target_database)
        snapshot = _capture_snapshot(
            connection,
            TARGET_USERNAME,
            TARGET_DATABASE,
            include_rows=False,
            query_timeout_seconds=self._query_timeout_seconds,
            manage_transaction=False,
        )
        if snapshot.snapshot_hash != expected_snapshot_hash:
            raise InstyleDemoRebuildScopeError(
                "target changed before the protected complete backup"
            )
        required = _resolve_required_tables(snapshot, required_tables)
        receipt_id = hashlib.sha256(
            f"{idempotency_key}:{plan_hash}:{snapshot.snapshot_hash}".encode("utf-8")
        ).hexdigest()
        target_backups: dict[str, str] = {}
        cursor = connection.cursor()
        for table_key in sorted(snapshot.tables, key=str.casefold):
            backup_table = _backup_table_identifier(table_key, receipt_id)
            exists = _table_exists(cursor, backup_table)
            if not exists:
                try:
                    cursor.execute(
                        f"SELECT * INTO {_quote_table(backup_table)} "
                        f"FROM {_quote_table(table_key)} WITH (HOLDLOCK,TABLOCKX)"
                    )
                    connection.commit()
                except Exception as exc:
                    try:
                        connection.rollback()
                    except Exception:
                        pass
                    raise InstyleDemoRebuildUnavailableError(
                        "protected complete backup copy failed for fixed target "
                        f"table {table_key}; target reset did not start and retry "
                        "reuses every completed backup table"
                    ) from exc
            source_count = _table_count(cursor, table_key)
            backup_count = _table_count(cursor, backup_table)
            if (
                source_count != int(snapshot.row_counts.get(table_key, -1))
                or backup_count != source_count
            ):
                raise InstyleDemoRebuildUnavailableError(
                    "streamed target backup row-count verification failed"
                )
            target_backups[table_key] = backup_table
        payload = _backup_payload(snapshot, required, target_backups)
        document = {
            "version": BACKUP_VERSION,
            "operation": OPERATION_NAME,
            "receiptId": receipt_id,
            "payloadHash": _sha256_json(payload),
            "payload": payload,
        }
        path = self._backup_path(receipt_id)
        _write_json_atomic(path, document)
        verified = self._read_verified_backup(
            connection,
            receipt_id,
            expected_snapshot_hash=expected_snapshot_hash,
        )
        if verified["payloadHash"] != document["payloadHash"]:
            raise InstyleDemoRebuildUnavailableError(
                "protected complete backup readback changed after persistence"
            )
        return {
            "ok": True,
            "complete": True,
            "readbackVerified": True,
            "rollbackAvailable": True,
            "snapshotHash": snapshot.snapshot_hash,
            "schemaHash": snapshot.schema_hash,
            "receiptId": receipt_id,
            "payloadHash": document["payloadHash"],
            "requiredTables": required,
            "backupTables": [
                {
                    "sourceTable": table_key,
                    "backupTable": backup_table,
                    "rowCount": int(snapshot.row_counts[table_key]),
                }
                for table_key, backup_table in sorted(
                    target_backups.items(),
                    key=lambda item: item[0].casefold(),
                )
            ],
        }

    def verify_backup(
        self,
        connection: Any,
        *,
        target_database: str,
        backup_receipt: dict[str, Any],
        expected_snapshot_hash: str,
    ) -> dict[str, Any]:
        _fixed_target(target_database)
        receipt_id = _receipt_id(backup_receipt)
        verified = self._read_verified_backup(
            connection,
            receipt_id,
            expected_snapshot_hash=expected_snapshot_hash,
        )
        if str(backup_receipt.get("payloadHash") or "") != verified["payloadHash"]:
            raise InstyleDemoRebuildUnavailableError(
                "protected backup receipt does not match private readback"
            )
        return {
            "ok": True,
            "readbackVerified": True,
            "rollbackAvailable": True,
            "receiptId": receipt_id,
        }

    def reset_target(
        self,
        connection: Any,
        *,
        target_database: str,
        idempotency_key: str,
        plan_hash: str,
        backup_receipt: dict[str, Any],
        expected_schema_hash: str,
    ) -> dict[str, Any]:
        _fixed_target(target_database)
        del idempotency_key, plan_hash
        backup = self._read_verified_backup(
            connection,
            _receipt_id(backup_receipt),
            expected_snapshot_hash=str(backup_receipt.get("snapshotHash") or ""),
        )
        schema = _capture_schema(connection.cursor(), TARGET_USERNAME, TARGET_DATABASE)
        if schema.schema_hash != expected_schema_hash:
            raise InstyleDemoRebuildScopeError(
                "target schema changed before the protected reset"
            )
        required = _resolve_required_tables(
            schema,
            list(backup["payload"].get("requiredTables") or []),
        )
        try:
            _clear_rows(connection.cursor(), schema, required)
            readback = _capture_snapshot(
                connection,
                TARGET_USERNAME,
                TARGET_DATABASE,
                include_rows=False,
                query_timeout_seconds=self._query_timeout_seconds,
                manage_transaction=False,
            )
            if readback.schema_hash != expected_schema_hash:
                raise InstyleDemoRebuildUnavailableError(
                    "target schema changed during the protected reset"
                )
            if any(int(readback.row_counts.get(table, -1)) != 0 for table in required):
                raise InstyleDemoRebuildUnavailableError(
                    "protected reset left rows in a required target table"
                )
            connection.commit()
        except Exception:
            try:
                connection.rollback()
            except Exception:
                pass
            raise
        return {
            "ok": True,
            "reset": True,
            "readbackVerified": True,
            "targetReadyForLoad": True,
            "schemaHash": expected_schema_hash,
            "directOperations": ["fixed_target_row_clear"],
        }

    def rollback_target(
        self,
        connection: Any,
        *,
        target_database: str,
        idempotency_key: str,
        plan_hash: str,
        backup_receipt: dict[str, Any],
    ) -> dict[str, Any]:
        _fixed_target(target_database)
        del idempotency_key, plan_hash
        expected_snapshot_hash = str(backup_receipt.get("snapshotHash") or "")
        backup = self._read_verified_backup(
            connection,
            _receipt_id(backup_receipt),
            expected_snapshot_hash=expected_snapshot_hash,
        )
        payload = backup["payload"]
        schema = _capture_schema(connection.cursor(), TARGET_USERNAME, TARGET_DATABASE)
        if schema.schema_hash != str(payload.get("schemaHash") or ""):
            raise InstyleDemoRebuildUnavailableError(
                "target schema changed before protected rollback"
            )
        required = _resolve_required_tables(
            schema,
            list(payload.get("requiredTables") or []),
        )
        rows = _decoded_rows(payload, required)
        try:
            cursor = connection.cursor()
            _clear_rows(cursor, schema, required)
            _insert_rows(cursor, schema, required, rows)
            _insert_streamed_backup_rows(
                cursor,
                schema,
                required,
                payload,
            )
            before_commit = _capture_snapshot(
                connection,
                TARGET_USERNAME,
                TARGET_DATABASE,
                include_rows=False,
                query_timeout_seconds=self._query_timeout_seconds,
                manage_transaction=False,
            )
            if before_commit.snapshot_hash != expected_snapshot_hash:
                raise InstyleDemoRebuildUnavailableError(
                    "protected rollback readback did not match the complete backup"
                )
            connection.commit()
            post_commit = _capture_snapshot(
                connection,
                TARGET_USERNAME,
                TARGET_DATABASE,
                include_rows=False,
                query_timeout_seconds=self._query_timeout_seconds,
                manage_transaction=False,
            )
            try:
                connection.rollback()
            except Exception:
                pass
            if post_commit.snapshot_hash != expected_snapshot_hash:
                raise InstyleDemoRebuildUnavailableError(
                    "protected rollback changed after commit"
                )
        except Exception:
            try:
                connection.rollback()
            except Exception:
                pass
            raise
        return {
            "ok": True,
            "restored": True,
            "readbackVerified": True,
            "receiptId": _receipt_id(backup_receipt),
            "snapshotHash": expected_snapshot_hash,
        }

    def _backup_path(self, receipt_id: str) -> Path:
        clean = _receipt_id({"receiptId": receipt_id})
        self._backup_dir.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self._backup_dir, 0o700)
        except OSError:
            pass
        return self._backup_dir / f"{clean}.json"

    def _read_verified_backup(
        self,
        connection: Any,
        receipt_id: str,
        *,
        expected_snapshot_hash: str,
    ) -> dict[str, Any]:
        document = _read_json_required(
            self._backup_path(receipt_id),
            "protected complete backup",
        )
        if (
            document.get("version") != BACKUP_VERSION
            or document.get("operation") != OPERATION_NAME
            or document.get("receiptId") != receipt_id
            or not isinstance(document.get("payload"), dict)
        ):
            raise InstyleDemoRebuildUnavailableError(
                "protected complete backup envelope is invalid"
            )
        payload = dict(document["payload"])
        payload_hash = _sha256_json(payload)
        if payload_hash != document.get("payloadHash"):
            raise InstyleDemoRebuildUnavailableError(
                "protected complete backup integrity check failed"
            )
        snapshot_hash = _snapshot_hash_from_payload(payload)
        if snapshot_hash != expected_snapshot_hash:
            raise InstyleDemoRebuildUnavailableError(
                "protected complete backup snapshot readback failed"
            )
        cursor = connection.cursor()
        for table_key, table in payload["tables"].items():
            if not isinstance(table, dict) or table.get("storage") != "target_table":
                continue
            backup_table = str(table.get("backupTable") or "")
            if (
                not _table_exists(cursor, backup_table)
                or _table_count(cursor, backup_table)
                != int(table.get("rowCount", -1))
            ):
                raise InstyleDemoRebuildUnavailableError(
                    "streamed protected backup table readback failed"
                )
        return {"payload": payload, "payloadHash": payload_hash}


def _backup_payload(
    snapshot: DatabaseSnapshot,
    required_tables: list[str],
    streamed_backups: dict[str, str],
) -> dict[str, Any]:
    tables: dict[str, Any] = {}
    for table_key in sorted(snapshot.tables, key=str.casefold):
        rows = snapshot.rows.get(table_key, [])
        if table_key in streamed_backups:
            tables[table_key] = {
                "rowCount": snapshot.row_counts[table_key],
                "dataHash": snapshot.table_hashes[table_key],
                "storage": "target_table",
                "backupTable": streamed_backups[table_key],
            }
            continue
        encoded_rows = [
            {
                str(name): _encode_backup_value(value)
                for name, value in sorted(row.items(), key=lambda item: item[0].casefold())
            }
            for row in rows
        ]
        tables[table_key] = {
            "rowCount": snapshot.row_counts[table_key],
            "dataHash": snapshot.table_hashes[table_key],
            "storage": "private_runtime_state",
            "rows": encoded_rows,
        }
    return {
        "version": BACKUP_VERSION,
        "targetDatabase": TARGET_DATABASE,
        "schemaHash": snapshot.schema_hash,
        "snapshotHash": snapshot.snapshot_hash,
        "requiredTables": required_tables,
        "tables": tables,
    }


def _snapshot_hash_from_payload(payload: dict[str, Any]) -> str:
    if (
        payload.get("version") != BACKUP_VERSION
        or payload.get("targetDatabase") != TARGET_DATABASE
        or not isinstance(payload.get("schemaHash"), str)
        or not isinstance(payload.get("tables"), dict)
    ):
        raise InstyleDemoRebuildUnavailableError(
            "protected complete backup payload is invalid"
        )
    table_values: list[dict[str, Any]] = []
    # Match _capture_snapshot's canonical table ordering exactly. SQL
    # identifiers in this schema have mixed casing, so a casefold sort produces
    # a different aggregate hash even when every table hash and count matches.
    for table_key in sorted(payload["tables"]):
        table = payload["tables"][table_key]
        if not isinstance(table, dict):
            raise InstyleDemoRebuildUnavailableError(
                "protected complete backup table payload is invalid"
            )
        if table.get("storage") == "target_table":
            if (
                not isinstance(table.get("backupTable"), str)
                or not table.get("backupTable")
                or int(table.get("rowCount", -1)) < 0
                or not isinstance(table.get("dataHash"), str)
            ):
                raise InstyleDemoRebuildUnavailableError(
                    "streamed protected backup table payload is invalid"
                )
            table_values.append(
                {
                    "table": table_key,
                    "rowCount": int(table["rowCount"]),
                    "dataHash": table["dataHash"],
                }
            )
            continue
        if not isinstance(table.get("rows"), list):
            raise InstyleDemoRebuildUnavailableError(
                "protected complete backup row payload is invalid"
            )
        decoded = [
            {str(name): _decode_backup_value(value) for name, value in row.items()}
            for row in table["rows"]
            if isinstance(row, dict)
        ]
        if len(decoded) != len(table["rows"]):
            raise InstyleDemoRebuildUnavailableError(
                "protected complete backup row payload is invalid"
            )
        row_values = sorted(_canonical_row_json(row) for row in decoded)
        data_hash = hashlib.sha256("\n".join(row_values).encode("utf-8")).hexdigest()
        if len(decoded) != int(table.get("rowCount", -1)) or data_hash != table.get("dataHash"):
            raise InstyleDemoRebuildUnavailableError(
                "protected complete backup row readback failed"
            )
        table_values.append(
            {
                "table": table_key,
                "rowCount": len(decoded),
                "dataHash": data_hash,
            }
        )
    value = {
        "databaseName": TARGET_DATABASE,
        "schemaHash": payload["schemaHash"],
        "tables": table_values,
    }
    snapshot_hash = _sha256_json(value)
    if snapshot_hash != payload.get("snapshotHash"):
        raise InstyleDemoRebuildUnavailableError(
            "protected complete backup aggregate readback failed"
        )
    return snapshot_hash


def _decoded_rows(
    payload: dict[str, Any],
    required_tables: list[str],
) -> dict[str, list[dict[str, Any]]]:
    tables = payload.get("tables")
    if not isinstance(tables, dict):
        raise InstyleDemoRebuildUnavailableError(
            "protected complete backup tables are unavailable"
        )
    output: dict[str, list[dict[str, Any]]] = {}
    for table_key in required_tables:
        table = tables.get(table_key)
        if not isinstance(table, dict):
            raise InstyleDemoRebuildUnavailableError(
                "required protected backup table is unavailable"
            )
        if table.get("storage") == "target_table":
            output[table_key] = []
            continue
        if not isinstance(table.get("rows"), list):
            raise InstyleDemoRebuildUnavailableError(
                "required protected backup rows are unavailable"
            )
        output[table_key] = [
            {str(name): _decode_backup_value(value) for name, value in row.items()}
            for row in table["rows"]
        ]
    return output


def _clear_rows(
    cursor: Any,
    schema: DatabaseSnapshot,
    required_tables: list[str],
) -> None:
    ordered, _cyclic = _dependency_order(schema, required_tables)
    for table_key in reversed(ordered):
        cursor.execute(f"DELETE FROM {_quote_table(table_key)}")


def _insert_rows(
    cursor: Any,
    schema: DatabaseSnapshot,
    required_tables: list[str],
    rows_by_table: dict[str, list[dict[str, Any]]],
) -> None:
    ordered, cyclic_foreign_keys = _dependency_order(schema, required_tables)
    deferred_values: list[dict[str, Any]] = []
    for table_key, column_name in cyclic_foreign_keys:
        spec = schema.tables[table_key]
        if not spec.primary_key:
            raise InstyleDemoRebuildUnavailableError(
                "protected rollback cannot restore a cyclic table without a primary key"
            )
        for row in rows_by_table.get(table_key, []):
            value = _row_value(row, column_name)
            if value is None:
                continue
            deferred_values.append(
                {
                    "table": table_key,
                    "column": column_name,
                    "value": value,
                    "primaryKey": [
                        (column.name, _row_value(row, column.name))
                        for column in spec.primary_key
                    ],
                }
            )
            existing = next(
                key for key in row if key.casefold() == column_name.casefold()
            )
            row[existing] = None
    for table_key in ordered:
        rows = rows_by_table.get(table_key, [])
        if not rows:
            continue
        spec = schema.tables[table_key]
        columns = [
            column
            for column in spec.copyable_columns
            if any(_has_row_key(row, column.name) for row in rows)
        ]
        if not columns:
            continue
        identity = spec.identity_column
        identity_present = bool(
            identity and any(_has_row_key(row, identity.name) for row in rows)
        )
        if identity_present:
            cursor.execute(f"SET IDENTITY_INSERT {_quote_table(table_key)} ON")
        try:
            statement = (
                f"INSERT INTO {_quote_table(table_key)} "
                f"({', '.join(_quote_identifier(column.name) for column in columns)}) "
                f"VALUES ({', '.join('?' for _ in columns)})"
            )
            values = [
                tuple(_row_value(row, column.name) for column in columns)
                for row in rows
            ]
            for start in range(0, len(values), MAX_BATCH_ROWS):
                cursor.executemany(statement, values[start : start + MAX_BATCH_ROWS])
        finally:
            if identity_present:
                cursor.execute(f"SET IDENTITY_INSERT {_quote_table(table_key)} OFF")
    for update in deferred_values:
        where = " AND ".join(
            f"{_quote_identifier(name)}=?" for name, _ in update["primaryKey"]
        )
        cursor.execute(
            f"UPDATE {_quote_table(update['table'])} "
            f"SET {_quote_identifier(update['column'])}=? WHERE {where}",
            [update["value"], *[value for _, value in update["primaryKey"]]],
        )


def _insert_streamed_backup_rows(
    cursor: Any,
    schema: DatabaseSnapshot,
    required_tables: list[str],
    payload: dict[str, Any],
) -> None:
    tables = payload.get("tables")
    if not isinstance(tables, dict):
        raise InstyleDemoRebuildUnavailableError(
            "streamed protected backup tables are unavailable"
        )
    ordered, cyclic = _dependency_order(schema, required_tables)
    cyclic_by_table: dict[str, set[str]] = {}
    for table_key, column_name in cyclic:
        cyclic_by_table.setdefault(table_key, set()).add(column_name.casefold())
    for table_key in ordered:
        table = tables.get(table_key)
        if not isinstance(table, dict) or table.get("storage") != "target_table":
            continue
        backup_table = str(table.get("backupTable") or "")
        if not _table_exists(cursor, backup_table):
            raise InstyleDemoRebuildUnavailableError(
                "streamed protected backup table is unavailable for rollback"
            )
        spec = schema.tables[table_key]
        columns = list(spec.copyable_columns)
        deferred_columns = cyclic_by_table.get(table_key, set())
        identity = spec.identity_column
        if identity is not None:
            cursor.execute(f"SET IDENTITY_INSERT {_quote_table(table_key)} ON")
        try:
            cursor.execute(
                f"INSERT INTO {_quote_table(table_key)} "
                f"({', '.join(_quote_identifier(column.name) for column in columns)}) "
                "SELECT "
                + ", ".join(
                    (
                        "NULL"
                        if column.name.casefold() in deferred_columns
                        else _quote_identifier(column.name)
                    )
                    for column in columns
                )
                + f" FROM {_quote_table(backup_table)}"
            )
        finally:
            if identity is not None:
                cursor.execute(f"SET IDENTITY_INSERT {_quote_table(table_key)} OFF")
    for table_key, column_name in cyclic:
        table = tables.get(table_key)
        if not isinstance(table, dict) or table.get("storage") != "target_table":
            continue
        spec = schema.tables[table_key]
        if not spec.primary_key:
            raise InstyleDemoRebuildUnavailableError(
                "protected rollback cannot restore a cyclic table without a primary key"
            )
        backup_table = str(table.get("backupTable") or "")
        join = " AND ".join(
            f"target.{_quote_identifier(column.name)}="
            f"backup.{_quote_identifier(column.name)}"
            for column in spec.primary_key
        )
        cursor.execute(
            f"UPDATE target SET target.{_quote_identifier(column_name)}="
            f"backup.{_quote_identifier(column_name)} "
            f"FROM {_quote_table(table_key)} AS target "
            f"JOIN {_quote_table(backup_table)} AS backup ON {join}"
        )


def _backup_table_identifier(table_key: str, receipt_id: str) -> str:
    digest = hashlib.sha256(table_key.casefold().encode("utf-8")).hexdigest()[:10]
    return f"dbo.__nova_rebuild_backup_{receipt_id[:10]}_{digest}"


def _table_exists(cursor: Any, table_key: str) -> bool:
    row = cursor.execute(
        "SELECT CASE WHEN OBJECT_ID(?, 'U') IS NULL THEN 0 ELSE 1 END",
        [table_key],
    ).fetchone()
    return bool(row and int(row[0] or 0) == 1)


def _table_count(cursor: Any, table_key: str) -> int:
    row = cursor.execute(
        f"SELECT COUNT_BIG(*) FROM {_quote_table(table_key)}"
    ).fetchone()
    return int(row[0] or 0) if row else 0


def _resolve_required_tables(
    snapshot: DatabaseSnapshot,
    required_tables: list[str],
) -> list[str]:
    if not required_tables:
        raise InstyleDemoRebuildUnavailableError(
            "protected reset requires the immutable required-table set"
        )
    lookup = {key.casefold(): key for key in snapshot.tables}
    resolved: list[str] = []
    for value in required_tables:
        key = lookup.get(str(value).casefold())
        if key is None:
            raise InstyleDemoRebuildScopeError(
                "protected reset required-table set no longer matches the target"
            )
        if key not in resolved:
            resolved.append(key)
    return sorted(resolved, key=str.casefold)


def _encode_backup_value(value: Any) -> Any:
    encoded = _canonical_value(value)
    if isinstance(encoded, dict) and encoded.get("type") not in {
        "bytes",
        "decimal",
        "datetime",
        "date",
        "time",
        "uuid",
        "float",
    }:
        raise InstyleDemoRebuildUnavailableError(
            "protected backup encountered an unsupported target value type"
        )
    return encoded


def _decode_backup_value(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if not isinstance(value, dict) or set(value) != {"type", "value"}:
        raise InstyleDemoRebuildUnavailableError(
            "protected backup value encoding is invalid"
        )
    kind = str(value["type"])
    raw = str(value["value"])
    try:
        if kind == "bytes":
            return base64.b64decode(raw.encode("ascii"), validate=True)
        if kind == "decimal":
            return Decimal(raw)
        if kind == "datetime":
            return datetime.fromisoformat(raw)
        if kind == "date":
            return date.fromisoformat(raw)
        if kind == "time":
            return time.fromisoformat(raw)
        if kind == "uuid":
            return UUID(raw)
        if kind == "float":
            return float(raw)
    except (ValueError, TypeError) as exc:
        raise InstyleDemoRebuildUnavailableError(
            "protected backup value readback is invalid"
        ) from exc
    raise InstyleDemoRebuildUnavailableError(
        "protected backup value type is unsupported"
    )


def _receipt_id(receipt: dict[str, Any]) -> str:
    value = str(receipt.get("receiptId") or "")
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise InstyleDemoRebuildUnavailableError(
            "protected backup receipt identifier is invalid"
        )
    return value


def _fixed_target(value: str) -> str:
    if str(value or "").casefold() != TARGET_DATABASE.casefold():
        raise InstyleDemoRebuildScopeError(
            "protected restore target is fixed to the demo database"
        )
    return TARGET_DATABASE
