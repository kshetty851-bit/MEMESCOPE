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
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.market import TokenMarketSnapshot, TradingStatus

#: How long a token must read INACTIVE, with no live print at all, before it is
#: called dead — by the engine, which closes the position, and by this module,
#: which stops quoting a price for it. ONE constant, because they are one
#: question: `service.DEATH_CONFIRMATION_WINDOW` re-exports this.
#:
#: Two minutes, and bounded by TIME rather than by a count of readings. "Two
#: consecutive inactives" never confirms for a token that stops being polled at
#: all, which is how this lab once froze its worst positions at their last
#: healthy price and held them for ever. One inactive print is NOT a death: it
#: cost $337 of live positions in a week — 56 of 806 `dead_zero` exits were
#: written off at $0.00 while the token traded again within ten minutes.
DEATH_CONFIRMATION_WINDOW = timedelta(minutes=2)


async def latest_trading_price(
    session: AsyncSession, mints: Iterable[str]
) -> dict[str, tuple[Decimal, datetime]]:
    """{mint: (price, captured_at)} from the newest TRADING print of each.

    A mint whose only recent rows are INACTIVE is absent from the result
    rather than carrying its last number. Absence is the honest answer — "this
    coin has no current price" — and a caller that renders it as a dash tells
    the reader something true, where a caller handed 0.0001867 would not.

    A price is also absent once the pool has DIED UNDER IT. Skipping inactive
    rows is not enough on its own: a coin whose last trading print was an hour
    ago and has printed inactive ever since still had a trading print, and
    returning it showed three closed `dead_zero` positions at +21.4%, +5.4% and
    +0.9% — each on the same row as an exit reason meaning "written off at
    zero". The mark predated its own close by two to four minutes.

    So the trading print must be the CURRENT state of the pool, not a
    superseded one: it is returned only when nothing has printed more than
    `DEATH_CONFIRMATION_WINDOW` after it. That is the engine's death rule
    exactly, and using it here means the view and the ledger cannot disagree
    about whether a coin is alive.

    It cannot blank a live coin — a live coin's newest print IS the trading
    print, so the gap is zero — and a single spurious inactive reading does not
    blank one either, which is the whole reason the rule is a window and not a
    count.

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
    # The newest print of ANY kind, inactive included. This is what says
    # whether the trading print above is current or superseded.
    newest_any = (
        select(
            TokenMarketSnapshot.mint_address,
            func.max(TokenMarketSnapshot.captured_at).label("at"),
        )
        .where(TokenMarketSnapshot.mint_address.in_(wanted))
        .group_by(TokenMarketSnapshot.mint_address)
        .subquery()
    )
    rows = await session.execute(
        select(ranked.c.mint_address, ranked.c.price_usd, ranked.c.captured_at)
        .join(newest_any, newest_any.c.mint_address == ranked.c.mint_address)
        .where(
            ranked.c.rn == 1,
            # THE SECOND HALF OF THE RULE. See the docstring.
            newest_any.c.at - ranked.c.captured_at <= DEATH_CONFIRMATION_WINDOW,
        )
    )
    return {r.mint_address: (r.price_usd, r.captured_at) for r in rows}
