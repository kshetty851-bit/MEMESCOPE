"""The lab's own configuration. Deliberately NOT `app.core.config`.

Reading the flag from the platform's settings object would mean editing that
object, and this lab edits nothing outside its own package. Environment
variables are read at call time; everything else is a constant here.

`SOLANA_RPC_URL` is the one variable name shared with the platform, because it
is the same node and there is no sense in two names for it. It is read here
directly rather than through `settings`, so the lab's configuration stays
self-contained and a test can point it somewhere else.

## Why the curve constants are overridable

They are NOT compiled into the pump.fun program. They live in a mutable
on-chain global-config account (`4wTV1YmiEkRvAtNtsSGPtUrqRYQMe5SKy2uB4Jjaxnjf`)
and pump.fun can change them. A collector that hard-coded them would keep
computing a progress number long after it became wrong, which is worse than
computing none. Every one of them is an environment variable.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from itertools import pairwise
from typing import TypeVar

_Money = TypeVar("_Money", float, Decimal)


def _flag(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def enabled() -> bool:
    """Read at call time, not at import: a test may flip it, and a worker that
    cached it at import would keep running a lab the operator turned off."""
    return _flag("LAB_GRADUATION_ENABLED")


def _dec(name: str, default: str) -> Decimal:
    raw = os.getenv(name, "").strip()
    if not raw:
        return Decimal(default)
    try:
        value = Decimal(raw)
    except (InvalidOperation, ValueError):
        return Decimal(default)
    return value if value.is_finite() else Decimal(default)


def _int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    try:
        return int(raw) if raw else default
    except ValueError:
        return default


# --- discovery: the free websocket --------------------------------------------
#: `subscribeNewToken` and `subscribeMigration` ONLY. Both are free and neither
#: needs a key. `subscribeTokenTrade` is metered and is deliberately not used:
#: progress comes from the chain instead, which costs nothing.
PUMPPORTAL_WS_URL = "wss://pumpportal.fun/api/data"
#: Where the held-position watcher subscribes. The PUBLIC Solana node, on
#: purpose and not as a fallback.
#:
#: `accountSubscribe` needs no key: measured 2026-09-15 on a pool taking 1,512
#: sells in five minutes, it delivered 44 updates in 25 seconds — one every
#: 0.6s, first arriving 1.3s after subscribing. DexScreener refreshes about
#: every 27 SECONDS, which is 45x slower and on the wrong side of the cliff
#: that decides whether a stop works at all:
#:
#:     0.6s -> FLOOR_5m $1,040      27s -> FLOOR_5m $0
#:
#: Helius refuses the websocket while its quota is spent (InvalidStatus), so
#: the public node is not the compromise here — it is the one that works.
#: Only open positions are subscribed, one to five at a time, so the public
#: node's connection limits are never close.
SOLANA_WS_URL = (os.getenv("LAB_GRADUATION_SOLANA_WS_URL", "").strip()
                 or "wss://api.mainnet-beta.solana.com")

#: Reconnect backoff, seconds. The platform's `BackoffPolicy` applies jitter.
RECONNECT_INITIAL_SECONDS = 1.0
RECONNECT_MAX_SECONDS = 60.0
#: A socket that has sent nothing for this long is treated as dead and
#: redialled. The free launch stream alone carries ~25 messages a minute, so
#: silence is a fault — and a half-open TCP connection reads exactly like a
#: quiet one.
STREAM_IDLE_TIMEOUT_SECONDS = 120.0
WS_PING_INTERVAL_SECONDS = 20.0


# --- progress: the chain ------------------------------------------------------
def rpc_url() -> str:
    """The node to poll. Any compliant Solana JSON-RPC endpoint.

    The public default works and is what this lab is sized for, but it is
    rate-limited per IP and shared with the whole world. Point this at a real
    endpoint before running the watch set anywhere near `MAX_WATCH_SET` —
    `services/rpc/registry.py` has the platform's reason for distrusting the
    public node, written after a collector quietly leaned on it.
    """
    return os.getenv("SOLANA_RPC_URL", "").strip() or "https://api.mainnet-beta.solana.com"


def safe_rpc_url() -> str:
    """`rpc_url()` with any credential stripped. Use this for ANYTHING a human
    or a log will see.

    Provider endpoints carry the key in the URL — Helius is
    `https://mainnet.helius-rpc.com/?api-key=<secret>` — so printing the
    endpoint prints the secret. This was learned the hard way: the recorder's
    startup banner wrote the full URL to stderr and put a live Helius key into
    the container log on the first production start.
    """
    raw = rpc_url()
    scheme, _, rest = raw.partition("://")
    host = rest.split("/", 1)[0].split("?", 1)[0]
    tail = raw[len(scheme) + 3 + len(host):]
    return f"{scheme}://{host}" + (" (credential redacted)" if tail.strip("/") else "")


#: pump.fun's program. The curve account is the PDA of
#: `["bonding-curve", mint]` under it.
PUMP_PROGRAM_ID = os.getenv("LAB_GRADUATION_PUMP_PROGRAM", "").strip() \
    or "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"

#: The Anchor discriminator of a `BondingCurve` account. Checked before
#: decoding: a PDA that exists but is not a curve must produce no reading
#: rather than five plausible-looking integers.
#: Confirmed live on 2026-09-11 and identical to the community decoder's
#: `PUMP_CURVE_STATE_SIGNATURE`.
CURVE_DISCRIMINATOR = bytes.fromhex("17b7f83760d8ac60")

#: How often the whole watch set is read.
#:
#: THREE seconds, not fifteen. Measured 2026-09-12: half of all graduates
#: complete their curve within a MINUTE of the lab first seeing them, and
#: only 34% were ever observed incomplete at all — 16.6% at 90% or above.
#: A fifteen-second shutter gets about four frames of the whole climb, which
#: is why the pre-graduation band is mostly invisible and why every
#: pre-graduation strategy is being tested on the half that stalled.
#:
#: It costs nothing: 500 tokens is 5 calls a poll, so 3 seconds is 100 calls a
#: minute — under two requests a second against an endpoint already paid for.
POLL_INTERVAL_S = _int("LAB_GRADUATION_POLL_INTERVAL_S", 3)
#: `getMultipleAccounts` accepts at most 100 addresses per request. A property
#: of the RPC, not of this lab, but pinned here so a change is visible.
MAX_ACCOUNTS_PER_CALL = 100
#: Token bucket, calls per minute against the node. At `MAX_WATCH_SET` 500 and
#: a 3s interval the poller needs exactly 100 a minute, so the bucket is 150:
#: sized AT the requirement it would throttle on every jitter, and throttling
#: a poller silently lengthens its interval, which is the thing being fixed.
RPC_CALLS_PER_MINUTE = _int("LAB_GRADUATION_RPC_CALLS_PER_MINUTE", 150)
#: How long a blocked bucket is re-polled before the pass gives up on a batch.
RPC_ACQUIRE_TIMEOUT_SECONDS = 30.0

#: Write a curve sample ONLY when a reserve actually moved.
#:
#: At `MAX_WATCH_SET` 500 and a 15-second interval, storing every poll is 2,000
#: rows a minute — 2.88 MILLION rows and roughly 290 MB a day — and the great
#: majority of them would be byte-identical to the row before. Measured on this
#: platform, 66.5% of live curves have had ZERO tokens bought, so most of that
#: volume is a dead curve restating itself.
#:
#: An unchanged reserve carries no information that the previous sample and its
#: timestamp do not already carry, and change detection is needed anyway for
#: `SILENT_MIN` eviction. Set false to store every poll.
SAMPLE_ON_CHANGE_ONLY = not _flag("LAB_GRADUATION_SAMPLE_EVERY_POLL")

# --- the bonding curve --------------------------------------------------------
#: Tokens the curve holds before anyone has bought. In RAW base units (6
#: decimals), because that is what the account carries — unlike the websocket,
#: which sent whole tokens.
#:
#: Confirmed live against an untouched curve on 2026-09-11:
#:     virtual_token_reserves  1,073,000,000,000,000
#:     real_token_reserves       793,100,000,000,000
#:     virtual_sol_reserves           30,000,000,006  (30 SOL, 9 decimals)
#:     token_total_supply      1,000,000,000,000,000
INITIAL_VIRTUAL_TOKEN_RESERVES = _dec(
    "LAB_GRADUATION_V_TOKENS_0", "1073000000000000")
#: Tokens actually FOR SALE on the curve. The other 206,900,000,000,000 of the
#: supply are held back to seed the AMM pool at migration and are never in the
#: curve account, which is why the curve does not empty.
INITIAL_REAL_TOKEN_RESERVES = _dec(
    "LAB_GRADUATION_REAL_TOKENS_0", "793100000000000")
#: Seeded quote reserve, 9 decimals. Recorded, not used in the progress maths —
#: progress is a pure function of the token side.
INITIAL_VIRTUAL_SOL_RESERVES = _dec("LAB_GRADUATION_V_SOL_0", "30000000000")
#: Token decimals, for turning raw reserves into whole tokens on the way out.
TOKEN_DECIMALS = 6

#: PumpPortal's `pool` field on a launch. `pump` is the bonding curve.
CURVE_POOL = "pump"
AMM_POOL = "pump-amm"
#: Launch platforms that are NOT a pump.fun curve. `bonk` has its own curve,
#: its own constants and no PDA under this program, so it is not admitted.
FOREIGN_POOLS: frozenset[str] = frozenset({"bonk"})

#: Quote denominations a launch may be priced in. A USDC-denominated curve puts
#: USDC in the reserve the SOL field normally holds; the TOKEN side, and so
#: progress, is identical. Detected at discovery from the launch message —
#: the account carries no denomination flag in the bytes this lab decodes.
QUOTE_SOL = "SOL"
QUOTE_USDC = "USDC"

# --- what gets tracked --------------------------------------------------------
#: A token is TRACKED from the first poll that puts it at or above this.
TRACK_PROGRESS_PCT = _dec("LAB_GRADUATION_TRACK_PCT", "70")
#: A checkpoint row is written the first time a token is seen at or above each.
CHECKPOINT_LEVELS: tuple[Decimal, ...] = tuple(
    Decimal(x) for x in (70, 80, 90, 95, 100)
)

#: Hard ceiling on the watch set. The poller's RPC cost is linear in this.
MAX_WATCH_SET = _int("LAB_GRADUATION_MAX_WATCH_SET", 500)
#: A candidate BELOW the tracking threshold whose progress has not changed for
#: this many minutes is evicted. Measured on progress, not on wall time: a
#: token nobody is buying is a token whose reserves do not move.
SILENT_MIN = _int("LAB_GRADUATION_SILENT_MIN", 30)
#: A TRACKED token is never evicted for silence. It leaves only when it
#: graduates (plus the post-graduation window) or when it has been stale this
#: long, which is the backstop against a curve that parks at 94% for ever.
STALE_HOURS = _int("LAB_GRADUATION_STALE_HOURS", 24)
#: How long a graduated token is sampled FROM ITS POOL OPEN — the first price
#: DexScreener answers with, not the migration.
#:
#: The two are ~9 minutes apart in practice, and measuring from the migration
#: loses that off the end: the sampler stopped at ~51 minutes of prices while
#: the outcome floor needs 55 of 60 counted from the open, so NO outcome could
#: ever qualify. Both sides now run on the same clock.
POST_MIGRATION_SECONDS = 60 * 60
#: How long to wait for a pool to appear at all before giving up on a
#: graduate. Bounds the wait for a token whose pair never gets indexed.
POSTGRAD_OPEN_GRACE_SECONDS = _int("LAB_GRADUATION_OPEN_GRACE_S", 15 * 60)

# --- post-graduation market data ----------------------------------------------
DEXSCREENER_URL = "https://api.dexscreener.com"
GECKOTERMINAL_URL = "https://api.geckoterminal.com/api/v2"
NETWORK = "solana"
#: How often a graduated token's pair is sampled.
#: TWENTY seconds, was sixty.
#:
#: A position can only leave at a price that was recorded, so the mark
#: interval is the floor on exit accuracy. With the tournament re-scoped to
#: 1-3 minute holds, sixty-second marks meant a two-minute hold could only
#: exit at 2:00 or 3:00 — a fifty per cent overshoot on the one variable the
#: whole re-scope is about, and the extra minute is where the wipeouts live.
#:
#: It costs almost nothing: roughly thirty tokens sit in the post-graduation
#: window and `DEXSCREENER_BATCH` is 30, so this is two or three requests a
#: minute against an endpoint that allows hundreds. Well short of a burst.
POSTGRAD_INTERVAL_S = _int("LAB_GRADUATION_POSTGRAD_INTERVAL_S", 20)
#: How often the mints we currently HOLD are re-priced.
#:
#: Three seconds, against twenty for the bulk loop — and the bulk loop spreads
#: its batch across the whole watch set, so any one token is seen about once a
#: MINUTE. That minute is where the money goes. Collapses here are cascades of
#: roughly 247 small sells (median $159 each, where $352 is needed to move
#: price 10%) falling 1.14% a second. Sixty-one seconds of that is 69.6%,
#: which is why the median fill on a stop was -64%.
#:
#: Open positions are one to five mints — a single DexScreener call — so this
#: costs one request every three seconds and NOTHING on the RPC quota, which
#: is exhausted.
HELD_INTERVAL_S = _int("LAB_GRADUATION_HELD_INTERVAL_S", 3)
#: How far price must move before a websocket update is written as a sample.
#:
#: The socket delivers one update every ~0.6s. Writing all of them would flood
#: a table already driving this box to 88% disk, and the record is not the
#: point — a FRESH MARK when a stop needs it is. Half a percent is well inside
#: the 1.14%-per-second fall these stops exist to catch.
HELD_WRITE_PCT = _dec("LAB_GRADUATION_HELD_WRITE_PCT", "0.005")
#: Whether websocket prices are WRITTEN as marks. The kill switch.
#:
#: Off from 2026-09-15 to 2026-09-16: the socket's raw reserve ratio was
#: written against entry prices that carry token decimals, and for twenty
#: minutes it put FLOOR_4m_SL at $17,517 on eight trades. Back on once both
#: decimals were read off the mint accounts and every mint's first price is
#: checked against DexScreener before it is written (`held_watch.MarkWriter`).
HELD_WRITE_ENABLED = os.getenv(
    "LAB_GRADUATION_HELD_WRITE_ENABLED", "1").strip().lower() in {"1", "true", "yes"}
#: A quiet pool is re-read from the chain this often, and its mark re-written.
#: A pool's price cannot move without its vaults changing, so silence on a
#: healthy subscription means an unchanged price — but "healthy" is proven by
#: reading, not assumed, which is what stops a dead subscription from
#: asserting a frozen price.
HELD_HEARTBEAT_S = _int("LAB_GRADUATION_HELD_HEARTBEAT_S", 10)
#: How long the book prefers a socket mark over a DexScreener row stamped
#: LATER. A DexScreener row carries its fetch time but a price ~27s old, so
#: "newest row" is not "newest price". Three heartbeats: past this the socket
#: is presumed down and the book falls back to whatever is newest.
HELD_TRUST_S = _int("LAB_GRADUATION_HELD_TRUST_S", 30)
#: A mint's first socket price may not sit more than this factor ABOVE
#: DexScreener's. A decimals error is a power of ten; DexScreener's own lag put
#: an honest price 17% away on a fresh graduate. Below is never refused — that
#: is a rug, which DexScreener can lag for minutes. See `MarkWriter`.
HELD_SCALE_BAND = _dec("LAB_GRADUATION_HELD_SCALE_BAND", "2")
#: A pool-open buy is priced off the pool's own vaults, not DexScreener's first
#: report, which can predate the pool's first big buy: Bluey (2026-09-17) was
#: booked at +1,044% because the feed's first price sat 11x under where the pool
#: already traded; on-chain it made +4%. The pool's price may differ from the
#: feed's by up to this factor either way before a scale error is the likelier
#: explanation and the buy is skipped. Wide on purpose: 11x was the market.
PAPER_ENTRY_CHAIN_BAND = _dec("LAB_GRADUATION_PAPER_ENTRY_CHAIN_BAND", "50")
#: Keepalive on the socket, seconds. A half-open connection reads exactly like
#: a quiet market; a missed pong turns it into a drop within two of these.
HELD_PING_S = _int("LAB_GRADUATION_HELD_PING_S", 5)
#: THE EARLY ARM, B3E_198k_5m. Every pumpswap graduation's pool is watched on
#: the vault socket for this long after the migration, and the first reading
#: at B3's depth is an entry.
#:
#: Ninety seconds, from where B3's own entries land: DexScreener first reports
#: a B3 pool a median 52s after the migration (p10 27s, p90 84.5s — 175 entries
#: over 48h, 2026-09-16). Watching longer would buy pools B3 never could have.
EARLY_WINDOW_S = _int("LAB_GRADUATION_EARLY_WINDOW_S", 90)
#: A crossing older than this is not an entry: a wallet acts on one in
#: seconds, and the book ticks every ten.
EARLY_MAX_AGE_S = _int("LAB_GRADUATION_EARLY_MAX_AGE_S", 30)
#: B3's floor, in dollars of pool depth. `test_tournament` holds it to the band.
EARLY_FLOOR_USD = Decimal(198_000)
#: Wrapped SOL. Depth is priced with the SOL rate, so only a SOL-quoted pool
#: can be priced here at all.
WSOL_MINT = "So11111111111111111111111111111111111111112"
#: The migration feed's name for a pumpswap graduation — the only venue whose
#: pool `parse_pool` reads.
PUMPSWAP_VENUE = "pump-amm"

#: THE FAST ARMS, E75_4m and E75T_4m (2026-09-19). The Tape Lab rebuilt 18
#: days of graduations off the chain (5,716 coins, `backend/app/labs/tape/`):
#: bought 15s after the pool opened instead of 45s, the same coins made +0.59%
#: a trade more (t 3.17 on unseen days), and keeping only coins whose operator
#: had 2+ earlier coins and no rug made +1.24% a trade on unseen days against
#: -0.45% for all of them. Both are pre-registered there; these arms test them
#: forward.
#:
#: A graduation is read on every tick from this many seconds after its
#: migration message until FAST_MAX_AGE_S, and bought the first time its pool's
#: own reserves show the BASE floor. The backtest bought at 5-15s.
FAST_MIN_AGE_S = _int("LAB_GRADUATION_FAST_MIN_AGE_S", 5)
FAST_MAX_AGE_S = _int("LAB_GRADUATION_FAST_MAX_AGE_S", 30)
#: Graduations read per tick, so a tick stays inside its 3-second cadence.
FAST_MAX_PER_TICK = _int("LAB_GRADUATION_FAST_MAX_PER_TICK", 8)
#: Operators are RECORDED from this depth, below the $75k the arms buy at: the
#: backtest learned reputations from every coin over ~$50k, and a record kept
#: only from the coins bought would learn only from what the rule let through.
OPERATOR_RECORD_FLOOR_USD = Decimal(50_000)

#: The repeat-rugger refusal (Karthik, 2026-09-20). An address the lab has
#: already seen on this many coins, this share of them rugged by the time of
#: the buy, refuses the coin. Replayed point-in-time over BASE_75k_5m's 655
#: trades since 14 Sep it refuses 30 of them, 12 of the 32 rugs, and the book
#: goes from +$132 to +$894 at $100 a trade. Every threshold pair from
#: (10, 5%) to (50, 20%) improves it, so these two are not a fitted edge.
REPEAT_MIN_COINS = _int("LAB_GRADUATION_REPEAT_MIN_COINS", 20)
#: Whole per cent, not a fraction: the driver infers a bind parameter's type
#: from what it is multiplied by, so `0.10 * count(*)` arrives as 0 and refuses
#: every address on the list. Integers cannot be truncated into a different
#: rule.
REPEAT_MIN_RUG_PCT = _int("LAB_GRADUATION_REPEAT_MIN_RUG_PCT", 10)
#: How long that list is held before it is read again. The labels behind it
#: arrive minutes apart; the tick runs every three seconds.
REPEAT_TTL_S = _int("LAB_GRADUATION_REPEAT_TTL_S", 300)
#: PRE-REGISTERED, 2026-09-20, and frozen before BASE_75k_quiet_5m took a
#: trade: a coin whose pool has already had this many transactions when the
#: book is about to buy is refused by the arms that ask for a quiet pool.
#:
#: Measured on 579 of BASE_75k_5m's own trades since 14 Sep, counting each
#: pool's transactions from its migration to the moment of that buy (on-chain,
#: nothing the book did not already know): rug rate 2.8% under 40 txs, 3.1%
#: at 40-70, 0% at 70-100, then 11.1% at 100-150 and 17.1% over 250. The jump
#: sits at 100, the gradient survives dropping the 16 Sep rug campaign
#: (2.6/3.7/0.0/11.1/10.3%) and the last three days alone (4.9 -> 18.2%), and
#: refusing at 100 is the best of the cuts tried on the five non-campaign days
#: (+$301 at $100 a trade, positive on four of them).
#:
#: It is a RISK GRADIENT, not a filter: quiet pools rug too (RICH on 19 Sep had
#: 25 transactions), and busy ones win (three +30% trades on 17 Sep). That is
#: why this runs as its own arm against the baseline instead of being added to
#: a live book.
QUIET_MAX_POOL_TXS = _int("LAB_GRADUATION_QUIET_MAX_POOL_TXS", 100)

#: A pool-open candidate the fast path never recorded is read at the buy
#: instead, up to this many a tick. One deep coin in five had no record at all,
#: and a coin with no record is bought with no money check (EVO, 20 Sep).
ENTRY_OPERATOR_MAX_READS = _int("LAB_GRADUATION_ENTRY_OPERATOR_MAX_READS", 4)
#: A wallet holding this share of supply at entry is the operator's.
OPERATOR_MIN_SHARE = Decimal("0.01")
#: A coin rugged when its pool price is down this much this long after entry.
#: It counts against its operator only from then on, never before.
OPERATOR_LABEL_AFTER_S = 300
OPERATOR_RUG_MOVE = Decimal("-0.5")
#: A pool still unreadable this long after its label was due stays unlabelled
#: and is left out of every operator's record.
OPERATOR_LABEL_GIVE_UP_S = 120
#: Trusted: at least this many earlier labelled coins share one of the
#: operator's wallets or funders, and none of them rugged.
OPERATOR_TRUST_MIN_COINS = 2
#: DexScreener's name for the pump.fun bonding curve, which is not a pool.
#: See `PostGradSampler._accept`.
CURVE_DEX_ID = "pumpfun"
#: `/tokens/v1/{chain}/{addresses}` takes a comma-separated list. Thirty is the
#: documented ceiling and the number the Breakout lab measured against.
DEXSCREENER_BATCH = 30
#: DexScreener's token endpoints allow 300 requests a minute. A 60-minute
#: window over ~31 graduations an hour is two calls a minute, so this cap is
#: never the binding constraint — it is here to stop a bug becoming a ban.
DEXSCREENER_CALLS_PER_MINUTE = _int("LAB_GRADUATION_DEX_CALLS_PER_MINUTE", 60)
#: GeckoTerminal's free tier is 30 calls a minute and it punishes bursts.
GECKOTERMINAL_CALLS_PER_MINUTE = _int("LAB_GRADUATION_GT_CALLS_PER_MINUTE", 25)
#: Minute candles asked for in one backfill.
BACKFILL_MINUTES = 60
#: A gap longer than this in a token's post-graduation samples is backfilled
#: from GeckoTerminal. Two intervals, so one late poll is not a gap.
BACKFILL_GAP_SECONDS = POSTGRAD_INTERVAL_S * 2
HTTP_TIMEOUT_SECONDS = 20.0
HTTP_MAX_ATTEMPTS = 4

# --- writing ------------------------------------------------------------------
#: The buffer drains on whichever comes first.
FLUSH_INTERVAL_SECONDS = 5.0
FLUSH_MAX_ROWS = 500
#: A hard ceiling, so a database outage costs memory but not the process.
BUFFER_MAX_ROWS = 50_000

# --- pruning ------------------------------------------------------------------
#: A token first seen this long ago that never migrated has its curve samples
#: deleted. Its `grad_tokens` row and its checkpoints are kept for ever.
PRUNE_AFTER_HOURS = 24
#: Never prune more tokens in one beat than this: the worker's soft time limit
#: is 540s and it kills a task BEFORE it commits.
PRUNE_MAX_TOKENS_PER_RUN = 500
PRUNE_INTERVAL_SECONDS = 15 * 60

# --- features -----------------------------------------------------------------
#: Checkpoint levels features are computed at. 100 is excluded: it IS the
#: graduation, so a feature measured there could not be used to decide an entry
#: before it. Phase 3 tests entry levels, and an entry at 100 is not an entry.
FEATURE_LEVELS: tuple[Decimal, ...] = tuple(Decimal(x) for x in (70, 80, 90, 95))
#: Velocity look-backs, in minutes.
VELOCITY_WINDOWS: tuple[int, ...] = (5, 15)
#: The activity-proxy window: samples-with-change in the last this-many minutes.
ACTIVITY_WINDOW_MIN = 15
#: A quiet run of at least this long between two reserve changes is one stall.
STALL_MIN = 5
#: A fall of this many progress POINTS from a running peak, after a checkpoint
#: and before graduation, sets that checkpoint's retrace flag.
RETRACE_DROP_PTS = _dec("LAB_GRADUATION_RETRACE_PTS", "5")

#: Outcome offsets from the pool open, in minutes.
RETURN_OFFSETS_MIN: tuple[int, ...] = (2, 5, 15, 30, 60)
#: The outcome window.
OUTCOME_WINDOW_MIN = 60
#: Outcomes are NULL unless at least this many distinct minutes of the window
#: carry a post-graduation sample. A return computed over a series with holes
#: in it is a number with no error bar, and Phase 3 would be judged on it.
OUTCOME_MIN_COVERAGE_MIN = _int("LAB_GRADUATION_MIN_COVERAGE_MIN", 55)
#: A graduate is not processed until its whole outcome window has closed, plus
#: this much slack for the last poll and its flush to land.
FEATURES_SETTLE_MIN = 5
#: Never compute more tokens in one beat than this: the worker's soft time
#: limit is 540s and it kills a task BEFORE it commits.
FEATURES_MAX_PER_RUN = _int("LAB_GRADUATION_FEATURES_MAX_PER_RUN", 500)
#: How often the beat recomputes.
FEATURES_INTERVAL_SECONDS = 10 * 60

# --- the replay backtester ----------------------------------------------------
#: Everything in the backtester is denominated in the QUOTE currency, because
#: that is the only unit both sides of a pre-graduation trade exist in: the
#: curve prices in SOL, and DexScreener's `price_native` is SOL too. Converting
#: the curve leg to USD would need a SOL/USD rate this lab does not record, and
#: taking one from the token's own post-graduation samples would be reading the
#: future to price a decision made before it.
#:
#: The consequence, written down because it will surprise someone:
#: `grad_features.return_*` is computed in USD and these are in SOL, so the two
#: differ by however much SOL/USD moved during the hold. Minutes, so usually
#: fractions of a percent — but not zero.
BACKTEST_NOTIONAL_QUOTE = _dec("LAB_GRADUATION_NOTIONAL_QUOTE", "0.5")
#: PumpSwap's take, per side, on the POST-graduation AMM legs.
#:
#: 25 bps, which is PumpSwap's published swap fee. It was 100 — the
#: bonding-curve constant — which is the wrong schedule for an AMM leg and
#: overcharged every post-graduation trade fourfold.
BACKTEST_PUMP_FEE_BPS = _int("LAB_GRADUATION_PUMP_FEE_BPS", 25)
#: The fee inside the bonding-curve fill maths. Separate from the one above so
#: the curve and the AMM can be priced differently, because they are.
#:
#: 125 bps: pump.fun's public fee page states the LIVE bonding-curve schedule
#: as 1.25% total (0.95% protocol + 0.30% creator). Their program README still
#: documents `fee_basis_points = 100`, which is the older constant — set this
#: to 100 to reproduce that instead. The live number is the default because a
#: backtest should charge what a trader actually pays.
BACKTEST_CURVE_FEE_BPS = _int("LAB_GRADUATION_CURVE_FEE_BPS", 125)
#: Slippage per side, in bps. 25.
#:
#: Was 150, inherited from the brief, and it was an assumption nobody had
#: checked. Measured on 405 recorded graduations: median pool depth at the
#: open is $97,770, and constant-product impact for an order of S into a pool
#: of depth L is about S/L — so a $100 order moves the price 0.10%, and even
#: the shallowest quartile (pools near $17,000) costs 0.58%. 150 bps was
#: charging fifteen times the median.
#:
#: 25 bps rather than the 10 the median implies, because depth varies and the
#: error that matters is the one that flatters the book: this sits near the
#: 75th percentile of impact at $100. It is a stated approximation of a real
#: quantity, which the 150 never was.
BACKTEST_SLIP_BPS = _int("LAB_GRADUATION_SLIP_BPS", 25)
#: A flat network fee per side, in quote: what a real swap paid, not a guess.
#:
#: 0.0001075 SOL. The repo's real mainnet swap (tests/unit/fixtures) paid
#: 105,000 lamports a side — 5,000 base plus 100,000 priority — and closing the
#: emptied token account afterwards (the wallet's sweep, which returns the
#: rent) is one more 5,000-lamport transaction per round trip. It was 0.002, a
#: guess twenty times too high that charged ~0.2% a side for nothing.
BACKTEST_PRIORITY_FEE_QUOTE = _dec("LAB_GRADUATION_PRIORITY_FEE_QUOTE", "0.0001075")
#: Concurrent positions. A signal arriving with every slot full is SKIPPED and
#: counted, never queued: a backtest that queues signals is quietly assuming
#: capital it did not have.
BACKTEST_MAX_SLOTS = _int("LAB_GRADUATION_MAX_SLOTS", 10)

#: An OPTIONAL extra haircut on a dead-curve exit, on top of the exact
#: constant-product sell the position is already closed at.
#:
#: Default 0. It used to be 0.5 and used to be the whole model — the position
#: was written off at half its last observed PRICE, which is a guess. It is now
#: priced by selling the actual token balance back into the actual reserves,
#: which is arithmetic. This knob remains for the part arithmetic cannot see:
#: that a stalled curve may have no bid at any size, and that the sell may
#: simply not land. Set it above 0 to charge for that.
PRE_GRAD_DEAD_HAIRCUT = _dec("LAB_GRADUATION_DEAD_HAIRCUT", "0")
#: How long a pre-graduation entry waits for a migration before it is dead.
PRE_GRAD_DEAD_HOURS = _int("LAB_GRADUATION_DEAD_HOURS", 24)

# --- the forward paper book ---------------------------------------------------
#: Its OWN flag, on top of the lab's. The recorder can run for weeks before
#: anything opens a position, and turning the lab on must not start a book.
def paper_enabled() -> bool:
    return enabled() and _flag("LAB_GRADUATION_PAPER_ENABLED")


#: The book is denominated in DOLLARS, because that is how it was specified.
#:
#: Each position is sized in USD and converted to quote at the SOL/USD rate
#: OBSERVED when it opens — DexScreener answers with `price_usd` and
#: `price_native` for the same pair at the same instant, so the rate is a
#: measurement rather than an assumption, and it is stored on the position so
#: a later move in SOL cannot rewrite what a past trade was worth. That is
#: also how a real order behaves.
PAPER_CAPITAL_USD = _dec("LAB_GRADUATION_PAPER_CAPITAL_USD", "1000")
#: $100, not $10. The priority fee is FIXED in SOL — about $0.21 a
#: transaction — so as a share of the position it explodes as the position
#: shrinks: 2.06% a side at $10 against 0.21% at $100. Execution cost is a
#: U-curve (fixed fee at the bottom, price impact at the top) and it bottoms
#: out between $100 and $250 at roughly 0.56% a side. The $10 book was paying
#: 4.65% round trip against a break-even of about 2%, so it could not have won
#: whatever its rules were.
PAPER_NOTIONAL_USD = _dec("LAB_GRADUATION_PAPER_NOTIONAL_USD", "100")
#: Only used when a token answers with one price and not the other, which
#: should not happen on the DexScreener path and is refused rather than
#: guessed — see `paper._rate`.
PAPER_QUOTE_FALLBACK = _dec("LAB_GRADUATION_PAPER_QUOTE_FALLBACK", "0")
PAPER_MAX_SLOTS = _int("LAB_GRADUATION_PAPER_SLOTS", 10)
#: Trailing stop, off the running peak. ZERO DISABLES IT.
#:
#: Disabled deliberately. Replayed over 430 recorded graduations a trailing
#: stop made every hold worse, at every level tested (20/30/50%) and at every
#: cost: it exits into the gap rather than at the stop, so it converts a
#: drawdown into a realised loss without avoiding one.
PAPER_TRAILING_PCT = _dec("LAB_GRADUATION_PAPER_TRAILING_PCT", "0")
#: Take profit, as a multiple of the price paid. ANYTHING <= 1 DISABLES IT.
#:
#: Disabled deliberately. Only 7.4% of graduations ever trade at 2x, and a
#: target cannot be reached without first surviving the hold — so in replay
#: every take-profit level tested (1.5x, 2x, 4x, 10x) left a 60-minute hold
#: negative. What the live book's 2x "achieved" was an artefact of filling at
#: the next sample rather than at the target: +157% average against a +94%
#: target, which flatters the book and would not happen to a limit order.
PAPER_TAKE_PROFIT_X = _dec("LAB_GRADUATION_PAPER_TAKE_PROFIT_X", "0")
#: TWO MINUTES. Was five.
#:
#: This stopped being a backstop and became the strategy. Replayed over 430
#: graduations, holds of 1-5 minutes are the only ones that are positive at
#: any execution cost; from 10 minutes out the mean is negative even at a zero
#: fee, which is a property of the asset and not something better execution
#: can fix. Against controls the five-minute exit returns +1.23% where a
#: random exit time returns -12.82% and holding to the end of the series
#: returns -14.47%.
#:
#: It is still ALSO the data's limit: the price series ends at
#: POST_MIGRATION_SECONDS, past which there is no mark and no exit price.
#: Measured over 427 live trades, the share of trades losing more than half
#: is a straight function of the hold: 4.5% at 1m, 7.7% at 2m, 12.3% at 3m,
#: 18.8% at 5m, and 40% by an hour. Every extra minute is another minute in
#: which the pool's liquidity can be pulled, and no exit rule offsets it —
#: 93% of collapses move price and liquidity in the SAME sample.
PAPER_MAX_HOLD_MINUTES = _int("LAB_GRADUATION_PAPER_MAX_HOLD_MIN", 2)
#: A position is only opened on a token whose pool opened within this long, so
#: the book enters near the open rather than halfway through a window.
PAPER_ENTRY_GRACE_MINUTES = _int("LAB_GRADUATION_PAPER_ENTRY_GRACE_MIN", 3)
#: How often the book ticks. THREE seconds (it was ten, a tenth of the
#: shortest hold).
#:
#: At sixty the book was breaking its own rule: a position due out at five
#: minutes is not noticed until the next tick, so 104 closed trades averaged
#: 5.77 minutes held, p90 6.76, worst 9.33. That is not a rounding error, it
#: is 15% more exposure than the rule allows to the one thing this lab has
#: established beyond doubt — that time in this market is expensive.
#:
#: Measured on those trades: they returned +$221.45, and exiting each at the
#: first mark at or after five minutes returns +$408.23. The lateness cost
#: $186.78, which is 46% of the book's potential profit.
#:
#: It costs nothing to fix: the tick is database-only, no external call. The
#: floor on accuracy is now the sampler's 60-second mark, not the book's
#: inattention.
#:
#: Ten was still too slow for the real wallet, which copies this book and
#: cannot start a buy until a tick has seen the pool open: over its first 15
#: trades that wait was a median 7.6s of a 17.4s entry lag, and one buy
#: 14s behind the paper price paid 1.0% more for it.
PAPER_INTERVAL_SECONDS = _int("LAB_GRADUATION_PAPER_TICK_S", 3)

# --- the A/B: an entry filter, tested rather than adopted ---------------------
#
# Replaying 537 graduations (2026-09-11/12) found two ENTRY-TIME signals that
# separate rugs, both mechanistic, both holding on each recorded day:
#
#   symbol never seen before   rugs in 5m 18.0%   reused symbol      3.0%
#   pool open 06:00-17:59 UTC  rugs in 5m 14.9%   18:00-05:59 UTC    5.4%
#
# The never-seen symbols that rugged were mash-ups of trending words — flygpt,
# juggbrain, fomoceo — fresh fabrications. The reused ones were copies of
# things with proven demand. Combined, the two cut the rug rate to 2.0% and
# keep 47% of graduations. Two days is not enough to trust the P&L, so the
# filter runs as a SECOND book beside the control, on the same graduations,
# and the two are compared after four weeks. The control is not touched.
#: The two arms the dedicated Paper panels render. Both are ordinary members
#: of `tournament.ARMS` — the panels are a close-up of two rows of the
#: leaderboard, not a separate experiment.
PAPER_BOOKS = ("F01_all_2m", "F14_symnight_2m")
#: The filtered book enters only when the pool opened inside this UTC window
#: (start inclusive, end exclusive, wrapping midnight).
PAPER_FILTER_HOUR_START = _int("LAB_GRADUATION_PAPER_FILTER_HOUR_START", 18)
PAPER_FILTER_HOUR_END = _int("LAB_GRADUATION_PAPER_FILTER_HOUR_END", 6)
#: ...and only when at least this many EARLIER tokens used the same symbol.
PAPER_FILTER_MIN_SYMBOL_REUSE = _int("LAB_GRADUATION_PAPER_FILTER_REUSE", 1)

# --- what it takes to ADOPT the entry filter, stated before anyone looks ------
#
# The A/B above runs for four weeks. "Compare the two books" is not a decision
# rule, and this platform has thirteen recorded findings that looked real until
# somebody wrote the rule down afterwards. These are the terms, fixed now.
#
# THE PRIMARY ENDPOINT IS THE EXCLUDED SET, NOT THE TWO BOOK TOTALS.
#
# The filtered book takes a strict SUBSET of the control's entries, so the two
# differ by exactly one thing: the graduations the filter refused. Comparing
# book totals measures that difference plus the noise of every trade they share.
# Measuring the refused set measures only the difference. The filter earned its
# keep if and only if the trades it threw away were, together, losers.
#
# THE CONTROL THAT MATTERS: a filter that discards 54% of a book improves that
# book about half the time by luck alone. So the real filter is judged against
# RANDOM filters of the same selectivity — the same count of graduations, drawn
# at random from the same control book. The real one must discard a worse set
# than 95% of random discards. Without this term the test measures nothing but
# the fact that some trades lose.
#
# THE PRECONDITION V2 ESTABLISHED: cutting catastrophes out of a book that
# loses anyway does not produce a profit. Track Record V2 drove its catastrophe
# rate from 26.7-90% down to 1.4% and still scored PF 0.54. So the ADMITTED set
# has to be positive on its own. A filter that turns a large loss into a small
# loss is a smaller loss, not an edge.
#
#: Not before this date, whatever the numbers look like. The judge refuses to
#: conclude early — the forex lab's interim window read PF 1.337 and its final
#: window read 1.045, and an early peek is how a window gets chosen.
AB_JUDGE_DATE = date(2026, 10, 10)
#: Refused graduations needed before the excluded set means anything.
AB_MIN_EXCLUDED = _int("LAB_GRADUATION_AB_MIN_EXCLUDED", 400)
#: ...and admitted ones, so the precondition is measured on real evidence too.
AB_MIN_ADMITTED = _int("LAB_GRADUATION_AB_MIN_ADMITTED", 400)
#: No single mint may carry the excluded set's loss. Every fake edge this
#: platform has found died on exactly this test.
AB_MAX_TOKEN_SHARE = _dec("LAB_GRADUATION_AB_MAX_SHARE", "0.20")
#: Random filters drawn to build the null distribution.
AB_RANDOM_DRAWS = _int("LAB_GRADUATION_AB_RANDOM_DRAWS", 2000)
#: The real filter's excluded-set mean must sit below this percentile of the
#: random filters' excluded-set means. 5 = beats 95% of chance.
AB_RANDOM_PERCENTILE = 5
#: Seed, so the null distribution is the same on a re-run and a changed verdict
#: means changed data rather than a changed draw.
AB_RANDOM_SEED = 20261010

# --- execution: what a real wallet could actually have done ------------------
#
# The paper book exists to inform a real wallet, so a trade it cannot execute
# is worse than no trade — it is a number that will not be there later.
#
# Slippage is no longer a flat assumption. `backtest.amm_impact` computes the
# exact constant-product move for the order against the pool's recorded depth,
# and an order too large for the pool is REFUSED rather than priced.
#
# 10%: a real wallet sets a slippage tolerance and the transaction reverts
# above it. Ten percent is already a loose tolerance for a deliberate trade;
# anything beyond it is not execution, it is hope.
#: The band an implied SOL/USD rate must fall in for the pool to be SOL-quoted.
#:
#: `price_usd / price_native` is the quote currency's dollar price. For a
#: SOL-quoted pool that is the SOL price; for a USDC-quoted one it is 1.00, and
#: `price_native` is then dollars, not SOL. Both were being traded: 8 of
#: B3_198k_5m's 213 closed trades sat in stablecoin pools on raydium, orca and
#: meteora, and one had an implied rate of 0.0037 — a pool quoted in neither.
#:
#: The RETURNS from those are still correct, because the quote cancels in a
#: price ratio. What is not correct is the page's claim that a SOL wallet would
#: have paid these prices: reaching a USDC pool costs a SOL->USDC leg in and a
#: USDC->SOL leg out, neither of which the cost model charges.
#:
#: Wide on purpose. SOL has traded $8-$260 in its life and this only has to
#: separate "a SOL price" from "1.00" and "0.0037".
#: Read each graduate's holder concentration once, at graduation.
#:
#: One `getTokenLargestAccounts` plus one `getTokenSupply` per graduating mint —
#: about 800 calls a day at the observed rate, against a budget the curve poller
#: already lives inside. Collection is ON because the data cannot be obtained
#: later: `getTokenLargestAccounts` answers about TODAY, and for a token that
#: has since rugged today's distribution is the wreckage. Measuring it after the
#: outcome and finding that rugs were concentrated would be reading the answer,
#: not predicting it.
HOLDER_COLLECT_ENABLED = (
    os.getenv("LAB_GRADUATION_HOLDER_COLLECT", "1").strip().lower()
    in {"1", "true", "yes", "on"})

#: The filter, and it is OFF. Nothing may act on this data until there is
#: enough of it to say whether concentration predicts anything — LP-lock and
#: deployer history were both collected as rug predictors here and neither
#: did. `None` means admit every token regardless of concentration.
HOLDER_MAX_TOP1_SHARE: Decimal | None = (
    _dec("LAB_GRADUATION_HOLDER_MAX_TOP1", "0")
    if os.getenv("LAB_GRADUATION_HOLDER_MAX_TOP1", "").strip() else None)

SOL_USD_MIN = _dec("LAB_GRADUATION_SOL_USD_MIN", "20")
SOL_USD_MAX = _dec("LAB_GRADUATION_SOL_USD_MAX", "1000")

# --- what a real wallet pays on a graduation pool, per side --------------------
#: PumpSwap's fee on a pump.fun migration pool, by market cap in SOL:
#: (from, lp + protocol + creator bps). Read from the fee program's config
#: account 5PHirr8joyTMp9JMm6nW7hNDVyEYdkzDqazxPD7RaTjx on 2026-09-16 and
#: matched to live Buy/Sell events — a $7.9M token paid 40, a $140M one 30.
#: The book charged a flat 25, which no pump.fun pool charges.
PUMPSWAP_FEE_TIERS: tuple[tuple[int, int], ...] = (
    (0, 125), (420, 120), (1_470, 115), (2_460, 110), (3_440, 105),
    (4_420, 100), (9_820, 95), (14_740, 90), (19_650, 85), (24_560, 80),
    (29_470, 75), (34_380, 70), (39_300, 65), (44_210, 60), (49_120, 55),
    (54_030, 53), (58_940, 50), (63_860, 48), (68_770, 45), (73_681, 43),
    (78_590, 40), (83_500, 38), (88_400, 35), (93_330, 33), (98_240, 30))
#: Every pump.fun mint is a fixed billion tokens, so market cap is price x this.
PUMP_SUPPLY = 1_000_000_000


def pool_fee_bps(price_native: Decimal | None) -> int:
    """The tier a pump.fun pool charges at this SOL price. No price, top tier."""
    if price_native is None or price_native <= 0:
        return PUMPSWAP_FEE_TIERS[0][1]
    mcap = price_native * PUMP_SUPPLY
    return next(bps for floor, bps in reversed(PUMPSWAP_FEE_TIERS) if mcap >= floor)


#: Jupiter's own cut of every swap it routes: `platformFee.feeBps` on a live
#: `/order` quote, 2026-09-16. The real wallet trades through it.
ROUTER_FEE_BPS = _int("LAB_GRADUATION_ROUTER_FEE_BPS", 10)

# --- when a timed exit may close -----------------------------------------------
#: How far behind the market a DexScreener row is. It quotes the last trade
#: and refreshes about every 27s, so a row fetched at T describes T - 27s.
#: Socket rows describe the moment they were read.
FEED_LAG_S = _int("LAB_GRADUATION_FEED_LAG_S", 27)
#: From a stop firing to a sale: a wallet sees the mark, quotes, signs and
#: sends. A stop is priced by the first mark this long after the one it fired on.
EXIT_REACTION_S = _int("LAB_GRADUATION_EXIT_REACTION_S", 3)
#: How long a due exit waits for a mark that describes the market AFTER it was
#: due. Past this it takes the newest mark there is and records `stale_exit`.
EXIT_MAX_WAIT_S = _int("LAB_GRADUATION_EXIT_MAX_WAIT_S", 600)
#: A pool down to this share of its entry depth has been drained, and its
#: quoted price is not one anyone can sell at: after a drain the quote is the
#: virtual reserve over a few tokens, which DexScreener printed at 3,500x the
#: entry. Such a mark is priced by the constant product instead — entry price
#: times the square of the depth ratio. Every drain this lab has seen went
#: below 10%; the deepest non-drain dump, -30%, kept 85%.
EXIT_COLLAPSE_FRACTION = _dec("LAB_GRADUATION_EXIT_COLLAPSE_FRACTION", "0.2")

PAPER_MAX_IMPACT = _dec("LAB_GRADUATION_PAPER_MAX_IMPACT", "0.10")
#: A pool whose depth was never recorded cannot be shown to be tradeable, so
#: it is refused too. False would mean "assume free execution when we do not
#: know", which is the assumption that produced a $21-pool trade worth $878.
PAPER_REQUIRE_KNOWN_DEPTH = True

# --- what it takes to CALL a tournament winner, stated before it starts ------
#
# Fifty arms produce a leader in an hour whether or not any of them is good, so
# a leaderboard alone is not a result. These are the terms, written down before
# the first trade, and the page reports them as pass/fail rather than prose:
#
#   * enough trades that the ranking is not one lucky token;
#   * a profit factor that would survive being wrong about a trade or two;
#   * no single token carrying the arm — every fake edge this platform has
#     found died on exactly this test;
#   * and it must beat the best of the EIGHT RANDOM ARMS, which is the only
#     term that distinguishes "leads" from "is better than chance".
TOURNEY_MIN_TRADES = _int("LAB_GRADUATION_TOURNEY_MIN_TRADES", 40)
TOURNEY_MAX_TOKEN_SHARE = _dec("LAB_GRADUATION_TOURNEY_MAX_SHARE", "0.20")

#: The profit factor a leader must clear, BY ITS OWN TRADE COUNT.
#:
#: This replaces a flat 1.50, which was wrong by a wide margin and wrong in
#: the flattering direction. A fixed bar reasons about one strategy; this
#: tournament reports the BEST OF FORTY-TWO, and the maximum of forty-two
#: draws is nothing like a single draw.
#:
#: Bootstrapped from 553 recorded graduations under the live execution model —
#: exact constant-product impact both legs, orders over 10% impact refused —
#: these are the 95th percentile of the best-of-42 profit factor when every
#: arm is noise:
#:
#:      30 trades   PF 104     75 trades   PF 5.2     300 trades   PF 2.0
#:      40 trades   PF 23      100 trades  PF 3.8     500 trades   PF 1.7
#:      50 trades   PF 9.8     150 trades  PF 2.9     800 trades   PF 1.5
#:
#: So at forty trades an arm the old bar of 1.50 sat BELOW the median of pure
#: noise: the luckiest of forty-two coin flippers typically reaches 4.8 there,
#: and one time in twenty reaches 23. The bar falls with sample size because
#: sample size is the only thing that dilutes luck.
#:
#: Recompute this if the number of real arms changes — the ceiling is a
#: property of how many draws the leaderboard takes, not just of the market.
TOURNEY_NOISE_CEILING: tuple[tuple[int, Decimal], ...] = (
    (30, Decimal("104.27")),
    (40, Decimal("23.47")),
    (50, Decimal("9.84")),
    (75, Decimal("5.23")),
    (100, Decimal("3.84")),
    (150, Decimal("2.85")),
    (200, Decimal("2.48")),
    (300, Decimal("2.04")),
    (500, Decimal("1.72")),
    (800, Decimal("1.53")),
    (1200, Decimal("1.41")),
)
#: The floor the curve is allowed to approach. Below this a "win" is too thin
#: to survive being wrong about a trade or two, however many trades there are.
TOURNEY_FLOOR_PF = _dec("LAB_GRADUATION_TOURNEY_FLOOR_PF", "1.30")


def required_pf(trades: int) -> Decimal:
    """The profit factor a leader needs at this trade count.

    Linear between the tabulated points, flat outside them. Below the first
    point the requirement is the first point's value, which is unreachable on
    purpose: an arm with under thirty trades has not produced evidence, and
    the trade-count term refuses it anyway.
    """
    points = TOURNEY_NOISE_CEILING
    if trades <= points[0][0]:
        return points[0][1]
    for (lo_n, lo_v), (hi_n, hi_v) in pairwise(points):
        if trades <= hi_n:
            span = Decimal(hi_n - lo_n)
            step = (Decimal(trades - lo_n) / span) if span else Decimal(0)
            return (lo_v + (hi_v - lo_v) * step).quantize(Decimal("0.01"))
    return max(points[-1][1], TOURNEY_FLOOR_PF)

#: The balance the leaderboard's "$100 wallet" column simulates.
#:
#: The tournament runs $1,000 over ten $100 slots because that is the size at
#: which execution is cheapest and the volume at which per-trade statistics
#: mean anything. A real account of $100 is a different machine: it holds ONE
#: position, fully invested, so it compounds rather than adds — and a single
#: -99% trade ends it permanently, whatever the arm does afterwards.
#:
#: Both are shown. The tournament measures the rule; this measures the wallet.
WALLET_DEMO_USD = _dec("LAB_GRADUATION_WALLET_DEMO_USD", "100")
#: Below this the wallet is finished, whatever the arithmetic says — and the
#: REAL wallet stops here too. `RealWalletDriver` sizes the graduation arm with
#: this floor through `live_spec.fundable`, the same rule `_funded_walk` walks,
#: so the board and the wallet cannot disagree about when the account is done.
#:
#: $56, this arm's own break-even ticket (2026-09-16). The priority fee is flat
#: in SOL, so a round trip costs 0.98% at $100, 1.35% at $50, 2.14% at $25 and
#: 4.56% at $10, and against B3's measured gross move the cost overtakes it at
#: about $56. It was $25 — where a round trip stops being payable against ~1%
#: a side at all — until the wallet began sizing from it.
#:
#: Without a floor the simulation is fiction: an account taking -99% holds
#: about $2.65, and compounding lets that $2.65 "recover" to nine figures on
#: later winners it could never have placed.
WALLET_MIN_USD = _dec("LAB_GRADUATION_WALLET_MIN_USD", "56")
#: The ways the board splits that $100: `n` equal trades of `$100 / n`.
#: 1 is the wallet above; the rest ask what a smaller bet per trade would do.
WALLET_SPLITS = (1, 2, 4, 5, 10, 20, 25, 50, 100)
#: Wallets bigger than $100 the board also shows, each trading its whole
#: balance as one ticket ($200 x 1 ...). A bigger order moves the pool further;
#: the walk charges that from each trade's recorded impact.
WALLET_LARGER = (200, 300, 500, 1000)


def wallet_floor(ticket: _Money) -> _Money:
    """The smallest entry worth placing on a `ticket`-sized trade.

    `WALLET_MIN_USD` is the floor of a whole `PAPER_NOTIONAL_USD` ticket. A
    smaller ticket stops at the same share of itself — a $25 ticket is not
    refused for being under $56. Floats (the board) and Decimals (the wallet)
    both work, and $100 gives exactly $56 in either.
    """
    kind = type(ticket)
    return ticket * kind(WALLET_MIN_USD) / kind(PAPER_NOTIONAL_USD)


#: How many positions that wallet spreads itself over. ONE.
#:
#: It was TEN, on a measurement that compared survival across sizes but did
#: NOT charge what the smaller positions cost. That was the error. The priority
#: fee is flat in SOL, so the round trip is entirely a function of order size:
#:
#:     $100  1.41%     $50  1.82%     $20  3.05%     $10  5.09%
#:
#: A $100 wallet over ten slots holds $10 positions and pays 5.09% a trade
#: from the very first fill — more than any gross edge this lab has measured.
#: The same 86 trades on the board's best arm:
#:
#:     1 slot  $310.50     2 slots  $257.99     5 slots  $116.75     10  $88.70
#:
#: Ten slots did not lose to the market. It lost to the fee.
#:
#: What one slot costs is real and must be said: a single -99% trade ends the
#: wallet permanently, where ten slots would lose a tenth. That is the risk
#: this accepts — and it is the risk a $100 account actually has, because
#: splitting $100 ten ways in THIS market is not diversification, it is paying
#: 5% a trade for the privilege. The arms that die at one slot were dying at
#: ten as well: FLOOR_3m is $0.00 at every slot count.
#:
#: It also makes the wallet describe the same thing the trades panel does —
#: a $100 position paying a $100 position's costs — which is the confusion
#: that sent Karthik round this loop three times.
WALLET_DEMO_SLOTS = _int("LAB_GRADUATION_WALLET_DEMO_SLOTS", 1)

@dataclass(frozen=True, slots=True)
class FreshBookSpec:
    """An arm's own trades from `start`, walked through a `capital_usd` wallet
    at `ticket_usd` a trade: up to capital / ticket at once, fewer after losses,
    exactly as the real wallet funds them."""

    book: str
    start: datetime
    capital_usd: Decimal
    ticket_usd: Decimal


#: Karthik's fresh books. Every trade an arm has taken since 2026-09-19 09:58
#: passed the real wallet's money checks (`moneyblock`), so none of these holds
#: a coin the wallet refuses.
#:
#: The $75k pair restarts at 2026-09-20 08:30 UTC, when the repeat-rugger
#: refusal, the entry-time operator read and the 4-minute twin went live: the
#: first $500 ended at $341 on four rugs, two of which the new rules refuse.
#: Its 5-minute and 4-minute books hold the same coins and differ in one thing,
#: the clock, which is what they are there to settle.
#: Karthik, 2026-09-20: the quiet-pool arm and the four $25k clocks, $500 each
#: at $100 a trade. The $75k 5m/4m and $10k panels went on 20 Sep; BASE_75k_5m
#: still trades as the quiet arm's control and keeps its row on the board.
#:
#: The four $25k books start at 14:11 UTC, the minute their arms went live, so
#: each holds every trade its arm ever made. They differ in ONE thing, the
#: clock, so the money columns are a like-for-like answer to "when to sell".
#: The $25k books ended on 2026-09-21 at $332, $426, $84 and $12 of their
#: $500. The three that replace them buy a $55-75k BAND, the one slice that
#: was positive on all four days measured, at two clocks plus the quiet twin
#: where the rugs are. Same $500 from the same minute, so their columns
#: compare like for like.
FRESH_BOOKS: tuple[FreshBookSpec, ...] = (
    FreshBookSpec("BASE_75k_quiet_5m", datetime(2026, 9, 20, 15, 0, tzinfo=UTC),
                  Decimal(500), Decimal(100)),
    # The four-minute twin starts from the same minute on purpose: its early
    # trades are the five-minute book's own coins re-priced at four minutes
    # (`scripts/seed_quiet_4m.py`), so the two walks are comparable only if
    # they are funded from the same start with the same money.
    FreshBookSpec("BASE_75k_quiet_4m", datetime(2026, 9, 20, 15, 0, tzinfo=UTC),
                  Decimal(500), Decimal(100)),
    *(FreshBookSpec(book, datetime(2026, 9, 21, 14, 15, tzinfo=UTC),
                    Decimal(500), Decimal(100))
      for book in ("BAND_55k_2m", "BAND_55k_5m", "BAND_55k_quiet_5m")),
)

# --- the kill gate, stated before this run produced a single trade ------------
#
# Written down on 2026-09-12, the day the book was re-armed, so that a good
# week cannot talk anyone out of it later. The lab has produced nine no-edge
# results; the tenth is the expected outcome and the gate is what makes that
# outcome cost nothing.
#
# Below ANY of these at the end of the run, the book closes. Not "reconsider".
PAPER_GATE_STARTED = "2026-09-12"
PAPER_GATE_WEEKS = 4
#: Profit factor: gross profit over gross loss. 1.5 is the same bar the
#: backtester's `evaluate_gate` uses, so the two agree on what passing means.
PAPER_GATE_MIN_PF = _dec("LAB_GRADUATION_PAPER_GATE_PF", "1.5")
#: At least this many closed trades, or the profit factor means nothing.
PAPER_GATE_MIN_TRADES = _int("LAB_GRADUATION_PAPER_GATE_TRADES", 100)
#: No single token may be more than this share of gross profit. Every
#: apparent edge this platform has found died on exactly this test.
PAPER_GATE_MAX_TOKEN_SHARE = _dec("LAB_GRADUATION_PAPER_GATE_SHARE", "0.20")

# --- the gate, stated before any result is looked at --------------------------
#: Out-of-sample profit factor. 1.5 and not 1.0: a strategy that merely clears
#: break-even on one sample has not cleared the next sample's costs.
GATE_MIN_PF = _dec("LAB_GRADUATION_GATE_MIN_PF", "1.5")
GATE_MIN_TRADES = _int("LAB_GRADUATION_GATE_MIN_TRADES", 100)
#: No one token may contribute more than this share of gross profit. Every
#: no-edge finding on this platform so far has had one token carrying it.
GATE_MAX_TOKEN_SHARE = _dec("LAB_GRADUATION_GATE_MAX_TOKEN_SHARE", "0.20")

# --- health -------------------------------------------------------------------
HEALTH_WINDOW_SECONDS = 600
