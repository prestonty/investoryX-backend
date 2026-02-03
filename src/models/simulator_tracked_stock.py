from src.api.database.database import Base
from sqlalchemy import (
    Boolean,
    Column,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    Index,
)
from sqlalchemy.orm import relationship

class SimulatorTrackedStock(Base):
    # SimulatorTrackedStock defines which tickers a simulator watches and their target allocation.
    __tablename__ = "simulator_tracked_stocks"
    __table_args__ = (
        UniqueConstraint(
            "simulator_id",
            "ticker",
            name="uq_simulator_tracked_stock_ticker",
        ),
        Index("ix_simulator_tracked_stock_simulator_id", "simulator_id"),
    )

    tracked_id = Column(Integer, primary_key=True, nullable=False)
    simulator_id = Column(
        Integer,
        ForeignKey("simulators.simulator_id", ondelete="CASCADE"),
        nullable=False,
    )
    ticker = Column(String, nullable=False)
    target_allocation = Column(Numeric(5, 2), nullable=False)
    enabled = Column(Boolean, server_default="TRUE")

    simulator = relationship("Simulator", back_populates="tracked_stocks")
