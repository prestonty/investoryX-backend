from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from typing import List

from src.api.database.database import get_db
from src.api.auth.auth import get_current_active_user
from src.models.users import Users
from src.models.simulator import Simulator
from src.models.simulator_tracked_stock import SimulatorTrackedStock
from src.models.simulator_position import SimulatorPosition
from src.models.simulator_trade import SimulatorTrade
from src.models.simulator_cash_ledger import SimulatorCashLedger
from src.models.simulator_schemas import (
    SimulatorCreate,
    SimulatorResponse,
    SimulatorTrackedStockCreate,
    SimulatorTrackedStockResponse,
    SimulatorSummaryResponse,
    SimulatorPositionResponse,
    SimulatorTradeResponse,
    SimulatorCashLedgerResponse,
    MessageResponse,
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
        user_id=current_user.user_id,
    )
    db.add(simulator)
    db.commit()
    db.refresh(simulator)
    return simulator


@router.get("/", response_model=List[SimulatorResponse])
def list_simulators(
    db: Session = Depends(get_db),
    current_user: Users = Depends(get_current_active_user),
):
    return (
        db.query(Simulator)
        .filter(Simulator.user_id == current_user.user_id)
        .order_by(Simulator.simulator_id.desc())
        .all()
    )


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


@router.delete("/{simulator_id}", response_model=MessageResponse)
def delete_simulator(
    simulator_id: int,
    db: Session = Depends(get_db),
    current_user: Users = Depends(get_current_active_user),
):
    simulator = get_user_simulator(db, simulator_id, current_user.user_id)
    if not simulator:
        raise HTTPException(status_code=404, detail="Simulator not found")

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
