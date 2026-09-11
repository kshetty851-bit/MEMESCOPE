# NSE Breakout Tracker — run log

One line per VERIFY pass. Newest at the bottom.

## Step 0 — discovery

**Where this is built, and why not where the brief said.** The brief describes a
repo with FastAPI + SQLAlchemy + **APScheduler**, a **React + Vite** frontend,
**Kite Connect auth**, an existing NSE screener, an existing 0–100 pre-breakout
score and an existing radar UI with resistance overlays. Searched every repo
under `~/Projects` excluding vendored code: **APScheduler and KiteConnect
appear nowhere on this machine.** The closest real match was `~/Projects/swingscope`
(NSE, bhavcopy, `app/prebreakout/` with a 0–100 readiness score, `app/levels/`)
— but it is Next.js, not Vite, and has no scheduler or Kite either. The user
then directed that this live **inside MEMESCOPE**, so it is a new isolated lab
beside the Solana Breakout Lab, whose architecture (levels → score → state
machine → episodes → outcomes → decile stats → SVG chart with resistance
overlays) is the same shape this brief asks for.

Consequences, all logged as unattended decisions in the README:

* There is **no existing NSE score to reuse** (2.2). The readiness score is
  built here, following `labs/breakout/momentum.py`'s shape.
* There is **no existing 3:45 PM IST job** to leave untouched (1.3), no Kite
  auth to leave untouched, and no existing radar UI or screener logic to avoid
  rewriting. Those constraints are satisfied vacuously.
* `RUN_LOG.md` lives in the lab folder, not the repo root: in MEMESCOPE a lab
  touches nothing outside its own directory, and two labs writing a root
  `RUN_LOG.md` would collide.

**Data sources, measured before any code was written.**

| Source | Result |
|---|---|
| NSE UDiFF bhavcopy ZIP, keyless with a browser UA + referer | **200.** 205 KB, 3,671 rows. `TckrSymb`, `SctySrs`, OHLC + turnover. |
| Series mix in one real file | EQ 2,638 · SM 380 · BE 245 · ST 91 · GS 55 · GB 43 — so EQ/BE filtering is essential and the file carries the field |
| EQ/BE rows | **2,883**; 2,533 with close ≥ ₹20 (before the turnover filter) |
| Bhavcopy archive reach | 200 at −750d; **404 at −1000d** — the archive in this format reaches ~2–2.7 years, **not 3** |
| Yahoo / yfinance (`SYMBOL.NS`, `^NSEI`) | **429 on every attempt**, including with a cookie-seeded session and backoff. Not usable. |
| NSE index close file `ind_close_all_DDMMYYYY.csv` | **200**, 17 KB — a keyless per-day Nifty 50 close |

**What that changes.** Yahoo is unavailable, so the brief's yfinance backfill
and its `^NSEI` relative return both need a different source. Both are solved
by the same archive the daily feed already uses: one bhavcopy ZIP per trading
day carries **every symbol at once**, so a full backfill is ~620 requests
rather than one per symbol for 2,533 symbols — cheaper *and* single-sourced, so
there is no cross-source adjustment mismatch. Nifty comes from the exchange's
own index file on the same days. `yfinance` is therefore **not added as a
dependency**; the lab uses `httpx`, as every other MEMESCOPE lab does.

The cost is split/bonus adjustment: bhavcopy is unadjusted and the brief's
corroboration source is gone. A >30% overnight gap is therefore **detected and
flagged** (`adjusted=false`, `suspect_gap=true`) rather than silently
corrected — conservative, and visible in the health route.

| # | phase | iter | what failed | what changed |
|---|---|---|---|---|
| 1 | 1 | 1 | — | migration `0067_nse_breakout` round-trips: up → 5 `bt_` tables, down → 0, up again → 5. `alembic check` clean for `bt_`. |
| 2 | 1 | 1 | — | live ingest of 6 trading days against the real archive: 5 ok, 1 missing, **14,433 rows, 1,616 active symbols**, 11 requests, 13.7s, zero 429s. |
| 3 | 1 | 1 | — | `test_bhavcopy.py` — 11 tests green against a 400-row slice of the real exchange file. |
| 4 | 1 | 2 | `test_re_ingesting_a_day_rewrites_rather_than_duplicates` read back the OLD close | **the test's fake was wrong, not the code.** `row(c=111)` left `h=105`, and the parser drops a bar whose high is below its close — so the correction was silently filtered and the upsert never saw it. Fixed the fixture, not the parser: that filter is why a zero-low bar cannot poison a level. |
| 5 | 1 | 2 | whole integration suite **skipped itself** the moment `test_api.py` imported `app.main` | `Base.metadata.drop_all(c, tables=own)` also visits sequences declared anywhere on `Base`, so it tried to drop an unrelated wallet's sequence, raised, and the fixture's `pytest.skip` swallowed it as "no test database available". Now drops and creates **one table at a time**, so `bt_` means `bt_`. This would have hidden every integration test behind a green-looking run. |
| 6 | 1 | 2 | `test_the_route_is_mounted_where_the_brief_says` — `'_IncludedRouter' object has no attribute 'path'` | this FastAPI keeps an included router as ONE lazy object, so walking `app.routes` finds no tracker path at all — an assertion over that list would have passed on a router that was never registered. Asserts over `app.openapi()["paths"]`, the served contract, instead. |
| 7 | 1 | 2 | — | `test_ingest.py` + `test_api.py` — **33 tests green**: universe filters, upsert idempotency, derived resumption, holiday-vs-failure, give-up after `MAX_DAY_FAILURES`, synthetic 1:2 split flagged-not-corrected, health coverage counted against scorable names, failures listed by name, empty database. |
| 8 | 1 | 2 | — | health route live against the scratch DB: `days_ok=175, days_failed=0, days_missing=11, bars=460,194, active=1,604`, Nifty present on all 175 days. |
| 9 | 1 | 3 | `bt_universe.name` was null for all 1,604 names and `series` was hard-coded `EQ` | the parser lifted name/ISIN/series out of the file and `upsert_bars` dropped them on the floor, so `rebuild_universe` — which runs off `bt_candles` — could only ever preserve nulls. Added `upsert_identity`, guarded **newest-day-wins** because the backfill walks backwards. Confirmed the guard's test FAILS without the `where` clause before trusting it. The model's own docstring promised a later phase could rely on `series`; it could not have. |
| 10 | 1 | 3 | — | `test_isolation.py` — 15 source-parsing checks: no wallet/engine/other-lab import, **no broker client imported anywhere** (asserted on imports, not on the word appearing in a docstring), no env read but the flag itself, the parser never learns a network exists, the migration is purely additive and matches the models column-for-column, both beat entries resolve to registered tasks, the router is mounted, alembic can see all five tables. The migration is found **by content** (`bt_universe` in the file), never by filename — shipping a lab between branches renumbers it. |
| 11 | 1 | 3 | — | `alembic check` against the scratch DB: **zero `bt_` drift**. The repo has ~25 pre-existing drifts on other tables (pumpfun, lab_*, real_wallet, hq_*); baselined, not caused here. |
| 12 | 1 | 3 | platform suite: 6 failed, 3,958 passed, 68 errors | **identical with and without this lab's four registration lines** — stashed them and re-ran to prove it. The 68 errors are the shared test DB refusing to drop `discovered_tokens` (a leftover `paper_v2_positions` FK from another branch); the 6 failures are paper-strategy registry tests. Pre-existing, untouched. |
| 13 | 1 | 4 | `BACKFILL_DAYS_PER_RUN = 40` claimed in its own comment that a pass "never runs long enough to be killed by the worker's time limit" — **nothing enforced that** | a day count is not a time budget. One unlucky day can burn 4 attempts × (30s timeout + up to 60s backoff) on each of its two requests, so 40 days has no upper bound in seconds. Celery's `task_soft_time_limit` is 540 with `task_acks_late` on, so an overrunning pass is killed **before it commits**, loses every day it fetched, and is redelivered to repeat the whole thing. Added `BACKFILL_DEADLINE_SECONDS = 420` and a wall-clock stop; the test asserts the margin against **Celery's own setting**, not a remembered number, and was confirmed to FAIL at 600 before being trusted at 420. Invisible standalone: the CLI has no time limit, so every local run passes while production stores nothing. |
| 14 | 1 | 4 | a 404 from the archive was recorded `missing` **whatever the hour** | `missing` is TERMINAL — `pending_days` treats it as settled and never asks again. The beat runs after the close so it would rarely see a pre-publication 404, but the CLI can be run at any hour: `python -m app.labs.nse_breakout ingest` at lunchtime would have settled that day as never-published and **dropped the whole session for ever**. Now a 404 before `PUBLISH_CUTOFF_HOURS_UTC` (18:00 UTC = 23:30 IST) records NOTHING and the day stays pending. The pre-decided rule was "bhavcopy missing → retry"; it was not retrying. |
| 15 | 1 | 4 | `first_seen` was the same date for every symbol | it was derived from the 20-day turnover window, so it was the WINDOW's start date — identical for a company listed in 2019 and one listed last week, while reading exactly like a listing date. Phase 2 would have used it to decide whether a name is old enough to score. Now `min(date)` over the whole candle table, re-derived on every rebuild rather than preserved, because a backfill that reaches further back moves the real first bar earlier. |
| 16 | 1 | 4 | — | **full backfill complete: 639 days walked, 608 ingested, 1,449,471 bars, 2024-03-26 → 2026-09-10, in 23m 31s. Zero failed days, zero retry-exhausted requests.** 37 days `missing` (holidays and the archive's own gaps). Nifty 50 present on all 608. |
| 17 | 1 | 4 | — | 425 bars flagged `suspect_gap` (0.03% of 1.45M) — real reverse-splits and consolidations, e.g. LICMFGOLD 14,401.80 → 143.20 (1:100). Flagged, **not corrected**: verified against raw SQL that the count matches the number of >30% overnight moves in the table exactly. |
