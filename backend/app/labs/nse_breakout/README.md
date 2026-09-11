# NSE Breakout Tracker

A pre-breakout radar for Indian equities: NSE cash-market names walking up into
a daily resistance level they have not cleared yet.

| Phase | What it is |
|---|---|
| 1 | the universe and its daily bars — `bt_universe`, `bt_candles`, `bt_index_closes`, `bt_ingest_days`, `bt_runs` |
| 2 | resistance levels, a readiness score, the state machine and the episode record |
| 3 | the "Breakouts" tab in the existing frontend |

It reads **one keyless source**: the NSE's own bhavcopy archive, plus the
exchange's daily index-close file for Nifty 50. **No Kite Connect** — its token
expires daily, and an unattended job that needs a human to log in every morning
is not unattended. Kite auth is untouched by this lab.

Isolated the way every other MEMESCOPE lab is: its own `bt_` tables, its own
flag, its own config, its own tests. It writes nothing outside its own tables.

---

## How to enable it

Off by default, one flag, read at call time:

```bash
NSE_BREAKOUT_ENABLED=true
```

Apply the migration, then fill the history:

```bash
cd backend && alembic upgrade head
```

```bash
cd backend && NSE_BREAKOUT_ENABLED=true python -m app.labs.nse_breakout backfill --all
```

### The commands

| Command | What it does |
|---|---|
| `ingest` | today's bhavcopy, then rebuild the universe from what is stored |
| `ingest --date 2026-09-10` | one specific day (re-running a day rewrites it) |
| `backfill` | one bounded slice — the same work the hourly beat does |
| `backfill --all` | loop the slice until nothing is pending, with progress on stdout |
| `universe` | the active universe as a table |
| `health` | the health route's payload as JSON |

**`--all` is safe to kill.** Each slice commits, and what is still pending is
*derived* from `bt_ingest_days` rather than stored in a cursor, so an
interrupted backfill costs the day in flight and nothing else. Re-run the same
command to carry on.

---

## Sources

| What | Where | Notes |
|---|---|---|
| Daily bars | `nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_{YYYYMMDD}_F_0000.csv.zip` | one ZIP per trading day, **every instrument in it** |
| Nifty 50 close | `nsearchives.nseindia.com/content/indices/ind_close_all_{DDMMYYYY}.csv` | one CSV per trading day |

Both need a browser `User-Agent` and a referer; the archive returns 403 without
them. Neither needs a key, a cookie or a session.

**One ZIP carries every symbol**, which is the whole reason the backfill is
cheap: ~620 requests for three years of history across ~2,900 symbols, rather
than one request per symbol. It also means every bar in the table came from one
source on one day, so there is no cross-source adjustment mismatch to reconcile.

**yfinance is not a dependency.** The brief specified it; Yahoo returns 429 to
this host on every attempt, including with a cookie-seeded session and backoff
(measured — see `RUN_LOG.md`). The bhavcopy archive replaced it for both bars
and Nifty.

### What the parser keeps

Rows are read **by column name**, never by position — the exchange has added
columns to this file before.

* `FinInstrmTp == STK` and `SctySrs in {EQ, BE}` — no futures, options, SME,
  government securities, gold bonds or ETFs.
* A row whose high is below its low, its open or its close is dropped. The
  exchange has published those, and a bar with a zero low would sit under every
  future support level for ever.

### Rate limits

One request at a time, `REQUESTS_PER_MINUTE = 60`, and `Retry-After` is treated
as a **floor** rather than a ceiling. Measured cost of a full backfill: ~620
requests, no 429s, no bans.

---

## The universe — `bt_universe`

Re-derived from what is stored, after every ingest. Never scraped, never a list
somebody maintains.

| Filter | Value | Why |
|---|---|---|
| Series | `EQ`, `BE` | ordinary equities |
| Last close | ≥ ₹20 | below that, a tick is a percent |
| **Median** 20-day turnover | ≥ ₹1 crore | the median, not the mean: one block deal cannot qualify an illiquid name |
| Bars | *(none)* | short histories stay in the universe and are excluded from levels |

A symbol that stops appearing goes **inactive with a reason**, never deleted —
`price`, `turnover` or `absent`. The exchange file carries no linkage between a
renamed symbol and its old name, so a rename arrives as a new row and the old
one goes inactive. Inventing the link would be worse than admitting there
isn't one.

Name, ISIN and series come from the bhavcopy itself, and **the newest day
wins** — the backfill walks the archive backwards, so without that guard every
slice would rewrite a current name with an older one and a company that renamed
itself would end up filed under what it was called three years ago.

Sector is **not** recorded. There is no keyless source for NSE sector
classification, and the paid ones may not be scraped.

### Corporate actions

Bhavcopy is **unadjusted**, and the corroboration source the brief named is
unreachable. So an overnight gap wider than `SPLIT_GAP_PCT` (30%) is
**flagged** — `suspect_gap = true`, `adjusted = false` — and never corrected.
Silently halving a price with nothing to check it against invents data; a
flagged bar stays visible in the health route and can be excluded by anything
that cares.

---

## The schedule

Two beat entries, all gated by the flag, all in **UTC** because the platform's
Celery runs in UTC and changing that would move every other lab's schedule.

| UTC | IST | What |
|---|---|---|
| 13:00 | 18:30 | the day's bhavcopy — NSE publishes it after the close |
| 14:00 | 19:30 | again, because it is occasionally late |
| 02:00 | 07:30 | again next morning, for the day it was very late |
| `:20` hourly | — | one bounded backfill slice; does nothing once complete |

A day the archive never published (a holiday, a weekend) is recorded `missing`
and **never asked about again** — but only once the file is actually overdue.
A 404 before 18:00 UTC (23:30 IST) records nothing at all and the day stays
pending, because `missing` is terminal and "not published yet" is not "never
published": settling today's date from a lunchtime CLI run would drop that
whole session for ever. A day that failed in transport is recorded
`failed` and retried up to `MAX_DAY_FAILURES` times, then given up on and
listed by name in the health route.

A pass is bounded **twice**: 40 days and 420 seconds. The day count alone is
not a time budget — one unlucky day can burn four attempts with backoff on each
of its two requests — and Celery kills a task at 540s **before it commits**,
with `task_acks_late` on, so an overrunning pass loses every day it fetched and
is then redelivered to fetch them again.

**The archive is the trading calendar.** There is no hard-coded holiday list:
Diwali moves every year, the exchange adds sessions, and a stale list would be
a second source of truth that silently disagrees with the first. A 404 is the
exchange answering the question.

---

## How to check health

```bash
curl -s localhost:8000/api/v1/tracker/health | jq
```

Flag off, it answers `{"running": false}` **without touching the database** —
"the tracker is not running" and "it ran and found nothing" are different facts
and must not render identically.

Flag on, `coverage` is the number that matters: it counts symbols with at least
`MIN_BARS_FOR_LEVELS` (250) bars, not symbols in the universe. A name with 40
bars cannot carry a resistance level, and counting it as covered would hide
exactly the gap this route exists to show.

### What the history actually looks like

Measured on a full backfill, 2026-09-11:

| | |
|---|---|
| Trading days ingested | **608**, 2024-03-26 → 2026-09-10 |
| Days the archive never published | 37 (holidays) |
| Days that **failed** | **0** |
| Bars | **1,449,471** |
| Active universe | **1,604** (1,303 inactive with a reason) |
| Names with ≥ 250 bars | **1,396 — 87.0% of all active** |
| Names with ≥ 250 bars, **of those listed long enough to have them** | **1,396 of 1,398 — 99.9%** |
| Bars flagged `suspect_gap` | 425 (0.03%) |
| Wall time | 23m 31s, no 429s, no bans |

The two numbers differ because 208 active names were **listed inside the
window** — a company that listed nine months ago cannot have 250 daily bars,
and no source can supply them. Not one of the 208 is a fetch gap: every name
that existed 250 sessions ago has its 250 bars, bar two that simply did not
print on every session. **Neither `MIN_BARS_FOR_LEVELS` nor the universe
filters were moved to make the headline number bigger** — the shortfall is the
market, not the code.

---

## Registration

Four lines outside this folder, all additive:

| File | Line |
|---|---|
| `app/models/__init__.py` | import `bt_*` so alembic sees them |
| `app/api/v1/router.py` | include the `/tracker` router |
| `app/workers/celery_app.py` | the module in `include`, plus two beat entries |
| `docker-compose.yml` | `NSE_BREAKOUT_ENABLED` passed through |

The models live on the **platform's** `Base`. A second `DeclarativeBase` would
hide these tables from alembic, which then emits `drop_table` for every one of
them on the next autogenerate.

---

## Decisions worth knowing

* **Bhavcopy missing → retry, never fabricate a bar.** A missing day is a hole,
  and a hole is honest. An interpolated bar is a level that never existed.
* **Renamed symbol → new row, old one inactive.** No linkage in the source.
* **< 250 bars → in the universe, out of levels and states.** It is a real
  tradable name; it just cannot carry a level yet.
* **Sector → omitted.** No keyless source, and a paid one may not be scraped.
* **Nifty missing → `rel_nifty` null, never zero.** Zero is a number and would
  be averaged; null is the absence of one. A missing index file never takes the
  equity ingest down with it.
* **Kite Connect → untouched.** Phases 1–2 are keyless by construction.

---

## Tests

```bash
cd backend && pytest app/labs/nse_breakout/tests -q
```

The parser is tested against a **400-row slice of a real exchange file**
(`tests/fixtures/bhavcopy_20260910.csv`), not a synthetic one — including the
series and instrument types that have to be filtered out, and the malformed
rows the exchange actually publishes.

The integration tests use their own engine and only ever touch `bt_` tables,
dropped and created **one table at a time**. Not
`Base.metadata.drop_all(tables=own)`: that also visits sequences declared
anywhere on `Base`, so merely importing `app.main` in a test made the fixture
try to drop an unrelated wallet's sequence — and the whole suite skipped itself
rather than failing.

---

## Layout

| File | What |
|---|---|
| `config.py` | every threshold, URL and budget; the flag is a function, not a constant |
| `bhavcopy.py` | pure parsing. No session, no clock, no I/O |
| `sources.py` | the archive client: retries, spacing, 404-is-an-answer |
| `ingest.py` | days, upserts, resumption, the universe, the gap flag |
| `data.py` | the read side |
| `api.py` | `/tracker` — read-only |
| `scheduler.py` | the beat tasks |
| `__main__.py` | the CLI |
