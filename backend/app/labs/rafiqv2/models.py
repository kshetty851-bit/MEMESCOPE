"""Rafiqv2's own tables. Prefix `rafiqv2_`; nothing else writes them.

No balance is stored: cash and equity derive from the position rows, so they
cannot drift from them. A book's mechanism state — ratchet, death-rate window,
day-open equity, learner evidence — is one JSON document on its book row,
because it is read and written as a whole once per tick.

On the platform's `Base` and imported in `app.models`, for the reason the
Rafiq Lab found the hard way: tables `alembic` cannot see come out of
autogenerate as `drop_table`.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    false,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

_PRICE = Numeric(38, 18)
_MONEY = Numeric(24, 4)
_QUANTITY = Numeric(48, 18)
_RATIO = Numeric(10, 4)


class Rafiqv2Book(Base):
    """One book, created at the lab's first tick and never re-created."""

    __tablename__ = "rafiqv2_books"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    code: Mapped[str] = mapped_column(String(4), nullable=False, unique=True)
    starting_equity: Mapped[Decimal] = mapped_column(_MONEY, nullable=False)
    #: The rules this book opened under. A mismatch stops the runner.
    config_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    activated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    state: Mapped[dict] = mapped_column(JSONB, nullable=False,
                                        server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
        onupdate=func.now())


class Rafiqv2Position(Base):
    """One simulated trade. The entry block and the learned parameters it
    opened under are written once; a position is judged by the rule it was
    opened under, never by one learned later."""

    __tablename__ = "rafiqv2_positions"
    __table_args__ = (
        UniqueConstraint("book_id", "mint_address", name="uq_rafiqv2_positions_book_mint"),
        Index("ix_rafiqv2_positions_book_status", "book_id", "status"),
        Index("ix_rafiqv2_positions_book_closed_at", "book_id", "closed_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    book_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("rafiqv2_books.id", ondelete="CASCADE"),
        nullable=False)
    mint_address: Mapped[str] = mapped_column(String(44), nullable=False)
    #: The Radar's token id, kept so a tick need not look it up again.
    token_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    #: As wide as `discovered_tokens.symbol`, so no symbol can fail an insert.
    symbol: Mapped[str | None] = mapped_column(String(64))
    detected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    #: What was paid per token after fee and impact. Every multiple is of this.
    entry_price: Mapped[Decimal] = mapped_column(_PRICE, nullable=False)
    entry_observed_price: Mapped[Decimal] = mapped_column(_PRICE, nullable=False)
    quantity: Mapped[Decimal] = mapped_column(_QUANTITY, nullable=False)
    cost_basis: Mapped[Decimal] = mapped_column(_MONEY, nullable=False)
    entry_liquidity_usd: Mapped[Decimal | None] = mapped_column(_MONEY)
    entry_market_cap_usd: Mapped[Decimal | None] = mapped_column(_MONEY)
    entry_impact_pct: Mapped[Decimal | None] = mapped_column(_RATIO)
    entry_score: Mapped[Decimal | None] = mapped_column(_RATIO)
    #: The two features `learning.py` says would unlock "which token to buy",
    #: read point-in-time at the decision by the Rafiq Lab's feed.
    entry_top10_holder_pct: Mapped[Decimal | None] = mapped_column(Numeric(9, 4))
    entry_lp_locked: Mapped[bool | None] = mapped_column(Boolean)
    entry_features_error: Mapped[str | None] = mapped_column(String(64))

    #: The learner's parameters as read immediately before this entry.
    rug_strictness: Mapped[Decimal] = mapped_column(_RATIO, nullable=False)
    lock_giveback: Mapped[Decimal] = mapped_column(_RATIO, nullable=False)
    size_multiplier: Mapped[Decimal] = mapped_column(_RATIO, nullable=False)

    status: Mapped[str] = mapped_column(String(8), nullable=False,
                                        server_default=text("'open'"))
    peak_price: Mapped[Decimal] = mapped_column(_PRICE, nullable=False)
    last_mark_price: Mapped[Decimal | None] = mapped_column(_PRICE)
    #: Depth of the last tradeable reading; 0 once the pool reads gone.
    last_mark_liquidity_usd: Mapped[Decimal | None] = mapped_column(_MONEY)
    last_evaluated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    scaled_out: Mapped[bool] = mapped_column(Boolean, nullable=False,
                                             server_default=false())
    scaled_out_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    scale_out_price: Mapped[Decimal | None] = mapped_column(_PRICE)
    #: Share still held; on a closed row, the share its final exit sold.
    fraction_open: Mapped[Decimal] = mapped_column(_RATIO, nullable=False,
                                                   server_default=text("1"))
    #: Proceeds of the scale-out; included in `exit_proceeds_usd` once closed.
    realised_usd: Mapped[Decimal] = mapped_column(_MONEY, nullable=False,
                                                  server_default=text("0"))

    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    exit_price: Mapped[Decimal | None] = mapped_column(_PRICE)
    exit_proceeds_usd: Mapped[Decimal | None] = mapped_column(_MONEY)
    exit_reason: Mapped[str | None] = mapped_column(String(16))
    exit_evidence: Mapped[str | None] = mapped_column(Text)
    #: The final sale filled at a tenth of entry or less, or the pool was gone.
    died: Mapped[bool | None] = mapped_column(Boolean)
    #: Best tradeable print in the hour after exit, over `entry_price`.
    forward_peak_multiple: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    #: When this trade was handed to `Learning.on_exit` (once).
    learning_recorded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
        onupdate=func.now())


class Rafiqv2Adjustment(Base):
    """Every parameter a book moved, and every halt it called, with why."""

    __tablename__ = "rafiqv2_adjustments"
    __table_args__ = (Index("ix_rafiqv2_adjustments_book_at", "book_id", "at"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    book_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("rafiqv2_books.id", ondelete="CASCADE"),
        nullable=False)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    parameter: Mapped[str] = mapped_column(String(32), nullable=False)
    old_value: Mapped[Decimal] = mapped_column(Numeric(24, 6), nullable=False)
    new_value: Mapped[Decimal] = mapped_column(Numeric(24, 6), nullable=False)
    sample_size: Mapped[int | None] = mapped_column(Integer)
    z_score: Mapped[Decimal | None] = mapped_column(Numeric(10, 3))
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now())
