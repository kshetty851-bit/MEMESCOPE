"""Karthik's fresh books: an arm's trades from a start, funded as that book's
own wallet would fund them."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from app.labs.graduation import config
from app.labs.graduation.api import fresh_book
from app.labs.graduation.tournament import ARMS, CONTROLS, accepts

B75, B10 = config.FRESH_BOOKS


def trade(spec: config.FreshBookSpec, minute: int, ret: float, hold: int = 5) -> tuple:
    opened = spec.start + timedelta(minutes=minute)
    return (opened, opened + timedelta(minutes=hold), ret, 0.0, 0.0)


def test_it_starts_at_500_and_ignores_everything_before_the_start() -> None:
    book = fresh_book([trade(B75, -60, 5.0), trade(B75, 1, 0.10), trade(B75, 10, -0.90)],
                      None, B75)
    assert (book.book, book.hold_minutes, book.capital_usd) == ("BASE_75k_5m", 5, Decimal(500))
    assert (book.trades, book.wins, book.rugs, book.skipped) == (2, 1, 1, 0)
    # $100 at +10%, then $100 at -90%: 500 + 10 - 90
    assert book.balance_usd == Decimal("420.00")
    assert book.pnl_usd == Decimal("-80.00") and book.return_pct == Decimal("-16.00")


def test_a_sixth_trade_at_once_finds_no_money_and_is_skipped() -> None:
    book = fresh_book([trade(B75, 0, 0.01, hold=30) for _ in range(6)], None, B75)
    assert (book.trades, book.skipped) == (5, 1)


def test_the_10k_book_is_ten_tickets_of_50() -> None:
    assert (B10.book, B10.capital_usd, B10.ticket_usd) == (
        "BASE_10k_2m", Decimal(500), Decimal(50))
    book = fresh_book([trade(B10, 0, 0.01, hold=10) for _ in range(11)], None, B10)
    assert (book.hold_minutes, book.trades, book.skipped) == (2, 10, 1)


def test_the_10k_arm_buys_every_pool_over_10k_and_is_not_the_baseline() -> None:
    arm = next(a for a in ARMS if a.name == "BASE_10k_2m")
    assert (arm.entry, arm.hold, arm.clock, arm.stop, arm.drain) == (
        "floor10k", 2, "entry", None, None)
    kw = {"mint": "m", "open_at": B10.start, "fdv": None, "sells": None, "reuse": None}
    assert accepts(arm, liquidity=Decimal(10_000), **kw)
    assert not accepts(arm, liquidity=Decimal(9_999), **kw)
    assert not accepts(arm, liquidity=None, **kw)
    assert [c.name for c in CONTROLS] == ["BASE_75k_5m"]
