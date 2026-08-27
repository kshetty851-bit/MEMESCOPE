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


def test_spec_hash_is_stable():
    """A frozen registry has a frozen hash. Update this ONLY with a version bump.

    1.0.0 was 672dffdb91a4c1a295ed2d6f4d95e0fa081bf34dea5b6ef11cbf6071558521e0.
    It ran for nineteen hours on a $1,000 book and its record is kept; 1.1.0 is a
    new record at $100 rather than an edit of that one, which is exactly what the
    version bump is for.
    """
    assert spec.SPEC_VERSION == "1.1.0"
    assert spec.SPEC_HASH == (
        "a5f0c2ed0fd29a1ce9ac6bc98efdafd96dea974a5db6c523f98e23bdcc447a41"
    )


def test_the_book_is_what_the_operator_will_actually_fund():
    """$1,000 was not a neutral choice — it made a $50 loss read as -5%.

    Replayed against the real price record, the same trades on a $100 book at the
    old $10 positions came to a mean of -33.6%, random control -98%. The sizes are
    now chosen for the book instead of inherited from one ten times larger.
    """
    assert spec.STARTING_EQUITY == D("100.00")
    assert spec.FAILURE_EQUITY_FLOOR == spec.STARTING_EQUITY * D("0.8")
    for s in spec.STRATEGIES:
        assert s.max_exposure_usd <= spec.STARTING_EQUITY * spec.MAX_DEPLOYED_FRACTION, s.id
        assert s.size_usd * s.max_concurrent == s.max_exposure_usd, s.id


def test_every_trading_strategy_can_time_out():
    """A position that neither reaches its target nor dies never returns its
    capital. On a $1,000 book that was a rounding error; on $100 it is the
    experiment stopping. V6-04's first 1.0.0 entry was still open nineteen hours
    later marked at $0.0003, and under a one-position cap that is a wallet that
    never trades again.
    """
    missing = [s.id for s in spec.STRATEGIES
               if s.trades and s.exits.time_exit_hours is None]
    assert missing == []
    # The control must not time out into a different strategy than it is.
    assert spec.BY_ID["V6-01"].exits.time_exit_hours is None


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
    ("V6-02", 30, "5", 8, "40"), ("V6-03", 0, "3", 20, "60"),
    ("V6-04", 30, "5", 10, "50"), ("V6-05", 30, "5", 10, "50"),
    ("V6-06", 30, "5", 8, "40"), ("V6-07", 30, "7.5", 8, "60"),
    ("V6-08", 30, "5", 10, "50"), ("V6-09", 30, "5", 10, "50"),
    ("V6-10", 30, "5", 10, "50"), ("V6-11", 30, "5", 10, "50"),
    ("V6-12", 30, "5", 10, "50"), ("V6-13", 30, "5", 10, "50"),
    ("V6-14", 30, "5", 10, "50"), ("V6-15", 0, "2.5", 20, "50"),
    ("V6-16", 60, "5", 10, "50"), ("V6-17", 30, "5", 10, "50"),
    ("V6-18", 60, "2.5", 4, "10"), ("V6-19", 30, "5", 8, "40"),
    ("V6-20", 30, "5", 10, "50"),
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
    ("V6-02", "1.25", 6), ("V6-03", "1.25", 6), ("V6-04", "1.25", 6),
    ("V6-05", "1.25", 6), ("V6-06", "1.25", 6), ("V6-07", "1.50", 6),
    ("V6-08", "1.25", 6), ("V6-09", "1.50", 6), ("V6-10", "1.25", 6),
    ("V6-11", "1.25", 6), ("V6-12", "1.25", 6), ("V6-13", "1.50", 6),
    ("V6-15", "1.25", 2), ("V6-16", "1.25", 6), ("V6-17", "1.25", 6),
    ("V6-18", "1.25", 6), ("V6-20", "1.25", 6),
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


# --- the public rulebook -----------------------------------------------------
# The page renders these strings verbatim. They are served rather than
# transcribed into TypeScript, so this is the only place they can drift.

def test_rulebook_covers_every_strategy():
    book = [spec.rules_json(s) for s in spec.STRATEGIES]
    assert len(book) == 20
    assert [r["id"] for r in book] == [s.id for s in spec.STRATEGIES]
    for r in book:
        assert r["entry_text"], f"{r['id']} must describe its entry"
        assert r["exit_text"], f"{r['id']} must describe its exits"


def test_rulebook_prose_never_changes_the_hash():
    """Descriptions are for readers. Editing one must not invalidate a live
    record, so the hash must not cover them."""
    assert spec.SPEC_HASH == (
        "a5f0c2ed0fd29a1ce9ac6bc98efdafd96dea974a5db6c523f98e23bdcc447a41"
    )


def test_rulebook_states_the_real_thresholds():
    v606 = spec.rules_json(spec.BY_ID["V6-06"])
    assert v606["entry_text"] == ["liquidity ≥ $400,000"]
    assert "take profit at 1.25x" in v606["exit_text"]
    assert v606["checkpoint_label"] == "+30 min"

    v619 = spec.rules_json(spec.BY_ID["V6-19"])
    assert "sell 50% at 1.25x" in v619["exit_text"]
    assert "runner exits at 2.00x" in v619["exit_text"]

    v618 = spec.rules_json(spec.BY_ID["V6-18"])
    assert v618["size_usd"] == "2.5"
    assert v618["max_exposure_usd"] == "10"


def test_every_strategy_declares_no_stop_loss_in_words():
    for s in spec.STRATEGIES:
        if not s.trades:
            continue
        assert any("no stop loss" in line for line in s.exits.describe())


def test_controls_say_what_they_do():
    assert spec.rules_json(spec.BY_ID["V6-01"])["entry_text"] == ["never enters"]
    assert spec.rules_json(spec.BY_ID["V6-02"])["entry_text"] == [
        "every eligible token (control)"
    ]
