# forex_lab — a hedged grid on EUR/USD, 2020-01-01 to 2026-06-30

2,416,710 one-minute bid/ask candles aggregated from Dukascopy ticks, 2020-01-01 to 2026-06-30. $1,000 paper wallet at 10x leverage, 1 micro lot an order, 0.8-pip spread, 0.2-pip slippage on stop fills, swap charged at every 17:00 New York rollover with three nights booked on Wednesday. No live trading and no paper feed: this is a replay and nothing else.

## Verdict

**FAIL** — the best configuration by profit factor is `S50_N3_M0`: step 50 pips, 3 levels each side, stop orders at x0 of the base size.

Against the gate stated in PLAN.md before the sweep ran, unadjusted:

| Gate condition | Required | Actual | |
|---|---|---|---|
| Profit factor | >= 1.3 | 1.045 | FAIL |
| Years positive | >= 4 of 6 | 3 of 6 | FAIL |
| 2022 positive | yes | $+16 | PASS |
| Max drawdown | < 25% | 18.26% | PASS |
| Largest month | <= 30% of total profit | 42.1% | FAIL |

## Every configuration

| Config | PF | Return % | Max DD % | Low water | Trades | Re-centres | Stop-outs | Rejected | Years + (of 6) | Best month share |
|---|---|---|---|---|---|---|---|---|---|---|
| `S50_N3_M0` | 1.045 | 9.73 | 18.26 | 928.62 | 1,207 | 193 | 0 | 0 | 3 of 6 | 42.1% |
| `S25_N6_M0` | 1.030 | 14.34 | 34.83 | 835.23 | 4,290 | 193 | 0 | 0 | 4 of 6 | 57.9% |
| `S25_N6_M1` | 1.028 | 18.81 | 33.32 | 767.65 | 7,661 | 193 | 0 | 241 | 3 of 6 | 76.6% |
| `S25_N6_M0.5` | 1.024 | 11.56 | 33.37 | 834.54 | 7,945 | 193 | 0 | 49 | 4 of 6 | 98.3% |
| `S50_N3_M0.5` | 1.022 | 3.22 | 16.43 | 947.18 | 2,175 | 193 | 0 | 0 | 4 of 6 | 154.0% |
| `S50_N6_M0` | 1.020 | 0.31 | 34.07 | 826.42 | 1,065 | 49 | 0 | 0 | 2 of 6 | 3313.5% |
| `S50_N3_M1` | 1.011 | -3.25 | 22.50 | 937.72 | 2,180 | 193 | 0 | 0 | 3 of 6 | — |
| `S25_N4_M0` | 0.987 | -13.11 | 39.74 | 843.05 | 4,606 | 448 | 0 | 0 | 4 of 6 | — |
| `S50_N6_M0.5` | 0.982 | -23.61 | 42.94 | 734.36 | 1,943 | 49 | 0 | 34 | 2 of 6 | — |
| `S15_N6_M1` | 0.975 | -55.23 | 79.86 | 250.98 | 14,214 | 542 | 0 | 3,905 | 2 of 6 | — |
| `S25_N4_M1` | 0.972 | -50.48 | 56.84 | 468.46 | 7,745 | 448 | 0 | 451 | 3 of 6 | — |
| `S25_N4_M0.5` | 0.969 | -41.95 | 51.06 | 561.50 | 8,179 | 448 | 0 | 46 | 4 of 6 | — |
| `S50_N4_M1` | 0.967 | -34.48 | 37.72 | 652.86 | 1,996 | 119 | 0 | 86 | 1 of 6 | — |
| `S15_N6_M0` | 0.954 | -58.09 | 78.95 | 268.23 | 9,943 | 542 | 0 | 875 | 3 of 6 | — |
| `S15_N6_M0.5` | 0.944 | -81.81 | 85.08 | 167.13 | 14,083 | 542 | 0 | 3,441 | 2 of 6 | — |
| `S25_N3_M1` | 0.944 | -70.90 | 73.99 | 277.14 | 7,435 | 830 | 0 | 1,193 | 1 of 6 | — |
| `S50_N4_M0.5` | 0.942 | -38.94 | 39.64 | 606.26 | 2,065 | 119 | 0 | 19 | 0 of 6 | — |
| `S50_N6_M1` | 0.932 | -59.07 | 70.32 | 383.84 | 1,558 | 49 | 0 | 241 | 2 of 6 | — |
| `S50_N4_M0` | 0.923 | -31.49 | 35.15 | 651.69 | 1,155 | 119 | 0 | 0 | 1 of 6 | — |
| `S25_N3_M0` | 0.921 | -54.85 | 61.65 | 417.10 | 4,956 | 830 | 0 | 0 | 2 of 6 | — |
| `S25_N3_M0.5` | 0.921 | -78.14 | 79.83 | 211.67 | 7,994 | 830 | 0 | 684 | 0 of 6 | — |
| `S15_N4_M1` | 0.904 | -89.01 | 89.08 | 109.91 | 7,958 | 1,295 | 0 | 9,291 | 0 of 6 | — |
| `S15_N4_M0.5` | 0.899 | -93.99 | 94.03 | 60.05 | 10,648 | 1,295 | 0 | 7,400 | 0 of 6 | — |
| `S15_N3_M1` | 0.896 | -89.23 | 89.35 | 107.71 | 8,825 | 2,280 | 0 | 11,178 | 0 of 6 | — |
| `S15_N3_M0.5` | 0.889 | -94.40 | 94.47 | 55.98 | 11,877 | 2,280 | 0 | 8,825 | 0 of 6 | — |
| `S15_N4_M0` | 0.878 | -88.85 | 88.91 | 111.53 | 7,145 | 1,295 | 0 | 2,980 | 0 of 6 | — |
| `S15_N3_M0` | 0.862 | -88.77 | 89.16 | 110.94 | 7,519 | 2,282 | 0 | 3,836 | 0 of 6 | — |

### Profit and loss by year, in dollars on a $1,000 wallet

| Config | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 |
|---|---|---|---|---|---|---|---|
| `S50_N3_M0` | -14 | +54 | +16 | -14 | -67 | +129 | -6 |
| `S25_N6_M0` | +65 | +86 | +5 | -90 | -111 | +202 | -13 |
| `S25_N6_M1` | +178 | +109 | +111 | -24 | -14 | -74 | -98 |
| `S25_N6_M0.5` | +124 | +72 | +36 | -49 | -62 | +46 | -53 |
| `S50_N3_M0.5` | -19 | +62 | +48 | +8 | -46 | +18 | -39 |
| `S50_N6_M0` | +175 | -52 | +252 | -18 | -120 | -174 | -60 |
| `S50_N3_M1` | -24 | +71 | +77 | +29 | -25 | -89 | -71 |
| `S25_N4_M0` | +11 | +108 | +189 | -8 | +36 | -364 | -104 |
| `S50_N6_M0.5` | +146 | -100 | +153 | -169 | -68 | -71 | -127 |
| `S15_N6_M1` | -212 | +382 | -340 | -491 | +116 | -52 | +44 |
| `S25_N4_M1` | -74 | +57 | -54 | +9 | +55 | -355 | -143 |
| `S25_N4_M0.5` | -43 | +45 | +31 | +0 | +45 | -361 | -137 |
| `S50_N4_M1` | -10 | +28 | -95 | -73 | -10 | -50 | -133 |
| `S15_N6_M0` | +16 | +201 | -500 | -375 | +109 | -87 | +56 |
| `S15_N6_M0.5` | -176 | +229 | -494 | -311 | +18 | -34 | -51 |
| `S25_N3_M1` | -168 | +26 | -160 | -240 | -39 | -89 | -39 |
| `S50_N4_M0.5` | -130 | -11 | -7 | -41 | -45 | -64 | -90 |
| `S50_N6_M1` | +203 | -221 | +92 | -277 | -59 | -275 | -53 |
| `S50_N4_M0` | -178 | -51 | +64 | -3 | -47 | -15 | -86 |
| `S25_N3_M0` | +60 | +1 | -209 | -302 | -11 | -68 | -20 |
| `S25_N3_M0.5` | -59 | -5 | -182 | -283 | -48 | -172 | -34 |
| `S15_N4_M1` | -405 | -87 | -312 | -81 | -1 | -5 | +0 |
| `S15_N4_M0.5` | -308 | -104 | -423 | -54 | -9 | -42 | +0 |
| `S15_N3_M1` | -380 | -82 | -430 | +0 | +0 | +0 | +0 |
| `S15_N3_M0.5` | -295 | -92 | -457 | -101 | +0 | +0 | +0 |
| `S15_N4_M0` | -157 | -30 | -477 | -224 | +0 | -2 | +0 |
| `S15_N3_M0` | -162 | -85 | -516 | -124 | +0 | -2 | +0 |

2026 is January to June, half a year, and is counted in nothing: the gate's denominator is the six full years 2020–2025.

"Max DD" is measured on EVERY candle, at the worse extreme of each, not on a daily close — a daily sample cannot see a trough that recovers before the day ends, and the gate this feeds is a ceiling, so measuring it low passes runs that should fail. Over this sweep the daily figure understated the fall on every configuration. "Low water" is the lowest equity the account ever showed, measured at the worse extreme of every candle rather than at a daily close. A configuration marked BLOWN passed through zero: its profit factor and its return are arithmetic about an account that had stopped existing, and no gate result for it means anything.

"Best month share" is the most profitable month as a fraction of the run's TOTAL profit, so it exceeds 100% whenever the other months lost money between them — a configuration whose whole result is one good month and a slow bleed. It is blank where there was no profit to concentrate, and the gate fails in that case too.

## Cost breakdown — `S50_N3_M0`

| Component | USD |
|---|---|
| Banked by take-profits | 3,084.84 |
| Realised on re-centres | -2,952.90 |
| Realised on stop-outs | 0.00 |
| Closed at the end of the run | -0.07 |
| Swap | -34.54 |
| **Final equity** | **1,097.33** |

Those five and the opening $1,000 add to the final equity exactly; a cost table that does not reconcile to the number printed under it is a table a reader has no reason to trust. The fourth line is the positions still open when the replay ran out of candles, closed at market so the curve ends in cash rather than on a mark.

Spread and slippage inside those figures: **108.16** paid across every fill, entries and exits both. It is not a separate line above because it is already inside each of them — every fill price in this engine is the price after the spread, so subtracting it again would bill it twice.

1,207 fills, 1,207 closed positions, 0 fills rejected by the 90% margin cap, 193 re-centres, 0 stop-outs.

## Is the winner a strategy, or the window?

The headline above is one number over one window. This is the question it cannot answer, computed from the same sweep:

| Year | Best that year | Its P&L | Rank of `S50_N3_M0` | Its P&L |
|---|---|---|---|---|
| 2020 | `S50_N6_M1` | +203 | #11 of 27 | -14 |
| 2021 | `S15_N6_M1` | +382 | #11 of 27 | +54 |
| 2022 | `S50_N6_M0` | +252 | #11 of 27 | +16 |
| 2023 | `S50_N3_M1` | +29 | #8 of 27 | -14 |
| 2024 | `S15_N6_M1` | +116 | #24 of 27 | -67 |
| 2025 | `S25_N6_M0` | +202 | #2 of 27 | +129 |
| 2026 | `S15_N6_M0` | +56 | #9 of 27 | -6 |

**6 different configurations win the 7 years**, and `S50_N3_M0` — the overall winner by profit factor — never wins one of them.

That is the signature of a parameter chosen by the window rather than by an edge. A configuration with a real advantage should be near the top most years; one that is mid-table every year and wins overall is winning by being least bad, which is a property of the sample and not of the strategy.

## Against the baselines

| | Final equity | Return |
|---|---|---|
| Best hedged grid, `S25_N6_M1` | 1,188.10 | 18.81% |
| Best neutral grid (no stop orders), `S50_N3_M0` | 1,097.33 | 9.73% |
| Buy and hold, 1 micro lot | 888.46 | -11.15% |

The hedged grid **beat** the neutral-grid baseline and **beat** buy-and-hold.

## Deviations from the brief, and what they cost

Every one of these is argued in full in DECISIONS.md; this is the list.

1. **Triple swap on Wednesday — an ADDITION, not a relaxation.** The brief says
   swap is applied daily at 17:00 New York. Charged on five weekday rollovers
   that is five nights of carry for seven nights held, and the weekend is never
   billed. Brokers book three nights at the Wednesday rollover, whose value
   date settles on Monday. It makes the backtest more expensive, not less.

2. **Swap rates are derived, not quoted.** OANDA publishes no retrievable
   historical swap archive. The table is built from what a swap is made of —
   the ECB deposit facility rate against Fed funds effective, time-weighted per
   year, less 0.5%/yr of markup each side — and the inputs and outputs are
   printed in `config.py` so the arithmetic can be checked.

3. **The spread is charged half on each fill.** "Applied on every fill", with
   grid levels at the mid, means a buy pays half above and a sell half below:
   one full 0.8-pip spread per round trip, which is what a broker takes.
   Charging the full spread on both legs would bill 1.6 pips for one round trip.

4. **A gapped order fills at its level, not at the reopen.** The conventional
   choice, and the one whose two errors cancel — see the limitation below.

5. **Margin is held at the open price and summed over hedged positions.** The
   brief gives a per-micro-lot formula without saying which price or how the
   two sides combine. Many brokers charge only the larger side in hedging mode;
   summing is the stricter reading, and the brief says positions are never
   netted.

6. **Market closes pay slippage as well as spread.** A re-centre or a stop-out
   is the one moment a grid dumps many positions into a fast move.

7. **"4 of 6 years" is measured over 2020–2025.** The window spans seven
   calendar years because 2026 is January to June. Folding a half year in as a
   seventh would loosen the gate; it is reported separately and counted in
   nothing.

8. **The migration was applied directly rather than through `alembic upgrade
   head`.** That command was already broken on this branch before this lab
   existed — `0063_breakout_lab` parents to a revision not present here — and
   the brief forbids touching files outside the lab. `0069` parents to `0068`,
   the branch head, and its DDL was executed against a clean database to prove
   it runs.

## Limitations worth stating plainly

**The gap model does not charge the worst of a weekend.** An order the market
gapped over fills at its own level, so a stop crossed by a 40-pip Sunday gap is
flattered by exactly the amount a limit crossed by the same gap is penalised.
The grid holds equal numbers of both, so the errors cancel in aggregate — and
for the neutral baseline, which has no stops, the convention is purely
conservative. But a grid is short volatility across a weekend, and this is the
one cost it is not made to pay in full.

**Six and a half years of one pair is one sample of one regime.** A grid's
headline number is famously a function of the window it ran over. The gate was
written down before the sweep ran and has not been adjusted since, which is the
only thing separating this from a search for a flattering window.

**This is a backtest.** Nothing here has traded. Fill assumptions that hold in
a replay — that a limit at a level always fills when price touches it, that
rejections are the only thing a broker ever refuses — are assumptions, not
observations.
