# SESSION

Working state for MEMESCOPE. Rebuilt from the repository, not from memory.
Rules of engagement live in `CLAUDE.md`; architecture in `ARCHITECTURE_DECISIONS.md`.

## Current version

`0.8.0-rc1` (`backend/pyproject.toml`, `app/core/config.py`).
Branch: `opportunity-engine-foundation`. Last commit: `e60255c`.

## Completed sprints

| # | Sprint | Evidence |
|---|---|---|
| 1 | Discovery, enrichment, scoring engine, frontend surfaces | tagged history through `3069c12` |
| 2 | Platform stabilisation — autovacuum tuning, maintenance, audit corrections | `MEMESCOPE_AUDIT.md` §3.5, §6 |
| 3 | Decision layer — conviction, thesis, health, change | `e7b06b6`, `10c947f` |
| 4 | Analyst ensemble — six specialists behind one contract | `26ac040` |
| 5 | Radar sweep rotation + peak-vs-window fix | `14ea3e6`, `7715a15` |
| 6 | Watchlists, immutable event log, orchestrator + REST | `4c8e459`, `d38860f` |
| 7 | Opportunity Engine architecture, fresh graduation, near-graduation replay | `e60255c`, ADR §14a |

## Current sprint — Sprint 8: bonding-curve collection

Goal: land the on-chain input ADR §14a names as the only unblock for Near
Graduation. All uncommitted on `opportunity-engine-foundation`.

Done:

- `app/models/curve.py` + migration `20260803_0009_bonding_curve_snapshots`
- `app/services/curve/{pda,state,collector}.py` — local PDA derivation, account
  parse with invariants, batched `getMultipleAccounts` (100/call)
- `app/repositories/curve.py` — append-only snapshot writes
- Worker TX-3: `_collect_curves` runs before detection in `market/worker.py`,
  with its own transaction and its own counters
- `FEATURE_CURVE_COLLECTION_ENABLED` and friends in the `x-backend-env` anchor
- Tests: `test_curve_pda`, `test_curve_state`, `test_curve_collection`

- **Curve progress now reaches the providers.** `CurveSnapshotRepository.
  windows_for` batches the series; `as_of_progress` attaches, per observation,
  the newest curve reading taken at or before it — never carried backwards.
  Gated on `FEATURE_CURVE_COLLECTION_ENABLED` so a stopped series is reported
  absent rather than stalled. 9 new tests; suite 2887 passed at 91%.

Remaining:

- `make check` fails at `ruff format --check` across **33 files, 18 of them
  committed and untouched** — pre-existing drift, not this sprint's. `ruff
  check` and `mypy` are clean. Needs a repo-wide format commit of its own.
- The account layout in `services/curve/state.py` is still unverified against
  mainnet (quota). Invariants make a wrong layout yield no reading, not a
  wrong one — but the first live run is the real test.

## Sprint 9 — opportunity lifecycle scheduling (done)

`app/opportunities/scheduler.py`: `opportunity_review`, beat every 5 minutes,
calling the existing `review_expired()` and committing its own transaction. No
lock, matching `score_sweep` — transitions are pure functions of stored
timestamps, so a duplicate pass is a no-op. Beat registration and `include`
asserted. 7 new tests; suite 2894 passed.

Correction recorded: re-detection opens a new generation after **CLOSED**, not
after ARCHIVED — AD-09, and the live-status partial unique index is what
enforces it. Archival is a settling period, not a lock.

## Sprint 10 — provider analytics (done)

`app/opportunities/analytics.py` (pure derivations) +
`OpportunityRepository.provider_totals` (two grouped passes) +
`GET /api/v1/opportunities/providers`. Nothing stored, no migration. Precision
reports unavailable with a reason: nothing writes `REALISED`/`INVALIDATED`, so
it has no denominator until the realisation exit path ships with breakout.
18 new tests; suite 2912 passed.

## Sprint 11 — breakout provider (done)

`providers/breakout.py`, emitting `BREAKOUT` and `PRE_BREAKOUT` (mutually
exclusive). Price above its own trailing high on volume above the window's
trailing **median** — ADR §16's baseline question, settled by measurement:
median, not mean, and the current reading excluded from its own baseline.
Registered operational; TTLs and thresholds in the compose anchor.

Replay over 54,253 historical windows (800 tokens): 11 breakout, 126
pre-breakout (0.253% of windows), strength median 64, byte-identical on a
second pass. 25,887 windows unavailable — 20,252 no volume baseline, 5,635 no
price. That is the honest floor, not a defect.

## Sprint 12 — signal outcomes (done)

`opportunities/outcomes.py` (pure) + engine `_settle_outcomes` on the detection
path + migration `0010_outcomes` (two `event_kind` values only — the outcome
lives in the existing `status` column). No new state, no new column.

**Precision is defined over predictive signals only.** Fresh graduation and
breakout are factual: they report completed changes and cannot be wrong later,
so scoring them would publish 0.00 against providers that never forecast.
Their invalidations are counted as `contradicted` instead. Replay: pre-breakout
precision 4/13 = 0.31 over 800 tokens; deterministic across 2,009 assessments.

## Sprint 13 — RPC abstraction (done)

`services/rpc/`: `SolanaRPC` interface, `StandardSolanaRPC` (plain JSON-RPC,
any node), `HeliusRPC` (standard + DAS `getAsset`), registry mirroring the
market-provider pattern. `services/helius/client.py` is now an alias shim.
`SOLANA_RPC_PROVIDER=solana` runs the platform with **no Helius key**; the key
is required only when Helius is the configured provider.

Verified live against `api.mainnet-beta.solana.com`, no API key: `getSlot`,
`getMultipleAccounts`, and a real pump.fun curve account parsed.

**Curve layout is now verified against mainnet** (closes the Sprint 8 unknown):
on-curve accounts return `token_total_supply=1e15` and
`real_token_reserves=793_100_000_000_000` — both exactly the documented
pump.fun constants — and `complete_byte` sits at offset 48 as documented.

## Sprint 14 — curve parser finalization (done)

`services/curve/state.py`: the "virtual reserves never drain to zero"
invariant now scopes to `complete=0` only. A live graduated account zeroes all
four reserves on migration — that's a fact of completion, not a misread.
`_U64_MAX` sentinel check still applies unconditionally. Re-ran Sprint 13's
four real graduated accounts against mainnet: all 4 previously-refused reads
now parse, `complete=True`, `progress=1`. 5 new regression tests pinned to the
observed bytes (incl. the real 115/151-byte account lengths); 2978 passed.

## V1 redesign — Week 1, item 1 (done)

**Market data on the opportunity board.** Launch blocker #1 from the V1 spec:
the board carried no price, liquidity, volume or age, so a trader could read a
signal and had no way to evaluate it.

`MarketOut` (nullable) + `age_seconds` on `OpportunityOut`;
`latest_for_mints` and `price_as_of_for_mints` batched on the market
repository; `_context_for` resolves a whole page in three queries, not one per
card. 24h change is derived at read time from two stored readings — no
`price_change_24h` column, because a stored delta drifts from its source.

Absence is a first-class state: an unpriced token returns `market: null`, never
zero; a token younger than 24h returns `change_24h_pct: null`, never 0%.
8 new tests; suite 3001 passed. Verified live — 25 cards carrying real figures.

## Sprint 23 — the Radar becomes the homepage (done)

Launch blocker #1 of the V1 review: the nav called `/` the Radar and it
rendered the Opportunity board — 100 cards with more available, ranked by
signal freshness — while `useRadar` was imported only by the Track Record. The
ranked list carrying the Radar score and the base rates was never rendered as a
list.

`/` is now the top 10 by Radar score. `services/market_context.py` holds the
shared identity/market/age resolution (three batched queries) that was a
private helper on the board; `opportunities.MarketOut` is now an alias for
`MarketStripOut` and the wire format is unchanged. `RadarEntryOut` gained
`market`, `age_seconds`, `risk_score`, `risk_reasons`, `evidence` and `signal`.

Risk and evidence come from the newest `radar_snapshots` row, batched with
`DISTINCT ON` and **read rather than recomputed** — the risk beside a score must
be the one the sweep that produced that score measured. The signal is joined
from the Opportunity Engine through the board's own explanation renderer.

Measured: `/radar?page_size=10` 8ms, the 100-row record page 22ms. 3048 backend
passed (+17), 258 frontend passed (+38).

**Correction recorded:** the Radar and the board rank different tokens — 9 mints
of 72 overlap, and 12 of 72 Radar rows carry a live signal. This is expected
(one ranks quality, the other ranks recency), but it means the signal column is
sparse by construction and must never be read as "the other 60 have no story".

## Sprint 24 — the Radar row in trader language (done)

Sprint 23's correction became this sprint's central fix. Why-now was derived
from the Opportunity Engine, and on the live top ten exactly **one row carried
a signal** — so nine of ten rows explained nothing.

`app/radar/readout.py` (pure, inside the purity boundary — signal types arrive
as plain strings so it imports nothing from `app.opportunities`) renders one
sentence per row from stored facts, in priority order: live signal → large move
from detection → strongest detection reason → the detection itself. Measured
live: **10 of 10 rows explain themselves, against 1 of 10 before.**

Engine vocabulary is off the wire, not just off the screen. `RadarSignalOut`
lost `provider`, `severity`, `headline` and the engine's `confidence`; it now
carries a stable code and one label. `risk_band` is cut server-side against
`readout.RISK_BANDS` so the thresholds sit beside the number that produced
them. Evidence renders as four dots.

Removed from the row: the category chip, "Detected at $X", the venue name, the
"Liveness unknown" chip, and the sort tabs. Added: logo, price, and the base
rate in its own block.

Measured: `/radar?page_size=10` 8ms (unchanged), **11 statements for ten rows,
identical to one row**. 3082 backend passed (+34), 268 frontend passed (+10).

**Guard added:** `tests/integration/test_radar_query_budget.py` asserts that
serving ten rows and one row issue the same number of statements. A latency
benchmark only catches an N+1 once the table is big enough to hurt.

**Correction recorded:** the reason-priority order in `readout.REASON_PRIORITY`
is calibrated against one observation of the live board (`trend_aligned` on 10
of 10, `resistance_broken` on 8, `volume_expanding` on 4). It is a judgement
about *informativeness*, not a measured result, and it is the one thing in this
sprint that is not reproducible from stored data. Re-measure before trusting it
on a materially different universe.

## Sprint 25 — paper wallet & strategy engine (done)

A deterministic simulation of one published rule over stored prices. No wallet,
no order, no chain.

**The finding.** Replayed over the full stored history (83 detections, 38 closed
trades) the published rule returns **-60.98%** against **+22.74%** for buying
everything equal-weight: 26.3% win rate, profit factor 0.58, 65.5% max drawdown,
22 stop-outs against 7 targets. The -50% stop is what does the damage on this
market. **No threshold was adjusted after seeing this** — tuning until the number
looks good is the hindsight the design exists to prevent.

`app/paper/`: `models`, `strategy`, `engine`, `metrics` pure (AST-enforced, and
the core imports nothing outside `app.paper` — the strategy takes a signal type
as a plain string to keep that boundary at one entry); `repository`, `service`,
`api`, `scheduler` are the I/O seams.

**Exits resolve against the observation series, not against "the price now."**
`resolve_exit` walks readings in order and closes at the first breach, dated to
the observation. A worker that missed six hours produces the same trades as one
that missed none. This is the whole claim, and it is asserted by replaying the
same history in different chunks in both unit and integration tests.

Two tables (`0011_paper_wallet`). Cash, equity, ROI, win rate and drawdown are
derived at read time; no price and no strategy definition is stored.
`uq_paper_positions_wallet_mint` **is** the entry rule — re-entry is a state the
schema cannot represent. The entry block is written once, so a target cannot be
recomputed favourably.

One wallet per strategy, not per user: the rule is mechanical, so per-user
wallets would hold identical rows. Three endpoints, none of them POST — there is
no manual entry, so there is no write endpoint.

Measured: 3167 backend passed (+85), 291 frontend passed (+23). Live: 10
positions opened from the Radar top 10, $1000 fully deployed, replay
deterministic on re-run.

**Corrections recorded:**

- Sprint 24's Radar "Paper trade" placeholder is retired. It is now a *fact*
  ("In wallet" / "Traded"), never a control — the strategy has no manual step,
  so a button would imply discretion the design excludes.
- Max drawdown is measured on the **realised** equity curve only. The path
  between closes is not reconstructed, so it is a floor on the true figure. The
  API ships that caveat as `max_drawdown_note` rather than leaving the page to
  imply otherwise.
- "Buy every Radar token" and "equal-weight Radar" are the **same measurement**
  on this data. Reported once; two labels over one number would be duplication.

## Sprint 26 — Strategy Lab (done)

Nine published exit rules replayed over the same detections and the same stored
prices. Only the exit logic differs.

**Equal Weight v1 is frozen and placed 7th of 9** (-3.84% marked) against
Trailing Stop 25% at +54.58%. It has not been tuned in response and must not be:
every comparison is drawn against it. `test_paper_exits.py` replays 120
orderings through both the new rule engine and the original
`engine.resolve_exit` and demands identical answers.

**The correction the data forced.** The first run showed Time Exit 24h at
+23.44% return with a 0.11 profit factor — both correct, and together
misleading: total return marked open positions while win rate and profit factor
counted only closed ones. The lab now serves `realised_return_pct` and
`open_share_pct` beside every marked figure, and a finding fires on the largest
divergence. Time Exit 72h reads **+18.84% marked against -62.72% realised** with
62% still open. Without that column three rules would have been promoted whose
closed trades lost badly.

Architecture: exit rules are **data**. `ExitRules` has four optional fields and
one `resolve` covers all nine strategies — no duplicated replay engine. The
dataset is loaded once and shared, because separately-loaded datasets could
differ by a snapshot landing between loads.

Refused, each with its reason on the page: **ATR** (needs a true range; this
platform stores one price per observation with no OHLC), **annualised return**
(below the published 90-day floor; the replay covers 6.3 days), **monthly
returns** (less than one month exists).

Validated: byte-identical across 10 runs and after reloading from Postgres.
5.3ms to replay 9 strategies over 84 detections (756 trades), 183ms to load.
3347 backend passed (+180), 302 frontend passed (+11).

**Corrections recorded:**

- The Sprint 25 replay reported the baseline at -60.98%; the lab reports -3.84%.
  Both are correct and they measure **different things**. Sprint 25 was
  cash-constrained ($1,000, 41 of 83 detections funded); the lab is
  unconstrained so entries stay identical across rules. The API ships that
  distinction as `methodology` on every response. Never quote one as the other.
- `lab_service.py` was added to the paper purity boundary's `IO_MODULES`. That
  set should grow only for a genuinely new seam — a name appearing there because
  a *decision* moved into an I/O module is the boundary eroding.
- Ranking is on marked total return, stated. A composite score would be an
  opinion wearing a measurement's clothes.

## Sprint 27 — execution costs (done)

Raised by a question about whether Radar tokens are really tradeable.

**Provenance, settled.** All 84 Radar entries carry
`source_program = 6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P` — the pump.fun
program id, written by the scanner at creation, and the column admission
actually filters on. **The "pump" mint suffix is not the gate and must not be
used as one**: 82 of 84 have it, two do not, and a vanity suffix can be ground
by anyone. Venues observed: pumpswap (84), pumpfun bonding curve (39),
meteora (4).

**The measurement that mattered.** Median pool depth is **$1,857**; 57 of 85
tokens hold under $5,000. A $100 order moves that price ~10.8% each way. Every
figure published in Sprints 25 and 26 assumed a fill at the observed mid with no
fee and infinite depth.

`app/paper/costs.py` (pure) charges the published swap fee per side plus the
exact constant-product impact `S/Y`, against the depth observed **at each end**.
The exit is charged on the position's value *when it closes*.

**Cost is progressive** — 3.70 points on the worst rule, 11.56 on the best,
because winners sell bigger positions. A flat per-trade estimate reports a
uniform drag and misses this entirely; the first rough pass did exactly that.

Net sits **beside** gross and ranking still uses gross, so the frozen benchmark
does not move because a lens was added. After costs 5 of 9 rules stay positive;
Time Exit 7d flips negative and the benchmark goes -7.84% -> -12.74%.

Refused, with the reasons shipped on every response: slippage from competing
flow, priority-fee competition and MEV (snapshots are not fills), and impact on
bonding-curve pairs (no liquidity reported at all — excluded from net, count
published).

3369 backend passed (+22), 305 frontend passed (+3).

**Corrections recorded:**

- `current == peak` on 9 of 84 entries is correct — those tokens are at their
  high since detection. Four had a stored peak below the true observed maximum,
  but every missed high landed *after* the last sweep: 15-minute sweep latency,
  self-correcting. The real bug here was fixed earlier by `window_high`.
- Two assumptions in the cost model are **unverified** and would change every
  net figure: that `liquidity_usd` reports both sides of the pool (the model
  halves it — if it is one-sided, every impact figure doubles), and the 30 bps
  default swap fee. Both are configuration, not measurements. Verify against the
  venue before quoting a net figure as precise.

## Sprint 28 — reality audit (design only, not implemented)

Full report: `docs/SPRINT_28_REALITY_AUDIT.md`. Measured 2026-08-04 against the
running system, 88 Radar tokens. **No code written; awaiting approval.**

**Provenance: settled.** 88/88 carry `source_program = 6EF8rrec…` with a creation
signature and block time. No token can enter from another launchpad — admission
joins on that column. All 88 have graduated; none is currently on a bonding
curve. Venues: pumpswap 87, meteora 1.

**Three defects found.**

1. **`peak_market_cap` is not raised with `peak_price`** — 6 of 88 (6.8%) are
   internally inconsistent, one showing `peak_price` 30× `current_price` while
   `peak_market_cap = current_market_cap`. Cause: `update_current` writes the
   market cap only when the peak candidate *is* the current price, so a peak
   raised via `window_high` leaves it behind. The snapshot holding that high
   does carry a market cap — reading it is not inventing. **Fix must be
   forward-only; the historical rows are a permanent record.**
2. **43% of Radar tokens have market data over an hour old**; p95 snapshot age
   is 7,347 minutes. Three of the visible Top 10 carry 169-minute-old prices with
   no staleness marker on the row. Root cause is **queue depth (36,154 active),
   not a broken worker** — tracked tokens are not prioritised and wait behind
   36,000 others. `/health/pipeline` calls this "healthy" because it only checks
   whether *any* snapshot was recent.
3. **Symbol collision** — 9 distinct mints named TNOS ($1,307 to $83M), 5 named
   SAOF. All genuine pump.fun mints; standard copycat pattern. The Radar shows
   them side by side with no way to tell them apart.

**Latency, chain to browser:** median ~15 min, p95 ~123 min. Enrichment revisit
(p95 106 min) is **53× the 2-minute polling interval**. Building WebSockets first
would remove the smallest term and animate two-hour-old data.

**Correction to Sprint 27's framing.** I characterised median liquidity of
~$1,857 as evidence these tokens are barely tradeable, citing a 178× mcap/liquidity
ratio. That ratio was an outlier. Median market cap is $1,717 against median
liquidity $1,814 — **ratio ≈ 1×**, with only 2 tokens above 50×. Liquidity is
proportionate to size. The ~11% price-impact figure for a $100 order stands;
"you could not exit" was wrong for the median case.

**Recommended order (reverses the brief):** enrichment priority lane → visible
staleness → collision marker → `peak_market_cap` fix → WebSockets last.

**Not verifiable from stored data, and stated as such:** whether provider prices
match the chain. The platform records what the provider returned and has no
independent oracle; only faithful recording can be claimed, not accuracy.

## Sprint 30 — Paper Wallet V2, a fresh launch (done)

Full report: `docs/SPRINT_30_PAPER_WALLET_V2.md`. An operational reset, not a
redesign: the Radar, the scoring and the Strategy Lab are untouched.

**A wallet is now a generation, not a singleton.** `uq_paper_wallets_live` — a
unique index on a constant, partial on `archived_at IS NULL` — makes "exactly
one live wallet" a database fact rather than an application promise. Migration
`0013` archives generation 1 (`accb18fc…`, 13 positions, nothing deleted); that
step is what makes the index satisfiable, which is why it is in the migration.

Live: **generation 2, `trailing_stop_25_v1` v1.0.0, started
2026-08-05T06:34:19.840157Z**, $1,000 fully deployed into 10 positions on the
first pass. 115 Radar tokens considered, 105 refused for cash and **none for
eligibility**. First purchase GOAP at $0.004034, rank 1. Equity $1,110.03
(+11.00%) nine minutes in — entirely unrealised, and nine minutes is not a
result.

**The published rule is a trailing stop and nothing else.** No target, no fixed
stop, no holding period — `NULL` on the row, not zero, so "no such rule" and "a
rule set to zero" stay distinguishable. Entry reads the **whole ranked Radar**,
not a top-ten cut: §4's loop only terminates in permanent idleness otherwise.
The registry refuses to construct with two operational strategies, so removing
the selector is enforced at import.

`app/paper/eligibility.py` holds §5's conditions once, called by both the
evaluator and the read path — "no qualified token" on the page and "opened 0" in
the log cannot come from different rules. Liquidity is a new gate, earning its
place twice: bonding-curve pairs report no depth, and an uncostable trade is an
unauditable one.

`paper_trade_audit` is append-only by construction — **one INSERT in the whole
codebase, no UPDATE, no DELETE**. It stores market cap and pool depth at each
end because those live in prunable snapshots: a figure that is only derivable is
only derivable while its rows survive, and the oldest trades would go dark first.

The wallet now advances on every Radar refresh as well as its own beat; verified
live (`paper_review_requested trigger=radar_sweep`, pass ran 0.1s later). It is a
trigger, not a second evaluator — exits still resolve from the stored series, so
more frequent passes change when a decision is *recorded*, never which one.

Measured: 3457 backend passed (+88), 374 frontend passed (+69). `make check`
green, including `ruff format --check` — the 23 pre-existing unformatted files
were formatted in their own commit first.

**Corrections recorded:**

- The generation number is **global, not per strategy**. The first version
  numbered within a strategy id, making the relaunch "v1" because its rule was
  new. Caught on the first live pass; the ten positions it had opened were
  deleted and re-opened under the corrected numbering, before any audit row or
  published figure existed.
- The exit books **at the trigger level, not at the price that breached it**.
  That is the frozen resolver's convention and it is optimistic on a gap down.
  It is now published on the strategy card as a rule of its own.
- **A position can run indefinitely.** No expiry means capital can stay locked
  in a token that never gives back a quarter of its high. This follows from §7
  and is left on the equity curve rather than smoothed over.
- The two benchmarks were made **genuinely different**, not renamed: one carries
  the wallet's cash constraint, one is the unconstrained index. Sprint 25's
  refusal of one-number-two-labels stands; a note fires when they coincide.
- Benchmark membership is `is_active OR swept during the period`. Filtering to
  what is still active would hand every benchmark survivorship the wallet never
  had.
- **The wallet's rule is not the lab's `trailing_25`** — the lab's carries a
  48-hour hold. The correction the previous commit recorded still applies; the
  two figures must not be quoted against each other.
- Not demonstrated live: **no trade has closed**, so the audit-writing path and
  every realised metric are proven by tests only. The empty state has not fired
  either — the wallet deployed its full $1,000 on pass one.

## Incident 2026-08-05 — the dead-letter cascade (fixed)

Full record: `docs/incidents/2026-08-05-dead-letter-cascade.md`. Found because
the wallet's positions read "updated 25 minutes ago" and kept ageing — the
freshness label from Sprint 28.1 is the only reason this surfaced at all.

A 60-second DexScreener circuit-breaker cooldown **permanently removed 163 of
the 200 tokens in the priority enrichment lane**, including 10 of the paper
wallet's 12 holdings. `succeeded = error is None` charged the outage to every
token in the batch; a rejection returns at `latency_ms=0` so the worker spun and
burned the 10-failure budget in seconds; `claim_due` filters on `ACTIVE`, and
`requeue_dead_letters` existed with **no caller anywhere in the codebase**.

Three fixes, matching the three defects:

- `_defer` treats provider-unavailable as a **batch deferral** — one UPDATE to
  `next_refresh_at`, no failure count, no attempt, no status change — pushed
  back by the breaker's own `retry_after_seconds`, which the error now carries
  rather than hiding in its message. Counted as `deferred`, never as `failed`.
- `should_dead_letter` now needs elapsed failing time as an independent second
  condition. A count alone is cadence-dependent: ten failures is 2.5 minutes on
  the 15-second lane and 20 on the normal one, so the tokens the product most
  wants fresh were the easiest to park.
- `enrichment-requeue-dead-letters` beat, every 5 minutes, bounded and
  oldest-first. Dead-lettering is a **quarantine, not a grave**.

Live: 154 tokens readmitted, every holding back to a 0-minute price age inside a
minute. 3472 backend passed (+15), 374 frontend. `make check` green.

**No figure was ever wrong.** Exits resolve from the stored series, so the
trailing stops still closed at the reading that breached them — the outage
delayed *when a decision was recorded*, never which one. After recovery the
wallet settled 4 trades and wrote its first 4 audit rows, so the permanent
record is now proven live rather than only by test.

**Worth watching:** `Falcon9` closed -11.64% gross against **-24.29% net** —
$12.09 of impact on a $100 position, exiting a far thinner pool than it entered.
The clearest live evidence yet for Sprint 27's finding that a flat per-trade
cost estimate misreports this market.

## Known blockers

- **Helius plan quota exhausted (HTTP 429).** Discovery is down and curve
  collection cannot run against the live chain. Not a bug; reported through
  `/api/v1/health/pipeline`. Everything in this sprint is written to be correct
  when quota returns.
- **Near graduation stays flag-off** until curve progress is proven to flow.
  Do not re-open the market-cap question — ADR §14a, closed with measurement.
- **pump.fun `liquidity_usd` is 100% null** (ADR 0002). Fix built, deployed and
  reverted the same day; still the largest signal-quality constraint.
- `review_expired` has no scheduled caller yet.

## Next sprints (planned, not started)

Numbering note: Sprint 24 was planned here as the paper wallet and was spent on
the Radar readout instead. The wallet moves to 25 and everything shifts by one.

- **Sprint 25 — paper wallet.** The only V1 destination that is still a
  placeholder. Model, migration, deterministic strategy engine ($100 equal
  weight, TP +100%, SL −50%, expiry = signal expiry), `/api/v1/paper`, and the
  wallet page. `/radar/benchmark` already reports `paper_wallet_note` honestly;
  that note is what this sprint retires. **The Radar row's "Paper trade" action
  ships disabled until this lands** — `RowActions` renders it `aria-disabled`
  with a plain-language title, and a test asserts it is not a button.
- **Sprint 26 — de-theming.** `agent-sigil`, `ai-core`, `universe` and
  `sentinel` are wired into `error.tsx`, `not-found.tsx`, `states.tsx`,
  `badge.tsx` and the auth layout, so removing them is a design-system change,
  not a rename. Also retires ~1,400 lines of client-side derivation
  (`lib/sentinel.ts`, `mission.ts`, `research-priority.ts`, `conviction.ts`,
  `thesis.ts`, `scoreboard.ts`) that forms a second opinion competing with the
  server-rendered reason codes. The brand still reads **LETZMOON** in
  `components/brand/logo.tsx` and `app/layout.tsx`.
- **Sprint 27 — Track Record analytics.** Sort by drawdown, age, market cap,
  signal and Radar score; detection/current/peak market-cap columns in the
  table. The page is already the strongest in the product; these are its gaps.
