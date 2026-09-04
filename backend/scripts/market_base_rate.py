"""What the memecoin market itself returns over a holding period, deaths included.

Read-only. Run it against production; it writes nothing.

## Why this exists as a script rather than a query someone retypes

Measured 2026-09-04, the same question gave four different answers depending on
how the dead tokens were handled:

    deaths dropped (price IS NOT NULL)            +16.4%
    deaths as recorded in snapshots only           -2.3%
    deaths counted via delisted_at                -19.3%   <- the honest one
    every unresolved entry assumed dead           -54.3%

A 35-point spread, and the OPTIMISTIC answer is the one that falls out by
default — because a query for a PRICE silently excludes whatever no longer has
one. That is not a subtle bias: it is the difference between a population that
looks mildly profitable and one that loses a fifth of its capital per hold.

So the method is committed, with its traps, instead of living in a chat log.

## The three traps, all of which produced a wrong answer before being caught

**SURVIVORSHIP.** A token that dies stops being snapshotted. Filtering on
`price_usd IS NOT NULL` deletes exactly the losses you are trying to measure.
Deaths are resolved here from `token_enrichment_state.delisted_at`, which
records the first observed absence of a pool the token used to have.

**GLITCHES.** One row in the 39-day history shows a 5,111x move in six hours on
a $327k pool. Uncapped, that single row moves the mean by +593pp. Multiples are
capped; the cap is a parameter because the right value is a judgement.

**UNRESOLVED IS NOT ZERO AND NOT SKIPPABLE.** An entry with neither a forward
price nor a recorded death is genuinely unknown. It is reported as a coverage
number rather than quietly dropped, because the answer moves with it and the
reader is entitled to see how much of the sample is missing.

## Cross-check

The death rate this reports (26.3% at the time of writing) is measured from raw
market data. The V6.1 Lab tournament, an entirely separate instrument holding
real positions to conclusion, measured 26.8%. Two methods, two populations,
half a point apart. If a future run diverges from the Lab by a lot, suspect the
measurement before believing the result.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import text

from app.db.session import SessionFactory

QUERY = text("""
WITH entry AS (
  SELECT DISTINCT ON (mint_address, date_trunc('hour', captured_at))
         mint_address, captured_at AS t0, price_usd AS p0
  FROM token_market_snapshots
  WHERE liquidity_usd >= :min_liq
    AND price_usd > 0
    AND trading_status = 'trading'
    AND extract(hour from captured_at) IN (0, 6, 12, 18)
    AND extract(minute from captured_at) < 10
  ORDER BY mint_address, date_trunc('hour', captured_at), captured_at
), fwd AS (
  SELECT e.t0,
         e.p0,
         (SELECT s.price_usd
            FROM token_market_snapshots s
           WHERE s.mint_address = e.mint_address
             AND s.captured_at BETWEEN e.t0 + :win_open AND e.t0 + :win_close
             AND s.trading_status = 'trading'
             AND s.price_usd IS NOT NULL
           ORDER BY s.captured_at
           LIMIT 1) AS p1,
         st.delisted_at
  FROM entry e
  LEFT JOIN token_enrichment_state st ON st.mint_address = e.mint_address
), cls AS (
  SELECT CASE
           WHEN p1 IS NOT NULL THEN least(p1 / p0, :cap)
           -- Dead by the end of the window. `delisted_at` is the FIRST observed
           -- absence of a pool this token used to have, so a value inside the
           -- window means it stopped trading during it.
           WHEN delisted_at IS NOT NULL AND delisted_at < t0 + :win_close THEN 0.0
           -- Neither priced nor known dead. Unknown, and counted as such.
           ELSE NULL
         END AS mult
  FROM fwd
)
SELECT count(*)                                          AS entries,
       count(mult)                                       AS resolved,
       count(*) FILTER (WHERE mult = 0)                  AS deaths,
       avg(mult)                                         AS mean_mult,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY mult) AS median_mult
FROM cls
""")


async def main(min_liq: int, hold: int, cap: float) -> None:
    async with SessionFactory() as session:
        row = (await session.execute(QUERY, {
            "min_liq": min_liq,
            "cap": Decimal(str(cap)),
            # Intervals built here rather than concatenated in SQL: the window
            # is two numbers, and building it in the query turned a parameter
            # into string arithmetic that failed to bind.
            "win_open": timedelta(hours=hold),
            "win_close": timedelta(hours=hold + 2),
        })).one()

    entries, resolved, deaths = row.entries, row.resolved, row.deaths
    print(f"liquidity floor ${min_liq:,}   hold {hold}-{hold + 2}h   cap {cap}x")
    print()
    print(f"  entries sampled   : {entries}")
    print(f"  resolved          : {resolved}"
          + (f"  ({100 * resolved / entries:.1f}%)" if entries else ""))
    print(f"  UNRESOLVED        : {entries - resolved}"
          " — neither priced nor known dead; the answer moves with these")
    if not resolved:
        print("\n  nothing resolved; no result")
        return
    print(f"  deaths            : {deaths}  ({100 * deaths / resolved:.1f}%)")
    print()
    print(f"  MEAN return       : {100 * (float(row.mean_mult) - 1):+.1f}%")
    print(f"  median return     : {100 * (float(row.median_mult) - 1):+.1f}%")
    print()
    print("  A mean far above the median is the right tail; check the max before")
    print("  believing it. One 5,111x glitch moved this by +593pp once already.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--min-liquidity", type=int, default=100_000)
    ap.add_argument("--hold-hours", type=int, default=6)
    ap.add_argument("--cap", type=float, default=10.0,
                    help="ceiling on any single multiple; guards price glitches")
    a = ap.parse_args()
    asyncio.run(main(a.min_liquidity, a.hold_hours, a.cap))
