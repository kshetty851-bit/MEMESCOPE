"""GRADUATION LAB — pump.fun tokens approaching the top of the bonding curve.

A recorder, and nothing else. It watches new launches, follows their curves up
from the chain, and fills five tables:

* `grad_tokens`           one row per mint it has ever watched, plus the
                          aggregates that survive pruning;
* `grad_curve_samples`    the reserve series, polled from the bonding curve
                          account, written when something moves;
* `grad_checkpoints`      one row per token per level (70/80/90/95/100%);
* `grad_migrations`       the graduation event;
* `grad_postgrad_samples` price, volume and buy/sell counts for the hour after.

`grad_trades` exists and is empty — see `models.GradTrade`.

No backtester, no paper trader, no frontend, no scoring. The point is to have
the data later, because the platform's RPC-polled collector could not see this
state: of 218 curves observed complete on 2026-09-09, **217 were never once
observed incomplete** — that collector piggybacks on the enrichment cycle,
which samples far too slowly. A dedicated poll of a bounded watch set can.

## Everything here is free

Discovery is PumpPortal's `subscribeNewToken` and `subscribeMigration`, both
free and neither needing a key. Progress is `getMultipleAccounts` against any
Solana node — one call per hundred tokens, because the curve address is derived
locally rather than looked up. Post-graduation market data is DexScreener, with
GeckoTerminal for gaps.

Nothing is metered. What that costs is per-TRADE detail: the account reports
reserves, not who moved them, so this lab cannot count buyers or holder
concentration at any price. Those columns are kept and left null — "not
collected", never "none".

Isolated the way the Breakout and Early Movers labs are: its own `grad_*`
tables, its own flag (`LAB_GRADUATION_ENABLED`, default off), its own config
module, its own tests. It imports no paper wallet, no real wallet, no radar and
no sibling lab; `tests/test_isolation.py` fails if that stops being true, and
pins the short list of platform modules it is allowed to reach into.
`sources.py` is the only module that may know a network exists.
"""
