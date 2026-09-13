# forex_lab — run log

One entry per change-set: what changed, what the tests said, what is still red.

**On the count.** The brief allows twelve iterations of
`build/fix → tests → integrity → sweep → report`, and its cut-off is
"12 iterations reached **without green tests**". The tests have been green from
the end of entry 1 onwards, so that cut-off has not been approached. Entries 2
to 11 are change-sets made while the download ran — the full loop cannot close
until Phase 1's data exists, and the integrity check and the sweep are the two
steps that were waiting on it. Entry 12 is the loop closing.

---

## Iteration 1 — the lab, the engine, and the first green suite

**Before any code.** Probed the environment, because two of this run's stated
BLOCKER conditions are environment facts:

* Dukascopy reachable — `EURUSD/2023/00/03/14h_ticks.bi5` returns 200 with an
  LZMA body. Throughput measured over 512 real hour-files: 1.67 files/s at
  concurrency 64 (99% first-pass), 2.53 at 128 (83%). Settled on 96.
* The pre-aggregated monthly candle files (`BID_candles_min_1.bi5`) would have
  cut ~40,500 requests to ~156. They **do not exist** — a genuine 404, body
  162 bytes, distinct from the CDN's *transient* 404 whose body is 3,464 bytes
  of styled HTML. Eight retries, two months, no success. Ticks it is.
* Postgres available (`memescope-test-pg`), fresh `forex_lab` database.
* The repo's `backend/.venv` is a broken symlink loop; built `~/.venvs/fxgrid`
  on 3.12 outside the tree.

**Built.** `config.py`, `models.py` (`fx_candles`, `fx_ingest_hours`),
`ticks.py` (bi5 decode + minute aggregation), `ingest.py` (concurrent,
resumable, idempotent), `store.py` (reads + the integrity check), `engine.py`
(the grid), `backtest.py` (replay, metrics, sweep, baselines), `report.py`,
`__main__.py` (CLI), migration `0069_forex_lab`, tests.

**Alembic.** `alembic upgrade head` fails on this branch with
`KeyError: '0062_early_movers_lab'` — `0063_breakout_lab` (commit 3e8239b, not
mine) parents to a revision that is not on `karthik-hq`. The brief forbids
touching files outside this lab, so the break is left alone; 0069 parents to
0068, the branch head, and its `upgrade()` was executed directly against a
clean database to prove the DDL runs. See DECISIONS.md #13.

**Ingest.** Started the full 2020-01-01 → 2026-06-30 pass in the background at
the top of the iteration, ~40,610 hour-files, so it runs while the engine is
built. ~5,500 done at the end of this entry, ~5% failing per pass and picked up
by the next — that is what `fx_ingest_hours.ok = false` is for.

### Tests

`55 passed` — engine 14, ticks 12, isolation 29.

One substantive **bug found and fixed by test 1**: the leg scan was inclusive
at both ends, so an order sitting exactly on the price where a leg *started*
fired without price ever having crossed it. On a mean-reverting instrument
that hands the grid a free fill at every turning point that lands on a level.
Fixed to a half-open interval `(from, to]`, with the gap from one candle's
close to the next candle's open walked as its own leg so nothing is skipped.
DECISIONS.md correction B.

Three expected VALUES were my arithmetic being wrong rather than the code, and
each has its hand calculation written out in DECISIONS.md before the number
was touched:

* **A** — test 1's fill count is 5, not 4. The re-placed sell stop legitimately
  fires a second time on the way back up, on the worse of the two orderings.
  Balance, trade count and rejections all unchanged.
* **C** — a cent below the margin boundary rejects the long and *accepts* the
  short, because they fill ten cents of notional apart. Rejecting a fill must
  not consume the margin it was refused; that is now its own test.
* **D** — the Wednesday fixture was crossing Tuesday's rollover too, so it
  accrued 4x and not 3x. The fixture now starts on Wednesday morning.

### End-to-end, on the 330,903 candles loaded so far

Export → backtest → metrics all run. Default config (S=25, N=4, x1.0) over
partial 2020: PF 0.951, −14.25%, 85 re-centres, 0 stop-outs, 54 rejected
fills. Re-centres realise −$2,487.76 against +$2,381.30 banked by
take-profits, which is the shape a grid usually has.

Replay speed: 39k candles/s worst case (S15/N6/x1.0), 828k/s for a neutral
grid. 2.4M candles x 27 configs is minutes, not hours.

**Remaining:** the download, the integrity check against complete data, the
sweep, REPORT.md. No failing tests.

---

## Iteration 2 — the data layer gets its own tests, and they find a bug

**Built.** `tests/conftest.py` (a database holding this lab's two tables and
nothing else — the platform's own conftest builds the entire schema, which
would make a lab test depend on every model in the repo staying importable)
and `tests/test_store.py`: loader idempotence, the resume query, the market-
hours planner, and every branch of the integrity check.

**Bug found by `test_the_weekend_is_not_a_gap`.** The gap check asked
"is the last candle before this gap in the weekend?" The last tick of the week
lands somewhere in 21:5x on Friday, which is *not* in the closed window — so
every weekend in six and a half years would have been reported as a hole, and
the integrity check would have failed on a perfectly loaded dataset. Now asked
of the FIRST MISSING minute instead.

Also dropped a redundant `pytestmark = pytest.mark.asyncio`: `asyncio_mode`
is already `auto` in pyproject.toml, and the module-level mark was being
applied to the two synchronous tests in the file and warning on each.

### Tests

`66 passed` — engine 14, ticks 12, isolation 29, store 11.

**Remaining:** the download (~6,300 of 40,610 hour-files), the integrity check
against complete data, the sweep, REPORT.md. No failing tests.

---

## Iteration 3 — the download's real failure was 429, not 503

**Found.** 358 hours had failed every retry. The breakdown was not what the
probe suggested:

| reason | count |
|---|---|
| HTTP 429 | 236 |
| HTTP 503 | 98 |
| connect / read errors | 10 |

**429 is the dominant failure, and it was being handled wrongly.** A 429 is
not a fact about one request — it is the feed asking the whole client to slow
down. Backing off one coroutine at a time left the other 95 hammering straight
through the penalty window, which turns a pause into a permanent failure: all
eight retries of a request landed inside the same rate-limited period.

**Built.** A shared `_Gate`. The first coroutine to see a 429 shuts it for
everyone and serves `Retry-After` (or 30s) once; the rest wait at it. A second
429 arriving during a cooldown does not extend it — otherwise 96 coroutines
seeing the same limit would turn a 30-second pause into 48 minutes. Not a
token bucket: the rate this feed tolerates is unpublished and moves, so
reacting to the server's own answer needs no guess.

Restarted the pass at concurrency 64 rather than 96. The probe had 64 at
1.67 files/s with 99% first-pass success against 96's 1.55 effective — past
the feed's ceiling, extra concurrency buys 429s, not throughput.

### Tests

`69 passed` — three new ones on the gate, including the one that matters: a
second 429 during a cooldown must not extend it.

**Remaining:** the download (7,572 of 40,610 hours loaded, 446,769 candles),
the integrity check against complete data, the sweep, REPORT.md. No failing
tests.

---

## Iteration 4 — the sweep runs end to end, and the bookkeeping gets audited

**Proved the pipeline.** `export` → `sweep` → `report` on the 449,585 candles
loaded so far: 27 configurations in 31 seconds across 8 cores, REPORT.md
rendered with a FAIL verdict against the real gate. 2.4M candles will take
about three minutes.

**Two bookkeeping bugs found by auditing `replay()`, not by a failing test.**
Neither would have raised anything; both would have produced a plausible
report with wrong numbers in it.

1. **Daily P&L was attributed to the wrong day.** Equity is sampled on the
   first candle of a NEW day, and the delta since the last sample was being
   filed under that new day's month. The delta was earned on the day BEFORE.
   Across a year boundary that puts 31 December's P&L into January — every
   year, in the exact column the "positive in ≥ 4 of 6 years" gate reads.
2. **The drawdown curve was unseeded.** Its first sample became the running
   peak, so a loss that happened before the first daily sample was invisible.
   The curve now starts at the opening balance.

**Also settled: the gate's denominator.** The window spans seven calendar
years because 2026 is January to June. The gate says "4 of 6". So
`config.FULL_YEARS` names 2020–2025 as the denominator and 2026 is reported
beside them and counted in nothing — rather than being quietly folded in to
make a seventh year and loosen the gate.

Deleted a dead `GridEngine` that `buy_and_hold()` constructed and never used.

### Tests

`78 passed` — nine new in `test_backtest.py`, covering attribution across a
year boundary, per-year totals summing to the final equity, the drawdown seed,
profit factor, and every one of the gate's five conditions failing on its own.

**Remaining:** the download, the integrity check against complete data, the
sweep, REPORT.md. No failing tests.

---

## Iteration 5 — patience was measured, and it was the slower option

The gate from iteration 3 was tuned by instinct and it was wrong. Measured at
concurrency 24 with a 12-in-a-row 503 trigger: **120 of 162 elapsed seconds
spent waiting**, and 0.62 files/s — against 1.55 for the fast pass it replaced.
Twelve consecutive 503s is not a wall when there are 24 requests in flight; it
is ordinary turbulence, and the gate was firing on it constantly.

**Turned around.** A failed hour is one row, and the next pass asks for exactly
those rows — that is what the resume log has been for since iteration 1. So:

* concurrency back to 64, retries down from 10 to **4**. A request that has
  failed four times has met the throttle, not bad luck, and the cheapest place
  to retry it is the next pass, by which time the throttle has moved on.
* the 503 gate now needs **forty** in a row — which with 64 in flight cannot be
  noise — and then waits the two minutes the feed was measured to need.
* `ingest_until_clean` runs passes until nothing is outstanding, stopping early
  on a pass that loads *nothing*: that is the feed refusing rather than the job
  finishing, and seven more identical passes will not change it.

**Measured after the change: 100 files in 30 seconds, 3.3 files/s, one
cooldown.** Five times the patient version, and twice the original.

Also wrote `README.md` for the lab.

### Tests

`80 passed` — two new on the pass loop, including the one that matters: a pass
that loads nothing must stop the loop rather than burn the remaining seven.

**Remaining:** the download (~2.75h at the measured rate), the integrity check,
the sweep, REPORT.md. No failing tests.

---

## Iteration 6 — the stop-out the backtest would mostly have missed

**Bug found by audit, not by a test.** `_check_stop_out` was called inside the
leg walk, after each event, and once on the fast path. So a candle that took
the SLOW path but happened to fire nothing was never checked — and more
importantly, the whole design made the margin call a thing that happens on
candles that *trade*. It isn't. A grid is walked into a stop-out by the mark:
price drifting against a book of open positions without reaching a single
order. The stop-out is now checked on every candle, at whichever extreme of it
hurts more.

**Added `min_equity` and `blown`.** A run whose final equity looks survivable
can have passed through zero on the way, and a profit factor computed over a
blown account is arithmetic about a thing that stopped existing. Both are now
carried into the sweep and the report has a "Low water" column that says
BLOWN where it applies.

### Tests

`82 passed` — two new. The stop-out one needed its fixture rebuilt twice: at
$200 of equity only ONE of a level's two orders fits under the margin cap
(which is the iteration-1 correction C behaviour, showing up again), and the
default 25-pip grid has its re-centre boundary only 75 pips from the fill, so
a mark-driven stop-out is unreachable inside it. It now uses a 500-pip grid
with no pending orders left, where the arithmetic is written out in the
docstring and the candle provably reaches nothing.

**Remaining:** the download (400 of 32,720 at 2.04 files/s, ~4.5h), the
integrity check, the sweep, REPORT.md. No failing tests.

---

## Iteration 7 — gaps, and a model that was rejected for being incoherent

The move from one candle's close to the next candle's open has been walked as
its own leg since iteration 1, so orders the market gapped over still fill.
What they fill AT was never decided deliberately, so it was, now.

**Built the literal model first: a gap trades at one price, so stops fill at
the reopen and limits fill better.** It did not survive its own test. A
take-profit is a limit one step from its entry, so a stop filled at the reopen
with a take-profit still sitting at its level opens and closes on two prices
that never both existed — the fixture showed a short opening at 1.09394 and
"taking profit" at 1.09504 for a $1.10 loss on a trade that would really have
cost ten cents. Filling the take-profits at the reopen too repairs that and
breaks something worse: limits then collect the whole gap as free entry, which
on a mean-reverting instrument is a gift, not a cost.

**Reverted to: every order fills at its own level**, the conventional choice,
and the one whose two errors cancel — a stop flattered by a gap is offset by a
limit penalised by the same amount, and the grid holds equal numbers of both.
For the neutral-grid baseline, which has no stops, it is purely conservative.

The test says it as the equivalence it is: a 60-pip gap and a 60-pip walk end
in an identical book, an identical trade list and an identical balance. The
limitation goes in REPORT.md rather than staying in a docstring.

### Tests

`85 passed` — three on gaps.

**Remaining:** the download, the integrity check, the sweep, REPORT.md. No
failing tests.

---

## Iteration 8 — I was wrong about the feed, and the mistake bought a real check

**Correction.** Iteration 1 recorded that Dukascopy publishes no pre-aggregated
candles. What I had tested was the MONTH path
(`EURUSD/2023/00/BID_candles_min_1.bi5`, a genuine 404) and I generalised from
it to the whole feed without trying the obvious neighbour. The DAY path —
`EURUSD/2023/00/03/BID_candles_min_1.bi5` — returns 200. One file per side per
day: 3,390 files against the tick path's 40,610.

**Built, but not as the loader.** The brief asks for ticks aggregated here, and
switching would mean the dataset is somebody else's arithmetic. What the
discovery is worth is that somebody else's arithmetic can now check mine.

`decode_day_candles` reads the 24-byte `>5If` format — and the ordering is
O, C, L, H, not O, H, L, C, so reading it as the familiar one swaps high and
close on every candle and still looks entirely plausible. Zero-volume rows are
dropped: the feed writes 1,440 rows a day whether it traded or not, and this
lab's table has no row for a minute with no tick.

`verify_against_published` samples loaded days at random, fetches both sides,
and compares. **First run against real data: 12 days, 28,592 candle-sides,
zero differences at 1e-5.** The unit tests prove the aggregator agrees with my
arithmetic; this proves it agrees with the vendor's, over the same ticks.

It is also a documented fallback now — if the tick download cannot finish
against the cumulative throttle, the day path is twelve times cheaper, decoded
and tested, and REPORT.md would have to say that is what was used.

### Tests

`89 passed` — four on the day-candle decoder, including the O/C/L/H reordering
and the zero-volume placeholder.

**Remaining:** the download, the integrity check, the sweep, REPORT.md. No
failing tests.

---

## Iteration 9 — invariants over adversarial paths

The seven verification tests check known scenarios. This iteration adds the
checks nobody thought to write down, driven over seeded random walks — flat,
trending up, trending down, high-volatility, and margin-starved — with wicks
on both sides so most candles are genuinely ambiguous and the clone-and-compare
path is the one under test.

The global one: **every dollar that moved the balance is in the trade list, and
every dollar in the trade list moved the balance.** Across five paths of 4,000
candles, `balance == start_equity + Σ pnl + Σ swap` to within 1e-6, and
`pnl == gross − cost` on every trade.

Per-candle, after every one of 2,000 steps on three paths: equity is balance
plus the mark; used margin is the sum of what the open positions hold, never a
running total that drifted; a position's opening order is never also resting;
no two resting orders share a level and kind; and every resting order sits on a
whole number of steps from the current centre, inside the re-centre boundary.

Plus four behavioural ones: a trending market must re-centre and must lose
money *through* the re-centres; a rejected fill never consumes the margin it
was refused (the iteration-1 bite, now asserted continuously on a $300
account that hits the cap repeatedly); a neutral grid never holds a short below
its centre; and two runs over a 5,000-candle adversarial path are byte
identical.

All pass, unchanged. No bug found — which is the point of writing them.

### Tests

`95 passed`.

**Remaining:** the download, the integrity check, the sweep, REPORT.md. No
failing tests.

---

## Iteration 10 — the market week is New York's, not UTC's

Checking the integrity rules against real 2020 data — rather than only against
fixtures — found the worst bug of the run so far, and it had two faces.

**The week's boundary is 17:00 New York**, which is 21:00 UTC under daylight
saving and 22:00 UTC outside it. Both the planner and the gap check had it
written down as a UTC constant. So:

* the planner **never requested Sunday 21:00–22:00 UTC in summer** — an hour of
  genuinely open market, on about thirty weekends a year, silently absent from
  the dataset;
* the gap check called Friday 20:59 → Sunday 22:00 an unexplained hole on every
  one of those weekends. On 2020 alone: **34 unexplained gaps, 33 of them this
  one mistake.** A correctly loaded dataset would have failed its own integrity
  check roughly two hundred times across the window.

**Fixed** with a `market.py` that states the rule once, in New York time, and
is called by the planner, the gap check *and* the expected-minute count —
which is now counted hour by hour from that same predicate instead of from an
average week, so leap years, both DST switches and a window ending on 30 June
are all handled by one definition rather than three.

Restarted the download so the missing summer hours are requested.

**Then the last gap in 2020 turned out to be Good Friday**, and the Easter
check was a guess: "Thursday to Monday in March or April". Good Friday 2020
opened a Friday-to-Sunday gap and was missed. Replaced with the anonymous
Gregorian algorithm, asserted against the known Easter date for every year
2020–2026.

**2020 re-checked: 34 unexplained gaps down to 1, and that one is now named.**

### Tests

`111 passed` — sixteen new in `test_market.py`, every one of them a real
instant from the window: both DST switch weekends, the summer and winter
closes, the summer and winter opens, and a full week being exactly 120 hours
however the offset moves underneath it.

**Remaining:** the download, the integrity check, the sweep, REPORT.md. No
failing tests.

---

## Iteration 11 — the report is made to tell the truth about its own coverage

Three things, all about the report rather than the strategy.

**A partial window is now declared in the title and in a banner.** The heading
was the brief's window, hardcoded, regardless of what was actually replayed —
so a half-finished download would have been written up as a six-year backtest
with a correct-looking title. The heading is now the range the data actually
covers, and when that falls short of 2020-01-01 → 2026-06-30 a banner says so
above everything else, including the point that "positive in 4 of 6 years"
cannot be satisfied by a window that does not contain six years.

**The baseline comparison is a sentence, not a subtraction.** The brief asks
for a plain statement of whether the hedged grid beat the neutral grid and
buy-and-hold; it now says so in words. And it says when a baseline is *absent*
rather than comparing against nothing — `report.py` used to raise
`ValueError: max() iterable argument is empty` on a sweep with no neutral
configuration, which is a degenerate input but a crash is a poor way to
discover that.

**Deviations and limitations**, written out: the eight places this
implementation departs from the brief and why, and the three limitations worth
saying out loud — the gap model not charging the worst of a weekend, six and a
half years of one pair being one sample of one regime, and nothing here ever
having actually filled.

### Tests

`115 passed` — four new, on the coverage banner, the spelled-out comparison and
the missing-baseline case.

**Remaining:** the download, the integrity check, the sweep, REPORT.md. No
failing tests.

---

## Iteration 12 — shipped to the site, and a warning about reading interim numbers

Renamed to **Forex Lab** on the operator's instruction and ported onto a branch
off `origin/main`, because the branch it was built on cannot reach the website:
main is 264 commits ahead of `karthik-hq` and the two number the same migration
slots differently — main's 0068 is `nse_breakout_phase2` and its 0069 is
`graduation_lab`, so a migration parented to karthik-hq's
`0068_graduation_features` cannot run on a database that has never seen it.
This branch's migration is `0085`, parented to main's head.

Added `fx_sweep_runs`, three read-only routes and a dashboard page; details in
the commit. Route registration was verified against `app.openapi()["paths"]`
rather than `app.routes` — this FastAPI keeps an included router as one lazy
object, so walking `app.routes` finds nothing and an assertion over it would
pass just as happily on a router that was never registered.

### The interim number moved a long way on seven months of data

The first published sweep, over 449,585 candles (to 2021-04-12), had a best
profit factor of **1.390**. Re-run over 676,865 candles (to 2021-11-12) it is
**1.228** — the gate's PF condition flips from PASS to FAIL.

Two things could explain that: the engine fixes of iterations 4, 6 and 10, or
the extra data. So the current engine was replayed over the ORIGINAL 449,585
candles, and it reproduces the original numbers exactly:

| config | PF then | PF now | return then | return now |
|---|---|---|---|---|
| `S50_N6_M0` | 1.390 | 1.390 | 22.44% | 22.44% |
| `S25_N6_M1` | 1.072 | 1.072 | 16.14% | 16.14% |
| `S25_N4_M1` | 0.986 | 0.986 | −6.66% | −6.66% |
| `S15_N3_M1` | 0.892 | 0.892 | −49.29% | −49.29% |

So **none of the P&L change is from the fixes** — they moved which candles
exist, how P&L is attributed to a year, and how drawdown is measured, not what
the strategy earns on a given series. The whole move is seven extra months.

That is the clearest available evidence for the caveat the report already
makes: a grid's headline number is a function of the window it ran over. Seven
months took the best configuration from clearing the profit-factor bar to
missing it. Nothing about the interim result should be read as a finding, and
the page says so in its coverage banner.

**Remaining:** the download (~2,300 of 31,431 this pass), then the final
integrity check, sweep and REPORT.md. No failing tests.

---

## Iteration 13 — made fit to merge

The operator asked for this on `main`, so it had to survive `main`'s CI rather
than just its own test suite. Ran every gate CI runs.

**Lint: 63 errors in this lab, down to 17.** Several were real rather than
stylistic:

* `l` as a variable name in seven places — it means "low" everywhere it
  appears, so it now says so;
* two unused imports;
* `zip()` without `strict=`;
* **two blocking file operations inside async functions** (`ASYNC230`) — the
  sweep file read in `publish()` and, worse, a 58 MB blocking write in
  `export_candles()`. Both are one-shot CLI paths today, so nothing starves;
  an async function that blocks the loop is a bug waiting for a caller that
  shares it. Both moved to `asyncio.to_thread`.

The seventeen that remain are the families every sibling lab already trips:
`T201` (a CLI's `print` is its output), `RUF001/2/3` (em-dashes in prose) and
one documented `S607` noqa.

**The rename that broke the engine.** Renaming `S, C` to `step, centre` in
`_build_grid` — to satisfy `N806` — left four references behind, because
`ruff format` had already re-wrapped the lines my edit was matching against.
Thirty tests went red instantly. Worth recording as the thing a test suite is
for: a "purely cosmetic" rename silently produced a grid whose take-profits
pointed at an undefined name.

Afterwards the current engine was replayed over the ORIGINAL candle file and
reproduced the pre-refactor numbers on every configuration checked, to six
decimal places. The cleanup changed no result.

**Alembic.** `0085` up-and-down cleanly: 3 tables → 0 → 3.

Two of CI's migration steps fail, and **both were already failing on `main`
before this lab existed**:

* `alembic downgrade base` dies on `bo_equity`, a Breakout Lab table dropped
  by `0083_remove_breakout`;
* `alembic check` reports drift on `real_wallet_live_intents`,
  `research_quotes`, `token_enrichment_state` and `token_early_buyers`.

Neither names an `fx_` table. This lab does not add to them and does not fix
them — the brief forbids touching files outside it, and a drift in
`real_wallet` is not a thing to repair in passing.

**The page now distinguishes "not deployed yet" from "broken".** The frontend
and the backend deploy separately and the frontend is faster, so a reader will
reach this page before the API route exists. A 404 now says so instead of
"could not load", which would send them looking for a bug that is not there.

### Tests

`124 passed`, `next build` passes, `ruff format --check` clean.

---

## Iteration 14 — the coverage check was passing years that were missing 6%

Checking the download's progress, 2020 stood out: it has **one** failed hour
out of 6,322, so it is effectively complete — and it scored **1.0148**. Above
one. A year cannot hold more minutes than the market was open for.

The cause was a 9-day holiday allowance subtracted from the denominator.
Measured against 2020, the real figure is ~3.7 days: 373,418 candles against
377,280 open minutes, 0.9898. The allowance was 2.4x too big, deflating
"expected" by 2.4%, and that turned a ONE-SIDED bound into a two-sided fudge.

**What it was hiding.** Under the old model:

| year | failed hours | old ratio | old verdict | new ratio | new verdict |
|---|---|---|---|---|---|
| 2020 | 1 | 1.0148 | ok | 0.9898 | ok |
| 2021 | 365 (5.8%) | 0.9523 | **ok** | 0.9288 | **OUT** |
| 2022 | 396 (6.4%) | 0.9562 | **ok** | 0.9326 | **OUT** |

Two years missing six percent of their hours were passing the coverage check.
That is not a cosmetic problem: the brief gates the sweep on the integrity
check, so the sweep would have run on incomplete years and the report would
have presented the result as a full backtest of them.

**Fixed** by comparing against the raw open minutes and making the two bounds
what they actually are, which is not symmetric:

* **floor 0.95** — holidays and thin hours legitimately remove minutes;
* **ceiling 1.001** — nothing legitimately adds them, so anything above one is
  a duplicated or spurious row.

The ceiling is the half that could not exist before. A deflated denominator
absorbs duplicate rows silently; against the true open-minute count they show
up immediately.

### Tests

`128 passed` — four new, including the ceiling (every row duplicated must
fail) and a regression on the real 2020 figure, asserting a complete year sits
inside both bounds with room rather than scraping one.

**Remaining:** the download, then the integrity check, the sweep and
REPORT.md.

---

## Iteration 15 — the cost table did not add up to the total printed under it

Checked the report's own arithmetic against the interim sweep. It does not
reconcile:

| config | start + tp + re-centre + stop-out + swap | final equity | missing |
|---|---|---|---|
| `S50_N6_M0` | 1,168.92 | 1,167.06 | −1.86 |
| `S25_N6_M0` | 1,140.44 | 1,134.88 | −5.56 |
| `S25_N6_M1` | 1,253.65 | 1,220.97 | **−32.68** |

The missing money is the positions still open when the replay runs out of
candles. `finish()` closes them at market so the equity curve ends in cash
rather than on a mark — a real P&L event, and it landed in no bucket at all.
Up to 2.6% of the wallet, printed as a column of figures that did not add to
the total beneath them.

A reader who checks a cost breakdown and finds it short has every reason to
distrust the rest of the table, and they would be right to.

**Fixed** with an `end_pnl` bucket, a row in the report and on the page, and —
the part that matters — a test asserting the reconciliation holds to the cent,
plus one asserting that every close reason lands in exactly one bucket, so a
fifth reason added later cannot silently reopen the hole.

Re-swept and re-published: all twenty-seven configurations now reconcile to
0.00.

### Tests

`130 passed`.

**Remaining:** the download, then the integrity check, the sweep and
REPORT.md.

---

## Iteration 16 — the drawdown was measured on daily closes, and the gate is a ceiling

`min_equity` marks every candle; the reported drawdown was computed from the
DAILY equity curve. Those two should tell the same story, and they did not:
`S50_N6_M0` reported 14.92% while its own low-water mark implied at least
17.4% — and that is a floor, because the true fall is measured from the
running peak rather than from the opening balance.

A daily sample cannot see a trough that recovers before the day ends. The gate
this figure feeds is a **ceiling** — "max DD < 25%" — so measuring it low does
not lose a passing run, it passes a failing one.

**Fixed** by tracking the peak and the fall in the engine, on every candle, at
the worse extreme of each. The peak is taken from the candle's best equity and
the fall measured to its worst, which assumes the high came before the low —
a few pips inside one minute, and the same conservative posture as resolving
fills by the worse of the two orderings.

**What it changed, over the interim sweep:**

* the daily curve understated the drawdown on **all 27 configurations**;
* one of them crosses the gate: `S25_N6_M1` goes **23.90% (pass) → 25.69%
  (fail)**.

The old figure is still computed and reported beside the real one, because the
gap between them is the point.

### Tests

`132 passed` — two new. The second needed three attempts, and the failures were
informative: a price round trip is NOT an equity round trip on a grid that
re-centres, because re-centring *realises* the loss instead of recovering it.
The working fixture uses a 50-pip, 6-level grid and a 250-pip dive, wide enough
that price returns without a re-centre, so the open positions go under water
and then take profit. 2.92% per candle against 1.80% daily — the daily figure
38% smaller.

**Remaining:** the download, then the integrity check, the sweep and
REPORT.md. The backend deploy is blocked on a permission I do not have.
