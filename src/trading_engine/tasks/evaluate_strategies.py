from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from celery import shared_task
from sqlalchemy import select

from src.api.database.database import SessionLocal
from src.models.price_bar import PriceBar as PriceBarModel
from src.models.simulator import Simulator
from src.models.simulator_position import SimulatorPosition
from src.models.simulator_tracked_stock import SimulatorTrackedStock
from src.trading_engine.services.portfolio import PortfolioSnapshot, Position
from src.trading_engine.services.pricing import PriceBar
from src.trading_engine.services.strategy import (
    Signal,
    SimpleMovingAverageStrategy,
    StrategyRegistry,
    StrategyService,
)


@shared_task(name="trading_engine.evaluate_strategies")
def evaluate_strategies(
    user_id: int | None = None,
    params: dict | None = None,
) -> dict:
    params = params or {}
    targets = load_target_portfolios(user_id)
    strategy_registry = build_strategy_registry()
    strategy_service = StrategyService(strategy_registry)
    strategy_name = str(params.get("strategy_name", "sma_crossover"))

    simulator_results: list[dict] = []
    total_signals = 0
    skipped = 0
    errors = 0

    for simulator in targets:
        simulator_id = int(simulator.simulator_id)
        try:
            snapshot = load_portfolio_snapshot(simulator_id)
            prices = load_price_history_for_portfolio(simulator_id, params)
            if not prices:
                skipped += 1
                simulator_results.append(
                    {
                        "simulator_id": simulator_id,
                        "status": "skipped_price_data_missing",
                        "signals_count": 0,
                    }
                )
                continue

            signals = evaluate_portfolio_strategies(
                strategy_service=strategy_service,
                strategy_name=strategy_name,
                prices=prices,
                portfolio_snapshot=snapshot,
                params=params,
            )
            saved_signals = persist_signals(simulator_id, signals)
            total_signals += len(saved_signals)
            simulator_results.append(
                {
                    "simulator_id": simulator_id,
                    "status": "ok",
                    "signals_count": len(saved_signals),
                }
            )
        except Exception as exc:
            errors += 1
            simulator_results.append(
                {
                    "simulator_id": simulator_id,
                    "status": "error",
                    "error": str(exc),
                }
            )

    return build_evaluation_summary(
        user_id=user_id,
        strategy_name=strategy_name,
        simulators_processed=len(targets),
        total_signals=total_signals,
        skipped=skipped,
        errors=errors,
        simulator_results=simulator_results,
    )


def load_target_portfolios(user_id: int | None = None) -> list[Simulator]:
    session = SessionLocal()
    try:
        stmt = (
            select(Simulator)
            .join(
                SimulatorTrackedStock,
                SimulatorTrackedStock.simulator_id == Simulator.simulator_id,
            )
            .where(SimulatorTrackedStock.enabled.is_(True))
            .distinct()
            .order_by(Simulator.simulator_id)
        )
        if user_id is not None:
            stmt = stmt.where(Simulator.user_id == user_id)
            simulators = session.execute(stmt).scalars().all()
        return simulators
    finally:
        session.close()


def load_portfolio_snapshot(simulator_id: int) -> PortfolioSnapshot:
    session = SessionLocal()
    try:
        stmt = select(Simulator).where(Simulator.simulator_id == simulator_id)
        simulator = session.execute(stmt).scalars().first()
        if simulator is None:
            raise ValueError(f"Simulator not found for simulator_id={simulator_id}")
        if simulator.user_id is None:
            raise ValueError(
                f"Simulator {simulator_id} is not associated with a user_id"
            )

        position_stmt = select(SimulatorPosition).where(
            SimulatorPosition.simulator_id == simulator_id
        )
        simulator_positions = session.execute(position_stmt).scalars().all()

        positions: dict[str, Position] = {}
        for simulator_position in simulator_positions:
            symbol = simulator_position.ticker.strip().upper()
            if not symbol:
                continue
            positions[symbol] = Position(
                symbol=symbol,
                quantity=float(simulator_position.shares),
                average_cost=float(simulator_position.avg_cost),
            )

        as_of = simulator.updated_at or datetime.now(timezone.utc)
        return PortfolioSnapshot(
            user_id=int(simulator.user_id),
            cash=float(simulator.cash_balance),
            positions=positions,
            as_of=as_of,
        )
    finally:
        session.close()


def load_price_history_for_portfolio(
    simulator_id: int,
    params: dict,
) -> list[PriceBar]:
    session = SessionLocal()
    try:
        tracked_stmt = (
            select(SimulatorTrackedStock)
            .where(SimulatorTrackedStock.simulator_id == simulator_id)
            .where(SimulatorTrackedStock.enabled.is_(True))
        )
        tracked_stocks = session.execute(tracked_stmt).scalars().all()

        tickers = sorted(
            {
                tracked_stock.ticker.strip().upper()
                for tracked_stock in tracked_stocks
                if tracked_stock.ticker and tracked_stock.ticker.strip()
            }
        )
        if not tickers:
            return []

        long_window = int(params.get("long_window", 20))
        buffer_days = int(params.get("buffer_days", 10))
        end_day = date.today()
        start_day = end_day - timedelta(days=long_window + buffer_days)

        prices_stmt = (
            select(PriceBarModel)
            .where(PriceBarModel.symbol.in_(tickers))
            .where(PriceBarModel.day >= start_day)
            .where(PriceBarModel.day <= end_day)
            .where(PriceBarModel.source == "yfinance")
            .order_by(PriceBarModel.symbol, PriceBarModel.day)
        )
        rows = session.execute(prices_stmt).scalars().all()
        return [
            PriceBar(
                symbol=row.symbol,
                day=row.day,
                open=float(row.open),
                high=float(row.high),
                low=float(row.low),
                close=float(row.close),
                volume=int(row.volume),
                source=row.source,
            )
            for row in rows
        ]
    finally:
        session.close()


def build_strategy_registry() -> StrategyRegistry:
    registry = StrategyRegistry()
    registry.register(SimpleMovingAverageStrategy()) # default to using SMA
    return registry


def evaluate_portfolio_strategies(
    strategy_service: StrategyService,
    strategy_name: str,
    prices: list[PriceBar],
    portfolio_snapshot: PortfolioSnapshot,
    params: dict,
) -> list[Signal]:
    signals = strategy_service.evaluate(
        strategy_name=strategy_name,
        prices=prices,
        portfolio=portfolio_snapshot,
        params=params,
    )
    return validate_signal_batch(signals)


def validate_signal_batch(signals: list[Signal]) -> list[Signal]:
    valid_actions = {"buy", "sell", "hold"}
    cleaned: list[Signal] = []
    for signal in signals:
        if signal.action not in valid_actions:
            continue
        if signal.quantity < 0:
            continue
        symbol = signal.symbol.strip().upper()
        if not symbol:
            continue
        cleaned.append(signal)
    return cleaned


def persist_signals(simulator_id: int, signals: list[Signal]) -> list[dict]:
    # Placeholder until a dedicated simulator_signals table/model exists.
    # Returns serialized signal payloads so downstream orchestration can be verified.
    return [
        {
            "simulator_id": simulator_id,
            "symbol": signal.symbol,
            "action": signal.action,
            "quantity": signal.quantity,
            "reason": signal.reason,
            "confidence": signal.confidence,
            "strategy_name": signal.strategy_name,
            "created_at": signal.created_at.isoformat(),
        }
        for signal in signals
    ]


def build_evaluation_summary(
    user_id: int | None,
    strategy_name: str,
    simulators_processed: int,
    total_signals: int,
    skipped: int,
    errors: int,
    simulator_results: list[dict],
) -> dict:
    return {
        "user_id": user_id,
        "strategy_name": strategy_name,
        "simulators_processed": simulators_processed,
        "total_signals": total_signals,
        "skipped": skipped,
        "errors": errors,
        "simulator_results": simulator_results,
    }
