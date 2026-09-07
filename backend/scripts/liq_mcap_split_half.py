"""Does liquidity-relative-to-size rank forward returns — and does it PERSIST?

Read-only. Run against production; it writes nothing.

## Why this script exists rather than another lab

The Depth Lab showed that ABSOLUTE liquidity does not separate a token that
survives from one that goes to zero: median entry liquidity was $341,956 for
both. But `liq_mcap` — liquidity as a fraction of market cap — separated the
two by 8.5x on the median.

On FOURTEEN tokens. That is the V6-07 shape exactly: a striking ratio on a
sample too small to mean anything, and four previous false edges on this
platform looked like that before split-half took them apart. So it is measured
here, on the history that already exists, before it is allowed to cost a
tournament.

## The test

Buckets, not a threshold. Every (mint, hour) entry with a live price and a
market cap is placed in a `liq_mcap` quintile, and the forward return over the
holding window is averaged per quintile. A threshold picked from the same data
it is measured on is a threshold fitted to noise.

**Split by TIME, and the second half is the answer.** The quintile ordering is
read off the FIRST half of the window and then applied to the SECOND. An effect
that ranks in-sample and not out-of-sample is the same non-effect that made the
mcap filter look like an 8.51 profit factor before split-half took it to 0.72.

## WHAT THIS SCRIPT FOUND ON ITS FIRST RUN, 2026-09-07

Not an answer about `liq_mcap`. A defect that made the question unanswerable.

`delisted_at` — the field every death-aware measurement here resolves deaths
from — stopped being written on 2026-09-04 04:42, the moment a one-off backfill
finished. 792,107 tokens had a pool, were empty, and carried no death stamp;
at the exact transition the code stamps (`consecutive_empty == 0` -> 1) only
7.5% were stamped.

The cause: `record_result` runs in the ENRICHMENT containers, and deploys had
only ever rebuilt `backend worker scheduler`. The enrichment images were three
days old and did not contain the stamping code at all. It had never run.

The symptom in this script's own output was a recent half reporting ZERO deaths
in every bucket — which reads as a safer population and is actually a blind
one. If a future run shows that again, check the enrichment image before
believing any of it.

## Two more sampling traps this script has to avoid

**RETENTION MAKES OLD HALVES BIASED.** Market snapshots older than
`MARKET_SNAPSHOT_RETENTION_DAYS` (7) are pruned EXCEPT for tokens that reached
the Radar or were traded. A 30-day window therefore compares a protected subset
against a full one — the first run showed 4,059 entries in half A against
20,594 in half B, which is retention, not the market. Keep the window inside
the retention period.

**RECENT ENTRIES HAVE NOT FINISHED DYING.** `--lag-hours` excludes entries whose
forward window has not closed and whose deaths have not had time to be
recorded.

## The three traps, all of which have produced a wrong answer here before

**SURVIVORSHIP.** A token that dies stops being snapshotted, so filtering on
`price_usd IS NOT NULL` deletes exactly the losses being measured. Deaths are
resolved from `token_enrichment_state.delisted_at` and counted as 0.

**GLITCHES.** One row in the history shows a 5,111x move in six hours. Uncapped,
that single row moved a mean by +593pp. Multiples are capped.

**UNRESOLVED IS NOT ZERO.** An entry with neither a forward price nor a
recorded death is unknown, and is reported as coverage rather than dropped.
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
  SELECT DISTINCT ON (s.mint_address, date_trunc('hour', s.captured_at))
         s.mint_address,
         s.captured_at                AS t0,
         s.price_usd                  AS p0,
         s.liquidity_usd / s.market_cap AS liq_mcap
  FROM token_market_snapshots s
  JOIN discovered_tokens d ON d.mint_address = s.mint_address
  WHERE s.captured_at >= :since
    AND s.captured_at <= :until
    AND s.price_usd > 0
    AND s.liquidity_usd >= :min_liq
    AND s.market_cap > 0
    AND s.trading_status = 'trading'
    AND s.suspect IS NOT TRUE
    AND d.source_program = ANY(:programs)
    AND extract(minute from s.captured_at) < 10
  ORDER BY s.mint_address, date_trunc('hour', s.captured_at), s.captured_at
), fwd AS (
  SELECT e.*,
         (SELECT s2.price_usd FROM token_market_snapshots s2
           WHERE s2.mint_address = e.mint_address
             AND s2.captured_at BETWEEN e.t0 + :win_open AND e.t0 + :win_close
             AND s2.trading_status = 'trading' AND s2.price_usd IS NOT NULL
           ORDER BY s2.captured_at LIMIT 1) AS p1,
         st.delisted_at
  FROM entry e
  LEFT JOIN token_enrichment_state st ON st.mint_address = e.mint_address
), cls AS (
  SELECT t0, liq_mcap,
         CASE
           WHEN p1 IS NOT NULL THEN least(p1 / p0, :cap)
           WHEN delisted_at IS NOT NULL AND delisted_at < t0 + :win_close THEN 0.0
           WHEN :assume_dead THEN 0.0
           ELSE NULL
         END AS mult
  FROM fwd
), halved AS (
  SELECT *, CASE WHEN t0 < :midpoint THEN 'A' ELSE 'B' END AS half FROM cls
), bucketed AS (
  -- Quintiles cut on the FIRST half only, then applied to both. Cutting them
  -- per-half would compare different thresholds and hide a real shift.
  SELECT h.*,
         width_bucket(h.liq_mcap,
                      (SELECT percentile_cont(0.20) WITHIN GROUP (ORDER BY liq_mcap)
                         FROM halved WHERE half = 'A'),
                      (SELECT percentile_cont(0.80) WITHIN GROUP (ORDER BY liq_mcap)
                         FROM halved WHERE half = 'A'),
                      3) AS bucket
  FROM halved h
)
SELECT half, bucket,
       count(*)                                          AS entries,
       count(mult)                                       AS resolved,
       count(*) FILTER (WHERE mult = 0)                  AS deaths,
       round(avg(liq_mcap)::numeric, 4)                  AS avg_liq_mcap,
       round(avg(mult)::numeric, 4)                      AS mean_mult,
       round((percentile_cont(0.5) WITHIN GROUP (ORDER BY mult))::numeric, 4) AS median_mult
FROM bucketed
GROUP BY half, bucket
ORDER BY half, bucket
""")


async def main(days: int, hold: int, min_liq: int, cap: float,
               assume_dead: bool = False, lag_hours: int = 24) -> None:
    async with SessionFactory() as session:
        now = (await session.execute(text("SELECT now()"))).scalar()
        # Entries must be old enough that their forward window has CLOSED and
        # a death has had time to be recorded. Without this the recent half
        # showed 0 deaths in every bucket — not a safer population, just one
        # that had not finished dying yet.
        until = now - timedelta(hours=lag_hours)
        since = until - timedelta(days=days)
        midpoint = until - timedelta(days=days / 2)
        rows = (await session.execute(QUERY, {
            "since": since,
            "until": until,
            "midpoint": midpoint,
            "min_liq": min_liq,
            "cap": Decimal(str(cap)),
            "win_open": timedelta(hours=hold),
            "win_close": timedelta(hours=hold + 2),
            "assume_dead": assume_dead,
            "programs": ["6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P",
                         "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA"],
        })).all()

    print(f"window {days}d ending {lag_hours}h ago   hold {hold}-{hold+2}h   "
          f"min liquidity ${min_liq:,}   cap {cap}x")
    print("unresolved treated as: " + ("DEAD (pessimistic bound)"
          if assume_dead else "unknown and excluded"))
    print("quintile cuts taken on half A only, then applied to B\n")
    print(f"{'half':5} {'bucket':7} {'entries':>8} {'resolved':>9} {'deaths':>7} "
          f"{'death%':>7} {'liq/mcap':>9} {'MEAN ret':>9} {'median':>8}")
    print("-" * 78)
    by_half: dict[str, list] = {}
    for r in rows:
        by_half.setdefault(r.half, []).append(r)
        death_pct = (100 * r.deaths / r.resolved) if r.resolved else 0
        mean_ret = (float(r.mean_mult) - 1) * 100 if r.mean_mult is not None else None
        med = (float(r.median_mult) - 1) * 100 if r.median_mult is not None else None
        print(f"{r.half:5} {r.bucket:<7} {r.entries:>8} {r.resolved:>9} {r.deaths:>7} "
              f"{death_pct:>6.1f}% {float(r.avg_liq_mcap):>9.4f} "
              f"{mean_ret:>8.1f}% {med:>7.1f}%")

    print()
    for half, rs in by_half.items():
        ranked = [r for r in rs if r.mean_mult is not None]
        if len(ranked) < 2:
            continue
        best = max(ranked, key=lambda r: r.mean_mult)
        worst = min(ranked, key=lambda r: r.mean_mult)
        print(f"half {half}: best bucket {best.bucket} "
              f"({(float(best.mean_mult)-1)*100:+.1f}%), "
              f"worst bucket {worst.bucket} "
              f"({(float(worst.mean_mult)-1)*100:+.1f}%)")
    print()
    print("THE QUESTION: does the bucket ordering in half A repeat in half B?")
    print("If the best bucket in A is not the best in B, this does not persist,")
    print("and it is the same non-effect as every filter tested here before.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--hold-hours", type=int, default=6)
    ap.add_argument("--min-liquidity", type=int, default=25_000)
    ap.add_argument("--cap", type=float, default=10.0)
    ap.add_argument("--lag-hours", type=int, default=24,
                    help="exclude entries newer than this, so every forward "
                         "window has closed and deaths have had time to be "
                         "recorded. Without it the recent half reports zero "
                         "deaths everywhere.")
    ap.add_argument("--assume-unresolved-dead", action="store_true",
                    help="the pessimistic bound: an entry that is neither "
                         "priced nor recorded dead is counted as a total loss. "
                         "Coverage is low, and the ORDERING surviving both "
                         "treatments is what makes it a finding rather than an "
                         "artefact of which rows happen to resolve.")
    a = ap.parse_args()
    asyncio.run(main(a.days, a.hold_hours, a.min_liquidity, a.cap,
                     a.assume_unresolved_dead, a.lag_hours))
