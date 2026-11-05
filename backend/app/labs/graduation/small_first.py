"""Small First Buy test (Karthik, 2026-11-05: "yes add it since day 1 for
november and revise it"). Paper only; nothing real trades on it.

The rule a search of 738 on the first-minute recorder found (28 Oct - 4 Nov,
picked on 28-31 Oct, checked on 1-4 Nov and against random coins): buy 45
seconds after graduating when the pool's SOL side 10 seconds in is under 110
SOL and the name has 1-5 letters; sell at the first reading +30% up after fees,
else at 5 minutes. Replayed 25 Oct - 4 Nov: +$154 on 684 trades at $5 -- found
after looking, so its days from 5 Nov on are the test.

Priced from `grad_first_minute` (on-chain, every change) exactly as the search
priced it: fees by pool tier plus Jupiter's cut plus `SLIP` each way, readings
forward-filled (no change = no trade). `refresh` (every 5 minutes) walks the
graduations in time order from `START` and stores each trade in Redis.
"""

from __future__ import annotations

import bisect
import json
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from fastapi import APIRouter
from sqlalchemy import text

from app.labs.graduation import config

START = datetime(2026, 10, 31, 20, tzinfo=UTC)       # 1 Nov, Dubai
ENTRY_S, HOLD_S, TARGET = 45, 300, 0.30
FIRST_MAX_SOL, POOL_MIN_SOL, NAME_MAX = 110.0, 60.0, 5
SLIP, TICKET = 0.005, 5.0
KEY, CURSOR = "smallfirst:v1", "smallfirst:v1:cursor"
CHUNK = timedelta(hours=12)
#: After the hold plus the recorder's slack, a graduation is final.
SETTLE = timedelta(seconds=ENTRY_S + HOLD_S + 120)

_ROWS = text("""
    select mint, extract(epoch from ts - migrated_at)::float8 age, price_native::float8, quote_reserve::float8,
           migrated_at
      from grad_first_minute
     where sol_quoted and migrated_at >= :a and migrated_at < :b
       and ts >= :a and ts < cast(:b as timestamptz) + interval '400 seconds'
       and ts - migrated_at <= interval '360 seconds'
     order by mint, ts""")


def _fee(p: float) -> float:
    return (config.pool_fee_bps(Decimal(str(p))) + config.ROUTER_FEE_BPS) / 1e4


def decide(path: list[tuple[float, float, float]], symbol: str | None) -> dict[str, Any] | None:
    """One graduation's (seconds after graduating, SOL price, SOL side) readings.
    None when the rule does not buy it."""
    if not path or path[0][0] > 10:
        return None
    ages = [a for a, _, _ in path]
    at = lambda t: path[max(0, bisect.bisect_right(ages, t) - 1)]  # noqa: E731
    name = (symbol or "").strip()
    first, entry = at(10), at(ENTRY_S)
    if not (0 < len(name) <= NAME_MAX and first[2] < FIRST_MAX_SOL and entry[2] >= POOL_MIN_SOL):
        return None
    buy = entry[1] * (1 + _fee(entry[1]) + SLIP)
    px, held, how = at(ENTRY_S + HOLD_S)[1], HOLD_S, "5m"
    for a, p, _ in path:
        if ENTRY_S < a <= ENTRY_S + HOLD_S and p * (1 - _fee(p) - SLIP) >= buy * (1 + TARGET):
            px, held, how = p, a - ENTRY_S, "target"
            break
    return {"ret": px * (1 - _fee(px) - SLIP) / buy - 1, "held_s": held, "how": how,
            "first_sol": first[2], "pool_sol": entry[2]}


async def refresh(session, redis, now: datetime | None = None) -> dict[str, int]:
    """Price the next `CHUNK` of graduations after the cursor that have settled."""
    now = now or datetime.now(UTC)
    raw = await redis.get(CURSOR)
    a = datetime.fromisoformat(raw.decode() if isinstance(raw, bytes) else raw) if raw else START
    b = min(a + CHUNK, now - SETTLE)
    if b <= a:
        return {"priced": 0}
    paths: dict[str, list] = defaultdict(list)
    grads: dict[str, datetime] = {}
    for m, age, p, q, mig in (await session.execute(_ROWS, {"a": a, "b": b})).all():
        paths[m].append((age, p, q))
        grads[m] = mig
    names = dict((await session.execute(
        text("select mint, symbol from grad_tokens where mint = any(:m)"), {"m": list(paths)})).all()) if paths else {}
    n = 0
    for m, path in paths.items():
        trade = decide(path, names.get(m))
        if trade:
            trade.update(symbol=names.get(m), graduated_at=grads[m].isoformat())
            await redis.hset(KEY, m, json.dumps(trade))
            n += 1
    await redis.set(CURSOR, b.isoformat())
    return {"priced": n, "graduations": len(paths)}


router = APIRouter(prefix="/labs/graduation/small-first", tags=["graduation-lab"])


@router.get("", summary="Small First Buy test: paper trades since 1 Nov")
async def board() -> dict[str, Any]:
    from app.core.redis import init_redis

    redis = await init_redis()
    raw = await redis.hgetall(KEY)
    cur = await redis.get(CURSOR)
    trades = sorted(({"mint": k.decode() if isinstance(k, bytes) else k, **json.loads(v)} for k, v in raw.items()),
                    key=lambda t: t["graduated_at"], reverse=True)
    days: dict[str, dict[str, Any]] = {}
    for t in trades:
        t["pnl_usd"] = round(TICKET * t["ret"], 2)
        d = (datetime.fromisoformat(t["graduated_at"]) + timedelta(hours=4)).date().isoformat()
        x = days.setdefault(d, {"day": d, "trades": 0, "wins": 0, "rugs": 0, "pnl_usd": 0.0})
        x["trades"] += 1
        x["wins"] += t["ret"] > 0
        x["rugs"] += t["ret"] <= -0.5
        x["pnl_usd"] = round(x["pnl_usd"] + t["pnl_usd"], 2)
    return {
        "started_at": START.isoformat(),
        "priced_until": (cur.decode() if isinstance(cur, bytes) else cur) if cur else None,
        "ticket_usd": TICKET,
        "trades": len(trades),
        "wins": sum(t["ret"] > 0 for t in trades),
        "rugs": sum(t["ret"] <= -0.5 for t in trades),
        "pnl_usd": round(sum(t["pnl_usd"] for t in trades), 2),
        "days": sorted(days.values(), key=lambda x: x["day"], reverse=True),
        "recent": trades[:30],
    }
