"""Refresh token model.

Only the SHA-256 digest of the token is persisted. Rotation is tracked via
`replaced_by_id`, which makes reuse of an already-rotated token detectable —
the classic signal that a refresh token has been stolen.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import INET
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.user import User


class RefreshToken(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "refresh_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    token_hash: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    replaced_by_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("refresh_tokens.id", ondelete="SET NULL"),
        nullable=True,
    )

    user_agent: Mapped[str | None] = mapped_column(String(400), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(INET, nullable=True)

    user: Mapped[User] = relationship(back_populates="refresh_tokens", lazy="joined")

    @property
    def is_expired(self) -> bool:
        return self.expires_at <= datetime.now(UTC)

    @property
    def is_active(self) -> bool:
        return self.revoked_at is None and not self.is_expired
