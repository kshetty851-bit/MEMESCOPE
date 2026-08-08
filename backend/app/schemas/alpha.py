"""Temporary private-alpha access schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from app.schemas.common import BaseSchema


class AlphaUnlockRequest(BaseSchema):
    code: str = Field(min_length=1, max_length=128)


class AlphaSessionStatus(BaseSchema):
    authenticated: bool
    expires_at: datetime | None = None
