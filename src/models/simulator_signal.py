from src.api.database.database import Base
from sqlalchemy import (
    Column,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    TIMESTAMP,
    text,
)


class SimulatorSignal(Base):
    # Strategy decision output persisted for later paper-trade execution.
    __tablename__ = "simulator_signals"
    __table_args__ = (
        Index("ix_simulator_signal_simulator_id", "simulator_id"),
        Index("ix_simulator_signal_status_created_at", "status", "created_at"),
    )

    signal_id = Column(Integer, primary_key=True, nullable=False)
    simulator_id = Column(
        Integer,
        ForeignKey("simulators.simulator_id", ondelete="CASCADE"),
        nullable=False,
    )
    ticker = Column(String, nullable=False)
    action = Column(String, nullable=False)  # buy | sell | hold
    quantity = Column(Numeric(14, 6), nullable=False)
    reason = Column(String, nullable=False)
    confidence = Column(Numeric(5, 4), nullable=False)
    strategy_name = Column(String, nullable=False)
    status = Column(String, nullable=False, server_default="pending")
    created_at = Column(TIMESTAMP(timezone=True), server_default=text("now()"))
    executed_at = Column(TIMESTAMP(timezone=True), nullable=True)
    execution_error = Column(String, nullable=True)
