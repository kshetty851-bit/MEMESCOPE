"""Seed KARTHIK_Q25_5M and KARTHIK_Q50_5M from Karthik's book's first day.

Karthik, 2026-09-26: "add $50k-75k pool check in karthik lab and 25k too
assuming we added them from the day 1". Neither arm existed, so there are no
trades to copy: this REPLAYS his rule on every graduation since his book
opened, from `grad_postgrad_samples`, and books each one through the engine's
own buy and `settle` arithmetic. Rows are written with close_reason "replayed".

What the replay cannot see, and stands in for (the live engine reads the pool
on-chain, and keeps those reads only for coins it bought):
  - entry: the first sample on the graduation's own pool;
  - quiet: that sample's m5 buys + sells < QUIET_MAX_POOL_TXS;
  - exit: the first sample at or after entry + 5 min whose price the pool's own
    depth can support. In an x*y=k pool, USD depth grows with the square root
    of price, so a quote past (depth ratio)^2 x 1.5 is a bad print — two such
    prints turned real +1% and +2% trades into +1,377% and +1,156%.
Checked against the trades the lab really took (2026-09-26): on the 212 coins
KARTHIK_QUIET_5M bought, the replay averaged +1.69% a trade against +1.04%
real (median gap 0.16%); on BAND_55k_quiet_5m's 38 matched coins, +9.99%
against +8.92%, and the same 4 rugs. So it reads about a point a trade
OPTIMISTIC — the seeded stretch is a look back, and only rows opened after
the deploy are forward evidence.

Safe to run twice: a mint already in the target book is skipped, and so is
anything at or after the book's first live trade.

    docker exec -w /app -e PYTHONPATH=/app memescope-backend-N \\
        python scripts/seed_karthik_bands.py [--apply]
"""

from __future__ import annotations

import asyncio
import sys
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import select, text

from app.db.session import SessionFactory
from app.labs.graduation import config
from app.labs.graduation.backtest import amm_buy, amm_impact
from app.labs.graduation.models import GradPaperPosition
from app.labs.graduation.paper import _rate, costs
from app.labs.graduation.tournament import BY_NAME, accepts, graduation_pool, settle

START = next(s for s in config.FRESH_BOOKS if s.book == "KARTHIK_QUIET_5M").start
TARGETS = ("KARTHIK_Q25_5M", "KARTHIK_Q50_5M")
N = config.PAPER_NOTIONAL_USD
_P = Decimal("0.000000000000000001")
_Q = Decimal("0.000000001")

#: Every graduation since the book opened, with its first 12 minutes of samples.
SAMPLES = text("""
select m.mint, m.ts as grad, s.ts, s.pair_address, s.price_native, s.price_usd,
       s.liquidity_usd, coalesce(s.txns_m5_buys, 0) + coalesce(s.txns_m5_sells, 0) as txs,
       t.symbol
from grad_migrations m
join grad_postgrad_samples s on s.mint = m.mint and s.ts >= m.ts
                             and s.ts <= m.ts + interval '12 minutes'
left join grad_tokens t on t.mint = m.mint
where m.ts >= :start
order by m.mint, s.ts
""")


Replayed = tuple[GradPaperPosition, Decimal, Decimal, object]


def replay(samples: list, hold: timedelta) -> Replayed | None:
    """One coin: the position the book would have opened, and its exit mark."""
    pool = graduation_pool(samples[0].mint)
    rows = [r for r in samples if r.pair_address == pool and r.price_native
            and r.price_native > 0 and r.liquidity_usd and r.price_usd]
    if not rows:
        return None
    e = rows[0]
    depth, price = Decimal(e.liquidity_usd), Decimal(e.price_native)
    if e.txs >= config.QUIET_MAX_POOL_TXS:
        return None
    impact = amm_impact(N, depth)
    rate = _rate(Decimal(e.price_usd), price)
    if impact is None or impact > config.PAPER_MAX_IMPACT or rate is None:
        return None
    nq = (N / rate).quantize(_Q)
    fee_bps = config.pool_fee_bps(price)
    fill = amm_buy(price, order_usd=N, liquidity_usd=depth,
                   fee_fraction=costs(nq, pool_fee_bps=fee_bps).fee_fraction)
    if fill is None or fill <= 0:
        return None
    exits = [r for r in rows if r.ts >= e.ts + hold
             and Decimal(r.price_native) <= price * (Decimal(r.liquidity_usd) / depth) ** 2
             * Decimal("1.5")]
    if not exits:
        return None
    x = exits[0]
    position = GradPaperPosition(
        mint=e.mint, symbol=(e.symbol or None), opened_at=e.ts,
        open_quote=price.quantize(_P), open_fill=fill.quantize(_P), notional_usd=N,
        sol_usd_at_open=rate.quantize(Decimal("0.000001")), notional_quote=nq,
        tokens=(nq / fill).quantize(_Q), peak_quote=price.quantize(_P),
        last_quote=Decimal(x.price_native).quantize(_P), liq_open_usd=depth,
        impact_open=impact.quantize(Decimal("0.000001")), pool_fee_bps=fee_bps,
        graduated_at=e.grad, marked_at=x.ts)
    return position, Decimal(x.price_native), Decimal(x.liquidity_usd), x.ts


async def main(apply: bool) -> None:
    async with SessionFactory() as session:
        by: dict[str, list] = defaultdict(list)
        for r in await session.execute(SAMPLES, {"start": START}):
            by[r.mint].append(r)
        seeded = dict.fromkeys(TARGETS, 0)
        for name in TARGETS:
            arm = BY_NAME[name]
            done = set(await session.scalars(
                select(GradPaperPosition.mint).where(GradPaperPosition.book == name)))
            live_from = await session.scalar(
                select(GradPaperPosition.opened_at)
                .where(GradPaperPosition.book == name,
                       GradPaperPosition.close_reason.is_distinct_from("replayed"))
                .order_by(GradPaperPosition.opened_at).limit(1))
            for mint, samples in by.items():
                if mint in done:
                    continue
                got = replay(samples, timedelta(minutes=arm.hold))
                if got is None:
                    continue
                position, quote, depth, closed_at = got
                if live_from is not None and position.opened_at >= live_from:
                    continue
                if not accepts(arm, mint=mint, open_at=position.opened_at,
                               liquidity=position.liq_open_usd, fdv=None,
                               sells=None, reuse=None):
                    continue
                position.book = name
                settle(position, quote, depth, "replayed", closed_at)
                session.add(position)
                seeded[name] += 1
        if apply:
            await session.commit()
        print(f"{seeded}; {'WRITTEN' if apply else 'dry run, nothing written'}")


asyncio.run(main("--apply" in sys.argv))
