"""The frozen V6 registry must match `V6_FINAL_20_STRATEGIES v1.0.0` exactly.

These assertions are transcribed from section 19 of the V6 report, not from the
code they check. If someone edits `spec.py`, this file fails — which is the
point: the specification is immutable once forward scoring starts, and a change
is V6.x or V7 with a record starting at zero.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.lab import spec

D = Decimal


def test_exactly_twenty_strategies_with_unique_ids():
    assert len(spec.STRATEGIES) == 20
    ids = [s.id for s in spec.STRATEGIES]
    assert ids == [f"V6-{i:02d}" for i in range(1, 21)]


def test_every_wallet_starts_at_one_thousand():
    assert spec.STARTING_EQUITY == D("1000.00")
    assert spec.FAILURE_EQUITY_FLOOR == D("800.00")


def test_spec_hash_is_stable():
    """A frozen registry has a frozen hash. Update this ONLY with a version bump."""
    assert spec.SPEC_VERSION == "1.0.0"
    assert spec.SPEC_HASH == (
        "672dffdb91a4c1a295ed2d6f4d95e0fa081bf34dea5b6ef11cbf6071558521e0"
    )


def test_cash_control_never_trades():
    cash = spec.BY_ID["V6-01"]
    assert cash.checkpoint_minutes is None
    assert cash.size_usd == 0
    assert cash.max_concurrent == 0
    assert cash.entry == ()
    assert cash.trades is False


def test_checkpoints_are_the_three_declared_ones():
    assert spec.CHECKPOINTS == [0, 30, 60]


#: (id, checkpoint, size, max_concurrent, max_exposure) straight from section 19.
SIZING = [
    ("V6-02", 30, "10", 8, "80"), ("V6-03", 0, "10", 20, "200"),
    ("V6-04", 30, "10", 10, "100"), ("V6-05", 30, "10", 10, "100"),
    ("V6-06", 30, "10", 8, "80"), ("V6-07", 30, "15", 8, "120"),
    ("V6-08", 30, "10", 10, "100"), ("V6-09", 30, "10", 10, "100"),
    ("V6-10", 30, "10", 10, "100"), ("V6-11", 30, "10", 10, "100"),
    ("V6-12", 30, "10", 10, "100"), ("V6-13", 30, "10", 10, "100"),
    ("V6-14", 30, "10", 10, "100"), ("V6-15", 0, "5", 20, "100"),
    ("V6-16", 60, "10", 10, "100"), ("V6-17", 30, "10", 10, "100"),
    ("V6-18", 60, "5", 4, "20"), ("V6-19", 30, "10", 8, "80"),
    ("V6-20", 30, "10", 10, "100"),
]


@pytest.mark.parametrize("sid,checkpoint,size,conc,expo", SIZING)
def test_frozen_sizing(sid, checkpoint, size, conc, expo):
    s = spec.BY_ID[sid]
    assert s.checkpoint_minutes == checkpoint
    assert s.size_usd == D(size)
    assert s.max_concurrent == conc
    assert s.max_exposure_usd == D(expo)


#: (id, take_profit, time_exit_hours) for the plain take-profit strategies.
TAKE_PROFITS = [
    ("V6-02", "1.25", 6), ("V6-03", "1.25", None), ("V6-04", "1.25", None),
    ("V6-05", "1.25", None), ("V6-06", "1.25", None), ("V6-07", "1.50", None),
    ("V6-08", "1.25", None), ("V6-09", "1.50", None), ("V6-10", "1.25", None),
    ("V6-11", "1.25", None), ("V6-12", "1.25", 6), ("V6-13", "1.50", 6),
    ("V6-15", "1.25", 2), ("V6-16", "1.25", None), ("V6-17", "1.25", None),
    ("V6-18", "1.25", None), ("V6-20", "1.25", None),
]


@pytest.mark.parametrize("sid,tp,time_h", TAKE_PROFITS)
def test_frozen_take_profit_and_time_exit(sid, tp, time_h):
    e = spec.BY_ID[sid].exits
    assert e.take_profit == D(tp)
    assert e.time_exit_hours == time_h


def test_no_strategy_carries_a_conventional_stop_loss():
    """V6 contains none: historically they filled at a median of $0.03."""
    assert all(s.exits.stop_loss is None for s in spec.STRATEGIES)


def test_v6_14_is_the_only_trailing_strategy():
    trailing = [s.id for s in spec.STRATEGIES if s.exits.trailing_drawdown is not None]
    assert trailing == ["V6-14"]
    e = spec.BY_ID["V6-14"].exits
    assert e.trailing_drawdown == D("0.35")
    assert e.trailing_arm_at == D("1.50")
    assert e.take_profit is None
    assert e.time_exit_hours == 6


def test_v6_19_is_the_only_partial_runner_strategy():
    partial = [s.id for s in spec.STRATEGIES if s.exits.partial_at is not None]
    assert partial == ["V6-19"]
    e = spec.BY_ID["V6-19"].exits
    assert e.partial_at == D("1.25")
    assert e.partial_fraction == D("0.50")
    assert e.runner_target == D("2.00")
    assert e.break_even_arm == D("1.25")
    assert e.break_even_exit == D("1.00")
    assert e.take_profit is None


def test_liquidity_exit_strategies():
    assert spec.BY_ID["V6-08"].exits.liquidity_exit_frac_of_entry == D("0.50")
    assert spec.BY_ID["V6-08"].exits.liquidity_exit_absolute_usd == D("1000")
    assert spec.BY_ID["V6-18"].exits.liquidity_exit_frac_of_entry == D("0.50")
    assert spec.BY_ID["V6-20"].exits.liquidity_exit_absolute_usd == D("1000")
    assert spec.BY_ID["V6-20"].exits.liquidity_exit_frac_of_entry is None


def test_liquidity_thresholds_match_the_report():
    def floor(sid):
        return next(c.value for c in spec.BY_ID[sid].entry if c.feature == "liq")

    assert floor("V6-04") == D("100000")
    assert floor("V6-05") == D("300000")
    assert floor("V6-06") == D("400000")
    assert floor("V6-07") == D("500000")
    assert floor("V6-12") == D("50000")
    assert floor("V6-18") == D("300000")
    assert floor("V6-19") == D("400000")


def test_no_strategy_exceeds_four_entry_conditions_except_declared_flow():
    """The V6 complexity limit. V6-12 carries a fifth only because integrity
    (`flow_quality == exact`) is a data-adequacy gate, not a market claim."""
    for s in spec.STRATEGIES:
        limit = 5 if s.id == "V6-12" else 4
        assert len(s.entry) <= limit, f"{s.id} has {len(s.entry)} conditions"


def test_two_forward_only_strategies_are_labelled_as_such():
    assert spec.BY_ID["V6-12"].evidence == "NONE_HISTORICALLY"
    assert spec.BY_ID["V6-20"].evidence == "NONE_HISTORICALLY"
    assert spec.BY_ID["V6-12"].hist_is_proxy is True
    assert spec.BY_ID["V6-20"].hist_is_proxy is True


def test_high_overfit_risk_is_recorded_on_the_two_cash_beaters():
    assert spec.BY_ID["V6-06"].overfit_risk == "HIGH"
    assert spec.BY_ID["V6-07"].overfit_risk == "HIGH"
    assert spec.BY_ID["V6-06"].hist["end_equity"] == 1064.51
    assert spec.BY_ID["V6-07"].hist["end_equity"] == 1117.29


def test_max_exposure_never_exceeds_the_wallet():
    for s in spec.STRATEGIES:
        assert s.max_exposure_usd <= spec.STARTING_EQUITY
        if s.trades:
            assert s.size_usd * s.max_concurrent >= s.max_exposure_usd
