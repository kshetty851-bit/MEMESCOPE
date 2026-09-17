# Rafiq Lab — G1 (MOONSHOT) build report

Built 2026-09-17. G1 replaces F2 as the lab's sixth book and is the only book
that opens positions. A2–F2 are archived under run id `F2-and-earlier`.

## Where this was built, and why not on `karthik-hq`

The brief says to work on `karthik-hq`. That branch does not contain the lab
the brief describes: it holds only the v1 lab (books A–E, migration
`0056_rafiq_lab`) and is 346 commits behind `origin/main`. A2–F2,
`entry_gate.py`, `outcomes.py`, `strategy_f2.py` and the candidates table exist
only on `main`, which is also what production runs.

So this work is on a new local branch, **`rafiq-g1`, cut from `origin/main`
(7045b2f)**, in its own worktree (`~/Projects/memescope-rafiq-g1`).
`karthik-hq` was not touched: another session was working on it in
`~/Projects/memescope-fxgrid` at the time. Nothing was pushed. The migrations
are numbered after `main`'s head (`0091_real_wallet_ticket`), not after
`karthik-hq`'s (`0069`). A `0070` parented on `karthik-hq` would collide with
`main`'s own `0070`.

## Phase 0 — the valuation bug

### What was wrong

There were two defects on one path, and together they sold vanished pools at
full value.

1. **`engine.evaluate`, no-mark branch.** When nothing priced the token at a
   tick and the max hold had passed, the position closed at
   `last_mark_price`. That is the last price anyone had seen, often hours
   earlier.
2. **`service._settle`, depth fallback.**
   `liquidity = obs.liquidity_usd if obs and obs.liquidity_usd else pos.entry_liquidity_usd`.
   Whenever the exit reading had no depth, the sale was priced into the depth
   the pool had **at entry**. That happened when there was no reading at all,
   and also when the feed mapped a drained pool's `0` to `None`. The second
   case hit every exit reason, not just `max_hold`.

A token whose pool had gone was therefore sold at its last healthy price into
its entry-day depth. That is roughly 99% of the stake, booked from a pool
nobody could trade.

### Evidence (A2–E2 archive, restored locally)

`~/Projects/MEMESCOPE-archives/rafiq_v2_A2E2_final_20260912T141358Z.sql.gz`
holds 840 closed trades.

- **180 of them took the no-mark `max_hold` path.** Their evidence says
  "no current market — exited at the last observed price …, priced against the
  pool's depth at entry".
- "Mark age" below is `closed_at − last_evaluated_at`, meaning how old the
  price was when it was booked.

| book | no-mark exits | booked return | mean mark age | stops in the same book |
|---|---|---|---|---|
| A2 | 16 | −0.7% | 630 min | −86.8% |
| B2 | 48 | −0.2% | 95 min | −83.8% |
| C2 | 71 | **+13.8%** | 141 min | −86.8% |
| D2 | 32 | **+23.6%** | 136 min | −87.4% |
| E2 | 13 | +3.6% | 396 min | −99.8% |

These are the C2 and D2 fake proceeds the brief describes.

**How the platform marks a dead pool** (traced through
`services/market/*`):

- A pool that is still listed but drained prints `inactive`, with a
  **still-populated, possibly stale price**.
- A pool the provider stops returning gets NULL placeholder rows marked
  `inactive`.
- `token_enrichment_state.delisted_at` is stamped on the first empty poll and
  cleared if the pool returns.

**The published friction figure was inflated by the same bug.**
`api._execution_cost` measured exit drag from the *observed print*, so two
things were booked as execution cost:

- a dead pool's leftover print, which nobody could sell into;
- the take-profit fill cap.

Across A2–F2 in the archive, friction came to **4.08% of notional**:

| component | share of notional |
|---|---|
| dead-pool exits (exit impact ≥ 50%) | 1.57% |
| fill cap | 1.12% |
| entry fee + impact | 0.74% |
| exit fee + impact | 0.65% |

The F2-only 9.3% figure in the brief comes from prod rows after this archive.
I could not re-measure it: a read-only prod query was refused by this
session's permission policy. Its shape matches the archive's.

### The fix

**One rule for every exit: sell into the reading the price came from, or into
nothing.**

- **`feed.pool_reading`** (new, pure) returns the newest tradeable print
  (trading status, price > 0, liquidity > 0), or `None` when the pool is gone.
  - The pool counts as gone when an `inactive` reading, or a `delisted_at`
    stamp, comes after the last tradeable print.
  - One dead poll is not a death: a tradeable print inside
    `DEATH_CONFIRMATION_SECONDS` (120s, the platform Lab's own window from
    `app.lab.marks`) still stands.
  - Provider-gap rows (trading status, no price or depth) decide nothing
    either way.
- **`feed.observe`** takes price **and** depth from that one reading.
  `Observation.is_tradeable` requires both.
- **`service._settle`** only marks against a tradeable reading. The depth for
  the sale is **that reading's** depth. The entry-depth fallback is deleted.
- **`engine.evaluate`**: at the box with no tradeable reading, the position
  still closes, because a zombie must not outlive its hold. It now fills at
  **0** and is valued at 0. The last priced print is kept in `exit_evidence`
  only.
- **`api._execution_cost`** measures exit drag from the **fill**, so
  "execution cost" is fee plus impact and nothing else. The fill cap and dead
  pools now show up as price P&L, which is what they are.

**Staleness is deliberately *not* a death.** This lab's positions are not in
the platform's priority re-pricing lane (`services/market/priority.py` only
covers paper and V6 Lab holdings). So a held token older than 6h is
re-priced only every 30 minutes. A fixed staleness cut-off would have zeroed
healthy F2 positions at their 8-hour box. A print is refused only by a death
signal, or by falling outside the feed's existing 2-hour lookback.

### Tests

- **`tests/test_exit_valuation.py`** (new) drives the real settle path,
  `RafiqLabService.tick`.
  - Five cases **fail on the pre-fix code** and pass after:
    - silent pool: pre-fix booked $49.61 of $50;
    - drained `inactive` pool printing +20%: pre-fix booked $59.48;
    - delisted pool;
    - one-poll `inactive` blip valued at the live print's own depth;
    - friction measured from the fill.
  - Two controls pass both before and after:
    - live pool valued at its own depth;
    - slowly polled live pool is still a market.
  - One pure table test covers `pool_reading`.
- **`tests/test_strategy_b.py::test_a_token_that_stops_printing_still_hits_the_box`**
  asserted the bug (`fill_price == 0.93`, the last print). It now asserts the
  position still closes at the box, at 0, with the print kept in the
  evidence.
- **Three inventory tests were already failing on `main`.** The F2 build left
  them red on purpose ("report it, do not edit it"). This brief asks for a
  green suite, so they now match the real inventory:
  - `test_full_cycle`: six books, and F2 enters;
  - `test_entry_gate`: F2 runs its own gate;
  - `test_isolation`: the candidates table is in the metadata.

**Gate:** lab suite 141 passed plus the G1 package 37 passed (178 in total),
with 0 failed.

### A count that does not match the brief

The brief says 22 + 33 = 55 G1 tests. The delivered `test_strategy_G1.py`
collects 22 (21 functions, one parametrised twice). The delivered
`test_learning.py` has **15** test functions, not 33. The G1 package
therefore has 37 tests, and all 37 pass after every phase.

The only edits to either test file are the import lines:

- `from strategy_G1` became `from app.labs.rafiq.g1.strategy_G1`;
- `from learning` became `from app.labs.rafiq.g1.learning`;
- `import learning` became `from app.labs.rafiq.g1 import learning`;
- ruff's isort split the two import lists one name per line.

`g1/ruff.toml` accepts the delivered files' remaining lint findings rather
than editing them:

- the module name `strategy_G1`, which its tests import;
- `strategy_G1.py`'s unused `field` import;
- the tests' unused `pytest` import;
- the tests' Yoda-style asserts.

## Phase 1 — runs, and G1 in the engine

### Runs

**`lab_run_id`** is now a column on three tables:

| table | role |
|---|---|
| `rafiq_lab_strategies` | config |
| `rafiq_lab_positions` | trades |
| `rafiq_lab_daily_state` | the equity snapshot: day-open mark-to-market equity |

- **Backfill.** Every existing row gets `F2-and-earlier` through a server
  default, and the migration then **drops** that default. A row written
  without a run fails instead of quietly joining the archive.
- **G1's run id** is `G1-2026-09-17`. The date is the `generated` date in G1's
  canonical JSON, the day its rules were frozen. The row's `activated_at`
  records when it actually started trading.
- **Config selection is by run.** `activate()` and `tick()` only create and
  read rows of `registry.CURRENT_RUN`. The strategies' unique key moved from
  `code` to `(lab_run_id, code)`. F2's row is never re-read, re-hashed or
  rewritten. A test compares its id, lane, starting equity, digest and
  `activated_at` before and after a G1 tick.
- **Reset.** A new run is a new strategy row at $1,000, and cash is derived
  per book, so G1 starts from a clean $1,000 while A2–F2 keep their numbers.
- **Old runs stay queryable.**
  - Every API route takes `?run=`, which defaults to the current run.
    `?run=F2-and-earlier` shows A2–F2.
  - SQL examples are at the end of this report.
- **A2–F2 stay in the registry with `enters=False`.** They are there so an
  archived book still renders and its digest still verifies.
  - Their digests are unchanged, because `enters` is outside the hash:
    A2 `bba07d8c`, B2 `068d3a0e`, C2 `9809be8c`, D2 `5fa3c4e2`,
    E2 `6c42fd38`, F2 `a753e73d`.
  - A module-level assert pins that G1 is the only entering book.

### Decision: what happens to positions A2–F2 still hold

They are **drained**. Each tick settles every open position of a
non-current run under the geometry frozen on its row, using the Phase 0
valuation. It opens nothing and asks no breaker.

- **Why:** "A2–E2 stay archived and do not run" is read as *open nothing*.
  Freezing open positions for ever would leave the archived record
  permanently incomplete and still marked at stale prices. Force-closing them
  is what the lab exists to avoid, since it sells a whole book into drained
  pools.
- **Timing:** F2's hold is 8h, so the drain is finished within about 8h of
  deploy.
- **After that,** it costs one empty query per tick.

### G1 in the engine (`service.py`)

**Exits.** A G1 position goes through `strategy_G1.evaluate(position, price,
now, abandon_gain=row.abandon_gain)`, the delivered function, called on the
tick's tradeable reading. A position with no tradeable reading holds until
the 45-minute box, and then closes at 0, exactly as Phase 0 defines.

**Partial sale.** When `evaluate` answers `scale_out`, the engine:

- sells that fraction (0.75) into the reading's depth;
- sets `scaled_out=True`, `fraction_open=0.25` and `scaled_out_at`;
- adds the proceeds to `realised_usd`;
- keeps the row **open**.

The fill carries the same 1.15× drift cap every level exit has, so a gap-up
print is a real fill and never an unlimited one.

**Exit reasons.** These are stored verbatim from `strategy_G1.Exit`:
`abandon_flat`, `runner_trail`, `stop`, `max_hold`.

**Decision:** `scale_out` is a partial sale, **not** a close, so it is never a
row's `exit_reason`. It is recorded by `scaled_out`, `scaled_out_at` and
`scale_out_price`, plus a `rafiq_g1_scale_out` log line. The final
`exit_reason` of a scaled-out position is whichever rule sold the last 25%.

**Decision: how a closed row reads.**

- `exit_proceeds_usd` is the **whole** position's proceeds, the scale-out
  included. Every existing `exit_proceeds_usd − cost_basis` in the lab (cash,
  the API, the analyst) therefore stays correct without a special case.
- `fraction_open` is left at the slice the final exit sold: 0.25 after a
  scale-out, 1 otherwise. That is what the "excluding the runner leg" SQL
  below needs.
- `api._execution_cost` prices a scaled-out row at its two fills.

**Frozen parameters.** `abandon_gain` and `size_multiplier` are written onto
each position at entry and never updated, like the rest of its geometry. A
test proves the stored threshold is the one evaluated: a row with 0.03 holds
at +6% while a row with 0.08 is abandoned.

**Sizing.** `strategy_G1.position_size(current_equity)` is multiplied by the
learning multiplier, which is 1 in this phase, and quantized to cents.

**Decision: current equity.** It is cash plus each open slice valued at what
its pool would pay (`sell_proceeds` at the last tradeable reading's depth,
and 0 once the pool reads gone). This `_value` is the exit valuation applied
now, and it feeds the breaker, the ratchet and the API alike. The old
`quantity × last price` mark kept a drained pool at full value until its box.

**Gate.**

1. Freshness: the candidate and its observation must each be at most 15
   minutes old.
2. Score at least 70 (`entry_score_min`).
3. `strategy_G1.admits(liquidity, market_cap)`. A missing market cap does not
   refuse, which is the semantics `admits` documents.
4. F2's 1.5% modelled-impact ceiling (`max_impact_pct` in the config).

Refusals are recorded under the lab's existing reason codes.

**Equity ratchet.**

- The delivered `EquityRatchet` is persisted in `rafiq_lab_run_state` (the
  high-water mark and the floor), so a restart cannot put the floor back to
  $950.
- `update()` runs after settling and before and after each entry.
  `check()` runs before every entry.
- A breach halts **new entries only**; open positions keep settling on their
  own rules.
- **Every floor move** writes a `rafiq_lab_adjustments` row
  (`parameter='equity_ratchet_floor'`, old, new, reason) and a
  `rafiq_g1_ratchet_floor_moved` log line.
- The opening state is high-water $1,000 and floor $950, matching both the
  config and `EquityRatchet`'s defaults.

**Daily breaker.** G1 uses the lab's existing breaker (`daily_breaker=True`,
E's `DailyBreakerPolicy`):

- a 5% drawdown in mark-to-market equity **including open positions**, which
  is the config's line;
- plus the policy's 8% realised-loss line.

**Decision:** the breaker is **not latched** for the rest of the day, because
that is how this service has always run it for E2 and F2 (it is re-evaluated
each tick). Latching it would be a behaviour change for the whole lab, and
the brief did not ask for one.

**Canonical config.**

- The registry loads `g1/strategy_G1.json` and builds G1's gate, display
  profile, starting equity and opening floor from it.
- G1's digest hashes the JSON's rules, with every `_`-prefixed commentary key
  excluded. A changed rule is therefore a new record and halts the runner on
  drift; an edited explanation does not.
- A test holds every number the JSON shares with `strategy_G1.py` and
  `learning.py` equal.

**`strategy_G1.py`** got the one allowed refactor: `evaluate(...,
abandon_gain=ABANDON_UNLESS_GAIN)`.

### Two fixes found on the way

1. **A glitch print became the peak.** `_settle` raised `peak_price` before
   the engine refused the print as off-band. A single 10× spike would then
   have fired G1's 45% runner trail, or any book's trail, on the next normal
   print. An off-band print now updates nothing, for every book.
2. **The run-state row would have been inserted twice in one tick.**
   Production's `SessionFactory` runs with `autoflush=False`, so a second
   lookup in the same tick could not see the first insert. The row is now
   flushed when it is created. The replay test caught this.

### Tests

**`tests/test_g1_engine.py`** runs 101 ticks over 22 synthetic trades on
fixed price paths through `RafiqLabService.tick`. The paths cover:

- 3 × scale-out then runner trail;
- 2 × scale-out then box;
- 3 × abandon;
- 3 × stop;
- 3 × held to the box;
- 2 × scale-out then stop;
- 1 × glitch print then abandon;
- 1 × scale-out then dead pool;
- 4 × dead pool.

For every trade it asserts the reason, the exit minute, the scale-out minute
and fraction, and the proceeds recomputed from the path. It also asserts the
entry quantity and the frozen parameters.

The ratchet part asserts that:

- wave 1 moves the floor 950 → 997.72 in five logged steps;
- the dead pools sink cash to $977.82;
- the two later admissions are **not entered**;
- the day is marked halted by the ratchet;
- every dead position still left at its own 45-minute box.

**Also in that file:**

- the frozen abandon threshold is the one evaluated;
- the bet is 1% of the current book ($11 on $1,100);
- the floor survives a restart;
- archived books are kept, not rewritten, drained, and never reopened;
- a G1 cycle leaves the Karthik wallet byte-identical;
- the config and the code agree;
- the digest ignores commentary.

**`tests/test_api_runs.py`** covers all five routes over HTTP, for the
current run, the archived run and an unknown run.

**Older tests.**

- The mechanism tests for the v2 books (legs, F2's floor and cap, the
  candidates ledger, the Phase 0 valuation) now carry a `v2_run` fixture. It
  runs the archived run exactly as it traded: all six books entering, and the
  default run pointed at it.
- The daily-cap test's twenty held positions now have live markets. Under
  pool valuation, twenty unpriced positions are worth $0 and would sink F2
  through its floor before the cap could bind.
- Two pinned inventories changed as deliberate edits: "only G1 enters", and
  the lab's seven tables.

**Gate:** lab suite **187 passed** (G1 package 37 of them), stable over
repeated runs.

### Migration `0092_rafiq_g1_run`

Verified four ways in a scratch Postgres 16:

1. An empty database upgrades through all 92 revisions.
2. A 0091 database holding the restored A2–E2 archive upgrades cleanly:
   6 strategies, 899 positions and 11 day rows are all backfilled to
   `F2-and-earlier`, and the defaults describe them exactly.
3. `downgrade 0091_real_wallet_ticket` and a second upgrade both run with the
   data intact. The downgrade is by explicit revision, never `-1`.
4. Autogenerate drift for `rafiq_*` tables at head is **zero**. The ten
   `remove_table` entries the comparison reports are the graduation lab's
   `grad_*` tables, which live outside the platform metadata on `main`; they
   predate this work.

### Platform suites, before and after

These ran against `main` at `7045b2f` and against this branch, with the same
venv and database:

| suite | passed | failed | same failure set on both? |
|---|---|---|---|
| `tests/unit` | 4,108 | 8 | yes |
| `tests/integration` | 888 | 32 | yes |

None of these failures come from this work.

## Phase 2 — learning, wired

### What the learner hears, and when

- **Once per closed G1 trade, on every exit path, oldest first, and only
  after the hour that follows the exit has closed.** `RafiqLabService.learn`
  selects closed G1 rows with `learning_recorded_at IS NULL` and
  `closed_at <= now − 1h`, in batches of 200.
- For each trade it reads the prints in `(closed_at, closed_at + 1h]` and
  writes `forward_peak_multiple` and `forward_went_to_zero` onto the row.
  Only then does it call `Learning.on_trade_closed(...)` and stamp
  `learning_recorded_at`.
- **`later_peak_multiple`** is `forward_peak_multiple`: the best **tradeable**
  print in the hour over `entry_price`, which is the same scale G1's +30%
  scale-out is measured on. When nothing tradeable printed, it is 1.0, which
  is `learning.py`'s own "never recovered" convention.
  - A drained pool's leftover price is not a peak; that is the print Phase 0
    stopped selling into.
- **`went_to_zero`** is true when any of these holds:
  - the exit itself found no pool (`exit_price = 0`);
  - the pool reads gone at the end of the hour (the same `pool_reading` rule
    an exit uses: an `inactive` reading or a `delisted_at` stamp after the
    last tradeable print, or nothing tradeable at all);
  - the last tradeable price is at or below 10% of entry.
- **`reached_take_profit`** is `scaled_out`. **Decision:** G1's take-profit
  rung is the +30% scale-out, which is also the "+30% runner" that
  `RegimeMonitor` describes.

### Decision: how the hour after exit is sampled

The pool is sampled by reading the platform's own `token_market_snapshots`,
which already prices every discovered token, rather than by polling
DexScreener from the lab.

- **Why:**
  - The lab's rule is read-only on the shared feed with no external endpoint
    (`outcomes.py` says why).
  - DexScreener and GeckoTerminal punish bursts.
  - A lab-side poller would be a second, rate-limited copy of the enrichment
    worker.
- **The cost, stated plainly:** Rafiq-lab positions are **not** in the
  platform's priority re-pricing lane (`services/market/priority.py` covers
  paper and V6 Lab holdings only). So a G1 token is priced:
  - every **30s** while it is under 30 minutes old;
  - every **5 min** after that.

  The post-exit hour is therefore a lower bound on the real peak: a spike
  between two 5-minute prints is missed.
  - **The fix is outside this brief.** Add open and recently closed
    `rafiq_lab_positions` to `resolve_membership` in `priority.py`, as
    HQ INC-056 did for the V6 Lab.

### Decision: where the job runs

- **Scheduled path:** the pass runs inside the existing Celery beat task
  `rafiq_lab_tick`, every minute, **before** entries. An adjustment is
  therefore in force for the very next decision.
- **Why not its own beat entry:** that would have to live in
  `app/workers/celery_app.py`, outside this package, and it could run after
  the entries it is meant to inform.
- **Manual path:** `app.labs.rafiq.scheduler.rafiq_g1_learning_tick`, a
  Celery task without a beat entry, runs the same pass from a worker shell.
  It is inert while the flag is off.

### Parameters before every entry

- `Learning.current_parameters()` is read **immediately before each entry
  decision**, per candidate, just before sizing.
- `abandon_gain_threshold` is frozen onto the position as `abandon_gain` and
  handed to `strategy_G1.evaluate(..., abandon_gain=...)` on every later
  tick.
- `size_multiplier` scales `position_size(current equity)` and is frozen onto
  the position.
- **Decision:** the threshold is frozen at entry rather than read live. A
  position is judged by the rule it was opened under, the same
  anti-hindsight rule as the rest of its geometry. A learned change applies
  to the entries after it.

### Persistence

- **`rafiq_lab_run_state.learning`** (JSONB, keyed by `lab_run_id`) holds the
  learner's evidence as `learning.py` keeps it:
  - the calibrator's threshold and its two buckets;
  - the regime window and its baseline;
  - the last size multiplier handed out.

  It is saved after each learning pass and after entries, because the regime
  fixes its baseline when first asked.
- **Every calibrator `Adjustment`** becomes a `rafiq_lab_adjustments` row:
  `parameter='abandon_gain_threshold'`, old, new, `sample_size`, `z_score`,
  reason, plus a log line. On load, those rows are handed back to the
  calibrator, so `adjustments_made` survives a restart.
- **Decision:** `RegimeMonitor` produces no `Adjustment` object, but its
  multiplier is a parameter the run moves. Each change of the handed-out
  multiplier is therefore also an adjustments row
  (`parameter='size_multiplier'`, with the regime note as its reason).
- **Serialization** reads `learning.py`'s dataclass fields directly. The
  module was not modified; it has no serializer of its own.
- **The status route** shows G1's `current_parameters()`. It reads them
  without creating the run's state row, because the request session commits
  on return and the router is read-only; a test holds that.

### Tests

**`tests/test_g1_learning.py`:**

- **The gate.** Forty closed trades (20 abandoned tokens that later ran,
  20 held tokens that lived) and one fresh admission, then a single tick.
  - It learns all 40, and `learning.py` loosens 0.08 → 0.09 once
    (n = 40, z ≥ 1.96, "cutting winners").
  - The adjustment is stored.
  - **The entry made in the same tick carries `abandon_gain = 0.09`.**
  - The evidence is cleared.
  - A restarted service reads 0.09 and one adjustment.
- A trade is fed once, and only after its hour.
- Every exit path reaches the right bucket; a scale-out counts as reaching
  take-profit.
- A halved regime halves the next bet ($5.00 on $1,000), and the change is
  audited.
- A pure table test covers `exit_outcome`.
- The manual task is registered and inert while the flag is off.

**`tests/test_api_runs.py`** gains `learning` on the status route and the
"GET writes nothing" check.

**`g1/test_learning.py`** passes in place (15 tests), as does
`g1/test_strategy_G1.py` (22).

**Gate:** lab suite **194 passed**, G1 package 37 passed, and the platform's
`tests/unit/test_rafiq_analyst.py` 16 passed.

### Migration `0093_rafiq_g1_learning`

Nullable columns only. It is verified four ways:

- upgrade from empty;
- upgrade over the archive;
- downgrade to `0092_rafiq_g1_run` and back;
- zero `rafiq_*` autogenerate drift.

## Phase 3 — top-10 concentration and LP lock at every decision

### What already existed, and was reused rather than duplicated

F2's build (migrations 0080/0081) already reads both features point-in-time
at every decision. It never blocks an entry, and it records every candidate,
entered **and** rejected, in `rafiq_lab_candidates`, together with forward
returns.

**Decision:** G1 inherits all of that unchanged. Adding a second
`top10_holder_pct` column next to `entry_top10_holder_pct`, or a second
rejection table next to `rafiq_lab_candidates`, would store every value
twice, and the copies could disagree. What was genuinely missing is the LP
answer as a boolean, plus a relation named for the rejected set.

### New columns (0094) and the relation the brief names

- **`rafiq_lab_positions.entry_lp_locked`** and
  **`rafiq_lab_candidates.lp_locked`**: `true` / `false` / `null`.
  - The name is `entry_`-prefixed on the trade row, like its neighbours
    `entry_top10_holder_pct` and `entry_lp_status`.
  - Both are derived by `feed.EntryFeatures.lp_locked` from the same reading
    that fills `lp_status` and `lp_reason_codes`, so they cannot disagree.
- **Top-10 holder concentration:** `rafiq_lab_positions.entry_top10_holder_pct`
  and `rafiq_lab_candidates.top10_holder_pct`, both existing since 0080/0081.
  They are a percent from 0 to 100, and each has a `*_captured_at` beside it.
- **`rafiq_lab_rejected_candidates`**, a **view** over `rafiq_lab_candidates`
  (`outcome = 'rejected'`). Each row carries:
  - `lab_run_id` and `strategy_code`;
  - `reject_reason`;
  - the market the decision saw;
  - `top10_holder_pct`, `lp_locked` and `lp_status`;
  - `forward_max_return_1h` (= `max_return_1h`), `forward_final_return_1h`
    and `forward_dead_1h`.

  **Decision:** it is a view, not a table, so a rejection is written once. It
  includes every refusal reason, not only the liquidity/cap/impact gate,
  because "never looked at it" and "looked and the pool was thin" are both
  decisions. Filter on `reject_reason` for the gate alone.
- **Forward 1h return.** It is filled by `outcomes.record`, which runs inside
  the Celery `rafiq_lab_tick` every tenth minute and can also be forced with
  `rafiq_outcomes_tick`. It reads snapshots in `(decided_at, decided_at + 1h]`.
  - **Changed here:** the maximum now counts only tradeable prints. A drained
    pool keeps printing its last price, and that print was being reported as
    a run: the same fiction Phase 0 removed from exits. This applies to rows
    filled after deploy. `final_return_*` and `dead_*` are unchanged.

### Sources and reliability

**`top10_holder_pct`**

- **Where it comes from.** `holder_snapshots.top10_pct`, the newest snapshot
  at or before the decision. The platform's research collector writes it
  (`app/workers/research_tasks.py`, beat `holder-snapshots-collect`):
  - using `getTokenLargestAccounts` plus `getTokenSupply`;
  - on the keyed research RPC: Chainstack, then Helius, never the public
    node, which refuses this method;
  - every 10 minutes, 10 tokens a pass, nursery tokens first and then Radar
    admissions from the last 24h;
  - once per token, never refreshed.

  It is gated by `FEATURE_RESEARCH_COLLECTORS_ENABLED` (code default off;
  prod env turns it on).
- **Why not a live RPC call at entry.** It is free but not live: calling
  `getTokenLargestAccounts` inside the tick would put a rate-limited call
  (429s measured even on Helius) in front of every decision. The brief
  allows "whatever free source the repo already uses", and this is it.
- **Reliability.**
  - On prod, 99.2% of 489 F2 decisions had it (24h to 2026-09-12 13:17Z;
    session memory, not re-measured here).
  - In the restored archive, 16 of 16 F2 decisions had it, read 35–46
    minutes before the decision (at admission or nursery entry).
- **Caveat: it probably includes the pool's own vault.** The collector's
  pool exclusion compares token-account addresses with DexScreener's pair
  address, which are different accounts, so the pool vault is almost never
  excluded. Read it as raw concentration including AMM vaults.
  - The snapshot keeps the raw top 20 in `accounts`, so this can be
    re-audited later by resolving each account's owner.
  - The fix belongs in the collector, outside this lab.
- **When it is null:** `entry_features_error` contains `no_holder_snapshot`.
  The collector had not reached the token by the decision, or it is off.

**`lp_locked`**

- **Where it comes from.** The platform's `LIQUIDITY_SECURITY` check
  (`app/security/liquidity_verifier.py`) in `token_security_evaluations`, the
  newest evaluation at or before the decision.
  - The beat `security-lab-coverage` evaluates Radar admissions within 20
    minutes of detection that have at least $100k liquidity, every minute.
    G1's $200k floor sits inside that coverage.
  - The check reads the chain: the pump.fun curve, and the derived PumpSwap
    migration pool's LP mint.
- **Mapping** (`EntryFeatures.lp_locked`):

  | check result | `lp_locked` | meaning |
  |---|---|---|
  | PASS, LP burned | `true` | the pump.fun migration pool's LP supply is zero |
  | PASS, on the bonding curve | `true` | no LP exists and the curve holds the reserves |
  | UNKNOWN + `LP_OUTSTANDING` | `false` | a redeemable claim exists; its holder is not checked |
  | FAIL | `false` | defensive only; this evaluator never emits it |
  | UNKNOWN (any other code) | `null` | including `TRADED_POOL_UNVERIFIED`, `POOL_NOT_PROTOCOL_MIGRATED`, `LIQUIDITY_SECURITY_UNVERIFIED` |
  | NOT_APPLICABLE `POOL_CUSTODY_OUT_OF_SCOPE` | `null` | Raydium, Meteora or Orca, which the evaluator cannot read |
  | no evaluation | `null` | nothing on file |

  **Decision:** both PASS mechanisms map to `true`, because in both cases
  nobody can withdraw the reserves. They differ only in whether an LP token
  ever existed. The PASS mechanism is not stored on the row, but it is
  recoverable by joining `token_security_evaluations` on mint and
  `lp_checked_at`.
- **Reliability.**
  - On prod, 73.4% of those 489 F2 decisions had an LP reading. The gap is
    coverage, not freshness: 129 of 130 misses were never evaluated.
  - In the archive, 10 of 16.
  - The check only understands pump.fun custody, so **most non-pump.fun
    pools will always be `null`**.
  - An earlier finding in this project (**memory, not re-run**) is that on
    traded mints the verdict did not separate total losses (p = 0.75).
    Treat `lp_locked` as a feature to test, not a known predictor.
- **When it is null:** `entry_features_error` contains
  `no_security_evaluation` (no row) or `no_lp_check` (a row without this
  check). Otherwise `lp_status` / `lp_reason_codes` show which undetermined
  result it was.

### Gate

**Test: `tests/test_g1_features.py`.** One G1 tick with two admissions:

- One enters. Its trade row and candidate row carry `top10 = 34.5` and
  `lp_status = PASS`, so `lp_locked = true`.
- One is refused for `liquidity_too_low`. It carries `top10 = 61.2` and
  UNKNOWN / `POOL_NOT_PROTOCOL_MIGRATED`, so `lp_locked = null`.
- A later reading (99% top-10, and a FAIL) is **not** read into either.
- After the outcomes pass, the refused candidate has
  `max_return_1h = 0.60`.

It also covers a silent store (the entry still happens, the columns are
null, and the error names both stores) and a seven-case table for the
mapping.

**In a database migrated by alembic to 0094**, with the real tick committed
(a scratch Postgres, not dev or prod):

```
== the live entry (trade row) ==
 symbol   | lab_run_id    | status | exit_reason  | cost_basis | entry_top10_holder_pct | entry_lp_status | entry_lp_locked
 DEMOGOOD | G1-2026-09-17 | closed | abandon_flat |    10.0000 |                34.5000 | PASS            | t

== the rejected candidate (rafiq_lab_rejected_candidates) ==
 strategy_code | lab_run_id    | symbol   | reject_reason     | liquidity_usd | top10_holder_pct | lp_status | lp_locked | forward_max_return_1h | forward_dead_1h
 G1            | G1-2026-09-17 | DEMOTHIN | liquidity_too_low |   150000.0000 |          61.2000 | UNKNOWN   | f         |              0.600000 | f
```

(DEMOTHIN's verdict in that run was UNKNOWN + `LP_OUTSTANDING`, hence
`false`.)

**On prod, and why not measured here.** Neither a live G1 entry nor a live
rejection exists yet, because G1 is not deployed. Once deployed, the same
two queries show them. Expected null rates are the reliability figures
above.

The view was also checked against the restored archive: F2's 13 real
rejections all carry `top10_holder_pct`.

**Suite:** lab suite 203 passed, G1 package 37 passed.

## Reference: every column and table this work added

| table | column | phase | meaning |
|---|---|---|---|
| `rafiq_lab_strategies` | `lab_run_id` | 1 | run this config row belongs to; unique with `code` |
| `rafiq_lab_positions` | `lab_run_id` | 1 | run of the trade |
| | `last_mark_liquidity_usd` | 1 | depth of the last tradeable reading, 0 once the pool reads gone |
| | `scaled_out`, `scaled_out_at`, `scale_out_price` | 1 | G1's 75% sale at +30% |
| | `fraction_open` | 1 | share still held; on a closed row, the share its final exit sold |
| | `realised_usd` | 1 | proceeds of partial sales (included in `exit_proceeds_usd` once closed) |
| | `abandon_gain`, `size_multiplier` | 1 | learning parameters frozen at entry |
| | `forward_peak_multiple`, `forward_went_to_zero` | 2 | the hour after exit |
| | `learning_recorded_at` | 2 | fed to `Learning.on_trade_closed` (once) |
| | `entry_lp_locked` | 3 | LP lock at entry |
| `rafiq_lab_daily_state` | `lab_run_id` | 1 | run of the day row |
| `rafiq_lab_candidates` | `lp_locked` | 3 | LP lock at the decision |
| `rafiq_lab_run_state` (new) | `ratchet_high_water`, `ratchet_floor`, `learning` | 1, 2 | a run's memory |
| `rafiq_lab_adjustments` (new) | `parameter`, `old_value`, `new_value`, `sample_size`, `z_score`, `reason`, `at` | 1 | every floor move, abandon-threshold change and size-multiplier change |
| `rafiq_lab_rejected_candidates` (view) | | 3 | refused candidates with both features and forward returns |

Migrations: `0092_rafiq_g1_run`, `0093_rafiq_g1_learning` and
`0094_rafiq_g1_features`, chained after `main`'s `0091_real_wallet_ticket`.
All are additive except one unique key, which moves from `code` to
`(lab_run_id, code)`.

## Every decision made without asking

1. **Built on `rafiq-g1` off `origin/main`, not on `karthik-hq`.**
   `karthik-hq` has no A2–F2. Migrations are numbered after `main`'s head.
   Nothing was pushed.
2. **Exits.**
   - An exit is valued only against a tradeable reading.
   - A pool is dead on an `inactive` reading or a delisting stamp after its
     last tradeable print, with the platform Lab's 120-second confirmation.
     Staleness alone is not death, because of the 30-minute re-price
     cadence.
3. **Friction** (`execution_cost_usd`) is measured from the fill, so it is
   fee plus impact only.
4. **Open positions are valued at what their pool would pay** (mark-to-pool)
   for equity, the breaker, the ratchet and the API. The last price times
   quantity is no longer used.
5. **An off-band (glitch) print updates nothing**, not even a trail's peak.
6. **Three stale inventory tests** that `main` left red on purpose were
   updated to the real inventory, because this brief asks for a green suite.
7. **Run ids.**
   - `F2-and-earlier` for everything before, `G1-2026-09-17` for G1. The
     date is the config's `generated` date.
   - Config rows are unique per `(run, code)`.
   - A2–F2 stay in the registry with `enters=False`, for display and digest
     checks.
8. **A2–F2's open positions are drained** on their own rules, never
   reopened and never force-closed.
9. **`scale_out` is a partial sale, not an `exit_reason`.** A closed row's
   `exit_proceeds_usd` is the whole position's proceeds, and `fraction_open`
   keeps the slice the final exit sold.
10. **The scale-out fill carries the lab's 1.15× drift cap**, like every
    level exit.
11. **G1's gate** is `strategy_G1.admits` (a missing market cap does not
    refuse), plus F2's 1.5% impact ceiling, a score of at least 70, and the
    lab's freshness guards.
12. **The daily breaker is the lab's existing one** (5% mark-to-market
    including open positions, plus an 8% realised line), re-evaluated every
    tick and not latched, as it always ran for E2 and F2.
13. **The ratchet's state is persisted per run.** Every floor move is an
    adjustments row.
14. **G1's digest hashes the canonical JSON's rules, not its prose.**
15. **The learning `at` is the tick time.** `later_peak_multiple` is the
    best tradeable print in the hour after exit over the entry price, and
    1.0 when nothing tradeable printed. `went_to_zero` uses the exit's
    dead-pool rule or a price at or below 10% of entry.
    `reached_take_profit` is `scaled_out`.
16. **The post-exit hour is read from the platform's snapshots**, not polled
    from DexScreener.
17. **The learning pass rides the minute tick, before entries.** A manual
    Celery task exists; no beat entry was added, because that lives outside
    the lab.
18. **The abandon threshold and size multiplier are frozen per position** at
    entry.
19. **Size-multiplier changes are audited** alongside calibrator
    adjustments.
20. **Top-10 concentration reuses the existing entry columns and
    `holder_snapshots`.** LP lock is a derived boolean, with both PASS
    mechanisms counted as locked. The rejected set is a view; it covers
    every refusal reason. The forward maximum counts tradeable prints only.
21. **The G1 test count is 37, not 55**: the delivered `test_learning.py`
    has 15 tests. A lab-local `g1/ruff.toml` accepts the delivered files'
    lint rather than editing them.
22. **New files follow the lab's hand formatting.** The lab and the
    migrations folder are not `ruff format`-clean on `main` (43 of 58 and
    46 of 95 files), so I did not reformat.

## Querying the G1 run and the archived runs

```sql
-- Every book, per run.
SELECT lab_run_id, code, lane, starting_equity, activated_at
FROM rafiq_lab_strategies ORDER BY lab_run_id, code;

-- One run's closed-trade summary per book. Swap the id for
-- 'F2-and-earlier' to read A2-F2.
SELECT s.code,
       count(*) FILTER (WHERE p.status = 'closed')                          AS closed,
       count(*) FILTER (WHERE p.status = 'open')                            AS open,
       round(sum(p.exit_proceeds_usd - p.cost_basis)
             FILTER (WHERE p.status = 'closed'), 2)                         AS realised_pnl,
       round(avg(p.exit_proceeds_usd - p.cost_basis)
             FILTER (WHERE p.status = 'closed'), 4)                         AS mean_net_per_trade
FROM rafiq_lab_positions p
JOIN rafiq_lab_strategies s ON s.id = p.strategy_id
WHERE p.lab_run_id = 'G1-2026-09-17'
GROUP BY s.code;

-- G1's exits by reason.
SELECT exit_reason, scaled_out, count(*),
       round(avg(exit_proceeds_usd - cost_basis), 4) AS mean_net
FROM rafiq_lab_positions
WHERE lab_run_id = 'G1-2026-09-17' AND status = 'closed'
GROUP BY 1, 2 ORDER BY 3 DESC;

-- What G1 learned and every floor move.
SELECT at, parameter, old_value, new_value, sample_size, z_score, reason
FROM rafiq_lab_adjustments WHERE lab_run_id = 'G1-2026-09-17' ORDER BY at;

-- Refusals, with both features and what the token did next.
SELECT reject_reason, count(*), avg(top10_holder_pct) AS top10,
       count(*) FILTER (WHERE lp_locked) AS locked,
       avg(forward_max_return_1h) AS mean_max_1h
FROM rafiq_lab_rejected_candidates
WHERE lab_run_id = 'G1-2026-09-17'
GROUP BY 1 ORDER BY 2 DESC;
```

The API reads the same split: `GET /api/v1/labs/rafiq/status` (the current
run) and `GET /api/v1/labs/rafiq/status?run=F2-and-earlier`, and likewise
for `/positions`, `/trades`, `/breaker` and `/analysis`.

## Mean net per trade, runner leg excluded

The runner leg is the 25% a scaled-out position kept after its +30% sale.

- For a position that scaled out, the non-runner part is the scale-out:
  `realised_usd` against the three quarters of cost it sold.
- A position that never scaled out has no runner leg, so it counts whole.

```sql
SELECT count(*)                                   AS trades,
       count(*) FILTER (WHERE scaled_out)         AS scaled_out,
       round(avg(CASE WHEN scaled_out
                      THEN realised_usd - cost_basis * (1 - fraction_open)
                      ELSE exit_proceeds_usd - cost_basis END), 4) AS mean_net_ex_runner,
       round(avg(exit_proceeds_usd - cost_basis), 4)               AS mean_net_all,
       round(sum((exit_proceeds_usd - realised_usd) - cost_basis * fraction_open)
             FILTER (WHERE scaled_out), 4)                          AS runner_leg_net_total
FROM rafiq_lab_positions
WHERE lab_run_id = 'G1-2026-09-17' AND status = 'closed';
```

Run against the demo database above, it returned 23 trades, 8 of them
scaled out, `mean_net_ex_runner = −0.9613`, `mean_net_all = −0.9670` and
`runner_leg_net_total = −0.1308`.

This works because a closed G1 row keeps `fraction_open` at the slice its
final exit sold (0.25 after a scale-out). With the Phase 0 fix in, the full
mean is also trustworthy; the ex-runner figure is the one G1's own config
asked for while the valuation was in doubt.

## Deploying this: not done, and not mine to do

Nothing was pushed or deployed. To ship it:

1. **Merge.** Open a PR from `rafiq-g1` to `main`. Renumber `0092`–`0094` if
   `main` has moved past `0091` by then, and check `alembic heads` shows one
   head.
2. **Migrate.** `deploy.sh` runs `alembic upgrade head`. That backfills
   A2–F2 to `F2-and-earlier`; no data changes.
3. **Flag.** `RAFIQ_LAB_ENABLED` is unchanged and already wired. On the first
   tick after deploy:
   - the runner creates G1's $1,000 row and starts trading;
   - it drains whatever A2–F2 hold;
   - A2–F2 stop opening positions.
4. **Collectors G1's features depend on** (both are platform settings, not
   this lab's):
   - `FEATURE_RESEARCH_COLLECTORS_ENABLED` for top-10;
   - `TOKEN_SECURITY_EVALUATION_ENABLED` plus the `security-lab-coverage`
     beat for LP.
5. **Check after deploy:**
   - `SELECT lab_run_id, code FROM rafiq_lab_strategies` shows a G1 row;
   - `GET /labs/rafiq/status` shows G1 alone, with `learning` and
     `ratchet_floor`.

## Known gaps and suggested follow-ups (outside this brief's scope)

- **Re-pricing lane.** Rafiq positions are not in the platform's priority
  re-pricing lane (`app/services/market/priority.py` → `resolve_membership`).
  G1's marks and its post-exit hour are sampled every 30s only while a token
  is under 30 minutes old, then every 5 minutes. Adding open and recently
  closed `rafiq_lab_positions` there is the single biggest data-quality
  improvement available to G1.
- **Top-10 pool exclusion.** The holder collector compares token-account
  addresses with a pair address, so its pool exclusion almost never fires.
- **Frontend.** `frontend/src/labs/rafiq` renders G1 without changes, but
  shows none of the new fields (`learning`, `ratchet_floor`, `scaled_out`,
  `fraction_open`, `?run=`).
- **F2's 9.3% friction** was not re-measured on prod: the read-only query was
  refused by this session's permission policy. This query splits exit drag
  by cause:

  ```sql
  SELECT round(100*sum(quantity*(exit_observed_price-exit_price))/sum(cost_basis),2) AS cap_or_leftover_pct,
         round(100*sum(quantity*exit_price-exit_proceeds_usd)/sum(cost_basis),2)     AS fee_and_impact_pct
  FROM rafiq_lab_positions p JOIN rafiq_lab_strategies s ON s.id=p.strategy_id
  WHERE s.code='F2' AND p.status='closed';
  ```
- **Platform test suites.** Both were run before and after on the same
  database (unit 4,108 passed / 8 failed; integration 888 passed / 32
  failed), with **identical failure sets on `main` at 7045b2f**. None comes
  from this work.
