# Sprint 28 — Reality Audit & Live Radar Platform

**Design only. Nothing here is implemented.** Every figure was measured against
the running system on 2026-08-04; none is estimated. Where a thing could not be
measured it says so rather than guessing.

**Numbering note.** The brief called this "Sprint 27 & 28". Sprint 27 is already
committed (`023e220`, execution costs). This document is Sprint 28, and Part B
records what Sprint 27 already answered so the two are not built twice.

---

# PART A — REALITY AUDIT

## A1. Peak / current / now identity — exact counts

**88 Radar tokens.** 6 have `current_price = peak_price`; 8 have
`current_market_cap = peak_market_cap`. The asymmetry is itself the finding.

| Cause | Count | Evidence |
|---|---|---|
| **Genuinely at ATH** | 3 | `peak_price = max(observed)`, snapshot < 25 min old (SAOF, CATE, TNOS) |
| **Genuinely at ATH, but stale data** | 1 | USWR — at its true max, snapshot **169 min** old |
| **Sweep latency** | 2 | Instagram, NEEGSEM — a higher price exists in snapshots *newer than the last sweep*; corrects itself next cycle |
| **`peak_market_cap` data bug** | 2 | SAOF ×2 — `peak_price` is **30× `current_price`** yet `peak_market_cap = current_market_cap` exactly |
| Provider issue | 0 | none found |
| Display bug | 0 | none found — the API serves what is stored |

### The one real bug: `peak_market_cap` is not raised with `peak_price`

**6 of 88 tokens (6.8%)** carry an internally inconsistent peak:
`peak_price > current_price` while `peak_market_cap <= current_market_cap`.

Cause is in `radar/repository.py::update_current`:

```python
if price is not None and candidate == price:
    entry.peak_market_cap = market_cap
```

`peak_market_cap` is written **only** when the peak candidate is the *current*
price. When the peak rises from `window_high` — a high observed between sweeps —
the market cap is left behind. The comment defends this ("a historical high has
no market cap stored beside it, and inventing one would be wrong") and the
*intent* is right, but the premise is wrong: the snapshot that recorded the
window high **does** carry a market cap. Reading it is not inventing.

**Consequence:** the Track Record's "Peak market cap" column understates the
peak, and can equal current market cap on a row whose multiple says 30×.

**Proposed fix (not implemented):** have `window_high` carry its snapshot's
market cap alongside the price, and write both together. Monotonic guarantee
unchanged. Backfill is *not* proposed — the historical rows cannot be corrected
without rewriting a permanent record, so the fix should apply forward only and
the discontinuity should be dated in `SESSION.md`.

### Not a bug

`current == peak` on a token at its genuine high is correct and expected. On a
monotonically rising token it will always be true. Sweep latency (15-minute
cadence) accounts for the rest and self-corrects.

---

## A2. Pump.fun provenance — verified on chain, not by name

**All 88 tokens: `source_program = 6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P`**
(the pump.fun program), with a creation signature and block time on every row.
Admission filters on this column, so provenance is structural.

| Field | Coverage |
|---|---|
| `source_program` = pump.fun | 88 / 88 (100%) |
| Creation transaction signature | 88 / 88 |
| Creation block time | 88 / 88 |

**No token entered the Radar from a non-pump.fun origin.** There is no path that
could: the candidate query joins on `DiscoveredToken.source_program == PUMPFUN_PROGRAM_ID`.

### Current venue

| Venue | Tokens | Meaning |
|---|---|---|
| pumpswap | 87 | Graduated to pump.fun's own AMM |
| meteora | 1 | Graduated, then migrated to Meteora |
| pumpfun (bonding curve) | 0 **currently** | 39 have curve history; all have since graduated |
| Raydium / other / unknown | 0 | — |

**Every Radar token has graduated.** None is currently on a bonding curve. This
matters for Part B.

### The finding the brief did not ask for: symbol collision

| Symbol | Distinct mints | Market cap range |
|---|---|---|
| **TNOS** | **9** | $1,307 – $83,173,327 |
| **SAOF** | **5** | $1,381 – $201,739,216 |
| *(no symbol)* | 4 | $8,289 – $5,581,583 |
| USOP | 4 | $1,323 – $1,718 |
| USWR | 4 | $1,318 – $3,750,778 |
| GDWR | 3 | $1,342 – $1,652 |
| TikTok | 2 | $1,374 – $1,402,118 |

**Nine distinct mints are called "TNOS", spanning a 63,000× market-cap range.**
These are all genuine pump.fun mints — they are copycats, the standard pattern
where a trending ticker is cloned within minutes.

The Radar currently shows them side by side with **no way to tell which is
which**. A trader reading "TNOS" on the homepage cannot know if it is the
$83M original or one of eight $1,300 clones. `tokenNaming()` shortens the mint
away and shows only the symbol.

This is the most consequential product finding in the audit, and it is not a
data problem — the data is correct. It is a **presentation** problem that
directly contradicts the platform's honesty principle.

**Proposed (not implemented):** surface a collision marker on any row whose
symbol is shared by another tracked mint, showing the mint prefix and the rank
of this mint by market cap among its namesakes. No new data required.

---

## A3. Tradeability

| State | Tokens | % |
|---|---|---|
| Currently tradeable (`trading`, liquidity > 0) | 88 | **100%** |
| Not tradeable | 0 | 0% |
| Delisted | 0 | 0% |
| Pool removed | 0 | 0% |
| Liquidity zero | 0 | 0% |
| Unknown | 0 | 0% |

Liquidity distribution:

| Band | Tokens |
|---|---|
| ≥ $10,000 | 20 |
| $1,000 – $10,000 | 68 |
| < $1,000 | 0 |

**Correction to what I told you last turn.** I previously framed median
liquidity of ~$1,857 as evidence these tokens are barely tradeable, citing an
mcap/liquidity ratio of 178×. That ratio was an **outlier**, not the norm:

| | |
|---|---|
| Median market cap | $1,717 |
| Median liquidity | $1,814 |
| **Median mcap / liquidity** | **≈ 1×** |
| Tokens above 10× | 8 |
| Tokens above 50× | 2 |

Liquidity is *proportionate* to size for the typical Radar token. They are small,
not hollow. The price-impact figure I gave stands (a $100 order into $1,814 moves
the price ~11%), but "you could not exit" was wrong for the median case and right
only for the two outliers.

---

## A4. Market data freshness — **the platform's biggest live problem**

Snapshot age across all 88 Radar tokens:

| | Minutes |
|---|---|
| Best | 0 |
| **Median** | **29** |
| **95th percentile** | **7,347** (5.1 days) |
| Worst | 7,848 (5.4 days) |
| **Older than 1 hour** | **38 of 88 (43%)** |

Radar sweep age is uniform at 8 minutes (15-minute cadence, working correctly).

### It reaches the homepage

Of the **Top 10 rows a user actually sees**, three carry market data
**169 minutes old**:

| Rank | Symbol | Snapshot age |
|---|---|---|
| 5 | GUNS | **169 min** |
| 6 | USWR | **169 min** |
| 9 | Gnomes | **169 min** |

These are presented with no staleness indicator. Sprint 24 put `captured_at` on
the price cell's `title` attribute — a hover tooltip, which is not sufficient
for a three-hour-old price on a page headed "Today's best opportunities".

### Root cause: enrichment queue depth, not a broken worker

| Metric | Value |
|---|---|
| Enrichment queue (`active`) | **36,154 tokens** |
| Dead-lettered | 5 |
| Throughput | 723 snapshots/min |
| Distinct tokens enriched per hour | 11,491 |
| **Full-queue cycle time** | **≈ 50 minutes** |
| Radar-token revisit gap — median | 6 min |
| Radar-token revisit gap — p95 | **106 min** |
| Radar-token revisit gap — worst | **144 min** |

The worker is healthy and fast. **Radar tokens are not prioritised in the
queue** — they compete with 36,000 others, so a tracked token can wait two hours
for a refresh.

### The health endpoint reports this as healthy

`/api/v1/health/pipeline` returns `"overall": "healthy"` while 43% of Radar
tokens are stale, because it only asks "was *any* snapshot written recently?"
It does not check per-token freshness or queue depth against a threshold.

**Proposed (not implemented):**
1. **Priority lane for Radar tokens** in the enrichment queue — the ~88 tracked
   tokens refreshed on a fixed short interval regardless of global backlog.
2. **Freshness in the health contract** — publish p95 snapshot age for tracked
   tokens and degrade `overall` when it exceeds a published threshold.
3. **Visible staleness on the row** — not a tooltip. A price older than the
   sweep interval should be marked on the face of the row.

---

## A5. Snapshot correctness

Replayed rather than spot-checked. Findings:

- **Price**: internally consistent. `peak_price` matches `max(observed)` for all
  but the 4 sweep-latency cases in A1, each of which resolves next cycle.
- **Market cap**: the `peak_market_cap` defect in A1 is the only inconsistency
  found. 6 of 88 affected.
- **Liquidity**: 100% populated on pumpswap and meteora; **0% on pumpfun
  bonding-curve rows** (ADR 0002, confirmed still true — 997 curve snapshots,
  none with liquidity).
- **Volume**: 1 of 88 tokens reports zero 24h volume; all others positive.

**Not verified, and cannot be from stored data:** whether the provider's price
matches the chain at that instant. The platform stores what the provider
returned; it has no independent oracle. Any claim that snapshots are *accurate*
rather than *faithfully recorded* would be unfounded. Verifying this needs a
second independent price source, which is a separate piece of work.

---

# PART B — PAPER TRADING REALISM

## B1. What Sprint 27 already answered

Do not rebuild these:

| Cost | Status |
|---|---|
| Swap / DEX / protocol fee | **Modelled** — published bps per side, configurable |
| Price impact | **Modelled** — exact constant-product `S/Y` against depth observed at each end |
| Pool depth | **Modelled** — read from the snapshot at entry and at exit |
| Slippage from competing flow | **Refused** — needs the mempool; platform stores snapshots |
| MEV exposure | **Refused** — same |
| Priority fee | **Refused** — same |

Measured effect (live, 88 tokens): drag ranges **3.70 to 11.56 points**, and it
is **progressive** — the exit is charged on what the position is worth when it
closes, so the rules that win most pay most to leave. After costs, 5 of 9
strategies stay positive.

## B2. Fee / slippage / impact drag, separated

The brief asks for fee drag, slippage drag and impact drag as separate columns.
Sprint 27 reports only the combined figure.

**Proposed:** split `cost_drag_pct` into `fee_drag_pct` and `impact_drag_pct`.
Both are already computed separately inside `costs.SideCost` — this is a
reporting change, not a model change. **`slippage_drag_pct` must not be added**:
it would be a null column implying a measurement that does not exist. The
refusal should stay a stated refusal.

## B3. Bonding-curve trades — should they be simulated at all?

**Measured: the question is currently moot, and that itself is the answer.**

- 0 of 88 Radar tokens are *currently* on a bonding curve.
- 39 have curve history; all graduated before or during tracking.
- 0 of 88 lab trades were excluded for missing depth (`uncosted_trades = 0`).

Every simulated entry landed on a graduated pumpswap pair with reported
liquidity. **No bonding-curve trade is being simulated today.**

**Recommendation: keep it that way, explicitly.** Bonding-curve fills cannot be
costed from stored data (no liquidity, and `bonding_curve_snapshots` does not
exist in this database — the Sprint 8 migration was never applied here). If the
Radar's admission window ever shifts earlier, curve trades would silently enter
the simulation uncosted. The guard should be explicit rather than incidental:
exclude pre-graduation entries by rule, publish the count, and state why.

## B4. Wallet realism

| Dimension | Current behaviour | Assessment |
|---|---|---|
| Position sizing | Fixed $100, equal weight | Realistic and deliberate |
| Capital reuse | Cash derived; freed on close, reusable same pass | Correct |
| Cash availability | Binding — declines entry when short | Correct, and *more* honest than the lab |
| **Partial fills** | **Not modelled** — an order fills whole or is declined | Defensible; a partial fill needs a fill model |
| **Maximum position size** | **Not capped against pool depth** | **Gap** |
| Wallet utilisation | 100% deployed (10 × $100 of $1,000) | Measured |

**The one real gap: no position size cap relative to pool depth.** A $100 order
into the median $1,814 pool is 5.5% of the pool and moves price ~11%. The
simulation charges that impact (Sprint 27) but never asks whether the order
should have been placed at all. A live trader would not take 5% of a pool.

**Proposed:** a published maximum — position size may not exceed *N%* of pool
depth — and entries above it declined and counted, exactly as the cash
constraint already works. `N` becomes part of the published strategy.

---

# PART C — LIVE RADAR PLATFORM

## C1. Where updates actually stop — measured

| Hop | Latency | Source |
|---|---|---|
| Chain → scanner | ~0 s | `last_discovery` 0.0 min, WS connected |
| **Scanner → enrichment snapshot** | **median 6 min, p95 106 min, worst 144 min** | revisit-gap query |
| Snapshot → Radar sweep | 0–15 min (median 8) | `crontab(minute="*/15")` |
| Radar → API response | **12 ms** | `/radar?page_size=10`, 5 runs |
| **API → screen** | **0–120 s** | `RADAR_POLL_MS = 120_000` |

### End-to-end, chain to browser

| | Latency |
|---|---|
| Best | seconds |
| **Median** | **≈ 15 min** |
| **95th percentile** | **≈ 123 min** |
| Worst observed | ≈ 161 min (matches the 169-min Top-10 rows) |

### The conclusion that should govern this sprint

**Enrichment revisit (p95 106 min) is 53× the polling interval (2 min).**

Building WebSockets first would remove the *smallest* term in a two-hour chain
and change median latency from ~15 min to ~14 min. The screen would update
instantly — with data that is still two hours old.

**Recommended order is therefore the reverse of the brief's:**

1. **Priority enrichment lane for tracked tokens** — attacks the 106-minute term.
2. **Radar sweep on snapshot arrival** for tracked tokens — attacks the 15-min term.
3. **WebSocket push** — attacks the 2-min term, and is only worth doing once the
   two above make "live" true.

Shipping 3 before 1 produces a terminal that animates stale numbers, which is
worse than a page that visibly polls.

## C2. Existing infrastructure — reuse, do not rebuild

**A WebSocket stack already exists and is running.**

- `core/events.py` — per-process fan-out hub bridging Redis pub/sub to local
  WebSockets, explicitly built so a thousand clients do not open a thousand
  Redis connections.
- `main.py` — starts the bridge on app startup.
- `api/v1/endpoints/tokens.py:112` — `@router.websocket("/stream")`, live.
- Redis channels namespaced by `ENVIRONMENT` (`settings.token_channel`).

It carries **scanner discovery events only**. The Radar, the Opportunity Engine
and the paper wallet publish nothing to it.

**No new event bus is needed.** The work is to publish additional event types
onto the channel that already exists and add a Radar-scoped WebSocket route.

## C3. Event schema

Every event carries **only changed fields**, plus identity and a monotonic
sequence number for gap detection. Never the table.

```
{ "seq": 918273, "type": "price_updated", "at": "2026-08-04T18:39:51.964Z",
  "mint": "FnDxikf…pump",
  "changed": { "price_usd": "0.1647", "market_cap": "164698846", "captured_at": "…" } }
```

| Event | Emitted by | Payload |
|---|---|---|
| `price_updated` | enrichment worker | price, market cap, liquidity, volume, captured_at |
| `score_updated` | radar sweep | score, confidence, evidence, risk band |
| `ranking_changed` | radar sweep | ordered list of top-N mints only |
| `new_token` | radar detector | full row (it has no prior state) |
| `token_dropped` | radar sweep | mint, reason |
| `signal_opened` / `signal_closed` | opportunity engine | mint, signal type, label, expiry |
| `paper_trade_opened` / `paper_trade_closed` | paper scheduler | mint, entry/exit, reason, pnl |
| `achievement_unlocked` | radar achievements | mint, tier, multiple |
| `pulse` | API, 5 s | Market Pulse counters only |

**Design rules:**
- `seq` is per-channel and monotonic. A client detecting a gap refetches the
  affected rows over REST rather than guessing — **no silent divergence**.
- Money stays a decimal **string**, as everywhere else.
- Events are **facts, not instructions**. No event tells the client to reorder;
  `ranking_changed` states the new order and the client reconciles.
- An event whose token the client does not hold is dropped client-side.

## C4. Frontend behaviour

- Row-level subscription keyed by mint; React Query cache updated in place via
  `setQueryData`, so one token changing re-renders one row.
- **Reconciliation on reconnect**: fetch the full page once, then resume the
  stream from the last `seq`. A missed event can never leave a stale row.
- **Fallback**: if the socket fails twice, fall back to the current 120 s poll
  and show it. Degrading silently to polling while the Pulse says "LIVE" would
  be the dishonesty this platform exists to avoid.

## C5. Animation

| Change | Treatment |
|---|---|
| Price up | 180 ms green background wash, ease-out, then clear |
| Price down | 180 ms red wash |
| Score change | 1-frame border highlight, no colour |
| Ranking change | FLIP transform, 240 ms, `cubic-bezier(.2,0,0,1)` |
| New token | slide in from top, 200 ms |
| Removed token | fade to 0 over 200 ms, then collapse height |

Constraints: no easing bounce, no scale, no sound, no colour outside the
existing `--color-safe` / `--color-danger` tokens. **Respect
`prefers-reduced-motion`** — flashes become a static 1-frame border. Bloomberg
does not celebrate a tick.

---

# PART D — MARKET PULSE

One dense row above the Radar. No cards, no mascot, no storytelling.

## Measurable today — ship these

| Metric | Source | Measured now |
|---|---|---|
| Scanner status + last event | `/health/pipeline` | healthy, 0.0 min |
| Enrichment status + last snapshot | `/health/pipeline` | healthy, 0.0 min |
| **Queue depth** | `token_enrichment_state` | **36,154** |
| Dead-lettered | same | 5 |
| Radar last sweep | `/health/pipeline` | 9.9 min ago |
| Tracked tokens | `radar_tokens` | 88 |
| Database | connection check | up |
| API latency | request timing | 12 ms |
| **Tracked-token snapshot p95** | derived | **7,347 min** ← the honest headline |
| Signals active / pending | `opportunity_signals` | queryable |
| Paper wallet equity + open | `/paper` | queryable |

## Not measurable today — must not appear

| Metric | Why |
|---|---|
| **Pump.fun launches today** | The scanner records what *it* saw, not what the chain produced. Publishing our count as the network's would overstate coverage. |
| **New launches last hour** | Same. |
| **Observable markets** | No definition backed by a stored figure. |
| **Last block event** | The scanner stores discovery time, not block height. |
| **Current latency (chain→screen)** | Not instrumented end to end. Derivable only after C1's work lands. |
| **WebSocket status** | No Radar socket exists yet. |

**Rule:** a Pulse metric ships only when a query returns it. Anything else is
absent, and the absence is visible.

## The honest headline

The Pulse's job is to reassure that the platform is watching. Given A4, the most
truthful single figure is not "88 tracked" but **freshness**: tracked-token p95
snapshot age, coloured against a published threshold. Today it would read red.
That is the point.

---

# PART E — VALIDATION PLAN

Measure before and after; nothing ships on assertion.

| Dimension | Method | Current baseline |
|---|---|---|
| UI latency | `performance.mark` around row commit | not instrumented |
| WebSocket latency | `seq` timestamp vs client receipt | n/a |
| Database latency | `EXPLAIN ANALYZE` on the hot path | radar page 12 ms |
| Rows updated/sec | client counter | n/a |
| Reconnects / dropped events | `seq` gap counter | n/a |
| CPU / memory | `docker stats` under load | to capture |
| Bandwidth | bytes/min per client vs polling | polling: ~1 payload / 120 s |
| Failure behaviour | kill Redis, kill API, sever socket | to test |
| Fallback polling | assert it engages **and is disclosed** | n/a |
| Recovery time | reconnect → first correct row | n/a |

**Load target to state up front:** the Radar shows 10 rows; the Pulse ticks
every 5 s. Expected steady-state is **< 5 events/sec** to a client. Any design
needing more than that is solving a problem this product does not have.

---

# MIGRATION STRATEGY

Four independently shippable steps, each with its own measurable win. None
requires the next.

| Step | Change | Attacks | Risk |
|---|---|---|---|
| **1** | Priority enrichment lane for tracked tokens | p95 106 min → target < 5 min | Low — queue ordering only |
| **2** | `peak_market_cap` carried with `window_high`; forward-only | 6.8% inconsistent peaks | Low — additive; **no backfill** |
| **3** | Symbol-collision marker on Radar rows | 9 mints named TNOS | None — presentation only |
| **4** | Radar events on the existing channel + WS route + reconciliation | 2 min → sub-second | Medium — needs fallback and gap detection |

Steps 1–3 are small, high-value, and independent of the realtime work. **Step 4
should not begin until step 1 is measured**, because until then "live" would be
a claim about the transport rather than about the data.

---

# RECOMMENDATION

The brief asks for a live terminal. The measurement says the terminal is not
where the problem is.

**The Radar is not slow to display. It is slow to know.** Median chain-to-screen
is ~15 minutes and p95 is ~2 hours; the polling interval contributes 2 minutes
of that. Three of the ten rows on the homepage right now carry prices from
nearly three hours ago and say nothing about it.

Ranked by measured impact:

1. **Enrichment priority for tracked tokens** — the 106-minute term.
2. **Visible staleness on the row** — honest today, costs nothing, and stops the
   product overstating what it knows while step 1 is built.
3. **Symbol-collision marker** — nine TNOS tokens is a trust problem shipping now.
4. **`peak_market_cap` fix** — 6.8% of rows internally inconsistent.
5. **WebSocket push** — genuinely valuable, and worth doing *after* the data
   behind it is fresh.

Steps 2 and 3 could ship in a day and would make the product more honest
immediately. Step 5 is the largest build and the smallest latency win.
