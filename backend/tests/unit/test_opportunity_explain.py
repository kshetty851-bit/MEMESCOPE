"""Explanations rendered from stored reason codes.

Pure. The point of the module is that prose lives in code and identifiers live
in the database, so rewording is a deploy rather than a migration (AD-07).
"""

from __future__ import annotations

import re

import pytest

from app.opportunities.explain import (
    REASON_MESSAGE,
    SIGNAL_HEADLINE,
    Explanation,
    explain,
    headline,
    message,
)
from app.opportunities.models import SignalType

pytestmark = pytest.mark.unit

EVIDENCE = (
    {"label": "Previous venue", "value": "pumpfun", "detail": "Bonding curve"},
    {"label": "Current venue", "value": "pumpswap", "detail": "Graduated pool"},
)


def _explain(**overrides: object) -> Explanation:
    values: dict[str, object] = {
        "signal_type": SignalType.FRESH_GRADUATION,
        "reason_codes": ("graduated_from_bonding_curve", "trading_venue_changed"),
        "evidence": EVIDENCE,
    }
    values.update(overrides)
    return explain(**values)  # type: ignore[arg-type]


class TestStructure:
    def test_it_answers_why_now(self) -> None:
        rendered = _explain()

        assert rendered.headline == "Freshly graduated"
        assert "bonding curve" in rendered.trigger
        assert rendered.boundary is not None

    def test_evidence_becomes_the_delta(self) -> None:
        delta = _explain().delta

        assert any("pumpfun" in line for line in delta)
        assert any("pumpswap" in line for line in delta)
        assert any("Bonding curve" in line for line in delta)

    def test_limits_are_always_present_for_a_known_signal(self) -> None:
        """The clause that keeps coverage honest.

        A card without it quietly looks complete, which is exactly what the
        platform refuses to do with smart money.
        """
        limits = _explain().limits

        assert limits
        assert any("Liquidity" in line for line in limits)
        assert any("Holder" in line for line in limits)

    def test_corroboration_is_empty_with_a_single_provider(self) -> None:
        assert _explain().corroboration == ()

    def test_corroboration_names_the_agreeing_providers(self) -> None:
        rendered = _explain(corroborating_providers=("liquidity_surge",))
        assert rendered.corroboration == ("Also reported by liquidity_surge.",)


class TestRobustness:
    def test_an_unknown_reason_code_renders_rather_than_raising(self) -> None:
        """A provider added in a future sprint must produce a plain-looking
        explanation, not a 500 on the board."""
        rendered = _explain(reason_codes=("some_future_code",))
        assert rendered.trigger == "Some future code"

    def test_an_unknown_signal_type_gets_a_derived_headline(self) -> None:
        assert headline(SignalType.WHALE_ACCUMULATION) == "Whale accumulation"

    def test_no_reason_codes_falls_back_to_the_headline(self) -> None:
        rendered = _explain(reason_codes=())
        assert rendered.trigger == rendered.headline
        assert rendered.boundary is None

    def test_incomplete_evidence_is_skipped_not_rendered_blank(self) -> None:
        rendered = _explain(evidence=({"label": "Venue"}, {"value": "pumpswap"}))
        assert rendered.delta == ()

    def test_evidence_without_detail_still_renders(self) -> None:
        rendered = _explain(evidence=({"label": "Observed at", "value": "12:00"},))
        assert rendered.delta == ("Observed at: 12:00",)


class TestDeterminism:
    def test_the_same_signal_explains_the_same_way(self) -> None:
        """A board reconstructed from a past moment must read as it did then."""
        assert _explain() == _explain()


class TestBoundaries:
    def test_no_message_is_a_recommendation(self) -> None:
        """The boundary erodes through prose long before anyone writes "buy".

        The same assertion the analyst contract makes across all six analysts.
        """
        # Whole words only: "Holders growing" legitimately contains "hold".
        forbidden = ("buy", "sell", "hold", "consider", "should", "recommend")
        for text in (*REASON_MESSAGE.values(), *SIGNAL_HEADLINE.values()):
            for word in forbidden:
                assert not re.search(rf"\b{word}\b", text, re.IGNORECASE), (
                    f"{text!r} contains {word!r}"
                )

    def test_messages_are_indicative_not_predictive(self) -> None:
        for text in REASON_MESSAGE.values():
            assert " will " not in text.lower()

    def test_every_shipped_signal_type_has_a_headline(self) -> None:
        assert SignalType.FRESH_GRADUATION in SIGNAL_HEADLINE

    def test_message_falls_back_readably(self) -> None:
        assert message("a_totally_unknown_code") == "A totally unknown code"
