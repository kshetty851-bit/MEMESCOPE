"""The Momentum Lab's tables. Prefix `mom_`.

On the platform's `Base`, as every lab here is: a separate metadata makes
`alembic revision --autogenerate` emit `drop_table` for tables it can see in
the database and not in the model tree.

**Paper only.** Nothing in this package can reach a key, a signer or a chain.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Index, Integer, Numeric, String, func, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

_ADDRESS = String(64)
#: USD prices run from ~1e-8 (a billion-supply meme) to hundreds of dollars.
_PRICE = Numeric(36, 18)
_USD = Numeric(24, 4)
_RATIO = Numeric(18, 8)


class MomPair(Base):
    """One token of the universe, and the ONE pool it is watched on.

    The pool is pinned at admission and never changed while the token is in
    the universe: a candle series spliced across two pools is two instruments
    pretending to be one.
    """

    __tablename__ = "mom_pairs"
    __table_args__ = (Index("ix_mom_pairs_status", "status"),)

    pair_address: Mapped[str] = mapped_column(_ADDRESS, primary_key=True)
    mint: Mapped[str] = mapped_column(_ADDRESS, nullable=False, index=True)
    symbol: Mapped[str | None] = mapped_column(String(32))
    dex_id: Mapped[str | None] = mapped_column(String(32))
    quote_mint: Mapped[str] = mapped_column(_ADDRESS, nullable=False)
    #: When the token's market began (its first pool), which is what "older
    #: than seven days" is measured from.
    born_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    #: `active` is polled; `dropped` is not (unless a position is still open).
    status: Mapped[str] = mapped_column(String(12), nullable=False,
                                        server_default="active")
    drop_reason: Mapped[str | None] = mapped_column(String(24))
    #: Which Jupiter lists named it at the last refresh.
    lists: Mapped[list[str] | None] = mapped_column(ARRAY(String(24)))
    admitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    listed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    #: The newest sample, so a position has a mark and the next candle an open.
    last_price: Mapped[Decimal | None] = mapped_column(_PRICE)
    last_sample_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    liquidity_usd: Mapped[Decimal | None] = mapped_column(_USD)
    volume_h24: Mapped[Decimal | None] = mapped_column(_USD)
    change_h1: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    glitches: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")


class MomCandle(Base):
    """A five-minute candle, built from the lab's own fixed-cadence samples.

    Filed by MARKET time (fetch time minus the feed's lag). `open` is the last
    price before the bucket when that price is recent, so consecutive candles
    join; `volume_usd` is the pool's rolling five-minute volume at the bucket's
    last sample, `buys`/`sells` likewise.
    """

    __tablename__ = "mom_candles"

    pair_address: Mapped[str] = mapped_column(_ADDRESS, primary_key=True)
    start: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    open: Mapped[Decimal] = mapped_column(_PRICE, nullable=False)
    high: Mapped[Decimal] = mapped_column(_PRICE, nullable=False)
    low: Mapped[Decimal] = mapped_column(_PRICE, nullable=False)
    close: Mapped[Decimal] = mapped_column(_PRICE, nullable=False)
    volume_usd: Mapped[Decimal | None] = mapped_column(_USD)
    buys: Mapped[int | None] = mapped_column(Integer)
    sells: Mapped[int | None] = mapped_column(Integer)
    volume_h24: Mapped[Decimal | None] = mapped_column(_USD)
    liquidity_usd: Mapped[Decimal | None] = mapped_column(_USD)
    change_h24: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    samples: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")


class MomClose(Base):
    """One evaluation of one closed bar across the universe.

    Written exactly once per (timeframe, bar) — the insert is the lock that
    stops two overlapping ticks judging the same bar twice. `fired` counts how
    many pools each rule accepted whether or not the strategy had a free slot,
    which is what the random controls' rate is measured from.
    """

    __tablename__ = "mom_closes"

    tf: Mapped[str] = mapped_column(String(4), primary_key=True)
    start: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    eligible: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    green: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    fired: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")


class MomSignal(Base):
    """A candle that some strategy's rule accepted: the momentum radar.

    Recorded whether or not any strategy had room to buy it, so the page can
    show every momentum candle the lab saw, and the rate a rule fires at is
    never confused with the rate a full book could take.
    """

    __tablename__ = "mom_signals"
    __table_args__ = (Index("ix_mom_signals_at", "at"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    pair_address: Mapped[str] = mapped_column(_ADDRESS, nullable=False)
    mint: Mapped[str] = mapped_column(_ADDRESS, nullable=False)
    symbol: Mapped[str | None] = mapped_column(String(32))
    tf: Mapped[str] = mapped_column(String(5), nullable=False)
    #: The candle's start (the sample's bucket for the rolling rule).
    start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    arms: Mapped[list[str]] = mapped_column(ARRAY(String(32)), nullable=False)
    features: Mapped[dict] = mapped_column(JSONB, nullable=False)


class MomPosition(Base):
    """One paper position of one strategy. **Paper only.**

    Life: `armed` (waiting for a price, pullback entries only) -> `pending`
    (decided, waiting for a sample AFTER the decision to fill it) -> `open` ->
    `closing` (exit decided, same wait) -> `closed`. `unfilled` is terminal and
    counted nowhere: an entry no fresh price ever arrived for.

    Measured at `TICKET_USD`. Nothing rewrites a closed row.
    """

    __tablename__ = "mom_positions"
    __table_args__ = (
        Index("ix_mom_positions_live", "status",
              postgresql_where=text("status <> 'closed' AND status <> 'unfilled'")),
        Index("ix_mom_positions_arm", "arm", "closed_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    arm: Mapped[str] = mapped_column(String(32), nullable=False)
    pair_address: Mapped[str] = mapped_column(_ADDRESS, nullable=False)
    mint: Mapped[str] = mapped_column(_ADDRESS, nullable=False)
    symbol: Mapped[str | None] = mapped_column(String(32))
    dex_id: Mapped[str | None] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(10), nullable=False)

    #: The candle that triggered it, and when the decision was taken.
    signal_tf: Mapped[str] = mapped_column(String(5), nullable=False)
    signal_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    signal_open: Mapped[Decimal] = mapped_column(_PRICE, nullable=False)
    signal_high: Mapped[Decimal] = mapped_column(_PRICE, nullable=False)
    signal_low: Mapped[Decimal] = mapped_column(_PRICE, nullable=False)
    signal_close: Mapped[Decimal] = mapped_column(_PRICE, nullable=False)
    features: Mapped[dict | None] = mapped_column(JSONB)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    #: Pullback entries: buy once a sample is at or under this, before `expires_at`.
    trigger_below: Mapped[Decimal | None] = mapped_column(_PRICE)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    open_price: Mapped[Decimal | None] = mapped_column(_PRICE)
    open_fill: Mapped[Decimal | None] = mapped_column(_PRICE)
    notional_usd: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    tokens: Mapped[Decimal | None] = mapped_column(Numeric(38, 12))
    fee_bps: Mapped[int | None] = mapped_column(Integer)
    liq_open_usd: Mapped[Decimal | None] = mapped_column(_USD)
    impact_open: Mapped[Decimal | None] = mapped_column(_RATIO)
    #: Exit levels fixed at the fill, from the signal candle.
    stop_price: Mapped[Decimal | None] = mapped_column(_PRICE)
    target_price: Mapped[Decimal | None] = mapped_column(_PRICE)
    #: The running high since entry — never the window's eventual high.
    peak_price: Mapped[Decimal | None] = mapped_column(_PRICE)
    #: Scale-out: half sold at +1R, the rest's stop moved to the entry.
    scaled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    scaled_usd: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))

    exit_reason: Mapped[str | None] = mapped_column(String(16))
    exit_decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    close_price: Mapped[Decimal | None] = mapped_column(_PRICE)
    close_fill: Mapped[Decimal | None] = mapped_column(_PRICE)
    liq_close_usd: Mapped[Decimal | None] = mapped_column(_USD)
    impact_close: Mapped[Decimal | None] = mapped_column(_RATIO)
    net_return: Mapped[Decimal | None] = mapped_column(_RATIO)
    pnl_usd: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
