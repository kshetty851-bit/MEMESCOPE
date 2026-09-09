"""The Movers registry, and the properties that make its result readable.

The spec asserts most of these at import, which is deliberate — a broken pair
should fail to load rather than quietly run a comparison nobody can attribute.
These tests exist so the failure names itself, and so the rules that came from
a measurement cannot drift away from what was measured without a red line.
"""

from __future__ import annotations

from decimal import Decimal as D

from app.movers import spec


def test_the_pair_differs_by_exactly_one_condition() -> None:
    """The whole experiment. Two differences and the result is unattributable."""
    signal, control = spec.STRATEGIES
    a = {str(c) for c in signal.entry}
    b = {str(c) for c in control.entry}
    assert a - b == {str(spec._TURNOVER)}
    assert b - a == set()


def test_the_control_is_the_one_without_the_filter() -> None:
    control = spec.BY_ID["MOV-02"]
    assert control.evidence == "CONTROL"
    assert not any(c.feature == "turnover_5m" for c in control.entry)
    assert any(c.feature == "turnover_5m" for c in spec.BY_ID["MOV-01"].entry)


def test_neither_arm_takes_profit() -> None:
    """A +10% cap destroyed 93% of gross return in the 15-minute study. A
    take-profit here would measure the exit rather than the entry, which is
    the only thing this lab is asking about."""
    for s in spec.STRATEGIES:
        assert s.exits.take_profit is None


def test_the_checkpoint_matches_where_the_signal_was_measured() -> None:
    """Turnover was measured at each token's tenth print, and the median token
    reaches that 9.8 minutes after first sight. A checkpoint elsewhere reads a
    different quantity and calls it the same rule."""
    for s in spec.STRATEGIES:
        assert s.checkpoint_minutes == 10


def test_both_arms_hold_for_the_same_thirty_minutes() -> None:
    """Median time from a fillable entry to a 2x was 19.7 minutes. If the arms
    ever held for different periods the comparison would be about the clock."""
    assert spec.TIME_EXIT_HOURS == 0.5
    for s in spec.STRATEGIES:
        assert s.exits.time_exit_hours == spec.TIME_EXIT_HOURS


def test_the_turnover_floor_sits_well_above_the_measured_cliff() -> None:
    """Below ~0.02 turnover, 10-24% of tokens doubled; above it, 30-47%. The
    floor must clear that cliff by a wide margin, because the cliff is where
    the dead coins stop rather than where the movers start."""
    assert spec.TURNOVER_FLOOR >= D("0.5")
    condition = next(c for c in spec.BY_ID["MOV-01"].entry
                     if c.feature == "turnover_5m")
    assert condition.op == "gte"
    assert condition.value == spec.TURNOVER_FLOOR


def test_the_book_cannot_be_overcommitted() -> None:
    for s in spec.STRATEGIES:
        assert s.size_usd * s.max_concurrent <= spec.STARTING_EQUITY


def test_size_is_flat_and_identical_across_arms() -> None:
    """Size following equity would confound the entry rule with the sizing
    rule, which is what left V6 unable to separate them afterwards."""
    assert len({s.size_usd for s in spec.STRATEGIES}) == 1
    assert spec.SIZE_USD == D("10")


def test_the_liquidity_floor_is_where_fills_were_measured() -> None:
    """~0.78% round trip at $100k, from 142,479 Jupiter quotes. Both arms carry
    it, so the control is not quietly buying cheaper depth."""
    for s in spec.STRATEGIES:
        liq = next(c for c in s.entry if c.feature == "liq")
        assert liq.value == spec.MIN_LIQUIDITY_USD == D("100000")


def test_neither_arm_requires_a_route_quote() -> None:
    """Deliberate, and measured: only 3.6% of tokens ever get a Jupiter quote
    and the median one arrives 24.2 minutes in, so a route condition would
    have cut the lab to a thirtieth of its pool and only after the median
    mover had already run. Depth carries the execution guarantee instead."""
    for s in spec.STRATEGIES:
        features = {c.feature for c in s.entry}
        assert "buy_route_ok" not in features
        assert "sell_route_ok" not in features


def test_the_hash_covers_the_rules_and_not_the_prose() -> None:
    """Editing a hypothesis must not restart a running tournament; editing a
    threshold must."""
    before = spec.SPEC_HASH
    original = spec.STRATEGIES[0].hypothesis
    object.__setattr__(spec.STRATEGIES[0], "hypothesis", "reworded entirely")
    try:
        assert spec._canonical() and spec.SPEC_HASH == before
    finally:
        object.__setattr__(spec.STRATEGIES[0], "hypothesis", original)


def test_the_version_is_short_enough_for_the_column() -> None:
    """`lab_tournaments.spec_version` is String(16). A longer name is rejected
    at activation, which is a runtime failure for a naming decision."""
    assert len(spec.SPEC_VERSION) <= 16
