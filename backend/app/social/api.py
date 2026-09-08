"""The Social Lab in one request: a signal and its control, side by side.

Read-only, and the board itself is `app/lab/board.py` — shared with the Depth
curve rather than copied from it.

The one local rule is the ORDER: signal first, control second, always. Sorting
by equity would put whichever wallet is ahead today on top, and a reader
glancing at the page would take position for result. The comparison is the
finding here, not the ranking, and the page must not be able to imply
otherwise.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.api.deps import DbSession
from app.lab import board as shared
from app.social import spec as sspec

router = APIRouter(prefix="/social", tags=["social"])

#: Both wallets share one book, so a full ledger stays small.
PER_CELL_TRADES = 60

DISCLOSURE = (
    "Research simulation. Two virtual $100 wallets, pump.fun tokens only, $5 a "
    "position and up to twenty at once, each banking on the WALLET at +10% and "
    "compounding from what it actually realised. They differ in ONE condition: "
    "SOCIAL-RISING requires the coin's comment rate to be going up, "
    "SOCIAL-CONTROL does not. Everything else — the pool, the size, the exits, "
    "the ratchet — is identical, which is what makes the pair readable. "
    "This is the first rule on this platform that reads something other than "
    "price, liquidity or volume, all of which have now been measured and found "
    "to carry no edge at any exit level. If the two wallets finish level, "
    "attention is not a signal either, and that is a real answer. "
    "Only about a fifth of the coins pump.fun's social feed surfaces can be "
    "priced here in real time, so both wallets trade a subset of what that feed "
    "shows. No real order was ever placed."
)


@router.get("/board")
async def board(session: DbSession) -> dict[str, Any]:
    return await shared.build(
        session, registry=sspec, disclosure=DISCLOSURE,
        per_cell=PER_CELL_TRADES,
        axis=lambda s_: {"is_control": bool(s_ and s_.evidence == "CONTROL")},
        # Signal, then control. Never by outcome — see the module docstring.
        order=lambda w: w["strategy_id"],
    )
