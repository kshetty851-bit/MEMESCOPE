# Pool Sprint Lab

Separate, read-only paper replay. Route `/pool-sprint-lab`; API
`GET /api/v1/labs/graduation/pool-sprint` with paginated `/trades` and `/trades.csv`.

## Fixed rules

- **SOL-only correction:** the exact recorded pool must have the candidate as
  its base mint and wrapped SOL (`So11111111111111111111111111111111111111112`)
  as its quote mint. Token symbols and the Solana chain label do not prove this.
  Verify the canonical SOL migration PDA, a decoded PumpSwap account, or exact
  pool metadata. Unknown identities are excluded and retried; verified non-SOL
  pools are excluded. Never substitute a later pool or re-enter at a later time.
  Pool mint identities are immutable; current prices/reserves are not used to
  decide historical eligibility. This correction recalculates all ledgers.

- Start **1 October 2026, 00:00 Dubai** with **$500**, **$50 per token**.
- **Fresh + 65% buys:** the original observation must be between 0 and 30
  seconds after `grad_tokens.migrated_at`. Its `txns_m5_buys` must be at least
  65% of `txns_m5_buys + txns_m5_sells`; this is transaction count, not volume.
  Refuse missing/negative counts, zero total activity and missing graduation
  times. Use integer comparison `100 * buys >= 65 * (buys + sells)`.
  Never qualify an entry from later readings. Every comparison ledger uses
  this same filter. Entry checks are included in trades and the CSV.
- **Creator block:** after an account's own funded, priced trade loses 50%
  or more, refuse all later tokens from that exact recorded creator address.
  The block is permanent within the replay. Activate only when the loss is
  observed at exit; a candle fallback cannot activate it before the seven-minute
  deadline. Previously opened trades are not cancelled. Unpriced reserves and
  unknown creators never create a block; unknown wallets are not grouped.
  Each start-date, size and cost comparison has its own funded trade history.
  The daily table and summary count creator refusals separately from cash skips;
  `/trades?status=creator_blocked` lists the refused entries and activation times.
- Admit a mint only when its **first** positive-liquidity DexScreener pool
  observation is at least $10,000 and below $40,000. A token initially observed
  above the band cannot qualify by falling into it later. A positive entry
  quote and a pool address are required. No name, crew or
  rugged-name filters from the other labs are inherited.
- Quote entry at that observation. Exit at the first positive SAME-POOL USD
  DexScreener reading from five through seven minutes after entry. If absent,
  use the first positive same-pool GeckoTerminal candle CLOSE whose minute END
  falls in that interval. The candle close is never known at its minute start.
  Do not use another pool or a peak/high. For ongoing entries, the candle
  fallback is finalised only once the seven-minute deadline has passed.
- These are recorded price-return estimates, not executable fills. Historical
  backfill delivery times, slippage, impact, failed swaps and actual fees are
  not established. All history before the strategy's creation is in sample.
- Recycle proceeds only at sale time. Multiple positions can overlap. A trade
  without enough free cash for its stake plus the scenario's cost is skipped.
- Headline is BEFORE COSTS, in fixed USD; it does not move with SOL's price.
  Cost comparison rows replay their OWN cash limit, not unlimited trades with
  a fee subtracted after the fact. Stake/pool comparisons also run independent
  $500 ledgers. Independent-account multiples assume no extra market impact.
- The header explicitly labels recorded-price paper returns and warns that
  delayed-entry research lost money. The strategy was selected after a large
  historical rule search, not independently validated on future trades.

## Missing prices and reconciliation

After seven minutes, an entry without a valid exit reserves the entire stake
as a loss for the conservative balance/daily boxes. This is not a claim that
the token actually rugged; reserve rows have no reported return and do not
increment observed rugs. Open entries before that deadline are carried at cost.
All open cash is reserved and cannot fund another trade. Lowest settled balance
is not a mark-to-market equity calculation. A late backfill may resolve an
unpriced reserve and revise the historical replay.

The page separately shows priced-trade profit and the unpriced stake reserve.
Daily accounts follow Dubai closing/settlement dates; entry costs belong to
the Dubai entry date. Figures, daily boxes, start dates, size grid, pool bands
and costs share the same ledger. Trades are paginated, with day/status/rug/cash
skip filters. CSV includes all funded entries and protects untrusted metadata
against spreadsheet formula injection. No private keys or credentials exist
in this dataset.

## Audited bootstrap and current observations

The deterministic gzip snapshot is a **private deployment artifact**, excluded
from this public repository. It is provisioned only in the API release image
at `backend/app/labs/graduation/data/pool_sprint_oct_2026.json.gz`. Do not commit
production-derived records, historical account results or real snapshot fixtures.
The bootstrap contains observations from the requested October start through a
fixed export timestamp. Its fields are mint, exact pool, entry time/price/liquidity,
metadata, exit time/price, source and candle start; the header includes schema
version (4, requiring base/quote mints, verification evidence, graduation time,
original entry buy/sell counts and recorded creator address), export cutoff
and the source export checksum. Legacy snapshots are refused. The source CSV and full
reconciliation stay private. Tests in this repository use synthetic records.

The API immediately serves the bootstrap with a visible historical timestamp
while asynchronously fetching newer entries. The page reports its last
successful data time and refresh errors. With no private bootstrap installed,
the endpoint returns 503 rather than inventing a balance. The existing production
alpha-access gate also covers these routes; this lab does not create a public
exception or bypass authentication.

`pool_sprint_book.py` contains the pure Decimal ledger. The API's only database
operations are bounded SELECTs inside an explicit REPEATABLE READ READ ONLY
transaction, rolled back after reading. SQL lives in `ENTRIES_SQL` / `EXITS_SQL`.
New-entry queries have an overlap around the last successful read and exclude
all mints with an earlier eligible observation. Unresolved entries are retried
for late prices. Finalised historical observations retain their selected source.

The cache exists only in the API process. It is replaced atomically after a
successful read and report; refresh failure retains the last good report and
marks it stale. There are no Redis writes, migrations, production-table writes,
scheduler hooks, signer imports or trading-worker changes.

## Verification and release scope

- Ledger tests cover overlapping stakes, receipt-time proceeds, cash skips,
  cost-specific funding, missing reserves versus rugs, future data, pool
  boundaries, Dubai days and synthetic profit/reserve reconciliation. The private bootstrap is also
  checked separately against the independent audit before release.
- Integration/API tests use an isolated disposable Postgres. They check first
  liquidity, same pool, minute-end timing, future/window rejection, late gaps,
  pagination, read-only routes and CSV metadata escaping.
- Frontend tests check truthful rules, separate profit/reserve figures, daily
  selection, unpriced rows and candle provenance. Existing Pump Catcher rule
  book and sidebar tests are retained.
- Production scope, if authorised: overlay only `api.py`, `pool_sprint.py`,
  `pool_sprint_book.py` and the bootstrap in the current API image; deploy the
  frontend with its new navigation item. No wallet, recorder, paper-worker,
  scheduler, database or Redis container needs replacement.

This is not financial advice.
