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
