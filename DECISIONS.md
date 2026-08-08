# MEMESCOPE Architecture Decisions

This ADR index records major decisions supported by repository code or dated project documentation. Current code and migrations remain authoritative when an older ADR conflicts with implementation.

## ADR-01 — Provider-neutral market data

- **Date / Sprint:** 2026-07-27, Day 3.
- **Problem:** Solana market-data vendors differ in payloads, coverage, batching, rate limits, and availability.
- **Decision:** Use a MarketDataProvider abstraction with a typed, provider-neutral MarketData object and runtime registry.
- **Why chosen:** It confines vendor JSON to adapters, permits deterministic tests, and makes provider replacement localized.
- **Alternatives considered:** Direct DexScreener calls in services; dict-returning clients; repository-layer normalization. All were rejected because they spread external semantics into business/persistence code.
- **Consequences:** Adapters own transport quirks and a new vendor requires deliberate implementation; domain services remain provider-independent.
- **Current status:** Accepted and implemented. See docs/adr/0001-market-provider-abstraction.md.

## ADR-02 — Partial data is explicit, never fabricated

- **Date / Sprint:** Day 3 onward; reinforced by scoring and Opportunity Engine documentation.
- **Problem:** Market-provider coverage is incomplete, particularly for bonding-curve liquidity and unsupported intelligence inputs.
- **Decision:** Make normalized fields optional; return unavailable state/reason rather than estimate or silently substitute.
- **Why chosen:** A missing observation is more honest and less damaging than false precision or a semantically different value.
- **Alternatives considered:** Treat absence as zero; infer values; hide unavailable components. These are rejected by the data and scoring contracts.
- **Consequences:** Scores/evidence can be lower, UI states can be empty, and product language must explain limits.
- **Current status:** Accepted and implemented across provider, scoring, Radar, opportunity, and paper paths.

## ADR-03 — Preserve observation history and permanent records

- **Date / Sprint:** Day 3 scoring design; Radar/Track Record and Paper Wallet V2.
- **Problem:** Current state alone cannot explain a result, reproduce a calculation, or retain trade evidence after snapshot retention.
- **Decision:** Use append-only market snapshots, score history, intelligence events, Radar records, and paper-trade audit entries; retain immutable first-detection/entry/exit facts.
- **Why chosen:** Historical evidence is needed for honest readouts, replay, outcome analysis, and auditability.
- **Alternatives considered:** Mutable current-state-only rows; recomputing all historic values from retained snapshots. Rejected because history can be pruned or revised and cannot safely replace durable evidence.
- **Consequences:** More storage and retention work; historical data needs explicit lifecycle planning.
- **Current status:** Accepted and implemented. Snapshot retention/partitioning remains open.

## ADR-04 — Server-derived values only

- **Date / Sprint:** 2026-07-29 frontend hardening; carried through V1.
- **Problem:** Client-side heuristics can diverge from backend scores, eligibility, and calculations.
- **Decision:** The backend computes scores and business/financial facts; the frontend renders returned state.
- **Why chosen:** One authoritative calculation prevents duplicate logic and misleading UI results.
- **Alternatives considered:** Recreate heuristics in React. Rejected and removed in the frontend refactor.
- **Consequences:** API contracts need sufficient explanation fields; frontend changes do not alter decision logic.
- **Current status:** Accepted and implemented.

## ADR-05 — Radar and Track Record are permanent evidence, not a transient leaderboard

- **Date / Sprint:** 2026-07-29; V1 Sprints 20–24.
- **Problem:** A live ranking alone cannot show what was observed, how it evolved, or what happened afterward.
- **Decision:** Maintain Radar records, immutable first-detection facts, upward-only peaks, achievements, and Track Record presentation.
- **Why chosen:** A record that preserves adverse outcomes as well as favorable ones is necessary for an evidence-first product.
- **Alternatives considered:** Show only current rankings or delete/overwrite historic states. Rejected because both erase context.
- **Consequences:** Historical rendering must not animate/rewrite past facts; stored records need durable identifiers.
- **Current status:** Accepted and implemented.

## ADR-06 — Historical base rates, not predictions

- **Date / Sprint:** Sprint 22, 2026-08-04.
- **Problem:** Readers need context for historical outcomes without being given a forecast or recommendation.
- **Decision:** Display historical base-rate context on Radar entries.
- **Why chosen:** It gives observed context while preserving the no-prediction/no-advice boundary.
- **Alternatives considered:** Predictive or conviction-led outcome claims. Unsupported by the documented product boundary.
- **Consequences:** Base rates must be labeled as historical and cannot imply future return.
- **Current status:** Accepted and implemented.

## ADR-07 — Opportunities are transitions, not token thresholds

- **Date / Sprint:** Architecture decision package, 2026-08-02; Opportunity Engine Sprints 8–14.
- **Problem:** Ranking a historical token universe by absolute values does not surface novelty.
- **Decision:** Admit an opportunity when a measurable transition occurs between observations; use the historical token database as substrate, not as the candidate list.
- **Why chosen:** A token may be old while its graduation, breakout, or other change is newly relevant.
- **Alternatives considered:** Static threshold or score-based admission. Rejected because it repeatedly returns the same population.
- **Consequences:** Opportunity data needs prior observations, materiality/evidence, lifecycle review, and source-supported providers.
- **Current status:** Accepted and implemented for fresh graduation and pre-breakout; near graduation is unavailable without a source.

## ADR-08 — Opportunity signals are deterministic, independent, and explainable

- **Date / Sprint:** Architecture decision package, 2026-08-02.
- **Problem:** A token can have multiple changes with different expiries, evidence, and certainty.
- **Decision:** Model one opportunity per token/generation with independently expiring signals; calculate confidence/ranking deterministically; render explanation from stable reason codes.
- **Why chosen:** This preserves deduplication, replayability, and a clear answer to why an item appeared now.
- **Alternatives considered:** A static candidate list, prose explanations stored in the database, or one undifferentiated signal. Rejected because they drift or cannot model lifecycle independently.
- **Consequences:** Database constraints enforce identity; signals need expiration review; explanations remain a rendering concern.
- **Current status:** Accepted and implemented in the Opportunity Engine.

## ADR-09 — Do not create duplicate calculation or replay systems

- **Date / Sprint:** Scoring design and Sprint 26/30 paper work.
- **Problem:** Separate implementations of the same rule can silently disagree and retrospectively redefine a result.
- **Decision:** Keep pure rules shared and versioned: published strategy values come from executable fields, one exit resolver serves equivalent strategies, and deterministic inputs drive replay.
- **Why chosen:** Reproducibility and auditable claims require one rule implementation.
- **Alternatives considered:** A separate Lab exit engine; database-configurable rules that can disagree with code; duplicated client calculations. Rejected.
- **Consequences:** Rule changes require a new strategy/model version; some historical wallet behavior cannot be reconstructed when its original rank inputs were not retained.
- **Current status:** Accepted and implemented. Strategy Lab explicitly discloses its divergence from exact wallet-entry replay.

## ADR-10 — Priority enrichment is derived from current product need

- **Date / Sprint:** Sprint 28, 2026-08-04.
- **Problem:** Visible/high-priority candidates need fresher market context without permanently favoring an accumulated subset.
- **Decision:** Recompute the priority enrichment lane from what the product currently displays.
- **Why chosen:** Membership is current state, not durable identity; recomputation prevents a stale favored set.
- **Alternatives considered:** Accumulate a permanent priority list. Rejected in scheduler documentation.
- **Consequences:** The lane refreshes frequently and is dependent on current Radar state and worker operation.
- **Current status:** Accepted and implemented.

## ADR-11 — Paper Wallet V2 uses one live generation and a continuous simulation

- **Date / Sprint:** Sprint 30, 2026-08-05.
- **Problem:** The original wallet could not both preserve prior results and relaunch under a new rule without mixing histories.
- **Decision:** Archive old generations, enforce exactly one live wallet by database constraint, persist positions/trades/audit evidence, and advance the active wallet every five minutes and after Radar refresh.
- **Why chosen:** It preserves historical truth while ensuring the current rule has a distinct, continuous record.
- **Alternatives considered:** Mutate the existing wallet; delete/reset old positions; treat worker passes as separate evaluators. Rejected because each would obscure history or duplicate logic.
- **Consequences:** Retired positions remain frozen; only one operational paper strategy is allowed; scheduler reliability becomes product-visible.
- **Current status:** Accepted and implemented through migration 0013_paper_wallet_v2.

## ADR-12 — Default paper strategy: equal USD 100 entries with a 25% trailing stop

- **Date / Sprint:** Sprint 30, 2026-08-05.
- **Problem:** The paper wallet needs one published, testable rule rather than discretionary or retrospectively adjusted behavior.
- **Decision:** Use trailing_stop_25_v1: USD 100 equal-weight entries in the highest-ranked eligible whole-Radar candidate; one entry per mint/generation; exit after a 25% drawdown from the running high.
- **Why chosen:** Equal sizing avoids mixing a second score-based allocation opinion into a Radar test; a trailing stop is stated in advance and mechanically executable.
- **Alternatives considered:** Retain the top-ten fixed-bracket/holding-period rule; variable sizing; discretionary selection; partial fills. The old equal-weight strategy is retired and archived; the others are not the published V2 rule.
- **Consequences:** A position may remain open indefinitely, cash below USD 100 cannot be deployed, and gap exits use a disclosed optimistic trigger-level convention.
- **Current status:** Accepted and operational when the paper-wallet feature flag and workers are enabled.

## ADR-13 — Liquidity is an entry gate; composite fill is not active

- **Date / Sprint:** ADR 0002, 2026-07-29; Sprint 30 entry conditions.
- **Problem:** Pump.fun bonding-curve liquidity was absent from the primary provider, but a secondary composite provider stalled enrichment under real concurrency.
- **Decision:** Preserve the provider abstraction; do not treat a stalled secondary fill as a valid current solution. Require positive liquidity for Paper Wallet V2 entry.
- **Why chosen:** A delayed or semantically incompatible fill is worse than an explicit absence; paper entries need a stated liquidity condition.
- **Alternatives considered:** Replace DexScreener; use mint-keyed GeckoTerminal values; block enrichment until budget refills; continue the composite request-path fill. These are documented as rejected/deferred/reverted.
- **Consequences:** Some curve tokens cannot qualify, and liquidity-source work remains a launch blocker.
- **Current status:** Composite provider design is recorded but reverted/non-production-viable as placed; direct curve collection exists, while reliable live coverage remains unresolved.

## ADR-14 — Honesty is a product and operational requirement

- **Date / Sprint:** Project-wide; reinforced by scoring, Radar, Strategy Lab, and Sprint 30.
- **Problem:** A system can appear more capable by hiding missing data, changing past rules, treating simulated fills as real, or presenting immature results as conclusions.
- **Decision:** Publish limits, reason codes, unavailable state, historical-only context, simulation caveats, and measured dates; preserve losses and avoid advice/predictions.
- **Why chosen:** The product mission is defensible recorded evidence, not persuasion.
- **Alternatives considered:** Silent fallbacks, placeholder precision, narrative claims, or unqualified performance headlines. Unsupported by repository policy and design.
- **Consequences:** More explicit empty/error states and less promotional language; every new feature needs a stated evidence boundary.
- **Current status:** Accepted and encoded in current product, calculation, and documentation conventions.
