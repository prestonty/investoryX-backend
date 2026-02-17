from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select

from src.api.database.database import SessionLocal
from src.models.price_bar import PriceBar as PriceBarModel
from src.models.simulator import Simulator
from src.models.simulator_position import SimulatorPosition
from src.models.simulator_signal import SimulatorSignal
from src.models.simulator_tracked_stock import SimulatorTrackedStock

from .execution import SignalExecutionStatus
from .portfolio import PortfolioSnapshot, Position
from .pricing import PriceBar
from .strategy import (
    Signal,
    SignalAction,
    SimpleMovingAverageStrategy,
    StrategyRegistry,
    StrategyService,
)

STATUS_OK = "ok"
STATUS_ERROR = "error"
STATUS_SKIPPED_PRICE_DATA_MISSING = "skipped_price_data_missing"


@dataclass
class EvaluationRunStats:
    total_signals: int = 0
    skipped: int = 0
    errors: int = 0


@dataclass(frozen=True)
class EvaluationSummary:
    user_id: int | None
    strategy_name: str
    simulators_processed: int
    total_signals: int
    skipped: int
    errors: int
    simulator_results: list[dict]

    def to_dict(self) -> dict:
        return {
            "user_id": self.user_id,
            "strategy_name": self.strategy_name,
            "simulators_processed": self.simulators_processed,
            "total_signals": self.total_signals,
            "skipped": self.skipped,
            "errors": self.errors,
            "simulator_results": self.simulator_results,
        }


@dataclass(frozen=True)
class SimulatorEvaluationResult:
    simulator_id: int
    status: str
    signals_count: int = 0
    error: str | None = None

    def to_dict(self) -> dict:
        payload = {
            "simulator_id": self.simulator_id,
            "status": self.status,
            "signals_count": self.signals_count,
        }
        if self.error is not None:
            payload["error"] = self.error
        return payload


class EvaluationService:
    """Runs strategy evaluation for one or many simulators and persists signals."""

    def run(
        self,
        user_id: int | None = None,
        params: dict | None = None,
    ) -> EvaluationSummary:
        params = params or {}
        targets = self.load_target_portfolios(user_id)
        strategy_registry = self.build_strategy_registry()
        strategy_service = StrategyService(strategy_registry)
        strategy_name = str(params.get("strategy_name", "sma_crossover"))

        simulator_results: list[dict] = []
        stats = EvaluationRunStats()

        for simulator in targets:
            simulator_id = int(simulator.simulator_id)
            result = self._evaluate_one_simulator(
                simulator_id=simulator_id,
                strategy_service=strategy_service,
                strategy_name=strategy_name,
                params=params,
            )
            simulator_results.append(result.to_dict())
            if result.status == STATUS_OK:
                stats.total_signals += int(result.signals_count)
            elif result.status == STATUS_SKIPPED_PRICE_DATA_MISSING:
                stats.skipped += 1
            elif result.status == STATUS_ERROR:
                stats.errors += 1

        return self.build_evaluation_summary(
            user_id=user_id,
            strategy_name=strategy_name,
            simulators_processed=len(targets),
            total_signals=stats.total_signals,
            skipped=stats.skipped,
            errors=stats.errors,
            simulator_results=simulator_results,
        )

    def _evaluate_one_simulator(
        self,
        simulator_id: int,
        strategy_service: StrategyService,
        strategy_name: str,
        params: dict,
    ) -> SimulatorEvaluationResult:
        try:
            snapshot = self.load_portfolio_snapshot(simulator_id)
            prices = self.load_price_history_for_portfolio(simulator_id, params)
            if not prices:
                return self._build_skipped_result(simulator_id)

            signals = self.evaluate_portfolio_strategies(
                strategy_service=strategy_service,
                strategy_name=strategy_name,
                prices=prices,
                portfolio_snapshot=snapshot,
                params=params,
            )
            saved_signals = self.persist_signals(simulator_id, signals)
            return self._build_ok_result(simulator_id, len(saved_signals))
        except Exception as exc:
            return self._build_error_result(simulator_id, str(exc))

    def _build_ok_result(
        self, simulator_id: int, signals_count: int
    ) -> SimulatorEvaluationResult:
        return SimulatorEvaluationResult(
            simulator_id=simulator_id,
            status=STATUS_OK,
            signals_count=signals_count,
        )

    def _build_skipped_result(self, simulator_id: int) -> SimulatorEvaluationResult:
        return SimulatorEvaluationResult(
            simulator_id=simulator_id,
            status=STATUS_SKIPPED_PRICE_DATA_MISSING,
            signals_count=0,
        )

    def _build_error_result(
        self, simulator_id: int, error: str
    ) -> SimulatorEvaluationResult:
        return SimulatorEvaluationResult(
            simulator_id=simulator_id,
            status=STATUS_ERROR,
            error=error,
        )

    def load_target_portfolios(self, user_id: int | None = None) -> list[Simulator]:
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
            return session.execute(stmt).scalars().all()
        finally:
            session.close()

    def load_portfolio_snapshot(self, simulator_id: int) -> PortfolioSnapshot:
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
                    quantity=Decimal(str(simulator_position.shares)),
                    average_cost=Decimal(str(simulator_position.avg_cost)),
                )

            as_of = simulator.updated_at or datetime.now(timezone.utc)
            return PortfolioSnapshot(
                user_id=int(simulator.user_id),
                cash=Decimal(str(simulator.cash_balance)),
                positions=positions,
                as_of=as_of,
            )
        finally:
            session.close()

    def load_price_history_for_portfolio(
        self,
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
                    open=Decimal(str(row.open)),
                    high=Decimal(str(row.high)),
                    low=Decimal(str(row.low)),
                    close=Decimal(str(row.close)),
                    volume=int(row.volume),
                    source=row.source,
                )
                for row in rows
            ]
        finally:
            session.close()

    def build_strategy_registry(self) -> StrategyRegistry:
        registry = StrategyRegistry()
        registry.register(SimpleMovingAverageStrategy())
        return registry

    def evaluate_portfolio_strategies(
        self,
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
        return self.validate_signal_batch(signals)

    def validate_signal_batch(self, signals: list[Signal]) -> list[Signal]:
        valid_actions = {action.value for action in SignalAction}
        cleaned: list[Signal] = []
        for signal in signals:
            if signal.action.value not in valid_actions:
                continue
            if signal.quantity < Decimal("0"):
                continue
            symbol = signal.symbol.strip().upper()
            if not symbol:
                continue
            cleaned.append(signal)
        return cleaned

    def persist_signals(
        self,
        simulator_id: int,
        signals: list[Signal],
    ) -> list[SimulatorSignal]:
        if not signals:
            return []

        session = SessionLocal()
        try:
            rows = [
                SimulatorSignal(
                    simulator_id=simulator_id,
                    ticker=signal.symbol.strip().upper(),
                    action=signal.action.value,
                    quantity=signal.quantity,
                    reason=signal.reason,
                    confidence=signal.confidence,
                    strategy_name=signal.strategy_name,
                    status=SignalExecutionStatus.PENDING.value,
                    created_at=signal.created_at,
                )
                for signal in signals
            ]
            session.add_all(rows)
            session.commit()
            for row in rows:
                session.refresh(row)
            return rows
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def build_evaluation_summary(
        self,
        user_id: int | None,
        strategy_name: str,
        simulators_processed: int,
        total_signals: int,
        skipped: int,
        errors: int,
        simulator_results: list[dict],
    ) -> EvaluationSummary:
        return EvaluationSummary(
            user_id=user_id,
            strategy_name=strategy_name,
            simulators_processed=simulators_processed,
            total_signals=total_signals,
            skipped=skipped,
            errors=errors,
            simulator_results=simulator_results,
        )
