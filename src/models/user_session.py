from src.core.database import Base
from sqlalchemy import Column, ForeignKey, Index, Integer, String, TIMESTAMP, text


class UserSession(Base):
    # One row per login. Access and refresh tokens carry the session_id, so
    # revoking the row (logout, refresh-token reuse) invalidates both at once.
    __tablename__ = "user_sessions"
    __table_args__ = (Index("ix_user_sessions_user_id", "user_id"),)

    session_id = Column(String(36), primary_key=True, nullable=False)
    user_id = Column(
        Integer,
        ForeignKey("users.user_id", ondelete="CASCADE"),
        nullable=False,
    )
    # The only refresh token id (jti) currently accepted for this session.
    refresh_jti = Column(String(36), nullable=False)
    # The token it replaced, accepted briefly so two tabs refreshing at the same
    # moment aren't mistaken for a stolen token being replayed.
    previous_refresh_jti = Column(String(36), nullable=True)
    rotated_at = Column(TIMESTAMP(timezone=True), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=text("now()"))
    expires_at = Column(TIMESTAMP(timezone=True), nullable=False)
    revoked_at = Column(TIMESTAMP(timezone=True), nullable=True)
    revoked_reason = Column(String, nullable=True)
