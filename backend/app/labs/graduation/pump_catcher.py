"""Pump Catcher Lab (Karthik, 2026-10-24: "show this in a separate lab since day 1
... rest everything look similar to karthik lab").

Karthik Lab's own trades, the same coins and rules, with one other exit: sell
at the first price reading at or above +30% (filled at the reading after it,
never at the trigger), otherwise at the first reading 10 minutes after the
buy. Measured on 807 of the book's coins (1-24 Oct, $50 a trade): +$2,064 vs
+$1,529 selling at 5 minutes, ahead in both halves of the month, but 58 big
losses against 22 -- chosen after looking at about 55 exits, so its own new
trades are the test.

Each position is priced once, from DexScreener readings of the SAME pool the
book bought in, and stored in Redis; `refresh` (every 5 minutes) prices the
ones that are old enough. A position whose readings disagree with the book's
own 5-minute result by more than `MISMATCH` (the feed switched pools, or a gap)
keeps the book's 5-minute result.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select, text

TARGET, HOLD_S, MISMATCH = 0.30, 600, 0.35
#: Its own starting balance (Karthik, 2026-10-24: "500$ looks okay, can we change
#: that since day 1 and all the tables too"); Karthik Lab stays at $300.
CAPITAL = Decimal(500)
KEY = "pumpcatcher:exit:v1"
BATCH = 250
#: Wait this long after the buy before deciding: the 10-minute reading plus slack.
SETTLE = timedelta(seconds=HOLD_S + 120)

_READINGS = text("""
    select ts, price_usd::float8, pair from (
      select ts, price_usd, pair_address pair from grad_postgrad_samples
       where mint = :m and price_usd > 0 and ts >= cast(:a as timestamptz) - interval '2 minutes'
         and ts <= cast(:a as timestamptz) + interval '30 minutes'
      union all
      select ts, price_usd, pair from longwatch_readings
       where mint = :m and price_usd > 0 and ts >= cast(:a as timestamptz) - interval '2 minutes'
         and ts <= cast(:a as timestamptz) + interval '30 minutes') x
    order by ts""")


def decide(path: list[tuple[float, float]], net5: float) -> dict[str, Any]:
    """The exit on one price path. `path` is (seconds after the buy, price / entry
    price), same pool, after the buy. Returns net return, seconds held, how."""
    near5 = [x for s, x in path if 240 <= s <= 420]
    if not near5 or abs(near5[0] - (1 + net5)) > MISMATCH or len(path) < 3:
        return {"net": net5, "held_s": 300, "gross": None, "how": "5m"}
    cost = (near5[0] - 1) - net5                     # this coin's fees + impact
    for i, (s, x) in enumerate(path):
        if s > HOLD_S:
            break
        if x >= 1 + TARGET:
            ns, nx = path[i + 1] if i + 1 < len(path) else (s, x)
            return {"net": nx - 1 - cost, "held_s": ns, "gross": nx, "how": "target"}
    for s, x in path:
        if s >= HOLD_S:
            return {"net": x - 1 - cost, "held_s": s, "gross": x, "how": "10m"}
    s, x = path[-1]
    return {"net": x - 1 - cost, "held_s": s, "gross": x, "how": "last"}


async def price(session, row) -> dict[str, Any]:
    rows = (await session.execute(_READINGS, {"m": row.mint, "a": row.opened_at})).all()
    pre = [(ts, p, pa) for ts, p, pa in rows if ts <= row.opened_at and pa]
    net5 = float(row.net_return)
    if not pre:
        return {"net": net5, "held_s": 300, "gross": None, "how": "5m"}
    pair, p0 = pre[-1][2], pre[-1][1]
    path = [((ts - row.opened_at).total_seconds(), p / p0)
            for ts, p, pa in rows if ts > row.opened_at and pa == pair]
    return decide(path, net5)


async def refresh(session, redis, now: datetime | None = None) -> dict[str, int]:
    """Price up to `BATCH` of the book's positions that are old enough and unpriced."""
    from app.labs.graduation import api, config
    from app.labs.graduation.models import GradPaperPosition

    now = now or datetime.now(UTC)
    spec = next(s for s in config.FRESH_BOOKS if s.book == "KARTHIK_QUIET_5M")
    done = set(await redis.hkeys(KEY))
    rows = (await session.scalars(
        select(GradPaperPosition).where(
            GradPaperPosition.book.in_(("KARTHIK_QUIET_5M", *api.KARTHIK_BAND_BOOKS)),
            GradPaperPosition.opened_at >= spec.start,
            GradPaperPosition.opened_at <= now - SETTLE,
            GradPaperPosition.closed_at.is_not(None),
            GradPaperPosition.net_return.is_not(None),
            GradPaperPosition.excluded.is_(None))
        .order_by(GradPaperPosition.opened_at))).all()
    todo = [r for r in rows if str(r.id) not in done and str(r.id).encode() not in done][:BATCH]
    for r in todo:
        await redis.hset(KEY, str(r.id), json.dumps(await price(session, r)))
    return {"priced": len(todo), "left": max(0, len(rows) - len(done) - len(todo))}


async def exits(redis) -> dict[str, dict[str, Any]]:
    raw = await redis.hgetall(KEY)
    return {(k.decode() if isinstance(k, bytes) else k): json.loads(v) for k, v in raw.items()}


class Repriced:
    """A position seen through the Pump Catcher's exit: its own net return and
    close time, everything else (entry, pool, symbol, impacts) the book's."""

    def __init__(self, row, ex: dict[str, Any]):
        self._row = row
        self.net_return = Decimal(str(round(ex["net"], 6)))      # the book's own type
        self.closed_at = row.opened_at + timedelta(seconds=ex["held_s"])
        self.close_quote = (row.open_quote * Decimal(str(ex["gross"]))
                            if ex.get("gross") and row.open_quote else row.close_quote)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._row, name)


def reprice(rows, priced: dict[str, dict[str, Any]]) -> list:
    """The rows that have been priced, re-priced; the rest are still settling."""
    return [Repriced(r, priced[str(r.id)]) for r in rows if str(r.id) in priced]
