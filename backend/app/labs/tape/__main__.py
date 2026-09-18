"""`python -m app.labs.tape <command>`

    harvest --from ISO --to ISO   list, tape, price and trace every graduation in the span
    watch --from ISO --to ISO     follow each coin's >= 1% wallets through the 4-min hold
    status                        what the file holds
    study [--split ISO]           the pre-registered backtest, as JSON + a text report
    export-operators --out CSV    operators + rug labels, for the graduation lab's seed

Needs `HELIUS_API_KEY` (read by the platform's settings, from the environment or
a `.env` in the working directory). The key is never printed: the URL is built
by `settings.HELIUS_RPC_URL` and every error path redacts it.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime

from app.core.config import settings
from app.labs.tape import chain, store


def _ts(value: str) -> int:
    parsed = datetime.fromisoformat(value)
    return int((parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)).timestamp())


async def _harvest(args: argparse.Namespace) -> dict[str, object]:
    if not settings.helius_configured:
        raise SystemExit("HELIUS_API_KEY is not set")
    db = store.connect(args.db)
    async with chain.Helius(settings.HELIUS_RPC_URL, rps=args.rps) as h:
        return await chain.harvest(h, db, t_from=_ts(args.t_from), t_to=_ts(args.t_to),
                                   workers=args.workers)


async def _watch(args: argparse.Namespace) -> dict[str, object]:
    if not settings.helius_configured:
        raise SystemExit("HELIUS_API_KEY is not set")
    db = store.connect(args.db)
    async with chain.Helius(settings.HELIUS_RPC_URL, rps=args.rps) as h:
        return await chain.watch_all(h, db, t_from=_ts(args.t_from), t_to=_ts(args.t_to),
                                     workers=args.workers)


def _status(args: argparse.Namespace) -> dict[str, object]:
    db = store.connect(args.db)
    one = lambda sql: db.execute(sql).fetchone()  # noqa: E731
    lo, hi, n = one("SELECT min(t0), max(t0), count(*) FROM grads")
    return {
        "graduations": n,
        "normal": one("SELECT count(*) FROM grads WHERE quote0 >= 50e9")[0],
        "span": [datetime.fromtimestamp(x, UTC).isoformat() if x else None for x in (lo, hi)],
        "taped": one("SELECT count(*) FROM grads WHERE tape='ok'")[0],
        "tape_errors": one("SELECT count(*) FROM grads WHERE tape LIKE 'error:%'")[0],
        "priced": one("SELECT count(*) FROM grads WHERE points='ok'")[0],
        "traced": one("SELECT count(*) FROM grads WHERE funders='ok'")[0],
        "trades": one("SELECT count(*) FROM trades")[0],
        "balances": one("SELECT count(*) FROM balances")[0],
        "points": one("SELECT count(*) FROM points")[0],
        "funders": one("SELECT count(*), count(funder) FROM funders"),
        "watched": one("SELECT count(DISTINCT mint), count(t), sum(capped) FROM moves"),
    }


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.labs.tape")
    parser.add_argument("--db", default=None, help="SQLite path (default $TAPE_DB)")
    sub = parser.add_subparsers(dest="command", required=True)
    h = sub.add_parser("harvest")
    h.add_argument("--from", dest="t_from", required=True)
    h.add_argument("--to", dest="t_to", required=True)
    h.add_argument("--workers", type=int, default=8)
    h.add_argument("--rps", type=float, default=40.0)
    w = sub.add_parser("watch")
    w.add_argument("--from", dest="t_from", required=True)
    w.add_argument("--to", dest="t_to", required=True)
    w.add_argument("--workers", type=int, default=8)
    w.add_argument("--rps", type=float, default=35.0)
    sub.add_parser("status")
    x = sub.add_parser("export-operators")
    x.add_argument("--out", required=True)
    s = sub.add_parser("study")
    s.add_argument("--split", default=None, help="first out-of-sample day (default: 60/40)")
    args = parser.parse_args()

    if args.command == "harvest":
        out: object = asyncio.run(_harvest(args))
    elif args.command == "watch":
        out = asyncio.run(_watch(args))
    elif args.command == "status":
        out = _status(args)
    else:
        from app.labs.tape import study

        db = store.connect(args.db)
        out = (study.export_operators(db, args.out) if args.command == "export-operators"
               else study.run(db, split=args.split))
    sys.stdout.write(json.dumps(out, indent=2, default=str) + "\n")


if __name__ == "__main__":
    main()
