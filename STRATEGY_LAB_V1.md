# STRATEGY LAB V1 — BUILD AND HISTORICAL REPLAY REPORT

## ENVIRONMENT

```
ENVIRONMENT:              local  (ENVIRONMENT=local in .env)
HOST:                     Karthiks-MacBook-Air.local  (Darwin 25.5.0, arm64)
DATABASE:                 memescope @ memescope-postgres-1  (local Docker)
GIT BRANCH:               main
GIT HEAD:                 b999e3e  feat(hq): observe-only by default…
ORIGINAL PAPER WALLET:    trailing_stop_25_secured_hold6h_v3, enabled,
                          PAPER_WALLET_ENTRIES_PAUSED=true  — UNCHANGED
PAPER WALLET V2:          PAPER_V2_MODE=disabled                — UNCHANGED
REAL WALLET MODE:         disabled                              — UNCHANGED
STRATEGY LAB STATUS:      BUILT · BACKTEST run recorded · FORWARD_RESEARCH built and verified,
                          left DISABLED in production (not deployed)
```

**LOCAL, not production.** Docker is not the tell — `ENVIRONMENT=local`, the DB is
the local container, and production is a separate OVH host at 51.79.166.133
running a different commit. Both were inspected; see *Deployment*.

---

## WHAT WAS BUILT

| Area | Files |
|---|---|
| Pure exit resolver | `backend/app/strategy_lab/rules.py` |
| Execution costs | `backend/app/strategy_lab/execution.py` |
| Strategy definitions | `backend/app/strategy_lab/strategies.py` |
| Canonical opportunities | `backend/app/strategy_lab/opportunities.py` |
| Replay engine | `backend/app/strategy_lab/replay.py` |
| Metrics / ranking | `backend/app/strategy_lab/metrics.py` |
| Persistence | `backend/app/strategy_lab/repository.py`, `app/models/strategy_lab.py` |
| Read layer | `backend/app/strategy_lab/reporting.py` |
| Orchestration | `backend/app/strategy_lab/service.py`, `scheduler.py`, `state.py` |
| API (read-only) | `backend/app/strategy_lab/api.py` — 8 GET routes, no write verb |
| Migration | `backend/alembic/versions/20260822_0045_strategy_lab.py` — 7 new tables, purely additive |
| Tests | `tests/unit/test_strategy_lab_rules.py`, `tests/unit/test_strategy_lab_isolation.py`, `tests/integration/test_strategy_lab_persistence.py` — **70 tests, all passing** |
| Frontend | `/strategy-lab` route, 6 sections, nav entry, client + hooks |

---

## TWO DEFECTS FOUND AND CORRECTED

Both produced *plausible* numbers rather than crashes, which is the only kind of
bug that matters in research code. Both are visible in the first two replay runs.

### 1. The shared cost model returns negative proceeds

`app.paper.costs.side_cost` prices impact as the **first-order approximation**
`notional × (notional / usd_side)`. It is unbounded: selling $25,000 into a pool
holding $500 is charged $2,500,000, so the model claims the seller *pays* $2.47m
to close. Paper Wallet never hits this because its exits are $25–$100; Strategy
Lab hits it constantly because it holds runners.

**First replay produced a strategy equity of −$654 trillion.**

Fixed in `strategy_lab/execution.py` with the exact constant-product identity
`proceeds = g·Y/(Y+g)` — bounded, agrees with the old formula to ~$0.02 on a $25
order into a $2,000 pool, and can never return negative proceeds. Paper Wallet's
own model was **not** modified. A separate task was filed: `paper_v2/replay.py`
still calls the unbounded version and has the same exposure.

### 2. A dead pool's price print was booked as profit

Mint `AkU4pUXdHR…` collapsed to **$0 liquidity**, after which the feed kept
printing `0.4986` — a "1286x". The replay booked that as a **+$31,904 profit on
a rugged token: 88% of all P&L in the result set.**

This is §6's failure mode inverted. Two corrections:

* A non-executable settlement is capped at the **last price the position could
  actually have sold into**. A print made after depth vanished is not a price.
* An **empty pool is a measurement, not an absence**: an order against $0
  liquidity returns nothing. Treating zero like "unknown depth" handed rugged
  positions most of their notional back.

After the fix the top trade is a token that ran 5.7x while its liquidity rose
from $182k to $332k — a real, executable run. 22 of the control's 94 positions
end at exactly $0 liquidity and lose the full stake, which is what a rug is.

---

## DATASET

```
Canonical opportunity   = first ELIGIBLE radar_decision_snapshots row per mint,
                          frozen with the evidence available at that instant.
DATE RANGE:               2026-08-15 .. 2026-08-21
CANONICAL OPPORTUNITIES:  998
USABLE:                   481
EXCLUDED:                 517
  HOLD_WINDOW_NOT_YET_ELAPSED        309   (still running — not a data failure)
  NO_OBSERVATION_AT_OR_AFTER_EXPIRY  202   (feed gap, or pool migration)
  NO_FORWARD_OBSERVATIONS              6
VENUES:                   pumpswap 479, meteora 2
OBSERVATIONS:             122,354  (pool-pinned to the entry pool)
```

This is ~6x the population Paper Wallet V2's backtest used, and it is the
**same** population for every strategy.

---

## RESULTS

```
RANK STRAT        N    EQUITY     RET%    PF   EXPECT  MAXDD%   RUGLOSS  2X  5X 10X  BLOCKED$
1    S9          55    883.34   -11.67  0.44    -2.12    22.4      0.00   0   0   0         0
2    LEGACY      78    231.53   -76.85  0.72    -9.85    88.0  1,887.64   3   1   0    40,300
3    S3         126     82.73   -91.73  0.22    -7.28    95.4    855.88   1   0   0     8,875
4    S10        126     82.73   -91.73  0.22    -7.28    95.4    855.88   1   0   0     8,875
5    S5          94     64.32   -93.57  0.25    -9.95    94.6    988.08   3   0   0     9,675
6    S4         121     61.83   -93.82  0.21    -7.75    97.3    910.45   2   0   0     9,000
7    S1         180    138.06   -86.19  0.48    -4.79    93.9  1,106.87   5   1   0     7,525
8    S6          98    109.84   -89.02  0.26    -9.08    90.9  1,012.69   4   0   0     9,575
9    S2         123     63.76   -93.62  0.25    -7.61    94.0  1,028.21   3   0   0     8,950
10   S7         154    129.18   -87.08  0.48    -5.65    89.7  1,235.43   7   1   0     8,175
11   S8         134     53.85   -94.61  0.43    -7.06    99.8  1,409.11   6   1   0     8,675
12   LEGACY25   170    127.20   -87.28  0.46    -5.13    90.1  1,142.07   5   1   0     7,775
```

**Every strategy lost money. Most lost almost everything.**

```
BEST FINAL EQUITY:      S9  $883.34   (by refusing 89% of opportunities)
BEST DRAWDOWN:          S9  22.4%     (same reason)
BEST PF:                LEGACY 0.72   (no strategy exceeded 1.0)
BEST EXPECTANCY:        S9  -$2.12    (least bad; still negative)
BEST RUG PROTECTION:    S9  $0        — never entered a token that rugged
                        Of strategies that actually traded: S1 recovered
                        $976.64 of $2,100 sunk into rugs (47%)
BEST MOONSHOT CAPTURE:  LEGACY 60% at 2x (N=10) · S7 50% at 2x (N=31)

PURE HOLD-6H (S5):      $64.32, -93.57%, PF 0.25, DD 94.6%
LEGACY BASELINE:        $231.53, -76.85%, PF 0.72, DD 88.0%  ($100 entries)
LEGACY BASELINE @ $25:  $127.20, -87.28%, PF 0.46, DD 90.1%
```

### Robustness (§24) — results with trades removed

```
STRAT         NORMAL   EX-BEST1   EX-BEST3  EX-WORST1  EX-WORST3  TOP1%  TOP3%  TOP5%
S9           -116.66    -130.61    -155.42     -96.87     -65.54     15     43     64
LEGACY       -768.47  -1,559.28  -2,331.02    -668.47    -468.47     41     81     88
S3/S10       -917.27    -980.85  -1,025.17    -892.27    -842.27     25     43     56
S5           -935.68  -1,051.06  -1,158.64    -910.68    -860.68     37     72     82
S4           -938.17  -1,003.46  -1,050.54    -913.17    -863.17     27     46     58
S1           -861.94    -988.73  -1,124.14    -836.94    -786.94     16     32     42
S6           -890.16  -1,005.54  -1,113.12    -865.16    -815.16     36     70     84
S2           -936.24  -1,007.40  -1,093.09    -911.24    -861.24     23     51     61
S7           -870.82  -1,023.32  -1,181.96    -845.82    -795.82     19     39     52
S8           -946.15  -1,120.27  -1,313.90    -921.15    -871.15     24     51     63
LEGACY25     -872.80  -1,071.55  -1,265.18    -847.80    -797.80     27     53     64
```

No strategy is `OUTLIER_DEPENDENT` — none was profitable to begin with, so
removing its best trade cannot flip it. LEGACY is the most concentrated: its top
3 trades carry 81% of its gross profit.

### THE FLAG THAT MATTERS MOST

**11 of 12 strategies carry `REGIME_CONCENTRATED`.** The control's 94 positions
break down as:

```
2026-08-15   n=11   catastrophe rate   0%
2026-08-20   n=26   catastrophe rate   4%
2026-08-21   n=57   catastrophe rate  68%
```

**61% of the trades are one day, and that day rugged two thirds of its tokens.**
This result set describes 2026-08-21 at least as much as it describes any
strategy. Nothing here should be treated as a finding about strategies until it
is reproduced across more market days.

---

## THE 20 RESEARCH QUESTIONS

1. **Highest final wallet?** S9 ($883). Of strategies that traded normally,
   LEGACY ($232) then S1 ($138). All are losses.
2. **Lowest max drawdown?** S9 at 22.4% — it refused 89% of opportunities.
   Among full participants: S7 at 89.7%.
3. **Best profit factor?** LEGACY 0.72. **No strategy exceeded 1.0.**
4. **Best expectancy?** S9 −$2.12/trade. Best full participant: S1 −$4.79.
5. **Loses least to rugs?** S9 ($0, took none). S3/S10 lost the least of the
   traders at −$856, and S1 recovered the largest share (47%).
6. **Most 2x captured?** S7 (7), then S8 (6), S1 and LEGACY25 (5).
7. **Most 5x?** S1 (1 of 5 reached), S7, S8, LEGACY, LEGACY25 (1 each).
8. **Most 10x?** None captured a 10x. Two positions reached 10x on an
   executable path; no strategy monetised one.
9. **Does 25% at 1.25x help?** Yes, materially. S1 (rungs at 1.25/1.50/1.75)
   ends at $138 against S5's $64, and its 47% rug recovery is the highest of
   any strategy. Early partials are the single clearest positive signal here.
10. **Does early profit-taking destroy moonshot returns?** Partly. S1's
    moonshot efficiency at 2x is 17% against S7's 50% and LEGACY's 60%. It
    captures *more* 2x events but monetises a smaller share of each.
11. **Does principal recovery at 2x work?** No. S2 ends at $63.76, worse than
    S5's control. Only 28 of 123 positions ever reached an executable 2x, so
    the rule almost never fires and the position holds to expiry regardless.
12. **Do 50% runners beat 25% runners?** No. S3/S10 (50% runner) end at $82.73;
    S1 (25% runner) ends at $138.06. More retained exposure lost more.
13. **Does Pure HOLD-6H beat the complicated strategies?** **No** — and this is
    the most important answer. S5 ranks 5th of 12 and finishes at $64. Six
    strategies with real exit logic beat it. Doing nothing is not the answer,
    but neither is anything tested.
14. **Trailing after profit vs. a stop from entry?** Mixed. S7/S8 (activated
    trails) end at $129/$54; LEGACY (trail from entry) ends at $232 but at $100
    per entry. Size-matched, LEGACY25 ends at $127 — statistically
    indistinguishable from S7. **No support for activation being better.**
15. **Does time-decay improve capital efficiency?** No. S6 turned over faster
    (247m average hold vs 385m) but ends at $110 with a 14% win rate — the
    lowest of any strategy. It freed capital into the same losing market.
16. **Does the age ≥ 4h gate improve equity, or just refuse risk?** **It
    refuses risk.** S9 took 55 of 481 opportunities (11% capture) and still
    lost 11.7%. It avoided every rug by avoiding almost everything. On this
    dataset it is the least-bad outcome and the least informative one.
17. **How many catastrophic tokens first produced enough profit for partial
    exits?** Substantial. Of S1's 84 rugs: **36 reached 1.25x, 29 reached
    1.50x, 16 reached 2x** before collapsing. Roughly 43% of rugs paid a rung
    on the way up.
18. **Which strategy recovers the most capital before rugs?** S1 — $976.64 of
    $2,100 (47%). S3/S10 recover 29%, S4 26%, S2 21%, S7 7%. S5, S6, S8,
    LEGACY and LEGACY25 recover **0%** — they have no partial exit to fire.
19. **Are results stable by day?** **No.** See the regime flag above: 61% of
    trades fall on one day at a 68% catastrophe rate. This is the dominant
    caveat on every number in this report.
20. **Does any strategy stay superior after removing its best trade?** The
    ordering is broadly stable — S1 and S9 remain the least-bad — but the
    question is moot: none was superior in absolute terms to begin with.

---

## CLASSIFICATION

| Strategy | Verdict | Why |
|---|---|---|
| S1 V2 Ladder Runner | **NEEDS MORE DATA** | Best full-participation equity, highest rug recovery (47%), lowest outlier concentration (top-1 = 16%). Still a −86% loss. |
| S2 Principal Recovery | **FAILED** | Worse than the control; the 2x rule almost never fires. |
| S3 Early Harvest | **NEEDS MORE DATA** | Beats the control; loses to S1. |
| S4 50/50 Runner | **FAILED** | Below the control. |
| S5 Pure HOLD-6H | **FAILED (as a strategy) / ESSENTIAL (as a control)** | −93.6%. Beaten by six others, which is itself the finding. |
| S6 Time-Decay | **FAILED** | Lowest win rate of any strategy (14%). |
| S7 Profit-Protected | **NEEDS MORE DATA** | Best moonshot capture among the ten (50% at 2x), most 2x events captured. |
| S8 Wide Trailing | **FAILED** | Worst equity (−94.6%) and worst drawdown (99.8%). |
| S9 Survival-Aware | **NEEDS MORE DATA** | Best equity, but N=55 (SMALL_SAMPLE) and it wins by abstention. |
| S10 Moonshot Barbell | **NEEDS MORE DATA** | Identical to S3 by construction — the identity is a determinism check, not a result. |
| LEGACY (current wallet) | **NEEDS MORE DATA** | Best PF, but 81% of gross profit from 3 trades. |
| LEGACY25 | **FAILED** | Size-matched, the legacy rule loses its apparent edge (−87%). |

**No strategy is PROMISING on this evidence.** Every one lost money on a dataset
dominated by a single catastrophic day.

---

## RECOMMENDATION

1. **Continue collecting evidence.** This is the only defensible action. The
   result set is one week and one dominant day.
2. **Forward-test S1 and S7** when forward research is switched on — S1 for its
   rug recovery, S7 for its moonshot capture. Both need out-of-sample data.
3. **Candidate for Paper Wallet V2: none.** Nothing here earns promotion.

**STOP. Nothing has been activated and nothing has been promoted.**

---

## PERFORMANCE (§26)

Measured on the local dataset:

```
Historical replay, 12 strategies x 481 opportunities:   29.3 s end to end
  canonical load (998 rows + 122k observations):        ~19 s
  replay + persist:                                     ~10 s
Rows written:                                           1,459 positions,
                                                        1,979 fills,
                                                        4,313 refusals,
                                                        998 opportunities
DB footprint, whole subsystem:                          4.8 MB / ~8,800 rows
```

Forward research is incremental, not a re-replay: per tick it reads only
observations newer than each open position's watermark and only opportunities
newer than the wallet. At ~1,000 opportunities/day that is ~12,000 strategy
evaluations/day and roughly 12 MB/month of new rows. It adds **no** provider
call, no RPC, and no enrichment work — it reads rows Radar and the market
collector already wrote. It holds its own advisory lock and returns before
opening a connection when the mode is not `FORWARD_RESEARCH`.

---

## TESTS

```
tests/unit/test_strategy_lab_rules.py           49 passed
tests/unit/test_strategy_lab_isolation.py       11 passed
tests/integration/test_strategy_lab_persistence.py  10 passed
                                                --------------
                                                70 passed
ruff check   All checks passed
ruff format  clean
tsc --noEmit no Strategy Lab errors
```

**Regression check against the committed baseline:**

```
                        HEAD (committed)     With Strategy Lab
unit tests              7 failed, 3361 passed, 7 errors
                                             7 failed, 3623 passed, 0 errors
```

The same 7 unit tests fail at HEAD with no Strategy Lab code present. They are
pre-existing: the paper strategy-registry tests expect
`paper_track_record_tp125_sl50_v1` to be operational while the code runs
`trailing_stop_25_secured_hold6h_v3`. A further 41 integration failures in
`test_paper_wallet.py` are caused by 231 uncommitted lines in
`backend/app/paper/service.py` from concurrent work — that diff never mentions
Strategy Lab.

---

## ISOLATION — ASSERTED, NOT PROMISED

```
ORIGINAL PAPER WALLET MODIFIED:   NO
PAPER WALLET V2 MODIFIED:         NO
REAL WALLET MODIFIED:             NO
LIVE EXECUTION PATH:              NONE
SIGNER:                           NONE
```

Enforced by `tests/unit/test_strategy_lab_isolation.py`, which fails the build if:

* `LabState` gains a live member (it has exactly DISABLED / BACKTEST / FORWARD_RESEARCH),
* any module imports `app.real_wallet`, `solders`, `solana`, or a wallet service,
* any identifier names a signer, keypair, private key or transaction submission,
* any write statement names a table outside `strategy_lab_*`,
* any Strategy Lab table gains a foreign key into `paper_*` or `real_wallet_*`,
* the API router exposes any verb other than GET,
* the forward evaluator's mode guard stops preceding its work,
* the migration stops being purely additive.

And by `tests/integration/test_strategy_lab_persistence.py`, which runs the
forward evaluator against a real database and asserts every wallet table is
byte-identical afterwards. Verified live: a forward tick opened 450 simulated
positions and Paper Wallet V1 (9 wallets, 363 positions) and V2 (0 positions)
were unchanged.

---

## DEPLOYMENT — NOT DONE, AND WHY

```
PRODUCTION DEPLOYED:              NO
LIVE ROUTE:                       not published
FORWARD RESEARCH:                 INACTIVE
```

Production was inspected (`ubuntu@51.79.166.133`, `~/MEMESCOPE`, 12 containers
healthy). Deployment was **stopped before any change** because it cannot be done
without violating this brief's own isolation requirement.

**1. Production is 7 commits behind `origin/main`.**

```
production HEAD  d862a9c
origin/main      7bce752

missing:  7bce752 feat(real-wallet): the hardening unit that 0042 was always part of
          b999e3e feat(hq): observe-only by default…
          55d0858 test(hq): the RED gate…
          79b0a71 feat(hq): the room shows what it did…
          a26e083 feat(hq): the reliability trio starts reading production…
          09266d3 feat(hq): a production watch that can measure, and repair four things
          c440a48 feat(hq): the reliability desk…
```

`scripts/deploy.sh` deploys `origin/main` wholesale. Shipping Strategy Lab
therefore also ships a **Real Wallet hardening commit** and six HQ commits
including one that can *repair* production components — none of which I wrote,
validated, or was asked to deploy.

**2. Production is 4 migrations behind, and 2 of them are not mine.**

```
production alembic_version:  0041_retention_fk_idx
0045_strategy_lab requires:  0042_kill_switch_clear_audit   (Real Wallet, uncommitted)
                             0043_hq_ops_tables             (committed)
                             0044_paper_wallet_v2           (Paper Wallet V2, uncommitted)
                             0045_strategy_lab              (mine, uncommitted)
```

Deploying Strategy Lab would create **Paper Wallet V2 tables** and a **Real
Wallet kill-switch audit table** in production. The brief states the deployment
"must NOT alter … Paper Wallet V2 … Real Wallet … wallet signer". It would.

Re-pointing `0045`'s `down_revision` at `0041` to skip them was considered and
rejected: it would fork the migration graph between dev and production, which is
the exact failure that crash-looped this project before.

**3. The gate says "ONLY if all checks pass".** They do not. 48 tests fail from
the concurrent uncommitted Paper Wallet work described above. I cannot fix them
without modifying Paper Wallet, which is forbidden.

**Nothing was committed or pushed.** The working tree holds 117 files of
concurrent agent work; committing the shared files Strategy Lab touches
(`config.py`, `models/__init__.py`, `router.py`, `celery_app.py`,
`docker-compose.yml`, `nav.ts`) would sweep that work into my commit.

### What unblocks it

1. Land or revert the in-flight Paper Wallet / Real Wallet work so the suite is
   green and migrations 0042/0044 are committed.
2. Confirm you want `origin/main`'s Real Wallet + HQ commits in production —
   they go with any deploy, Strategy Lab or not.
3. Then: commit Strategy Lab, push, run `./scripts/deploy.sh` on the host, and
   set `STRATEGY_LAB_MODE=FORWARD_RESEARCH` in production `.env`.

Strategy Lab is deploy-ready on its own terms: migration additive and applied
cleanly locally, env vars in the shared compose anchor (verified reaching
`worker` and `scheduler`), page rendering at `/strategy-lab` with no console
errors and no overflow at 375/768/1280px, and the forward tick a no-op until the
mode is changed.
