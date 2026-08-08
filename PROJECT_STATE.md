# MEMESCOPE Project State

Snapshot based on repository commit 4350212a804582ecc1e19ce229d51599a5364c74 (2026-08-05). It records repository capability, not the unobservable live state of a deployment. Checked-in feature flags default to disabled; their environment-specific state is not derivable from this repository.

## Current product status

The repository is on the v0.8.0-rc1 release line and contains the read-only intelligence, Opportunity Engine, and Paper Wallet V2 code paths. There is no live trading or custody implementation. Production readiness is not evidenced as complete in the repository.

## Current architecture

~~~mermaid
flowchart LR
  RPC["Solana RPC / WebSocket"] --> Scan["Scanner"]
  Scan --> Tokens["discovered_tokens"]
  Tokens --> Enrich["Enrichment queue"]
  Enrich --> Snapshots["token_market_snapshots<br/>(append-only)"]
  Snapshots --> Scores["Scoring"]
  Scores --> ScoreState["token_scores + token_score_history"]
  Snapshots --> Radar["Radar / Track Record"]
  Snapshots --> Opportunities["Opportunity Engine"]
  Snapshots --> Paper["Paper Wallet"]
  Radar --> Priority["Priority enrichment lane"]
  Radar --> Web["FastAPI /api/v1"]
  ScoreState --> Web
  Opportunities --> Web
  Paper --> Web
  Web --> UI["Next.js dashboard"]
~~~

The conventional backend direction is router → service → repository → database. Provider adapters isolate external payloads. Worker jobs own background transactions; request database dependencies own request transactions.

## Implemented features

- Solana/Pump.fun discovery using standard RPC and an optional Helius path, including a Pump.fun CreateEvent fallback.
- Durable enrichment state, append-only market snapshots, and direct Pump.fun curve collection.
- Deterministic scoring: liquidity depth, momentum, trade flow, valuation structure, survival/age, and a market-risk gate. Unsupported holder, smart-money, and narrative inputs remain explicitly unavailable.
- Radar rankings, permanent Track Record records, achievements, identity/readout support, and historical base-rate reporting.
- Intelligence events, analyst cache, watchlist domains, and exit-intelligence support.
- Change-based opportunities for fresh graduation and pre-breakout, with lifecycle review, signal outcomes, and analytics. Near graduation is non-operational without a source.
- Priority enrichment for visible/important candidates.
- Paper Wallet V2, deterministic eligibility, trailing-stop strategy, cost model, immutable audit records, idle-cash explanation, and Strategy Lab.
- Protected dashboard routes for Radar, Track record, Paper wallet, Strategy lab, and a placeholder Settings page.

## Current scheduler overview

All schedules are configured in backend/app/workers/celery_app.py. Their effect depends on their feature flags and a running worker.

| Job | Cadence | Purpose |
|---|---:|---|
| purge expired refresh tokens | daily 03:00 UTC | Removes expired refresh tokens. |
| score sweep | every 15 minutes | Reconciles scoring after crash/restart gaps. |
| prune score history | daily 03:30 UTC | Applies score-history retention work. |
| Radar sweep | every 15 minutes | Re-evaluates persisted projects. |
| Pump.fun Radar scan | every 15 minutes | Runs Pump.fun Radar admission from persisted data. |
| event cycle | minutes 3, 18, 33, 48 | Detects change against prior analyst readings. |
| opportunity review | every 5 minutes | Advances expiry, closure, and archival. |
| paper review | every 5 minutes and after Radar refresh | Settles exits and considers eligible entries. |
| priority lane | every minute | Recomputes priority enrichment membership. |
| dead-letter requeue | every 5 minutes | Returns eligible enrichment work from quarantine. |

## Current strategy overview

The operational paper strategy is trailing_stop_25_v1, version 1.0.0.

- It selects the highest-ranked eligible candidate across the whole Radar, not a top-ten cutoff.
- Each entry is USD 100 equal weight; partial fills are declined.
- A wallet generation may enter a mint once.
- Entry requires no existing holding, a market snapshot, positive price, acceptable trading status when supplied, positive liquidity, and available cash.
- Exit occurs after a 25% fall from the highest observed price while open.
- It has no take-profit, fixed stop, or maximum holding period.
- Exit booking uses the stored series and a published optimistic trigger-level convention for a gap.

This is a paper simulation. It models fees and constant-product price impact but does not model all live-execution effects, including MEV and partial fills.

## Current feature-completion percentages

The repository does not define an accepted feature scope, denominator, or completion metric. Therefore no evidence-supported percentage can be calculated. The table deliberately records status rather than inventing percentages.

| Area | Completion percentage | Evidence-supported status |
|---|---:|---|
| Discovery, enrichment, scoring, and Radar | Not measured | Implemented code paths; flags default off. |
| Opportunity Engine | Not measured | Fresh graduation and pre-breakout are implemented; near graduation lacks a source. |
| Paper Wallet V2 and Strategy Lab | Not measured | Implemented simulation; execution realism is intentionally limited. |
| Production deployment | Not measured | Operational completion is not evidenced by the repository. |

## Current live metrics

No current live metrics are available from source control. The following are historical, dated measurements and must not be treated as present production values:

| Measurement | Reported result | Evidence |
|---|---:|---|
| Radar top-10 read | 8 ms | Sprint 23 report |
| Radar record read | 22 ms | Sprint 23 report |
| Strategy Lab | 5.3 ms across 9 strategies / 84 detections | Sprint 26 report |
| Strategy Lab load | 183 ms | Sprint 26 report |
| Dead-letter recovery | 154 tokens; minute-0 price within 1 minute | Sprint 30 incident record |
| Validation at HEAD | 3,474 backend tests; 374 frontend tests; make check clean | Commit 4350212 message |

The test suite was not rerun for documentation work because it may write to a test database and this sprint excludes database modification.

## Current launch blockers

- The latest documented incident reports Helius quota exhaustion (HTTP 429), leaving the scanner down and curve collection without a live source.
- Pump.fun curve-token liquidity remains unreliable; the composite provider was reverted after it stalled enrichment.
- Near-graduation detection lacks an upstream source.
- Production host/domain, credential handling, TLS/ACME verification, Sentry verification, backups/monitoring validation, and real load testing are not evidenced as complete.
- Paper Wallet V2 remains a simulation, not a live-execution product.

## Current technical debt

- Snapshot retention/partitioning and a latest-snapshot pointer are proposed, not implemented.
- Historical trend reads were reported at roughly 5–7 seconds; the proposed latest-pointer optimization remains open.
- Documentation is fragmented and stale in several primary sources.
- exit_signals/api.py has a documented architecture exception: inline SQL and a private Radar import.
- Settings is a placeholder; implemented backend capabilities are not all finished product workflows.
- Nginx deployment material conflicts with the Caddy production overlay.
- A recorded frontend dependency audit found three high-severity transitive findings; current remediation is not established in repository evidence.

## Current known limitations

- Provider availability and fidelity are external constraints; unavailable data must remain visible.
- Paper exits use stored quotes and an optimistic gap convention, not actual fills.
- No documented partial-fill model or maximum position-depth cap exists.
- Opportunity coverage is limited to source-supported transitions.
- Live balances, throughput, feature-flag state, and service health cannot be inferred from code.

## Active decisions and pending work

Active decisions are catalogued in DECISIONS.md. Priorities supported by current documents are:

1. Restore a reliable scanner/curve source and monitor quota/availability.
2. Implement or explicitly defer a tested liquidity-source design.
3. Implement or explicitly defer near graduation when a source exists.
4. Add retention/partitioning and evaluate a latest-snapshot pointer.
5. Complete production-operability work: secrets, host/domain, TLS, Sentry, monitoring, backups, and load testing.
6. Reconcile documentation and generate a current API reference from routes/tests.
