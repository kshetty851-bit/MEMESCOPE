"""Unit tests for clone-risk banding.

Pure in, pure out — the module takes two integers and returns a verdict, so
every case here is a literal. No fixtures, no database, no clock.
"""

from __future__ import annotations

import pytest

from app.services.identity import (
    CloneRisk,
    IdentityConfidence,
    assess,
    unnamed,
)

pytestmark = pytest.mark.unit


def test_a_unique_name_carries_no_clone_risk() -> None:
    result = assess(sharing_name=1, discovered_before=0)
    assert result.clone_risk is CloneRisk.NONE
    assert result.identity_confidence is IdentityConfidence.HIGH
    assert result.is_earliest_known is True


def test_being_copied_is_not_the_same_as_copying() -> None:
    """First to a name that 148 others later reused.

    The risk belongs to the imitators, not to this token — but the name is
    still ambiguous to anyone searching, so confidence is not high.
    """
    result = assess(sharing_name=149, discovered_before=0)
    assert result.clone_risk is CloneRisk.LOW
    assert result.identity_confidence is IdentityConfidence.MODERATE
    assert result.is_earliest_known is True


def test_a_widely_reused_name_arriving_late_is_high_risk() -> None:
    """The live worst case: the 149th token called Puffins."""
    result = assess(sharing_name=149, discovered_before=148)
    assert result.clone_risk is CloneRisk.HIGH
    assert result.identity_confidence is IdentityConfidence.LOW
    assert result.is_earliest_known is False
    assert "149" in result.explanation
    assert "148" in result.explanation


def test_a_small_collision_arriving_late_is_moderate() -> None:
    result = assess(sharing_name=3, discovered_before=2)
    assert result.clone_risk is CloneRisk.MODERATE
    assert result.identity_confidence is IdentityConfidence.LOW


def test_the_contested_threshold_is_the_only_step_between_moderate_and_high() -> None:
    """Nine sharers is a collision; ten is a pattern. Locked so the band
    cannot drift without a test failing."""
    assert assess(sharing_name=9, discovered_before=1).clone_risk is CloneRisk.MODERATE
    assert assess(sharing_name=10, discovered_before=1).clone_risk is CloneRisk.HIGH


def test_an_unnamed_token_reports_that_it_was_checked() -> None:
    """ "Nothing to compare" and "not compared" are different facts."""
    result = unnamed()
    assert result.clone_risk is CloneRisk.NONE
    # Confidence is low, not high: we cannot confirm identity without a name.
    assert result.identity_confidence is IdentityConfidence.LOW
    assert "no name recorded" in result.explanation


def test_explanations_are_finished_sentences() -> None:
    """The client displays these verbatim and must never have to compose one."""
    for result in (
        assess(sharing_name=1, discovered_before=0),
        assess(sharing_name=149, discovered_before=0),
        assess(sharing_name=149, discovered_before=148),
        assess(sharing_name=3, discovered_before=2),
        unnamed(),
    ):
        assert result.explanation.endswith(".")
        # A count may legitimately open the sentence ("148 earlier tokens …").
        assert result.explanation[0].isupper() or result.explanation[0].isdigit()


def test_singular_and_plural_read_correctly() -> None:
    assert "1 earlier token already" in assess(sharing_name=2, discovered_before=1).explanation
    assert (
        "2 earlier tokens already" in assess(sharing_name=3, discovered_before=2).explanation
    )


def test_the_wording_never_claims_certainty_about_the_original() -> None:
    """MEMESCOPE sees only what it scanned, so it cannot know the true first."""
    earliest = assess(sharing_name=149, discovered_before=0)
    assert "cannot see tokens launched before" in earliest.explanation


@pytest.mark.parametrize(
    ("sharing", "before"),
    [(0, 0), (-1, 0), (5, -1), (5, 5), (5, 6)],
)
def test_impossible_counts_fail_loudly(sharing: int, before: int) -> None:
    """A miscounted collision would mislabel a token, so it raises."""
    with pytest.raises(ValueError):
        assess(sharing_name=sharing, discovered_before=before)
