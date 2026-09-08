"""The Five-Minute Lab's board.

Reuses `build_board` rather than restating it: both tournaments run the same
ratchet over the same tables, so a second copy would be a second definition of
"cycles banked" and "equity", and the first edit to either would make the two
pages disagree about the same arithmetic without either looking wrong.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from app.api.deps import DbSession
from app.compound.api import build_board
from app.fivemin import spec as fmspec
from app.lab.api import build_trades

router = APIRouter(prefix="/fivemin", tags=["fivemin"])

DISCLOSURE = (
    "A hypothesis, not a finding. The five-minute hold comes from the pump.fun "
    "graduation cohort, where selling at five minutes returned +$504.73 on a "
    "$100 book — and where ONE coin of 138 did 47.97x and produced 59.7% of "
    "all gross profit. Remove that single trade and the same cohort returns "
    "+$35.12. The median trade was 1.037x. That cohort is also a different "
    "population from the one this wallet trades. The stake never scales with "
    "the balance, so any compounding here is the wallet ratchet and nothing "
    "else."
)


@router.get("/board")
async def board(session: DbSession) -> dict[str, Any]:
    out = await build_board(session, registry=fmspec)
    # This lab's own disclosure replaces the Compound Lab's: the reason to
    # distrust this one is specific to it.
    out["disclosure"] = DISCLOSURE
    out["time_exit_minutes"] = fmspec.TIME_EXIT_MINUTES
    out["sizing_scales"] = fmspec.SIZING_SCALES
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
