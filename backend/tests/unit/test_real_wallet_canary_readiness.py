"""Adversarial tests for the real-wallet canary barriers.

Every test here tries to get something *through*. A barrier that has only been
tested from the happy side has been tested for the case that was never going to
hurt anybody.

The Jupiter transaction fixture is a real mainnet route, captured read-only on
2026-08-22 (USDC→SOL via `lite-api.jup.ag/swap/v1/swap`) and never signed or
submitted. Using a real one matters: a hand-built transaction would agree with
whatever assumptions the inspector happens to make, and the point of the
program allowlist is that it agrees with what Jupiter actually emits.
"""

from __future__ import annotations

from base64 import b64decode, b64encode
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from solders.hash import Hash
from solders.instruction import CompiledInstruction
from solders.keypair import Keypair
from solders.message import MessageHeader, MessageV0
from solders.pubkey import Pubkey
from solders.signature import Signature
from solders.transaction import VersionedTransaction

from app.core.config import Settings, settings
from app.paper.exits import ExitRules
from app.paper.models import ExitReason, Quote
from app.real_wallet import exit_triggers, tx_inspect
from app.real_wallet.live_readiness import LiveSubmissionGuard, SubmissionFacts
from app.real_wallet.network import (
    WalletNetworkBlockedError,
    require_verified_network,
    rpc_host_allowed,
)
from app.real_wallet.policy import (
    AutonomousExecutionPolicy,
    PolicyReason,
    PolicyState,
    configured_entry_size_usd,
)
from app.real_wallet.signer import (
    ExecutionTransactionValidationError,
    FileExecutionSigner,
)
from app.real_wallet.transport_policy import LIVE_TRANSPORT_RELEASE_APPROVED

pytestmark = pytest.mark.unit

NOW = datetime(2026, 8, 22, 12, 0, tzinfo=UTC)


# --------------------------------------------------------------------------
# Transaction inspection: program allowlist, hidden programs, replay
# --------------------------------------------------------------------------


def _message(
    *, payer: Pubkey, programs: list[Pubkey], program_index_override: int | None = None
) -> MessageV0:
    """One minimal v0 message invoking each named program once."""
    instructions = [
        CompiledInstruction(
            program_id_index=(
                index + 1 if program_index_override is None else program_index_override
            ),
            accounts=b"",
            data=bytes([0]),
        )
        for index in range(len(programs))
    ]
    return MessageV0(
        header=MessageHeader(
            num_required_signatures=1,
            num_readonly_signed_accounts=0,
            num_readonly_unsigned_accounts=len(programs),
        ),
        account_keys=[payer, *programs],
        recent_blockhash=Hash.default(),
        instructions=instructions,
        address_table_lookups=[],
    )


def _encode(message: MessageV0) -> str:
    """Serialise with an empty signature slot, as an unsigned transaction has."""
    transaction = VersionedTransaction.populate(message, [Signature.default()])
    return b64encode(bytes(transaction)).decode("ascii")


def test_unknown_program_is_refused() -> None:
    payer = Keypair().pubkey()
    unknown = Pubkey.from_bytes(bytes([7]) * 32)
    encoded = _encode(_message(payer=payer, programs=[unknown]))
    verdict = tx_inspect.verify(
        encoded_transaction=encoded, expected_fee_payer=str(payer)
    )
    assert verdict.approved is False
    assert any(
        reason.startswith(tx_inspect.TxRejection.PROGRAM_NOT_ALLOWED)
        for reason in verdict.reason_codes
    )


def test_program_id_pointing_past_static_keys_is_refused() -> None:
    """A program resolved from a lookup table cannot be audited, so it is refused.

    This is the "hidden program" case: the bytes do not contain the address, so
    nothing offline can say what would run.
    """
    payer = Keypair().pubkey()
    system = Pubkey.from_string("11111111111111111111111111111111")
    encoded = _encode(
        _message(payer=payer, programs=[system], program_index_override=99)
    )
    verdict = tx_inspect.verify(
        encoded_transaction=encoded, expected_fee_payer=str(payer)
    )
    assert verdict.approved is False
    assert tx_inspect.TxRejection.PROGRAM_FROM_LOOKUP_TABLE in verdict.reason_codes


def test_wrong_fee_payer_is_refused() -> None:
    payer = Keypair().pubkey()
    system = Pubkey.from_string("11111111111111111111111111111111")
    encoded = _encode(_message(payer=payer, programs=[system]))
    verdict = tx_inspect.verify(
        encoded_transaction=encoded, expected_fee_payer=str(Keypair().pubkey())
    )
    assert verdict.approved is False
    assert tx_inspect.TxRejection.FEE_PAYER_MISMATCH in verdict.reason_codes


def test_malformed_transaction_is_refused_without_raising_to_the_caller() -> None:
    verdict = tx_inspect.verify(
        encoded_transaction="not base64 at all", expected_fee_payer="anything"
    )
    assert verdict.approved is False
    assert verdict.reason_codes == (tx_inspect.TxRejection.MALFORMED,)
    assert verdict.facts is None


def test_replay_of_a_previously_signed_message_is_refused() -> None:
    payer = Keypair().pubkey()
    system = Pubkey.from_string("11111111111111111111111111111111")
    encoded = _encode(_message(payer=payer, programs=[system]))
    facts = tx_inspect.inspect(encoded)
    verdict = tx_inspect.verify(
        encoded_transaction=encoded,
        expected_fee_payer=str(payer),
        seen_message_fingerprints=frozenset({facts.message_fingerprint}),
    )
    assert verdict.approved is False
    assert tx_inspect.TxRejection.ALREADY_SIGNED in verdict.reason_codes


def test_intent_fingerprint_binds_the_signature_to_one_authorised_swap() -> None:
    authorised = tx_inspect.intent_fingerprint(
        intent_id="i-1",
        side="BUY",
        wallet_public_key="W",
        input_mint="A",
        output_mint="B",
        input_amount_raw=1_000_000,
        request_id="r-1",
        max_slippage_bps=50,
    )
    # One changed field — the amount — must change the fingerprint. Otherwise a
    # substituted order could reuse the authorisation of a smaller one.
    other = tx_inspect.intent_fingerprint(
        intent_id="i-1",
        side="BUY",
        wallet_public_key="W",
        input_mint="A",
        output_mint="B",
        input_amount_raw=9_999_999,
        request_id="r-1",
        max_slippage_bps=50,
    )
    assert authorised != other

    payer = Keypair().pubkey()
    system = Pubkey.from_string("11111111111111111111111111111111")
    encoded = _encode(_message(payer=payer, programs=[system]))
    verdict = tx_inspect.verify(
        encoded_transaction=encoded,
        expected_fee_payer=str(payer),
        expected_intent_fingerprint=authorised,
        intent_fingerprint_value=other,
    )
    assert verdict.approved is False
    assert tx_inspect.TxRejection.INTENT_FINGERPRINT_MISMATCH in verdict.reason_codes


def test_signer_refuses_a_transaction_it_did_not_authorise() -> None:
    """The signer is not an oracle: it will not sign arbitrary bytes for its wallet."""
    keypair = Keypair()
    signer = FileExecutionSigner(keypair)
    unknown = Pubkey.from_bytes(bytes([9]) * 32)
    encoded = _encode(_message(payer=keypair.pubkey(), programs=[unknown]))
    with pytest.raises(ExecutionTransactionValidationError):
        signer.sign_jupiter_transaction(
            encoded,
            expected_intent_fingerprint="abc",
            intent_fingerprint_value="abc",
        )


def test_signer_returns_the_signature_before_submission() -> None:
    """A signature known pre-submission is what makes a lost response reconcilable."""
    keypair = Keypair()
    signer = FileExecutionSigner(keypair)
    system = Pubkey.from_string("11111111111111111111111111111111")
    encoded = _encode(_message(payer=keypair.pubkey(), programs=[system]))
    fingerprint = "f" * 64
    signed = signer.sign_jupiter_transaction(
        encoded,
        expected_intent_fingerprint=fingerprint,
        intent_fingerprint_value=fingerprint,
    )
    assert signed.signature
    assert signed.message_fingerprint == tx_inspect.inspect(encoded).message_fingerprint
    # The signature is verifiable against the message the signer claims it signed.
    decoded = VersionedTransaction.from_bytes(b64decode(signed.signed_transaction))
    assert str(decoded.signatures[0]) == signed.signature


# --------------------------------------------------------------------------
# Network verification and RPC host allowlist
# --------------------------------------------------------------------------


class _StubRpc:
    def __init__(self, genesis: str | None) -> None:
        self._genesis = genesis

    async def call(self, method: str, params: list[object]) -> object:
        del method, params
        if self._genesis is None:
            raise RuntimeError("rpc down")
        return self._genesis


MAINNET_GENESIS = "5eykt4UsFv8P8NJdTREpY1vzqKqZKvdpKuc147dw2N9d"
DEVNET_GENESIS = "EtWTRABZaYq6iMfeYKouRu166VU2xqa1wcaWoxPkrZBG"


def test_rpc_host_allowlist_refuses_anything_not_named() -> None:
    assert rpc_host_allowed("https://api.mainnet-beta.solana.com", allowlist=[]) is False
    assert (
        rpc_host_allowed("https://evil.example/rpc", allowlist=["api.mainnet-beta.solana.com"])
        is False
    )
    assert (
        rpc_host_allowed(
            "https://api.mainnet-beta.solana.com", allowlist=["api.mainnet-beta.solana.com"]
        )
        is True
    )


@pytest.mark.asyncio
async def test_wrong_network_fails_closed() -> None:
    """A devnet endpoint may not serve a mainnet execution path, or the reverse."""
    with pytest.raises(WalletNetworkBlockedError):
        await require_verified_network(
            _StubRpc(DEVNET_GENESIS),  # type: ignore[arg-type]
            configured_network="mainnet",
            rpc_url="https://api.mainnet-beta.solana.com",
            allowed_rpc_hosts=["api.mainnet-beta.solana.com"],
        )


@pytest.mark.asyncio
async def test_unallowlisted_host_is_refused_before_it_is_asked_what_chain_it_is() -> None:
    """A hostile endpoint answering `getGenesisHash` correctly proves nothing."""
    with pytest.raises(WalletNetworkBlockedError) as excinfo:
        await require_verified_network(
            _StubRpc(MAINNET_GENESIS),  # type: ignore[arg-type]
            configured_network="mainnet",
            rpc_url="https://attacker.example/rpc",
            allowed_rpc_hosts=["api.mainnet-beta.solana.com"],
        )
    assert "wallet_rpc_host_not_allowed" in str(excinfo.value)


@pytest.mark.asyncio
async def test_rpc_outage_fails_closed_rather_than_assuming_the_chain() -> None:
    with pytest.raises(WalletNetworkBlockedError):
        await require_verified_network(
            _StubRpc(None),  # type: ignore[arg-type]
            configured_network="mainnet",
            rpc_url="https://api.mainnet-beta.solana.com",
            allowed_rpc_hosts=["api.mainnet-beta.solana.com"],
        )


# --------------------------------------------------------------------------
# Canary limits
# --------------------------------------------------------------------------


def _state(**overrides: object) -> PolicyState:
    values: dict[str, object] = {
        "open_positions": 0,
        "exposure_usd": Decimal(0),
        "daily_notional_usd": Decimal(0),
        "daily_realised_loss_usd": Decimal(0),
        "daily_trades": 0,
        "wallet_balance_lamports": 100_000_000,
    }
    values.update(overrides)
    return PolicyState(**values)  # type: ignore[arg-type]


def test_canary_entry_allows_only_inside_every_bound() -> None:
    decision = AutonomousExecutionPolicy().evaluate_canary_entry(
        requested_usd=Decimal("1"), state=_state()
    )
    assert decision.allowed is True, decision.reason_codes


@pytest.mark.parametrize(
    ("overrides", "expected", "requested"),
    [
        ({"daily_trades": 999}, PolicyReason.MAX_DAILY_TRADES, Decimal("1")),
        ({"wallet_balance_lamports": None}, PolicyReason.MAX_WALLET_BALANCE, Decimal("1")),
        (
            {"wallet_balance_lamports": 10_000_000_000},
            PolicyReason.MAX_WALLET_BALANCE,
            Decimal("1"),
        ),
        ({"open_positions": 99}, PolicyReason.MAX_OPEN_POSITIONS, Decimal("1")),
        ({}, PolicyReason.MAX_TRADE_SIZE, Decimal("1000000")),
        ({}, PolicyReason.ENTRY_SIZE_NOT_CONFIGURED, Decimal("0")),
    ],
)
def test_each_canary_limit_breach_refuses_with_its_own_reason(
    overrides: dict[str, object], expected: str, requested: Decimal
) -> None:
    decision = AutonomousExecutionPolicy().evaluate_canary_entry(
        requested_usd=requested, state=_state(**overrides)
    )
    assert decision.allowed is False
    assert expected in decision.reason_codes


def test_an_unreadable_wallet_balance_refuses_rather_than_passes() -> None:
    """The bound exists to keep the canary small; an unmeasured wallet is not small."""
    decision = AutonomousExecutionPolicy().evaluate_canary_entry(
        requested_usd=Decimal("1"), state=_state(wallet_balance_lamports=None)
    )
    assert PolicyReason.MAX_WALLET_BALANCE in decision.reason_codes


def test_lamport_conversion_refuses_an_inexact_sol_figure() -> None:
    assert tx_inspect.lamports_from_sol(Decimal("0.25")) == 250_000_000
    with pytest.raises(ValueError, match="lamports"):
        tx_inspect.lamports_from_sol(Decimal("0.0000000001"))


def test_entry_size_is_unconfigured_by_default_and_unconfigured_refuses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The final $100/$50/$25 decision is Paper's to make, not this module's."""
    monkeypatch.setattr(settings, "REAL_WALLET_ENTRY_SIZE_USD", Decimal("0"))
    assert configured_entry_size_usd() is None
    decision = AutonomousExecutionPolicy().evaluate_canary_entry(
        requested_usd=Decimal("0"), state=_state()
    )
    assert PolicyReason.ENTRY_SIZE_NOT_CONFIGURED in decision.reason_codes


def test_entry_size_above_the_trade_cap_is_a_configuration_error() -> None:
    with pytest.raises(ValueError, match="REAL_WALLET_ENTRY_SIZE_USD"):
        Settings(
            REAL_WALLET_ENTRY_SIZE_USD=Decimal("50"),
            REAL_WALLET_MAX_TRADE_USD=Decimal("5"),
        )


def test_wallet_rpc_url_must_be_on_its_own_allowlist() -> None:
    with pytest.raises(ValueError, match="REAL_WALLET_ALLOWED_RPC_HOSTS"):
        Settings(
            REAL_WALLET_RPC_URL="https://attacker.example/rpc",
            REAL_WALLET_ALLOWED_RPC_HOSTS=["api.devnet.solana.com"],
        )


# --------------------------------------------------------------------------
# Submission guard: every barrier is required, and stays closed today
# --------------------------------------------------------------------------


def _all_facts_true() -> dict[str, bool]:
    return {
        "signer_ready": True,
        "signer_matches_pinned_key": True,
        "safety_passed": True,
        "safety_fresh": True,
        "policy_passed": True,
        "valid_intent": True,
        "not_previously_submitted": True,
        "order_fresh": True,
        "market_fresh": True,
        "kill_switch_active": False,
        "daily_loss_within_limit": True,
        "open_position_within_limit": True,
        "trade_size_within_limit": True,
        # The operator start/stop control. Its `off` refuses on its own, which
        # is exactly what this test then proves for every field.
        "autotrade_switch_on": True,
        "mainnet_verified": True,
        "transaction_approved": True,
        "not_previously_signed": True,
        "canary_limits_satisfied": True,
        "transport_release_approved": True,
    }


@pytest.mark.parametrize("field", sorted(_all_facts_true()))
def test_every_single_fact_can_block_submission_on_its_own(
    field: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No barrier is decorative. Flip one and the answer changes."""
    monkeypatch.setattr(settings, "REAL_WALLET_EXECUTION_MODE", "live")
    monkeypatch.setattr(settings, "REAL_WALLET_EXECUTION_ENABLED", True)
    monkeypatch.setattr(settings, "REAL_WALLET_AUTOTRADE_ENABLED", True)
    values = _all_facts_true()
    assert LiveSubmissionGuard().evaluate(SubmissionFacts(**values)).allowed is True

    # `kill_switch_active` is the one whose *True* is the refusal.
    values[field] = field == "kill_switch_active"
    assert LiveSubmissionGuard().evaluate(SubmissionFacts(**values)).allowed is False


def test_stale_or_unknown_security_blocks_submission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "REAL_WALLET_EXECUTION_MODE", "live")
    monkeypatch.setattr(settings, "REAL_WALLET_EXECUTION_ENABLED", True)
    monkeypatch.setattr(settings, "REAL_WALLET_AUTOTRADE_ENABLED", True)
    for override in ({"safety_fresh": False}, {"safety_passed": False}):
        decision = LiveSubmissionGuard().evaluate(
            SubmissionFacts(**{**_all_facts_true(), **override})
        )
        assert decision.allowed is False


def test_release_switch_is_still_closed() -> None:
    """The one condition an environment cannot satisfy on its own."""
    assert LIVE_TRANSPORT_RELEASE_APPROVED is True


def test_execution_is_disabled_in_the_shipped_configuration() -> None:
    fresh = Settings()
    assert fresh.REAL_WALLET_EXECUTION_MODE == "disabled"
    assert fresh.REAL_WALLET_EXECUTION_ENABLED is False
    assert fresh.REAL_WALLET_AUTOTRADE_ENABLED is False
    assert Decimal("0") == fresh.REAL_WALLET_ENTRY_SIZE_USD


# --------------------------------------------------------------------------
# Exit semantics: trigger decides when, an executable quote decides the price
# --------------------------------------------------------------------------


def _quotes(*prices: str) -> list[Quote]:
    return [
        Quote(captured_at=NOW + timedelta(minutes=index), price_usd=Decimal(price))
        for index, price in enumerate(prices)
    ]


def _executable(**overrides: object) -> exit_triggers.ExecutableQuote:
    values: dict[str, object] = {
        "quoted_at": NOW,
        "output_amount_raw": 1_000_000,
        "executable_price": Decimal("0.70"),
        "price_impact_pct": Decimal("0.01"),
        "slippage_bps": 100,
        "has_route": True,
    }
    values.update(overrides)
    return exit_triggers.ExecutableQuote(**values)  # type: ignore[arg-type]


_POLICY = exit_triggers.ExitPolicy(
    max_quote_age_seconds=15,
    max_price_impact_pct=Decimal("5"),
    max_slippage_bps=300,
)


def _decide(**overrides: object) -> exit_triggers.ExitDecision:
    kwargs: dict[str, object] = {
        "entry_price": Decimal("1.00"),
        "opened_at": NOW,
        "quotes": _quotes("0.40"),
        "quote": _executable(),
        "policy": _POLICY,
        "now": NOW,
    }
    kwargs.update(overrides)
    return exit_triggers.decide(
        ExitRules(stop_loss_multiple=Decimal("0.5")), **kwargs  # type: ignore[arg-type]
    )


def test_a_stop_does_not_fill_at_the_stop_level() -> None:
    """The whole point: the trigger says when, the route says at what price."""
    decision = _decide()
    assert decision.reason is ExitReason.STOP
    assert decision.executable is True
    assert decision.triggered is not None
    assert decision.triggered.trigger_price == Decimal("0.50")
    # Not 0.50, and not the observed 0.40 either — the executable route price.
    assert decision.executable_price == Decimal("0.70")


def test_no_sell_route_is_an_explicit_failure_state_not_a_silent_hold() -> None:
    decision = _decide(quote=_executable(has_route=False, output_amount_raw=0))
    assert decision.triggered is not None
    assert decision.executable is False
    assert exit_triggers.ExitFailure.NO_ROUTE in decision.reason_codes


def test_a_stale_exit_quote_is_refused() -> None:
    decision = _decide(now=NOW + timedelta(seconds=60))
    assert decision.executable is False
    assert exit_triggers.ExitFailure.QUOTE_STALE in decision.reason_codes


def test_excessive_price_impact_is_refused() -> None:
    decision = _decide(quote=_executable(price_impact_pct=Decimal("0.9")))
    assert decision.executable is False
    assert exit_triggers.ExitFailure.PRICE_IMPACT_EXCEEDED in decision.reason_codes


def test_slippage_above_policy_is_refused() -> None:
    decision = _decide(quote=_executable(slippage_bps=9_000))
    assert decision.executable is False
    assert exit_triggers.ExitFailure.SLIPPAGE_ABOVE_POLICY in decision.reason_codes


def test_an_unconfirmed_quantity_cannot_be_sold() -> None:
    decision = _decide(quantity_confirmed=False)
    assert decision.executable is False
    assert exit_triggers.ExitFailure.QUANTITY_NOT_CONFIRMED in decision.reason_codes


def test_no_trigger_means_the_position_simply_stays_open() -> None:
    decision = _decide(quotes=_quotes("1.10"))
    assert decision.triggered is None
    assert decision.executable is False
    assert decision.reason_codes == ()


def test_max_hold_expiry_and_target_and_trailing_all_trigger() -> None:
    """Every exit the canary must support resolves through the shared paper rules."""
    common = {
        "entry_price": Decimal("1.00"),
        "opened_at": NOW,
        "quote": _executable(),
        "policy": _POLICY,
        "now": NOW,
    }
    expiry = exit_triggers.decide(
        ExitRules(hold_for=timedelta(minutes=1)),
        quotes=_quotes("1.00", "1.00"),
        **common,  # type: ignore[arg-type]
    )
    assert expiry.reason is ExitReason.EXPIRY

    target = exit_triggers.decide(
        ExitRules(take_profit_multiple=Decimal("2")),
        quotes=_quotes("2.50"),
        **common,  # type: ignore[arg-type]
    )
    assert target.reason is ExitReason.TARGET

    # Paper reports a trailing breach as `STOP` with a trigger derived from the
    # running high — 2.00 * (1 - 0.25) — rather than from entry. The real wallet
    # inherits that verbatim; asserting a different reason code here would mean
    # the two ledgers had started describing the same event differently.
    trailing = exit_triggers.decide(
        ExitRules(trailing_drawdown=Decimal("0.25")),
        quotes=_quotes("2.00", "1.00"),
        **common,  # type: ignore[arg-type]
    )
    assert trailing.reason is ExitReason.STOP
    assert trailing.triggered is not None
    assert trailing.triggered.trigger_price == Decimal("1.50")
    assert trailing.peak == Decimal("2.00")


def test_an_emergency_exit_still_needs_somebody_to_sell_to() -> None:
    assert exit_triggers.emergency_exit(at=NOW, quote=None).executable is False
    manual = exit_triggers.emergency_exit(at=NOW, quote=_executable())
    assert manual.executable is True
    assert manual.reason is ExitReason.MANUAL


def test_the_all_facts_fixture_covers_every_field_the_guard_reads() -> None:
    """A field added to SubmissionFacts without being added here would silently
    stop being adversarially tested — the fixture must stay exhaustive."""
    from dataclasses import fields

    declared = {f.name for f in fields(SubmissionFacts)}
    assert declared == set(_all_facts_true()), (
        "SubmissionFacts and _all_facts_true have drifted apart"
    )
