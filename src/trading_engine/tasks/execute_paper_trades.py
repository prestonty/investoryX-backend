from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from celery import shared_task
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.api.database.database import SessionLocal
from src.models.price_bar import PriceBar
from src.models.simulator import Simulator
from src.models.simulator_position import SimulatorPosition
from src.models.simulator_signal import SimulatorSignal
from src.models.simulator_trade import SimulatorTrade
from src.trading_engine.services.execution import (
    ExecutionSummary,
    SignalExecutionStatus,
    SignalOutcome,
    TradeIntent,
)
from src.trading_engine.services.strategy import SignalAction

@dataclass
class ExecutionContext:
    session: Session
    now: datetime
    fee_per_trade: Decimal
    slippage_bps: Decimal
    cash_by_sim: dict[int, Decimal]
    holdings_by_sim: dict[int, dict[str, Decimal]]

@shared_task(name="trading_engine.execute_paper_trades")
def record_paper_trades(
    simulator_id: int | None = None,
    limit: int = 500,
    slippage_bps: str | Decimal = "0",
    fee_per_trade: str | Decimal = "0",
) -> ExecutionSummary:
    # Celery/JSON boundaries should pass financial inputs as strings.
    # We normalize to Decimal immediately inside execute_signals().
    return execute_signals(
        simulator_id=simulator_id,
        limit=limit,
        slippage_bps=slippage_bps,
        fee_per_trade=fee_per_trade,
    )


def execute_signals(
    simulator_id: int | None = None,
    limit: int = 500,
    slippage_bps: str | Decimal = "0",
    fee_per_trade: str | Decimal = "0",
) -> ExecutionSummary:
    # Main execution loop: pending signals -> validated intents -> simulated trades.
    session = SessionLocal()
    try:
        # Convert at the boundary once, then keep all internal math in Decimal.
        slippage_bps_decimal = Decimal(str(slippage_bps))
        fee_per_trade_decimal = Decimal(str(fee_per_trade))

        pending = _load_pending_signals(
            session=session,
            simulator_id=simulator_id,
            limit=limit,
        )
        if not pending:
            return ExecutionSummary(
                processed=0,
                executed=0,
                skipped=0,
                failed=0,
                trades_created=0,
            )

        simulator_ids = sorted({int(signal.simulator_id) for signal in pending})
        context = ExecutionContext(
            session=session,
            now=datetime.now(timezone.utc),
            fee_per_trade=fee_per_trade_decimal,
            slippage_bps=slippage_bps_decimal,
            cash_by_sim=_load_cash_by_simulator(session, simulator_ids),
            holdings_by_sim=_load_holdings_by_simulator(session, simulator_ids),
        )

        executed = 0
        skipped = 0
        failed = 0
        trades_created = 0

        for signal in pending:
            outcome, trade = _process_signal(signal=signal, context=context)
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
        # One commit at the end keeps signal/trade updates atomic for this batch.
        return ExecutionSummary(
                processed=len(pending),
                executed=executed,
                skipped=skipped,
                failed=failed,
                trades_created=trades_created,
            )
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _load_pending_signals(
    session,
    simulator_id: int | None = None,
    limit: int = 500,
) -> list[SimulatorSignal]:
    # Fetch oldest pending signals first for deterministic processing.
    stmt = (
        select(SimulatorSignal)
        .where(SimulatorSignal.status == SignalExecutionStatus.PENDING.value)
        .order_by(SimulatorSignal.created_at, SimulatorSignal.signal_id)
        .limit(limit)
    )
    if simulator_id is not None:
        stmt = stmt.where(SimulatorSignal.simulator_id == simulator_id)
    return session.execute(stmt).scalars().all()


def _load_cash_by_simulator(session, simulator_ids: list[int]) -> dict[int, Decimal]:
    if not simulator_ids:
        return {}
    stmt = select(Simulator).where(Simulator.simulator_id.in_(simulator_ids))
    rows = session.execute(stmt).scalars().all()
    return {int(row.simulator_id): Decimal(str(row.cash_balance)) for row in rows}


def _load_holdings_by_simulator(
    session,
    simulator_ids: list[int],
) -> dict[int, dict[str, Decimal]]:
    if not simulator_ids:
        return {}
    stmt = select(SimulatorPosition).where(SimulatorPosition.simulator_id.in_(simulator_ids))
    rows = session.execute(stmt).scalars().all()
    holdings: dict[int, dict[str, Decimal]] = {}
    for row in rows:
        sim_id = int(row.simulator_id)
        symbol = row.ticker.strip().upper()
        holdings.setdefault(sim_id, {})
        holdings[sim_id][symbol] = Decimal(str(row.shares))
    return holdings


def _get_latest_close(session, symbol: str) -> Decimal | None:
    # Execution uses latest known close as the reference market price.
    stmt = (
        select(PriceBar)
        .where(PriceBar.symbol == symbol)
        .where(PriceBar.source == "yfinance")
        .order_by(PriceBar.day.desc())
        .limit(1)
    )
    row = session.execute(stmt).scalars().first()
    if row is None:
        return None
    return Decimal(str(row.close))


def _validate_signal(signal: SimulatorSignal) -> str | None:
    # Basic structural checks only (action/ticker/quantity sanity).
    if not signal.ticker or not signal.ticker.strip():
        return "signal missing ticker"
    if signal.action not in {action.value for action in SignalAction}:
        return f"unsupported action={signal.action}"
    if Decimal(str(signal.quantity)) <= 0 and signal.action != SignalAction.HOLD.value:
        return "signal quantity must be positive"
    return None


def _mark_failed(signal: SimulatorSignal, reason: str, now: datetime) -> None:
    signal.status = SignalExecutionStatus.FAILED.value
    signal.execution_error = reason
    signal.executed_at = now


def _mark_skipped(signal: SimulatorSignal, reason: str, now: datetime) -> None:
    signal.status = SignalExecutionStatus.SKIPPED.value
    signal.execution_error = reason
    signal.executed_at = now


def _mark_executed(signal: SimulatorSignal, now: datetime) -> None:
    signal.status = SignalExecutionStatus.EXECUTED.value
    signal.execution_error = None
    signal.executed_at = now


def _process_signal(
    signal: SimulatorSignal,
    context: ExecutionContext,
) -> tuple[SignalOutcome, SimulatorTrade | None]:
    # Validate raw signal payload before any market/portfolio work.
    error = _validate_signal(signal)
    if error:
        # Structural invalid signal (bad action/ticker/qty). Mark failed and stop.
        _mark_failed(signal, error, context.now)
        return SignalOutcome.FAILED, None

    if signal.action == SignalAction.HOLD.value:
        # Hold signals are expected but intentionally non-executable.
        # We persist this as skipped so the signal leaves the pending queue.
        _mark_skipped(signal, "hold signal is not executable", context.now)
        return SignalOutcome.SKIPPED, None

    # Resolve current market reference for the symbol.
    symbol = signal.ticker.strip().upper()
    price = _get_latest_close(context.session, symbol)
    if price is None:
        # Missing market data means the signal cannot be executed safely.
        _mark_failed(signal, f"no latest price for ticker={symbol}", context.now)
        return SignalOutcome.FAILED, None

    # Pull mutable in-memory portfolio state for this simulator.
    # This lets multiple signals in one batch see prior in-batch effects.
    sim_id = int(signal.simulator_id)
    current_cash = context.cash_by_sim.get(sim_id, Decimal("0"))
    current_holding = context.holdings_by_sim.get(sim_id, {}).get(symbol, Decimal("0"))

    # Translate signal + price into the normalized execution intent model.
    intent = _build_trade_intent(signal=signal, price=price)
    # Quantity and risk checks are kept separate for clearer failure reasons.
    qty_error = _size_executable_quantity(
        intent=intent,
        cash=current_cash,
        held_shares=current_holding,
        fee=context.fee_per_trade,
    )
    if qty_error:
        # Quantity cannot be executed with current portfolio constraints.
        _mark_failed(signal, qty_error, context.now)
        return SignalOutcome.FAILED, None

    risk_error = _apply_risk_rules(
        intent=intent,
        cash=current_cash,
        held_shares=current_holding,
        fee=context.fee_per_trade,
    )
    if risk_error:
        # Risk rule rejected this intent (cash/shares/non-tradable action).
        _mark_failed(signal, risk_error, context.now)
        return SignalOutcome.FAILED, None

    # Compute execution economics for paper fill (slippage + fixed fee).
    fill_price = _estimate_fill_price(
        side=intent.side,
        market_price=intent.reference_price,
        slippage_bps=context.slippage_bps,
    )
    fee = context.fee_per_trade
    trade = _to_trade(
        simulator_id=sim_id,
        symbol=symbol,
        side=intent.side,
        quantity=intent.quantity,
        fill_price=fill_price,
        fee=fee,
        executed_at=context.now,
    )

    # Update in-memory balances to keep same-run decisions consistent.
    # DB portfolio tables are reconciled later by the reconciliation task.
    trade_value = fill_price * intent.quantity
    if intent.side is SignalAction.BUY:
        context.cash_by_sim[sim_id] = current_cash - trade_value - fee
        context.holdings_by_sim.setdefault(sim_id, {})
        context.holdings_by_sim[sim_id][symbol] = current_holding + intent.quantity
    elif intent.side is SignalAction.SELL:
        context.cash_by_sim[sim_id] = current_cash + trade_value - fee
        context.holdings_by_sim.setdefault(sim_id, {})
        context.holdings_by_sim[sim_id][symbol] = current_holding - intent.quantity

    # Signal processed successfully; caller will add trade to session and commit batch.
    _mark_executed(signal, context.now)
    return SignalOutcome.EXECUTED, trade


def _build_trade_intent(signal: SimulatorSignal, price: Decimal) -> TradeIntent:
    # Normalize DB signal + market price into an execution-domain intent object.
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
    intent: TradeIntent,
    cash: Decimal,
    held_shares: Decimal,
    fee: Decimal,
) -> str | None:
    # Hard risk checks: buy requires cash, sell requires available shares.
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
    side: SignalAction,
    market_price: Decimal,
    slippage_bps: Decimal,
) -> Decimal:
    # Apply simple slippage model around the reference price.
    if slippage_bps <= Decimal("0"):
        return market_price
    bps = slippage_bps / Decimal("10000")
    if side is SignalAction.BUY:
        return market_price * (Decimal("1") + bps)
    return market_price * (Decimal("1") - bps)


def _size_executable_quantity(
    intent: TradeIntent,
    cash: Decimal,
    held_shares: Decimal,
    fee: Decimal,
) -> str | None:
    # Ensure requested quantity is executable for the current portfolio state.
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
    simulator_id: int,
    symbol: str,
    side: SignalAction,
    quantity: Decimal,
    fill_price: Decimal,
    fee: Decimal,
    executed_at: datetime,
) -> SimulatorTrade:
    # DB stores action as string, so serialize enum value at write time.
    return SimulatorTrade(
        simulator_id=simulator_id,
        ticker=symbol,
        side=side.value,
        price=fill_price,
        shares=quantity,
        fee=fee,
        executed_at=executed_at,
    )
