"""Fresh Catch Lab (Karthik, 2026-10-26: "create a paper lab for 10k-30k with this
rule since oct 1 ... start balance 1000$ and per trade 50$").

The rule, exactly as researched on 1-26 Oct (`$10k-$30k`, realistic replay: +$5,480
at $50 a trade, +$279 without Kimchi, -$578 without its best two):

* the coin's FIRST positive-liquidity DexScreener reading shows a pool of $10k to
  under $30k, on its verified canonical token/SOL pool (derived address);
* that reading came 0-30 s after the on-chain graduation (`grad_migrations`);
* at least 65% of its 5-minute transactions were buys (counts, not dollars);
* not bought 08:00-11:59 Dubai.

Bought at the NEXT same-pool reading (never at the reading that qualified it),
sold at the first same-pool DexScreener reading 4-6 minutes later, else the
GeckoTerminal candle close whose minute ENDS in that window, else the stake is
lost. Costs: 1.25% a side plus constant-product impact of the ticket both ways.
Paper only: nothing here can reach a wallet.

Each coin is decided once, after `SETTLE`, and stored in Redis; `refresh` (every
5 minutes) decides the graduations not yet decided, oldest first.
"""

from __future__ import annotations

import heapq
import json
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text

from app.labs.graduation import config
from app.security.liquidity import derive_or_none

KEY = "freshcatch:coins:v1"
START = datetime(2026, 9, 30, 20, tzinfo=UTC)          # 1 Oct 00:00 Dubai
CAPITAL, TICKET = 1000.0, 50.0
POOL = (10_000, 30_000)
FRESH_S, BUY_SHARE = 30, 65
SKIP_DUBAI_HOURS = range(8, 12)
HOLD_S, WINDOW_S = 240, 120
FEE_SIDE = 0.0125
DUBAI = timezone(timedelta(hours=4))
#: A coin is decided once its exit window has closed and late readings are in.
SETTLE = timedelta(minutes=15)
BATCH = 2000

_GRADS = text("""
    select mint, min(ts) ts from grad_migrations
    where pool = 'pump-amm' and ts >= :a and ts <= :b group by mint order by min(ts)""")
_FIRST = text("""
    select ts, pair_address, price_usd::float8, liquidity_usd::float8, txns_m5_buys, txns_m5_sells
    from grad_postgrad_samples
    where mint = :m and source = 'dexscreener' and pair_address is not null and liquidity_usd > 0
    order by ts limit 1""")
_AFTER = text("""
    select ts, source, price_usd::float8, liquidity_usd::float8 from grad_postgrad_samples
    where mint = :m and pair_address = :p and price_usd > 0 and ts > :a
      and ts <= cast(:a as timestamptz) + interval '12 minutes'
      and source in ('dexscreener', 'geckoterminal')
    order by ts""")


def qualifies(first: Any, graduated: datetime, mint: str) -> str | None:
    """None if the first reading qualifies, else why not (kept for the page)."""
    ts, pair, price, liq, buys, sells = first
    if not POOL[0] <= liq < POOL[1]:
        return "pool"
    derived = derive_or_none(mint, pumpfun_program=config.PUMP_PROGRAM_ID)
    if not derived or derived[0] != pair:
        return "not_sol_pool"
    if not 0 <= (ts - graduated).total_seconds() <= FRESH_S:
        return "not_fresh"
    if buys is None or sells is None or buys < 0 or sells < 0 or buys + sells == 0 \
            or 100 * buys < BUY_SHARE * (buys + sells):
        return "buys_under_65"
    if ts.astimezone(DUBAI).hour in SKIP_DUBAI_HOURS:
        return "morning"
    return None


def priced(after: list[Any]) -> dict[str, Any] | None:
    """The trade on the readings after the qualifying one: entry at the next Dex
    reading, exit 4-6 minutes later (Dex reading, else candle close at minute end)."""
    dex = [r for r in after if r[1] == "dexscreener"]
    if not dex:
        return None
    entry_at, _, entry, liq = dex[0]
    lo, hi = entry_at + timedelta(seconds=HOLD_S), entry_at + timedelta(seconds=HOLD_S + WINDOW_S)
    out = next(((r[0], r[2], "dex") for r in dex[1:] if lo <= r[0] <= hi), None)
    if out is None:
        out = next(((r[0] + timedelta(minutes=1), r[2], "candle") for r in after
                    if r[1] == "geckoterminal" and lo <= r[0] + timedelta(minutes=1) <= hi), None)
    cost = 2 * FEE_SIDE + (2 * TICKET / (liq / 2) if liq else 0)
    if out is None:
        return {"entry_at": entry_at.isoformat(), "exit_at": hi.isoformat(), "net": -1.0,
                "how": "unpriced", "liq": liq}
    gross = out[1] / entry - 1
    net = max(-1.0, (1 + gross) * (1 - cost) - 1)
    return {"entry_at": entry_at.isoformat(), "exit_at": out[0].isoformat(), "net": net,
            "gross": gross, "how": out[2], "liq": liq}


async def refresh(session, redis, now: datetime | None = None) -> dict[str, int]:
    """Decide up to `BATCH` graduations old enough to be final, oldest first."""
    now = now or datetime.now(UTC)
    done = {k.decode() if isinstance(k, bytes) else k for k in await redis.hkeys(KEY)}
    grads = (await session.execute(_GRADS, {"a": START, "b": now - SETTLE})).all()
    todo = [(m, ts) for m, ts in grads if m not in done][:BATCH]
    kept = 0
    for mint, graduated in todo:
        first = (await session.execute(_FIRST, {"m": mint})).first()
        why = "no_reading" if first is None else qualifies(first, graduated, mint)
        rec: dict[str, Any] = {"why": why}
        if why is None:
            sym = await session.scalar(text("select symbol from grad_tokens where mint = :m"), {"m": mint})
            after = (await session.execute(_AFTER, {"m": mint, "p": first[1], "a": first[0]})).all()
            trade = priced(after)
            if trade is None:
                rec = {"why": "no_next_reading"}
            else:
                rec = {"why": None, "symbol": sym, "pool": first[3], "seen_s":
                       round((first[0] - graduated).total_seconds(), 1),
                       "buys": first[4], "sells": first[5], **trade}
                kept += 1
        await redis.hset(KEY, mint, json.dumps(rec))
    return {"decided": len(todo), "trades": kept, "left": len(grads) - len(done) - len(todo)}


def book(coins: dict[str, dict[str, Any]], now: datetime) -> dict[str, Any]:
    """The $1,000 account: a trade is taken only with $50 free, its proceeds come
    back at its sale. An unpriced exit loses the stake."""
    trades = sorted(({"mint": m, **r} for m, r in coins.items() if r.get("why") is None),
                    key=lambda r: r["entry_at"])
    cash = bal = low = peak = CAPITAL
    drop = 0.0
    pend: list[tuple[str, float, dict[str, Any]]] = []
    took, skipped, days = [], 0, {}

    def settle(until: str) -> None:
        nonlocal cash, bal, low, peak, drop
        while pend and pend[0][0] <= until:
            at, proceeds, r = heapq.heappop(pend)
            cash += proceeds
            bal += proceeds - TICKET
            low, peak = min(low, bal), max(peak, bal)
            drop = max(drop, peak - bal)
            day = datetime.fromisoformat(at).astimezone(DUBAI).date().isoformat()
            d = days.setdefault(day, {"day": day, "trades": 0, "pnl_usd": 0.0, "rugs": 0})
            d["trades"] += 1
            d["pnl_usd"] += proceeds - TICKET
            d["rugs"] += r["net"] <= -0.5

    for r in trades:
        settle(r["entry_at"])
        if cash < TICKET:
            skipped += 1
            continue
        cash -= TICKET
        proceeds = TICKET * (1 + r["net"])
        heapq.heappush(pend, (r["exit_at"], proceeds, r))
        took.append({**r, "pnl_usd": round(proceeds - TICKET, 2)})
    settle("9999")
    pnl = sorted((t["pnl_usd"] for t in took), reverse=True)
    why: dict[str, int] = {}
    for r in coins.values():
        if r.get("why"):
            why[r["why"]] = why.get(r["why"], 0) + 1
    return {
        "name": "Fresh Catch Lab", "started_at": START.isoformat(), "as_of": now.isoformat(),
        "capital_usd": CAPITAL, "ticket_usd": TICKET, "balance_usd": round(bal, 2),
        "pnl_usd": round(bal - CAPITAL, 2), "lowest_usd": round(low, 2),
        "worst_drop_usd": round(drop, 2), "trades": len(took), "skipped_cash": skipped,
        "wins": sum(p > 0 for p in pnl), "rugs": sum(t["net"] <= -0.5 for t in took),
        "unpriced": sum(t["how"] == "unpriced" for t in took),
        "without_best_usd": round(sum(pnl[1:]), 2), "without_best5_usd": round(sum(pnl[5:]), 2),
        "best": [{"symbol": t["symbol"], "pnl_usd": t["pnl_usd"]}
                 for t in sorted(took, key=lambda t: -t["pnl_usd"])[:5]],
        "graduations_checked": len(coins), "refused": why,
        "days": [{**d, "pnl_usd": round(d["pnl_usd"], 2)} for d in sorted(days.values(), key=lambda d: d["day"])],
        "trades_list": [{k: t.get(k) for k in ("mint", "symbol", "pool", "seen_s", "buys", "sells",
                                                 "entry_at", "exit_at", "net", "how", "pnl_usd")}
                        for t in reversed(took[-200:])],
    }


async def coins(redis) -> dict[str, dict[str, Any]]:
    raw = await redis.hgetall(KEY)
    return {(k.decode() if isinstance(k, bytes) else k): json.loads(v) for k, v in raw.items()}
