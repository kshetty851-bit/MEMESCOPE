"""The lab's own tables. Prefix `grad_`.

On the PLATFORM's `Base`, for the reason the Crypto Trend, Breakout and Rafiq
labs document: a separate metadata makes `alembic revision --autogenerate` emit
`drop_table` for every table it can see in the database and not in the model
tree. Sharing the metadata is what makes the schema tool agree with the schema.

`server_default` is declared wherever the migration sets one, so the two do not
show up as drift.

## Where each number comes from

Since the move off the metered trade stream there are three sources, and the
tables are split along them because they have different shapes and different
failure modes:

* `grad_curve_samples` — the CHAIN, via `getMultipleAccounts` every
  `POLL_INTERVAL_S`. Reserves and progress. Always available, costs nothing.
* `grad_postgrad_samples` — DEXSCREENER (GeckoTerminal on a missed poll), once
  a minute for an hour after graduation. Price, volume, buy/sell counts.
* `grad_migrations` — the free PumpPortal migration feed.

`grad_trades` is **kept and left empty**. Per-trade detail is no longer bought
from PumpPortal's metered stream; a Phase 2 backfill may fill it for graduates
only, from transaction history, where the population is small enough to afford.

## Nullability is driven by the live feed, not by the brief

Measured across 121 consecutive `create` messages: `name` and `symbol` were
absent from 17, `bondingCurveKey` from 19, and NO message of any type carries a
slot or a timestamp. So those columns are nullable, and every `ts` in this
package is receipt or poll time, which is the only clock there is.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    DateTime,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    false,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

_ADDRESS = String(64)
_SIGNATURE = String(96)
#: A quote reserve or amount: SOL, or USDC on a USDC-denominated curve.
_QUOTE = Numeric(30, 9)
#: Token amounts, in WHOLE tokens. The account counts in base units; these
#: columns hold the divided figure so a human can read a row.
_TOKENS = Numeric(38, 9)
#: 0.000 to 100.000.
_PCT = Numeric(6, 3)
#: A share of 1, to six places.
_SHARE = Numeric(9, 6)
_USD = Numeric(24, 8)

#: `grad_tokens.status`.
STATUS_WATCHING = "watching"
STATUS_TRACKING = "tracking"
STATUS_MIGRATED = "migrated"
STATUS_DONE = "done"

#: `grad_postgrad_samples.source`.
SOURCE_DEXSCREENER = "dexscreener"
SOURCE_GECKOTERMINAL = "geckoterminal"


class GradToken(Base):
    """One mint this lab has ever watched, keyed on the mint.

    Never deleted. The pruner strips its curve samples after a day without a
    graduation and leaves this row, so "how many tokens got to 80% and died"
    stays answerable for ever at one row per token.
    """

    __tablename__ = "grad_tokens"
    __table_args__ = (
        Index("ix_grad_tokens_status_first_seen", "status", "first_seen_at"),
        Index("ix_grad_tokens_tracked_at", "tracked_at"),
        Index("ix_grad_tokens_migrated_at", "migrated_at"),
    )

    mint: Mapped[str] = mapped_column(_ADDRESS, primary_key=True)
    #: Absent from 17 of 121 observed launches. See the module docstring.
    symbol: Mapped[str | None] = mapped_column(String(32))
    name: Mapped[str | None] = mapped_column(String(128))
    creator: Mapped[str | None] = mapped_column(_ADDRESS)
    #: The launch platform: `pump`, or `bonk` for a curve this lab does not
    #: model and does not admit.
    launch_pool: Mapped[str | None] = mapped_column(String(32))
    #: As the LAUNCH MESSAGE reported it, which is **not reliable** and is never
    #: what this lab polls. Measured on 15 consecutive launches on 2026-09-11:
    #: 3 of them carried the SAME `bondingCurveKey`
    #: (`BwWK17cbHxwWBKZkUYvzxLcNQ1YVyaFezduWbtm2de6s`) for three unrelated
    #: mints, and that address is a zero-length account owned by the System
    #: Program — not a curve at all. Stored only so the disagreement stays
    #: findable; `curve_address` is the one that was actually read.
    bonding_curve_key: Mapped[str | None] = mapped_column(_ADDRESS)
    #: The PDA this lab DERIVED and actually polls. Stored because it is the
    #: address the samples came from, and because a disagreement with
    #: `bonding_curve_key` is worth being able to find later.
    curve_address: Mapped[str | None] = mapped_column(_ADDRESS)
    #: `SOL` or `USDC`. A USDC-denominated curve holds USDC in the reserve the
    #: SOL field normally carries. Detected from the LAUNCH message: the curve
    #: account carries no denomination flag in the bytes this lab decodes.
    quote_currency: Mapped[str] = mapped_column(
        String(8), nullable=False, server_default=text("'SOL'")
    )

    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    #: When it first polled at/above the threshold. Null = never got there.
    tracked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    migrated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    unsubscribed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    #: `silent`, `post_migration`, `stale`, `evicted`, `foreign`, `shutdown`.
    unsubscribe_reason: Mapped[str | None] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text(f"'{STATUS_WATCHING}'")
    )

    #: The HIGHEST progress ever seen, not the last. Progress falls when
    #: somebody sells, and "did it reach 90" is the question this lab is for.
    max_progress_pct: Mapped[Decimal | None] = mapped_column(_PCT)
    #: The most recent reading, which is what eviction and health read.
    last_progress_pct: Mapped[Decimal | None] = mapped_column(_PCT)
    #: When a reserve last actually MOVED. `SILENT_MIN` eviction measures from
    #: here, not from the last poll: a poll happens whether or not anybody
    #: traded, so polling time would make every dead token look alive.
    last_progress_change_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    first_sample_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_sample_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sample_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    #: Market cap in the quote currency, from the curve's own reserves:
    #: `virtual_quote / virtual_token * total_supply`. The peak ever seen.
    peak_market_cap_quote: Mapped[Decimal | None] = mapped_column(_QUOTE)

    # --- trade aggregates: EMPTY, and deliberately kept ----------------------
    #: These were filled by the metered PumpPortal trade stream and are not
    #: filled by anything today. Kept rather than dropped because a Phase 2
    #: backfill over GRADUATES ONLY — a few hundred tokens a day, not a few
    #: hundred thousand — can fill them from transaction history without
    #: another migration. A reader must treat 0 here as "not collected".
    trade_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    buy_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    sell_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    unique_traders: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    unique_buyers: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    volume_sol: Mapped[Decimal | None] = mapped_column(_QUOTE)
    first_trade_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_trade_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    #: Set by the pruner. A row with this set has no `grad_curve_samples` left.
    pruned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class GradCurveSample(Base):
    """One reading of one bonding curve account.

    **Written only when a reserve moved**, unless `SAMPLE_ON_CHANGE_ONLY` is
    off. Storing every poll of every watched token is ~2.88 million rows a day,
    the large majority byte-identical to the row before them — two thirds of
    live curves have never had a single token bought. An unchanged reserve says
    nothing the previous row and the poll cadence do not already say.

    The consequence to keep in mind when reading this table: **the gap between
    two rows is not a gap in coverage.** It means nothing happened. The token's
    `last_sample_at` says when it was last actually looked at.
    """

    __tablename__ = "grad_curve_samples"
    __table_args__ = (
        UniqueConstraint("mint", "ts", name="uq_grad_curve_samples_mint_ts"),
        Index("ix_grad_curve_samples_mint_ts", "mint", "ts"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    #: Poll time. The chain read carries no timestamp of its own at this
    #: encoding, so this is when the response was decoded.
    ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    mint: Mapped[str] = mapped_column(_ADDRESS, nullable=False)

    #: Whole tokens, divided down from the account's base units.
    v_token_reserves: Mapped[Decimal | None] = mapped_column(_TOKENS)
    real_token_reserves: Mapped[Decimal | None] = mapped_column(_TOKENS)
    #: SOL, or USDC on a USDC-denominated curve — `grad_tokens.quote_currency`
    #: says which, and it is repeated here so one row is self-describing.
    v_quote_reserves: Mapped[Decimal | None] = mapped_column(_QUOTE)
    real_quote_reserves: Mapped[Decimal | None] = mapped_column(_QUOTE)
    quote_currency: Mapped[str | None] = mapped_column(String(8))
    token_total_supply: Mapped[Decimal | None] = mapped_column(_TOKENS)

    progress_pct: Mapped[Decimal | None] = mapped_column(_PCT)
    #: The account's own flag. `true` is the chain saying the curve has filled,
    #: and it is the graduation signal that does not depend on the websocket.
    complete: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=false()
    )
    market_cap_quote: Mapped[Decimal | None] = mapped_column(_QUOTE)


class GradPostgradSample(Base):
    """One reading of a graduated token's AMM pair.

    Sampled for `POST_MIGRATION_SECONDS` after the migration event. `source`
    distinguishes a live DexScreener poll from a GeckoTerminal minute candle
    backfilled over a poll that was missed — the two are not the same
    measurement and must never be averaged together without knowing which.
    """

    __tablename__ = "grad_postgrad_samples"
    __table_args__ = (
        UniqueConstraint("mint", "ts", name="uq_grad_postgrad_samples_mint_ts"),
        Index("ix_grad_postgrad_samples_mint_ts", "mint", "ts"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    mint: Mapped[str] = mapped_column(_ADDRESS, nullable=False)
    #: `dexscreener` (a live poll) or `geckoterminal` (a backfilled candle).
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    #: The AMM pair. Needed for the GeckoTerminal backfill, which addresses a
    #: POOL and not a mint — a token whose first DexScreener poll fails can
    #: therefore never be backfilled. See README, known limitations.
    pair_address: Mapped[str | None] = mapped_column(_ADDRESS)
    dex_id: Mapped[str | None] = mapped_column(String(32))

    price_usd: Mapped[Decimal | None] = mapped_column(_USD)
    price_native: Mapped[Decimal | None] = mapped_column(_USD)
    liquidity_usd: Mapped[Decimal | None] = mapped_column(Numeric(24, 2))
    fdv: Mapped[Decimal | None] = mapped_column(Numeric(24, 2))
    volume_m5_usd: Mapped[Decimal | None] = mapped_column(Numeric(24, 2))
    volume_h1_usd: Mapped[Decimal | None] = mapped_column(Numeric(24, 2))
    #: ONE minute's volume, and the only volume a backfilled candle can give.
    #: DexScreener's m5/h1 are rolling windows it computes itself, so a
    #: GeckoTerminal candle cannot fill them and leaves them null rather than
    #: putting a one-minute figure in a five-minute column.
    volume_m1_usd: Mapped[Decimal | None] = mapped_column(Numeric(24, 2))
    #: Null on a backfilled candle: GeckoTerminal's OHLCV carries volume but no
    #: buy/sell split. Null here means "this source cannot say", not "zero".
    txns_m5_buys: Mapped[int | None] = mapped_column(Integer)
    txns_m5_sells: Mapped[int | None] = mapped_column(Integer)
    txns_h1_buys: Mapped[int | None] = mapped_column(Integer)
    txns_h1_sells: Mapped[int | None] = mapped_column(Integer)


class GradCheckpoint(Base):
    """The state of one token the first time it polled at one level.

    Written once per `(mint, level_pct)` and never revised: a checkpoint is a
    measurement at a moment, and a row that gets updated is a moment that can
    no longer be read back.
    """

    __tablename__ = "grad_checkpoints"
    __table_args__ = (
        UniqueConstraint("mint", "level_pct", name="uq_grad_checkpoints_mint"),
        Index("ix_grad_checkpoints_level_ts", "level_pct", "ts"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    mint: Mapped[str] = mapped_column(_ADDRESS, nullable=False)
    #: The level this row is FOR: 70, 80, 90, 95, 100.
    level_pct: Mapped[Decimal] = mapped_column(_PCT, nullable=False)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    #: The progress actually observed, which is >= `level_pct`: a token can
    #: cross three levels between two polls and owe three rows at once, all
    #: three carrying the one reading that revealed them.
    progress_pct: Mapped[Decimal] = mapped_column(_PCT, nullable=False)

    v_token_reserves: Mapped[Decimal | None] = mapped_column(_TOKENS)
    real_token_reserves: Mapped[Decimal | None] = mapped_column(_TOKENS)
    v_quote_reserves: Mapped[Decimal | None] = mapped_column(_QUOTE)
    real_quote_reserves: Mapped[Decimal | None] = mapped_column(_QUOTE)
    quote_currency: Mapped[str | None] = mapped_column(String(8))
    market_cap_quote: Mapped[Decimal | None] = mapped_column(_QUOTE)

    # --- trade-derived: EMPTY, and deliberately kept -------------------------
    #: Filled by the metered trade stream, which this lab no longer buys. The
    #: chain reports reserves, not who moved them, so a poller cannot count
    #: buyers or holders at any price. Kept for the Phase 2 graduate-only
    #: backfill. 0 and null here mean "not collected", never "none".
    buy_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    sell_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    unique_buyers: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    unique_traders: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    top10_holder_share: Mapped[Decimal | None] = mapped_column(_SHARE)
    holders_seen: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )


class GradTrade(Base):
    """Per-trade detail. **Empty today**, and kept on purpose.

    It was filled from PumpPortal's `subscribeTokenTrade`, which is metered at
    0.01 SOL per 10,000 events. Progress now comes from the chain for nothing,
    so the stream — and its bill — is gone, and with it the only source of
    per-trade detail for the ~1,500 tokens an hour that never graduate.

    Phase 2 may backfill this for GRADUATES ONLY from transaction history: a
    few hundred tokens a day is an affordable population where a few hundred
    thousand was not. The table stays so that work needs no migration.
    """

    __tablename__ = "grad_trades"
    __table_args__ = (
        UniqueConstraint("signature", "mint", name="uq_grad_trades_signature"),
        Index("ix_grad_trades_mint_ts", "mint", "ts"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    mint: Mapped[str] = mapped_column(_ADDRESS, nullable=False)
    side: Mapped[str] = mapped_column(String(4), nullable=False)
    sol_amount: Mapped[Decimal] = mapped_column(_QUOTE, nullable=False)
    token_amount: Mapped[Decimal] = mapped_column(_TOKENS, nullable=False)
    trader: Mapped[str] = mapped_column(_ADDRESS, nullable=False)
    pool: Mapped[str] = mapped_column(String(16), nullable=False)
    progress_pct: Mapped[Decimal | None] = mapped_column(_PCT)
    v_token_reserves: Mapped[Decimal | None] = mapped_column(_TOKENS)
    v_quote_reserves: Mapped[Decimal | None] = mapped_column(_QUOTE)
    quote_currency: Mapped[str | None] = mapped_column(String(8))
    market_cap_sol: Mapped[Decimal | None] = mapped_column(_QUOTE)
    new_token_balance: Mapped[Decimal | None] = mapped_column(_TOKENS)
    signature: Mapped[str | None] = mapped_column(_SIGNATURE)


class GradMigration(Base):
    """The graduation event, one row per mint.

    The whole message is kept in `raw`: PumpPortal publishes no example payload
    for `subscribeMigration`, so the columns above it are this lab's reading of
    an unverified shape and `raw` is the appeal against a misreading.
    """

    __tablename__ = "grad_migrations"

    mint: Mapped[str] = mapped_column(_ADDRESS, primary_key=True)
    ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    pool: Mapped[str | None] = mapped_column(String(16))
    signature: Mapped[str | None] = mapped_column(_SIGNATURE)
    #: The highest progress this lab polled before the event arrived. Null when
    #: the token was never watched — the migration feed is global and reports
    #: graduations of tokens this lab never saw launch.
    progress_pct_before: Mapped[Decimal | None] = mapped_column(_PCT)
    #: True when the CHAIN said `complete` before the websocket said migrated.
    #: The two signals are independent and either may arrive first; which one
    #: did is worth knowing when reconciling timings later.
    seen_complete_on_chain: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=false()
    )
    raw: Mapped[dict | None] = mapped_column(JSONB)
