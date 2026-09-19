"""The Momentum Lab's own configuration. Not `app.core.config`.

Environment variables are read at call time (a worker that cached a flag at
import would keep running a lab the operator turned off). Everything else is a
constant here, so the rules a strategy traded under are readable in one file.
"""

from __future__ import annotations

import os
from decimal import Decimal, InvalidOperation


def _flag(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    try:
        return int(raw) if raw else default
    except ValueError:
        return default


def _dec(name: str, default: str) -> Decimal:
    raw = os.getenv(name, "").strip()
    try:
        value = Decimal(raw) if raw else Decimal(default)
    except (InvalidOperation, ValueError):
        return Decimal(default)
    return value if value.is_finite() else Decimal(default)


def enabled() -> bool:
    """The single gate. Off, every task returns before opening a session and
    every route answers `running: false`."""
    return _flag("LAB_MOMENTUM_ENABLED")


# --- the universe -------------------------------------------------------------
#: THE RULE: a token's market must be older than this. Measured from its FIRST
#: pool (Jupiter's `firstPool.createdAt`), falling back to the mint's own
#: `createdAt`. A token minted a month ago whose first pool opened yesterday is
#: a new launch, not an established one, and is not admitted.
MIN_AGE_DAYS = _int("LAB_MOMENTUM_MIN_AGE_DAYS", 7)
#: Jupiter's token lists. Twelve calls a refresh: every list, every window.
#: Built by what trades, so the universe is tokens people are actually buying.
JUPITER_URL = "https://lite-api.jup.ag/tokens/v2"
JUPITER_LISTS: tuple[str, ...] = ("toptraded", "toptrending", "toporganicscore")
JUPITER_WINDOWS: tuple[str, ...] = ("5m", "1h", "6h", "24h")
JUPITER_LIMIT = 100
#: Jupiter tags whose WHOLE list joins the universe, one call each. "verified"
#: is ~3,500 tokens; on 2026-09-19 it took the universe from 142 (the lists
#: above, capped at 100 each whatever `limit` asks) to ~540 tokens older than
#: seven days with a $50k pool. Most of them are quiet, and the 20-trade floor
#: means a quiet one only counts on the day it wakes up.
JUPITER_TAGS: tuple[str, ...] = ("verified",)
#: Not momentum trades: dollars, staked SOL, lending receipts, wrapped majors
#: and tokenised stocks (which move with their exchange's hours, not this
#: market). Matched against Jupiter's own tags.
EXCLUDED_TAGS = frozenset({
    "stable", "lst", "original-lst", "yield", "yb", "jup-lend-earn", "major",
    "stocks", "xstocks", "equities", "rwa", "prestocks",
})
WSOL_MINT = "So11111111111111111111111111111111111111112"
USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
USDT_MINT = "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"
#: A pool quoted in anything else prices the token THROUGH another volatile
#: token; the universe wallet once read RAY at $1.10T that way.
QUOTE_MINTS = frozenset({WSOL_MINT, USDC_MINT, USDT_MINT})
EXCLUDED_MINTS = QUOTE_MINTS
#: Jupiter's own liquidity figure at admission, and the pinned pool's at
#: every candle. $100 into $50k of pool is 0.4% of impact a leg.
MIN_LIQUIDITY_USD = _dec("LAB_MOMENTUM_MIN_LIQUIDITY_USD", "50000")
MIN_PAIR_LIQUIDITY_USD = _dec("LAB_MOMENTUM_MIN_PAIR_LIQUIDITY_USD", "25000")
#: A token stays polled this long after it last appeared on any list.
UNIVERSE_TTL_HOURS = _int("LAB_MOMENTUM_UNIVERSE_TTL_HOURS", 48)
#: Hard cap on the polled set: 30 pools a DexScreener call, so 700 is 24 calls
#: a tick (~8s of pacing inside a 30s tick).
MAX_PAIRS = _int("LAB_MOMENTUM_MAX_PAIRS", 700)
#: New tokens given a pool per refresh, and the pace of those lookups. They run
#: with NO lock held (`plan_universe`), so a tick never waits on them, and
#: slower than a tick polls, because the host's DexScreener allowance is shared
#: with enrichment and the graduation lab.
UNIVERSE_MAX_RESOLVE = _int("LAB_MOMENTUM_UNIVERSE_MAX_RESOLVE", 300)
RESOLVE_CALLS_PER_MINUTE = _int("LAB_MOMENTUM_RESOLVE_CALLS_PER_MINUTE", 100)

# --- DexScreener ----------------------------------------------------------------
DEXSCREENER_URL = "https://api.dexscreener.com"
#: `/latest/dex/pairs/solana/{a,b,...}` takes thirty. Polled BY PAIR ADDRESS,
#: so a mark can never hop to another pool: `/tokens/v1` returns every pool a
#: mint trades in, in no stable order, and that hop once fabricated +$2,414
#: of a +$1,712 paper book in the graduation lab.
DEXSCREENER_BATCH = 30
#: Pacing, not a burst allowance: one call per 60/rate seconds, so a tick's
#: fifteen calls land in five seconds. The pairs endpoints allow 300 a minute;
#: at a 30-second tick this lab AVERAGES ~30, leaving the rest to enrichment
#: and the graduation lab, which share the host's IP.
DEXSCREENER_CALLS_PER_MINUTE = _int("LAB_MOMENTUM_DEX_CALLS_PER_MINUTE", 180)
JUPITER_CALLS_PER_MINUTE = 30
HTTP_TIMEOUT_SECONDS = 15.0
HTTP_MAX_ATTEMPTS = 3
#: Both hosts 403 a default client user-agent.
USER_AGENT = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/128.0 Safari/537.36")
#: A DexScreener row fetched at T quotes the market at about T - 27s (measured
#: by the graduation lab). Every sample is filed at that market moment, and a
#: fill may only use a sample whose market moment is AFTER the decision.
FEED_LAG_S = _int("LAB_MOMENTUM_FEED_LAG_S", 27)
#: A sample this many times above OR below the previous one, inside two
#: minutes, is refused as a bad print; after two minutes the new level is
#: taken, so a real crash is recognised, late.
#:
#: Both ways since 2026-09-19. It was upward only, on the idea that a false
#: crash only ever hurts a long book. It does worse than hurt: DexScreener
#: printed ANTFUN at $0.0000005 against $0.083 (and XMR, UNI, ENA, SUI and
#: KNOTS likewise, 40 of 54,028 bars) — a buy filled on such a print books a
#: gain of millions of percent, a stop fires on a pool that never moved, and a
#: time exit on one books -100%. None had yet; the replay of a 25% stop found them.
GLITCH_X = Decimal(3)

# --- candles --------------------------------------------------------------------
#: The stored candle. 15m and 1h are aggregated from it when they close.
BASE_BAR_S = 300
TIMEFRAMES: dict[str, int] = {"5m": 300, "15m": 900, "1h": 3600}
#: How many earlier bars define "normal" for a token: its median body and the
#: range a breakout must clear.
LOOKBACK_BARS = 24
#: A token needs this many of those bars on record before any rule may judge
#: it. The first two hours after admission are history, not signals.
MIN_HISTORY_BARS = 20
#: The trend filter's average.
TREND_BARS = 48
#: A 5m bar is judged only if at least this many samples built it; a bar made
#: of one sample is a single price, not a candle.
MIN_SAMPLES_5M = 3
#: A candle counts only with real trading: at least this many trades for every
#: five minutes it spans (20 = four a minute; 60 on a 15m bar, 240 on 1h). The
#: rolling rule needs the same in its five-minute window, and the random
#: controls draw only from candles that pass it.
#:
#: Added 2026-09-19, 40 minutes after launch. On prod the median watched coin
#: averaged 12 trades per 5 minutes over a day and 3 in a quiet hour, and 13 of
#: the first 16 candles that moved 2%+ had fewer than 10 trades: one or two
#: buyers in a thin pool, not momentum. The lab's first trade was one of them
#: (+9.5% on two buys). "3x normal volume" cannot catch it, because on a quiet
#: coin three times normal is still a handful of trades.
MIN_TRADES_PER_5M = _int("LAB_MOMENTUM_MIN_TRADES_PER_5M", 20)
#: The share of an aggregated bar's 5m bars that must exist.
MIN_COVERAGE = Decimal("0.75")
CANDLE_RETENTION_DAYS = _int("LAB_MOMENTUM_CANDLE_RETENTION_DAYS", 3)
SIGNAL_RETENTION_DAYS = 14

# --- the book -------------------------------------------------------------------
#: Every strategy's wallet starts here.
START_USD = Decimal("1000")
#: The size every trade is MEASURED at. The board's splits re-price the same
#: trades at other sizes; the impact each trade paid scales with the ticket.
TICKET_USD = Decimal("100")
#: The wallet's splits: tickets the $1,000 is cut into. 10 x $100 is the
#: headline because it is the size the trades were measured at.
SPLITS: tuple[int, ...] = (1, 2, 5, 10, 20)
HEADLINE_SPLIT = 10
#: The book records at most this many positions per strategy at once, so the
#: 20 x $50 split can still be walked. A signal arriving with every slot full
#: is skipped, never queued.
MAX_OPEN_PER_ARM = _int("LAB_MOMENTUM_MAX_OPEN_PER_ARM", 20)
#: A wallet walk stops funding once cash is under half a ticket.
MIN_STAKE_FRACTION = 0.5

# --- costs ----------------------------------------------------------------------
#: Pool fee plus router cut, a side. Established Solana pools (Raydium CPMM
#: and CLMM, Meteora DLMM, Orca) charge 1-30 bps and Jupiter adds ~10; a live
#: Jupiter round trip measured 0.50-0.56% at $10-$50 on this population
#: (Track Record V2, 2026-08-23). 30 bps a side plus the impact below prices
#: a $100 round trip at 0.7-1.4%, at or above what was measured.
FEE_BPS = _int("LAB_MOMENTUM_FEE_BPS", 30)
#: pump.fun's own AMM charges by market cap (graduation lab, verified on
#: 111 of 111 real fills): 125 bps under ~$0.4k SOL of market cap, down to 30.
#: `(market cap in SOL, bps)`; applied only to `pumpswap` pools.
PUMPSWAP_FEE_TIERS: tuple[tuple[int, int], ...] = (
    (0, 125), (420, 120), (1_470, 115), (2_460, 110), (3_440, 105),
    (4_420, 100), (9_820, 95), (14_740, 90), (19_650, 85), (24_560, 80),
    (29_470, 75), (34_380, 70), (39_300, 65), (44_210, 60), (49_120, 55),
    (54_030, 53), (58_940, 50), (63_860, 48), (68_770, 45), (73_681, 43),
    (78_590, 40), (83_500, 38), (88_400, 35), (93_330, 33), (98_240, 30))
ROUTER_FEE_BPS = 10
#: Network plus priority fee a transaction, flat. ~0.00012 SOL.
NETWORK_FEE_USD = Decimal("0.02")
#: A buy that would move the pool further than this is refused: past a
#: slippage limit a real swap reverts, it does not fill badly.
MAX_IMPACT = Decimal("0.03")


def fee_bps(dex_id: str | None, market_cap_sol: Decimal | None) -> int:
    """The side fee a pool charges, router included."""
    if dex_id == "pumpswap":
        if market_cap_sol is None or market_cap_sol <= 0:
            pool = PUMPSWAP_FEE_TIERS[0][1]
        else:
            pool = next(bps for floor, bps in reversed(PUMPSWAP_FEE_TIERS)
                        if market_cap_sol >= floor)
        return pool + ROUTER_FEE_BPS
    return FEE_BPS


# --- timing ---------------------------------------------------------------------
#: A decided entry waits at most this long for a sample to fill it.
ENTRY_MAX_WAIT_S = 180
#: A decided exit waits this long for a fresh sample, then takes the last one.
EXIT_MAX_WAIT_S = 300
#: A position whose pool has returned nothing for this long is closed at its
#: last price and says so (`no_data`). Never at zero: one empty answer from a
#: feed is not a dead pool (the V6 lab booked 6.9% of its zeros on tokens that
#: were still trading).
NO_DATA_CLOSE_S = 3600
