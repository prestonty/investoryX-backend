from src.api.database.database import Base
from sqlalchemy import Column, Date, Integer, Numeric, String, UniqueConstraint, Index


class PriceBar(Base):
    # Daily OHLCV bar for a given symbol and date.
    __tablename__ = "price_bars"
    __table_args__ = (
        UniqueConstraint("symbol", "day", "source", name="uq_price_bar_symbol_day_source"),
        Index("ix_price_bar_symbol_day", "symbol", "day"),
    )

    bar_id = Column(Integer, primary_key=True, nullable=False)
    symbol = Column(String, nullable=False)
    day = Column(Date, nullable=False)
    open = Column(Numeric(12, 4), nullable=False)
    high = Column(Numeric(12, 4), nullable=False)
    low = Column(Numeric(12, 4), nullable=False)
    close = Column(Numeric(12, 4), nullable=False)
    volume = Column(Integer, nullable=False)
    source = Column(String, nullable=False, default="yfinance")
