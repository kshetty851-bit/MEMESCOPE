"""The lab's own configuration. Deliberately NOT `app.core.config`.

One environment variable read at call time; everything else a constant here,
including the swap table — the engine must have no DB dependency, so the
"config table" the brief asks for is a Python table, not a Postgres one.
"""

from __future__ import annotations

import os
from datetime import date

# --- flag ---------------------------------------------------------------------


def _flag(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def enabled() -> bool:
    """Read at call time, not at import: a test may flip it, and a process that
    cached it at import would keep running a lab the operator turned off."""
    return _flag("FOREX_LAB_ENABLED")


# --- instrument ---------------------------------------------------------------

SYMBOL = "EURUSD"
#: One pip.
PIP = 0.0001
#: Units of base currency in one micro lot. EUR/USD: €1,000.
MICRO_LOT_UNITS = 1_000
#: Dukascopy quotes EUR/USD in points of 1e-5.
POINT_SCALE = 1e-5
#: Leverage. Margin per micro lot = MICRO_LOT_UNITS * price / LEVERAGE.
LEVERAGE = 10

# --- backtest window ----------------------------------------------------------

START = date(2020, 1, 1)
END = date(2026, 6, 30)

# --- source -------------------------------------------------------------------

DUKASCOPY_BASE = "https://datafeed.dukascopy.com/datafeed"
#: Probed at 128 (~2.5 files/s, ~17% failures) and 64 (1.67/s, 99%) — but both
#: figures are from the first few hundred files. The feed's throttle is
#: CUMULATIVE: after ~7,900 files it answered 64 consecutive requests with 503
#: and only recovered after two minutes of silence. So this is set for a job
#: that has to keep going for hours, not for a fast ten minutes.
INGEST_CONCURRENCY = 64
#: Deliberately few. A request that has failed four times has met the throttle,
#: not bad luck, and the cheapest place to retry it is the next PASS — by then
#: the throttle has moved on. Retrying hard in place is what turned a 1.55
#: files/s pass into a 0.62 files/s one.
INGEST_RETRIES = 4
INGEST_TIMEOUT_SECONDS = 60.0

# --- strategy defaults --------------------------------------------------------

DEFAULT_STEP_PIPS = 25
DEFAULT_LEVELS = 4
DEFAULT_LOTS = 1.0
DEFAULT_START_EQUITY = 1_000.0
#: Charged half on each fill, so a round trip pays one full spread — which is
#: what a broker actually takes. See DECISIONS.md #1.
DEFAULT_SPREAD_PIPS = 0.8
#: Adverse, on stop fills only. Limit orders fill at their price or not at all.
DEFAULT_STOP_SLIPPAGE_PIPS = 0.2
#: Fraction of equity that used margin may not exceed, or the fill is rejected.
MARGIN_CAP = 0.90
#: Close everything when equity falls below this fraction of used margin.
STOP_OUT_RATIO = 0.50

# --- swap ---------------------------------------------------------------------

#: Rollover moment, in New York wall-clock time.
SWAP_HOUR_NY = 17
#: OANDA (and every other broker) books three nights of carry at the Wednesday
#: rollover, because Wednesday's value date settles on Monday. Without it the
#: weekend is never charged and a multi-week grid position looks 2/7 cheaper
#: than it is.
TRIPLE_SWAP_WEEKDAY = 2  # Monday=0

#: USD per micro lot (€1,000) per night, by calendar year.
#:
#: SOURCE. OANDA does not publish a retrievable historical swap archive, so
#: these are DERIVED from the two published policy rates that a real swap is
#: made of, plus a broker markup. For each year:
#:
#:     long  = (ECB_deposit_facility - Fed_funds_effective - 0.5%) / 365 * N
#:     short = (Fed_funds_effective - ECB_deposit_facility - 0.5%) / 365 * N
#:
#: where N is the USD notional of one micro lot (€1,000 at that year's average
#: EUR/USD rate) and 0.5%/yr is the markup each side pays — the ~1%/yr round
#: trip that OANDA's published EUR/USD financing charges have carried.
#: Annual averages of the policy rates used, in percent:
#:
#:   year   ECB DFR   Fed funds   EUR/USD    d%     long $/night   short $/night
#:   2020    -0.50      0.36        1.142    -0.86      -0.0426        +0.0113
#:   2021    -0.50      0.08        1.183    -0.58      -0.0350        +0.0026
#:   2022    +0.08      1.68        1.054    -1.60      -0.0606        +0.0318
#:   2023    +3.31      5.02        1.081    -1.71      -0.0655        +0.0358
#:   2024    +3.73      5.15        1.082    -1.42      -0.0569        +0.0273
#:   2025    +2.26      4.10        1.100    -1.84      -0.0705        +0.0404
#:   2026    +2.00      3.40        1.120    -1.40      -0.0583        +0.0276
#:
#: The ECB column is the TIME-WEIGHTED average of the deposit facility rate
#: across that year's decisions, not the year-end rate — 2022 and 2023 moved
#: too far for a year-end figure to mean anything. 2026 covers Jan–Jun only.
#: Signs are the ones a EUR/USD trader actually lived with over this window:
#: long EUR against USD paid carry in every one of these years, short EUR
#: earned it — and earned almost nothing in 2021, when the differential was
#: barely wider than the markup.
#:
SWAP_USD_PER_MICRO_LOT: dict[int, tuple[float, float]] = {
    #  year: (long, short)
    2020: (-0.0426, +0.0113),
    2021: (-0.0350, +0.0026),
    2022: (-0.0606, +0.0318),
    2023: (-0.0655, +0.0358),
    2024: (-0.0569, +0.0273),
    2025: (-0.0705, +0.0404),
    2026: (-0.0583, +0.0276),
}
#: A year outside the table (there should be none inside START..END) falls back
#: to the nearest year present, rather than silently charging zero carry.
SWAP_FALLBACK_YEAR = 2026

# --- sweep --------------------------------------------------------------------

SWEEP_STEPS = (15, 25, 50)
SWEEP_LEVELS = (3, 4, 6)
#: Size of the stop orders as a multiple of the base lot size. 0 removes them
#: entirely, which is the neutral-grid baseline.
SWEEP_STOP_MULTIPLIERS = (0.0, 0.5, 1.0)

#: The gate is stated as "positive in >= 4 of 6 years". The window spans SEVEN
#: calendar years, because 2026 is half a year — January to June. These six are
#: the full ones, and they are the denominator; 2026 is reported beside them and
#: counted in nothing, rather than being quietly folded in to make a seventh.
FULL_YEARS: tuple[int, ...] = (2020, 2021, 2022, 2023, 2024, 2025)
PARTIAL_YEAR = 2026

# --- integrity ----------------------------------------------------------------

#: A gap longer than this outside a weekend fails the integrity check.
MAX_GAP_MINUTES = 60
#: Per-year candle count must land within this fraction of the expected count.
CANDLE_COUNT_TOLERANCE = 0.05
