"""Read-only visibility into future real-wallet safety decisions."""

from __future__ import annotations

from fastapi import APIRouter, Query
from sqlalchemy import select

from app.api.deps import DbSession
from app.models.real_wallet_safety import RealWalletSafetyEvaluation

router = APIRouter(prefix="/real-wallet-safety", tags=["real-wallet-safety"])


@router.get("/evaluations/{mint_address}", summary="Read safety decisions for a mint")
async def evaluations(
    mint_address: str,
    session: DbSession,
    limit: int = Query(default=20, ge=1, le=100),
) -> dict[str, object]:
    """Audit read model only; it cannot trigger a quote, order, or wallet action."""
    rows = (
        (
            await session.execute(
                select(RealWalletSafetyEvaluation)
                .where(RealWalletSafetyEvaluation.mint_address == mint_address)
                .order_by(RealWalletSafetyEvaluation.evaluated_at.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return {
        "mint_address": mint_address,
        "items": [
            {
                "decision": row.decision,
                "evaluated_at": row.evaluated_at,
                "trade_size_usd": str(row.trade_size_usd),
                "policy_version": row.policy_version,
                "reason_codes": row.reason_codes,
                "market_snapshot_at": row.market_snapshot_at,
                "market_age_seconds": None
                if row.market_age_seconds is None
                else str(row.market_age_seconds),
                "buy_price_impact_pct": None
                if row.buy_price_impact_pct is None
                else str(row.buy_price_impact_pct),
                "sell_price_impact_pct": None
                if row.sell_price_impact_pct is None
                else str(row.sell_price_impact_pct),
                "round_trip_loss_usd": None
                if row.round_trip_loss_usd is None
                else str(row.round_trip_loss_usd),
                "round_trip_loss_pct": None
                if row.round_trip_loss_pct is None
                else str(row.round_trip_loss_pct),
                "provenance": row.provenance,
                "token_configuration": row.token_configuration,
            }
            for row in rows
        ],
    }
