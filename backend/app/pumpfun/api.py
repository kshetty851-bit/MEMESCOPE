"""The copy lab in one request: the book, the ledger, and the lag.

Read-only. The COVERAGE numbers are the point of this payload — how many of the
leader's trades we managed to copy, and why we missed the rest. A copy lab that
reported only its own fills would look like a strategy; what decides whether
copying works is the gap between what he did and what we could do.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from sqlalchemy import func, select

from app.api.deps import DbSession
from app.lab import leaderboard
from app.models.lab import LabPosition, LabStrategy, LabTournament
from app.models.pumpfun import PumpfunSignal
from app.pumpfun import spec

router = APIRouter(prefix="/pumpfun", tags=["pumpfun"])

DISCLOSURE = (
    "Research simulation. One virtual $100 wallet mirroring the entries and "
    "exits of a single on-chain wallet, forward only — nothing the leader did "
    "before this lab started is ever copied. No real order was placed. "
    "Measured on chain over 30 days, this leader's profit was concentrated in "
    "ONE token out of 252; what is being tested is whether a follower can "
    "catch that, arriving minutes late at a hundredth of the size."
)


@router.get("/board")
async def board(session: DbSession) -> dict[str, Any]:
    t = (await session.execute(
        select(LabTournament).where(
            LabTournament.spec_version == spec.SPEC_VERSION)
    )).scalars().first()
    base = {
        "disclosure": DISCLOSURE,
        "spec_version": spec.SPEC_VERSION, "spec_hash": spec.SPEC_HASH,
        "leader_address": spec.LEADER_ADDRESS, "leader_label": spec.LEADER_LABEL,
        "starting_equity": spec.STARTING_EQUITY,
        "max_signal_age_seconds": spec.MAX_SIGNAL_AGE_SECONDS,
        "rules": spec.rules_json(spec.STRATEGIES[0]),
    }
    if t is None:
        return leaderboard._jsonable({**base, "activated": False,
                                      "signals": [], "positions": [],
                                      "coverage": {}})

    row = (await session.execute(
        select(LabStrategy).where(LabStrategy.tournament_id == t.id)
    )).scalars().first()
    signals = list((await session.execute(
        select(PumpfunSignal).where(PumpfunSignal.tournament_id == t.id)
        .order_by(PumpfunSignal.leader_at.desc()).limit(150)
    )).scalars())
    positions = list((await session.execute(
        select(LabPosition).where(LabPosition.strategy_row_id == row.id)
        .order_by(LabPosition.opened_at.desc()).limit(150)
    )).scalars())

    # Counted in the database, not from the 150 rows above: the page shows a
    # window, and a coverage figure computed from a window is a figure about
    # the window.
    by_outcome = dict((await session.execute(
        select(PumpfunSignal.outcome, func.count())
        .where(PumpfunSignal.tournament_id == t.id)
        .group_by(PumpfunSignal.outcome)
    )).all())
    actionable = sum(v for k, v in by_outcome.items()
                     if k != "before_watch_start")
    copied = by_outcome.get("opened", 0) + by_outcome.get("closed", 0)
    lag = (await session.execute(
        select(func.avg(func.extract(
            "epoch", PumpfunSignal.seen_at - PumpfunSignal.leader_at)))
        .where(PumpfunSignal.tournament_id == t.id,
               PumpfunSignal.acted.is_(True))
    )).scalar()

    open_value = sum((p.last_open_value_usd or p.size_usd)
                     for p in positions if p.status == "open")
    return leaderboard._jsonable({
        **base,
        "activated": True,
        "watching_from": t.valid_from.isoformat(),
        "strategy_id": row.strategy_id, "name": row.name, "status": row.status,
        "cash": row.cash, "open_value": open_value,
        "equity": row.cash + open_value,
        "coverage": {
            "signals_seen": sum(by_outcome.values()),
            "actionable": actionable,
            "copied": copied,
            "copied_pct": (round(100 * copied / actionable, 1)
                           if actionable else None),
            "by_outcome": by_outcome,
            "mean_lag_seconds": round(float(lag), 1) if lag is not None else None,
        },
        "signals": [{
            "signature": s.signature, "mint": s.mint_address, "side": s.side,
            "leader_sol": s.leader_sol,
            "leader_at": s.leader_at.isoformat(), "seen_at": s.seen_at.isoformat(),
            "lag_seconds": round((s.seen_at - s.leader_at).total_seconds(), 1),
            "acted": s.acted, "outcome": s.outcome,
        } for s in signals],
        "positions": [{
            "id": str(p.id), "mint": p.mint_address, "status": p.status,
            "opened_at": p.opened_at.isoformat(), "size_usd": p.size_usd,
            "open_value": p.last_open_value_usd,
            "exec_multiple": p.last_exec_multiple, "exit_reason": p.exit_reason,
            "pnl": ((p.exit_proceeds_usd - p.size_usd)
                    if p.exit_proceeds_usd is not None else None),
        } for p in positions],
    })
