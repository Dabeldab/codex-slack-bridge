from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

try:
    import fcntl
except ImportError:  # pragma: no cover - production runtime is Linux.
    fcntl = None


DEFAULT_INTERNAL_COMMUNICATION_JOURNAL = (
    "/var/lib/nova/broker/internal-comms/verified-requests.jsonl"
)
try:
    INTERNAL_COMMUNICATION_TIMEZONE = ZoneInfo("America/New_York")
except ZoneInfoNotFoundError:  # Windows test runtimes may not bundle tzdata.
    INTERNAL_COMMUNICATION_TIMEZONE = None
_THREAD_LOCK = threading.RLock()


@dataclass
class InternalRequestDay:
    greeting_required: bool
    local_date: str
    recipient_sha256: str
    journal_path: Path
    _recorded: bool = False

    def record_verified(self, *, channel: str, provider_id: str = "") -> None:
        if self._recorded:
            return
        if not self.greeting_required:
            # The journal is shared greeting state, not a second copy of each
            # provider's operation log. One verified row per recipient/day is
            # enough, and keeps retries or later requests from growing it.
            self._recorded = True
            return
        clean_channel = str(channel or "").strip().casefold()
        if clean_channel not in {"salesforce", "zoom"}:
            raise ValueError("internal request channel is invalid")
        provider_hash = (
            hashlib.sha256(str(provider_id).encode("utf-8")).hexdigest()
            if str(provider_id or "").strip()
            else ""
        )
        record = {
            "time": int(time.time()),
            "status": "verified",
            "localDate": self.local_date,
            "recipientSha256": self.recipient_sha256,
            "channel": clean_channel,
            "providerIdSha256": provider_hash,
        }
        descriptor = os.open(
            self.journal_path,
            os.O_APPEND | os.O_CREAT | os.O_WRONLY,
            0o660,
        )
        try:
            os.fchmod(descriptor, 0o660)
        except (OSError, AttributeError):
            # A second broker may be a group writer rather than the owner.
            # On Windows, os.fchmod doesn't exist (AttributeError) or fails (OSError).
            pass
        with os.fdopen(descriptor, "a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n"
            )
            handle.flush()
            os.fsync(handle.fileno())
        self._recorded = True


@contextmanager
def internal_request_day(
    recipient_key: str,
    *,
    journal_path: str | Path | None = None,
    now: datetime | None = None,
) -> Iterator[InternalRequestDay]:
    """Serialize employee requests and determine the first verified contact today."""

    normalized_key = " ".join(str(recipient_key or "").split()).casefold()
    if not normalized_key:
        raise ValueError("internal request recipient key is required")
    path = Path(
        journal_path
        or os.getenv("NOVA_INTERNAL_COMMUNICATION_JOURNAL_PATH")
        or DEFAULT_INTERNAL_COMMUNICATION_JOURNAL
    )
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o770)
    lock_path = Path(f"{path}.lock")
    descriptor = os.open(
        lock_path,
        os.O_APPEND | os.O_CREAT | os.O_WRONLY,
        0o660,
    )
    try:
        os.fchmod(descriptor, 0o660)
    except (OSError, AttributeError):
        # The shared group already owns production files created by the other
        # broker; group write access is sufficient even when chmod is not.
        pass
    instant = now or datetime.now(timezone.utc)
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=timezone.utc)
    local_date = _new_york_date(instant)
    recipient_sha256 = hashlib.sha256(normalized_key.encode("utf-8")).hexdigest()

    with _THREAD_LOCK, os.fdopen(descriptor, "a", encoding="utf-8") as handle:
        try:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            seen_today = False
            if path.is_file():
                with path.open("r", encoding="utf-8") as journal:
                    for line in journal:
                        try:
                            row = json.loads(line)
                        except (TypeError, ValueError):
                            continue
                        if (
                            row.get("status") == "verified"
                            and row.get("localDate") == local_date
                            and row.get("recipientSha256") == recipient_sha256
                        ):
                            seen_today = True
            yield InternalRequestDay(
                greeting_required=not seen_today,
                local_date=local_date,
                recipient_sha256=recipient_sha256,
                journal_path=path,
            )
        finally:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def restore_verified_internal_request_day(
    recipient_key: str,
    *,
    verified_local_date: str,
    channel: str,
    provider_id: str = "",
    journal_path: str | Path | None = None,
    now: datetime | None = None,
) -> bool:
    """Restore missing shared state only on the provider operation's own NY day."""

    clean_date = str(verified_local_date or "").strip()
    try:
        date.fromisoformat(clean_date)
    except ValueError:
        return False
    with internal_request_day(
        recipient_key,
        journal_path=journal_path,
        now=now,
    ) as request:
        if request.local_date != clean_date:
            return False
        request.record_verified(channel=channel, provider_id=provider_id)
        return True


def _new_york_date(instant: datetime) -> str:
    if INTERNAL_COMMUNICATION_TIMEZONE is not None:
        return instant.astimezone(INTERNAL_COMMUNICATION_TIMEZONE).date().isoformat()

    utc = instant.astimezone(timezone.utc)
    year = utc.year
    march_first = datetime(year, 3, 1, tzinfo=timezone.utc)
    first_march_sunday = 1 + ((6 - march_first.weekday()) % 7)
    second_march_sunday = first_march_sunday + 7
    dst_start_utc = datetime(
        year,
        3,
        second_march_sunday,
        7,
        tzinfo=timezone.utc,
    )
    november_first = datetime(year, 11, 1, tzinfo=timezone.utc)
    first_november_sunday = 1 + ((6 - november_first.weekday()) % 7)
    dst_end_utc = datetime(
        year,
        11,
        first_november_sunday,
        6,
        tzinfo=timezone.utc,
    )
    offset = -4 if dst_start_utc <= utc < dst_end_utc else -5
    return (utc + timedelta(hours=offset)).date().isoformat()