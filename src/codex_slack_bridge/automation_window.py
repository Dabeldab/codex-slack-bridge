"""Shared daily gate for Nova's unattended background automation."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, time, timedelta, timezone
from typing import Any, Mapping
from zoneinfo import ZoneInfo


DEFAULT_TIMEZONE = "America/New_York"
DEFAULT_START = "08:00"
DEFAULT_END = "19:00"


def _parse_local_time(value: object, *, field: str) -> time:
    text = str(value or "").strip()
    try:
        parsed = datetime.strptime(text, "%H:%M").time()
    except ValueError as exc:
        raise ValueError(f"{field} must use 24-hour HH:MM format") from exc
    return parsed.replace(second=0, microsecond=0)


def _aware_now(value: datetime | None, zone: ZoneInfo) -> datetime:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("now must include a timezone")
    return current.astimezone(zone)


def automation_window_status(
    defaults: Mapping[str, Any] | None = None,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    settings = defaults or {}
    enabled = bool(settings.get("automation_window_enabled", True))
    timezone_name = str(settings.get("automation_window_timezone") or DEFAULT_TIMEZONE).strip()
    start_text = str(settings.get("automation_window_local_start") or DEFAULT_START).strip()
    end_text = str(settings.get("automation_window_local_end") or DEFAULT_END).strip()
    zone = ZoneInfo(timezone_name)
    local_now = _aware_now(now, zone)
    start = _parse_local_time(start_text, field="automation_window_local_start")
    end = _parse_local_time(end_text, field="automation_window_local_end")
    if start == end:
        raise ValueError("automation window start and end cannot match")

    local_time = local_now.time().replace(tzinfo=None)
    if start < end:
        is_open = start <= local_time < end
        if local_time < start:
            next_change = datetime.combine(local_now.date(), start, zone)
            next_state = "open"
        elif local_time < end:
            next_change = datetime.combine(local_now.date(), end, zone)
            next_state = "closed"
        else:
            next_change = datetime.combine(local_now.date() + timedelta(days=1), start, zone)
            next_state = "open"
    else:
        is_open = local_time >= start or local_time < end
        if local_time >= start:
            next_change = datetime.combine(local_now.date() + timedelta(days=1), end, zone)
            next_state = "closed"
        elif local_time < end:
            next_change = datetime.combine(local_now.date(), end, zone)
            next_state = "closed"
        else:
            next_change = datetime.combine(local_now.date(), start, zone)
            next_state = "open"

    if not enabled:
        is_open = True
        next_change = None
        next_state = "unchanged"

    return {
        "ok": True,
        "enabled": enabled,
        "open": is_open,
        "state": "open" if is_open else "closed",
        "timezone": timezone_name,
        "localStart": start_text,
        "localEnd": end_text,
        "localNow": local_now.isoformat(),
        "nextState": next_state,
        "nextChangeLocal": next_change.isoformat() if next_change else None,
        "nextChangeUtc": next_change.astimezone(timezone.utc).isoformat() if next_change else None,
        "interactiveAgentsAvailable": True,
        "manualRunsAllowed": True,
    }


def automation_window_open(
    defaults: Mapping[str, Any] | None = None,
    *,
    now: datetime | None = None,
) -> bool:
    return bool(automation_window_status(defaults, now=now)["open"])


def _parse_instant(value: str) -> datetime:
    text = str(value or "").strip().replace("Z", "+00:00")
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        raise ValueError("--at must include a UTC offset")
    return parsed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check Nova's unattended automation window.")
    parser.add_argument("--timezone", default=DEFAULT_TIMEZONE)
    parser.add_argument("--start", default=DEFAULT_START)
    parser.add_argument("--end", default=DEFAULT_END)
    parser.add_argument("--at", default="", help="Optional ISO-8601 test instant with a UTC offset.")
    args = parser.parse_args(argv)
    status = automation_window_status(
        {
            "automation_window_enabled": True,
            "automation_window_timezone": args.timezone,
            "automation_window_local_start": args.start,
            "automation_window_local_end": args.end,
        },
        now=_parse_instant(args.at) if args.at else None,
    )
    print(json.dumps(status, sort_keys=True, separators=(",", ":")))
    return 0 if status["open"] else 3


if __name__ == "__main__":
    raise SystemExit(main())
