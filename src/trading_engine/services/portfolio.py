from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .execution import Trade


@dataclass(frozen=True)
class Position:
    """Holding for a single symbol in a portfolio."""
    symbol: str
    quantity: float
    average_cost: float


@dataclass(frozen=True)
class PortfolioSnapshot:
    """Point-in-time view of a portfolio."""
    user_id: int
    cash: float
    positions: dict[str, Position]
    as_of: datetime


class PortfolioRepository(Protocol):
    """Persistence interface for portfolios and snapshots."""
    def get_snapshot(self, user_id: int) -> PortfolioSnapshot:
        raise NotImplementedError

    def apply_trades(self, user_id: int, trades: list["Trade"]) -> PortfolioSnapshot:
        raise NotImplementedError

    def record_snapshot(self, snapshot: PortfolioSnapshot) -> None:
        raise NotImplementedError


class PortfolioService:
    """Loads portfolios and records portfolio changes."""
    def __init__(self, repo: PortfolioRepository) -> None:
        self._repo = repo

    def load_portfolio(self, user_id: int) -> PortfolioSnapshot:
        return self._repo.get_snapshot(user_id)

    def apply_trades(self, user_id: int, trades: list["Trade"]) -> PortfolioSnapshot:
        return self._repo.apply_trades(user_id, trades)

    def snapshot(self, snapshot: PortfolioSnapshot) -> None:
        self._repo.record_snapshot(snapshot)
