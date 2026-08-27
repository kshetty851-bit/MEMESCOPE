"""Move SOL out of the execution wallet, to one address and no other.

This is the only path in MEMESCOPE that moves money without a trade, and it is
deliberately the narrowest one in the system. It does exactly one thing: a
canonical System Program transfer from the execution wallet to the single
nominated withdrawal address.

## Why it is safe to have at all

Every other money path can lose value — a swap buys something that might be
worthless. This one cannot. The destination is fixed in configuration, checked
here, and checked AGAIN inside the isolated signer against the signer's own copy
of the setting. A caller that has been fully compromised can, at worst, send the
operator their own money.

That asymmetry is why this exists while trading stayed gated for months.

## What is verified, and where

  1. here      the destination is the nominated one, the amount leaves the fee
                reserve intact, and the wallet is on the chain we think it is
  2. inspector `inspect_native_transfer` re-derives account count, account
                ORDER, fee payer, destination, program id, instruction
                discriminator and lamports from the assembled bytes — a valid
                transaction is not automatically the intended transaction
  3. signer    the same inspection again, inside the process that holds the key,
                against settings that process reads for itself

Three independent checks of the same fact, because the first two run where an
attacker who reached the API already is.

## What it does not do

It does not retry. A submitted transfer whose response was lost is an UNCERTAIN
transfer, and asking again is how one withdrawal becomes two. The signature is
returned and the operator can look it up; the wallet's balance is the truth.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.core.config import settings
from app.core.logging import get_logger
from app.real_wallet import withdrawal
from app.real_wallet.devnet_transaction import (
    DevnetTransactionValidationError,
    NativeTransferSpec,
    build_unsigned_native_transfer,
    inspect_native_transfer,
)
from app.real_wallet.network import require_verified_network
from app.real_wallet.tx_inspect import lamports_from_sol
from app.services.rpc.base import SolanaRPC

logger = get_logger(__name__)


class WithdrawError(RuntimeError):
    """A withdrawal was refused. The message names which check refused it."""


@dataclass(frozen=True, slots=True)
class PreparedWithdrawal:
    """One assembled, inspected, unsigned transfer."""

    unsigned_transaction: str
    destination: str
    lamports: int
    fingerprint: str
    blockhash: str

    @property
    def sol(self) -> Decimal:
        return Decimal(self.lamports).scaleb(-9)


async def prepare(
    rpc: SolanaRPC, *, sol_amount: Decimal, balance_lamports: int
) -> PreparedWithdrawal:
    """Assemble and inspect a transfer. Signs nothing and submits nothing."""
    wallet = settings.REAL_WALLET_PUBLIC_KEY.strip()
    if not wallet:
        raise WithdrawError("wallet_not_configured")

    # The destination is never a parameter. It cannot be passed in, so it cannot
    # be passed in wrongly.
    destination = withdrawal.assert_permitted(
        settings.REAL_WALLET_WITHDRAWAL_ADDRESS.strip()
    )

    if sol_amount <= 0:
        raise WithdrawError("amount_must_be_positive")
    try:
        lamports = lamports_from_sol(sol_amount)
    except ValueError as exc:
        raise WithdrawError("amount_is_not_whole_lamports") from exc

    # The reserve is what pays for the NEXT transaction, including a later
    # withdrawal. Emptying the wallet to the last lamport strands whatever is
    # left in it.
    reserve = lamports_from_sol(Decimal(str(settings.REAL_WALLET_MIN_SOL_FEE_RESERVE)))
    if balance_lamports - lamports < reserve:
        raise WithdrawError(
            f"would_leave_less_than_fee_reserve:{settings.REAL_WALLET_MIN_SOL_FEE_RESERVE}"
        )

    # Which chain, proven, before anything is built. A transfer assembled
    # against the wrong chain is a transfer to an address that may not be the
    # operator's on that chain.
    await require_verified_network(
        rpc,
        configured_network=settings.REAL_WALLET_NETWORK,
        rpc_url=settings.REAL_WALLET_RPC_URL,
        allowed_rpc_hosts=settings.REAL_WALLET_ALLOWED_RPC_HOSTS,
    )

    blockhash = await _latest_blockhash(rpc)
    spec = NativeTransferSpec(
        fee_payer=wallet, destination=destination, lamports=lamports
    )
    encoded = build_unsigned_native_transfer(spec=spec, blockhash=blockhash)
    try:
        # Re-derived from the assembled BYTES, not from the spec that produced
        # them. A valid transaction is not automatically the intended one.
        inspected = inspect_native_transfer(encoded, expected=spec)
    except DevnetTransactionValidationError as exc:
        raise WithdrawError(f"assembled_transfer_rejected:{exc}") from exc

    logger.warning(
        "real_wallet_withdrawal_prepared",
        destination=destination, lamports=lamports,
        fingerprint=inspected.fingerprint[:16],
    )
    return PreparedWithdrawal(
        unsigned_transaction=encoded,
        destination=destination,
        lamports=lamports,
        fingerprint=inspected.fingerprint,
        blockhash=blockhash,
    )


async def _latest_blockhash(rpc: SolanaRPC) -> str:
    response = await rpc.call("getLatestBlockhash", [{"commitment": "finalized"}])
    value = (response or {}).get("value") if isinstance(response, dict) else None
    blockhash = (value or {}).get("blockhash") if isinstance(value, dict) else None
    if not isinstance(blockhash, str) or not blockhash:
        raise WithdrawError("blockhash_unavailable")
    return blockhash


async def submit(rpc: SolanaRPC, *, signed_transaction: str) -> str:
    """Send once. Never retry.

    A submitted transfer whose response was lost is an UNCERTAIN transfer, and
    asking again is how one withdrawal becomes two. On any error the caller is
    told the outcome is unknown and pointed at the chain, which is the only
    thing that can settle it.
    """
    response = await rpc.call(
        "sendTransaction",
        [signed_transaction, {"encoding": "base64", "maxRetries": 0,
                              "preflightCommitment": "confirmed"}],
        attempts=1,
    )
    if not isinstance(response, str) or not response:
        raise WithdrawError("submission_result_unreadable")
    return response


__all__ = ["PreparedWithdrawal", "WithdrawError", "prepare", "submit"]
