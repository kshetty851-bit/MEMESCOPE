"""CPY-01 and CPY-02 side by side — the only way either number means anything."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from sqlalchemy import select

from app.api.deps import DbSession
from app.copycontrol import spec as ccspec
from app.lab import board as shared, leaderboard

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


#: The bar, fixed BEFORE the data arrives. Written here rather than decided
#: later because every false edge on this platform came from a threshold chosen
#: after seeing the result.
MIN_CLOSED_TRADES = 25


@router.get("/comparison")
async def comparison(session: DbSession) -> dict[str, Any]:
    """CPY-01 against CPY-02, and whether the difference means anything yet.

    Only trades opened after the CONTROL started are counted on either side.
    CPY-01 traded for days before CPY-02 existed — including the 4.8x — and
    those trades have no control and never will, so including them would
    compare one arm's whole life against the other's fraction of it.

    The verdict is deliberately hard to earn. It stays `not_enough_data` below
    25 closed trades, and a signal that only wins WITH its single best trade is
    reported as `carried_by_one_trade` rather than as a win: on four trades
    CPY-01 showed +52% a mean that became -22.6% with one trade removed, and
    that is the shape every false edge here has had.
    """
    from decimal import Decimal

    from sqlalchemy import func

    from app.models.lab import LabPosition, LabStrategy, LabTournament
    from app.pumpfun import spec as pspec

    control_t = (await session.execute(
        select(LabTournament).where(
            LabTournament.spec_version == ccspec.SPEC_VERSION)
    )).scalars().first()
    if control_t is None:
        return {"activated": False, "bar": {"min_closed_trades": MIN_CLOSED_TRADES},
                "arms": [], "verdict": "control_not_started"}
    since = control_t.valid_from

    async def arm(spec_version: str, role: str) -> dict[str, Any]:
        row = (await session.execute(
            select(LabStrategy).join(
                LabTournament, LabTournament.id == LabStrategy.tournament_id
            ).where(LabTournament.spec_version == spec_version)
        )).scalars().first()
        if row is None:
            return {"role": role, "present": False}
        pnls = [p for p in (await session.execute(
            select(LabPosition.exit_proceeds_usd - LabPosition.size_usd)
            .where(LabPosition.strategy_row_id == row.id,
                   LabPosition.status == "closed",
                   LabPosition.opened_at >= since)
        )).scalars() if p is not None]
        open_value = Decimal(await session.scalar(
            select(func.coalesce(func.sum(func.coalesce(
                LabPosition.last_open_value_usd, LabPosition.size_usd)), 0))
            .where(LabPosition.strategy_row_id == row.id,
                   LabPosition.status == "open")
        ) or 0)
        total = sum(pnls) if pnls else Decimal(0)
        best = max(pnls) if pnls else Decimal(0)
        return {
            "role": role, "present": True,
            "strategy_id": row.strategy_id, "name": row.name,
            "cash": row.cash, "open_value": open_value,
            "equity": row.cash + open_value,
            "closed_trades": len(pnls),
            "realised_pnl": total,
            # The test that matters. A strategy whose whole result is one trade
            # has not been shown to work; it has been shown to have had a trade.
            "realised_pnl_excluding_best": (total - best) if pnls else Decimal(0),
            "best_trade_pnl": best if pnls else None,
        }

    signal = await arm(pspec.SPEC_VERSION, "signal")
    control = await arm(ccspec.SPEC_VERSION, "control")

    n = min(signal.get("closed_trades", 0), control.get("closed_trades", 0))
    if n < MIN_CLOSED_TRADES:
        verdict, detail = "not_enough_data", (
            f"{n} paired closed trades of {MIN_CLOSED_TRADES}. Nothing here is "
            f"a result yet, in either direction."
        )
    else:
        gap = signal["realised_pnl"] - control["realised_pnl"]
        gap_ex = (signal["realised_pnl_excluding_best"]
                  - control["realised_pnl_excluding_best"])
        if gap <= 0:
            verdict, detail = "control_matches_or_wins", (
                "Copying the leader did not beat buying at random at the same "
                "moments. That is a real answer."
            )
        elif gap_ex <= 0:
            verdict, detail = "carried_by_one_trade", (
                "Ahead of its control, but not once its single best trade is "
                "removed. On this platform that shape has always been luck."
            )
        else:
            verdict, detail = "signal_beats_control", (
                "Ahead of its control, and still ahead with its best trade "
                "removed."
            )

    return leaderboard._jsonable({
        "activated": True,
        "since": since.isoformat(),
        "bar": {"min_closed_trades": MIN_CLOSED_TRADES,
                "must_survive_dropping_best_trade": True},
        "arms": [signal, control],
        "paired_closed_trades": n,
        "verdict": verdict,
        "verdict_detail": detail,
        "disclosure": DISCLOSURE,
    })
