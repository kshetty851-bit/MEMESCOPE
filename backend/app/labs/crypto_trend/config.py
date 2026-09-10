"""The lab's own configuration. Deliberately NOT `app.core.config`.

Reading the flag from the platform's settings object would mean editing that
object, and this module's premise is that nothing existing is edited. One
environment variable read at call time; everything else a constant here.
"""

from __future__ import annotations

import os


def _flag(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def enabled() -> bool:
    """Read at call time, not at import: a test may flip it, and a worker
    that cached it at import would keep running a lab the operator turned off."""
    return _flag("CRYPTO_TREND_LAB_ENABLED")


# --- sources (keyless) --------------------------------------------------------
COINGECKO_MARKETS_URL = "https://api.coingecko.com/api/v3/coins/markets"
BINANCE_FAPI_URL = "https://fapi.binance.com"

# --- universe -----------------------------------------------------------------
#: How many coins to ask CoinGecko for, before exclusions and perp mapping.
UNIVERSE_FETCH = 30
#: How many survive into the universe.
UNIVERSE_SIZE = 20
UNIVERSE_REFRESH_SECONDS = 24 * 3600

#: Stablecoins, wrapped/staked tokens and anything else that is not a trend
#: instrument. Matched case-insensitively against BOTH the CoinGecko id and the
#: ticker, so a rename on either side still catches it. Editable; every entry
#: is a plain string. USDC is here deliberately even though Binance lists a
#: USDCUSDT perp — the exclusion runs before the mapping, not after.
EXCLUDED: frozenset[str] = frozenset({
    # stablecoins — ids
    "tether", "usd-coin", "usds", "dai", "ethena-usde", "usd1-wlfi",
    "global-dollar", "first-digital-usd", "paypal-usd", "true-usd", "usdt0",
    "binance-bridged-usdt-bnb-smart-chain", "ethena-staked-usde", "susds",
    "blackrock-usd-institutional-digital-liquidity-fund",
    "ondo-us-dollar-yield", "frax-usd", "usdd", "gho",
    # stablecoins — tickers
    "usdt", "usdc", "usde", "usd1", "usdg", "fdusd", "pyusd", "tusd",
    "susde", "buidl", "usdy", "frxusd",
    # wrapped / staked — ids
    "wrapped-bitcoin", "coinbase-wrapped-btc", "weth", "staked-ether",
    "wrapped-steth", "wrapped-eeth", "rocket-pool-eth", "binance-peg-weth",
    "wrapped-beacon-eth", "kelp-dao-restaked-eth", "solv-btc",
    "lombard-staked-btc", "binance-staked-sol", "jito-staked-sol",
    # wrapped / staked — tickers
    "wbtc", "cbbtc", "steth", "wsteth", "weeth", "reth", "wbeth", "rseth",
    "solvbtc", "lbtc", "bnsol", "jitosol",
    # exchange token named by the brief
    "leo-token", "leo",
})

#: CoinGecko id -> Binance USDT-margined perpetual, for coins whose contract is
#: not simply `<TICKER>USDT`. Binance quotes the sub-cent memecoins as
#: thousand-unit contracts, so their PRICES are x1000 — a later phase that
#: sizes a position has to know that. TON and HYPE currently map by default
#: (CoinGecko's TON ticker is `gram` and Binance's contract is `GRAMUSDT`);
#: add them here only if either side renames.
SYMBOL_OVERRIDES: dict[str, str] = {
    "shiba-inu": "1000SHIBUSDT",
    "pepe": "1000PEPEUSDT",
    "bonk": "1000BONKUSDT",
    "floki": "1000FLOKIUSDT",
}

# --- candles ------------------------------------------------------------------
TIMEFRAMES: tuple[str, ...] = ("1h", "4h")
#: Backfill depth on first sight of a symbol, and the rolling window kept after.
CANDLE_WINDOW = 1000

# --- HTTP ---------------------------------------------------------------------
#: Binance allows 2,400 request-weight per minute per IP. Half of it is more
#: than this lab will ever spend and leaves room for anything else on the host.
WEIGHT_PER_MINUTE = 1200
HTTP_TIMEOUT_SECONDS = 10.0
MAX_ATTEMPTS = 4

#: Tick records kept for `data_health()`.
RUN_HISTORY = 500
