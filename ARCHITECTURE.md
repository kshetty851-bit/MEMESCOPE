# MEMESCOPE Architecture

## High Level

```
                Helius WebSocket
                       │
                       ▼
              Discovery Service
                       │
                       ▼
                PostgreSQL
                       │
      ┌────────────────┴───────────────┐
      ▼                                ▼
 Market Enrichment              REST / WebSocket
      │                                │
      ▼                                ▼
 DexScreener                     Next.js Frontend
      │
      ▼
 AI Scoring Engine (Next)
```

---

## Backend

Framework:
- FastAPI

Database:
- PostgreSQL

ORM:
- SQLAlchemy Async

Cache:
- Redis

Worker:
- Celery

Migrations:
- Alembic

Authentication:
- JWT

---

## Frontend

Framework:
- Next.js 15

Language:
- TypeScript

Styling:
- Tailwind CSS v4

Architecture:
- Component driven

---

## Current Modules

Completed

- Authentication
- Discovery
- Market Enrichment
- Composite market provider (bonding-curve liquidity fill)
- Live Feed
- Observatory UI
- AI Scoring Engine
- Opportunity Radar and the permanent track record
- Exit Watch, Hall of Fame / Hall of Lessons
- Production deployment overlay (Caddy, backups, deploy/rollback)

Blocked on data that does not exist yet

- Smart Wallet Intelligence — no wallet addresses, transactions or holder lists
  in the schema. Reported unavailable rather than estimated.
- Rug Detection — needs mint/freeze authority and LP burn data.
- Narrative AI — token name and symbol are the only text the platform holds.

Upcoming

- Alerts (needs a delivery channel)
- Portfolio / watchlists
- Rotation engine (computable from the stored series today)

---

## Rules

Backend owns all business logic.

Frontend never fabricates data.

Frontend only renders backend state.

All features should be modular.

Prefer reusable services.

Keep APIs versioned.