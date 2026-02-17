from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.models.price_bar import PriceBar as PriceBarModel
from src.models.simulator import Simulator
from src.models.simulator_position import SimulatorPosition
from src.models.simulator_signal import SimulatorSignal
from src.models.simulator_trade import SimulatorTrade

from .actions import SignalAction
from .portfolio import PortfolioSnapshot
from .strategy import Signal


class SignalExecutionStatus(str, Enum):
    PENDING = "pending"
    EXECUTED = "executed"
    SKIPPED = "skipped"
    FAILED = "failed"


class SignalOutcome(str, Enum):
    EXECUTED = "executed"
    SKIPPED = "skipped"
    FAILED = "failed"


@dataclass(frozen=True)
class ExecutionRules:
    """Risk and cost constraints applied during paper execution."""

    max_position_pct: Decimal
    max_order_value: Decimal
    fee_per_trade: Decimal
    slippage_bps: Decimal


@dataclass(frozen=True)
class Trade:
    """Executed paper trade derived from a signal."""

    symbol: str
    side: SignalAction
    quantity: Decimal
    price: Decimal
    fee: Decimal
    executed_at: datetime
    strategy_name: str


class ExecutionService:
    """Turns signals into paper trades using rules and prices."""

    def execute_signals(
        self,
        signals: list[Signal],
        portfolio: PortfolioSnapshot,
        rules: ExecutionRules,
        prices: dict[str, Decimal],
    ) -> list[Trade]:
        raise NotImplementedError


@dataclass(frozen=True)
class ExecutionSummary:
    processed: int
    executed: int
    skipped: int
    failed: int
    trades_created: int


@dataclass(frozen=True)
class TradeIntent:
    signal_id: int
    simulator_id: int
    symbol: str
    side: SignalAction
    quantity: Decimal
    reference_price: Decimal
    strategy_name: str | None = None


@dataclass
class ExecutionContext:
    session: Session
    now: datetime
    fee_per_trade: Decimal
    slippage_bps: Decimal
    cash_by_sim: dict[int, Decimal]
    holdings_by_sim: dict[int, dict[str, Decimal]]


class PaperTradeExecutionService:
    """Executes pending simulator signals into paper trades."""

    def execute_pending_signals(
        self,
        session: Session,
        simulator_id: int | None = None,
        limit: int = 500,
        slippage_bps: Decimal = Decimal("0"),
        fee_per_trade: Decimal = Decimal("0"),
    ) -> ExecutionSummary:
        pending = self._load_pending_signals(
            session=session,
            simulator_id=simulator_id,
            limit=limit,
        )
        if not pending:
            return ExecutionSummary(0, 0, 0, 0, 0)

        simulator_ids = sorted({int(signal.simulator_id) for signal in pending})
        context = ExecutionContext(
            session=session,
            now=datetime.now(timezone.utc),
            fee_per_trade=fee_per_trade,
            slippage_bps=slippage_bps,
            cash_by_sim=self._load_cash_by_simulator(session, simulator_ids),
            holdings_by_sim=self._load_holdings_by_simulator(session, simulator_ids),
        )

        executed = 0
        skipped = 0
        failed = 0
        trades_created = 0

        for signal in pending:
            outcome, trade = self._process_signal(signal=signal, context=context)
            if trade is not None:
                session.add(trade)
                trades_created += 1
            if outcome is SignalOutcome.EXECUTED:
                executed += 1
            elif outcome is SignalOutcome.SKIPPED:
                skipped += 1
            else:
                failed += 1

        session.commit()
        return ExecutionSummary(
            processed=len(pending),
            executed=executed,
            skipped=skipped,
            failed=failed,
            trades_created=trades_created,
        )

    def _load_pending_signals(
        self,
        session: Session,
        simulator_id: int | None = None,
        limit: int = 500,
    ) -> list[SimulatorSignal]:
        stmt = (
            select(SimulatorSignal)
            .where(SimulatorSignal.status == SignalExecutionStatus.PENDING.value)
            .order_by(SimulatorSignal.created_at, SimulatorSignal.signal_id)
            .limit(limit)
        )
        if simulator_id is not None:
            stmt = stmt.where(SimulatorSignal.simulator_id == simulator_id)
        return session.execute(stmt).scalars().all()

    def _load_cash_by_simulator(
        self,
        session: Session,
        simulator_ids: list[int],
    ) -> dict[int, Decimal]:
        if not simulator_ids:
            return {}
        stmt = select(Simulator).where(Simulator.simulator_id.in_(simulator_ids))
        rows = session.execute(stmt).scalars().all()
        return {int(row.simulator_id): Decimal(str(row.cash_balance)) for row in rows}

    def _load_holdings_by_simulator(
        self,
        session: Session,
        simulator_ids: list[int],
    ) -> dict[int, dict[str, Decimal]]:
        if not simulator_ids:
            return {}
        stmt = select(SimulatorPosition).where(
            SimulatorPosition.simulator_id.in_(simulator_ids)
        )
        rows = session.execute(stmt).scalars().all()
        holdings: dict[int, dict[str, Decimal]] = {}
        for row in rows:
            sim_id = int(row.simulator_id)
            symbol = row.ticker.strip().upper()
            holdings.setdefault(sim_id, {})
            holdings[sim_id][symbol] = Decimal(str(row.shares))
        return holdings

    def _get_latest_close(self, session: Session, symbol: str) -> Decimal | None:
        stmt = (
            select(PriceBarModel)
            .where(PriceBarModel.symbol == symbol)
            .where(PriceBarModel.source == "yfinance")
            .order_by(PriceBarModel.day.desc())
            .limit(1)
        )
        row = session.execute(stmt).scalars().first()
        if row is None:
            return None
        return Decimal(str(row.close))

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

    def _mark_failed(self, signal: SimulatorSignal, reason: str, now: datetime) -> None:
        signal.status = SignalExecutionStatus.FAILED.value
        signal.execution_error = reason
        signal.executed_at = now

    def _mark_skipped(self, signal: SimulatorSignal, reason: str, now: datetime) -> None:
        signal.status = SignalExecutionStatus.SKIPPED.value
        signal.execution_error = reason
        signal.executed_at = now

    def _mark_executed(self, signal: SimulatorSignal, now: datetime) -> None:
        signal.status = SignalExecutionStatus.EXECUTED.value
        signal.execution_error = None
        signal.executed_at = now

    def _process_signal(
        self,
        signal: SimulatorSignal,
        context: ExecutionContext,
    ) -> tuple[SignalOutcome, SimulatorTrade | None]:
        error = self._validate_signal(signal)
        if error:
            self._mark_failed(signal, error, context.now)
            return SignalOutcome.FAILED, None

        if signal.action == SignalAction.HOLD.value:
            self._mark_skipped(signal, "hold signal is not executable", context.now)
            return SignalOutcome.SKIPPED, None

        symbol = signal.ticker.strip().upper()
        price = self._get_latest_close(context.session, symbol)
        if price is None:
            self._mark_failed(signal, f"no latest price for ticker={symbol}", context.now)
            return SignalOutcome.FAILED, None

        sim_id = int(signal.simulator_id)
        current_cash = context.cash_by_sim.get(sim_id, Decimal("0"))
        current_holding = context.holdings_by_sim.get(sim_id, {}).get(symbol, Decimal("0"))

        intent = self._build_trade_intent(signal=signal, price=price)
        qty_error = self._size_executable_quantity(
            intent=intent,
            cash=current_cash,
            held_shares=current_holding,
            fee=context.fee_per_trade,
        )
        if qty_error:
            self._mark_failed(signal, qty_error, context.now)
            return SignalOutcome.FAILED, None

        risk_error = self._apply_risk_rules(
            intent=intent,
            cash=current_cash,
            held_shares=current_holding,
            fee=context.fee_per_trade,
        )
        if risk_error:
            self._mark_failed(signal, risk_error, context.now)
            return SignalOutcome.FAILED, None

        fill_price = self._estimate_fill_price(
            side=intent.side,
            market_price=intent.reference_price,
            slippage_bps=context.slippage_bps,
        )
        fee = context.fee_per_trade
        trade = self._to_trade(
            simulator_id=sim_id,
            symbol=symbol,
            side=intent.side,
            quantity=intent.quantity,
            fill_price=fill_price,
            fee=fee,
            executed_at=context.now,
        )

        trade_value = fill_price * intent.quantity
        if intent.side is SignalAction.BUY:
            context.cash_by_sim[sim_id] = current_cash - trade_value - fee
            context.holdings_by_sim.setdefault(sim_id, {})
            context.holdings_by_sim[sim_id][symbol] = current_holding + intent.quantity
        elif intent.side is SignalAction.SELL:
            context.cash_by_sim[sim_id] = current_cash + trade_value - fee
            context.holdings_by_sim.setdefault(sim_id, {})
            context.holdings_by_sim[sim_id][symbol] = current_holding - intent.quantity

        self._mark_executed(signal, context.now)
        return SignalOutcome.EXECUTED, trade

    def _build_trade_intent(self, signal: SimulatorSignal, price: Decimal) -> TradeIntent:
        return TradeIntent(
            signal_id=int(signal.signal_id),
            simulator_id=int(signal.simulator_id),
            symbol=signal.ticker.strip().upper(),
            side=SignalAction(signal.action.lower()),
            quantity=Decimal(str(signal.quantity)),
            reference_price=Decimal(str(price)),
            strategy_name=signal.strategy_name,
        )

    def _apply_risk_rules(
        self,
        intent: TradeIntent,
        cash: Decimal,
        held_shares: Decimal,
        fee: Decimal,
    ) -> str | None:
        qty = intent.quantity
        price = intent.reference_price
        side = intent.side
        if side is SignalAction.BUY:
            total = qty * price + fee
            if total > cash:
                return "insufficient cash"
        elif side is SignalAction.SELL:
            if qty > held_shares:
                return "insufficient shares"
        else:
            return "non-tradable action"
        return None

    def _estimate_fill_price(
        self,
        side: SignalAction,
        market_price: Decimal,
        slippage_bps: Decimal,
    ) -> Decimal:
        if slippage_bps <= Decimal("0"):
            return market_price
        bps = slippage_bps / Decimal("10000")
        if side is SignalAction.BUY:
            return market_price * (Decimal("1") + bps)
        return market_price * (Decimal("1") - bps)

    def _size_executable_quantity(
        self,
        intent: TradeIntent,
        cash: Decimal,
        held_shares: Decimal,
        fee: Decimal,
    ) -> str | None:
        qty = intent.quantity
        price = intent.reference_price
        side = intent.side
        if qty <= 0:
            return "non-positive trade quantity"
        if side is SignalAction.BUY:
            if price <= 0:
                return "invalid price"
            max_affordable = (cash - fee) / price if cash > fee else Decimal("0")
            if qty > max_affordable:
                return "requested quantity exceeds affordable quantity"
        elif side is SignalAction.SELL:
            if qty > held_shares:
                return "requested quantity exceeds held shares"
        return None

    def _to_trade(
        self,
        simulator_id: int,
        symbol: str,
        side: SignalAction,
        quantity: Decimal,
        fill_price: Decimal,
        fee: Decimal,
        executed_at: datetime,
    ) -> SimulatorTrade:
        return SimulatorTrade(
            simulator_id=simulator_id,
            ticker=symbol,
            side=side.value,
            price=fill_price,
            shares=quantity,
            fee=fee,
            executed_at=executed_at,
        )
