# ADR 0002 — Fill the bonding-curve liquidity gap with a pool-keyed secondary

- **Status:** Accepted
- **Date:** 2026-07-29
- **Context:** Closing the coverage gap ADR 0001 predicted
- **Supersedes:** nothing. Extends [ADR 0001](0001-market-provider-abstraction.md).

## Context

ADR 0001 recorded, on day 3, that "DexScreener does not report liquidity for
pump.fun bonding-curve pools". Measured against the live database on 29 July
2026, that shortfall is the single largest constraint on the product:

| DEX | Snapshots (2h window) | Null `liquidity_usd` | Share |
| --- | --- | --- | --- |
| `pumpfun` | 29,477 | 29,477 | **100%** |
| `pumpswap` | 850 | 0 | 0% |
| `meteora` | 12 | 0 | 0% |

pump.fun is **97% of all observations** and liquidity is missing for every one
of them. `liquidity_depth` carries 0.20 of the scoring model's weight, so this
one gap is why 17,727 of 19,590 scored tokens (**90.5%**) sit at 45% coverage
against a model ceiling of 65%, and why mean evidence across the feed is 44.6.

Every downstream honesty mechanism is working correctly — the gap is declared,
weighted, and charged to evidence rather than hidden. But the most useful thing
the platform could do for its own core claim is to stop having the gap.

## Decision

Add `CompositeProvider`, a `MarketDataProvider` that wraps the existing primary
and fills **only** missing liquidity from a secondary, keyed by **pool
address**. Selected with `MARKET_PROVIDER=composite`; the default is unchanged.

```
MarketEnrichmentService ──▶ CompositeProvider (MarketDataProvider)
                                   │
                    ┌──────────────┴──────────────┐
              DexScreenerProvider        GeckoTerminalPoolLiquidity
              (primary, unchanged)       (secondary, pool-keyed)
```

### The field choice, which is the whole decision

GeckoTerminal exposes reserves in two places. The mint-keyed one is the obvious
choice and is wrong. Measured against DexScreener on identical pools:

| Endpoint | Field | Keyed by | Agreement with DexScreener |
| --- | --- | --- | --- |
| `/tokens/multi/{mints}` | `total_reserve_in_usd` | mint | **0.49x – 0.97x** |
| `/pools/multi/{pools}` | `reserve_in_usd` | pool | **median 1.005x** (0.984–1.046, n=12, $50–$7,600) |

The mint-keyed field is roughly single-sided on thin pools and roughly
both-sided on deep ones, so it is not a constant factor that could be corrected
— it is a different quantity whose relationship to the primary's varies with
pool structure.

Writing it into `token_market_snapshots.liquidity_usd` would place two
meanings in one column. The consequence is worse than a wrong number: the
Radar's momentum dimension compares liquidity *across time*
(`LIQUIDITY_GROWING` / `LIQUIDITY_SHRINKING`), so a vendor changing between two
observations of the same token would manufacture a halving or a doubling that
never occurred, and Exit Watch would raise "liquidity leaving" on an artefact.

Pool-keyed lookup is possible because DexScreener returns `pool_address` for
**100%** of the rows it leaves without liquidity.

### Three rules, each preventing a specific silent failure

1. **A primary value is never overwritten.** The secondary fills `None` only.
   Reconciling two vendors' disagreement about a number the primary supplied is
   not this layer's business.
2. **A secondary failure costs nothing.** Any `ProviderError` — including an
   exhausted budget — returns the primary's batch intact. Snapshots are the
   durable asset; losing a batch to a supplementary lookup is a strictly worse
   trade than the figure it was fetching.
3. **Provenance changes only when the data does.** A filled row records
   `dexscreener+geckoterminal`; an unfilled one keeps `dexscreener`. A series
   can never change meaning without the `provider` column saying so.

### Budget

GeckoTerminal's free tier allows ~30 calls/min; `CallBudget` is set to 25 and
**never blocks** — it refuses and the fill is skipped. At 30 pools per call
that is ~750 pools/min against a measured enrichment peak near 4,000
tokens/min.

## Consequences

**Good**

- Nothing above the provider layer changed: no service, repository, schema,
  migration, endpoint or frontend edit. ADR 0001's central claim, tested.
- Liquidity becomes available for bonding-curve tokens for the first time,
  lifting `liquidity_depth` (0.20 weight) and therefore coverage, evidence and
  confidence on the tokens it reaches.
- Opt-in. `MARKET_PROVIDER` still defaults to `dexscreener`, so the change
  ships dark and is enabled deliberately.

**Costs**

- **Coverage is partial and must be reported as such.** The budget covers a
  fraction of peak demand; the rest keep the null liquidity they have today.
  `fill_stats()` exposes eligible/filled/skipped and the worker logs it per
  batch. Partial coverage is *not* biased: tokens are offered to the fill in
  the order the scheduler claimed them, which is `next_refresh_at` order, so
  they take turns rather than a favoured subset being permanently enriched.
- A token's liquidity may be present in one snapshot and absent in the next.
  This is strictly better than always-absent and creates no false trend,
  because every present value comes from the same semantic source — but
  consumers must continue to treat `liquidity_usd` as nullable.
- A second vendor is a second outage surface. It has its own circuit breaker
  and cannot open the primary's.
- `trading_status` is **not** re-derived after a fill. The threshold
  (`MIN_TRADEABLE_LIQUIDITY_USD`) belongs to the adapter that defines it, and
  duplicating it here would let the two drift.

## Alternatives considered

**Replace DexScreener with GeckoTerminal.** Rejected: GeckoTerminal's
`pools/multi` carries no buy/sell counts and its token endpoint reports
`market_cap_usd` as null for these tokens. It is complementary, not superior.

**Use the mint-keyed batch endpoint.** Rejected on the measurement above. It is
the cheaper integration and the reason this ADR exists.

**Derive bonding-curve reserves on-chain via Helius.** The correct long-term
answer — the curve account holds the real SOL reserve, `getMultipleAccounts`
takes 100 accounts per call, and the key is already configured, so it would
cover 100% of demand rather than a fraction. Deferred, not rejected: it needs
PDA derivation and account-layout decoding, which is a different kind of work
from a market adapter and deserves its own verification pass. See
[§14](../../MEMESCOPE_MASTER_CONTEXT.md#14-roadmap).

**Block enrichment until budget refills.** Rejected outright: it trades a
complete snapshot for a late one, and a snapshot timestamped two minutes after
the observation it describes is silently wrong data.

## Verification

- `tests/unit/test_composite_provider.py` — 30 tests locking the three rules,
  including that a filled row changes provenance and an unfilled one does not.
- `tests/unit/test_geckoterminal_provider.py` — adapter parsing, including that
  an indexed pool reporting no reserve is absent rather than zero.
- `tests/unit/test_rate_budget.py` — continuous refill, non-blocking refusal.
- Verified live against both real APIs: 5 of 6 bonding-curve tokens filled,
  the sixth correctly left null as not-yet-indexed, provenance recorded, one
  budget token spent.
