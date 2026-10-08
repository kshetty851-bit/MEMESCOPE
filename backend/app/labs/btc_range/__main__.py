"""`python -m app.labs.btc_range <command>` - the lab's own entry point.

    backfill --days N   fetch N days of history (idempotent; closed candles are never changed)
    ingest              one catch-up pass, exactly what the beat task does
    replay --hours N    replay the last N hours (default 24) through the default config
                        and print what the strategy would have done; reads only

Read-only market data in, rows in `btc_candles` out. Works with the beat flag
off: the flag gates the SCHEDULED task, not an operator running this by hand. `replay`
reads stored candles only and writes nothing.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import sys
from datetime import UTC, datetime

from app.core.config import settings
from app.db.session import SessionFactory, dispose_engine
from app.labs.btc_range import service
from app.labs.btc_range.ingest import IngestResult, backfill, ingest_latest
from app.labs.btc_range.source import BinanceKlineClient, KlineError


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.labs.btc_range")
    sub = parser.add_subparsers(dest="command", required=True)
    back = sub.add_parser("backfill", help="fetch N days of history")
    back.add_argument("--days", type=int, default=90)
    sub.add_parser("ingest", help="one catch-up pass")
    replay = sub.add_parser("replay", help="replay the last N hours through the defaults")
    replay.add_argument("--hours", type=int, default=24)
    return parser


async def _run(args: argparse.Namespace) -> IngestResult:
    now = datetime.now(UTC)
    try:
        async with (
            BinanceKlineClient(settings.LAB_BTC_RANGE_BINANCE_URL) as client,
            SessionFactory() as session,
        ):
            if args.command == "backfill":
                result = await backfill(session, client, days=args.days, now=now)
            else:
                result = await ingest_latest(session, client, now=now)
            await session.commit()
            return result
    finally:
        await dispose_engine()


async def _replay(hours: int) -> dict[str, object]:
    try:
        async with SessionFactory() as session:
            return await service.replay(session, now=datetime.now(UTC), hours=hours)
    finally:
        await dispose_engine()


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "backfill" and args.days < 1:
        sys.stderr.write("--days must be >= 1\n")
        return 2
    if args.command == "replay":
        if args.hours < 1:
            sys.stderr.write("--hours must be >= 1\n")
            return 2
        # Engine teardown logs to stdout; send it to stderr so stdout is the JSON alone
        # and `| jq` works.
        with contextlib.redirect_stdout(sys.stderr):
            report = asyncio.run(_replay(args.hours))
        sys.stdout.write(json.dumps(report, indent=2) + "\n")
        return 0
    try:
        result = asyncio.run(_run(args))
    except KlineError as exc:
        sys.stderr.write(f"candle source failed: {exc}\n")
        return 1
    sys.stdout.write(
        json.dumps(
            {"pages": result.pages, "fetched": result.fetched, "written": result.written}
        )
        + "\n"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
