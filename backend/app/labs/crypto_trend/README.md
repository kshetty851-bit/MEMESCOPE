# Crypto Trend Lab — Phase 1: data layer

Market data for trend-following on the top-20 cryptocurrencies by market cap.
**This phase stores candles, funding and the universe. It generates no
signal, opens no position, and has no UI.**

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
   The newest 1,000 per symbol and timeframe are kept.
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

## The read interface — `data.py`

| Function | Returns |
|---|---|
| `get_universe(session)` | `list[Coin]`, by rank |
| `get_candles(session, symbol, timeframe, limit)` | `list[Candle]`, oldest first |
| `get_funding(session, symbol)` | `float \| None` — latest rate seen |
| `data_health(session, now=None)` | plain-JSON `dict` |

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

53 pass, including one that proves alembic can see the tables through
`app.models` and one that resolves the beat entry to a registered task. Unit tests cover stablecoin
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
├── models.py       ct_universe, ct_candles, ct_funding, ct_runs — on the platform Base
├── universe.py     select_universe(): exclusions, mapping, the 20 — pure
├── candles.py      parse_klines(), find_gaps(), interval maths — pure
├── sources.py      CoinGecko + Binance over one httpx client; weight budget; backoff
├── service.py      one tick: universe, candles, funding, run record, pruning
├── data.py         get_universe / get_candles / get_funding / data_health
├── api.py          GET /labs/crypto-trend/health
├── scheduler.py    the Celery task (unregistered until the beat lines land)
├── __main__.py     python -m app.labs.crypto_trend tick|run|health
└── tests/          53 tests; fakes.py is the network stand-in
alembic/versions/20260910_0057_crypto_trend_lab.py
```
