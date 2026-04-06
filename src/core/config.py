import os
from dotenv import load_dotenv

load_dotenv()


class Settings:
    database_url: str = os.getenv("DATABASE_URL", "")
    secret_key: str = os.getenv("SECRET_KEY", "")
    refresh_secret_key: str = os.getenv("REFRESH_SECRET_KEY", secret_key)
    algorithm: str = os.getenv("ALGORITHM", "HS256")

    access_token_expire_minutes: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30"))
    refresh_token_expire_days: int = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "7"))
    email_token_expire_minutes: int = int(os.getenv("EMAIL_TOKEN_EXPIRE_MINUTES", "1440"))

    redis_url: str = os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0")
    resend_api_key: str = os.getenv("RESEND_API_KEY", "")

    stock_search_limit: int = 200
    screener_cache_ttl: int = 300  # seconds

    debug_errors: bool = os.getenv("DEBUG_ERRORS", "false").lower() in ("1", "true", "yes")
    disable_email_verification: bool = os.getenv("DISABLE_EMAIL_VERIFICATION", "false").lower() in ("1", "true", "yes")
    dev_mode: bool = os.getenv("DEV_MODE", "false").lower() in ("1", "true", "yes")

    frontend_base_url: str = os.getenv("FRONTEND_BASE_URL", "http://localhost:3000")


settings = Settings()
