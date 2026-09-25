"""Give back the rent parked in the wallet's empty token accounts.

Every buy opens a token account, and opening one parks rent in it — about
0.0015 SOL, roughly $0.15. Selling the tokens leaves the account open and the
rent parked. At the graduation arm's pace (~60 trades a day) that is ~$9 a day
the wallet cannot spend, which is half of what the paper board says it makes.
Closing an empty account returns the rent to the wallet.

## Why this is safe to sign automatically

A token-program `CloseAccount` does one thing: it moves the account's lamports
to the destination and deletes the account. The program itself refuses it
while the account holds any tokens (or withheld Token-2022 fees, or is frozen),
so it cannot destroy anything of value. What would matter is WHERE the lamports
go — so the destination must be the wallet itself, and the only signer the
wallet. `inspect` checks exactly that from the assembled bytes, and the
isolated signer runs the same inspection again before it signs; nothing else is
accepted, not even a compute-budget instruction.

## What it leaves alone

Anything a trade might still be using: the whole sweep waits while any intent
is in flight, and accounts for mints with an open position or an unresolved
intent are kept. Wrapped SOL is Jupiter's to manage. Accounts someone else may
close, frozen ones, and ones holding withheld fees would fail on chain, so they
are not attempted.

One account per transaction, so one refusal cannot hold up the rest, and every
send is preflighted: a close that would fail is rejected before it costs a fee.
A dropped close is simply found again on the next sweep.
"""

from __future__ import annotations

import base64
import hashlib
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from solders.hash import Hash
from solders.instruction import AccountMeta, Instruction
from solders.message import Message
from solders.pubkey import Pubkey
from solders.transaction import Transaction
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.models.real_wallet_execution import RealWalletLiveIntent, RealWalletPosition
from app.real_wallet.balance import (
    TOKEN_PROGRAM_IDS,
    ExecutionWalletBalanceService,
    ExecutionWalletTokenBalance,
)
from app.real_wallet.live_readiness import ExecutionState
from app.real_wallet.live_repository import LiveIntentRepository
from app.real_wallet.mainnet_signer_client import (
    MainnetSignerRejectedError,
    MainnetSignerUnavailableError,
    UnixMainnetSignerClient,
)
from app.real_wallet.network import require_verified_network
from app.services.rpc.base import RpcError, SolanaRPC
from app.services.rpc.standard import StandardSolanaRPC

logger = get_logger(__name__)

#: `CloseAccount` in both the SPL Token and the Token-2022 programs.
CLOSE_ACCOUNT = 9
TOKEN_PROGRAMS = frozenset(TOKEN_PROGRAM_IDS)
NATIVE_MINT = "So11111111111111111111111111111111111111112"
#: A transaction may close this many accounts; the sweep sends one at a time.
MAX_CLOSES_PER_TRANSACTION = 8
#: How many accounts one sweep closes. The rest wait for the next sweep.
MAX_CLOSES_PER_SWEEP = 10

#: A trade in motion. The sweep waits for it to land rather than close an
#: account under it.
IN_FLIGHT = (ExecutionState.CREATED, ExecutionState.SAFETY_APPROVED,
             ExecutionState.ORDER_CREATED, ExecutionState.SIGNED,
             ExecutionState.SUBMITTED)


class AccountCloseRejectedError(ValueError):
    """The transaction is not one that only closes this wallet's accounts into itself."""


@dataclass(frozen=True, slots=True)
class InspectedClose:
    accounts: tuple[str, ...]
    fingerprint: str


def build(*, wallet: str, accounts: Sequence[tuple[str, str]], blockhash: str) -> str:
    """Unsigned legacy transaction closing (account, token program) pairs into the wallet."""
    try:
        owner = Pubkey.from_string(wallet)
        instructions = [
            Instruction(
                Pubkey.from_string(program),
                bytes([CLOSE_ACCOUNT]),
                [
                    AccountMeta(Pubkey.from_string(target), is_signer=False, is_writable=True),
                    AccountMeta(owner, is_signer=False, is_writable=True),   # destination
                    AccountMeta(owner, is_signer=True, is_writable=False),   # owner
                ],
            )
            for target, program in accounts
        ]
        message = Message.new_with_blockhash(instructions, owner, Hash.from_string(blockhash))
        encoded = base64.b64encode(bytes(Transaction.new_unsigned(message))).decode("ascii")
    except Exception as exc:
        raise AccountCloseRejectedError("close_construction_failed") from exc
    inspect(encoded, wallet=wallet)
    return encoded


def inspect(encoded_transaction: str, *, wallet: str) -> InspectedClose:
    """Accept only `CloseAccount`s that pay this wallet and are signed by it alone.

    Read from the assembled bytes, never from what the builder was asked for: a
    valid transaction is not automatically the intended one.
    """
    try:
        raw = base64.b64decode(encoded_transaction, validate=True)
        message = Transaction.from_bytes(raw).message
        keys = [str(key) for key in message.account_keys]
        instructions = list(message.instructions)
        header = message.header
    except Exception as exc:
        raise AccountCloseRejectedError("malformed_close_transaction") from exc

    if not keys or keys[0] != wallet:
        raise AccountCloseRejectedError("fee_payer_is_not_the_wallet")
    if header.num_required_signatures != 1 or header.num_readonly_signed_accounts != 0:
        raise AccountCloseRejectedError("only_the_wallet_may_sign")
    if not 1 <= len(instructions) <= MAX_CLOSES_PER_TRANSACTION:
        raise AccountCloseRejectedError("unexpected_instruction_count")
    if str(message.recent_blockhash) in ("", "11111111111111111111111111111111"):
        raise AccountCloseRejectedError("missing_recent_blockhash")

    closed: list[str] = []
    programs: set[int] = set()
    for ix in instructions:
        program = ix.program_id_index
        if program >= len(keys) or keys[program] not in TOKEN_PROGRAMS:
            raise AccountCloseRejectedError("not_a_token_program")
        if bytes(ix.data) != bytes([CLOSE_ACCOUNT]):
            raise AccountCloseRejectedError("not_a_close_account")
        accounts = list(ix.accounts)
        # [account, destination, owner]: the rent goes to the wallet, and the
        # wallet is the authority.
        if len(accounts) != 3 or accounts[1] != 0 or accounts[2] != 0:
            raise AccountCloseRejectedError("close_must_pay_and_be_signed_by_the_wallet")
        target = accounts[0]
        if target in (0, program) or target >= len(keys) or keys[target] in closed:
            raise AccountCloseRejectedError("unexpected_close_target")
        if not _writable(message, target, len(keys)):
            raise AccountCloseRejectedError("close_target_not_writable")
        programs.add(program)
        closed.append(keys[target])

    for program in programs:
        if _writable(message, program, len(keys)):
            raise AccountCloseRejectedError("program_marked_writable")
    # Nothing rides along: every key is the wallet, a closed account or a program.
    if len(keys) != 1 + len(closed) + len(programs):
        raise AccountCloseRejectedError("unexpected_account")
    return InspectedClose(accounts=tuple(closed),
                          fingerprint=hashlib.sha256(raw).hexdigest())


def _writable(message: Message, index: int, count: int) -> bool:
    header = message.header
    if index < header.num_required_signatures:
        return index < header.num_required_signatures - header.num_readonly_signed_accounts
    return index < count - header.num_readonly_unsigned_accounts


def closable(
    balances: Iterable[ExecutionWalletTokenBalance], *, wallet: str,
    keep_mints: frozenset[str] = frozenset(),
) -> list[ExecutionWalletTokenBalance]:
    """The accounts a close would succeed on and nothing still needs."""
    return [
        b for b in balances
        if b.raw_amount == "0"
        and b.program_id in TOKEN_PROGRAMS
        and b.state == "initialized"
        and b.close_authority in (None, wallet)
        and not b.is_native
        and b.mint_address != NATIVE_MINT
        and b.withheld_amount == 0
        and b.mint_address not in keep_mints
    ]


@dataclass(frozen=True, slots=True)
class SweepOutcome:
    closed: tuple[str, ...] = ()
    refused: tuple[str, ...] = ()
    skipped: str | None = None
    signatures: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, object]:
        return {"closed": len(self.closed), "refused": len(self.refused),
                "skipped": self.skipped}


async def sweep(
    session: AsyncSession, *,
    rpc: SolanaRPC | None = None,
    signer: UnixMainnetSignerClient | None = None,
    limit: int = MAX_CLOSES_PER_SWEEP,
    wallet: str | None = None,
) -> SweepOutcome:
    """Close what is safe to close, one account per transaction.

    ``wallet``: whose accounts — the owner's by default, or a family member's
    own wallet (2026-09-25). Only that wallet's open positions are kept, and
    the signer re-proves the rent goes back to that same wallet.
    """
    owner = settings.REAL_WALLET_PUBLIC_KEY.strip()
    family = wallet is not None and wallet != owner
    wallet = (wallet or owner).strip()
    if not wallet:
        return SweepOutcome(skipped="wallet_not_configured")
    # Automatic transactions follow the same two flags as trading. The autotrade
    # switch does not apply: a stopped wallet should still get its rent back.
    if (settings.REAL_WALLET_EXECUTION_MODE != "live"
            or not settings.REAL_WALLET_EXECUTION_ENABLED):
        return SweepOutcome(skipped="execution_not_live")
    if await LiveIntentRepository(session).active_kill_switches():
        return SweepOutcome(skipped="kill_switch_active")
    if await session.scalar(select(RealWalletLiveIntent.id).where(
            RealWalletLiveIntent.state.in_(IN_FLIGHT)).limit(1)):
        return SweepOutcome(skipped="trade_in_flight")
    # This wallet's open coins — and any open position with no wallet
    # recorded, which every sweep keeps: an account left open costs rent,
    # one closed under a position cannot be undone.
    keep = frozenset((await session.scalars(
        select(RealWalletPosition.mint_address).where(
            RealWalletPosition.status == "OPEN",
            or_(RealWalletPosition.wallet_public_key == wallet,
                RealWalletPosition.wallet_public_key.is_(None)))
        .union(select(RealWalletLiveIntent.mint_address).where(
            RealWalletLiveIntent.state == ExecutionState.RECONCILIATION_REQUIRED,
            RealWalletLiveIntent.wallet_public_key == wallet))
    )).all())

    rpc = rpc or StandardSolanaRPC(rpc_url=settings.REAL_WALLET_RPC_URL)
    signer = signer or UnixMainnetSignerClient()
    closed: list[str] = []
    refused: list[str] = []
    signatures: list[str] = []
    async with rpc:
        await require_verified_network(
            rpc,
            configured_network=settings.REAL_WALLET_NETWORK,
            rpc_url=settings.REAL_WALLET_RPC_URL,
            allowed_rpc_hosts=settings.REAL_WALLET_ALLOWED_RPC_HOSTS,
        )
        balances = await ExecutionWalletBalanceService(rpc).get_spl_balances(wallet)
        targets = closable(balances, wallet=wallet, keep_mints=keep)[:limit]
        if not targets:
            return SweepOutcome()
        blockhash = await _latest_blockhash(rpc)
        for target in targets:
            try:
                encoded = build(wallet=wallet, blockhash=blockhash,
                                accounts=[(target.token_account, target.program_id)])
                # The owner's call is exactly what it always was; only a
                # family wallet names itself.
                signed = await (signer.sign_close_accounts(encoded, wallet=wallet)
                                if family else signer.sign_close_accounts(encoded))
                signatures.append(await _send(rpc, signed["signed_transaction"]))
            except (AccountCloseRejectedError, MainnetSignerRejectedError,
                    MainnetSignerUnavailableError, RpcError) as exc:
                logger.warning("real_wallet_account_close_refused",
                               account=target.token_account, reason=str(exc)[:160])
                refused.append(target.token_account)
                continue
            closed.append(target.token_account)
            logger.info("real_wallet_account_closed", account=target.token_account,
                        mint=target.mint_address, signature=signatures[-1])
    return SweepOutcome(closed=tuple(closed), refused=tuple(refused),
                        signatures=tuple(signatures))


async def _latest_blockhash(rpc: SolanaRPC) -> str:
    response = await rpc.call("getLatestBlockhash", [{"commitment": "finalized"}])
    value = response.get("value") if isinstance(response, dict) else None
    blockhash = value.get("blockhash") if isinstance(value, dict) else None
    if not isinstance(blockhash, str) or not blockhash:
        raise RpcError("blockhash_unavailable")
    return blockhash


async def _send(rpc: SolanaRPC, signed_transaction: str) -> str:
    """Preflighted, so a close that would fail is refused before it costs a fee."""
    signature = await rpc.call(
        "sendTransaction",
        [signed_transaction, {"encoding": "base64", "preflightCommitment": "confirmed"}],
        attempts=1,
    )
    if not isinstance(signature, str) or not signature:
        raise RpcError("send_result_unreadable")
    return signature


__all__ = ["AccountCloseRejectedError", "InspectedClose", "SweepOutcome", "build",
           "closable", "inspect", "sweep"]
