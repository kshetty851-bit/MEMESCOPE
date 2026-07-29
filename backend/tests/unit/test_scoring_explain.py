"""Reason codes, explanation assembly, and read-time freshness.

The metadata completeness test is the important one: codes are persisted in
`token_score_history.reasons`, so a code without a template would reach the UI
as an unrenderable identifier.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.services.scoring.explain import (
    REASON_META,
    AgentId,
    ReasonCode,
    Severity,
    build_explanation,
    meta_for,
)
from app.services.scoring.freshness import confidence_of, freshness_of
from app.services.scoring.normalisers import HUNDRED, ONE, ZERO

pytestmark = pytest.mark.unit

NOW = datetime(2026, 7, 27, 12, 0, tzinfo=UTC)


# --- Reason metadata -----------------------------------------------------------


def test_every_reason_code_has_metadata() -> None:
    """A code with no template renders as a raw identifier in the product."""
    assert set(REASON_META) == set(ReasonCode)


@pytest.mark.parametrize("code", list(ReasonCode))
def test_metadata_is_well_formed(code: ReasonCode) -> None:
    meta = meta_for(code)
    assert isinstance(meta.severity, Severity)
    assert isinstance(meta.agent, AgentId)
    assert meta.template.strip()
    assert meta.template.endswith(".")


def test_critical_codes_are_reserved_for_real_danger() -> None:
    """Severity drives the headline; inflating it would drown genuine alarms."""
    critical = {code for code in ReasonCode if meta_for(code).severity is Severity.CRITICAL}
    assert critical == {
        ReasonCode.LIQUIDITY_DRAWDOWN_ACUTE,
        ReasonCode.DEPTH_RATIO_CRITICAL,
        ReasonCode.POOL_INACTIVE,
    }


# --- Explanation assembly ------------------------------------------------------


def test_reasons_are_ordered_most_severe_first() -> None:
    explanation = build_explanation(
        (
            ReasonCode.MOMENTUM_STEADY,  # info
            ReasonCode.LIQUIDITY_THIN,  # caution
            ReasonCode.POOL_INACTIVE,  # critical
            ReasonCode.LIQUIDITY_DEEP,  # positive
        )
    )
    assert explanation.reasons == (
        ReasonCode.POOL_INACTIVE,
        ReasonCode.LIQUIDITY_THIN,
        ReasonCode.LIQUIDITY_DEEP,
        ReasonCode.MOMENTUM_STEADY,
    )
    assert explanation.primary is ReasonCode.POOL_INACTIVE


def test_ties_keep_emission_order() -> None:
    """Determinism: equal severities must not reorder run to run."""
    codes = (ReasonCode.MOMENTUM_STEADY, ReasonCode.TOKEN_TOO_NEW)
    assert build_explanation(codes).reasons == codes


def test_duplicates_collapse_to_first_occurrence() -> None:
    explanation = build_explanation(
        (ReasonCode.LIQUIDITY_THIN, ReasonCode.MOMENTUM_STEADY, ReasonCode.LIQUIDITY_THIN)
    )
    assert explanation.reasons.count(ReasonCode.LIQUIDITY_THIN) == 1


def test_an_empty_explanation_has_no_headline() -> None:
    explanation = build_explanation(())
    assert explanation.reasons == ()
    assert explanation.primary is None
    assert explanation.primary_agent is None
    assert explanation.primary_severity is None


def test_the_headline_carries_its_owning_agent() -> None:
    """Observatory Log attribution: "Sentinel detected ..." comes from here."""
    explanation = build_explanation((ReasonCode.LIQUIDITY_DRAWDOWN_ACUTE,))
    assert explanation.primary_agent is AgentId.SENTINEL
    assert explanation.primary_severity is Severity.CRITICAL


# --- Freshness (read-time) -----------------------------------------------------


def test_a_just_captured_snapshot_is_fully_fresh() -> None:
    assert freshness_of(NOW, now=NOW, tier_interval_seconds=300) == ONE


def test_freshness_decays_with_age() -> None:
    recent = freshness_of(NOW - timedelta(seconds=150), now=NOW, tier_interval_seconds=300)
    older = freshness_of(NOW - timedelta(seconds=600), now=NOW, tier_interval_seconds=300)
    assert ONE > recent > older > ZERO


def test_freshness_bottoms_out_after_three_intervals() -> None:
    assert (
        freshness_of(NOW - timedelta(seconds=900), now=NOW, tier_interval_seconds=300) == ZERO
    )
    assert freshness_of(NOW - timedelta(days=7), now=NOW, tier_interval_seconds=300) == ZERO


def test_freshness_is_relative_to_the_token_s_own_tier() -> None:
    """Two minutes is nothing for a six-hourly token, a missed beat for a fresh one."""
    age = timedelta(minutes=2)
    fast_tier = freshness_of(NOW - age, now=NOW, tier_interval_seconds=30)
    slow_tier = freshness_of(NOW - age, now=NOW, tier_interval_seconds=21600)
    assert slow_tier > fast_tier


def test_freshness_without_a_snapshot_is_zero() -> None:
    assert freshness_of(None, now=NOW, tier_interval_seconds=300) == ZERO


def test_freshness_with_no_interval_is_zero() -> None:
    assert freshness_of(NOW, now=NOW, tier_interval_seconds=0) == ZERO


def test_a_snapshot_from_the_future_is_treated_as_current() -> None:
    """A provider clock running ahead is not a reason to discount the data."""
    assert freshness_of(NOW + timedelta(minutes=5), now=NOW, tier_interval_seconds=300) == ONE


# --- Confidence ----------------------------------------------------------------


def test_confidence_is_evidence_discounted_by_freshness() -> None:
    assert confidence_of(Decimal(64), ONE) == Decimal(64)
    assert confidence_of(Decimal(64), ZERO) == ZERO


def test_stale_data_reduces_confidence_without_touching_evidence() -> None:
    """The split that stops a stalled token reading as confidently scored."""
    evidence = Decimal(65)
    fresh = confidence_of(evidence, ONE)
    stale = confidence_of(evidence, Decimal("0.25"))
    assert fresh > stale > ZERO


def test_confidence_discounts_gently() -> None:
    """Square root: a slightly stale observation is still informative."""
    assert confidence_of(HUNDRED, Decimal("0.25")) == Decimal(50)


def test_confidence_stays_within_range() -> None:
    for step in range(0, 101):
        value = confidence_of(HUNDRED, Decimal(step) / HUNDRED)
        assert ZERO <= value <= HUNDRED
