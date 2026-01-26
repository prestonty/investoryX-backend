from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel


class SimulatorCreate(BaseModel):
    name: str
    starting_cash: float


class SimulatorResponse(BaseModel):
    simulator_id: int
    user_id: Optional[int]
    name: str
    starting_cash: float
    cash_balance: float
    created_at: Optional[datetime]
    updated_at: Optional[datetime]

    class Config:
        from_attributes = True


class SimulatorTrackedStockCreate(BaseModel):
    ticker: str
    target_allocation: float
    enabled: Optional[bool] = True


class SimulatorTrackedStockResponse(BaseModel):
    tracked_id: int
    simulator_id: int
    ticker: str
    target_allocation: float
    enabled: bool

    class Config:
        from_attributes = True


class SimulatorPositionResponse(BaseModel):
    position_id: int
    simulator_id: int
    ticker: str
    shares: float
    avg_cost: float

    class Config:
        from_attributes = True


class SimulatorTradeResponse(BaseModel):
    trade_id: int
    simulator_id: int
    ticker: str
    side: str
    price: float
    shares: float
    fee: float
    executed_at: Optional[datetime]

    class Config:
        from_attributes = True


class SimulatorCashLedgerResponse(BaseModel):
    ledger_id: int
    simulator_id: int
    delta: float
    reason: str
    balance_after: float
    created_at: Optional[datetime]

    class Config:
        from_attributes = True


class SimulatorSummaryResponse(BaseModel):
    simulator: SimulatorResponse
    tracked_stocks: List[SimulatorTrackedStockResponse]
    positions: List[SimulatorPositionResponse]
    trades: List[SimulatorTradeResponse]
    cash_ledger: List[SimulatorCashLedgerResponse]


class MessageResponse(BaseModel):
    message: str
