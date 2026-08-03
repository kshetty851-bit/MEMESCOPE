"""The Near Graduation provider and its scoring model.

Two subjects, and the first matters most: **the provider ships switched off
because the data does not support it**, not because the model is unfinished.
The model below is complete and exercised here with the provider explicitly
enabled, so it is ready the moment a real source of curve progress exists.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.opportunities.explain import REASON_MESSAGE, SIGNAL_LIMITS, explain
from app.opportunities.models import (
    MarketObservation,
    ObservationWindow,
    OpportunityStage,
    SignalSeverity,
    SignalType,
)
from app.opportunities.providers import registry
from app.opportunities.providers.near_graduation import (
    MIN_AVAILABLE_WEIGHT,
    PROVIDER_ID,
    REASON_APPROACHING,
    REASON_PROGRESS_STALLED,
    REASON_THIN_OBSERVATION,
    WEIGHTS,
    NearGraduationProvider,
)

pytestmark = pytest.mark.unit

NOW = datetime(2026, 8, 3, 12, 0, tzinfo=UTC)
MINT = "HHbRJ9Fw2tPxETGSsaeQhpgdizfVafLvXK7eo5mwpump"
THRESHOLD = Decimal(69_000)


def _enabled(**overrides: object) -> NearGraduationProvider:
    """The provider with the model switched on, for testing the model."""
    kwargs: dict[str, object] = {
        "enabled": True,
        "graduation_market_cap": THRESHOLD,
        "min_progress": Decimal("0.55"),
        "min_observations": 4,
        "bonding_curve_venues": frozenset({"pumpfun"}),
    }
    kwargs.update(overrides)
    return NearGraduationProvider(**kwargs)  # type: ignore[arg-type]


def _window(
    *,
    caps: list[float | None],
    volumes: list[float | None] | None = None,
    progress: list[float | None] | None = None,
    buys: list[int | None] | None = None,
    sells: list[int | None] | None = None,
    venue: str | None = "pumpfun",
    minutes_apart: int = 30,
) -> ObservationWindow:
    """A window of `len(caps)` observations, oldest first."""
    count = len(caps)
    # Progress now comes from the bonding curve, not from market cap. The
    # default derives it from `caps` so the model tests read the same as before
    # Sprint 8; `progress=` overrides it, and passing caps with progress=[None]
    # is how "market cap present, curve absent" is expressed.
    if progress is None:
        progress = [None if cap is None else cap / 69_000 for cap in caps]
    volumes = volumes or [1000.0] * count
    buys = buys or [100 + index * 10 for index in range(count)]
    sells = sells or [80 + index * 5 for index in range(count)]

    return ObservationWindow(
        mint_address=MINT,
        observations=tuple(
            MarketObservation(
                captured_at=NOW - timedelta(minutes=minutes_apart * (count - 1 - index)),
                price_usd=Decimal("0.0001"),
                market_cap=None if caps[index] is None else Decimal(str(caps[index])),
                curve_progress=(
                    None if progress[index] is None else Decimal(str(progress[index]))
                ),
                volume_24h=(
                None if volumes[index] is None else Decimal(str(volumes[index]))
            ),
                buy_count_24h=buys[index],
                sell_count_24h=sells[index],
                dex_name=venue,
            )
            for index in range(count)
        ),
    )


class TestShipsSwitchedOff:
    def test_the_default_provider_is_not_operational(self) -> None:
        """The headline decision of this sprint.

        `market_cap` on a bonding-curve pair does not track curve progress:
        across 386 observed graduations it identified 5, and of 48 tokens that
        reached $50k only those same 5 graduated. A threshold on it would be an
        estimate dressed as an observation.
        """
        assert NearGraduationProvider(enabled=False).meta.operational is False

    def test_it_declares_why_rather_than_going_missing(self) -> None:
        """A missing provider is invisible; one that says why it cannot run is a
        fact a reader can weigh."""
        reason = NearGraduationProvider(enabled=False).meta.unavailable_reason
        assert reason is not None
        assert "not collected" in reason
        assert "386" in reason and "48" in reason

    def test_calling_it_directly_still_declares(self) -> None:
        """The registry skips non-operational providers, but a caller holding an
        instance must get the declaration — never a score from data we do not
        trust."""
        result = NearGraduationProvider(enabled=False).evaluate(
            _window(caps=[60_000] * 6), now=NOW
        )
        assert not result.available
        assert result.candidates == ()

    def test_it_is_registered_despite_being_off(self) -> None:
        """Registered so the gap is discoverable in the provider list."""
        assert PROVIDER_ID in registry.ids
        assert registry.get(PROVIDER_ID).meta.emits == (SignalType.NEAR_GRADUATION,)

    def test_the_shipped_registry_does_not_run_it(self) -> None:
        operational = {provider.meta.provider_id for provider in registry.operational()}
        assert PROVIDER_ID not in operational

    def test_fresh_graduation_is_preserved(self) -> None:
        """Sprint 7 must not disturb the provider Sprint 4 shipped."""
        assert "fresh_graduation" in registry.ids
        assert registry.get("fresh_graduation").meta.operational is True


class TestAdmission:
    def test_a_token_below_the_band_says_nothing(self) -> None:
        """Most of the universe sits far down the curve. Reporting it would make
        "near graduation" mean nothing."""
        result = _enabled().evaluate(_window(caps=[1_000] * 6), now=NOW)
        assert result.candidates == ()

    def test_a_token_inside_the_band_is_reported(self) -> None:
        result = _enabled().evaluate(_window(caps=[45_000] * 6), now=NOW)
        assert len(result.candidates) == 1
        assert result.candidates[0].signal_type is SignalType.NEAR_GRADUATION
        assert result.candidates[0].stage is OpportunityStage.NEAR_GRADUATION

    def test_an_already_graduated_token_is_not_its_subject(self) -> None:
        result = _enabled().evaluate(_window(caps=[60_000] * 6, venue="pumpswap"), now=NOW)
        assert result.candidates == ()

    def test_absent_curve_progress_reports_nothing_rather_than_guessing(self) -> None:
        """The mandatory anchor. Without a distance to graduation there is no
        such thing as being near it — and a window with no curve reading must
        not be scored on the remaining components."""
        result = _enabled().evaluate(_window(caps=[None] * 6), now=NOW)
        assert result.candidates == ()

    def test_market_cap_alone_no_longer_produces_a_signal(self) -> None:
        """The §14a consequence, pinned.

        `market_cap` identified 5 of 386 observed graduations. Leaving it as a
        fallback would quietly reintroduce a signal already disproven, so a
        window with a market cap and no curve reading reports nothing.
        """
        result = _enabled().evaluate(
            _window(caps=[60_000] * 6, progress=[None] * 6), now=NOW
        )
        assert result.candidates == ()

    def test_curve_progress_alone_is_enough(self) -> None:
        """The converse: no market cap at all, but a curve reading, works.

        This is the whole point of Sprint 8 — the signal no longer depends on a
        field that cannot carry it.
        """
        result = _enabled().evaluate(
            _window(caps=[None] * 6, progress=[0.88] * 6), now=NOW
        )
        assert len(result.candidates) == 1

    def test_an_empty_window_says_nothing(self) -> None:
        result = _enabled().evaluate(ObservationWindow(mint_address=MINT), now=NOW)
        assert result.candidates == ()

    def test_a_null_venue_is_not_assumed_to_be_the_curve(self) -> None:
        result = _enabled().evaluate(_window(caps=[60_000] * 6, venue=None), now=NOW)
        assert result.candidates == ()


class TestModel:
    def test_further_along_the_curve_scores_higher(self) -> None:
        near = _enabled().evaluate(_window(caps=[66_000] * 6), now=NOW).candidates[0]
        early = _enabled().evaluate(_window(caps=[40_000] * 6), now=NOW).candidates[0]
        assert near.strength > early.strength

    def test_a_rising_curve_beats_a_stalled_one(self) -> None:
        """The component that separates a token parked at 80% for a day from one
        that arrived there in an hour."""
        rising = (
            _enabled()
            .evaluate(_window(caps=[40_000, 45_000, 50_000, 55_000, 60_000, 65_000]), now=NOW)
            .candidates[0]
        )
        stalled = _enabled().evaluate(_window(caps=[65_000] * 6), now=NOW).candidates[0]
        assert rising.strength > stalled.strength
        assert REASON_PROGRESS_STALLED in stalled.reason_codes

    def test_buy_pressure_is_read_from_deltas_not_levels(self) -> None:
        """`buy_count_24h` is a trailing total: its level says what happened over
        a day, its change says what happened since the last observation."""
        buying = (
            _enabled()
            .evaluate(
                _window(
                    caps=[60_000] * 6,
                    buys=[100, 140, 180, 220, 260, 300],
                    sells=[90] * 6,
                ),
                now=NOW,
            )
            .candidates[0]
        )
        selling = (
            _enabled()
            .evaluate(
                _window(
                    caps=[60_000] * 6,
                    buys=[100] * 6,
                    sells=[90, 130, 170, 210, 250, 290],
                ),
                now=NOW,
            )
            .candidates[0]
        )
        assert buying.strength > selling.strength

    def test_expanding_volume_scores_above_fading_volume(self) -> None:
        expanding = (
            _enabled()
            .evaluate(
                _window(caps=[60_000] * 6,
                volumes=[100, 100, 100, 400, 400, 400]),
                now=NOW,
            )
            .candidates[0]
        )
        fading = (
            _enabled()
            .evaluate(
                _window(caps=[60_000] * 6,
                volumes=[400, 400, 400, 100, 100, 100]),
                now=NOW,
            )
            .candidates[0]
        )
        assert expanding.strength > fading.strength

    def test_a_thin_window_still_reports_but_says_so(self) -> None:
        """Held with less confidence, and the reason is said out loud rather
        than folded silently into a lower number."""
        result = _enabled().evaluate(_window(caps=[60_000] * 4), now=NOW)
        assert len(result.candidates) == 1
        assert REASON_THIN_OBSERVATION in result.candidates[0].reason_codes

    def test_too_little_available_weight_declines(self) -> None:
        """Below the floor there is not enough to say anything honest.

        One observation leaves only `progress` and `consistency` available —
        0.45 of declared weight, under the 0.55 floor.
        """
        result = _enabled().evaluate(_window(caps=[60_000]), now=NOW)
        assert result.candidates == ()

    def test_strength_stays_in_range(self) -> None:
        extreme = (
            _enabled()
            .evaluate(
                _window(
                    caps=[68_999] * 8,
                    volumes=[1, 1, 1, 1, 100_000, 100_000, 100_000, 100_000],
                    buys=[0, 500, 1000, 1500, 2000, 2500, 3000, 3500],
                    sells=[0] * 8,
                    minutes_apart=1,
                ),
                now=NOW,
            )
            .candidates[0]
        )
        assert Decimal(0) <= extreme.strength <= Decimal(100)

    def test_weights_are_published_and_sum_to_one(self) -> None:
        """Published, so the number is checkable rather than asserted."""
        assert sum(WEIGHTS.values()) == Decimal(1)
        assert Decimal(1) > MIN_AVAILABLE_WEIGHT


class TestSeverity:
    @pytest.mark.parametrize(
        ("cap", "expected"),
        [
            (68_000, SignalSeverity.MAJOR),
            (55_000, SignalSeverity.NOTABLE),
            (40_000, SignalSeverity.INFO),
        ],
    )
    def test_severity_tracks_position_not_certainty(
        self, cap: int, expected: SignalSeverity
    ) -> None:
        """Severity is a property of the type and its position. How sure we are
        is confidence, which the engine derives — collapsing them would make a
        certain-but-trivial signal look like an important one."""
        candidate = _enabled().evaluate(_window(caps=[cap] * 6), now=NOW).candidates[0]
        assert candidate.severity is expected


class TestDeterminism:
    def test_the_same_window_gives_the_same_answer(self) -> None:
        """What makes the signal replayable over stored history, which is how
        thresholds get tuned rather than guessed."""
        window = _window(caps=[40_000, 48_000, 55_000, 61_000, 64_000, 66_000])
        first = _enabled().evaluate(window, now=NOW)
        second = _enabled().evaluate(window, now=NOW + timedelta(days=30))
        assert first.candidates == second.candidates

    def test_the_clock_does_not_change_the_reading(self) -> None:
        window = _window(caps=[60_000] * 6)
        now_strength = _enabled().evaluate(window, now=NOW).candidates[0].strength
        past = _enabled().evaluate(window, now=NOW - timedelta(days=400))
        assert now_strength == past.candidates[0].strength


class TestEvidenceAndExplanation:
    def test_every_component_appears_in_the_evidence(self) -> None:
        """Including the ones that could not be read. A component omitted is
        invisible; one that says "not available" is a fact."""
        candidate = _enabled().evaluate(_window(caps=[60_000] * 6), now=NOW).candidates[0]
        labels = {item.label for item in candidate.evidence}

        for component in WEIGHTS:
            assert component.replace("_", " ").capitalize() in labels
        assert "Curve progress" in labels

    def test_an_unavailable_component_is_labelled_as_such(self) -> None:
        candidate = (
            _enabled()
            .evaluate(_window(caps=[60_000] * 4, volumes=[None] * 4), now=NOW)
            .candidates[0]
        )
        values = {item.label: item.value for item in candidate.evidence}
        assert values["Volume trend"] == "not available"

    def test_it_always_carries_the_admission_reason_code(self) -> None:
        candidate = _enabled().evaluate(_window(caps=[60_000] * 6), now=NOW).candidates[0]
        assert candidate.reason_codes[0] == REASON_APPROACHING

    def test_every_reason_code_it_emits_has_prose(self) -> None:
        """A code with no message renders as itself — readable, but it means the
        explanation was never written."""
        candidate = (
            _enabled()
            .evaluate(
                _window(
                    caps=[40_000, 48_000, 55_000, 61_000, 64_000, 66_000],
                    volumes=[100, 100, 100, 500, 500, 500],
                    buys=[100, 200, 300, 400, 500, 600],
                    sells=[90] * 6,
                    minutes_apart=5,
                ),
                now=NOW,
            )
            .candidates[0]
        )
        assert len(candidate.reason_codes) >= 4
        for code in candidate.reason_codes:
            assert code in REASON_MESSAGE, f"{code} has no rendered message"

    def test_the_explanation_declares_what_it_could_not_check(self) -> None:
        """The limits clause carries the honesty. Curve progress being inferred
        from market cap is the single most important caveat on this signal."""
        limits = SIGNAL_LIMITS[SignalType.NEAR_GRADUATION]
        assert any("not a direct read of the bonding curve" in line for line in limits)
        assert any("Liquidity" in line for line in limits)

        candidate = _enabled().evaluate(_window(caps=[60_000] * 6), now=NOW).candidates[0]
        rendered = explain(
            signal_type=SignalType.NEAR_GRADUATION,
            reason_codes=candidate.reason_codes,
            evidence=tuple(
                {"label": item.label, "value": item.value, "detail": item.detail}
                for item in candidate.evidence
            ),
        )
        assert rendered.headline == "Approaching graduation"
        assert rendered.limits

    def test_no_message_is_a_recommendation(self) -> None:
        """The boundary erodes through prose long before anyone writes "buy"."""
        import re

        for code in (
            REASON_APPROACHING,
            REASON_PROGRESS_STALLED,
            REASON_THIN_OBSERVATION,
        ):
            text = REASON_MESSAGE[code]
            for word in ("buy", "sell", "hold", "should", "recommend"):
                assert not re.search(rf"\b{word}\b", text, re.IGNORECASE)

    def test_messages_are_indicative_not_predictive(self) -> None:
        """"is approaching", never "will graduate". The provider reports a
        trajectory it observed, not an outcome it expects."""
        for code, text in REASON_MESSAGE.items():
            assert " will " not in text.lower(), code
