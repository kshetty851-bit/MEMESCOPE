"""Tests for the shared mechanisms and the per-book learning engine.

Many of these assert that learning does NOT fire. That is deliberate: this
project has twice been burned by fitting to a small sample.
"""
from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from app.labs.rafiqv2.learning import (LOCK_GIVEBACK_MAX, LOCK_GIVEBACK_MIN, MIN_SAMPLE,
                      Learning, TradeRecord)
from app.labs.rafiqv2.strategy_common import (FRICTION_PCT, DeathRateBreaker, EquityRatchet,
                             FastRugGate, ProfitLock)

T0 = datetime(2026, 9, 19, 12, 0, 0)
def at(**kw): return T0 + timedelta(**kw)


class TestFastRugGates:
    def test_a_token_down_three_percent_at_thirty_seconds_is_cut(self):
        assert FastRugGate().check(age=timedelta(seconds=30),
                                   multiple=Decimal("0.96")) == "rug_30s"

    def test_nothing_fires_before_the_first_checkpoint(self):
        assert FastRugGate().check(age=timedelta(seconds=29),
                                   multiple=Decimal("0.50")) is None

    def test_clearing_one_checkpoint_is_not_a_pass_for_the_next(self):
        """G1's whole loss: 3 tokens cleared +8% at 10m and died by 45m."""
        g = FastRugGate()
        assert g.check(age=timedelta(minutes=10), multiple=Decimal("1.09")) is None
        assert g.check(age=timedelta(minutes=20),
                       multiple=Decimal("1.09")) == "abandon_20m"

    def test_a_move_that_continues_is_kept(self):
        assert FastRugGate().check(age=timedelta(minutes=20),
                                   multiple=Decimal("1.20")) is None

    def test_the_latest_checkpoint_governs(self):
        g = FastRugGate()
        assert g.check(age=timedelta(minutes=30),
                       multiple=Decimal("1.02")) == "abandon_20m"


class TestProfitLock:
    def test_it_does_not_arm_below_friction(self):
        lock = ProfitLock()
        lock.observe(Decimal("1.02"))
        assert lock.armed is False

    def test_clearing_friction_means_never_red_again(self):
        lock = ProfitLock()
        lock.observe(Decimal("1.04"))
        assert lock.armed is True
        assert lock.floor_multiple == 1 + FRICTION_PCT
        assert lock.breached(Decimal("1.00")) is True

    def test_a_winner_cannot_round_trip_to_a_loss(self):
        """A 45% trail would let +30% come back to -1%. This will not."""
        lock = ProfitLock()
        lock.observe(Decimal("1.30"))
        assert lock.floor_multiple == Decimal("1.14")
        assert lock.breached(Decimal("1.20")) is False
        assert lock.breached(Decimal("1.14")) is True

    def test_the_floor_never_falls(self):
        lock = ProfitLock()
        lock.observe(Decimal("1.60"))
        floor = lock.floor_multiple
        lock.observe(Decimal("1.05"))
        assert lock.floor_multiple == floor

    def test_a_big_runner_locks_most_of_it(self):
        lock = ProfitLock()
        lock.observe(Decimal("2.50"))
        assert lock.floor_multiple == Decimal("1.70")

    def test_it_cannot_force_a_sale(self):
        assert not hasattr(ProfitLock(), "sell")
        assert not hasattr(ProfitLock(), "force_close")


class TestDeathRateBreaker:
    def test_it_fires_on_the_eighth_consecutive_death(self):
        b = DeathRateBreaker()
        fired = None
        for i in range(18):
            b.record(token_died=True, now=at(minutes=i))
            if fired is None and b.check(at(minutes=i))[0]:
                fired = i + 1
        assert fired == 8

    def test_a_healthy_window_does_not_halt(self):
        b = DeathRateBreaker()
        for i in range(20):
            b.record(token_died=(i % 4 == 0), now=at(minutes=i))
        assert b.check(at(minutes=21))[0] is False

    def test_the_halt_expires(self):
        b = DeathRateBreaker()
        for i in range(8):
            b.record(token_died=True, now=at(minutes=i))
        assert b.check(at(hours=7))[0] is False


class TestLearningIsPerBook:
    def test_two_books_keep_separate_evidence(self):
        a, g = Learning(book="A2"), Learning(book="G2")
        a.on_entry(TradeRecord("m1", T0, Decimal(10), None, None))
        a.on_exit("m1", closed_at=T0, exit_reason="rug_30s",
                  net_return=Decimal("-0.03"), peak_multiple=Decimal(1),
                  token_died=True)
        assert a.current_parameters()["closed_trades"] == 1
        assert g.current_parameters()["closed_trades"] == 0

    def test_the_book_name_is_on_every_adjustment(self):
        """Cut tokens nearly always recovered; kept ones nearly never died.
        That is the gates cutting winners, and it must loosen them."""
        lrn = Learning(book="C2")
        for i in range(60):
            cut = i % 2 == 0
            lrn.on_entry(TradeRecord(f"m{i}", T0, Decimal(10), None, None))
            lrn.on_exit(f"m{i}", closed_at=T0,
                        exit_reason="rug_30s" if cut else "stop",
                        net_return=Decimal("-0.5"),
                        peak_multiple=Decimal("2.0") if cut else Decimal("1.0"),
                        token_died=False if cut else False)
        assert lrn.adjustments, "expected at least one adjustment"
        assert all(a.book == "C2" for a in lrn.adjustments)
        assert lrn.rug.strictness < 0, "should have loosened"


class TestLearningOnEveryBuy:
    def test_an_open_trade_is_tracked_until_it_closes(self):
        lrn = Learning(book="G2")
        lrn.on_entry(TradeRecord("abc", T0, Decimal(10), Decimal(250_000), None))
        assert lrn.current_parameters()["open_trades"] == 1
        lrn.on_exit("abc", closed_at=at(minutes=5), exit_reason="scale_out",
                    net_return=Decimal("0.25"), peak_multiple=Decimal("1.3"),
                    token_died=False)
        p = lrn.current_parameters()
        assert p["open_trades"] == 0 and p["closed_trades"] == 1

    def test_hold_time_is_recorded(self):
        lrn = Learning(book="G2")
        lrn.on_entry(TradeRecord("abc", T0, Decimal(10), None, None))
        lrn.on_exit("abc", closed_at=at(seconds=45), exit_reason="rug_30s",
                    net_return=Decimal("-0.03"), peak_multiple=Decimal("1.0"),
                    token_died=True)
        assert lrn.history[0].hold_seconds == 45.0


class TestItRefusesToLearnFromNoise:
    def test_nothing_moves_below_the_minimum_sample(self):
        lrn = Learning(book="A2")
        for i in range(10):
            lrn.on_entry(TradeRecord(f"m{i}", T0, Decimal(10), None, None))
            lrn.on_exit(f"m{i}", closed_at=T0, exit_reason="rug_30s",
                        net_return=Decimal("-0.03"), peak_multiple=Decimal("5.0"),
                        token_died=False)
        assert lrn.current_parameters()["adjustments_made"] == 0

    def test_nothing_moves_without_significance(self):
        lrn = Learning(book="A2")
        for i in range(80):
            lrn.on_entry(TradeRecord(f"m{i}", T0, Decimal(10), None, None))
            lrn.on_exit(f"m{i}", closed_at=T0,
                        exit_reason="rug_30s" if i % 2 else "stop",
                        net_return=Decimal("-0.1"),
                        peak_multiple=Decimal("1.3") if i % 4 < 2 else Decimal("1.0"),
                        token_died=(i % 4 < 2))
        assert lrn.current_parameters()["adjustments_made"] == 0

    def test_the_lock_stays_inside_its_bounds(self):
        lrn = Learning(book="D2")
        lrn.lock.giveback = LOCK_GIVEBACK_MAX
        for i in range(80):
            lrn.on_entry(TradeRecord(f"m{i}", T0, Decimal(10), None, None))
            lrn.on_exit(f"m{i}", closed_at=T0, exit_reason="lock",
                        net_return=Decimal("0.05"), peak_multiple=Decimal("9.0"),
                        token_died=False, lock_armed=(i % 2 == 0))
        assert lrn.lock.giveback <= LOCK_GIVEBACK_MAX
        assert lrn.lock.giveback >= LOCK_GIVEBACK_MIN

    def test_size_never_scales_up_on_a_hot_streak(self):
        lrn = Learning(book="B2")
        lrn.regime.set_baseline(0.10)
        for i in range(120):
            lrn.regime.record(reached_take_profit=True)
        assert lrn.current_parameters()["size_multiplier"] == 1.0

    def test_size_halves_when_the_tail_disappears(self):
        lrn = Learning(book="B2")
        lrn.regime.set_baseline(0.40)
        for i in range(120):
            lrn.regime.record(reached_take_profit=False)
        assert lrn.current_parameters()["size_multiplier"] == 0.5


class TestAuditTrail:
    def test_every_change_is_logged_with_its_evidence(self):
        lrn = Learning(book="E2")
        for i in range(60):
            cut = i % 2 == 0
            lrn.on_entry(TradeRecord(f"m{i}", T0, Decimal(10), None, None))
            lrn.on_exit(f"m{i}", closed_at=T0,
                        exit_reason="rug_30s" if cut else "stop",
                        net_return=Decimal("-0.5"),
                        peak_multiple=Decimal("1.0") if cut else Decimal("1.0"),
                        token_died=False if cut else True)
        assert lrn.audit_log()
        line = lrn.audit_log()[0]
        assert "E2" in line and "n=" in line and "z=" in line


class TestTheBoundaryIsStillDocumented:
    def test_the_module_says_what_it_cannot_learn(self):
        from app.labs.rafiqv2 import learning
        doc = learning.__doc__
        assert "0.3914" in doc and "0.4517" in doc
        assert "holder" in doc and "LP lock status" in doc
        assert "18 and 18 died" in doc
        assert "learn noise" in doc
