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
from decimal import Decimal, InvalidOperation


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

#: How often the whole watch set is read. The task's default.
POLL_INTERVAL_S = _int("LAB_GRADUATION_POLL_INTERVAL_S", 15)
#: `getMultipleAccounts` accepts at most 100 addresses per request. A property
#: of the RPC, not of this lab, but pinned here so a change is visible.
MAX_ACCOUNTS_PER_CALL = 100
#: Token bucket, calls per minute against the node. At `MAX_WATCH_SET` 500 and
#: a 15s interval the poller needs 20 calls a minute; this is five times that,
#: and still a sixth of the public endpoint's published allowance.
RPC_CALLS_PER_MINUTE = _int("LAB_GRADUATION_RPC_CALLS_PER_MINUTE", 100)
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
POSTGRAD_INTERVAL_S = _int("LAB_GRADUATION_POSTGRAD_INTERVAL_S", 60)
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
#: pump.fun / PumpSwap take, per side, on the POST-graduation AMM legs.
BACKTEST_PUMP_FEE_BPS = _int("LAB_GRADUATION_PUMP_FEE_BPS", 100)
#: The fee inside the bonding-curve fill maths. Separate from the one above so
#: the curve and the AMM can be priced differently, because they are.
#:
#: 125 bps: pump.fun's public fee page states the LIVE bonding-curve schedule
#: as 1.25% total (0.95% protocol + 0.30% creator). Their program README still
#: documents `fee_basis_points = 100`, which is the older constant — set this
#: to 100 to reproduce that instead. The live number is the default because a
#: backtest should charge what a trader actually pays.
BACKTEST_CURVE_FEE_BPS = _int("LAB_GRADUATION_CURVE_FEE_BPS", 125)
#: Assumed slippage per side. The brief's default.
BACKTEST_SLIP_BPS = _int("LAB_GRADUATION_SLIP_BPS", 150)
#: A flat priority fee per side, in quote. At the default notional this is
#: another 40 bps, which is why it is not ignorable on a 0.5 SOL position.
BACKTEST_PRIORITY_FEE_QUOTE = _dec("LAB_GRADUATION_PRIORITY_FEE_QUOTE", "0.002")
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


#: Starting capital, in quote. 5 SOL ~ $1,000 at $200/SOL.
PAPER_CAPITAL_QUOTE = _dec("LAB_GRADUATION_PAPER_CAPITAL", "5.0")
#: Per position. 0.5 SOL ~ $100, ten of them.
PAPER_NOTIONAL_QUOTE = _dec("LAB_GRADUATION_PAPER_NOTIONAL", "0.5")
PAPER_MAX_SLOTS = _int("LAB_GRADUATION_PAPER_SLOTS", 10)
#: Trailing stop, as a fraction off the running peak.
PAPER_TRAILING_PCT = _dec("LAB_GRADUATION_PAPER_TRAILING_PCT", "0.30")
#: A hard backstop, because the post-graduation price series ENDS at
#: POST_MIGRATION_SECONDS. Past that there is no mark and no exit price, so a
#: position left open would simply hang. This is a property of the data, not a
#: strategy choice.
PAPER_MAX_HOLD_MINUTES = _int("LAB_GRADUATION_PAPER_MAX_HOLD_MIN", 60)
#: A position is only opened on a token whose pool opened within this long, so
#: the book enters near the open rather than halfway through a window.
PAPER_ENTRY_GRACE_MINUTES = _int("LAB_GRADUATION_PAPER_ENTRY_GRACE_MIN", 3)
#: How often the book ticks.
PAPER_INTERVAL_SECONDS = 60

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
