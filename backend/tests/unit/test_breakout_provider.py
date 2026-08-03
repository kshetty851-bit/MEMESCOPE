"""The breakout provider, against literal windows.

Pure, so every case is a list of observations and an assertion. The ones worth
having are the refusals: a provider that answers when it should not is how an
estimate reaches a board that promises observations.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.opportunities.models import (
    MarketObservation,
    ObservationWindow,
    SignalSeverity,
    SignalType,
)
from app.opportunities.providers.breakout import (
    NO_PRICE,
    NO_VOLUME,
    NO_WINDOW,
    REASON_APPROACHING_RANGE,
    REASON_BUY_PRESSURE,
    REASON_PRICE_BROKE_RANGE,
    REASON_THIN_WINDOW,
    REASON_VOLUME_EXPANDED,
    BreakoutProvider,
)

pytestmark = pytest.mark.unit

NOW = datetime(2026, 8, 3, 12, 0, tzinfo=UTC)


def _observation(
    index: int,
    *,
    price: str | None = "1.0",
    volume: str | None = "100",
    buys: int | None = None,
    sells: int | None = None,
) -> MarketObservation:
    return MarketObservation(
        captured_at=NOW - timedelta(minutes=(20 - index) * 5),
        price_usd=None if price is None else Decimal(price),
        volume_1h=None if volume is None else Decimal(volume),
        buy_count_24h=buys,
        sell_count_24h=sells,
        dex_name="pumpswap",
    )


def _window(*observations: MarketObservation) -> ObservationWindow:
    return ObservationWindow(mint_address="mint", observations=observations)


def _flat(
    count: int = 11, *, price: str = "1.0", volume: str = "100"
) -> list[MarketObservation]:
    return [_observation(index, price=price, volume=volume) for index in range(count)]


def _provider() -> BreakoutProvider:
    return BreakoutProvider(
        min_observations=8,
        price_margin=Decimal("0.15"),
        volume_multiple=Decimal(2),
        proximity=Decimal("0.90"),
    )


class TestRefusals:
    def test_a_window_too_short_to_hold_a_range_is_unavailable(self) -> None:
        """Two points are not a range.

        Unavailable rather than silent: a provider that returns nothing is
        indistinguishable from one that looked and saw nothing, and only the
        second is true here.
        """
        result = _provider().evaluate(_window(*_flat(4)), now=NOW)

        assert not result.available
        assert result.unavailable_reason == NO_WINDOW

    def test_a_window_with_no_price_is_unavailable(self) -> None:
        """11.5% of pump.fun observations carry no price. No range exists for
        them, and inferring one from market cap is the §14a mistake."""
        observations = [*_flat(), _observation(11, price=None)]

        result = _provider().evaluate(_window(*observations), now=NOW)

        assert result.unavailable_reason == NO_PRICE

    def test_a_window_with_no_volume_is_unavailable(self) -> None:
        observations = [*_flat(), _observation(11, price="2.0", volume=None)]

        result = _provider().evaluate(_window(*observations), now=NOW)

        assert result.unavailable_reason == NO_VOLUME

    def test_a_zero_baseline_is_unavailable_not_infinite(self) -> None:
        """Dividing by a baseline of zero would make every reading a surge."""
        observations = [*_flat(volume="0"), _observation(11, price="2.0", volume="500")]

        result = _provider().evaluate(_window(*observations), now=NOW)

        assert result.unavailable_reason == NO_VOLUME


class TestNoSignal:
    def test_a_flat_series_emits_nothing(self) -> None:
        result = _provider().evaluate(_window(*_flat(12)), now=NOW)

        assert result.available
        assert result.candidates == ()

    def test_a_price_break_without_volume_is_not_a_breakout(self) -> None:
        """A price drifting above its range on no extra trading is the same
        thinness that set the range, re-read."""
        observations = [*_flat(), _observation(11, price="2.0", volume="100")]

        result = _provider().evaluate(_window(*observations), now=NOW)

        assert result.candidates == ()

    def test_volume_alone_well_below_the_range_emits_nothing(self) -> None:
        """Expanded volume on a collapsed price is not approaching anything."""
        observations = [*_flat(), _observation(11, price="0.5", volume="500")]

        result = _provider().evaluate(_window(*observations), now=NOW)

        assert result.candidates == ()


class TestBreakout:
    def test_price_above_the_range_on_expanded_volume_is_a_breakout(self) -> None:
        observations = [*_flat(), _observation(11, price="1.5", volume="400")]

        candidate = _provider().evaluate(_window(*observations), now=NOW).candidates[0]

        assert candidate.signal_type is SignalType.BREAKOUT
        assert candidate.severity is SignalSeverity.MAJOR
        assert REASON_PRICE_BROKE_RANGE in candidate.reason_codes
        assert REASON_VOLUME_EXPANDED in candidate.reason_codes
        assert candidate.observed_at == observations[-1].captured_at

    def test_the_range_excludes_the_observation_under_test(self) -> None:
        """A baseline the current reading helped set cannot report that reading
        as unusual — the reason the median is trailing, not inclusive."""
        observations = [*_flat(), _observation(11, price="1.16", volume="400")]

        candidate = _provider().evaluate(_window(*observations), now=NOW).candidates[0]

        assert candidate.signal_type is SignalType.BREAKOUT

    def test_one_volume_spike_does_not_move_the_baseline(self) -> None:
        """The median's whole job. With a mean, this single 10,000 observation
        would lift the baseline above the breakout reading and hide it.
        """
        history = _flat(10)
        history[3] = _observation(3, price="1.0", volume="10000")
        observations = [*history, _observation(11, price="1.5", volume="400")]

        candidate = _provider().evaluate(_window(*observations), now=NOW).candidates[0]

        assert candidate.signal_type is SignalType.BREAKOUT

    def test_buy_pressure_is_recorded_when_both_counts_exist(self) -> None:
        observations = [
            *_flat(),
            _observation(11, price="1.5", volume="400", buys=90, sells=30),
        ]

        candidate = _provider().evaluate(_window(*observations), now=NOW).candidates[0]

        assert REASON_BUY_PRESSURE in candidate.reason_codes

    def test_a_thin_window_still_answers_but_says_so(self) -> None:
        """Charged to the explanation, not hidden — and not a refusal either,
        which would lose a real transition."""
        observations = [*_flat(8), _observation(11, price="1.5", volume="400")]

        candidate = _provider().evaluate(_window(*observations), now=NOW).candidates[0]

        assert REASON_THIN_WINDOW in candidate.reason_codes


class TestPreBreakout:
    def test_near_the_range_on_expanded_volume_is_pre_breakout(self) -> None:
        observations = [*_flat(), _observation(11, price="0.95", volume="400")]

        candidate = _provider().evaluate(_window(*observations), now=NOW).candidates[0]

        assert candidate.signal_type is SignalType.PRE_BREAKOUT
        assert candidate.severity is SignalSeverity.NOTABLE
        assert REASON_APPROACHING_RANGE in candidate.reason_codes

    def test_the_two_claims_are_mutually_exclusive(self) -> None:
        """One window, one candidate — a provider corroborating itself would
        inflate confidence from a single observation counted twice."""
        observations = [*_flat(), _observation(11, price="1.5", volume="400")]

        result = _provider().evaluate(_window(*observations), now=NOW)

        assert len(result.candidates) == 1


class TestStrength:
    def test_strength_rises_with_the_size_of_the_break(self) -> None:
        modest = [*_flat(), _observation(11, price="1.16", volume="250")]
        emphatic = [*_flat(), _observation(11, price="3.0", volume="900")]

        provider = _provider()
        weak = provider.evaluate(_window(*modest), now=NOW).candidates[0]
        strong = provider.evaluate(_window(*emphatic), now=NOW).candidates[0]

        assert weak.strength < strong.strength
        assert Decimal(0) <= weak.strength <= Decimal(100)

    def test_an_absurd_ratio_saturates_rather_than_dominating(self) -> None:
        """A 25,000x ratio exists in the stored history — a token whose prior
        price was effectively zero. Unbounded, one such row would outrank every
        real breakout it shared a board with.
        """
        observations = [
            *_flat(price="0.0000001"),
            _observation(11, price="10", volume="9999"),
        ]

        candidate = _provider().evaluate(_window(*observations), now=NOW).candidates[0]

        assert candidate.strength == Decimal("100.00")

    def test_a_breakout_outranks_a_pre_breakout_of_equal_expansion(self) -> None:
        broke = [*_flat(), _observation(11, price="1.16", volume="400")]
        approaching = [*_flat(), _observation(11, price="0.95", volume="400")]

        provider = _provider()
        first = provider.evaluate(_window(*broke), now=NOW).candidates[0]
        second = provider.evaluate(_window(*approaching), now=NOW).candidates[0]

        assert first.strength > second.strength


class TestDeterminism:
    def test_the_same_window_yields_the_same_candidate_every_time(self) -> None:
        """Replayability is the point of provider purity: a signal that cannot
        be reproduced from stored data cannot be backtested or audited.
        """
        observations = [
            *_flat(),
            _observation(11, price="1.5", volume="400", buys=90, sells=30),
        ]
        window = _window(*observations)

        runs = [_provider().evaluate(window, now=NOW) for _ in range(5)]

        assert all(run == runs[0] for run in runs)

    def test_the_clock_does_not_enter_the_claim(self) -> None:
        """`now` is a parameter and nothing reads it — the property the purity
        tests enforce for every other engine here."""
        observations = [*_flat(), _observation(11, price="1.5", volume="400")]
        window = _window(*observations)

        early = _provider().evaluate(window, now=NOW)
        late = _provider().evaluate(window, now=NOW + timedelta(days=400))

        assert early == late


class TestEvidence:
    def test_evidence_names_the_window_span(self) -> None:
        """Cadence is tier-dependent: twelve observations is six minutes for a
        fresh token and three days for an old one. A reader is entitled to know
        which range was broken."""
        observations = [*_flat(), _observation(11, price="1.5", volume="400")]

        candidate = _provider().evaluate(_window(*observations), now=NOW).candidates[0]

        labels = {item.label for item in candidate.evidence}
        assert {"Trailing high", "Volume baseline", "Window"} <= labels
        span = next(item for item in candidate.evidence if item.label == "Window")
        assert "minutes" in (span.detail or "")

    def test_every_figure_is_recomputable_from_the_window(self) -> None:
        observations = [*_flat(), _observation(11, price="1.5", volume="400")]

        candidate = _provider().evaluate(_window(*observations), now=NOW).candidates[0]

        values = {item.label: item.value for item in candidate.evidence}
        assert values["Trailing high"].startswith("1")
        assert values["Latest price"].startswith("1.5")
        assert values["Above range by"] == "50.0%"
