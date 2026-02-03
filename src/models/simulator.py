from src.api.database.database import Base
from sqlalchemy import Column, ForeignKey, Integer, String, TIMESTAMP, Numeric, text, Index
from sqlalchemy.orm import relationship

class Simulator(Base):
    # Simulator represents a single paper-trading bot configuration and its cash state.
    __tablename__ = "simulators"
    __table_args__ = (Index("ix_simulators_user_id", "user_id"),)

    simulator_id = Column(Integer, primary_key=True, nullable=False)
    user_id = Column(Integer, ForeignKey("users.user_id", ondelete="CASCADE"), nullable=True)
    name = Column(String, nullable=False)
    starting_cash = Column(Numeric(12, 2), nullable=False)
    cash_balance = Column(Numeric(12, 2), nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), server_default=text("now()"))
    updated_at = Column(TIMESTAMP(timezone=True), server_default=text("now()"))

    tracked_stocks = relationship(
        "SimulatorTrackedStock",
        
    )
