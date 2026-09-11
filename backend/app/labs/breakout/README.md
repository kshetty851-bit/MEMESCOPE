# Breakout Lab

Momentum into daily resistance on **established** Solana tokens — pools older
than a week, with real liquidity and real volume, on real DEXes. **Phase 1 is
the data layer and nothing else**: a universe and its candles. There is no
setup detection, no score, no position, no paper wallet and no UI, and none of
those is a small addition away.

Isolated the way the Crypto Trend lab is: its own `bo_*` tables, its own flag,
its own config, its own tests, and no import of any paper wallet, real wallet,
radar, or other lab. It reads two keyless public APIs and writes only its own
tables. A source-parsing test holds every one of those claims.

---

## How to enable it

Off by default. One environment variable:

```bash
BREAKOUT_LAB_ENABLED=true
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
