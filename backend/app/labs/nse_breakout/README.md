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
| `detect` | levels, score and state on the newest bar |
| `near` | the current NEAR/WATCH board as a table |
| `replay [--all]` | the causal walk over the whole history; resumable |
| `outcomes` | fill outcomes whose window has closed |
| `stats [--source live]` | the aggregate payload as JSON |
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
| ISIN | starts `INE` | `INE` is company equity, `INF` is mutual-fund units — which is what every NSE **ETF** is. They trade in series EQ with `FinInstrmTp` STK, so no other filter can see them. An ETF's resistance is the index's and its volume is the market maker's. 106 of 1,604 names. A symbol whose ISIN is not yet known is **not** excluded. |

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
| `:50` hourly | — | one bounded replay slice; does nothing once complete |
| 15:40 | 21:10 | fill outcomes whose window has closed |

Detection is **chained to the ingest**, not given a slot of its own: a state
evaluated against a bar the ingest has not stored yet would record yesterday's
answer as today's. It is enqueued rather than awaited, so one long pass cannot
push the other past the worker's soft limit.

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

# Phase 2 — detection, episodes and outcomes

## Levels — `levels.py`

A level is a **cluster of confirmed swing highs** within `CLUSTER_PCT` (2%) of
each other, priced at their volume-weighted mean. One swing high is a price
somebody sold at once; three within two percent is a price somebody sells at,
and that is what a breakout has to get through.

A swing high is a bar whose high is **strictly above** every high within
`SWING_LOOKBACK` (5) bars on each side. Strictly, because two equal highs
inside one window are a range rather than a peak, and admitting both would put
the same level in the ladder twice with twice the weight.

A cluster is **broken** when a close after its last touch clears it by more
than `BREAK_CONFIRM_PCT` (1%). Two things are deliberate there: a bare "close
above" would let a cluster be broken by one of its own constituent bars, since
the level is a mean and a swing above that mean usually closed above it; and
the 1% is the same margin the state machine needs for a BREAKOUT, so a level
cannot be broken by a move too small to be a breakout.

### The property that makes the record worth keeping

**Levels computed over bars 0..i are exactly the levels the full series gives
for bar i.** The right-hand confirmation window is what guarantees it: the last
five bars of any series can never produce a swing, because the bars that would
confirm them have not closed. `test_levels.py` asserts it on every prefix, and
again in the sharper form — that no longer series ever moves, adds or removes a
swing already confirmed.

Without that property every replayed episode was decided with information from
its own future, and the statistics below are fiction.

## The readiness score — `score.py`

The brief said to reuse the existing 0–100 pre-breakout score. **There is no
such score** anywhere on this machine (see `RUN_LOG.md`, step 0), so it is
built here: five components, each clamped to `[0, 1]`, each stored beside the
score.

| Component | Weight | What it asks |
|---|---|---|
| `proximity` | 0.30 | how close the close sits under the level |
| `compression` | 0.20 | is the 20-day range a coil or a drift |
| `trend` | 0.20 | above a **rising** 50-day mean — half each |
| `volume` | 0.20 | is participation arriving before the break |
| `touches` | 0.10 | a level tested four times is a real level |

A stock with nothing above it scores **zero** for proximity, not one: it is not
ready to break out, it has already broken out of everything, and that must not
be the top of the board.

The score says "coiled under a real level with participation". It does **not**
say the breakout will happen — the episode record exists to find that out, and
the decile table in `/stats` is the question being asked.

## The state machine — `states.py`

Evaluated on each new daily bar. **Every window is counted in BARS, not
calendar days**: the outcome horizons are trading days, a stock that does not
trade produces no bar, and a long weekend must not age a setup.

| State | Rule |
|---|---|
| `WATCH` | score ≥ 60 and distance ≤ 10% |
| `NEAR` | score ≥ 70 and distance ≤ 4%, close not above the level |
| `BREAKOUT` | close clears the level by > 1% **on ≥ 1.5x** the 20-day mean volume |
| `FALSE_BREAKOUT` | was BREAKOUT, closed back under the level within 5 bars |
| `FAILED` | fell > 8% below the level, or 5 bars in a row under `WATCH_SCORE`, or went through the level on no volume |
| `EXPIRED` | 60 bars open with none of the above |
| `NONE` | otherwise |

**The level is fixed when the episode opens.** After that the episode is about
that price, not whatever is nearest today. Without it a stock drifting upward
has its target quietly raised every bar and can never break out — and a
breakout would immediately re-target the next level up, so the episode would
never record the thing it was opened to record.

**NONE does not close an episode.** It means "no new state this bar". The ways
out are FAILED, FALSE_BREAKOUT and EXPIRED; a run of NONE bars turns into
FAILED through the weak-bar count. Closing on NONE would split one setup into
two half-episodes with a `ref_price` from the wrong day.

### Episodes

Opened on the first WATCH or NEAR, recording `first_near_date` and `ref_price`
(the close that day). A stock that gaps through a level nobody was watching is
reported as BREAKOUT and records **no episode** — there is no ref_price for it,
and inventing one would be inventing an entry. The **first** confirmed breakout
is the breakout; later closes through the level are events.

One open episode per symbol per source, enforced by a partial unique index — so
a bug that opened a second one fails loudly rather than double-counting every
statistic.

## Outcomes — `outcomes.py`

Filled by a **separate pass** once the window has elapsed. Nothing that decides
a state can see a return, and a test asserts `states.py` does not import
`outcomes` or `stats`. That separation is the only reason any of the numbers
below are a backtest rather than a description.

Measured from two points, because they answer different questions: buying at
NEAR is buying an expectation and eats the false breakouts; buying the
confirmed breakout is buying a fact and pays a worse price for it.

| Column | From |
|---|---|
| `ret_ref_5/10/20/40` | `ref_price` — what buying the setup would have done |
| `ret_bo_5/10/20/40` | `breakout_price` — what buying the confirmation would have done |
| `mfe_20` / `mae_20` | best and worst excursion in the 20 bars after each point |
| `held_20d_pct` | breakout price to the close 20 bars later |
| `trail10_pct` | the same entry with a 10% trailing stop |
| `rel_nifty_20` | the 20-bar return minus Nifty 50 over the same sessions |

A horizon the series does not reach is **absent, never zero** — the difference
between "it went nowhere" and "we cannot know yet" is the whole point of a
record like this, and a zero would be averaged in as a flat trade.

### The line that decides whether any of this means anything

`trail_result` takes **the low before the high**. A bar that would both take
the stop out and set a new high exits at the stop, because we cannot see the
order within a daily bar and so assume the one that costs us. The high-water
mark rises only after the low has been checked, so a stop can never be lifted
by a high the price reached after it would already have been hit.

Getting that backwards is how a backtest invents money.

## The historical replay

`Detector.walk` is one function with two callers: the daily pass folds it over
the newest bar, the replay folds it over every bar from the start. A test walks
the same series both ways — once in a sweep, once one bar at a time carrying
the episode through the database as the daily job does — and asserts the
episodes match field for field. **That test found a real bug in the live path**
that no single-path test could have: the daily pass was storing the bar's state
on the episode row, so a dull day abandoned the setup and a second episode
opened when it recovered.

```bash
cd backend && NSE_BREAKOUT_ENABLED=true python -m app.labs.nse_breakout replay --all
```

Resumable and deadline-bounded like the backfill. The marker is
`bt_universe.replayed_at`, not the presence of episodes: a symbol that produced
none has still been replayed.

### What the replay cannot see

* **Survivorship.** The universe is derived from names trading today, so a
  company delisted in 2025 is absent from a replay covering 2024. Its setups —
  disproportionately the ones that ended badly — are not in these numbers.
* **Unadjusted prices.** Bars across a split or bonus are flagged
  `suspect_gap`, not corrected, so a level computed across one is wrong. 425
  bars of 1.45M are flagged (0.03%).
* The thresholds were fixed before the replay ran and were **not** adjusted
  afterwards. The payload carries them so a number can never be read against
  the wrong rules.

### The replay result

Run 2026-09-11 over **1,300 symbols, 608 sessions (2024-03-26 to 2026-09-10)**,
producing **8,484 episodes**, of which 7,281 had complete outcome windows. The
thresholds in `config` were fixed before this ran and were not touched
afterwards.

| | |
|---|---|
| Episodes | **8,484** |
| Reached a confirmed breakout | **30.0%** |
| Of those, closed back under the level within 5 bars | **45.3%** |
| Median bars from the setup opening to the breakout | 3 |

**From `ref_price`** (buying the setup at NEAR), 20 trading days:

| mean | median | win rate | mean MFE | mean MAE |
|---|---|---|---|---|
| **−0.07%** | −1.13% | 44.97% | +8.88% | −7.61% |

**From `breakout_price`** (buying the confirmation), 20 trading days:

| mean | median | win rate | mean MFE | mean MAE |
|---|---|---|---|---|
| **+0.09%** | −1.08% | 44.91% | +9.84% | −8.37% |

With a 10% trailing stop from the breakout: mean **−0.26%**, win rate 34.5%,
**profit factor 0.93**, and **93% of positions were stopped out** — a 10% trail
is inside the ordinary daily noise of these names. Relative to Nifty 50 over
the same sessions: **−0.03%**.

| Score decile | n | reached breakout | mean ret from breakout | mean ret from ref |
|---|---|---|---|---|
| 60–69 | 4,612 | **17.5%** | −0.31% | −1.03% |
| 70–79 | 2,652 | **38.2%** | −0.25% | +0.27% |
| 80–89 | 1,079 | **58.1%** | +1.22% | +2.78% |
| 90–99 | 141 | **70.2%** | −0.45% | +4.65% |

| Year | episodes | reached breakout | mean ret from breakout | vs Nifty |
|---|---|---|---|---|
| 2025 | 4,495 | 28.9% | −0.44% | −1.05% |
| 2026 | 3,989 | 31.3% | +0.87% | +1.62% |

### What that says — no tuning

**The score predicts the breakout and does not predict the return.** The reach
rate climbs monotonically across the deciles, 17.5% → 38.2% → 58.1% → 70.2%: a
four-fold spread, on 8,484 episodes, from a score whose thresholds were fixed
before the test. That part works — the score ranks which setups clear their
level, which is the event it was built to rank.

What follows the breakout is noise. The mean 20-day return from the breakout
price is +0.09% with a 45% win rate, the decile column is not monotone and its
top bucket is **negative**, and the whole thing is −0.03% against the Nifty over
the same sessions. Mean MFE +9.8% against mean MAE −8.4% is a symmetric
distribution with no drift, which is what a coin looks like. The two years
disagree on the sign (−1.05% vs +1.62% relative), which is the signature of a
result that exists in one sample and not in the other. The ref-side decile
column *is* monotone (−1.03% → +4.65%) but most of that is mechanical: a higher
score means a closer level, so the ref price is nearer the breakout that
follows and the same move is measured from lower down.

Add costs and it is worse: 45% of confirmed breakouts close back under the
level within five bars, and the 10% trailing stop — the only exit rule tested —
returns a profit factor of **0.93** while stopping out 93% of the time.

**So: a good level-clearing predictor, and no tradeable edge in this record.**
The subject matter was never the return; the record exists to say whether the
score was worth computing, and the answer is "for the event, yes; for the
money, no". Nothing was adjusted to improve any of these numbers, and the
thresholds that produced them travel with them in the `config` block of
`/stats`.

## The routes

Read-only, all six, all under `/api/v1/tracker`. **These shapes are the
contract Phase 3 is built against** — `test_routes.py` asserts the field names
explicitly rather than by round-tripping a model, because a rename that the
fixtures do not follow is exactly the mismatch the Phase 3 definition of done
forbids.

| Route | Returns |
|---|---|
| `GET /health` | universe size, coverage, last bhavcopy, failures, corporate actions |
| `GET /near?limit=` | `[{symbol, name, state, score, close, resistance, distance_pct, tightness, is_52w_high, days_in_state, turnover_20d, bar_date}]` — **NEAR first, then by score**, sorted in SQL |
| `GET /breakouts?days=30&source=live` | `[{symbol, breakout_date, breakout_price, resistance, volume_mult, ret_since_pct, max_gain_pct, max_drawdown_pct, state, live_state, false_breakout, days_since}]` |
| `GET /stock/{symbol}?candles=750` | `{stock, levels:{clusters, nearest_resistance, is_52w_high, week52_high, atr, range_pct, tightness}, score:{score, components, state, days_in_state, distance_pct}, episode, history[], candles[]}` |
| `GET /episodes?source=&limit=&offset=` | `{total, limit, offset, items:[episode]}` |
| `GET /stats?source=replay` | the aggregate below, plus `config` and `caveats` |

`sector` is **absent** from `/near`, not null: there is no keyless source for
NSE sector classification and the paid ones may not be scraped.

With the flag off, every route answers empty. `/stock` is the exception — it
returns 503, because an empty body there would read as "no such stock".

---

## Layout

| File | What |
|---|---|
| `config.py` | every threshold, URL and budget; the flag is a function, not a constant |
| `bhavcopy.py` | pure parsing. No session, no clock, no I/O |
| `sources.py` | the archive client: retries, spacing, 404-is-an-answer |
| `ingest.py` | days, upserts, resumption, the universe, the gap flag |
| `data.py` | the read side |
| `levels.py` | swing highs, clusters, ATR, 52-week high. Pure |
| `score.py` | the five components and the 0-100 score. Pure |
| `states.py` | the state machine. Pure, and cannot see a return |
| `outcomes.py` | the return arithmetic, low-before-high. Pure |
| `stats.py` | the aggregate, including the decile table. Pure |
| `episodes.py` | the walk, the writers, and the outcome filler |
| `api.py` | `/tracker` — read-only |
| `scheduler.py` | the beat tasks |
| `__main__.py` | the CLI |
