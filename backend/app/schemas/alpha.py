"""Temporary private-alpha access schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from app.schemas.common import BaseSchema


class AlphaUnlockRequest(BaseSchema):
    code: str = Field(min_length=1, max_length=128)


class AlphaSessionStatus(BaseSchema):
    authenticated: bool
    expires_at: datetime | None = None


class AlphaActivityRequest(BaseSchema):
    path: str = Field(min_length=1, max_length=256)


class AlphaActivitySession(BaseSchema):
    session_id: str
    unlocked_at: datetime
    last_seen_at: datetime
    current_path: str
    status: Literal["active", "idle", "offline"]


class AlphaActivityOverview(BaseSchema):
    active_now: int
    seen_today: int
    sessions: list[AlphaActivitySession]
