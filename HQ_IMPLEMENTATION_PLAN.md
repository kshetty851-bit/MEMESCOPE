# MEMESCOPE HQ — Implementation Plan

**Status:** design only. Nothing in this document has been built.
**Written against:** `64ae08b`
**Trading logic touched:** none. This plan does not modify Paper strategy, Real
Wallet execution, liquidity-security rules, scanner eligibility, risk limits,
stop/trailing logic, transaction safety, or any release barrier.

---

## 0. The one-sentence version

HQ renders state MEMESCOPE already publishes as a cartoon organisation, through
a read-only adapter, on an isolated lazy-loaded route, with no new dependencies.

---

## 1. Reference image analysis

| Property | What the reference does | Verdict for HQ |
|---|---|---|
| **Camera** | Fixed isometric, ~30° elevation, ~45° yaw. No perspective convergence — parallel projection. | **Carry.** Parallel projection means one CSS transform per tile and no z-fighting. It is also the only 3D-looking camera that stays legible at 1280px. |
| **Character scale** | Head ≈ 1/4 body. Seated figure ≈ 1.6× desk height. Occupies roughly a third of its desk cluster. | **Carry the ratio, not the proportion.** 1/4 heads read as children's game. HQ uses ≈1/5.5 — still cartoon, reads as professional adults. |
| **Furniture scale** | Desks are the unit of measure; everything else is sized against them. | **Carry.** One desk = one grid cell = one employee = one subsystem. The grid *is* the information architecture. |
| **Room density** | Moderate. Roughly 40% floor visible. Clusters separated by walkways. | **Carry the density, tighten the discipline.** 10 employees + 6 zones needs more negative space than the reference has, or status colour has nowhere to land. |
| **Visual hierarchy** | Flat. Every desk equally weighted; the eye wanders. | **Reject.** HQ needs a clear focal point (Mission Board) and a clear secondary (Execution Vault). Hierarchy carries the operational meaning. |
| **Lighting** | Single soft ambient, no cast shadows, no time-of-day. | **Partially carry.** Keep the flat ambient base — it is cheap and it never fights status colour. Add a *tint layer* for day/night and incident, not real lighting. |
| **Character detail** | Individually drawn, ~8 distinct silhouettes, hand-painted shading. | **Reject the technique, carry the intent.** Hand-painted raster for 10 characters × 8 states × idle frames is unshippable. HQ uses layered SVG: one body rig, per-character palette + accessory + hair. |
| **Environment detail** | Books, plants, printer, water cooler, patterned rug, framed art. | **Carry selectively.** Props earn their place by being a *status surface* (desk monitor, alert lamp, achievement shelf) or by being cheap ambience (plant, window). Nothing in between. |
| **Animation suitability** | Static illustration; characters are single poses. Nothing is rigged. | **This is the key finding.** The reference gives no animation model at all. HQ must invent one, and it must be transform-only — see §22. |
| **Palette** | Warm beige + grey carpet + primary-coloured clothing. Office-realistic. | **Reject.** Wrong universe. HQ is a space station and must inherit the existing MEMESCOPE dark space theme, or it will look like a bolted-on minigame. |

**What must NOT be carried:** the office-realistic palette, the flat hierarchy,
the hand-painted character technique, the cubicle-farm feeling, and the implied
"9-to-5" of a daylit office. MEMESCOPE runs 24/7 and the room must say so.

---

## 2. Final art direction

**"Mission control, drawn warmly."**

- **Projection:** CSS isometric. Base tile 128×64 logical units. One transform
  on the room container; children are positioned in tile coordinates.
- **Palette:** inherits the existing MEMESCOPE space tokens. Deep navy/charcoal
  station interior, cyan and amber instrument light, warm skin and clothing
  tones so the humans read as *warm objects in a cool room*. That contrast is
  the whole charm.
- **Characters:** layered SVG rig — `body` (shared), `hair`, `garment`,
  `accessory`, `face`. Per-character differentiation is palette + silhouette
  accessory (§5), never a bespoke drawing.
- **Line:** no outlines. Soft interior shading via two-stop gradients.
- **Status colour is reserved.** Green/amber/red appear *only* on operational
  state. No decorative green plants competing with an APPROVED badge. This is
  the single rule that keeps Level 2 (observability) from being drowned by
  Level 1 (entertainment).
- **Windows:** reuse `src/components/space/objects.tsx` and `universe.css`
  starfield behind a window frame — no second starfield implementation.

---

## 3. Office floor plan

Isometric room, 16×12 tiles. Reading order follows the token journey, so the
room's geometry teaches the pipeline.

```
                        ╔═══════ VIEWPORT / STARFIELD ═══════╗
                        ║   (reuses existing space objects)   ║
   ┌────────────────────╨─────────────────────────────────────╨────────────┐
   │                        ▓▓ MISSION BOARD ▓▓                            │
   │                            NOVA (roams)                               │
   ├──────────────────┬────────────────────────────────────────────────────┤
   │                  │              TRADING FLOOR                         │
   │   RISK ROOM      │   RADAR  →  LUNA  →  DEX  →  REX                  │
   │   (glass wall)   │                              │                     │
   │      ATLAS       │                       ┌──────┴──────┐              │
   │                  │                       │ EXEC VAULT  │              │
   │   ▓ shield wall  │                       │  🔒 LOCKED  │              │
   ├──────────────────┴───────────────────────┴─────────────┴──────────────┤
   │            CENTRAL WALKWAY  (Nova's patrol route)                     │
   ├───────────────────────────┬───────────────────────────────────────────┤
   │      PORTFOLIO            │   OPS / TECH        │   PERFORMANCE LAB   │
   │        MILO               │   ECHO    BYTE      │        SAGE         │
   │  ▓ positions wall         │   ▓ queue board     │   ▓ analytics wall  │
   ├───────────────────────────┴─────────────────────┴─────────────────────┤
   │                    BREAK ROOM  ☕  🛋   station window                 │
   └───────────────────────────────────────────────────────────────────────┘
```

Deliberate choices:

- **Atlas is behind glass.** He is the only character who can *stop* the
  pipeline, and a physical barrier makes that legible without a label.
- **The Vault adjoins Rex but is a separate sealed room.** Paper execution is
  Rex's open desk; real money is behind a door. The psychological separation the
  brief asks for is architectural, not decorative.
- **Trading floor reads left→right** in journey order. Milo sits below, because
  he receives from Rex *and* feeds back into the next decision.
- **Nova has no desk.** She has the board and a patrol route. That is what makes
  her read as the director rather than the eleventh analyst.

---

## 4. Character roster

| # | Name | Role | Zone | Subsystem |
|---|---|---|---|---|
| 1 | **Nova** | CEO / Mission Director | Mission Control (roams) | Overall status, portfolio roll-up, daily brief |
| 2 | **Radar** | Head of Discovery | Trading floor | Scanner, token discovery, Radar admission |
| 3 | **Luna** | Senior Token Analyst | Trading floor | Scoring, analyst orchestration, candidate evaluation |
| 4 | **Dex** | Market Analyst | Trading floor | DexScreener enrichment, price/liq/vol, quote freshness |
| 5 | **Atlas** | Chief Risk Officer | Risk Room (glass) | Safety gate, liquidity security, mint/freeze authority, impact |
| 6 | **Milo** | Portfolio Manager | Portfolio | Paper positions, exposure, holding period, capital efficiency |
| 7 | **Rex** | Trader / Execution | Trading floor + Vault | Paper entries/exits; Real Wallet state (display only) |
| 8 | **Echo** | Operations Manager | Ops/Tech | Celery, queues, enrichment backlog, priority lane |
| 9 | **Byte** | CTO / Infrastructure | Ops/Tech | Postgres, Redis, RPC, WebSocket, API health |
| 10 | **Sage** | Performance Analyst | Performance Lab | Track Record, P&L, win rate, drawdown, strategy comparison |

---

## 5. Character visual differentiation

Recognisable at 64px without labels, using three axes only. No bespoke art.

| Character | Silhouette accessory | Palette | Desk signature |
|---|---|---|---|
| Nova | Tablet in hand, no chair | Deep indigo + gold | *(none — the board is hers)* |
| Radar | Headset with antenna | Electric cyan | Sweeping radar dish |
| Luna | Hair bun + stylus | Violet | Tilted chart slate |
| Dex | Visor, four small screens | Amber | Multi-monitor rig + mug |
| Atlas | Shoulder yoke, shield emblem | Steel blue + white | Shield lamp (green/red) |
| Milo | Cardigan, clipboard | Forest green | Tall positions wall |
| Rex | Rolled sleeves, wrist terminal | Crimson | Single wide execution desk |
| Echo | Tool belt, clipboard, moves | Orange | Queue board with columns |
| Byte | Hoodie, hair tuft, 3 mugs | Slate + lime | Three terminals, cable spill |
| Sage | Glasses, long coat | Teal | Wide analytics wall |

Everyone shares one body rig. Differentiation is `hair`, `garment` fill,
`accessory` path, and desk prop — four small SVG swaps.

---

## 6. Character personalities (idle vocabulary)

Presentation only. An idle animation never implies the backend is idle.

| Character | Idle behaviours |
|---|---|
| Nova | Patrols walkway, pauses at a department, sips coffee, looks out window |
| Radar | Leans into screen, taps rapidly, spins dish, glances at Luna |
| Luna | Reads slate, annotates, occasional slow nod |
| Dex | Head flicks between monitors, reaches for mug |
| Atlas | Still. Slow deliberate scans. Adjusts a stack. Rarely moves. |
| Milo | Steps back from wall, arms folded, tilts head |
| Rex | Drums fingers, leans back, rolls chair |
| Echo | Walks between terminals, gestures at board |
| Byte | Slumps, stretches, refills mug, occasionally naps (rare easter egg) |
| Sage | Slow scroll, chin on hand, adjusts glasses |

---

## 7. Existing real data available for each employee

Verified present at `64ae08b`.

| Employee | Source | Fields |
|---|---|---|
| **Nova** | `GET /api/v1/paper`, `GET /health/pipeline`, `GET /radar/performance` | `overall`, metrics roll-up, `open_positions`, `realised_pnl` |
| **Radar** | `health/pipeline.scanner`, WS `token.discovered`, `radar.changed` | `status`, `last_discovery`, `minutes_since_last_token`, `connected`, `reconnect_attempts`, `failure_reason` |
| **Luna** | `health/pipeline.scoring`, WS `score.changed`, `radar.score_updated` | `status`, `last_score`, `minutes_since_last_score`, `pending` |
| **Dex** | `health/pipeline.market_enrichment`, WS `market.changed` | `last_snapshot`, `minutes_since_last_snapshot`, `tracked_freshness_worst_seconds`, `tracked_stale_count` |
| **Atlas** | `GET /real-wallet-safety/evaluations/{mint}`, `paper/eligibility` refusal codes | `decision`, `reason_codes`, `liquidity_usd`, `buy/sell_price_impact_pct`, `round_trip_loss_pct`, `mint_authority_active`, `freeze_authority_active` |
| **Milo** | `GET /api/v1/paper`, `/paper/positions` | `opened_at`, `current_pct`, `current_price_at`, `last_market_check_at`, `size_usd`, `open_value`, `invested_usd`, `waiting_for` |
| **Rex** | `GET /api/v1/paper/audit`, WS `paper.changed`; `GET /real-wallet/status` | `exit_reason`, `net_pnl_usd`, `opened_at`/`closed_at`; vault: `submission_permitted`, kill switches |
| **Echo** | `health/pipeline.market_enrichment` | `queue_depth`, `priority_queue_depth`, `priority_tokens`, `dead_lettered`, `oldest_priority_wait_seconds`, `oldest_normal_wait_seconds` |
| **Byte** | `health/pipeline.overall`, `/ready`, `real-wallet/status.rpc` | stage statuses, `rpc.verified`, `observed_genesis_hash`, `error` |
| **Sage** | `GET /paper/audit`, `/radar/performance`, `/radar/achievements` | `win_rate_pct`, `profit_factor`, `max_drawdown_pct`, `average_hold_hours`, `exits_by_reason`, milestones |

**Live events already published:** `token.discovered`, `market.changed`,
`score.changed`, `radar.changed`, `radar.ranking_changed`, `radar.score_updated`,
`paper.changed`, `real_wallet.changed`, `real_wallet.dry_run.changed`.

---

## 8. Missing data / signals

Each is **read-only** and additive. None touches trading logic.

| Gap | Affects | Proposal | Phase |
|---|---|---|---|
| No aggregate safety-evaluation counters | Atlas panel ("today: reviewed / rejected / liquidity failures / authority failures") | New `GET /real-wallet-safety/summary?window=24h` — `GROUP BY decision, reason_code` over `real_wallet_safety_evaluations` | HQ-5 |
| No Celery worker/queue introspection | Echo ("workers healthy?") | Extend `health/pipeline` with a `workers` block, or a new `GET /health/workers`. Enrichment depth is currently a proxy, not the truth. | HQ-10 |
| No DB/Redis latency surface | Byte incident mode | Add `postgres`/`redis` blocks to `/health/pipeline` | HQ-10 |
| No candidate-refusal counts | Radar→Luna funnel, Case File rejections | Expose aggregate `paper_decision_snapshots` refusal reasons | HQ-7 |
| No "last meaningful high" / momentum | Milo capital-efficiency panel | Derive client-side from `peak_price` + `current_pct` + `opened_at`. **Observation only.** | HQ-9 |
| No V2 strategy | Sage Strategy Lab | Out of scope. Lab renders V1 only and shows `NOT AVAILABLE` for V2. | — |
| No `hq.*` normalized events | Journey | **Not proposed.** Existing events suffice; see §19. | — |

Until each lands, the corresponding panel shows **`NOT AVAILABLE`**. No estimates.

---

## 9. HQ State Adapter design

```
 backend (unchanged)          adapter (new, frontend)         presentation
 ─────────────────────        ───────────────────────         ────────────
 GET /health/pipeline  ┐
 GET /api/v1/paper     ├──►  useHqSnapshot()  ──►  HqState  ──►  <Employee/>
 GET /real-wallet/status│         (TanStack)        (frozen)      <Zone/>
 WS  paper.changed     ┘                                          <Vault/>
 WS  radar.*           ──►  useHqEvents()   ──►  HqEvent[]  ──►  <Journey/>
```

`src/lib/hq/adapter.ts` — **pure functions, no I/O, no clock.** Matches the
codebase's existing engine-purity convention so it is unit-testable without a
network or a fake timer.

```ts
export interface HqState {
  office: OfficeActivity;                       // QUIET | NORMAL | BUSY | HIGH_ALERT
  employees: Record<EmployeeId, EmployeeState>;
  vault: VaultState;
  board: MissionBoardState;
  observedAt: string;
  degraded: DegradedSource[];  // which inputs failed — drives NOT AVAILABLE
}

export function deriveHqState(inputs: {
  pipeline: PipelineHealth | null;
  paper: WalletOut | null;
  realWallet: RealWalletStatus | null;
  now: number;
}): HqState;
```

Three rules, enforced by tests:

1. **A null input never produces a green state.** Missing data yields
   `offline` for that employee and `NOT AVAILABLE` in its panel — never `idle`,
   which would read as "healthy and quiet".
2. **The adapter is total.** Every backend shape maps to exactly one employee
   state. No `default: "working"` fallthrough.
3. **The adapter is the only place that knows backend field names.** Components
   receive `EmployeeState`, never `PipelineHealth`.

---

## 10. Employee state machine

```
        ┌──────────┐
        │ offline  │◄──── source null / stage down
        └────┬─────┘
             │ data arrives
        ┌────▼─────┐   activity      ┌──────────┐   backlog    ┌────────┐
        │   idle   │────────────────►│ working  │─────────────►│  busy  │
        └────▲─────┘                 └────┬─────┘              └───┬────┘
             │                            │                        │
             │        ┌──────────┐        │ evaluating             │
             └────────┤reviewing │◄───────┘                        │
                      └────┬─────┘                                 │
                           │                                       │
              ┌────────────┼───────────────┐                       │
         ┌────▼────┐  ┌────▼────┐    ┌─────▼────┐                  │
         │ success │  │  alert  │    │  error   │◄─────────────────┘
         └─────────┘  └─────────┘    └──────────┘
          (transient,   (sticky until  (sticky until
           ~4s decay)    condition       stage healthy)
                         clears)
```

Mapping (excerpt — the full table lives in the adapter's docstring):

| Condition | Employee | State |
|---|---|---|
| `scanner.status == healthy` and recent discovery | Radar | `working` |
| `scanner.connected == false` | Radar | `error` |
| `score.changed` for a top-ranked mint | Luna | `reviewing` |
| `market_enrichment.tracked_stale_count > 0` | Dex | `alert` |
| safety decision `REJECT` | Atlas | `alert` |
| safety decision `ALLOW` | Atlas | `success` (decays) |
| `paper.changed` with `opened > 0` | Rex | `working` |
| closed position, `net_pnl_usd > 0` | Rex | `success` |
| `queue_depth > threshold` | Echo | `busy` |
| `rpc.verified == false` | Byte | `alert` |
| `overall == down` | Byte | `error` |

**`success` decays; `alert` and `error` do not.** A green flash must not be able
to hide a red condition that is still true.

---

## 11. Office activity state machine

```
QUIET      no discoveries in 10m, queue < 50, no open evaluations
NORMAL     default
BUSY       queue_depth > 500 OR discovery rate > 20/min OR ≥1 evaluation in flight
HIGH_ALERT overall == down OR rpc unverified OR kill switch armed
```

**Localisation rule (explicit requirement):** `HIGH_ALERT` raises the *room* tint
only for infrastructure-wide failures. A single Atlas rejection sets
`atlas.state = alert` and lights the Risk Room lamp — it never touches
`office`. Implemented as: office activity reads only `pipeline` + `realWallet`,
never per-token events. Enforced by a unit test.

---

## 12. Token Case File architecture

```ts
interface CaseFile {
  caseNumber: string;        // derived from mint + first-seen, stable, not random
  mint: string;
  symbol: string | null;
  stages: {
    discovery:  StageRecord;   // Radar
    analysis:   StageRecord;   // Luna  — score
    market:     StageRecord;   // Dex   — liquidity/price freshness
    security:   StageRecord;   // Atlas — decision + reason_codes
    portfolio:  StageRecord;   // Milo  — eligible / refused + reason
    execution:  StageRecord;   // Rex   — paper buy/sell
  };
  status: "in_review" | "open_position" | "closed" | "rejected" | "unknown";
}

interface StageRecord {
  state: "pending" | "passed" | "failed" | "unavailable";
  at: string | null;
  detail: string | null;      // real reason code, verbatim
  source: "radar" | "scoring" | "market" | "safety" | "paper";
}
```

Rules:

- Every field traces to a response. **No field is computed to look complete.**
- A stage with no backing data is `unavailable`, rendered `NOT AVAILABLE` —
  not `pending`, which would falsely imply it is queued.
- Rejection detail uses **verbatim reason codes** (`UNSAFE_LIQUIDITY`,
  `MINT_AUTHORITY_ACTIVE`, `LIQUIDITY_SECURITY_UNKNOWN`), mapped to prose by an
  existing-style reason-code dictionary, never invented.
- Clicking navigates to `/tokens/{mint}` — the real page.
- Case files are **derived, not stored.** Assembled client-side from Radar +
  paper + safety responses. No new persistence, no new write path.

---

## 13. Token journey architecture

Only tokens that reach *candidate* status get a visible journey. Everything else
is aggregated into Radar's counter.

- **Transport:** a `DataPacket` — a small glowing SVG token that animates
  desk→desk along a precomputed path using `transform: translate3d()` on a
  single element. No character walks.
- **Budget:** max **3 concurrent** packets. A fourth increments a "+N" badge on
  the destination desk instead of spawning. Hard cap, enforced in the store.
- **Trigger:** a real `paper.changed` / `radar.score_updated` / safety decision.
  Never a timer.
- **Reduced motion:** packet does not travel. The destination desk's stage chip
  updates directly and the Case File row fills in.

Aggregation is the difference between charming and unusable at 300 tokens/min.

---

## 14. Active Position Board

Wall panel beside Milo. Reads `GET /api/v1/paper` → `positions[status=open]`.

```
RADON     +12.4%   held 2h 14m   ● ACTIVE
PEPE       −3.2%   held 47m      ● ACTIVE
TANUKI    UNKNOWN  held 1d 3h    ● NO MARKET
```

- Max 6 rows visible, `+N more` overflow → opens `/wallet`.
- `current_pct === null` renders `UNKNOWN`, never `0.0%`.
- Uses the existing freshness component's semantics for quote age. **Note:**
  `src/components/ui/freshness.tsx` is currently modified by another agent —
  HQ will *consume* it read-only and not edit it (§ Conflicts).
- Row click → `/tokens/{mint}`.

---

## 15. Holding-period observability

Milo's panel. **Observation only — HQ never triggers an exit.**

```
POSITION  RADON
Held                  7h 42m        ← now − opened_at
Return                +1.8%         ← current_pct
Peak return           +14.2%        ← peak_price vs entry_price
Time since peak       4h ago        ← DERIVED, marked as derived
Capital               $100          ← size_usd
CAPITAL EFFICIENCY    DECLINING     ← DERIVED LABEL
```

- Derived fields are visually marked as derived (subdued, `~` prefix) so they
  are never mistaken for backend truth.
- "Capital efficiency" is a **presentation label from a documented client-side
  rule**, not a strategy signal. The rule is written in the component docstring
  and asserted in a test.
- A future `TRAILING_STOP_25_TIME_V2` is explicitly **out of scope**. HQ emits
  no signal any strategy reads. Enforced by §35.

---

## 16. Mission Board

```
MEMESCOPE LIVE

Scanner        ● ONLINE          Scanning        142
Market data    ● HEALTHY         Reviewing         3
Paper wallet   ● ACTIVE          Open positions   12
Real wallet    ● DISABLED
Workers        ● HEALTHY
```

- Every row from `health/pipeline` + `paper` + `real-wallet/status`.
- **Real Wallet row is truthful and defaults to the safe reading.** If
  `/real-wallet/status` fails, it renders `UNKNOWN`, never `DISABLED` — the
  wrong direction of a wrong guess is claiming safety we did not verify.
- Click → existing `/command` / `/wallet` / `/real-wallet` pages.

---

## 17. Real Wallet Vault design

A sealed room adjoining Rex. **Display only. Cannot bypass anything.**

| Backend truth | Vault |
|---|---|
| `submission_permitted == false`, execution disabled | **LOCKED** — door sealed, red seam |
| any kill switch `active` | **LOCKED — HALTED** + actor/reason from the audit row |
| mode `armed` | **SEALED — ARMED** (rehearsal; still no submission) |
| mode `live` + release approved | **UNLOCKED** — only reachable state that shows green |
| status fetch failed | **UNKNOWN** |

Guarantees:

- Vault is a **pure function of `/real-wallet/status`**. It has no write path,
  no button that arms anything, and no local override.
- Rex's Paper desk and the Vault are visually unmistakable: open desk vs sealed
  room, crimson vs steel, "PAPER" vs "REAL" plate.
- A component test asserts: given `submission_permitted: false`, the Vault
  cannot render the unlocked variant under any prop combination.

---

## 18. Incident visualisation

| Condition | Visual | Localised to |
|---|---|---|
| RPC unverified | Byte `alert`, terminal amber | Ops/Tech |
| `overall == down` | Byte `error`, room tint | Whole office |
| Enrichment backlog high | Echo `busy`, queue board fills | Ops/Tech |
| `tracked_stale_count > 0` | Dex `alert`, stale badge | Trading floor |
| Safety `REJECT` | Atlas shield lamp red, Case File → rejected | Risk Room only |
| Scanner disconnected | Radar `error`, dish stops | Trading floor |
| Kill switch armed | Vault LOCKED — HALTED | Vault + Mission Board |

Every incident surfaces as **text + icon + colour**, never colour alone (§27).

---

## 19. WebSocket / event integration

**Decision: reuse `useLiveUpdates()`. Introduce no `hq.*` event namespace.**

Rationale: the existing hook already multiplexes seven event types over one
socket, handles reconnect/backoff, and exposes `LiveStreamStatus`. A parallel HQ
socket would double connections for zero new information — every signal HQ needs
is already on the wire. The brief's `hq.*` events are only warranted "if the
existing architecture genuinely benefits", and it does not.

HQ subscribes to the existing stream and maps events in the adapter:

```
token.discovered      → Radar pulse, scanning counter
radar.score_updated   → Luna reviewing, Case File analysis stage
market.changed        → Dex activity
paper.changed         → Rex + Milo + Case File execution stage
real_wallet.changed   → Vault re-read
```

`paper.changed` fires every few seconds under load (measured earlier this
session), so HQ **coalesces on a 500ms trailing edge** before touching state.

---

## 20. Component tree

```
app/(dashboard)/hq/page.tsx            ← route, lazy boundary
└── <HqProvider>                       ← adapter + store, one subscription
    ├── <HqStage>                      ← isometric transform container
    │   ├── <StationWindow/>           ← reuses space/objects.tsx
    │   ├── <MissionBoard/>
    │   ├── <Zone id="risk">   <Employee id="atlas"/>  <ShieldLamp/>
    │   ├── <Zone id="floor">  <Employee id="radar|luna|dex|rex"/>
    │   │                      <ExecutionVault/>
    │   ├── <Zone id="portfolio"> <Employee id="milo"/> <ActivePositionBoard/>
    │   ├── <Zone id="ops">    <Employee id="echo|byte"/> <QueueBoard/>
    │   ├── <Zone id="lab">    <Employee id="sage"/>  <AnalyticsWall/>
    │   ├── <Zone id="break">  <BreakRoom/>
    │   ├── <Nova/>                    ← patrol path, not a zone
    │   └── <JourneyLayer/>            ← ≤3 DataPackets
    ├── <EmployeePanel/>               ← side sheet, real metrics only
    ├── <CaseFilePanel/>
    └── <HqFallback/>                  ← mobile / reduced-motion / no-data
```

---

## 21. Asset strategy

- **No raster character art.** Layered inline SVG, one shared rig.
- **No sprite sheets.** The brief warns against giant sheets and the rig makes
  them unnecessary.
- **Room** is CSS + SVG gradients on transformed divs — no background image.
- **Props** are a single SVG sprite `<symbol>` file, `<use>`-referenced.
- **Starfield** reuses `universe.css` — zero new assets.
- Estimated added payload: **< 60KB gzipped**, all lazy.

---

## 22. Animation strategy

The reference offers no animation model, so this is invented and constrained:

| Layer | Technique | Cost |
|---|---|---|
| Idle loops (breathing, typing) | CSS `@keyframes` on `transform`/`opacity`, staggered `animation-delay` | GPU, zero JS |
| State transitions | CSS class swap + `transition` | zero JS |
| Nova patrol | CSS keyframe path along the walkway | zero JS |
| Data packets | `transform: translate3d()`, `transitionend` cleanup | ≤3 elements |
| Alert pulses | CSS animation on a single lamp element | zero JS |
| Screen flicker | `opacity` keyframes | zero JS |

**No `requestAnimationFrame` loop. No animation library.** Framer Motion is not
installed and this machine's npm registry access is blocked — the plan requires
zero new dependencies, which is also the brief's stated preference.

Pause when hidden: one `visibilitychange` listener toggles a
`data-hq-paused` attribute on the stage; CSS halts every animation via
`animation-play-state: paused`. One listener, no per-component teardown.

---

## 23. Performance budget

| Metric | Budget | Mechanism |
|---|---|---|
| Added JS on non-HQ routes | **0 bytes** | route-level `dynamic(() => …, { ssr:false })`; nothing imported from shared layout |
| HQ route JS | < 120KB gz | no new deps |
| HQ assets | < 60KB gz | SVG only |
| Animated elements | ≤ 60 | fixed cast; packets capped at 3 |
| React re-renders per event | ≤ 2 zones | Zustand selector subscriptions, not context broadcast |
| Network | 1 WS (shared) + 3 polled queries | TanStack `staleTime` ≥ 15s |
| Hidden tab | 0 animation, 0 poll | `visibilitychange` + `refetchIntervalInBackground: false` |

**Regression guard:** a test asserts `/wallet` and `/command` bundles contain no
`hq/` module. This is the brief's hardest performance requirement and the
easiest to break by accident.

---

## 24–26. Responsive experience

**Desktop (≥1280px)** — full isometric stage. Click zone → camera focus (CSS
`scale` + `translate` on the stage, not a real camera). Click employee → side
panel. Escape returns to overview. No free-roam controls.

**Tablet (768–1279px)** — stage renders at reduced density: zones remain, ambient
props and break room are dropped, Nova does not patrol. Zone focus becomes the
primary interaction.

**Mobile (<768px)** — **the stage is not rendered at all.** Per the brief, HQ
becomes a card stack:

```
[ Mission Board card ]     ← system status, full fidelity
[ Office activity chip ]
[ Department cards × 6 ]   ← tap → employee list
[ Employee cards × 10 ]    ← status + real metrics
[ Active positions ]
[ Recent case files ]
```

Identical data, zero isometric cost. This is a separate component tree, not a
CSS-hidden desktop scene.

---

## 27. Accessibility

- Every status is **text + icon + colour**. Never colour alone.
- Employees are `<button>`s with `aria-label="Atlas, Chief Risk Officer, alert"`.
- The stage is `role="img"` with a full text description; the card stack is the
  accessible equivalent and is what screen readers get.
- Live status changes announce via a single polite `aria-live` region,
  **throttled to one announcement per 5s** so a busy pipeline does not flood.
- Focus order follows journey order, matching the visual left→right reading.

---

## 28. Reduced motion

Follows the existing `use-reduced-motion` / `universe.css` convention exactly.

Under `prefers-reduced-motion: reduce`:
- all idle loops, patrol, packets and pulses stop;
- **every operational fact remains**: state chips, lamps, counters, panels,
  Case Files and the Mission Board are all static-readable;
- alerts become a static badge rather than a pulse.

The test: with motion disabled, a reader must still be able to answer every
Level-2 question in the brief. Asserted in a component test.

---

## 29. Testing strategy

| Layer | Test |
|---|---|
| Adapter | Pure unit tests: every backend shape → expected `HqState`; null inputs → `offline` + `NOT AVAILABLE`; totality (no fallthrough) |
| Office activity | A single Atlas rejection does **not** raise office to `HIGH_ALERT` |
| Vault | `submission_permitted:false` cannot render unlocked under any props |
| Case File | No field is populated without a backing source; missing → `NOT AVAILABLE` |
| Journey | ≥4 concurrent candidates produce 3 packets + a `+N` badge |
| Isolation | `/wallet` and `/command` bundles contain no `hq/` module |
| Reduced motion | All operational text present with animation disabled |
| A11y | Every employee has an accessible name including its state |

---

## 30. Files to add

```
frontend/src/app/(dashboard)/hq/page.tsx
frontend/src/lib/hq/employees.ts          ← the structured roster (§ brief)
frontend/src/lib/hq/adapter.ts            ← pure derivation
frontend/src/lib/hq/adapter.test.ts
frontend/src/lib/hq/case-file.ts
frontend/src/lib/hq/reason-codes.ts       ← code → prose, no invention
frontend/src/lib/hq/geometry.ts           ← tile → screen transform
frontend/src/hooks/use-hq-state.ts
frontend/src/hooks/use-hq-events.ts
frontend/src/components/hq/  (stage, zone, employee, nova, mission-board,
                              execution-vault, active-positions, queue-board,
                              analytics-wall, shield-lamp, journey-layer,
                              employee-panel, case-file-panel, break-room,
                              hq-cards/  ← mobile tree)
frontend/src/styles/hq.css
frontend/src/components/hq/*.test.tsx
```

Backend (read-only additions, later phases only):
```
backend/app/real_wallet_safety/api.py   ← + GET /summary   (HQ-5)
backend/app/health/schemas.py|service.py ← + workers/db/redis blocks (HQ-10)
```

## 31. Files to modify

| File | Change | Risk |
|---|---|---|
| `frontend/src/lib/design/nav.ts` | add one `HQ` item | **Clean at `64ae08b`.** Single-line addition. |
| `frontend/src/components/layout/nav-icons.tsx` | add `IconHq` | Clean. Additive. |

That is the complete list for HQ-1 through HQ-9. **No trading file, no backend
strategy file, and no file currently modified by the other agent is touched.**

---

## 32. Implementation phases

The brief's sequencing is sound; two amendments:

| Phase | Content | Amendment |
|---|---|---|
| **HQ-1** | Route, isolation, geometry, static shell, nav entry | — |
| **HQ-2** | 10 characters, desks, zones | — |
| **HQ-3** | **Adapter + state machine (no animation yet)** | **Moved earlier.** Building animations before the state model means animating a guess. Prove the data maps first. |
| **HQ-4** | Idle/working/busy/reviewing/alert/success animations | was HQ-3 |
| **HQ-5** | Mission Board + system health | was HQ-6 |
| **HQ-6** | Employee panels + `/real-wallet-safety/summary` | was HQ-5 |
| **HQ-7** | Execution Vault | **Promoted.** It is the highest-integrity element; it should exist before anything trade-shaped is drawn. |
| **HQ-8** | Case Files |
| **HQ-9** | Token journey + packet aggregation |
| **HQ-10** | Active Positions + holding-period observation |
| **HQ-11** | Ops/infrastructure visualisation + health additions |
| **HQ-12** | Day/night, break room, ambient interactions |
| **HQ-13** | Milestones (`/radar/achievements`), easter eggs, polish |

**HQ-1 is one PR. Nothing after it starts until you have seen the shell.**

---

## 33. Risks

| Risk | Severity | Mitigation |
|---|---|---|
| **Charm outruns truth** — HQ looks alive while data is stale | **High** | `offline`/`NOT AVAILABLE` never renders as green or idle; adapter tests enforce it |
| Event storm at 300 tokens/min | High | Aggregate; 3-packet cap; 500ms coalesce |
| HQ assets leak into `/wallet` | High | Bundle-isolation test |
| Vault misreads as unlocked | **Critical** | Pure function of status; unlocked variant unreachable when `submission_permitted:false`; dedicated test |
| Isometric CSS breaks at odd viewports | Medium | Fixed tile grid; mobile uses a different tree entirely |
| Scope creep into strategy | **Critical** | §35 |
| Merge conflict with the other agent | Medium | §34 — HQ touches two clean files |
| 10 characters × 8 states unshippable | Medium | Shared rig; differentiation is 4 SVG swaps |

---

## 34. Dependencies & conflicts

**New packages: none.** Uses React 19, Next 15, TanStack Query, Zustand,
Tailwind 4, and the existing `space/` + `universe.css` — all present.

**Files currently modified by the other agent** (must not be touched):
```
backend/app/paper/{api,schemas,service}.py   backend/app/middleware/alpha_access.py
frontend/src/app/(dashboard)/{launches,record,trending}/page.tsx
frontend/src/components/paper/positions-table.tsx
frontend/src/components/scanner/quick-detail.tsx
frontend/src/components/token/verdict-band.tsx
frontend/src/components/ui/freshness.{tsx,test.tsx}
frontend/src/types/paper.ts
```

HQ **consumes** `freshness.tsx` and `types/paper.ts` read-only and **edits
neither**. If HQ later needs a change in one, it will be raised rather than
made. The two files HQ modifies (`nav.ts`, `nav-icons.tsx`) are clean.

---

## 35. Areas that must remain isolated from trading logic

**HQ is strictly read-only. It has no write path to any trading system.**

Forbidden, and structurally prevented:
- No HQ module imports from `app/paper/strategy`, `app/real_wallet/*`,
  `app/real_wallet_safety/service`.
- HQ issues **no POST/PUT/PATCH/DELETE** to any trading endpoint — including
  the kill-switch endpoints, which HQ *displays* but never *calls*.
- No character decision influences any backend value.
- No HQ state is read by any strategy, guard, gate or scheduler.
- The Vault renders `/real-wallet/status`; it cannot arm, clear, or unlock.
- Milo's capital-efficiency label is presentation; no strategy consumes it.

**Enforcement:** an AST test in the style of the existing
`test_paper_purity.py` asserting that no `hq/` module imports a trading module,
and that no HQ hook issues a mutating request.

---

## Appendix — data integrity contract

| Situation | HQ shows |
|---|---|
| Endpoint failed | `NOT AVAILABLE` |
| Field null | `UNKNOWN` |
| No data yet | `WAITING FOR DATA` |
| Real Wallet status unknown | `UNKNOWN` (never `DISABLED`) |
| Derived value | marked as derived |
| Ambient animation | fictional, and never implies system state |

No fake activity, trades, tokens, profit, statistics, approvals, health, or Real
Wallet activity — anywhere, under any failure mode.
