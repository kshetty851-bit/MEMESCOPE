"""The frozen Arena rules. Editing a threshold here is a NEW candidate.

These tests exist to make a silent rule change impossible: the constants are
pinned, missing data is proven to skip rather than pass, and each condition is
shown to be load-bearing.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.arena import rules
from app.arena.rules import Observation

pytestmark = pytest.mark.unit


def test_frozen_constants_match_protocol_v1():
    assert rules.RULES_VERSION == "1.0.0"
    assert rules.CHECKPOINT_MINUTES == 30
    assert rules.TAKE_PROFIT_MULTIPLE == Decimal("1.5")
    assert rules.TIME_EXIT_HOURS == 6
    assert rules.STARTING_EQUITY == Decimal("1000.00")
    assert rules.POSITION_SIZE_USD == Decimal("10.00")
    assert rules.MAX_CONCURRENT == 5
    assert rules.MAX_DEPLOYED_USD == Decimal("50.00")
    assert rules.FAILURE_EQUITY_FLOOR == Decimal("800.00")


def _good_b():
    return Observation(buy_route_ok=True, sell_route_ok=True,
                       quoted_impact_pct=Decimal("1.0"), liquidity_usd=Decimal("50000"))


def _good_c():
    return Observation(unique_wallets_1h=40, unique_buyers_1h=25, unique_sellers_1h=15,
                       top10_tx_share=Decimal("0.5"), flow_quality="exact")


def _good_d():
    return Observation(liquidity_usd=Decimal("60000"), liquidity_at_10m=Decimal("50000"),
                       max_liquidity_drop_frac=Decimal("0.1"), observation_count=30,
                       drawdown_from_peak=Decimal("0.2"))


@pytest.mark.parametrize("fn,obs", [(rules.evaluate_b, _good_b()), (rules.evaluate_c, _good_c()),
                                    (rules.evaluate_d, _good_d())])
def test_a_fully_qualifying_observation_passes(fn, obs):
    assert fn(obs).eligible is True


@pytest.mark.parametrize("field", ["buy_route_ok", "sell_route_ok", "quoted_impact_pct", "liquidity_usd"])
def test_b_treats_every_missing_input_as_a_skip_not_a_pass(field):
    obs = _good_b()
    v = rules.evaluate_b(Observation(**{**{k: getattr(obs, k) for k in obs.__slots__}, field: None}))
    assert v.eligible is False and v.skip_reason.startswith("unknown_")


def test_b_rejects_the_case_the_arena_exists_for():
    """Buy works, sell does not. Production measured 46 of these."""
    v = rules.evaluate_b(Observation(buy_route_ok=True, sell_route_ok=False,
                                     quoted_impact_pct=Decimal("1"), liquidity_usd=Decimal("50000")))
    assert v.eligible is False and v.skip_reason == "sell_route_failed"


def test_b_rejects_impact_above_three_percent():
    v = rules.evaluate_b(Observation(buy_route_ok=True, sell_route_ok=True,
                                     quoted_impact_pct=Decimal("3.01"), liquidity_usd=Decimal("50000")))
    assert v.skip_reason == "impact_above_3pct"


def test_c_rejects_narrow_participation_and_domination():
    narrow = Observation(unique_wallets_1h=19, unique_buyers_1h=15, unique_sellers_1h=2,
                         top10_tx_share=Decimal("0.3"), flow_quality="exact")
    assert rules.evaluate_c(narrow).skip_reason == "wallets_below_20"
    dominated = Observation(unique_wallets_1h=40, unique_buyers_1h=25, unique_sellers_1h=15,
                            top10_tx_share=Decimal("0.81"), flow_quality="exact")
    assert rules.evaluate_c(dominated).skip_reason == "top10_share_above_80pct"


def test_c_refuses_to_judge_on_truncated_flow_data():
    capped = Observation(unique_wallets_1h=40, unique_buyers_1h=25, unique_sellers_1h=15,
                         top10_tx_share=Decimal("0.5"), flow_quality="capped")
    assert rules.evaluate_c(capped).skip_reason == "flow_window_capped"


def test_d_rejects_decay_and_withdrawal():
    decay = Observation(liquidity_usd=Decimal("40000"), liquidity_at_10m=Decimal("50000"),
                        max_liquidity_drop_frac=Decimal("0.1"), observation_count=30,
                        drawdown_from_peak=Decimal("0.1"))
    assert rules.evaluate_d(decay).skip_reason == "liquidity_decaying"
    pulled = Observation(liquidity_usd=Decimal("60000"), liquidity_at_10m=Decimal("50000"),
                         max_liquidity_drop_frac=Decimal("0.51"), observation_count=30,
                         drawdown_from_peak=Decimal("0.1"))
    assert rules.evaluate_d(pulled).skip_reason == "liquidity_withdrawal_over_50pct"


def test_e_requires_one_condition_from_each_family():
    ok = Observation(buy_route_ok=True, sell_route_ok=True, unique_wallets_1h=25,
                     liquidity_usd=Decimal("50000"), liquidity_at_10m=Decimal("40000"))
    assert rules.evaluate_e(ok).eligible is True
    assert rules.evaluate_e(Observation(**{**{k: getattr(ok, k) for k in ok.__slots__},
                                           "sell_route_ok": False})).skip_reason == "not_two_sided"


class TestTheFrozenExitPolicy:
    def test_a_dead_pool_settles_before_any_target_is_honoured(self):
        """A price print from a pool nobody can sell into is not a fill."""
        assert rules.exit_decision(multiple=Decimal("9"), liquidity_usd=Decimal("50000"),
                                   sell_route_ok=True, held_hours=1, is_dead=True) == "dead_zero"

    def test_a_lost_sell_route_exits_even_in_profit(self):
        assert rules.exit_decision(multiple=Decimal("1.4"), liquidity_usd=Decimal("50000"),
                                   sell_route_ok=False, held_hours=1, is_dead=False) == "sell_route_lost"

    def test_collapsed_liquidity_counts_as_a_lost_route(self):
        assert rules.exit_decision(multiple=Decimal("1.0"), liquidity_usd=Decimal("999"),
                                   sell_route_ok=None, held_hours=1, is_dead=False) == "sell_route_lost"

    def test_target_and_time_fire_at_their_frozen_levels(self):
        assert rules.exit_decision(multiple=Decimal("1.5"), liquidity_usd=Decimal("50000"),
                                   sell_route_ok=True, held_hours=1, is_dead=False) == "target_1_5x"
        assert rules.exit_decision(multiple=Decimal("1.0"), liquidity_usd=Decimal("50000"),
                                   sell_route_ok=True, held_hours=6, is_dead=False) == "time_6h"
        assert rules.exit_decision(multiple=Decimal("1.49"), liquidity_usd=Decimal("50000"),
                                   sell_route_ok=True, held_hours=5.9, is_dead=False) is None
