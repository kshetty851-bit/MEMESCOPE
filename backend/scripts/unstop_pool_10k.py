"""Re-price the Pool Lab's $10k book WITHOUT its 10% stop, as if from day 1.

Karthik, 2026-10-12: "apply it to 10k pool since day 1" (no stop-loss, out at
three minutes). Every closed POOL_10K_QUIET_3M trade the stop closed is priced
again at its three-minute exit the way `_manage` times one: the first mark that
describes the market at or after the exit was due (`exit_mark`), sold through
the book's own `valued` / `settle`. A trade without a mark there is left as it
was and listed. The reverse of `restop_pool_10k.py` (2026-10-07), whose replay
read back-dated DexScreener marks.

The rows it changes are written first to a JSON backup, so the stopped closes
can be put back.

    docker exec -w /app memescope-worker-1 python scripts/unstop_pool_10k.py [--apply]
"""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select

from app.db.session import SessionFactory
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
         "pnl_usd", "liq_close_usd", "impact_close", "exit_signal_at", "exit_signal",
         "last_quote", "marked_at")


async def main(apply: bool) -> None:
    assert BY_NAME[BOOK].stop is None, "the arm still has its stop: deploy first"
    async with SessionFactory() as session:
        rows = (await session.scalars(
            select(GradPaperPosition)
            .where(GradPaperPosition.book == BOOK, GradPaperPosition.closed_at.is_not(None),
                   or_(GradPaperPosition.exit_signal_at.is_not(None),
                       GradPaperPosition.close_reason == "hard_stop"))
            .order_by(GradPaperPosition.opened_at))).all()
        backup, changed, unpriced = [], 0, []
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
            out = exit_mark(marks, due)
            if out is None:
                unpriced.append(row.symbol or row.mint[:8])
                continue
            was = {k: getattr(row, k) for k in SAVED}
            backup.append({"id": str(row.id),
                           **{k: (str(v) if v is not None else None) for k, v in was.items()}})
            price, collapsed = valued(out, row.open_quote, row.liq_open_usd)
            settle(row, price, out.depth, collapsed or "max_hold", seen_at(out) or due)
            row.exit_signal_at, row.exit_signal = None, None
            row.last_quote, row.marked_at = row.close_quote, row.closed_at
            changed += 1
            before, after = 100 * float(was["net_return"]), 100 * float(row.net_return)
            print(f"{row.symbol or row.mint[:8]:<12} {before:>+8.2f}% -> {after:>+8.2f}%")
        if apply and backup:
            stamp = f"{datetime.now(UTC):%Y%m%d%H%M%S}"
            name = f"{tempfile.gettempdir()}/unstop_backup_{stamp}.json"
            with open(name, "w") as fh:  # noqa: ASYNC230 - a one-off script
                json.dump(backup, fh)
            await session.commit()
            print(f"backup: {name}")
        print(f"\n{changed} of {len(rows)} re-priced; {len(unpriced)} left as they were "
              f"(no mark at three minutes): {', '.join(unpriced[:20])}; "
              f"{'WRITTEN' if apply else 'dry run, nothing written'}")


asyncio.run(main("--apply" in sys.argv))
