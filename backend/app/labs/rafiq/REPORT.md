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
