"""SOL/USD for execution accounting, and the two things it makes honest.

Every limit in this system is written in USD. Every network fee is paid in SOL.
Without a dated reading joining the two, `_close_confirmed_position` had no
choice but to write the gross figure into `realised_net_pnl_usd` — a column
named `net` holding gross, which reads as measured and is not.

It also meant `REAL_WALLET_MIN_SOL_FEE_RESERVE` could be checked only against
itself. A wallet can hold enough SOL for the transaction in front of it and not
enough for the one that closes the position, and a position that cannot fund
its own exit is worse than one that was never opened.

## No new vendor

The source is the Jupiter quote endpoint the paper wallet already depends on,
asked for one SOL in USDC. Adding a price provider for a single number would be
a new failure mode, a new key and a new thing to monitor.

## What is refused

`current()` returns `None` rather than a stale or invented figure. Callers
divide into two kinds and the distinction matters:

* **Entry risk controls fail closed.** No price means the fee reserve cannot be
  evaluated, so no entry.
* **Historical settlement degrades.** A trade that already happened keeps its
  measured gross figure; the net is left `None` with a reason. Fabricating a
  price to fill a column would be worse than an empty one.

The pure arithmetic below takes `now` and a price as parameters and reads no
clock, so fee conversion is reproducible from stored values.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol

from app.core.config import settings
from app.core.logging import get_logger
from app.paper.execution import ExecutionQuoteUnavailableError
from app.services.jupiter import JupiterExecutionClient

logger = get_logger(__name__)

LAMPORTS_PER_SOL = Decimal(1_000_000_000)
_SOL_DECIMALS = 9

#: Recorded when a settled trade cannot be given a net figure.
NET_UNAVAILABLE_NO_PRICE = (
    "No SOL/USD reading was available when this trade settled, so its network "
    "fee could not be converted to USD. The gross figure is measured; no net "
    "figure is claimed."
)
NET_UNAVAILABLE_NO_FEE = (
    "The confirmed transaction reported no network fee, so no fee could be "
    "deducted. The gross figure is measured; no net figure is claimed."
)


@dataclass(frozen=True, slots=True)
class SolUsdPrice:
    """One dated SOL/USD reading, with the provider that produced it."""

    usd: Decimal
    observed_at: datetime
    source: str

    def age_seconds(self, now: datetime) -> Decimal:
        return Decimal(str((now - self.observed_at).total_seconds()))

    def is_fresh(self, now: datetime, *, max_age_seconds: int) -> bool:
        """A reading from the future is not fresh, it is wrong."""
        age = self.age_seconds(now)
        return Decimal(0) <= age <= Decimal(max_age_seconds)


def lamports_to_sol(lamports: int) -> Decimal:
    return Decimal(lamports) / LAMPORTS_PER_SOL


def fee_usd(*, lamports: int | None, price: SolUsdPrice | None) -> Decimal | None:
    """Convert a network fee to USD, or refuse.

    `None` for either input gives `None` out. A missing fee and a fee of zero
    are different facts and only one of them is a measurement.
    """
    if lamports is None or price is None or lamports < 0:
        return None
    return lamports_to_sol(lamports) * price.usd


@dataclass(frozen=True, slots=True)
class FeeReserveDecision:
    """Whether the wallet can afford this transaction *and* its exit."""

    sufficient: bool
    required_sol: Decimal
    available_sol: Decimal | None
    reasons: tuple[str, ...]


def evaluate_fee_reserve(
    *,
    balance_sol: Decimal | None,
    minimum_reserve_sol: Decimal,
    priority_fee_sol: Decimal,
    base_fee_sol: Decimal = Decimal("0.000005"),
    exit_multiplier: int = 2,
) -> FeeReserveDecision:
    """Conservative: the entry, its priority fee, and the exit that must follow.

    `exit_multiplier` counts transactions, not fees — at 2 the wallet must hold
    enough for this transaction and one more, because an opened position has to
    be closable. Recovery beyond that is what `minimum_reserve_sol` is for, and
    it is added on top rather than counted within.

    Fails closed on an unknown balance: not knowing what the wallet holds is not
    evidence that it holds enough.
    """
    per_transaction = base_fee_sol + priority_fee_sol
    required = per_transaction * Decimal(exit_multiplier) + minimum_reserve_sol

    if balance_sol is None:
        return FeeReserveDecision(
            sufficient=False,
            required_sol=required,
            available_sol=None,
            reasons=("SOL_BALANCE_UNKNOWN",),
        )
    if balance_sol < required:
        return FeeReserveDecision(
            sufficient=False,
            required_sol=required,
            available_sol=balance_sol,
            reasons=("SOL_FEE_RESERVE_INSUFFICIENT",),
        )
    return FeeReserveDecision(
        sufficient=True, required_sol=required, available_sol=balance_sol, reasons=()
    )


class SolUsdPriceSource(Protocol):
    async def current(self, *, now: datetime) -> SolUsdPrice | None: ...


class JupiterSolUsdPriceSource:
    """SOL/USD from the quote endpoint the paper wallet already uses.

    Read-only and public: it asks what one SOL routes to in USDC. Deliberately
    not a new provider — one more vendor for one number is one more key, one
    more outage and one more thing to monitor.
    """

    source_name = "jupiter_quote_v1"

    def __init__(self, *, client: JupiterExecutionClient | None = None) -> None:
        self._client = client or JupiterExecutionClient()

    async def current(self, *, now: datetime) -> SolUsdPrice | None:
        """One SOL priced in USDC, or `None` if the route is unavailable.

        The reading is stamped with `now` rather than a provider timestamp: the
        quote describes the market at the moment it was fetched, and inventing
        a more precise instant than we observed would overstate its freshness.
        """
        try:
            quote = await self._client.sell_quote(
                input_mint=settings.EXECUTION_SOL_MINT,
                quantity=Decimal(1),
                input_decimals=_SOL_DECIMALS,
                now=now,
            )
        except (ExecutionQuoteUnavailableError, Exception) as exc:
            # Any failure is an absent price. Execution accounting must never
            # inherit a partially-parsed number from a provider error path.
            logger.warning("sol_usd_price_unavailable", error=str(exc))
            return None

        usd = quote.output_amount_usd
        if usd is None or usd <= 0:
            return None
        return SolUsdPrice(usd=usd, observed_at=now, source=self.source_name)


class UnavailableSolUsdPriceSource:
    """Explicit empty source, for wiring that must fail closed rather than guess."""

    source_name = "unavailable"

    async def current(self, *, now: datetime) -> SolUsdPrice | None:
        del now
        return None


@dataclass(frozen=True, slots=True)
class SolPriceReadiness:
    """What the admin dashboard says about fee accounting."""

    source: str
    price_usd: Decimal | None
    observed_at: datetime | None
    age_seconds: Decimal | None
    fresh: bool
    max_age_seconds: int
    minimum_reserve_sol: Decimal
    fee_accounting_ready: bool
    unavailable_reason: str | None
