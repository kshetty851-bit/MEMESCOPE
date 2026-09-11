"""Every trading rule, with hand-computed numbers and no database."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.labs.breakout import config, rules

T0 = datetime(2026, 1, 1, tzinfo=UTC)


def candidate(mint="A", score=70, liquidity=250_000.0, volume=500_000.0,
              price=10.0) -> rules.Candidate:
    return rules.Candidate(mint=mint, episode_id=None, score=score,
                           liquidity_usd=liquidity, volume_24h_usd=volume,
                           fill_open=price)


def held(mint="A", qty=10.0, entry=10.0, slot=100.0, high_water=100.0,
         opened=T0) -> rules.Held:
    return rules.Held(mint=mint, qty=qty, entry_price=entry, slot_size=slot,
                      high_water_value=high_water, opened_at=opened)


# --- costs ----------------------------------------------------------------------

def test_slippage_moves_the_fill_against_us_on_both_sides() -> None:
    assert rules.buy_price(100.0) == pytest.approx(101.0)   # 100 bps
    assert rules.sell_price(100.0) == pytest.approx(99.0)


def test_the_fee_is_charged_on_the_notional() -> None:
    assert rules.fee(1000.0) == pytest.approx(3.0)          # 30 bps


def test_a_slot_never_spends_more_than_the_slot_size() -> None:
    """Hand-computed: $100 at 30bps buys $99.70 of token and pays $0.0299 of
    fee, totalling $99.73 — never $100.30."""
    fill = rules.open_fill(price=10.0, size=100.0)
    assert fill.notional + fill.fees <= 100.0 + 1e-9
    assert fill.notional == pytest.approx(100.0 / 1.003)
    assert fill.price == pytest.approx(10.1), "the buy is slipped up"
    assert fill.qty == pytest.approx(fill.notional / 10.1)


def test_closing_slips_down_and_pays_its_own_fee() -> None:
    fill = rules.close_fill(qty=10.0, price=10.0)
    assert fill.price == pytest.approx(9.9)
    assert fill.notional == pytest.approx(99.0)
    assert fill.fees == pytest.approx(99.0 * 0.003)


def test_a_round_trip_at_a_flat_price_loses_exactly_the_costs() -> None:
    """1% each way plus 30bps each way. The number to beat is not zero."""
    entry = rules.open_fill(price=10.0, size=100.0)
    exit_ = rules.close_fill(entry.qty, 10.0)
    net, pct = rules.pnl(entry.notional, exit_.notional, entry.fees + exit_.fees)
    assert net < 0
    assert pct == pytest.approx(-2.58, abs=0.05)


# --- sizing ---------------------------------------------------------------------

def test_the_slot_is_a_tenth_of_current_equity_and_compounds() -> None:
    assert rules.slot_size(1000.0) == pytest.approx(100.0)
    assert rules.slot_size(2000.0) == pytest.approx(200.0)
    assert rules.slot_size(500.0) == pytest.approx(50.0)


def test_there_is_no_floor_under_the_slot_size() -> None:
    """Pre-decided: below $100 of equity the lab carries on at equity/10. The
    kill switch is the only thing allowed to stop it."""
    assert rules.slot_size(50.0) == pytest.approx(5.0)
    assert rules.slot_size(1.0) == pytest.approx(0.1)


# --- entry gates ----------------------------------------------------------------

def test_a_thin_pool_is_refused() -> None:
    thin = candidate(liquidity=config.MIN_LIQ_FOR_ENTRY - 1)
    assert rules.entry_skip(thin, 100.0, frozenset()) == rules.SKIP_LIQUIDITY
    ok = candidate(liquidity=config.MIN_LIQ_FOR_ENTRY)
    assert rules.entry_skip(ok, 100.0, frozenset()) is None, "the floor is inclusive"


def test_an_unknown_liquidity_is_refused_not_assumed_deep() -> None:
    assert rules.entry_skip(candidate(liquidity=None), 100.0,
                            frozenset()) == rules.SKIP_LIQUIDITY


def test_a_position_larger_than_the_pool_share_cap_is_refused() -> None:
    """$100 into a $15,000 pool is 0.67% — over the 0.5% cap. The honest limit
    on a memecoin order is the pool, not the wallet."""
    small_pool = candidate(liquidity=15_000.0)
    assert rules.entry_skip(small_pool, 100.0, frozenset()) == rules.SKIP_LIQUIDITY
    deep = candidate(liquidity=100_000.0)
    assert rules.entry_skip(deep, 100.0, frozenset()) is None   # 0.1%
    assert rules.entry_skip(deep, 600.0, frozenset()) == rules.SKIP_POOL_SHARE  # 0.6%


def test_a_token_already_held_is_not_entered_twice() -> None:
    assert rules.entry_skip(candidate("A"), 100.0,
                            frozenset({"A"})) == rules.SKIP_HELD


def test_a_candidate_with_no_price_is_refused() -> None:
    assert rules.entry_skip(candidate(price=0.0), 100.0,
                            frozenset()) == rules.SKIP_NO_PRICE


# --- ranking and slots ----------------------------------------------------------

def test_candidates_are_ranked_by_momentum_then_volume_then_mint() -> None:
    ranked = rules.rank([
        candidate("low", score=60, volume=900.0),
        candidate("tieB", score=90, volume=100.0),
        candidate("tieA", score=90, volume=500.0),
    ])
    assert [c.mint for c in ranked] == ["tieA", "tieB", "low"]


def test_the_highest_momentum_takes_the_only_free_slot() -> None:
    """Pre-decided: score first, then 24h volume."""
    entries, skipped = rules.choose_entries(
        [candidate("weak", score=66), candidate("strong", score=95)],
        equity=1000.0, held=frozenset(), free_slots=1)
    assert [c.mint for c, _ in entries] == ["strong"]
    assert skipped["weak"] == "no_slot"


def test_a_tie_on_momentum_is_broken_by_volume() -> None:
    entries, _ = rules.choose_entries(
        [candidate("quiet", score=80, volume=1_000.0),
         candidate("busy", score=80, volume=900_000.0)],
        equity=1000.0, held=frozenset(), free_slots=1)
    assert [c.mint for c, _ in entries] == ["busy"]


def test_no_free_slots_means_no_entries_and_a_reason_for_each() -> None:
    entries, skipped = rules.choose_entries(
        [candidate("A"), candidate("B")], equity=1000.0, held=frozenset(),
        free_slots=0)
    assert entries == []
    assert skipped == {"A": "no_slot", "B": "no_slot"}


def test_a_halted_account_enters_nothing_however_good_the_setup() -> None:
    entries, skipped = rules.choose_entries(
        [candidate("A", score=100)], equity=1000.0, held=frozenset(),
        free_slots=10, halted=True)
    assert entries == [] and skipped == {"A": "halted"}


def test_every_entry_on_one_bar_gets_the_same_slot_size() -> None:
    """Sized once from the equity at the start of the pass, so the order they
    are processed in cannot change either one."""
    entries, _ = rules.choose_entries(
        [candidate("A", score=90), candidate("B", score=80)],
        equity=1000.0, held=frozenset(), free_slots=10)
    sizes = {round(fill.notional + fill.fees, 6) for _, fill in entries}
    assert len(sizes) == 1 and sizes.pop() == pytest.approx(100.0)


def test_two_candidates_for_the_same_mint_take_one_slot() -> None:
    entries, skipped = rules.choose_entries(
        [candidate("A", score=90), candidate("A", score=80)],
        equity=1000.0, held=frozenset(), free_slots=10)
    assert len(entries) == 1 and skipped["A"] == rules.SKIP_HELD


# --- the trailing stop ----------------------------------------------------------

def test_the_stop_sits_a_quarter_of_the_slot_below_the_high_water() -> None:
    assert rules.trail_amount(100.0) == pytest.approx(25.0)
    assert rules.trail_amount(200.0) == pytest.approx(50.0), "scales with the slot"
    assert rules.stop_value(150.0, 25.0) == pytest.approx(125.0)


def test_a_bar_whose_low_breaks_the_stop_exits_at_the_stop() -> None:
    step = rules.trail_step(qty=10.0, low=7.0, high=8.0, high_water=100.0, trail=25.0)
    assert step.stopped is True
    assert step.exit_value == pytest.approx(75.0)


def test_a_bar_that_both_breaks_the_stop_and_makes_a_new_high_still_exits() -> None:
    """**The ordering that decides whether this book is honest.** The low is
    taken first, always."""
    step = rules.trail_step(qty=10.0, low=7.0, high=1000.0, high_water=100.0, trail=25.0)
    assert step.stopped is True and step.exit_value == pytest.approx(75.0)


def test_a_surviving_bar_ratchets_the_high_water_up_and_never_down() -> None:
    up = rules.trail_step(qty=10.0, low=9.5, high=20.0, high_water=100.0, trail=25.0)
    assert up.stopped is False and up.high_water == pytest.approx(200.0)
    down = rules.trail_step(qty=10.0, low=9.5, high=10.5, high_water=200.0, trail=25.0)
    assert down.high_water == pytest.approx(200.0), "never ratchets down"


# --- exits ----------------------------------------------------------------------

def test_leaving_the_universe_is_the_first_exit_checked() -> None:
    """It wins even over a bar that would have been a perfectly good hold."""
    reason, price = rules.exit_reason(
        held(), low=10.0, high=11.0, close=10.5, now=T0, episode_failed=False,
        in_universe=False)
    assert reason == rules.FORCED_EXIT and price == 10.5


def test_the_trailing_stop_fires_before_the_failed_setup_rule() -> None:
    reason, _ = rules.exit_reason(
        held(), low=7.0, high=8.0, close=7.5, now=T0, episode_failed=True,
        in_universe=True)
    assert reason == rules.TRAIL_STOP


def test_a_failed_setup_closes_the_position_only_when_it_is_under_water() -> None:
    losing = rules.exit_reason(held(entry=10.0), low=9.6, high=9.9, close=9.7, now=T0,
                               episode_failed=True, in_universe=True)
    assert losing is not None and losing[0] == rules.FAILED_SETUP
    winning = rules.exit_reason(held(entry=10.0), low=10.5, high=12.0, close=11.0,
                                now=T0, episode_failed=True, in_universe=True)
    assert winning is None, "a winner keeps its trailing stop"


def test_the_time_stop_only_closes_a_loser() -> None:
    late = T0 + timedelta(hours=config.MAX_HOLD_HOURS)
    losing = rules.exit_reason(held(entry=10.0), low=9.6, high=9.9, close=9.7, now=late,
                               episode_failed=False, in_universe=True)
    assert losing is not None and losing[0] == rules.TIME_STOP
    winning = rules.exit_reason(held(entry=10.0), low=10.5, high=12.0, close=11.0,
                                now=late, episode_failed=False, in_universe=True)
    assert winning is None, "a winner is not closed on the clock"


def test_the_time_stop_does_not_fire_one_hour_early() -> None:
    early = T0 + timedelta(hours=config.MAX_HOLD_HOURS - 1)
    assert rules.exit_reason(held(entry=10.0), low=9.6, high=9.9, close=9.7, now=early,
                             episode_failed=False, in_universe=True) is None


def test_an_ordinary_bar_is_no_exit_at_all() -> None:
    assert rules.exit_reason(held(), low=9.9, high=10.5, close=10.2, now=T0,
                             episode_failed=False, in_universe=True) is None


# --- the kill switch ------------------------------------------------------------

def test_drawdown_is_measured_from_the_peak_and_never_negative() -> None:
    assert rules.drawdown_pct(600.0, 1000.0) == pytest.approx(40.0)
    assert rules.drawdown_pct(1200.0, 1000.0) == 0.0, "above the peak is not a drawdown"
    assert rules.drawdown_pct(100.0, 0.0) == 0.0


def test_the_switch_trips_strictly_beyond_the_limit() -> None:
    peak = 1000.0
    at_limit = peak * (1 - config.MAX_DRAWDOWN_PCT / 100)
    assert rules.should_halt(at_limit, peak) is False, "exactly at the limit holds"
    assert rules.should_halt(at_limit - 0.01, peak) is True


def test_pnl_is_net_of_every_cost() -> None:
    net, pct = rules.pnl(entry_notional=100.0, exit_notional=120.0, fees=0.6)
    assert net == pytest.approx(19.4)
    assert pct == pytest.approx(19.4)
    assert rules.pnl(0.0, 0.0, 0.0) == (0.0, 0.0)
