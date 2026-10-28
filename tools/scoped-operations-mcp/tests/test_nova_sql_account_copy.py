from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

# AgentChat/coding_agent 2026-08-06T10:12:33Z

from scoped_operations_mcp.nova_sql_account_copy import (
    AccountCopyScopeError,
    ColumnMeta,
    CompiledTable,
    RelationshipMeta,
    TableMeta,
    _build_plan_sql,
    _copy_key,
    _dependency_order,
    _normalize_request,
    _require_business_table,
)
from scoped_operations_mcp.nova_sql_client import _validated_write_plan


ROOT = Path(__file__).resolve().parents[3]


def _column(
    name: str,
    ordinal: int,
    *,
    primary_key: bool = False,
    identity: bool = False,
    type_name: str = "int",
    nullable: bool = False,
) -> ColumnMeta:
    return ColumnMeta(
        name=name,
        ordinal=ordinal,
        type_name=type_name,
        max_length=4 if type_name == "int" else 200,
        precision=10,
        scale=0,
        nullable=nullable,
        identity=identity,
        computed=False,
        generated=False,
        has_default=False,
        primary_key_ordinal=1 if primary_key else 0,
    )


class PlanningCursor:
    def __init__(self) -> None:
        self.rows = []
        self.commands: list[tuple[str, list[object]]] = []

    def execute(self, sql, parameters=None):
        values = list(parameters or [])
        self.commands.append((str(sql), values))
        normalized = " ".join(str(sql).split())
        if normalized.startswith("CREATE TABLE #acm"):
            self.rows = []
        elif normalized.startswith("INSERT INTO #acm") and "SELECT CAST" in normalized:
            self.rows = []
        elif "SUM(CASE WHEN [IsWinner]=1" in normalized and "#acm01_" in normalized:
            self.rows = [(3, 2, 2, 0)]
        elif "SUM(CASE WHEN [IsWinner]=1" in normalized and "#acm02_" in normalized:
            self.rows = [(2, 2, 2, 0)]
        elif normalized.startswith("SELECT COUNT_BIG(*)"):
            self.rows = [(0,)]
        else:
            raise AssertionError((sql, parameters))
        return self

    def fetchone(self):
        return self.rows[0] if self.rows else None


def test_account_copy_request_is_table_generic_but_never_accepts_sql() -> None:
    request = _normalize_request(
        [
            {
                "table": "custom.FutureBusinessTable",
                "columns": ["FutureId", "LocationId"],
                "match_columns": ["FutureId"],
                "filter": {
                    "exists": {
                        "table": "custom.FutureScope",
                        "on": [{"local_column": "FutureId", "foreign_column": "FutureId"}],
                        "filter": {"column": "LocationId", "op": "eq", "value": 7},
                    }
                },
            }
        ]
    )

    assert request[0]["table"] == "custom.FutureBusinessTable"
    assert request[0]["filter"]["exists"]["table"] == "custom.FutureScope"

    with pytest.raises(AccountCopyScopeError, match="unsupported table fields"):
        _normalize_request([{"table": "dbo.Products", "sql": "DELETE FROM dbo.Products"}])
    with pytest.raises(AccountCopyScopeError, match="protected or internal table"):
        _require_business_table("dbo.Api_Credentials")


def test_invoice_destination_location_override_requires_source_location_filter() -> None:
    with pytest.raises(AccountCopyScopeError, match="explicit source LocationID"):
        _normalize_request(
            [
                {
                    "table": "dbo.Invoices",
                    "filter": {"column": "Timestamp", "op": "gte", "value": "2026-04-01"},
                    "overrides": {"LocationID": 1},
                }
            ]
        )

    request = _normalize_request(
        [
            {
                "table": "dbo.Invoices",
                "filter": {
                    "all": [
                        {"column": "Timestamp", "op": "gte", "value": "2026-04-01"},
                        {"column": "LocationID", "op": "eq", "value": 1},
                    ]
                },
                "overrides": {"LocationID": 1},
            }
        ]
    )

    assert request[0]["filter"]["all"][1]["value"] == 1


def test_dependency_order_places_relationship_parent_first_and_rejects_cycles() -> None:
    parent_meta = TableMeta(
        "dbo",
        "Products",
        (_column("ProductId", 1, primary_key=True),),
    )
    child_meta = TableMeta(
        "dbo",
        "Invoice_Products",
        (
            _column("InvoiceProductId", 1, primary_key=True),
            _column("ProductId", 2),
        ),
    )
    parent = CompiledTable(
        key="dbo.Products",
        source=parent_meta,
        target=parent_meta,
        mode="insert_missing",
        columns=("ProductId",),
        match_columns=("ProductId",),
        identity_strategy="preserve",
        filter_spec={"all": []},
        overrides={},
        relationships=(),
        map_table="#acm01_products",
    )
    child_relationship = RelationshipMeta("ProductId", "dbo.Products", "ProductId")
    child = CompiledTable(
        key="dbo.Invoice_Products",
        source=child_meta,
        target=child_meta,
        mode="insert_missing",
        columns=("InvoiceProductId", "ProductId"),
        match_columns=("InvoiceProductId",),
        identity_strategy="preserve",
        filter_spec={"all": []},
        overrides={},
        relationships=(child_relationship,),
        map_table="#acm02_invoice_products",
    )

    assert [item.key for item in _dependency_order([child, parent])] == [
        "dbo.Products",
        "dbo.Invoice_Products",
    ]

    parent_cycle = CompiledTable(
        **{
            **parent.__dict__,
            "relationships": (
                RelationshipMeta("ProductId", "dbo.Invoice_Products", "InvoiceProductId"),
            ),
        }
    )
    with pytest.raises(AccountCopyScopeError, match="contain a cycle"):
        _dependency_order([parent_cycle, child])


def test_copy_key_accepts_one_legacy_integer_identity_without_declared_pk() -> None:
    legacy = TableMeta(
        "dbo",
        "Invoice_Payments",
        (
            _column("Invoice_Payments_ID", 1, identity=True),
            _column("InvoiceID", 2),
        ),
    )
    assert _copy_key(legacy).name == "Invoice_Payments_ID"

    ambiguous = TableMeta(
        "dbo",
        "LegacyLink",
        (
            _column("LeftID", 1),
            _column("RightID", 2),
        ),
    )
    with pytest.raises(AccountCopyScopeError, match="integer primary key or one integer identity"):
        _copy_key(ambiguous)


def test_compiled_copy_deduplicates_maps_relationships_and_fits_guarded_executor() -> None:
    products = TableMeta(
        "dbo",
        "Products",
        (
            _column("ProductId", 1, primary_key=True, identity=True),
            _column("ProductName", 2, type_name="nvarchar"),
            _column("BarcodeNumber", 3, type_name="nvarchar", nullable=True),
        ),
    )
    invoice_products = TableMeta(
        "dbo",
        "Invoice_Products",
        (
            _column("InvoiceProductId", 1, primary_key=True, identity=True),
            _column("ProductId", 2),
            _column("Quantity", 3),
        ),
    )
    product_plan = CompiledTable(
        key="dbo.Products",
        source=products,
        target=products,
        mode="insert_missing",
        columns=("ProductId", "ProductName", "BarcodeNumber"),
        match_columns=("ProductName", "BarcodeNumber"),
        identity_strategy="remap",
        filter_spec={"column": "ProductName", "op": "eq", "value": "Widget"},
        overrides={},
        relationships=(),
        map_table="#acm01_38d5f240",
    )
    child_plan = CompiledTable(
        key="dbo.Invoice_Products",
        source=invoice_products,
        target=invoice_products,
        mode="insert_missing",
        columns=("InvoiceProductId", "ProductId", "Quantity"),
        match_columns=("InvoiceProductId",),
        identity_strategy="preserve",
        filter_spec={"all": []},
        overrides={},
        relationships=(RelationshipMeta("ProductId", "dbo.Products", "ProductId"),),
        map_table="#acm02_a86b675c",
    )
    cursor = PlanningCursor()

    statements, summary, expected_rows, verification_sql = _build_plan_sql(
        cursor,
        source="Source_Account",
        compiled=[product_plan, child_plan],
    )

    assert expected_rows == 4
    assert summary["tables"][0]["deduplicatedSourceRows"] == 1
    assert summary["orphanChecks"] == 1
    assert len(statements) == 6
    assert all("DELETE" not in item["sql"].upper() for item in statements)
    assert statements[0]["sql"].startswith("CREATE TABLE #acm01_")
    assert statements[1]["sql"].startswith("INSERT INTO #acm01_")
    assert "SELECT CAST(s.[ProductId] AS bigint)" in statements[1]["sql"]
    assert statements[1]["parameters"] == ["Widget"]
    assert "LEFT JOIN [dbo].[Products] AS p" in verification_sql
    assert "r1.[TargetKey]" in statements[-1]["sql"]

    guarded = _validated_write_plan(
        company_username="Target_Account",
        source_company_usernames=["Source_Account"],
        statements=statements,
        verification_sql=verification_sql,
        verification_parameters=[],
        expected_affected_rows=expected_rows,
        expected_verification_value=0,
        idempotency_key="ticket-347534-account-copy",
    )
    assert guarded.source_company_usernames == ("Source_Account",)
    assert guarded.expected_affected_rows == 4
    assert set(guarded.target_operations) == {"dbo.Invoice_Products", "dbo.Products"}


def test_account_copy_is_registered_as_the_reusable_taylor_route() -> None:
    pipelines = json.loads(
        (ROOT / "config" / "pipeline-registry.json").read_text(encoding="utf-8")
    )["pipelines"]
    account_copy = pipelines["development_service_account_copy"]
    text = " ".join(
        account_copy["preferred_entrypoints"]
        + account_copy["avoid_by_default"]
        + account_copy["steps"]
        + account_copy["verification"]
    )
    for name in (
        "nova_sql_account_copy_preview",
        "nova_sql_account_copy_execute",
        "nova_sql_account_copy_status",
        "immutable plan",
    ):
        assert name in text

    capabilities = yaml.safe_load(
        (ROOT / "config" / "agent-capabilities.yaml").read_text(encoding="utf-8")
    )
    coding = set(capabilities["lanes"]["coding_agent"]["operations"])
    support = set(capabilities["lanes"]["tickets_agent"]["operations"])
    for operation in (
        "nova_sql.account_copy.preview",
        "nova_sql.account_copy.status",
        "nova_sql.account_copy.execute",
    ):
        assert operation in coding
        assert operation not in support

    fast_path = json.loads(
        (ROOT / "config" / "tool-fast-paths.json").read_text(encoding="utf-8")
    )["tools"]["nova_sql"]
    fast_text = " ".join(
        fast_path["safe_actions"]
        + fast_path["requires_authorization_for"]
        + fast_path["fast_start"]
    )
    assert "nova_sql_account_copy_preview" in fast_text
    assert "nova_sql_account_copy_execute" in fast_text
    assert "nova_sql_account_copy_status" in fast_text
