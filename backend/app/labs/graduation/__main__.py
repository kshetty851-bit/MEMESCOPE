"""`python -m app.labs.graduation <command>` — the lab's own entry point.

    record                  hold the socket open, poll the chain, fill the tables
    poll                    one curve poll pass over the current watch set
    features [--recompute]  build grad_features for graduates whose hour is up
    summary                 the distribution Phase 3 is judged against
    backtest [--strategy N] replay the baselines, per-week table and gate
    prune                   one prune pass
    health                  recorder_health() as JSON
    curve --mint MINT       derive the PDA, read the account, decode it
    progress --tokens N     what N virtual token reserves means, as a percentage

Exists so the lab is runnable without registering anything in the platform's
Celery beat. `record` is the process that does the work; the beat task is only
the pruning behind it.

`curve` is the one-shot diagnostic: it does the whole chain — derive, fetch,
decode, compute — for a single mint, which is the fastest way to tell a bad
RPC endpoint from a bad mint from a changed account layout.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import pathlib
import signal
import sys
from decimal import Decimal, InvalidOperation
from typing import Any

from app.db.session import SessionFactory
from app.labs.graduation import config, curve
from app.labs.graduation.backtest import (
    BASELINES,
    Backtester,
    coverage_line,
    format_report,
    load_replays,
    trades_csv,
)
from app.labs.graduation.features import format_summary, summary
from app.labs.graduation.recorder import GraduationRecorder, recorder_health
from app.labs.graduation.scheduler import features_tick, prune_tick
from app.labs.graduation.sources import CurveRPC


def _emit(payload: object) -> None:
    """Stdout, the way the sibling labs' CLIs do it. Routing a command-line
    tool's output through structlog would emit JSON at an operator."""
    sys.stdout.write(json.dumps(payload, default=str, indent=2) + "\n")


async def _record() -> int:
    """Run until SIGINT/SIGTERM, then flush what is buffered and exit."""
    recorder = GraduationRecorder()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):  # not on Windows
            loop.add_signal_handler(sig, recorder.stream.stop)
    sys.stderr.write(f"polling {config.safe_rpc_url()} every {config.POLL_INTERVAL_S}s, "
                     f"watch set <= {config.MAX_WATCH_SET}\n")
    await recorder.run()
    return 0


async def _summary() -> str:
    async with SessionFactory() as session:
        return format_summary(await summary(session))


async def _backtest(names: list[str], limit: int) -> tuple[str, str]:
    """Replay each named strategy over one load of the recorded series.

    Returns the report and the CSV rather than writing the file: the caller is
    synchronous, and a blocking disk write inside the event loop is the kind of
    thing that is invisible here and not invisible under a scheduler.
    """
    async with SessionFactory() as session:
        coverage = await coverage_line(session)
        replays = await load_replays(session, limit=limit)
    if not replays:
        return "no recorded tokens to replay — run `record` first", ""

    blocks: list[str] = []
    rows: list[Any] = []
    printed: dict[str, Any] | None = coverage
    for name in names:
        result = Backtester(BASELINES[name]).run(replays)
        rows.extend(result.trades)
        blocks.append(format_report(result, coverage=printed))
        printed = None  # printed once, above everything
    return "\n\n".join(blocks), trades_csv(rows)


async def _health() -> dict:
    async with SessionFactory() as session:
        return await recorder_health(session)


async def _curve(mint: str) -> dict:
    """Derive, fetch and decode one mint's curve. One RPC call."""
    async with CurveRPC() as rpc:
        address = rpc.address_for(mint)
        if address is None:
            return {"mint": mint, "error": "not a valid base58 mint"}
        readings = await rpc.fetch([mint])
        if mint not in readings:
            return {"mint": mint, "curve_address": address,
                    "error": "the RPC read did not happen", "rpc": config.safe_rpc_url()}
        state = readings[mint]
        if state is None:
            return {"mint": mint, "curve_address": address,
                    "account": "absent or not a bonding curve"}
        v_quote, real_quote = curve.quote_reserves(state)
        return {
            "mint": mint,
            "curve_address": address,
            "progress_pct": str(curve.progress_of(state)),
            "complete": state.complete,
            "v_token_reserves": str(curve.whole_tokens(state.virtual_token_reserves)),
            "real_token_reserves": str(curve.whole_tokens(state.real_token_reserves)),
            "v_quote_reserves": str(v_quote),
            "real_quote_reserves": str(real_quote),
            "token_total_supply": str(curve.whole_tokens(state.token_total_supply)),
            "market_cap_quote": str(curve.market_cap_quote(state)),
        }


def _progress(tokens: str) -> dict[str, str]:
    try:
        value = Decimal(tokens)
    except (InvalidOperation, ValueError):
        return {"error": f"not a number: {tokens!r}"}
    return {
        "virtual_token_reserves": str(value),
        "progress_pct": str(curve.progress_pct(value, pool=config.CURVE_POOL)),
        "curve_floor_raw": str(curve.curve_floor_tokens()),
        "note": "reserves are RAW base units (6 decimals), as the account carries them",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.labs.graduation")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("record", help="hold the socket open and poll the chain")
    sub.add_parser("poll", help="one curve poll pass")
    feats = sub.add_parser("features", help="build grad_features")
    feats.add_argument("--recompute", action="store_true",
                       help="rewrite rows that already exist, not just new ones")
    sub.add_parser("summary", help="the return distribution, with its denominator")
    back = sub.add_parser("backtest", help="replay the baselines")
    back.add_argument("--strategy", action="append", choices=sorted(BASELINES),
                      help="repeatable; default is every baseline")
    back.add_argument("--csv", help="write the per-trade rows here")
    back.add_argument("--limit", type=int, default=5000,
                      help="maximum tokens to load")
    sub.add_parser("prune", help="one prune pass")
    sub.add_parser("health", help="recorder_health() as JSON")
    one = sub.add_parser("curve", help="derive, fetch and decode one mint's curve")
    one.add_argument("--mint", required=True)
    progress = sub.add_parser("progress", help="what a reserve reading means")
    progress.add_argument("--tokens", required=True)
    args = parser.parse_args(argv)

    if not config.enabled() and args.command in ("record", "prune", "poll",
                                                 "features"):
        sys.stderr.write("LAB_GRADUATION_ENABLED is not set — nothing will run.\n")
        return 1

    if args.command == "record":
        try:
            return asyncio.run(_record())
        except KeyboardInterrupt:
            # `run()` flushes in its own `finally`; this is a clean exit.
            return 0
    if args.command == "poll":
        _emit(asyncio.run(_poll_once()))
        return 0
    if args.command == "features":
        _emit(asyncio.run(features_tick(recompute=args.recompute)))
        return 0
    if args.command == "summary":
        sys.stdout.write(asyncio.run(_summary()) + "\n")
        return 0
    if args.command == "backtest":
        report, rows = asyncio.run(
            _backtest(args.strategy or sorted(BASELINES), args.limit))
        if args.csv and rows:
            pathlib.Path(args.csv).write_text(rows)
            report += f"\n\n{len(rows.splitlines()) - 1} trades -> {args.csv}"
        sys.stdout.write(report + "\n")
        return 0
    if args.command == "prune":
        _emit(asyncio.run(prune_tick()))
        return 0
    if args.command == "health":
        _emit(asyncio.run(_health()))
        return 0
    if args.command == "curve":
        _emit(asyncio.run(_curve(args.mint)))
        return 0
    _emit(_progress(args.tokens))
    return 0


async def _poll_once() -> dict:
    """One pass over a watch set loaded from nothing — useful only with a
    `--mint`-seeded set, so it reports an empty pass honestly."""
    recorder = GraduationRecorder()
    async with recorder.rpc:
        from datetime import UTC, datetime

        result = await recorder.poll_once(datetime.now(UTC))
        await recorder.flush()
        return result


if __name__ == "__main__":
    raise SystemExit(main())
