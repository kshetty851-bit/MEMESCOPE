"""What does Strategy E's expectancy do as its loss cap varies?

THIS IS A SENSITIVITY ANALYSIS, NOT A BACKTEST — read this before the numbers.
----------------------------------------------------------------------------
The only historical data available for this population is the Karthik Paper
Wallet's SUMMARY statistics and its per-trade ENTRY/EXIT snapshots — never a
tick-by-tick price path between them. That means it is not possible to
honestly "replay" a different exit rule against this history: a trade
Karthik's own (stop-less) rule closed as -100% might have been rescued at
-12% by a real stop, or might have gapped straight through it in one
observation exactly like the liquidity collapses the original MEMESCOPE audit
found — and there is no way to tell which, for any individual trade, without
the missing price path.

What CAN be done honestly: hold the population's measured, real quantities
fixed — the exact win/loss SPLIT (166/145 of 311, the platform's own reported
counts, not a re-derived rate) and the average winner size implied by its own
realised P&L — and ask how expectancy responds as the LOSS CAP varies from
"uncapped" (Karthik's actual number) down through Strategy E's -12% design
point. This isolates the one variable this project actually controls (how
large a single loss is ALLOWED to become) from the one it does not yet have
evidence about (whether E's entry-side consensus filter changes the win rate
itself — that requires forward data, not this dataset).

CALIBRATION CHECK (must reproduce Karthik's own reported number)
------------------------------------------------------------------
The "no stop" row below is required to reproduce Karthik's actual realised
result, -$774.86 over 311 trades (-$2.49/trade), to within rounding. If it
does not, the calibration is wrong and the script says so loudly rather than
printing a plausible-looking but false number. An earlier version of this
script failed this exact check (it reported -13.63%/trade against a true
-24.9%/trade) because its synthetic winner distribution's mean silently
drifted from the target during random generation — caught by adding this
assertion, not by eyeballing the output.

Every point below carries a bootstrap confidence interval and
Benjamini-Hochberg correction across the number of loss-cap configurations
actually swept, so a "the strategy is profitable" conclusion cannot be reached
by scanning several caps and reporting the best one.
"""
from __future__ import annotations

import random
import sys
from decimal import Decimal

from app.labs.rafiq.adapters.stats import assess

# --- Karthik's own published numbers, verbatim -----------------------------
KARTHIK_WINS = 166
KARTHIK_LOSSES = 145
KARTHIK_CLOSED_TRADES = KARTHIK_WINS + KARTHIK_LOSSES     # = 311, matches the platform
KARTHIK_REALISED_PNL = Decimal("-774.86")
KARTHIK_STAKE = Decimal(10)

# Average winner implied by the platform's own totals, using the EXACT
# reported counts (not win_rate * n, which would round and drift):
#   realised = wins*avg_win_usd - losses*stake      (Karthik: every loss = -100%)
_AVG_WIN_USD = (KARTHIK_REALISED_PNL + KARTHIK_LOSSES * KARTHIK_STAKE) / KARTHIK_WINS
AVG_WIN_PCT = _AVG_WIN_USD / KARTHIK_STAKE * 100


def winner_draws(n_wins: int, target_mean_pct: Decimal, *, seed: int) -> list:
    """`n_wins` right-skewed values whose SAMPLE MEAN equals `target_mean_pct`
    exactly, by construction — rescaled after drawing rather than relying on a
    distribution's theoretical mean, which is what silently drifted last time.
    """
    rng = random.Random(seed)  # noqa: S311 - a fixed-seed draw, not cryptography
    raw = [max(1.0, rng.lognormvariate(0, 0.7)) for _ in range(n_wins)]
    raw_mean = sum(raw) / len(raw)
    scale = float(target_mean_pct) / raw_mean
    return [v * scale for v in raw]


def population_for(loss_cap_pct: Decimal, wins_pct: list) -> list:
    """Same winners every time (passed in); only the loss magnitude varies,
    so the sweep isolates exactly one variable."""
    return list(wins_pct) + [-float(loss_cap_pct)] * KARTHIK_LOSSES


def _out(line: str = "") -> None:
    """This script's output IS its product, so it goes to stdout directly.
    `print` is banned project-wide (ruff T20) to stop debug leftovers reaching
    an operator through a structured log; a command-line report is neither."""
    sys.stdout.write(f"{line}\n")


def main() -> None:
    wins_pct = winner_draws(KARTHIK_WINS, AVG_WIN_PCT, seed=0)
    assert abs(sum(wins_pct) / len(wins_pct) - float(AVG_WIN_PCT)) < 0.01, \
        "winner rescaling failed to hit the target mean"

    _out("=" * 78)
    _out("STRATEGY E SENSITIVITY SWEEP — loss cap vs expectancy")
    _out("=" * 78)
    _out("\nDerived from Karthik's own numbers (exact counts, not a rate):")
    _out(f"  wins / losses      : {KARTHIK_WINS} / {KARTHIK_LOSSES} "
          f"of {KARTHIK_CLOSED_TRADES}")
    _out(f"  avg winner (solved): {float(AVG_WIN_PCT):+.1f}%")

    baseline = population_for(Decimal(100), wins_pct)
    baseline_mean = sum(baseline) / len(baseline)
    target = float(KARTHIK_REALISED_PNL / KARTHIK_STAKE / KARTHIK_CLOSED_TRADES * 100)
    _out("\nCALIBRATION CHECK:")
    _out(f"  simulated no-stop mean : {baseline_mean:+.2f}%/trade")
    _out(f"  Karthik's actual mean  : {target:+.2f}%/trade "
          f"(-$774.86 / 311 trades / $10 stake)")
    assert abs(baseline_mean - target) < 0.5, (
        f"CALIBRATION FAILED: simulated {baseline_mean:.2f} vs actual {target:.2f} "
        f"-- refusing to print a sweep built on a miscalibrated baseline")
    _out(f"  MATCH within {abs(baseline_mean-target):.2f} pts -- proceeding\n")

    caps = [Decimal(100), Decimal(40), Decimal(25), Decimal(15), Decimal(12),
            Decimal(8)]
    samples = [population_for(c, wins_pct) for c in caps]
    verdicts = [assess(f"cap_{c}", s, configurations_searched=len(caps), seed=1)
               for c, s in zip(caps, samples, strict=True)]

    _out(f"{'loss cap':>18}{'n':>6}{'mean':>9}{'95% CI':>20}{'FDR pass':>10}"
          f"{'verdict':>10}")
    _out("-" * 78)
    for cap, v in zip(caps, verdicts, strict=True):
        label = "Karthik (no stop)" if cap == 100 else f"Strategy-like -{cap}%"
        _out(f"{label:>18}{v.n:>6}{v.mean:>9.2f}"
              f"{f'[{v.ci.low:+.1f}, {v.ci.high:+.1f}]':>20}"
              f"{v.p_corrected_survives!s:>10}{'PASS' if v.passed else 'fail':>10}")

    _out("\nOUTLIER DEPENDENCE (does the result survive losing its best trades?):")
    for cap, v in zip(caps, verdicts, strict=True):
        if cap in (Decimal(100), Decimal(12)):
            _out(f"  -{cap}%: survives={v.outliers.survives}  "
                  f"mean_all={v.outliers.mean_all:+.2f}  "
                  f"mean_without_top5={v.outliers.mean_without_top.get(5, float('nan')):+.2f}")

    _out("\n" + "=" * 78)
    _out("READ THIS BEFORE ACTING ON ANY ROW ABOVE:")
    _out("  This sweep holds the win/loss SPLIT and average winner FIXED at")
    _out("  Karthik's measured values. It does NOT model whether Strategy E's")
    _out("  entry-side consensus filter changes the win rate -- that is")
    _out("  unmeasured and requires forward data. It also does NOT model")
    _out("  gap-through: a real stop can still fill worse than its nominal")
    _out("  level, exactly as the original MEMESCOPE audit found for")
    _out("  liquidity collapses. Treat this as evidence that BOUNDING loss")
    _out("  size is necessary, not as proof any specific cap is sufficient.")
    _out("=" * 78)


if __name__ == "__main__":
    main()
