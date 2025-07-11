from database import Base
from sqlalchemy import Column, Integer, String, TIMESTAMP, Boolean, text


class Stocks(Base):
    __tablename__ = "stocks"

    stock_id = Column(Integer,primary_key=True,nullable=False)
    company_name = Column(String,nullable=False)
    ticker = Column(String,nullable=False)
