"""`python -m app.labs.forex_lab <command>` — the lab's own entry point.

    ingest [--start D] [--end D] [--concurrency N]   one resumable download pass
    status                                            what is loaded, as JSON
    integrity                                         the data integrity check
    verify [--days N]                                 stored candles vs the feed's own
    export                                            candles -> the replay file
    backtest [--step 25] [--levels 4] ...             one config, as JSON
    sweep [--jobs N] [--out PATH]                     the full parameter sweep
    report [--sweep PATH]                             write REPORT.md
    publish [--sweep PATH]                            put a sweep on the dashboard

Exists so the lab is runnable without registering anything in the platform's
Celery beat — this lab has no scheduled work at all, by design.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime, timedelta

from app.labs.forex_lab import config


def _date(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=UTC)


def _progress(stats: dict) -> None:
    done = stats["ok"] + stats["failed"]
    sys.stderr.write(
        f"[ingest] {datetime.now(UTC):%H:%M:%S} {done}/{stats['todo']} "
        f"ok={stats['ok']} failed={stats['failed']} empty={stats['empty']} "
        f"candles={stats['candles']} cooldowns={stats.get('cooldowns', 0)}"
        f"/{stats.get('cooldown_seconds', 0)}s\n"
    )
    sys.stderr.flush()


def _pass_done(n: int, stats: dict) -> None:
    sys.stderr.write(
        f"[ingest] === pass {n} done: ok={stats['ok']} failed={stats['failed']} "
        f"of {stats['todo']} ===\n"
    )
    sys.stderr.flush()


async def _ingest(args) -> dict:
    from app.db.session import SessionFactory
    from app.labs.forex_lab.ingest import ingest_until_clean

    return await ingest_until_clean(
        SessionFactory,
        start=_date(args.start) if args.start else None,
        end=(_date(args.end) + timedelta(days=1)) if args.end else None,
        concurrency=args.concurrency,
        passes=args.passes,
        progress_every=100,
        on_progress=_progress,
        on_pass=_pass_done,
    )


async def _status() -> dict:
    from app.db.session import SessionFactory
    from app.labs.forex_lab.store import status

    async with SessionFactory() as session:
        return await status(session)


async def _verify(args) -> dict:
    from app.db.session import SessionFactory
    from app.labs.forex_lab.ingest import verify_against_published

    return await verify_against_published(SessionFactory, days=args.days)


async def _export() -> dict:
    from app.db.session import SessionFactory
    from app.labs.forex_lab.backtest import CANDLE_FILE, export_candles

    async with SessionFactory() as session:
        n = await export_candles(session)
    return {"candles": n, "path": str(CANDLE_FILE),
            "bytes": CANDLE_FILE.stat().st_size}


async def _integrity() -> dict:
    from app.db.session import SessionFactory
    from app.labs.forex_lab.store import integrity_check

    async with SessionFactory() as session:
        return await integrity_check(session)


async def _publish(args) -> dict:
    from app.db.session import SessionFactory
    from app.labs.forex_lab.backtest import publish

    return await publish(SessionFactory, args.sweep)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="app.labs.forex_lab")
    sub = p.add_subparsers(dest="cmd", required=True)

    ing = sub.add_parser("ingest", help="one resumable download pass")
    ing.add_argument("--start")
    ing.add_argument("--end")
    ing.add_argument("--concurrency", type=int, default=None)
    ing.add_argument("--passes", type=int, default=8,
                     help="repeat until nothing is outstanding (default 8)")

    sub.add_parser("status", help="what is loaded")
    sub.add_parser("integrity", help="the data integrity check")
    ver = sub.add_parser("verify", help="stored candles vs the feed's own candles")
    ver.add_argument("--days", type=int, default=20)
    sub.add_parser("export", help="candles -> the binary replay file")

    bt = sub.add_parser("backtest", help="one config")
    bt.add_argument("--step", type=int, default=config.DEFAULT_STEP_PIPS)
    bt.add_argument("--levels", type=int, default=config.DEFAULT_LEVELS)
    bt.add_argument("--stop-mult", type=float, default=1.0)
    bt.add_argument("--lots", type=float, default=config.DEFAULT_LOTS)
    bt.add_argument("--trades", action="store_true", help="include the trade list")

    sw = sub.add_parser("sweep", help="the full parameter sweep")
    sw.add_argument("--jobs", type=int, default=0, help="0 = one per CPU")
    sw.add_argument("--out", default="sweep.json")

    rp = sub.add_parser("report", help="write REPORT.md")
    rp.add_argument("--sweep", default="sweep.json")

    pb = sub.add_parser("publish", help="put a sweep on the dashboard")
    pb.add_argument("--sweep", default="sweep.json")

    args = p.parse_args(argv)

    if args.cmd == "ingest":
        print(json.dumps(asyncio.run(_ingest(args)), indent=2))
    elif args.cmd == "status":
        print(json.dumps(asyncio.run(_status()), indent=2, default=str))
    elif args.cmd == "verify":
        r = asyncio.run(_verify(args))
        print(json.dumps(r, indent=2, default=str))
        return 0 if r["passed"] else 1
    elif args.cmd == "export":
        print(json.dumps(asyncio.run(_export()), indent=2))
    elif args.cmd == "integrity":
        r = asyncio.run(_integrity())
        print(json.dumps(r, indent=2, default=str))
        return 0 if r["passed"] else 1
    elif args.cmd == "backtest":
        from app.labs.forex_lab.backtest import run_one_sync

        print(json.dumps(run_one_sync(args.step, args.levels, args.stop_mult,
                                      args.lots, with_trades=args.trades),
                         indent=2, default=str))
    elif args.cmd == "sweep":
        from app.labs.forex_lab.backtest import run_sweep_sync

        print(json.dumps(run_sweep_sync(args.out, jobs=args.jobs), indent=2, default=str))
    elif args.cmd == "publish":
        print(json.dumps(asyncio.run(_publish(args)), indent=2, default=str))
    elif args.cmd == "report":
        from app.labs.forex_lab.report import write_report

        print(write_report(args.sweep))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
