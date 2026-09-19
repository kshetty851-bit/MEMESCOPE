# Momentum Lab

Fifty paper strategies that buy the **momentum candle** on Solana tokens whose
market is **older than seven days**, each from a **$1,000 wallet**. Paper
only: nothing in this package can reach a key, a signer or a chain.

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
lag — into a stored 5m candle (`mom_candles`, 3 days kept). 15m and 1h bars
are aggregated from the 5m ones in SQL when they close. Highs and lows are
**sampled**, so wicks between samples are missed; a chart's candle low sits at
or under the one a stop here uses.

A bar is judged once (`mom_closes` is the lock), only after it has closed, and
only against bars that closed before it, and only once the token has 20 bars
of its own history (~100 minutes on 5m, 5 hours on 15m, 20 hours on 1h).

**Only busy candles count:** a bar is judged only with at least 20 trades per
five minutes it spans (60 on 15m, 240 on 1h); the rolling rule needs 20 in its
window, and the random controls draw from the same busy bars. Added 40 minutes
after launch: the median watched coin does 12 trades per 5 minutes (3 in a
quiet hour), 13 of the first 16 candles that moved 2%+ had under 10 trades,
and the first live trade was +9.5% on two buys. Positions decided before the
floor went live are `void` (shown, counted nowhere).

**The momentum candle (`M5_BASE`):** green, up 2%+, 3x the token's median
5m body over the last 24 bars, on 3x normal volume (DexScreener's own 24h
volume / 288), closing in the top 40% of its range, more buys than sells.
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

## The fifty

One factor at a time from the base, so each strategy answers one question:

| family | strategies | yardstick |
|---|---|---|
| controls | `R5_TIME` random bar at the base's measured rate, `R5_SAME` the base's moments with random tokens, `R5_GREEN` random green bar, `R15_TIME`, `R1H_TIME` | — |
| 5m entry | base, looser, bigger, 8%+, 6x volume, no volume, closes at high, 2x buyers, 2h breakout, first impulse, second leg, trend, counter-trend, breadth, confirm, pullback | base / `R5_TIME` |
| universe | pool $50k-250k / $250k-1M / $1M+, age 7-30d / 30-180d / 180d+ | base |
| exits | hold 15m / 1h / 4h, stop at low + 1R/2R/3R, stop at midpoint + 2R, 5% / 10% trail, +5% / +10% take-profit, first red candle, **split exit** (half at +1R, rest at +3R or breakeven) | base |
| 15m, 1h | base, breakout, stop/target or trail | own random control |
| catch | DexScreener's own last-5-minutes window up 4% / 8% on 3x volume, bought mid-move | `R5_TIME` |
| dip | buy the RED momentum candle | `R5_TIME` |

`python -m app.labs.momentum arms` prints every rule in the words the page uses.

## The board

* Every trade is measured at $100 (`TICKET_USD`).
* **Wallets and splits:** the trades are re-walked in the order they opened
  through a $1,000 wallet cut into 1 x $1,000, 2 x $500, 5 x $200, 10 x $100
  (the headline) or 20 x $50. A wallet with no free ticket skips the signal; a
  bigger ticket pays proportionally more impact.
* **Error between hours**, not trades: trades in one hour are one market.
* **The bar is z >= 3 against the yardstick.** Fifty comparisons at z >= 2
  pass one or two by luck. `verdict` says "waiting" under 30 trades.

## Run it

    python -m app.labs.momentum universe   # refresh the token list
    python -m app.labs.momentum tick       # one 30-second tick
    python -m app.labs.momentum prune      # candles > 3 days, signals > 14
    python -m app.labs.momentum arms       # print the fifty rules

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
