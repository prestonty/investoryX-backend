from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from datetime import timedelta
from pydantic import BaseModel

from src.api.database.database import get_db
from src.api.auth.auth import (
    authenticate_user, 
    create_access_token, 
    get_password_hash, 
    get_current_active_user,
    ACCESS_TOKEN_EXPIRE_MINUTES
)
from src.models.users import Users

router = APIRouter(prefix="/api/auth", tags=["authentication"])

class Token(BaseModel):
    access_token: str
    token_type: str

class UserCreate(BaseModel):
    Name: str
    email: str
    password: str

class UserResponse(BaseModel):
    UserId: int
    Name: str
    email: str
    is_active: bool

    class Config:
        from_attributes = True

@router.post("/token", response_model=Token)
async def login_for_access_token(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db)
):
    """Login endpoint that returns a JWT token."""
    # Check if user exists first
    from src.api.auth.auth import get_user_by_email
    existing_user = get_user_by_email(db, form_data.username)
    
    if not existing_user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No account found with this email address",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Now check password
    user = authenticate_user(db, form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": str(user.UserId)}, expires_delta=access_token_expires
    )
    
    return {"access_token": access_token, "token_type": "bearer"}

@router.post("/register", response_model=UserResponse)
async def register_user(user: UserCreate, db: Session = Depends(get_db)):
    """Register a new user."""
    # Check if user already exists
    existing_user = db.query(Users).filter(Users.email == user.email).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered"
        )
    
    # Create new user with hashed password
    hashed_password = get_password_hash(user.password)
    db_user = Users(
        Name=user.Name,
        email=user.email,
        password=hashed_password,
        is_active=True  # Set to True by default, you can change this if you want email verification
    )
    
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    
    return db_user

@router.get("/me", response_model=UserResponse)
async def read_users_me(current_user: Users = Depends(get_current_active_user)):
    """Get current user information."""
    return current_user 