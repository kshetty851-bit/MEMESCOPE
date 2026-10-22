from decimal import Decimal

from app.labs.longwatch import service as s

MINT, POOL = "Mint1111", "Pool1111"


def _pair(addr, dex, liq, base=MINT):
    return {"pairAddress": addr, "dexId": dex, "liquidity": {"usd": liq}, "baseToken": {"address": base}}


def test_pick_pair_prefers_the_graduation_pool_then_deepest_pumpswap():
    pairs = [_pair("other", "pumpswap", 90_000), _pair(POOL, "pumpswap", 10_000),
             _pair("ray", "raydium", 500_000), _pair("x", "pumpswap", 1e9, base="NotMine")]
    assert s.pick_pair(pairs, MINT, POOL)["pairAddress"] == POOL
    assert s.pick_pair(pairs, MINT, None)["pairAddress"] == "other"
    assert s.pick_pair([], MINT, POOL) is None


def test_a_flat_round_trip_loses_fees_and_impact():
    price, liq = Decimal("0.001"), Decimal("40000")
    qty = s._buy_qty(price, liq)
    back = s._sell(qty, price, liq)
    assert 0 < back < s.TRADE_USD * Decimal("0.98")
