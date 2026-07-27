"""Risk gate tests.

The priority test in this file is `test_an_acute_drawdown_cannot_be_outvoted`:
it is the executable form of the lesson recorded at
`frontend/src/lib/intelligence.ts:124`, where a linear risk sum let a textbook
rug score "moderate". If that test ever passes trivially, the gate has stopped
being a gate.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest

from app.services.scoring.components.market_risk import MarketRisk
from app.services.scoring.explain import ReasonCode
from app.services.scoring.features import Observation
from app.services.scoring.models.v1 import MODEL_V1
from app.services.scoring.normalisers import ONE, ZERO
from app.services.scoring import evaluate
from tests.unit.scoring_builders import NOW, declining_window, features, observations

pytestmark = pytest.mark.unit

GATE = MarketRisk()


# --- Drawdown -----------------------------------------------------------------


def test_an_acute_drawdown_vetoes() -> None:
    """$80k to $12k in twenty minutes is a rug in progress, not a dip."""
    assessment = GATE.evaluate(
        features(
            liquidity_usd=Decimal(12000),
            window=declining_window(peak=80000, current=12000, seconds_ago=1200),
        )
    )
    assert assessment.vetoed is True
    assert ReasonCode.LIQUIDITY_DRAWDOWN_ACUTE in assessment.reasons


def test_an_acute_drawdown_cannot_be_outvoted(
) -> None:
    """The whole reason risk multiplies instead of adding.

    Every opportunity signal is set to its strongest: deep-looking liquidity
    history, explosive volume, overwhelming buy pressure, a mature token. The
    collapsing pool must still cap the score.
    """
    collapsing = features(
        liquidity_usd=Decimal(12000),
        market_cap=Decimal(5000000),
        fully_diluted_valuation=Decimal(5000000),
        volume_24h=Decimal(288000),
        volume_5m=Decimal(50000),
        volume_1h=Decimal(200000),
        buy_count_24h=50000,
        sell_count_24h=10,
        age_minutes=Decimal(600),
        window=declining_window(peak=80000, current=12000, seconds_ago=1200),
    )
    result = evaluate(collapsing, MODEL_V1)

    assert result.has_veto is True
    assert result.score <= MODEL_V1.veto_ceiling
    assert str(result.grade) == "critical"
    assert result.is_elite is False


def test_the_same_decline_over_days_is_decay_not_a_rug() -> None:
    """Rev 2's split. Conflating these would veto every slowly-dying old token."""
    gradual = GATE.evaluate(
        features(
            liquidity_usd=Decimal(12000),
            risk_window_seconds=3600,
            window=(
                Observation(NOW, Decimal("0.001"), Decimal(12000)),
                Observation(NOW - timedelta(days=3), Decimal("0.004"), Decimal(80000)),
            ),
        )
    )
    assert gradual.vetoed is False
    assert ReasonCode.LIQUIDITY_DRAWDOWN_GRADUAL in gradual.reasons
    assert gradual.penalty > ZERO


def test_a_moderate_acute_drawdown_penalises_without_vetoing() -> None:
    assessment = GATE.evaluate(
        features(
            liquidity_usd=Decimal(50000),
            window=declining_window(peak=90000, current=50000, seconds_ago=600),
        )
    )
    assert assessment.vetoed is False
    assert assessment.penalty >= Decimal("0.35")


def test_rising_liquidity_is_not_a_drawdown() -> None:
    assessment = GATE.evaluate(
        features(
            liquidity_usd=Decimal(90000),
            window=declining_window(peak=50000, current=90000, seconds_ago=600),
        )
    )
    assert assessment.raw["acute_drawdown"] is None
    assert assessment.vetoed is False


def test_drawdown_needs_a_current_liquidity_figure() -> None:
    assessment = GATE.evaluate(features(liquidity_usd=None))
    assert assessment.raw["acute_drawdown"] is None
    assert assessment.raw["gradual_drawdown"] is None


def test_drawdown_needs_a_window() -> None:
    assessment = GATE.evaluate(features(window=()))
    assert assessment.raw["acute_drawdown"] is None


# --- Other signals ------------------------------------------------------------


def test_an_inactive_pool_vetoes() -> None:
    assessment = GATE.evaluate(features(trading_status="inactive"))
    assert assessment.vetoed is True
    assert ReasonCode.POOL_INACTIVE in assessment.reasons


def test_a_negligible_depth_ratio_is_penalised() -> None:
    assessment = GATE.evaluate(
        features(liquidity_usd=Decimal(50), market_cap=Decimal(5000000), window=())
    )
    assert ReasonCode.DEPTH_RATIO_CRITICAL in assessment.reasons
    assert assessment.penalty >= Decimal("0.30")


def test_sell_dominance_scales_rather_than_stepping() -> None:
    """0.66 is a lean; 0.95 is an exit queue. They must not weigh the same."""
    lean = GATE.evaluate(features(buy_count_24h=340, sell_count_24h=660, window=()))
    queue = GATE.evaluate(features(buy_count_24h=50, sell_count_24h=950, window=()))
    assert queue.penalty > lean.penalty


def test_balanced_flow_is_not_penalised_for_selling() -> None:
    assessment = GATE.evaluate(features(buy_count_24h=500, sell_count_24h=500, window=()))
    assert ReasonCode.SELL_PRESSURE_DOMINANT not in assessment.reasons


def test_sell_share_needs_trades() -> None:
    assessment = GATE.evaluate(
        features(buy_count_24h=None, sell_count_24h=None, window=())
    )
    assert assessment.raw["sell_share"] is None

    empty = GATE.evaluate(features(buy_count_24h=0, sell_count_24h=0, window=()))
    assert empty.raw["sell_share"] is None


def test_unresolved_metadata_is_penalised() -> None:
    assessment = GATE.evaluate(features(metadata_resolved=False, window=()))
    assert ReasonCode.METADATA_UNRESOLVED in assessment.reasons


def test_liquidity_below_the_floor_is_penalised() -> None:
    assessment = GATE.evaluate(features(liquidity_usd=Decimal(100), window=()))
    assert ReasonCode.LIQUIDITY_THIN in assessment.reasons


def test_a_healthy_token_earns_no_penalty() -> None:
    assessment = GATE.evaluate(features(window=observations(count=6)))
    assert assessment.penalty == ZERO
    assert assessment.vetoed is False
    assert assessment.reasons == ()


# --- Bounds -------------------------------------------------------------------


def test_the_penalty_never_exceeds_one() -> None:
    """Every signal firing at once must saturate, not overflow."""
    assessment = GATE.evaluate(
        features(
            liquidity_usd=Decimal(10),
            market_cap=Decimal(10000000),
            metadata_resolved=False,
            trading_status="inactive",
            buy_count_24h=1,
            sell_count_24h=999,
            window=declining_window(peak=100000, current=10, seconds_ago=300),
        )
    )
    assert assessment.penalty == ONE
    assert assessment.as_score == Decimal(100)


def test_the_penalty_is_never_negative() -> None:
    assessment = GATE.evaluate(features())
    assert assessment.penalty >= ZERO


def test_absent_data_is_not_treated_as_safety() -> None:
    """A token we know nothing about is not a safe token."""
    unknown = GATE.evaluate(
        features(
            liquidity_usd=None,
            market_cap=None,
            metadata_resolved=False,
            buy_count_24h=None,
            sell_count_24h=None,
            window=(),
        )
    )
    assert unknown.penalty > ZERO
