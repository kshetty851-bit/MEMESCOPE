"""The production runner: the one place the real collaborators meet.

Every piece of the real rail was built and correct and nothing composed them, so
an intent created by the driver sat at CREATED for ever. These tests hold the
properties that make the composition safe rather than merely present.

They are structural on purpose. The behavioural path needs a database, a chain,
Jupiter and a signer; what can be pinned cheaply and must never regress is
WHO decides — and the answer is never this module.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from app.real_wallet import executor as ex
from app.real_wallet.live_readiness import ExecutionState, LiveSubmissionGuard

pytestmark = pytest.mark.unit


def _tree() -> ast.Module:
    return ast.parse(Path(ex.__file__).read_text())


def _fn(name: str) -> ast.AsyncFunctionDef:
    return next(n for n in ast.walk(_tree())
                if isinstance(n, ast.AsyncFunctionDef) and n.name == name)


def test_it_never_decides_for_itself_whether_to_submit():
    """The guard and the transport policy are the authorities. This module may
    ask them; it must not contain a branch that submits without them."""
    fn = _fn("_sign_and_submit")
    called = {n.func.attr for n in ast.walk(fn)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
    assert "evaluate" in called          # the guard
    assert "execute_signed_order" in called
    src = ast.unparse(fn)
    # The refusal must be checked, and it must return rather than continue.
    assert "if not guard.allowed" in src
    assert "_block" in src


def test_the_signed_transaction_is_never_persisted_or_logged():
    """Bearer-grade: whoever holds those bytes can broadcast them. They live in
    one local and go straight to the transport."""
    fn = _fn("_sign_and_submit")
    # `ast.unparse` normalises quoting, so count the subscript on the tree.
    reads = [
        n for n in ast.walk(fn)
        if isinstance(n, ast.Subscript)
        and isinstance(n.value, ast.Name) and n.value.id == "signed"
        and isinstance(n.slice, ast.Constant)
        and n.slice.value == "signed_transaction"
    ]
    assert len(reads) == 1, "the bytes must reach exactly one place"
    src = ast.unparse(fn)
    for call in ast.walk(fn):
        if not (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)):
            continue
        if call.func.attr in {"warning", "info", "error", "exception", "transition"}:
            assert "signed_transaction" not in ast.unparse(call), ast.unparse(call)


def test_the_signature_is_stored_before_the_network_call():
    """The difference between a lost /execute response being recoverable and
    being permanently unknown."""
    fn = _fn("_sign_and_submit")
    body = ast.unparse(fn)
    store = body.index("record_signature_before_submission")
    submit = body.index("execute_signed_order")
    assert store < submit


def test_the_stop_control_is_re_read_on_every_step():
    """An operator who presses STOP while an intent is in motion stops that
    intent. Checking it once at the start of a flight would make the control a
    suggestion."""
    fn = _fn("advance")
    src = ast.unparse(fn)
    assert "AutotradeSwitchService" in src
    assert "autotrade_switch_off" in src


def test_an_intent_already_in_flight_is_reconciled_never_abandoned():
    """The chain does not care about our switches. Once submitted, the only
    honest next step is to ask what happened."""
    fn = _fn("advance")
    src = ast.unparse(fn)
    assert "ExecutionState.SUBMITTED" in src
    assert "_reconcile" in src
    # And the kill switch must not be able to route a submitted intent to BLOCKED.
    submitted = src.index("if intent.state == ExecutionState.SUBMITTED")
    reconcile = src.index("_reconcile", submitted)
    block = src.index("kill_switch_active", submitted)
    assert reconcile < block


def test_confirmation_comes_from_the_chain_not_from_the_transport_reply():
    """Jupiter saying 'success' is a reply, not a settlement."""
    submit = ast.unparse(_fn("_sign_and_submit"))
    assert "ExecutionState.CONFIRMED" not in submit
    reconcile = ast.unparse(_fn("_reconcile"))
    assert "inspect" in reconcile and "ExecutionState.CONFIRMED" in reconcile


def test_a_landed_transaction_without_deltas_is_not_a_settled_position():
    """A position recorded from an assumed fill is wrong by an unknown amount."""
    src = ast.unparse(_fn("_reconcile"))
    assert "has_settlement_evidence" in src
    assert "RECONCILIATION_REQUIRED" in src


def test_every_unmeasurable_fact_refuses():
    """`_fresh` is the shape of the whole module: a missing measurement is not a
    pass. A None timestamp must never read as fresh."""
    from datetime import UTC, datetime, timedelta

    now = datetime.now(UTC)
    assert ex.RealWalletExecutor._fresh(None, now, 60) is False
    assert ex.RealWalletExecutor._fresh(now - timedelta(seconds=10), now, 60) is True
    assert ex.RealWalletExecutor._fresh(now - timedelta(seconds=90), now, 60) is False
    # A timestamp from the future is not fresh either — it is a broken clock.
    assert ex.RealWalletExecutor._fresh(now + timedelta(seconds=10), now, 60) is False


def test_a_dead_blockhash_is_refused_rather_than_paid_for():
    """Jupiter's transaction carries a blockhash that dies in about ninety
    seconds. Submitting a stale one buys a fee to be told so."""
    assert ex.MAX_ORDER_AGE_SECONDS <= 90
    src = ast.unparse(_fn("_sign_and_submit"))
    assert "order_expired" in src


def test_the_guard_still_refuses_everything_this_module_can_produce():
    """The end-to-end property, asserted rather than assumed: with every fact
    this executor can measure at its best, the guard must still refuse while the
    release constant stands. If this ever passes, submission became possible
    without a reviewed diff."""
    from app.real_wallet.transport_policy import LIVE_TRANSPORT_RELEASE_APPROVED

    facts = ex.SubmissionFacts(
        signer_ready=True, signer_matches_pinned_key=True,
        safety_passed=True, safety_fresh=True, policy_passed=True,
        valid_intent=True, not_previously_submitted=True,
        order_fresh=True, market_fresh=True, kill_switch_active=False,
        daily_loss_within_limit=True, open_position_within_limit=True,
        trade_size_within_limit=True, mainnet_verified=True,
        transaction_approved=True, not_previously_signed=True,
        canary_limits_satisfied=True,
        transport_release_approved=LIVE_TRANSPORT_RELEASE_APPROVED,
        autotrade_switch_on=True,
    )
    decision = LiveSubmissionGuard().evaluate(facts)
    if not LIVE_TRANSPORT_RELEASE_APPROVED:
        assert not decision.allowed
        assert any("release" in r.lower() or "transport" in r.lower()
                   for r in decision.reasons), decision.reasons


def test_only_states_with_a_handler_advance():
    """A terminal state must not fall through into a handler by accident."""
    fn = _fn("advance")
    src = ast.unparse(fn)
    for state in (ExecutionState.CREATED, ExecutionState.SAFETY_APPROVED,
                  ExecutionState.ORDER_CREATED, ExecutionState.SUBMITTED):
        assert f"ExecutionState.{state.name}" in src
    assert "terminal_state" in src
    for terminal in ("CONFIRMED", "FAILED", "BLOCKED"):
        assert f"ExecutionState.{terminal}: self._" not in src


def test_the_safety_verdict_is_compared_against_what_the_gate_returns():
    """It compared against "ALLOWED"; the gate returns "ALLOW".

    So every intent was blocked, and the recorded reason was the empty string —
    an allowed decision carries no reason codes, so the row read `safety:` and
    named nothing. Fail-closed, and completely broken.

    Asserted against the gate's own literal rather than a copy, so the two
    cannot drift apart again.
    """
    import inspect

    from app.real_wallet_safety import service as safety

    gate_src = inspect.getsource(safety.RealWalletSafetyGate)
    assert '"ALLOW" if not reasons else "REJECT"' in gate_src

    fn = _fn("_run_safety")
    src = ast.unparse(fn)
    assert "'ALLOW'" in src
    assert "'ALLOWED'" not in src


def test_a_block_always_names_something():
    """`safety:` with nothing after it is not a reason. A blocked intent that
    cannot say why is an intent nobody can debug."""
    src = ast.unparse(_fn("_run_safety"))
    assert "or 'unspecified'" in src


def test_an_order_that_fails_its_recheck_blocks_rather_than_escaping():
    """`OrderEvidenceRejectedError` is a different thing from the order being
    unavailable, and it escaped uncaught: the intent stayed at SAFETY_APPROVED
    and was retried every minute against a market that had already refused it.

    Seen for real — Jupiter built a transaction whose slippage was above policy,
    and the exception propagated straight out of the executor.
    """
    fn = _fn("_build_order")
    handlers = [h for n in ast.walk(fn) if isinstance(n, ast.Try) for h in n.handlers]
    caught = {ast.unparse(h.type) for h in handlers if h.type is not None}
    assert "JupiterV2OrderUnavailableError" in caught
    assert "OrderEvidenceRejectedError" in caught
    # Both end in a recorded block, not a re-raise.
    for h in handlers:
        assert "_block" in ast.unparse(h)


def test_the_order_request_states_our_slippage_rather_than_inheriting_jupiters():
    """Jupiter applies its own auto-slippage when none is asked for — measured
    at 500 bps on a token whose real price impact was 0.0059%, against a policy
    of 300.

    Vetoing that afterwards is not the same as governing it: the tolerance baked
    into the SIGNED TRANSACTION was Jupiter's, so an order that slipped 4% would
    have been honoured on chain. The request now carries the policy.
    """
    from app.core.config import settings
    from app.real_wallet import jupiter_v2

    src = Path(jupiter_v2.__file__).read_text()
    assert '"slippageBps"' in src
    assert "REAL_WALLET_EXIT_MAX_SLIPPAGE_BPS" in src

    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.AsyncFunctionDef) and n.name == "order")
    params = next(d for d in ast.walk(fn) if isinstance(d, ast.Dict)
                  and any(isinstance(k, ast.Constant) and k.value == "inputMint"
                          for k in d.keys))
    keys = {k.value for k in params.keys if isinstance(k, ast.Constant)}
    assert "slippageBps" in keys
    # And it is the policy, not a literal that could drift from it.
    assert settings.REAL_WALLET_EXIT_MAX_SLIPPAGE_BPS > 0
