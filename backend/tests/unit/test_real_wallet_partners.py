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


def test_profit_now_is_the_wallets_value_at_todays_sol_price_split_in_half():
    """Karthik, 2026-09-29: the balance is $137.63, so each has made $18.815."""
    rows = [(START + H, START + 1.1 * H, D("38.64"), "CLOSED")]
    # 1.1803 SOL at $116.61 = $137.63.
    out = book(rows, now=START + 2 * H, sol_usd=D("116.61"), wallet_sol=D("1.180259"))
    assert out["total_value_usd"] == "137.63" and out["value_pct"] == "37.63"
    karthik = out["partners"][0]
    assert (karthik["value_usd"], karthik["value_profit_usd"]) == ("68.82", "18.82")
    assert karthik["value_sol"] == "0.5901" and karthik["put_in_sol"] == "0.4229"
    assert karthik["profit_usd"] == "19.32"          # the trading profit, beside it


def test_an_open_trade_counts_at_what_it_cost():
    """$50 is in a coin for five minutes, not in SOL: the value must not dip."""
    out = book([], now=START + H, sol_usd=D("100"), wallet_sol=D("0.60"),
               open_cost_usd=D("50"))
    assert out["total_value_usd"] == "110.00" and out["open_cost_usd"] == "50.00"


def test_no_price_or_no_balance_means_no_value_rather_than_a_guess():
    rows = [(START + H, START + 1.1 * H, D("20.00"), "CLOSED")]
    for out in (book(rows, now=START + 2 * H),
                book(rows, now=START + 2 * H, sol_usd=D("200")),
                book(rows, now=START + 2 * H, wallet_sol=D("1"))):
        assert out["partners"][0]["value_profit_usd"] is None
        assert out["value_pct"] is None
        assert out["partners"][0]["put_in_sol"] == "0.4229"
