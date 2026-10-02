from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from pydantic import BaseModel, ConfigDict, Field
from datetime import datetime

from src.core.database import get_db
from src.core.security import get_current_active_user
from src.models.users import Users

router = APIRouter(prefix="/api/users", tags=["users"])

# Account creation goes through POST /api/auth/register, which enforces email verification.

class UserResponse(BaseModel):
    userId: int = Field(alias="userId")
    name: str = Field(alias="name")
    email: str
    timestamp: datetime
    is_active: bool

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


@router.get("/{user_id}", response_model=UserResponse)
def get_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: Users = Depends(get_current_active_user)
):
    """Get a specific user by ID (requires authentication)."""
    if user_id != current_user.user_id:
        raise HTTPException(status_code=403, detail="Forbidden")
    user = db.query(Users).filter(Users.user_id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user
