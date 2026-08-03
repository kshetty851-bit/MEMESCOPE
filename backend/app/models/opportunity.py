"""Opportunity Engine persistence.

Two tables, both additive. Nothing in `radar_tokens`, `token_scores`,
`token_market_snapshots`, `discovered_tokens` or `intelligence_events` is
touched.

## Why two tables and not one

ARCHITECTURE_DECISIONS.md AD-05 proposed carrying the opportunity header on
`radar_tokens`. That is not reachable without changing Radar behaviour, which
Sprint 4 forbids:

  * `uq_radar_tokens_mint_address` is unique on `mint_address` **alone**, and
    the Radar's detector inserts with `ON CONFLICT (mint_address) DO NOTHING`.
    Widening it to `(mint_address, generation)` breaks that insert outright.
  * Eight columns on `radar_tokens` are `NOT NULL` and belong to the Radar's
    scoring model — `first_opportunity_score`, `current_category`,
    `model_version` and the rest. An opportunity raised by a signal provider
    has none of them, and inventing values would put fabricated scores on the
    Radar board.

The header therefore gets its own table. It duplicates no token data: identity
lives in `discovered_tokens` and is referenced by foreign key, with
`mint_address` denormalised for the same reason every other table here
denormalises it — so per-token reads need no join.

## The two guarantees enforced in the schema, not in code

  * **One live opportunity per token.** A partial unique index over the live
    statuses. Two workers racing on the same mint cannot both win.
  * **No duplicate active signal.** Unique on
    `(opportunity_id, signal_type, provider_id)`. A re-detection updates the
    row it collides with; it never inserts a second.

Both follow the scanner's precedent: the database is the guarantee and the
application check is an optimisation.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.opportunities.models import (
    LIVE_STATUSES,
    OpportunityPriority,
    OpportunityStage,
    OpportunityStatus,
    SignalStatus,
)

#: 0-100 with two decimals, matching `token_scores` and `radar_tokens`.
_SCORE = Numeric(5, 2)

#: Rendered into the partial index predicate. Derived from the enum rather than
#: written out, so adding a live status cannot leave the index behind.
_LIVE_STATUS_SQL = ", ".join(f"'{status.value}'" for status in sorted(LIVE_STATUSES))


class Opportunity(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """One token's currently-interesting moment, in one generation.

    `detected_at` and `generation` are written once and never updated. Every
    claim the platform makes about how an opportunity performed is measured
    from them, which is the same discipline `radar_tokens.first_*` holds.
    """

    __tablename__ = "opportunities"

    token_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("discovered_tokens.id", ondelete="CASCADE"),
        nullable=False,
    )
    mint_address: Mapped[str] = mapped_column(String(44), nullable=False)

    #: Increments each time a token opens a *new* opportunity after a previous
    #: one was archived. Never reused, so two separate calls on the same token
    #: stay separately measurable in the permanent record.
    generation: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )

    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=OpportunityStatus.NEW.value
    )
    stage: Mapped[str] = mapped_column(
        String(32), nullable=False, default=OpportunityStage.UNKNOWN.value
    )

    #: 0-100, recomputed on every evaluation. `priority_band` is the coarse
    #: label; the number is what ranks and the band is what survives a
    #: weighting change.
    priority: Mapped[Decimal] = mapped_column(
        _SCORE, nullable=False, default=Decimal(0), server_default="0"
    )
    priority_band: Mapped[str] = mapped_column(
        String(16), nullable=False, default=OpportunityPriority.LOW.value
    )
    #: The highest confidence among live signals. Denormalised so the eventual
    #: board can rank without joining every signal row.
    confidence: Mapped[Decimal] = mapped_column(
        _SCORE, nullable=False, default=Decimal(0), server_default="0"
    )

    # --- Write once, never update -------------------------------------------
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    # --- Updated as the opportunity lives ------------------------------------
    last_confirmed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    #: When the opportunity entered EXPIRING. The grace window is measured from
    #: here, and a re-detection inside it revives the opportunity in place
    #: rather than minting a new generation.
    expiring_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        # One opportunity per token per generation, always.
        UniqueConstraint("mint_address", "generation", name="uq_opportunities_mint_gen"),
        # ...and at most one of them live. This is the AD-09 guarantee: two
        # workers racing on the same mint cannot both open an opportunity.
        Index(
            "uq_opportunities_live_mint",
            "mint_address",
            unique=True,
            postgresql_where=text(f"status IN ({_LIVE_STATUS_SQL})"),
        ),
        # The dominant read once a board exists: live, best first.
        Index(
            "ix_opportunities_live_priority",
            text("priority DESC"),
            postgresql_where=text(f"status IN ({_LIVE_STATUS_SQL})"),
        ),
        # The expiry sweep's claim query.
        Index("ix_opportunities_status_confirmed", "status", "last_confirmed_at"),
        Index("ix_opportunities_detected", detected_at.desc()),
        CheckConstraint("generation >= 1", name="ck_opportunities_generation_positive"),
    )


class OpportunitySignal(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """One provider's claim about one transition, with its own expiry.

    Rows rather than a JSONB array on the opportunity, because each signal has
    an independent TTL, an independent confirmation count and its own dedup
    key. Expressing that inside an array would mean scanning and rewriting it on
    every expiry sweep.
    """

    __tablename__ = "opportunity_signals"

    opportunity_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("opportunities.id", ondelete="CASCADE"),
        nullable=False,
    )
    #: Denormalised from the parent, so "every signal for this token" needs no
    #: join and the event writer has the mint without a lookup.
    mint_address: Mapped[str] = mapped_column(String(44), nullable=False)

    signal_type: Mapped[str] = mapped_column(String(48), nullable=False)
    provider_id: Mapped[str] = mapped_column(String(48), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=SignalStatus.PENDING.value
    )
    severity: Mapped[str] = mapped_column(String(16), nullable=False)

    #: The provider's own claim about the transition, 0-100.
    strength: Mapped[Decimal] = mapped_column(_SCORE, nullable=False)
    #: What the engine derived from strength, confirmation, corroboration,
    #: evidence and freshness. Never supplied by a provider.
    confidence: Mapped[Decimal] = mapped_column(
        _SCORE, nullable=False, default=Decimal(0), server_default="0"
    )
    #: How many times this signal has been observed. 1 is a first sighting, and
    #: a first sighting is not yet on any board.
    confirmations: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    #: Observations in the window it was derived from. The evidence gate reads
    #: this, so a thinly-evidenced signal cannot rank.
    observations: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )

    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_confirmed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    #: The snapshot timestamp the claim was derived from. Re-running detection
    #: over the same observation must not count as a fresh confirmation, and
    #: this is what makes that check possible.
    observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    #: Stable identifiers. Prose is rendered from these at read time and never
    #: stored, so wording changes never require a migration (AD-07).
    reason_codes: Mapped[list[str]] = mapped_column(
        JSONB, default=list, server_default="[]", nullable=False
    )
    #: The named figures behind the claim, as an ordered list of
    #: `{label, value, detail}`. Auditable, and enough for a client to render
    #: the explanation without inventing the sentence.
    evidence: Mapped[list[dict[str, str | None]]] = mapped_column(
        JSONB, default=list, server_default="[]", nullable=False
    )

    __table_args__ = (
        # No duplicate signal: one row per (opportunity, type, provider). A
        # re-detection updates this row rather than inserting a second, which is
        # how "Near Graduation + Pre-Breakout + Liquidity Surge" stays one
        # opportunity with three signals.
        UniqueConstraint(
            "opportunity_id",
            "signal_type",
            "provider_id",
            name="uq_opportunity_signals_dedupe",
        ),
        # The expiry sweep: "which live signals are past their TTL?".
        Index("ix_opportunity_signals_expiry", "status", "expires_at"),
        Index("ix_opportunity_signals_opportunity", "opportunity_id"),
        Index("ix_opportunity_signals_mint", "mint_address"),
        CheckConstraint("confirmations >= 1", name="ck_opportunity_signals_confirmations"),
    )
