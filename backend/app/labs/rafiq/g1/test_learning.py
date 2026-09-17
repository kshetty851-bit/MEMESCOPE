"""Tests for the learning layer.

Most of these assert that learning DOESN'T fire. That is the point: this
project has twice been burned by fitting to a small sample (a $300k liquidity
floor on n=28 from one day, a positive F2 read on 14 trades). A learner that
moves on weak evidence would automate that mistake instead of avoiding it.
"""
from datetime import datetime
from decimal import Decimal

import pytest

from app.labs.rafiq.g1.learning import (
    ABANDON_GAIN_MAX,
    ABANDON_GAIN_MIN,
    MIN_SAMPLE,
    SIGNIFICANCE_Z,
    AbandonCalibrator,
    Learning,
    RegimeMonitor,
)

NOW = datetime(2026, 9, 17, 12, 0, 0)


class TestItLearnsWhenTheEvidenceIsReal:
    def test_it_loosens_when_it_is_cutting_winners(self):
        c = AbandonCalibrator()
        before = c.gain_threshold
        for _ in range(60):
            c.record_abandoned(later_peak_multiple=2.0)   # every cut token ran
        for _ in range(60):
            c.record_held(went_to_zero=False)             # nothing held died
        adj = c.evaluate(NOW)
        assert adj is not None
        assert c.gain_threshold > before
        assert "cutting winners" in adj.reason

    def test_it_tightens_when_it_is_holding_losers(self):
        c = AbandonCalibrator()
        before = c.gain_threshold
        for _ in range(60):
            c.record_abandoned(later_peak_multiple=1.0)   # cuts were right
        for _ in range(60):
            c.record_held(went_to_zero=True)              # everything held died
        adj = c.evaluate(NOW)
        assert adj is not None
        assert c.gain_threshold < before
        assert "holding losers" in adj.reason

    def test_every_change_records_its_evidence(self):
        c = AbandonCalibrator()
        for _ in range(60):
            c.record_abandoned(2.0)
            c.record_held(False)
        adj = c.evaluate(NOW)
        assert adj.sample_size >= MIN_SAMPLE
        assert abs(adj.z_score) >= SIGNIFICANCE_Z
        assert adj.old_value != adj.new_value
        assert adj.parameter == "abandon_gain_threshold"


class TestItRefusesToLearnFromNoise:
    def test_no_adjustment_below_the_minimum_sample(self):
        """The $300k floor was fitted to 28 trades. This is the guard."""
        c = AbandonCalibrator()
        for _ in range(10):
            c.record_abandoned(5.0)      # extreme, but only 10 of them
            c.record_held(True)
        assert c.sample_size < MIN_SAMPLE
        assert c.evaluate(NOW) is None

    def test_no_adjustment_when_the_difference_is_not_significant(self):
        """A point estimate is not evidence."""
        c = AbandonCalibrator()
        for i in range(60):
            c.record_abandoned(2.0 if i % 2 else 1.0)   # 50%
            c.record_held(i % 2 == 0)                   # 50%
        assert c.evaluate(NOW) is None

    def test_it_never_moves_outside_its_bounds(self):
        c = AbandonCalibrator(gain_threshold=ABANDON_GAIN_MAX)
        for _ in range(60):
            c.record_abandoned(5.0)
            c.record_held(False)
        c.evaluate(NOW)
        assert c.gain_threshold <= ABANDON_GAIN_MAX

        c2 = AbandonCalibrator(gain_threshold=ABANDON_GAIN_MIN)
        for _ in range(60):
            c2.record_abandoned(1.0)
            c2.record_held(True)
        c2.evaluate(NOW)
        assert c2.gain_threshold >= ABANDON_GAIN_MIN

    def test_it_moves_one_step_at_a_time(self):
        """No jumping to the bound on one window of evidence."""
        c = AbandonCalibrator(gain_threshold=Decimal("0.08"))
        for _ in range(60):
            c.record_abandoned(10.0)
            c.record_held(False)
        c.evaluate(NOW)
        assert c.gain_threshold == Decimal("0.09")

    def test_evidence_is_cleared_after_a_change(self):
        """Otherwise the same window fires the same adjustment repeatedly."""
        c = AbandonCalibrator()
        for _ in range(60):
            c.record_abandoned(2.0)
            c.record_held(False)
        assert c.evaluate(NOW) is not None
        assert c.evaluate(NOW) is None


class TestRegimeLearning:
    def test_it_halves_size_when_the_tail_disappears(self):
        r = RegimeMonitor()
        r.set_baseline(0.40)
        for _ in range(120):
            r.record(reached_take_profit=False)
        mult, note = r.assessment()
        assert mult == 0.5
        assert "tail is not there" in note

    def test_it_never_scales_up_on_a_hot_streak(self):
        """F2 looked profitable on 14 lucky trades. Sizing up into that would
        have turned a streak into a drawdown."""
        r = RegimeMonitor()
        r.set_baseline(0.20)
        for _ in range(120):
            r.record(reached_take_profit=True)
        mult, note = r.assessment()
        assert mult == 1.0
        assert "never scaling up" in note

    def test_unknown_regime_trades_normally_and_says_so(self):
        r = RegimeMonitor()
        for _ in range(5):
            r.record(True)
        mult, note = r.assessment()
        assert mult == 1.0
        assert "regime unknown" in note


class TestWiring:
    def test_abandoned_and_held_trades_go_to_different_buckets(self):
        lrn = Learning()
        lrn.on_trade_closed(exit_reason="abandon_flat", went_to_zero=False,
                            later_peak_multiple=2.0, reached_take_profit=False, now=NOW)
        lrn.on_trade_closed(exit_reason="take_profit", went_to_zero=False,
                            later_peak_multiple=1.4, reached_take_profit=True, now=NOW)
        assert len(lrn.abandon._abandoned) == 1
        assert len(lrn.abandon._held) == 1

    def test_current_parameters_is_readable_before_every_entry(self):
        lrn = Learning()
        p = lrn.current_parameters()
        assert set(p) >= {"abandon_gain_threshold", "size_multiplier",
                          "regime_note", "adjustments_made"}
        assert p["size_multiplier"] == 1.0
        assert p["adjustments_made"] == 0

    def test_it_does_nothing_at_all_on_day_one(self):
        """40 trades minimum. G1 at 45-minute holds reaches that in hours, not
        weeks — but it is not zero."""
        lrn = Learning()
        for _ in range(20):
            lrn.on_trade_closed(exit_reason="abandon_flat", went_to_zero=False,
                                later_peak_multiple=3.0, reached_take_profit=False,
                                now=NOW)
        assert lrn.current_parameters()["adjustments_made"] == 0


class TestTheBoundaryIsDocumented:
    def test_the_module_says_what_it_cannot_learn(self):
        """Entry classification needs features that separate. None of the
        recorded ones do. The docstring must keep carrying the p-values so
        nobody adds a classifier over noise."""
        from app.labs.rafiq.g1 import learning
        doc = learning.__doc__
        assert "0.3914" in doc and "0.4517" in doc
        assert "top-10 holder concentration" in doc
        assert "would fit noise" in doc
