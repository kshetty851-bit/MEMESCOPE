"""Every arm must be executable with a real wallet, not just scorable.

A backtest can price things a wallet cannot buy. These are the four ways this
tournament could drift into measuring something unbuyable, each one pinned so
the drift fails here rather than at the point of funding an account.

The measurements behind the numbers, taken on prod 2026-09-13 over 3 days:

  - migration -> first observable price: 10% by 13s, median 42s, 90% by 73s.
    The lab enters at that FIRST OBSERVED sample, so a wallet reading the same
    feed sees the same price. Entry is reproducible.
  - gap between price samples in the first five minutes: median 61s, 90th
    percentile 70s. An exit shorter than that is marked by a sample that has
    not arrived, so a one-minute hold cannot be verified by either the lab or
    the wallet.
"""

from __future__ import annotations

import inspect
from decimal import Decimal

import pytest

from app.labs.graduation import config
from app.labs.graduation.tournament import ARMS, accepts

pytestmark = pytest.mark.unit

#: Median gap between observable prices, in seconds. An arm holding for less
#: than this is priced by a sample that does not exist yet.
OBSERVED_SAMPLE_GAP_S = 61


def test_no_arm_holds_for_less_than_the_data_can_see():
    for arm in ARMS:
        assert arm.hold * 60 >= OBSERVED_SAMPLE_GAP_S, (
            f"{arm.name} holds {arm.hold}m, under the {OBSERVED_SAMPLE_GAP_S}s "
            "median gap between price samples — its exit price would come from "
            "a mark that arrives late, and a real wallet could not verify it")


def test_every_entry_decision_uses_only_what_a_wallet_can_see_first():
    """`accepts` takes the token's mint, its open time, and three figures the
    price feed carries. It must not reach for anything else — an entry rule
    that depended on the outcome, or on a later sample, would be unbuyable."""
    params = set(inspect.signature(accepts).parameters) - {"arm"}
    assert params == {"mint", "open_at", "liquidity", "fdv", "sells", "reuse"}, (
        "the entry decision gained an input; check it is observable BEFORE the "
        f"buy, not after: {params}")


def test_a_missing_reading_refuses_the_trade():
    """The feed can answer without liquidity. Treating that as 'in band' would
    buy tokens the rule never claimed — and a wallet would do the same."""
    blank = {"mint": "M" * 44, "liquidity": None, "fdv": None,
             "sells": None, "reuse": None}
    from datetime import UTC, datetime
    now = datetime.now(UTC)
    for arm in ARMS:
        if arm.entry.startswith("liq_"):
            assert not accepts(arm, open_at=now, **blank), arm.name


def test_the_position_stays_above_the_size_that_can_be_paid_for():
    """Below $25 a round trip costs more than it can make: the priority fee is
    flat in SOL, so it is 0.25% of a $250 order and 2.32% of a $10 one against
    a break-even near 1% a side."""
    assert config.PAPER_NOTIONAL_USD >= config.WALLET_MIN_USD
    assert config.WALLET_DEMO_USD / config.WALLET_DEMO_SLOTS < config.PAPER_NOTIONAL_USD


def test_an_order_that_would_move_the_pool_is_refused_not_filled():
    """The one thing a backtest can fake for free. Ten percent is the cap, and
    it is the same number a real wallet sets as slippage tolerance."""
    assert Decimal("0") < config.PAPER_MAX_IMPACT <= Decimal("0.10")


def test_the_grid_never_buys_below_the_floor_where_tokens_are_destroyed():
    """Under $75k, 32-57% of tokens lose more than a quarter in five minutes
    and 98% of those skip past any stop between two samples. No arm may buy
    there — not as a filter, as a refusal."""
    from datetime import UTC, datetime
    now = datetime.now(UTC)
    token = {"mint": "M" * 44, "fdv": Decimal("500000"), "sells": 1, "reuse": 1}
    for liq in (Decimal("1000"), Decimal("40000"), Decimal("74999")):
        for arm in ARMS:
            if arm.entry.startswith("liq_"):
                assert not accepts(arm, open_at=now, liquidity=liq, **token), (
                    f"{arm.name} would buy a ${liq} pool")


def test_no_arm_decides_by_dice_roll():
    """Every arm on this board must be a strategy someone would fund.

    A hash-of-the-mint control is a sharp null and it is executable, but it is
    not fundable, and a leaderboard topped by something unfundable answers a
    question nobody asked. The baseline is now FLOOR — buy every graduation
    above $75k — which is both a real strategy and the correct null for a
    selection rule, since every grid arm is a subset of its population.
    """
    for arm in ARMS:
        assert not arm.entry.startswith("rand"), (
            f"{arm.name} decides by hashing the mint — no rule, nothing to "
            "fund. Use FLOOR as the baseline instead")


def test_the_baseline_shares_the_grid_universe_exactly():
    """A baseline that bought a different population would not be a baseline.

    FLOOR must take every token any grid arm takes, and no token any grid arm
    refuses — otherwise 'the band beat the baseline' could just mean the two
    were shopping in different shops.
    """
    from datetime import UTC, datetime

    from app.labs.graduation.tournament import LIQ_BANDS

    now = datetime.now(UTC)
    token = {"mint": "M" * 44, "fdv": Decimal("500000"), "sells": 1, "reuse": 1}
    floor = next(a for a in ARMS if a.entry == "floor")
    grid = [a for a in ARMS if a.entry.startswith("liq_")]
    for probe in (74_999, 75_000, 100_000, 250_000, 5_000_000):
        liq = Decimal(probe)
        taken_by_grid = any(accepts(a, open_at=now, liquidity=liq, **token)
                            for a in grid)
        taken_by_floor = accepts(floor, open_at=now, liquidity=liq, **token)
        assert taken_by_grid == taken_by_floor, (
            f"${probe}: grid={taken_by_grid} floor={taken_by_floor} — the "
            "baseline and the grid must shop in the same universe")
    assert LIQ_BANDS[-1][2] >= 1_000_000_000, "the top band must be unbounded"


@pytest.mark.asyncio
async def test_retiring_an_arm_does_not_strand_its_open_positions():
    """A position on a book that is no longer an arm must still be settled.

    Generation 2 replaced generation 1 and left 51 positions open on 47
    retired arms — the oldest a TWO-MINUTE hold that had been open for
    twenty-five hours, rendered on the page as a live trade. The manage pass
    walked `BY_NAME` and skipped anything it did not recognise, so a retired
    book's rows could never close.
    """
    import inspect

    from app.labs.graduation.tournament import Tournament

    src = inspect.getsource(Tournament._manage)
    head = src[src.index("arm = BY_NAME.get"):]
    branch = head[:head.index("age =")]
    assert "_close(" in branch and "arm_retired" in branch, (
        "_manage skips positions whose arm is gone instead of settling them; "
        "those rows stay open for ever")


def test_the_curve_arm_prices_its_depth_the_way_the_impact_maths_expects():
    """`v_quote_reserves` is the QUOTE SIDE; `liquidity_usd` is the pool TOTAL.

    Every other arm passes DexScreener's total, and the impact maths halves it
    to recover the quote side. Handing the curve's reserve straight through
    would halve the depth and DOUBLE every impact figure — which would refuse
    fills a real wallet would get, and mis-price the ones it took.
    """
    from decimal import Decimal as D

    from app.labs.graduation.backtest import amm_impact
    from app.labs.graduation.tournament import _curve_depth_usd

    # Measured: a median curve at >=90% holds 97.7 SOL, and a $100 buy there
    # is ~1.01% impact.
    depth = _curve_depth_usd(D("97.7"), D("101.35"))
    impact = amm_impact(D("100"), depth)
    assert impact is not None
    assert D("0.009") < impact < D("0.011"), impact
    # No rate means no claim, rather than a guessed one.
    assert _curve_depth_usd(D("97.7"), None) is None


def test_the_curve_arm_is_refused_when_the_curve_is_too_thin():
    """The bottom decile at >=90% holds about $184 of quote. A $100 order there
    is over half the pool and must be refused, not filled."""
    from decimal import Decimal as D

    from app.labs.graduation.backtest import amm_impact
    from app.labs.graduation.tournament import _curve_depth_usd

    thin = _curve_depth_usd(D("1.82"), D("101.35"))
    impact = amm_impact(D("100"), thin)
    assert impact is not None and impact > config.PAPER_MAX_IMPACT, impact


def test_the_curve_machinery_is_inert_while_no_arm_uses_it():
    """CURVE90_2m is retired but its plumbing stays, tested and unused.

    Curve entry was not trivial to make correct — the quote-side depth alone
    would have doubled every impact figure — and the next hypothesis that
    wants pre-graduation entry should not rediscover it. It must cost nothing
    while idle: no arm carries `entry="curve"`, so `_fill_curve` returns
    before it queries anything.
    """
    from app.labs.graduation.tournament import Tournament

    assert not [a for a in ARMS if a.entry == "curve"]
    src = inspect.getsource(Tournament._fill_curve)
    guard = src[:src.index("rows = await")]
    assert 'a.entry == "curve"' in guard and "return 0" in guard, (
        "_fill_curve must bail before touching the database when no arm "
        "carries the curve entry")
