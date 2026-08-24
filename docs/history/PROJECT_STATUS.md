# Project Status

Last updated: 2026-07-27 (end of Day 3)

## Milestones

| Day | Milestone                        | Status      | Tag                     |
| --- | -------------------------------- | ----------- | ----------------------- |
| 1   | Platform foundation              | ✅ Complete | —                       |
| 2   | Solana token discovery engine    | ✅ Complete | `v0.2-token-discovery`  |
| 3   | Token enrichment engine          | ✅ Complete | uncommitted             |
| 4+  | Not started                      | —           | —                       |

---

## Day 1 — Platform foundation ✅

Auth (JWT access + rotating httpOnly refresh with reuse detection), FastAPI
backend, Next.js frontend, PostgreSQL, Redis, structured logging, error
envelope, rate limiting, health probes, Docker Compose, GitHub Actions CI,
pytest + vitest.

## Day 2 — Solana token discovery engine ✅

A scanner process consumes Helius `logsSubscribe`, detects newly created SPL
tokens, resolves their metadata, persists them idempotently, and broadcasts each
discovery over WebSocket in real time.

Measured on mainnet: 169,013 stream events filtered to 146 creations in 10
minutes, 0 duplicates, 0 dropped, 0 reconnect failures.

## Day 3 — Token enrichment engine ✅

A second independent worker consumes discoveries and continuously enriches them
with market data on an adaptive schedule, writing append-only snapshots.

**What runs**

| Component            | Where                                            |
| -------------------- | ------------------------------------------------ |
| Enrichment worker    | `enrichment` service, `app/enrichment_main.py`   |
| Provider interface   | `app/services/market/providers/base.py`          |
| DexScreener adapter  | `app/services/market/providers/dexscreener.py`   |
| Provider registry    | `app/services/market/providers/registry.py`      |
| Circuit breaker      | `app/services/market/circuit_breaker.py`         |
| Adaptive scheduler   | `app/services/market/scheduler.py`               |
| Enrichment service   | `app/services/market/service.py`                 |
| Query service (read) | `app/services/market/query_service.py`           |
| Repositories         | `app/repositories/market.py`                     |
| REST API             | `app/api/v1/endpoints/market.py`                 |
| Live feed + details  | `frontend/src/app/(dashboard)/feed`, `/tokens/[mint]` |

**Independence from the scanner.** The worker is its own container. It listens
on the Redis discovery channel to enrol new tokens instantly, and drives all
subsequent refreshes from a database work queue. Stopping enrichment does not
affect discovery in any way.

A backfill sweep enrols any token that has no scheduling row. It runs at startup
**and every 5 minutes thereafter** — live verification showed that a
startup-only sweep left 1,411 tokens orphaned after their state was lost, since
the Redis listener only sees events published while it is connected. The
periodic sweep closed the gap to zero.

**Measured on mainnet (2026-07-27)**

```
tokens discovered      1,703        tokens enrolled     1,703   (0 unenrolled)
snapshots written      6,015        tokens with market  1,598   (93.8%)
provider latency       404 ms avg   p50 374 ms   p95 550 ms
refreshes              6,518        failures            0
dead-lettered          0            degraded cycles     0
history depth          25 max       3.76 avg per token
```

Adaptive scheduling is doing its job: 673 `fresh` tokens absorbed 5,452
refreshes (8.1 each) while 1,030 `young` tokens took 1,066 (1.03 each) — new
tokens are polled roughly 8× more often, exactly as intended.

Batching 30 mints per request is what makes this affordable: ~6,500 refreshes
cost roughly 220 provider calls.

**Resilience, verified live.** With the provider pointed at an unroutable
address, the circuit opened after 3 failures, calls failed fast (`latency_ms=0`),
a half-open probe fired at 60s and correctly reopened, the worker stayed up, and
**32 tokens were discovered during the outage** — proving discovery is genuinely
independent. On restore, snapshots resumed immediately with zero dead-letters.

---

## Feature flags

| Flag                         | Default | Effect                                              |
| ---------------------------- | ------- | --------------------------------------------------- |
| `FEATURE_SCANNER_ENABLED`    | `false` | Gates the discovery scanner. Needs `HELIUS_API_KEY`. |
| `FEATURE_ENRICHMENT_ENABLED` | `false` | Gates the market enrichment worker.                  |
| `FEATURE_AI_SCORING_ENABLED` | `false` | Day 4+ placeholder, no logic behind it.              |

## Known limitations

**Day 3**

- **DexScreener does not report liquidity for pump.fun bonding-curve pools.**
  Confirmed live: `liquidity_usd` is null for pre-graduation tokens while price,
  market cap, and volume are present. A second provider would fill this gap —
  which is exactly what the abstraction exists for.
- **Roughly half of brand-new mints are not indexed at first contact.** They are
  recorded as `consecutive_empty` and retried on a linear backoff; most resolve
  within a few minutes. Nothing is lost, but a token's first snapshot is
  typically a minute or two after discovery, not instant.
- **Single enrichment replica in practice.** The claim query is written for
  multiple replicas (`FOR UPDATE SKIP LOCKED` plus a lease), but this has only
  been exercised with one worker. Multi-replica needs a load test before it is
  trusted.
- **No snapshot retention policy.** At the observed rate the table grows by
  roughly 24k rows/hour with the scanner running. Time-based partitioning or a
  rollup job is needed before this runs for weeks. This is the most pressing
  follow-up.
- **`is_verified` is a proxy.** DexScreener has no true verification flag; a paid
  profile or label is used as the closest available signal.

**Carried over from Day 2**

- Coverage is launchpad-scoped (pump.fun by default); the Token program itself
  is too high-volume to stream.
- Single scanner replica by design — each opens its own subscription.
- No historical backfill of tokens launched while the scanner was stopped.

## Test coverage

| Suite                        | Count | Day 3 additions |
| ---------------------------- | ----- | --------------- |
| Backend unit                 | 109   | +57             |
| Backend integration          | 107   | +53             |
| Frontend                     | 32    | +19             |
| **Total**                    | 248   | +129            |

Day 3 test files: scheduler 21 · market API 19 · provider adapter 18 ·
market repository 18 · service + worker 16 · circuit breaker 10 ·
provider registry 8 · frontend formatting 15 · market hook 4.

Backend coverage 84%. `ruff`, `mypy --strict`, ESLint, and `tsc` all clean.

## Next up (not started)

Day 4 is not begun. Natural candidates: snapshot retention/partitioning, a
second market provider for liquidity coverage, price-change and momentum
derivations, AI risk scoring.
