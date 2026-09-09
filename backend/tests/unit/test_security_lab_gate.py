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


def test_the_control_draws_from_the_same_pool_as_the_incumbent() -> None:
    """Otherwise the fresh control differs from MOV-02 in two ways and neither
    comparison means anything."""
    assert spec.BY_ID["MOV-04"].entry == spec.BY_ID["MOV-02"].entry


def test_the_gate_demands_a_positive_verdict() -> None:
    """`>= 1` where 1 is VERIFIED alone. If this ever became `>= 0`, or the
    feature started counting UNKNOWN as a pass, the arm would look gated and
    buy everything — the failure that leaves no trace in a result."""
    c = next(c for c in spec.BY_ID["MOV-03"].entry
             if c.feature == "security_verified")
    assert c.op == "gte" and c.value == D("1")


def test_the_incumbent_is_not_gated() -> None:
    """MOV-02 has been running since 07:54 and must keep running unchanged;
    gating it would silently restart the thing it is a record of."""
    assert not any(c.feature == "security_verified"
                   for c in spec.BY_ID["MOV-02"].entry)


def test_all_three_arms_size_and_exit_identically() -> None:
    assert len({s.size_usd for s in spec.STRATEGIES}) == 1
    assert len({s.max_concurrent for s in spec.STRATEGIES}) == 1
    assert len({s.exits.time_exit_hours for s in spec.STRATEGIES}) == 1
    assert all(s.exits.take_profit is None for s in spec.STRATEGIES)
