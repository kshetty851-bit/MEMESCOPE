# MEMESCOPE Roadmap

> Product Roadmap

---

# Vision

Build the world's best AI-powered crypto intelligence platform.

The goal is to discover opportunities before everyone else using AI, on-chain analysis and real-time market intelligence.

---

# Completed

## ✅ Day 1 – Foundation

- FastAPI backend
- PostgreSQL
- Redis
- Authentication
- Docker
- CI/CD
- Logging
- Testing

Status: Complete

---

## ✅ Day 2 – Discovery Engine

- Helius integration
- Solana token discovery
- Live WebSocket
- Token storage
- REST APIs
- Live feed

Status: Complete

---

## ✅ Day 3 – Market Enrichment

- DexScreener integration
- Historical snapshots
- Market enrichment
- Scheduler
- Circuit breaker
- Trending endpoint

Status: Complete

---

## ✅ Frontend Evolution

- Living Universe
- Observatory
- Mission Telemetry
- AI Core
- Observatory Log
- Animated AI sigils
- Command Mode

Status: Complete

---

## ✅ Day 4 – AI Scoring Engine

Deterministic weighted model, no ML or LLM in the scoring path. Score,
confidence, evidence, explanation and history. Weights published at
`/api/v1/scores/model`.

Status: Complete

---

## ✅ Phases 5–7 – Observatory, alpha surfaces, production rehearsal

Camera, Sentinel narration, About page, feedback, onboarding, Caddy edge,
backups, deploy/rollback. Six deployment defects found and fixed in rehearsal.

Status: Complete

---

## ✅ Phase 8 – Opportunity Radar

Tracks projects of any age. Returns measured from MEMESCOPE's first detection,
never from token launch. First detection immutable, records append-only, failed
opportunities never hidden.

Status: Complete

---

## ✅ Phase 9 – Exit Watch and the permanent record

Seven checkable signals, two declared and permanently unavailable. Never a sell
signal. Hall of Fame ranks by peak, Hall of Lessons by current, one page and one
toggle.

Status: Complete

---

## ✅ Phase 10 – Composite market provider

Fills the pump.fun bonding-curve liquidity gap, keyed by pool address. Opt-in
via `MARKET_PROVIDER=composite`.

Status: Complete

---

# Next Milestones

## 🚧 v0.8.0-rc1 → private alpha

Stabilisation, versioning and release preparation. See `RELEASE_NOTES.md`.

The remaining blocker for a public deployment is operational, not
engineering: no server, domain or credentials.

---

## Planned, and genuinely buildable now

### Rotation engine

Lead/lag over the stored series — volume leading price, liquidity leading
volume. Computable from data the platform already holds.

### `/market/trending` performance

A latest-snapshot pointer to replace the `DISTINCT ON` over the full
append-only snapshot table. Currently ~5–7s and degrading linearly.

### Second scoring signal source

On-chain bonding-curve reserves via Helius would close the liquidity gap
completely rather than partially.

---

## Blocked until the data pipeline exists

These are **not** scheduled work. Each needs a data source the platform does not
have, and none will be estimated in the meantime.

### Day 5 — Smart Wallet Intelligence

Needs wallet addresses, transactions and holder history. Historical
profitability additionally needs price-at-timestamp for arbitrary tokens across
arbitrary history — a dataset that cannot be reconstructed from our own records.

### Day 6 — Security & Rug Detection

Needs mint/freeze authority, LP burn and renouncement data. **Unlocks Elite.**

### Day 7 — Narrative Intelligence

Needs token metadata or a social provider. A keyword classifier over a ticker is
not narrative intelligence.

### Day 8 — Alerts

Needs a delivery channel. Must read state, not rely on event delivery.

### Day 9 — Portfolio

Watchlists, favourites, PnL.

### Day 10 — Public launch

Production deployment, monitoring, public launch.

---

# Future

Multi-chain support

Ethereum

Base

BNB

Sui

Aptos

Hyperliquid

---

# Long-term Ideas

- AI Portfolio Assistant
- Wallet Copy Trading
- AI Market Reports
- Mobile App
- Public API
- TradingView integration
- Portfolio risk analysis
- Whale heatmaps
- AI chat assistant
- Premium subscription

---

# Guiding Principle

Every feature should answer one question:

"Does this help users discover high-quality opportunities earlier and with greater confidence?"

If the answer is no, rethink the feature.