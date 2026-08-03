"""The providers that exist, and the one place that knows they exist.

Registration happens here rather than in `registry.py` so that module stays
about the mechanism. Adding a provider in a future sprint is a module plus one
line below — the engine is not touched.

Future providers (holder growth, community surge, whale accumulation, builder
activity, narrative acceleration) register here as **non-operational** with the
reason they cannot run, so the gap stays visible in the API surface instead of
being an undocumented absence. See ARCHITECTURE_DECISIONS.md §14 for which
signals the platform holds data for today.
"""

from app.opportunities.providers.base import SignalProvider
from app.opportunities.providers.breakout import BreakoutProvider
from app.opportunities.providers.fresh_graduation import FreshGraduationProvider
from app.opportunities.providers.near_graduation import NearGraduationProvider
from app.opportunities.providers.registry import (
    DuplicateProviderError,
    ProviderRegistry,
    UnknownProviderError,
    registry,
)


def register_default_providers(target: ProviderRegistry = registry) -> ProviderRegistry:
    """Populate a registry with every provider this build ships.

    Idempotent by id: calling it twice on the same registry is a programming
    error and raises, which is what catches a double import wiring bug at
    startup rather than at the first detection cycle.
    """
    target.register(FreshGraduationProvider())
    # Registered even while non-operational, which is the point of the
    # `operational` flag: a provider that declares why it cannot run is a fact a
    # reader can weigh, while a missing one is invisible. It starts emitting the
    # moment `OPPORTUNITY_NEAR_GRADUATION_ENABLED` is set — see the module
    # docstring for what has to be true of the data first.
    target.register(NearGraduationProvider())
    # Operational from the day it ships: it needs price and hourly volume, both
    # of which the platform already stores for every venue. No flag — a flag
    # here would imply a doubt the measurement does not support.
    target.register(BreakoutProvider())
    return target


register_default_providers()

__all__ = [
    "BreakoutProvider",
    "DuplicateProviderError",
    "FreshGraduationProvider",
    "NearGraduationProvider",
    "ProviderRegistry",
    "SignalProvider",
    "UnknownProviderError",
    "register_default_providers",
    "registry",
]
