from __future__ import annotations

import hashlib
import json
import os
import re
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

# AgentChat/coding_agent 2026-08-06T10:12:33Z

OPERATION_NAME = "account_copy_v1"
IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_$#@]{0,127}$")
COMPANY_USERNAME = re.compile(r"^[A-Za-z0-9_]{1,80}$")
IDEMPOTENCY_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{7,199}$")
PLAN_ID = re.compile(r"^[0-9a-f]{64}$")
SECRET_COLUMN = re.compile(
    r"(?:password|passcode|secret|securitykey|api_?key|token|authorization|cookie|"
    r"deviceconfig|merchantnumber|merchanttransid|merchantloginid|employee_ssn|"
    r"cardnumber|card_?number|cvv|trackdata)",
    re.IGNORECASE,
)
BLOCKED_TABLE = re.compile(
    r"(?:credential|password|secret|token|auth|session|paymentprofile|"
    r"merchantcredential)",
    re.IGNORECASE,
)
INTERNAL_TABLE_PREFIXES = ("__codex_", "__nova_", "sys")
INTEGER_TYPES = frozenset({"bigint", "int", "smallint", "tinyint"})
ROWVERSION_TYPES = frozenset({"rowversion", "timestamp"})
MAX_TABLES = 40
MAX_RELATIONSHIPS = 120
MAX_FILTER_NODES = 100
MAX_FILTER_DEPTH = 4
MAX_PLAN_ROWS = 5_000_000


class AccountCopyScopeError(ValueError):
    """A requested account copy is outside the guarded copy contract."""


class AccountCopyUnavailableError(RuntimeError):
    """The guarded account-copy broker could not complete safely."""


@dataclass(frozen=True)
class ColumnMeta:
    name: str
    ordinal: int
    type_name: str
    max_length: int
    precision: int
    scale: int
    nullable: bool
    identity: bool
    computed: bool
    generated: bool
    has_default: bool
    primary_key_ordinal: int = 0

    @property
    def copyable(self) -> bool:
        return (
            not self.computed
            and not self.generated
            and self.type_name.casefold() not in ROWVERSION_TYPES
            and not SECRET_COLUMN.search(self.name)
        )


@dataclass(frozen=True)
class RelationshipMeta:
    column: str
    referenced_table: str
    referenced_column: str


@dataclass(frozen=True)
class TableMeta:
    schema: str
    name: str
    columns: tuple[ColumnMeta, ...]
    relationships: tuple[RelationshipMeta, ...] = ()

    @property
    def key(self) -> str:
        return f"{self.schema}.{self.name}"

    @property
    def primary_key(self) -> tuple[ColumnMeta, ...]:
        return tuple(
            sorted(
                (column for column in self.columns if column.primary_key_ordinal),
                key=lambda column: column.primary_key_ordinal,
            )
        )

    @property
    def column_lookup(self) -> dict[str, ColumnMeta]:
        return {column.name.casefold(): column for column in self.columns}


def _copy_key(table: TableMeta) -> ColumnMeta:
    """Return the one integer row key the broker can safely crosswalk.

    A few legacy Nova link tables have a single integer IDENTITY column but no
    declared primary-key constraint.  Treating that server-generated identity
    as the row key preserves the same relationship-safe behavior without
    weakening the contract for tables that have neither shape.
    """

    declared = table.primary_key
    if len(declared) == 1 and declared[0].type_name.casefold() in INTEGER_TYPES:
        return declared[0]
    if not declared:
        identities = tuple(
            column
            for column in table.columns
            if column.identity and column.type_name.casefold() in INTEGER_TYPES
        )
        if len(identities) == 1:
            return identities[0]
    raise AccountCopyScopeError(
        f"{table.key} needs one declared integer primary key or one integer identity row key "
        "for relationship-safe account copying"
    )


@dataclass(frozen=True)
class CompiledTable:
    key: str
    source: TableMeta
    target: TableMeta
    mode: str
    columns: tuple[str, ...]
    match_columns: tuple[str, ...]
    identity_strategy: str
    filter_spec: Any
    overrides: dict[str, Any]
    relationships: tuple[RelationshipMeta, ...]
    map_table: str


class AccountCopyOperation:
    """Build and execute server-owned, schema-aware account-copy plans."""

    def __init__(
        self,
        *,
        connect: Callable[[str, bool], Any],
        preview_guarded: Callable[..., dict[str, Any]],
        execute_guarded: Callable[..., dict[str, Any]],
        guarded_status: Callable[[str, str], dict[str, Any]],
        state_dir: str | Path,
    ) -> None:
        self._connect = connect
        self._preview_guarded = preview_guarded
        self._execute_guarded = execute_guarded
        self._guarded_status = guarded_status
        self._state_dir = Path(state_dir).expanduser().resolve() / OPERATION_NAME

    def capabilities(self) -> dict[str, Any]:
        return {
            "configured": True,
            "operation": OPERATION_NAME,
            "writeOwner": "coding_agent",
            "arbitrarySqlAccepted": False,
            "accountSpecificScriptRequired": False,
            "schemaDiscovered": True,
            "currentAndFutureAccountsSupported": True,
            "maximumTables": MAX_TABLES,
            "supportedModes": ["insert_missing", "update_existing", "upsert"],
            "identityStrategies": ["preserve", "remap"],
            "relationshipSources": ["declared_foreign_keys", "typed_relationship_overrides"],
            "protectedColumnsCopied": False,
            "protectedTablesCopied": False,
            "fullTargetTableBackups": True,
            "singleTransaction": True,
            "immutablePreviewRequired": True,
            "orphanReadbackRequired": True,
        }

    def preview(
        self,
        *,
        source_company_username: str,
        target_company_username: str,
        tables: list[dict[str, Any]],
        idempotency_key: str,
        ticket_number: str = "",
    ) -> dict[str, Any]:
        source = _company_username(source_company_username, "source_company_username")
        target = _company_username(target_company_username, "target_company_username")
        if source.casefold() == target.casefold():
            raise AccountCopyScopeError("source and target accounts must be different")
        clean_key = _idempotency_key(idempotency_key)
        clean_ticket = _ticket_number(ticket_number)
        request = _normalize_request(tables)

        compiled = self._compile(
            source=source,
            target=target,
            request=request,
            idempotency_key=clean_key,
            ticket_number=clean_ticket,
        )
        guarded_preview = self._preview_guarded(**compiled["guardedArgs"])
        plan_body = {
            "operation": OPERATION_NAME,
            "sourceCompanyUsername": source,
            "targetCompanyUsername": target,
            "ticketNumber": clean_ticket,
            "idempotencyKey": clean_key,
            "request": request,
            "schemaFingerprint": compiled["schemaFingerprint"],
            "guardedPlanHash": guarded_preview["planHash"],
            "guardedArgs": compiled["guardedArgs"],
            "summary": compiled["summary"],
        }
        plan_id = _digest(plan_body)
        record = {
            **plan_body,
            "planId": plan_id,
            "status": "previewed",
            "createdAtUtc": _utc_now(),
            "updatedAtUtc": _utc_now(),
        }
        _write_json(self._plan_path(plan_id), record, create_only=True)
        return _public_plan(record)

    def execute(self, *, plan_id: str) -> dict[str, Any]:
        clean_plan_id = _plan_id(plan_id)
        record = self._reconcile_record(self._read_plan(clean_plan_id))
        if record.get("status") == "completed" and isinstance(record.get("receipt"), dict):
            return _public_execution(record, replay=True)
        if record.get("status") == "needs_reconciliation":
            raise AccountCopyUnavailableError(
                "the prior account-copy execution may have committed; inspect account-copy status and target readback before any retry"
            )

        recompiled = self._compile(
            source=str(record["sourceCompanyUsername"]),
            target=str(record["targetCompanyUsername"]),
            request=list(record["request"]),
            idempotency_key=str(record["idempotencyKey"]),
            ticket_number=str(record.get("ticketNumber") or ""),
        )
        guarded_preview = self._preview_guarded(**recompiled["guardedArgs"])
        if (
            recompiled["schemaFingerprint"] != record.get("schemaFingerprint")
            or guarded_preview.get("planHash") != record.get("guardedPlanHash")
            or recompiled["guardedArgs"] != record.get("guardedArgs")
        ):
            raise AccountCopyScopeError(
                "source, target, schema, row scope, or relationship mapping changed after preview; create a new preview"
            )

        record["status"] = "executing"
        record["updatedAtUtc"] = _utc_now()
        _write_json(self._plan_path(clean_plan_id), record)
        try:
            receipt = self._execute_guarded(
                **recompiled["guardedArgs"],
                preview_hash=str(record["guardedPlanHash"]),
            )
        except Exception as exc:
            record["status"] = (
                "needs_reconciliation"
                if "committed" in str(exc).casefold() or "do not retry" in str(exc).casefold()
                else "failed_rolled_back"
            )
            record["failure"] = str(exc)[:1000]
            record["updatedAtUtc"] = _utc_now()
            _write_json(self._plan_path(clean_plan_id), record)
            raise

        record["status"] = "completed"
        record["receipt"] = receipt
        record["updatedAtUtc"] = _utc_now()
        _write_json(self._plan_path(clean_plan_id), record)
        return _public_execution(record, replay=False)

    def status(self, *, plan_id: str) -> dict[str, Any]:
        record = self._reconcile_record(self._read_plan(_plan_id(plan_id)))
        return _public_status(record)

    def _reconcile_record(self, record: dict[str, Any]) -> dict[str, Any]:
        guarded = self._guarded_status(
            str(record["idempotencyKey"]),
            str(record["guardedPlanHash"]),
        )
        record["guardedReceiptStatus"] = guarded.get("status", "not_found")
        if guarded.get("status") == "completed" and record.get("status") != "completed":
            record["status"] = "completed"
            record["receipt"] = guarded
            record["failure"] = ""
            record["updatedAtUtc"] = _utc_now()
            _write_json(self._plan_path(str(record["planId"])), record)
        elif guarded.get("status") == "committed_readback_failed":
            record["status"] = "needs_reconciliation"
            record["updatedAtUtc"] = _utc_now()
            _write_json(self._plan_path(str(record["planId"])), record)
        return record

    def _compile(
        self,
        *,
        source: str,
        target: str,
        request: list[dict[str, Any]],
        idempotency_key: str,
        ticket_number: str,
    ) -> dict[str, Any]:
        with closing(self._connect(target, True)) as connection:
            cursor = connection.cursor()
            actual = cursor.execute("SELECT DB_NAME()").fetchone()
            if not actual or str(actual[0] or "").casefold() != f"POS_{target}".casefold():
                raise AccountCopyUnavailableError("account-copy broker connected to an unexpected target")
            compiled, schema_fingerprint = _compile_tables(
                cursor,
                source=source,
                target=target,
                request=request,
            )
            statements, summary, expected_rows, verification_sql = _build_plan_sql(
                cursor,
                source=source,
                compiled=compiled,
            )
            try:
                connection.rollback()
            except Exception:
                pass

        if expected_rows > MAX_PLAN_ROWS:
            raise AccountCopyScopeError(
                f"account copy affects {expected_rows} rows, above the {MAX_PLAN_ROWS}-row account-copy ceiling"
            )
        guarded_args = {
            "company_username": target,
            "source_company_usernames": [source],
            "statements": statements,
            "verification_sql": verification_sql,
            "verification_parameters": [],
            "expected_affected_rows": expected_rows,
            "expected_verification_value": 0,
            "idempotency_key": idempotency_key,
        }
        summary = {
            **summary,
            "ticketNumber": ticket_number,
            "sourceCompanyUsername": source,
            "targetCompanyUsername": target,
            "expectedAffectedRows": expected_rows,
            "transactionMode": "single_transaction",
            "backupMode": "full_copy_of_every_changed_target_table",
            "protectedColumnsOmitted": True,
        }
        return {
            "guardedArgs": guarded_args,
            "summary": summary,
            "schemaFingerprint": schema_fingerprint,
        }

    def _plan_path(self, plan_id: str) -> Path:
        return self._state_dir / "plans" / f"{plan_id}.json"

    def _read_plan(self, plan_id: str) -> dict[str, Any]:
        path = self._plan_path(plan_id)
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise AccountCopyScopeError("account-copy plan was not found") from exc
        except Exception as exc:
            raise AccountCopyUnavailableError("account-copy plan could not be read safely") from exc
        if not isinstance(value, dict) or str(value.get("planId") or "") != plan_id:
            raise AccountCopyUnavailableError("account-copy plan record is invalid")
        body = {
            key: value[key]
            for key in (
                "operation",
                "sourceCompanyUsername",
                "targetCompanyUsername",
                "ticketNumber",
                "idempotencyKey",
                "request",
                "schemaFingerprint",
                "guardedPlanHash",
                "guardedArgs",
                "summary",
            )
        }
        if _digest(body) != plan_id:
            raise AccountCopyUnavailableError("account-copy plan integrity check failed")
        return value


def _normalize_request(tables: Any) -> list[dict[str, Any]]:
    if not isinstance(tables, list) or not 1 <= len(tables) <= MAX_TABLES:
        raise AccountCopyScopeError(f"tables must contain between 1 and {MAX_TABLES} entries")
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    relationship_count = 0
    for raw in tables:
        if not isinstance(raw, dict):
            raise AccountCopyScopeError("each table entry must be an object")
        unknown = set(raw) - {
            "table",
            "mode",
            "columns",
            "match_columns",
            "identity_strategy",
            "filter",
            "overrides",
            "relationships",
        }
        if unknown:
            raise AccountCopyScopeError(f"unsupported table fields: {', '.join(sorted(unknown))}")
        table = _table_key(raw.get("table"))
        if table.casefold() in seen:
            raise AccountCopyScopeError(f"table {table} is listed more than once")
        seen.add(table.casefold())
        mode = str(raw.get("mode") or "insert_missing").strip().casefold()
        if mode not in {"insert_missing", "update_existing", "upsert"}:
            raise AccountCopyScopeError(f"unsupported copy mode for {table}")
        strategy = str(raw.get("identity_strategy") or "preserve").strip().casefold()
        if strategy not in {"preserve", "remap"}:
            raise AccountCopyScopeError(f"unsupported identity strategy for {table}")
        columns = raw.get("columns", ["*"])
        if not isinstance(columns, list) or not columns or not all(isinstance(value, str) for value in columns):
            raise AccountCopyScopeError(f"columns for {table} must be a nonempty string list")
        match_columns = raw.get("match_columns", [])
        if not isinstance(match_columns, list) or not all(isinstance(value, str) for value in match_columns):
            raise AccountCopyScopeError(f"match_columns for {table} must be a string list")
        overrides = raw.get("overrides", {})
        if not isinstance(overrides, dict) or not all(isinstance(key, str) for key in overrides):
            raise AccountCopyScopeError(f"overrides for {table} must be an object")
        clean_overrides = {str(key): _json_scalar(value, f"{table}.{key}") for key, value in overrides.items()}
        relationships = raw.get("relationships", [])
        if not isinstance(relationships, list):
            raise AccountCopyScopeError(f"relationships for {table} must be a list")
        clean_relationships: list[dict[str, str]] = []
        for relationship in relationships:
            if not isinstance(relationship, dict) or set(relationship) != {
                "column",
                "references_table",
                "references_column",
            }:
                raise AccountCopyScopeError(
                    f"each relationship for {table} needs column, references_table, and references_column"
                )
            clean_relationships.append(
                {
                    "column": _identifier(relationship["column"]),
                    "references_table": _table_key(relationship["references_table"]),
                    "references_column": _identifier(relationship["references_column"]),
                }
            )
        relationship_count += len(clean_relationships)
        if relationship_count > MAX_RELATIONSHIPS:
            raise AccountCopyScopeError("the account-copy relationship ceiling was exceeded")
        filter_spec = _normalize_filter(raw.get("filter"), depth=0, counter=[0])
        output.append(
            {
                "table": table,
                "mode": mode,
                "columns": [_identifier(value) if value != "*" else "*" for value in columns],
                "match_columns": [_identifier(value) for value in match_columns],
                "identity_strategy": strategy,
                "filter": filter_spec,
                "overrides": clean_overrides,
                "relationships": clean_relationships,
            }
        )
    _require_invoice_source_location_scope(output)
    return output


def _require_invoice_source_location_scope(request: list[dict[str, Any]]) -> None:
    """Do not let a destination LocationID override silently widen invoice scope."""

    for item in request:
        if str(item["table"]).casefold() != "dbo.invoices":
            continue
        if not any(str(name).casefold() == "locationid" for name in item["overrides"]):
            continue
        if _conjunctive_filter_values(item["filter"], "LocationID") is None:
            raise AccountCopyScopeError(
                "dbo.Invoices with a LocationID destination override must also have an explicit "
                "source LocationID eq/in filter; the override changes the destination and does not scope the source"
            )


def _conjunctive_filter_values(filter_spec: dict[str, Any], column: str) -> tuple[Any, ...] | None:
    if "column" in filter_spec:
        if str(filter_spec["column"]).casefold() != column.casefold():
            return None
        if filter_spec["op"] == "eq":
            return (filter_spec.get("value"),)
        if filter_spec["op"] == "in":
            return tuple(filter_spec.get("value") or ()) or None
        return None
    if "all" in filter_spec:
        for child in filter_spec["all"]:
            values = _conjunctive_filter_values(child, column)
            if values is not None:
                return values
    return None


def _compile_tables(
    cursor: Any,
    *,
    source: str,
    target: str,
    request: list[dict[str, Any]],
) -> tuple[list[CompiledTable], str]:
    selected = {str(item["table"]).casefold(): str(item["table"]) for item in request}
    source_cache: dict[str, TableMeta] = {}
    target_cache: dict[str, TableMeta] = {}

    def source_meta(key: str) -> TableMeta:
        folded = key.casefold()
        if folded not in source_cache:
            source_cache[folded] = _read_table_meta(cursor, database=f"POS_{source}", table=key)
        return source_cache[folded]

    def target_meta(key: str) -> TableMeta:
        folded = key.casefold()
        if folded not in target_cache:
            target_cache[folded] = _read_table_meta(cursor, database="", table=key)
        return target_cache[folded]

    output: list[CompiledTable] = []
    for index, item in enumerate(request, start=1):
        key = str(item["table"])
        _require_business_table(key)
        source_table = source_meta(key)
        target_table = target_meta(key)
        source_columns = source_table.column_lookup
        target_columns = target_table.column_lookup
        if item["columns"] == ["*"]:
            columns = [
                target_column.name
                for target_column in target_table.columns
                if target_column.copyable
                and target_column.name.casefold() in source_columns
                and source_columns[target_column.name.casefold()].copyable
                and _compatible(source_columns[target_column.name.casefold()], target_column)
            ]
        else:
            columns = []
            for name in item["columns"]:
                source_column = _column(source_table, name)
                target_column = _column(target_table, name)
                if not source_column.copyable or not target_column.copyable:
                    raise AccountCopyScopeError(f"protected or generated column {key}.{name} cannot be copied")
                if not _compatible(source_column, target_column):
                    raise AccountCopyScopeError(f"source and target column types differ for {key}.{name}")
                columns.append(target_column.name)

        overrides: dict[str, Any] = {}
        for name, value in item["overrides"].items():
            target_column = _column(target_table, name)
            if not target_column.copyable:
                raise AccountCopyScopeError(f"protected or generated override {key}.{name} is not allowed")
            overrides[target_column.name] = value
            if target_column.name not in columns:
                columns.append(target_column.name)

        target_pk = _copy_key(target_table)
        source_pk = _copy_key(source_table)
        if target_pk.name.casefold() != source_pk.name.casefold():
            raise AccountCopyScopeError(
                f"{key} needs the same integer row key in source and target"
            )
        if target_pk.name not in columns:
            columns.insert(0, target_pk.name)

        match_columns = list(item["match_columns"]) or [target_pk.name]
        resolved_match: list[str] = []
        for name in match_columns:
            source_column = _column(source_table, name)
            target_column = _column(target_table, name)
            if not source_column.copyable or not target_column.copyable:
                raise AccountCopyScopeError(f"protected match column {key}.{name} is not allowed")
            if not _compatible(source_column, target_column):
                raise AccountCopyScopeError(f"match column types differ for {key}.{name}")
            resolved_match.append(target_column.name)
        if item["identity_strategy"] == "remap" and [value.casefold() for value in resolved_match] == [target_pk.name.casefold()]:
            raise AccountCopyScopeError(
                f"{key} identity remapping requires stable business match_columns, not only the primary key"
            )

        relationships: dict[str, RelationshipMeta] = {}
        for relationship in target_table.relationships:
            if relationship.referenced_table.casefold() in selected:
                relationships[relationship.column.casefold()] = relationship
        for raw in item["relationships"]:
            relationship = RelationshipMeta(
                column=_column(target_table, raw["column"]).name,
                referenced_table=_table_key(raw["references_table"]),
                referenced_column=_identifier(raw["references_column"]),
            )
            if relationship.referenced_table.casefold() not in selected:
                raise AccountCopyScopeError(
                    f"relationship {key}.{relationship.column} points to an unselected table"
                )
            relationships[relationship.column.casefold()] = relationship
        for relationship in relationships.values():
            source_column = _column(source_table, relationship.column)
            target_column = _column(target_table, relationship.column)
            parent_source = source_meta(relationship.referenced_table)
            parent_target = target_meta(relationship.referenced_table)
            parent_source_column = _column(parent_source, relationship.referenced_column)
            parent_target_column = _column(parent_target, relationship.referenced_column)
            if (
                source_column.type_name.casefold() not in INTEGER_TYPES
                or target_column.type_name.casefold() not in INTEGER_TYPES
                or not parent_source_column.primary_key_ordinal
                or not parent_target_column.primary_key_ordinal
            ):
                raise AccountCopyScopeError(
                    f"relationship {key}.{relationship.column} must reference the selected parent's integer primary key"
                )
            if relationship.column.casefold() not in {name.casefold() for name in columns}:
                raise AccountCopyScopeError(
                    f"relationship column {key}.{relationship.column} must be included in columns"
                )
        _validate_filter_columns(item["filter"], source_meta, key)

        selected_column_keys = {name.casefold() for name in columns}
        for target_column in target_table.columns:
            if (
                not target_column.nullable
                and not target_column.has_default
                and not target_column.identity
                and target_column.copyable
                and target_column.name.casefold() not in selected_column_keys
                and item["mode"] in {"insert_missing", "upsert"}
            ):
                raise AccountCopyScopeError(
                    f"required target column {key}.{target_column.name} must be included"
                )

        output.append(
            CompiledTable(
                key=key,
                source=source_table,
                target=target_table,
                mode=str(item["mode"]),
                columns=tuple(columns),
                match_columns=tuple(resolved_match),
                identity_strategy=str(item["identity_strategy"]),
                filter_spec=item["filter"],
                overrides=overrides,
                relationships=tuple(relationships.values()),
                map_table=f"#acm{index:02d}_{hashlib.sha256(key.casefold().encode()).hexdigest()[:8]}",
            )
        )

    ordered = _dependency_order(output)
    schema_value = {
        "source": [_table_schema_value(source_cache[key]) for key in sorted(source_cache)],
        "target": [_table_schema_value(target_cache[key]) for key in sorted(target_cache)],
        "order": [table.key for table in ordered],
    }
    return ordered, _digest(schema_value)


def _build_plan_sql(
    cursor: Any,
    *,
    source: str,
    compiled: list[CompiledTable],
) -> tuple[list[dict[str, Any]], dict[str, Any], int, str]:
    database = _quote_identifier(f"POS_{source}")
    maps = {table.key.casefold(): table for table in compiled}
    statements: list[dict[str, Any]] = []
    table_summaries: list[dict[str, Any]] = []

    for table in compiled:
        source_sql = f"{database}.{_quote_table(table.key)}"
        target_sql = _quote_table(table.key)
        copy_key = _copy_key(table.target)
        pk = copy_key.name
        filter_sql, filter_parameters = _filter_sql(
            table.filter_spec,
            source_database=database,
            root_table=table.source,
            alias="s",
        )
        partition = ", ".join(f"s.{_quote_identifier(name)}" for name in table.match_columns)
        target_join = " AND ".join(
            _null_safe_equals(f"t.{_quote_identifier(name)}", f"s.{_quote_identifier(name)}")
            for name in table.match_columns
        )
        if table.identity_strategy == "remap":
            generated_key = (
                f"b.[BaseKey] + DENSE_RANK() OVER (ORDER BY {partition})"
            )
        else:
            generated_key = f"MAX(s.{_quote_identifier(pk)}) OVER (PARTITION BY {partition})"
        winner = f"MAX(s.{_quote_identifier(pk)}) OVER (PARTITION BY {partition})"
        create_map_sql = (
            f"CREATE TABLE {table.map_table} ("
            "[SourceKey] bigint NOT NULL, [TargetKey] bigint NOT NULL, "
            "[IsNew] bit NOT NULL, [IsWinner] bit NOT NULL)"
        )
        map_sql = (
            f"INSERT INTO {table.map_table} ([SourceKey], [TargetKey], [IsNew], [IsWinner]) "
            f"SELECT CAST(s.{_quote_identifier(pk)} AS bigint), "
            f"CAST(COALESCE(t.{_quote_identifier(pk)}, {generated_key}) AS bigint) AS [TargetKey], "
            f"CAST(CASE WHEN t.{_quote_identifier(pk)} IS NULL THEN 1 ELSE 0 END AS bit) AS [IsNew], "
            f"CAST(CASE WHEN s.{_quote_identifier(pk)}={winner} THEN 1 ELSE 0 END AS bit) AS [IsWinner] "
            f"FROM {source_sql} AS s "
            f"CROSS JOIN (SELECT COALESCE(MAX({_quote_identifier(pk)}),0) AS [BaseKey] FROM {target_sql}) AS b "
            f"LEFT JOIN {target_sql} AS t ON {target_join} WHERE {filter_sql}"
        )
        cursor.execute(create_map_sql)
        cursor.execute(map_sql, filter_parameters)
        statements.append({"sql": create_map_sql, "parameters": []})
        statements.append({"sql": map_sql, "parameters": filter_parameters})

        counts = cursor.execute(
            f"SELECT COUNT_BIG(*),"
            "COALESCE(SUM(CASE WHEN [IsWinner]=1 THEN 1 ELSE 0 END),0),"
            "COALESCE(SUM(CASE WHEN [IsWinner]=1 AND [IsNew]=1 THEN 1 ELSE 0 END),0),"
            "COALESCE(SUM(CASE WHEN [IsWinner]=1 AND [IsNew]=0 THEN 1 ELSE 0 END),0) "
            f"FROM {table.map_table}"
        ).fetchone()
        scoped_rows = int(counts[0] or 0)
        winner_rows = int(counts[1] or 0)
        new_rows = int(counts[2] or 0)
        existing_rows = int(counts[3] or 0)
        if table.identity_strategy == "preserve":
            collision = cursor.execute(
                f"SELECT COUNT_BIG(*) FROM {table.map_table} AS m "
                f"JOIN {target_sql} AS t ON t.{_quote_identifier(pk)}=m.[TargetKey] "
                "WHERE m.[IsWinner]=1 AND m.[IsNew]=1"
            ).fetchone()
            if collision and int(collision[0] or 0):
                raise AccountCopyScopeError(
                    f"{table.key} has target primary-key collisions; use stable match_columns and identity_strategy remap"
                )
        ambiguous_target = cursor.execute(
            "SELECT COUNT_BIG(*) FROM (SELECT "
            + ", ".join(_quote_identifier(name) for name in table.match_columns)
            + f" FROM {target_sql} GROUP BY "
            + ", ".join(_quote_identifier(name) for name in table.match_columns)
            + " HAVING COUNT_BIG(*)>1) AS d"
        ).fetchone()
        if ambiguous_target and int(ambiguous_target[0] or 0):
            raise AccountCopyScopeError(
                f"{table.key} target match_columns are not unique; choose a safer business key"
            )
        table_summaries.append(
            {
                "table": table.key,
                "mode": table.mode,
                "scopedSourceRows": scoped_rows,
                "deduplicatedSourceRows": scoped_rows - winner_rows,
                "newRows": new_rows,
                "matchedRows": existing_rows,
                "identityStrategy": table.identity_strategy,
                "relationshipCount": len(table.relationships),
            }
        )

    for table in compiled:
        source_sql = f"{database}.{_quote_table(table.key)}"
        target_sql = _quote_table(table.key)
        copy_key = _copy_key(table.target)
        pk = copy_key.name
        relationship_by_column = {
            relationship.column.casefold(): relationship for relationship in table.relationships
        }
        joins: list[str] = []
        relationship_aliases: dict[str, str] = {}
        for index, relationship in enumerate(table.relationships, start=1):
            parent = maps[relationship.referenced_table.casefold()]
            alias = f"r{index}"
            relationship_aliases[relationship.column.casefold()] = alias
            joins.append(
                f"LEFT JOIN {parent.map_table} AS {alias} ON {alias}.[SourceKey]="
                f"s.{_quote_identifier(relationship.column)}"
            )
            unresolved = cursor.execute(
                f"SELECT COUNT_BIG(*) FROM {table.map_table} AS m "
                f"JOIN {source_sql} AS s ON s.{_quote_identifier(pk)}=m.[SourceKey] "
                f"LEFT JOIN {parent.map_table} AS p ON p.[SourceKey]=s.{_quote_identifier(relationship.column)} "
                "WHERE m.[IsWinner]=1 AND "
                f"s.{_quote_identifier(relationship.column)} IS NOT NULL "
                f"AND s.{_quote_identifier(relationship.column)} NOT IN (-1,0) "
                "AND p.[SourceKey] IS NULL"
            ).fetchone()
            if unresolved and int(unresolved[0] or 0):
                raise AccountCopyScopeError(
                    f"{table.key}.{relationship.column} has references outside the selected parent scope"
                )

        expressions: list[str] = []
        parameters: list[Any] = []
        for column_name in table.columns:
            if column_name.casefold() == pk.casefold():
                expressions.append("m.[TargetKey]")
            elif column_name in table.overrides:
                expressions.append("?")
                parameters.append(table.overrides[column_name])
            elif column_name.casefold() in relationship_aliases:
                alias = relationship_aliases[column_name.casefold()]
                expressions.append(
                    f"CASE WHEN s.{_quote_identifier(column_name)} IN (-1,0) "
                    f"THEN s.{_quote_identifier(column_name)} ELSE {alias}.[TargetKey] END"
                )
            else:
                expressions.append(f"s.{_quote_identifier(column_name)}")

        if table.mode in {"insert_missing", "upsert"}:
            insert_sql = (
                f"INSERT INTO {target_sql} ("
                + ", ".join(_quote_identifier(name) for name in table.columns)
                + ") SELECT "
                + ", ".join(expressions)
                + f" FROM {source_sql} AS s JOIN {table.map_table} AS m "
                f"ON m.[SourceKey]=s.{_quote_identifier(pk)} "
                + " ".join(joins)
                + " WHERE m.[IsWinner]=1 AND m.[IsNew]=1"
            )
            statements.append(
                {
                    "sql": insert_sql,
                    "parameters": parameters,
                    "identity_insert": bool(copy_key.identity),
                }
            )

        if table.mode in {"update_existing", "upsert"}:
            assignments: list[str] = []
            update_parameters: list[Any] = []
            for column_name, expression in zip(table.columns, expressions):
                if column_name.casefold() == pk.casefold() or column_name.casefold() in {
                    value.casefold() for value in table.match_columns
                }:
                    continue
                assignments.append(f"t.{_quote_identifier(column_name)}={expression}")
                if expression == "?":
                    update_parameters.append(table.overrides[column_name])
            if assignments:
                update_sql = (
                    f"UPDATE t SET {', '.join(assignments)} FROM {target_sql} AS t "
                    f"JOIN {table.map_table} AS m ON m.[TargetKey]=t.{_quote_identifier(pk)} "
                    f"JOIN {source_sql} AS s ON s.{_quote_identifier(pk)}=m.[SourceKey] "
                    + " ".join(joins)
                    + " WHERE m.[IsWinner]=1 AND m.[IsNew]=0"
                )
                statements.append({"sql": update_sql, "parameters": update_parameters})

    expected_rows = 0
    for item in table_summaries:
        if item["mode"] in {"insert_missing", "upsert"}:
            expected_rows += int(item["newRows"])
        if item["mode"] in {"update_existing", "upsert"}:
            table = next(value for value in compiled if value.key == item["table"])
            mutable = [
                name
                for name in table.columns
                if name.casefold() != _copy_key(table.target).name.casefold()
                and name.casefold() not in {value.casefold() for value in table.match_columns}
            ]
            if mutable:
                expected_rows += int(item["matchedRows"])

    verification_terms: list[str] = []
    for table in compiled:
        pk = _copy_key(table.target).name
        target_sql = _quote_table(table.key)
        required_map_predicate = (
            "m.[IsWinner]=1 AND m.[IsNew]=0"
            if table.mode == "update_existing"
            else "m.[IsWinner]=1"
        )
        verification_terms.append(
            f"(SELECT COUNT_BIG(*) FROM {table.map_table} AS m LEFT JOIN {target_sql} AS t "
            f"ON t.{_quote_identifier(pk)}=m.[TargetKey] WHERE {required_map_predicate} "
            f"AND t.{_quote_identifier(pk)} IS NULL)"
        )
        for relationship in table.relationships:
            parent = maps[relationship.referenced_table.casefold()]
            parent_pk = _copy_key(parent.target).name
            verification_terms.append(
                f"(SELECT COUNT_BIG(*) FROM {target_sql} AS c JOIN {table.map_table} AS cm "
                f"ON cm.[TargetKey]=c.{_quote_identifier(pk)} LEFT JOIN {_quote_table(parent.key)} AS p "
                f"ON p.{_quote_identifier(parent_pk)}=c.{_quote_identifier(relationship.column)} "
                f"WHERE cm.[IsWinner]=1 AND c.{_quote_identifier(relationship.column)} IS NOT NULL "
                f"AND c.{_quote_identifier(relationship.column)} NOT IN (-1,0) "
                f"AND p.{_quote_identifier(parent_pk)} IS NULL)"
            )
    verification_sql = "SELECT CAST(" + " + ".join(verification_terms or ["0"]) + " AS bigint)"
    return (
        statements,
        {
            "tableCount": len(compiled),
            "dependencyOrder": [table.key for table in compiled],
            "tables": table_summaries,
            "orphanChecks": sum(len(table.relationships) for table in compiled),
        },
        expected_rows,
        verification_sql,
    )


def _read_table_meta(cursor: Any, *, database: str, table: str) -> TableMeta:
    _require_business_table(table)
    schema, name = table.split(".", 1)
    prefix = f"{_quote_identifier(database)}." if database else ""
    rows = cursor.execute(
        "SELECT c.name,c.column_id,LOWER(ty.name),c.max_length,c.precision,c.scale,"
        "c.is_nullable,c.is_identity,c.is_computed,c.generated_always_type,"
        "CASE WHEN c.default_object_id=0 THEN 0 ELSE 1 END,COALESCE(pk.key_ordinal,0) "
        f"FROM {prefix}sys.tables t JOIN {prefix}sys.schemas s ON s.schema_id=t.schema_id "
        f"JOIN {prefix}sys.columns c ON c.object_id=t.object_id "
        f"JOIN {prefix}sys.types ty ON ty.user_type_id=c.user_type_id "
        "LEFT JOIN (SELECT ic.object_id,ic.column_id,ic.key_ordinal "
        f"FROM {prefix}sys.indexes i JOIN {prefix}sys.index_columns ic "
        "ON ic.object_id=i.object_id AND ic.index_id=i.index_id WHERE i.is_primary_key=1) pk "
        "ON pk.object_id=c.object_id AND pk.column_id=c.column_id "
        "WHERE s.name=? AND t.name=? ORDER BY c.column_id",
        [schema, name],
    ).fetchall()
    if not rows:
        raise AccountCopyScopeError(f"table {table} does not exist in an account database")
    columns = tuple(
        ColumnMeta(
            name=str(row[0]),
            ordinal=int(row[1]),
            type_name=str(row[2]),
            max_length=int(row[3]),
            precision=int(row[4]),
            scale=int(row[5]),
            nullable=bool(row[6]),
            identity=bool(row[7]),
            computed=bool(row[8]),
            generated=bool(row[9]),
            has_default=bool(row[10]),
            primary_key_ordinal=int(row[11]),
        )
        for row in rows
    )
    relationship_rows = cursor.execute(
        "SELECT pc.name,rs.name,rt.name,rc.name "
        f"FROM {prefix}sys.foreign_keys fk "
        f"JOIN {prefix}sys.foreign_key_columns fkc ON fkc.constraint_object_id=fk.object_id "
        f"JOIN {prefix}sys.tables pt ON pt.object_id=fk.parent_object_id "
        f"JOIN {prefix}sys.schemas ps ON ps.schema_id=pt.schema_id "
        f"JOIN {prefix}sys.columns pc ON pc.object_id=pt.object_id AND pc.column_id=fkc.parent_column_id "
        f"JOIN {prefix}sys.tables rt ON rt.object_id=fk.referenced_object_id "
        f"JOIN {prefix}sys.schemas rs ON rs.schema_id=rt.schema_id "
        f"JOIN {prefix}sys.columns rc ON rc.object_id=rt.object_id AND rc.column_id=fkc.referenced_column_id "
        "WHERE ps.name=? AND pt.name=? AND fk.is_disabled=0",
        [schema, name],
    ).fetchall()
    return TableMeta(
        schema=schema,
        name=name,
        columns=columns,
        relationships=tuple(
            RelationshipMeta(
                column=str(row[0]),
                referenced_table=f"{row[1]}.{row[2]}",
                referenced_column=str(row[3]),
            )
            for row in relationship_rows
        ),
    )


def _dependency_order(tables: list[CompiledTable]) -> list[CompiledTable]:
    by_key = {table.key.casefold(): table for table in tables}
    dependencies = {
        key: {
            relationship.referenced_table.casefold()
            for relationship in table.relationships
            if relationship.referenced_table.casefold() != key
        }
        for key, table in by_key.items()
    }
    ordered: list[CompiledTable] = []
    remaining = {key: set(value) for key, value in dependencies.items()}
    while remaining:
        ready = sorted((key for key, deps in remaining.items() if not deps), key=str.casefold)
        if not ready:
            raise AccountCopyScopeError(
                "selected table relationships contain a cycle; remove the unsafe relationship or split the copy"
            )
        for key in ready:
            ordered.append(by_key[key])
            remaining.pop(key)
        for deps in remaining.values():
            deps.difference_update(ready)
    return ordered


def _normalize_filter(value: Any, *, depth: int, counter: list[int]) -> Any:
    counter[0] += 1
    if counter[0] > MAX_FILTER_NODES or depth > MAX_FILTER_DEPTH:
        raise AccountCopyScopeError("account-copy filter is too large or deeply nested")
    if value in (None, {}, []):
        return {"all": []}
    if not isinstance(value, dict):
        raise AccountCopyScopeError("filter nodes must be objects")
    if set(value) in ({"all"}, {"any"}):
        key = next(iter(value))
        children = value[key]
        if not isinstance(children, list):
            raise AccountCopyScopeError(f"filter {key} must be a list")
        return {key: [_normalize_filter(child, depth=depth + 1, counter=counter) for child in children]}
    if set(value) == {"column", "op"} or set(value) == {"column", "op", "value"}:
        op = str(value["op"] or "").strip().casefold()
        if op not in {"eq", "ne", "gt", "gte", "lt", "lte", "in", "is_null", "not_null"}:
            raise AccountCopyScopeError("unsupported account-copy filter operator")
        result: dict[str, Any] = {"column": _identifier(value["column"]), "op": op}
        if op in {"is_null", "not_null"}:
            if "value" in value:
                raise AccountCopyScopeError(f"filter {op} does not accept a value")
        elif op == "in":
            raw_values = value.get("value")
            if not isinstance(raw_values, list) or not 1 <= len(raw_values) <= 500:
                raise AccountCopyScopeError("filter in requires 1 to 500 scalar values")
            result["value"] = [_json_scalar(item, "filter value") for item in raw_values]
        else:
            result["value"] = _json_scalar(value.get("value"), "filter value")
        return result
    if set(value) == {"exists"} and isinstance(value["exists"], dict):
        exists = value["exists"]
        if set(exists) != {"table", "on", "filter"}:
            raise AccountCopyScopeError("exists filter needs table, on, and filter")
        joins = exists["on"]
        if not isinstance(joins, list) or not 1 <= len(joins) <= 8:
            raise AccountCopyScopeError("exists filter on must contain 1 to 8 joins")
        clean_joins = []
        for join in joins:
            if not isinstance(join, dict) or set(join) != {"local_column", "foreign_column"}:
                raise AccountCopyScopeError("exists joins need local_column and foreign_column")
            clean_joins.append(
                {
                    "local_column": _identifier(join["local_column"]),
                    "foreign_column": _identifier(join["foreign_column"]),
                }
            )
        return {
            "exists": {
                "table": _table_key(exists["table"]),
                "on": clean_joins,
                "filter": _normalize_filter(exists["filter"], depth=depth + 1, counter=counter),
            }
        }
    raise AccountCopyScopeError("unsupported account-copy filter shape")


def _validate_filter_columns(filter_spec: Any, meta_getter: Callable[[str], TableMeta], root: str | None = None) -> None:
    if "all" in filter_spec or "any" in filter_spec:
        for child in filter_spec.get("all", filter_spec.get("any", [])):
            _validate_filter_columns(child, meta_getter, root)
        return
    if "column" in filter_spec:
        if root is None:
            return
        column = _column(meta_getter(root), filter_spec["column"])
        if not column.copyable:
            raise AccountCopyScopeError("protected columns cannot be used to scope an account copy")
        return
    exists = filter_spec["exists"]
    table = _table_key(exists["table"])
    _require_business_table(table)
    child_meta = meta_getter(table)
    if root is not None:
        parent_meta = meta_getter(root)
        for join in exists["on"]:
            local = _column(parent_meta, join["local_column"])
            foreign = _column(child_meta, join["foreign_column"])
            if not local.copyable or not foreign.copyable:
                raise AccountCopyScopeError("protected columns cannot be used to scope an account copy")
    _validate_filter_columns(exists["filter"], meta_getter, table)


def _filter_sql(
    filter_spec: Any,
    *,
    source_database: str,
    root_table: TableMeta,
    alias: str,
    counter: list[int] | None = None,
) -> tuple[str, list[Any]]:
    counter = counter or [0]
    if "all" in filter_spec or "any" in filter_spec:
        key = "all" if "all" in filter_spec else "any"
        parts: list[str] = []
        parameters: list[Any] = []
        for child in filter_spec[key]:
            sql, values = _filter_sql(
                child,
                source_database=source_database,
                root_table=root_table,
                alias=alias,
                counter=counter,
            )
            parts.append(sql)
            parameters.extend(values)
        if not parts:
            return "1=1", []
        return "(" + (" AND " if key == "all" else " OR ").join(parts) + ")", parameters
    if "column" in filter_spec:
        column = _column(root_table, filter_spec["column"])
        reference = f"{alias}.{_quote_identifier(column.name)}"
        op = filter_spec["op"]
        if op == "is_null":
            return f"{reference} IS NULL", []
        if op == "not_null":
            return f"{reference} IS NOT NULL", []
        if op == "in":
            values = list(filter_spec["value"])
            return f"{reference} IN ({', '.join('?' for _ in values)})", values
        operator = {"eq": "=", "ne": "<>", "gt": ">", "gte": ">=", "lt": "<", "lte": "<="}[op]
        return f"{reference}{operator}?", [filter_spec["value"]]
    exists = filter_spec["exists"]
    table = _readless_table_meta(exists["table"])
    counter[0] += 1
    child_alias = f"e{counter[0]}"
    child_sql, parameters = _filter_sql(
        exists["filter"],
        source_database=source_database,
        root_table=table,
        alias=child_alias,
        counter=counter,
    )
    joins = " AND ".join(
        f"{child_alias}.{_quote_identifier(join['foreign_column'])}="
        f"{alias}.{_quote_identifier(join['local_column'])}"
        for join in exists["on"]
    )
    return (
        f"EXISTS (SELECT 1 FROM {source_database}.{_quote_table(exists['table'])} AS {child_alias} "
        f"WHERE {joins} AND {child_sql})",
        parameters,
    )


# Filter compilation needs only resolved names. _compile_tables validates the real
# metadata first, then this small projection keeps SQL construction independent
# from another metadata round trip.
def _readless_table_meta(table: str) -> TableMeta:
    schema, name = _table_key(table).split(".", 1)
    return TableMeta(schema=schema, name=name, columns=())


def _column(table: TableMeta, name: str) -> ColumnMeta:
    match = table.column_lookup.get(str(name or "").casefold())
    if match is None:
        # Exists-filter child projections have already been validated against
        # live metadata. Preserve the validated identifier for SQL compilation.
        if not table.columns:
            return ColumnMeta(_identifier(name), 0, "int", 4, 10, 0, True, False, False, False, False)
        raise AccountCopyScopeError(f"column {table.key}.{name} does not exist")
    return match


def _compatible(source: ColumnMeta, target: ColumnMeta) -> bool:
    if source.type_name.casefold() != target.type_name.casefold():
        return False
    type_name = source.type_name.casefold()
    if type_name in {"char", "nchar", "nvarchar", "varchar", "binary", "varbinary"}:
        return target.max_length == -1 or (source.max_length != -1 and target.max_length >= source.max_length)
    if type_name in {"decimal", "numeric"}:
        return target.precision >= source.precision and target.scale >= source.scale
    return True


def _table_schema_value(table: TableMeta) -> dict[str, Any]:
    return {
        "table": table.key,
        "columns": [column.__dict__ for column in table.columns],
        "relationships": [relationship.__dict__ for relationship in table.relationships],
    }


def _public_plan(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "ok": True,
        "status": "preview",
        "operation": OPERATION_NAME,
        "planId": record["planId"],
        "idempotencyKey": record["idempotencyKey"],
        "sourceCompanyUsername": record["sourceCompanyUsername"],
        "targetCompanyUsername": record["targetCompanyUsername"],
        "summary": record["summary"],
        "approvalRequired": True,
        "arbitrarySqlAccepted": False,
        "sourceWritesAllowed": False,
        "protectedColumnsCopied": False,
    }


def _public_execution(record: dict[str, Any], *, replay: bool) -> dict[str, Any]:
    receipt = dict(record.get("receipt") or {})
    return {
        "ok": True,
        "status": "completed",
        "operation": OPERATION_NAME,
        "planId": record["planId"],
        "idempotencyKey": record["idempotencyKey"],
        "sourceCompanyUsername": record["sourceCompanyUsername"],
        "targetCompanyUsername": record["targetCompanyUsername"],
        "summary": record["summary"],
        "affectedRows": int(receipt.get("affectedRows") or 0),
        "transactionCommitted": bool(receipt.get("transactionCommitted")),
        "postCommitReadbackVerified": bool(receipt.get("postCommitReadbackVerified")),
        "backupTables": receipt.get("backupTables", []),
        "idempotentReplay": replay or bool(receipt.get("idempotentReplay")),
    }


def _public_status(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "ok": True,
        "operation": OPERATION_NAME,
        "planId": record["planId"],
        "status": record.get("status"),
        "sourceCompanyUsername": record["sourceCompanyUsername"],
        "targetCompanyUsername": record["targetCompanyUsername"],
        "idempotencyKey": record["idempotencyKey"],
        "summary": record["summary"],
        "updatedAtUtc": record.get("updatedAtUtc"),
        "guardedReceiptStatus": record.get("guardedReceiptStatus", "not_found"),
        "failure": str(record.get("failure") or "")[:1000],
    }


def _company_username(value: Any, field: str) -> str:
    clean = str(value or "").strip()
    if clean.casefold().startswith("pos_"):
        clean = clean[4:]
    if not COMPANY_USERNAME.fullmatch(clean):
        raise AccountCopyScopeError(f"{field} must be an exact Nova company username")
    return clean


def _idempotency_key(value: Any) -> str:
    clean = str(value or "").strip()
    if not IDEMPOTENCY_KEY.fullmatch(clean):
        raise AccountCopyScopeError("idempotency_key must be a stable 8-200 character identifier")
    return clean


def _ticket_number(value: Any) -> str:
    clean = str(value or "").strip()
    if clean and not re.fullmatch(r"[0-9]{1,18}", clean):
        raise AccountCopyScopeError("ticket_number must contain only digits")
    return clean


def _plan_id(value: Any) -> str:
    clean = str(value or "").strip().casefold()
    if not PLAN_ID.fullmatch(clean):
        raise AccountCopyScopeError("plan_id must be the exact immutable account-copy plan identifier")
    return clean


def _identifier(value: Any) -> str:
    clean = str(value or "").strip()
    if not IDENTIFIER.fullmatch(clean):
        raise AccountCopyScopeError("table and column identifiers must use the guarded identifier format")
    return clean


def _table_key(value: Any) -> str:
    clean = str(value or "").strip()
    parts = clean.split(".")
    if len(parts) != 2:
        raise AccountCopyScopeError("tables must be schema-qualified, for example dbo.Products")
    return f"{_identifier(parts[0])}.{_identifier(parts[1])}"


def _require_business_table(table: str) -> None:
    clean = _table_key(table)
    name = clean.split(".", 1)[1]
    if name.casefold().startswith(INTERNAL_TABLE_PREFIXES) or BLOCKED_TABLE.search(name):
        raise AccountCopyScopeError(f"protected or internal table {clean} cannot be copied")


def _json_scalar(value: Any, field: str) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        if isinstance(value, str) and len(value) > 4000:
            raise AccountCopyScopeError(f"{field} exceeds the scalar length limit")
        return value
    raise AccountCopyScopeError(f"{field} must be a JSON scalar")


def _quote_identifier(value: str) -> str:
    return f"[{_identifier(value)}]"


def _quote_table(value: str) -> str:
    schema, name = _table_key(value).split(".", 1)
    return f"{_quote_identifier(schema)}.{_quote_identifier(name)}"


def _null_safe_equals(left: str, right: str) -> str:
    return f"({left}={right} OR ({left} IS NULL AND {right} IS NULL))"


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    ).hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_json(path: Path, value: dict[str, Any], *, create_only: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if create_only and path.exists():
        existing = json.loads(path.read_text(encoding="utf-8"))
        if existing.get("planId") != value.get("planId"):
            raise AccountCopyUnavailableError("account-copy plan identifier collision")
        return
    temporary = path.with_suffix(f".tmp.{os.getpid()}")
    temporary.write_text(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True),
        encoding="utf-8",
    )
    os.replace(temporary, path)
