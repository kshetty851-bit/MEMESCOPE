"""Watchlist, event and brief contracts.

Every `summary` field arrives as a finished sentence rendered server-side, the
same convention `ScoreReason.message` and the Radar's reasons follow. A client
that composed these would own a claim the platform never issued.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import Field

from app.schemas.common import BaseSchema

# --- Watchlists -------------------------------------------------------------


class WatchlistCreate(BaseSchema):
    name: str = Field(min_length=1, max_length=64)
    description: str | None = Field(default=None, max_length=280)
    #: Event kinds that should interrupt the user. Empty means record
    #: everything, interrupt for nothing — the default, because a system that
    #: notifies by default gets muted by default.
    alert_on: list[str] = Field(default_factory=list)


class WatchlistUpdate(BaseSchema):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    description: str | None = Field(default=None, max_length=280)
    alert_on: list[str] | None = None


class WatchlistRead(BaseSchema):
    id: uuid.UUID
    name: str
    description: str | None
    alert_on: list[str]
    item_count: int
    created_at: datetime
    updated_at: datetime


class WatchlistItemCreate(BaseSchema):
    mint_address: str = Field(min_length=32, max_length=44)
    note: str | None = Field(default=None, max_length=2000)


class WatchlistItemRead(BaseSchema):
    mint_address: str
    note: str | None
    #: State captured when the token was added, so the timeline can answer
    #: "what changed since I started watching?" without re-deriving history.
    added_mission_state: str | None
    added_priority: str | None
    added_score: Decimal | None
    created_at: datetime
    #: Live state, when the platform currently has a reading for it.
    current_mission_state: str | None = None
    current_priority: str | None = None
    current_score: Decimal | None = None
    #: The most recent event for this token, if any.
    last_change: str | None = None
    last_change_at: datetime | None = None


# --- Events -----------------------------------------------------------------


class EventRead(BaseSchema):
    id: uuid.UUID
    mint_address: str
    kind: str
    severity: str
    #: Which analyst detected it. Null for ensemble-level changes.
    analyst: str | None
    previous_value: str | None
    current_value: str | None
    summary: str
    occurred_at: datetime


class EventPage(BaseSchema):
    items: list[EventRead]
    total: int
    page: int
    page_size: int
    pages: int
    #: Echoed so an empty page caused by a strict filter is distinguishable
    #: from an empty log — the convention `/scores/top` established.
    applied_filters: dict[str, str | None]


# --- Brief ------------------------------------------------------------------


class BriefCounts(BaseSchema):
    new_opportunities: int
    promotions: int
    demotions: int
    risk_increases: int
    risk_resolutions: int
    clone_warnings: int
    #: Events whose kind the brief has no category for. Reported rather than
    #: dropped: a silently discarded event is worse than an uncategorised one.
    other: int


class BriefRead(BaseSchema):
    since: datetime
    generated_at: datetime
    counts: BriefCounts
    #: The events themselves, newest first, so the brief is checkable.
    entries: list[EventRead]
    #: True when nothing happened. Stated explicitly rather than left to an
    #: empty list, because "nothing changed" is a finding.
    quiet: bool
    summary: str
