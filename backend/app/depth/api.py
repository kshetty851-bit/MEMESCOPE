"""The depth curve in one request: twenty wallets, one variable.

The board itself is `app/lab/board.py`, shared with the other ratchet
experiments. All that is local here is the x-axis: the liquidity floor each
cell tests, and the rule that the curve reads in floor order rather than in
outcome order.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.api.deps import DbSession
from app.depth import spec as cspec
from app.lab import board as shared

router = APIRouter(prefix="/depth", tags=["depth"])

#: Trades returned per cell. Twenty cells make a full ledger large, and the
#: page shows one cell at a time — the counts and the realised P&L beside them
#: are computed over EVERY row, so a truncated list cannot understate a record.
PER_CELL_TRADES = 60

DISCLOSURE = (
    "Research simulation. Twenty virtual $100 wallets differing in ONE number: "
    "the liquidity floor, from $25,000 to $1,000,000. No momentum, no score, no "
    "filter of any kind beyond the floor. Read it as a CURVE, not a "
    "leaderboard — one cell beating another can be luck, which is exactly what "
    "the result that prompted this experiment might have been. Only a "
    "monotonic trend across twenty points would mean anything. Above $500,000 "
    "there were 29 pump.fun tokens in three days and above $1M only ten, so the "
    "top cells trade rarely and repeatedly. No real order was ever placed."
)


@router.get("/board")
async def board(session: DbSession) -> dict[str, Any]:
    return await shared.build(
        session, registry=cspec, disclosure=DISCLOSURE,
        per_cell=PER_CELL_TRADES,
        axis=lambda s_: {"floor_usd": (
            float(next(c.value for c in s_.entry if c.feature == "liq"))
            if s_ else 0.0)},
        # By FLOOR, never by equity. This is a dose-response curve and its shape
        # is the result; sorting by outcome would put the winner at the top and
        # destroy the only thing the experiment measures.
        order=lambda w: w["floor_usd"],
    )
