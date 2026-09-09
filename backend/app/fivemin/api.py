"""The Graduation Hold Lab's board — two arms, so a multi-wallet board.

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
    "Run as refutation, not expectation. This buys the pump.fun graduation "
    "cohort two minutes after a coin completes — two minutes because a lab "
    "cannot buy what it cannot price, and only 23% of graduates have a price "
    "and a liquidity at their graduation stamp against 75% by +2. The only "
    "entry condition is $100,000 of liquidity, and that is execution fidelity "
    "rather than a signal: below it 7-8% of sells cannot route, and an exit "
    "that cannot happen on time would measure the delay instead of the clock. "
    "The stake is $2 across fifty concurrent positions because every loss in "
    "this population is TOTAL, so bet size is the only lever that helped: over "
    "465 corrected graduations and 48 shape/exit combinations, NONE was "
    "profitable once its single best trade was removed, and $2 x 50 was merely "
    "the least-bad at $93.57 from $100. The fifteen-minute arm was retired "
    "because its median was the same while its share of total losses tripled. "
    "This lab therefore no longer carries a control: it can show what the "
    "five-minute hold did, not whether the five-minute hold was the reason."
)


@router.get("/board")
async def board(session: DbSession) -> dict[str, Any]:
    # Ordered by STAKE, smallest first, because the book shape is now the axis:
    # both arms sell on the same clock and differ only in how $100 is divided.
    # Sorting by equity would put whichever arm is winning on top and destroy
    # the only axis this experiment has.
    out = await lab_board.build(
        session, registry=fmspec, disclosure=DISCLOSURE,
        order=lambda w: w.get("size_usd") or 0,
        axis=lambda s_: {
            "hold_minutes": (round((s_.exits.time_exit_hours or 0) * 60)
                             if s_ else None),
            # The label carries POPULATION as well as shape now, because two
            # arms share a shape and only the population separates them.
            "shape": (f"{s_.name}" if s_ else None),
            "source": (fmspec.SOURCE_BY_STRATEGY.get(
                s_.id, fmspec.CANDIDATE_SOURCE) if s_ else None),
        },
    )
    out["hold_minutes"] = list(fmspec.HOLD_MINUTES)
    out["stake_usd"] = str(fmspec.STAKE_USD)
    out["book_shapes"] = [f"${int(k)} x {n}" for k, n in fmspec.BOOK_SHAPES]
    out["arm_sources"] = {
        a.id: fmspec.SOURCE_BY_STRATEGY.get(a.id, fmspec.CANDIDATE_SOURCE)
        for a in fmspec.STRATEGIES
    }
    out["sizing_scales"] = fmspec.SIZING_SCALES
    out["cycle_enabled"] = fmspec.CYCLE_ENABLED
    out["candidate_source"] = fmspec.CANDIDATE_SOURCE
    out["checkpoint_minutes"] = fmspec.CHECKPOINT_MINUTES
    out["liquidity_floor"] = str(fmspec.LIQUIDITY_FLOOR)
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
