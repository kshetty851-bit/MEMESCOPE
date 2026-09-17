"""`/labs/graduation` — read-only. No POST/PUT/PATCH/DELETE.

With the flag off every route answers `running: false` without touching the
database: "the lab is not running" and "the lab ran and found nothing" are
different facts and must not render identically.

The page this feeds is a **status board, not a strategy**. It reports what the
recorder has seen; it ranks nothing and recommends nothing.
"""

from __future__ import annotations

import random
from collections.abc import Iterable, Sequence
from functools import lru_cache
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from math import sqrt
from statistics import fmean, pstdev
from typing import Any, NamedTuple

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.labs.graduation import config, live_spec
from app.labs.graduation.models import (
    GradCheckpoint,
    GradCurveSample,
    GradMigration,
    GradPaperPosition,
    GradPaperRestatement,
    GradPostgradSample,
    GradToken,
)
from app.labs.graduation.paper import PaperBook, costs, net_return, positions
from app.labs.graduation.tournament import ARMS

router = APIRouter(prefix="/labs/graduation", tags=["graduation-lab"])


class Funnel(BaseModel):
    """How many tokens reached each stage. Strictly decreasing by definition."""

    seen: int = 0
    crossed_70: int = 0
    crossed_80: int = 0
    crossed_90: int = 0
    crossed_95: int = 0
    graduated: int = 0


class Signals(BaseModel):
    """Graduation is reported by two INDEPENDENT sources and either can arrive
    alone. Showing only one would undercount, so the split is published."""

    both: int = 0
    feed_only: int = 0
    chain_only: int = 0


class Recent(BaseModel):
    mint: str
    symbol: str | None = None
    max_progress_pct: Decimal | None = None
    tracked: bool = False
    migrated: bool = False
    sample_count: int = 0


class PaperPosition(BaseModel):
    """One trade. The mint is published in FULL, not shortened: a truncated
    address cannot be pasted into an explorer, and an unverifiable number on a
    P&L page is worth less than no number."""

    mint: str
    symbol: str | None = None
    name: str | None = None
    opened_at: datetime
    notional_usd: Decimal
    open_fill: Decimal
    last_quote: Decimal | None = None
    peak_quote: Decimal
    closed_at: datetime | None = None
    close_reason: str | None = None
    #: Realised for a closed position; marked-to-market for an open one.
    pnl_usd: Decimal | None = None
    #: Likewise — so an open position shows a return, not a dash.
    net_return: Decimal | None = None
    #: The recorded price series for this mint crossed pools, so the trade is
    #: shown but counts for nothing. See `paper.switched_mints`.
    voided: bool = False
    #: What the fill was priced against. Published so a trade can be AUDITED
    #: rather than trusted: the pool's total value at each leg and the exact
    #: constant-product move the order caused against it. A reader can take
    #: the mint to DexScreener and check the pool was that deep.
    liq_open_usd: Decimal | None = None
    liq_close_usd: Decimal | None = None
    impact_open: Decimal | None = None
    impact_close: Decimal | None = None
    #: Why the trade counts for nothing, when it does not: `not_graduation_pool`
    #: for a token that never graduated from pump.fun.
    excluded: str | None = None
    #: What this trade made or lost for the wallet SIZE the reader picked, and
    #: whether that wallet could pay for it at all. Both null unless the
    #: request asked for a size: the book itself always trades $100.
    size_pnl_usd: Decimal | None = None
    size_funded: bool | None = None
    #: A restated trade: what the restatement did, and what the row said before.
    restated: str | None = None
    was_pnl_usd: Decimal | None = None
    was_net_return: Decimal | None = None


class PaperBookOut(BaseModel):
    """The forward book. Rules frozen in advance; nothing here is tunable."""

    running: bool = False
    #: Which tournament arm this panel renders, e.g. `E05_hold_5m`.
    book: str = "E05_hold_5m"
    filter_description: str = ""
    starting_usd: Decimal = Decimal(0)
    equity_usd: Decimal = Decimal(0)
    realised_usd: Decimal = Decimal(0)
    unrealised_usd: Decimal = Decimal(0)
    pnl_usd: Decimal = Decimal(0)
    return_pct: Decimal = Decimal(0)
    open_positions: int = 0
    closed_positions: int = 0
    wins: int = 0
    #: Closed trades excluded from every figure above because their price
    #: series crossed pools. Published rather than silently dropped.
    voided: int = 0
    max_slots: int = 0
    notional_usd: Decimal = Decimal(0)
    trailing_pct: Decimal = Decimal(0)
    #: Take profit as a multiple of the price paid: 2 is "sell at 2x".
    take_profit_x: Decimal = Decimal(0)
    max_hold_minutes: int = 0
    #: The gate this run was given BEFORE it produced a trade, and where it
    #: currently stands against it.
    gate_started: str = ""
    gate_weeks: int = 0
    gate_min_pf: Decimal = Decimal(0)
    gate_min_trades: int = 0
    gate_max_token_share: Decimal = Decimal(0)
    profit_factor: Decimal | None = None
    top_token_share: Decimal | None = None
    #: What the cost model charges on ONE leg: pump fee + assumed slippage +
    #: the priority fee as a share of the position. Published because "would a
    #: real wallet have made this?" is a question about exactly this number.
    cost_pct_per_side: Decimal = Decimal(0)
    #: Split, because exposure and results are different questions. The
    #: closed list here is the most recent few; `/paper/trades` has all of
    #: them, so a 30-second poll does not carry the whole history each time.
    open_trades: list[PaperPosition] = []
    closed_trades: list[PaperPosition] = []
    #: Echoed back when a size was asked for, so the panel can say which wallet
    #: the per-trade dollars belong to and check its own total: the funded
    #: trades sum to `size_end_usd - size_start_usd`.
    size_ticket_usd: Decimal | None = None
    size_start_usd: Decimal | None = None
    size_end_usd: Decimal | None = None
    size_funded: int | None = None
    size_skipped: int | None = None


class GraduationStatus(BaseModel):
    running: bool
    rpc_host: str
    poll_interval_s: int
    watch_set: int
    watch_set_max: int
    funnel: Funnel = Funnel()
    signals: Signals = Signals()
    curve_samples: int = 0
    checkpoints: int = 0
    checkpoints_with_reserves: int = 0
    postgrad_samples: int = 0
    #: Derived, not measured: ceil(watch_set / 100) calls a poll, at
    #: 60 / POLL_INTERVAL_S polls a minute.
    rpc_calls_per_minute: int = 0
    samples_last_hour: int = 0
    tokens_last_hour: int = 0
    recent: list[Recent] = []
    #: Surfaced because the page must not imply the quote side is sound.
    quote_side_trusted: bool = False

    # --- can the climb be seen at all? --------------------------------------
    #: Of tokens whose curve was observed COMPLETE, how many were ever also
    #: observed incomplete, and how many at 90% or above.
    #:
    #: This is the lab's own resolution, measured rather than assumed, and it
    #: bounds every pre-graduation question: a strategy can only trade the
    #: curves it can see, and on 2026-09-12 that was 34% / 16.6% at a
    #: fifteen-second poll. Half of all graduates complete within a minute of
    #: first sighting, so the shutter speed IS the population filter.
    #: All three are over the LAST HOUR, so a change to the poll interval
    #: shows up here within the hour instead of being averaged into history.
    graduates_observed: int = 0
    graduates_seen_climbing: int = 0
    graduates_seen_at_90: int = 0

    # --- is the chain actually being read? ----------------------------------
    #: When the poller last successfully read ANY curve. `last_sample_at`
    #: advances on every poll a token is read, whether or not its reserves
    #: moved, so this is the RPC's pulse — and it works from the backend
    #: container, which cannot see the recorder's in-process counters.
    last_chain_read_at: datetime | None = None
    seconds_since_chain_read: int | None = None
    #: True when there is a watch set but nothing has been read for several
    #: poll intervals. This is the case a row count cannot show: a revoked
    #: key, a dead node, a crashed loop — the tables simply stop growing while
    #: everything else on the page still reads normally.
    recorder_stalled: bool = False
    stall_threshold_s: int = 0


@router.get("/status", response_model=GraduationStatus)
async def status(db: AsyncSession = Depends(get_db)) -> GraduationStatus:
    """Everything the board renders, in one call."""
    base = GraduationStatus(
        running=config.enabled(),
        rpc_host=config.safe_rpc_url(),
        poll_interval_s=config.POLL_INTERVAL_S,
        watch_set=0,
        watch_set_max=config.MAX_WATCH_SET,
    )
    if not base.running:
        return base

    hour_ago = datetime.now(UTC) - timedelta(hours=1)

    async def count(stmt) -> int:
        return int(await db.scalar(stmt) or 0)

    crossed = {}
    for level in (70, 80, 90, 95):
        crossed[level] = await count(
            select(func.count()).select_from(GradToken)
            .where(GradToken.max_progress_pct >= level))

    complete_mints = (select(GradCurveSample.mint)
                      .where(GradCurveSample.complete.is_(True)).distinct())
    feed_mints = select(GradMigration.mint)
    # Materialised ONCE. Calling `.subquery()` twice builds two independent
    # subqueries and SQLAlchemy joins them as a cartesian product — it warns,
    # and the count it returns is the product rather than the difference.
    complete_sub = complete_mints.subquery()

    base.funnel = Funnel(
        seen=await count(select(func.count()).select_from(GradToken)),
        crossed_70=crossed[70], crossed_80=crossed[80],
        crossed_90=crossed[90], crossed_95=crossed[95],
        graduated=await count(
            select(func.count()).select_from(
                select(GradMigration.mint).union(complete_mints).subquery())),
    )
    base.signals = Signals(
        both=await count(select(func.count()).select_from(GradMigration)
                         .where(GradMigration.mint.in_(complete_mints))),
        feed_only=await count(select(func.count()).select_from(GradMigration)
                              .where(GradMigration.mint.not_in(complete_mints))),
        chain_only=await count(
            select(func.count()).select_from(complete_sub)
            .where(complete_sub.c.mint.not_in(feed_mints))),
    )
    # What is ACTUALLY being polled, not what is flagged as unretired.
    #
    # The watch set lives in the recorder's memory, so every restart orphans
    # its tokens with `unsubscribed_at` still NULL and nothing ever clears
    # them. Counting the flag reported 1,769 against a cap of 500 while the
    # poller was really reading 478 — and `rpc_calls_per_minute` is derived
    # from this, so it claimed 360 calls a minute against a 150 budget that
    # was never being exceeded. A number that cannot exceed its own cap is
    # not measuring the thing it names.
    watching_now = datetime.now(UTC) - timedelta(
        seconds=config.POLL_INTERVAL_S * 5)
    base.watch_set = await count(
        select(func.count()).select_from(GradToken)
        .where(GradToken.unsubscribed_at.is_(None),
               GradToken.last_sample_at >= watching_now))
    base.curve_samples = await count(
        select(func.count()).select_from(GradCurveSample))
    base.checkpoints = await count(
        select(func.count()).select_from(GradCheckpoint))
    base.checkpoints_with_reserves = await count(
        select(func.count()).select_from(GradCheckpoint)
        .where(GradCheckpoint.v_token_reserves.is_not(None)))
    base.postgrad_samples = await count(
        select(func.count()).select_from(GradPostgradSample))
    # Stated, not left to the model default: this is a claim the page renders
    # a warning from, and a default is not a claim.
    base.quote_side_trusted = False
    base.samples_last_hour = await count(
        select(func.count()).select_from(GradCurveSample)
        .where(GradCurveSample.ts >= hour_ago))
    base.tokens_last_hour = await count(
        select(func.count()).select_from(GradToken)
        .where(GradToken.first_seen_at >= hour_ago))

    # Windowed to the last hour, not cumulative: this figure exists to show
    # whether a change to the poll interval moved it, and a lifetime average
    # would take days to drift. It also keeps the scan small as the table
    # grows. One pass, grouped — not a correlated subquery per token.
    seen = (
        select(
            GradCurveSample.mint.label("mint"),
            func.bool_or(GradCurveSample.complete.is_(True)).label("done"),
            func.bool_or(GradCurveSample.complete.isnot(True)).label("climbing"),
            func.bool_or(GradCurveSample.complete.isnot(True)
                         & (GradCurveSample.progress_pct >= 90)).label("at90"),
        )
        .where(GradCurveSample.ts >= hour_ago)
        .group_by(GradCurveSample.mint)
        .subquery()
    )
    coverage = (await db.execute(
        select(
            func.count().filter(seen.c.done),
            func.count().filter(seen.c.done & seen.c.climbing),
            func.count().filter(seen.c.done & seen.c.at90),
        ).select_from(seen))).one()
    (base.graduates_observed, base.graduates_seen_climbing,
     base.graduates_seen_at_90) = (int(x or 0) for x in coverage)

    base.last_chain_read_at = await db.scalar(
        select(func.max(GradToken.last_sample_at)))
    # Five poll intervals. A healthy poller refreshes every one of them, so
    # five is slack for a slow flush without being slow to notice a stall.
    base.stall_threshold_s = config.POLL_INTERVAL_S * 5
    # Whether there is anything to watch — NOT whether anything is being
    # watched. `watch_set` is derived from RECENT POLLING, so a dead recorder
    # empties it, and guarding the alarm on it meant the alarm switched itself
    # off at the exact moment it was needed. On 2026-09-13 the recorder was
    # stopped for thirty-one minutes and this page read "polling normally" the
    # whole time, because watch_set had fallen to 0.
    #
    # The launch feed is the independent witness: it kept admitting 286 tokens
    # an hour throughout, which is the proof there was work the recorder was
    # not doing.
    has_work = base.watch_set > 0 or base.tokens_last_hour > 0
    if base.last_chain_read_at is not None:
        age = (datetime.now(UTC) - base.last_chain_read_at).total_seconds()
        base.seconds_since_chain_read = int(age)
        base.recorder_stalled = has_work and age > base.stall_threshold_s
    else:
        # Nothing has ever been read. Only a stall if there is something to read.
        base.recorder_stalled = has_work

    calls_per_poll = -(-base.watch_set // config.MAX_ACCOUNTS_PER_CALL)
    polls_per_minute = max(1, 60 // max(1, config.POLL_INTERVAL_S))
    base.rpc_calls_per_minute = calls_per_poll * polls_per_minute


    rows = (await db.execute(
        select(GradToken.mint, GradToken.symbol, GradToken.max_progress_pct,
               GradToken.tracked_at, GradToken.migrated_at,
               GradToken.sample_count)
        .where(GradToken.max_progress_pct.is_not(None))
        .order_by(GradToken.max_progress_pct.desc(),
                  GradToken.first_seen_at.desc())
        .limit(12))).all()
    base.recent = [
        Recent(mint=r.mint, symbol=r.symbol, max_progress_pct=r.max_progress_pct,
               tracked=r.tracked_at is not None,
               migrated=r.migrated_at is not None, sample_count=r.sample_count)
        for r in rows
    ]
    return base


def _filter_description() -> str:
    return (f"pool opened {config.PAPER_FILTER_HOUR_START:02d}:00-"
            f"{config.PAPER_FILTER_HOUR_END:02d}:00 UTC, and the symbol had "
            f"been used by at least {config.PAPER_FILTER_MIN_SYMBOL_REUSE} "
            f"earlier token{'s' if config.PAPER_FILTER_MIN_SYMBOL_REUSE != 1 else ''}")


async def _paper(db: AsyncSession, *, book: str = "E05_hold_5m",
                 limit: int | None = 10, ticket: float | None = None,
                 split: int = 1) -> PaperBookOut:
    """One book's state. Read-only: this endpoint never ticks it."""
    account = await PaperBook(db, book=book).account()
    open_rows, closed_rows = await positions(db, book=book, limit=limit)
    # The headline cost is a real position's, not a nominal one: the priority
    # fee is flat in SOL, so its share depends entirely on the size traded.
    # With no positions yet there is no rate to convert $100 with, and the
    # configured nominal is the only honest stand-in.
    sample = next((r[0] for r in (*open_rows, *closed_rows)), None)
    book_costs = costs(sample.notional_quote if sample else None,
                       pool_fee_bps=sample.pool_fee_bps if sample else None)
    cents = Decimal("0.01")

    def out(row: Any) -> PaperPosition:
        """Closed rows carry their realised figures; open ones are marked to
        the last price, at the SOL/USD rate captured when they opened.

        Both the dollars and the percentage come from the same ratio, so they
        cannot disagree with each other.
        """
        p, symbol, name, voided, restatement = row
        pnl, net = p.pnl_usd, p.net_return
        if p.closed_at is None:
            live = net_return(p, p.last_quote)
            if live is not None:
                pnl = (p.notional_usd * live).quantize(cents)
                net = live.quantize(Decimal("0.00000001"))
        return PaperPosition(
            mint=p.mint, symbol=symbol or p.symbol, name=name,
            opened_at=p.opened_at, notional_usd=p.notional_usd,
            open_fill=p.open_fill, last_quote=p.last_quote,
            peak_quote=p.peak_quote, closed_at=p.closed_at,
            close_reason=p.close_reason, pnl_usd=pnl, net_return=net,
            voided=bool(voided),
            liq_open_usd=p.liq_open_usd, liq_close_usd=p.liq_close_usd,
            impact_open=p.impact_open, impact_close=p.impact_close,
            excluded=p.excluded,
            restated=restatement.reason if restatement else None,
            was_pnl_usd=restatement.was_pnl_usd if restatement else None,
            was_net_return=restatement.was_net_return if restatement else None)

    closed_out = [out(r) for r in closed_rows]
    sized = await _size_trades(db, rows=closed_rows, out_rows=closed_out,
                               ticket=ticket, split=split)

    return PaperBookOut(
        running=config.paper_enabled(),
        book=book,
        filter_description=(_filter_description()
                            if book == config.PAPER_BOOKS[1] else ""),
        # Quantised HERE, not left to the renderer: an unrounded Decimal
        # serialises as 1023.223558651711844672524598 and reads as false
        # precision on a figure that is only ever dollars and cents.
        starting_usd=account.starting.quantize(cents),
        equity_usd=account.equity.quantize(cents),
        realised_usd=account.realised.quantize(cents),
        unrealised_usd=account.unrealised.quantize(cents),
        pnl_usd=account.pnl.quantize(cents),
        return_pct=account.return_pct,
        open_positions=account.open_positions,
        closed_positions=account.closed_positions,
        wins=account.wins,
        voided=account.voided,
        max_slots=config.PAPER_MAX_SLOTS,
        notional_usd=config.PAPER_NOTIONAL_USD,
        trailing_pct=config.PAPER_TRAILING_PCT,
        take_profit_x=config.PAPER_TAKE_PROFIT_X,
        max_hold_minutes=config.PAPER_MAX_HOLD_MINUTES,
        gate_started=config.PAPER_GATE_STARTED,
        gate_weeks=config.PAPER_GATE_WEEKS,
        gate_min_pf=config.PAPER_GATE_MIN_PF,
        gate_min_trades=config.PAPER_GATE_MIN_TRADES,
        gate_max_token_share=config.PAPER_GATE_MAX_TOKEN_SHARE,
        profit_factor=account.profit_factor,
        top_token_share=account.top_token_share,
        cost_pct_per_side=book_costs.side_fraction.quantize(Decimal("0.0001")),
        open_trades=[out(r) for r in open_rows],
        closed_trades=closed_out,
        **sized,
    )


@lru_cache(maxsize=1)
def _wallet_sizes() -> frozenset[tuple[float, int]]:
    """The (ticket, split) pairs the board offers, and nothing else.

    The endpoint answers for a size the page can actually show, so a caller
    cannot invent a wallet the leaderboard never walked and compare the two.
    """
    base = float(config.PAPER_NOTIONAL_USD)
    return frozenset({(base / n, n) for n in config.WALLET_SPLITS}
                     | {(float(t), 1) for t in config.WALLET_LARGER})


async def _size_trades(db: AsyncSession, *, rows: Sequence[Any],
                       out_rows: list[PaperPosition], ticket: float | None,
                       split: int) -> dict[str, Any]:
    """Stamp each trade with what the reader's wallet size made on it.

    The panel used to show $100 fills whatever size the board was set to, so a
    reader who picked $10 x 10 saw the row say +14% and every trade under it
    say $100. Both were right and they looked like a contradiction.

    One walk, not a scaling: the same `_funded_walk` the row above runs, over
    the same trades in the same order, so a trade the small wallet could not
    pay for is marked rather than silently divided by ten.
    """
    if ticket is None:
        return {}
    eligible = [r[0] for r in rows
                if r[0].excluded is None and r[0].net_return is not None
                and r[0].close_quote and r[0].close_quote > 0
                and r[0].notional_usd and r[0].notional_usd > 0
                and r[0].closed_at is not None
                and r[0].closed_at >= datetime.now(UTC) - timedelta(days=7)
                and r[0].sol_usd_at_open is not None
                and config.SOL_USD_MIN <= r[0].sol_usd_at_open <= config.SOL_USD_MAX]
    eligible.sort(key=lambda p: (p.opened_at, p.id))
    rate = await db.scalar(
        select(GradPostgradSample.price_usd / GradPostgradSample.price_native)
        .where(GradPostgradSample.price_usd > 0,
               GradPostgradSample.price_native > 0)
        .order_by(GradPostgradSample.ts.desc()).limit(1))
    walk = _funded_walk(
        [(p.opened_at, p.closed_at, float(p.net_return),
          float(p.impact_open or 0), float(p.impact_close or 0))
         for p in eligible],
        rate, ticket=ticket, start=ticket * split)
    cents = Decimal("0.01")
    by_mint = {p.mint: value for p, value in zip(eligible, walk.pnl, strict=True)}
    for row in out_rows:
        if row.mint not in by_mint:
            continue
        value = by_mint[row.mint]
        row.size_funded = value is not None
        row.size_pnl_usd = (Decimal(str(value)).quantize(cents)
                            if value is not None else None)
    return {
        "size_ticket_usd": Decimal(str(ticket)),
        "size_start_usd": Decimal(str(ticket * split)),
        "size_end_usd": Decimal(str(walk.cash)).quantize(cents),
        "size_funded": walk.funded,
        "size_skipped": walk.skipped,
    }


@router.get("/paper/trades", response_model=PaperBookOut)
async def paper_trades(book: str = "E05_hold_5m",
                       ticket: float | None = None, split: int = 1,
                       db: AsyncSession = Depends(get_db)) -> PaperBookOut:
    """Every closed trade, not just the recent ones.

    Its own route rather than a bigger `/status`, because the board polls
    status every thirty seconds and the trade history only grows. Sorting is
    the page's job: the whole list is here, so it can order without asking
    again.
    """
    if not config.enabled():
        return PaperBookOut()
    from app.labs.graduation.tournament import BY_NAME

    if book not in BY_NAME:
        return PaperBookOut(book=book)
    if ticket is not None and (ticket, split) not in _wallet_sizes():
        raise HTTPException(
            status_code=422,
            detail="ticket/split must be one of the board's wallet sizes")
    return await _paper(db, book=book, limit=None, ticket=ticket, split=split)


#: How far every graduated token got, from its pool open to its HIGHEST
#: recorded price in the hour after.
#:
#: Peaks, not outcomes. Reaching 5x is not earning 5x — it needs the top
#: called to the minute — so the same query returns where the tokens actually
#: ENDED, which is the number that belongs next to it.
#:
#: Multi-pool series are excluded: a mint whose marks crossed pools shows a
#: "peak" that is a change of denomination, which is how one token appeared
#: to do 162x in a minute.
_RETURNS_SQL = text("""
WITH pairs AS (
    SELECT mint, count(DISTINCT pair_address) AS np
      FROM grad_postgrad_samples WHERE price_native > 0 GROUP BY mint),
opened AS (
    SELECT DISTINCT ON (mint) mint, price_native AS op
      FROM grad_postgrad_samples WHERE price_native > 0 ORDER BY mint, ts),
peaked AS (
    SELECT mint, max(price_native) AS pk
      FROM grad_postgrad_samples WHERE price_native > 0 GROUP BY mint),
ended AS (
    SELECT DISTINCT ON (mint) mint, price_native AS lp
      FROM grad_postgrad_samples WHERE price_native > 0 ORDER BY mint, ts DESC),
m AS (
    SELECT o.mint, p.pk / o.op AS x, e.lp / o.op AS final
      FROM opened o
      JOIN peaked p USING (mint)
      JOIN ended e USING (mint)
      JOIN pairs USING (mint)
     WHERE pairs.np = 1)
SELECT
    count(*)                                                   AS usable,
    count(*) FILTER (WHERE x >= 1.5)                           AS over_1_5x,
    count(*) FILTER (WHERE x >= 2)                             AS over_2x,
    count(*) FILTER (WHERE x >= 3)                             AS over_3x,
    count(*) FILTER (WHERE x >= 5)                             AS over_5x,
    count(*) FILTER (WHERE x >= 10)                            AS over_10x,
    count(*) FILTER (WHERE x >= 50)                            AS over_50x,
    count(*) FILTER (WHERE x >= 100)                           AS over_100x,
    count(*) FILTER (WHERE final < 1)                          AS ended_below,
    count(*) FILTER (WHERE final < 0.1)                        AS ended_down_90,
    max(x)                                                     AS best
  FROM m
""")


class ReturnTier(BaseModel):
    """One "reached at least this" tier. Cumulative, so the tiers nest."""

    label: str
    reached: int


class Returns(BaseModel):
    """What the recorded population actually did, with its denominator.

    The denominator is published because it is most of the story: 20,529
    tokens were seen and a few hundred have a usable price series, so a
    percentage quoted against the wrong one is off by a factor of thirty.
    """

    running: bool = False
    seen: int = 0
    migrated: int = 0
    priced: int = 0
    excluded_multi_pool: int = 0
    usable: int = 0
    tiers: list[ReturnTier] = []
    #: The counterweight to the tiers. A peak is not an outcome.
    ended_below_open: int = 0
    ended_down_90: int = 0
    best_multiple: Decimal | None = None


@router.get("/returns", response_model=Returns)
async def returns(db: AsyncSession = Depends(get_db)) -> Returns:
    """How far each graduated token got, and where it ended up."""
    if not config.enabled():
        return Returns()
    row = (await db.execute(_RETURNS_SQL)).one()
    priced = int(await db.scalar(
        select(func.count(func.distinct(GradPostgradSample.mint)))
        .where(GradPostgradSample.price_native > 0)) or 0)
    return Returns(
        running=True,
        seen=int(await db.scalar(select(func.count()).select_from(GradToken)) or 0),
        migrated=int(await db.scalar(
            select(func.count(func.distinct(GradMigration.mint)))) or 0),
        priced=priced,
        excluded_multi_pool=priced - int(row.usable or 0),
        usable=int(row.usable or 0),
        tiers=[
            ReturnTier(label="1.5x", reached=int(row.over_1_5x or 0)),
            ReturnTier(label="2x", reached=int(row.over_2x or 0)),
            ReturnTier(label="3x", reached=int(row.over_3x or 0)),
            ReturnTier(label="5x", reached=int(row.over_5x or 0)),
            ReturnTier(label="10x", reached=int(row.over_10x or 0)),
            ReturnTier(label="50x", reached=int(row.over_50x or 0)),
            ReturnTier(label="100x", reached=int(row.over_100x or 0)),
        ],
        ended_below_open=int(row.ended_below or 0),
        ended_down_90=int(row.ended_down_90 or 0),
        best_multiple=(Decimal(row.best).quantize(Decimal("0.1"))
                       if row.best is not None else None),
    )


class SplitWallet(BaseModel):
    """The funded wallet at another size: `start_usd` traded in `split` equal
    tickets of `ticket_usd`.

    Same trades, same rule (`live_spec.fundable`). The $100 wallet split into
    smaller tickets loses less to a rug and makes less on everything else; the
    flat network fee is a bigger share of a small ticket, and it moves the pool
    less. A bigger wallet ($200 x 1 ...) moves the pool further on every trade.
    $100 x 1 is `wallet_funded_usd`.
    """

    split: int
    ticket_usd: Decimal
    start_usd: Decimal
    wallet_usd: Decimal
    trades_funded: int
    trades_skipped: int
    #: The lowest the wallet stood at any close, open trades at cost: what
    #: the worst run of this arm's history did to an account this size.
    low_usd: Decimal


class ArmRow(BaseModel):
    """One arm's standing. Everything is realised — open positions are not
    counted, because an unrealised number is what every blown-up book in this
    platform's history was leading on."""

    name: str
    note: str = ""
    entry: str = ""
    #: The rule in full, in words: what it buys and when it sells. Built from
    #: the Arm itself, so the page cannot describe a rule the code is not
    #: running.
    entry_rule: str = ""
    exit_rule: str = ""
    hold_minutes: int = 0
    take_profit_x: Decimal | None = None
    trailing_pct: Decimal | None = None
    is_control: bool = False
    trades: int = 0
    wins: int = 0
    realised_usd: Decimal = Decimal(0)
    mean_pct: Decimal | None = None
    profit_factor: Decimal | None = None
    top_token_share: Decimal | None = None
    open_positions: int = 0
    #: Realised P&L as a percentage of the arm's $1,000 capital.
    return_pct: Decimal = Decimal(0)
    #: Capital + realised + open positions marked to their last price. The
    #: number a real account would show, and the only one on this row that
    #: includes anything not yet banked — `realised_usd` deliberately does not.
    equity_usd: Decimal = Decimal(0)
    unrealised_usd: Decimal = Decimal(0)
    #: What a REAL $100 wallet would hold, having taken these same trades.
    #:
    #: Not the tournament's equity divided by ten. That book is ADDITIVE —
    #: $100 a slot out of $1,000, so a -99% costs a tenth. A $100 account is
    #: fully invested and COMPOUNDS, spread over `WALLET_DEMO_SLOTS`
    #: positions of a tenth of equity each.
    #:
    #: The spread is what keeps it alive. At one position per account a -99%
    #: is terminal and 65 of 69 arms end at zero; at ten, none do.
    wallet_100_usd: Decimal = Decimal(0)
    #: The same $100, but only taking trades it could actually FUND.
    #:
    #: `wallet_100_usd` above counts every trade the arm made, because that is
    #: what scores a rule. A real account cannot buy a second token with money
    #: already in the first, so when signals overlap it skips them — and the
    #: page used to print "what a real $100 wallet would have made" under a
    #: number that had taken 212 trades an account could only fund 139 of.
    #: Both are correct; only this one is achievable.
    wallet_funded_usd: Decimal = Decimal(0)
    trades_funded: int = 0
    trades_skipped: int = 0
    #: The same wallet at every split of `config.WALLET_SPLITS` and at each
    #: bigger size in `config.WALLET_LARGER`. Shown, never ranked on: the
    #: leader and the gate stay on the $100 ticket.
    splits: list[SplitWallet] = []
    #: Hours since this arm's OWN first trade — not the board clock, which
    #: measures from the newest arm so that every arm is compared over a window
    #: they all traded in. A row that has been running three days and one that
    #: started this morning are not the same evidence, and the board's single
    #: clock cannot say so.
    arm_hours: Decimal = Decimal(0)
    #: When this arm opened its FIRST position. `arm_hours` is this minus now,
    #: computed server-side and therefore frozen between polls; the timestamp
    #: lets the page tick a live clock instead of showing a figure that jumps
    #: every thirty seconds.
    first_trade_at: datetime | None = None
    #: The worst single trade the arm has taken. The number that decides the
    #: figure above, because compounding has no memory of the good ones.
    worst_trade_pct: Decimal | None = None
    #: Where the $100 WALLET lands after thirty days of the same rule at the
    #: same trade rate — median balance, and the 5th-95th percentile band.
    #:
    #: A BALANCE, not a gain, and in the same dollars as `wallet_100_usd`:
    #: $41 means the wallet is down to $41. It used to be a gain on a $1,000
    #: book sitting one column away from a $100 balance.
    #:
    #: The band is the point. A projection from a few dozen trades is mostly
    #: an artefact of which tokens happened to arrive, and a single number
    #: would hide that behind a decimal point.
    #: The wallet's median balance at each horizon, from ONE simulated path per
    #: draw: the same walk is measured at a day, a week, a fortnight and a
    #: month, so the four figures are consistent with each other by
    #: construction rather than four separate guesses.
    projected_1d_usd: Decimal | None = None
    projected_1w_usd: Decimal | None = None
    projected_15d_usd: Decimal | None = None
    projected_30d_usd: Decimal | None = None
    projected_30d_low: Decimal | None = None
    projected_30d_high: Decimal | None = None
    #: The token's own move per trade, BEFORE execution — and what execution
    #: took, which is the difference between this and `mean_pct`.
    #:
    #: On the board because the two failures look identical in the net figure
    #: and need opposite responses. Measured over three days: pools under $75k
    #: cost 3.24% a round trip, $75k-$116k cost 1.30%, and deeper than $116k
    #: cost 1.06% — of which only 0.175% is price impact. The rest is fees,
    #: which no entry rule can filter away.
    #:
    #: The consequence is the bar this lab is really chasing: the best gross
    #: edge measured anywhere is +0.60%, against a cheapest toll of 1.06%. An
    #: arm whose GROSS is under its COST cannot be profitable however good its
    #: entry rule is.
    gross_pct: Decimal | None = None
    cost_pct: Decimal | None = None
    projected_trades: int = 0
    #: Share of simulated paths in which the wallet fell below the size at
    #: which a position is worth placing — and over how many days, because a
    #: wipeout rate over a week is not one over a month.
    ruin_pct: Decimal | None = None
    ruin_days: int = 0


class Leaderboard(BaseModel):
    """Fifty arms, eight of which cannot have an edge.

    `control_band` is the best $100 WALLET among those eight — the same
    dollars as every other money figure on the board. A leader that
    has not cleared it has not beaten chance, and `leader_beats_controls` says
    so in one boolean rather than leaving it to the reader's optimism.
    """

    running: bool = False
    started_at: datetime | None = None
    arms: list[ArmRow] = []
    controls: list[ArmRow] = []
    control_band: Decimal | None = None
    best_control: str = ""
    leader: str = ""
    leader_beats_controls: bool = False
    #: The gate a leader must clear to be called. Stated here, not in prose.
    min_trades: int = 0
    #: The PF required OF THIS LEADER, at its own trade count — the 95th
    #: percentile of the best-of-42 profit factor when every arm is noise.
    #: A flat bar would be answering a question nobody asked: the tournament
    #: reports a maximum of forty-two draws, not a single strategy.
    required_profit_factor: Decimal = Decimal(0)
    max_token_share: Decimal = Decimal(0)
    called: bool = False
    verdict: str = ""
    total_trades: int = 0
    notional_usd: Decimal = Decimal(0)
    capital_usd: Decimal = Decimal(0)
    #: The starting balance the `wallet_100_usd` column simulates, and how
    #: many positions it spreads over.
    wallet_demo_usd: Decimal = Decimal(0)
    wallet_demo_slots: int = 0
    #: How long the tournament has been running. The projection is meaningless
    #: below an hour and barely better above it, so the reader is told.
    hours_running: Decimal = Decimal(0)
    #: The 2026-09-16 restatement of the board's closed trades: how many were
    #: rebooked, how many of those were never graduations and now count for
    #: nothing, and how many exits moved to a price taken after they were due.
    restated_rule: str = ""
    restated_trades: int = 0
    restated_excluded: int = 0
    restated_repriced: int = 0
    #: Of the repriced: exits that fell after the pool had been drained. Those
    #: trades are LEFT OUT of every figure (operator's instruction), and
    #: `restated_rugged_usd` is what they really lost.
    restated_collapsed: int = 0
    restated_rugged_usd: Decimal = Decimal(0)


#: Thirty-day projections, memoised. `(computed_at, {arm: fields})`.
#:
#: The simulation is 160 paths over a thirty-day horizon for every arm that
#: has enough trades, and its cost grows with the horizon — measured on prod
#: at 1,955 ms, then 2,279, then 2,577 across three consecutive calls as the
#: trade rate climbed. That is precisely the "slows down later" shape, on an
#: endpoint the board polls every thirty seconds.
#:
#: A forecast of the next month does not change meaningfully in two minutes,
#: so it is computed at most that often. Everything else on the leaderboard —
#: P&L, trade counts, the gate — stays live on every request.
_PROJECTIONS: tuple[datetime, dict[str, dict[str, Any]]] | None = None
_PROJECTION_TTL = timedelta(minutes=2)


class Walk(NamedTuple):
    cash: float
    funded: int
    skipped: int
    took: list[tuple[datetime, float]]
    low: float
    #: Dollars this wallet made or lost on each trade it was offered, in the
    #: order it met them; `None` where it had no free money and skipped. The
    #: trade list renders these, so the rows and the wallet figure beside them
    #: come from one walk rather than two models that can disagree.
    pnl: tuple[float | None, ...]


def _multiple(ret: float, impact: Sequence[float], k: float) -> float:
    """What a trade measured at $100 returns per dollar at `k` times that size,
    before the network fee (`_size_penalty` charges that).

    Impact is linear in order size (`backtest.amm_impact`), so an order `k`
    times as large moves the pool `k` times as far on both legs. `impact` is
    the trade's recorded (open, close) impact, empty when unknown. At k == 1
    this is exactly `1 + ret`.
    """
    gross = 1.0 + ret
    if impact and k != 1.0:
        i_open, i_close = impact
        gross *= ((1 + i_open) / (1 + k * i_open)
                  * (1 + i_close) / (1 + k * i_close))
    return gross


def _low_through(cash: float, held: list[tuple[datetime, float, float]],
                 due: list[tuple[datetime, float, float]]) -> float:
    """The lowest the account stands while `due` closes in time order, with
    everything still open counted at cost."""
    equity = cash + sum(h[2] for h in held) + sum(h[2] for h in due)
    low = equity
    for _, r, size in sorted(due, key=lambda h: h[0]):
        equity += size * (r - 1)
        low = min(low, equity)
    return low


def _funded_walk(
    trades: Sequence[tuple], rate: Decimal | None = None,
    ticket: float | None = None, start: float | None = None,
) -> Walk:
    """What a real $100 account could have taken — equity, funded, skipped,
    and the lowest it stood.

    `trades` are (opened, closed, return[, impact_open, impact_close]).
    `ticket` changes the stake from `PAPER_NOTIONAL_USD`, and the floor
    scales with it (`wallet_floor`); `start` is the opening balance
    (`WALLET_DEMO_USD` unless given).

    `_wallet_walk` walks the arm's returns one after another and never asks
    whether the account could have held them at the same time. That is right
    for scoring a RULE: every trade the arm made is counted, so the comparison
    between arms is not decided by which overlapping signal an account happened
    to be free for.

    Returns the funded trades as well, because the PROJECTION has to be built
    from the same set: forecasting the rule's trade rate onto an account that
    can only fund two thirds of them overstates by exactly the gap.

    It is wrong for the sentence the page prints beside it. A $100 account
    holding one $100 position has no money for a second, so when signals
    overlap it must SKIP them — measured on B3_198k_5m, 73 of 212. Reported
    separately rather than replacing the other, because the two answer
    different questions and putting one number under both was the defect.

    Slots are not configured here; they emerge from cash, which is the same
    thing a wallet does. The ticket never grows past `PAPER_NOTIONAL_USD`: the
    returns were measured at that size and a larger order pays more impact.
    """
    base = float(config.PAPER_NOTIONAL_USD)
    cap = base if ticket is None else ticket
    floor = config.wallet_floor(cap)
    cash = float(config.WALLET_DEMO_USD) if start is None else start
    low = cash
    held: list[tuple[datetime, float, float]] = []
    #: (closed_at, return) for every trade the account could pay for. The
    #: projection is built from THESE, so the forecast and the column beside it
    #: describe the same account rather than two different ones.
    took: list[tuple[datetime, float]] = []
    pnl: list[float | None] = []
    funded = skipped = 0
    for opened, closed, ret, *impact in trades:
        due = [h for h in held if h[0] <= opened]
        if due:
            held = [h for h in held if h[0] > opened]
            low = min(low, _low_through(cash, held, due))
            for _, r, size in due:
                cash += size * r
        # The wallet's own rule (`live_spec.fundable`), so this balance is the
        # one the real wallet would reach. Rounded to shed float dust that
        # would otherwise make a whole ticket read a hair short.
        stake = live_spec.fundable(round(cash, 9), holding=bool(held),
                                   ticket=cap, floor=floor)
        if stake is None:
            skipped += 1
            pnl.append(None)
            continue
        cash -= stake
        multiple = (_multiple(ret, impact, stake / base)
                    - _size_penalty(stake, base, rate))
        held.append((closed, multiple, stake))
        took.append((closed, ret))
        pnl.append(stake * (multiple - 1.0))
        funded += 1
    low = min(low, _low_through(cash, [], held))
    for _, r, size in held:
        cash += size * r
    return Walk(cash, funded, skipped, took, low, tuple(pnl))


def _wallet_walk(returns: Iterable[float],
                 rate: Decimal | None = None) -> tuple[float, bool]:
    """Walk the $100 wallet through these returns; equity and whether it died.

    ONE model, two callers — the leaderboard's money column and its thirty-day
    projection. They disagreed before this existed: the column compounded $100
    over ten slots while the projection added fixed $100 positions to a $1,000
    book, so the same arm read $152 in one column and +$23,876 in the next.
    Two currencies on one row is not a forecast, it is a typo with decimals.

    Each position is a TENTH of current equity, so the account compounds and no
    single trade ends it. It stops below `WALLET_MIN_USD / slots`, the point at
    which the next position is too small to be worth placing.

    An element of `returns` is ONE STEP, which is one trade for the column
    (the real sequence, in order) and the sum of a ten-position block for the
    projection (ten slots really do resolve together). The formula is the same
    either way, which is the point of having one function.

    `rate` is SOL/USD, and without it the walk charges no size penalty — the
    old behaviour, kept only so a caller with no rate in hand still returns a
    number rather than raising. Every caller that can get one should.

    A position stops growing at `PAPER_NOTIONAL_USD`, and that cap is evidence
    rather than caution: every return here was MEASURED at a $100 order, and
    the shallowest decile of pools this lab trades holds $15.9k, so $100 pays
    1.3% of impact a leg and $800 pays 10.1% — past the size at which the lab
    refuses to fill at all. Uncapped, a 1.6%-per-trade arm compounds $100 into
    $1.4bn over a month of trades, which is arithmetic, not a forecast. Above
    $100 a position there is no evidence, and the impact curve says what there
    is would be worse.
    """
    slots = max(1, config.WALLET_DEMO_SLOTS)
    equity = float(config.WALLET_DEMO_USD)
    floor = float(config.WALLET_MIN_USD) / slots
    cap = float(config.PAPER_NOTIONAL_USD)
    base = float(config.PAPER_NOTIONAL_USD)
    for r in returns:
        position = min(equity / slots, cap)
        equity += position * (r - _size_penalty(position, base, rate))
        if equity < floor:
            return 0.0, True
    return equity, False


@lru_cache(maxsize=64)
def _fee_shape(measured_at_usd: float, rate_str: str) -> tuple[float, float]:
    """The cost curve as (flat, priority_usd), solved once per rate.

    `costs()` builds Decimals, and calling it twice per step inside the wallet
    walk took the leaderboard from 3s to 30s — past every browser timeout, so
    the board simply did not load. The model is exactly linear in 1/size (a
    flat swap fee plus a priority fee fixed in SOL), so two evaluations pin it
    and the inner loop becomes float arithmetic:

        side(s) = flat + priority / s

    Verified against the model at four sizes, at SOL $100 and the current
    `BACKTEST_PRIORITY_FEE_QUOTE` (0.0001075 SOL a side): $100 0.611%,
    $50 0.622%, $25 0.643%, $10 0.708% a leg. The figures this docstring
    carried before — 0.705%, 0.909%, 1.318%, 2.546% — were measured when that
    fee was 0.002 SOL, twenty times too high, and they made every small size
    look far worse than it is. The live wallet's own network fee is smaller
    still: 14,500 lamports a round trip on 2026-09-17, about $0.0015.
    """
    rate = Decimal(rate_str)
    a, b = 100.0, 10.0
    sa = float(costs(Decimal(str(a)) / rate).side_fraction)
    sb = float(costs(Decimal(str(b)) / rate).side_fraction)
    priority = (sa - sb) / (1.0 / a - 1.0 / b)
    flat = sa - priority / a
    return flat, priority


def _size_penalty(position_usd: float, measured_at_usd: float,
                  rate: Decimal | None) -> float:
    """What a position of THIS size pays beyond what the measured one did.

    Every return handed to this walk was priced on a $100 order. A smaller
    order does not cost what a $100 order costs, because the priority fee is
    flat in SOL and its share grows as the order shrinks:

        $100  0.611% a leg    $50  0.622%    $25  0.643%    $10  0.708%

    Small at today's fee, and the correction matters most at $1-$2 a trade
    (+2.1% a round trip at $1). It was large when this was written, because
    the fee was then 0.002 SOL a side: charging $100 execution to a $10
    position understated the round trip by 3.68% per trade and turned the
    leaderboard's best arm from $88.84 into $121.04. Kept because the shape is
    right whatever the fee is, and the fee is a setting.

    Returned as the EXCESS over the size the returns were measured at, so a
    wallet whose position happens to be $100 pays nothing extra and the walk
    stays identical to what it was.
    """
    if rate is None or position_usd <= 0:
        return 0.0
    _flat, priority = _fee_shape(measured_at_usd, str(rate))
    # Only the priority term differs between sizes; the flat fee cancels.
    return 2.0 * (priority / position_usd - priority / measured_at_usd)


@router.get("/tournament", response_model=Leaderboard)
async def tournament(db: AsyncSession = Depends(get_db)) -> Leaderboard:
    """The leaderboard. One grouped read, not fifty."""
    if not config.enabled():
        return Leaderboard()

    closed = (await db.execute(
        select(GradPaperPosition.book,
               func.count().label("trades"),
               func.count().filter(GradPaperPosition.pnl_usd > 0).label("wins"),
               func.coalesce(func.sum(GradPaperPosition.pnl_usd), 0).label("pnl"),
               func.coalesce(func.sum(GradPaperPosition.pnl_usd).filter(
                   GradPaperPosition.pnl_usd > 0), 0).label("gross_up"),
               func.coalesce(-func.sum(GradPaperPosition.pnl_usd).filter(
                   GradPaperPosition.pnl_usd < 0), 0).label("gross_down"),
               func.max(GradPaperPosition.pnl_usd).label("best"),
               func.avg(GradPaperPosition.net_return).label("mean"),
               func.min(GradPaperPosition.opened_at).label("first"),
               # The token's own move, before execution took its cut. The
               # difference between this and `mean` is the whole toll — fees
               # and impact together — and without it a losing arm cannot be
               # told apart from a winning arm that paid its edge away.
               func.avg(GradPaperPosition.close_quote
                        / GradPaperPosition.open_quote - 1).label("gross"))
        .where(GradPaperPosition.closed_at.is_not(None),
               GradPaperPosition.notional_usd > 0,
               GradPaperPosition.close_quote > 0,
               GradPaperPosition.open_quote > 0,
               # A restated trade that was never a graduation is shown on its
               # arm's panel and counted nowhere, here included.
               GradPaperPosition.excluded.is_(None))
        .group_by(GradPaperPosition.book))).all()
    stats = {r.book: r for r in closed}

    # Per-trade returns, for the projection band. Aggregates cannot give it:
    # the spread of thirty days depends on the SHAPE of an arm's returns, and
    # this market's shape is hundreds of small gains against a few wipeouts.
    # Bounded to a week. Unbounded this grows without limit, and a projection
    # built from month-old trades would be describing a market that has moved
    # on — the recent window is both cheaper and more honest.
    # ORDERED, because one consumer compounds them and compounding is not
    # commutative once a trade can take the account to zero.
    # SOL/USD, so the wallet can charge what ITS position size really costs.
    # Observed rather than fetched: the newest sample carrying both prices,
    # which keeps the figure inside the data the rest of the board trusts.
    sol_rate = await db.scalar(
        select(GradPostgradSample.price_usd / GradPostgradSample.price_native)
        .where(GradPostgradSample.price_usd > 0,
               GradPostgradSample.price_native > 0)
        .order_by(GradPostgradSample.ts.desc()).limit(1))

    per_arm: dict[str, list[float]] = {}
    #: The same returns, grouped by the HOUR they closed in. Trades inside one
    #: hour are the same market, not independent draws, and the projection's
    #: uncertainty has to be measured between hours rather than between trades.
    per_arm_hourly: dict[str, dict[datetime, list[float]]] = {}
    #: Entry and exit times as well as the return, because whether an account
    #: could have HELD two trades at once is a fact about their overlap.
    per_arm_trades: dict[str, list[tuple[datetime, datetime, float, float, float]]] = {}
    for book, ret, closed_at, opened_at, i_open, i_close in (await db.execute(
            select(GradPaperPosition.book, GradPaperPosition.net_return,
                   GradPaperPosition.closed_at, GradPaperPosition.opened_at,
                   GradPaperPosition.impact_open, GradPaperPosition.impact_close)
            .where(GradPaperPosition.closed_at.is_not(None),
                   GradPaperPosition.closed_at >= datetime.now(UTC) - timedelta(days=7),
                   GradPaperPosition.notional_usd > 0,
                   GradPaperPosition.close_quote > 0,
                   # SOL-QUOTED ONLY. `sol_usd_at_open` is the pool's quote
                   # currency in dollars, stored at entry — 1.00 for a
                   # stablecoin pair. Those trades happened and their returns
                   # are right, but a SOL wallet could not have reached them in
                   # one hop, and the board claims it could. Filtered at read
                   # time rather than rewritten: the rows stay exactly as they
                   # closed, and lifting the band shows them again.
                   GradPaperPosition.sol_usd_at_open >= config.SOL_USD_MIN,
                   GradPaperPosition.sol_usd_at_open <= config.SOL_USD_MAX,
                   GradPaperPosition.net_return.is_not(None),
                   GradPaperPosition.excluded.is_(None))
            # In the order a wallet MEETS them: by entry, then by id. Ordered
            # by close, trades closed in the same tick came back in whatever
            # order the table gave, and the funded wallet — which takes one
            # and skips the other — read anywhere from $220 to $240 on the
            # same 225 trades.
            .order_by(GradPaperPosition.opened_at, GradPaperPosition.id))).all():
        per_arm.setdefault(book, []).append(float(ret))
        per_arm_trades.setdefault(book, []).append(
            (opened_at, closed_at, float(ret),
             float(i_open or 0), float(i_close or 0)))
        (per_arm_hourly.setdefault(book, {})
         .setdefault(closed_at.replace(minute=0, second=0, microsecond=0), [])
         .append(float(ret)))

    def wallet_100(returns: list[float]) -> tuple[Decimal, Decimal | None]:
        """A $100 account taking EVERY trade the arm made, one after another.

        `WALLET_DEMO_SLOTS` is 1, so each position is the whole account capped
        at `PAPER_NOTIONAL_USD` — the "ten positions of a tenth each" this
        docstring used to describe has not been the behaviour since the slot
        count changed, and the sentence outlived the code.

        It models no concurrency: overlapping trades are walked in sequence as
        though the account were free for all of them. That is deliberate and it
        is what makes this the number to COMPARE arms on — every arm is scored
        on every trade it made. `wallet_funded_usd` is the achievable twin.

        It stops at `WALLET_MIN_USD`, and that floor is load-bearing rather
        than tidy: without it a wallet reduced to a few dollars "recovers" on
        later winners it could never have placed — a test caught exactly that,
        compounding $2.65 back to nine figures.

        The returns are the tournament's, taken at $100 a position. A $10
        order pays a wider spread, so this is the optimistic reading of the
        smaller size; the sizing comparison that chose ten re-priced every
        trade properly, and ten won there too.
        """
        if not returns:
            return config.WALLET_DEMO_USD, None
        equity, _ = _wallet_walk(returns, sol_rate)
        return (Decimal(str(equity)).quantize(Decimal("0.01")),
                Decimal(str(min(returns) * 100)).quantize(Decimal("0.1")))
    open_now: dict[str, int] = {}
    unrealised: dict[str, Decimal] = {}
    for position in (await db.scalars(
            select(GradPaperPosition)
            .where(GradPaperPosition.closed_at.is_(None),
                   GradPaperPosition.notional_usd > 0,
                   GradPaperPosition.excluded.is_(None)))).all():
        open_now[position.book] = open_now.get(position.book, 0) + 1
        # Marked to the last recorded price, at the rate captured when the
        # position opened — the same arithmetic the closed rows use, so equity
        # does not change shape the moment a position closes.
        live = net_return(position, position.last_quote)
        if live is not None:
            unrealised[position.book] = (unrealised.get(position.book, Decimal(0))
                                         + position.notional_usd * live)
    # How long every arm has been running TOGETHER — the newest arm's first
    # trade, not the oldest arm's.
    #
    # It was `min(opened_at)` over every row ever written, so it counted from a
    # generation that has since been retired: the board read "running 35.9h"
    # on arms whose oldest trade was ninety minutes old. Scoping it to the
    # current arms was not enough either, because two of them are carried-over
    # A/B arms with months of history, which would report 36.9h for a board
    # whose newest twelve arms are two hours old.
    #
    # The newest arm's start is the honest figure because it is the only window
    # in which the board is a FAIR COMPARISON. Outside it the arms traded
    # different tokens in different markets, and comparing them there is the
    # error that made a 35-trade arm look like it beat a 166-trade one earlier
    # today.
    firsts = (await db.execute(
        select(func.min(GradPaperPosition.opened_at))
        .where(GradPaperPosition.book.in_([a.name for a in ARMS]))
        .group_by(GradPaperPosition.book))).scalars().all()
    started = max(firsts) if firsts else None
    hours = ((datetime.now(UTC) - started).total_seconds() / 3600
             if started else 0.0)

    global _PROJECTIONS
    fresh = (_PROJECTIONS is not None
             and datetime.now(UTC) - _PROJECTIONS[0] < _PROJECTION_TTL)
    cached: dict[str, dict[str, Any]] = _PROJECTIONS[1] if fresh and _PROJECTIONS else {}

    def project(returns: list[float], hours: float,
                hourly: dict[datetime, list[float]]) -> dict[str, Any]:
        """Thirty days of this arm, as an ACCOUNT rather than a running total.

        The previous version summed per-trade returns and reported bands like
        "-$140,681 from $1,000", which is not a pessimistic forecast — it is an
        impossible one. It kept funding $100 positions after the account was
        empty. An account that cannot pay for the next position stops, and the
        worst thirty days can therefore cost exactly the capital and no more.

        That barrier changes the upside too: a path wiped out on day three does
        not collect the other twenty-seven, so the median is not the mean of an
        unbounded sum.

        `P(ruin)` is the number that matters to anyone about to use real money,
        and the sum of per-trade returns cannot express it at all.

        Sampled in blocks of `PAPER_MAX_SLOTS`, because that is how the account
        actually moves — ten positions are open at once and resolve together —
        and the block sums are drawn once into a pool so the cost does not grow
        with a thirty-day horizon.
        """
        n = len(returns)
        if n < 10 or hours < 1.0:
            return {}
        # The arm's OWN elapsed time, not the board's.
        #
        # Every arm used to share the board clock, which was wrong the moment
        # arms started at different times — and became absurd when the clock
        # was narrowed to the window in which all arms are comparable: an arm
        # whose 190 trades span 37 hours had its rate computed over 3.7, so it
        # projected ten times the trades it takes and $330 from $100 in a day.
        rate = n / hours
        horizon = int(rate * 24 * 30)
        # Resampling the observed trades holds this arm's mean FIXED at the
        # sample mean, so the band answers "which tokens arrive" and silently
        # assumes the edge is real. After a day, the standard error of that
        # mean is usually larger than the mean — the dominant uncertainty is
        # whether there is an edge at all, and a band that omits it is the
        # confident half of the answer. Each path draws its own mean.
        # THE STANDARD ERROR, CLUSTERED BY HOUR.
        #
        # Measured between trades this was `pstdev(returns)/sqrt(n)`, which
        # treats 190 trades as 190 independent draws. They are not: trades
        # inside one hour are the same market moving, so the effective sample
        # is the number of HOURS, not the number of fills. The difference is
        # not cosmetic — with per-trade error a 14-hour arm reported a 30-day
        # band of $5,845 to $11,133 and a 0% chance of ever being wiped out,
        # which is a promise of eighty-fold with no downside.
        #
        # This is the same error, in a new place, as counting 2,223 trades
        # across 79 tokens as 2,223 observations.
        by_hour = [fmean(v) for v in hourly.values() if v] if hourly else []
        if len(by_hour) > 1:
            sem = pstdev(by_hour) / sqrt(len(by_hour))
        else:
            # Under two hours of history there is nothing to measure variation
            # between, and the per-trade figure would understate it. Refuse the
            # projection rather than print a confident one.
            return {}
        # Ten positions are open at once and resolve together, so a step is a
        # block of ten and the block sums are drawn ONCE into a pool. Walking
        # 9,000 individual trades 160 times per arm across fifty arms is 74
        # million iterations inside a web request; this is 148 thousand.
        block = max(1, config.WALLET_DEMO_SLOTS)
        pool = [sum(returns[random.randrange(n)] for _ in range(block))  # noqa: S311
                for _ in range(1024)]
        # A day, a week, a fortnight, a month — as step counts on the same
        # path. Each horizon walks a PREFIX of one drawn sequence rather than
        # being simulated separately, so the four cannot contradict each other:
        # a wallet that is dead at day one is dead at day thirty.
        # A HORIZON IS ONLY SHOWN IF THE DATA REACHES A TENTH OF THE WAY TO IT.
        #
        # Clustering the error by hour barely moved the band, and it should not
        # have: with fourteen hours of consistently positive trades, no honest
        # measure of SAMPLING error produces a negative month. The problem is
        # not the error model, it is that a month is fifty-one times the window
        # observed. Nothing in fourteen hours can speak about thirty days.
        #
        # A tenth is the limit, so: a day needs 2.4 hours behind it, a week
        # needs 17, a fortnight 36, a month 72. Horizons past that are left
        # blank until the history reaches them, which is the difference between
        # a projection and a wish.
        days = tuple(d for d in (1, 7, 15, 30) if hours * 10 >= d * 24)
        if not days:
            return {}
        cuts = {d: max(1, int(rate * 24 * d) // block) for d in days}
        longest = cuts[days[-1]]
        finals: dict[int, list[float]] = {d: [] for d in days}
        ruined = 0
        for _ in range(160):
            drift = random.gauss(0.0, sem) * block
            seq = [pool[random.randrange(1024)] + drift  # noqa: S311
                   for _ in range(longest)]
            for d in days:
                equity, dead = _wallet_walk(seq[:cuts[d]], sol_rate)
                finals[d].append(equity)
                if d == days[-1]:
                    ruined += dead
        for d in days:
            finals[d].sort()

        def at(d: int, p: float) -> Decimal:
            v = finals[d]
            return Decimal(str(v[int(p * (len(v) - 1))])).quantize(Decimal("0.01"))

        out: dict[str, Any] = {"projected_trades": horizon}
        for d, field in ((1, "1d"), (7, "1w"), (15, "15d"), (30, "30d")):
            if d in finals:
                out[f"projected_{field}_usd"] = at(d, 0.50)
        if 30 in finals:
            out["projected_30d_low"] = at(30, 0.05)
            out["projected_30d_high"] = at(30, 0.95)
        # Ruin is counted on the LONGEST horizon actually simulated, and the
        # page says which — a wipeout rate over a week is not a wipeout rate
        # over a month and must not be read as one.
        out["ruin_days"] = days[-1]
        out["ruin_pct"] = (Decimal(ruined) / Decimal(len(finals[days[-1]])) * 100
                           ).quantize(Decimal("0.1"))
        return out

    def row(arm) -> ArmRow:
        s = stats.get(arm.name)
        pf = top = mean = None
        gross = cost = None
        if s is not None and s.trades and s.gross is not None:
            gross = (Decimal(s.gross) * 100).quantize(Decimal("0.01"))
            if s.mean is not None:
                cost = (gross - (Decimal(s.mean) * 100)).quantize(Decimal("0.01"))
        if s is not None and s.trades:
            if s.gross_down > 0:
                pf = (Decimal(s.gross_up) / Decimal(s.gross_down)).quantize(Decimal("0.01"))
            if s.gross_up > 0 and s.best is not None and s.best > 0:
                top = (Decimal(s.best) / Decimal(s.gross_up)).quantize(Decimal("0.0001"))
            if s.mean is not None:
                mean = (Decimal(s.mean) * 100).quantize(Decimal("0.01"))
        # Hours since THIS arm's first trade. An arm added today must not
        # inherit the trade rate of one that has run since yesterday.
        first = s.first if s is not None else None
        arm_hours = ((datetime.now(UTC) - first).total_seconds() / 3600
                     if first else 0.0)
        open_pnl = unrealised.get(arm.name, Decimal(0)).quantize(Decimal("0.01"))
        wallet, worst = wallet_100(per_arm.get(arm.name, []))
        # ponytail: thirteen walks per arm per request, O(trades) each; move
        # them under `_PROJECTIONS` if the board ever slows.
        mine = per_arm_trades.get(arm.name, [])
        base = float(config.PAPER_NOTIONAL_USD)
        # (ticket, how many tickets the wallet holds), biggest ticket first.
        sizes = sorted([(float(t), 1) for t in config.WALLET_LARGER]
                       + [(base / n, n) for n in config.WALLET_SPLITS],
                       key=lambda size: -size[0]) if mine else [(base, 1)]
        walks = {(t, n): _funded_walk(mine, sol_rate, ticket=t, start=t * n)
                 for t, n in sizes}
        # By NAME, not by position: this unpacked five fields and broke the
        # whole board for fifteen minutes on 2026-09-17 when `Walk` grew a
        # sixth. Nothing here needs the tuple's shape.
        official = walks[(base, 1)]
        funded_usd = official.cash
        n_funded, n_skipped = official.funded, official.skipped
        funded_trades = official.took
        # The forecast now describes the SAME account as the column beside it.
        # Projecting the rule's trade rate onto a $100 wallet overstated by
        # exactly the trades that wallet could never have funded — 73 of 213
        # on the leading arm.
        funded_returns = [r for _, r in funded_trades]
        funded_hourly: dict[datetime, list[float]] = {}
        for closed_at, r in funded_trades:
            (funded_hourly.setdefault(
                closed_at.replace(minute=0, second=0, microsecond=0), [])
             .append(r))
        forecast = (cached.get(arm.name, {}) if fresh
                    else project(funded_returns, arm_hours, funded_hourly))
        realised = (Decimal(s.pnl) if s else Decimal(0)).quantize(Decimal("0.01"))
        return ArmRow(
            name=arm.name, note=arm.note, entry=arm.entry,
            entry_rule=arm.entry_rule, exit_rule=arm.exit_rule,
            hold_minutes=arm.hold,
            take_profit_x=arm.tp, trailing_pct=arm.trail, is_control=arm.is_control,
            trades=int(s.trades) if s else 0, wins=int(s.wins) if s else 0,
            realised_usd=realised,
            mean_pct=mean, gross_pct=gross, cost_pct=cost,
            profit_factor=pf, top_token_share=top,
            open_positions=int(open_now.get(arm.name, 0)),
            return_pct=((realised / config.PAPER_CAPITAL_USD * 100)
                        .quantize(Decimal("0.01"))
                        if config.PAPER_CAPITAL_USD else Decimal(0)),
            wallet_100_usd=wallet, worst_trade_pct=worst,
            wallet_funded_usd=Decimal(str(funded_usd)).quantize(Decimal("0.01")),
            trades_funded=n_funded, trades_skipped=n_skipped,
            splits=[SplitWallet(
                split=n,
                ticket_usd=Decimal(str(t)).quantize(Decimal("0.01")),
                start_usd=Decimal(str(t * n)).quantize(Decimal("0.01")),
                wallet_usd=Decimal(str(w.cash)).quantize(Decimal("0.01")),
                trades_funded=w.funded, trades_skipped=w.skipped,
                low_usd=Decimal(str(w.low)).quantize(Decimal("0.01")),
            ) for (t, n), w in walks.items() if mine],
            arm_hours=Decimal(str(arm_hours)).quantize(Decimal("0.1")),
            first_trade_at=first,
            unrealised_usd=open_pnl,
            equity_usd=(config.PAPER_CAPITAL_USD + realised + open_pnl
                        ).quantize(Decimal("0.01")),
            **forecast)

    # The A/B pair KEEPS TRADING and keeps its judge date; it just does not
    # appear on a leaderboard it is not competing in. Ranking a separate
    # experiment beside the arms is what made "delete the negative ones" the
    # obvious request — and ending a pre-registered experiment early destroys
    # the only property it has.
    rows = [row(a) for a in ARMS if not a.ab_experiment]
    if not fresh:
        _PROJECTIONS = (datetime.now(UTC), {
            r.name: {"projected_1d_usd": r.projected_1d_usd,
                     "projected_1w_usd": r.projected_1w_usd,
                     "projected_15d_usd": r.projected_15d_usd,
                     "projected_30d_usd": r.projected_30d_usd,
                     "projected_30d_low": r.projected_30d_low,
                     "projected_30d_high": r.projected_30d_high,
                     "projected_trades": r.projected_trades,
                     "ruin_pct": r.ruin_pct, "ruin_days": r.ruin_days}
            for r in rows if r.projected_30d_usd is not None})
    # Ranked on the WALLET, which is the money column the board shows. Ranking
    # on the $1,000 book's P&L put "#1" beside a number computed from a
    # different account, and the two can disagree: the book is additive, so it
    # rewards a big win on a dead arm that the wallet never recovers from.
    #
    # An arm that has not traded is not leading. Sorting on money alone ranks a
    # never-traded arm — still holding its full $100 — above every arm that has
    # taken a trade and lost, and the top fills with filters that have simply
    # not matched anything yet.
    # LIVE ARMS FIRST, then the dead, then whatever has not traded.
    #
    # A wiped arm stays on the board deliberately — deleting losers is how a
    # leaderboard becomes flattering by construction, and these rows carry the
    # day's most important finding: every one of them died to a single token
    # while holding the whole wallet. That is the cost of one slot, and it is
    # only visible because they are still here.
    #
    # It also fixes the leader: `leader` takes the first traded row, so without
    # this a wiped arm could be named leader on tie-breaks.
    # Ranked on the FUNDED wallet, because that is the column the board shows
    # and a board ranked by a figure a reader cannot see is the same defect as
    # a figure labelled as something it is not.
    #
    # The cost is real and worth stating: the funded walk skips trades the
    # account could not pay for, and WHICH ones it skips is timing rather than
    # skill. An arm that dodged its losers is flattered here, and one that
    # dodged its winners is punished. `wallet_100_usd` is still computed and
    # still on the API for exactly that comparison — it just no longer decides
    # the order while being invisible.
    rows.sort(key=lambda r: (r.trades > 0, r.wallet_funded_usd > 0,
                             r.wallet_funded_usd), reverse=True)
    traded = [r for r in rows if r.trades]
    control_rows = [r for r in rows if r.is_control]
    # In WALLET dollars, because that is the column the board now shows. As
    # realised P&L this stat contradicted the very dot beside it: the frontend
    # already marked "beats every random arm" on wallet value.
    band = max((r.wallet_funded_usd for r in control_rows if r.trades),
               default=None)
    best_control = next((r.name for r in control_rows
                         if band is not None and r.trades
                         and r.wallet_funded_usd == band), "")
    # ANY arm may lead, baselines included.
    #
    # This excluded controls, which was right when a control was a coin flip —
    # a dice roll cannot be "the winner" of anything. It became wrong the
    # moment the baseline stopped being a dice roll and started being a
    # strategy: on 2026-09-14 `FLOOR_3m` reached profit factor 4.24 against a
    # required 2.99 on 143 trades, the first arm in this lab ever to clear its
    # bar — and the board reported a SIX-trade band arm as the leader, because
    # the thing that was working had been classified as the control.
    #
    # A baseline that wins is the most useful result this lab can produce: it
    # means the edge is in the floor, not in anything clever layered on top.
    leader = next(iter(traded), None)
    # The no-selection arm: every graduation, no floor, no band. Every other
    # arm's population is a subset of its own, so it is what a baseline has to
    # beat when the baseline is itself the leader.
    naked = next((r for r in rows if r.entry == "all" and r.trades), None)

    restated = dict((await db.execute(
        select(GradPaperRestatement.reason, func.count())
        .join(GradPaperPosition,
              GradPaperPosition.id == GradPaperRestatement.position_id)
        .where(GradPaperPosition.book.in_([a.name for a in ARMS
                                           if not a.ab_experiment]))
        .group_by(GradPaperRestatement.reason))).all())
    rule = await db.scalar(select(func.max(GradPaperRestatement.rule)))
    rugged_usd = await db.scalar(
        select(func.coalesce(func.sum(GradPaperPosition.pnl_usd), 0))
        .where(GradPaperPosition.excluded == "rugged",
               GradPaperPosition.book.in_([a.name for a in ARMS
                                           if not a.ab_experiment])))

    board = Leaderboard(
        restated_rule=rule or "",
        restated_trades=sum(restated.values()),
        restated_excluded=restated.get("not_graduation_pool", 0),
        restated_repriced=sum(v for k, v in restated.items()
                              if k not in ("fees", "not_graduation_pool")),
        restated_collapsed=restated.get("pool_collapsed", 0),
        restated_rugged_usd=Decimal(rugged_usd or 0).quantize(Decimal("0.01")),
        running=config.paper_enabled(), started_at=started, arms=rows,
        controls=control_rows, control_band=band, best_control=best_control,
        leader=leader.name if leader else "",
        leader_beats_controls=bool(leader and leader.trades and band is not None
                                   and leader.wallet_funded_usd > band),
        min_trades=config.TOURNEY_MIN_TRADES,
        required_profit_factor=config.required_pf(
            leader.trades if leader else 0),
        max_token_share=config.TOURNEY_MAX_TOKEN_SHARE,
        total_trades=sum(r.trades for r in rows),
        notional_usd=config.PAPER_NOTIONAL_USD,
        capital_usd=config.PAPER_CAPITAL_USD,
        wallet_demo_usd=config.WALLET_DEMO_USD,
        wallet_demo_slots=config.WALLET_DEMO_SLOTS,
        hours_running=Decimal(str(round(hours, 1))),
    )
    if leader is None:
        board.verdict = (
            f"{len(traded)} arms have closed trades; none of them is a "
            "strategy arm yet." if traded else "No arm has closed a trade yet.")
        return board
    fails = []
    # A WHAT-IF IS NEVER CALLED. Trades on pools drained while they were open
    # are left out of these figures on the operator's instruction, and with
    # them out B3_198k_5m cleared every term below. It would not have with
    # them in: the gate certifies a strategy, and a strategy made those trades.
    rugged = await db.scalar(
        select(func.count()).select_from(GradPaperPosition)
        .where(GradPaperPosition.book == leader.name,
               GradPaperPosition.excluded == "rugged"))
    if rugged:
        fails.append(f"{rugged} trades on pools drained while they were open are "
                     f"left out of these figures as a what-if, and a winner is "
                     f"only called on every trade it made")
    need_pf = config.required_pf(leader.trades)
    board.required_profit_factor = need_pf
    if leader.trades < board.min_trades:
        fails.append(f"{leader.trades} trades, needs {board.min_trades}")
    if leader.profit_factor is None or leader.profit_factor < need_pf:
        fails.append(f"profit factor {leader.profit_factor or 0}, needs "
                     f"{need_pf} at {leader.trades} trades — that is what the "
                     f"luckiest of 42 noise arms reaches")
    if leader.top_token_share is not None and leader.top_token_share > board.max_token_share:
        fails.append(f"one token is {leader.top_token_share * 100:.0f}% of its profit, "
                     f"needs under {board.max_token_share * 100:.0f}%")
    if not control_rows:
        fails.append("THERE IS NO BASELINE — every FLOOR arm was retired, so a "
                     "profitable arm here cannot be told apart from a rising "
                     "market. Restoring one baseline restores the comparison")
    elif band is None:
        fails.append("no baseline arm has closed a trade yet, so there is "
                     "nothing to compare against")
    elif leader.is_control:
        # The leader IS the baseline. "Has not beaten the baseline" is a
        # sentence about nothing when the two are the same arm, so the term it
        # must clear instead is the arm that selects nothing at all.
        if naked is None:
            fails.append("the no-selection arm has not traded, so there is "
                         "nothing to compare a baseline against")
        elif leader.wallet_funded_usd <= naked.wallet_funded_usd:
            fails.append(f"is the baseline and has not beaten {naked.name}, "
                         f"which applies no filter at all "
                         f"(${naked.wallet_funded_usd} against "
                         f"${leader.wallet_funded_usd})")
        else:
            board.leader_beats_controls = True
    elif not board.leader_beats_controls:
        fails.append(f"has not beaten the baseline ({best_control}, "
                     f"${band} wallet against ${leader.wallet_funded_usd})")
    board.called = not fails
    board.verdict = ("CALLED: " + leader.name + " cleared every term."
                     + (" It is the BASELINE — the edge is the floor itself, "
                        "not a filter layered on it." if leader.is_control else "")
                     if board.called else
                     f"{leader.name} leads but is not called — " + "; ".join(fails))
    return board
