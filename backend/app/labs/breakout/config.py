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
    return _flag("BREAKOUT_LAB_ENABLED")


# --- sources (keyless) --------------------------------------------------------
GECKOTERMINAL_URL = "https://api.geckoterminal.com/api/v2"
DEXSCREENER_URL = "https://api.dexscreener.com"
NETWORK = "solana"

# --- universe -----------------------------------------------------------------
#: GeckoTerminal serves 20 pools per page and refuses page 11 with a 401 —
#: measured, not assumed. Ten pages is the whole ranked list it will give.
UNIVERSE_PAGES = 10
#: A pool younger than this is not an established token.
MIN_AGE_DAYS = 7
MIN_LIQUIDITY_USD = 50_000
MIN_VOLUME_24H_USD = 100_000
#: Matched as a PREFIX of the venue's own id, because both sources suffix
#: their variants: GeckoTerminal serves `raydium-clmm` and `meteora-damm-v2`
#: alongside `raydium` and `meteora`. Measured on 80 live pools: of the 22 that
#: cleared every other filter and sat on an allowed venue, 4 were
#: `raydium-clmm` — an exact-match list would have dropped all four.
DEX_ALLOWLIST: tuple[str, ...] = ("raydium", "meteora", "orca", "pumpswap")
#: Bonding curves, excluded by the brief. `pumpswap` is the GRADUATED AMM and
#: is allowed above; `pumpfun` is the curve itself and is not. The denylist is
#: checked first, so a prefix collision can never admit one.
DEX_DENYLIST: tuple[str, ...] = ("pumpfun",)
#: Most active tokens kept, by 24h volume. Measured against the live top-200
#: pools this does not bind — about 30 pools a refresh clear the filters.
MAX_UNIVERSE = 300
UNIVERSE_REFRESH_SECONDS = 15 * 60

#: Stablecoins, wrapped SOL, liquid-staking tokens and bridged majors: things
#: that trade but do not break out. By MINT, because a mint cannot be renamed.
#: Editable — every entry is a plain string, and an unknown mint simply is not
#: excluded. Only the BASE token of a pool is checked (see `universe.py`).
EXCLUDED_MINTS: frozenset[str] = frozenset({
    # wrapped SOL
    "So11111111111111111111111111111111111111112",
    # stablecoins
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",   # USDC
    "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",   # USDT
    "USDSwr9ApdHk5bvJKMjzff41FfuX8bSxdKcR81vTwcA",    # USDS
    "2b1kV6DkPAnxd5ixfnxCpjxmKwqjjaYmCZfHsFu24GXo",   # PYUSD
    "DEkqHyPN7GMRJ5cArtQFAWefqbZb33Hyf6s5iCwjEonT",   # USDe
    "9zNQRsGLjNKwCUU5Gq5LR8beUCPzQMVMqKAi3SSZh54u",   # FDUSD
    "HzwqbKZw8HxMN6bF2yFZNrht3c2iXXzpKcFu7uBEDKtr",   # EURC
    "A1KLoBrKBde8Ty9qtNQUtq3C2ortoC3u7twggz7sEto6",   # USDY
    "USDH1SM1ojwWUga67PGrgFWUHibbjqMvuMaDkRJTgkX",    # USDH
    "2u1tszSeqZ3qBWF3uNGPFc8TzMk2tdiwknnRMWGWjGWH",   # UXD
    # liquid staking
    "J1toso1uCk3RLmjorhTtrVwY9HJ7X8V9yYac6Y7kGCPn",   # jitoSOL
    "mSoLzYCxHdYgdzU16g5QSh3i5K3z3KZK7ytfqcJm7So",    # mSOL
    "bSo13r4TkiE4KumL71LsHTPpL2euBYLFx6h9HP3piy1",    # bSOL
    "jupSoLaHXQiZZTSfEWMTRRgpnyFm8f6sZdosWBjx93v",    # jupSOL
    "5oVNBeEEQvYi1cX3ir8Dx5n1P7pdxydbGF2X4TxVusJm",   # INF
    "he1iusmfkpAdwvxLNGV8Y1iSbj4rUy6yMhEA3fotn9A",    # hSOL
    "LSTxxxnJzKDFSLr4dUkPcmCf5VyryEqzPLz5j4bpxFp",    # LST
    "CgnTSoL3DgY9SFHxcLj6CgCgKKoTBr6tp4CPAEWy25DE",   # cgntSOL
    "BNso1VUJnh4zcfpZa6986Ea66P6TCp59hvtNJ8b1X85",    # BNSOL
    # bridged / wrapped majors
    "3NZ9JMVBmGAqocybic2c7LQCJScmgsAZ6vQqTDzcqmJh",   # WBTC (Wormhole)
    "cbbtcf3aa214zXHbiAZQwf4122FBYbraNdFqgw4iMij",    # cbBTC
    "7vfCXTUXx5WJV5JADk17DUJ4ksgau7utNKj4b963voxs",   # WETH (Wormhole)
    "9n4nbM75f5Ui33ZbPYXn59EwSgE8CGsHtAeTH5YFeJ9E",   # WBTC (Sollet, legacy)
})

# --- candles ------------------------------------------------------------------
#: GeckoTerminal's own names for the two OHLCV timeframes. Stored verbatim so
#: a row's `timeframe` is the string the API was asked for.
TIMEFRAMES: tuple[str, ...] = ("day", "hour")
INTERVAL_SECONDS: dict[str, int] = {"day": 86_400, "hour": 3_600}
#: Bars per request. 100 is the API's cap, not a choice.
OHLCV_LIMIT = 100
#: How much history each timeframe is backfilled to. 180 daily bars is half a
#: year of resistance levels; 336 hourly is fourteen days.
CANDLE_WINDOW_1D = 180
CANDLE_WINDOW_1H = 336
#: Pages of BACKWARD paging one token may spend per timeframe per tick, so a
#: single deep backfill cannot consume the whole budget. Backfill is resumable
#: — the next tick sees the same short history and continues.
BACKFILL_PAGES_PER_TICK = 2
#: The daily bar closes at 00:00 UTC; GeckoTerminal needs a moment to publish
#: it. Nothing daily is fetched before this minute past midnight.
DAY_REFRESH_AFTER_MINUTE = 5


def candle_window(timeframe: str) -> int:
    return {"day": CANDLE_WINDOW_1D, "hour": CANDLE_WINDOW_1H}.get(
        timeframe, CANDLE_WINDOW_1H)


#: Consecutive failed fetches before a token is marked inactive. Reset by any
#: success, so a token is retired for being persistently broken, never for a
#: bad afternoon.
MAX_FETCH_FAILURES = 5

# --- HTTP ---------------------------------------------------------------------
#: GeckoTerminal's free tier allows ~30 calls a minute. The PLATFORM currently
#: spends none of it: `MARKET_PROVIDER=dexscreener`, and its GeckoTerminal
#: provider is consulted only under `composite`. If that is ever switched on,
#: its `MARKET_SECONDARY_CALLS_PER_MINUTE` (25) plus this would exceed the
#: tier — cut THIS number, it is the lab's whole claim on the host.
GECKOTERMINAL_CALLS_PER_MINUTE = 25
#: DexScreener allows ~300/min on `/tokens/v1` and ~60/min on the boost and
#: profile lists (measured: a bare second call to `/token-profiles/latest/v1`
#: answered 429). The platform's enrichment worker already spends up to ~48 a
#: minute of it. Four calls a tick is all this lab wants; 60 is headroom.
DEXSCREENER_CALLS_PER_MINUTE = 60

#: **A per-minute rate is not enough for these hosts: they punish BURSTS.**
#: Measured against the live GeckoTerminal API, a client inside the 30/min
#: allowance was refused on its SEVENTH call 0.7 seconds in, and stayed
#: refused for about 35 seconds. A plain token bucket is the wrong shape for
#: that, because it starts full and hands out its whole minute at once.
#:
#: So each host's bucket is built with a capacity of ONE and a window of
#: `60 / rate` seconds, which turns the platform's own `CallBudget` into a
#: minimum SPACING between calls — 2.4s for GeckoTerminal, 1.0s for
#: DexScreener — with no burst possible and no new rate-limiter written.
def call_spacing_seconds(calls_per_minute: int) -> float:
    return 60.0 / calls_per_minute
#: A tick must finish inside its 15-minute beat. Both bounds are needed: the
#: call cap bounds a healthy tick, the deadline bounds one spent in backoff.
#: Whatever is left over is simply still missing next tick, and next tick
#: fetches it.
#:
#: PER PHASE, not per tick, despite the name: the universe pass and the candle
#: pass each build their own `BreakoutSource`, so each gets its own cap. The
#: universe pass spends ~16 of it and the candle pass is the one that can
#: reach 240. The DEADLINE is the candle pass's alone — the universe pass
#: is bounded by having a fixed number of calls to make.
MAX_CALLS_PER_TICK = 240

#: **This must stay under Celery's soft time limit, and by a real margin.**
#:
#: `app/workers/celery_app.py` sets `task_soft_time_limit=540` and
#: `task_time_limit=600`. The deadline was 600, so on the first production
#: tick the candle pass was killed by `SoftTimeLimitExceeded` at 540s —
#: BEFORE it reached its own stopping point, which meant it never wrote its
#: run row and never committed. Every candle it had fetched was rolled back,
#: and because `task_acks_late=True` the task was redelivered to do it again.
#: The lab looked perfectly healthy standalone, where nothing imposes a limit,
#: and silently stored nothing under the worker.
#:
#: 420 leaves two full minutes for the final upsert, the prune, the run row
#: and the commit — all of which happen AFTER the deadline stops the loop.
#: A deadline at or above the soft limit is the bug; anything comfortably
#: below it is not.
TICK_DEADLINE_SECONDS = 420
HTTP_TIMEOUT_SECONDS = 15.0
#: **GeckoTerminal's free tier is far tighter than its documented 30/min, and
#: it throttles rather than refusing outright.** Measured at three fixed
#: spacings, 15 calls each, after a cool-down:
#:
#:     2.4s apart (25/min):  8 of 15 answered 429
#:     4.0s apart (15/min):  7 of 15
#:     6.0s apart (10/min):  5 of 15
#:
#: In every run the first ~6 calls passed and the refusals began after that,
#: which is a bucket of about six with a slow refill — spacing alone cannot
#: avoid it, because the SUSTAINED rate it allows is roughly 4-5 a minute.
#:
#: So 429s are normal operation here, not an incident, and the retry has to
#: outlast them: seven attempts from a 2-second base with a 60-second ceiling
#: expects ~60s of waiting, against the ~35s a refusal was measured to last.
#: The spacing above stays because it keeps the bucket from emptying in a
#: burst; the retry is what absorbs the rest.
MAX_ATTEMPTS = 7
BACKOFF_INITIAL_SECONDS = 2.0
BACKOFF_MAX_SECONDS = 60.0
#: A default httpx agent is refused by some CDNs; name the lab honestly.
HTTP_USER_AGENT = "memescope-breakout-lab/1.0"

#: Tick records kept for `data_health()`.
RUN_HISTORY = 500
#: The beat's period, in seconds.
TICK_SECONDS = 15 * 60


# ============================================================================
# Phase 2 — setup detection
# ============================================================================

# --- levels (`levels.py`) -----------------------------------------------------
#: Fewest daily bars a token needs before any level is computed. Below it the
#: token is SKIPPED, not an error — a pool a fortnight old has no resistance
#: history worth the name.
MIN_DAILY_BARS = 14
#: A swing high must exceed every high this many bars on each side, and the
#: right side must have CLOSED — an unconfirmed swing is hindsight.
SWING_LOOKBACK = 3
#: Swing highs within this fraction of each other are one level.
CLUSTER_PCT = 0.03
#: Daily ATR period, and the two windows the compression component compares.
DAILY_ATR_PERIOD = 14
ATR_FAST_DAYS = 5
ATR_SLOW_DAYS = 20
#: Windows for the volume mean and the range the close is placed inside.
VOLUME_MEAN_DAYS = 20
RANGE_DAYS = 10

# --- momentum (`momentum.py`) -------------------------------------------------
#: Weights, summing to 1. With no hourly candles the hourly weight is dropped
#: and the rest are renormalised — see `HOURLY_MISSING_SCORE_CAP`.
MOMENTUM_WEIGHTS: dict[str, float] = {
    "volume": 0.30,
    "structure": 0.15,
    "position": 0.25,
    "compression": 0.15,
    "hourly": 0.15,
}
#: Today+yesterday volume against the 20-day mean, as a ratio; this is where
#: the component scores full marks.
VOLUME_RATIO_CAP = 3.0
#: Daily bars whose low is compared with the one before it.
STRUCTURE_BARS = 3
#: Hourly closes the confirmation component reads.
HOURLY_CONFIRM_BARS = 12
#: A score computed without the hourly component cannot exceed this. It is a
#: CAP, not a penalty: the four remaining components are renormalised to sum
#: to one, then the result is clipped. A token we can only half-see must not
#: outrank one we can see completely.
HOURLY_MISSING_SCORE_CAP = 80

# --- the state machine (`setups.py`) ------------------------------------------
#: Momentum floors.
WATCH_SCORE = 50
PRE_SCORE = 65
#: How far below the nearest resistance each state reaches, in percent.
WATCH_ZONE_PCT = 15.0
PRE_ZONE_PCT = 6.0
#: An hourly close this far ABOVE resistance is a confirmed break.
BREAK_CONFIRM_PCT = 1.0
#: A setup that reached PRE_BREAKOUT and then fell this far below resistance
#: (or lost its momentum floor) has failed.
FAIL_PCT = 12.0
#: An episode open this long without breaking out or failing EXPIRES.
MAX_EPISODE_HOURS = 168

# --- outcomes -----------------------------------------------------------------
#: Outcome columns are filled once this many hours have passed since the
#: episode's reference price, so `pct_at_72h` has bars to read.
OUTCOME_WINDOW_HOURS = 72
#: The hypothetical trailing stop recorded against every episode: a $100
#: position that exits when its value falls this far below its high-water
#: value. Phase 3's live trader uses the same rule at its own slot size.
TRAIL_NOTIONAL_USD = 100.0
TRAIL_USD = 25.0


# ============================================================================
# Phase 3 — the paper trader
# ============================================================================

def trading_enabled() -> bool:
    """A SECOND flag, separate from the lab's. Detection and recording are
    safe to run anywhere; opening positions is a different decision, and one
    switch for both would mean you could not have the watchlist without the
    book. Read at call time, like the other."""
    return _flag("BREAKOUT_TRADING_ENABLED")


#: Paper only. There is no key, no signer and no route that could execute.
STARTING_EQUITY = 1000.0
SLOTS = 10
#: Memecoin-realistic, and deliberately pessimistic: 1% of slippage on a
#: $100 order into a $50k pool is generous to us, not to the model.
SLIPPAGE_BPS = 100
FEE_BPS = 30
#: A pool thinner than this is not entered at all.
MIN_LIQ_FOR_ENTRY = 50_000.0
#: And a position may not be more than this share of the pool's liquidity —
#: the honest limit on a $100 order is the pool, not the wallet.
MAX_POOL_SHARE_PCT = 0.5
#: The trailing stop, as a PERCENTAGE of the slot size at entry rather than a
#: fixed $25. At the starting equity a slot is $100 and 25% is exactly the
#: $25 the brief asks for; storing it as a percentage means it still is 25%
#: of the position after the account has grown or shrunk.
TRAIL_PCT = 25.0
#: A position still under water after this many hours is closed.
MAX_HOLD_HOURS = 168
#: Drawdown from peak equity that trips the kill switch. Only a CLI reset
#: clears it.
MAX_DRAWDOWN_PCT = 40.0
#: Equity points kept.
EQUITY_HISTORY_HOURS = 24 * 90
