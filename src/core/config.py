import os
from decimal import Decimal
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

    # Paper-trading execution costs, applied the same way by every trading path
    # (strategy fills, backtests and manual orders). Slippage always works against
    # the trader: buys fill above the market price, sells below. 5 bps = 0.05%.
    sim_fee_per_trade: Decimal = Decimal(os.getenv("SIM_FEE_PER_TRADE", "0"))
    sim_slippage_bps: Decimal = Decimal(os.getenv("SIM_SLIPPAGE_BPS", "5"))
    # Largest notional value of a single paper buy; unset means no cap.
    sim_max_order_value: Decimal | None = (
        Decimal(os.environ["SIM_MAX_ORDER_VALUE"]) if os.getenv("SIM_MAX_ORDER_VALUE") else None
    )

    debug_errors: bool = os.getenv("DEBUG_ERRORS", "false").lower() in ("1", "true", "yes")
    rate_limit_enabled: bool = os.getenv("RATE_LIMIT_ENABLED", "true").lower() in ("1", "true", "yes")
    # Only enable behind a proxy that sets X-Forwarded-For (e.g. Railway); otherwise
    # clients could spoof the header to dodge rate limits.
    trust_proxy_headers: bool = os.getenv("TRUST_PROXY_HEADERS", "false").lower() in ("1", "true", "yes")
    disable_email_verification: bool = os.getenv("DISABLE_EMAIL_VERIFICATION", "false").lower() in ("1", "true", "yes")
    dev_mode: bool = os.getenv("DEV_MODE", "false").lower() in ("1", "true", "yes")

    frontend_base_url: str = os.getenv("FRONTEND_BASE_URL", "http://localhost:3000")

    # Auth cookies. Production serves the API at api.investoryx.ca, so
    # COOKIE_DOMAIN=.investoryx.ca shares them with the frontend's server
    # (www.investoryx.ca). Leave unset locally (host-only cookies on localhost).
    cookie_domain: str | None = os.getenv("COOKIE_DOMAIN") or None
    secure_cookies: bool = os.getenv("ENVIRONMENT", "development").lower() == "production"

    @property
    def cors_origins(self) -> list[str]:
        raw = os.getenv("CORS_ORIGINS", "")
        if raw:
            return [o.strip() for o in raw.split(",") if o.strip()]
        return [self.frontend_base_url]


settings = Settings()
