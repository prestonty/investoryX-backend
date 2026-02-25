from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, selectinload
from sqlalchemy.exc import IntegrityError
from typing import List
from decimal import Decimal
from datetime import datetime, timedelta, timezone

from src.api.database.database import get_db
from src.api.auth.auth import get_current_active_user
from src.api.services.stock_data_service import getStockHistory
from src.data_types.history import Period, Interval
from src.models.users import Users
from src.models.simulator import Simulator
from src.models.simulator_tracked_stock import SimulatorTrackedStock
from src.models.simulator_position import SimulatorPosition
from src.models.simulator_trade import SimulatorTrade
from src.models.simulator_cash_ledger import SimulatorCashLedger
from src.models.simulator_schemas import (
    SimulatorCreate,
    SimulatorResponse,
    SimulatorRenameRequest,
    SimulatorSettingsUpdateRequest,
    SimulatorTrackedStockCreate,
    SimulatorTrackedStockResponse,
    SimulatorSummaryResponse,
    SimulatorPositionResponse,
    SimulatorTradeResponse,
    SimulatorCashLedgerResponse,
    MessageResponse,
    SimulatorRunResponse,
    SimulatorRunRequest,
)


router = APIRouter(prefix="/api/simulator", tags=["simulator"])


def get_user_simulator(
    db: Session,
    simulator_id: int,
    user_id: int,
) -> Simulator | None:
    return (
        db.query(Simulator)
        .filter(
            Simulator.simulator_id == simulator_id,
            Simulator.user_id == user_id,
        )
        .first()
    )


@router.post("/", response_model=SimulatorResponse)
def create_simulator(
    payload: SimulatorCreate,
    db: Session = Depends(get_db),
    current_user: Users = Depends(get_current_active_user),
):
    simulator = Simulator(
        name=payload.name,
        starting_cash=payload.starting_cash,
        cash_balance=payload.starting_cash,
        status=payload.status,
        frequency=payload.frequency,
        price_mode=payload.price_mode,
        max_position_pct=payload.max_position_pct,
        max_daily_loss_pct=payload.max_daily_loss_pct,
        stopped_reason=payload.stopped_reason,
        user_id=current_user.user_id,
    )
    db.add(simulator)
    db.commit()
    db.refresh(simulator)
    return simulator

@router.patch("/rename/{simulator_id}/", response_model=SimulatorResponse)
def rename_simulator(
    simulator_id: int,
    payload: SimulatorRenameRequest,
    db: Session = Depends(get_db),
    current_user: Users = Depends(get_current_active_user),
):
    simulator = get_user_simulator(db, simulator_id, current_user.user_id)
    if not simulator:
        raise HTTPException(status_code=404, detail="Simulator not found")

    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Name cannot be empty")

    simulator.name = name
    db.add(simulator)
    db.commit()
    db.refresh(simulator)
    return SimulatorResponse.model_validate(simulator)


@router.patch("/{simulator_id}/settings", response_model=SimulatorResponse)
def update_simulator_settings(
    simulator_id: int,
    payload: SimulatorSettingsUpdateRequest,
    db: Session = Depends(get_db),
    current_user: Users = Depends(get_current_active_user),
):
    simulator = get_user_simulator(db, simulator_id, current_user.user_id)
    if not simulator:
        raise HTTPException(status_code=404, detail="Simulator not found")

    if "frequency" in payload.model_fields_set and payload.frequency is not None:
        simulator.frequency = payload.frequency
    if "price_mode" in payload.model_fields_set and payload.price_mode is not None:
        simulator.price_mode = payload.price_mode
    if "max_position_pct" in payload.model_fields_set:
        simulator.max_position_pct = payload.max_position_pct
    if "max_daily_loss_pct" in payload.model_fields_set:
        simulator.max_daily_loss_pct = payload.max_daily_loss_pct

    db.add(simulator)
    db.commit()
    db.refresh(simulator)
    return SimulatorResponse.model_validate(simulator)


@router.get("/", response_model=List[SimulatorResponse])
def list_simulators(
    db: Session = Depends(get_db),
    current_user: Users = Depends(get_current_active_user),
):
    sims = (
        db.query(Simulator)
        .options(selectinload(Simulator.tracked_stocks))
        .filter(Simulator.user_id == current_user.user_id)
        .order_by(Simulator.simulator_id.desc())
        .all()
    )
    return [
        SimulatorResponse(
            simulator_id=s.simulator_id,
            user_id=s.user_id,
            name=s.name,
            starting_cash=s.starting_cash,
            cash_balance=s.cash_balance,
            status=s.status,
            last_run_at=s.last_run_at,
            next_run_at=s.next_run_at,
            frequency=s.frequency,
            price_mode=s.price_mode,
            max_position_pct=s.max_position_pct,
            max_daily_loss_pct=s.max_daily_loss_pct,
            stopped_reason=s.stopped_reason,
            created_at=s.created_at,
            updated_at=s.updated_at,
            tickers=[ts.ticker for ts in s.tracked_stocks],
        )
        for s in sims
    ]


@router.post(
    "/{simulator_id}/tracked-stocks",
    response_model=SimulatorTrackedStockResponse,
)
def add_tracked_stock(
    simulator_id: int,
    payload: SimulatorTrackedStockCreate,
    db: Session = Depends(get_db),
    current_user: Users = Depends(get_current_active_user),
):
    simulator = get_user_simulator(db, simulator_id, current_user.user_id)
    if not simulator:
        raise HTTPException(status_code=404, detail="Simulator not found")

    tracked = SimulatorTrackedStock(
        simulator_id=simulator_id,
        ticker=payload.ticker.upper(),
        target_allocation=payload.target_allocation,
        enabled=payload.enabled if payload.enabled is not None else True,
    )
    db.add(tracked)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=400, detail="Tracked stock already exists"
        )
    db.refresh(tracked)
    return tracked


@router.get("/{simulator_id}", response_model=SimulatorSummaryResponse)
def get_simulator_summary(
    simulator_id: int,
    db: Session = Depends(get_db),
    current_user: Users = Depends(get_current_active_user),
):
    simulator = get_user_simulator(db, simulator_id, current_user.user_id)
    if not simulator:
        raise HTTPException(status_code=404, detail="Simulator not found")

    tracked_stocks = (
        db.query(SimulatorTrackedStock)
        .filter(SimulatorTrackedStock.simulator_id == simulator_id)
        .order_by(SimulatorTrackedStock.tracked_id)
        .all()
    )
    positions = (
        db.query(SimulatorPosition)
        .filter(SimulatorPosition.simulator_id == simulator_id)
        .order_by(SimulatorPosition.position_id)
        .all()
    )
    trades = (
        db.query(SimulatorTrade)
        .filter(SimulatorTrade.simulator_id == simulator_id)
        .order_by(SimulatorTrade.executed_at.desc())
        .all()
    )
    cash_ledger = (
        db.query(SimulatorCashLedger)
        .filter(SimulatorCashLedger.simulator_id == simulator_id)
        .order_by(SimulatorCashLedger.created_at.desc())
        .all()
    )

    return SimulatorSummaryResponse(
        simulator=SimulatorResponse.model_validate(simulator),
        tracked_stocks=[
            SimulatorTrackedStockResponse.model_validate(item)
            for item in tracked_stocks
        ],
        positions=[
            SimulatorPositionResponse.model_validate(item)
            for item in positions
        ],
        trades=[
            SimulatorTradeResponse.model_validate(item)
            for item in trades
        ],
        cash_ledger=[
            SimulatorCashLedgerResponse.model_validate(item)
            for item in cash_ledger
        ],
    )


@router.post("/{simulator_id}/run", response_model=SimulatorRunResponse)
def run_simulator(
    simulator_id: int,
    payload: SimulatorRunRequest,
    db: Session = Depends(get_db),
    current_user: Users = Depends(get_current_active_user),
):
    simulator = get_user_simulator(db, simulator_id, current_user.user_id)
    if not simulator:
        raise HTTPException(status_code=404, detail="Simulator not found")

    price_mode = payload.price_mode or simulator.price_mode
    frequency = payload.frequency or simulator.frequency
    simulator.price_mode = price_mode
    simulator.frequency = frequency

    tracked_stocks = (
        db.query(SimulatorTrackedStock)
        .filter(
            SimulatorTrackedStock.simulator_id == simulator_id,
            SimulatorTrackedStock.enabled.is_(True),
        )
        .order_by(SimulatorTrackedStock.tracked_id)
        .all()
    )

    if not tracked_stocks:
        db.add(simulator)
        db.commit()
        db.refresh(simulator)
        return SimulatorRunResponse(
            message="No tracked stocks to evaluate",
            trades_executed=0,
            cash_balance=Decimal(str(simulator.cash_balance)),
            price_mode=price_mode,
            frequency=frequency,
        )

    fee_rate = Decimal("0.001")
    trades_executed = 0

    for tracked in tracked_stocks:
        ticker = tracked.ticker.upper()
        history = getStockHistory(
            ticker,
            period=Period.DAY_5,
            interval=Interval.DAY_1,
        )
        rows = history.get("data", []) if isinstance(history, dict) else []
        if not rows:
            continue
        latest = rows[-1]
        price_key = "open" if price_mode == "open" else "close"
        price = latest.get(price_key)
        if price is None:
            continue
        current_price = Decimal(str(price))
        if current_price <= 0:
            continue

        position = (
            db.query(SimulatorPosition)
            .filter(
                SimulatorPosition.simulator_id == simulator_id,
                SimulatorPosition.ticker == ticker,
            )
            .first()
        )

        if not position or Decimal(str(position.shares)) <= Decimal("0"):
            desired_investment = (
                Decimal(str(simulator.starting_cash))
                * Decimal(str(tracked.target_allocation))
                / Decimal("100")
            )
            available_cash = Decimal(str(simulator.cash_balance))
            buy_amount = min(desired_investment, available_cash)
            if buy_amount <= 0:
                continue

            total_cost = buy_amount * (Decimal("1") + fee_rate)
            if total_cost > available_cash:
                buy_amount = available_cash / (Decimal("1") + fee_rate)
                if buy_amount <= 0:
                    continue
                total_cost = buy_amount * (Decimal("1") + fee_rate)

            shares = buy_amount / current_price
            fee = buy_amount * fee_rate

            position = SimulatorPosition(
                simulator_id=simulator_id,
                ticker=ticker,
                shares=shares,
                avg_cost=current_price,
            )
            db.add(position)

            simulator.cash_balance = Decimal(str(simulator.cash_balance)) - total_cost
            db.add(
                SimulatorTrade(
                    simulator_id=simulator_id,
                    ticker=ticker,
                    side="buy",
                    price=current_price,
                    shares=shares,
                    fee=fee,
                )
            )
            db.add(
                SimulatorCashLedger(
                    simulator_id=simulator_id,
                    delta=-total_cost,
                    reason="buy",
                    balance_after=simulator.cash_balance,
                )
            )
            trades_executed += 1
            continue

        avg_cost = Decimal(str(position.avg_cost))
        if avg_cost <= 0:
            continue

        pct_change = (current_price - avg_cost) / avg_cost
        should_sell = pct_change >= Decimal("0.05") or pct_change <= Decimal("-0.05")
        if not should_sell:
            continue

        shares = Decimal(str(position.shares))
        proceeds = shares * current_price
        fee = proceeds * fee_rate
        net = proceeds - fee

        simulator.cash_balance = Decimal(str(simulator.cash_balance)) + net
        db.add(
            SimulatorTrade(
                simulator_id=simulator_id,
                ticker=ticker,
                side="sell",
                price=current_price,
                shares=shares,
                fee=fee,
            )
        )
        db.add(
            SimulatorCashLedger(
                simulator_id=simulator_id,
                delta=net,
                reason="sell",
                balance_after=simulator.cash_balance,
            )
        )

        position.shares = Decimal("0")
        position.avg_cost = Decimal("0")
        trades_executed += 1

    now_utc = datetime.now(timezone.utc)
    simulator.last_run_at = now_utc
    simulator.next_run_at = (
        now_utc + timedelta(hours=12)
        if frequency == "twice_daily"
        else now_utc + timedelta(days=1)
    )

    db.commit()
    db.refresh(simulator)

    return SimulatorRunResponse(
        message="Simulator run completed",
        trades_executed=trades_executed,
        cash_balance=Decimal(str(simulator.cash_balance)),
        price_mode=price_mode,
        frequency=frequency,
    )


@router.delete("/{simulator_id}", response_model=MessageResponse)
def delete_simulator(
    simulator_id: int,
    db: Session = Depends(get_db),
    current_user: Users = Depends(get_current_active_user),
):
    simulator = get_user_simulator(db, simulator_id, current_user.user_id)
    if not simulator:
        raise HTTPException(status_code=404, detail="Simulator not found")

    # Delete all items associated with this simulator id before deleting the simulator
    db.query(SimulatorTrackedStock).filter(
        SimulatorTrackedStock.simulator_id == simulator_id
    ).delete(synchronize_session=False)
    db.query(SimulatorPosition).filter(
        SimulatorPosition.simulator_id == simulator_id
    ).delete(synchronize_session=False)
    db.query(SimulatorTrade).filter(
        SimulatorTrade.simulator_id == simulator_id
    ).delete(synchronize_session=False)
    db.query(SimulatorCashLedger).filter(
        SimulatorCashLedger.simulator_id == simulator_id
    ).delete(synchronize_session=False)

    db.delete(simulator)
    db.commit()
    return {"message": "Simulator removed"}


@router.delete(
    "/{simulator_id}/tracked-stocks/{tracked_id}",
    response_model=MessageResponse,
)
def delete_tracked_stock(
    simulator_id: int,
    tracked_id: int,
    db: Session = Depends(get_db),
    current_user: Users = Depends(get_current_active_user),
):
    simulator = get_user_simulator(db, simulator_id, current_user.user_id)
    if not simulator:
        raise HTTPException(status_code=404, detail="Simulator not found")

    tracked = (
        db.query(SimulatorTrackedStock)
        .filter(
            SimulatorTrackedStock.simulator_id == simulator_id,
            SimulatorTrackedStock.tracked_id == tracked_id,
        )
        .first()
    )
    if not tracked:
        raise HTTPException(status_code=404, detail="Tracked stock not found")

    db.delete(tracked)
    db.commit()
    return {"message": "Tracked stock removed"}


@router.delete(
    "/{simulator_id}/tracked-stocks/by-ticker/{ticker}",
    response_model=MessageResponse,
)
def delete_tracked_stock_by_ticker(
    simulator_id: int,
    ticker: str,
    db: Session = Depends(get_db),
    current_user: Users = Depends(get_current_active_user),
):
    simulator = get_user_simulator(db, simulator_id, current_user.user_id)
    if not simulator:
        raise HTTPException(status_code=404, detail="Simulator not found")

    tracked = (
        db.query(SimulatorTrackedStock)
        .filter(
            SimulatorTrackedStock.simulator_id == simulator_id,
            SimulatorTrackedStock.ticker == ticker.upper(),
        )
        .first()
    )
    if not tracked:
        raise HTTPException(status_code=404, detail="Tracked stock not found")

    db.delete(tracked)
    db.commit()
    return {"message": "Tracked stock removed"}
