from __future__ import annotations

# AgentChat/coding_agent 2026-08-06T12:02:00Z
# AgentChat/coding_agent 2026-08-06T13:12:00Z
# AgentChat/coding_agent 2026-08-06T13:54:59Z

import re

from scoped_operations_mcp.instyle_runway_merge_sql_v1 import (
    INSTYLE_RUNWAY_INVENTORY_HISTORY_CATCHUP_SQL_V3,
    INSTYLE_RUNWAY_LOCATION_STATUS_REPAIR_SQL_V2,
    INSTYLE_RUNWAY_MERGE_SQL_V1,
)
from scoped_operations_mcp.nova_sql_instyle_runway_merge import (
    FULL_MERGE_MODE,
    INVENTORY_HISTORY_CATCHUP_MODE,
    LOCATION_STATUS_REPAIR_MODE,
    REPAIR_LOCATION_IDS,
    SOURCE_A_ACCOUNT_ID,
    SOURCE_A_USERNAME,
    SOURCE_B_ACCOUNT_ID,
    SOURCE_B_USERNAME,
    TARGET_ACCOUNT_ID,
    TARGET_USERNAME,
    InstyleRunwayMergeOperation,
    _preview_result,
    _script_for_mode,
)


def test_production_sql_is_fixed_atomic_backed_up_and_not_demo() -> None:
    sql = INSTYLE_RUNWAY_MERGE_SQL_V1

    assert "POS_DEMO_NOVA_CAFE" not in sql
    assert "DEMO_NOVA_CAFE" not in sql
    assert "DECLARE @Target sysname=N'POS_INSTYLE_RUNWAY'" in sql
    assert "BEGIN TRANSACTION" in sql
    assert "IF @@TRANCOUNT>0 ROLLBACK TRANSACTION" in sql
    assert "__codex_instyle_runway_backup_manifest" in sql
    assert "SELECT * INTO dbo." in sql
    assert "@BackupRows<>@BackupSourceRows" in sql
    assert "@BackupTablesCreated=0" in sql


def test_production_sql_has_exact_location_region_and_product_contract() -> None:
    sql = INSTYLE_RUNWAY_MERGE_SQL_V1

    assert "LocationID+24,2" in sql
    assert "COUNT_BIG(*) FROM #LocationMap WHERE SourceTag='A')<>24" in sql
    assert "COUNT_BIG(*) FROM #LocationMap WHERE SourceTag='B')<>20" in sql
    assert "@Locations<>44 OR @Regions<>2" in sql
    assert "RegionName=N'LE BOUTIQUE INSTYLE'" in sql
    assert "RegionName=N'Instyle Fragrance'" in sql
    assert "lm.TargetLocationID" in sql
    assert "rm.TargetRegionID" in sql
    assert "ORDER BY SourceProductID DESC,SourceTag DESC" in sql
    assert "__codex_instyle_runway_product_map" in sql
    assert "immutable production product crosswalk changed" in sql
    assert "PlanHash char(64) NOT NULL" in sql
    assert "cc.NormalizedName=N''locationmanageremployeeid''" in sql
    assert "WHEN s.LocationManagerEmployeeID=1 THEN 1" in sql


def test_location_status_repair_is_fixed_atomic_and_fully_backed_up() -> None:
    sql = INSTYLE_RUNWAY_LOCATION_STATUS_REPAIR_SQL_V2

    assert "DB_NAME()<>N'POS_INSTYLE_RUNWAY'" in sql
    assert "BEGIN TRANSACTION" in sql
    assert "IF @@TRANCOUNT>0 ROLLBACK TRANSACTION" in sql
    assert "SELECT * INTO dbo." in sql
    assert "FROM dbo.Locations" in sql
    assert "@BackupRows<>@SourceRows OR @BackupRows<>44" in sql
    assert "@RowsUpdated<>13" in sql
    assert "LocationManagerEmployeeID=1" in sql
    assert "LocationManagerEmployeeID=1000000001" in sql
    for location_id in REPAIR_LOCATION_IDS:
        assert str(location_id) in sql
    assert "DELETE" not in sql.upper()
    assert "DROP TABLE" not in sql.upper()
    assert _script_for_mode(FULL_MERGE_MODE) == INSTYLE_RUNWAY_MERGE_SQL_V1
    assert (
        _script_for_mode(LOCATION_STATUS_REPAIR_MODE)
        == INSTYLE_RUNWAY_LOCATION_STATUS_REPAIR_SQL_V2
    )


def test_location_status_repair_never_writes_either_source() -> None:
    direct_source_dml = re.compile(
        r"\b(?:INSERT(?:\s+INTO)?|UPDATE|DELETE(?:\s+FROM)?|TRUNCATE\s+TABLE|"
        r"DROP\s+TABLE|ALTER\s+TABLE)\s+"
        r"(?:\[?POS_LE_BOUTIQUE_INSTYLE\]?|\[?POS_Instyle_Fragrance\]?)\.",
        re.IGNORECASE,
    )

    assert not direct_source_dml.search(INSTYLE_RUNWAY_LOCATION_STATUS_REPAIR_SQL_V2)


def test_inventory_history_catchup_is_fixed_atomic_and_fully_backed_up() -> None:
    sql = INSTYLE_RUNWAY_INVENTORY_HISTORY_CATCHUP_SQL_V3

    assert "DB_NAME()<>N'POS_INSTYLE_RUNWAY'" in sql
    assert "BEGIN TRANSACTION" in sql
    assert "IF @@TRANCOUNT>0 ROLLBACK TRANSACTION" in sql
    assert "SELECT * INTO dbo." in sql
    assert "FROM dbo.InventoryHistoryItem" in sql
    assert "@BackupRows<>@SourceRows" in sql
    assert "SET IDENTITY_INSERT dbo.InventoryHistoryItem ON" in sql
    assert "POS_LE_BOUTIQUE_INSTYLE].dbo.InventoryHistoryItem" in sql
    assert "POS_Instyle_Fragrance].dbo.InventoryHistoryItem" in sql
    assert "pm.SourceTag='A'" in sql
    assert "pm.SourceTag='B'" in sql
    assert "@RowsA+@RowsB<>@ExpectedRows-@SourceRows" in sql
    assert "DELETE" not in sql.upper()
    assert "DROP TABLE" not in sql.upper()
    assert (
        _script_for_mode(INVENTORY_HISTORY_CATCHUP_MODE)
        == INSTYLE_RUNWAY_INVENTORY_HISTORY_CATCHUP_SQL_V3
    )


def test_inventory_history_catchup_never_writes_either_source() -> None:
    direct_source_dml = re.compile(
        r"\b(?:INSERT(?:\s+INTO)?|UPDATE|DELETE(?:\s+FROM)?|TRUNCATE\s+TABLE|"
        r"DROP\s+TABLE|ALTER\s+TABLE)\s+"
        r"(?:\[?POS_LE_BOUTIQUE_INSTYLE\]?|\[?POS_Instyle_Fragrance\]?)\.",
        re.IGNORECASE,
    )

    assert not direct_source_dml.search(
        INSTYLE_RUNWAY_INVENTORY_HISTORY_CATCHUP_SQL_V3
    )


def test_production_sql_enforces_fresh_107_142_11_scope_and_orphans() -> None:
    sql = INSTYLE_RUNWAY_MERGE_SQL_V1

    assert "@QualifiedPlaceholderProducts<>107" in sql
    assert "@QualifiedPlaceholderInvoiceLines<>142" in sql
    assert "@QuarantinedInvoiceProductRows<>11" in sql
    assert "__codex_instyle_runway_invoice_product_quarantine" in sql
    assert "RowJson nvarchar(max) NOT NULL" in sql
    assert "@ProductOrphans<>0" in sql
    assert "@DeclaredForeignKeyOrphans<>0" in sql
    assert "@HistoryRows<>@ExpectedHistoryRows" in sql
    assert "@LocationGroupMismatches<>0" in sql
    assert "@RegionGroupMismatches<>0" in sql


def test_production_sql_never_targets_either_source_for_dml() -> None:
    sql = INSTYLE_RUNWAY_MERGE_SQL_V1
    direct_source_dml = re.compile(
        r"\b(?:INSERT(?:\s+INTO)?|UPDATE|DELETE(?:\s+FROM)?|TRUNCATE\s+TABLE|"
        r"DROP\s+TABLE|ALTER\s+TABLE)\s+"
        r"(?:\[?POS_LE_BOUTIQUE_INSTYLE\]?|\[?POS_Instyle_Fragrance\]?)\.",
        re.IGNORECASE,
    )

    assert not direct_source_dml.search(sql)


def test_production_sql_never_copies_protected_credentials() -> None:
    sql = INSTYLE_RUNWAY_MERGE_SQL_V1

    assert "RegionManagerPassword=s.RegionManagerPassword" not in sql
    assert "RegionManagerCommissionPercent,RegionManagerPassword" not in sql
    for protected_column in (
        "password",
        "passcode",
        "secret",
        "securitykey",
        "apikey",
        "token",
        "authorization",
        "cookie",
        "deviceconfig",
        "merchantnumber",
        "merchanttransid",
        "merchantloginid",
        "employeessn",
        "cardnumber",
        "cvv",
        "trackdata",
    ):
        assert f"r.NormalizedName NOT LIKE N''%{protected_column}%''" in sql
    for protected_table in (
        "credential",
        "password",
        "secret",
        "token",
        "auth",
        "session",
        "paymentprofile",
        "merchantcredential",
    ):
        assert f"NOT LIKE N''%{protected_table}%''" in sql


def test_fixed_salesforce_identities_are_required() -> None:
    identities = {
        SOURCE_A_USERNAME: SOURCE_A_ACCOUNT_ID,
        SOURCE_B_USERNAME: SOURCE_B_ACCOUNT_ID,
        TARGET_USERNAME: TARGET_ACCOUNT_ID,
    }
    operation = InstyleRunwayMergeOperation(
        connect=lambda _read_only: None,
        resolve_account=lambda username: {
            "account_id": identities[username],
            "company_username": username,
        },
        state_dir=".",
    )

    assert operation._resolved_identities() == identities


def test_preview_exposes_contract_without_sql_or_credentials() -> None:
    result = _preview_result(
        {
            "idempotencyKey": "account-merge-347072-347073-v1",
            "planHash": "a" * 64,
            "fixedSources": [SOURCE_A_USERNAME, SOURCE_B_USERNAME],
            "fixedTarget": TARGET_USERNAME,
            "copyMode": "single_database_side_set_based_transaction",
            "targetState": {"locations": 18, "regions": 1},
            "sourceTableRows": {},
            "approvedSourceScope": {
                "qualifiedPlaceholderProducts": 107,
                "qualifiedInvoiceLines": 142,
                "quarantinedInvoiceProductRows": 11,
            },
            "locationPlan": {},
            "productDedupe": "fixed",
            "productCrosswalk": "source-qualified immutable",
        },
        replay=False,
    )

    flattened = repr(result).casefold()
    assert result["operation"] == "nova_sql_instyle_runway_merge_preview"
    assert result["fixedTarget"] == TARGET_USERNAME
    assert result["targetBackupRequired"] is True
    assert "password" not in flattened
    assert "connection" not in flattened
    assert "select " not in flattened


def test_repair_preview_exposes_only_bounded_business_scope() -> None:
    result = _preview_result(
        {
            "mode": LOCATION_STATUS_REPAIR_MODE,
            "idempotencyKey": "account-merge-347072-347073-status-v2",
            "planHash": "b" * 64,
            "fixedSources": [SOURCE_A_USERNAME, SOURCE_B_USERNAME],
            "fixedTarget": TARGET_USERNAME,
            "copyMode": "single_database_side_set_based_transaction",
            "targetBackupScope": "full_dbo_Locations",
            "targetState": {"locations": 44, "regions": 2},
            "sourceTableRows": {},
            "approvedSourceScope": {},
            "existingMerge": {
                "locationStatusMismatchIds": list(REPAIR_LOCATION_IDS),
            },
            "locationPlan": {},
            "productDedupe": "fixed",
            "productCrosswalk": "source-qualified immutable",
        },
        replay=False,
    )

    flattened = repr(result).casefold()
    assert result["mode"] == LOCATION_STATUS_REPAIR_MODE
    assert result["targetBackupScope"] == "full_dbo_Locations"
    assert tuple(result["locationStatusMismatchIds"]) == REPAIR_LOCATION_IDS
    assert "select " not in flattened
    assert "password" not in flattened
