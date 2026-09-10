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
#: Candles per request. Binance allows more; 1,000 keeps the weight tiers simple.
KLINES_LIMIT = 1000
#: Rolling window kept per timeframe. 5,000 hourly candles is ~208 days — more
#: than 1,000 4h candles (~166) — so a deep 1h backfill survives the prune.
CANDLE_WINDOW_1H = 5000
CANDLE_WINDOW_4H = 1000


def candle_window(timeframe: str) -> int:
    return {"1h": CANDLE_WINDOW_1H, "4h": CANDLE_WINDOW_4H}.get(timeframe, CANDLE_WINDOW_4H)


#: Frozen historical universes (`universe snapshot --as-of DATE`).
COINGECKO_COIN_URL = "https://api.coingecko.com/api/v3/coins"
#: The public tier's limit, with headroom; a 429 still backs off.
COINGECKO_CALLS_PER_MINUTE = 25
#: How many of today's top coins are candidates for a past-date ranking.
SNAPSHOT_FETCH = 60
#: The public API refuses history older than this; `days=max` is a paid plan.
COINGECKO_MAX_HISTORY_DAYS = 365

# --- HTTP ---------------------------------------------------------------------
#: Binance allows 2,400 request-weight per minute per IP. Half of it is more
#: than this lab will ever spend and leaves room for anything else on the host.
WEIGHT_PER_MINUTE = 1200
HTTP_TIMEOUT_SECONDS = 10.0
MAX_ATTEMPTS = 4

#: Tick records kept for `data_health()`.
RUN_HISTORY = 500

# --- trend engine (Phase 2) ---------------------------------------------------
EMA_FAST = 20
EMA_SLOW = 50
EMA_TREND = 200
ADX_PERIOD = 14
ATR_PERIOD = 14
DONCHIAN_PERIOD = 20
SWING_LOOKBACK = 5
#: Below this ADX nothing is a trend, whatever the averages say.
ADX_MIN = 20.0
#: EMA_slow's change is measured over this many bars.
SLOPE_BARS = 5
#: Fewest closed candles a state is computed from; below it no row is written.
#: EMA_slow needs 50, ADX needs 2 x its period, the slope needs a few more.
MIN_BARS = 60

#: Strength components score full marks at: ADX 50, an EMA spread of two
#: ATRs, a close at the Donchian channel's edge, and a swing structure that
#: agrees with the direction. Weights: ADX, spread, Donchian position,
#: structure. The formula is in the README.
STRENGTH_ADX_FULL = 50.0
STRENGTH_SPREAD_ATR_FULL = 2.0
STRENGTH_WEIGHTS = (0.3, 0.2, 0.3, 0.2)
#: Structure is a VETO, not a gate: an UP reading is refused only when the
#: most recent swing is a lower low under the prior swing low by more than
#: this many ATRs (mirror for DOWN). Shallow or mixed structure lets the
#: averages and ADX decide.
STRUCTURE_VETO_ATR = 0.5

#: Regime: share of the universe whose 4h direction must agree.
BREADTH_RISK_ON = 0.60
BREADTH_RISK_OFF = 0.60
REGIME_BTC_SYMBOL = "BTCUSDT"
REGIME_ETH_SYMBOL = "ETHUSDT"
#: Trend state and regime rows older than this are pruned each run.
TREND_RETENTION_DAYS = 30

# --- strategy (Phase 3) -----------------------------------------------------------
#: Decisions are taken on closed 4h bars; 1h only feeds the verdict.
STRATEGY_TIMEFRAME = "4h"
#: A coin below this 4h strength is not entered.
STRENGTH_MIN = 40
#: In CHOP, entries need at least this much breadth on their side.
CHOP_BREADTH_MIN = 0.40
#: Shorts are skipped when the current funding rate is below this (per 8h):
#: negative funding means shorts pay longs.
FUNDING_SHORT_MAX = -0.0003
MAX_POSITIONS = 5
MAX_SAME_SIDE = 4
#: A single rally must not open the whole book on one close.
MAX_NEW_ENTRIES_PER_BAR = 2
#: Sizing: risk this fraction of equity per position, with the stop at
#: STOP_ATR x the 4h ATR at entry; notional is capped at MAX_NOTIONAL_PCT.
RISK_PER_TRADE = 0.01
STOP_ATR = 2.0
MAX_NOTIONAL_PCT = 0.20
#: Once a position is TRAIL_TRIGGER_ATR x entry-ATR in profit, trail at
#: TRAIL_ATR x the CURRENT ATR from the best close.
TRAIL_TRIGGER_ATR = 1.5
TRAIL_ATR = 2.5
#: A position still under water after this many 4h bars is closed.
MAX_BARS = 60

# --- simulation costs -------------------------------------------------------------
FEE_TAKER = 0.0005
SLIPPAGE_BPS = 5
#: Per 8h, when `ct_funding` has no row for the boundary.
FUNDING_FALLBACK = 0.0001
#: The replay account. $1,000, the figure every lab here starts from.
SIM_STARTING_EQUITY = 1000.0
