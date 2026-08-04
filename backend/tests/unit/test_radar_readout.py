"""The trader-facing readout: one sentence, four bands, no invention.

Pure, so these tests need no fixtures and no database. What they pin down is
mostly *refusal* — the layer must never print a raw code, never quote a move it
did not measure, and never turn an unassessed risk into a band.

The priority order is asserted rather than assumed. It is the whole design: a
sentence that reports the least interesting true fact is worse than useless on
a row read in three seconds.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.radar import readout
from app.radar.models import RadarReason

pytestmark = pytest.mark.unit

NOW = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)


class TestSignalLabel:
    def test_engine_names_are_translated(self) -> None:
        assert readout.signal_label("fresh_graduation") == "Recently graduated from Pump.fun"
        assert readout.signal_label("breakout") == "Strong buying pressure"

    def test_an_unknown_type_renders_nothing_rather_than_its_code(self) -> None:
        """Printing `pre_breakout` on screen is worse than printing nothing, and
        a provider shipping before its label is a deploy away from correct."""
        assert readout.signal_label("some_future_provider") is None
        assert readout.signal_label(None) is None

    def test_every_declared_signal_type_has_a_label(self) -> None:
        """Guards the gap this module exists to close: a signal the engine can
        emit and this layer cannot say."""
        from app.opportunities.models import SignalType

        for member in SignalType:
            assert member.value in readout.SIGNAL_LABEL
            assert member.value in readout.SIGNAL_WHY


class TestRiskBand:
    def test_high_scores_are_safe_matching_how_risk_is_scored(self) -> None:
        assert readout.risk_band(Decimal(90)) == "low"
        assert readout.risk_band(Decimal(50)) == "medium"
        assert readout.risk_band(Decimal(30)) == "high"
        assert readout.risk_band(Decimal(10)) == "extreme"

    def test_the_boundaries_are_inclusive_at_the_floor(self) -> None:
        assert readout.risk_band(Decimal(70)) == "low"
        assert readout.risk_band(Decimal(45)) == "medium"
        assert readout.risk_band(Decimal(25)) == "high"

    def test_an_unassessed_risk_has_no_band(self) -> None:
        """`None` is not a fifth band. On this scale an invented zero would read
        as the most dangerous token on the page."""
        assert readout.risk_band(None) is None


class TestElapsed:
    def test_it_completes_a_sentence(self) -> None:
        assert readout.elapsed(30) == "moments ago"
        assert readout.elapsed(60) == "1 minute ago"
        assert readout.elapsed(18 * 60) == "18 minutes ago"
        assert readout.elapsed(3_600) == "1 hour ago"
        assert readout.elapsed(6 * 3_600) == "6 hours ago"
        assert readout.elapsed(86_400) == "1 day ago"
        assert readout.elapsed(3 * 86_400) == "3 days ago"

    def test_a_clock_disagreement_does_not_produce_a_negative_phrase(self) -> None:
        assert readout.elapsed(-30) == "moments ago"


class TestWhyNowPriority:
    def test_a_live_signal_outranks_a_large_move(self) -> None:
        """The signal is the only input about *now* rather than about state."""
        result = readout.why_now(
            now=NOW,
            signal_type="fresh_graduation",
            signal_detected_at=NOW - timedelta(minutes=18),
            current_multiple=Decimal("9.0"),
            detection_reasons=("resistance_broken",),
            first_detected_at=NOW - timedelta(days=2),
        )
        assert result.code == "signal:fresh_graduation"
        assert result.sentence == "Graduated from Pump.fun 18 minutes ago."

    def test_a_large_move_outranks_a_detection_reason(self) -> None:
        result = readout.why_now(
            now=NOW,
            current_multiple=Decimal("3.5"),
            detection_reasons=("resistance_broken",),
            first_detected_at=NOW - timedelta(days=2),
        )
        assert result.code == "move_up"
        assert result.sentence == "Trading 3.5x above where it was detected."

    def test_losses_are_narrated_as_readily_as_gains(self) -> None:
        """A track record that only narrates winners is not a track record."""
        result = readout.why_now(
            now=NOW,
            current_multiple=Decimal("0.30"),
            detection_reasons=("resistance_broken",),
            first_detected_at=NOW - timedelta(days=2),
        )
        assert result.code == "move_down"
        assert result.sentence == "Down 70% from where it was detected."

    def test_a_move_inside_the_threshold_is_not_news(self) -> None:
        """ "Up 1.1x since detection" dresses a rounding error as news."""
        result = readout.why_now(
            now=NOW,
            current_multiple=Decimal("1.1"),
            detection_reasons=("resistance_broken",),
            first_detected_at=NOW - timedelta(days=2),
        )
        assert result.code == "reason:resistance_broken"

    def test_the_most_distinguishing_reason_wins(self) -> None:
        """`trend_aligned` held for 10 of the live top 10 and says almost
        nothing; `resistance_broken` held for 8 and says a great deal."""
        result = readout.why_now(
            now=NOW,
            detection_reasons=("trend_aligned", "turnover_healthy", "resistance_broken"),
            first_detected_at=NOW - timedelta(days=2),
        )
        assert result.code == "reason:resistance_broken"

    def test_the_order_of_the_stored_list_does_not_change_the_answer(self) -> None:
        """Determinism: the same facts must produce the same sentence however
        the engine happened to append them."""
        forwards = readout.why_now(
            now=NOW,
            detection_reasons=("volume_expanding", "trend_aligned"),
            first_detected_at=NOW,
        )
        backwards = readout.why_now(
            now=NOW,
            detection_reasons=("trend_aligned", "volume_expanding"),
            first_detected_at=NOW,
        )
        assert forwards == backwards


class TestWhyNowRefusals:
    def test_missing_data_is_never_a_headline(self) -> None:
        """`community_data_unavailable` held for 10 of the live top 10. It is a
        statement about our collection, not about the token — it belongs in the
        evidence figure, not in a sentence about why this is interesting."""
        result = readout.why_now(
            now=NOW,
            detection_reasons=("community_data_unavailable", "insufficient_history"),
            first_detected_at=NOW - timedelta(hours=6),
        )
        assert result.code == "detected"
        assert result.sentence == "Picked up by the Radar 6 hours ago."

    def test_an_unknown_reason_code_is_skipped_not_printed(self) -> None:
        result = readout.why_now(
            now=NOW,
            detection_reasons=("some_new_code", "volume_expanding"),
            first_detected_at=NOW,
        )
        assert result.code == "reason:volume_expanding"
        assert "some_new_code" not in result.sentence

    def test_there_is_always_something_true_to_say(self) -> None:
        """The floor is the detection itself, which is always true."""
        result = readout.why_now(now=NOW, first_detected_at=NOW - timedelta(hours=2))
        assert result.sentence == "Picked up by the Radar 2 hours ago."

    def test_even_a_row_with_no_facts_at_all_renders(self) -> None:
        """A row that renders beats a page that 500s over a sentence."""
        result = readout.why_now(now=NOW)
        assert result.code == "unavailable"
        assert result.sentence

    def test_no_sentence_contains_a_raw_code(self) -> None:
        """An underscore in rendered prose means a code escaped the mapping."""
        for reason in readout.REASON_PRIORITY:
            result = readout.why_now(
                now=NOW, detection_reasons=(reason.value,), first_detected_at=NOW
            )
            assert "_" not in result.sentence, reason

    def test_no_sentence_predicts(self) -> None:
        """Templates are indicative, matching `explain.py`: "volume is
        expanding", never "volume will expand"."""
        forbidden = (" will ", " should ", " expect", "likely", "could ", "going to")
        sentences = [
            readout.why_now(
                now=NOW, detection_reasons=(reason.value,), first_detected_at=NOW
            ).sentence
            for reason in readout.REASON_PRIORITY
        ]
        sentences += list(readout.SIGNAL_LABEL.values())
        for sentence in sentences:
            lowered = sentence.lower()
            for word in forbidden:
                assert word not in lowered, sentence


class TestCoverage:
    def test_every_prioritised_reason_has_wording(self) -> None:
        for reason in readout.REASON_PRIORITY:
            assert reason in readout.REASON_WHY

    def test_only_unavailability_reasons_are_left_unsayable(self) -> None:
        """If the engine gains a reason, this asserts someone decided whether it
        is worth saying rather than letting it fall silently to the fallback."""
        unsayable = set(RadarReason) - set(readout.REASON_PRIORITY)
        assert unsayable == {
            RadarReason.COMMUNITY_DATA_UNAVAILABLE,
            RadarReason.INSUFFICIENT_HISTORY,
            RadarReason.SIGNAL_NOT_AVAILABLE,
        }
