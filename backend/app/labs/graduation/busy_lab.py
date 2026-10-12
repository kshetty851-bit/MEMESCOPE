"""BUSY POOL LAB (Karthik, 2026-10-12: "set up the busy pool as a separate lab
- 10k pool starting today with 200$ and 20$ per trade").

The $10k book refuses every pool that already had 100+ trades when it would
buy; 4,788 such coins were skipped 5-12 Oct and nothing recorded how they did.
`POOL_10K_BUSY_3M` buys exactly those (pool $10k+, not $25k-$50k, within two
minutes of graduating, out at 3 minutes or 10% under the price paid) and this
lays its trades out at $20 a trade on $200. Paper only; no real wallet follows
it. Its page rules are deliberately none: it measures busy pools as they come.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.labs.graduation import api, config
from app.labs.graduation.models import GradPaperPosition, GradPostgradSample

KEY = "graduation:busy_lab"
BOOK = "POOL_10K_BUSY_3M"
START = datetime(2026, 10, 12, 8, 0, tzinfo=UTC)   # 12:00 Dubai, 12 Oct
TICKET = 20.0
CAPITAL = 200.0


async def build(db: AsyncSession) -> dict[str, Any]:
    cents = Decimal("0.01")
    sol = await db.scalar(
        select(GradPostgradSample.price_usd / GradPostgradSample.price_native)
        .where(GradPostgradSample.price_usd > 0, GradPostgradSample.price_native > 0)
        .order_by(GradPostgradSample.ts.desc()).limit(1))
    rows = sorted(await api._pool_rows(db, (BOOK,), START, 10_000, skip_repeat=False),
                  key=api._opened_order)
    walk = api._funded_walk(
        [(r.opened_at, r.closed_at, float(r.net_return), float(r.impact_open or 0),
          float(r.impact_close or 0)) for r in rows], sol, ticket=TICKET, start=CAPITAL)
    took = [(r, m) for r, m in zip(rows, walk.pnl, strict=True) if m is not None]
    held = (await db.scalars(
        select(GradPaperPosition)
        .where(GradPaperPosition.book == BOOK, GradPaperPosition.closed_at.is_(None),
               GradPaperPosition.excluded.is_(None), GradPaperPosition.opened_at >= START)
        .order_by(GradPaperPosition.opened_at.desc()))).all()
    rug = float(config.OPERATOR_RUG_MOVE)
    first = took[0][0].opened_at if took else None
    return {
        "started_at": START, "computed_at": datetime.now(UTC), "first_trade_at": first,
        "ticket_usd": TICKET, "capital_usd": CAPITAL, "hold_minutes": 3, "stop_pct": 10,
        "busy_min_txs": config.QUIET_MAX_POOL_TXS,
        "balance_usd": Decimal(str(walk.cash)).quantize(cents),
        "days": api._karthik_days(took, first or START, CAPITAL, cents),
        "closed": [{"symbol": r.symbol, "mint": r.mint, "opened_at": r.opened_at,
                    "closed_at": r.closed_at, "pool_usd": r.liq_open_usd, **api._mcaps(r),
                    "pct": Decimal(str(100 * float(r.net_return))).quantize(cents),
                    "pnl_usd": Decimal(str(m)).quantize(cents),
                    "rugged": float(r.net_return) <= rug}
                   for r, m in reversed(took)],
        "open": [{"symbol": p.symbol, "mint": p.mint, "opened_at": p.opened_at,
                  "pool_usd": p.liq_open_usd} for p in held],
    }
