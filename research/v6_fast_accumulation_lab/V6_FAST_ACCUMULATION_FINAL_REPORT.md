# V6 FAST-ACCUMULATION EDGE LAB — FINAL REPORT

`RESEARCH_ONLY`

**Result: FAIL — NO RELIABLE EDGE IDENTIFIED**
**Stopped at: STEP 1 (repository/data audit), under brief §26 STOP CONDITIONS.**
**Nothing was implemented, deployed, or modified in production.**

| | |
|---|---|
| Experiment ID | `V6_FAST_ACCUM_2026_09_12_001` |
| Git SHA | `489492a8a08d1f6d4f97e37c2ca6e29e9a33edb7` |
| Measured against | production DB (`memescope-postgres-1`), 2026-09-12 ~17:05 UTC |
| Verification | `feasibility.sql` in this directory — every number below is re-runnable |

This lab did not fail to find an edge. It failed to find **data capable of testing for
one**. The distinction matters: the hypothesis is not refuted, it is *unfalsifiable on
the current archive*. §26 requires a stop and a report rather than a number, because a
number produced from this archive would be a confident artefact of its own sampling.

---

## Executive Summary

Three of the six §26 stop conditions are triggered:

1. **Required historical data does not exist.** Bonding-curve progress — the first leg of
   the hypothesis — exists in exactly one table family (`grad_*`), which holds
   **28.3 hours** of history. The acceptance gate (§14) requires purged *weekly*
   walk-forward across multiple test weeks with every test week profitable. One day
   cannot produce one train/test week pair, let alone a rolling series.
2. **Entry-time observations cannot be reconstructed** on the longer archive. Over a full
   week, **0.47%** of the launch universe has any observation within 120 seconds of its
   on-chain launch — and the table that reaches back four weeks carries no curve
   reserves at all, so curve progress is not derivable from it at any latency.
3. **The archive contains unavoidable look-ahead / survivorship.** The 24-hour pruner
   deletes the curve series of every non-graduate, and the collector's watch-set
   eviction closes the observation window *preferentially on tokens that stopped
   accumulating*. Only **46.5%** of eligible entries resolve; the censored 53.5% are
   selected against the losing outcome, which biases any measured profit factor
   **upward**. That is the false-positive direction — the most dangerous one here.

A fourth, softer finding: **the Telegram leg is not collected anywhere on the platform.**
It is recoverable (§ "Telegram"), which makes it the one blocker that is merely unbuilt
rather than impossible.

---

## Dataset — what actually exists

Measured on prod, not dev (a dev copy runs no collectors and would misreport coverage).

### The only source of bonding-curve progress

| table | rows | window |
|---|---|---|
| `grad_tokens` | 28,047 | 2026-09-11 12:43:43Z → 2026-09-12 17:03:39Z (**28.3 h**) |
| `grad_curve_samples` | 257,936 | 2026-09-11 12:46:28Z → 2026-09-12 17:03:41Z |

Of 28,188 tokens ever watched, 1,056 reached `complete` on chain — a 3.7% graduation
base rate. 4,515 tokens are already `pruned_at`-stamped: their curve series is **gone**.

This source is otherwise well-suited to the hypothesis, which is what makes the verdict
narrow rather than sweeping:

- Admission is from `subscribeNewToken` — **every** new mint enters before its outcome
  is known, exactly the unbiased universe §3 demands.
- `POLL_INTERVAL_S = 3`, far finer than the 30/60/90/120-second snapshot grid of §4.
- `progress_pct` and `market_cap_quote` are stored per sample, so both the curve leg and
  the ">30 SOL initial mcap" leg are computable **at the decision timestamp** with no
  future information.
- `BACKTEST_CURVE_FEE_BPS = 125` — the 1.25% of §6 is already the house model.

The problem is duration and censoring, not fidelity.

### The longer archive, and why it cannot substitute

| table | rows | window | fatal gap |
|---|---|---|---|
| `discovered_tokens` | 1,138,258 | from 2026-07-27 (**6.7 weeks**) | identity + `block_time` only; no curve state |
| `token_market_snapshots` | 5,753,140 | from 2026-08-15 (**4 weeks**) | DexScreener price/liquidity; **no reserves, no curve progress** |
| `token_curve_snapshots` | 4,434 | 4 minutes on 2026-09-09 | abandoned experiment |

`token_market_snapshots` is the only multi-week price series, and it cannot express the
entry rule: there is no column from which bonding-curve progress can be derived.

### Observation latency on the longer archive

One week of launches (`created_at` in [now−8d, now−1d]), restricted to rows carrying an
on-chain `block_time`:

| | |
|---|---|
| tokens with `block_time` | 216,746 |
| with **any** market snapshot | 124,901 (57.6%) |
| with a snapshot **within 120 s of launch** | **1,024 (0.47%)** |
| median launch→first-snapshot latency | **140 s** |

The decision timestamp of the *slowest* pre-registered config (FAST-120) is 120 seconds.
The median token is not observed until after that instant has passed. And the 0.47% that
are observed in time are selected by DexScreener having indexed the pair quickly — which
correlates with immediate trading activity, i.e. **with the hypothesis variable itself**.
Running the experiment on that subset would condition the universe on a proxy for fast
accumulation and then measure fast accumulation.

---

## Eligible entries — the one encouraging number

Over the last 24 hours of unpruned curve data (23,364 tokens, 20,461 with samples), with
all three legs applied except Telegram (uncollected):

| config | curve + time | **+ mcap > 30 SOL** |
|---|---|---|
| FAST-60 (≥10%, ≤60 s) | 5,934 | **4,357** |
| FAST-90 (≥15%, ≤90 s) | 5,285 | **3,656** |
| FAST-120 (≥20%, ≤120 s) | 4,397 | **2,834** |

Signal supply is not the constraint. At §6's 5 concurrent slots and a 30-minute hold, the
book saturates at ~240 trades/day, so the §14 minimum of 100 OOS trades is comfortably
reachable *per test week* — **once the history exists**.

The elapsed clock is measured from `first_seen_at`, the recorder's receipt of the launch
message. PumpPortal sends no slot and no timestamp in any message, so receipt time is the
only clock there is. This is a genuine limitation, but it is the *correct* one for a
tradeable rule: nothing can be acted on before it is received.

---

## Why the exits cannot be simulated — the decisive finding

FAST-90 entries at least 45 minutes old (n = 3,517), asking whether the 30-minute holding
period is observable at all:

| | |
|---|---|
| entries with full 30-minute curve coverage | **558 (15.9%)** |
| median observed coverage | **5 minutes** |
| median post-entry samples | 10 |

Being fair to the data, a position may also resolve early — take-profit, stop, or
graduation — so coverage need not be complete. Counting an entry as **resolved** if it
touched +100%, touched −40%, graduated, or ran the full 30 minutes (n = 3,489 with any
post-entry path):

| outcome | count |
|---|---|
| touched +100% (TP) | 438 |
| touched −40% (SL) | 1,368 |
| graduated | 13 |
| **resolved (any of the above, or full 30 min)** | **1,623 (46.5%)** |
| **censored — window closed before resolution** | **1,866 (53.5%)** |

53.5% censoring would be survivable if it were random. It is not. The collector stops
polling for these reasons (24 h, 23,367 tokens):

| reason | share |
|---|---|
| `evicted` — watch set full, **lowest progress dropped first** | 42.4% |
| `silent` — no reserve movement for 30 min | 31.2% |
| `shutdown` | 16.7% |
| still watching | 7.6% |
| `post_migration` | 2.1% |

Both dominant mechanisms — evicting the lowest-progress token when the 500-slot set
fills, and dropping tokens whose reserves have stopped moving — remove **tokens that
stopped accumulating**. A token drifting toward the −40% stop is exactly the token that
goes quiet and gets evicted; a token running toward +100% keeps its reserves moving and
stays in the set. The censoring is correlated with the outcome, in the direction that
**deletes losers and keeps winners**.

Any profit factor computed on the resolved 46.5% is therefore biased upward by an
unquantifiable amount. Passing §14's PF ≥ 1.5 on this archive would be evidence about the
eviction policy, not about the hypothesis.

### A directional note, explicitly not a result

Among the 3,489 entries with any observable path, 438 touched +100% and 1,368 touched
−40% — a 24.3% win rate against the 28.6% breakeven that a +100%/−40% payoff requires,
before fees, on a sample already tilted toward winners. This is 24 hours of one config,
in-sample, censored, with no control and no correction. It is recorded because it points
the same way as the platform's prior nine no-edge findings, and for no stronger purpose.
It is **not** the acceptance gate and must not be cited as one.

---

## The Telegram leg

The hypothesis's third condition cannot currently be evaluated, but unlike the other two
it is buildable:

- The platform integrates **no social provider at all**. `app/radar/community.py` is a
  module whose entire function is to return `unavailable`, deliberately, so that the gap
  is visible in every score rather than silently missing.
- `grad_tokens` stores no metadata URI. The PumpPortal `create` message carries `uri`
  (104 of 121 observed messages), but the lab does not persist it.
- **However:** 99.2% of grad-lab mints (23,169 of 23,367) join to
  `discovered_tokens.metadata_uri`, which is populated for 93.6% of the 6.7-week archive.

So Telegram is recoverable by fetching each token's off-chain metadata JSON. Because
pump.fun metadata is content-addressed on IPFS, the document at a given CID *is* the
launch-time document — fetching it later is not look-ahead. This would be new collection
infrastructure (unpaid, but unbuilt), and §23 rightly forbids letting it become a hidden
dependency. It is listed here as the one blocker with a clean remedy.

---

## Leakage audit

Not run — there was nothing to audit. No features were constructed, because the archive
cannot supply the decision-timestamp observations they would be built from. The leakage
checker of §15 remains unwritten by design: writing it before the data exists would be
machinery validating an empty set.

The leakage that *was* found is upstream of any feature, in the archive itself:
retention (the 24-hour pruner) and sampling (eviction correlated with outcome). No
feature-level checker can detect or repair either, because both act before a feature is
computed.

---

## Acceptance gate (§14)

| # | condition | status |
|---|---|---|
| 1 | OOS profit factor ≥ 1.5 | **not evaluable** — no OOS period exists |
| 2 | ≥ 100 OOS trades | **not evaluable** — no OOS period exists |
| 3 | no token > 20% of OOS profit | not evaluable |
| 4 | every test week profitable | **structurally impossible** — 28.3 h of history |
| 5 | positive after fees and slippage | not evaluable |
| 6 | survives multiple-comparison correction | not evaluable |
| 7 | bootstrap CIs not outlier-driven | not evaluable |

Conditions cannot be *satisfied* by being unevaluable. Per §14 — "If ANY required
condition fails" — the gate result is:

**`NO RELIABLE EDGE IDENTIFIED`**

with the qualifier that this run was stopped at the data layer, not the edge layer. The
hypothesis has not been tested and has not been refuted.

---

## Reproduction

`feasibility.sql` was re-run end to end against prod after the report was written; every
figure reproduced. Queries 4-7 use rolling `now() - interval '24 hours'` windows, so
re-running an hour later moves them slightly — the second run returned 15.7% full-path
coverage against 15.7-15.9% here, 46.4% against 46.5%, and 42.9% evicted against 42.4%.
Drift of that size does not touch any conclusion: none of them turns on a fraction of a
percentage point.

Query 5 is deliberately split into 5a (coverage) and 5b (early resolution). Coverage must
be measured on the **unclipped** sample series — clipping the join to `entry + 30 minutes`
caps `max(ts)` at the boundary and reports that no entry was ever covered for the full
horizon, which is a property of the query rather than of the data.

---

## Limitations of this report

- Every number is a 24-hour or 7-day slice measured at one instant on one day. Launch
  rates and DexScreener indexing latency vary; a different week would move the figures,
  though not by enough to change a 0.47% or a 28-hour window.
- The eligible-entry counts apply two of three hypothesis legs. Adding Telegram would
  reduce them by an unknown factor.
- `first_seen_at` is receipt time, so the elapsed-seconds thresholds carry unmeasured
  network and queue latency.
- The 46.5% resolution rate uses curve-derived mid price (`v_quote / v_token`) with no
  fee or slippage model. It measures *observability*, not profitability.

---

## What would unblock this

Stated for the record; **not implemented**, and each item touches a live collector, which
§1 puts out of bounds for this lab.

1. **Retain pre-entry curve series.** The pruner deletes non-graduates at 24 h. The
   experiment needs the first ~35 minutes of *every* token retained — roughly 10 samples
   per token, a small fraction of what is dropped today.
2. **Hold entries for the full horizon.** A token that met an entry rule must not be
   evicted for silence or for room until its 30-minute window closes. This is the fix
   that removes the outcome-correlated censoring, and it is the load-bearing one.
3. **Persist the launch `uri`**, and resolve Telegram from it.

With all three in place, forward collection reaches the §14 gate in roughly **five to six
weeks**: ~240 slot-limited trades/day clears 100 OOS trades inside the first test week,
and four to five rolling test weeks follow.

This is a forward-collection programme, not a backtest. The honest position today is that
the question is open and the archive cannot close it.

---

## Final Decision

**`NO RELIABLE EDGE IDENTIFIED`**
