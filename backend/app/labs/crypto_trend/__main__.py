"""`python -m app.labs.crypto_trend <command>` — the lab's own entry point.

    tick                                   one data pass
    run                                    the data pass every 60s, foreground
    health                                 data_health() as JSON
    trend                                  the engine once, as a table
    backfill --tf 1h --to-match 4h         deep-fill one timeframe back to another's start
    backfill --tf 1d --from 2021-01-01     deep-fill a timeframe from a fixed date
    universe snapshot --as-of DATE --name N   freeze the top-20 as of DATE
    universe from-daily --since DATE --name N  freeze a universe from stored coverage

Exists so the lab is runnable without registering anything in the platform's
Celery beat.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime

from app.db.session import SessionFactory
from app.labs.crypto_trend import config
from app.labs.crypto_trend.data import data_health, get_regime, get_trend_state, get_universe
from app.labs.crypto_trend.scheduler import tick, trend_tick
from app.labs.crypto_trend.trend import TrendState, coin_verdict

POLL_SECONDS = 60


async def _run() -> None:
    while True:
        sys.stdout.write(json.dumps(await tick()) + "\n")
        sys.stdout.flush()
        await asyncio.sleep(POLL_SECONDS)


async def _health() -> dict:
    async with SessionFactory() as session:
        return await data_health(session)


def _cell(s: TrendState | None) -> str:
    if s is None:
        return f"{'-':<6}{'':>4}{'':>6}{'':>7}{'':>3}"
    veto = "!" if s.structure_veto else ""
    return f"{s.direction:<6}{s.strength:>4}{s.bars_in_state:>6}{s.adx:>7.1f}{veto:>3}"


async def _trend() -> str:
    summary = await trend_tick()
    if "states" not in summary:  # disabled, or the engine failed
        return json.dumps(summary)
    async with SessionFactory() as session:
        members = await get_universe(session)
        latest = {(s.symbol, s.timeframe): s for s in await get_trend_state(session)}
        regimes = await get_regime(session, limit=1)
    head = f"{'dir':<6}{'str':>4}{'bars':>6}{'adx':>7}{'v':>3}"
    lines = [f"{'symbol':<14}{head}   {head}   verdict  (! = structure veto)",
             f"{'':<14}{'4h':<26}   {'1h':<26}"]
    for m in members:
        s4, s1 = latest.get((m.binance_symbol, "4h")), latest.get((m.binance_symbol, "1h"))
        v = coin_verdict(m.binance_symbol, s4, s1)
        lines.append(f"{m.binance_symbol:<14}{_cell(s4)}   {_cell(s1)}   "
                     f"{v.verdict} ({v.reason})")
    if regimes:
        r = regimes[0]
        lines.append(f"regime {r.regime}  breadth_up {r.breadth_up:.2f}  "
                     f"breadth_down {r.breadth_down:.2f}  btc {r.btc_direction}  "
                     f"eth {r.eth_direction}  bar {r.bar_close_time.isoformat()}")
    lines.append(json.dumps(summary))
    return "\n".join(lines)


async def _backfill(timeframe: str, reference: str | None, start: str | None) -> dict:
    """One-off, idempotent, logs the requests used.

    With `--to-match`, extends `timeframe` back to the earliest stored
    reference candle for every live-universe symbol. With `--from`, fills
    from a fixed date for every symbol the lab knows — the live universe,
    every stored snapshot, and BTC and ETH.
    """
    from app.labs.crypto_trend.service import CryptoTrendService
    from app.labs.crypto_trend.snapshots import known_symbols
    from app.labs.crypto_trend.sources import MarketSource

    if not config.enabled():
        return {"skipped": "crypto_trend_lab_disabled"}
    now = datetime.now(UTC)
    async with MarketSource() as source, SessionFactory() as session:
        service = CryptoTrendService(session, source)
        if start is not None:
            symbols = await known_symbols(session, extra=("BTCUSDT", "ETHUSDT"))
            result = await service.backfill_from(
                symbols, timeframe=timeframe,
                start=datetime.fromisoformat(start).replace(tzinfo=UTC), now=now)
        else:
            symbols = [c.binance_symbol for c in await get_universe(session)]
            result = await service.backfill_to_match(
                symbols, timeframe=timeframe, reference=reference, now=now)
        await session.commit()
    result["http_requests"] = source.requests
    return result


async def _from_daily(name: str, since: str, timeframe: str) -> dict:
    from app.labs.crypto_trend.snapshots import snapshot_from_coverage

    async with SessionFactory() as session:
        result = await snapshot_from_coverage(
            session, name=name, timeframe=timeframe,
            since=datetime.fromisoformat(since).replace(tzinfo=UTC))
        await session.commit()
    return result


async def _snapshot(name: str, as_of: str) -> dict:
    from app.labs.crypto_trend.snapshots import SnapshotService
    from app.labs.crypto_trend.sources import MarketSource

    if not config.enabled():
        return {"skipped": "crypto_trend_lab_disabled"}
    when = datetime.fromisoformat(as_of).replace(tzinfo=UTC)
    async with MarketSource() as source, SessionFactory() as session:
        result = await SnapshotService(session, source).create(name=name, as_of=when,
                                                               now=datetime.now(UTC))
        await session.commit()
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.labs.crypto_trend")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("tick", "run", "health", "trend"):
        sub.add_parser(name)
    backfill = sub.add_parser("backfill")
    backfill.add_argument("--tf", default="1h", choices=("1h", "4h", "1d"))
    backfill.add_argument("--to-match", dest="reference", choices=("1h", "4h", "1d"))
    backfill.add_argument("--from", dest="start", metavar="YYYY-MM-DD",
                          help=f"default {config.DAILY_BACKFILL_START} for --tf 1d")
    universe = sub.add_parser("universe")
    universe.add_argument("action", choices=["snapshot", "from-daily"])
    universe.add_argument("--as-of", dest="as_of", help="snapshot: YYYY-MM-DD, UTC")
    universe.add_argument("--since", help="from-daily: YYYY-MM-DD, UTC")
    universe.add_argument("--tf", default="1d", choices=("1h", "4h", "1d"))
    universe.add_argument("--name", required=True)
    args = parser.parse_args(argv)

    if args.command == "tick":
        sys.stdout.write(json.dumps(asyncio.run(tick()), indent=2) + "\n")
    elif args.command == "run":
        asyncio.run(_run())
    elif args.command == "health":
        sys.stdout.write(json.dumps(asyncio.run(_health()), indent=2) + "\n")
    elif args.command == "trend":
        sys.stdout.write(asyncio.run(_trend()) + "\n")
    elif args.command == "backfill":
        start, reference = args.start, args.reference
        if start is None and reference is None:
            start = config.DAILY_BACKFILL_START if args.tf == "1d" else None
            reference = "4h" if start is None else None
        if start is not None and reference is not None:
            parser.error("pass either --from or --to-match, not both")
        if reference is not None and args.tf == reference:
            parser.error("--tf and --to-match must differ")
        sys.stdout.write(json.dumps(asyncio.run(_backfill(args.tf, reference, start)),
                                    indent=2) + "\n")
    elif args.command == "universe":
        if args.action == "snapshot":
            if not args.as_of:
                parser.error("snapshot needs --as-of")
            out = asyncio.run(_snapshot(args.name, args.as_of))
        else:
            if not args.since:
                parser.error("from-daily needs --since")
            out = asyncio.run(_from_daily(args.name, args.since, args.tf))
        sys.stdout.write(json.dumps(out, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
