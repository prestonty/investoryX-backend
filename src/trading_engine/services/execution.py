from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_FLOOR, Decimal
from enum import Enum

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from src.core.config import settings
from src.models.price_bar import PriceBar as PriceBarModel
from src.models.simulator import Simulator
from src.models.simulator_cash_ledger import SimulatorCashLedger
from src.models.simulator_position import SimulatorPosition
from src.models.simulator_signal import SimulatorSignal
from src.models.simulator_trade import SimulatorTrade

from .actions import SignalAction
from .pricing import last_completed_trading_day, previous_trading_day

logger = logging.getLogger("investoryx.trading_engine.execution")

LIVE_SOURCE = "live"
# How far back to look for a price to value holdings that have no bar on the trade day.
MARK_LOOKBACK_DAYS = 10
PRICE_STEP = Decimal("0.0001")


class SignalExecutionStatus(str, Enum):
    PENDING = "pending"
    EXECUTED = "executed"
    SKIPPED = "skipped"
    FAILED = "failed"


class SignalOutcome(str, Enum):
    EXECUTED = "executed"
    SKIPPED = "skipped"
    FAILED = "failed"


# SHARED FILL RULES ---------------------------------------------------------------
# Live execution and backtests both size and price orders with plan_fill(), so a
# backtest trades exactly the way the live pipeline would.


@dataclass(frozen=True)
class ExecutionRules:
    """Cost and risk limits applied to every paper fill, live or backtest."""

    fee_per_trade: Decimal = Decimal("0")
    slippage_bps: Decimal = Decimal("0")
    # Percent of portfolio equity (25 = 25%) one symbol may reach after a buy.
    max_position_pct: Decimal | None = None
    # Largest notional value of a single buy.
    max_order_value: Decimal | None = None

    @classmethod
    def for_simulator(
        cls,
        simulator: Simulator,
        fee_per_trade: Decimal | None = None,
        slippage_bps: Decimal | None = None,
    ) -> ExecutionRules:
        """Platform costs from settings plus the simulator's own risk limits."""
        max_position_pct = simulator.max_position_pct
        return cls(
            fee_per_trade=(
                settings.sim_fee_per_trade if fee_per_trade is None else fee_per_trade
            ),
            slippage_bps=settings.sim_slippage_bps if slippage_bps is None else slippage_bps,
            max_position_pct=(
                Decimal(str(max_position_pct)) if max_position_pct is not None else None
            ),
            max_order_value=settings.sim_max_order_value,
        )


@dataclass(frozen=True)
class Fill:
    """A sized, priced order that passed every rule."""

    side: SignalAction
    quantity: Decimal
    price: Decimal
    fee: Decimal
    requested_quantity: Decimal
    limited_by: str | None = None

    @property
    def cash_delta(self) -> Decimal:
        gross = self.price * self.quantity
        if self.side is SignalAction.BUY:
            return -(gross + self.fee)
        return gross - self.fee


@dataclass(frozen=True)
class FillRejected:
    reason: str


def plan_fill(
    side: SignalAction,
    quantity: Decimal,
    market_price: Decimal,
    cash: Decimal,
    held_shares: Decimal,
    equity: Decimal,
    rules: ExecutionRules,
) -> Fill | FillRejected:
    """Size and price one order against the portfolio and rules.

    Risk caps (max_order_value, max_position_pct) shrink a buy to the whole
    shares that fit; running out of cash or shares rejects the order.
    """
    if side not in (SignalAction.BUY, SignalAction.SELL):
        return FillRejected("non-tradable action")
    if quantity <= 0:
        return FillRejected("non-positive trade quantity")
    if market_price <= 0:
        return FillRejected("invalid price")

    fill_price = estimate_fill_price(side, market_price, rules.slippage_bps)
    if side is SignalAction.SELL:
        if quantity > held_shares:
            return FillRejected("insufficient shares")
        return Fill(side, quantity, fill_price, rules.fee_per_trade, quantity)

    executable, limited_by = _apply_buy_caps(
        quantity, fill_price, market_price, held_shares, equity, rules
    )
    if executable <= 0:
        return FillRejected(f"exceeds {limited_by}")
    if executable * fill_price + rules.fee_per_trade > cash:
        return FillRejected("insufficient cash")
    return Fill(side, executable, fill_price, rules.fee_per_trade, quantity, limited_by)


def _apply_buy_caps(
    quantity: Decimal,
    fill_price: Decimal,
    market_price: Decimal,
    held_shares: Decimal,
    equity: Decimal,
    rules: ExecutionRules,
) -> tuple[Decimal, str | None]:
    limited_by = None
    if rules.max_order_value is not None:
        cap = _floor_shares(rules.max_order_value / fill_price)
        if cap < quantity:
            quantity, limited_by = cap, "max_order_value"
    if rules.max_position_pct is not None:
        headroom = equity * rules.max_position_pct / 100 - held_shares * market_price
        cap = _floor_shares(headroom / fill_price)
        if cap < quantity:
            quantity, limited_by = cap, "max_position_pct"
    return quantity, limited_by


def _floor_shares(value: Decimal) -> Decimal:
    return value.to_integral_value(rounding=ROUND_FLOOR) if value > 0 else Decimal("0")


def estimate_fill_price(
    side: SignalAction,
    market_price: Decimal,
    slippage_bps: Decimal,
) -> Decimal:
    if slippage_bps <= Decimal("0"):
        return market_price
    bps = slippage_bps / Decimal("10000")
    if side is SignalAction.BUY:
        price = market_price * (Decimal("1") + bps)
    else:
        price = market_price * (Decimal("1") - bps)
    # Trades store 4 decimal places; rounding here keeps the cash moved by a
    # fill equal to what replaying the stored trade gives.
    return price.quantize(PRICE_STEP)


def portfolio_equity(
    cash: Decimal,
    holdings: dict[str, Decimal],
    marks: dict[str, Decimal],
) -> Decimal:
    # A holding with no known price adds nothing, which only makes caps stricter.
    return cash + sum(
        (shares * marks.get(symbol, Decimal("0")) for symbol, shares in holdings.items()),
        Decimal("0"),
    )


# LIVE EXECUTION --------------------------------------------------------------------


@dataclass(frozen=True)
class ExecutionSummary:
    processed: int
    executed: int
    skipped: int
    failed: int
    trades_created: int


@dataclass
class ExecutionContext:
    session: Session
    now: datetime
    trade_day: date
    signal_day: date
    rules_by_sim: dict[int, ExecutionRules]
    cash_by_sim: dict[int, Decimal]
    holdings_by_sim: dict[int, dict[str, Decimal]]
    opens: dict[str, Decimal]
    marks: dict[str, Decimal]


class PaperTradeExecutionService:
    """Executes pending simulator signals into paper trades."""

    def execute_pending_signals(
        self,
        session: Session,
        simulator_id: int | None = None,
        limit: int = 500,
        slippage_bps: Decimal = Decimal("0"),
        fee_per_trade: Decimal = Decimal("0"),
        trade_day: date | None = None,
    ) -> ExecutionSummary:
        """Fill signals from the previous trading day's close at trade_day's open.

        A decision made on one day's close can't trade before the next session
        opens. Signals evaluated on trade_day itself stay pending for the next
        run; older ones expire.
        """
        trade_day = trade_day or last_completed_trading_day()
        pending = self._load_due_signals(session, simulator_id, limit, trade_day)
        if not pending:
            return ExecutionSummary(0, 0, 0, 0, 0)

        context = self._build_context(
            session=session,
            pending=pending,
            trade_day=trade_day,
            fee_per_trade=fee_per_trade,
            slippage_bps=slippage_bps,
        )
        counts = {outcome: 0 for outcome in SignalOutcome}
        trades_created = 0
        for signal in pending:
            outcome, trade = self._process_signal(signal=signal, context=context)
            counts[outcome] += 1
            if trade is not None:
                session.add(trade)
                session.add(self._to_ledger_entry(trade))
                trades_created += 1

        session.commit()
        return ExecutionSummary(
            processed=len(pending),
            executed=counts[SignalOutcome.EXECUTED],
            skipped=counts[SignalOutcome.SKIPPED],
            failed=counts[SignalOutcome.FAILED],
            trades_created=trades_created,
        )

    def _build_context(
        self,
        session: Session,
        pending: list[SimulatorSignal],
        trade_day: date,
        fee_per_trade: Decimal,
        slippage_bps: Decimal,
    ) -> ExecutionContext:
        simulator_ids = sorted({int(signal.simulator_id) for signal in pending})
        simulators = session.execute(
            select(Simulator).where(Simulator.simulator_id.in_(simulator_ids))
        ).scalars().all()
        holdings_by_sim = self._load_holdings_by_simulator(session, simulator_ids)
        symbols = {signal.ticker.strip().upper() for signal in pending if signal.ticker}
        for holdings in holdings_by_sim.values():
            symbols.update(holdings)
        opens, marks = self._load_prices(session, sorted(symbols), trade_day)

        return ExecutionContext(
            session=session,
            now=datetime.now(timezone.utc),
            trade_day=trade_day,
            signal_day=previous_trading_day(trade_day),
            rules_by_sim={
                int(sim.simulator_id): ExecutionRules.for_simulator(
                    sim, fee_per_trade=fee_per_trade, slippage_bps=slippage_bps
                )
                for sim in simulators
            },
            cash_by_sim={
                int(sim.simulator_id): Decimal(str(sim.cash_balance)) for sim in simulators
            },
            holdings_by_sim=holdings_by_sim,
            opens=opens,
            marks=marks,
        )

    def _load_due_signals(
        self,
        session: Session,
        simulator_id: int | None,
        limit: int,
        trade_day: date,
    ) -> list[SimulatorSignal]:
        stmt = (
            select(SimulatorSignal)
            .where(SimulatorSignal.status == SignalExecutionStatus.PENDING.value)
            # Signals evaluated on trade_day (or later) wait for the next open.
            .where(
                or_(
                    SimulatorSignal.for_day.is_(None),
                    SimulatorSignal.for_day < trade_day,
                )
            )
            .order_by(SimulatorSignal.created_at, SimulatorSignal.signal_id)
            .limit(limit)
        )
        if simulator_id is not None:
            stmt = stmt.where(SimulatorSignal.simulator_id == simulator_id)
        return session.execute(stmt).scalars().all()

    def _load_holdings_by_simulator(
        self,
        session: Session,
        simulator_ids: list[int],
    ) -> dict[int, dict[str, Decimal]]:
        stmt = select(SimulatorPosition).where(
            SimulatorPosition.simulator_id.in_(simulator_ids)
        )
        holdings: dict[int, dict[str, Decimal]] = {}
        for row in session.execute(stmt).scalars().all():
            symbol = row.ticker.strip().upper()
            holdings.setdefault(int(row.simulator_id), {})[symbol] = Decimal(str(row.shares))
        return holdings

    def _load_prices(
        self,
        session: Session,
        symbols: list[str],
        day: date,
    ) -> tuple[dict[str, Decimal], dict[str, Decimal]]:
        """Opens on `day` (fill prices) and marks (that open, else the latest close)."""
        if not symbols:
            return {}, {}
        stmt = (
            select(PriceBarModel)
            .where(PriceBarModel.symbol.in_(symbols))
            .where(PriceBarModel.source == "yfinance")
            .where(PriceBarModel.day <= day)
            .where(PriceBarModel.day >= day - timedelta(days=MARK_LOOKBACK_DAYS))
            .order_by(PriceBarModel.symbol, PriceBarModel.day)
        )
        opens: dict[str, Decimal] = {}
        marks: dict[str, Decimal] = {}
        for row in session.execute(stmt).scalars().all():
            if row.day == day:
                opens[row.symbol] = marks[row.symbol] = Decimal(str(row.open))
            else:
                marks[row.symbol] = Decimal(str(row.close))
        return opens, marks

    def _validate_signal(self, signal: SimulatorSignal) -> str | None:
        if not signal.ticker or not signal.ticker.strip():
            return "signal missing ticker"
        if signal.action not in {action.value for action in SignalAction}:
            return f"unsupported action={signal.action}"
        if (
            Decimal(str(signal.quantity)) <= 0
            and signal.action != SignalAction.HOLD.value
        ):
            return "signal quantity must be positive"
        return None

    def _mark(
        self,
        signal: SimulatorSignal,
        status: SignalExecutionStatus,
        now: datetime,
        reason: str | None = None,
    ) -> None:
        signal.status = status.value
        signal.execution_error = reason
        signal.executed_at = now

    def _process_signal(
        self,
        signal: SimulatorSignal,
        context: ExecutionContext,
    ) -> tuple[SignalOutcome, SimulatorTrade | None]:
        error = self._validate_signal(signal)
        if error:
            self._mark(signal, SignalExecutionStatus.FAILED, context.now, error)
            return SignalOutcome.FAILED, None

        if signal.action == SignalAction.HOLD.value:
            self._mark(
                signal, SignalExecutionStatus.SKIPPED, context.now,
                "hold signal is not executable",
            )
            return SignalOutcome.SKIPPED, None

        # Only the previous trading day's decisions are due; anything older (e.g.
        # left pending by a failed run) must not fill at a much later price.
        if signal.for_day != context.signal_day:
            evaluated_for = signal.for_day.isoformat() if signal.for_day else "an unknown day"
            self._mark(
                signal, SignalExecutionStatus.SKIPPED, context.now,
                f"expired: evaluated for {evaluated_for}, not executed until "
                f"{context.trade_day.isoformat()}",
            )
            return SignalOutcome.SKIPPED, None

        symbol = signal.ticker.strip().upper()
        price = context.opens.get(symbol)
        if price is None:
            self._mark(
                signal, SignalExecutionStatus.FAILED, context.now,
                f"no opening price for ticker={symbol} on {context.trade_day.isoformat()}",
            )
            return SignalOutcome.FAILED, None

        return self._fill_signal(signal, symbol, price, context)

    def _fill_signal(
        self,
        signal: SimulatorSignal,
        symbol: str,
        price: Decimal,
        context: ExecutionContext,
    ) -> tuple[SignalOutcome, SimulatorTrade | None]:
        sim_id = int(signal.simulator_id)
        cash = context.cash_by_sim.get(sim_id, Decimal("0"))
        holdings = context.holdings_by_sim.setdefault(sim_id, {})
        result = plan_fill(
            side=SignalAction(signal.action.lower()),
            quantity=Decimal(str(signal.quantity)),
            market_price=price,
            cash=cash,
            held_shares=holdings.get(symbol, Decimal("0")),
            equity=portfolio_equity(cash, holdings, context.marks),
            rules=context.rules_by_sim.get(sim_id, ExecutionRules()),
        )
        if isinstance(result, FillRejected):
            self._mark(signal, SignalExecutionStatus.FAILED, context.now, result.reason)
            return SignalOutcome.FAILED, None

        if result.limited_by:
            logger.info(
                "signal_id=%s reduced from %s to %s shares by %s",
                signal.signal_id, result.requested_quantity, result.quantity,
                result.limited_by,
            )
        held_after = holdings.get(symbol, Decimal("0")) + (
            result.quantity if result.side is SignalAction.BUY else -result.quantity
        )
        holdings[symbol] = held_after
        context.cash_by_sim[sim_id] = cash + result.cash_delta

        trade = self._to_trade(
            simulator_id=sim_id,
            symbol=symbol,
            fill=result,
            executed_at=context.now,
            balance_after=context.cash_by_sim[sim_id],
            strategy_name=signal.strategy_name,
        )
        self._mark(signal, SignalExecutionStatus.EXECUTED, context.now)
        return SignalOutcome.EXECUTED, trade

    def _to_trade(
        self,
        simulator_id: int,
        symbol: str,
        fill: Fill,
        executed_at: datetime,
        balance_after: Decimal,
        strategy_name: str,
    ) -> SimulatorTrade:
        return SimulatorTrade(
            simulator_id=simulator_id,
            ticker=symbol,
            side=fill.side.value,
            price=fill.price,
            shares=fill.quantity,
            fee=fill.fee,
            executed_at=executed_at,
            source=LIVE_SOURCE,
            balance_after=balance_after,
            strategy_name=strategy_name,
        )

    def _to_ledger_entry(self, trade: SimulatorTrade) -> SimulatorCashLedger:
        gross = trade.price * trade.shares
        delta = -(gross + trade.fee) if trade.side == SignalAction.BUY.value else gross - trade.fee
        return SimulatorCashLedger(
            simulator_id=trade.simulator_id,
            delta=delta,
            reason=trade.side,
            balance_after=trade.balance_after,
            source=LIVE_SOURCE,
        )
