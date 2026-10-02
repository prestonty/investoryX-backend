from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrategyParams(BaseModel):
    """Base for per-strategy tunables; defaults here are each strategy's defaults."""

    model_config = ConfigDict(extra="forbid")

    def history_bars(self) -> int:
        """Daily bars a strategy needs to make a decision with these params."""
        raise NotImplementedError


class SmaCrossoverParams(StrategyParams):
    short_window: int = Field(5, ge=1, le=200, title="Short SMA (days)")
    long_window: int = Field(20, ge=2, le=400, title="Long SMA (days)")
    trade_quantity: Decimal = Field(Decimal("1"), gt=0, le=100000, title="Shares per trade")

    @model_validator(mode="after")
    def _short_below_long(self) -> SmaCrossoverParams:
        if self.short_window >= self.long_window:
            raise ValueError("short_window must be smaller than long_window")
        return self

    def history_bars(self) -> int:
        # Crossover compares today's SMAs with yesterday's.
        return self.long_window + 1


class Sma50x200Params(StrategyParams):
    trade_quantity: Decimal = Field(Decimal("1"), gt=0, le=100000, title="Shares per trade")

    def history_bars(self) -> int:
        return 201


class PairsTradingParams(StrategyParams):
    symbol_a: str | None = Field(None, max_length=10, title="Traded stock (A)")
    symbol_b: str | None = Field(None, max_length=10, title="Reference stock (B)")
    window: int = Field(20, ge=2, le=250, title="Z-score window (days)")
    entry_threshold: Decimal = Field(Decimal("2.0"), gt=0, le=10, title="Entry Z-score")
    trade_quantity: Decimal = Field(Decimal("10"), gt=0, le=100000, title="Shares per trade")

    @field_validator("symbol_a", "symbol_b")
    @classmethod
    def _normalize_symbol(cls, value: str | None) -> str | None:
        value = (value or "").strip().upper()
        return value or None

    def history_bars(self) -> int:
        return self.window


class AuctionLiquidityParams(StrategyParams):
    deviation_threshold: Decimal = Field(
        Decimal("0.02"), gt=0, lt=1, title="Deviation threshold (fraction)"
    )
    trade_size: Decimal = Field(Decimal("50"), gt=0, le=100000, title="Shares per trade")

    def history_bars(self) -> int:
        # Fair value is the 5-day average close.
        return 5
