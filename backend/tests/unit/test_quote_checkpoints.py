"""Checkpoints are frozen data, not a tunable.

The V5 protocol fixes the decision moments at 5/10/20/30/45/60 minutes after
nursery entry and forbids choosing one after seeing outcomes. These tests pin
the constant and the grace window so a later edit is a visible, deliberate act
rather than a quiet drift that would invalidate the sealed OOS set.
"""

from __future__ import annotations

import pytest

from app.workers.research_tasks import CHECKPOINT_GRACE_MINUTES, CHECKPOINT_MINUTES

pytestmark = pytest.mark.unit


def test_checkpoints_match_the_frozen_protocol():
    assert CHECKPOINT_MINUTES == (5, 10, 20, 30, 45, 60)


def test_checkpoints_are_ordered_and_unique():
    assert list(CHECKPOINT_MINUTES) == sorted(set(CHECKPOINT_MINUTES))


def test_grace_never_overlaps_the_next_checkpoint():
    """A quote taken late must not be attributable to two checkpoints — the
    tightest gap in the frozen set is 5 minutes."""
    gaps = [b - a for a, b in zip(CHECKPOINT_MINUTES, CHECKPOINT_MINUTES[1:], strict=False)]
    assert CHECKPOINT_GRACE_MINUTES < min(gaps)
