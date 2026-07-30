"""Unit tests for change detection.

The rules worth locking are the ones about *silence*. An event engine that
fires too often is worse than none, because users mute it and lose the alerts
that mattered — so most of these assert that nothing was emitted.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.analysts.lifecycle import MissionState
from app.analysts.research import ResearchPriority
from app.events.detector import TokenState, detect
from app.models.intelligence import EventKind, EventSeverity

pytestmark = pytest.mark.unit


def state(**over: object) -> TokenState:
    base: dict[str, object] = {
        "mint_address": "mint",
        "mission_state": MissionState.ORBIT,
        "research_priority": ResearchPriority.MEDIUM,
        "combined_score": Decimal(60),
        "confidence": Decimal(50),
        "liquidity_score": Decimal(60),
        "momentum_score": Decimal(60),
        "risk_score": Decimal(60),
        "clone_risk": "none",
        "exit_severity": "clear",
        "warning_codes": frozenset(),
    }
    base.update(over)
    return TokenState(**base)  # type: ignore[arg-type]


class TestSilenceIsTheDefault:
    def test_an_unchanged_token_emits_nothing(self) -> None:
        assert detect(state(), state()) == []

    def test_score_drift_below_the_bar_is_not_an_event(self) -> None:
        # Scores move continuously as observations arrive. Only a move past the
        # engine's own materiality threshold counts.
        quiet = detect(state(liquidity_score=Decimal(60)), state(liquidity_score=Decimal(70)))
        assert quiet == []

    def test_confidence_drift_below_the_bar_is_not_an_event(self) -> None:
        assert detect(state(confidence=Decimal(50)), state(confidence=Decimal(56))) == []

    def test_price_alone_never_produces_an_event(self) -> None:
        # There is no price field on TokenState at all — by design. A price move
        # that matters surfaces as momentum or liquidity, with evidence.
        assert not hasattr(state(), "price")


class TestMeaningfulChangesAreReported:
    def test_a_mission_downgrade_is_urgent(self) -> None:
        events = detect(
            state(mission_state=MissionState.ASCENT),
            state(mission_state=MissionState.LOST_CONTACT),
        )
        assert len(events) == 1
        assert events[0].kind is EventKind.MISSION_DOWNGRADED
        # Deterioration on something a user may hold outranks the same move up.
        assert events[0].severity is EventSeverity.URGENT
        assert events[0].previous_value == "ascent"
        assert events[0].current_value == "lost_contact"

    def test_a_mission_promotion_is_notable_not_urgent(self) -> None:
        events = detect(
            state(mission_state=MissionState.RE_ENTRY),
            state(mission_state=MissionState.ORBIT),
        )
        assert events[0].kind is EventKind.MISSION_PROMOTED
        assert events[0].severity is EventSeverity.NOTABLE

    def test_reaching_critical_priority_is_urgent(self) -> None:
        events = detect(
            state(research_priority=ResearchPriority.LOW),
            state(research_priority=ResearchPriority.CRITICAL),
        )
        assert events[0].kind is EventKind.PRIORITY_INCREASED
        assert events[0].severity is EventSeverity.URGENT

    def test_exit_watch_activation_carries_the_disclaimer(self) -> None:
        events = detect(state(exit_severity="clear"), state(exit_severity="elevated"))
        assert events[0].kind is EventKind.EXIT_WATCH_ACTIVATED
        assert "never a sell signal" in events[0].summary

    def test_exit_watch_clearing_is_reported_too(self) -> None:
        events = detect(state(exit_severity="watch"), state(exit_severity="clear"))
        assert events[0].kind is EventKind.EXIT_WATCH_CLEARED

    def test_a_severity_shift_within_exit_watch_is_a_risk_change(self) -> None:
        # watch -> elevated is real but is not an "activation"; the wording has
        # to stay true to what happened.
        events = detect(state(exit_severity="watch"), state(exit_severity="elevated"))
        assert events[0].kind is EventKind.RISK_INCREASED
        assert "watch to elevated" in events[0].summary

    def test_clone_detection_is_urgent(self) -> None:
        events = detect(state(clone_risk="none"), state(clone_risk="high"))
        assert events[0].kind is EventKind.CLONE_DETECTED
        assert events[0].severity is EventSeverity.URGENT

    def test_a_clone_move_between_trivial_levels_is_ignored(self) -> None:
        # none -> low is not a warning worth interrupting anyone for.
        assert detect(state(clone_risk="none"), state(clone_risk="low")) == []

    def test_a_material_liquidity_move_is_reported_with_both_values(self) -> None:
        events = detect(state(liquidity_score=Decimal(30)), state(liquidity_score=Decimal(70)))
        assert events[0].kind is EventKind.LIQUIDITY_IMPROVED
        assert events[0].previous_value == "30"
        assert events[0].current_value == "70"
        assert events[0].analyst == "liquidity"


class TestRiskDirectionIsNotInverted:
    def test_a_rising_risk_score_resolves_risk(self) -> None:
        # Risk scores higher-is-safer. A mixed convention inside one engine is
        # how sign errors ship.
        events = detect(state(risk_score=Decimal(20)), state(risk_score=Decimal(80)))
        assert events[0].kind is EventKind.RISK_RESOLVED

    def test_a_falling_risk_score_raises_risk(self) -> None:
        events = detect(state(risk_score=Decimal(80)), state(risk_score=Decimal(20)))
        assert events[0].kind is EventKind.RISK_INCREASED
        assert events[0].severity is EventSeverity.URGENT


class TestFirstSighting:
    def test_a_new_token_produces_one_event_not_a_burst(self) -> None:
        # Diffing against nothing would report every field as an improvement.
        events = detect(None, state())
        assert len(events) == 1
        assert events[0].kind is EventKind.FIRST_ANALYSED
        assert events[0].severity is EventSeverity.INFO

    def test_a_first_sighting_is_not_described_as_an_improvement(self) -> None:
        summary = detect(None, state())[0].summary.lower()
        for banned in ("improved", "rose", "promoted", "increased"):
            assert banned not in summary


class TestDeterminism:
    def test_the_same_pair_yields_the_same_events_every_time(self) -> None:
        before = state(mission_state=MissionState.ASCENT, confidence=Decimal(80))
        after = state(mission_state=MissionState.RE_ENTRY, confidence=Decimal(30))
        runs = {
            tuple((e.kind, e.previous_value, e.current_value) for e in detect(before, after))
            for _ in range(30)
        }
        assert len(runs) == 1

    def test_a_missing_reading_never_fabricates_a_change(self) -> None:
        # None means "could not be read". Treating it as zero would emit a
        # collapse event every time an analyst went dark.
        assert detect(state(liquidity_score=None), state(liquidity_score=Decimal(90))) == []
        assert detect(state(liquidity_score=Decimal(90)), state(liquidity_score=None)) == []


class TestNoAdviceInEventCopy:
    def test_no_event_summary_recommends_anything(self) -> None:
        pairs = [
            (None, state()),
            (
                state(mission_state=MissionState.ASCENT),
                state(mission_state=MissionState.LOST_CONTACT),
            ),
            (state(exit_severity="clear"), state(exit_severity="elevated")),
            (state(clone_risk="none"), state(clone_risk="high")),
            (state(risk_score=Decimal(80)), state(risk_score=Decimal(10))),
            (state(confidence=Decimal(20)), state(confidence=Decimal(90))),
        ]
        prose = " ".join(
            event.summary for before, after in pairs for event in detect(before, after)
        ).lower()

        for banned in (
            "you should buy",
            "you should sell",
            "we recommend",
            "consider buying",
            "time to buy",
            "guaranteed",
            "will rise",
        ):
            assert banned not in prose
