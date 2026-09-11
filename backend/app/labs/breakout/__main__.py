"""`python -m app.labs.breakout <command>` — the lab's own entry point.

    tick                    one full tick: universe, candles, setups
    universe                the active universe as a table
    setups                  one setup pass, then the watchlist as a table
    levels --mint MINT      the resistance clusters for one token
    outcomes                fill outcome columns for episodes past their window
    backfill --mint MINT    fill both timeframes for one token, ignoring the
                            per-tick page cap
    health                  data_health() as JSON

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
from app.labs.breakout import config
from app.labs.breakout.data import data_health, get_levels, get_setups, get_universe
from app.labs.breakout.scheduler import outcomes_tick, setups_tick, tick


async def _health() -> dict:
    async with SessionFactory() as session:
        return await data_health(session)


async def _universe() -> str:
    # Formatted INSIDE the session: `get_universe` hands back session-bound
    # rows, and reading one after its session closes is a detached-instance
    # error waiting for the first person who adds a commit above.
    async with SessionFactory() as session:
        return _table(await get_universe(session))


def _table(members: list) -> str:
    if not members:
        return "empty universe — run `python -m app.labs.breakout tick` first"
    now = datetime.now(UTC)
    header = (f"{'symbol':<12}{'mint':<46}{'dex':<16}{'age_d':>7}"
              f"{'liq_usd':>14}{'vol_24h':>16}{'price':>14}{'alt':>5}{'fail':>6}")
    lines = [header, "-" * len(header)]
    for m in members:
        lines.append(
            f"{(m.symbol or '?')[:11]:<12}{m.mint:<46}{m.dex[:15]:<16}"
            f"{(now - m.pair_created_at).total_seconds() / 86400:>7.1f}"
            f"{float(m.liquidity_usd or 0):>14,.0f}"
            f"{float(m.volume_24h_usd or 0):>16,.0f}"
            f"{float(m.price_usd or 0):>14.8f}"
            f"{len(m.alt_pools or ()):>5}{m.fetch_failures:>6}"
        )
    lines.append(f"{len(members)} active, cap {config.MAX_UNIVERSE}")
    return "\n".join(lines)


async def _backfill(mint: str) -> dict:
    from sqlalchemy import select

    from app.labs.breakout.candles import BreakoutCandles
    from app.labs.breakout.models import BoUniverseMember
    from app.labs.breakout.sources import BreakoutSource

    if not config.enabled():
        return {"skipped": "breakout_lab_disabled"}
    async with BreakoutSource(max_calls=10_000) as source, SessionFactory() as session:
        member = (await session.execute(
            select(BoUniverseMember).where(BoUniverseMember.mint == mint)
        )).scalar_one_or_none()
        if member is None:
            return {"error": f"{mint} is not in bo_universe"}
        result = await BreakoutCandles(session, source).backfill(member, datetime.now(UTC))
        await session.commit()
    return result


async def _setups() -> str:
    summary = await setups_tick()
    if "by_state" not in summary:  # disabled, or the pass failed
        return json.dumps(summary, indent=2)
    async with SessionFactory() as session:
        rows = await get_setups(session)
    header = (f"{'state':<14}{'symbol':<12}{'score':>6}{'dist%':>8}{'price':>14}"
              f"{'resist':>14}{'hrs':>7}{'liq_usd':>13}")
    lines = [header, "-" * len(header)]
    for r in rows:
        lines.append(
            f"{r['state']:<14}{(r['symbol'] or '?')[:11]:<12}{r['score']:>6}"
            f"{(r['distance_pct'] if r['distance_pct'] is not None else 0):>8.2f}"
            f"{(r['price'] or 0):>14.8f}{(r['resistance'] or 0):>14.8f}"
            f"{r['hours_open']:>7.1f}{(r['liquidity_usd'] or 0):>13,.0f}")
    lines.append(json.dumps(summary))
    return "\n".join(lines)


async def _levels(mint: str) -> str:
    async with SessionFactory() as session:
        row = await get_levels(session, mint)
        if row is None:
            return f"no levels stored for {mint} (too few daily bars, or never seen)"
        close = float(row.close)
        header = f"{'level':>18}{'vs close':>11}{'touches':>9}{'broken':>8}  first -> last"
        lines = [f"{mint}  close {close:.8f}  "
                 f"nearest resistance "
                 f"{float(row.nearest_resistance) if row.nearest_resistance else 0:.8f}"
                 f"  atr {float(row.atr) if row.atr else 0:.8f}",
                 header, "-" * len(header)]
        for c in row.clusters:
            level = float(c["level"])
            lines.append(
                f"{level:>18.8f}{(level - close) / close * 100:>10.1f}%"
                f"{c['touches']:>9}{('yes' if c['broken'] else 'no'):>8}"
                f"  {c['first'][:10]} -> {c['last'][:10]}")
        return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.labs.breakout")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("tick", "universe", "health", "setups", "outcomes"):
        sub.add_parser(name)
    levels = sub.add_parser("levels")
    levels.add_argument("--mint", required=True)
    backfill = sub.add_parser("backfill")
    backfill.add_argument("--mint", required=True)
    args = parser.parse_args(argv)

    if args.command == "tick":
        sys.stdout.write(json.dumps(asyncio.run(tick()), indent=2) + "\n")
    elif args.command == "universe":
        sys.stdout.write(asyncio.run(_universe()) + "\n")
    elif args.command == "health":
        sys.stdout.write(json.dumps(asyncio.run(_health()), indent=2) + "\n")
    elif args.command == "setups":
        sys.stdout.write(asyncio.run(_setups()) + "\n")
    elif args.command == "levels":
        sys.stdout.write(asyncio.run(_levels(args.mint)) + "\n")
    elif args.command == "outcomes":
        sys.stdout.write(json.dumps(asyncio.run(outcomes_tick()), indent=2) + "\n")
    elif args.command == "backfill":
        sys.stdout.write(json.dumps(asyncio.run(_backfill(args.mint)), indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
