from src.api.database.database import Base
from sqlalchemy import Column, Integer, ForeignKey, UniqueConstraint, Index


class Watchlist(Base):
    __tablename__ = "watchlist"
    __table_args__ = (
        UniqueConstraint("user_id", "stock_id", name="uq_watchlist_user_stock"),
        Index("ix_watchlist_user_id", "user_id"),
        Index("ix_watchlist_stock_id", "stock_id"),
    )

    watchlist_id = Column(Integer, primary_key=True, nullable=False)
    stock_id = Column(Integer, ForeignKey("stocks.stock_id", ondelete="CASCADE"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False)
