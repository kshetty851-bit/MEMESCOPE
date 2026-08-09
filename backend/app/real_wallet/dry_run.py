"""Autonomous real-wallet dry-run: signal -> safety -> policy -> V2 order -> audit.

This module has no signer import and no transaction-submission capability.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from solders.keypair import Keypair
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.radar import RadarToken
from app.paper import eligibility
from app.paper.models import Candidate
from app.paper.strategy import registry
from app.radar.repository import RadarRepository
from app.real_wallet.jupiter_v2 import RealWalletJupiterV2Client
from app.real_wallet.policy import AutonomousExecutionPolicy
from app.real_wallet.repository import RealWalletExecutionRepository
from app.real_wallet_safety.service import RealWalletSafetyGate, SafetyDecision
from app.repositories.market import MarketSnapshotRepository
from app.repositories.token import TokenRepository

USDC_DECIMALS = 6
REASON_ORDER_UNAVAILABLE = "JUPITER_V2_ORDER_UNAVAILABLE"
REASON_ORDER_INVALID = "JUPITER_V2_ORDER_INVALID"
REASON_STRATEGY_DECLINED = "STRATEGY_DECLINED"


@dataclass(frozen=True, slots=True)
class DryRunOutcome:
    mode: str
    evaluated: int
    strategy_signals: int
    safety_allowed: int
    safety_blocked: int
    policy_allowed: int
    policy_blocked: int
    would_buy: int
    would_sell: int
    hypothetical_exposure_usd: Decimal
    skipped: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "mode": self.mode,
            "evaluated": self.evaluated,
            "strategy_signals": self.strategy_signals,
            "safety_allowed": self.safety_allowed,
            "safety_blocked": self.safety_blocked,
            "policy_allowed": self.policy_allowed,
            "policy_blocked": self.policy_blocked,
            "would_buy": self.would_buy,
            "would_sell": self.would_sell,
            "hypothetical_exposure_usd": str(self.hypothetical_exposure_usd),
            "skipped": self.skipped,
        }


class RealWalletDryRunService:
    """Runs the published V1 entry signal through independent safety/policy gates."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        safety_gate: RealWalletSafetyGate | None = None,
        jupiter: RealWalletJupiterV2Client | None = None,
    ) -> None:
        self._session = session
        self._safety = safety_gate or RealWalletSafetyGate(session)
        self._jupiter = jupiter or RealWalletJupiterV2Client()
        self._repository = RealWalletExecutionRepository(session)
        self._market = MarketSnapshotRepository(session)
        self._radar = RadarRepository(session)

    async def review(self, *, now: datetime) -> DryRunOutcome:
        """Evaluate only in explicit dry-run mode; disabled performs zero I/O/writes."""
        if settings.REAL_WALLET_EXECUTION_MODE != "dry_run":
            return DryRunOutcome(
                mode=settings.REAL_WALLET_EXECUTION_MODE,
                evaluated=0,
                strategy_signals=0,
                safety_allowed=0,
                safety_blocked=0,
                policy_allowed=0,
                policy_blocked=0,
                would_buy=0,
                would_sell=0,
                hypothetical_exposure_usd=Decimal(0),
                skipped="execution_mode_disabled",
            )

        entries = await self._radar.list_entries(
            category=None,
            active_only=True,
            sort="score",
            limit=settings.REAL_WALLET_DRY_RUN_CANDIDATE_LIMIT,
            offset=0,
        )
        signals = await self._strategy_signals(entries, now=now)
        safety_allowed = safety_blocked = policy_allowed = policy_blocked = would_buy = 0
        state = await self._repository.policy_state(now=now)
        requested = settings.REAL_WALLET_MAX_TRADE_USD
        policy = AutonomousExecutionPolicy()
        # Jupiter V2 requires a valid `taker` public key to construct an
        # order. This keypair lives only in this review call: its private
        # bytes are never stored, configured, logged, serialized, or used to
        # sign. The returned public address is supplied only to `/order`.
        taker = _ephemeral_dry_run_taker_public_key()

        for rank, _row, candidate, symbol in signals:
            safety = await self._safety.evaluate(
                mint_address=candidate.mint_address, trade_size_usd=requested, now=now
            )
            base = self._base_values(
                symbol=symbol,
                candidate=candidate,
                rank=rank,
                now=now,
                safety=safety,
                requested=requested,
            )
            if safety.decision != "ALLOW":
                await self._record(base, status="BLOCKED", reasons=safety.reason_codes)
                safety_blocked += 1
                continue
            safety_allowed += 1

            policy_decision = policy.evaluate_entry(requested_usd=requested, state=state)
            if not policy_decision.allowed:
                await self._record(
                    base, status="BLOCKED", reasons=policy_decision.reason_codes
                )
                policy_blocked += 1
                continue
            policy_allowed += 1
            if safety.token_decimals is None:
                await self._record(base, status="BLOCKED", reasons=(REASON_ORDER_INVALID,))
                continue

            try:
                buy = await self._jupiter.order(
                    side="BUY",
                    input_mint=settings.JUPITER_USDC_MINT,
                    output_mint=candidate.mint_address,
                    amount_raw=_raw_usdc(requested),
                    taker_public_key=taker,
                )
                output_raw = _order_output_amount(buy.raw)
                sell = await self._jupiter.order(
                    side="SELL",
                    input_mint=candidate.mint_address,
                    output_mint=settings.JUPITER_USDC_MINT,
                    amount_raw=output_raw,
                    taker_public_key=taker,
                )
                if not buy.route_plan or not sell.route_plan:
                    raise ValueError("order has no route plan")
            except Exception:
                await self._record(base, status="BLOCKED", reasons=(REASON_ORDER_UNAVAILABLE,))
                continue

            created = await self._record(
                base,
                status="WOULD_BUY",
                reasons=(),
                buy_order=buy.as_json(),
                sell_order=sell.as_json(),
            )
            if created:
                would_buy += 1
                state = type(state)(
                    open_positions=state.open_positions + 1,
                    exposure_usd=state.exposure_usd + requested,
                    daily_notional_usd=state.daily_notional_usd + requested,
                    daily_realised_loss_usd=state.daily_realised_loss_usd,
                )

        final_state = await self._repository.policy_state(now=now)
        return DryRunOutcome(
            mode="dry_run",
            evaluated=len(entries),
            strategy_signals=len(signals),
            safety_allowed=safety_allowed,
            safety_blocked=safety_blocked,
            policy_allowed=policy_allowed,
            policy_blocked=policy_blocked,
            would_buy=would_buy,
            would_sell=0,
            hypothetical_exposure_usd=final_state.exposure_usd,
        )

    async def _strategy_signals(
        self, entries: Sequence[RadarToken], *, now: datetime
    ) -> list[tuple[int, RadarToken, Candidate, str | None]]:
        """Use the production strategy's exact ranked eligibility and `entry_for` rule."""
        rows = list(entries)
        mints = [row.mint_address for row in rows]
        snapshots = await self._market.latest_for_mints(mints)
        held = await self._repository.held_mints()
        observations = [
            eligibility.Observation(
                mint_address=row.mint_address,
                rank=rank,
                has_snapshot=(snapshot := snapshots.get(row.mint_address)) is not None,
                observed_at=snapshot.captured_at if snapshot else None,
                price_usd=snapshot.price_usd if snapshot else None,
                liquidity_usd=snapshot.liquidity_usd if snapshot else None,
                market_cap=snapshot.market_cap if snapshot else None,
                trading_status=str(snapshot.trading_status.value) if snapshot else None,
            )
            for rank, row in enumerate(rows, start=1)
        ]
        verdicts = eligibility.screen(observations, held_ever=held, open_now=set())
        tokens = await TokenRepository(self._session).get_many_by_mints(mints)
        strategy = registry.default
        signals: list[tuple[int, RadarToken, Candidate, str | None]] = []
        for rank, (row, verdict) in enumerate(zip(rows, verdicts, strict=True), start=1):
            if verdict.candidate is None:
                continue
            # This is the production V1 `entry_for` call. Its $100 strategy
            # amount remains untouched; the independent policy subsequently
            # caps an autonomous dry-run at $5.
            instruction = strategy.entry_for(
                verdict.candidate, cash_available=Decimal(100), now=now
            )
            if instruction is None:
                continue
            token = tokens.get(row.mint_address)
            signals.append((rank, row, verdict.candidate, token.symbol if token else None))
        return signals

    def _base_values(
        self,
        *,
        symbol: str | None,
        candidate: Candidate,
        rank: int,
        now: datetime,
        safety: SafetyDecision,
        requested: Decimal,
    ) -> dict[str, object]:
        signal_key = (
            f"{candidate.mint_address}:{candidate.observed_at.isoformat()}:"
            "trailing_stop_25_v1:BUY:jupiter_v2_ephemeral_taker"
        )
        return {
            "idempotency_key": hashlib.sha256(signal_key.encode()).hexdigest(),
            "mint_address": candidate.mint_address,
            "symbol": symbol,
            "side": "BUY",
            "mode": "dry_run",
            "strategy_id": "trailing_stop_25_v1",
            "strategy_version": "1.0.0",
            "radar_rank": rank,
            "signal_at": candidate.observed_at,
            "evaluated_at": now,
            "requested_usd": requested,
            "safety_evaluation_id": safety.evaluation_id,
            "safety_decision": safety.decision,
            "liquidity_usd": candidate.liquidity_usd,
            "buy_impact_pct": safety.buy_price_impact_pct,
            "sell_impact_pct": safety.sell_price_impact_pct,
            "round_trip_loss_pct": safety.round_trip_loss_pct,
        }

    async def _record(
        self,
        base: dict[str, object],
        *,
        status: str,
        reasons: tuple[str, ...],
        buy_order: dict[str, object] | None = None,
        sell_order: dict[str, object] | None = None,
    ) -> bool:
        found = await self._repository.record(
            **base,
            status=status,
            reason_codes=list(reasons),
            buy_order=buy_order,
            sell_order=sell_order,
        )
        return found is not None


def _raw_usdc(amount: Decimal) -> int:
    return int((amount * (Decimal(10) ** USDC_DECIMALS)).to_integral_value())


def _ephemeral_dry_run_taker_public_key() -> str:
    """Create a one-call, unfunded `/order` taker without exposing its secret."""
    keypair = Keypair()
    try:
        return str(keypair.pubkey())
    finally:
        del keypair


def _order_output_amount(raw: dict[str, object]) -> int:
    value = raw.get("outAmount")
    output = int(str(value))
    if output <= 0:
        raise ValueError("order has zero output")
    return output
