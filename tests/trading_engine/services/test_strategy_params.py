from __future__ import annotations

from src.trading_engine.strategies.catalog import effective_params


def test_saved_params_are_merged_with_defaults() -> None:
    assert effective_params("sma_crossover", {"short_window": 10}) == {
        "short_window": 10,
        "long_window": 20,
        "trade_quantity": 1.0,
    }
