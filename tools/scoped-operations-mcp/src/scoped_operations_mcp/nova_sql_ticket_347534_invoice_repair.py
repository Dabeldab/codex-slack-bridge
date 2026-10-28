from __future__ import annotations

import hashlib
import json
import os
import re
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


OPERATION_NAME = "ticket_347534_invoice_location_repair_v1"
SOURCE_USERNAME = "CrystalLaserArt"
SOURCE_DATABASE = "POS_CrystalLaserArt"
TARGET_USERNAME = "Crystal_laser_Studio"
TARGET_DATABASE = "POS_Crystal_laser_Studio"
SOURCE_LOCATION_ID = 1
WRONG_SOURCE_LOCATION_ID = 3
TARGET_LOCATION_ID = 1
CUTOFF = "2026-04-01T00:00:00"
PROTECTED_INVOICE_ID = 73242
MAX_DELETE_ROWS = 5_000
IDEMPOTENCY_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{7,199}$")
PREVIEW_HASH = re.compile(r"^[0-9a-f]{64}$")

CHANGED_TABLES = (
    "dbo.Invoice_Products_Commission",
    "dbo.Invoices_Notes",
    "dbo.Invoice_Employees",
    "dbo.Invoice_Payments",
    "dbo.Invoice_Products",
    "dbo.Invoices",
)

BAD_SCOPE_CTE = f"""
WITH bad AS (
    SELECT t.InvoiceID
    FROM dbo.Invoices AS t
    JOIN [{SOURCE_DATABASE}].dbo.Invoices AS s ON s.InvoiceID=t.InvoiceID
    WHERE s.LocationID={WRONG_SOURCE_LOCATION_ID}
      AND s.[Timestamp]>='{CUTOFF}'
      AND t.InvoiceID<>{PROTECTED_INVOICE_ID}
)
""".strip()

MANIFEST_SQL = BAD_SCOPE_CTE + f"""
SELECT
    (SELECT COUNT_BIG(*) FROM dbo.Invoices) AS TargetInvoices,
    (SELECT COUNT_BIG(*) FROM bad) AS BadInvoices,
    (SELECT COUNT_BIG(*) FROM dbo.Invoice_Employees AS x JOIN bad AS b ON b.InvoiceID=x.InvoiceID) AS BadInvoiceEmployees,
    (SELECT COUNT_BIG(*) FROM dbo.Invoice_Payments AS x JOIN bad AS b ON b.InvoiceID=x.InvoiceID) AS BadInvoicePayments,
    (SELECT COUNT_BIG(*) FROM dbo.Invoice_Products AS x JOIN bad AS b ON b.InvoiceID=x.InvoiceID) AS BadInvoiceProducts,
    (SELECT COUNT_BIG(*) FROM dbo.Invoices_Notes AS x JOIN bad AS b ON b.InvoiceID=x.InvoiceID) AS BadInvoiceNotes,
    (SELECT COUNT_BIG(*) FROM dbo.Invoice_Products_Commission AS x JOIN dbo.Invoice_Products AS ip ON ip.Invoice_Products_ID=x.Invoice_ProductsID JOIN bad AS b ON b.InvoiceID=ip.InvoiceID) AS BadInvoiceProductCommissions,
    (SELECT COUNT_BIG(*) FROM dbo.Invoices WHERE InvoiceID={PROTECTED_INVOICE_ID}) AS ProtectedInvoice,
    (SELECT COUNT_BIG(*) FROM dbo.Invoice_Employees WHERE InvoiceID={PROTECTED_INVOICE_ID}) AS ProtectedInvoiceEmployees,
    (SELECT COUNT_BIG(*) FROM dbo.Invoice_Payments WHERE InvoiceID={PROTECTED_INVOICE_ID}) AS ProtectedInvoicePayments,
    (SELECT COUNT_BIG(*) FROM dbo.Invoice_Products WHERE InvoiceID={PROTECTED_INVOICE_ID}) AS ProtectedInvoiceProducts,
    (SELECT COUNT_BIG(*) FROM dbo.Invoices_Notes WHERE InvoiceID={PROTECTED_INVOICE_ID}) AS ProtectedInvoiceNotes,
    (SELECT COUNT_BIG(*) FROM dbo.Invoice_Products_Commission AS x JOIN dbo.Invoice_Products AS ip ON ip.Invoice_Products_ID=x.Invoice_ProductsID WHERE ip.InvoiceID={PROTECTED_INVOICE_ID}) AS ProtectedInvoiceProductCommissions,
    (SELECT COUNT_BIG(*) FROM [{SOURCE_DATABASE}].dbo.Invoices WHERE LocationID={SOURCE_LOCATION_ID} AND [Timestamp]>='{CUTOFF}') AS SourceLocationInvoices,
    (SELECT COUNT_BIG(*) FROM [{SOURCE_DATABASE}].dbo.Invoices AS s WHERE s.LocationID={SOURCE_LOCATION_ID} AND s.[Timestamp]>='{CUTOFF}' AND NOT EXISTS (SELECT 1 FROM dbo.Invoices AS t WHERE t.InvoiceID=s.InvoiceID)) AS MissingSourceLocationInvoices
""".strip()

READBACK_SQL = f"""
SELECT
    (SELECT COUNT_BIG(*) FROM dbo.Invoices) AS TargetInvoices,
    (SELECT COUNT_BIG(*) FROM dbo.Invoices AS t JOIN [{SOURCE_DATABASE}].dbo.Invoices AS s ON s.InvoiceID=t.InvoiceID WHERE s.LocationID={WRONG_SOURCE_LOCATION_ID} AND s.[Timestamp]>='{CUTOFF}' AND t.InvoiceID<>{PROTECTED_INVOICE_ID}) AS WrongSourceInvoicesRemaining,
    (SELECT COUNT_BIG(*) FROM dbo.Invoices WHERE InvoiceID={PROTECTED_INVOICE_ID}) AS ProtectedInvoice,
    (SELECT COUNT_BIG(*) FROM dbo.Invoice_Employees WHERE InvoiceID={PROTECTED_INVOICE_ID}) AS ProtectedInvoiceEmployees,
    (SELECT COUNT_BIG(*) FROM dbo.Invoice_Payments WHERE InvoiceID={PROTECTED_INVOICE_ID}) AS ProtectedInvoicePayments,
    (SELECT COUNT_BIG(*) FROM dbo.Invoice_Products WHERE InvoiceID={PROTECTED_INVOICE_ID}) AS ProtectedInvoiceProducts,
    (SELECT COUNT_BIG(*) FROM dbo.Invoices_Notes WHERE InvoiceID={PROTECTED_INVOICE_ID}) AS ProtectedInvoiceNotes,
    (SELECT COUNT_BIG(*) FROM dbo.Invoice_Products_Commission AS x JOIN dbo.Invoice_Products AS ip ON ip.Invoice_Products_ID=x.Invoice_ProductsID WHERE ip.InvoiceID={PROTECTED_INVOICE_ID}) AS ProtectedInvoiceProductCommissions,
    (SELECT COUNT_BIG(*) FROM [{SOURCE_DATABASE}].dbo.Invoices AS s WHERE s.LocationID={SOURCE_LOCATION_ID} AND s.[Timestamp]>='{CUTOFF}' AND NOT EXISTS (SELECT 1 FROM dbo.Invoices AS t WHERE t.InvoiceID=s.InvoiceID)) AS MissingSourceLocationInvoices,
    (SELECT COUNT_BIG(*) FROM dbo.Invoice_Employees AS x LEFT JOIN dbo.Invoices AS i ON i.InvoiceID=x.InvoiceID WHERE i.InvoiceID IS NULL) AS OrphanInvoiceEmployees,
    (SELECT COUNT_BIG(*) FROM dbo.Invoice_Payments AS x LEFT JOIN dbo.Invoices AS i ON i.InvoiceID=x.InvoiceID WHERE i.InvoiceID IS NULL) AS OrphanInvoicePayments,
    (SELECT COUNT_BIG(*) FROM dbo.Invoice_Products AS x LEFT JOIN dbo.Invoices AS i ON i.InvoiceID=x.InvoiceID WHERE i.InvoiceID IS NULL) AS OrphanInvoiceProducts,
    (SELECT COUNT_BIG(*) FROM dbo.Invoices_Notes AS x LEFT JOIN dbo.Invoices AS i ON i.InvoiceID=x.InvoiceID WHERE i.InvoiceID IS NULL) AS OrphanInvoiceNotes,
    (SELECT COUNT_BIG(*) FROM dbo.Invoice_Products_Commission AS x LEFT JOIN dbo.Invoice_Products AS ip ON ip.Invoice_Products_ID=x.Invoice_ProductsID WHERE ip.Invoice_Products_ID IS NULL) AS OrphanInvoiceProductCommissions
""".strip()


class Ticket347534RepairScopeError(ValueError):
    """The fixed ticket repair no longer matches the reviewed live state."""


class Ticket347534RepairUnavailableError(RuntimeError):
    """The fixed repair committed without a durable receipt or readback."""


class Ticket347534InvoiceRepairOperation:
    """Remove only ticket 347534's wrong-location invoice graph."""

    def __init__(
        self,
        *,
        connect: Callable[[bool], Any],
        state_dir: str | Path,
        query_timeout_seconds: int = 120,
    ) -> None:
        self._connect = connect
        self._state_dir = Path(state_dir).expanduser().resolve() / OPERATION_NAME
        self._query_timeout_seconds = max(120, min(int(query_timeout_seconds), 1_800))

    def preview(self, *, idempotency_key: str) -> dict[str, Any]:
        clean_key = _idempotency_key(idempotency_key)
        receipt = _read_json_optional(self._receipt_path(clean_key))
        if receipt:
            return _completed_result(receipt, replay=True)
        with closing(self._connect(True)) as connection:
            connection.timeout = self._query_timeout_seconds
            cursor = connection.cursor()
            _verify_database_binding(cursor)
            manifest = _manifest(cursor)
        _validate_manifest(manifest)
        plan_hash = _digest({"operation": OPERATION_NAME, "idempotencyKey": clean_key, "manifest": manifest})
        preview = {
            "operation": OPERATION_NAME,
            "status": "preview",
            "idempotencyKey": clean_key,
            "planHash": plan_hash,
            "fixedSource": SOURCE_USERNAME,
            "fixedTarget": TARGET_USERNAME,
            "sourceLocationId": SOURCE_LOCATION_ID,
            "wrongSourceLocationId": WRONG_SOURCE_LOCATION_ID,
            "targetLocationId": TARGET_LOCATION_ID,
            "cutoff": CUTOFF,
            "protectedInvoiceId": PROTECTED_INVOICE_ID,
            "genericDeleteExposed": False,
            "sourceDatabaseReadOnlyByOperationPolicy": True,
            "fullTargetBackupsRequired": True,
            "manifest": manifest,
            "previewedAtUtc": _utc_now(),
        }
        existing = _read_json_optional(self._preview_path(clean_key))
        if existing and existing.get("planHash") != plan_hash:
            raise Ticket347534RepairScopeError("live invoice scope changed after the fixed repair preview")
        if not existing:
            _write_json_atomic(self._preview_path(clean_key), preview)
        return existing or preview

    def status(self, *, idempotency_key: str) -> dict[str, Any]:
        clean_key = _idempotency_key(idempotency_key)
        receipt = _read_json_optional(self._receipt_path(clean_key))
        if receipt:
            return _completed_result(receipt, replay=True)
        preview = _read_json_optional(self._preview_path(clean_key))
        return {
            "ok": True,
            "operation": OPERATION_NAME,
            "status": "previewed" if preview else "not_previewed",
            "idempotencyKey": clean_key,
            "planHash": (preview or {}).get("planHash", ""),
            "safeToRetry": bool(preview),
        }

    def execute(self, *, idempotency_key: str, preview_hash: str) -> dict[str, Any]:
        clean_key = _idempotency_key(idempotency_key)
        clean_hash = _preview_hash(preview_hash)
        receipt = _read_json_optional(self._receipt_path(clean_key))
        if receipt:
            return _completed_result(receipt, replay=True)
        preview = _read_json_optional(self._preview_path(clean_key))
        if not preview or preview.get("planHash") != clean_hash:
            raise Ticket347534RepairScopeError("preview_hash must match the fixed repair preview")

        committed = False
        backups: list[dict[str, Any]] = []
        mutation_counts: dict[str, int] = {}
        readback: dict[str, int] = {}
        with closing(self._connect(False)) as connection:
            connection.timeout = self._query_timeout_seconds
            cursor = connection.cursor()
            try:
                cursor.execute("SET XACT_ABORT ON")
                cursor.execute("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
                _verify_database_binding(cursor)
                _acquire_lock(cursor, clean_key)
                current = _manifest(cursor)
                _validate_manifest(current)
                if current != preview.get("manifest"):
                    raise Ticket347534RepairScopeError("invoice scope changed after preview; no rows were changed")
                backups = _create_backups(cursor, clean_hash)
                mutation_counts = _delete_wrong_graph(cursor)
                if sum(mutation_counts.values()) > MAX_DELETE_ROWS:
                    raise Ticket347534RepairScopeError("repair exceeded its fixed affected-row ceiling")
                expected = _expected_mutation_counts(current)
                if mutation_counts != expected:
                    raise Ticket347534RepairScopeError("deleted-row counts differed from the fixed preview")
                readback = _readback(cursor)
                _validate_readback(readback, current)
                connection.commit()
                committed = True
            except Exception:
                if not committed:
                    connection.rollback()
                raise

        # Read from the write-primary after commit. A read-intent connection can
        # legitimately lag and must not turn a completed repair into an
        # uncertain retry.
        with closing(self._connect(False)) as connection:
            connection.timeout = self._query_timeout_seconds
            final_readback = _readback(connection.cursor())
        _validate_readback(final_readback, preview["manifest"])
        receipt = {
            "operation": OPERATION_NAME,
            "status": "completed",
            "idempotencyKey": clean_key,
            "planHash": clean_hash,
            "fixedSource": SOURCE_USERNAME,
            "fixedTarget": TARGET_USERNAME,
            "protectedInvoiceId": PROTECTED_INVOICE_ID,
            "sourceDatabaseReadOnlyByOperationPolicy": True,
            "genericDeleteExposed": False,
            "transactionCommitted": True,
            "backups": backups,
            "mutationCounts": mutation_counts,
            "readback": final_readback,
            "completedAtUtc": _utc_now(),
        }
        try:
            _write_json_atomic(self._receipt_path(clean_key), receipt)
        except Exception as exc:
            raise Ticket347534RepairUnavailableError(
                "ticket repair committed without a durable receipt; call status and do not retry"
            ) from exc
        return _completed_result(receipt, replay=False)

    def _preview_path(self, key: str) -> Path:
        return self._state_dir / f"{hashlib.sha256(key.encode('utf-8')).hexdigest()}.preview.json"

    def _receipt_path(self, key: str) -> Path:
        return self._state_dir / f"{hashlib.sha256(key.encode('utf-8')).hexdigest()}.receipt.json"


def _manifest(cursor: Any) -> dict[str, int]:
    cursor.execute(MANIFEST_SQL)
    row = cursor.fetchone()
    names = [str(column[0]) for column in cursor.description]
    return {names[index]: int(row[index] or 0) for index in range(len(names))}


def _validate_manifest(manifest: dict[str, int]) -> None:
    if manifest.get("BadInvoices") != 480:
        raise Ticket347534RepairScopeError("fixed repair requires exactly 480 wrong-location invoices")
    if manifest.get("ProtectedInvoice") != 1:
        raise Ticket347534RepairScopeError("protected August 6 invoice 73242 is missing")
    if manifest.get("MissingSourceLocationInvoices") != 1:
        raise Ticket347534RepairScopeError("expected exactly one later source Location 1 invoice")
    if sum(_expected_mutation_counts(manifest).values()) > MAX_DELETE_ROWS:
        raise Ticket347534RepairScopeError("fixed repair exceeds its reviewed affected-row ceiling")


def _expected_mutation_counts(manifest: dict[str, int]) -> dict[str, int]:
    return {
        "Invoice_Products_Commission": manifest.get("BadInvoiceProductCommissions", -1),
        "Invoices_Notes": manifest.get("BadInvoiceNotes", -1),
        "Invoice_Employees": manifest.get("BadInvoiceEmployees", -1),
        "Invoice_Payments": manifest.get("BadInvoicePayments", -1),
        "Invoice_Products": manifest.get("BadInvoiceProducts", -1),
        "Invoices": manifest.get("BadInvoices", -1),
    }


def _create_backups(cursor: Any, plan_hash: str) -> list[dict[str, Any]]:
    suffix = plan_hash[:12]
    output: list[dict[str, Any]] = []
    for table in CHANGED_TABLES:
        name = table.split(".", 1)[1]
        backup = f"dbo.__codex_bak_{name}_{suffix}"
        if int(cursor.execute("SELECT COUNT_BIG(*) FROM sys.tables WHERE object_id=OBJECT_ID(?)", backup).fetchone()[0] or 0):
            raise Ticket347534RepairScopeError("deterministic repair backup already exists without a receipt")
        cursor.execute(f"SELECT * INTO [{backup.split('.')[0]}].[{backup.split('.')[1]}] FROM [dbo].[{name}] WITH (HOLDLOCK,TABLOCKX)")
        source_count = int(cursor.execute(f"SELECT COUNT_BIG(*) FROM [dbo].[{name}]").fetchone()[0] or 0)
        backup_count = int(cursor.execute(f"SELECT COUNT_BIG(*) FROM [{backup.split('.')[0]}].[{backup.split('.')[1]}]").fetchone()[0] or 0)
        if source_count != backup_count:
            raise Ticket347534RepairScopeError("full target backup row-count verification failed")
        output.append({"sourceTable": table, "backupTable": backup, "rowCount": backup_count})
    return output


def _delete_wrong_graph(cursor: Any) -> dict[str, int]:
    cursor.execute(
        f"""SELECT t.InvoiceID INTO #Ticket347534BadInvoices
             FROM dbo.Invoices AS t WITH (UPDLOCK,HOLDLOCK)
             JOIN [{SOURCE_DATABASE}].dbo.Invoices AS s WITH (HOLDLOCK) ON s.InvoiceID=t.InvoiceID
             WHERE s.LocationID={WRONG_SOURCE_LOCATION_ID}
               AND s.[Timestamp]>='{CUTOFF}'
               AND t.InvoiceID<>{PROTECTED_INVOICE_ID}"""
    )
    statements = (
        ("Invoice_Products_Commission", "DELETE c FROM dbo.Invoice_Products_Commission AS c JOIN dbo.Invoice_Products AS ip ON ip.Invoice_Products_ID=c.Invoice_ProductsID JOIN #Ticket347534BadInvoices AS b ON b.InvoiceID=ip.InvoiceID"),
        ("Invoices_Notes", "DELETE x FROM dbo.Invoices_Notes AS x JOIN #Ticket347534BadInvoices AS b ON b.InvoiceID=x.InvoiceID"),
        ("Invoice_Employees", "DELETE x FROM dbo.Invoice_Employees AS x JOIN #Ticket347534BadInvoices AS b ON b.InvoiceID=x.InvoiceID"),
        ("Invoice_Payments", "DELETE x FROM dbo.Invoice_Payments AS x JOIN #Ticket347534BadInvoices AS b ON b.InvoiceID=x.InvoiceID"),
        ("Invoice_Products", "DELETE x FROM dbo.Invoice_Products AS x JOIN #Ticket347534BadInvoices AS b ON b.InvoiceID=x.InvoiceID"),
        ("Invoices", "DELETE x FROM dbo.Invoices AS x JOIN #Ticket347534BadInvoices AS b ON b.InvoiceID=x.InvoiceID"),
    )
    counts: dict[str, int] = {}
    for name, sql in statements:
        cursor.execute(sql)
        counts[name] = int(cursor.rowcount)
    return counts


def _readback(cursor: Any) -> dict[str, int]:
    cursor.execute(READBACK_SQL)
    row = cursor.fetchone()
    names = [str(column[0]) for column in cursor.description]
    return {names[index]: int(row[index] or 0) for index in range(len(names))}


def _validate_readback(readback: dict[str, int], manifest: dict[str, int]) -> None:
    expected_target = manifest["TargetInvoices"] - manifest["BadInvoices"]
    if readback.get("TargetInvoices") != expected_target:
        raise Ticket347534RepairScopeError("target invoice count failed repair readback")
    if readback.get("WrongSourceInvoicesRemaining") != 0:
        raise Ticket347534RepairScopeError("wrong-source invoices remain after repair")
    for name in (
        "ProtectedInvoice",
        "ProtectedInvoiceEmployees",
        "ProtectedInvoicePayments",
        "ProtectedInvoiceProducts",
        "ProtectedInvoiceNotes",
        "ProtectedInvoiceProductCommissions",
    ):
        if readback.get(name) != manifest.get(name):
            raise Ticket347534RepairScopeError("protected August 6 invoice graph changed")
    if readback.get("MissingSourceLocationInvoices") != 1:
        raise Ticket347534RepairScopeError("source Location 1 catch-up scope changed during repair")
    for name, value in readback.items():
        if name.startswith("Orphan") and value != 0:
            raise Ticket347534RepairScopeError("orphan invoice references detected after repair")


def _verify_database_binding(cursor: Any) -> None:
    row = cursor.execute("SELECT DB_NAME()").fetchone()
    if not row or str(row[0] or "").casefold() != TARGET_DATABASE.casefold():
        raise Ticket347534RepairScopeError("fixed repair connected to an unexpected target")


def _acquire_lock(cursor: Any, key: str) -> None:
    row = cursor.execute(
        "DECLARE @result int; EXEC @result=sys.sp_getapplock @Resource=?,@LockMode='Exclusive',@LockOwner='Transaction',@LockTimeout=30000; SELECT @result",
        f"nova:{OPERATION_NAME}:{key}",
    ).fetchone()
    if not row or int(row[0]) < 0:
        raise Ticket347534RepairUnavailableError("could not acquire the fixed repair lock")


def _completed_result(receipt: dict[str, Any], *, replay: bool) -> dict[str, Any]:
    return {"ok": True, **receipt, "idempotentReplay": replay}


def _idempotency_key(value: Any) -> str:
    clean = str(value or "").strip()
    if not IDEMPOTENCY_KEY.fullmatch(clean):
        raise Ticket347534RepairScopeError("idempotency_key must be a stable 8-200 character identifier")
    return clean


def _preview_hash(value: Any) -> str:
    clean = str(value or "").strip().casefold()
    if not PREVIEW_HASH.fullmatch(clean):
        raise Ticket347534RepairScopeError("preview_hash must be the exact fixed repair hash")
    return clean


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")).hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json_optional(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    if not isinstance(value, dict):
        raise Ticket347534RepairUnavailableError("fixed repair state is invalid")
    return value


def _write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f".tmp.{os.getpid()}")
    temporary.write_text(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True), encoding="utf-8")
    os.replace(temporary, path)
