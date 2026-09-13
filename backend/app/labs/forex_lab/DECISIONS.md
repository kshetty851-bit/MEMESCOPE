# forex_lab — decisions taken without asking

The brief says to make the documented default choice and keep going. Each entry
is a choice that was not fully determined by the spec, what was chosen, and why.
Corrections to my own arithmetic are at the bottom, with the working shown, as
the loop rules require.

---

## 1. The spread is charged half on each fill, not in full on both

The spec says "spread (parameter, default 0.8 pip) applied on every fill".
Grid levels are MID prices. A buy fills at mid + half-spread, a sell at
mid − half-spread, so a round trip pays exactly one full 0.8-pip spread — what
a broker actually takes when the level sits at the mid. Charging the full
spread on each of the two legs would bill 1.6 pips for one round trip, which
is not a cost that exists.

Every fill still pays, which is the sentence's plain meaning: it pays its own
half. A 25-pip take-profit on a limit fill is therefore $2.50 − $0.08 = $2.42
per micro lot, and on a stop fill $2.50 − $0.08 − $0.02 = $2.40.

## 2. Worst intra-candle ordering is resolved by simulating both

`open→low→high→close` and `open→high→low→close` are both run on cloned state
and the one that ends the candle with LOWER equity is the one that happened.
The alternative — picking an ordering per candle by a rule of thumb — cannot
be right on a hedged grid, which has positions on both sides and no fixed
"bad direction".

A candle whose range reaches no order, no take-profit and neither re-centre
boundary skips both walks; it can only move the equity mark, and that is done
directly. Over real data this is the overwhelming majority of minutes and it
is what makes 27 configurations over 2.4M candles finish.

## 3. An order fires when price ARRIVES at its level, never while sitting on it

Each leg is scanned over the half-open interval `(from, to]`. This was not the
first implementation, and changing it was the substantive bug fix of iteration
1 — see correction A.

## 4. Level N sits exactly on the re-centre boundary, and fills before it

With N levels of S pips, the outermost order and the hard stop are at the same
price. Filling the order and then closing it in the re-centre at that same
price pays two spreads for nothing, which is strictly worse for the strategy
than not filling — so that is the order events are processed in.

## 5. At one price, entries are processed before take-profits

Both are "at" the same price so the order is arbitrary in a real book. Entries
consume margin, so doing them first produces MORE rejections than doing the
take-profits first would. That is the conservative direction for a strategy
trying to demonstrate a profit.

## 6. Margin is held at the open price, summed over every position

The spec gives margin per micro lot as `1000 x price / 10` without saying
which price or how hedged positions combine. Margin is computed at the fill
price and held for the life of the position, and hedged longs and shorts are
summed, not offset. Many brokers charge only the larger side in hedging mode;
summing is the stricter reading and the spec says positions are never netted.

## 7. Market closes pay slippage as well as spread

Re-centre and stop-out close everything at once, which is the single moment a
grid is dumping many positions into a fast move. Treating those as stop fills
(spread + slippage) rather than limit fills is the honest reading of "slippage
on stop fills".

## 8. Equity marks at the closing side of the spread

A long marks at the bid, a short at the ask — so an open position shows the
half-spread it would pay to leave, exactly as a real platform's equity line
does. Margin calls therefore arrive slightly earlier than a mid-marked book
would produce them. No slippage in the mark: an equity line does not price the
urgency of an exit that has not happened.

## 9. Swap rates are derived from published policy rates

OANDA publishes no retrievable historical swap archive, so the table in
`config.py` is derived from what a swap is actually made of:

    long  = (ECB deposit facility − Fed funds effective − 0.5%) / 365 x notional
    short = (Fed funds effective − ECB deposit facility − 0.5%) / 365 x notional

with 0.5%/yr of markup on each side (the ~1%/yr round trip OANDA's EUR/USD
financing has carried) and notional = €1,000 at that year's average EUR/USD.
The ECB column is time-weighted across each year's decisions, because 2022 and
2023 moved too far for a year-end figure to mean anything. The full table,
inputs and outputs, is in `config.py`.

Every year in the window comes out negative for the long side and positive for
the short side, which is what a EUR/USD trader actually lived through: the
dollar paid more than the euro for the whole of 2020–2026.

## 10. Triple swap on Wednesday is ON, and is an addition to the spec

The spec says "swap applied at 17:00 New York daily". Charged only on the five
weekday rollovers, that is 5 nights of carry per 7 nights held — the weekend
would simply never be billed. Brokers solve this by booking three nights at
the Wednesday rollover, whose value date settles on Monday. It is ON by
default, it makes the backtest MORE expensive rather than less, and it is
listed as a deviation in REPORT.md.

The rollover is driven by the calendar, not by a candle arriving at 17:00 NY:
Friday's rollover lands on the weekly close, where the feed often has no tick
at all, and keying off candle arrival would hand the strategy a free night
every single week.

## 11. The swap table lives in Python, not in Postgres

The spec requires the engine to have no DB dependency and also calls the swap
rates a "config table". Both are satisfied by a table in `config.py`.

## 12. Ticks are what the dataset is built from — see correction E, which
##      overturns half of what this entry originally said

`EURUSD/<yyyy>/<mm>/BID_candles_min_1.bi5` — a MONTH of the feed's own
1-minute candles — would have replaced ~40,500 requests with ~156. It returns a
genuine 404 (a 162-byte body, as against the 3,464-byte body of the CDN's
*transient* 404, which is a styled error page). Eight retries on two separate
months, no success.

From which I concluded that the feed publishes no pre-aggregated candles at
all. That was wrong, and correction E says what is actually there. The dataset
is still built from ticks, because the brief asks for ticks and because an
aggregation this lab did not perform is one it cannot check — but the day-level
candle files are now used to check the one it did.

## 13. Local verification runs my migration's DDL directly, because the branch's
##     alembic chain was already broken

`alembic upgrade head` fails on `karthik-hq` with
`KeyError: '0062_early_movers_lab'` — `0063_breakout_lab` (commit 3e8239b,
not mine) parents to a revision that is not on this branch. The spec forbids
touching files outside this lab bar the new migration, so the break is left
alone. `0069_forex_lab` parents to `0068_graduation_features`, which is
the branch head, and its `upgrade()` was executed directly against a clean
database to prove the DDL runs and produces the 11 and 8 columns the models
declare.

---

# Corrections to my own arithmetic

## A. Test 1's expected fill count was 4; it is 5. The engine was right.

**What I asserted.** Down 60 pips from 1.10000 with S=25 and N=4, then back to
the centre: four fills (a buy limit and a sell stop at each of 1.09750 and
1.09500), three take-profits, one position left open.

**What actually happens.** Five fills, three take-profits, two positions left
open. The fifth fill is real and I had missed it.

**The working.** When the 1.09750 short takes profit at 1.09500, its sell stop
is re-placed at 1.09750 — that is the spec's re-placement rule. Price then
walks back up. The candle from 1.09750 to 1.09800 has, as its worst ordering,
`open → high → low → close` = 1.09750 → 1.09800 → 1.09750 → 1.09800. On the
middle leg price is FALLING from 1.09800 through 1.09750, and a sell stop at
1.09750 is exactly an order to sell when price falls through 1.09750. It
fires, opening a short at 1.09744 into a rising market.

It is also the worse of the two orderings — `open → low → high → close` leaves
it untouched — so the engine is required to choose it.

**Effect on the other expected values.** None. The new short's take-profit is
1.09500, which the path never revisits, so it stays open and unrealised:
balance is still exactly $1,007.24 from the same three take-profits
(+2.40 +2.42 +2.42), and rejections are still zero. Only `fills` (4 → 5) and
the open-position count (1 → 2) change.

## B. Correction A had a genuine bug underneath it, now fixed

Before the half-open interval of decision 3, the leg scan was inclusive at
both ends, and the same sell stop fired for a different and WRONG reason: the
candle from 1.09700 to 1.09750 ends exactly on the order's level, and the next
candle's first leg then started at 1.09750 and "found" an order it was already
sitting on. Price had never crossed the level — it arrived from below, where
a sell stop is not even a valid pending order.

Under a closed interval every turning point that lands on a grid level hands
the grid a free fill, which is a bias in the strategy's favour on a mean-
reverting instrument. The half-open interval `(from, to]` fires an order only
when a leg travels onto its level, and the gap from one candle's close to the
next candle's open is walked as a leg of its own so nothing is skipped.

## C. Test 5's two-order expectation was wrong: one cent below the boundary
##    rejects the long, not both orders

**What I asserted.** At one cent below the boundary equity, both orders at
level −1 are rejected.

**The working.** The two orders do not cost the same margin, because they do
not fill at the same price. The buy limit fills at 1.09750 + 0.00004 =
1.09754 and needs 1,000 x 1.09754 / 10 = $109.754. The sell stop fills at
1.09750 − 0.00004 − 0.00002 = 1.09744 and needs $109.744 — one cent less.

With equity $121.9389 (a cent under the long's boundary of 109.754/0.9 =
$121.9489), the cap is 0.9 x 121.9389 = $109.74501:

    long   109.754  > 109.74501  -> rejected, and used margin stays at 0
    short  109.744  < 109.74501  -> accepted

So: one rejection and one open position, not two rejections and none. The
boundary test now uses a single order, where the boundary is unambiguous, and
asserts this two-order asymmetry separately as the thing it actually is.

## D. Test 6's Wednesday fixture crossed two rollovers, not one

Starting the engine on Tuesday morning and stepping to Wednesday evening
passes the Tuesday 17:00 rollover as well as the Wednesday one, so the
position accrues 1x + 3x = 4x, which is what the engine charged. The fixture
now starts on Wednesday morning, after Tuesday's rollover, so Wednesday's is
the only one crossed and the assertion is the 3x the test is named for.

---

## 14. Gaps fill at the order's level, not at the price the market reopened at

The move from one candle's close to the next candle's open is walked as a leg
of its own — without that, every weekend's worth of crossed orders is simply
skipped. The question is what price they fill at.

**Tried and rejected: the literal reading.** A gap trades at exactly one price,
the reopen, so limits fill better than their level and stops fill worse. It
does not survive contact with the rest of the spec. A take-profit is a limit
order one step from its entry, so filling a stop at the reopen while its
take-profit sits at a level the market never traded produces a position that
opens and closes on two prices that never both existed — in the fixture that
exposed it, a short opened at 1.09394 and "took profit" at 1.09504, booking a
$1.10 loss on a trade that in reality would have cost ten cents. Filling the
take-profits at the reopen too fixes the incoherence and creates a worse
problem: limits collect the entire gap as free entry, which on a mean-reverting
instrument is a gift to the strategy rather than a cost to it.

**Kept: at its level.** The two errors point in opposite directions and cancel.
A stop filled at its level is flattered by the gap by exactly the amount a
limit filled at its level is penalised, and the grid holds equal numbers of
both. For the neutral-grid baseline, which has no stops at all, it is purely
conservative. And it makes the gap leg behave identically to the same move
walked minute by minute, which is a property a test can state in one line.

It is a real limitation, not a free choice, and it is listed in REPORT.md
rather than left in a docstring: a grid that is short volatility across a
weekend is exactly the thing a gap hurts, and this model does not charge it
for the worst of one.

## E. "Dukascopy publishes no pre-aggregated candles" was wrong. It publishes
##    them per DAY, and they now verify this lab's own aggregation.

**What I asserted** (decision 12, as originally written): the feed has no
pre-aggregated candle files, so ticks are the only path.

**What I had actually tested:** the MONTH path,
`EURUSD/2023/00/BID_candles_min_1.bi5`. That genuinely 404s. I generalised from
one path to the whole feed without testing the obvious neighbour.

**What is there:** `EURUSD/2023/00/03/BID_candles_min_1.bi5` — one file per
side per DAY — returns 200 with 12,549 bytes. Same LZMA container, 24-byte
records of `>5If` = (seconds into the day, open, close, low, high, volume),
prices in points. Note the ordering: O, C, L, H, not the O, H, L, C that every
other format in the world uses, and reading one as the other swaps high and
close on every candle while looking entirely plausible.

**What it changes.** Not the loader: the brief asks for ticks aggregated here,
and 3,390 day-files instead of 40,610 hour-files would be a different dataset
built by somebody else's arithmetic. What it changes is that somebody else's
arithmetic is now available to check mine against.

`verify_against_published` samples days at random from what is actually loaded,
downloads both sides' candle files, and compares them against the stored rows.
First real run: **12 days, 28,592 candle-sides, zero differences** at 1e-5.
The unit tests prove the aggregator agrees with my arithmetic; this proves it
agrees with the vendor's, over the same ticks, on real days.

It is also now a documented fallback. If the tick download proves unable to
finish against the feed's cumulative throttle, the day-candle path is twelve
times cheaper, decoded, and tested — and the REPORT would have to say that is
what was used.

## F. "Friday 22:00 UTC to Sunday 22:00 UTC" is only true in winter, and the
##    mistake was costing real data

**What I asserted**, in `iter_hours` and again in the gap check: the FX week
runs Sunday 22:00 UTC to Friday 22:00 UTC.

**What is true:** it runs Sunday 17:00 **New York** to Friday 17:00 New York.
New York observes daylight saving and UTC does not, so from the second Sunday
in March to the first Sunday in November that boundary is **21:00 UTC**, not
22:00.

**What it cost.** Two things, one of them expensive:

* the planner skipped Sunday 21:00–22:00 UTC through every summer — an hour of
  genuinely open market, on roughly thirty weekends a year, never requested;
* the gap check reported Friday 20:59 → Sunday 22:00 as an unexplained hole on
  every one of those weekends. Measured on 2020 alone: **34 unexplained gaps,
  of which 33 were this.** A correctly loaded dataset would have failed its own
  integrity check about two hundred times over the window.

**Fixed** by putting the rule in `market.py`, expressed in the timezone it is
actually written in, and having the planner, the gap check and the expected-
minute count all call the same predicate. An expected count computed from a
different definition of "open" than the one that decided what to download is a
check measuring its own assumptions.

2020 re-checked after the fix: **34 unexplained gaps down to 1.**

## G. The Easter heuristic was a guess, and it missed the one gap that mattered

The last remaining gap in 2020 was 10 April 20:58 → 12 April 22:00 — Good
Friday. The holiday check asked whether a gap ran Thursday-to-Monday in March
or April, which is Easter-shaped but not Easter: Good Friday 2020 opened a
**Friday-to-Sunday** gap and was missed, and in a year where Easter fell
elsewhere the same rule would have excused an ordinary outage.

Replaced with the anonymous Gregorian algorithm and an explicit window of Good
Friday, Easter Sunday and Easter Monday. Asserted against the known dates for
every year in the window, 2020 through 2026.
