"""Which wallets are repeatedly early into coins that go somewhere.

The ranking half of the KOL lab. `token_early_buyers` records that a wallet was
among the first buyers of a coin; this asks whether that meant anything, and
turns the answer into a set of wallets worth following forward.

## Ranked on one window, traded on the next. Always.

The single rule this module exists to enforce. A wallet scored on the same
trades that selected it is guaranteed to look good — that is the selection
trap that produced four false edges on this platform, and it is the entire
reason pump.fun's own leaderboard was useless: "the five most profitable
traders of the last month" is a fact about the past that predicts nothing.

So `rank()` takes an explicit `as_of` and reads NOTHING after it. The
tournament freezes its ranking at activation and lives with it. If the ranking
is any good, wallets chosen from data the lab never saw will keep hitting; if
it is not, they will revert to the base rate, and the control arm will say so.

## What counts as a hit

The coin at least DOUBLED from the wallet's own entry, within six hours of it.
Measured from the first price observable at-or-after the buy, not from the
coin's launch price — a wallet cannot buy at a price that had already gone.

A doubling PEAK is not a realisable profit, and this is not a P&L: it asks
whether the wallet was early into something that moved, which is the only
question the data can answer. What a wallet actually kept would need its
subsequent sells, and pump.fun's leaderboard already demonstrated what happens
when unrealised gains are read as earnings.

## Why a minimum sample, and why it is not negotiable

A wallet with two early buys that both ran has a 100% hit rate and tells us
nothing at all. With thousands of wallets in the pool, some will hit five in a
row by chance — so `MIN_EARLY_BUYS` is the difference between a ranking and a
list of lucky coincidences, and the base rate is reported beside every score
so a reader can see whether "60%" is impressive or ordinary.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

#: A wallet must have been early into at least this many coins in the ranking
#: window before it is scored at all. Five in a row happens by chance across
#: thousands of wallets; this is the floor under that.
MIN_EARLY_BUYS = 5

#: How far after a wallet's own entry the coin has to double.
HIT_HORIZON_HOURS = 6

#: The multiple that counts as "went somewhere".
HIT_MULTIPLE = 2.0

#: How many wallets a tournament follows. Small on purpose: the point is to
#: test whether the TOP of the ranking is real, and a wide net would dilute
#: whatever signal exists into the base rate.
TOP_N = 50


@dataclass(frozen=True, slots=True)
class RankedWallet:
    wallet_address: str
    early_buys: int
    hits: int
    hit_rate: float


#: Everything is bound to `as_of`. Every date filter below is an upper bound on
#: it, which is what makes the result point-in-time rather than a summary of
#: whatever the table happens to hold when it runs.
_SQL = text("""
WITH scored AS (
    SELECT
        eb.wallet_address,
        eb.mint_address,
        -- The first price observable at or after the buy. A wallet cannot buy
        -- at a price that had already gone, so entry is never the coin's
        -- launch print.
        (SELECT s.price_usd FROM token_market_snapshots s
          WHERE s.mint_address = eb.mint_address
            AND s.captured_at >= eb.bought_at
            AND s.captured_at <= :as_of
            AND s.price_usd > 0
          ORDER BY s.captured_at
          LIMIT 1) AS entry_price,
        (SELECT max(s.price_usd) FROM token_market_snapshots s
          WHERE s.mint_address = eb.mint_address
            AND s.captured_at >= eb.bought_at
            AND s.captured_at <= LEAST(
                  eb.bought_at + (:horizon_hours * interval '1 hour'),
                  :as_of)
            AND s.price_usd > 0) AS peak_price
    FROM token_early_buyers eb
    WHERE eb.bought_at >= :window_start
      AND eb.bought_at <= :as_of
),
per_wallet AS (
    SELECT wallet_address,
           count(*) AS early_buys,
           -- A coin we could never price is NOT a hit. Counting it as one
           -- would reward wallets for buying things that went dark.
           count(*) FILTER (
               WHERE entry_price IS NOT NULL
                 AND peak_price IS NOT NULL
                 AND peak_price >= entry_price * :hit_multiple
           ) AS hits
    FROM scored
    GROUP BY wallet_address
)
SELECT wallet_address, early_buys, hits,
       hits::float / NULLIF(early_buys, 0) AS hit_rate
FROM per_wallet
WHERE early_buys >= :min_buys
ORDER BY hit_rate DESC, early_buys DESC
LIMIT :top_n
""")

_BASE_RATE_SQL = text("""
WITH scored AS (
    SELECT
        (SELECT s.price_usd FROM token_market_snapshots s
          WHERE s.mint_address = eb.mint_address
            AND s.captured_at >= eb.bought_at
            AND s.captured_at <= :as_of
            AND s.price_usd > 0
          ORDER BY s.captured_at LIMIT 1) AS entry_price,
        (SELECT max(s.price_usd) FROM token_market_snapshots s
          WHERE s.mint_address = eb.mint_address
            AND s.captured_at >= eb.bought_at
            AND s.captured_at <= LEAST(
                  eb.bought_at + (:horizon_hours * interval '1 hour'),
                  :as_of)
            AND s.price_usd > 0) AS peak_price
    FROM token_early_buyers eb
    WHERE eb.bought_at >= :window_start AND eb.bought_at <= :as_of
)
SELECT count(*) AS n,
       count(*) FILTER (
           WHERE entry_price IS NOT NULL AND peak_price IS NOT NULL
             AND peak_price >= entry_price * :hit_multiple
       )::float / NULLIF(count(*), 0) AS base_rate
FROM scored
""")


async def rank(
    session: AsyncSession,
    *,
    as_of: datetime,
    window_days: int = 7,
    top_n: int = TOP_N,
    min_buys: int = MIN_EARLY_BUYS,
) -> list[RankedWallet]:
    """The top wallets by hit rate, using only data at or before `as_of`."""
    rows = (await session.execute(_SQL, {
        "as_of": as_of,
        "window_start": as_of - timedelta(days=window_days),
        "horizon_hours": HIT_HORIZON_HOURS,
        "hit_multiple": HIT_MULTIPLE,
        "min_buys": min_buys,
        "top_n": top_n,
    })).all()
    return [
        RankedWallet(wallet_address=r.wallet_address, early_buys=r.early_buys,
                     hits=r.hits, hit_rate=float(r.hit_rate or 0.0))
        for r in rows
    ]


async def base_rate(
    session: AsyncSession, *, as_of: datetime, window_days: int = 7
) -> tuple[int, float | None]:
    """(early buys scored, share that hit) across ALL wallets.

    Reported beside every ranking because a hit rate means nothing on its own:
    if being early into anything at all doubles a third of the time, a wallet
    at 35% is noise wearing a rosette.
    """
    row = (await session.execute(_BASE_RATE_SQL, {
        "as_of": as_of,
        "window_start": as_of - timedelta(days=window_days),
        "horizon_hours": HIT_HORIZON_HOURS,
        "hit_multiple": HIT_MULTIPLE,
    })).one()
    return int(row.n or 0), (float(row.base_rate) if row.base_rate is not None else None)
