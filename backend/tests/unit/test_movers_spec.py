"""The Movers registry, and the properties that make its result readable.

The spec asserts most of these at import, which is deliberate — a broken pair
should fail to load rather than quietly run a comparison nobody can attribute.
These tests exist so the failure names itself, and so the rules that came from
a measurement cannot drift away from what was measured without a red line.
"""

from __future__ import annotations

from decimal import Decimal as D

from app.movers import spec


def test_the_turnover_arm_is_gone_entirely() -> None:
    """MOV-01 was retired on 2026-09-09 after 3 closed trades. It is removed
    from the registry rather than disabled, so the engine cannot reach a
    strategy id its own spec no longer defines — that mismatch is how one
    lab's tick raises a KeyError on another lab's book."""
    assert "MOV-01" not in spec.BY_ID
    assert "MOV-02" not in spec.BY_ID
    # movers-2.0.0 is a fresh tournament with exactly the pair. The count is
    # asserted so a third arm cannot appear unnoticed: an unpaired arm is the
    # failure mode this file exists to catch.
    assert len(spec.STRATEGIES) == 2


def test_no_turnover_condition_survives_without_a_control() -> None:
    """Reinstating the filter must mean reinstating the control with it.
    A filtered arm with nothing to compare against measures nothing."""
    assert not any(c.feature == "turnover_5m"
                   for st in spec.STRATEGIES for c in st.entry)


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


def test_the_measured_floor_is_kept_on_record() -> None:
    """The constant outlives the arm on purpose. It is the one number this
    lab actually measured — below ~0.02 turnover 10-24% of coins doubled and
    above it 30-47% — and anyone reinstating the filter should start from the
    measurement rather than from a fresh guess."""
    assert spec.TURNOVER_FLOOR >= D("0.5")


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


def test_the_stake_is_a_tenth_of_the_wallet_capped_at_a_hundred() -> None:
    """The rule as given: $10 at $100, $20 at $200, $30 at $300, and no more
    than $100 once the wallet reaches $1,000."""
    from app.sizing import linear_multiplier

    assert spec.SIZING_MODE == "linear"
    cap = D(spec.SIZING_CAP_MULTIPLE)
    for balance, expected in (("100", "10"), ("200", "20"), ("300", "30"),
                              ("1000", "100"), ("5000", "100")):
        m = linear_multiplier(D(balance), base=spec.STARTING_EQUITY,
                              cap_multiple=cap)
        assert spec.SIZE_USD * m == D(expected), balance


def test_sizing_is_declared_on_every_arm() -> None:
    """One arm today, but the moment a second exists the two must size
    identically or the comparison confounds the entry rule with the stake."""
    assert len({s.size_usd for s in spec.STRATEGIES}) == 1
    assert len({s.max_concurrent for s in spec.STRATEGIES}) == 1
