"""The only Phase 2 transaction shape: a tiny native-SOL devnet transfer.

Jupiter's route and swap assembly APIs are mainnet-oriented.  Treating a
mainnet quote as a devnet quote would be a dangerous fiction, so Phase 2 proves
the custody and lifecycle plumbing with exactly one highly inspectable System
Program transfer.  This module refuses every other message shape.
"""

from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass
from typing import Any

from solders.hash import Hash
from solders.message import Message
from solders.pubkey import Pubkey
from solders.system_program import ID as SYSTEM_PROGRAM_ID
from solders.system_program import TransferParams, transfer
from solders.transaction import Transaction

NATIVE_SOL_MINT = "So11111111111111111111111111111111111111112"
SYSTEM_TRANSFER_DISCRIMINANT = 2


class DevnetTransactionValidationError(ValueError):
    """A caller tried to send a transaction outside the tiny allowlist."""


@dataclass(frozen=True, slots=True)
class NativeTransferSpec:
    """The server-authorized transfer semantics, never caller-supplied bytes."""

    fee_payer: str
    destination: str
    lamports: int


@dataclass(frozen=True, slots=True)
class InspectedNativeTransfer:
    fee_payer: str
    destination: str
    lamports: int
    recent_blockhash: str
    fingerprint: str

    def as_metadata(self) -> dict[str, Any]:
        return {
            "kind": "system_transfer",
            "program_id": str(SYSTEM_PROGRAM_ID),
            "fee_payer": self.fee_payer,
            "destination": self.destination,
            "lamports": self.lamports,
            "recent_blockhash": self.recent_blockhash,
        }


def transaction_fingerprint(encoded_transaction: str) -> str:
    """Stable hash of exact transaction bytes, before and after every boundary."""
    try:
        raw = base64.b64decode(encoded_transaction, validate=True)
    except Exception as exc:
        raise DevnetTransactionValidationError("malformed_transaction_encoding") from exc
    return hashlib.sha256(raw).hexdigest()


def build_unsigned_native_transfer(*, spec: NativeTransferSpec, blockhash: str) -> str:
    """Build a serialised unsigned legacy transaction from the allowed spec."""
    _validate_spec(spec)
    try:
        message = Message.new_with_blockhash(
            [
                transfer(
                    TransferParams(
                        from_pubkey=Pubkey.from_string(spec.fee_payer),
                        to_pubkey=Pubkey.from_string(spec.destination),
                        lamports=spec.lamports,
                    )
                )
            ],
            Pubkey.from_string(spec.fee_payer),
            Hash.from_string(blockhash),
        )
        transaction = Transaction.new_unsigned(message)
    except Exception as exc:
        raise DevnetTransactionValidationError("native_transfer_construction_failed") from exc
    encoded = base64.b64encode(bytes(transaction)).decode("ascii")
    inspect_native_transfer(encoded, expected=spec)
    return encoded


def inspect_native_transfer(
    encoded_transaction: str, *, expected: NativeTransferSpec
) -> InspectedNativeTransfer:
    """Allow exactly one canonical System Program transfer and nothing else.

    This closes the common signing-boundary failure mode: a valid Solana
    transaction is not automatically *the intended* transaction.  Account
    order, fee payer, writable/signer set, program, instruction discriminator,
    destination, and amount are all checked against durable server-authored
    data before simulation and again in the isolated signer.
    """
    _validate_spec(expected)
    try:
        raw = base64.b64decode(encoded_transaction, validate=True)
        transaction = Transaction.from_bytes(raw)
        message = transaction.message
        account_keys = list(message.account_keys)
        instructions = list(message.instructions)
    except Exception as exc:
        raise DevnetTransactionValidationError("malformed_native_transfer") from exc

    if len(account_keys) != 3:
        raise DevnetTransactionValidationError("unexpected_account_count")
    expected_keys = [expected.fee_payer, expected.destination, str(SYSTEM_PROGRAM_ID)]
    if [str(key) for key in account_keys] != expected_keys:
        if str(account_keys[0]) != expected.fee_payer:
            raise DevnetTransactionValidationError("unexpected_fee_payer")
        if str(account_keys[1]) != expected.destination:
            raise DevnetTransactionValidationError("unexpected_destination")
        raise DevnetTransactionValidationError("unexpected_account")
    if not message.is_signer(0) or not _is_writable(message, 0, len(account_keys)):
        raise DevnetTransactionValidationError("unexpected_fee_payer_permissions")
    if message.is_signer(1) or not _is_writable(message, 1, len(account_keys)):
        raise DevnetTransactionValidationError("unexpected_destination_permissions")
    if message.is_signer(2) or _is_writable(message, 2, len(account_keys)):
        raise DevnetTransactionValidationError("unexpected_program_permissions")
    if len(instructions) != 1:
        raise DevnetTransactionValidationError("unexpected_instruction_count")
    instruction = instructions[0]
    if instruction.program_id_index != 2:
        raise DevnetTransactionValidationError("unexpected_program_id")
    if list(instruction.accounts) != [0, 1]:
        raise DevnetTransactionValidationError("unexpected_instruction_accounts")
    data = bytes(instruction.data)
    if len(data) != 12 or int.from_bytes(data[:4], "little") != SYSTEM_TRANSFER_DISCRIMINANT:
        raise DevnetTransactionValidationError("unexpected_instruction_type")
    lamports = int.from_bytes(data[4:], "little")
    if lamports != expected.lamports:
        raise DevnetTransactionValidationError("unexpected_amount")
    blockhash = str(message.recent_blockhash)
    if not blockhash or blockhash == "11111111111111111111111111111111":
        raise DevnetTransactionValidationError("missing_recent_blockhash")
    return InspectedNativeTransfer(
        fee_payer=expected.fee_payer,
        destination=expected.destination,
        lamports=lamports,
        recent_blockhash=blockhash,
        fingerprint=hashlib.sha256(raw).hexdigest(),
    )


def _validate_spec(spec: NativeTransferSpec) -> None:
    if spec.lamports <= 0:
        raise DevnetTransactionValidationError("non_positive_transfer_amount")
    try:
        Pubkey.from_string(spec.fee_payer)
        Pubkey.from_string(spec.destination)
    except Exception as exc:
        raise DevnetTransactionValidationError("invalid_transfer_address") from exc
    if spec.fee_payer == spec.destination:
        raise DevnetTransactionValidationError("self_transfer_not_permitted")


def _is_writable(message: Message, index: int, account_count: int) -> bool:
    """Derive writability from the legacy message header's canonical layout."""
    header = message.header
    if index < header.num_required_signatures:
        return index < header.num_required_signatures - header.num_readonly_signed_accounts
    return index < account_count - header.num_readonly_unsigned_accounts
