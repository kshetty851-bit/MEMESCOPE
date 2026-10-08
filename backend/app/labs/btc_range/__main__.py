"""`python -m app.labs.btc_range <command>` - the lab's own entry point.

    backfill --days N   fetch N days of history (idempotent; closed candles are never changed)
    ingest              one catch-up pass, exactly what the beat task does

Read-only market data in, rows in `btc_candles` out. Works with the beat flag
off: the flag gates the SCHEDULED task, not an operator running this by hand.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime

from app.core.config import settings
from app.db.session import SessionFactory, dispose_engine
from app.labs.btc_range.ingest import IngestResult, backfill, ingest_latest
from app.labs.btc_range.source import BinanceKlineClient, KlineError


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.labs.btc_range")
    sub = parser.add_subparsers(dest="command", required=True)
    back = sub.add_parser("backfill", help="fetch N days of history")
    back.add_argument("--days", type=int, default=90)
    sub.add_parser("ingest", help="one catch-up pass")
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


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "backfill" and args.days < 1:
        sys.stderr.write("--days must be >= 1\n")
        return 2
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
