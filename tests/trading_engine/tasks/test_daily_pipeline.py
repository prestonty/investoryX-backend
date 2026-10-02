from __future__ import annotations

from datetime import date

import pytest

import src.trading_engine.tasks.daily_pipeline as pipeline_module
from src.trading_engine.services.execution import ExecutionSummary

TRADING_DAY = date(2024, 3, 8)


class _Evaluation:
    def to_dict(self) -> dict:
        return {"simulator_results": []}


@pytest.fixture
def stages(monkeypatch: pytest.MonkeyPatch) -> dict:
    """Replace every stage with a recorder; `bars` controls how many prices get stored."""
    state: dict = {"calls": [], "bars": 3}

    class _Pricing:
        def __init__(self, **_):
            pass

        def fetch_and_store_daily_bars(self, symbols, day):
            state["calls"].append(("fetch", day))
            return state["bars"]

    class _EvaluationService:
        def run(self, as_of_day, simulator_id):
            state["calls"].append(("evaluate", as_of_day))
            return _Evaluation()

    def _execute(**kwargs):
        state["calls"].append(("execute", kwargs["day"]))
        return ExecutionSummary(0, 0, 0, 0, 0)

    def _reconcile(simulator_id):
        state["calls"].append(("reconcile", simulator_id))
        return {"reconciled": 0}

    monkeypatch.setattr(pipeline_module, "get_all_enabled_simulator_tickers", lambda _id: ["AAPL"])
    monkeypatch.setattr(pipeline_module, "YahooPriceProvider", lambda: None)
    monkeypatch.setattr(pipeline_module, "SqlPriceBarRepository", lambda: None)
    monkeypatch.setattr(pipeline_module, "PricingService", _Pricing)
    monkeypatch.setattr(pipeline_module, "EvaluationService", _EvaluationService)
    monkeypatch.setattr(pipeline_module, "execute_signals", _execute)
    monkeypatch.setattr(pipeline_module, "reconcile_portfolios", _reconcile)
    return state


def test_stages_run_in_order_for_the_same_day(stages) -> None:
    result = pipeline_module.run_pipeline(day=TRADING_DAY)

    # Yesterday's orders fill at today's open before today's close is evaluated,
    # so strategies see the portfolio after those fills.
    assert stages["calls"] == [
        ("fetch", TRADING_DAY),
        ("execute", TRADING_DAY),
        ("reconcile", None),
        ("evaluate", TRADING_DAY),
    ]
    assert result["day"] == "2024-03-08"
    assert result["trades_executed"]["executed"] == 0


def test_non_trading_day_does_nothing(stages) -> None:
    result = pipeline_module.run_pipeline(day=date(2025, 11, 27))  # Thanksgiving

    assert result == {"day": "2025-11-27", "skipped": "not a trading day"}
    assert stages["calls"] == []


def test_missing_prices_stop_before_execution(stages) -> None:
    stages["bars"] = 0

    with pytest.raises(pipeline_module.MissingPriceDataError):
        pipeline_module.run_pipeline(day=TRADING_DAY)

    assert stages["calls"] == [("fetch", TRADING_DAY)]


def test_task_retries_when_prices_are_missing(stages, monkeypatch: pytest.MonkeyPatch) -> None:
    stages["bars"] = 0
    retries: list[dict] = []

    class _Retry(Exception):
        pass

    def _fake_retry(**kwargs):
        retries.append(kwargs)
        return _Retry()

    monkeypatch.setattr(pipeline_module.run_daily_pipeline, "retry", _fake_retry)

    with pytest.raises(_Retry):
        pipeline_module.run_daily_pipeline("2024-03-08")

    assert retries[0]["countdown"] == pipeline_module.PRICE_RETRY_DELAY_SECONDS
    assert isinstance(retries[0]["exc"], pipeline_module.MissingPriceDataError)
