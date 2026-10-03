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
