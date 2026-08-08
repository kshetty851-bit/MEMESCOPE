# MEMESCOPE AI Context

This is the permanent handbook for AI collaboration. It reflects repository commit 4350212a804582ecc1e19ce229d51599a5364c74 (2026-08-05).

## Authority order

When sources disagree, use this order:

1. Current code, migrations, tests, and checked-in configuration.
2. Current operational evidence recorded in a dated commit or incident document.
3. PROJECT_STATE.md and DECISIONS.md.
4. SPRINT_HISTORY.md.
5. Older project, architecture, release, and design documents.

Do not use a stale document to justify changing working code. Record the conflict instead.

## Quick Start for AI Agents

1. Read AI_CONTEXT.md.
2. Read PROJECT_STATE.md.
3. Read SPRINT_HISTORY.md.
4. Read DECISIONS.md.
5. Audit the relevant repository area before changing it.
6. Never duplicate an existing subsystem.
7. Implement the smallest correct change.
8. Run full validation appropriate to the change.
9. Measure before and after when performance or behavior is involved.
10. Report honestly: distinguish verified facts, historical reports, unavailable data, and assumptions.

## Mission and product boundary

MEMESCOPE is a read-only intelligence system for Solana and Pump.fun tokens. It discovers tokens, records market and curve observations, produces deterministic scores and Radar records, detects change-based opportunities, and operates a paper-wallet strategy laboratory.

It is not a custody product, signing wallet, live trading system, price-prediction service, or financial-advice product. Its output describes recorded evidence and explicit system state; it does not recommend what a person should buy, sell, or expect.

## Product philosophy

- The opportunity is new; the token does not have to be. Every opportunity exists because something changed.
- Missing, stale, unscored, and empty states are legitimate states to explain rather than hide.
- Durable evidence is preferable to a transient impression. Historical records must remain interpretable.
- Backend calculations are authoritative. A browser renders facts; it does not create financial or business truth.
- No metric, explanation, or visual may imply information that the system did not observe.

## Architecture

The normal backend dependency direction is router → service → repository → database.

- Routes validate, authorize, call services, and return response models. They do not contain direct SQL or domain policy.
- Services own application behavior and appropriate transaction boundaries.
- Repositories own database access.
- Core modules remain free of application-specific imports.
- Vertical feature packages, including radar, opportunities, paper, and priority, follow the same direction.
- The documented inline-SQL/private-import exception in exit_signals/api.py is legacy, not a template.

Pipeline ownership is intentionally separated:

Solana RPC / WebSocket → scanner → discovered_tokens → Redis / token WebSocket

Enrichment queue → append-only market snapshots → scoring → current and historical scores

Persisted observations → Radar, intelligence events, Opportunity Engine, and Paper Wallet readers

Worker paths are not request-handler work. Scanner, enrichment, scoring, Radar, opportunities, paper review, curve collection, and priority enrichment have independent operational responsibilities.

## Backend and frontend

FastAPI serves versioned routes under /api/v1. SQLAlchemy/Alembic provide persistence; Redis and Celery support process coordination and scheduled work. Provider adapters normalize external data at the boundary, so domain code works with typed values instead of vendor JSON.

The Next.js frontend has protected dashboard routes and authentication routes. Its current dashboard destinations are Radar, Track record, Paper wallet, Strategy lab, and Settings. Settings is a placeholder. The dashboard root is Radar.

The frontend may format and present API data, but must not recompute scores, rankings, paper eligibility, entry logic, exits, costs, or other server-owned facts.

## Data and transaction integrity

- Use Decimal and NUMERIC for money, price, liquidity, and related quantities; serialize decimals as strings.
- Use timezone-aware UTC timestamps and ISO-8601 UTC API values.
- Market snapshots, score history, intelligence events, and paper-trade audit records are append-only.
- Current score writes are guarded against time regression. Radar first detection is immutable and its peaks only rise.
- Persist unavailable values with a reason. Never substitute an estimate for an observation.
- Request-scoped get_db owns request transactions; services/repositories flush. Worker entry points own their commits.
- Commit an observed enrichment snapshot before dependent scoring so later failure does not erase the observation.
- The database enforces one live paper wallet, unique paper positions per wallet/mint, and immutable audit evidence.
- Do not create foreign-key dependencies on prunable snapshots when retained audit evidence must survive retention.

## Determinism and shared systems

Calculation modules subject to the repository's purity tests must receive changing inputs explicitly and must not perform I/O, read a clock, use randomness, or read environment state. Keep orchestration outside pure functions.

Reuse a single source of truth for calculations. In particular, strategies publish the values they execute, eligibility is shared between evaluation and display, and live/Lab exit resolution uses shared logic where the rules are equivalent. A second local implementation of any score, eligibility, ranking, or exit rule is a defect.

## API conventions

- Prefix API routes with /api/v1 and use response models.
- Preserve the established error envelope and request-id behavior.
- Serialize decimals as strings and dates as UTC ISO-8601 values.
- For a known item with unavailable state, return explanatory state; reserve 404 for an unknown identity.
- Normalize provider data before it reaches services and batch provider work where the contract supports it.
- Make authentication-scope changes explicit product and security decisions.

## Coding, design, and testing standards

Use the repository's configured Ruff, mypy, frontend lint/typecheck, migration, unit, integration, contract, and AST-purity checks. Tests can write to their configured test database; never use them against a user-managed or production database.

New settings belong in backend/app/core/config.py, relevant environment templates, and the configuration-anchor tests. Schema changes need a new migration, never an edit to an applied migration.

The visual system is dark and restrained. Animate only material live changes, respect reduced motion, keep historical facts stable, and avoid fabricated precision, promotional language, and recommendation cues. Vocabulary tests protect current brand/product terminology.

## Things that must not change casually

- Read-only boundary: no custody, private keys, signing, or live execution.
- Evidence-first, deterministic, and explicit-uncertainty behavior.
- Server-derived financial and business values.
- Append-only evidence/audit semantics and immutable history.
- UTC timestamps and Decimal/NUMERIC financial calculations.
- Provider-normalization and pure-calculation boundaries.
- One-live-paper-wallet and immutable audit invariants.
- Opportunity-means-change semantics.
- No fabricated data, advice, predictions, guarantees, or retrospective rule changes.
- The configuration/session identity contract without a planned migration for existing sessions.
