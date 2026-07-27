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
- Live Feed
- Observatory UI

Upcoming

- AI Scoring
- Smart Wallet Intelligence
- Rug Detection
- Narrative AI
- Alerts
- Portfolio

---

## Rules

Backend owns all business logic.

Frontend never fabricates data.

Frontend only renders backend state.

All features should be modular.

Prefer reusable services.

Keep APIs versioned.