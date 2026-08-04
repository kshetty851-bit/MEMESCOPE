"""Solana RPC access, vendor-neutral.

`get_rpc()` returns whatever is configured. Import the concrete classes only
where a specific node is genuinely the subject — the registry is the one place
that should know they exist.
"""

from app.services.rpc.base import (
    RpcDescription,
    RpcError,
    RpcRateLimitError,
    SolanaRPC,
)
from app.services.rpc.registry import available_rpcs, get_rpc, register_rpc

__all__ = [
    "RpcDescription",
    "RpcError",
    "RpcRateLimitError",
    "SolanaRPC",
    "available_rpcs",
    "get_rpc",
    "register_rpc",
]
