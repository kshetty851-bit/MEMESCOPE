"""Backend-only keypair handling for the dedicated execution wallet.

No caller should receive raw key bytes.  The future execution engine will pass
an intent id to this boundary; it must never pass signer material through a
task, API schema, database row, log, or browser response.
"""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import Protocol

from solders.keypair import Keypair


class ExecutionSignerUnavailableError(RuntimeError):
    """A signer is unavailable: execution must fail closed."""


class ExecutionWalletPublicKeyMismatchError(RuntimeError):
    """The mounted secret does not belong to the configured public address."""


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


class UnavailableExecutionSigner:
    """Explicit fail-closed signer used while execution mode is disabled/dry-run."""

    @property
    def public_key(self) -> str:
        raise ExecutionSignerUnavailableError("execution_wallet_signer_unavailable")

    def sign_message(self, message: bytes) -> bytes:
        del message
        raise ExecutionSignerUnavailableError("execution_wallet_signer_unavailable")
