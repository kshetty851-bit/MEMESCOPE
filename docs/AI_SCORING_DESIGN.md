# AI Scoring Engine — Technical Design

- **Status:** Proposed, awaiting approval
- **Document revision:** Rev 2 (supersedes Rev 1 after design review; see §22)
- **Date:** 2026-07-27
- **Milestone:** Day 4
- **Author:** Backend architecture
- **Supersedes:** `frontend/src/lib/intelligence.ts` (provisional client-side heuristics)

> **Naming note.** "Rev 1 / Rev 2" refer to revisions of *this document*. `v1`,
> `v2` refer to *scoring model versions* (weight vectors). They are independent:
> this Rev 2 document specifies scoring model `v1`.

---

## 0. Summary and the argument up front

This document specifies a **deterministic, versioned, explainable scoring engine**
that computes a 0–100 opportunity score, a separate confidence value, and a
structured explanation for every discovered token, on every market refresh.

Three positions are deliberate departures from the obvious reading of the
roadmap. They are argued in §17 but stated here because everything follows from
them:

1. **There is no machine learning in Day 4, and no LLM anywhere in the scoring
   path.** We have no labels — the platform has been collecting data for days and
   we do not yet know which tokens rugged or ran. A supervised model without
   outcomes is a guess with extra steps. The engine is a transparent weighted
   feature model whose *reproducibility* (§2.1) makes a later ML combiner a
   drop-in replacement rather than a rewrite.

2. **Most of the inputs the roadmap lists for Day 4 do not exist yet.** Holder
   distribution, contract authorities, LP burn, and smart-money wallets are
   Day 5–6 data collection; narrative is Day 7. Scoring them now would mean
   fabricating them. The engine declares its full target weight vector, marks
   unavailable components explicitly, renormalises the available ones, and
   **charges the difference to evidence**. Evidence is capped at 0.65 in v1, so
   the Elite gate is unreachable until Day 6. Gold stays dark. That is the
   correct outcome, not a limitation to work around.

3. **Risk is a multiplicative gate, not a weighted addend.** A linear sum lets
   strong momentum offset a fatal liquidity structure. We have direct evidence
   this fails: the comment at `frontend/src/lib/intelligence.ts:124` records that
   the first linear formulation capped total risk at 0.75, so a textbook rug —
   $50 of liquidity behind a $5M valuation — scored "moderate". Multiplication
   and hard vetoes cannot be out-voted.

---

## 1. Goals

| # | Goal | Success criterion |
|---|------|-------------------|
| G1 | Score every enriched token continuously | Every token with ≥1 market snapshot has a current score row within one refresh interval of its latest snapshot |
| G2 | Never fabricate a signal | Every component maps to stored data; unavailable components are reported as unavailable, never imputed |
| G3 | Explain every score | Every score carries per-component contributions and stable reason codes sufficient to render "why" without back-reference to the engine |
| G4 | Separate conviction from evidence | Score, evidence, and freshness are independent axes; none inflates the score |
| G5 | Reproducibility | The score tier-1 set (§2.1) is a pure function of `(stored data, model version)` and is recomputable exactly |
| G6 | Auditability across time | Every stored score carries `model_version`; scores from different versions are never silently compared |
| G7 | Zero impact on discovery and enrichment | A scoring failure degrades to "no score"; snapshots and discovery are never lost, delayed, or blocked |
| G8 | Rank tokens cheaply and stably | Ranked reads are keyset-paginated over an indexed scan, with no page-boundary duplication |
| G9 | Never serve stale evidence as fresh | Confidence decays with wall-clock time at read time, not only at write time |
| G10 | Replace the client heuristics | The API contract covers every field `intelligence.ts` derives, so that file is deleted rather than reinterpreted |
| G11 | Make Days 5–7 additive | Adding a component is a new module plus a weight-vector entry; no changes to the engine, schema, API shape, or worker |

## 2. Design principles

### 2.1 Reproducibility, stated precisely

Rev 1 claimed the score was "a pure function of stored data". Review showed that
was false once EMA smoothing entered, because the smoothed value depended on the
sequence and timing of prior evaluations — most of which are deliberately never
stored (§8.3). Rev 2 removes write-time smoothing (§7.1) and replaces the vague
claim with a two-tier contract.

**Tier 1 — strongly reproducible.** `score`, `market_risk`, `evidence`,
`coverage`, `grade`, and every component contribution are pure functions of
`(DiscoveredToken, snapshots in window, model version)`. No dependence on any
prior score. `evaluate()` performs **no I/O**: no database, no network, no clock,
no randomness. Time enters as an explicit `now`, exactly as
`RefreshScheduler.decide()` already does (`app/services/market/scheduler.py`).

**Tier 2 — replay-reproducible.** `is_elite` and `elite_streak` depend on
sustained qualification and are therefore path-dependent. They are derived from
`token_score_history` — itself stored data — and are exactly reproducible by
replaying history rows in ascending `evaluated_at`. `rescore_tokens` does exactly
that, in order, per token.

**Tier 3 — not stored at all.** `freshness` and the served `confidence` are
computed at **read time** from `evidence` and the age of the latest snapshot
(§9). They are never persisted, because a stored freshness is a lie the moment
it is written (finding 3).

This contract is what buys backfill, shadow deploys, trivial unit testing, and a
later ML combiner. It is also now testable — see §18.4.

### 2.2 Explainability is a stored artefact, not a rendering concern

The engine emits structured contributions and enum reason codes, never prose.
Prose is a presentation-layer template keyed by reason code. Explanations stay
testable, translatable, diffable across versions, and free of generation cost —
and the Observatory Log renders from real state rather than from a sentence the
backend guessed at.

### 2.3 Versioned model configuration lives in code

Weight vectors are frozen dataclasses in `app/services/scoring/models/`, selected
through a registry keyed by `SCORING_MODEL_VERSION` — the same pattern, for the
same reasons, as the provider registry in ADR 0001. Weights in a database table
would be mutable at runtime, invisible to code review, uncovered by tests, and
would make a stored score unreproducible. Transparency is served instead by
exposing the active config read-only at `GET /api/v1/scores/model`.

### 2.4 The engine knows nothing about enrichment

`services/scoring/` imports models and repositories. It does not import
`services/market/`, with one deliberate exception: it reads `SchedulePolicy` to
derive tier intervals (§6.1), because that policy is the single source of truth
for cadence and duplicating it would guarantee drift. The dependency is on a pure
frozen dataclass, not on the enrichment service.

---

## 3. Non-goals

Explicitly **out of scope for Day 4**:

- **Machine learning of any kind.** Revisited when labels exist (§19.1).
- **LLM involvement in the numeric path.** Its legitimate home is Day 7 narrative
  summarisation, and optionally prose generation *from* structured reasons.
- **Price prediction.** The score answers "how strong does this look right now,
  and how much evidence is behind it?" It does not forecast returns, and no field
  may imply otherwise.
- **Financial advice.** Grades are descriptive.
- **New data collection.** No holder queries, contract authority inspection, LP
  burn checks, or socials. Days 5–7, each arriving as a component behind the
  interface defined here.
- **Real whale intelligence.** Average trade size is a weak proxy and will not
  ship under Titan's name (§6.4).
- **Alerts.** Day 8. Day 4 publishes the events they will consume.
- **Per-user or per-risk-appetite scoring.** §17.G: a read-time re-rank, not a
  second score.
- **Multi-chain.** Chain-agnostic by construction; no chain-specific work now.
- **Backtesting UI.** An offline harness only (§18.6).

---

## 4. Architecture

### 4.1 Placement — two transactions, not one

```
                    ┌─────────────────────────────────────────────────┐
                    │           enrichment worker process             │
                    │                                                 │
                    │  TX-1 (existing, unchanged)                     │
  DexScreener ─────▶│   claim batch ─▶ fetch ─▶ write snapshots ─▶ COMMIT
                    │                                          │      │
                    │  ────────────────────────────────────────┼───── │
                    │  TX-2 (new, independent)                 ▼      │
                    │   ┌──────────────────────────────────────────┐  │
                    │   │        TokenScoringService               │  │ (I/O)
                    │   │  · load feature window (1 query)         │  │
                    │   │  · load current + last history (1 query) │  │
                    │   │  · call engine (pure)                    │  │
                    │   │  · upsert + conditional history insert   │  │
                    │   │  · COMMIT                                │  │
                    │   └──────────────────┬───────────────────────┘  │
                    │                      │                          │
                    │        buffered events, published AFTER commit  │
                    └──────────────────────┼──────────────────────────┘
                                           │
                    ┌──────────────────────▼──────────────────────┐
                    │              ScoringEngine                  │  (pure)
                    │  components ─▶ risk gate ─▶ composite       │
                    │  ─▶ evidence ─▶ grade ─▶ explanation        │
                    └──────────────────────┬──────────────────────┘
                                           │
              ┌────────────────────────────┼──────────────────────┐
              ▼                            ▼                      ▼
      token_scores                token_score_history      Redis score channel
      (current, scalars only)     (append-only, detail)    (after commit only)
              │                            │                      │
              └──────────────┬─────────────┘                      ▼
                             ▼                             API WS multiplex
                    REST /scores endpoints                 ─▶ Observatory Log
```

**Scoring runs in its own transaction, after the enrichment transaction commits.**
Rev 1 placed it inside the enrichment transaction behind a savepoint. Review
found two problems with that (findings 5 and 12): `claim_due` holds row locks on
`token_enrichment_state` until commit
(`app/repositories/market.py:221-253`), so scoring latency directly extended a
lock-holding transaction across every replica; and the savepoint mechanism was
solving a problem that separation solves more simply.

A second transaction gives the same guarantee — **snapshots always commit,
whatever scoring does** — with no savepoint, no extended lock hold, and no
special error handling. The cost is a crash window between the two commits where
a snapshot exists without a score. `score_sweep` (§12) closes it, and must do so
anyway for deploys and restarts.

### 4.2 Module layout

```
backend/app/services/scoring/
├── __init__.py
├── engine.py            ScoringEngine.evaluate() — pure, no I/O
├── features.py          FeatureSet + windowing (pure)
├── normalisers.py       bounded monotone transforms
├── components/
│   ├── base.py          ScoreComponent protocol
│   ├── liquidity.py  momentum.py  trade_flow.py
│   ├── valuation.py  survival.py
│   └── market_risk.py   the gate — returns a penalty, not a contribution
├── models/
│   ├── base.py          ModelConfig, ComponentWeight (frozen dataclasses)
│   ├── v1.py            MODEL_V1
│   └── registry.py      get_model(version) — fails loudly on unknown
├── weighting.py         renormalisation + cap redistribution (§8.2)
├── evidence.py          coverage · depth  (time-invariant)
├── freshness.py         read-time decay  (used by schemas, not by the engine)
├── explain.py           ReasonCode enum, severity, templates
├── grading.py           score → Grade band; Elite gate over history
└── service.py           TokenScoringService — the only module doing I/O

backend/app/models/score.py            TokenScore, TokenScoreHistory
backend/app/repositories/score.py      ScoreRepository, ScoreHistoryRepository
backend/app/schemas/score.py           API contracts (own the freshness computation)
backend/app/api/v1/endpoints/scores.py routes
backend/app/core/cache.py              first cache helper (§14)
```

Layering matches the existing split: routers → read-side query service →
repositories, with the write path owned by the worker and a separate read service
for the API — mirroring `MarketEnrichmentService` vs `MarketQueryService`, so the
API has no path to trigger a write.

---

## 5. Data flow

### 5.1 Steady state, per enrichment cycle

**TX-1** — unchanged: claim batch, provider fetch, snapshot rows written, commit.

**TX-2** — new, in a fresh session:

1. **One query** loads the feature window for every mint in the batch:
   ```sql
   SELECT * FROM (
     SELECT *, ROW_NUMBER() OVER (PARTITION BY mint_address
                                  ORDER BY captured_at DESC) AS rn
     FROM token_market_snapshots
     WHERE mint_address = ANY(:mints) AND captured_at >= :window_start
   ) s WHERE s.rn <= :k
   ```
   `:window_start` is **per-tier**, not a global constant (§6.1, finding 2).
   Because tiers differ within a batch, the batch uses the widest window in the
   set and each token's features are then trimmed to its own window in memory —
   one round trip, no per-token queries.
2. **One query** loads `token_scores` plus each token's most recent
   `token_score_history` row (for delta, materiality, and Elite streak).
   `DiscoveredToken` and `TokenEnrichmentState` are already in memory from TX-1.
3. Per token: build `FeatureSet` (pure) → `ScoringEngine.evaluate()` (pure).
4. **Bulk upsert** `token_scores` with a monotonic guard (§11.1, finding 4).
5. **Conditional bulk insert** into `token_score_history` — material changes only
   (§8.3), plus an unconditional row on a token's first-ever evaluation.
6. **Commit.**
7. **After commit**, publish buffered events to Redis, fire-and-forget
   (finding 5). Matching the scanner, which commits at
   `app/services/scanner/scanner.py:302` and publishes at `:313`.

### 5.2 Backfill and recompute

- **`score_sweep`** — periodic. Picks up tokens with snapshots but **no current
  score, or a current score older than their tier's staleness bound** (finding 3).
  Rev 1 covered only the missing case.
- **`rescore_tokens(model_version, mode)`** — walks tokens in ID order and
  recomputes from stored snapshots. `mode="promote"` writes current rows under
  the monotonic guard; `mode="shadow"` writes only history rows tagged with the
  candidate version and serves nothing. Tier-2 quantities are reconstructed by
  replaying each token's history in ascending `evaluated_at`.

### 5.3 Event flow

Scores publish to a **separate channel**, `memescope:scores:changed`; the
discovery channel is untouched.

```json
{
  "type": "score_changed",
  "mint_address": "…",
  "score": 71.4,
  "previous_score": 64.2,
  "evidence": 52.0,
  "grade": "strong",
  "is_elite": false,
  "primary_reason": "MOMENTUM_ACCELERATING",
  "model_version": "v1",
  "evaluated_at": "2026-07-27T18:04:11Z"
}
```

The event carries `evidence` (time-invariant), not `confidence` (read-time), so a
queued or replayed event can never assert a freshness that has since expired.

The API's `TokenEventBroadcaster` gains a second subscription and multiplexes
both channels onto `/tokens/stream` in a `{"type": …, "data": …}` envelope. This
is a breaking change to the WS payload shape — see §21.1.

---

## 6. Score components

### 6.1 Windowing — tier-relative

Rev 1 used a fixed 60-minute feature window. Review found this collides with the
Day 3 adaptive tiers (finding 2): at `ENRICHMENT_TIER_MATURE_INTERVAL_SECONDS=1800`
a mature token yields 2 snapshots in 60 minutes, and at
`ENRICHMENT_TIER_OLD_INTERVAL_SECONDS=21600` an old token yields 0–1 — permanently
capping `depth`, and therefore evidence, for every healthy token over a day old.

Rev 2 derives all windows from the token's tier:

```
tier            = SchedulePolicy.tier_for_age(age_minutes)     # reused, not duplicated
tier_interval   = SchedulePolicy.interval_for_tier(tier)
history_window  = clamp(K × tier_interval, 1 hour, 7 days)     # K = SCORING_FEATURE_WINDOW = 12
risk_window     = min(SCORING_RUG_WINDOW_SECONDS, history_window)   # default 1 hour
```

Resulting windows: fresh 1 h, young 1 h, mature 6 h, old 72 h — each holding up
to K snapshots, so `depth` can reach 1.0 in every tier.

The tier is computed from token age, **not** read from
`TokenEnrichmentState.tier`, which is nullable and unset before a token's first
result (`app/models/market.py:193`, finding 11). Deriving it removes both the
null case and a dependency on enrichment bookkeeping.

**Consequence to accept:** an old token's window spans days, so its price-trend
term compares observations far apart. The momentum component emits
`MOMENTUM_COARSE_SAMPLING` when mean sample spacing exceeds one hour, so the
readout is qualified rather than silently misleading.

### 6.2 Component contract

```python
@dataclass(frozen=True, slots=True)
class ComponentResult:
    id: ComponentId
    available: bool           # False ⇒ excluded from the sum, charged to coverage
    score: Decimal | None     # 0–100, None iff not available
    raw: dict[str, Decimal | None]
    reasons: tuple[ReasonCode, ...]
```

All arithmetic is `Decimal` end-to-end (finding 10, §8.4). `available=False` is a
first-class outcome, not an error.

### 6.3 Available in v1

**`liquidity_depth`** — Sentinel/Oracle. *Can you exit?* Absolute depth on a
log-saturating curve ($2k → 10, $25k → 50, $150k → 85, $1M → 100) combined 50/50
with depth ratio `liquidity/market_cap` (0.01 → 5, 0.05 → 45, 0.15 → 85, ≥0.30 →
100). Absolute depth alone rewards large-cap illiquidity; ratio alone rewards a
$300 pool behind a $1k cap. Unavailable when `liquidity_usd` is null — including
the known DexScreener gap for pump.fun bonding-curve pools (ADR 0001), which is
exactly why coverage feeds evidence.

**`momentum`** — Pulse. Ratios of `volume_5m` and `volume_1h` against a
uniform-rate baseline (`volume_24h/288`, `volume_24h/24`), log-compressed with
10× saturation, plus a price-trend term over the window. Weighted 0.4/0.35/0.25.
Requires `volume_24h > 0`; the price term needs ≥3 observations and is dropped
with `INSUFFICIENT_HISTORY` otherwise.

**`trade_flow`** — Pulse. Buy share through a band (0.5 → 50, 0.65 → 80, ≥0.75 →
95; 0.35 → 20, ≤0.25 → 5), multiplied by a participation factor from total trade
count (log-saturating, 2000 → 1.0) so that 3 buys and 0 sells does not read as
overwhelming demand.

**`valuation_structure`** — Oracle. `market_cap/FDV` near 1.0 scores high; a large
gap means supply overhang (≤0.3 → 20). An absolute FDV band penalises both dust
and implausible valuations for an hours-old token.

**`survival_age`** — Scout. Deliberately non-monotone: <5 min → 25, 30 min → 55,
2–24 h → 85, 3 d → 60, >7 d → 40. Minutes-old is unknown rather than good, and
week-old meme coins have usually spent their move. Always available.

### 6.4 Declared but unavailable in v1

| Component | Weight | Blocked on |
|-----------|--------|-----------|
| `contract_safety` | 0.15 | Day 6 — mint/freeze authority, LP burn, renouncement |
| `holder_distribution` | 0.12 | Day 5/6 — top-10 concentration, holder count |
| `smart_money` | 0.05 | Day 5 — wallet clustering, labelled wallets |
| `narrative` | 0.03 | Day 7 — social/attention signal |

**On `smart_money`:** average trade size is computable today and the client
heuristic uses it, but one $50k swap and fifty $1k swaps are indistinguishable
under it and it is trivially wash-traded. Shipping it as whale intelligence would
overstate the platform to users making money decisions. It is folded into
`trade_flow` as a minor participation input; Titan's panel reads "awaiting wallet
intelligence" until Day 5.

### 6.5 The risk gate — `market_risk`

Returns a penalty in [0, 1] plus optional hard vetoes. Not part of the weighted sum.

| Signal | Source | Contribution |
|--------|--------|--------------|
| Liquidity drawdown from peak **within `risk_window`** | window snapshots | ≥40% → +0.35, ≥70% → **veto** |
| Liquidity drawdown from peak **outside `risk_window`** | window snapshots | ≥70% → +0.20, no veto |
| Depth ratio below floor | `liquidity/market_cap` < 0.01 | +0.30 |
| Pool inactive | `trading_status = inactive` | **veto** |
| Sell dominance | `sells/(buys+sells)` > 0.65 | +0.20 scaled |
| Metadata unresolved | `metadata_status != resolved` | +0.10 |
| Absolute liquidity floor | `liquidity_usd` < $500 | +0.25 |

The in-window / out-of-window split is new in Rev 2. A 70% decline over three
days is decay; the same decline over twenty minutes is a rug in progress. Rev 1
conflated them, which would have vetoed every slowly-dying old token.

Liquidity drawdown remains the one genuine security signal available on Day 4,
and it exists only because Day 3 stored immutable history.

Vetoes clamp the score to `VETO_CEILING` (35), force `grade = "critical"`, and
set `is_elite = false` unconditionally.

---

## 7. Scoring pipeline

```
FeatureSet (windowed per §6.1)
   │
   ├─▶ results   = [c.evaluate(f) for c in model.components]
   ├─▶ available = [r for r in results if r.available]
   │
   ├─▶ if Σ weight(available) < MIN_SCORABLE_WEIGHT (0.15):
   │        └─▶ no score written; status = "insufficient_data"      ← new in Rev 2
   │
   ├─▶ coverage = Σ weight(available) / Σ weight(declared)
   ├─▶ effective_weights = renormalise_and_cap(available)           ← §8.2, new in Rev 2
   ├─▶ opportunity = Σ (effective_weight_i × score_i)
   │
   ├─▶ risk_penalty, vetoes = market_risk.evaluate(f)
   ├─▶ score = opportunity × (1 − RISK_LAMBDA × risk_penalty)
   │   if vetoes: score = min(score, VETO_CEILING)
   │
   ├─▶ depth    = min(1, observations / SCORING_MIN_OBSERVATIONS)
   ├─▶ evidence = 100 × coverage^1.0 × depth^0.75      (time-invariant, STORED)
   │
   ├─▶ grade = band(score)
   ├─▶ elite = elite_gate(score, evidence, risk_penalty, f, history_streak)
   │
   └─▶ ScoreResult(score, evidence, market_risk, grade, elite, components[], reasons[])
```

### 7.1 Smoothing removed

Rev 1 applied an asymmetric EMA to the stored score. Review found this made the
score path-dependent, breaking the reproducibility contract and rendering the
Rev 1 §18.4 test unsatisfiable (finding 1). Rev 2 removes write-time smoothing
entirely. The stored score is the pure gated score.

What smoothing was buying, and where each part now lives:

| Purpose | Rev 2 mechanism |
|---------|-----------------|
| Danger reported immediately | Free — no smoothing means no lag, which was the asymmetry's whole point |
| Suppress score jitter in history and events | Materiality thresholds (§8.3) |
| Conviction earned slowly | The Elite sustain requirement (§7.2), which is where it actually mattered |
| Stable headline for the UI | Grade bands (wide) plus the materiality deadband on grade transitions |

This is a net simplification: one fewer stored column, one fewer tuning
parameter, and a reproducibility guarantee that can be tested.

### 7.2 Elite gate

`score ≥ 85` **and** `evidence ≥ 70` **and** `risk_penalty ≤ 0.2` **and**
`liquidity_usd ≥ $25k` **and** the same qualification sustained across
`SCORING_ELITE_SUSTAIN_EVALUATIONS` (3) consecutive evaluations.

The gate uses `evidence`, not read-time confidence, so it is time-invariant and
unambiguous. The streak is derived by reading the token's recent history rows,
not by incrementing a mutable counter (finding 4).

Since evidence is capped at 0.65 in v1, **no token can be certified Elite until
Day 6.** Given the design bible's "gold that appears often is not gold", this is
the right failure mode and should be stated in the UI rather than engineered
around by lowering the threshold.

---

## 8. Weighting strategy

### 8.1 The v1 vector

```python
MODEL_V1 = ModelConfig(
    version="v1",
    components=(
        ComponentWeight("liquidity_depth",     0.20),
        ComponentWeight("momentum",            0.15),
        ComponentWeight("trade_flow",          0.12),
        ComponentWeight("valuation_structure", 0.10),
        ComponentWeight("survival_age",        0.08),
        ComponentWeight("contract_safety",     0.15),   # unavailable in v1
        ComponentWeight("holder_distribution", 0.12),   # unavailable in v1
        ComponentWeight("smart_money",         0.05),   # unavailable in v1
        ComponentWeight("narrative",           0.03),   # unavailable in v1
    ),
    risk_lambda=Decimal("0.8"),
    veto_ceiling=Decimal("35"),
    max_single_contribution=Decimal("0.35"),
    min_scorable_weight=Decimal("0.15"),
)
```

Declared weights sum to 1.00. Available weights sum to **0.65** — the ceiling on
coverage, and therefore on evidence, for every token in v1.

An invariant test asserts the sum is exactly 1.00 and that every declared
component resolves in the registry. A violation fails at import, matching the
project's fail-fast configuration discipline.

### 8.2 Renormalisation and the contribution cap — specified

Rev 1 left the interaction between renormalisation and `max_single_contribution`
undefined (finding 7). Concretely: a new token with no volume data has only
liquidity (0.20), valuation (0.10), and survival (0.08) available; renormalising
gives liquidity 0.526, over the 0.35 cap, with 0.176 of weight unaccounted for.

**Algorithm** (`weighting.py`), deterministic and terminating:

1. Renormalise available weights to sum to 1.0.
2. Cap any weight above `max_single_contribution`; record the excess.
3. Redistribute the total excess proportionally among **uncapped** components.
4. Repeat from 2, to a fixed point, at most 4 passes.
5. If all components are capped (i.e. `n × cap < 1.0`, so the cap is
   unsatisfiable), **relax the cap uniformly**: every component takes `1/n`. Emit
   `WEIGHT_CAP_RELAXED`.

Weights always sum to exactly 1.0 on exit. The score is never systematically
depressed by orphaned weight, and the invariant is asserted in the engine.

**Floor.** If available weight is below `min_scorable_weight` (0.15), no score is
produced at all: `status = "insufficient_data"`. Scoring a token on one component
is worse than declining to score it.

### 8.3 Materiality — when history is written

`token_scores` is upserted on every evaluation. `token_score_history` receives a
row when any of these holds, compared against the **most recent history row**
(not against a mutable column — finding 4):

- `|score − last_history.score| ≥ SCORING_HISTORY_MIN_DELTA` (2.0)
- grade changed **and** `|delta| ≥ SCORING_GRADE_DEADBAND` (0.5) — the deadband
  stops a token oscillating across a band edge from writing a row per evaluation
- `is_elite` toggled
- a veto engaged or cleared
- more than `SCORING_HISTORY_MIN_INTERVAL_SECONDS` (300) since the last row
- the token has no history row at all (first evaluation — always written, which
  guarantees §11.2's detail lookup always resolves)

Without this, a 30-second tier writes 2,880 near-identical rows per token per day
and the Observatory Log becomes noise, violating "entries should come only from
genuine backend events."

### 8.4 Numeric discipline

All engine arithmetic is `Decimal` in a 28-digit context, quantized to 2dp with
`ROUND_HALF_EVEN` at exactly two points: emitting a `contribution`, and
persisting a score.

Rev 1 asserted contributions reconcile exactly to the total "thanks to Numeric",
which was false for float arithmetic rounded independently (finding 10). Rev 2
specifies the rule that makes it true: **contributions are quantized in
descending order and the largest absorbs the rounding residual**, so
`Σ contributions − risk_deduction == score` exactly, by construction. This is a
hard invariant, asserted in the engine and tested in §18.1.

---

## 9. Confidence — split into stored evidence and read-time freshness

Rev 1 stored a single `confidence` computed at write time. Review found its
dominant term decays with wall-clock time, so a stalled or dead-lettered token
served a confidence figure computed when its data was fresh (finding 3).

Rev 2 splits the axis:

```
# Time-invariant, computed by the engine, STORED
coverage  = Σ weight(available) / Σ weight(declared)
depth     = min(1, observations / SCORING_MIN_OBSERVATIONS)      # default 3
evidence  = 100 × coverage^1.0 × depth^0.75

# Time-dependent, computed at READ time, never stored
age       = now − latest_snapshot_at
freshness = clamp(1 − age / (3 × tier_interval), 0, 1)
confidence = evidence × freshness^0.5
```

Multiplicative throughout, so any collapsed factor collapses the result — the
honest behaviour. A token with perfect market data but one snapshot has seen one
instant of its life; a token whose last snapshot is twenty minutes stale in a
30-second tier is being reported on from memory, and now the API says so
**without anything having to recompute the row**.

`tier_interval` at read time is derived from token age via `SchedulePolicy`, the
same pure function used at write time (§6.1), so read and write agree by
construction.

The engine records the **limiting factor** as a reason code —
`CONFIDENCE_LIMITED_BY_COVERAGE` / `…_HISTORY`; the read layer adds
`CONFIDENCE_LIMITED_BY_FRESHNESS` when freshness is the smallest term — so the UI
can say which, rather than showing an unexplained number.

**Consequence:** with coverage capped at 0.65, evidence cannot exceed 65 in v1,
and the Elite gate requires 70. See §7.2.

---

## 10. Explainability model

### 10.1 Stored structure

The `components` JSONB array lives on **`token_score_history` only** (§11,
finding 6):

```json
[
  {
    "id": "liquidity_depth",
    "agent": "sentinel",
    "available": true,
    "score": "62.50",
    "declared_weight": "0.20",
    "effective_weight": "0.308",
    "contribution": "19.24",
    "raw": {"liquidity_usd": "48200.0000", "depth_ratio": "0.061"},
    "reasons": ["LIQUIDITY_ADEQUATE"]
  },
  {
    "id": "contract_safety",
    "agent": "sentinel",
    "available": false,
    "score": null,
    "declared_weight": "0.15",
    "effective_weight": "0.000",
    "contribution": "0.00",
    "raw": {},
    "reasons": ["COMPONENT_NOT_YET_IMPLEMENTED"]
  }
]
```

Decimals serialise as strings, matching how the market schemas already carry
`Decimal`. Contributions reconcile exactly to the score (§8.4), so the UI can
render a waterfall that provably adds up.

### 10.2 Reason codes

A stable `ReasonCode` StrEnum with severity (`info` / `positive` / `caution` /
`critical`), owning agent, and presentation template. **Append-only across model
versions** — removing a code is a breaking change to stored history.

Representative set: `LIQUIDITY_DEEP`, `LIQUIDITY_ADEQUATE`, `LIQUIDITY_THIN`,
`LIQUIDITY_DRAWDOWN_ACUTE`, `LIQUIDITY_DRAWDOWN_GRADUAL`, `DEPTH_RATIO_CRITICAL`,
`MOMENTUM_ACCELERATING`, `MOMENTUM_STEADY`, `MOMENTUM_DECAYING`,
`MOMENTUM_COARSE_SAMPLING`, `BUY_PRESSURE_DOMINANT`, `SELL_PRESSURE_DOMINANT`,
`PARTICIPATION_THIN`, `SUPPLY_OVERHANG`, `VALUATION_IMPLAUSIBLE`, `TOKEN_TOO_NEW`,
`SURVIVAL_ESTABLISHED`, `TOKEN_STALE`, `POOL_INACTIVE`, `METADATA_UNRESOLVED`,
`INSUFFICIENT_HISTORY`, `COMPONENT_NOT_YET_IMPLEMENTED`, `COMPONENT_ERROR`,
`WEIGHT_CAP_RELAXED`, `CONFIDENCE_LIMITED_BY_COVERAGE`,
`CONFIDENCE_LIMITED_BY_HISTORY`, `CONFIDENCE_LIMITED_BY_FRESHNESS`.

### 10.3 Observatory Log

Entries derive from **score transitions**, not evaluations. The event carries
`primary_reason` and the owning agent, so "Sentinel detected liquidity
withdrawal" is generated from `LIQUIDITY_DRAWDOWN_ACUTE` + `agent=sentinel` by a
template. No prose crosses the API, and every line traces to a stored reason code
on a stored row.

---

## 11. Database schema

Two tables, mirroring the enrichment split already proven in this codebase.
Rev 2 changes the column split between them (finding 6) and removes the snapshot
foreign key (finding 9).

### 11.1 `token_scores` — current state, scalars only

Rev 1 put the `components` JSONB here and rewrote it on every evaluation. At
~2 KB per row and ~43k evaluations/hour that is ~2 GB/day of WAL churn plus
continuous dead-tuple pressure on a ~10k-row table, with HOT updates unlikely
once the column TOASTs. The scalars change every cycle; the breakdown rarely
does. Rev 2 keeps this table narrow and puts detail in history.

| Column | Type | Notes |
|--------|------|-------|
| `id` | UUID PK | `UUIDPrimaryKeyMixin` |
| `token_id` | UUID FK → `discovered_tokens.id` ON DELETE CASCADE, **unique** | |
| `mint_address` | String(44), unique, indexed | denormalised, as snapshots do |
| `model_version` | String(32) | |
| `score` | Numeric(5,2) | 0.00–100.00 |
| `evidence` | Numeric(5,2) | time-invariant; **replaces stored `confidence`** |
| `coverage` | Numeric(5,2) | |
| `observations` | Integer | snapshots in the window |
| `market_risk` | Numeric(5,2) | 0–100, higher is worse |
| `opportunity_raw` | Numeric(5,2) | pre-gate; diagnosis |
| `grade` | Enum `score_grade` | critical / weak / watch / strong / high_conviction |
| `is_elite` | Boolean | |
| `has_veto` | Boolean | |
| `latest_snapshot_at` | timestamptz | **input to read-time freshness (§9)** |
| `evaluated_at` | timestamptz | also the monotonic guard key |
| `source_snapshot_captured_at` | timestamptz | provenance, **no FK** |
| `created_at` / `updated_at` | | `TimestampMixin` |

Removed from Rev 1: `components` and `reasons` (moved to history), `confidence`
(now read-time), `previous_score` and `elite_streak` (read-modify-write hazards —
derived from history instead), `source_snapshot_id` FK (finding 9: an enforced FK
into `token_market_snapshots` would block the partition detach/drop that snapshot
retention depends on; a timestamp carries the same provenance with no coupling).

Indexes:

```
ix_token_scores_mint             (mint_address) UNIQUE
ix_token_scores_ranking          (model_version, score DESC, mint_address)   ← keyset tiebreak
ix_token_scores_ranking_hot      (model_version, score DESC, mint_address)
                                 WHERE has_veto = false AND evidence >= 25   ← partial, §14.2
ix_token_scores_elite            (score DESC) WHERE is_elite
ix_token_scores_staleness        (evaluated_at)                              ← score_sweep
```

**Monotonic upsert** (finding 4). Three writers touch this table — inline
scoring, `score_sweep`, `rescore_tokens` — and `FOR UPDATE SKIP LOCKED` only
makes *enrichment replicas* disjoint. The guard makes a stale evaluation
unable to overwrite a fresher one:

```sql
INSERT INTO token_scores (...) VALUES (...)
ON CONFLICT (token_id) DO UPDATE SET ...
WHERE EXCLUDED.evaluated_at > token_scores.evaluated_at
   OR EXCLUDED.model_version <> token_scores.model_version
```

The `model_version` clause lets a promotion run overwrite regardless of
timestamp ordering, which is the one case where a "stale" write is intended.

**Numeric, not float**, for exact reproducibility — a golden test comparing 71.40
to 71.40000000000001 across platforms is a test that fails for no reason.

### 11.2 `token_score_history` — append-only, carries the detail

Score scalars as above, minus mutable bookkeeping, plus:

| Column | Type | Notes |
|--------|------|-------|
| `components` | JSONB | §10.1 — written only on material change |
| `reasons` | JSONB | ordered reason codes |
| `delta` | Numeric(5,2) | vs the previous history row |
| `trigger` | String(32) | `delta` / `grade_change` / `elite_change` / `veto_change` / `heartbeat` / `first` |

```
ix_score_history_mint_evaluated  (mint_address, evaluated_at DESC)
ix_score_history_evaluated       (evaluated_at DESC)
```

The per-token detail endpoint reads the latest row via
`(mint_address, evaluated_at DESC) LIMIT 1` — an index lookup, no maintained
pointer, and no FK into a table that may be partitioned. §8.3 guarantees a first
row always exists, so the lookup always resolves for a scored token.

Time-partitioning is deferred, exactly as for snapshots, but the append-only
shape and the absence of inbound FKs keep it available.

### 11.3 On a label/outcome table — deliberately not built

`token_score_history` records `(mint, score, evaluated_at)` and
`token_market_snapshots` records the complete price series, so forward returns at
any horizon are a join computable offline over data already stored. Building
`token_outcomes` now would add write load and a migration to precompute something
derivable. **Recommendation: do not build it.**

---

## 12. Background jobs

| Job | Trigger | Purpose |
|-----|---------|---------|
| Inline batch scoring | Every enrichment cycle, TX-2 | The main path (§5.1) |
| `score_sweep` | Celery Beat, every 15 min | Tokens with snapshots and **no score, or a score staler than `SCORING_STALE_AFTER_TIER_MULTIPLE` × tier_interval** — covers the TX-1/TX-2 crash window, deploys, and stalled enrichment |
| `rescore_tokens` | Manual / post-deploy | Backfill or shadow-evaluate a model version; resumable, batch-limited, replays history in order for tier-2 quantities |
| `prune_score_history` | Celery Beat, daily 03:30 | Retention: full history 30 days, then thinned to hourly |

`score_sweep`'s staleness arm is new in Rev 2 (finding 3): Rev 1 only caught
missing scores, which left a stalled token's row untouched indefinitely. Read-time
freshness (§9) already prevents that row from *reading* as fresh; the sweep exists
so the row also gets *corrected* rather than merely discounted.

No new process is introduced — `worker` and `scheduler` already exist in
`docker-compose.yml`.

---

## 13. APIs

New router `app/api/v1/endpoints/scores.py`, mounted twice like `market.py`.

### 13.1 `GET /api/v1/tokens/{mint}/score`

```json
{
  "mint_address": "…",
  "score": {
    "score": "71.40",
    "confidence": "49.70",
    "evidence": "52.10",
    "freshness": "0.91",
    "market_risk": "18.00",
    "coverage": "65.00",
    "grade": "strong",
    "is_elite": false,
    "observations": 9,
    "has_veto": false,
    "model_version": "v1",
    "evaluated_at": "2026-07-27T18:04:11Z",
    "latest_snapshot_at": "2026-07-27T18:04:09Z",
    "previous_score": "64.20",
    "components": [ … §10.1 … ],
    "reasons": [
      {"code": "MOMENTUM_ACCELERATING", "severity": "positive", "agent": "pulse"},
      {"code": "CONFIDENCE_LIMITED_BY_COVERAGE", "severity": "info", "agent": "oracle"}
    ]
  },
  "status": "scored"
}
```

`confidence` and `freshness` are computed per request (§9) — the response is
never stale even if the row is. `previous_score` and `components` come from the
history join.

`score` is `null` and `status` is one of `not_scored` / `awaiting_market` /
`insufficient_data` / `scoring_disabled` when there is nothing to report. This
mirrors `TokenMarketRead.market: null` — an unscored token is a 200 with a null
body, never a 404, because the token exists and the absence is meaningful state.

Routes register regardless of `FEATURE_AI_SCORING_ENABLED`; the flag gates
computation, not the contract.

### 13.2 `GET /api/v1/tokens/{mint}/score/history`

Offset-paginated, newest first, `page` / `page_size` / `since` / `until` —
identical to `MarketHistoryPage`. Offset pagination is correct here: the table is
append-only, so pages are stable.

### 13.3 `GET /api/v1/scores/top` — keyset paginated

Rev 1 specified offset pagination with per-page cache TTLs. Review found that
pages populated at different instants over a ranking that changes every 30
seconds produce duplicates and omissions as rows migrate across boundaries
(finding 8). Rev 2 uses keyset pagination pinned to a ranking generation.

- **Cursor:** opaque base64 of `(score, mint_address, generation)`; sort key
  `(score DESC, mint_address ASC)` matches `ix_token_scores_ranking`, so deep
  pages cost the same as shallow ones.
- **Generation:** `floor(epoch / SCORING_RANKING_TTL_SECONDS)`. A paging session
  stays inside one generation, so the result set it walks is internally
  consistent. An expired generation returns `410 Gone` with code
  `ranking_generation_expired`, and the client restarts from the head.
- **Filters:** `min_evidence` (default 25), `max_risk`, `grade`, `elite_only`,
  `max_staleness_seconds`, `sort_by` ∈ {`score`, `evidence`, `evaluated_at`}.

Filtering is on **`evidence`, not `confidence`** — evidence is time-invariant and
therefore indexable, while confidence is computed per request. Freshness is
applied through `max_staleness_seconds`, which is a range predicate on
`latest_snapshot_at` rather than an unindexable expression.

**Response echoes what was filtered** (finding 13):

```json
{
  "items": [ … ],
  "next_cursor": "…",
  "generation_expires_at": "2026-07-27T18:04:31Z",
  "applied_filters": {"min_evidence": "25.00", "max_staleness_seconds": 1800},
  "matched_total": 412,
  "candidate_total": 9877
}
```

Rev 1's silent `min_confidence=25` default could empty the product's main ranking
endpoint with a 200 and no indication — particularly given finding 2, which
pinned mature tokens just above that threshold. Echoing the filters and both
counts makes the exclusion visible.

### 13.4 `GET /api/v1/scores/model`

Active model version, every declared component with weight, availability and
owning agent, grade band boundaries, Elite gate criteria, and the weighting
algorithm's parameters. Static per deploy. This is what makes §8's "these are
priors" verifiable rather than asserted.

### 13.5 Extension to `/market/trending`

`TrendingEntry` gains `score: TokenScoreRead | null` — additive, non-breaking, one
join on a page of ≤100 rows. Without it the discovery feed would issue N
follow-up requests to show a score per row.

### 13.6 Frontend cutover

| `TokenIntelligence` field | Replacement |
|---------------------------|-------------|
| `momentum` | component `momentum` |
| `risk` | `market_risk` + risk reason codes |
| `whale` | **removed** — no honest backing until Day 5 (§6.4) |
| `community` | **removed** — Day 7 |
| `confidence` | `confidence` (read-time) — and `evidence` where a stable value is wanted |
| `gemProbability` | `score` |
| `elite` | `is_elite` |
| `provisional` | `status != "scored"`, or low `coverage` |

Two fields disappear rather than being reimplemented. That is the design working
as intended: the client heuristic filled panels the backend could not yet justify.

---

## 14. Caching

### 14.1 What is not cached

**No per-token score cache.** `GET /tokens/{mint}/score` is a unique-index lookup
plus one indexed history lookup — sub-millisecond. Fronting it with Redis adds a
hop, serialisation, an invalidation path, and a staleness bug class to save
something already cheaper than the cache. Additionally, confidence is now
computed per request (§9), so a cached response would reintroduce exactly the
stale-freshness defect finding 3 removed. Caching this endpoint is now not merely
unnecessary but incorrect.

### 14.2 What is cached

| Surface | Strategy | TTL | Notes |
|---------|----------|-----|-------|
| `/scores/top` | Redis read-through; key = all filters + cursor + **`model_version`** + generation | 20 s | Generation and TTL are the same number, so a cached page never outlives the generation it belongs to |
| `/scores/model` | In-process, module-level | process lifetime | Immutable per deploy |
| `TrendingEntry.score` | None | — | Rides the existing trending query |

Two details: `model_version` in every key means a deploy invalidates naturally
rather than serving scores computed under old weights; and the ranking cache
needs single-flight protection (a short Redis lock around recomputation) so
expiry under load does not send every worker into the same scan.

`ix_token_scores_ranking_hot` — partial on `has_veto = false AND evidence >= 25` —
serves the default filter combination (finding 8's performance half). Non-default
filters fall back to the full ranking index, which is acceptable because they are
rare and the cache absorbs repeats.

This is the project's first cache; it introduces `app/core/cache.py`, deliberately
scoped to these two uses.

---

## 15. Performance

### 15.1 Budgets

| Operation | Budget | Basis |
|-----------|--------|-------|
| `evaluate()` per token | < 400 µs | ~20 `Decimal` operations; Decimal is ~3× float, still negligible |
| Feature window load per batch of 60 | 1 query, < 20 ms | Windowed read on `ix_snapshots_mint_captured_desc`, K=12, widest-tier window |
| Current + latest-history load | 1 query, < 8 ms | Indexed `IN` over ≤60 mints |
| Persist per batch | 2 statements, < 15 ms | Narrow upsert (§11.1) + conditional history insert |
| **TX-2 total per cycle** | **< 80 ms** | Outside TX-1, so it extends no lock hold |
| `GET /tokens/{mint}/score` p95 | < 30 ms | Two indexed lookups + serialisation |
| `GET /scores/top` p95 (cold) | < 90 ms | Keyset scan on the partial index; cached thereafter |

TX-1's duration — and therefore the lock hold on `token_enrichment_state` — is
**unchanged from Day 3**, because scoring moved out of it (finding 12). This is
the main reason the two-transaction split is worth the crash window.

### 15.2 Write volume

At `ENRICHMENT_BATCH_LIMIT=60` and a 5 s poll, the ceiling is ~12 tokens/s →
~43k evaluations/hour. Each is a narrow upsert (~150 bytes changed), batched to
~720 statements/hour. Rev 1's per-evaluation JSONB rewrite — ~2 GB/day of WAL —
is gone; JSONB is now written only on material change, expected at 5–15% of
evaluations plus the 5-minute heartbeat, cutting JSONB write volume by roughly an
order of magnitude.

### 15.3 Load-bearing indexes

`ix_snapshots_mint_captured_desc` (Day 3) carries the feature window query — the
hottest new read — unchanged. No new index on snapshots is required, which is a
good sign the Day 3 schema was designed correctly.

**Watch item:** the tier-relative window (§6.1) means old tokens read up to 72
hours of snapshot history. The `rn <= K` cut happens after the index range scan,
so a high-traffic old token with thousands of snapshots in-window pays for rows it
discards. If snapshot volume per token grows beyond ~10k rows, add
`AND captured_at >= now() - interval` tightening per tier, or a lateral join
taking K rows per mint. Not needed at current volumes; recorded so it is not
rediscovered.

---

## 16. Failure handling

**Scoring is never allowed to damage enrichment.** Snapshots are durable; scores
are derived and recomputable.

| Failure | Behaviour |
|---------|-----------|
| Component raises | Caught per component → `available=False`, reason `COMPONENT_ERROR`, logged with mint and component id. Score still produced from the rest, with lower coverage |
| Engine raises for one token | Caught per token; others in the batch proceed |
| TX-2 fails entirely | **TX-1 already committed** — snapshots are safe. Logged; `score_sweep` repairs |
| Crash between TX-1 and TX-2 | Snapshot without a score; `score_sweep` repairs |
| Redis publish fails | Logged at warning, swallowed. Events are best-effort and published only after commit, so the database is always the source of truth. Alerts (Day 8) must read state, never rely on event delivery |
| Available weight < 0.15 | No score row; `status="insufficient_data"` (§8.2) |
| Model version unknown | Registry raises at startup — process refuses to boot |
| Weights fail invariants | Import-time assertion failure |
| Feature window query times out | Batch scored with `observations=0` → depth collapses → evidence collapses. Degrades honestly |
| Concurrent stale write | Rejected by the monotonic guard (§11.1); no error, no lost update |
| Scoring disabled by flag | Service not constructed; endpoints report `scoring_disabled` |

Every degraded path lands in the score's own reason codes and in `coverage` /
`observations`, so a user sees "low confidence: insufficient history" rather than
an unexplained number. There is no failure mode in which the engine reports high
conviction on bad inputs — that property is why coverage multiplies rather than
adds.

---

## 17. Alternatives considered

**A. Score on read, in the API.** No tables, no worker changes. Rejected — no
history (so no events, no Observatory Log, no Day 8 alerts), N+1 feature queries
per page, ranking impossible without scoring every token per request, and scores
that vary with request timing rather than with data.

**B. A dedicated scoring worker fed by a queue.** The instinctive
"microservices" answer, and still wrong for v1. The only trigger is "a snapshot
was just written"; the computation is microseconds; the data is at hand. A queue
adds at-least-once delivery, ordering, lag monitoring, and a second failure
domain for nothing. Because `services/scoring/` does not depend on
`services/market/` (§2.4), extraction is a wiring change. **Revisit when:** TX-2
exceeds 20% of cycle wall-time, TX-2's own lock hold becomes contended, or a
component needs slow external I/O that cannot be served from precomputed state.

**C. Compute the score in SQL.** Rejected: untestable at the needed granularity,
cannot emit structured explanations, cannot be versioned with the code that reads
it, and puts the weight vector beyond code review.

**D. LLM-generated scores.** Rejected on every axis. Non-deterministic (identical
inputs, different scores — unauditable for users making money decisions), 200–2000
ms and real cost against ~43k evaluations/hour, and no information gain: an LLM
reading six numbers is a very expensive weighted sum that cannot show its
arithmetic. Legitimate uses are Day 7 narrative extraction and optionally
rendering prose *from* the structured reasons this engine emits.

**E. Train a model now.** Rejected: no labels. §11.3 shows labels are derivable
retroactively from data already stored, so nothing is lost by waiting.

**F. Percentile normalisation against the live cohort.** Tempting — self-calibrating,
no threshold tuning. Rejected because a token's score would depend on *other
tokens*, making "why did my score drop?" unanswerable when nothing about that
token changed (violates G3). Cohort percentile remains valuable as separately
reported context, never folded into the score.

**G. Per-user weight profiles.** Rejected as a scoring feature: N incomparable
scores, broken caching and ranking, impossible support. Stored per-component
contributions (§10.1) mean personalised *ranking* is a read-time re-rank over
history detail, needing no second engine.

**H. (Rev 2) Keep smoothing, store the EMA state.** Considered when resolving
finding 1. Rejected: it preserves path dependence, requires a mutable
read-modify-write column that finding 4 shows is racy across three writers, and
buys jitter suppression that materiality thresholds already provide. Removing it
was strictly cheaper than making it correct.

---

## 18. Testing strategy

### 18.1 Unit — pure, no fixtures (the majority)

- **Normalisers:** property-based (Hypothesis) — monotonic in their declared
  direction, output in [0, 100], `None`-safe, no NaN/Inf for any finite input.
- **Components:** table-driven per component, including every `available=False`
  path.
- **Weighting (§8.2):** weights sum to exactly 1.0 after renormalisation and
  capping, for every subset of available components including singletons; the
  cap-relaxation branch fires only when `n × cap < 1.0`; the algorithm terminates
  within 4 passes for all subsets (exhaustive over 2⁹ = 512 subsets — cheap and
  total).
- **Numeric discipline (§8.4):** `Σ contributions − risk_deduction == score`
  **exactly**, as Decimals, across the full golden corpus. Rev 1's version of this
  invariant was unsatisfiable; the residual-absorption rule makes it hold.
- **Risk gate:** each veto forces the ceiling; the acute-drawdown case is the
  priority test — an $80k → $12k pool inside `risk_window` must not score above
  35 no matter what momentum is supplied. The same decline *outside* the window
  must **not** veto (the Rev 2 split, §6.5).
- **Evidence:** any single factor at zero forces evidence to zero; the
  limiting-factor reason matches the smallest term.
- **Elite gate:** unreachable at coverage 0.65; reachable in a synthetic model
  with all components available; requires the full sustain streak.
- **Model config invariants:** weights sum to 1.00; ids resolve; grade bands
  contiguous and exhaustive; every reason code has a template.

### 18.2 Tier interaction (new in Rev 2 — finding 2)

A dedicated suite crossing every `RefreshTier` with realistic snapshot cadences,
asserting that **a healthy token in every tier can reach `depth = 1.0` and
therefore the coverage-limited evidence ceiling**. Rev 1 would have failed this
for `MATURE` and `OLD`, which is the bug that motivated it. Includes a token whose
tier changes mid-window.

### 18.3 Golden corpus

~40 hand-built `FeatureSet`s covering archetypes — healthy launch, acute rug,
gradual decay, dying pool, stale token, no-market token, single snapshot, missing
market cap, wash-traded pattern, single-component survivor (exercising §8.2's
floor and cap-relaxation) — with expected scores checked in. **Any weight change
shows its full blast radius as a diff in the pull request.** The highest-value
test artefact in the design.

### 18.4 Reproducibility — matched to the contract (Rev 2, finding 1)

Rev 1 asserted `rescore_tokens` reproduces byte-identical scores, which was
unsatisfiable under smoothing. Rev 2 tests the contract as actually stated in
§2.1:

- **Tier 1:** `evaluate()` on a stored `FeatureSet` reproduces `score`,
  `evidence`, `coverage`, `market_risk`, `grade` and every contribution
  bit-identically, in-process and across a fresh interpreter.
- **Tier 2:** `is_elite` / `elite_streak` reproduce when history is replayed in
  ascending `evaluated_at`, and are explicitly *not* asserted to reproduce under
  out-of-order replay.
- **Tier 3:** `freshness` and `confidence` are asserted to be absent from both
  tables — a schema test, so the split cannot silently regress.

### 18.5 Concurrency (new in Rev 2 — finding 4)

Rev 1 had no concurrency tests, which is how a lost-update race reaches
production. Against real Postgres:

- Two sessions upsert the same token; the older `evaluated_at` loses and the
  stored row is the newer one.
- `rescore_tokens` in promote mode overwrites despite an older timestamp, via the
  `model_version` clause — and does **not** overwrite a newer row of the *same*
  version.
- `score_sweep` and inline scoring racing the same token converge to the newer
  evaluation with no row corruption.
- Elite streak derived from history is unaffected by interleaved writers.

### 18.6 Integration (real Postgres, existing harness)

- TX-1 commits snapshots even when TX-2 raises; `score_sweep` then repairs.
- Materiality: a flat token yields one history row per heartbeat, not one per
  evaluation; a token oscillating across a grade boundary by <0.5 yields none.
- Read-time freshness: advancing the clock lowers `confidence` on an
  **unchanged** row — the direct test for finding 3.
- API: unscored token returns 200 with `score: null`; history pagination matches
  the market contract; `/scores/top` keyset paging returns no duplicates and no
  omissions while scores mutate between page fetches (the direct test for
  finding 8); an expired generation returns 410.
- Migration: forward and backward on a populated database (§21.2).

### 18.7 Calibration and the offline harness

Assert the corpus is not degenerate — spread above a floor, no more than 40%
inside one 10-point band. `scripts/score_backtest.py` replays stored snapshots
under one or more model versions and reports distributions, grade histograms,
veto rates, and coverage. A tool, not a test; used before promoting a version.

---

## 19. Future extensibility

**19.1 The ML path.** When history supports derived forward returns (§11.3), fit
a combiner over the same `ComponentResult` vector. Features, storage, explanation
structure, API shape, and worker integration are unchanged; `ModelConfig` gains a
`combiner` field and `v2` ships alongside `v1` in shadow mode. **Explainability
must survive the change** — a model whose contributions cannot be decomposed per
component does not meet G3 and should not ship, whatever its accuracy.

**19.2 Days 5–7 components.** Each is a new module, a registry entry, and a weight
in a new model version. `contract_safety` and `holder_distribution` need slow
on-chain reads and must **not** be fetched inline: they are computed by their own
workers into their own state tables and read as precomputed features, with their
own staleness feeding freshness. That constraint is why `ComponentResult.available`
exists from day one. As they land, coverage rises from 0.65 toward 1.0 and Elite
becomes reachable.

**19.3 Multi-chain.** `FeatureSet` contains no Solana-specific concepts. A second
chain needs a scanner and a provider, not a scoring change.

**19.4 Personalised ranking.** Read-time re-rank over stored components (§17.G).

**19.5 Score-driven refresh tiers.** Letting the score influence
`RefreshScheduler` is deliberately deferred: it creates a feedback loop — score
drives data density drives depth drives evidence drives score — that needs
thought before it ships. Rev 2's tier-relative windowing (§6.1) makes the loop
tighter, not looser, so this warning is now stronger than in Rev 1.

---

## 20. Configuration

| Setting | Default | Notes |
|---------|---------|-------|
| `FEATURE_AI_SCORING_ENABLED` | `false` | Exists already |
| `SCORING_MODEL_VERSION` | `"v1"` | Registry key; unknown value fails at boot |
| `SCORING_FEATURE_WINDOW` | `12` | K snapshots |
| `SCORING_WINDOW_MIN_SECONDS` | `3600` | Floor for `history_window` |
| `SCORING_WINDOW_MAX_SECONDS` | `604800` | Ceiling (7 days) |
| `SCORING_RUG_WINDOW_SECONDS` | `3600` | Acute-drawdown veto window |
| `SCORING_MIN_OBSERVATIONS` | `3` | Depth denominator |
| `SCORING_HISTORY_MIN_DELTA` | `2.0` | Materiality |
| `SCORING_GRADE_DEADBAND` | `0.5` | Band-edge oscillation guard |
| `SCORING_HISTORY_MIN_INTERVAL_SECONDS` | `300` | Heartbeat |
| `SCORING_ELITE_SUSTAIN_EVALUATIONS` | `3` | |
| `SCORING_STALE_AFTER_TIER_MULTIPLE` | `4` | `score_sweep` staleness bound |
| `SCORING_RANKING_TTL_SECONDS` | `20` | Cache TTL **and** ranking generation length |
| `SCORE_EVENT_CHANNEL` | `"memescope:scores:changed"` | |

---

## 21. Open questions and migration

### 21.1 Open questions for approval

1. **WebSocket envelope migration (§5.3).** Dual-emit for one release, or clean
   break coordinated with the frontend? The stream has no external consumers, so
   a clean break is cheaper — confirm no third party is attached.
2. **Elite unreachable in v1 (§7.2).** Confirmed as intended? The alternative —
   lowering the evidence threshold so gold can appear — is available and is
   recommended against.
3. **Grade band boundaries.** Proposed: critical <30, weak 30–49, watch 50–64,
   strong 65–79, high_conviction ≥80. Product-visible labels deserve a product
   decision.
4. **History retention.** Proposed 30 days full, then hourly thinning. Thinning
   is irreversible and degrades the tier-2 replay in §18.4 for old tokens —
   confirm against future backtesting ambitions.
5. **Public or authenticated.** Proposed public, matching tokens and market. The
   auth boundary is cheaper to place now than to retrofit.
6. **(Rev 2) `min_evidence=25` as the ranking default.** Now visible in the
   response (§13.3), but still a default that hides rows. Confirm 25, or ship
   with no default filter and let the frontend choose.

### 21.2 Migration risk

- **Additive only.** Two new tables, one new enum, one new nullable field on
  `TrendingEntry`'s response. No existing table is altered, so the migration is
  reversible and can ship ahead of the engine.
- **No FK into `token_market_snapshots`** (§11.1), so snapshot partitioning and
  retention remain unblocked — the single largest migration risk in Rev 1.
- **Enum `score_grade`** is a native Postgres enum, matching existing practice.
  Adding a grade later requires `ALTER TYPE ... ADD VALUE`, which cannot run
  inside a transaction in older Postgres — noted so the boundaries are decided
  before ship (open question 3), not after.
- **Backward migration** drops both tables; no data outside them is affected.
  Tested in §18.6.

---

## 22. Revision notes — Rev 1 → Rev 2

All thirteen review findings are resolved below. "Preserved" items are recorded so
it is clear what the review did *not* change.

| # | Finding | Resolution | Sections changed |
|---|---------|-----------|------------------|
| 1 | Smoothing made the score path-dependent; the reproducibility claim was false and the §18.4 test unsatisfiable | Write-time EMA removed entirely. Reproducibility restated as an explicit three-tier contract; jitter control moved to materiality thresholds and the Elite sustain rule | §2.1, §7.1, §17.H, §18.4, §11.1 (columns dropped) |
| 2 | Fixed 60-minute feature window collided with Day 3 adaptive tiers, permanently capping evidence for mature/old tokens | Windows are tier-relative: `clamp(K × tier_interval, 1 h, 7 d)`. Dedicated tier-interaction test suite added | §6.1, §18.2, §15.3 (watch item), §20 |
| 3 | Confidence stored at write time but decays with wall-clock time; stalled tokens served stale confidence as fresh | Split into stored `evidence` (time-invariant) and read-time `freshness`; `confidence` is computed per request and never persisted. `score_sweep` also refreshes stale rows | §9, §11.1, §12, §13.1, §14.1, §18.6 |
| 4 | Lost-update race between inline scoring, `score_sweep`, and `rescore_tokens`; `previous_score` and `elite_streak` were read-modify-write | Monotonic upsert guard on `evaluated_at`; both mutable columns removed and derived from history; concurrency test suite added | §11.1, §7.2, §8.3, §18.5, §16 |
| 5 | Redis publish ordered before commit — events could describe uncommitted scores | Events buffered during TX-2 and published after commit, matching the scanner's existing pattern | §5.1, §5.3, §16 |
| 6 | `components` JSONB rewritten on every evaluation (~2 GB/day WAL on a 10k-row table) | `token_scores` narrowed to scalars; JSONB detail moved to `token_score_history`, written only on material change; detail read via an indexed lookup | §11.1, §11.2, §10.1, §15.2 |
| 7 | Renormalisation × `max_single_contribution` left orphaned weight undefined | Explicit iterative redistribution algorithm with a cap-relaxation branch and a `min_scorable_weight` floor; exhaustive subset test | §8.2, §7, §18.1 |
| 8 | Offset pagination plus per-page cache TTLs caused duplicates and omissions | Keyset pagination pinned to a ranking generation; partial index for the default filter set; 410 on expired generation | §13.3, §14.2, §11.1 (index), §18.6 |
| 9 | `source_snapshot_id` FK would block snapshot partitioning and retention | Replaced with `source_snapshot_captured_at`; no FK into snapshots from either table | §11.1, §11.2, §21.2 |
| 10 | Float arithmetic made the exact-reconciliation invariant unsatisfiable | `Decimal` end-to-end with `ROUND_HALF_EVEN`, quantization at two defined points, and largest-contribution residual absorption | §8.4, §6.2, §10.1, §18.1 |
| 11 | `TokenEnrichmentState.tier` is nullable before a token's first result | Tier derived from token age via `SchedulePolicy.tier_for_age()`; the stored string is no longer read | §6.1, §2.4, §9 |
| 12 | Scoring inside TX-1 extended the lock hold on `token_enrichment_state` | Scoring moved to its own transaction after the enrichment commit; savepoint mechanism removed; lock hold added to the extraction triggers | §4.1, §5.1, §15.1, §17.B |
| 13 | `min_confidence=25` filtered silently | Response echoes `applied_filters`, `matched_total`, `candidate_total`; renamed to `min_evidence`; added as open question 6 | §13.3, §21.1 |

**Preserved from Rev 1** — reviewed and unchanged: the deterministic-over-ML
position and its reasoning (§0.1, §17.E); the coverage-driven honesty mechanism
and the resulting unreachable Elite gate (§0.2, §7.2); the multiplicative risk
gate (§0.3, §6.5); inline-in-worker over a queue (§17.B); the decision not to
build `token_outcomes` (§11.3); the no-per-token-cache stance (§14.1, now with a
second argument); component definitions and weights (§6.3, §8.1); the
explainability model (§10); and the module boundary that made findings 1, 3, 6,
and 12 fixable without touching the engine (§2.4).

**Net effect on the schema:** `token_scores` loses six columns (`components`,
`reasons`, `confidence`, `previous_score`, `elite_streak`, `source_snapshot_id`)
and gains three (`evidence`, `latest_snapshot_at`, `source_snapshot_captured_at`),
ending narrower and cheaper to update than Rev 1's.

---

## 23. Implementation order

Each step is independently reviewable and leaves the system working.

1. Schema + migration + repositories, including the monotonic upsert guard — merge with tests.
2. `normalisers.py`, `features.py` with tier-relative windowing, `weighting.py`, model config + registry; invariant and exhaustive-subset tests.
3. Components and the risk gate, with the golden corpus and the tier-interaction suite.
4. `engine.py`, `evidence.py`, `grading.py`, `explain.py` — pure, fully unit-tested, including the exact-reconciliation invariant.
5. `service.py` + TX-2 integration into the enrichment cycle; concurrency tests.
6. `score_sweep` (missing **and** stale), `rescore_tokens`, `prune_score_history`.
7. Schemas with read-time freshness, endpoints, `/scores/model`; integration tests.
8. Keyset pagination, ranking generation, `app/core/cache.py`.
9. Score events published after commit; WebSocket multiplexing.
10. `TrendingEntry.score`, then frontend cutover and deletion of `intelligence.ts`.

Steps 1–4 touch nothing that runs in production and can proceed in parallel with
review of this document.
