"""Boost Lab what-if (Karthik, 2026-10-18): "check revised profit if we entered
the trade at 8 min and exited at 4m, 6m, 8m and 10m".

The same coins Boost Lab picks today, every skip rule applied at the book's
real buy, but bought `ENTRY_MIN` minutes LATER and held 4/6/8/10 minutes from
that later buy. The later buy is priced off the first mark at or after it, at
that moment's pool depth, with the lab's own buy and exit maths, then walked
through the same $50-on-$250 cash walk with the 3-loss cooldown. A coin whose
pool had already collapsed by the later buy is not bought (nobody would buy a
drained pool) and is counted. Paper only, nothing is written beyond what
`boost_lab.build` already keeps.

    docker compose exec -T backend python -m scripts.boost_lab_late_entry
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any

from app.db.session import SessionFactory
from app.labs.graduation import boost_lab as bl
from app.labs.graduation import config
from app.labs.graduation.backtest import amm_buy, amm_impact
from app.labs.graduation.models import GradPaperPosition
from app.labs.graduation.paper import _P, _Q, costs
from app.labs.graduation.tournament import Mark, exit_mark, seen_at, settle, valued

ENTRY_MIN = 8
HOLDS = (4, 6, 8, 10)
dead_at_entry: set[str] = set()


def _late_sold_at(row: Any, marks: list[Mark], minutes: int) -> GradPaperPosition | None:
    entry = exit_mark(marks, row.opened_at + timedelta(minutes=ENTRY_MIN))
    if entry is None or (at := seen_at(entry)) is None:
        return None
    if valued(entry, row.open_quote, row.liq_open_usd)[1] is not None:
        dead_at_entry.add(row.mint)
        return None
    copy = GradPaperPosition(book="BOOST", **{k: getattr(row, k) for k in bl._CARRIED})
    price, depth = entry.price, entry.depth
    fee_bps = config.pool_fee_bps(price)
    leg = costs(copy.notional_quote, pool_fee_bps=fee_bps)
    fill = amm_buy(price, order_usd=copy.notional_usd, liquidity_usd=depth,
                   fee_fraction=leg.fee_fraction) or leg.buy_price(price)
    impact = amm_impact(copy.notional_usd, depth)
    copy.opened_at, copy.liq_open_usd = at, depth
    copy.open_quote, copy.pool_fee_bps = price.quantize(_P), fee_bps
    copy.open_fill = fill.quantize(_P)
    copy.tokens = (copy.notional_quote / fill).quantize(_Q)
    copy.impact_open = None if impact is None else impact.quantize(_P)
    due = at + timedelta(minutes=minutes)
    after = [m for m in marks if (t := seen_at(m)) is not None and t >= at]
    mark = exit_mark(after, due)
    if mark is None:
        return None
    seen = [m.price for m in after if (t := seen_at(m)) is not None and t <= due]
    copy.peak_quote = max([*seen, copy.open_quote])
    quote, collapsed = valued(mark, copy.open_quote, copy.liq_open_usd)
    settle(copy, quote, mark.depth, collapsed or "max_hold", seen_at(mark) or due)
    return copy


async def main() -> None:
    # The lab's own run with only the entry moved: its marks must reach the
    # later buy plus the longest hold.
    bl.MINUTES, bl.HOLD_MINUTES = HOLDS, HOLDS[0]
    bl._sold_at = _late_sold_at
    base_marks = bl._marks

    async def marks(db: Any, row: Any) -> list[Mark]:
        bl.MINUTES = (ENTRY_MIN + max(HOLDS),)
        try:
            return await base_marks(db, row)
        finally:
            bl.MINUTES = HOLDS

    bl._marks = marks
    async with SessionFactory() as db:
        out = await bl.build(db)
    print(f"Boost Lab, bought {ENTRY_MIN}m after the book's buy, "
          f"${bl.TICKET:.0f} tickets on ${bl.CAPITAL:.0f}; coins picked {out['coins_picked']}, "
          f"already drained at the later buy {len(dead_at_entry)}")
    print(f"{'exit':>6} {'trades':>7} {'wins':>5} {'rugs':>5} {'pnl $':>10} {'lowest $':>10}")
    for line in out["minutes"]:
        print(f"{'+' + str(line['minutes']) + 'm':>6} {line['trades']:>7} {line['wins']:>5} "
              f"{line['rugs']:>5} {line['pnl_usd']:>10} {line['lowest_usd']:>10}")


if __name__ == "__main__":
    asyncio.run(main())
