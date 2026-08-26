"""Turn a nominated V6 strategy into at most one real BUY intent per tick.

The binding is deliberately narrow: the real wallet trades **what the Lab
strategy already decided to trade**, read from `lab_decisions`. It does not
re-derive candidates, re-evaluate features, or hold a rule of its own. That
matters for two reasons — the paper record and the real record then describe the
same decisions, and there is exactly one place where entry logic lives.

## Everything here is a refusal

The driver's job is mostly to decline. It runs only when the operator's switch
is on, only on the strategy they nominated, only within the canary bounds the
server owns, and only on a mint this wallet has never traded. `AutonomousExecutionPolicy`
remains the authority on size and count; this asks it rather than reimplementing
it, because two places that both decide how much to spend will eventually
disagree.

It creates intents. It does not assemble orders, sign, or submit — those are the
lifecycle's, and each has its own barrier.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.models.lab import LabDecision
from app.models.real_wallet_execution import RealWalletLiveIntent
from app.real_wallet.autotrade import AutotradeSwitchService
from app.real_wallet.live_repository import LiveIntentRepository
from app.real_wallet.policy import AutonomousExecutionPolicy, PolicyState

logger = get_logger(__name__)

#: How far back a Lab decision may be and still be actionable. A decision the
#: Lab made an hour ago describes a market that no longer exists, and acting on
#: it would be trading a stale opinion rather than a current one.
MAX_DECISION_AGE = timedelta(minutes=10)


@dataclass(frozen=True, slots=True)
class DriverOutcome:
    created: int
    skipped: str | None = None
    mint: str | None = None

    def as_dict(self) -> dict:
        return {"created": self.created, "skipped": self.skipped, "mint": self.mint}


class RealWalletDriver:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def tick(self, *, now: datetime | None = None) -> DriverOutcome:
        now = now or datetime.now(UTC)

        switch = await AutotradeSwitchService(self._session).state()
        if not switch.enabled:
            return DriverOutcome(0, "autotrade_switch_off")
        if not switch.nominated_strategy:
            return DriverOutcome(0, "no_strategy_nominated")

        wallet = settings.REAL_WALLET_PUBLIC_KEY.strip()
        if not wallet:
            return DriverOutcome(0, "wallet_not_configured")

        entry_usd = settings.REAL_WALLET_ENTRY_SIZE_USD
        if entry_usd <= 0:
            # Zero means nobody decided. A fallback size is a size that ships
            # whatever the fallback was.
            return DriverOutcome(0, "entry_size_not_configured")

        repo = LiveIntentRepository(self._session)
        if await repo.active_kill_switches():
            return DriverOutcome(0, "kill_switch_active")

        # Measured, not assumed. `evaluate_canary_entry` refuses an unreadable
        # balance on purpose — the ceiling exists to keep the canary tiny, and a
        # wallet nobody measured has not been shown to be tiny. An RPC failure
        # is therefore a skip, never a trade.
        balance_lamports = await self._wallet_lamports(wallet)
        if balance_lamports is None:
            return DriverOutcome(0, "wallet_balance_unreadable")

        # The server-owned bounds, asked rather than reimplemented.
        open_positions = await repo.open_positions_count()
        decision = AutonomousExecutionPolicy().evaluate_canary_entry(
            requested_usd=entry_usd,
            state=PolicyState(
                open_positions=open_positions,
                exposure_usd=Decimal(open_positions) * entry_usd,
                daily_notional_usd=await self._notional_today(now),
                daily_realised_loss_usd=Decimal(0),
                daily_trades=await self._trades_today(now),
                wallet_balance_lamports=balance_lamports,
            ),
        )
        if not decision.allowed:
            return DriverOutcome(0, "policy:" + ",".join(decision.reason_codes))

        candidate = await self._next_candidate(
            strategy_id=switch.nominated_strategy, now=now
        )
        if candidate is None:
            return DriverOutcome(0, "no_fresh_candidate")

        # One intent per tick, deliberately. A loop here would turn a single
        # bad minute into a whole book.
        intent = await repo.create_intent(
            idempotency_key=f"v6:{switch.nominated_strategy}:{candidate}",
            mint_address=candidate,
            side="BUY",
            strategy_id=switch.nominated_strategy,
            strategy_version=settings.REAL_WALLET_SAFETY_POLICY_VERSION,
            wallet_public_key=wallet,
            requested_usd=entry_usd,
            input_mint=settings.JUPITER_USDC_MINT,
            output_mint=candidate,
        )
        if intent is None:
            return DriverOutcome(0, "already_traded", candidate)

        logger.warning("real_wallet_intent_created", mint=candidate,
                       strategy=switch.nominated_strategy, usd=str(entry_usd))
        return DriverOutcome(1, None, candidate)

    async def _wallet_lamports(self, wallet: str) -> int | None:
        """Chain balance in lamports, or None when it could not be read."""
        from app.real_wallet.balance import ExecutionWalletBalanceService
        from app.real_wallet.network import verify_wallet_network
        from app.real_wallet.tx_inspect import lamports_from_sol
        from app.services.rpc.standard import StandardSolanaRPC

        try:
            rpc = StandardSolanaRPC(rpc_url=settings.REAL_WALLET_RPC_URL)
            async with rpc:
                status = await verify_wallet_network(
                    rpc, network=settings.REAL_WALLET_NETWORK
                )
                if not status.verified:
                    return None
                got = await ExecutionWalletBalanceService(rpc).get_sol_balance(wallet)
                return lamports_from_sol(Decimal(str(got.sol)))
        except Exception as exc:  # pragma: no cover - unreadable chain is a skip
            logger.warning("real_wallet_balance_unreadable", error=str(exc)[:80])
            return None

    async def _next_candidate(self, *, strategy_id: str, now: datetime) -> str | None:
        """The most recent mint this strategy chose and this wallet has not traded."""
        cutoff = now - MAX_DECISION_AGE
        traded = select(RealWalletLiveIntent.mint_address)
        rows = await self._session.execute(
            select(LabDecision.mint_address)
            .where(
                LabDecision.strategy_id == strategy_id.upper(),
                LabDecision.eligible.is_(True),
                LabDecision.checkpoint_at >= cutoff,
                LabDecision.mint_address.not_in(traded),
            )
            .order_by(LabDecision.checkpoint_at.desc())
            .limit(1)
        )
        return rows.scalars().first()

    async def _trades_today(self, now: datetime) -> int:
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        rows = await self._session.execute(
            select(RealWalletLiveIntent.id).where(
                RealWalletLiveIntent.created_at >= start
            )
        )
        return len(rows.scalars().all())

    async def _notional_today(self, now: datetime) -> Decimal:
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        rows = await self._session.execute(
            select(RealWalletLiveIntent.requested_usd).where(
                RealWalletLiveIntent.created_at >= start
            )
        )
        return sum((v for v in rows.scalars() if v), Decimal(0))
