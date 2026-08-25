"""Single-use, expiring password-reset tokens.

The token itself is never stored. What is stored is its SHA-256, for the same
reason a password is stored hashed: a database read must not hand somebody the
ability to take over an account. SHA-256 rather than bcrypt is deliberate — the
token is 256 bits of `secrets` output, so there is no dictionary to slow an
attacker down through, and a fast digest keeps verification O(1) on a lookup by
hash rather than a scan.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UUIDPrimaryKeyMixin


class PasswordResetToken(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "password_reset_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    #: SHA-256 hex of the emailed token. The token is never written anywhere.
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    #: Set the moment it is spent. A used token is kept, not deleted, so a
    #: second attempt is a recorded event rather than a silent miss.
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    #: Superseded when a newer request arrives, so only the latest link works.
    invalidated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    requested_ip: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_password_reset_user", "user_id", "created_at"),
    )
