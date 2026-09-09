"""Strategy C: a wider stop must buy a smaller position, or the risk budget
this function exists to enforce is fiction.

THE ONE SUBTLETY, STATED RATHER THAN ENGINEERED AROUND
------------------------------------------------------
Risk equality holds where the notional cap does not bind. Rafiq's own
`max_notional_usd = 50` is a real, deliberate ceiling, and above it the deep
pool's position is clipped, so its dollar risk falls BELOW the thin pool's. The
equality test therefore runs at an equity where neither side is capped, and the
capped case is asserted separately as the truncation it is. Loosening the cap
to make a prettier test would be editing Rafiq's spec to fit our assertion.
"""

from __future__ import annotations

from decimal import Decimal

from app.labs.rafiq.strategies.strategy_c_volatility_adjusted import (
    VolatilityAdjustedPolicy,
    round_trip_cost_pct,
    sized_for_liquidity,
    stop_distance_for,
)

POLICY = VolatilityAdjustedPolicy()
DEEP = Decimal(100_000)
THIN = Decimal(5_000)
#: Below the point where `max_notional_usd = 50` binds on either side.
UNCAPPED_EQUITY = Decimal(400)


def test_thinner_pool_gets_a_wider_stop() -> None:
    assert stop_distance_for(THIN) > stop_distance_for(DEEP)


def test_thinner_pool_gets_a_smaller_notional() -> None:
    deep = sized_for_liquidity(UNCAPPED_EQUITY, DEEP,
                               stop_pct=stop_distance_for(DEEP))
    thin = sized_for_liquidity(UNCAPPED_EQUITY, THIN,
                               stop_pct=stop_distance_for(THIN))
    assert thin < deep


def test_dollar_risk_is_equal_within_rounding() -> None:
    """The whole point: wider stop x smaller size = the same money at risk."""
    risks = []
    for liq in (THIN, DEEP, Decimal(20_000), Decimal(250_000)):
        stop = stop_distance_for(liq)
        size = sized_for_liquidity(UNCAPPED_EQUITY, liq, stop_pct=stop)
        risks.append(size * stop / 100)
    budget = UNCAPPED_EQUITY * Decimal("0.01")
    for risk in risks:
        assert abs(risk - budget) < Decimal("0.01"), risks


def test_the_notional_cap_truncates_risk_and_that_is_deliberate() -> None:
    """At $1,000 the deep pool's $83 position is clipped to Rafiq's $50, so
    its risk is BELOW budget. Documented, not smoothed away."""
    stop = stop_distance_for(DEEP)
    size = sized_for_liquidity(Decimal(1_000), DEEP, stop_pct=stop)
    assert size == Decimal(50)
    assert size * stop / 100 < Decimal(1_000) * Decimal("0.01")


def test_unknown_liquidity_returns_none_never_a_default() -> None:
    assert stop_distance_for(None) is None
    assert stop_distance_for(Decimal(0)) is None
    assert stop_distance_for(Decimal(-1)) is None
    assert round_trip_cost_pct(Decimal(50), None) is None
    # And an unpriceable pool sizes to zero, not to some fallback notional.
    assert sized_for_liquidity(Decimal(1_000), None, stop_pct=Decimal(12)) == 0


def test_stop_is_clamped_at_both_ends() -> None:
    """A pathological input never produces a useless stop."""
    assert stop_distance_for(Decimal(1)) == POLICY.max_stop_pct
    assert stop_distance_for(Decimal(10_000_000_000)) == POLICY.min_stop_pct


def test_sqrt_scaling_at_the_reference_depth() -> None:
    """At the reference liquidity the stop IS the base stop — square-root
    scaling with a ratio of 1 must be the identity, not near it."""
    assert stop_distance_for(POLICY.reference_liquidity_usd) == POLICY.base_stop_pct
    # 4x thinner -> sqrt(4) = 2x the stop, clamped by max_stop_pct at 24 < 25.
    assert stop_distance_for(POLICY.reference_liquidity_usd / 4) == Decimal(24)


def test_a_non_default_sensitivity_does_not_crash() -> None:
    """`Decimal ** float` raises TypeError. Rafiq's fallback path exists for
    exactly that, and it is only exercised when sensitivity is not 0.5."""
    linear = VolatilityAdjustedPolicy(sensitivity=Decimal(1))
    assert stop_distance_for(Decimal(50_000), policy=linear) == Decimal(24)


def test_thinner_pools_cost_more_to_round_trip() -> None:
    """The direction C's whole premise rests on, at a fixed order size."""
    thin = round_trip_cost_pct(Decimal(50), THIN)
    deep = round_trip_cost_pct(Decimal(50), DEEP)
    assert thin > deep > 0
