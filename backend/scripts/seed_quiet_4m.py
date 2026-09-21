"""Seed BASE_75k_quiet_4m from its five-minute twin's closed trades.

Karthik, 2026-09-21: "juz copy the closed trades and assume sold at 4m and
continue". Every closed `BASE_75k_quiet_5m` position is copied into the
four-minute book and re-priced at ITS OWN four-minute mark, through the lab's
own `exit_mark` / `valued` / `settle` — the same arithmetic a live close uses,
so a seeded row and a forward row are priced identically.

What this is, stated plainly so the board is never misread: the seeded stretch
is a REPLAY of coins the five-minute arm chose, not trades the four-minute arm
took by itself. It is hindsight about the exit, never about the entry — the
entries, their quiet readings and their fills are the twin's, unchanged. Only
rows opened after this ran are forward evidence.

Safe to run twice: a (book, mint) already in the four-minute book is skipped,
and so is anything opened at or after the book's first live trade, so a coin
the live arm bought for itself is never overwritten by a copy.

    docker exec -w /app memescope-backend-N python scripts/seed_quiet_4m.py [--apply]
"""

from __future__ import annotations

import asyncio
import sys
from datetime import timedelta

from sqlalchemy import select

from app.db.session import SessionFactory
from app.labs.graduation.models import GradPaperPosition, GradPostgradSample
from app.labs.graduation.tournament import BY_NAME, Mark, exit_mark, seen_at, settle, valued

SOURCE = "BASE_75k_quiet_5m"
TARGET = "BASE_75k_quiet_4m"

#: Copied verbatim: everything the entry decided. The exit fields are the only
#: thing this script computes.
CARRIED = ("mint", "symbol", "opened_at", "open_quote", "open_fill", "notional_usd",
           "sol_usd_at_open", "notional_quote", "tokens", "liq_open_usd",
           "impact_open", "pool_fee_bps", "graduated_at", "excluded")


async def main(apply: bool) -> None:
    hold = timedelta(minutes=BY_NAME[TARGET].hold)
    async with SessionFactory() as session:
        done = set(await session.scalars(
            select(GradPaperPosition.mint).where(GradPaperPosition.book == TARGET)))
        # A coin the live four-minute arm has already bought for itself marks
        # the end of what may be seeded: nothing at or after it is copied.
        live_from = await session.scalar(
            select(GradPaperPosition.opened_at).where(GradPaperPosition.book == TARGET)
            .order_by(GradPaperPosition.opened_at).limit(1))
        rows = (await session.scalars(
            select(GradPaperPosition)
            .where(GradPaperPosition.book == SOURCE,
                   GradPaperPosition.closed_at.is_not(None))
            .order_by(GradPaperPosition.opened_at))).all()

        made = kept_close = 0
        for row in rows:
            if row.mint in done or (live_from is not None and row.opened_at >= live_from):
                continue
            marks = [Mark(s.price_native, s.liquidity_usd, s.ts, s.source)
                     for s in await session.scalars(
                         select(GradPostgradSample)
                         .where(GradPostgradSample.mint == row.mint,
                                GradPostgradSample.ts >= row.opened_at,
                                GradPostgradSample.ts <= row.closed_at + timedelta(minutes=2),
                                GradPostgradSample.price_native.is_not(None))
                         .order_by(GradPostgradSample.ts))]
            copy = GradPaperPosition(book=TARGET, **{k: getattr(row, k) for k in CARRIED})
            due = row.opened_at + hold
            mark = exit_mark(marks, due)
            if mark is None:
                # Nothing describes the market at four minutes. The twin's own
                # close is the only honest price left, so the row keeps it and
                # says so rather than inventing one.
                copy.peak_quote = row.peak_quote
                settle(copy, row.close_quote, row.liq_close_usd,
                       f"{row.close_reason}_unmarked_at_4m", row.closed_at)
                kept_close += 1
            else:
                seen = [m for m in marks if (t := seen_at(m)) is not None and t <= due]
                copy.peak_quote = max([m.price for m in seen] + [row.open_quote])
                price, collapsed = valued(mark, row.open_quote, row.liq_open_usd)
                settle(copy, price, mark.depth, collapsed or "max_hold",
                       seen_at(mark) or due)
            copy.last_quote, copy.marked_at = copy.close_quote, copy.closed_at
            session.add(copy)
            made += 1
            print(f"{row.symbol or row.mint[:8]:<10} 5m {100 * float(row.net_return):>+7.2f}%"
                  f"  ->  4m {100 * float(copy.net_return):>+7.2f}%  {copy.close_reason}")
        if apply:
            await session.commit()
        wrote = "WRITTEN" if apply else "dry run, nothing written"
        print(f"\n{made} copied ({kept_close} with no four-minute mark), "
              f"{len(rows) - made} skipped; {wrote}")


asyncio.run(main("--apply" in sys.argv))
