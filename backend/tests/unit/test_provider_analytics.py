"""Deriving a provider's record from its raw counts.

The derivations are pure, so they are exercised against literals — including
every case where the honest answer is to refuse. Those are the ones worth
having: a ratio with an empty denominator is where an analytics layer starts
inventing performance nobody measured.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from app.opportunities.analytics import (
    NO_OUTCOMES_REASON,
    NOT_PREDICTIVE_REASON,
    ProviderAnalytics,
    ProviderTotals,
    summarise,
)

pytestmark = pytest.mark.unit


def _record(**totals: Any) -> ProviderAnalytics:
    return summarise(
        ProviderTotals(provider_id="fresh_graduation", **totals),
        name="Fresh graduation",
        operational=True,
        unavailable_reason=None,
    )


class TestCounts:
    def test_counts_pass_through_untouched(self) -> None:
        record = _record(signals=10, opportunities=7, confirmed=6, expired=3, closed=4)

        assert (record.signals, record.opportunities) == (10, 7)
        assert (record.confirmed, record.expired, record.closed) == (6, 3, 4)


class TestAverages:
    def test_average_confidence_divides_by_the_signals_it_summed(self) -> None:
        record = _record(signals=4, confidence_total=Decimal(250))

        assert record.average_confidence == Decimal("62.50")

    def test_lifetime_averages_only_over_closed_generations(self) -> None:
        """A live opportunity has no lifetime yet.

        Counting it as zero would drag the average toward a duration nothing
        ever had — the estimate dressed as a measurement.
        """
        record = _record(signals=9, lifetime_seconds_total=Decimal(7_200), lifetime_samples=2)

        assert record.average_lifetime_seconds == 3_600

    def test_a_provider_that_has_closed_nothing_has_no_average_lifetime(self) -> None:
        record = _record(signals=5, opportunities=5)

        assert record.average_lifetime_seconds is None


class TestHitRate:
    def test_hit_rate_is_confirmations_over_everything_emitted(self) -> None:
        record = _record(signals=8, confirmed=6)

        assert record.hit_rate == Decimal("0.75")

    def test_a_provider_that_never_ran_has_no_hit_rate(self) -> None:
        """`None`, not zero. Zero reads as tried-and-failed; this one never
        tried, and the two must not look alike on an operator's screen."""
        record = _record()

        assert record.hit_rate is None


class TestPrecision:
    def test_precision_is_unavailable_while_no_outcome_is_recorded(self) -> None:
        """The whole point of the sprint's honesty rule.

        Nothing writes REALISED or INVALIDATED yet, so precision has no
        denominator. It is reported absent with the reason attached — never as
        zero, and never quietly substituted by the hit rate.
        """
        record = _record(signals=40, confirmed=31, closed=22)

        assert record.precision is None
        assert record.precision_unavailable_reason == NO_OUTCOMES_REASON
        assert record.hit_rate is not None

    def test_precision_is_computed_once_outcomes_exist(self) -> None:
        """Ready for the realisation exit path without a code change."""
        record = _record(signals=10, realised=3, invalidated=1)

        assert record.precision == Decimal("0.75")
        assert record.precision_unavailable_reason is None

    def test_an_all_invalidated_provider_scores_zero_not_none(self) -> None:
        """Measured and bad is a different claim from unmeasured."""
        record = _record(signals=6, invalidated=4)

        assert record.precision == Decimal(0)
        assert record.precision_unavailable_reason is None


class TestNonOperationalProviders:
    def test_a_blocked_provider_carries_its_reason(self) -> None:
        """Registered with zeroes rather than omitted — "produced nothing" and
        "does not exist here" are different facts."""
        record = summarise(
            ProviderTotals(provider_id="near_graduation"),
            name="Near graduation",
            operational=False,
            unavailable_reason="Bonding-curve progress is not collected.",
        )

        assert record.operational is False
        assert record.unavailable_reason == "Bonding-curve progress is not collected."
        assert record.signals == 0
        assert record.hit_rate is None


class TestPredictiveSplit:
    def test_a_factual_provider_reports_precision_as_not_applicable(self) -> None:
        """The number that must never be published.

        Fresh graduation reports a completed change. With precision computed
        over every signal, its structurally-zero numerator over its
        invalidations would publish 0.00 against a provider that never made a
        prediction to miss — correct arithmetic, false claim.
        """
        record = summarise(
            ProviderTotals(provider_id="fresh_graduation", signals=40, contradicted=3),
            name="Fresh graduation",
            operational=True,
            unavailable_reason=None,
            predictive=False,
        )

        assert record.precision is None
        assert record.precision_unavailable_reason == NOT_PREDICTIVE_REASON
        assert record.contradicted == 3

    def test_the_two_gaps_are_distinguishable(self) -> None:
        """ "Never forecasts" and "has not resolved a forecast yet" are
        different facts, and a reader waiting for a number deserves to know
        which one they are looking at."""
        waiting = _record(signals=10)
        never = summarise(
            ProviderTotals(provider_id="fresh_graduation"),
            name="Fresh graduation",
            operational=True,
            unavailable_reason=None,
            predictive=False,
        )

        assert waiting.precision_unavailable_reason == NO_OUTCOMES_REASON
        assert never.precision_unavailable_reason == NOT_PREDICTIVE_REASON
        assert waiting.precision_unavailable_reason != never.precision_unavailable_reason

    def test_a_contradiction_never_reaches_a_ratio(self) -> None:
        """A re-indexing artefact is a data correction, not a bad call."""
        record = _record(signals=8, confirmed=6, contradicted=5)

        assert record.hit_rate == Decimal("0.75")
        assert record.precision is None
