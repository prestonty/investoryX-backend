from src.api.database.database import Base
from sqlalchemy import Column, ForeignKey, Integer, String, TIMESTAMP, Numeric, text, Index, Enum
from sqlalchemy.orm import relationship

SIMULATOR_STATUS_ACTIVE = "Active Trading"
SIMULATOR_STATUS_PAUSED = "Pause Trading"
SIMULATOR_STATUS_VALUES = (
    SIMULATOR_STATUS_ACTIVE,
    SIMULATOR_STATUS_PAUSED,
)

simulator_status_enum = Enum(
    *SIMULATOR_STATUS_VALUES,
    name="simulator_status",
    native_enum=False,
)

SIMULATOR_FREQUENCY_DAILY = "daily"
SIMULATOR_FREQUENCY_TWICE_DAILY = "twice_daily"
SIMULATOR_FREQUENCY_VALUES = (
    SIMULATOR_FREQUENCY_DAILY,
    SIMULATOR_FREQUENCY_TWICE_DAILY,
)

simulator_frequency_enum = Enum(
    *SIMULATOR_FREQUENCY_VALUES,
    name="simulator_frequency",
    native_enum=False,
)

SIMULATOR_PRICE_MODE_OPEN = "open"
SIMULATOR_PRICE_MODE_CLOSE = "close"
SIMULATOR_PRICE_MODE_VALUES = (
    SIMULATOR_PRICE_MODE_OPEN,
    SIMULATOR_PRICE_MODE_CLOSE,
)

simulator_price_mode_enum = Enum(
    *SIMULATOR_PRICE_MODE_VALUES,
    name="simulator_price_mode",
    native_enum=False,
)


class Simulator(Base):
    # Simulator represents a single paper-trading bot configuration and its cash state.
    __tablename__ = "simulators"
    __table_args__ = (Index("ix_simulators_user_id", "user_id"),)

    simulator_id = Column(Integer, primary_key=True, nullable=False)
    user_id = Column(Integer, ForeignKey("users.user_id", ondelete="CASCADE"), nullable=True)
    name = Column(String, nullable=False)
    starting_cash = Column(Numeric(12, 2), nullable=False)
    cash_balance = Column(Numeric(12, 2), nullable=False)
    status = Column(
        simulator_status_enum,
        nullable=False,
        server_default=text(f"'{SIMULATOR_STATUS_ACTIVE}'"),
    )
    last_run_at = Column(TIMESTAMP(timezone=True), nullable=True)
    next_run_at = Column(TIMESTAMP(timezone=True), nullable=True)
    frequency = Column(
        simulator_frequency_enum,
        nullable=False,
        server_default=text(f"'{SIMULATOR_FREQUENCY_DAILY}'"),
    )
    price_mode = Column(
        simulator_price_mode_enum,
        nullable=False,
        server_default=text(f"'{SIMULATOR_PRICE_MODE_CLOSE}'"),
    )
    max_position_pct = Column(Numeric(5, 2), nullable=True)
    max_daily_loss_pct = Column(Numeric(5, 2), nullable=True)
    stopped_reason = Column(String, nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=text("now()"))
    updated_at = Column(TIMESTAMP(timezone=True), server_default=text("now()"))

    tracked_stocks = relationship(
        "SimulatorTrackedStock",
        
    )
