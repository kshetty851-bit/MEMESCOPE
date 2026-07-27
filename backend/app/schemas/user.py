"""User request/response schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import EmailStr, Field, field_validator

from app.core.config import settings
from app.models.user import UserRole
from app.schemas.common import BaseSchema


def _validate_password_strength(value: str) -> str:
    if len(value) < settings.PASSWORD_MIN_LENGTH:
        raise ValueError(
            f"Password must be at least {settings.PASSWORD_MIN_LENGTH} characters."
        )
    if not any(char.isdigit() for char in value):
        raise ValueError("Password must contain at least one digit.")
    if not any(char.isalpha() for char in value):
        raise ValueError("Password must contain at least one letter.")
    return value


class UserCreate(BaseSchema):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    display_name: str | None = Field(default=None, max_length=64)

    _check_password = field_validator("password")(_validate_password_strength)


class UserUpdate(BaseSchema):
    display_name: str | None = Field(default=None, max_length=64)


class PasswordChange(BaseSchema):
    current_password: str
    new_password: str = Field(min_length=8, max_length=128)

    _check_password = field_validator("new_password")(_validate_password_strength)


class UserRead(BaseSchema):
    id: uuid.UUID
    email: EmailStr
    display_name: str | None
    role: UserRole
    is_active: bool
    is_verified: bool
    last_login_at: datetime | None
    created_at: datetime
