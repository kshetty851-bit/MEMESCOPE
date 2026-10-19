"""Isolated FOMO Lab ledger. No real-wallet or existing paper-wallet writes."""

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
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

MONEY = Numeric(24, 4)
QTY = Numeric(48, 18)
PRICE = Numeric(38, 18)


class FomoBook(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "fomo_books"

    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    #: "main" copies every fresh buy; "consensus" (2026-10-19) only a buy a
    #: different ranked trader made in the hour before. Same roster and feed.
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="main",
                                      server_default="main")
    cash_usd: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    roster_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_captured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    feed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    feed_error: Mapped[str | None] = mapped_column(String(128))


class FomoLeader(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "fomo_leaders"

    book_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("fomo_books.id"), nullable=False
    )
    user_id: Mapped[str] = mapped_column(String(80), nullable=False)
    handle: Mapped[str] = mapped_column(String(100), nullable=False)
    wallet: Mapped[str] = mapped_column(String(64), nullable=False)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    pnl_24h_usd: Mapped[Decimal | None] = mapped_column(MONEY)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    follow_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ranked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    #: The newest transaction already read for this wallet: the next poll asks
    #: the node only for what came after it.
    last_signature: Mapped[str | None] = mapped_column(String(100))

    __table_args__ = (
        UniqueConstraint("book_id", "user_id", name="uq_fomo_leader_user"),
        Index("ix_fomo_leader_active", "book_id", "active", "rank"),
    )


class FomoPosition(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "fomo_positions"

    book_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("fomo_books.id"), nullable=False
    )
    leader_wallet: Mapped[str] = mapped_column(String(64), nullable=False)
    mint: Mapped[str] = mapped_column(String(64), nullable=False)
    buy_signature: Mapped[str] = mapped_column(String(96), nullable=False)
    leader_bought_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    entry_price_usd: Mapped[Decimal] = mapped_column(PRICE, nullable=False)
    quantity: Mapped[Decimal] = mapped_column(QTY, nullable=False)
    spent_usd: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    status: Mapped[str] = mapped_column(String(8), nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    exit_price_usd: Mapped[Decimal | None] = mapped_column(PRICE)
    proceeds_usd: Mapped[Decimal | None] = mapped_column(MONEY)
    last_value_usd: Mapped[Decimal | None] = mapped_column(MONEY)
    last_mark_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint(
            "book_id", "leader_wallet", "buy_signature", "mint", name="uq_fomo_position_buy"
        ),
        Index("ix_fomo_position_open", "book_id", "status", "leader_wallet", "mint"),
    )


class FomoSignal(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "fomo_signals"

    book_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("fomo_books.id"), nullable=False
    )
    leader_wallet: Mapped[str] = mapped_column(String(64), nullable=False)
    signature: Mapped[str] = mapped_column(String(96), nullable=False)
    mint: Mapped[str] = mapped_column(String(64), nullable=False)
    side: Mapped[str] = mapped_column(String(4), nullable=False)
    traded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    outcome: Mapped[str] = mapped_column(String(40), nullable=False)
    position_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("fomo_positions.id")
    )

    __table_args__ = (
        UniqueConstraint(
            "book_id", "leader_wallet", "signature", "mint", name="uq_fomo_signal_once"
        ),
        Index("ix_fomo_signal_recent", "book_id", "seen_at"),
    )
