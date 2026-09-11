"""The read interface. Everything downstream reads comes through here.

Every function takes the session, as every read in this repo does; the
caller owns the transaction boundary. `data_health()` returns plain JSON
(ISO strings, floats) so the API route and the CLI print it unchanged.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.labs.breakout import config
from app.labs.breakout.candles import Candle, find_gaps, interval, last_closed_open
from app.labs.breakout.models import (
    BoAccount,
    BoCandle,
    BoEpisode,
    BoEquity,
    BoLevels,
    BoPosition,
    BoRun,
    BoSetupSnapshot,
    BoTrade,
    BoUniverseMember,
)


async def get_universe(
    session: AsyncSession, active_only: bool = True,
) -> list[BoUniverseMember]:
    """Watched tokens, most liquid names first — the candle queue's order.

    Returns SESSION-BOUND rows, not detached copies, because the candle sync
    needs to update the ones it touches. Read their attributes inside the
    session that produced them.
    """
    stmt = select(BoUniverseMember).order_by(
        BoUniverseMember.volume_24h_usd.desc().nullslast(), BoUniverseMember.mint)
    if active_only:
        stmt = stmt.where(BoUniverseMember.active.is_(True))
    return list((await session.execute(stmt)).scalars())


async def get_candles(
    session: AsyncSession, mint: str, timeframe: str, limit: int | None = None,
) -> list[Candle]:
    """The newest `limit` closed bars (default: the timeframe's window),
    OLDEST FIRST — the order every indicator wants."""
    limit = config.candle_window(timeframe) if limit is None else limit
    rows = (await session.execute(
        select(BoCandle)
        .where(BoCandle.mint == mint, BoCandle.timeframe == timeframe)
        .order_by(BoCandle.open_time.desc())
        .limit(limit)
    )).scalars()
    return [Candle(r.mint, r.pool_address, r.timeframe, r.open_time, r.open, r.high,
                   r.low, r.close, r.volume_usd, r.close_time)
            for r in reversed(list(rows))]


async def data_health(session: AsyncSession, *, now: datetime | None = None,
                      ) -> dict[str, Any]:
    """Flag state, universe size, per-token candle coverage, and the last run
    of each phase.

    With the flag off this answers `{"running": False}` without touching the
    database: "the lab is not running" and "the lab ran and found nothing" are
    different facts and must not render identically.
    """
    if not config.enabled():
        return {"running": False}
    now = now or datetime.now(UTC)

    members = await get_universe(session, active_only=False)
    active = [m for m in members if m.active]
    mints = [m.mint for m in active]

    times: dict[tuple[str, str], list[datetime]] = defaultdict(list)
    if mints:
        for mint, timeframe, open_time in (await session.execute(
            select(BoCandle.mint, BoCandle.timeframe, BoCandle.open_time)
            .where(BoCandle.mint.in_(mints))
        )).all():
            times[(mint, timeframe)].append(open_time)

    tokens: dict[str, dict[str, Any]] = {}
    coverage: dict[str, dict[str, int]] = {
        tf: {"tokens": 0, "complete": 0, "stale": 0, "bars": 0, "starved": 0}
        for tf in config.TIMEFRAMES
    }
    starved_tokens: dict[str, list[str]] = {tf: [] for tf in config.TIMEFRAMES}
    for member in active:
        per_timeframe: dict[str, Any] = {}
        for timeframe in config.TIMEFRAMES:
            step = interval(timeframe)
            stored = times.get((member.mint, timeframe), [])
            gaps = find_gaps(stored, step)
            last = max(stored, default=None)
            want = config.candle_window(timeframe)
            # A token is behind when the last closed bar is not stored. One
            # bar of slack for `hour`, because a tick lands somewhere inside
            # the interval, never exactly on its close.
            stale = last is None or last < last_closed_open(timeframe, now) - step
            # STARVED: the last closed bar is not stored, so this token is due
            # a fetch right now and has not had one. A sweep the deadline cut
            # short leaves exactly these behind, and the next tick picks them
            # up — a non-zero count is the carry-over working, not an outage.
            # `stale` is looser by one bar, so starved is the leading signal.
            due = last is None or last < last_closed_open(timeframe, now)
            per_timeframe[timeframe] = {
                "count": len(stored),
                "window": want,
                "complete": len(stored) >= want,
                "last_open_time": None if last is None else last.isoformat(),
                "age_seconds": None if last is None else (now - last).total_seconds(),
                "stale": stale,
                "starved": due,
                "gaps": len(gaps),
                "missing_bars": sum(int((b - a) / step) + 1 for a, b in gaps),
                "gap_ranges": [(a.isoformat(), b.isoformat()) for a, b in gaps[:5]],
            }
            bucket = coverage[timeframe]
            bucket["tokens"] += 1
            bucket["bars"] += len(stored)
            bucket["complete"] += int(len(stored) >= want)
            bucket["stale"] += int(stale)
            bucket["starved"] += int(due)
            if due:
                starved_tokens[timeframe].append(member.mint)
        tokens[member.mint] = {
            "symbol": member.symbol, "pool_address": member.pool_address,
            "dex": member.dex, "fetch_failures": member.fetch_failures,
            "last_error": member.last_error, "candles": per_timeframe,
        }

    last_seen = await session.scalar(
        select(func.max(BoUniverseMember.last_seen))
        .where(BoUniverseMember.active.is_(True)))
    runs = {
        run.phase: {
            "started_at": run.started_at.isoformat(),
            "finished_at": run.finished_at.isoformat(),
            "age_seconds": (now - run.started_at).total_seconds(),
            "universe_size": run.universe_size, "added": run.added,
            "dropped": run.dropped, "candles_upserted": run.candles_upserted,
            "tokens_refreshed": run.tokens_refreshed,
            "tokens_carried": run.tokens_carried,
            "requests": run.requests or {}, "errors": run.errors or [],
        }
        for run in (await session.execute(
            select(BoRun).distinct(BoRun.phase)
            .order_by(BoRun.phase, BoRun.started_at.desc())
        )).scalars()
    }

    return {
        "running": True,
        "universe": {
            "active": len(active),
            "inactive": len(members) - len(active),
            "max": config.MAX_UNIVERSE,
            "refreshed_at": None if last_seen is None else last_seen.isoformat(),
            "stale": last_seen is None
            or (now - last_seen).total_seconds() >= config.UNIVERSE_REFRESH_SECONDS,
        },
        "coverage": coverage,
        #: Tokens still owed a fetch, per timeframe, most liquid first — the
        #: queue the next tick will start on. Capped so the payload stays
        #: readable; `coverage[tf]["starved"]` carries the full count.
        "starved_tokens": {tf: mints[:20] for tf, mints in starved_tokens.items()},
        "budget": {
            "geckoterminal_per_minute": config.GECKOTERMINAL_CALLS_PER_MINUTE,
            "dexscreener_per_minute": config.DEXSCREENER_CALLS_PER_MINUTE,
            "max_calls_per_tick": config.MAX_CALLS_PER_TICK,
            "last_tick_requests": {
                phase: run["requests"] for phase, run in runs.items()
            },
        },
        "tokens": tokens,
        "last_run": runs,
    }


# ============================================================================
# Phase 2 — setups, episodes, levels
# ============================================================================

async def get_levels(session: AsyncSession, mint: str) -> BoLevels | None:
    """The latest daily read for one token, or None if it was never computed
    (too few daily bars, or never in the universe)."""
    return (await session.execute(
        select(BoLevels).where(BoLevels.mint == mint)
    )).scalar_one_or_none()


async def latest_snapshots(
    session: AsyncSession, mints: Sequence[str] | None = None,
) -> dict[str, BoSetupSnapshot]:
    """The newest snapshot per mint. `DISTINCT ON`, so one query rather than
    one per token."""
    stmt = (select(BoSetupSnapshot)
            .distinct(BoSetupSnapshot.mint)
            .order_by(BoSetupSnapshot.mint, BoSetupSnapshot.bar_close_time.desc()))
    if mints is not None:
        if not mints:
            return {}
        stmt = stmt.where(BoSetupSnapshot.mint.in_(list(mints)))
    return {s.mint: s for s in (await session.execute(stmt)).scalars()}


async def get_setups(
    session: AsyncSession, state: str | None = None,
) -> list[dict[str, Any]]:
    """Open episodes with their latest snapshot and universe row, PRE_BREAKOUT
    first and then by score, descending.

    An open episode whose latest snapshot is NONE-state (a lull) still
    appears, carrying its last known state — dropping it would make a watchlist
    that flickers.
    """
    episodes = (await session.execute(
        select(BoEpisode).where(BoEpisode.closed_at.is_(None))
    )).scalars().all()
    if not episodes:
        return []

    mints = [e.mint for e in episodes]
    members = {m.mint: m for m in (await session.execute(
        select(BoUniverseMember).where(BoUniverseMember.mint.in_(mints))
    )).scalars()}
    snapshots = await latest_snapshots(session, mints)
    now = datetime.now(UTC)

    rows: list[dict[str, Any]] = []
    for episode in episodes:
        member = members.get(episode.mint)
        snapshot = snapshots.get(episode.mint)
        row_state = snapshot.state if snapshot else "NONE"
        if state is not None and row_state != state:
            continue
        rows.append({
            "mint": episode.mint,
            "symbol": member.symbol if member else None,
            "name": member.name if member else None,
            "pool": member.pool_address if member else None,
            "state": row_state,
            "score": snapshot.score if snapshot else 0,
            "components": (snapshot.components if snapshot else {}),
            "price": _f(snapshot.price) if snapshot else None,
            "resistance": _f(snapshot.resistance) if snapshot else None,
            "distance_pct": _f(snapshot.distance_pct) if snapshot else None,
            "opened_at": episode.opened_at,
            "first_pre_breakout_at": episode.first_pre_breakout_at,
            "hours_open": round((now - episode.opened_at).total_seconds() / 3600, 2),
            "liquidity_usd": _f(member.liquidity_usd) if member else None,
            "volume_24h_usd": _f(member.volume_24h_usd) if member else None,
        })
    # PRE_BREAKOUT first, then by score. `STATE_ORDER` keeps the ordering in
    # one place so the route and the frontend cannot disagree about it.
    rows.sort(key=lambda r: (STATE_ORDER.get(r["state"], 99), -r["score"]))
    return rows


#: Watchlist ordering. Lower sorts first.
STATE_ORDER = {"PRE_BREAKOUT": 0, "WATCHING": 1, "BROKE_OUT": 2, "FAILED": 3, "NONE": 4}


async def get_episodes(
    session: AsyncSession, closed: bool | None = True, limit: int = 50, offset: int = 0,
) -> tuple[int, list[BoEpisode]]:
    """`(total, page)` of episodes, newest first."""
    stmt = select(BoEpisode)
    count_stmt = select(func.count()).select_from(BoEpisode)
    if closed is True:
        stmt, count_stmt = (s.where(BoEpisode.closed_at.is_not(None))
                            for s in (stmt, count_stmt))
    elif closed is False:
        stmt, count_stmt = (s.where(BoEpisode.closed_at.is_(None))
                            for s in (stmt, count_stmt))
    total = await session.scalar(count_stmt) or 0
    rows = (await session.execute(
        stmt.order_by(BoEpisode.opened_at.desc()).limit(limit).offset(offset)
    )).scalars().all()
    return total, list(rows)


async def get_setup_stats(session: AsyncSession) -> dict[str, Any]:
    """Open episodes by state, closed episodes by reason, and — the only part
    that matters — what the completed outcomes look like BY SCORE DECILE.

    If the score predicts anything, the top deciles beat the bottom ones. Every
    lab in this repo so far has answered no; this is the view that will say so
    quickly rather than after a quarter of paper trading.
    """
    open_rows = await get_setups(session)
    open_by_state: dict[str, int] = {}
    for row in open_rows:
        open_by_state[row["state"]] = open_by_state.get(row["state"], 0) + 1

    closed_counts = dict((await session.execute(
        select(BoEpisode.close_reason, func.count())
        .where(BoEpisode.closed_at.is_not(None))
        .group_by(BoEpisode.close_reason)
    )).all())

    # Score at the episode's first PRE_BREAKOUT is the score the decision was
    # taken on — not the latest one, which would be hindsight.
    scored = (await session.execute(
        select(BoEpisode.trail25_result_pct, BoSetupSnapshot.score)
        .join(BoSetupSnapshot,
              (BoSetupSnapshot.mint == BoEpisode.mint)
              & (BoSetupSnapshot.bar_close_time >= BoEpisode.first_pre_breakout_at))
        .where(BoEpisode.outcome_at.is_not(None),
               BoEpisode.trail25_result_pct.is_not(None))
        .distinct(BoEpisode.id)
        .order_by(BoEpisode.id, BoSetupSnapshot.bar_close_time)
    )).all()
    results = [(float(r), int(s)) for r, s in scored]

    return {
        "open_by_state": open_by_state,
        "closed": {
            "n": sum(closed_counts.values()),
            "broke_out": closed_counts.get("BROKE_OUT", 0),
            "failed": closed_counts.get("FAILED", 0),
            "expired": (closed_counts.get("EXPIRED", 0)
                        + closed_counts.get("universe_exit", 0)),
        },
        "outcomes": _outcome_stats(results),
    }


def _outcome_stats(results: Sequence[tuple[float, int]]) -> dict[str, Any]:
    """Mean/median/win-rate overall and per score decile.

    Deciles are of the SCORE (0-100 in tens), not of the sample — a fixed
    binning, so two runs a week apart are comparable and an empty decile shows
    as empty rather than silently widening its neighbours.
    """
    if not results:
        return {"n": 0, "mean_trail25_pct": None, "median_trail25_pct": None,
                "win_rate": None, "by_score_decile": []}
    values = sorted(r for r, _ in results)
    buckets: dict[int, list[float]] = {}
    for result, score in results:
        buckets.setdefault(min(score // 10, 9), []).append(result)
    return {
        "n": len(values),
        "mean_trail25_pct": round(sum(values) / len(values), 4),
        "median_trail25_pct": round(_median(values), 4),
        "win_rate": round(sum(1 for v in values if v > 0) / len(values), 4),
        "by_score_decile": [
            {
                "decile": decile,
                "n": len(group),
                "mean_trail25_pct": round(sum(group) / len(group), 4),
                "win_rate": round(sum(1 for v in group if v > 0) / len(group), 4),
            }
            for decile, group in sorted(buckets.items())
        ],
    }


def _median(values: Sequence[float]) -> float:
    ordered = sorted(values)
    mid = len(ordered) // 2
    return (ordered[mid] if len(ordered) % 2
            else (ordered[mid - 1] + ordered[mid]) / 2)


def _f(value: Any) -> float | None:
    return None if value is None else float(value)


# ============================================================================
# Phase 3 — the paper ledger
# ============================================================================

async def get_account(session: AsyncSession) -> BoAccount | None:
    """The one account row, or None before the first trading tick."""
    return (await session.execute(
        select(BoAccount).where(BoAccount.scope == "default"))).scalar_one_or_none()


async def get_positions(session: AsyncSession) -> list[BoPosition]:
    return list((await session.execute(
        select(BoPosition).order_by(BoPosition.opened_at))).scalars())


async def get_trades(
    session: AsyncSession, limit: int = 50, offset: int = 0,
) -> tuple[int, list[BoTrade]]:
    """`(total, page)` of closed trades, newest first."""
    total = await session.scalar(select(func.count()).select_from(BoTrade)) or 0
    rows = (await session.execute(
        select(BoTrade).order_by(BoTrade.closed_at.desc()).limit(limit).offset(offset)
    )).scalars().all()
    return total, list(rows)


async def get_equity_curve(session: AsyncSession, hours: int = 168) -> list[BoEquity]:
    """The curve, oldest first — the order a chart draws in."""
    cutoff = datetime.now(UTC) - timedelta(hours=hours)
    return list((await session.execute(
        select(BoEquity).where(BoEquity.bar_close_time >= cutoff)
        .order_by(BoEquity.bar_close_time))).scalars())


async def get_trade_stats(session: AsyncSession) -> dict[str, Any]:
    """Win rate, expectancy, profit factor, drawdown and the split by exit
    reason.

    Every figure is net of fees and slippage, because `pnl_usd` is. Drawdown
    is read off the stored equity curve rather than off the trade sequence —
    the curve includes open positions, and a drawdown that only counts closed
    trades is not a drawdown anyone lived through.
    """
    trades = list((await session.execute(select(BoTrade))).scalars())
    account = await get_account(session)
    curve = list((await session.execute(
        select(BoEquity).order_by(BoEquity.bar_close_time))).scalars())

    if not trades:
        return {"trades": 0, "win_rate": None, "avg_win_pct": None,
                "avg_loss_pct": None, "expectancy_pct": None, "profit_factor": None,
                "max_drawdown_pct": _curve_drawdown(curve),
                "return_pct": _return_pct(account), "by_exit_reason": {},
                "fees_total": 0.0}

    pcts = [float(t.pnl_pct) for t in trades]
    wins = [p for p in pcts if p > 0]
    losses = [p for p in pcts if p <= 0]
    gross_win = sum(float(t.pnl_usd) for t in trades if t.pnl_usd > 0)
    gross_loss = -sum(float(t.pnl_usd) for t in trades if t.pnl_usd <= 0)

    by_reason: dict[str, dict[str, Any]] = {}
    for trade in trades:
        bucket = by_reason.setdefault(
            trade.exit_reason, {"n": 0, "pnl_usd": 0.0, "mean_pct": 0.0})
        bucket["n"] += 1
        bucket["pnl_usd"] += float(trade.pnl_usd)
        bucket["mean_pct"] += float(trade.pnl_pct)
    for bucket in by_reason.values():
        bucket["mean_pct"] = round(bucket["mean_pct"] / bucket["n"], 4)
        bucket["pnl_usd"] = round(bucket["pnl_usd"], 4)

    return {
        "trades": len(trades),
        "win_rate": round(len(wins) / len(trades), 4),
        "avg_win_pct": round(sum(wins) / len(wins), 4) if wins else None,
        "avg_loss_pct": round(sum(losses) / len(losses), 4) if losses else None,
        "expectancy_pct": round(sum(pcts) / len(pcts), 4),
        # None, not infinity, when nothing has lost yet — a profit factor with
        # no denominator is not a very good profit factor, it is no data.
        "profit_factor": round(gross_win / gross_loss, 4) if gross_loss > 0 else None,
        "max_drawdown_pct": _curve_drawdown(curve),
        "return_pct": _return_pct(account),
        "by_exit_reason": by_reason,
        "fees_total": round(sum(float(t.fees_usd) for t in trades), 4),
    }


def _curve_drawdown(curve: Sequence[BoEquity]) -> float:
    """The deepest peak-to-trough on the stored equity curve, in percent."""
    peak = worst = 0.0
    for point in curve:
        equity = float(point.equity)
        peak = max(peak, equity)
        if peak > 0:
            worst = max(worst, (peak - equity) / peak * 100)
    return round(worst, 4)


def _return_pct(account: BoAccount | None) -> float:
    if account is None:
        return 0.0
    return round((float(account.equity) - config.STARTING_EQUITY)
                 / config.STARTING_EQUITY * 100, 4)
