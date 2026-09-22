# Momentum Lab

Thirteen paper strategies on Solana tokens whose market is **older than seven
days**, each from a **$500 wallet**, on **30 bps pools only**. Paper only:
nothing in this package can reach a key, a signer or a chain.

**Run 1 (19-22 Sep 2026, fifty strategies, 23,911 closed trades) found no edge
in the momentum candle.** Replayed over its 890 entries, every take profit
from 3% to 30% and every hold from 30 minutes to 6 hours lost money. What it
found instead was mechanical, and run 2 is built on it:

| run 1 measured | run 2 does |
|---|---|
| a round trip costs 77 bps on a 30 bps venue, 185 bps on pump.fun's AMM — whose coins also fell more (gross -0.78% against raydium's +0.50%) | `MAX_FEE_BPS` refuses that venue before judging, so strategies and controls share one population |
| 1,644 stopped trades lost 7.6% each; a 3-5% take profit sells the winners | no stops anywhere, one take profit, at 15% |
| the loudest candles were the worst (over 15%: -5.4% a trade; 200+ trades in the bar: -4.4%) | the `QUIET` arms cap the move at 5% and volume at 10x |
| three things were not negative in either half of the sample: a coin down 10%+ on the day (+4.9%, n=44), a pool over $1m with a 15% take profit (+0.77%, n=107), and the red-candle snap-back (+0.10%) | `DOWN`, `DEEP` and `SNAP` test exactly those, forward |

Those three came out of the same data that suggested them. They are
hypotheses on test, not findings.

Page: `/momentum-candles` ("Momentum Lab" in the nav). API: `/api/v1/labs/momentum/*`.
Flag: `LAB_MOMENTUM_ENABLED` (default off; it is in the compose anchor).

## The universe

* **Where tokens come from:** Jupiter's `toptraded`, `toptrending` and
  `toporganicscore` lists, each at 5m / 1h / 6h / 24h (capped at 100 each,
  whatever `limit` asks), plus its whole `verified` tag list (~3,500 tokens,
  one call) — thirteen keyless calls every 30 minutes. Measured 2026-09-19:
  the lists alone gave 142 eligible tokens; with `verified`, ~540 (~510 with
  a usable pool). Most of the added ones are quiet: the 20-trade floor means
  they count only when they wake up.
* **A refresh never stalls a tick:** the lookups (`plan_universe`, up to 300
  new tokens at 100 calls a minute) run with no lock and no open transaction;
  only the write (`apply_universe`) takes the lab's lock.
* **The rule:** first pool created more than `MIN_AGE_DAYS` (7) ago —
  Jupiter's `firstPool.createdAt`, falling back to the mint's `createdAt`.
* **Dropped at the door:** stables, staked SOL, lending receipts, wrapped
  majors and tokenised stocks (by Jupiter tag), and anything under $50k of
  liquidity.
* **One pool per token, pinned for life:** the most traded DexScreener pair
  quoted in SOL/USDC/USDT with the token as its BASE. Polled by pair address
  (`/latest/dex/pairs`), so a mark can never hop pools.
* A token off every list for 48h stops being polled, unless a position is
  still open on it.

## Candles

Every 30 seconds each pool is sampled once (~15 DexScreener calls at most).
A sample is filed at its **market** moment — fetch time minus the feed's ~27s
lag — into a stored 5m candle (`mom_candles`, 3 days kept). The SQL that
aggregates 15m and 1h bars is still there, but run 2 judges 5m bars only:
run 1's 15m and 1h arms were worse than its 5m ones. Highs and lows are
**sampled**, so wicks between samples are missed; a chart's candle low sits at
or under the one a stop here uses.

A bar is judged once (`mom_closes` is the lock), only after it has closed, and
only against bars that closed before it, and only once the token has 20 bars
of its own history (~100 minutes on 5m).

**Only busy candles count:** a bar is judged only with at least 20 trades per
five minutes it spans, and the random controls draw from the same busy bars. Added 40 minutes
after launch: the median watched coin does 12 trades per 5 minutes (3 in a
quiet hour), 13 of the first 16 candles that moved 2%+ had under 10 trades,
and the first live trade was +9.5% on two buys. Positions decided before the
floor went live are `void` (shown, counted nowhere).

**The momentum candle (`BASE_60`):** green, up 2%+, 3x the token's median
5m body over the last 24 bars, on 3x normal volume (DexScreener's own 24h
volume / 288), closing in the top 40% of its range. Not "more buys than
sells": that was the first version, and it blocked every real pump of the first
hours (ANONCOIN +11.2% on 2 buys / 30 sells, BP +3.9% on 41x volume with 2 / 91)
because a trade COUNT hides trade size; `M5_BUYERS` tests it on its own.
Calibrated for RATE only, on 4,020 real 5m candles of 22 universe tokens
(GeckoTerminal, 2026-09-19): it fires on ~1% of bars.

## Fills — never on the price a decision used

* A buy decided on this tick fills on the **next tick's sample** for that
  pool, a price fetched after the decision (describing the market ~3s after
  it). A pullback entry first waits for a sample at or under its limit, then
  fills the same way.
* A stop, target or trail decided on one sample sells on the next one. A time
  exit sells on the first sample describing a moment at or past its due time.
* Costs, both legs: pool fee 30 bps (pumpswap: its market-cap tier) including
  the router, the constant-product move of the order against half the pool's
  reported liquidity, and $0.02 network fee. A buy that would move the pool
  more than 3% is refused.
* A pool that returns nothing for an hour closes at its last price as
  `no_data` — never at zero.

## The thirteen

One factor at a time from the base, on 5m candles only, each on two exits:
out after **an hour**, or **+15% or two hours**, whichever comes first.

| family | strategies | yardstick |
|---|---|---|
| controls | `RND_60` random bar at the base's measured rate, `RND_TP15` the same with the take profit, `RND_DOWN` random bar of a coin already down 10%+ on the day | — |
| base | `BASE_60`, `BASE_TP15` — the momentum candle itself | `RND_60` / `RND_TP15` |
| down | `DOWN_60`, `DOWN_TP15` — only while the coin is down 10%+ on the day | `RND_DOWN` / `DOWN_60` |
| universe | `DEEP_60`, `DEEP_TP15` — only in pools over $1m | base |
| quiet | `QUIET_60`, `QUIET_TP15` — 2-5% on 3-10x volume, nothing louder | base |
| dip | `SNAP_60`, `SNAP_6H` — buy the RED candle, an hour or six | `RND_60` / `SNAP_60` |

`RND_DOWN` is the one that matters most: `DOWN_60` has to beat a random buy
of the SAME beaten-down coins, not just a random buy.

`python -m app.labs.momentum arms` prints every rule in the words the page uses.

## The board

* Every trade is measured at $50 (`TICKET_USD`).
* **Wallets and splits:** the trades are re-walked in the order they opened
  through a $500 wallet cut into 1 x $500, 2 x $250, 5 x $100, 10 x $50
  (the headline) or 20 x $25. Run 1 showed what few tickets do: the same
  strategy ended at $229 on one ticket and $1,156 on ten, because with two
  slots it is luck which signals get funded. Read the board at 10 x $50. A wallet with no free ticket skips the signal; a
  bigger ticket pays proportionally more impact.
* **Error between hours**, not trades: trades in one hour are one market.
* **The bar is z >= 3 against the yardstick.** Thirteen comparisons at z >= 2
  pass one by luck. `verdict` says "waiting" under 30 trades.

## Run it

    python -m app.labs.momentum universe   # refresh the token list
    python -m app.labs.momentum tick       # one 30-second tick
    python -m app.labs.momentum prune      # candles > 3 days, signals > 14
    python -m app.labs.momentum arms       # print the thirteen rules

Beat (in `celery_app.py`): `momentum-lab-tick` every `LAB_MOMENTUM_TICK_S`
(30) seconds, `momentum-lab-universe` at :07/:37, `momentum-lab-prune` at :17.
Tests: `pytest app/labs/momentum/tests` (the tick test needs Postgres at
`MOMENTUM_LAB_TEST_DATABASE_URI` and skips without it).

## What this lab already knows it is up against

Established-token breakouts on 4h bars lost to random entry by 2.73pp
(Track Record V2, 2026-08-23); dormant-then-breakout was rare and flat; a stop
at 25% in this population behaved like a fee. None of those tested 5m-1h
candles with a 30-minute to 6-hour hold, which is what this lab asks. Read
the board against its controls, not against zero.
