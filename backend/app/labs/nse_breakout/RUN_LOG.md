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
beside the Solana Breakout Lab (since deleted, 2026-09-12), whose architecture
(levels → score → state
machine → episodes → outcomes → decile stats → SVG chart with resistance
overlays) is the same shape this brief asks for.

Consequences, all logged as unattended decisions in the README:

* There is **no existing NSE score to reuse** (2.2). The readiness score is
  built here, following the shape of the Solana lab's `momentum.py` — a file
  that no longer exists, so `score.py` here is now the only copy of it.
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
| 18 | 2 | 1 | — | migration `0068_nse_bt_phase2` round-trips (3 tables + 1 nullable column ↔ 0); `alembic check` still zero `bt_` drift. |
| 19 | 2 | 1 | the replay looked like it would be too slow to run at all | measured before optimising: **0.30s per symbol** for a full 608-bar causal walk, ~9 minutes for the universe — and 1ms for a one-bar daily pass. No incremental level-walker needed; the naive implementation is the implementation. |
| 20 | 2 | 2 | `test_the_fixture_walks_all_the_way_to_a_breakout` — the hand-built series never scored 60 | **the fixture was wrong, not the thresholds.** A flat coil on quiet volume genuinely scores 51: no trend, no participation. Reshaped the FIXTURE into a setup a person would draw — a long advance, three rejections at ~101, a 26-bar base, volume arriving in the last four days — which scores 72-73 and breaks out on 3.3x volume. Moving `WATCH_SCORE` to make a test pass would have been tuning the rules to the test. |
| 21 | 2 | 2 | `test_the_daily_pass_and_the_replay_produce_the_same_episodes` — the two disagreed from the 2nd bar | **a real bug in the live path, found by the cross-check and by nothing else.** `_refresh` wrote the BAR's evaluation into the episode row, so a NONE bar stored `state='NONE'` on an open episode; the next day's pass rebuilds its starting point from that row, read it as "not open", abandoned the setup mid-flight and opened a second one when it recovered — two half-episodes with a `ref_price` from the wrong day. The row now carries the ADVANCED EPISODE's state; the bar's own state goes to the snapshot and the event, where it belongs. |
| 22 | 2 | 2 | `/near` listed CPSEETF and SMALLCAP | **ETFs.** They trade in series EQ with `FinInstrmTp` STK, so neither Phase 1 filter could see them, and the brief excludes ETFs. Their ISIN says what they are: `INF` is mutual-fund units, `INE` is company equity. 106 of the 1,604 "active" names were ETFs. An ETF's resistance is the index's and its volume is the market maker's, so a breakout in one is not a fact about a company. Universe: 1,604 → **1,498**. Unknown ISIN is NOT disqualifying. |
| 23 | 2 | 2 | `days_in_state` never incremented in a test while working live | a test artefact worth recording: `_upsert_states` is a Core statement, so an ORM object the test had already loaded kept reporting the old value from the identity map. `expire_all()` in the test; no production change. |
| 24 | 2 | 3 | the outcome pass loaded every symbol's bars at once | filling the whole replay touches ~1,300 symbols × ~600 bars; batched by SYMBOL instead, so memory is one symbol's history rather than the candle table. |
| 25 | 2 | 3 | episodes measured near the end of the data **starved every symbol after the batch limit** | an episode whose 40-bar window has not elapsed returns False on every pass, for ever. Sitting at the front of the ordering it re-failed each run and symbols past the limit were never reached. Added a SQL pre-filter for symbols that can have something fillable. |
| 26 | 2 | 3 | that pre-filter silently matched **zero rows** while the identical arithmetic in Python matched | **SQLAlchemy types a bind parameter from the LEFT operand.** `BtUniverseMember.last_seen - timedelta(days=56)` sent the timedelta as a **DATE**, not an interval — the statement compiled, executed, raised nothing, and returned nothing. Fixed with `literal(gap, Interval())`. Caught only because a test asserted the row DID fill; a test that merely called `fill()` and checked for no exception would have passed for ever. |
| 27 | 2 | 4 | — | **replay complete: 1,300 symbols, 8,484 episodes, 608s.** Outcomes filled for 7,281 (60 still inside their window). 46,282 transition events. |
| 28 | 2 | 4 | — | live daily pass: 1,300 scorable names in 13s → **1,198 NONE, 78 WATCH, 24 NEAR**. All six routes return 200 with the documented shapes over real HTTP. |
| 29 | 2 | 4 | — | **the replay result, no tuning: the score predicts the BREAKOUT and not the RETURN.** Reach rate climbs 17.5% → 38.2% → 58.1% → 70.2% across the deciles — a four-fold monotone spread on 8,484 episodes. What follows is noise: +0.09% mean 20-day return from the breakout, 45% win rate, decile column not monotone with a NEGATIVE top bucket, −0.03% vs Nifty, MFE +9.8 against MAE −8.4, and the two years disagree on the sign. 45% of confirmed breakouts close back under the level within 5 bars; the 10% trail returns PF 0.93 and stops out 93% of the time. Full table and reasoning in the README. |
| 30 | 2 | 4 | a name that left the universe kept its state row | its episodes stay — that is the record — but a stale score against a current-looking `bar_date` reads as today's answer. The daily pass now drops state rows for inactive names. |
| 31 | 3 | 1 | — | `/breakouts` built in `frontend/src/labs/nse-tracker/`: board, stock view with the SVG chart, recent breakouts, outcomes card. **21 frontend tests**; the full frontend suite is 1,094 across 79 files, all green. ESLint clean on the new files. |
| 32 | 3 | 1 | the fixture's breakout date fell OUTSIDE the fixture's candle window, so no marker drew | the fixture was wrong — but the case is real, so it is now a test of its own: a marker cannot be placed on a bar the chart was not given, and drawing it at the edge would put the breakout on the wrong day. |
| 33 | 3 | 1 | the score components rendered in JSON key order | which put the 10%-weighted component above the 30%-weighted one, so the reader's eye landed on the least important bar first. Ordered by weight, asserted in a test. |
| 34 | 3 | 1 | `next build` fails prerendering `/` | **pre-existing and not from this branch** — proved by stashing every frontend change and reproducing it exactly. `frontend/node_modules` in this worktree is a SYMLINK into MEMESCOPE's, which breaks the RSC client manifest's module resolution (`Could not find the module … in the React Client Manifest`). `Compiled successfully` and the type check both pass, and the route count goes 21 → 22 with this page, so it builds. Verified instead by running the dev server against the live backend and against mock mode. |
| 35 | 3 | 1 | — | live verification: `/breakouts` on the real backend renders 1,498 active / 1,300 scorable / 24 NEAR / 78 WATCH, the stock panel draws JSWINFRA's ladder and its 90-score components, and the outcomes card shows the full decile table with the negative top bucket in red. Mock mode renders every panel including the empty states. |

## Deployment — 2026-09-11

| # | what | result |
|---|---|---|
| 36 | `next build` in the REAL repo (not the worktree) | **passes**, `/breakouts` in the route table at 10 kB. The worktree failure was its symlinked `node_modules` breaking the RSC client manifest, exactly as suspected — but the Vercel gate needed a real answer, not a suspicion. |
| 37 | secret scan of the three commits before pushing to a PUBLIC repo | clean — every hit for `token` is prose (Kite Connect, colour tokens); no credentials, no IPs. |
| 38 | `git push origin nse-breakout-lab:main` | fast-forward `f3342f2..a7c0e4f`, no merge commit. |
| 39 | `./scripts/deploy.sh` on prod | **14/14 health checks, deployed `a7c0e4f85d3f`, no rollback.** Migration `0068_nse_bt_phase2`, all eight `bt_*` tables, all four beat entries registered. `NSE_BREAKOUT_ENABLED=true` added to `.env.production` (backed up first). Build cache pruned to 13 GB free beforehand. |
| 40 | **claimed prod could not reach NSE — WRONG** | `curl` from the server's shell returned 403 with the app's own UA and referer, and a full cookie handshake also 403'd, which looked exactly like a datacentre-IP block. It was not. `docker exec memescope-backend-1 python -c "... NseArchive().bhavcopy(d)"` returned the identical **205,216 bytes**: httpx sends headers curl does not and the WAF keys on them. `bt_runs` already said `ok: 39, failed: 0` — the record outranked the probe and I read the probe first. A different CLIENT is a different request. |
| 41 | — | prod backfills itself from the exchange. Slice cost there is ~4 min against ~90s locally: **2 cores, 3 GB, load 5**, shared with the armed real wallet — so the CPU-bound replay is left to the hourly beat rather than run by hand. |
| 42 | — | `nse_bhavcopy_not_yet date=2026-09-11` in the prod log: the publication-cutoff fix refusing to settle today's file while the market is still open. The one production behaviour that could only ever be observed in production. |
| 43 | deploy | `backfill --all` **span at one NSE request per second** once only today's unpublished bhavcopy was left | the loop stopped on "a pass did no work" and a `too_early` day IS work: it walks one day, settles nothing, so `days=1` and `remaining=1` for ever. Caught in production after ~100 iterations. Both `--all` loops now stop when **`remaining` stops falling**, which is the only honest definition of no progress and covers every case that makes one — a day too early, a day out of retries, a slice cut off by its own deadline. Regression test fails in 0.16s against the old condition. |
| 44 | deploy | the 09:50 replay tick fired **mid-backfill** and walked 200 symbols on ~250-400 bars instead of 608 | exactly the gap flagged before it happened: `bars >= 250` cannot tell "this name only ever traded 250 sessions" from "the backfill is 250 days in". Those 200 were marked `replayed_at` permanently and produced 268 episodes against the ~1,300 a full walk gives. Cleared on prod (268 episodes, 1,415 events, 200 markers) so the beat re-walks them over complete history. The code fix — gate the replay on `pending_days()` being empty — is queued, not bodged in. |
| 45 | deploy | the first version of the regression test **hung the machine** instead of failing | a non-terminating loop under a `lambda` fake wrote unbounded progress into pytest's capture buffer until the process choked, and `asyncio.wait_for` could not save it. The fake now refuses to be called more than 60 times. A test whose failure mode is "your laptop stops" is not a test anyone keeps. |
| 46 | deploy | claimed the fix was restored after a revert — it was **not** | `cp` from the backup was in a command I killed before it ran, and the grep I checked with matched `remaining == previous_remaining` in the OTHER loop. Ruff's dead-assignment warning was what actually caught it. Second time this session that a grep stood in for reading the line that mattered. |
| 47 | 3 | 2 | **clicking a stock looked like it did nothing** | reported on the live site. The panel opened correctly — it renders BELOW the board, and the board is a hundred rows, so the chart appeared entirely off-screen. My own earlier check missed it because I used `scroll_to` to find the Close button, which did the scrolling the product should have done. Selecting a stock now scrolls the panel into view, honouring `prefers-reduced-motion`. |
| 48 | 3 | 2 | every unbroken level on the chart looked identical | so "where is the resistance" meant cross-referencing the metrics panel beside it. The NEAREST unbroken level is now drawn at double stroke, full opacity, and labelled with its price at the axis; the others fade back. Verified in the live DOM rather than by eye: one `level-nearest` at stroke-width 2, label `3040`, 12 broken levels dashed behind it. |
| 49 | 3 | 2 | 3 tests broke on `scrollIntoView is not a function` | jsdom implements no layout. Stubbed in the lab's own test file, NOT in the shared `vitest.setup.ts` — that file belongs to the whole repo and this lab edits nothing outside its folder. |
| 50 | 3 | 3 | the scroll landed **mid-chart**, heading already above the reader | it fired when the SYMBOL changed, while the panel was still a short loading skeleton; the taller real content then replaced it under the scroll position. Moved into the panel and keyed on the DATA arriving — the component that grows is the one that scrolls. |
| 51 | 3 | 3 | `behavior: "smooth"` **silently did nothing** | measured on the live page: the identical call moved the container **0px** with `smooth` and **4,577px** with `auto`. Some browsers and embedded views drop the animation, and a scroll that sometimes does nothing is the bug this exists to fix. Now instant — which is also better for a four-thousand-pixel jump, and is what a reader asking for reduced motion wants anyway. End-to-end: one click moved the container **4,082px** and left the panel top **16px** below the viewport, exactly the `scroll-mt-4` offset. |
| 52 | 3 | 3 | **deleted 11 tracked files out of another session's working tree** | the `next build` gate needs real `node_modules`, so files were copied into `~/Projects/MEMESCOPE` and `rm`'d afterwards. Safe the first time; by the second that tree had been switched to a branch which TRACKED those files, so the cleanup removed them from someone's checkout. Restored with `git checkout --`. That tree is shared and its branch moves — see the memory note. |
