"""The read interface. Everything downstream reads comes through here.

Every function takes the session, as every read in this repo does; the caller
owns the transaction boundary. `health()` returns plain JSON so the route and
the CLI print it unchanged.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.labs.nse_breakout import config, states, stats
from app.labs.nse_breakout.models import (
    BtCandle,
    BtEpisode,
    BtIndexClose,
    BtIngestDay,
    BtRun,
    BtState,
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


# --- phase 2 ------------------------------------------------------------------

def _f(value: Any) -> float | None:
    return None if value is None else float(value)


async def get_near(session: AsyncSession, limit: int = 200) -> list[dict[str, Any]]:
    """Stocks currently NEAR or WATCH. **NEAR first, then by score.**

    Sorted in SQL rather than in Python so the ordering the frontend is built
    against cannot drift with a slice.
    """
    rows = (await session.execute(
        select(BtState, BtUniverseMember.name, BtUniverseMember.turnover_20d)
        .join(BtUniverseMember, BtUniverseMember.symbol == BtState.symbol)
        # Active only. A name that leaves the universe — delisted, or revealed
        # to be an ETF — keeps its last state row, and without this filter it
        # would sit on the board for ever.
        .where(BtUniverseMember.active.is_(True),
               BtState.state.in_((states.NEAR, states.WATCH)))
        .order_by(case((BtState.state == states.NEAR, 0), else_=1),
                  BtState.score.desc(), BtState.symbol)
        .limit(limit))).all()
    return [{
        "symbol": s.symbol, "name": name, "state": s.state, "score": s.score,
        "close": _f(s.close), "resistance": _f(s.resistance),
        "distance_pct": _f(s.distance_pct), "tightness": s.tightness,
        "is_52w_high": s.is_52w_high, "days_in_state": s.days_in_state,
        "turnover_20d": _f(turnover), "bar_date": s.bar_date.isoformat(),
        # Sector is deliberately absent: no keyless source exists for NSE
        # sector classification, and the paid ones may not be scraped.
    } for s, name, turnover in rows]


async def get_breakouts(session: AsyncSession, days: int = 30,
                        source: str = "live") -> list[dict[str, Any]]:
    """Episodes whose breakout confirmed in the last `days` calendar days."""
    cutoff = datetime.now(UTC).date() - timedelta(days=days)
    rows = (await session.execute(
        select(BtEpisode, BtState.close, BtState.state)
        .outerjoin(BtState, BtState.symbol == BtEpisode.symbol)
        .where(BtEpisode.source == source, BtEpisode.breakout_date.is_not(None),
               BtEpisode.breakout_date >= cutoff)
        .order_by(BtEpisode.breakout_date.desc()))).all()
    today = datetime.now(UTC).date()
    out = []
    for episode, last_close, live_state in rows:
        entry = _f(episode.breakout_price)
        close = _f(last_close)
        out.append({
            "symbol": episode.symbol,
            "breakout_date": episode.breakout_date.isoformat(),
            "breakout_price": entry, "resistance": _f(episode.resistance),
            "volume_mult": _f(episode.breakout_volume_mult),
            # Measured against the latest stored close, so it moves with the
            # data rather than being frozen at the outcome window.
            "ret_since_pct": (round((close - entry) / entry * 100, 4)
                              if entry and close else None),
            "max_gain_pct": _f(episode.mfe_bo_20),
            "max_drawdown_pct": _f(episode.mae_bo_20),
            "state": episode.state, "live_state": live_state,
            "false_breakout": episode.close_reason == states.FALSE_BREAKOUT,
            "days_since": (today - episode.breakout_date).days,
        })
    return out


async def get_stock(session: AsyncSession, symbol: str,
                    candles: int = 750) -> dict[str, Any] | None:
    """Everything `/stock/{symbol}` draws, from what is STORED.

    The clusters come out of `bt_states` rather than being recomputed here: a
    route that recomputes can disagree with the state that was recorded, and
    then the chart shows a level the machine never saw.
    """
    member = (await session.execute(
        select(BtUniverseMember).where(BtUniverseMember.symbol == symbol))
    ).scalar_one_or_none()
    if member is None:
        return None
    state = (await session.execute(
        select(BtState).where(BtState.symbol == symbol))).scalar_one_or_none()
    episodes = list((await session.execute(
        select(BtEpisode).where(BtEpisode.symbol == symbol)
        .order_by(BtEpisode.opened.desc()).limit(50))).scalars())
    bars = await get_candles(session, symbol, limit=candles)
    live_open = next((e for e in episodes
                      if e.source == "live" and e.closed is None), None)
    return {
        "stock": {"symbol": member.symbol, "name": member.name,
                  "series": member.series, "active": member.active,
                  "bars": member.bars, "turnover_20d": _f(member.turnover_20d),
                  "first_seen": member.first_seen.isoformat(),
                  "last_seen": member.last_seen.isoformat()},
        "levels": ({"clusters": state.clusters or [],
                    "nearest_resistance": _f(state.resistance),
                    "is_52w_high": state.is_52w_high,
                    "week52_high": _f(state.week52_high),
                    "atr": _f(state.atr), "range_pct": _f(state.range_pct),
                    "tightness": state.tightness} if state else None),
        "score": ({"score": state.score, "components": state.components or {},
                   "state": state.state, "days_in_state": state.days_in_state,
                   "distance_pct": _f(state.distance_pct),
                   "bar_date": state.bar_date.isoformat()} if state else None),
        "episode": episode_json(live_open) if live_open else None,
        "history": [episode_json(e) for e in episodes],
        "candles": [{"d": b.date.isoformat(), "o": _f(b.open), "h": _f(b.high),
                     "l": _f(b.low), "c": _f(b.close), "v": b.volume,
                     "suspect": b.suspect_gap} for b in bars],
    }


def episode_json(episode: BtEpisode) -> dict[str, Any]:
    """One episode in the shape Phase 3 is built against."""
    return {
        "id": str(episode.id), "symbol": episode.symbol,
        "source": episode.source, "opened": episode.opened.isoformat(),
        "first_near_date": (episode.first_near_date.isoformat()
                            if episode.first_near_date else None),
        "ref_price": _f(episode.ref_price), "resistance": _f(episode.resistance),
        "score_at_open": episode.score_at_open, "max_score": episode.max_score,
        "breakout_date": (episode.breakout_date.isoformat()
                          if episode.breakout_date else None),
        "breakout_price": _f(episode.breakout_price),
        "volume_mult": _f(episode.breakout_volume_mult),
        "days_to_breakout": episode.days_to_breakout,
        "state": episode.state,
        "closed": episode.closed.isoformat() if episode.closed else None,
        "close_reason": episode.close_reason,
        "ret_ref_5": _f(episode.ret_ref_5), "ret_ref_10": _f(episode.ret_ref_10),
        "ret_ref_20": _f(episode.ret_ref_20), "ret_ref_40": _f(episode.ret_ref_40),
        "ret_bo_5": _f(episode.ret_bo_5), "ret_bo_10": _f(episode.ret_bo_10),
        "ret_bo_20": _f(episode.ret_bo_20), "ret_bo_40": _f(episode.ret_bo_40),
        "mfe_20": _f(episode.mfe_20), "mae_20": _f(episode.mae_20),
        "held_20d_pct": _f(episode.held_20d_pct),
        "trail10_pct": _f(episode.trail10_pct),
        "trail10_stopped": episode.trail10_stopped,
        "rel_nifty_20": _f(episode.rel_nifty_20),
        "outcomes_filled": episode.outcomes_filled_at is not None,
    }


async def get_episodes(session: AsyncSession, source: str = "replay",
                       limit: int = 100, offset: int = 0) -> dict[str, Any]:
    total = await session.scalar(
        select(func.count()).select_from(BtEpisode)
        .where(BtEpisode.source == source)) or 0
    rows = list((await session.execute(
        select(BtEpisode).where(BtEpisode.source == source)
        .order_by(BtEpisode.opened.desc(), BtEpisode.symbol)
        .limit(limit).offset(offset))).scalars())
    return {"total": total, "limit": limit, "offset": offset,
            "items": [episode_json(e) for e in rows]}


async def get_stats(session: AsyncSession, source: str = "replay",
                    ) -> dict[str, Any]:
    """The whole aggregate for one source, plus the thresholds it was produced
    under — so a number can never be read against the wrong rules."""
    rows = list((await session.execute(
        select(BtEpisode).where(BtEpisode.source == source))).scalars())
    payload = stats.summarise(rows)
    payload["source"] = source
    payload["config"] = stats.config_snapshot()
    payload["caveats"] = [
        # Survivorship: the universe is derived from names trading TODAY, so a
        # company delisted in 2025 is absent from a replay that covers 2024.
        # Its setups — disproportionately the ones that went to zero — are not
        # in these numbers.
        "survivorship: delisted names are absent from the universe, so the "
        "replay cannot see setups that ended in delisting",
        "the score's thresholds were fixed before this replay ran and were "
        "not adjusted afterwards",
        "bhavcopy is unadjusted; bars across a corporate action are flagged "
        "suspect_gap, not corrected",
    ]
    return payload
