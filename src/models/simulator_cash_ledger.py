from src.api.database.database import Base
from sqlalchemy import Column, ForeignKey, Integer, Numeric, String, TIMESTAMP, text, Index


class SimulatorCashLedger(Base):
    __tablename__ = "simulator_cash_ledger"
    __table_args__ = (Index("ix_simulator_cash_ledger_simulator_id", "simulator_id"),)

    ledger_id = Column(Integer, primary_key=True, nullable=False)
    simulator_id = Column(
        Integer,
        ForeignKey("simulators.simulator_id", ondelete="CASCADE"),
        nullable=False,
    )
    delta = Column(Numeric(12, 2), nullable=False)
    reason = Column(String, nullable=False)
    balance_after = Column(Numeric(12, 2), nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), server_default=text("now()"))
