"""The read interface. Everything downstream reads comes through here.

Every function takes the session, as every read in this repo does; the caller
owns the transaction boundary. `health()` returns plain JSON so the route and
the CLI print it unchanged.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.labs.nse_breakout import config
from app.labs.nse_breakout.models import (
    BtCandle,
    BtIndexClose,
    BtIngestDay,
    BtRun,
    BtUniverseMember,
)


async def get_universe(session: AsyncSession, active_only: bool = True,
                       ) -> list[BtUniverseMember]:
    """Members, most liquid first — the order every downstream pass wants."""
    stmt = select(BtUniverseMember).order_by(
        BtUniverseMember.turnover_20d.desc().nullslast(), BtUniverseMember.symbol)
    if active_only:
        stmt = stmt.where(BtUniverseMember.active.is_(True))
    return list((await session.execute(stmt)).scalars())


async def get_candles(session: AsyncSession, symbol: str, limit: int | None = None,
                      ) -> list[BtCandle]:
    """The newest `limit` daily bars, OLDEST FIRST — the order every indicator
    wants, and the order a chart draws in."""
    stmt = (select(BtCandle).where(BtCandle.symbol == symbol)
            .order_by(BtCandle.date.desc()))
    if limit:
        stmt = stmt.limit(limit)
    return list(reversed(list((await session.execute(stmt)).scalars())))


async def get_index_closes(session: AsyncSession,
                           index_name: str = config.NIFTY_NAME) -> list[BtIndexClose]:
    return list((await session.execute(
        select(BtIndexClose).where(BtIndexClose.index_name == index_name)
        .order_by(BtIndexClose.date))).scalars())


async def health(session: AsyncSession, *, now: datetime | None = None,
                 ) -> dict[str, Any]:
    """Universe size, candle coverage, last bhavcopy, backfill progress,
    failures.

    With the flag off this answers `{"running": False}` without touching the
    database: "the tracker is not running" and "it ran and found nothing" are
    different facts and must not render identically.
    """
    if not config.enabled():
        return {"running": False}
    now = now or datetime.now(UTC)

    active, inactive = (await session.execute(
        select(
            func.count().filter(BtUniverseMember.active.is_(True)),
            func.count().filter(BtUniverseMember.active.is_(False)),
        ))).one()

    # Coverage is about SCORABLE names: a symbol in the universe with 40 bars
    # cannot have a level computed, and counting it as covered would hide
    # exactly the gap this route exists to show.
    covered, total_syms = (await session.execute(
        select(
            func.count().filter(BtUniverseMember.bars >= config.MIN_BARS_FOR_LEVELS),
            func.count(),
        ).where(BtUniverseMember.active.is_(True)))).one()

    bars_total, first_bar, last_bar = (await session.execute(
        select(func.count(), func.min(BtCandle.date), func.max(BtCandle.date)))).one()

    day_rows = dict((await session.execute(
        select(BtIngestDay.status, func.count()).group_by(BtIngestDay.status))).all())
    failed_days = [
        {"date": d.isoformat(), "failures": f, "error": (e or "")[:200]}
        for d, f, e in (await session.execute(
            select(BtIngestDay.date, BtIngestDay.failures, BtIngestDay.last_error)
            .where(BtIngestDay.status == "failed")
            .order_by(BtIngestDay.date.desc()).limit(20))).all()]

    suspect = await session.scalar(
        select(func.count()).select_from(BtCandle)
        .where(BtCandle.suspect_gap.is_(True))) or 0

    nifty_first, nifty_last, nifty_n = (await session.execute(
        select(func.min(BtIndexClose.date), func.max(BtIndexClose.date), func.count())
        .where(BtIndexClose.index_name == config.NIFTY_NAME))).one()

    runs = {
        r.phase: {
            "started_at": r.started_at.isoformat(),
            "age_seconds": round((now - r.started_at).total_seconds(), 1),
            "days": r.days, "rows": r.rows, "symbols": r.symbols,
            "detail": r.detail or {}, "errors": r.errors or [],
        }
        for r in (await session.execute(
            select(BtRun).distinct(BtRun.phase)
            .order_by(BtRun.phase, BtRun.started_at.desc()))).scalars()
    }

    ok_days = day_rows.get("ok", 0)
    return {
        "running": True,
        "universe": {"active": active, "inactive": inactive,
                     "min_price_inr": config.MIN_PRICE_INR,
                     "min_turnover_inr": config.MIN_TURNOVER_INR},
        "coverage": {
            "bars_required": config.MIN_BARS_FOR_LEVELS,
            "symbols_covered": covered,
            "symbols_active": total_syms,
            "pct": round(covered / total_syms * 100, 2) if total_syms else 0.0,
            "bars_total": bars_total,
            "first_bar": first_bar.isoformat() if first_bar else None,
            "last_bar": last_bar.isoformat() if last_bar else None,
        },
        "bhavcopy": {
            "last_date": last_bar.isoformat() if last_bar else None,
            "days_ok": ok_days,
            "days_missing": day_rows.get("missing", 0),
            "days_failed": day_rows.get("failed", 0),
            # A day the archive never published is not a gap in our data.
            "target_days": config.BACKFILL_DAYS,
            "failed_days": failed_days,
        },
        "corporate_actions": {
            "suspect_gap_bars": suspect,
            "gap_pct": config.SPLIT_GAP_PCT,
            "adjusted": False,
            "note": ("bhavcopy is unadjusted and no corroboration source is "
                     "reachable; gaps are flagged, never corrected"),
        },
        "nifty": {"bars": nifty_n,
                  "first": nifty_first.isoformat() if nifty_first else None,
                  "last": nifty_last.isoformat() if nifty_last else None},
        "last_run": runs,
    }
