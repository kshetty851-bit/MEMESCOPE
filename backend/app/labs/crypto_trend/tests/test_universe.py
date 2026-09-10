"""Stablecoin filtering and symbol mapping. Pure; no database, no network."""

from __future__ import annotations

from decimal import Decimal

from app.labs.crypto_trend import config
from app.labs.crypto_trend.universe import is_excluded, map_symbol, select_universe

PERPS = {"BTCUSDT", "ETHUSDT", "USDCUSDT", "HYPEUSDT", "GRAMUSDT", "1000PEPEUSDT", "SOLUSDT"}


def market(cid, ticker, rank, cap=1_000_000_000):
    return {"id": cid, "symbol": ticker, "name": cid.title(), "market_cap": cap,
            "market_cap_rank": rank}


def test_stablecoins_are_excluded_even_when_binance_lists_a_perp() -> None:
    """USDCUSDT is a real Binance perp. The exclusion must run BEFORE the
    perp check, or the universe would trend-trade a dollar."""
    chosen, skipped = select_universe(
        [market("bitcoin", "btc", 1), market("usd-coin", "usdc", 2),
         market("ethereum", "eth", 3)],
        PERPS,
    )
    assert [c.binance_symbol for c in chosen] == ["BTCUSDT", "ETHUSDT"]
    assert skipped == []


def test_exclusion_matches_id_or_ticker_case_insensitively() -> None:
    assert is_excluded({"id": "tether", "symbol": "xyz"})
    assert is_excluded({"id": "something-new", "symbol": "USDT"})
    assert is_excluded({"id": "leo-token", "symbol": "leo"})
    assert is_excluded({"id": "wrapped-steth", "symbol": "wsteth"})
    assert not is_excluded({"id": "bitcoin", "symbol": "btc"})


def test_the_exclusion_list_is_lowercase() -> None:
    """Matching lowercases the input, so an entry with capitals could never match."""
    assert all(e == e.lower() for e in config.EXCLUDED)


def test_default_mapping_is_ticker_plus_usdt() -> None:
    assert map_symbol("bitcoin", "btc") == "BTCUSDT"
    # CoinGecko's TON ticker is `gram`, and Binance's contract is GRAMUSDT.
    assert map_symbol("the-open-network", "gram") == "GRAMUSDT"


def test_override_map_wins_over_the_default() -> None:
    assert map_symbol("pepe", "pepe") == "1000PEPEUSDT"
    assert map_symbol("shiba-inu", "shib") == "1000SHIBUSDT"


def test_coin_without_a_perp_is_skipped_and_reported() -> None:
    chosen, skipped = select_universe(
        [market("bitcoin", "btc", 1), market("figure-heloc", "figr_heloc", 2),
         market("hyperliquid", "hype", 3)],
        PERPS,
    )
    assert [c.binance_symbol for c in chosen] == ["BTCUSDT", "HYPEUSDT"]
    assert skipped == [{"coingecko_id": "figure-heloc", "ticker": "FIGR_HELOC",
                        "tried": "FIGR_HELOCUSDT"}]
    # Ranks are contiguous within the universe, not CoinGecko's.
    assert [c.rank for c in chosen] == [1, 2]
    assert [c.market_cap_rank for c in chosen] == [1, 3]


def test_a_skipped_coin_does_not_consume_a_slot() -> None:
    markets = [market("figure-heloc", "figr_heloc", 1), market("bitcoin", "btc", 2),
               market("ethereum", "eth", 3), market("solana", "sol", 4)]
    chosen, _ = select_universe(markets, PERPS, size=2)
    assert [c.binance_symbol for c in chosen] == ["BTCUSDT", "ETHUSDT"]


def test_universe_is_capped_at_size() -> None:
    markets = [market("bitcoin", "btc", 1), market("ethereum", "eth", 2),
               market("solana", "sol", 3)]
    chosen, _ = select_universe(markets, PERPS, size=2)
    assert len(chosen) == 2


def test_market_cap_is_decimal_and_survives_null() -> None:
    chosen, _ = select_universe([market("bitcoin", "btc", 1, cap=1_545_300_000_000),
                                 {"id": "ethereum", "symbol": "eth", "market_cap": None,
                                  "market_cap_rank": 2}], PERPS)
    assert chosen[0].market_cap_usd == Decimal("1545300000000")
    assert chosen[1].market_cap_usd is None
    assert chosen[1].name == "ETH"
