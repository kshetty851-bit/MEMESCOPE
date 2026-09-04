"""Market enrichment models.

Two tables with very different access patterns, kept separate on purpose:

  * `token_market_snapshots` is append-only history. It is written constantly
    and never updated, so it stays cheap to insert into and safe to partition
    by time later.
  * `token_enrichment_state` is the scheduler's work queue: one mutable row per
    token holding when it is next due. Keeping this out of the snapshot table
    means the hot "what is due?" query touches a small table, and keeping it out
    of `discovered_tokens` leaves discovery concerns undisturbed.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    desc,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.token import DiscoveredToken

# Prices for meme coins routinely run to 1e-9 or smaller, and market caps to
# 1e10. Numeric (not float) because these are money: binary floats cannot
# represent decimal fractions exactly and the error compounds across snapshots.
PRICE_PRECISION = Numeric(38, 18)
MONEY_PRECISION = Numeric(24, 4)


# Lanes of `TokenEnrichmentState.priority`. The claim query orders on this
# column descending, so the numbers are the scheduling contract: a higher lane
# always claims before a lower one. Open paper positions, live opportunities and
# visible Radar ranks live in DISPLAY — permanently above NURSERY, so a
# speculative fresh token can never starve committed capital of its next quote.
LANE_NORMAL = 0
#: A token in its first minutes of life, prioritised *because it is new* —
#: discovery itself qualifies it, before any observation exists. This is what
#: breaks the circularity of "needs observations to be interesting, needs to be
#: interesting to be observed". Bounded and temporary: membership is trimmed to
#: `ENRICHMENT_NURSERY_MAX_TOKENS` and evicted after the FRESH age window.
LANE_NURSERY = 1
#: What the product is actively displaying (Radar ranks, open opportunities,
#: open paper positions). Was `1` before the nursery existed.
LANE_DISPLAY = 2
#: One-shot post-admission quote acquisition. Cleared after a single attempt.
#: Was `2` before the nursery existed.
LANE_TRACK_RECORD = 3


class EnrichmentStatus(enum.StrEnum):
    """Scheduling state of a token."""

    ACTIVE = "active"
    # Parked after repeated failures. Retained rather than deleted so the
    # backlog is visible and can be requeued deliberately.
    DEAD_LETTER = "dead_letter"
    PAUSED = "paused"


class TradingStatus(enum.StrEnum):
    """Whether the token is tradeable according to the provider."""

    # Provider has no pool indexed yet — normal for a token seconds old.
    UNKNOWN = "unknown"
    TRADING = "trading"
    # Indexed but with no meaningful liquidity left.
    INACTIVE = "inactive"


class TokenMarketSnapshot(Base, UUIDPrimaryKeyMixin):
    """One immutable observation of a token's market at a point in time."""

    __tablename__ = "token_market_snapshots"

    token_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("discovered_tokens.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Denormalised so history queries never need a join back to the token.
    mint_address: Mapped[str] = mapped_column(String(44), nullable=False)

    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    price_usd: Mapped[Decimal | None] = mapped_column(PRICE_PRECISION, nullable=True)
    price_native: Mapped[Decimal | None] = mapped_column(PRICE_PRECISION, nullable=True)
    liquidity_usd: Mapped[Decimal | None] = mapped_column(MONEY_PRECISION, nullable=True)
    fully_diluted_valuation: Mapped[Decimal | None] = mapped_column(
        MONEY_PRECISION, nullable=True
    )
    market_cap: Mapped[Decimal | None] = mapped_column(MONEY_PRECISION, nullable=True)

    volume_24h: Mapped[Decimal | None] = mapped_column(MONEY_PRECISION, nullable=True)
    volume_1h: Mapped[Decimal | None] = mapped_column(MONEY_PRECISION, nullable=True)
    volume_5m: Mapped[Decimal | None] = mapped_column(MONEY_PRECISION, nullable=True)

    buy_count_24h: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sell_count_24h: Mapped[int | None] = mapped_column(Integer, nullable=True)

    dex_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    trading_pair: Mapped[str | None] = mapped_column(String(96), nullable=True)
    pool_address: Mapped[str | None] = mapped_column(String(44), nullable=True)

    trading_status: Mapped[TradingStatus] = mapped_column(
        Enum(
            TradingStatus,
            name="trading_status",
            native_enum=True,
            validate_strings=True,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        default=TradingStatus.UNKNOWN,
        server_default=TradingStatus.UNKNOWN.value,
        nullable=False,
    )
    is_verified: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )
    # --- ingest data-quality firewall (V4 Phase 2) ------------------------
    # The provider's print is preserved untouched in `price_usd`; these
    # columns only ANNOTATE it. A flagged row is excluded from peaks,
    # features, outcomes and wallet reads — but remains fully auditable.
    suspect: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )
    #: Why the row was flagged: price_band_high / price_band_low /
    #: liquidity_jump / pair_switch. NULL on clean rows.
    suspect_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    #: The rolling-median baseline the print was compared against, recorded so
    #: the judgement can be re-audited without reconstructing the window.
    baseline_price_usd: Mapped[Decimal | None] = mapped_column(
        PRICE_PRECISION, nullable=True
    )

    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    # Round-trip time of the provider call that produced this row.
    provider_latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    token: Mapped[DiscoveredToken] = relationship(lazy="raise")

    __table_args__ = (
        # The dominant read: "history for this token, newest first". Also serves
        # the DISTINCT ON that resolves each token's latest snapshot.
        Index(
            "ix_snapshots_mint_captured_desc",
            "mint_address",
            captured_at.desc(),
        ),
        Index("ix_snapshots_token_captured_desc", "token_id", captured_at.desc()),
        # Trending scans recent rows across all tokens.
        Index("ix_snapshots_captured_at", captured_at.desc()),
    )


class TokenEnrichmentState(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Per-token scheduling state. Exactly one row per discovered token."""

    __tablename__ = "token_enrichment_state"

    token_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("discovered_tokens.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    mint_address: Mapped[str] = mapped_column(
        String(44), unique=True, index=True, nullable=False
    )

    status: Mapped[EnrichmentStatus] = mapped_column(
        Enum(
            EnrichmentStatus,
            name="enrichment_status",
            native_enum=True,
            validate_strings=True,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        default=EnrichmentStatus.ACTIVE,
        server_default=EnrichmentStatus.ACTIVE.value,
        nullable=False,
    )

    # The claim query orders by this; it is the single hottest column here.
    next_refresh_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_success_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    consecutive_failures: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    total_refreshes: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    total_snapshots: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    # Provider indexed nothing for this mint on the last attempt. Tracked
    # separately from a failure: "no pool yet" is expected, not an error.
    consecutive_empty: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )

    #: When this token stopped being tradeable, or NULL while it still is.
    #:
    #: Set once, when a run of empty provider results confirms a pool that
    #: existed has gone; cleared if the token ever returns. Durable on purpose:
    #: the `INACTIVE` snapshot that marks the same event is written once and
    #: then expires with retention, so it cannot answer "was this alive at time
    #: T" for any T outside the window it happens to sit in.
    #:
    #: A query for a PRICE silently excludes dead tokens, which is how a
    #: population that returns -2.3% measured as +16.4%. This column is what
    #: lets a measurement count the deaths instead of dropping them.
    delisted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    last_error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Which adaptive tier produced the current interval; logged for tuning.
    tier: Mapped[str | None] = mapped_column(String(16), nullable=True)
    #: Lane, not a queue. See the `LANE_*` constants above: 0 is the ordinary
    #: adaptive population, 1 the fresh-token nursery, 2 what the product is
    #: actively displaying, 3 one-shot Track Record quote acquisition.
    #:
    #: This exists because the claim query orders by `next_refresh_at` and the
    #: backlog reached 36,154 tokens: a tracked token asking for a 15-second
    #: refresh queued behind 36,000 rows that were hours overdue, so its p95
    #: observed gap was 106 minutes. Sorting on this column first is what lets
    #: the lane jump the backlog **without a second queue or a second worker**.
    priority: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default=text("0")
    )

    token: Mapped[DiscoveredToken] = relationship(lazy="raise")

    __table_args__ = (
        # The claim query: WHERE status='active' AND next_refresh_at <= now()
        # ORDER BY next_refresh_at. A composite index keeps it index-only.
        Index("ix_enrichment_due", "status", "next_refresh_at"),
        # The claim query after Sprint 28: WHERE status='active' AND
        # next_refresh_at <= now() ORDER BY priority DESC, next_refresh_at.
        # Without this the priority sort degrades into a heap sort over the
        # whole backlog on every claim.
        Index(
            "ix_enrichment_priority_due",
            "status",
            desc("priority"),
            "next_refresh_at",
        ),
    )

class TokenMarketCandle1h(Base):
    """Hourly downsampled OHLCV candles for long-term charting."""

    __tablename__ = "token_market_candles_1h"

    mint_address: Mapped[str] = mapped_column(String(44), primary_key=True, nullable=False)
    # The start of the hourly bucket
    bucket: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True, nullable=False)

    open_price: Mapped[Decimal | None] = mapped_column(PRICE_PRECISION, nullable=True)
    high_price: Mapped[Decimal | None] = mapped_column(PRICE_PRECISION, nullable=True)
    low_price: Mapped[Decimal | None] = mapped_column(PRICE_PRECISION, nullable=True)
    close_price: Mapped[Decimal | None] = mapped_column(PRICE_PRECISION, nullable=True)
    
    close_market_cap: Mapped[Decimal | None] = mapped_column(MONEY_PRECISION, nullable=True)
    close_liquidity_usd: Mapped[Decimal | None] = mapped_column(MONEY_PRECISION, nullable=True)

    volume: Mapped[Decimal | None] = mapped_column(MONEY_PRECISION, nullable=True)

    __table_args__ = (
        Index("ix_candles_1h_mint_bucket_desc", "mint_address", bucket.desc()),
    )
