from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

import src.trading_engine.services.history as history_module
import src.trading_engine.services.pricing as pricing_module
import src.trading_engine.tasks.daily_pipeline as pipeline_module
from src.core.config import settings
from src.core.database import get_db
from src.core.security import get_current_active_user
from src.main import app
from src.models.price_bar import PriceBar
from src.models.users import Users

SIGNAL_DAY = date(2024, 3, 7)  # Thursday: AAPL closes on a dip
FILL_DAY = date(2024, 3, 8)  # Friday: the order fills at this open


@pytest.fixture
def client(db, monkeypatch):
    """The real API, engine and database; only Yahoo and the clock are faked."""

    def _get_db():
        with db.session() as session:
            yield session

    class _Yahoo:  # bars are seeded by the tests instead of downloaded
        def fetch_daily_bars_range(self, symbols, start_day, end_day):
            return []

    class _Pricing:
        def __init__(self, **_):
            pass

        def fetch_and_store_daily_bars(self, symbols, day):
            return len(symbols)

    db.add(Users(user_id=1, name="u", email="u@x", password="p", is_active=True))
    monkeypatch.setattr(pricing_module, "YahooPriceProvider", _Yahoo)
    monkeypatch.setattr(history_module, "last_completed_trading_day", lambda: SIGNAL_DAY)
    monkeypatch.setattr(pipeline_module, "PricingService", _Pricing)
    monkeypatch.setattr(settings, "sim_fee_per_trade", Decimal("0"))
    monkeypatch.setattr(settings, "sim_slippage_bps", Decimal("0"))
    monkeypatch.setattr(settings, "sim_max_order_value", None)
    app.dependency_overrides[get_db] = _get_db
    app.dependency_overrides[get_current_active_user] = lambda: Users(user_id=1)
    yield TestClient(app)
    app.dependency_overrides.clear()


def _seed_prices(db) -> None:
    db.bars("AAPL", [date(2024, 3, 1), date(2024, 3, 4), date(2024, 3, 5), date(2024, 3, 6)], "100")
    db.bars("AAPL", [SIGNAL_DAY], "90")  # 8% under the 5-day average: a dip to buy
    db.add(PriceBar(symbol="AAPL", day=FILL_DAY, open=Decimal("95"), high=Decimal("98"),
                    low=Decimal("94"), close=Decimal("97"), volume=1000, source="yfinance"))


def _run(client: TestClient, monkeypatch, simulator_id: int, day: date) -> dict:
    monkeypatch.setattr(pipeline_module, "last_completed_trading_day", lambda: day)
    response = client.post(f"/api/simulator/{simulator_id}/run", json={})
    assert response.status_code == 200
    return response.json()


def test_simulator_trades_with_its_strategy_settings(db, client, monkeypatch) -> None:
    _seed_prices(db)
    strategies = {s["value"] for s in client.get("/api/strategies").json()}
    assert "auction_liquidity_provider" in strategies

    sim_id = client.post(
        "/api/simulator", json={"name": "Bot", "starting_cash": 10000}
    ).json()["simulator_id"]
    settings_response = client.patch(
        f"/api/simulator/{sim_id}/settings",
        json={"strategy_name": "auction_liquidity_provider", "strategy_params": {"trade_size": 5}},
    )
    assert settings_response.json()["strategy_params"] == {
        "deviation_threshold": 0.02,
        "trade_size": 5.0,
    }
    added = client.post(
        f"/api/simulator/{sim_id}/tracked-stocks", json={"ticker": "aapl", "target_allocation": 10}
    )
    assert added.status_code == 200

    # Day 1: the dip is spotted at the close; the buy waits for the next open.
    first = _run(client, monkeypatch, sim_id, SIGNAL_DAY)
    assert (first["trades_executed"], first["orders_queued"]) == (0, 1)

    # Day 2: the buy fills at the open, and the portfolio is rebuilt from the trade.
    second = _run(client, monkeypatch, sim_id, FILL_DAY)
    assert (second["trades_executed"], second["orders_queued"]) == (1, 0)

    summary = client.get(f"/api/simulator/{sim_id}").json()
    [trade] = summary["trades"]
    assert (trade["side"], Decimal(str(trade["shares"])), Decimal(str(trade["price"]))) == (
        "buy", Decimal("5"), Decimal("95"),
    )
    [position] = summary["positions"]
    assert (position["ticker"], Decimal(str(position["shares"]))) == ("AAPL", Decimal("5"))
    assert Decimal(str(summary["simulator"]["cash_balance"])) == Decimal("9525")
    # Day 2's close was back near its average: the latest decision says why it held.
    [decision] = summary["decisions"]
    assert (decision["ticker"], decision["action"]) == ("AAPL", "hold")
    assert "within" in decision["reason"]


def test_adding_stock_without_enough_history_explains_why(db, client) -> None:
    _seed_prices(db)  # 5 trading days of AAPL
    sim_id = client.post(
        "/api/simulator", json={"name": "Bot", "starting_cash": 10000}
    ).json()["simulator_id"]
    client.patch(f"/api/simulator/{sim_id}/settings", json={"strategy_name": "sma_50_200_crossover"})

    response = client.post(
        f"/api/simulator/{sim_id}/tracked-stocks", json={"ticker": "AAPL", "target_allocation": 10}
    )

    assert response.status_code == 400
    assert response.json()["detail"] == (
        "Not enough price history: SMA 50/200 (Golden Cross) needs 201 trading days, "
        "but AAPL has 5. Pick a shorter-term strategy or a smaller window."
    )
    assert client.get(f"/api/simulator/{sim_id}").json()["tracked_stocks"] == []
