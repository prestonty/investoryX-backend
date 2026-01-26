from src.api.database.database import Base
from sqlalchemy import Column, ForeignKey, Integer, Numeric, String, TIMESTAMP, text, Index


class SimulatorTrade(Base):
    # SimulatorTrade is an immutable log of buy/sell actions executed by a simulator.
    __tablename__ = "simulator_trades"
    __table_args__ = (Index("ix_simulator_trade_simulator_id", "simulator_id"),)

    trade_id = Column(Integer, primary_key=True, nullable=False)
    simulator_id = Column(
        Integer,
        ForeignKey("simulators.simulator_id", ondelete="CASCADE"),
        nullable=False,
    )
    ticker = Column(String, nullable=False)
    side = Column(String, nullable=False)  # "buy" or "sell"
    price = Column(Numeric(12, 4), nullable=False)
    shares = Column(Numeric(14, 6), nullable=False)
    fee = Column(Numeric(10, 2), nullable=False, server_default="0")
    executed_at = Column(TIMESTAMP(timezone=True), server_default=text("now()"))
