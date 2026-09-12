"""Strategy F.

The interesting tests here are not the gate mechanics — they are the
assertions that F does NOT claim an edge, because the previous draft did and
the claim did not replicate. If someone later tunes a threshold to make F
look profitable, `test_f_does_not_claim_an_edge` should be what stops them.
"""
from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.labs.rafiq.strategies.strategy_f2 import (
    FLOOR_AT_START,
    FLOOR_WITH_ROOM,
    LOSS_BOUNDED,
    MAX_TRADES_PER_DAY,
    MIN_LIQUIDITY_USD,
    ZERO_AVOIDANCE,
    DailyTradeCap,
    EquityFloor,
    admits,
    may_enter,
)


class TestEntryGate:
    def test_unknown_liquidity_is_refused_not_assumed(self):
        ok, reason, checks = admits(None, 500_000)
        assert ok is False
        assert "unknown" in reason
        assert checks == []

    def test_missing_market_cap_is_reported_not_silently_passed(self):
        """v2 has no market-cap column. The gate must say it could not run
        that check rather than let the caller believe it did."""
        ok, reason, checks = admits(250_000, None)
        assert ok is True
        assert "market_cap" not in checks
        assert "liquidity" in checks

    def test_market_cap_is_enforced_when_present(self):
        ok, reason, checks = admits(250_000, 150_000)
        assert ok is False and "market cap" in reason
        assert "market_cap" in checks

    @pytest.mark.parametrize("liq,expected", [
        (199_999, False), (200_000, True), (250_000, True),
    ])
    def test_liquidity_floor_boundary(self, liq, expected):
        assert admits(liq, 250_000)[0] is expected


class TestEquityFloor:
    def test_floor_halts_at_or_below(self):
        f = EquityFloor(floor_usd=Decimal(900))
        assert f.breached(Decimal("900.00")) is True
        assert f.breached(Decimal("899.99")) is True
        assert f.breached(Decimal("900.01")) is False

    def test_floor_at_start_halts_on_first_dollar_of_drawdown(self):
        """Documented behaviour, not a bug. The user asked for $1,000 on a
        $1,000 book; this is what that means."""
        halt, why = FLOOR_AT_START.check(Decimal("999.99"))
        assert halt is True and "hard floor" in why

    def test_disabled_floor_never_halts(self):
        f = EquityFloor(floor_usd=Decimal(900), enabled=False)
        assert f.breached(Decimal(1)) is False
        assert f.check(Decimal(1)) == (False, None)

    def test_floor_does_not_expose_a_force_close(self):
        """Force-closing on breach would sell into the drained pools that
        produce the -100% rows. The API must not offer it."""
        assert not hasattr(FLOOR_WITH_ROOM, "force_close")
        assert not hasattr(FLOOR_WITH_ROOM, "liquidate")


class TestDailyTradeCap:
    def test_cap_blocks_after_limit(self):
        cap, d = DailyTradeCap(max_per_day=3), date(2026, 9, 12)
        for _ in range(3):
            assert cap.allows(d) is True
            cap.record(d)
        assert cap.allows(d) is False
        assert cap.remaining(d) == 0

    def test_cap_resets_on_a_new_day(self):
        cap, d1, d2 = DailyTradeCap(max_per_day=2), date(2026, 9, 12), date(2026, 9, 13)
        cap.record(d1); cap.record(d1)
        assert cap.allows(d1) is False
        assert cap.allows(d2) is True
        assert cap.remaining(d2) == 2

    def test_zero_cap_blocks_everything(self):
        assert DailyTradeCap(max_per_day=0).allows(date(2026, 9, 12)) is False


class TestMayEnter:
    def test_floor_breach_is_reported_before_instrument_failures(self):
        """A halted book reports the halt, even when the token would also
        have failed its own gate. Otherwise the operator reads 'thin pool'
        and never learns the book is stopped."""
        ok, why = may_enter(equity_usd=Decimal(500), today=date(2026, 9, 12),
                            liquidity_usd=1_000, floor=FLOOR_WITH_ROOM)
        assert ok is False and "hard floor" in why

    def test_happy_path(self):
        ok, why = may_enter(equity_usd=Decimal(1000), today=date(2026, 9, 12),
                            liquidity_usd=250_000, market_cap_usd=250_000)
        assert ok is True and why is None


class TestSizing:
    def test_position_is_one_percent_of_a_thousand_dollar_book(self):
        """A2, D2 and E2 ran $50 on $1,000. At an 18% zero rate that is 90%
        of the book consumed by zeros per 100 trades; at $10 it is 18%."""
        assert LOSS_BOUNDED.sizing.max_notional_usd == Decimal(10)
        assert LOSS_BOUNDED.sizing.risk_per_trade == Decimal("0.01")

    def test_exits_are_e2s_unchanged(self):
        """E2 had the best survivor return (+14.9%). The evidence says exits
        are not where the loss is, so F must not fiddle with them."""
        e = LOSS_BOUNDED.exits
        assert e.take_profit_mult == Decimal("1.30")
        assert e.stop_mult == Decimal("0.88")
        assert e.trailing_frac == Decimal("0.20")
        assert e.max_hold == timedelta(hours=8)


class TestCalibrationAgainstProductionData:
    """Constants that trace to a measurement. If one of these fails, the
    measurement changed and the docstring is now lying."""

    def test_liquidity_floor_sits_where_the_signal_dies(self):
        """Karthik: liquidity separates zeros at p=0.0001 overall, p=0.03
        above $100k, p=0.16 above $200k. $200k is the last useful point."""
        assert Decimal(200_000) == MIN_LIQUIDITY_USD

    def test_daily_cap_is_far_below_v2s_observed_rate(self):
        """v2 ran 376 gated trades in 0.64 days = 588/day. At a negative
        per-trade expectancy the trade count multiplies the loss, so the cap
        must be a small fraction of that rate, not a trim of it."""
        V2_OBSERVED_TRADES_PER_DAY = 588
        assert MAX_TRADES_PER_DAY <= V2_OBSERVED_TRADES_PER_DAY / 10

    def test_f_does_not_claim_an_edge(self):
        """The docstring must keep saying F cannot hit 5%/day. This test
        exists because the previous draft claimed a $300k edge that was
        n=28 from a single day with a CI straddling zero."""
        doc = __import__(
            "app.labs.rafiq.strategies.strategy_f2",
            fromlist=["x"]).__doc__
        assert "cannot return 5%/day" in doc
        assert "DID NOT REPLICATE" in doc
        assert "F is not a profit strategy" in doc

    def test_break_even_requires_roughly_halving_the_zero_rate(self):
        """E[r] = (1-p)*r_s - p = 0  =>  p* = r_s / (1 + r_s).
        Checked against the measured books."""
        measured = {            # book: (zero rate, survivor mean return)
            "A2": (0.100, 0.020), "B2": (0.152, 0.095), "C2": (0.222, 0.042),
            "E2": (0.200, 0.149), "Karthik": (0.466, 0.407),
        }
        for book, (p, r_s) in measured.items():
            tolerable = r_s / (1 + r_s)
            assert p > tolerable, f"{book} would already break even"
            assert (1 - p) * r_s - p < 0, f"{book} expectancy should be negative"

    def test_alias_kept_for_the_draft_name(self):
        assert ZERO_AVOIDANCE is LOSS_BOUNDED
