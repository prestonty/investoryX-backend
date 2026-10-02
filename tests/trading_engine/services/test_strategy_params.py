from __future__ import annotations

from datetime import date, timedelta

import pytest

from src.models.simulator_signal import SimulatorSignal
from src.trading_engine.services.evaluation import EvaluationService
from src.trading_engine.strategies.catalog import (
    CATALOG,
    InvalidStrategyParams,
    describe_strategies,
    effective_params,
    history_bars,
    params_to_store,
)

AS_OF = date(2024, 3, 8)


def test_effective_params_fill_defaults() -> None:
    assert effective_params("sma_crossover", {"short_window": 10}) == {
        "short_window": 10,
        "long_window": 20,
        "trade_quantity": 1.0,
    }


@pytest.mark.parametrize(
    "params, message",
    [
        ({"short_window": 30}, "short_window must be smaller than long_window"),
        ({"trade_quantity": 0}, "trade_quantity"),
        ({"unknown": 1}, "unknown"),
    ],
)
def test_invalid_params_are_rejected(params, message) -> None:
    with pytest.raises(InvalidStrategyParams, match=message):
        effective_params("sma_crossover", params)


def test_params_to_store_keeps_only_given_keys() -> None:
    assert params_to_store("stat_arb_pairs", {"symbol_a": " pep ", "window": 30}) == {
        "symbol_a": "PEP",
        "window": 30,
    }
    assert params_to_store("stat_arb_pairs", {}) is None


@pytest.mark.parametrize(
    "strategy_name, params, expected",
    [
        ("sma_crossover", {"long_window": 50}, 51),
        ("sma_50_200_crossover", {}, 201),
        ("stat_arb_pairs", {"window": 60}, 60),
        # Run options like buffer_days aren't strategy params and must not break it.
        ("auction_liquidity_provider", {"buffer_days": 3}, 5),
    ],
)
def test_history_bars_follow_params(strategy_name, params, expected) -> None:
    assert history_bars(strategy_name, params) == expected


def test_catalog_describes_every_strategy_with_bounds() -> None:
    options = {option["value"]: option for option in describe_strategies()}

    assert set(options) == set(CATALOG)
    short_window = next(
        p for p in options["sma_crossover"]["params"] if p["name"] == "short_window"
    )
    assert short_window == {
        "name": "short_window",
        "label": "Short SMA (days)",
        "type": "integer",
        "default": 5,
        "min": 1,
        "max": 200,
    }


def test_run_overrides_win_over_saved_params() -> None:
    params = EvaluationService().resolve_strategy_params(
        "sma_crossover", {"short_window": 3}, {"short_window": 4, "strategy_name": "x"}
    )

    assert params["short_window"] == 4
    assert "strategy_name" not in params


def test_saved_params_size_the_price_history(db) -> None:
    db.simulator(1, strategy_params={"long_window": 60})
    db.bars("AAPL", [AS_OF - timedelta(days=d) for d in (0, 100, 200)])

    params = EvaluationService().resolve_strategy_params("sma_crossover", {"long_window": 60})
    bars = EvaluationService().load_price_history_for_portfolio(
        1, params, "sma_crossover", AS_OF
    )

    # 61 bars + 61 buffer days = 122 calendar days back: includes day -100, not -200.
    assert sorted(bar.day for bar in bars) == [AS_OF - timedelta(days=100), AS_OF]


def test_invalid_saved_params_fail_only_that_simulator(db) -> None:
    db.simulator(1, strategy_params={"short_window": 50})  # not below long_window
    db.simulator(2, tickers=("MSFT",))
    db.bars("AAPL", [AS_OF])
    db.bars("MSFT", [AS_OF])

    summary = EvaluationService().run(as_of_day=AS_OF)

    statuses = {r["simulator_id"]: r["status"] for r in summary.simulator_results}
    assert statuses == {1: "error", 2: "ok"}
    assert {s.simulator_id for s in db.all(SimulatorSignal)} == {2}
