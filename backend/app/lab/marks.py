"""The latest price a coin can actually be said to have.

ONE function, because the rule it encodes was learned expensively and then
forgotten inside a day.

## The rule

An INACTIVE snapshot carries a `price_usd` and that number is not a price.
When a pool dies the provider keeps emitting rows, and what it emits is noise:
measured on 3rPtdowXdc on 2026-09-09, a coin trading at 0.00007 collapsed 95%
to 0.00000366 and went inactive, then reported 0.0001867 — FIFTY-ONE TIMES
higher — while still inactive, with nothing trading. A view that trusted the
newest row showed a position correctly written off as dead as though it were
up 174%.

The payoff research hit the same thing from the other direction and it cost a
whole population: dead coins marked at their last observed price, which is
never zero, turned -1.19% into +0.49%. The engine's own marking has always
guarded it (`live_print`, and the INACTIVE branch in `_mark`). The trades view
did not, because it was written later by someone who knew the rule and did not
apply it.

## Why this is a module and not three lines in a query

So that "read the latest price" has exactly one implementation and a test can
forbid the others. `test_lab_isolation` asserts that nothing outside this file
selects `TokenMarketSnapshot.price_usd` for valuation — the next person to
need a current price will find this function, and the rule with it, instead of
writing the obvious wrong thing again.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.market import TokenMarketSnapshot, TradingStatus


async def latest_trading_price(
    session: AsyncSession, mints: Iterable[str]
) -> dict[str, tuple[Decimal, datetime]]:
    """{mint: (price, captured_at)} from the newest TRADING print of each.

    A mint whose only recent rows are INACTIVE is absent from the result
    rather than carrying its last number. Absence is the honest answer — "this
    coin has no current price" — and a caller that renders it as a dash tells
    the reader something true, where a caller handed 0.0001867 would not.

    One windowed query for the whole set, not a subquery per row: the trades
    view asks about every position it lists.
    """
    wanted = list({m for m in mints if m})
    if not wanted:
        return {}

    ranked = (
        select(
            TokenMarketSnapshot.mint_address,
            TokenMarketSnapshot.price_usd,
            TokenMarketSnapshot.captured_at,
            func.row_number()
            .over(
                partition_by=TokenMarketSnapshot.mint_address,
                order_by=TokenMarketSnapshot.captured_at.desc(),
            )
            .label("rn"),
        )
        .where(
            TokenMarketSnapshot.mint_address.in_(wanted),
            TokenMarketSnapshot.price_usd.is_not(None),
            TokenMarketSnapshot.price_usd > 0,
            # THE RULE. See the module docstring before relaxing this.
            TokenMarketSnapshot.trading_status != TradingStatus.INACTIVE,
        )
        .subquery()
    )
    rows = await session.execute(
        select(ranked.c.mint_address, ranked.c.price_usd, ranked.c.captured_at)
        .where(ranked.c.rn == 1)
    )
    return {r.mint_address: (r.price_usd, r.captured_at) for r in rows}
