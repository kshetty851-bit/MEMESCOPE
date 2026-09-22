"""Seed BAND_55k_pump_5m from its control's pump-mint trades.

Karthik, 2026-09-22: "build the pump only arm and revise the closed trades".
A pure copy, unlike `seed_quiet_4m.py`: this rule only REFUSES coins, so every
trade it keeps is identical to the control's — same entry, same fill, same
five-minute exit. Nothing is re-priced, so nothing can be re-priced wrongly.

The seeded stretch is still a REPLAY of coins BAND_55k_5m chose, and the
filter was applied to them afterwards. Only rows opened after this ran are
forward evidence.

Safe to run twice: a mint already in the target book is skipped, and so is
anything at or after the book's first live trade.

    docker exec -w /app -e PYTHONPATH=/app memescope-backend-N \
        python scripts/seed_band_pump.py [--apply]
"""

from __future__ import annotations

import asyncio
import sys

from sqlalchemy import select

from app.db.session import SessionFactory
from app.labs.graduation.models import GradPaperPosition

SOURCE = "BAND_55k_5m"
TARGET = "BAND_55k_pump_5m"
SUFFIX = "pump"

#: Every column of the control's row. The filter changes which trades exist,
#: never what a trade was.
CARRIED = ("mint", "symbol", "opened_at", "open_quote", "open_fill", "notional_usd",
           "sol_usd_at_open", "notional_quote", "tokens", "peak_quote", "last_quote",
           "marked_at", "closed_at", "close_quote", "close_fill", "close_reason",
           "pnl_quote", "net_return", "pnl_usd", "liq_open_usd", "liq_close_usd",
           "impact_open", "impact_close", "pool_fee_bps", "graduated_at",
           "exit_signal_at", "exit_signal", "excluded")


async def main(apply: bool) -> None:
    async with SessionFactory() as session:
        done = set(await session.scalars(
            select(GradPaperPosition.mint).where(GradPaperPosition.book == TARGET)))
        live_from = await session.scalar(
            select(GradPaperPosition.opened_at).where(GradPaperPosition.book == TARGET)
            .order_by(GradPaperPosition.opened_at).limit(1))
        rows = (await session.scalars(
            select(GradPaperPosition)
            .where(GradPaperPosition.book == SOURCE,
                   GradPaperPosition.closed_at.is_not(None))
            .order_by(GradPaperPosition.opened_at))).all()

        copied = refused = 0
        for row in rows:
            if not row.mint.endswith(SUFFIX):
                refused += 1
                print(f"  refused {row.symbol or row.mint[:8]:<12} mint ends "
                      f"{row.mint[-6:]}  booked {100 * float(row.net_return):>+7.2f}%")
                continue
            if row.mint in done or (live_from is not None and row.opened_at >= live_from):
                continue
            session.add(GradPaperPosition(
                book=TARGET, **{k: getattr(row, k) for k in CARRIED}))
            copied += 1
        if apply:
            await session.commit()
        print(f"\n{copied} copied, {refused} refused for their launchpad; "
              f"{'WRITTEN' if apply else 'dry run, nothing written'}")


asyncio.run(main("--apply" in sys.argv))
