from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import annotated_types
from pydantic import ValidationError

from src.trading_engine.services.strategy import (
    AuctionLiquidityStrategy,
    PairsTradingStrategy,
    Strategy,
    StrategyRegistry,
)

from .manual import ManualStrategy
from .moving_averages import SimpleMovingAverageStrategy, Sma50x200CrossoverStrategy
from .params import (
    AuctionLiquidityParams,
    ManualParams,
    PairsTradingParams,
    Sma50x200Params,
    SmaCrossoverParams,
    StrategyParams,
)

DEFAULT_STRATEGY_NAME = SimpleMovingAverageStrategy.name
# Simulators on this "strategy" are traded by hand and never evaluated.
MANUAL_STRATEGY_NAME = ManualStrategy.name


@dataclass(frozen=True)
class StrategyEntry:
    strategy: Strategy
    label: str
    params_model: type[StrategyParams]

    @property
    def name(self) -> str:
        return self.strategy.name


# Single source of truth for which strategies exist: the engine registry, the
# API's accepted strategy names and the settings form all come from here.
CATALOG: dict[str, StrategyEntry] = {
    entry.name: entry
    for entry in (
        StrategyEntry(SimpleMovingAverageStrategy(), "SMA Crossover", SmaCrossoverParams),
        StrategyEntry(
            Sma50x200CrossoverStrategy(), "SMA 50/200 (Golden Cross)", Sma50x200Params
        ),
        StrategyEntry(PairsTradingStrategy(), "Pairs Trading (Stat Arb)", PairsTradingParams),
        StrategyEntry(
            AuctionLiquidityStrategy(), "Auction Liquidity Provider", AuctionLiquidityParams
        ),
        StrategyEntry(ManualStrategy(), "Manual trading", ManualParams),
    )
}


class InvalidStrategyParams(ValueError):
    """Stored or submitted params don't fit the strategy's params model."""


def get_entry(strategy_name: str) -> StrategyEntry:
    try:
        return CATALOG[strategy_name]
    except KeyError:
        raise InvalidStrategyParams(f"Unknown strategy: {strategy_name}") from None


def build_registry() -> StrategyRegistry:
    registry = StrategyRegistry()
    for entry in CATALOG.values():
        registry.register(entry.strategy)
    return registry


def validate_params(strategy_name: str, params: dict | None) -> StrategyParams:
    """Validate params for a strategy, filling in defaults for anything unset."""
    model = get_entry(strategy_name).params_model
    try:
        return model.model_validate(params or {})
    except ValidationError as exc:
        raise InvalidStrategyParams(_format_errors(exc)) from exc


def effective_params(strategy_name: str, params: dict | None) -> dict[str, Any]:
    """Validated params with defaults, as plain JSON-safe values (numbers stay numbers)."""
    validated = validate_params(strategy_name, params)
    return {key: _json_value(value) for key, value in validated.model_dump().items()}


def params_to_store(strategy_name: str, params: dict | None) -> dict[str, Any] | None:
    """Validate params and keep only the keys that were given, so defaults can evolve."""
    validated = validate_params(strategy_name, params)
    given = validated.model_dump(exclude_unset=True)
    return {key: _json_value(value) for key, value in given.items()} or None


def history_bars(strategy_name: str, params: dict | None) -> int:
    """Bars of history the strategy needs; keys it doesn't know (run options) are ignored."""
    fields = get_entry(strategy_name).params_model.model_fields
    known = {key: value for key, value in (params or {}).items() if key in fields}
    return validate_params(strategy_name, known).history_bars()


def describe_strategies() -> list[dict]:
    """Strategy options plus a form description of each one's params."""
    return [
        {
            "value": entry.name,
            "label": entry.label,
            "params": [
                _describe_field(name, field)
                for name, field in entry.params_model.model_fields.items()
            ],
        }
        for entry in CATALOG.values()
    ]


def _describe_field(name: str, field) -> dict:
    annotation = field.annotation
    if annotation is int:
        kind = "integer"
    elif annotation is Decimal:
        kind = "number"
    else:
        kind = "ticker"

    spec: dict[str, Any] = {
        "name": name,
        "label": field.title or name,
        "type": kind,
        "default": _json_value(field.default),
    }
    for constraint in field.metadata:
        if isinstance(constraint, annotated_types.Ge):
            spec["min"] = _json_value(constraint.ge)
        elif isinstance(constraint, annotated_types.Gt):
            spec["min"] = _json_value(constraint.gt)
            spec["min_exclusive"] = True
        elif isinstance(constraint, annotated_types.Le):
            spec["max"] = _json_value(constraint.le)
        elif isinstance(constraint, annotated_types.Lt):
            spec["max"] = _json_value(constraint.lt)
            spec["max_exclusive"] = True
    return spec


def _json_value(value: Any) -> Any:
    return float(value) if isinstance(value, Decimal) else value


def _format_errors(exc: ValidationError) -> str:
    messages = []
    for error in exc.errors():
        location = ".".join(str(part) for part in error["loc"])
        message = error["msg"].removeprefix("Value error, ")
        messages.append(f"{location}: {message}" if location else message)
    return "; ".join(messages)
