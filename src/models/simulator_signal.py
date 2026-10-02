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
    UniqueConstraint,
    text,
)


class SimulatorSignal(Base):
    # Strategy decision output persisted for later paper-trade execution.
    __tablename__ = "simulator_signals"
    __table_args__ = (
        Index("ix_simulator_signal_simulator_id", "simulator_id"),
        Index("ix_simulator_signal_status_created_at", "status", "created_at"),
        # One evaluation per simulator per trading day; rows from before
        # for_day existed are NULL and not constrained.
        UniqueConstraint(
            "simulator_id", "for_day", "ticker", name="uq_simulator_signal_day_ticker"
        ),
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
    # Trading day whose prices produced this signal; it may only fill on that day.
    for_day = Column(Date, nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=text("now()"))
    executed_at = Column(TIMESTAMP(timezone=True), nullable=True)
    execution_error = Column(String, nullable=True)
