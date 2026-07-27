# Project Status

Last updated: 2026-07-27 (end of Day 2)

## Milestones

| Day | Milestone                        | Status      |
| --- | -------------------------------- | ----------- |
| 1   | Platform foundation              | ✅ Complete |
| 2   | Solana token discovery engine    | ✅ Complete |
| 3+  | Not started                      | —           |

---

## Day 1 — Platform foundation ✅

Auth (JWT access + rotating httpOnly refresh with reuse detection), FastAPI
backend, Next.js frontend, PostgreSQL, Redis, structured logging, error
envelope, rate limiting, health probes, Docker Compose, GitHub Actions CI,
pytest + vitest.

## Day 2 — Solana token discovery engine ✅

A scanner process consumes Helius `logsSubscribe`, detects newly created SPL
tokens, resolves their metadata, persists them idempotently, and broadcasts each
discovery to connected clients in real time.

**What runs**

| Component        | Where                                   |
| ---------------- | --------------------------------------- |
| Scanner process  | `scanner` service, `app/scanner_main.py` |
| Helius client    | `app/services/helius/client.py`          |
| Parsing (pure)   | `app/services/scanner/parser.py`         |
| Pipeline         | `app/services/scanner/scanner.py`        |
| Persistence      | `app/repositories/token.py`              |
| Query use cases  | `app/services/token_service.py`          |
| REST + WebSocket | `app/api/v1/endpoints/tokens.py`         |
| Event fan-out    | `app/core/events.py`                     |
| Live feed UI     | `frontend/src/app/(dashboard)/feed/`     |

**Discovery source.** Watched programs are configurable
(`SCANNER_WATCH_PROGRAMS`); the default is the pump.fun program, where the
overwhelming majority of Solana meme coins launch. Detection keys off the
`InitializeMint`/`InitializeMint2` log marker, which is the authoritative signal
that a mint came into existence and covers both SPL Token and Token-2022.

**Measured on mainnet (10-minute run, 2026-07-27)**

```
events_received=169013  events_filtered=146  events_queued=146
tokens_discovered=146   tokens_duplicate=0   events_dropped=0
reconnects=0            resolve_failures=0
```

The pre-filter discards 99.91% of stream traffic before any RPC call, which is
what keeps the engine inside rate limits.

---

## Feature flags

| Flag                         | Default | Effect                                       |
| ---------------------------- | ------- | -------------------------------------------- |
| `FEATURE_SCANNER_ENABLED`    | `false` | Gates the scanner process. Needs `HELIUS_API_KEY`. |
| `FEATURE_AI_SCORING_ENABLED` | `false` | Day 3+ placeholder, no logic behind it.       |

Configuration refuses to boot if the scanner is enabled without a Helius key.

## Known limitations

- **Coverage is launchpad-scoped.** With the default configuration the engine
  sees pump.fun launches. A token minted directly against the Token program
  without a watched launchpad is not seen. Subscribing to the Token program
  itself is possible but delivers ~9k tx/25s, which is not viable to stream;
  broadening coverage should go through Helius webhooks instead.
- **Single scanner replica.** Each instance opens its own subscription, so
  scaling out would duplicate events rather than share them. Horizontal scaling
  needs partitioning by program or a shared work queue.
- **Metadata can lag.** Tokens whose metadata is not yet indexed are stored with
  `metadata_status=pending`. A backfill sweep for pending rows is not yet
  scheduled — `list_pending_metadata()` exists for it but nothing calls it.
- **No historical backfill.** The scanner only sees tokens launched while it is
  running; a restart leaves a gap.

## Test coverage

| Suite                     | Count |
| ------------------------- | ----- |
| Backend (unit + integration) | 106 |
| Frontend                  | 13    |

Backend coverage 82%. `ruff`, `mypy --strict`, ESLint, and `tsc` all clean.

## Next up (not started)

Day 3 is not begun. Natural candidates: metadata backfill sweep, historical
backfill on startup, liquidity/holder enrichment, AI risk scoring.
