from __future__ import annotations

from datetime import date, datetime

import pytest

from src.trading_engine.services.pricing import (
    MARKET_TZ,
    _is_trading_day,
    last_completed_trading_day,
)


@pytest.mark.parametrize(
    ("day", "expected"),
    [
        (date(2025, 11, 26), True),   # ordinary Wednesday
        (date(2025, 11, 29), False),  # Saturday
        (date(2025, 11, 27), False),  # Thanksgiving
        (date(2025, 4, 18), False),   # Good Friday
        (date(2025, 6, 19), False),   # Juneteenth
        (date(2026, 7, 3), False),    # July 4th on Saturday, observed Friday
        (date(2022, 12, 30), True),   # New Year's on Saturday is not observed on Friday
        (date(2021, 6, 18), True),    # Juneteenth observance begins in 2022
    ],
)
def test_is_trading_day(day: date, expected: bool) -> None:
    assert _is_trading_day(day) is expected


def _et(*args: int) -> datetime:
    return datetime(*args, tzinfo=MARKET_TZ)


def test_before_close_uses_previous_trading_day() -> None:
    assert last_completed_trading_day(_et(2025, 11, 26, 15, 59)) == date(2025, 11, 25)


def test_at_close_uses_same_day() -> None:
    assert last_completed_trading_day(_et(2025, 11, 26, 16, 0)) == date(2025, 11, 26)


def test_monday_morning_uses_previous_friday() -> None:
    assert last_completed_trading_day(_et(2025, 12, 1, 9, 0)) == date(2025, 11, 28)


def test_skips_holidays() -> None:
    # Evening of Thanksgiving: last completed session is Wednesday.
    assert last_completed_trading_day(_et(2025, 11, 27, 18, 0)) == date(2025, 11, 26)


def test_converts_other_timezones_to_eastern() -> None:
    # 20:30 UTC is 16:30 EDT on the same day.
    utc = datetime.fromisoformat("2025-06-10T20:30:00+00:00")
    assert last_completed_trading_day(utc) == date(2025, 6, 10)
