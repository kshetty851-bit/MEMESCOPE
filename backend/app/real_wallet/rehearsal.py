"""The ARMED rehearsal: prove the whole chain with no transaction existing.

`dry_run` has no wallet to read and never spends anything, so it cannot exercise
the parts that matter most — the real balance ceiling, the real signer, the real
genesis check. `live` exercises them by spending money. ARMED is the state in
between: every pre-submission condition is evaluated against **real facts**, the
twenty-one-condition guard runs on those facts, and `/execute` remains impossible
by construction.

This module gathers the facts and reports them. It is the last thing that can be
learned for free.

**It cannot submit, sign, or spend.** It builds no transaction and never calls
the transport. It reads: a public key, a genesis hash, a balance, a kill switch,
a configuration. Facts it cannot measure are reported as unavailable and passed
to the guard as their refusing default — an unmeasured precondition has not been
met, it has merely not been looked at.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.real_wallet.balance import ExecutionWalletBalanceService
from app.real_wallet.live_readiness import (
    LiveSubmissionGuard,
    SubmissionFacts,
)
from app.real_wallet.live_repository import LiveIntentRepository
from app.real_wallet.network import is_valid_wallet_address, verify_wallet_network
from app.real_wallet.policy import AutonomousExecutionPolicy, PolicyState
from app.real_wallet.mainnet_signer_client import (
    MainnetSignerRejectedError,
    MainnetSignerUnavailableError,
    UnixMainnetSignerClient,
)
from app.real_wallet.transport_policy import (
    ExecutionTransportPolicy,
    current_envelope,
)
from app.real_wallet.tx_inspect import lamports_from_sol
from app.services.rpc.standard import StandardSolanaRPC

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class Observed:
    """One fact, and how it was obtained. `value` None means unmeasured."""

    key: str
    value: bool | None
    source: str
    note: str = ""

    @property
    def state(self) -> str:
        return "MEASURED" if self.value is not None else "UNAVAILABLE"


@dataclass(frozen=True, slots=True)
class RehearsalReport:
    envelope: str
    network: str
    public_key: str
    balance_sol: Decimal | None
    facts: SubmissionFacts
    guard_allowed: bool
    guard_reasons: tuple[str, ...]
    transport_permitted: bool
    transport_reasons: tuple[str, ...]
    observations: tuple[Observed, ...] = field(default_factory=tuple)

    @property
    def submission_impossible(self) -> bool:
        """ARMED must always refuse. If this is ever False outside `live`, the
        rehearsal itself has found a defect, which is the point of asserting it."""
        return not self.transport_permitted

    @property
    def unmeasured(self) -> tuple[str, ...]:
        return tuple(o.key for o in self.observations if o.value is None)


async def rehearse(session: AsyncSession, *, now: datetime) -> RehearsalReport:
    """Evaluate every pre-submission condition against real facts."""
    observations: list[Observed] = []

    def seen(key: str, value: bool | None, source: str, note: str = "") -> bool:
        observations.append(Observed(key, value, source, note))
        return bool(value)

    public_key = settings.REAL_WALLET_PUBLIC_KEY.strip()

    # --- signer: ASK the isolated service; never load the key here ----------
    # Application containers are deliberately denied a signer path, so this
    # cannot answer by opening the file. It asks the one process that holds it,
    # over a socket, and receives a public key back. On devnet there is no
    # mainnet signer to ask, and "unavailable" is the honest answer rather than
    # a failure — which is why it reports UNAVAILABLE rather than False.
    signer_ready: bool | None = None
    signer_matches: bool | None = None
    note = ""
    if not public_key:
        signer_ready = signer_matches = False
        note = "no pinned public key configured"
    elif not settings.MAINNET_SIGNER_SOCKET.strip():
        note = "no mainnet signer socket configured — service not deployed"
    else:
        try:
            got = await UnixMainnetSignerClient().identity()
            signer_ready = True
            signer_matches = bool(got.get("matches_pinned_key"))
            note = f"signer holds {got.get('public_key', '')[:8]}…"
            if not signer_matches:
                note = "signer holds a DIFFERENT key than the pinned one"
        except MainnetSignerRejectedError as exc:
            signer_ready, signer_matches = True, False
            note = f"signer refused: {exc}"
        except MainnetSignerUnavailableError as exc:
            signer_ready = signer_matches = False
            note = f"signer unreachable: {exc}"
    seen("signer_ready", signer_ready, "mainnet signer socket", note)
    seen("signer_matches_pinned_key", signer_matches, "derived vs pinned", note)

    # --- chain: the endpoint we would actually trade through ----------------
    network_verified: bool | None = None
    balance_sol: Decimal | None = None
    balance_lamports: int | None = None
    if public_key and is_valid_wallet_address(public_key):
        rpc = StandardSolanaRPC(rpc_url=settings.REAL_WALLET_RPC_URL)
        try:
            async with rpc:
                status = await verify_wallet_network(
                    rpc, network=settings.REAL_WALLET_NETWORK
                )
                network_verified = status.verified
                if status.verified:
                    got = await ExecutionWalletBalanceService(rpc).get_sol_balance(
                        public_key
                    )
                    balance_sol = Decimal(str(got.sol))
                    balance_lamports = lamports_from_sol(balance_sol)
        except Exception as exc:  # pragma: no cover - an unreadable chain is UNKNOWN
            logger.warning("rehearsal_chain_unreadable", error=str(exc))
            network_verified = None
    else:
        network_verified = False
    seen("mainnet_verified", network_verified, "genesis hash vs configured network",
         "" if public_key else "no wallet configured")
    seen("wallet_balance_readable", None if balance_sol is None else True,
         "getBalance", f"{balance_sol} SOL" if balance_sol is not None else "unreadable")

    # --- kill switch --------------------------------------------------------
    kill_switch_active: bool | None = None
    try:
        kill_switch_active = bool(
            await LiveIntentRepository(session).active_kill_switches()
        )
    except Exception as exc:  # pragma: no cover
        logger.warning("rehearsal_kill_switch_unreadable", error=str(exc))
    seen("kill_switch_clear", None if kill_switch_active is None
         else not kill_switch_active, "active_kill_switches")

    # --- canary bounds: size and count, evaluated as a real entry would -----
    entry_size = settings.REAL_WALLET_ENTRY_SIZE_USD
    canary = AutonomousExecutionPolicy().evaluate_canary_entry(
        requested_usd=entry_size,
        state=PolicyState(
            open_positions=0,
            exposure_usd=Decimal(0),
            daily_notional_usd=Decimal(0),
            daily_realised_loss_usd=Decimal(0),
            daily_trades=0,
            wallet_balance_lamports=balance_lamports,
        ),
    )
    seen("canary_limits_satisfied", canary.allowed, "evaluate_canary_entry",
         ",".join(canary.reason_codes) or "within bounds")

    # Facts this rehearsal deliberately cannot establish: they belong to an
    # actual order, and no order exists. They stay at their refusing defaults,
    # which is why the guard must still refuse at the end of a clean rehearsal.
    for key, why in (
        ("safety_passed", "needs a candidate mint"),
        ("safety_fresh", "needs a candidate mint"),
        ("valid_intent", "no intent exists"),
        ("not_previously_submitted", "no intent exists"),
        ("order_fresh", "no order exists"),
        ("market_fresh", "no order exists"),
        ("transaction_approved", "no transaction is built"),
        ("not_previously_signed", "nothing is signed"),
    ):
        seen(key, None, "not applicable without an order", why)

    facts = SubmissionFacts(
        signer_ready=bool(signer_ready),
        signer_matches_pinned_key=bool(signer_matches),
        policy_passed=canary.allowed,
        kill_switch_active=(True if kill_switch_active is None else kill_switch_active),
        daily_loss_within_limit=True,
        open_position_within_limit=True,
        trade_size_within_limit=canary.allowed,
        mainnet_verified=bool(network_verified),
        canary_limits_satisfied=canary.allowed,
        transport_release_approved=False,
    )
    guard = LiveSubmissionGuard().evaluate(facts)
    transport = ExecutionTransportPolicy().authorise(
        guard=guard,
        base_url=getattr(settings, "JUPITER_V2_BASE_URL", "") or "https://api.jup.ag",
        client_injected=False,
    )

    report = RehearsalReport(
        envelope=str(current_envelope()),
        network=settings.REAL_WALLET_NETWORK,
        public_key=public_key or "",
        balance_sol=balance_sol,
        facts=facts,
        guard_allowed=guard.allowed,
        guard_reasons=guard.reasons,
        transport_permitted=transport.permitted,
        transport_reasons=transport.reasons,
        observations=tuple(observations),
    )
    logger.info("real_wallet_rehearsal", envelope=report.envelope,
                guard_allowed=report.guard_allowed,
                submission_impossible=report.submission_impossible,
                unmeasured=len(report.unmeasured))
    return report


def as_dict(report: RehearsalReport) -> dict:
    return {
        "envelope": report.envelope,
        "network": report.network,
        "public_key": report.public_key,
        "balance_sol": (str(report.balance_sol)
                        if report.balance_sol is not None else None),
        "submission_impossible": report.submission_impossible,
        "guard_allowed": report.guard_allowed,
        "guard_reasons": list(report.guard_reasons),
        "transport_permitted": report.transport_permitted,
        "transport_reasons": list(report.transport_reasons),
        "unmeasured": list(report.unmeasured),
        "observations": [
            {"key": o.key, "state": o.state, "value": o.value,
             "source": o.source, "note": o.note}
            for o in report.observations
        ],
    }
