from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

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


def test_backtest_trades_a_rally_without_touching_live_portfolio(db, monkeypatch) -> None:
    class _Provider:
        def fetch_daily_bars_range(self, symbols, start_day, end_day):
            return [bar for s in symbols for bar in _rising_bars(s, start_day, end_day)]

    monkeypatch.setattr(backtest_module, "YahooPriceProvider", _Provider)
    db.simulator(1, cash="10000", strategy_params={"trade_quantity": 3})

    result = BacktestService().run(1, date(2024, 3, 1), date(2024, 4, 30))

    trades = db.all(SimulatorTrade, simulator_id=1)
    assert trades and {t.shares for t in trades} == {Decimal("3")}  # simulator's settings
    assert result.pnl > 0  # buying into a rally, held shares valued at the last close
    assert result.final_equity == result.final_cash + result.holdings_value
    assert db.get(Simulator, 1).cash_balance == Decimal("10000")  # live cash untouched
