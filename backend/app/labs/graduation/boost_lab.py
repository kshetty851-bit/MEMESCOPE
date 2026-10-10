"""Boost Lab (Karthik, 2026-10-10: "yes set up both in different lab").

Does paying DexScreener pay? A paper book of every coin a graduation book
bought that ALREADY had a paid DexScreener profile, or active boosts, when it
was bought, at any pool size, sold `HOLD_MINUTES` after. $50 on $250 (5x),
several at once while the cash allows.

Why 4 minutes: on the 28 such coins 1-10 Oct, 4m made the most (+$268 at $50
on $500) and past 5m it fell apart (7 rugs of 28 by 10m). Chosen after
looking, on 28 coins, three of which carried it (+$11 without them): this
book is the test, not the proof.

The trades are the books' own entries re-priced at `HOLD_MINUTES` with the
lab's exit maths (`exit_mark`, `valued`, `settle`), so no new arm buys
anything. Profiles are read from `token_market_snapshots.is_verified`;
boosts from `boosts_active`, recorded only from `BOOSTS_SINCE`. The minute
table beside it re-prices the same coins at other holds. Paper only.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.labs.graduation import api, config
from app.labs.graduation import pool_lab as pl
from app.labs.graduation.models import GradPaperPosition, GradPostgradSample
from app.labs.graduation.tournament import Mark, exit_mark, seen_at, settle, valued

KEY = "graduation:boost_lab"
FROM = pl.FROM                                   # backtest from 1 Oct, 00:00 Dubai
START = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)  # live from 16:00 Dubai
BOOSTS_SINCE = START
HOLD_MINUTES = 4
MINUTES = (2, 3, 4, 5, 6, 8, 10)
TICKET = 50.0
CAPITAL = 250.0

_CARRIED = ("mint", "symbol", "opened_at", "open_quote", "open_fill", "notional_usd",
            "sol_usd_at_open", "notional_quote", "tokens", "liq_open_usd", "impact_open",
            "pool_fee_bps", "graduated_at", "excluded")

#: Each entry's last snapshot before the buy: paid profile, active boosts.
_PAID_SQL = text("""
    select x.mint, s.is_verified, s.boosts_active
    from unnest(cast(:m as varchar[]), cast(:t as timestamptz[])) as x(mint, at)
    cross join lateral (
        select is_verified, boosts_active from token_market_snapshots
        where mint_address = x.mint and captured_at <= x.at
        order by captured_at desc limit 1) s
    where s.is_verified or coalesce(s.boosts_active, 0) > 0
""")


async def _marks(db: AsyncSession, row: Any) -> list[Mark]:
    return [Mark(s.price_native, s.liquidity_usd, s.ts, s.source) for s in await db.scalars(
        select(GradPostgradSample).where(
            GradPostgradSample.mint == row.mint, GradPostgradSample.ts >= row.opened_at,
            GradPostgradSample.ts <= row.opened_at + timedelta(minutes=max(MINUTES) + 2),
            GradPostgradSample.price_native.is_not(None))
        .order_by(GradPostgradSample.ts))]


def _sold_at(row: Any, marks: list[Mark], minutes: int) -> GradPaperPosition | None:
    """The entry re-priced as if sold `minutes` after it; None if unpriced yet."""
    due = row.opened_at + timedelta(minutes=minutes)
    mark = exit_mark(marks, due)
    if mark is None:
        return None
    copy = GradPaperPosition(book="BOOST", **{k: getattr(row, k) for k in _CARRIED})
    seen = [m.price for m in marks if (t := seen_at(m)) is not None and t <= due]
    copy.peak_quote = max([*seen, row.open_quote])
    price, collapsed = valued(mark, row.open_quote, row.liq_open_usd)
    settle(copy, price, mark.depth, collapsed or "max_hold", seen_at(mark) or due)
    return copy


async def build(db: AsyncSession) -> dict[str, Any]:
    cents = Decimal("0.01")
    sol = await db.scalar(
        select(GradPostgradSample.price_usd / GradPostgradSample.price_native)
        .where(GradPostgradSample.price_usd > 0, GradPostgradSample.price_native > 0)
        .order_by(GradPostgradSample.ts.desc()).limit(1))
    books = tuple((await db.execute(text(
        "select distinct book from grad_paper_positions where opened_at >= :f"),
        {"f": FROM})).scalars())
    rows = await api._pool_rows(db, books, FROM, 0, skip_repeat=False)
    paid = {m: (bool(v), b) for m, v, b in (await db.execute(_PAID_SQL, {
        "m": [r.mint for r in rows], "t": [r.opened_at for r in rows]})).all()} if rows else {}
    picked = [r for r in rows if r.mint in paid]
    sold: dict[int, list[GradPaperPosition]] = {m: [] for m in MINUTES}
    for row in picked:
        marks = await _marks(db, row)
        for minutes in MINUTES:
            if (c := _sold_at(row, marks, minutes)) is not None:
                sold[minutes].append(c)
    book = sorted(sold[HOLD_MINUTES], key=api._opened_order)
    walk = api._funded_walk(
        [(c.opened_at, c.closed_at, float(c.net_return), float(c.impact_open or 0),
          float(c.impact_close or 0)) for c in book], sol, ticket=TICKET, start=CAPITAL)
    took = [(c, m) for c, m in zip(book, walk.pnl, strict=True) if m is not None]
    rug = float(config.OPERATOR_RUG_MOVE)
    first = took[0][0].opened_at if took else None
    return {
        "started_at": START, "backtest_from": FROM, "boosts_since": BOOSTS_SINCE,
        "computed_at": datetime.now(UTC), "hold_minutes": HOLD_MINUTES,
        "ticket_usd": TICKET, "capital_usd": CAPITAL,
        "balance_usd": Decimal(str(walk.cash)).quantize(cents),
        "coins_seen": len(rows), "coins_picked": len(picked),
        "boosted_coins": sum(1 for _, b in paid.values() if (b or 0) > 0),
        # Days from the first trade: no coin had a profile on record before
        # 8 Oct, so days from 1 Oct would open on a week of empty boxes.
        "first_trade_at": first,
        "days": api._karthik_days(took, first or FROM, CAPITAL, cents),
        "closed": [{"symbol": c.symbol, "mint": c.mint, "opened_at": c.opened_at,
                    "closed_at": c.closed_at, "pool_usd": c.liq_open_usd,
                    "pct": Decimal(str(100 * float(c.net_return))).quantize(cents),
                    "pnl_usd": Decimal(str(m)).quantize(cents),
                    "rugged": float(c.net_return) <= rug,
                    "profile": paid[c.mint][0], "boosts": paid[c.mint][1],
                    "live": c.opened_at >= START}
                   for c, m in reversed(took)],
        "minutes": [{"minutes": m, "current": m == HOLD_MINUTES, "trades": len(sold[m]),
                     **{k: v for k, v in api._karthik_line(
                         sorted(sold[m], key=api._opened_order), sol, size=TICKET,
                         capital=CAPITAL, cents=cents).items()
                        if k in ("pnl_usd", "rugs", "wins", "lowest_usd")}}
                    for m in MINUTES],
    }
