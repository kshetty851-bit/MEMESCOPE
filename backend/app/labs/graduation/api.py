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
from sqlalchemy import func, select
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
from app.labs.graduation.paper import PaperBook, costs, positions

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
    mint: str
    symbol: str | None = None
    opened_at: datetime
    notional_usd: Decimal
    open_fill: Decimal
    last_quote: Decimal | None = None
    peak_quote: Decimal
    closed_at: datetime | None = None
    close_reason: str | None = None
    #: Realised for a closed position; marked-to-market for an open one.
    pnl_usd: Decimal | None = None
    net_return: Decimal | None = None


class PaperBookOut(BaseModel):
    """The forward book. Rules frozen in advance; nothing here is tunable."""

    running: bool = False
    starting_usd: Decimal = Decimal(0)
    equity_usd: Decimal = Decimal(0)
    realised_usd: Decimal = Decimal(0)
    unrealised_usd: Decimal = Decimal(0)
    pnl_usd: Decimal = Decimal(0)
    return_pct: Decimal = Decimal(0)
    open_positions: int = 0
    closed_positions: int = 0
    wins: int = 0
    max_slots: int = 0
    notional_usd: Decimal = Decimal(0)
    trailing_pct: Decimal = Decimal(0)
    max_hold_minutes: int = 0
    positions: list[PaperPosition] = []


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
    paper: PaperBookOut = PaperBookOut()

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

    base.paper = await _paper(db)

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


async def _paper(db: AsyncSession) -> PaperBookOut:
    """The book's state. Read-only: this endpoint never ticks it."""
    book = PaperBook(db)
    account = await book.account()
    book_costs = costs()
    rows = await positions(db, limit=20)

    def mark(p: Any) -> Decimal | None:
        """Closed positions carry their realised dollars; open ones are
        marked to the last price, using the rate captured at entry."""
        if p.pnl_usd is not None:
            return p.pnl_usd
        if p.last_quote is None or p.notional_quote <= 0:
            return None
        value = p.tokens * book_costs.sell_price(p.last_quote)
        return (p.notional_usd * (value / p.notional_quote - 1)).quantize(
            Decimal("0.01"))

    return PaperBookOut(
        running=config.paper_enabled(),
        starting_usd=account.starting,
        equity_usd=account.equity,
        realised_usd=account.realised,
        unrealised_usd=account.unrealised,
        pnl_usd=account.pnl,
        return_pct=account.return_pct,
        open_positions=account.open_positions,
        closed_positions=account.closed_positions,
        wins=account.wins,
        max_slots=config.PAPER_MAX_SLOTS,
        notional_usd=config.PAPER_NOTIONAL_USD,
        trailing_pct=config.PAPER_TRAILING_PCT,
        max_hold_minutes=config.PAPER_MAX_HOLD_MINUTES,
        positions=[
            PaperPosition(
                mint=p.mint, symbol=p.symbol, opened_at=p.opened_at,
                notional_usd=p.notional_usd, open_fill=p.open_fill,
                last_quote=p.last_quote, peak_quote=p.peak_quote,
                closed_at=p.closed_at, close_reason=p.close_reason,
                pnl_usd=mark(p), net_return=p.net_return)
            for p in rows
        ],
    )
