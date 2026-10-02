from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from pydantic import BaseModel, ConfigDict, Field, field_validator
from fastapi.responses import JSONResponse
import os
from src.services.email import sendSignUpEmail


from src.core.database import get_db
from src.core.rate_limit import RateLimit
from src.core.security import (
    authenticate_user,
    decode_refresh_token,
    get_password_hash,
    get_current_active_user,
    create_email_verification_token,
    verify_email_token,
    verify_token,
)
from src.core.sessions import (
    ACCESS_COOKIE,
    REFRESH_COOKIE,
    clear_auth_cookies,
    revoke_session_for_token,
    rotate_session,
    set_auth_cookies,
    start_session,
)
from src.models.users import Users

router = APIRouter(prefix="/api/auth", tags=["authentication"])

# Per-IP limits against brute-force logins, signup spam and email-quota abuse.
LOGIN_LIMIT = RateLimit("login", limit=10, window_seconds=60)
REGISTER_LIMIT = RateLimit("register", limit=5, window_seconds=3600)
VERIFY_EMAIL_LIMIT = RateLimit("verify_email", limit=20, window_seconds=60)
REFRESH_LIMIT = RateLimit("refresh", limit=30, window_seconds=60)
DISABLE_EMAIL_VERIFICATION = os.getenv("DISABLE_EMAIL_VERIFICATION", "false").lower() in ("1", "true", "yes")

class Token(BaseModel):
    access_token: str
    token_type: str

PASSWORD_MIN_LENGTH = 8


class UserCreate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    name: str = Field(alias="Name")
    email: str
    password: str

    @field_validator("password")
    @classmethod
    def password_policy(cls, value: str) -> str:
        # Keep in sync with the signup form's checks in the frontend.
        if len(value) < PASSWORD_MIN_LENGTH:
            raise ValueError(f"Password must be at least {PASSWORD_MIN_LENGTH} characters")
        if not any(ch.isalpha() for ch in value):
            raise ValueError("Password must contain at least one letter")
        if not any(ch.isdigit() for ch in value):
            raise ValueError("Password must contain at least one number")
        return value

class UserResponse(BaseModel):
    user_id: int
    name: str
    email: str
    is_active: bool

    class Config:
        from_attributes = True


@router.post("/token", response_model=Token, dependencies=[Depends(LOGIN_LIMIT)])
async def login_for_access_token(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
    request: Request = None
):
    """Log in: starts a session and sets httpOnly auth cookies.

    The access token is also returned in the body for API clients and the
    OpenAPI docs; the web frontend relies on the cookies only.
    """
    # Authenticate — a single generic error and constant-time password check
    # (also for unknown emails) prevent user enumeration
    user = authenticate_user(db, form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Ensure user is active (email verified) unless verification is disabled
    if not user.is_active and not DISABLE_EMAIL_VERIFICATION:
        # Don't resend verification email automatically - user should use the one from registration
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Email not verified. Please check your email for the verification link from when you registered.",
        )

    access_token, refresh_token = start_session(db, user)
    response = JSONResponse(content={"access_token": access_token, "token_type": "bearer"})
    set_auth_cookies(response, access_token, refresh_token)
    return response

@router.post("/register", response_model=UserResponse, dependencies=[Depends(REGISTER_LIMIT)])
async def register_user(user: UserCreate, db: Session = Depends(get_db)):
    """Register a new user."""
    try:
        # Check if user already exists
        existing_user = db.query(Users).filter(Users.email == user.email).first()
        if existing_user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email already registered",
            )

        # Create new user with hashed password
        hashed_password = get_password_hash(user.password)
        db_user = Users(
            name=user.name,
            email=user.email,
            password=hashed_password,
            is_active=DISABLE_EMAIL_VERIFICATION is True,  # Set to True when verification is disabled
        )

        db.add(db_user)
        db.commit()
        db.refresh(db_user)

        if not DISABLE_EMAIL_VERIFICATION:
            # Create email verification token and send email
            verification_token = create_email_verification_token(db_user.user_id)
            # Construct proper verification URL with token
            frontend_url = os.getenv("FRONTEND_BASE_URL", "http://localhost:3000")
            verification_url = f"{frontend_url}/verify-email?token={verification_token}"

            try:
                sendSignUpEmail(db_user.email, db_user.name, verification_url)
            except Exception:
                # If email fails, we still created the account but inform the client
                # Client can trigger resend verification later
                pass

        return db_user
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Registration failed. Please try again.",
        )



@router.get("/me", response_model=UserResponse)
async def read_users_me(current_user: Users = Depends(get_current_active_user)):
    """Get current user information."""
    return current_user

@router.get("/verify-email", dependencies=[Depends(VERIFY_EMAIL_LIMIT)])
async def verify_email(token: str, db: Session = Depends(get_db)):
    """Endpoint to verify a user's email using a token."""
    user_id = verify_email_token(token)
    if user_id is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired verification token")

    user = db.query(Users).filter(Users.user_id == user_id).first()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    if user.is_active:
        return {"message": "Account already verified"}

    user.is_active = True
    db.add(user)
    db.commit()

    return {"message": "Email verified successfully"}

@router.post("/refresh", dependencies=[Depends(REFRESH_LIMIT)])
def refresh_token_endpoint(request: Request, db: Session = Depends(get_db)):
    """Rotate the refresh-token cookie and issue a new access-token cookie.

    Tokens are only delivered as httpOnly cookies, never in the body.
    """
    try:
        access_token, refresh_token = rotate_session(db, request.cookies.get(REFRESH_COOKIE))
    except HTTPException as exc:
        # Clear stale cookies so the frontend stops treating the user as logged in.
        response = JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
        clear_auth_cookies(response)
        return response

    response = JSONResponse(content={"message": "Session refreshed"})
    set_auth_cookies(response, access_token, refresh_token)
    return response


@router.post("/logout")
def logout(request: Request, db: Session = Depends(get_db)):
    """Revoke the current session (its tokens stop working immediately) and clear cookies."""
    payload = None
    refresh_token = request.cookies.get(REFRESH_COOKIE)
    if refresh_token:
        try:
            payload = decode_refresh_token(refresh_token)
        except HTTPException:
            payload = None
    if payload is None:
        authorization = request.headers.get("authorization", "")
        bearer = authorization[7:] if authorization.lower().startswith("bearer ") else None
        access_token = bearer or request.cookies.get(ACCESS_COOKIE)
        payload = verify_token(access_token) if access_token else None

    revoke_session_for_token(db, payload, reason="logout")

    response = JSONResponse(content={"message": "Logged out successfully"})
    clear_auth_cookies(response)
    return response
