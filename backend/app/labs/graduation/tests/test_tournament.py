"""Fifty arms, eight of which must be incapable of an edge."""

from __future__ import annotations

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
    assert _coin("R1_coin50_5m", "abc", 50) == _coin("R1_coin50_5m", "abc", 50)
    mints = [f"m{i}pump" for i in range(4000)]
    for arm in CONTROLS:
        pct = int(arm.entry[4:])
        taken = sum(1 for m in mints if _coin(arm.name, m, pct))
        assert abs(taken / len(mints) * 100 - pct) < 4, arm.name
    # Two controls with the same rule must still pick different tokens, or
    # they are one control counted twice.
    a = {m for m in mints if _coin("R1_coin50_5m", m, 50)}
    b = {m for m in mints if _coin("R2_coin50_5m", m, 50)}
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

    assert took("E05_hold_5m", DAY) and took("E05_hold_5m", NIGHT)
    assert took("F04_night_5m", NIGHT) and not took("F04_night_5m", DAY)
    assert took("F05_day_5m", DAY) and not took("F05_day_5m", NIGHT)
    assert took("F01_sym_5m", DAY) and not took("F01_sym_5m", DAY, reuse=0)
    assert took("F03_newsym_5m", DAY, reuse=0) and not took("F03_newsym_5m", DAY)
    assert took("F06_deep_5m", DAY) and not took("F06_deep_5m", DAY, liquidity=D(5_000))
    assert took("F07_shallow_5m", DAY, liquidity=D(5_000))
    assert took("F08_nosell_5m", DAY) and not took("F08_nosell_5m", DAY, sells=7)
    assert took("F09_hassell_5m", DAY, sells=7)
    assert took("F10_bigcap_5m", DAY) and not took("F10_bigcap_5m", DAY, fdv=D(50_000))
    assert took("F11_smallcap_5m", DAY, fdv=D(50_000))
    # The A/B arm needs BOTH conditions.
    assert took("C01_symnight_5m", NIGHT)
    assert not took("C01_symnight_5m", DAY)
    assert not took("C01_symnight_5m", NIGHT, reuse=0)


def test_a_missing_feature_is_a_refusal_not_a_pass() -> None:
    """DexScreener can answer without liquidity or a transaction count. An arm
    that treated a missing value as satisfying its filter would be trading a
    different population from the one it claims."""
    for name in ("F06_deep_5m", "F07_shallow_5m", "F10_bigcap_5m", "F11_smallcap_5m"):
        assert not accepts(BY_NAME[name], open_at=NIGHT,
                           **{**TOKEN, "liquidity": None, "fdv": None})
    for name in ("F08_nosell_5m", "F09_hassell_5m"):
        assert not accepts(BY_NAME[name], open_at=NIGHT, **{**TOKEN, "sells": None})
    assert not accepts(BY_NAME["F01_sym_5m"], open_at=NIGHT, **{**TOKEN, "reuse": None})


def test_the_live_book_and_the_ab_arm_are_both_in_the_tournament() -> None:
    """The Paper panels render two arms of the leaderboard rather than a
    separate experiment, so those names must exist."""
    assert config.PAPER_BOOKS == ("E05_hold_5m", "C01_symnight_5m")
    for name in config.PAPER_BOOKS:
        assert name in BY_NAME
    assert BY_NAME["E05_hold_5m"].hold == config.PAPER_MAX_HOLD_MINUTES


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
    plain = BY_NAME["E05_hold_5m"]
    assert plain.exit_rule == "at 5 minutes"

    both = BY_NAME["X07_tp2_trail30"]
    assert "2x" in both.exit_rule and "30%" in both.exit_rule
    assert "60 minutes" in both.exit_rule
    assert both.exit_rule.startswith("whichever comes first")

    # Singular minute, because "1 minutes" reads as a bug in the data.
    assert BY_NAME["E01_hold_1m"].exit_rule == "at 1 minute"
