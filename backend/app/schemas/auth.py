"""Authentication schemas."""

from __future__ import annotations

from pydantic import EmailStr, Field

from app.schemas.common import BaseSchema
from app.schemas.user import UserRead


class LoginRequest(BaseSchema):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class AccessToken(BaseSchema):
    access_token: str
    token_type: str = "bearer"
    expires_in: int = Field(description="Access token lifetime in seconds.")


class AuthResponse(AccessToken):
    """Login/register/refresh response.

    The refresh token is deliberately absent: it is delivered as an httpOnly
    cookie so browser JavaScript can never read it.
    """

    user: UserRead


class MessageResponse(BaseSchema):
    message: str
