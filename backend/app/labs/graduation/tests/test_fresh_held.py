"""A fresh book's coins, never sold: priced by selling them into the pool now."""

from __future__ import annotations

from decimal import Decimal

from app.labs.graduation import config
from app.labs.graduation.api import held_value

SOL = Decimal(100)


def test_a_small_sale_into_a_deep_pool_gets_the_price_less_fees() -> None:
    # 1,000 SOL against 100M tokens (6 decimals): 0.00001 SOL a token.
    got, depth = held_value(100_000_000 * 10**6, 1_000 * 10**9, 6, 9, Decimal(1_000_000), SOL)
    fee = Decimal(config.pool_fee_bps(Decimal("0.00001")) + config.ROUTER_FEE_BPS) / 10_000
    mark = Decimal(1_000_000) * Decimal("0.00001") * SOL          # $1,000 at the price
    assert mark * (1 - fee) * Decimal("0.98") < got < mark * (1 - fee)
    assert depth == Decimal(200_000)


def test_a_drained_pool_pays_almost_nothing_whatever_it_quotes() -> None:
    # A rugged pool: 0.5 SOL left against 900M tokens.
    got, _ = held_value(900_000_000 * 10**6, 5 * 10**8, 6, 9, Decimal(1_000_000), SOL)
    assert got < Decimal("0.06")


def test_nothing_to_sell_or_no_pool_is_no_value() -> None:
    assert held_value(0, 10**9, 6, 9, Decimal(1), SOL) is None
    assert held_value(10**6, 10**9, 6, 9, Decimal(0), SOL) is None
