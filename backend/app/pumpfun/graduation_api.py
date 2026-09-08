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

from decimal import Decimal
from typing import Any

from fastapi import APIRouter
from sqlalchemy import func, select

from app.api.deps import DbSession
from app.models.graduation import PumpfunGraduation, PumpfunGraduationMark
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
