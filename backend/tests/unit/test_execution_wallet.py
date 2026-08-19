"""Security boundaries for the dedicated execution wallet."""

from __future__ import annotations

import json
import stat
from unittest.mock import AsyncMock

import pytest
from solders.keypair import Keypair

from app.core.config import Settings
from app.db.base import Base
from app.real_wallet.balance import ExecutionWalletBalanceService
from app.real_wallet.generate_wallet import generate_wallet_file
from app.real_wallet.network import (
    GENESIS_HASHES,
    is_valid_wallet_address,
    verify_wallet_network,
)
from app.real_wallet.signer import (
    ExecutionSignerUnavailableError,
    ExecutionWalletPublicKeyMismatchError,
    FileExecutionSigner,
    UnavailableExecutionSigner,
    verify_expected_public_key,
)
from app.real_wallet.wallet_init import import_wallet_file, write_backup_manifest

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


def test_offline_import_and_backup_manifest_never_repeat_key_material(tmp_path) -> None:
    source_keypair = Keypair()
    source = tmp_path / "source.json"
    source.write_text(json.dumps(list(bytes(source_keypair))))
    target = tmp_path / "imported.json"
    manifest = tmp_path / "backup-proof.json"

    public_key = import_wallet_file(source=source, output=target)
    write_backup_manifest(secret_file=target, output=manifest, public_key=public_key)

    assert public_key == str(source_keypair.pubkey())
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    assert stat.S_IMODE(manifest.stat().st_mode) == 0o600
    assert "recovery_material_included" in manifest.read_text()
    assert str(list(bytes(source_keypair))) not in manifest.read_text()


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


async def test_spl_balance_lookup_reads_both_programs_and_parses_raw_amounts() -> None:
    rpc = AsyncMock()
    rpc.call.side_effect = [
        {
            "value": [
                {
                    "pubkey": "token-account-1",
                    "account": {
                        "data": {
                            "parsed": {
                                "info": {
                                    "mint": "mint-1",
                                    "tokenAmount": {"amount": "1234500", "decimals": 6},
                                }
                            }
                        }
                    },
                }
            ]
        },
        {"value": []},
    ]

    balances = await ExecutionWalletBalanceService(rpc).get_spl_balances("public-address-only")

    assert [(row.mint_address, row.quantity, row.decimals) for row in balances] == [
        ("mint-1", "1.234500", 6)
    ]
    assert rpc.call.await_count == 2


async def test_wallet_network_is_verified_from_genesis_hash() -> None:
    rpc = AsyncMock()
    rpc.call.return_value = GENESIS_HASHES["devnet"]

    status = await verify_wallet_network(rpc, network="devnet")

    assert status.verified is True
    rpc.call.assert_awaited_once_with("getGenesisHash", [])


async def test_wallet_network_mismatch_fails_closed_before_a_balance_read() -> None:
    rpc = AsyncMock()
    rpc.call.return_value = GENESIS_HASHES["mainnet"]

    status = await verify_wallet_network(rpc, network="devnet")

    assert status.verified is False
    assert status.error == "network_mismatch"


def test_wallet_address_validation_accepts_only_public_keys() -> None:
    assert is_valid_wallet_address(str(Keypair().pubkey()))
    assert not is_valid_wallet_address("not-a-solana-public-key")


def test_application_settings_refuse_a_signer_file_path() -> None:
    with pytest.raises(ValueError, match="not permitted in application processes"):
        Settings(REAL_WALLET_EXECUTION_SECRET_FILE="/run/secrets/wallet.json")


def test_real_wallet_database_schema_has_no_key_material_columns() -> None:
    sensitive = {"private_key", "secret", "keypair", "seed", "mnemonic"}
    real_wallet_tables = [
        table
        for name, table in Base.metadata.tables.items()
        if name.startswith("real_wallet_")
    ]

    assert real_wallet_tables
    assert all(not (set(table.columns.keys()) & sensitive) for table in real_wallet_tables)
