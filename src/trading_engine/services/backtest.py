from __future__ import annotations

import logging
from dataclasses import dataclass, field, asdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from src.core.database import SessionLocal
from src.models.simulator import Simulator
from src.models.simulator_cash_ledger import SimulatorCashLedger
from src.models.simulator_trade import SimulatorTrade
from src.models.simulator_tracked_stock import SimulatorTrackedStock

from .actions import SignalAction
from .evaluation import EvaluationService
from .portfolio import PortfolioSnapshot, Position
from .pricing import PriceBar, YahooPriceProvider, _is_trading_day

logger = logging.getLogger("investoryx.trading_engine.backtest")

FEE_PER_TRADE = Decimal("0")
SLIPPAGE_BPS = Decimal("0")
LOOKBACK_BUFFER_DAYS = 35  # enough history for long SMA windows


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
        for dr in d["day_results"]:
            dr["day"] = dr["day"] if isinstance(dr["day"], str) else dr["day"].isoformat()
            dr["cash_after"] = str(dr["cash_after"])
        return d


class BacktestService:
    """Runs a trading strategy across a historical date range for a given simulator.

    State is purely ephemeral — the simulator's live cash_balance and positions
    are never mutated. Only `simulator_trades` and `simulator_cash_ledger` receive
    new rows (tagged source='backtest').
    """

    def run(
        self,
        simulator_id: int,
        start_date: date,
        end_date: date,
        price_mode: str = "close",
        clear_previous: bool = True,
    ) -> BacktestResult:
        session = SessionLocal()
        try:
            return self._run(
                session=session,
                simulator_id=simulator_id,
                start_date=start_date,
                end_date=end_date,
                price_mode=price_mode,
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
        price_mode: str,
        clear_previous: bool,
    ) -> BacktestResult:
        simulator = self._load_simulator(session, simulator_id)
        tickers = self._load_tickers(session, simulator_id)

        if not tickers:
            return BacktestResult(
                simulator_id=simulator_id,
                start_date=start_date,
                end_date=end_date,
                trading_days_run=0,
                total_trades=0,
                starting_cash=Decimal(str(simulator.starting_cash)),
                final_cash=Decimal(str(simulator.starting_cash)),
                pnl=Decimal("0"),
                pnl_pct=Decimal("0"),
                warnings=["No enabled tracked stocks found — nothing to backtest."],
            )

        if clear_previous:
            self._clear_backtest_rows(session, simulator_id)

        # Fetch all price data in one bulk call (include lookback for strategy history)
        lookback_start = start_date - timedelta(days=LOOKBACK_BUFFER_DAYS)
        logger.info(
            "Fetching price bars for %s from %s to %s",
            tickers,
            lookback_start.isoformat(),
            end_date.isoformat(),
        )
        provider = YahooPriceProvider()
        all_bars = provider.fetch_daily_bars_range(tickers, lookback_start, end_date)

        # Build price index: day -> symbol -> PriceBar
        price_index: dict[date, dict[str, PriceBar]] = {}
        for bar in all_bars:
            price_index.setdefault(bar.day, {})[bar.symbol] = bar

        # Build ordered list of all bars up to each day (for strategy lookback)
        all_bars_sorted = sorted(all_bars, key=lambda b: (b.symbol, b.day))

        # Set up strategy evaluation
        evaluation_service = EvaluationService()
        strategy_registry = evaluation_service.build_strategy_registry()
        from .strategy import StrategyService
        strategy_service = StrategyService(strategy_registry)
        strategy_name = getattr(simulator, "strategy_name", None) or "sma_crossover"

        # Ephemeral portfolio state seeded from starting_cash
        starting_cash = Decimal(str(simulator.starting_cash))
        cash = starting_cash
        holdings: dict[str, Decimal] = {}  # symbol -> shares

        strategy_params: dict = {}

        trading_days = [
            d
            for d in _date_range(start_date, end_date)
            if _is_trading_day(d)
        ]

        accumulated_trades: list[SimulatorTrade] = []
        accumulated_ledger: list[SimulatorCashLedger] = []
        day_results: list[BacktestDayResult] = []
        warnings: list[str] = []

        for day in trading_days:
            # Slice bars up to and including this day for strategy lookback
            day_bars = [b for b in all_bars_sorted if b.day <= day]
            if not day_bars:
                warnings.append(f"{day.isoformat()}: no price data available, skipping day")
                continue

            positions = {
                symbol: Position(
                    symbol=symbol,
                    quantity=qty,
                    average_cost=Decimal("0"),
                )
                for symbol, qty in holdings.items()
                if qty > 0
            }
            snapshot = PortfolioSnapshot(
                user_id=int(simulator.user_id),
                cash=cash,
                positions=positions,
                as_of=datetime.combine(day, datetime.min.time()).replace(tzinfo=timezone.utc),
                simulator_id=simulator_id,
            )

            try:
                raw_signals = strategy_service.evaluate(
                    strategy_name=strategy_name,
                    prices=day_bars,
                    portfolio=snapshot,
                    params=strategy_params,
                )
                signals = evaluation_service.validate_signal_batch(raw_signals)
            except Exception as exc:
                warnings.append(f"{day.isoformat()}: strategy evaluation failed — {exc}")
                day_results.append(BacktestDayResult(
                    day=day,
                    signals_generated=0,
                    trades_executed=0,
                    cash_after=cash,
                    skipped_tickers=[],
                ))
                continue

            day_trades = 0
            skipped: list[str] = []
            day_price_map = price_index.get(day, {})

            for signal in signals:
                if signal.action.value == SignalAction.HOLD.value:
                    continue

                symbol = signal.symbol.strip().upper()
                price_bar = day_price_map.get(symbol)
                if price_bar is None:
                    skipped.append(symbol)
                    continue

                market_price = price_bar.close if price_mode == "close" else price_bar.open
                quantity = signal.quantity

                if signal.action == SignalAction.BUY:
                    total_cost = market_price * quantity + FEE_PER_TRADE
                    if total_cost > cash:
                        continue  # insufficient cash — skip
                    cash -= total_cost
                    holdings[symbol] = holdings.get(symbol, Decimal("0")) + quantity
                elif signal.action == SignalAction.SELL:
                    held = holdings.get(symbol, Decimal("0"))
                    if quantity > held:
                        continue  # insufficient shares — skip
                    proceeds = market_price * quantity - FEE_PER_TRADE
                    cash += proceeds
                    holdings[symbol] = held - quantity
                    if holdings[symbol] <= 0:
                        holdings.pop(symbol, None)
                else:
                    continue

                executed_at = datetime.combine(day, datetime.min.time()).replace(tzinfo=timezone.utc)
                accumulated_trades.append(SimulatorTrade(
                    simulator_id=simulator_id,
                    ticker=symbol,
                    side=signal.action.value,
                    price=market_price,
                    shares=quantity,
                    fee=FEE_PER_TRADE,
                    executed_at=executed_at,
                    source="backtest",
                    balance_after=cash,
                ))

                ledger_delta = (
                    -(market_price * quantity + FEE_PER_TRADE)
                    if signal.action == SignalAction.BUY
                    else (market_price * quantity - FEE_PER_TRADE)
                )
                accumulated_ledger.append(SimulatorCashLedger(
                    simulator_id=simulator_id,
                    delta=ledger_delta,
                    reason=signal.action.value,
                    balance_after=cash,
                    source="backtest",
                ))
                day_trades += 1

            day_results.append(BacktestDayResult(
                day=day,
                signals_generated=len(signals),
                trades_executed=day_trades,
                cash_after=cash,
                skipped_tickers=skipped,
            ))

        # Bulk persist all rows
        if accumulated_trades:
            session.add_all(accumulated_trades)
        if accumulated_ledger:
            session.add_all(accumulated_ledger)

        # Persist the final cash balance back to the simulator
        simulator = self._load_simulator(session, simulator_id)
        simulator.cash_balance = cash
        session.commit()

        pnl = cash - starting_cash
        pnl_pct = (pnl / starting_cash * Decimal("100")).quantize(Decimal("0.01")) if starting_cash else Decimal("0")

        return BacktestResult(
            simulator_id=simulator_id,
            start_date=start_date,
            end_date=end_date,
            trading_days_run=len(trading_days),
            total_trades=len(accumulated_trades),
            starting_cash=starting_cash,
            final_cash=cash,
            pnl=pnl,
            pnl_pct=pnl_pct,
            day_results=day_results,
            warnings=warnings,
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
                SimulatorTrade.source == "backtest",
            )
        )
        session.execute(
            delete(SimulatorCashLedger).where(
                SimulatorCashLedger.simulator_id == simulator_id,
                SimulatorCashLedger.source == "backtest",
            )
        )
        session.commit()


def _date_range(start: date, end: date):
    """Yield each calendar date from start through end inclusive."""
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)
