from __future__ import annotations

import hashlib
import json
import re
from contextlib import ExitStack, closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from .nova_sql_instyle_demo_rebuild import (
    HASH,
    IDEMPOTENCY_KEY,
    PRODUCT_KEY_COLUMNS,
    PRODUCT_REFERENCE_COLUMNS,
    SOURCE_A_DATABASE,
    SOURCE_A_USERNAME,
    SOURCE_B_DATABASE,
    SOURCE_B_ID_OFFSET,
    SOURCE_B_USERNAME,
    TARGET_DATABASE,
    TARGET_USERNAME,
    ColumnSpec,
    DatabaseSnapshot,
    InstyleDemoRebuildScopeError,
    InstyleDemoRebuildUnavailableError,
    TableSpec,
    _acquire_application_lock,
    _canonical_row_json,
    _capture_schema,
    _dependency_order,
    _find_table,
    _has_column,
    _has_row_key,
    _normalize_product_value,
    _placeholder_row,
    _project_row,
    _quote_identifier,
    _quote_table,
    _read_json_optional,
    _read_json_required,
    _required_int,
    _row_value,
    _set_row_value,
    _set_timeout,
    _sha256_json,
    _transform_product_winner_row,
    _transform_row,
    _validate_schema_contract,
    _verify_database_binding,
    _write_json_atomic,
)


OPERATION_NAME = "instyle_demo_incremental_sync_v1"
OPERATION_TOOLS = (
    "nova_sql_instyle_demo_sync_preview",
    "nova_sql_instyle_demo_sync_execute",
    "nova_sql_instyle_demo_sync_status",
)
EXCLUDED_COPY_TABLES = frozenset({"inventoryhistoryitem", "log4net"})
CHECKPOINT_TABLE = "dbo.__AgentChat_InstyleMergeCheckpoint"
PRODUCT_MAP_TABLE = "dbo.__codex_instyle_core_product_map"
MAX_DELTA_ROWS_PER_SOURCE_TABLE = 500_000
BATCH_ROWS = 2_000

# These eleven Instyle Fragrance lines were written without InvoiceID.  The
# corresponding source invoices were independently verified before this fixed
# operation was designed.  The source database remains read-only; the repair is
# applied only to rows copied into DEMO_NOVA_CAFE.
INVOICE_PRODUCT_INVOICE_REPAIRS = {
    158439: 119342,
    158440: 119343,
    158441: 119343,
    160307: 120626,
    160308: 120626,
    160309: 120627,
    160310: 120628,
    160311: 120629,
    160312: 120630,
    160313: 120631,
    160314: 120631,
}
INVOICE_EMPLOYEE_INVOICE_REPAIRS = {
    128329: 119342,
    128330: 119342,
    128331: 119343,
    129823: 120626,
    129824: 120627,
    129825: 120628,
    129826: 120629,
    129827: 120630,
    129828: 120631,
}
INVOICE_PAYMENT_INVOICE_REPAIRS = {
    118824: 119342,
    118825: 119343,
    120135: 120626,
    120136: 120627,
    120137: 120628,
    120138: 120629,
    120139: 120629,
    120140: 120630,
    120141: 120631,
}


class InstyleDemoSyncOperation:
    """Resume the proven Instyle demo merge without recopying cold history."""

    def __init__(
        self,
        *,
        connect: Callable[[str, bool], Any],
        state_dir: str | Path,
        query_timeout_seconds: int = 30,
    ) -> None:
        self._connect = connect
        self._state_dir = Path(state_dir).expanduser().resolve() / OPERATION_NAME
        self._query_timeout_seconds = max(300, min(int(query_timeout_seconds), 1_800))

    def preview(self, *, idempotency_key: str) -> dict[str, Any]:
        clean_key = _idempotency_key(idempotency_key)
        existing = _read_json_optional(self._preview_path(clean_key))
        if existing:
            return _preview_result(existing, replay=True)
        with ExitStack() as stack:
            source_a_connection = stack.enter_context(
                closing(self._connect(SOURCE_A_USERNAME, True))
            )
            source_b_connection = stack.enter_context(
                closing(self._connect(SOURCE_B_USERNAME, True))
            )
            target_connection = stack.enter_context(
                closing(self._connect(TARGET_USERNAME, True))
            )
            immutable = self._build_manifest(
                source_a_connection,
                source_b_connection,
                target_connection,
                clean_key,
            )
        plan_hash = _sha256_json(_execution_contract(immutable))
        preview = {
            **immutable,
            "planHashVersion": 2,
            "planHash": plan_hash,
            "previewedAt": datetime.now(timezone.utc).isoformat(),
        }
        _write_json_atomic(self._preview_path(clean_key), preview)
        return _preview_result(preview, replay=False)

    def status(self, *, idempotency_key: str) -> dict[str, Any]:
        """Reconcile one preview after an uncertain execute without writing."""

        clean_key = _idempotency_key(idempotency_key)
        completed = _read_json_optional(self._receipt_path(clean_key))
        if completed:
            result = _completed_result(completed, replay=True)
            result["operation"] = OPERATION_TOOLS[2]
            result["reconciliationStatus"] = "completed"
            result["completionReceiptPresent"] = True
            result["safeToRetry"] = False
            return result

        preview = _read_json_optional(self._preview_path(clean_key))
        if not preview:
            return {
                "ok": True,
                "operation": OPERATION_TOOLS[2],
                "status": "not_previewed",
                "idempotencyKey": clean_key,
                "completionReceiptPresent": False,
                "safeToRetry": False,
                "nextStep": (
                    "Call nova_sql_instyle_demo_sync_preview with this stable "
                    "idempotency key."
                ),
            }

        with ExitStack() as stack:
            source_a_connection = stack.enter_context(
                closing(self._connect(SOURCE_A_USERNAME, True))
            )
            source_b_connection = stack.enter_context(
                closing(self._connect(SOURCE_B_USERNAME, True))
            )
            target_connection = stack.enter_context(
                closing(self._connect(TARGET_USERNAME, True))
            )
            current = self._build_manifest(
                source_a_connection,
                source_b_connection,
                target_connection,
                clean_key,
            )
            sources_unchanged = _source_contract(
                current.get("sources")
            ) == _source_contract(preview.get("sources"))
            target_unchanged = current.get("target") == preview.get("target")
            readback: dict[str, Any] = {}
            completion_verified = False
            reconciliation_status = "not_committed"
            if not target_unchanged:
                target_cursor = target_connection.cursor()
                target_snapshot = _capture_schema(
                    target_cursor,
                    TARGET_USERNAME,
                    TARGET_DATABASE,
                )
                readback = _reconciliation_readback(
                    target_cursor,
                    target_snapshot,
                    preview=preview,
                )
                completion_verified = bool(
                    sources_unchanged and readback.get("completionVerified")
                )
                reconciliation_status = (
                    "committed_without_receipt"
                    if completion_verified
                    else "target_changed_without_receipt"
                )

        safe_to_retry = bool(
            sources_unchanged
            and target_unchanged
            and reconciliation_status == "not_committed"
        )
        return {
            "ok": True,
            "operation": OPERATION_TOOLS[2],
            "status": "reconciled",
            "idempotencyKey": clean_key,
            "previewHash": preview.get("planHash"),
            "fixedSources": [SOURCE_A_USERNAME, SOURCE_B_USERNAME],
            "fixedTarget": TARGET_USERNAME,
            "sourceDatabasesReadOnly": True,
            "sourceRowsMayAdvance": True,
            "completionReceiptPresent": False,
            "reconciliationStatus": reconciliation_status,
            "sourcesUnchanged": sources_unchanged,
            "targetBaselineUnchanged": target_unchanged,
            "previewTargetBaseline": _public_target_baseline(preview.get("target")),
            "currentTargetBaseline": _public_target_baseline(current.get("target")),
            "readback": readback,
            "completionVerified": completion_verified,
            "safeToRetry": safe_to_retry,
            "nextStep": (
                "Retry nova_sql_instyle_demo_sync_execute once with the same "
                "idempotency key and preview hash."
                if safe_to_retry
                else (
                    "Treat the operation as completed; do not retry."
                    if completion_verified
                    else "Do not retry until the changed target is reviewed."
                )
            ),
        }

    def execute(self, *, idempotency_key: str, preview_hash: str) -> dict[str, Any]:
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
                "preview hash, idempotency key, or fixed sync plan does not match"
            )
        completed = _read_json_optional(self._receipt_path(clean_key))
        if completed:
            return _completed_result(completed, replay=True)
        if int(preview.get("planHashVersion") or 0) != 2:
            raise InstyleDemoRebuildScopeError(
                "this preview predates the live-source-safe hash contract; "
                "create a new preview and idempotency key"
            )

        with ExitStack() as stack:
            source_a_connection = stack.enter_context(
                closing(self._connect(SOURCE_A_USERNAME, True))
            )
            source_b_connection = stack.enter_context(
                closing(self._connect(SOURCE_B_USERNAME, True))
            )
            target_connection = stack.enter_context(
                closing(self._connect(TARGET_USERNAME, False))
            )
            for connection in (
                source_a_connection,
                source_b_connection,
                target_connection,
            ):
                _set_timeout(connection, self._query_timeout_seconds)
            current = self._build_manifest(
                source_a_connection,
                source_b_connection,
                target_connection,
                clean_key,
            )
            if _sha256_json(_execution_contract(current)) != clean_hash:
                raise InstyleDemoRebuildScopeError(
                    "a source schema or the demo baseline changed after preview; "
                    "create a new preview and idempotency key"
                )

            source_a_schema = _capture_schema(
                source_a_connection.cursor(),
                SOURCE_A_USERNAME,
                SOURCE_A_DATABASE,
            )
            source_b_schema = _capture_schema(
                source_b_connection.cursor(),
                SOURCE_B_USERNAME,
                SOURCE_B_DATABASE,
            )
            target_schema = _capture_schema(
                target_connection.cursor(),
                TARGET_USERNAME,
                TARGET_DATABASE,
            )
            core_source_a = _without_excluded_tables(source_a_schema)
            core_source_b = _without_excluded_tables(source_b_schema)
            core_target = _without_excluded_tables(target_schema)
            required_tables = _validate_schema_contract(
                core_source_a,
                core_source_b,
                core_target,
            )

            target_cursor = target_connection.cursor()
            try:
                target_connection.autocommit = False
            except Exception:
                pass
            target_cursor.execute("SET XACT_ABORT ON")
            _verify_database_binding(target_cursor, TARGET_DATABASE)
            _acquire_application_lock(target_cursor, clean_key)

            committed = False
            started_at = datetime.now(timezone.utc)
            run_id = str(uuid4())
            try:
                product_map, product_result = _sync_products(
                    source_a_connection,
                    source_b_connection,
                    target_cursor,
                    core_source_a,
                    core_source_b,
                    core_target,
                )
                orphan_updates = _repair_target_product_orphans(
                    target_cursor,
                    target_schema,
                )
                checkpoints = _read_latest_checkpoints(target_cursor)
                copy_result = _copy_incremental_rows(
                    source_a_connection=source_a_connection,
                    source_b_connection=source_b_connection,
                    target_connection=target_connection,
                    source_a=core_source_a,
                    source_b=core_source_b,
                    target=core_target,
                    required_tables=required_tables,
                    product_map=product_map,
                    checkpoints=checkpoints,
                    run_id=run_id,
                )
                fixed_repairs = _repair_fixed_target_invoice_links(target_cursor)
                orphan_updates_after_copy = _repair_target_product_orphans(
                    target_cursor,
                    target_schema,
                )
                source_after = self._source_manifest(
                    source_a_connection,
                    source_b_connection,
                )
                if _source_contract(source_after) != _source_contract(
                    current.get("sources")
                ):
                    raise InstyleDemoRebuildScopeError(
                        "a source schema changed during the fixed demo sync; the "
                        "target transaction was rolled back"
                    )
                readback = _readback(
                    target_cursor,
                    target_schema,
                    product_result=product_result,
                    source_manifest=source_after,
                )
                target_connection.commit()
                committed = True
                post_commit = _readback(
                    target_cursor,
                    target_schema,
                    product_result=product_result,
                    source_manifest=source_after,
                )
                if post_commit != readback:
                    raise InstyleDemoRebuildUnavailableError(
                        "demo sync committed but its readback changed"
                    )
            except Exception:
                if not committed:
                    try:
                        target_connection.rollback()
                    except Exception:
                        pass
                raise

        receipt = {
            "version": 1,
            "operation": OPERATION_NAME,
            "status": "completed",
            "idempotencyKey": clean_key,
            "planHash": clean_hash,
            "runId": run_id,
            "startedAt": started_at.isoformat(),
            "completedAt": datetime.now(timezone.utc).isoformat(),
            "fixedSources": [SOURCE_A_USERNAME, SOURCE_B_USERNAME],
            "fixedTarget": TARGET_USERNAME,
            "sourceDatabasesReadOnly": True,
            "sourceRowsMayAdvance": True,
            "sourceDataAdvancedDuringRun": source_after != current.get("sources"),
            "targetBackupCreated": False,
            "targetBackupRequired": False,
            "inventoryHistoryItemAction": "preserved_in_place",
            "productSync": product_result,
            "orphanRowsRepaired": orphan_updates + orphan_updates_after_copy,
            "incrementalCopy": copy_result,
            "fixedInvoiceLinkRepairs": fixed_repairs,
            "readback": post_commit,
            "postWriteReadbackVerified": True,
        }
        _write_json_atomic(self._receipt_path(clean_key), receipt)
        return _completed_result(receipt, replay=False)

    def _build_manifest(
        self,
        source_a_connection: Any,
        source_b_connection: Any,
        target_connection: Any,
        idempotency_key: str,
    ) -> dict[str, Any]:
        sources = self._source_manifest(source_a_connection, source_b_connection)
        cursor = target_connection.cursor()
        _verify_database_binding(cursor, TARGET_DATABASE)
        checkpoint_rows = _checkpoint_manifest(cursor)
        target_baseline = {
            "productRows": _table_count(cursor, "dbo.Products"),
            "invoiceProductRows": _table_count(cursor, "dbo.Invoice_Products"),
            "inventoryHistoryItemRows": _table_count(
                cursor,
                "dbo.InventoryHistoryItem",
            ),
            "checkpointHash": _sha256_json(checkpoint_rows),
            "checkpointRows": len(checkpoint_rows),
            "productOrphanRows": _target_product_orphan_count(cursor),
        }
        return {
            "version": 1,
            "operation": OPERATION_NAME,
            "tickets": ["347072", "347073"],
            "idempotencyKey": idempotency_key,
            "sources": sources,
            "target": {
                "companyUsername": TARGET_USERNAME,
                "databaseName": TARGET_DATABASE,
                **target_baseline,
            },
            "copyMode": "checkpointed_incremental_core",
            "productDedupeKey": list(PRODUCT_KEY_COLUMNS),
            "sourceBNonProductIdOffset": SOURCE_B_ID_OFFSET,
            "excludedCopyTables": sorted(EXCLUDED_COPY_TABLES),
            "inventoryHistoryItemAction": "preserve_existing_target_rows",
            "sourceMutationAllowed": False,
            "targetBackupRequired": False,
            "fixedInvoiceProductRepairCount": len(
                INVOICE_PRODUCT_INVOICE_REPAIRS
            ),
            "fixedInvoiceEmployeeRepairCount": len(
                INVOICE_EMPLOYEE_INVOICE_REPAIRS
            ),
            "fixedInvoicePaymentRepairCount": len(
                INVOICE_PAYMENT_INVOICE_REPAIRS
            ),
        }

    def _source_manifest(
        self,
        source_a_connection: Any,
        source_b_connection: Any,
    ) -> list[dict[str, Any]]:
        return [
            _source_manifest(
                source_a_connection,
                SOURCE_A_USERNAME,
                SOURCE_A_DATABASE,
            ),
            _source_manifest(
                source_b_connection,
                SOURCE_B_USERNAME,
                SOURCE_B_DATABASE,
            ),
        ]

    def _preview_path(self, idempotency_key: str) -> Path:
        return self._state_path("preview", idempotency_key)

    def _receipt_path(self, idempotency_key: str) -> Path:
        return self._state_path("receipt", idempotency_key)

    def _state_path(self, kind: str, idempotency_key: str) -> Path:
        digest = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()
        return self._state_dir / f"{digest}.{kind}.json"


def _source_manifest(
    connection: Any,
    company_username: str,
    database_name: str,
) -> dict[str, Any]:
    cursor = connection.cursor()
    _verify_database_binding(cursor, database_name)
    schema = _without_excluded_tables(
        _capture_schema(cursor, company_username, database_name)
    )
    tables: list[dict[str, Any]] = []
    for table_key in sorted(schema.tables, key=str.casefold):
        spec = schema.tables[table_key]
        cursor_columns = _cursor_columns(spec)
        row = cursor.execute(
            f"SELECT COUNT_BIG(*) FROM {_quote_table(table_key)}"
        ).fetchone()
        count = int(row[0] or 0) if row else 0
        last_values: list[Any] = []
        if cursor_columns and count:
            select_columns = ", ".join(
                _quote_identifier(column.name) for column in cursor_columns
            )
            order_columns = ", ".join(
                f"{_quote_identifier(column.name)} DESC"
                for column in cursor_columns
            )
            last_row = cursor.execute(
                f"SELECT TOP (1) {select_columns} "
                f"FROM {_quote_table(table_key)} ORDER BY {order_columns}"
            ).fetchone()
            if last_row:
                last_values = [
                    _manifest_value(last_row[index])
                    for index in range(len(cursor_columns))
                ]
        tables.append(
            {
                "table": table_key,
                "rowCount": count,
                "cursorColumns": [column.name for column in cursor_columns],
                "lastKey": last_values,
            }
        )
    return {
        "companyUsername": company_username,
        "databaseName": database_name,
        "schemaHash": schema.schema_hash,
        "tables": tables,
    }


def _source_contract(value: Any) -> list[dict[str, str]]:
    """Keep schema identity immutable while allowing ordinary source row drift."""

    return sorted(
        [
            {
                "companyUsername": str(item.get("companyUsername") or ""),
                "databaseName": str(item.get("databaseName") or ""),
                "schemaHash": str(item.get("schemaHash") or ""),
            }
            for item in (value or [])
            if isinstance(item, dict)
        ],
        key=lambda item: (
            item["companyUsername"].casefold(),
            item["databaseName"].casefold(),
        ),
    )


def _execution_contract(manifest: dict[str, Any]) -> dict[str, Any]:
    contract = dict(manifest)
    contract["sources"] = _source_contract(manifest.get("sources"))
    return contract


def _without_excluded_tables(snapshot: DatabaseSnapshot) -> DatabaseSnapshot:
    tables = {
        key: spec
        for key, spec in snapshot.tables.items()
        if spec.name.casefold() not in EXCLUDED_COPY_TABLES
    }
    schema_hash = _sha256_json(
        {
            "databaseName": snapshot.database_name,
            "tables": [
                {
                    "table": key,
                    "columns": [
                        {
                            "name": column.name,
                            "type": column.type_name,
                            "nullable": column.nullable,
                            "identity": column.identity,
                            "computed": column.computed,
                            "generated": column.generated,
                            "default": column.has_default,
                            "primaryKeyOrdinal": column.primary_key_ordinal,
                        }
                        for column in tables[key].columns
                    ],
                }
                for key in sorted(tables)
            ],
        }
    )
    return DatabaseSnapshot(
        company_username=snapshot.company_username,
        database_name=snapshot.database_name,
        captured_at=snapshot.captured_at,
        schema_hash=schema_hash,
        snapshot_hash="",
        tables=tables,
        table_hashes={key: "" for key in tables},
        row_counts={key: 0 for key in tables},
    )


def _cursor_columns(spec: TableSpec) -> tuple[ColumnSpec, ...]:
    if spec.primary_key:
        return spec.primary_key
    identity = spec.identity_column
    return (identity,) if identity is not None else ()


def _sync_products(
    source_a_connection: Any,
    source_b_connection: Any,
    target_cursor: Any,
    source_a: DatabaseSnapshot,
    source_b: DatabaseSnapshot,
    target: DatabaseSnapshot,
) -> tuple[dict[tuple[str, int], int], dict[str, Any]]:
    source_a_spec = _find_table(source_a, "Products")
    source_b_spec = _find_table(source_b, "Products")
    target_spec = _find_table(target, "Products")
    source_rows = {
        SOURCE_A_USERNAME: _read_product_index_rows(
            source_a_connection.cursor(),
            source_a_spec,
        ),
        SOURCE_B_USERNAME: _read_product_index_rows(
            source_b_connection.cursor(),
            source_b_spec,
        ),
    }
    target_rows = _read_product_index_rows(target_cursor, target_spec)
    _ensure_product_map_table(target_cursor)
    existing_map = _read_product_map(target_cursor)
    target_ids = {
        _required_int(_row_value(row, "ProductID"), "target ProductID")
        for row in target_rows
    }
    target_by_key: dict[tuple[str, str, str, str], list[int]] = {}
    target_key_by_id: dict[int, tuple[str, str, str, str]] = {}
    for row in target_rows:
        key = _product_key(row)
        target_id = _required_int(
            _row_value(row, "ProductID"),
            "target ProductID",
        )
        target_key_by_id[target_id] = key
        if any(key):
            target_by_key.setdefault(key, []).append(target_id)

    grouped: dict[
        tuple[str, str, str, str],
        list[tuple[str, dict[str, Any]]],
    ] = {}
    for source_name, rows in source_rows.items():
        for row in rows:
            product_id = _required_int(
                _row_value(row, "ProductID"),
                "source ProductID",
            )
            key = _product_key(row)
            if not any(key):
                key = (
                    f"__source__:{source_name.casefold()}:{product_id}",
                    "",
                    "",
                    "",
                )
            grouped.setdefault(key, []).append((source_name, row))

    product_map: dict[tuple[str, int], int] = {}
    new_rows: list[dict[str, Any]] = []
    pending_new_rows: list[tuple[str, int, int]] = []
    map_rows: list[tuple[str, int, int, str, bool]] = []
    next_id = max([0, *target_ids]) + 1
    source_priority = {SOURCE_A_USERNAME: 1, SOURCE_B_USERNAME: 0}
    for key in sorted(grouped):
        candidates = grouped[key]
        mapped_candidates = {
            existing_map[(source_name, _source_product_id(row))]
            for source_name, row in candidates
            if (source_name, _source_product_id(row)) in existing_map
            and existing_map[(source_name, _source_product_id(row))]
            in target_ids
        }
        same_id_candidates = sorted(
            {
                _source_product_id(row)
                for _source_name, row in candidates
                if _source_product_id(row) in target_ids
                and (
                    target_key_by_id.get(_source_product_id(row)) == key
                    or (
                        str(key[0]).startswith("__source__:")
                        and not any(
                            target_key_by_id.get(
                                _source_product_id(row),
                                ("", "", "", ""),
                            )
                        )
                    )
                )
            }
        )
        target_candidates = sorted(target_by_key.get(key, []))
        if mapped_candidates:
            target_id = min(mapped_candidates)
        elif same_id_candidates:
            target_id = same_id_candidates[0]
        elif target_candidates:
            target_id = target_candidates[0]
        else:
            winner_source, winner = max(
                candidates,
                key=lambda item: (
                    _source_product_id(item[1]),
                    source_priority[item[0]],
                    hashlib.sha256(
                        _canonical_row_json(item[1]).encode("utf-8")
                    ).hexdigest(),
                ),
            )
            desired = _source_product_id(winner)
            target_id = desired
            if target_id <= 0 or target_id in target_ids:
                while next_id in target_ids:
                    next_id += 1
                target_id = next_id
                next_id += 1
            target_ids.add(target_id)
            pending_new_rows.append((winner_source, desired, target_id))
        key_hash = _sha256_json(list(key))
        for source_name, row in candidates:
            source_id = _source_product_id(row)
            product_map[(source_name, source_id)] = target_id
            map_rows.append(
                (
                    _source_tag(source_name),
                    source_id,
                    target_id,
                    key_hash,
                    False,
                )
            )

    full_source_rows: dict[tuple[str, int], dict[str, Any]] = {}
    for source_name, connection, spec in (
        (SOURCE_A_USERNAME, source_a_connection, source_a_spec),
        (SOURCE_B_USERNAME, source_b_connection, source_b_spec),
    ):
        source_ids = sorted(
            {
                source_id
                for winner_source, source_id, _target_id in pending_new_rows
                if winner_source == source_name
            }
        )
        for row in _read_exact_integer_rows(
            connection.cursor(),
            spec,
            "ProductID",
            source_ids,
        ):
            full_source_rows[(source_name, _source_product_id(row))] = row
    for winner_source, source_id, target_id in pending_new_rows:
        winner = full_source_rows.get((winner_source, source_id))
        if winner is None:
            raise InstyleDemoRebuildUnavailableError(
                "a selected source product changed during the bounded product scan"
            )
        new_row = _transform_product_winner_row(
            winner_source,
            winner,
            target_spec,
            target_id,
        )
        if not str(_row_value(new_row, "ProductName") or "").strip():
            _set_row_value(
                new_row,
                "ProductName",
                f"Unnamed product [{_source_tag(winner_source)}:{source_id}]",
            )
        new_rows.append(new_row)

    missing_references = _target_missing_product_references(target_cursor)
    missing_references.update(
        _source_invoice_product_missing_references(
            source_a_connection,
            source_b_connection,
            source_a,
            source_b,
        )
    )
    template_rows = (
        _read_exact_integer_rows(
            target_cursor,
            target_spec,
            "ProductID",
            [
                min(
                    _required_int(
                        _row_value(row, "ProductID"),
                        "target ProductID",
                    )
                    for row in target_rows
                )
            ],
        )
        if target_rows
        else []
    )
    template = dict(template_rows[0]) if template_rows else {}
    placeholder_rows: list[dict[str, Any]] = []
    for source_name, source_id in sorted(
        missing_references,
        key=lambda value: (value[0].casefold(), value[1]),
    ):
        existing_target = existing_map.get((source_name, source_id))
        if existing_target in target_ids:
            target_id = int(existing_target)
        elif (source_name, source_id) in product_map:
            target_id = product_map[(source_name, source_id)]
        else:
            while next_id in target_ids:
                next_id += 1
            target_id = next_id
            target_ids.add(target_id)
            next_id += 1
            placeholder = _placeholder_row(template, target_spec)
            label = f"MISSING-{_source_tag(source_name)}-{source_id}"
            _set_row_value(placeholder, "ProductID", target_id)
            _set_row_value(
                placeholder,
                "ProductName",
                f"Inactive missing product [{_source_tag(source_name)}:{source_id}]",
            )
            for column_name, value in (
                ("SKU", label),
                ("BarcodeNumber", label),
                ("BarcodeNumber2", f"{label}-2"),
            ):
                if _has_column(target_spec, column_name):
                    _set_row_value(placeholder, column_name, value)
            for column in target_spec.columns:
                if column.name.replace("_", "").casefold() in {
                    "active",
                    "isactive",
                    "productactive",
                    "productisavailable",
                }:
                    _set_row_value(placeholder, column.name, False)
            placeholder_rows.append(placeholder)
        product_map[(source_name, source_id)] = target_id
        map_rows.append(
            (
                _source_tag(source_name),
                source_id,
                target_id,
                _sha256_json(["missing", _source_tag(source_name), source_id]),
                True,
            )
        )

    inserted = _insert_rows_if_missing(
        target_cursor,
        target_spec,
        [*new_rows, *placeholder_rows],
    )
    _write_product_map(target_cursor, map_rows)
    return product_map, {
        "sourceRows": sum(len(rows) for rows in source_rows.values()),
        "canonicalSourceKeys": len(grouped),
        "mappingRows": len(product_map),
        "newCanonicalProducts": len(new_rows),
        "missingSourceProducts": len(missing_references),
        "newPlaceholderProducts": len(placeholder_rows),
        "insertedTargetProducts": inserted,
        "expectedTargetProducts": len(target_rows) + inserted,
    }


def _source_invoice_product_missing_references(
    source_a_connection: Any,
    source_b_connection: Any,
    source_a: DatabaseSnapshot,
    source_b: DatabaseSnapshot,
) -> set[tuple[str, int]]:
    output: set[tuple[str, int]] = set()
    for source_name, connection, snapshot in (
        (SOURCE_A_USERNAME, source_a_connection, source_a),
        (SOURCE_B_USERNAME, source_b_connection, source_b),
    ):
        products = _find_table(snapshot, "Products")
        lookup = {spec.name.casefold(): spec for spec in snapshot.tables.values()}
        cursor = connection.cursor()
        spec = lookup.get("invoice_products")
        if spec is None:
            continue
        product_column = next(
            column.name
            for column in spec.columns
            if column.name.casefold() == "productid"
        )
        product_id_column = next(
            column.name
            for column in products.columns
            if column.name.casefold() == "productid"
        )
        cursor.execute(
            f"SELECT DISTINCT x.{_quote_identifier(product_column)} "
            f"FROM {_quote_table(spec.key)} x "
            f"LEFT JOIN {_quote_table(products.key)} p "
            f"ON p.{_quote_identifier(product_id_column)}="
            f"x.{_quote_identifier(product_column)} "
            f"WHERE x.{_quote_identifier(product_column)}>0 "
            f"AND p.{_quote_identifier(product_id_column)} IS NULL"
        )
        for row in cursor.fetchall():
            output.add(
                (
                    source_name,
                    _required_int(row[0], f"{spec.key}.{product_column}"),
                )
            )
    return output


def _target_missing_product_references(
    cursor: Any,
) -> set[tuple[str, int]]:
    output: set[tuple[str, int]] = set()
    for table_name, column_name in PRODUCT_REFERENCE_COLUMNS.items():
        if table_name == "inventoryhistoryitem":
            continue
        row = cursor.execute(
            "SELECT s.name,t.name,c.name FROM sys.tables t "
            "JOIN sys.schemas s ON s.schema_id=t.schema_id "
            "JOIN sys.columns c ON c.object_id=t.object_id "
            "WHERE LOWER(t.name)=? AND LOWER(c.name)=?",
            [table_name, column_name],
        ).fetchone()
        if not row:
            continue
        table_key = f"{row[0]}.{row[1]}"
        actual_column = str(row[2])
        cursor.execute(
            f"SELECT DISTINCT x.{_quote_identifier(actual_column)} "
            f"FROM {_quote_table(table_key)} x "
            "LEFT JOIN [dbo].[Products] p "
            f"ON p.[ProductID]=x.{_quote_identifier(actual_column)} "
            f"WHERE x.{_quote_identifier(actual_column)}>0 "
            "AND p.[ProductID] IS NULL"
        )
        for value_row in cursor.fetchall():
            encoded = _required_int(
                value_row[0],
                f"{table_key}.{actual_column}",
            )
            if encoded >= SOURCE_B_ID_OFFSET:
                output.add(
                    (
                        SOURCE_B_USERNAME,
                        encoded - SOURCE_B_ID_OFFSET,
                    )
                )
            else:
                output.add((SOURCE_A_USERNAME, encoded))
    return output


def _copy_incremental_rows(
    *,
    source_a_connection: Any,
    source_b_connection: Any,
    target_connection: Any,
    source_a: DatabaseSnapshot,
    source_b: DatabaseSnapshot,
    target: DatabaseSnapshot,
    required_tables: list[str],
    product_map: dict[tuple[str, int], int],
    checkpoints: dict[tuple[str, str], list[Any]],
    run_id: str,
) -> dict[str, Any]:
    target_cursor = target_connection.cursor()
    try:
        target_cursor.fast_executemany = True
    except Exception:
        pass
    ordered, _cyclic = _dependency_order(target, required_tables)
    target_lookup = {key.casefold(): key for key in target.tables}
    source_definitions = (
        (
            "A",
            SOURCE_A_USERNAME,
            source_a_connection,
            source_a,
            {key.casefold(): key for key in source_a.tables},
        ),
        (
            "B",
            SOURCE_B_USERNAME,
            source_b_connection,
            source_b,
            {key.casefold(): key for key in source_b.tables},
        ),
    )
    table_results: list[dict[str, Any]] = []
    total_inserted = 0
    for required_key in ordered:
        target_key = target_lookup[required_key.casefold()]
        target_spec = target.tables[target_key]
        if target_spec.name.casefold() in {"products", *EXCLUDED_COPY_TABLES}:
            continue
        for (
            source_tag,
            source_name,
            source_connection,
            source_snapshot,
            source_lookup,
        ) in source_definitions:
            source_key = source_lookup.get(required_key.casefold())
            if source_key is None:
                continue
            source_spec = source_snapshot.tables[source_key]
            cursor_columns = _cursor_columns(source_spec)
            if not cursor_columns:
                continue
            last_values = checkpoints.get(
                (source_tag, source_spec.name.casefold()),
                [],
            )
            delta_rows = _read_delta_rows(
                source_connection.cursor(),
                source_spec,
                cursor_columns,
                last_values,
            )
            rows = list(delta_rows)
            if (
                source_name == SOURCE_B_USERNAME
                and source_spec.name.casefold() == "invoice_products"
            ):
                repair_rows = _read_exact_integer_rows(
                    source_connection.cursor(),
                    source_spec,
                    "Invoice_Products_ID",
                    list(INVOICE_PRODUCT_INVOICE_REPAIRS),
                )
                seen = {
                    _required_int(
                        _row_value(row, "Invoice_Products_ID"),
                        "Invoice_Products_ID",
                    )
                    for row in rows
                }
                rows.extend(
                    row
                    for row in repair_rows
                    if _required_int(
                        _row_value(row, "Invoice_Products_ID"),
                        "Invoice_Products_ID",
                    )
                    not in seen
                )
            if not rows:
                continue
            transformed: list[dict[str, Any]] = []
            for source_row in rows:
                _apply_fixed_source_repairs(
                    source_name,
                    source_spec.name,
                    source_row,
                )
                _ensure_delta_product_mapping(
                    target_cursor,
                    target,
                    source_name,
                    source_spec,
                    source_row,
                    product_map,
                )
                target_row = _transform_row(
                    source_name,
                    source_row,
                    source_spec,
                    target_spec,
                    product_map,
                )
                target_row.pop("__expectedProductOrphan", None)
                identity = source_spec.identity_column
                if (
                    source_name == SOURCE_B_USERNAME
                    and identity is not None
                    and _has_row_key(target_row, identity.name)
                ):
                    value = _row_value(target_row, identity.name)
                    if value is not None and int(value) < SOURCE_B_ID_OFFSET:
                        _set_row_value(
                            target_row,
                            identity.name,
                            _required_int(
                                value,
                                f"{source_spec.key}.{identity.name}",
                            )
                            + SOURCE_B_ID_OFFSET,
                        )
                transformed.append(target_row)
            inserted = _insert_rows_if_missing(
                target_cursor,
                target_spec,
                transformed,
            )
            total_inserted += inserted
            source_last = _last_cursor_values(delta_rows, cursor_columns)
            if source_last:
                _write_checkpoint(
                    target_cursor,
                    run_id=run_id,
                    source_tag=source_tag,
                    table_name=source_spec.name,
                    range_start=last_values,
                    range_end=source_last,
                    rows_committed=inserted,
                )
            table_results.append(
                {
                    "sourceTag": source_tag,
                    "table": source_spec.key,
                    "candidateRows": len(rows),
                    "insertedRows": inserted,
                }
            )
    return {
        "insertedRows": total_inserted,
        "tablesWithDeltas": len(table_results),
        "tables": table_results,
    }


def _ensure_delta_product_mapping(
    cursor: Any,
    target: DatabaseSnapshot,
    source_name: str,
    source_spec: TableSpec,
    source_row: dict[str, Any],
    product_map: dict[tuple[str, int], int],
) -> None:
    product_column = PRODUCT_REFERENCE_COLUMNS.get(
        source_spec.name.casefold()
    )
    if not product_column or not _has_column(source_spec, product_column):
        return
    original = _row_value(source_row, product_column)
    if original is None:
        return
    source_id = _required_int(
        original,
        f"{source_spec.key}.{product_column}",
    )
    if source_id <= 0 or (source_name, source_id) in product_map:
        return
    products = _find_table(target, "Products")
    max_row = cursor.execute(
        f"SELECT MAX([ProductID]) FROM {_quote_table(products.key)}"
    ).fetchone()
    target_id = int(max_row[0] or 0) + 1
    template_rows = _read_rows(cursor, products)
    template = dict(template_rows[0]) if template_rows else {}
    placeholder = _placeholder_row(template, products)
    label = f"MISSING-{_source_tag(source_name)}-{source_id}"
    _set_row_value(placeholder, "ProductID", target_id)
    _set_row_value(
        placeholder,
        "ProductName",
        f"Inactive missing product [{_source_tag(source_name)}:{source_id}]",
    )
    for column_name, value in (
        ("SKU", label),
        ("BarcodeNumber", label),
        ("BarcodeNumber2", f"{label}-2"),
    ):
        if _has_column(products, column_name):
            _set_row_value(placeholder, column_name, value)
    for column in products.columns:
        if column.name.replace("_", "").casefold() in {
            "active",
            "isactive",
            "productactive",
            "productisavailable",
        }:
            _set_row_value(placeholder, column.name, False)
    _insert_rows_if_missing(cursor, products, [placeholder])
    product_map[(source_name, source_id)] = target_id
    _write_product_map(
        cursor,
        [
            (
                _source_tag(source_name),
                source_id,
                target_id,
                _sha256_json(
                    ["missing", _source_tag(source_name), source_id]
                ),
                True,
            )
        ],
    )


def _read_delta_rows(
    cursor: Any,
    spec: TableSpec,
    cursor_columns: tuple[ColumnSpec, ...],
    last_values: list[Any],
) -> list[dict[str, Any]]:
    columns = list(spec.copyable_columns)
    select_columns = ", ".join(
        _quote_identifier(column.name) for column in columns
    )
    parameters: list[Any] = []
    where = ""
    if last_values:
        if len(last_values) != len(cursor_columns):
            raise InstyleDemoRebuildUnavailableError(
                f"checkpoint key shape changed for {spec.key}"
            )
        clauses: list[str] = []
        for index, column in enumerate(cursor_columns):
            equal = [
                f"{_quote_identifier(cursor_columns[prefix].name)}=?"
                for prefix in range(index)
            ]
            greater = f"{_quote_identifier(column.name)}>?"
            clauses.append("(" + " AND ".join([*equal, greater]) + ")")
            parameters.extend(last_values[:index])
            parameters.append(last_values[index])
        where = " WHERE " + " OR ".join(clauses)
    order = ", ".join(
        _quote_identifier(column.name) for column in cursor_columns
    )
    cursor.execute(
        f"SELECT {select_columns} FROM {_quote_table(spec.key)}"
        f"{where} ORDER BY {order}",
        parameters,
    )
    raw_rows = cursor.fetchmany(MAX_DELTA_ROWS_PER_SOURCE_TABLE + 1)
    if len(raw_rows) > MAX_DELTA_ROWS_PER_SOURCE_TABLE:
        raise InstyleDemoRebuildUnavailableError(
            f"incremental delta for {spec.key} exceeds the fixed "
            f"{MAX_DELTA_ROWS_PER_SOURCE_TABLE}-row safety ceiling"
        )
    return [
        {
            column.name: raw[index]
            for index, column in enumerate(columns)
        }
        for raw in raw_rows
    ]


def _insert_rows_if_missing(
    cursor: Any,
    spec: TableSpec,
    rows: list[dict[str, Any]],
) -> int:
    if not rows:
        return 0
    key_columns = _cursor_columns(spec)
    if not key_columns:
        raise InstyleDemoRebuildUnavailableError(
            f"{spec.key} has no primary key or identity cursor"
        )
    columns = [
        column
        for column in spec.copyable_columns
        if any(_has_row_key(row, column.name) for row in rows)
    ]
    if not columns:
        return 0
    before = _table_count(cursor, spec.key)
    identity = spec.identity_column
    identity_present = bool(
        identity and any(_has_row_key(row, identity.name) for row in rows)
    )
    if identity_present:
        cursor.execute(f"SET IDENTITY_INSERT {_quote_table(spec.key)} ON")
    try:
        key_predicate = " AND ".join(
            f"t.{_quote_identifier(column.name)}=?"
            for column in key_columns
        )
        sql = (
            f"INSERT INTO {_quote_table(spec.key)} "
            f"({', '.join(_quote_identifier(column.name) for column in columns)}) "
            f"SELECT {', '.join('?' for _ in columns)} "
            f"WHERE NOT EXISTS (SELECT 1 FROM {_quote_table(spec.key)} t "
            f"WHERE {key_predicate})"
        )
        values = [
            (
                *(_row_value(row, column.name) for column in columns),
                *(_row_value(row, column.name) for column in key_columns),
            )
            for row in rows
        ]
        try:
            cursor.fast_executemany = True
        except Exception:
            pass
        for start in range(0, len(values), BATCH_ROWS):
            cursor.executemany(sql, values[start : start + BATCH_ROWS])
    finally:
        if identity_present:
            cursor.execute(f"SET IDENTITY_INSERT {_quote_table(spec.key)} OFF")
    after = _table_count(cursor, spec.key)
    return after - before


def _repair_target_product_orphans(
    cursor: Any,
    target: DatabaseSnapshot,
) -> int:
    products = _find_table(target, "Products")
    total = 0
    lookup = {spec.name.casefold(): spec for spec in target.tables.values()}
    for table_name, column_name in PRODUCT_REFERENCE_COLUMNS.items():
        spec = lookup.get(table_name)
        if spec is None or not _has_column(spec, column_name):
            continue
        actual_column = next(
            column.name
            for column in spec.columns
            if column.name.casefold() == column_name.casefold()
        )
        before = _orphan_count(cursor, spec, actual_column, products)
        if not before:
            continue
        cursor.execute(
            f"UPDATE x SET {_quote_identifier(actual_column)}=m.[TargetProductID] "
            f"FROM {_quote_table(spec.key)} x "
            f"LEFT JOIN {_quote_table(products.key)} p "
            f"ON p.[ProductID]=x.{_quote_identifier(actual_column)} "
            f"JOIN {_quote_table(PRODUCT_MAP_TABLE)} m ON "
            f"(m.[SourceTag]='A' AND "
            f"x.{_quote_identifier(actual_column)}=m.[SourceProductID] "
            f"AND x.{_quote_identifier(actual_column)}<{SOURCE_B_ID_OFFSET}) "
            f"OR (m.[SourceTag]='B' AND "
            f"x.{_quote_identifier(actual_column)}="
            f"m.[SourceProductID]+{SOURCE_B_ID_OFFSET}) "
            f"WHERE x.{_quote_identifier(actual_column)}>0 "
            "AND p.[ProductID] IS NULL"
        )
        after = _orphan_count(cursor, spec, actual_column, products)
        if after:
            raise InstyleDemoRebuildUnavailableError(
                f"product orphan repair left {after} rows in {spec.key}"
            )
        total += before
    return total


def _repair_fixed_target_invoice_links(cursor: Any) -> dict[str, int]:
    repairs = (
        (
            "dbo.Invoice_Products",
            "Invoice_Products_ID",
            INVOICE_PRODUCT_INVOICE_REPAIRS,
        ),
        (
            "dbo.Invoice_Employees",
            "Invoice_Employees_ID",
            INVOICE_EMPLOYEE_INVOICE_REPAIRS,
        ),
        (
            "dbo.Invoice_Payments",
            "Invoice_Payments_ID",
            INVOICE_PAYMENT_INVOICE_REPAIRS,
        ),
    )
    result: dict[str, int] = {}
    for table_key, row_id_column, mapping in repairs:
        updated = 0
        for row_id, invoice_id in mapping.items():
            target_row_id = row_id + SOURCE_B_ID_OFFSET
            target_invoice_id = invoice_id + SOURCE_B_ID_OFFSET
            cursor.execute(
                f"UPDATE {_quote_table(table_key)} SET [InvoiceID]=? "
                f"WHERE {_quote_identifier(row_id_column)}=? "
                "AND ([InvoiceID] IS NULL OR [InvoiceID]<>?)",
                [target_invoice_id, target_row_id, target_invoice_id],
            )
            if cursor.rowcount and cursor.rowcount > 0:
                updated += int(cursor.rowcount)
        result[table_key] = updated
    return result


def _readback(
    cursor: Any,
    target: DatabaseSnapshot,
    *,
    product_result: dict[str, Any],
    source_manifest: list[dict[str, Any]],
) -> dict[str, Any]:
    products = _find_table(target, "Products")
    product_rows = _table_count(cursor, products.key)
    duplicate_product_keys = _duplicate_product_key_count(cursor, products)
    orphan_rows = _target_product_orphan_count(cursor)
    invoice_product_null_invoices = int(
        cursor.execute(
            "SELECT COUNT_BIG(*) FROM [dbo].[Invoice_Products] "
            "WHERE [InvoiceID] IS NULL"
        ).fetchone()[0]
    )
    placeholder_gaps = int(
        cursor.execute(
            f"SELECT COUNT_BIG(*) FROM {_quote_table(PRODUCT_MAP_TABLE)} m "
            f"JOIN {_quote_table(products.key)} p "
            "ON p.[ProductID]=m.[TargetProductID] "
            "WHERE m.[IsPlaceholder]=1 AND ("
            "NULLIF(LTRIM(RTRIM(p.[ProductName])),'') IS NULL OR "
            "NULLIF(LTRIM(RTRIM(p.[SKU])),'') IS NULL OR "
            "NULLIF(LTRIM(RTRIM(p.[BarcodeNumber])),'') IS NULL)"
        ).fetchone()[0]
    )
    fixed_rows = _fixed_invoice_product_readback(cursor)
    if duplicate_product_keys:
        raise InstyleDemoRebuildUnavailableError(
            "target contains duplicate nonblank Nova product keys"
        )
    if orphan_rows:
        raise InstyleDemoRebuildUnavailableError(
            f"target contains {orphan_rows} orphaned product references"
        )
    if invoice_product_null_invoices:
        raise InstyleDemoRebuildUnavailableError(
            "target Invoice_Products still contains blank InvoiceID values"
        )
    if placeholder_gaps:
        raise InstyleDemoRebuildUnavailableError(
            "one or more inactive missing-product rows has a blank Nova "
            "ProductName, SKU, or BarcodeNumber"
        )
    if fixed_rows != len(INVOICE_PRODUCT_INVOICE_REPAIRS):
        raise InstyleDemoRebuildUnavailableError(
            "the eleven fixed Instyle invoice-product links did not read back"
        )
    location_row = cursor.execute(
        "SELECT (SELECT COUNT_BIG(*) FROM [dbo].[Locations]),"
        "(SELECT COUNT_BIG(*) FROM [dbo].[Regions]),"
        "(SELECT COUNT_BIG(*) FROM [dbo].[InventoryHistoryItem])"
    ).fetchone()
    return {
        "productRows": product_rows,
        "expectedProductRows": int(product_result["expectedTargetProducts"]),
        "duplicateNonblankProductKeys": duplicate_product_keys,
        "productOrphanRows": orphan_rows,
        "invoiceProductsWithBlankInvoiceId": invoice_product_null_invoices,
        "fixedInvoiceProductRows": fixed_rows,
        "placeholderRequiredFieldGaps": placeholder_gaps,
        "locations": int(location_row[0] or 0),
        "regions": int(location_row[1] or 0),
        "inventoryHistoryItemRowsPreserved": int(location_row[2] or 0),
        "sourceManifestHash": _sha256_json(source_manifest),
    }


def _apply_fixed_source_repairs(
    source_name: str,
    table_name: str,
    row: dict[str, Any],
) -> None:
    if source_name != SOURCE_B_USERNAME:
        return
    definitions = {
        "invoice_products": (
            "Invoice_Products_ID",
            INVOICE_PRODUCT_INVOICE_REPAIRS,
        ),
        "invoice_employees": (
            "Invoice_Employees_ID",
            INVOICE_EMPLOYEE_INVOICE_REPAIRS,
        ),
        "invoice_payments": (
            "Invoice_Payments_ID",
            INVOICE_PAYMENT_INVOICE_REPAIRS,
        ),
    }
    definition = definitions.get(table_name.casefold())
    if definition is None:
        return
    column_name, mapping = definition
    row_id = _required_int(_row_value(row, column_name), column_name)
    if row_id in mapping:
        _set_row_value(row, "InvoiceID", mapping[row_id])


def _ensure_product_map_table(cursor: Any) -> None:
    cursor.execute(
        f"IF OBJECT_ID('{PRODUCT_MAP_TABLE}','U') IS NULL "
        f"CREATE TABLE {_quote_table(PRODUCT_MAP_TABLE)} ("
        "[SourceTag] char(1) NOT NULL,"
        "[SourceProductID] int NOT NULL,"
        "[TargetProductID] int NOT NULL,"
        "[KeyHash] char(64) NOT NULL,"
        "[IsPlaceholder] bit NOT NULL,"
        "[UpdatedAtUtc] datetime2(7) NOT NULL,"
        "CONSTRAINT [PK___codex_instyle_core_product_map] "
        "PRIMARY KEY ([SourceTag],[SourceProductID]))"
    )


def _read_product_map(cursor: Any) -> dict[tuple[str, int], int]:
    cursor.execute(
        f"SELECT [SourceTag],[SourceProductID],[TargetProductID] "
        f"FROM {_quote_table(PRODUCT_MAP_TABLE)}"
    )
    output: dict[tuple[str, int], int] = {}
    for row in cursor.fetchall():
        source_name = (
            SOURCE_A_USERNAME if str(row[0]).strip() == "A" else SOURCE_B_USERNAME
        )
        output[(source_name, int(row[1]))] = int(row[2])
    return output


def _write_product_map(
    cursor: Any,
    rows: list[tuple[str, int, int, str, bool]],
) -> None:
    if not rows:
        return
    statement = (
        f"UPDATE {_quote_table(PRODUCT_MAP_TABLE)} SET "
        "[TargetProductID]=?,[KeyHash]=?,[IsPlaceholder]=?,"
        "[UpdatedAtUtc]=SYSUTCDATETIME() "
        "WHERE [SourceTag]=? AND [SourceProductID]=?;"
        f"IF @@ROWCOUNT=0 INSERT INTO {_quote_table(PRODUCT_MAP_TABLE)} "
        "([SourceTag],[SourceProductID],[TargetProductID],[KeyHash],"
        "[IsPlaceholder],[UpdatedAtUtc]) "
        "VALUES (?,?,?,?,?,SYSUTCDATETIME())"
    )
    values = [
        (
            target_id,
            key_hash,
            is_placeholder,
            source_tag,
            source_id,
            source_tag,
            source_id,
            target_id,
            key_hash,
            is_placeholder,
        )
        for source_tag, source_id, target_id, key_hash, is_placeholder in rows
    ]
    try:
        cursor.fast_executemany = True
    except Exception:
        pass
    for start in range(0, len(values), BATCH_ROWS):
        cursor.executemany(statement, values[start : start + BATCH_ROWS])


def _read_latest_checkpoints(
    cursor: Any,
) -> dict[tuple[str, str], list[Any]]:
    cursor.execute(
        f"WITH c AS (SELECT [SourceTag],[TableName],[RangeEndJson],"
        "ROW_NUMBER() OVER(PARTITION BY [SourceTag],[TableName] "
        "ORDER BY [CheckpointID] DESC) rn "
        f"FROM {_quote_table(CHECKPOINT_TABLE)}) "
        "SELECT [SourceTag],[TableName],[RangeEndJson] FROM c WHERE rn=1"
    )
    output: dict[tuple[str, str], list[Any]] = {}
    for row in cursor.fetchall():
        values = json.loads(str(row[2]))
        output[(str(row[0]).strip(), str(row[1]).casefold())] = [
            item.get("value") for item in values if isinstance(item, dict)
        ]
    return output


def _write_checkpoint(
    cursor: Any,
    *,
    run_id: str,
    source_tag: str,
    table_name: str,
    range_start: list[Any],
    range_end: list[Any],
    rows_committed: int,
) -> None:
    start_json = (
        json.dumps(_checkpoint_values(range_start), separators=(",", ":"))
        if range_start
        else None
    )
    end_json = json.dumps(
        _checkpoint_values(range_end),
        separators=(",", ":"),
    )
    cursor.execute(
        f"INSERT INTO {_quote_table(CHECKPOINT_TABLE)} "
        "([RunID],[SourceTag],[TableName],[RangeStartJson],[RangeEndJson],"
        "[RangeEndHash],[RowsCommitted],[CompletedAtUtc]) "
        "VALUES (?,?,?,?,?,?,?,SYSUTCDATETIME())",
        [
            run_id,
            source_tag,
            table_name,
            start_json,
            end_json,
            hashlib.sha256(end_json.encode("utf-8")).hexdigest(),
            rows_committed,
        ],
    )


def _checkpoint_values(values: list[Any]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for value in values:
        if isinstance(value, bool):
            type_name = "bit"
        elif isinstance(value, int):
            type_name = "int"
        else:
            type_name = "string"
        output.append({"type": type_name, "value": _manifest_value(value)})
    return output


def _checkpoint_manifest(cursor: Any) -> list[dict[str, Any]]:
    cursor.execute(
        f"WITH c AS (SELECT [SourceTag],[TableName],[RangeEndJson],"
        "[RowsCommitted],[CompletedAtUtc],"
        "ROW_NUMBER() OVER(PARTITION BY [SourceTag],[TableName] "
        "ORDER BY [CheckpointID] DESC) rn "
        f"FROM {_quote_table(CHECKPOINT_TABLE)}) "
        "SELECT [SourceTag],[TableName],[RangeEndJson],[RowsCommitted],"
        "[CompletedAtUtc] FROM c WHERE rn=1 ORDER BY [TableName],[SourceTag]"
    )
    return [
        {
            "sourceTag": str(row[0]).strip(),
            "table": str(row[1]),
            "rangeEnd": str(row[2]),
            "rowsCommitted": int(row[3] or 0),
            "completedAt": row[4].isoformat() if row[4] else "",
        }
        for row in cursor.fetchall()
    ]


def _read_rows(cursor: Any, spec: TableSpec) -> list[dict[str, Any]]:
    columns = list(spec.copyable_columns)
    cursor.execute(
        "SELECT "
        + ", ".join(_quote_identifier(column.name) for column in columns)
        + f" FROM {_quote_table(spec.key)}"
    )
    return [
        {
            column.name: raw[index]
            for index, column in enumerate(columns)
        }
        for raw in cursor.fetchall()
    ]


def _read_product_index_rows(
    cursor: Any,
    spec: TableSpec,
) -> list[dict[str, Any]]:
    """Read only the five small fields needed to choose product mappings."""

    required_names = ("ProductID", *PRODUCT_KEY_COLUMNS)
    by_name = {column.name.casefold(): column for column in spec.columns}
    columns = []
    for required_name in required_names:
        column = by_name.get(required_name.casefold())
        if column is None:
            raise InstyleDemoRebuildUnavailableError(
                f"{spec.key} is missing required product field {required_name}"
            )
        columns.append(column)
    cursor.execute(
        "SELECT "
        + ", ".join(_quote_identifier(column.name) for column in columns)
        + f" FROM {_quote_table(spec.key)}"
    )
    return [
        {
            column.name: raw[index]
            for index, column in enumerate(columns)
        }
        for raw in cursor.fetchall()
    ]


def _read_exact_integer_rows(
    cursor: Any,
    spec: TableSpec,
    column_name: str,
    values: list[int],
) -> list[dict[str, Any]]:
    if not values:
        return []
    actual = next(
        column.name
        for column in spec.columns
        if column.name.casefold() == column_name.casefold()
    )
    columns = list(spec.copyable_columns)
    cursor.execute(
        "SELECT "
        + ", ".join(_quote_identifier(column.name) for column in columns)
        + f" FROM {_quote_table(spec.key)} "
        f"WHERE {_quote_identifier(actual)} IN "
        f"({','.join('?' for _ in values)})",
        values,
    )
    return [
        {
            column.name: raw[index]
            for index, column in enumerate(columns)
        }
        for raw in cursor.fetchall()
    ]


def _last_cursor_values(
    rows: list[dict[str, Any]],
    columns: tuple[ColumnSpec, ...],
) -> list[Any]:
    if not rows:
        return []
    return list(
        max(
            (
                tuple(_row_value(row, column.name) for column in columns)
                for row in rows
            )
        )
    )


def _product_key(row: dict[str, Any]) -> tuple[str, str, str, str]:
    return tuple(
        _normalize_product_value(_row_value(row, name))
        for name in PRODUCT_KEY_COLUMNS
    )


def _source_product_id(row: dict[str, Any]) -> int:
    return _required_int(_row_value(row, "ProductID"), "ProductID")


def _source_tag(source_name: str) -> str:
    return "A" if source_name == SOURCE_A_USERNAME else "B"


def _table_count(cursor: Any, table_key: str) -> int:
    row = cursor.execute(
        f"SELECT COUNT_BIG(*) FROM {_quote_table(table_key)}"
    ).fetchone()
    return int(row[0] or 0) if row else 0


def _orphan_count(
    cursor: Any,
    spec: TableSpec,
    product_column: str,
    products: TableSpec,
) -> int:
    row = cursor.execute(
        f"SELECT COUNT_BIG(*) FROM {_quote_table(spec.key)} x "
        f"LEFT JOIN {_quote_table(products.key)} p "
        f"ON p.[ProductID]=x.{_quote_identifier(product_column)} "
        f"WHERE x.{_quote_identifier(product_column)}>0 "
        "AND p.[ProductID] IS NULL"
    ).fetchone()
    return int(row[0] or 0) if row else 0


def _target_product_orphan_count(cursor: Any) -> int:
    rows = cursor.execute(
        "SELECT SUM(v.[Orphans]) FROM ("
        "SELECT COUNT_BIG(*) [Orphans] FROM [dbo].[Coupons_Products] x "
        "LEFT JOIN [dbo].[Products] p ON p.[ProductID]=x.[ProductID] "
        "WHERE x.[ProductID]>0 AND p.[ProductID] IS NULL UNION ALL "
        "SELECT COUNT_BIG(*) FROM [dbo].[CustomerOrders_Products] x "
        "LEFT JOIN [dbo].[Products] p ON p.[ProductID]=x.[ProductID] "
        "WHERE x.[ProductID]>0 AND p.[ProductID] IS NULL UNION ALL "
        "SELECT COUNT_BIG(*) FROM [dbo].[Inventory] x "
        "LEFT JOIN [dbo].[Products] p ON p.[ProductID]=x.[ProductID] "
        "WHERE x.[ProductID]>0 AND p.[ProductID] IS NULL UNION ALL "
        "SELECT COUNT_BIG(*) FROM [dbo].[Inventory_Counts_Products] x "
        "LEFT JOIN [dbo].[Products] p ON p.[ProductID]=x.[ProductID] "
        "WHERE x.[ProductID]>0 AND p.[ProductID] IS NULL UNION ALL "
        "SELECT COUNT_BIG(*) FROM [dbo].[Inventory_Damage] x "
        "LEFT JOIN [dbo].[Products] p ON p.[ProductID]=x.[ProductID] "
        "WHERE x.[ProductID]>0 AND p.[ProductID] IS NULL UNION ALL "
        "SELECT COUNT_BIG(*) FROM [dbo].[Inventory_Transactions] x "
        "LEFT JOIN [dbo].[Products] p ON p.[ProductID]=x.[ProductID] "
        "WHERE x.[ProductID]>0 AND p.[ProductID] IS NULL UNION ALL "
        "SELECT COUNT_BIG(*) FROM [dbo].[InventoryHistoryItem] x "
        "LEFT JOIN [dbo].[Products] p ON p.[ProductID]=x.[OriginalProductId] "
        "WHERE x.[OriginalProductId]>0 AND p.[ProductID] IS NULL UNION ALL "
        "SELECT COUNT_BIG(*) FROM [dbo].[Invoice_Products] x "
        "LEFT JOIN [dbo].[Products] p ON p.[ProductID]=x.[ProductID] "
        "WHERE x.[ProductID]>0 AND p.[ProductID] IS NULL UNION ALL "
        "SELECT COUNT_BIG(*) FROM [dbo].[Invoice_Refunds] x "
        "LEFT JOIN [dbo].[Products] p ON p.[ProductID]=x.[ProductID] "
        "WHERE x.[ProductID]>0 AND p.[ProductID] IS NULL UNION ALL "
        "SELECT COUNT_BIG(*) FROM [dbo].[Pending_Invoice_Product] x "
        "LEFT JOIN [dbo].[Products] p ON p.[ProductID]=x.[ProductID] "
        "WHERE x.[ProductID]>0 AND p.[ProductID] IS NULL UNION ALL "
        "SELECT COUNT_BIG(*) FROM [dbo].[PriceLists_Items] x "
        "LEFT JOIN [dbo].[Products] p ON p.[ProductID]=x.[ProductID] "
        "WHERE x.[ProductID]>0 AND p.[ProductID] IS NULL UNION ALL "
        "SELECT COUNT_BIG(*) FROM [dbo].[ProductFavorites] x "
        "LEFT JOIN [dbo].[Products] p ON p.[ProductID]=x.[ProductID] "
        "WHERE x.[ProductID]>0 AND p.[ProductID] IS NULL UNION ALL "
        "SELECT COUNT_BIG(*) FROM [dbo].[Quote_Products] x "
        "LEFT JOIN [dbo].[Products] p ON p.[ProductID]=x.[ProductID] "
        "WHERE x.[ProductID]>0 AND p.[ProductID] IS NULL UNION ALL "
        "SELECT COUNT_BIG(*) FROM [dbo].[Refunds_Products] x "
        "LEFT JOIN [dbo].[Products] p ON p.[ProductID]=x.[ProductID] "
        "WHERE x.[ProductID]>0 AND p.[ProductID] IS NULL UNION ALL "
        "SELECT COUNT_BIG(*) FROM [dbo].[StorageOrders_Products] x "
        "LEFT JOIN [dbo].[Products] p ON p.[ProductID]=x.[ProductID] "
        "WHERE x.[ProductID]>0 AND p.[ProductID] IS NULL"
        ") v"
    ).fetchone()
    return int(rows[0] or 0) if rows else 0


def _duplicate_product_key_count(cursor: Any, products: TableSpec) -> int:
    row = cursor.execute(
        "WITH p AS (SELECT "
        "UPPER(LTRIM(RTRIM(ISNULL([ProductName],'')))) n1,"
        "UPPER(LTRIM(RTRIM(ISNULL([BarcodeNumber],'')))) n2,"
        "UPPER(LTRIM(RTRIM(ISNULL([BarcodeNumber2],'')))) n3,"
        "UPPER(LTRIM(RTRIM(ISNULL([SKU],'')))) n4 "
        f"FROM {_quote_table(products.key)}) "
        "SELECT COUNT_BIG(*) FROM (SELECT n1,n2,n3,n4 FROM p "
        "WHERE n1<>'' OR n2<>'' OR n3<>'' OR n4<>'' "
        "GROUP BY n1,n2,n3,n4 HAVING COUNT_BIG(*)>1) d"
    ).fetchone()
    return int(row[0] or 0) if row else 0


def _fixed_invoice_product_readback(cursor: Any) -> int:
    predicates = " OR ".join(
        "([Invoice_Products_ID]=? AND [InvoiceID]=?)"
        for _ in INVOICE_PRODUCT_INVOICE_REPAIRS
    )
    parameters: list[int] = []
    for row_id, invoice_id in INVOICE_PRODUCT_INVOICE_REPAIRS.items():
        parameters.extend(
            [
                row_id + SOURCE_B_ID_OFFSET,
                invoice_id + SOURCE_B_ID_OFFSET,
            ]
        )
    row = cursor.execute(
        "SELECT COUNT_BIG(*) FROM [dbo].[Invoice_Products] WHERE "
        + predicates,
        parameters,
    ).fetchone()
    return int(row[0] or 0) if row else 0


def _manifest_value(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _idempotency_key(value: str) -> str:
    clean = str(value or "").strip()
    if not IDEMPOTENCY_KEY.fullmatch(clean):
        raise InstyleDemoRebuildScopeError(
            "idempotency_key must be a stable 8-200 character operation identifier"
        )
    return clean


def _preview_result(preview: dict[str, Any], *, replay: bool) -> dict[str, Any]:
    target = dict(preview.get("target") or {})
    return {
        "ok": True,
        "operation": OPERATION_TOOLS[0],
        "status": "previewed",
        "replay": replay,
        "idempotencyKey": preview.get("idempotencyKey"),
        "previewHash": preview.get("planHash"),
        "fixedSources": [SOURCE_A_USERNAME, SOURCE_B_USERNAME],
        "fixedTarget": TARGET_USERNAME,
        "sourceDatabasesReadOnly": True,
        "sourceRowsMayAdvance": True,
        "targetBackupRequired": False,
        "copyMode": preview.get("copyMode"),
        "inventoryHistoryItemAction": preview.get("inventoryHistoryItemAction"),
        "targetBaseline": {
            "productRows": target.get("productRows"),
            "invoiceProductRows": target.get("invoiceProductRows"),
            "inventoryHistoryItemRows": target.get("inventoryHistoryItemRows"),
            "productOrphanRows": target.get("productOrphanRows"),
            "checkpointRows": target.get("checkpointRows"),
        },
        "nextStep": (
            "Call nova_sql_instyle_demo_sync_execute with this same "
            "idempotency key and exact preview hash."
        ),
    }


def _completed_result(
    receipt: dict[str, Any],
    *,
    replay: bool,
) -> dict[str, Any]:
    return {
        "ok": True,
        "operation": OPERATION_TOOLS[1],
        "status": receipt.get("status"),
        "replay": replay,
        "idempotencyKey": receipt.get("idempotencyKey"),
        "previewHash": receipt.get("planHash"),
        "runId": receipt.get("runId"),
        "fixedSources": receipt.get("fixedSources"),
        "fixedTarget": receipt.get("fixedTarget"),
        "sourceDatabasesReadOnly": receipt.get("sourceDatabasesReadOnly"),
        "sourceRowsMayAdvance": receipt.get("sourceRowsMayAdvance", True),
        "sourceDataAdvancedDuringRun": receipt.get(
            "sourceDataAdvancedDuringRun"
        ),
        "targetBackupCreated": receipt.get("targetBackupCreated"),
        "targetBackupRequired": receipt.get("targetBackupRequired"),
        "inventoryHistoryItemAction": receipt.get(
            "inventoryHistoryItemAction"
        ),
        "productSync": receipt.get("productSync"),
        "orphanRowsRepaired": receipt.get("orphanRowsRepaired"),
        "incrementalCopy": receipt.get("incrementalCopy"),
        "fixedInvoiceLinkRepairs": receipt.get("fixedInvoiceLinkRepairs"),
        "readback": receipt.get("readback"),
        "postWriteReadbackVerified": receipt.get(
            "postWriteReadbackVerified"
        ),
    }


def execution_failure_result(
    *,
    idempotency_key: str,
    preview_hash: str,
    error: Exception,
) -> dict[str, Any]:
    """Return a bounded diagnostic and force same-key status reconciliation."""

    message = str(error or "").strip()
    if not message:
        message = repr(error).strip()
    message = re.sub(
        r"(?i)(pwd|password|token|authorization|secret)\s*=\s*[^;\s]+",
        r"\1=[redacted]",
        message,
    )
    message = re.sub(
        r"(?i)(?:uid|user\s*id)\s*=\s*[^;\s]+",
        "uid=[redacted]",
        message,
    )
    return {
        "ok": False,
        "operation": OPERATION_TOOLS[1],
        "status": "execution_failed_reconciliation_required",
        "idempotencyKey": str(idempotency_key or "").strip(),
        "previewHash": str(preview_hash or "").strip().lower(),
        "errorType": type(error).__name__,
        "error": message[:2000] or "unknown execution failure",
        "safeToRetry": False,
        "nextStep": (
            "Call nova_sql_instyle_demo_sync_status with this same idempotency "
            "key before any retry."
        ),
    }


def _public_target_baseline(value: Any) -> dict[str, Any]:
    target = dict(value or {})
    return {
        "productRows": target.get("productRows"),
        "invoiceProductRows": target.get("invoiceProductRows"),
        "inventoryHistoryItemRows": target.get("inventoryHistoryItemRows"),
        "productOrphanRows": target.get("productOrphanRows"),
        "checkpointRows": target.get("checkpointRows"),
        "checkpointHash": target.get("checkpointHash"),
    }


def _reconciliation_readback(
    cursor: Any,
    target: DatabaseSnapshot,
    *,
    preview: dict[str, Any],
) -> dict[str, Any]:
    products = _find_table(target, "Products")
    duplicate_product_keys = _duplicate_product_key_count(cursor, products)
    orphan_rows = _target_product_orphan_count(cursor)
    invoice_product_null_invoices = int(
        cursor.execute(
            "SELECT COUNT_BIG(*) FROM [dbo].[Invoice_Products] "
            "WHERE [InvoiceID] IS NULL"
        ).fetchone()[0]
    )
    map_exists = bool(
        cursor.execute(
            f"SELECT CASE WHEN OBJECT_ID('{PRODUCT_MAP_TABLE}','U') IS NULL "
            "THEN 0 ELSE 1 END"
        ).fetchone()[0]
    )
    placeholder_gaps: int | None = None
    if map_exists:
        placeholder_gaps = int(
            cursor.execute(
                f"SELECT COUNT_BIG(*) FROM {_quote_table(PRODUCT_MAP_TABLE)} m "
                f"JOIN {_quote_table(products.key)} p "
                "ON p.[ProductID]=m.[TargetProductID] "
                "WHERE m.[IsPlaceholder]=1 AND ("
                "NULLIF(LTRIM(RTRIM(p.[ProductName])),'') IS NULL OR "
                "NULLIF(LTRIM(RTRIM(p.[SKU])),'') IS NULL OR "
                "NULLIF(LTRIM(RTRIM(p.[BarcodeNumber])),'') IS NULL)"
            ).fetchone()[0]
        )
    fixed_rows = _fixed_invoice_product_readback(cursor)
    location_row = cursor.execute(
        "SELECT (SELECT COUNT_BIG(*) FROM [dbo].[Locations]),"
        "(SELECT COUNT_BIG(*) FROM [dbo].[Regions]),"
        "(SELECT COUNT_BIG(*) FROM [dbo].[InventoryHistoryItem])"
    ).fetchone()
    preview_history = int(
        dict(preview.get("target") or {}).get("inventoryHistoryItemRows") or 0
    )
    history_rows = int(location_row[2] or 0)
    completion_verified = bool(
        map_exists
        and duplicate_product_keys == 0
        and orphan_rows == 0
        and invoice_product_null_invoices == 0
        and placeholder_gaps == 0
        and fixed_rows == len(INVOICE_PRODUCT_INVOICE_REPAIRS)
        and int(location_row[0] or 0) == 44
        and int(location_row[1] or 0) == 4
        and history_rows == preview_history
    )
    return {
        "duplicateNonblankProductKeys": duplicate_product_keys,
        "productOrphanRows": orphan_rows,
        "invoiceProductsWithBlankInvoiceId": invoice_product_null_invoices,
        "fixedInvoiceProductRows": fixed_rows,
        "placeholderRequiredFieldGaps": placeholder_gaps,
        "productMapPresent": map_exists,
        "locations": int(location_row[0] or 0),
        "regions": int(location_row[1] or 0),
        "inventoryHistoryItemRowsPreserved": history_rows,
        "completionVerified": completion_verified,
    }
