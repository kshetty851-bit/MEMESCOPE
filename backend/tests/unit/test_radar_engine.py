"""Opportunity Radar engine.

Fixture-free by construction: the engine performs no I/O and takes `now` as an
argument, so every case here is a literal series in and a verdict out.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.radar import achievements, detector, scorer
from app.radar.models import (
    Observation,
    RadarCategory,
    RadarDimension,
    RadarReason,
    RadarSeries,
)

pytestmark = pytest.mark.unit

NOW = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)


def series(
    *,
    count: int = 48,
    price_start: Decimal = Decimal("0.001"),
    price_step: Decimal = Decimal(0),
    liquidity: Decimal | None = Decimal(20_000),
    liquidity_step: Decimal = Decimal(0),
    volume: Decimal | None = Decimal(15_000),
    volume_step: Decimal = Decimal(0),
    market_cap: Decimal | None = Decimal(200_000),
    buys: int | None = 100,
    sells: int | None = 100,
    mint: str = "MintTest",
) -> RadarSeries:
    observations = [
        Observation(
            captured_at=NOW - timedelta(minutes=(count - i) * 30),
            price_usd=price_start + price_step * Decimal(i),
            market_cap=market_cap,
            liquidity_usd=None
            if liquidity is None
            else liquidity + liquidity_step * Decimal(i),
            volume_24h=None if volume is None else volume + volume_step * Decimal(i),
            volume_1h=Decimal(500),
            buy_count_24h=buys,
            sell_count_24h=sells,
        )
        for i in range(count)
    ]
    return RadarSeries(mint_address=mint, observations=observations)


class TestCoverage:
    def test_community_is_declared_and_always_unavailable(self) -> None:
        # The whole point of declaring it: the gap is visible in coverage
        # rather than silently absent from the weight table.
        result = scorer.evaluate(series(), now=NOW)

        assert result is not None
        community = result.dimension(RadarDimension.COMMUNITY)
        assert community is not None
        assert community.available is False
        assert RadarReason.COMMUNITY_DATA_UNAVAILABLE in community.reasons

    def test_coverage_is_capped_at_declared_available_weight(self) -> None:
        result = scorer.evaluate(series(), now=NOW)

        assert result is not None
        # 0.85 of 1.00 declared weight can be applied; community is the gap.
        assert result.coverage == Decimal(85)

    def test_confidence_is_below_coverage_when_history_is_short(self) -> None:
        shallow = scorer.evaluate(series(count=12), now=NOW)
        deep = scorer.evaluate(series(count=48), now=NOW)

        assert shallow is not None and deep is not None
        assert shallow.confidence < deep.confidence
        assert deep.confidence == deep.coverage

    def test_no_result_when_almost_nothing_applies(self) -> None:
        # No liquidity and no volume strips every dimension that needs them.
        thin = series(count=4, liquidity=None, volume=None)

        assert scorer.evaluate(thin, now=NOW) is None


class TestDeterminism:
    def test_same_input_gives_bit_identical_output(self) -> None:
        # The property that makes backfill exact and the track record auditable.
        first = scorer.evaluate(series(price_step=Decimal("0.00001")), now=NOW)
        second = scorer.evaluate(series(price_step=Decimal("0.00001")), now=NOW)

        assert first is not None and second is not None
        assert first.score == second.score
        assert first.coverage == second.coverage
        assert [d.score for d in first.dimensions] == [d.score for d in second.dimensions]

    def test_score_stays_within_bounds_on_extreme_input(self) -> None:
        extreme = series(
            price_start=Decimal("0.000001"),
            price_step=Decimal("0.01"),
            liquidity=Decimal(1),
            liquidity_step=Decimal(100_000),
            volume=Decimal(1),
            volume_step=Decimal(1_000_000),
        )
        result = scorer.evaluate(extreme, now=NOW)

        assert result is not None
        assert Decimal(0) <= result.score <= Decimal(100)


class TestMomentum:
    def test_growing_liquidity_and_volume_score_above_flat(self) -> None:
        flat = scorer.evaluate(series(), now=NOW)
        growing = scorer.evaluate(
            series(liquidity_step=Decimal(400), volume_step=Decimal(500)), now=NOW
        )

        assert flat is not None and growing is not None
        flat_m = flat.dimension(RadarDimension.MOMENTUM)
        grow_m = growing.dimension(RadarDimension.MOMENTUM)
        assert flat_m is not None and grow_m is not None
        assert grow_m.score is not None and flat_m.score is not None
        assert grow_m.score > flat_m.score

    def test_liquidity_growth_from_zero_does_not_produce_infinity(self) -> None:
        # The easiest way to game a growth model: start at zero. Guarded
        # explicitly rather than left to division semantics.
        result = scorer.evaluate(
            series(liquidity=Decimal(0), liquidity_step=Decimal(500)), now=NOW
        )

        assert result is not None
        assert Decimal(0) <= result.score <= Decimal(100)

    def test_buy_pressure_is_reported(self) -> None:
        result = scorer.evaluate(series(buys=200, sells=40), now=NOW)

        assert result is not None
        assert RadarReason.BUY_PRESSURE_DOMINANT in result.reasons


class TestTechnical:
    def test_insufficient_history_is_unavailable_not_zero(self) -> None:
        # "We cannot read structure yet" and "the structure is bad" are
        # different claims and must not collapse into the same score.
        result = scorer.evaluate(series(count=8), now=NOW)

        assert result is not None
        tech = result.dimension(RadarDimension.TECHNICAL)
        assert tech is not None
        assert tech.available is False
        assert RadarReason.INSUFFICIENT_HISTORY in tech.reasons

    def test_rising_series_breaks_resistance(self) -> None:
        result = scorer.evaluate(series(price_step=Decimal("0.00005")), now=NOW)

        assert result is not None
        assert RadarReason.RESISTANCE_BROKEN in result.reasons

    def test_falling_series_reports_breakdown_not_breakout(self) -> None:
        result = scorer.evaluate(
            series(price_start=Decimal("0.01"), price_step=Decimal("-0.0001")), now=NOW
        )

        assert result is not None
        assert RadarReason.RESISTANCE_BROKEN not in result.reasons


class TestRiskGate:
    def test_critically_thin_liquidity_is_excluded_however_good_the_rest(self) -> None:
        # The worst thing the Radar could do is surface a project whose pool
        # cannot support an exit.
        result = scorer.evaluate(
            series(
                liquidity=Decimal(200),
                price_step=Decimal("0.0001"),
                volume_step=Decimal(900),
            ),
            now=NOW,
        )

        assert result is not None
        assert detector.qualifies(result) is False
        assert detector.classify(result) is None

    def test_unknown_risk_is_not_treated_as_safe(self) -> None:
        # No liquidity data at all: risk is unavailable, and an unknown danger
        # must not read as an absent one.
        result = scorer.evaluate(series(liquidity=None), now=NOW)

        if result is not None:
            assert detector.qualifies(result) is False


class TestCategories:
    def test_a_small_project_with_signals_beats_a_large_one_without(self) -> None:
        # The founding rule of the Radar, stated as the property that actually
        # matters: there is no size floor, and quality wins.
        small_and_improving = scorer.evaluate(
            series(
                market_cap=Decimal(60_000),
                liquidity=Decimal(12_000),
                liquidity_step=Decimal(400),
                volume_step=Decimal(500),
                price_step=Decimal("0.00002"),
            ),
            now=NOW,
        )
        large_and_flat = scorer.evaluate(
            series(market_cap=Decimal(5_000_000), liquidity=Decimal(12_000)), now=NOW
        )

        assert small_and_improving is not None and large_and_flat is not None
        assert small_and_improving.score > large_and_flat.score

    def test_size_alone_is_not_a_qualification_threshold(self) -> None:
        # Market cap appears in the model only through liquidity-to-valuation —
        # which penalises an *unbacked* valuation rather than rewarding a large
        # one. No gate anywhere reads market cap directly, so a token is never
        # excluded for being small.
        tiny = scorer.evaluate(
            series(
                market_cap=Decimal(15_000),
                liquidity=Decimal(9_000),
                liquidity_step=Decimal(300),
                volume_step=Decimal(400),
                price_step=Decimal("0.00002"),
            ),
            now=NOW,
        )

        assert tiny is not None
        assert detector.qualifies(tiny) is True

    def test_elite_needs_several_dimensions_to_agree(self) -> None:
        # One very strong axis must not manufacture an Elite on its own.
        result = scorer.evaluate(series(), now=NOW)
        assert result is not None
        assert detector.classify(result) is not RadarCategory.ELITE

    def test_strong_community_is_reported_unreachable(self) -> None:
        # Not merely absent — a category nothing has qualified for and one that
        # cannot be qualified for are different facts.
        assert detector.category_is_reachable(RadarCategory.STRONG_COMMUNITY) is False
        assert detector.category_is_reachable(RadarCategory.ELITE) is True


class TestAchievements:
    def test_multiple_is_measured_from_detection_not_launch(self) -> None:
        assert achievements.multiple(Decimal(2), Decimal(10)) == Decimal(5)

    def test_zero_first_price_yields_none_not_infinity(self) -> None:
        # One infinite return would corrupt every aggregate on the track record.
        assert achievements.multiple(Decimal(0), Decimal(10)) is None

    def test_tiers_are_driven_by_peak_not_current(self) -> None:
        # A token that touched 10x and fell back has still earned 10x.
        earned = achievements.newly_earned(peak_multiple=Decimal(12), already_earned=[])

        assert [tier.label for tier in earned] == ["2x", "5x", "10x"]

    def test_already_recorded_tiers_are_not_re_awarded(self) -> None:
        earned = achievements.newly_earned(
            peak_multiple=Decimal(12), already_earned=[Decimal(2), Decimal(5)]
        )

        assert [tier.label for tier in earned] == ["10x"]

    def test_performance_measures_days_from_detection(self) -> None:
        result = achievements.performance(
            first_price=Decimal(1),
            current_price=Decimal(3),
            peak_price=Decimal(7),
            detected_at=NOW - timedelta(days=5),
            now=NOW,
        )

        assert result.current_multiple == Decimal(3)
        assert result.peak_multiple == Decimal(7)
        assert result.days_since_detection == Decimal(5)
