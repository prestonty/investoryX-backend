from __future__ import annotations

import os

# Prevent import-time failure in src.api.database.database during test discovery.
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
# Rate limits would make repeated API calls in a test flaky.
os.environ.setdefault("RATE_LIMIT_ENABLED", "false")

import importlib
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.core.database import Base
from src.models.price_bar import PriceBar
from src.models.simulator import Simulator
from src.models.simulator_cash_ledger import SimulatorCashLedger
from src.models.simulator_position import SimulatorPosition
from src.models.simulator_signal import SimulatorSignal
from src.models.simulator_trade import SimulatorTrade
from src.models.simulator_tracked_stock import SimulatorTrackedStock
from src.models.stocks import Stocks
from src.models.user_session import UserSession
from src.models.users import Users

_TABLES = [
    Users.__table__,
    Simulator.__table__,
    SimulatorTrackedStock.__table__,
    SimulatorSignal.__table__,
    SimulatorTrade.__table__,
    SimulatorCashLedger.__table__,
    SimulatorPosition.__table__,
    PriceBar.__table__,
    UserSession.__table__,
    Stocks.__table__,
]


@pytest.fixture
def session_factory():
    """In-memory SQLite database with the trading tables, shared across sessions."""
    engine = create_engine(
        "sqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def _on_connect(dbapi_connection, _record):
        # Models use Postgres' now() as a server default.
        dbapi_connection.create_function(
            "now", 0, lambda: datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")
        )
        # Let SQLAlchemy manage transactions so SAVEPOINTs work (pysqlite recipe).
        dbapi_connection.isolation_level = None

    @event.listens_for(engine, "begin")
    def _on_begin(connection):
        connection.exec_driver_sql("BEGIN")

    Base.metadata.create_all(engine, tables=_TABLES)
    yield sessionmaker(bind=engine, expire_on_commit=False)
    engine.dispose()


# Engine modules that open their own sessions via `SessionLocal()`.
_SESSION_MODULES = [
    "src.trading_engine.services.evaluation",
    "src.trading_engine.services.backtest",
    "src.trading_engine.services.pricing",
    "src.trading_engine.tasks.execute_paper_trades",
    "src.trading_engine.tasks.reconcile_portfolios",
]


class TradingDb:
    """Seeding and lookup helpers over the SQLite test database."""

    def __init__(self, factory) -> None:
        self.session = factory

    def add(self, *rows):
        with self.session() as session:
            session.add_all(rows)
            session.commit()
        return rows

    def all(self, model, **filters):
        with self.session() as session:
            return session.query(model).filter_by(**filters).all()

    def get(self, model, key):
        with self.session() as session:
            return session.get(model, key)

    def simulator(
        self,
        simulator_id: int,
        user_id: int | None = 1,
        cash: str = "1000",
        status: str = "Active Trading",
        strategy_name: str = "sma_crossover",
        tickers: tuple[str, ...] = ("AAPL",),
        strategy_params: dict | None = None,
    ) -> None:
        if user_id is not None and self.get(Users, user_id) is None:
            self.add(Users(user_id=user_id, name="u", email="u@x", password="p", is_active=True))
        self.add(
            Simulator(
                simulator_id=simulator_id,
                user_id=user_id,
                name=f"sim {simulator_id}",
                starting_cash=Decimal(cash),
                cash_balance=Decimal(cash),
                status=status,
                strategy_name=strategy_name,
                strategy_params=strategy_params,
            )
        )
        self.add(
            *[
                SimulatorTrackedStock(
                    simulator_id=simulator_id,
                    ticker=ticker,
                    target_allocation=Decimal("10"),
                    enabled=True,
                )
                for ticker in tickers
            ]
        )

    def bars(self, symbol: str, days: list[date], close: str = "100") -> None:
        self.add(
            *[
                PriceBar(
                    symbol=symbol,
                    day=day,
                    open=Decimal(close),
                    high=Decimal(close),
                    low=Decimal(close),
                    close=Decimal(close),
                    volume=1000,
                    source="yfinance",
                )
                for day in days
            ]
        )


@pytest.fixture
def db(session_factory, monkeypatch: pytest.MonkeyPatch) -> TradingDb:
    for module_path in _SESSION_MODULES:
        module = importlib.import_module(module_path)
        monkeypatch.setattr(module, "SessionLocal", session_factory)
    return TradingDb(session_factory)
