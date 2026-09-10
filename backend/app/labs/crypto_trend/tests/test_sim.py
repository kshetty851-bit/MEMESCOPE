"""Fee, slippage and funding accounting, and R. Hand-computed."""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.labs.crypto_trend.sim import SimAccount
from app.labs.crypto_trend.strategy import LONG, OPEN, SHORT, Order, StrategyConfig
from app.labs.crypto_trend.tests.fakes import NOW

CFG = StrategyConfig()  # fee 0.0005, slippage 5 bps, $1,000
LATER = NOW + timedelta(hours=8)


def order(side: str) -> Order:
    return Order("AAAUSDT", OPEN, side, "t", qty=2.0, stop_distance=4.0, atr=2.0,
                 notional=200.0, implied_leverage=0.2, reference_price=100.0)


def test_a_long_round_trip_by_hand() -> None:
    acct = SimAccount(CFG)
    p = acct.fill_open(order(LONG), 100.0, NOW)
    # buy at 100 x 1.0005 = 100.05 on qty 2 -> notional 200.10, fee 0.10005
    assert p.entry_price == pytest.approx(100.05)
    assert p.stop == pytest.approx(96.05)
    assert p.fees_paid == pytest.approx(0.10005)
    assert acct.cash == pytest.approx(1000 - 0.10005)
    assert acct.equity({"AAAUSDT": 105.0}) == pytest.approx(
        1000 - 0.10005 + 2 * (105 - 100.05))

    t = acct.fill_close("AAAUSDT", 110.0, LATER, "test")
    # sell at 110 x 0.9995 = 109.945; fee 2 x 109.945 x 0.0005 = 0.109945
    # gross (109.945 - 100.05) x 2 = 19.79; net 19.79 - 0.10005 - 0.109945
    assert t.exit_price == pytest.approx(109.945)
    assert t.fees == pytest.approx(0.10005 + 0.109945)
    assert t.pnl_usd == pytest.approx(19.79 - 0.10005 - 0.109945)
    assert t.risk_usd == 8.0 and t.pnl_r == pytest.approx(t.pnl_usd / 8.0)
    assert acct.cash == pytest.approx(1000 + t.pnl_usd)  # equity identity
    assert acct.positions == {} and acct.trades == [t]
    assert acct.fees_total == pytest.approx(t.fees)


def test_a_short_round_trip_by_hand() -> None:
    acct = SimAccount(CFG)
    p = acct.fill_open(order(SHORT), 100.0, NOW)
    assert p.entry_price == pytest.approx(99.95) and p.stop == pytest.approx(103.95)
    t = acct.fill_close("AAAUSDT", 90.0, LATER, "test")
    # buy back at 90 x 1.0005 = 90.045; gross (99.95 - 90.045) x 2 = 19.81
    assert t.exit_price == pytest.approx(90.045)
    fees = 2 * 99.95 * 0.0005 + 2 * 90.045 * 0.0005
    assert t.pnl_usd == pytest.approx(19.81 - fees)
    assert acct.cash == pytest.approx(1000 + t.pnl_usd)


def test_funding_is_paid_by_longs_and_received_by_shorts() -> None:
    acct = SimAccount(CFG)
    acct.fill_open(order(LONG), 100.0, NOW)
    cash = acct.cash
    assert acct.charge_funding("AAAUSDT", 0.0001, 100.0) == pytest.approx(0.02)
    assert acct.cash == pytest.approx(cash - 0.02)
    assert acct.positions["AAAUSDT"].funding_paid == pytest.approx(0.02)

    short = SimAccount(CFG)
    short.fill_open(order(SHORT), 100.0, NOW)
    assert short.charge_funding("AAAUSDT", 0.0001, 100.0) == pytest.approx(-0.02)
    # negative funding: shorts pay
    assert short.charge_funding("AAAUSDT", -0.0003, 100.0) == pytest.approx(0.06)
    assert short.positions["AAAUSDT"].funding_paid == pytest.approx(0.04)
    assert short.funding_total == pytest.approx(0.04)


def test_funding_flows_into_the_trade_pnl() -> None:
    acct = SimAccount(CFG)
    acct.fill_open(order(LONG), 100.0, NOW)
    acct.charge_funding("AAAUSDT", 0.0001, 100.0)
    t = acct.fill_close("AAAUSDT", 100.0, LATER, "test")
    fees = 2 * 100.05 * 0.0005 + 2 * 99.95 * 0.0005
    assert t.funding == pytest.approx(0.02)
    assert t.pnl_usd == pytest.approx((99.95 - 100.05) * 2 - fees - 0.02)
    assert acct.cash == pytest.approx(1000 + t.pnl_usd)


def test_a_losing_stop_is_minus_one_r_before_costs() -> None:
    acct = SimAccount(CFG)
    p = acct.fill_open(order(LONG), 100.0, NOW)
    # an open that lands exactly on the stop after slippage
    t = acct.fill_close("AAAUSDT", p.stop / 0.9995, LATER, "hard_stop")
    assert t.exit_price == pytest.approx(p.stop)
    assert t.pnl_r == pytest.approx((-8.0 - t.fees) / 8.0)


def test_r_is_on_the_risk_actually_taken_and_both_are_reported() -> None:
    """Intended 1% of $1,000 is $10; the cap left qty 2 against a $4 stop,
    so the stop can only lose $8. R divides by the $8."""
    acct = SimAccount(CFG)
    capped = Order("AAAUSDT", OPEN, LONG, "t", qty=2.0, stop_distance=4.0, atr=2.0,
                   notional=200.0, implied_leverage=0.2, reference_price=100.0,
                   intended_risk_usd=10.0)
    p = acct.fill_open(capped, 100.0, NOW)
    assert p.intended_risk_usd == 10.0
    t = acct.fill_close("AAAUSDT", 110.0, LATER, "test")
    assert (t.risk_usd, t.intended_risk_usd) == (8.0, 10.0)
    assert t.pnl_r == pytest.approx(t.pnl_usd / 8.0)
    assert t.pnl_r != pytest.approx(t.pnl_usd / 10.0)
