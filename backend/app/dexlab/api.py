"""The Dex Lab in one request: a signal and its control, side by side.

Read-only. The board itself is `app/lab/board.py` and `/trades` is
`app/lab/api.py`'s — shared rather than copied, so the pages cannot come to
disagree about what "realised" means.

The one local rule is the ORDER: signal first, control second, always. Sorting
by equity would put whichever wallet is ahead today on top, and a reader
glancing at the page would take position for result. The comparison IS the
finding.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from app.api.deps import DbSession
from app.dexlab import spec as dxspec
from app.lab import board as shared
from app.lab.api import build_trades

router = APIRouter(prefix="/dex", tags=["dex"])

#: Both wallets share one book, so a full ledger stays small.
PER_CELL_TRADES = 60

DISCLOSURE = (
    "Research simulation. TWO virtual $100 wallets started together over the "
    "same pool of Solana tokens with at least $100,000 of liquidity, on any "
    "venue, $5 a position and up to twenty at once, each held six hours with "
    "no take-profit, no stop and no wallet ratchet. They differ in ONE "
    "condition: DEXBOARD-TURNOVER requires that the token traded at least "
    "twice its own liquidity in the previous hour, and DEXBOARD-CONTROL does "
    "not. "
    "The question is whether a DexScreener top gainer can be identified before "
    "it is one. The board is a rear-view mirror and DexScreener's public API "
    "does not expose it — there is no gainers endpoint and no sort by price "
    "change — so this rebuilds the board's input from our own price and volume "
    "record and asks whether the input predicts the board. "
    "Measured over 66 hours of 2026-08-21 to 08-23: of 152,913 Solana mints "
    "observed, 7,852 report pool liquidity at all and 619 ever reach $100,000. "
    "Among those, tokens that went on to touch 2x sat at 20.7 times hourly "
    "turnover and tokens that did not at 0.05. Held six hours with an unpriced "
    "token counted as a total loss, the turnover rule returned a mean of 1.47x "
    "over 251 episodes against the control's 0.82x over 417 — but a fifth of "
    "its positions went to zero against the control's 2%, and the finding "
    "comes from a single three-day window in one market regime. "
    "Expect the signal arm to trade far less than the control; compare equity, "
    "not activity. If the two finish level, turnover is worthless here, and "
    "that is a real answer — nine no-edge findings precede this one. "
    "No real order was ever placed."
)


@router.get("/board")
async def board(session: DbSession) -> dict[str, Any]:
    out = await shared.build(
        session, registry=dxspec, disclosure=DISCLOSURE,
        per_cell=PER_CELL_TRADES,
        # Signal, then control. Never by outcome — see the module docstring.
        order=lambda w: w["strategy_id"],
    )
    # Served rather than hardcoded in the client, so a reader checking the page
    # against the rulebook is reading the numbers the engine judges with.
    out["turnover_floor"] = dxspec.TURNOVER_FLOOR
    out["min_liquidity_usd"] = dxspec.MIN_LIQUIDITY_USD
    out["hold_hours"] = dxspec.TIME_EXIT_HOURS
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
    return await build_trades(session, registry=dxspec, disclosure=DISCLOSURE,
                              strategy_id=strategy_id, status=status, limit=limit)
