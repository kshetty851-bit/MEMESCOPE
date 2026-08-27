"""RPC registry.

The single place that knows concrete RPC classes. Services ask for "the
configured node" and receive a `SolanaRPC`; adding a vendor means registering
one class here and nothing else in the codebase changes.

Deliberately identical in shape to `services/market/providers/registry` — the
platform already had this pattern for market data, and a second abstraction
that behaved differently would be one more thing to learn for no gain.
"""

from __future__ import annotations

from collections.abc import Callable

from app.core.config import settings
from app.core.logging import get_logger
from app.services.rpc.base import SolanaRPC
from app.services.rpc.chainstack import ChainstackRPC
from app.services.rpc.helius import HeliusRPC
from app.services.rpc.router import FallbackRPC
from app.services.rpc.standard import StandardSolanaRPC

logger = get_logger(__name__)

RpcFactory = Callable[[], SolanaRPC]

_PROVIDERS: dict[str, RpcFactory] = {
    StandardSolanaRPC.name: StandardSolanaRPC,
    HeliusRPC.name: HeliusRPC,
    ChainstackRPC.name: ChainstackRPC,
    # Chainstack primary -> Helius fallback -> unavailable. Public never.
    FallbackRPC.name: FallbackRPC,
}


def get_research_rpc() -> SolanaRPC:
    """The only RPC research collectors may use: the production router.

    Never the public endpoint — a collector that silently leaned on it is how
    holder data became sixty failure rows and one datum. With nothing
    configured the router refuses loudly, and the collector records honest
    failure rows instead of quiet zeros.
    """
    return FallbackRPC()


def register_rpc(name: str, factory: RpcFactory) -> None:
    """Register an implementation. Used by tests and future vendors."""
    _PROVIDERS[name] = factory


def available_rpcs() -> tuple[str, ...]:
    return tuple(sorted(_PROVIDERS))


def get_rpc(name: str | None = None) -> SolanaRPC:
    """Construct the configured node.

    An unknown name falls back to the standard client rather than raising. The
    fallback is the *vendor-neutral* one on purpose: a typo in configuration
    should leave the platform running against a plain endpoint with a warning,
    not dead — and never silently on a vendor the operator did not ask for.
    """
    key = (name or settings.SOLANA_RPC_PROVIDER).strip().lower()
    factory = _PROVIDERS.get(key)
    if factory is None:
        logger.warning(
            "rpc_provider_unknown",
            requested=key,
            available=available_rpcs(),
            using=StandardSolanaRPC.name,
        )
        factory = StandardSolanaRPC
    return factory()
