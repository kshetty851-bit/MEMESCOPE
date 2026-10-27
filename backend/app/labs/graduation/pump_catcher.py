"""Pump Catcher Lab (Karthik, 2026-10-24: "show this in a separate lab since day 1
... rest everything look similar to karthik lab").

Karthik Lab's own trades, the same coins and rules, with one other exit: sell
at the first price reading at or above +30% (filled at the reading after it,
never at the trigger); a coin still held at 5 minutes and DOWN there (the
book's own 5-minute result below zero) is sold at 5 minutes; anything else at
the first reading 10 minutes after the buy. The 5-minute check (24 Oct, after
a test of 10 variants on 812 coins): +$2,306 vs +$2,042 and 51 big losses vs
60, ahead in both halves of the month. Measured on 807 of the book's coins (1-24 Oct, $50 a trade): +$2,064 vs
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
#: v2 (2026-10-24, Karthik: "yes great add it since day 1"): a coin that is down
#: at 5 minutes is sold then, like Karthik Lab; only coins up at 5 minutes stay
#: for the +30% target or 10 minutes. Every position re-priced under v2.
#: v3 (Karthik, 2026-10-27: "pause user 1 and do both"): priced the way a real
#: wallet sells. The +30% target must be reached AFTER this coin's fees and
#: impact, and every exit gives up `REAL_SLIP` more: USER 1's real sells came in
#: 1-2 points under the lab's and twice missed the target by a hair (Apple x1.278
#: and x1.248 real against x1.32 on paper), then rugged. Re-priced from day 1:
#: +$2,492 -> about +$977 at $50.
KEY = "pumpcatcher:exit:v3"
REAL_SLIP = 0.03
CHECK_S = 300
BATCH = 250
#: Wait this long after the buy before deciding: the 10-minute reading plus slack.
SETTLE = timedelta(seconds=HOLD_S + 120)

_READINGS = text("""
    select ts, price_usd::float8, pair_address pair from grad_postgrad_samples
     where mint = :m and price_usd > 0 and ts >= cast(:a as timestamptz) - interval '2 minutes'
       and ts <= cast(:a as timestamptz) + interval '30 minutes'
    order by ts""")


def decide(path: list[tuple[float, float]], net5: float) -> dict[str, Any]:
    """The exit on one price path. `path` is (seconds after the buy, price / entry
    price), same pool, after the buy. Returns net return, seconds held, how."""
    near5 = [x for s, x in path if 240 <= s <= 420]
    if not near5 or abs(near5[0] - (1 + net5)) > MISMATCH or len(path) < 3:
        return {"net": net5 - REAL_SLIP, "held_s": 300, "gross": None, "how": "5m"}
    cost = (near5[0] - 1) - net5 + REAL_SLIP         # this coin's fees + impact + real slippage
    for i, (s, x) in enumerate(path):
        if s > HOLD_S:
            break
        if s > CHECK_S and net5 < 0:                 # down at 5 minutes: out, like Karthik Lab
            return {"net": net5 - REAL_SLIP, "held_s": 300, "gross": None, "how": "5m-down"}
        if x - 1 - cost >= TARGET:                   # +30% as a real wallet would see it
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
        return {"net": net5 - REAL_SLIP, "held_s": 300, "gross": None, "how": "5m"}
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
