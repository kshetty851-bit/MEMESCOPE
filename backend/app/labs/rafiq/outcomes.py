"""Forward outcomes for every candidate, entered or refused.

## What this measures, and why it is not a backtest

For each recorded decision, three horizons after it: the best the token
reached, where it ended, and whether its pool was gone. Nothing here simulates
a trade and nothing applies an exit rule — `max_return` is a ceiling nobody
could have captured. It bounds what was available to any rule, which is the
only honest way to ask "would refusing this token have been right".

## Where the prices come from

`token_market_snapshots` and nothing else. The platform already prices every
admitted token about every sixteen seconds, so this calls no external
endpoint, cannot be rate-limited, and costs no quota. DexScreener and
GeckoTerminal were the alternative and are strictly worse here: they would
return the token's state *now* rather than at +1h, which is the wrong
measurement for every row older than the newest.

## Point-in-time

Every window is strictly `(decided_at, decided_at + horizon]`, so the decision
instant itself is excluded and the return is entirely forward. Rows are only
attempted once their horizon has actually closed — a +24h figure computed at
+3h would be a 3-hour return wearing a 24-hour label.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.labs.rafiq.feed import RafiqFeed
from app.labs.rafiq.models import RafiqCandidate

logger = get_logger(__name__)

#: The horizons, and the column suffix each one writes.
HORIZONS: tuple[tuple[str, timedelta], ...] = (
    ("1h", timedelta(hours=1)),
    ("6h", timedelta(hours=6)),
    ("24h", timedelta(hours=24)),
)

#: Below this, the pool is gone for practical purposes — the level Rafiq's
#: brief names, and the level at which this platform's own closed trades
#: return approximately nothing regardless of the quoted price.
DEAD_LIQUIDITY_USD = Decimal(1_000)

#: How many rows one pass will settle. A cap, not a target: the query is
#: indexed on `decided_at` and this keeps a backlog from turning one beat into
#: a long transaction against a table the trading tick also writes.
BATCH = 200


async def record(session: AsyncSession, *, now: datetime | None = None,
                 batch: int = BATCH) -> dict[str, Any]:
    """Fill in every horizon that has closed and has not been attempted."""
    moment = (now or datetime.now(UTC)).astimezone(UTC)
    written: dict[str, int] = {}

    for label, span in HORIZONS:
        rows = list((await session.execute(
            select(RafiqCandidate)
            .where(RafiqCandidate.decided_at <= moment - span,
                   RafiqCandidate.price_usd.is_not(None),
                   # `outcomes_attempted` is the bookkeeping, not the value
                   # columns: a token that printed nothing in the window has a
                   # legitimately null return and must not be retried for
                   # ever. The `is_(None)` half is not redundant — JSONB `?`
                   # against a NULL column yields NULL, so without it every
                   # row that has never been attempted is filtered out and
                   # nothing is ever recorded.
                   or_(RafiqCandidate.outcomes_attempted.is_(None),
                       ~RafiqCandidate.outcomes_attempted.has_key(label)))
            .order_by(RafiqCandidate.decided_at)
            .limit(batch)
        )).scalars())

        feed = RafiqFeed(session)
        for row in rows:
            await _settle(feed, row, label=label, span=span)
        # Flushed per horizon so the next horizon's selection sees this one's
        # bookkeeping, and so a caller that reads a row back before committing
        # does not read a stale one.
        await session.flush()
        written[label] = len(rows)

    return {"recorded": written}


async def _settle(feed: RafiqFeed, row: RafiqCandidate, *, label: str,
                  span: timedelta) -> None:
    window = await feed.forward_window(mint=row.mint_address,
                                       after=row.decided_at,
                                       until=row.decided_at + span)

    attempted = dict(row.outcomes_attempted or {})
    if not window:
        # Attempted and empty. The null stays, and stays explicable.
        attempted[label] = None
        row.outcomes_attempted = attempted
        return

    prices = [r.price_usd for r in window if r.price_usd and r.price_usd > 0]
    last = window[-1]
    base = row.price_usd
    if prices and base and base > 0:
        setattr(row, f"max_return_{label}", max(prices) / base - 1)
    if last.price_usd is not None and base and base > 0:
        setattr(row, f"final_return_{label}", last.price_usd / base - 1)
    if last.liquidity_usd is not None:
        setattr(row, f"dead_{label}", last.liquidity_usd < DEAD_LIQUIDITY_USD)

    attempted[label] = last.captured_at.isoformat()
    row.outcomes_attempted = attempted


async def coverage(session: AsyncSession) -> dict[str, Any]:
    """Non-null rate per instrumented field. What a read-out needs to say
    whether the instrument is working, rather than whether it is wired."""
    total = (await session.execute(
        select(func.count()).select_from(RafiqCandidate)
    )).scalar_one()
    if not total:
        return {"candidates": 0}

    counted = (await session.execute(select(
        func.count(RafiqCandidate.top10_holder_pct),
        func.count(RafiqCandidate.lp_status),
        func.count(RafiqCandidate.safety_status),
        func.count(RafiqCandidate.liquidity_usd),
        func.count(RafiqCandidate.max_return_1h),
    ))).one()
    fields = ("top10_holder_pct", "lp_status", "safety_status",
              "liquidity_usd", "max_return_1h")
    return {"candidates": total,
            "non_null_pct": {f: round(c * 100 / total, 1)
                             for f, c in zip(fields, counted, strict=True)}}
