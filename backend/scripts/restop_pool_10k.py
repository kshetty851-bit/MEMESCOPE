"""Re-price the Pool Lab's $10k book with its 10% stop, as if from day 1.

Karthik, 2026-10-07: "apply -10% stop loss to 10k book and revise profit
assuming we started day 1". Every closed POOL_10K_QUIET_3M trade opened before
the stop went live is walked through its own price marks the way `_manage`
does: the first mark at or under the stop DECIDES, the sale is priced by the
first mark `EXIT_REACTION_S` after it (`exit_mark` / `valued` / `settle`). A
trade whose marks never reach the stop keeps its three-minute close.

The rows it changes are written first to a JSON backup beside it, so the
original three-minute closes can be put back.

    docker exec -w /app memescope-worker-1 python scripts/restop_pool_10k.py [--apply]
"""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.db.session import SessionFactory
from app.labs.graduation import config
from app.labs.graduation.models import GradPaperPosition, GradPostgradSample
from app.labs.graduation.tournament import (
    BY_NAME,
    Mark,
    _timed_due,
    exit_mark,
    seen_at,
    settle,
    valued,
)

BOOK = "POOL_10K_QUIET_3M"
SAVED = ("closed_at", "close_quote", "close_fill", "close_reason", "pnl_quote", "net_return",
         "pnl_usd", "liq_close_usd", "impact_close", "exit_signal_at", "exit_signal")


async def main(apply: bool) -> None:
    stop = BY_NAME[BOOK].stop
    assert stop is not None, "the arm has no stop yet"
    react = timedelta(seconds=config.EXIT_REACTION_S)
    async with SessionFactory() as session:
        rows = (await session.scalars(
            select(GradPaperPosition)
            .where(GradPaperPosition.book == BOOK, GradPaperPosition.closed_at.is_not(None),
                   GradPaperPosition.exit_signal_at.is_(None))
            .order_by(GradPaperPosition.opened_at))).all()
        backup, changed = [], 0
        for row in rows:
            due = _timed_due(row)
            marks = [Mark(s.price_native, s.liquidity_usd, s.ts, s.source)
                     for s in await session.scalars(
                         select(GradPostgradSample)
                         .where(GradPostgradSample.mint == row.mint,
                                GradPostgradSample.ts >= row.opened_at,
                                GradPostgradSample.ts <= due + timedelta(minutes=2),
                                GradPostgradSample.price_native.is_not(None))
                         .order_by(GradPostgradSample.ts))]
            entry = row.notional_quote / row.tokens
            hit = None
            for m in marks:
                t = seen_at(m)
                if t is None or t <= row.opened_at or t >= due:
                    continue
                price, _ = valued(m, row.open_quote, row.liq_open_usd)
                if price / entry - 1 <= -stop:
                    hit = t
                    break
            if hit is None:
                continue
            out = exit_mark(marks, hit + react)
            if out is None:
                continue
            was = {k: getattr(row, k) for k in SAVED}
            backup.append({"id": str(row.id),
                           **{k: (str(v) if v is not None else None) for k, v in was.items()}})
            price, collapsed = valued(out, row.open_quote, row.liq_open_usd)
            settle(row, price, out.depth, collapsed or "hard_stop",
                   seen_at(out) or hit + react)
            row.exit_signal_at, row.exit_signal = hit + react, "hard_stop"
            row.last_quote, row.marked_at = row.close_quote, row.closed_at
            changed += 1
            before, after = 100 * float(was["net_return"]), 100 * float(row.net_return)
            print(f"{row.symbol or row.mint[:8]:<12} {before:>+8.2f}% -> {after:>+8.2f}%")
        if apply and backup:
            # /app is read-only to the worker's user; the temp dir is not.
            stamp = f"{datetime.now(UTC):%Y%m%d%H%M%S}"
            name = f"{tempfile.gettempdir()}/restop_backup_{stamp}.json"
            with open(name, "w") as fh:  # noqa: ASYNC230 - a one-off script
                json.dump(backup, fh)
            await session.commit()
            print(f"backup: {name}")
        print(f"\n{changed} of {len(rows)} re-priced; "
              f"{'WRITTEN' if apply else 'dry run, nothing written'}")


asyncio.run(main("--apply" in sys.argv))
