# Pump Catcher v3 — 25 October 2026

Owner approved replacement of the Pump Catcher paper strategy and pricing,
including the replay from 1 October. Karthik Lab and real-wallet policies are unchanged.

## Frozen strategy

Use the recorded paper entry time and price; do not defer an earlier signal
and reuse its earlier price. If entry is more than 55.00991761684418 seconds
after graduation (the frozen fitted split), waive only these six gates:
spaced names, unnamed-evening, small AI pools, $150k–$200k pools,
opening-buy check, and busy-big-pool check. Keep pool/name eligibility,
source quiet/fresh-entry rules, crew blocks and permanently blocked names.

For those selected signals, exit at the first observed +100% gross target,
or a 20% drawdown from the observed peak after the peak reached +50%,
or the first reading at/after ten minutes. Target/trailing triggers fill at
the next strictly distinct timestamp. The five-minute loss exit is replaced.
For other signals retain +30%, last-known five-minute net-down exit, or ten minutes,
independently priced. No rule is fitted by the application.

Start with $500 and $50 tickets. Settle only closes strictly before an entry;
reserve capital for overlapping trades. Ban a normalized name for twelve hours
following this account's own funded trade closing at a loss of at least 50%.
Skipped/unfunded trades never start or extend the ban. Each comparison account
replays its own funding/name history. Comparison sizes use the same entry/exit
signals and resize estimated execution costs; they are hypothetical, not a
separate optimization of each size's exit rule.

## Pricing and display

Read raw `grad_postgrad_samples` and `longwatch_readings` for the derived
graduation pool only, including native-only reserve readings. Use stored native
entry quotes, recorded entry fees resized to the order, estimated current pool
impact, swap/router fees and fixed priority fees. No future five-minute
calibration, 35% fallback or Redis v2 return is used. Missing executable exits
or exit depth are counted as full modeled losses after the twelve-minute
settlement window. Returns never fall below -100%.

The main headline, daily rows, trade list, start-date comparisons, floor tests,
size grid and wallet-count scenarios dispatch to this same pricing/funding
engine. The main figures stay in fixed trade dollars rather than being
revalued at today's SOL price. The daily page follows existing lab convention:
Dubai days attributed by closing time; the earlier research chat table used
buy dates, so individual daily rows can differ while the total agrees.

Calculations read the production database, keep bounded per-process price caches,
and never write positions, Redis, wallet state or environment settings. The
previous v2 pricing worker is unchanged; the revised page does not consume it.
A per-process lock prevents duplicate cold book builds. Historical execution
readings and computed size returns are cached; full raw trajectories are freed.

## Verification

- All 899 funded trades match the frozen 24 October 23:07 Dubai research ledger
  individually, within $0.00000001 per trade.
- Frozen replay: profit $1,508.809666, 57 rugs, lowest realized equity
  $459.896074. Starting $500 ends at $2,008.809666.
- Later production read-only snapshot: 900 trades, profit $1,509.19,
  balance $2,009.19, 57 rugs, lowest $459.90.
- Page-response checks: trade sum, day sum, count, single-user wallet and
  current-size/current-floor grid agree with the headline.
- 15 isolated pricing/funding unit tests, four frontend rule-book tests,
  TypeScript type check and frozen-ledger parity check.
- Timed read-only process: about 23 seconds cold, 1.32 seconds warm;
  response cache adds a sixty-second shared result per worker.

## Limits

The frozen fitted split was selected after over 4,000 new specifications plus
previous searches on the same October data. Both halves are reused historical
data, not untouched validation. There is no guaranteed profit or global optimum.
Raw reading gaps, delayed quotes, the derived pool mapping, source entry
assumptions, historical opening-buy checks and current crew aggregates remain
limitations. A quoted price/depth does not prove that a real sell would execute.
Open positions are valued at cost in lowest equity, not marked to market.
Multi-wallet scenarios estimate queue impact, not exact reserve evolution.

This is not financial advice.
