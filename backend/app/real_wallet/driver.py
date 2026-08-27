"""Turn the funded V6 strategies into at most one real BUY intent per tick.

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
from decimal import ROUND_DOWN, Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.models.lab import LabDecision
from app.models.real_wallet_execution import RealWalletLiveIntent
from app.real_wallet.allocations import Allocation, AllocationService
from app.real_wallet.autotrade import AutotradeSwitchService
from app.real_wallet.live_repository import LiveIntentRepository
from app.real_wallet.policy import (
    AutonomousExecutionPolicy,
    PolicyState,
    configured_entry_size_usd,
)
from app.real_wallet.sol_price import JupiterSolUsdPriceSource
from app.real_wallet.tx_inspect import lamports_from_sol

#: Lamports in one SOL. Named rather than inline so the conversion in
#: `equity_usd` reads as a unit change and not a magic number.
_LAMPORTS_PER_SOL = Decimal(1_000_000_000)

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
        """At most one BUY intent, across all funded strategies.

        STILL ONE INTENT PER TICK, and that is the whole reason this loops the
        way it does. The single-strategy version said "a loop here would turn a
        single bad minute into a whole book" — dividing the wallet between five
        strategies and then creating one intent EACH would have quietly made
        that exact loop, five times worse, while looking like the same throttle.
        So the loop finds the first strategy that can act, acts once, and stops.

        Which strategy gets the tick is decided by least-recently-served
        rotation, not by allocation size or alphabetical order. Ordering by
        anything correlated with the strategies themselves would let one of them
        take every tick while a rival never trades, and the difference between
        their records would then be an artefact of this function.
        """
        now = now or datetime.now(UTC)

        switch = await AutotradeSwitchService(self._session).state()
        if not switch.enabled:
            return DriverOutcome(0, "autotrade_switch_off")

        allocations = await AllocationService(self._session).enabled()
        if not allocations:
            return DriverOutcome(0, "no_strategy_nominated")

        wallet = settings.REAL_WALLET_PUBLIC_KEY.strip()
        if not wallet:
            return DriverOutcome(0, "wallet_not_configured")

        if settings.REAL_WALLET_ENTRY_SIZE_USD <= 0:
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

        # Priced here rather than after the policy check, because the size the
        # policy judges has to be the size actually intended. The growth ladder
        # is denominated in dollars and the wallet holds SOL, so there is no
        # equity figure — and therefore no stake — without this reading.
        sol_price = await self._sol_usd(now)
        if sol_price is None:
            # An unpriced entry is an entry nobody sized. Refuse rather than
            # guess: every limit this wallet has is written in dollars.
            return DriverOutcome(0, "sol_price_unavailable")

        # Total equity is read ONCE and divided, never read per strategy. Two
        # reads a few milliseconds apart would give two strategies two different
        # books to take their share of, and the shares would then not add up to
        # the wallet.
        total_equity_usd = (
            Decimal(balance_lamports) / _LAMPORTS_PER_SOL * sol_price
            + await repo.open_exposure_usd()
        )

        skipped: list[str] = []
        for allocation in await self._rotation_order(allocations):
            outcome = await self._try_strategy(
                allocation,
                repo=repo,
                wallet=wallet,
                now=now,
                total_equity_usd=total_equity_usd,
                sol_price=sol_price,
                balance_lamports=balance_lamports,
            )
            if outcome.created:
                return outcome
            skipped.append((allocation.strategy_id, outcome.skipped))

        # Every strategy declined. Report all of their reasons rather than the
        # first: "V6-06 had no candidate and V6-11 is at its allocation" is an
        # operator's answer, and the first reason alone is a guess at it.
        #
        # One strategy reports its reason BARE, with no id prefix. That is the
        # string an undivided wallet has always returned, and the caller reading
        # it should not have to learn a new format because a feature it is not
        # using now exists. The prefix appears only when it carries information.
        if len(skipped) == 1:
            return DriverOutcome(0, skipped[0][1])
        return DriverOutcome(0, " ".join(f"{sid}={why}" for sid, why in skipped))

    async def _try_strategy(
        self,
        allocation: Allocation,
        *,
        repo: LiveIntentRepository,
        wallet: str,
        now: datetime,
        total_equity_usd: Decimal,
        sol_price: Decimal,
        balance_lamports: int,
    ) -> DriverOutcome:
        """One strategy's turn. Returns created=1 only if it actually acted."""
        strategy_id = allocation.strategy_id

        # --- THIS STRATEGY'S SHARE ------------------------------------------
        # The ladder measures the strategy's OWN capital, not the wallet's. A
        # strategy holding 20% of a $1,000 book is running $200 and should
        # double its stake when ITS $200 becomes $400 — not when somebody
        # else's strategy doubles the wallet. Sizing every strategy off total
        # equity would have each of them growing on the others' results.
        strategy_equity = total_equity_usd * allocation.fraction
        entry_usd = configured_entry_size_usd(strategy_equity)
        if entry_usd is None or entry_usd <= 0:
            return DriverOutcome(0, "entry_size_not_configured")

        # --- THE ALLOCATION ITSELF ------------------------------------------
        # Deployed cost against the share. Untagged legacy positions count
        # toward no strategy (see `open_exposure_usd`), so this can only
        # under-state a strategy's usage, never over-state it — and an
        # under-stated usage is bounded by the global caps below regardless.
        deployed = await repo.open_exposure_usd(strategy_id=strategy_id)
        if deployed + entry_usd > strategy_equity:
            return DriverOutcome(0, "allocation_exhausted")

        # --- THE SERVER-OWNED BOUNDS, UNCHANGED AND GLOBAL -------------------
        # Asked, not reimplemented, and asked with the WHOLE book's numbers.
        # An allocation divides the wallet; it does not give any strategy its
        # own private set of caps. Five strategies at 20% each still share one
        # max-open-positions and one daily notional.
        decision = AutonomousExecutionPolicy().evaluate_canary_entry(
            requested_usd=entry_usd,
            state=PolicyState(
                open_positions=await repo.open_positions_count(),
                exposure_usd=await repo.open_exposure_usd(),
                daily_notional_usd=await self._notional_today(now),
                daily_realised_loss_usd=Decimal(0),
                daily_trades=await self._trades_today(now),
                wallet_balance_lamports=balance_lamports,
            ),
        )
        if not decision.allowed:
            return DriverOutcome(0, "policy:" + ",".join(decision.reason_codes))

        candidate = await self._next_candidate(strategy_id=strategy_id, now=now)
        if candidate is None:
            return DriverOutcome(0, "no_fresh_candidate")

        # Price the entry in the asset the wallet actually holds, and store it.
        # Quantised DOWN to whole lamports before conversion: rounding down
        # means the entry is at most the authorised size, never a lamport over.
        sol_amount = (entry_usd / sol_price).quantize(
            Decimal("1e-9"), rounding=ROUND_DOWN
        )
        lamports = lamports_from_sol(sol_amount)
        if lamports <= 0:
            return DriverOutcome(0, "entry_size_rounds_to_zero_lamports")

        intent = await repo.create_intent(
            idempotency_key=f"v6:{strategy_id}:{candidate}",
            mint_address=candidate,
            side="BUY",
            strategy_id=strategy_id,
            strategy_version=settings.REAL_WALLET_SAFETY_POLICY_VERSION,
            wallet_public_key=wallet,
            requested_usd=entry_usd,
            input_mint=settings.EXECUTION_SOL_MINT,
            output_mint=candidate,
            actual_input_amount_raw=lamports,
        )
        if intent is None:
            return DriverOutcome(0, "already_traded", candidate)

        logger.warning(
            "real_wallet_intent_created",
            mint=candidate,
            strategy=strategy_id,
            usd=str(entry_usd),
            allocation=str(allocation.fraction),
        )
        return DriverOutcome(1, None, candidate)

    async def _rotation_order(
        self, allocations: list[Allocation]
    ) -> list[Allocation]:
        """Least-recently-served first; a strategy that never traded goes first.

        Read from the intents themselves rather than kept as a cursor. A stored
        pointer would drift the moment an intent was created by anything else,
        and the intents are already the record of who was served when.
        """
        rows = await self._session.execute(
            select(
                RealWalletLiveIntent.strategy_id,
                func.max(RealWalletLiveIntent.created_at),
            ).group_by(RealWalletLiveIntent.strategy_id)
        )
        last_served = {sid: at for sid, at in rows.all() if sid}
        never = datetime.min.replace(tzinfo=UTC)
        return sorted(
            allocations,
            key=lambda a: (last_served.get(a.strategy_id, never), a.strategy_id),
        )

    async def _sol_usd(self, now: datetime) -> Decimal | None:
        """The wallet's own SOL/USD reading, or None. Never a guessed rate."""
        try:
            price = await JupiterSolUsdPriceSource().current(now=now)
        except Exception:  # noqa: BLE001 - an unpriced entry refuses
            return None
        if price is None or price.usd <= 0:
            return None
        if not price.is_fresh(
            now, max_age_seconds=settings.EXECUTION_SOL_PRICE_MAX_AGE_SECONDS
        ):
            return None
        return Decimal(str(price.usd))

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
