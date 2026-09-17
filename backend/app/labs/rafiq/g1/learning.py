"""LEARNING — G1 learns from the market and adapts its own behaviour.

This module is the learning layer. It watches what actually happens to the
tokens G1 trades and moves G1's parameters when the evidence says they are
wrong. Below: the three things "learning" can mean here, which two are live in
this file, and why the third is waiting on two missing columns rather than on
effort.

THREE DIFFERENT THINGS GET CALLED "LEARNING"
----------------------------------------------
1. LEARNING WHICH TOKEN TO BUY — a classifier over entry features.
   NOT BUILT, and the reason is a measurement rather than a preference. Over
   559 v2 trades, two-sided permutation tests (20,000 iterations) comparing
   total losses against survivors:

        entry_liquidity_usd     p = 0.3914
        entry slippage %        p = 0.4517
        detect -> open delay    p = 0.4500
        cost_basis              p = 0.1133

   Nothing separates. A model trained on these features would fit noise and
   report confidence while doing it, which is worse than no model. The two
   features that plausibly WOULD separate — top-10 holder concentration and LP
   lock status — are not recorded anywhere yet. Record them, and this section
   becomes buildable.

2. LEARNING WHETHER YOUR OWN RULES ARE MISCALIBRATED — buildable now, and
   built below. G1 has exactly one parameter that is a guess rather than a
   measurement: the abandon rule (out at 10 minutes unless up 8%). Every other
   constant traces to an observed distribution. `AbandonCalibrator` watches
   what abandoned tokens did afterwards and moves that threshold when the
   evidence says it is wrong.

3. LEARNING WHAT THE MARKET IS DOING RIGHT NOW — buildable now, and built
   below. `RegimeMonitor` tracks whether the feed is producing runners at all.
   When it is not, the correct response is to trade less, not to trade
   differently.

WHY THIS IS BOUNDED AND SLOW
------------------------------
An adaptive system that retunes on small samples is the exact failure this
project has already walked into twice — a $300k liquidity floor fitted to 28
trades from a single day, and a positive F2 read fitted to 14. So every
adjustment here requires a minimum sample, must survive a significance check
rather than a point estimate, is bounded to a range, moves in small steps, and
writes an audit line saying what changed and on what evidence.

It will adapt over days, not minutes. That is deliberate.
"""
from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

# --- bounds. The calibrator may move inside these and nowhere else. ---------
ABANDON_GAIN_MIN = Decimal("0.03")
ABANDON_GAIN_MAX = Decimal("0.15")
ABANDON_STEP = Decimal("0.01")

#: No adjustment on fewer observations than this, ever.
MIN_SAMPLE = 40

#: Two-proportion z-test threshold. A point estimate is not evidence.
SIGNIFICANCE_Z = 1.96

#: Rolling window for regime. Long enough to be a regime, short enough to move.
REGIME_WINDOW = 120


@dataclass(frozen=True)
class Adjustment:
    """Every parameter change, with the evidence that justified it."""

    at: datetime
    parameter: str
    old_value: Decimal
    new_value: Decimal
    reason: str
    sample_size: int
    z_score: float


def _two_proportion_z(hits_a: int, n_a: int, hits_b: int, n_b: int) -> float:
    """z for the difference of two rates. 0.0 when it cannot be computed."""
    if n_a == 0 or n_b == 0:
        return 0.0
    p_a, p_b = hits_a / n_a, hits_b / n_b
    pooled = (hits_a + hits_b) / (n_a + n_b)
    denom = pooled * (1 - pooled) * (1 / n_a + 1 / n_b)
    if denom <= 0:
        return 0.0
    return (p_a - p_b) / math.sqrt(denom)


@dataclass
class AbandonCalibrator:
    """Is G1 cutting flat tokens too early, or not early enough?

    Feed it every closed trade. It compares two rates:

        * of tokens G1 ABANDONED, how many later ran (it cut a winner)
        * of tokens G1 HELD past the checkpoint, how many later died

    If abandoned tokens recover significantly more often than held tokens die,
    the threshold is too aggressive and loosens. If the reverse, it tightens.
    When neither is significant it does not move, which is the common case and
    the correct one.
    """

    gain_threshold: Decimal = Decimal("0.08")
    _abandoned: deque = field(default_factory=lambda: deque(maxlen=400))
    _held: deque = field(default_factory=lambda: deque(maxlen=400))
    adjustments: list = field(default_factory=list)

    def record_abandoned(self, later_peak_multiple: float) -> None:
        """A trade the abandon rule closed. `later_peak_multiple` is the best
        the token reached afterwards, 1.0 if it never recovered."""
        self._abandoned.append(later_peak_multiple >= 1.30)

    def record_held(self, went_to_zero: bool) -> None:
        """A trade that passed the checkpoint and was kept."""
        self._held.append(bool(went_to_zero))

    @property
    def sample_size(self) -> int:
        return len(self._abandoned) + len(self._held)

    def evaluate(self, now: datetime):
        """Returns an Adjustment if the evidence supports one, else None."""
        n_a, n_h = len(self._abandoned), len(self._held)
        if self.sample_size < MIN_SAMPLE or n_a == 0 or n_h == 0:
            return None

        cut_winners = sum(self._abandoned)
        kept_losers = sum(self._held)
        z = _two_proportion_z(cut_winners, n_a, kept_losers, n_h)

        if abs(z) < SIGNIFICANCE_Z:
            return None

        old = self.gain_threshold
        if z > 0:
            # Abandoned tokens recover more than held tokens die -> too eager.
            new = min(ABANDON_GAIN_MAX, old + ABANDON_STEP)
            why = (f"abandoned tokens later ran {100*cut_winners/n_a:.0f}% of the "
                   f"time vs {100*kept_losers/n_h:.0f}% of held tokens dying - "
                   f"cutting winners, loosening")
        else:
            new = max(ABANDON_GAIN_MIN, old - ABANDON_STEP)
            why = (f"held tokens died {100*kept_losers/n_h:.0f}% of the time vs "
                   f"{100*cut_winners/n_a:.0f}% of abandoned ones running - "
                   f"holding losers, tightening")

        if new == old:
            return None   # already at a bound; do not log a no-op

        self.gain_threshold = new
        adj = Adjustment(now, "abandon_gain_threshold", old, new, why,
                         self.sample_size, round(z, 3))
        self.adjustments.append(adj)
        self._abandoned.clear()
        self._held.clear()
        return adj


@dataclass
class RegimeMonitor:
    """Is the feed producing runners at all right now?

    Not a prediction about any token — a description of the population. When
    the rate of tokens reaching +30% collapses against the trailing baseline,
    the right response is to size down and trade less, because the tail G1
    depends on is not there this week.
    """

    window: int = REGIME_WINDOW
    _recent: deque = field(default_factory=lambda: deque(maxlen=REGIME_WINDOW))
    _baseline_rate: float | None = None

    def record(self, reached_take_profit: bool) -> None:
        self._recent.append(bool(reached_take_profit))

    @property
    def sample_size(self) -> int:
        return len(self._recent)

    @property
    def runner_rate(self):
        if not self._recent:
            return None
        return sum(self._recent) / len(self._recent)

    def set_baseline(self, rate: float) -> None:
        self._baseline_rate = rate

    def assessment(self):
        """(size_multiplier, note). 1.0 means trade normally."""
        if self.sample_size < MIN_SAMPLE:
            return 1.0, f"regime unknown ({self.sample_size}/{MIN_SAMPLE} observations)"
        rate = self.runner_rate
        if self._baseline_rate is None:
            self._baseline_rate = rate
            return 1.0, f"baseline set at {100*rate:.0f}% runner rate"

        z = _two_proportion_z(sum(self._recent), len(self._recent),
                              int(self._baseline_rate * self.window), self.window)
        if z < -SIGNIFICANCE_Z:
            return 0.5, (f"runner rate {100*rate:.0f}% vs baseline "
                         f"{100*self._baseline_rate:.0f}% (z={z:.2f}) - "
                         f"halving size, the tail is not there")
        if z > SIGNIFICANCE_Z:
            return 1.0, (f"runner rate {100*rate:.0f}% above baseline "
                         f"(z={z:.2f}) - normal size, never scaling up on a "
                         f"hot streak")
        return 1.0, f"regime normal ({100*rate:.0f}% runner rate, z={z:.2f})"


@dataclass
class Learning:
    """The learning layer. Wire this to G1 and call `on_trade_closed` for every
    closed trade; read `current_parameters()` before every entry."""

    abandon: AbandonCalibrator = field(default_factory=AbandonCalibrator)
    regime: RegimeMonitor = field(default_factory=RegimeMonitor)

    def on_trade_closed(self, *, exit_reason: str, went_to_zero: bool,
                        later_peak_multiple: float, reached_take_profit: bool,
                        now: datetime):
        if exit_reason == "abandon_flat":
            self.abandon.record_abandoned(later_peak_multiple)
        else:
            self.abandon.record_held(went_to_zero)
        self.regime.record(reached_take_profit)
        return self.abandon.evaluate(now)

    def current_parameters(self) -> dict:
        mult, note = self.regime.assessment()
        return {
            "abandon_gain_threshold": float(self.abandon.gain_threshold),
            "size_multiplier": mult,
            "regime_note": note,
            "abandon_sample": self.abandon.sample_size,
            "adjustments_made": len(self.abandon.adjustments),
        }
