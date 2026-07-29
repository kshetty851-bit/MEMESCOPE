"""Exit Watch engine.

Fixture-free: the detector is pure and takes `now` explicitly.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.exit_signals import detector, smart_money
from app.exit_signals.models import ExitSeverity, ExitSignal
from app.radar.models import Observation, RadarSeries

pytestmark = pytest.mark.unit

NOW = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)


def series(
    *,
    count: int = 48,
    price: Decimal = Decimal("0.001"),
    price_step: Decimal = Decimal(0),
    liquidity: Decimal | None = Decimal(30_000),
    liquidity_step: Decimal = Decimal(0),
    volume: Decimal | None = Decimal(20_000),
    volume_step: Decimal = Decimal(0),
    buys: int | None = 100,
    sells: int | None = 100,
) -> RadarSeries:
    return RadarSeries(
        mint_address="MintExit",
        observations=[
            Observation(
                captured_at=NOW - timedelta(minutes=(count - i) * 30),
                price_usd=price + price_step * Decimal(i),
                market_cap=Decimal(200_000),
                liquidity_usd=None if liquidity is None else liquidity + liquidity_step * i,
                volume_24h=None if volume is None else volume + volume_step * i,
                volume_1h=Decimal(800),
                buy_count_24h=buys,
                sell_count_24h=sells,
            )
            for i in range(count)
        ],
    )


class TestNothingWrong:
    def test_a_stable_token_is_clear(self) -> None:
        assessment = detector.assess(series(), now=NOW)

        assert assessment.severity is ExitSeverity.CLEAR
        assert assessment.triggered == ()

    def test_a_short_series_concludes_nothing_and_says_so(self) -> None:
        # Reported CLEAR but with zero coverage. "Nothing is wrong" and "nobody
        # has watched this long enough to tell" must stay distinguishable.
        assessment = detector.assess(series(count=6), now=NOW)

        assert assessment.severity is ExitSeverity.CLEAR
        assert assessment.coverage == Decimal(0)
        assert all(not signal.available for signal in assessment.signals)


class TestIndividualSignals:
    def test_collapsing_volume_fires(self) -> None:
        assessment = detector.assess(
            series(volume=Decimal(60_000), volume_step=Decimal(-1_100)), now=NOW
        )

        assert assessment.has(ExitSignal.VOLUME_COLLAPSING)

    def test_liquidity_being_withdrawn_fires(self) -> None:
        assessment = detector.assess(
            series(liquidity=Decimal(60_000), liquidity_step=Decimal(-900)), now=NOW
        )

        assert assessment.has(ExitSignal.LIQUIDITY_LEAVING)

    def test_price_far_below_its_high_fires(self) -> None:
        falling = series(price=Decimal("0.01"), price_step=Decimal("-0.00018"))

        assert detector.assess(falling, now=NOW).has(ExitSignal.TECHNICAL_BREAKDOWN)

    def test_sell_pressure_fires(self) -> None:
        assessment = detector.assess(series(buys=20, sells=80), now=NOW)

        assert assessment.has(ExitSignal.SELL_PRESSURE_BUILDING)

    def test_score_falling_from_its_peak_fires(self) -> None:
        assessment = detector.assess(
            series(), now=NOW, current_score=Decimal(55), peak_score=Decimal(80)
        )

        assert assessment.has(ExitSignal.MOMENTUM_ROLLING_OVER)

    def test_confidence_falling_fires(self) -> None:
        assessment = detector.assess(
            series(),
            now=NOW,
            current_confidence=Decimal(40),
            peak_confidence=Decimal(85),
        )

        assert assessment.has(ExitSignal.CONFIDENCE_DROPPING)

    def test_trading_below_detection_price_fires(self) -> None:
        # The first thing a user checks. Leaving it implicit would look like
        # the platform avoiding the subject.
        assessment = detector.assess(
            series(price=Decimal("0.0004")), now=NOW, first_price=Decimal("0.001")
        )

        assert assessment.has(ExitSignal.PRICE_BELOW_DETECTION)


class TestSeverityNeedsAgreement:
    def test_one_signal_is_watch_not_elevated(self) -> None:
        # A single deteriorating metric is noise. Escalating on it would train
        # users to ignore the warning entirely.
        assessment = detector.assess(series(buys=20, sells=80), now=NOW)

        assert assessment.severity is ExitSeverity.WATCH

    def test_several_independent_signals_escalate(self) -> None:
        assessment = detector.assess(
            series(
                price=Decimal("0.01"),
                price_step=Decimal("-0.00018"),
                volume=Decimal(60_000),
                volume_step=Decimal(-1_100),
                liquidity=Decimal(60_000),
                liquidity_step=Decimal(-900),
                buys=15,
                sells=85,
            ),
            now=NOW,
        )

        assert assessment.severity is ExitSeverity.ELEVATED
        assert len(assessment.triggered) >= detector.ELEVATED_SIGNALS

    def test_triggered_signals_are_ordered_by_magnitude(self) -> None:
        assessment = detector.assess(
            series(
                volume=Decimal(60_000),
                volume_step=Decimal(-1_200),
                liquidity=Decimal(60_000),
                liquidity_step=Decimal(-400),
            ),
            now=NOW,
        )
        magnitudes = [s.magnitude or Decimal(0) for s in assessment.triggered]

        assert magnitudes == sorted(magnitudes, reverse=True)


class TestUnavailableIsNotClear:
    def test_missing_liquidity_is_unavailable_not_a_pass(self) -> None:
        # A signal that could not be checked must never read as one that was
        # checked and passed.
        assessment = detector.assess(series(liquidity=None), now=NOW)
        liquidity = next(s for s in assessment.signals if s.id is ExitSignal.LIQUIDITY_LEAVING)

        assert liquidity.available is False
        assert liquidity.triggered is False

    def test_smart_money_signals_are_always_unavailable(self) -> None:
        assessment = detector.assess(series(), now=NOW)

        for signal_id in smart_money.DECLARED_SIGNALS:
            signal = next(s for s in assessment.signals if s.id is signal_id)
            assert signal.available is False

    def test_coverage_is_capped_even_with_every_input_supplied(self) -> None:
        # With the full Radar context provided, seven of nine signals can be
        # checked. The remaining two have no data source, so coverage can never
        # reach 100 — the same honesty mechanism the Radar and scoring engine
        # use, and the reason Exit Watch never claims a clean bill of health.
        assessment = detector.assess(
            series(),
            now=NOW,
            current_score=Decimal(70),
            peak_score=Decimal(72),
            current_confidence=Decimal(80),
            peak_confidence=Decimal(82),
            first_price=Decimal("0.001"),
        )

        assert assessment.coverage == Decimal(7) / Decimal(9) * Decimal(100)
        assert assessment.coverage < Decimal(100)

    def test_coverage_falls_when_the_radar_context_is_absent(self) -> None:
        # Assessing a token the Radar has never scored is a thinner reading,
        # and the figure says so rather than implying the same certainty.
        without = detector.assess(series(), now=NOW)

        assert without.coverage < Decimal(50)


class TestSmartMoneyIsHonest:
    def test_token_intelligence_is_null_not_zero(self) -> None:
        # Zero would read as "no smart wallets found". The truth is "we cannot
        # see wallets at all", which is a different claim.
        block = smart_money.token_intelligence()

        assert block["smart_wallet_count"] is None
        assert block["net_accumulation"] is None
        assert isinstance(block["unavailable_reason"], str)
        assert "not collected" in block["unavailable_reason"]


class TestDeterminism:
    def test_the_same_series_always_assesses_identically(self) -> None:
        first = detector.assess(series(volume_step=Decimal(-300)), now=NOW)
        second = detector.assess(series(volume_step=Decimal(-300)), now=NOW)

        assert first.severity is second.severity
        assert [s.triggered for s in first.signals] == [s.triggered for s in second.signals]
