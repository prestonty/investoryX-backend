from __future__ import annotations

import logging
from bisect import bisect_right
from dataclasses import dataclass, field, asdict
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from src.core.database import SessionLocal
from src.models.simulator import Simulator
from src.models.simulator_cash_ledger import SimulatorCashLedger
from src.models.simulator_trade import SimulatorTrade
from src.models.simulator_tracked_stock import SimulatorTrackedStock
from src.trading_engine.strategies.catalog import DEFAULT_STRATEGY_NAME

from .actions import SignalAction
from .evaluation import EvaluationService, filter_to_fresh_symbols, one_signal_per_ticker
from .execution import (
    ExecutionRules,
    Fill,
    FillRejected,
    plan_fill,
    portfolio_equity,
)
from .portfolio import PortfolioSnapshot, Position
from .pricing import MARKET_TZ, PriceBar, YahooPriceProvider, _is_trading_day
from .strategy import Signal, StrategyService

logger = logging.getLogger("investoryx.trading_engine.backtest")

BACKTEST_SOURCE = "backtest"
MARKET_OPEN = time(9, 30)


@dataclass
class BacktestDayResult:
    day: date
    signals_generated: int
    trades_executed: int
    cash_after: Decimal
    skipped_tickers: list[str]


@dataclass
class BacktestResult:
    simulator_id: int
    start_date: date
    end_date: date
    trading_days_run: int
    total_trades: int
    starting_cash: Decimal
    final_cash: Decimal
    pnl: Decimal
    pnl_pct: Decimal
    holdings_value: Decimal = Decimal("0")
    final_equity: Decimal | None = None
    day_results: list[BacktestDayResult] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        # Convert date/Decimal to serializable types
        d["start_date"] = self.start_date.isoformat()
        d["end_date"] = self.end_date.isoformat()
        d["starting_cash"] = str(self.starting_cash)
        d["final_cash"] = str(self.final_cash)
        d["pnl"] = str(self.pnl)
        d["pnl_pct"] = str(self.pnl_pct)
        d["holdings_value"] = str(self.holdings_value)
        d["final_equity"] = str(
            self.final_equity if self.final_equity is not None else self.final_cash
        )
        for dr in d["day_results"]:
            dr["day"] = dr["day"] if isinstance(dr["day"], str) else dr["day"].isoformat()
            dr["cash_after"] = str(dr["cash_after"])
        return d


@dataclass
class _BacktestRun:
    """Everything a backtest carries from one simulated day to the next."""

    simulator: Simulator
    strategy_service: StrategyService
    strategy_name: str
    params: dict
    rules: ExecutionRules
    bars: list[PriceBar]  # sorted by day
    bar_days: list[date]  # bars' days, for slicing history up to a day
    price_index: dict[date, dict[str, PriceBar]]
    cash: Decimal
    holdings: dict[str, Decimal] = field(default_factory=dict)
    last_close: dict[str, Decimal] = field(default_factory=dict)
    # Yesterday's decisions, filled at today's open.
    pending: dict[str, Signal] = field(default_factory=dict)
    trades: list[SimulatorTrade] = field(default_factory=list)
    ledger: list[SimulatorCashLedger] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class BacktestService:
    """Replays a simulator's strategy over a historical date range.

    Each simulated day mirrors the live pipeline: the previous day's signals
    fill at this day's open under the same execution rules (fees, slippage,
    risk caps), then the strategy evaluates this day's close.

    State is purely ephemeral — the simulator's live cash_balance and positions
    are never mutated. Only `simulator_trades` and `simulator_cash_ledger` receive
    new rows (tagged source='backtest').
    """

    def run(
        self,
        simulator_id: int,
        start_date: date,
        end_date: date,
        clear_previous: bool = True,
    ) -> BacktestResult:
        session = SessionLocal()
        try:
            return self._run(
                session=session,
                simulator_id=simulator_id,
                start_date=start_date,
                end_date=end_date,
                clear_previous=clear_previous,
            )
        finally:
            session.close()

    def _run(
        self,
        session: Session,
        simulator_id: int,
        start_date: date,
        end_date: date,
        clear_previous: bool,
    ) -> BacktestResult:
        simulator = self._load_simulator(session, simulator_id)
        tickers = self._load_tickers(session, simulator_id)
        starting_cash = Decimal(str(simulator.starting_cash))

        if not tickers:
            return BacktestResult(
                simulator_id=simulator_id,
                start_date=start_date,
                end_date=end_date,
                trading_days_run=0,
                total_trades=0,
                starting_cash=starting_cash,
                final_cash=starting_cash,
                pnl=Decimal("0"),
                pnl_pct=Decimal("0"),
                warnings=["No enabled tracked stocks found — nothing to backtest."],
            )

        if clear_previous:
            self._clear_backtest_rows(session, simulator_id)

        run = self._prepare_run(simulator, tickers, start_date, end_date)
        trading_days = [d for d in _date_range(start_date, end_date) if _is_trading_day(d)]
        day_results = [self._simulate_day(run, day) for day in trading_days]

        if run.pending:
            run.warnings.append(
                f"{len(run.pending)} signal(s) from the final day would fill "
                "at the next open, after the backtest ends"
            )

        # Bulk persist all rows. The simulator's live cash_balance is intentionally
        # left untouched; the backtest outcome is reported via the result instead.
        session.add_all(run.trades)
        session.add_all(run.ledger)
        session.commit()

        return self._build_result(run, start_date, end_date, trading_days, day_results)

    def _prepare_run(
        self,
        simulator: Simulator,
        tickers: list[str],
        start_date: date,
        end_date: date,
    ) -> _BacktestRun:
        evaluation_service = EvaluationService()
        strategy_name = simulator.strategy_name or DEFAULT_STRATEGY_NAME
        params = evaluation_service.resolve_strategy_params(
            strategy_name, simulator.strategy_params
        )

        # Fetch all price data in one bulk call, with enough lookback for the
        # strategy's history to be usable from the first backtest day.
        lookback_start = start_date - timedelta(
            days=evaluation_service.resolve_history_days(params, strategy_name)
        )
        logger.info(
            "Fetching price bars for %s from %s to %s",
            tickers,
            lookback_start.isoformat(),
            end_date.isoformat(),
        )
        bars = YahooPriceProvider().fetch_daily_bars_range(tickers, lookback_start, end_date)
        bars.sort(key=lambda bar: (bar.day, bar.symbol))

        price_index: dict[date, dict[str, PriceBar]] = {}
        for bar in bars:
            price_index.setdefault(bar.day, {})[bar.symbol] = bar

        return _BacktestRun(
            simulator=simulator,
            strategy_service=StrategyService(evaluation_service.build_strategy_registry()),
            strategy_name=strategy_name,
            params=params,
            rules=ExecutionRules.for_simulator(simulator),
            bars=bars,
            bar_days=[bar.day for bar in bars],
            price_index=price_index,
            cash=Decimal(str(simulator.starting_cash)),
        )

    def _simulate_day(self, run: _BacktestRun, day: date) -> BacktestDayResult:
        day_prices = run.price_index.get(day, {})
        trades_before = len(run.trades)
        skipped = self._fill_pending_at_open(run, day, day_prices)

        signals = self._evaluate_close(run, day)
        for symbol, bar in day_prices.items():
            run.last_close[symbol] = bar.close

        return BacktestDayResult(
            day=day,
            signals_generated=len(signals),
            trades_executed=len(run.trades) - trades_before,
            cash_after=run.cash,
            skipped_tickers=skipped,
        )

    def _fill_pending_at_open(
        self,
        run: _BacktestRun,
        day: date,
        day_prices: dict[str, PriceBar],
    ) -> list[str]:
        """Fill yesterday's signals at today's open; returns tickers with no bar today."""
        marks = {**run.last_close, **{s: bar.open for s, bar in day_prices.items()}}
        skipped: list[str] = []
        for symbol, signal in run.pending.items():
            bar = day_prices.get(symbol)
            if bar is None:
                skipped.append(symbol)
                continue
            result = plan_fill(
                side=signal.action,
                quantity=signal.quantity,
                market_price=bar.open,
                cash=run.cash,
                held_shares=run.holdings.get(symbol, Decimal("0")),
                equity=portfolio_equity(run.cash, run.holdings, marks),
                rules=run.rules,
            )
            if isinstance(result, FillRejected):
                continue
            self._apply_fill(run, symbol, result, day)
        run.pending = {}
        return skipped

    def _apply_fill(self, run: _BacktestRun, symbol: str, fill: Fill, day: date) -> None:
        run.cash += fill.cash_delta
        held = run.holdings.get(symbol, Decimal("0"))
        held += fill.quantity if fill.side is SignalAction.BUY else -fill.quantity
        if held > 0:
            run.holdings[symbol] = held
        else:
            run.holdings.pop(symbol, None)

        simulator_id = int(run.simulator.simulator_id)
        run.trades.append(SimulatorTrade(
            simulator_id=simulator_id,
            ticker=symbol,
            side=fill.side.value,
            price=fill.price,
            shares=fill.quantity,
            fee=fill.fee,
            executed_at=datetime.combine(day, MARKET_OPEN, tzinfo=MARKET_TZ),
            source=BACKTEST_SOURCE,
            balance_after=run.cash,
        ))
        run.ledger.append(SimulatorCashLedger(
            simulator_id=simulator_id,
            delta=fill.cash_delta,
            reason=fill.side.value,
            balance_after=run.cash,
            source=BACKTEST_SOURCE,
        ))

    def _evaluate_close(self, run: _BacktestRun, day: date) -> list[Signal]:
        """Run the strategy on prices up to this day's close; queue trades for the next open."""
        history = filter_to_fresh_symbols(
            run.bars[: bisect_right(run.bar_days, day)], day
        )
        if not history:
            run.warnings.append(f"{day.isoformat()}: no price data available, skipping day")
            return []

        snapshot = PortfolioSnapshot(
            user_id=int(run.simulator.user_id),
            cash=run.cash,
            positions={
                symbol: Position(symbol=symbol, quantity=qty, average_cost=Decimal("0"))
                for symbol, qty in run.holdings.items()
            },
            as_of=datetime.combine(day, time(16, 0), tzinfo=MARKET_TZ),
            simulator_id=int(run.simulator.simulator_id),
        )
        try:
            signals = EvaluationService().validate_signal_batch(
                run.strategy_service.evaluate(
                    strategy_name=run.strategy_name,
                    prices=history,
                    portfolio=snapshot,
                    params=run.params,
                )
            )
        except Exception as exc:
            run.warnings.append(f"{day.isoformat()}: strategy evaluation failed — {exc}")
            return []

        run.pending = {
            symbol: signal
            for symbol, signal in one_signal_per_ticker(signals).items()
            if signal.action is not SignalAction.HOLD
        }
        return signals

    def _build_result(
        self,
        run: _BacktestRun,
        start_date: date,
        end_date: date,
        trading_days: list[date],
        day_results: list[BacktestDayResult],
    ) -> BacktestResult:
        # Mark open positions to their last close on or before end_date, so a
        # backtest that ends holding shares isn't reported as a cash loss.
        holdings_value = Decimal("0")
        for symbol, qty in run.holdings.items():
            last_close = _last_close_on_or_before(run.bars, symbol, end_date)
            if last_close is None:
                run.warnings.append(f"{symbol}: no closing price to value {qty} held shares")
                continue
            holdings_value += qty * last_close

        starting_cash = Decimal(str(run.simulator.starting_cash))
        final_equity = run.cash + holdings_value
        pnl = final_equity - starting_cash
        pnl_pct = (
            (pnl / starting_cash * Decimal("100")).quantize(Decimal("0.01"))
            if starting_cash
            else Decimal("0")
        )
        return BacktestResult(
            simulator_id=int(run.simulator.simulator_id),
            start_date=start_date,
            end_date=end_date,
            trading_days_run=len(trading_days),
            total_trades=len(run.trades),
            starting_cash=starting_cash,
            final_cash=run.cash,
            pnl=pnl,
            pnl_pct=pnl_pct,
            holdings_value=holdings_value,
            final_equity=final_equity,
            day_results=day_results,
            warnings=run.warnings,
        )

    def _load_simulator(self, session: Session, simulator_id: int) -> Simulator:
        stmt = select(Simulator).where(Simulator.simulator_id == simulator_id)
        simulator = session.execute(stmt).scalars().first()
        if simulator is None:
            raise ValueError(f"Simulator {simulator_id} not found")
        return simulator

    def _load_tickers(self, session: Session, simulator_id: int) -> list[str]:
        stmt = (
            select(SimulatorTrackedStock.ticker)
            .where(SimulatorTrackedStock.simulator_id == simulator_id)
            .where(SimulatorTrackedStock.enabled.is_(True))
        )
        rows = session.execute(stmt).scalars().all()
        return sorted({t.strip().upper() for t in rows if t and t.strip()})

    def _clear_backtest_rows(self, session: Session, simulator_id: int) -> None:
        session.execute(
            delete(SimulatorTrade).where(
                SimulatorTrade.simulator_id == simulator_id,
                SimulatorTrade.source == BACKTEST_SOURCE,
            )
        )
        session.execute(
            delete(SimulatorCashLedger).where(
                SimulatorCashLedger.simulator_id == simulator_id,
                SimulatorCashLedger.source == BACKTEST_SOURCE,
            )
        )
        session.commit()


def _last_close_on_or_before(bars: list[PriceBar], symbol: str, day: date) -> Decimal | None:
    closes = [bar.close for bar in bars if bar.symbol == symbol and bar.day <= day]
    return closes[-1] if closes else None  # bars are sorted by day


def _date_range(start: date, end: date):
    """Yield each calendar date from start through end inclusive."""
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)
