"""The graduation cohort: what happens in the hour after a coin graduates.

Computed server-side so one implementation owns the accounting, and so the page
cannot quietly disagree with a query run by hand.

Two exclusions, both of which change the answer:

* **The cold-start batch.** The collector's very first pass stamped every coin
  that was ALREADY complete. Their stamp is when we started watching, not when
  they graduated — the precise error that made the snapshot version
  unanswerable — so the earliest stamp instant is dropped. Genuine graduations
  trickle in at roughly one every two minutes; the cold start arrived seventy in
  the same second, which is how it is identified.
* **Coins with no graduation market cap.** Nothing can be measured against an
  unknown reference, and substituting a curve-derived estimate would be an
  assumption dressed as an observation.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from fastapi import APIRouter
from sqlalchemy import func, select

from app.api.deps import DbSession
from app.models.graduation import PumpfunGraduation, PumpfunGraduationMark
from app.lab import leaderboard
from app.pumpfun.graduation import TARGET_MINUTES

router = APIRouter(prefix="/pumpfun", tags=["pumpfun"])

DISCLOSURE = (
    "Observation, not a strategy. Every pump.fun coin seen graduating is "
    "stamped at the moment we first observe its bonding curve complete, and "
    "re-read at 5, 15, 30 and 60 minutes. The return shown is what buying at "
    "that stamped market cap and selling at each age would have produced, "
    "before fees and before any price impact — so treat it as an upper bound. "
    "pump.fun publishes no graduation timestamp; this is ours."
)


@router.get("/graduations")
async def graduations(session: DbSession) -> dict[str, Any]:
    cold_start = await session.scalar(
        select(func.min(PumpfunGraduation.first_seen_complete_at))
    )
    base = select(PumpfunGraduation).where(
        PumpfunGraduation.mcap_usd_at_graduation.is_not(None),
        PumpfunGraduation.mcap_usd_at_graduation > 0,
    )
    if cold_start is not None:
        base = base.where(PumpfunGraduation.first_seen_complete_at != cold_start)

    cohort = {g.id: g for g in (await session.execute(base)).scalars()}
    total_stamped = await session.scalar(
        select(func.count()).select_from(PumpfunGraduation)
    )

    rows = []
    for minutes in TARGET_MINUTES:
        marks = (await session.execute(
            select(PumpfunGraduationMark)
            .where(PumpfunGraduationMark.minutes_since == minutes,
                   PumpfunGraduationMark.mcap_usd.is_not(None))
        )).scalars()
        rets = sorted(
            float(m.mcap_usd / cohort[m.graduation_id].mcap_usd_at_graduation) - 1.0
            for m in marks if m.graduation_id in cohort
        )
        if not rets:
            rows.append({"minutes": minutes, "n": 0})
            continue
        mid = len(rets) // 2
        median = rets[mid] if len(rets) % 2 else (rets[mid - 1] + rets[mid]) / 2
        rows.append({
            "minutes": minutes,
            "n": len(rets),
            # Median first: one glitch cannot move it, and a mean on this
            # population is carried by a handful of survivors.
            "median_pct": round(median * 100, 2),
            "mean_pct": round(sum(rets) / len(rets) * 100, 2),
            "pct_up": round(100.0 * sum(1 for r in rets if r > 0) / len(rets), 1),
            "worst_pct": round(rets[0] * 100, 2),
            "best_pct": round(rets[-1] * 100, 2),
        })

    return {
        "disclosure": DISCLOSURE,
        "cohort": len(cohort),
        "total_stamped": total_stamped or 0,
        "excluded_cold_start": (total_stamped or 0) - len(cohort),
        "since": cold_start.isoformat() if cold_start else None,
        "ages": rows,
    }


# --------------------------------------------------------------------------
# A simulated $100 book over the same cohort
# --------------------------------------------------------------------------

#: The book, and how it is divided. $10 x 10 means the whole $100 can be at
#: work at once and every position is the same size — no discretion about which
#: coin deserves more, because there is no basis for such a judgement here.
PAPER_BOOK_USD = Decimal("100")
PAPER_POSITION_USD = Decimal("10")
PAPER_MAX_CONCURRENT = 10

#: A multiple above this inside an hour is a corrupt market cap, not a trade.
#: The raw feed produced 11,670x on one coin; left in, it alone would have
#: reported the book turning $100 into six figures. Excluded and COUNTED, never
#: clamped — a clamped glitch is still a number somebody trusts.
PAPER_GLITCH_MULTIPLE = Decimal("100")

#: Round-trip execution assumed for the NET figure. Measured from real Jupiter
#: quotes at >= $100k liquidity. A coin at graduation sits in a much thinner
#: pool, so this is a FLOOR on the true cost and the net number is optimistic.
PAPER_EXECUTION_PCT = Decimal("0.0078")


@router.get("/graduations/paper")
async def graduation_paper(session: DbSession) -> dict[str, Any]:
    """What a $100 book would have made buying every graduation and selling at
    a fixed age — simulated over the cohort we actually stamped.

    NOT a lab. Nothing is traded; this replays the collected marks under one
    rule, so it cannot drift from the data it describes.

    Every exclusion is reported rather than silently dropped, because a
    backtest that quietly discards what it cannot price reports the survivors
    as if they were the population — which is the single error that has made
    every previous result on this platform look better than it was.
    """
    cold_start = await session.scalar(
        select(func.min(PumpfunGraduation.first_seen_complete_at))
    )
    rows = list((await session.execute(
        select(PumpfunGraduation)
        .where(PumpfunGraduation.mcap_usd_at_graduation.is_not(None),
               PumpfunGraduation.mcap_usd_at_graduation > 0,
               PumpfunGraduation.first_seen_complete_at != cold_start)
        .order_by(PumpfunGraduation.first_seen_complete_at)
    )).scalars())

    marks: dict[tuple, Decimal] = {}
    for m in (await session.execute(
        select(PumpfunGraduationMark)
        .where(PumpfunGraduationMark.mcap_usd.is_not(None))
    )).scalars():
        marks[(m.graduation_id, m.minutes_since)] = m.mcap_usd

    horizons = []
    for minutes in TARGET_MINUTES:
        cash = PAPER_BOOK_USD
        equity_realised = Decimal(0)
        open_until: list[datetime] = []
        taken = skipped_capacity = no_mark = glitched = 0

        for g in rows:
            t0 = g.first_seen_complete_at
            open_until = [t for t in open_until if t > t0]
            if len(open_until) >= PAPER_MAX_CONCURRENT:
                skipped_capacity += 1
                continue
            exit_mcap = marks.get((g.id, minutes))
            if exit_mcap is None:
                # Not yet old enough, or unreadable. NOT a zero and not a win.
                no_mark += 1
                continue
            mult = exit_mcap / g.mcap_usd_at_graduation
            if mult > PAPER_GLITCH_MULTIPLE:
                glitched += 1
                continue
            if cash < PAPER_POSITION_USD:
                skipped_capacity += 1
                continue
            cash -= PAPER_POSITION_USD
            proceeds = PAPER_POSITION_USD * mult
            cash += proceeds
            equity_realised += proceeds - PAPER_POSITION_USD
            open_until.append(t0 + timedelta(minutes=minutes))
            taken += 1

        gross = cash
        # Execution charged on BOTH legs of every trade actually taken.
        cost = PAPER_POSITION_USD * PAPER_EXECUTION_PCT * Decimal(taken)
        horizons.append({
            "minutes": minutes,
            "trades": taken,
            "final_equity_gross": round(gross, 2),
            "final_equity_net": round(gross - cost, 2),
            "pnl_gross": round(gross - PAPER_BOOK_USD, 2),
            "pnl_net": round(gross - PAPER_BOOK_USD - cost, 2),
            "execution_charged": round(cost, 2),
            "skipped_no_mark_yet": no_mark,
            "skipped_capacity": skipped_capacity,
            "excluded_glitch": glitched,
        })

    return leaderboard._jsonable({
        "disclosure": (
            f"Simulated. A ${PAPER_BOOK_USD:.0f} book, ${PAPER_POSITION_USD:.0f} "
            f"per position and at most {PAPER_MAX_CONCURRENT} at once, buying "
            "every graduation we stamped and selling at a fixed age. Nothing "
            "was traded. Entry is our first sighting of the completed curve — "
            "up to a minute after the real graduation — so a fill at that price "
            "is assumed, not demonstrated. Execution is charged at "
            f"{PAPER_EXECUTION_PCT*100:.2f}% round trip, measured on pools at "
            "$100k+ liquidity; a coin at graduation sits in a far thinner pool, "
            "so the net figure is a BEST CASE and the true cost is higher."
        ),
        "book_usd": PAPER_BOOK_USD,
        "position_usd": PAPER_POSITION_USD,
        "max_concurrent": PAPER_MAX_CONCURRENT,
        "cohort": len(rows),
        "horizons": horizons,
    })
