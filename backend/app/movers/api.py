"""The Movers Lab in one request: a signal and its control, side by side.

Read-only, and the board itself is `app/lab/board.py` — shared rather than
copied. `/trades` is `app/lab/api.py`'s, likewise shared, so the two pages
cannot come to disagree about what "realised" means.

The one local rule is the ORDER: signal first, control second, always. Sorting
by equity would put whichever wallet is ahead today on top, and a reader
glancing at the page would take position for result. The comparison IS the
finding here, not the ranking, and the page must not be able to imply
otherwise.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from app.api.deps import DbSession
from app.lab import board as shared
from app.lab.api import build_trades
from app.movers import spec as mvspec

router = APIRouter(prefix="/movers", tags=["movers"])

#: Both wallets share one book, so a full ledger stays small.
PER_CELL_TRADES = 60

DISCLOSURE = (
    "Research simulation. TWO virtual $100 wallets started together, buying "
    "pump.fun coins with at least $100k of liquidity, a tenth of the balance "
    "per position and up to ten at once, each held 30 minutes with no "
    "take-profit and no stop, banking and compounding whenever the wallet is "
    "up 10%. They differ in ONE condition: SECURITY-GATED requires that this "
    "platform's own security evaluator positively VERIFIED the coin — "
    "contract, mint and freeze authority, liquidity — before the checkpoint, "
    "and SECURITY-CONTROL does not. "
    "The question comes from the trade record rather than a hunch. Over 50 "
    "closed trades in the previous run, partial losses averaged fourteen "
    "cents; the whole loss was five coins going to zero, -$76 against +$113 "
    "from everything else. No exit rule reaches a coin that rugs inside its "
    "holding period, and deeper liquidity did not help — the rugs entered at "
    "$423k on average against $258k for the survivors. "
    "UNKNOWN counts as not verified, as does an unevaluated coin: the "
    "evaluator's own policy requires every check to positively pass, and "
    "'we could not look' is not evidence of safety. Expect the gated arm to "
    "trade less, and to sit idle entirely while evaluation coverage catches "
    "up. If the two finish level the gate is worthless, and that is a real "
    "answer. "
    "The earlier run (movers-1.0.0, 56 trades, turnover filter retired "
    "mid-run) is frozen and is not shown here. No real order was ever placed."
)


@router.get("/board")
async def board(session: DbSession) -> dict[str, Any]:
    out = await shared.build(
        session, registry=mvspec, disclosure=DISCLOSURE,
        per_cell=PER_CELL_TRADES,
        # Signal, then control. Never by outcome — see the module docstring.
        order=lambda w: w["strategy_id"],
    )
    # Served rather than hardcoded in the client, so a reader checking the page
    # against this docstring is reading the same numbers the engine judges with.
    out["turnover_floor"] = mvspec.TURNOVER_FLOOR
    out["min_liquidity_usd"] = mvspec.MIN_LIQUIDITY_USD
    out["hold_minutes"] = round(mvspec.TIME_EXIT_HOURS * 60)
    return out


@router.get("/trades")
async def trades(session: DbSession,
                 strategy_id: str | None = Query(default=None),
                 status: str | None = Query(default=None, pattern="^(open|closed)$"),
                 limit: int = Query(default=500, le=2000)) -> dict[str, Any]:
    """Every position either wallet holds or has closed, with its own P&L.

    Filterable by strategy because the comparison is the point: a reader who
    wants to see what the control bought that the signal skipped needs to be
    able to isolate one arm.
    """
    return await build_trades(session, registry=mvspec, disclosure=DISCLOSURE,
                              strategy_id=strategy_id, status=status, limit=limit)
