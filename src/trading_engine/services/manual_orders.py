from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from enum import Enum

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.models.price_bar import PriceBar as PriceBarModel
from src.models.simulator import Simulator
from src.models.simulator_cash_ledger import SimulatorCashLedger
from src.models.simulator_order import SimulatorOrder
from src.models.simulator_position import SimulatorPosition
from src.models.simulator_signal import SimulatorSignal
from src.models.simulator_trade import SimulatorTrade
from src.trading_engine.strategies.catalog import MANUAL_STRATEGY_NAME

from .actions import SignalAction
from .execution import (
    MARK_LOOKBACK_DAYS,
    ExecutionRules,
    Fill,
    SignalExecutionStatus,
    estimate_fill_price,
    plan_fill,
    portfolio_equity,
)
from .portfolio import PortfolioService
from .pricing import (
    MARKET_TZ,
    YahooPriceProvider,
    fetch_last_price,
    last_opened_trading_day,
    market_is_open,
    next_open_day,
)

logger = logging.getLogger("investoryx.trading_engine.manual_orders")

MANUAL_SOURCE = "manual"
# A queued order whose opening price still can't be found this many days after
# its fill day is rejected rather than left waiting forever.
OPEN_PRICE_GRACE_DAYS = 5


class OrderStatus(str, Enum):
    PENDING = "pending"
    FILLED = "filled"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


class OrderRejected(Exception):
    """The order can't be placed or filled; the message is shown to the user."""


def current_time() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class OrderQuote:
    """What a market order would do if placed now; nothing is saved."""

    ticker: str
    side: SignalAction
    shares: Decimal
    # Latest price; the last close while the market is closed.
    market_price: Decimal
    # market_price with slippage against the trader.
    estimated_price: Decimal
    fee: Decimal
    # Cash paid for a buy, or received for a sell.
    estimated_total: Decimal
    # True while the market is open; otherwise the order waits for fill_day's open.
    fills_now: bool
    fill_day: date


@dataclass(frozen=True)
class PlacedOrder:
    quote: OrderQuote
    trade: SimulatorTrade | None = None  # filled immediately (market open)
    order: SimulatorOrder | None = None  # queued for the next open


@dataclass(frozen=True)
class QueuedFillSummary:
    filled: int = 0
    rejected: int = 0
    # Still pending because the opening price isn't available yet.
    waiting: int = 0

    def __add__(self, other: QueuedFillSummary) -> QueuedFillSummary:
        return QueuedFillSummary(
            self.filled + other.filled,
            self.rejected + other.rejected,
            self.waiting + other.waiting,
        )


@dataclass(frozen=True)
class _Book:
    """Cash and shares an order may use, after what queued orders have set aside."""

    cash: Decimal
    held: Decimal
    reserved_cash: Decimal
    reserved_shares: Decimal
    equity: Decimal

    @property
    def available_cash(self) -> Decimal:
        return self.cash - self.reserved_cash

    @property
    def available_shares(self) -> Decimal:
        return self.held - self.reserved_shares


class ManualOrderService:
    """Market orders a user places by hand on a simulator set to manual trading.

    While the market is open an order fills immediately at the latest price.
    Otherwise it is queued and fills at the next trading day's open, the same
    price a strategy's order would get. Either way it is sized and priced by
    plan_fill(), so fees, slippage and risk limits match the automated paths.
    """

    def quote(
        self,
        session: Session,
        simulator: Simulator,
        ticker: str,
        side: SignalAction,
        shares: Decimal,
        now: datetime | None = None,
    ) -> OrderQuote:
        now = now or current_time()
        _require_manual(simulator)
        market_price = _market_price(ticker)
        quote, _ = self._plan(session, simulator, ticker, side, shares, market_price, now)
        return quote

    def place(
        self,
        session: Session,
        simulator_id: int,
        ticker: str,
        side: SignalAction,
        shares: Decimal,
        now: datetime | None = None,
    ) -> PlacedOrder:
        """Fill or queue an order. The caller commits (or rolls back on OrderRejected)."""
        now = now or current_time()
        _require_manual(session.get(Simulator, simulator_id))
        # Orders queued for an open that has already happened go first, as at a broker.
        self.fill_due_orders(session, now=now, simulator_id=simulator_id)
        market_price = _market_price(ticker)

        simulator = _lock_simulator(session, simulator_id)
        _require_manual(simulator)
        quote, fill = self._plan(session, simulator, ticker, side, shares, market_price, now)
        if not quote.fills_now:
            order = SimulatorOrder(
                simulator_id=simulator_id,
                ticker=ticker,
                side=side.value,
                shares=shares,
                quote_price=market_price,
                fill_day=quote.fill_day,
                status=OrderStatus.PENDING.value,
            )
            session.add(order)
            session.flush()
            return PlacedOrder(quote=quote, order=order)

        trade = _record_fill(session, simulator, ticker, fill, executed_at=now)
        return PlacedOrder(quote=quote, trade=trade)

    def cancel(
        self,
        session: Session,
        simulator_id: int,
        order_id: int,
        now: datetime | None = None,
    ) -> SimulatorOrder:
        """Cancel a queued order. The caller commits."""
        now = now or current_time()
        # Holding the simulator's lock means a concurrent fill can't take this order.
        _lock_simulator(session, simulator_id)
        order = session.execute(
            select(SimulatorOrder)
            .where(SimulatorOrder.simulator_id == simulator_id)
            .where(SimulatorOrder.order_id == order_id)
        ).scalar_one_or_none()
        if order is None:
            raise LookupError(f"order_id={order_id} not found")
        if order.status != OrderStatus.PENDING.value:
            raise OrderRejected(f"This order was already {order.status}")
        _close(order, OrderStatus.CANCELLED, now)
        return order

    def fill_due_orders(
        self,
        session: Session,
        now: datetime | None = None,
        simulator_id: int | None = None,
    ) -> QueuedFillSummary:
        """Fill queued orders whose open has happened, committing one simulator at a time."""
        now = now or current_time()
        stmt = (
            select(SimulatorOrder.simulator_id)
            .where(SimulatorOrder.status == OrderStatus.PENDING.value)
            .where(SimulatorOrder.fill_day <= last_opened_trading_day(now))
            .distinct()
        )
        if simulator_id is not None:
            stmt = stmt.where(SimulatorOrder.simulator_id == simulator_id)
        simulator_ids = sorted(session.execute(stmt).scalars().all())

        total = QueuedFillSummary()
        for sim_id in simulator_ids:
            try:
                total += self._fill_due_for(session, _lock_simulator(session, sim_id), now)
                session.commit()
            except Exception:
                session.rollback()
                logger.exception("Filling queued orders failed for simulator_id=%s", sim_id)
        return total

    def _fill_due_for(
        self,
        session: Session,
        simulator: Simulator,
        now: datetime,
    ) -> QueuedFillSummary:
        orders = session.execute(
            select(SimulatorOrder)
            .where(SimulatorOrder.simulator_id == simulator.simulator_id)
            .where(SimulatorOrder.status == OrderStatus.PENDING.value)
            .where(SimulatorOrder.fill_day <= last_opened_trading_day(now))
            .order_by(SimulatorOrder.created_at, SimulatorOrder.order_id)
        ).scalars().all()
        opens = _opening_prices(session, {(order.ticker, order.fill_day) for order in orders})
        today = now.astimezone(MARKET_TZ).date()

        filled = rejected = waiting = 0
        for order in orders:
            price = opens.get((order.ticker, order.fill_day))
            if price is None:
                if (today - order.fill_day).days > OPEN_PRICE_GRACE_DAYS:
                    order.error = (
                        f"No opening price for {order.ticker} on {order.fill_day.isoformat()}"
                    )
                    _close(order, OrderStatus.REJECTED, now)
                    rejected += 1
                else:
                    waiting += 1
                continue

            # Earlier orders fill first; a later one that no longer fits is rejected.
            book = _load_book(session, simulator, order.ticker, price, now, reserve=False)
            try:
                fill = _size(
                    simulator,
                    order.ticker,
                    SignalAction(order.side),
                    Decimal(str(order.shares)),
                    price,
                    book,
                )
            except OrderRejected as exc:
                order.error = f"Not filled at the open: {exc}"
                _close(order, OrderStatus.REJECTED, now)
                rejected += 1
                continue

            trade = _record_fill(session, simulator, order.ticker, fill, executed_at=now)
            order.trade_id = trade.trade_id
            _close(order, OrderStatus.FILLED, now)
            filled += 1
        return QueuedFillSummary(filled, rejected, waiting)

    def _plan(
        self,
        session: Session,
        simulator: Simulator,
        ticker: str,
        side: SignalAction,
        shares: Decimal,
        market_price: Decimal,
        now: datetime,
    ) -> tuple[OrderQuote, Fill]:
        book = _load_book(session, simulator, ticker, market_price, now, reserve=True)
        fill = _size(simulator, ticker, side, shares, market_price, book)
        fills_now = market_is_open(now)
        quote = OrderQuote(
            ticker=ticker,
            side=side,
            shares=fill.quantity,
            market_price=market_price,
            estimated_price=fill.price,
            fee=fill.fee,
            estimated_total=abs(fill.cash_delta),
            fills_now=fills_now,
            fill_day=last_opened_trading_day(now) if fills_now else next_open_day(now),
        )
        return quote, fill


def switch_trading_mode(
    session: Session,
    simulator_id: int,
    old_strategy: str,
    new_strategy: str,
    now: datetime | None = None,
) -> None:
    """Drop orders queued by the mode a simulator is leaving. The caller commits.

    Switching to manual cancels the strategy's orders waiting for the next open;
    switching to a strategy cancels the user's queued manual orders.
    """
    now = now or current_time()
    if new_strategy == MANUAL_STRATEGY_NAME and old_strategy != MANUAL_STRATEGY_NAME:
        signals = session.execute(
            select(SimulatorSignal)
            .where(SimulatorSignal.simulator_id == simulator_id)
            .where(SimulatorSignal.status == SignalExecutionStatus.PENDING.value)
        ).scalars().all()
        for signal in signals:
            signal.status = SignalExecutionStatus.SKIPPED.value
            signal.execution_error = "cancelled: switched to manual trading"
            signal.executed_at = now
    elif old_strategy == MANUAL_STRATEGY_NAME and new_strategy != MANUAL_STRATEGY_NAME:
        orders = session.execute(
            select(SimulatorOrder)
            .where(SimulatorOrder.simulator_id == simulator_id)
            .where(SimulatorOrder.status == OrderStatus.PENDING.value)
        ).scalars().all()
        for order in orders:
            order.error = "Cancelled: switched to automated trading"
            _close(order, OrderStatus.CANCELLED, now)


def _require_manual(simulator: Simulator) -> None:
    if simulator.strategy_name != MANUAL_STRATEGY_NAME:
        raise OrderRejected(
            "This simulator trades automatically. Switch its strategy to Manual trading "
            "to place orders yourself."
        )


def _market_price(ticker: str) -> Decimal:
    price = fetch_last_price(ticker)
    if price is None:
        raise OrderRejected(
            f"Couldn't get a price for {ticker}. Check the ticker or try again in a moment."
        )
    return price


def _lock_simulator(session: Session, simulator_id: int) -> Simulator:
    """Load the simulator for update, so concurrent orders can't spend the same cash."""
    return session.execute(
        select(Simulator)
        .where(Simulator.simulator_id == simulator_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one()


def _load_book(
    session: Session,
    simulator: Simulator,
    ticker: str,
    market_price: Decimal,
    now: datetime,
    reserve: bool,
) -> _Book:
    cash = Decimal(str(simulator.cash_balance))
    positions = session.execute(
        select(SimulatorPosition).where(
            SimulatorPosition.simulator_id == simulator.simulator_id
        )
    ).scalars().all()
    holdings = {row.ticker.strip().upper(): Decimal(str(row.shares)) for row in positions}

    # Value holdings at their latest close, falling back to what was paid for them
    # (manually traded stocks may have no stored bars); only the risk caps use this.
    marks = {row.ticker.strip().upper(): Decimal(str(row.avg_cost)) for row in positions}
    marks.update(_latest_closes(session, sorted(holdings), now))
    marks[ticker] = market_price

    reserved_cash = reserved_shares = Decimal("0")
    if reserve:
        rules = ExecutionRules.for_simulator(simulator)
        pending = session.execute(
            select(SimulatorOrder)
            .where(SimulatorOrder.simulator_id == simulator.simulator_id)
            .where(SimulatorOrder.status == OrderStatus.PENDING.value)
        ).scalars().all()
        for order in pending:
            order_shares = Decimal(str(order.shares))
            if order.side == SignalAction.BUY.value:
                price = estimate_fill_price(
                    SignalAction.BUY, Decimal(str(order.quote_price)), rules.slippage_bps
                )
                reserved_cash += price * order_shares + rules.fee_per_trade
            elif order.ticker == ticker:
                reserved_shares += order_shares

    return _Book(
        cash=cash,
        held=holdings.get(ticker, Decimal("0")),
        reserved_cash=reserved_cash,
        reserved_shares=reserved_shares,
        equity=portfolio_equity(cash, holdings, marks),
    )


def _latest_closes(session: Session, symbols: list[str], now: datetime) -> dict[str, Decimal]:
    if not symbols:
        return {}
    since = now.astimezone(MARKET_TZ).date() - timedelta(days=MARK_LOOKBACK_DAYS)
    rows = session.execute(
        select(PriceBarModel)
        .where(PriceBarModel.symbol.in_(symbols))
        .where(PriceBarModel.source == "yfinance")
        .where(PriceBarModel.day >= since)
        .order_by(PriceBarModel.symbol, PriceBarModel.day)
    ).scalars().all()
    return {row.symbol: Decimal(str(row.close)) for row in rows}


def _opening_prices(
    session: Session,
    wanted: set[tuple[str, date]],
) -> dict[tuple[str, date], Decimal]:
    """Each (symbol, day)'s opening price: stored bars first, then Yahoo.

    Today's bar is still forming during the session, but its open is final.
    """
    if not wanted:
        return {}
    rows = session.execute(
        select(PriceBarModel)
        .where(PriceBarModel.symbol.in_(sorted({symbol for symbol, _ in wanted})))
        .where(PriceBarModel.day.in_(sorted({day for _, day in wanted})))
        .where(PriceBarModel.source == "yfinance")
    ).scalars().all()
    opens = {
        (row.symbol, row.day): Decimal(str(row.open))
        for row in rows
        if (row.symbol, row.day) in wanted
    }

    missing = wanted - opens.keys()
    provider = YahooPriceProvider()
    for day in sorted({day for _, day in missing}):
        symbols = sorted(symbol for symbol, missing_day in missing if missing_day == day)
        for bar in provider.fetch_daily_bars(symbols, day):
            if bar.open.is_finite() and bar.open > 0:
                opens[(bar.symbol, day)] = bar.open
    return opens


def _size(
    simulator: Simulator,
    ticker: str,
    side: SignalAction,
    shares: Decimal,
    market_price: Decimal,
    book: _Book,
) -> Fill:
    """Price the order with plan_fill(), or raise OrderRejected explaining why not.

    A manual order is all-or-nothing: where a strategy's buy would be shrunk to
    fit a risk limit, the user is told the most they can buy instead.
    """
    rules = ExecutionRules.for_simulator(simulator)
    result = plan_fill(
        side=side,
        quantity=shares,
        market_price=market_price,
        cash=book.available_cash,
        held_shares=book.available_shares,
        equity=book.equity,
        rules=rules,
    )
    if isinstance(result, Fill):
        if result.limited_by is None:
            return result
        raise OrderRejected(_limit_message(result.limited_by, result.quantity, ticker, simulator))

    reason = result.reason
    if reason == "insufficient cash":
        cost = estimate_fill_price(side, market_price, rules.slippage_bps) * shares
        set_aside = (
            " (some is set aside for your queued orders)" if book.reserved_cash > 0 else ""
        )
        raise OrderRejected(
            f"Not enough cash: this order needs about {_money(cost + rules.fee_per_trade)}, "
            f"and {_money(max(book.available_cash, Decimal('0')))} is available{set_aside}"
        )
    if reason == "insufficient shares":
        if book.held <= 0:
            raise OrderRejected(f"You don't own any {ticker} shares")
        queued = " (the rest are in queued sell orders)" if book.reserved_shares > 0 else ""
        raise OrderRejected(
            f"You can sell at most {_shares(max(book.available_shares, Decimal('0')))} "
            f"{ticker} shares{queued}"
        )
    if reason.startswith("exceeds "):
        raise OrderRejected(
            _limit_message(reason.removeprefix("exceeds "), Decimal("0"), ticker, simulator)
        )
    raise OrderRejected(f"Order rejected: {reason}")


def _limit_message(limited_by: str, most: Decimal, ticker: str, simulator: Simulator) -> str:
    if limited_by == "max_position_pct":
        pct = Decimal(str(simulator.max_position_pct)).normalize()
        limit = f"Your max position size is {pct:f}% of the portfolio"
        if most <= 0:
            return f"{limit}, and {ticker} is already at it"
        return f"{limit}: you can buy at most {_shares(most)} more {ticker} shares"
    if limited_by == "max_order_value":
        rules = ExecutionRules.for_simulator(simulator)
        return (
            f"Orders are capped at {_money(rules.max_order_value)}: "
            f"you can buy at most {_shares(most)} {ticker} shares"
        )
    return f"Order exceeds {limited_by}"


def _record_fill(
    session: Session,
    simulator: Simulator,
    ticker: str,
    fill: Fill,
    executed_at: datetime,
) -> SimulatorTrade:
    """Save the trade and its cash movement, then rebuild cash and positions from the ledger."""
    balance_after = Decimal(str(simulator.cash_balance)) + fill.cash_delta
    trade = SimulatorTrade(
        simulator_id=simulator.simulator_id,
        ticker=ticker,
        side=fill.side.value,
        price=fill.price,
        shares=fill.quantity,
        fee=fill.fee,
        executed_at=executed_at,
        source=MANUAL_SOURCE,
        balance_after=balance_after,
    )
    session.add(trade)
    session.add(
        SimulatorCashLedger(
            simulator_id=simulator.simulator_id,
            delta=fill.cash_delta,
            reason=fill.side.value,
            balance_after=balance_after,
            source=MANUAL_SOURCE,
        )
    )
    session.flush()
    PortfolioService().reconcile_simulator(session=session, simulator_id=simulator.simulator_id)
    # Later orders in this session read positions back with queries.
    session.flush()
    return trade


def _close(order: SimulatorOrder, status: OrderStatus, now: datetime) -> None:
    order.status = status.value
    order.closed_at = now


def _money(value: Decimal | None) -> str:
    return f"${value:,.2f}" if value is not None else "the limit"


def _shares(value: Decimal) -> str:
    return f"{value.normalize():f}"
