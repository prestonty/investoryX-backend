"""Login sessions: issuing, rotating and revoking token pairs, and auth cookies.

Every login creates a UserSession row. Access tokens (short-lived) and refresh
tokens carry its session id ("sid"), so revoking the row logs that session out
immediately. Each refresh rotates the refresh token; presenting an already
rotated token again (outside a short grace window) is treated as theft and
revokes the whole session.
"""

import logging
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, Response, status
from sqlalchemy.orm import Session

from src.core.config import settings
from src.core.security import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    REFRESH_TOKEN_EXPIRE_DAYS,
    create_access_token,
    create_refresh_token,
    decode_refresh_token,
)
from src.models.user_session import UserSession
from src.models.users import Users

logger = logging.getLogger("investoryx.sessions")

ACCESS_COOKIE = "access_token"
REFRESH_COOKIE = "refresh_token"
# Readable by the frontend, holds no secret: it only tells the UI a session
# probably exists, since the token cookies are httpOnly.
SESSION_HINT_COOKIE = "session_active"
# The refresh token is only ever needed by the auth endpoints.
REFRESH_COOKIE_PATH = "/api/auth"
# Two tabs refreshing at the same moment both present the same refresh token;
# the second one within this window gets the current tokens instead of tripping
# reuse detection.
ROTATION_GRACE_SECONDS = 30

_unauthorized = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired or revoked"
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime | None) -> datetime | None:
    # SQLite (tests) returns naive datetimes; Postgres returns aware ones.
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _issue(session: UserSession) -> tuple[str, str]:
    claims = {"sub": str(session.user_id), "sid": session.session_id}
    access = create_access_token(claims, timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    refresh = create_refresh_token(
        {**claims, "jti": session.refresh_jti},
        timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS),
    )
    return access, refresh


def start_session(db: Session, user: Users) -> tuple[str, str]:
    """Create a session for a successful login and return (access, refresh) tokens."""
    session = UserSession(
        session_id=str(uuid.uuid4()),
        user_id=user.user_id,
        refresh_jti=str(uuid.uuid4()),
        expires_at=_now() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS),
    )
    db.add(session)
    db.commit()
    return _issue(session)


def session_is_active(db: Session, session_id: str | None, user_id: int) -> bool:
    if not session_id:
        return False
    session = db.get(UserSession, session_id)
    return (
        session is not None
        and session.user_id == user_id
        and session.revoked_at is None
        and _aware(session.expires_at) > _now()
    )


def rotate_session(db: Session, refresh_token: str | None) -> tuple[str, str]:
    """Exchange a refresh token for a new (access, refresh) pair; raises 401 if not allowed."""
    if not refresh_token:
        raise _unauthorized
    payload = decode_refresh_token(refresh_token)
    try:
        user_id = int(payload.get("sub"))
    except (TypeError, ValueError):
        raise _unauthorized
    session_id, jti = payload.get("sid"), payload.get("jti")

    if not session_id:
        # Refresh token issued before sessions existed: convert it into a session once.
        user = db.get(Users, user_id)
        if user is None or not user.is_active:
            raise _unauthorized
        return start_session(db, user)

    # Lock the row so concurrent refreshes of one session are serialized.
    session = (
        db.query(UserSession)
        .filter(UserSession.session_id == session_id)
        .with_for_update()
        .first()
    )
    now = _now()
    if (
        session is None
        or session.user_id != user_id
        or session.revoked_at is not None
        or _aware(session.expires_at) <= now
    ):
        db.rollback()
        raise _unauthorized

    if jti == session.refresh_jti:
        session.previous_refresh_jti = session.refresh_jti
        session.refresh_jti = str(uuid.uuid4())
        session.rotated_at = now
        session.expires_at = now + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
        db.commit()
        return _issue(session)

    rotated_at = _aware(session.rotated_at)
    if (
        jti is not None
        and jti == session.previous_refresh_jti
        and rotated_at is not None
        and now - rotated_at <= timedelta(seconds=ROTATION_GRACE_SECONDS)
    ):
        # Concurrent refresh from another tab: hand out the current tokens.
        db.commit()
        return _issue(session)

    # An old refresh token was replayed: assume it was stolen and end the session.
    logger.warning("Refresh token reuse detected; revoking session %s", session_id)
    session.revoked_at = now
    session.revoked_reason = "refresh_token_reuse"
    db.commit()
    raise _unauthorized


def revoke_session_for_token(db: Session, token_payload: dict | None, reason: str) -> None:
    """Revoke the session a decoded token belongs to (no-op if it has none)."""
    session_id = (token_payload or {}).get("sid")
    if not session_id:
        return
    session = db.get(UserSession, session_id)
    if session is not None and session.revoked_at is None:
        session.revoked_at = _now()
        session.revoked_reason = reason
        db.commit()


def set_auth_cookies(response: Response, access_token: str, refresh_token: str) -> None:
    common = {
        "domain": settings.cookie_domain,
        "secure": settings.secure_cookies,
        "samesite": "lax",
    }
    response.set_cookie(
        ACCESS_COOKIE, access_token, max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        httponly=True, path="/", **common,
    )
    response.set_cookie(
        REFRESH_COOKIE, refresh_token, max_age=REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60,
        httponly=True, path=REFRESH_COOKIE_PATH, **common,
    )
    response.set_cookie(
        SESSION_HINT_COOKIE, "1", max_age=REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60,
        httponly=False, path="/", **common,
    )


def clear_auth_cookies(response: Response) -> None:
    common = {
        "domain": settings.cookie_domain,
        "secure": settings.secure_cookies,
        "samesite": "lax",
    }
    response.delete_cookie(ACCESS_COOKIE, path="/", httponly=True, **common)
    response.delete_cookie(REFRESH_COOKIE, path=REFRESH_COOKIE_PATH, httponly=True, **common)
    response.delete_cookie(SESSION_HINT_COOKIE, path="/", **common)
    # Refresh cookies from before the path was narrowed to /api/auth.
    response.delete_cookie(REFRESH_COOKIE, path="/", httponly=True, **common)
