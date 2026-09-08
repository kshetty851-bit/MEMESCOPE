"""The Hold-Horizon Lab's board — two arms, so a multi-wallet board.

Serves `lab.board.build`, the same builder Depth, Momentum and Social use,
rather than the Compound Lab's single-wallet `build_board`. That one selects
ONE strategy row with `.first()`, which was right while this lab had one
wallet and would silently have shown a single arm now that it has two.

Nothing here recomputes a figure the engine owns: a second implementation is a
second answer, and the first time either changed they would disagree.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from app.api.deps import DbSession
from app.fivemin import spec as fmspec
from app.lab import board as lab_board
from app.lab.api import build_trades

router = APIRouter(prefix="/fivemin", tags=["fivemin"])

DISCLOSURE = (
    "Run as refutation, not expectation. The FIFTEEN-minute hold has already "
    "been measured on 1,348 real executed positions and returned about -8.5% "
    "net per trade — the 9% with no price at the horizon were the rugs, not "
    "missing data. The FIVE-minute figure that motivated this lab (+$504.73 on "
    "a $100 book) came from a different population, pump.fun graduations, and "
    "rested on ONE coin of 138 doing 47.97x: remove it and the same cohort "
    "returns +$35.12, median trade 1.037x. What is new here is that both "
    "horizons take the SAME entry at the SAME instant with the SAME $10 stake, "
    "so the difference between the two arms is the clock and nothing else. "
    "There is no wallet ratchet and the stake never scales."
)


@router.get("/board")
async def board(session: DbSession) -> dict[str, Any]:
    # Ordered by the horizon itself, shortest first, so the board reads as the
    # comparison it is. Sorting by equity would put whichever arm is winning on
    # top and destroy the only axis this experiment has.
    out = await lab_board.build(
        session, registry=fmspec, disclosure=DISCLOSURE,
        order=lambda w: w.get("hold_minutes") or 0,
        axis=lambda s_: {"hold_minutes": (
            round((s_.exits.time_exit_hours or 0) * 60) if s_ else None)},
    )
    out["hold_minutes"] = list(fmspec.HOLD_MINUTES)
    out["stake_usd"] = str(fmspec.STAKE_USD)
    out["sizing_scales"] = fmspec.SIZING_SCALES
    out["cycle_enabled"] = fmspec.CYCLE_ENABLED
    return out


@router.get("/trades")
async def trades(session: DbSession,
                 status: str | None = Query(default=None, pattern="^(open|closed)$"),
                 limit: int = Query(default=500, le=2000)) -> dict[str, Any]:
    """Every position this lab holds or has closed, each with its own P&L and
    its full mint. The board's `positions` is a display window, not the record;
    this is the record, built by the same function `/lab/trades` uses so the
    two cannot disagree about what "realised" means.
    """
    return await build_trades(session, registry=fmspec, disclosure=DISCLOSURE,
                              status=status, limit=limit)
