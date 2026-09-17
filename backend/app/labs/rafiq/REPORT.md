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
