"""The Matrix Lab's board: twenty-four arms, read as a grid rather than a list.

Ordered by strategy id, which sorts the grid into its axes — population, then
clock, then book shape — so the board reads as the factorial it is. NEVER by
outcome: sorting twenty-four books by equity puts whichever line is ahead at
the top and invites exactly the reading this design exists to prevent.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from app.api.deps import DbSession
from app.lab import board as shared
from app.lab.api import build_trades
from app.matrix import spec as mxspec

router = APIRouter(prefix="/matrix", tags=["matrix"])

PER_CELL_TRADES = 30

DISCLOSURE = (
    "A grid, not a horse race. Twenty-four wallets across two populations, "
    "four holding periods and three book shapes — every arm differs from its "
    "neighbours in exactly ONE dimension, so a difference is attributable and "
    "a whole row or column reads as a dose-response. With this many books the "
    "single best line is very probably noise: V6 ran twenty wallets here and "
    "eighteen finished below the failure floor. The AGED section carries its "
    "own warning: a breakout entry on established tokens has already measured "
    "2.73 percentage points WORSE than a random bar in the same tokens, so it "
    "runs to test whether the CLOCK behaves differently there, not because the "
    "population is expected to win. Every arm banks the wallet at +10% and "
    "compounds from what was realised; for the no-clock arms that is the only "
    "exit, so a book holding coins that neither rise nor die stays locked. "
    "Nothing here is real money."
)


@router.get("/board")
async def board(session: DbSession) -> dict[str, Any]:
    out = await shared.build(
        session, registry=mxspec, disclosure=DISCLOSURE,
        per_cell=PER_CELL_TRADES,
        # By id, which sorts population -> clock -> shape. Never by outcome.
        order=lambda w: w["strategy_id"],
        axis=lambda s_: {
            "section": ("FRESH" if s_.id.startswith("F") else "AGED") if s_ else None,
            "clock_minutes": (None if s_ is None or s_.exits.time_exit_hours is None
                              else round(s_.exits.time_exit_hours * 60)),
            "shape": (f"${int(s_.size_usd)} x {s_.max_concurrent}" if s_ else None),
            "source": (mxspec.SOURCE_BY_STRATEGY.get(s_.id) if s_ else None),
        },
    )
    out["min_liquidity_usd"] = str(mxspec.MIN_LIQUIDITY_USD)
    out["min_age_hours"] = str(mxspec.MIN_AGE_HOURS)
    out["target_multiple"] = str(mxspec.CYCLE_TARGET_MULTIPLE)
    out["sections"] = ["FRESH", "AGED"]
    return out


@router.get("/trades")
async def trades(session: DbSession,
                 strategy_id: str | None = Query(default=None),
                 status: str | None = Query(default=None, pattern="^(open|closed)$"),
                 limit: int = Query(default=500, le=2000)) -> dict[str, Any]:
    """Every position any arm holds or has closed, filterable by arm.

    Filterable because a grid is unreadable otherwise: comparing two cells
    means isolating them, and twenty-four books interleaved by time is not a
    comparison, it is a log.
    """
    return await build_trades(session, registry=mxspec, disclosure=DISCLOSURE,
                              strategy_id=strategy_id, status=status, limit=limit)
