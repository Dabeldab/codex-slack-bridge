from __future__ import annotations

# AgentChat/coding_agent 2026-07-28T04:19:17Z

import base64
import hashlib
import json
import os
import re
import stat
import subprocess
import unicodedata
from contextlib import ExitStack, closing
from dataclasses import dataclass, field
from datetime import date, datetime, time, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Protocol
from uuid import UUID


OPERATION_NAME = "instyle_demo_rebuild_v1"
SOURCE_A_USERNAME = "LE_BOUTIQUE_INSTYLE"
SOURCE_A_DATABASE = "POS_LE_BOUTIQUE_INSTYLE"
SOURCE_B_USERNAME = "Instyle_Fragrance"
SOURCE_B_DATABASE = "POS_Instyle_Fragrance"
TARGET_USERNAME = "DEMO_NOVA_CAFE"
TARGET_DATABASE = "POS_DEMO_NOVA_CAFE"
TICKET_NUMBERS = ("347072", "347073")
SOURCE_B_ID_OFFSET = 1_000_000_000
PRODUCT_KEY_COLUMNS = ("ProductName", "BarcodeNumber", "BarcodeNumber2", "SKU")
PRODUCT_TABLE_NAME = "products"
INVOICE_PRODUCTS_TABLE_NAME = "invoice_products"
STREAMED_TABLE_NAMES = frozenset({"inventoryhistoryitem"})
EXCLUDED_DIAGNOSTIC_TABLE_NAMES = frozenset({"log4net"})
FIXED_TARGET_SCHEMA_OMISSIONS = {
    (
        SOURCE_B_USERNAME.casefold(),
        "dbo.employees_hours",
        "originalhours",
    ): {
        "sourceType": "decimal",
        "nullable": True,
    },
}
PRODUCT_REFERENCE_COLUMNS = {
    "coupons_products": "productid",
    "customerorders_products": "productid",
    "inventory": "productid",
    "inventory_counts_products": "productid",
    "inventory_damage": "productid",
    "inventory_transactions": "productid",
    "inventoryhistoryitem": "originalproductid",
    "invoice_products": "productid",
    "invoice_refunds": "productid",
    "pending_invoice_product": "productid",
    "pricelists_items": "productid",
    "productfavorites": "productid",
    "quote_products": "productid",
    "refunds_products": "productid",
    "storageorders_products": "productid",
}
INTERNAL_TABLE_PREFIXES = ("__codex_", "__nova_rebuild_")
IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_$#@]{0,127}$")
IDEMPOTENCY_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{7,199}$")
HASH = re.compile(r"^[0-9a-f]{64}$")
MAX_SOURCE_ROWS = 5_000_000
MAX_BATCH_ROWS = 1_000
STREAM_BATCH_ROWS = 10_000
FIXED_OPERATION_QUERY_TIMEOUT_SECONDS = 3_600
DURABLE_RECEIPT_TABLE = "dbo.__codex_instyle_demo_rebuild_receipts"


class InstyleDemoRebuildScopeError(ValueError):
    """The fixed Instyle-to-demo operation contract was violated."""


class InstyleDemoRebuildUnavailableError(RuntimeError):
    """A required protected restore or database dependency is unavailable."""


class ProtectedDemoRestoreGateway(Protocol):
    """Broker-owned reset boundary; implementations never return credentials."""

    def capability_status(self, *, target_database: str) -> dict[str, Any]: ...

    def create_complete_backup(
        self,
        connection: Any,
        *,
        target_database: str,
        idempotency_key: str,
        plan_hash: str,
        expected_snapshot_hash: str,
        required_tables: list[str],
    ) -> dict[str, Any]: ...

    def verify_backup(
        self,
        connection: Any,
        *,
        target_database: str,
        backup_receipt: dict[str, Any],
        expected_snapshot_hash: str,
    ) -> dict[str, Any]: ...

    def reset_target(
        self,
        connection: Any,
        *,
        target_database: str,
        idempotency_key: str,
        plan_hash: str,
        backup_receipt: dict[str, Any],
        expected_schema_hash: str,
    ) -> dict[str, Any]: ...

    def rollback_target(
        self,
        connection: Any,
        *,
        target_database: str,
        idempotency_key: str,
        plan_hash: str,
        backup_receipt: dict[str, Any],
    ) -> dict[str, Any]: ...


class LocalProtectedDemoRestoreGateway:
    """Invoke only an operator-installed, root-owned protected demo restore helper."""

    _ACTIONS = frozenset({"capabilities", "backup", "verify_backup", "reset", "rollback"})
    _SECRET_KEY = re.compile(
        r"(?:password|passcode|secret|token|authorization|cookie|connectionstring|credential)",
        re.IGNORECASE,
    )

    def __init__(self, helper_path: str | Path, *, timeout_seconds: int = 900) -> None:
        self._configured_helper_path = Path(helper_path).expanduser()
        self._helper_path = self._configured_helper_path.resolve()
        self._timeout_seconds = max(30, min(int(timeout_seconds), 3_600))

    @classmethod
    def from_environment(cls) -> LocalProtectedDemoRestoreGateway | None:
        value = os.getenv("NOVA_SQL_INSTYLE_DEMO_RESTORE_HELPER", "").strip()
        if not value:
            return None
        timeout = int(os.getenv("NOVA_SQL_INSTYLE_DEMO_RESTORE_TIMEOUT_SECONDS", "900"))
        return cls(value, timeout_seconds=timeout)

    def capability_status(self, *, target_database: str) -> dict[str, Any]:
        return self._request("capabilities", {"targetDatabase": _fixed_target(target_database)})

    def create_complete_backup(
        self,
        _connection: Any,
        *,
        target_database: str,
        idempotency_key: str,
        plan_hash: str,
        expected_snapshot_hash: str,
        required_tables: list[str],
    ) -> dict[str, Any]:
        return self._request(
            "backup",
            {
                "targetDatabase": _fixed_target(target_database),
                "idempotencyKey": _idempotency_key(idempotency_key),
                "planHash": _hash_value(plan_hash),
                "expectedSnapshotHash": _hash_value(expected_snapshot_hash),
                "requiredTables": [str(value) for value in required_tables],
            },
        )

    def verify_backup(
        self,
        _connection: Any,
        *,
        target_database: str,
        backup_receipt: dict[str, Any],
        expected_snapshot_hash: str,
    ) -> dict[str, Any]:
        return self._request(
            "verify_backup",
            {
                "targetDatabase": _fixed_target(target_database),
                "backupReceipt": _bounded_receipt(backup_receipt),
                "expectedSnapshotHash": _hash_value(expected_snapshot_hash),
            },
        )

    def reset_target(
        self,
        _connection: Any,
        *,
        target_database: str,
        idempotency_key: str,
        plan_hash: str,
        backup_receipt: dict[str, Any],
        expected_schema_hash: str,
    ) -> dict[str, Any]:
        return self._request(
            "reset",
            {
                "targetDatabase": _fixed_target(target_database),
                "idempotencyKey": _idempotency_key(idempotency_key),
                "planHash": _hash_value(plan_hash),
                "backupReceipt": _bounded_receipt(backup_receipt),
                "expectedSchemaHash": _hash_value(expected_schema_hash),
            },
        )

    def rollback_target(
        self,
        _connection: Any,
        *,
        target_database: str,
        idempotency_key: str,
        plan_hash: str,
        backup_receipt: dict[str, Any],
    ) -> dict[str, Any]:
        return self._request(
            "rollback",
            {
                "targetDatabase": _fixed_target(target_database),
                "idempotencyKey": _idempotency_key(idempotency_key),
                "planHash": _hash_value(plan_hash),
                "backupReceipt": _bounded_receipt(backup_receipt),
            },
        )

    def _request(self, action: str, payload: dict[str, Any]) -> dict[str, Any]:
        if action not in self._ACTIONS:
            raise InstyleDemoRebuildScopeError("protected restore helper action is not allowed")
        try:
            metadata = self._helper_path.stat()
        except OSError as exc:
            raise InstyleDemoRebuildUnavailableError(
                "protected demo restore helper is unavailable"
            ) from exc
        if (
            self._configured_helper_path.is_symlink()
            or not self._helper_path.is_absolute()
            or not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != 0
            or metadata.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
            or not os.access(self._helper_path, os.X_OK)
        ):
            raise InstyleDemoRebuildUnavailableError(
                "protected demo restore helper ownership or permissions are unsafe"
            )
        request = {
            "version": 1,
            "operation": OPERATION_NAME,
            "action": action,
            "payload": payload,
        }
        try:
            result = subprocess.run(
                [str(self._helper_path), action],
                input=json.dumps(request, sort_keys=True, separators=(",", ":")),
                text=True,
                capture_output=True,
                timeout=self._timeout_seconds,
                check=False,
                env={
                    "LANG": "C.UTF-8",
                    "PATH": "/usr/sbin:/usr/bin:/sbin:/bin",
                },
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise InstyleDemoRebuildUnavailableError(
                "protected demo restore helper did not complete"
            ) from exc
        if result.returncode != 0 or len(result.stdout) > 65_536:
            raise InstyleDemoRebuildUnavailableError(
                "protected demo restore helper returned an unsuccessful result"
            )
        try:
            response = json.loads(result.stdout)
        except Exception as exc:
            raise InstyleDemoRebuildUnavailableError(
                "protected demo restore helper returned invalid readback"
            ) from exc
        if not isinstance(response, dict) or _contains_secret_key(response):
            raise InstyleDemoRebuildUnavailableError(
                "protected demo restore helper returned an unsafe response"
            )
        return response


@dataclass(frozen=True)
class ColumnSpec:
    name: str
    ordinal: int
    type_name: str
    nullable: bool
    identity: bool
    computed: bool
    generated: bool
    has_default: bool
    primary_key_ordinal: int = 0

    @property
    def copyable(self) -> bool:
        return not self.computed and not self.generated and self.type_name.casefold() not in {
            "rowversion",
            "timestamp",
        }

    @property
    def integer(self) -> bool:
        return self.type_name.casefold() in {"bigint", "int", "smallint", "tinyint"}


@dataclass(frozen=True)
class ForeignKeySpec:
    column: str
    referenced_table: str
    referenced_column: str


@dataclass(frozen=True)
class TableSpec:
    schema: str
    name: str
    columns: tuple[ColumnSpec, ...]
    foreign_keys: tuple[ForeignKeySpec, ...] = ()

    @property
    def key(self) -> str:
        return f"{self.schema}.{self.name}"

    @property
    def primary_key(self) -> tuple[ColumnSpec, ...]:
        return tuple(sorted((column for column in self.columns if column.primary_key_ordinal), key=lambda c: c.primary_key_ordinal))

    @property
    def identity_column(self) -> ColumnSpec | None:
        return next((column for column in self.columns if column.identity), None)

    @property
    def copyable_columns(self) -> tuple[ColumnSpec, ...]:
        return tuple(column for column in self.columns if column.copyable)


@dataclass
class DatabaseSnapshot:
    company_username: str
    database_name: str
    captured_at: str
    schema_hash: str
    snapshot_hash: str
    tables: dict[str, TableSpec]
    table_hashes: dict[str, str]
    row_counts: dict[str, int]
    consistency_mode: str = "schema_only"
    streamed_tables: tuple[str, ...] = ()
    rows: dict[str, list[dict[str, Any]]] = field(default_factory=dict)

    def public_manifest(self) -> dict[str, Any]:
        return {
            "companyUsername": self.company_username,
            "databaseName": self.database_name,
            "schemaHash": self.schema_hash,
            "snapshotHash": self.snapshot_hash,
            "consistencyMode": self.consistency_mode,
            "tableCount": len(self.tables),
            "tables": [
                {
                    "table": key,
                    "rowCount": self.row_counts[key],
                    "dataHash": self.table_hashes[key],
                    "captureMode": (
                        "database_bucket_fingerprint"
                        if key in self.streamed_tables
                        else "materialized_rows"
                    ),
                    "schema": _table_schema_value(self.tables[key]),
                }
                for key in sorted(self.tables)
            ],
        }


@dataclass
class MergeDataset:
    rows: dict[str, list[dict[str, Any]]]
    quarantine_rows: list[dict[str, Any]]
    reconciliation: dict[str, dict[str, int]]
    product_mapping_count: int
    placeholder_product_count: int
    product_dedupe_count: int
    product_map: dict[tuple[str, int], int] = field(default_factory=dict)
    streamed_tables: tuple[str, ...] = ()
    expected_product_orphan_rows: int = 0
    deferred_updates: list[dict[str, Any]] = field(default_factory=list)


class InstyleDemoRebuildOperation:
    """Fixed three-account rebuild with no caller-selected account, database, table, or SQL."""

    def __init__(
        self,
        *,
        connect: Callable[[str, bool], Any],
        state_dir: str | Path,
        restore_gateway: ProtectedDemoRestoreGateway | None,
        query_timeout_seconds: int = 30,
    ) -> None:
        self._connect = connect
        self._state_dir = Path(state_dir).expanduser().resolve() / OPERATION_NAME
        self._restore_gateway = restore_gateway
        # The fixed operation includes single-statement backup, load, and
        # readback work over more than 30M InventoryHistoryItem rows. It must
        # never inherit a generic bounded-read timeout.
        self._query_timeout_seconds = max(
            FIXED_OPERATION_QUERY_TIMEOUT_SECONDS,
            min(
                int(query_timeout_seconds),
                FIXED_OPERATION_QUERY_TIMEOUT_SECONDS,
            ),
        )

    def preview(self, *, idempotency_key: str) -> dict[str, Any]:
        clean_key = _idempotency_key(idempotency_key)
        existing = _read_json_optional(self._preview_path(clean_key))
        if existing:
            return _preview_result(existing, replay=True)
        restore_status = self._require_restore_gateway()
        with ExitStack() as stack:
            source_a_connection = stack.enter_context(closing(self._connect(SOURCE_A_USERNAME, True)))
            source_b_connection = stack.enter_context(closing(self._connect(SOURCE_B_USERNAME, True)))
            target_connection = stack.enter_context(closing(self._connect(TARGET_USERNAME, True)))
            source_a = _capture_snapshot(
                source_a_connection,
                SOURCE_A_USERNAME,
                SOURCE_A_DATABASE,
                include_rows=True,
                query_timeout_seconds=self._query_timeout_seconds,
            )
            source_b = _capture_snapshot(
                source_b_connection,
                SOURCE_B_USERNAME,
                SOURCE_B_DATABASE,
                include_rows=True,
                query_timeout_seconds=self._query_timeout_seconds,
            )
            target = _capture_snapshot(
                target_connection,
                TARGET_USERNAME,
                TARGET_DATABASE,
                include_rows=False,
                query_timeout_seconds=self._query_timeout_seconds,
            )

        required_tables = _validate_schema_contract(source_a, source_b, target)
        target_schema_omissions = _fixed_target_schema_omissions(
            source_a,
            source_b,
            target,
        )
        dataset = _build_merge_dataset(source_a, source_b, target, required_tables)
        immutable = {
            "version": 1,
            "operation": OPERATION_NAME,
            "tickets": list(TICKET_NUMBERS),
            "idempotencyKey": clean_key,
            "sourceA": source_a.public_manifest(),
            "sourceB": source_b.public_manifest(),
            "target": target.public_manifest(),
            "requiredTables": required_tables,
            "fixedTargetSchemaOmissions": target_schema_omissions,
            "sourceBNonProductIdOffset": SOURCE_B_ID_OFFSET,
            "productDedupeKey": list(PRODUCT_KEY_COLUMNS),
            "reconciliation": dataset.reconciliation,
            "productMappingCount": dataset.product_mapping_count,
            "placeholderProductCount": dataset.placeholder_product_count,
            "productDedupeCount": dataset.product_dedupe_count,
            "streamedTables": list(dataset.streamed_tables),
            "excludedDiagnosticTables": sorted(EXCLUDED_DIAGNOSTIC_TABLE_NAMES),
            "expectedProductOrphanRowsBeforeStreaming": dataset.expected_product_orphan_rows,
            "quarantineRowCount": len(dataset.quarantine_rows),
            "restoreContractVersion": str(restore_status.get("contractVersion") or ""),
        }
        plan_hash = _sha256_json(immutable)
        manifest = {
            **immutable,
            "planHash": plan_hash,
            "previewedAt": datetime.now(timezone.utc).isoformat(),
        }
        _write_json_atomic(self._preview_path(clean_key), manifest)
        return _preview_result(manifest, replay=False)

    def execute(self, *, idempotency_key: str, preview_hash: str) -> dict[str, Any]:
        clean_key = _idempotency_key(idempotency_key)
        clean_hash = str(preview_hash or "").strip().lower()
        if not HASH.fullmatch(clean_hash):
            raise InstyleDemoRebuildScopeError(
                "preview_hash must be the exact hash returned by nova_sql_instyle_demo_rebuild_preview"
            )
        gateway_status = self._require_restore_gateway()
        preview = _read_json_required(self._preview_path(clean_key), "preview")
        if preview.get("planHash") != clean_hash or preview.get("idempotencyKey") != clean_key:
            raise InstyleDemoRebuildScopeError("preview hash, idempotency key, or fixed rebuild plan does not match")
        if preview.get("operation") != OPERATION_NAME:
            raise InstyleDemoRebuildScopeError("preview belongs to a different business operation")

        completed = _read_json_optional(self._receipt_path(clean_key))
        if completed:
            return _completed_result(completed, clean_key, clean_hash, replay=True)
        checkpoint = _read_json_optional(self._checkpoint_path(clean_key)) or {}
        _validate_checkpoint(checkpoint, clean_key, clean_hash)

        gateway = self._restore_gateway
        if gateway is None:
            raise InstyleDemoRebuildUnavailableError("protected demo restore workflow is not configured")

        backup_receipt = dict(checkpoint.get("backupReceipt") or {})
        reset_completed = checkpoint.get("phase") in {"reset_completed", "load_started"}
        committed = False
        with ExitStack() as stack:
            source_a_connection = stack.enter_context(closing(self._connect(SOURCE_A_USERNAME, True)))
            source_b_connection = stack.enter_context(closing(self._connect(SOURCE_B_USERNAME, True)))
            source_a = _capture_snapshot(
                source_a_connection,
                SOURCE_A_USERNAME,
                SOURCE_A_DATABASE,
                include_rows=True,
                query_timeout_seconds=self._query_timeout_seconds,
                keep_transaction_open=True,
            )
            source_b = _capture_snapshot(
                source_b_connection,
                SOURCE_B_USERNAME,
                SOURCE_B_DATABASE,
                include_rows=True,
                query_timeout_seconds=self._query_timeout_seconds,
                keep_transaction_open=True,
            )
            _require_snapshot_match(source_a, preview["sourceA"], "source A")
            _require_snapshot_match(source_b, preview["sourceB"], "source B")

            target_connection = stack.enter_context(closing(self._connect(TARGET_USERNAME, False)))
            _set_timeout(target_connection, self._query_timeout_seconds)
            target_cursor = target_connection.cursor()
            _verify_database_binding(target_cursor, TARGET_DATABASE)
            _acquire_application_lock(target_cursor, clean_key)
            target_schema = _capture_schema(
                target_cursor,
                TARGET_USERNAME,
                TARGET_DATABASE,
            )
            required_tables = _validate_schema_contract(
                source_a,
                source_b,
                target_schema,
            )
            if required_tables != [str(value) for value in preview["requiredTables"]]:
                raise InstyleDemoRebuildScopeError(
                    "required table set changed after preview"
                )
            target_schema_omissions = _fixed_target_schema_omissions(
                source_a,
                source_b,
                target_schema,
            )
            if target_schema_omissions != list(
                preview.get("fixedTargetSchemaOmissions") or []
            ):
                raise InstyleDemoRebuildScopeError(
                    "fixed target schema omission evidence changed after preview"
                )
            dataset = _build_merge_dataset(
                source_a,
                source_b,
                target_schema,
                required_tables,
            )
            _validate_reconciliation(dataset, preview)
            current_target: DatabaseSnapshot | None = None
            if not checkpoint:
                current_target = _capture_snapshot(
                    target_connection,
                    TARGET_USERNAME,
                    TARGET_DATABASE,
                    include_rows=False,
                    query_timeout_seconds=self._query_timeout_seconds,
                    manage_transaction=False,
                )
                _require_snapshot_match(current_target, preview["target"], "target")
            source_a.rows.clear()
            source_b.rows.clear()
            streamed_stage_tables, streamed_expected_orphans = _stage_streamed_tables(
                connect=self._connect,
                target_connection=target_connection,
                source_a=source_a,
                source_b=source_b,
                target=target_schema,
                dataset=dataset,
                preview=preview,
                plan_hash=clean_hash,
                query_timeout_seconds=self._query_timeout_seconds,
            )
            dataset.expected_product_orphan_rows += streamed_expected_orphans

            try:
                if not checkpoint:
                    if current_target is None:
                        raise InstyleDemoRebuildUnavailableError(
                            "fresh target snapshot is unavailable before backup"
                        )
                    backup_receipt = dict(
                        gateway.create_complete_backup(
                            target_connection,
                            target_database=TARGET_DATABASE,
                            idempotency_key=clean_key,
                            plan_hash=clean_hash,
                            expected_snapshot_hash=current_target.snapshot_hash,
                            required_tables=required_tables,
                        )
                        or {}
                    )
                    _require_backup_receipt(
                        backup_receipt,
                        expected_snapshot_hash=current_target.snapshot_hash,
                    )
                    verified = dict(
                        gateway.verify_backup(
                            target_connection,
                            target_database=TARGET_DATABASE,
                            backup_receipt=backup_receipt,
                            expected_snapshot_hash=current_target.snapshot_hash,
                        )
                        or {}
                    )
                    _require_backup_verification(verified, backup_receipt)
                    checkpoint = _checkpoint(
                        clean_key,
                        clean_hash,
                        "backup_verified",
                        backup_receipt=backup_receipt,
                    )
                    _write_json_atomic(self._checkpoint_path(clean_key), checkpoint)
                else:
                    verified = dict(
                        gateway.verify_backup(
                            target_connection,
                            target_database=TARGET_DATABASE,
                            backup_receipt=backup_receipt,
                            expected_snapshot_hash=str(preview["target"]["snapshotHash"]),
                        )
                        or {}
                    )
                    _require_backup_verification(verified, backup_receipt)

                if not reset_completed:
                    reset = dict(
                        gateway.reset_target(
                            target_connection,
                            target_database=TARGET_DATABASE,
                            idempotency_key=clean_key,
                            plan_hash=clean_hash,
                            backup_receipt=backup_receipt,
                            expected_schema_hash=str(preview["target"]["schemaHash"]),
                        )
                        or {}
                    )
                    _require_reset_receipt(reset, expected_schema_hash=str(preview["target"]["schemaHash"]))
                    checkpoint = _checkpoint(
                        clean_key,
                        clean_hash,
                        "reset_completed",
                        backup_receipt=backup_receipt,
                        reset_receipt=reset,
                    )
                    _write_json_atomic(self._checkpoint_path(clean_key), checkpoint)
                    reset_completed = True

                try:
                    target_connection.close()
                except Exception:
                    pass
                target_connection = stack.enter_context(closing(self._connect(TARGET_USERNAME, False)))
                _set_timeout(target_connection, self._query_timeout_seconds)
                target_cursor = target_connection.cursor()
                target_cursor.execute("SET XACT_ABORT ON")
                _verify_database_binding(target_cursor, TARGET_DATABASE)
                _acquire_application_lock(target_cursor, clean_key)
                target_schema = _capture_schema(
                    target_cursor,
                    TARGET_USERNAME,
                    TARGET_DATABASE,
                )
                if target_schema.schema_hash != str(preview["target"]["schemaHash"]):
                    raise InstyleDemoRebuildScopeError("target schema changed after protected reset")
                durable_receipt = _read_durable_receipt(target_cursor, clean_key)
                if durable_receipt:
                    _require_durable_receipt(durable_receipt, clean_key, clean_hash)
                    quarantine_table = f"dbo.__codex_quarantine_invoice_products_{clean_hash[:12]}"
                    post_commit = _readback_target_dataset(
                        target_cursor,
                        target_schema,
                        required_tables,
                        dataset,
                        quarantine_table,
                    )
                    if durable_receipt.get("readbackHash") != _sha256_json(post_commit):
                        raise InstyleDemoRebuildUnavailableError(
                            "durable rebuild receipt does not match resumed post-commit readback"
                        )
                    receipt = _completion_receipt(
                        clean_key,
                        clean_hash,
                        required_tables,
                        target_schema_omissions,
                        dataset,
                        backup_receipt,
                        post_commit,
                        gateway_status,
                    )
                    _write_json_atomic(self._receipt_path(clean_key), receipt)
                    return _completed_result(receipt, clean_key, clean_hash, replay=True)
                checkpoint = _checkpoint(
                    clean_key,
                    clean_hash,
                    "load_started",
                    backup_receipt=backup_receipt,
                    reset_receipt=dict(checkpoint.get("resetReceipt") or {}),
                )
                _write_json_atomic(self._checkpoint_path(clean_key), checkpoint)
                quarantine_table = _load_target_dataset(
                    target_cursor,
                    target_schema,
                    required_tables,
                    dataset,
                    clean_hash,
                    streamed_stage_tables=streamed_stage_tables,
                )
                readback = _readback_target_dataset(
                    target_cursor,
                    target_schema,
                    required_tables,
                    dataset,
                    quarantine_table,
                )
                _write_durable_receipt(
                    target_cursor,
                    idempotency_key=clean_key,
                    plan_hash=clean_hash,
                    readback_hash=_sha256_json(readback),
                )
                target_connection.commit()
                committed = True
                post_commit = _readback_target_dataset(
                    target_cursor,
                    target_schema,
                    required_tables,
                    dataset,
                    quarantine_table,
                )
                if post_commit != readback:
                    raise InstyleDemoRebuildUnavailableError(
                        "rebuild committed but post-write readback changed; protected rollback is required"
                    )
                durable_receipt = _read_durable_receipt(target_cursor, clean_key)
                _require_durable_receipt(durable_receipt, clean_key, clean_hash)
                if durable_receipt.get("readbackHash") != _sha256_json(post_commit):
                    raise InstyleDemoRebuildUnavailableError(
                        "durable rebuild receipt does not match post-commit readback"
                    )
                receipt = _completion_receipt(
                    clean_key,
                    clean_hash,
                    required_tables,
                    target_schema_omissions,
                    dataset,
                    backup_receipt,
                    post_commit,
                    gateway_status,
                )
                _write_json_atomic(self._receipt_path(clean_key), receipt)
                return _completed_result(receipt, clean_key, clean_hash, replay=False)
            except Exception as exc:
                if not committed:
                    try:
                        target_connection.rollback()
                    except Exception:
                        pass
                if reset_completed and backup_receipt:
                    rollback_connection = None
                    try:
                        rollback_connection = self._connect(TARGET_USERNAME, False)
                        rollback = dict(
                            gateway.rollback_target(
                                rollback_connection,
                                target_database=TARGET_DATABASE,
                                idempotency_key=clean_key,
                                plan_hash=clean_hash,
                                backup_receipt=backup_receipt,
                            )
                            or {}
                        )
                        if not (
                            rollback.get("ok")
                            and rollback.get("restored")
                            and rollback.get("readbackVerified")
                        ):
                            raise InstyleDemoRebuildUnavailableError(
                                "protected rollback did not return verified target restoration"
                            )
                        _write_json_atomic(
                            self._checkpoint_path(clean_key),
                            _checkpoint(
                                clean_key,
                                clean_hash,
                                "rolled_back",
                                backup_receipt=backup_receipt,
                                rollback_receipt=rollback,
                            ),
                        )
                    except Exception as rollback_exc:
                        raise InstyleDemoRebuildUnavailableError(
                            "rebuild failed after reset and protected rollback could not be verified; do not retry"
                        ) from rollback_exc
                    finally:
                        if rollback_connection is not None:
                            try:
                                rollback_connection.close()
                            except Exception:
                                pass
                if isinstance(exc, (InstyleDemoRebuildScopeError, InstyleDemoRebuildUnavailableError)):
                    raise
                raise InstyleDemoRebuildUnavailableError(
                    "fixed Instyle demo rebuild failed; the target transaction was rolled back"
                ) from exc
            finally:
                for source_connection in (source_a_connection, source_b_connection):
                    try:
                        source_connection.rollback()
                    except Exception:
                        pass

    def recover(self, *, idempotency_key: str, preview_hash: str) -> dict[str, Any]:
        """Restore the fixed demo target after an abandoned post-reset execute.

        Recovery accepts only the original operation identity. It never reads a
        source database, rebuilds a plan, or accepts caller-selected account,
        database, table, row, or SQL input.
        """

        clean_key = _idempotency_key(idempotency_key)
        clean_hash = str(preview_hash or "").strip().lower()
        if not HASH.fullmatch(clean_hash):
            raise InstyleDemoRebuildScopeError(
                "preview_hash must be the exact hash returned by nova_sql_instyle_demo_rebuild_preview"
            )
        gateway_status = self._require_restore_gateway()
        preview = _read_json_required(self._preview_path(clean_key), "preview")
        if (
            preview.get("planHash") != clean_hash
            or preview.get("idempotencyKey") != clean_key
            or preview.get("operation") != OPERATION_NAME
        ):
            raise InstyleDemoRebuildScopeError(
                "preview hash, idempotency key, or fixed rebuild plan does not match"
            )

        completed = _read_json_optional(self._receipt_path(clean_key))
        if completed:
            return {
                **_completed_result(completed, clean_key, clean_hash, replay=True),
                "recoveryAction": "none_completed",
                "sourceDatabasesRead": False,
            }

        checkpoint = _read_json_optional(self._checkpoint_path(clean_key)) or {}
        if not checkpoint:
            raise InstyleDemoRebuildUnavailableError(
                "no durable rebuild checkpoint is available for protected recovery"
            )
        if (
            checkpoint.get("operation") != OPERATION_NAME
            or checkpoint.get("idempotencyKey") != clean_key
            or checkpoint.get("planHash") != clean_hash
        ):
            raise InstyleDemoRebuildScopeError(
                "idempotency key was used for a different rebuild checkpoint"
            )

        phase = str(checkpoint.get("phase") or "")
        if phase == "rolled_back":
            rollback = dict(checkpoint.get("rollbackReceipt") or {})
            _require_rollback_receipt(rollback)
            return _recovery_result(
                clean_key,
                clean_hash,
                status="rolled_back",
                action="none_already_restored",
                rollback_receipt=rollback,
                gateway_status=gateway_status,
                replay=True,
            )
        if phase == "backup_verified":
            return _recovery_result(
                clean_key,
                clean_hash,
                status="target_unchanged",
                action="none_reset_never_started",
                rollback_receipt={},
                gateway_status=gateway_status,
                replay=True,
            )
        if phase not in {"reset_completed", "load_started"}:
            raise InstyleDemoRebuildUnavailableError(
                "the durable rebuild checkpoint is not recoverable by the fixed target restore"
            )

        backup_receipt = dict(checkpoint.get("backupReceipt") or {})
        _require_backup_receipt(
            backup_receipt,
            expected_snapshot_hash=str(preview["target"]["snapshotHash"]),
        )
        gateway = self._restore_gateway
        if gateway is None:
            raise InstyleDemoRebuildUnavailableError(
                "protected demo restore workflow is not configured"
            )

        with closing(self._connect(TARGET_USERNAME, False)) as target_connection:
            _set_timeout(target_connection, self._query_timeout_seconds)
            target_cursor = target_connection.cursor()
            target_cursor.execute("SET XACT_ABORT ON")
            _verify_database_binding(target_cursor, TARGET_DATABASE)
            _acquire_application_lock(target_cursor, clean_key)
            target_schema = _capture_schema(
                target_cursor,
                TARGET_USERNAME,
                TARGET_DATABASE,
            )
            if target_schema.schema_hash != str(preview["target"]["schemaHash"]):
                raise InstyleDemoRebuildScopeError(
                    "target schema changed before protected abandoned-run recovery"
                )
            durable_receipt = _read_durable_receipt(target_cursor, clean_key)
            if durable_receipt:
                _require_durable_receipt(durable_receipt, clean_key, clean_hash)
                return _recovery_result(
                    clean_key,
                    clean_hash,
                    status="committed",
                    action="none_durable_commit_present",
                    rollback_receipt={},
                    gateway_status=gateway_status,
                    replay=True,
                )
            verified = dict(
                gateway.verify_backup(
                    target_connection,
                    target_database=TARGET_DATABASE,
                    backup_receipt=backup_receipt,
                    expected_snapshot_hash=str(preview["target"]["snapshotHash"]),
                )
                or {}
            )
            _require_backup_verification(verified, backup_receipt)
            rollback = dict(
                gateway.rollback_target(
                    target_connection,
                    target_database=TARGET_DATABASE,
                    idempotency_key=clean_key,
                    plan_hash=clean_hash,
                    backup_receipt=backup_receipt,
                )
                or {}
            )
            _require_rollback_receipt(rollback)

        _write_json_atomic(
            self._checkpoint_path(clean_key),
            _checkpoint(
                clean_key,
                clean_hash,
                "rolled_back",
                backup_receipt=backup_receipt,
                rollback_receipt=rollback,
            ),
        )
        return _recovery_result(
            clean_key,
            clean_hash,
            status="rolled_back",
            action="protected_backup_restored",
            rollback_receipt=rollback,
            gateway_status=gateway_status,
            replay=False,
        )

    def _require_restore_gateway(self) -> dict[str, Any]:
        if self._restore_gateway is None:
            raise InstyleDemoRebuildUnavailableError(
                "the protected demo restore workflow is not configured for this broker"
            )
        status = dict(self._restore_gateway.capability_status(target_database=TARGET_DATABASE) or {})
        required = (
            status.get("ok"),
            status.get("completeBackup"),
            status.get("backupReadback"),
            status.get("protectedReset"),
            status.get("rollback"),
            status.get("applicationLock"),
            status.get("separateAccountConnections"),
            status.get("noCrossDatabaseTenantRights"),
        )
        if not all(required):
            raise InstyleDemoRebuildUnavailableError(
                "protected demo restore workflow lacks backup, reset, rollback, lock, or isolation guarantees"
            )
        forbidden = {str(value).casefold() for value in (status.get("directOperations") or [])}
        if forbidden & {"delete", "drop", "alter", "disable_constraints", "cross_database_sql"}:
            raise InstyleDemoRebuildScopeError(
                "protected demo restore workflow advertises a forbidden direct database operation"
            )
        return status

    def _preview_path(self, idempotency_key: str) -> Path:
        return self._state_path("preview", idempotency_key)

    def _checkpoint_path(self, idempotency_key: str) -> Path:
        return self._state_path("checkpoint", idempotency_key)

    def _receipt_path(self, idempotency_key: str) -> Path:
        return self._state_path("receipt", idempotency_key)

    def _state_path(self, kind: str, idempotency_key: str) -> Path:
        digest = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()
        return self._state_dir / f"{kind}-{digest}.json"


def _capture_snapshot(
    connection: Any,
    company_username: str,
    expected_database: str,
    *,
    include_rows: bool,
    query_timeout_seconds: int,
    keep_transaction_open: bool = False,
    manage_transaction: bool = True,
) -> DatabaseSnapshot:
    _set_timeout(connection, query_timeout_seconds)
    cursor = connection.cursor()
    consistency_mode = "existing_transaction"
    if manage_transaction:
        try:
            connection.autocommit = True
        except Exception:
            pass
        _verify_database_binding(cursor, expected_database)
        cursor.execute(
            "SELECT snapshot_isolation_state FROM sys.databases WHERE name=DB_NAME()"
        )
        row = cursor.fetchone()
        consistency_mode = (
            "snapshot"
            if row and int(row[0] or 0) == 1
            else "serializable_capture"
        )
        cursor.execute(
            "SET TRANSACTION ISOLATION LEVEL "
            + ("SNAPSHOT" if consistency_mode == "snapshot" else "SERIALIZABLE")
        )
        try:
            connection.autocommit = False
        except Exception:
            pass
        cursor.execute("BEGIN TRANSACTION")
    schema_snapshot = _capture_schema(cursor, company_username, expected_database)
    rows_by_table: dict[str, list[dict[str, Any]]] = {}
    hashes: dict[str, str] = {}
    counts: dict[str, int] = {}
    streamed_tables: list[str] = []
    for table_key in sorted(schema_snapshot.tables):
        spec = schema_snapshot.tables[table_key]
        columns = spec.copyable_columns
        if spec.name.casefold() in STREAMED_TABLE_NAMES:
            count, data_hash = _capture_streamed_table_fingerprint(cursor, spec)
            counts[table_key] = count
            hashes[table_key] = data_hash
            streamed_tables.append(table_key)
            continue
        if not columns:
            rows: list[dict[str, Any]] = []
        else:
            select_columns = ", ".join(_quote_identifier(column.name) for column in columns)
            cursor.execute(f"SELECT {select_columns} FROM {_quote_table(spec.key)}")
            raw_rows = cursor.fetchall()
            if len(raw_rows) > MAX_SOURCE_ROWS:
                raise InstyleDemoRebuildScopeError(
                    f"required table {table_key} exceeds the operation-specific source row ceiling"
                )
            rows = [
                {column.name: raw[index] for index, column in enumerate(columns)}
                for raw in raw_rows
            ]
        row_values = sorted(_canonical_row_json(row) for row in rows)
        counts[table_key] = len(rows)
        hashes[table_key] = hashlib.sha256("\n".join(row_values).encode("utf-8")).hexdigest()
        if include_rows:
            rows_by_table[table_key] = rows
    snapshot_value = {
        "databaseName": expected_database,
        "schemaHash": schema_snapshot.schema_hash,
        "tables": [
            {"table": key, "rowCount": counts[key], "dataHash": hashes[key]}
            for key in sorted(schema_snapshot.tables)
        ],
    }
    snapshot_hash = _sha256_json(snapshot_value)
    if manage_transaction and (
        not keep_transaction_open or consistency_mode == "serializable_capture"
    ):
        try:
            connection.rollback()
        except Exception as exc:
            if consistency_mode == "serializable_capture":
                try:
                    connection.close()
                except Exception:
                    pass
                raise InstyleDemoRebuildUnavailableError(
                    "serializable source capture could not release its read transaction"
                ) from exc
    return DatabaseSnapshot(
        company_username=company_username,
        database_name=expected_database,
        captured_at=datetime.now(timezone.utc).isoformat(),
        schema_hash=schema_snapshot.schema_hash,
        snapshot_hash=snapshot_hash,
        tables=schema_snapshot.tables,
        table_hashes=hashes,
        row_counts=counts,
        consistency_mode=consistency_mode,
        streamed_tables=tuple(streamed_tables),
        rows=rows_by_table,
    )


def _capture_streamed_table_fingerprint(
    cursor: Any,
    spec: TableSpec,
) -> tuple[int, str]:
    if not spec.primary_key:
        raise InstyleDemoRebuildScopeError(
            f"streamed table {spec.key} requires a declared primary key"
        )
    bucket_columns = ", ".join(
        _quote_identifier(column.name) for column in spec.primary_key
    )
    value_columns = ", ".join(
        _quote_identifier(column.name) for column in spec.copyable_columns
    )
    cursor.execute(
        "SELECT (CONVERT(bigint,CHECKSUM(" + bucket_columns + ")) & 4095) AS Bucket,"
        "COUNT_BIG(*) AS BucketRows,"
        "CHECKSUM_AGG(BINARY_CHECKSUM(" + value_columns + ")) AS BucketChecksum "
        f"FROM {_quote_table(spec.key)} "
        "GROUP BY (CONVERT(bigint,CHECKSUM(" + bucket_columns + ")) & 4095) "
        "ORDER BY Bucket"
    )
    buckets = [
        {
            "bucket": int(row[0] or 0),
            "rowCount": int(row[1] or 0),
            "checksum": int(row[2] or 0),
        }
        for row in cursor.fetchall()
    ]
    return (
        sum(int(value["rowCount"]) for value in buckets),
        _sha256_json(
            {
                "version": 1,
                "mode": "sql-bucket-checksum-4096",
                "table": spec.key,
                "buckets": buckets,
            }
        ),
    )


def _stage_streamed_tables(
    *,
    connect: Callable[[str, bool], Any],
    target_connection: Any,
    source_a: DatabaseSnapshot,
    source_b: DatabaseSnapshot,
    target: DatabaseSnapshot,
    dataset: MergeDataset,
    preview: dict[str, Any],
    plan_hash: str,
    query_timeout_seconds: int,
) -> tuple[dict[str, list[str]], int]:
    if not dataset.streamed_tables:
        return {}, 0
    target_cursor = target_connection.cursor()
    stage_tables: dict[str, list[str]] = {}
    expected_orphan_rows = 0
    sources = (
        (SOURCE_A_USERNAME, SOURCE_A_DATABASE, source_a, preview["sourceA"], "a"),
        (SOURCE_B_USERNAME, SOURCE_B_DATABASE, source_b, preview["sourceB"], "b"),
    )
    for target_key in dataset.streamed_tables:
        target_spec = target.tables[target_key]
        if len(target_spec.primary_key) != 1:
            raise InstyleDemoRebuildScopeError(
                f"streamed table {target_key} requires one declared primary key"
            )
        primary_key = target_spec.primary_key[0]
        columns = list(target_spec.copyable_columns)
        if not columns:
            raise InstyleDemoRebuildScopeError(
                f"streamed table {target_key} has no copyable columns"
            )
        stage_tables[target_key] = []
        for source_name, expected_database, source, source_manifest, source_tag in sources:
            source_key = next(
                (
                    key
                    for key in source.tables
                    if key.casefold() == target_key.casefold()
                ),
                None,
            )
            if source_key is None:
                continue
            source_spec = source.tables[source_key]
            manifest_table = next(
                (
                    dict(value)
                    for value in source_manifest.get("tables") or []
                    if str(value.get("table") or "").casefold()
                    == source_key.casefold()
                ),
                None,
            )
            if manifest_table is None:
                raise InstyleDemoRebuildUnavailableError(
                    "streamed source table is absent from the immutable preview"
                )
            expected_count = int(manifest_table.get("rowCount", -1))
            expected_hash = str(manifest_table.get("dataHash") or "")
            stage_table = _stage_table_identifier(
                target_key,
                plan_hash,
                source_tag,
            )
            stage_tables[target_key].append(stage_table)
            stage_count = _table_row_count_optional(target_cursor, stage_table)
            if stage_count is None:
                target_cursor.execute(
                    "SELECT TOP (0) "
                    + ", ".join(_quote_identifier(column.name) for column in columns)
                    + f" INTO {_quote_table(stage_table)} "
                    + f"FROM {_quote_table(target_key)}"
                )
                target_connection.commit()
                stage_count = 0
            if stage_count > expected_count:
                raise InstyleDemoRebuildUnavailableError(
                    "streamed staging table exceeds its immutable source count"
                )
            if stage_count == expected_count:
                expected_orphan_rows += _stage_expected_product_orphan_count(
                    target_cursor,
                    stage_table,
                    target_spec,
                )
                continue

            source_connection = connect(source_name, True)
            try:
                _set_timeout(source_connection, query_timeout_seconds)
                source_cursor = source_connection.cursor()
                try:
                    source_connection.autocommit = True
                except Exception:
                    pass
                _verify_database_binding(source_cursor, expected_database)
                source_cursor.execute("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
                try:
                    source_connection.autocommit = False
                except Exception:
                    pass
                source_cursor.execute("BEGIN TRANSACTION")
                count, data_hash = _capture_streamed_table_fingerprint(
                    source_cursor,
                    source_spec,
                )
                if count != expected_count or data_hash != expected_hash:
                    raise InstyleDemoRebuildScopeError(
                        f"{source_name} streamed source changed after preview"
                    )

                source_primary_key = source_spec.primary_key[0]
                start_source_id = 0
                if stage_count:
                    row = target_cursor.execute(
                        f"SELECT MAX({_quote_identifier(primary_key.name)}) "
                        f"FROM {_quote_table(stage_table)}"
                    ).fetchone()
                    staged_max = int(row[0] or 0) if row else 0
                    start_source_id = (
                        staged_max - SOURCE_B_ID_OFFSET
                        if source_name == SOURCE_B_USERNAME
                        else staged_max
                    )
                    prefix_count = source_cursor.execute(
                        f"SELECT COUNT_BIG(*) FROM {_quote_table(source_key)} "
                        f"WHERE {_quote_identifier(source_primary_key.name)}<=?",
                        [start_source_id],
                    ).fetchone()
                    if not prefix_count or int(prefix_count[0] or 0) != stage_count:
                        raise InstyleDemoRebuildUnavailableError(
                            "streamed staging checkpoint does not match the source prefix"
                        )

                select_sql = (
                    "SELECT "
                    + ", ".join(_quote_identifier(column.name) for column in source_spec.copyable_columns)
                    + f" FROM {_quote_table(source_key)} "
                    + f"WHERE {_quote_identifier(source_primary_key.name)}>? "
                    + f"ORDER BY {_quote_identifier(source_primary_key.name)}"
                )
                source_cursor.execute(select_sql, [start_source_id])
                insert_sql = (
                    f"INSERT INTO {_quote_table(stage_table)} "
                    f"({', '.join(_quote_identifier(column.name) for column in columns)}) "
                    f"VALUES ({', '.join('?' for _ in columns)})"
                )
                try:
                    target_cursor.fast_executemany = True
                except Exception:
                    pass
                target_cursor.execute(
                    f"SET IDENTITY_INSERT {_quote_table(stage_table)} ON"
                )
                inserted_since_commit = 0
                try:
                    while True:
                        raw_rows = source_cursor.fetchmany(STREAM_BATCH_ROWS)
                        if not raw_rows:
                            break
                        values: list[tuple[Any, ...]] = []
                        for raw in raw_rows:
                            source_row = {
                                column.name: raw[index]
                                for index, column in enumerate(source_spec.copyable_columns)
                            }
                            transformed = _transform_row(
                                source_name,
                                source_row,
                                source_spec,
                                target_spec,
                                dataset.product_map,
                            )
                            transformed.pop("__expectedProductOrphan", False)
                            values.append(
                                tuple(
                                    _row_value(transformed, column.name)
                                    for column in columns
                                )
                            )
                        target_cursor.executemany(insert_sql, values)
                        inserted_since_commit += len(values)
                        if inserted_since_commit >= 100_000:
                            target_connection.commit()
                            inserted_since_commit = 0
                    target_cursor.execute(
                        f"SET IDENTITY_INSERT {_quote_table(stage_table)} OFF"
                    )
                    target_connection.commit()
                except Exception:
                    try:
                        target_connection.rollback()
                    except Exception:
                        pass
                    raise
                final_count = _table_row_count_optional(target_cursor, stage_table)
                if final_count != expected_count:
                    raise InstyleDemoRebuildUnavailableError(
                        "streamed staging row count did not match the immutable source"
                    )
                expected_orphan_rows += _stage_expected_product_orphan_count(
                    target_cursor,
                    stage_table,
                    target_spec,
                )
            finally:
                try:
                    source_connection.rollback()
                except Exception:
                    pass
                try:
                    source_connection.close()
                except Exception:
                    pass
    return stage_tables, expected_orphan_rows


def _stage_table_identifier(
    target_table: str,
    plan_hash: str,
    source_tag: str,
) -> str:
    table_digest = hashlib.sha256(target_table.casefold().encode("utf-8")).hexdigest()[:10]
    return (
        "dbo.__nova_rebuild_stage_"
        f"{plan_hash[:10]}_{source_tag}_{table_digest}"
    )


def _stage_expected_product_orphan_count(
    cursor: Any,
    stage_table: str,
    spec: TableSpec,
) -> int:
    column_name = PRODUCT_REFERENCE_COLUMNS.get(spec.name.casefold())
    if not column_name or not _has_column(spec, column_name):
        return 0
    actual = next(
        column.name
        for column in spec.columns
        if column.name.casefold() == column_name
    )
    row = cursor.execute(
        f"SELECT COUNT_BIG(*) FROM {_quote_table(stage_table)} "
        f"WHERE {_quote_identifier(actual)}>-2000000000 "
        f"AND {_quote_identifier(actual)}<-1"
    ).fetchone()
    return int(row[0] or 0) if row else 0


def _table_row_count_optional(cursor: Any, table_key: str) -> int | None:
    row = cursor.execute(
        "SELECT CASE WHEN OBJECT_ID(?, 'U') IS NULL THEN 0 ELSE 1 END",
        [table_key],
    ).fetchone()
    if not row or int(row[0] or 0) != 1:
        return None
    row = cursor.execute(
        f"SELECT COUNT_BIG(*) FROM {_quote_table(table_key)}"
    ).fetchone()
    return int(row[0] or 0)


def _capture_schema(cursor: Any, company_username: str, expected_database: str) -> DatabaseSnapshot:
    _verify_database_binding(cursor, expected_database)
    cursor.execute(
        "SELECT s.name,t.name,c.name,c.column_id,LOWER(ty.name),c.is_nullable,c.is_identity,"
        "c.is_computed,c.generated_always_type,CASE WHEN dc.object_id IS NULL THEN 0 ELSE 1 END,"
        "ISNULL(pk.key_ordinal,0) "
        "FROM sys.tables t JOIN sys.schemas s ON s.schema_id=t.schema_id "
        "JOIN sys.columns c ON c.object_id=t.object_id "
        "JOIN sys.types ty ON ty.user_type_id=c.user_type_id "
        "LEFT JOIN sys.default_constraints dc ON dc.object_id=c.default_object_id "
        "LEFT JOIN (SELECT ic.object_id,ic.column_id,ic.key_ordinal FROM sys.indexes i "
        "JOIN sys.index_columns ic ON ic.object_id=i.object_id AND ic.index_id=i.index_id "
        "WHERE i.is_primary_key=1) pk ON pk.object_id=c.object_id AND pk.column_id=c.column_id "
        "WHERE t.is_ms_shipped=0 ORDER BY s.name,t.name,c.column_id"
    )
    column_rows = list(cursor.fetchall())
    cursor.execute(
        "SELECT ps.name,pt.name,pc.name,rs.name,rt.name,rc.name "
        "FROM sys.foreign_key_columns fkc "
        "JOIN sys.tables pt ON pt.object_id=fkc.parent_object_id "
        "JOIN sys.schemas ps ON ps.schema_id=pt.schema_id "
        "JOIN sys.columns pc ON pc.object_id=pt.object_id AND pc.column_id=fkc.parent_column_id "
        "JOIN sys.tables rt ON rt.object_id=fkc.referenced_object_id "
        "JOIN sys.schemas rs ON rs.schema_id=rt.schema_id "
        "JOIN sys.columns rc ON rc.object_id=rt.object_id AND rc.column_id=fkc.referenced_column_id "
        "ORDER BY ps.name,pt.name,fkc.constraint_column_id"
    )
    foreign_key_rows = list(cursor.fetchall())
    columns_by_table: dict[str, list[ColumnSpec]] = {}
    table_names: dict[str, tuple[str, str]] = {}
    for row in column_rows:
        schema, table = str(row[0]), str(row[1])
        if _internal_table(table) or (
            expected_database != TARGET_DATABASE
            and table.casefold() in EXCLUDED_DIAGNOSTIC_TABLE_NAMES
        ):
            continue
        _require_identifier(schema)
        _require_identifier(table)
        _require_identifier(str(row[2]))
        key = f"{schema}.{table}"
        table_names[key.casefold()] = (schema, table)
        columns_by_table.setdefault(key.casefold(), []).append(
            ColumnSpec(
                name=str(row[2]),
                ordinal=int(row[3]),
                type_name=str(row[4]),
                nullable=bool(row[5]),
                identity=bool(row[6]),
                computed=bool(row[7]),
                generated=bool(row[8]),
                has_default=bool(row[9]),
                primary_key_ordinal=int(row[10] or 0),
            )
        )
    foreign_keys: dict[str, list[ForeignKeySpec]] = {}
    for row in foreign_key_rows:
        parent_key = f"{row[0]}.{row[1]}".casefold()
        referenced_key = f"{row[3]}.{row[4]}"
        if (
            parent_key not in columns_by_table
            or _internal_table(str(row[4]))
            or (
                expected_database != TARGET_DATABASE
                and str(row[4]).casefold() in EXCLUDED_DIAGNOSTIC_TABLE_NAMES
            )
        ):
            continue
        foreign_keys.setdefault(parent_key, []).append(
            ForeignKeySpec(
                column=str(row[2]),
                referenced_table=referenced_key,
                referenced_column=str(row[5]),
            )
        )
    tables = {
        f"{schema}.{table}": TableSpec(
            schema=schema,
            name=table,
            columns=tuple(sorted(columns_by_table[key], key=lambda column: column.ordinal)),
            foreign_keys=tuple(foreign_keys.get(key, [])),
        )
        for key, (schema, table) in table_names.items()
    }
    schema_hash = _sha256_json(
        {"databaseName": expected_database, "tables": [_table_schema_value(tables[key]) for key in sorted(tables)]}
    )
    return DatabaseSnapshot(
        company_username=company_username,
        database_name=expected_database,
        captured_at=datetime.now(timezone.utc).isoformat(),
        schema_hash=schema_hash,
        snapshot_hash="",
        tables=tables,
        table_hashes={key: "" for key in tables},
        row_counts={key: 0 for key in tables},
    )


def _validate_schema_contract(
    source_a: DatabaseSnapshot,
    source_b: DatabaseSnapshot,
    target: DatabaseSnapshot,
) -> list[str]:
    required_lookup: dict[str, str] = {}
    for source in (source_a, source_b):
        for key in source.tables:
            required_lookup.setdefault(key.casefold(), key)
    required = sorted(required_lookup.values(), key=str.casefold)
    target_lookup = {key.casefold(): key for key in target.tables}
    errors: list[str] = []
    for key in required:
        if key.casefold() not in target_lookup:
            errors.append(
                f"required source table {key} is missing from the demo target"
            )
            continue
        target_spec = target.tables[target_lookup[key.casefold()]]
        for source in (source_a, source_b):
            source_key = next((candidate for candidate in source.tables if candidate.casefold() == key.casefold()), None)
            if source_key is None:
                continue
            source_spec = source.tables[source_key]
            target_columns = {column.name.casefold(): column for column in target_spec.copyable_columns}
            for column in source_spec.copyable_columns:
                target_column = target_columns.get(column.name.casefold())
                if target_column is None:
                    if _is_fixed_target_schema_omission(
                        source,
                        source_spec,
                        column,
                    ):
                        continue
                    errors.append(
                        f"required source column {source_spec.key}.{column.name} "
                        "is missing from the demo target"
                    )
                    continue
                if target_column.type_name.casefold() != column.type_name.casefold():
                    errors.append(
                        f"required source column {source_spec.key}.{column.name} "
                        "has a changed target type"
                    )
    if errors:
        raise InstyleDemoRebuildScopeError("; ".join(errors))
    for snapshot in (source_a, source_b, target):
        products = _find_table(snapshot, PRODUCT_TABLE_NAME)
        invoice_products = _find_table(snapshot, INVOICE_PRODUCTS_TABLE_NAME)
        for column_name in ("ProductID", *PRODUCT_KEY_COLUMNS):
            if not _has_column(products, column_name):
                raise InstyleDemoRebuildScopeError(
                    f"{snapshot.database_name} Products is missing required column {column_name}"
                )
        for column_name in ("InvoiceID", "ProductID"):
            if not _has_column(invoice_products, column_name):
                raise InstyleDemoRebuildScopeError(
                    f"{snapshot.database_name} Invoice_Products is missing required column {column_name}"
                )
    return required


def _is_fixed_target_schema_omission(
    source: DatabaseSnapshot,
    source_spec: TableSpec,
    column: ColumnSpec,
) -> bool:
    key = (
        source.company_username.casefold(),
        source_spec.key.casefold(),
        column.name.casefold(),
    )
    contract = FIXED_TARGET_SCHEMA_OMISSIONS.get(key)
    if contract is None:
        return False
    foreign_key_columns = {
        foreign_key.column.casefold()
        for foreign_key in source_spec.foreign_keys
    }
    if (
        column.type_name.casefold() != str(contract["sourceType"]).casefold()
        or column.nullable is not bool(contract["nullable"])
        or column.identity
        or column.computed
        or column.generated
        or column.primary_key_ordinal
        or column.name.casefold() in foreign_key_columns
    ):
        raise InstyleDemoRebuildScopeError(
            "fixed source-only column "
            f"{source.company_username}/{source_spec.key}.{column.name} "
            "changed type, nullability, key, identity, computed, or foreign-key role"
        )
    return True


def _fixed_target_schema_omissions(
    source_a: DatabaseSnapshot,
    source_b: DatabaseSnapshot,
    target: DatabaseSnapshot,
) -> list[dict[str, Any]]:
    target_lookup = {key.casefold(): key for key in target.tables}
    omissions: list[dict[str, Any]] = []
    for source in (source_a, source_b):
        for source_spec in source.tables.values():
            target_key = target_lookup.get(source_spec.key.casefold())
            if target_key is None:
                continue
            target_columns = {
                column.name.casefold()
                for column in target.tables[target_key].copyable_columns
            }
            source_rows = source.rows.get(source_spec.key, [])
            for column in source_spec.copyable_columns:
                if column.name.casefold() in target_columns:
                    continue
                if not _is_fixed_target_schema_omission(
                    source,
                    source_spec,
                    column,
                ):
                    continue
                omissions.append(
                    {
                        "sourceCompanyUsername": source.company_username,
                        "sourceDatabaseName": source.database_name,
                        "table": source_spec.key,
                        "column": column.name,
                        "sourceType": str(
                            FIXED_TARGET_SCHEMA_OMISSIONS[
                                (
                                    source.company_username.casefold(),
                                    source_spec.key.casefold(),
                                    column.name.casefold(),
                                )
                            ]["sourceType"]
                        ),
                        "nullable": column.nullable,
                        "sourceRowCount": int(
                            source.row_counts.get(source_spec.key, len(source_rows))
                        ),
                        "populatedRowCount": sum(
                            1
                            for row in source_rows
                            if _row_value(row, column.name) is not None
                        ),
                        "targetDatabaseName": target.database_name,
                        "targetColumnPresent": False,
                        "copyBehavior": (
                            "The source rows and all matching Employees_Hours "
                            "columns remain in scope; OriginalHours values are not "
                            "copied because POS_DEMO_NOVA_CAFE has no such column."
                        ),
                    }
                )
    return sorted(
        omissions,
        key=lambda item: (
            str(item["sourceCompanyUsername"]).casefold(),
            str(item["table"]).casefold(),
            str(item["column"]).casefold(),
        ),
    )


def _build_merge_dataset(
    source_a: DatabaseSnapshot,
    source_b: DatabaseSnapshot,
    target: DatabaseSnapshot,
    required_tables: list[str],
) -> MergeDataset:
    target_products = _find_table(target, PRODUCT_TABLE_NAME)
    source_products_a = _find_table(source_a, PRODUCT_TABLE_NAME)
    source_products_b = _find_table(source_b, PRODUCT_TABLE_NAME)
    product_map, product_rows, dedupe_count = _build_product_rows(
        source_a.rows.get(source_products_a.key, []),
        source_b.rows.get(source_products_b.key, []),
        target_products,
    )
    placeholder_sources: list[tuple[str, int]] = []
    for source_name, source_snapshot in (
        (SOURCE_A_USERNAME, source_a),
        (SOURCE_B_USERNAME, source_b),
    ):
        source_invoice_products = _find_table(source_snapshot, INVOICE_PRODUCTS_TABLE_NAME)
        for source_row in source_snapshot.rows.get(source_invoice_products.key, []):
            product_id = _row_value(source_row, "ProductID")
            if product_id is None:
                continue
            original_id = _required_int(product_id, f"{source_invoice_products.key}.ProductID")
            if (source_name, original_id) not in product_map:
                placeholder_sources.append((source_name, original_id))
    placeholder_rows = _build_placeholder_products(
        placeholder_sources,
        product_map,
        product_rows,
        target_products,
    )
    product_rows.extend(placeholder_rows)
    rows: dict[str, list[dict[str, Any]]] = {}
    quarantine: list[dict[str, Any]] = []
    reconciliation: dict[str, dict[str, int]] = {}
    streamed_tables: list[str] = []
    expected_product_orphan_rows = 0
    target_lookup = {key.casefold(): key for key in target.tables}
    source_lookups = (
        (SOURCE_A_USERNAME, source_a, {key.casefold(): key for key in source_a.tables}),
        (SOURCE_B_USERNAME, source_b, {key.casefold(): key for key in source_b.tables}),
    )

    for required_key in required_tables:
        target_key = target_lookup[required_key.casefold()]
        target_spec = target.tables[target_key]
        if target_spec.name.casefold() == PRODUCT_TABLE_NAME:
            continue
        if target_spec.name.casefold() in STREAMED_TABLE_NAMES:
            source_count = sum(
                int(source_snapshot.row_counts.get(source_lookup.get(required_key.casefold(), ""), 0))
                for _source_name, source_snapshot, source_lookup in source_lookups
            )
            rows[target_key] = []
            reconciliation[target_key] = {
                "sourceRows": source_count,
                "targetRows": source_count,
                "quarantinedRows": 0,
                "deduplicatedRows": 0,
            }
            streamed_tables.append(target_key)
            continue
        merged: list[dict[str, Any]] = []
        source_count = 0
        quarantined = 0
        for source_name, source_snapshot, source_lookup in source_lookups:
            source_key = source_lookup.get(required_key.casefold())
            if source_key is None:
                continue
            source_spec = source_snapshot.tables[source_key]
            source_rows = source_snapshot.rows.get(source_key, [])
            source_count += len(source_rows)
            for source_row in source_rows:
                if (
                    target_spec.name.casefold() == INVOICE_PRODUCTS_TABLE_NAME
                    and _row_value(source_row, "InvoiceID") is None
                ):
                    quarantine.append(
                        {
                            "SourceCompanyUsername": source_name,
                            "OriginalRowJson": _canonical_row_json(source_row),
                            "RowHash": hashlib.sha256(_canonical_row_json(source_row).encode("utf-8")).hexdigest(),
                        }
                    )
                    quarantined += 1
                    continue
                transformed = _transform_row(
                    source_name,
                    source_row,
                    source_spec,
                    target_spec,
                    product_map,
                )
                if transformed.pop("__expectedProductOrphan", False):
                    expected_product_orphan_rows += 1
                merged.append(transformed)
        _require_unique_primary_keys(target_spec, merged)
        rows[target_key] = merged
        reconciliation[target_key] = {
            "sourceRows": source_count,
            "targetRows": len(merged),
            "quarantinedRows": quarantined,
            "deduplicatedRows": 0,
        }

    _require_unique_primary_keys(target_products, product_rows)
    rows[target_products.key] = product_rows
    source_product_count = len(source_a.rows.get(source_products_a.key, [])) + len(
        source_b.rows.get(source_products_b.key, [])
    )
    reconciliation[target_products.key] = {
        "sourceRows": source_product_count,
        "targetRows": len(product_rows),
        "quarantinedRows": 0,
        "deduplicatedRows": dedupe_count,
    }
    _validate_in_memory_orphans(rows, target)
    return MergeDataset(
        rows=rows,
        quarantine_rows=quarantine,
        reconciliation=reconciliation,
        product_mapping_count=len(product_map),
        placeholder_product_count=len(placeholder_rows),
        product_dedupe_count=dedupe_count,
        product_map=product_map,
        streamed_tables=tuple(streamed_tables),
        expected_product_orphan_rows=expected_product_orphan_rows,
    )


def _build_product_rows(
    source_a_rows: list[dict[str, Any]],
    source_b_rows: list[dict[str, Any]],
    target_spec: TableSpec,
) -> tuple[dict[tuple[str, int], int], list[dict[str, Any]], int]:
    grouped: dict[tuple[str, str, str, str], list[tuple[str, dict[str, Any]]]] = {}
    for source_name, source_rows in (
        (SOURCE_A_USERNAME, source_a_rows),
        (SOURCE_B_USERNAME, source_b_rows),
    ):
        for row in source_rows:
            product_id = _required_int(_row_value(row, "ProductID"), "ProductID")
            key = tuple(_normalize_product_value(_row_value(row, name)) for name in PRODUCT_KEY_COLUMNS)
            if not any(key):
                key = (f"__source__:{source_name.casefold()}:{product_id}", "", "", "")
            grouped.setdefault(key, []).append((source_name, row))

    all_ids = [
        _required_int(_row_value(row, "ProductID"), "ProductID")
        for values in grouped.values()
        for _, row in values
    ]
    next_id = max([0, *all_ids]) + 1
    used_ids: set[int] = set()
    mapping: dict[tuple[str, int], int] = {}
    winners: list[tuple[str, dict[str, Any], int]] = []
    source_priority = {SOURCE_A_USERNAME: 1, SOURCE_B_USERNAME: 0}
    for key in sorted(grouped):
        candidates = grouped[key]
        winner_source, winner = max(
            candidates,
            key=lambda item: (
                _required_int(_row_value(item[1], "ProductID"), "ProductID"),
                source_priority[item[0]],
                hashlib.sha256(_canonical_row_json(item[1]).encode("utf-8")).hexdigest(),
            ),
        )
        desired_id = _required_int(_row_value(winner, "ProductID"), "ProductID")
        target_id = desired_id
        if target_id in used_ids:
            while next_id in used_ids:
                next_id += 1
            target_id = next_id
            next_id += 1
        used_ids.add(target_id)
        winners.append((winner_source, winner, target_id))
        for source_name, row in candidates:
            original_id = _required_int(_row_value(row, "ProductID"), "ProductID")
            mapping[(source_name, original_id)] = target_id
    output = [
        _transform_product_winner_row(source_name, row, target_spec, target_id)
        for source_name, row, target_id in winners
    ]
    return mapping, output, sum(max(0, len(values) - 1) for values in grouped.values())


def _transform_product_winner_row(
    source_name: str,
    source_row: dict[str, Any],
    target_spec: TableSpec,
    target_id: int,
) -> dict[str, Any]:
    row = _project_row(source_row, target_spec)
    _set_row_value(row, "ProductID", target_id)
    if source_name != SOURCE_B_USERNAME:
        return row
    fk_by_column = {foreign_key.column.casefold(): foreign_key for foreign_key in target_spec.foreign_keys}
    for column in target_spec.columns:
        if column.name.casefold() == "productid" or not column.integer:
            continue
        foreign_key = fk_by_column.get(column.name.casefold())
        if foreign_key is None or foreign_key.referenced_table.rsplit(".", 1)[-1].casefold() == PRODUCT_TABLE_NAME:
            continue
        value = _row_value(row, column.name)
        if value is None:
            continue
        _set_row_value(
            row,
            column.name,
            _offset_source_b_id(value, column, f"{target_spec.key}.{column.name}"),
        )
    return row


def _build_placeholder_products(
    placeholder_sources: list[tuple[str, int]],
    product_map: dict[tuple[str, int], int],
    existing_products: list[dict[str, Any]],
    target_spec: TableSpec,
) -> list[dict[str, Any]]:
    missing = sorted(set(placeholder_sources), key=lambda value: (value[0].casefold(), value[1]))
    if not missing:
        return []
    existing_ids = {
        _required_int(_row_value(row, "ProductID"), "ProductID")
        for row in existing_products
    }
    next_id = max([0, *existing_ids]) + 1
    template = dict(existing_products[0]) if existing_products else {}
    output: list[dict[str, Any]] = []
    active_columns = [
        column.name
        for column in target_spec.columns
        if column.name.replace("_", "").casefold()
        in {
            "active",
            "isactive",
            "productactive",
            "productisavailable",
        }
    ]
    if not active_columns:
        raise InstyleDemoRebuildScopeError(
            "the target Products schema cannot guarantee inactive missing-product placeholders"
        )
    for source_name, original_id in missing:
        if (source_name, original_id) in product_map:
            continue
        while next_id in existing_ids:
            next_id += 1
        target_id = next_id
        existing_ids.add(target_id)
        next_id += 1
        row = _placeholder_row(template, target_spec)
        _set_row_value(row, "ProductID", target_id)
        _set_row_value(row, "ProductName", f"Inactive missing product [{source_name}:{original_id}]")
        for column_name in ("BarcodeNumber", "BarcodeNumber2"):
            if _has_column(target_spec, column_name):
                _set_row_value(row, column_name, "")
        if _has_column(target_spec, "SKU"):
            prefix = "LBI" if source_name == SOURCE_A_USERNAME else "IF"
            _set_row_value(row, "SKU", f"MISSING-{prefix}-{original_id}")
        for column_name in active_columns:
            _set_row_value(row, column_name, False)
        product_map[(source_name, original_id)] = target_id
        output.append(row)
    return output


def _transform_row(
    source_name: str,
    source_row: dict[str, Any],
    source_spec: TableSpec,
    target_spec: TableSpec,
    product_map: dict[tuple[str, int], int],
) -> dict[str, Any]:
    row = _project_row(source_row, target_spec)
    source_columns = {column.name.casefold(): column for column in source_spec.columns}
    target_columns = {column.name.casefold(): column for column in target_spec.columns}
    fk_by_column = {foreign_key.column.casefold(): foreign_key for foreign_key in target_spec.foreign_keys}
    pk_names = {column.name.casefold() for column in target_spec.primary_key}
    fixed_product_column = PRODUCT_REFERENCE_COLUMNS.get(target_spec.name.casefold())
    for name, target_column in target_columns.items():
        if name not in {key.casefold() for key in row}:
            continue
        current = _row_value(row, target_column.name)
        if current is None:
            continue
        foreign_key = fk_by_column.get(name)
        refers_to_products = bool(
            foreign_key and foreign_key.referenced_table.rsplit(".", 1)[-1].casefold() == PRODUCT_TABLE_NAME
        )
        is_product_id = (
            name == fixed_product_column
            or (
                name == "productid"
                and (
                    refers_to_products
                    or target_spec.name.casefold() == INVOICE_PRODUCTS_TABLE_NAME
                )
            )
        )
        if is_product_id:
            original_id = _required_int(current, f"{target_spec.key}.{target_column.name}")
            if original_id <= 0:
                continue
            mapped = product_map.get((source_name, original_id))
            if mapped is None:
                if target_spec.name.casefold() == INVOICE_PRODUCTS_TABLE_NAME:
                    raise InstyleDemoRebuildScopeError(
                        f"source-qualified product mapping is missing for {source_name}:{original_id}"
                    )
                mapped = _expected_orphan_product_reference(source_name, original_id)
                row["__expectedProductOrphan"] = True
            _set_row_value(row, target_column.name, mapped)
            continue
        source_column = source_columns.get(name)
        identity_like = name in pk_names or foreign_key is not None
        if (
            source_name == SOURCE_B_USERNAME
            and identity_like
            and source_column is not None
            and source_column.integer
            and not refers_to_products
        ):
            _set_row_value(
                row,
                target_column.name,
                _offset_source_b_id(
                    current,
                    target_column,
                    f"{target_spec.key}.{target_column.name}",
                ),
            )
    return row


def _expected_orphan_product_reference(source_name: str, original_id: int) -> int:
    if not 0 < original_id < 1_000_000_000:
        raise InstyleDemoRebuildScopeError(
            "source product exception cannot be encoded inside the fixed SQL int ranges"
        )
    base = -2_000_000_000 if source_name == SOURCE_A_USERNAME else -1_000_000_000
    mapped = base + original_id
    if mapped >= 0 or mapped in {-1, 0}:
        raise InstyleDemoRebuildScopeError(
            "source product exception collided with a reserved sentinel"
        )
    return mapped


def _offset_source_b_id(value: Any, column: ColumnSpec, label: str) -> int:
    original = _required_int(value, label)
    if original in {-1, 0}:
        return original
    mapped = original + SOURCE_B_ID_OFFSET
    if column.type_name.casefold() == "int" and not -(2**31) <= mapped < 2**31:
        raise InstyleDemoRebuildScopeError(f"source B ID offset overflows {label}")
    return mapped


def _validate_in_memory_orphans(rows: dict[str, list[dict[str, Any]]], target: DatabaseSnapshot) -> None:
    row_lookup = {key.casefold(): value for key, value in rows.items()}
    table_lookup = {key.casefold(): value for key, value in target.tables.items()}
    for table_key, table_rows in rows.items():
        spec = target.tables[table_key]
        for foreign_key in spec.foreign_keys:
            parent_key = foreign_key.referenced_table.casefold()
            if parent_key not in row_lookup or parent_key not in table_lookup:
                continue
            parent_values = {
                _row_value(row, foreign_key.referenced_column)
                for row in row_lookup[parent_key]
            }
            for row in table_rows:
                value = _row_value(row, foreign_key.column)
                if value is not None and value not in parent_values:
                    raise InstyleDemoRebuildScopeError(
                        f"source-qualified mapping leaves an orphan in {table_key}.{foreign_key.column}"
                    )


def _validate_reconciliation(dataset: MergeDataset, preview: dict[str, Any]) -> None:
    if dataset.reconciliation != preview.get("reconciliation"):
        raise InstyleDemoRebuildScopeError("source reconciliation changed after preview")
    if dataset.product_mapping_count != int(preview.get("productMappingCount", -1)):
        raise InstyleDemoRebuildScopeError("source-qualified product mapping changed after preview")
    if dataset.placeholder_product_count != int(preview.get("placeholderProductCount", -1)):
        raise InstyleDemoRebuildScopeError("missing-product placeholder plan changed after preview")
    if len(dataset.quarantine_rows) != int(preview.get("quarantineRowCount", -1)):
        raise InstyleDemoRebuildScopeError("NULL InvoiceID quarantine plan changed after preview")
    if dataset.expected_product_orphan_rows != int(
        preview.get("expectedProductOrphanRowsBeforeStreaming", -1)
    ):
        raise InstyleDemoRebuildScopeError(
            "source-baseline product exception plan changed after preview"
        )


def _load_target_dataset(
    cursor: Any,
    target: DatabaseSnapshot,
    required_tables: list[str],
    dataset: MergeDataset,
    plan_hash: str,
    *,
    streamed_stage_tables: dict[str, list[str]] | None = None,
) -> str:
    streamed_stage_tables = streamed_stage_tables or {}
    ordered, cyclic_foreign_keys = _dependency_order(target, required_tables)
    deferred_values: list[dict[str, Any]] = []
    for table_key, column_name in cyclic_foreign_keys:
        spec = target.tables[table_key]
        primary_key = spec.primary_key
        if not primary_key:
            raise InstyleDemoRebuildScopeError(
                f"cyclic table {table_key} needs a primary key for bounded deferred updates"
            )
        for row in dataset.rows.get(table_key, []):
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
                        for column in primary_key
                    ],
                }
            )
            _set_row_value(row, column_name, None)
    for table_key in ordered:
        stages = streamed_stage_tables.get(table_key, [])
        if stages:
            spec = target.tables[table_key]
            columns = list(spec.copyable_columns)
            identity = spec.identity_column
            if identity is not None:
                cursor.execute(f"SET IDENTITY_INSERT {_quote_table(table_key)} ON")
            try:
                for stage_table in stages:
                    cursor.execute(
                        f"INSERT INTO {_quote_table(table_key)} "
                        f"({', '.join(_quote_identifier(column.name) for column in columns)}) "
                        "SELECT "
                        + ", ".join(_quote_identifier(column.name) for column in columns)
                        + f" FROM {_quote_table(stage_table)}"
                    )
            finally:
                if identity is not None:
                    cursor.execute(f"SET IDENTITY_INSERT {_quote_table(table_key)} OFF")
            continue
        rows = dataset.rows.get(table_key, [])
        if not rows:
            continue
        spec = target.tables[table_key]
        columns = [column for column in spec.copyable_columns if any(_has_row_key(row, column.name) for row in rows)]
        if not columns:
            continue
        identity = spec.identity_column
        if identity is not None and any(_has_row_key(row, identity.name) for row in rows):
            cursor.execute(f"SET IDENTITY_INSERT {_quote_table(table_key)} ON")
        try:
            sql = (
                f"INSERT INTO {_quote_table(table_key)} "
                f"({', '.join(_quote_identifier(column.name) for column in columns)}) "
                f"VALUES ({', '.join('?' for _ in columns)})"
            )
            values = [
                tuple(_row_value(row, column.name) for column in columns)
                for row in rows
            ]
            for start in range(0, len(values), MAX_BATCH_ROWS):
                cursor.executemany(sql, values[start : start + MAX_BATCH_ROWS])
        finally:
            if identity is not None and any(_has_row_key(row, identity.name) for row in rows):
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
    dataset.deferred_updates.extend(deferred_values)

    quarantine_table = f"dbo.__codex_quarantine_invoice_products_{plan_hash[:12]}"
    if dataset.quarantine_rows:
        cursor.execute(
            f"CREATE TABLE {_quote_table(quarantine_table)} ("
            "[SourceCompanyUsername] nvarchar(80) NOT NULL,"
            "[OriginalRowJson] nvarchar(max) NOT NULL,"
            "[RowHash] char(64) NOT NULL,"
            "[QuarantinedAtUtc] datetime2(7) NOT NULL"
            ")"
        )
        cursor.executemany(
            f"INSERT INTO {_quote_table(quarantine_table)} "
            "([SourceCompanyUsername],[OriginalRowJson],[RowHash],[QuarantinedAtUtc]) VALUES (?,?,?,?)",
            [
                (
                    row["SourceCompanyUsername"],
                    row["OriginalRowJson"],
                    row["RowHash"],
                    datetime.now(timezone.utc),
                )
                for row in dataset.quarantine_rows
            ],
        )
    return quarantine_table


def _readback_target_dataset(
    cursor: Any,
    target: DatabaseSnapshot,
    required_tables: list[str],
    dataset: MergeDataset,
    quarantine_table: str,
) -> dict[str, Any]:
    table_counts: dict[str, int] = {}
    for table_key in required_tables:
        target_key = next(key for key in target.tables if key.casefold() == table_key.casefold())
        row = cursor.execute(f"SELECT COUNT_BIG(*) FROM {_quote_table(target_key)}").fetchone()
        count = int(row[0] or 0) if row else 0
        expected = int(
            dataset.reconciliation.get(target_key, {}).get(
                "targetRows",
                len(dataset.rows.get(target_key, [])),
            )
        )
        if count != expected:
            raise InstyleDemoRebuildScopeError(f"post-write row reconciliation failed for {target_key}")
        table_counts[target_key] = count
    quarantine_count = 0
    if dataset.quarantine_rows:
        row = cursor.execute(f"SELECT COUNT_BIG(*) FROM {_quote_table(quarantine_table)}").fetchone()
        quarantine_count = int(row[0] or 0) if row else 0
        if quarantine_count != len(dataset.quarantine_rows):
            raise InstyleDemoRebuildScopeError("post-write quarantine reconciliation failed")
    expected_product_orphan_rows = _validate_sql_duplicates_and_orphans(
        cursor,
        target,
        required_tables,
        dataset,
    )
    return {
        "tableCounts": table_counts,
        "quarantineRowCount": quarantine_count,
        "duplicatePrimaryKeys": 0,
        "orphanForeignKeys": 0,
        "expectedProductOrphanRows": expected_product_orphan_rows,
        "unexpectedProductOrphanRows": 0,
        "sourceReconciliationVerified": True,
    }


def _validate_sql_duplicates_and_orphans(
    cursor: Any,
    target: DatabaseSnapshot,
    required_tables: list[str],
    dataset: MergeDataset,
) -> int:
    required_lookup = {key.casefold(): key for key in required_tables}
    for table_key in required_tables:
        target_key = next(key for key in target.tables if key.casefold() == table_key.casefold())
        spec = target.tables[target_key]
        primary_key = spec.primary_key
        if primary_key:
            columns = ", ".join(_quote_identifier(column.name) for column in primary_key)
            row = cursor.execute(
                f"SELECT COUNT_BIG(*) FROM (SELECT {columns} FROM {_quote_table(target_key)} "
                f"GROUP BY {columns} HAVING COUNT_BIG(*) > 1) AS d"
            ).fetchone()
            if row and int(row[0] or 0):
                raise InstyleDemoRebuildScopeError(f"duplicate primary-key validation failed for {target_key}")
        for foreign_key in spec.foreign_keys:
            parent_key = required_lookup.get(foreign_key.referenced_table.casefold())
            if parent_key is None:
                continue
            row = cursor.execute(
                f"SELECT COUNT_BIG(*) FROM {_quote_table(target_key)} AS c "
                f"LEFT JOIN {_quote_table(parent_key)} AS p "
                f"ON p.{_quote_identifier(foreign_key.referenced_column)}="
                f"c.{_quote_identifier(foreign_key.column)} "
                f"WHERE c.{_quote_identifier(foreign_key.column)} IS NOT NULL "
                f"AND p.{_quote_identifier(foreign_key.referenced_column)} IS NULL"
            ).fetchone()
            if row and int(row[0] or 0):
                raise InstyleDemoRebuildScopeError(
                    f"orphan foreign-key validation failed for {target_key}.{foreign_key.column}"
                )
    products_key = next(
        key
        for key in target.tables
        if target.tables[key].name.casefold() == PRODUCT_TABLE_NAME
    )
    required_casefold = {key.casefold() for key in required_tables}
    expected_product_orphans = 0
    for table_name, column_name in PRODUCT_REFERENCE_COLUMNS.items():
        target_key = next(
            (
                key
                for key, spec in target.tables.items()
                if key.casefold() in required_casefold
                and spec.name.casefold() == table_name
            ),
            None,
        )
        if target_key is None or not _has_column(target.tables[target_key], column_name):
            continue
        spec = target.tables[target_key]
        actual_column = next(
            column.name
            for column in spec.columns
            if column.name.casefold() == column_name
        )
        unexpected = cursor.execute(
            f"SELECT COUNT_BIG(*) FROM {_quote_table(target_key)} AS c "
            f"LEFT JOIN {_quote_table(products_key)} AS p "
            f"ON p.[ProductID]=c.{_quote_identifier(actual_column)} "
            f"WHERE c.{_quote_identifier(actual_column)}>0 "
            "AND p.[ProductID] IS NULL"
        ).fetchone()
        if unexpected and int(unexpected[0] or 0):
            raise InstyleDemoRebuildScopeError(
                f"unexpected product orphan validation failed for {target_key}.{actual_column}"
            )
        expected = cursor.execute(
            f"SELECT COUNT_BIG(*) FROM {_quote_table(target_key)} AS c "
            f"LEFT JOIN {_quote_table(products_key)} AS p "
            f"ON p.[ProductID]=c.{_quote_identifier(actual_column)} "
            f"WHERE c.{_quote_identifier(actual_column)}>-2000000000 "
            f"AND c.{_quote_identifier(actual_column)}<-1 "
            "AND p.[ProductID] IS NULL"
        ).fetchone()
        expected_product_orphans += int(expected[0] or 0) if expected else 0
    if expected_product_orphans != dataset.expected_product_orphan_rows:
        raise InstyleDemoRebuildScopeError(
            "source-baseline product exception readback changed after load"
        )
    return expected_product_orphans


def _dependency_order(
    target: DatabaseSnapshot,
    required_tables: list[str],
) -> tuple[list[str], list[tuple[str, str]]]:
    required_lookup = {key.casefold(): next(candidate for candidate in target.tables if candidate.casefold() == key.casefold()) for key in required_tables}
    dependencies: dict[str, set[str]] = {value: set() for value in required_lookup.values()}
    for table_key in dependencies:
        spec = target.tables[table_key]
        for foreign_key in spec.foreign_keys:
            parent = required_lookup.get(foreign_key.referenced_table.casefold())
            if parent and parent != table_key:
                dependencies[table_key].add(parent)
    ordered: list[str] = []
    deferred: list[tuple[str, str]] = []
    remaining = {key: set(value) for key, value in dependencies.items()}
    while remaining:
        ready = sorted((key for key, value in remaining.items() if not value), key=str.casefold)
        if not ready:
            cycle = sorted(remaining, key=str.casefold)
            cycle_lookup = {value.casefold() for value in cycle}
            for table_key in cycle:
                spec = target.tables[table_key]
                cycle_foreign_keys = [
                    foreign_key
                    for foreign_key in spec.foreign_keys
                    if foreign_key.referenced_table.casefold() in cycle_lookup
                ]
                for foreign_key in cycle_foreign_keys:
                    column = next(
                        column
                        for column in spec.columns
                        if column.name.casefold() == foreign_key.column.casefold()
                    )
                    if not column.nullable:
                        raise InstyleDemoRebuildScopeError(
                            f"required table cycle contains non-null foreign key {table_key}.{column.name}"
                        )
                    deferred.append((table_key, column.name))
            ordered.extend(cycle)
            break
        for key in ready:
            ordered.append(key)
            remaining.pop(key)
        for value in remaining.values():
            value.difference_update(ready)
    return ordered, deferred


def _placeholder_row(template: dict[str, Any], target_spec: TableSpec) -> dict[str, Any]:
    row = _project_row(template, target_spec)
    for column in target_spec.copyable_columns:
        if _has_row_key(row, column.name):
            continue
        if column.nullable or column.has_default or column.identity:
            continue
        _set_row_value(row, column.name, _neutral_value(column.type_name))
    return row


def _neutral_value(type_name: str) -> Any:
    lowered = type_name.casefold()
    if lowered in {"bigint", "decimal", "float", "int", "money", "numeric", "real", "smallint", "smallmoney", "tinyint"}:
        return 0
    if lowered == "bit":
        return False
    if lowered in {"binary", "image", "varbinary"}:
        return b""
    if lowered in {"date"}:
        return date(2000, 1, 1)
    if lowered in {"datetime", "datetime2", "smalldatetime"}:
        return datetime(2000, 1, 1, tzinfo=timezone.utc)
    if lowered == "time":
        return time(0, 0)
    if lowered == "uniqueidentifier":
        return UUID(int=0)
    return ""


def _project_row(source_row: dict[str, Any], target_spec: TableSpec) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for column in target_spec.copyable_columns:
        if _has_row_key(source_row, column.name):
            output[column.name] = _row_value(source_row, column.name)
        elif not (column.nullable or column.has_default or column.identity):
            output[column.name] = _neutral_value(column.type_name)
    return output


def _require_unique_primary_keys(spec: TableSpec, rows: list[dict[str, Any]]) -> None:
    if not spec.primary_key:
        return
    seen: set[tuple[Any, ...]] = set()
    for row in rows:
        key = tuple(_canonical_value(_row_value(row, column.name)) for column in spec.primary_key)
        if key in seen:
            raise InstyleDemoRebuildScopeError(f"source-qualified mapping creates duplicate key in {spec.key}")
        seen.add(key)


def _find_table(snapshot: DatabaseSnapshot, name: str) -> TableSpec:
    candidates = [table for table in snapshot.tables.values() if table.name.casefold() == name.casefold()]
    if len(candidates) != 1:
        raise InstyleDemoRebuildScopeError(f"expected exactly one {name} table in {snapshot.database_name}")
    return candidates[0]


def _require_snapshot_match(snapshot: DatabaseSnapshot, manifest: dict[str, Any], label: str) -> None:
    if snapshot.database_name.casefold() != str(manifest.get("databaseName") or "").casefold():
        raise InstyleDemoRebuildScopeError(f"{label} resolved to a changed database")
    if snapshot.schema_hash != manifest.get("schemaHash"):
        raise InstyleDemoRebuildScopeError(f"{label} schema changed after preview")
    if snapshot.snapshot_hash != manifest.get("snapshotHash"):
        raise InstyleDemoRebuildScopeError(f"{label} source snapshot changed after preview")


def _require_backup_receipt(receipt: dict[str, Any], *, expected_snapshot_hash: str) -> None:
    if not (
        receipt.get("ok")
        and receipt.get("complete")
        and receipt.get("readbackVerified")
        and receipt.get("rollbackAvailable")
        and receipt.get("snapshotHash") == expected_snapshot_hash
        and receipt.get("receiptId")
    ):
        raise InstyleDemoRebuildUnavailableError(
            "complete target backup or rollback availability was not verified before reset"
        )


def _require_backup_verification(verification: dict[str, Any], receipt: dict[str, Any]) -> None:
    if not (
        verification.get("ok")
        and verification.get("readbackVerified")
        and verification.get("rollbackAvailable")
        and verification.get("receiptId") == receipt.get("receiptId")
    ):
        raise InstyleDemoRebuildUnavailableError("protected target backup readback or rollback is unavailable")


def _require_reset_receipt(receipt: dict[str, Any], *, expected_schema_hash: str) -> None:
    if not (
        receipt.get("ok")
        and receipt.get("reset")
        and receipt.get("readbackVerified")
        and receipt.get("targetReadyForLoad")
        and receipt.get("schemaHash") == expected_schema_hash
    ):
        raise InstyleDemoRebuildUnavailableError("protected demo reset did not return exact readiness readback")
    direct = {str(value).casefold() for value in (receipt.get("directOperations") or [])}
    if direct & {"delete", "drop", "alter", "disable_constraints", "cross_database_sql"}:
        raise InstyleDemoRebuildScopeError("protected demo reset used a forbidden direct operation")


def _require_rollback_receipt(receipt: dict[str, Any]) -> None:
    if not (
        receipt.get("ok")
        and receipt.get("restored")
        and receipt.get("readbackVerified")
        and str(receipt.get("receiptId") or "")
        and str(receipt.get("snapshotHash") or "")
    ):
        raise InstyleDemoRebuildUnavailableError(
            "protected rollback did not return verified target restoration"
        )


def _validate_checkpoint(checkpoint: dict[str, Any], idempotency_key: str, plan_hash: str) -> None:
    if not checkpoint:
        return
    if (
        checkpoint.get("operation") != OPERATION_NAME
        or checkpoint.get("idempotencyKey") != idempotency_key
        or checkpoint.get("planHash") != plan_hash
    ):
        raise InstyleDemoRebuildScopeError("idempotency key was used for a different rebuild checkpoint")
    if checkpoint.get("phase") == "rolled_back":
        raise InstyleDemoRebuildUnavailableError(
            "the prior attempt was rolled back; create a new preview and idempotency key"
        )


def _checkpoint(
    idempotency_key: str,
    plan_hash: str,
    phase: str,
    *,
    backup_receipt: dict[str, Any],
    reset_receipt: dict[str, Any] | None = None,
    rollback_receipt: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "version": 1,
        "operation": OPERATION_NAME,
        "phase": phase,
        "recordedAt": datetime.now(timezone.utc).isoformat(),
        "idempotencyKey": idempotency_key,
        "planHash": plan_hash,
        "backupReceipt": backup_receipt,
        "resetReceipt": reset_receipt or {},
        "rollbackReceipt": rollback_receipt or {},
    }


def _read_durable_receipt(cursor: Any, idempotency_key: str) -> dict[str, Any]:
    exists = cursor.execute(
        "SELECT CASE WHEN OBJECT_ID(?, 'U') IS NULL THEN 0 ELSE 1 END",
        [DURABLE_RECEIPT_TABLE],
    ).fetchone()
    if not exists or int(exists[0] or 0) != 1:
        return {}
    row = cursor.execute(
        f"SELECT [PlanHash],[Status],[ReadbackHash] FROM {_quote_table(DURABLE_RECEIPT_TABLE)} "
        "WHERE [IdempotencyKey]=?",
        [idempotency_key],
    ).fetchone()
    if not row:
        return {}
    return {
        "idempotencyKey": idempotency_key,
        "planHash": str(row[0] or ""),
        "status": str(row[1] or ""),
        "readbackHash": str(row[2] or ""),
    }


def _write_durable_receipt(
    cursor: Any,
    *,
    idempotency_key: str,
    plan_hash: str,
    readback_hash: str,
) -> None:
    cursor.execute(
        f"IF OBJECT_ID(N'{DURABLE_RECEIPT_TABLE}',N'U') IS NULL "
        f"CREATE TABLE {_quote_table(DURABLE_RECEIPT_TABLE)} ("
        "[IdempotencyKey] nvarchar(200) NOT NULL PRIMARY KEY,"
        "[PlanHash] char(64) NOT NULL,"
        "[Status] varchar(20) NOT NULL,"
        "[ReadbackHash] char(64) NOT NULL,"
        "[RecordedAtUtc] datetime2(7) NOT NULL"
        ")"
    )
    cursor.execute(
        f"INSERT INTO {_quote_table(DURABLE_RECEIPT_TABLE)} "
        "([IdempotencyKey],[PlanHash],[Status],[ReadbackHash],[RecordedAtUtc]) VALUES (?,?,?,?,?)",
        [
            idempotency_key,
            plan_hash,
            "completed",
            readback_hash,
            datetime.now(timezone.utc),
        ],
    )


def _require_durable_receipt(
    receipt: dict[str, Any],
    idempotency_key: str,
    plan_hash: str,
) -> None:
    if not receipt:
        raise InstyleDemoRebuildUnavailableError(
            "durable rebuild receipt is unavailable after commit; do not retry"
        )
    if (
        receipt.get("idempotencyKey") != idempotency_key
        or receipt.get("planHash") != plan_hash
        or receipt.get("status") != "completed"
        or not HASH.fullmatch(str(receipt.get("readbackHash") or ""))
    ):
        raise InstyleDemoRebuildScopeError(
            "idempotency key belongs to a different or uncertain durable rebuild receipt"
        )


def _completion_receipt(
    idempotency_key: str,
    plan_hash: str,
    required_tables: list[str],
    target_schema_omissions: list[dict[str, Any]],
    dataset: MergeDataset,
    backup_receipt: dict[str, Any],
    readback: dict[str, Any],
    gateway_status: dict[str, Any],
) -> dict[str, Any]:
    return {
        "version": 1,
        "operation": OPERATION_NAME,
        "status": "completed",
        "recordedAt": datetime.now(timezone.utc).isoformat(),
        "idempotencyKey": idempotency_key,
        "planHash": plan_hash,
        "ticketNumbers": list(TICKET_NUMBERS),
        "sources": [SOURCE_A_USERNAME, SOURCE_B_USERNAME],
        "target": TARGET_USERNAME,
        "requiredTableCount": len(required_tables),
        "fixedTargetSchemaOmissions": target_schema_omissions,
        "reconciliation": dataset.reconciliation,
        "productMappingCount": dataset.product_mapping_count,
        "productDedupeCount": dataset.product_dedupe_count,
        "placeholderProductCount": dataset.placeholder_product_count,
        "expectedProductOrphanRows": dataset.expected_product_orphan_rows,
        "streamedTables": list(dataset.streamed_tables),
        "excludedDiagnosticTables": sorted(EXCLUDED_DIAGNOSTIC_TABLE_NAMES),
        "quarantinedNullInvoiceIdCount": len(dataset.quarantine_rows),
        "backupReceipt": backup_receipt,
        "readback": readback,
        "transactionCommitted": True,
        "postWriteReadbackVerified": True,
        "checkpointResumeVerified": True,
        "durableIdempotencyVerified": True,
        "restoreContractVersion": str(gateway_status.get("contractVersion") or ""),
    }


def _completed_result(
    receipt: dict[str, Any],
    idempotency_key: str,
    preview_hash: str,
    *,
    replay: bool,
) -> dict[str, Any]:
    if (
        receipt.get("operation") != OPERATION_NAME
        or receipt.get("status") != "completed"
        or receipt.get("idempotencyKey") != idempotency_key
        or receipt.get("planHash") != preview_hash
    ):
        raise InstyleDemoRebuildScopeError("idempotency key belongs to a different or uncertain rebuild")
    return {
        "ok": True,
        "status": "completed",
        "operation": "nova_sql_instyle_demo_rebuild_execute",
        "businessOperation": OPERATION_NAME,
        "ticketNumbers": list(TICKET_NUMBERS),
        "idempotencyKey": idempotency_key,
        "planHash": preview_hash,
        "sources": [SOURCE_A_USERNAME, SOURCE_B_USERNAME],
        "target": TARGET_USERNAME,
        "requiredTableCount": int(receipt.get("requiredTableCount", 0)),
        "fixedTargetSchemaOmissions": list(
            receipt.get("fixedTargetSchemaOmissions") or []
        ),
        "reconciliation": dict(receipt.get("reconciliation") or {}),
        "productMappingCount": int(receipt.get("productMappingCount", 0)),
        "productDedupeCount": int(receipt.get("productDedupeCount", 0)),
        "placeholderProductCount": int(receipt.get("placeholderProductCount", 0)),
        "expectedProductOrphanRows": int(
            receipt.get("expectedProductOrphanRows", 0)
        ),
        "streamedTables": list(receipt.get("streamedTables") or []),
        "excludedDiagnosticTables": list(
            receipt.get("excludedDiagnosticTables") or []
        ),
        "quarantinedNullInvoiceIdCount": int(receipt.get("quarantinedNullInvoiceIdCount", 0)),
        "backupReceipt": dict(receipt.get("backupReceipt") or {}),
        "readback": dict(receipt.get("readback") or {}),
        "transactionCommitted": True,
        "postWriteReadbackVerified": True,
        "durableIdempotencyVerified": bool(receipt.get("durableIdempotencyVerified")),
        "idempotentReplay": bool(replay),
        "arbitrarySqlAccepted": False,
        "genericExecutorChanged": False,
    }


def _recovery_result(
    idempotency_key: str,
    plan_hash: str,
    *,
    status: str,
    action: str,
    rollback_receipt: dict[str, Any],
    gateway_status: dict[str, Any],
    replay: bool,
) -> dict[str, Any]:
    return {
        "ok": True,
        "operation": "nova_sql_instyle_demo_rebuild_recover",
        "status": status,
        "recoveryAction": action,
        "idempotencyKey": idempotency_key,
        "previewHash": plan_hash,
        "fixedTarget": TARGET_USERNAME,
        "fixedTargetDatabase": TARGET_DATABASE,
        "sourceDatabasesRead": False,
        "callerSelectedAccountsAccepted": False,
        "arbitrarySqlAccepted": False,
        "protectedRestoreContractVersion": str(
            gateway_status.get("contractVersion") or ""
        ),
        "rollbackReceipt": rollback_receipt,
        "postWriteReadbackVerified": bool(
            rollback_receipt.get("readbackVerified")
        )
        or status in {"target_unchanged", "committed"},
        "idempotentReplay": bool(replay),
    }


def _preview_result(manifest: dict[str, Any], *, replay: bool) -> dict[str, Any]:
    if manifest.get("operation") != OPERATION_NAME or not HASH.fullmatch(str(manifest.get("planHash") or "")):
        raise InstyleDemoRebuildUnavailableError("fixed rebuild preview receipt is invalid; do not execute")

    def summary(value: dict[str, Any]) -> dict[str, Any]:
        tables = list(value.get("tables") or [])
        return {
            "companyUsername": value.get("companyUsername"),
            "databaseName": value.get("databaseName"),
            "capturedAt": manifest.get("previewedAt"),
            "schemaHash": value.get("schemaHash"),
            "snapshotHash": value.get("snapshotHash"),
            "consistencyMode": value.get("consistencyMode"),
            "tableCount": int(value.get("tableCount", len(tables))),
            "rowCount": sum(int(table.get("rowCount", 0)) for table in tables),
        }

    required_tables = [str(value) for value in (manifest.get("requiredTables") or [])]
    return {
        "ok": True,
        "status": "preview",
        "operation": "nova_sql_instyle_demo_rebuild_preview",
        "businessOperation": OPERATION_NAME,
        "ticketNumbers": list(TICKET_NUMBERS),
        "idempotencyKey": manifest.get("idempotencyKey"),
        "planHash": manifest.get("planHash"),
        "sources": [summary(manifest["sourceA"]), summary(manifest["sourceB"])],
        "target": summary(manifest["target"]),
        "latestSourceSnapshot": True,
        "requiredTableCount": len(required_tables),
        "requiredTables": required_tables,
        "fixedTargetSchemaOmissions": list(
            manifest.get("fixedTargetSchemaOmissions") or []
        ),
        "sourceBNonProductIdOffset": SOURCE_B_ID_OFFSET,
        "productDedupeKey": list(PRODUCT_KEY_COLUMNS),
        "productMappingCount": int(manifest.get("productMappingCount", 0)),
        "productDedupeCount": int(manifest.get("productDedupeCount", 0)),
        "placeholderProductCount": int(manifest.get("placeholderProductCount", 0)),
        "streamedTables": list(manifest.get("streamedTables") or []),
        "excludedDiagnosticTables": list(manifest.get("excludedDiagnosticTables") or []),
        "expectedProductOrphanRowsBeforeStreaming": int(
            manifest.get("expectedProductOrphanRowsBeforeStreaming", 0)
        ),
        "quarantinedNullInvoiceIdCount": int(manifest.get("quarantineRowCount", 0)),
        "reconciliation": dict(manifest.get("reconciliation") or {}),
        "completeTargetBackupRequired": True,
        "protectedResetRequired": True,
        "rollbackRequired": True,
        "checkpointResume": True,
        "idempotentReplay": bool(replay),
        "arbitrarySqlAccepted": False,
        "callerSelectedAccountsAccepted": False,
        "genericExecutorChanged": False,
        "forbiddenDirectOperations": ["DELETE", "DROP", "ALTER", "constraint disable", "cross-database SQL"],
        "rollbackInstructions": (
            "Use only this operation's protected restore receipt for the same idempotency key and plan hash; "
            "the broker performs rollback and readback without caller-supplied SQL."
        ),
    }


def _public_snapshot_summary(snapshot: DatabaseSnapshot) -> dict[str, Any]:
    return {
        "companyUsername": snapshot.company_username,
        "databaseName": snapshot.database_name,
        "capturedAt": snapshot.captured_at,
        "schemaHash": snapshot.schema_hash,
        "snapshotHash": snapshot.snapshot_hash,
        "tableCount": len(snapshot.tables),
        "rowCount": sum(snapshot.row_counts.values()),
    }


def _table_schema_value(spec: TableSpec) -> dict[str, Any]:
    return {
        "table": spec.key,
        "columns": [
            {
                "name": column.name,
                "ordinal": column.ordinal,
                "type": column.type_name,
                "nullable": column.nullable,
                "identity": column.identity,
                "computed": column.computed,
                "generated": column.generated,
                "hasDefault": column.has_default,
                "primaryKeyOrdinal": column.primary_key_ordinal,
            }
            for column in spec.columns
        ],
        "foreignKeys": [
            {
                "column": foreign_key.column,
                "referencedTable": foreign_key.referenced_table,
                "referencedColumn": foreign_key.referenced_column,
            }
            for foreign_key in spec.foreign_keys
        ],
    }


def _verify_database_binding(cursor: Any, expected_database: str) -> None:
    row = cursor.execute("SELECT DB_NAME()").fetchone()
    actual = str(row[0] or "") if row else ""
    if actual.casefold() != expected_database.casefold():
        raise InstyleDemoRebuildScopeError("broker connection resolved to an unexpected database")


def _acquire_application_lock(cursor: Any, idempotency_key: str) -> None:
    resource = f"NovaSqlInstyleDemoRebuild:{TARGET_DATABASE}"[:240]
    row = cursor.execute(
        "DECLARE @result int; EXEC @result=sys.sp_getapplock @Resource=?,@LockMode='Exclusive',"
        "@LockOwner='Session',@LockTimeout=30000; SELECT @result",
        [resource],
    ).fetchone()
    if not row or int(row[0]) < 0:
        raise InstyleDemoRebuildUnavailableError("another fixed demo rebuild holds the target application lock")


def _set_timeout(connection: Any, seconds: int) -> None:
    try:
        connection.timeout = seconds
    except Exception:
        pass


def _idempotency_key(value: str) -> str:
    clean = str(value or "").strip()
    if not IDEMPOTENCY_KEY.fullmatch(clean):
        raise InstyleDemoRebuildScopeError(
            "idempotency_key must be a stable 8-200 character operation identifier"
        )
    return clean


def _hash_value(value: Any) -> str:
    clean = str(value or "").strip().lower()
    if not HASH.fullmatch(clean):
        raise InstyleDemoRebuildScopeError("protected restore hash must be an exact SHA-256 value")
    return clean


def _fixed_target(value: str) -> str:
    clean = str(value or "").strip()
    if clean.casefold() != TARGET_DATABASE.casefold():
        raise InstyleDemoRebuildScopeError("protected restore target must be the fixed demo database")
    return TARGET_DATABASE


def _bounded_receipt(value: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(value, dict) or _contains_secret_key(value):
        raise InstyleDemoRebuildScopeError("protected restore receipt is invalid or contains a secret field")
    serialized = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    if len(serialized) > 32_768:
        raise InstyleDemoRebuildScopeError("protected restore receipt exceeds the fixed size ceiling")
    return json.loads(serialized)


def _contains_secret_key(value: Any) -> bool:
    if isinstance(value, dict):
        for key, child in value.items():
            if LocalProtectedDemoRestoreGateway._SECRET_KEY.search(str(key)):
                return True
            if _contains_secret_key(child):
                return True
    elif isinstance(value, list):
        return any(_contains_secret_key(child) for child in value)
    return False


def _internal_table(name: str) -> bool:
    lowered = str(name).casefold()
    return lowered == "sysdiagrams" or any(lowered.startswith(prefix) for prefix in INTERNAL_TABLE_PREFIXES)


def _require_identifier(value: str) -> str:
    clean = str(value or "")
    if not IDENTIFIER.fullmatch(clean):
        raise InstyleDemoRebuildScopeError("database metadata contains an unsupported identifier")
    return clean


def _quote_identifier(value: str) -> str:
    return f"[{_require_identifier(value)}]"


def _quote_table(value: str) -> str:
    parts = str(value or "").split(".")
    if len(parts) != 2:
        raise InstyleDemoRebuildScopeError("table identifier must be schema-qualified")
    return ".".join(_quote_identifier(part) for part in parts)


def _normalize_product_value(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    return " ".join(text.strip().split()).casefold()


def _required_int(value: Any, label: str) -> int:
    if value is None or isinstance(value, bool):
        raise InstyleDemoRebuildScopeError(f"{label} must contain a non-null integer")
    try:
        integer = int(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise InstyleDemoRebuildScopeError(f"{label} must contain an integer") from exc
    if isinstance(value, (float, Decimal)) and value != integer:
        raise InstyleDemoRebuildScopeError(f"{label} must contain an integer")
    return integer


def _has_column(spec: TableSpec, name: str) -> bool:
    return any(column.name.casefold() == name.casefold() for column in spec.columns)


def _has_row_key(row: dict[str, Any], name: str) -> bool:
    return any(key.casefold() == name.casefold() for key in row)


def _row_value(row: dict[str, Any], name: str) -> Any:
    return next((value for key, value in row.items() if key.casefold() == name.casefold()), None)


def _set_row_value(row: dict[str, Any], name: str, value: Any) -> None:
    existing = next((key for key in row if key.casefold() == name.casefold()), name)
    row[existing] = value


def _canonical_row_json(row: dict[str, Any]) -> str:
    return json.dumps(
        {str(key): _canonical_value(value) for key, value in sorted(row.items(), key=lambda item: item[0].casefold())},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )


def _canonical_value(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, bytes):
        return {"type": "bytes", "value": base64.b64encode(value).decode("ascii")}
    if isinstance(value, Decimal):
        return {"type": "decimal", "value": str(value)}
    if isinstance(value, (datetime, date, time)):
        return {"type": type(value).__name__, "value": value.isoformat()}
    if isinstance(value, UUID):
        return {"type": "uuid", "value": str(value)}
    if isinstance(value, float):
        return {"type": "float", "value": repr(value)}
    return {"type": type(value).__name__, "value": str(value)}


def _sha256_json(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    ).hexdigest()


def _write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f".{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, sort_keys=True, indent=2), encoding="utf-8")
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)


def _read_json_optional(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    return _read_json_required(path, "state")


def _read_json_required(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise InstyleDemoRebuildUnavailableError(
            f"fixed rebuild {label} is missing or unreadable; do not retry execution"
        ) from exc
    if not isinstance(value, dict):
        raise InstyleDemoRebuildUnavailableError(f"fixed rebuild {label} is invalid; do not retry execution")
    return value
