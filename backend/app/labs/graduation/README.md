# Graduation Lab

Records pump.fun tokens approaching the top of the bonding curve, and their
trading either side of migration, so that a graduation strategy can be
backtested later against data that was captured live.

It is a **recorder, a feature engine and a replay harness**. No paper trader,
no tuned strategy, no frontend. Seven tables, three loops, two beat tasks.

**Everything it reads is free.** An earlier version of this lab bought
per-trade data from PumpPortal's `subscribeTokenTrade` at 0.01 SOL per 10,000
events — roughly 0.7 SOL a day. The chain reports the same curve state for the
price of an RPC call, so that stream is gone. What went with it is per-trade
detail; see [Known limitations](#known-limitations).

## Why it exists

The platform already has a bonding-curve collector that polls the chain over
RPC. Measured on 2026-09-09, it cannot see this state: of **218 curves observed
complete, 217 were never once observed incomplete**. The maximum incomplete
progress ever caught was 79.23%, and the 80–100% band — the band that matters —
was empty.

That is not a limit of RPC polling. It is a limit of *that* collector, which
piggybacks on the enrichment cycle and is dominated by brand-new tokens nobody
has bought. A dedicated poll of a small, bounded watch set on a fifteen-second
interval sees the approach; a whole-universe sweep on an enrichment cadence
does not.

---

## Where each number comes from

| source | what it gives | cost |
|---|---|---|
| PumpPortal `subscribeNewToken` | candidate mints | free |
| PumpPortal `subscribeMigration` | graduation timestamps | free |
| `getMultipleAccounts` on derived PDAs | reserves, progress, `complete` | one call per 100 tokens |
| DexScreener `/tokens/v1` | post-graduation price, volume, buy/sell counts | free, 300 rpm |
| GeckoTerminal minute OHLCV | backfill for a missed post-grad poll | free, 30 rpm |

Three loops run in one process and fail separately: a rate-limited market API
must not stop the curve poll, and a websocket reconnect must not pause either.

---

## The curve arithmetic

pump.fun mints 1,000,000,000 tokens and puts **793,100,000** of them on the
curve. The curve account is seeded with a virtual token reserve of
**1,073,000,000** — the 793,100,000 for sale plus a 279,900,000 offset that
makes the constant product quote a sane opening price before anyone has bought.

```
tokens_sold = 1_073_000_000 - virtual_token_reserves
progress    = tokens_sold / 793_100_000
```

The curve is **complete when the virtual reserve reaches 279,900,000**. In the
account these are raw base units (6 decimals), so the constants in `config` are
those figures times 10⁶.

### The 206,900,000 correction

An earlier statement of this lab's brief said the curve completes when
"~206.9M tokens remain of the 793.1M curve allocation". That is wrong, and it
is wrong in the direction that matters.

`206,900,000` is `1,000,000,000 − 793,100,000`: the supply **held back to seed
the AMM pool at migration**. Those tokens are never in the curve account, so
they can never be "remaining in the curve". Using them as the floor reads a
*full* curve as **91.57%**, which would make the 95% and 100% checkpoints
unreachable and understate every reading near the top by about eight points.
`tests/test_curve.py` asserts the 91.57% misreading directly, so the mistake
cannot come back quietly.

### Verified, not assumed

A live read of an untouched curve on 2026-09-11:

```
owner          6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P
length         151 bytes
discriminator  17b7f83760d8ac60      == the community decoder's signature
v_token        1,073,000,000,000,000
real_token       793,100,000,000,000
v_sol             30,000,000,006      (30 SOL, 9 decimals)
total          1,000,000,000,000,000
```

That response is saved verbatim as `tests/fixtures/curve_account.json` and the
tests decode it.

**On the account layout.** `app/services/curve/state.py` declares
`ACCOUNT_SIZE = 49` and the live account is 151 bytes. That is not a bug: the
check is a *minimum*, and the five reserves and the `complete` flag all live in
the 49-byte prefix. The 102 bytes past it are **not decoded** — the account has
grown since that module was written, and reading a field this lab has never
verified would be inventing data.

### Why the constants are environment variables

They are **not compiled into the pump.fun program**. They live in a mutable
on-chain global-config account (`4wTV1YmiEkRvAtNtsSGPtUrqRYQMe5SKy2uB4Jjaxnjf`)
and pump.fun can change them. Override with `LAB_GRADUATION_V_TOKENS_0`,
`LAB_GRADUATION_REAL_TOKENS_0`, `LAB_GRADUATION_V_SOL_0`.

`tests/test_curve.py` also asserts that this module's progress agrees with
`CurveState.progress` from the platform's own curve service, so a join between
`grad_curve_samples` and the platform's curve snapshots is guaranteed to be
comparing the same quantity.

### USDC-denominated curves

A USDC curve holds USDC in the reserve the SOL field normally carries. Progress
is a pure function of the **token** side, so the same expression is correct in
both denominations and there is no special case in the maths.

What does differ is the label, and a column called `sol_amount` holding USDC is
a silent unit error. So every quote column is named `..._quote` and
`grad_tokens.quote_currency` says which it is. **The denomination is detected
from the launch message**, not from the account: the bytes this lab decodes
carry no denomination flag, and the launch message's field names
(`vSolInBondingCurve` versus `vUsdcInBondingCurve`) are the only signal there
is.

---

## The PDA, and why the feed's own answer is not used

The curve account is the program-derived address of `["bonding-curve", mint]`
under `6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P`. Deriving it locally is what
makes the whole watch set one call per hundred tokens: there is no address
lookup to do first.

The launch feed also *reports* a `bondingCurveKey`, on 102 of 121 messages. It
is recorded and **never used**, because it is not reliable. Measured on 15
consecutive launches on 2026-09-11:

* 12 agreed with the derived PDA;
* **3 carried the same key — `BwWK17cbHxwWBKZkUYvzxLcNQ1YVyaFezduWbtm2de6s` —
  for three unrelated mints**, and that address is a zero-length account owned
  by the System Program, not a curve at all.

A lab that polled the reported key would read nothing for those tokens for ever
and never know why. `grad_tokens` stores both `bonding_curve_key` and the
derived `curve_address` so the disagreement stays findable.

---

## Schema

Six tables, all prefixed `grad_`. Created by
`20260911_0066_graduation_lab.py` and extended by
`20260911_0067_graduation_rpc_polling.py` (revision `0067_graduation_rpc`).
Neither touches a table outside this lab; `tests/test_isolation.py` parses both
and fails if one does.

### `grad_tokens` — one row per mint ever watched

Never deleted; this is what survives pruning. Carries identity (`mint`,
`symbol`, `name`, `creator`, `launch_pool`, `quote_currency`), addresses
(`bonding_curve_key` as reported, `curve_address` as derived and polled),
lifecycle (`first_seen_at`, `tracked_at`, `migrated_at`, `unsubscribed_at`,
`unsubscribe_reason`, `status`, `pruned_at`) and aggregates
(`max_progress_pct`, `last_progress_pct`, `last_progress_change_at`,
`first_sample_at`, `last_sample_at`, `sample_count`, `peak_market_cap_quote`).

`max_progress_pct` is the **highest ever seen**, not the last: progress falls
when somebody sells, and "did it reach 90" is the question this lab is for.

`last_progress_change_at` moves only when a **reserve actually moves**, which
is what silence is measured against — see [the watch set](#the-watch-set).

### `grad_curve_samples` — the reserve series

`ts`, `mint`, both token reserves and both quote reserves (in whole units),
`quote_currency`, `token_total_supply`, `progress_pct`, `complete`,
`market_cap_quote`.

**Written only when a reserve moved.** Storing every poll of every watched
token would be ~2.88 million rows a day, the great majority byte-identical to
the row before — two thirds of live curves have never had a single token
bought. An unchanged reserve says nothing the previous row and the poll cadence
do not already say. Set `LAB_GRADUATION_SAMPLE_EVERY_POLL=true` to store all of
them.

> **Reading this table:** a gap between two rows is **not** a gap in coverage.
> It means nothing happened. `grad_tokens.last_sample_at` says when the token
> was last actually looked at, and `sample_count` how many times.

### `grad_checkpoints` — one row per token per level

Written once per `(mint, level_pct)` at **70 / 80 / 90 / 95 / 100** and never
revised. Carries both reserves, `quote_currency`, `market_cap_quote`, and the
`progress_pct` *actually observed*, which is `>= level_pct`: a token can cross
three levels between two polls and owes three rows at once.

A level that was **observed** carries its reserves. A level only **inferred**
from a migration event carries null — a graduated curve zeroes every reserve,
so there is nothing truthful to put there, and a zero would read as a
measurement nobody made.

### `grad_migrations` — the graduation event

`mint`, `ts`, `pool`, `signature`, `progress_pct_before`,
`seen_complete_on_chain`, and `raw` (JSONB). The feed is **global**: it reports
graduations of tokens this lab never watched, and those are recorded too with a
null `progress_pct_before`.

`seen_complete_on_chain` says whether the chain's own `complete` flag beat the
websocket to it. The two signals are independent and either may arrive first.

### `grad_postgrad_samples` — the hour after

`ts`, `mint`, `source`, `pair_address`, `dex_id`, `price_usd`, `price_native`,
`liquidity_usd`, `fdv`, `volume_m5_usd`, `volume_h1_usd`, `volume_m1_usd`, and
`txns_{m5,h1}_{buys,sells}`.

`source` is `dexscreener` (a live poll) or `geckoterminal` (a backfilled
candle). **They are not the same measurement and must never be averaged
together without knowing which is which**: a candle carries a price and one
minute's volume, and leaves the rolling windows and the buy/sell counts null,
because it cannot know them.

### `grad_features` — one row per graduated token

Built by `features.py` from the five tables above. **Phase 3 reads this; nothing
in this lab does.** Wide rather than long: four checkpoint blocks of nine
columns, so an entry level is a column prefix rather than a join and a filter
like "velocity at 90 above x, for tokens that also cleared 80" is one ordinary
`WHERE`. There will never be a fifth block — 100 is graduation itself.

**Features, at each of 70/80/90/95** (`f70_*` … `f95_*`):

| column | meaning |
|---|---|
| `_at` | when the checkpoint was observed |
| `_minutes_since_launch` | from `grad_tokens.first_seen_at` |
| `_minutes_from_70` | from crossing 70%; 0 at the 70 block |
| `_velocity_5m`, `_velocity_15m` | progress **points per minute**, both ends forward-filled |
| `_changes_15m` | reserve changes in the preceding 15 minutes |
| `_stall_count` | quiet runs of ≥ 5 min between crossing 70% and here |
| `_market_cap_quote` | from the checkpoint row |
| `_retrace_flag` | progress fell ≥ 5 points from a running peak between here and graduation |

**Outcomes, relative to the pool open** — the first post-graduation price
sample, and the earliest price anything could actually have been bought at:
`open_at`, `open_price_usd`, `return_2m/5m/15m/30m/60m`, `max_return_60m`,
`max_drawdown_60m`, `minutes_to_peak`, `migration_lag_min`,
`postgrad_minutes_covered`, `sample_gap_flag`, `backfilled_samples`,
`outcome_ok`.

Returns are **fractions of the open**: `0.25` is +25%, `1.0` is a 2x.
`max_drawdown_60m` is peak-to-trough from a *running* peak, not versus the
open — a token that doubles and halves has drawn down 50%, and measuring
against the open would call it flat.

#### Three rules that decide what a null means

* **A checkpoint never reached nulls its whole block, and the token is still
  written.** "Reached 80 and died" is the row Phase 3 most needs; dropping it
  would condition the sample on success.
* **Outcomes null together when coverage is thin** — under
  `OUTCOME_MIN_COVERAGE_MIN` (55) of the 60 minutes. A return computed over a
  series with holes in it is a number with no error bar.
  `postgrad_minutes_covered` is written either way, so a null always says why.
* **A graduate this lab never watched still gets a row**: outcomes, and null
  features (`launch_at IS NULL` marks them). Those are a useful control, not a
  defect.

Everything time-based reads a **forward-filled** curve, because
`grad_curve_samples` is change-only. `progress_at(t)` is the progress of the
last sample at or before `t`. There is one honest extrapolation: before the
first sample but at or after the launch, progress reads **0** — a pump.fun
curve holds its full allocation the instant it is created, which is the
protocol and not a guess. Before the launch it reads null.

### `grad_trades` — empty, and kept on purpose

Per-trade detail came from the metered stream. A Phase 2 backfill may fill this
for **graduates only** — a few hundred tokens a day rather than the ~36,000
that launch — from transaction history. The table stays so that work needs no
migration.

---

## The watch set

A candidate enters from `subscribeNewToken`; that is the only door. A token at
or above `TRACK_PROGRESS_PCT` (70%) is **tracked**, and tracked tokens are
treated differently:

| rule | applies to | window |
|---|---|---|
| `silent` | below 70% | no reserve movement for `SILENT_MIN` (30 min) |
| `evicted` | below 70% | the set is full; lowest progress goes first |
| `post_migration` | migrated | `POST_MIGRATION_SECONDS` (60 min) |
| `stale` | **anything** | `STALE_HOURS` (24) since first seen |

A tracked token is never evicted for silence and never evicted for room. A
curve parked at 94% for three hours is not a mistake to clean up; it is the
observation. `stale` is the only backstop, so the set cannot silt up.

**Silence is measured on the reserves, not the clock.** A poll happens whether
or not anybody traded. Measuring from the last *poll* would make every dead
token look permanently alive and the set would fill with curves nobody has ever
bought.

`bonk` launches are refused outright: a bonk curve has no PDA under the
pump.fun program at all, so polling one would read a nonexistent account every
fifteen seconds for ever.

---

## RPC rate math

At the defaults — `MAX_WATCH_SET=500`, `POLL_INTERVAL_S=15`,
`getMultipleAccounts` capped at 100 addresses:

```
calls per poll     ceil(500 / 100)      =  5
polls per minute   60 / 15              =  4
calls per minute   5 x 4                = 20     (0.33 / second)
```

Against the public endpoint's published allowance of 100 requests per 10
seconds (600/minute), that is **about 3% of budget**. The token bucket
(`CallBudget`, continuous refill) is set to `RPC_CALLS_PER_MINUTE=100` — five
times what the poller needs and a sixth of what the node allows, so a bug
cannot turn into a ban.

Scaling is linear and easy to reason about: doubling the watch set doubles the
calls; halving the interval doubles them.

| watch set | interval | calls/min | % of public allowance |
|---|---|---|---|
| 500 | 15s | 20 | 3% |
| 1,000 | 15s | 40 | 7% |
| 500 | 5s | 60 | 10% |
| 2,000 | 5s | 240 | 40% |

**The public endpoint is a default, not a recommendation.** It is shared with
the whole world, rate-limited per IP, and this platform's own
`services/rpc/registry.py` refuses to let research collectors near it — written
after one quietly leaned on it and produced "sixty failure rows and one datum".
Point `SOLANA_RPC_URL` at a real endpoint before running near `MAX_WATCH_SET`.

**Market APIs.** Roughly 31 tokens graduate an hour (738 in 24h, measured), so
a 60-minute window holds ~31 open at once. Batched 30 mints to a call, that is
**2 DexScreener calls a minute** against an allowance of 300. GeckoTerminal is
only touched to backfill a gap, capped at 25/minute against a free tier of 30.
Both honour `Retry-After` as a *floor*, never a ceiling — GeckoTerminal answers
a 429 with `Retry-After: 0` and then refuses for about thirty-five seconds.

**Row volume** depends entirely on how many curves move, which is the one
number that has not been measured. The ceiling is every token moving every poll
(~2.88M rows/day); the floor is nothing moving (~500 rows/day, one per token on
first sight). Measure it on the first day and set `PRUNE_AFTER_HOURS`
accordingly.

---

## How to run

### 1. Migrate

```bash
cd backend && alembic upgrade head
```

### 2. Configure

```bash
LAB_GRADUATION_ENABLED=true
SOLANA_RPC_URL=https://your-endpoint    # optional; defaults to public mainnet
```

Optional: `LAB_GRADUATION_POLL_INTERVAL_S` (15), `LAB_GRADUATION_MAX_WATCH_SET`
(500), `LAB_GRADUATION_SILENT_MIN` (30), `LAB_GRADUATION_STALE_HOURS` (24),
`LAB_GRADUATION_TRACK_PCT` (70), `LAB_GRADUATION_RPC_CALLS_PER_MINUTE` (100),
`LAB_GRADUATION_SAMPLE_EVERY_POLL` (off), and the three curve constants.
No API key is needed for anything.

### 3. Run the recorder

A long-lived process holding a websocket and a poll loop, so **not** a Celery
task:

```bash
python -m app.labs.graduation record
```

SIGINT/SIGTERM flush the buffers and exit cleanly.

### 4. Build the features

```bash
python -m app.labs.graduation features
```

Processes graduates whose 60-minute outcome window has closed (plus 5 minutes
of slack), skipping any that already have a row. `--recompute` rewrites
existing rows — use it after a post-graduation backfill has filled gaps that
made outcomes null. It also runs on Celery beat every 10 minutes.

### 5. The summary Phase 3 is judged against

```bash
python -m app.labs.graduation summary
```

```
coverage
--------
  graduates                5
  with a usable outcome    4
  dropped, thin coverage   1
  had at least one gap     1
  never watched pre-grad   1
  reached 70/80/90/95      4/4/3/2
  mean minutes covered     54.0

metric               n      mean       p10       p25    median       p75  ...
return_5m            4    0.3875    0.1850    0.3875    0.5000    0.5000  ...
max_return_60m       4    1.2725    0.8630    1.2725    1.5000    1.5000  ...
```

It ships with its own denominator on purpose. A percentile table over the rows
that happened to have clean coverage, with no count of the rows that did not,
is the shape of every fake edge this platform has already found — so
`dropped, thin coverage` and `never watched pre-grad` are printed above the
distribution, not below it.

`features.SUMMARY_SQL` and `features.COVERAGE_SQL` are plain strings meant to
be pasted into `psql`. A query nobody can paste is a query nobody checks.

**Read `max_return_60m` carefully.** It is the best price in the window, which
nothing can systematically capture. It is the *ceiling* on any exit rule, not a
result — treating it as achievable is how a strategy gets built on a number
that was never available.

### 6. Replay a strategy

```bash
python -m app.labs.graduation backtest --csv /tmp/trades.csv
```

Runs every baseline over the recorded series and prints, in order: the
coverage line, the funnel, a per-ISO-week table, the walk-forward split, and
the gate verdict.

**Strategies are pluggable classes.** A `Strategy` names `decision_times` — the
moments it wants to be asked — and returns an `EntrySignal` from a `View`. Exit
rules are composable objects (`TimeBox`, `TrailingStop`, `HardStop`,
`TakeProfit`) combined into an `ExitPolicy`, where the **first rule to fire on
a tick wins** and the order is the caller's to state: a stop and a take-profit
can both be true on one 60-second bar, and which one filled is not knowable
from minute data.

Two baselines ship, and **neither is tuned**:

| | entry | exit |
|---|---|---|
| `B0_open_timebox_5m` | the pool open | +5 minutes |
| `B1_f90_then_open_5m` | the 90% checkpoint, on the curve | pool open +5 minutes |

They exist to be beaten. A harness that arrives with a winner already in it is
a harness nobody audits — and if a baseline ever passes the gate on real data,
the first suspicion should be the harness, not the edge.

#### Causality is structural

A strategy never receives the whole series. It receives a `View` the harness
built from rows with `ts <= now`, and the slicing happens *before* the strategy
is called — there is no future in the object to peek at.
`test_backtest.py` drives a deliberately greedy strategy past a 9x spike and
asserts it fills at the price it had actually reached.

#### The pre-stated gate

| criterion | threshold |
|---|---|
| out-of-sample profit factor | ≥ 1.5 |
| trades | ≥ 100 |
| max single token's share of gross profit | ≤ 20% |
| every out-of-sample week | net positive |

Thresholds live in `config.py`, so raising the bar after seeing a result is a
visible edit rather than a quiet one. Out-of-sample is the **second half of the
ISO weeks** — split on weeks and not on trade count, which would put part of a
week on each side.

#### Costs, and what they are denominated in

Per side: 1% pump fee + `SLIP_BPS` (150) + a flat `PRIORITY_FEE_QUOTE`
(0.002 SOL), which on the default 0.5 SOL position is another 40 bps.
**290 bps a side, 5.8% round trip** — so a trade that closes at the price it
opened at loses 5.64%.

Everything is in the **quote currency (SOL)**, because that is the only unit
both legs of a pre-graduation trade exist in: the curve prices in SOL, and
DexScreener's `price_native` is SOL. Converting the curve leg to USD would need
a SOL/USD rate this lab does not record — and taking one from the token's own
post-graduation samples would be reading the future to price a decision made
before it. The consequence: **these returns do not equal
`grad_features.return_*`**, which are USD, and differ by however much SOL/USD
moved during the hold.

A backfilled GeckoTerminal candle carries no native price and so cannot be a
fill point. Those tokens are counted in the funnel, never silently dropped.

#### The population is not just graduates

A pre-graduation strategy tested only on tokens that went on to graduate is
conditioned on the outcome it is trying to predict. So the population is every
token that **reached the entry checkpoint**, graduate or not, and one that
never migrates within `PRE_GRAD_DEAD_HOURS` (24) is written off at
`PRE_GRAD_DEAD_HAIRCUT` (0.5) of its last observed curve price — no pool, no
route out, no bid.

Note the interaction with pruning: a non-graduate's curve series is deleted
after 24h and its checkpoints are kept, so for an older dead token the "last
observed price" *is* the entry and the loss is exactly the haircut. That is the
intended reading, not an accident.

### 7. Diagnostics

```bash
python -m app.labs.graduation curve --mint <MINT>
```

Does the whole chain for one mint — derive, fetch, decode, compute — which is
the fastest way to tell a bad endpoint from a bad mint from a changed layout:

```json
{
  "mint": "Bjsxb2QErbB4rhpSRsUgtNBPPri24R3AK58tQwjvpump",
  "curve_address": "3XWT7fTxe9xkKsGYjNZ3AVoaomUVpxw2hDyeo3Rupwfy",
  "progress_pct": "0.000",
  "complete": false,
  "real_token_reserves": "793100000",
  "market_cap_quote": "27.958993482"
}
```

Also `health` (counters as JSON), `prune` (one pass), and
`progress --tokens N`.

### 8. The beat tasks

Two: pruning every 15 minutes, feature building every 10.
`app.labs.graduation.scheduler` is in `celery_app.py`'s `include` list and both
schedules register themselves with `setdefault`, so an operator who prefers an
explicit entry wins and there is never a duplicate. With the flag down both
return before opening a session.

They are deliberately **not** chained: they touch disjoint rows — the pruner
only ever deletes non-graduates, the feature engine only ever reads graduates —
so ordering them would buy nothing and a failure in one would delay the other.

### 9. Tests

```bash
python -m pytest app/labs/graduation/tests -q
```

218 tests, no database and no network required.

---

## Known limitations

**0. Between two polls, the path is not recorded — and features inherit that.**
Fifteen seconds is long enough for a curve to go from 68% to 94%. Checkpoints
handle it correctly (all three levels written from the one reading that
revealed them), but a checkpoint's timestamp is *when it was seen*, not when it
happened, so `minutes_from_70` and both velocities carry up to one poll
interval of slack. A strategy tuned to differences finer than that is tuned to
noise.

**1. There is no per-trade detail, and there cannot be.** The curve account
reports *reserves*, not who moved them. Buyer counts, unique traders and
holder concentration are not computable from a poller at any price. Those
columns are kept for a Phase 2 graduate-only backfill and are **0 or null
today**: a reader must treat that as "not collected", never as "none". This is
the real cost of coming off the metered stream, and it is the one thing that
got worse.

**2. Between two polls, nothing is known.** Fifteen seconds is long enough for
a token to go from 68% to 94%, and the intermediate path is simply not
recorded. Checkpoints handle this correctly — all three levels are written from
the one reading that revealed them — but a checkpoint's timestamp is *when it
was seen*, not when it happened, and the two can differ by up to a poll
interval. Nothing here can reconstruct intra-poll ordering.

**3. Every timestamp is observation time.** No PumpPortal message carries a
timestamp or a slot, and `getMultipleAccounts` at this encoding carries no slot
either. So `ts` is when the process read the response.

**4. A gap in `grad_curve_samples` is not a gap in coverage.** It means nothing
moved. Use `grad_tokens.last_sample_at` and `sample_count` to tell "not
looked at" from "looked at, unchanged".

**5. The migration payload shape is unverified.** PumpPortal publishes no
example for `subscribeMigration`. The field names here are the documented ones;
`unexpected_fields()` reports anything new on the first live run — logged once
and surfaced in `health` — rather than letting a renamed field become a column
of nulls discovered months later.

**6. A token whose first DexScreener poll fails can never be backfilled.**
GeckoTerminal addresses a *pool*, and the pool address is only ever learned
from a DexScreener response. That gap is permanent, and `backfill_impossible`
counts it rather than hiding it.

**7. Coverage is bounded by `MAX_WATCH_SET`.** At a high enough launch rate the
least-progressed candidate is evicted, so some tokens are never followed.
`unsubscribe_reason = 'evicted'` marks them, and any analysis of "what fraction
of launches reach 70%" must exclude them or it is measuring the cap. The same
caution applies to `grad_features`: it holds graduates, so **any rate computed
from it alone is conditioned on graduating**.

**8. There is no backfill and no history.** A token is only known if this
process was running when it launched, and a restart loses the in-memory state.
**Any study over this data is survivorship-affected** in the same way as the
Phase 9.5 historical dataset: it records what was watched, not what existed.

**9. Pruning is lossy on purpose.** After 24 hours a token that never migrated
loses every `grad_curve_samples` row. What survives is the `grad_tokens`
aggregates and *all* of its checkpoints — "how many tokens reached 90% and died
there" stays answerable for ever at five rows a token. Raise
`PRUNE_AFTER_HOURS` before a study that needs the reserve series on failures.

**10. The backtester's cost model understates a pre-graduation entry, and
cannot fix it.** `SLIP_BPS` is a flat assumption. On the curve it is far too
kind: median pre-graduation liquidity was **$4,112**, making a $100 buy ~2.5%
of the pool, with measured Jupiter impact near 99% and **no sell route at all
for 37% of tokens**. The reserve series records what the curve *quoted*, not
what a taker would have been *filled* at, so nothing in the harness can correct
this. A pre-graduation strategy that clears the gate has cleared a bar that is
too low; the next step is a depth model, not a deployment. Post-graduation
paths do not carry this caveat.

**11. Even with perfect data, the trade may not exist.** Measured on 738
graduates in 24h: only 94 had any pre-graduation liquidity reading, **median
pre-grad liquidity $4,112**, and only 29 would clear a $100k floor. At that
depth Jupiter routing showed ~99% buy impact and **37% of sells had no route**.
This lab is built to *measure* the approach to graduation. Nothing here asserts
it is tradeable, and the liquidity evidence so far says the pre-graduation side
is not.

---

## Isolation

Its own `grad_*` tables, its own flag, its own config module, its own tests.
It imports no paper wallet, no real wallet, no radar and no sibling lab.

It **does** import four platform modules, deliberately and by name:
`app.services.curve.pda` (PDA derivation), `app.services.curve.state` (the
mainnet-verified account decoder), `app.services.rpc.standard` (plain JSON-RPC)
and `app.services.market.providers.rate_budget` (the token bucket). All are
pure or transport; none trades, scores or holds a wallet. Re-implementing the
curve layout inside the lab would mean two definitions of the same bytes, free
to drift — exactly the failure the platform's curve module exists to prevent.

`tests/test_isolation.py` pins that allow-list, fails on any other `app.`
import, asserts that `curve.py`, `parse.py` and `watchset.py` never learn a
network exists, and fails if `subscribeTokenTrade` reappears anywhere in
executable code. It also pins the table names `features.py` is allowed to name
in raw SQL. Deleting this directory plus its three migrations removes the lab
entirely.
