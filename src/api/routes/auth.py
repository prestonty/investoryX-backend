from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from datetime import timedelta
from pydantic import BaseModel, ConfigDict, Field
from fastapi.responses import JSONResponse
import os
from src.api.auth.auth import get_user_by_email
from src.api.services.email_service import sendSignUpEmail


from src.api.database.database import get_db
from src.api.auth.auth import (
    authenticate_user,
    create_access_token,
    create_refresh_token,
    get_password_hash,
    get_current_active_user,
    ACCESS_TOKEN_EXPIRE_MINUTES,
    REFRESH_TOKEN_EXPIRE_DAYS,
    create_email_verification_token,
    verify_email_token,
    refresh_access_token,
)
from src.models.users import Users

router = APIRouter(prefix="/api/auth", tags=["authentication"])
DISABLE_EMAIL_VERIFICATION = os.getenv("DISABLE_EMAIL_VERIFICATION", "false").lower() in ("1", "true", "yes")

class Token(BaseModel):
    access_token: str
    token_type: str

class UserCreate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    name: str = Field(alias="Name")
    email: str
    password: str

class UserResponse(BaseModel):
    user_id: int
    name: str
    email: str
    is_active: bool

    class Config:
        from_attributes = True

class TestEmailRequest(BaseModel):
    email: str
    name: str
    verification_url: str | None = None



@router.post("/token", response_model=Token)
async def login_for_access_token(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
    request: Request = None
):
    """Login endpoint that returns a JWT token and sets cookies."""
    # Check if user exists first
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
    
    # Ensure user is active (email verified) unless verification is disabled
    if not user.is_active and not DISABLE_EMAIL_VERIFICATION:
        # Don't resend verification email automatically - user should use the one from registration
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Email not verified. Please check your email for the verification link from when you registered.",
        )
    
    # Create both access and refresh tokens
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": str(user.user_id)}, expires_delta=access_token_expires
    )
    
    refresh_token_expires = timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    refresh_token = create_refresh_token(
        data={"sub": str(user.user_id)}, expires_delta=refresh_token_expires
    )
    
    # Create response with tokens
    response = {"access_token": access_token, "token_type": "bearer"}
    
    # Set cookies in the response
    json_response = JSONResponse(content=response)
    
    # Set access token cookie (httpOnly=False so frontend can read it)
    json_response.set_cookie(
        key="access_token",
        value=access_token,
        max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60,  # Convert to seconds
        httponly=False,
        secure=False,  # Set to True in production with HTTPS
        samesite="lax",
        path="/"
    )
    
    # Set refresh token cookie (httpOnly=True for security)
    json_response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        max_age=REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60,  # Convert to seconds
        httponly=True,
        secure=False,  # Set to True in production with HTTPS
        samesite="lax",
        path="/"
    )
    
    return json_response

@router.post("/register", response_model=UserResponse)
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
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Registration failed: {exc}",
        )



@router.get("/me", response_model=UserResponse)
async def read_users_me(current_user: Users = Depends(get_current_active_user)):
    """Get current user information."""
    return current_user 

@router.get("/verify-email")
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

@router.post("/refresh")
def refresh_token_endpoint(request: Request, db: Session = Depends(get_db)):
    """Endpoint to refresh access token using a refresh token from cookies."""
    result = refresh_access_token(request, db)
    
    # Set the new access token as a cookie
    response = JSONResponse(content=result)
    
    response.set_cookie(
        key="access_token",
        value=result["access_token"],
        max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60,  # Convert to seconds
        httponly=False,
        secure=False,  # Set to True in production with HTTPS
        samesite="lax",
        path="/"
    )
    
    return response

@router.post("/logout")
async def logout():
    """Logout endpoint that clears authentication cookies."""    
    response = JSONResponse(content={"message": "Logged out successfully"})
    
    # Clear access token cookie
    response.delete_cookie(
        key="access_token",
        path="/"
    )
    
    # Clear refresh token cookie
    response.delete_cookie(
        key="refresh_token",
        path="/"
    )
    
    return response

@router.post("/test-email")
async def test_email(payload: TestEmailRequest):
    """Send a test verification email to validate Resend setup."""
    verification_url = payload.verification_url or "http://localhost:3000/verify-email?token=test"
    try:
        sendSignUpEmail(payload.email, payload.name, verification_url)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Email send failed: {exc}",
        )
    return {"message": "Test email sent"}
