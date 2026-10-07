from src.core.database import Base
from sqlalchemy import (
    Column,
    Date,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    TIMESTAMP,
    text,
)


class SimulatorOrder(Base):
    # A manual market order placed while the market was closed. It waits here and
    # fills at fill_day's opening price; orders placed during market hours fill
    # immediately and only appear as trades.
    __tablename__ = "simulator_orders"
    __table_args__ = (
        Index("ix_simulator_order_simulator_id", "simulator_id"),
        Index("ix_simulator_order_status_fill_day", "status", "fill_day"),
    )

    order_id = Column(Integer, primary_key=True, nullable=False)
    simulator_id = Column(
        Integer,
        ForeignKey("simulators.simulator_id", ondelete="CASCADE"),
        nullable=False,
    )
    ticker = Column(String, nullable=False)
    side = Column(String, nullable=False)  # buy | sell
    shares = Column(Numeric(14, 6), nullable=False)
    # Last price when the order was placed; reserves cash for pending buys.
    quote_price = Column(Numeric(12, 4), nullable=False)
    # Trading day whose opening price fills the order.
    fill_day = Column(Date, nullable=False)
    status = Column(String, nullable=False, server_default="pending")  # pending | filled | rejected | cancelled
    error = Column(String, nullable=True)
    trade_id = Column(
        Integer,
        ForeignKey("simulator_trades.trade_id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at = Column(TIMESTAMP(timezone=True), server_default=text("now()"))
    closed_at = Column(TIMESTAMP(timezone=True), nullable=True)
