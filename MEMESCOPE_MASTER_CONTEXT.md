# MEMESCOPE — Master Context

> Single source of truth for the project: what it is, how it is built, what is
> done, what is true right now, and the rules any future work must follow.
>
> **Last verified:** 29 July 2026 (`v0.8.0-rc1`), against the running local
> stack, a full production-mode rehearsal, and a release audit.
> Every number in [§11](#11-verified-state) was measured, not remembered.

---

## Contents

1. [What MEMESCOPE is](#1-what-memescope-is)
2. [Status at a glance](#2-status-at-a-glance)
3. [Quick start](#3-quick-start)
4. [Architecture](#4-architecture)
5. [The AI Scoring Engine](#5-the-ai-scoring-engine)
6. [Data model](#6-data-model)
7. [API surface](#7-api-surface)
8. [Frontend](#8-frontend)
9. [Configuration and feature flags](#9-configuration-and-feature-flags)
10. [Design system](#10-design-system)
11. [Verified state](#11-verified-state)
12. [Engineering conventions](#12-engineering-conventions)
13. [Known issues and open questions](#13-known-issues-and-open-questions)
14. [Roadmap](#14-roadmap)
15. [Document map](#15-document-map)
16. [Production deployment](#16-production-deployment)
17. [Alpha experience](#17-alpha-experience-phase-6b)
18. [Production rehearsal](#18-production-rehearsal-phase-6c)
19. [Opportunity Radar](#19-opportunity-radar-phase-8)
20. [Exit Watch & the permanent record](#20-exit-watch--the-permanent-record-phase-9)
21. [Composite market provider](#21-composite-market-provider-phase-10)

---

## 1. What MEMESCOPE is

A production-grade AI crypto intelligence platform. It discovers newly launched
Solana tokens the moment they appear on-chain, enriches them with market data,
scores them with a deterministic AI engine, detects rugs, and presents the result
as an **orbital observatory** rather than a crypto dashboard.

The interface is operated by seven named AI divisions — Scout (discovery), Titan
(whale intelligence), Oracle (analysis), Pulse (momentum), Sentinel (security),
Echo (narrative), Apex (elite certification). They are a presentation layer over
real backend state, never a fiction: an agent panel that has no data source says
so explicitly.

**The founding rule, from which most decisions follow:** the frontend never
fabricates data. It renders backend state. Where the platform does not know
something, the product says it does not know.

---

## 2. Status at a glance

| Milestone | Scope | Status |
|---|---|---|
| Day 1 | FastAPI, Postgres, Redis, auth, Docker, CI, testing | ✅ Complete |
| Day 2 | Helius integration, Solana discovery, WebSocket, REST feed | ✅ Complete |
| Day 3 | DexScreener enrichment, snapshots, scheduler, circuit breaker | ✅ Complete |
| Frontend | Living Universe, Observatory, AI Core, Command Mode | ✅ Complete |
| Day 4 · Phase 1 | Scoring schema, models, repositories | ✅ Complete |
| Day 4 · Phase 2 | Pure scoring engine (100% coverage) | ✅ Complete |
| Day 4 · Phase 3 | `TokenScoringService`, worker integration, Celery jobs | ✅ Complete |
| Day 4 · Phase 4 | Scoring REST API | ✅ Complete |
| Day 4 · Phase 4.1 | Frontend cutover to real scores | ✅ Complete |
| Phase 5A | Observatory foundation — landing page reachable, dev login flow removed | ✅ Complete |
| Phase 5B | Immersive experience — observatory camera, compositor audit | ✅ Complete |
| Phase 5C | Sentinel AI operator — mission brief, narration, log grouping | ✅ Complete |
| Phase 6A | Private alpha deployment — Caddy, backups, deploy scripts, alpha UX | ✅ Complete |
| Phase 6B | Private alpha launch — About, feedback, onboarding, failure states | ✅ Complete |
| Phase 6C | Production rehearsal — six deployment defects found and fixed | ✅ Complete |
| Phase 8 | Opportunity Radar & track record — new intelligence layer | ✅ Complete |
| Phase 9 | Exit Watch, Hall of Fame/Lessons, leaderboards | ✅ Complete |
| Phase 10 | Composite market provider — bonding-curve liquidity fill | ✅ Complete |
| **v0.8.0-rc1** | **Stabilisation, versioning, audit, release preparation** | ✅ **Complete** |
| Launch | Deploy to a public host | ⬜ **Blocked: no server, domain or credentials** |
| Phase 5D | Polish — performance, accessibility, production optimisation | ⬜ Next |
| Day 5 | Smart Wallet Intelligence | ⬜ Queued |

**Quality gates, all green:** 2,364 backend tests (90% coverage), 113 frontend
tests, ruff, ruff-format, mypy strict, eslint, tsc. Production images build and
both production surfaces were verified from the built image — see
[§16](#16-production-deployment).

> **Phase 5A scope note.** The milestone as briefed also called for creating a
> landing page, Observatory shell, navigation and design system. All four already
> existed and were verified working, so they were left alone — the rule against
> redesigning completed systems outranks a brief written without them in view.
> The one item describing real work was removing the temporary development login
> flow, which turned out to be hiding the landing page. See [§9](#9-configuration-and-feature-flags).

> **Phase 5B scope note.** Likewise: the starfield, planet system, orbital
> motion, particle field, activity visualisation and signal pulses were all
> already built in `Universe`. The milestone delivered the one missing piece —
> the **camera** ([§8](#8-frontend)) — and the profiling, accessibility and
> compatibility verification that had never been done. **React Three Fiber was
> considered and rejected**; the reasoning is recorded in [§10](#10-design-system)
> because it is the kind of decision that gets re-proposed every six months.

---

## 3. Quick start

```bash
make up
```

### Ports — read this first

Host ports are **deliberately shifted** to avoid collisions with another local
project. This is the single most common source of confusion:

| Service | Host port | Container port |
|---|---|---|
| Frontend | 3000 | 3000 |
| **Backend** | **8001** | 8000 |
| **Postgres** | **5433** | 5432 |
| **Redis** | **6380** | 6379 |

`curl localhost:8000` will fail or hit something else entirely. The API is on
**8001**, and `NEXT_PUBLIC_API_URL` matches.

| Surface | URL |
|---|---|
| Frontend | http://localhost:3000 |
| API docs | http://localhost:8001/docs |
| Readiness | http://localhost:8001/ready |

```bash
make migrate      # apply migrations
make seed         # create a local admin
make check        # lint + typecheck + test, everything CI runs
make help         # every target
```

### Running processes

Eight containers: `postgres`, `redis`, `backend`, `frontend`, plus four workers —
`scanner` (Helius discovery), `enrichment` (DexScreener refresh + scoring),
`worker` (Celery), `scheduler` (Celery beat).

---

## 4. Architecture

### Request path

Requests enter through middleware that assigns a request id, applies rate limits
and sets security headers. **Routers handle HTTP only** and delegate to services,
which hold business rules and know nothing about FastAPI. Services use
repositories for all database access. Errors are raised as `AppError` subclasses
and rendered into one JSON envelope, so every failure looks the same to clients.
Anything slower than a request goes to Celery.

```
router → service → repository → database
```

This layering is not negotiable. No business logic in routers; no HTTP in
services; no external calls in repositories.

### Pipeline

```
        Helius WebSocket
               │
               ▼
      scanner ──▶ discovered_tokens ──▶ Redis channel ──▶ API WebSocket clients
                          │
                          ▼
      enrichment ──▶ token_market_snapshots        (TX-1, DexScreener)
                          │
                          ▼
      scoring    ──▶ token_scores + history        (TX-2, pure engine)
                          │
                          ▼
                  Redis score channel ──▶ (Day 8 alerts)
                          │
                          ▼
                  REST /api/v1/scores ──▶ Next.js frontend
```

### Two transactions, deliberately

Enrichment commits snapshots (**TX-1**), then scoring runs in its **own session**
(**TX-2**). Reasons:

- `claim_due` holds row locks on `token_enrichment_state` until TX-1 commits.
  Scoring inside it would extend that lock across every worker replica.
- Snapshots are the durable asset; scores are derived and recomputable. A scoring
  failure must never cost a snapshot.

The cost is a crash window where a snapshot exists without a score. `score_sweep`
closes it — which it has to do anyway, for deploys and restarts.

**Events publish after commit, never before.** An event published inside the
transaction can describe a score that never landed. Asserted by a test whose fake
Redis queries the database on its own connection at publish time.

---

## 5. The AI Scoring Engine

The centrepiece of Day 4. Full design: [`docs/AI_SCORING_DESIGN.md`](docs/AI_SCORING_DESIGN.md) (Rev 2).

### Three positions that shape everything

**1. No machine learning, no LLM in the scoring path.** We have no labels — the
platform has been collecting for days and we do not know which tokens rugged or
ran. A model trained on that would encode current guesses with a false veneer of
rigour. The engine is a transparent weighted feature model whose *purity* makes
an ML combiner a later drop-in. An LLM reading six numbers is an expensive
weighted sum that cannot show its arithmetic; its real home is Day 7 narrative.

**2. Missing signals are visible, not hidden.** Contract safety, holder
distribution, smart money and narrative have no data source yet. The model
declares them with real weight, marks them unavailable, renormalises the rest,
and **charges the gap to evidence**. Available weight sums to 0.65, so evidence
is capped at 65 — and the Elite gate needs 70. **No token can be certified Elite
until Day 6.** Gold stays dark. That is the correct outcome, not a bug.

**3. Risk multiplies, it does not add.** A linear sum lets strong momentum offset
a fatal liquidity structure. The frontend's old heuristic proved it: a linear risk
sum capped at 0.75, so a textbook rug scored "moderate". The gate multiplies and
can veto outright.

### The v1 model

| Component | Weight | Agent | Available |
|---|---|---|---|
| `liquidity_depth` | 0.20 | Sentinel | ✅ |
| `momentum` | 0.15 | Pulse | ✅ |
| `trade_flow` | 0.12 | Pulse | ✅ |
| `valuation_structure` | 0.10 | Oracle | ✅ |
| `survival_age` | 0.08 | Scout | ✅ |
| `contract_safety` | 0.15 | Sentinel | ⬜ Day 6 |
| `holder_distribution` | 0.12 | Titan | ⬜ Day 5/6 |
| `smart_money` | 0.05 | Titan | ⬜ Day 5 |
| `narrative` | 0.03 | Echo | ⬜ Day 7 |

Weights are **priors, not fitted parameters**, and are published at
`GET /api/v1/scores/model` so that claim is checkable rather than asserted.

### Pipeline

```
FeatureSet (tier-relative window)
  ├─▶ components → available? → coverage
  ├─▶ if available weight < 0.15 → status "insufficient_data", no score
  ├─▶ renormalise + cap (max 0.35 per component, excess redistributed)
  ├─▶ opportunity = Σ effective_weight × component_score
  ├─▶ score = opportunity × (1 − 0.8 × risk_penalty); veto ⇒ min(score, 35)
  ├─▶ evidence = 100 × coverage^1.0 × depth^0.75      ← stored
  ├─▶ grade = band(score); elite = gate(score, evidence, risk, liquidity, streak)
  └─▶ ScoreResult(+ components, reasons)
```

`freshness` and `confidence` are **never stored** — they are computed per request
from the age of the underlying snapshot, so a stalled token reads as stale
without anything having to rewrite its row.

### Reproducibility contract

| Tier | Fields | Guarantee |
|---|---|---|
| 1 — strong | score, market_risk, evidence, coverage, grade, contributions | Pure function of `(stored data, model version)`. Bit-identical on re-evaluation. |
| 2 — replay | `is_elite`, `elite_streak` | Reproducible by replaying history in ascending `evaluated_at`. |
| 3 — never stored | `freshness`, `confidence` | Computed at read time. Asserted absent from both tables. |

`evaluate()` performs **no I/O** — no database, network, clock or randomness.
Time enters as an explicit `now`. All arithmetic is `Decimal` inside a fixed
28-digit context, because `decimal.getcontext()` is thread-local and mutable and
output must not depend on what ran before.

**Exact reconciliation:** contributions are quantised in descending order with
the largest absorbing the residual, so `Σ contributions − risk_deduction ==
score` exactly. A waterfall that does not add up on screen is a bug users can see.

### Grade bands

| Grade | Range |
|---|---|
| critical | < 30 (or vetoed) |
| weak | 30–49 |
| watch | 50–64 |
| strong | 65–79 |
| high_conviction | ≥ 80 |

### Package layout

```
backend/app/services/scoring/
├── engine.py          evaluate() — pure entry point
├── features.py        FeatureSet + tier-relative windowing
├── normalisers.py     bounded Decimal transforms
├── components/        liquidity · momentum · trade_flow · valuation ·
│                      survival · market_risk (the gate)
├── models/            versioned weight vectors + registry
├── weighting.py       renormalisation and cap redistribution
├── evidence.py        coverage × depth
├── grading.py         bands + Elite gate
├── explain.py         reason codes, severities, templates
├── materiality.py     when history is worth writing
├── freshness.py       read-time decay
├── service.py         ← I/O seam (write path)
└── query_service.py   ← I/O seam (read path)
```

**Only those two `*_service.py` files touch a database.** A test parses every
other module's AST and fails on any import of sqlalchemy, redis, fastapi, celery,
asyncio, random or time — and on any `datetime.now()`. Adding a third I/O module
fails that test deliberately.

### Background jobs

| Job | Trigger | Purpose |
|---|---|---|
| Inline scoring | Every enrichment cycle (TX-2) | The fast path |
| `score_sweep` | Beat, every 15 min | Missing, stale, or model-version-outdated scores |
| `rescore_tokens` | Manual | Resumable keyset backfill under a model version |
| `prune_score_history` | Beat, daily 03:30 | Thin history beyond 30 days to hourly |

---

## 6. Data model

Ten tables. Migration head: **`0005_radar`**. Fresh install, full rollback
and re-upgrade are verified, and `alembic check` reports no drift (it is now a
CI gate; the phantom `ix_refresh_tokens_expires_at` drift was reconciled in
v0.8.0-rc1).

| Table | Shape | Notes |
|---|---|---|
| `users`, `refresh_tokens` | Mutable | Auth, JWT + httpOnly refresh cookie |
| `discovered_tokens` | Append-mostly | One row per mint |
| `token_market_snapshots` | **Append-only** | Immutable observations; the durable asset |
| `token_enrichment_state` | Mutable, 1/token | Scheduler work queue, `FOR UPDATE SKIP LOCKED` |
| `token_scores` | Mutable, 1/token | **Scalars only** |
| `token_score_history` | **Append-only** | Carries the JSONB component breakdown |

### Why `token_scores` is narrow

It is rewritten on every evaluation (~43k/hour at ceiling). Keeping the ~2 KB
component JSONB here would mean ~2 GB/day of WAL churn on a 10k-row table plus
constant dead-tuple pressure. The breakdown lives in history, written only on
material change.

### Two guards worth knowing

**Monotonic upsert.** Three writers touch `token_scores` — inline scoring, the
sweep, and rescore jobs — and `SKIP LOCKED` only makes enrichment replicas
disjoint. A stale evaluation cannot overwrite a fresher one:

```sql
ON CONFLICT (token_id) DO UPDATE SET ...
WHERE EXCLUDED.evaluated_at > token_scores.evaluated_at
   OR EXCLUDED.model_version <> token_scores.model_version
```

**No FK into snapshots.** Provenance is `source_snapshot_captured_at`, a
timestamp. An enforced foreign key would block the partition detach/drop that
snapshot retention will eventually need.

### Materiality

`token_scores` is upserted every evaluation; history is written only when the
score moves ≥ 2.0, the grade changes with ≥ 0.5 movement, elite or veto toggles,
300 s pass (heartbeat), or it is the token's first evaluation. Without this a
30-second tier writes ~2,880 near-identical rows per token per day and the
Observatory Log becomes noise.

---

## 7. API surface

33 paths / 34 operations, all documented in OpenAPI at `/docs`. A generated
snapshot is committed at [`docs/api/openapi.json`](docs/api/openapi.json).

### Scoring

| Endpoint | Purpose |
|---|---|
| `GET /api/v1/scores/top` | Ranked, filtered, paginated. Excludes vetoed by default. |
| `GET /api/v1/scores/{mint}` | Current score + component waterfall + reasons |
| `GET /api/v1/scores/{mint}/history` | Recorded changes, newest first |
| `GET /api/v1/scores/model` | Active weights, bands, Elite gate |

Also: auth (`register`, `login`, `refresh`, `logout`, `logout-all`), users
(`me`, `me/password`), tokens (`list`, `latest`, `{mint}`, `{mint}/market`,
`{mint}/history`), `market/trending`, `live`, `ready`.

### Conventions

- **Decimals serialise as strings.** A JSON float would round exactly the numbers
  the waterfall must reconcile.
- **Absence is state, not error.** An unscored token returns 200 with
  `score: null` and a `status` (`awaiting_market`, `not_scored`,
  `insufficient_data`, `scoring_disabled`). Only an undiscovered mint is a 404.
- **Filters are echoed.** `/scores/top` returns `applied_filters`, `total` and
  `candidate_total`, so an empty page caused by a strict filter is
  distinguishable from an empty table.
- `min_confidence` filters on stored **evidence** — an exact upper bound on
  confidence, and the only form that can be applied database-side without
  reimplementing the tier policy in SQL.

---

## 8. Frontend

Next.js 15 App Router, React 19, Tailwind v4, Zustand (session), TanStack Query
(server state).

### All scoring comes from the backend

`lib/intelligence.ts` — 246 lines of client-side heuristics that filled the
division panels before the engine existed — was **deleted** in Phase 4.1. It was
a second, unversioned opinion that could disagree with the engine about the same
token.

```
/scores/top ──▶ useScoresByMint() ──▶ Core · cards · log · panels · rail
/scores/{mint} ─▶ useTokenScore() ──▶ mission report (component waterfall)
```

`lib/scores.ts` parses and labels; **it never decides**. If a helper there ever
needs a threshold that changes a verdict, that threshold belongs in the engine.

### Request efficiency

One shared TanStack query serves every consumer on a page. A dashboard load now
issues **5 requests, zero duplicates**. Previously it issued roughly twice that,
with `/tokens?page_size=1` alone fired seven or more times per load because
several components each fetched the total independently. Deduplication is
enforced by a test: three `useScoresByMint()` calls in one render issue exactly
one fetch.

Latency telemetry reads the API client's own timing rather than firing a request
whose only purpose is to be measured.

### The observatory scene

`Universe` is the view through the observation window: six parallax planes, from
deep stars that barely move to foreground motes that drift perceptibly. It runs
**zero JavaScript per frame**. Geometry is memoised, all motion is CSS, and the
only script involved is one passive `pointermove` listener that coalesces to a
single write of two CSS variables per frame.

Two independent movements compose:

| | What it is | Changes on | Duration |
|---|---|---|---|
| **Camera** | Where the observatory is pointed | Navigation | `--duration-camera` (1400ms) |
| **Parallax** | How the head moves within that framing | Pointer | continuous |

The camera (`lib/camera.ts`) is a pure lookup from pathname to `{x, y, scale}`,
kept out of the component so the framing decisions are testable and live in one
table rather than scattered as magic numbers. It wraps the planes, so a route
change animates exactly **one** composited element however many planes the scene
grows to. The vignette sits outside it — that is chrome holding the sky off the
UI, not part of the sky.

Framings are deliberately small (≤4% translation, ≤1.12 scale) and a test
enforces that envelope. Larger values turn navigation into a ride and start
fighting the interface for attention, which is the opposite of what §10 asks for.

### Sentinel — the operator's voice

Sentinel narrates what the engine decided. It is a **narrator, not an analyst**:
it holds no opinion, runs no threshold, and issues no request of its own.

`lib/sentinel.ts` carries the rule that keeps that true. Every sentence is built
from one of exactly three inputs:

1. A string the **backend rendered** (`ScoreReason.message`).
2. A **categorical state the backend decided** (`grade`, `has_veto`, `is_elite`,
   `status`, `severity`, `available`).
3. **Plain arithmetic** over backend numbers — counts, means, differences.

The forbidden fourth is a threshold. The moment a helper decides that "momentum
above 70 is strong", the frontend owns a verdict the engine does not know about
and the two can disagree about the same token — the exact failure
`lib/intelligence.ts` was deleted for in Phase 4.1. Prose hides a threshold far
better than a number does, which makes this module the most tempting place in
the codebase to reintroduce one. So *"nothing in this window is graded Strong or
better"* (a count over backend grades) ships; *"market conditions are neutral"*
does not, because **neutral** is a judgement no backend field returns.

**Split by surface, because the payloads differ.** `/scores/top` omits `reasons`,
`previous_score` and `components` — a ranking is scanned, not read. So:

| Surface | Source | What Sentinel can say |
|---|---|---|
| Command Center | cached `/scores/top` window | Aggregate only: distribution, leader, worst risk, mean coverage |
| Token detail | cached `/scores/{mint}` | Specific: the engine's own sentences, the score delta, which signals are missing by name |

Neither issues a request for Sentinel's benefit. The dashboard remains at
**5 requests, zero duplicates**.

### The Observatory Log

Entries carry `timestamp · agent · category · severity · message · mint`.
Categories are `discovery · ai · risk · market · infrastructure`; grouping is
done by **filtering rather than sectioning**, because chronology is what makes a
log readable and sections would each lose it. Only categories with entries get a
control — a filter that can only ever return nothing would imply activity the
station does not have.

Two defects were fixed here in Phase 5C, both of which had silently starved the
log of the engine's verdicts:

- The verdict line searched `score.reasons`, which the **ranking endpoint never
  populates**. The branch could not fire; the log had never once reported what
  the engine concluded. It now falls back to `grade`.
- Verdicts were only emitted for tokens **joined against the discovery feed**, so
  a token had to be scored while still among the newest arrivals. At the rate the
  scanner discovers, almost none are. Verdicts now come from the scoring window
  directly, which is the correct source for what the engine decided; the feed
  remains the correct source for what arrived.

### Key files

```
src/lib/sentinel.ts         interpretation core (pure) + the rule above
src/components/sentinel/    operator panel (aggregate) · operator read (token)
src/types/score.ts          API contracts
src/lib/scores.ts           client + presentation helpers
src/hooks/use-scores.ts     TanStack Query hooks
src/hooks/use-api-latency.ts
src/app/page.tsx            landing page — the front door, always reachable
src/middleware.ts           dev auth bypass routing (auth pages only)
src/middleware.test.ts      asserts `/` is never bypassed
src/lib/camera.ts           per-view camera framings (pure)
src/components/brand/universe/universe.tsx   the scene
src/components/token/token-card.tsx     Grade · Score · Confidence · Evidence · Risk
src/components/token/mission-report.tsx component waterfall, backend-attributed
```

---

## 9. Configuration and feature flags

All settings in `backend/app/core/config.py`, validated at import. **A
misconfigured process never boots.**

| Flag | Default | Effect |
|---|---|---|
| `FEATURE_SCANNER_ENABLED` | false | Helius discovery (requires `HELIUS_API_KEY`) |
| `FEATURE_ENRICHMENT_ENABLED` | false | DexScreener refresh loop |
| `FEATURE_AI_SCORING_ENABLED` | false | Scoring engine. Requires enrichment. |
| `SCORING_MODEL_VERSION` | `v1` | Registry key; unknown value fails at startup |
| `MARKET_PROVIDER` | `dexscreener` | `composite` adds the liquidity fill ([§21](#21-composite-market-provider-phase-10)); unknown value fails loudly |
| `DEVELOPMENT_BYPASS_AUTH` | false | See below |

> ⚠️ **Any new setting must be added to the `x-backend-env` anchor in
> `docker-compose.yml`.** A flag absent from that anchor never reaches the
> containers and silently falls back to its code default regardless of `.env`.
> This has already happened once with `FEATURE_AI_SCORING_ENABLED`.

### Development auth bypass

`DEVELOPMENT_BYPASS_AUTH=true` + `NEXT_PUBLIC_DEVELOPMENT_BYPASS_AUTH=true`
treats every request as an authenticated developer and routes `/login` and
`/register` straight to `/command`. No auth code was deleted — endpoints, JWT,
refresh tokens, models and both auth pages remain intact.

**`/` is not bypassed** (changed in Phase 5A). It was until then, which meant the
landing page rendered for nobody in the only environment anyone ran. Skipping a
login screen is a development convenience; skipping the front door hides a
shipped surface and lets it rot unnoticed. `src/middleware.test.ts` locks this —
a landing page reachable while the bypass is active is now an asserted property,
not a thing someone remembers.

While the bypass is active the landing header offers a single **Enter
Observatory** action instead of Sign in / Request access, because a credential
control that silently bounces the visitor to `/command` is the product claiming
a step it does not take.

Safety, by construction rather than by convention:

- **Production refuses to boot** with the flag set. Silently ignoring it would
  leave whoever set it believing something false about the deployment.
- Every consumer reads `settings.auth_bypass_active`, which ands the flag with
  `ENVIRONMENT == "local"`. No call site can forget the environment check.
- `test` is **excluded** — otherwise a developer with the flag exported would run
  the whole suite with auth disabled and every auth test would pass for the
  wrong reason.
- The developer principal is transient and never persisted; a real row would
  outlive the flag.
- A `warning` is logged on every boot while it is active.

Set both to `false` and restart to restore the normal flow.

---

## 10. Design system

Full detail: [`DESIGN_BIBLE.md`](DESIGN_BIBLE.md). The rules that constrain code:

- **Not a crypto website.** An orbital observatory: elegant, minimal, cinematic,
  data-first, calm.
- **Colour.** Dark, cool blues, subtle cyan, white type. **Gold is reserved
  exclusively for Elite** — a grade never earns it. Red only for warnings, green
  only for confirmations.
- **Motion communicates information.** Fade, glow, slow rotation, parallax. No
  bounce, no flashing. 60 FPS; prefer SVG/CSS/GPU transforms over WebGL. Respect
  reduced-motion.
- **The universe reacts to real backend events only.** Never invent activity.
- **Extend the design system; do not redesign without a clear reason.**
  Consistency beats novelty.

### Why not WebGL / React Three Fiber

Asked and answered in Phase 5B. The scene is CSS and SVG, and it stays that way
until something appears that CSS genuinely cannot express.

The existing universe runs **zero JavaScript per frame** — all motion is
declarative CSS, and 22 of its 23 keyframes animate only `transform` and
`opacity`, so they are handed to the compositor and cost nothing on the main
thread. A React Three Fiber scene replaces that with a `requestAnimationFrame`
render loop, ~600 KB of dependencies, a WebGL context per surface, and a new
class of failure on machines without hardware acceleration. It would make the
60 FPS target *harder* to hold, not easier.

The one remaining repaint-per-frame animation is `energy`
(`stroke-dashoffset`, the conduit flow on `AgentSigil alive`). It is deliberate:
dashoffset is the only honest way to flow a dashed line along its own path, the
repaint is bounded by a ≤44px sigil, and `alive` is opt-in for exactly this
reason. Do not put it on anything that renders in bulk.

Reach for WebGL only with a specific effect that justifies it, behind a flag,
with the CSS scene as the fallback — never as a wholesale replacement.

---

## 11. Verified state

Measured against the running stack on 28 July 2026.

### Live data

| Metric | Value |
|---|---|
| Tokens discovered | 11,629 |
| Market snapshots | 609,655 |
| Tokens scored | 9,579 |
| Score history rows | 76,038 |
| Vetoed by the risk gate | 124 |
| Elite certified | **0** (expected — unreachable in v1) |
| Mean score | 41.0 |

### Grade distribution

| Grade | Count | Range |
|---|---|---|
| critical | 528 | < 30 (or vetoed) |
| weak | 7,984 | 30 – 49 |
| watch | 1,033 | 50 – 64 |
| strong | 32 | 65 – 79 |
| high_conviction | 2 | ≥ 80 |

A discriminating, realistic spread — not the degenerate single-band clustering
that careless weighting produces.

### Coverage reality — important

| Coverage | Tokens |
|---|---|
| 45% | 8,201 |
| 30% | 670 |
| 65% | 332 |

**Most tokens score at 45% coverage, not the model's 65% ceiling.** The missing
0.20 is `liquidity_depth`: DexScreener does not report liquidity for pump.fun
bonding-curve pools (ADR 0001 predicted this). Evidence — and therefore
confidence — is correspondingly low across the feed. This is the coverage
mechanism working exactly as designed: the gap is visible rather than papered
over. It is also the strongest argument for a second market provider.

**Re-measured 29 July 2026, and the gap is larger than the table above shows.**
Of 19,590 scored tokens, 17,727 (**90.5%**) sit at 45% coverage; mean evidence
is 44.6. In a two-hour snapshot window `pumpfun` was 29,477 of 30,339
observations — **97% of the feed, with null liquidity on 100% of them**, while
`pumpswap` and `meteora` reported liquidity on every row. [§21](#21-composite-market-provider-phase-10)
is the response.

### Quality gates

| Gate | Result |
|---|---|
| Backend tests | 2,364 passed |
| Backend coverage | 91% (100% on every scoring module) |
| Frontend tests | 113 passed |
| ruff / ruff-format / mypy strict | Pass |
| eslint / tsc | Pass |

### Scene performance (Phase 5B)

| Measure | Value |
|---|---|
| Keyframes animating only `transform`/`opacity` | **22 of 23** |
| Repaint-per-frame keyframes | 1 (`energy`, deliberate — see [§10](#10-design-system)) |
| JavaScript per frame | **0** |
| Universe DOM nodes | 457 (of 1,773 on `/command`) |
| Composited layer hints (`will-change`) | 7 |
| Forced style-recalc + layout, Observatory | 6.3 ms median / 10.2 ms p95 |
| Forced style-recalc + layout, Command | 4.5 ms median / 5.5 ms p95 |
| Running animations, Observatory → Command | **130 → 0** |

The recalc figures are a deliberately worst-case **forced synchronous reflow of
the whole document**, not per-frame cost — compositor animations do not trigger
one. Read them as "what a real layout change costs", where the scene adds ~1.8ms.

**FPS was not measured.** The only browser available to the agent harness renders
hidden, which pauses `requestAnimationFrame`, so any number it produced would be
fiction. The compositor audit above is the evidence that stands behind the 60 FPS
claim; a real FPS reading needs a visible browser and is still outstanding.

### Browser support floor

Chrome 111 · Safari 16.2 · Firefox 113, set entirely by `oklch()` and
`color-mix()` in the palette. No `@property`, no `:has()`. Phase 5B lowered risk
slightly by replacing an animated `background-position` with a transform.

---

## 12. Engineering conventions

**Testing**
- Unit tests are pure and fixture-free. Integration tests use real Postgres and
  Redis, each in a rolled-back transaction.
- Tests must never depend on ambient environment. Pin flags explicitly — this has
  bitten twice (`test_config.py`, `test_scores_api.py`).
- Any module importing `SessionFactory` by name must be patched in
  `conftest.test_session_factory`, or it will read and write the **development**
  database during tests. This has happened once.
- Coverage runs with `concurrency = ["greenlet", "thread"]`; without it
  SQLAlchemy's async layer makes coverage under-report async services by ~15%.

**Async workers**
- Celery tasks call `run_async()` (`app/workers/runtime.py`), never
  `asyncio.run()` directly. The module-global engine's pooled connections
  otherwise leak across event loops and the *second* task in a worker fails with
  `got Future attached to a different loop`.

**Numbers**
- Money and scores are `Decimal` end to end, `NUMERIC` in Postgres, strings on
  the wire. Never float.

**Linting**
- Ruff runs over the **whole backend** — `ruff check .`, not an explicit directory
  list, in both the Makefile and CI. A list has to be remembered every time a
  top-level directory is added, and it was not: `alembic/` and `scripts/` sat
  unlinted until the scope was widened. Suppress deliberate findings in
  `[tool.ruff.lint.per-file-ignores]` with a comment saying why, rather than
  narrowing the scope again.
- Migrations are format-checked like any other source. `alembic revision
  --autogenerate` emits output the formatter disagrees with, so run `make format`
  after generating one.

**Comments**
- Explain *why*, not *what*. Record the reasoning that would otherwise be lost —
  especially where a simpler-looking alternative was rejected.

---

## 13. Known issues and open questions

**Open product decisions**

1. **Grade band boundaries** (30/50/65/80) are an engineering default. They are
   product-visible labels and deserve a product decision.
2. **Elite unreachable in v1** — confirmed as intended? The alternative (lowering
   the evidence threshold so gold can appear) is available and recommended
   against.
3. **History retention** — 30 days full, then hourly thinning. Thinning is
   irreversible and degrades tier-2 replay for old tokens.
4. **Public vs authenticated** scoring endpoints. Currently public. The auth
   boundary is cheaper to place now than to retrofit.

**Known technical debt**

- **Offset pagination on `/scores/top`.** Implemented as specified, but pages are
  offset-based over a ranking that changes every 30 seconds, so a row can shift
  between pages while a client walks them. Ordering is total (sort column +
  `mint_address`), so any single request is deterministic. Keyset pagination
  pinned to a ranking generation is the designed fix.
- **`ix_refresh_tokens_expires_at`** exists in the database (migration 0001) but
  not in the model, so `alembic check` reports drift. Pre-existing; blocks using
  `alembic check` as a clean CI gate.
- **Liquidity coverage gap** — see [§11](#11-verified-state). Now *partially*
  addressable: [§21](#21-composite-market-provider-phase-10) adds a secondary
  provider that fills it for the tokens its call budget reaches, which is a
  fraction of peak demand. Closing it fully needs on-chain bonding-curve reads
  (ADR 0002, "Alternatives considered") or a paid plan.
- **WebSocket score events** are published to `memescope:scores:changed` but not
  yet multiplexed onto `/tokens/stream`. Requires an envelope change to the WS
  payload, which is breaking; the stream has no external consumers.

---

## 14. Roadmap

| Phase | Scope |
|---|---|
| **5D** | Polish — performance, accessibility, browser compatibility, production optimisation. |

| Day | Scope |
|---|---|
| **5** | Smart Wallet Intelligence — wallet clustering, labelled wallets. Unlocks `smart_money` and `holder_distribution`. |
| **6** | Security & Rug Detection — mint/freeze authority, LP burn, renouncement. Unlocks `contract_safety`; **makes Elite reachable**. |
| **7** | Narrative Intelligence — unlocks `narrative`. The one place an LLM belongs. |
| **8** | Alerts — Telegram, Discord, email, push. Consumes the score event channel. Must read state, not rely on event delivery. |
| **9** | Portfolio — watchlists, favourites, PnL |
| **10** | Production deployment, monitoring, public launch |

**Closing the liquidity gap fully.** [§21](#21-composite-market-provider-phase-10)
fills it for the fraction of tokens a free-tier call budget reaches. The
complete fix is to read pump.fun bonding-curve reserves **on-chain** via
Helius — the curve account holds the real SOL reserve, `getMultipleAccounts`
takes 100 accounts per call, and the key is already configured, so it would
cover 100% of demand with no vendor budget at all. It needs PDA derivation and
account-layout decoding; see ADR 0002, "Alternatives considered".

**Later:** multi-chain (Ethereum, Base, BNB, Sui, Aptos, Hyperliquid). The
scoring engine is already chain-agnostic — a second chain needs a scanner and a
provider, not a scoring change.

**The ML path.** When `token_score_history` and `token_market_snapshots` support
derived forward returns, fit a combiner over the same `ComponentResult` vector.
Features, storage, explanation structure, API shape and worker integration are
unchanged. **Explainability must survive the change** — a model whose
contributions cannot be decomposed per component does not ship, whatever its
accuracy.

**Guiding principle.** Every feature answers one question: *does this help users
discover high-quality opportunities earlier and with greater confidence?* If not,
rethink it.

---

## 15. Document map

| Document | Contents |
|---|---|
| **This file** | Single source of truth; start here |
| [`README.md`](README.md) | Setup, repository layout, where features go |
| [`docs/AI_SCORING_DESIGN.md`](docs/AI_SCORING_DESIGN.md) | Scoring engine design, Rev 2, with the review that reshaped it |
| [`DESIGN_BIBLE.md`](DESIGN_BIBLE.md) | Visual identity, motion, colour |
| [`ARCHITECTURE.md`](ARCHITECTURE.md) | High-level module map |
| [`ROADMAP.md`](ROADMAP.md) | Milestones |
| [`PROJECT_CONTEXT.md`](PROJECT_CONTEXT.md) | Product vision, AI divisions |
| [`docs/adr/0001-*.md`](docs/adr/) | Market provider abstraction |
| [`docs/adr/0002-*.md`](docs/adr/) | Composite provider; the pool-keyed liquidity fill and why the mint-keyed field is wrong |
| [`ALPHA_CHECKLIST.md`](ALPHA_CHECKLIST.md) | Running the private alpha: limitations, testing checklist, feedback, success criteria |
| [`docs/API.md`](docs/API.md), [`DEVELOPMENT.md`](docs/DEVELOPMENT.md), [`DEPLOYMENT.md`](docs/DEPLOYMENT.md) | Reference |

`docs/AI_SCORING_DESIGN.md` §22 is worth reading before changing the engine: it
records thirteen defects found in design review — including a reproducibility
claim that was false and a windowing bug that would have capped evidence for
every token over a day old — and why each fix took the shape it did.

---

## 16. Production deployment

Added in Phase 6A to put MEMESCOPE behind a permanent HTTPS URL for a private
alpha. **The development stack is untouched** — production is an overlay, not a
replacement, and `make up` behaves exactly as [§3](#3-quick-start) describes.

### Topology

```
                    Internet
                       │  :80 → :443 (Caddy redirects)
                       ▼
              ┌─────────────────┐
              │      Caddy      │  automatic TLS · zstd/gzip · security headers
              │  172.19.0.x     │  immutable caching on /_next/static
              └────────┬────────┘
             /api/*    │    everything else
             /live     │
             /ready    ▼
      ┌──────────────┐   ┌──────────────┐
      │   backend    │   │   frontend   │  Next.js standalone
      │  gunicorn ×4 │   │   node       │
      └──────┬───────┘   └──────────────┘
             │
   ┌─────────┴──────────┬───────────┬────────────┐
   ▼                    ▼           ▼            ▼
postgres             redis      worker      scheduler
   │                                            scanner · enrichment
   ▼
 backup  (postgres:16-alpine, daily dump + retention)
```

Nothing but Caddy publishes a port — **now actually true**. Until Phase 6C it
was not: the overlay used `ports: []`, and Compose merges list fields by
concatenation, so an empty list removed nothing and the base file's mappings
survived into production. Postgres and Redis were published on the host. The
overlay uses `!reset []` instead, and the rehearsal verifies the rendered config
exposes only 80/443.

### Deploying

```bash
cp .env.production.example .env.production   # fill in every REQUIRED value
./scripts/deploy.sh                          # pull · backup · build · migrate · restart · verify
```

`deploy.sh` records the current commit and **takes a database backup before it
builds**, then rolls back automatically if `health-check.sh` fails. The backup
comes first because a build can take minutes and the backup exists to protect
the migration that follows it.

| Script | Purpose |
|---|---|
| `scripts/deploy.sh` | The whole pipeline. `--ref <tag>` to deploy something other than `origin/main`; `--no-rollback` to keep a broken release for inspection. |
| `scripts/rollback.sh` | Return to the previous commit. Called automatically on failed verification. |
| `scripts/health-check.sh` | 12 checks across both services. Exit 0 means serving. |
| `scripts/backup.sh` | One dump, filed into the retention tiers. |
| `scripts/restore.sh` | Interactive restore. Deliberately not automated. |

**Rollback does not reverse migrations.** They are forward-only, so the backup is
the recovery path for a bad schema change — which is why `rollback.sh` says so
explicitly rather than exiting on a bare non-zero.

### Security

Everything below was verified against the built production image, not just the
source. Docs and OpenAPI return **404** in production.

| Control | State |
|---|---|
| Secure cookies | `REFRESH_COOKIE_SECURE` — **boot fails** if false in production |
| CSP | `default-src 'none'; frame-ancestors 'none'` on the API; Caddy adds the frontend's |
| HSTS | `max-age=31536000; includeSubDomains`, production only |
| CORS | Explicit origins; **boot fails** on a missing value |
| XSS / clickjacking | `nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy`, `Permissions-Policy` |
| Rate limiting | 120/min, keyed by bearer token then client IP; Redis-backed, fails open |
| Trusted proxy | `TRUSTED_PROXY_IPS` — see below |
| Secrets | `SecretStr`, never logged; `.env.production` gitignored; templates carry shape only |
| Non-root | Both images run as uid 1001 |
| Auth bypass | **Boot fails** if set in production |

**Trusted proxy — the one that fails silently.** `rate_limit.py` keys on
`request.client.host`. Behind a proxy that is *the proxy*, so without correction
every user shares one 120/min bucket: the limiter becomes useless and one
abusive client denies everyone. `TRUSTED_PROXY_IPS` enables uvicorn's
`ProxyHeadersMiddleware`, added **last so it is outermost** and runs before the
limiter or the logger read the address. The header is honoured only from a
declared peer — trusting it unconditionally would let any client choose its own
bucket, which is worse than no limiter.

The default `172.16.0.0/12` covers Docker's compose bridge range (this project's
network is `172.19.0.0/16`), asserted by a test. **A local `docker run -p` test
does not exercise this** — Docker Desktop presents `192.168.65.1`, outside the
CIDR, so per-client bucketing correctly appears not to work. Verify on the real
topology or with `TRUSTED_PROXY_IPS=*`.

### Monitoring

| Signal | Where |
|---|---|
| Liveness | `GET /live` — process is up |
| Readiness | `GET /ready` — reports database and Redis individually |
| Structured logs | JSON via structlog, request id on every line, `LOG_FORMAT=json` |
| Errors | Sentry, if `SENTRY_DSN` is set |
| Product analytics | `lib/analytics.ts` — a seam, not an integration; see below |

`SENTRY_DSN` and `sentry-sdk` had both existed since Day 1 but `init()` was never
called, so the DSN was configuration that did nothing. `app/core/observability.py`
now initialises it with `environment`, `release` (the build SHA) and
`send_default_pii=False`. With no DSN nothing starts — an empty value is a
supported configuration, not a broken one.

`posthog-js` is **deliberately not installed**. The module documents the wiring —
key, host, opt-out posture — so enabling it is an install and an uncomment.
Shipping 60 KB of vendor script to every page before an alpha tester has asked
for a funnel is paying for a decision not yet made.

### Backups

`pg_dump -Fc` daily, filed into **7 daily · 4 weekly · 6 monthly**. Tiering is
decided at write time by which directory the dump lands in, not later by parsing
dates off filenames — a scheme that survives missed runs. Weekly and monthly are
hard links, so extra tiers cost no disk until the daily copy is pruned. Dumps are
written to a temporary name and moved into place only on success, so an
interrupted dump can never be mistaken for a restorable one.

**Restore:**

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml \
  run --rm backup /scripts/restore.sh /backups/daily/<file>.dump
```

It refuses to run unattended: it prints the target, requires the database name
typed back, and waits for the writers to be stopped. Restoring underneath a
running enrichment worker produces a database that is neither the backup nor the
current state.

### Alpha surfaces

`NEXT_PUBLIC_ALPHA=true` renders a bar carrying the model's limitations, the
version, **the build SHA**, and a feedback link. The SHA is the point: alpha
reports arrive hours later, and without it there is no way to know which code
produced the behaviour. A blank `FEEDBACK_URL` hides the button rather than
rendering a control that goes nowhere. Dismissal is remembered per build, so a
new deployment re-announces itself.

### Known limitations

- **Never deployed to a real host.** Everything here is verified locally: images
  build, configs validate, validators fire, headers serve, backups restore. The
  first real deploy will still be the first real deploy.
- **`docker/nginx/nginx.conf` is superseded and unused.** Retained rather than
  deleted; the production overlay references Caddy only.
- **No log aggregation.** Logs are structured JSON on stdout and go no further
  than `docker compose logs`. Fine for one host and a handful of testers.
- **`deploy.sh` has no zero-downtime path.** `up -d` restarts containers; expect
  seconds of downtime. Acceptable for an alpha, not for launch.
- **Backups stay on the same host** as the database they protect. Off-site copies
  are the obvious next step and are not implemented.
- **`deploy.replicas: 2`** on the backend is honoured by Compose but gives no
  scheduling guarantees; it is not a high-availability configuration.

---

## 17. Alpha experience (Phase 6B)

Surfaces added for the first invited cohort. Operating guidance —
limitations to disclose, testing checklist, success criteria — lives in
[`ALPHA_CHECKLIST.md`](ALPHA_CHECKLIST.md).

### The failure state that was missing

The Command Center rendered skeletons whenever the discovery list was empty. A
failed request and a genuinely quiet chain therefore looked identical, and both
looked like *loading* — permanently. A first-time user reads that as a slow
product rather than a broken one, and does not reload.

There are now three distinct states: **loading** (a request is genuinely
outstanding), **empty** (both queries answered and the chain is quiet), and
**error** (`useScoresByMint` reported a failure, with a retry). `isError` was
already exposed by the hook; the page simply never read it.

### About

`/about` is the trust surface, inside the dashboard shell so the reader is one
click from the instrument. It answers what the product is, what problem it
solves, what AI scoring means *here* (a weighted model, no LLM, deterministic,
weights published at `/scores/model`), what the grade bands mean, and what
coverage, evidence and confidence each measure.

It states the four unavailable signals by name and says plainly that Elite is
unreachable. Every figure on the page is already true and already published —
nothing there is a promise.

### Feedback

A floating control on every page of the instrument, with four categories.
Reports carry the page path, build SHA, environment and user agent, so a report
is reproducible without a follow-up conversation, and the form says so before
sending rather than collecting quietly.

`lib/feedback.ts` is the only module that knows where a report goes, and it
degrades in a defined order:

1. `NEXT_PUBLIC_FEEDBACK_ENDPOINT` — POST as JSON.
2. `NEXT_PUBLIC_FEEDBACK_URL` — open an external form.
3. Neither — **show the report back for copying.**

The third branch matters more than it looks. There is no feedback endpoint on
the backend yet and building one was not an alpha blocker, but silently
discarding what a tester wrote is the fastest way to stop them writing again.
A network failure returns the report too, for the same reason. Swapping in a
real destination is a configuration change.

### Onboarding

One dismissible primer on the Command Center covering the three things that
prevent the most common misreading — treating the score as a verdict while
ignoring the confidence beside it — and a link to About. Dismissal is permanent
and, unlike the alpha bar, not keyed to the build: the alpha bar re-announces
because what is being tested changed, but nobody needs to be taught how to read
a grade twice.

Deliberately not a guided tour. A multi-step overlay blocks the live feed the
user came to look at, and a tour library is a dependency and a maintenance
burden for a message that fits in three sentences.

---

## 18. Production rehearsal (Phase 6C)

The full production stack was run locally — production images, Caddy with its
internal CA, both backend replicas, workers, and the backup service — under an
isolated compose project so the development stack and its data were untouched.

It found **six defects, none of which any amount of local development would have
surfaced**, because every one of them lives in the gap between the development
and production configurations.

| # | Defect | Consequence if shipped |
|---|---|---|
| 1 | `ports: []` does not clear inherited port mappings | **Postgres and Redis published on the public host** |
| 2 | `SENTRY_DSN: ${SENTRY_DSN:-}` supplies `""`, not absent | **Every deployment without Sentry crashed on boot** |
| 3 | `ALLOWED_HOSTS` missing from the `x-backend-env` anchor | All four workers restart-looped; backend looked healthy |
| 4 | Celery beat could not write its schedule (non-root, `/app` not writable) | **Scheduler dead → `score_sweep` never runs** |
| 5 | Disabled features exit 0 under `restart: unless-stopped` | Hot restart loop that looks like a crash |
| 6 | Both backend replicas race to apply migrations | Collision on `alembic_version`; a real migration could half-apply |

Defect 3 is the second occurrence of the trap [§9](#9-configuration-and-feature-flags)
already warns about — a setting absent from the anchor never reaches the
containers. The anchor now carries everything the production validators demand,
because `ENVIRONMENT` reaches every service from there and anything production
*requires* has to arrive with it.

### Verified in production mode

| Check | Result |
|---|---|
| Services | postgres · redis · backend ×2 · frontend · worker · scheduler · caddy · backup all healthy |
| Exposure | only 80/443/443-udp published |
| HTTP → HTTPS | 308 redirect |
| Security headers at the edge | HSTS (preload), CSP, `nosniff`, `X-Frame-Options`, Referrer-Policy, Permissions-Policy; `Server` removed |
| Docs in production | `/docs` and `/openapi.json` → **404** |
| Static caching | `/_next/static` → `max-age=31536000, immutable` |
| Compression | gzip (zstd offered) |
| Surfaces through Caddy | `/` `/command` `/feed` `/division` `/system` `/about` `/login` all 200 |
| Auth, production path | 401 unauthenticated · 401 bad credentials · 201 register · 200 with token; refresh cookie `HttpOnly; Secure; SameSite=lax` |
| Backups | scheduled + on-demand; **destroy-and-restore round trip verified** |
| Logging | structured JSON with request ids |
| Exceptions | zero after the fixes |

### Rate limiting — read before changing `TRUSTED_PROXY_IPS`

Per-client bucketing is **proven working** against the backend directly: distinct
`X-Forwarded-For` values get distinct buckets and repeats return to the right one.

It cannot be exercised faithfully from inside Docker, and the reason is worth
understanding before someone "fixes" a non-bug. Caddy correctly **strips**
inbound `X-Forwarded-For` from untrusted clients, so the backend sees the test
container's real address — which is inside `172.16.0.0/12` and therefore treated
as a proxy, collapsing every test client into one bucket. Real users arrive from
public addresses, outside that range, and are distinguished correctly.

The consequence that does matter: **`TRUSTED_PROXY_IPS` must never overlap
addresses real clients can occupy.** RFC1918 space is safe for an
internet-facing deployment. It would be wrong for an internal deployment where
users share the private range.

### What the rehearsal could not cover

- Real DNS, a real certificate authority, and a real public address.
- Behaviour under real latency, or any load beyond single requests.
- Caddy's ACME path — the rehearsal used the internal CA, so certificate
  issuance and renewal are still unproven.
- Sentry actually receiving an event (no DSN available).

---

## 19. Opportunity Radar (Phase 8)

A **second intelligence layer**, above the launch scanner rather than replacing
it. The scanner still discovers exactly as before; nothing in §4's pipeline
changed. The Radar asks a different question of a different population.

| | Scanner + scoring engine | Opportunity Radar |
|---|---|---|
| Question | "What launched, and how does it score?" | "Which projects are getting **stronger**?" |
| Population | New mints | Every token with history, at any age |
| Cadence | Per enrichment cycle | Sweep every 15 minutes |
| Output | Grade + evidence | Category + multi-dimensional score + **track record** |

### The founding rule

**Market cap is never a qualification.** No gate in `detector.py` reads it. A
$60k project with growing liquidity, expanding volume and clean structure
outranks a $500k launch with none of those, and a test asserts there is no size
floor. Market cap appears in the model only through *liquidity-to-valuation*,
which penalises an **unbacked** valuation rather than rewarding a large one.

### Package layout

Mirrors `services/scoring` deliberately — a pure engine with I/O seams — so one
discipline covers both. `test_radar_purity.py` enforces it: no database, no
network, no clock, no randomness in the engine, and time enters as an explicit
`now`. That purity is what lets the token page **recompute** a score rather than
trust a cached one, which is what makes the track record an audit.

```
app/radar/
├── models.py        domain types                  (pure)
├── normalise.py     bounded transforms            (pure)
├── momentum.py      is it getting stronger?       (pure)
├── technical.py     price structure               (pure)
├── health.py        health · liquidity · risk     (pure)
├── community.py     declared, no data source      (pure)
├── scorer.py        weights, coverage             (pure)
├── detector.py      category gates                (pure)
├── achievements.py  milestones from detection     (pure)
├── explain.py       reason codes → English        (pure)
├── repository.py    ← I/O seam: database
├── service.py       ← I/O seam: orchestration
├── scheduler.py     ← I/O seam: Celery
└── api.py           ← I/O seam: HTTP
```

### The model

| Dimension | Weight | Available |
|---|---|---|
| `momentum` | 0.28 | ✅ |
| `technical` | 0.22 | ✅ |
| `liquidity_quality` | 0.18 | ✅ |
| `community` | 0.15 | ⬜ **no data source** |
| `onchain_health` | 0.12 | ✅ |
| `risk` | 0.05 | ✅ |

Available weight is **0.85**, so coverage caps at 85 and confidence below it —
the same mechanism §5 uses, not a second one. Weights are priors, published at
`GET /api/v1/radar/categories`.

**Every dimension scores higher = better, including risk.** A mixed convention
inside one weighted sum is how sign errors ship.

### Categories, and one that cannot be awarded

`early_momentum` · `breakout` · `undervalued` · `elite` · `strong_community`.

**Elite requires four independent dimensions to agree** at ≥65, not one high
score — and the scorer caps any single dimension at 40% of the total precisely
so one strong axis cannot manufacture it. Observed rate on real data: **1 in
4,000 evaluated**.

**`strong_community` is unreachable** and the API says so
(`reachable: false` with a reason), rather than merely never appearing. A
category nothing has qualified for and one that *cannot* be qualified for are
different facts, and the difference matters to anyone judging the record. It is
left in the ladder so that adding a social provider turns it on without a
structural change.

### The track record

The feature the rest of the product is judged by, so its guarantees are enforced
in SQL and asserted by integration tests:

- **First detection is written once.** `ON CONFLICT DO NOTHING`, never an
  upsert. An upsert would silently reset the denominator of every reported
  return and quietly improve the platform's record each time a token was
  re-detected.
- **Returns are measured from MEMESCOPE's first detection, never from launch.**
  Measuring from launch would credit the platform with moves it never called.
- **The peak only rises.** A later crash cannot erase a high that happened.
- **Achievements are permanent** and driven by peak, not current.
- **Nothing is ever deleted.** Failed opportunities stay on the record beside
  successful ones. The track record page reports `0.0% reached 2×` when that is
  the truth, and shows the worst performer with the same prominence as the best.

### Endpoints

`GET /api/v1/radar` · `/{mint}` · `/{mint}/history` · `/performance` ·
`/leaderboard` · `/achievements` · `/categories`. All additive; no existing
route changed shape.

### Frontend

`/radar` (the Radar), `/track-record` (platform performance), `/radar/{mint}`
(timeline, dimensions, milestones, reasons). Cards lead with **return since
detection**, and market cap appears second — a card that led with size would
make the opposite argument to the one the product is making.

### Known limitations

- **Community, holders, whales, mint/freeze authority and LP burn are not
  collected.** Risk is therefore a floor, not a clearance, and the module says
  so rather than implying otherwise.
- **Technical structure reads enrichment snapshots, not exchange candles.** A
  "high" is the highest *observed* price — a sample of the true high. The
  dimension describes observed structure; it is not a chart-pattern detector.
- Radar snapshots use the same materiality rule as `token_score_history`, so
  the timeline is a narrative rather than a per-cycle log.
- The record is young: figures on the track record page are honest but not yet
  meaningful, and will not be until opportunities have had months to play out.

---

## 20. Exit Watch & the permanent record (Phase 9)

### Why Smart Money is not here

Phase 9 asked for a wallet intelligence engine. **It is not built, and the
reason is not effort.**

The platform stores market *aggregates* — price, market cap, liquidity, volume,
and buy/sell **counts**. There are no wallet addresses, no transactions and no
holder lists anywhere in the schema. Nothing in the brief's wallet section can
be derived from what exists.

Worse, the headline signals could not be derived even from a complete wallet
feed starting today. "Historical profitability", "win rate" and "average ROI"
are claims about trades a wallet made **before MEMESCOPE existed**, priced at
the moment each trade happened, across tokens the platform never observed.
Computing them needs price-at-timestamp for arbitrary tokens across arbitrary
history — a dataset the platform does not have and cannot reconstruct from its
own records.

A wallet score built without that would be a number with the shape of evidence
and none of the substance, placed exactly where users are most likely to trust
it. That is the failure `lib/intelligence.ts` was deleted for in Phase 4.1.

So smart money is **declared and reported unavailable**, the same mechanism used
for `community` (Radar) and `contract_safety` (scoring):

- `GET /api/v1/smart-money/{mint}` returns every field as `null` — never zero,
  because "no smart wallets found" and "wallets cannot be seen" are different
  claims — with `unavailable_reason` attached.
- Two Exit Watch signals are declared and permanently unavailable, so Exit Watch
  **coverage caps at 78%** (7 of 9) and never claims a clean bill of health.
- The leaderboard ships `top_smart_money` and `top_accumulation` as empty boards
  labelled *"empty by construction, not by absence of activity"*.

`app/exit_signals/smart_money.py` documents the four steps implementing it would
actually take. Steps 1–2 are a data-engineering project, not a scoring module.

### Exit Watch

The other half of a detection platform. A product that only ever says "this
looks good" accumulates opinions it has no mechanism to revise.

Seven checkable signals: volume collapsing, liquidity leaving, technical
breakdown, momentum rolling over, confidence dropping, sell pressure building,
price below detection. Two declared and uncollectable: smart-money distribution,
holder growth.

**Severity comes from agreement, not drama.** One deteriorating metric on a thin
pool is noise; three unrelated ones together is a pattern. Thresholds are
deliberately *lagging* — Exit Watch is meant to be right, not early, because a
warning that fires on every wobble teaches users to ignore it.

**It is never a sell signal.** The platform knows nothing about anyone's
position, cost basis or intent. The disclaimer is carried on every API response
rather than left to a footer a client might not render.

Assessed **live** from the stored series on every request rather than cached —
the engine is pure so recomputation is exact, and a stale warning is worse than
none. That also fixed a defect found during verification: the list originally
displayed `radar_tokens.current_multiple`, which only moves on a Radar sweep,
so a token could be flagged `price_below_detection` while showing 1.00×. The
signal and the number now come from the same observation.

### Hall of Fame and Hall of Lessons

One table ordered two ways. Phase 8's decision to make `radar_tokens`
append-only with an immutable first-detection block is what makes both possible;
neither needed new storage.

- **Hall of Fame** ranks by *peak* multiple — what the call was worth at its
  best. Judging a detection by today's price would credit or punish the platform
  for time it never claimed to predict.
- **Hall of Lessons** ranks by *current* multiple, ascending. Nothing filtered,
  nothing softened, counted in the same denominator as the winners.

They share one page behind one toggle rather than living on two pages, one of
which nobody links to. That is the difference between disclosure and burial.

### Endpoints

`/exit-watch` · `/exit-watch/{mint}` · `/exit-watch/model` · `/smart-money/{mint}` ·
`/hall-of-fame` · `/hall-of-lessons` · `/leaderboard`. All additive; no existing
route changed shape.

### Deferred, with reasons

- **Narratives** — token `name`/`symbol` are the only text the platform holds. A
  keyword classifier over a ticker is not narrative intelligence, and shipping
  one would imply a capability that is not there. Needs token metadata or a
  social provider.
- **Rotation** — genuinely computable from the series (volume leading price,
  liquidity leading volume) and the natural next increment. Left out of this
  pass rather than shipped thin.
- **Smart alerts** — depends on a delivery channel (Day 8) that does not exist.

---

## 21. Composite market provider (Phase 10)

The first work aimed at the platform's own biggest limitation rather than at a
new surface. Full reasoning: [`docs/adr/0002-composite-liquidity-fill.md`](docs/adr/0002-composite-liquidity-fill.md).

### What it changes

`MARKET_PROVIDER=composite` wraps DexScreener with a secondary that supplies
liquidity for pump.fun bonding-curve pools — the gap that caps ~90% of the feed
at 45% coverage. **Nothing above the provider layer moved**: no service,
repository, schema, migration, endpoint or frontend change. That is ADR 0001's
central claim being cashed in rather than restated.

The default is still `dexscreener`. The feature ships dark and is enabled
deliberately.

### The one decision that matters

GeckoTerminal exposes reserves under two similar names, and the obvious one is
wrong:

| Endpoint | Field | Keyed by | Agreement with DexScreener |
|---|---|---|---|
| `/tokens/multi` | `total_reserve_in_usd` | mint | **0.49x – 0.97x** |
| `/pools/multi` | `reserve_in_usd` | pool | **median 1.005x** (n=12, $50–$7,600) |

The mint-keyed field is the natural one to reach for — enrichment is keyed by
mint — and it is not a constant factor off, so it cannot be corrected. Writing
it into `liquidity_usd` would put two meanings in one column, and because the
Radar compares liquidity *across time*, a vendor changing between two
observations would manufacture a halving or doubling that never happened and
Exit Watch would warn on the artefact.

The lookup is pool-keyed instead. It is possible at all because DexScreener
returns `pool_address` for **100%** of the rows it leaves without liquidity.

### Three rules

1. **A primary value is never overwritten** — the secondary fills `None` only.
2. **A secondary failure costs nothing** — any error, including an exhausted
   budget, returns the primary's batch intact. Snapshots are the durable asset.
3. **Provenance changes only when the data does** — a filled row records
   `dexscreener+geckoterminal`, an unfilled one stays `dexscreener`.

### Honest limits

- **Coverage is partial.** The free tier allows ~30 calls/min; the budget is set
  to 25 and never blocks. At 30 pools per call that is ~750 pools/min against a
  measured enrichment peak near 4,000 tokens/min. The remainder keep the null
  liquidity they have today, and `fill_stats()` reports eligible/filled/skipped
  every batch rather than leaving the shortfall invisible.
- **Partial is not biased.** Tokens reach the fill in the scheduler's
  `next_refresh_at` order, so they take turns; no subset is permanently favoured.
- **Liquidity may appear and disappear between snapshots.** Strictly better than
  always-absent, and no false trend is created because every present value comes
  from the same semantic source — but `liquidity_usd` stays nullable.
- **`trading_status` is not re-derived** after a fill; that threshold belongs to
  the adapter that defines it.
- The full fix is on-chain: the bonding curve account holds the real reserve and
  Helius takes 100 accounts per call, which would cover 100% of demand. Deferred
  with reasons in ADR 0002, not rejected.

### Verified

76 new unit tests (2,432 total, coverage held at 90%; composite 99%, budget and
registry 100%). Verified live against both real APIs: **5 of 6 bonding-curve
tokens filled**, the sixth correctly left null as not-yet-indexed, provenance
recorded on exactly the filled rows, one budget token spent.
