"""Backend-only keypair handling for the dedicated execution wallet.

No caller should receive raw key bytes.  The future execution engine will pass
an intent id to this boundary; it must never pass signer material through a
task, API schema, database row, log, or browser response.
"""

from __future__ import annotations

import json
import os
import stat
from base64 import b64decode, b64encode
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from solders.keypair import Keypair
from solders.transaction import Transaction, VersionedTransaction

from app.real_wallet import tx_inspect


@dataclass(frozen=True, slots=True)
class SignedTransaction:
    """What leaves the signer. Never the key, never the keypair, never a path."""

    signed_transaction: str
    #: Known *before* submission, because it is computed from the message we
    #: just signed. This is what makes a lost submit response reconcilable.
    signature: str
    #: Replay key. The same message signed twice yields the same value.
    message_fingerprint: str
    program_ids: tuple[str, ...]


class ExecutionSignerUnavailableError(RuntimeError):
    """A signer is unavailable: execution must fail closed."""


class ExecutionWalletPublicKeyMismatchError(RuntimeError):
    """The mounted secret does not belong to the configured public address."""


class ExecutionTransactionValidationError(RuntimeError):
    """A Jupiter assembled transaction is not safe to sign."""


class ExecutionSigner(Protocol):
    """Minimal signing boundary for a future execution-only service."""

    @property
    def public_key(self) -> str: ...

    def sign_message(self, message: bytes) -> bytes: ...


def verify_expected_public_key(*, expected_public_key: str, derived_public_key: str) -> None:
    """Pin a loaded signer to the configured dedicated wallet, or fail closed."""
    if not expected_public_key or expected_public_key != derived_public_key:
        raise ExecutionWalletPublicKeyMismatchError("execution_wallet_public_key_mismatch")


class FileExecutionSigner:
    """Signer backed by a JSON keypair file mounted only into the backend.

    Construction is explicit so merely setting a secret-file path cannot load a
    key or change execution behaviour.  This class is not wired to any live
    path in the current release.
    """

    def __init__(self, keypair: Keypair) -> None:
        self._keypair = keypair

    @property
    def public_key(self) -> str:
        return str(self._keypair.pubkey())

    @classmethod
    def load(cls, *, secret_file: Path, expected_public_key: str) -> FileExecutionSigner:
        try:
            mode = stat.S_IMODE(os.stat(secret_file).st_mode)
            if mode & 0o077:
                raise ExecutionSignerUnavailableError(
                    "execution_wallet_secret_file_permissions"
                )
            encoded = json.loads(secret_file.read_text(encoding="utf-8"))
            if not isinstance(encoded, list) or not all(
                isinstance(value, int) for value in encoded
            ):
                raise ValueError("keypair must be a JSON byte array")
            signer = cls(Keypair.from_bytes(bytes(encoded)))
        except (OSError, ValueError, TypeError) as exc:
            raise ExecutionSignerUnavailableError(
                "execution_wallet_signer_unavailable"
            ) from exc
        verify_expected_public_key(
            expected_public_key=expected_public_key, derived_public_key=signer.public_key
        )
        return signer

    def sign_message(self, message: bytes) -> bytes:
        """Unit-testable primitive only; no transaction is built or submitted here."""
        return bytes(self._keypair.sign_message(message))

    def sign_jupiter_transaction(
        self,
        encoded_transaction: str,
        *,
        expected_intent_fingerprint: str,
        intent_fingerprint_value: str,
        allowed_programs: frozenset[str] | None = None,
        seen_message_fingerprints: frozenset[str] = frozenset(),
    ) -> SignedTransaction:
        """Sign one assembled V0 transaction, or refuse it with named reasons.

        Three questions are answered before a signature exists, and they are
        deliberately different questions:

        * **Whose transaction is this** — one required signature, fee payer is
          the pinned wallet. That was always here.
        * **What does it invoke** — `tx_inspect` decodes the message and refuses
          any top-level program outside the allowlist, and any program id that
          would have to be resolved from an address lookup table. Compiled route
          instructions are opaque; an unauditable program id is not signed.
        * **Is it the transaction we authorised** — the caller's fingerprint
          must equal one recomputed from the authoritative intent. A caller
          therefore cannot nominate what it is signing.

        Mint and amount semantics remain the job of `order_evidence.verify`
        against the JSON `/order` body, which must run before this boundary;
        those values are genuinely not readable from compiled route bytes.

        Returns the signature alongside the signed bytes. **The signature must
        be persisted before submission**: a lost `/execute` response with no
        stored signature is a transaction that may have landed and can never be
        reconciled, which is the one failure that forces a blind retry.
        """
        verdict = tx_inspect.verify(
            encoded_transaction=encoded_transaction,
            expected_fee_payer=self.public_key,
            allowed_programs=allowed_programs,
            expected_intent_fingerprint=expected_intent_fingerprint,
            intent_fingerprint_value=intent_fingerprint_value,
            seen_message_fingerprints=seen_message_fingerprints,
        )
        if not verdict.approved:
            raise ExecutionTransactionValidationError(",".join(verdict.reason_codes))
        facts = verdict.facts
        assert facts is not None
        try:
            transaction = VersionedTransaction.from_bytes(b64decode(encoded_transaction))
            message = transaction.message
            signature = self._keypair.sign_message(bytes(message))
            signed = VersionedTransaction.populate(message, [signature])
            return SignedTransaction(
                signed_transaction=b64encode(bytes(signed)).decode("ascii"),
                signature=str(signature),
                message_fingerprint=facts.message_fingerprint,
                program_ids=facts.program_ids,
            )
        except Exception as exc:
            raise ExecutionTransactionValidationError("malformed_jupiter_transaction") from exc

    def sign_native_transaction(self, encoded_transaction: str) -> tuple[str, str]:
        """Sign an already-inspected legacy transaction without exposing the key.

        The Phase 2 isolated signer calls this only after its own independent
        native-transfer inspection.  This small primitive repeats the payer
        check here so a future caller cannot accidentally bypass both layers.
        """
        try:
            transaction = Transaction.from_bytes(b64decode(encoded_transaction))
            if str(transaction.message.account_keys[0]) != self.public_key:
                raise ExecutionTransactionValidationError("transaction_taker_mismatch")
            transaction.partial_sign([self._keypair], transaction.message.recent_blockhash)
            signature = str(transaction.signatures[0])
            return b64encode(bytes(transaction)).decode("ascii"), signature
        except ExecutionTransactionValidationError:
            raise
        except Exception as exc:
            raise ExecutionTransactionValidationError("malformed_native_transaction") from exc


class UnavailableExecutionSigner:
    """Explicit fail-closed signer used while execution mode is disabled/dry-run."""

    @property
    def public_key(self) -> str:
        raise ExecutionSignerUnavailableError("execution_wallet_signer_unavailable")

    def sign_message(self, message: bytes) -> bytes:
        del message
        raise ExecutionSignerUnavailableError("execution_wallet_signer_unavailable")
