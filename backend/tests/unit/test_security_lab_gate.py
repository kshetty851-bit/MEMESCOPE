"""The security gate, and the two ways it could quietly stop being a gate.

The lab spends its losses on rugs — five of fifty closed trades, -$76 against
+$113 from everything else — and the platform already had an evaluator that
nothing pointed at those coins. These tests hold the gate to the policy the
evaluator itself states: every check must positively PASS.
"""

from __future__ import annotations

from decimal import Decimal as D

from app.movers import spec


def test_the_pair_differs_by_the_security_condition_alone() -> None:
    gated = {str(c) for c in spec.BY_ID["MOV-03"].entry}
    control = {str(c) for c in spec.BY_ID["MOV-04"].entry}
    assert gated - control == {str(spec._SECURE)}
    assert control - gated == set()


def test_the_control_is_the_pool_alone() -> None:
    """Any extra condition on the control and the pair differs in two ways."""
    assert spec.BY_ID["MOV-04"].entry == spec._POOL


def test_the_gate_demands_a_positive_verdict() -> None:
    """`>= 1` where 1 is VERIFIED alone. If this ever became `>= 0`, or the
    feature started counting UNKNOWN as a pass, the arm would look gated and
    buy everything — the failure that leaves no trace in a result."""
    c = next(c for c in spec.BY_ID["MOV-03"].entry
             if c.feature == "security_verified")
    assert c.op == "gte" and c.value == D("1")


def test_a_fresh_version_starts_a_fresh_tournament() -> None:
    """The previous run halted on `spec_hash_drift` when its registry was
    edited underneath it. A new SPEC_VERSION is how that is resolved honestly:
    the old tournament keeps its record and this one starts clean, rather than
    the stored hash being overwritten to make an edited experiment look
    continuous."""
    assert spec.SPEC_VERSION == "movers-2.0.0"
    assert len(spec.SPEC_VERSION) <= 16


def test_all_three_arms_size_and_exit_identically() -> None:
    assert len({s.size_usd for s in spec.STRATEGIES}) == 1
    assert len({s.max_concurrent for s in spec.STRATEGIES}) == 1
    assert len({s.exits.time_exit_hours for s in spec.STRATEGIES}) == 1
    assert all(s.exits.take_profit is None for s in spec.STRATEGIES)
