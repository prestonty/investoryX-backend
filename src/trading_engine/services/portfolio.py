from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Protocol
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.models.simulator import Simulator
from src.models.simulator_position import SimulatorPosition
from src.models.simulator_trade import SimulatorTrade

from .actions import SignalAction


@dataclass(frozen=True)
class Position:
    """Holding for a single symbol in a portfolio."""
    symbol: str
    quantity: Decimal
    average_cost: Decimal


@dataclass(frozen=True)
class PortfolioSnapshot:
    """Point-in-time view of a portfolio."""
    user_id: int
    cash: Decimal
    positions: dict[str, Position]
    as_of: datetime
    simulator_id: int | None = None


@dataclass(frozen=True)
class ExecutedTrade:
    """Ledger trade used to rebuild canonical portfolio state."""
    trade_id: int
    simulator_id: int
    symbol: str
    side: SignalAction
    quantity: Decimal
    price: Decimal
    fee: Decimal
    executed_at: datetime


@dataclass(frozen=True)
class PortfolioReconciliationResult:
    simulator_id: int
    trades_processed: int
    starting_cash: Decimal
    reconciled_cash: Decimal
    cash_drift: Decimal
    position_drift_count: int

    def to_dict(self) -> dict:
        return {
            "simulator_id": self.simulator_id,
            "trades_processed": self.trades_processed,
            "starting_cash": str(self.starting_cash),
            "reconciled_cash": str(self.reconciled_cash),
            "cash_drift": str(self.cash_drift),
            "position_drift_count": self.position_drift_count,
        }


class PortfolioRepository(Protocol):
    """Persistence boundary for loading and storing simulator portfolio state."""

    def get_snapshot(self, session: Session, simulator_id: int) -> PortfolioSnapshot:
        raise NotImplementedError

    def get_starting_cash(self, session: Session, simulator_id: int) -> Decimal:
        raise NotImplementedError

    def list_simulator_ids(
        self,
        session: Session,
        limit: int | None = None,
    ) -> list[int]:
        raise NotImplementedError

    def list_executed_trades(
        self,
        session: Session,
        simulator_id: int,
    ) -> list[ExecutedTrade]:
        raise NotImplementedError

    def save_reconciled_state(
        self,
        session: Session,
        simulator_id: int,
        cash: Decimal,
        positions: dict[str, Position],
    ) -> None:
        raise NotImplementedError


class SqlPortfolioRepository:
    """SQLAlchemy repository for simulator portfolio state."""

    def get_snapshot(self, session: Session, simulator_id: int) -> PortfolioSnapshot:
        simulator = self._load_simulator(session=session, simulator_id=simulator_id)
        if simulator.user_id is None:
            raise ValueError(
                f"Simulator {simulator_id} is not associated with a user_id"
            )
        positions = self._load_positions(session=session, simulator_id=simulator_id)

        as_of = simulator.updated_at or datetime.now(timezone.utc)
        return PortfolioSnapshot(
            user_id=int(simulator.user_id),
            cash=Decimal(str(simulator.cash_balance)),
            positions=positions,
            as_of=as_of,
            simulator_id=simulator_id,
        )

    def get_starting_cash(self, session: Session, simulator_id: int) -> Decimal:
        simulator = self._load_simulator(session=session, simulator_id=simulator_id)
        return Decimal(str(simulator.starting_cash))

    def list_simulator_ids(
        self,
        session: Session,
        limit: int | None = None,
    ) -> list[int]:
        stmt = select(Simulator.simulator_id).order_by(Simulator.simulator_id)
        if limit is not None:
            stmt = stmt.limit(limit)
        return [int(simulator_id) for simulator_id in session.execute(stmt).scalars().all()]

    def list_executed_trades(
        self,
        session: Session,
        simulator_id: int,
    ) -> list[ExecutedTrade]:
        stmt = (
            select(SimulatorTrade)
            .where(SimulatorTrade.simulator_id == simulator_id)
            .order_by(SimulatorTrade.executed_at, SimulatorTrade.trade_id)
        )
        rows = session.execute(stmt).scalars().all()
        now = datetime.now(timezone.utc)

        trades: list[ExecutedTrade] = []
        for row in rows:
            symbol = (row.ticker or "").strip().upper()
            if not symbol:
                continue
            trades.append(
                ExecutedTrade(
                    trade_id=int(row.trade_id),
                    simulator_id=int(row.simulator_id),
                    symbol=symbol,
                    side=SignalAction(str(row.side).strip().lower()),
                    quantity=Decimal(str(row.shares)),
                    price=Decimal(str(row.price)),
                    fee=Decimal(str(row.fee)),
                    executed_at=row.executed_at or now,
                )
            )
        return trades

    def save_reconciled_state(
        self,
        session: Session,
        simulator_id: int,
        cash: Decimal,
        positions: dict[str, Position],
    ) -> None:
        simulator = self._load_simulator(session=session, simulator_id=simulator_id)
        simulator.cash_balance = cash
        simulator.updated_at = datetime.now(timezone.utc)

        stmt = select(SimulatorPosition).where(
            SimulatorPosition.simulator_id == simulator_id
        )
        existing_rows = session.execute(stmt).scalars().all()
        existing_by_symbol = {
            row.ticker.strip().upper(): row
            for row in existing_rows
            if row.ticker and row.ticker.strip()
        }

        for symbol, position in positions.items():
            row = existing_by_symbol.pop(symbol, None)
            if row is None:
                session.add(
                    SimulatorPosition(
                        simulator_id=simulator_id,
                        ticker=symbol,
                        shares=position.quantity,
                        avg_cost=position.average_cost,
                    )
                )
                continue
            row.shares = position.quantity
            row.avg_cost = position.average_cost

        for row in existing_by_symbol.values():
            session.delete(row)

    def _load_simulator(self, session: Session, simulator_id: int) -> Simulator:
        stmt = select(Simulator).where(Simulator.simulator_id == simulator_id)
        simulator = session.execute(stmt).scalars().first()
        if simulator is None:
            raise ValueError(f"Simulator not found for simulator_id={simulator_id}")
        return simulator

    def _load_positions(
        self,
        session: Session,
        simulator_id: int,
    ) -> dict[str, Position]:
        stmt = select(SimulatorPosition).where(
            SimulatorPosition.simulator_id == simulator_id
        )
        rows = session.execute(stmt).scalars().all()

        positions: dict[str, Position] = {}
        for row in rows:
            symbol = (row.ticker or "").strip().upper()
            if not symbol:
                continue
            positions[symbol] = Position(
                symbol=symbol,
                quantity=Decimal(str(row.shares)),
                average_cost=Decimal(str(row.avg_cost)),
            )
        return positions


class PortfolioService:
    """Business logic for loading and reconciling simulator portfolios."""

    def __init__(self, repo: PortfolioRepository | None = None) -> None:
        self._repo = repo or SqlPortfolioRepository()

    def load_portfolio(self, session: Session, simulator_id: int) -> PortfolioSnapshot:
        return self._repo.get_snapshot(session=session, simulator_id=simulator_id)

    def reconcile_simulator(
        self,
        session: Session,
        simulator_id: int,
    ) -> PortfolioReconciliationResult:
        current_snapshot = self._repo.get_snapshot(session=session, simulator_id=simulator_id)
        starting_cash = self._repo.get_starting_cash(
            session=session,
            simulator_id=simulator_id,
        )
        trades = self._repo.list_executed_trades(session=session, simulator_id=simulator_id)
        reconciled_cash, reconciled_positions = self._replay_trades(
            starting_cash=starting_cash,
            trades=trades,
        )

        self._repo.save_reconciled_state(
            session=session,
            simulator_id=simulator_id,
            cash=reconciled_cash,
            positions=reconciled_positions,
        )

        return PortfolioReconciliationResult(
            simulator_id=simulator_id,
            trades_processed=len(trades),
            starting_cash=starting_cash,
            reconciled_cash=reconciled_cash,
            cash_drift=current_snapshot.cash - reconciled_cash,
            position_drift_count=self._count_position_drift(
                stored=current_snapshot.positions,
                reconciled=reconciled_positions,
            ),
        )

    def reconcile_all(
        self,
        session: Session,
        simulator_ids: list[int] | None = None,
        limit: int | None = None,
    ) -> list[PortfolioReconciliationResult]:
        if simulator_ids is None:
            simulator_ids = self._repo.list_simulator_ids(session=session, limit=limit)
        return [
            self.reconcile_simulator(session=session, simulator_id=simulator_id)
            for simulator_id in simulator_ids
        ]

    def _replay_trades(
        self,
        starting_cash: Decimal,
        trades: list[ExecutedTrade],
    ) -> tuple[Decimal, dict[str, Position]]:
        cash = starting_cash
        positions: dict[str, Position] = {}

        for trade in trades:
            self._validate_trade(trade)
            current = positions.get(
                trade.symbol,
                Position(symbol=trade.symbol, quantity=Decimal("0"), average_cost=Decimal("0")),
            )

            if trade.side is SignalAction.BUY:
                cash -= trade.price * trade.quantity + trade.fee
                next_quantity = current.quantity + trade.quantity
                gross_cost = (
                    current.quantity * current.average_cost
                    + trade.price * trade.quantity
                    + trade.fee
                )
                next_average_cost = gross_cost / next_quantity
                positions[trade.symbol] = Position(
                    symbol=trade.symbol,
                    quantity=next_quantity,
                    average_cost=next_average_cost,
                )
                continue

            if trade.quantity > current.quantity:
                raise ValueError(
                    f"trade_id={trade.trade_id} sells {trade.quantity} but holds "
                    f"only {current.quantity} for symbol={trade.symbol}"
                )

            cash += trade.price * trade.quantity - trade.fee
            remaining_quantity = current.quantity - trade.quantity
            if remaining_quantity == 0:
                positions.pop(trade.symbol, None)
                continue

            positions[trade.symbol] = Position(
                symbol=trade.symbol,
                quantity=remaining_quantity,
                average_cost=current.average_cost,
            )

        return cash, positions

    def _validate_trade(self, trade: ExecutedTrade) -> None:
        if trade.side not in {SignalAction.BUY, SignalAction.SELL}:
            raise ValueError(
                f"trade_id={trade.trade_id} has unsupported side={trade.side.value}"
            )
        if trade.quantity <= 0:
            raise ValueError(f"trade_id={trade.trade_id} has non-positive quantity")
        if trade.price <= 0:
            raise ValueError(f"trade_id={trade.trade_id} has non-positive price")
        if trade.fee < 0:
            raise ValueError(f"trade_id={trade.trade_id} has negative fee")

    def _count_position_drift(
        self,
        stored: dict[str, Position],
        reconciled: dict[str, Position],
    ) -> int:
        symbols = set(stored.keys()) | set(reconciled.keys())
        drift = 0
        for symbol in symbols:
            stored_position = stored.get(symbol)
            reconciled_position = reconciled.get(symbol)
            if stored_position is None or reconciled_position is None:
                drift += 1
                continue
            if stored_position.quantity != reconciled_position.quantity:
                drift += 1
                continue
            if stored_position.average_cost != reconciled_position.average_cost:
                drift += 1
        return drift
