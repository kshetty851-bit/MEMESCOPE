"""Provider registration, lookup and isolated execution.

The engine imports this module. It never imports a provider, so adding one is a
registration plus a pure module — the same inversion `services/market/providers`
established for market data and that ADR 0002 demonstrated holds under a whole
new vendor.

**Isolation is enforced here, not trusted.** Providers are pure, so a raised
exception is a bug rather than an expected condition — but one buggy provider
must not cost every other provider's signals on that token. `evaluate_all`
catches, records, and continues.
"""

from __future__ import annotations

from datetime import datetime

from app.core.logging import get_logger
from app.opportunities.models import ObservationWindow, ProviderResult
from app.opportunities.providers.base import SignalProvider

logger = get_logger(__name__)


class DuplicateProviderError(RuntimeError):
    """Two providers claiming the same id.

    Raised at registration rather than tolerated: two providers under one id
    would make signal attribution ambiguous, and the dedup key
    `(opportunity, signal_type, provider_id)` would silently merge them.
    """


class UnknownProviderError(KeyError):
    """A provider id nothing has registered.

    Raised rather than returning None, matching the scoring model registry: a
    typo must not quietly fall back to a default nobody chose.
    """


class ProviderRegistry:
    """The set of providers the engine will run.

    An instance rather than module globals, so a test can build a registry with
    exactly one provider instead of monkeypatching a shared dict.
    """

    def __init__(self) -> None:
        self._providers: dict[str, SignalProvider] = {}

    def register(self, provider: SignalProvider) -> SignalProvider:
        provider_id = provider.meta.provider_id
        if provider_id in self._providers:
            raise DuplicateProviderError(f"provider '{provider_id}' is already registered")
        self._providers[provider_id] = provider
        return provider

    def get(self, provider_id: str) -> SignalProvider:
        try:
            return self._providers[provider_id]
        except KeyError as exc:
            raise UnknownProviderError(
                f"unknown provider '{provider_id}'. Registered: {sorted(self._providers)}"
            ) from exc

    def __contains__(self, provider_id: object) -> bool:
        return provider_id in self._providers

    def __len__(self) -> int:
        return len(self._providers)

    @property
    def ids(self) -> tuple[str, ...]:
        """Registration order preserved, so evaluation order is deterministic."""
        return tuple(self._providers)

    def all(self) -> tuple[SignalProvider, ...]:
        return tuple(self._providers.values())

    def operational(self) -> tuple[SignalProvider, ...]:
        """Providers that have a data source today.

        Non-operational providers stay registered on purpose: their `meta`
        carries the reason they cannot run, so the gap is discoverable rather
        than being an undocumented absence.
        """
        return tuple(
            provider for provider in self._providers.values() if provider.meta.operational
        )

    def evaluate_all(
        self, window: ObservationWindow, *, now: datetime
    ) -> tuple[ProviderResult, ...]:
        """Run every operational provider over one window.

        Returns each provider's `ProviderResult`. A provider that raises is
        logged and skipped — its absence costs its own signals and nothing
        else. Detection for a token must not be all-or-nothing across
        independent sources.
        """
        results: list[ProviderResult] = []
        for provider in self.operational():
            try:
                results.append(provider.evaluate(window, now=now))
            except Exception as exc:
                logger.exception(
                    "signal_provider_failed",
                    provider=provider.meta.provider_id,
                    mint=window.mint_address,
                    error=str(exc),
                    error_type=type(exc).__name__,
                )
        return tuple(results)


#: The process-wide registry the engine uses by default. Populated in
#: `providers/__init__.py`, which is the one place that knows which providers
#: exist — deliberately not here, so this module stays about the mechanism.
registry = ProviderRegistry()
