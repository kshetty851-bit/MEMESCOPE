"""Watchlists and the immutable event record.

Four tables, all additive. Nothing in `radar_*`, `token_scores`,
`token_market_snapshots` or `discovered_tokens` is touched — Phase 16 sits on
top of the existing intelligence rather than inside it.

Two shapes carry the weight:

  * **`analyst_reading_cache`** is mutable, one row per token. It holds the
    last observed state so the next cycle can diff against it without
    re-analysing the universe. This is what makes event generation incremental
    rather than a full rescan.
  * **`intelligence_events`** is append-only. Once written an event is never
    updated or deleted, because the whole value of "what changed last week" is
    that the answer cannot be quietly revised. It is the same discipline
    `token_market_snapshots` and `radar_tokens` already hold.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class EventKind(enum.StrEnum):
    """What changed. Persisted, so append-only.

    Deliberately named for the *observation*, never for an action. There is no
    `BUY_SIGNAL` here and there never will be — an event says what the analysts
    saw move, and what a user does with that is not something the platform has
    a view on.
    """

    MISSION_PROMOTED = "mission_promoted"
    MISSION_DOWNGRADED = "mission_downgraded"
    PRIORITY_INCREASED = "priority_increased"
    PRIORITY_DECREASED = "priority_decreased"
    RISK_INCREASED = "risk_increased"
    RISK_RESOLVED = "risk_resolved"
    CLONE_DETECTED = "clone_detected"
    CLONE_RESOLVED = "clone_resolved"
    LIQUIDITY_IMPROVED = "liquidity_improved"
    LIQUIDITY_WEAKENED = "liquidity_weakened"
    MOMENTUM_WEAKENED = "momentum_weakened"
    MOMENTUM_IMPROVED = "momentum_improved"
    EXIT_WATCH_ACTIVATED = "exit_watch_activated"
    EXIT_WATCH_CLEARED = "exit_watch_cleared"
    CONFIDENCE_INCREASED = "confidence_increased"
    CONFIDENCE_DECREASED = "confidence_decreased"
    FIRST_ANALYSED = "first_analysed"

    # --- Opportunity Engine lifecycle (Sprint 4) ----------------------------
    # Added, never redefined: every kind above keeps the meaning it has always
    # had, and no existing detector emits any of the kinds below. The engine
    # writes through the same append-only repository, so the timeline, the
    # brief and the watchlist deltas pick these up with no changes.
    OPPORTUNITY_OPENED = "opportunity_opened"
    OPPORTUNITY_CONFIRMED = "opportunity_confirmed"
    OPPORTUNITY_EXPIRING = "opportunity_expiring"
    OPPORTUNITY_CLOSED = "opportunity_closed"
    OPPORTUNITY_ARCHIVED = "opportunity_archived"
    SIGNAL_ADDED = "signal_added"
    SIGNAL_CONFIRMED = "signal_confirmed"
    SIGNAL_EXPIRED = "signal_expired"
    #: The signal's claim came true — the predicted transition happened.
    SIGNAL_REALISED = "signal_realised"
    #: The transition the signal reported reversed. For a factual signal this
    #: is a correction, not a failed prediction (see `opportunities/outcomes`).
    SIGNAL_INVALIDATED = "signal_invalidated"


class EventSeverity(enum.StrEnum):
    INFO = "info"
    NOTABLE = "notable"
    URGENT = "urgent"


class Watchlist(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A named list belonging to one user."""

    __tablename__ = "watchlists"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str | None] = mapped_column(String(280), nullable=True)

    #: Which event kinds should interrupt the user, as a list of EventKind
    #: values. Empty means "record everything, interrupt for nothing" — the
    #: default, because a system that notifies by default gets muted by default.
    alert_on: Mapped[list[str]] = mapped_column(
        JSONB, default=list, server_default="[]", nullable=False
    )

    __table_args__ = (
        # One name per user. Two lists called "Recovery" is a bug the user
        # cannot see until they add to the wrong one.
        UniqueConstraint("user_id", "name", name="uq_watchlists_user_name"),
        Index("ix_watchlists_user", "user_id"),
    )


class WatchlistItem(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """One token on one list, with the reason it was added."""

    __tablename__ = "watchlist_items"

    watchlist_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("watchlists.id", ondelete="CASCADE"), nullable=False
    )
    mint_address: Mapped[str] = mapped_column(String(44), nullable=False)

    #: Free text from the user. The one field on this platform whose contents
    #: LETZMOON has no opinion about.
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    #: State at the moment of adding, so the timeline can answer "what has
    #: changed since I started watching this?" without re-deriving history.
    added_mission_state: Mapped[str | None] = mapped_column(String(32), nullable=True)
    added_priority: Mapped[str | None] = mapped_column(String(16), nullable=True)
    added_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)

    __table_args__ = (
        UniqueConstraint("watchlist_id", "mint_address", name="uq_watchlist_items_mint"),
        Index("ix_watchlist_items_mint", "mint_address"),
        Index("ix_watchlist_items_list", "watchlist_id"),
    )


class AnalystReadingCache(Base, UUIDPrimaryKeyMixin):
    """The last observed state per token. Mutable, one row per mint.

    Exists so change detection is a diff against one row rather than a re-run
    of the whole universe. Without it, "what changed?" would mean analysing
    23,000 projects twice on every cycle.

    Deliberately narrow: only the fields events are derived from. The full
    readings are recomputable from stored observations at any time — the
    analysts are pure — so caching them would be duplicated state that could
    drift from its source.
    """

    __tablename__ = "analyst_reading_cache"

    mint_address: Mapped[str] = mapped_column(String(44), unique=True, nullable=False)

    mission_state: Mapped[str | None] = mapped_column(String(32), nullable=True)
    research_priority: Mapped[str | None] = mapped_column(String(16), nullable=True)
    combined_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    liquidity_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    momentum_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    risk_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    clone_risk: Mapped[str | None] = mapped_column(String(16), nullable=True)
    exit_severity: Mapped[str | None] = mapped_column(String(16), nullable=True)

    #: Warning codes present at the last observation, so added/removed warnings
    #: are a set difference rather than a re-derivation.
    warning_codes: Mapped[list[str]] = mapped_column(
        JSONB, default=list, server_default="[]", nullable=False
    )

    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (Index("ix_reading_cache_observed", observed_at.desc()),)


class IntelligenceEvent(Base, UUIDPrimaryKeyMixin):
    """One meaningful change. Append-only, never updated.

    Carries both sides of the change and the analyst that detected it, so the
    UI can render "Liquidity Intelligence: 34 → 61" without asking the server
    what it meant. An event that only said "something improved" would be a
    notification rather than intelligence.
    """

    __tablename__ = "intelligence_events"

    mint_address: Mapped[str] = mapped_column(String(44), nullable=False)

    kind: Mapped[EventKind] = mapped_column(
        Enum(
            EventKind,
            name="event_kind",
            native_enum=True,
            validate_strings=True,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=False,
    )
    severity: Mapped[EventSeverity] = mapped_column(
        Enum(
            EventSeverity,
            name="event_severity",
            native_enum=True,
            validate_strings=True,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=False,
    )

    #: Which analyst detected it. Null for events derived from the ensemble.
    analyst: Mapped[str | None] = mapped_column(String(16), nullable=True)

    previous_value: Mapped[str | None] = mapped_column(String(64), nullable=True)
    current_value: Mapped[str | None] = mapped_column(String(64), nullable=True)

    #: A finished sentence, rendered server-side like every other explanation
    #: on this platform.
    summary: Mapped[str] = mapped_column(String(400), nullable=False)

    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        # The dominant read: "what changed for this token, newest first".
        Index("ix_events_mint_occurred", "mint_address", occurred_at.desc()),
        # And the personal brief: "everything since a timestamp".
        Index("ix_events_occurred", occurred_at.desc()),
        # Deduplication. The same change must not be recorded twice if a cycle
        # runs twice, so a kind can occur once per token per second.
        UniqueConstraint("mint_address", "kind", "occurred_at", name="uq_events_mint_kind_at"),
    )
