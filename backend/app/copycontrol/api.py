"""CPY-01 and CPY-02 side by side — the only way either number means anything."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.api.deps import DbSession
from app.copycontrol import spec as ccspec
from app.lab import board as shared

router = APIRouter(prefix="/copycontrol", tags=["copycontrol"])

DISCLOSURE = (
    "Research simulation, and a CONTROL rather than a strategy. A virtual $100 "
    "wallet that buys a RANDOM pump.fun token at the exact moments CPY-01 "
    "copies the leader's buys, at the same size, and sells when he sells his — "
    "so entry time, position size and holding period are all matched and the "
    "ONLY difference is which token was chosen. The token is drawn from a "
    "generator seeded with the leader's transaction signature, so every pick "
    "is reproducible from the ledger. It starts from its own valid_from and "
    "says NOTHING about CPY-01's earlier trades — a control cannot be run "
    "retroactively. No real order was ever placed."
)


@router.get("/board")
async def board(session: DbSession) -> dict[str, Any]:
    return await shared.build(
        session, registry=ccspec, disclosure=DISCLOSURE, per_cell=60,
    )
