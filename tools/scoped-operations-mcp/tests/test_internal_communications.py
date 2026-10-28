from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from threading import Barrier

from scoped_operations_mcp.internal_communications import (
    internal_request_day,
    restore_verified_internal_request_day,
)


def test_internal_request_day_uses_new_york_date_and_keeps_raw_identity_out(
    tmp_path: Path,
) -> None:
    journal = tmp_path / "verified-requests.jsonl"
    recipient = "leo@novapointofsale.com"

    with internal_request_day(
        recipient,
        journal_path=journal,
        now=datetime(2026, 7, 29, 3, 59, tzinfo=timezone.utc),
    ) as first:
        assert first.local_date == "2026-07-28"
        assert first.greeting_required is True
        first.record_verified(channel="salesforce", provider_id="0D5000000000001")

    with internal_request_day(
        recipient,
        journal_path=journal,
        now=datetime(2026, 7, 29, 3, 59, 30, tzinfo=timezone.utc),
    ) as same_day:
        assert same_day.local_date == "2026-07-28"
        assert same_day.greeting_required is False
        same_day.record_verified(channel="salesforce", provider_id="0D5000000000002")

    with internal_request_day(
        recipient,
        journal_path=journal,
        now=datetime(2026, 7, 29, 4, 0, tzinfo=timezone.utc),
    ) as next_day:
        assert next_day.local_date == "2026-07-29"
        assert next_day.greeting_required is True
        next_day.record_verified(channel="zoom", provider_id="zoom-message-1")

    raw = journal.read_text(encoding="utf-8")
    rows = [json.loads(line) for line in raw.splitlines()]
    assert len(rows) == 2
    assert [row["localDate"] for row in rows] == ["2026-07-28", "2026-07-29"]
    assert recipient not in raw
    assert "0D5000000000001" not in raw
    assert "zoom-message-1" not in raw
    assert all(
        set(row)
        == {
            "channel",
            "localDate",
            "providerIdSha256",
            "recipientSha256",
            "status",
            "time",
        }
        for row in rows
    )


def test_internal_request_day_serializes_concurrent_agents(
    tmp_path: Path,
) -> None:
    journal = tmp_path / "verified-requests.jsonl"
    start = Barrier(2)

    def verify_request(index: int) -> bool:
        start.wait()
        with internal_request_day(
            "005000000000001",
            journal_path=journal,
            now=datetime(2026, 7, 29, 15, 0, tzinfo=timezone.utc),
        ) as request:
            greeting_required = request.greeting_required
            request.record_verified(
                channel="salesforce",
                provider_id=f"0D500000000000{index}",
            )
            return greeting_required

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(verify_request, (1, 2)))

    assert sorted(results) == [False, True]
    assert len(journal.read_text(encoding="utf-8").splitlines()) == 1


def test_restore_verified_day_repairs_same_day_but_never_suppresses_next_day(
    tmp_path: Path,
) -> None:
    journal = tmp_path / "verified-requests.jsonl"
    instant = datetime(2026, 7, 29, 15, 0, tzinfo=timezone.utc)

    restored_old_day = restore_verified_internal_request_day(
        "wiko@example.test",
        verified_local_date="2026-07-28",
        channel="zoom",
        provider_id="old-message",
        journal_path=journal,
        now=instant,
    )
    assert restored_old_day is False
    assert not journal.exists()

    restored_same_day = restore_verified_internal_request_day(
        "wiko@example.test",
        verified_local_date="2026-07-29",
        channel="zoom",
        provider_id="same-day-message",
        journal_path=journal,
        now=instant,
    )
    assert restored_same_day is True

    with internal_request_day(
        "wiko@example.test",
        journal_path=journal,
        now=instant,
    ) as request:
        assert request.greeting_required is False

    raw = journal.read_text(encoding="utf-8")
    assert "wiko@example.test" not in raw
    assert "same-day-message" not in raw
