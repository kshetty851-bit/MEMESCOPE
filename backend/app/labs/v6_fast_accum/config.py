"""Pre-registered, frozen configuration for the V6 fast-accumulation experiment.

`RESEARCH_ONLY`. Nothing here is read by any production path.

## Everything in this file is pre-registered

The three entry configurations, the exit rule, the fee, the slippage model and
the acceptance gate were fixed BEFORE any result was computed, and are hashed
into every run (`config_hash`). That hash is what makes "we did not tune this
until it passed" a checkable claim rather than a promise: a run whose hash
differs from the pre-registered one is a different experiment and is labelled
as such.

The thresholds are CANDIDATES, not three chances to pick a winner. Selection
among them happens on TRAIN folds only — see `analysis.select_config`.

## Why the fee is not a guess

`CURVE_FEE_BPS = 125` is the graduation lab's measured pump.fun curve fee, and
the fill maths are that lab's `curve_fill_buy` / `curve_fill_sell`, which model
the fee's asymmetry exactly: on a buy it is a markup on the amount leaving the
wallet, on a sell it is a deduction from the SOL coming back. `sol_in * (1-f)`
is the wrong form for a buy and differs materially at these sizes.

Price impact is NOT assumed. It is computed against the curve's own reserves at
the decision sample, so a position deepens the curve exactly as it would on
chain. `EXTRA_SLIP_BPS` is an additional adverse haircut on top of that, for
the latency between observing a sample and landing a transaction.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, asdict
from decimal import Decimal

#: Bumped when a change here would make two runs incomparable.
SPEC_VERSION = "v6-fast-accum-1.0.0"

# --- entry candidates ---------------------------------------------------------


@dataclass(frozen=True, slots=True)
class EntryConfig:
    """One pre-registered entry rule. Immutable by construction."""

    name: str
    #: Curve progress, in PERCENT, at or above which the token is eligible.
    min_progress_pct: Decimal
    #: Seconds since first observation, at or below which entry must happen.
    max_elapsed_s: int
    #: Initial market cap floor, in SOL. Evaluated at the DECISION sample.
    min_mcap_sol: Decimal
    #: Whether the Telegram overlay is required. See `overlays`.
    require_telegram: bool


#: The three pre-registered candidates of the brief, verbatim.
FAST_60 = EntryConfig("FAST-60", Decimal("10"), 60, Decimal("30"), True)
FAST_90 = EntryConfig("FAST-90", Decimal("15"), 90, Decimal("30"), True)
FAST_120 = EntryConfig("FAST-120", Decimal("20"), 120, Decimal("30"), True)

CANDIDATES: tuple[EntryConfig, ...] = (FAST_60, FAST_90, FAST_120)

# --- controls -----------------------------------------------------------------
#: Each control is the SAME simulator over a different entry rule, so a
#: difference between base and control is attributable to the rule alone.
#:
#: A: random eligible entry in the same curve-progress region.
#: B: curve + mcap, WITHOUT telegram.
#: C: curve + telegram, WITHOUT mcap.
#: D: curve threshold alone.
CONTROL_A = "CONTROL-A-random-in-region"
CONTROL_B = "CONTROL-B-no-telegram"
CONTROL_C = "CONTROL-C-no-mcap"
CONTROL_D = "CONTROL-D-curve-only"

# --- exit rule (pre-registered, frozen) ---------------------------------------
#: Take profit at +100%.
TP_MULT = Decimal("2.0")
#: Stop loss at -40%.
SL_MULT = Decimal("0.6")
#: Time stop.
MAX_HOLD_MIN = 30
#: A position is closed BEFORE migration, never carried through it.
EXIT_BEFORE_GRADUATION = True

#: When several exit conditions fall inside one observation interval the
#: simulator takes the WORST executable one, in this order. A sample is a
#: single reserve reading: it cannot say whether the low or the high came
#: first, so assuming the favourable one would be look-ahead.
EXIT_PRECEDENCE = ("graduation", "stop_loss", "take_profit", "time_stop")

# --- execution ----------------------------------------------------------------
NOTIONAL_USD = Decimal("10")
MAX_CONCURRENT = 5
MAX_DEPLOYED_USD = Decimal("50")
#: Frozen for the experiment and recorded in the config hash. Per-entry SOL/USD
#: is not stored anywhere in the archive, and every ratio metric (PF, win rate,
#: expectancy as a fraction) is invariant to it — only the absolute dollar
#: figures scale. Stated rather than hidden.
SOL_USD_FROZEN = Decimal("150")
#: pump.fun's bonding-curve fee, in basis points. The graduation lab's measured
#: value, and the brief's.
CURVE_FEE_BPS = 125
#: Adverse haircut applied on TOP of exact curve impact, per leg, for the
#: latency between seeing a sample and landing a transaction.
EXTRA_SLIP_BPS = 25
#: Flat per-transaction priority fee, in SOL, paid on BOTH legs.
PRIORITY_FEE_SOL = Decimal("0.002")

# --- walk-forward -------------------------------------------------------------
#: The pre-registered fold width. The gate is judged on THIS and nothing else.
FOLD = "weekly"
#: Embargo between a train fold and the test fold that follows it. Must exceed
#: the maximum strategy horizon (30 min) so no trade can straddle the boundary.
EMBARGO_MIN = 45
#: A secondary DAILY split is also reported. It is EXPLORATORY ONLY and can
#: never satisfy the gate: `analysis.gate` reads the weekly folds. It exists
#: because an archive too short for weeks still has something to show, and
#: showing it beats showing nothing as long as it cannot be mistaken for a
#: pass. See `analysis.walk_forward`.
SECONDARY_FOLD = "daily"

# --- acceptance gate (pre-registered, §14 verbatim) ---------------------------
GATE_MIN_PROFIT_FACTOR = Decimal("1.5")
GATE_MIN_OOS_TRADES = 100
GATE_MAX_SINGLE_TOKEN_PROFIT_SHARE = Decimal("0.20")
GATE_ALL_TEST_WEEKS_PROFITABLE = True
GATE_ALPHA = Decimal("0.05")

# --- statistics ---------------------------------------------------------------
BOOTSTRAP_ITERATIONS = 10_000
RANDOM_SEED = 20260912

# --- overlays -----------------------------------------------------------------
#: Independently measurable overlays, per §22. Each is a predicate on a
#: decision-time feature; none is folded into a score, and there is no score.
#: `UNAVAILABLE` overlays are reported as such and never silently skipped.
OVERLAY_TELEGRAM = "telegram"
OVERLAY_MCAP = "initial_mcap_30_sol"

#: Overlays the current archive cannot supply. Per §23 these must not become
#: hidden dependencies: the base experiment runs without them and says so.
UNAVAILABLE_OVERLAYS: dict[str, str] = {
    OVERLAY_TELEGRAM: (
        "No social provider exists on the platform (app/radar/community.py "
        "returns unavailable by construction), and grad_tokens does not "
        "persist the launch `uri`. Recoverable in principle: 99.2% of grad "
        "mints carry discovered_tokens.metadata_uri, and pump.fun metadata is "
        "content-addressed on IPFS, so resolving the CID later returns the "
        "launch-time document. Not built, and not a dependency of Phase 1."
    ),
}


def config_hash() -> str:
    """A stable digest of every pre-registered value above.

    Recorded on every run. Two runs with the same hash tested the same
    hypothesis; a run with a different hash is a different experiment, whatever
    it is called.
    """
    payload = {
        "spec": SPEC_VERSION,
        "candidates": [asdict(c) for c in CANDIDATES],
        "tp": str(TP_MULT), "sl": str(SL_MULT), "hold_min": MAX_HOLD_MIN,
        "exit_precedence": list(EXIT_PRECEDENCE),
        "notional_usd": str(NOTIONAL_USD), "max_concurrent": MAX_CONCURRENT,
        "max_deployed_usd": str(MAX_DEPLOYED_USD),
        "sol_usd": str(SOL_USD_FROZEN),
        "fee_bps": CURVE_FEE_BPS, "slip_bps": EXTRA_SLIP_BPS,
        "priority_fee_sol": str(PRIORITY_FEE_SOL),
        "fold": FOLD, "embargo_min": EMBARGO_MIN,
        "gate": {
            "pf": str(GATE_MIN_PROFIT_FACTOR), "trades": GATE_MIN_OOS_TRADES,
            "conc": str(GATE_MAX_SINGLE_TOKEN_PROFIT_SHARE),
            "alpha": str(GATE_ALPHA),
        },
        "seed": RANDOM_SEED,
    }
    # `default=str` so a Decimal hashes as its exact text rather than a float:
    # binary rounding would make the digest depend on the platform.
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]
