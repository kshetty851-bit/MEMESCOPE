"""Component tests, including every unavailability path.

`available=False` is the mechanism that keeps "we do not know" from rendering as
"it is fine", so each component's route to unavailability gets its own test
rather than being covered incidentally.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.services.scoring.components import COMPONENT_REGISTRY
from app.services.scoring.components.base import ComponentId, NotYetImplemented
from app.services.scoring.components.liquidity import LiquidityDepth
from app.services.scoring.components.momentum import Momentum
from app.services.scoring.components.survival import SurvivalAge
from app.services.scoring.components.trade_flow import TradeFlow
from app.services.scoring.components.valuation import ValuationStructure
from app.services.scoring.explain import AgentId, ReasonCode
from app.services.scoring.normalisers import HUNDRED, ZERO
from tests.unit.scoring_builders import features, observations

pytestmark = pytest.mark.unit


def test_every_registered_component_declares_an_agent() -> None:
    """Attribution drives the Observatory Log; an unowned readout cannot render."""
    for component_id, component in COMPONENT_REGISTRY.items():
        assert component.id is component_id
        assert isinstance(component.agent, AgentId)


def test_every_component_id_is_registered() -> None:
    assert set(COMPONENT_REGISTRY) == set(ComponentId)


@pytest.mark.parametrize("component_id", list(ComponentId))
def test_no_component_ever_leaves_the_zero_to_hundred_range(
    component_id: ComponentId,
) -> None:
    """Sweep the extremes: absent data, zeros, and implausibly large values."""
    extremes = [
        features(),
        features(liquidity_usd=None, market_cap=None, fully_diluted_valuation=None),
        features(liquidity_usd=ZERO, market_cap=ZERO, volume_24h=ZERO),
        features(
            liquidity_usd=Decimal(10**12),
            market_cap=Decimal(10**15),
            fully_diluted_valuation=Decimal(10**15),
            volume_24h=Decimal(10**12),
            volume_1h=Decimal(10**12),
            volume_5m=Decimal(10**12),
            buy_count_24h=10**9,
            sell_count_24h=0,
            age_minutes=Decimal(10**7),
        ),
        features(window=(), buy_count_24h=None, sell_count_24h=None),
    ]
    component = COMPONENT_REGISTRY[component_id]
    for feature_set in extremes:
        result = component.evaluate(feature_set)
        if result.available:
            assert result.score is not None
            assert ZERO <= result.score <= HUNDRED
        else:
            assert result.score is None


# --- liquidity_depth ----------------------------------------------------------


def test_liquidity_is_unavailable_without_a_figure() -> None:
    """The pump.fun bonding-curve gap: charged to coverage, not scored as zero."""
    result = LiquidityDepth().evaluate(features(liquidity_usd=None))
    assert result.available is False
    assert result.score is None


def test_deep_liquidity_outscores_thin() -> None:
    deep = LiquidityDepth().evaluate(
        features(liquidity_usd=Decimal(500000), market_cap=Decimal(1000000))
    )
    thin = LiquidityDepth().evaluate(
        features(liquidity_usd=Decimal(800), market_cap=Decimal(1000000))
    )
    assert deep.score is not None and thin.score is not None
    assert deep.score > thin.score
    assert ReasonCode.LIQUIDITY_DEEP in deep.reasons
    assert ReasonCode.LIQUIDITY_THIN in thin.reasons


def test_liquidity_survives_a_missing_market_cap() -> None:
    """Absolute depth is still real information; discarding it would be worse."""
    result = LiquidityDepth().evaluate(features(market_cap=None))
    assert result.available is True
    assert ReasonCode.DEPTH_RATIO_UNAVAILABLE in result.reasons


def test_shallow_pool_behind_a_large_valuation_scores_low() -> None:
    """The rug shape: the ratio term is what catches it."""
    result = LiquidityDepth().evaluate(
        features(liquidity_usd=Decimal(50), market_cap=Decimal(5000000))
    )
    assert result.score is not None
    assert result.score < Decimal(20)


# --- momentum -----------------------------------------------------------------


def test_momentum_is_unavailable_without_daily_volume() -> None:
    for volume in (None, ZERO):
        result = Momentum().evaluate(features(volume_24h=volume))
        assert result.available is False


def test_burst_activity_scores_above_flat_activity() -> None:
    bursting = Momentum().evaluate(
        features(volume_24h=Decimal(28800), volume_5m=Decimal(1000), volume_1h=Decimal(6000))
    )
    flat = Momentum().evaluate(
        features(volume_24h=Decimal(28800), volume_5m=Decimal(100), volume_1h=Decimal(1200))
    )
    assert bursting.score is not None and flat.score is not None
    assert bursting.score > flat.score
    assert ReasonCode.MOMENTUM_ACCELERATING in bursting.reasons


def test_momentum_drops_the_trend_term_without_enough_history() -> None:
    """Two points are not a trend; the omission is recorded, not hidden."""
    result = Momentum().evaluate(features(window=observations(count=2)))
    assert result.available is True
    assert ReasonCode.INSUFFICIENT_HISTORY in result.reasons
    assert result.raw["price_change_pct"] is None


def test_momentum_uses_the_trend_when_history_allows() -> None:
    rising = features(
        window=(
            *observations(count=1, price="0.002"),
            *observations(count=2, price="0.001", spacing_seconds=600),
        )
    )
    result = Momentum().evaluate(rising)
    assert ReasonCode.INSUFFICIENT_HISTORY not in result.reasons
    assert result.raw["price_change_pct"] is not None


def test_momentum_flags_coarse_sampling() -> None:
    """An old token's window spans days; the readout says so."""
    result = Momentum().evaluate(features(window=observations(count=4, spacing_seconds=7200)))
    assert ReasonCode.MOMENTUM_COARSE_SAMPLING in result.reasons


def test_momentum_ignores_a_zero_starting_price() -> None:
    window = (
        *observations(count=2, price="0.002"),
        *observations(count=1, price=0, spacing_seconds=900),
    )
    result = Momentum().evaluate(features(window=window))
    assert result.available is True
    assert ReasonCode.INSUFFICIENT_HISTORY in result.reasons


def test_decaying_momentum_is_named() -> None:
    result = Momentum().evaluate(
        features(volume_24h=Decimal(100000), volume_5m=ZERO, volume_1h=ZERO)
    )
    assert ReasonCode.MOMENTUM_DECAYING in result.reasons


# --- trade_flow ---------------------------------------------------------------


def test_trade_flow_is_unavailable_without_counts() -> None:
    result = TradeFlow().evaluate(features(buy_count_24h=None, sell_count_24h=None))
    assert result.available is False


def test_trade_flow_is_unavailable_with_zero_trades() -> None:
    result = TradeFlow().evaluate(features(buy_count_24h=0, sell_count_24h=0))
    assert result.available is False


def test_a_perfect_ratio_on_three_trades_does_not_read_as_conviction() -> None:
    """The participation factor exists for exactly this case."""
    thin = TradeFlow().evaluate(features(buy_count_24h=3, sell_count_24h=0))
    thick = TradeFlow().evaluate(features(buy_count_24h=1500, sell_count_24h=500))

    assert thin.score is not None and thick.score is not None
    assert thin.score < thick.score
    assert ReasonCode.PARTICIPATION_THIN in thin.reasons


def test_sell_dominance_is_reported() -> None:
    result = TradeFlow().evaluate(features(buy_count_24h=100, sell_count_24h=900))
    assert ReasonCode.SELL_PRESSURE_DOMINANT in result.reasons


def test_buy_dominance_is_reported() -> None:
    result = TradeFlow().evaluate(features(buy_count_24h=900, sell_count_24h=100))
    assert ReasonCode.BUY_PRESSURE_DOMINANT in result.reasons


def test_trade_flow_treats_a_missing_side_as_zero() -> None:
    result = TradeFlow().evaluate(features(buy_count_24h=50, sell_count_24h=None))
    assert result.available is True
    assert result.raw["sell_count_24h"] == ZERO


# --- valuation_structure ------------------------------------------------------


def test_valuation_is_unavailable_without_any_figure() -> None:
    result = ValuationStructure().evaluate(
        features(market_cap=None, fully_diluted_valuation=None)
    )
    assert result.available is False


def test_supply_overhang_scores_below_a_coherent_valuation() -> None:
    overhang = ValuationStructure().evaluate(
        features(market_cap=Decimal(100000), fully_diluted_valuation=Decimal(1000000))
    )
    coherent = ValuationStructure().evaluate(
        features(market_cap=Decimal(950000), fully_diluted_valuation=Decimal(1000000))
    )
    assert overhang.score is not None and coherent.score is not None
    assert overhang.score < coherent.score
    assert ReasonCode.SUPPLY_OVERHANG in overhang.reasons
    assert ReasonCode.VALUATION_COHERENT in coherent.reasons


def test_dust_valuations_are_implausible() -> None:
    result = ValuationStructure().evaluate(
        features(market_cap=Decimal(50), fully_diluted_valuation=Decimal(50))
    )
    assert ReasonCode.VALUATION_IMPLAUSIBLE in result.reasons


def test_valuation_falls_back_to_the_sanity_band_alone() -> None:
    result = ValuationStructure().evaluate(features(market_cap=None))
    assert result.available is True
    assert result.raw["circulating_share"] is None


def test_valuation_uses_market_cap_when_fdv_is_missing() -> None:
    result = ValuationStructure().evaluate(
        features(fully_diluted_valuation=None, market_cap=Decimal(500000))
    )
    assert result.available is True
    assert result.score is not None


# --- survival_age -------------------------------------------------------------


def test_survival_is_always_available() -> None:
    """Age is always known, even when everything else is missing."""
    result = SurvivalAge().evaluate(
        features(liquidity_usd=None, market_cap=None, volume_24h=None, window=())
    )
    assert result.available is True


def test_survival_peaks_in_the_middle() -> None:
    """Non-monotone by design: both ends are uninteresting, for opposite reasons."""
    newborn = SurvivalAge().evaluate(features(age_minutes=Decimal(2)))
    established = SurvivalAge().evaluate(features(age_minutes=Decimal(600)))
    ancient = SurvivalAge().evaluate(features(age_minutes=Decimal(20000)))

    assert newborn.score is not None
    assert established.score is not None
    assert ancient.score is not None
    assert established.score > newborn.score
    assert established.score > ancient.score


@pytest.mark.parametrize(
    ("age", "expected"),
    [
        (2, ReasonCode.TOKEN_TOO_NEW),
        (60, ReasonCode.TOKEN_TOO_NEW),
        (600, ReasonCode.SURVIVAL_ESTABLISHED),
        (20000, ReasonCode.TOKEN_STALE),
    ],
)
def test_survival_reasons_track_the_lifecycle(age: int, expected: ReasonCode) -> None:
    result = SurvivalAge().evaluate(features(age_minutes=Decimal(age)))
    assert expected in result.reasons


# --- placeholders -------------------------------------------------------------


@pytest.mark.parametrize(
    "component_id",
    [
        ComponentId.CONTRACT_SAFETY,
        ComponentId.HOLDER_DISTRIBUTION,
        ComponentId.SMART_MONEY,
        ComponentId.NARRATIVE,
    ],
)
def test_undelivered_components_report_themselves_as_missing(
    component_id: ComponentId,
) -> None:
    """Their declared weight is what caps evidence at 0.65 in v1."""
    result = COMPONENT_REGISTRY[component_id].evaluate(features())
    assert result.available is False
    assert result.reasons == (ReasonCode.COMPONENT_NOT_YET_IMPLEMENTED,)


def test_placeholder_carries_its_agent() -> None:
    placeholder = NotYetImplemented(ComponentId.NARRATIVE, AgentId.ECHO)
    assert placeholder.evaluate(features()).agent is AgentId.ECHO
