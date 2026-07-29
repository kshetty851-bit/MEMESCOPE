"""Provider registry.

The single place that knows concrete provider classes. Services ask for "the
configured provider" and receive a `MarketDataProvider`; adding a vendor means
registering one class here, and nothing else in the codebase changes.
"""

from __future__ import annotations

from collections.abc import Callable

from app.core.config import settings
from app.core.logging import get_logger
from app.services.market.providers.base import MarketDataProvider
from app.services.market.providers.composite import CompositeProvider
from app.services.market.providers.dexscreener import DexScreenerProvider

logger = get_logger(__name__)

ProviderFactory = Callable[[], MarketDataProvider]


def _composite() -> MarketDataProvider:
    """DexScreener with the GeckoTerminal liquidity fill behind it.

    The primary is constructed here rather than injected because the registry
    is the layer that knows concrete classes; the composite itself stays
    agnostic about which provider it is wrapping.
    """
    return CompositeProvider(DexScreenerProvider())


_PROVIDERS: dict[str, ProviderFactory] = {
    DexScreenerProvider.name: DexScreenerProvider,
    CompositeProvider.name: _composite,
}


def register_provider(name: str, factory: ProviderFactory) -> None:
    """Register an implementation. Used by tests and future vendors."""
    _PROVIDERS[name] = factory


def available_providers() -> tuple[str, ...]:
    return tuple(sorted(_PROVIDERS))


def get_provider(name: str | None = None) -> MarketDataProvider:
    """Construct the configured provider.

    Fails loudly on an unknown name: silently falling back to a default would
    mean a typo in configuration ships wrong data with no signal.
    """
    key = (name or settings.MARKET_PROVIDER).strip().lower()
    factory = _PROVIDERS.get(key)
    if factory is None:
        raise ValueError(
            f"Unknown market provider {key!r}. Available: {', '.join(available_providers())}"
        )
    logger.debug("market_provider_selected", provider=key)
    return factory()
