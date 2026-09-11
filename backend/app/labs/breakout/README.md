# Breakout Lab

Momentum into daily resistance on **established** Solana tokens — pools older
than a week, with real liquidity and real volume, on real DEXes.

| Phase | What it is |
|---|---|
| 1 | the universe and its candles — `bo_universe`, `bo_candles`, `bo_runs` |
| 2 | resistance levels, a momentum score, the setup state machine and the episode record — `bo_levels`, `bo_setup_snapshots`, `bo_episodes` |
| 3 | the paper trader: ten slots of equity/10 from $1,000 with a 25% trailing stop — `bo_account`, `bo_positions`, `bo_trades`, `bo_equity` |
| 4 | the tab at `/breakout-lab` |

**It is paper.** Its own ledger, no key, no signer, and no route that can move
the book. Nothing here imports the platform paper wallet, the Karthik wallet,
the real wallet or another lab, and a source-parsing test holds that on every
module including the ones no test exercises.

Isolated the way the Crypto Trend lab is: its own tables, its own flags, its
own config, its own tests. It reads two keyless public APIs — GeckoTerminal
and DexScreener — and writes only its own tables.

---

## How to enable it

Off by default, behind **two** flags. The first runs detection and recording;
the second, separately, lets it open paper positions.

```bash
BREAKOUT_LAB_ENABLED=true
BREAKOUT_TRADING_ENABLED=true
```

Apply the migration, then drive a tick:

```bash
cd backend && alembic upgrade head
```

```bash
cd backend && BREAKOUT_LAB_ENABLED=true python -m app.labs.breakout tick
```

In Docker, the same inside the backend container:

```bash
docker compose exec -e BREAKOUT_LAB_ENABLED=true backend python -m app.labs.breakout tick
```

With the flag off, every task returns `{"skipped": "breakout_lab_disabled"}`
**before it opens a session or a socket**, and the routes answer
`{"running": false}` without touching the database. Tests hold both.

### The commands

| Command | What it does |
|---|---|
| `python -m app.labs.breakout tick` | one full tick: universe refresh, then candles |
| `python -m app.labs.breakout universe` | the active universe as a table |
| `python -m app.labs.breakout backfill --mint MINT` | fill both timeframes for one token, ignoring the per-tick page cap |
| `python -m app.labs.breakout health` | `data_health()` as JSON |

---

## What a tick does

Two halves, chained. `breakout-lab-tick` runs the universe refresh and then
**enqueues** `breakout_candles_tick` — the Crypto Trend lab's pattern, and the
paper wallet's before it. Chained rather than separately scheduled so candles
can never race the universe they are fetched for; enqueued rather than run
inline so a candle failure cannot roll back a completed universe refresh.

### 1. Universe — `universe.py`

Candidates, Solana only:

| Source | Endpoint | Calls |
|---|---|---|
| GeckoTerminal | `/networks/solana/pools?sort=h24_volume_usd_desc&include=base_token`, pages 1…`UNIVERSE_PAGES` | 10 |
| GeckoTerminal | `/networks/solana/trending_pools` | 1 |
| DexScreener | `/token-boosts/top/v1`, `/token-profiles/latest/v1` | 2 |
| DexScreener | `/tokens/v1/solana/{≤30 mints}` for the Solana mints those two named | 1–2 |

`/latest/dex/search?q=` is deliberately **not** used: it is too broad, and the
two ranked lists above already are the volume ranking this lab wants.

Then the filters, all in `config.py`, checked in this order so a counter of
rejections reads as a funnel:

| Filter | Default | Note |
|---|---|---|
| `EXCLUDED_MINTS` | stables, WSOL, LSTs, bridged majors | by **mint**, because a mint cannot be renamed. Editable list. |
| `DEX_ALLOWLIST` | raydium, meteora, orca, pumpswap | **prefix** match — see below |
| `DEX_DENYLIST` | pumpfun | checked first, so the bonding curve can never be admitted by a prefix |
| `MIN_AGE_DAYS` | 7 | on `pool_created_at` / `pairCreatedAt`; an **unknown** age is refused, not assumed old |
| `MIN_LIQUIDITY_USD` | 50,000 | a **missing** liquidity is refused — an unknown reserve is not a $50,000 one |
| `MIN_VOLUME_24H_USD` | 100,000 | |
| `MAX_UNIVERSE` | 300 | the cap, by 24h volume |

**The dex allow-list matches by prefix, and that is not laziness.** Both
sources suffix their venue variants — GeckoTerminal serves `raydium-clmm` and
`meteora-damm-v2` beside `raydium` and `meteora`. Measured on 80 live pools:
28 cleared age, liquidity and volume, 22 of those sat on an allowed venue, and
**4 of the 22 were `raydium-clmm`** — an exact-match list would have dropped
all four, an 18% cut for a spelling.
`pumpswap` (the graduated AMM) is allowed and `pumpfun` (the curve) is not,
which is why the denylist exists and is checked first.

**One pool per token.** The deepest pool wins and the token's other
*qualifying* pools are stored as `alt_pools` JSON for reference. A pool of the
same token that failed the filters is not kept as an alternate — it is not a
fallback, it is a pool that failed.

**Only the BASE token of a pool is considered.** On a `SOL / USDC` pool the
base is WSOL and the exclusion list catches it. A token that only ever appears
as the *quote* side of a pool is invisible to this lab; on Solana that is
effectively only the stables and WSOL, which are excluded anyway.

Everything is persisted to `bo_universe` keyed on the mint. A token that stops
qualifying is marked `active = false` with an `inactive_reason` — **never
deleted**, and its candles are kept. Qualifying again clears the flag, resets
the failure counter, and leaves `first_seen` alone, so a re-admission stays
comparable with a token that never left. Additions and drops are logged each
refresh (`breakout_universe_refreshed`).

**A refresh that produces nothing leaves the previous universe standing.** A
bad response must not empty the watch list.

### 2. Candles — `candles.py`

`GET /networks/solana/pools/{pool}/ohlcv/{day|hour}`, `currency=usd`.

| Timeframe | Window | Refresh |
|---|---|---|
| `day` | `CANDLE_WINDOW_1D` = 180 bars | once a day, after `DAY_REFRESH_AFTER_MINUTE` (5) past 00:00 UTC |
| `hour` | `CANDLE_WINDOW_1H` = 336 bars (14 days) | every tick, for the tokens whose bar has closed |

Two directions per token and timeframe, **neither sent unless it is needed**:

* **forward** — the bars that have closed since the newest stored one, asked
  for with `limit = missing + 1`. When that count is zero **no request is
  sent at all**, which is most ticks for `hour` and every tick but one a day
  for `day`.
* **backward** — pages of older bars until the window is full or the pool's
  history runs out, at most `BACKFILL_PAGES_PER_TICK` (2) a tick so one deep
  backfill cannot eat the budget. Resumable by construction: the next tick
  sees the same short history and continues.

**The still-forming bar is dropped.** GeckoTerminal serves it as the *first*
row; storing it would write a close that is still moving. The cut is
`open_time + interval <= now`.

**`before_timestamp` is inclusive** — a page asked for `before=t` comes back
with the bar at `t` as its first row. The upsert absorbs the overlap, and a
page that returns no bar older than the one already held is how the lab knows
it has reached the pool's first bar. It never spins.

Storage is `bo_candles`, unique on `(mint, timeframe, open_time)`, upsert only.
A bar with a missing or non-numeric price is **dropped rather than stored as
zero**: a zero low would sit under every future support level for ever.

#### The queue, and what "carry the remainder" means

The refresh walks the active universe **ordered by 24h volume, descending**, so
a rate-limited run covers the most liquid names first. It stops on the call
cap or the deadline and reports `tokens_carried`.

**No queue is stored.** A token is due a fetch exactly when its newest stored
bar is older than the last closed bar, so a token fetched this tick drops out
of the queue and one that was not fetched is still in it. Ordering the due
list by volume therefore covers the liquid names first and leaves the rest for
the next tick — which *is* the carry. A stored queue would be a second source
of truth for a fact `MAX(open_time)` already answers.

When the budget runs out mid-token, what was already fetched is **kept**, not
rolled back: the calls that bought it are exactly the ones that just ran out.
The token still counts as carried, because the timeframe the budget cut short
is still missing.

Each token's work otherwise runs in its own savepoint, so one token failing
costs that token this tick and nothing else.

#### Per-token data health

`MAX_FETCH_FAILURES` (5) **consecutive** failures retire a token with
`inactive_reason = "fetch_failures"`. Any success resets the counter, so a
token is retired for being persistently broken and never for a bad afternoon.
Last candle time per timeframe and gap detection are computed in
`data_health()` from `bo_candles` — they are derived, not stored, because a
fourth table holding what a `GROUP BY` already knows would be a second source
of truth for the same fact.

---

## Sources and their limits

Free and keyless throughout. **The lab keeps its own thin client**
(`sources.py`) and imports neither of the platform's two — see that module's
docstring for why.

### What the platform already spends

| Host | Platform's spend | The lab's budget |
|---|---|---|
| `api.dexscreener.com` | the **primary** market provider. `ENRICHMENT_BATCH_LIMIT` 120 ÷ `MARKET_PROVIDER_BATCH_SIZE` 30 = 4 requests per cycle, every `ENRICHMENT_POLL_INTERVAL_SECONDS` (5) → **up to ~48/min** of a ~300/min ceiling, plus the curve collector | `DEXSCREENER_CALLS_PER_MINUTE` = 60. About 4 calls a tick is all it wants. |
| `api.geckoterminal.com` | **currently none.** `MARKET_SECONDARY_CALLS_PER_MINUTE` is 25 of a ~30/min free tier, but that provider is consulted only when `MARKET_PROVIDER="composite"`, and `.env` sets `dexscreener` | `GECKOTERMINAL_CALLS_PER_MINUTE` = 25 |

> **If anyone switches `MARKET_PROVIDER` to `composite`**, the platform's 25
> plus this lab's 25 exceeds GeckoTerminal's free tier and both will start
> taking 429s. `GECKOTERMINAL_CALLS_PER_MINUTE` is the one constant to cut; it
> is the lab's whole claim on that host.

### Two things measured on live traffic, both of which changed the code

**1. A per-minute rate is not enough — these hosts punish bursts.** A client
well inside GeckoTerminal's 30/min allowance was refused on its **seventh call,
0.7 seconds in**, and stayed refused for about **35 seconds**. A plain token
bucket is the wrong shape for that: it starts full and hands out the whole
minute at once. So each host's `CallBudget` is built with a **capacity of one**
and a window of `60 / rate` seconds, which turns the platform's own bucket into
a minimum *spacing* between calls — 2.4s for GeckoTerminal, 1.0s for
DexScreener — with no burst possible and no new rate-limiter written.

**2. `Retry-After` is a floor, never a ceiling.** GeckoTerminal answers a 429
with **`Retry-After: 0`** and then refuses for half a minute. Honouring that
header literally — which is what the obvious implementation does — retried four
times inside a millisecond and gave up while the host was still angry. The
delay is `max(Retry-After, backoff.delay_for(attempt))`, a non-numeric or
negative header reads as zero, and `MAX_ATTEMPTS` is 5 from a 2-second base so
the expected total wait covers the measured lockout. Both behaviours have a
test that drives the real client over a fake transport.

A 4xx that is not 429 is **not** retried: a 404 is a dead pool, not a busy
host, and retrying it spends the budget on a wrong answer.

### What the budget costs in wall time

**One thing to watch if this is ever put on a busy worker.** The beat fires
every 900s and the tick is bounded at roughly 80s (universe) + 600s (candles),
so in the normal case two candle passes cannot overlap. They could if the
worker's queue is backed up by more than ~220s, and because each pass builds
its own `BreakoutSource` the two would spend *separate* budgets against the
same host. There is no distributed lock — the deadline is the guard, and
lowering `TICK_DEADLINE_SECONDS` widens the margin. If `bo_runs` ever shows two
`candles` rows whose windows overlap, that is what happened.

At 2.4s a call, a universe refresh is ~40s (16 calls) and a full candle sweep
is about 2.4s × tokens × timeframes × pages. `MAX_CALLS_PER_TICK` (240) and
`TICK_DEADLINE_SECONDS` (600) bound it; the rest carries. Both are **per
phase**: the two passes build a `BreakoutSource` each, so each has its own cap,
and the deadline is the candle pass's alone — the universe pass is bounded by
having a fixed number of calls to make. **At
`MAX_UNIVERSE` = 300 a complete hourly sweep does not fit in one 15-minute
tick** — that is the free tier's arithmetic, not a bug, and the carry is the
design for it. In practice the cap is nowhere near binding (see below).

---

## How to check health

```bash
cd backend && BREAKOUT_LAB_ENABLED=true python -m app.labs.breakout health
```

or, once the API is up and an alpha cookie is held:

| Route | Answers |
|---|---|
| `GET /api/v1/labs/breakout/health` | flag state, universe size, candle coverage per timeframe, budget, the last run of each phase |
| `GET /api/v1/labs/breakout/universe` | active tokens with their stats, most liquid first |

(every router in this repo mounts under `settings.API_V1_PREFIX`, so the paths
carry `/v1`.) Both are **read-only** — there is no POST, PUT, PATCH or DELETE
on this router, and a test holds it.

`health` reports, per token and timeframe: `count`, `window`, `complete`,
`last_open_time`, `age_seconds`, `stale`, `gaps`, `missing_bars` and up to five
`gap_ranges`; per token, `fetch_failures` and `last_error`; plus a `coverage`
roll-up, the budget's settings and last spend, and each phase's last run with
its errors and `tokens_carried`.

---

## Registration

Three lines live outside this package, and **one more is deliberately not
made.**

| File | Lines | What it does |
|---|---|---|
| `app/api/v1/router.py` | +4 | the import and `api_router.include_router(breakout_lab.router)` |
| `app/models/__init__.py` | +6 | imports the lab's models so `alembic/env.py` (which imports only `app.models`) can see them |
| `docker-compose.yml` | +1 | `BREAKOUT_LAB_ENABLED` in the `x-backend-env` anchor, so the flag reaches every container |
| `alembic/versions/20260911_0063_breakout_lab.py` | new | the three tables |

**Why the models import matters:** `alembic/env.py` imports `app.models` and
nothing else, so a model that package never imports is invisible to
autogenerate. Without that line the next `alembic revision --autogenerate`
sees three `bo_*` tables in the database and none in the model tree, and writes
a migration that **drops them**. It is the silent one, and the damage arrives
later in someone else's migration.

**`app/workers/celery_app.py` is deliberately untouched.** The brief's first
hard constraint whitelists exactly the three files above, and the beat
registration is not among them. So the schedule **registers itself on import**,
with `conf.beat_schedule.setdefault` — the pattern the Early Movers lab already
uses — and one line is left to an operator:

```python
include=[..., "app.labs.breakout.scheduler"]      # celery_app.py
```

```bash
celery -A app.workers.celery_app worker -I app.labs.breakout.scheduler
```

Until one of those is in place both tasks are defined and nothing runs them,
and `python -m app.labs.breakout` is the way to drive the lab. `setdefault`
means an operator who prefers to name the entry in `celery_app.py` wins over
the self-registration and there is never a second entry for the same task. The
candle task deliberately has **no** beat entry of its own: it is chained.

**Registration does not start anything.** With the flag down the task returns
before opening a session or a socket. Setting the flag means restarting the
worker and scheduler, as with every flag here — and so does the registration
itself: a Celery process started before these lines does not know the task
exists until it restarts.

The migration is parented to `0062_early_movers_lab` on `karthik-hq`. On `main`
it would need renumbering and re-parenting, as the Rafiq lab's 0056 became
0063 there.

---

## Decisions worth knowing

* **`bo_universe.holders` is created and always null.** Neither GeckoTerminal's
  public pool payload nor DexScreener's pair payload carries a holder count,
  and the brief asks for it "if available". The column exists so a later phase
  with a holder source needs no migration; nothing fills it today, and the
  route reports it as null rather than as zero.
* **Three tables, not four.** Per-token data health is last-candle-time, gaps
  and a failure count. The first two are derivable from `bo_candles`; only the
  counter is state, and it is two columns on `bo_universe`.
* **Prices carry 18 decimals.** Solana tokens are quoted far below a cent — a
  memecoin at 6.3e-9 is ordinary — and `Numeric(24, 8)` would round that to
  zero. USD aggregates keep 2.
* **`pool_address` is stored on every candle**, not only on the universe row.
  A token whose deepest pool changes must not silently splice two venues' price
  history into one series without that being visible.
* **`UNIVERSE_PAGES` is 10 because the API refuses page 11 with a 401.** Twenty
  pools a page, so ten pages is the whole ranked list GeckoTerminal will serve,
  not a number someone liked.
* **The universe is small, and the cap is not the reason.** On live data the
  age filter is what binds: of ~180 candidate pools a refresh, roughly two
  thirds are under a week old. `MAX_UNIVERSE` = 300 has never come close to
  binding.
* **No setup detection, no score, no position.** Nothing here should acquire
  one in this phase.

---

## Tests

```bash
cd backend && pytest app/labs/breakout/tests -q
```

93 pass, 1 skipped. They cover the filter chain (each floor and its
inclusive boundary, the unknown-age and missing-liquidity cases, the exclusion
list, the dex prefix match and the denylist's precedence, the funnel counter),
the one-pool-per-token collapse and its `alt_pools`, both sources' payload
normalisation including junk numbers and missing fields, the refresh's
additions, drops, re-admissions, idempotency and its refusal to empty the
universe; the candle maths (the last closed bar, the forming-bar cut, gaps, the
daily guard), forward and backward paging with `before_timestamp`, the
no-progress stop, upsert idempotency and correction, the quiet tick that sends
nothing, per-timeframe pruning, the failure counter and its reset; and the HTTP
layer over a fake transport — pacing, the `Retry-After: 0` floor, the give-up
after `MAX_ATTEMPTS`, the 404 that is not retried, the per-tick cap, and the
two hosts not spending each other's allowance. One test runs a **whole tick
through the real HTTP layer against a transport that answers 429 to
everything** and requires it to carry its queue, report its errors and count
one failure per token — not to crash, and not to retire anything on one bad
tick. Integration tests need Postgres
and are skipped cleanly without one; they run inside a transaction that is
always rolled back.

The isolation tests are the ones that matter most: no forbidden import in any
module, the only `app.services` import being the shared rate budget, every
table on the platform `Base` with the `bo_` prefix, the migration purely
additive and matching the models column for column, the API read-only, the flag
defaulting off, and the two external registrations resolving.

One test talks to GeckoTerminal and is off unless asked:

```bash
cd backend && RUN_NETWORK_TESTS=1 pytest app/labs/breakout/tests/test_network.py -q
```

The tests live inside the package, so the repo's default `pytest` (scoped to
`tests/`) is unchanged by this module's existence.

---

## Layout

```
app/labs/breakout/
├── config.py       BREAKOUT_LAB_ENABLED, sources, filters, exclusions, budgets
├── models.py       bo_universe, bo_candles, bo_runs
├── sources.py      GeckoTerminal + DexScreener over one httpx client; two budgets; backoff
├── universe.py     normalisation, filters, one-pool-per-token (pure) + the refresh
├── candles.py      OHLCV parsing, forming-bar cut, gaps (pure) + the budgeted sync
├── data.py         get_universe / get_candles / data_health
├── api.py          GET /labs/breakout/health | /universe
├── scheduler.py    breakout-lab-tick (self-registering) -> chained breakout-candles-tick
├── __main__.py     python -m app.labs.breakout tick|universe|backfill|health
└── tests/          93 tests; fakes.py holds the network stand-in and both payload shapes
alembic/versions/20260911_0063_breakout_lab.py
```

---

# Phase 2 — setup detection

## Resistance levels — `levels.py`

Pure, from daily candles, for tokens with at least `MIN_DAILY_BARS` (14) of
them. Fewer and the token is **skipped, not an error** — a pool a fortnight
old has no resistance history worth the name.

1. **Confirmed swing highs.** Bar `i` is a swing high when its high is
   strictly above every high within `SWING_LOOKBACK` (3) bars on **each**
   side. The right side must have closed, so the last three bars of a series
   can never produce one.
2. **Clusters.** Swing highs within `CLUSTER_PCT` (3%) of the group's running
   volume-weighted mean are one level, and the level is that mean. A level
   carries its touch count and its first and last touch.
3. **Broken.** A level is broken when a daily bar closed above it **after the
   cluster's last touch**.
4. **Nearest resistance** is the lowest unbroken level above the close. None
   means no setup — there is nothing above to break.

Plus daily ATR(14) — Wilder, because every reference implementation is — the
5- and 20-day ATRs the compression component compares, the 20-day mean volume
and the 10-day high and low.

### The property that makes the record worth keeping

**Nothing in `levels.py` may look forward**, and a test asserts it on every
prefix bar of a synthetic series at four lookbacks: the swing set computed
over bars 0..i must equal the swing set the full series had at bar i. If that
ever stops being true, every row in `bo_episodes` was written with knowledge
of the future and the table is worthless as a backtest. It is one `range()`
bound, and it is very easy to lose.

## The momentum score — `momentum.py`

Five components, each clamped to `[0, 1]`, weighted by
`config.MOMENTUM_WEIGHTS` (0.30 / 0.15 / 0.25 / 0.15 / 0.15, summing to one):

| Component | What it reads |
|---|---|
| `volume` | today + yesterday against twice the 20-day mean, capped at `VOLUME_RATIO_CAP` (3×) |
| `structure` | the share of the last 3 daily bars whose low is above the one before it |
| `position` | where the close sits in the 10-day range, 0 at the low and 1 at the high |
| `compression` | `1 − ATR(5)/ATR(20)`; a coil scores high, an expansion zero |
| `hourly` | half the sign of the 12-hour slope, half the share of green bars |

Every component comes back with the score. A score nobody can take apart is a
number nobody can argue with — and the point of `bo_episodes` is to find out
later which of these five, if any, predicted anything.

**Missing hourly data drops the hourly weight, renormalises the other four,
and caps the result at `HOURLY_MISSING_SCORE_CAP` (80)** with
`hourly_missing` set. Scoring the absent component zero would punish us for
our own data gap; leaving the weights alone would quietly score the token out
of 85. The cap is what stops a half-seen token outranking a fully-seen one.

## The state machine — `setups.py`

Evaluated on every closed hourly bar, against the nearest unbroken
resistance. `distance_pct` is how far **below** resistance the price is;
negative means above.

| State | Rule |
|---|---|
| `BROKE_OUT` | close more than `BREAK_CONFIRM_PCT` (1%) above resistance — whatever the score says |
| `FAILED` | the episode **had** reached `PRE_BREAKOUT` and price is now more than `FAIL_PCT` (12%) below resistance, or the score fell under `FAIL_SCORE` (50) — deliberately *not* the watch floor |
| `PRE_BREAKOUT` | score ≥ `PRE_SCORE` (65) and 0 ≤ distance ≤ `PRE_ZONE_PCT` (6%) |
| `WATCHING` | score ≥ `WATCH_SCORE` (35) and 0 ≤ distance ≤ `WATCH_ZONE_PCT` (30%) |
| `NONE` | anything else |

Checked in that order, and the order is not arbitrary: failure is tested
before the entry zones so a setup cannot re-arm on the same bar it fails.

**The band between resistance and resistance + 1% is deliberately `NONE`** —
`PRE_BREAKOUT` is strictly below resistance and a break needs a 1% close above
it, so a price inside that sliver is neither. It does not close an episode: a
lull is not an answer.

### Episodes

One open episode per token, enforced by a **partial** unique index so closed
ones accumulate freely. It opens on the first `WATCHING` or `PRE_BREAKOUT`,
and closes on `BROKE_OUT`, `FAILED`, `MAX_EPISODE_HOURS` (168) → `EXPIRED`, or
the token leaving the universe → `universe_exit`.

`first_pre_breakout_at` and `entry_ref_price` are set the first hour it
reaches `PRE_BREAKOUT` — the moment Phase 3 buys, and the reference every
outcome is measured from. `peak_price` and `min_price` are tracked **only
after** that reference exists: a high reached before we would have bought is
not a gain we would have had.

### Outcomes, 72 hours later

A separate daily pass fills `max_gain_pct_from_ref`, `max_loss_pct_from_ref`,
`pct_at_24h`, `pct_at_72h`, `trail25_result_pct` and `outcome_gappy`, marking
`outcome_at` so it never runs twice. **The separation is the point**: if the
outcome were written by the same pass that wrote the setup, the record would
be worthless. Gaps in the hourly bars are treated as no movement and flagged,
so the number can be excluded later rather than silently trusted.

`trail25_result_pct` is what a $100 position with a $25 trailing stop would
have returned — and it is computed with the **same function the live trader
uses**, not a second implementation. See Phase 3.

---

# Phase 3 — the paper trader

Behind **its own second flag**, `BREAKOUT_TRADING_ENABLED`, default off.
Detection and recording are safe to run anywhere; opening positions is a
separate decision, and one switch for both would mean you could not have the
watchlist without the book.

```bash
BREAKOUT_LAB_ENABLED=true BREAKOUT_TRADING_ENABLED=true \
  python -m app.labs.breakout trader status
```

## Entry

A token whose episode **transitions** into `PRE_BREAKOUT` — not one that has
been sitting in it for six hours. Entering a stale state every hour would be a
different strategy from the one being recorded.

**Decide on one bar, fill on the next.** The trader takes the transition that
happened on the *previous* closed bar and fills at the **open** of the bar that
has just closed. That is the brief's "fill at the next hourly open" with no
pending-order state, because by tick time that open is a stored number rather
than a guess.

| Gate | Rule |
|---|---|
| slots | `SLOTS` (10); slot size is `equity / SLOTS` **at the moment of entry**, so it compounds and shrinks with the book |
| liquidity | `liquidity_usd ≥ MIN_LIQ_FOR_ENTRY` ($50,000); an unknown liquidity is refused, not assumed deep |
| pool share | the position may not exceed `MAX_POOL_SHARE_PCT` (0.5%) of pool liquidity — the honest limit on a memecoin order is the pool, not the wallet |
| one per token | never two positions in the same mint |
| ranking | more candidates than slots → highest score, ties broken by 24h volume, then by mint so the order is total |

Costs on every fill: `SLIPPAGE_BPS` (100 = 1%) and `FEE_BPS` (30). A round
trip at a flat price loses about **2.6%**, so the number to beat is not zero.

**There is no floor under the slot size.** Below $100 of equity the lab carries
on at equity/10 — pre-decided, because the kill switch is the only thing
allowed to halt trading.

## Exit — first rule wins

| Reason | Rule |
|---|---|
| `forced_exit` | the token left the universe; we can no longer price it honestly |
| `trail_stop` | value fell `TRAIL_PCT` (25%) of the slot below its high-water value |
| `failed_setup` | the episode closed `FAILED` **and** the position is under water |
| `time_stop` | held `MAX_HOLD_HOURS` (168) **and** still under water |

The last two only close losers on purpose: a winner keeps its trailing stop,
which is the exit that knows what the price is actually doing.

### The line that decides whether any of this means anything

`rules.trail_step` takes **the low before the high**. A bar that would both
take the stop out and set a new high exits at the stop — we cannot see the
order within a bar, so we assume the order that costs us. The high-water mark
is raised only after the low has been checked, so a stop can never be lifted
by a high the price reached after it would already have been hit.

**That function is shared.** Phase 2's `trail_result` folds it over a series;
the trader calls it once per tick. One rule, not two implementations — so
`bo_episodes.trail25_result_pct` and the live book cannot drift apart. A test
runs the same hourly series through both and requires them equal net of
costs, and a second, structural test asserts `trail_result` really does call
`trail_step` rather than reimplementing it.

## The kill switch

Drawdown from peak equity beyond `MAX_DRAWDOWN_PCT` (40%) closes every
position, sets `halted`, and refuses entries until a human runs:

```bash
python -m app.labs.breakout trader reset-halt --yes
```

The reset also **re-bases the peak to current equity** — leaving the old peak
would re-trip the switch on the next tick, which is not a reset, it is a loop.

```bash
python -m app.labs.breakout trader flatten --yes
```

Both destructive commands require `--yes`.

---

# The routes

All eleven are **read-only**. There is no POST, PUT, PATCH or DELETE on this
router and no endpoint that can open, close or size a position — trading is
driven by the scheduled tick and the CLI, and two tests hold it.

| Route | Answers |
|---|---|
| `GET /api/v1/labs/breakout/health` | flag, universe size, candle coverage, `starved_tokens`, budget, last run per phase |
| `GET .../universe` | active tokens with their stats |
| `GET .../setups` | open episodes, `PRE_BREAKOUT` first then by score |
| `GET .../setups/{mint}` | the token panel: universe row, levels, latest snapshot, episode, and both candle series |
| `GET .../episodes?limit&offset` | the closed record, with every outcome column |
| `GET .../stats` | open by state, closed by reason, **outcomes by score decile** |
| `GET .../account` | equity, cash, unrealised, drawdown, slots, halted, trading flag |
| `GET .../positions` | open positions with mark, high-water and trailing-stop value |
| `GET .../trades?limit&offset` | closed round trips with their exit reason |
| `GET .../equity?hours` | the curve |
| `GET .../trade_stats` | win rate, expectancy, profit factor, drawdown, split by exit reason |

With either flag off the routes answer `running: false` — or the starting
account — **without touching the database**, because "not running" and "ran
and found nothing" are different facts.

---

# Phase 4 — the tab

`/breakout-lab`, from `frontend/src/labs/breakout/`. One nav entry and one
route file outside that folder, and nothing else.

* **Header** — equity, unrealised, drawdown, slots used/free, slot size,
  universe size, last tick, a red `HALTED` banner in an `alert` role, and a
  `paper` tag that is always visible.
* **Setups watchlist** — open episodes, `PRE_BREAKOUT` first and badged, then
  by score. A row opens the token panel.
* **Token panel** — SVG candles with a daily/hourly toggle, resistance
  clusters drawn as horizontal lines (**unbroken solid, broken dashed**), the
  pre-breakout zone shaded under the nearest resistance, entry and trailing-stop
  markers when a position is open, and the five score components beside it.
* **Positions + equity curve** with a 24h / 7d / 30d selector.
* **Trades + two verdict cards** — the trading statistics, and *"Does the
  score work?"*: completed episodes by the score they were recorded at
  against what the trailing stop returned. If the score predicts anything, the
  top deciles beat the bottom ones.

**No charting library.** There is none in this repo and this lab may not add
one, so the chart is plain SVG on a **logarithmic** price axis — a memecoin
that ran 40× over 180 days is a vertical wall on a linear axis with every
level formed months ago squashed into the floor, which is exactly what the
chart exists to show.

Mock mode is `NEXT_PUBLIC_BREAKOUT_MOCK=true`, served from `mock.ts`. The
fixtures are **typed against `types.ts`**, which mirrors the backend response
models, so a field renamed on the server fails the build rather than rendering
a blank column nobody notices for a week.

---

# Pre-registered change — 2026-09-11, the widened watch gate

Recorded **before** the change ran, so `bo_episodes` can be split on it
afterwards rather than argued about.

## What was observed first

The first production tick, on real data:

```
242 candidates
 −173  pool younger than 7 days        (71% of everything)
 − 27  excluded mint
 − 11  wrong DEX
=  31 qualifying pools → 18 tokens → 13 scorable → 1 WATCHING
```

One token on the watchlist. Two separate causes, both measured:

* **The ranked list is capped.** GeckoTerminal's network-wide `/pools` serves
  200 pools however it is sorted, and that was the whole candidate supply.
* **The tokens with momentum had no resistance left.** RAY scored 77 with
  every cluster broken — nothing above to break. The one token sitting under
  resistance (SOLCEX, 0.15% below) scored 62 against a PRE floor of 65.

## What changed

| | Before | After | Touches trading? |
|---|---|---|---|
| `UNIVERSE_SORTS` | 1 sort | volume **and** tx count | no |
| `UNIVERSE_DEXES` | — | raydium, orca, meteora, pumpswap, 5 pages each | no |
| `UNIVERSE_REFRESH_SECONDS` | 900 | 3600 | no |
| `WATCH_SCORE` | 50 | **35** | no |
| `WATCH_ZONE_PCT` | 15 | **30** | no |
| `FAIL_SCORE` | *was `WATCH_SCORE`* | **50**, its own constant | **prevented** a change |
| `PRE_SCORE` | 65 | 65 | — |
| `PRE_ZONE_PCT` | 6 | 6 | — |
| `MIN_AGE_DAYS` | 7 | 7 | — |

**The trading gate did not move.** `WATCHING` is a watchlist; `PRE_BREAKOUT`
is what the book buys. Widening the first grows what can be seen without
changing a single entry, so episodes before and after this date remain
comparable on the only thing the trader reads.

**`FAIL_SCORE` is the part worth reading twice.** `FAILED` is one of the
trader's exits, and the failure rule read `WATCH_SCORE`. Lowering the watch
floor to 35 would therefore have lowered the bar at which a *live position* is
declared dead — holding losers longer — with nothing in the diff saying so.
The two questions now have two constants, and a test asserts a setup can never
be declared dead while it is still worth watching.

## Why five pages per venue and not ten

Measured against the live API before shipping: four venues at ten pages each
produced **81 retries and had not finished after six minutes**. The free tier
will not sustain it. At five the sweep is ~35 calls and finishes inside the
deadline — which matters beyond speed, because **only a complete sweep is
allowed to retire a token**, so a permanently-truncated one would mean nothing
ever leaves the universe. Raise it once the real cost is observed in
`bo_runs.requests`.

## What this is expected to do, and what would falsify it

Expected: candidates ~242 → ~640, universe ~18 → 80–150, watchlist into the
tens. **Not into the hundreds** — 6% of the universe reached WATCHING at the
old gate, and the arithmetic for hundreds of setups needs either a universe in
the thousands or a change to `MIN_AGE_DAYS`, which is the lab's premise.

The honest risk is that a wider gate is simply a noisier one. The test is
`GET /stats` → `outcomes.by_score_decile`: if the low deciles this change
admits perform like the high ones, the score never carried information and the
widening only made that visible sooner. That is a useful answer either way,
and it is the reason the outcome columns are filled by a separate pass 72
hours later.

---

# Decisions made unattended

Each of these was ambiguous in the brief. The conservative reading was taken
and recorded here rather than asked about.

* **A level breaks only on a close above it AFTER the cluster's last touch.**
  Read literally, "any daily close above it" lets a cluster break itself: the
  level is a volume-weighted mean, so a constituent swing can have closed above
  it. Restricting the search is also the conservative reading — fewer levels
  are called broken, so more stand as resistance and fewer breakouts are
  claimed.
* **No cluster-merge pass, because none is reachable.** The decision list asks
  for duplicate clusters to be merged after rounding. With this grouping they
  cannot arise — a new group opens only when the previous group's mean is
  final and already more than `CLUSTER_PCT` away — so a fold over them would
  never fire. A parametrised test asserts the invariant directly instead,
  which is what the decision was for.
* **The `position` component is continuous, not a 30% threshold.** A threshold
  would throw away the difference between a close at the 31st percentile and
  one at the 99th, which is the difference that matters. A close in the top
  30% is simply one scoring above 0.7.
* **Only the BASE token of a pool is considered.** A token that appears only
  as the quote side is invisible to the lab; on Solana that is effectively the
  stables and wrapped SOL, which are excluded anyway.
* **`failed_setup` and `time_stop` only close losing positions.** A failed
  setup that is nonetheless in profit keeps its trailing stop.
* **The kill-switch reset re-bases the peak**, or it would re-trip next tick.
* **A position with no bar on this tick is held, not guessed at** — unless the
  token has also left the universe, in which case it is closed at its entry,
  the only number still defensible.
* **Drawdown is read off the stored equity curve**, not off the trade
  sequence: open positions are part of a drawdown anyone lived through.
* **`profit_factor` is null, not infinity, when nothing has lost yet.**
* **Mock mode reads `process.env.NEXT_PUBLIC_BREAKOUT_MOCK` directly** rather
  than going through `src/lib/env.ts`, which is shared and outside this lab's
  permitted edits.
