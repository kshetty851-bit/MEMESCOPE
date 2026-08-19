"""Phase 2's network and manual-lifecycle hard stops."""

from __future__ import annotations

import base64
from pathlib import Path
from types import SimpleNamespace

import pytest
from solders.hash import Hash
from solders.instruction import AccountMeta, Instruction
from solders.keypair import Keypair
from solders.message import Message
from solders.pubkey import Pubkey
from solders.transaction import Transaction

from app.real_wallet.devnet_intent import (
    DevnetIntentState,
    DevnetIntentTransitionError,
    require_transition,
)
from app.real_wallet.devnet_signer import DevnetSignerError, _spec_from_intent
from app.real_wallet.devnet_transaction import (
    NATIVE_SOL_MINT,
    DevnetTransactionValidationError,
    NativeTransferSpec,
    build_unsigned_native_transfer,
    inspect_native_transfer,
)
from app.real_wallet.devnet_workflow import _simulation_outcome
from app.real_wallet.network import DevnetExecutionBlockedError, require_verified_devnet


class _Rpc:
    def __init__(self, genesis: str) -> None:
        self.genesis = genesis

    async def call(self, method: str, params: object) -> object:
        assert method == "getGenesisHash"
        assert params == []
        return self.genesis


@pytest.mark.unit
async def test_phase_two_rejects_mainnet_before_any_rpc_call() -> None:
    with pytest.raises(DevnetExecutionBlockedError, match="phase2_devnet_only"):
        await require_verified_devnet(_Rpc("ignored"), configured_network="mainnet")


@pytest.mark.unit
async def test_phase_two_rejects_a_non_devnet_genesis_hash() -> None:
    with pytest.raises(DevnetExecutionBlockedError, match="network_mismatch"):
        await require_verified_devnet(_Rpc("not-devnet"), configured_network="devnet")


@pytest.mark.unit
async def test_phase_two_accepts_only_verified_devnet() -> None:
    status = await require_verified_devnet(
        _Rpc("EtWTRABZaYq6iMfeYKouRu166VU2xqa1wcaWoxPkrZBG"), configured_network="devnet"
    )
    assert status.verified


@pytest.mark.unit
def test_manual_approval_is_required_before_signing() -> None:
    with pytest.raises(DevnetIntentTransitionError):
        require_transition(
            current=DevnetIntentState.SIMULATED, next_state=DevnetIntentState.SIGNED
        )
    require_transition(
        current=DevnetIntentState.SIMULATED, next_state=DevnetIntentState.AWAITING_APPROVAL
    )
    require_transition(
        current=DevnetIntentState.AWAITING_APPROVAL, next_state=DevnetIntentState.APPROVED
    )
    require_transition(current=DevnetIntentState.APPROVED, next_state=DevnetIntentState.SIGNED)


def test_phase_two_uses_one_exact_native_transfer_shape() -> None:
    payer = Keypair()
    recipient = Keypair()
    spec = NativeTransferSpec(
        fee_payer=str(payer.pubkey()),
        destination=str(recipient.pubkey()),
        lamports=100_000,
    )

    encoded = build_unsigned_native_transfer(spec=spec, blockhash=str(Hash.new_unique()))
    inspected = inspect_native_transfer(encoded, expected=spec)

    assert inspected.fee_payer == str(payer.pubkey())
    assert inspected.destination == str(recipient.pubkey())
    assert inspected.lamports == 100_000
    assert len(inspected.fingerprint) == 64


def test_allowlist_rejects_unexpected_fee_payer_destination_and_amount() -> None:
    payer = Keypair()
    recipient = Keypair()
    encoded = build_unsigned_native_transfer(
        spec=NativeTransferSpec(
            fee_payer=str(payer.pubkey()),
            destination=str(recipient.pubkey()),
            lamports=100_000,
        ),
        blockhash=str(Hash.new_unique()),
    )

    with pytest.raises(DevnetTransactionValidationError, match="unexpected_fee_payer"):
        inspect_native_transfer(
            encoded,
            expected=NativeTransferSpec(
                fee_payer=str(Keypair().pubkey()),
                destination=str(recipient.pubkey()),
                lamports=100_000,
            ),
        )
    with pytest.raises(DevnetTransactionValidationError, match="unexpected_destination"):
        inspect_native_transfer(
            encoded,
            expected=NativeTransferSpec(
                fee_payer=str(payer.pubkey()),
                destination=str(Keypair().pubkey()),
                lamports=100_000,
            ),
        )
    with pytest.raises(DevnetTransactionValidationError, match="unexpected_amount"):
        inspect_native_transfer(
            encoded,
            expected=NativeTransferSpec(
                fee_payer=str(payer.pubkey()),
                destination=str(recipient.pubkey()),
                lamports=99_999,
            ),
        )


def test_allowlist_rejects_an_unexpected_program() -> None:
    payer = Keypair()
    recipient = Keypair()
    malicious_program = Pubkey.new_unique()
    instruction = Instruction(
        malicious_program,
        b"",
        [
            AccountMeta(payer.pubkey(), is_signer=True, is_writable=True),
            AccountMeta(recipient.pubkey(), is_signer=False, is_writable=True),
        ],
    )
    message = Message.new_with_blockhash([instruction], payer.pubkey(), Hash.new_unique())
    encoded = base64.b64encode(bytes(Transaction.new_unsigned(message))).decode("ascii")

    with pytest.raises(DevnetTransactionValidationError, match="unexpected_account"):
        inspect_native_transfer(
            encoded,
            expected=NativeTransferSpec(
                fee_payer=str(payer.pubkey()),
                destination=str(recipient.pubkey()),
                lamports=1,
            ),
        )


def test_allowlist_rejects_unexpected_signer_writable_and_instruction_type() -> None:
    payer = Keypair()
    recipient = Keypair()
    expected = NativeTransferSpec(
        fee_payer=str(payer.pubkey()), destination=str(recipient.pubkey()), lamports=1
    )
    bad_messages = [
        Message.new_with_blockhash(
            [
                Instruction(
                    Pubkey.from_string("11111111111111111111111111111111"),
                    (2).to_bytes(4, "little") + (1).to_bytes(8, "little"),
                    [
                        AccountMeta(payer.pubkey(), is_signer=True, is_writable=True),
                        AccountMeta(recipient.pubkey(), is_signer=True, is_writable=True),
                    ],
                )
            ],
            payer.pubkey(),
            Hash.new_unique(),
        ),
        Message.new_with_blockhash(
            [
                Instruction(
                    Pubkey.from_string("11111111111111111111111111111111"),
                    (3).to_bytes(4, "little") + (1).to_bytes(8, "little"),
                    [
                        AccountMeta(payer.pubkey(), is_signer=True, is_writable=True),
                        AccountMeta(recipient.pubkey(), is_signer=False, is_writable=True),
                    ],
                )
            ],
            payer.pubkey(),
            Hash.new_unique(),
        ),
    ]

    for message in bad_messages:
        encoded = base64.b64encode(bytes(Transaction.new_unsigned(message))).decode("ascii")
        with pytest.raises(DevnetTransactionValidationError):
            inspect_native_transfer(encoded, expected=expected)


def test_isolated_signer_revalidates_intent_mints_without_trusting_the_api() -> None:
    intent = SimpleNamespace(
        network="devnet",
        action_type="SOL_TRANSFER",
        input_mint="unexpected-mint",
        output_mint=NATIVE_SOL_MINT,
        wallet_public_key=str(Keypair().pubkey()),
        destination_public_key=str(Keypair().pubkey()),
        input_amount_raw=1,
    )

    with pytest.raises(DevnetSignerError, match="unexpected_intent_mint"):
        _spec_from_intent(intent)


def test_simulation_payload_distinguishes_success_from_failure() -> None:
    success = _simulation_outcome(
        {"context": {"slot": 8}, "value": {"err": None, "logs": ["ok"], "unitsConsumed": 42}}
    )
    failed = _simulation_outcome(
        {"context": {"slot": 9}, "value": {"err": {"InstructionError": [0, "Custom"]}}}
    )

    assert success["success"] is True
    assert success["units_consumed"] == 42
    assert failed["success"] is False
    assert failed["logs"] == []


def test_phase_two_api_has_no_signer_file_reference() -> None:
    root = Path(__file__).resolve().parents[2]
    api_source = (root / "app" / "real_wallet" / "api.py").read_text()
    workflow_source = (root / "app" / "real_wallet" / "devnet_workflow.py").read_text()
    signer_source = (root / "app" / "real_wallet" / "devnet_signer.py").read_text()

    assert "PHASE2_DEVNET_SIGNER_FILE" not in api_source
    assert "PHASE2_DEVNET_SIGNER_FILE" not in workflow_source
    assert "PHASE2_DEVNET_SIGNER_FILE" in signer_source
    config_source = (root / "app" / "core" / "config.py").read_text()
    assert "PHASE2_DEVNET_SIGNER_FILE:" not in config_source


def test_paper_wallet_and_generation_two_cannot_import_phase_two_execution() -> None:
    root = Path(__file__).resolve().parents[2]
    prohibited = ("devnet_workflow", "devnet_signer", "devnet_transaction")
    paths = [
        *(root / "app" / "paper").rglob("*.py"),
        *(root / "app" / "radar").rglob("*.py"),
    ]
    for path in paths:
        source = path.read_text()
        assert not any(name in source for name in prohibited), path
