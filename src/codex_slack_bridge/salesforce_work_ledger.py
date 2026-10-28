# AgentChat/direct_codex 2026-07-14T10:45:00-04:00: durable Salesforce delta routing for Alex and Jamie.
# AgentChat/coding_agent 2026-07-14T17:45:00-04:00: support retiring disabled billing reconciliation work.
from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Condition
from typing import Any, Iterable

from .memory import redact_secrets


SUPPORT_RECORD_TYPES = {"1. nova classic", "nova classic", "2. nova wave", "nova wave"}
BILLING_RECORD_TYPES = {"3. billing", "billing", "nova billing"}
EXCLUDED_ACCOUNT_WORDS = {"demo", "test", "template"}
INTERNAL_JOB_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9:_.-]{0,255}$")
MATERIAL_TICKET_FIELDS = (
    "SystemModstamp",
    "RecordTypeName",
    "Account__c",
    "Is_Closed__c",
    "Ticket_Closed_Date__c",
    "Description__c",
    "Billing_Notes_Internal__c",
    "Tech_Main_Issue__c",
    "Technical_Issue__c",
    "NOVA_Wave_Issue__c",
    "NOVA_Wave_Technical_Issue__c",
    "Customer_Contact__c",
    "NovaPOS_Location__c",
    "Location_ID__c",
    "Accounts_or_Order_Issue__c",
    "Reason_for_closing_the_account__c",
    "NovaPOS_Order__c",
    "Order_ID_from_B_A__c",
    "Customer_Notified__c",
)
ACCOUNT_CANCELLATION_RE = re.compile(
    r"\b(?:cancel(?:l?ed|l?ing|lation)?|close(?:d|ing)?|deactivat(?:e|ed|ing|ion)|"
    r"terminat(?:e|ed|ing|ion))\b.{0,80}"
    r"\b(?:account|service|subscription|nova\s+pos)\b|"
    r"\b(?:account|service|subscription|nova\s+pos)\b.{0,80}"
    r"\b(?:cancel(?:l?ed|l?ing|lation)?|close(?:d|ing)?|deactivat(?:e|ed|ing|ion)|"
    r"terminat(?:e|ed|ing|ion))\b",
    re.IGNORECASE | re.DOTALL,
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe(value: Any, limit: int = 1000) -> str:
    text = " ".join(redact_secrets(str(value or "")).split())
    return text if len(text) <= limit else text[: max(0, limit - 3)].rstrip() + "..."


def _internal_job_id(value: Any) -> str:
    """Validate a local scheduler identifier without passing it through secret redaction.

    Command Center job keys intentionally have a token-like shape.  Treating
    those internal primary keys as display text caused ``redact_secrets`` to
    replace every assignment with the literal ``[redacted]``, so terminal jobs
    could never find and finish their Salesforce work rows.
    """

    job_id = str(value or "").strip()
    if not job_id or not INTERNAL_JOB_ID_RE.fullmatch(job_id):
        raise ValueError("Invalid internal scheduler job id.")
    return job_id


def _hash_payload(value: Any) -> str:
    rendered = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()


def account_is_excluded(name: Any = "", company_username: Any = "") -> bool:
    tokens = set(re.findall(r"[a-z0-9]+", f"{name} {company_username}".casefold()))
    return bool(tokens & EXCLUDED_ACCOUNT_WORDS)


def ticket_route(record_type: Any) -> tuple[str, str]:
    normalized = " ".join(str(record_type or "").casefold().split())
    if normalized in SUPPORT_RECORD_TYPES:
        return "support", "tickets_agent"
    if normalized in BILLING_RECORD_TYPES:
        return "billing", "billing_agent"
    return "ignored", ""


def ticket_has_account_cancellation_intent(ticket: dict[str, Any]) -> bool:
    """Recognize account lifecycle work without routing ordinary support lookups to billing."""

    category = " ".join(str(ticket.get("Accounts_or_Order_Issue__c") or "").casefold().split())
    reason = str(ticket.get("Reason_for_closing_the_account__c") or "").strip()
    text = "\n".join(
        str(ticket.get(key) or "")
        for key in (
            "Description__c",
            "notesFull",
            "subject",
            "taskTitle",
            "instruction",
        )
    )
    return bool(reason or ACCOUNT_CANCELLATION_RE.search(text)) and (
        not category or category in {"account", "order", "account/order", "accounts or orders"}
    )


def ticket_route_for_ticket(ticket: dict[str, Any]) -> tuple[str, str]:
    route, agent = ticket_route(ticket.get("RecordTypeName") or ticket.get("recordType"))
    if route == "support" and ticket_has_account_cancellation_intent(ticket):
        return "billing", "billing_agent"
    return route, agent


def ticket_is_terminal(ticket: dict[str, Any]) -> bool:
    """A closed ticket is terminal only when no known downstream account work remains."""

    if not bool(ticket.get("Is_Closed__c") if "Is_Closed__c" in ticket else ticket.get("isClosed")):
        return False
    return not ticket_has_account_cancellation_intent(ticket)


def material_ticket_hash(ticket: dict[str, Any]) -> str:
    return _hash_payload({key: ticket.get(key) for key in MATERIAL_TICKET_FIELDS})


@dataclass(frozen=True)
class PollResult:
    tickets: list[dict[str, Any]]
    billing_accounts: list[dict[str, Any]]
    high_watermark: str


class SalesforceWorkLedger:
    """Small WAL ledger for material Salesforce ticket/account versions."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._changed = Condition()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.path), timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=5000")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=FULL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS sf_meta (
                    key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at_utc TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS sf_ticket_work (
                    ticket_id TEXT PRIMARY KEY,
                    ticket_number TEXT NOT NULL DEFAULT '',
                    record_type TEXT NOT NULL DEFAULT '',
                    route TEXT NOT NULL DEFAULT '',
                    assigned_agent TEXT NOT NULL DEFAULT '',
                    account_id TEXT NOT NULL DEFAULT '',
                    source_modstamp TEXT NOT NULL DEFAULT '',
                    material_hash TEXT NOT NULL DEFAULT '',
                    investigated_hash TEXT NOT NULL DEFAULT '',
                    context_hash TEXT NOT NULL DEFAULT '',
                    investigated_context_hash TEXT NOT NULL DEFAULT '',
                    state TEXT NOT NULL DEFAULT 'detected',
                    assigned_job_id TEXT NOT NULL DEFAULT '',
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    detected_at_utc TEXT NOT NULL,
                    updated_at_utc TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_sf_ticket_dispatch
                    ON sf_ticket_work(state, assigned_agent, updated_at_utc);
                CREATE TABLE IF NOT EXISTS sf_billing_work (
                    account_id TEXT PRIMARY KEY,
                    source_hash TEXT NOT NULL DEFAULT '',
                    investigated_hash TEXT NOT NULL DEFAULT '',
                    trigger_kind TEXT NOT NULL DEFAULT '',
                    excluded INTEGER NOT NULL DEFAULT 0,
                    exclusion_reason TEXT NOT NULL DEFAULT '',
                    state TEXT NOT NULL DEFAULT 'detected',
                    assigned_job_id TEXT NOT NULL DEFAULT '',
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    detected_at_utc TEXT NOT NULL,
                    updated_at_utc TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_sf_billing_dispatch
                    ON sf_billing_work(state, excluded, updated_at_utc);
                CREATE TABLE IF NOT EXISTS sf_polls (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    started_at_utc TEXT NOT NULL,
                    completed_at_utc TEXT NOT NULL,
                    status TEXT NOT NULL,
                    tickets_seen INTEGER NOT NULL DEFAULT 0,
                    ticket_jobs INTEGER NOT NULL DEFAULT 0,
                    billing_accounts_seen INTEGER NOT NULL DEFAULT 0,
                    billing_jobs INTEGER NOT NULL DEFAULT 0,
                    error TEXT NOT NULL DEFAULT '',
                    elapsed_ms INTEGER NOT NULL DEFAULT 0
                );
                """
            )
            columns = {str(row[1]) for row in connection.execute("PRAGMA table_info(sf_ticket_work)").fetchall()}
            if "context_hash" not in columns:
                connection.execute("ALTER TABLE sf_ticket_work ADD COLUMN context_hash TEXT NOT NULL DEFAULT ''")
            if "investigated_context_hash" not in columns:
                connection.execute(
                    "ALTER TABLE sf_ticket_work ADD COLUMN investigated_context_hash TEXT NOT NULL DEFAULT ''"
                )

    def meta(self, key: str, default: str = "") -> str:
        with self._connect() as connection:
            row = connection.execute("SELECT value FROM sf_meta WHERE key=?", (key,)).fetchone()
        return str(row["value"]) if row else default

    def set_meta(self, key: str, value: Any) -> None:
        now = _utc_now()
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO sf_meta(key,value,updated_at_utc) VALUES(?,?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at_utc=excluded.updated_at_utc",
                (_safe(key, 120), _safe(value, 2000), now),
            )

    def ingest_tickets(self, tickets: Iterable[dict[str, Any]]) -> int:
        changed = 0
        now = _utc_now()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            for ticket in tickets:
                ticket_id = str(ticket.get("Id") or "").strip()
                if not ticket_id:
                    continue
                route, agent = ticket_route_for_ticket(ticket)
                if route == "ignored":
                    continue
                digest = material_ticket_hash(ticket)
                context_digest = str(ticket.get("ContextFingerprint") or "")
                current = connection.execute(
                    "SELECT material_hash,investigated_hash,context_hash,investigated_context_hash,state "
                    "FROM sf_ticket_work WHERE ticket_id=?",
                    (ticket_id,),
                ).fetchone()
                current_context = str(current["context_hash"]) if current else ""
                effective_context = context_digest or current_context
                if current and str(current["material_hash"]) == digest and current_context == effective_context:
                    continue
                state = "complete" if ticket_is_terminal(ticket) else "classified"
                investigated = str(current["investigated_hash"]) if current else ""
                connection.execute(
                    "INSERT INTO sf_ticket_work(ticket_id,ticket_number,record_type,route,assigned_agent,account_id,"
                    "source_modstamp,material_hash,investigated_hash,context_hash,investigated_context_hash,state,"
                    "assigned_job_id,detected_at_utc,updated_at_utc) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
                    "ON CONFLICT(ticket_id) DO UPDATE SET "
                    "ticket_number=excluded.ticket_number,record_type=excluded.record_type,route=excluded.route,"
                    "assigned_agent=excluded.assigned_agent,account_id=excluded.account_id,"
                    "source_modstamp=excluded.source_modstamp,material_hash=excluded.material_hash,"
                    "context_hash=excluded.context_hash,"
                    "state=excluded.state,assigned_job_id='',updated_at_utc=excluded.updated_at_utc",
                    (
                        ticket_id,
                        _safe(ticket.get("Name"), 80),
                        _safe(ticket.get("RecordTypeName"), 120),
                        route,
                        agent,
                        _safe(ticket.get("Account__c"), 32),
                        _safe(ticket.get("SystemModstamp") or ticket.get("LastModifiedDate"), 80),
                        digest,
                        investigated,
                        effective_context,
                        str(current["investigated_context_hash"]) if current else "",
                        state,
                        "",
                        now,
                        now,
                    ),
                )
                changed += 1
        if changed:
            with self._changed:
                self._changed.notify_all()
        return changed

    def ingest_billing_accounts(self, accounts: Iterable[dict[str, Any]]) -> int:
        changed = 0
        now = _utc_now()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            for account in accounts:
                account_id = str(account.get("accountId") or account.get("Id") or "").strip()
                if not account_id:
                    continue
                excluded = account_is_excluded(account.get("name"), account.get("companyUsername"))
                source_hash = _hash_payload(
                    {
                        "locationModstamp": account.get("locationModstamp") or "",
                        "orderModstamp": account.get("orderModstamp") or "",
                        "triggerKind": account.get("triggerKind") or "",
                    }
                )
                current = connection.execute(
                    "SELECT source_hash,investigated_hash FROM sf_billing_work WHERE account_id=?",
                    (account_id,),
                ).fetchone()
                if current and str(current["source_hash"]) == source_hash:
                    continue
                connection.execute(
                    "INSERT INTO sf_billing_work(account_id,source_hash,investigated_hash,trigger_kind,excluded,"
                    "exclusion_reason,state,assigned_job_id,detected_at_utc,updated_at_utc) VALUES(?,?,?,?,?,?,?,?,?,?) "
                    "ON CONFLICT(account_id) DO UPDATE SET source_hash=excluded.source_hash,"
                    "trigger_kind=excluded.trigger_kind,excluded=excluded.excluded,"
                    "exclusion_reason=excluded.exclusion_reason,state=excluded.state,assigned_job_id='',"
                    "updated_at_utc=excluded.updated_at_utc",
                    (
                        account_id,
                        source_hash,
                        str(current["investigated_hash"]) if current else "",
                        _safe(account.get("triggerKind"), 80),
                        1 if excluded else 0,
                        "demo_test_template" if excluded else "",
                        "complete" if excluded else "classified",
                        "",
                        now,
                        now,
                    ),
                )
                changed += 1
        return changed

    def ingest_ticket_projection(self, tickets: Iterable[dict[str, Any]]) -> int:
        """Reconcile the full board's Chatter/session context without storing its bodies."""

        changed = 0
        now = _utc_now()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            for ticket in tickets:
                ticket_id = str(ticket.get("id") or ticket.get("Id") or "").strip()
                if not ticket_id:
                    continue
                route, agent = ticket_route_for_ticket(ticket)
                if route == "ignored":
                    continue
                context_hash = _hash_payload(
                    {
                        "updatedAt": ticket.get("updatedAt") or "",
                        "notes": _hash_payload(str(ticket.get("notesFull") or "")),
                        "chatter": _hash_payload(ticket.get("chatterItems") or []),
                        "sessions": _hash_payload(ticket.get("sessionHistoryItems") or []),
                    }
                )
                current = connection.execute(
                    "SELECT material_hash,context_hash,investigated_context_hash FROM sf_ticket_work "
                    "WHERE ticket_id=?", (ticket_id,)
                ).fetchone()
                if current and str(current["context_hash"]) == context_hash:
                    continue
                is_closed = ticket_is_terminal(ticket)
                if current:
                    connection.execute(
                        "UPDATE sf_ticket_work SET ticket_number=?,record_type=?,route=?,assigned_agent=?,"
                        "context_hash=?,state=?,assigned_job_id='',updated_at_utc=? WHERE ticket_id=?",
                        (
                            _safe(ticket.get("number"), 80),
                            _safe(ticket.get("recordType"), 120),
                            route,
                            agent,
                            context_hash,
                            "complete" if is_closed else "classified",
                            now,
                            ticket_id,
                        ),
                    )
                else:
                    base_hash = _hash_payload(
                        {
                            "ticketId": ticket_id,
                            "updatedAt": ticket.get("updatedAt") or "",
                            "recordType": ticket.get("recordType") or "",
                        }
                    )
                    connection.execute(
                        "INSERT INTO sf_ticket_work(ticket_id,ticket_number,record_type,route,assigned_agent,"
                        "source_modstamp,material_hash,context_hash,state,detected_at_utc,updated_at_utc) "
                        "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            ticket_id,
                            _safe(ticket.get("number"), 80),
                            _safe(ticket.get("recordType"), 120),
                            route,
                            agent,
                            _safe(ticket.get("updatedAt"), 80),
                            base_hash,
                            context_hash,
                            "complete" if is_closed else "classified",
                            now,
                            now,
                        ),
                    )
                changed += 1
        return changed

    def dispatchable_tickets(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM sf_ticket_work WHERE state='classified' AND "
                "(material_hash<>investigated_hash OR context_hash<>investigated_context_hash) "
                "ORDER BY updated_at_utc ASC LIMIT ?", (max(1, min(limit, 200)),)
            ).fetchall()
        return [dict(row) for row in rows]

    def dispatchable_billing(self, limit: int = 25) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM sf_billing_work WHERE state='classified' AND excluded=0 "
                "AND source_hash<>investigated_hash ORDER BY updated_at_utc ASC LIMIT ?",
                (max(1, min(limit, 100)),),
            ).fetchall()
        return [dict(row) for row in rows]

    def retire_billing_work(self) -> int:
        """Terminalize every queued/assigned reconciliation version without deleting audit rows."""

        now = _utc_now()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "UPDATE sf_billing_work SET state='complete',investigated_hash=source_hash,"
                "assigned_job_id='',updated_at_utc=? WHERE state<>'complete' OR source_hash<>investigated_hash",
                (now,),
            )
            changed = int(connection.execute("SELECT changes()").fetchone()[0])
        if changed:
            with self._changed:
                self._changed.notify_all()
        return changed

    def mark_assigned(self, kind: str, identity: str, job_id: str) -> None:
        table, key = ("sf_ticket_work", "ticket_id") if kind == "ticket" else ("sf_billing_work", "account_id")
        with self._connect() as connection:
            connection.execute(
                f"UPDATE {table} SET state='investigating',assigned_job_id=?,updated_at_utc=? WHERE {key}=?",
                (_internal_job_id(job_id), _utc_now(), identity),
            )

    def finish_job(self, job_id: str, *, handled: bool, needs_review: bool = False) -> None:
        job_id = _internal_job_id(job_id)
        now = _utc_now()
        with self._connect() as connection:
            for table, digest_column in (("sf_ticket_work", "material_hash"), ("sf_billing_work", "source_hash")):
                row = connection.execute(
                    f"SELECT {digest_column},attempt_count FROM {table} WHERE assigned_job_id=?", (job_id,)
                ).fetchone()
                if not row:
                    continue
                if handled:
                    if table == "sf_ticket_work":
                        connection.execute(
                            "UPDATE sf_ticket_work SET state=?,investigated_hash=material_hash,"
                            "investigated_context_hash=context_hash,updated_at_utc=? WHERE assigned_job_id=?",
                            ("action_pending" if needs_review else "complete", now, job_id),
                        )
                    else:
                        connection.execute(
                            f"UPDATE {table} SET state=?,investigated_hash={digest_column},updated_at_utc=? "
                            "WHERE assigned_job_id=?",
                            ("action_pending" if needs_review else "complete", now, job_id),
                        )
                else:
                    connection.execute(
                        f"UPDATE {table} SET state='classified',attempt_count=?,assigned_job_id='',updated_at_utc=? "
                        "WHERE assigned_job_id=?",
                        (int(row["attempt_count"] or 0) + 1, now, job_id),
                    )

    def repair_redacted_assignments(self) -> dict[str, int]:
        """Return legacy scrubbed assignments to the dispatch queue once.

        Only the exact sentinel written by the former bug is repaired.  Valid
        assignments and completed versions are left untouched.
        """

        repaired: dict[str, int] = {"ticket": 0, "billing": 0}
        now = _utc_now()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            for kind, table, digest_column in (
                ("ticket", "sf_ticket_work", "material_hash"),
                ("billing", "sf_billing_work", "source_hash"),
            ):
                connection.execute(
                    f"UPDATE {table} SET state=CASE WHEN {digest_column}=investigated_hash "
                    "THEN 'complete' ELSE 'classified' END, assigned_job_id='', updated_at_utc=? "
                    "WHERE assigned_job_id='[redacted]'",
                    (now,),
                )
                repaired[kind] = int(connection.execute("SELECT changes()").fetchone()[0])
        if any(repaired.values()):
            with self._changed:
                self._changed.notify_all()
        return repaired

    def record_poll(self, *, started_at: str, status: str, tickets_seen: int, ticket_jobs: int,
                    billing_seen: int, billing_jobs: int, error: str = "", elapsed_ms: int = 0) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO sf_polls(started_at_utc,completed_at_utc,status,tickets_seen,ticket_jobs,"
                "billing_accounts_seen,billing_jobs,error,elapsed_ms) VALUES(?,?,?,?,?,?,?,?,?)",
                (started_at, _utc_now(), _safe(status, 40), tickets_seen, ticket_jobs, billing_seen,
                 billing_jobs, _safe(error, 1000), max(0, int(elapsed_ms))),
            )

    def status(self) -> dict[str, Any]:
        try:
            with self._connect() as connection:
                integrity = str(connection.execute("PRAGMA quick_check").fetchone()[0])
                ticket_states = {str(r[0]): int(r[1]) for r in connection.execute(
                    "SELECT state,COUNT(*) FROM sf_ticket_work GROUP BY state").fetchall()}
                billing_states = {str(r[0]): int(r[1]) for r in connection.execute(
                    "SELECT state,COUNT(*) FROM sf_billing_work GROUP BY state").fetchall()}
                last = connection.execute("SELECT * FROM sf_polls ORDER BY id DESC LIMIT 1").fetchone()
            return {
                "ok": integrity == "ok" and (not last or str(last["status"]) != "failed"),
                "integrity": integrity,
                "ticketStates": ticket_states,
                "billingStates": billing_states,
                "lastPoll": dict(last) if last else {},
            }
        except sqlite3.Error as exc:
            return {"ok": False, "integrity": "error", "error": _safe(exc, 500)}


def _load_salesforce_api(path: Path):
    module_name = "agentchat_salesforce_api"
    if module_name in sys.modules:
        return sys.modules[module_name]
    source_root = str(path.parent)
    if source_root not in sys.path:
        sys.path.insert(0, source_root)
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Salesforce helper could not be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _query_all(sf: Any, token: str, soql: str) -> list[dict[str, Any]]:
    result = sf._soql_query(token, soql)
    records = list(result.get("records") or [])
    next_url = result.get("nextRecordsUrl")
    while next_url:
        import requests
        response = requests.get(
            f"{sf.get_instance_url().rstrip('/')}{next_url}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=15,
        )
        response.raise_for_status()
        result = response.json()
        records.extend(result.get("records") or [])
        next_url = result.get("nextRecordsUrl")
    return records


def _watermark_with_overlap(watermark: str, seconds: int = 120) -> str:
    value = str(watermark or "").strip()
    if not value:
        return ""
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value
    return (parsed - timedelta(seconds=max(0, seconds))).astimezone(timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%S.000Z"
    )


def collect_salesforce_delta(*, helper_path: str | Path, watermark: str = "", lookback_hours: int = 24) -> PollResult:
    """Fetch bounded parent-record deltas; ticket bodies remain untrusted data."""

    sf = _load_salesforce_api(Path(helper_path))
    token = sf.get_salesforce_token()
    if not token:
        raise RuntimeError("Salesforce authentication is unavailable")
    checkpoint = watermark
    watermark = _watermark_with_overlap(watermark)
    if not watermark:
        watermark = (datetime.now(timezone.utc) - timedelta(hours=max(1, min(lookback_hours, 168)))).strftime(
            "%Y-%m-%dT%H:%M:%S.000Z"
        )
    ticket_fields = (
        "Id,Name,RecordType.Name,Account__c,Account__r.Name,Account__r.Company_Username__c,"
        "SystemModstamp,LastModifiedDate,Is_Closed__c,"
        "Ticket_Closed_Date__c,Description__c,Billing_Notes_Internal__c,Tech_Main_Issue__c,"
        "Technical_Issue__c,NOVA_Wave_Issue__c,NOVA_Wave_Technical_Issue__c,Customer_Contact__c,"
        "NovaPOS_Location__c,Location_ID__c,Accounts_or_Order_Issue__c,"
        "Reason_for_closing_the_account__c,NovaPOS_Order__c,Order_ID_from_B_A__c,Customer_Notified__c"
    )
    tickets = _query_all(
        sf, token,
        f"SELECT {ticket_fields} FROM NovaPOS_Ticket__c WHERE SystemModstamp >= {watermark} "
        "AND RecordType.Name IN ('1. NOVA Classic','2. Nova Wave','3. Billing') "
        "ORDER BY SystemModstamp ASC LIMIT 2000",
    )
    normalized_tickets = []
    high_watermark = checkpoint or watermark
    for ticket in tickets:
        item = dict(ticket)
        item.pop("attributes", None)
        record_type = item.pop("RecordType", None)
        account = item.pop("Account__r", None)
        if isinstance(account, dict) and account_is_excluded(account.get("Name"), account.get("Company_Username__c")):
            continue
        item["RecordTypeName"] = (record_type or {}).get("Name") if isinstance(record_type, dict) else ""
        high_watermark = max(high_watermark, str(item.get("SystemModstamp") or watermark))
        normalized_tickets.append(item)

    changed_accounts: dict[str, dict[str, Any]] = {}
    for obj, kind in (("NovaPOS_Location__c", "location"), ("NovaPOS_Order__c", "order")):
        records = _query_all(
            sf, token,
            f"SELECT Id,Account__c,SystemModstamp FROM {obj} WHERE Account__c != null "
            f"AND SystemModstamp >= {watermark} ORDER BY SystemModstamp ASC LIMIT 2000",
        )
        for record in records:
            account_id = str(record.get("Account__c") or "")
            if not account_id:
                continue
            row = changed_accounts.setdefault(account_id, {"accountId": account_id, "triggerKinds": set()})
            row["triggerKinds"].add(kind)
            row[f"{kind}Modstamp"] = max(
                str(row.get(f"{kind}Modstamp") or ""), str(record.get("SystemModstamp") or "")
            )
            high_watermark = max(high_watermark, str(record.get("SystemModstamp") or watermark))
    account_ids = sorted(changed_accounts)
    for start in range(0, len(account_ids), 200):
        batch = account_ids[start : start + 200]
        if not batch:
            continue
        quoted = ",".join(f"'{value}'" for value in batch)
        for account in _query_all(
            sf, token,
            "SELECT Id,Name,Company_Username__c FROM Account WHERE Id IN (" + quoted + ")",
        ):
            row = changed_accounts.get(str(account.get("Id") or ""))
            if row is not None:
                row["name"] = account.get("Name") or ""
                row["companyUsername"] = account.get("Company_Username__c") or ""
    billing_accounts = []
    for row in changed_accounts.values():
        row["triggerKind"] = "+".join(sorted(row.pop("triggerKinds")))
        billing_accounts.append(row)
    return PollResult(normalized_tickets, billing_accounts, high_watermark)
