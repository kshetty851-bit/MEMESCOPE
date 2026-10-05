"""The Pool Lab's maths (2026-10-05): ten wallets on one coin pay one after
another, and the per-coin cap admits five."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.labs.graduation import pool_lab as pl

T0 = datetime(2026, 10, 2, 12, 0, tzinfo=UTC)


def test_a_later_order_in_the_queue_pays_more():
    first, fifth = pl.queue_k(0, 50), pl.queue_k(4, 50)
    assert (first, fifth) == (0.5, 4.5)
    impact = (0.01, 0.01)
    assert pl.legs_multiple(0.05, impact, 1, 1) == 1.05  # as measured at $100
    assert pl.legs_multiple(0.05, impact, first, first) > pl.legs_multiple(
        0.05, impact, fifth, fifth
    )
    assert pl.legs_multiple(0.05, None, 9, 9) == 1.05  # no recorded impact, no change


def test_the_cap_lets_five_wallets_in_and_they_take_turns():
    coins = [
        (
            T0 + timedelta(minutes=10 * i),
            T0 + timedelta(minutes=10 * i + 5),
            0.10,
            (0.01, 0.01),
        )
        for i in range(2)
    ]
    capped = pl.ten_wallets(coins, 0.0, cap=pl.COIN_CAP)
    assert [w.trades for w in capped] == [1] * 10  # five, then the other five
    uncapped = pl.ten_wallets(coins, 0.0, cap=None)
    assert [w.trades for w in uncapped] == [2] * 10
    # First in line does best on the same coin.
    assert uncapped[0].worth() > uncapped[9].worth()


def test_a_wallet_never_spends_money_it_does_not_have():
    # Eleven overlapping coins on $500 at $50: ten tickets, the eleventh waits.
    coins = [
        (T0 + timedelta(seconds=i), T0 + timedelta(minutes=5), 0.0, None) for i in range(11)
    ]
    wallets = pl.ten_wallets(coins, 0.0, cap=None)
    assert all(w.trades == 10 for w in wallets)
    assert all(abs(w.worth() - pl.WALLET_START) < 1e-9 for w in wallets)
