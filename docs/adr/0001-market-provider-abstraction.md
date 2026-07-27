# ADR 0001 — Abstract the market data provider behind an interface

- **Status:** Accepted
- **Date:** 2026-07-27
- **Context:** Day 3, Token Enrichment Engine

## Context

The enrichment engine needs price, liquidity, volume, and trade counts for every
discovered token. Several vendors supply this for Solana — DexScreener, Birdeye,
Jupiter, GeckoTerminal, Helius' own DAS — and they differ in every dimension
that matters:

| Concern            | Reality across vendors                                  |
| ------------------ | ------------------------------------------------------- |
| Response shape     | Nested pairs, flat quotes, or per-pool arrays           |
| Auth               | None, API key, or signed requests                        |
| Batching           | 1, 30, or 100 addresses per call                         |
| Rate limits        | 60/min to 1000/min, sometimes tier-dependent             |
| Coverage           | Bonding-curve tokens are indexed by some, not by others  |
| Cost               | Free with throttling, or per-request billing             |

We picked DexScreener to start: no key required, broad Solana DEX coverage, and
30 addresses per request, which is what makes refreshing thousands of tokens
affordable inside a free rate limit.

That choice will not survive contact with scale. DexScreener does not report
liquidity for pump.fun bonding-curve pools (observed directly during Day 3 live
verification), has no SLA, and rate-limits aggressively. A paid provider is a
question of when, not whether. Meanwhile the tokens, snapshots, scheduler, API,
and frontend must be indifferent to who supplies the numbers.

## Decision

Define `MarketDataProvider` as an abstract base class in
`app/services/market/providers/base.py`, alongside a normalised `MarketData`
value object. Every layer above the provider package speaks only those two
types. Concrete adapters live beside the interface and are selected at runtime
through a registry keyed by the `MARKET_PROVIDER` setting.

```
MarketEnrichmentService ──▶ MarketDataProvider (ABC)
                                   ▲
                    ┌──────────────┴──────────────┐
              DexScreenerProvider          (future adapters)
```

Concretely:

- `MarketData` is provider-neutral, with **every field optional**. Partial data
  is the norm, not the exception.
- `fetch_many()` is the primitive; `fetch_one()` is a wrapper. Batching is part
  of the contract because it is the difference between one request and thirty.
- A token with no indexed pool is an **absent key**, never an exception. Only a
  genuine call failure raises `ProviderError`.
- Transport, auth, retry, and circuit breaking are the adapter's business.
  Services see a working provider or a `ProviderError`.
- The registry fails loudly on an unknown name rather than falling back to a
  default, so a typo in configuration cannot silently ship wrong data.

## Consequences

**Good**

- Swapping vendors is one new file plus one config change. No service,
  repository, schema, or endpoint moves.
- The service layer is testable without a network. `FakeProvider` in the worker
  tests reproduces outages, empty results, and partial payloads deterministically
  — impossible if services called `httpx` directly.
- Multi-provider fallback becomes tractable later: a `CompositeProvider`
  implementing the same interface can try vendors in order without any caller
  knowing.
- `provider` is recorded on every snapshot, so history stays interpretable
  across a vendor migration instead of silently changing meaning.

**Costs**

- One extra indirection between the service and the HTTP call. Acceptable: the
  interface is four methods.
- The normalised shape is a lowest common denominator. A vendor-specific field
  (say, a proprietary risk score) needs a deliberate interface change rather
  than being passed through. That friction is the point — it keeps vendor
  concepts from leaking into the domain.
- Each adapter must handle its own quirks, so adding a vendor is real work, not
  a config line. Also the point.

## Alternatives considered

**Call DexScreener directly from the service.** Fewer files today. Rejected:
every service test would need HTTP mocking, and the eventual vendor migration
would touch the service, the repository row builder, and the tests at once.

**A thin `dict`-returning client instead of a typed value object.** Rejected:
`data["liquidity"]["usd"]` would spread vendor JSON shape through the service,
which is exactly the coupling the abstraction exists to prevent. `MarketData`
also gives mypy something real to check.

**Normalise at the repository layer.** Rejected outright: it would make the
repository depend on an external API, and the brief is explicit that
repositories stay database-only.

## Verification

`tests/unit/test_provider_registry.py` registers a second implementation
(`StubProvider`) and drives it through the registry and the service, proving the
swap path works without touching business logic.
