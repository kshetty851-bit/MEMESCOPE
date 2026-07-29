"""Unit tests for `CompositeProvider`.

These lock the three rules in the module docstring, because each of them
prevents a failure that would be invisible in production: a silently
overwritten primary value, a batch of snapshots lost to a supplementary
lookup, and a `liquidity_usd` series whose meaning changed without the
`provider` column recording it.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

import pytest

from app.models.market import TradingStatus
from app.services.market.providers.base import (
    MarketData,
    MarketDataProvider,
    ProviderError,
    ProviderHealth,
    ProviderRateLimitError,
)
from app.services.market.providers.composite import MAX_PROVIDER_LABEL, CompositeProvider

pytestmark = pytest.mark.unit

MINT = "4BkPY3txwgKJBr4qfA35Y7kSiGfniDzN6wFsEdMKpump"
OTHER = "AwL4opAKtqWMz6hPePouf2kd2Sx7hNxhzcyBXMqNpump"
POOL = "9pDuF4dvUNSdGiJqQnJTrwWyBnHnUvpVfXpNvbwCvXyz"
POOL2 = "7RrnoB1JJZQpxVQ8cKcCLmZgHFEHkPfmXaXhqTgvNa11"


def _data(
    mint: str = MINT,
    *,
    liquidity: Decimal | None = None,
    pool: str | None = POOL,
    provider: str = "dexscreener",
) -> MarketData:
    """A pump.fun row as DexScreener really returns it: priced, but no liquidity."""
    return MarketData(
        mint_address=mint,
        price_usd=Decimal("0.000002055896768"),
        liquidity_usd=liquidity,
        market_cap=Decimal("2055.89"),
        volume_24h=Decimal("0.0726"),
        buy_count_24h=1,
        sell_count_24h=0,
        dex_name="pumpfun",
        pool_address=pool,
        trading_status=TradingStatus.TRADING,
        provider=provider,
        provider_latency_ms=42,
    )


class FakePrimary(MarketDataProvider):
    name = "dexscreener"
    batch_size = 30

    def __init__(self, results: dict[str, MarketData] | None = None) -> None:
        self.results = results if results is not None else {MINT: _data()}
        self.closed = False

    async def fetch_many(self, mint_addresses: Sequence[str]) -> dict[str, MarketData]:
        return dict(self.results)

    async def close(self) -> None:
        self.closed = True

    async def health(self) -> ProviderHealth:
        return ProviderHealth(
            name=self.name, available=True, circuit_state="closed", last_latency_ms=42
        )


class FakeSecondary:
    """Stands in for `GeckoTerminalPoolLiquidity` — pool-keyed, by design."""

    name = "geckoterminal"
    batch_size = 30

    def __init__(
        self,
        reserves: dict[str, Decimal] | None = None,
        *,
        error: Exception | None = None,
    ) -> None:
        self.reserves = reserves or {}
        self.error = error
        self.requested: list[list[str]] = []
        self.closed = False

    async def fetch_pool_reserves(self, pool_addresses: Sequence[str]) -> dict[str, Decimal]:
        self.requested.append(list(pool_addresses))
        if self.error is not None:
            raise self.error
        return {p: r for p, r in self.reserves.items() if p in set(pool_addresses)}

    async def start(self) -> None:
        return None

    async def close(self) -> None:
        self.closed = True

    async def health(self) -> ProviderHealth:
        return ProviderHealth(name=self.name, available=True, circuit_state="closed")


def _composite(
    primary: FakePrimary | None = None, secondary: FakeSecondary | None = None
) -> CompositeProvider:
    return CompositeProvider(primary or FakePrimary(), secondary)  # type: ignore[arg-type]


# --- The gap this exists to close --------------------------------------------


async def test_fills_missing_liquidity_from_the_secondary() -> None:
    secondary = FakeSecondary({POOL: Decimal("1631.1462")})
    composite = _composite(secondary=secondary)

    result = await composite.fetch_many([MINT])

    assert result[MINT].liquidity_usd == Decimal("1631.1462")
    assert secondary.requested == [[POOL]]


async def test_the_secondary_is_asked_by_pool_address() -> None:
    """A mint-keyed lookup would read a field of different meaning entirely."""
    secondary = FakeSecondary()
    await _composite(secondary=secondary).fetch_many([MINT])
    assert secondary.requested == [[POOL]]
    assert MINT not in secondary.requested[0]


# --- Rule 1: a primary value is never overwritten ----------------------------


async def test_existing_liquidity_is_never_overwritten() -> None:
    primary = FakePrimary({MINT: _data(liquidity=Decimal("500"))})
    secondary = FakeSecondary({POOL: Decimal("999999")})
    composite = _composite(primary, secondary)

    result = await composite.fetch_many([MINT])

    assert result[MINT].liquidity_usd == Decimal("500")
    # Not merely unchanged — never even requested.
    assert secondary.requested == []


async def test_no_other_field_is_touched_by_a_fill() -> None:
    secondary = FakeSecondary({POOL: Decimal("1631.1462")})
    before = _data()
    result = await _composite(FakePrimary({MINT: before}), secondary).fetch_many([MINT])
    after = result[MINT]

    assert after.price_usd == before.price_usd
    assert after.market_cap == before.market_cap
    assert after.volume_24h == before.volume_24h
    assert after.buy_count_24h == before.buy_count_24h
    assert after.dex_name == before.dex_name
    assert after.pool_address == before.pool_address
    assert after.provider_latency_ms == before.provider_latency_ms


async def test_trading_status_is_left_to_the_adapter_that_owns_the_threshold() -> None:
    """Re-deriving it here would put MIN_TRADEABLE_LIQUIDITY_USD in two places."""
    secondary = FakeSecondary({POOL: Decimal("0.01")})
    primary = FakePrimary({MINT: _data()})
    result = await _composite(primary, secondary).fetch_many([MINT])
    assert result[MINT].trading_status is TradingStatus.TRADING


async def test_a_row_without_a_pool_cannot_be_filled() -> None:
    primary = FakePrimary({MINT: _data(pool=None)})
    secondary = FakeSecondary({POOL: Decimal("1631")})
    result = await _composite(primary, secondary).fetch_many([MINT])

    assert result[MINT].liquidity_usd is None
    assert secondary.requested == []


# --- Rule 2: a secondary failure costs nothing -------------------------------


@pytest.mark.parametrize(
    "error",
    [
        ProviderError("geckoterminal is down"),
        ProviderRateLimitError("geckoterminal call budget exhausted (25/min)"),
    ],
)
async def test_a_secondary_failure_returns_the_primary_batch_intact(
    error: Exception,
) -> None:
    """Snapshots are the durable asset; a fill must never be able to cost one."""
    secondary = FakeSecondary(error=error)
    composite = _composite(FakePrimary({MINT: _data(), OTHER: _data(OTHER)}), secondary)

    result = await composite.fetch_many([MINT, OTHER])

    assert set(result) == {MINT, OTHER}
    assert result[MINT].liquidity_usd is None
    assert result[MINT].provider == "dexscreener"


async def test_a_skipped_fill_is_reported_not_silent() -> None:
    secondary = FakeSecondary(error=ProviderRateLimitError("budget exhausted"))
    composite = _composite(secondary=secondary)

    await composite.fetch_many([MINT])
    stats = composite.fill_stats()

    assert stats.eligible == 1
    assert stats.filled == 0
    assert stats.skipped == 1
    assert stats.error is not None and "budget" in stats.error


async def test_a_failure_part_way_through_keeps_what_was_already_fetched() -> None:
    """60 eligible rows is two chunks; the budget can expire between them.

    Voiding the first chunk would discard calls already spent and liquidity
    already in hand.
    """

    class FailsOnSecondChunk(FakeSecondary):
        def __init__(self) -> None:
            super().__init__()
            self.batch_size = 2
            self.calls = 0

        async def fetch_pool_reserves(
            self, pool_addresses: Sequence[str]
        ) -> dict[str, Decimal]:
            self.calls += 1
            if self.calls > 1:
                raise ProviderRateLimitError("budget exhausted")
            return {p: Decimal("100") for p in pool_addresses}

    rows = {f"mint{i}": _data(f"mint{i}", pool=f"pool{i}") for i in range(4)}
    composite = _composite(FakePrimary(rows), FailsOnSecondChunk())

    result = await composite.fetch_many(list(rows))
    stats = composite.fill_stats()

    assert result["mint0"].liquidity_usd == Decimal("100")
    assert result["mint1"].liquidity_usd == Decimal("100")
    assert result["mint2"].liquidity_usd is None
    assert (stats.eligible, stats.filled, stats.skipped) == (4, 2, 2)
    assert stats.error is not None


async def test_a_pool_the_vendor_does_not_know_counts_as_skipped() -> None:
    composite = _composite(secondary=FakeSecondary({}))
    await composite.fetch_many([MINT])
    stats = composite.fill_stats()
    assert (stats.eligible, stats.filled, stats.skipped) == (1, 0, 1)


# --- Rule 3: provenance changes only when the data does ----------------------


async def test_a_filled_row_records_both_vendors() -> None:
    secondary = FakeSecondary({POOL: Decimal("1631.1462")})
    result = await _composite(secondary=secondary).fetch_many([MINT])
    assert result[MINT].provider == "dexscreener+geckoterminal"


async def test_an_unfilled_row_keeps_the_primary_alone() -> None:
    """Otherwise the column would claim a contribution that never happened."""
    result = await _composite(secondary=FakeSecondary({})).fetch_many([MINT])
    assert result[MINT].provider == "dexscreener"


async def test_only_the_filled_rows_change_provenance() -> None:
    primary = FakePrimary({MINT: _data(), OTHER: _data(OTHER, pool=POOL2)})
    secondary = FakeSecondary({POOL: Decimal("1631")})
    result = await _composite(primary, secondary).fetch_many([MINT, OTHER])

    assert result[MINT].provider == "dexscreener+geckoterminal"
    assert result[OTHER].provider == "dexscreener"


async def test_provenance_label_cannot_overflow_the_column() -> None:
    """`provider` is String(32); a longer label would fail the whole insert."""
    long_name = "a" * 30
    primary = FakePrimary({MINT: _data(provider=long_name)})
    secondary = FakeSecondary({POOL: Decimal("1631")})
    result = await _composite(primary, secondary).fetch_many([MINT])

    assert len(result[MINT].provider) <= MAX_PROVIDER_LABEL
    # The data is still filled — only the label degrades.
    assert result[MINT].liquidity_usd == Decimal("1631")
    assert result[MINT].provider == long_name


# --- Mechanics ---------------------------------------------------------------


async def test_chunks_pool_lookups_to_the_secondary_batch_size() -> None:
    rows = {f"mint{i}": _data(f"mint{i}", pool=f"pool{i}") for i in range(7)}
    secondary = FakeSecondary()
    secondary.batch_size = 3
    await _composite(FakePrimary(rows), secondary).fetch_many(list(rows))

    assert [len(chunk) for chunk in secondary.requested] == [3, 3, 1]


async def test_batch_size_follows_the_primary() -> None:
    """The service chunks mints by this; the secondary chunks pools itself."""
    primary = FakePrimary()
    primary.batch_size = 17
    assert _composite(primary).batch_size == 17


async def test_an_empty_primary_result_skips_the_secondary_entirely() -> None:
    secondary = FakeSecondary()
    result = await _composite(FakePrimary({}), secondary).fetch_many([MINT])
    assert result == {}
    assert secondary.requested == []


async def test_nothing_eligible_skips_the_secondary_entirely() -> None:
    primary = FakePrimary({MINT: _data(liquidity=Decimal("10"))})
    secondary = FakeSecondary()
    await _composite(primary, secondary).fetch_many([MINT])
    assert secondary.requested == []


async def test_fill_stats_reset_between_batches() -> None:
    """A stale count would misreport the gap on the next batch."""
    secondary = FakeSecondary({POOL: Decimal("1631")})
    composite = _composite(secondary=secondary)

    await composite.fetch_many([MINT])
    assert composite.fill_stats().filled == 1

    composite._primary = FakePrimary({MINT: _data(liquidity=Decimal("5"))})
    await composite.fetch_many([MINT])
    assert composite.fill_stats().filled == 0
    assert composite.fill_stats().eligible == 0


async def test_start_opens_both_sides() -> None:
    class RecordingPrimary(FakePrimary):
        def __init__(self) -> None:
            super().__init__()
            self.started = False

        async def start(self) -> None:
            self.started = True

    class RecordingSecondary(FakeSecondary):
        def __init__(self) -> None:
            super().__init__()
            self.started = False

        async def start(self) -> None:
            self.started = True

    primary, secondary = RecordingPrimary(), RecordingSecondary()
    async with _composite(primary, secondary):
        pass

    assert primary.started is True
    assert secondary.started is True


async def test_a_reserve_for_a_pool_never_requested_is_ignored() -> None:
    """Defends rule 1 independently of the adapter's own filtering."""

    class Chatty(FakeSecondary):
        async def fetch_pool_reserves(
            self, pool_addresses: Sequence[str]
        ) -> dict[str, Decimal]:
            self.requested.append(list(pool_addresses))
            return {POOL: Decimal("1631"), "never-asked-for": Decimal("9")}

    composite = _composite(secondary=Chatty())
    result = await composite.fetch_many([MINT])

    assert result[MINT].liquidity_usd == Decimal("1631")
    assert composite.fill_stats().filled == 1


async def test_close_releases_both_even_if_the_primary_raises() -> None:
    class Exploding(FakePrimary):
        async def close(self) -> None:
            raise RuntimeError("primary close failed")

    secondary = FakeSecondary()
    composite = _composite(Exploding(), secondary)

    with pytest.raises(RuntimeError):
        await composite.close()
    assert secondary.closed is True


async def test_health_reports_both_sides() -> None:
    composite = _composite(secondary=FakeSecondary({POOL: Decimal("1631")}))
    await composite.fetch_many([MINT])
    health = await composite.health()

    assert health.name == "composite"
    assert health.available is True
    assert health.details["primary"] == "dexscreener"
    assert health.details["secondary"] == "geckoterminal"
    assert health.details["last_fill_filled"] == "1"


async def test_a_secondary_outage_does_not_make_the_composite_unavailable() -> None:
    """It supplements. Its absence is a coverage gap, not an outage."""
    secondary = FakeSecondary()

    async def unhealthy() -> ProviderHealth:
        return ProviderHealth(name="geckoterminal", available=False, circuit_state="open")

    secondary.health = unhealthy  # type: ignore[method-assign]
    health = await _composite(secondary=secondary).health()

    assert health.available is True
    assert health.details["secondary_available"] == "False"
