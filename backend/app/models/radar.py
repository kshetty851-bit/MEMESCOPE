"""Radar persistence.

Three tables, each with a different mutability contract:

* `radar_tokens` — one row per token ever detected. The **first-detection block
  is written once and never updated**, which is what makes the track record
  trustworthy. Current/peak fields move.
* `radar_snapshots` — append-only history of scores over time.
* `radar_achievements` — append-only milestones. Never deleted, never revoked.

Nothing is ever removed. A failed opportunity stays on the record beside a
successful one, because a track record that quietly drops its losers is
marketing rather than evidence.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
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
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

#: Prices span many orders of magnitude on this market; the scale matches
#: `token_market_snapshots.price_usd` so a value can round-trip unchanged.
_PRICE = Numeric(38, 18)
_MONEY = Numeric(24, 4)
_SCORE = Numeric(5, 2)
_MULTIPLE = Numeric(20, 6)


class RadarToken(Base):
    """A project the Radar has detected, and how it has performed since.

    The `first_*` columns are the reason this table exists. They are written on
    detection and never touched again — every return the platform reports is
    measured from them, never from the token's launch.
    """

    __tablename__ = "radar_tokens"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    token_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("discovered_tokens.id", ondelete="CASCADE"),
        nullable=False,
    )
    mint_address: Mapped[str] = mapped_column(String(44), nullable=False, unique=True)

    # --- First detection: write once, never update --------------------------
    first_detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    first_price: Mapped[Decimal | None] = mapped_column(_PRICE)
    first_market_cap: Mapped[Decimal | None] = mapped_column(_MONEY)
    first_liquidity: Mapped[Decimal | None] = mapped_column(_MONEY)
    first_volume_24h: Mapped[Decimal | None] = mapped_column(_MONEY)
    #: Declared but not collected — the platform indexes no holder data. Kept as
    #: a column so that adding a provider backfills into a shape that exists.
    first_holder_count: Mapped[int | None] = mapped_column(Integer)
    first_opportunity_score: Mapped[Decimal] = mapped_column(_SCORE, nullable=False)
    first_confidence: Mapped[Decimal] = mapped_column(_SCORE, nullable=False)
    #: Why it was detected, as reason codes. Frozen alongside the other first_*
    #: values so the original rationale survives later re-scoring.
    detection_reason: Mapped[list[str]] = mapped_column(
        JSONB().with_variant(JSON(), "sqlite"), nullable=False, default=list
    )
    category: Mapped[str] = mapped_column(String(32), nullable=False)

    # --- Current state: updated every evaluation -----------------------------
    current_price: Mapped[Decimal | None] = mapped_column(_PRICE)
    current_market_cap: Mapped[Decimal | None] = mapped_column(_MONEY)
    current_liquidity: Mapped[Decimal | None] = mapped_column(_MONEY)
    current_opportunity_score: Mapped[Decimal] = mapped_column(_SCORE, nullable=False)
    current_confidence: Mapped[Decimal] = mapped_column(_SCORE, nullable=False)
    current_category: Mapped[str] = mapped_column(String(32), nullable=False)

    # --- Peak since detection ------------------------------------------------
    #: Highest price observed *after* detection. Monotonic by construction: the
    #: repository only raises it, so a later crash cannot erase a peak that
    #: genuinely happened.
    peak_price: Mapped[Decimal | None] = mapped_column(_PRICE)
    peak_market_cap: Mapped[Decimal | None] = mapped_column(_MONEY)
    #: The rest of the observation the peak price came from. Added in Sprint 28
    #: because `peak_market_cap` was written only when the peak happened to be
    #: the *current* price: a peak raised from a between-sweeps high left the
    #: market cap behind, and 6 of 88 rows ended up with `peak_price` above
    #: `current_price` while `peak_market_cap` equalled `current_market_cap`.
    #:
    #: The snapshot holding the high already carries these figures, so reading
    #: them is not inventing. **Every peak_* column is written from exactly one
    #: observation, together, or none of them is.**
    peak_liquidity: Mapped[Decimal | None] = mapped_column(_MONEY)
    peak_volume_24h: Mapped[Decimal | None] = mapped_column(_MONEY)
    #: When the observation behind the peak was *captured*, as distinct from
    #: `peak_at`, which is when the sweep noticed it.
    peak_observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    peak_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    peak_multiple: Mapped[Decimal | None] = mapped_column(_MULTIPLE)
    current_multiple: Mapped[Decimal | None] = mapped_column(_MULTIPLE)

    #: False once the token stops being evaluated (delisted, no longer indexed).
    #: It stays on the record either way — this only separates the live Radar
    #: from the historical one.
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    model_version: Mapped[str] = mapped_column(String(32), nullable=False)
    last_evaluated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("ix_radar_tokens_category", "current_category"),
        Index("ix_radar_tokens_score", "current_opportunity_score"),
        Index("ix_radar_tokens_detected", "first_detected_at"),
        # The leaderboard's ordering. Partial on active rows because that is
        # what the default Radar view asks for.
        # Partial on active rows: the default Radar view asks only for those,
        # and the historical record is queried by other paths.
        Index(
            "ix_radar_tokens_peak_multiple",
            "peak_multiple",
            postgresql_where=text("is_active"),
        ),
    )


class RadarSnapshot(Base):
    """Append-only score history.

    Written on material change rather than every evaluation, for the same
    reason `token_score_history` is: a 30-second cadence would otherwise write
    thousands of near-identical rows per token per day and drown the timeline.
    """

    __tablename__ = "radar_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    radar_token_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("radar_tokens.id", ondelete="CASCADE"), nullable=False
    )
    mint_address: Mapped[str] = mapped_column(String(44), nullable=False)
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    price: Mapped[Decimal | None] = mapped_column(_PRICE)
    market_cap: Mapped[Decimal | None] = mapped_column(_MONEY)
    liquidity: Mapped[Decimal | None] = mapped_column(_MONEY)
    volume_24h: Mapped[Decimal | None] = mapped_column(_MONEY)
    holder_count: Mapped[int | None] = mapped_column(Integer)

    opportunity_score: Mapped[Decimal] = mapped_column(_SCORE, nullable=False)
    confidence: Mapped[Decimal] = mapped_column(_SCORE, nullable=False)
    coverage: Mapped[Decimal] = mapped_column(_SCORE, nullable=False)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    #: Per-dimension breakdown, so a historical score can be explained without
    #: recomputing it. The equivalent of `token_score_history.components`.
    dimensions: Mapped[dict[str, object]] = mapped_column(
        JSONB().with_variant(JSON(), "sqlite"), nullable=False, default=dict
    )
    reasons: Mapped[list[str]] = mapped_column(
        JSONB().with_variant(JSON(), "sqlite"), nullable=False, default=list
    )
    model_version: Mapped[str] = mapped_column(String(32), nullable=False)

    __table_args__ = (
        Index("ix_radar_snapshots_token_time", "radar_token_id", "captured_at"),
        Index("ix_radar_snapshots_mint_time", "mint_address", "captured_at"),
    )


class RadarAchievement(Base):
    """A return milestone, recorded permanently.

    Unique per (token, tier): an achievement is reached once. Never deleted —
    a token that touched 10x and returned to zero has still touched 10x, and
    the record says both things.
    """

    __tablename__ = "radar_achievements"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    radar_token_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("radar_tokens.id", ondelete="CASCADE"), nullable=False
    )
    mint_address: Mapped[str] = mapped_column(String(44), nullable=False)
    #: "2x", "10x", … Matches `achievements.TIERS`, which is append-only.
    tier: Mapped[str] = mapped_column(String(16), nullable=False)
    multiple: Mapped[Decimal] = mapped_column(_MULTIPLE, nullable=False)

    achieved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    price_at_achievement: Mapped[Decimal | None] = mapped_column(_PRICE)
    market_cap_at_achievement: Mapped[Decimal | None] = mapped_column(_MONEY)
    #: How long it took from detection, for the leaderboard.
    days_to_achieve: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))

    __table_args__ = (
        UniqueConstraint("radar_token_id", "tier", name="uq_radar_achievement_tier"),
        Index("ix_radar_achievements_tier", "tier"),
        Index("ix_radar_achievements_time", "achieved_at"),
    )
