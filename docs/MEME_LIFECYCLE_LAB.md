# Meme Lifecycle Lab — Phase 1–4 design

Status: **approved 2026-10-03**, Phase 1–4 only. No strategy expansion until the
Phase 1–4 review.

The Lab is a *measurement* system before it is a strategy system. Its job is to
find out whether a meme that already exists on the internet, experiencing a
measurable new attention wave with market confirmation, carries information
MEMESCOPE's market signals do not — and to be able to prove that wrong.

## Hard rules

1. **Absence is never zero.** Every collection attempt is a `mll_collection_runs`
   row. A source that did not answer yields `Unavailable(reason)`, never `0`.
2. **One gate.** `pit.information_available_at(...)` is the only place data is
   admitted to a decision. Every engine downstream takes an `InformationState`.
3. **Three timestamps.** `source_timestamp`, `observed_at`, `retrieved_at` — see
   `app/lifecycle_lab/domain.py`. FORWARD data is visible at `T` iff
   `retrieved_at <= T`.
4. **Two data classes, two modes.** `FORWARD` (collected prospectively) and
   `BACKFILL` (fetched about the past). `AUTHORITATIVE` mode admits FORWARD only
   and is the only verdict-grade mode. `EXPLORATORY` admits BACKFILL at
   `source_timestamp + PUBLICATION_LAG[source]`, except accumulating metrics
   (engagement, cumulative replies), which are never visible before their
   `retrieved_at`. Every exploratory output is labelled.
5. **Links are facts with a time.** A meme↔token link is visible only after its
   `linked_at`. EXPLORATORY mode may set `hindsight_links=True`; every output
   produced that way is stamped `HINDSIGHT` and AUTHORITATIVE mode refuses it.
6. **Raw observations are truth; features are derived.** Attention/market
   features and events are recomputed from raw rows during replay. Stored events
   carry `detector_version` and are reproducible.
7. **Pure engines.** `domain, pit, linking, attention, market, events, states,
   divergence, timeliness, exits, portfolio, strategy, experiments, replay,
   metrics, config` do no I/O, hold no clock, use no randomness. AST test.
8. **Never trades.** `REAL_TRADING = False` is a constant. The package may not
   import `app.real_wallet*`, `solders`, or any execution module. Test-enforced.
9. **No recommendations.** Reason codes describe observations. No buy/sell/hold
   wording in any user-facing string.

## Package layout — `backend/app/lifecycle_lab/`

| Module | Pure | Purpose |
|---|---|---|
| `domain.py` | ✓ | Shared types (written first; the contract) |
| `config.py` | ✓ | `LabConfig` dataclass: portfolio + thresholds, all defaults |
| `pit.py` | ✓ | `information_available_at(...)` |
| `linking.py` | ✓ | Deterministic meme↔token matcher (EXACT_NAME/SYMBOL, ALIAS, WEBSITE, SOCIAL_LINK) |
| `attention.py` | ✓ | `attention_features(state) -> AttentionFeatures` |
| `market.py` | ✓ | `market_features(state, mint) -> MarketFeatures`, age buckets |
| `events.py` | ✓ | `detect_events(history, state, ...) -> list[MemeEvent]`, wave counting |
| `states.py` | ✓ | `classify_state(...) -> LifecycleState` |
| `divergence.py` | ✓ | `classify_divergence(attn, mkt) -> DivergenceCase` |
| `timeliness.py` | ✓ | `timeliness(event, market_points) -> Timeliness` |
| `exits.py` | ✓ | TP / SL / trailing / max-hold / attention-collapse / volume-collapse |
| `portfolio.py` | ✓ | $1,000 ledger: $10 size, 5 open, $50 deployed |
| `strategy.py` | ✓ | Baseline strategy + control-arm architecture (A–D) |
| `experiments.py` | ✓ | 70/15/15 chronological split, spec hash, sample-size labels, multiple-testing counter |
| `replay.py` | ✓ | Drives decision times → PIT → features → events → strategy → portfolio |
| `metrics.py` | ✓ | Trade stats, percentiles, top-N contribution, streaks |
| `adapters/` | I/O | One adapter per source, common protocol |
| `collector.py` | I/O | Runs adapters, records runs, writes observations |
| `repository.py` | I/O | All SQL; maps rows ↔ domain types |
| `service.py` | I/O | Orchestration: load → pure replay → persist |
| `scheduler.py` | I/O | Celery tasks (collection, linking, forward replay) |
| `schemas.py`, `api.py` | I/O | HTTP, `/api/v1/lifecycle-lab` |

ORM tables live in `backend/app/models/lifecycle_lab.py` (repo convention).

## Data flow

```
 Source (pump.fun poller · Wikipedia · GDELT · DexScreener · GeckoTerminal · [Reddit] · [X])
   │      disabled / unauthorised sources still produce a run row: DISABLED / UNAVAILABLE
   ▼
 Adapter (adapters/*.py)  ── fetch(subjects, now) → AdapterResult(status, reason, observations)
   ▼
 Collector  ── mll_collection_runs (every attempt)  +  mll_attention_observations (ON CONFLICT DO NOTHING)
   │           pump.fun replies are READ from pumpfun_social_snapshots, not copied
   │           GeckoTerminal OHLCV → token_market_candles (BACKFILL)
   │           market FORWARD → token_market_snapshots (existing enrichment; protected from retention)
   ▼
 Timestamp / provenance  (source_timestamp · observed_at · retrieved_at · data_class · source_url · confidence)
   ▼
 information_available_at(T, mode)  → InformationState   ← the only gate
   ▼
 Attention engine (attention.py, market.py)  → AttentionFeatures, MarketFeatures  (Unavailable ≠ 0)
   ▼
 Event engine (events.py, states.py, divergence.py)  → MemeEvent, LifecycleState, DivergenceCase
   ▼
 Point-in-time replay (replay.py)  — decision times in order; strategy sees only InformationState
   ▼
 Paper portfolio (portfolio.py, exits.py)  → trades with entry reason + evidence timeline
   ▼
 Research report (metrics.py, timeliness.py)  → mll_backtest_runs.summary, mll_meme_events outcomes
```

## Tables (migration `0112_meme_lifecycle_lab`)

| Table | Key / idempotency |
|---|---|
| `mll_memes` | unique `slug` |
| `mll_meme_aliases` | unique `(meme_id, alias_normalized, kind)` |
| `mll_meme_tokens` | unique `(meme_id, mint_address)`; `linked_at` write-once |
| `mll_collection_runs` | uuid; index `(source, finished_at desc)`, `(meme_id, source, finished_at)` |
| `mll_attention_observations` | unique `dedupe_key`; index `(meme_id, retrieved_at)`, `(mint_address, retrieved_at)`, `(source, observed_at)` |
| `mll_meme_events` | unique `(meme_id, event_type, detected_at, detector_version, mode, coalesce(mint,''))` |
| `mll_experiments` | unique `experiment_key`; `spec_hash` |
| `mll_backtest_runs` | uuid; FK experiment |
| `mll_paper_trades` | unique `(backtest_run_id, mint_address, entry_at)` |
| `mll_portfolio_snapshots` | unique `(backtest_run_id, at)` |

Also in 0112: `token_market_candles_1h` (empty; no reader or writer since 0038)
is renamed `token_market_candles` and gains `resolution_s` (default 3600),
`source` (default `'derived'`), `data_class` (default `'forward'`),
`retrieved_at`, and the PK becomes `(mint_address, resolution_s, source, bucket)`.
Existing rows, if any, keep their meaning (hourly, derived).

Retention: `_prune_market_snapshots` and the pump.fun social prune protect
mints with a current `mll_meme_tokens` link. Enrichment: currently linked mints
of tracked memes (bounded by `MLL_MAX_TRACKED_TOKENS`) refresh at least every
`MLL_MARKET_INTERVAL_SECONDS` through the existing scheduler — not a new market
system.

## Settings (all in the `x-backend-env` anchor)

`FEATURE_LIFECYCLE_LAB_ENABLED=false`, `MLL_WIKIPEDIA_ENABLED`, `MLL_GDELT_ENABLED`,
`MLL_DEXSCREENER_ENABLED`, `MLL_GECKOTERMINAL_BACKFILL_ENABLED`,
`MLL_PUMPFUN_REPLIES_ENABLED`, `MLL_REDDIT_ENABLED=false`, `MLL_X_ENABLED=false`,
`MLL_REDDIT_CLIENT_ID/SECRET/USER_AGENT` (empty), `MLL_X_BEARER_TOKEN` (empty),
`MLL_MAX_TRACKED_TOKENS=200`, `MLL_MARKET_INTERVAL_SECONDS=300`,
`MLL_FORWARD_START` (ISO date; the authoritative epoch).
Portfolio/threshold defaults live in `config.py` and are recorded into each
experiment's spec, so a run is reproducible from its row alone.

## API — `/api/v1/lifecycle-lab`

| Method | Path | |
|---|---|---|
| GET | `/overview` | portfolio KPIs (latest authoritative forward run), forward start, source health summary |
| GET | `/health` | per-source status, last run, reason, data class |
| GET | `/memes` | radar rows |
| GET | `/memes/{slug}` | identity, aliases, links, series (attention / price / volume), events, trades |
| GET | `/experiments` | registry rows with split boundaries and status |
| GET | `/runs/{id}` | run summary, metrics, trades, equity curve |
| POST | `/memes` (admin) | create meme + aliases (manual curation) |
| POST | `/memes/{slug}/links` (admin) | manual link; `linked_at` = server now, never client-supplied |

## Storage estimate (200 tracked memes, ~400 linked tokens)

| Data | Rows / month | ≈ Size / month |
|---|---|---|
| GDELT 15-min buckets | ~580k | ~250 MB |
| Wikipedia daily | ~6k | ~3 MB |
| DexScreener profile (daily per token) | ~12k | ~15 MB |
| Collection runs | ~150k | ~40 MB |
| Protected market snapshots @ 5 min, 400 tokens | ~3.5M | ~1.5 GB |
| GeckoTerminal backfill (one-off, 2×1000 bars/token) | ~800k once | ~200 MB once |
| pump.fun replies | 0 new (read in place; retention extended for linked mints) | small |

The protected market snapshots dominate. `MLL_MAX_TRACKED_TOKENS` and
`MLL_MARKET_INTERVAL_SECONDS` are the levers.

## Cost

$0 recurring at launch. Wikipedia, GDELT, DexScreener and GeckoTerminal are free
(rate-limited); pump.fun replies are already collected. Reddit and X adapters
exist and report `DISABLED` until authorised access is configured.

## Known limits at launch

* Wikipedia per-article pageviews are **daily** — footprint and baseline, not a
  fast signal. Hourly views exist only as bulk dumps (not used).
* GDELT is news, not social. Recent buckets are revised as GDELT ingests; the
  first-written value is what was known then, and is what we keep.
* pump.fun replies cover only coins in the poller's top-100 listings; a linked
  coin outside them is UNAVAILABLE for that poll, not zero.
* Bonding-curve liquidity is null (ADR 0002): costs fall back to a flat,
  configurable slippage and the trade is flagged `cost_model=flat`.
* Unique participants and engagement have no source until Reddit/X: they are
  `Unavailable("no_source")` everywhere.
* No train/validation/test split is meaningful until enough forward data
  exists; experiments say so.

## API response contract (Phase 1–4)

Money, prices and ratios are JSON **strings** (Decimal) or `null`. A derived
value that could not be computed is a `Measured` object, never `0`:

```jsonc
// Measured
{ "value": "4.7" | null, "unavailable_reason": "no_source" | null }

// SourceHealth
{ "source": "gdelt", "label": "GDELT (news)",
  "status": "available|unavailable|disabled|error|stale|partial|never_collected",
  "reason": "disabled_by_config" | null, "last_run_at": iso | null,
  "data_class": "forward|backfill", "observations_24h": 12 | null }
```

`GET /overview`
```jsonc
{ "lab_enabled": true, "real_trading": false, "mode": "authoritative",
  "forward_start": iso | null, "forward_days": 3.5 | null,
  "portfolio": { "run_id": str | null, "as_of": iso | null, "starting_capital": "1000",
    "equity": str|null, "cash": str|null, "deployed": str|null, "realized_pnl": str|null,
    "unrealized_pnl": str|null, "roi": str|null, "drawdown": str|null,
    "trades": 0, "open_positions": 0, "sample_label": "insufficient (<25)",
    "unavailable_reason": "no_forward_run_yet" | null },
  "experiment": { "experiment_key": str, "split_meaningful": false, "split_note": str,
    "train": [iso, iso], "validation": [iso, iso], "test": [iso, iso] } | null,
  "sources": [SourceHealth], "tracked_memes": 0, "linked_tokens": 0,
  "notes": ["Only forward data collected since <forward_start> counts toward the verdict."] }
```

`GET /health` → `{ "generated_at": iso, "sources": [SourceHealth] }`

`GET /memes` → `{ "generated_at": iso, "items": [MemeRow] }`
```jsonc
// MemeRow
{ "slug": "frogceo", "display_name": "FROGCEO",
  "tokens": [{ "mint": str, "symbol": str|null, "name": str|null, "link_method": "manual",
               "confidence": "0.8", "linked_at": iso }],
  "primary_mint": str | null, "token_age_seconds": 345600 | null, "age_bucket": "3-7d",
  "market_cap": str|null, "liquidity_usd": str|null, "volume_1h": str|null,
  "price_change_1h": str|null,
  "attention": { "mentions_1h": Measured, "mentions_24h": Measured, "velocity": Measured,
                 "acceleration": Measured, "baseline_multiple": Measured,
                 "platform_count": Measured },
  "lifecycle_state": "reviving", "market_activity": Measured,   // volume_growth
  "data_freshness_seconds": 120 | null, "paper_status": "none|open|closed",
  "contains_backfill": false }
```

`GET /memes/{slug}`
```jsonc
{ "meme": { "slug", "display_name", "description", "tracking_started_at",
            "wikipedia_title", "gdelt_query" },
  "aliases": [{ "alias", "kind", "added_at" }],
  "links": [{ "mint", "method", "confidence", "linked_at", "unlinked_at" }],
  "series": {                                   // hourly buckets, ascending
    "attention": [{ "t": iso, "value": str|null }],   // null = unavailable, not 0
    "price":     [{ "t": iso, "value": str|null }],
    "volume":    [{ "t": iso, "value": str|null }],
    "per_source": { "gdelt": [{ "t", "value" }], ... },
    "backfill_before": iso | null },            // points before this are exploratory
  "markers": [{ "t": iso, "kind": "attention_spike|revival|wave|paper_entry|paper_exit|token_launch|...",
                "label": str, "event_type": str|null, "mint": str|null }],
  "events": [{ "event_type", "detected_at", "mint", "divergence_case", "lifecycle_state",
               "mode", "contains_backfill", "returns": { "5m": Measured, ..., "24h": Measured },
               "price_at_detection": str|null, "run_up_before_detection": Measured }],
  "trades": [{ "trade_key", "mint", "entry_at", "entry_price", "size_usd", "exit_at",
               "exit_price", "exit_reason", "pnl_usd", "return_pct", "status",
               "entry_reason", "evidence_timeline": [{ "at", "kind", "detail" }] }],
  "data_label": "authoritative|exploratory", "contains_backfill": bool,
  "sources": [SourceHealth] }
```

`GET /experiments` → `{ "items": [{ "experiment_key", "hypothesis", "arm", "mode",
"spec_hash", "created_at", "data_cutoff", "train", "validation", "test",
"split_meaningful", "split_note", "status" }] }`

`GET /runs/{id}` → `{ "run": {...}, "metrics": {...}, "snapshots": [...], "trades": [...] }`

---

# Validation phase (2026-10-03)

Goal: move from "the Lab passes tests" to "the Lab collects trustworthy forward
data continuously and replays it incrementally". No new strategies, no tuning.

## DEV STARTUP

Everything below was checked against the code on 2026-10-03 and is held by
`backend/tests/unit/test_mll_wiring.py` (tasks registered, beat cadences, flag
gating, routes, Reddit/X off, compose anchor). The Lab ships **dark**: nothing
collects until the flag below is set, and setting it is the only switch.

### Required environment variables

Set in `.env` (docker compose reads it); every one is already forwarded to all
services through the `x-backend-env` anchor in `docker-compose.yml`, so one
value reaches the API, the worker and beat alike.

| Variable | Default | Needed | Meaning |
|---|---|---|---|
| `FEATURE_LIFECYCLE_LAB_ENABLED` | `false` | **yes, `true`** | Master switch. Off: every task returns `{"skipped": "lab_disabled"}` before opening a session, every source reports `DISABLED`, `/overview` says `lab_enabled: false`. |
| `MLL_FORWARD_START` | empty | **yes, today's date** (`2026-10-03`) | ISO date of the authoritative forward epoch. Empty = no FORWARD observation counts toward a verdict. Set once; moving it later throws data away. |
| `MLL_WIKIPEDIA_ENABLED` / `MLL_GDELT_ENABLED` / `MLL_DEXSCREENER_ENABLED` / `MLL_GECKOTERMINAL_BACKFILL_ENABLED` | `true` | no | Per-source switches; act only while the Lab flag is on. A switched-off source writes a `DISABLED` run, never a zero. |
| `MLL_PUMPFUN_REPLIES_ENABLED` | `true` | no | Gates only the pump.fun replies **health probe**. Also needs `FEATURE_PUMPFUN_SOCIAL_ENABLED=true` (default `false`), which is the poller that actually collects replies. Without it the source is `DISABLED: pumpfun_social_disabled`. |
| `MLL_REDDIT_ENABLED`, `MLL_REDDIT_CLIENT_ID`, `MLL_REDDIT_CLIENT_SECRET`, `MLL_REDDIT_USER_AGENT` | `false`, empty | **leave unset** | Reddit turns on only when the switch **and** all three credentials are present (official OAuth; no scraping). |
| `MLL_X_ENABLED`, `MLL_X_BEARER_TOKEN` | `false`, empty | **leave unset** | X has no implementation: even with both set it reports `DISABLED: not_implemented_no_api_plan`. |
| `MLL_MAX_TRACKED_TOKENS` | `200` | no | Cap on linked mints refreshed on the fast market cadence. |
| `MLL_MARKET_INTERVAL_SECONDS` | `300` | no | Refresh interval for those mints. |
| `MLL_EXPERIMENT_HORIZON_DAYS` | `90` | no | Span of the pre-registered baseline experiment, from `MLL_FORWARD_START`. Split boundaries are fixed when first registered. |
| `MLL_AUTOLINK_MIN_CONFIDENCE` | `"0.8"` | no | Autolinker floor: website / social-handle matches only. Name and ticker collisions need manual curation. |
| `MLL_WIKIPEDIA_USER_AGENT` | descriptive UA | no | Wikimedia throttles generic UAs; put real contact details here. |
| `MLL_GDELT_MIN_INTERVAL_SECONDS` | `6` | no | Spacing between GDELT requests (GDELT asks for one per ~5s). |

Minimum to start collecting:

```bash
# .env
FEATURE_LIFECYCLE_LAB_ENABLED=true
MLL_FORWARD_START=2026-10-03          # the day collection starts, ISO date
# optional, to get the pump.fun replies source going
FEATURE_PUMPFUN_SOCIAL_ENABLED=true
```

Flags are read at process start: **recreate** the services after changing them
(`docker compose up -d --force-recreate backend worker scheduler`). The API
auto-reloads source, but not environment; the worker and beat reload neither.

### Required migration

`0112_meme_lifecycle_lab` (alembic head at the time of writing). The backend
container applies it on start (`RUN_MIGRATIONS`); otherwise `make migrate`.
Verify: `docker compose exec -T backend alembic current` shows the head, and
`\dt mll_*` lists ten tables. If another migration lands after it, the head
moves but 0112 must stay an ancestor (test-enforced). `make migration-check`
must stay clean.

### Required Celery workers

Lab tasks have no queue routing, so they run on the **default queue**, consumed
by the compose service **`worker`** (`celery -A app.workers.celery_app worker
--concurrency=2`). `worker-paper` consumes only `graduation_paper` and will
never see them. The module `app.lifecycle_lab.scheduler` is listed in the Celery
`include`, so the worker registers all seven tasks on start.

The market side of a linked token (price, liquidity, volume) comes from the
existing enrichment services (`enrichment`, `enrichment-fast`; they need
`FEATURE_ENRICHMENT_ENABLED=true`), not from a Lab-specific poller; the Lab
protects linked mints from retention and nominates them for refresh. pump.fun
replies need the existing `app.pumpfun.social_scheduler` beat entries
(`FEATURE_PUMPFUN_SOCIAL_ENABLED`).

### Required Celery beat

Compose service **`scheduler`** (`celery -A app.workers.celery_app beat`). The
Lab's six entries are declared in `backend/app/workers/celery_app.py` and are
inert while the flag is off (each task checks the flag before opening a
session), so they are always registered:

| Beat entry | Task | Cadence (UTC minutes) |
|---|---|---|
| `lifecycle-collect` | `lifecycle_collect_tick` | every 15 min at :01 :16 :31 :46 |
| `lifecycle-detect-events` | `lifecycle_detect_events_tick` | every 5 min (:00, :05, ...) |
| `lifecycle-timeliness` | `lifecycle_timeliness_tick` | every 15 min at :04 :19 :34 :49 |
| `lifecycle-forward-replay` | `lifecycle_forward_replay_tick` | :11 and :41 |
| `lifecycle-autolink` | `lifecycle_autolink_tick` | hourly at :23 |
| `lifecycle-experiment` | `lifecycle_experiment_tick` | hourly at :07 |
| *(none; admin POST)* | `lifecycle_backfill` | on demand, EXPLORATORY only |

Beat keeps its schedule shelve in `/tmp`, so a restart picks up new entries.

### How to verify collection

1. **Tasks reach the worker.** `docker compose logs worker | grep lifecycle`
   shows `lifecycle_collect ...` lines every 15 minutes. `skipped: lab_disabled`
   means the flag did not reach that container.
2. **Run rows exist, one per attempt** (the Lab's rule 1: absence is never zero):

   ```sql
   SELECT source, status, reason, count(*), max(finished_at)
   FROM mll_collection_runs
   WHERE finished_at > now() - interval '1 hour'
   GROUP BY 1, 2, 3 ORDER BY 1, 2;
   ```

   Expected with no memes seeded: `unavailable / no_subjects` for Wikipedia,
   GDELT, DexScreener; `disabled / disabled_by_config` for Reddit and X;
   `disabled / pumpfun_social_disabled` (or `available` / `stale` /
   `unavailable: poller_never_ran` once the poller is on) for pump.fun. After
   seeding, per-meme rows appear (`meme_id IS NOT NULL`) with real outcomes.
3. **Observations land, and none are fabricated:**

   ```sql
   SELECT source, metric, data_class, count(*), min(retrieved_at), max(retrieved_at)
   FROM mll_attention_observations GROUP BY 1, 2, 3 ORDER BY 1, 2;
   ```

4. **API** (reads are public; no cookie unless `ALPHA_ACCESS_REQUIRED=true`, in
   which case send the alpha cookie):

   ```bash
   B=http://localhost:8000/api/v1/lifecycle-lab
   curl -s $B/overview        | jq '{lab_enabled, forward_start, forward_days, sources: [.sources[] | {source, status, reason}]}'
   curl -s $B/health          | jq '.sources[] | {source, status, reason, last_run_at, observations_24h}'
   curl -s $B/memes           | jq '.items[] | {slug, attention: .attention.mentions_24h}'
   ```

   A source that has not answered shows `status: error|unavailable|stale` with a
   `reason`, and a meme's attention shows `value: null` with an
   `unavailable_reason` - never `"0"`.

### How to verify data health

* `GET $B/quality` - forward vs backfill observations today / this week,
  per-source success rates (DISABLED is excluded from both sides of the rate),
  `unavailable_sources`, `stale_sources`, memes without observations, linked
  tokens without market history or with missing fields.
* `GET $B/memes/{slug}/quality` - per-meme audit trail: each link's
  `linked_by` and evidence, per-source first/latest observation and
  forward/backfill counts, collection priority.
* `GET $B/research-status` - `NOT_STARTED` while `MLL_FORWARD_START` is unset
  or in the future or the flag is off, then `COLLECTING` (first 7 days) and
  `INSUFFICIENT_DATA`; `verdict` is `UNCERTAIN` throughout.
* Healthy dev state on a machine that can reach the sources: Wikipedia and
  DexScreener `available`, GDELT `available` or `partial` (rate limits), Reddit
  and X `disabled`, `contains_backfill: false` on every meme row.
* If the sources are unreachable (a sandbox or egress policy), expect
  `error / network_error` for Wikipedia, GDELT and DexScreener, `0`
  observations, and `value: null` everywhere. That is a truthful board, not a
  bug; do not relax anything to make it look populated.

## SEEDING THE FIRST MEMES

The registry starts empty and an empty board is a truthful board. Memes are
curated by hand; token links are curated by hand **with evidence**. Nothing in
this procedure is automated past the point of identity, because a false link
contaminates every attention and market feature built on it and the permanent
record cannot be edited.

Tooling: `backend/scripts/mll_seed.py` (an API client for the admin endpoints)
and `docs/lifecycle_lab_seed.example.json` (15 candidate existing internet
memes, **no token links**). Held by `backend/tests/unit/test_mll_seed.py`.

### What the script does and refuses

```bash
export MLL_ADMIN_TOKEN=<admin access token>     # POST /api/v1/auth/login -> access_token
python backend/scripts/mll_seed.py --dry-run docs/my_seed.json            # plan only
python backend/scripts/mll_seed.py --base-url http://localhost:8000 docs/my_seed.json
```

Run it inside the stack with `docker compose exec -T -e MLL_ADMIN_TOKEN backend
python scripts/mll_seed.py ...` (the seed file must be under `./backend`, which
is bind-mounted), or on any host with `httpx`.

* Calls only the existing admin API: `POST /memes` (meme + aliases in one
  request), `POST /memes/{slug}/aliases` (new aliases on an existing meme),
  `POST /memes/{slug}/links`. Every timestamp (`tracking_started_at`,
  `added_at`, `linked_at`) is the **server's clock**; the script never sends
  `linked_at`, and a seed entry that carries one is refused, not dropped.
* **Idempotent.** It reads `GET /memes/{slug}` first and skips any meme, alias
  or link that exists; an existing meme's description and queries are never
  rewritten. Re-running after adding a link only adds that link.
* `--dry-run` prints the plan and never writes (it reads the registry if the
  server is reachable, otherwise plans everything as new).
* **Validates the whole file before sending anything**; one defect aborts the
  run with every problem listed (exit 2).
* **Refuses a link** unless it carries an `evidence_url` (an http(s) page
  showing the match). `exact_symbol`, `exact_name` and `alias_match` are
  refused outright: a ticker or a name is never sufficient, because thousands
  of tokens share one. Accepted methods:
  * `manual` - needs `evidence_url` and an `evidence_note` saying how identity
    was verified;
  * `website_match` / `social_link_match` - need `evidence_url` and `matched`
    (the website URL / social handle that matched on both sides).
* `TO_VERIFY` is a placeholder, not data: a placeholder alias is skipped, and a
  link whose `mint` is `TO_VERIFY` is reported as `pending` and never sent. A
  real mint with a placeholder or missing evidence is an error.

**Known limit.** The admin link endpoint accepts only `mint` and `confidence`
and stores the link as `manual`, recording the admin as `linked_by`. The
evidence is therefore validated by the script but kept in the seed file, not in
the database. Commit the seed file (without the token): it is the audit trail
for why each link exists.

### Procedure (per meme)

1. **Verify the meme's identity.** Confirm it is a meme that existed on the
   internet *before* any token: open the Wikipedia article and check the exact
   title (the example titles are from memory and must be checked; a wrong title
   is reported honestly as `UNAVAILABLE`, never as zero). Record the canonical
   website and social handles from the meme's own pages, not from a token's
   claims. Pick a `gdelt_query` precise enough to avoid homonyms (quoted
   phrase; `OR` for variants).
2. **Write the meme and its aliases** in the seed file: `name`, `phrase`,
   `hashtag`, `wiki_title`, and, once verified, `domain` and `social_handle`.
   Avoid `symbol` aliases and generic words: aliases feed Reddit and linking
   queries, and a noisy alias is a noisy feature. Run `--dry-run`, then the
   real run. The meme now appears in `/lifecycle-lab/memes` with
   `value: null` attention until sources answer.
3. **Find candidate tokens** on DexScreener (search the name, open the Solana
   pairs). A candidate is a *lead*, not a link: record the mint, the pair URL,
   the token's website and social links.
4. **Verify the candidate through a cross-reference, not a name.** The token's
   website or social account must point at the meme's canonical website or
   account **and** that canonical page must point back at the token (or the
   same operator controls both), ideally confirmed on-chain (metadata URI,
   creator wallet, pump.fun page). The ticker matching is never part of the
   evidence: copy-cat tokens share tickers by design.
5. **Add the link with confidence and evidence.** In the meme's `links` list:

   ```json
   { "mint": "<verified address>", "method": "manual", "confidence": "0.9",
     "evidence_url": "https://<page that shows the match>",
     "evidence_note": "Token site links @canonical_handle; that account's pinned post links this mint." }
   ```

   Use `website_match` / `social_link_match` with `matched` when the evidence
   is exactly that. Choose confidence honestly (the autolinker admits only
   >= 0.8); an unverifiable candidate gets no link at all.
6. **Re-run the script.** Only the new link is sent; `linked_at` is now. From
   that instant the link is visible to the Lab, and never before: a link cannot
   be backdated to look as if it were known at an earlier pump.

Never type a mint address from memory. If DexScreener is unreachable, stop;
leave the slot `TO_VERIFY`.

### First-run checklist

1. `FEATURE_LIFECYCLE_LAB_ENABLED=true` and `MLL_FORWARD_START` set (DEV STARTUP).
2. Copy the example, fix the Wikipedia titles, run `--dry-run`, then the seed.
3. Wait for one collection tick (`:01 :16 :31 :46`); check
   `mll_collection_runs` and `/health`.
4. Add links one meme at a time, verified as above.

## LIVE SOURCE STATUS

**Live validation is blocked by this environment's network policy (2026-10-03).**
No source in the table below has been observed answering from this codebase.

| Source | Live status | What was attempted |
|---|---|---|
| GDELT DOC 2.0 | **not verified** | One request through `GdeltAdapter`; the egress proxy answered 403 for `api.gdeltproject.org`, httpx raised `ProxyError`, the adapter recorded `ERROR network_error`. No further live requests were made. |
| Wikipedia (Wikimedia REST) | **not verified** | Not attempted: `wikimedia.org` is blocked by the same policy. |
| DexScreener | **not verified** | Not attempted: `api.dexscreener.com` is blocked. |
| pump.fun replies | n/a (no network) | The adapter is a freshness probe over `pumpfun_social_snapshots`; the poller itself needs `frontend-api-v3.pump.fun`, also blocked here. |

Everything the adapters assume about live responses is therefore labelled
**UNVERIFIED — from documentation/memory** in code comments and below. The
tests use `httpx.MockTransport` only. GDELT failure fixtures are SYNTHETIC
(`backend/tests/fixtures/lifecycle_lab/gdelt/synthetic_*`); no success-shape
fixture has been captured, and the live-shape tests skip with
"live GDELT fixture not captured: network blocked in CI container".

**How to validate** (from a host with outbound access):

```bash
docker compose exec -T backend python scripts/mll_validate_sources.py --dry-run   # prints the requests, sends nothing
docker compose exec -T backend python scripts/mll_validate_sources.py             # ONE request per enabled source
```

The script uses the real adapters (Lab flag forced on in-process only; each
`MLL_*_ENABLED` switch honoured) and prints, per source: HTTP status,
content-type, top-level keys, and the adapter's parsed status / reason / per-
subject detail / detected `bucket_seconds`. pump.fun freshness is read from the
database if reachable. Options: `--name`, `--gdelt-query`, `--wikipedia-title`,
`--mint`, `--no-fixture`.

The GDELT request asks for the scheduler's maximum span (24 h) so the
15-minute-resolution assumption is tested where it is most likely to break.
Only an HTTP 200 JSON-object answer is written to
`backend/tests/fixtures/lifecycle_lab/gdelt/live_timelinevolraw.json`
(status, header subset, verbatim body, url, query, `retrieved_at`) — a
throttle page or an error is never saved as the success shape. Commit the file;
`tests/unit/test_mll_gdelt.py::test_live_fixture_*` then run against it. If
they fail, the documented assumptions were wrong: fix the adapter and this
section, never the fixture.

## GDELT API BEHAVIOUR

Code: `backend/app/lifecycle_lab/adapters/gdelt.py`. Tests:
`tests/unit/test_mll_gdelt.py`, `tests/unit/test_mll_adapters.py`. Status of
every claim: **what we send** is verified by tests; **how GDELT answers** is
UNVERIFIED — from documentation/memory (see LIVE SOURCE STATUS).

**Request.** `GET https://api.gdeltproject.org/api/v2/doc/doc` with
`query`, `mode=timelinevolraw` (raw article counts — `timelinevol` is a share
of coverage, not a count), `format=json`, and either `timespan=<N>h` (forward)
or `startdatetime`/`enddatetime` `YYYYMMDDHHMMSS` (backfill).

**Query construction** (verified: this is what we send).

* `meme.gdelt_query` verbatim when curated (operators such as
  `sourcelang:eng` are the curator's choice); otherwise the display name as one
  quoted phrase, inner `"` removed: `"Frog CEO"`.
* **Aliases are not OR'd in.** A timeline is one series for the whole query and
  cannot say which OR'd term matched — OR-ing would merge two populations into
  one count.
* **Batching memes into one request is impossible** for the same reason: the
  answer cannot be attributed back to per-meme counts.
* **Identical query strings are shared** within a pass: one request, the
  timeline fanned out to every meme with that query, each getting its own rows
  (own `meme_id`, so distinct dedupe keys). The run detail records
  `requests`, `subjects`, `shared_queries`.

**Response classification** (shapes UNVERIFIED; classification test-pinned
against SYNTHETIC fixtures). GDELT is known to answer throttling and query
errors with **HTTP 200 and a plain-text body**, not JSON and not 4xx.

| Answer | Run status / reason |
|---|---|
| JSON object with a timeline | AVAILABLE (closed buckets only) |
| empty body, `{}`, missing / empty `timeline` | UNAVAILABLE `no_data_for_window` — nothing returned is not a count of 0 |
| one point only | UNAVAILABLE `bucket_size_unknown` |
| text mentioning a request limit ("Please limit requests to one every 5 seconds…") | ERROR `rate_limited` — **stops the run** like a 429 |
| any other non-JSON text (phrase too short, invalid query, HTML) | ERROR `gdelt_query_error`; first 200 chars in that meme's run `detail.body_head` — the run continues with other queries |
| body that starts like JSON but does not parse | ERROR `unparseable` |
| HTTP 429 | ERROR `rate_limited` (stops the run) |
| HTTP ≥ 500, or any other non-2xx | ERROR `http_<code>` |
| timeout / transport failure | ERROR `timeout` / `network_error` |
| uneven spacing | ERROR `irregular_buckets` |
| FORWARD bucket width ≠ 15 min | ERROR `unexpected_bucket_size` (`detail.bucket_seconds`) |

The "limit" heuristic needs both *limit* and *request* (or "rate limit" /
"too many requests"), so a query error that merely mentions a length limit
does not halt the whole pass.

**Timestamp semantics** (UNVERIFIED — from documentation/memory). `date` is
treated as the bucket **start** (`bucket_window`): `source_timestamp =
window_start = date`, `observed_at = window_end = date + width`,
`retrieved_at = now`. Only buckets with `window_end <= now` are written. If
`date` is really the end, every row is visible one bucket later than it could
have been — a timeliness cost, never look-ahead. Pinned by
`test_date_labels_the_bucket_start_unverified`.

**Resolution.** Width is detected from the timestamps, never assumed. FORWARD
runs additionally require exactly 15 minutes: an hourly answer mixed into a
15-minute series would be double-counted by the attention engine, so it is
refused loudly instead of stored. Backfill accepts any width. Whether a 24 h
span still returns 15-minute buckets is UNVERIFIED — the validation script asks
for exactly that span.

**Revisions.** Recent buckets fill in as GDELT ingests late articles. First
write wins (`ON CONFLICT DO NOTHING` on the dedupe key): what we keep is what
was known when we asked, so a replay never sees a later revision early.

**Politeness.** Requests are spaced by `MLL_GDELT_MIN_INTERVAL_SECONDS` (6 s;
GDELT asks for ≤ 1 request / 5 s). A scheduled pass also has a request budget
and a wall-clock deadline (next section).

## COLLECTION SCHEDULER AND PRIORITY

Code: `priority.py` (pure), `collector.py` (`SourceSchedule`),
`service.py` (`collection_priorities`, `plan_collection`), `scheduler.py`
(`_collect_tick`). Tests: `tests/unit/test_mll_priority.py`,
`tests/unit/test_mll_collector_schedule.py`,
`tests/integration/test_mll_source_chain.py` (scheduling section).

**Priority is collection frequency only.** It is never an input to a decision;
`strategy.py`, `replay.py` and every other decision engine are test-forbidden
from importing `priority.py`. What it changes is how much forward data exists,
which the point-in-time gate then treats like any other data.

**Level** — from the meme's lifecycle state classified point-in-time at `now`
(`states.classify_state` over AUTHORITATIVE data). A meme whose newest reading
has aged out of its freshness budget (e.g. after failed collections) reads
UNKNOWN; so when the state at `now` is UNKNOWN but an attention reading was retrieved
within 24 h, the state classified *at that reading's `retrieved_at`* stands in
(reason `last_known_state:<state>`). Without this a dormant meme would be
promoted to NORMAL and collected hourly.

| Level | States |
|---|---|
| HIGH | ACCELERATING, PUMPING, REVIVING, SECOND_WAVE, THIRD_WAVE |
| NORMAL | EMERGING, ACTIVE, COOLING, UNKNOWN (with data in the last 24 h) |
| LOW | DORMANT, DECAYING, DEAD, UNKNOWN with no data in the last 24 h |

**Cadence per source.**

| Source | Due when | Notes |
|---|---|---|
| GDELT | last success older than HIGH 15 min / NORMAL 60 min / LOW 6 h | `timespan` = gap since last success + one 15-min bucket of overlap, clamped to [2 h, 24 h], rounded up to whole hours; never collected → 24 h. Overlap is free (first-write-wins dedupe). |
| Wikipedia | no success yet this UTC day | daily data; the 3-day forward window heals a day published late |
| DexScreener profiles | no success yet this UTC day, per mint | a newly linked mint has no history, so it is due immediately |
| pump.fun replies | every pass | a freshness probe; no network |

A *success* is an AVAILABLE / UNAVAILABLE / PARTIAL per-subject run (the
source answered, possibly "nothing"); `deferred_budget` is not a success — the
source was never asked. After `k` consecutive ERROR runs the next attempt is
`base × 2^(k−1)` after the last error (base = the level interval for GDELT,
1 h for the daily sources), capped at 6 h (the LOW interval).

**What gets recorded.** A meme that is not due is not asked and gets **no
run** — its last run stands. A meme that is due but beyond the budget gets an
`UNAVAILABLE deferred_budget` run (never silently dropped). A source with
nothing due records nothing that pass (a global run claiming to speak for every
meme when nobody was asked would be false — `pit` lets a global run speak for
all memes). The global run's `detail.schedule` carries
`{due, not_due, deferred, planned_requests}`; the tick's return value carries
the same per source, or `"unscheduled"` if planning failed (then every subject
is asked with the fixed 6 h span, as before the scheduler — logged as
`lifecycle_collect_plan_failed`).

**Budget.** Per pass, GDELT requests ≤
`floor((task_time_limit − 180 s) / MLL_GDELT_MIN_INTERVAL_SECONDS)` =
`floor((600 − 180) / 6)` = **70**. Due memes are admitted in the total order
(priority desc, last success asc — never collected first, slug, id); memes
sharing a query cost one request. Independently, the adapter will not *start* a
request that could run past `start + (task_time_limit − 180 s)` (spacing + the
20 s request timeout), so a run of slow answers defers memes instead of the
task being killed mid-write.

**Target 10–20 memes, worked through.** Worst case, all 20 HIGH: 20 requests
× 6 s ≈ 2 min per 15-min pass, 29 % of the 70-request budget — nothing
deferred. A typical mix (say 3 HIGH, 7 NORMAL, 10 LOW) averages 3 + 7/4 +
10/24 ≈ 5.2 GDELT requests per pass (≈ 500/day, versus 1,920/day unscheduled).
Wikipedia: 20 requests once a day. DexScreener: one batch call (≤ 30 mints)
once a day plus any newly linked mint.

**Request-reduction questions, answered.**

| Option | Verdict | Why |
|---|---|---|
| Batch memes into one GDELT query | **No** | a timeline cannot attribute OR'd terms to separate memes |
| Share identical queries | **Yes** | de-duplicated per pass; each meme gets its own rows |
| Reduce frequency | **Yes, by priority** | HIGH 15 min, NORMAL 60 min, LOW 6 h |
| Skip unchanged | **Only by due time** | GDELT returns no ETag / change token; asking is the only way to know |
| Prioritise | **Yes** | deterministic admission order under the budget; overflow deferred and recorded |

**Freshness budgets (2026-10-03; resolves the two interactions previously
listed here).** Staleness is judged per source, by
`domain.SOURCE_MAX_AGE` — each source's collection cadence plus a margin:
Wikipedia, DexScreener and GeckoTerminal 30 h (daily), GDELT 7 h (LOW
priority's 6 h), pump.fun replies 30 min, Reddit/X 2 h. The gate applies it to
`SourceAvailability` (STALE past budget) and records it on the
`InformationState`, and attention uses the same budget for "is this series
still *now*", so availability and `platform_count` follow attention, not the
scheduler. `information_available_at(source_max_age=...)` overrides the
mapping whole; `max_observation_age` covers only sources it omits (`{}`
restores the old single 2 h budget). Run precedence: a meme's own per-subject
run (meme or linked mint) decides its status; a global run speaks for it only
until it has one, so one erroring due meme no longer turns non-due memes
PARTIAL / ERROR.

## INCREMENTAL REPLAY AND CHECKPOINTS

The forward replay runs every 30 minutes over `[MLL_FORWARD_START, now)`.
Before this change it re-ran every tick every time, so its cost grew with the
forward period. It now continues from a checkpoint, and **the result is the
same as a full replay**. The rest of this section explains why that holds
and what makes a checkpoint unusable.

### Architecture

| Piece | Pure | Role |
|---|---|---|
| `replay.ReplayState` | ✓ | Everything the fold carries from one tick to the next. Immutable, and round-trips through JSON (`to_json`/`from_json`) with Decimals as strings |
| `replay.resume_replay(state, inputs, cfg, mode, arm, end, hindsight_links, checkpoint_at=None)` | ✓ | Continues the fold. Returns the result over `[state.start, end)` and the state after the last tick before `end`, or before `checkpoint_at` if given. `run_replay` is `resume_replay` from `ReplayState.initial` |
| `checkpoint.py` | ✓ | `Checkpoint`, `CheckpointVersions`, `CheckpointScope`, the pure `input_watermarks` reference digest, and `is_valid(checkpoint, current_versions=, current_watermarks=) -> (bool, reason)` |
| `repository.input_watermarks` | I/O | The same digest as a single SQL aggregate |
| `repository.get/save/delete_checkpoint` | I/O | `mll_replay_checkpoints` (migration `0113`): one row per scope (`mode`, `arm`, experiment, hindsight), unique on `scope_key`, with no history kept. It cascades with its experiment and its run |
| `service.run_forward_replay(now, force_full=False)` | I/O | Load → validate → resume or replay in full → persist → checkpoint |

Each forward run does the following for every arm:

1. `cp_tick` is the last grid tick before `now - MLL_CHECKPOINT_SAFETY_LAG_SECONDS`.
   The SQL watermark at `cp_tick` is computed **before** the inputs are loaded.
2. The inputs are loaded in full: rows since `forward_start - 8d`, as before.
3. The checkpoint is read, and its watermark is recomputed in SQL at its
   `processed_until` **after** the load. It is then compared with
   `is_valid` (see below).
4. If it is valid, the run calls `resume_replay(state, …, end=now, checkpoint_at=now - lag)`.
   Otherwise it does the same from `ReplayState.initial`. The pass reports
   up to `now` and exports the state at `cp_tick` along the way.
5. The run persists its results, then upserts the new checkpoint in the
   same transaction.

The order in steps 1 and 3 matters. A row committed between the digest and
the load either changes the next run's watermark (step 1) or fails this
run's validation (step 3). Both lead to a full replay. Neither lets a resume
silently miss the row.

### What is resumed, and what is recomputed

**Carried in `ReplayState`:**
- Identity: mode, arm, start, `hindsight_links`, `history_lookback`,
  `config_hash` and meme ids. `resume_replay` refuses a mismatch.
- Progress: tick count and `processed_until`.
- The portfolio ledger:
  - cash, realised P&L and the equity peak;
  - open positions, kept in ledger order because Decimal sums depend on
    order. Each position stores its trade with the evidence so far, its
    exit state (entry and peak price, entry volume and attention), its exit
    cursor and the exit notes already recorded. The cursor is stored as a
    time (`cursor_at`), not a row index;
  - closed trades and the equity curve, together with the last valuation,
    which supplies the curve's closing point.
- Per meme: the prior events. These are all the memory the event engine
  uses for episodes and re-arming.
- The decision log, plus its compaction state: the open run and its outcome
  for each `(meme, mint)`.
- Rejection counts and the `contains_backfill` flag.

**Recomputed every tick from the inputs, never carried:**
- the `InformationState`;
- attention and market features;
- events (checked against the carried priors);
- lifecycle states, divergence and strategy decisions.

The detectors read all visible history through the gate, so a resume still
loads all the inputs. What it saves is the ticks already folded in.

**Recomputed every run:** the ticks after the checkpoint. That is at least
the last `MLL_CHECKPOINT_SAFETY_LAG_SECONDS`, because late rows may still
change them.

**Persisted incrementally:** an incremental run writes only what the
checkpoint state had not produced yet:
- trades that were not closed in that state, with the exit side upserted;
- snapshots past the state's equity curve;
- events after its last tick.

The run that produced the checkpoint wrote everything else, in the same
transaction as the checkpoint row. The writes are first-write-wins and keyed
upserts, as before, so the stored rows match what a forced full run would
store. The integration test checks this.

### Invalidation rules (reason codes in `summary.replay.invalidation_reason`)

| Cause | Reason |
|---|---|
| First run, or the checkpoint was deleted or cascaded away | `no_checkpoint` |
| Forced (`force_full=True`) | `forced` |
| `REPLAY_VERSION` bumped | `replay_version_changed` |
| A byte changed in any engine module (`checkpoint.ENGINE_MODULES`; a test asserts the list covers `replay.py`'s transitive imports). The hash is read once per process, so it reflects the code that is actually running | `engine_code_changed` |
| Experiment strategy spec hash changed | `strategy_spec_changed` |
| `LabConfig` or the arm's strategy spec changed (`replay.config_hash`) | `config_changed` |
| `MLL_FORWARD_START` moved | `window_start_changed` |
| A meme was added, archived or removed | `meme_set_changed` |
| A link with `linked_at <= processed_until` was added, removed or edited, or an `unlinked_at <= processed_until` was set or moved. Under hindsight, every link counts | `link_changed:<meme>:<kinds>` |
| An alias with `added_at <= processed_until`, or the meme row itself | `alias_changed:…`, `meme_changed:…` |
| The `discovered_tokens` row of a counted mint changed (it is not time-gated, and token age reads it) | `token_changed:…` |
| An observation, pump.fun reply, market snapshot or collection run with knowledge time `<= processed_until` was added, removed or edited | `retroactive_data_changed:<meme or *>:<obs\|market\|run>` |
| The forward run row was replaced | `run_changed` |
| The state document can't be read, or disagrees with the checkpoint row | `state_unreadable:…`, `state_inconsistent`, `state_mismatch:…` |

**Input watermark.** For each meme and each kind of row, the watermark is:

- `count(*)`;
- the sum of the first 60 bits of `md5(canonical row key)`;

over every row whose knowledge time is `<= processed_until`. Knowledge time
is:

- `retrieved_at` for observations. In EXPLORATORY mode, backfill uses the
  replay's publication-lag floor;
- `available_at` for market rows;
- `finished_at` for collection runs.

A row that becomes known *after* `processed_until` doesn't change the
watermark. Picking up such rows is exactly what resuming is for.

Rows count for a meme under the same subject rules as the PIT gate, using
the same lower bound as the loader (`forward_start - 8d`). Global collection
runs count once, under the key `*`.

The key covers every field an engine reads, plus identity. It doesn't cover
`raw_payload` or `source_url`, which are provenance only. `checkpoint.py`
defines the key strings, and the SQL in `repository.input_watermarks`
reproduces them byte for byte (`trim_scale` for numbers, epoch microseconds
for timestamps). An integration test compares the SQL result with the pure
digest over rows loaded by the same repository, in both modes and with
hindsight on. That test found a real divergence while this was being built.

### Safety lag

`MLL_CHECKPOINT_SAFETY_LAG_SECONDS` defaults to 1800 and is set in the
`x-backend-env` anchor. Collectors stamp `retrieved_at` when they fetch and
insert slightly later. Enrichment does the same with `captured_at`. A
checkpoint taken right at `now` would be invalidated by nearly every such
row. With the lag, those rows land in the recomputed tail instead. The lag
only keeps invalidations rare. The watermark is what guarantees correctness:
a row that still arrives behind the lag causes one full replay.

### Equivalence guarantee and how it is tested

The guarantee: for identical inputs, `resume_replay` from any state that an
earlier replay returned produces a `ReplayResult` equal to the uninterrupted
`run_replay`. Equal means the same events, entries, exits, closed and open
trades, evidence timelines, equity curve, decision log, rejection counts,
metrics and `input_fingerprint`, checked by dataclass equality and by a hash
of `to_dict()`.

This holds because the state after tick `T` depends only on rows visible at
or before `T`, and every carried value is restored exactly.

`tests/unit/test_mll_incremental.py` checks this on a deliberately busy
synthetic world:

- First, second and third waves, an observed dormancy and a revival.
- A link made mid-replay, a link withdrawn mid-replay, and a mint shared by
  two memes.
- Unpriced readings, and a market-wide surge that fills the position cap.
- Take-profit, stop-loss, trailing-stop, volume-collapse, attention-collapse,
  max-hold and end-of-data exits. A test asserts that all of these happen.

Every intermediate state goes through JSON. The resume points are:

- a midpoint, both on and off the grid;
- every 9th tick;
- every tick across the busiest stretch;
- inside open positions;
- inside attention episodes;
- on the tick an exit fires;
- a resume that folds no new tick;
- EXPLORATORY mode with backfill, hindsight links and a history window
  short enough that backfill ages out;
- a bounded `history_lookback`.

Further tests cover:

- the round trip `from_json(to_json(s)) == s`;
- that resuming never mutates its input state;
- that `checkpoint_at` returns exactly the shorter replay's state;
- that a mismatched mode, arm, configuration, links mode or meme set is
  refused.

The suite was mutation-checked. Each of these breaks fails it:

- dropping the exit notes;
- resetting the exit cursor;
- resetting the trailing peak;
- dropping prior events;
- dropping the open decision runs;
- dropping the backfill flag;
- dropping the last valuation.

`tests/unit/test_mll_checkpoint.py` covers each invalidation cause together
with the change that must *not* invalidate: a row retrieved one minute after
the checkpoint, a link made after it, an unlink after it, and backfill under
AUTHORITATIVE. It also checks the contract end to end:

- when `is_valid` passes, the resumed result equals a full replay;
- a row stamped before the checkpoint but inserted after it is refused, and
  trusting it would have produced a different answer.

`tests/integration/test_mll_checkpoint_service.py` checks the service:

- the second run resumes;
- its stored trades, snapshots, events, summary and next checkpoint equal a
  forced full run's, compared across a savepoint;
- a retroactive observation, a backdated link, a new meme, a different
  config hash, edited engine bytes and a replaced run row each invalidate;
- the SQL digest equals the pure digest.

### Cost model

Let *T* be the ticks so far, Δ the ticks since the checkpoint (about
lag + 30 min, so roughly 12 at 5-minute ticks), *M* the memes and *R* the
stored rows in the window.

| | Full | Incremental |
|---|---|---|
| Engine calls | O(T·M) | O(Δ·M) |
| Input load | O(R) | O(R), unchanged. The gate needs the full visible history |
| Canonicalise and index the inputs | O(R log R) | O(R log R) |
| Watermarks | one SQL aggregate, O(R) | two SQL aggregates, O(R). Neither leaves the database |
| State (de)serialisation | none | O(state). State grows with the equity curve, decision runs, events and closed trades |

Measured on synthetic data with production defaults (5-minute ticks and an
8-day history bound):

| 14 days × 15 memes (16 mints; ~21.6k observations, ~69k market points), baseline arm | |
|---|---|
| Full replay, 4,032 ticks (196 trades, 1,975 events, 12,054 decision runs, 1,827 snapshots) | **560 s** |
| Incremental resume 30 minutes later (12 ticks, including the recomputed tail) | **4.5 s** |
| Checkpoint state | 9.6 MB JSON (encode 225 ms, decode 127 ms) |
| Pure watermark over all inputs (the reference; production uses SQL) | 0.5 s |

The state is dominated by the events, each of which carries its feature
snapshot, and then by the decision log. Both grow linearly with the forward
period. Over a 90-day horizon, expect a state of roughly 60 MB per arm. That
is the first thing to slim down: closed outputs could move out of the state
once persisted. It has not been done, because it trades simplicity for size.

The SQL watermark over about 850k market snapshots and 140k observations
(15 memes × 2 mints, 90 days plus 8 days of lookback) takes about 4.2 s on
the dev Postgres, so about 8.5 s per run for the two digests. That cost is
linear in stored rows and independent of ticks.

If it becomes the bottleneck, the next step is a per-meme aggregate
maintained on insert. It is not built: an incremental digest has to be
proven correct against deletes and edits, and the full digest is the simple
guarantee.

## DATA-QUALITY MODEL

`GET /quality`, `GET /memes/{slug}/quality` and `GET /research-status` answer one
question: *can the forward record be trusted, and is there enough of it?* They
read; they never write, and every query is bounded by the request's `now`.

**What is counted, and when.**

| Figure | Rule |
|---|---|
| Observation date | `retrieved_at` — the only timestamp that proves when MEMESCOPE knew a reading. A backfilled 2024 Wikipedia day retrieved yesterday is yesterday's *acquisition* |
| `observations_today` / `_week` | since UTC midnight / the last 7 days; split by `data_class` into `forward` and `backfill`, never summed |
| pump.fun replies | read in place from `pumpfun_social_snapshots` for currently linked mints; counted as **forward** (source `pumpfun_replies`); a NULL `reply_count` is not an observation |
| GeckoTerminal | writes candles, not observations: shown per meme as `backfill_count` (candles with `data_class='backfill'`), not in the `/quality` observation totals |
| `runs_24h` | every collection run finished in the last 24h, any status |
| `failures_24h` | `unavailable` + `error` runs. `stale` and `partial` are degraded states, listed per source but not failures |
| `success_rate_24h` | `available ÷ (runs − disabled)`, 3 decimals. **DISABLED leaves both sides**: switching a source off is configuration, not a failure. `null` when the denominator is 0 — a source that was never asked has no rate, not 0% and not 100% |
| `unavailable_sources` | current health is `unavailable`, `error` or `disabled` (cannot deliver data now). `never_collected` is not listed: it has not been attempted |
| `memes_without_observations` | tracked memes with no observation of any class addressed to the meme or to a linked mint, and no pump.fun reply for one. Listed, not hidden |
| `tokens_without_market_history` | currently linked mints with neither a (non-suspect) forward snapshot nor a backfill candle |
| `tokens_with_incomplete_market_data` | the **latest** forward snapshot is missing any of `price_usd`, `market_cap`, `liquidity_usd`, `volume_1h`; `missing` lists them. An old gap since filled is not a gap. Snapshots the ingest firewall flagged `suspect` are ignored, as in every other reader |

**Per-meme audit.** Links carry `linked_at` (write-once), `method`,
`confidence`, `linked_by` and the matcher's `evidence`; links dated after `now`
are not shown. `sources` covers all seven sources with the *current* health
status and, for this meme, first/latest `retrieved_at` and forward/backfill
counts (`observation_count` is their sum; zero is a real zero here because the
status beside it says whether the source was ever able to answer). `market`
per linked mint counts forward snapshots plus backfill candles; `missing_fields`
comes from the latest forward snapshot, and is all four fields when none exists.
`lifecycle_state`, `attention` and `divergence_case` come from the same pure
engines as the radar, evaluated at `now` in AUTHORITATIVE mode.
`collection_priority` is `priority.py`'s output for the meme (frequency only; it
never reaches a decision), with the reason code rendered to prose server-side.

**Research status.** `research_status.py` is a pure state machine
(`NOT_STARTED → COLLECTING → INSUFFICIENT_DATA → READY_FOR_ANALYSIS`) over the
eight requirements above. Facts come from the database at `now`:

* *Independent events*: forward AUTHORITATIVE wave events (`new_attention_wave`,
  `second_wave`, `third_wave`) plus revivals not within 24h of a wave on the same
  meme (a revival *is* a wave that follows observed dormancy — one episode, not
  two). Backfill-derived events and events outside `[forward_start, now]` never
  count.
* *Revival / later-wave*: `meme_revival` + `second_wave` + `third_wave` rows.
* *Trades*: closed baseline-arm trades in the latest forward run with
  `exit_at <= now`; trades entered after `now`, or flagged backfill/hindsight,
  do not count. *Out-of-sample* = closed trades entered inside the experiment's
  test segment (none can exist before it begins). *Concentration* = the top
  meme's share of those trades; unmeasurable with zero trades.
* *Control arms*: B, C and D each have a completed forward run over exactly the
  baseline run's window.

A fact that cannot be measured (no experiment, no baseline run) is `observed:
null`, `met: false` with a reason — never 0 and never assumed. The verdict is
always `UNCERTAIN` and `verdict_engine_available` is `false`; `ANALYZING` and
`AUTHORITATIVE_RESULT` are unreachable until a verdict engine exists
(`research_status.UNREACHABLE_STATES`, pinned by tests). The thresholds are
module constants pinned by `tests/unit/test_mll_research_status.py` to this
document's table, which it parses — editing one without the other fails.

`POST /memes` refuses slugs that collide with the Lab's own pages
(`quality`, `research-status`, `health`, `overview`, `experiments`, `runs`,
`memes`) with 422.

## EXPLORATORY vs AUTHORITATIVE DATA

The two classes are labelled identically everywhere (API `data_label`, UI banners):

> **EXPLORATORY DATA** — Historical data may contain survivorship or look-ahead
> limitations. Not used for the authoritative strategy verdict.

> **FORWARD DATA** — Collected prospectively by MEMESCOPE. Eligible for the
> authoritative research dataset.

Authoritative replay admits FORWARD rows only (`pit.py`); backfilled engagement
and cumulative metrics are invisible even in exploratory mode until retrieved.

## RESEARCH VERDICT STATES

```
NOT_STARTED        MLL_FORWARD_START unset or in the future, or the Lab flag is off
COLLECTING         forward collection running; gate not evaluated as near
INSUFFICIENT_DATA  forward data exists but at least one minimum-evidence requirement is unmet
READY_FOR_ANALYSIS every requirement met and the experiment's data_cutoff has passed
ANALYZING          an authoritative analysis run is in progress
AUTHORITATIVE_RESULT a completed analysis over the pre-registered splits
```

`verdict` is **UNCERTAIN** in every state except AUTHORITATIVE_RESULT. The
verdict engine (EDGE EXISTS / NO EDGE / WEAK EDGE / OVERFIT) is **not built in
this phase**, so the furthest reachable state is READY_FOR_ANALYSIS and the
verdict is UNCERTAIN by construction. COLLECTING vs INSUFFICIENT_DATA:
COLLECTING while the forward span is shorter than 7 days (too early to judge any
requirement); INSUFFICIENT_DATA afterwards until every requirement is met.

## MINIMUM EVIDENCE REQUIREMENTS

Fixed before any result was seen. Chosen from research-quality conventions
already used in this repo (the 25/50/100/200/500 sample ladder, the V6 protocol's
≥100-trade promotion floor and top-trade concentration rule) — not from Lab
results, of which there are none.

| Requirement | Threshold | Why |
|---|---|---|
| Forward observation period | ≥ the experiment horizon (`MLL_EXPERIMENT_HORIZON_DAYS`, 90) and `data_cutoff` passed | The 70/15/15 split is defined over that horizon; an unfinished test segment is not out-of-sample |
| Independent meme events | ≥ 100 forward events (one per episode, per `events.py` re-arm rules) | Below 100 the event-level return distribution is anecdotal |
| Revival / later-wave events | ≥ 30 (MEME_REVIVAL + SECOND_WAVE + THIRD_WAVE) | The core hypothesis is about *re*-activation; first waves alone cannot test it |
| Trades (baseline arm, all segments) | ≥ 100 closed | Repo-wide promotion floor (V6 protocol) |
| Out-of-sample trades (test segment) | ≥ 30 closed | Smallest OOS sample where a profit factor is not dominated by one trade |
| Distinct memes with trades | ≥ 10 | Guards against "it works because of one meme" |
| Single-meme concentration | top meme ≤ 25% of trades | Same reason |
| Control arms run | B, C, D completed over the same window | "Adds information" is only answerable against controls |

Every requirement reports `{threshold, observed, met}`; a requirement that
cannot be measured is `met=false` with a reason, never assumed.

## NEW API CONTRACT (validation phase)

`GET /quality` — forward data-quality report
```jsonc
{ "generated_at": iso,
  "tracked_memes": 12, "tracked_tokens": 9,
  "observations_today": { "forward": 340, "backfill": 0 },
  "observations_week":  { "forward": 2100, "backfill": 5600 },
  "collection": {
    "runs_24h": 180, "failures_24h": 4, "success_rate_24h": "0.977" | null,
    "by_source": [{ "source", "label", "runs_24h", "available", "unavailable", "disabled",
                    "error", "stale", "partial", "success_rate_24h": str|null,
                    "last_success_at": iso|null, "last_status": str|null, "last_reason": str|null }] },
  "unavailable_sources": ["reddit"], "stale_sources": [],
  "oldest_forward_observation_at": iso|null, "newest_forward_observation_at": iso|null,
  "memes_without_observations": [{ "slug", "display_name" }],
  "tokens_without_market_history": [{ "mint", "meme_slug" }],
  "tokens_with_incomplete_market_data": [{ "mint", "meme_slug", "missing": ["liquidity_usd"] }] }
```
`success_rate` = AVAILABLE ÷ (runs − DISABLED); DISABLED is a configuration
state, not a failure, and is excluded from both sides.

`GET /memes/{slug}/quality` — per-meme audit trail
```jsonc
{ "meme": { "slug", "display_name", "description", "tracking_started_at", "wikipedia_title", "gdelt_query" },
  "aliases": [{ "alias", "kind", "added_at" }],
  "links": [{ "mint", "method", "confidence", "linked_at", "unlinked_at", "linked_by", "evidence" }],
  "sources": [{ "source", "label", "status", "reason", "first_observation_at", "latest_observation_at",
                "observation_count", "forward_count", "backfill_count" }],
  "market": [{ "mint", "first_observation_at", "latest_observation_at", "observation_count",
               "missing_fields": ["liquidity_usd"] }],
  "lifecycle_state": "dormant",
  "attention": { "mentions_1h": Measured, "velocity": Measured, "acceleration": Measured,
                 "baseline_multiple": Measured },
  "divergence_case": "none",
  "collection_priority": { "level": "low|normal|high", "interval_seconds": 21600, "reason": str } }
```

`GET /research-status`
```jsonc
{ "state": "NOT_STARTED|COLLECTING|INSUFFICIENT_DATA|READY_FOR_ANALYSIS|ANALYZING|AUTHORITATIVE_RESULT",
  "verdict": "UNCERTAIN", "verdict_engine_available": false,
  "forward_start": iso|null, "forward_days": 0.0|null, "experiment_key": str|null,
  "requirements": [{ "key", "label", "threshold": str, "observed": str|null, "met": false,
                     "reason": str|null }],
  "explanation": str }
```
`GET /overview` gains `"research_status": <same object>`.
