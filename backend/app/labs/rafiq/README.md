# Rafiq Lab

Five strategies supplied by a collaborator, run beside the existing paper
engine on the same token feed, each on its own **$1,000** book.

**Research simulation. Not the Paper Wallet, not real money, no chain.** A
position here is a row recording what a published rule would have done.

Nothing in this lab has a return target, and nothing here should acquire one.
Strategy D bounds how much a bad day can take away; nothing bounds the other
direction, and no number in this module, its API, its UI or its tests should
imply otherwise.

---

## How to enable it

Off by default. One environment variable:

```bash
RAFIQ_LAB_ENABLED=true
```

Then apply the migration and drive a tick:

```bash
cd backend && alembic upgrade head
```

```bash
cd backend && python -m app.labs.rafiq tick
```

`tick` is idempotent and safe to run late — it settles what is open, asks the
breaker, then considers what is fresh.

In deployment you do not need to run it by hand: the Celery beat calls
`app.labs.rafiq.scheduler.rafiq_lab_tick` **every minute**. Registration does
not start anything — the flag gates the task before it opens a session. Setting
`RAFIQ_LAB_ENABLED` means restarting the worker, like every other flag here.
The command line above is for a one-off run or a local check.

With the flag off, the runner returns immediately, every route answers
`running: false`, and the UI says the lab is not running rather than showing
an empty book. Those are different facts.

### The beat

Registered in `app/workers/celery_app.py` as `rafiq-lab-tick`, every minute,
alongside `lab-tick` and the Arena. Two additive lines: the module in
`imports`, the entry in `beat_schedule`.

Every minute rather than every five because Strategy B's exits are measured in
a two-hour box; a coarser beat would blur the one distinction B exists to draw.

A failure is contained — the task logs and returns rather than raising into the
beat, exactly as the Arena, the V6 Lab and the research collectors do. The lab
is instrumentation, and instrumentation must never disturb what it observes.

---

## How to compare it against the existing wallet

The **Rafiq Lab** page (`/rafiq-lab`) puts each strategy's book beside the
Karthik paper wallet's own numbers, from `$1,000` in both cases.

The comparison happens **in the browser**, and that is a constraint rather
than a convenience: the backend lab is forbidden from reading the existing
wallet's positions or trades, so the page fetches `/labs/rafiq/status` and
`/karthik` as two independent reads of two independent ledgers.

Read the columns as two records, never as a difference. **The two books do not
cover the same period** — each starts when it was activated, and an admission
that predates a book's activation is never entered by it.

Read-only API:

| Route | What it answers |
|---|---|
| `GET /api/v1/labs/rafiq/status` | five books: equity, cash, realised, the frozen rules, the equity curve |
| `GET /api/v1/labs/rafiq/positions` | what is open, with age and current mark-to-market value |
| `GET /api/v1/labs/rafiq/trades` | every closed trade, with the evidence for its exit |
| `GET /api/v1/labs/rafiq/breaker` | today's daily state per strategy |

There is no POST, PUT, PATCH or DELETE. No manual entry, no manual exit, no
activation endpoint.

### The sensitivity sweep

`strategy_e_sensitivity.py` is a **command-line script only** and is never
part of the live loop:

```bash
cd backend && python -m app.labs.rafiq.sensitivity
```

Its calibration assertion is intact: the "no stop" row must reproduce the
Karthik wallet's own realised result (−$774.86 over 311 trades, −24.92%/trade)
to within 0.5 points, or the script refuses to print the sweep. It currently
matches to 0.00 points. Read the banner it prints before acting on any row —
it is a sensitivity analysis, not a backtest.

---

## The gaps

Strategy E's entry gate asks for four independent evidence streams — on-chain,
DEX, social, safety — of which **at least two must confirm, safety mandatory**.
These are what MEMESCOPE can and cannot supply. Every one of them is *absent*
where the platform cannot answer, and **absent never counts as confirming**.

| What E asks for | What MEMESCOPE has | Status |
|---|---|---|
| **social stream** | *nothing* — no Twitter, Telegram or social model exists anywhere in the repo | **Permanently absent.** E can reach at most 3 of its 4 streams. |
| `buyers` / `sellers` (unique wallets) | `wallet_flow_snapshots.w1h_unique_buyers` / `_sellers` | **Frequently absent.** Keyed by *pool*, not mint, and behind `FEATURE_WALLET_FLOW_ENABLED`, which ships **off**. |
| `buys` / `sells` (trade counts) | `wallet_flow_snapshots.w1h_buy_count` / `_sell_count` | Same table, same caveat. `token_market_snapshots` has only 24-hour cumulative counters; a window delta is derivable, a since-entry count is not. |
| safety verdict | `token_security_evaluations.overall_status` | Present, but often `UNKNOWN` for a young mint. **`UNKNOWN` maps to absent, never to a pass.** |
| `volume_m5` | `token_market_snapshots.volume_5m` | Present. |
| `market_cap`, `liquidity` | `token_market_snapshots` | Present. |
| entry threshold (70 / 68) | `radar_tokens.current_opportunity_score`, 0–100 | Present. |

**The practical consequence, measured rather than predicted:** on a market
with no wallet-flow row and no security evaluation, only the DEX stream can
confirm — one stream, and not the mandatory one — so **E enters nothing**. A
full-cycle test asserts exactly that, with A, B, C and D all entering the same
token. E declining a market this platform can only half-observe is the design
working, not a bug; turning `FEATURE_WALLET_FLOW_ENABLED` on and keeping
security evaluations fresh is what gives E something to trade.

### Two smaller gaps, recorded rather than smoothed over

* **Strategy C's docstring cites EarlySignal's cost model** (~1.6% round trip
  at $10k liquidity, ~0.8% at $100k). This port does not reproduce those
  figures — `adapters/costs.py` uses MEMESCOPE's own calibration, measured
  against 320 live Jupiter quotes, which is harsher (a $50 order round-trips
  at ~22% into a $10k pool, ~3.0% into a $100k one). What both models agree
  on, and the only thing C's logic depends on, is the direction: a thinner
  pool costs more. That direction has a test; the EarlySignal numbers do not,
  because they are not true here.
* **C and D have no exit shape of their own.** C is a sizing and stop-distance
  policy; D is a portfolio halt. To run either as a strategy they need a
  target, trail, hold and threshold, and those are taken from **A**, not
  invented — A is the profile C's `base_stop_pct = 12` was written against.
  So the C column answers "what does liquidity-derived risk do to A?" and the
  D column answers "what does the daily breaker do to A?"

---

## What is guaranteed, and how

| Claim | Held by |
|---|---|
| Zero changes to the existing implementation | Four additive registrations: one router include, one nav entry, one model import, one beat entry. `git diff --stat` shows insertions only — no deletions, no modified lines. |
| Never reads or writes the existing wallet | An AST test asserting no module here imports `app.paper*`, `app.karthik*`, `app.real_wallet*`, `app.lab`, `app.arena` or `app.strategy_lab` — plus a full-cycle test that hashes `karthik_*` before and after a live tick and requires the hashes to match. |
| Read-only on the shared feed | `feed.py` is the only module importing a shared model, and a test asserts it contains no insert, update, delete, add, merge, flush or commit. |
| Own ledger | `rafiq_lab_strategies`, `rafiq_lab_positions`, `rafiq_lab_daily_state`. Nothing else writes them; a schema diff of a database migrated 0055 → 0056 shows 46 columns added across exactly those three tables and **zero** removals or changes. |
| Rafiq's logic preserved | The five files are byte-identical to what was supplied except their import lines and dead imports `ruff` refuses to compile. `git diff` against the originals is the receipt. |
| Nothing claimed without a test | 64 tests, including every docstring claim that survived the port, and the beat entry resolving to a real task. |
| The schema tool agrees with the schema | The models are on the platform's `Base` and imported in `app/models/__init__.py`, so `alembic check` reports **no** operation of any kind against `rafiq_lab_*`. A separate `DeclarativeBase` was tried first and reverted — see below. |

### The metadata reversal, and why

The lab's models were first given their own `DeclarativeBase` so that
`alembic check` could not see them at all. That made things worse, not better.
Autogenerate compares the platform's metadata against the database, so three
tables present in one and absent from the other came out as `drop_table`
operations: the next person to run `alembic revision --autogenerate` would
have been handed a migration that **deletes the lab's ledger**.

They are now on the platform's `Base`, imported once in
`app/models/__init__.py`, with `server_default` declared on the three columns
that have one in the migration. `alembic check` now reports nothing at all
about `rafiq_lab_*`.

For context: `alembic check` on this branch **already fails** at 0055, on ~25
pre-existing index, constraint and server-default drifts in `hq_*`, `lab_*`,
`password_reset_tokens`, `real_wallet_*` and `strategy_lab_*`. None of those
is a table drop, and the lab adds nothing to that list.

### Why `rafiq_lab_` and not `rafiq_`

`rafiq_wallets`, `rafiq_opportunities`, `rafiq_positions`, `rafiq_fills` and
`rafiq_events` are already taken by an unmerged `rafiq-wallet` branch — a
different experiment, verdict NO-GO, never deployed. `rafiq_lab_` is still the
requested prefix and is the version that survives if that branch is ever
merged.

---

## Tests

```bash
cd backend && pytest app/labs/rafiq/tests -q
```

64 of them. They live inside the package, so `pytest` with no arguments — which the repo
scopes to `testpaths = ["tests"]` — is unchanged by this module's existence.
The full-cycle tests need Postgres and skip cleanly without it.

## Layout

```
app/labs/rafiq/
├── adapters/          the `earlysignal.*` shims: costs, sizing, engine,
│                      profiles, evidence, manipulation, safety, stats
├── strategies/        Rafiq's five files, verbatim but for imports
├── tests/             62 tests
├── config.py          RAFIQ_LAB_ENABLED, read from env, default off
├── models.py          the three `rafiq_lab_*` tables, own metadata
├── feed.py            READ-ONLY view of the shared token feed
├── engine.py          the exit evaluator — pure, no I/O
├── registry.py        the five runners, as five values
├── service.py         one tick: settle, breaker, enter
├── api.py             four read-only routes
├── scheduler.py       a Celery task, deliberately unregistered
├── sensitivity.py     the CLI sweep
└── __main__.py        `python -m app.labs.rafiq tick`
```

Frontend lives in `frontend/src/labs/rafiq/`, reached by a two-line re-export
at `frontend/src/app/(dashboard)/rafiq-lab/page.tsx`.
