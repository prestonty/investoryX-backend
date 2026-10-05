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
    ],
)
def test_is_trading_day(day: date, expected: bool) -> None:
    assert _is_trading_day(day) is expected


def test_last_completed_trading_day() -> None:
    after_close = datetime(2025, 11, 26, 16, 30, tzinfo=MARKET_TZ)
    monday_morning = datetime(2025, 12, 1, 9, 0, tzinfo=MARKET_TZ)

    assert last_completed_trading_day(after_close) == date(2025, 11, 26)
    assert last_completed_trading_day(monday_morning) == date(2025, 11, 28)
