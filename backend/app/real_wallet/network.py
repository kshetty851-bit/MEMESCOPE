"""Network and public-address guards for the dedicated wallet surface.

The scanner's RPC configuration is intentionally not reused here.  A wallet
reader must name its cluster, verify it through ``getGenesisHash``, and refuse
to show a balance when the endpoint does not match that declaration.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from solders.pubkey import Pubkey

from app.services.rpc.base import SolanaRPC

WalletNetwork = Literal["devnet", "mainnet"]

# Cluster identity is deliberately pinned rather than inferred from an endpoint
# hostname. Devnet can be restarted, so this value is refreshed only by a
# reviewed change after a read-only getGenesisHash verification.
GENESIS_HASHES: dict[WalletNetwork, str] = {
    "devnet": "EtWTRABZaYq6iMfeYKouRu166VU2xqa1wcaWoxPkrZBG",
    "mainnet": "5eykt4UsFv8P8NJdTREpY1vzqKqZKvdpKuc147dw2N9d",
}


def is_valid_wallet_address(value: str) -> bool:
    """Accept only a canonical 32-byte Solana public key, never a secret."""
    try:
        return str(Pubkey.from_string(value.strip())) == value.strip()
    except (TypeError, ValueError):
        return False


@dataclass(frozen=True, slots=True)
class WalletNetworkStatus:
    network: WalletNetwork
    expected_genesis_hash: str
    observed_genesis_hash: str | None
    verified: bool
    error: str | None = None


async def verify_wallet_network(
    rpc: SolanaRPC, *, network: WalletNetwork
) -> WalletNetworkStatus:
    """Verify the endpoint's cluster before reading a configured wallet."""
    expected = GENESIS_HASHES[network]
    try:
        observed = await rpc.call("getGenesisHash", [])
    except Exception:
        return WalletNetworkStatus(network, expected, None, False, "rpc_unavailable")
    if not isinstance(observed, str):
        return WalletNetworkStatus(network, expected, None, False, "invalid_rpc_response")
    return WalletNetworkStatus(
        network=network,
        expected_genesis_hash=expected,
        observed_genesis_hash=observed,
        verified=observed == expected,
        error=None if observed == expected else "network_mismatch",
    )


class DevnetExecutionBlockedError(RuntimeError):
    """A Phase 2 write path was not proven to target devnet."""


async def require_verified_devnet(
    rpc: SolanaRPC, *, configured_network: str
) -> WalletNetworkStatus:
    """Hard-stop every manual execution step outside verified devnet.

    This is deliberately stricter than the read-only wallet check: a configured
    ``mainnet`` value is refused before an RPC call, and an endpoint with any
    other genesis hash is refused after it.  Callers must invoke this before
    construction, simulation, signing, and submission.
    """
    if configured_network != "devnet":
        raise DevnetExecutionBlockedError("phase2_devnet_only")
    status = await verify_wallet_network(rpc, network="devnet")
    if not status.verified:
        raise DevnetExecutionBlockedError(status.error or "devnet_network_unverified")
    return status
