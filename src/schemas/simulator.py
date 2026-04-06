from datetime import datetime
from decimal import Decimal
from typing import List, Optional, Literal

from pydantic import BaseModel

SIMULATOR_STATUS_ACTIVE = "Active Trading"
SimulatorStatus = Literal["Active Trading", "Pause Trading"]
SIMULATOR_FREQUENCY_DAILY = "daily"
SIMULATOR_PRICE_MODE_CLOSE = "close"
SimulatorFrequency = Literal["daily", "twice_daily"]
SimulatorPriceMode = Literal["open", "close"]


class SimulatorCreate(BaseModel):
    name: str
    starting_cash: Decimal
    status: SimulatorStatus = SIMULATOR_STATUS_ACTIVE
    frequency: SimulatorFrequency = SIMULATOR_FREQUENCY_DAILY
    price_mode: SimulatorPriceMode = SIMULATOR_PRICE_MODE_CLOSE
    max_position_pct: Optional[Decimal] = None
    max_daily_loss_pct: Optional[Decimal] = None
    stopped_reason: Optional[str] = None


class SimulatorResponse(BaseModel):
    simulator_id: int
    user_id: Optional[int]
    name: str
    starting_cash: Decimal
    cash_balance: Decimal
    status: SimulatorStatus
    last_run_at: Optional[datetime]
    next_run_at: Optional[datetime]
    frequency: SimulatorFrequency
    price_mode: SimulatorPriceMode
    max_position_pct: Optional[Decimal]
    max_daily_loss_pct: Optional[Decimal]
    stopped_reason: Optional[str]
    created_at: Optional[datetime]
    updated_at: Optional[datetime]
    tickers: List[str] = []

    class Config:
        from_attributes = True


class SimulatorRenameRequest(BaseModel):
    name: str


class SimulatorSettingsUpdateRequest(BaseModel):
    frequency: Optional[SimulatorFrequency] = None
    price_mode: Optional[SimulatorPriceMode] = None
    max_position_pct: Optional[Decimal] = None
    max_daily_loss_pct: Optional[Decimal] = None


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
    price_mode: SimulatorPriceMode
    frequency: SimulatorFrequency


class SimulatorRunRequest(BaseModel):
    price_mode: Optional[SimulatorPriceMode] = None
    frequency: Optional[SimulatorFrequency] = None
