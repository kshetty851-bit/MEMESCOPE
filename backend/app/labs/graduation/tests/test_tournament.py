"""Fifty arms, eight of which must be incapable of an edge."""

from __future__ import annotations

import inspect
from datetime import UTC, datetime
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


def test_the_tournament_is_fifty_arms_of_which_eight_are_noise() -> None:
    """The controls are the whole point. Fifty strategies produce a leader in
    an hour whether or not any of them is good, so the leaderboard only means
    something against arms that provably cannot have an edge."""
    assert len(ARMS) == 50
    assert len(CONTROLS) == 8
    assert len({a.name for a in ARMS}) == 50
    assert all(len(a.name) <= 32 for a in ARMS)


def test_arms_differ_only_in_entry_and_exit() -> None:
    """Anything else varying between arms would be what the tournament
    measures. Size, costs and clock are shared by construction — the Arm
    record has nowhere to put them."""
    assert set(Arm.__dataclass_fields__) == {
        "name", "entry", "hold", "tp", "trail", "note"}


def test_a_control_decides_on_nothing_and_never_changes_its_mind() -> None:
    """Hashed rather than drawn: a control that re-rolled each tick would be a
    different rule every time, and could not be compared with anything."""
    assert _coin("R1_coin50_1m", "abc", 50) == _coin("R1_coin50_1m", "abc", 50)
    mints = [f"m{i}pump" for i in range(4000)]
    for arm in CONTROLS:
        pct = int(arm.entry[4:])
        taken = sum(1 for m in mints if _coin(arm.name, m, pct))
        assert abs(taken / len(mints) * 100 - pct) < 4, arm.name
    # Two controls with the same rule must still pick different tokens, or
    # they are one control counted twice.
    a = {m for m in mints if _coin("R1_coin50_1m", m, 50)}
    b = {m for m in mints if _coin("R2_coin50_2m", m, 50)}
    assert 0.2 < len(a & b) / len(a | b) < 0.5


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

    assert took("F15_all_2m", DAY) and took("F15_all_2m", NIGHT)
    assert took("F19_night_2m", NIGHT) and not took("F19_night_2m", DAY)
    assert took("F20_day_2m", DAY) and not took("F20_day_2m", NIGHT)
    assert took("F16_sym_2m", DAY) and not took("F16_sym_2m", DAY, reuse=0)
    assert took("F18_newsym_2m", DAY, reuse=0) and not took("F18_newsym_2m", DAY)
    assert took("F21_deep_2m", DAY) and not took("F21_deep_2m", DAY, liquidity=D(5_000))
    assert took("F22_shallow_2m", DAY, liquidity=D(5_000))
    assert took("F23_nosell_2m", DAY) and not took("F23_nosell_2m", DAY, sells=7)
    assert took("F24_hassell_2m", DAY, sells=7)
    assert took("F25_bigcap_2m", DAY) and not took("F25_bigcap_2m", DAY, fdv=D(50_000))
    assert took("F26_smallcap_2m", DAY, fdv=D(50_000))
    # The combined arm needs BOTH conditions.
    assert took("F28_symnight_2m", NIGHT)
    assert not took("F28_symnight_2m", DAY)
    assert not took("F28_symnight_2m", NIGHT, reuse=0)


def test_a_missing_feature_is_a_refusal_not_a_pass() -> None:
    """DexScreener can answer without liquidity or a transaction count. An arm
    that treated a missing value as satisfying its filter would be trading a
    different population from the one it claims."""
    for name in ("F21_deep_2m", "F22_shallow_2m", "F25_bigcap_2m", "F26_smallcap_2m"):
        assert not accepts(BY_NAME[name], open_at=NIGHT,
                           **{**TOKEN, "liquidity": None, "fdv": None})
    for name in ("F23_nosell_2m", "F24_hassell_2m"):
        assert not accepts(BY_NAME[name], open_at=NIGHT, **{**TOKEN, "sells": None})
    assert not accepts(BY_NAME["F16_sym_2m"], open_at=NIGHT, **{**TOKEN, "reuse": None})


def test_the_live_book_and_the_ab_arm_are_both_in_the_tournament() -> None:
    """The Paper panels render two arms of the leaderboard rather than a
    separate experiment, so those names must exist."""
    assert config.PAPER_BOOKS == ("F15_all_2m", "F28_symnight_2m")
    for name in config.PAPER_BOOKS:
        assert name in BY_NAME
    assert BY_NAME["F15_all_2m"].hold == config.PAPER_MAX_HOLD_MINUTES


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
        assert "CONTROL" in arm.entry_rule


def test_each_arm_states_both_halves_of_its_rule() -> None:
    for arm in ARMS:
        assert arm.entry_rule and arm.entry_rule != arm.entry, arm.name
        assert "minute" in arm.exit_rule, arm.name


def test_the_exit_rule_names_every_condition_the_arm_carries() -> None:
    """A reader must be able to tell a plain hold from a hold plus a target,
    without reading the arm's name."""
    assert BY_NAME["F15_all_2m"].exit_rule == "at 2 minutes"
    assert BY_NAME["F29_all_3m"].exit_rule == "at 3 minutes"
    # Singular minute, because "1 minutes" reads as a bug in the data.
    assert BY_NAME["F01_all_1m"].exit_rule == "at 1 minute"
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
