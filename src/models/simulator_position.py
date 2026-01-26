from src.api.database.database import Base
from sqlalchemy import (
    Column,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    Index,
)


class SimulatorPosition(Base):
    __tablename__ = "simulator_positions"
    __table_args__ = (
        UniqueConstraint(
            "simulator_id",
            "ticker",
            name="uq_simulator_position_ticker",
        ),
        Index("ix_simulator_position_simulator_id", "simulator_id"),
    )

    position_id = Column(Integer, primary_key=True, nullable=False)
    simulator_id = Column(
        Integer,
        ForeignKey("simulators.simulator_id", ondelete="CASCADE"),
        nullable=False,
    )
    ticker = Column(String, nullable=False)
    shares = Column(Numeric(14, 6), nullable=False)
    avg_cost = Column(Numeric(12, 4), nullable=False)
