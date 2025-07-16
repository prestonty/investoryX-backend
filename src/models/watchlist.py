from src.api.database.database import Base
from sqlalchemy import Column, Integer, String, TIMESTAMP, Boolean, text


class Watchlist(Base):
    __tablename__ = "watchlist"

    watchlist_id = Column(Integer,primary_key=True,nullable=False)
    stock_id = Column(Integer,nullable=False)
    user_id = Column(Integer,nullable=False)
