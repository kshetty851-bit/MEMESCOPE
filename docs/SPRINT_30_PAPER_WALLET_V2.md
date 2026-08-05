# Sprint 30 — Paper Wallet V2 (fresh launch)

Implementation report. Every figure below was measured against the running
platform on 2026-08-05; nothing is projected and nothing is rounded in the
platform's favour.

---

## 1. What launched

| | |
|---|---|
| Wallet version | **generation 2** (`trailing_stop_25_v1`) |
| Strategy | **Trailing Stop 25%**, version `1.0.0` |
| Wallet start timestamp | `2026-08-05T06:34:19.840157Z` |
| Benchmark start timestamp | `2026-08-05T06:34:19.840157Z` — the same instant, by construction |
| Starting capital | $1,000.00 |
| Archived wallet ID | `accb18fc-022b-43e4-9390-e9ce406ab879` (`equal_weight_v1`, generation 1) |
| Archived trade count | **13** — 7 closed, 6 still open and now permanently frozen |
| Archived at | `2026-08-05T05:48:05.951694Z` |

The benchmark start is not "also today" — it is the *same column*. Both
comparisons read `paper_wallets.started_at`, so there is no way for them to
drift onto a different period than the wallet they are measuring.

## 2. State at the time of writing

Measured through `GET /api/v1/paper` roughly nine minutes after launch.

| | |
|---|---|
| Cash | $0.00 |
| Invested capital | $1,000.00 |
| Equity | $1,110.03 |
| Portfolio return | +11.00% |
| Open positions | 10 |
| Closed positions | 0 |
| Trades in the permanent record | 0 |
| First purchased token | **GOAP** (`kpmhzGSYni1ta6Crc1xRDne2g7NTuEmmNJpDxwvpump`) at $0.004034, Radar rank 1 |

The first pass considered **115 Radar tokens**, opened **10**, and refused the
other **105 for insufficient cash** — no token was refused for eligibility, so
the constraint on this launch was capital and not quality.

**+11.00% nine minutes in is real market movement, not an artefact.** Two
holdings moved hard immediately after entry (BNANA +43%, eelonmusk +37% against
their entry prices); the rest sit within a few percent. Nothing has closed, so
the entire figure is marked-to-market and unrealised. Win rate, drawdown,
average hold, average winner and average loser all read `—` rather than 0,
because no closed trade exists to compute them from.

### Benchmarks, over the same nine minutes

| Benchmark | Return | Held | Difference vs wallet |
|---|---|---|---|
| Buy every Radar token | −1.78% | 10 | +12.78 pts |
| Equal weight Radar | +0.92% | 115 | +10.08 pts |
| Hold SOL | unavailable | — | published reason, no number |

Nine minutes is not a result. These figures are reported because the brief asked
for measured values, not because they mean anything yet — a difference drawn
over nine minutes of memecoin prices is noise, and it should be read as evidence
that the plumbing works rather than that the strategy does.

## 3. What was built

### Reset and archive

`paper_wallets` gained `generation`, `started_at`, `archived_at` and
`archive_reason`. The old one-wallet-per-strategy constraint became
`(strategy_id, generation)`, and a new partial unique index on a constant —
`uq_paper_wallets_live`, `WHERE archived_at IS NULL` — makes **exactly one live
wallet** a fact the database enforces rather than a promise the application
makes. Migration `0013_paper_wallet_v2` archives every wallet that existed; that
step is what makes the new index satisfiable, which is why it belongs in the
migration rather than in a script.

Nothing was deleted. The archived wallet's 13 positions are byte-identical to
what they were, and `GET /api/v1/paper/archive` serves them for internal
comparison only — it is not linked from the product.

**Its six open positions will never settle**, and the archive says so on every
response. Closing them would be an exit no published rule chose; marking them to
a later price would let a retired result keep moving. Both are worse than
stating it.

### The strategy

`TrailingStopStrategy`, published as one rule with three explicit absences:

- Entry: the **highest-ranked eligible token on the whole Radar**, not a top-ten
  cut. §4 states the loop as "exit → cash → immediately buy the next
  highest-ranked eligible token, repeat forever", and a rule that only ever
  looked at ten rows would go permanently idle once those ten had each been
  traded once.
- Size: $100 equal weight, unchanged and unweighted.
- Exit: 25% back from the highest price observed while the position was open.
  **No take profit, no fixed stop, no holding period** — those are `NULL` on the
  position row, not zeroes, so a reader can tell "no such rule" from "a rule set
  to zero".

The registry now refuses to construct with more than one operational strategy,
so the removal of the selector is enforced at import rather than by convention.
`equal_weight_v1` remains registered but retired, because its archived wallet
still has to be able to name the rules that produced its trades.

### Continuous operation

The wallet advances on its own five-minute beat **and** on every Radar refresh:
`radar_sweep` and `pumpfun_radar_scan` both enqueue a pass when they finish.
Verified live — a manual sweep at 06:42:47 logged `paper_review_requested
trigger=radar_sweep` and the worker ran the pass 0.1s later.

The trigger is not a second evaluator. It runs the same `review`, and running it
more often changes only *when a decision is recorded*: exits resolve against the
stored observation series, so the trade that comes out is the same one whatever
the schedule did. `test_evaluating_late_gives_the_same_trade_as_evaluating_often`
asserts this against a real database.

### Entry conditions

`app/paper/eligibility.py` holds §5's conditions as one pure function with one
reason code per condition. It is called by both the evaluator and the wallet
read, which is the point: "no qualified token" on the page and "opened 0" in the
log can never come from different rules.

New this sprint: **liquidity is now an entry gate**. It earns its place twice —
a bonding-curve pair reports no depth at all (ADR 0002), and a trade whose
execution cost cannot be computed cannot be audited.

### The permanent record

`paper_trade_audit`, one row per completed trade, written once. It records mint,
symbol, both timestamps, both prices, both market caps, both pool depths, gross
and net return, fee, price impact, exit reason, strategy id and version, and the
wallet generation.

**There is exactly one statement in the codebase that writes it, and it is an
INSERT** with `ON CONFLICT DO NOTHING`. No UPDATE and no DELETE exists against
that table, so "nothing may ever be overwritten" is a property of the code
rather than a policy someone has to remember.

The obvious objection is that this duplicates what the positions table already
implies. It does not: the market cap and pool depth come from
`token_market_snapshots`, which is pruned. A figure that is only *derivable* is
only derivable while its rows survive — and the oldest trades, the ones a track
record is actually judged on, would be the first to go dark.

The cost model is unchanged (Sprint 27): published swap fee per side plus exact
constant-product impact against the depth observed at each end, with slippage
from competing flow, priority fees and MEV still refused and still disclosed.

## 4. Validation

Everything below was run against the running stack on 2026-08-05.

| Check | Result |
|---|---|
| `ruff check .` | All checks passed |
| `ruff format --check .` | Passed (see note) |
| `mypy app` | Success: no issues found in 207 source files |
| `alembic check` | No new upgrade operations detected |
| Migration up/down/up round trip | Clean |
| Backend `pytest` | **3,457 passed, 28 skipped** (+88 on the sprint's baseline of 3,369) |
| Frontend `vitest` | **374 passed** (+69 on the baseline of 305) |
| `tsc --noEmit` | Clean |
| `eslint src --max-warnings=0` | Clean (exit 0) |
| `next build` | Succeeded, 10 routes |
| Live application | Verified — see §2 and §5 |

**Note on `ruff format`.** It was failing on 23 committed files before this
sprint started — pre-existing drift that SESSION.md recorded as needing a
format commit of its own. Since the brief requires every validation to pass
before committing, that repo-wide format was run and committed **separately**,
ahead of the sprint commit. It is mechanical, changes no behaviour, and the full
suite was re-run after it.

## 5. Live verification

- `GET /api/v1/paper` — wallet v2, $1,000 start, 10 open, both benchmarks
  measured from `started_at`, `hold_sol` unavailable with its reason.
- `GET /api/v1/paper/positions` — 10 rows carrying `trailing_drawdown` and a
  live `trailing_stop_price` derived from each running high.
- `GET /api/v1/paper/audit` — enabled, total 0, disclosure served.
- `GET /api/v1/paper/archive` — one archived wallet, 6 open / 7 closed, frozen
  note present.
- `/wallet` in the browser — full dashboard renders: equity, return, cash,
  invested, win rate, drawdown, average hold, average and largest winner/loser,
  current strategy, last trade, next Radar evaluation, both benchmarks, the
  published rule card, the ten open positions and the empty permanent record.
  No strategy selector anywhere.
- Beat + Radar trigger both observed firing in the worker log.

## 6. What is not yet demonstrated live

Stated rather than implied.

- **No trade has closed**, so the audit-writing path and every realised metric
  are proven by tests only, not by live data. The first trailing-stop exit is
  the real test.
- **The empty state** (`"Waiting for the next qualified Radar opportunity."`)
  has not fired live either, because the wallet deployed its full $1,000 on its
  first pass. It is asserted by integration test.
- **Nine minutes is not a track record.** Every figure in §2 is provisional and
  most of it is unrealised.

## 7. Corrections and decisions recorded

- **The generation number is global, not per strategy.** The first
  implementation numbered generations within a strategy id, which made the
  Sprint 30 relaunch "v1" because its rule was new — the opposite of what the
  number is for. Caught on the first live pass, fixed, and the ten positions
  that first pass had opened were deleted and re-opened under the corrected
  numbering. No audit row and no published figure existed at that point.

- **Exit rules are read off the position's own row, not from configuration.**
  That is the anti-hindsight guarantee made concrete: a position settles under
  the rules published when it was taken, even if the live strategy is later
  replaced.

- **The exit books at the trigger level, not at the price that breached it.**
  This is the frozen convention of the shared resolver and it is *optimistic on
  a gap down*. It is now published as a rule of its own on the strategy card
  ("Fill assumption") rather than left in a docstring.

- **A position can run indefinitely.** With no expiry, a token that never gives
  back a quarter of its high is never sold, and that capital is unavailable for
  the next entry. This follows directly from §7's "exit only when the
  deterministic rule triggers" and is left visible on the equity curve rather
  than smoothed over.

- **The two benchmarks were made genuinely different, not renamed.** Sprint 25
  recorded that "buy every Radar token" and "equal-weight Radar" were one
  measurement under two labels and refused the duplication. §13 asked for both,
  so one now carries the wallet's cash constraint ($100 each, first come first
  served, $1,000 cap, never sold) and the other does not ($1,000 split evenly
  across the whole universe). They coincide only while ten or fewer tokens
  qualify, and the API publishes a note saying so when they do.

- **Benchmark membership is `is_active OR swept during the period`, not
  `is_active`.** Filtering to what is still on the Radar would hand every
  benchmark a survivorship bonus the wallet never got — the strategy had to hold
  what it bought.

- **The wallet's rule and the Strategy Lab's `trailing_25` are not the same
  rule.** The lab's carries a 48-hour holding period; the wallet's carries none.
  The lab was left untouched this sprint, and the two figures must not be quoted
  against each other — the correction the previous commit recorded still stands.

- **No threshold was chosen or adjusted after seeing a result.** 25% was
  specified in the brief before the relaunch and has not been revisited.
