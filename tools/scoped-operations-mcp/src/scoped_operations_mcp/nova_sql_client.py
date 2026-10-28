from __future__ import annotations

# AgentChat/coding_agent 2026-07-23T20:26:28Z
# AgentChat/coding_agent 2026-08-03T22:55:08Z
# AgentChat/coding_agent 2026-08-05T11:15:00Z
# AgentChat/coding_agent 2026-08-06T11:50:00Z

import base64
import hashlib
import json
import math
import os
import re
from contextlib import closing
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from itertools import combinations
from pathlib import Path
from typing import Any, Callable

from .nova_sql_instyle_demo_rebuild import (
    InstyleDemoRebuildOperation,
    ProtectedDemoRestoreGateway,
)
from .nova_sql_account_copy import AccountCopyOperation
from .nova_sql_instyle_set_based import (
    SetBasedInstyleDemoSyncOperation,
    execution_failure_result,
)
from .nova_sql_instyle_runway_merge import (
    InstyleRunwayMergeOperation,
    TARGET_USERNAME as INSTYLE_RUNWAY_USERNAME,
    execution_failure_result as instyle_runway_execution_failure_result,
)
from .nova_sql_oklahoma_hawaii_catalog_replace import (
    OklahomaHawaiiCatalogReplaceOperation,
)
from .nova_sql_table_restore import NovaSqlTableRestoreOperation
from .nova_sql_ticket_347534_invoice_repair import (
    OPERATION_NAME as TICKET_347534_INVOICE_REPAIR,
    TARGET_USERNAME as TICKET_347534_TARGET_USERNAME,
    Ticket347534InvoiceRepairOperation,
)


COMPANY_USERNAME = re.compile(r"^[A-Za-z0-9_]{1,80}$")
SECRET_COLUMN = re.compile(
    r"(?:password|passcode|secret|securitykey|api_?key|token|authorization|cookie|"
    r"deviceconfig|merchantnumber|merchanttransid|merchantloginid|employee_ssn)",
    re.IGNORECASE,
)
FORBIDDEN_SQL = re.compile(
    r"\b(?:alter|backup|bulk|create|dbcc|delete|deny|drop|exec(?:ute)?|grant|insert|"
    r"kill|merge|openquery|opendatasource|openrowset|reconfigure|restore|revoke|"
    r"shutdown|truncate|update|use|waitfor)\b",
    re.IGNORECASE,
)
SELECT_INTO = re.compile(r"\bselect\b[\s\S]*?\binto\b", re.IGNORECASE)
CROSS_DATABASE_NAME = re.compile(
    r"(?:\[[^\]]+\]|[A-Za-z_][A-Za-z0-9_$#@]*)\s*\.\s*"
    r"(?:\[[^\]]+\]|[A-Za-z_][A-Za-z0-9_$#@]*)\s*\.",
)
PREFERRED_DRIVERS = (
    "ODBC Driver 18 for SQL Server",
    "ODBC Driver 17 for SQL Server",
)
API_COHORT_SQL_USERNAME = "nova_taylor_api_cohort_ro"
API_COHORT_DATABASE = "POS_Main"
API_COHORT_COLUMNS = ("Username", "DatabaseName", "ApiExpirationDate")
WRITE_FORBIDDEN_SQL = re.compile(
    r"\b(?:alter|backup|bulk|dbcc|delete|deny|drop|exec(?:ute)?|grant|kill|merge|"
    r"openquery|opendatasource|openrowset|output|reconfigure|restore|revoke|shutdown|"
    r"truncate|use|waitfor)\b",
    re.IGNORECASE,
)
WRITE_KEYWORD = re.compile(r"\b(?:create|delete|drop|insert|merge|truncate|update)\b", re.IGNORECASE)
IDEMPOTENCY_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{7,199}$")
IDENTIFIER_PART = r"(?:\[[A-Za-z_][A-Za-z0-9_$#@]*\]|[A-Za-z_][A-Za-z0-9_$#@]*)"
QUALIFIED_TABLE = rf"(?P<schema>{IDENTIFIER_PART})\s*\.\s*(?P<table>{IDENTIFIER_PART})"
THREE_PART_NAME = re.compile(
    rf"(?P<database>{IDENTIFIER_PART})\s*\.\s*"
    rf"{IDENTIFIER_PART}\s*\.\s*{IDENTIFIER_PART}",
    re.IGNORECASE,
)
TEMP_TABLE = re.compile(r"^#(?!#)[A-Za-z_][A-Za-z0-9_]{0,126}$")
MAX_WRITE_STATEMENTS = 25
MAX_WRITE_ROWS = 10_000
MAX_WRITE_PARAMETERS = 500
MAX_DATA_MOVE_SOURCES = 8
MAX_DATA_MOVE_STATEMENTS = 100
MAX_DATA_MOVE_ROWS = 100_000_000
MAX_DATA_MOVE_PARAMETERS = 5_000
LOCATIONS_FEATURE_MIGRATION = "locations_session_surcharge_locale_v1"
LOCATIONS_FEATURE_TABLE = "dbo.Locations"
KIT_UPGRADE_MIGRATION = "kit_upgrade_v1"
KIT_UPGRADE_TABLE = "dbo.Kit"
LOCATION_REGION_UPDATE = "location_region_update_v1"
LOCATION_REACTIVATION_UPDATE = "location_reactivation_update_v1"
LOCATION_LAYAWAY_ENABLE = "location_layaway_enable_v1"
INVOICE_SPARE_INVESTIGATION = "invoice_spare_investigation_v1"
LOCATION_LAYAWAY_TABLE = "dbo.Locations_Layaways"
LOCATION_LAYAWAY_MAX_LOCATIONS = 100
LOCATION_LAYAWAY_DEFAULTS = {
    "expirationDay": 90,
    "isChangeLayawayExpirationDate": 0,
    "minFirstPayment": 10,
    "disclaimer": "Please come back and ask for our returning customer discount!",
}
LOCATION_REGION_SAFE_TRIGGER_NAME = "tr_locations_fixzero"
LOCATION_REGION_SAFE_TRIGGER_DEFINITION = """
CREATE TRIGGER tr_Locations_FixZero
   ON  Locations
   AFTER INSERT, UPDATE
AS
BEGIN
    SET NOCOUNT ON;

DECLARE @InputRegion int, @MinRegion int, @LocationID int

SELECT
  @InputRegion = RegionID
FROM Inserted

IF @InputRegion = 0
BEGIN
  SELECT @LocationID = LocationID FROM Inserted
  SELECT @MinRegion = MIN(RegionID) FROM Regions
  INSERT INTO Logs (ActionName, LogDescription)

  SELECT 'Trigger: Fix Location Zero', 'Region swithced to: ' + ISNULL(CAST(@MinRegion as varchar(10)),' ') + ' for Location: ' + ISNULL(CAST(@LocatioNID as varchar(10)), '1')

  UPDATE Locations
  SET RegionID = @MinRegion
  WHERE RegionID = 0
END

END
"""
LOCATIONS_FEATURE_COLUMNS = (
    {
        "name": "SessionIdleTime",
        "ddl": "[SessionIdleTime] INT NULL",
        "type": "int",
        "maxLength": 4,
        "precision": 10,
        "scale": 0,
    },
    {
        "name": "IsSurchargeEnabled",
        "ddl": "[IsSurchargeEnabled] BIT NULL",
        "type": "bit",
        "maxLength": 1,
        "precision": 1,
        "scale": 0,
    },
    {
        "name": "SurchargePercentage",
        "ddl": "[SurchargePercentage] DECIMAL(5,2) NULL",
        "type": "decimal",
        "maxLength": 5,
        "precision": 5,
        "scale": 2,
    },
    {
        "name": "SurchargeLabel",
        "ddl": "[SurchargeLabel] VARCHAR(20) NULL",
        "type": "varchar",
        "maxLength": 20,
        "precision": 0,
        "scale": 0,
    },
    {
        "name": "locale_code",
        "ddl": "[locale_code] NVARCHAR(10) NULL",
        "type": "nvarchar",
        "maxLength": 20,
        "precision": 0,
        "scale": 0,
    },
)
KIT_UPGRADE_COLUMNS = (
    {
        "name": "TierDiscountPercents",
        "ddl": "[TierDiscountPercents] NVARCHAR(400) NULL",
        "type": "nvarchar",
        "maxLength": 800,
        "precision": 0,
        "scale": 0,
    },
    {
        "name": "DiscountType",
        "ddl": "[DiscountType] INT NULL",
        "type": "int",
        "maxLength": 4,
        "precision": 10,
        "scale": 0,
    },
    {
        "name": "ContinueLastTier",
        "ddl": "[ContinueLastTier] BIT NULL",
        "type": "bit",
        "maxLength": 1,
        "precision": 1,
        "scale": 0,
    },
    {
        "name": "BundleQuantity",
        "ddl": "[BundleQuantity] INT NULL",
        "type": "int",
        "maxLength": 4,
        "precision": 10,
        "scale": 0,
    },
    {
        "name": "BundlePrice",
        "ddl": "[BundlePrice] DECIMAL(18,2) NULL",
        "type": "decimal",
        "maxLength": 9,
        "precision": 18,
        "scale": 2,
    },
    {
        "name": "BuyQuantity",
        "ddl": "[BuyQuantity] INT NULL",
        "type": "int",
        "maxLength": 4,
        "precision": 10,
        "scale": 0,
    },
    {
        "name": "GetQuantity",
        "ddl": "[GetQuantity] INT NULL",
        "type": "int",
        "maxLength": 4,
        "precision": 10,
        "scale": 0,
    },
    {
        "name": "GetDiscountPercent",
        "ddl": "[GetDiscountPercent] DECIMAL(5,2) NULL",
        "type": "decimal",
        "maxLength": 5,
        "precision": 5,
        "scale": 2,
    },
    {
        "name": "StopAfterFirstGroup",
        "ddl": "[StopAfterFirstGroup] BIT NULL",
        "type": "bit",
        "maxLength": 1,
        "precision": 1,
        "scale": 0,
    },
    {
        "name": "SubtotalMinimum",
        "ddl": "[SubtotalMinimum] DECIMAL(18,2) NULL",
        "type": "decimal",
        "maxLength": 9,
        "precision": 18,
        "scale": 2,
    },
    {
        "name": "SubtotalDiscountPercent",
        "ddl": "[SubtotalDiscountPercent] DECIMAL(5,2) NULL",
        "type": "decimal",
        "maxLength": 5,
        "precision": 5,
        "scale": 2,
    },
    {
        "name": "SubtotalTarget",
        "ddl": "[SubtotalTarget] INT NULL",
        "type": "int",
        "maxLength": 4,
        "precision": 10,
        "scale": 0,
    },
    {
        "name": "SubtotalNthPosition",
        "ddl": "[SubtotalNthPosition] INT NULL",
        "type": "int",
        "maxLength": 4,
        "precision": 10,
        "scale": 0,
    },
    {
        "name": "StartDate",
        "ddl": "[StartDate] DATETIME NULL",
        "type": "datetime",
        "maxLength": 8,
        "precision": 23,
        "scale": 3,
    },
    {
        "name": "EndDate",
        "ddl": "[EndDate] DATETIME NULL",
        "type": "datetime",
        "maxLength": 8,
        "precision": 23,
        "scale": 3,
    },
)
KIT_UPGRADE_PRESERVED_COLUMNS = (
    "Id",
    "Name",
    "Description",
    "Barcode",
    "Picture",
    "NumberOfProducts",
    "Active",
    "CreatedOn",
    "CreatedBy",
    "ModifiedOn",
    "ModifiedBy",
    "LessExpensiveItemDiscountPercent",
)


class NovaSqlScopeError(ValueError):
    """A query exceeded the fixed read-only Nova SQL boundary."""


class NovaSqlUnavailableError(RuntimeError):
    """The bounded Nova SQL provider connection is unavailable."""


@dataclass(frozen=True)
class NovaSqlSettings:
    server: str = "cluster.novapointofsale.com,6682"
    driver: str = ""
    connection_timeout_seconds: int = 30
    query_timeout_seconds: int = 30
    maximum_rows: int = 200
    maximum_response_characters: int = 500_000
    api_cohort_credential_file: str = ""
    api_cohort_maximum_rows: int = 5_000
    developer_username_file: str = ""
    developer_password_file: str = ""


@dataclass(frozen=True)
class ValidatedWriteStatement:
    sql: str
    parameters: list[Any]
    kind: str
    target_table: str
    persistent: bool
    identity_insert: bool


@dataclass(frozen=True)
class ValidatedWritePlan:
    company_username: str
    source_company_usernames: tuple[str, ...]
    statements: list[ValidatedWriteStatement]
    verification_sql: str
    verification_parameters: list[Any]
    expected_affected_rows: int
    expected_verification_value: int
    idempotency_key: str
    target_operations: dict[str, tuple[str, ...]]
    identity_insert_targets: tuple[str, ...]
    maximum_affected_rows: int
    plan_hash: str


class ScopedNovaSqlClient:
    """Exact-database reads plus an optional Taylor-only guarded write path."""

    def __init__(
        self,
        salesforce_client: Any,
        settings: NovaSqlSettings | None = None,
        *,
        connect_factory: Callable[[str], Any] | None = None,
        drivers_factory: Callable[[], list[str]] | None = None,
        write_enabled: bool = False,
        write_state_dir: str | Path | None = None,
        instyle_demo_restore_gateway: ProtectedDemoRestoreGateway | None = None,
    ) -> None:
        self.salesforce_client = salesforce_client
        self.settings = settings or NovaSqlSettings()
        self._connect_factory = connect_factory
        self._drivers_factory = drivers_factory
        self.write_enabled = bool(write_enabled)
        default_state = Path(os.getenv("LOCALAPPDATA") or ".") / "NovaSqlGuardedExecutor"
        self.write_state_dir = Path(write_state_dir or default_state).expanduser().resolve()
        self._instyle_demo_rebuild = InstyleDemoRebuildOperation(
            connect=lambda company_username, read_only: self._connect(
                company_username,
                read_only=read_only,
            ),
            state_dir=self.write_state_dir,
            restore_gateway=instyle_demo_restore_gateway,
            query_timeout_seconds=self.settings.query_timeout_seconds,
        )
        self._instyle_demo_sync = SetBasedInstyleDemoSyncOperation(
            connect=lambda read_only: self._connect_developer(
                read_only=read_only,
                autocommit=True,
            ),
            state_dir=self.write_state_dir,
            query_timeout_seconds=max(self.settings.query_timeout_seconds, 3_600),
        )
        self._instyle_runway_merge = InstyleRunwayMergeOperation(
            connect=lambda read_only: self._connect_developer(
                read_only=read_only,
                company_username=INSTYLE_RUNWAY_USERNAME,
                autocommit=True,
            ),
            resolve_account=lambda company_username: self.salesforce_client._resolve_nova_sql_account(
                company_username
            ),
            state_dir=self.write_state_dir,
            query_timeout_seconds=max(self.settings.query_timeout_seconds, 7_200),
        )
        self._oklahoma_hawaii_catalog_replace = OklahomaHawaiiCatalogReplaceOperation(
            connect=lambda read_only: self._connect_developer(
                read_only=read_only,
                company_username="oklahoma",
                autocommit=read_only,
            ),
            state_dir=self.write_state_dir,
            query_timeout_seconds=max(self.settings.query_timeout_seconds, 120),
        )
        self._instyle_demo_restore_gateway = instyle_demo_restore_gateway
        self._table_restore = NovaSqlTableRestoreOperation(
            connect_database=lambda company_username, database_name, read_only: (
                self._connect_database(
                    company_username,
                    database_name,
                    read_only=read_only,
                )
            ),
            state_dir=self.write_state_dir,
            query_timeout_seconds=max(self.settings.query_timeout_seconds, 120),
        )
        self._account_copy = AccountCopyOperation(
            connect=lambda company_username, read_only: self._connect_developer(
                read_only=read_only,
                company_username=company_username,
                autocommit=False,
            ),
            preview_guarded=self.preview_write,
            execute_guarded=self.execute_guarded_write,
            guarded_status=self._guarded_write_receipt_status,
            state_dir=self.write_state_dir,
        )
        self._ticket_347534_invoice_repair = Ticket347534InvoiceRepairOperation(
            connect=lambda read_only: self._connect_developer(
                read_only=read_only,
                company_username=TICKET_347534_TARGET_USERNAME,
                autocommit=False,
            ),
            state_dir=self.write_state_dir,
            query_timeout_seconds=max(self.settings.query_timeout_seconds, 120),
        )

    def capability_status(self) -> dict[str, Any]:
        try:
            driver = self._driver()
        except NovaSqlUnavailableError:
            driver = ""
        return {
            "ok": bool(driver),
            "accessMode": "bounded_read_and_guarded_write" if self.write_enabled else "bounded_read_only",
            "driverConfigured": bool(driver),
            "maximumRows": self.settings.maximum_rows,
            "exactDatabaseBinding": True,
            "secretColumnsReturned": False,
            "allowedReadOperations": [
                "bounded_select",
                "schema_preflight",
                "authoritative_billing_locations",
                INVOICE_SPARE_INVESTIGATION,
            ],
            "writesExposed": self.write_enabled,
            "writeOwner": "coding_agent",
            "allowedWriteOperations": (
                [
                    "update",
                    "insert",
                    "temporary_table",
                    "fixed_table_restore",
                    "fixed_location_region_update",
                    "fixed_location_reactivation_update",
                    "fixed_location_layaway_enable",
                    "fixed_locations_feature_migration",
                    "kit_upgrade",
                    "fixed_instyle_demo_set_based_sync",
                    "fixed_instyle_runway_production_merge",
                    "fixed_oklahoma_hawaii_catalog_replace",
                    "fixed_ticket_347534_invoice_location_repair",
                    "guarded_cross_account_set_based_insert_update",
                    "schema_aware_account_copy",
                ]
                if self.write_enabled
                else []
            ),
            "allowedSchemaMigrations": (
                [LOCATIONS_FEATURE_MIGRATION, KIT_UPGRADE_MIGRATION]
                if self.write_enabled
                else []
            ),
            "forbiddenWriteOperations": [
                "generic_delete",
                "drop",
                "truncate",
                "arbitrary_alter",
                "merge",
            ],
            "fixedDestructiveOperations": (
                ["oklahoma_hawaii_catalog_replace_v1", TICKET_347534_INVOICE_REPAIR]
                if self.write_enabled
                else []
            ),
            "genericDeleteExposed": False,
            "backupBeforePermanentWrite": self.write_enabled,
            "apiCustomerEmailCohortConfigured": bool(self.settings.api_cohort_credential_file),
            "apiCustomerEmailCohortReadOnly": True,
            "instyleDemoRebuildConfigured": bool(self._instyle_demo_restore_gateway),
            "instyleDemoSyncConfigured": bool(
                self.write_enabled
                and self._instyle_demo_sync.configured
                and self.settings.developer_username_file
                and self.settings.developer_password_file
            ),
            "instyleDemoRebuildFixedSources": ["LE_BOUTIQUE_INSTYLE", "Instyle_Fragrance"],
            "instyleDemoRebuildFixedTarget": "DEMO_NOVA_CAFE",
            "instyleDemoRebuildGenericExecutorChanged": False,
            "instyleDemoSyncExecutionMode": "single_database_side_set_based_sql",
            "instyleDemoSyncInventoryHistoryPolicy": "copy_missing_rows_set_based",
            "instyleDemoSyncSourceDatabasesReadOnly": True,
            "instyleDemoSyncTargetBackupRequired": False,
            "instyleRunwayMergeConfigured": bool(
                self.write_enabled
                and self._instyle_runway_merge.configured
                and self.settings.developer_username_file
                and self.settings.developer_password_file
            ),
            "instyleRunwayMergeFixedSources": [
                "LE_BOUTIQUE_INSTYLE",
                "Instyle_Fragrance",
            ],
            "instyleRunwayMergeFixedTarget": "INSTYLE_RUNWAY",
            "instyleRunwayMergeSourceDatabasesReadOnly": True,
            "instyleRunwayMergeTargetBackupsRequired": True,
            "instyleRunwayMergeAtomic": True,
            "oklahomaHawaiiCatalogReplaceConfigured": bool(
                self.write_enabled
                and self.settings.developer_username_file
                and self.settings.developer_password_file
            ),
            "oklahomaHawaiiCatalogReplaceFixedSource": "unique_lifestyle_llc",
            "oklahomaHawaiiCatalogReplaceFixedTarget": "oklahoma",
            "oklahomaHawaiiCatalogReplaceFixedCategory": "HAWAII",
            "oklahomaHawaiiCatalogReplaceGenericDeleteChanged": False,
            "oklahomaHawaiiCatalogReplaceTargetBackupsRequired": True,
            "oklahomaHawaiiCatalogReplaceAtomic": True,
            "ticket347534InvoiceRepairConfigured": bool(
                self.write_enabled
                and self.settings.developer_username_file
                and self.settings.developer_password_file
            ),
            "ticket347534InvoiceRepairProtectedInvoiceId": 73242,
            "ticket347534InvoiceRepairGenericDeleteChanged": False,
            "crossAccountDataMoveConfigured": bool(
                self.write_enabled
                and self.settings.developer_username_file
                and self.settings.developer_password_file
            ),
            "crossAccountDataMoveModes": [
                "insert_select",
                "update_from_join",
                "temporary_staging",
            ],
            "crossAccountDataMoveMaximumSources": MAX_DATA_MOVE_SOURCES,
            "crossAccountDataMoveMaximumStatements": MAX_DATA_MOVE_STATEMENTS,
            "crossAccountDataMoveMaximumAffectedRows": MAX_DATA_MOVE_ROWS,
            "crossAccountDataMoveTargetBackupRequired": True,
            "crossAccountDataMoveSourceDatabasesReadOnlyByStatementPolicy": True,
            "accountCopy": {
                **self._account_copy.capabilities(),
                "configured": bool(
                    self.write_enabled
                    and self.settings.developer_username_file
                    and self.settings.developer_password_file
                ),
            },
            "tableRestore": (
                self._table_restore.capabilities()
                if self.write_enabled
                else {"configured": False, "writeOwner": "coding_agent"}
            ),
        }

    def update_location_region(
        self,
        company_username: str,
        location_id: int,
        region_id: int,
        idempotency_key: str,
    ) -> dict[str, Any]:
        """Set one exact dbo.Locations RegionId with backup, idempotency, and readback."""

        self._require_write_enabled()
        clean_username = _company_username(company_username)
        clean_location_id = _positive_int(location_id, "location_id")
        clean_region_id = _positive_int(region_id, "region_id")
        clean_key = _idempotency_key(idempotency_key)
        plan_hash = hashlib.sha256(
            json.dumps(
                {
                    "operation": LOCATION_REGION_UPDATE,
                    "companyUsername": clean_username.casefold(),
                    "locationId": clean_location_id,
                    "regionId": clean_region_id,
                    "idempotencyKey": clean_key,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        receipt_path = _location_region_receipt_path(self.write_state_dir, clean_key)
        existing_receipt = _read_json_file(receipt_path)
        if existing_receipt:
            result = _location_region_receipt_result(
                existing_receipt,
                company_username=clean_username,
                location_id=clean_location_id,
                region_id=clean_region_id,
                idempotency_key=clean_key,
                plan_hash=plan_hash,
                replay=True,
            )
            with closing(self._connect(clean_username, read_only=True)) as connection:
                cursor = connection.cursor()
                _verify_database_binding(cursor, clean_username)
                readback = _read_location_region(cursor, clean_location_id)
            if readback["regionId"] != clean_region_id:
                raise NovaSqlUnavailableError(
                    "the prior location-region receipt no longer matches authoritative readback"
                )
            return {**result, "readback": readback}

        committed = False
        backup_rows: list[dict[str, Any]] = []
        before: dict[str, int] = {}
        after: dict[str, int] = {}
        with closing(self._connect(clean_username, read_only=False)) as connection:
            connection.timeout = self.settings.query_timeout_seconds
            cursor = connection.cursor()
            try:
                cursor.execute("SET XACT_ABORT ON")
                _verify_database_binding(cursor, clean_username)
                _acquire_write_lock(cursor, clean_username, clean_key)

                existing_receipt = _read_json_file(receipt_path)
                if existing_receipt:
                    connection.rollback()
                    result = _location_region_receipt_result(
                        existing_receipt,
                        company_username=clean_username,
                        location_id=clean_location_id,
                        region_id=clean_region_id,
                        idempotency_key=clean_key,
                        plan_hash=plan_hash,
                        replay=True,
                    )
                    readback = _read_location_region(cursor, clean_location_id)
                    if readback["regionId"] != clean_region_id:
                        raise NovaSqlUnavailableError(
                            "the concurrent location-region receipt does not match authoritative readback"
                        )
                    return {**result, "readback": readback}

                before = _read_location_region(
                    cursor,
                    clean_location_id,
                    lock_for_update=True,
                )
                if before["regionId"] == clean_region_id:
                    connection.rollback()
                    receipt = _write_location_region_receipt(
                        receipt_path,
                        company_username=clean_username,
                        location_id=clean_location_id,
                        region_id=clean_region_id,
                        idempotency_key=clean_key,
                        plan_hash=plan_hash,
                        status="completed",
                        before=before,
                        after=before,
                        backups=[],
                        transaction_committed=False,
                        no_op=True,
                    )
                    return _location_region_receipt_result(
                        receipt,
                        company_username=clean_username,
                        location_id=clean_location_id,
                        region_id=clean_region_id,
                        idempotency_key=clean_key,
                        plan_hash=plan_hash,
                        replay=False,
                    )

                _validate_location_region_update_surface(cursor, clean_region_id)
                backup_table = _backup_table_identifier(LOCATIONS_FEATURE_TABLE, plan_hash)
                if _table_exists(cursor, backup_table):
                    raise NovaSqlScopeError(
                        "the deterministic Locations backup already exists without a completed receipt; do not retry"
                    )
                source_sql = _quoted_table(LOCATIONS_FEATURE_TABLE)
                backup_sql = _quoted_table(backup_table)
                cursor.execute(
                    f"SELECT * INTO {backup_sql} FROM {source_sql} WITH (HOLDLOCK, TABLOCKX)"
                )
                source_count = int(
                    cursor.execute(f"SELECT COUNT_BIG(*) FROM {source_sql}").fetchone()[0] or 0
                )
                backup_count = int(
                    cursor.execute(f"SELECT COUNT_BIG(*) FROM {backup_sql}").fetchone()[0] or 0
                )
                if source_count != backup_count:
                    raise NovaSqlScopeError(
                        "automatic dbo.Locations backup row-count verification failed"
                    )
                backup_rows.append(
                    {
                        "sourceTable": LOCATIONS_FEATURE_TABLE,
                        "backupTable": backup_table,
                        "rowCount": backup_count,
                    }
                )

                cursor.execute(
                    "UPDATE [dbo].[Locations] SET [RegionId]=? WHERE [LocationId]=?",
                    [clean_region_id, clean_location_id],
                )
                if int(cursor.rowcount or 0) != 1:
                    raise NovaSqlScopeError(
                        "the exact location-region update did not affect one row"
                    )
                after = _read_location_region(cursor, clean_location_id)
                if after["regionId"] != clean_region_id:
                    raise NovaSqlScopeError(
                        "pre-commit location-region readback did not match the requested value"
                    )

                connection.commit()
                committed = True
                after = _read_location_region(cursor, clean_location_id)
                if after["regionId"] != clean_region_id:
                    _write_location_region_receipt(
                        receipt_path,
                        company_username=clean_username,
                        location_id=clean_location_id,
                        region_id=clean_region_id,
                        idempotency_key=clean_key,
                        plan_hash=plan_hash,
                        status="committed_readback_failed",
                        before=before,
                        after=after,
                        backups=backup_rows,
                        transaction_committed=True,
                        no_op=False,
                    )
                    raise NovaSqlUnavailableError(
                        "location-region update committed without verified readback; do not retry"
                    )
                receipt = _write_location_region_receipt(
                    receipt_path,
                    company_username=clean_username,
                    location_id=clean_location_id,
                    region_id=clean_region_id,
                    idempotency_key=clean_key,
                    plan_hash=plan_hash,
                    status="completed",
                    before=before,
                    after=after,
                    backups=backup_rows,
                    transaction_committed=True,
                    no_op=False,
                )
            except (NovaSqlScopeError, NovaSqlUnavailableError):
                if not committed:
                    try:
                        connection.rollback()
                    except Exception:
                        pass
                raise
            except Exception as exc:
                if not committed:
                    try:
                        connection.rollback()
                    except Exception:
                        pass
                    raise NovaSqlUnavailableError(
                        "location-region update failed and was rolled back"
                    ) from exc
                try:
                    _write_location_region_receipt(
                        receipt_path,
                        company_username=clean_username,
                        location_id=clean_location_id,
                        region_id=clean_region_id,
                        idempotency_key=clean_key,
                        plan_hash=plan_hash,
                        status="committed_readback_failed",
                        before=before,
                        after=after,
                        backups=backup_rows,
                        transaction_committed=True,
                        no_op=False,
                    )
                except Exception:
                    pass
                raise NovaSqlUnavailableError(
                    "location-region update committed without a final receipt; do not retry"
                ) from exc

        return _location_region_receipt_result(
            receipt,
            company_username=clean_username,
            location_id=clean_location_id,
            region_id=clean_region_id,
            idempotency_key=clean_key,
            plan_hash=plan_hash,
            replay=False,
        )

    def update_location_reactivation(
        self,
        company_username: str,
        location_id: int,
        idempotency_key: str,
    ) -> dict[str, Any]:
        """Reactivate one exact location by changing manager employee 1 to 0."""

        self._require_write_enabled()
        clean_username = _company_username(company_username)
        clean_location_id = _positive_int(location_id, "location_id")
        clean_key = _idempotency_key(idempotency_key)
        plan_hash = hashlib.sha256(
            json.dumps(
                {
                    "operation": LOCATION_REACTIVATION_UPDATE,
                    "companyUsername": clean_username.casefold(),
                    "locationId": clean_location_id,
                    "fromLocationManagerEmployeeId": 1,
                    "toLocationManagerEmployeeId": 0,
                    "idempotencyKey": clean_key,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        receipt_path = _location_reactivation_receipt_path(
            self.write_state_dir,
            clean_key,
        )
        existing_receipt = _read_json_file(receipt_path)
        if existing_receipt:
            result = _location_reactivation_receipt_result(
                existing_receipt,
                company_username=clean_username,
                location_id=clean_location_id,
                idempotency_key=clean_key,
                plan_hash=plan_hash,
                replay=True,
            )
            with closing(self._connect(clean_username, read_only=True)) as connection:
                cursor = connection.cursor()
                _verify_database_binding(cursor, clean_username)
                readback = _read_location_reactivation(cursor, clean_location_id)
            if readback["locationManagerEmployeeId"] != 0:
                raise NovaSqlUnavailableError(
                    "the prior location-reactivation receipt no longer matches authoritative readback"
                )
            return {**result, "readback": readback}

        committed = False
        backup_rows: list[dict[str, Any]] = []
        before: dict[str, int] = {}
        after: dict[str, int] = {}
        with closing(self._connect(clean_username, read_only=False)) as connection:
            connection.timeout = self.settings.query_timeout_seconds
            cursor = connection.cursor()
            try:
                cursor.execute("SET XACT_ABORT ON")
                _verify_database_binding(cursor, clean_username)
                _acquire_write_lock(cursor, clean_username, clean_key)

                existing_receipt = _read_json_file(receipt_path)
                if existing_receipt:
                    connection.rollback()
                    result = _location_reactivation_receipt_result(
                        existing_receipt,
                        company_username=clean_username,
                        location_id=clean_location_id,
                        idempotency_key=clean_key,
                        plan_hash=plan_hash,
                        replay=True,
                    )
                    readback = _read_location_reactivation(cursor, clean_location_id)
                    if readback["locationManagerEmployeeId"] != 0:
                        raise NovaSqlUnavailableError(
                            "the concurrent location-reactivation receipt does not match authoritative readback"
                        )
                    return {**result, "readback": readback}

                before = _read_location_reactivation(
                    cursor,
                    clean_location_id,
                    lock_for_update=True,
                )
                if before["locationManagerEmployeeId"] == 0:
                    connection.rollback()
                    receipt = _write_location_reactivation_receipt(
                        receipt_path,
                        company_username=clean_username,
                        location_id=clean_location_id,
                        idempotency_key=clean_key,
                        plan_hash=plan_hash,
                        status="completed",
                        before=before,
                        after=before,
                        backups=[],
                        transaction_committed=False,
                        no_op=True,
                    )
                    return _location_reactivation_receipt_result(
                        receipt,
                        company_username=clean_username,
                        location_id=clean_location_id,
                        idempotency_key=clean_key,
                        plan_hash=plan_hash,
                        replay=False,
                    )
                if before["locationManagerEmployeeId"] != 1:
                    raise NovaSqlScopeError(
                        "location reactivation requires LocationManagerEmployeeID to be exactly 1"
                    )
                if before["regionId"] <= 0:
                    raise NovaSqlScopeError(
                        "location reactivation requires a positive existing RegionId"
                    )

                _validate_location_region_update_surface(cursor, before["regionId"])
                backup_table = _backup_table_identifier(
                    LOCATIONS_FEATURE_TABLE,
                    plan_hash,
                )
                if _table_exists(cursor, backup_table):
                    raise NovaSqlScopeError(
                        "the deterministic Locations backup already exists without a completed receipt; do not retry"
                    )
                source_sql = _quoted_table(LOCATIONS_FEATURE_TABLE)
                backup_sql = _quoted_table(backup_table)
                cursor.execute(
                    f"SELECT * INTO {backup_sql} FROM {source_sql} WITH (HOLDLOCK, TABLOCKX)"
                )
                source_count = int(
                    cursor.execute(
                        f"SELECT COUNT_BIG(*) FROM {source_sql}"
                    ).fetchone()[0]
                    or 0
                )
                backup_count = int(
                    cursor.execute(
                        f"SELECT COUNT_BIG(*) FROM {backup_sql}"
                    ).fetchone()[0]
                    or 0
                )
                if source_count != backup_count:
                    raise NovaSqlScopeError(
                        "automatic dbo.Locations backup row-count verification failed"
                    )
                backup_rows.append(
                    {
                        "sourceTable": LOCATIONS_FEATURE_TABLE,
                        "backupTable": backup_table,
                        "rowCount": backup_count,
                    }
                )

                cursor.execute(
                    "UPDATE [dbo].[Locations] SET [LocationManagerEmployeeID]=0 "
                    "WHERE [LocationId]=? AND [LocationManagerEmployeeID]=1 "
                    "AND [RegionId]=?",
                    [clean_location_id, before["regionId"]],
                )
                if int(cursor.rowcount or 0) != 1:
                    raise NovaSqlScopeError(
                        "the exact location-reactivation update did not affect one row"
                    )
                after = _read_location_reactivation(cursor, clean_location_id)
                if (
                    after["locationManagerEmployeeId"] != 0
                    or after["regionId"] != before["regionId"]
                ):
                    raise NovaSqlScopeError(
                        "pre-commit location-reactivation readback did not match the fixed contract"
                    )

                connection.commit()
                committed = True
                after = _read_location_reactivation(cursor, clean_location_id)
                if (
                    after["locationManagerEmployeeId"] != 0
                    or after["regionId"] != before["regionId"]
                ):
                    _write_location_reactivation_receipt(
                        receipt_path,
                        company_username=clean_username,
                        location_id=clean_location_id,
                        idempotency_key=clean_key,
                        plan_hash=plan_hash,
                        status="committed_readback_failed",
                        before=before,
                        after=after,
                        backups=backup_rows,
                        transaction_committed=True,
                        no_op=False,
                    )
                    raise NovaSqlUnavailableError(
                        "location reactivation committed without verified readback; do not retry"
                    )
                receipt = _write_location_reactivation_receipt(
                    receipt_path,
                    company_username=clean_username,
                    location_id=clean_location_id,
                    idempotency_key=clean_key,
                    plan_hash=plan_hash,
                    status="completed",
                    before=before,
                    after=after,
                    backups=backup_rows,
                    transaction_committed=True,
                    no_op=False,
                )
            except (NovaSqlScopeError, NovaSqlUnavailableError):
                if not committed:
                    try:
                        connection.rollback()
                    except Exception:
                        pass
                raise
            except Exception as exc:
                if not committed:
                    try:
                        connection.rollback()
                    except Exception:
                        pass
                    raise NovaSqlUnavailableError(
                        "location reactivation failed and was rolled back"
                    ) from exc
                try:
                    _write_location_reactivation_receipt(
                        receipt_path,
                        company_username=clean_username,
                        location_id=clean_location_id,
                        idempotency_key=clean_key,
                        plan_hash=plan_hash,
                        status="committed_readback_failed",
                        before=before,
                        after=after,
                        backups=backup_rows,
                        transaction_committed=True,
                        no_op=False,
                    )
                except Exception:
                    pass
                raise NovaSqlUnavailableError(
                    "location reactivation committed without a final receipt; do not retry"
                ) from exc

        return _location_reactivation_receipt_result(
            receipt,
            company_username=clean_username,
            location_id=clean_location_id,
            idempotency_key=clean_key,
            plan_hash=plan_hash,
            replay=False,
        )

    def enable_location_layaways(
        self,
        company_username: str,
        location_ids: list[int],
        idempotency_key: str,
    ) -> dict[str, Any]:
        """Enable layaway for exact locations with fixed defaults and verified readback."""

        self._require_write_enabled()
        clean_username = _company_username(company_username)
        clean_location_ids = _location_ids(location_ids)
        clean_key = _idempotency_key(idempotency_key)
        plan_hash = hashlib.sha256(
            json.dumps(
                {
                    "operation": LOCATION_LAYAWAY_ENABLE,
                    "companyUsername": clean_username.casefold(),
                    "locationIds": clean_location_ids,
                    "defaults": LOCATION_LAYAWAY_DEFAULTS,
                    "idempotencyKey": clean_key,
                },
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
            ).encode("utf-8")
        ).hexdigest()
        receipt_path = _location_layaway_receipt_path(
            self.write_state_dir,
            clean_key,
        )
        existing_receipt = _read_json_file(receipt_path)
        if existing_receipt:
            result = _location_layaway_receipt_result(
                existing_receipt,
                company_username=clean_username,
                location_ids=clean_location_ids,
                idempotency_key=clean_key,
                plan_hash=plan_hash,
                replay=True,
            )
            with closing(self._connect(clean_username, read_only=True)) as connection:
                cursor = connection.cursor()
                _verify_database_binding(cursor, clean_username)
                readback = _read_location_layaway_settings(
                    cursor,
                    clean_location_ids,
                )
            if not _location_layaway_rows_match_defaults(readback):
                raise NovaSqlUnavailableError(
                    "the prior location-layaway receipt no longer matches authoritative readback"
                )
            return {**result, "readback": readback}

        committed = False
        affected_rows = 0
        backup_rows: list[dict[str, Any]] = []
        before: list[dict[str, Any]] = []
        after: list[dict[str, Any]] = []
        with closing(self._connect(clean_username, read_only=False)) as connection:
            connection.timeout = self.settings.query_timeout_seconds
            cursor = connection.cursor()
            try:
                cursor.execute("SET XACT_ABORT ON")
                _verify_database_binding(cursor, clean_username)
                _acquire_write_lock(cursor, clean_username, clean_key)

                existing_receipt = _read_json_file(receipt_path)
                if existing_receipt:
                    connection.rollback()
                    result = _location_layaway_receipt_result(
                        existing_receipt,
                        company_username=clean_username,
                        location_ids=clean_location_ids,
                        idempotency_key=clean_key,
                        plan_hash=plan_hash,
                        replay=True,
                    )
                    readback = _read_location_layaway_settings(
                        cursor,
                        clean_location_ids,
                    )
                    if not _location_layaway_rows_match_defaults(readback):
                        raise NovaSqlUnavailableError(
                            "the concurrent location-layaway receipt does not match authoritative readback"
                        )
                    return {**result, "readback": readback}

                _validate_location_layaway_enable_surface(
                    cursor,
                    clean_location_ids,
                )
                before = _read_location_layaway_settings(
                    cursor,
                    clean_location_ids,
                    lock_for_update=True,
                )
                changes = [
                    row for row in before if not _location_layaway_row_matches_defaults(row)
                ]
                if not changes:
                    connection.rollback()
                    receipt = _write_location_layaway_receipt(
                        receipt_path,
                        company_username=clean_username,
                        location_ids=clean_location_ids,
                        idempotency_key=clean_key,
                        plan_hash=plan_hash,
                        status="completed",
                        affected_rows=0,
                        before=before,
                        after=before,
                        backups=[],
                        transaction_committed=False,
                        no_op=True,
                    )
                    return _location_layaway_receipt_result(
                        receipt,
                        company_username=clean_username,
                        location_ids=clean_location_ids,
                        idempotency_key=clean_key,
                        plan_hash=plan_hash,
                        replay=False,
                    )

                backup_table = _backup_table_identifier(
                    LOCATION_LAYAWAY_TABLE,
                    plan_hash,
                )
                if _table_exists(cursor, backup_table):
                    raise NovaSqlScopeError(
                        "the deterministic Locations_Layaways backup already exists without a completed receipt; do not retry"
                    )
                source_sql = _quoted_table(LOCATION_LAYAWAY_TABLE)
                backup_sql = _quoted_table(backup_table)
                cursor.execute(
                    f"SELECT * INTO {backup_sql} FROM {source_sql} WITH (HOLDLOCK, TABLOCKX)"
                )
                source_count = int(
                    cursor.execute(
                        f"SELECT COUNT_BIG(*) FROM {source_sql}"
                    ).fetchone()[0]
                    or 0
                )
                backup_count = int(
                    cursor.execute(
                        f"SELECT COUNT_BIG(*) FROM {backup_sql}"
                    ).fetchone()[0]
                    or 0
                )
                if source_count != backup_count:
                    raise NovaSqlScopeError(
                        "automatic dbo.Locations_Layaways backup row-count verification failed"
                    )
                backup_rows.append(
                    {
                        "sourceTable": LOCATION_LAYAWAY_TABLE,
                        "backupTable": backup_table,
                        "rowCount": backup_count,
                    }
                )

                for row in changes:
                    location_id = int(row["locationId"])
                    parameters = [
                        LOCATION_LAYAWAY_DEFAULTS["expirationDay"],
                        LOCATION_LAYAWAY_DEFAULTS[
                            "isChangeLayawayExpirationDate"
                        ],
                        LOCATION_LAYAWAY_DEFAULTS["minFirstPayment"],
                        LOCATION_LAYAWAY_DEFAULTS["disclaimer"],
                        location_id,
                    ]
                    if row["enabled"]:
                        cursor.execute(
                            "UPDATE [dbo].[Locations_Layaways] SET "
                            "[ExpirationDay]=?,[IsChangeLayawayExpirationDate]=?,"
                            "[MinFirstPayment]=?,[Disclaimer]=? WHERE [LocationId]=?",
                            parameters,
                        )
                    else:
                        cursor.execute(
                            "INSERT INTO [dbo].[Locations_Layaways] "
                            "([ExpirationDay],[IsChangeLayawayExpirationDate],"
                            "[MinFirstPayment],[Disclaimer],[LocationId]) "
                            "VALUES (?,?,?,?,?)",
                            parameters,
                        )
                    if int(cursor.rowcount or 0) != 1:
                        raise NovaSqlScopeError(
                            "each location layaway enablement must affect exactly one row"
                        )
                    affected_rows += 1

                if affected_rows != len(changes):
                    raise NovaSqlScopeError(
                        "location layaway affected-row verification failed"
                    )
                after = _read_location_layaway_settings(
                    cursor,
                    clean_location_ids,
                )
                if not _location_layaway_rows_match_defaults(after):
                    raise NovaSqlScopeError(
                        "pre-commit location-layaway readback did not match the fixed defaults"
                    )

                connection.commit()
                committed = True
                after = _read_location_layaway_settings(
                    cursor,
                    clean_location_ids,
                )
                if not _location_layaway_rows_match_defaults(after):
                    _write_location_layaway_receipt(
                        receipt_path,
                        company_username=clean_username,
                        location_ids=clean_location_ids,
                        idempotency_key=clean_key,
                        plan_hash=plan_hash,
                        status="committed_readback_failed",
                        affected_rows=affected_rows,
                        before=before,
                        after=after,
                        backups=backup_rows,
                        transaction_committed=True,
                        no_op=False,
                    )
                    raise NovaSqlUnavailableError(
                        "location layaway enablement committed without verified readback; do not retry"
                    )
                receipt = _write_location_layaway_receipt(
                    receipt_path,
                    company_username=clean_username,
                    location_ids=clean_location_ids,
                    idempotency_key=clean_key,
                    plan_hash=plan_hash,
                    status="completed",
                    affected_rows=affected_rows,
                    before=before,
                    after=after,
                    backups=backup_rows,
                    transaction_committed=True,
                    no_op=False,
                )
            except (NovaSqlScopeError, NovaSqlUnavailableError):
                if not committed:
                    try:
                        connection.rollback()
                    except Exception:
                        pass
                raise
            except Exception as exc:
                if not committed:
                    try:
                        connection.rollback()
                    except Exception:
                        pass
                    raise NovaSqlUnavailableError(
                        "location layaway enablement failed and was rolled back"
                    ) from exc
                try:
                    _write_location_layaway_receipt(
                        receipt_path,
                        company_username=clean_username,
                        location_ids=clean_location_ids,
                        idempotency_key=clean_key,
                        plan_hash=plan_hash,
                        status="committed_readback_failed",
                        affected_rows=affected_rows,
                        before=before,
                        after=after,
                        backups=backup_rows,
                        transaction_committed=True,
                        no_op=False,
                    )
                except Exception:
                    pass
                raise NovaSqlUnavailableError(
                    "location layaway enablement committed without a final receipt; do not retry"
                ) from exc

        return _location_layaway_receipt_result(
            receipt,
            company_username=clean_username,
            location_ids=clean_location_ids,
            idempotency_key=clean_key,
            plan_hash=plan_hash,
            replay=False,
        )

    def api_customer_email_cohort(self) -> dict[str, Any]:
        """Return the fixed, verified API-customer email cohort without caller-selected SQL."""

        with closing(self._connect_api_cohort()) as connection:
            connection.timeout = self.settings.query_timeout_seconds
            cursor = connection.cursor()
            database_row = cursor.execute("SELECT DB_NAME() AS DatabaseName").fetchone()
            database_name = str(database_row[0] or "") if database_row else ""
            if database_name.casefold() != API_COHORT_DATABASE.casefold():
                raise NovaSqlUnavailableError("API cohort reader connected to an unexpected database")
            cursor.execute(
                "SELECT Username,DatabaseName,ApiExpirationDate FROM dbo.users "
                "WHERE ApiExpirationDate IS NOT NULL "
                "AND ApiExpirationDate > SYSUTCDATETIME() "
                "AND NULLIF(LTRIM(RTRIM(Username)), '') IS NOT NULL "
                "ORDER BY Username"
            )
            raw_columns = tuple(str(column[0] or "") for column in (cursor.description or ()))
            if raw_columns != API_COHORT_COLUMNS:
                raise NovaSqlUnavailableError("API cohort query returned an unexpected schema")
            raw_rows = cursor.fetchmany(self.settings.api_cohort_maximum_rows + 1)

        if len(raw_rows) > self.settings.api_cohort_maximum_rows:
            raise NovaSqlUnavailableError("API cohort exceeds its fixed row ceiling; no partial list was returned")
        api_accounts = [
            {
                "companyUsername": str(row[0] or "").strip(),
                "databaseName": str(row[1] or "").strip(),
                "apiExpirationDate": _safe_value(row[2]),
            }
            for row in raw_rows
        ]
        result = self.salesforce_client.api_customer_email_cohort(api_accounts)
        return {
            **result,
            "accessMode": "fixed_read_only",
            "sourceDatabase": API_COHORT_DATABASE,
            "sourceTable": "dbo.users",
            "sourceColumns": list(API_COHORT_COLUMNS),
            "apiCandidateCount": len(api_accounts),
            "arbitrarySqlExposed": False,
            "writesExposed": False,
            "emailSent": False,
        }

    def preflight(self, company_username: str) -> dict[str, Any]:
        clean_username = _company_username(company_username)
        expected_database = f"POS_{clean_username}"
        with closing(self._connect(clean_username)) as connection:
            connection.timeout = self.settings.query_timeout_seconds
            cursor = connection.cursor()
            row = cursor.execute(
                "SELECT DB_NAME() AS DatabaseName, "
                "(SELECT COUNT_BIG(*) FROM sys.tables) AS TableCount, "
                "(SELECT COUNT_BIG(*) FROM sys.views) AS ViewCount"
            ).fetchone()
        database_name = str(row[0] or "")
        if database_name.casefold() != expected_database.casefold():
            raise NovaSqlUnavailableError("Nova SQL connected to an unexpected database")
        return {
            "ok": True,
            "accessMode": "bounded_read_only",
            "companyUsername": clean_username,
            "databaseName": database_name,
            "tableCount": int(row[1] or 0),
            "viewCount": int(row[2] or 0),
        }

    def billing_locations(self, company_username: str) -> dict[str, Any]:
        """Read the fixed location projection used by Nova BillingAutomation."""

        clean_username = _company_username(company_username)
        with closing(self._connect(clean_username)) as connection:
            connection.timeout = self.settings.query_timeout_seconds
            cursor = connection.cursor()
            cursor.execute(
                "SELECT LocationID,LocationName,LocationManagerEmployeeID "
                "FROM dbo.Locations ORDER BY LocationID"
            )
            columns = tuple(str(column[0] or "") for column in (cursor.description or ()))
            if columns != (
                "LocationID",
                "LocationName",
                "LocationManagerEmployeeID",
            ):
                raise NovaSqlUnavailableError(
                    "Nova BillingAutomation location projection returned an unexpected schema"
                )
            raw_rows = cursor.fetchmany(self.settings.maximum_rows + 1)

        if len(raw_rows) > self.settings.maximum_rows:
            raise NovaSqlUnavailableError(
                "Nova BillingAutomation location projection exceeded the fixed row ceiling"
            )
        locations: list[dict[str, Any]] = []
        for raw in raw_rows:
            try:
                location_id = int(raw[0])
                manager_employee_id = int(raw[2])
            except (TypeError, ValueError) as exc:
                raise NovaSqlUnavailableError(
                    "Nova BillingAutomation returned an invalid location identity or status"
                ) from exc
            if location_id <= 0:
                raise NovaSqlUnavailableError(
                    "Nova BillingAutomation returned a non-positive location identity"
                )
            name = str(raw[1] or "").strip()[:255]
            is_storage = bool(re.search(r"\bstorage\b", name, re.IGNORECASE))
            status = (
                "Active"
                if manager_employee_id == 0
                else "Inactive"
                if manager_employee_id == 1
                else "Unknown"
            )
            locations.append(
                {
                    "locationId": location_id,
                    "locationName": name,
                    "locationManagerEmployeeId": manager_employee_id,
                    "status": status,
                    "isStorage": is_storage,
                    "activeNonStorage": status == "Active" and not is_storage,
                }
            )
        return {
            "ok": True,
            "verified": True,
            "accessMode": "fixed_read_only",
            "sourceSystem": "Nova BillingAutomation",
            "sourceDatabase": f"POS_{clean_username}",
            "sourceTable": "dbo.Locations",
            "statusRule": "LocationManagerEmployeeID 0=Active, 1=Inactive",
            "companyUsername": clean_username,
            "locations": locations,
            "locationCount": len(locations),
            "activeNonStorageLocationIds": [
                row["locationId"] for row in locations if row["activeNonStorage"]
            ],
            "activeNonStorageCount": sum(
                1 for row in locations if row["activeNonStorage"]
            ),
            "writesPerformed": False,
            "arbitrarySqlExposed": False,
        }

    def invoice_spare_investigation(
        self,
        company_username: str,
        invoice_id: int,
    ) -> dict[str, Any]:
        """Reconcile one invoice and its bounded spare-transfer neighborhood."""

        clean_username = _company_username(company_username)
        clean_invoice_id = _positive_int(invoice_id, "invoice_id")
        maximum_related_invoices = 25

        header_columns = (
            "InvoiceID",
            "LocationID",
            "Timestamp",
            "ServerTimestamp",
            "Subtotal",
            "Tax",
            "Total",
            "Discount",
            "Spare",
            "SpareInvoiceID",
            "InvoiceTypeID",
            "TotalTip",
        )

        def fetch_rows(
            cursor: Any,
            sql: str,
            parameters: list[Any],
            expected_columns: tuple[str, ...],
            maximum_rows: int,
            label: str,
        ) -> list[dict[str, Any]]:
            cursor.execute(sql, parameters)
            columns = tuple(str(column[0] or "") for column in (cursor.description or ()))
            if columns != expected_columns:
                raise NovaSqlUnavailableError(
                    f"Nova SQL spare investigation returned an unexpected {label} schema"
                )
            rows = cursor.fetchmany(maximum_rows + 1)
            if len(rows) > maximum_rows:
                raise NovaSqlUnavailableError(
                    f"Nova SQL spare investigation exceeded the bounded {label} row ceiling"
                )
            return [dict(zip(columns, row)) for row in rows]

        with closing(self._connect(clean_username, read_only=True)) as connection:
            connection.timeout = self.settings.query_timeout_seconds
            cursor = connection.cursor()
            root_rows = fetch_rows(
                cursor,
                "SELECT InvoiceID,LocationID,[Timestamp],ServerTimestamp,Subtotal,Tax,Total,"
                "Discount,Spare,SpareInvoiceID,InvoiceTypeID,TotalTip "
                "FROM dbo.Invoices WHERE InvoiceID = ?",
                [clean_invoice_id],
                header_columns,
                1,
                "root invoice",
            )
            if not root_rows:
                raise NovaSqlUnavailableError("Nova SQL invoice was not found")

            source_invoice_id = int(root_rows[0].get("SpareInvoiceID") or 0)
            related_rows = fetch_rows(
                cursor,
                "SELECT InvoiceID,LocationID,[Timestamp],ServerTimestamp,Subtotal,Tax,Total,"
                "Discount,Spare,SpareInvoiceID,InvoiceTypeID,TotalTip "
                "FROM dbo.Invoices "
                "WHERE InvoiceID = ? OR SpareInvoiceID = ? "
                "OR (? > 0 AND InvoiceID = ?) "
                "OR (? > 0 AND SpareInvoiceID = ?) "
                "ORDER BY InvoiceID",
                [
                    clean_invoice_id,
                    clean_invoice_id,
                    source_invoice_id,
                    source_invoice_id,
                    source_invoice_id,
                    source_invoice_id,
                ],
                header_columns,
                maximum_related_invoices,
                "related invoice",
            )
            if not related_rows:
                related_rows = root_rows
            invoice_ids = sorted({int(row["InvoiceID"]) for row in related_rows})
            placeholders = ",".join("?" for _ in invoice_ids)

            line_columns = (
                "InvoiceID",
                "InvoiceProductsID",
                "ProductID",
                "ProductName",
                "Quantity",
                "SaleUnitPrice",
                "StoredUnitDiscount",
                "StoredProductTax",
                "ProductCostPriceAtSale",
                "CurrentBaseMinimumPrice",
                "CurrentPriceListMinimumPrice",
                "CurrentEffectiveMinimumPrice",
                "CurrentBaseMarkupPrice",
                "CurrentPriceListMarkupPrice",
                "CurrentEffectiveMarkupPrice",
                "PriceListID",
            )
            line_rows = fetch_rows(
                cursor,
                "SELECT ip.InvoiceID,ip.Invoice_Products_ID AS InvoiceProductsID,"
                "ip.ProductID,p.ProductName,ip.Quantity,ip.ProductPrice AS SaleUnitPrice,"
                "ip.ProductDiscount AS StoredUnitDiscount,ip.ProductTax AS StoredProductTax,"
                "ip.ProductCostPriceAtSale,p.ProductMinPrice AS CurrentBaseMinimumPrice,"
                "pli.ProductMinPrice AS CurrentPriceListMinimumPrice,"
                "COALESCE(pli.ProductMinPrice,p.ProductMinPrice,0) AS CurrentEffectiveMinimumPrice,"
                "p.ProductMarkupPrice AS CurrentBaseMarkupPrice,"
                "pli.ProductMarkupPrice AS CurrentPriceListMarkupPrice,"
                "COALESCE(pli.ProductMarkupPrice,p.ProductMarkupPrice,0) AS CurrentEffectiveMarkupPrice,"
                "l.PriceListID "
                "FROM dbo.Invoice_Products ip "
                "JOIN dbo.Invoices i ON i.InvoiceID=ip.InvoiceID "
                "JOIN dbo.Products p ON p.ProductID=ip.ProductID "
                "JOIN dbo.Locations l ON l.LocationID=i.LocationID "
                "LEFT JOIN dbo.PriceLists_Items pli "
                "ON pli.PriceListID=l.PriceListID AND pli.ProductID=ip.ProductID "
                f"WHERE ip.InvoiceID IN ({placeholders}) "
                "ORDER BY ip.InvoiceID,ip.Invoice_Products_ID",
                invoice_ids,
                line_columns,
                self.settings.maximum_rows,
                "invoice product",
            )

            payment_columns = (
                "InvoiceID",
                "InvoicePaymentID",
                "PaymentMethod",
                "Amount",
                "Tip",
                "Timestamp",
            )
            payment_rows = fetch_rows(
                cursor,
                "SELECT InvoiceID,Invoice_Payments_ID AS InvoicePaymentID,PaymentMethod,"
                "Amount,Tip,[Timestamp] FROM dbo.Invoice_Payments "
                f"WHERE InvoiceID IN ({placeholders}) "
                "ORDER BY InvoiceID,Invoice_Payments_ID",
                invoice_ids,
                payment_columns,
                self.settings.maximum_rows,
                "invoice payment",
            )

            coupon_columns = (
                "InvoiceID",
                "InvoiceCouponID",
                "CouponID",
                "AmountUsed",
                "Description",
                "Code",
                "CurrentCouponSpare",
            )
            coupon_rows = fetch_rows(
                cursor,
                "SELECT ic.InvoiceID,ic.Invoice_CouponsID AS InvoiceCouponID,ic.CouponID,"
                "ic.AmountUsed,c.Description,c.Code,c.Spare AS CurrentCouponSpare "
                "FROM dbo.Invoice_Coupons ic "
                "JOIN dbo.Coupons c ON c.CouponID=ic.CouponID "
                f"WHERE ic.InvoiceID IN ({placeholders}) "
                "ORDER BY ic.InvoiceID,ic.Invoice_CouponsID",
                invoice_ids,
                coupon_columns,
                self.settings.maximum_rows,
                "invoice coupon",
            )

            location_columns = (
                "LocationID",
                "LocationName",
                "IsForceMinimumPrice",
                "MaxMinutesSinceLastInvoiceToAttach",
                "PriceListID",
                "IsDisplayProductPriceIncTax",
            )
            location_ids = sorted({int(row["LocationID"]) for row in related_rows})
            location_placeholders = ",".join("?" for _ in location_ids)
            location_rows = fetch_rows(
                cursor,
                "SELECT LocationID,LocationName,IsForceMinimumPrice,"
                "MaxMinutesSinceLastInvoiceToAttach,PriceListID,IsDisplayProductPriceIncTax "
                f"FROM dbo.Locations WHERE LocationID IN ({location_placeholders}) "
                "ORDER BY LocationID",
                location_ids,
                location_columns,
                maximum_related_invoices,
                "location",
            )

        lines_by_invoice: dict[int, list[dict[str, Any]]] = {
            current_id: [] for current_id in invoice_ids
        }
        for row in line_rows:
            quantity = _money_decimal(row["Quantity"])
            sale_unit_price = _money_decimal(row["SaleUnitPrice"])
            unit_discount = _money_decimal(row["StoredUnitDiscount"])
            current_minimum = _money_decimal(row["CurrentEffectiveMinimumPrice"])
            gross = _money_round(sale_unit_price * quantity)
            total_discount = _money_round(unit_discount * quantity)
            net = _money_round((sale_unit_price - unit_discount) * quantity)
            current_minimum_total = _money_round(current_minimum * quantity)
            lines_by_invoice[int(row["InvoiceID"])].append(
                {
                    "invoiceProductsId": int(row["InvoiceProductsID"]),
                    "productId": int(row["ProductID"]),
                    "productName": str(row["ProductName"] or "")[:255],
                    "quantity": _safe_value(row["Quantity"]),
                    "saleUnitPrice": _safe_value(row["SaleUnitPrice"]),
                    "storedUnitDiscount": _safe_value(row["StoredUnitDiscount"]),
                    "grossAtSalePrice": _safe_value(gross),
                    "quantityAwareDiscount": _safe_value(total_discount),
                    "netAfterLineDiscount": _safe_value(net),
                    "currentEffectiveMinimumPrice": _safe_value(current_minimum),
                    "currentMinimumContribution": _safe_value(current_minimum_total),
                    "currentSpareContribution": _safe_value(
                        _money_round(net - current_minimum_total)
                    ),
                    "currentBaseMinimumPrice": _safe_value(row["CurrentBaseMinimumPrice"]),
                    "currentPriceListMinimumPrice": _safe_value(
                        row["CurrentPriceListMinimumPrice"]
                    ),
                    "currentEffectiveMarkupPrice": _safe_value(
                        row["CurrentEffectiveMarkupPrice"]
                    ),
                    "priceListId": _safe_value(row["PriceListID"]),
                    "storedProductTax": _safe_value(row["StoredProductTax"]),
                    "productCostPriceAtSale": _safe_value(row["ProductCostPriceAtSale"]),
                }
            )

        payments_by_invoice: dict[int, list[dict[str, Any]]] = {
            current_id: [] for current_id in invoice_ids
        }
        for row in payment_rows:
            payments_by_invoice[int(row["InvoiceID"])].append(
                {
                    "invoicePaymentId": int(row["InvoicePaymentID"]),
                    "paymentMethod": str(row["PaymentMethod"] or "")[:100],
                    "amount": _safe_value(row["Amount"]),
                    "tip": _safe_value(row["Tip"]),
                    "timestamp": _safe_value(row["Timestamp"]),
                }
            )

        coupons_by_invoice: dict[int, list[dict[str, Any]]] = {
            current_id: [] for current_id in invoice_ids
        }
        for row in coupon_rows:
            coupons_by_invoice[int(row["InvoiceID"])].append(
                {
                    "invoiceCouponId": int(row["InvoiceCouponID"]),
                    "couponId": int(row["CouponID"]),
                    "amountUsed": _safe_value(row["AmountUsed"]),
                    "description": str(row["Description"] or "")[:255],
                    "code": str(row["Code"] or "")[:100],
                    "currentCouponSpare": _safe_value(row["CurrentCouponSpare"]),
                }
            )

        invoice_results: list[dict[str, Any]] = []
        derived_by_invoice: dict[int, dict[str, Decimal]] = {}
        for row in related_rows:
            current_id = int(row["InvoiceID"])
            lines = lines_by_invoice[current_id]
            gross_products = _money_round(
                sum((_money_decimal(item["grossAtSalePrice"]) for item in lines), Decimal("0"))
            )
            quantity_aware_discount = _money_round(
                sum(
                    (_money_decimal(item["quantityAwareDiscount"]) for item in lines),
                    Decimal("0"),
                )
            )
            net_products = _money_round(gross_products - quantity_aware_discount)
            current_minimum_total = _money_round(
                sum(
                    (_money_decimal(item["currentMinimumContribution"]) for item in lines),
                    Decimal("0"),
                )
            )
            current_spare = _money_round(net_products - current_minimum_total)
            payment_total = _money_round(
                sum(
                    (
                        _money_decimal(item["amount"])
                        for item in payments_by_invoice[current_id]
                    ),
                    Decimal("0"),
                )
            )
            subtotal = _money_decimal(row["Subtotal"])
            total = _money_decimal(row["Total"])
            stored_spare = _money_decimal(row["Spare"])
            derived_by_invoice[current_id] = {
                "grossProducts": gross_products,
                "quantityAwareDiscount": quantity_aware_discount,
                "netProducts": net_products,
                "currentMinimumTotal": current_minimum_total,
                "currentSpare": current_spare,
                "paymentTotal": payment_total,
                "storedSpare": stored_spare,
            }
            invoice_results.append(
                {
                    "invoiceId": current_id,
                    "locationId": int(row["LocationID"]),
                    "timestamp": _safe_value(row["Timestamp"]),
                    "serverTimestamp": _safe_value(row["ServerTimestamp"]),
                    "subtotal": _safe_value(row["Subtotal"]),
                    "tax": _safe_value(row["Tax"]),
                    "total": _safe_value(row["Total"]),
                    "headerDiscount": _safe_value(row["Discount"]),
                    "storedSpare": _safe_value(row["Spare"]),
                    "spareInvoiceId": int(row["SpareInvoiceID"] or 0),
                    "invoiceTypeId": int(row["InvoiceTypeID"] or 0),
                    "totalTip": _safe_value(row["TotalTip"]),
                    "lineCount": len(lines),
                    "unitCount": _safe_value(
                        _money_round(
                            sum(
                                (_money_decimal(item["quantity"]) for item in lines),
                                Decimal("0"),
                            )
                        )
                    ),
                    "grossProducts": _safe_value(gross_products),
                    "quantityAwareLineDiscount": _safe_value(quantity_aware_discount),
                    "netProducts": _safe_value(net_products),
                    "currentMinimumTotal": _safe_value(current_minimum_total),
                    "currentSpareFromLineSnapshot": _safe_value(current_spare),
                    "subtotalMatchesNetProducts": _money_equal(subtotal, net_products),
                    "paymentTotal": _safe_value(payment_total),
                    "paymentMatchesInvoiceTotal": _money_equal(payment_total, total),
                    "lines": lines,
                    "payments": payments_by_invoice[current_id],
                    "coupons": coupons_by_invoice[current_id],
                }
            )

        root = next(item for item in invoice_results if item["invoiceId"] == clean_invoice_id)
        relationship: dict[str, Any] = {
            "attachedSourceInvoiceId": source_invoice_id,
            "approvalRule": "own spare + full attached invoice spare must be zero or positive",
            "grossRetailValueIsApprovalGate": False,
            "storedFinalSpare": root["storedSpare"],
            "historicalMinimumPriceCapturedOnInvoiceProduct": False,
            "currentProductMinimumsAreSnapshotOnly": True,
        }
        if source_invoice_id and source_invoice_id in derived_by_invoice:
            source = derived_by_invoice[source_invoice_id]
            root_derived = derived_by_invoice[clean_invoice_id]
            inferred_attached_spare = source["currentSpare"]
            if inferred_attached_spare > 0:
                inferred_own_spare = _money_round(
                    root_derived["storedSpare"] - inferred_attached_spare
                )
                inferred_at_sale_minimum = _money_round(
                    root_derived["netProducts"] - inferred_own_spare
                )
                current_minimum_gap = _money_round(
                    root_derived["currentMinimumTotal"] - inferred_at_sale_minimum
                )
                source_children = [
                    item
                    for item in invoice_results
                    if item["spareInvoiceId"] == source_invoice_id
                ]
                duplicate_signature = (
                    len(source_children) == 1
                    and _money_equal(source["storedSpare"], -inferred_attached_spare)
                )
                relationship.update(
                    {
                        "inferredAttachedSpareFromSourceLineSnapshot": _safe_value(
                            inferred_attached_spare
                        ),
                        "inferredOwnSpareAtSale": _safe_value(inferred_own_spare),
                        "inferredMinimumTotalAtSale": _safe_value(inferred_at_sale_minimum),
                        "currentMinimumSnapshotGap": _safe_value(current_minimum_gap),
                        "approvalArithmetic": {
                            "ownSpare": _safe_value(inferred_own_spare),
                            "attachedSpare": _safe_value(inferred_attached_spare),
                            "result": root["storedSpare"],
                            "wouldPass": root_derived["storedSpare"] >= 0,
                        },
                        "sourceExpectedSpareAfterOneFullTransfer": "0.00",
                        "sourceObservedStoredSpare": _safe_value(source["storedSpare"]),
                        "duplicateFullSourceDeductionSignature": duplicate_signature,
                        "duplicateDeductionInterpretation": (
                            "strong database signature; confirm the client persistence path before declaring root cause"
                            if duplicate_signature
                            else "not established from this bounded neighborhood"
                        ),
                        "minimumGapCandidates": _minimum_gap_candidates(
                            lines_by_invoice[clean_invoice_id], current_minimum_gap
                        ),
                    }
                )

        return {
            "ok": True,
            "verified": True,
            "accessMode": "fixed_deep_read_only",
            "operation": INVOICE_SPARE_INVESTIGATION,
            "companyUsername": clean_username,
            "databaseName": f"POS_{clean_username}",
            "requestedInvoiceId": clean_invoice_id,
            "relatedInvoiceIds": invoice_ids,
            "invoices": invoice_results,
            "locations": [
                {
                    "locationId": int(row["LocationID"]),
                    "locationName": str(row["LocationName"] or "")[:255],
                    "forceMinimumPrice": bool(row["IsForceMinimumPrice"]),
                    "maxMinutesSinceLastInvoiceToAttach": _safe_value(
                        row["MaxMinutesSinceLastInvoiceToAttach"]
                    ),
                    "priceListId": _safe_value(row["PriceListID"]),
                    "displayProductPriceIncludingTax": bool(
                        row["IsDisplayProductPriceIncTax"]
                    ),
                }
                for row in location_rows
            ],
            "spareRelationship": relationship,
            "calculationContract": {
                "grossProducts": "sum(ProductPrice * Quantity)",
                "quantityAwareLineDiscount": "sum(ProductDiscount * Quantity)",
                "netProducts": "sum((ProductPrice - ProductDiscount) * Quantity)",
                "currentSpareSnapshot": (
                    "net products - current effective minimum prices; current master or price-list "
                    "minimums are not proof of the historical minimum used at sale"
                ),
                "attachedInvoiceApproval": (
                    "the POS compares own spare plus the attached invoice's available spare; "
                    "gross retail value is not the approval threshold"
                ),
                "legacyTransferBehavior": (
                    "the full available source spare is transferred, not only the amount required"
                ),
            },
            "requiredAgentConclusionBoundaries": [
                "Separate stored facts from reconstructed values and source-code conclusions.",
                "Do not call current Products or PriceLists_Items minimum prices historical facts.",
                "Trace both the approval condition and every source-spare persistence call before confirming a duplicate deduction.",
                "Use quantity-aware discount math; never subtract one unit net from a multi-unit gross.",
                "Reconcile payments to invoice total, not gross product value.",
            ],
            "maximumRelatedInvoices": maximum_related_invoices,
            "writesPerformed": False,
            "arbitrarySqlExposed": False,
            "protectedColumnsReturned": False,
        }

    def read(
        self,
        company_username: str,
        sql: str,
        parameters: list[Any] | None = None,
        *,
        max_rows: int = 100,
    ) -> dict[str, Any]:
        clean_username = _company_username(company_username)
        clean_sql = _validated_select(sql)
        clean_parameters = _bounded_parameters(parameters)
        row_limit = max(1, min(int(max_rows), self.settings.maximum_rows))
        with closing(self._connect(clean_username)) as connection:
            connection.timeout = self.settings.query_timeout_seconds
            cursor = connection.cursor()
            cursor.execute(clean_sql, clean_parameters)
            if cursor.description is None:
                raise NovaSqlScopeError("Nova SQL read must return one result set")
            raw_columns = [str(column[0] or "")[:128] for column in cursor.description]
            allowed_indexes = [index for index, name in enumerate(raw_columns) if not SECRET_COLUMN.search(name)]
            if not allowed_indexes:
                raise NovaSqlScopeError("Nova SQL result contains only protected columns")
            columns = [raw_columns[index] for index in allowed_indexes]
            raw_rows = cursor.fetchmany(row_limit + 1)

        truncated = len(raw_rows) > row_limit
        rows: list[dict[str, Any]] = []
        response_characters = 0
        for raw_row in raw_rows[:row_limit]:
            item = {
                raw_columns[index]: _safe_value(raw_row[index])
                for index in allowed_indexes
            }
            response_characters += sum(len(str(value)) for value in item.values())
            if response_characters > self.settings.maximum_response_characters:
                truncated = True
                break
            rows.append(item)
        return {
            "ok": True,
            "accessMode": "bounded_read_only",
            "companyUsername": clean_username,
            "databaseName": f"POS_{clean_username}",
            "columns": columns,
            "rows": rows,
            "rowCount": len(rows),
            "truncated": truncated,
            "protectedColumnsOmitted": len(raw_columns) - len(columns),
        }

    def preview_write(
        self,
        company_username: str,
        statements: list[dict[str, Any]],
        verification_sql: str,
        expected_affected_rows: int,
        expected_verification_value: int,
        idempotency_key: str,
        verification_parameters: list[Any] | None = None,
        source_company_usernames: list[str] | None = None,
    ) -> dict[str, Any]:
        """Validate one immutable local or cross-account write plan without changing data."""

        self._require_write_enabled()
        plan = _validated_write_plan(
            company_username=company_username,
            statements=statements,
            verification_sql=verification_sql,
            verification_parameters=verification_parameters,
            expected_affected_rows=expected_affected_rows,
            expected_verification_value=expected_verification_value,
            idempotency_key=idempotency_key,
            source_company_usernames=source_company_usernames,
        )
        with closing(self._connect_write_plan(plan)) as connection:
            connection.timeout = (
                max(self.settings.query_timeout_seconds, 3_600)
                if plan.source_company_usernames
                else self.settings.query_timeout_seconds
            )
            cursor = connection.cursor()
            _verify_database_binding(cursor, plan.company_username)
            sources = _preview_source_databases(cursor, plan)
            targets = _preview_target_tables(cursor, plan)
            try:
                connection.rollback()
            except Exception:
                pass
        return {
            "ok": True,
            "status": "preview",
            "accessMode": "guarded_write_preview",
            "companyUsername": plan.company_username,
            "databaseName": f"POS_{plan.company_username}",
            "sourceCompanyUsernames": list(plan.source_company_usernames),
            "sourceDatabases": sources,
            "sourceDatabasesReadOnly": bool(plan.source_company_usernames),
            "executionMode": (
                "cross_account_set_based_sql"
                if plan.source_company_usernames
                else "single_account_guarded_sql"
            ),
            "planHash": plan.plan_hash,
            "idempotencyKey": plan.idempotency_key,
            "statementCount": len(plan.statements),
            "expectedAffectedRows": plan.expected_affected_rows,
            "expectedVerificationValue": plan.expected_verification_value,
            "permanentTargets": targets,
            "backupRequired": bool(targets),
            "backupStrategy": "full in-database table copy before the first permanent UPDATE or INSERT",
            "forbiddenOperations": ["DELETE", "DROP", "TRUNCATE", "ALTER", "MERGE", "dynamic SQL"],
            "maximumAffectedRows": plan.maximum_affected_rows,
        }

    def data_move_read(
        self,
        target_company_username: str,
        source_company_usernames: list[str],
        sql: str,
        parameters: list[Any] | None = None,
        *,
        max_rows: int = 100,
    ) -> dict[str, Any]:
        """Run one bounded SELECT across one target and explicitly allowlisted Nova sources."""

        self._require_write_enabled()
        clean_target = _company_username(target_company_username)
        clean_sources = _source_company_usernames(
            source_company_usernames,
            target_company_username=clean_target,
        )
        if not clean_sources:
            raise NovaSqlScopeError(
                "source_company_usernames must name at least one cross-account source"
            )
        clean_sql = _validated_select(
            sql,
            allowed_source_databases=tuple(
                f"POS_{value}" for value in clean_sources
            ),
        )
        clean_parameters = _bounded_parameters(parameters)
        row_limit = max(1, min(int(max_rows), self.settings.maximum_rows))
        with closing(
            self._connect_developer(
                read_only=True,
                company_username=clean_target,
            )
        ) as connection:
            connection.timeout = max(self.settings.query_timeout_seconds, 3_600)
            cursor = connection.cursor()
            _verify_database_binding(cursor, clean_target)
            source_databases = _source_database_summaries(cursor, clean_sources)
            cursor.execute(clean_sql, clean_parameters)
            if cursor.description is None:
                raise NovaSqlScopeError(
                    "cross-account Nova SQL read must return one result set"
                )
            raw_columns = [
                str(column[0] or "")[:128] for column in cursor.description
            ]
            allowed_indexes = [
                index
                for index, name in enumerate(raw_columns)
                if not SECRET_COLUMN.search(name)
            ]
            if not allowed_indexes:
                raise NovaSqlScopeError(
                    "cross-account Nova SQL result contains only protected columns"
                )
            columns = [raw_columns[index] for index in allowed_indexes]
            raw_rows = cursor.fetchmany(row_limit + 1)

        truncated = len(raw_rows) > row_limit
        rows: list[dict[str, Any]] = []
        response_characters = 0
        for raw_row in raw_rows[:row_limit]:
            item = {
                raw_columns[index]: _safe_value(raw_row[index])
                for index in allowed_indexes
            }
            response_characters += sum(len(str(value)) for value in item.values())
            if response_characters > self.settings.maximum_response_characters:
                truncated = True
                break
            rows.append(item)
        return {
            "ok": True,
            "accessMode": "bounded_cross_account_read_only",
            "targetCompanyUsername": clean_target,
            "targetDatabase": f"POS_{clean_target}",
            "sourceCompanyUsernames": list(clean_sources),
            "sourceDatabases": source_databases,
            "sourceDatabasesReadOnly": True,
            "columns": columns,
            "rows": rows,
            "rowCount": len(rows),
            "truncated": truncated,
            "protectedColumnsOmitted": len(raw_columns) - len(columns),
        }

    def execute_guarded_write(
        self,
        company_username: str,
        statements: list[dict[str, Any]],
        verification_sql: str,
        expected_affected_rows: int,
        expected_verification_value: int,
        idempotency_key: str,
        preview_hash: str,
        verification_parameters: list[Any] | None = None,
        source_company_usernames: list[str] | None = None,
    ) -> dict[str, Any]:
        """Back up every permanent target, execute one bounded transaction, and verify before and after commit."""

        self._require_write_enabled()
        plan = _validated_write_plan(
            company_username=company_username,
            statements=statements,
            verification_sql=verification_sql,
            verification_parameters=verification_parameters,
            expected_affected_rows=expected_affected_rows,
            expected_verification_value=expected_verification_value,
            idempotency_key=idempotency_key,
            source_company_usernames=source_company_usernames,
        )
        if not re.fullmatch(r"[0-9a-f]{64}", str(preview_hash or "").strip().lower()):
            raise NovaSqlScopeError("preview_hash must be the exact hash returned by nova_sql_write_preview")
        if str(preview_hash).strip().lower() != plan.plan_hash:
            raise NovaSqlScopeError("write plan differs from the approved preview")

        receipt_path = _receipt_path(self.write_state_dir, plan.idempotency_key)
        existing = _read_json_file(receipt_path)
        if existing:
            return _idempotent_receipt_result(existing, plan)

        committed = False
        backup_rows: list[dict[str, Any]] = []
        affected_rows = 0
        source_rows_before: list[dict[str, Any]] = []
        source_rows_after: list[dict[str, Any]] = []
        with closing(self._connect_write_plan(plan)) as connection:
            connection.timeout = (
                max(self.settings.query_timeout_seconds, 3_600)
                if plan.source_company_usernames
                else self.settings.query_timeout_seconds
            )
            cursor = connection.cursor()
            try:
                cursor.execute("SET XACT_ABORT ON")
                _verify_database_binding(cursor, plan.company_username)
                source_rows_before = _preview_source_databases(cursor, plan)
                _acquire_write_lock(cursor, plan.company_username, plan.idempotency_key)

                existing = _read_json_file(receipt_path)
                if existing:
                    try:
                        connection.rollback()
                    except Exception:
                        pass
                    return _idempotent_receipt_result(existing, plan)

                targets = _preview_target_tables(cursor, plan)
                for target in targets:
                    backup_table = _backup_table_identifier(target["table"], plan.plan_hash)
                    if _table_exists(cursor, backup_table):
                        raise NovaSqlScopeError(
                            "a deterministic backup already exists without a completed receipt; do not retry this write"
                        )
                    source_sql = _quoted_table(target["table"])
                    backup_sql = _quoted_table(backup_table)
                    cursor.execute(f"SELECT * INTO {backup_sql} FROM {source_sql} WITH (HOLDLOCK, TABLOCKX)")
                    source_count = int(cursor.execute(f"SELECT COUNT_BIG(*) FROM {source_sql}").fetchone()[0] or 0)
                    backup_count = int(cursor.execute(f"SELECT COUNT_BIG(*) FROM {backup_sql}").fetchone()[0] or 0)
                    if source_count != backup_count:
                        raise NovaSqlScopeError("automatic table backup row-count verification failed")
                    backup_rows.append(
                        {"sourceTable": target["table"], "backupTable": backup_table, "rowCount": backup_count}
                    )

                for statement in plan.statements:
                    statement_row_count = -1
                    if statement.identity_insert:
                        target_sql = _quoted_table(statement.target_table)
                        cursor.execute(f"SET IDENTITY_INSERT {target_sql} ON")
                        try:
                            cursor.execute(statement.sql, statement.parameters)
                            statement_row_count = int(
                                getattr(cursor, "rowcount", -1)
                            )
                        finally:
                            try:
                                cursor.execute(
                                    f"SET IDENTITY_INSERT {target_sql} OFF"
                                )
                            except Exception:
                                pass
                    else:
                        cursor.execute(statement.sql, statement.parameters)
                        statement_row_count = int(
                            getattr(cursor, "rowcount", -1)
                        )
                    if statement.persistent:
                        row_count = statement_row_count
                        if row_count < 0:
                            raise NovaSqlScopeError("permanent write did not return a bounded affected-row count")
                        affected_rows += row_count
                        if affected_rows > plan.maximum_affected_rows:
                            raise NovaSqlScopeError("write exceeded the hard affected-row ceiling")

                if affected_rows != plan.expected_affected_rows:
                    raise NovaSqlScopeError("affected-row count did not match the approved preview")
                verification_value = _verification_scalar(cursor, plan)
                if verification_value != plan.expected_verification_value:
                    raise NovaSqlScopeError("pre-commit verification did not match the approved value")

                connection.commit()
                committed = True
                source_rows_after = _preview_source_databases(cursor, plan)
                post_commit_value = _verification_scalar(cursor, plan)
                if post_commit_value != plan.expected_verification_value:
                    receipt = _write_receipt(
                        receipt_path,
                        plan,
                        status="committed_readback_failed",
                        affected_rows=affected_rows,
                        verification_value=post_commit_value,
                        backups=backup_rows,
                        source_rows_before=source_rows_before,
                        source_rows_after=source_rows_after,
                    )
                    raise NovaSqlUnavailableError(
                        "Nova SQL write committed but post-commit readback failed; do not retry this idempotency key"
                    )

                receipt = _write_receipt(
                    receipt_path,
                    plan,
                    status="completed",
                    affected_rows=affected_rows,
                    verification_value=post_commit_value,
                    backups=backup_rows,
                    source_rows_before=source_rows_before,
                    source_rows_after=source_rows_after,
                )
            except (NovaSqlScopeError, NovaSqlUnavailableError):
                if not committed:
                    try:
                        connection.rollback()
                    except Exception:
                        pass
                raise
            except Exception as exc:
                if not committed:
                    try:
                        connection.rollback()
                    except Exception:
                        pass
                    raise NovaSqlUnavailableError("guarded Nova SQL write failed and was rolled back") from exc
                _write_receipt(
                    receipt_path,
                    plan,
                    status="committed_readback_failed",
                    affected_rows=affected_rows,
                    verification_value=-1,
                    backups=backup_rows,
                    source_rows_before=source_rows_before,
                    source_rows_after=source_rows_after,
                )
                raise NovaSqlUnavailableError(
                    "Nova SQL write committed but final receipt/readback failed; do not retry this idempotency key"
                ) from exc

        return {
            "ok": True,
            "status": "completed",
            "accessMode": "guarded_write",
            "companyUsername": plan.company_username,
            "databaseName": f"POS_{plan.company_username}",
            "sourceCompanyUsernames": list(plan.source_company_usernames),
            "sourceDatabasesReadOnly": bool(plan.source_company_usernames),
            "executionMode": (
                "cross_account_set_based_sql"
                if plan.source_company_usernames
                else "single_account_guarded_sql"
            ),
            "planHash": plan.plan_hash,
            "idempotencyKey": plan.idempotency_key,
            "affectedRows": affected_rows,
            "verificationValue": receipt["verificationValue"],
            "backupTables": receipt["backups"],
            "sourceRowsBefore": receipt.get("sourceRowsBefore", []),
            "sourceRowsAfter": receipt.get("sourceRowsAfter", []),
            "sourceRowCountsStableDuringExecution": (
                receipt.get("sourceRowsBefore", [])
                == receipt.get("sourceRowsAfter", [])
            ),
            "transactionCommitted": True,
            "postCommitReadbackVerified": True,
            "idempotentReplay": False,
        }

    def preview_locations_feature_columns_migration(
        self,
        company_username: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        """Preview the one approved dbo.Locations feature-column migration without changing schema or data."""

        self._require_write_enabled()
        clean_username = _company_username(company_username)
        clean_key = _idempotency_key(idempotency_key)
        with closing(self._connect(clean_username, read_only=False)) as connection:
            connection.timeout = self.settings.query_timeout_seconds
            cursor = connection.cursor()
            _verify_database_binding(cursor, clean_username)
            state = _locations_feature_migration_state(cursor, clean_username, clean_key)
            try:
                connection.rollback()
            except Exception:
                pass
        return {
            "ok": True,
            "status": "preview",
            "accessMode": "fixed_schema_migration_preview",
            "operation": LOCATIONS_FEATURE_MIGRATION,
            "companyUsername": clean_username,
            "databaseName": f"POS_{clean_username}",
            "table": LOCATIONS_FEATURE_TABLE,
            "planHash": state["planHash"],
            "idempotencyKey": clean_key,
            "missingColumns": state["missingColumns"],
            "verifiedExistingColumns": state["existingColumns"],
            "expectedColumns": _public_locations_feature_columns(),
            "sourceRowCount": state["rowCount"],
            "backupRequired": bool(state["missingColumns"]),
            "backupTable": state["backupTable"] if state["missingColumns"] else "",
            "backupStrategy": "full in-database dbo.Locations copy with row-count verification before ALTER",
            "arbitrarySqlAccepted": False,
            "forbiddenOperations": ["DELETE", "DROP", "TRUNCATE", "arbitrary ALTER", "MERGE", "dynamic SQL"],
        }

    def execute_locations_feature_columns_migration(
        self,
        company_username: str,
        idempotency_key: str,
        preview_hash: str,
    ) -> dict[str, Any]:
        """Back up dbo.Locations and add only the five approved nullable columns that are missing."""

        self._require_write_enabled()
        clean_username = _company_username(company_username)
        clean_key = _idempotency_key(idempotency_key)
        clean_hash = str(preview_hash or "").strip().lower()
        if not re.fullmatch(r"[0-9a-f]{64}", clean_hash):
            raise NovaSqlScopeError(
                "preview_hash must be the exact hash returned by nova_sql_locations_feature_columns_preview"
            )

        receipt_path = _locations_feature_receipt_path(self.write_state_dir, clean_key)
        existing_receipt = _read_json_file(receipt_path)
        if existing_receipt:
            return _locations_feature_receipt_result(
                existing_receipt,
                company_username=clean_username,
                idempotency_key=clean_key,
                preview_hash=clean_hash,
                replay=True,
            )

        committed = False
        backup_rows: list[dict[str, Any]] = []
        columns_added: list[str] = []
        final_columns: list[dict[str, Any]] = []
        with closing(self._connect(clean_username, read_only=False)) as connection:
            connection.timeout = self.settings.query_timeout_seconds
            cursor = connection.cursor()
            try:
                cursor.execute("SET XACT_ABORT ON")
                _verify_database_binding(cursor, clean_username)
                _acquire_write_lock(cursor, clean_username, clean_key)

                existing_receipt = _read_json_file(receipt_path)
                if existing_receipt:
                    try:
                        connection.rollback()
                    except Exception:
                        pass
                    return _locations_feature_receipt_result(
                        existing_receipt,
                        company_username=clean_username,
                        idempotency_key=clean_key,
                        preview_hash=clean_hash,
                        replay=True,
                    )

                cursor.execute("SELECT COUNT_BIG(*) FROM [dbo].[Locations] WITH (TABLOCKX, HOLDLOCK)").fetchone()
                state = _locations_feature_migration_state(cursor, clean_username, clean_key)
                if state["planHash"] != clean_hash:
                    raise NovaSqlScopeError("Locations schema changed after preview; run a new preview")

                columns_added = list(state["missingColumns"])
                if not columns_added:
                    try:
                        connection.rollback()
                    except Exception:
                        pass
                    receipt = _write_locations_feature_receipt(
                        receipt_path,
                        company_username=clean_username,
                        idempotency_key=clean_key,
                        plan_hash=clean_hash,
                        status="completed",
                        columns_added=[],
                        columns=state["columns"],
                        backups=[],
                        transaction_committed=False,
                        no_op=True,
                    )
                    return _locations_feature_receipt_result(
                        receipt,
                        company_username=clean_username,
                        idempotency_key=clean_key,
                        preview_hash=clean_hash,
                        replay=False,
                    )

                backup_table = str(state["backupTable"])
                if _table_exists(cursor, backup_table):
                    raise NovaSqlScopeError(
                        "the deterministic Locations backup already exists without a completed receipt; do not retry"
                    )
                source_sql = _quoted_table(LOCATIONS_FEATURE_TABLE)
                backup_sql = _quoted_table(backup_table)
                cursor.execute(f"SELECT * INTO {backup_sql} FROM {source_sql} WITH (HOLDLOCK, TABLOCKX)")
                source_count = int(cursor.execute(f"SELECT COUNT_BIG(*) FROM {source_sql}").fetchone()[0] or 0)
                backup_count = int(cursor.execute(f"SELECT COUNT_BIG(*) FROM {backup_sql}").fetchone()[0] or 0)
                if source_count != backup_count:
                    raise NovaSqlScopeError("automatic dbo.Locations backup row-count verification failed")
                backup_rows.append(
                    {
                        "sourceTable": LOCATIONS_FEATURE_TABLE,
                        "backupTable": backup_table,
                        "rowCount": backup_count,
                    }
                )

                specs = {str(spec["name"]): spec for spec in LOCATIONS_FEATURE_COLUMNS}
                for column_name in columns_added:
                    spec = specs[column_name]
                    cursor.execute(f"ALTER TABLE [dbo].[Locations] ADD {spec['ddl']}")

                verified = _locations_feature_migration_state(cursor, clean_username, clean_key)
                if verified["missingColumns"]:
                    raise NovaSqlScopeError("pre-commit Locations column verification failed")
                final_columns = list(verified["columns"])

                connection.commit()
                committed = True
                post_commit = _locations_feature_migration_state(cursor, clean_username, clean_key)
                if post_commit["missingColumns"]:
                    _write_locations_feature_receipt(
                        receipt_path,
                        company_username=clean_username,
                        idempotency_key=clean_key,
                        plan_hash=clean_hash,
                        status="committed_readback_failed",
                        columns_added=columns_added,
                        columns=post_commit["columns"],
                        backups=backup_rows,
                        transaction_committed=True,
                        no_op=False,
                    )
                    raise NovaSqlUnavailableError(
                        "Locations migration committed but post-commit readback failed; do not retry this idempotency key"
                    )
                final_columns = list(post_commit["columns"])
                receipt = _write_locations_feature_receipt(
                    receipt_path,
                    company_username=clean_username,
                    idempotency_key=clean_key,
                    plan_hash=clean_hash,
                    status="completed",
                    columns_added=columns_added,
                    columns=final_columns,
                    backups=backup_rows,
                    transaction_committed=True,
                    no_op=False,
                )
            except (NovaSqlScopeError, NovaSqlUnavailableError) as exc:
                if not committed:
                    try:
                        connection.rollback()
                    except Exception:
                        pass
                    raise
                try:
                    _write_locations_feature_receipt(
                        receipt_path,
                        company_username=clean_username,
                        idempotency_key=clean_key,
                        plan_hash=clean_hash,
                        status="committed_readback_failed",
                        columns_added=columns_added,
                        columns=final_columns,
                        backups=backup_rows,
                        transaction_committed=True,
                        no_op=False,
                    )
                except Exception:
                    pass
                raise NovaSqlUnavailableError(
                    "Locations migration committed without final verified readback; do not retry this idempotency key"
                ) from exc
            except Exception as exc:
                if not committed:
                    try:
                        connection.rollback()
                    except Exception:
                        pass
                    raise NovaSqlUnavailableError("Locations migration failed and was rolled back") from exc
                try:
                    _write_locations_feature_receipt(
                        receipt_path,
                        company_username=clean_username,
                        idempotency_key=clean_key,
                        plan_hash=clean_hash,
                        status="committed_readback_failed",
                        columns_added=columns_added,
                        columns=final_columns,
                        backups=backup_rows,
                        transaction_committed=True,
                        no_op=False,
                    )
                except Exception:
                    pass
                raise NovaSqlUnavailableError(
                    "Locations migration committed without a final receipt; do not retry this idempotency key"
                ) from exc

        return _locations_feature_receipt_result(
            receipt,
            company_username=clean_username,
            idempotency_key=clean_key,
            preview_hash=clean_hash,
            replay=False,
        )

    def preview_kit_upgrade(
        self,
        company_username: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        """Preview the fixed-contract dbo.Kit upgrade for one exact company database."""

        self._require_write_enabled()
        clean_username = _company_username(company_username)
        clean_key = _idempotency_key(idempotency_key)
        with closing(self._connect(clean_username, read_only=False)) as connection:
            connection.timeout = self.settings.query_timeout_seconds
            cursor = connection.cursor()
            _verify_database_binding(cursor, clean_username)
            state = _kit_upgrade_state(cursor, clean_username, clean_key)
            try:
                connection.rollback()
            except Exception:
                pass
        return {
            "ok": True,
            "status": "preview",
            "accessMode": "fixed_schema_migration_preview",
            "operation": KIT_UPGRADE_MIGRATION,
            "companyUsername": clean_username,
            "databaseName": f"POS_{clean_username}",
            "table": KIT_UPGRADE_TABLE,
            "planHash": state["planHash"],
            "idempotencyKey": clean_key,
            "missingColumns": state["missingColumns"],
            "verifiedExistingColumns": state["existingColumns"],
            "expectedColumns": _public_kit_upgrade_columns(),
            "sourceRowCount": state["rowCount"],
            "sourceDataChecksum": state["dataChecksum"],
            "backupRequired": bool(state["missingColumns"]),
            "backupTable": state["backupTable"] if state["missingColumns"] else "",
            "backupStrategy": "full in-database dbo.Kit copy plus exact preserved-column comparison before commit",
            "arbitrarySqlAccepted": False,
            "fixedSchemaContract": True,
            "forbiddenOperations": ["DELETE", "DROP", "TRUNCATE", "arbitrary ALTER", "MERGE", "dynamic SQL"],
        }

    def execute_kit_upgrade(
        self,
        company_username: str,
        idempotency_key: str,
        preview_hash: str,
    ) -> dict[str, Any]:
        """Back up one exact company dbo.Kit and add only the approved nullable columns."""

        self._require_write_enabled()
        clean_username = _company_username(company_username)
        clean_key = _idempotency_key(idempotency_key)
        clean_hash = str(preview_hash or "").strip().lower()
        if not re.fullmatch(r"[0-9a-f]{64}", clean_hash):
            raise NovaSqlScopeError(
                "preview_hash must be the exact hash returned by "
                "nova_sql_kit_upgrade_preview"
            )

        receipt_path = _kit_upgrade_receipt_path(self.write_state_dir, clean_key)
        existing_receipt = _read_json_file(receipt_path)
        if existing_receipt:
            return _kit_upgrade_receipt_result(
                existing_receipt,
                company_username=clean_username,
                idempotency_key=clean_key,
                preview_hash=clean_hash,
                replay=True,
            )

        committed = False
        backup_rows: list[dict[str, Any]] = []
        columns_added: list[str] = []
        final_columns: list[dict[str, Any]] = []
        source_data_fingerprint: dict[str, int] = {}
        with closing(self._connect(clean_username, read_only=False)) as connection:
            connection.timeout = self.settings.query_timeout_seconds
            cursor = connection.cursor()
            try:
                cursor.execute("SET XACT_ABORT ON")
                _verify_database_binding(cursor, clean_username)
                _acquire_write_lock(cursor, clean_username, clean_key)

                existing_receipt = _read_json_file(receipt_path)
                if existing_receipt:
                    try:
                        connection.rollback()
                    except Exception:
                        pass
                    return _kit_upgrade_receipt_result(
                        existing_receipt,
                        company_username=clean_username,
                        idempotency_key=clean_key,
                        preview_hash=clean_hash,
                        replay=True,
                    )

                cursor.execute(
                    "SELECT COUNT_BIG(*) FROM [dbo].[Kit] WITH (TABLOCKX, HOLDLOCK)"
                ).fetchone()
                state = _kit_upgrade_state(cursor, clean_username, clean_key)
                if state["planHash"] != clean_hash:
                    raise NovaSqlScopeError("Kit schema or data changed after preview; run a new preview")

                columns_added = list(state["missingColumns"])
                source_data_fingerprint = {
                    "rowCount": int(state["rowCount"]),
                    "checksum": int(state["dataChecksum"]),
                }
                if not columns_added:
                    try:
                        connection.rollback()
                    except Exception:
                        pass
                    receipt = _write_kit_upgrade_receipt(
                        receipt_path,
                        company_username=clean_username,
                        idempotency_key=clean_key,
                        plan_hash=clean_hash,
                        status="completed",
                        columns_added=[],
                        columns=state["columns"],
                        backups=[],
                        source_data_fingerprint=source_data_fingerprint,
                        verified_data_fingerprint=source_data_fingerprint,
                        transaction_committed=False,
                        no_op=True,
                    )
                    return _kit_upgrade_receipt_result(
                        receipt,
                        company_username=clean_username,
                        idempotency_key=clean_key,
                        preview_hash=clean_hash,
                        replay=False,
                    )

                backup_table = str(state["backupTable"])
                if _table_exists(cursor, backup_table):
                    raise NovaSqlScopeError(
                        "the deterministic Kit backup already exists without a completed receipt; do not retry"
                    )
                source_sql = _quoted_table(KIT_UPGRADE_TABLE)
                backup_sql = _quoted_table(backup_table)
                cursor.execute(f"SELECT * INTO {backup_sql} FROM {source_sql} WITH (HOLDLOCK, TABLOCKX)")
                source_count = int(cursor.execute(f"SELECT COUNT_BIG(*) FROM {source_sql}").fetchone()[0] or 0)
                backup_count = int(cursor.execute(f"SELECT COUNT_BIG(*) FROM {backup_sql}").fetchone()[0] or 0)
                if source_count != backup_count:
                    raise NovaSqlScopeError("automatic dbo.Kit backup row-count verification failed")
                backup_rows.append(
                    {
                        "sourceTable": KIT_UPGRADE_TABLE,
                        "backupTable": backup_table,
                        "rowCount": backup_count,
                    }
                )

                specs = {str(spec["name"]): spec for spec in KIT_UPGRADE_COLUMNS}
                for column_name in columns_added:
                    cursor.execute(f"ALTER TABLE [dbo].[Kit] ADD {specs[column_name]['ddl']}")

                verified = _kit_upgrade_state(cursor, clean_username, clean_key)
                if verified["missingColumns"]:
                    raise NovaSqlScopeError("pre-commit Kit column verification failed")
                verified_data_fingerprint = {
                    "rowCount": int(verified["rowCount"]),
                    "checksum": int(verified["dataChecksum"]),
                }
                if verified_data_fingerprint != source_data_fingerprint:
                    raise NovaSqlScopeError("pre-commit Kit data-preservation check failed")
                if not _kit_upgrade_backup_matches(cursor, backup_table):
                    raise NovaSqlScopeError("pre-commit Kit exact backup comparison failed")
                if _kit_upgrade_non_null_count(cursor, columns_added):
                    raise NovaSqlScopeError("new Kit columns were not initialized to NULL")
                final_columns = list(verified["columns"])

                connection.commit()
                committed = True
                post_commit = _kit_upgrade_state(cursor, clean_username, clean_key)
                post_commit_fingerprint = {
                    "rowCount": int(post_commit["rowCount"]),
                    "checksum": int(post_commit["dataChecksum"]),
                }
                readback_ok = (
                    not post_commit["missingColumns"]
                    and post_commit_fingerprint == source_data_fingerprint
                    and _kit_upgrade_backup_matches(cursor, backup_table)
                    and _kit_upgrade_non_null_count(cursor, columns_added) == 0
                )
                if not readback_ok:
                    _write_kit_upgrade_receipt(
                        receipt_path,
                        company_username=clean_username,
                        idempotency_key=clean_key,
                        plan_hash=clean_hash,
                        status="committed_readback_failed",
                        columns_added=columns_added,
                        columns=post_commit["columns"],
                        backups=backup_rows,
                        source_data_fingerprint=source_data_fingerprint,
                        verified_data_fingerprint=post_commit_fingerprint,
                        transaction_committed=True,
                        no_op=False,
                    )
                    raise NovaSqlUnavailableError(
                        "Kit upgrade committed but post-commit readback failed; do not retry this idempotency key"
                    )
                final_columns = list(post_commit["columns"])
                receipt = _write_kit_upgrade_receipt(
                    receipt_path,
                    company_username=clean_username,
                    idempotency_key=clean_key,
                    plan_hash=clean_hash,
                    status="completed",
                    columns_added=columns_added,
                    columns=final_columns,
                    backups=backup_rows,
                    source_data_fingerprint=source_data_fingerprint,
                    verified_data_fingerprint=post_commit_fingerprint,
                    transaction_committed=True,
                    no_op=False,
                )
            except (NovaSqlScopeError, NovaSqlUnavailableError) as exc:
                if not committed:
                    try:
                        connection.rollback()
                    except Exception:
                        pass
                    raise
                try:
                    _write_kit_upgrade_receipt(
                        receipt_path,
                        company_username=clean_username,
                        idempotency_key=clean_key,
                        plan_hash=clean_hash,
                        status="committed_readback_failed",
                        columns_added=columns_added,
                        columns=final_columns,
                        backups=backup_rows,
                        source_data_fingerprint=source_data_fingerprint,
                        verified_data_fingerprint={},
                        transaction_committed=True,
                        no_op=False,
                    )
                except Exception:
                    pass
                raise NovaSqlUnavailableError(
                    "Kit upgrade committed without final verified readback; do not retry this idempotency key"
                ) from exc
            except Exception as exc:
                if not committed:
                    try:
                        connection.rollback()
                    except Exception:
                        pass
                    raise NovaSqlUnavailableError("Kit upgrade failed and was rolled back") from exc
                try:
                    _write_kit_upgrade_receipt(
                        receipt_path,
                        company_username=clean_username,
                        idempotency_key=clean_key,
                        plan_hash=clean_hash,
                        status="committed_readback_failed",
                        columns_added=columns_added,
                        columns=final_columns,
                        backups=backup_rows,
                        source_data_fingerprint=source_data_fingerprint,
                        verified_data_fingerprint={},
                        transaction_committed=True,
                        no_op=False,
                    )
                except Exception:
                    pass
                raise NovaSqlUnavailableError(
                    "Kit upgrade committed without a final receipt; do not retry this idempotency key"
                ) from exc

        return _kit_upgrade_receipt_result(
            receipt,
            company_username=clean_username,
            idempotency_key=clean_key,
            preview_hash=clean_hash,
            replay=False,
        )

    def preview_instyle_demo_rebuild(self, *, idempotency_key: str) -> dict[str, Any]:
        """Preview the fixed Instyle rebuild from two exact sources into the demo-only target."""

        self._require_write_enabled()
        return self._instyle_demo_rebuild.preview(idempotency_key=idempotency_key)

    def execute_instyle_demo_rebuild(
        self,
        *,
        idempotency_key: str,
        preview_hash: str,
    ) -> dict[str, Any]:
        """Execute only the immutable fixed Instyle rebuild plan through the protected restore boundary."""

        self._require_write_enabled()
        return self._instyle_demo_rebuild.execute(
            idempotency_key=idempotency_key,
            preview_hash=preview_hash,
        )

    def recover_instyle_demo_rebuild(
        self,
        *,
        idempotency_key: str,
        preview_hash: str,
    ) -> dict[str, Any]:
        """Restore the fixed demo target after an abandoned post-reset execute."""

        self._require_write_enabled()
        return self._instyle_demo_rebuild.recover(
            idempotency_key=idempotency_key,
            preview_hash=preview_hash,
        )

    def preview_instyle_demo_sync(self, *, idempotency_key: str) -> dict[str, Any]:
        """Preview the fixed database-side set-based Instyle sync."""

        self._require_write_enabled()
        return self._instyle_demo_sync.preview(idempotency_key=idempotency_key)

    def status_instyle_demo_sync(self, *, idempotency_key: str) -> dict[str, Any]:
        """Reconcile one preview/execute pair through read-only connections."""

        self._require_write_enabled()
        return self._instyle_demo_sync.status(idempotency_key=idempotency_key)

    def execute_instyle_demo_sync(
        self,
        *,
        idempotency_key: str,
        preview_hash: str,
    ) -> dict[str, Any]:
        """Run the fixed incremental sync while both source accounts stay read-only."""

        self._require_write_enabled()
        try:
            return self._instyle_demo_sync.execute(
                idempotency_key=idempotency_key,
                preview_hash=preview_hash,
            )
        except Exception as exc:
            return execution_failure_result(
                idempotency_key=idempotency_key,
                preview_hash=preview_hash,
                error=exc,
            )

    def preview_instyle_runway_merge(self, *, idempotency_key: str) -> dict[str, Any]:
        """Preview the fixed two-source production merge into INSTYLE_RUNWAY."""

        self._require_write_enabled()
        return self._instyle_runway_merge.preview(idempotency_key=idempotency_key)

    def status_instyle_runway_merge(self, *, idempotency_key: str) -> dict[str, Any]:
        """Reconcile the fixed production merge through read-only connections."""

        self._require_write_enabled()
        return self._instyle_runway_merge.status(idempotency_key=idempotency_key)

    def execute_instyle_runway_merge(
        self,
        *,
        idempotency_key: str,
        preview_hash: str,
    ) -> dict[str, Any]:
        """Execute only the immutable reviewed Instyle Runway merge plan."""

        self._require_write_enabled()
        try:
            return self._instyle_runway_merge.execute(
                idempotency_key=idempotency_key,
                preview_hash=preview_hash,
            )
        except Exception as exc:
            return instyle_runway_execution_failure_result(
                idempotency_key=idempotency_key,
                preview_hash=preview_hash,
                error=exc,
            )

    def preview_oklahoma_hawaii_catalog_replace(
        self,
        *,
        idempotency_key: str,
    ) -> dict[str, Any]:
        """Preview the fixed Oklahoma replacement from Unique Lifestyle HAWAII."""

        self._require_write_enabled()
        return self._oklahoma_hawaii_catalog_replace.preview(
            idempotency_key=idempotency_key,
        )

    def status_oklahoma_hawaii_catalog_replace(
        self,
        *,
        idempotency_key: str,
    ) -> dict[str, Any]:
        """Reconcile the fixed replacement after an uncertain execute."""

        self._require_write_enabled()
        return self._oklahoma_hawaii_catalog_replace.status(
            idempotency_key=idempotency_key,
        )

    def execute_oklahoma_hawaii_catalog_replace(
        self,
        *,
        idempotency_key: str,
        preview_hash: str,
    ) -> dict[str, Any]:
        """Execute only the exact fixed atomic delete-and-copy contract."""

        self._require_write_enabled()
        return self._oklahoma_hawaii_catalog_replace.execute(
            idempotency_key=idempotency_key,
            preview_hash=preview_hash,
        )

    def preview_table_restore(
        self,
        *,
        company_username: str,
        schema_name: str,
        table_name: str,
        key_columns: list[str],
        restore_columns: list[str],
        idempotency_key: str,
    ) -> dict[str, Any]:
        """Preview a column-scoped restore from POS_<company>_RESTORE."""

        self._require_write_enabled()
        return self._table_restore.preview(
            company_username=company_username,
            schema_name=schema_name,
            table_name=table_name,
            key_columns=key_columns,
            restore_columns=restore_columns,
            idempotency_key=idempotency_key,
        )

    def execute_table_restore(
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
        """Execute only the exact previewed table-column restore."""

        self._require_write_enabled()
        return self._table_restore.execute(
            company_username=company_username,
            schema_name=schema_name,
            table_name=table_name,
            key_columns=key_columns,
            restore_columns=restore_columns,
            idempotency_key=idempotency_key,
            preview_hash=preview_hash,
        )

    def preview_account_copy(
        self,
        *,
        source_company_username: str,
        target_company_username: str,
        tables: list[dict[str, Any]],
        idempotency_key: str,
        ticket_number: str = "",
    ) -> dict[str, Any]:
        """Preview a reusable schema-aware account copy without accepting SQL."""

        self._require_write_enabled()
        return self._account_copy.preview(
            source_company_username=source_company_username,
            target_company_username=target_company_username,
            tables=tables,
            idempotency_key=idempotency_key,
            ticket_number=ticket_number,
        )

    def execute_account_copy(self, *, plan_id: str) -> dict[str, Any]:
        """Execute only one immutable server-owned account-copy plan."""

        self._require_write_enabled()
        return self._account_copy.execute(plan_id=plan_id)

    def account_copy_status(self, *, plan_id: str) -> dict[str, Any]:
        """Read the durable state of one account-copy plan."""

        self._require_write_enabled()
        return self._account_copy.status(plan_id=plan_id)

    def preview_ticket_347534_invoice_repair(
        self,
        *,
        idempotency_key: str,
    ) -> dict[str, Any]:
        """Preview the fixed wrong-location invoice graph repair for ticket 347534."""

        self._require_write_enabled()
        return self._ticket_347534_invoice_repair.preview(
            idempotency_key=idempotency_key,
        )

    def status_ticket_347534_invoice_repair(
        self,
        *,
        idempotency_key: str,
    ) -> dict[str, Any]:
        """Read durable state for the fixed ticket 347534 repair."""

        self._require_write_enabled()
        return self._ticket_347534_invoice_repair.status(
            idempotency_key=idempotency_key,
        )

    def execute_ticket_347534_invoice_repair(
        self,
        *,
        idempotency_key: str,
        preview_hash: str,
    ) -> dict[str, Any]:
        """Execute only the reviewed fixed ticket 347534 invoice repair."""

        self._require_write_enabled()
        return self._ticket_347534_invoice_repair.execute(
            idempotency_key=idempotency_key,
            preview_hash=preview_hash,
        )

    def _guarded_write_receipt_status(
        self,
        idempotency_key: str,
        plan_hash: str,
    ) -> dict[str, Any]:
        receipt = _read_json_file(_receipt_path(self.write_state_dir, idempotency_key))
        if receipt is None:
            return {"status": "not_found"}
        if (
            receipt.get("idempotencyKey") != idempotency_key
            or receipt.get("planHash") != plan_hash
        ):
            raise NovaSqlUnavailableError(
                "the account-copy idempotency key belongs to a different guarded plan"
            )
        status = str(receipt.get("status") or "unknown")
        if status != "completed":
            return {"status": status}
        return {
            "status": "completed",
            "affectedRows": int(receipt.get("affectedRows") or 0),
            "backupTables": list(receipt.get("backups") or []),
            "transactionCommitted": True,
            "postCommitReadbackVerified": True,
            "idempotentReplay": True,
        }

    def _require_write_enabled(self) -> None:
        if not self.write_enabled:
            raise NovaSqlScopeError("guarded Nova SQL writes are exposed only to coding_agent")

    def _connect(self, company_username: str, *, read_only: bool = True) -> Any:
        clean_username = _company_username(company_username)
        return self._connect_database(
            clean_username,
            f"POS_{clean_username}",
            read_only=read_only,
        )

    def _connect_database(
        self,
        company_username: str,
        database_name: str,
        *,
        read_only: bool = True,
    ) -> Any:
        clean_username = _company_username(company_username)
        clean_database = str(database_name or "").strip()
        allowed_databases = {
            f"POS_{clean_username}".casefold(),
            f"POS_{clean_username}_RESTORE".casefold(),
        }
        if clean_database.casefold() not in allowed_databases:
            raise NovaSqlScopeError(
                "Nova SQL database binding is limited to the exact live database "
                "or its fixed _RESTORE copy"
            )
        try:
            account = self.salesforce_client._resolve_nova_sql_account(clean_username)
            password = _decrypt_nova_password(str(account["password"]))
            driver = self._driver()
            connection_string = (
                f"DRIVER={{{driver}}};"
                f"SERVER={self.settings.server};"
                f"DATABASE={clean_database};"
                f"UID={clean_username};"
                f"PWD={password};"
                "Encrypt=yes;"
                "TrustServerCertificate=yes;"
                f"ApplicationIntent={'ReadOnly' if read_only else 'ReadWrite'};"
                f"Connection Timeout={self.settings.connection_timeout_seconds};"
            )
            if self._connect_factory is not None:
                connection = self._connect_factory(connection_string)
                if hasattr(connection, "autocommit"):
                    connection.autocommit = bool(read_only)
                return connection
            import pyodbc  # type: ignore[import-not-found]

            return pyodbc.connect(connection_string, autocommit=bool(read_only))
        except (NovaSqlScopeError, NovaSqlUnavailableError):
            raise
        except Exception as exc:
            mode = "read" if read_only else "guarded write"
            raise NovaSqlUnavailableError(f"Nova SQL {mode} connection failed") from exc

    def _connect_api_cohort(self) -> Any:
        credential_path = Path(self.settings.api_cohort_credential_file).expanduser()
        if not self.settings.api_cohort_credential_file or not credential_path.is_file():
            raise NovaSqlUnavailableError("API customer cohort credential is not configured")
        try:
            credentials = json.loads(credential_path.read_text(encoding="utf-8"))
            username = str(credentials.get("username") or "").strip()
            password = str(credentials.get("password") or "")
            if username != API_COHORT_SQL_USERNAME or not password:
                raise NovaSqlUnavailableError("API customer cohort credential is invalid")
            driver = self._driver()
            connection_string = (
                f"DRIVER={{{driver}}};"
                f"SERVER={self.settings.server};"
                f"DATABASE={API_COHORT_DATABASE};"
                f"UID={username};"
                f"PWD={password};"
                "Encrypt=yes;"
                "TrustServerCertificate=yes;"
                "ApplicationIntent=ReadOnly;"
                f"Connection Timeout={self.settings.connection_timeout_seconds};"
            )
            if self._connect_factory is not None:
                connection = self._connect_factory(connection_string)
                if hasattr(connection, "autocommit"):
                    connection.autocommit = True
                return connection
            import pyodbc  # type: ignore[import-not-found]

            return pyodbc.connect(connection_string, autocommit=True)
        except (NovaSqlScopeError, NovaSqlUnavailableError):
            raise
        except Exception as exc:
            raise NovaSqlUnavailableError("API customer cohort read-only connection failed") from exc

    def _connect_write_plan(self, plan: ValidatedWritePlan) -> Any:
        if plan.source_company_usernames:
            return self._connect_developer(
                read_only=False,
                company_username=plan.company_username,
            )
        return self._connect(plan.company_username, read_only=False)

    def _connect_developer(
        self,
        *,
        read_only: bool,
        company_username: str = "DEMO_NOVA_CAFE",
        autocommit: bool = False,
    ) -> Any:
        clean_username = _company_username(company_username)
        username_path = Path(self.settings.developer_username_file).expanduser()
        password_path = Path(self.settings.developer_password_file).expanduser()
        if (
            not self.settings.developer_username_file
            or not self.settings.developer_password_file
            or not username_path.is_file()
            or not password_path.is_file()
        ):
            raise NovaSqlUnavailableError(
                "the fixed developer SQL broker credential is not configured"
            )
        try:
            username = username_path.read_text(encoding="utf-8").strip()
            password = password_path.read_text(encoding="utf-8").rstrip("\r\n")
            if not username or not password:
                raise NovaSqlUnavailableError(
                    "the fixed developer SQL broker credential is invalid"
                )
            driver = self._driver()
            connection_string = (
                f"DRIVER={{{driver}}};"
                f"SERVER={self.settings.server};"
                f"DATABASE=POS_{clean_username};"
                f"UID={username};"
                f"PWD={password};"
                "Encrypt=yes;"
                "TrustServerCertificate=yes;"
                f"ApplicationIntent={'ReadOnly' if read_only else 'ReadWrite'};"
                f"Connection Timeout={self.settings.connection_timeout_seconds};"
            )
            if self._connect_factory is not None:
                connection = self._connect_factory(connection_string)
                if hasattr(connection, "autocommit"):
                    connection.autocommit = autocommit
                return connection
            import pyodbc  # type: ignore[import-not-found]

            return pyodbc.connect(connection_string, autocommit=autocommit)
        except (NovaSqlScopeError, NovaSqlUnavailableError):
            raise
        except Exception as exc:
            raise NovaSqlUnavailableError(
                "the fixed developer SQL broker connection failed"
            ) from exc

    def _driver(self) -> str:
        if self.settings.driver:
            return self.settings.driver
        try:
            if self._drivers_factory is not None:
                drivers = self._drivers_factory()
            else:
                import pyodbc  # type: ignore[import-not-found]

                drivers = list(pyodbc.drivers())
        except Exception as exc:
            raise NovaSqlUnavailableError("Nova SQL ODBC support is not installed") from exc
        for preferred in PREFERRED_DRIVERS:
            if preferred in drivers:
                return preferred
        raise NovaSqlUnavailableError("A supported SQL Server ODBC driver is not installed")


def _company_username(value: str) -> str:
    clean = str(value or "").strip()
    if clean.lower().startswith("pos_"):
        clean = clean[4:]
    if not COMPANY_USERNAME.fullmatch(clean):
        raise NovaSqlScopeError("company_username must be an exact Nova company username")
    return clean


def _idempotency_key(value: str) -> str:
    clean = str(value or "").strip()
    if not IDEMPOTENCY_KEY.fullmatch(clean):
        raise NovaSqlScopeError("idempotency_key must be a stable 8-200 character operation identifier")
    return clean


def _validated_write_plan(
    *,
    company_username: str,
    statements: list[dict[str, Any]],
    verification_sql: str,
    verification_parameters: list[Any] | None,
    expected_affected_rows: int,
    expected_verification_value: int,
    idempotency_key: str,
    source_company_usernames: list[str] | None = None,
) -> ValidatedWritePlan:
    clean_username = _company_username(company_username)
    clean_sources = _source_company_usernames(
        source_company_usernames,
        target_company_username=clean_username,
    )
    statement_limit = (
        MAX_DATA_MOVE_STATEMENTS if clean_sources else MAX_WRITE_STATEMENTS
    )
    affected_row_limit = MAX_DATA_MOVE_ROWS if clean_sources else MAX_WRITE_ROWS
    parameter_limit = (
        MAX_DATA_MOVE_PARAMETERS if clean_sources else MAX_WRITE_PARAMETERS
    )
    allowed_source_databases = tuple(f"POS_{value}" for value in clean_sources)
    if not isinstance(statements, list) or not 1 <= len(statements) <= statement_limit:
        raise NovaSqlScopeError(
            f"statements must contain between 1 and {statement_limit} entries"
        )

    clean_key = str(idempotency_key or "").strip()
    if not IDEMPOTENCY_KEY.fullmatch(clean_key):
        raise NovaSqlScopeError("idempotency_key must be a stable 8-200 character operation identifier")
    if isinstance(expected_affected_rows, bool) or not isinstance(expected_affected_rows, int):
        raise NovaSqlScopeError("expected_affected_rows must be an integer")
    if not 0 <= expected_affected_rows <= affected_row_limit:
        raise NovaSqlScopeError(
            "expected_affected_rows must be between 0 and "
            f"{affected_row_limit}"
        )
    if isinstance(expected_verification_value, bool) or not isinstance(expected_verification_value, int):
        raise NovaSqlScopeError("expected_verification_value must be an integer")

    validated: list[ValidatedWriteStatement] = []
    target_operations: dict[str, set[str]] = {}
    parameter_count = 0
    for entry in statements:
        if not isinstance(entry, dict) or set(entry) - {
            "sql",
            "parameters",
            "identity_insert",
        }:
            raise NovaSqlScopeError(
                "each statement must contain only sql, optional parameters, "
                "and optional identity_insert"
            )
        sql = _single_write_statement(
            entry.get("sql", ""),
            allowed_source_databases=allowed_source_databases,
        )
        parameters = _bounded_parameters(entry.get("parameters"))
        parameter_count += len(parameters)
        if parameter_count > parameter_limit:
            raise NovaSqlScopeError(
                f"a write plan may contain at most {parameter_limit} parameters"
            )
        kind, target, persistent = _classify_write_statement(sql)
        identity_insert = entry.get("identity_insert", False)
        if not isinstance(identity_insert, bool):
            raise NovaSqlScopeError("identity_insert must be true or false")
        if identity_insert and (kind != "insert" or not persistent):
            raise NovaSqlScopeError(
                "identity_insert is allowed only for an INSERT into one "
                "schema-qualified permanent target"
            )
        validated.append(
            ValidatedWriteStatement(
                sql=sql,
                parameters=parameters,
                kind=kind,
                target_table=target,
                persistent=persistent,
                identity_insert=identity_insert,
            )
        )
        if persistent:
            target_operations.setdefault(target, set()).add(kind)

    if not target_operations and expected_affected_rows:
        raise NovaSqlScopeError("expected_affected_rows must be zero when a plan changes only temporary tables")

    clean_verification_sql = _validated_select(
        verification_sql,
        allowed_source_databases=allowed_source_databases,
    )
    clean_verification_parameters = _bounded_parameters(verification_parameters)
    parameter_count += len(clean_verification_parameters)
    if parameter_count > parameter_limit:
        raise NovaSqlScopeError(
            f"a write plan may contain at most {parameter_limit} parameters"
        )

    immutable = {
        "companyUsername": clean_username,
        "sourceCompanyUsernames": list(clean_sources),
        "statements": [
            {
                "sql": statement.sql,
                "parameters": [_canonical_parameter(value) for value in statement.parameters],
                "identityInsert": statement.identity_insert,
            }
            for statement in validated
        ],
        "verificationSql": clean_verification_sql,
        "verificationParameters": [_canonical_parameter(value) for value in clean_verification_parameters],
        "expectedAffectedRows": expected_affected_rows,
        "expectedVerificationValue": expected_verification_value,
        "idempotencyKey": clean_key,
    }
    plan_hash = hashlib.sha256(
        json.dumps(immutable, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    ).hexdigest()
    return ValidatedWritePlan(
        company_username=clean_username,
        source_company_usernames=clean_sources,
        statements=validated,
        verification_sql=clean_verification_sql,
        verification_parameters=clean_verification_parameters,
        expected_affected_rows=expected_affected_rows,
        expected_verification_value=expected_verification_value,
        idempotency_key=clean_key,
        target_operations={
            table: tuple(sorted(operations)) for table, operations in sorted(target_operations.items())
        },
        identity_insert_targets=tuple(
            sorted(
                {
                    statement.target_table
                    for statement in validated
                    if statement.identity_insert
                }
            )
        ),
        maximum_affected_rows=affected_row_limit,
        plan_hash=plan_hash,
    )


def _source_company_usernames(
    values: list[str] | None,
    *,
    target_company_username: str,
) -> tuple[str, ...]:
    if values is None:
        return ()
    if not isinstance(values, list) or len(values) > MAX_DATA_MOVE_SOURCES:
        raise NovaSqlScopeError(
            "source_company_usernames must be a list of at most "
            f"{MAX_DATA_MOVE_SOURCES} exact Nova company usernames"
        )
    result: list[str] = []
    seen: set[str] = set()
    target_key = target_company_username.casefold()
    for value in values:
        clean = _company_username(value)
        key = clean.casefold()
        if key == target_key:
            raise NovaSqlScopeError(
                "a cross-account source must differ from the writable target"
            )
        if key not in seen:
            result.append(clean)
            seen.add(key)
    return tuple(result)


def _single_write_statement(
    value: Any,
    *,
    allowed_source_databases: tuple[str, ...] = (),
) -> str:
    sql = str(value or "").strip()
    if not sql or len(sql) > 20_000:
        raise NovaSqlScopeError("each write statement must be between 1 and 20000 characters")
    if "--" in sql or "/*" in sql or "*/" in sql:
        raise NovaSqlScopeError("SQL comments are not allowed")
    if sql.endswith(";"):
        sql = sql[:-1].rstrip()
    if ";" in sql:
        raise NovaSqlScopeError("exactly one SQL statement is allowed per entry")
    if WRITE_FORBIDDEN_SQL.search(sql):
        raise NovaSqlScopeError("SQL contains a destructive, administrative, dynamic, or external-access operation")
    _validate_cross_database_reads(sql, allowed_source_databases)
    return sql


def _classify_write_statement(sql: str) -> tuple[str, str, bool]:
    create_match = re.match(
        r"^CREATE\s+TABLE\s+(?P<target>#(?!#)[A-Za-z_][A-Za-z0-9_]{0,126})\s*\(",
        sql,
        re.IGNORECASE,
    )
    if create_match:
        _require_single_write_keyword(sql, "create")
        target = create_match.group("target")
        if not TEMP_TABLE.fullmatch(target):
            raise NovaSqlScopeError("CREATE TABLE is allowed only for a local temporary table")
        return "create_temp_table", target.casefold(), False

    if re.match(r"^SELECT\b", sql, re.IGNORECASE):
        into_matches = re.findall(
            r"\bINTO\s+(#(?!#)[A-Za-z_][A-Za-z0-9_]{0,126})\b",
            sql,
            re.IGNORECASE,
        )
        if len(into_matches) != 1 or WRITE_KEYWORD.search(sql):
            raise NovaSqlScopeError("SELECT writes are allowed only as SELECT INTO one local temporary table")
        return "select_into_temp", into_matches[0].casefold(), False

    insert_match = re.match(
        rf"^INSERT\s+INTO\s+(?P<target>#(?!#)[A-Za-z_][A-Za-z0-9_]{{0,126}}|{QUALIFIED_TABLE})\s*\(",
        sql,
        re.IGNORECASE,
    )
    if insert_match:
        _require_single_write_keyword(sql, "insert")
        target = insert_match.group("target")
        if target.startswith("#"):
            return "insert", target.casefold(), False
        return "insert", _normalize_qualified_table(target), True

    update_match = re.match(
        rf"^UPDATE\s+(?P<target>#(?!#)[A-Za-z_][A-Za-z0-9_]{{0,126}}|{QUALIFIED_TABLE}|{IDENTIFIER_PART})\s+SET\b",
        sql,
        re.IGNORECASE,
    )
    if update_match:
        _require_single_write_keyword(sql, "update")
        set_end = update_match.end()
        if not re.search(r"\bWHERE\b", sql[set_end:], re.IGNORECASE):
            raise NovaSqlScopeError("every UPDATE requires an explicit WHERE clause")
        target = update_match.group("target")
        if target.startswith("#"):
            return "update", target.casefold(), False
        if re.fullmatch(QUALIFIED_TABLE, target, re.IGNORECASE):
            return "update", _normalize_qualified_table(target), True
        return "update", _resolve_update_alias(sql, target), True

    raise NovaSqlScopeError(
        "only UPDATE with WHERE, INSERT with explicit columns, CREATE TABLE #temp, and SELECT INTO #temp are allowed"
    )


def _require_single_write_keyword(sql: str, expected: str) -> None:
    keywords = [match.group(0).casefold() for match in WRITE_KEYWORD.finditer(sql)]
    if keywords != [expected]:
        raise NovaSqlScopeError("each statement may contain exactly one approved write operation")


def _resolve_update_alias(sql: str, alias: str) -> str:
    clean_alias = _identifier_value(alias)
    reference = re.compile(
        rf"\b(?:FROM|JOIN)\s+(?P<source_schema>{IDENTIFIER_PART})\s*\.\s*"
        rf"(?P<source_table>{IDENTIFIER_PART})\s+(?:AS\s+)?(?P<alias>{IDENTIFIER_PART})(?=\s|$)",
        re.IGNORECASE,
    )
    matches = [
        f"{match.group('source_schema')}.{match.group('source_table')}"
        for match in reference.finditer(sql)
        if _identifier_value(match.group("alias")).casefold() == clean_alias.casefold()
    ]
    if len(matches) != 1:
        raise NovaSqlScopeError("an UPDATE alias must resolve to exactly one schema-qualified permanent table")
    return _normalize_qualified_table(matches[0])


def _identifier_value(value: str) -> str:
    clean = str(value or "").strip()
    if clean.startswith("[") and clean.endswith("]"):
        clean = clean[1:-1]
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_$#@]*", clean):
        raise NovaSqlScopeError("SQL identifier is outside the guarded identifier format")
    return clean


def _normalize_qualified_table(value: str) -> str:
    match = re.fullmatch(QUALIFIED_TABLE, str(value or "").strip(), re.IGNORECASE)
    if not match:
        raise NovaSqlScopeError("permanent write targets must be schema-qualified tables")
    return f"{_identifier_value(match.group('schema'))}.{_identifier_value(match.group('table'))}"


def _validate_cross_database_reads(
    sql: str,
    allowed_source_databases: tuple[str, ...],
) -> None:
    if ".." in sql:
        raise NovaSqlScopeError("linked-server and default-schema references are not allowed")
    references = list(THREE_PART_NAME.finditer(sql))
    if not references:
        if CROSS_DATABASE_NAME.search(sql):
            raise NovaSqlScopeError(
                "cross-database syntax must name an approved Nova source database"
            )
        return
    allowed = {value.casefold() for value in allowed_source_databases}
    for match in references:
        database = _identifier_value(match.group("database"))
        if database.casefold() == "dbo":
            # dbo.Table.Column is a common target-column qualifier, not a
            # cross-database reference.
            continue
        if database.casefold() not in allowed:
            raise NovaSqlScopeError(
                "cross-database reads are allowed only from the explicitly "
                "previewed Nova source accounts"
            )


def _quoted_table(value: str) -> str:
    clean = _normalize_qualified_table(value)
    schema, table = clean.split(".", 1)
    return f"[{schema}].[{table}]"


def _canonical_parameter(value: Any) -> Any:
    if isinstance(value, Decimal):
        return {"type": "decimal", "value": str(value)}
    if isinstance(value, datetime):
        return {"type": "datetime", "value": value.isoformat()}
    if isinstance(value, date):
        return {"type": "date", "value": value.isoformat()}
    if isinstance(value, float):
        if not math.isfinite(value):
            raise NovaSqlScopeError("SQL numeric parameters must be finite")
        return {"type": "float", "value": repr(value)}
    return value


def _verify_database_binding(cursor: Any, company_username: str) -> None:
    expected = f"POS_{company_username}"
    row = cursor.execute("SELECT DB_NAME()").fetchone()
    actual = str(row[0] or "") if row else ""
    if actual.casefold() != expected.casefold():
        raise NovaSqlUnavailableError("Nova SQL connected to an unexpected database")


def _positive_int(value: Any, field_name: str) -> int:
    try:
        clean = int(value)
    except (TypeError, ValueError) as exc:
        raise NovaSqlScopeError(f"{field_name} must be a positive integer") from exc
    if clean <= 0 or clean > 2_147_483_647:
        raise NovaSqlScopeError(f"{field_name} must be a positive integer")
    return clean


def _location_ids(values: Any) -> list[int]:
    if not isinstance(values, list) or not values:
        raise NovaSqlScopeError("location_ids must be a non-empty list of positive integers")
    if len(values) > LOCATION_LAYAWAY_MAX_LOCATIONS:
        raise NovaSqlScopeError(
            f"location_ids may contain at most {LOCATION_LAYAWAY_MAX_LOCATIONS} locations"
        )
    clean: list[int] = []
    for value in values:
        if isinstance(value, bool):
            raise NovaSqlScopeError("location_ids must contain only positive integers")
        clean.append(_positive_int(value, "location_ids item"))
    if len(set(clean)) != len(clean):
        raise NovaSqlScopeError("location_ids must not contain duplicates")
    return sorted(clean)


def _nullable_database_int(value: Any, field_name: str) -> int | None:
    if value is None:
        return None
    try:
        clean = int(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise NovaSqlScopeError(f"{field_name} did not read back as an integer") from exc
    if isinstance(value, (float, Decimal)) and value != clean:
        raise NovaSqlScopeError(f"{field_name} did not read back as an integer")
    return clean


def _nullable_database_number(value: Any, field_name: str) -> int | float | str | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        integral = int(value)
        return integral if value == integral else str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise NovaSqlScopeError(f"{field_name} did not read back as a finite number")
        return int(value) if value.is_integer() else value
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    try:
        parsed = Decimal(str(value))
    except Exception as exc:
        raise NovaSqlScopeError(f"{field_name} did not read back as a number") from exc
    integral = int(parsed)
    return integral if parsed == integral else str(parsed)


def _read_location_layaway_settings(
    cursor: Any,
    location_ids: list[int],
    *,
    lock_for_update: bool = False,
) -> list[dict[str, Any]]:
    lock = " WITH (UPDLOCK, HOLDLOCK)" if lock_for_update else ""
    placeholders = ",".join("?" for _ in location_ids)
    cursor.execute(
        "SELECT [LocationId],[ExpirationDay],[IsChangeLayawayExpirationDate],"
        f"[MinFirstPayment],[Disclaimer] FROM [dbo].[Locations_Layaways]{lock} "
        f"WHERE [LocationId] IN ({placeholders}) ORDER BY [LocationId]",
        location_ids,
    )
    rows = cursor.fetchall()
    by_location: dict[int, dict[str, Any]] = {}
    for raw in rows:
        location_id = int(raw[0])
        if location_id in by_location:
            raise NovaSqlScopeError(
                "dbo.Locations_Layaways contains duplicate rows for a requested location"
            )
        by_location[location_id] = {
            "locationId": location_id,
            "enabled": True,
            "expirationDay": _nullable_database_int(raw[1], "ExpirationDay"),
            "isChangeLayawayExpirationDate": _nullable_database_int(
                raw[2],
                "IsChangeLayawayExpirationDate",
            ),
            "minFirstPayment": _nullable_database_number(raw[3], "MinFirstPayment"),
            "disclaimer": None if raw[4] is None else str(raw[4]),
        }
    return [
        by_location.get(
            location_id,
            {
                "locationId": location_id,
                "enabled": False,
                "expirationDay": None,
                "isChangeLayawayExpirationDate": None,
                "minFirstPayment": None,
                "disclaimer": None,
            },
        )
        for location_id in location_ids
    ]


def _location_layaway_row_matches_defaults(row: dict[str, Any]) -> bool:
    try:
        minimum_matches = Decimal(str(row.get("minFirstPayment"))) == Decimal(
            LOCATION_LAYAWAY_DEFAULTS["minFirstPayment"]
        )
    except Exception:
        minimum_matches = False
    return bool(
        row.get("enabled")
        and row.get("expirationDay") == LOCATION_LAYAWAY_DEFAULTS["expirationDay"]
        and row.get("isChangeLayawayExpirationDate")
        == LOCATION_LAYAWAY_DEFAULTS["isChangeLayawayExpirationDate"]
        and minimum_matches
        and row.get("disclaimer") == LOCATION_LAYAWAY_DEFAULTS["disclaimer"]
    )


def _location_layaway_rows_match_defaults(rows: list[dict[str, Any]]) -> bool:
    return bool(rows) and all(_location_layaway_row_matches_defaults(row) for row in rows)


def _validate_location_layaway_enable_surface(
    cursor: Any,
    location_ids: list[int],
) -> None:
    metadata = cursor.execute(
        "SELECT t.temporal_type,t.is_memory_optimized "
        "FROM sys.tables t JOIN sys.schemas s ON s.schema_id=t.schema_id "
        "WHERE s.name=? AND t.name=?",
        ["dbo", "Locations_Layaways"],
    ).fetchone()
    if not metadata:
        raise NovaSqlScopeError(
            "dbo.Locations_Layaways is not an accessible base table"
        )
    if int(metadata[0] or 0):
        raise NovaSqlScopeError(
            "dbo.Locations_Layaways is temporal and cannot use this fixed operation"
        )
    if int(metadata[1] or 0):
        raise NovaSqlScopeError(
            "dbo.Locations_Layaways is memory optimized and cannot use this fixed operation"
        )

    create_permission = cursor.execute(
        "SELECT HAS_PERMS_BY_NAME(DB_NAME(), 'DATABASE', 'CREATE TABLE')"
    ).fetchone()
    schema_permission = cursor.execute(
        "SELECT HAS_PERMS_BY_NAME('dbo', 'SCHEMA', 'ALTER')"
    ).fetchone()
    if not create_permission or int(create_permission[0] or 0) != 1:
        raise NovaSqlScopeError("the Nova login cannot create the mandatory backup table")
    if not schema_permission or int(schema_permission[0] or 0) != 1:
        raise NovaSqlScopeError(
            "the Nova login cannot create a mandatory backup in schema dbo"
        )
    for permission in ("SELECT", "INSERT", "UPDATE"):
        allowed = cursor.execute(
            "SELECT HAS_PERMS_BY_NAME('dbo.Locations_Layaways', 'OBJECT', ?)",
            [permission],
        ).fetchone()
        if not allowed or int(allowed[0] or 0) != 1:
            raise NovaSqlScopeError(
                f"the Nova login lacks {permission} permission on dbo.Locations_Layaways"
            )

    trigger_count = cursor.execute(
        "SELECT COUNT_BIG(*) FROM sys.triggers WHERE parent_id=OBJECT_ID(?) "
        "AND is_disabled=0",
        [LOCATION_LAYAWAY_TABLE],
    ).fetchone()
    if trigger_count and int(trigger_count[0] or 0):
        raise NovaSqlScopeError(
            "dbo.Locations_Layaways has an enabled DML trigger outside this fixed contract"
        )

    cursor.execute(
        "SELECT c.name,ty.name,c.max_length,c.is_nullable,c.is_identity,"
        "c.is_computed,CASE WHEN dc.object_id IS NULL THEN 0 ELSE 1 END,"
        "c.generated_always_type "
        "FROM sys.columns c JOIN sys.types ty ON ty.user_type_id=c.user_type_id "
        "LEFT JOIN sys.default_constraints dc ON dc.object_id=c.default_object_id "
        "WHERE c.object_id=OBJECT_ID(?)",
        [LOCATION_LAYAWAY_TABLE],
    )
    column_rows = cursor.fetchall()
    columns = {str(row[0] or "").casefold(): row for row in column_rows}
    required_types = {
        "locationid": {"tinyint", "smallint", "int", "bigint"},
        "expirationday": {"tinyint", "smallint", "int", "bigint"},
        "ischangelayawayexpirationdate": {"bit", "tinyint", "smallint", "int"},
        "minfirstpayment": {
            "tinyint",
            "smallint",
            "int",
            "bigint",
            "decimal",
            "numeric",
            "money",
            "smallmoney",
            "float",
            "real",
        },
        "disclaimer": {"char", "varchar", "nchar", "nvarchar", "text", "ntext"},
    }
    for name, allowed_types in required_types.items():
        row = columns.get(name)
        if not row:
            raise NovaSqlScopeError(
                f"dbo.Locations_Layaways is missing required column {name}"
            )
        if str(row[1] or "").casefold() not in allowed_types:
            raise NovaSqlScopeError(
                f"dbo.Locations_Layaways column {name} has an unsupported type"
            )
        if bool(row[4]) or bool(row[5]) or int(row[7] or 0):
            raise NovaSqlScopeError(
                f"dbo.Locations_Layaways column {name} is not directly writable"
            )

    disclaimer = columns["disclaimer"]
    disclaimer_type = str(disclaimer[1] or "").casefold()
    max_length = int(disclaimer[2] or 0)
    required_length = len(LOCATION_LAYAWAY_DEFAULTS["disclaimer"])
    if max_length != -1 and disclaimer_type not in {"text", "ntext"}:
        available_characters = (
            max_length // 2 if disclaimer_type in {"nchar", "nvarchar"} else max_length
        )
        if available_characters < required_length:
            raise NovaSqlScopeError(
                "dbo.Locations_Layaways Disclaimer is too short for the fixed text"
            )

    included = set(required_types)
    for name, row in columns.items():
        if name in included:
            continue
        column_type = str(row[1] or "").casefold()
        auto_populated = bool(
            row[3]
            or row[4]
            or row[5]
            or row[6]
            or int(row[7] or 0)
            or column_type in {"timestamp", "rowversion"}
        )
        if not auto_populated:
            raise NovaSqlScopeError(
                f"dbo.Locations_Layaways column {row[0]} requires an unsupported caller value"
            )

    placeholders = ",".join("?" for _ in location_ids)
    cursor.execute(
        "SELECT [LocationId] FROM [dbo].[Locations] WITH (UPDLOCK, HOLDLOCK) "
        f"WHERE [LocationId] IN ({placeholders}) ORDER BY [LocationId]",
        location_ids,
    )
    resolved = [int(row[0]) for row in cursor.fetchall()]
    if resolved != location_ids:
        raise NovaSqlScopeError(
            "every location_id must resolve to exactly one dbo.Locations row"
        )


def _normalized_sql_module(value: str) -> str:
    return re.sub(r"[\s\[\]]+", "", str(value or "")).casefold()


def _read_location_region(
    cursor: Any,
    location_id: int,
    *,
    lock_for_update: bool = False,
) -> dict[str, int]:
    lock = " WITH (UPDLOCK, HOLDLOCK)" if lock_for_update else ""
    cursor.execute(
        f"SELECT [LocationId],[RegionId] FROM [dbo].[Locations]{lock} "
        "WHERE [LocationId]=?",
        [location_id],
    )
    rows = cursor.fetchall()
    if len(rows) != 1:
        raise NovaSqlScopeError("location_id did not resolve to exactly one dbo.Locations row")
    return {
        "locationId": int(rows[0][0]),
        "regionId": int(rows[0][1] or 0),
    }


def _read_location_reactivation(
    cursor: Any,
    location_id: int,
    *,
    lock_for_update: bool = False,
) -> dict[str, int]:
    lock = " WITH (UPDLOCK, HOLDLOCK)" if lock_for_update else ""
    cursor.execute(
        f"SELECT [LocationId],[RegionId],[LocationManagerEmployeeID] "
        f"FROM [dbo].[Locations]{lock} WHERE [LocationId]=?",
        [location_id],
    )
    rows = cursor.fetchall()
    if len(rows) != 1:
        raise NovaSqlScopeError(
            "location_id did not resolve to exactly one dbo.Locations row"
        )
    return {
        "locationId": int(rows[0][0]),
        "regionId": int(rows[0][1] or 0),
        "locationManagerEmployeeId": int(rows[0][2] or 0),
    }


def _validate_location_region_update_surface(cursor: Any, region_id: int) -> None:
    metadata = cursor.execute(
        "SELECT t.temporal_type,t.is_memory_optimized "
        "FROM sys.tables t JOIN sys.schemas s ON s.schema_id=t.schema_id "
        "WHERE s.name=? AND t.name=?",
        ["dbo", "Locations"],
    ).fetchone()
    if not metadata:
        raise NovaSqlScopeError("dbo.Locations is not an accessible base table")
    if int(metadata[0] or 0):
        raise NovaSqlScopeError("dbo.Locations is temporal and cannot use this fixed update")
    if int(metadata[1] or 0):
        raise NovaSqlScopeError(
            "dbo.Locations is memory optimized and cannot use this fixed update"
        )

    create_permission = cursor.execute(
        "SELECT HAS_PERMS_BY_NAME(DB_NAME(), 'DATABASE', 'CREATE TABLE')"
    ).fetchone()
    schema_permission = cursor.execute(
        "SELECT HAS_PERMS_BY_NAME('dbo', 'SCHEMA', 'ALTER')"
    ).fetchone()
    if not create_permission or int(create_permission[0] or 0) != 1:
        raise NovaSqlScopeError("the Nova login cannot create the mandatory backup table")
    if not schema_permission or int(schema_permission[0] or 0) != 1:
        raise NovaSqlScopeError("the Nova login cannot create a mandatory backup in schema dbo")
    for permission in ("SELECT", "UPDATE"):
        allowed = cursor.execute(
            "SELECT HAS_PERMS_BY_NAME('dbo.Locations', 'OBJECT', ?)",
            [permission],
        ).fetchone()
        if not allowed or int(allowed[0] or 0) != 1:
            raise NovaSqlScopeError(
                f"the Nova login lacks {permission} permission on dbo.Locations"
            )

    region = cursor.execute(
        "SELECT COUNT_BIG(*) FROM [dbo].[Regions] WHERE [RegionId]=?",
        [region_id],
    ).fetchone()
    if not region or int(region[0] or 0) != 1:
        raise NovaSqlScopeError("region_id did not resolve to exactly one dbo.Regions row")

    cursor.execute(
        "SELECT tr.name,sm.definition FROM sys.triggers tr "
        "JOIN sys.sql_modules sm ON sm.object_id=tr.object_id "
        "WHERE tr.parent_id=OBJECT_ID(?) AND tr.is_disabled=0",
        ["dbo.Locations"],
    )
    trigger_rows = cursor.fetchall()
    expected_definition = _normalized_sql_module(
        LOCATION_REGION_SAFE_TRIGGER_DEFINITION
    )
    for name, definition in trigger_rows:
        if (
            str(name or "").strip().casefold() != LOCATION_REGION_SAFE_TRIGGER_NAME
            or _normalized_sql_module(str(definition or "")) != expected_definition
        ):
            raise NovaSqlScopeError(
                "dbo.Locations has an enabled DML trigger outside the reviewed "
                "nonzero-RegionId contract"
            )


def _preview_source_databases(
    cursor: Any,
    plan: ValidatedWritePlan,
) -> list[dict[str, Any]]:
    return _source_database_summaries(cursor, plan.source_company_usernames)


def _source_database_summaries(
    cursor: Any,
    source_company_usernames: tuple[str, ...],
) -> list[dict[str, Any]]:
    sources: list[dict[str, Any]] = []
    for company_username in source_company_usernames:
        database = f"POS_{company_username}"
        access = cursor.execute(
            "SELECT DB_ID(?),HAS_DBACCESS(?)",
            database,
            database,
        ).fetchone()
        if (
            not access
            or access[0] is None
            or int(access[1] or 0) != 1
        ):
            raise NovaSqlScopeError(
                f"the guarded developer broker cannot read source {company_username}"
            )
        quoted = f"[{database}]"
        row = cursor.execute(
            "SELECT COUNT_BIG(DISTINCT t.object_id),COALESCE(SUM(p.rows),0) "
            f"FROM {quoted}.sys.tables t "
            f"LEFT JOIN {quoted}.sys.partitions p ON p.object_id=t.object_id "
            "AND p.index_id IN (0,1) WHERE t.is_ms_shipped=0"
        ).fetchone()
        sources.append(
            {
                "companyUsername": company_username,
                "databaseName": database,
                "tableCount": int(row[0] or 0) if row else 0,
                "estimatedRows": int(row[1] or 0) if row else 0,
                "accessMode": "read_only_by_statement_policy",
            }
        )
    return sources


def _reviewed_location_trigger_side_effects_are_backed(
    cursor: Any,
    plan: ValidatedWritePlan,
    *,
    table: str,
    enabled_trigger_count: int,
) -> bool:
    """Allow only the reviewed Locations trigger when its Logs side effect is backed."""

    target_tables = {item.casefold() for item in plan.target_operations}
    if (
        table.casefold() != "dbo.locations"
        or "dbo.logs" not in target_tables
        or enabled_trigger_count != 1
    ):
        return False

    cursor.execute(
        "SELECT tr.name,sm.definition FROM sys.triggers tr "
        "JOIN sys.sql_modules sm ON sm.object_id=tr.object_id "
        "WHERE tr.parent_id=OBJECT_ID(?) AND tr.is_disabled=0",
        [table],
    )
    trigger_rows = cursor.fetchall()
    if len(trigger_rows) != enabled_trigger_count:
        return False
    expected_definition = _normalized_sql_module(
        LOCATION_REGION_SAFE_TRIGGER_DEFINITION
    )
    return all(
        str(name or "").strip().casefold() == LOCATION_REGION_SAFE_TRIGGER_NAME
        and _normalized_sql_module(str(definition or "")) == expected_definition
        for name, definition in trigger_rows
    )


def _preview_target_tables(cursor: Any, plan: ValidatedWritePlan) -> list[dict[str, Any]]:
    if not plan.target_operations:
        return []
    create_permission = cursor.execute(
        "SELECT HAS_PERMS_BY_NAME(DB_NAME(), 'DATABASE', 'CREATE TABLE')"
    ).fetchone()
    if not create_permission or int(create_permission[0] or 0) != 1:
        raise NovaSqlScopeError("the Nova login cannot create the mandatory backup table")

    targets: list[dict[str, Any]] = []
    for table, operations in plan.target_operations.items():
        schema, name = table.split(".", 1)
        metadata = cursor.execute(
            "SELECT t.object_id, t.temporal_type, "
            "(SELECT COUNT_BIG(*) FROM sys.triggers tr WHERE tr.parent_id = t.object_id AND tr.is_disabled = 0), "
            "(SELECT COUNT_BIG(*) FROM sys.foreign_keys fk WHERE fk.referenced_object_id = t.object_id "
            " AND fk.is_disabled = 0 AND fk.update_referential_action <> 0) "
            "FROM sys.tables t JOIN sys.schemas s ON s.schema_id = t.schema_id "
            "WHERE s.name = ? AND t.name = ?",
            [schema, name],
        ).fetchone()
        if not metadata:
            raise NovaSqlScopeError(f"permanent target {table} is not an accessible base table")
        object_id = int(metadata[0])
        temporal_type = int(metadata[1] or 0)
        enabled_triggers = int(metadata[2] or 0)
        update_cascades = int(metadata[3] or 0)
        if temporal_type:
            raise NovaSqlScopeError(f"permanent target {table} is temporal and may touch an unbacked history table")
        if enabled_triggers and not _reviewed_location_trigger_side_effects_are_backed(
            cursor,
            plan,
            table=table,
            enabled_trigger_count=enabled_triggers,
        ):
            raise NovaSqlScopeError(f"permanent target {table} has enabled DML triggers that may touch unbacked tables")
        if "update" in operations and update_cascades:
            raise NovaSqlScopeError(f"permanent target {table} has cascading updates that may touch unbacked tables")

        schema_permission = cursor.execute(
            "SELECT HAS_PERMS_BY_NAME(?, 'SCHEMA', 'ALTER')",
            [schema],
        ).fetchone()
        if not schema_permission or int(schema_permission[0] or 0) != 1:
            raise NovaSqlScopeError(f"the Nova login cannot create a mandatory backup in schema {schema}")
        required_permissions = ("SELECT",) + tuple(operation.upper() for operation in operations)
        for permission in required_permissions:
            allowed = cursor.execute(
                "SELECT HAS_PERMS_BY_NAME(?, 'OBJECT', ?)",
                [table, permission],
            ).fetchone()
            if not allowed or int(allowed[0] or 0) != 1:
                raise NovaSqlScopeError(f"the Nova login lacks {permission} permission on {table}")
        identity_insert = table in plan.identity_insert_targets
        if identity_insert:
            identity_columns = cursor.execute(
                "SELECT COUNT_BIG(*) FROM sys.columns "
                "WHERE object_id=? AND is_identity=1",
                [object_id],
            ).fetchone()
            if not identity_columns or int(identity_columns[0] or 0) != 1:
                raise NovaSqlScopeError(
                    f"identity_insert requires exactly one identity column on {table}"
                )
            alter_permission = cursor.execute(
                "SELECT HAS_PERMS_BY_NAME(?, 'OBJECT', 'ALTER')",
                [table],
            ).fetchone()
            if not alter_permission or int(alter_permission[0] or 0) != 1:
                raise NovaSqlScopeError(
                    f"the Nova login lacks ALTER permission required for identity_insert on {table}"
                )

        quoted = _quoted_table(table)
        row_count_row = cursor.execute(f"SELECT COUNT_BIG(*) FROM {quoted}").fetchone()
        row_count = int(row_count_row[0] or 0) if row_count_row else 0
        targets.append(
            {
                "table": table,
                "objectId": object_id,
                "rowCount": row_count,
                "operations": list(operations),
                "backupTable": _backup_table_identifier(table, plan.plan_hash),
                "enabledTriggerCount": enabled_triggers,
                "updateCascadeCount": 0,
                "identityInsert": identity_insert,
            }
        )
    return targets


def _locations_feature_sql_type(spec: dict[str, Any]) -> str:
    ddl = str(spec["ddl"])
    return ddl.split("] ", 1)[1].rsplit(" NULL", 1)[0]


def _public_locations_feature_columns() -> list[dict[str, Any]]:
    return [
        {
            "name": str(spec["name"]),
            "sqlType": _locations_feature_sql_type(spec),
            "nullable": True,
        }
        for spec in LOCATIONS_FEATURE_COLUMNS
    ]


def _locations_feature_migration_state(
    cursor: Any,
    company_username: str,
    idempotency_key: str,
) -> dict[str, Any]:
    schema = "dbo"
    table_name = "Locations"
    metadata = cursor.execute(
        "SELECT t.object_id, t.temporal_type, t.is_memory_optimized "
        "FROM sys.tables t JOIN sys.schemas s ON s.schema_id = t.schema_id "
        "WHERE s.name = ? AND t.name = ?",
        [schema, table_name],
    ).fetchone()
    if not metadata:
        raise NovaSqlScopeError("dbo.Locations is not an accessible base table")
    if int(metadata[1] or 0):
        raise NovaSqlScopeError("dbo.Locations is temporal and cannot use this fixed migration")
    if int(metadata[2] or 0):
        raise NovaSqlScopeError("dbo.Locations is memory optimized and cannot use this fixed migration")

    enabled_ddl_triggers = cursor.execute(
        "SELECT COUNT_BIG(*) FROM sys.triggers "
        "WHERE parent_class = 0 AND is_disabled = 0"
    ).fetchone()
    if enabled_ddl_triggers and int(enabled_ddl_triggers[0] or 0):
        raise NovaSqlScopeError(
            "the database has an enabled DDL trigger whose side effects cannot be included in the backup"
        )

    create_permission = cursor.execute(
        "SELECT HAS_PERMS_BY_NAME(DB_NAME(), 'DATABASE', 'CREATE TABLE')"
    ).fetchone()
    if not create_permission or int(create_permission[0] or 0) != 1:
        raise NovaSqlScopeError("the Nova login cannot create the mandatory dbo.Locations backup")
    schema_permission = cursor.execute(
        "SELECT HAS_PERMS_BY_NAME(?, 'SCHEMA', 'ALTER')",
        [schema],
    ).fetchone()
    if not schema_permission or int(schema_permission[0] or 0) != 1:
        raise NovaSqlScopeError("the Nova login cannot create the mandatory backup in schema dbo")
    for permission in ("SELECT", "ALTER"):
        allowed = cursor.execute(
            "SELECT HAS_PERMS_BY_NAME(?, 'OBJECT', ?)",
            [LOCATIONS_FEATURE_TABLE, permission],
        ).fetchone()
        if not allowed or int(allowed[0] or 0) != 1:
            raise NovaSqlScopeError(f"the Nova login lacks {permission} permission on dbo.Locations")

    names = [str(spec["name"]) for spec in LOCATIONS_FEATURE_COLUMNS]
    placeholders = ", ".join("?" for _ in names)
    rows = cursor.execute(
        "SELECT c.name, LOWER(ty.name), c.max_length, c.precision, c.scale, c.is_nullable, "
        "c.is_computed, c.is_identity, c.generated_always_type, c.is_sparse, c.is_column_set, "
        "CASE WHEN c.user_type_id = c.system_type_id THEN 0 ELSE 1 END AS IsAliasType "
        "FROM sys.columns c JOIN sys.types ty ON ty.user_type_id = c.user_type_id "
        "WHERE c.object_id = OBJECT_ID(N'dbo.Locations', N'U') "
        f"AND c.name IN ({placeholders})",
        names,
    ).fetchall()
    actual_by_name: dict[str, tuple[Any, ...]] = {}
    for row in rows:
        key = str(row[0] or "").casefold()
        if key in actual_by_name:
            raise NovaSqlScopeError("dbo.Locations has ambiguous approved-column metadata")
        actual_by_name[key] = tuple(row)

    missing_columns: list[str] = []
    existing_columns: list[str] = []
    columns: list[dict[str, Any]] = []
    observed_columns: list[dict[str, Any]] = []
    for spec in LOCATIONS_FEATURE_COLUMNS:
        name = str(spec["name"])
        actual = actual_by_name.get(name.casefold())
        expected_public = {
            "name": name,
            "sqlType": _locations_feature_sql_type(spec),
            "nullable": True,
        }
        if actual is None:
            missing_columns.append(name)
            columns.append({**expected_public, "status": "missing"})
            observed_columns.append({"name": name, "present": False})
            continue

        matches = (
            str(actual[0]).casefold() == name.casefold()
            and str(actual[1]).casefold() == str(spec["type"]).casefold()
            and int(actual[2]) == int(spec["maxLength"])
            and int(actual[3]) == int(spec["precision"])
            and int(actual[4]) == int(spec["scale"])
            and bool(actual[5])
            and not any(bool(actual[index]) for index in range(6, 12))
        )
        if not matches:
            raise NovaSqlScopeError(
                f"existing dbo.Locations column {name} does not match the approved definition"
            )
        existing_columns.append(name)
        columns.append({**expected_public, "status": "verified_existing"})
        observed_columns.append({"name": name, "present": True, **expected_public})

    immutable = {
        "operation": LOCATIONS_FEATURE_MIGRATION,
        "companyUsername": company_username,
        "table": LOCATIONS_FEATURE_TABLE,
        "idempotencyKey": idempotency_key,
        "expectedColumns": _public_locations_feature_columns(),
        "observedColumns": observed_columns,
    }
    plan_hash = hashlib.sha256(
        json.dumps(immutable, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    ).hexdigest()
    row_count_row = cursor.execute("SELECT COUNT_BIG(*) FROM [dbo].[Locations]").fetchone()
    row_count = int(row_count_row[0] or 0) if row_count_row else 0
    return {
        "planHash": plan_hash,
        "missingColumns": missing_columns,
        "existingColumns": existing_columns,
        "columns": columns,
        "rowCount": row_count,
        "backupTable": _backup_table_identifier(LOCATIONS_FEATURE_TABLE, plan_hash),
    }


def _public_kit_upgrade_columns() -> list[dict[str, Any]]:
    return [
        {
            "name": str(spec["name"]),
            "sqlType": _locations_feature_sql_type(spec),
            "nullable": True,
            "default": None,
        }
        for spec in KIT_UPGRADE_COLUMNS
    ]


def _kit_upgrade_state(
    cursor: Any,
    company_username: str,
    idempotency_key: str,
) -> dict[str, Any]:
    metadata = cursor.execute(
        "SELECT t.object_id, t.temporal_type, t.is_memory_optimized "
        "FROM sys.tables t JOIN sys.schemas s ON s.schema_id = t.schema_id "
        "WHERE s.name = ? AND t.name = ?",
        ["dbo", "Kit"],
    ).fetchone()
    if not metadata:
        raise NovaSqlScopeError("dbo.Kit is not an accessible base table for the selected company")
    if int(metadata[1] or 0):
        raise NovaSqlScopeError("dbo.Kit is temporal and cannot use the fixed Kit upgrade")
    if int(metadata[2] or 0):
        raise NovaSqlScopeError("dbo.Kit is memory optimized and cannot use the fixed Kit upgrade")

    enabled_ddl_triggers = cursor.execute(
        "SELECT COUNT_BIG(*) FROM sys.triggers WHERE parent_class = 0 AND is_disabled = 0"
    ).fetchone()
    if enabled_ddl_triggers and int(enabled_ddl_triggers[0] or 0):
        raise NovaSqlScopeError(
            "the selected company database has an enabled DDL trigger whose side effects cannot be included in the backup"
        )

    create_permission = cursor.execute(
        "SELECT HAS_PERMS_BY_NAME(DB_NAME(), 'DATABASE', 'CREATE TABLE')"
    ).fetchone()
    if not create_permission or int(create_permission[0] or 0) != 1:
        raise NovaSqlScopeError("the Nova login cannot create the mandatory dbo.Kit backup")
    schema_permission = cursor.execute(
        "SELECT HAS_PERMS_BY_NAME(?, 'SCHEMA', 'ALTER')",
        ["dbo"],
    ).fetchone()
    if not schema_permission or int(schema_permission[0] or 0) != 1:
        raise NovaSqlScopeError("the Nova login cannot create the mandatory Kit backup in schema dbo")
    for permission in ("SELECT", "ALTER"):
        allowed = cursor.execute(
            "SELECT HAS_PERMS_BY_NAME(?, 'OBJECT', ?)",
            [KIT_UPGRADE_TABLE, permission],
        ).fetchone()
        if not allowed or int(allowed[0] or 0) != 1:
            raise NovaSqlScopeError(
                f"the Nova login lacks {permission} permission on dbo.Kit"
            )

    names = [str(spec["name"]) for spec in KIT_UPGRADE_COLUMNS]
    placeholders = ", ".join("?" for _ in names)
    rows = cursor.execute(
        "SELECT c.name, LOWER(ty.name), c.max_length, c.precision, c.scale, c.is_nullable, "
        "c.is_computed, c.is_identity, c.generated_always_type, c.is_sparse, c.is_column_set, "
        "CASE WHEN c.user_type_id = c.system_type_id THEN 0 ELSE 1 END AS IsAliasType, "
        "c.default_object_id "
        "FROM sys.columns c JOIN sys.types ty ON ty.user_type_id = c.user_type_id "
        "WHERE c.object_id = OBJECT_ID(N'dbo.Kit', N'U') "
        f"AND c.name IN ({placeholders})",
        names,
    ).fetchall()
    actual_by_name: dict[str, tuple[Any, ...]] = {}
    for row in rows:
        key = str(row[0] or "").casefold()
        if key in actual_by_name:
            raise NovaSqlScopeError("dbo.Kit has ambiguous approved-column metadata")
        actual_by_name[key] = tuple(row)

    missing_columns: list[str] = []
    existing_columns: list[str] = []
    columns: list[dict[str, Any]] = []
    observed_columns: list[dict[str, Any]] = []
    for spec in KIT_UPGRADE_COLUMNS:
        name = str(spec["name"])
        actual = actual_by_name.get(name.casefold())
        expected_public = {
            "name": name,
            "sqlType": _locations_feature_sql_type(spec),
            "nullable": True,
            "default": None,
        }
        if actual is None:
            missing_columns.append(name)
            columns.append({**expected_public, "status": "missing"})
            observed_columns.append({"name": name, "present": False})
            continue

        matches = (
            str(actual[0]).casefold() == name.casefold()
            and str(actual[1]).casefold() == str(spec["type"]).casefold()
            and int(actual[2]) == int(spec["maxLength"])
            and int(actual[3]) == int(spec["precision"])
            and int(actual[4]) == int(spec["scale"])
            and bool(actual[5])
            and not any(bool(actual[index]) for index in range(6, 12))
            and int(actual[12] or 0) == 0
        )
        if not matches:
            raise NovaSqlScopeError(
                f"existing dbo.Kit column {name} does not match the approved Kit upgrade definition"
            )
        existing_columns.append(name)
        columns.append({**expected_public, "status": "verified_existing"})
        observed_columns.append({"name": name, "present": True, **expected_public})

    preserved_sql = ", ".join(f"[{name}]" for name in KIT_UPGRADE_PRESERVED_COLUMNS)
    data_row = cursor.execute(
        "SELECT COUNT_BIG(*), COALESCE(CHECKSUM_AGG(BINARY_CHECKSUM("
        f"{preserved_sql}"
        ")), 0) FROM [dbo].[Kit] WITH (HOLDLOCK)"
    ).fetchone()
    row_count = int(data_row[0] or 0) if data_row else 0
    data_checksum = int(data_row[1] or 0) if data_row else 0
    immutable = {
        "operation": KIT_UPGRADE_MIGRATION,
        "companyUsername": company_username,
        "table": KIT_UPGRADE_TABLE,
        "idempotencyKey": idempotency_key,
        "expectedColumns": _public_kit_upgrade_columns(),
        "observedColumns": observed_columns,
        "preservedData": {"rowCount": row_count, "checksum": data_checksum},
    }
    plan_hash = hashlib.sha256(
        json.dumps(immutable, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    ).hexdigest()
    return {
        "planHash": plan_hash,
        "missingColumns": missing_columns,
        "existingColumns": existing_columns,
        "columns": columns,
        "rowCount": row_count,
        "dataChecksum": data_checksum,
        "backupTable": _backup_table_identifier(KIT_UPGRADE_TABLE, plan_hash),
    }


def _kit_upgrade_backup_matches(cursor: Any, backup_table: str) -> bool:
    source_sql = _quoted_table(KIT_UPGRADE_TABLE)
    backup_sql = _quoted_table(backup_table)
    columns = ", ".join(f"[{name}]" for name in KIT_UPGRADE_PRESERVED_COLUMNS)
    source_only = cursor.execute(
        f"SELECT COUNT_BIG(*) FROM (SELECT {columns} FROM {source_sql} "
        f"EXCEPT SELECT {columns} FROM {backup_sql}) AS [SourceOnly]"
    ).fetchone()
    backup_only = cursor.execute(
        f"SELECT COUNT_BIG(*) FROM (SELECT {columns} FROM {backup_sql} "
        f"EXCEPT SELECT {columns} FROM {source_sql}) AS [BackupOnly]"
    ).fetchone()
    return not int(source_only[0] or 0) and not int(backup_only[0] or 0)


def _kit_upgrade_non_null_count(cursor: Any, columns: list[str]) -> int:
    if not columns:
        return 0
    predicate = " OR ".join(f"[{name}] IS NOT NULL" for name in columns)
    row = cursor.execute(f"SELECT COUNT_BIG(*) FROM [dbo].[Kit] WHERE {predicate}").fetchone()
    return int(row[0] or 0) if row else 0


def _backup_table_identifier(source_table: str, plan_hash: str) -> str:
    schema, table = _normalize_qualified_table(source_table).split(".", 1)
    safe_base = table[:96]
    return f"{schema}.__codex_bak_{safe_base}_{plan_hash[:12]}"


def _table_exists(cursor: Any, table: str) -> bool:
    row = cursor.execute("SELECT CASE WHEN OBJECT_ID(?, 'U') IS NULL THEN 0 ELSE 1 END", [table]).fetchone()
    return bool(row and int(row[0] or 0))


def _acquire_write_lock(cursor: Any, company_username: str, idempotency_key: str) -> None:
    resource = f"NovaSqlGuardedWrite:{company_username}"[:240]
    row = cursor.execute(
        "DECLARE @result int; "
        "EXEC @result = sys.sp_getapplock @Resource = ?, @LockMode = 'Exclusive', "
        "@LockOwner = 'Transaction', @LockTimeout = 30000; SELECT @result",
        [resource],
    ).fetchone()
    result = int(row[0]) if row and row[0] is not None else -999
    if result < 0:
        raise NovaSqlUnavailableError("another guarded Nova SQL write currently holds the database lock")


def _verification_scalar(cursor: Any, plan: ValidatedWritePlan) -> int:
    cursor.execute(plan.verification_sql, plan.verification_parameters)
    row = cursor.fetchone()
    if not row or row[0] is None or isinstance(row[0], bool):
        raise NovaSqlScopeError("verification_sql must return one non-null integer scalar")
    try:
        value = int(row[0])
    except (TypeError, ValueError, OverflowError) as exc:
        raise NovaSqlScopeError("verification_sql must return one integer scalar") from exc
    if isinstance(row[0], (float, Decimal)) and row[0] != value:
        raise NovaSqlScopeError("verification_sql must return one integer scalar")
    return value


def _receipt_path(state_dir: Path, idempotency_key: str) -> Path:
    state_dir.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()
    return state_dir / f"{digest}.json"


def _locations_feature_receipt_path(state_dir: Path, idempotency_key: str) -> Path:
    return _receipt_path(state_dir, f"{LOCATIONS_FEATURE_MIGRATION}:{idempotency_key}")


def _kit_upgrade_receipt_path(state_dir: Path, idempotency_key: str) -> Path:
    return _receipt_path(state_dir, f"{KIT_UPGRADE_MIGRATION}:{idempotency_key}")


def _location_region_receipt_path(state_dir: Path, idempotency_key: str) -> Path:
    return _receipt_path(state_dir, f"{LOCATION_REGION_UPDATE}:{idempotency_key}")


def _location_reactivation_receipt_path(
    state_dir: Path,
    idempotency_key: str,
) -> Path:
    return _receipt_path(
        state_dir,
        f"{LOCATION_REACTIVATION_UPDATE}:{idempotency_key}",
    )


def _location_layaway_receipt_path(
    state_dir: Path,
    idempotency_key: str,
) -> Path:
    return _receipt_path(
        state_dir,
        f"{LOCATION_LAYAWAY_ENABLE}:{idempotency_key}",
    )


def _read_json_file(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise NovaSqlUnavailableError("guarded write receipt is unreadable; do not retry") from exc
    if not isinstance(value, dict):
        raise NovaSqlUnavailableError("guarded write receipt is invalid; do not retry")
    return value


def _write_receipt(
    path: Path,
    plan: ValidatedWritePlan,
    *,
    status: str,
    affected_rows: int,
    verification_value: int,
    backups: list[dict[str, Any]],
    source_rows_before: list[dict[str, Any]],
    source_rows_after: list[dict[str, Any]],
) -> dict[str, Any]:
    receipt = {
        "version": 1,
        "status": status,
        "recordedAt": datetime.now(timezone.utc).isoformat(),
        "companyUsername": plan.company_username,
        "databaseName": f"POS_{plan.company_username}",
        "sourceCompanyUsernames": list(plan.source_company_usernames),
        "idempotencyKey": plan.idempotency_key,
        "planHash": plan.plan_hash,
        "affectedRows": int(affected_rows),
        "verificationValue": int(verification_value),
        "backups": backups,
        "sourceRowsBefore": source_rows_before,
        "sourceRowsAfter": source_rows_after,
    }
    temporary = path.with_suffix(f".{os.getpid()}.tmp")
    temporary.write_text(json.dumps(receipt, sort_keys=True, indent=2), encoding="utf-8")
    os.replace(temporary, path)
    return receipt


def _write_locations_feature_receipt(
    path: Path,
    *,
    company_username: str,
    idempotency_key: str,
    plan_hash: str,
    status: str,
    columns_added: list[str],
    columns: list[dict[str, Any]],
    backups: list[dict[str, Any]],
    transaction_committed: bool,
    no_op: bool,
) -> dict[str, Any]:
    receipt = {
        "version": 1,
        "operation": LOCATIONS_FEATURE_MIGRATION,
        "status": status,
        "recordedAt": datetime.now(timezone.utc).isoformat(),
        "companyUsername": company_username,
        "databaseName": f"POS_{company_username}",
        "table": LOCATIONS_FEATURE_TABLE,
        "idempotencyKey": idempotency_key,
        "planHash": plan_hash,
        "columnsAdded": list(columns_added),
        "columns": list(columns),
        "backups": list(backups),
        "transactionCommitted": bool(transaction_committed),
        "noOp": bool(no_op),
        "postCommitReadbackVerified": status == "completed",
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f".{os.getpid()}.tmp")
    temporary.write_text(json.dumps(receipt, sort_keys=True, indent=2), encoding="utf-8")
    os.replace(temporary, path)
    return receipt


def _write_kit_upgrade_receipt(
    path: Path,
    *,
    company_username: str,
    idempotency_key: str,
    plan_hash: str,
    status: str,
    columns_added: list[str],
    columns: list[dict[str, Any]],
    backups: list[dict[str, Any]],
    source_data_fingerprint: dict[str, int],
    verified_data_fingerprint: dict[str, int],
    transaction_committed: bool,
    no_op: bool,
) -> dict[str, Any]:
    receipt = {
        "version": 1,
        "operation": KIT_UPGRADE_MIGRATION,
        "status": status,
        "recordedAt": datetime.now(timezone.utc).isoformat(),
        "companyUsername": company_username,
        "databaseName": f"POS_{company_username}",
        "table": KIT_UPGRADE_TABLE,
        "idempotencyKey": idempotency_key,
        "planHash": plan_hash,
        "columnsAdded": list(columns_added),
        "columns": list(columns),
        "backups": list(backups),
        "sourceDataFingerprint": dict(source_data_fingerprint),
        "verifiedDataFingerprint": dict(verified_data_fingerprint),
        "transactionCommitted": bool(transaction_committed),
        "noOp": bool(no_op),
        "postCommitReadbackVerified": status == "completed",
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f".{os.getpid()}.tmp")
    temporary.write_text(json.dumps(receipt, sort_keys=True, indent=2), encoding="utf-8")
    os.replace(temporary, path)
    return receipt


def _write_location_region_receipt(
    path: Path,
    *,
    company_username: str,
    location_id: int,
    region_id: int,
    idempotency_key: str,
    plan_hash: str,
    status: str,
    before: dict[str, int],
    after: dict[str, int],
    backups: list[dict[str, Any]],
    transaction_committed: bool,
    no_op: bool,
) -> dict[str, Any]:
    receipt = {
        "version": 1,
        "operation": LOCATION_REGION_UPDATE,
        "status": status,
        "recordedAt": datetime.now(timezone.utc).isoformat(),
        "companyUsername": company_username,
        "databaseName": f"POS_{company_username}",
        "table": LOCATIONS_FEATURE_TABLE,
        "locationId": location_id,
        "regionId": region_id,
        "idempotencyKey": idempotency_key,
        "planHash": plan_hash,
        "before": dict(before),
        "after": dict(after),
        "backups": list(backups),
        "transactionCommitted": bool(transaction_committed),
        "noOp": bool(no_op),
        "postCommitReadbackVerified": status == "completed",
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f".{os.getpid()}.tmp")
    temporary.write_text(json.dumps(receipt, sort_keys=True, indent=2), encoding="utf-8")
    os.replace(temporary, path)
    return receipt


def _write_location_reactivation_receipt(
    path: Path,
    *,
    company_username: str,
    location_id: int,
    idempotency_key: str,
    plan_hash: str,
    status: str,
    before: dict[str, int],
    after: dict[str, int],
    backups: list[dict[str, Any]],
    transaction_committed: bool,
    no_op: bool,
) -> dict[str, Any]:
    receipt = {
        "version": 1,
        "operation": LOCATION_REACTIVATION_UPDATE,
        "status": status,
        "recordedAt": datetime.now(timezone.utc).isoformat(),
        "companyUsername": company_username,
        "databaseName": f"POS_{company_username}",
        "table": LOCATIONS_FEATURE_TABLE,
        "locationId": location_id,
        "fromLocationManagerEmployeeId": 1,
        "toLocationManagerEmployeeId": 0,
        "idempotencyKey": idempotency_key,
        "planHash": plan_hash,
        "before": dict(before),
        "after": dict(after),
        "backups": list(backups),
        "transactionCommitted": bool(transaction_committed),
        "noOp": bool(no_op),
        "postCommitReadbackVerified": status == "completed",
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f".{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(receipt, sort_keys=True, indent=2),
        encoding="utf-8",
    )
    os.replace(temporary, path)
    return receipt


def _write_location_layaway_receipt(
    path: Path,
    *,
    company_username: str,
    location_ids: list[int],
    idempotency_key: str,
    plan_hash: str,
    status: str,
    affected_rows: int,
    before: list[dict[str, Any]],
    after: list[dict[str, Any]],
    backups: list[dict[str, Any]],
    transaction_committed: bool,
    no_op: bool,
) -> dict[str, Any]:
    receipt = {
        "version": 1,
        "operation": LOCATION_LAYAWAY_ENABLE,
        "status": status,
        "recordedAt": datetime.now(timezone.utc).isoformat(),
        "companyUsername": company_username,
        "databaseName": f"POS_{company_username}",
        "table": LOCATION_LAYAWAY_TABLE,
        "locationIds": list(location_ids),
        "defaults": dict(LOCATION_LAYAWAY_DEFAULTS),
        "idempotencyKey": idempotency_key,
        "planHash": plan_hash,
        "affectedRows": int(affected_rows),
        "before": list(before),
        "after": list(after),
        "backups": list(backups),
        "transactionCommitted": bool(transaction_committed),
        "noOp": bool(no_op),
        "postCommitReadbackVerified": status == "completed",
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f".{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(receipt, sort_keys=True, indent=2),
        encoding="utf-8",
    )
    os.replace(temporary, path)
    return receipt


def _location_region_receipt_result(
    receipt: dict[str, Any],
    *,
    company_username: str,
    location_id: int,
    region_id: int,
    idempotency_key: str,
    plan_hash: str,
    replay: bool,
) -> dict[str, Any]:
    if not all(
        (
            receipt.get("operation") == LOCATION_REGION_UPDATE,
            str(receipt.get("companyUsername") or "").casefold()
            == company_username.casefold(),
            int(receipt.get("locationId") or 0) == location_id,
            int(receipt.get("regionId") or 0) == region_id,
            receipt.get("idempotencyKey") == idempotency_key,
            receipt.get("planHash") == plan_hash,
        )
    ):
        raise NovaSqlScopeError(
            "idempotency key was already used for a different location-region target"
        )
    if receipt.get("status") != "completed":
        raise NovaSqlUnavailableError(
            "a prior location-region update may have committed without verified readback; do not retry"
        )
    return {
        "ok": True,
        "status": "completed",
        "accessMode": "fixed_location_region_update",
        "operation": LOCATION_REGION_UPDATE,
        "companyUsername": company_username,
        "databaseName": f"POS_{company_username}",
        "table": LOCATIONS_FEATURE_TABLE,
        "locationId": location_id,
        "regionId": region_id,
        "idempotencyKey": idempotency_key,
        "planHash": plan_hash,
        "before": dict(receipt.get("before") or {}),
        "readback": dict(receipt.get("after") or {}),
        "backupTables": list(receipt.get("backups") or []),
        "transactionCommitted": bool(receipt.get("transactionCommitted")),
        "postCommitReadbackVerified": True,
        "noOp": bool(receipt.get("noOp")),
        "idempotentReplay": bool(replay),
        "arbitrarySqlAccepted": False,
        "triggerContract": "nonzero_regionid_side_effect_free",
    }


def _location_reactivation_receipt_result(
    receipt: dict[str, Any],
    *,
    company_username: str,
    location_id: int,
    idempotency_key: str,
    plan_hash: str,
    replay: bool,
) -> dict[str, Any]:
    if not all(
        (
            receipt.get("operation") == LOCATION_REACTIVATION_UPDATE,
            str(receipt.get("companyUsername") or "").casefold()
            == company_username.casefold(),
            int(receipt.get("locationId") or 0) == location_id,
            int(receipt.get("fromLocationManagerEmployeeId") or 0) == 1,
            receipt.get("toLocationManagerEmployeeId") == 0,
            receipt.get("idempotencyKey") == idempotency_key,
            receipt.get("planHash") == plan_hash,
        )
    ):
        raise NovaSqlScopeError(
            "idempotency key was already used for a different location-reactivation target"
        )
    if receipt.get("status") != "completed":
        raise NovaSqlUnavailableError(
            "a prior location reactivation may have committed without verified readback; do not retry"
        )
    return {
        "ok": True,
        "status": "completed",
        "accessMode": "fixed_location_reactivation_update",
        "operation": LOCATION_REACTIVATION_UPDATE,
        "companyUsername": company_username,
        "databaseName": f"POS_{company_username}",
        "table": LOCATIONS_FEATURE_TABLE,
        "locationId": location_id,
        "fromLocationManagerEmployeeId": 1,
        "toLocationManagerEmployeeId": 0,
        "idempotencyKey": idempotency_key,
        "planHash": plan_hash,
        "before": dict(receipt.get("before") or {}),
        "readback": dict(receipt.get("after") or {}),
        "backupTables": list(receipt.get("backups") or []),
        "transactionCommitted": bool(receipt.get("transactionCommitted")),
        "postCommitReadbackVerified": True,
        "noOp": bool(receipt.get("noOp")),
        "idempotentReplay": bool(replay),
        "arbitrarySqlAccepted": False,
        "triggerContract": "reviewed_fixzero_with_positive_regionid",
    }


def _location_layaway_receipt_result(
    receipt: dict[str, Any],
    *,
    company_username: str,
    location_ids: list[int],
    idempotency_key: str,
    plan_hash: str,
    replay: bool,
) -> dict[str, Any]:
    try:
        receipt_location_ids = sorted(
            int(value) for value in receipt.get("locationIds") or []
        )
    except (TypeError, ValueError, OverflowError) as exc:
        raise NovaSqlScopeError("location-layaway receipt target is invalid") from exc
    if not all(
        (
            receipt.get("operation") == LOCATION_LAYAWAY_ENABLE,
            str(receipt.get("companyUsername") or "").casefold()
            == company_username.casefold(),
            receipt_location_ids == location_ids,
            dict(receipt.get("defaults") or {}) == LOCATION_LAYAWAY_DEFAULTS,
            receipt.get("idempotencyKey") == idempotency_key,
            receipt.get("planHash") == plan_hash,
        )
    ):
        raise NovaSqlScopeError(
            "idempotency key was already used for a different location-layaway target"
        )
    if receipt.get("status") != "completed":
        raise NovaSqlUnavailableError(
            "a prior location layaway enablement may have committed without verified readback; do not retry"
        )
    return {
        "ok": True,
        "status": "completed",
        "accessMode": "fixed_location_layaway_enable",
        "operation": LOCATION_LAYAWAY_ENABLE,
        "companyUsername": company_username,
        "databaseName": f"POS_{company_username}",
        "table": LOCATION_LAYAWAY_TABLE,
        "locationIds": list(location_ids),
        "defaults": dict(LOCATION_LAYAWAY_DEFAULTS),
        "idempotencyKey": idempotency_key,
        "planHash": plan_hash,
        "affectedRows": int(receipt.get("affectedRows") or 0),
        "before": list(receipt.get("before") or []),
        "readback": list(receipt.get("after") or []),
        "backupTables": list(receipt.get("backups") or []),
        "transactionCommitted": bool(receipt.get("transactionCommitted")),
        "postCommitReadbackVerified": True,
        "noOp": bool(receipt.get("noOp")),
        "idempotentReplay": bool(replay),
        "arbitrarySqlAccepted": False,
    }


def _locations_feature_receipt_result(
    receipt: dict[str, Any],
    *,
    company_username: str,
    idempotency_key: str,
    preview_hash: str,
    replay: bool,
) -> dict[str, Any]:
    same_operation = receipt.get("operation") == LOCATIONS_FEATURE_MIGRATION
    same_company = str(receipt.get("companyUsername") or "").casefold() == company_username.casefold()
    same_key = receipt.get("idempotencyKey") == idempotency_key
    same_plan = receipt.get("planHash") == preview_hash
    if not all((same_operation, same_company, same_key, same_plan)):
        raise NovaSqlScopeError(
            "idempotency key was already used for a different Locations migration target or preview"
        )
    if receipt.get("status") != "completed":
        raise NovaSqlUnavailableError(
            "a prior Locations migration may have committed without verified readback; do not retry"
        )
    return {
        "ok": True,
        "status": "completed",
        "accessMode": "fixed_schema_migration",
        "operation": LOCATIONS_FEATURE_MIGRATION,
        "companyUsername": company_username,
        "databaseName": f"POS_{company_username}",
        "table": LOCATIONS_FEATURE_TABLE,
        "planHash": preview_hash,
        "idempotencyKey": idempotency_key,
        "columnsAdded": list(receipt.get("columnsAdded") or []),
        "verifiedColumns": list(receipt.get("columns") or []),
        "backupTables": list(receipt.get("backups") or []),
        "transactionCommitted": bool(receipt.get("transactionCommitted")),
        "postCommitReadbackVerified": True,
        "noOp": bool(receipt.get("noOp")),
        "idempotentReplay": bool(replay),
        "arbitrarySqlAccepted": False,
    }


def _kit_upgrade_receipt_result(
    receipt: dict[str, Any],
    *,
    company_username: str,
    idempotency_key: str,
    preview_hash: str,
    replay: bool,
) -> dict[str, Any]:
    same_operation = receipt.get("operation") == KIT_UPGRADE_MIGRATION
    same_company = str(receipt.get("companyUsername") or "").casefold() == company_username.casefold()
    same_key = receipt.get("idempotencyKey") == idempotency_key
    same_plan = receipt.get("planHash") == preview_hash
    if not all((same_operation, same_company, same_key, same_plan)):
        raise NovaSqlScopeError(
            "idempotency key was already used for a different Kit upgrade target or preview"
        )
    if receipt.get("status") != "completed":
        raise NovaSqlUnavailableError(
            "a prior Kit upgrade may have committed without verified readback; do not retry"
        )
    return {
        "ok": True,
        "status": "completed",
        "accessMode": "fixed_schema_migration",
        "operation": KIT_UPGRADE_MIGRATION,
        "companyUsername": company_username,
        "databaseName": f"POS_{company_username}",
        "table": KIT_UPGRADE_TABLE,
        "planHash": preview_hash,
        "idempotencyKey": idempotency_key,
        "columnsAdded": list(receipt.get("columnsAdded") or []),
        "verifiedColumns": list(receipt.get("columns") or []),
        "backupTables": list(receipt.get("backups") or []),
        "sourceDataFingerprint": dict(receipt.get("sourceDataFingerprint") or {}),
        "verifiedDataFingerprint": dict(receipt.get("verifiedDataFingerprint") or {}),
        "transactionCommitted": bool(receipt.get("transactionCommitted")),
        "postCommitReadbackVerified": True,
        "noOp": bool(receipt.get("noOp")),
        "idempotentReplay": bool(replay),
        "arbitrarySqlAccepted": False,
        "fixedSchemaContract": True,
    }


def _idempotent_receipt_result(receipt: dict[str, Any], plan: ValidatedWritePlan) -> dict[str, Any]:
    if receipt.get("planHash") != plan.plan_hash or receipt.get("idempotencyKey") != plan.idempotency_key:
        raise NovaSqlScopeError("idempotency key was already used for a different Nova SQL write plan")
    if receipt.get("status") != "completed":
        raise NovaSqlUnavailableError("a prior write may have committed without verified readback; do not retry")
    return {
        "ok": True,
        "status": "completed",
        "accessMode": "guarded_write",
        "companyUsername": plan.company_username,
        "databaseName": f"POS_{plan.company_username}",
        "sourceCompanyUsernames": list(plan.source_company_usernames),
        "sourceDatabasesReadOnly": bool(plan.source_company_usernames),
        "executionMode": (
            "cross_account_set_based_sql"
            if plan.source_company_usernames
            else "single_account_guarded_sql"
        ),
        "planHash": plan.plan_hash,
        "idempotencyKey": plan.idempotency_key,
        "affectedRows": int(receipt.get("affectedRows", 0)),
        "verificationValue": int(receipt.get("verificationValue", 0)),
        "backupTables": list(receipt.get("backups") or []),
        "sourceRowsBefore": list(receipt.get("sourceRowsBefore") or []),
        "sourceRowsAfter": list(receipt.get("sourceRowsAfter") or []),
        "sourceRowCountsStableDuringExecution": (
            list(receipt.get("sourceRowsBefore") or [])
            == list(receipt.get("sourceRowsAfter") or [])
        ),
        "transactionCommitted": True,
        "postCommitReadbackVerified": True,
        "idempotentReplay": True,
    }


def _validated_select(
    value: str,
    *,
    allowed_source_databases: tuple[str, ...] = (),
) -> str:
    sql = str(value or "").strip()
    if not sql or len(sql) > 20_000:
        raise NovaSqlScopeError("sql must be between 1 and 20000 characters")
    if "--" in sql or "/*" in sql or "*/" in sql:
        raise NovaSqlScopeError("SQL comments are not allowed")
    statements = [part.strip() for part in sql.split(";") if part.strip()]
    if len(statements) != 1:
        raise NovaSqlScopeError("exactly one SQL statement is allowed")
    clean = statements[0]
    if not re.match(r"^(?:select|with)\b", clean, re.IGNORECASE):
        raise NovaSqlScopeError("only SELECT or CTE SELECT reads are allowed")
    if FORBIDDEN_SQL.search(clean) or SELECT_INTO.search(clean):
        raise NovaSqlScopeError("SQL contains a write, execution, or external-access operation")
    _validate_cross_database_reads(clean, allowed_source_databases)
    return clean


def _bounded_parameters(values: list[Any] | None) -> list[Any]:
    if values is None:
        return []
    if not isinstance(values, list) or len(values) > 50:
        raise NovaSqlScopeError("parameters must be a list of at most 50 scalar values")
    result: list[Any] = []
    for value in values:
        if value is None or isinstance(value, (bool, int, float, Decimal, date, datetime)):
            result.append(value)
        elif isinstance(value, str) and len(value) <= 4000:
            result.append(value)
        else:
            raise NovaSqlScopeError("SQL parameters must be bounded scalar values")
    return result


def _decrypt_nova_password(value: str) -> str:
    if not value or not value.startswith("="):
        return value
    try:
        decoded = base64.b64decode(value[1:], validate=True).decode("utf-8")
        return "".join(chr(ord(character) - index) for index, character in enumerate(decoded))
    except Exception as exc:
        raise NovaSqlUnavailableError("Nova SQL credential could not be decoded") from exc


def _safe_value(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, (bytes, bytearray, memoryview)):
        return f"<binary:{len(value)}>"
    return str(value)[:4000]


def _money_decimal(value: Any) -> Decimal:
    if value is None or value == "":
        return Decimal("0")
    try:
        return Decimal(str(value))
    except Exception as exc:
        raise NovaSqlUnavailableError(
            "Nova SQL spare investigation returned a non-numeric money value"
        ) from exc


def _money_round(value: Any) -> Decimal:
    return _money_decimal(value).quantize(Decimal("0.01"))


def _money_equal(left: Any, right: Any) -> bool:
    return abs(_money_round(left) - _money_round(right)) <= Decimal("0.01")


def _minimum_gap_candidates(
    lines: list[dict[str, Any]],
    gap: Decimal,
) -> list[dict[str, Any]]:
    clean_gap = _money_round(gap)
    if clean_gap <= 0 or len(lines) > 30:
        return []
    candidates: list[dict[str, Any]] = []
    eligible = [
        item
        for item in lines
        if _money_decimal(item.get("currentMinimumContribution")) > 0
    ]
    for size in range(1, min(3, len(eligible)) + 1):
        for group in combinations(eligible, size):
            contribution = _money_round(
                sum(
                    (
                        _money_decimal(item["currentMinimumContribution"])
                        for item in group
                    ),
                    Decimal("0"),
                )
            )
            if not _money_equal(contribution, clean_gap):
                continue
            candidates.append(
                {
                    "currentMinimumContribution": _safe_value(contribution),
                    "products": [
                        {
                            "productId": int(item["productId"]),
                            "productName": str(item["productName"] or "")[:255],
                            "quantity": item["quantity"],
                            "currentEffectiveMinimumPrice": item[
                                "currentEffectiveMinimumPrice"
                            ],
                        }
                        for item in group
                    ],
                    "interpretation": (
                        "These current minimum-price contributions exactly explain the gap; "
                        "verify whether they were zero, lower, or excluded at sale."
                    ),
                }
            )
            if len(candidates) >= 10:
                return candidates
    return candidates
