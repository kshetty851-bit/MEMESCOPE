"""A primary provider with a secondary that fills one specific gap.

ADR 0001 anticipated this shape: *"a `CompositeProvider` implementing the same
interface can try vendors in order without any caller knowing."* It is a
`MarketDataProvider`, so `MarketEnrichmentService`, the repositories, the API
and the frontend are all unchanged — the swap is one config value.

## What it does, precisely

It is **not** a failover chain. The secondary is never asked for a market the
primary already described; it is asked for exactly one field, for exactly the
rows where the primary returned a pool but no liquidity for it. Three rules
follow, and each exists to stop a plausible-looking mistake:

1. **A primary value is never overwritten.** The secondary fills `None` and
   nothing else. Two vendors disagreeing about a number the primary already
   supplied is a reconciliation problem this layer has no standing to settle.
2. **A secondary failure costs nothing.** Any `ProviderError` from the fill —
   including an exhausted call budget — leaves the primary's result intact and
   returns it. Snapshots are the durable asset (MASTER_CONTEXT §4); losing a
   whole batch to a supplementary lookup would be a strictly worse trade than
   the missing figure it was trying to supply.
3. **Provenance changes only when the data does.** A row whose liquidity came
   from the fill records both vendors, so a series can never silently change
   meaning without the `provider` column saying so.

## The budget, and what it honestly buys

GeckoTerminal's free tier allows ~30 calls/min. At 30 pools per call that is
~900 pools/min against a measured enrichment peak near 4,000 tokens/min, so the
fill covers a *fraction* of demand and the remainder keeps the null liquidity
it has today. That is a real limitation, not a rounding error, and it is
reported rather than hidden: `fill_stats()` exposes what was requested, filled
and skipped, and the worker logs it every batch.

Coverage is therefore partial, but it is not biased. Tokens are offered to the
fill in the order the scheduler claimed them, and the scheduler orders by
`next_refresh_at` — so tokens take turns rather than a favoured subset being
permanently enriched while others are permanently not.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from app.core.logging import get_logger
from app.services.market.providers.base import (
    MarketData,
    MarketDataProvider,
    ProviderError,
    ProviderHealth,
)
from app.services.market.providers.geckoterminal import GeckoTerminalPoolLiquidity

logger = get_logger(__name__)

# `token_market_snapshots.provider` is String(32); a longer label would raise on
# insert and cost the batch the very snapshots this class exists to improve.
MAX_PROVIDER_LABEL = 32


@dataclass(frozen=True, slots=True)
class FillStats:
    """What the last fill attempt actually achieved."""

    #: Rows the primary returned with a pool but no liquidity.
    eligible: int = 0
    #: Rows the secondary supplied a reserve for.
    filled: int = 0
    #: Eligible rows left unfilled — budget, outage, or simply not indexed.
    skipped: int = 0
    #: Set when the fill was abandoned wholesale, with the reason.
    error: str | None = None


class CompositeProvider(MarketDataProvider):
    """`primary`, with `secondary` filling missing liquidity by pool address."""

    name = "composite"

    def __init__(
        self,
        primary: MarketDataProvider,
        secondary: GeckoTerminalPoolLiquidity | None = None,
    ) -> None:
        self._primary = primary
        self._secondary = secondary or GeckoTerminalPoolLiquidity()
        # The service chunks by this, so it must be the primary's: the
        # secondary chunks its own pool lookups internally.
        self.batch_size = primary.batch_size
        self._last_fill = FillStats()

    @property
    def primary(self) -> MarketDataProvider:
        return self._primary

    @property
    def secondary(self) -> GeckoTerminalPoolLiquidity:
        return self._secondary

    def fill_stats(self) -> FillStats:
        return self._last_fill

    async def start(self) -> None:
        await self._primary.start()
        await self._secondary.start()

    async def close(self) -> None:
        # Closed independently: a failure releasing one must not leak the other.
        try:
            await self._primary.close()
        finally:
            await self._secondary.close()

    async def fetch_many(self, mint_addresses: Sequence[str]) -> dict[str, MarketData]:
        results = await self._primary.fetch_many(mint_addresses)
        if not results:
            self._last_fill = FillStats()
            return results

        # Eligible = the primary found a pool but reported no liquidity for it.
        # A row without a pool address cannot be looked up by pool, and one that
        # already has liquidity must not be touched (rule 1).
        eligible = {
            data.pool_address: mint
            for mint, data in results.items()
            if data.liquidity_usd is None and data.pool_address
        }
        if not eligible:
            self._last_fill = FillStats()
            return results

        reserves, error = await self._fetch_reserves(list(eligible))
        if error is not None:
            logger.warning(
                "liquidity_fill_degraded",
                provider=self._secondary.name,
                eligible=len(eligible),
                recovered=len(reserves),
                reason=error,
            )

        merged = dict(results)
        filled = 0
        for pool, reserve in reserves.items():
            mint = eligible.get(pool)
            if mint is None:
                continue
            data = merged[mint]
            # Re-check rather than trust the eligibility snapshot: cheap, and it
            # makes rule 1 true by construction at the point of mutation.
            if data.liquidity_usd is not None:
                continue
            merged[mint] = self._with_liquidity(data, reserve)
            filled += 1

        self._last_fill = FillStats(
            eligible=len(eligible),
            filled=filled,
            skipped=len(eligible) - filled,
            error=error,
        )
        logger.info(
            "liquidity_fill_completed",
            provider=self._secondary.name,
            eligible=len(eligible),
            filled=filled,
            skipped=len(eligible) - filled,
        )
        return merged

    async def _fetch_reserves(
        self, pools: Sequence[str]
    ) -> tuple[dict[str, Decimal], str | None]:
        """Chunk the pool lookups, keeping whatever completed before a failure.

        A batch of 60 eligible rows is two chunks at the secondary's batch size
        of 30, and the budget can easily run out between them. Discarding the
        first chunk because the second was refused would throw away calls
        already spent and liquidity already in hand — so chunks are accumulated
        and the first error stops the loop rather than voiding it.

        Returns what was gathered plus the error, if any. Rule 2 holds either
        way: the caller merges what it got and the primary's batch is intact
        regardless.
        """
        size = max(1, self._secondary.batch_size)
        reserves: dict[str, Decimal] = {}
        for start in range(0, len(pools), size):
            try:
                reserves |= await self._secondary.fetch_pool_reserves(
                    pools[start : start + size]
                )
            except ProviderError as exc:
                # Further chunks would hit the same budget or outage.
                return reserves, str(exc)
        return reserves, None

    def _with_liquidity(self, data: MarketData, reserve: Decimal) -> MarketData:
        """Return `data` carrying the filled liquidity and honest provenance.

        `MarketData` is frozen, so this replaces rather than mutates — which is
        what keeps the primary's own result untouched for any other reader.

        `trading_status` is deliberately left alone. The primary decided it
        without liquidity, and re-deriving it here would mean this class owned a
        threshold (`MIN_TRADEABLE_LIQUIDITY_USD`) that belongs to the adapter
        that defines it.
        """
        label = f"{data.provider}+{self._secondary.name}"
        return MarketData(
            mint_address=data.mint_address,
            price_usd=data.price_usd,
            price_native=data.price_native,
            liquidity_usd=reserve,
            fully_diluted_valuation=data.fully_diluted_valuation,
            market_cap=data.market_cap,
            volume_24h=data.volume_24h,
            volume_1h=data.volume_1h,
            volume_5m=data.volume_5m,
            buy_count_24h=data.buy_count_24h,
            sell_count_24h=data.sell_count_24h,
            dex_name=data.dex_name,
            trading_pair=data.trading_pair,
            pool_address=data.pool_address,
            trading_status=data.trading_status,
            is_verified=data.is_verified,
            provider=label if len(label) <= MAX_PROVIDER_LABEL else data.provider,
            provider_latency_ms=data.provider_latency_ms,
            observed_at=data.observed_at,
        )

    async def health(self) -> ProviderHealth:
        primary = await self._primary.health()
        secondary = await self._secondary.health()
        stats = self._last_fill
        return ProviderHealth(
            name=self.name,
            # The composite is available whenever the primary is: the secondary
            # supplements and its outage is a coverage gap, not an outage here.
            available=primary.available,
            circuit_state=primary.circuit_state,
            consecutive_failures=primary.consecutive_failures,
            last_latency_ms=primary.last_latency_ms,
            details={
                "primary": primary.name,
                "primary_circuit": primary.circuit_state,
                "secondary": secondary.name,
                "secondary_circuit": secondary.circuit_state,
                "secondary_available": str(secondary.available),
                "last_fill_eligible": str(stats.eligible),
                "last_fill_filled": str(stats.filled),
                "last_fill_skipped": str(stats.skipped),
                **{f"secondary_{k}": v for k, v in secondary.details.items()},
            },
        )
