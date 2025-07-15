from app.api.database.database import Base
from sqlalchemy import Column, Integer, String, TIMESTAMP, Boolean, text
from sqlalchemy.ext.declarative import declarative_base

StockBase = declarative_base()
metadata = StockBase.metadata


class Stocks(Base):
    __tablename__ = "stocks"

    stock_id = Column(Integer,primary_key=True,nullable=False)
    company_name = Column(String,nullable=False)
    ticker = Column(String,nullable=False)
    exchange = Column(String,nullable=False)
    asset_type = Column(String,nullable=False)

