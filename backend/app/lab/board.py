"""One compound-ratchet board, served for whichever registry asked for it.

Depth, Momentum and Social are the same page with a different x-axis, and this
was copied between them twice before it was shared. Read-only: nothing here
recomputes a figure the engine owns, for the same reason the Lab's API does
not — a second implementation is a second answer, and the first time either
changed they would disagree.

`axis` contributes the columns that only one experiment has (Depth's liquidity
floor), and `order` decides how the board reads. Both belong to the caller: a
dose-response curve sorted by outcome stops being a curve, and a leaderboard
sorted by rule id stops being a leaderboard.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Callable

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.lab import leaderboard
from app.models.compound import CompoundCycle
from app.models.lab import LabPosition, LabStrategy, LabTournament


async def build(
    session: AsyncSession, *, registry: Any, disclosure: str,
    per_cell: int = 60,
    axis: Callable[[Any], dict] | None = None,
    order: Callable[[dict], Any] | None = None,
) -> dict[str, Any]:
    # `target_multiple` is read with a default because a registry may run no
    # ratchet at all (fivemin-2.0.0 sets `CYCLE_ENABLED = False`). Absent means
    # "this experiment has no target", which is not the same as a target of
    # zero — so it is served as null and the page omits the column.
    t = (await session.execute(
        select(LabTournament).where(
            LabTournament.spec_version == registry.SPEC_VERSION)
    )).scalars().first()
    if t is None:
        return {"disclosure": disclosure, "activated": False,
                "spec_version": registry.SPEC_VERSION, "spec_hash": registry.SPEC_HASH,
                "starting_equity": registry.STARTING_EQUITY,
                "target_multiple": getattr(registry, "CYCLE_TARGET_MULTIPLE", None),
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
        .order_by(LabPosition.opened_at.desc()).limit(per_cell * 20)
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
        if len(e["trades"]) < per_cell:
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
        s_ = registry.BY_ID.get(r.strategy_id)
        wallets.append({
            "strategy_id": r.strategy_id, "name": r.name, "status": r.status,
            "hypothesis": (s_.hypothesis if s_ else ""),
            "exit_text": (registry.rules_json(s_)["exit_text"] if s_ else []),
            "checkpoint_label": (registry.rules_json(s_)["checkpoint_label"]
                                 if s_ else ""),
            "size_usd": (s_.size_usd if s_ else None),
            "max_concurrent": (s_.max_concurrent if s_ else None),
            "closed_positions": by_row[r.id]["closed"],
            "realised_pnl": by_row[r.id]["realised"],
            "trades": by_row[r.id]["trades"],
            "entry_text": (registry.rules_json(s_)["entry_text"] if s_ else []),
            "cash": r.cash, "open_value": ov, "equity": r.cash + ov,
            "open_positions": by_row[r.id]["open"],
            "cycles_banked": len(banked),
            "cycle_no": running.cycle_no if running else None,
            "base_usd": running.base_usd if running else None,
            "target_usd": running.target_usd if running else None,
            "last_realised": banked[0].realised_equity if banked else None,
        })
    # Sorted by the CALLER, because how a board reads is the experiment's
    # business and not this function's. Depth is a dose-response curve and must
    # read low floor to high; sorting it by equity would put the winner on top
    # and destroy the only thing it measures.
    if axis:
        for w in wallets:
            w.update(axis(registry.BY_ID.get(w["strategy_id"])))
    if order:
        wallets.sort(key=order)
    for i, w in enumerate(wallets, 1):
        w["rank"] = i

    return leaderboard._jsonable({
        "disclosure": disclosure,
        "activated": True,
        "wallets": wallets,
        "spec_version": registry.SPEC_VERSION,
        "spec_hash": registry.SPEC_HASH,
        # When this tournament was frozen. Served so a page can show how long
        # it has been running: a result is unreadable without knowing whether
        # it took two hours or two weeks to happen.
        "valid_from": t.valid_from.isoformat(),
        "starting_equity": registry.STARTING_EQUITY,
        "target_multiple": getattr(registry, "CYCLE_TARGET_MULTIPLE", None),
        "failure_floor": registry.FAILURE_EQUITY_FLOOR,
        # No board-level `cycles_banked` or `current_cycle`. They were carried
        # here from the single-wallet Compound Lab, where they mean something,
        # and on a multi-wallet board they silently reported the LAST wallet in
        # the loop as if it were the whole experiment. Nothing read them.
        # Each wallet carries its own, which is the only honest place for them.
    })
