"""The homepage's journey section: live figures only (Karthik, 2026-09-27).

Public — the site-code gate lets this one path through
(`middleware.alpha_access.EXEMPT_EXACT_PATHS`) — and cached a minute, like
Karthik's Lab summary. It lives here, not in `app.labs.graduation`, because it
reads the real wallet, which that lab is kept apart from on purpose.

From the real wallet it carries the COUNT of the owner's trades and wins since
midnight Dubai and nothing else: no amounts, no coins, no address.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter
from sqlalchemy import text

from app.api.deps import DbSession
from app.core.config import settings
from app.labs.graduation.api import karthik_book
from app.services.github_counts import github_counts, github_days

router = APIRouter(tags=["homepage"])

DUBAI = timedelta(hours=4)
TTL_S = 60
_CACHE: tuple[datetime, dict[str, Any]] | None = None


@router.get("/journey", summary="The homepage journey section's live figures")
async def journey(db: DbSession) -> dict[str, Any]:
    global _CACHE
    now = datetime.now(UTC)
    if _CACHE is not None and (now - _CACHE[0]).total_seconds() < TTL_S:
        return _CACHE[1]
    book = await karthik_book(db)
    finished = [d for d in book["days"] if not d["running"]]
    last = finished[0] if finished else None      # days come newest first
    today = (now + DUBAI).replace(hour=0, minute=0, second=0, microsecond=0) - DUBAI
    real = (await db.execute(text("""
        select count(*) as trades,
               count(*) filter (where coalesce(realised_net_pnl_usd,
                                               realised_gross_pnl_usd) > 0) as wins
        from real_wallet_positions
        where status = 'CLOSED' and closed_at >= :today
          and wallet_public_key = :owner"""),
        {"today": today, "owner": settings.REAL_WALLET_PUBLIC_KEY.strip()})).one()
    counts = (await db.execute(text("""
        select (select count(distinct book) from grad_paper_positions) as strategies,
               (select count(*) from grad_paper_positions) as paper_trades,
               (select count(*) from real_wallet_positions) as real_trades,
               (select count(*) from grad_migrations) as graduations"""))).one()
    out = {
        "lab": {
            "started_at": book["started_at"], "judge_at": book["judge_at"],
            "trades": book["trades"], "wins": book["wins"], "rugs": book["rugs"],
            "finished_days": len(finished),
            "last_day_pnl_usd": last["pnl_usd"] if last else None,
        },
        "real_today": {"trades": real.trades, "wins": real.wins, "since": today},
        "strategies_tested": counts.strategies,
        "trades_tested": counts.paper_trades + counts.real_trades,
        "graduations_watched": counts.graduations,
        **await github_counts(now),
        # The day-by-day log: every day with a commit, and what it built.
        "days": await github_days(now),
    }
    _CACHE = (now, out)
    return out
