"""User account model."""

from __future__ import annotations

import enum
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Enum, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.refresh_token import RefreshToken


class UserRole(enum.StrEnum):
    USER = "user"
    ANALYST = "analyst"
    ADMIN = "admin"


class User(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(64), nullable=True)

    role: Mapped[UserRole] = mapped_column(
        # values_callable stores the lowercase `.value`, not the enum member
        # name, so the Postgres labels match what the API serialises.
        Enum(
            UserRole,
            name="user_role",
            native_enum=True,
            validate_strings=True,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        default=UserRole.USER,
        server_default=UserRole.USER.value,
        nullable=False,
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true", nullable=False
    )
    is_verified: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )
    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    refresh_tokens: Mapped[list[RefreshToken]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    @property
    def is_admin(self) -> bool:
        return self.role is UserRole.ADMIN
