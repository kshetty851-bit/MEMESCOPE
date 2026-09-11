"""`python -m app.labs.nse_breakout <command>` — the tracker's entry point.

    ingest [--date YYYY-MM-DD]  one day's bhavcopy, then rebuild the universe
    backfill [--days N|--all]   walk the archive backwards; resumable
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
from app.labs.nse_breakout.data import get_universe, health
from app.labs.nse_breakout.ingest import Ingest
from app.labs.nse_breakout.scheduler import backfill_tick, ingest_tick
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
    """
    started = time.monotonic()
    days = rows = 0
    while True:
        result = await backfill_tick(limit=slice_days)
        if result.get("error") or result.get("skipped"):
            return {"stopped": result, "days": days, "rows": rows}
        days += result["days"]
        rows += result["rows"]
        sys.stdout.write(
            f"[{time.monotonic() - started:7.0f}s] +{result['days']}d "
            f"ok={result['ok']} rows={result['rows']} "
            f"remaining={result['remaining_days']}\n")
        sys.stdout.flush()
        if not result["remaining_days"] or not result["days"]:
            return {"days": days, "rows": rows,
                    "seconds": round(time.monotonic() - started, 1),
                    "remaining_days": result["remaining_days"]}


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
    elif args.command == "universe":
        sys.stdout.write(asyncio.run(_universe()) + "\n")
        return 0
    else:
        out = asyncio.run(_health())
    sys.stdout.write(json.dumps(out, indent=2, default=str) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
