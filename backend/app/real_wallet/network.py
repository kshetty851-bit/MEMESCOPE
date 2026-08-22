"""Network and public-address guards for the dedicated wallet surface.

The scanner's RPC configuration is intentionally not reused here.  A wallet
reader must name its cluster, verify it through ``getGenesisHash``, and refuse
to show a balance when the endpoint does not match that declaration.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlparse

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


def rpc_host_allowed(url: str, *, allowlist: Sequence[str]) -> bool:
    """Whether a wallet RPC endpoint is one we approved in advance.

    `REAL_WALLET_RPC_URL` is configuration, and configuration is editable by
    whoever can edit an environment. Without this, a misconfigured or hostile
    endpoint could answer `getGenesisHash` with mainnet's hash while serving
    fabricated balances, stale blockhashes, or a submission black hole. The
    genesis check proves *which chain the endpoint claims*; this proves *which
    endpoint we agreed to ask*. Both are needed, and neither substitutes.

    An empty allowlist permits nothing. Fail-closed is the only safe default
    for a value whose whole purpose is to narrow.
    """
    host = (urlparse(url).hostname or "").lower()
    if not host:
        return False
    return host in {entry.strip().lower() for entry in allowlist if entry.strip()}


class WalletNetworkBlockedError(RuntimeError):
    """A write path was not proven to target the configured, allowlisted chain."""


async def require_verified_network(
    rpc: SolanaRPC,
    *,
    configured_network: str,
    rpc_url: str,
    allowed_rpc_hosts: Sequence[str],
) -> WalletNetworkStatus:
    """Hard-stop any real execution step that is not on the proven chain.

    The mainnet counterpart of `require_verified_devnet`, and deliberately one
    check stricter: the endpoint's host must be on the allowlist *before* it is
    trusted to answer what chain it is. Asking an unapproved host to identify
    itself and then believing the answer is not verification.

    Callers must invoke this before order assembly, before signing, and again
    before submission. A wrong-network read is a display bug; a wrong-network
    signature is a lost wallet.
    """
    if configured_network not in GENESIS_HASHES:
        raise WalletNetworkBlockedError("wallet_network_unsupported")
    if not rpc_host_allowed(rpc_url, allowlist=allowed_rpc_hosts):
        raise WalletNetworkBlockedError("wallet_rpc_host_not_allowed")
    status = await verify_wallet_network(rpc, network=configured_network)
    if not status.verified:
        raise WalletNetworkBlockedError(status.error or "wallet_network_unverified")
    return status


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
