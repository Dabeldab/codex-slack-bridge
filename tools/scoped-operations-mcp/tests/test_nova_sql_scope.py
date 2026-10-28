from __future__ import annotations

# AgentChat/coding_agent 2026-08-05T11:15:00Z

import re
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from scoped_operations_mcp.nova_sql_client import (
    INVOICE_SPARE_INVESTIGATION,
    LOCATION_LAYAWAY_DEFAULTS,
    LOCATION_LAYAWAY_ENABLE,
    LOCATION_REGION_SAFE_TRIGGER_DEFINITION,
    LOCATION_REGION_UPDATE,
    LOCATION_REACTIVATION_UPDATE,
    LOCATIONS_FEATURE_COLUMNS,
    LOCATIONS_FEATURE_MIGRATION,
    KIT_UPGRADE_MIGRATION,
    KIT_UPGRADE_COLUMNS,
    NovaSqlScopeError,
    NovaSqlSettings,
    NovaSqlUnavailableError,
    ScopedNovaSqlClient,
    _preview_target_tables,
    _validated_select,
    _validated_write_plan,
)


class FakeSalesforce:
    def _resolve_nova_sql_account(self, company_username):
        return {"company_username": company_username, "password": "safe-test-password"}


class FakeCursor:
    timeout = 0

    def __init__(self, *, description, rows):
        self.description = [(name,) for name in description]
        self.rows = list(rows)

    def execute(self, _sql, _parameters=None):
        return self

    def fetchone(self):
        return self.rows[0]

    def fetchmany(self, count):
        return self.rows[:count]


class FakeConnection:
    def __init__(self, cursor):
        self._cursor = cursor
        self.closed = False
        self.timeout = 0

    def cursor(self):
        return self._cursor

    def close(self):
        self.closed = True


class InvoiceSpareCursor:
    timeout = 0

    def __init__(self, *, missing_root=False):
        self.description = []
        self.rows = []
        self.commands = []
        self.missing_root = missing_root

    def execute(self, sql, parameters=None):
        values = list(parameters or [])
        self.commands.append((str(sql), values))
        normalized = " ".join(str(sql).split())
        if "FROM dbo.Invoice_Products ip" in normalized:
            self.description = [
                ("InvoiceID",),
                ("InvoiceProductsID",),
                ("ProductID",),
                ("ProductName",),
                ("Quantity",),
                ("SaleUnitPrice",),
                ("StoredUnitDiscount",),
                ("StoredProductTax",),
                ("ProductCostPriceAtSale",),
                ("CurrentBaseMinimumPrice",),
                ("CurrentPriceListMinimumPrice",),
                ("CurrentEffectiveMinimumPrice",),
                ("CurrentBaseMarkupPrice",),
                ("CurrentPriceListMarkupPrice",),
                ("CurrentEffectiveMarkupPrice",),
                ("PriceListID",),
            ]
            self.rows = [
                (12642, 22458, 277, "Microneedling RF Premium", 1, Decimal("1950"), Decimal("150"), Decimal("0"), Decimal("0"), Decimal("400"), None, Decimal("400"), Decimal("1950"), None, Decimal("1950"), None),
                (12642, 22459, 287, "Hifu face & neck", 1, Decimal("1760"), Decimal("0"), Decimal("0"), Decimal("0"), Decimal("350"), None, Decimal("350"), Decimal("1760"), None, Decimal("1760"), None),
                (12643, 22460, 277, "Microneedling RF Premium", 1, Decimal("1950"), Decimal("1950"), Decimal("0"), Decimal("0"), Decimal("400"), None, Decimal("400"), Decimal("1950"), None, Decimal("1950"), None),
                (12643, 22461, 287, "Hifu face & neck", 3, Decimal("1760"), Decimal("1760"), Decimal("0"), Decimal("0"), Decimal("350"), None, Decimal("350"), Decimal("1760"), None, Decimal("1760"), None),
                (12643, 22462, 359, "RF FACE", 6, Decimal("899"), Decimal("899"), Decimal("0"), Decimal("0"), Decimal("300"), None, Decimal("300"), Decimal("899"), None, Decimal("899"), None),
                (12643, 22463, 261, "The Perfect Derma Peel", 2, Decimal("1200"), Decimal("1200"), Decimal("0"), Decimal("0"), Decimal("399.99"), None, Decimal("399.99"), Decimal("1200"), None, Decimal("1200"), None),
                (12643, 22464, 275, "Microneedling Promo", 2, Decimal("250"), Decimal("250"), Decimal("0"), Decimal("0"), Decimal("99"), None, Decimal("99"), Decimal("250"), None, Decimal("250"), None),
            ]
        elif "FROM dbo.Invoice_Payments" in normalized:
            self.description = [
                ("InvoiceID",),
                ("InvoicePaymentID",),
                ("PaymentMethod",),
                ("Amount",),
                ("Tip",),
                ("Timestamp",),
            ]
            self.rows = [
                (12642, 12241, "Other", Decimal("3560"), Decimal("0"), datetime(2026, 7, 9, 12, 26, 46)),
            ]
        elif "FROM dbo.Invoice_Coupons ic" in normalized:
            self.description = [
                ("InvoiceID",),
                ("InvoiceCouponID",),
                ("CouponID",),
                ("AmountUsed",),
                ("Description",),
                ("Code",),
                ("CurrentCouponSpare",),
            ]
            self.rows = []
        elif "FROM dbo.Locations WHERE" in normalized:
            self.description = [
                ("LocationID",),
                ("LocationName",),
                ("IsForceMinimumPrice",),
                ("MaxMinutesSinceLastInvoiceToAttach",),
                ("PriceListID",),
                ("IsDisplayProductPriceIncTax",),
            ]
            self.rows = [(1, "Lilly Beauty", True, 120, None, False)]
        elif "OR SpareInvoiceID" in normalized:
            self.description = [(name,) for name in (
                "InvoiceID", "LocationID", "Timestamp", "ServerTimestamp", "Subtotal",
                "Tax", "Total", "Discount", "Spare", "SpareInvoiceID", "InvoiceTypeID",
                "TotalTip",
            )]
            self.rows = [
                (12642, 1, datetime(2026, 7, 9, 12, 26, 46), datetime(2026, 7, 9, 14, 26, 47), Decimal("3560"), Decimal("0"), Decimal("3560"), Decimal("150"), Decimal("-2810"), 0, 1, Decimal("0")),
                (12643, 1, datetime(2026, 7, 9, 12, 27, 18), datetime(2026, 7, 9, 14, 27, 19), Decimal("0"), Decimal("0"), Decimal("0"), Decimal("15524"), Decimal("362.02"), 12642, 1, Decimal("0")),
            ]
        else:
            self.description = [(name,) for name in (
                "InvoiceID", "LocationID", "Timestamp", "ServerTimestamp", "Subtotal",
                "Tax", "Total", "Discount", "Spare", "SpareInvoiceID", "InvoiceTypeID",
                "TotalTip",
            )]
            self.rows = [] if self.missing_root else [
                (12643, 1, datetime(2026, 7, 9, 12, 27, 18), datetime(2026, 7, 9, 14, 27, 19), Decimal("0"), Decimal("0"), Decimal("0"), Decimal("15524"), Decimal("362.02"), 12642, 1, Decimal("0")),
            ]
        return self

    def fetchmany(self, count):
        return self.rows[:count]


class DataMoveReadCursor:
    timeout = 0

    def __init__(self):
        self.description = []
        self.rows = []
        self.commands = []

    def execute(self, sql, *parameters):
        values = (
            list(parameters[0])
            if len(parameters) == 1 and isinstance(parameters[0], list)
            else list(parameters)
        )
        self.commands.append((sql, values))
        normalized = " ".join(str(sql).split())
        if normalized == "SELECT DB_NAME()":
            self.description = [("DatabaseName",)]
            self.rows = [("POS_Target_Account",)]
        elif normalized == "SELECT DB_ID(?),HAS_DBACCESS(?)":
            self.description = [("DatabaseId",), ("HasAccess",)]
            self.rows = [(42, 1)]
        elif ".sys.tables t" in normalized:
            self.description = [("TableCount",), ("EstimatedRows",)]
            self.rows = [(117, 1_754_246)]
        else:
            self.description = [
                ("CandidateCount",),
                ("ApiPassword",),
            ]
            self.rows = [(101, "never-return")]
        return self

    def fetchone(self):
        return self.rows[0]

    def fetchmany(self, count):
        return self.rows[:count]


class ApiCohortCursor:
    timeout = 0

    def __init__(self):
        self.description = []
        self.rows = []
        self.commands = []

    def execute(self, sql, _parameters=None):
        self.commands.append(sql)
        if sql == "SELECT DB_NAME() AS DatabaseName":
            self.description = [("DatabaseName",)]
            self.rows = [("POS_Main",)]
        else:
            self.description = [("Username",), ("DatabaseName",), ("ApiExpirationDate",)]
            self.rows = [("Kento", "POS_Kento", datetime(2027, 1, 1, tzinfo=timezone.utc))]
        return self

    def fetchone(self):
        return self.rows[0]

    def fetchmany(self, count):
        return self.rows[:count]


class ApiCohortSalesforce(FakeSalesforce):
    def __init__(self):
        self.received = []

    def api_customer_email_cohort(self, api_accounts):
        self.received = api_accounts
        return {"ok": True, "verified": True, "recipientCount": 1, "recipients": []}


def _approved_locations_column_metadata(spec):
    return (
        spec["name"],
        spec["type"],
        spec["maxLength"],
        spec["precision"],
        spec["scale"],
        1,
        0,
        0,
        0,
        0,
        0,
        0,
    )


class LocationsMigrationCursor:
    timeout = 0
    rowcount = -1

    def __init__(self, state):
        self.state = state
        self.rows = []

    def execute(self, sql, parameters=None):
        parameters = list(parameters or [])
        self.state["commands"].append((sql, parameters))
        normalized = " ".join(str(sql).split())
        upper = normalized.upper()
        self.rows = []

        if upper == "SELECT DB_NAME()":
            self.rows = [("POS_Kento",)]
        elif "FROM SYS.TABLES T JOIN SYS.SCHEMAS" in upper:
            self.rows = [(101, 0, 0)]
        elif "FROM SYS.TRIGGERS" in upper and "PARENT_CLASS = 0" in upper:
            self.rows = [(0,)]
        elif "HAS_PERMS_BY_NAME" in upper:
            self.rows = [(1,)]
        elif "FROM SYS.COLUMNS C JOIN SYS.TYPES" in upper:
            requested = {str(value).casefold() for value in parameters}
            self.rows = [
                tuple(metadata)
                for name, metadata in self.state["columns"].items()
                if name.casefold() in requested
            ]
        elif upper.startswith("SELECT COUNT_BIG(*) FROM [DBO].[LOCATIONS]"):
            self.rows = [(self.state["row_count"],)]
        elif upper.startswith("SELECT COUNT_BIG(*) FROM [DBO].[__CODEX_BAK_"):
            match = re.search(r"FROM\s+\[dbo\]\.\[([^\]]+)\]", normalized, re.IGNORECASE)
            assert match
            self.rows = [(self.state["backups"][f"dbo.{match.group(1)}"],)]
        elif "OBJECT_ID(?, 'U')" in upper:
            self.rows = [(1 if parameters[0] in self.state["backups"] else 0,)]
        elif upper.startswith("SELECT * INTO"):
            match = re.search(r"INTO\s+\[dbo\]\.\[([^\]]+)\]", normalized, re.IGNORECASE)
            assert match
            self.state["backups"][f"dbo.{match.group(1)}"] = self.state["row_count"]
        elif upper.startswith("ALTER TABLE [DBO].[LOCATIONS] ADD"):
            match = re.search(r"\bADD\s+\[([^\]]+)\]", normalized, re.IGNORECASE)
            assert match
            name = match.group(1)
            spec = next(item for item in LOCATIONS_FEATURE_COLUMNS if item["name"] == name)
            self.state["columns"][name] = _approved_locations_column_metadata(spec)
        elif "SP_GETAPPLOCK" in upper:
            self.rows = [(0,)]
        elif upper.startswith("SET XACT_ABORT") or upper.startswith("SELECT TOP (0)"):
            pass
        else:
            raise AssertionError((sql, parameters))
        return self

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return list(self.rows)


class LocationsMigrationConnection:
    def __init__(self, state):
        self._cursor = LocationsMigrationCursor(state)
        self.state = state
        self.timeout = 0
        self.autocommit = False
        self.closed = False

    def cursor(self):
        return self._cursor

    def commit(self):
        self.state["commits"] += 1

    def rollback(self):
        self.state["rollbacks"] += 1

    def close(self):
        self.closed = True


def _approved_kit_column_metadata(spec):
    return (*_approved_locations_column_metadata(spec), 0)


class KitUpgradeCursor:
    timeout = 0
    rowcount = -1

    def __init__(self, state):
        self.state = state
        self.rows = []

    def execute(self, sql, parameters=None):
        parameters = list(parameters or [])
        self.state["commands"].append((sql, parameters))
        normalized = " ".join(str(sql).split())
        upper = normalized.upper()
        self.rows = []

        if upper == "SELECT DB_NAME()":
            self.rows = [(f"POS_{self.state['company_username']}",)]
        elif "FROM SYS.TABLES T JOIN SYS.SCHEMAS" in upper:
            self.rows = [(202, 0, 0)]
        elif "FROM SYS.TRIGGERS" in upper and "PARENT_CLASS = 0" in upper:
            self.rows = [(0,)]
        elif "HAS_PERMS_BY_NAME" in upper:
            self.rows = [(1,)]
        elif "FROM SYS.COLUMNS C JOIN SYS.TYPES" in upper:
            requested = {str(value).casefold() for value in parameters}
            self.rows = [
                tuple(metadata)
                for name, metadata in self.state["columns"].items()
                if name.casefold() in requested
            ]
        elif "CHECKSUM_AGG(BINARY_CHECKSUM" in upper:
            self.rows = [(self.state["row_count"], self.state["data_checksum"])]
        elif upper.startswith("SELECT COUNT_BIG(*) FROM (SELECT"):
            self.rows = [(0,)]
        elif upper.startswith("SELECT COUNT_BIG(*) FROM [DBO].[KIT] WHERE"):
            self.rows = [(0,)]
        elif upper.startswith("SELECT COUNT_BIG(*) FROM [DBO].[KIT]"):
            self.rows = [(self.state["row_count"],)]
        elif upper.startswith("SELECT COUNT_BIG(*) FROM [DBO].[__CODEX_BAK_"):
            match = re.search(r"FROM\s+\[dbo\]\.\[([^\]]+)\]", normalized, re.IGNORECASE)
            assert match
            self.rows = [(self.state["backups"][f"dbo.{match.group(1)}"],)]
        elif "OBJECT_ID(?, 'U')" in upper:
            self.rows = [(1 if parameters[0] in self.state["backups"] else 0,)]
        elif upper.startswith("SELECT * INTO"):
            match = re.search(r"INTO\s+\[dbo\]\.\[([^\]]+)\]", normalized, re.IGNORECASE)
            assert match
            self.state["backups"][f"dbo.{match.group(1)}"] = self.state["row_count"]
        elif upper.startswith("ALTER TABLE [DBO].[KIT] ADD"):
            match = re.search(r"\bADD\s+\[([^\]]+)\]", normalized, re.IGNORECASE)
            assert match
            name = match.group(1)
            spec = next(item for item in KIT_UPGRADE_COLUMNS if item["name"] == name)
            self.state["columns"][name] = _approved_kit_column_metadata(spec)
        elif "SP_GETAPPLOCK" in upper:
            self.rows = [(0,)]
        elif upper.startswith("SET XACT_ABORT"):
            pass
        else:
            raise AssertionError((sql, parameters))
        return self

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return list(self.rows)


class KitUpgradeConnection:
    def __init__(self, state):
        self._cursor = KitUpgradeCursor(state)
        self.state = state
        self.timeout = 0
        self.closed = False

    def cursor(self):
        return self._cursor

    def commit(self):
        self.state["commits"] += 1

    def rollback(self):
        self.state["rollbacks"] += 1

    def close(self):
        self.closed = True


class LocationRegionCursor:
    timeout = 0
    rowcount = -1

    def __init__(self, state):
        self.state = state
        self.rows = []

    def execute(self, sql, parameters=None):
        parameters = list(parameters or [])
        self.state["commands"].append((sql, parameters))
        normalized = " ".join(str(sql).split())
        upper = normalized.upper()
        self.rows = []
        self.rowcount = -1

        if upper == "SELECT DB_NAME()":
            self.rows = [("POS_Kento",)]
        elif "SP_GETAPPLOCK" in upper:
            self.rows = [(0,)]
        elif upper.startswith("SELECT [LOCATIONID],[REGIONID] FROM [DBO].[LOCATIONS]"):
            if int(parameters[0]) == self.state["location_id"]:
                self.rows = [
                    (self.state["location_id"], self.state["region_id"])
                ]
        elif upper.startswith(
            "SELECT [LOCATIONID],[REGIONID],[LOCATIONMANAGEREMPLOYEEID] FROM [DBO].[LOCATIONS]"
        ):
            if int(parameters[0]) == self.state["location_id"]:
                self.rows = [
                    (
                        self.state["location_id"],
                        self.state["region_id"],
                        self.state["manager_employee_id"],
                    )
                ]
        elif "FROM SYS.TABLES T JOIN SYS.SCHEMAS" in upper:
            self.rows = [(0, 0)]
        elif "HAS_PERMS_BY_NAME" in upper:
            self.rows = [(1,)]
        elif upper.startswith("SELECT COUNT_BIG(*) FROM [DBO].[REGIONS]"):
            self.rows = [
                (1 if int(parameters[0]) in self.state["valid_regions"] else 0,)
            ]
        elif "FROM SYS.TRIGGERS TR JOIN SYS.SQL_MODULES" in upper:
            self.rows = list(self.state["triggers"])
        elif "OBJECT_ID(?, 'U')" in upper:
            self.rows = [
                (1 if parameters[0] in self.state["backups"] else 0,)
            ]
        elif upper.startswith("SELECT * INTO"):
            match = re.search(
                r"INTO\s+\[dbo\]\.\[([^\]]+)\]",
                normalized,
                re.IGNORECASE,
            )
            assert match
            self.state["backups"][f"dbo.{match.group(1)}"] = self.state[
                "row_count"
            ]
        elif upper.startswith("SELECT COUNT_BIG(*) FROM [DBO].[LOCATIONS]"):
            self.rows = [(self.state["row_count"],)]
        elif upper.startswith("SELECT COUNT_BIG(*) FROM [DBO].[__CODEX_BAK_"):
            match = re.search(
                r"FROM\s+\[dbo\]\.\[([^\]]+)\]",
                normalized,
                re.IGNORECASE,
            )
            assert match
            self.rows = [
                (self.state["backups"][f"dbo.{match.group(1)}"],)
            ]
        elif upper.startswith(
            "UPDATE [DBO].[LOCATIONS] SET [REGIONID]=? WHERE [LOCATIONID]=?"
        ):
            assert int(parameters[1]) == self.state["location_id"]
            self.state["region_id"] = int(parameters[0])
            self.rowcount = 1
        elif upper.startswith(
            "UPDATE [DBO].[LOCATIONS] SET [LOCATIONMANAGEREMPLOYEEID]=0 "
            "WHERE [LOCATIONID]=? AND [LOCATIONMANAGEREMPLOYEEID]=1 AND [REGIONID]=?"
        ):
            if (
                int(parameters[0]) == self.state["location_id"]
                and int(parameters[1]) == self.state["region_id"]
                and self.state["manager_employee_id"] == 1
            ):
                self.state["manager_employee_id"] = 0
                self.rowcount = 1
        elif upper.startswith("SET XACT_ABORT"):
            pass
        else:
            raise AssertionError((sql, parameters))
        return self

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return list(self.rows)


class LocationRegionConnection:
    def __init__(self, state):
        self._cursor = LocationRegionCursor(state)
        self.state = state
        self.timeout = 0
        self.autocommit = False

    def cursor(self):
        return self._cursor

    def commit(self):
        self.state["commits"] += 1

    def rollback(self):
        self.state["rollbacks"] += 1

    def close(self):
        pass


class LocationLayawayCursor:
    timeout = 0
    rowcount = -1

    def __init__(self, state):
        self.state = state
        self.rows = []

    def execute(self, sql, parameters=None):
        parameters = list(parameters or [])
        self.state["commands"].append((sql, parameters))
        normalized = " ".join(str(sql).split())
        upper = normalized.upper()
        self.rows = []
        self.rowcount = -1

        if upper == "SELECT DB_NAME()":
            self.rows = [("POS_Kento",)]
        elif "SP_GETAPPLOCK" in upper:
            self.rows = [(0,)]
        elif "FROM SYS.TABLES T JOIN SYS.SCHEMAS" in upper:
            self.rows = [(0, 0)]
        elif "HAS_PERMS_BY_NAME" in upper:
            self.rows = [(1,)]
        elif upper.startswith("SELECT COUNT_BIG(*) FROM SYS.TRIGGERS"):
            self.rows = [(self.state.get("trigger_count", 0),)]
        elif "FROM SYS.COLUMNS C JOIN SYS.TYPES" in upper:
            self.rows = [
                ("Locations_LayawaysID", "int", 4, 0, 1, 0, 0, 0),
                ("LocationID", "int", 4, 0, 0, 0, 0, 0),
                ("ExpirationDay", "int", 4, 0, 0, 0, 0, 0),
                (
                    "IsChangeLayawayExpirationDate",
                    "bit",
                    1,
                    0,
                    0,
                    0,
                    0,
                    0,
                ),
                ("MinFirstPayment", "decimal", 9, 0, 0, 0, 0, 0),
                ("Disclaimer", "nvarchar", 400, 1, 0, 0, 0, 0),
            ]
        elif upper.startswith(
            "SELECT [LOCATIONID] FROM [DBO].[LOCATIONS] WITH (UPDLOCK, HOLDLOCK)"
        ):
            requested = {int(value) for value in parameters}
            self.rows = [
                (value,)
                for value in sorted(self.state["locations"])
                if value in requested
            ]
        elif upper.startswith(
            "SELECT [LOCATIONID],[EXPIRATIONDAY],[ISCHANGELAYAWAYEXPIRATIONDATE],"
            "[MINFIRSTPAYMENT],[DISCLAIMER] FROM [DBO].[LOCATIONS_LAYAWAYS]"
        ):
            requested = {int(value) for value in parameters}
            self.rows = []
            for location_id in sorted(requested):
                row = self.state["settings"].get(location_id)
                if row is not None:
                    self.rows.append(
                        (
                            location_id,
                            row["expirationDay"],
                            row["isChangeLayawayExpirationDate"],
                            row["minFirstPayment"],
                            row["disclaimer"],
                        )
                    )
        elif "OBJECT_ID(?, 'U')" in upper:
            self.rows = [
                (1 if parameters[0] in self.state["backups"] else 0,)
            ]
        elif upper.startswith("SELECT * INTO"):
            match = re.search(
                r"INTO\s+\[dbo\]\.\[([^\]]+)\]",
                normalized,
                re.IGNORECASE,
            )
            assert match
            self.state["backups"][f"dbo.{match.group(1)}"] = len(
                self.state["settings"]
            )
        elif upper.startswith(
            "SELECT COUNT_BIG(*) FROM [DBO].[LOCATIONS_LAYAWAYS]"
        ):
            self.rows = [(len(self.state["settings"]),)]
        elif upper.startswith("SELECT COUNT_BIG(*) FROM [DBO].[__CODEX_BAK_"):
            match = re.search(
                r"FROM\s+\[dbo\]\.\[([^\]]+)\]",
                normalized,
                re.IGNORECASE,
            )
            assert match
            self.rows = [
                (self.state["backups"][f"dbo.{match.group(1)}"],)
            ]
        elif upper.startswith("UPDATE [DBO].[LOCATIONS_LAYAWAYS] SET"):
            location_id = int(parameters[4])
            if location_id in self.state["settings"]:
                self.state["settings"][location_id] = {
                    "expirationDay": int(parameters[0]),
                    "isChangeLayawayExpirationDate": int(parameters[1]),
                    "minFirstPayment": int(parameters[2]),
                    "disclaimer": str(parameters[3]),
                }
                self.rowcount = 1
        elif upper.startswith("INSERT INTO [DBO].[LOCATIONS_LAYAWAYS]"):
            location_id = int(parameters[4])
            if location_id not in self.state["settings"]:
                self.state["settings"][location_id] = {
                    "expirationDay": int(parameters[0]),
                    "isChangeLayawayExpirationDate": int(parameters[1]),
                    "minFirstPayment": int(parameters[2]),
                    "disclaimer": str(parameters[3]),
                }
                self.rowcount = 1
        elif upper.startswith("SET XACT_ABORT"):
            pass
        else:
            raise AssertionError((sql, parameters))
        return self

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return list(self.rows)


class LocationLayawayConnection:
    def __init__(self, state):
        self._cursor = LocationLayawayCursor(state)
        self.state = state
        self.timeout = 0
        self.autocommit = False

    def cursor(self):
        return self._cursor

    def commit(self):
        self.state["commits"] += 1

    def rollback(self):
        self.state["rollbacks"] += 1

    def close(self):
        pass


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE dbo.Invoices SET Total = 0",
        "SELECT * INTO dbo.Copy FROM dbo.Invoices",
        "SELECT * FROM master.dbo.sysdatabases",
        "SELECT 1; SELECT 2",
        "EXEC dbo.DoSomething",
        "SELECT * FROM OPENROWSET('x', 'y', 'z')",
        "SELECT 1 -- hidden operation",
    ],
)
def test_read_validator_rejects_writes_external_access_and_multiple_statements(sql):
    with pytest.raises(NovaSqlScopeError):
        _validated_select(sql)


def test_read_omits_protected_columns_and_caps_rows():
    connection = FakeConnection(
        FakeCursor(
            description=["InvoiceID", "EmployeePassword", "Label"],
            rows=[(1, "secret", "first"), (2, "secret", "second")],
        )
    )
    client = ScopedNovaSqlClient(
        FakeSalesforce(),
        connect_factory=lambda _connection_string: connection,
        drivers_factory=lambda: ["ODBC Driver 18 for SQL Server"],
    )

    result = client.read("Kento", "SELECT InvoiceID, EmployeePassword, Label FROM dbo.Invoices", max_rows=1)

    assert result["columns"] == ["InvoiceID", "Label"]
    assert result["rows"] == [{"InvoiceID": 1, "Label": "first"}]
    assert result["protectedColumnsOmitted"] == 1
    assert result["truncated"] is True
    assert connection.closed is True


def test_taylor_cross_account_read_is_target_bound_and_omits_secrets(tmp_path):
    username_file = tmp_path / "developer-username"
    password_file = tmp_path / "developer-password"
    username_file.write_text("developer", encoding="utf-8")
    password_file.write_text("password", encoding="utf-8")
    cursor = DataMoveReadCursor()
    connection = FakeConnection(cursor)
    connection.autocommit = True
    connection_strings = []

    def connect(connection_string):
        connection_strings.append(connection_string)
        return connection

    client = ScopedNovaSqlClient(
        FakeSalesforce(),
        settings=NovaSqlSettings(
            developer_username_file=str(username_file),
            developer_password_file=str(password_file),
        ),
        connect_factory=connect,
        drivers_factory=lambda: ["ODBC Driver 18 for SQL Server"],
        write_enabled=True,
        write_state_dir=tmp_path,
    )

    result = client.data_move_read(
        target_company_username="Target_Account",
        source_company_usernames=["Source_Account"],
        sql=(
            "SELECT COUNT_BIG(*) CandidateCount, MAX(s.ApiPassword) ApiPassword "
            "FROM POS_Source_Account.dbo.Products AS s"
        ),
        max_rows=1,
    )

    assert result["targetDatabase"] == "POS_Target_Account"
    assert result["sourceCompanyUsernames"] == ["Source_Account"]
    assert result["sourceDatabasesReadOnly"] is True
    assert result["columns"] == ["CandidateCount"]
    assert result["rows"] == [{"CandidateCount": 101}]
    assert result["protectedColumnsOmitted"] == 1
    assert "DATABASE=POS_Target_Account" in connection_strings[0]
    assert "ApplicationIntent=ReadOnly" in connection_strings[0]
    assert connection.autocommit is False
    assert connection.closed is True


def test_preflight_requires_exact_database_binding():
    connection = FakeConnection(
        FakeCursor(description=["DatabaseName", "TableCount", "ViewCount"], rows=[("POS_Kento", 42, 3)])
    )
    client = ScopedNovaSqlClient(
        FakeSalesforce(),
        connect_factory=lambda _connection_string: connection,
        drivers_factory=lambda: ["ODBC Driver 18 for SQL Server"],
    )

    result = client.preflight("Kento")

    assert result == {
        "ok": True,
        "accessMode": "bounded_read_only",
        "companyUsername": "Kento",
        "databaseName": "POS_Kento",
        "tableCount": 42,
        "viewCount": 3,
    }


def test_billing_locations_is_fixed_authoritative_projection():
    connection = FakeConnection(
        FakeCursor(
            description=[
                "LocationID",
                "LocationName",
                "LocationManagerEmployeeID",
            ],
            rows=[
                (1, "Main Store", 0),
                (2, "Storage Back Room", 0),
                (3, "Closed Shop", 1),
            ],
        )
    )
    client = ScopedNovaSqlClient(
        FakeSalesforce(),
        connect_factory=lambda _connection_string: connection,
        drivers_factory=lambda: ["ODBC Driver 18 for SQL Server"],
    )

    result = client.billing_locations("Kento")

    assert result["sourceSystem"] == "Nova BillingAutomation"
    assert result["sourceTable"] == "dbo.Locations"
    assert result["activeNonStorageLocationIds"] == [1]
    assert result["activeNonStorageCount"] == 1
    assert result["locations"][1]["isStorage"] is True
    assert result["locations"][2]["status"] == "Inactive"
    assert result["arbitrarySqlExposed"] is False
    assert connection.closed is True


def test_invoice_spare_investigation_reconstructs_approval_and_duplicate_signature():
    cursor = InvoiceSpareCursor()
    connection = FakeConnection(cursor)
    connection_strings = []
    client = ScopedNovaSqlClient(
        FakeSalesforce(),
        connect_factory=lambda value: connection_strings.append(value) or connection,
        drivers_factory=lambda: ["ODBC Driver 18 for SQL Server"],
    )

    result = client.invoice_spare_investigation("Divinity_Investments_LLC", 12643)

    assert result["operation"] == INVOICE_SPARE_INVESTIGATION
    assert result["accessMode"] == "fixed_deep_read_only"
    assert result["relatedInvoiceIds"] == [12642, 12643]
    source, child = result["invoices"]
    assert source["grossProducts"] == "3710.00"
    assert source["quantityAwareLineDiscount"] == "150.00"
    assert source["netProducts"] == "3560.00"
    assert source["paymentTotal"] == "3560.00"
    assert source["paymentMatchesInvoiceTotal"] is True
    assert child["grossProducts"] == "15524.00"
    assert child["quantityAwareLineDiscount"] == "15524.00"
    assert child["netProducts"] == "0.00"
    assert child["paymentTotal"] == "0.00"
    assert child["paymentMatchesInvoiceTotal"] is True

    relationship = result["spareRelationship"]
    assert relationship["attachedSourceInvoiceId"] == 12642
    assert relationship["approvalArithmetic"] == {
        "ownSpare": "-2447.98",
        "attachedSpare": "2810.00",
        "result": "362.02",
        "wouldPass": True,
    }
    assert relationship["currentMinimumSnapshotGap"] == "1800.00"
    assert relationship["minimumGapCandidates"][0]["products"] == [
        {
            "productId": 359,
            "productName": "RF FACE",
            "quantity": 6,
            "currentEffectiveMinimumPrice": "300",
        }
    ]
    assert relationship["sourceExpectedSpareAfterOneFullTransfer"] == "0.00"
    assert relationship["sourceObservedStoredSpare"] == "-2810"
    assert relationship["duplicateFullSourceDeductionSignature"] is True
    assert result["writesPerformed"] is False
    assert result["arbitrarySqlExposed"] is False
    assert result["protectedColumnsReturned"] is False
    assert "ApplicationIntent=ReadOnly" in connection_strings[0]
    assert connection.closed is True
    assert cursor.commands
    assert all(command.lstrip().upper().startswith("SELECT") for command, _ in cursor.commands)
    assert all("SELECT *" not in command.upper() for command, _ in cursor.commands)


def test_invoice_spare_investigation_is_reported_by_capability_discovery():
    client = ScopedNovaSqlClient(
        FakeSalesforce(),
        connect_factory=lambda _value: FakeConnection(InvoiceSpareCursor()),
        drivers_factory=lambda: ["ODBC Driver 18 for SQL Server"],
    )

    assert INVOICE_SPARE_INVESTIGATION in client.capability_status()[
        "allowedReadOperations"
    ]


def test_invoice_spare_investigation_requires_existing_positive_invoice():
    cursor = InvoiceSpareCursor(missing_root=True)
    connection = FakeConnection(cursor)
    client = ScopedNovaSqlClient(
        FakeSalesforce(),
        connect_factory=lambda _value: connection,
        drivers_factory=lambda: ["ODBC Driver 18 for SQL Server"],
    )

    with pytest.raises(NovaSqlScopeError):
        client.invoice_spare_investigation("Divinity_Investments_LLC", 0)

    with pytest.raises(NovaSqlUnavailableError, match="invoice was not found"):
        client.invoice_spare_investigation("Divinity_Investments_LLC", 999999)


def test_api_customer_email_cohort_has_fixed_database_columns_and_no_sql_input(tmp_path):
    credential_file = tmp_path / "api-cohort.json"
    credential_file.write_text(
        '{"username":"nova_taylor_api_cohort_ro","password":"test-only-password"}',
        encoding="utf-8",
    )
    cursor = ApiCohortCursor()
    connection = FakeConnection(cursor)
    connection_strings = []
    salesforce = ApiCohortSalesforce()
    client = ScopedNovaSqlClient(
        salesforce,
        NovaSqlSettings(api_cohort_credential_file=str(credential_file)),
        connect_factory=lambda connection_string: connection_strings.append(connection_string) or connection,
        drivers_factory=lambda: ["ODBC Driver 18 for SQL Server"],
    )

    result = client.api_customer_email_cohort()

    assert result["sourceDatabase"] == "POS_Main"
    assert result["sourceTable"] == "dbo.users"
    assert result["sourceColumns"] == ["Username", "DatabaseName", "ApiExpirationDate"]
    assert result["writesExposed"] is False
    assert result["arbitrarySqlExposed"] is False
    assert result["emailSent"] is False
    assert salesforce.received[0]["companyUsername"] == "Kento"
    assert "DATABASE=POS_Main" in connection_strings[0]
    assert "ApplicationIntent=ReadOnly" in connection_strings[0]
    query = cursor.commands[1]
    assert "ApiExpirationDate > SYSUTCDATETIME()" in query
    assert "UserPassword" not in query
    assert "ApiPassword" not in query
    assert "ApiRefreshToken" not in query
    assert not re.search(r"\b(?:insert|update|delete|merge|execute|exec)\b", query, re.IGNORECASE)
    assert connection.closed is True


def _write_plan(statements, **overrides):
    values = {
        "company_username": "Platinum_Beauty_Pte_Ltd",
        "statements": statements,
        "verification_sql": "SELECT COUNT_BIG(*) FROM dbo.Customers WHERE LocationID = 0",
        "verification_parameters": [],
        "expected_affected_rows": 477,
        "expected_verification_value": 0,
        "idempotency_key": "platinum-477-location-v1",
    }
    values.update(overrides)
    return _validated_write_plan(**values)


def test_guarded_write_plan_allows_temp_mapping_and_where_bounded_update():
    statements = [
        {"sql": "CREATE TABLE #mapping (CustomerID int NOT NULL, LocationID int NOT NULL)"},
        {"sql": "INSERT INTO #mapping (CustomerID, LocationID) VALUES (?, ?)", "parameters": [1, 3]},
        {
            "sql": (
                "UPDATE c SET LocationID = m.LocationID "
                "FROM dbo.Customers AS c JOIN #mapping AS m ON m.CustomerID = c.CustomerID "
                "WHERE c.LocationID = 0"
            )
        },
    ]

    first = _write_plan(statements)
    second = _write_plan(statements)

    assert first.target_operations == {"dbo.Customers": ("update",)}
    assert first.plan_hash == second.plan_hash
    assert len(first.plan_hash) == 64


def test_guarded_write_plan_allows_permanent_insert_with_explicit_columns():
    plan = _write_plan(
        [{"sql": "INSERT INTO dbo.CustomerFlags (CustomerID, FlagID) VALUES (?, ?)", "parameters": [7, 2]}],
        expected_affected_rows=1,
        verification_sql="SELECT COUNT_BIG(*) FROM dbo.CustomerFlags WHERE CustomerID = ? AND FlagID = ?",
        verification_parameters=[7, 2],
        expected_verification_value=1,
        idempotency_key="customer-flag-insert-v1",
    )

    assert plan.target_operations == {"dbo.CustomerFlags": ("insert",)}


def test_guarded_write_plan_allows_dbo_table_column_qualification():
    plan = _write_plan(
        [
            {
                "sql": (
                    "UPDATE dbo.Customers SET LocationID=? "
                    "WHERE dbo.Customers.CustomerID=?"
                ),
                "parameters": [3, 7],
            }
        ],
        expected_affected_rows=1,
    )

    assert plan.target_operations == {"dbo.Customers": ("update",)}


def test_guarded_write_plan_allows_set_based_cross_account_ranges_and_upsert():
    statements = [
        {
            "sql": (
                "UPDATE t SET ProductName = s.ProductName "
                "FROM dbo.Products AS t "
                "JOIN POS_Source_Account.dbo.Products AS s "
                "ON s.ProductID = t.ProductID "
                "WHERE s.ProductID BETWEEN ? AND ?"
            ),
            "parameters": [100, 200],
        },
        {
            "sql": (
                "INSERT INTO dbo.Products (ProductID, ProductName) "
                "SELECT s.ProductID, s.ProductName "
                "FROM POS_Source_Account.dbo.Products AS s "
                "WHERE s.ProductID BETWEEN ? AND ? "
                "AND NOT EXISTS (SELECT 1 FROM dbo.Products AS t "
                "WHERE t.ProductID = s.ProductID)"
            ),
            "parameters": [100, 200],
            "identity_insert": True,
        },
    ]

    plan = _write_plan(
        statements,
        company_username="Target_Account",
        source_company_usernames=["Source_Account"],
        expected_affected_rows=25_000,
        verification_sql=(
            "SELECT COUNT_BIG(*) FROM dbo.Products AS t "
            "JOIN POS_Source_Account.dbo.Products AS s "
            "ON s.ProductID=t.ProductID WHERE s.ProductID BETWEEN ? AND ?"
        ),
        verification_parameters=[100, 200],
        expected_verification_value=101,
        idempotency_key="cross-account-product-upsert-v1",
    )

    assert plan.source_company_usernames == ("Source_Account",)
    assert plan.target_operations == {
        "dbo.Products": ("insert", "update"),
    }
    assert plan.identity_insert_targets == ("dbo.Products",)
    assert plan.maximum_affected_rows == 100_000_000


@pytest.mark.parametrize(
    "statements,sources",
    [
        (
            [
                {
                    "sql": (
                        "INSERT INTO dbo.Products (ProductID) "
                        "SELECT ProductID FROM POS_Unlisted.dbo.Products"
                    )
                }
            ],
            ["Source_Account"],
        ),
        (
            [
                {
                    "sql": (
                        "UPDATE s SET ProductName='changed' "
                        "FROM POS_Source_Account.dbo.Products AS s "
                        "WHERE s.ProductID=1"
                    )
                }
            ],
            ["Source_Account"],
        ),
        (
            [
                {
                    "sql": (
                        "INSERT INTO POS_Source_Account.dbo.Products (ProductID) "
                        "VALUES (1)"
                    )
                }
            ],
            ["Source_Account"],
        ),
    ],
)
def test_cross_account_plan_rejects_unlisted_reads_and_every_source_write(
    statements,
    sources,
):
    with pytest.raises(NovaSqlScopeError):
        _write_plan(
            statements,
            company_username="Target_Account",
            source_company_usernames=sources,
            expected_affected_rows=1,
        )


def test_cross_account_plan_rejects_target_as_source_and_local_plan_cross_read():
    with pytest.raises(NovaSqlScopeError, match="must differ"):
        _write_plan(
            [
                {
                    "sql": (
                        "INSERT INTO dbo.Products (ProductID) "
                        "SELECT ProductID FROM POS_Target_Account.dbo.Products"
                    )
                }
            ],
            company_username="Target_Account",
            source_company_usernames=["Target_Account"],
            expected_affected_rows=1,
        )

    with pytest.raises(NovaSqlScopeError, match="explicitly previewed"):
        _write_plan(
            [
                {
                    "sql": (
                        "INSERT INTO dbo.Products (ProductID) "
                        "SELECT ProductID FROM POS_Source_Account.dbo.Products"
                    )
                }
            ],
            company_username="Target_Account",
            expected_affected_rows=1,
        )


def test_identity_insert_is_allowed_only_for_permanent_insert():
    with pytest.raises(NovaSqlScopeError, match="only for an INSERT"):
        _write_plan(
            [
                {
                    "sql": (
                        "UPDATE dbo.Products SET ProductName=? "
                        "WHERE ProductID=?"
                    ),
                    "parameters": ["Rose", 1],
                    "identity_insert": True,
                }
            ],
            expected_affected_rows=1,
        )


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM dbo.Customers WHERE CustomerID = 1",
        "DROP TABLE dbo.Customers",
        "TRUNCATE TABLE dbo.Customers",
        "ALTER TABLE dbo.Customers ADD Unsafe bit",
        "MERGE INTO dbo.Customers AS c USING #mapping AS m ON c.CustomerID=m.CustomerID WHEN MATCHED THEN UPDATE SET LocationID=m.LocationID",
        "UPDATE dbo.Customers SET LocationID = 3",
        "INSERT INTO dbo.Customers VALUES (1, 3)",
        "CREATE TABLE dbo.Backdoor (ID int)",
        "CREATE TABLE ##global (ID int)",
        "UPDATE otherdb.dbo.Customers SET LocationID = 3 WHERE CustomerID = 1",
        "UPDATE dbo.Customers SET LocationID = 3 WHERE CustomerID = 1; UPDATE dbo.Customers SET LocationID = 4 WHERE CustomerID = 2",
        "EXEC sp_executesql N'UPDATE dbo.Customers SET LocationID=3 WHERE CustomerID=1'",
    ],
)
def test_guarded_write_plan_rejects_destructive_unbounded_or_out_of_scope_sql(sql):
    with pytest.raises(NovaSqlScopeError):
        _write_plan([{"sql": sql}], expected_affected_rows=1)


def test_write_executor_is_disabled_outside_taylor_lane():
    client = ScopedNovaSqlClient(FakeSalesforce(), write_enabled=False)

    with pytest.raises(NovaSqlScopeError, match="only to coding_agent"):
        client.preview_write(
            company_username="Platinum_Beauty_Pte_Ltd",
            statements=[{"sql": "UPDATE dbo.Customers SET LocationID = 3 WHERE CustomerID = 1"}],
            verification_sql="SELECT COUNT_BIG(*) FROM dbo.Customers WHERE CustomerID = 1 AND LocationID = 3",
            expected_affected_rows=1,
            expected_verification_value=1,
            idempotency_key="disabled-lane-test-v1",
        )


class TargetPreviewCursor:
    def __init__(self, trigger_name="tr_Locations_FixZero", trigger_definition=None):
        self.trigger_name = trigger_name
        self.trigger_definition = trigger_definition or LOCATION_REGION_SAFE_TRIGGER_DEFINITION
        self.rows = []

    def execute(self, sql, parameters=None):
        normalized = " ".join(str(sql).split()).upper()
        parameters = list(parameters or [])
        if "CREATE TABLE" in normalized and "HAS_PERMS_BY_NAME" in normalized:
            self.rows = [(1,)]
        elif "FROM SYS.TABLES T JOIN SYS.SCHEMAS" in normalized:
            is_locations = str(parameters[1]).casefold() == "locations"
            self.rows = [(101 if is_locations else 102, 0, 1 if is_locations else 0, 0)]
        elif "FROM SYS.TRIGGERS TR JOIN SYS.SQL_MODULES" in normalized:
            self.rows = [(self.trigger_name, self.trigger_definition)]
        elif "HAS_PERMS_BY_NAME" in normalized:
            self.rows = [(1,)]
        elif "FROM SYS.COLUMNS" in normalized:
            self.rows = [(1,)]
        elif normalized.startswith("SELECT COUNT_BIG(*) FROM"):
            self.rows = [(5,)]
        else:
            raise AssertionError((sql, parameters))
        return self

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return list(self.rows)


def _locations_and_logs_plan():
    return _write_plan(
        [
            {
                "sql": "UPDATE dbo.Locations SET LocationName=? WHERE LocationID=?",
                "parameters": ["Store", 1],
            },
            {
                "sql": "INSERT INTO dbo.Logs (LogID) SELECT ? WHERE ?=1",
                "parameters": [-1, 0],
            },
        ],
        expected_affected_rows=1,
        verification_sql="SELECT COUNT_BIG(*) FROM dbo.Locations WHERE LocationID=?",
        verification_parameters=[1],
        expected_verification_value=1,
        idempotency_key="locations-trigger-backed-side-effect-v1",
    )


def test_guarded_preview_allows_only_reviewed_locations_trigger_with_logs_backup():
    targets = _preview_target_tables(TargetPreviewCursor(), _locations_and_logs_plan())

    locations = next(item for item in targets if item["table"] == "dbo.Locations")
    logs = next(item for item in targets if item["table"] == "dbo.Logs")
    assert locations["enabledTriggerCount"] == 1
    assert logs["enabledTriggerCount"] == 0


def test_guarded_preview_rejects_reviewed_locations_trigger_without_logs_backup():
    plan = _write_plan(
        [
            {
                "sql": "UPDATE dbo.Locations SET LocationName=? WHERE LocationID=?",
                "parameters": ["Store", 1],
            }
        ],
        expected_affected_rows=1,
        verification_sql="SELECT COUNT_BIG(*) FROM dbo.Locations WHERE LocationID=?",
        verification_parameters=[1],
        expected_verification_value=1,
        idempotency_key="locations-trigger-unbacked-side-effect-v1",
    )

    with pytest.raises(NovaSqlScopeError, match="unbacked tables"):
        _preview_target_tables(TargetPreviewCursor(), plan)


def test_guarded_preview_rejects_changed_locations_trigger_even_with_logs_backup():
    with pytest.raises(NovaSqlScopeError, match="unbacked tables"):
        _preview_target_tables(
            TargetPreviewCursor(
                trigger_definition=LOCATION_REGION_SAFE_TRIGGER_DEFINITION.replace(
                    "SET NOCOUNT ON", "SET NOCOUNT OFF"
                )
            ),
            _locations_and_logs_plan(),
        )


def test_fixed_locations_migration_is_disabled_outside_taylor_lane():
    client = ScopedNovaSqlClient(FakeSalesforce(), write_enabled=False)

    with pytest.raises(NovaSqlScopeError, match="only to coding_agent"):
        client.preview_locations_feature_columns_migration(
            company_username="Kento",
            idempotency_key="locations-feature-disabled-v1",
        )


def test_fixed_location_region_update_backs_up_once_and_verifies_readback(tmp_path):
    state = {
        "location_id": 41,
        "region_id": 5,
        "valid_regions": {5, 6},
        "row_count": 3,
        "backups": {},
        "triggers": [
            ("tr_Locations_FixZero", LOCATION_REGION_SAFE_TRIGGER_DEFINITION)
        ],
        "commands": [],
        "commits": 0,
        "rollbacks": 0,
    }
    client = ScopedNovaSqlClient(
        FakeSalesforce(),
        connect_factory=lambda _connection_string: LocationRegionConnection(
            state
        ),
        drivers_factory=lambda: ["ODBC Driver 18 for SQL Server"],
        write_enabled=True,
        write_state_dir=tmp_path,
    )

    result = client.update_location_region(
        company_username="Kento",
        location_id=41,
        region_id=6,
        idempotency_key="location-region-kento-41-v1",
    )

    commands = [command for command, _ in state["commands"]]
    backup_index = next(
        index
        for index, command in enumerate(commands)
        if command.upper().startswith("SELECT * INTO")
    )
    update_index = next(
        index
        for index, command in enumerate(commands)
        if command.upper().startswith("UPDATE [DBO].[LOCATIONS]")
    )
    assert backup_index < update_index
    assert result["operation"] == LOCATION_REGION_UPDATE
    assert result["before"] == {"locationId": 41, "regionId": 5}
    assert result["readback"] == {"locationId": 41, "regionId": 6}
    assert result["backupTables"][0]["rowCount"] == 3
    assert result["transactionCommitted"] is True
    assert result["postCommitReadbackVerified"] is True
    assert result["arbitrarySqlAccepted"] is False
    assert state["commits"] == 1

    replay = client.update_location_region(
        company_username="Kento",
        location_id=41,
        region_id=6,
        idempotency_key="location-region-kento-41-v1",
    )
    assert replay["idempotentReplay"] is True
    assert sum(
        command.upper().startswith("UPDATE [DBO].[LOCATIONS]")
        for command, _ in state["commands"]
    ) == 1


def test_fixed_location_region_update_rejects_unreviewed_trigger_before_backup(
    tmp_path,
):
    state = {
        "location_id": 41,
        "region_id": 5,
        "valid_regions": {5, 6},
        "row_count": 3,
        "backups": {},
        "triggers": [
            (
                "tr_Unexpected",
                "CREATE TRIGGER tr_Unexpected ON Locations AFTER UPDATE AS "
                "BEGIN INSERT INTO Logs(ActionName) SELECT 'unexpected' END",
            )
        ],
        "commands": [],
        "commits": 0,
        "rollbacks": 0,
    }
    client = ScopedNovaSqlClient(
        FakeSalesforce(),
        connect_factory=lambda _connection_string: LocationRegionConnection(
            state
        ),
        drivers_factory=lambda: ["ODBC Driver 18 for SQL Server"],
        write_enabled=True,
        write_state_dir=tmp_path,
    )

    with pytest.raises(NovaSqlScopeError, match="outside the reviewed"):
        client.update_location_region(
            company_username="Kento",
            location_id=41,
            region_id=6,
            idempotency_key="location-region-trigger-reject-v1",
        )

    assert state["backups"] == {}
    assert state["region_id"] == 5
    assert state["commits"] == 0


def test_fixed_location_reactivation_backs_up_once_and_verifies_readback(tmp_path):
    state = {
        "location_id": 1,
        "region_id": 5,
        "manager_employee_id": 1,
        "valid_regions": {5},
        "row_count": 3,
        "backups": {},
        "triggers": [
            ("tr_Locations_FixZero", LOCATION_REGION_SAFE_TRIGGER_DEFINITION)
        ],
        "commands": [],
        "commits": 0,
        "rollbacks": 0,
    }
    client = ScopedNovaSqlClient(
        FakeSalesforce(),
        connect_factory=lambda _connection_string: LocationRegionConnection(state),
        drivers_factory=lambda: ["ODBC Driver 18 for SQL Server"],
        write_enabled=True,
        write_state_dir=tmp_path,
    )

    result = client.update_location_reactivation(
        company_username="Kento",
        location_id=1,
        idempotency_key="location-reactivation-kento-1-v1",
    )

    commands = [command for command, _ in state["commands"]]
    backup_index = next(
        index
        for index, command in enumerate(commands)
        if command.upper().startswith("SELECT * INTO")
    )
    update_index = next(
        index
        for index, command in enumerate(commands)
        if "SET [LOCATIONMANAGEREMPLOYEEID]=0" in command.upper()
    )
    assert backup_index < update_index
    assert result["operation"] == LOCATION_REACTIVATION_UPDATE
    assert result["before"] == {
        "locationId": 1,
        "regionId": 5,
        "locationManagerEmployeeId": 1,
    }
    assert result["readback"] == {
        "locationId": 1,
        "regionId": 5,
        "locationManagerEmployeeId": 0,
    }
    assert result["backupTables"][0]["rowCount"] == 3
    assert result["transactionCommitted"] is True
    assert result["postCommitReadbackVerified"] is True
    assert result["arbitrarySqlAccepted"] is False
    assert state["commits"] == 1

    replay = client.update_location_reactivation(
        company_username="Kento",
        location_id=1,
        idempotency_key="location-reactivation-kento-1-v1",
    )
    assert replay["idempotentReplay"] is True
    assert sum(
        "SET [LOCATIONMANAGEREMPLOYEEID]=0" in command.upper()
        for command, _ in state["commands"]
    ) == 1


def test_fixed_location_reactivation_rejects_nonstandard_start_value(tmp_path):
    state = {
        "location_id": 1,
        "region_id": 5,
        "manager_employee_id": 7,
        "valid_regions": {5},
        "row_count": 3,
        "backups": {},
        "triggers": [
            ("tr_Locations_FixZero", LOCATION_REGION_SAFE_TRIGGER_DEFINITION)
        ],
        "commands": [],
        "commits": 0,
        "rollbacks": 0,
    }
    client = ScopedNovaSqlClient(
        FakeSalesforce(),
        connect_factory=lambda _connection_string: LocationRegionConnection(state),
        drivers_factory=lambda: ["ODBC Driver 18 for SQL Server"],
        write_enabled=True,
        write_state_dir=tmp_path,
    )

    with pytest.raises(NovaSqlScopeError, match="exactly 1"):
        client.update_location_reactivation(
            company_username="Kento",
            location_id=1,
            idempotency_key="location-reactivation-invalid-start-v1",
        )

    assert state["backups"] == {}
    assert state["commits"] == 0


def test_fixed_location_layaway_enable_updates_inserts_backs_up_and_replays(tmp_path):
    state = {
        "locations": {1, 2},
        "settings": {
            1: {
                "expirationDay": 0,
                "isChangeLayawayExpirationDate": 1,
                "minFirstPayment": 5,
                "disclaimer": "Old terms",
            }
        },
        "backups": {},
        "commands": [],
        "commits": 0,
        "rollbacks": 0,
    }
    client = ScopedNovaSqlClient(
        FakeSalesforce(),
        connect_factory=lambda _connection_string: LocationLayawayConnection(state),
        drivers_factory=lambda: ["ODBC Driver 18 for SQL Server"],
        write_enabled=True,
        write_state_dir=tmp_path,
    )

    result = client.enable_location_layaways(
        company_username="Kento",
        location_ids=[2, 1],
        idempotency_key="ticket-347700-layaway-enable-v1",
    )

    assert result["operation"] == LOCATION_LAYAWAY_ENABLE
    assert result["locationIds"] == [1, 2]
    assert result["defaults"] == LOCATION_LAYAWAY_DEFAULTS
    assert result["affectedRows"] == 2
    assert result["transactionCommitted"] is True
    assert result["postCommitReadbackVerified"] is True
    assert result["arbitrarySqlAccepted"] is False
    assert result["backupTables"][0]["rowCount"] == 1
    assert state["settings"] == {
        1: dict(LOCATION_LAYAWAY_DEFAULTS),
        2: dict(LOCATION_LAYAWAY_DEFAULTS),
    }
    assert state["commits"] == 1
    mutation_count = sum(
        command.upper().startswith(("UPDATE ", "INSERT ", "SELECT * INTO"))
        for command, _ in state["commands"]
    )

    replay = client.enable_location_layaways(
        company_username="Kento",
        location_ids=[1, 2],
        idempotency_key="ticket-347700-layaway-enable-v1",
    )
    assert replay["idempotentReplay"] is True
    assert replay["readback"] == [
        {"locationId": 1, "enabled": True, **LOCATION_LAYAWAY_DEFAULTS},
        {"locationId": 2, "enabled": True, **LOCATION_LAYAWAY_DEFAULTS},
    ]
    assert sum(
        command.upper().startswith(("UPDATE ", "INSERT ", "SELECT * INTO"))
        for command, _ in state["commands"]
    ) == mutation_count


def test_fixed_location_layaway_enable_is_safe_no_op_when_defaults_match(tmp_path):
    state = {
        "locations": {1},
        "settings": {1: dict(LOCATION_LAYAWAY_DEFAULTS)},
        "backups": {},
        "commands": [],
        "commits": 0,
        "rollbacks": 0,
    }
    client = ScopedNovaSqlClient(
        FakeSalesforce(),
        connect_factory=lambda _connection_string: LocationLayawayConnection(state),
        drivers_factory=lambda: ["ODBC Driver 18 for SQL Server"],
        write_enabled=True,
        write_state_dir=tmp_path,
    )

    result = client.enable_location_layaways(
        company_username="Kento",
        location_ids=[1],
        idempotency_key="ticket-347701-layaway-enable-v1",
    )

    assert result["noOp"] is True
    assert result["affectedRows"] == 0
    assert result["transactionCommitted"] is False
    assert result["backupTables"] == []
    assert state["commits"] == 0
    assert not any(
        command.upper().startswith(("UPDATE ", "INSERT ", "SELECT * INTO"))
        for command, _ in state["commands"]
    )


def test_fixed_location_layaway_enable_rejects_missing_location_before_backup(tmp_path):
    state = {
        "locations": {1},
        "settings": {},
        "backups": {},
        "commands": [],
        "commits": 0,
        "rollbacks": 0,
    }
    client = ScopedNovaSqlClient(
        FakeSalesforce(),
        connect_factory=lambda _connection_string: LocationLayawayConnection(state),
        drivers_factory=lambda: ["ODBC Driver 18 for SQL Server"],
        write_enabled=True,
        write_state_dir=tmp_path,
    )

    with pytest.raises(NovaSqlScopeError, match="every location_id"):
        client.enable_location_layaways(
            company_username="Kento",
            location_ids=[1, 2],
            idempotency_key="ticket-347702-layaway-enable-v1",
        )

    assert not state["backups"]
    assert state["commits"] == 0


def test_fixed_location_layaway_enable_rejects_trigger_and_non_taylor_lane(tmp_path):
    state = {
        "locations": {1},
        "settings": {},
        "backups": {},
        "commands": [],
        "commits": 0,
        "rollbacks": 0,
        "trigger_count": 1,
    }
    client = ScopedNovaSqlClient(
        FakeSalesforce(),
        connect_factory=lambda _connection_string: LocationLayawayConnection(state),
        drivers_factory=lambda: ["ODBC Driver 18 for SQL Server"],
        write_enabled=True,
        write_state_dir=tmp_path,
    )
    with pytest.raises(NovaSqlScopeError, match="enabled DML trigger"):
        client.enable_location_layaways(
            company_username="Kento",
            location_ids=[1],
            idempotency_key="ticket-347703-layaway-enable-v1",
        )
    assert not state["backups"]

    disabled = ScopedNovaSqlClient(FakeSalesforce(), write_enabled=False)
    with pytest.raises(NovaSqlScopeError, match="only to coding_agent"):
        disabled.enable_location_layaways(
            company_username="Kento",
            location_ids=[1],
            idempotency_key="ticket-347704-layaway-enable-v1",
        )


def test_fixed_locations_migration_backs_up_before_exact_alters_and_is_idempotent(tmp_path):
    state = {
        "columns": {},
        "row_count": 14,
        "backups": {},
        "commands": [],
        "commits": 0,
        "rollbacks": 0,
    }
    client = ScopedNovaSqlClient(
        FakeSalesforce(),
        connect_factory=lambda _connection_string: LocationsMigrationConnection(state),
        drivers_factory=lambda: ["ODBC Driver 18 for SQL Server"],
        write_enabled=True,
        write_state_dir=tmp_path,
    )

    preview = client.preview_locations_feature_columns_migration(
        company_username="Kento",
        idempotency_key="locations-feature-kento-v1",
    )

    expected_names = [str(spec["name"]) for spec in LOCATIONS_FEATURE_COLUMNS]
    assert preview["operation"] == LOCATIONS_FEATURE_MIGRATION
    assert preview["missingColumns"] == expected_names
    assert preview["expectedColumns"] == [
        {"name": "SessionIdleTime", "sqlType": "INT", "nullable": True},
        {"name": "IsSurchargeEnabled", "sqlType": "BIT", "nullable": True},
        {"name": "SurchargePercentage", "sqlType": "DECIMAL(5,2)", "nullable": True},
        {"name": "SurchargeLabel", "sqlType": "VARCHAR(20)", "nullable": True},
        {"name": "locale_code", "sqlType": "NVARCHAR(10)", "nullable": True},
    ]
    assert preview["backupRequired"] is True
    assert preview["sourceRowCount"] == 14
    assert preview["arbitrarySqlAccepted"] is False
    assert not any(command.upper().startswith("ALTER TABLE") for command, _ in state["commands"])

    result = client.execute_locations_feature_columns_migration(
        company_username="Kento",
        idempotency_key="locations-feature-kento-v1",
        preview_hash=preview["planHash"],
    )

    commands = [command for command, _ in state["commands"]]
    backup_index = next(index for index, command in enumerate(commands) if command.upper().startswith("SELECT * INTO"))
    alter_indexes = [index for index, command in enumerate(commands) if command.upper().startswith("ALTER TABLE")]
    assert len(alter_indexes) == 5
    assert backup_index < min(alter_indexes)
    assert [commands[index] for index in alter_indexes] == [
        f"ALTER TABLE [dbo].[Locations] ADD {spec['ddl']}" for spec in LOCATIONS_FEATURE_COLUMNS
    ]
    assert result["columnsAdded"] == expected_names
    assert [column["name"] for column in result["verifiedColumns"]] == expected_names
    assert result["backupTables"][0]["rowCount"] == 14
    assert result["transactionCommitted"] is True
    assert result["postCommitReadbackVerified"] is True
    assert result["arbitrarySqlAccepted"] is False
    assert state["commits"] == 1

    command_count = len(state["commands"])
    replay = client.execute_locations_feature_columns_migration(
        company_username="Kento",
        idempotency_key="locations-feature-kento-v1",
        preview_hash=preview["planHash"],
    )
    assert replay["idempotentReplay"] is True
    assert len(state["commands"]) == command_count


def test_fixed_locations_migration_rejects_conflicting_existing_column(tmp_path):
    state = {
        "columns": {
            "SessionIdleTime": (
                "SessionIdleTime",
                "bigint",
                8,
                19,
                0,
                1,
                0,
                0,
                0,
                0,
                0,
                0,
            )
        },
        "row_count": 1,
        "backups": {},
        "commands": [],
        "commits": 0,
        "rollbacks": 0,
    }
    client = ScopedNovaSqlClient(
        FakeSalesforce(),
        connect_factory=lambda _connection_string: LocationsMigrationConnection(state),
        drivers_factory=lambda: ["ODBC Driver 18 for SQL Server"],
        write_enabled=True,
        write_state_dir=tmp_path,
    )

    with pytest.raises(NovaSqlScopeError, match="does not match the approved definition"):
        client.preview_locations_feature_columns_migration(
            company_username="Kento",
            idempotency_key="locations-conflict-kento-v1",
        )


def test_fixed_locations_migration_is_safe_no_op_when_all_columns_already_match(tmp_path):
    state = {
        "columns": {
            str(spec["name"]): _approved_locations_column_metadata(spec)
            for spec in LOCATIONS_FEATURE_COLUMNS
        },
        "row_count": 5,
        "backups": {},
        "commands": [],
        "commits": 0,
        "rollbacks": 0,
    }
    client = ScopedNovaSqlClient(
        FakeSalesforce(),
        connect_factory=lambda _connection_string: LocationsMigrationConnection(state),
        drivers_factory=lambda: ["ODBC Driver 18 for SQL Server"],
        write_enabled=True,
        write_state_dir=tmp_path,
    )
    preview = client.preview_locations_feature_columns_migration(
        company_username="Kento",
        idempotency_key="locations-no-op-kento-v1",
    )

    assert preview["missingColumns"] == []
    assert preview["backupRequired"] is False
    result = client.execute_locations_feature_columns_migration(
        company_username="Kento",
        idempotency_key="locations-no-op-kento-v1",
        preview_hash=preview["planHash"],
    )

    assert result["noOp"] is True
    assert result["transactionCommitted"] is False
    assert result["backupTables"] == []
    assert state["commits"] == 0
    assert not any(
        command.upper().startswith(("SELECT * INTO", "ALTER TABLE"))
        for command, _ in state["commands"]
    )


def test_kit_upgrade_backs_up_adds_exact_columns_and_preserves_data(tmp_path):
    state = {
        "company_username": "Kento",
        "columns": {},
        "row_count": 1,
        "data_checksum": 347489,
        "backups": {},
        "commands": [],
        "commits": 0,
        "rollbacks": 0,
    }
    client = ScopedNovaSqlClient(
        FakeSalesforce(),
        connect_factory=lambda _connection_string: KitUpgradeConnection(state),
        drivers_factory=lambda: ["ODBC Driver 18 for SQL Server"],
        write_enabled=True,
        write_state_dir=tmp_path,
    )

    preview = client.preview_kit_upgrade(
        company_username="Kento",
        idempotency_key="kit-upgrade-kento-20260803-v1",
    )

    expected_names = [str(spec["name"]) for spec in KIT_UPGRADE_COLUMNS]
    assert preview["operation"] == KIT_UPGRADE_MIGRATION
    assert preview["companyUsername"] == "Kento"
    assert preview["missingColumns"] == expected_names
    assert preview["sourceRowCount"] == 1
    assert preview["sourceDataChecksum"] == 347489
    assert preview["fixedSchemaContract"] is True
    assert set(preview) >= {"planHash", "expectedColumns", "backupTable"}
    assert not any(command.upper().startswith("ALTER TABLE") for command, _ in state["commands"])

    result = client.execute_kit_upgrade(
        company_username="Kento",
        idempotency_key="kit-upgrade-kento-20260803-v1",
        preview_hash=preview["planHash"],
    )

    commands = [command for command, _ in state["commands"]]
    backup_index = next(index for index, command in enumerate(commands) if command.upper().startswith("SELECT * INTO"))
    alter_indexes = [index for index, command in enumerate(commands) if command.upper().startswith("ALTER TABLE")]
    assert len(alter_indexes) == 15
    assert backup_index < min(alter_indexes)
    assert [commands[index] for index in alter_indexes] == [
        f"ALTER TABLE [dbo].[Kit] ADD {spec['ddl']}" for spec in KIT_UPGRADE_COLUMNS
    ]
    assert result["columnsAdded"] == expected_names
    assert result["sourceDataFingerprint"] == {"rowCount": 1, "checksum": 347489}
    assert result["verifiedDataFingerprint"] == result["sourceDataFingerprint"]
    assert result["backupTables"][0]["rowCount"] == 1
    assert result["transactionCommitted"] is True
    assert result["postCommitReadbackVerified"] is True
    assert result["fixedSchemaContract"] is True
    assert state["commits"] == 1

    command_count = len(state["commands"])
    replay = client.execute_kit_upgrade(
        company_username="Kento",
        idempotency_key="kit-upgrade-kento-20260803-v1",
        preview_hash=preview["planHash"],
    )
    assert replay["idempotentReplay"] is True
    assert len(state["commands"]) == command_count

    with pytest.raises(NovaSqlScopeError, match="different Kit upgrade target or preview"):
        client.execute_kit_upgrade(
            company_username="Another_Account",
            idempotency_key="kit-upgrade-kento-20260803-v1",
            preview_hash=preview["planHash"],
        )


def test_kit_upgrade_rejects_conflicting_existing_column(tmp_path):
    conflicting = dict(KIT_UPGRADE_COLUMNS[0])
    conflicting["type"] = "varchar"
    state = {
        "company_username": "Kento",
        "columns": {"TierDiscountPercents": _approved_kit_column_metadata(conflicting)},
        "row_count": 1,
        "data_checksum": 10,
        "backups": {},
        "commands": [],
        "commits": 0,
        "rollbacks": 0,
    }
    client = ScopedNovaSqlClient(
        FakeSalesforce(),
        connect_factory=lambda _connection_string: KitUpgradeConnection(state),
        drivers_factory=lambda: ["ODBC Driver 18 for SQL Server"],
        write_enabled=True,
        write_state_dir=tmp_path,
    )

    with pytest.raises(NovaSqlScopeError, match="does not match the approved Kit upgrade definition"):
        client.preview_kit_upgrade(
            company_username="Kento",
            idempotency_key="kit-upgrade-kento-conflict-20260803-v1",
        )


def test_kit_upgrade_is_safe_no_op_when_all_columns_match(tmp_path):
    state = {
        "company_username": "Already_Upgraded",
        "columns": {
            str(spec["name"]): _approved_kit_column_metadata(spec)
            for spec in KIT_UPGRADE_COLUMNS
        },
        "row_count": 3,
        "data_checksum": 42,
        "backups": {},
        "commands": [],
        "commits": 0,
        "rollbacks": 0,
    }
    client = ScopedNovaSqlClient(
        FakeSalesforce(),
        connect_factory=lambda _connection_string: KitUpgradeConnection(state),
        drivers_factory=lambda: ["ODBC Driver 18 for SQL Server"],
        write_enabled=True,
        write_state_dir=tmp_path,
    )

    preview = client.preview_kit_upgrade(
        company_username="Already_Upgraded",
        idempotency_key="kit-upgrade-already-upgraded-20260803-v1",
    )
    assert preview["missingColumns"] == []
    assert preview["backupRequired"] is False

    result = client.execute_kit_upgrade(
        company_username="Already_Upgraded",
        idempotency_key="kit-upgrade-already-upgraded-20260803-v1",
        preview_hash=preview["planHash"],
    )
    assert result["noOp"] is True
    assert result["transactionCommitted"] is False
    assert result["backupTables"] == []
    assert state["commits"] == 0
    assert not any(
        command.upper().startswith(("SELECT * INTO", "ALTER TABLE"))
        for command, _ in state["commands"]
    )


def test_kit_upgrade_is_disabled_outside_taylor_lane(tmp_path):
    client = ScopedNovaSqlClient(FakeSalesforce(), write_enabled=False, write_state_dir=tmp_path)

    with pytest.raises(NovaSqlScopeError, match="only to coding_agent"):
        client.preview_kit_upgrade(
            company_username="Kento",
            idempotency_key="kit-upgrade-kento-disabled-20260803-v1",
        )
