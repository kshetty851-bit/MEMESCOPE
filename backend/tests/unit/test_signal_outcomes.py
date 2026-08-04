"""Deciding what became of a signal.

Pure rules over literal windows. The refusals matter most: an outcome forced
onto an open question is a verdict the data did not support, and every precision
figure the platform ever publishes divides by these counts.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.opportunities.models import (
    MarketObservation,
    ObservationWindow,
    SignalStatus,
    SignalType,
)
from app.opportunities.outcomes import (
    PREDICTIVE_SIGNALS,
    REASON_BREAKOUT_REALISED,
    REASON_CURVE_RETREATED,
    REASON_GRADUATION_REALISED,
    REASON_PRESSURE_FADED,
    REASON_VENUE_REVERTED,
    OutcomeRules,
    assess,
)

pytestmark = pytest.mark.unit

NOW = datetime(2026, 8, 3, 12, 0, tzinfo=UTC)
RULES = OutcomeRules(
    price_margin=Decimal("0.15"),
    proximity=Decimal("0.90"),
    bonding_curve_venues=frozenset({"pumpfun"}),
    graduated_venues=frozenset({"pumpswap"}),
    min_curve_progress=Decimal("0.55"),
)


def _observation(
    minutes: int,
    *,
    price: str | None = "1.0",
    venue: str | None = "pumpswap",
    progress: str | None = None,
) -> MarketObservation:
    return MarketObservation(
        captured_at=NOW + timedelta(minutes=minutes),
        price_usd=None if price is None else Decimal(price),
        volume_1h=Decimal(100),
        dex_name=venue,
        curve_progress=None if progress is None else Decimal(progress),
    )


def _window(*observations: MarketObservation) -> ObservationWindow:
    return ObservationWindow(mint_address="mint", observations=observations)


class TestDeclaration:
    def test_only_forecasts_are_predictive(self) -> None:
        """The distinction the whole precision figure rests on.

        A fresh graduation reports a change that already completed; it cannot
        be right or wrong later. Including it would publish 0.00 precision
        against a provider that never made a prediction to miss.
        """
        assert {
            SignalType.NEAR_GRADUATION,
            SignalType.PRE_BREAKOUT,
        } == PREDICTIVE_SIGNALS
        assert SignalType.FRESH_GRADUATION not in PREDICTIVE_SIGNALS
        assert SignalType.BREAKOUT not in PREDICTIVE_SIGNALS


class TestOpenQuestions:
    def test_a_signal_is_never_judged_by_its_own_observation(self) -> None:
        """The claim marking its own homework.

        Without this the observation that opened a signal would immediately
        resolve it, and every signal would carry an outcome decided by the same
        snapshot that created it.
        """
        window = _window(_observation(0, price="1.0"), _observation(5, price="2.0"))

        verdict = assess(
            SignalType.PRE_BREAKOUT,
            window,
            observed_at=window.observations[-1].captured_at,
            rules=RULES,
        )

        assert verdict is None

    def test_a_price_still_inside_the_band_is_undecided(self) -> None:
        """Most signals neither realise nor reverse before their TTL. `None` is
        the common, correct answer — not a failure to decide."""
        window = _window(*[_observation(i, price="1.0") for i in range(4)])

        assert assess(SignalType.PRE_BREAKOUT, window, observed_at=None, rules=RULES) is None

    def test_a_missing_price_decides_nothing(self) -> None:
        """The same refusal the provider makes on the same missing field —
        unknown, not unrealised."""
        window = _window(_observation(0, price="1.0"), _observation(5, price=None))

        assert assess(SignalType.PRE_BREAKOUT, window, observed_at=None, rules=RULES) is None

    def test_breakout_has_no_rule_at_all(self) -> None:
        """A completed price move cannot reverse into never having happened.

        A retracement rule would convert every ordinary pullback into a recorded
        failure and make the platform's own history read as usually wrong.
        """
        window = _window(_observation(0, price="10.0"), _observation(5, price="0.1"))

        assert assess(SignalType.BREAKOUT, window, observed_at=None, rules=RULES) is None


class TestPreBreakout:
    def test_clearing_the_range_realises_it(self) -> None:
        """ADR §15 step 3's realisation path: it exits here and re-enters
        through the provider as a breakout, two records of one story."""
        window = _window(
            _observation(0, price="1.0"),
            _observation(5, price="1.0"),
            _observation(10, price="1.5"),
        )

        verdict = assess(SignalType.PRE_BREAKOUT, window, observed_at=None, rules=RULES)

        assert verdict is not None
        assert verdict.status is SignalStatus.REALISED
        assert verdict.realised
        assert verdict.reason_code == REASON_BREAKOUT_REALISED

    def test_falling_out_of_the_band_invalidates_it(self) -> None:
        window = _window(
            _observation(0, price="1.0"),
            _observation(5, price="1.0"),
            _observation(10, price="0.5"),
        )

        verdict = assess(SignalType.PRE_BREAKOUT, window, observed_at=None, rules=RULES)

        assert verdict is not None
        assert verdict.status is SignalStatus.INVALIDATED
        assert not verdict.realised
        assert verdict.reason_code == REASON_PRESSURE_FADED

    def test_it_is_judged_against_the_boundary_it_was_opened_against(self) -> None:
        """Same margin the provider published. Opened against one number and
        judged against another, the record would be unreplayable."""
        window = _window(
            _observation(0, price="1.0"),
            _observation(5, price="1.0"),
            _observation(10, price="1.14"),
        )

        assert assess(SignalType.PRE_BREAKOUT, window, observed_at=None, rules=RULES) is None


class TestNearGraduation:
    def test_reaching_a_graduated_venue_realises_it(self) -> None:
        window = _window(_observation(0, venue="pumpfun"), _observation(5, venue="pumpswap"))

        verdict = assess(SignalType.NEAR_GRADUATION, window, observed_at=None, rules=RULES)

        assert verdict is not None
        assert verdict.status is SignalStatus.REALISED
        assert verdict.reason_code == REASON_GRADUATION_REALISED

    def test_a_retreating_curve_invalidates_it(self) -> None:
        window = _window(
            _observation(0, venue="pumpfun", progress="0.8"),
            _observation(5, venue="pumpfun", progress="0.2"),
        )

        verdict = assess(SignalType.NEAR_GRADUATION, window, observed_at=None, rules=RULES)

        assert verdict is not None
        assert verdict.status is SignalStatus.INVALIDATED
        assert verdict.reason_code == REASON_CURVE_RETREATED

    def test_absent_curve_progress_decides_nothing(self) -> None:
        """Never inferred from market cap. §14a measured that as unusable, and
        an outcome derived from it would be an estimate presented as a result.
        """
        window = _window(_observation(0, venue="pumpfun"), _observation(5, venue="pumpfun"))

        assert (
            assess(SignalType.NEAR_GRADUATION, window, observed_at=None, rules=RULES) is None
        )


class TestFreshGraduation:
    def test_a_venue_reverting_contradicts_the_reading(self) -> None:
        """Factual, so this is a correction rather than a failed forecast — it
        is counted as a contradiction and never reaches precision."""
        window = _window(_observation(0, venue="pumpswap"), _observation(5, venue="pumpfun"))

        verdict = assess(SignalType.FRESH_GRADUATION, window, observed_at=None, rules=RULES)

        assert verdict is not None
        assert verdict.status is SignalStatus.INVALIDATED
        assert verdict.reason_code == REASON_VENUE_REVERTED

    def test_a_token_that_stays_graduated_is_left_alone(self) -> None:
        window = _window(_observation(0, venue="pumpswap"), _observation(5, venue="pumpswap"))

        assert (
            assess(SignalType.FRESH_GRADUATION, window, observed_at=None, rules=RULES) is None
        )


class TestDeterminism:
    def test_the_same_window_decides_the_same_way_every_time(self) -> None:
        """An outcome has to be replayable over history exactly as it was
        decided live, or no backtest of it means anything."""
        window = _window(
            _observation(0, price="1.0"),
            _observation(5, price="1.0"),
            _observation(10, price="1.5"),
        )

        verdicts = [
            assess(SignalType.PRE_BREAKOUT, window, observed_at=None, rules=RULES)
            for _ in range(5)
        ]

        assert all(verdict == verdicts[0] for verdict in verdicts)
