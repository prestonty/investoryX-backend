from __future__ import annotations

from datetime import date, timedelta

from src.models.simulator import SIMULATOR_STATUS_PAUSED
from src.models.simulator_signal import SimulatorSignal
from src.trading_engine.services.evaluation import (
    STATUS_OK,
    STATUS_SKIPPED_ALREADY_EVALUATED,
    STATUS_SKIPPED_PRICE_DATA_MISSING,
    EvaluationService,
)

AS_OF = date(2024, 3, 8)  # a Friday well in the past, so "now" is after its close


def _days_back(count: int) -> list[date]:
    return [AS_OF - timedelta(days=offset) for offset in range(count)]


def test_symbols_without_as_of_bar_are_dropped(db) -> None:
    db.simulator(1, tickers=("AAPL", "MSFT"))
    db.bars("AAPL", _days_back(5))
    db.bars("MSFT", _days_back(5)[1:])  # MSFT is missing AS_OF

    bars = EvaluationService().load_price_history_for_portfolio(1, {}, "sma_crossover", AS_OF)

    assert {bar.symbol for bar in bars} == {"AAPL"}


def test_no_fresh_bars_skips_simulator(db) -> None:
    db.simulator(1)
    db.bars("AAPL", _days_back(5)[1:])

    summary = EvaluationService().run(as_of_day=AS_OF)

    assert summary.simulator_results[0]["status"] == STATUS_SKIPPED_PRICE_DATA_MISSING
    assert db.all(SimulatorSignal) == []


def test_second_evaluation_for_same_day_is_skipped(db) -> None:
    db.simulator(1)
    db.bars("AAPL", _days_back(5))

    first = EvaluationService().run(as_of_day=AS_OF)
    signals_after_first = len(db.all(SimulatorSignal))
    second = EvaluationService().run(as_of_day=AS_OF)

    assert first.simulator_results[0]["status"] == STATUS_OK
    assert signals_after_first > 0
    assert second.simulator_results[0]["status"] == STATUS_SKIPPED_ALREADY_EVALUATED
    assert len(db.all(SimulatorSignal)) == signals_after_first


def test_paused_simulators_are_not_evaluated(db) -> None:
    db.simulator(1, tickers=("AAPL",))
    db.simulator(2, tickers=("AAPL",), status=SIMULATOR_STATUS_PAUSED)

    targets = EvaluationService().load_target_portfolios()

    assert [sim.simulator_id for sim in targets] == [1]


def test_simulator_id_scopes_evaluation(db) -> None:
    db.simulator(1)
    db.simulator(2)
    db.bars("AAPL", _days_back(5))

    summary = EvaluationService().run(as_of_day=AS_OF, simulator_id=2)

    assert [r["simulator_id"] for r in summary.simulator_results] == [2]
    assert {s.simulator_id for s in db.all(SimulatorSignal)} == {2}
