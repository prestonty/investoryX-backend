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


def test_signals_record_the_day_they_were_evaluated_for(db) -> None:
    db.simulator(1)
    db.bars("AAPL", _days_back(5))

    EvaluationService().run(as_of_day=AS_OF)

    assert {s.for_day for s in db.all(SimulatorSignal)} == {AS_OF}


def test_concurrent_run_is_stopped_by_unique_constraint(db, monkeypatch) -> None:
    db.simulator(1)
    db.bars("AAPL", _days_back(5))
    EvaluationService().run(as_of_day=AS_OF)
    count = len(db.all(SimulatorSignal))

    # Simulate a second run that passed the pre-check before the first one committed.
    racing = EvaluationService()
    monkeypatch.setattr(racing, "has_signals_for_day", lambda *_: False)
    summary = racing.run(as_of_day=AS_OF)

    assert summary.simulator_results[0]["status"] == STATUS_SKIPPED_ALREADY_EVALUATED
    assert len(db.all(SimulatorSignal)) == count


def test_legacy_undated_signal_after_close_still_counts_as_evaluated(db) -> None:
    from datetime import datetime, timezone
    from decimal import Decimal

    db.simulator(1)
    db.add(SimulatorSignal(
        simulator_id=1, ticker="AAPL", action="hold", quantity=Decimal("0"), reason="old",
        confidence=Decimal("0"), strategy_name="sma_crossover", status="skipped",
        created_at=datetime(2024, 3, 8, 21, 30, tzinfo=timezone.utc),  # 4:30 PM ET on AS_OF
        for_day=None,
    ))

    assert EvaluationService().has_signals_for_day(1, AS_OF) is True
    assert EvaluationService().has_signals_for_day(1, AS_OF + timedelta(days=3)) is False


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
