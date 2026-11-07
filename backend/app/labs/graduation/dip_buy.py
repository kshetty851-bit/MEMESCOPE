"""Dip Buy, the Pump Catcher Lab's rule from 1 Nov (Karthik, 2026-11-06: "apply
this rule from 1st Nov and show revised profits"). Paper only; the real wallets
and USER 1 keep following the old coins (`pump_feed`).

30 seconds after graduating, buy when the price is 20-40% below its peak so far,
the name has 1-5 letters and the pool's SOL side holds at least 30 SOL; sell at
+60% after costs (filled at the next reading), else at 5 minutes. Picked from
about 38,000 rules on 26-31 Oct; one of the 12 best there, and chosen among those
after seeing 1-6 Nov, so its days from 7 Nov on are the test.

Quiet Small Pool, the lab's second rule from 1 Nov (Karthik, 2026-11-08: "add
quiet small pool to lab since nov 1"): 20 seconds after graduating, buy when the
pool's SOL side holds 30-60 SOL and has not fallen more than 5% from its high
(nobody big has sold); sell at +100% or -35% after costs (each filled at the next
reading), else at 7 minutes. Picked on 28 Oct-3 Nov, held on 4-7 Nov (10 trades),
so its days from 8 Nov on are the test. A coin both rules want is Quiet's.

Priced from `grad_first_minute` (on-chain, every change), readings forward-filled
(no change = no trade): fees by pool tier plus Jupiter's cut plus `SLIP` each
way. `refresh` (every 5 minutes) walks the graduations in time order from `START`
and stores each trade in Redis.
"""

from __future__ import annotations

import bisect
import json
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import text

from app.labs.graduation import config, pump_catcher

START = datetime(2026, 10, 31, 20, tzinfo=UTC)       # 1 Nov, Dubai
ENTRY_S, HOLD_S, TARGET = 30, 300, 0.60
DIP_MIN, DIP_MAX, POOL_MIN_SOL, NAME_MAX = 0.20, 0.40, 30.0, 5
SLIP = 0.005
QUIET_S, QUIET_HOLD_S, QUIET_TARGET, QUIET_STOP = 20, 420, 1.00, -0.35
QUIET_POOL_SOL, QUIET_MAX_DROP = (30.0, 60.0), 0.05
#: v2 (2026-11-08): both rules, each trade with its rule and entry second.
KEY, CURSOR = "dipbuy:v2", "dipbuy:v2:cursor"
CHUNK = timedelta(hours=24)
#: After the hold plus the recorder's slack, a graduation is final.
SETTLE = timedelta(seconds=max(ENTRY_S + HOLD_S, QUIET_S + QUIET_HOLD_S) + 120)

_ROWS = text("""
    select mint, extract(epoch from ts - migrated_at)::float8 age, price_native::float8, quote_reserve::float8,
           migrated_at
      from grad_first_minute
     where sol_quoted and migrated_at >= :a and migrated_at < :b
       and ts >= :a and ts < cast(:b as timestamptz) + interval '520 seconds'
       and ts - migrated_at <= interval '480 seconds'
     order by mint, ts""")


def _fee(p: float) -> float:
    return (config.pool_fee_bps(Decimal(str(p))) + config.ROUTER_FEE_BPS) / 1e4


def _sell(path, i: int, end: int, buy: float, target: float, stop: float | None) -> tuple[int, str, float]:
    """Index, how and return (before `REAL_SLIP`) of the sell after buying at reading `i`."""
    sold = lambda p: p * (1 - _fee(p) - SLIP) / buy - 1  # noqa: E731
    for k in range(i + 1, end + 1):
        r = sold(path[k][1]) - pump_catcher.REAL_SLIP
        if r >= target or (stop is not None and r <= stop):
            out = min(k + 1, end)                       # filled at the next reading
            return out, "target" if r >= target else "stop", sold(path[out][1])
    return end, "time", sold(path[end][1])


def decide(path: list[tuple[float, float, float]], symbol: str | None) -> dict[str, Any] | None:
    """One graduation's (seconds after graduating, SOL price, SOL side) readings.
    None when neither rule buys it. The return is before `REAL_SLIP`, which the
    exits count and `Position` takes off."""
    if not path or path[0][0] > 10:
        return None
    ages = [a for a, _, _ in path]
    last = lambda t: max(0, bisect.bisect_right(ages, t) - 1)  # noqa: E731
    i = last(QUIET_S)
    pool = path[i][2]
    if QUIET_POOL_SOL[0] <= pool < QUIET_POOL_SOL[1] and pool >= (1 - QUIET_MAX_DROP) * max(q for _, _, q in path[:i + 1]):
        rule, entry_s, hold, target, stop = "quiet", QUIET_S, QUIET_HOLD_S, QUIET_TARGET, QUIET_STOP
    else:
        i = last(ENTRY_S)
        name = (symbol or "").strip()
        dip = 1 - path[i][1] / max(p for _, p, _ in path[:i + 1])
        if not (0 < len(name) <= NAME_MAX and path[i][2] >= POOL_MIN_SOL and DIP_MIN <= dip < DIP_MAX):
            return None
        rule, entry_s, hold, target, stop = "dip", ENTRY_S, HOLD_S, TARGET, None
    entry = path[i]
    buy = entry[1] * (1 + _fee(entry[1]) + SLIP)
    out, how, ret = _sell(path, i, last(entry_s + hold), buy, target, stop)
    return {"rule": rule, "entry_s": entry_s, "ret": ret, "how": how,
            "held_s": path[out][0] - entry_s if how != "time" else hold,
            "pool_sol": entry[2], "entry_px": entry[1], "exit_px": path[out][1]}


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


class Position:
    """A trade dressed as a book position, so the Pump Catcher page walks it like
    its own. Priced like the lab's other trades: `REAL_SLIP` comes off, and the
    walk adds its own size penalty."""

    impact_open = impact_close = Decimal(0)

    def __init__(self, mint: str, t: dict[str, Any], sol_usd: float | None):
        self.id = self.mint = mint
        self.symbol = t.get("symbol")
        self.rule = t.get("rule", "dip")
        self.opened_at = datetime.fromisoformat(t["graduated_at"]) + timedelta(seconds=t.get("entry_s", ENTRY_S))
        self.closed_at = self.opened_at + timedelta(seconds=t["held_s"])
        self.net_return = Decimal(str(round(t["ret"] - pump_catcher.REAL_SLIP, 6)))
        self.liq_open_usd = Decimal(round(2 * t["pool_sol"] * sol_usd)) if sol_usd else None
        self.open_quote, self.close_quote = t.get("entry_px"), t.get("exit_px")
        self.sol_usd_at_open = sol_usd

    def __getattr__(self, name: str) -> Any:     # anything else a book row has: unknown
        return None


async def positions(redis, sol_usd: Any) -> list[Position]:
    rate = float(sol_usd) if sol_usd else None
    raw = await redis.hgetall(KEY)
    return sorted((Position(k.decode() if isinstance(k, bytes) else k, json.loads(v), rate) for k, v in raw.items()),
                  key=lambda p: (p.opened_at, p.mint))
