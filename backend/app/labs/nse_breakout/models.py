"""The lab's own tables. Prefix `bt_`.

On the PLATFORM's `Base`, for the reason every other lab here documents: a
separate metadata makes `alembic revision --autogenerate` emit `drop_table`
for tables it can see in the database and not in the model tree.

`server_default` is declared wherever the migration sets one, so the two do
not show up as drift. Nullable JSONB uses `none_as_null` so a Python `None`
becomes SQL NULL rather than the JSON scalar `null` — the Solana lab learned
that one the hard way, on a `jsonb_array_length` that failed on every clean
run.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    false,
    func,
    text,
    true,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

_JSONB = JSONB(none_as_null=True)
#: Indian equities trade from a few rupees to ~1,50,000 (MRF). Four decimals
#: is more than the exchange quotes.
_PRICE = Numeric(18, 4)
#: Turnover in rupees: a large-cap day is ~1e10, so this has room.
_INR = Numeric(24, 2)
_SYMBOL = String(32)


class BtUniverseMember(Base):
    """One NSE equity under watch, keyed on its trading symbol.

    Never deleted. A symbol that stops qualifying has `active` cleared with a
    reason; a renamed or merged symbol simply stops appearing in the bhavcopy
    and goes inactive, while the new symbol arrives as its own row — which is
    the pre-decided rule and also the only thing the data supports, since the
    exchange file carries no rename linkage.
    """

    __tablename__ = "bt_universe"
    __table_args__ = (
        UniqueConstraint("symbol", name="uq_bt_universe_symbol"),
        Index("ix_bt_universe_active_turnover", "active", "turnover_20d"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    symbol: Mapped[str] = mapped_column(_SYMBOL, nullable=False)
    name: Mapped[str | None] = mapped_column(String(128))
    isin: Mapped[str | None] = mapped_column(String(16))
    #: `EQ` or `BE`. Kept so a later phase can treat trade-for-trade names
    #: differently without re-deriving it.
    series: Mapped[str] = mapped_column(String(4), nullable=False)
    last_close: Mapped[Decimal | None] = mapped_column(_PRICE)
    #: 20-day MEDIAN turnover, the liquidity gate. Median so one block deal
    #: cannot qualify an otherwise untradeable name.
    turnover_20d: Mapped[Decimal | None] = mapped_column(_INR)
    bars: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    first_seen: Mapped[date] = mapped_column(Date, nullable=False)
    last_seen: Mapped[date] = mapped_column(Date, nullable=False)
    active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=true()
    )
    #: `price` | `turnover` | `series` | `absent` — why it is not active.
    #: `pending` is the identity pass's placeholder, replaced by
    #: `rebuild_universe` inside the same transaction.
    inactive_reason: Mapped[str | None] = mapped_column(String(16))
    #: When the historical replay last walked this symbol. The resumption
    #: marker for `Detector.replay`: a symbol that produced no episodes has
    #: still been replayed, and without this it would be walked again on
    #: every pass for ever.
    replayed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class BtCandle(Base):
    """One daily bar. The unique constraint is what makes ingest idempotent:
    the same trading day re-ingested is the same rows."""

    __tablename__ = "bt_candles"
    __table_args__ = (
        UniqueConstraint("symbol", "date", name="uq_bt_candles_symbol_date"),
        Index("ix_bt_candles_date", "date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    symbol: Mapped[str] = mapped_column(_SYMBOL, nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    open: Mapped[Decimal] = mapped_column(_PRICE, nullable=False)
    high: Mapped[Decimal] = mapped_column(_PRICE, nullable=False)
    low: Mapped[Decimal] = mapped_column(_PRICE, nullable=False)
    close: Mapped[Decimal] = mapped_column(_PRICE, nullable=False)
    volume: Mapped[int] = mapped_column(Numeric(20, 0), nullable=False)
    turnover: Mapped[Decimal | None] = mapped_column(_INR)
    #: FALSE for every bhavcopy bar — the exchange file is unadjusted and the
    #: only corroboration source for corporate actions (yfinance) answered 429
    #: to every request from this host. Kept as a column so a later phase with
    #: an adjustment source does not need a migration.
    adjusted: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    #: A >`SPLIT_GAP_PCT` overnight gap. Flagged, never corrected: silently
    #: "fixing" a price with no corroboration invents data, and a split that
    #: is merely marked stays visible in the health route.
    suspect_gap: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )


class BtIndexClose(Base):
    """Nifty 50's daily close, from the exchange's own index file — what the
    relative-return columns are measured against."""

    __tablename__ = "bt_index_closes"
    __table_args__ = (
        UniqueConstraint("index_name", "date", name="uq_bt_index_closes_name_date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    index_name: Mapped[str] = mapped_column(String(32), nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    close: Mapped[Decimal] = mapped_column(_PRICE, nullable=False)


class BtIngestDay(Base):
    """One trading day's ingest, so a backfill is resumable and a missing file
    is a recorded fact rather than a silent hole.

    A day is only `ok` once its bars are committed. The backfill resumes from
    the days this table does not have, which is what makes it safe to kill.
    """

    __tablename__ = "bt_ingest_days"
    __table_args__ = (UniqueConstraint("date", name="uq_bt_ingest_days_date"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    date: Mapped[date] = mapped_column(Date, nullable=False)
    #: `ok` | `missing` (holiday or not published) | `failed`
    status: Mapped[str] = mapped_column(String(8), nullable=False)
    rows: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    symbols: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    failures: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    last_error: Mapped[str | None] = mapped_column(Text)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class BtRun(Base):
    """What one pass did, so the health route can report failures that
    happened in a worker the API never sees."""

    __tablename__ = "bt_runs"
    __table_args__ = (Index("ix_bt_runs_started_at", "started_at"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    #: `ingest` | `backfill` | `universe` | `levels` | `outcomes` | `replay`
    phase: Mapped[str] = mapped_column(String(16), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    days: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    rows: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    symbols: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    detail: Mapped[dict[str, Any] | None] = mapped_column(_JSONB)
    errors: Mapped[list[str] | None] = mapped_column(_JSONB)


# --- phase 2 ------------------------------------------------------------------

#: A percentage. Room for a stock that went up 50x and for four decimals.
_PCT = Numeric(12, 4)


class BtState(Base):
    """The latest daily read for one symbol: levels, score and state.

    **One row per symbol, not one per day.** `/near` wants today, and the
    history that matters is in `bt_episode_events` — which records transitions
    rather than 1,600 unchanged rows a day. A daily snapshot table would be
    ~400k rows a year to answer a question nothing asks.
    """

    __tablename__ = "bt_states"
    __table_args__ = (
        UniqueConstraint("symbol", name="uq_bt_states_symbol"),
        Index("ix_bt_states_state_score", "state", "score"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    symbol: Mapped[str] = mapped_column(_SYMBOL, nullable=False)
    #: The bar this was computed on — NOT when the job ran.
    bar_date: Mapped[date] = mapped_column(Date, nullable=False)
    #: `NONE` | `WATCH` | `NEAR` | `BREAKOUT` | `FALSE_BREAKOUT` | `FAILED` | `EXPIRED`
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    components: Mapped[dict[str, Any] | None] = mapped_column(_JSONB)
    close: Mapped[Decimal] = mapped_column(_PRICE, nullable=False)
    #: None when nothing unbroken sits above the close. That is a stock at an
    #: all-time high, not a missing value.
    resistance: Mapped[Decimal | None] = mapped_column(_PRICE)
    distance_pct: Mapped[Decimal | None] = mapped_column(_PCT)
    range_pct: Mapped[Decimal | None] = mapped_column(_PCT)
    tightness: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    is_52w_high: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    week52_high: Mapped[Decimal | None] = mapped_column(_PRICE)
    atr: Mapped[Decimal | None] = mapped_column(_PRICE)
    volume_mult: Mapped[Decimal | None] = mapped_column(_PCT)
    #: Every cluster, so `/stock/{symbol}` can draw the whole ladder without
    #: recomputing it and risking a different answer from the one stored.
    clusters: Mapped[list[dict[str, Any]] | None] = mapped_column(_JSONB)
    days_in_state: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default=text("1")
    )
    bars: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class BtEpisode(Base):
    """One setup from the first WATCH/NEAR to whatever ended it, with what
    happened afterwards filled in later by a separate pass.

    **The separation is what makes this a backtest.** Outcome columns are
    written by `outcomes_tick` once the window has elapsed, never by the pass
    that detects the setup — so nothing that decides a state can see a return.

    `source` is `live` or `replay`. They are never mixed in a statistic: the
    replay is one causal walk over history with today's rules, the live rows
    accumulate one bar at a time, and averaging them together would hide which
    is which.
    """

    __tablename__ = "bt_episodes"
    __table_args__ = (
        # One OPEN episode per symbol per source. Partial, so closed episodes
        # accumulate freely — which is the whole record.
        Index("uq_bt_episodes_open", "symbol", "source", unique=True,
              postgresql_where=text("closed IS NULL")),
        Index("ix_bt_episodes_source_opened", "source", "opened"),
        Index("ix_bt_episodes_breakout", "source", "breakout_date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    symbol: Mapped[str] = mapped_column(_SYMBOL, nullable=False)
    #: `live` | `replay`
    source: Mapped[str] = mapped_column(String(8), nullable=False)
    opened: Mapped[date] = mapped_column(Date, nullable=False)
    first_near_date: Mapped[date | None] = mapped_column(Date)
    #: Close on `first_near_date`: what buying the setup would have paid.
    ref_price: Mapped[Decimal | None] = mapped_column(_PRICE)
    #: The level this episode is about, fixed at open.
    resistance: Mapped[Decimal | None] = mapped_column(_PRICE)
    score_at_open: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    max_score: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    breakout_date: Mapped[date | None] = mapped_column(Date)
    breakout_price: Mapped[Decimal | None] = mapped_column(_PRICE)
    breakout_volume_mult: Mapped[Decimal | None] = mapped_column(_PCT)
    days_to_breakout: Mapped[int | None] = mapped_column(Integer)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    #: Bars the episode has been open, and bars since the breakout. Stored
    #: because the live pass sees one bar a day: without them `EXPIRED` and
    #: the false-breakout window could never fire, since the counters would
    #: reset every morning.
    bars_open: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    bars_since_breakout: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    #: Consecutive bars under `WATCH_SCORE`, for the same reason.
    weak_bars: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    closed: Mapped[date | None] = mapped_column(Date)
    #: `FALSE_BREAKOUT` | `FAILED` | `EXPIRED` | `no_volume` | `fell_away` |
    #: `score_faded` | `window_complete`
    close_reason: Mapped[str | None] = mapped_column(String(24))

    # --- outcomes, filled later ------------------------------------------------
    #: Percent returns. Absent (NULL) means "not measurable yet", NEVER zero.
    ret_ref_5: Mapped[Decimal | None] = mapped_column(_PCT)
    ret_ref_10: Mapped[Decimal | None] = mapped_column(_PCT)
    ret_ref_20: Mapped[Decimal | None] = mapped_column(_PCT)
    ret_ref_40: Mapped[Decimal | None] = mapped_column(_PCT)
    mfe_20: Mapped[Decimal | None] = mapped_column(_PCT)
    mae_20: Mapped[Decimal | None] = mapped_column(_PCT)
    ret_bo_5: Mapped[Decimal | None] = mapped_column(_PCT)
    ret_bo_10: Mapped[Decimal | None] = mapped_column(_PCT)
    ret_bo_20: Mapped[Decimal | None] = mapped_column(_PCT)
    ret_bo_40: Mapped[Decimal | None] = mapped_column(_PCT)
    mfe_bo_20: Mapped[Decimal | None] = mapped_column(_PCT)
    mae_bo_20: Mapped[Decimal | None] = mapped_column(_PCT)
    #: From `breakout_price` to the close 20 trading days later.
    held_20d_pct: Mapped[Decimal | None] = mapped_column(_PCT)
    #: The same entry with a 10% trailing stop, evaluated LOW BEFORE HIGH.
    trail10_pct: Mapped[Decimal | None] = mapped_column(_PCT)
    trail10_bars: Mapped[int | None] = mapped_column(Integer)
    trail10_stopped: Mapped[bool | None] = mapped_column(Boolean)
    #: Return minus Nifty 50 over the same window. NULL when the index is
    #: missing for that window — pre-decided: null, never zero.
    rel_nifty_20: Mapped[Decimal | None] = mapped_column(_PCT)
    rel_nifty_bo_20: Mapped[Decimal | None] = mapped_column(_PCT)
    outcomes_filled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                 nullable=False)


class BtEpisodeEvent(Base):
    """One state transition inside an episode. Append-only."""

    __tablename__ = "bt_episode_events"
    __table_args__ = (
        Index("ix_bt_episode_events_episode", "episode_id", "date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    #: No ForeignKey: the episode table is written by a replay that rewrites
    #: whole symbols at a time, and a cascade would be a delete this lab has
    #: no reason to own. Events are pruned with their episodes explicitly.
    episode_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    close: Mapped[Decimal | None] = mapped_column(_PRICE)
    resistance: Mapped[Decimal | None] = mapped_column(_PRICE)
    score: Mapped[int | None] = mapped_column(Integer)
    note: Mapped[str | None] = mapped_column(Text)
