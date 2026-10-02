import os
from passlib.context import CryptContext
from jose import JWTError, jwt
from datetime import datetime, timedelta, timezone
from typing import Optional
from fastapi import Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from dotenv import load_dotenv

from src.core.database import get_db
from src.models.user_session import UserSession
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
# Short-lived: the frontend refreshes transparently, and a stolen access token
# is only useful briefly (logout revokes it immediately anyway).
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "15"))
REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "7"))
EMAIL_TOKEN_EXPIRE_MINUTES = int(os.getenv("EMAIL_TOKEN_EXPIRE_MINUTES", "1440"))  # 24 hours by default

# OAuth2 scheme for token authentication
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/auth/token", auto_error=False)

# Every token carries a "type" claim so one kind can't be used as another
# (e.g. an emailed verification link or a refresh cookie as an API bearer token).
TOKEN_TYPE_ACCESS = "access"
TOKEN_TYPE_REFRESH = "refresh"
TOKEN_TYPE_VERIFY_EMAIL = "verify_email"

# Verified against when the email doesn't exist, so login takes the same time
# either way and response timing can't reveal which emails have accounts.
_DUMMY_PASSWORD_HASH = pwd_context.hash("not-a-real-password")

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
        verify_password(password, _DUMMY_PASSWORD_HASH)
        return None
    if not verify_password(password, user.password):
        return None
    if not user.is_active:
        return None  # Prevent inactive users from logging in
    return user

def create_access_token(
    data: dict,
    expires_delta: Optional[timedelta] = None,
    token_type: str = TOKEN_TYPE_ACCESS,
) -> str:
    """Create a JWT signed with SECRET_KEY (an API access token by default)."""
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=15))
    to_encode.update({"exp": expire, "type": token_type})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def create_refresh_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Create a JWT refresh token."""
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(days=7))
    to_encode.update({"exp": expire, "type": TOKEN_TYPE_REFRESH})
    encoded_jwt = jwt.encode(to_encode, REFRESH_SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def decode_refresh_token(token: str) -> dict:
    """Decode and validate a refresh token."""
    try:
        payload = jwt.decode(token, REFRESH_SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")
    # Refresh tokens issued before the "type" claim existed have no type; accept
    # them until they expire (REFRESH_TOKEN_EXPIRE_DAYS) so nobody is logged out.
    if payload.get("type") not in (TOKEN_TYPE_REFRESH, None):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")
    return payload

def create_email_verification_token(user_id: int, expires_minutes: Optional[int] = None) -> str:
    """Create a JWT token specifically for email verification."""
    minutes = expires_minutes if expires_minutes is not None else EMAIL_TOKEN_EXPIRE_MINUTES
    expire = timedelta(minutes=minutes)
    return create_access_token(
        {"sub": str(user_id), "scope": "verify_email"},
        expire,
        token_type=TOKEN_TYPE_VERIFY_EMAIL,
    )

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

async def get_current_user(
    request: Request,
    bearer_token: Optional[str] = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> Users:
    """Get the current user from the access token.

    Browsers send it as the httpOnly `access_token` cookie; API clients (and
    the OpenAPI docs) may send it as a Bearer header instead.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    token = bearer_token or request.cookies.get("access_token")
    if not token:
        raise credentials_exception
    payload = verify_token(token)
    if payload is None:
        raise credentials_exception
    # Only access tokens authenticate API calls. Older tokens without a type or
    # session are rejected too; the frontend then refreshes and gets new ones.
    if payload.get("type") != TOKEN_TYPE_ACCESS:
        raise credentials_exception

    try:
        user_id = int(payload.get("sub"))
    except (TypeError, ValueError):
        raise credentials_exception

    # Logout and refresh-token reuse revoke the session, which must invalidate
    # its access tokens immediately rather than at expiry.
    session = db.get(UserSession, payload.get("sid")) if payload.get("sid") else None
    if (
        session is None
        or session.user_id != user_id
        or session.revoked_at is not None
        or _as_utc(session.expires_at) <= datetime.now(timezone.utc)
    ):
        raise credentials_exception

    user = get_user_by_id(db, user_id)
    if user is None:
        raise credentials_exception

    return user


def _as_utc(value: datetime) -> datetime:
    # SQLite (tests) returns naive datetimes; Postgres returns aware ones.
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)

async def get_current_active_user(current_user: Users = Depends(get_current_user)) -> Users:
    """Get the current active user."""
    if not current_user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")
    return current_user
