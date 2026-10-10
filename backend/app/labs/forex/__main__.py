"""`python -m app.labs.forex <command>` - the lab's own entry point.

    import <csv> --symbol EURUSD --timeframe 1m [--format auto] [--utc-offset-minutes 0]
                          store a candle file (idempotent; stored candles are never changed).
                          Use this for large files: the HTTP route caps an upload at 60 MB.
    fetch --start YYYY-MM-DD --end YYYY-MM-DD [--symbol EURUSD]
                          download 1-minute candles day by day (cached days are skipped).
    backtest --strategy rsi_pullback --start YYYY-MM-DD --end YYYY-MM-DD
                          replay the strategy's default config over stored candles and print
                          the summary as JSON.

Research and paper only: the one network call is the public historical-candle
download, and nothing here places an order or holds a credential. Each command
owns its session and commits explicitly.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from app.db.session import SessionFactory, dispose_engine
from app.labs.forex import codec, meta, service
from app.labs.forex.csv_import import FORMATS
from app.labs.forex.types import StrategyId


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.labs.forex")
    sub = parser.add_subparsers(dest="command", required=True)

    imp = sub.add_parser("import", help="store a candle CSV")
    imp.add_argument("csv", type=Path)
    imp.add_argument("--symbol", default="EURUSD")
    imp.add_argument("--timeframe", default="1m")
    imp.add_argument("--format", dest="fmt", default="auto", choices=FORMATS)
    imp.add_argument("--utc-offset-minutes", type=int, default=0)

    fetch = sub.add_parser("fetch", help="download 1-minute candles")
    fetch.add_argument("--start", required=True, type=date.fromisoformat)
    fetch.add_argument("--end", required=True, type=date.fromisoformat)
    fetch.add_argument("--symbol", default="EURUSD")

    back = sub.add_parser("backtest", help="replay a default strategy config")
    back.add_argument("--strategy", required=True, choices=[s.value for s in StrategyId])
    back.add_argument("--start", required=True, type=date.fromisoformat)
    back.add_argument("--end", required=True, type=date.fromisoformat)
    back.add_argument("--timeframe", default=None)
    return parser


def _day_start(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, tzinfo=UTC)


async def _import(args: argparse.Namespace) -> dict[str, Any]:
    text = args.csv.read_text(encoding="utf-8", errors="replace")
    async with SessionFactory() as session:
        batch = await service.import_csv(
            session,
            symbol=args.symbol,
            timeframe=args.timeframe,
            fmt=args.fmt,
            utc_offset_minutes=args.utc_offset_minutes,
            filename=args.csv.name,
            content=text,
        )
        await session.commit()
    keep = (
        "id", "symbol", "timeframe", "filename", "rows_total", "rows_accepted",
        "rows_inserted", "rows_existing", "error_count", "detected_format", "start", "end",
    )  # fmt: skip
    out: dict[str, Any] = {k: batch[k] for k in keep}
    out["notes"] = [n["text"] for n in batch["notes"]]
    out["quality_grade"] = (batch["quality"] or {}).get("grade")
    out["first_errors"] = batch["errors"][:5]
    return out


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    """Queue a fetch or backtest run, execute it here, and report it."""
    async with SessionFactory() as session:
        if args.command == "fetch":
            run = await service.create_fetch_run(
                session,
                provider=service.PROVIDER,
                symbol=args.symbol,
                start_date=args.start,
                end_date=args.end,
            )
        else:
            cfg = meta.default_config(StrategyId(args.strategy))
            if args.timeframe:
                data = codec.config_to_json(cfg)
                data["timeframe"] = args.timeframe
                cfg = codec.config_from_json(data)
            run = await service.create_run(
                session,
                kind="backtest",
                config=codec.config_to_json(cfg),
                configs=None,
                start=_day_start(args.start),
                end=_day_start(args.end) + timedelta(days=1),
                name=None,
                strategy_version_id=None,
                options=None,
            )
        await session.commit()
        await service.execute_run(session, int(run["id"]), commit=True)
        detail = await service.get_run(session, int(run["id"]))
    finished = detail["run"]
    if finished["status"] != "done":
        return {
            "run_id": finished["id"],
            "status": finished["status"],
            "error": finished["error"],
        }
    if args.command == "fetch":
        return {"run_id": finished["id"], "status": "done", **detail["result"]}
    return {"run_id": finished["id"], "status": "done", "summary": finished["summary"]}


async def _main(args: argparse.Namespace) -> dict[str, Any]:
    try:
        if args.command == "import":
            return await _import(args)
        return await _run(args)
    finally:
        await dispose_engine()


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        # Engine teardown logs to stdout; send it to stderr so stdout is the JSON alone.
        with contextlib.redirect_stdout(sys.stderr):
            report = asyncio.run(_main(args))
    except (ValueError, OSError) as exc:
        sys.stderr.write(f"{exc}\n")
        return 2
    sys.stdout.write(json.dumps(report, indent=2, default=str) + "\n")
    return 0 if report.get("status", "done") == "done" else 1


if __name__ == "__main__":
    sys.exit(main())
