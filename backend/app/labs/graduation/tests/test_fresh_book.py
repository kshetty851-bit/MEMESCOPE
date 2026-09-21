"""Karthik's fresh books: an arm's trades from a start, funded as that book's
own wallet would fund them."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from app.labs.graduation import config
from app.labs.graduation.api import fresh_book
from app.labs.graduation.tournament import ARMS, CONTROLS, accepts

BQ, *SWEEP = config.FRESH_BOOKS     # the quiet arm, then the four $25k clocks

#: The book the panel dropped on 2026-09-20, whose arm still runs as this
#: one's control: the wallet walk that fed it is what this file tests.
B75 = config.FreshBookSpec("BASE_75k_5m", BQ.start, Decimal(500), Decimal(100))


def test_the_page_shows_the_quiet_book_and_the_25k_clocks() -> None:
    assert (BQ.book, BQ.capital_usd, BQ.ticket_usd) == (
        "BASE_75k_quiet_5m", Decimal(500), Decimal(100))
    # Two pairs that differ in one thing each, so the columns compare like for
    # like: same floor, same money, same start, plain against quiet.
    assert [s.book for s in SWEEP] == [
        "BASE_25k_2m", "BASE_25k_quiet_2m", "BASE_25k_5m", "BASE_25k_quiet_5m"]
    assert {(s.capital_usd, s.ticket_usd, s.start) for s in SWEEP} == {
        (Decimal(500), Decimal(100), SWEEP[0].start)}
    arms = [next(a for a in ARMS if a.name == s.book) for s in SWEEP]
    assert [a.hold for a in arms] == [2, 2, 5, 5]
    assert [a.quiet for a in arms] == [False, True, False, True]
    arm = next(a for a in ARMS if a.name == BQ.book)
    assert arm.quiet and arm.hold == 5 and not arm.is_control
    # The control it is judged against still trades, panel or no panel.
    assert [c.name for c in CONTROLS] == ["BASE_75k_5m"]


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

def test_the_25k_arms_are_one_floor_two_clocks_and_the_quiet_rule() -> None:
    """$25k and locked liquidity throughout; 2m and 5m; plain against quiet.
    No holder cap: of 200 coins read at the buy, "no wallet over 5%" admitted
    two, because every pump.fun graduation has a launch wallet near 79% and a
    pool wallet near 15%."""
    sweep = sorted((a for a in ARMS if a.name.startswith("BASE_25k")),
                   key=lambda a: (a.hold, a.quiet))
    assert [a.name for a in sweep] == [
        "BASE_25k_2m", "BASE_25k_quiet_2m", "BASE_25k_5m", "BASE_25k_quiet_5m"]
    assert [a.hold for a in sweep] == [2, 2, 5, 5]
    assert [a.quiet for a in sweep] == [False, True, False, True]
    assert all(a.locked and a.entry == "floor25" and not a.is_control for a in sweep)
    assert all((a.tp, a.trail, a.stop, a.drain, a.clock) == (None, None, None, None, "entry")
               for a in sweep)
    kw = {"mint": "m", "open_at": BQ.start, "fdv": None, "sells": None, "reuse": None}
    assert accepts(sweep[0], liquidity=Decimal(25_000), **kw)
    assert not accepts(sweep[0], liquidity=Decimal(24_999), **kw)
    assert not accepts(sweep[0], liquidity=None, **kw)
