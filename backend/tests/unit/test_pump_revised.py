"""Independent pricing/funding boundaries. No DB, Redis or wallet writes."""
import unittest
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

from app.labs.graduation.pump_revised import Priced, selected, walk, wallet_run

A = datetime(2026, 10, 1, tzinfo=UTC)


def source(age=60, **changes):
    values = dict(id='p', mint='mint', symbol='coin', opened_at=A,
                  graduated_at=A-timedelta(seconds=age), notional_usd=Decimal(100),
                  open_quote=Decimal(1), open_fill=Decimal('1.01604'),
                  impact_open=Decimal('.01'), sol_usd_at_open=Decimal(100),
                  net_return=Decimal('-.9'))
    values.update(changes)
    return SimpleNamespace(**values)


def quote(seconds, price, rid='a', pair='own', liquidity=100000):
    return dict(ts=A+timedelta(seconds=seconds), native=price, usd=None,
                liq=liquidity, pair=pair, rid=rid)


class PricingTests(unittest.TestCase):
    def test_native_only_and_same_pool(self):
        row = Priced(source(), [quote(60, 4, pair='other'), quote(120, 1.1),
                                quote(600, 1.2)], 'own')
        self.assertEqual(row.how, '10m')
        self.assertGreater(float(row.net_return), 0)
        self.assertLess(float(row.net_return), .2)  # fees and impact deducted

    def test_target_fills_at_next_distinct_timestamp(self):
        row = Priced(source(), [quote(60, 2), quote(60, .5, rid='b'),
                                quote(90, 1.4), quote(600, 1.3)], 'own')
        self.assertEqual(row.closed_at, A+timedelta(seconds=90))
        self.assertEqual(row.how, 'target')

    def test_trailing_fills_after_gap_and_can_lose(self):
        row = Priced(source(), [quote(30, 1.6), quote(60, 1.2),
                                quote(90, .3), quote(600, .1)], 'own')
        self.assertEqual(row.how, 'trailing')
        self.assertEqual(row.closed_at, A+timedelta(seconds=90))
        self.assertLess(float(row.net_return), -.5)

    def test_five_minute_uses_last_known_quote_not_future_quote(self):
        row = Priced(source(age=30), [quote(290, .9), quote(310, 1.1),
                                      quote(600, 1.2)], 'own')
        self.assertEqual(row.how, '5m-down')
        self.assertEqual(row.closed_at, A+timedelta(seconds=310))

    def test_new_exit_replaces_five_minute_loss_for_selected_signals(self):
        row = Priced(source(), [quote(290, .9), quote(310, 1.1),
                                quote(600, 1.2)], 'own')
        self.assertEqual(row.how, '10m')

    def test_no_five_minute_calibration_or_book_fallback(self):
        path = [quote(300, 1.1), quote(600, 1.2)]
        one = Priced(source(net_return=Decimal('-.9')), path, 'own')
        two = Priced(source(net_return=Decimal('9')), path, 'own')
        self.assertEqual(one.net_return, two.net_return)

    def test_missing_next_fill_is_not_filled_at_trigger(self):
        row = Priced(source(), [quote(60, 2.1)], 'own')
        self.assertEqual(row.how, 'unpriced-loss')
        self.assertEqual(row.net_return, -1)

    def test_missing_pool_never_uses_another_pool(self):
        row = Priced(source(), [quote(600, 9)], None)
        self.assertEqual(row.net_return, -1)

    def test_missing_exit_depth_is_full_loss(self):
        row = Priced(source(), [quote(600, 2, liquidity=0)], 'own')
        self.assertEqual(row.net_return, -1)

    def test_age_is_original_entry_age(self):
        self.assertFalse(selected(source(age=55)))
        self.assertTrue(selected(source(age=60)))

    def test_larger_and_later_orders_pay_more_impact(self):
        row = Priced(source(), [quote(600, 1.1)], 'own')
        self.assertGreater(row.return_at(50), row.return_at(100))
        self.assertGreater(row.return_at(50), row.return_at(50, 1))


def trade(seconds, ret, closed, symbol='coin'):
    return SimpleNamespace(opened_at=A+timedelta(seconds=seconds),
                           closed_at=A+timedelta(seconds=closed), symbol=symbol,
                           return_at=lambda size, place=0: ret)


class FundingTests(unittest.TestCase):
    def test_unfunded_rug_does_not_block_name(self):
        rows = [trade(0, 0, 100, 'other'), trade(1, -1, 20), trade(101, .1, 120)]
        w = walk(rows, start=50)
        self.assertEqual(w.pnl, (0, None, 5))
        self.assertEqual(w.skipped, 1)

    def test_name_block_only_after_own_rug_closes(self):
        rows = [trade(0, -.5, 100), trade(90, .1, 120),
                trade(101, .1, 130), trade(43301, .1, 43400)]
        w = walk(rows)
        self.assertEqual(w.pnl, (-25, 5, None, 5))

    def test_close_at_same_timestamp_cannot_fund_entry(self):
        rows = [trade(0, .1, 100, 'a'), trade(100, .2, 200, 'b')]
        self.assertEqual(walk(rows, start=50).pnl, (5, None))

    def test_lowest_equity_settles_in_order_with_open_positions_at_cost(self):
        rows = [trade(0, -.5, 100, 'a'), trade(1, .1, 90, 'b')]
        w = walk(rows)
        self.assertEqual(w.low, 480)
        self.assertEqual(w.cash, 480)
        self.assertEqual(wallet_run(rows, 1, 500)[0]['pnl_usd'], -20)


if __name__ == '__main__':
    unittest.main()
