"""MEMESCOPE's track record (Karthik, 2026-10-22): "put all this information
and keep updating! mention which token did how many x returns".

Everything here is measured, never estimated:
  * the funnel: coins seen launching, tracked on the curve, graduated,
    traded on paper by how many books, checked and traded by the real wallet;
  * for every graduation, the best multiple its price reached in the 24 hours
    after graduating, against its first recorded price (a peak, not a trade
    anyone could have taken: the page says so);
  * the best trades the books and the real wallet actually made.

A day's graduations take ~2 s to read, so `refresh` keeps finished days in
Redis and only recomputes the last two; the API reads the stored result.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import text

DUBAI = timedelta(hours=4)
FIRST_DAY = date(2026, 9, 11)              # the Graduation Lab's first graduation
DAY_KEY, TOTALS_KEY, BEST_KEY = "track:grad-day:v2:", "track:totals", "track:best"
TIERS = (1.1, 1.5, 2, 5, 10, 50, 100)
TOP_PER_DAY = 15
#: A price that jumps UP this much between two samples is the feed switching
#: to another pool, not a trade (memory: DexScreener pair switching).
GLITCH_JUMP = 20
#: A pool holding less than this at its first price is a dead or fake pool
#: (ChileCar "4,719x" started in a $9 pool): its multiples mean nothing.
MIN_POOL_USD = 5_000

_DAY_SQL = text("""
with g as (select distinct on (mint) mint, ts from grad_migrations
           where ts >= :lo and ts < :hi order by mint, ts)
select g.mint, g.ts, t.symbol, t.name,
       array_agg(extract(epoch from p.ts - g.ts)::float8 order by p.ts),
       array_agg(p.price_usd::float8 order by p.ts),
       (array_agg(p.liquidity_usd::float8 order by p.ts))[1]
from g
join (select mint, ts, price_usd, liquidity_usd from grad_postgrad_samples
      where mint in (select mint from g)) p
     on p.mint = g.mint and p.ts >= g.ts and p.ts <= g.ts + interval '24 hours' and p.price_usd > 0
left join grad_tokens t on t.mint = g.mint
group by g.mint, g.ts, t.symbol, t.name""")


def _day_bounds(d: date) -> tuple[datetime, datetime]:
    lo = datetime(d.year, d.month, d.day, tzinfo=UTC) - DUBAI
    return lo, lo + timedelta(days=1)


def summarise(rows: list[tuple]) -> dict[str, Any]:
    """One Dubai day: how many graduated, how many reached each multiple, and
    the day's best movers."""
    coins = []
    for mint, ts, symbol, name, mins, px, liq in rows:
        if (len(px) < 3 or px[0] <= 0 or (liq or 0) < MIN_POOL_USD
                or any(b > a * GLITCH_JUMP for a, b in zip(px, px[1:]))):
            continue
        # A peak must hold for two samples in a row (~20-30 s): one print is not a price.
        held = [min(a, b) for a, b in zip(px, px[1:])]
        i = max(range(len(held)), key=held.__getitem__)
        coins.append({"mint": mint, "symbol": symbol, "name": name,
                      "graduated_at": ts.isoformat(), "pool_usd": round(liq or 0),
                      "peak_x": round(held[i] / px[0], 2), "peak_after_min": round(mins[i] / 60, 1),
                      "end_x": round(px[-1] / px[0], 3)})
    coins.sort(key=lambda c: -c["peak_x"])
    return {"graduated": len(rows), "measured": len(coins),
            "reached": {str(t): sum(c["peak_x"] >= t for c in coins) for t in TIERS},
            "ended_down_80": sum(c["end_x"] <= 0.2 for c in coins),
            "top": coins[:TOP_PER_DAY]}


async def _totals(session) -> dict[str, Any]:
    one = lambda sql: session.execute(text(sql))  # noqa: E731
    seen = (await one("select count(*), min(discovered_at) from discovered_tokens")).one()
    tracked = (await one("select count(*) from grad_tokens")).one()
    grads = (await one("select count(distinct mint), min(ts) from grad_migrations")).one()
    paper = (await one("select count(distinct mint), count(*), count(distinct book) "
                       "from grad_paper_positions where excluded is null")).one()
    real = (await one("""select count(*), count(distinct mint_address),
                          count(*) filter (where realised_net_pnl_usd > 0),
                          coalesce(sum(realised_net_pnl_usd), 0), min(opened_at)
                         from real_wallet_positions where status = 'CLOSED'""")).one()
    checks = (await one("select count(*) from real_wallet_safety_evaluations")).one()
    return {"coins_seen": seen[0], "seen_since": seen[1].isoformat() if seen[1] else None,
            "curve_tracked": tracked[0], "graduated": grads[0],
            "graduated_since": grads[1].isoformat() if grads[1] else None,
            "paper_coins": paper[0], "paper_trades": paper[1], "strategies": paper[2],
            "real_trades": real[0], "real_coins": real[1], "real_wins": real[2],
            "real_pnl_usd": round(float(real[3]), 2),
            "real_since": real[4].isoformat() if real[4] else None,
            "safety_checks": checks[0]}


async def _best(session) -> dict[str, Any]:
    """The biggest wins the books and the real wallet actually banked."""
    paper = (await session.execute(text("""
        select distinct on (mint) mint, symbol, book, opened_at, net_return::float8, liq_open_usd::float8
        from grad_paper_positions
        where book in ('KARTHIK_QUIET_5M', 'KARTHIK_Q50_5M') and excluded is null
          and net_return is not null and opened_at >= '2026-09-30 20:00+00'
        order by mint, net_return desc"""))).all()
    paper = sorted(paper, key=lambda r: -r[4])[:12]
    real = (await session.execute(text("""
        select p.mint_address, p.opened_at, p.realised_net_pnl_usd::float8,
               (p.entry_actual_input_amount * p.entry_sol_price_usd)::float8, p.strategy_id,
               (select g.symbol from grad_paper_positions g where g.mint = p.mint_address
                and g.symbol is not null limit 1)
        from real_wallet_positions p
        where p.status = 'CLOSED' and p.realised_net_pnl_usd is not null
          and p.entry_actual_input_amount > 0 and p.entry_sol_price_usd > 0
        order by p.realised_net_pnl_usd / nullif(p.entry_actual_input_amount * p.entry_sol_price_usd, 0) desc
        limit 12"""))).all()
    return {
        "paper": [{"mint": m, "symbol": s, "book": b, "opened_at": at.isoformat(),
                   "x": round(1 + r, 2), "pool_usd": round(liq or 0)} for m, s, b, at, r, liq in paper],
        "real": [{"mint": m, "symbol": sym, "opened_at": at.isoformat(), "strategy": st,
                  "stake_usd": round(stake, 2), "pnl_usd": round(pnl, 2),
                  "x": round(1 + pnl / stake, 2)} for m, at, pnl, stake, st, sym in real if stake],
    }


async def refresh(session, redis, now: datetime | None = None) -> dict[str, Any]:
    """Store the totals, the best trades and every missing or recent day."""
    now = now or datetime.now(UTC)
    today = (now + DUBAI).date()
    done = 0
    d = FIRST_DAY
    while d <= today:
        key = DAY_KEY + d.isoformat()
        # A day's coins keep being read for 24 h after graduating, so the last
        # two finished days are recomputed too.
        if d >= today - timedelta(days=2) or not await redis.exists(key):
            lo, hi = _day_bounds(d)
            rows = (await session.execute(_DAY_SQL, {"lo": lo, "hi": hi})).all()
            await redis.set(key, json.dumps({"date": d.isoformat(), **summarise(rows)}))
            done += 1
        d += timedelta(days=1)
    await redis.set(TOTALS_KEY, json.dumps({**await _totals(session), "at": now.isoformat()}))
    await redis.set(BEST_KEY, json.dumps(await _best(session)))
    return {"days_computed": done}


async def read(redis) -> dict[str, Any] | None:
    totals = json.loads(await redis.get(TOTALS_KEY) or "null")
    if totals is None:
        return None
    days = []
    for key in sorted(await redis.keys(DAY_KEY + "*")):
        days.append(json.loads(await redis.get(key)))
    hall = sorted((c for d in days for c in d["top"]), key=lambda c: -c["peak_x"])
    week = days[-7:]
    return {
        "totals": totals,
        "best": json.loads(await redis.get(BEST_KEY) or "{}"),
        "reached": {str(t): sum(d["reached"][str(t)] for d in days) for t in TIERS},
        "measured": sum(d["measured"] for d in days),
        "ended_down_80": sum(d["ended_down_80"] for d in days),
        "hall_of_fame": hall[:24],
        "this_week": sorted((c for d in week for c in d["top"]), key=lambda c: -c["peak_x"])[:12],
        "days": [{"date": d["date"], "graduated": d["graduated"], "measured": d["measured"],
                  "x2": d["reached"]["2"], "x10": d["reached"]["10"],
                  "best_x": d["top"][0]["peak_x"] if d["top"] else None,
                  "best_symbol": d["top"][0]["symbol"] if d["top"] else None} for d in days],
    }
