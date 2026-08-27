"""`GET /api/v1/lab/*` — the V6 Strategy Lab scoreboard. Read-only, no write verb.

Every response is labelled RESEARCH SIMULATION. Lab equity is not Paper Wallet
equity, and the two must never be presented as the same number.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select

from app.api.deps import DbSession
from app.lab import leaderboard, spec
from app.models.token import DiscoveredToken
from app.models.lab import (
    LabDecision,
    LabEquityPoint,
    LabPosition,
    LabSnapshot,
    LabStrategy,
    LabTournament,
)

router = APIRouter(prefix="/lab", tags=["lab"])

# The book size is interpolated rather than written out: it said "$1,000" for as
# long as the book was $1,000 and would have gone on saying it afterwards.
DISCLOSURE = (
    "RESEARCH SIMULATION — NOT THE OFFICIAL PAPER WALLET, NOT REAL MONEY. Twenty "
    f"virtual ${spec.STARTING_EQUITY:,.0f} portfolios scoring frozen V6 hypotheses "
    "against a cash control, all fed by the one MEMESCOPE scanner. Equity is cash "
    "plus what the open book could be SOLD for, never plus what it cost. Historical "
    "figures shown beside a strategy are context from a closed dataset that six "
    "studies have already mined; they are not validation and are never merged with "
    "forward results."
)


async def _tournament(session) -> LabTournament:
    row = (await session.execute(
        select(LabTournament).where(LabTournament.spec_version == spec.SPEC_VERSION)
    )).scalars().first()
    if row is None:
        raise HTTPException(status_code=404, detail="V6 Strategy Lab is not activated")
    return row


@router.get("/board")
async def board(session: DbSession) -> dict[str, Any]:
    """The live leaderboard: twenty strategies, three leader badges, timings."""
    t = await _tournament(session)
    now = datetime.now(UTC)
    rows = await leaderboard.strategy_rows(session, tournament_id=t.id)
    rows.sort(key=lambda r: r["equity"], reverse=True)
    for i, r in enumerate(rows, 1):
        r["rank"] = i
    total_closed = sum(r["trades"] for r in rows)
    snap_taken = t.snapshot_taken_at is not None
    return leaderboard._jsonable({
        "disclosure": DISCLOSURE,
        "spec_version": t.spec_version, "spec_hash": t.spec_hash,
        "spec_immutable": True,
        # Served, not assumed by the client. The page hardcoded $1,000 in its
        # heading and kept saying it after the book became $100.
        "starting_equity": spec.STARTING_EQUITY,
        "valid_from": t.valid_from.isoformat(),
        "snapshot_at": t.snapshot_at.isoformat(),
        "snapshot_taken": snap_taken,
        "snapshot_taken_at": t.snapshot_taken_at.isoformat() if snap_taken else None,
        "elapsed_hours": (now - t.valid_from).total_seconds() / 3600,
        "hours_to_snapshot": max(0.0, (t.snapshot_at - now).total_seconds() / 3600),
        "status": t.status,
        "real_money_enabled": False,
        "total_closed_trades": total_closed,
        "overall_confidence": leaderboard.confidence(total_closed),
        "leaders": leaderboard.leaders(rows),
        "strategies": rows,
        # The frozen rulebook, served rather than duplicated in the client, so
        # a reader checking the page against the report is reading the same
        # registry the engine judges with.
        "rulebook": [spec.rules_json(s) for s in spec.STRATEGIES],
    })


@router.get("/strategies/{strategy_id}")
async def strategy_detail(strategy_id: str, session: DbSession) -> dict[str, Any]:
    """Frozen rules, historical context and caveats, plus the live book."""
    s = spec.BY_ID.get(strategy_id.upper())
    if s is None:
        raise HTTPException(status_code=404, detail=f"unknown strategy {strategy_id}")
    # Scoped to the current record. `strategy_id` alone matches one row PER
    # tournament, so once V6.1 existed this returned whichever the database
    # happened to hand back first — V6-04 at $1,000 or V6-04 at $100, silently.
    t = await _tournament(session)
    row = (await session.execute(
        select(LabStrategy).where(LabStrategy.tournament_id == t.id,
                                  LabStrategy.strategy_id == s.id)
    )).scalars().first()
    if row is None:
        raise HTTPException(status_code=404, detail="V6 Strategy Lab is not activated")

    positions = list((await session.execute(
        select(LabPosition).where(LabPosition.strategy_row_id == row.id)
        .order_by(LabPosition.opened_at.desc()).limit(200)
    )).scalars())
    skips = list((await session.execute(
        select(LabDecision.skip_reason, LabDecision.id)
        .where(LabDecision.strategy_row_id == row.id, LabDecision.eligible.is_(False))
    )).all())
    reasons: dict[str, int] = {}
    for reason, _ in skips:
        reasons[reason or "unknown"] = reasons.get(reason or "unknown", 0) + 1
    curve = list((await session.execute(
        select(LabEquityPoint.captured_at, LabEquityPoint.equity, LabEquityPoint.cash,
               LabEquityPoint.open_value)
        .where(LabEquityPoint.strategy_row_id == row.id)
        .order_by(LabEquityPoint.captured_at)
    )).all())
    all_rows = await leaderboard.strategy_rows(session, tournament_id=t.id)
    mine = next((r for r in all_rows if r["strategy_id"] == s.id), {})
    return leaderboard._jsonable({
        "disclosure": DISCLOSURE,
        "strategy": row.rules,
        "stats": mine,
        "historical_warning": (
            "HISTORICALLY INTERESTING — HIGH OVERFIT RISK. Historical profit is not "
            "validation: it comes from a dataset six prior studies already mined, and "
            "this strategy's gate changed prevalence across that sample."
            if s.overfit_risk == "HIGH" else None
        ),
        "skip_reasons": dict(sorted(reasons.items(), key=lambda kv: -kv[1])),
        "decisions_total": len(skips) + len(positions),
        "equity_curve": [{"at": a.isoformat(), "equity": e, "cash": c, "open_value": o}
                         for a, e, c, o in curve],
        "positions": [{
            "mint": p.mint_address, "opened_at": p.opened_at.isoformat(),
            "status": p.status, "size_usd": p.size_usd,
            "open_value": p.last_open_value_usd, "exec_multiple": p.last_exec_multiple,
            "peak_exec_multiple": p.peak_exec_multiple,
            "closed_at": p.closed_at.isoformat() if p.closed_at else None,
            "exit_reason": p.exit_reason, "exit_proceeds_usd": p.exit_proceeds_usd,
            "pnl": ((p.exit_proceeds_usd - p.size_usd) if p.exit_proceeds_usd is not None
                    else None),
            "route_state": p.route_state, "reached_125": p.reached_125,
            "reached_150": p.reached_150, "reached_200": p.reached_200,
            "partial_done": p.partial_done,
        } for p in positions],
    })


@router.get("/snapshots")
async def snapshots(session: DbSession,
                    label: str | None = Query(default=None)) -> dict[str, Any]:
    """Immutable frozen leaderboards. The 24-hour one is labelled `24H`."""
    t = await _tournament(session)
    q = select(LabSnapshot).where(LabSnapshot.tournament_id == t.id)
    if label:
        q = q.where(LabSnapshot.label == label.upper())
    rows = list((await session.execute(q.order_by(LabSnapshot.boundary_at))).scalars())
    return {
        "disclosure": DISCLOSURE,
        "snapshots": [{"label": r.label, "boundary_at": r.boundary_at.isoformat(),
                       "taken_at": r.taken_at.isoformat(),
                       "elapsed_hours": r.elapsed_hours, "payload": r.payload}
                      for r in rows],
    }


@router.get("/decisions")
async def decisions(session: DbSession,
                    strategy_id: str | None = Query(default=None),
                    eligible: bool | None = Query(default=None),
                    limit: int = Query(default=100, le=500)) -> dict[str, Any]:
    """The decision ledger — skips included, because a refusal is evidence."""
    t = await _tournament(session)
    q = (
        select(LabDecision)
        .join(LabStrategy, LabStrategy.id == LabDecision.strategy_row_id)
        .where(LabStrategy.tournament_id == t.id)
        .order_by(LabDecision.checkpoint_at.desc())
        .limit(limit)
    )
    if strategy_id:
        q = q.where(LabDecision.strategy_id == strategy_id.upper())
    if eligible is not None:
        q = q.where(LabDecision.eligible.is_(eligible))
    rows = list((await session.execute(q)).scalars())
    return leaderboard._jsonable({
        "disclosure": DISCLOSURE,
        "decisions": [{
            "strategy_id": r.strategy_id, "mint": r.mint_address,
            "checkpoint_at": r.checkpoint_at.isoformat(),
            "checkpoint_minutes": r.checkpoint_minutes,
            "eligible": r.eligible, "skip_reason": r.skip_reason,
            "route_state": r.route_state, "features": r.features,
        } for r in rows],
    })

@router.get("/trades")
async def trades(session: DbSession,
                 strategy_id: str | None = Query(default=None),
                 status: str | None = Query(default=None, pattern="^(open|closed)$"),
                 limit: int = Query(default=500, le=2000)) -> dict[str, Any]:
    """Every position the Lab holds or has closed, with its full mint address.

    The mint is returned unabbreviated on purpose: the point of this view is
    that a reader can copy the contract address and check the token against the
    market themselves, rather than taking the Lab's word for it.
    """
    # Scoped to the current record. Positions carry a bare `strategy_id`, so
    # without the join this listed V6's $1,000 trades alongside V6.1's $100 ones
    # under one heading, which is the same book twice at two different sizes.
    t = await _tournament(session)
    q = (
        select(LabPosition, DiscoveredToken.symbol, DiscoveredToken.name)
        .join(LabStrategy, LabStrategy.id == LabPosition.strategy_row_id)
        .outerjoin(DiscoveredToken, DiscoveredToken.id == LabPosition.token_id)
        .where(LabStrategy.tournament_id == t.id)
        .order_by(LabPosition.opened_at.desc())
        .limit(limit)
    )
    if strategy_id:
        q = q.where(LabPosition.strategy_id == strategy_id.upper())
    if status:
        q = q.where(LabPosition.status == status)
    rows = list((await session.execute(q)).all())

    names = {r.strategy_id: r.name for r in
             (await session.execute(select(LabStrategy))).scalars()}

    out = []
    for pos, symbol, token_name in rows:
        realised = ((pos.exit_proceeds_usd - pos.size_usd)
                    if pos.exit_proceeds_usd is not None else None)
        value = (pos.exit_proceeds_usd if pos.status == "closed"
                 else (pos.last_open_value_usd if pos.last_open_value_usd is not None
                       else pos.size_usd))
        out.append({
            "strategy_id": pos.strategy_id,
            "strategy_name": names.get(pos.strategy_id),
            # The full contract address, never truncated.
            "mint": pos.mint_address,
            "symbol": symbol, "token_name": token_name,
            "status": pos.status,
            "opened_at": pos.opened_at.isoformat(),
            "closed_at": pos.closed_at.isoformat() if pos.closed_at else None,
            "held_hours": (((pos.closed_at or pos.last_evaluated_at or pos.opened_at)
                            - pos.opened_at).total_seconds() / 3600),
            "size_usd": pos.size_usd,
            "entry_price": pos.entry_price,
            "entry_liquidity_usd": pos.entry_liquidity_usd,
            "current_value_usd": value,
            "unrealised_pnl": (None if pos.status == "closed"
                               else (value - pos.size_usd if value is not None else None)),
            "realised_pnl": realised,
            "exec_multiple": pos.last_exec_multiple,
            "peak_exec_multiple": pos.peak_exec_multiple,
            "exit_reason": pos.exit_reason,
            "exit_proceeds_usd": pos.exit_proceeds_usd,
            "route_state": pos.route_state,
            "reached_125": pos.reached_125,
            "reached_150": pos.reached_150,
            "reached_200": pos.reached_200,
            "partial_done": pos.partial_done,
            "entry_source": pos.entry_source,
        })
    return leaderboard._jsonable({
        "disclosure": DISCLOSURE,
        "total": len(out),
        "open": sum(1 for t in out if t["status"] == "open"),
        "closed": sum(1 for t in out if t["status"] == "closed"),
        "trades": out,
    })
