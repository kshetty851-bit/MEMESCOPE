"""Two tables: what was locked, and what happened to it afterwards.

Deliberately not the graduation lab's schema. That one carries a book, arms
and rug verdicts; this carries observations, because nothing here has earned
the right to a strategy yet.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

#: EVM addresses are 42 characters. Sized like the Solana tables for one
#: reason: a shared helper that truncates would corrupt silently.
_ADDRESS = String(64)


class RhoodLock(Base):
    """One locker event on Robinhood Chain.

    `token` is the event's first indexed argument, verified by calling
    `symbol()` on it. `quote` is its first data word, WETH on every event seen.

    ONE ROW PER EVENT, held by the database on (tx_hash, log_index): the
    recorder re-reads an overlapping window every pass so a failure leaves no
    hole, and without this that overlap would duplicate every row.
    """

    __tablename__ = "rhood_locks"
    __table_args__ = (
        UniqueConstraint("tx_hash", "log_index", name="uq_rhood_locks_event"),
        Index("ix_rhood_locks_seen", "seen_at"),
        Index("ix_rhood_locks_token", "token"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    block_number: Mapped[int] = mapped_column(BigInteger, nullable=False)
    #: The block's own timestamp, not when we noticed. Every measurement of
    #: "how long after graduation" depends on this being the chain's clock.
    block_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    tx_hash: Mapped[str] = mapped_column(String(80), nullable=False)
    log_index: Mapped[int] = mapped_column(BigInteger, nullable=False)
    token: Mapped[str] = mapped_column(_ADDRESS, nullable=False)
    quote: Mapped[str | None] = mapped_column(_ADDRESS)
    symbol: Mapped[str | None] = mapped_column(String(64))
    name: Mapped[str | None] = mapped_column(String(128))
    #: When DexScreener says this token's DEEPEST pair was created. The whole
    #: question the recorder exists to answer is whether this is minutes before
    #: the lock (a graduation) or months (a re-lock of an old coin).
    pair_created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    #: PINNED at first sight and never re-chosen. One token had SEVEN pairs
    #: with liquidity from $1,146 to $157,675; re-picking between them is how
    #: the Solana books once fabricated $2,414 of profit.
    pair_address: Mapped[str | None] = mapped_column(_ADDRESS)
    pairs_seen: Mapped[int | None] = mapped_column(BigInteger)
    seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now())
    #: False once the token could not be priced at all, so a gap in the samples
    #: is never mistaken for a coin that went quiet.
    priced: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class RhoodSample(Base):
    """One reading of a locked token's pinned pair."""

    __tablename__ = "rhood_samples"
    __table_args__ = (
        Index("ix_rhood_samples_token_ts", "token", "ts"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    token: Mapped[str] = mapped_column(_ADDRESS, nullable=False)
    pair_address: Mapped[str | None] = mapped_column(_ADDRESS)
    ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now())
    price_usd: Mapped[Decimal | None] = mapped_column(Numeric(40, 18))
    price_native: Mapped[Decimal | None] = mapped_column(Numeric(40, 18))
    liquidity_usd: Mapped[Decimal | None] = mapped_column(Numeric(20, 2))
    fdv: Mapped[Decimal | None] = mapped_column(Numeric(20, 2))
    volume_m5_usd: Mapped[Decimal | None] = mapped_column(Numeric(20, 2))
    txns_m5_buys: Mapped[int | None] = mapped_column(BigInteger)
    txns_m5_sells: Mapped[int | None] = mapped_column(BigInteger)
