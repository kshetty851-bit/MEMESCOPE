"""Read-only visibility into future real-wallet safety decisions."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Query
from sqlalchemy import select

from app.api.deps import DbSession
from app.core.config import settings
from app.models.real_wallet_execution import RealWalletKillSwitch
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


@router.get("/execution-posture", summary="Whether execution can happen at all")
async def execution_posture(session: DbSession) -> dict[str, object]:
    """The Execution Vault's only source. Read-only, and structurally so.

    It reports *posture* — can this platform execute right now — and nothing
    that would help anyone execute. There is no balance here, no signer
    material, no public key, no transport detail, and no verb but GET. The
    richer `/real-wallet/status` read stays admin-only and untouched.

    ── WHY A SEPARATE STATE MACHINE ────────────────────────────────────────

    The settings alone can express contradictions — a mode of `live` with
    execution disabled, a kill switch active while everything else looks
    ready — and a panel that rendered each flag independently would let a
    reader assemble an optimistic reading out of true parts. So the states
    are ordered by severity and the **most restrictive wins**:

        HALTED    a kill switch is active. Nothing else matters.
        LOCKED    execution is disabled, or the mode cannot execute.
        ARMED     an order could be prepared, but not submitted.
        UNLOCKED  submission is possible.
        UNKNOWN   the posture could not be established.

    `UNLOCKED` is deliberately the hardest to reach: it requires the mode to
    be `live`, execution enabled, *and* no kill switch — so a half-configured
    deployment reads LOCKED rather than as something in between.
    """
    now = datetime.now(UTC)
    try:
        switches = (
            (await session.execute(select(RealWalletKillSwitch))).scalars().all()
        )
    except Exception:
        return {
            "state": "UNKNOWN",
            "detail": "The kill-switch record could not be read.",
            "observed_at": now,
            "sourced": False,
        }

    active = [row for row in switches if row.active]
    mode = settings.REAL_WALLET_EXECUTION_MODE
    enabled = bool(settings.REAL_WALLET_EXECUTION_ENABLED)
    autotrade = bool(settings.REAL_WALLET_AUTOTRADE_ENABLED)

    if active:
        state = "HALTED"
        detail = "A kill switch is active. Execution is stopped regardless of configuration."
    elif mode == "disabled" or not enabled:
        state = "LOCKED"
        detail = (
            "Execution is disabled. No order can be prepared, signed or submitted."
        )
    elif mode == "dry_run":
        state = "LOCKED"
        detail = "Dry run only: decisions are recorded and nothing can be submitted."
    elif mode == "armed":
        state = "ARMED"
        detail = "An order could be prepared and audited, but not submitted."
    elif mode == "live":
        state = "UNLOCKED"
        detail = "Submission is possible."
    else:  # pragma: no cover - Literal keeps this unreachable
        state = "UNKNOWN"
        detail = "The execution mode was not recognised."

    return {
        "state": state,
        "detail": detail,
        "mode": mode,
        "execution_enabled": enabled,
        "autotrade_enabled": autotrade,
        "network": settings.REAL_WALLET_NETWORK,
        "kill_switches": [
            {
                "kind": row.kind,
                "active": row.active,
                "reason": row.reason,
                "activated_at": row.activated_at,
            }
            for row in switches
        ],
        "active_kill_switches": len(active),
        "observed_at": now,
        "sourced": True,
    }
