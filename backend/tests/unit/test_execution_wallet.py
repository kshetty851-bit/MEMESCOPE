"""Security boundaries for the dedicated execution wallet."""

from __future__ import annotations

import json
import stat
from unittest.mock import AsyncMock

import pytest
from solders.keypair import Keypair

from app.core.config import Settings
from app.real_wallet.balance import ExecutionWalletBalanceService
from app.real_wallet.generate_wallet import generate_wallet_file
from app.real_wallet.signer import (
    ExecutionSignerUnavailableError,
    ExecutionWalletPublicKeyMismatchError,
    FileExecutionSigner,
    UnavailableExecutionSigner,
    verify_expected_public_key,
)

pytestmark = pytest.mark.unit


def test_execution_modes_are_explicit_and_disabled_by_default() -> None:
    default = Settings()
    dry_run = Settings(REAL_WALLET_EXECUTION_MODE="dry_run")

    assert default.REAL_WALLET_EXECUTION_MODE == "disabled"
    assert default.REAL_WALLET_EXECUTION_ENABLED is False
    assert default.REAL_WALLET_AUTOTRADE_ENABLED is False
    assert dry_run.REAL_WALLET_EXECUTION_MODE == "dry_run"
    mode_annotation = Settings.model_fields["REAL_WALLET_EXECUTION_MODE"].annotation
    assert set(mode_annotation.__args__) == {"disabled", "dry_run", "armed", "live"}


def test_generator_writes_owner_only_secret_and_returns_public_address(tmp_path) -> None:
    secret_path = tmp_path / "memescope-execution.json"

    public_key = generate_wallet_file(secret_path)

    assert secret_path.exists()
    assert stat.S_IMODE(secret_path.stat().st_mode) == 0o600
    restored = Keypair.from_bytes(bytes(json.loads(secret_path.read_text())))
    assert str(restored.pubkey()) == public_key
    with pytest.raises(FileExistsError):
        generate_wallet_file(secret_path)


def test_file_signer_pins_derived_public_key(tmp_path) -> None:
    keypair = Keypair()
    secret_path = tmp_path / "signer.json"
    secret_path.write_text(json.dumps(list(bytes(keypair))))
    secret_path.chmod(0o600)

    signer = FileExecutionSigner.load(
        secret_file=secret_path, expected_public_key=str(keypair.pubkey())
    )

    assert signer.public_key == str(keypair.pubkey())
    assert signer.sign_message(b"unit-test")


def test_mismatched_or_unavailable_signer_fails_closed(tmp_path) -> None:
    keypair = Keypair()
    secret_path = tmp_path / "signer.json"
    secret_path.write_text(json.dumps(list(bytes(keypair))))
    secret_path.chmod(0o600)

    with pytest.raises(ExecutionWalletPublicKeyMismatchError, match="public_key_mismatch"):
        FileExecutionSigner.load(
            secret_file=secret_path, expected_public_key=str(Keypair().pubkey())
        )
    with pytest.raises(ExecutionSignerUnavailableError):
        UnavailableExecutionSigner().sign_message(b"never-sign")
    with pytest.raises(ExecutionWalletPublicKeyMismatchError):
        verify_expected_public_key(
            expected_public_key="", derived_public_key=str(keypair.pubkey())
        )


async def test_balance_lookup_uses_only_public_address() -> None:
    rpc = AsyncMock()
    rpc.call.return_value = {"context": {"slot": 1}, "value": 123_000_000}

    balance = await ExecutionWalletBalanceService(rpc).get_sol_balance("public-address-only")

    rpc.call.assert_awaited_once_with(
        "getBalance", ["public-address-only", {"commitment": "confirmed"}]
    )
    assert balance.lamports == 123_000_000
    assert balance.sol == pytest.approx(0.123)
