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
    "Research simulation. Two virtual $100 wallets, pump.fun tokens only, $10 a "
    "position and up to ten at once, each held for exactly 30 minutes with NO "
    "take-profit and no stop. They differ in ONE condition: MOVERS-TURNOVER "
    "requires five-minute volume of at least 1.0x the coin's liquidity, "
    "MOVERS-CONTROL does not. Everything else — the pool, the $100k liquidity "
    "floor, the size, the clock — is identical, which is what makes the pair "
    "readable. "
    "The rule comes from a measurement, not a hunch: over 4,130 tokens, those "
    "that later doubled were sitting at 0.63 turnover beforehand against 0.11 "
    "for those that did not. But that same measurement showed turnover is a "
    "FLOOR and not a score — above the threshold the hit rate is flat and "
    "non-monotonic across every decile — so nothing here ranks or sizes by it. "
    "'Doubled' there meant the price TOUCHED 2x at some later moment, which no "
    "seller necessarily got: every payoff study on this platform has found "
    "peaks are not realisable and every exit level tested came out negative. "
    "If the two wallets finish level, turnover is not a signal, and that is a "
    "real answer. The control has beaten the designed arm here before. "
    "No real order was ever placed."
)


@router.get("/board")
async def board(session: DbSession) -> dict[str, Any]:
    out = await shared.build(
        session, registry=mvspec, disclosure=DISCLOSURE,
        per_cell=PER_CELL_TRADES,
        axis=lambda s_: {"is_control": bool(s_ and s_.evidence == "CONTROL")},
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
