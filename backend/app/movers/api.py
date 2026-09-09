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
    "Research simulation, and NO LONGER A CONTROLLED ONE. One virtual $100 "
    "wallet buying every pump.fun coin with at least $100k of liquidity, a "
    "tenth of the balance per position and up to ten at once, each held 30 "
    "minutes with no take-profit and no stop, banking and compounding "
    "whenever the wallet is up 10%. "
    "It began as a pair: MOVERS-TURNOVER required five-minute volume of at "
    "least 1.0x the coin's liquidity and this arm did not, so the difference "
    "between them measured whether that filter was worth anything. The "
    "filtered arm was retired on 2026-09-09 with three closed trades, so that "
    "question is now unanswered and cannot be answered from this page. "
    "What remains has NO BENCHMARK. A good number here cannot be told apart "
    "from a good week, which matters because the measurement this lab was "
    "built on found turnover to be a floor rather than a score, and because "
    "every payoff study on this platform has found peaks are not realisable "
    "and every exit level negative. "
    "No real order was ever placed."
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
