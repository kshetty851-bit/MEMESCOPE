"""`/labs/graduation` — read-only. No POST/PUT/PATCH/DELETE.

With the flag off every route answers `running: false` without touching the
database: "the lab is not running" and "the lab ran and found nothing" are
different facts and must not render identically.

The page this feeds is a **status board, not a strategy**. It reports what the
recorder has seen; it ranks nothing and recommends nothing.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.labs.graduation import config
from app.labs.graduation.models import (
    GradCheckpoint,
    GradCurveSample,
    GradMigration,
    GradPaperPosition,
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
    if base.last_chain_read_at is not None:
        age = (datetime.now(UTC) - base.last_chain_read_at).total_seconds()
        base.seconds_since_chain_read = int(age)
        base.recorder_stalled = (base.watch_set > 0
                                 and age > base.stall_threshold_s)
    else:
        # Nothing has ever been read. Only a stall if there is something to read.
        base.recorder_stalled = base.watch_set > 0

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
                 limit: int | None = 10) -> PaperBookOut:
    """One book's state. Read-only: this endpoint never ticks it."""
    account = await PaperBook(db, book=book).account()
    open_rows, closed_rows = await positions(db, book=book, limit=limit)
    # The headline cost is a real position's, not a nominal one: the priority
    # fee is flat in SOL, so its share depends entirely on the size traded.
    # With no positions yet there is no rate to convert $100 with, and the
    # configured nominal is the only honest stand-in.
    sample = next((r[0] for r in (*open_rows, *closed_rows)), None)
    book_costs = costs(sample.notional_quote if sample else None)
    cents = Decimal("0.01")

    def out(row: Any) -> PaperPosition:
        """Closed rows carry their realised figures; open ones are marked to
        the last price, at the SOL/USD rate captured when they opened.

        Both the dollars and the percentage come from the same ratio, so they
        cannot disagree with each other.
        """
        p, symbol, name, voided = row
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
            impact_open=p.impact_open, impact_close=p.impact_close)

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
        closed_trades=[out(r) for r in closed_rows],
    )


@router.get("/paper/trades", response_model=PaperBookOut)
async def paper_trades(book: str = "E05_hold_5m",
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
    return await _paper(db, book=book, limit=None)


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
    #: Not the tournament's equity divided by ten. A $100 account cannot run
    #: ten $100 positions — it runs ONE, fully invested, so it COMPOUNDS:
    #: 100 x product(1 + return). That is a different arithmetic from the
    #: book's additive $100-a-slot sizing, and it is the one that applies to
    #: an account you would actually fund.
    #:
    #: The consequence is the point. A single -99% trade takes the product to
    #: zero and the wallet never comes back, whatever the arm does afterwards.
    wallet_100_usd: Decimal = Decimal(0)
    #: The worst single trade the arm has taken. The number that decides the
    #: figure above, because compounding has no memory of the good ones.
    worst_trade_pct: Decimal | None = None
    #: Where thirty days of the SAME rule at the SAME trade rate would land —
    #: median, and the 5th-95th percentile band around it.
    #:
    #: The band is the point. A projection from a few dozen trades is mostly
    #: an artefact of which tokens happened to arrive, and a single number
    #: would hide that behind a decimal point. Positions are a fixed $100
    #: regardless of equity, so the arithmetic is additive rather than
    #: compounding — compounding a noisy edge produces numbers that are
    #: arithmetic rather than forecast.
    projected_30d_usd: Decimal | None = None
    projected_30d_low: Decimal | None = None
    projected_30d_high: Decimal | None = None
    projected_trades: int = 0
    #: Share of simulated thirty-day paths in which the account could no
    #: longer fund a position. The one figure a running total cannot express.
    ruin_pct: Decimal | None = None


class Leaderboard(BaseModel):
    """Fifty arms, eight of which cannot have an edge.

    `control_band` is the best realised P&L among those eight. A leader that
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
    #: The starting balance the `wallet_100_usd` column simulates.
    wallet_demo_usd: Decimal = Decimal(0)
    #: How long the tournament has been running. The projection is meaningless
    #: below an hour and barely better above it, so the reader is told.
    hours_running: Decimal = Decimal(0)


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
               func.avg(GradPaperPosition.net_return).label("mean"))
        .where(GradPaperPosition.closed_at.is_not(None),
               GradPaperPosition.notional_usd > 0,
               GradPaperPosition.close_quote > 0)
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
    per_arm: dict[str, list[float]] = {}
    for book, ret in (await db.execute(
            select(GradPaperPosition.book, GradPaperPosition.net_return)
            .where(GradPaperPosition.closed_at.is_not(None),
                   GradPaperPosition.closed_at >= datetime.now(UTC) - timedelta(days=7),
                   GradPaperPosition.notional_usd > 0,
                   GradPaperPosition.close_quote > 0,
                   GradPaperPosition.net_return.is_not(None))
            .order_by(GradPaperPosition.closed_at))).all():
        per_arm.setdefault(book, []).append(float(ret))

    def wallet_100(returns: list[float]) -> tuple[Decimal, Decimal | None]:
        """A real $100 account taking these trades, one at a time.

        Fully invested and therefore compounding, which is what a $100 wallet
        running $100 positions necessarily is.

        It stops at `WALLET_MIN_USD`, and that floor is load-bearing rather
        than tidy: an account taking a -99% trade holds about $2.65, and
        without a floor the product lets that $2.65 "recover" to nine figures
        on later winners it could never have placed. Below $25 a round trip
        costs more than the strategy makes.
        """
        if not returns:
            return config.WALLET_DEMO_USD, None
        equity = float(config.WALLET_DEMO_USD)
        for r in returns:
            equity *= (1 + r)
            if equity < float(config.WALLET_MIN_USD):
                equity = 0.0
                break
        return (Decimal(str(equity)).quantize(Decimal("0.01")),
                Decimal(str(min(returns) * 100)).quantize(Decimal("0.1")))
    open_now: dict[str, int] = {}
    unrealised: dict[str, Decimal] = {}
    for position in (await db.scalars(
            select(GradPaperPosition)
            .where(GradPaperPosition.closed_at.is_(None),
                   GradPaperPosition.notional_usd > 0))).all():
        open_now[position.book] = open_now.get(position.book, 0) + 1
        # Marked to the last recorded price, at the rate captured when the
        # position opened — the same arithmetic the closed rows use, so equity
        # does not change shape the moment a position closes.
        live = net_return(position, position.last_quote)
        if live is not None:
            unrealised[position.book] = (unrealised.get(position.book, Decimal(0))
                                         + position.notional_usd * live)
    started = await db.scalar(select(func.min(GradPaperPosition.opened_at)))
    hours = ((datetime.now(UTC) - started).total_seconds() / 3600
             if started else 0.0)

    global _PROJECTIONS
    fresh = (_PROJECTIONS is not None
             and datetime.now(UTC) - _PROJECTIONS[0] < _PROJECTION_TTL)
    cached: dict[str, dict[str, Any]] = _PROJECTIONS[1] if fresh and _PROJECTIONS else {}

    def project(returns: list[float]) -> dict[str, Any]:
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
        rate = n / hours
        horizon = int(rate * 24 * 30)
        cap = float(config.PAPER_CAPITAL_USD)
        size = float(config.PAPER_NOTIONAL_USD)
        block = max(1, config.PAPER_MAX_SLOTS)
        steps = max(1, horizon // block)
        pool = [sum(returns[random.randrange(n)] for _ in range(block))  # noqa: S311
                for _ in range(1024)]
        finals: list[float] = []
        ruined = 0
        for _ in range(160):
            equity = cap
            for _ in range(steps):
                equity += size * pool[random.randrange(len(pool))]  # noqa: S311
                if equity < size:
                    equity = max(0.0, equity)
                    ruined += 1
                    break
            finals.append(equity - cap)
        finals.sort()

        def at(p: float) -> Decimal:
            return Decimal(str(finals[int(p * (len(finals) - 1))])).quantize(
                Decimal("0.01"))

        return {
            "projected_30d_usd": at(0.50),
            "projected_30d_low": at(0.05),
            "projected_30d_high": at(0.95),
            "projected_trades": horizon,
            "ruin_pct": (Decimal(ruined) / Decimal(len(finals)) * 100
                         ).quantize(Decimal("0.1")),
        }

    def row(arm) -> ArmRow:
        s = stats.get(arm.name)
        pf = top = mean = None
        if s is not None and s.trades:
            if s.gross_down > 0:
                pf = (Decimal(s.gross_up) / Decimal(s.gross_down)).quantize(Decimal("0.01"))
            if s.gross_up > 0 and s.best is not None and s.best > 0:
                top = (Decimal(s.best) / Decimal(s.gross_up)).quantize(Decimal("0.0001"))
            if s.mean is not None:
                mean = (Decimal(s.mean) * 100).quantize(Decimal("0.01"))
        forecast = (cached.get(arm.name, {}) if fresh
                    else project(per_arm.get(arm.name, [])))
        open_pnl = unrealised.get(arm.name, Decimal(0)).quantize(Decimal("0.01"))
        wallet, worst = wallet_100(per_arm.get(arm.name, []))
        realised = (Decimal(s.pnl) if s else Decimal(0)).quantize(Decimal("0.01"))
        return ArmRow(
            name=arm.name, note=arm.note, entry=arm.entry,
            entry_rule=arm.entry_rule, exit_rule=arm.exit_rule,
            hold_minutes=arm.hold,
            take_profit_x=arm.tp, trailing_pct=arm.trail, is_control=arm.is_control,
            trades=int(s.trades) if s else 0, wins=int(s.wins) if s else 0,
            realised_usd=realised,
            mean_pct=mean, profit_factor=pf, top_token_share=top,
            open_positions=int(open_now.get(arm.name, 0)),
            return_pct=((realised / config.PAPER_CAPITAL_USD * 100)
                        .quantize(Decimal("0.01"))
                        if config.PAPER_CAPITAL_USD else Decimal(0)),
            wallet_100_usd=wallet, worst_trade_pct=worst,
            unrealised_usd=open_pnl,
            equity_usd=(config.PAPER_CAPITAL_USD + realised + open_pnl
                        ).quantize(Decimal("0.01")),
            **forecast)

    rows = [row(a) for a in ARMS]
    if not fresh:
        _PROJECTIONS = (datetime.now(UTC), {
            r.name: {"projected_30d_usd": r.projected_30d_usd,
                     "projected_30d_low": r.projected_30d_low,
                     "projected_30d_high": r.projected_30d_high,
                     "projected_trades": r.projected_trades,
                     "ruin_pct": r.ruin_pct}
            for r in rows if r.projected_30d_usd is not None})
    # An arm that has not traded is not leading. Sorting on P&L alone ranks a
    # never-traded $0.00 above an arm that took one trade and lost $1.30, and
    # the top of the board fills with arms whose filter has simply not matched
    # anything yet.
    rows.sort(key=lambda r: (r.trades > 0, r.realised_usd), reverse=True)
    traded = [r for r in rows if r.trades]
    control_rows = [r for r in rows if r.is_control]
    band = max((r.realised_usd for r in control_rows if r.trades), default=None)
    best_control = next((r.name for r in control_rows
                         if band is not None and r.trades
                         and r.realised_usd == band), "")
    leader = next((r for r in traded if not r.is_control), None)

    board = Leaderboard(
        running=config.paper_enabled(), started_at=started, arms=rows,
        controls=control_rows, control_band=band, best_control=best_control,
        leader=leader.name if leader else "",
        leader_beats_controls=bool(leader and leader.trades and band is not None
                                   and leader.realised_usd > band),
        min_trades=config.TOURNEY_MIN_TRADES,
        required_profit_factor=config.required_pf(
            leader.trades if leader else 0),
        max_token_share=config.TOURNEY_MAX_TOKEN_SHARE,
        total_trades=sum(r.trades for r in rows),
        notional_usd=config.PAPER_NOTIONAL_USD,
        capital_usd=config.PAPER_CAPITAL_USD,
        wallet_demo_usd=config.WALLET_DEMO_USD,
        hours_running=Decimal(str(round(hours, 1))),
    )
    if leader is None:
        board.verdict = (
            f"{len(traded)} arms have closed trades; none of them is a "
            "strategy arm yet." if traded else "No arm has closed a trade yet.")
        return board
    fails = []
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
    if band is None:
        fails.append("no random arm has closed a trade yet, so there is "
                     "nothing to compare against")
    elif not board.leader_beats_controls:
        fails.append(f"has not beaten the best random arm ({best_control}, "
                     f"${band})")
    board.called = not fails
    board.verdict = ("CALLED: " + leader.name + " cleared every term."
                     if board.called else
                     f"{leader.name} leads but is not called — " + "; ".join(fails))
    return board
