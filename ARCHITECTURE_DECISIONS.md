# MEMESCOPE — Architecture Decisions

> **Status:** Accepted, pre-implementation
> **Date:** 2026-08-02
> **Scope:** The Opportunity Engine — the central intelligence layer
> **Supersedes:** the Radar's role as an opportunity *producer* (Phase 8)
> **Extends:** [ADR 0001](docs/adr/0001-market-provider-abstraction.md) ·
> [ADR 0002](docs/adr/0002-composite-liquidity-fill.md)

This document records the architecture agreed before implementation begins. It
is the permanent reference for the Opportunity Engine: what was decided, why,
and what each decision costs. Per-subsystem decisions that predate it remain in
`docs/adr/`; this does not restate them.

Nothing here has been built. Where a decision depends on data the platform does
not hold, that is stated rather than designed around — see §12.

---

## 1. Context

MEMESCOPE is not a token scanner. It is an opportunity intelligence platform.
The distinction is architectural, not marketing: a scanner answers *which tokens
exist*, and the current Radar is built to answer exactly that.

The observed failure is a direct consequence. `discovered_tokens` serves as both
the watch universe and the candidate list, so the Radar ranks a static set of
24,196 historical Pump.fun tokens by a score recomputed every 15 minutes. The
board barely moves, because nothing about the *set* is changing — only the
scores within it. Ranking a fixed population cannot surface novelty.

The product needs the opposite framing:

> **The opportunity is new. The token does not have to be.**

A token that launched three weeks ago and crossed its graduation threshold four
minutes ago is exactly what the platform should surface. A token that has been
sitting at rank 7 for two days is not.

**Every opportunity exists because something changed.** The engine must detect
change, not evaluate absolute values.

---

## 2. Decision summary

| # | Decision |
| --- | --- |
| AD-01 | The historical token database becomes the observation *substrate*, not the candidate list |
| AD-02 | The append-only market snapshot stream is the primary discovery source |
| AD-03 | Admission requires a *transition*, never a threshold |
| AD-04 | Signal providers implement one generic contract; Pump.fun is one provider among many |
| AD-05 | Two-level model: one opportunity per token, many independently-expiring signals |
| AD-06 | Confidence is deterministic, pure, and published |
| AD-07 | Explanations are rendered from stable reason codes, never stored as prose |
| AD-08 | Ranking is `severity × confidence × freshness`, with evidence as a gate |
| AD-09 | Uniqueness constraints, not application checks, guarantee deduplication |
| AD-10 | TTL is a property of the signal type; four independent exit paths |
| AD-11 | The event log is the source of truth; the board is a projection over it |
| AD-12 | Detection rides enrichment writes, not a timer |

---

## 3. AD-01 — The historical database changes role

**Decision.** `discovered_tokens` and `token_enrichment_state` remain the
observation substrate: who is watched, and how often. They stop being the
candidate list. Radar admission moves onto the change stream.

**Why.** Conflating the two roles is the defect. The 24,196 tokens should stay
watched — they are exactly the population the vision cares about, since a token
may be days or weeks old. They simply stop being *candidates* until something
happens to them.

**Consequence.** The platform decouples from the scanner. New launches feed the
substrate, but opportunities no longer require new tokens — so MEMESCOPE becomes
useful again before the Helius quota block (`MEMESCOPE_AUDIT.md` R1) is resolved.

---

## 4. AD-02 — The snapshot stream is the discovery source

**Decision.** Discovery reads `token_market_snapshots` as a *sequence*:
the delta between consecutive observations of the same mint. `analyst_reading_cache`
and `intelligence_events` are the secondary source for slower-moving change.

**Why.** The pipeline already produces this. 1.72 M append-only rows, tiered
cadence, nothing overwritten — the information the product wants ("liquidity
doubled in 40 minutes", "this now trades on pumpswap") is already stored and has
never been read as a series. `app/events/detector.py` already implements
diff-against-cached-previous for the analyst ensemble; it is the prototype for
the whole engine.

**Consequence.** No new ingestion. The change stream is a read pattern over data
the platform pays for today.

---

## 5. AD-03 — Transitions, not thresholds

**Decision.** A token is admitted when a measurable quantity crosses a boundary
it was not across at the previous observation. Three qualifiers apply:

- **Confirmation** — the crossing holds for a second observation, or is
  corroborated on an independent dimension (a price move *with* volume behind
  it). One snapshot is noise.
- **Materiality** — reuses the existing `scoring/materiality.py` gate. A
  crossing inside measurement jitter is not an event.
- **Evidence floor** — no admission on a window too thin to distinguish a signal
  from a first data point.

**Why.** "Market cap above $50k" is a filter: it matches thousands of tokens
forever. "Market cap crossed $50k, having been below it at the previous
observation" matches a handful and is genuinely new. This single rule is what
separates an opportunity engine from a leaderboard.

---

## 6. AD-04 — Signal Provider Interface

**Decision.** Generalise the contract in `app/analysts/base.py`. A provider is a
**pure function from an observation window to zero or more signal candidates** —
no I/O, no session, no clock.

Each provider declares the signal types it can emit and the inputs it requires.
When inputs are missing it returns an explicit **unavailable, with a reason** —
it never estimates. This is the contract `/smart-money/{mint}` already honours in
production.

Every candidate carries the same envelope:

`signal_type` · `direction` · `strength` (0–100, provider-normalised) ·
`evidence` · `reason_codes` · `provider_id` · `model_version` · `observed_at`

An orchestrator — the existing analyst orchestrator, widened — fans one window
across every registered provider and merges the results.

**Why.** Purity is what makes signals replayable over history, which is how
thresholds get tuned rather than guessed. It is also why the scoring engine and
the six analysts sit at 100% test coverage; the pattern is proven in this
codebase.

**Consequence.** Pump.fun graduation is **one provider**. Adding whale, builder,
or narrative intelligence later is a registry entry plus a pure module. The
engine imports the registry, never a provider — the same inversion ADR 0001
established for market data, and which ADR 0002 demonstrated holds under a whole
new vendor.

---

## 7. AD-05 — Opportunity model

Two levels, because signals expire independently but the opportunity is per
token.

**Opportunity** (header — extends `radar_tokens`)

`opportunity_id` · `token` (mint + identity) · `generation` · `status`
(pending / active / expiring / closed) · `priority` · `stage` ·
`detected_at` *(immutable)* · `last_confirmed_at` · `closed_at` · `peak_*`

**Signal** (`opportunity_signals` — the one new table)

`signal_id` · `opportunity_id` · `signal_type` · `provider_id` · `confidence` ·
`severity` · `strength` · `detected_at` · `last_confirmed_at` · `expires_at` ·
`confirmations` · `evidence` (JSONB) · `reason_codes` · `status`

**Why one new table.** Per-signal TTL, per-signal confirmation counting, and the
dedupe key all need row-level identity. A JSONB array on `radar_tokens` cannot
express them without scanning it on every expiry sweep. This table is necessary,
not incidental — the constraint against unnecessary tables is respected by there
being exactly one.

**`explanation` is deliberately not stored.** It is rendered from `reason_codes`
at read time, as `scoring/explain.py` does today, so wording changes never
require a migration.

**Stage and signal are orthogonal.** A token has exactly one `stage`
(pre-graduation / near-graduation / fresh-graduation / established) and
zero-to-many live signals. They can never duplicate one another.

---

## 8. AD-06 — Confidence

**Decision.** Deterministic, pure, and published. Four inputs, mirroring the
scoring engine's evidence machinery:

| Input | Effect |
| --- | --- |
| **Corroboration** | Independent providers reaching the same conclusion. Two agreeing is worth far more than one shouting. |
| **Persistence** | Consecutive confirmations, on a bounded decelerating curve — repetition alone cannot reach high confidence. |
| **Data quality** | Observation count and coverage of the inputs the signal depends on. |
| **Freshness** | Reuses the existing tier-relative freshness curve. |

**Rises** on confirmation, corroboration, and widening evidence.
**Falls** on missed confirmation windows, freshness decay, provider
unavailability, and contradiction by another provider.

Contradiction reduces confidence; it never deletes the signal. The disagreement
is itself information worth surfacing.

**Consequence.** The bonding-curve liquidity gap correctly *caps* confidence
rather than being hidden — consistent with how the platform already charges
missing data to evidence rather than estimating around it.

---

## 9. AD-07 — Explanation

**Decision.** Every opportunity answers *"why did this appear now?"* through one
reusable five-part structure, assembled from reason codes:

**Trigger** (what crossed) → **Boundary** (the threshold, published) →
**Delta** (from-value, to-value, over what window) → **Corroboration** (which
other providers agree) → **Limits** (what could not be checked, and why)

Reason codes are stable identifiers; prose is a rendering layer.

**Why.** Translatable, diffable across model versions, and testable without
string matching. The "Limits" clause is not optional — it is where the platform's
honesty principle lives.

---

## 10. AD-08 — Ranking

**Decision.** `priority = severity × confidence × freshness`, with **evidence as
a gate, not a multiplier**: below an evidence floor an opportunity is not ranked
at all.

`severity` is a published per-signal-type constant — fresh graduation outranks a
mild volume expansion. Ties break on `detected_at` descending. Weights are
published at an endpoint, as `/scores/model`, `/radar/categories` and
`/analysts/model` already are.

**Why a gate rather than a multiplier.** A multiplier lets a confident-looking,
thinly-evidenced signal climb the board. A gate cannot.

**Ranking must be reproducible from stored fields alone** — no hidden state — so
any past board can be reconstructed exactly.

**The AI score becomes a ranking input, not the admission gate.** Admission
answers "did something change"; the score answers "how good is what changed".
Today one mechanism does both jobs, and is bad at the first.

---

## 11. AD-09 / AD-10 — Deduplication and expiry

### Deduplication

- **Opportunity identity** = `(mint_address, generation)`, unique. One card per
  token, always.
- **Signal identity** = `(opportunity_id, signal_type, provider_id)`, unique
  among live rows. Re-detection **updates** `last_confirmed_at` and increments
  `confirmations`; it never inserts.

Near Graduation + Pre-Breakout + Liquidity Surge is therefore **one opportunity
with three live signals**, each with its own TTL and confidence.

The database constraint is the guarantee; application checks are an optimisation
only — the same division the scanner already relies on with `ON CONFLICT DO
NOTHING`.

Reopening after close creates a **new generation**, never a resurrection: two
separate calls must remain separately measurable in the permanent record.

### Expiry

TTL is a property of the signal type, configured, never global:

| Signal | TTL | Rationale |
| --- | --- | --- |
| Near graduation | hours | Resolves quickly, either direction |
| Fresh graduation | ~48 h | A bounded, factual window |
| Breakout | hours | Confirmed or invalidated fast |
| Pre-breakout | ~1 day | Realised → re-enters as breakout |
| Liquidity / volume surge | hours – 1 day | Baseline itself moves |
| Community / narrative | days | Slower-moving by nature |

**Four independent exit paths:**

1. **Expiry** — TTL elapsed.
2. **Invalidation** — the transition reversed.
3. **Realisation** — the predicted thing happened. Exit, then possibly re-enter
   as a different signal.
4. **Evidence staleness** — enrichment stopped succeeding on that token.

The fourth is the lesson of `MEMESCOPE_AUDIT.md` §3.5 and Sprint 2: absence of
fresh data must *expire* an opportunity, never freeze it in place. A stalled
pipeline must produce an empty board, not a stale one. **An empty Radar is a
truthful Radar.**

An opportunity closes when its last live signal expires. A Celery beat task
sweeps expiries on the existing cadence and can only ever *close* — it cannot
open, which keeps detection on exactly one path.

---

## 12. AD-11 — Event model

**Decision.** Every state transition appends to `intelligence_events`, which is
already immutable, already uniquely keyed on `(mint, kind, occurred_at)`, and
already indexed for both per-token and chronological reads.

Event kinds: `opportunity_opened` · `signal_added` · `signal_confirmed` ·
`confidence_changed` · `signal_expired` · `opportunity_closed`, plus outcome
events for peak and return.

**The live board is a projection over the log, not a parallel truth.** One write
powers the timeline, per-token history, watchlist deltas, alerts, backtesting and
performance reports.

Because signals are pure functions of stored windows (AD-04), historical replay
under new thresholds is possible — which is how thresholds get tuned rather than
guessed.

Alerts read the **projection**, not the event stream, satisfying the roadmap's
standing requirement that alerts read state rather than depend on delivery.

Closed opportunities are archived, never deleted: immutable `detected_at` and
peak tracking continue to feed Hall of Fame and Hall of Lessons. The permanent
record contract from Phase 8/9 is unchanged.

---

## 13. AD-12 — Integration

| Component | Role after |
| --- | --- |
| **Scanner** | Unchanged. Feeds the watch universe. No longer the source of opportunities, so the platform stays useful while the Helius quota block persists. |
| **Market enrichment** | Unchanged, and becomes **the clock**. Detection runs when a snapshot lands, not on a timer, so work scales with change rather than table size. The 48-bucket sweep over 24 k tokens disappears. |
| **Radar** | Becomes the **read model**. `radar_tokens` is the opportunity header; the API keeps its shape. No frontend change is forced. |
| **Scoring** | Becomes a provider *and* a ranking input. The engine is untouched; its purity tests stay intact. |
| **Watchlists** | Subscribe to opportunity events by mint — `/watchlists/{id}/events` already expresses this. |
| **Alerts** | The first genuinely unblocked roadmap feature: read live opportunities, deliver, mark delivered. |

**Infrastructure reuse.** Celery for the expiry sweep and orchestration; Redis
for fan-out on the environment-namespaced channels; `intelligence_events` for
the log; `radar_tokens` for the header.

**Migration surface:** one new table plus columns on `radar_tokens`. Additive
throughout — no existing route changes shape, no table is rewritten.

---

## 14. Data availability — what can actually be built

Signals are only designed for data the platform holds. Of the twelve change
types in the vision, four are computable today:

| Signal | Status | Basis |
| --- | --- | --- |
| **Fresh graduation** | ✅ Available | `dex_name` transitions `pumpfun` → `pumpswap`. Unambiguous, already stored |
| **Near graduation** | ✅ Available | `market_cap` against the published threshold |
| **Pre-breakout / breakout** | ✅ Available | Price and volume series |
| **Volume expansion** | ✅ Available | `volume_5m` / `volume_1h` / `volume_24h` |
| **Liquidity expansion** | ⚠️ Post-graduation only | `liquidity_usd` is null for **100 %** of bonding-curve rows (ADR 0002) |
| **Accumulation** | ⚠️ Partial | Buy/sell counts exist; wallet-level accumulation does not |
| **Holder growth** | ❌ Blocked | No holder data anywhere in the schema |
| **Whale accumulation / smart money** | ❌ Blocked | No wallet addresses or transactions |
| **Community / narrative** | ❌ Blocked | Token name and symbol are the only text held |
| **Builder activity** | ❌ Blocked | No source |

Blocked providers **register as declared-unavailable with a reason** rather than
being omitted or estimated. The gap stays visible in the API surface, as
`/smart-money/{mint}` already does.

Closing the bonding-curve liquidity gap unlocks liquidity signals across ~97 % of
the universe and is the highest-value unblock behind this vision. ADR 0002
records why the built solution was reverted and what it needs before re-enabling.

---

## 15. Sequencing

1. **Fresh graduation.** A clean transition on data already stored, needing no
   new source. Validates the entire pipeline end to end — provider contract,
   confirmation, event log, projection, expiry — on the smallest honest signal.
2. **Near graduation.** Same substrate, adds a published threshold.
3. **Breakout / pre-breakout.** Introduces multi-observation windows and the
   realisation exit path.
4. **Liquidity signals.** Gated on ADR 0002's re-placement work.
5. **Blocked providers.** Registered as unavailable until a data source exists.

Sprint 1 and Sprint 2 remain prerequisites in spirit: detection riding enrichment
writes assumes enrichment is healthy and observable, which is what the pipeline
health surface now reports.

---

## 16. Open questions

Recorded rather than guessed, to be settled with measurement during
implementation:

- **Graduation threshold provenance.** Pump.fun's threshold is a protocol
  constant that has changed before. Read from configuration; consider deriving it
  from observed `pumpfun` → `pumpswap` transitions rather than hardcoding.
- **Confirmation window per tier.** A fresh-tier token is observed every 30 s and
  an old-tier one every 6 h. "Two consecutive observations" means very different
  things; the confirmation requirement is probably tier-relative.
- **Baseline for surge detection.** Volume and liquidity surges need a baseline.
  Trailing median over the token's own window is the likely answer, but the
  window length is an empirical question.
- **Board size.** Unbounded live opportunities is not a product. Whether the
  bound is a ranking cutoff, an evidence floor, or a hard limit should be decided
  against real detection volume, not in advance.
- **Backfill.** Whether to replay history to seed the first board, or start empty
  and let it fill. Starting empty is more honest; starting seeded demonstrates
  the product sooner.

---

## 17. Consequences

**Good**

- Work becomes proportional to change rather than to table size — the sweep over
  24 k tokens disappears.
- One write to the event log powers six read surfaces.
- Adding an intelligence source is a registry entry, not an engine change.
- Alerts, the rotation engine and backtesting all become reachable from the same
  substrate.
- The platform stops depending on the scanner for its core value.

**Costs**

- One new table and a set of columns on `radar_tokens`.
- Detection latency is now bounded by enrichment cadence — a fresh-tier token is
  seen within 30 s, an old-tier one within 6 h. Acceptable, and explicit.
- Four of twelve vision signals are buildable now. The rest are declared, not
  delivered, until their data exists.
- Reason-code rendering adds a layer between detection and display. Worth it: it
  is what keeps explanations out of migrations.

**Accepted risk**

- The board can be empty. This is correct behaviour and must not be
  "fixed" by relaxing admission — an empty board means nothing changed, which is
  information, not a bug.

---

*Recorded 2026-08-02, before implementation. Amendments belong in this document
with a date, in the style of ADR 0002's field-result addendum — not as silent
edits.*
