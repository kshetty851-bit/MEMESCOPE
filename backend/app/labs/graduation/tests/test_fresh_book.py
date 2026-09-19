"""Karthik's fresh $500 BASE 75k book: the baseline's trades from its start,
funded as a $500 wallet at $100 a trade would fund them."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from app.labs.graduation import config
from app.labs.graduation.api import fresh_book

T0 = config.FRESH_START


def trade(minute: int, ret: float, hold: int = 5) -> tuple:
    opened = T0 + timedelta(minutes=minute)
    return (opened, opened + timedelta(minutes=hold), ret, 0.0, 0.0)


def test_it_starts_at_500_and_ignores_everything_before_the_start() -> None:
    book = fresh_book([trade(-60, 5.0), trade(1, 0.10), trade(10, -0.90)])
    assert book.capital_usd == Decimal(500)
    assert (book.trades, book.wins, book.rugs, book.skipped) == (2, 1, 1, 0)
    # $100 at +10%, then $100 at -90%: 500 + 10 - 90
    assert book.balance_usd == Decimal("420.00")
    assert book.pnl_usd == Decimal("-80.00") and book.return_pct == Decimal("-16.00")
    assert book.lowest_usd <= Decimal("420.00")


def test_a_sixth_trade_at_once_finds_no_money_and_is_skipped() -> None:
    book = fresh_book([trade(0, 0.01, hold=30) for _ in range(6)])
    assert (book.trades, book.skipped) == (5, 1)
