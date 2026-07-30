# Event Intelligence

How LETZMOON decides that something changed, and how it tells you.

---

## The design constraint everything follows from

**Silence is the default.** An event engine that fires whenever a number moves
gets muted within a week, and a muted channel also swallows the alerts that
mattered. So every event must clear an explicit threshold, and most of the
detector's tests assert that *nothing* was emitted.

Two consequences worth stating plainly:

- **Price is not an input.** `TokenState` has no price field and a test asserts
  it. Price is the noisiest series the platform holds and the one users can
  already see elsewhere. A price move that means something surfaces here as a
  *momentum* or *liquidity* change with the detecting analyst's evidence
  attached, or it does not surface.
- **Score drift reuses the engine's own bar.** `MATERIAL_SCORE_DELTA` comes
  from `services/scoring/materiality.py` rather than being re-decided, so this
  module and `token_score_history` agree about the word "changed".

---

## Lifecycle

```
enrichment writes snapshots
        │
        ▼
Radar sweep re-evaluates tracked projects        (*/15)
        │
        ▼
event cycle                                      (3,18,33,48 — after the sweep)
        │
        ├─▶ load current readings   (six analysts, unchanged)
        ├─▶ load previous readings  (analyst_reading_cache, one batched query)
        ├─▶ detect(previous, current)             pure, deterministic
        ├─▶ append events           (intelligence_events, ON CONFLICT DO NOTHING)
        ├─▶ overwrite cache         (analyst_reading_cache)
        └─▶ COMMIT — both, or neither
```

The cycle runs **after** the sweep on purpose. Running it first would diff a
stale reading against itself, report nothing, and lose the change until the next
cycle.

---

## The transaction boundary is the whole design

A cycle writes two things per token: the events it detected, and the new cached
state. They must land together.

| Failure | Consequence |
|---|---|
| Events commit, cache does not | Next cycle re-detects the same changes. The dedup key protects the log, so the run is merely wasted. |
| Cache commits, events do not | **The change is lost permanently.** The cache now says "already seen", so no future cycle will ever report it. |

The second is silent and unrecoverable, which is why the commit is at the end of
the whole batch rather than per token. A token that fails is counted, logged at
error level with its mint, and skipped — one bad series must not cost the batch,
and a cycle that quietly drops tokens looks identical to a quiet market.

---

## Storage: two shapes, two disciplines

**`analyst_reading_cache`** — mutable, one row per token. Holds *where we were*
so the next cycle diffs against one row instead of re-analysing 23,000
projects. This is what makes detection incremental.

**`intelligence_events`** — append-only. There is no update or delete path
anywhere in the repository, and a test asserts it. "What changed last week" is
only worth asking if the answer cannot be quietly revised.

Deduplication is **per moment, not per kind**: `ON CONFLICT DO NOTHING` on
`(mint_address, kind, occurred_at)`. A retry or a racing worker records each
change once, while a token genuinely promoted twice still gets two events.

The cache is deliberately narrow — only the fields events derive from. The full
readings are recomputable at any time because the analysts are pure, so caching
them would be duplicated state that could drift from its source.

---

## Execution summary

Every cycle returns operational telemetry, logged as `event_cycle_completed`:

| Field | Reading it |
|---|---|
| `analysed` | Tokens successfully observed |
| `changed` | Tokens that produced at least one event |
| `events_generated` | Events the log accepted |
| `events_skipped` | Proposed minus accepted — a persistent gap means dedup is firing, usually because the cycle runs more often than state moves |
| `cache_hits` / `cache_misses` | Misses are first sightings; a rising miss rate means new tokens are arriving |
| `failures` | Tokens that raised. Never silent — each is logged with its mint |
| `elapsed_ms` | Wall clock |

---

## REST API

Watchlist routes are scoped to the authenticated user **in SQL**. A request for
someone else's list returns **404, not 403** — confirming a resource exists to a
caller who cannot read it is itself a leak.

| Method | Path | Notes |
|---|---|---|
| GET | `/watchlists` | With item counts |
| POST | `/watchlists` | 409 on duplicate name per user |
| PATCH | `/watchlists/{id}` | Rename, describe, reconfigure alerts |
| DELETE | `/watchlists/{id}` | Cascades to items |
| GET | `/watchlists/{id}/tokens` | Adds live state and last change, batched |
| POST | `/watchlists/{id}/tokens` | Captures state at the moment of adding |
| DELETE | `/watchlists/{id}/tokens/{mint}` | 404 if not on the list |
| GET | `/watchlists/{id}/events` | One query for the whole list |
| GET | `/events` | Paginated, filtered, ordered — all in SQL |
| GET | `/events/{id}` | |
| GET | `/events/token/{mint}` | Newest first |
| GET | `/brief` | Scoped to watched tokens by default |
| GET | `/brief/changes` | Entries only |
| GET | `/mission-log` | Unscoped: the operator's view |

`applied_filters` is echoed on paged responses so an empty page caused by a
strict filter is distinguishable from an empty log — the convention
`/scores/top` established.

Ordering is total (`occurred_at`, then `id`). Without the tiebreak, two events
in the same second could swap between pages while a client walks them.

---

## The brief

Generated **entirely from the stored event log**. It never re-derives analyst
logic, and a test asserts the module does not import the analysts. If it
recomputed readings it could disagree with the events it is summarising, and a
user reading both would have no way to know which was right.

Scoped to watched tokens by default. An empty watchlist returns a brief that
says so, rather than falling through to "no filter" and returning the whole
platform's activity — that would be a feed, and the point of the brief is to be
short enough to read.

Event kinds with no brief category land in `other` rather than being dropped: a
silently discarded event is worse than an uncategorised one.

---

## Troubleshooting

**No events, ever.** Check `FEATURE_RADAR_ENABLED` — the cycle skips outright
when the Radar is off, and logs `event_cycle_skipped` with the reason. Then
check that state is actually moving: with the scanner down and enrichment idle
on long refresh tiers, a correct engine reports nothing because nothing changed.

**`events_skipped` climbing.** Deduplication is firing. Normally means the cycle
runs more often than state moves, which is harmless. If it climbs while
`cache_hits` stays at zero, the cache is not being written — check for a
rollback between the event insert and the cache write.

**`cache_misses` equals `analysed` on every run.** The cache is not persisting.
Every cycle then re-emits `FIRST_ANALYSED` and the log fills with duplicates the
dedup key rejects.

**Watchlist writes return 409 mentioning the dev bypass.**
`DEVELOPMENT_BYPASS_AUTH=true` produces a transient principal that is never
written to `users`, and watchlists need a real row. Sign in with a seeded
account (`make seed`) or set the flag to `false`.

**PATCH returning 500 with `MissingGreenlet`.** `updated_at` carries
`onupdate=func.now()`, so after an UPDATE it is a server-side value the session
has not seen; reading it triggers an implicit lazy fetch outside greenlet
context. The route refreshes explicitly after commit. Any new route that mutates
and then serialises a timestamped row needs the same.
