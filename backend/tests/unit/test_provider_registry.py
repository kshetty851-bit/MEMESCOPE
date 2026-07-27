"""Unit tests for the provider registry — the swap point for vendors."""

from __future__ import annotations

from collections.abc import Sequence

import pytest

from app.services.market.providers.base import (
    MarketData,
    MarketDataProvider,
    ProviderHealth,
)
from app.services.market.providers.dexscreener import DexScreenerProvider
from app.services.market.providers.registry import (
    available_providers,
    get_provider,
    register_provider,
)

pytestmark = pytest.mark.unit


class StubProvider(MarketDataProvider):
    """Proves a second vendor drops in without touching services."""

    name = "stub"
    batch_size = 5

    async def fetch_many(self, mint_addresses: Sequence[str]) -> dict[str, MarketData]:
        return {
            mint: MarketData(mint_address=mint, provider=self.name) for mint in mint_addresses
        }

    async def health(self) -> ProviderHealth:
        return ProviderHealth(name=self.name, available=True, circuit_state="closed")


def test_default_provider_is_dexscreener() -> None:
    assert isinstance(get_provider(), DexScreenerProvider)


def test_unknown_provider_fails_loudly() -> None:
    """A configuration typo must not silently fall back to a default."""
    with pytest.raises(ValueError, match="Unknown market provider"):
        get_provider("does-not-exist")


def test_name_is_case_insensitive() -> None:
    assert get_provider("DexScreener").name == "dexscreener"


def test_a_new_provider_can_be_registered_and_selected() -> None:
    register_provider(StubProvider.name, StubProvider)
    try:
        assert "stub" in available_providers()
        provider = get_provider("stub")
        assert isinstance(provider, StubProvider)
        assert provider.batch_size == 5
    finally:
        from app.services.market.providers import registry

        registry._PROVIDERS.pop("stub", None)


async def test_fetch_one_delegates_to_fetch_many() -> None:
    """The interface's convenience wrapper must work for any implementation."""
    data = await StubProvider().fetch_one("MintX")
    assert data is not None
    assert data.mint_address == "MintX"
    assert data.provider == "stub"


async def test_fetch_one_returns_none_when_absent() -> None:
    class EmptyProvider(StubProvider):
        async def fetch_many(self, mint_addresses: Sequence[str]) -> dict[str, MarketData]:
            return {}

    assert await EmptyProvider().fetch_one("MintX") is None


async def test_provider_context_manager_starts_and_closes() -> None:
    async with StubProvider() as provider:
        assert await provider.fetch_one("MintX") is not None


def test_market_data_has_market_flag() -> None:
    assert not MarketData(mint_address="m").has_market
    assert MarketData(mint_address="m", pool_address="p").has_market
    assert MarketData(mint_address="m", price_usd=1).has_market  # type: ignore[arg-type]
