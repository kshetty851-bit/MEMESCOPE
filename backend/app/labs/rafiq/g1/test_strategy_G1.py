"""G1 tests. 45-minute box, uncapped runner, ratcheting floor."""
from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from app.labs.rafiq.g1.strategy_G1 import (
    ABANDON_AFTER,
    MAX_HOLD,
    RUNNER_TRAIL,
    SCALE_OUT_AT,
    SCALE_OUT_FRACTION,
    EquityRatchet,
    Exit,
    Position,
    admits,
    evaluate,
    position_size,
)

T0 = datetime(2026, 9, 17, 12, 0, 0)


def pos(entry="1.0"):
    return Position(entry_price=Decimal(entry), opened_at=T0, stake_usd=Decimal(10))


def at(minutes):
    return T0 + timedelta(minutes=minutes)


class TestMoonOrNothing:
    def test_flat_at_ten_minutes_is_abandoned(self):
        assert evaluate(pos(), Decimal("1.02"), at(10))[2] == Exit.ABANDON

    def test_moving_at_ten_minutes_is_held(self):
        assert evaluate(pos(), Decimal("1.09"), at(10)) is None

    def test_not_abandoned_before_ten_minutes(self):
        assert evaluate(pos(), Decimal("1.00"), at(9)) is None

    def test_a_collapsing_token_exits_as_a_stop_not_as_flat(self):
        """Order matters: 'abandon' and 'stop' mean different things in the
        ledger, and a token down 12% at minute 10 is a stop."""
        assert evaluate(pos(), Decimal("0.87"), at(10))[2] == Exit.STOP


class TestUncappedRunner:
    def test_scale_out_sells_three_quarters_at_thirty_percent(self):
        action, frac, reason = evaluate(pos(), Decimal("1.30"), at(15))
        assert (action, frac, reason) == ("sell", SCALE_OUT_FRACTION, Exit.SCALE_OUT)

    def test_scaling_out_returns_almost_the_whole_stake(self):
        """0.75 x 1.30 = 0.975. From here the remainder is a free ride."""
        assert SCALE_OUT_FRACTION * SCALE_OUT_AT >= Decimal("0.97")

    def test_the_runner_has_no_take_profit(self):
        """This is the point of G1. F2 capped at +30% and gave away tokens that
        reached +206% and +214%."""
        p = pos()
        p.scaled_out = True
        p.fraction_open = Decimal("0.25")
        for mult in ("1.5", "2.0", "3.0", "5.0"):
            p.peak_price = Decimal(mult)
            assert evaluate(p, Decimal(mult), at(20)) is None, f"capped at {mult}"

    def test_the_runner_exits_on_a_wide_trail(self):
        p = pos()
        p.scaled_out = True
        p.fraction_open = Decimal("0.25")
        p.peak_price = Decimal("3.0")
        assert evaluate(p, Decimal("1.60"), at(20))[2] == Exit.RUNNER_TRAIL

    def test_the_trail_is_wide_enough_to_sit_through_noise(self):
        """A 20% trail (F2's) exits on ordinary volatility. 45% does not."""
        assert RUNNER_TRAIL >= Decimal("0.40")
        p = pos()
        p.scaled_out = True
        p.fraction_open = Decimal("0.25")
        p.peak_price = Decimal("2.0")
        assert evaluate(p, Decimal("1.65"), at(20)) is None   # -17.5% off peak


class TestSpeed:
    def test_hard_box_at_forty_five_minutes(self):
        p = pos()
        p.scaled_out = True
        p.fraction_open = Decimal("0.25")
        p.peak_price = Decimal("1.40")
        assert evaluate(p, Decimal("1.35"), at(45))[2] == Exit.MAX_HOLD

    def test_the_box_is_far_shorter_than_every_other_book(self):
        """A2 12h, E2/F2 8h, C2/D2 4h, B2 2h. Time to +30% is p90 = 60 min."""
        assert MAX_HOLD <= timedelta(hours=1)
        assert ABANDON_AFTER < MAX_HOLD


class TestEquityRatchet:
    def test_the_floor_follows_the_book_up(self):
        r = EquityRatchet()
        assert r.update(Decimal(1100)) == Decimal("1067.00")
        assert r.update(Decimal(1400)) == Decimal("1358.00")

    def test_the_floor_never_comes_down(self):
        r = EquityRatchet()
        r.update(Decimal(1400))
        assert r.update(Decimal(1000)) == Decimal("1358.00")
        assert r.update(Decimal(500)) == Decimal("1358.00")

    def test_a_run_can_be_given_back_three_percent_and_no_more(self):
        r = EquityRatchet()
        r.update(Decimal(1400))
        assert r.check(Decimal(1360))[0] is False
        assert r.check(Decimal(1350))[0] is True

    def test_the_ratchet_never_force_closes(self):
        """Force-closing sells into pools that may already be dead — the exact
        mechanism behind this lab's -100% rows."""
        r = EquityRatchet()
        assert not hasattr(r, "force_close")
        assert not hasattr(r, "liquidate")
        assert r.check(Decimal(1))[1].endswith("no new entries")

    def test_the_reason_names_the_high_water_mark(self):
        r = EquityRatchet()
        r.update(Decimal(1400))
        assert "1,400" in r.check(Decimal(100))[1]


class TestSizingCompounds:
    def test_the_bet_grows_with_the_book(self):
        """A ratcheting book that never raises its bet never compounds."""
        assert position_size(Decimal(1000)) == Decimal("10.00")
        assert position_size(Decimal(2000)) == Decimal("20.00")

    def test_the_bet_shrinks_too(self):
        assert position_size(Decimal(500)) == Decimal("5.00")


class TestEntryGateUnchanged:
    def test_unknown_liquidity_is_refused(self):
        assert admits(None, 500_000)[0] is False

    def test_missing_market_cap_is_reported_not_assumed(self):
        ok, _, checks = admits(250_000, None)
        assert ok is True and "market_cap" not in checks

    @pytest.mark.parametrize("liq,ok", [(199_999, False), (200_000, True)])
    def test_liquidity_floor(self, liq, ok):
        assert admits(liq, 250_000)[0] is ok
