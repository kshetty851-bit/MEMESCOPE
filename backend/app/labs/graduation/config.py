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
from itertools import pairwise


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
#: FIVE MINUTES, and now the only exit there is.
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
PAPER_MAX_HOLD_MINUTES = _int("LAB_GRADUATION_PAPER_MAX_HOLD_MIN", 5)
#: A position is only opened on a token whose pool opened within this long, so
#: the book enters near the open rather than halfway through a window.
PAPER_ENTRY_GRACE_MINUTES = _int("LAB_GRADUATION_PAPER_ENTRY_GRACE_MIN", 3)
#: How often the book ticks. FIFTEEN seconds, not sixty.
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
PAPER_INTERVAL_SECONDS = _int("LAB_GRADUATION_PAPER_TICK_S", 15)

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
PAPER_BOOKS = ("E05_hold_5m", "C01_symnight_5m")
#: The filtered book enters only when the pool opened inside this UTC window
#: (start inclusive, end exclusive, wrapping midnight).
PAPER_FILTER_HOUR_START = _int("LAB_GRADUATION_PAPER_FILTER_HOUR_START", 18)
PAPER_FILTER_HOUR_END = _int("LAB_GRADUATION_PAPER_FILTER_HOUR_END", 6)
#: ...and only when at least this many EARLIER tokens used the same symbol.
PAPER_FILTER_MIN_SYMBOL_REUSE = _int("LAB_GRADUATION_PAPER_FILTER_REUSE", 1)

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
