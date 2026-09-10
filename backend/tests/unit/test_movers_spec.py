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
    # THREE arms now, and every one of them is inside a pair: MOV-03/MOV-04
    # differ in the security gate alone, MOV-05/MOV-03 in the clock alone. The
    # count is still asserted for the original reason — an UNPAIRED arm invites
    # reading the best line as a result — so a fourth arm must arrive with its
    # own control and update this deliberately.
    assert len(spec.STRATEGIES) == 3
    assert set(spec.BY_ID) == {"MOV-03", "MOV-04", "MOV-05"}


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


def test_the_security_pair_holds_for_the_same_thirty_minutes() -> None:
    """Median time from a fillable entry to a 2x was 19.7 minutes. If the
    SECURITY pair ever held for different periods its comparison would be about
    the clock rather than the gate.

    MOV-05 is excluded deliberately: it exists to have no clock, and it is
    paired against MOV-03 rather than against MOV-04 (see the test below)."""
    assert spec.TIME_EXIT_HOURS == 0.5
    for sid in ("MOV-03", "MOV-04"):
        assert spec.BY_ID[sid].exits.time_exit_hours == spec.TIME_EXIT_HOURS


def test_the_no_clock_arm_is_paired_and_differs_only_in_the_clock() -> None:
    """MOV-05 runs the wallet ratchet with NO holding period, on instruction.

    An unpaired arm invites reading the best line as a result, so it is pinned
    to a control: MOV-04 carries identical entry conditions and keeps its
    thirty-minute exit, which makes the pair ask exactly one question — does
    holding until the PORTFOLIO is up beat holding each position for half an
    hour?

    Paired with MOV-04 rather than MOV-03 on correction: MOV-05 carries no
    security gate, and MOV-04 is also the arm that actually trades — MOV-03
    took none of the two candidates movers-4.0.0 judged while MOV-04 took
    both."""
    assert spec.BY_ID["MOV-05"].exits.time_exit_hours is None
    assert spec.BY_ID["MOV-04"].exits.time_exit_hours is not None
    assert spec.BY_ID["MOV-05"].entry == spec.BY_ID["MOV-04"].entry
    assert spec.BY_ID["MOV-05"].size_usd == spec.BY_ID["MOV-04"].size_usd
    assert (spec.BY_ID["MOV-05"].max_concurrent
            == spec.BY_ID["MOV-04"].max_concurrent)

def test_the_no_clock_arm_carries_no_security_gate() -> None:
    """It is the CONTROL's rules with the clock removed, so it must not quietly
    acquire the gate — that would make it differ from MOV-04 in two ways."""
    from app.movers.spec import _SECURE
    assert _SECURE not in spec.BY_ID["MOV-05"].entry
    assert _SECURE in spec.BY_ID["MOV-03"].entry


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
    # $1 x 100 since movers-8.0.0: one percent of the wallet a position, a
    # hundred at a time, and the book still exactly the starting equity.
    assert spec.SIZE_USD == D("1")
    assert spec.MAX_CONCURRENT == 100
    assert spec.SIZE_USD * spec.MAX_CONCURRENT == spec.STARTING_EQUITY


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


def test_the_stake_is_one_percent_of_the_wallet_capped_at_ten_times() -> None:
    """The rule as given, in multiples of the base stake so it survives a
    change of shape: 1x at $100, 2x at $200, 3x at $300, and no more than the
    cap once the wallet reaches ten times its start. At $1 x 100 that is $1,
    $2, $3 and a $10 ceiling."""
    from app.sizing import linear_multiplier

    assert spec.SIZING_MODE == "linear"
    cap = D(spec.SIZING_CAP_MULTIPLE)
    for balance, expected in (("100", "1"), ("200", "2"), ("300", "3"),
                              ("1000", str(cap)), ("5000", str(cap))):
        m = linear_multiplier(D(balance), base=spec.STARTING_EQUITY,
                              cap_multiple=cap)
        assert m == D(expected), balance
        assert spec.SIZE_USD * m == spec.SIZE_USD * D(expected), balance


def test_sizing_is_declared_on_every_arm() -> None:
    """One arm today, but the moment a second exists the two must size
    identically or the comparison confounds the entry rule with the stake."""
    assert len({s.size_usd for s in spec.STRATEGIES}) == 1
    assert len({s.max_concurrent for s in spec.STRATEGIES}) == 1
