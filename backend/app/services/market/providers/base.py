"""Market data provider interface.

Everything above this module speaks `MarketData` and `MarketDataProvider`, never
a vendor's JSON. Swapping DexScreener for Birdeye or Jupiter is then a matter of
writing one adapter and changing `MARKET_PROVIDER` — no service, repository, or
API code moves. See docs/adr/0001-market-provider-abstraction.md.

`MarketData` is a normalised, provider-neutral value object. Every field is
optional because real providers return partial data constantly: a token minutes
old typically has a price but no market cap, and one with no pool has nothing.
"""

from __future__ import annotations

import abc
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from types import TracebackType
from typing import Self

from app.models.market import TradingStatus


class ProviderError(RuntimeError):
    """A provider call failed in a way worth retrying."""


class ProviderUnavailableError(ProviderError):
    """The provider is down or the circuit breaker is open.

    **No request was made on any token's behalf.** That distinction is the whole
    reason this class is separate from `ProviderError`: a token cannot be judged
    by a call that never left the process, and the enrichment service must not
    charge this to a token's failure budget. See `MarketEnrichmentService.enrich`.

    `retry_after_seconds` carries the breaker's own remaining cooldown so the
    caller can defer the batch by exactly that long. It was previously only
    available inside the message string; parsing prose to decide a schedule is
    the kind of thing that works until someone rewords the sentence.
    """

    def __init__(self, message: str, *, retry_after_seconds: float | None = None) -> None:
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


class ProviderRateLimitError(ProviderError):
    """The provider rejected the call for rate-limit reasons."""


@dataclass(frozen=True, slots=True)
class MarketData:
    """Normalised market state for one token, from any provider."""

    mint_address: str

    price_usd: Decimal | None = None
    price_native: Decimal | None = None
    liquidity_usd: Decimal | None = None
    fully_diluted_valuation: Decimal | None = None
    market_cap: Decimal | None = None

    volume_24h: Decimal | None = None
    volume_1h: Decimal | None = None
    volume_5m: Decimal | None = None

    buy_count_24h: int | None = None
    sell_count_24h: int | None = None

    dex_name: str | None = None
    trading_pair: str | None = None
    pool_address: str | None = None

    trading_status: TradingStatus = TradingStatus.UNKNOWN
    is_verified: bool = False

    provider: str = "unknown"
    provider_latency_ms: int | None = None
    observed_at: datetime | None = None

    @property
    def has_market(self) -> bool:
        """True when the provider actually knows about a pool for this token."""
        return self.pool_address is not None or self.price_usd is not None


@dataclass(frozen=True, slots=True)
class ProviderHealth:
    name: str
    available: bool
    circuit_state: str
    consecutive_failures: int = 0
    last_latency_ms: int | None = None
    details: dict[str, str] = field(default_factory=dict)


class MarketDataProvider(abc.ABC):
    """Contract every market data source must satisfy.

    Implementations own transport, authentication, retry, and response shape.
    They must not raise for a token that simply has no market — that is an empty
    result, not a failure — and must not import anything from `app.services`
    outside this package.
    """

    #: Stable identifier recorded on every snapshot for provenance.
    name: str = "base"

    #: Most mints the provider accepts in a single call. 1 disables batching.
    batch_size: int = 1

    async def __aenter__(self) -> Self:
        await self.start()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.close()

    async def start(self) -> None:  # noqa: B027 — optional hook, not every provider needs one
        """Open any long-lived resources. Safe to call more than once."""

    async def close(self) -> None:  # noqa: B027 — optional hook, not every provider needs one
        """Release resources. Safe to call more than once."""

    @abc.abstractmethod
    async def fetch_many(self, mint_addresses: Sequence[str]) -> dict[str, MarketData]:
        """Fetch market data for several mints at once.

        Returns a mapping keyed by mint address, containing only the mints the
        provider had data for. Mints with no pool are simply absent — callers
        must not treat a missing key as an error.

        Raises `ProviderError` (or a subclass) when the call itself failed.
        """

    async def fetch_one(self, mint_address: str) -> MarketData | None:
        """Convenience wrapper over `fetch_many`."""
        result = await self.fetch_many([mint_address])
        return result.get(mint_address)

    @abc.abstractmethod
    async def health(self) -> ProviderHealth:
        """Report availability without performing a full fetch."""
