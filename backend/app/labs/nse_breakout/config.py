"""The lab's own configuration. Deliberately NOT `app.core.config`.

One environment variable read at call time; everything else a constant here,
so nothing outside this package needs editing to run the tracker.
"""

from __future__ import annotations

import os


def _flag(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def enabled() -> bool:
    """Read at call time, not at import: a test may flip it, and a worker that
    cached it at import would keep running a lab the operator turned off."""
    return _flag("NSE_BREAKOUT_ENABLED")


# --- sources (keyless) --------------------------------------------------------
#: The UDiFF common bhavcopy: one ZIP per trading day carrying EVERY instrument.
#: This is both the daily feed and the backfill — one source, so there is no
#: cross-source adjustment mismatch to reconcile.
BHAVCOPY_URL = ("https://nsearchives.nseindia.com/content/cm/"
                "BhavCopy_NSE_CM_0_0_0_{yyyymmdd}_F_0000.csv.zip")
#: The exchange's own per-day index closes — where Nifty 50 comes from.
#: Yahoo (`^NSEI`) answered 429 to every attempt from this host, including with
#: a cookie-seeded session, so it is not used anywhere in this lab.
INDEX_CLOSE_URL = ("https://nsearchives.nseindia.com/content/indices/"
                   "ind_close_all_{ddmmyyyy}.csv")
NIFTY_NAME = "Nifty 50"

#: NSE refuses a default client agent outright, and wants a referer.
HTTP_USER_AGENT = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36")
HTTP_REFERER = "https://www.nseindia.com/"
HTTP_TIMEOUT_SECONDS = 30.0
MAX_ATTEMPTS = 4
BACKOFF_INITIAL_SECONDS = 2.0
BACKOFF_MAX_SECONDS = 60.0
#: The archive is a static file host, not a rate-limited API, but a backfill
#: walks ~620 of them and politeness costs nothing.
REQUESTS_PER_MINUTE = 60
#: Hours past midnight UTC on a trading day before a 404 from the archive is
#: taken to mean "never published" rather than "not published YET". The market
#: closes at 15:30 IST (10:00 UTC) and the file lands around 18:00 IST
#: (12:30 UTC); 18:00 UTC is 23:30 IST, a wide margin. Before that a 404 is
#: recorded as nothing at all, so the day stays pending and is simply asked
#: for again — `missing` is TERMINAL, and settling today's date at lunchtime
#: would lose that whole session for ever.
PUBLISH_CUTOFF_HOURS_UTC = 18

# --- universe -----------------------------------------------------------------
#: Only real equity series. EQ is the rolling segment; BE is trade-for-trade.
#: SM/ST are SME, GS/GB are government securities and gold bonds, BZ is
#: suspended — the bhavcopy carries all of them and none is a breakout
#: candidate. Measured on one live file: EQ 2,638, BE 245, SM 380, ST 91.
ALLOWED_SERIES: frozenset[str] = frozenset({"EQ", "BE"})
#: `STK` excludes index futures and anything else that is not a share.
ALLOWED_INSTRUMENT = "STK"
#: Indian ISINs encode what the instrument IS: `INE` is company equity, `INF`
#: is mutual-fund units — which is what every NSE ETF is. They trade in series
#: EQ with `FinInstrmTp` STK, so the series filter cannot see them, and the
#: brief excludes ETFs. This is the exact, keyless rule. A symbol whose ISIN is
#: not yet known is NOT excluded: unknown is not disqualifying.
ALLOWED_ISIN_PREFIX = "INE"
MIN_PRICE_INR = 20.0
#: 20-day MEDIAN turnover, not mean: one block deal must not qualify a name
#: that is otherwise untradeable.
MIN_TURNOVER_INR = 1_00_00_000.0     # 1 crore
TURNOVER_WINDOW_DAYS = 20
#: Fewest daily bars before a symbol is scored. It stays in the universe
#: either way — this gates levels and states, not membership.
MIN_BARS_FOR_LEVELS = 250

# --- backfill -----------------------------------------------------------------
#: How far back to walk the archive. The UDiFF format 404s beyond roughly
#: 2.7 years — measured: 200 at -750 days, 404 at -1000 — so the brief's three
#: years is not available from this source and this is what there is. Still
#: comfortably past `MIN_BARS_FOR_LEVELS`.
BACKFILL_DAYS = 900
#: Trading days a full backfill is expected to yield, for progress reporting.
EXPECTED_TRADING_DAYS_PER_YEAR = 248
#: Days fetched per backfill pass, so the job is resumable. Measured at ~2.2s
#: a day, so a slice is ~90s — but a day count is not a time budget, which is
#: what `BACKFILL_DEADLINE_SECONDS` is for.
BACKFILL_DAYS_PER_RUN = 40
#: Wall-clock stop for one backfill pass. A day count alone does NOT bound the
#: time: one unlucky day can burn 4 attempts x (30s timeout + up to 60s
#: backoff) on each of its two requests, so 40 days has no upper bound in
#: seconds. Celery's `task_soft_time_limit` is 540 and `task_acks_late` is on,
#: so a pass that overruns is killed BEFORE it commits, loses every day it
#: fetched, and is then redelivered to do it all again. 420 leaves 120s for
#: the run row, the universe rebuild and the commit. Asserted in a test
#: against Celery's own setting rather than trusted as a number.
BACKFILL_DEADLINE_SECONDS = 420
#: Consecutive failures before a trading day is given up on and recorded.
MAX_DAY_FAILURES = 5

# --- corporate actions --------------------------------------------------------
#: Bhavcopy is UNADJUSTED and the brief's corroboration source (yfinance) is
#: unreachable, so a gap this large is FLAGGED, never silently corrected.
#: A 1:2 split halves the price overnight; a genuine one-day -30% move in a
#: liquid Indian equity is rare enough to be worth looking at either way.
SPLIT_GAP_PCT = 30.0

# --- levels (phase 2) ---------------------------------------------------------
#: Bars each side of a high before it counts as a confirmed swing. The RIGHT
#: side is the no-hindsight guarantee: the last `SWING_LOOKBACK` bars of any
#: series can never produce a swing, because the bars that would confirm them
#: have not closed yet.
SWING_LOOKBACK = 5
#: Swing highs within this much of a group's volume-weighted mean are one
#: level. One swing high is a price somebody sold at once; three within 2% is
#: a price somebody sells at, and that is what a breakout has to get through.
CLUSTER_PCT = 2.0
#: A close must clear a level by this much to break it. A close one paisa
#: above a level is noise, and calling it a break would manufacture breakouts.
BREAK_CONFIRM_PCT = 1.0
ATR_PERIOD = 14
VOLUME_MEAN_DAYS = 20
VOLUME_SLOW_DAYS = 50
#: Window for the range used by `tightness` and for MFE/MAE.
RANGE_DAYS = 20
#: A 20-day range narrower than this is a coil. Tight before a break is the
#: setup; wide before a break is just a stock that moves.
TIGHT_RANGE_PCT = 12.0
#: Trading days in a year, for the 52-week high.
WEEK52_DAYS = 250

# --- the readiness score ------------------------------------------------------
#: The brief said to reuse the existing 0-100 pre-breakout score. Discovery
#: found no such score anywhere on this machine (logged in RUN_LOG step 0), so
#: it is built here. Five components, each clamped to [0, 1], each returned
#: alongside the score — a score nobody can take apart is a number nobody can
#: argue with, and the whole point of the episode table is to find out later
#: which of the five, if any, predicted anything.
SCORE_WEIGHTS = {
    "proximity": 0.30,    # how close the close sits under resistance
    "compression": 0.20,  # a narrow 20-day range: a coil, not a drift
    "trend": 0.20,        # above a rising 50-day mean
    "volume": 0.20,       # participation showing up before the break
    "touches": 0.10,      # a level tested four times is a real level
}
#: Touches at which the `touches` component saturates.
SCORE_TOUCH_CAP = 4
#: Days in the trend component's moving average.
SCORE_TREND_DAYS = 50
#: Volume ratio (recent mean / 20-day mean) at which `volume` saturates.
SCORE_VOLUME_CAP = 2.0
#: Days averaged for the recent side of that ratio. Two, not one: a single
#: day's volume is one block deal as often as it is a crowd.
SCORE_VOLUME_DAYS = 2

# --- the state machine --------------------------------------------------------
#: WATCH: in the neighbourhood. NEAR: close to breaking.
WATCH_SCORE = 60
WATCH_PCT = 10.0
NEAR_SCORE = 70
NEAR_PCT = 4.0
#: A breakout needs volume. A close through a level on no volume is a drift,
#: and the thing being tested is whether anybody showed up.
BREAK_VOL_MULT = 1.5
#: A close back below the level within this many days un-makes the breakout.
FALSE_WINDOW_DAYS = 5
#: How far below resistance a watched name falls before the setup is dead.
FAIL_PCT = 8.0
#: Consecutive bars under `WATCH_SCORE` that also end an episode.
FAIL_SCORE_BARS = 5
#: An episode that has done nothing for this long expires.
MAX_EPISODE_DAYS = 60

# --- outcomes -----------------------------------------------------------------
#: Trading-day horizons every return is measured at.
OUTCOME_HORIZONS = (5, 10, 20, 40)
#: Window for max favourable and max adverse excursion, and for `held_20d_pct`.
OUTCOME_WINDOW_DAYS = 20
#: The trailing stop recorded beside the raw hold, as a percentage of the high
#: water mark. Evaluated LOW BEFORE HIGH — see `outcomes.trail_result`.
TRAIL_PCT = 10.0
#: A trailed position is closed at the market after this many days either way,
#: so an outcome always has an answer.
TRAIL_MAX_DAYS = 60
#: Longest horizon: an episode cannot have its outcomes filled until this many
#: trading days have passed since the measurement point.
OUTCOME_MAX_HORIZON = 40

# --- replay -------------------------------------------------------------------
#: Symbols replayed per pass, so the historical replay is resumable and never
#: outruns the worker's time limit. See `BACKFILL_DEADLINE_SECONDS`.
REPLAY_SYMBOLS_PER_RUN = 200
REPLAY_DEADLINE_SECONDS = 420

# --- the outcome pass ---------------------------------------------------------
#: Symbols whose outcomes are filled per pass. Batched by SYMBOL, not by
#: episode: filling the whole replay touches ~1,300 symbols with ~600 bars
#: each, and holding all of those at once would put the candle table in memory.
OUTCOME_SYMBOLS_PER_RUN = 400
OUTCOME_DEADLINE_SECONDS = 420
