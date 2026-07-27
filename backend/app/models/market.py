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
    String,
    func,
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

    last_error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Which adaptive tier produced the current interval; logged for tuning.
    tier: Mapped[str | None] = mapped_column(String(16), nullable=True)

    token: Mapped[DiscoveredToken] = relationship(lazy="raise")

    __table_args__ = (
        # The claim query: WHERE status='active' AND next_refresh_at <= now()
        # ORDER BY next_refresh_at. A composite index keeps it index-only.
        Index("ix_enrichment_due", "status", "next_refresh_at"),
    )
