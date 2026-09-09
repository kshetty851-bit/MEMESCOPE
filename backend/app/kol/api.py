"""The KOL Lab: a signal, its control, and the wallets it decided to follow.

Read-only. The board is `app/lab/board.py` and the trades view is
`app/lab/api.py`, both shared rather than copied.

`/wallets` exists so the ranking can be argued with rather than taken. A hit
rate on its own is unreadable — the base rate is served beside it, because if
being early into anything doubles a third of the time then 35% is noise.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Query
from sqlalchemy import select

from app.api.deps import DbSession
from app.kol import ranking
from app.kol import spec as kspec
from app.lab import board as shared
from app.lab.api import build_trades
from app.models.kol import KolWalletRank

router = APIRouter(prefix="/kol", tags=["kol"])

PER_CELL_TRADES = 60

DISCLOSURE = (
    "Research simulation. Two virtual $100 wallets, $10 a position and up to "
    "ten at once, each held exactly 30 minutes with no take-profit and no "
    "stop. They differ in ONE condition: KOL-FOLLOWED requires that a wallet "
    "we follow was among the coin's first buyers, KOL-CONTROL does not. "
    "The followed wallets were chosen by how often their early buys doubled "
    "within six hours, measured over the seven days BEFORE this tournament "
    "opened, and frozen at that moment — nothing after it touched the "
    "selection. That discipline is the whole design: pump.fun's own "
    "leaderboard ranks the past month's winners, which predicts nothing, and "
    "claimed $1M+ for wallets whose on-chain realised SOL was negative. "
    "A hit rate here says a wallet's coins DOUBLED from its entry, not that "
    "the wallet made money — peaks are not realisable. Compare every score "
    "against the base rate served beside it. If the two wallets finish level, "
    "the ranking is worthless, and that is a real answer. "
    "No real order was ever placed."
)


@router.get("/board")
async def board(session: DbSession) -> dict[str, Any]:
    out = await shared.build(
        session, registry=kspec, disclosure=DISCLOSURE,
        per_cell=PER_CELL_TRADES,
        axis=lambda s_: {"is_control": bool(s_ and s_.evidence == "CONTROL")},
        # Signal, then control. Never by outcome.
        order=lambda w: w["strategy_id"],
    )
    out["hold_minutes"] = round(kspec.TIME_EXIT_HOURS * 60)
    out["min_liquidity_usd"] = kspec.MIN_LIQUIDITY_USD
    return out


@router.get("/wallets")
async def wallets(session: DbSession) -> dict[str, Any]:
    """The frozen ranking, with the evidence that selected each wallet."""
    rows = list((await session.execute(
        select(KolWalletRank)
        .where(KolWalletRank.spec_version == kspec.SPEC_VERSION)
        .order_by(KolWalletRank.rank)
    )).scalars())

    # The live base rate, for scale. Recomputed rather than stored because it
    # is context for the reader, never an input to a decision.
    scored, base = await ranking.base_rate(session, as_of=datetime.now(UTC))

    return {
        "disclosure": DISCLOSURE,
        "frozen": bool(rows),
        "computed_at": rows[0].computed_at.isoformat() if rows else None,
        "min_early_buys": ranking.MIN_EARLY_BUYS,
        "hit_horizon_hours": ranking.HIT_HORIZON_HOURS,
        "hit_multiple": ranking.HIT_MULTIPLE,
        # What a score has to beat to mean anything.
        "base_rate": base,
        "base_rate_sample": scored,
        "wallets": [
            {"rank": r.rank, "wallet": r.wallet_address,
             "early_buys": r.early_buys, "hits": r.hits, "hit_rate": r.hit_rate}
            for r in rows
        ],
    }


@router.get("/trades")
async def trades(session: DbSession,
                 strategy_id: str | None = Query(default=None),
                 status: str | None = Query(default=None, pattern="^(open|closed)$"),
                 limit: int = Query(default=500, le=2000)) -> dict[str, Any]:
    return await build_trades(session, registry=kspec, disclosure=DISCLOSURE,
                              strategy_id=strategy_id, status=status, limit=limit)
