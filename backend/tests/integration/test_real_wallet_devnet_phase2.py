"""Durable Phase 2 devnet quote/intent evidence against real Postgres."""

from __future__ import annotations

import base64
import json
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from solders.hash import Hash
from solders.keypair import Keypair
from solders.transaction import Transaction

from app.models.real_wallet_execution import RealWalletDevnetIntent
from app.real_wallet.devnet_intent import DevnetIntentState, DevnetIntentTransitionError
from app.real_wallet.devnet_repository import DevnetIntentRepository
from app.real_wallet.devnet_signer import DevnetSignerError, sign_approved_intent
from app.real_wallet.devnet_transaction import inspect_native_transfer, transaction_fingerprint
from app.real_wallet.devnet_workflow import DevnetManualWorkflow, DevnetManualWorkflowError

pytestmark = pytest.mark.integration


class _DevnetRpc:
    def __init__(self, *, payer: str, destination: str) -> None:
        self.payer = payer
        self.destination = destination
        self.submitted = False
        self.signature = ""
        self.calls: list[str] = []

    async def call(self, method: str, params, *, attempts: int = 3):
        del attempts
        self.calls.append(method)
        if method == "getGenesisHash":
            return "EtWTRABZaYq6iMfeYKouRu166VU2xqa1wcaWoxPkrZBG"
        if method == "getLatestBlockhash":
            return {"context": {"slot": 8}, "value": {"blockhash": str(Hash.new_unique())}}
        if method == "getBalance":
            address = params[0]
            if address == self.payer:
                return {"value": 999_895_000 if self.submitted else 1_000_000_000}
            if address == self.destination:
                return {"value": 100_000 if self.submitted else 0}
        if method == "simulateTransaction":
            return {
                "context": {"slot": 9},
                "value": {"err": None, "logs": ["ok"], "unitsConsumed": 500},
            }
        if method == "sendTransaction":
            self.submitted = True
            return self.signature
        if method == "getSignatureStatuses":
            return {"value": [{"err": None, "confirmationStatus": "confirmed", "slot": 11}]}
        raise AssertionError(method)


class _SignerDevnetRpc:
    """Only the isolated signer owns this independent genesis verification."""

    def __init__(self, *, rpc_url: str) -> None:
        self.rpc_url = rpc_url
        self.calls: list[str] = []

    async def __aenter__(self) -> _SignerDevnetRpc:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    async def call(self, method: str, params: object, *, attempts: int = 3) -> object:
        del params, attempts
        self.calls.append(method)
        if method == "getGenesisHash":
            return "EtWTRABZaYq6iMfeYKouRu166VU2xqa1wcaWoxPkrZBG"
        raise AssertionError(method)


class _ExistingSession:
    """Let the signer reload through its normal context-manager boundary."""

    def __init__(self, session) -> None:
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, *_args: object) -> None:
        return None


def _patch_phase_two_wallet(monkeypatch: pytest.MonkeyPatch, payer: Keypair) -> None:
    monkeypatch.setattr(
        "app.real_wallet.devnet_workflow.settings.REAL_WALLET_NETWORK", "devnet"
    )
    monkeypatch.setattr(
        "app.real_wallet.devnet_workflow.settings.REAL_WALLET_PUBLIC_KEY", str(payer.pubkey())
    )
    monkeypatch.setattr(
        "app.real_wallet.devnet_workflow.settings.PHASE2_DEVNET_MAX_TRANSFER_LAMPORTS",
        1_000_000,
    )


async def _approved_intent(
    db_session, monkeypatch: pytest.MonkeyPatch
) -> tuple[RealWalletDevnetIntent, Keypair, _DevnetRpc]:
    payer = Keypair()
    destination = Keypair()
    _patch_phase_two_wallet(monkeypatch, payer)
    rpc = _DevnetRpc(payer=str(payer.pubkey()), destination=str(destination.pubkey()))
    workflow = DevnetManualWorkflow(db_session, rpc)
    quote = await workflow.quote_native_transfer(
        destination_public_key=str(destination.pubkey()), lamports=100_000
    )
    intent = await workflow.create_intent(
        quote_id=quote.id,
        idempotency_key=f"phase2-approved-{uuid.uuid4()}",
    )
    await workflow.simulate(intent_id=intent.id)
    return (
        await workflow.approve(
            intent_id=intent.id,
            approved_by_user_id=uuid.uuid4(),
            confirmation_phrase="APPROVE_DEVNET_TRANSFER",
        ),
        payer,
        rpc,
    )


async def test_devnet_quote_and_intent_chain_are_durable_and_idempotent(db_session) -> None:
    repository = DevnetIntentRepository(db_session)
    wallet = str(Keypair().pubkey())
    destination = str(Keypair().pubkey())
    now = datetime.now(UTC)
    quote = await repository.create_quote(
        wallet_public_key=wallet,
        input_mint="So11111111111111111111111111111111111111112",
        output_mint="So11111111111111111111111111111111111111112",
        input_amount_raw=Decimal("100000"),
        expected_output_raw=Decimal("100000"),
        minimum_output_raw=Decimal("100000"),
        slippage_bps=0,
        price_impact_pct=Decimal("0"),
        estimated_fee_lamports=5_000,
        provider="solana_system_program_devnet",
        provider_reference="system-transfer:v1",
        route={"kind": "system_transfer", "destination": destination},
        quoted_at=now,
        expires_at=now + timedelta(seconds=60),
        provider_payload={"network": "devnet"},
    )
    created = await repository.create_intent(
        idempotency_key="phase2-durable-intent",
        wallet_public_key=wallet,
        action_type="SOL_TRANSFER",
        input_mint=quote.input_mint,
        output_mint=quote.output_mint,
        input_amount_raw=quote.input_amount_raw,
        destination_public_key=destination,
        at=now,
    )
    assert created is not None
    await repository.transition(
        intent=created,
        next_state=DevnetIntentState.QUOTED,
        at=now,
        event_type="quote_attached",
        detail={"quote_id": str(quote.id)},
        quote_id=quote.id,
        quote_expires_at=quote.expires_at,
    )
    await db_session.flush()

    duplicate = await repository.create_intent(
        idempotency_key="phase2-durable-intent",
        wallet_public_key=wallet,
        action_type="SOL_TRANSFER",
        input_mint=quote.input_mint,
        output_mint=quote.output_mint,
        input_amount_raw=quote.input_amount_raw,
        destination_public_key=destination,
        at=now,
    )
    restored = await repository.intent_by_id(created.id)
    events = await repository.events(created.id)

    assert duplicate is None
    assert restored is not None and restored.quote_id == quote.id
    assert restored.state == DevnetIntentState.QUOTED
    assert [event.event_type for event in events] == ["created", "quote_attached"]


async def test_illegal_transition_is_rejected_without_an_audit_mutation(db_session) -> None:
    repository = DevnetIntentRepository(db_session)
    intent = RealWalletDevnetIntent(
        idempotency_key="phase2-illegal-transition",
        wallet_public_key=str(Keypair().pubkey()),
        network="devnet",
        action_type="SOL_TRANSFER",
        input_mint="So11111111111111111111111111111111111111112",
        output_mint="So11111111111111111111111111111111111111112",
        input_amount_raw=Decimal(1),
        destination_public_key=str(Keypair().pubkey()),
        state=DevnetIntentState.DRAFT,
    )
    db_session.add(intent)
    await db_session.flush()

    with pytest.raises(DevnetIntentTransitionError):
        await repository.transition(
            intent=intent,
            next_state=DevnetIntentState.SIGNED,
            at=datetime.now(UTC),
            detail={},
        )

    assert await repository.events(intent.id) == []


async def test_expired_quote_moves_an_unfinalized_intent_to_expired(db_session) -> None:
    repository = DevnetIntentRepository(db_session)
    now = datetime.now(UTC)
    intent = RealWalletDevnetIntent(
        idempotency_key="phase2-expiry",
        wallet_public_key=str(Keypair().pubkey()),
        network="devnet",
        action_type="SOL_TRANSFER",
        input_mint="So11111111111111111111111111111111111111112",
        output_mint="So11111111111111111111111111111111111111112",
        input_amount_raw=Decimal(1),
        destination_public_key=str(Keypair().pubkey()),
        state=DevnetIntentState.QUOTED,
        quote_expires_at=now - timedelta(seconds=1),
    )
    db_session.add(intent)
    await db_session.flush()

    assert await repository.expire_if_needed(intent=intent, at=now) is True
    assert intent.state == DevnetIntentState.EXPIRED
    assert intent.failure_reason == "intent_expired"


async def test_successful_simulation_submission_confirmation_and_reconciliation(
    db_session, monkeypatch: pytest.MonkeyPatch
) -> None:
    intent, payer, rpc = await _approved_intent(db_session, monkeypatch)
    workflow = DevnetManualWorkflow(db_session, rpc)
    assert intent.state == DevnetIntentState.APPROVED
    assert intent.simulation_status == "SUCCESS"

    # This test supplies an independently signed transaction exactly as the
    # isolated signer would persist; the signer process itself is never called
    # by the API/workflow process.
    unsigned = Transaction.from_bytes(base64.b64decode(intent.transaction_base64))
    unsigned.partial_sign([payer], unsigned.message.recent_blockhash)
    signed = base64.b64encode(bytes(unsigned)).decode("ascii")
    signature = str(unsigned.signatures[0])
    rpc.signature = signature
    inspected = inspect_native_transfer(
        signed,
        expected=DevnetManualWorkflow._spec_from_intent(intent),
    )
    repository = DevnetIntentRepository(db_session)
    await repository.transition(
        intent=intent,
        next_state=DevnetIntentState.SIGNED,
        at=datetime.now(UTC),
        event_type="signed_by_test_isolated_boundary",
        detail={"signature": signature},
        signing_status="SIGNED",
        signed_transaction_base64=signed,
        transaction_signature=signature,
        signer_validation={
            "signed_transaction_fingerprint": transaction_fingerprint(signed),
            "transaction_semantics": inspected.as_metadata(),
        },
    )
    intent = await workflow.submit(intent_id=intent.id)
    assert intent.state == DevnetIntentState.SUBMITTED
    assert (await workflow.submit(intent_id=intent.id)).state == DevnetIntentState.SUBMITTED
    assert rpc.calls.count("sendTransaction") == 1
    intent = await workflow.confirm_and_reconcile(intent_id=intent.id)

    assert intent.state == DevnetIntentState.CONFIRMED
    assert intent.reconciliation is not None
    assert intent.reconciliation["actual_output_lamports"] == 100_000
    assert intent.reconciliation["network_fee_lamports"] == 5_000
    assert "sendTransaction" in rpc.calls


async def test_simulation_failure_is_durable_and_blocks_manual_approval(
    db_session, monkeypatch: pytest.MonkeyPatch
) -> None:
    payer = Keypair()
    destination = Keypair()
    _patch_phase_two_wallet(monkeypatch, payer)

    class _FailedSimulationRpc(_DevnetRpc):
        async def call(self, method: str, params, *, attempts: int = 3):
            if method == "simulateTransaction":
                return {
                    "context": {"slot": 9},
                    "value": {
                        "err": {"InstructionError": [0, "InsufficientFunds"]},
                        "logs": ["insufficient funds"],
                    },
                }
            return await super().call(method, params, attempts=attempts)

    workflow = DevnetManualWorkflow(
        db_session,
        _FailedSimulationRpc(payer=str(payer.pubkey()), destination=str(destination.pubkey())),
    )
    quote = await workflow.quote_native_transfer(
        destination_public_key=str(destination.pubkey()), lamports=100_000
    )
    intent = await workflow.create_intent(
        quote_id=quote.id, idempotency_key="phase2-simulation-fails"
    )

    with pytest.raises(DevnetManualWorkflowError, match="simulation_failed"):
        await workflow.simulate(intent_id=intent.id)

    assert intent.state == DevnetIntentState.FAILED
    assert intent.simulation_status == "FAILED"
    assert intent.failure_reason == "simulation_failed"
    with pytest.raises(DevnetManualWorkflowError):
        await workflow.approve(
            intent_id=intent.id,
            approved_by_user_id=uuid.uuid4(),
            confirmation_phrase="APPROVE_DEVNET_TRANSFER",
        )


async def test_isolated_signer_independently_verifies_and_signs_once(
    db_session, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    intent, payer, _rpc = await _approved_intent(db_session, monkeypatch)
    secret_path = tmp_path / "phase2-devnet-keypair.json"
    secret_path.write_text(json.dumps(list(bytes(payer))), encoding="utf-8")
    secret_path.chmod(0o600)
    monkeypatch.setenv("PHASE2_DEVNET_SIGNER_FILE", str(secret_path))
    monkeypatch.setattr(
        "app.real_wallet.devnet_signer.SessionFactory", lambda: _ExistingSession(db_session)
    )
    monkeypatch.setattr(
        "app.real_wallet.devnet_signer.StandardSolanaRPC", _SignerDevnetRpc
    )

    result = await sign_approved_intent(intent.id)
    assert result == {"intent_id": str(intent.id), "signature": result["signature"]}
    assert result["signature"] == intent.transaction_signature
    assert intent.state == DevnetIntentState.SIGNED
    assert intent.signer_validation is not None
    assert intent.signer_validation["network_verified"] is True
    assert json.dumps(list(bytes(payer))) not in json.dumps(result)

    # A client retry receives the original signature and cannot produce another.
    assert await sign_approved_intent(intent.id) == result
    events = await DevnetIntentRepository(db_session).events(intent.id)
    assert [event.event_type for event in events].count("signed_by_isolated_signer") == 1


async def test_isolated_signer_rejects_unknown_unapproved_expired_and_recovery_states(
    db_session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "app.real_wallet.devnet_signer.SessionFactory", lambda: _ExistingSession(db_session)
    )
    unknown = uuid.uuid4()
    with pytest.raises(DevnetSignerError, match="devnet_intent_not_found"):
        await sign_approved_intent(unknown)

    wallet = str(Keypair().pubkey())
    destination = str(Keypair().pubkey())
    now = datetime.now(UTC)
    unapproved = RealWalletDevnetIntent(
        idempotency_key="phase2-signer-unapproved",
        wallet_public_key=wallet,
        network="devnet",
        action_type="SOL_TRANSFER",
        input_mint="So11111111111111111111111111111111111111112",
        output_mint="So11111111111111111111111111111111111111112",
        input_amount_raw=Decimal(1),
        destination_public_key=destination,
        state=DevnetIntentState.DRAFT,
    )
    expired = RealWalletDevnetIntent(
        idempotency_key="phase2-signer-expired",
        wallet_public_key=wallet,
        network="devnet",
        action_type="SOL_TRANSFER",
        input_mint="So11111111111111111111111111111111111111112",
        output_mint="So11111111111111111111111111111111111111112",
        input_amount_raw=Decimal(1),
        destination_public_key=destination,
        state=DevnetIntentState.APPROVED,
        approval_status="APPROVED",
        approval_expires_at=now - timedelta(seconds=1),
        signing_status="PENDING",
        simulation_status="SUCCESS",
        transaction_base64="not-needed-after-expiry",
    )
    interrupted = RealWalletDevnetIntent(
        idempotency_key="phase2-signer-recovery",
        wallet_public_key=wallet,
        network="devnet",
        action_type="SOL_TRANSFER",
        input_mint="So11111111111111111111111111111111111111112",
        output_mint="So11111111111111111111111111111111111111112",
        input_amount_raw=Decimal(1),
        destination_public_key=destination,
        state=DevnetIntentState.APPROVED,
        approval_status="APPROVED",
        approval_expires_at=now + timedelta(seconds=60),
        signing_status="SIGNING",
        simulation_status="SUCCESS",
        transaction_base64="not-needed-after-recovery",
    )
    db_session.add_all([unapproved, expired, interrupted])
    await db_session.flush()

    with pytest.raises(DevnetSignerError, match="devnet_intent_not_approved"):
        await sign_approved_intent(unapproved.id)
    with pytest.raises(DevnetSignerError, match="devnet_quote_or_approval_expired"):
        await sign_approved_intent(expired.id)
    with pytest.raises(DevnetSignerError, match="devnet_signing_outcome_unknown"):
        await sign_approved_intent(interrupted.id)

    assert expired.state == DevnetIntentState.EXPIRED
    assert interrupted.state == DevnetIntentState.FAILED
    assert interrupted.failure_reason == "signing_outcome_unknown"
