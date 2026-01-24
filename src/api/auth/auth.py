import os
from passlib.context import CryptContext
from jose import JWTError, jwt
from datetime import datetime, timedelta
from typing import Optional
from fastapi import Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from dotenv import load_dotenv

from src.api.database.database import get_db
from src.models.users import Users

# Load environment variables
load_dotenv()

# Password hashing (argon2 default; bcrypt allowed for legacy hashes)
pwd_context = CryptContext(schemes=["argon2", "bcrypt"], deprecated="auto")

# Token configuration
SECRET_KEY = os.getenv("SECRET_KEY")
if SECRET_KEY is None:
    raise RuntimeError("SECRET_KEY not set in environment or .env file!")

REFRESH_SECRET_KEY = os.getenv("REFRESH_SECRET_KEY", SECRET_KEY)  # Fallback to SECRET_KEY if not set
ALGORITHM = os.getenv("ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30"))
REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "7"))
EMAIL_TOKEN_EXPIRE_MINUTES = int(os.getenv("EMAIL_TOKEN_EXPIRE_MINUTES", "1440"))  # 24 hours by default

# OAuth2 scheme for token authentication
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/auth/token")

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plain password against its hash."""
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password: str) -> str:
    """Hash a password."""
    return pwd_context.hash(password)

def get_user_by_email(db: Session, email: str) -> Optional[Users]:
    """Get user by email from database."""
    return db.query(Users).filter(Users.email == email).first()

def get_user_by_id(db: Session, user_id: int) -> Optional[Users]:
    """Get user by ID from database."""
    return db.query(Users).filter(Users.user_id == user_id).first()

def authenticate_user(db: Session, email: str, password: str) -> Optional[Users]:
    """Authenticate a user with email and password."""
    user = get_user_by_email(db, email)
    if not user:
        return None
    if not verify_password(password, user.password):
        return None
    if not user.is_active:
        return None  # Prevent inactive users from logging in
    return user

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Create a JWT access token."""
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=15))
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def create_refresh_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Create a JWT refresh token."""
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(days=7))
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, REFRESH_SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def decode_refresh_token(token: str) -> dict:
    """Decode and validate a refresh token."""
    try:
        payload = jwt.decode(token, REFRESH_SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")

def refresh_access_token(request: Request, db: Session):
    """Validate refresh token and return a new access token."""
    refresh_token = request.cookies.get("refresh_token")
    if not refresh_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing refresh token")

    payload = decode_refresh_token(refresh_token)
    user_id: str = payload.get("sub")
    if user_id is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token payload")

    # Verify user exists and is active
    user = db.query(Users).filter(Users.user_id == int(user_id)).first()
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found or inactive")

    # Create a new access token
    new_access_token = create_access_token(
        data={"sub": str(user.user_id)},
        expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )

    return {"access_token": new_access_token, "token_type": "bearer"}


def create_email_verification_token(user_id: int, expires_minutes: Optional[int] = None) -> str:
    """Create a JWT token specifically for email verification."""
    minutes = expires_minutes if expires_minutes is not None else EMAIL_TOKEN_EXPIRE_MINUTES
    expire = timedelta(minutes=minutes)
    return create_access_token({"sub": str(user_id), "scope": "verify_email"}, expire)

def verify_token(token: str) -> Optional[dict]:
    """Verify and decode a JWT token."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        return None

def verify_email_token(token: str) -> Optional[int]:
    """Verify an email verification token and return the user_id if valid."""
    payload = verify_token(token)
    if payload is None:
        return None
    if payload.get("scope") != "verify_email":
        return None
    try:
        return int(payload.get("sub")) if payload.get("sub") is not None else None
    except (TypeError, ValueError):
        return None

async def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> Users:
    """Get the current authenticated user from token."""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    payload = verify_token(token)
    if payload is None:
        raise credentials_exception
    
    user_id: int = payload.get("sub")
    if user_id is None:
        raise credentials_exception
    
    user = get_user_by_id(db, user_id)
    if user is None:
        raise credentials_exception
    
    return user

async def get_current_active_user(current_user: Users = Depends(get_current_user)) -> Users:
    """Get the current active user."""
    if not current_user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")
    return current_user 
