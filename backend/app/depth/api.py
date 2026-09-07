"""The depth curve in one request: twenty wallets, one variable.

Read-only. The wallet, the cycle ledger and the open book, served already
computed — nothing here recomputes a figure the engine owns, for the same
reason the Lab's API does not: a second implementation is a second answer, and
the first time either changed they would disagree.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from fastapi import APIRouter
from sqlalchemy import func, select

from app.api.deps import DbSession
from app.depth import spec as cspec
from app.lab import leaderboard
from app.models.compound import CompoundCycle
from app.models.lab import LabPosition, LabStrategy, LabTournament

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

    rows = list((await session.execute(
        select(LabStrategy).where(LabStrategy.tournament_id == t.id)
        .order_by(LabStrategy.strategy_id)
    )).scalars())
    ids = [r.id for r in rows]
    cycles = list((await session.execute(
        select(CompoundCycle).where(CompoundCycle.strategy_row_id.in_(ids))
        .order_by(CompoundCycle.cycle_no.desc())
    )).scalars())
    # OPEN and CLOSED, both, because a cell's record is not readable from its
    # open book alone: a wallet holding nothing has either never traded or
    # closed everything, and those are opposite facts.
    positions = list((await session.execute(
        select(LabPosition).where(LabPosition.strategy_row_id.in_(ids))
        .order_by(LabPosition.opened_at.desc()).limit(PER_CELL_TRADES * 20)
    )).scalars())

    # Counts and realised P&L come from the DATABASE, over every row, because
    # `positions` above is a display window. Deriving a cell's record from a
    # truncated list would understate it the moment a cell traded more than the
    # window, and the understatement would grow with the cell's activity —
    # which is exactly backwards.
    totals = {
        (rid, st): (n, pnl, held)
        for rid, st, n, pnl, held in (await session.execute(
            select(LabPosition.strategy_row_id, LabPosition.status,
                   func.count(),
                   func.coalesce(func.sum(LabPosition.exit_proceeds_usd
                                          - LabPosition.size_usd), 0),
                   func.coalesce(func.sum(func.coalesce(
                       LabPosition.last_open_value_usd,
                       LabPosition.size_usd)), 0))
            .where(LabPosition.strategy_row_id.in_(ids))
            .group_by(LabPosition.strategy_row_id, LabPosition.status)
        )).all()
    }
    by_row: dict = {
        r.id: {
            "open_value": Decimal(totals.get((r.id, "open"), (0, 0, 0))[2] or 0),
            "open": totals.get((r.id, "open"), (0, 0, 0))[0],
            "closed": totals.get((r.id, "closed"), (0, 0, 0))[0],
            "realised": Decimal(totals.get((r.id, "closed"), (0, 0, 0))[1] or 0),
            "trades": [],
        }
        for r in rows
    }
    for p in positions:
        e = by_row[p.strategy_row_id]
        if len(e["trades"]) < PER_CELL_TRADES:
            e["trades"].append({
                "id": str(p.id), "mint": p.mint_address, "status": p.status,
                "opened_at": p.opened_at.isoformat(),
                "closed_at": p.closed_at.isoformat() if p.closed_at else None,
                "size_usd": p.size_usd,
                "value": (p.exit_proceeds_usd if p.status == "closed"
                          else p.last_open_value_usd),
                "exec_multiple": p.last_exec_multiple,
                "exit_reason": p.exit_reason,
                "pnl": ((p.exit_proceeds_usd - p.size_usd)
                        if p.exit_proceeds_usd is not None else None),
            })
    cyc_by_row: dict = {}
    for c in cycles:
        cyc_by_row.setdefault(c.strategy_row_id, []).append(c)

    wallets = []
    for r in rows:
        mine = cyc_by_row.get(r.id, [])
        running = next((c for c in mine if c.reached_at is None), None)
        banked = [c for c in mine if c.reached_at is not None]
        ov = by_row[r.id]["open_value"]
        s_ = cspec.BY_ID.get(r.strategy_id)
        wallets.append({
            "strategy_id": r.strategy_id, "name": r.name, "status": r.status,
            "floor_usd": (float(next(c.value for c in s_.entry
                                     if c.feature == "liq")) if s_ else 0.0),
            "hypothesis": (s_.hypothesis if s_ else ""),
            "exit_text": (cspec.rules_json(s_)["exit_text"] if s_ else []),
            "checkpoint_label": (cspec.rules_json(s_)["checkpoint_label"]
                                 if s_ else ""),
            "size_usd": (s_.size_usd if s_ else None),
            "max_concurrent": (s_.max_concurrent if s_ else None),
            "closed_positions": by_row[r.id]["closed"],
            "realised_pnl": by_row[r.id]["realised"],
            "trades": by_row[r.id]["trades"],
            "entry_text": (cspec.rules_json(s_)["entry_text"] if s_ else []),
            "cash": r.cash, "open_value": ov, "equity": r.cash + ov,
            "open_positions": by_row[r.id]["open"],
            "cycles_banked": len(banked),
            "cycle_no": running.cycle_no if running else None,
            "base_usd": running.base_usd if running else None,
            "target_usd": running.target_usd if running else None,
            "last_realised": banked[0].realised_equity if banked else None,
        })
    # Ordered by FLOOR, never by equity. This is a dose-response curve and its
    # shape is the result; sorting by outcome would put the winner at the top
    # and destroy the only thing the experiment measures.
    wallets.sort(key=lambda w: w["floor_usd"])
    for i, w in enumerate(wallets, 1):
        w["rank"] = i

    return leaderboard._jsonable({
        "disclosure": DISCLOSURE,
        "activated": True,
        "wallets": wallets,
        "spec_version": cspec.SPEC_VERSION,
        "spec_hash": cspec.SPEC_HASH,
        "starting_equity": cspec.STARTING_EQUITY,
        "target_multiple": cspec.CYCLE_TARGET_MULTIPLE,
        "failure_floor": cspec.FAILURE_EQUITY_FLOOR,
        # Cycles COMPLETED, not cycles started: the running one has banked
        # nothing yet and counting it would overstate the record by one.
        "cycles_banked": len(banked),
        "current_cycle": ({
            "cycle_no": running.cycle_no, "base_usd": running.base_usd,
            "target_usd": running.target_usd,
            "started_at": running.started_at.isoformat(),
        } if running else None),
    })
