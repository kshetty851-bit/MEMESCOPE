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
    that depended on the outcome, or on a later sample, would be unbuyable.

    `buys` joined `sells` on 2026-09-16 for the $500k+flow arm. It is
    `txns_m5_buys` on the pool's FIRST recorded sample — the same row, the same
    instant, and the same feed as the depth the rule already reads. A wallet
    sees it at the moment it decides.
    """
    params = set(inspect.signature(accepts).parameters) - {"arm"}
    assert params == {"mint", "open_at", "liquidity", "fdv",
                      "sells", "buys", "reuse"}, (
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
    """Below $56 this arm's round trip costs more than it makes: the priority
    fee is flat in SOL, so a round trip is 0.98% of a $100 order and 4.56% of a
    $10 one, and B3's measured gross move stops covering it at about $56."""
    assert config.PAPER_NOTIONAL_USD >= config.WALLET_MIN_USD
    # The wallet's position must be at least the payable floor. This used to
    # assert the OPPOSITE — that the position was SMALLER than the notional the
    # returns were measured at — which is precisely the condition that made
    # every wallet figure optimistic: a $10 position was charged a $100
    # position's costs.
    position = config.WALLET_DEMO_USD / config.WALLET_DEMO_SLOTS
    assert position >= config.WALLET_MIN_USD, (
        f"a ${position} position is below the ${config.WALLET_MIN_USD} at which "
        "a round trip stops being payable")


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


def test_no_band_buys_below_the_floor_the_bands_were_drawn_from():
    """There is no FLOOR arm left to compare against — every baseline was
    retired 2026-09-15 — so what survives of that check is the absolute rule:
    nothing may buy a pool under $75k, which is where a third to a half of
    tokens are destroyed."""
    from datetime import UTC, datetime

    from app.labs.graduation.tournament import LIQ_BANDS

    now = datetime.now(UTC)
    token = {"mint": "M" * 44, "fdv": Decimal("500000"), "sells": 1, "reuse": 1}
    for probe in (1_000, 40_000, 74_999):
        # F01_all_2m is exempt and must be: it is the A/B CONTROL, and its
        # whole rule is "every graduation, no filter". Excluding it here is
        # what makes this a statement about the BANDS.
        assert not any(
            accepts(a, open_at=now, liquidity=Decimal(probe), **token)
            for a in ARMS if a.entry.startswith("liq_")), (
            f"${probe} must be refused by every band arm")
    assert LIQ_BANDS[0][1] == 75_000


async def test_retiring_an_arm_does_not_strand_its_open_positions():
    """A position on a book that is no longer an arm must still be settled.

    Generation 2 replaced generation 1 and left 51 positions open on 47
    retired arms — the oldest a TWO-MINUTE hold that had been open for
    twenty-five hours, rendered on the page as a live trade. The manage pass
    walked `BY_NAME` and skipped anything it did not recognise, so a retired
    book's rows could never close.
    """
    import uuid
    from datetime import UTC, datetime, timedelta
    from decimal import Decimal as D
    from types import SimpleNamespace

    from app.labs.graduation.models import GradPaperPosition
    from app.labs.graduation.tournament import Tournament

    now = datetime(2026, 9, 16, 12, 0, tzinfo=UTC)
    position = GradPaperPosition(
        id=uuid.uuid4(), book="R1_coin50_5m", mint="Retired111", opened_at=now - timedelta(hours=25),
        open_quote=D("0.001"), open_fill=D("0.001"), notional_usd=D(100),
        sol_usd_at_open=D(100), notional_quote=D(1), tokens=D(1000),
        peak_quote=D("0.001"), last_quote=D("0.001"), liq_open_usd=D("50000"))
    mark = SimpleNamespace(mint="Retired111", price_native=D("0.0011"),
                           liquidity_usd=D("50000"), ts=now, source="dexscreener")

    class Session:
        def __init__(self):
            self.answers = [[mark], []]

        async def scalars(self, statement):
            return SimpleNamespace(all=lambda: [position])

        async def execute(self, statement):
            rows = self.answers.pop(0)
            return SimpleNamespace(all=lambda: rows)

    assert await Tournament(Session(), now=now)._manage() == 1
    assert position.close_reason == "arm_retired"
    assert position.close_quote == D("0.0011")


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


def test_a_stop_is_only_real_if_the_price_is_fresh_enough_to_fire_it():
    """A stop on minute-old prices is worse than no stop.

    Measured 2026-09-15: collapses are cascades of ~247 sells falling 1.14% a
    SECOND, so 61-second-old data fires a 10% stop at -70% — and the observed
    median fill was -64%, which is the same number reached two ways. The stop
    arms are only honest because open positions are re-priced every
    HELD_INTERVAL_S seconds.
    """
    from app.labs.graduation.tournament import ARMS

    stops = [a for a in ARMS if a.stop is not None]
    assert stops, "no stop arms to protect"
    assert config.HELD_INTERVAL_S <= 5, (
        f"open positions are re-priced every {config.HELD_INTERVAL_S}s; at "
        "1.14% a second a stop cannot fill near its level")
    # Every stop arm must have an exact twin WITHOUT the stop, or the forward
    # comparison is against a different population.
    for arm in stops:
        twin = arm.name.replace("_SL", "")
        match = next((a for a in ARMS if a.name == twin), None)
        assert match is not None, f"{arm.name} has no stopless twin"
        assert (match.entry, match.hold) == (arm.entry, arm.hold), (
            f"{arm.name} and {twin} must differ ONLY in the stop")


def test_only_sol_quoted_pools_are_sizeable():
    """A wallet holding SOL cannot reach a USDC-quoted pool in one hop.

    `price_usd / price_native` is the QUOTE CURRENCY's dollar price, not
    always SOL's: 1.00 means the pair is stablecoin-quoted and `price_native`
    is dollars. Eight of B3_198k_5m's 213 closed trades were exactly that, on
    raydium, orca and meteora, and one had an implied rate of 0.0037 — quoted
    in neither SOL nor a dollar.

    Their RETURNS were never wrong; the quote cancels in a price ratio. What
    was wrong is the sentence the board prints beside them, which says a SOL
    wallet would have paid those prices. It would have paid two more swap legs.

    Guarded in `_rate` because every entry path sizes through it — the curve
    fill, the post-graduation fill and the paper book.
    """
    from decimal import Decimal as D

    from app.labs.graduation.paper import _rate

    # a SOL-quoted pool: token at 0.00000048 SOL, $0.000048 -> SOL ~ $100
    assert _rate(D("0.000048"), D("0.00000048")) == D(100)
    # a stablecoin pool: both prices are dollars, so the ratio is 1
    assert _rate(D("0.000048"), D("0.000048")) is None
    # and the odd one actually seen in the record
    assert _rate(D("1"), D("270")) is None
    # the band must never reject a real SOL price
    for sol in ("20", "95", "104", "260", "1000"):
        assert _rate(D(sol), D(1)) == D(sol), f"SOL at ${sol} must be tradeable"


def test_holder_concentration_is_collected_but_not_acted_on():
    """Collected because it can only be read at graduation; OFF because there
    is no evidence yet that it predicts anything.

    `getTokenLargestAccounts` answers about TODAY. For a token that has since
    rugged, today's distribution is the wreckage — so measuring it after the
    outcome and finding rugs were concentrated reads the answer rather than
    predicting it. That is why collection cannot wait for a hypothesis.

    And why the FILTER waits: LP-lock and deployer history were both collected
    here as rug predictors and neither predicted rugs. Concentration is the
    third candidate, not a known one.
    """
    from app.labs.graduation import config

    assert config.HOLDER_COLLECT_ENABLED is True, (
        "the reading cannot be taken later; collection must be on")
    assert config.HOLDER_MAX_TOP1_SHARE is None, (
        "nothing may be excluded on concentration until there is data saying "
        "concentration predicts a rug")


def test_the_board_stops_where_the_real_wallet_does():
    """`_funded_walk` and `RealWalletDriver` share `live_spec.fundable`, so the
    balance the page prints is the one the wallet would reach. A $100 account
    that halves is finished at the floor: the next signal is skipped on the
    board exactly as the wallet refuses it."""
    from datetime import UTC, datetime, timedelta

    from app.labs.graduation.api import _funded_walk

    t0 = datetime(2026, 9, 16, tzinfo=UTC)
    minutes = timedelta(minutes=1)
    trades = [(t0, t0 + 5 * minutes, -0.50),
              (t0 + 10 * minutes, t0 + 15 * minutes, 0.10)]
    cash, funded, skipped, _, _ = _funded_walk(trades)
    assert (funded, skipped) == (1, 1)
    assert cash < float(config.WALLET_MIN_USD)

    # A drawdown that stays above the floor keeps trading, at a smaller size.
    trades = [(t0, t0 + 5 * minutes, -0.10),
              (t0 + 10 * minutes, t0 + 15 * minutes, 0.10)]
    cash, funded, skipped, _, _ = _funded_walk(trades)
    assert (funded, skipped) == (2, 0)
    assert round(cash, 2) == 99.0


def test_a_split_wallet_loses_one_ticket_to_a_rug_not_the_account():
    """The same two trades at a $100 ticket and at $25. The rug ends the whole
    wallet; the split one loses a quarter and keeps trading."""
    from datetime import UTC, datetime, timedelta

    from app.labs.graduation.api import _funded_walk

    t0 = datetime(2026, 9, 17, tzinfo=UTC)
    minutes = timedelta(minutes=1)
    trades = [(t0, t0 + 5 * minutes, -1.0),
              (t0 + 10 * minutes, t0 + 15 * minutes, 0.10)]
    whole = _funded_walk(trades)
    assert (whole.funded, whole.skipped, whole.cash, whole.low) == (1, 1, 0.0, 0.0)

    split = _funded_walk(trades, ticket=25.0)
    assert (split.funded, split.skipped) == (2, 0)
    assert round(split.cash, 2) == 77.5
    assert round(split.low, 2) == 75.0


def test_a_smaller_order_moves_the_pool_less():
    """Impact is linear in order size, so a quarter-size order pays a quarter of
    it on each leg; at full size the return is exactly what was measured."""
    import pytest

    from app.labs.graduation.api import _multiple

    assert _multiple(0.05, (0.01, 0.01), 1.0) == 1.05
    assert _multiple(0.05, (), 0.25) == 1.05
    assert _multiple(0.05, (0.01, 0.01), 0.25) == pytest.approx(
        1.05 * (1.01 / 1.0025) ** 2)


def test_a_bigger_wallet_pays_more_impact_and_a_smaller_fee_share():
    """$1,000 in one ticket: ten times the order moves the pool ten times as
    far on both legs, and the flat network fee is a tenth of the share."""
    from datetime import UTC, datetime, timedelta
    from decimal import Decimal

    from app.labs.graduation.api import _funded_walk, _multiple

    t0 = datetime(2026, 9, 17, tzinfo=UTC)
    trade = (t0, t0 + timedelta(minutes=4), 0.02, 0.001, 0.001)
    big = _funded_walk([trade], Decimal("100"), ticket=1000.0, start=1000.0)
    assert (big.funded, big.skipped) == (1, 0)
    measured = _multiple(0.02, (0.001, 0.001), 1.0)
    at_ten = _multiple(0.02, (0.001, 0.001), 10.0)
    assert at_ten < measured
    # Starts at $1,000 and makes the trade's return at ten times the size,
    # plus a fee credit (the priority fee is flat in SOL).
    assert big.cash > 1000.0 * at_ten
    assert big.low == 1000.0
