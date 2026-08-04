"""Compatibility surface for the pre-abstraction Helius client.

The implementation moved to `services/rpc/` in Sprint 13, where Helius became
one `SolanaRPC` among several rather than the thing the platform was built on.
This module stays so existing imports keep working, and so the move reads as one
reviewable change rather than a rename touching a dozen call sites.

Aliases, not subclasses: `HeliusClient is HeliusRPC` is true, so an `isinstance`
check or a stubbed injection written against either name behaves identically.
Nothing here adds behaviour.

**New code should import from `app.services.rpc`.** Naming the vendor is now a
choice about a specific node, and most callers do not need to make it — they
want `get_rpc()`, which returns whatever is configured.
"""

from __future__ import annotations

from app.services.rpc.base import RpcError, RpcRateLimitError
from app.services.rpc.helius import HeliusRPC

#: The old names, bound to the new implementations.
HeliusClient = HeliusRPC
HeliusError = RpcError
HeliusRateLimitError = RpcRateLimitError

__all__ = [
    "HeliusClient",
    "HeliusError",
    "HeliusRPC",
    "HeliusRateLimitError",
    "RpcError",
    "RpcRateLimitError",
]
