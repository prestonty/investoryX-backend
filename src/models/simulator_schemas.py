from datetime import datetime
from decimal import Decimal
from typing import List, Optional, Literal

from pydantic import BaseModel


class SimulatorCreate(BaseModel):
    name: str
    starting_cash: Decimal


class SimulatorResponse(BaseModel):
    simulator_id: int
    user_id: Optional[int]
    name: str
    starting_cash: Decimal
    cash_balance: Decimal
    created_at: Optional[datetime]
    updated_at: Optional[datetime]
    tickers: List[str] = []

    class Config:
        from_attributes = True


class SimulatorRenameRequest(BaseModel):
    name: str


class SimulatorTrackedStockCreate(BaseModel):
    ticker: str
    target_allocation: Decimal
    enabled: Optional[bool] = True


class SimulatorTrackedStockResponse(BaseModel):
    tracked_id: int
    simulator_id: int
    ticker: str
    target_allocation: Decimal
    enabled: bool

    class Config:
        from_attributes = True


class SimulatorPositionResponse(BaseModel):
    position_id: int
    simulator_id: int
    ticker: str
    shares: Decimal
    avg_cost: Decimal

    class Config:
        from_attributes = True


class SimulatorTradeResponse(BaseModel):
    trade_id: int
    simulator_id: int
    ticker: str
    side: str
    price: Decimal
    shares: Decimal
    fee: Decimal
    executed_at: Optional[datetime]

    class Config:
        from_attributes = True


class SimulatorCashLedgerResponse(BaseModel):
    ledger_id: int
    simulator_id: int
    delta: Decimal
    reason: str
    balance_after: Decimal
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


class SimulatorRunResponse(BaseModel):
    message: str
    trades_executed: int
    cash_balance: Decimal
    price_mode: str
    frequency: str


class SimulatorRunRequest(BaseModel):
    price_mode: Literal["open", "close"] = "close"
    frequency: Literal["daily", "twice_daily"] = "daily"
