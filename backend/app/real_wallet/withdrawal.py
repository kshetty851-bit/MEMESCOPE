"""One address SOL may leave for, and one place that decides it.

The wallet is deliberately asymmetric. **Deposits are open**: the execution
address is public, anyone may send to it, and nothing about receiving needs a
permission. **Withdrawals are closed to exactly one destination** — the address
the operator nominated — so the question "where can this money go?" has a single
answer that does not depend on the caller, the signer, or an environment nobody
re-read.

That asymmetry is the whole value. Every other barrier in the real-wallet rail
asks *whether* a transfer may happen; this one bounds *where it can land* if one
of those barriers is ever wrong. A compromised caller that got past the guard,
the transport policy and the release constant could still only return the funds
to their owner.

## Fail closed, in both directions

An unset destination permits nothing rather than anything. This is the same
direction the RPC host list takes, and for the same reason: the failure mode of
"empty means allow all" is total, and the failure mode of "empty means refuse" is
a support ticket.

A destination equal to the execution wallet is also refused. It is not dangerous,
but it is never what an operator meant, and a self-transfer that silently
succeeds hides a misconfiguration until the day it matters.

## What this module is not

It moves nothing. It holds no key, builds no transaction, and calls no RPC. It
answers one question about one string, which is what makes it cheap to audit and
impossible to route around by accident: the check is not a step in a flow that a
future caller might skip, it is a function that the flow cannot complete without.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.config import settings
from app.real_wallet.network import is_valid_wallet_address


class WithdrawalDestinationError(RuntimeError):
    """A withdrawal named a destination this wallet will not send to."""


@dataclass(frozen=True, slots=True)
class WithdrawalPolicy:
    """The nominated destination, and whether it is usable."""

    destination: str
    configured: bool
    reason: str = ""

    @property
    def usable(self) -> bool:
        return self.configured and not self.reason


def policy() -> WithdrawalPolicy:
    """Read and validate the nominated destination. Never raises."""
    address = settings.REAL_WALLET_WITHDRAWAL_ADDRESS.strip()
    if not address:
        return WithdrawalPolicy(
            destination="", configured=False,
            reason="no_withdrawal_address_configured",
        )
    if not is_valid_wallet_address(address):
        return WithdrawalPolicy(
            destination=address, configured=True,
            reason="withdrawal_address_is_not_a_valid_solana_address",
        )
    if address == settings.REAL_WALLET_PUBLIC_KEY.strip():
        return WithdrawalPolicy(
            destination=address, configured=True,
            reason="withdrawal_address_is_the_execution_wallet_itself",
        )
    return WithdrawalPolicy(destination=address, configured=True)


def assert_permitted(destination: str) -> str:
    """Refuse anything but the nominated address. Returns it on success.

    Compared after stripping and never case-folded: base58 is case-sensitive, and
    two addresses differing only in case are two different accounts.
    """
    current = policy()
    if not current.configured:
        raise WithdrawalDestinationError("withdrawal_destination_not_configured")
    if current.reason:
        raise WithdrawalDestinationError(current.reason)
    candidate = (destination or "").strip()
    if not candidate:
        raise WithdrawalDestinationError("withdrawal_destination_missing")
    if candidate != current.destination:
        raise WithdrawalDestinationError("withdrawal_destination_not_permitted")
    return current.destination


__all__ = [
    "WithdrawalDestinationError",
    "WithdrawalPolicy",
    "assert_permitted",
    "policy",
]
