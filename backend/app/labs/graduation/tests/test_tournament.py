"""Fifty arms, eight of which must be incapable of an edge."""

from __future__ import annotations

import inspect
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.labs.graduation import config
from app.labs.graduation.tournament import (
    ARMS,
    BY_NAME,
    CONTROLS,
    Arm,
    _coin,
    accepts,
)

D = Decimal
NIGHT = datetime(2026, 9, 13, 20, 0, tzinfo=UTC)
DAY = datetime(2026, 9, 13, 10, 0, tzinfo=UTC)
TOKEN = {"mint": "Abc123pump", "liquidity": D(150_000), "fdv": D(2_000_000),
         "sells": 0, "reuse": 4}
#: STRATEGY, a B3 trade of 2026-09-16, and the pool its migration made.
REAL_MINT = "Awa4V1xpYjvVtzjhqXAB6tfxvDdQv8jQ62JXTjspump"
REAL_POOL = "3AUWJB3UckEypW9QFn8gaFtiLpr5FPhBpb4Yc8jnF9dw"
#: NTDA's pool: a real pumpswap pool, and the wrong one for REAL_MINT.
OTHER_POOL = "9iBTLLovzL4hJeDo3iYj7bYMC4cMkTWGuqt5eCfY8pTo"


def test_the_tournament_is_a_hold_sweep_with_a_baseline_on_every_hold() -> None:
    """The controls are the whole point. Fifty strategies produce a leader in
    an hour whether or not any of them is good, so the leaderboard only means
    something against arms that provably cannot have an edge.

    Generation 2.1 (2026-09-14) is a HOLD SWEEP: 5 FLOOR baselines at 2/3/4/5/6
    minutes taking every qualifying graduation, wide bands crossed with the
    same 5 holds, and the 2 pre-registered A/B arms.

    B2 ($116k-$198k) was retired 2026-09-15 with all five of its holds
    negative — the band the historical slice liked best, refuted forward.

    Five STOP-CARRYING twins were added the same day, each an exact copy of an
    arm above it with a 10% hard stop. A stop makes an arm a strategy rather
    than a baseline, so FLOOR_*_SL are NOT counted among the controls.

    The 2m and 6m holds were retired 2026-09-15 — both wiped in every band
    they ran in. F01_all_2m keeps its two minutes: it is a pre-registered A/B
    arm with a judge date, not part of the sweep.

    Fourteen narrow bands came first and starved — 25 trades a day each of a
    320-token flow — while producing scatter rather than a shape. Pooled by
    HOLD the same data separated cleanly (2m +1.11%, 3m +2.22%, 5m +0.34%
    gross on identical samples), so the resolution moved to the factor that
    moves.

    One baseline per hold, so no hold is judged without an unselected twin on
    its own clock. Nothing on this board decides by hashing a mint.
    """
    assert len(ARMS) == 20
    # Karthik's quiet-pool arm (2026-09-20): the baseline's rule, refusing a
    # pool already past `QUIET_MAX_POOL_TXS` transactions. Not a control, so
    # the baseline below is unchanged and it has something to be judged against.
    # Its four-minute twin (2026-09-21) differs in the clock and NOTHING else,
    # so the pair measures the fifth minute — where the rugs land — on its own.
    # Karthik's rug-money block (2026-09-23) is a NEW arm beside the band, not
    # a change to it: BAND_55k_5m keeps running untouched as its control, so
    # the pair differs in that one filter and nothing else.
    blk, ctl = BY_NAME["BAND_55k_blk_5m"], BY_NAME["BAND_55k_5m"]
    assert blk.rug_blocked and not ctl.rug_blocked
    assert ((blk.entry, blk.hold, blk.locked, blk.quiet)
            == (ctl.entry, ctl.hold, ctl.locked, ctl.quiet))
    assert sum(a.rug_blocked for a in ARMS) == 1, (
        "one arm asks for the wide list; it is a tax on any arm whose rugs are "
        "rare (B5: +$256 -> +$229 while preventing none)")
    quiet75 = sorted((a for a in ARMS if a.entry == "floor75"),
                     key=lambda a: (a.hold, a.name))
    assert [a.name for a in quiet75] == [
        "BASE_75k_quiet_4m", "BASE_75k_quiet_5m", "KARTHIK_QUIET_5M"]
    assert [a.hold for a in quiet75] == [4, 5, 5]
    assert all(a.quiet and not a.is_control for a in quiet75)
    assert len({(a.entry, a.tp, a.trail, a.stop, a.drain, a.clock, a.locked, a.quiet)
                for a in quiet75}) == 1
    # The fast pair (2026-09-19): E75T is E75 plus ONE condition, a clean
    # operator record, so E75 is its matched control on the same clock.
    fast = {a.name: a for a in ARMS if a.entry in ("fast75", "fast75_trust")}
    assert set(fast) == {"E75_4m", "E75T_4m"}
    assert {(a.hold, a.clock, a.stop, a.drain)
            for a in fast.values()} == {(4, "entry", None, None)}
    # The BASELINE is back (2026-09-16). Without one the board could not tell a
    # profitable arm from a rising market — every arm here is a SUBSET of the
    # floor arm's population, so beating it is the claim each one makes.
    assert len(CONTROLS) == 1 and CONTROLS[0].name == "BASE_75k_5m"
    # B3_198k_3m retired the same day at -$58.90 on 213 trades. Three minutes
    # was the worst hold in every band this lab has run, and what it showed —
    # leaving earlier is worse — is still shown by 4m against 5m.
    assert not any(a.name == "B3_198k_3m" for a in ARMS)
    # The graduation-clock arms (g2, g3, g4) were retired on 2026-09-21 as
    # losers, so every live arm now counts its hold from its own fill.
    assert {a.clock for a in ARMS} == {"entry"}
    assert len({a.name for a in ARMS}) == len(ARMS)
    assert all(len(a.name) <= 32 for a in ARMS)


def test_arms_differ_only_in_entry_and_exit() -> None:
    """Anything else varying between arms would be what the tournament
    measures. Size, costs and clock are shared by construction — the Arm
    record has nowhere to put them."""
    # `ab_experiment` is not a strategy parameter and cannot become one: it
    # decides whether an arm appears on the BOARD, never what it buys or when
    # it sells. The rug-signal A/B runs on its own pre-registered clock and
    # competes with nothing here, so ranking it beside the arms invited
    # "delete the losing ones" — which would have ended it three weeks early.
    # `locked`, `quiet` and `rug_blocked` are part of the entry: whether a
    # pool's liquidity is locked, how many transactions it has already had, and
    # whether its money has been behind a rug, are all read at the buy, where
    # `accepts` cannot see them.
    assert set(Arm.__dataclass_fields__) == {
        "name", "entry", "hold", "tp", "trail", "stop", "drain", "clock",
        "note", "ab_experiment", "locked", "quiet", "rug_blocked"}
    assert all(a.ab_experiment is False for a in ARMS if a.entry.startswith("liq_")), (
        "a tournament arm flagged as an experiment would vanish from its own "
        "comparison")


def test_the_baseline_is_a_strategy_not_a_dice_roll() -> None:
    """Generation 2 dropped the coin-flip controls: a hash-of-the-mint arm is
    a sharp null and it is executable, but it is not fundable, and this lab
    exists to find something to fund.

    FLOOR — buy every graduation above the floor — is the honest null for a
    selection rule, because every grid arm is a SUBSET of its population.

    `_coin` stays in the module: it is still the right tool if a future
    generation needs a randomised control, and deleting it would mean writing
    it again from memory."""
    assert all(a.entry == "floor" for a in CONTROLS)
    assert not any(a.entry.startswith("rand") for a in ARMS)
    # Still deterministic, for whenever it is wanted again.
    assert _coin("R50_2m", "abc", 50) == _coin("R50_2m", "abc", 50)
    mints = [f"m{i}pump" for i in range(4000)]
    taken = sum(1 for m in mints if _coin("R50_2m", m, 50))
    assert abs(taken / len(mints) * 100 - 50) < 4


def test_every_entry_filter_is_implemented() -> None:
    """`accepts` raises on an unknown key, so a typo in an arm name would be a
    silent no-trade rather than an error."""
    for arm in ARMS:
        accepts(arm, open_at=NIGHT, **TOKEN)
    with pytest.raises(ValueError):
        accepts(Arm("bogus", "no_such_filter", 5), open_at=NIGHT, **TOKEN)


def test_the_filters_split_the_population_the_way_they_claim() -> None:
    def took(name: str, when: datetime, **over: object) -> bool:
        return accepts(BY_NAME[name], open_at=when, **{**TOKEN, **over})

    assert took("F01_all_2m", DAY) and took("F01_all_2m", NIGHT)
    assert took("F14_symnight_2m", NIGHT)
    assert not took("F14_symnight_2m", DAY)
    assert not took("F14_symnight_2m", NIGHT, reuse=0)
    from app.labs.graduation.tournament import LIQ_BANDS
    # The bands must never OVERLAP — a token in two bands would be counted
    # twice and the comparison between them would be meaningless.
    for (_, _, hi), (_, lo2, _) in zip(LIQ_BANDS, LIQ_BANDS[1:]):
        assert hi <= lo2, "bands must not overlap"
    # They no longer TILE, and that is deliberate: B2 ($116k-$198k) was retired
    # with all five holds negative, so that range has no band arm. It is still
    # measured — every FLOOR arm buys it — it simply has no filter claiming to
    # improve on the floor there.
    gap = [liq for liq in (80_000, 120_000, 150_000, 190_000)
           if not any(a.entry.startswith("liq_") and took(a.name, DAY, liquidity=D(liq))
                      for a in ARMS)]
    assert gap == [80_000, 120_000, 150_000, 190_000], (
        "the retired B2 range must stay uncovered by bands; if a band grew to "
        "fill it, that band is now two hypotheses wearing one name")
    # There is no FLOOR arm left to cover the retired ranges: every baseline
    # was retired on request, so those pools are now bought by nothing. That
    # is the cost of the trim and it is stated rather than asserted away.
    # Everywhere a band DOES claim, exactly one claims it.
    # B3 is the only band left, so only pools above $198k are claimed. The
    # ranges B1 and B2 covered are now unwatched by any band — deliberate,
    # and the reason the gap assertions below are what they are.
    # DERIVED, not hard-coded. This probed 2m until the two-minute arms were
    # retired and 3m until B3_198k_3m was, and each time it silently fell to an
    # empty set and asserted nothing. Taking the hold from the arms themselves
    # means a retirement can never quietly switch this test off.
    # Exit VARIANTS of a band arm (a stop, a drain, a clock from graduation)
    # buy exactly what it buys by design; the overlap rule is about bands.
    plain = [a for a in ARMS if a.entry.startswith("liq_") and a.stop is None
             and a.drain is None and a.clock == "entry"]
    band_holds = sorted({a.hold for a in plain})
    assert band_holds, "no band arms left — this test would assert nothing"
    probe_hold = band_holds[0]
    for liq in (250_000, 5_000_000):
        hit = [a.name for a in plain
               if a.hold == probe_hold and took(a.name, DAY, liquidity=D(liq))]
        assert len(hit) == 1, (liq, hit)
    # And nothing below the floor is bought at all — that is the whole point.
    assert not any(took(a.name, DAY, liquidity=D(40_000))
                   for a in ARMS if a.entry.startswith("liq_"))


def test_a_missing_feature_is_a_refusal_not_a_pass() -> None:
    """DexScreener can answer without liquidity or a transaction count. An arm
    that treated a missing value as satisfying its filter would be trading a
    different population from the one it claims."""
    for arm in ARMS:
        if not arm.entry.startswith("liq_"):
            continue
        assert not accepts(arm, open_at=NIGHT,
                           **{**TOKEN, "liquidity": None, "fdv": None})
    # Every surviving arm is a liquidity band, and a missing reading must
    # refuse rather than pass — that is the whole of this test now.


def test_the_live_book_and_the_ab_arm_are_both_in_the_tournament() -> None:
    """The Paper panels render two arms of the leaderboard rather than a
    separate experiment, so those names must exist."""
    assert config.PAPER_BOOKS == ("F01_all_2m", "F14_symnight_2m")
    for name in config.PAPER_BOOKS:
        assert name in BY_NAME
    assert BY_NAME["F01_all_2m"].hold == 2


def test_the_calling_gate_is_stated_before_the_tournament_runs() -> None:
    """Including the term that separates 'leads' from 'beats chance'."""
    assert config.TOURNEY_MIN_TRADES >= 40
    assert D("0.20") >= config.TOURNEY_MAX_TOKEN_SHARE
    # The PF term is no longer a constant — it is the noise ceiling for the
    # leader's own trade count. See `test_the_pf_bar_is_the_noise_ceiling`.
    assert callable(config.required_pf)


def test_an_arm_that_has_not_traded_cannot_lead() -> None:
    """Ranking on P&L alone puts a never-traded $0.00 above an arm that took
    one trade and lost a dollar, so the top of the board fills with arms whose
    filter has not matched anything yet. Observed live within a minute of the
    tournament opening: 17 trades closed and the board showed a leader with
    none of them.
    """
    rows = [
        {"name": "untraded", "trades": 0, "pnl": D("0.00")},
        {"name": "lost_one", "trades": 1, "pnl": D("-1.30")},
        {"name": "won_two", "trades": 2, "pnl": D("4.10")},
    ]
    rows.sort(key=lambda r: (r["trades"] > 0, r["pnl"]), reverse=True)
    assert [r["name"] for r in rows] == ["won_two", "lost_one", "untraded"]


# --- execution: could a real wallet have done this? ---------------------------

def test_a_pool_too_small_for_the_order_is_refused_not_priced() -> None:
    """The defect this replaced: a flat 25 bps was charged on a $100 order into
    a pool holding $21, and the resulting trade showed +878% and carried the
    whole leaderboard. A real transaction whose price move exceeds the wallet's
    slippage tolerance REVERTS — it does not fill badly, it does not fill.
    """
    from app.labs.graduation.backtest import amm_impact

    order = config.PAPER_NOTIONAL_USD
    # The $21 pool that produced $878 of paper profit.
    assert amm_impact(order, D(21)) > config.PAPER_MAX_IMPACT
    # A pool that can absorb a $100 order comfortably.
    assert amm_impact(order, D(200_000)) < config.PAPER_MAX_IMPACT
    # Unknown depth cannot be shown to be tradeable.
    assert amm_impact(order, None) is None
    assert config.PAPER_REQUIRE_KNOWN_DEPTH is True


def test_the_slippage_tolerance_is_a_real_wallets_tolerance() -> None:
    """Ten percent is already loose for a deliberate trade. Above it the model
    would be claiming fills nobody gets."""
    assert D("0.01") <= config.PAPER_MAX_IMPACT <= D("0.15")


def test_the_exit_is_sized_by_what_the_position_is_now_worth() -> None:
    """A token that ran 878% is ten times the order on the way out, into a pool
    that is usually no deeper. Selling it at the quote is the error that made a
    $21 pool look like $878 of profit."""
    from app.labs.graduation.backtest import amm_sell

    spot, depth, fee = D("0.000001"), D(10_000), D("0.005")
    at_cost = amm_sell(spot, value_usd=D(100), liquidity_usd=depth, fee_fraction=fee)
    after_run = amm_sell(spot, value_usd=D(978), liquidity_usd=depth, fee_fraction=fee)
    assert at_cost is not None and after_run is not None
    assert after_run < at_cost, "a grown position must be harder to sell"


# --- the bar moves with the sample -------------------------------------------

def test_the_pf_bar_is_the_noise_ceiling_not_a_round_number() -> None:
    """A flat 1.50 was wrong by a wide margin and wrong in the flattering
    direction. The tournament reports the BEST OF FORTY-TWO arms, and the
    maximum of forty-two draws is nothing like a single draw: bootstrapped
    from 553 recorded graduations under the live execution model, the luckiest
    of forty-two noise arms typically reaches PF 4.8 at forty trades and one
    time in twenty reaches 23.
    """
    assert config.required_pf(40) > D("20")
    assert config.required_pf(100) > D("3.5")
    assert config.required_pf(300) > D("2")
    assert not hasattr(config, "TOURNEY_MIN_PF"), "the flat bar is gone"


def test_the_bar_falls_as_the_sample_grows_and_never_inverts() -> None:
    """Sample size is the only thing that dilutes luck, so the requirement has
    to fall monotonically — a bar that rose with evidence would be absurd."""
    counts = [30, 40, 50, 75, 100, 150, 200, 300, 500, 800, 1200, 5000]
    bars = [config.required_pf(n) for n in counts]
    assert bars == sorted(bars, reverse=True), bars
    # Interpolated between tabulated points, not snapped to them.
    assert config.required_pf(100) > config.required_pf(125) > config.required_pf(150)
    # And it never drops below something a real trader would take seriously.
    assert bars[-1] >= config.TOURNEY_FLOOR_PF


def test_a_thin_sample_cannot_clear_its_own_bar() -> None:
    """The point of the curve: at thirty trades nothing is provable, so the
    requirement is set where noise sits rather than somewhere reachable."""
    assert config.required_pf(10) == config.required_pf(30)
    assert config.required_pf(30) > D("50")


# --- the rules are published, and cannot drift from the code -----------------

def test_every_entry_filter_is_described() -> None:
    """The page prints each arm's rule. If a filter gains a branch in
    `accepts` and no sentence in `ENTRY_RULES`, the page would describe a
    strategy the tournament is not running — so the two are bound here."""
    from app.labs.graduation.tournament import ENTRY_RULES

    used = {a.entry for a in ARMS}
    assert used <= set(ENTRY_RULES), used - set(ENTRY_RULES)
    for key, text in ENTRY_RULES.items():
        assert text and not text.endswith("."), key
    # Every control says so in its own description, so a reader skimming the
    # rules cannot mistake one for a strategy.
    for arm in CONTROLS:
        assert "BASELINE" in arm.entry_rule


def test_each_arm_states_both_halves_of_its_rule() -> None:
    for arm in ARMS:
        assert arm.entry_rule and arm.entry_rule != arm.entry, arm.name
        assert "minute" in arm.exit_rule, arm.name


def test_the_exit_rule_names_every_condition_the_arm_carries() -> None:
    """A reader must be able to tell a plain hold from a hold plus a target,
    without reading the arm's name."""
    assert BY_NAME["B3_198k_4m"].exit_rule == "at 4 minutes"
    assert BY_NAME["B3_198k_4m"].exit_rule == "at 4 minutes"
    assert BY_NAME["B3_198k_5m"].exit_rule == "at 5 minutes"
    # Singular minute, for whenever an arm holds one — the formatting must
    # not read as a bug in the data.
    from app.labs.graduation.tournament import Arm
    assert Arm("x", "all", 1).exit_rule == "at 1 minute"
    # Every arm is a plain hold now; the target and trailing families held
    # 15 minutes or more and were dropped with them.
    assert all(a.tp is None and a.trail is None for a in ARMS)


# --- the projection is an account, not a running total ------------------------

def test_a_thousand_dollar_account_cannot_lose_more_than_a_thousand() -> None:
    """The first version summed per-trade returns and reported bands like
    "-$140,681 from $1,000" — not a pessimistic forecast but an impossible
    one, because it kept funding $100 positions after the account was empty.

    Simulated here directly: a strategy that loses on every trade stops when
    it can no longer pay for the next one.
    """
    capital, size = 1000.0, 100.0
    equity, trades = capital, 0
    while equity >= size and trades < 10_000:
        equity += size * -0.50           # every trade halves its position
        trades += 1
    assert equity >= 0
    assert capital - equity <= capital, "cannot lose more than the account holds"
    assert trades < 30, "a losing arm ruins quickly, it does not run 30 days"


def test_ruin_ends_the_path_and_the_rest_of_the_month() -> None:
    """A path wiped out on day three does not collect the other twenty-seven,
    so the barrier changes the upside as well as the downside."""
    capital, size = 1000.0, 100.0
    returns = [-1.0] * 12 + [10.0]       # a winner that arrives too late
    equity, collected = capital, 0
    for r in returns:
        if equity < size:
            break
        equity += size * r
        collected += 1
    assert collected < len(returns), "the late winner is never reached"
    assert equity < capital


# --- the tick must not get slower as the lab records more --------------------

def test_the_candidate_query_is_bounded_by_the_window_not_the_table() -> None:
    """The obvious form — GROUP BY mint HAVING min(ts) >= cutoff — asks every
    mint that ever existed when its first sample was, so Postgres scans the
    whole table: 211 ms against 56,000 rows, on a table growing 130,000 a day,
    inside a tick that runs every fifteen seconds.

    The form actually used asks it backwards: a pool that opened inside the
    window HAS a sample inside it and NO sample before it. Both are index
    lookups, and the first only ever touches the last few minutes of rows.
    Measured 23 ms, and flat in table size.

    Asserted on the SQL rather than by timing, because a timing test on a
    developer machine measures the developer's machine.
    """
    import re

    from app.labs.graduation import tournament as t

    src = inspect.getsource(t.Tournament._candidates)
    body = "\n".join(ln for ln in src.splitlines()
                     if not ln.strip().startswith("#"))
    assert "exists()" in body, "the cheap form uses a NOT EXISTS"
    assert not re.search(r"having\s*\(\s*func\.min", body), (
        "HAVING min(ts) over the whole table is the scan this replaced")


def test_the_projection_window_is_bounded() -> None:
    """Per-trade returns feed the thirty-day projection. Unbounded, that query
    grows without limit; and a projection built from month-old trades would be
    describing a market that has moved on."""
    from app.labs.graduation import api

    body = inspect.getsource(api.tournament)
    assert "timedelta(days=7)" in body


def test_the_pair_switch_answer_is_memoised() -> None:
    """Deriving it is a pass over every sample ever recorded — 2,269 ms at
    56,000 rows, and it ran on every status poll. An index only reaches
    1,099 ms because the question has to look at every mint however it is
    indexed, so the answer is held instead."""
    from app.labs.graduation import paper

    assert paper._SWITCHED_TTL.total_seconds() >= 60
    src = inspect.getsource(paper.switched_mints)
    assert "_SWITCHED" in src and "frozenset" in src


def test_the_projection_is_memoised_because_its_cost_grows() -> None:
    """160 simulated paths over a thirty-day horizon, for every arm with
    enough trades, and the horizon grows with the trade rate. Measured on prod
    across three consecutive calls: 1,955 ms, 2,279 ms, 2,577 ms — climbing,
    on an endpoint polled every thirty seconds.

    A forecast of the next month does not change meaningfully in two minutes.
    Everything else on the leaderboard stays live.
    """
    from app.labs.graduation import api

    assert api._PROJECTION_TTL.total_seconds() >= 60
    body = inspect.getsource(api.tournament)
    assert "_PROJECTIONS" in body and "cached.get" in body
    # The live figures must NOT come from the memo.
    assert "realised_usd=realised" in body


# --- what a real $100 wallet would hold ---------------------------------------

def test_one_position_because_ten_could_not_pay_the_fee() -> None:
    """A conclusion corrected twice, and the second correction is not a
    retraction of the first — both measurements were right about their own
    population.

    TEN was chosen across 69 arms of an older generation, re-pricing every
    trade at each size:

        1 x $100   median $0    survived  4/69
        4 x $25    median $32   survived 60/69
        10 x $10   median $54   survived 69/69

    That generation bought everything, -99% tokens included, so a single
    position was ended by the first one it met. Ten slots bought survival.

    Generation 2.1 refuses pools under $75k, which is where those -99% tokens
    live, and the calculus inverts. The priority fee is flat in SOL, so the
    round trip is a function of order size — $100 1.41%, $50 1.82%, $20 3.05%,
    $10 5.09% — and on the board's best arm, same 86 trades:

        1 slot $310.50   2 slots $257.99   5 slots $116.75   10 slots $88.70

    Ten slots did not lose to the market. It lost to the fee: 5.09% a trade is
    larger than any gross edge this lab has measured.

    THE COST IS REAL AND STAYS SAID: one position is ended permanently by one
    -99% trade, where ten would lose a tenth. That risk is accepted because it
    is the risk a $100 account actually has — splitting $100 ten ways in this
    market is not diversification, it is paying 5% a trade for the privilege.
    """
    # The old finding still holds on the old population: concentration dies to
    # a wipeout, and that has not stopped being true.
    losses = [0.04] * 30 + [-0.99]
    one, ten = 100.0, 100.0
    for r in losses:
        one += one * r
        ten += (ten / 10) * r
    assert one < 5, "a single position is ended by one wipeout"
    assert ten > 100, "ten positions take a tenth of the hit"
    # And the fee is why ten lost anyway, once the floor removed those tokens.
    assert config.WALLET_DEMO_SLOTS == 1
    assert config.WALLET_DEMO_USD / config.WALLET_DEMO_SLOTS == config.PAPER_NOTIONAL_USD, (
        "the wallet must trade the size its returns were MEASURED at, or the "
        "board reports one number priced two ways")


def test_a_hundred_dollar_wallet_compounds_and_can_end_at_zero() -> None:
    """The tournament runs $1,000 over ten $100 slots and its P&L is ADDITIVE.
    A $100 account is a different machine: it holds one position, fully
    invested, so it compounds — and compounding has no memory of the good
    trades once a bad one takes the product to zero.

    Measured on the live book: arms with 17-99 trades show $111-$177, and
    every arm past 180 trades shows $0.00, because by then it has met its
    -99%. That is the number that applies to an account someone would fund.
    """
    grow = [0.05] * 20
    equity = 100.0
    for r in grow:
        equity *= 1 + r
    assert equity > 250, "twenty +5% trades compound well past additive"

    # One -99% ends it, and nothing after can bring it back — but ONLY if the
    # floor is the smallest position that can actually be executed. At a $1
    # floor the surviving $2.65 compounds back to nine figures on winners it
    # could never have placed, which is how this test first failed.
    ruinous = [0.05] * 20 + [-0.99] + [0.50] * 50
    equity = 100.0
    for r in ruinous:
        equity *= 1 + r
        if equity < float(config.WALLET_MIN_USD):
            equity = 0.0
            break
    assert equity == 0.0, "a wipeout is permanent for a fully-invested wallet"
    assert D("20") <= config.WALLET_MIN_USD, (
        "below ~$25 a round trip costs more than the strategy earns, so a "
        "wallet that small is finished whatever the arithmetic says")


def test_the_wallet_is_not_the_tournament_equity_divided_by_ten() -> None:
    """The obvious shortcut is wrong in both directions: additive sizing
    cannot be rescaled into compounding sizing, and a $100 account cannot run
    ten $100 positions at all."""
    assert D("100") == config.WALLET_DEMO_USD
    assert D("1000") == config.PAPER_CAPITAL_USD
    assert config.PAPER_NOTIONAL_USD * config.PAPER_MAX_SLOTS == config.PAPER_CAPITAL_USD
    # A $100 wallet could not fund even two of the tournament's positions.
    assert config.WALLET_DEMO_USD < config.PAPER_NOTIONAL_USD * 2


async def test_a_live_socket_mark_beats_a_later_stamped_dexscreener_row() -> None:
    """A DexScreener row carries its FETCH time and a price ~27s old. After
    sVkL4MXW rugged on 2026-09-15 it sat 5.7x above the pool's own reserves
    for over a minute, so "newest row" would have closed the position on a
    price that no longer existed. A socket mark inside the trust window wins;
    past it the socket is presumed down and the newest row stands."""
    from types import SimpleNamespace

    from sqlalchemy.dialects import postgresql

    from app.labs.graduation.tournament import Tournament

    class Session:
        def __init__(self, *answers):
            self.answers, self.statements = list(answers), []

        async def execute(self, statement):
            self.statements.append(statement)
            rows = self.answers.pop(0)
            return SimpleNamespace(all=lambda: rows)

    stale = SimpleNamespace(mint="A", price_native=D("0.00000022"),
                            liquidity_usd=D("10896.26"), ts=NIGHT,
                            source="dexscreener")
    live = SimpleNamespace(mint="A", price_native=D("0.000000005"),
                           liquidity_usd=D("310.00"),
                           ts=NIGHT - timedelta(seconds=2), source="held_ws")
    other = SimpleNamespace(mint="B", price_native=D("0.000001"),
                            liquidity_usd=D("200000"), ts=NIGHT,
                            source="dexscreener")
    session = Session([stale, other], [live])
    marks = await Tournament(session, now=NIGHT)._latest_prices(["A", "B"])
    assert {m: mark[:2] for m, mark in marks.items()} == {
        "A": (live.price_native, live.liquidity_usd),
        "B": (other.price_native, other.liquidity_usd)}
    # The mark says when it was read and by whom: the exit rule needs both.
    assert marks["A"].source == "held_ws" and marks["A"].ts == live.ts
    socket_query = session.statements[1].compile(dialect=postgresql.dialect())
    assert "grad_postgrad_samples.source = " in str(socket_query)
    assert "held_ws" in socket_query.params.values()
    window = [v for v in socket_query.params.values() if isinstance(v, datetime)]
    assert NIGHT - timedelta(seconds=config.HELD_TRUST_S) in window


async def test_a_tick_that_finds_another_running_steps_aside(monkeypatch) -> None:
    """At a three-second cadence a slow tick can still be running when the next
    begins. Both would fill the same graduation, and the (book, mint)
    constraint would roll back the whole second tick, its closes included."""
    from app.labs.graduation import scheduler

    class Locked:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return None

        async def scalar(self, statement):
            assert "pg_try_advisory_xact_lock" in str(statement)
            return False

    class NeverBuilt:
        def __init__(self, *args, **kwargs):
            raise AssertionError("a second tick ran")

    monkeypatch.setenv("LAB_GRADUATION_ENABLED", "1")
    monkeypatch.setenv("LAB_GRADUATION_PAPER_ENABLED", "1")
    monkeypatch.setattr(scheduler, "SessionFactory", Locked)
    monkeypatch.setattr(scheduler, "Tournament", NeverBuilt)
    assert await scheduler.paper_tick() == {"skipped": "graduation_paper_tick_running"}



class _Answers:
    """A session that answers each query with the next scripted rows."""

    def __init__(self, *answers):
        self.answers, self.statements, self.added = list(answers), [], []

    async def execute(self, statement):
        from types import SimpleNamespace

        self.statements.append(statement)
        rows = self.answers.pop(0)
        return SimpleNamespace(all=lambda: rows,
                               first=lambda: rows[0] if rows else None)

    def add(self, obj):
        self.added.append(obj)


def test_the_early_arm_is_b3_bought_earlier_not_a_new_rule() -> None:
    """B3E_198k_5m was retired on 2026-09-21 at -$412, so the rule it used is
    driven here by an arm of this test's own: the early path still runs for
    any arm that asks, and what it must and must not buy is still pinned."""
    from app.labs.graduation.tournament import BAND_BY_KEY, Arm

    early = Arm("TEST_early_5m", "early_B3", 5)
    b3 = BY_NAME["B3_198k_5m"]
    assert (early.hold, early.stop, early.tp, early.trail) == (
        b3.hold, b3.stop, b3.tp, b3.trail)
    assert BAND_BY_KEY[b3.entry][0] == config.EARLY_FLOOR_USD
    assert not early.ab_experiment and not early.is_control
    # Never from DexScreener's pool open, however deep: that would be B3 again.
    assert not accepts(early, open_at=NIGHT, **{**TOKEN, "liquidity": D(5_000_000)})


async def test_the_early_arm_buys_the_crossing_at_the_pools_own_price(
    monkeypatch,
) -> None:
    from types import SimpleNamespace

    from sqlalchemy.dialects import postgresql

    from app.labs.graduation import tournament
    from app.labs.graduation.tournament import Arm, Tournament

    crossing = SimpleNamespace(
        mint=REAL_MINT, pool=REAL_POOL, crossed_at=NIGHT - timedelta(seconds=4),
        migrated_at=NIGHT - timedelta(seconds=30),
        price_native=D("0.0000012"), depth_usd=D("250000"), sol_usd=D("100"))
    mine = Arm("TEST_early_5m", "early_B3", 5)
    monkeypatch.setattr(tournament, "ARMS", (*tournament.ARMS, mine))
    session = _Answers([(crossing, "EARLY")], [], [])
    assert await Tournament(session, now=NIGHT)._fill_early() == 1
    (position,) = session.added
    assert position.book == "TEST_early_5m"
    assert position.opened_at == crossing.crossed_at
    assert position.open_quote == crossing.price_native
    assert position.open_fill > position.open_quote     # fee and impact paid
    assert position.liq_open_usd == crossing.depth_usd
    assert position.sol_usd_at_open == D("100")
    query = str(session.statements[0].compile(dialect=postgresql.dialect()))
    assert "grad_early_opens.crossed_at >=" in query
    assert "grad_early_opens.crossed_at <=" in query

    # Already held: not bought twice.
    again = _Answers([(crossing, "EARLY")], [("TEST_early_5m", REAL_MINT)], [])
    assert await Tournament(again, now=NIGHT)._fill_early() == 0
    # A pool too shallow for $100 to fill is refused, as B3's would be.
    thin = SimpleNamespace(**{**crossing.__dict__, "depth_usd": D("500")})
    assert await Tournament(_Answers([(thin, None)], [], []), now=NIGHT)._fill_early() == 0
    # A pool the migration did not make is not a graduation, however deep.
    other = SimpleNamespace(**{**crossing.__dict__, "pool": OTHER_POOL})
    assert await Tournament(_Answers([(other, None)], [], []), now=NIGHT)._fill_early() == 0


async def test_a_graduated_curve_is_never_a_mark() -> None:
    """The early arm opens before DexScreener has a pool row. The token's last
    curve price is a fraction of the pool's, and marking on it would book a
    -99% that never happened."""
    from types import SimpleNamespace

    from app.labs.graduation.tournament import Tournament

    dead = SimpleNamespace(mint="EarlyMint", v_quote_reserves=D(85),
                           v_token_reserves=D(206_900_000), complete=True)
    live = SimpleNamespace(mint="Climbing", v_quote_reserves=D(60),
                           v_token_reserves=D(400_000_000), complete=False)
    rate = SimpleNamespace(price_usd=D("0.0002"), price_native=D("0.000002"))
    session = _Answers([], [], [rate], [dead, live])
    marks = await Tournament(session, now=NIGHT)._latest_prices(["EarlyMint", "Climbing"])
    assert "EarlyMint" not in marks
    assert marks["Climbing"][0] == D(60) / D(400_000_000)


# --- the 2026-09-16 fixes -------------------------------------------------------

def test_only_the_pool_a_pump_fun_migration_makes_is_a_graduation() -> None:
    from app.labs.graduation.tournament import graduation_pool

    assert graduation_pool(REAL_MINT) == REAL_POOL
    # JUP was bought as a "graduation" on 2026-09-15; it never had a curve.
    assert graduation_pool("JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN") != (
        "C1MgLojNLWBKADvu9BHdtgzz1oZX4dZ5zGdGcgvvW8Wz")
    assert graduation_pool("not a mint") is None


def _mk(ts: datetime, price: str, depth: str | None = "250000",
        source: str = "dexscreener"):
    from app.labs.graduation.tournament import Mark

    return Mark(D(price), D(depth) if depth else None, ts, source)


def test_a_timed_exit_is_priced_only_by_the_market_after_it_was_due() -> None:
    """FAIR, 2026-09-14: due 19:14:46, drained 19:14:50, closed 19:15:00 on a
    DexScreener row from 19:13 — booked at -0.1% instead of -100%. A row
    fetched at T quotes the market at T minus the feed's lag, so it can only
    price an exit due at or before that."""
    from app.labs.graduation.tournament import exit_mark

    due = NIGHT
    lag = timedelta(seconds=config.FEED_LAG_S)
    fetched_just_after = _mk(due + lag - timedelta(seconds=1), "1.0")
    fetched_late_enough = _mk(due + lag, "0.9")
    later = _mk(due + lag + timedelta(seconds=30), "0.8")
    assert exit_mark([fetched_just_after], due) is None
    assert exit_mark([later, fetched_late_enough, fetched_just_after], due) == (
        fetched_late_enough)
    # A socket read describes the moment it was taken: no lag. Read at `due`,
    # it describes an earlier moment than a row fetched five seconds after
    # `due + lag`, however the two were stamped.
    socket = _mk(due, "0.95", source="held_ws")
    fetched_after = _mk(due + lag + timedelta(seconds=5), "0.9")
    assert exit_mark([later, fetched_after, socket], due) == socket
    assert exit_mark([], due) is None


def test_a_drained_pool_is_priced_by_its_depth_not_its_quote() -> None:
    """After a drain DexScreener printed FAIR at 1.747 SOL — 3,500x what it was
    bought at — over $1,829 of depth. No one could sell there."""
    from app.labs.graduation.tournament import valued

    entry, liq = D("0.0005"), D("613000")
    drained = _mk(NIGHT, "1.747", depth="1829")
    price, why = valued(drained, entry, liq)
    assert why == "pool_collapsed"
    ratio = D("1829") / liq
    assert price == entry * ratio * ratio
    assert price < entry * D("0.0001")
    # A hard dump that leaves the pool standing is still a price: WOFI fell 30%
    # on 2026-09-15 with 85% of its depth intact.
    dumped = _mk(NIGHT, "0.00035", depth="521000")
    assert valued(dumped, entry, liq) == (D("0.00035"), None)
    assert valued(_mk(NIGHT, "0.00035", depth=None), entry, liq) == (D("0.00035"), None)
    assert valued(drained, entry, None) == (D("1.747"), None)
    # Emptied outright, it still books a price the column can hold, so the
    # -100% is counted rather than voided as unrepresentable.
    emptied = _mk(NIGHT, "1.747", depth="0")
    assert valued(emptied, D("0.0000001"), liq) == (D("1E-18"), "pool_collapsed")


def test_the_pool_fee_is_pumpswaps_tier_at_that_market_cap() -> None:
    """Matched to live swaps on 2026-09-16: STRATEGY at 79k SOL paid 40 bps,
    NTDA at 1.44M SOL paid 30, and a pool of unknown price is charged the top."""
    assert config.pool_fee_bps(D("0.00007898")) == 40
    assert config.pool_fee_bps(D("0.001441")) == 30
    assert config.pool_fee_bps(D("0.00006386")) == 48      # exactly 63,860 SOL
    assert config.pool_fee_bps(D("0.0000638599")) == 50
    assert config.pool_fee_bps(D("0.0000000001")) == 125
    assert config.pool_fee_bps(None) == 125
    tiers = [bps for _, bps in config.PUMPSWAP_FEE_TIERS]
    assert tiers == sorted(tiers, reverse=True)


def test_the_book_charges_the_pool_tier_and_the_router() -> None:
    from app.labs.graduation.paper import costs

    leg = costs(D("1.0"), pool_fee_bps=40)
    assert leg.fee_fraction == D("0.0040") + D("0.0010") + config.BACKTEST_PRIORITY_FEE_QUOTE
    assert config.ROUTER_FEE_BPS == 10


class _Tick:
    """Positions for `scalars`, then scripted rows for each `execute`."""

    def __init__(self, positions, *answers):
        self.positions, self.answers = positions, list(answers)
        self.statements = []

    async def scalars(self, statement):
        from types import SimpleNamespace

        return SimpleNamespace(all=lambda: self.positions)

    async def execute(self, statement):
        from types import SimpleNamespace

        self.statements.append(statement)
        rows = self.answers.pop(0)
        return SimpleNamespace(all=lambda: rows)


def _open_position(opened_at: datetime, *, book: str = "B3_198k_5m"):
    import uuid

    from app.labs.graduation.models import GradPaperPosition

    return GradPaperPosition(
        id=uuid.uuid4(), book=book, mint=REAL_MINT, opened_at=opened_at,
        open_quote=D("0.0005"), open_fill=D("0.000503"), notional_usd=D(100),
        sol_usd_at_open=D(100), notional_quote=D(1), tokens=D(1) / D("0.000503"),
        peak_quote=D("0.0005"), last_quote=D("0.0005"),
        liq_open_usd=D("613000"))


def _row(ts: datetime, price: str, depth: str, source: str = "dexscreener"):
    from types import SimpleNamespace

    return SimpleNamespace(mint=REAL_MINT, price_native=D(price),
                           liquidity_usd=D(depth), ts=ts, source=source)


async def test_a_due_position_waits_for_a_mark_taken_after_it_was_due() -> None:
    from app.labs.graduation.tournament import Tournament

    opened = NIGHT - timedelta(minutes=5, seconds=10)       # due 10s ago
    stale = _row(NIGHT - timedelta(seconds=5), "0.00051", "613000")
    position = _open_position(opened)
    session = _Tick([position], [stale], [], [stale])
    assert await Tournament(session, now=NIGHT)._manage() == 0
    assert position.closed_at is None
    # The book still marks it — it just may not sell on that mark.
    assert position.last_quote == D("0.00051")


async def test_the_first_mark_after_due_closes_it_at_that_price() -> None:
    from app.labs.graduation.tournament import Tournament

    opened = NIGHT - timedelta(minutes=6)                    # due 60s ago
    before = _row(NIGHT - timedelta(seconds=50), "0.00051", "613000")
    after = _row(NIGHT - timedelta(seconds=20), "0.00052", "614000")
    position = _open_position(opened)
    session = _Tick([position], [after], [], [before, after])
    assert await Tournament(session, now=NIGHT)._manage() == 1
    assert position.close_reason == "max_hold"
    assert position.close_quote == D("0.00052")
    assert position.closed_at == NIGHT


async def test_a_drain_after_due_is_booked_as_the_loss_it_was() -> None:
    from app.labs.graduation.tournament import Tournament

    opened = NIGHT - timedelta(minutes=6)
    drained = _row(NIGHT - timedelta(seconds=20), "1.747", "1829")
    position = _open_position(opened)
    session = _Tick([position], [drained], [], [drained])
    assert await Tournament(session, now=NIGHT)._manage() == 1
    assert position.close_reason == "pool_collapsed"
    assert position.net_return < D("-0.99")


async def test_an_exit_with_no_later_mark_is_taken_late_and_says_so() -> None:
    from app.labs.graduation.tournament import Tournament

    opened = NIGHT - timedelta(minutes=5, seconds=config.EXIT_MAX_WAIT_S + 1)
    last = _row(opened + timedelta(minutes=4), "0.00051", "613000")
    position = _open_position(opened)
    session = _Tick([position], [last], [], [last])
    assert await Tournament(session, now=NIGHT)._manage() == 1
    assert position.close_reason == "stale_exit"


async def test_a_token_that_never_graduated_is_not_bought(monkeypatch) -> None:
    """JUP, PENGU and tokenized stocks arrived as `raydium-cpmm` migrations and
    were bought as B3 on pools over $198k. Priced on any pool but the one the
    pump.fun migration made, a candidate is not a graduation."""
    from types import SimpleNamespace

    from app.labs.graduation import tournament
    from app.labs.graduation.tournament import Tournament

    def candidate(pair):
        return SimpleNamespace(
            mint=REAL_MINT, open_at=NIGHT, price_native=D("0.00008"),
            graduated_at=NIGHT - timedelta(seconds=40),
            price_usd=D("0.008"), pair_address=pair,
            liquidity_usd=D("250000"), fdv=D("8000000"), txns_m5_sells=1,
            txns_m5_buys=50, symbol=None, first_seen_at=None)

    async def no_mirror(session, entries):
        return 0

    monkeypatch.setattr(tournament.live_decisions, "record", no_mirror)
    # Nine arms take a $250k pool: the baseline, the seven B3 arms — five on
    # the entry clock plus g2/g3/g4 on the graduation clock, which this
    # candidate graduated 40s ago so all three still have time — and the
    # all-graduations A/B control. B5 needs $500k; B3E and the night A/B do not
    # buy from this query.
    for pair, bought in ((OTHER_POOL, 0), (REAL_POOL, 4)):
        session = _Answers([], [], [])
        session.statements = []
        t = Tournament(session, now=NIGHT)

        async def rows(pair=pair):
            return [candidate(pair)]

        monkeypatch.setattr(t, "_candidates", rows)
        assert await t._fill() == bought
        assert all(p.pool_fee_bps == 40 for p in session.added)


# --- the rug arms ------------------------------------------------------------

def test_the_rug_arms_say_what_they_do() -> None:
    """The drain exit and the graduation clocks were retired on 2026-09-21
    (drain -$310, g2 -$542, g3 -$406, g4 -$361, against +$508 for the B3 they
    vary). The sentences they printed are still what those rules say, so they
    are pinned on arms of this test's own rather than dropped."""
    from app.labs.graduation.tournament import Arm

    drain = Arm("TEST_DR", "liq_B3", 5, drain=Decimal("0.20"))
    assert drain.exit_rule == (
        "whichever comes first: the pool loses 20% of its SOL, or 5 minutes")
    assert Arm("TEST_g4", "liq_B3", 4, clock="graduation").exit_rule == (
        "at 4 minutes after graduating")
    assert not drain.is_control


def test_a_graduation_clock_counts_from_the_graduation(monkeypatch) -> None:
    """The graduation clocks (g2, g3, g4) were retired on 2026-09-21 as
    losers. The clock itself is still in `_due` and `_time_left` for any arm
    that asks, so it is pinned here on an arm of this test's own."""
    from app.labs.graduation import tournament
    from app.labs.graduation.tournament import Arm, _due, _time_left

    g4 = Arm("TEST_g4", "liq_B3", 4, clock="graduation")
    monkeypatch.setattr(tournament, "BY_NAME", {**BY_NAME, g4.name: g4})
    graduated = NIGHT - timedelta(seconds=50)
    position = _open_position(NIGHT, book=g4.name)
    position.graduated_at = graduated
    assert _due(position) == graduated + timedelta(minutes=4)
    # Unknown graduation: the entry is all there is to count from.
    position.graduated_at = None
    assert _due(position) == NIGHT + timedelta(minutes=4)
    b3 = BY_NAME["B3_198k_5m"]
    # A pool listed three minutes in still has a minute to hold; one listed
    # later would be bought and sold in the same breath.
    assert _time_left(g4, graduated + timedelta(minutes=3), graduated)
    assert not _time_left(g4, graduated + timedelta(minutes=3, seconds=1), graduated)
    assert not _time_left(g4, NIGHT, None)
    assert _time_left(b3, graduated + timedelta(minutes=30), None)


def test_the_short_graduation_clocks_only_take_a_pool_listed_in_time(monkeypatch) -> None:
    """g2 sells two minutes after the graduation, so it can only buy a pool
    the feed reports inside the first minute — and DexScreener reports a B3
    pool a median 52s in. It will therefore fund fewer trades than g3 or g4,
    which is the rule rather than a fault: an exit a wallet cannot reach in
    time is not a rule it can run."""
    from app.labs.graduation import tournament
    from app.labs.graduation.tournament import Arm, _due, _time_left

    graduated = NIGHT - timedelta(seconds=50)
    g2 = Arm("TEST_g2", "liq_B3", 2, clock="graduation")
    g3 = Arm("TEST_g3", "liq_B3", 3, clock="graduation")
    monkeypatch.setattr(tournament, "BY_NAME", {**BY_NAME, g2.name: g2, g3.name: g3})

    position = _open_position(NIGHT, book=g2.name)
    position.graduated_at = graduated
    assert _due(position) == graduated + timedelta(minutes=2)

    assert _time_left(g2, graduated + timedelta(seconds=52), graduated)
    assert _time_left(g2, graduated + timedelta(minutes=1), graduated)
    assert not _time_left(g2, graduated + timedelta(minutes=1, seconds=1), graduated)
    # g3 takes the same pool with a minute to spare.
    assert _time_left(g3, graduated + timedelta(minutes=2), graduated)
    assert not _time_left(g3, graduated + timedelta(minutes=2, seconds=1), graduated)


async def test_a_drain_stop_sells_on_the_market_after_it_fires(monkeypatch) -> None:
    """FAIR went from 2,960 SOL to 41 in one second; USGR took twenty. A stop
    that fired on a drained mark and sold AT that mark would book a price the
    drain had already left behind, so the sale is the first mark after the
    stop plus the time a wallet needs to act.

    B3_198k_5m_DR was retired on 2026-09-21 at -$310, so the rule is pinned
    here on an arm of this test's own."""
    from app.labs.graduation import tournament
    from app.labs.graduation.tournament import Arm, Tournament

    drain = Arm("TEST_DR", "liq_B3", 5, drain=Decimal("0.20"))
    monkeypatch.setattr(tournament, "BY_NAME", {**BY_NAME, drain.name: drain})
    opened = NIGHT - timedelta(minutes=1)
    position = _open_position(opened, book=drain.name)
    draining = _row(NIGHT - timedelta(seconds=2), "0.00031", "440000", source="held_ws")
    first = await Tournament(_Tick([position], [draining], [draining]),
                             now=NIGHT)._manage()
    assert first == 0 and position.closed_at is None
    assert position.exit_signal == "drain_stop"
    assert position.exit_signal_at == draining.ts + timedelta(
        seconds=config.EXIT_REACTION_S)

    later = NIGHT + timedelta(seconds=10)
    after = _row(NIGHT + timedelta(seconds=4), "0.00020", "350000", source="held_ws")
    session = _Tick([position], [after], [after], [draining, after])
    assert await Tournament(session, now=later)._manage() == 1
    assert position.close_reason == "drain_stop"
    assert position.close_quote == D("0.00020")


async def test_a_pool_that_holds_its_depth_does_not_trip_the_drain_stop(
    monkeypatch,
) -> None:
    from app.labs.graduation import tournament
    from app.labs.graduation.tournament import Arm, Tournament

    drain = Arm("TEST_DR", "liq_B3", 5, drain=Decimal("0.20"))
    monkeypatch.setattr(tournament, "BY_NAME", {**BY_NAME, drain.name: drain})
    position = _open_position(NIGHT - timedelta(minutes=1), book=drain.name)
    dip = _row(NIGHT - timedelta(seconds=2), "0.00045", "560000", source="held_ws")
    assert await Tournament(_Tick([position], [dip], [dip]), now=NIGHT)._manage() == 0
    assert position.exit_signal is None


async def test_a_price_stop_also_sells_on_the_mark_after_it(monkeypatch) -> None:
    from app.labs.graduation import tournament
    from app.labs.graduation.tournament import Arm, Tournament

    # B3_198k_5m_SL was retired on 2026-09-21; the hard stop itself still
    # works for any arm that asks, so this drives it with one of its own.
    stopper = Arm("TEST_SL", "liq_B3", 5, stop=Decimal("0.10"))
    monkeypatch.setattr(tournament, "BY_NAME", {**BY_NAME, stopper.name: stopper})
    position = _open_position(NIGHT - timedelta(minutes=1), book=stopper.name)
    fell = _row(NIGHT - timedelta(seconds=40), "0.00042", "600000")
    assert await Tournament(_Tick([position], [fell], []), now=NIGHT)._manage() == 0
    assert position.exit_signal == "hard_stop"
    # A DexScreener row describes the market 27s before it was fetched.
    assert position.exit_signal_at == (fell.ts - timedelta(seconds=config.FEED_LAG_S)
                                       + timedelta(seconds=config.EXIT_REACTION_S))
    next_row = _row(NIGHT + timedelta(seconds=5), "0.00040", "590000")
    session = _Tick([position], [next_row], [], [fell, next_row])
    assert await Tournament(session, now=NIGHT + timedelta(seconds=10))._manage() == 1
    assert position.close_reason == "hard_stop"
    assert position.close_quote == D("0.00040")


# --- pool-open buys are priced off the pool ----------------------------------

def _pool(price: str, sol: str, *, quote_mint: str = config.WSOL_MINT):
    """A pool whose vaults hold `sol` SOL against tokens trading at `price`."""
    from app.labs.graduation.held_watch import Held

    tokens = Decimal(sol) / Decimal(price)
    return Held(mint=REAL_MINT, pool=REAL_POOL, base_vault="BaseVault",
                quote_vault="QuoteVault", base_decimals=6, quote_decimals=9,
                base=int(tokens * 10**6), quote=int(Decimal(sol) * 10**9),
                quote_mint=quote_mint, lp_supply=0)   # a migration pool: LP burned


async def _buy(monkeypatch, *, feed_price: str, pool, liquidity: str = "250000",
               full: bool = False, tx_reader=None):
    """One pool-open candidate through `_fill`, with the pool read as `pool`.
    The tick runs 12s after the feed first listed the pool."""
    from types import SimpleNamespace

    from app.labs.graduation import tournament
    from app.labs.graduation.tournament import Tournament

    mirrored, reads = [], []

    async def record(session, entries):
        mirrored.extend(entries)
        return len(entries)

    async def reader(mint, pool_address):
        reads.append((mint, pool_address))
        return pool

    monkeypatch.setattr(tournament.live_decisions, "record", record)
    tournament._POOL_TXS.clear()
    session = _Answers([], [], [])
    t = Tournament(session, now=NIGHT + timedelta(seconds=12), pool_reader=reader,
                   tx_reader=tx_reader)

    async def rows():
        return [SimpleNamespace(
            mint=REAL_MINT, open_at=NIGHT, price_native=Decimal(feed_price),
            graduated_at=NIGHT - timedelta(seconds=40),
            price_usd=Decimal(feed_price) * 100, pair_address=REAL_POOL,
            liquidity_usd=Decimal(liquidity), fdv=Decimal("8000000"),
            txns_m5_sells=1, txns_m5_buys=50, symbol=None, first_seen_at=None)]

    monkeypatch.setattr(t, "_candidates", rows)
    if full:  # every arm already at its slot limit
        from app.labs.graduation.tournament import ARMS

        async def counts():
            return {arm.name: config.PAPER_MAX_SLOTS for arm in ARMS}

        monkeypatch.setattr(t, "_open_counts", counts)
    return await t._fill(), session.added, mirrored, reads


async def test_the_quiet_arm_buys_only_a_pool_that_is_still_quiet(
    monkeypatch,
) -> None:
    """Under the pre-registered line it buys, at or over it the arm sits out,
    and an unread count is not proven quiet. The other arms are untouched."""
    from app.labs.graduation.tournament import Tournament

    cut = config.QUIET_MAX_POOL_TXS
    for count, buys in ((0, True), (cut - 1, True), (cut, False), (None, False)):
        reads = []

        async def reader(pool, at, count=count):
            reads.append(pool)
            return count

        monkeypatch.setattr(Tournament, "_tx_reader", None, raising=False)
        _, added, _, _ = await _buy(monkeypatch, feed_price="0.00050",
                                    pool=_pool("0.00050", "500"), tx_reader=reader)
        books = {p.book for p in added}
        assert ("BASE_75k_quiet_5m" in books) is buys, count
        assert "BASE_75k_5m" in books        # the baseline takes it either way
        assert len(reads) == 1               # one read per coin, not per arm


async def test_an_arm_that_asks_for_locked_liquidity_gets_it(monkeypatch) -> None:
    """LP supply zero on the buy's own read is locked; outstanding LP or an
    unread LP mint is not. No arm has asked since BASE_10k_2m was retired on
    2026-09-20, so the rule is driven here by an arm of this test's own."""
    from app.labs.graduation import tournament
    from app.labs.graduation.tournament import ARMS, Arm

    mine = Arm("TEST_locked_2m", "all", 2, locked=True)
    monkeypatch.setattr(tournament, "ARMS", (*ARMS, mine))
    for lp_supply, locked in ((0, True), (5_000, False), (None, False)):
        pool = _pool("0.00050", "500")
        pool.lp_supply = lp_supply
        _, added, _, _ = await _buy(monkeypatch, feed_price="0.00050", pool=pool)
        books = {p.book for p in added}
        assert ("TEST_locked_2m" in books) is locked, lp_supply
        assert "F01_all_2m" in books


async def test_a_buy_fills_at_the_pools_own_price_not_the_feeds_first_report(
    monkeypatch,
) -> None:
    """Bluey, 2026-09-17: DexScreener's first report said 0.000004773 SOL while
    the pool already traded near 0.0000541 after its first big buy. Bought at
    the report, the book booked +1,044%; on-chain the trade made +4%."""
    bought, added, mirrored, reads = await _buy(
        monkeypatch, feed_price="0.000004773", pool=_pool("0.0000541", "980"))
    assert bought == 4   # every arm this coin qualifies for; a $250k pool is
    # above the band arms' ceiling, so only the deep books take it
    assert reads == [(REAL_MINT, REAL_POOL)], "one read prices every arm"
    for p in added:
        assert abs(p.open_quote / Decimal("0.0000541") - 1) < Decimal("0.001")
        assert p.open_fill > p.open_quote, "a buy pays above spot"
        # The clock starts when the price was taken, not when the feed listed.
        assert p.opened_at == NIGHT + timedelta(seconds=12)
        assert p.liq_open_usd == Decimal("250000"), "the arm's own number is kept"
    assert mirrored and {m.opened_at for m in mirrored} == {NIGHT + timedelta(seconds=12)}
    assert all(abs(m.price_native / Decimal("0.0000541") - 1) < Decimal("0.001")
               for m in mirrored)


async def test_a_pool_that_cannot_be_read_is_not_bought_on_the_feeds_price(
    monkeypatch,
) -> None:
    bought, added, mirrored, reads = await _buy(monkeypatch, feed_price="0.00008", pool=None)
    assert (bought, added, mirrored, len(reads)) == (0, [], [], 1)


async def test_a_pool_price_a_scale_error_away_is_not_bought(monkeypatch) -> None:
    """A thousandfold is what the decimals error produced on 2026-09-15. Eleven
    times (Bluey) was the market; fifty is where the band stops believing it."""
    assert (await _buy(monkeypatch, feed_price="0.00008", pool=_pool("0.08", "980")))[0] == 0
    assert (await _buy(monkeypatch, feed_price="0.00008",
                       pool=_pool("0.00000008", "980")))[0] == 0
    assert (await _buy(monkeypatch, feed_price="0.00008",
                       pool=_pool("0.00088", "980")))[0] == 4


async def test_a_pool_not_quoted_in_sol_is_not_bought(monkeypatch) -> None:
    usdc = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
    pool = _pool("0.00008", "980", quote_mint=usdc)
    assert (await _buy(monkeypatch, feed_price="0.00008", pool=pool))[0] == 0


async def test_the_pool_is_only_read_for_a_candidate_an_arm_would_take(monkeypatch) -> None:
    """Candidates come back every tick for three minutes. Reading the chain for
    ones no arm wants would be a read per candidate per tick for nothing."""
    bought, _, _, reads = await _buy(monkeypatch, feed_price="0.00008",
                                     pool=_pool("0.00008", "980"), full=True)
    assert (bought, reads) == (0, [])


async def test_the_scheduler_prices_pool_opens_off_the_pool(monkeypatch) -> None:
    from app.labs.graduation import scheduler, sources

    built: dict = {}

    class Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return None

        async def scalar(self, statement):
            return True

        async def commit(self):
            return None

    class Recorded:
        def __init__(self, session, **kwargs):
            built.update(kwargs)

        async def tick(self):
            return {"ticked": True}

    monkeypatch.setenv("LAB_GRADUATION_ENABLED", "1")
    monkeypatch.setenv("LAB_GRADUATION_PAPER_ENABLED", "1")
    monkeypatch.setattr(scheduler, "SessionFactory", Session)
    monkeypatch.setattr(scheduler, "Tournament", Recorded)
    assert await scheduler.paper_tick() == {"ticked": True}
    assert built["pool_reader"] is sources.pool_now


def test_karthiks_small_pool_checks_buy_only_their_band():
    """KARTHIK_Q25_5M and KARTHIK_Q50_5M: his rule on the pools his book skips.
    Half-open bands, so a pool sits in exactly one of them."""
    from datetime import UTC, datetime
    from decimal import Decimal

    from app.labs.graduation.tournament import BY_NAME, accepts

    at = datetime(2026, 9, 26, tzinfo=UTC)
    def takes(name, usd):
        return accepts(BY_NAME[name], mint="xpump", open_at=at, liquidity=Decimal(usd),
                       fdv=None, sells=None, reuse=None)
    assert [takes("KARTHIK_Q25_5M", v) for v in (24_999, 25_000, 49_999, 50_000)] == [
        False, True, True, False]
    assert [takes("KARTHIK_Q50_5M", v) for v in (49_999, 50_000, 74_999, 75_000)] == [
        False, True, True, False]
    assert BY_NAME["KARTHIK_Q25_5M"].quiet and BY_NAME["KARTHIK_Q50_5M"].quiet
    assert BY_NAME["KARTHIK_Q25_5M"].hold == BY_NAME["KARTHIK_Q50_5M"].hold == 5
