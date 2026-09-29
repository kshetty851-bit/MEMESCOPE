"""Karthik and Rafiq's 50-50 of the real wallet, from 28 Sep 15:00 Dubai."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from app.real_wallet import partners
from app.real_wallet.partners import START, book

D = Decimal
H = timedelta(hours=1)


def test_profit_splits_half_and_half_and_days_use_the_opening_balance():
    rows = [
        (START + 1 * H, START + 1.1 * H, D("2.00"), "CLOSED"),
        (START + 5 * H, START + 5.1 * H, D("-0.50"), "CLOSED"),
        (START + 25 * H, START + 25.1 * H, D("10.00"), "CLOSED"),  # day 2
        (START + 26 * H, None, None, "OPEN"),  # not profit yet
    ]
    out = book(rows, now=START + 27 * H)
    assert (
        out["profit_usd"],
        out["balance_usd"],
        out["trades"],
        out["wins"],
        out["open"],
    ) == ("11.50", "111.50", 3, 2, 1)
    karthik, rafiq = out["partners"]
    assert (
        karthik["name"],
        karthik["put_in_usd"],
        karthik["profit_usd"],
        karthik["now_usd"],
    ) == ("Karthik", "50.00", "5.75", "55.75")
    assert rafiq == {**karthik, "name": "Rafiq"}
    day2, day1 = out["days"]  # newest first
    assert (day1["n"], day1["pnl_usd"], day1["pct"], day1["running"]) == (
        1,
        "1.50",
        "1.50",
        False,
    )
    # Day 2 opened with $101.50, so +$10.00 is 9.85% of it, not 10%.
    assert (day2["n"], day2["pnl_usd"], day2["pct"], day2["running"]) == (
        2,
        "10.00",
        "9.85",
        True,
    )
    assert day2["balance_usd"] == "111.50"


def test_before_the_start_there_is_nothing():
    out = book([], now=START - H)
    assert (out["profit_usd"], out["days"]) == ("0.00", [])


def test_the_start_is_three_pm_dubai_on_the_28th():
    assert START.isoformat() == "2026-09-28T11:00:00+00:00"
    assert str(partners.CAPITAL) == "100"


def test_each_partner_is_shown_in_sol_at_todays_price():
    rows = [(START + H, START + 1.1 * H, D("20.00"), "CLOSED")]
    out = book(rows, now=START + 2 * H, sol_usd=D("200"))
    karthik = out["partners"][0]
    # Half of 0.8457 SOL in; half of $20 = $10 = 0.05 SOL made at $200.
    assert (karthik["put_in_sol"], karthik["profit_sol"], karthik["now_sol"]) == \
        ("0.4229", "0.0500", "0.4729")
    assert karthik["now_value_usd"] == "94.57"      # 0.47285 SOL x $200
    assert (out["total_put_in_sol"], out["total_now_sol"], out["sol_usd"]) == \
        ("0.8457", "0.9457", "200.00")


def test_no_sol_price_means_no_sol_figures_rather_than_a_guess():
    out = book([(START + H, START + 1.1 * H, D("20.00"), "CLOSED")], now=START + 2 * H)
    assert out["partners"][0]["profit_sol"] is None and out["sol_usd"] is None
    assert out["partners"][0]["put_in_sol"] == "0.4229"
