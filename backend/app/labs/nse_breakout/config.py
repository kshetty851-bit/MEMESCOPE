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
