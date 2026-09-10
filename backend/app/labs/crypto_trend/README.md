# Crypto Trend Lab

Trend-following on the top-20 cryptocurrencies by market cap. **Phase 1**
stores candles, funding and the universe; **Phase 2** computes each coin's
trend state and a market-wide regime from them; **Phase 3** is the strategy
as pure functions and a replay harness that runs it over stored history at
cost. **None of them touches the paper wallet, holds a live position, or
has a UI.**

Isolated the way the Rafiq lab is: its own `ct_*` tables, its own flag, its
own config, its own tests, and no import of any paper, karthik, real-wallet or
lab engine — nor of any shared model. It reads two keyless public APIs and
writes only its own tables.

---

## How to enable it

Off by default. One environment variable:

```bash
CRYPTO_TREND_LAB_ENABLED=true
```

Apply the migration, then drive a tick:

```bash
cd backend && alembic upgrade head
```

```bash
cd backend && python -m app.labs.crypto_trend tick
```

`tick` is idempotent and safe to run late. The first one backfills; every
later one fetches only what has closed since. To keep it running without a
Celery worker:

```bash
cd backend && python -m app.labs.crypto_trend run     # one tick every 60s, foreground
```

Two one-off commands (Phase 3.1) extend the data for out-of-sample work:

```bash
cd backend && python -m app.labs.crypto_trend backfill --tf 1h --to-match 4h
```

```bash
cd backend && python -m app.labs.crypto_trend universe snapshot --as-of 2026-03-28 --name oos_march
```

In Docker the same, inside the backend container:

```bash
docker compose exec -e CRYPTO_TREND_LAB_ENABLED=true backend python -m app.labs.crypto_trend tick
```

With the flag off, `tick` returns `{"skipped": "crypto_trend_lab_disabled"}`
before it opens a session or a socket, and the health route answers
`{"running": false}` without touching the database. A test holds both.

## What runs, each tick

1. **Universe**, if the current one is 24h old or absent: CoinGecko
   `/coins/markets` top-30, exclusions applied (`config.EXCLUDED`), each
   survivor mapped to a Binance USDT-margined perpetual (`config.SYMBOL_OVERRIDES`
   first, else `<TICKER>USDT`) and checked against Binance `exchangeInfo`.
   The first 20 that map are the universe. Additions, removals and the coins
   skipped for having no perp are logged (`crypto_trend_universe_refreshed`,
   `crypto_trend_no_perp`) and the skipped ones are recorded on the run.
2. **Candles**, `1h` and `4h`, per member: the last stored `close_time` is
   read; if the next candle cannot have closed yet, **no request is sent**;
   otherwise one request from `last_close + 1ms`, up to 1,000 rows. The
   forming candle is never stored. Upsert on `(symbol, timeframe, open_time)`.
   The newest `CANDLE_WINDOW_1H` (5,000) hourly and `CANDLE_WINDOW_4H` (1,000)
   4h candles per symbol are kept — per timeframe, so a deep 1h backfill
   survives the prune.
3. **Funding**, one `premiumIndex` call for every symbol (weight 10), filtered
   to the universe, upserted on `(symbol, next_funding_time)` — one row per
   funding interval, not one per minute, because the rate only moves at
   settlement.
4. **A run record** (`ct_runs`): what was fetched, how many requests, every
   error, the skipped coins. `data_health()` reads the newest.

Each symbol's fetch runs in its own savepoint: one symbol failing costs that
symbol this tick and nothing else. Measured on the first real tick: a
19-coin universe, 37,384 candles, 41 requests, 24 seconds. The next tick:
1 request.

### Rate limits

Binance limits by request **weight** per IP per minute (2,400). The lab
spends from the platform's `CallBudget` token bucket, capped at 1,200/min,
with each call declaring its published weight (klines 2–10 by `limit`,
`premiumIndex` 10, `exchangeInfo` 1). A 429 or 418 honours `Retry-After`
and otherwise uses the platform's `BackoffPolicy`; after `MAX_ATTEMPTS` the
call raises and is recorded as that symbol's error for the tick.

## How to check health

```bash
cd backend && python -m app.labs.crypto_trend health
```

or, once the API is up and an alpha cookie is held:

```
GET /api/v1/labs/crypto-trend/health
```

(the brief names `/api/labs/crypto-trend/health`; every router in this repo
mounts under `settings.API_V1_PREFIX`, so the path carries `/v1`.)

Per symbol and timeframe: `count`, `last_close_time`, `age_seconds`, `stale`
(nothing stored for two intervals), `gaps`, `missing_candles`, up to five
`gap_ranges`. Per symbol: the latest funding row. Plus the universe (size,
`refreshed_at`, `stale`, symbols) and the last run (timings, counts,
`errors`, `skipped`).

## The trend engine (Phase 2)

Pure computation over `data.py`: it never calls CoinGecko or Binance, and a
test parses its four modules to hold that. Plain Python — numpy is not a
dependency of this repo and the maths does not need it.

### Indicators — `indicators.py`

EMA, Wilder ATR, Wilder +DI/−DI/ADX, Donchian and swing structure, each a
series aligned to its input with `None` until enough history exists. The
seeding conventions are in the module docstring, because reference
implementations differ: EMA seeds on the simple mean of the first `period`
values; ATR's first value is the mean of the first `period` true ranges;
ADX seeds on the mean of the first `period` DX values and therefore first
appears on candle `2 * period - 1`. Every function is tested against
hand-computed values with the arithmetic in the test, and against
identities a definition must satisfy (a constant series, a perfectly
monotonic one, a ramp's known lag).

Periods, in `config.py`: `EMA_FAST=20, EMA_SLOW=50, EMA_TREND=200,
ADX_PERIOD=14, ATR_PERIOD=14, DONCHIAN_PERIOD=20, SWING_LOOKBACK=5`.

### Per-coin state — `trend.py`

On closed candles only, per symbol and timeframe:

| Field | Meaning |
|---|---|
| `direction` | `UP` if close > EMA_slow, EMA_fast > EMA_slow and ADX ≥ `ADX_MIN` (20); `DOWN` if the mirror holds; `FLAT` otherwise — unless the structure veto below refuses it. |
| `strength` | 0–100, below. |
| `slope` | EMA_slow's change over `SLOPE_BARS` (5) bars, in percent, signed. |
| `atr_pct` | ATR as a percentage of the close. |
| `bars_in_state` | Consecutive closed bars, this one included, on which the same rule fired. |
| `structure` | `HH_HL` / `LH_LL` / `MIXED` from the last two confirmed swing highs and lows. A label, not a gate. |
| `structure_veto` | True when the averages and ADX read a trend that the most recent swing refused; the state is then `FLAT` because of structure, not despite it. Only ever True on a `FLAT` state. |
| `ema_fast`, `ema_slow`, `ema_trend`, `adx`, `close` | The inputs, so a row explains itself. `ema_trend` is null until 200 bars exist. |

A swing high is a high strictly above every high within `SWING_LOOKBACK`
candles on each side, and it is **confirmed** only once the candle
`lookback` bars later has closed. `bars_in_state` is evaluated with what
was known on each bar — a swing counts from its confirmation, never
earlier — so the count carries no hindsight.

**The structure veto (Phase 2.1).** Structure was a hard gate — `UP`
required `HH_HL` — and it made verdicts sparse. It is now a veto and a
strength input. An `UP` reading from the averages and ADX is refused only
when the **most recent confirmed swing** is a lower low under the prior
swing low by more than `STRUCTURE_VETO_ATR` (0.5) × ATR; `DOWN` mirrors it
with a higher high. Three things do not veto: a shallow break; a structure
with fewer than two swings on the side that matters; and a break that a
later swing has already answered, because then the most recent swing is on
the other side and the break is history. `MIXED` structure vetoes nothing.
A vetoed state is `FLAT` with `structure_veto` set, so the effect is visible
in the table and the route.

**The strength formula.** Four components, each clamped to `[0, 1]`:

```
a = ADX / STRENGTH_ADX_FULL                                   (50 → full marks)
b = |EMA_fast − EMA_slow| / (STRENGTH_SPREAD_ATR_FULL × ATR)  (a 2-ATR spread → full)
c = lean × (close − Donchian midpoint) / (channel half-width)  (at the edge → full)
d = 1 if the structure agrees with the direction, else 0      (HH_HL for UP, LH_LL for DOWN)
strength = round(100 × (0.3·a + 0.2·b + 0.3·c + 0.2·d))
```

`lean` is +1 when EMA_fast ≥ EMA_slow and −1 otherwise, so `c` measures
the close's distance from the midpoint **in the direction the averages
lean**; a close on the wrong side scores zero rather than negative. `d` is
earned only by a trending state whose structure agrees with it — `MIXED`
adds nothing, and a `FLAT` state never earns it. Weights and ceilings are
`STRENGTH_WEIGHTS`, `STRENGTH_ADX_FULL` and `STRENGTH_SPREAD_ATR_FULL` in
`config.py`. Strength is a magnitude: it says how trendy, not which way, and
it is computed for `FLAT` states too.

**The verdict**, one per coin from its 4h and 1h states:

| Verdict | Rule |
|---|---|
| `LONG_BIAS` | 4h `UP` and 1h `UP` or `FLAT` |
| `SHORT_BIAS` | 4h `DOWN` and 1h `DOWN` or `FLAT` |
| `NEUTRAL` | anything else, with the reason: `4h FLAT, 1h DOWN`, `4h UP against 1h DOWN`, `4h UP, 1h missing`, `no 4h state` |

A missing 1h state is neither `UP` nor `FLAT`, so it gives `NEUTRAL`.

### Market regime — `regime.py`

From the universe's 4h directions: `breadth_up` and `breadth_down` are the
fractions `UP` and `DOWN` among coins **with** a 4h state (a contract too
new for one is not in the denominator).

| Regime | Rule |
|---|---|
| `RISK_ON` | `breadth_up ≥ BREADTH_RISK_ON` (0.60) and BTC's 4h is not `DOWN` |
| `RISK_OFF` | `breadth_down ≥ BREADTH_RISK_OFF` (0.60) and BTC's 4h is not `UP` |
| `CHOP` | otherwise, including an empty universe |

Thresholds are inclusive; a missing BTC state is neither `UP` nor `DOWN`,
so it vetoes nothing. `REGIME_BTC_SYMBOL` and `REGIME_ETH_SYMBOL` name the
two reported coins.

### Persistence and schedule — `engine.py`, `scheduler.py`

`ct_trend_state` holds **one row per closed bar** per symbol and timeframe,
keyed on `bar_close_time`; `ct_regime` one row per bar close across the
universe. The engine runs every minute but upserts on those keys, so
between closes it rewrites the same rows and the row count moves only when
a bar closes: 24 rows a day on 1h and 6 on 4h per symbol. Both tables keep
`TREND_RETENTION_DAYS` (30) and are pruned in the same run.

The engine is **chained** behind the data tick: `crypto_trend_lab_tick`
enqueues `crypto_trend_trend_tick` when it finishes, exactly as the paper
wallet's review is enqueued after the Radar sweep. It has no beat entry of
its own — crontab cannot offset by thirty seconds, and a second
every-minute entry would race the candles it needs — so **Phase 2 touched
no file outside this package.** Migration 0058 adds the two tables and 0059
the `structure_veto` column.

```bash
cd backend && python -m app.labs.crypto_trend trend    # run the engine once, print the table
```

Measured on the current 19-coin universe: 38 states in 1.3 seconds.

**What the veto changed, measured on one frozen set of candles (2026-09-10,
last 1h close 13:59:59Z).** Verdicts went from 2 LONG_BIAS / 0 SHORT_BIAS /
17 NEUTRAL under the hard gate to 2 / 1 / 16 under the veto; the regime
stayed CHOP. On 1h, DOWN readings rose from 12 to 16 — the gate had been
holding back four downtrends whose lower lows were not yet confirmed. On 4h
the gate had been the binding constraint for exactly one coin: of the 16
states still FLAT, 8 fail ADX < 20 and 7 have misaligned averages, and one
(HBAR) is a DOWN reading vetoed by a higher high deeper than half an ATR.
Verdicts are sparse on 4h today because 4h trends are weak, not because of
structure. Migration 0059 adds the column.

### Routes

| Route | Answers |
|---|---|
| `GET /api/v1/labs/crypto-trend/trend` | every coin's latest state per timeframe, its verdict and the reason |
| `GET /api/v1/labs/crypto-trend/regime` | the latest regime and the last 24 values, newest first |

Both answer `running: false` with the flag off, without touching the database.

## The strategy and the replay (Phase 3)

`strategy.py` is pure: it takes a `Snapshot` of one closed 4h bar — the
states, the previous bar's states, the regime, the latest funding, the
universe — plus the open positions and the equity, and returns orders. No
I/O, no clock. `sim.py` is money only: fills at cost, funding, P&L.
`replay.py` drives both over stored candles. Every value below is in
`config.py` and can be overridden per replay run.

### Entry, on a closed 4h bar

| Gate | Rule |
|---|---|
| flip | the coin's verdict FLIPPED to `LONG_BIAS` (or `SHORT_BIAS`) on this bar — a verdict that was already there is not an entry |
| regime | long: `RISK_ON`, or `CHOP` with `breadth_up ≥ CHOP_BREADTH_MIN` (0.40); short: `RISK_OFF`, or `CHOP` with `breadth_down ≥ 0.40`; no regime, no entry |
| BTC | no longs while BTC's 4h is `DOWN`, no shorts while it is `UP` |
| strength | 4h `strength ≥ STRENGTH_MIN` (40) |
| funding | shorts skipped when the latest rate `< FUNDING_SHORT_MAX` (−0.0003 per 8h), i.e. when shorts are paying heavily |
| caps | `MAX_POSITIONS` (5) open, one per symbol, `MAX_SAME_SIDE` (4) per direction; the strongest candidates take the free slots |

A position closing on this bar frees its slot and its symbol at the same
next-open fill an entry takes, so a verdict reversal on one coin is a
close and an open on the same bar.

### Sizing

Risk `RISK_PER_TRADE` (1%) of equity against a stop `STOP_ATR` (2.0) × the
4h ATR at entry: `notional = risk / (stop_distance / close)`, capped at
`MAX_NOTIONAL_PCT` (20%) of equity. The implied leverage (`notional /
equity`) is recorded on every order and trade. On today's universe the cap
binds on almost every trade — a 2-ATR stop on a 4h bar is usually under 5%
of price — so the risk actually taken is below 1%.

### Exit, checked on every closed 4h bar, first rule wins

| Reason | Rule |
|---|---|
| `universe_exit` | the symbol is no longer in `ct_universe` |
| `regime_exit` | `RISK_OFF` closes every long, `RISK_ON` every short |
| `verdict_exit` | the verdict flipped to the OPPOSITE bias (`NEUTRAL` does not exit) |
| `hard_stop` | close beyond `entry ∓ STOP_ATR × ATR_at_entry`, fixed at fill |
| `trail_stop` | once profit ≥ `TRAIL_TRIGGER_ATR` (1.5) × entry ATR, a trail hangs `TRAIL_ATR` (2.5) × the CURRENT ATR off the best close and only ever tightens; close beyond it exits |
| `time_stop` | `MAX_BARS` (60 bars = 10 days) held and still under water |

Stops are judged on the bar's **close** and filled at the next open: a
bar-close system, not an intrabar one. A gap through a stop fills at the
worse open, which is the conservative side.

### Costs, on every simulated fill

Taker fee `FEE_TAKER` (0.05%) and slippage `SLIPPAGE_BPS` (5) on both sides
— a long buys at `open × 1.0005` and sells at `open × 0.9995`. Funding on
every open position at every 8h boundary it is held across: the stored
rate when `ct_funding` covers that settlement, else `FUNDING_FALLBACK`
(0.0001 per 8h). Positive funding is paid by longs to shorts. Funding
history starts the day the lab went live, so a replay before that runs on
the fallback throughout.

### The replay

```bash
cd backend && python -m app.labs.crypto_trend.replay --from 2026-03-28 --to 2026-09-10
```

```bash
cd backend && python -m app.labs.crypto_trend.replay --from ... --to ... --param STOP_ATR=3 --param ADX_MIN=25
```

```bash
cd backend && python -m app.labs.crypto_trend.replay --from ... --to ... --grid
```

`--param` overrides any `config.py` value for the run — the strategy's and
the engine's (`ADX_MIN`, `STRUCTURE_VETO_ATR`, the EMA periods) alike.
`--grid` runs every combination of the default grid (`STOP_ATR` 1.5/2/3 ×
`STRENGTH_MIN` 30/40/50 × `ADX_MIN` 20/25, 18 runs) or of the lists you
pass (`--grid STOP_ATR=1.5,2 ADX_MIN=20`), capped at 50, and prints one row
per combination sorted by expectancy, followed by the warning it deserves.

Each run writes `output/<run>/trades.csv`, `equity.csv`, `summary.json`
(the folder is git-ignored) and stores its window, parameters and summary
in `ct_replay_runs` (migration 0060) unless `--no-store`. The summary:
net P&L, return, max drawdown, trade count, win rate, average win and loss
in R, expectancy in R, profit factor, long and short breakdown, exposure,
average implied leverage, fees and funding, and P&L by exit reason.

**Hindsight-free by construction.** Every indicator is causal, so the state
on bar i computed over the whole series equals the state computed over
bars 0..i alone — `compute_trend_states` does one pass and a test holds the
identity bit for bit on every prefix. The replay steps through those
states, decides on a bar's close, fills at the next open. A test appends
future candles to a dataset and requires trades, equity curve and verdicts
to be unchanged.

**Two caveats that bound every number it prints.**

* *Survivorship.* The universe is the CURRENT top-20 for the whole window.
  A coin that has rallied its way into the top-20 since the window began
  is replayed as if it had always qualified; one that fell out is never
  seen. A trend-following result on such a universe is optimistic by
  construction, and nothing here corrects for it.
* *The 1h history bounds the window.* The verdict needs a 1h state, and
  1,000 hourly candles is about six weeks, so however far back the 4h
  history reaches, bars before that read `NEUTRAL` and enter nothing. A
  replay "over the full 4h history" trades the last five weeks of it.

### Out-of-sample: deep 1h history and frozen universes (Phase 3.1)

Two things made the first replay unreadable: the 1h history only reached
back six weeks, and the universe was today's. Both are fixed by one-off
commands; nothing changes in the tick.

**Deep 1h backfill.** `backfill --tf 1h --to-match 4h` pages forward from
each symbol's earliest stored 4h candle in 1,000-candle requests until it
meets the earliest stored 1h candle, upserting every page, so an
interrupted run resumes and a second run costs nothing (it reports each
symbol as `covered`). Requests go through the same weight budget as the
tick. Measured: 19 symbols, 2,999 candles each, in 18 seconds; the health
route then shows zero gaps on both timeframes.

**Frozen universe.** `universe snapshot --as-of DATE --name NAME` takes
today's top-60 from CoinGecko, applies the same exclusions, fetches each
coin's daily market-cap chart, ranks by the cap **on `DATE`**, keeps the
top 20 that have a Binance perp today, stores the list in
`ct_universe_snapshots` (migration 0061) and backfills both timeframes for
any symbol not yet stored. `replay --universe NAME` then runs on that list;
the summary's window block names the universe it used.

Three honest limits of the snapshot:

* **The public CoinGecko API serves at most 365 days of history**; `days=max`
  is a paid plan. `as_of` older than that is refused. The brief asked for
  `days=max`; this uses the smallest window that covers `as_of`.
* **The candidates are still today's top-60.** A coin that was top-20 on the
  date and has since fallen below 60th, or lost its Binance perp, is not
  in the snapshot. The survivorship residue is smaller than the live
  universe's, not zero.
* **CoinGecko's public rate limit is well under the documented 25 a minute**
  — measured on the day: 429 with a 30-second `Retry-After` on most calls.
  The source honours it, so a snapshot of ~50 coins takes about half an
  hour rather than two minutes. `COINGECKO_CALLS_PER_MINUTE` is the ceiling
  the source asks for; the 429s are what it gets.

**R on the risk actually taken.** Every trade records `intended_risk_usd`
(`RISK_PER_TRADE` × equity at the decision) and `risk_usd` (`qty` ×
`stop_distance` at fill); `pnl_r` divides by the latter. The summary's
`actual_risk_pct_of_intended` shows how often the notional cap bound.

**Correlation guard.** `MAX_NEW_ENTRIES_PER_BAR` (2) caps how many
positions one close can open, strongest first, so a broad rally cannot
fill the whole book on a single bar.

## The read interface — `data.py`

| Function | Returns |
|---|---|
| `get_universe(session)` | `list[Coin]`, by rank |
| `get_candles(session, symbol, timeframe, limit)` | `list[Candle]`, oldest first |
| `get_funding(session, symbol)` | `float \| None` — latest rate seen |
| `data_health(session, now=None)` | plain-JSON `dict` |
| `get_trend_state(session, symbol=None, timeframe=None)` | `list[TrendState]` — the latest per (symbol, timeframe) |
| `get_regime(session, limit=1)` | `list[Regime]`, newest first |
| `get_funding_history(session, symbols)` | every stored funding row for the replay |
| `get_universe_snapshot(session, name)` | a frozen universe by name, or None |

Every function takes the session, as every read in this repo does. Candles
come back as a list of frozen dataclasses with `Decimal` prices, not a
DataFrame — pandas is not a dependency here and this phase does not need it.

---

## Registration: the four existing files touched

Every touch is additive — `git diff --numstat` shows insertions only, and
the lint findings on each file are unchanged from before. Each is the same
line the Rafiq lab needed, and a test holds each one.

| File | Lines | What it does |
|---|---|---|
| `app/api/v1/router.py` | +3 | mounts the health route |
| `app/models/__init__.py` | +7 | imports the lab's models so `alembic/env.py` (which imports only `app.models`) can see them |
| `app/workers/celery_app.py` | +10 | the module in `include`, the `crypto-trend-lab-tick` entry in `beat_schedule` |
| `docker-compose.yml` | +1 | `CRYPTO_TREND_LAB_ENABLED` in the `x-backend-env` anchor, so the flag reaches the containers |

**Why the models import matters:** measured on a scratch database migrated
to 0057, `alembic check` *without* it reports `remove_table` for all four
`ct_*` tables — the next `alembic revision --autogenerate` would have
written a migration that drops them. With it, `alembic check` says nothing
about `ct_*` at all (verified the same way).

**Registration does not start anything.** The beat calls the task every
minute; with the flag down it returns before opening a session or a socket.
Setting the flag means restarting the worker and scheduler, as with every
flag here — and so does the registration itself: a Celery process running
from before these lines does not know the task exists until it restarts.

The migration is parented to `0056_rafiq_lab` on `karthik-hq`. On `main`
it would need renumbering and re-parenting, as the Rafiq lab's 0056 became
0063 there.

---

## Decisions worth knowing

* **A coin without a perp does not consume a slot.** The brief's order is
  "exclude, take 20, map, skip"; read literally, a top-20 with three
  untradeable entries would be a universe of 17. The lab takes the first 20
  that *map*, because a coin that cannot be traded cannot be one of the 20
  that are. Today's top-30 still yields 19: after eight stablecoins and LEO
  are excluded, three of the remaining 22 (a tokenised HELOC, RAIN, WBT)
  have no Binance perp. `UNIVERSE_FETCH` is one constant if 30 proves thin.
* **USDC has a Binance perp.** The exclusion list is applied *before* the
  perp check, and a test holds that order.
* **TON is `GRAMUSDT`.** CoinGecko's ticker for `the-open-network` is now
  `gram`, and Binance's contract matches it, so no override is needed today.
* **Thousand-unit contracts.** Binance quotes SHIB, PEPE, BONK and FLOKI as
  `1000…USDT`; their stored prices are ×1000 the coin's. The override map
  handles the symbol; a later phase that sizes a position must handle the
  scale.
* **Coins that are new to Binance have short histories.** Canton and
  Hyperliquid have far fewer than 1,000 4h candles; `count` in health shows it.
* **Removed coins keep their candles.** Only `ct_universe.removed_at` moves.
  `prune_candles` bounds every symbol's window, current or not.
* **No stored balance, no signal, no position.** Nothing here should acquire
  one in this phase.

## Tests

```bash
cd backend && pytest app/labs/crypto_trend/tests -q
```

203 pass. Phase 2 adds indicator tests against hand-computed values and
analytic identities, trend-state tests on synthetic uptrend, downtrend and
sideways series, regime tests for all three outcomes and their boundaries,
and route tests against a seeded database; Phase 2.1 adds the veto's
unit cases and four synthetic pullback scenarios (shallow, on the boundary,
deep, and deep-then-answered). Phase 3 adds every entry gate and exit rule,
the sizing maths and caps, hand-computed fee, slippage and funding
accounting, a three-coin synthetic replay whose every fill is reconciled
from first principles, and the hindsight test. Phase 3.1 adds backfill
paging against a fake exchange, snapshot ranking on fixed fixtures, the
actual-versus-intended risk maths, the per-bar entry cap and the
per-timeframe window. Phase 1's cover stablecoin
filtering, symbol mapping, the forming-candle cut, gap detection, retry and
backoff, weight tiers; integration tests (skipped without Postgres, run in
a rolled-back transaction) cover upsert idempotency for candles and funding,
re-ranking with removals and re-admissions, the no-request quiet minute,
per-symbol containment, the rolling window, run-history bounds and the
health report. All network is faked at the transport.

One test talks to Binance and is off unless asked:

```bash
cd backend && RUN_NETWORK_TESTS=1 pytest app/labs/crypto_trend/tests/test_network.py -q
```

The tests live inside the package, so the repo's default `pytest` (scoped to
`tests/`) is unchanged by this module's existence.

## Layout

```
app/labs/crypto_trend/
├── config.py       CRYPTO_TREND_LAB_ENABLED, sources, exclusion list, overrides, limits
├── models.py       ct_universe, ct_candles, ct_funding, ct_runs, ct_trend_state, ct_regime,
│                   ct_replay_runs, ct_universe_snapshots
├── universe.py     select_universe(): exclusions, mapping, the 20 — pure
├── candles.py      parse_klines(), find_gaps(), interval maths — pure
├── sources.py      CoinGecko + Binance over one httpx client; weight budget; backoff
├── service.py      one tick: universe, candles, funding, run record, pruning
├── data.py         get_universe / get_candles / get_funding / data_health / get_trend_state / get_regime
├── indicators.py   EMA, ATR, ADX, Donchian, swings — pure
├── trend.py        per-coin state, strength, verdict — pure
├── regime.py       market regime — pure
├── engine.py       runs trend + regime over the universe, upserts ct_trend_state / ct_regime
├── strategy.py     entries, sizing, exits — pure
├── sim.py          the replay account: fills at cost, funding, P&L — not the paper wallet
├── replay.py       the harness and its CLI; writes output/ and ct_replay_runs
├── snapshots.py    a universe frozen at a past date (ct_universe_snapshots)
├── output/         replay results, git-ignored
├── api.py          GET /labs/crypto-trend/health | /trend | /regime
├── scheduler.py    the beat task, and the engine task it enqueues
├── __main__.py     python -m app.labs.crypto_trend tick|run|health|trend|backfill|universe
└── tests/          203 tests; fakes.py holds the network stand-in and the synthetic series
alembic/versions/20260910_0057_crypto_trend_lab.py
alembic/versions/20260910_0058_crypto_trend_engine.py
alembic/versions/20260910_0059_crypto_trend_structure_veto.py
alembic/versions/20260910_0060_crypto_trend_replay_runs.py
alembic/versions/20260910_0061_crypto_trend_snapshots.py
```
