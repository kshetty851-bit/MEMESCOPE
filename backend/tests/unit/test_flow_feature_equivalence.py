"""The Lab's `sell_share_15m` and the paper wallet's must be the same number.

The flow-filtered paper strategy is V6-07 plus one condition, and its whole
claim is that it can be compared against V6-07 running unfiltered in the Lab.
That comparison is only meaningful while both sides compute the feature
identically.

They do NOT share code. `app.flow_features` was written for the paper wallet;
`lab/service.py` still computes its own, and deliberately so — the Lab was
running a live tournament and the instruction was not to touch it. So this is
two implementations that agree, and nothing in either runtime enforces that.

This test is the enforcement, and it enforces the two halves UNEQUALLY. That
distinction is load-bearing, so it is stated rather than left to be discovered:

  THE HELPER IS PINNED AUTOMATICALLY. `_delta` is imported from
  `app.lab.service`, so editing the clamp compares the real edited function and
  fails immediately.

  THE FORMULA IS PINNED BY CONVENTION. `_lab_sell_share` below is a
  TRANSCRIPTION. If somebody changes the ratio in `lab/service.py`, or its
  `(db + ds) > 0` branch, the Lab moves and this test keeps comparing
  `flow_features` against the stale transcription — and passes.

The comment on `_lab_sell_share` is the mitigation, and it is the best
available while the Lab must not be touched: pinning the formula properly means
`lab/service.py` importing `flow_features`, which would have meant editing a
module inside a running tournament.

**If the Lab is ever unfrozen, that is the moment to make `lab/service.py`
import `flow_features` and delete the transcription entirely.**

Both this file and the unequal-enforcement distinction above came out of review
by a second session: first that the original claim of "cannot drift apart" was
false because restating IS reimplementing, then that the fix itself claimed
more enforcement than it delivers.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app import flow_features
from app.lab.service import _delta as lab_delta

pytestmark = pytest.mark.unit


class _Snap:
    def __init__(self, buys, sells):
        self.buy_count_24h = buys
        self.sell_count_24h = sells


def _lab_sell_share(last: _Snap, prev15: _Snap) -> Decimal | None:
    """The Lab's own path, transcribed from `lab/service.py`.

    Kept as a transcription rather than an import because the Lab computes it
    inline inside `LabService._features`, mid-query, and cannot be called
    without a session and a token. If that block is ever edited, THIS FUNCTION
    IS THE ONE TO UPDATE — and the assertions below will then tell you whether
    `app.flow_features` still matches.
    """
    db = lab_delta(last.buy_count_24h, prev15.buy_count_24h)
    ds = lab_delta(last.sell_count_24h, prev15.sell_count_24h)
    if db is not None and ds is not None and (db + ds) > 0:
        return Decimal(ds) / Decimal(db + ds)
    return None


CASES = [
    ("ordinary mix", _Snap(100, 50), _Snap(90, 40)),
    ("all buys", _Snap(100, 40), _Snap(90, 40)),
    ("all sells", _Snap(90, 50), _Snap(90, 40)),
    ("no trades in the window", _Snap(10, 5), _Snap(10, 5)),
    ("buy counter ticks backwards", _Snap(80, 50), _Snap(90, 40)),
    ("sell counter ticks backwards", _Snap(100, 30), _Snap(90, 40)),
    ("both counters backwards", _Snap(80, 30), _Snap(90, 40)),
    ("buy counter missing", _Snap(None, 50), _Snap(90, 40)),
    ("sell counter missing", _Snap(100, None), _Snap(90, 40)),
    ("earlier counter missing", _Snap(100, 50), _Snap(None, 40)),
    ("large counters, one trade apart", _Snap(1_000_000, 999_999), _Snap(999_999, 999_998)),
    ("single trade in the window", _Snap(1, 0), _Snap(0, 0)),
]


@pytest.mark.parametrize(
    ("label", "last", "earlier"), CASES, ids=[c[0] for c in CASES]
)
def test_the_two_implementations_agree_exactly(label, last, earlier) -> None:
    """Exact Decimal equality, not approximate.

    A share that differs in the last place is a rule with a different
    threshold, and the threshold is the entire experiment.
    """
    assert flow_features.trade_flow(last, earlier).sell_share == _lab_sell_share(
        last, earlier
    ), label


def test_the_clamp_helpers_agree() -> None:
    """`counter_delta` is the Lab's `_delta` under another name."""
    for now, then in [(100, 90), (90, 100), (0, 0), (None, 1), (1, None), (5, 5)]:
        assert flow_features.counter_delta(now, then) == lab_delta(now, then)


def test_neither_side_turns_an_empty_window_into_zero() -> None:
    """The branch most likely to be "simplified" by someone who does not know
    the other copy exists. An untraded token is not a token nobody is selling,
    and a strategy filtering on "sell share is low" must not be handed a zero
    it can pass."""
    last, earlier = _Snap(10, 5), _Snap(10, 5)
    assert _lab_sell_share(last, earlier) is None
    assert flow_features.trade_flow(last, earlier).sell_share is None
