# FOMO Lab

This is a forward paper experiment on the [fomo.family Discover](https://fomo.family/discover)
24-hour trader leaderboard. It has its own tables and does not call any real
execution path.

## Rule

- One shared book starts with **$500**. Every copied buy spends **$50**; at most
  ten lots may be open. Proceeds return to the same cash book.
- The source's top 20 ranks are refreshed every 60 minutes (the free API plan allows about 1,000 calls a month). A trader without a
  valid Solana wallet cannot be followed; the board shows the actual roster.
  A new trader becomes actionable only at the time they first enter the roster.
  If the provider's roster capture becomes older than two hours, buys pause
  until a fresh roster arrives; sells of already held lots continue.
- Every two minutes each followed wallet (the current roster, plus any departed
  trader whose paper lot remains open) is read from the free public Solana RPC
  node, not Helius: its new transaction ids since a per-wallet bookmark, then
  each transaction. A swap is the wallet's own largest token balance change with
  SOL or another token moving the other way; transfers are ignored. A bookmark
  moves only when every transaction after it was read. Observations are
  processed in chain time order and deduplicated by wallet, signature and mint.
- A new buy older than five minutes is recorded but skipped. A sell of a held
  lot is still attempted after an outage; missing fresh prices leave it pending
  until a later tick. One sell closes the oldest matching $50 lot, since the
  decoded swap does not reliably give a proportion of the trader's holdings.
  A sell cannot close a lot bought later on chain.
- Buys and sells use the shared Lab liquidity impact and 0.3% per-side fee
  model against MEMESCOPE's newest non-suspect trading snapshot. A price older
  than 15 minutes is never used for a fill. A missing price records a refusal,
  never a fabricated fill.
- Current open values are marks, not confirmed sale proceeds. The board shows
  how many open marks are stale.

## Feed and activation

The [FOMO API](https://fomoapi.io/docs) is an independent, unofficial provider
for the fomo.family 24-hour leaderboard; it requires a paid or free API key.
MEMESCOPE uses its leaderboard only for selection, and verifies activity from
Solana transactions on the public node. Set `FOMO_API_KEY` and
`FEATURE_FOMO_LAB_ENABLED=true` in the shared backend environment (not
`FEATURE_LAB_ENABLED`, which would revive the retired labs), apply migration
`0121_fomo_lab` and restart workers and beat. The book starts at the first valid roster after activation. Existing
history is never opened retroactively. The flag defaults off because this
repository has no FOMO API key configured.

The worker logs and `/api/v1/labs/fomo/board` expose feed failures. A full
page of 100 new transactions is flagged as saturated: activity beyond that page cannot be
claimed as fully covered. Source-reported 24-hour P/L is shown beside each
rank but is not used to calculate MEMESCOPE paper returns.
