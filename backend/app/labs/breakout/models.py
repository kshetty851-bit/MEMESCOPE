"""The lab's own tables. Prefix `bo_`.

On the PLATFORM's `Base`, for the reason the Crypto Trend and Rafiq labs
document: a separate metadata makes `alembic revision --autogenerate` emit
`drop_table` for tables it can see in the database and not in the model tree.
Sharing the metadata is what makes the schema tool agree with the schema.

Phase 1 is three tables, not four. The brief asked for per-token data health
— last candle time per timeframe, gaps, consecutive fetch failures. The first
two are derivable from `bo_candles` and are computed in `data.data_health()`;
only the failure counter is state, and it is two columns on `bo_universe`. A
fourth table storing what a `GROUP BY` already knows would be a second source
of truth for the same fact.

Phase 2 adds `bo_levels`, `bo_setup_snapshots` and `bo_episodes`.

`server_default` is declared wherever the migration sets one, so the two do
not show up as drift.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
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

#: Nullable JSONB columns use `none_as_null` so a Python `None` becomes SQL
#: NULL rather than the JSON scalar `null`. Without it `jsonb_array_length(
#: errors)` fails on every run that had no errors — the app reads the column
#: through `or []` and never notices, so the first person to hurt is whoever
#: opens psql to ask a question of this table.
_JSONB = JSONB(none_as_null=True)

#: Solana tokens are quoted far below a cent — a memecoin at 6.3e-9 is
#: ordinary. `Numeric(24, 8)` would round that to zero, so prices carry 18
#: decimals. USD aggregates do not need them.
_PRICE = Numeric(36, 18)
_USD = Numeric(24, 2)
_ADDRESS = String(64)


class BoUniverseMember(Base):
    """One established token under watch, keyed on its mint.

    Never deleted: a token that fails the filters on a refresh has `active`
    cleared and `inactive_reason` set, and passing again clears both. Its
    candles are kept either way — the history is the point.
    """

    __tablename__ = "bo_universe"
    __table_args__ = (
        UniqueConstraint("mint", name="uq_bo_universe_mint"),
        Index("ix_bo_universe_active_volume", "active", "volume_24h_usd"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    mint: Mapped[str] = mapped_column(_ADDRESS, nullable=False)
    symbol: Mapped[str | None] = mapped_column(String(32))
    name: Mapped[str | None] = mapped_column(String(128))
    #: The deepest pool for this token. Candles are fetched against this one.
    pool_address: Mapped[str] = mapped_column(_ADDRESS, nullable=False)
    dex: Mapped[str] = mapped_column(String(32), nullable=False)
    pair_created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    liquidity_usd: Mapped[Decimal | None] = mapped_column(_USD)
    volume_24h_usd: Mapped[Decimal | None] = mapped_column(_USD)
    price_usd: Mapped[Decimal | None] = mapped_column(_PRICE)
    fdv: Mapped[Decimal | None] = mapped_column(_USD)
    #: ALWAYS NULL in this phase. Neither GeckoTerminal's public pool payload
    #: nor DexScreener's pair payload carries a holder count, and the brief
    #: asks for it "if available". The column exists so a later phase with a
    #: holder source does not need a migration to use it.
    holders: Mapped[int | None] = mapped_column(Integer)
    #: The token's OTHER qualifying pools, shallower than `pool_address`:
    #: `[{"pool_address", "dex", "liquidity_usd", "volume_24h_usd"}]`. Kept
    #: for reference — nothing in this phase reads it.
    alt_pools: Mapped[list[dict[str, Any]] | None] = mapped_column(_JSONB)
    #: Which source produced the winning pool, `geckoterminal` or `dexscreener`.
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=true()
    )
    #: Why it is not active: a filter name, or `fetch_failures`.
    inactive_reason: Mapped[str | None] = mapped_column(String(32))
    #: CONSECUTIVE failed candle fetches. Any success sets it back to zero.
    fetch_failures: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    last_error: Mapped[str | None] = mapped_column(Text)


class BoCandle(Base):
    """One CLOSED OHLCV bar. The unique constraint is what makes the poll
    idempotent: the same bar upserted twice is one row."""

    __tablename__ = "bo_candles"
    __table_args__ = (
        UniqueConstraint("mint", "timeframe", "open_time",
                         name="uq_bo_candles_mint_timeframe_open_time"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    mint: Mapped[str] = mapped_column(_ADDRESS, nullable=False)
    #: The pool the bar came from. Stored per row, not only on the universe,
    #: because a token whose deepest pool changes must not silently splice two
    #: venues' price history into one series without that being visible.
    pool_address: Mapped[str] = mapped_column(_ADDRESS, nullable=False)
    #: `day` | `hour` — GeckoTerminal's own names, stored verbatim.
    timeframe: Mapped[str] = mapped_column(String(8), nullable=False)
    open_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    open: Mapped[Decimal] = mapped_column(_PRICE, nullable=False)
    high: Mapped[Decimal] = mapped_column(_PRICE, nullable=False)
    low: Mapped[Decimal] = mapped_column(_PRICE, nullable=False)
    close: Mapped[Decimal] = mapped_column(_PRICE, nullable=False)
    volume_usd: Mapped[Decimal | None] = mapped_column(_USD)
    close_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class BoRun(Base):
    """What one tick did, so `data_health()` can report errors that happened
    in a worker process the API never sees. Pruned to `RUN_HISTORY` rows."""

    __tablename__ = "bo_runs"
    __table_args__ = (Index("ix_bo_runs_started_at", "started_at"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    #: `universe` | `candles` — the two halves of the chained tick.
    phase: Mapped[str] = mapped_column(String(16), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    universe_size: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    added: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    dropped: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    candles_upserted: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    tokens_refreshed: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    #: Tokens that were due a fetch and did not get one — the queue carried
    #: into the next tick. Non-zero is the budget working, not an error.
    tokens_carried: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    #: `{"geckoterminal": n, "dexscreener": n}` — requests actually sent,
    #: retries included.
    requests: Mapped[dict[str, Any] | None] = mapped_column(_JSONB)
    errors: Mapped[list[str] | None] = mapped_column(_JSONB)


# ============================================================================
# Phase 2 — setup detection
# ============================================================================

class BoLevels(Base):
    """The latest daily read per token: one row, replaced each pass.

    History is not kept here on purpose — `bo_setup_snapshots` records the
    resistance that was in force on every evaluated bar, which is the version
    a backtest needs. A second full history of clusters would be a second
    source of truth for the same fact.
    """

    __tablename__ = "bo_levels"
    __table_args__ = (UniqueConstraint("mint", name="uq_bo_levels_mint"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    mint: Mapped[str] = mapped_column(_ADDRESS, nullable=False)
    #: `[{"level", "touches", "first", "last", "broken"}]`, ascending by level.
    clusters: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    #: Lowest unbroken cluster above the close. NULL means no setup is possible
    #: — there is nothing above to break.
    nearest_resistance: Mapped[Decimal | None] = mapped_column(_PRICE)
    atr: Mapped[Decimal | None] = mapped_column(_PRICE)
    atr_fast: Mapped[Decimal | None] = mapped_column(_PRICE)
    atr_slow: Mapped[Decimal | None] = mapped_column(_PRICE)
    volume_mean: Mapped[Decimal | None] = mapped_column(_USD)
    high_range: Mapped[Decimal | None] = mapped_column(_PRICE)
    low_range: Mapped[Decimal | None] = mapped_column(_PRICE)
    close: Mapped[Decimal] = mapped_column(_PRICE, nullable=False)
    daily_bars: Mapped[int] = mapped_column(Integer, nullable=False)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class BoSetupSnapshot(Base):
    """One row per token per hourly bar in a non-NONE state.

    Keyed on the BAR, not the clock: re-running a pass rewrites the row rather
    than adding one, so the table is a clean per-hour series whatever the
    scheduler does.
    """

    __tablename__ = "bo_setup_snapshots"
    __table_args__ = (
        UniqueConstraint("mint", "bar_close_time", name="uq_bo_setup_snapshots_mint_bar"),
        Index("ix_bo_setup_snapshots_bar", "bar_close_time"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    mint: Mapped[str] = mapped_column(_ADDRESS, nullable=False)
    bar_close_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    #: `WATCHING` | `PRE_BREAKOUT` | `BROKE_OUT` | `FAILED`
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    #: The five components behind the score, so a row explains itself.
    components: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    price: Mapped[Decimal] = mapped_column(_PRICE, nullable=False)
    resistance: Mapped[Decimal | None] = mapped_column(_PRICE)
    #: Percent of resistance the price is BELOW it; negative means above.
    distance_pct: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    hourly_missing: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class BoEpisode(Base):
    """One token's run at one resistance level, from first interest to answer.

    **This table is the future backtest.** Everything before `closed_at` is
    written without knowing the outcome; everything after it is filled by the
    daily outcomes pass 72 hours later. The separation is the point — if the
    two were ever written in the same pass the record would be worthless.
    """

    __tablename__ = "bo_episodes"
    __table_args__ = (
        # One OPEN episode per token. Partial, so closed episodes accumulate
        # freely — a token may run at the same level many times.
        Index("uq_bo_episodes_open_mint", "mint", unique=True,
              postgresql_where=text("closed_at IS NULL")),
        Index("ix_bo_episodes_opened_at", "opened_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    mint: Mapped[str] = mapped_column(_ADDRESS, nullable=False)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    #: When the setup first reached PRE_BREAKOUT — the moment Phase 3 buys, and
    #: the reference every outcome column is measured from. NULL means the
    #: episode never got that far.
    first_pre_breakout_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    #: `BROKE_OUT` | `FAILED` | `EXPIRED` | `universe_exit`
    close_reason: Mapped[str | None] = mapped_column(String(16))
    entry_ref_price: Mapped[Decimal | None] = mapped_column(_PRICE)
    resistance_at_open: Mapped[Decimal | None] = mapped_column(_PRICE)
    #: Extremes seen AFTER the reference price, never before it.
    peak_price: Mapped[Decimal | None] = mapped_column(_PRICE)
    min_price: Mapped[Decimal | None] = mapped_column(_PRICE)

    # --- filled by the daily outcomes pass, never by the setups pass ---------
    max_gain_pct_from_ref: Mapped[Decimal | None] = mapped_column(Numeric(16, 4))
    max_loss_pct_from_ref: Mapped[Decimal | None] = mapped_column(Numeric(16, 4))
    pct_at_24h: Mapped[Decimal | None] = mapped_column(Numeric(16, 4))
    pct_at_72h: Mapped[Decimal | None] = mapped_column(Numeric(16, 4))
    #: A $100 position with a $25 trailing stop from `entry_ref_price`, read
    #: off hourly bars with the low taken before the high. Phase 3's live
    #: trader runs the same rule; a test asserts the two agree.
    trail25_result_pct: Mapped[Decimal | None] = mapped_column(Numeric(16, 4))
    #: The hourly bars behind the outcome were not contiguous. The numbers are
    #: still written — they are just not to be trusted without this flag read.
    outcome_gappy: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    #: When the outcome columns were filled. NULL means not yet.
    outcome_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# ============================================================================
# Phase 3 — the paper trader's own ledger
# ============================================================================
#
# ITS OWN. Not the platform paper wallet, not the Karthik wallet, not another
# lab's book. Nothing in this package imports any of them and a test parses
# every module to hold that. $1,000, ten slots, no key and no signer.

class BoAccount(Base):
    """One row. `scope` exists only to carry the unique constraint that makes
    "one row" a schema fact rather than a convention someone breaks later."""

    __tablename__ = "bo_account"
    __table_args__ = (UniqueConstraint("scope", name="uq_bo_account_scope"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    scope: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'default'")
    )
    #: Cash plus the mark-to-market value of every open position.
    equity: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    cash: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    #: The high-water mark the kill switch measures drawdown against.
    peak_equity: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    halted: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    halted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    halted_reason: Mapped[str | None] = mapped_column(String(64))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class BoPosition(Base):
    """An OPEN position. Closing one deletes this row and writes a `bo_trades`
    row — the trade is the permanent record, and keeping a closed position in
    both places would be two sources of truth for one fill."""

    __tablename__ = "bo_positions"
    __table_args__ = (UniqueConstraint("mint", name="uq_bo_positions_mint"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    mint: Mapped[str] = mapped_column(_ADDRESS, nullable=False)
    episode_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    qty: Mapped[Decimal] = mapped_column(Numeric(38, 12), nullable=False)
    entry_price: Mapped[Decimal] = mapped_column(_PRICE, nullable=False)
    #: Equity / SLOTS at the moment of entry. The trail is a percentage of it,
    #: so the stop scales with the account rather than staying $25 for ever.
    slot_size: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    #: The highest mark-to-market VALUE this position has reached. The stop
    #: hangs `TRAIL_PCT` of `slot_size` below it and only ever ratchets up.
    high_water_value: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    entry_fees: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    #: The bar this position was opened ON — what makes a re-run idempotent.
    entry_bar: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class BoTrade(Base):
    """One closed round trip. The permanent record."""

    __tablename__ = "bo_trades"
    __table_args__ = (
        UniqueConstraint("mint", "entry_bar", name="uq_bo_trades_mint_entry_bar"),
        Index("ix_bo_trades_closed_at", "closed_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    mint: Mapped[str] = mapped_column(_ADDRESS, nullable=False)
    symbol: Mapped[str | None] = mapped_column(String(32))
    episode_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    qty: Mapped[Decimal] = mapped_column(Numeric(38, 12), nullable=False)
    entry_price: Mapped[Decimal] = mapped_column(_PRICE, nullable=False)
    exit_price: Mapped[Decimal] = mapped_column(_PRICE, nullable=False)
    slot_size: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    #: Net of both sides' fees and slippage. This is the only P&L number.
    pnl_usd: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    pnl_pct: Mapped[Decimal] = mapped_column(Numeric(16, 4), nullable=False)
    fees_usd: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    closed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    entry_bar: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    exit_bar: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    #: `trail_stop` | `failed_setup` | `time_stop` | `forced_exit` | `halt` | `flatten`
    exit_reason: Mapped[str] = mapped_column(String(24), nullable=False)


class BoEquity(Base):
    """One row per hourly tick — the curve the frontend draws."""

    __tablename__ = "bo_equity"
    __table_args__ = (
        UniqueConstraint("bar_close_time", name="uq_bo_equity_bar"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    bar_close_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    equity: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    cash: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    unrealised: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    positions: Mapped[int] = mapped_column(Integer, nullable=False)
