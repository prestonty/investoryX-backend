from __future__ import annotations

from src.trading_engine.services.portfolio import PortfolioSnapshot
from src.trading_engine.services.pricing import PriceBar
from src.trading_engine.services.strategy import Signal


class ManualStrategy:
    """No automated decisions: the user places every order by hand.

    Evaluation skips simulators on this strategy entirely; it is registered so a
    simulator can switch between manual and automated trading like any other
    strategy change.
    """

    name = "manual"

    def generate_signals(
        self,
        prices: list[PriceBar],
        portfolio: PortfolioSnapshot,
        params: dict,
    ) -> list[Signal]:
        return []
