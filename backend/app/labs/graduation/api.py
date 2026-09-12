"""`/labs/graduation` — read-only. No POST/PUT/PATCH/DELETE.

With the flag off every route answers `running: false` without touching the
database: "the lab is not running" and "the lab ran and found nothing" are
different facts and must not render identically.

The page this feeds is a **status board, not a strategy**. It reports what the
recorder has seen; it ranks nothing and recommends nothing.
"""

from __future__ import annotations

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
    GradPostgradSample,
    GradToken,
)
from app.labs.graduation.paper import PaperBook, costs, net_return, positions

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


class PaperBookOut(BaseModel):
    """The forward book. Rules frozen in advance; nothing here is tunable."""

    running: bool = False
    #: `control` or `filtered`. Same rules; the second adds one entry check.
    book: str = "control"
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
    paper: PaperBookOut = PaperBookOut()
    #: The A/B twin: identical rules behind an entry filter, on the same
    #: graduations. Compared against `paper` after four weeks.
    paper_filtered: PaperBookOut = PaperBookOut(book="filtered")

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
    base.watch_set = await count(
        select(func.count()).select_from(GradToken)
        .where(GradToken.unsubscribed_at.is_(None)))
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

    base.paper = await _paper(db, book="control")
    base.paper_filtered = await _paper(db, book="filtered")

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


async def _paper(db: AsyncSession, *, book: str = "control",
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
            voided=bool(voided))

    return PaperBookOut(
        running=config.paper_enabled(),
        book=book,
        filter_description=_filter_description() if book == "filtered" else "",
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
async def paper_trades(book: str = "control",
                       db: AsyncSession = Depends(get_db)) -> PaperBookOut:
    """Every closed trade, not just the recent ones.

    Its own route rather than a bigger `/status`, because the board polls
    status every thirty seconds and the trade history only grows. Sorting is
    the page's job: the whole list is here, so it can order without asking
    again.
    """
    if not config.enabled():
        return PaperBookOut()
    if book not in config.PAPER_BOOKS:
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
