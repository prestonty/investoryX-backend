from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from pydantic import BaseModel
from datetime import datetime

from app.api.database.database import get_db
from app.models.users import Users

router = APIRouter(prefix="/api/users", tags=["users"])

class UserCreate(BaseModel):
    Name: str
    email: str
    password: str

class UserResponse(BaseModel):
    UserId: int
    Name: str
    email: str
    timestamp: datetime
    is_active: bool

    class Config:
        from_attributes = True

@router.get("/", response_model=List[UserResponse])
def get_users(db: Session = Depends(get_db)):
    users = db.query(Users).all()
    return users

@router.get("/{user_id}", response_model=UserResponse)
def get_user(user_id: int, db: Session = Depends(get_db)):
    user = db.query(Users).filter(Users.UserId == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user

@router.post("/", response_model=UserResponse)
def create_user(user: UserCreate, db: Session = Depends(get_db)):
    db_user = Users(**user.dict())
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user