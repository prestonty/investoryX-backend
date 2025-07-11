from database import Base
from sqlalchemy import Column, Integer, String, TIMESTAMP, Boolean, text


class WatchItems(Base):
    __tablename__ = "watch_items"

    watchlist_id = Column(Integer,primary_key=True,nullable=False)
    stock_id = Column(String,nullable=False)
    user_id = Column(String,nullable=False)
