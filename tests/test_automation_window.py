from datetime import datetime

import pytest

from codex_slack_bridge.automation_window import automation_window_status


DEFAULTS = {
    "automation_window_enabled": True,
    "automation_window_timezone": "America/New_York",
    "automation_window_local_start": "08:00",
    "automation_window_local_end": "19:00",
}


@pytest.mark.parametrize(
    ("instant", "is_open"),
    [
        ("2026-01-15T07:59:59-05:00", False),
        ("2026-01-15T08:00:00-05:00", True),
        ("2026-01-15T18:59:59-05:00", True),
        ("2026-01-15T19:00:00-05:00", False),
        ("2026-07-15T08:00:00-04:00", True),
        ("2026-07-15T19:00:00-04:00", False),
    ],
)
def test_daily_window_is_start_inclusive_and_end_exclusive(instant, is_open):
    status = automation_window_status(DEFAULTS, now=datetime.fromisoformat(instant))

    assert status["open"] is is_open
    assert status["state"] == ("open" if is_open else "closed")
    assert status["timezone"] == "America/New_York"
    assert status["interactiveAgentsAvailable"] is True
    assert status["manualRunsAllowed"] is True


def test_closed_window_reports_the_next_dst_aware_opening():
    status = automation_window_status(
        DEFAULTS,
        now=datetime.fromisoformat("2026-07-15T21:00:00-04:00"),
    )

    assert status["open"] is False
    assert status["nextState"] == "open"
    assert status["nextChangeLocal"] == "2026-07-16T08:00:00-04:00"
    assert status["nextChangeUtc"] == "2026-07-16T12:00:00+00:00"


def test_disabled_window_keeps_automation_open():
    status = automation_window_status(
        {**DEFAULTS, "automation_window_enabled": False},
        now=datetime.fromisoformat("2026-07-15T23:00:00-04:00"),
    )

    assert status["open"] is True
    assert status["nextState"] == "unchanged"
    assert status["nextChangeLocal"] is None


@pytest.mark.parametrize(
    "defaults",
    [
        {**DEFAULTS, "automation_window_local_start": "8am"},
        {**DEFAULTS, "automation_window_local_end": "08:00", "automation_window_local_start": "08:00"},
        {**DEFAULTS, "automation_window_timezone": "Not/AZone"},
    ],
)
def test_invalid_window_configuration_fails_closed_at_startup(defaults):
    with pytest.raises((ValueError, KeyError)):
        automation_window_status(defaults, now=datetime.fromisoformat("2026-07-15T12:00:00-04:00"))
