"""`python -m app.labs.nse_breakout <command>` — the tracker's entry point.

    ingest [--date YYYY-MM-DD]  one day's bhavcopy, then rebuild the universe
    backfill [--days N|--all]   walk the archive backwards; resumable
    detect                      levels, score and state on the newest bar
    near                        the current NEAR/WATCH board as a table
    replay [--all]              the causal walk over the whole history
    outcomes [--all]            fill outcomes whose window has closed
    stats [--source replay]     the aggregate payload as JSON
    universe                    the active universe as a table
    health                      the health route's payload as JSON

Exists so the tracker is runnable without Celery beat, and so "re-run the
backfill" is a documented command rather than a scratch script. `--all` loops
the same bounded slice the beat runs, so killing it costs the day in flight
and nothing else — resumption is derived from `bt_ingest_days`, not stored.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from datetime import UTC, date, datetime

from app.db.session import SessionFactory
from app.labs.nse_breakout import config
from app.labs.nse_breakout.data import get_near, get_stats, get_universe, health
from app.labs.nse_breakout.ingest import Ingest
from app.labs.nse_breakout.scheduler import (
    backfill_tick,
    detect_tick,
    ingest_tick,
    outcomes_tick,
    replay_tick,
)
from app.labs.nse_breakout.sources import NseArchive


async def _health() -> dict:
    async with SessionFactory() as session:
        return await health(session)


async def _one_day(when: date) -> dict:
    if not config.enabled():
        return {"skipped": "nse_breakout_disabled"}
    now = datetime.now(UTC)
    async with NseArchive() as archive, SessionFactory() as session:
        job = Ingest(session, archive)
        out = await job.day(when, now=now)
        out["universe"] = await job.rebuild_universe(now=now)
        await session.commit()
        return out


async def _backfill_all(slice_days: int) -> dict:
    """The beat's slice, on a loop, with progress on stdout.

    Each slice commits, so this is safe to interrupt: the next run picks up
    from whatever `bt_ingest_days` says is still pending.

    **It stops when a pass stops making progress, not when a pass does no
    work.** Those differ, and the difference cost a hot loop in production:
    once only today's unpublished bhavcopy was left, every pass "walked one
    day" — the day count was 1, the pending count stayed 1, and a condition
    written on the day count spun at one NSE request per second. `remaining`
    not falling is the only honest definition of no progress, and it covers
    every case that produces one: a day too early to settle, a day that has
    exhausted its retries, a slice stopped by its own deadline.
    """
    started = time.monotonic()
    days = rows = 0
    previous_remaining: int | None = None
    while True:
        result = await backfill_tick(limit=slice_days)
        if result.get("error") or result.get("skipped"):
            return {"stopped": result, "days": days, "rows": rows}
        days += result["days"]
        rows += result["rows"]
        remaining = result["remaining_days"]
        sys.stdout.write(
            f"[{time.monotonic() - started:7.0f}s] +{result['days']}d "
            f"ok={result['ok']} rows={result['rows']} "
            f"remaining={remaining}\n")
        sys.stdout.flush()
        if not remaining or remaining == previous_remaining:
            return {"days": days, "rows": rows,
                    "seconds": round(time.monotonic() - started, 1),
                    "remaining_days": remaining,
                    "stalled": bool(remaining)}
        previous_remaining = remaining


async def _replay_all() -> dict:
    """The beat's slice, on a loop, with progress on stdout. Safe to kill: the
    marker is `bt_universe.replayed_at`, written per symbol as it goes."""
    started = time.monotonic()
    symbols = episodes = 0
    previous_remaining: int | None = None
    while True:
        result = await replay_tick()
        if result.get("error") or result.get("skipped"):
            return {"stopped": result, "symbols": symbols, "episodes": episodes}
        symbols += result["symbols"]
        episodes += result["episodes"]
        remaining = result["remaining"]
        sys.stdout.write(
            f"[{time.monotonic() - started:7.0f}s] +{result['symbols']} symbols "
            f"episodes={result['episodes']} remaining={remaining}\n")
        sys.stdout.flush()
        # Same rule as the backfill: progress, not work done. A symbol the
        # walk skips still counts as a symbol.
        if not remaining or remaining == previous_remaining:
            return {"symbols": symbols, "episodes": episodes,
                    "seconds": round(time.monotonic() - started, 1),
                    "remaining": remaining, "stalled": bool(remaining)}
        previous_remaining = remaining


async def _outcomes_all() -> dict:
    """The beat's pass, on a loop. Each pass commits, so it is safe to kill."""
    started = time.monotonic()
    filled = waiting = 0
    while True:
        result = await outcomes_tick()
        if result.get("error") or result.get("skipped"):
            return {"stopped": result, "filled": filled}
        filled += result["filled"]
        waiting += result["waiting"]
        sys.stdout.write(
            f"[{time.monotonic() - started:7.0f}s] +{result['filled']} filled "
            f"waiting={result['waiting']} symbols={result['symbols']} "
            f"remaining={result.get('remaining_symbols', 0)}\n")
        sys.stdout.flush()
        if not result["filled"]:
            return {"filled": filled, "still_waiting": result["waiting"],
                    "seconds": round(time.monotonic() - started, 1)}


async def _near() -> str:
    async with SessionFactory() as session:
        rows = await get_near(session)
        if not rows:
            return "nothing NEAR or WATCH — run `python -m app.labs.nse_breakout detect`"
        header = (f"{'symbol':<14}{'state':<7}{'score':>6}{'close':>11}"
                  f"{'resist':>11}{'dist%':>8}{'tight':>7}{'52wh':>6}{'days':>6}")
        lines = [header, "-" * len(header)]
        for r in rows:
            lines.append(
                f"{r['symbol'][:13]:<14}{r['state']:<7}{r['score']:>6}"
                f"{r['close']:>11,.2f}{(r['resistance'] or 0):>11,.2f}"
                f"{(r['distance_pct'] or 0):>8.2f}"
                f"{('yes' if r['tightness'] else '-'):>7}"
                f"{('yes' if r['is_52w_high'] else '-'):>6}{r['days_in_state']:>6}")
        near = sum(1 for r in rows if r["state"] == "NEAR")
        lines.append(f"{len(rows)} rows — {near} NEAR, {len(rows) - near} WATCH")
        return "\n".join(lines)


async def _stats(source: str) -> dict:
    async with SessionFactory() as session:
        return await get_stats(session, source=source)


async def _universe() -> str:
    # Formatted INSIDE the session: these are session-bound rows.
    async with SessionFactory() as session:
        members = await get_universe(session)
        if not members:
            return "empty universe — run `python -m app.labs.nse_breakout backfill`"
        header = (f"{'symbol':<14}{'name':<34}{'bars':>6}{'last_close':>12}"
                  f"{'turnover_20d':>16}{'last_seen':>12}")
        lines = [header, "-" * len(header)]
        for m in members:
            lines.append(
                f"{m.symbol[:13]:<14}{(m.name or '')[:33]:<34}{m.bars:>6}"
                f"{float(m.last_close or 0):>12,.2f}"
                f"{float(m.turnover_20d or 0):>16,.0f}"
                f"{m.last_seen.isoformat():>12}")
        lines.append(f"{len(members)} active, ≥{config.MIN_BARS_FOR_LEVELS} bars = "
                     f"{sum(1 for m in members if m.bars >= config.MIN_BARS_FOR_LEVELS)}")
        return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m app.labs.nse_breakout")
    sub = parser.add_subparsers(dest="command", required=True)

    ingest = sub.add_parser("ingest", help="one day's bhavcopy")
    ingest.add_argument("--date", type=date.fromisoformat, default=None)

    backfill = sub.add_parser("backfill", help="walk the archive backwards")
    backfill.add_argument("--days", type=int, default=config.BACKFILL_DAYS_PER_RUN)
    backfill.add_argument("--all", action="store_true",
                          help="loop until nothing is pending")

    sub.add_parser("detect", help="one detection pass on the newest bar")
    sub.add_parser("near", help="the current board")
    replay = sub.add_parser("replay", help="the causal walk over history")
    replay.add_argument("--all", action="store_true",
                        help="loop until every symbol has been walked")
    replay.add_argument("--symbols", type=int,
                        default=config.REPLAY_SYMBOLS_PER_RUN)
    outcomes = sub.add_parser("outcomes",
                              help="fill outcomes whose window has closed")
    outcomes.add_argument("--all", action="store_true",
                          help="loop until every symbol has been visited")
    stats = sub.add_parser("stats")
    stats.add_argument("--source", default="replay",
                       choices=("replay", "live"))
    sub.add_parser("universe")
    sub.add_parser("health")

    args = parser.parse_args()
    if not config.enabled() and args.command != "health":
        sys.stderr.write("NSE_BREAKOUT_ENABLED is not set — nothing would run\n")
        return 1

    if args.command == "ingest":
        out = asyncio.run(_one_day(args.date) if args.date else ingest_tick())
    elif args.command == "backfill":
        out = asyncio.run(_backfill_all(args.days) if args.all
                          else backfill_tick(limit=args.days))
    elif args.command == "detect":
        out = asyncio.run(detect_tick())
    elif args.command == "replay":
        out = asyncio.run(_replay_all() if args.all
                          else replay_tick(limit=args.symbols))
    elif args.command == "outcomes":
        out = asyncio.run(_outcomes_all() if args.all else outcomes_tick())
    elif args.command == "stats":
        out = asyncio.run(_stats(args.source))
    elif args.command == "near":
        sys.stdout.write(asyncio.run(_near()) + "\n")
        return 0
    elif args.command == "universe":
        sys.stdout.write(asyncio.run(_universe()) + "\n")
        return 0
    else:
        out = asyncio.run(_health())
    sys.stdout.write(json.dumps(out, indent=2, default=str) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
