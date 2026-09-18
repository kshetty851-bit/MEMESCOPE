# Tape Lab — pump.fun graduations, rebuilt from the chain

Built 2026-09-18 on the Helius Developer plan (one month paid). Every earlier
graduation study on this platform priced trades off DexScreener snapshots and
never saw a wallet; the BASE book's +$187 paper profit was -$3 on-chain. This lab
reads the chain itself and keeps what it read, so the data outlives the plan.

```
python -m app.labs.tape harvest --from 2026-09-01 --to 2026-09-18   # resumable
python -m app.labs.tape status
python -m app.labs.tape study
```

Needs `HELIUS_API_KEY` (settings reads it from the environment or `./.env`).
Data goes to `$TAPE_DB` (default `~/memescope-tape/tape.db`), never the repo.
No tables, beat entries or pages in the platform: it touches nothing that runs.

## What the harvest reads (chain.py)

| pass | read | cost |
|---|---|---|
| graduations | every successful migration, off pump.fun's migration authority `39azUYFW…` | ~0.1 credit each |
| screen | the pool at 5s, 15s, 45s after it opened | 30 credits a coin |
| tape | coins ≥ 250 SOL deep at any of those: every transaction from the coin's creation to 45s after the pool opened — curve trades, swaps, every wallet balance | ~50-300 |
| points | the pool at every exit a backtest may use (entry + 1, 2, 3, 4, 5, 10 min) | 180 |
| funders | who first paid SOL into the creator and the top 3 holders at 15s | ~10-20 a wallet |
| watch | each ≥ 1% wallet's first move of the coin during the 4-min hold (Helius `tokenTransfer` filter), and the pool 2s / 5s after it | ~30-60 |

Measured 2026-09-18: 1 hour of graduations = ~3,100 credits and 10 seconds; a
full day ~94k credits. Listing matched production's PumpPortal migration feed
78/78 for the hour checked. The two pricing paths (tape vs point reads) agreed
at every entry second checked (0 mismatches).

## What a graduation looks like on-chain (first harvested hour)

The creator buys the entire curve in the launch second (79.31% of supply), the
pool opens, and a second wallet immediately buys 15-19% of supply out of it,
paying hundreds to ~1,400 SOL. The pool is left holding ~1-4% of the tokens and
all that SOL: "$300k of liquidity", owned by the operator who can take it back
by selling. The same pool-buyer wallet appeared in three coins in one hour, and
one funder paid both the creator and the pool buyer of another.

## Pre-registered hypotheses (fixed before the study was run)

Base trade for every filter test: buy 0.2 SOL (~$20) **15 seconds** after the
pool opened, into pools holding **≥ 375 SOL** (BASE's $75k floor at ~$100 SOL),
sell **4 minutes** later. Priced off the pool's vaults + virtual quote, the
pool's fee tier by market cap, Jupiter's 10 bps and 0.00001 SOL network fee per leg.

**The fill model reproduces the real wallet.** Checked against all 111 of its
on-chain round trips (17-18 Sep): the fee tier matched the pool's own swap event
111/111 on both legs; buys got exactly the tokens the model says (actual/model
1.00000 from p10 to p90, 40 checked); sells matched the constant product with the
virtual quote to 0.00002%, less Jupiter's 10 bps. The network fee was first set
at 0.0001 SOL and cut to 0.00001 (the wallet's median ~8.5k lamports) — logged in
`~/memescope-tape/PREREGISTRATION.txt`, before any result was read.

"Operator" = the coin's creator, every wallet that held ≥ 1% of supply from the
pool's opening to the entry, and whoever funded each of them. A coin is a rug
when its pool price 5 min after a 15s entry is ≤ -50%; that label counts
against an operator only from the moment it was known.

| id | keep the trade when | why it is here |
|---|---|---|
| H1a | no coin of the same operator rugged in the last 3h | the live money-source block (+$127 on 485 trades, 3.5 days) |
| H1b | the operator never rugged before | the permanent version |
| H1c | the operator's earlier coins rugged < 50% (or fewer than 2 known) | rate, not any-rug |
| H1d | the operator has ≥ 2 earlier coins and none rugged | whitelist of proven operators |
| H2 | (paired, same coins) buy at 5s / 15s vs 45s | the scanner's own question: does reading the chain instead of waiting ~45s for DexScreener pay? |
| H3 | no operator wallet has moved ≥ 1% of its bag before the entry | rugs come from bags already held at the buy |
| H4 | retail buyers before entry (count), threshold picked on TRAIN | organic demand |
| H4b | retail SOL in before entry, threshold picked on TRAIN | same, by size |
| H5 | the curve lived > 60s (natural, not an instant graduation) | different population |
| H6 | top bag / pool token reserve, threshold picked on TRAIN | "loaded gun" |
| H7 | no group of ≥ 2 near-identical bags (≥ 0.5% each) | the bundle rugs |
| H8 | pool opened 18:00-05:59 UTC | the running A/B's hour rule, checked on history (the A/B itself is judged 10 Oct, untouched) |
| H9 | depth 580-990 SOL ($116k-$198k) | the liquidity band |
| H10 | the pool's fee tier at entry ≤ 50 bps (market cap ≥ ~59k SOL) | the toll is 0.8%-2.5% a round trip by tier, and known at entry (added 16:4x UTC, before any result) |
| H11 | depth ≥ 990 SOL (B3's $198k floor) | the live B3 arms, gated like the rest (same amendment) |

## The gate (TEST days only, every term must hold)

* TRAIN = the first 60% of days, TEST = the rest. TRAIN picks the H4/H4b/H6
  thresholds; TEST is read once.
* ≥ 150 trades; mean net return > 0; still positive without the best trade and
  without the best day; ≥ 60% of days positive.
* **Beats chance:** the filter's kept trades beat ≥ 1 - α of 2,000 random
  subsets of the same size from its own population, α = 0.05 / 14 (Bonferroni over
  the 14 filters). A filter that sheds trades at random scores ~0.5.

**H12 — sell when the operator moves** (added before any result, same day).
Every wallet holding ≥ 1% at the 15s entry is watched through the hold; the
first transaction that leaves one of them under 99% of its bag triggers a sale
2 seconds later (a websocket sees it in ~1s, the sale lands in ~1-2s; 5s is
reported too). Passes if, on the TEST days, the base gate's money terms hold
(≥ 150 trades, mean > 0, positive without the best trade and the best day,
≥ 60% of days up) AND it beats the plain 4-minute exit on the same coins by a
paired t > 3. This is the one idea aimed at the tail the stops never caught:
a rug is operators selling, and on-chain their first sale can be seen.

H2 (entry speed) is not a filter: it passes if buying at 15s beats buying the
same coins at 45s by a paired t > 3 on the TEST days.

Nothing passing means no edge at this cost. Priors: ten earlier graduation and
memecoin studies here found none (see the MEMESCOPE memory index); the
population loses on average and its losses are gaps no stop catches. A pass is a
reason to paper-trade the rule forward, not to fund it.

## Not tested, and what would be needed

* Pre-graduation (curve) entries: 85% of graduations are bought out in the
  launch second, so there is no curve to trade.

## Results — run once, 2026-09-18 18:11 UTC

Harvest: Sep 1-18, 5,716 tradeable graduations (every one of 18 days, 0
failures), 1.72M credits + 0.23M for the operator watch. TRAIN Sep 1-10, TEST
Sep 11-18. Raw output: `~/memescope-tape/study-result.json`.

Base trade (15s entry, ≥ 375 SOL, 4-min hold, $20): TRAIN -0.53%/trade
(-$297), TEST -0.45% (-$172). 94% of trades win, and the 3% that are rugs
take all of it.

| rule | TEST trades | mean | $ at $20 | minus best day | days up | beats random | gate |
|---|---|---|---|---|---|---|---|
| base | 1,893 | -0.45% | -$172 | -$217 | 3/8 | – | – |
| H1a no operator rug in 3h (the live block) | 1,748 | +0.46% | +$162 | +$108 | 6/8 | p 0.0005 | **pass** |
| H1b operator never rugged | 1,094 | +0.70% | +$153 | +$86 | 5/8 | p 0.0005 | **pass** |
| **H1d proven operator (≥ 2 earlier coins, none rugged)** | **769** | **+1.24%** | **+$191** | **+$134** | **7/8** | **p 0.0005** | **pass** |
| H3, H4, H4b, H5, H6, H7, H8, H9, H10, H11, H1c | | | | | | | fail |

H2, entry speed: the same coins bought at 15s instead of 45s gain +0.59% a
trade (TEST paired t = 3.17; TRAIN +0.57%, t = 3.73) — **pass**. 5s gains more.
H12, selling when an operator moves: **fail**. It halves rugs (1.85% vs 3.28%)
but operators move early and often, so it sells the drift away (win rate 94% ->
61%); paired t = -2.1.

**H1d audit (post-hoc, does not change the verdict):** positive in all 18
cells of entry 5/15/45s x hold 3/4/5 min x TRAIN/TEST (+0.08% to +1.55%);
+1.24% / +1.24% / +1.25% with a prior rug counted 0 / 2 / 10 minutes late; +1.17%
buying 5s later; 84 operator clusters, the most frequent wallet in 10% of trades
and +1.09% without it; max drawdown -$57 on each half against the base's
-$330/-$390; at most 4-6 positions open at once. It still takes rugs (0.91%
of trades; worst -99.9%): the edge holds only while that rate stays low.

What it means: the loss in graduations is operators who rug, and on-chain an
operator is recognisable by its wallets and the money behind them. Coins from
operators with a clean record behave; coins from new or dirty ones carry the
rugs. A backtest over 18 days of one regime — the next step is a forward paper
book, not money.
