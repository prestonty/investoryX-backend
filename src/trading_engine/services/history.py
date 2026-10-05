from __future__ import annotations

from datetime import date, timedelta

from src.trading_engine.strategies.catalog import get_entry, history_bars

from .evaluation import EvaluationService
from .pricing import backfill_symbol_history, count_price_bars, last_completed_trading_day

# Calendar days of history every tracked ticker gets, whatever its strategy.
# Covers the longest default lookback: SMA 50/200 loads 201 bars + 201 buffer days.
DEFAULT_HISTORY_DAYS = 420


class InsufficientPriceHistoryError(Exception):
    """Tracked stocks don't have the daily bars the simulator's strategy needs."""

    def __init__(self, strategy_label: str, required_bars: int, available: dict[str, int]) -> None:
        self.strategy_label = strategy_label
        self.required_bars = required_bars
        self.available = available  # symbol -> trading days of history it has
        super().__init__(self._message())

    def _message(self) -> str:
        short = {symbol: bars for symbol, bars in self.available.items() if bars > 0}
        missing = [symbol for symbol, bars in self.available.items() if bars == 0]
        sentences = []
        if short:
            have = ", ".join(f"{symbol} has {bars}" for symbol, bars in short.items())
            sentences.append(
                f"Not enough price history: {self.strategy_label} needs "
                f"{self.required_bars} trading days, but {have}. "
                "Pick a shorter-term strategy or a smaller window."
            )
        if missing:
            sentences.append(
                f"No price history found for {', '.join(missing)}. "
                "Check the ticker or try again later."
            )
        return " ".join(sentences)


def ensure_price_history(
    symbols: list[str],
    strategy_name: str,
    params: dict,
    as_of: date | None = None,
) -> None:
    """Load each symbol's history and check the strategy can evaluate it.

    Raises InsufficientPriceHistoryError naming every symbol that falls short.
    """
    if not symbols:
        return
    as_of = as_of or last_completed_trading_day()
    required = history_bars(strategy_name, params)
    # The same window evaluation reads, so passing here means evaluation has enough.
    window_days = EvaluationService().resolve_history_days(params, strategy_name)
    load_from = as_of - timedelta(days=max(window_days, DEFAULT_HISTORY_DAYS))

    available: dict[str, int] = {}
    for symbol in symbols:
        backfill_symbol_history(symbol, load_from, as_of)
        bars = count_price_bars(symbol, as_of - timedelta(days=window_days), as_of)
        if bars < required:
            available[symbol] = bars
    if available:
        raise InsufficientPriceHistoryError(get_entry(strategy_name).label, required, available)
