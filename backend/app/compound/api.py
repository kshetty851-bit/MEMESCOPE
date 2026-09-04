"""What the Compound Lab is doing, as one request.

Read-only. The wallet, the cycle ledger and the open book, served already
computed — nothing here recomputes a figure the engine owns, for the same
reason the Lab's API does not: a second implementation is a second answer, and
the first time either changed they would disagree.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from sqlalchemy import select

from app.api.deps import DbSession
from app.compound import spec as cspec
from app.lab import leaderboard
from app.models.compound import CompoundCycle
from app.models.lab import LabPosition, LabStrategy, LabTournament

router = APIRouter(prefix="/compound", tags=["compound"])

DISCLOSURE = (
    "Research simulation. One virtual $100 wallet trading a frozen rule and "
    "taking profit on the WALLET at +10%, then compounding from what it "
    "actually realised. No real order was ever placed for any of it. The entry "
    "rule was chosen on a handful of trades and is a hypothesis, not a result."
)


@router.get("/board")
async def board(session: DbSession) -> dict[str, Any]:
    t = (await session.execute(
        select(LabTournament).where(
            LabTournament.spec_version == cspec.SPEC_VERSION)
    )).scalars().first()
    if t is None:
        return {"disclosure": DISCLOSURE, "activated": False,
                "spec_version": cspec.SPEC_VERSION, "spec_hash": cspec.SPEC_HASH,
                "starting_equity": cspec.STARTING_EQUITY,
                "target_multiple": cspec.CYCLE_TARGET_MULTIPLE,
                "cycles": [], "positions": []}

    row = (await session.execute(
        select(LabStrategy).where(LabStrategy.tournament_id == t.id)
    )).scalars().first()
    cycles = list((await session.execute(
        select(CompoundCycle).where(CompoundCycle.strategy_row_id == row.id)
        .order_by(CompoundCycle.cycle_no.desc())
    )).scalars())
    positions = list((await session.execute(
        select(LabPosition).where(LabPosition.strategy_row_id == row.id)
        .order_by(LabPosition.opened_at.desc()).limit(200)
    )).scalars())

    open_value = sum((p.last_open_value_usd or p.size_usd)
                     for p in positions if p.status == "open")
    running = next((c for c in cycles if c.reached_at is None), None)
    banked = [c for c in cycles if c.reached_at is not None]

    return leaderboard._jsonable({
        "disclosure": DISCLOSURE,
        "activated": True,
        "spec_version": cspec.SPEC_VERSION,
        "spec_hash": cspec.SPEC_HASH,
        "strategy_id": row.strategy_id,
        "name": row.name,
        "rules": cspec.rules_json(cspec.BY_ID[row.strategy_id]),
        "starting_equity": cspec.STARTING_EQUITY,
        "target_multiple": cspec.CYCLE_TARGET_MULTIPLE,
        "failure_floor": cspec.FAILURE_EQUITY_FLOOR,
        "cash": row.cash,
        "open_value": open_value,
        "equity": row.cash + open_value,
        "status": row.status,
        # Cycles COMPLETED, not cycles started: the running one has banked
        # nothing yet and counting it would overstate the record by one.
        "cycles_banked": len(banked),
        "current_cycle": ({
            "cycle_no": running.cycle_no, "base_usd": running.base_usd,
            "target_usd": running.target_usd,
            "started_at": running.started_at.isoformat(),
        } if running else None),
        "cycles": [{
            "cycle_no": c.cycle_no, "base_usd": c.base_usd,
            "target_usd": c.target_usd,
            "started_at": c.started_at.isoformat(),
            "reached_at": c.reached_at.isoformat() if c.reached_at else None,
            "equity_at_target": c.equity_at_target,
            "realised_equity": c.realised_equity,
            "positions_closed": c.positions_closed,
            "outcome": c.outcome,
        } for c in cycles],
        "positions": [{
            "id": str(p.id), "mint": p.mint_address, "status": p.status,
            "opened_at": p.opened_at.isoformat(), "size_usd": p.size_usd,
            "open_value": p.last_open_value_usd,
            "exec_multiple": p.last_exec_multiple,
            "exit_reason": p.exit_reason,
            "pnl": ((p.exit_proceeds_usd - p.size_usd)
                    if p.exit_proceeds_usd is not None else None),
        } for p in positions],
    })
