# V6 FORWARD STRATEGY LAB — TOURNAMENT PROTOCOL v1.0.0 (FROZEN)
**Frozen before any V6 outcome was scored. Research simulation only — the Lab never creates a
Paper, Karthik or real-wallet position, and the real wallet stays DISABLED.**

Spec registry: `V6_FINAL_20_STRATEGIES v1.0.0`, transcribed into `backend/app/lab/spec.py`.
**SHA-256 `672dffdb91a4c1a295ed2d6f4d95e0fa081bf34dea5b6ef11cbf6071558521e0`.**
Every strategy row carries this hash; a tick whose registry no longer hashes to it halts
rather than scoring tokens against drifted rules.

## 0. Contamination disclosure (read first)

The historical dataset 2026-07-29 → 2026-08-25 has been mined **seven times** (V1, V2,
Strategy Lab, V3, V4, V5, V6). `NO GENUINELY UNTOUCHED HISTORICAL OOS REMAINS.` The only
unseen data is forward of `valid_from`. Tokens whose checkpoint precedes `valid_from` are
never scored, and the instant is stamped once at activation and can never move — including
the 24-hour boundary derived from it, which is therefore never extended for downtime.

Historical figures shown beside a strategy are context, never validation, and are never
added to forward results.

## 1. Population and checkpoints

One authoritative scanner. The admission stream is `radar_tokens`; the market history is
the common `token_market_snapshots` series. For each (token, checkpoint) the observation is
built **once** and handed to every strategy acting at that checkpoint. Twenty strategies,
never twenty scanners.

Checkpoints, from the registry: **0 minutes (admission), 30 minutes, 60 minutes** after
`radar_tokens.first_detected_at`. A strategy sees only rows with
`captured_at <= checkpoint_at`.

## 2. The twenty strategies

Frozen in `spec.py` and reproduced in §19 of `V6_STRATEGY_DESIGN.md`. Two are controls
(V6-01 cash, V6-02 random), one is a production replica (V6-03), one is a deliberate
refutation test of trailing stops (V6-14). Eighteen of the twenty lose money historically
and are included because they discriminate between competing explanations, not because they
are expected to win.

**No strategy is redesigned, retuned or replaced during the run.** Ideas arising from
results are recorded as `V7 HYPOTHESES` and are not activated.

## 3. Sizing and portfolio

$1,000.00 each · per-strategy position size, max concurrent and max exposure as frozen ·
one position per mint **per strategy** ever · no leverage, no borrowing, no martingale, no
averaging down, no size escalation. Capital is modelled **sequentially**: a position ties up
its size until its own frozen exit fires. The same token may be bought independently by
several strategies; that is expected and is not a shared position.

## 4. Execution model (identical for all twenty)

30 bps per side · exact constant-product impact against `(liquidity/2) ÷ 12`, calibrated on
320 live Jupiter quotes · a real Jupiter quote is preferred where one exists · fill-drift cap
`≤ trigger × 1.15` on level exits · 10-minute rolling-median glitch band ×3, symmetric, and
an off-band print never fills in either direction · 15-minute stale guard · ingest-suspect
rows excluded · provider `trading_status = inactive` settles at **$0.00**, never at the last
healthy print · `radar_tokens.peak_multiple` is never executable truth.

No strategy may receive better fills than another.

## 5. Route truth

`BUY_OK` / `BUY_FAILED` / `SELL_OK` / `SELL_FAILED` / `ROUTE_UNKNOWN` are recorded per
decision and per position. **UNKNOWN is not PASS.** A missing quote makes V6-20 skip, never
enter on an optimistic chart fill. A chart 2× is never an executable 2× when no sale was
possible.

## 6. Wallet flow keying

`wallet_flow_snapshots` is keyed by **pool address**, not mint. The Lab resolves
mint → active pool from the token's own snapshots and reads flow for that pool only; an
unrelated pool is never joined, and the resolved key and its `key_kind` are persisted on the
decision. V6-12 additionally requires `w1h_quality == "exact"`; a `capped` window **skips**.

## 7. Exit policy

Each strategy's exits are frozen individually. Order of evaluation is fixed and losses
precede gains, so on a single mark the position never gets the benefit of the doubt: dead
pool → liquidity floor → liquidity decay → sell-route loss → break-even → trailing → partial
→ take profit / runner → stagnation → time exit.

**V6 contains no conventional stop losses.** Historically a −25% stop filled at a median of
$0.03 against a nominal $7.50, so the family is omitted deliberately rather than by oversight.

## 8. Accounting

`EQUITY = CASH + EXECUTABLE OPEN VALUE`. Deployed cost is displayed beside it and is never
counted as value. A dead position marks at $0.00, never at a stale healthy print.

## 9. Circuit breaker

A strategy whose equity falls below **$800.00** stops opening new positions and is flagged
`FAILED — DRAWDOWN`. Its open positions still run to their own frozen exits. **A failed
strategy is never reset, replaced or re-optimised.** Its record is preserved.

## 10. Decision ledger

Every token that reaches a strategy's checkpoint produces one row for that strategy —
**including skips, with the reason** — written once and never rewritten after the outcome
arrives. What a strategy refused to buy is evidence exactly as much as what it bought. Each
row records the common snapshot ids the features came from, so any decision can be replayed
against the rows that produced it.

## 11. The 24-hour snapshot

At `valid_from + 24h` an immutable `24H` leaderboard is written. Open positions are **marked
at their executable value at the boundary and are NOT force-closed** — this rule is frozen
here, before launch. They continue normally in the ongoing tournament. The snapshot is
idempotent by unique constraint on (tournament, label): a restart cannot produce a second,
different 24-hour leaderboard, and a boundary crossed during downtime is still captured on
the next tick at its frozen instant.

**24 hours is a snapshot, not the end of the experiment.** The tournament continues
unchanged afterwards, automatically.

## 12. Continuation checkpoints

Further immutable snapshots at **48H, 72H, 7D, 14D, 21D**. Sample-size language on every
report: 25 `EXTREMELY LOW CONFIDENCE` · 50 `EARLY` · 100 `PRELIMINARY` · 200 `INTERMEDIATE`
· 500 `SUBSTANTIAL FORWARD SAMPLE`. Below 25 closed trades a leader is reported as
**OBSERVED PROFIT**, never as **EVIDENCE OF EDGE**.

V6 research predicts most strategies will close fewer than 25 trades in 24 hours. The
24-hour result is therefore **EARLY / SMOKE-TEST EVIDENCE**.

## 13. The three leaders

`PROFIT LEADER` (highest executable equity) · `RISK-ADJUSTED LEADER` (return per unit of
drawdown and profit factor, requiring a minimum closed sample, discounted when more than 80%
of profit comes from the top three trades) · `EXECUTABLE 2× LEADER` (highest genuine
executable 2× capture with its sample stated). Independent by construction; no strategy is
forced to win all three. **Cash is allowed to win.**

## 14. Promotion

Being first in the Lab promotes nothing. No strategy is promoted to the official Paper
Wallet or to any real-money consideration by this protocol. After the 24-hour snapshot the
leader is classified `PROMISING` / `NOT PROMISING` / `INSUFFICIENT SAMPLE` and the
tournament continues. A separate, explicit authorisation would be required for any promotion.

## 15. Immutability

Changing any feature, threshold, checkpoint, exit or sizing creates a **new version whose
record starts at zero**. Results from different versions are never merged. The registry hash
is checked on every tick.
