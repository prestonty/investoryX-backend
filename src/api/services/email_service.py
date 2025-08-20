import resend
import os
from pathlib import Path
from datetime import datetime

resend.api_key = os.getenv("RESEND_API_KEY")

def load_template(template_name: str) -> str:
    """Load an HTML email template from the templates directory"""
    template_path = Path(__file__).parent / "email_templates" / f"{template_name}.html"
    with open(template_path, 'r', encoding='utf-8') as f:
        return f.read()

def sendSignUpEmail(email: str, first_name: str, verification_url: str, link_ttl_minutes: int = 15):
    """Send email verification email using the sign_up.html template"""
    html_content = load_template("sign_up")
    
    # Replace template variables
    html_content = html_content.replace("{email}", email)
    html_content = html_content.replace("{verification_url}", verification_url)
    html_content = html_content.replace("{link_ttl_minutes}", str(link_ttl_minutes))
    html_content = html_content.replace("{year}", str(datetime.now().year))
    
    params: resend.Emails.SendParams = {
        "from": "InvestoryX <noreply@investoryx.ca>",
        "to": [email],
        "subject": "Verify your email - InvestoryX",
        "html": html_content,
    }

    try:
        resend.Emails.send(params)
    except Exception as e:
        raise RuntimeError(f"Error sending verification email: {e}")

def sendWelcomeEmail(email: str, first_name: str, dashboard_url: str):
    """Send welcome email using the welcome.html template"""
    html_content = load_template("welcome")
    
    # Replace template variables
    html_content = html_content.replace("{first_name}", first_name)
    html_content = html_content.replace("{dashboard_url}", dashboard_url)
    html_content = html_content.replace("{year}", str(datetime.now().year))
    
    params: resend.Emails.SendParams = {
        "from": "InvestoryX <noreply@investoryx.ca>",
        "to": [email],
        "subject": "Welcome to InvestoryX! 🎉",
        "html": html_content,
    }

    try:
        resend.Emails.send(params)
    except Exception as e:
        raise RuntimeError(f"Error sending welcome email: {e}")
