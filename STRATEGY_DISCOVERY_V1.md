# STRATEGY DISCOVERY ENGINE V1 — REPORT

```
ENVIRONMENT:      local            (ENVIRONMENT=local)
HOST:             Karthiks-MacBook-Air.local  (Darwin 25.5.0, arm64)
DATABASE:         memescope @ memescope-postgres-1 (local Docker), alembic 0046
DATASET SOURCE:   LOCAL_BACKTEST
GIT BRANCH:       main
GIT HEAD:         b999e3e  feat(hq): observe-only by default…
STRATEGY LAB:     BACKTEST
PAPER WALLET V1:  trailing_stop_25_secured_hold6h_v3, entries paused — UNCHANGED
PAPER WALLET V2:  disabled — UNCHANGED
REAL WALLET:      disabled — UNCHANGED
```

**LOCAL, not production.** Production is a separate OVH host at 51.79.166.133 on
a different commit and a different database. Nothing in this report is
production evidence, and nothing was deployed.

---

## FINAL VERDICT

# B. MORE DATA REQUIRED

```
STRATEGIES GENERATED:      1,850
DISCOVERY SURVIVORS:         277   (top 15% of an in-sample block)
VALIDATION SURVIVORS:          0
FINAL HOLDOUT SURVIVORS:       0   (no candidate reached the holdout)
FORWARD CHAMPIONS:             0
```

Not "no strategy exists" — **this dataset cannot answer the question.** The
Radar's decision audit covers three calendar days and **one of them carries 93%
of the sample.** A 50/25/25 split of that is three slices of a single afternoon,
not three market regimes. The engine says so on its own overview screen rather
than leaving it to be inferred.

---

## THE CANONICAL LAYER HAD A DEFECT — FIXED FIRST (§1)

`liq_to_mcap` and `market_cap` were **NULL on all 1,027 canonical
opportunities**, so §4's entire liquidity/market-cap entry family was
untestable. The cause: the Radar's `market_state` block carries price,
liquidity, volume and trade counts, but no valuation.

Market cap *is* available point-in-time from `token_market_snapshots` — 100%
coverage at an average lag of **11 seconds before** the eligibility instant.
`opportunities.py` now joins it with `captured_at <= evaluated_at`, the same
strictly-point-in-time form the SEC-2 join uses. Observed distribution
afterwards: liq/mcap p10 0.040, median 0.258, p90 1.385 — so §4's 0.20 and 0.35
cuts land either side of the median and are informative rather than decorative.

---

## TWO BUGS FOUND IN THE ENGINE ITSELF

Both produced plausible leaderboards, which is the only dangerous kind.

### 1. Every penalty was inverted for a losing strategy

The score multiplied a robust return by four factors in (0, 1] — drawdown,
sample size, capture, day consistency. Multiplying a **loss** by 0.88 makes it
*less* negative, so every penalty *raised* the rank of the strategies it was
meant to punish. On a dataset where everything loses, that inverts the entire
board.

The first run ranked **`$10 entries on tokens ≥ 12h old` first out of 1,850**:
16% capture, 45 trades, −1.5% instead of −90%. Near-abstention scoring as skill
— precisely what §18 exists to prevent.

Fixed with `scoring.penalise`, which multiplies a gain and **divides** a loss, so
a penalty always moves a score down. After the fix the top of the board is
strategies with positive returns, PF above 1.0, and 19% capture.

### 2. The funnel never narrowed

`discovery_survivors` was derived from the survival verdict. The discovery block
is in-sample and judges non-strictly, so all 1,850 "survived" and the funnel
reported 1,850 → 1,850. It now records what each stage actually **kept**.

A third, smaller correction: a candidate with 4 trades and no losing trade was
reporting `PF = inf` and passing as a survivor. There is now an absolute
`EVIDENCE_FLOOR_N = 10`, below which no metric is treated as measurable, and an
undefined profit factor is stated as undefined rather than infinite.

---

## DATASET AND SPLIT

```
Canonical opportunities (matured, 6h forward coverage):   549 usable
Excluded:   292 HOLD_WINDOW_NOT_YET_ELAPSED   (still running, not a data failure)
            201 NO_OBSERVATION_AT_OR_AFTER_EXPIRY
              6 NO_FORWARD_OBSERVATIONS

Split granularity:  HOUR   (day boundaries impossible — see below)
DISCOVERY   281   2026-08-15 17:25 → 2026-08-21 15:59
VALIDATION  142   2026-08-21 16:02 → 2026-08-21 19:54
HOLDOUT     126   2026-08-21 20:00 → 2026-08-21 23:56
Walk-forward folds: 25
```

**Why hour boundaries.** The engine wanted day boundaries and could not have
them:

```
2026-08-15    12 opportunities
2026-08-16..19  — no Radar decision audit exists at all —
2026-08-20    27
2026-08-21   709
2026-08-22   264  (not yet matured)
```

Market snapshots exist for every day in that range; the *Radar decision audit*
does not. The canonical opportunity is a Radar eligibility decision, and
rebuilding an equivalent from raw snapshots would be constructing the
incompatible research universe §1 forbids.

**12h holds were dropped** (§8). Requiring 12h of forward coverage cuts the
sample from 565 to 324 *and* takes what remains disproportionately from the
earliest hours — putting a population change and the chronological split in the
same experiment. `MAX_HOLD = 6h` gates the universe for every strategy, which is
what makes §1's identical-opportunities requirement hold across the search.

---

## SEARCH SPACE

```
11 entry x 3 size x 7 profit x 8 exit  =  1,848   (+2 legacy $100 reference)
```

A **full factorial**, not a hand-picked list — §30's attribution question is
only answerable if every level appears against every other level.

| Dimension | Levels |
|---|---|
| Entry | none · age ≥2/4/6/12h · liq/mcap ≥0.20/0.35 · sell/buy ≥0.10 · reject s/b [0.10,0.35) · liquidity ≥$50k · age≥4h+liq/mcap≥0.20 |
| Size | $10 · $25 · $50 (+$100 legacy, ranked apart) |
| Profit | P0 none · P1 full ladder to 2x · P2 ladder+25% runner · P3 early harvest · P4 principal recovery · P5 50/50 · P6 barbell |
| Exit | hold 2h/4h/6h · trail 25%/35% from entry · trail 25%/35% after 1.5x · time-decay |
| Portfolio | second stage only: 2 breakers, 3 exposure caps |

### Requested but NOT testable — each checked against the data

| Feature | Why |
|---|---|
| `price_change_1h`, `price_change_5m` | NULL on all 150,013 eligible Radar decisions — provider does not supply them |
| `buys_1h` / `sells_1h` | NULL on all eligible decisions — provider supplies 24h counts only |
| All 12 wallet-flow features | **FUTURE_FEATURES_NOT_READY.** No point-in-time capture. Backfilling current wallet state into an old decision would be look-ahead of the worst kind |
| SEC-2 as an alpha variable | Only 16 of 1,027 opportunities carry an evaluation at or before their own eligibility. Structural gate, carried as evidence, never a filter |
| 12h holds | See above |
| Liquidity-aware sizing | Deferred per §6 — prior analyses were methodologically flawed |

§8's E4 and E5 are combinations already present (E4 = laddered profit × pure
hold; E5 = laddered profit × activated trail), not separate exit keys — listing
them again would double-count them in attribution.

---

## TOP 10 — WALK-FORWARD (§12's primary evidence, 25 folds pooled)

```
STRAT          N  CAP%   RET%    PF  EXPECT   DD%  WIN%  2X%  PDAY%  OUTLIER  STATUS
DISC-A0190    34   6.5   0.56  1.11    0.17   2.4    44   54     67  top3     FAILED
DISC-A0182    34   6.5   0.51  1.10    0.15   2.4    44   91     67  top3     FAILED
DISC-A0191    34   6.5   0.48  1.10    0.14   2.4    44   54     67  top3     FAILED
DISC-A0183    34   6.5   0.42  1.09    0.12   2.4    44   91     67  top3     FAILED
DISC-A0222    34   6.5   0.35  1.07    0.10   2.4    44   56     67  top3     FAILED
DISC-A0198    34   6.5   0.35  1.07    0.10   2.4    44   56     67  top3     FAILED
DISC-A0199    34   6.5   0.21  1.04    0.06   2.4    44   56     67  top3     FAILED
DISC-A0223    34   6.5   0.21  1.04    0.06   2.4    44   56     67  top3     FAILED
DISC-A0189    34   6.5   0.18  1.04    0.05   2.2    35   54     67  top3     FAILED
DISC-A0179    34   6.5   0.14  1.03    0.04   2.4    44   91     67  top3     FAILED
```

Only **13 of 277** walk-forward evaluations produced a positive return, all of
them outlier-dependent on their top three trades.

The holdout table is empty because nothing survived validation — the seal was
opened once, on an empty finalist list, and remains spent for these definitions.

---

## TOP 5 FORWARD CHAMPIONS

**None.** §26 is explicit that this is an acceptable result.

The best walk-forward candidate, measured against the champion bar:

**DISC-A0190** — *$10 entries on tokens at least 2h old. Take 25% at 1.25x, 25%
at 1.50x, 25% at 1.75x, hold 25% to the exit rule. Exit: 25% trailing stop armed
only after 1.5x; hard expiry at 6h.*

| Standard | Met | Value |
|---|:--:|---|
| OOS PF ≥ 1.20 | ✗ | 1.11 |
| positive expectancy | ✓ | $0.17 |
| positive wallet return | ✓ | +0.6% |
| max DD ≤ 40% | ✓ | 2.4% |
| capture ≥ 20% | ✗ | 6.5% |
| N ≥ 50 | ✗ | 34 |
| profitable without best trade | ✗ | −$10.79 |
| profitable across multiple days | ✗ | 3 days, 67% profitable, 79% concentration |

**3 of 8.** It is not a champion, and its 0.6% return over 34 trades at 6.5%
capture is not distinguishable from noise on this sample.

---

## REQUIRED ANSWERS

| Question | Answer |
|---|---|
| Any strategy PF > 1? | **Yes** — 13 of 277 walk-forward, best 1.11. All outlier-dependent. |
| Any PF ≥ 1.2? | **No** out-of-sample. (In-sample discovery reaches 1.88, which is what in-sample means.) |
| Any positive expectancy? | **Yes**, marginally — best $0.17/trade on 34 trades. |
| Any max DD ≤ 40%? | **Yes**, widely — but only because exposure is tiny. Best candidates deploy ~$340 of $1,000. |
| Any keeping ≥ 20% capture? | **Not among the positive ones.** The best positive candidate captures 6.5%. `E-none` captures 58% and loses 66%. |
| Any positive without its best trade? | **No.** Every positive walk-forward candidate goes negative without its top 1 *and* its top 3. |
| Any positive without top 3? | **No.** |

### Which entry features help most?

```
FAMILY        n     MEAN RET   MEDIAN     PF   CAPTURE   KEPT
age         672      -8.19%   -5.45%   0.59     17.2%   33.0%
liquidity   168     -12.14%   -9.83%   0.77     23.7%   20.2%
combo       168     -14.93%  -14.00%   0.21     14.6%   12.5%
none        170     -65.53%  -66.45%   0.44     57.6%    0.0%
liq_mcap    336     -66.21%  -68.77%   0.32     39.3%    0.0%
sell_buy    336     -72.00%  -75.60%   0.38     53.8%    0.0%
```

**Age filters dominate**, and `liquidity ≥ $50k` has the best profit factor
(0.77) at a usable 23.7% capture — the most interesting single result in the
table, because it trades meaningfully and still loses least per dollar risked.

**This is heavily confounded with capture**: age filters take 16–19% of
opportunities while `none` takes 58%. Less exposure to a losing market is less
loss. `E-liq50k` is the one that partly escapes the confound.

**liq/mcap and sell/buy filters did not help** — both worse than no filter at
all on mean return, despite the fix that made liq/mcap testable.

### Which position size helps most?

```
$10   -27.07%   |   $25   -37.67%   |   $50   -44.88%   |   $100   -48.96%
```

Monotonic. **Smaller is better**, which on a losing dataset means "risk less",
not "this size has edge".

### Which exit style helps most?

```
trail_from_entry     -30.24%   pf 0.61
trail_after_profit   -33.25%   pf 0.59
decay                -40.31%   pf 0.32
pure_hold            -41.74%   pf 0.36
```

**Trailing beats holding, and trailing from entry beats waiting for profit.**
This *contradicts* the S7/S8 hypothesis from the hand-built lab. Per exit:
`X-tr25` (25% trail from entry) is the single best exit at −28.07%, pf 0.67.

### Which profit ladder helps most?

```
P1 full ladder to 2x  -28.66%  |  P2 ladder+runner  -33.84%  |  P5 50/50  -38.06%
P3 early harvest      -38.12%  |  P6 barbell        -38.12%  |  P4 recovery -38.91%
P0 no take-profit     -40.18%
```

**Partial profit-taking helps, and taking more of it helps more.** P1 — which
sells the entire position by 2x and keeps no runner — is best; P0 is worst.
P3 and P6 are identical to the cent, which is the determinism check working
(§7 specifies the same rungs for both).

### Do portfolio breakers help?

**Not measured.** §9 places them in a second stage over validation survivors, and
there were none. The machinery is built and unit-tested — the exposure cap and
both loss breakers demonstrably reduce entries and never block an exit — but it
has nothing to be applied to.

---

## WHY EVERY ANSWER ABOVE IS WEAK

Every attribution row is dominated by one confound: **capture**. On a dataset
where the median strategy loses 25%, "less exposure" and "better strategy" are
the same column. `E-liq50k` is the only entry level that is both restrictive and
high-capture enough to partly separate the two, and one level is not a finding.

`DAY_CONCENTRATED` fires on nearly every candidate: 79% of the best walk-forward
candidate's trades fall on one UTC day.

---

## PERFORMANCE (§22)

```
Full search, 1,850 candidates x 4 blocks x 25 walk-forward folds:  7.2 s
Schedule resolutions:                                             18,060
Naive equivalent (every strategy replays the market):           ~993,000
Universe load (549 opportunities + observations):                 ~9 s
DB footprint of one persisted run:                            ~2,000 candidate
                                                              + ~4,400 result rows
```

The optimisation: a fill schedule depends on the price path and the rule only,
never on position size — every rung is a fraction of the initial quantity and
every trigger a multiple of the entry price. It is resolved once per
(opportunity × profit × exit) and reused. Costs are *not* cached, because
execution cost is quadratic in notional. `test_a_cached_schedule_matches_an_uncached_replay_exactly`
asserts the shortcut is exact rather than close.

---

## FILES, MIGRATIONS, TESTS

**New backend** — `backend/app/strategy_lab/discovery/`: `space.py`,
`splits.py`, `engine.py`, `scoring.py`, `attribution.py`, `service.py`,
`repository.py`, `api.py`. Plus `backend/app/models/strategy_lab_discovery.py`.

**Modified** — `backend/app/strategy_lab/opportunities.py` (point-in-time market
cap), `backend/app/models/__init__.py`, `backend/app/api/v1/router.py`.

**New frontend** — `frontend/src/lib/strategy-discovery.ts`,
`frontend/src/components/strategy-lab/discovery.tsx`; Discovery tab added to
`frontend/src/app/(dashboard)/strategy-lab/page.tsx`.

**Migration** — `0046_strategy_lab_discovery`: three new tables, purely
additive, `downgrade` drops only what it created. Applied locally; alembic head
is `0046_strategy_lab_discovery`.

**Tests** — `backend/tests/unit/test_strategy_discovery.py`, 39 tests. Isolation
guards extended to the subpackage (`rglob`, plus a test that fails if the glob
ever stops reaching it).

```
tests/unit/test_strategy_discovery.py            39 passed
tests/unit/test_strategy_lab_isolation.py        23 passed
tests/unit/test_strategy_lab_rules.py            43 passed
tests/integration/test_strategy_lab_persistence.py  10 passed
                                                 ---------
                                                115 passed
ruff check   All checks passed
ruff format  clean
tsc --noEmit no Strategy Lab or Discovery errors

Full unit suite:  7 failed, 3,668 passed
Baseline at HEAD: 7 failed, 3,361 passed
```

The same 7 pre-existing failures as the committed baseline (stale paper
strategy-registry expectations). **+307 passing tests, zero regressions.**

---

## ISOLATION

```
ORIGINAL PAPER WALLET MODIFIED:   NO
PAPER WALLET V2 MODIFIED:         NO
REAL WALLET MODIFIED:             NO
PRODUCTION TRADING RULES:         UNCHANGED
GEN 10 CREATED:                   NO
SEC-2 / RADAR / NURSERY:          UNCHANGED
TRACK RECORD:                     UNCHANGED
STRATEGY AUTO-PROMOTED:           NO
LIVE EXECUTION PATH:              NONE
TRANSACTIONS SUBMITTED:           0
PRODUCTION DEPLOYED:              NO
```

Enforced by tests, not convention: no source in the package (now scanned
recursively) imports `app.real_wallet`, `solders`, `solana` or a wallet service;
no identifier names a signer, keypair or transaction; no write statement names a
table outside `strategy_lab_*`; both routers expose GET only; both migrations are
purely additive and together create exactly the owned table set.

---

## RECOMMENDATION

1. **Collect more days.** The binding constraint is not the engine — it runs
   1,850 strategies in 7 seconds. It is that `radar_decision_snapshots` has
   three days of history and one of them is 93% of the sample. Roughly two
   weeks of continuous coverage would make a day-boundary 50/25/25 split real.
2. **Investigate the Radar audit gap** for 2026-08-16 → 08-19. Market snapshots
   exist across it; decisions do not. If that is recoverable, the usable history
   roughly doubles immediately.
3. **Then re-run.** The hypotheses worth carrying forward are the ones this
   search *ranked* rather than validated: small size, trailing stops from entry,
   aggressive early profit-taking (P1), and a liquidity floor around $50k.
4. **Promote nothing.** No candidate reached CHAMPION, so none earns even a
   simulated forward wallet.

**STOP.** Nothing deployed, nothing activated, nothing promoted.
