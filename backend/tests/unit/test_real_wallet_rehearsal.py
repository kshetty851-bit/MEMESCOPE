"""The rehearsal must prove the chain without ever being able to use it.

Its whole value is that it can be run on a funded mainnet wallet safely. A
rehearsal that could submit would be a canary, not a rehearsal.
"""

from __future__ import annotations

import ast
from pathlib import Path

from app.real_wallet import rehearsal as rh


def test_it_cannot_submit_sign_or_spend():
    """Structural, not prose: the module must not import a transport, a signer
    factory it could sign with, or anything that builds a transaction."""
    src = Path(rh.__file__).read_text()
    tree = ast.parse(src)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
        elif isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
    assert "app.real_wallet.live_transport" not in imported
    assert "app.real_wallet.devnet_transaction" not in imported
    assert "httpx" not in imported

    called = {
        n.func.attr for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
    }
    for banned in ("execute", "submit", "sign_message", "send_transaction"):
        assert banned not in called, f"rehearsal must never call {banned}()"


def test_unmeasured_facts_default_to_refusing():
    """A fact that could not be established must reach the guard as its
    refusing value, never as a pass."""
    facts = rh.SubmissionFacts()
    assert facts.kill_switch_active is True   # armed is the refusing default
    for name in ("signer_ready", "safety_passed", "mainnet_verified",
                 "transport_release_approved", "canary_limits_satisfied"):
        assert getattr(facts, name) is False


def test_a_clean_rehearsal_still_refuses_submission():
    """Even with everything a rehearsal CAN establish, the guard must refuse:
    the order-level facts belong to an order, and no order exists."""
    from app.real_wallet.live_readiness import LiveSubmissionGuard, SubmissionFacts

    optimistic = SubmissionFacts(
        signer_ready=True, signer_matches_pinned_key=True, policy_passed=True,
        kill_switch_active=False, daily_loss_within_limit=True,
        open_position_within_limit=True, trade_size_within_limit=True,
        mainnet_verified=True, canary_limits_satisfied=True,
    )
    decision = LiveSubmissionGuard().evaluate(optimistic)
    assert decision.allowed is False
    assert "RELEASE_NOT_APPROVED" in decision.reasons
    assert "SAFETY_NOT_APPROVED" in decision.reasons


def test_the_report_exposes_what_it_could_not_measure():
    report = rh.RehearsalReport(
        envelope="armed", network="mainnet", public_key="x", balance_sol=None,
        facts=rh.SubmissionFacts(), guard_allowed=False, guard_reasons=("X",),
        transport_permitted=False, transport_reasons=("Y",),
        observations=(
            rh.Observed("a", True, "src"),
            rh.Observed("b", None, "src"),
        ),
    )
    assert report.unmeasured == ("b",)
    assert report.submission_impossible is True
    assert rh.as_dict(report)["observations"][1]["state"] == "UNAVAILABLE"


def test_submission_impossible_tracks_the_transport_not_the_guard():
    """The guard can be satisfied and submission still impossible — the
    transport is the authority, and the report must not claim otherwise."""
    report = rh.RehearsalReport(
        envelope="armed", network="mainnet", public_key="x", balance_sol=None,
        facts=rh.SubmissionFacts(), guard_allowed=True, guard_reasons=(),
        transport_permitted=False, transport_reasons=("MODE_NOT_LIVE",),
    )
    assert report.submission_impossible is True
