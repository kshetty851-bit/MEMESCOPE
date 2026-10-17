"""MEMESCOPE's own numbers for the front page: measured by this site, labelled as ours.

Only what the owner already publishes (2026-09-24): pump.fun graduation counts,
first-hour rug rates and Karthik's Lab headline figures. No trade lists, no
wallets, no coin-level lab detail.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.labs.graduation.models import GradMigration, GradRugVerdict

_DRAINS = text("""
select v.mint, v.graduated_at, t.symbol, t.name
from grad_rug_verdicts v left join grad_tokens t on t.mint = v.mint
where v.rugged and v.graduated_at >= :since
order by v.graduated_at desc limit 8""")


async def pulse(session: AsyncSession, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    day, hour = now - timedelta(hours=24), now - timedelta(hours=1)
    grads_24h, grads_1h = (
        await session.execute(
            select(
                func.count().filter(GradMigration.ts >= day),
                func.count().filter(GradMigration.ts >= hour),
            ).where(GradMigration.ts >= day)
        )
    ).one()
    measured, rugged = (
        await session.execute(
            select(
                func.count().filter(GradRugVerdict.measured),
                func.count().filter(GradRugVerdict.rugged),
            ).where(GradRugVerdict.graduated_at >= day)
        )
    ).one()
    drains = [
        {
            "mint": r.mint,
            "symbol": r.symbol,
            "name": r.name,
            "graduated_at": r.graduated_at.isoformat(),
        }
        for r in (await session.execute(_DRAINS, {"since": now - timedelta(hours=12)})).all()
    ]
    from app.labs.graduation.api import karthik_summary  # cached for 5 minutes there

    try:
        lab = await karthik_summary(session)
        lab = {
            k: (str(v) if not isinstance(v, (int, float, str, type(None))) else v)
            for k, v in lab.items()
        }
    except Exception:  # the lab is optional on the front page
        lab = None
    return {
        "graduations_24h": int(grads_24h or 0),
        "graduations_1h": int(grads_1h or 0),
        "rug_measured_24h": int(measured or 0),
        "rugged_24h": int(rugged or 0),
        "rug_rate_24h": (round(100 * rugged / measured, 1) if measured else None),
        "recent_drains": drains,
        "karthik_lab": lab,
    }
