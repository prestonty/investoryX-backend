from src.api.database.database import Base
from sqlalchemy import Column, Integer, String, TIMESTAMP, Boolean, text


class Users(Base):
    __tablename__ = "users"

    user_id = Column(Integer, primary_key=True, nullable=False)
    name = Column(String, nullable=False)
    email = Column(String,nullable=False)
    password = Column(String, nullable=False)
    timestamp = Column(TIMESTAMP(timezone=True), server_default=text('now()'))
    is_active = Column(Boolean, server_default='FALSE')
