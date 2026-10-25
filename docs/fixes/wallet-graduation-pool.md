# Graduation wallet: use the intended pool for market safety

## Incident

At 02:56 Dubai on 25 October 2026, the owner wallet attempted to buy
FRiWr1Mgw7mTY6eBrTmvQUNv8BxMGQgai99GRktipump. The safety evaluation rejected
LIQUIDITY_INVALID. Its freshly fetched snapshot described the old pump.fun
curve with null liquidity. The graduation recorder already had a live
DexScreener observation of the deterministic PumpSwap pool with $52,425.49.

A price or pool address made `MarketData.has_market` true, so the old refresh
path did not fall back to the lab observation. It also reused any recent
snapshot regardless of missing liquidity. Safety then independently selected
the latest token-wide snapshot, allowing the wrong pool to mask a valid older
observation of the intended pool.

## Correction

- For graduation intents, derive the canonical migration pool and pass the
  same pool to market refresh and safety evaluation. Unknown derivations refuse.
- Repository latest-snapshot reads optionally restrict to that pool and
  continue excluding quarantined snapshots.
- Reuse only current (non-future), positive-price, positive-liquidity pool data.
- If the provider returns an invalid or different pool, try a fresh live lab
  observation of that same canonical pool. No future, backfilled or different
  pool observation can stand in. Do not insert wrong-pool provider results on
  this path when the fallback is unavailable.
- Persist through the existing enrichment/sanity firewall; never unquarantine
  a suspect observation or waive any safety check. Preserve its observed time.
- Native vault-price cross-checks must also match the selected snapshot's pool.
- Other strategies keep their existing pool selection. Sells keep their
  existing path. No switch, strategy, trade size, funding rule, or threshold
  changes. Existing blocked intents stay blocked; idempotency is unchanged.

## Verification

98 unit and PostgreSQL integration tests pass in isolated containers sharing
only a disposable database namespace. No production credentials or external
network are supplied to those tests. New tests cover the incident shape,
wrong pools with positive liquidity, unusable cached values, older canonical
snapshots masked by newer wrong-pool snapshots, future lab rows, retained
quarantine, shared refresh/safety selection, and unchanged sells/blocked intents.

A separate database-enforced read-only replay of the actual incident selected
the canonical pool `8rdwPkUnVxH8cWFURB3Q4z6nM47vUBWVePguCu2gm7Vg`, liquidity
$52,425.49, observed 6.882077 seconds before evaluation. The market-data checks
accept that observation. The replay did not call the safety evaluator, create
orders, make RPC/Jupiter requests, or write database/Redis records. It does not
claim that a live order would necessarily have passed all later checks or filled.

## Release scope

Four application files only. Publish to the API and general Celery worker,
which executes both the minute tasks and fast real-wallet loop. Preserve each
service's image contents and runtime settings, retain rollback images, and
verify loaded source and worker health without manually running a trading tick.
No paper-lab API/frontend changes and no migrations. Do not reopen the stale
incident intent or submit any test order.
