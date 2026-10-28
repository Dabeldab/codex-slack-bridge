# AgentChat/direct_codex 2026-08-04T16:08:29Z
"""Deterministic, shift-aware support reminders for the Ghost Busters channel."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable
from zoneinfo import ZoneInfo

from google.auth.transport.requests import AuthorizedSession
from google.oauth2.credentials import Credentials

from .zoom_kb_sync import get_zoom_token


SCHEDULE_SPREADSHEET_ID = "1yfx8UPupk23RVTGZ5cUurAkp-hMeFj6Qkgw3um9ovBk"
TIMEZONE_NAME = "America/New_York"
GHOST_BUSTERS_CHANNEL_ID = "8951653b0e784070b50def3138b1ac50"
REVIEW_CHANNEL_IDS = (
    "ed88f6f175194192a0caeff55de08eba",
    "83db902a3f28473e964d925239a8a3ba",
)
DEFAULT_STATE_PATH = Path("/tmp/nova/support-shift-reminders.jsonl")
DEFAULT_CACHE_PATH = Path("/tmp/nova/support_shift_reminders.json")
DEFAULT_GRACE_MINUTES = 60
MAX_HISTORY_PAGES = 10
ZOOM_BASE_URL = "https://api.zoom.us/v2"
WORKSPACE_SCOPES = (
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/spreadsheets",
)


@dataclass(frozen=True)
class Rep:
    schedule_name: str
    display_name: str
    email: str
    first_name: str


@dataclass(frozen=True)
class Shift:
    rep: Rep
    start: datetime
    end: datetime

    @property
    def key(self) -> str:
        return f"{self.rep.email}:{self.start.astimezone(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"


REPS = (
    Rep("Eddie", "Ahmed Talal", "eddi@novapointofsale.com", "Eddie"),
    Rep("OscarO", "Oscar Ocampo", "oscaro@novapointofsale.com", "Oscar Ocampo"),
    Rep("Eduardo", "Eduardo Brambila", "eduardo@novapointofsale.com", "Eduardo"),
    Rep("Oscar", "Oscar Umana", "oscar@novapointofsale.com", "Oscar Umana"),
    Rep("Mordi", "Mordi Turgeman", "mordi@novapointofsale.com", "Mordi"),
)
REP_BY_SCHEDULE_NAME = {rep.schedule_name.casefold(): rep for rep in REPS}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the bounded support shift reminder check.")
    parser.add_argument("--state", default=str(DEFAULT_STATE_PATH))
    parser.add_argument("--cache", default=str(DEFAULT_CACHE_PATH))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--now", default="", help="Optional ISO timestamp for a deterministic test run.")
    parser.add_argument("--grace-minutes", type=int, default=DEFAULT_GRACE_MINUTES)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    now = _parse_timestamp(args.now) if args.now else datetime.now(timezone.utc)
    result = run_reminders(
        now=now,
        state_path=Path(args.state),
        cache_path=Path(args.cache),
        dry_run=bool(args.dry_run),
        grace_minutes=max(0, min(int(args.grace_minutes), 240)),
    )
    print(json.dumps(_public_summary(result), sort_keys=True))


def run_reminders(
    *,
    now: datetime,
    state_path: Path,
    cache_path: Path,
    dry_run: bool = False,
    grace_minutes: int = DEFAULT_GRACE_MINUTES,
    sheet_reader: Callable[[str], list[list[Any]]] | None = None,
    history_reader: Callable[[str, datetime, datetime], list[dict[str, Any]]] | None = None,
    sender: Callable[[str], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    resolved_now = _as_utc(now)
    local_now = resolved_now.astimezone(ZoneInfo(TIMEZONE_NAME))
    tab = local_now.strftime("%b%y")
    values = (sheet_reader or _read_schedule_values)(tab)
    shifts = parse_schedule(values, tab=tab)
    active = [
        shift
        for shift in shifts
        if shift.start + timedelta(minutes=grace_minutes) <= local_now < shift.end
    ]
    state = read_state(state_path)
    earliest = min((shift.start for shift in active), default=local_now)
    messages: list[dict[str, Any]] = []
    if active:
        reader = history_reader or _read_zoom_history
        for channel_id in REVIEW_CHANNEL_IDS:
            messages.extend(reader(channel_id, earliest, local_now))

    review_keys: list[str] = []
    ticket_keys: list[str] = []
    names: list[str] = []
    for shift in active:
        review_key = f"review:{shift.key}"
        if review_key not in state and not has_review_activity(shift, messages, local_now):
            review_keys.append(review_key)
            names.append(shift.rep.first_name)
        ticket_key = f"eduardo-ticket:{shift.key}"
        if shift.rep.email == "eduardo@novapointofsale.com" and ticket_key not in state:
            ticket_keys.append(ticket_key)

    body = build_message(names=names, remind_eduardo=bool(ticket_keys))
    outcome: dict[str, Any] = {
        "ok": True,
        "status": "not_due",
        "checkedAtUtc": _iso(resolved_now),
        "timezone": TIMEZONE_NAME,
        "scheduleTab": tab,
        "activeShiftCount": len(active),
        "reviewReminderCount": len(review_keys),
        "eduardoTicketReminderCount": len(ticket_keys),
        "sent": False,
        "dryRun": bool(dry_run),
    }
    if not body:
        outcome["status"] = "no_reminder_needed" if active else "no_active_shift"
        write_cache(cache_path, outcome)
        return outcome
    if dry_run:
        outcome["status"] = "dry_run_due"
        write_cache(cache_path, outcome)
        return outcome

    request_keys = sorted([*review_keys, *ticket_keys])
    request_hash = hashlib.sha256(("\n".join(request_keys) + "\n" + body).encode("utf-8")).hexdigest()
    send_result = (
        sender(body)
        if sender is not None
        else _send_zoom_channel_message(body, shift_started_at=earliest)
    )
    message_id = str(send_result.get("messageId") or "").strip()
    if not send_result.get("ok") or not message_id:
        outcome.update({"ok": False, "status": "uncertain", "sent": False})
        write_cache(cache_path, outcome)
        return outcome

    append_state(
        state_path,
        {
            "atUtc": _iso(resolved_now),
            "requestHash": request_hash,
            "keys": request_keys,
            "messageId": message_id,
            "channelId": GHOST_BUSTERS_CHANNEL_ID,
            "readbackVerified": True,
        },
    )
    outcome.update(
        {
            "status": "sent",
            "sent": True,
            "messageId": message_id,
            "readbackVerified": True,
        }
    )
    write_cache(cache_path, outcome)
    return outcome


def parse_schedule(values: list[list[Any]], *, tab: str) -> list[Shift]:
    year = 2000 + int(tab[-2:])
    local_tz = ZoneInfo(TIMEZONE_NAME)
    shifts: list[Shift] = []
    headers: list[tuple[int, list[tuple[int, datetime]]]] = []
    for header_index, row in enumerate(values):
        day_columns: list[tuple[int, datetime]] = []
        for column, value in enumerate(row):
            parsed_date = _parse_schedule_date(str(value or ""), year=year, tz=local_tz)
            if parsed_date is not None:
                day_columns.append((column, parsed_date))
        if day_columns:
            headers.append((header_index, day_columns))

    for position, (header_index, day_columns) in enumerate(headers):
        next_header_index = headers[position + 1][0] if position + 1 < len(headers) else len(values)
        for candidate in values[header_index + 1 : next_header_index]:
            name = str(candidate[0] if candidate else "").strip().casefold()
            if name in {"", "totals"}:
                continue
            rep = REP_BY_SCHEDULE_NAME.get(name)
            if rep is None:
                continue
            for column, day in day_columns:
                marker = _cell(candidate, column).casefold()
                start_text = _cell(candidate, column + 1)
                end_text = _cell(candidate, column + 2)
                if marker == "x" or not start_text or not end_text:
                    continue
                start_time = _parse_time(start_text)
                end_time = _parse_time(end_text)
                if start_time is None or end_time is None:
                    continue
                start = datetime.combine(day.date(), start_time, local_tz)
                end = datetime.combine(day.date(), end_time, local_tz)
                if end <= start:
                    end += timedelta(days=1)
                shifts.append(Shift(rep=rep, start=start, end=end))
    unique = {shift.key: shift for shift in shifts}
    return sorted(unique.values(), key=lambda shift: (shift.start, shift.rep.email))


def has_review_activity(shift: Shift, messages: Iterable[dict[str, Any]], now: datetime) -> bool:
    end = min(shift.end, now.astimezone(shift.start.tzinfo))
    for message in messages:
        sender = str(
            message.get("sender")
            or message.get("sender_email")
            or message.get("senderEmail")
            or ""
        ).strip().casefold()
        if sender != shift.rep.email:
            continue
        stamp = _message_timestamp(message)
        if stamp is not None and shift.start <= stamp.astimezone(shift.start.tzinfo) <= end:
            return True
    return False


def build_message(*, names: list[str], remind_eduardo: bool) -> str:
    parts: list[str] = []
    if names:
        distinct = list(dict.fromkeys(names))
        parts.append(
            f"Hey team, {', '.join(distinct)}, please make sure you're sending customer review requests this shift."
        )
    if remind_eduardo:
        parts.append("Eduardo, please look over the open tickets while you're on.")
    return " ".join(parts)


def read_state(path: Path) -> set[str]:
    keys: set[str] = set()
    if not path.exists():
        return keys
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            row = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict) or not row.get("readbackVerified"):
            continue
        values = row.get("keys") if isinstance(row.get("keys"), list) else []
        keys.update(str(value) for value in values if str(value).strip())
    return keys


def append_state(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")


def write_cache(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(payload, handle, sort_keys=True, separators=(",", ":"))
        handle.write("\n")
        temp_path = Path(handle.name)
    os.replace(temp_path, path)


def _read_schedule_values(tab: str) -> list[list[Any]]:
    adc_path = Path(os.getenv("RORY_GOOGLE_WORKSPACE_ADC_PATH", "")).expanduser()
    if not adc_path.is_file():
        raise RuntimeError("Google Workspace schedule credential is unavailable")
    credentials = Credentials.from_authorized_user_file(str(adc_path), scopes=list(WORKSPACE_SCOPES))
    session = AuthorizedSession(credentials)
    encoded_range = urllib.parse.quote(f"'{tab}'!A1:AF200", safe="!:$'(),-._~")
    url = (
        "https://sheets.googleapis.com/v4/spreadsheets/"
        f"{SCHEDULE_SPREADSHEET_ID}/values/{encoded_range}"
    )
    response = session.get(
        url,
        params={
            "majorDimension": "ROWS",
            "valueRenderOption": "FORMATTED_VALUE",
            "dateTimeRenderOption": "FORMATTED_STRING",
        },
        timeout=45,
    )
    if response.status_code != 200:
        raise RuntimeError(f"Schedule read failed with HTTP {response.status_code}")
    payload = response.json()
    values = payload.get("values") if isinstance(payload, dict) else []
    return values if isinstance(values, list) else []


def _read_zoom_history(channel_id: str, start: datetime, end: datetime) -> list[dict[str, Any]]:
    token = get_zoom_token()
    rows: list[dict[str, Any]] = []
    next_token = ""
    for _ in range(MAX_HISTORY_PAGES):
        params = {
            "to_channel": channel_id,
            "from": start.date().isoformat(),
            "to": end.date().isoformat(),
            "page_size": "100",
        }
        if next_token:
            params["next_page_token"] = next_token
        payload = _zoom_request(token, "GET", "/chat/users/me/messages", params=params)
        page = payload.get("messages") if isinstance(payload.get("messages"), list) else []
        rows.extend(row for row in page if isinstance(row, dict))
        next_token = str(payload.get("next_page_token") or "").strip()
        if not next_token:
            break
    return rows


def _send_zoom_channel_message(body: str, *, shift_started_at: datetime) -> dict[str, Any]:
    token = get_zoom_token()
    shift_started_utc = _as_utc(shift_started_at)

    def is_current_shift_match(row: dict[str, Any]) -> bool:
        stamp = _message_timestamp(row)
        return (
            str(row.get("message") or "") == body
            and stamp is not None
            and _as_utc(stamp) >= shift_started_utc
        )

    before = _read_zoom_history(
        GHOST_BUSTERS_CHANNEL_ID,
        shift_started_at,
        datetime.now(ZoneInfo(TIMEZONE_NAME)),
    )
    exact_before = [row for row in before if is_current_shift_match(row)]
    if exact_before:
        message_id = str(exact_before[-1].get("id") or exact_before[-1].get("message_id") or "")
        return {"ok": bool(message_id), "messageId": message_id, "duplicatePrevented": True}
    created = _zoom_request(
        token,
        "POST",
        "/chat/users/me/messages",
        json_body={"message": body, "to_channel": GHOST_BUSTERS_CHANNEL_ID},
    )
    ids = created.get("ids") if isinstance(created.get("ids"), list) else []
    message_id = str(ids[0] if ids else created.get("id") or "").strip()
    if not message_id:
        reconciled = [
            row
            for row in _read_zoom_history(
                GHOST_BUSTERS_CHANNEL_ID,
                shift_started_at,
                datetime.now(ZoneInfo(TIMEZONE_NAME)),
            )
            if is_current_shift_match(row)
        ]
        if len(reconciled) != 1:
            return {"ok": False, "status": "uncertain"}
        message_id = str(reconciled[0].get("id") or reconciled[0].get("message_id") or "").strip()
    readback = _zoom_request(
        token,
        "GET",
        f"/chat/users/me/messages/{urllib.parse.quote(message_id, safe='')}",
        params={"to_channel": GHOST_BUSTERS_CHANNEL_ID},
    )
    if (
        str(readback.get("id") or readback.get("message_id") or "") != message_id
        or str(readback.get("message") or "") != body
    ):
        return {"ok": False, "status": "uncertain", "messageId": message_id}
    return {"ok": True, "messageId": message_id, "readbackVerified": True}


def _zoom_request(
    token: str,
    method: str,
    path: str,
    *,
    params: dict[str, str] | None = None,
    json_body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    url = ZOOM_BASE_URL + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    data = None
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    if json_body is not None:
        data = json.dumps(json_body, separators=(",", ":")).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"Zoom reminder API failed with HTTP {exc.code}") from exc
    if not raw.strip():
        return {}
    payload = json.loads(raw)
    return payload if isinstance(payload, dict) else {"data": payload}


def _parse_schedule_date(value: str, *, year: int, tz: ZoneInfo) -> datetime | None:
    clean = value.strip()
    if "," not in clean:
        return None
    try:
        parsed = datetime.strptime(f"{clean}, {year}", "%A, %B %d, %Y").replace(tzinfo=tz)
    except ValueError:
        return None
    return parsed


def _parse_time(value: str) -> time | None:
    clean = value.strip()
    for pattern in ("%H:%M", "%I:%M %p", "%I %p"):
        try:
            return datetime.strptime(clean, pattern).time()
        except ValueError:
            continue
    return None


def _cell(row: list[Any], index: int) -> str:
    return str(row[index] if index < len(row) else "").strip()


def _message_timestamp(message: dict[str, Any]) -> datetime | None:
    value = message.get("date_time") or message.get("dateTime") or message.get("timestamp") or message.get("time")
    if isinstance(value, (int, float)):
        seconds = float(value) / 1000.0 if float(value) > 10_000_000_000 else float(value)
        return datetime.fromtimestamp(seconds, timezone.utc)
    if not value:
        return None
    try:
        return _parse_timestamp(str(value))
    except ValueError:
        return None


def _parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return _as_utc(value).isoformat().replace("+00:00", "Z")


def _public_summary(result: dict[str, Any]) -> dict[str, Any]:
    return {
        key: result.get(key)
        for key in (
            "ok",
            "status",
            "checkedAtUtc",
            "scheduleTab",
            "activeShiftCount",
            "reviewReminderCount",
            "eduardoTicketReminderCount",
            "sent",
            "dryRun",
            "readbackVerified",
        )
        if key in result
    }


if __name__ == "__main__":
    main()
