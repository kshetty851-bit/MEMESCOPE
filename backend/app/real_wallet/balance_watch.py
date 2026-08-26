"""Money that left without going through the rail.

Every other guard in this wallet asks whether a spend may PROCEED —
`LiveSubmissionGuard` names twenty-two conditions, the transport policy names
more, the signer re-verifies everything it is handed. All of them sit in front
of the rail. None of them notices money that never used it.

That is the gap this closes, and it is a different KIND of question from
everything else HQ watches. A wedged worker is an operations problem. A wallet
that is lighter than the rail can account for is a key being used somewhere
else, and it is the one signal here that should be read as security rather than
health.

## What counts as unexplained

Only a DECREASE. Deposits are open by design — the address is public and anyone
may send to it — so a balance going up is never suspicious and reporting it
would train the reader to dismiss the alert.

A decrease is explained when the rail did something that would cause one:

  * an intent reached SUBMITTED or CONFIRMED in the window, or
  * a withdrawal was submitted in the window.

Anything else is unexplained, with one allowance: `FEE_TOLERANCE_LAMPORTS`
absorbs rent and priority-fee dust so the alarm is not spent on noise. It is
small on purpose — five thousandths of a SOL is far below any trade this wallet
is configured to make, so nothing meaningful hides under it.

## Unmeasurable is not clean

An unreadable balance writes NO observation at all rather than a clean one. A
gap in the series is honest; a row saying "nothing moved" when nothing was
measured is the reassurance this module exists to withhold, and it would also
become the baseline the next comparison trusts.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.models.real_wallet_execution import (
    RealWalletBalanceObservation,
    RealWalletLiveIntent,
)
from app.real_wallet.balance import ExecutionWalletBalanceService
from app.real_wallet.tx_inspect import lamports_from_sol
from app.services.rpc.base import SolanaRPC

logger = get_logger(__name__)

#: Dust the rail cannot itemise: rent adjustments, priority fees, a failed
#: transaction's fee. 0.005 SOL — far below any trade this wallet is configured
#: to make, so nothing meaningful hides beneath it.
FEE_TOLERANCE_LAMPORTS = 5_000_000

#: How far back to look for a rail action that explains a decrease. Generous
#: against the observation cadence: an intent that submitted just before the
#: previous observation still explains a drop seen at this one.
EXPLAIN_WINDOW = timedelta(minutes=30)


@dataclass(frozen=True, slots=True)
class BalanceReading:
    measured: bool
    detail: str
    lamports: int | None = None
    delta_lamports: int | None = None
    unexplained: bool | None = None

    @property
    def sol(self) -> Decimal | None:
        return Decimal(self.lamports).scaleb(-9) if self.lamports is not None else None


async def observe(
    session: AsyncSession, rpc: SolanaRPC, *, now: datetime | None = None
) -> BalanceReading:
    """Read the chain, compare it to the last observation, record the verdict."""
    now = now or datetime.now(UTC)
    wallet = settings.REAL_WALLET_PUBLIC_KEY.strip()
    if not wallet:
        return BalanceReading(measured=False, detail="No execution wallet configured.")

    try:
        sol = (await ExecutionWalletBalanceService(rpc).get_sol_balance(wallet)).sol
        lamports = lamports_from_sol(Decimal(str(sol)))
    except Exception as exc:  # noqa: BLE001
        # No row. A gap in the series is honest; a row claiming nothing moved
        # would be a lie AND would become the baseline the next check trusts.
        logger.warning("real_wallet_balance_unreadable", error=str(exc))
        return BalanceReading(measured=False, detail=f"Balance unreadable: {exc}")

    previous = (await session.execute(
        select(RealWalletBalanceObservation)
        .where(RealWalletBalanceObservation.wallet_public_key == wallet)
        .order_by(RealWalletBalanceObservation.observed_at.desc())
        .limit(1)
    )).scalars().first()

    delta: int | None = None
    unexplained: bool | None = None
    note: str | None = None

    if previous is not None:
        delta = lamports - int(previous.lamports)
        if delta >= -FEE_TOLERANCE_LAMPORTS:
            # Unchanged, up, or down by dust. Deposits are open by design and a
            # rise is never suspicious.
            unexplained = False
            note = "no material decrease"
        else:
            explained_by = await _rail_activity(session, wallet, now)
            unexplained = explained_by is None
            note = explained_by or "no submitted or confirmed intent in the window"

    session.add(RealWalletBalanceObservation(
        wallet_public_key=wallet, observed_at=now, lamports=lamports,
        delta_lamports=delta, unexplained=unexplained, note=(note or "")[:200],
    ))

    if unexplained:
        # Loud, and phrased as what it is. This is not a component being slow.
        logger.error(
            "real_wallet_balance_unexplained",
            wallet=wallet, lamports=lamports, delta_lamports=delta,
            sol_moved=str(Decimal(-(delta or 0)).scaleb(-9)),
        )

    return BalanceReading(
        measured=True,
        detail=(f"{Decimal(lamports).scaleb(-9)} SOL"
                + (f", {Decimal(delta).scaleb(-9)} since last" if delta is not None
                   else " (first observation)")),
        lamports=lamports, delta_lamports=delta, unexplained=unexplained,
    )


async def _rail_activity(
    session: AsyncSession, wallet: str, now: datetime
) -> str | None:
    """What the rail did recently that would explain a decrease, or None.

    SUBMITTED counts as well as CONFIRMED: a transfer that reached the network
    has already moved the money, and waiting for confirmation before accepting
    it as an explanation would raise a false alarm on every trade during the
    seconds it takes to settle.
    """
    since = now - EXPLAIN_WINDOW
    row = (await session.execute(
        select(RealWalletLiveIntent.id, RealWalletLiveIntent.state)
        .where(
            RealWalletLiveIntent.wallet_public_key == wallet,
            RealWalletLiveIntent.state.in_(("submitted", "confirmed")),
            RealWalletLiveIntent.submitted_at.is_not(None),
            RealWalletLiveIntent.submitted_at >= since,
        )
        .limit(1)
    )).first()
    if row is not None:
        return f"intent {str(row.id)[:8]} {row.state}"
    return None


async def latest(session: AsyncSession) -> RealWalletBalanceObservation | None:
    wallet = settings.REAL_WALLET_PUBLIC_KEY.strip()
    if not wallet:
        return None
    return (await session.execute(
        select(RealWalletBalanceObservation)
        .where(RealWalletBalanceObservation.wallet_public_key == wallet)
        .order_by(RealWalletBalanceObservation.observed_at.desc())
        .limit(1)
    )).scalars().first()


__all__ = [
    "EXPLAIN_WINDOW",
    "FEE_TOLERANCE_LAMPORTS",
    "BalanceReading",
    "latest",
    "observe",
]
