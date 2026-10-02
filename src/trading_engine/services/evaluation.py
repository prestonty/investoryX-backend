from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import and_, or_, select
from sqlalchemy.exc import IntegrityError

from src.core.database import SessionLocal
from src.models.price_bar import PriceBar as PriceBarModel
from src.models.simulator import SIMULATOR_STATUS_PAUSED, Simulator
from src.models.simulator_position import SimulatorPosition
from src.models.simulator_signal import SimulatorSignal
from src.models.simulator_tracked_stock import SimulatorTrackedStock
from src.trading_engine.strategies.catalog import (
    DEFAULT_STRATEGY_NAME,
    build_registry,
    effective_params,
    history_bars,
)

from .actions import SignalAction
from .execution import SignalExecutionStatus
from .portfolio import PortfolioSnapshot, Position
from .pricing import MARKET_CLOSE, MARKET_TZ, PriceBar, last_completed_trading_day
from .strategy import Signal, StrategyRegistry, StrategyService

STATUS_OK = "ok"
STATUS_ERROR = "error"
STATUS_SKIPPED_PRICE_DATA_MISSING = "skipped_price_data_missing"
STATUS_SKIPPED_ALREADY_EVALUATED = "skipped_already_evaluated"


class AlreadyEvaluatedError(Exception):
    """Signals for this simulator and trading day were already saved by another run."""


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
        as_of_day: date | None = None,
        simulator_id: int | None = None,
    ) -> EvaluationSummary:
        params = params or {}
        as_of_day = as_of_day or last_completed_trading_day()
        targets = self.load_target_portfolios(user_id, simulator_id)
        strategy_registry = self.build_strategy_registry()
        strategy_service = StrategyService(strategy_registry)
        # strategy_name can be overridden globally via params, otherwise each simulator uses its own
        global_strategy_name = params.get("strategy_name")

        simulator_results: list[dict] = []
        stats = EvaluationRunStats()

        for simulator in targets:
            simulator_id = int(simulator.simulator_id)
            strategy_name = (
                global_strategy_name or simulator.strategy_name or DEFAULT_STRATEGY_NAME
            )
            # Saved params belong to the simulator's own strategy only.
            stored_params = (
                simulator.strategy_params
                if strategy_name == simulator.strategy_name
                else None
            )
            result = self._evaluate_one_simulator(
                simulator_id=simulator_id,
                strategy_service=strategy_service,
                strategy_name=strategy_name,
                stored_params=stored_params,
                overrides=params,
                as_of_day=as_of_day,
            )
            simulator_results.append(result.to_dict())
            if result.status == STATUS_OK:
                stats.total_signals += int(result.signals_count)
            elif result.status in (
                STATUS_SKIPPED_PRICE_DATA_MISSING,
                STATUS_SKIPPED_ALREADY_EVALUATED,
            ):
                stats.skipped += 1
            elif result.status == STATUS_ERROR:
                stats.errors += 1

        return self.build_evaluation_summary(
            user_id=user_id,
            strategy_name=global_strategy_name or "per_simulator",
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
        stored_params: dict | None,
        overrides: dict,
        as_of_day: date,
    ) -> SimulatorEvaluationResult:
        try:
            if self.has_signals_for_day(simulator_id, as_of_day):
                return self._build_skipped_result(
                    simulator_id, STATUS_SKIPPED_ALREADY_EVALUATED
                )
            params = self.resolve_strategy_params(strategy_name, stored_params, overrides)
            snapshot = self.load_portfolio_snapshot(simulator_id)
            prices = self.load_price_history_for_portfolio(
                simulator_id,
                params,
                strategy_name,
                as_of_day,
            )
            if not prices:
                return self._build_skipped_result(simulator_id)

            signals = self.evaluate_portfolio_strategies(
                strategy_service=strategy_service,
                strategy_name=strategy_name,
                prices=prices,
                portfolio_snapshot=snapshot,
                params=params,
            )
            try:
                saved_signals = self.persist_signals(simulator_id, signals, as_of_day)
            except AlreadyEvaluatedError:
                # A concurrent run evaluated this day between the pre-check and the insert.
                return self._build_skipped_result(simulator_id, STATUS_SKIPPED_ALREADY_EVALUATED)
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

    def _build_skipped_result(
        self,
        simulator_id: int,
        status: str = STATUS_SKIPPED_PRICE_DATA_MISSING,
    ) -> SimulatorEvaluationResult:
        return SimulatorEvaluationResult(
            simulator_id=simulator_id,
            status=status,
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

    def load_target_portfolios(
        self,
        user_id: int | None = None,
        simulator_id: int | None = None,
    ) -> list[Simulator]:
        session = SessionLocal()
        try:
            stmt = (
                select(Simulator)
                .join(
                    SimulatorTrackedStock,
                    SimulatorTrackedStock.simulator_id == Simulator.simulator_id,
                )
                .where(SimulatorTrackedStock.enabled.is_(True))
                .where(Simulator.status != SIMULATOR_STATUS_PAUSED)
                .distinct()
                .order_by(Simulator.simulator_id)
            )
            if user_id is not None:
                stmt = stmt.where(Simulator.user_id == user_id)
            if simulator_id is not None:
                stmt = stmt.where(Simulator.simulator_id == simulator_id)
            return session.execute(stmt).scalars().all()
        finally:
            session.close()

    def has_signals_for_day(self, simulator_id: int, as_of_day: date) -> bool:
        """True if this simulator was already evaluated on as_of_day's prices.

        Keeps the scheduled pipeline, manual runs and dev runs from creating
        duplicate signals (and duplicate trades) for the same prices. This is a
        fast pre-check; the unique constraint on (simulator_id, for_day, ticker)
        is what actually prevents duplicates when runs race (see persist_signals).
        """
        # Signals saved before for_day existed have it NULL. Evaluation for a day
        # only runs after that day's close, so for those, any signal created at or
        # after the close means the day was evaluated.
        day_close = datetime.combine(as_of_day, MARKET_CLOSE, tzinfo=MARKET_TZ)
        session = SessionLocal()
        try:
            stmt = (
                select(SimulatorSignal.signal_id)
                .where(SimulatorSignal.simulator_id == simulator_id)
                .where(
                    or_(
                        SimulatorSignal.for_day == as_of_day,
                        and_(
                            SimulatorSignal.for_day.is_(None),
                            SimulatorSignal.created_at >= day_close.astimezone(timezone.utc),
                        ),
                    )
                )
                .limit(1)
            )
            return session.execute(stmt).first() is not None
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
        strategy_name: str,
        as_of_day: date,
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

            end_day = as_of_day
            start_day = end_day - timedelta(
                days=self.resolve_history_days(params, strategy_name)
            )

            prices_stmt = (
                select(PriceBarModel)
                .where(PriceBarModel.symbol.in_(tickers))
                .where(PriceBarModel.day >= start_day)
                .where(PriceBarModel.day <= end_day)
                .where(PriceBarModel.source == "yfinance")
                .order_by(PriceBarModel.symbol, PriceBarModel.day)
            )
            rows = session.execute(prices_stmt).scalars().all()
            bars = [
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
            return filter_to_fresh_symbols(bars, as_of_day)
        finally:
            session.close()

    def build_strategy_registry(self) -> StrategyRegistry:
        return build_registry()

    def resolve_strategy_params(
        self,
        strategy_name: str,
        stored_params: dict | None,
        overrides: dict | None = None,
    ) -> dict:
        """The simulator's saved params (validated, defaults filled), then run overrides."""
        params = effective_params(strategy_name, stored_params)
        params.update(
            {key: value for key, value in (overrides or {}).items() if key != "strategy_name"}
        )
        return params

    def resolve_history_days(self, params: dict, strategy_name: str) -> int:
        """Calendar days of price history one evaluation of this strategy needs."""
        bars = history_bars(strategy_name, params)
        return bars + self.resolve_buffer_days(params, bars)

    def resolve_buffer_days(self, params: dict, bars: int) -> int:
        if "buffer_days" in params:
            buffer_days = int(params["buffer_days"])
        else:
            # Calendar days contain weekends/holidays; widen history by default.
            buffer_days = max(10, bars)
        if buffer_days < 0:
            raise ValueError("buffer_days must be >= 0")
        return buffer_days

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
        for_day: date,
    ) -> list[SimulatorSignal]:
        """Save signals for for_day; raises AlreadyEvaluatedError if another run did first."""
        if not signals:
            return []

        by_ticker = one_signal_per_ticker(signals)
        session = SessionLocal()
        try:
            rows = [
                SimulatorSignal(
                    simulator_id=simulator_id,
                    ticker=ticker,
                    action=signal.action.value,
                    quantity=signal.quantity,
                    reason=signal.reason,
                    confidence=signal.confidence,
                    strategy_name=signal.strategy_name,
                    status=SignalExecutionStatus.PENDING.value,
                    created_at=signal.created_at,
                    for_day=for_day,
                )
                for ticker, signal in by_ticker.items()
            ]
            session.add_all(rows)
            session.commit()
            for row in rows:
                session.refresh(row)
            return rows
        except IntegrityError as exc:
            session.rollback()
            raise AlreadyEvaluatedError(
                f"simulator_id={simulator_id} already has signals for {for_day.isoformat()}"
            ) from exc
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


def filter_to_fresh_symbols(bars: list[PriceBar], as_of_day: date) -> list[PriceBar]:
    """Drop every symbol that has no bar for as_of_day.

    Without today's bar a strategy would re-evaluate yesterday's prices and
    repeat yesterday's decision, so stale symbols must not be evaluated.
    """
    fresh_symbols = {bar.symbol for bar in bars if bar.day == as_of_day}
    return [bar for bar in bars if bar.symbol in fresh_symbols]


def one_signal_per_ticker(signals: list[Signal]) -> dict[str, Signal]:
    """At most one signal per ticker per day (the unique constraint's shape)."""
    by_ticker: dict[str, Signal] = {}
    for signal in signals:
        by_ticker.setdefault(signal.symbol.strip().upper(), signal)
    return by_ticker
