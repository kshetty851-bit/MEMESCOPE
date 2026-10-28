from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.labs.graduation import config
from app.labs.graduation.held_watch import FirstMinute, Held

T0 = datetime(2026, 10, 25, tzinfo=UTC)


def _held(base, quote, slot):
    h = Held(mint="M", pool="P", base_vault="b", quote_vault="q", base_decimals=6,
             quote_decimals=9, quote_mint=config.WSOL_MINT)
    h.base, h.quote, h.slot = base, quote, slot
    return h


def test_a_slot_is_kept_only_once_complete_and_only_when_the_price_moved():
    fm = FirstMinute(window_s=480)
    fm.add("M", T0, "sig")
    assert fm.observe(_held(1_000_000_000, 10_000_000_000, 5), T0 + timedelta(seconds=1)) == []
    # Same slot, the other vault lands: still not complete.
    assert fm.observe(_held(900_000_000, 11_000_000_000, 5), T0 + timedelta(seconds=1)) == []
    rows = fm.observe(_held(900_000_000, 11_000_000_000, 6), T0 + timedelta(seconds=2))
    assert len(rows) == 1 and rows[0]["slot"] == 5 and rows[0]["sol_quoted"]
    assert rows[0]["price_native"] == Decimal(11) / Decimal(900)        # both sides of the swap
    assert rows[0]["virtual_quote"] == 0
    assert rows[0]["ts"] == T0 + timedelta(seconds=1)                   # when slot 5 was heard
    # Slot 6 had the same price: closing it writes nothing.
    assert fm.observe(_held(800_000_000, 12_000_000_000, 7), T0 + timedelta(seconds=3)) == []
    last = fm.expire(T0 + timedelta(seconds=481))
    assert [r["slot"] for r in last] == [7] and "M" not in fm.due
    assert fm.observe(_held(1, 1, 8), T0 + timedelta(seconds=482)) == []  # window closed


def test_unknown_mints_are_ignored():
    assert FirstMinute(window_s=480).observe(_held(1, 1, 1), T0) == []


def test_a_wrapped_virtual_field_is_kept_signed_and_out_of_the_price():
    fm = FirstMinute(window_s=480)
    fm.add("M", T0, "sig")
    h = _held(1_000_000_000, 10_000_000_000, 5)
    h.virtual_quote = 2**64 - 14_845_478
    fm.observe(h, T0)
    (row,) = fm.expire(T0 + timedelta(seconds=481))
    assert row["virtual_quote"] == -14_845_478 and row["price_native"] == Decimal(10) / Decimal(1000)


def test_a_pool_hint_is_kept_only_for_watched_mints_and_dropped_with_them():
    fm = FirstMinute(window_s=480)
    fm.hint("M", "POOL")                      # not graduated yet: ignored
    assert fm.pools == {}
    fm.add("M", T0, "sig", "POOL")
    fm.hint("M", "OTHER")                     # the first named pool stays
    assert fm.pools == {"M": "POOL"}
    fm.expire(T0 + timedelta(seconds=481))
    assert fm.pools == {}


def test_at_most_one_row_a_second_and_no_non_sol_pools():
    fm = FirstMinute(window_s=480)
    fm.add("M", T0, "sig")
    rows = []
    for i, (slot, secs) in enumerate([(5, 1.0), (6, 1.3), (7, 1.6), (8, 2.2), (9, 2.5)]):
        rows += fm.observe(_held(1_000_000_000 - i * 1_000_000, 10_000_000_000, slot), T0 + timedelta(seconds=secs))
    assert [r["slot"] for r in rows] == [5, 8]           # slots 6 and 7 fell inside slot 5's second
    other = FirstMinute(window_s=480)
    other.add("M", T0, "sig")
    h = _held(1_000_000_000, 10_000_000_000, 5)
    h.quote_mint = "USDC"
    other.observe(h, T0)
    assert other.observe(_held(1, 1, 6), T0 + timedelta(seconds=2)) == [] and "M" not in other.due
