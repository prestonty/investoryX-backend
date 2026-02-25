from fastapi import APIRouter, HTTPException

from src.api.services.email_service import sendSignUpEmail, sendWelcomeEmail
from src.models.requests import EmailRequest


router = APIRouter(tags=["email"])


@router.post("/send-sign-up-email")
def send_sign_up_email(request: EmailRequest):
    try:
        return sendSignUpEmail(request.email, request.first_name, request.verification_url)
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/send-welcome-email")
def send_welcome_email(email: str, first_name: str, dashboard_url: str):
    try:
        return sendWelcomeEmail(email, first_name, dashboard_url)
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
