import re
from datetime import date, datetime
from decimal import Decimal
from typing import Any, List, Optional, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from src.trading_engine.strategies.catalog import (
    CATALOG,
    DEFAULT_STRATEGY_NAME,
    InvalidStrategyParams,
    effective_params,
)

SIMULATOR_STATUS_ACTIVE = "Active Trading"
SimulatorStatus = Literal["Active Trading", "Pause Trading"]
SIMULATOR_FREQUENCY_DAILY = "daily"
SimulatorFrequency = Literal["daily", "twice_daily"]


class SimulatorCreate(BaseModel):
    name: str
    starting_cash: Decimal
    status: SimulatorStatus = SIMULATOR_STATUS_ACTIVE
    frequency: SimulatorFrequency = SIMULATOR_FREQUENCY_DAILY
    max_position_pct: Optional[Decimal] = Field(None, gt=0, le=100)
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
    max_position_pct: Optional[Decimal]
    max_daily_loss_pct: Optional[Decimal]
    stopped_reason: Optional[str]
    strategy_name: str = DEFAULT_STRATEGY_NAME
    # Every param of strategy_name, with defaults filled in for unset ones.
    strategy_params: Optional[dict[str, Any]] = None
    created_at: Optional[datetime]
    updated_at: Optional[datetime]
    tickers: List[str] = []

    class Config:
        from_attributes = True

    @model_validator(mode="after")
    def _fill_param_defaults(self) -> "SimulatorResponse":
        try:
            self.strategy_params = effective_params(self.strategy_name, self.strategy_params)
        except InvalidStrategyParams:
            # Saved params no longer fit (e.g. after a strategy change); show them as stored.
            self.strategy_params = self.strategy_params or {}
        return self


class SimulatorRenameRequest(BaseModel):
    name: str


class SimulatorSettingsUpdateRequest(BaseModel):
    frequency: Optional[SimulatorFrequency] = None
    max_position_pct: Optional[Decimal] = Field(None, gt=0, le=100)
    max_daily_loss_pct: Optional[Decimal] = None
    strategy_name: Optional[str] = None
    # Replaces the saved params; omitted keys use the strategy's defaults.
    strategy_params: Optional[dict[str, Any]] = None

    @field_validator("strategy_name")
    @classmethod
    def _known_strategy(cls, value: str | None) -> str | None:
        if value is not None and value not in CATALOG:
            raise ValueError(f"must be one of: {', '.join(CATALOG)}")
        return value


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
    source: Optional[str] = "live"
    balance_after: Optional[Decimal] = None

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


class SimulatorDecisionResponse(BaseModel):
    """The strategy's latest decision for one tracked stock, and what became of it."""

    ticker: str
    action: str  # buy | sell | hold
    quantity: Decimal
    reason: str
    # pending = waiting for the next open; executed/skipped/failed after that.
    status: str
    execution_error: Optional[str] = None
    for_day: Optional[date] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class SimulatorOrderResponse(BaseModel):
    """A manual order queued while the market was closed, and what became of it."""

    order_id: int
    simulator_id: int
    ticker: str
    side: str  # buy | sell
    shares: Decimal
    # Last price when the order was placed.
    quote_price: Decimal
    # Trading day whose opening price fills the order.
    fill_day: date
    # pending = waiting for fill_day's open; filled, rejected or cancelled after that.
    status: str
    error: Optional[str] = None
    trade_id: Optional[int] = None
    created_at: Optional[datetime] = None
    closed_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class SimulatorSummaryResponse(BaseModel):
    simulator: SimulatorResponse
    tracked_stocks: List[SimulatorTrackedStockResponse]
    positions: List[SimulatorPositionResponse]
    trades: List[SimulatorTradeResponse]
    cash_ledger: List[SimulatorCashLedgerResponse]
    decisions: List[SimulatorDecisionResponse] = []
    # Recent manual orders queued for an open, newest first.
    orders: List[SimulatorOrderResponse] = []


class ManualOrderRequest(BaseModel):
    ticker: str
    side: Literal["buy", "sell"]
    # Whole shares only.
    shares: int = Field(gt=0, le=1_000_000)

    @field_validator("ticker")
    @classmethod
    def _normalize_ticker(cls, value: str) -> str:
        value = value.strip().upper()
        if not re.fullmatch(r"[A-Z0-9.\-]{1,10}", value):
            raise ValueError("Enter a ticker symbol")
        return value


class ManualOrderQuoteResponse(BaseModel):
    """What a market order would do if placed now."""

    ticker: str
    side: Literal["buy", "sell"]
    shares: Decimal
    # Latest price; the last close while the market is closed.
    market_price: Decimal
    # market_price with slippage against the trader.
    estimated_price: Decimal
    fee: Decimal
    # Cash paid for a buy, or received for a sell.
    estimated_total: Decimal
    slippage_bps: Decimal
    # False while the market is closed: the order waits for fill_day's open.
    fills_now: bool
    fill_day: date


class ManualOrderPlacedResponse(BaseModel):
    status: Literal["filled", "queued"]
    message: str
    quote: ManualOrderQuoteResponse
    trade: Optional[SimulatorTradeResponse] = None
    order: Optional[SimulatorOrderResponse] = None
    cash_balance: Decimal


class MessageResponse(BaseModel):
    message: str


class SimulatorRunResponse(BaseModel):
    message: str
    # Fills of the previous trading day's orders, at today's open.
    trades_executed: int
    # Buy/sell orders decided on today's close, waiting for the next open.
    orders_queued: int = 0
    cash_balance: Decimal
    frequency: SimulatorFrequency


class SimulatorRunRequest(BaseModel):
    frequency: Optional[SimulatorFrequency] = None


# ---------------------------------------------------------------------------
# Backtest (Trading Sandbox) schemas
# ---------------------------------------------------------------------------

class BacktestRequest(BaseModel):
    start_date: date
    end_date: date
    clear_previous: bool = True


class BacktestDayResult(BaseModel):
    day: date
    signals_generated: int
    trades_executed: int
    cash_after: Decimal
    skipped_tickers: List[str]


class BacktestResult(BaseModel):
    simulator_id: int
    start_date: date
    end_date: date
    trading_days_run: int
    total_trades: int
    starting_cash: Decimal
    final_cash: Decimal
    pnl: Decimal
    pnl_pct: Decimal
    # Market value of shares still held at end_date; pnl = final_equity - starting_cash.
    # Optional so results computed before these fields existed still parse.
    holdings_value: Optional[Decimal] = None
    final_equity: Optional[Decimal] = None
    day_results: List[BacktestDayResult]
    warnings: List[str]


class BacktestLaunchResponse(BaseModel):
    task_id: str
    message: str


class BacktestStatusResponse(BaseModel):
    task_id: str
    status: Literal["pending", "running", "success", "failure"]
    result: Optional[BacktestResult] = None
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Strategy catalog schemas
# ---------------------------------------------------------------------------

class StrategyParamSpec(BaseModel):
    name: str
    label: str
    type: Literal["integer", "number", "ticker"]
    default: Optional[float | int | str] = None
    min: Optional[float] = None
    max: Optional[float] = None
    min_exclusive: bool = False
    max_exclusive: bool = False


class StrategyOptionResponse(BaseModel):
    value: str
    label: str
    params: List[StrategyParamSpec]
