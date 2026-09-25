"""The family members' OWN Solana wallets (2026-09-25).

Karthik asked for each of Jaya, Asha and Apoorva to have an address of their
own to deposit to, and to trade individually. This module is the one place
that says which public key belongs to whom. It holds no secret: the keys live
as 0600 files that only the isolated signer mounts, and the signer checks each
one against the public key pinned here before it will sign anything with it.

Configured as ``REAL_WALLET_FAMILY_WALLETS="jaya=<pubkey>,asha=<pubkey>,..."``
in the host's env file — not in this repository, which is public.

Fail-closed: a malformed entry, an unknown member, a repeated key, a key equal
to the owner's wallet or to the withdrawal address is a configuration error,
and every caller treats a configuration error as "no family wallets at all".
A half-understood key map is the one thing a signer must never act on.

Stage 1 of 2. With this in place a member has an address, a balance and a way
out — a withdrawal that can only go to Karthik's nominated address, exactly
like his own wallet's. Trading from these wallets is stage 2; until then the
signer signs nothing but those withdrawals for them.
"""

from __future__ import annotations

from app.core.config import settings
from app.real_wallet.family import MEMBERS
from app.real_wallet.network import is_valid_wallet_address


class FamilyWalletConfigError(ValueError):
    """The family wallet map is not something a signer may act on."""


def parse(raw: str, *, owner: str, withdrawal: str) -> dict[str, str]:
    """``"jaya=<pk>,asha=<pk>"`` -> ``{"JAYA": "<pk>", ...}``, or raise."""
    out: dict[str, str] = {}
    for entry in (e.strip() for e in raw.split(",")):
        if not entry:
            continue
        name, sep, key = entry.partition("=")
        member, key = name.strip().upper(), key.strip()
        if not sep or member not in MEMBERS:
            raise FamilyWalletConfigError(f"unknown_family_member:{name.strip() or '?'}")
        if member in out:
            raise FamilyWalletConfigError(f"family_member_listed_twice:{member}")
        if not is_valid_wallet_address(key):
            raise FamilyWalletConfigError(f"invalid_family_wallet:{member}")
        if key in (owner, withdrawal):
            # A family wallet that IS the owner's wallet would let the family
            # path sign for the owner; one that is the withdrawal address would
            # make "withdraw to Karthik" a transfer to itself.
            raise FamilyWalletConfigError(f"family_wallet_collides:{member}")
        if key in out.values():
            raise FamilyWalletConfigError(f"family_wallet_shared:{member}")
        out[member] = key
    return out


def pinned() -> dict[str, str]:
    """The configured map, validated against this process's own settings."""
    return parse(settings.REAL_WALLET_FAMILY_WALLETS,
                 owner=settings.REAL_WALLET_PUBLIC_KEY.strip(),
                 withdrawal=settings.REAL_WALLET_WITHDRAWAL_ADDRESS.strip())


def address(member: str) -> str | None:
    """A member's own address, or None if they have none (or the map is bad)."""
    try:
        return pinned().get(member.upper())
    except FamilyWalletConfigError:
        return None


def member_for(public_key: str) -> str | None:
    """Whose wallet this is, or None. Raises on a bad map: a signer asking
    this question must not read a malformed map as "nobody's"."""
    for member, key in pinned().items():
        if key == public_key:
            return member
    return None


__all__ = ["FamilyWalletConfigError", "address", "member_for", "parse", "pinned"]
