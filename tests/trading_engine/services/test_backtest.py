from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest

import src.trading_engine.services.backtest as backtest_module
from src.models.simulator import Simulator
from src.models.simulator_trade import SimulatorTrade
from src.trading_engine.services.backtest import BacktestService
from src.trading_engine.services.pricing import PriceBar, _is_trading_day


def _rising_bars(symbol: str, start: date, end: date) -> list[PriceBar]:
    bars: list[PriceBar] = []
    day, price = start, Decimal("100")
    while day <= end:
        if _is_trading_day(day):
            # Dip then rally so the short SMA crosses above the long SMA.
            price += Decimal("-1") if len(bars) < 30 else Decimal("3")
            bars.append(PriceBar(symbol, day, price, price, price, price, 1000, "yfinance"))
        day += timedelta(days=1)
    return bars


@pytest.fixture
def fake_provider(monkeypatch: pytest.MonkeyPatch) -> dict:
    calls: dict = {}

    class _Provider:
        def fetch_daily_bars_range(self, symbols, start_day, end_day):
            calls["start_day"] = start_day
            return [bar for s in symbols for bar in _rising_bars(s, start_day, end_day)]

    monkeypatch.setattr(backtest_module, "YahooPriceProvider", _Provider)
    return calls


def test_backtest_does_not_touch_live_cash(db, fake_provider) -> None:
    db.simulator(1, cash="10000")

    result = BacktestService().run(1, date(2024, 3, 1), date(2024, 4, 30))

    assert result.total_trades > 0
    assert db.get(Simulator, 1).cash_balance == Decimal("10000")
    assert {t.source for t in db.all(SimulatorTrade, simulator_id=1)} == {"backtest"}


def test_backtest_pnl_includes_value_of_held_shares(db, fake_provider) -> None:
    db.simulator(1, cash="10000")

    result = BacktestService().run(1, date(2024, 3, 1), date(2024, 4, 30))

    # The rising market leaves the SMA strategy holding shares at the end.
    assert result.holdings_value > 0
    assert result.final_equity == result.final_cash + result.holdings_value
    assert result.pnl == result.final_equity - result.starting_cash
    # Buying into a rally must not be reported as a loss of the cash spent.
    assert result.pnl > 0
    payload = result.to_dict()
    assert Decimal(payload["final_equity"]) == result.final_equity


def test_backtest_lookback_covers_long_window(db, fake_provider) -> None:
    db.simulator(1, strategy_name="sma_50_200_crossover")
    start = date(2024, 3, 1)

    BacktestService().run(1, start, date(2024, 3, 29))

    # 200-day window plus buffer, in calendar days (was a fixed 35 days).
    assert (start - fake_provider["start_day"]).days >= 400
