"""The monthly long/short book's arithmetic."""

from datetime import UTC, datetime
from decimal import Decimal

from app.labs.btc_range import monthly as m


def bar(month, o, c, h, lo, complete=True):
    return m.MonthBar(datetime(2026, month, 1, tzinfo=UTC), Decimal(o), Decimal(c),
                      Decimal(h), Decimal(lo), complete)


def test_follows_last_month_and_charges_fees_on_the_leveraged_amount():
    rows = m.book([bar(1, 100, 110, 111, 99), bar(2, 110, 121, 122, 109)])
    assert len(rows) == 1 and rows[0].side == 1  # January rose -> long
    # 3 x 10% = +30%, minus 2 sides x 0.07% x 3 = 0.42% -> $295.80
    assert rows[0].pnl_usd == Decimal("295.80") and not rows[0].liquidated


def test_a_down_month_means_short_and_a_rally_against_it_liquidates():
    rows = m.book([bar(1, 100, 90, 101, 89), bar(2, 90, 95, 120, 88)])
    assert rows[0].side == -1
    assert rows[0].liquidation_price == Decimal(90) * (1 + (1 / Decimal(3) - Decimal("0.005")))
    assert rows[0].liquidated and rows[0].pnl_usd == Decimal(-1000)


def test_the_running_month_is_marked_at_the_current_price():
    rows = m.book([bar(1, 100, 110, 111, 99), bar(2, 110, 112, 113, 109, complete=False)],
                  current_price=Decimal(99))
    assert rows[0].running and rows[0].exit == Decimal(99) and rows[0].pnl_usd < 0
