"""Minimal, anonymous state for private-alpha session activity."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UUIDPrimaryKeyMixin


class AlphaSession(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "alpha_sessions"

    # The signed alpha cookie's random JWT jti. It is generated server-side and
    # is not an account, device, browser, IP address, or fingerprint.
    session_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    unlocked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), index=True, nullable=False
    )
    current_path: Mapped[str] = mapped_column(String(256), nullable=False, default="/")
    # The migration intentionally uses a unique constraint for session_id and
    # indexes last_seen_at for status/retention queries. These timestamp fields
    # stay unindexed to match that immutable schema exactly.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
