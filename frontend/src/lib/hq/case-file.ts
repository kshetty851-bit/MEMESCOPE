import type { RadarDetail, MarketStrip } from "@/types/radar";
import type { PaperPosition, PaperPositions } from "@/types/paper";
import type { Source } from "./adapter";
import { fresh } from "./adapter";
import type {
  PaperDecisions,
  SafetyEvaluations,
  TokenSecurityEvaluations,
} from "./pipeline";

/**
 * THE TOKEN CASE FILE ADAPTER.
 *
 * HQ-4's rule extended to individual tokens: components read a normalized
 * `TokenCaseFile`, never a backend field name. This file is the only place
 * that translates `RadarDetail` / `PaperPosition` / a safety-evaluation row
 * into "what happened to this token" — and the only place with the authority
 * to decide that something is UNAVAILABLE rather than guess.
 *
 * ── THE REAL PIPELINE, AS AUDITED FOR THIS PHASE ──────────────────────────
 *
 * A token's actual path through MEMESCOPE, and exactly what each stage below
 * reads. No conceptual diagram substitutes for this — it is what the code
 * on this branch does today.
 *
 *   scanner discovers a mint
 *     → `token.discovered` (WS), a `radar_tokens` row with `first_detected_at`
 *   enrichment + scoring produce dimensions and reasons
 *     → `score.changed` (WS); `GET /radar/{mint}` returns `dimensions`,
 *       `reasons`, `last_evaluated_at` — this one endpoint already carries
 *       discovery, scoring *and* the current market strip, because Radar's
 *       detail view was built to answer exactly this question first.
 *   `PaperWalletService` reviews ranked, *active* Radar entries every pass
 *   and calls `paper.eligibility.judge()` — a pure function over market
 *   facts only (already-traded, already-held, has a snapshot, has a price,
 *   `trading_status == "trading"`, liquidity > 0). It does not read mint
 *   authority, freeze authority, or any safety/security signal. **Paper's
 *   buy decision has never consulted token safety.**
 *   a passing judgement opens a position
 *     → `paper.changed` (WS); a row in `paper_positions`, exposed whole via
 *       `GET /paper/positions` — "every simulated trade", open and closed
 *       together. Absence from this list is real negative evidence: the
 *       list is exhaustive, so a mint that never appears in it was never
 *       bought, full stop.
 *
 * ── WHAT HQ-6 CHANGED, AND WHAT IT DELIBERATELY DID NOT ──────────────────
 *
 * Two gaps above are now closed, and the third is closed differently from how
 * it looks.
 *
 * ATLAS is no longer the Real Wallet's preview. `GET /token-security/
 * evaluations/{mint}` is a shared, read-only evaluator that runs regardless of
 * `REAL_WALLET_EXECUTION_MODE`, and it answers three states rather than two:
 * VERIFIED, FAILED, UNKNOWN.
 *
 * SEC-1 then made `LIQUIDITY_SECURITY` real. It is no longer permanently
 * UNKNOWN: the backend derives the pump.fun bonding curve and the canonical
 * PumpSwap migration pool from the mint and reads them on-chain. What HQ
 * renders is the backend's verdict plus its **mechanism**, and the mechanism
 * is why the word "locked" still never appears here — what gets proven is
 * protocol custody or a burned migration LP, and neither of those is a
 * locker. Saying "locked" would claim something nobody verified.
 *
 * DECISION can finally render FAILED. `GET /paper/decisions/{mint}` serves the
 * verdict the review pass records at the moment it decides. HQ still does not
 * recompute a single eligibility condition; it reads the engine's own answer.
 *
 * WHAT DID NOT CHANGE — AND THIS IS THE POINT OF THE PHASE:
 *
 * **Paper Wallet still does not consult token security before buying.**
 * `judge()` reads market facts only. So a case file can truthfully show
 *
 *     ATLAS    — FAILED or UNKNOWN
 *     DECISION — PASSED
 *     REX      — BOUGHT
 *
 * all at once, and this file must render exactly that when it happens. The
 * inconsistency is real, it is the evidence HQ-6 exists to collect, and
 * smoothing it into a coherent-looking story would destroy the only thing the
 * phase produced.
 */

/* ── the normalized shape ────────────────────────────────────────────── */

/**
 * `UNKNOWN` is separate from `UNAVAILABLE` and the distinction is the whole
 * contract. UNAVAILABLE means no source was consulted or none answered.
 * UNKNOWN means a source answered and could not establish the fact — the
 * token was evaluated and the platform still cannot say it is safe. Folding
 * them together would let an RPC outage and a genuinely unverifiable token
 * render identically, which is the failure this phase exists to prevent.
 */
export type CaseStageStatus =
  | "PENDING"
  | "PASSED"
  | "FAILED"
  | "UNKNOWN"
  | "UNAVAILABLE";

export interface CaseStage {
  status: CaseStageStatus;
  /** When the evidence behind this stage was produced. Null when there is none. */
  timestamp: string | null;
  /** One sentence. Never fabricated from a code alone without checking it means this. */
  summary: string;
  reasonCodes: string[];
  /** Whether any evidence source was actually consulted for this stage. */
  sourced: boolean;
  /** `true` when the reading might already be older than the pipeline moves. */
  stale: boolean;
}

export type CaseOverallState =
  | "discovered"
  | "scoring"
  | "evaluating"
  | "rejected"
  | "bought"
  | "closed"
  | "unknown";

export interface CaseStages {
  discovery: CaseStage;
  scoring: CaseStage;
  market: CaseStage;
  safety: CaseStage;
  decision: CaseStage;
  execution: CaseStage;
}

/** A single structured evidence row for the case panel. `null` renders NOT AVAILABLE. */
/**
 * Which department a row belongs to, and therefore which heading it sits
 * under.
 *
 * The separation is the point rather than the tidiness. "Liquidity $24,300"
 * and "Liquidity security: Unknown" are adjacent strings about completely
 * different things — one is a market depth reading from a price provider, the
 * other is a statement about whether anyone can withdraw that depth — and a
 * flat list invites a reader to treat the first as evidence for the second.
 * Dex reporting a large number is not evidence that Atlas cleared anything.
 */
export type CaseEvidenceGroup = "market" | "security" | "paper" | "scoring";

export interface CaseEvidence {
  label: string;
  value: string | null;
  /** `AT ENTRY` | `CURRENT` | `LAST CHECKED` | undefined when timing is not ambiguous. */
  when?: "entry" | "current" | "checked";
  source: string;
  group: CaseEvidenceGroup;
}

export interface TokenCaseFile {
  mint: string;
  symbol: string | null;
  name: string | null;
  imageUrl: string | null;
  discoveredAt: string | null;
  lastUpdatedAt: string | null;
  currentStage: keyof CaseStages;
  overallState: CaseOverallState;
  stages: CaseStages;
  evidence: CaseEvidence[];
}

/* ── freshness ───────────────────────────────────────────────────────── */

/**
 * How long a reading stays "current" before the stage is marked stale.
 *
 * Discovery has no window: `first_detected_at` is a permanent historical
 * fact and is never stale, by definition — see §28. Everything else uses the
 * same multiple-of-poll-interval logic HQ-4 established.
 */
const STAGE_STALE_MS = {
  scoring: 15 * 60_000,
  market: 5 * 60_000,
  safety: 30 * 60_000,
} as const;

function num(value: string | null | undefined): string | null {
  return value === null || value === undefined ? null : value;
}

/**
 * `PaperPosition.current_pct` (and `peak_pct`) arrive already scaled to a
 * percentage by `_pct_from` in `app/paper/api.py` — "20.11" means 20.11%, not
 * a fraction of one. Multiplying by 100 again was live-verified against a
 * real closed position and produced 2011.0% instead of 20.1%, which is
 * exactly the kind of bug fixture data cannot catch and only a real number
 * exposes.
 */
function pct(value: string | null | undefined): string | null {
  if (value === null || value === undefined) return null;
  const n = Number(value);
  return Number.isFinite(n) ? `${n >= 0 ? "+" : ""}${n.toFixed(1)}%` : value;
}

function money(value: string | null | undefined): string | null {
  if (value === null || value === undefined) return null;
  const n = Number(value);
  if (!Number.isFinite(n)) return value;
  return `$${n.toLocaleString("en-US", { maximumFractionDigits: n < 10 ? 4 : 0 })}`;
}

function ageMs(timestamp: string | null, now: number): number | null {
  if (!timestamp) return null;
  const at = Date.parse(timestamp);
  return Number.isFinite(at) ? now - at : null;
}

/* ── sources this file accepts ──────────────────────────────────────── */

export interface CaseSources {
  /** `GET /radar/{mint}` — discovery, scoring and market, together. */
  radar: Source<RadarDetail>;
  /**
   * `GET /real-wallet-safety/evaluations/{mint}`.
   *
   * Kept only as supplementary evidence. Since HQ-6 the Atlas stage is
   * derived from `tokenSecurity` below; this one describes the Real Wallet's
   * own trade-sized preview and is almost always empty.
   */
  safety: Source<SafetyEvaluations>;
  /** `GET /token-security/evaluations/{mint}` — the shared evaluator. Atlas. */
  tokenSecurity: Source<TokenSecurityEvaluations>;
  /** `GET /paper/decisions/{mint}` — the engine's own per-mint verdict. */
  decisions: Source<PaperDecisions>;
  /**
   * `GET /paper/positions` — the exhaustive record; searched by mint.
   * `enabled` on this same payload is also where "is Paper Wallet even
   * turned on" comes from — one query answers both, so no second source is
   * needed just to read a flag the first one already carries.
   */
  paperPositions: Source<PaperPositions>;
  now: number;
}

const EMPTY_STAGE: CaseStage = {
  status: "UNAVAILABLE",
  timestamp: null,
  summary: "No source has been read yet.",
  reasonCodes: [],
  sourced: false,
  stale: false,
};

function unavailable(summary: string, sourced = false): CaseStage {
  return { status: "UNAVAILABLE", timestamp: null, summary, reasonCodes: [], sourced, stale: false };
}

function unresolved(
  summary: string,
  timestamp: string | null,
  reasonCodes: string[] = [],
  stale = false,
): CaseStage {
  return { status: "UNKNOWN", timestamp, summary, reasonCodes, sourced: true, stale };
}

function pending(summary: string, timestamp: string | null = null): CaseStage {
  return { status: "PENDING", timestamp, summary, reasonCodes: [], sourced: true, stale: false };
}

function passed(
  summary: string,
  timestamp: string | null,
  reasonCodes: string[] = [],
  stale = false,
): CaseStage {
  return { status: "PASSED", timestamp, summary, reasonCodes, sourced: true, stale };
}

function failed(
  summary: string,
  timestamp: string | null,
  reasonCodes: string[] = [],
  stale = false,
): CaseStage {
  return { status: "FAILED", timestamp, summary, reasonCodes, sourced: true, stale };
}

/* ── stage derivations ──────────────────────────────────────────────── */

/**
 * RADAR — discovery.
 *
 * PASSED the moment a `RadarDetail` exists at all: `first_detected_at` is
 * written once, at discovery, and is never revised — so its mere presence on
 * the row *is* the discovery evidence. There is no PENDING for this stage:
 * either the mint has a Radar row or HQ has nothing to say about it, and
 * "pending discovery" is not a state a case file can be opened to observe.
 * Never stale — a historical fact does not expire.
 */
function deriveDiscovery(radar: RadarDetail | null): CaseStage {
  if (!radar) return unavailable("This mint has no Radar record.");
  return passed(
    radar.detection_reason.length > 0
      ? `Discovered — ${radar.detection_reason.join(", ")}.`
      : "Discovered.",
    radar.first_detected_at,
  );
}

/**
 * LUNA — scoring.
 *
 * The dimension list is only populated by `GET /radar/{mint}` when the
 * engine could re-evaluate the stored series; an entry can exist with none
 * (freshly discovered, not yet scored). That is the real PENDING case, and
 * it is distinguished from PASSED by whether the backend actually returned
 * any dimensions — never invented client-side.
 */
function deriveScoring(radar: RadarDetail | null, now: number): CaseStage {
  if (!radar) return unavailable("No Radar record to score.");
  const at = radar.last_evaluated_at;
  const stale = (ageMs(at, now) ?? 0) > STAGE_STALE_MS.scoring;

  if (radar.dimensions.length === 0) {
    return pending("Not yet scored — no dimension evaluation on record.", at);
  }
  const available = radar.dimensions.filter((d) => d.available);
  const critical = radar.reasons.filter((r) => r.severity === "critical");
  const summary =
    critical.length > 0
      ? critical[0]!.message
      : `Scored — opportunity ${radar.opportunity_score} (${available.length}/${radar.dimensions.length} dimensions available).`;
  return passed(summary, at, radar.reasons.map((r) => r.code), stale);
}

/**
 * DEX — market and liquidity FACTS ONLY.
 *
 * Deliberately never uses the word "locked" or "secure" — that is Atlas's
 * conclusion, if he has one, and Dex reporting a liquidity number is not
 * evidence about whether that liquidity is safe. See the module header.
 */
function deriveMarket(radar: RadarDetail | null, now: number): CaseStage {
  if (!radar) return unavailable("No Radar record carries market data.");
  const strip = radar.market;
  if (!strip || strip.captured_at === null) {
    return pending("No market snapshot recorded for this mint yet.");
  }
  const stale = (ageMs(strip.captured_at, now) ?? 0) > STAGE_STALE_MS.market;
  const parts: string[] = [];
  if (strip.market_cap) parts.push(`MCAP ${money(strip.market_cap)}`);
  if (strip.liquidity_usd) parts.push(`liquidity ${money(strip.liquidity_usd)}`);
  if (strip.dex_name) parts.push(`on ${strip.dex_name}`);
  return passed(
    parts.length > 0 ? parts.join(", ") + "." : "Market data recorded, no readable figures.",
    strip.captured_at,
    [],
    stale,
  );
}

/**
 * ATLAS — the shared security evaluation, and nothing inferred from anything.
 *
 * Three outcomes, never two. A token that failed a check is FAILED; a token
 * that was evaluated and could not be fully verified is UNKNOWN; a token with
 * no evaluation on record is UNAVAILABLE. None of them may be rendered as a
 * pass, and an UNKNOWN must never be described with the word "locked",
 * "secure" or "safe" — see the module header.
 */
function deriveSafety(
  security: TokenSecurityEvaluations | null,
  now: number,
): CaseStage {
  if (!security || security.items.length === 0) {
    return unavailable(
      "No shared security evaluation has been recorded for this mint.",
      security !== null,
    );
  }
  const latest = security.items[0]!;
  // The backend computes staleness against each check's own validity window
  // and publishes the verdict. HQ reads it rather than re-deriving one.
  const stale = latest.stale || (ageMs(latest.evaluated_at, now) ?? 0) > STAGE_STALE_MS.safety;

  if (latest.overall_status === "FAILED") {
    const failing = latest.checks.filter((c) => c.status === "FAIL");
    return failed(
      failing.length > 0
        ? failing.map((c) => c.detail || c.name).join(" ")
        : "Failed a security check.",
      latest.evaluated_at,
      latest.reason_codes,
      stale,
    );
  }
  if (latest.overall_status === "VERIFIED") {
    return passed(
      "Every applicable security check passed.",
      latest.evaluated_at,
      [],
      stale,
    );
  }
  const unresolvedChecks = latest.checks.filter((c) => c.status === "UNKNOWN");
  return unresolved(
    unresolvedChecks.length > 0
      ? `Could not be verified — ${unresolvedChecks
          .map((c) => c.name)
          .join(", ")} unresolved.`
      : "Could not be verified.",
    latest.evaluated_at,
    latest.reason_codes,
    stale,
  );
}

/**
 * The per-check rows for the panel. Rendered verbatim from the evaluator —
 * HQ never decides what a check means, only how to lay it out.
 */
export interface CaseSecurityCheck {
  name: string;
  status: "PASS" | "FAIL" | "UNKNOWN" | "NOT_APPLICABLE";
  detail: string;
}

/**
 * The verified custody mechanism, in the evaluator's own vocabulary.
 *
 * Rendered as prose but never *re-interpreted*: HQ maps a backend enum to a
 * phrase and stops there. Only a mechanism that came back with a PASS is
 * shown — a mechanism attached to an UNKNOWN would describe something the
 * backend explicitly declined to conclude.
 */
const MECHANISM_TEXT: Record<string, string> = {
  BONDING_CURVE_CUSTODY: "Bonding-curve custody (pump.fun)",
  PUMPSWAP_MIGRATED_LP_BURNED: "Protocol custody — migration LP burned",
};

export function liquidityMechanism(
  security: TokenSecurityEvaluations | null,
): string | null {
  const check = security?.items[0]?.checks.find((c) => c.name === "LIQUIDITY_SECURITY");
  if (!check || check.status !== "PASS") return null;
  const mechanism = check.evidence?.["mechanism"];
  if (typeof mechanism !== "string" || mechanism === "NONE") return null;
  return MECHANISM_TEXT[mechanism] ?? mechanism;
}

function securityChecks(
  security: TokenSecurityEvaluations | null,
): CaseSecurityCheck[] {
  const latest = security?.items[0];
  if (!latest) return [];
  return latest.checks.map((check) => ({
    name: check.name,
    status: check.status,
    detail: check.detail,
  }));
}

/**
 * DECISION — the engine's own verdict, read back. Never recomputed.
 *
 * HQ-5 could only ever render PASSED or PENDING here, because `judge()`'s
 * refusals were counted in aggregate and discarded per mint. HQ-6 records
 * them, so FAILED is finally sayable with the reason the engine actually
 * used.
 *
 * ORDER OF EVIDENCE, STRONGEST FIRST
 *
 * A recorded decision outranks an inferred one, *except* that an open
 * position still wins outright: opening a position **is** the decision, and
 * it is the one piece of evidence that cannot be wrong.
 *
 * THE GAP THAT REMAINS, AND WHY IT IS NOT PAPERED OVER
 *
 * Ownership refusals (`already_traded`, `already_held`) are deliberately not
 * recorded — they would be hundreds of rows a minute restating what
 * `GET /paper/positions` already answers. So an empty decision list means
 * "no non-ownership verdict on record", which is not "never considered", and
 * it is reported as such rather than as a pass.
 */
function deriveDecision(
  radar: RadarDetail | null,
  decisions: PaperDecisions | null,
  bought: boolean,
  walletEnabled: boolean | null,
): CaseStage {
  if (bought) return passed("Qualified — a Paper position was opened.", null);

  const latest = decisions?.items[0] ?? null;
  if (latest) {
    // SEC-2: a security refusal carries the canonical `security_gate` code
    // plus the evaluator's own detail codes. The detail is what a reader
    // needs — "security_gate" alone says only that a gate exists.
    const securityCodes = latest.reason_codes.filter((code) => code !== "security_gate");
    if (latest.reason_codes.includes("security_gate")) {
      // The gate's own classification decides the wording. An infrastructure
      // refusal must not read as a finding about the token (§6, §21).
      const temporary = latest.entry_outcome === "REFUSED_UNAVAILABLE";
      return failed(
        temporary
          ? "Entry temporarily refused — security could not be checked. This is not a finding about the token."
          : `Entry refused by the security gate — ${securityCodes.join(", ") || "no reason recorded"}.`,
        latest.decided_at,
        latest.reason_codes,
      );
    }
    const summary =
      latest.reason_labels[0] ??
      latest.reason_codes[0] ??
      "Recorded by the wallet's own review pass.";
    // `eligible` means §5's conditions passed. It is not a purchase: the
    // strategy may still have declined for cash, which is itself recorded
    // as a reason and shown here rather than smoothed away.
    return latest.decision === "eligible"
      ? passed(`Qualified — ${summary}`, latest.decided_at, latest.reason_codes)
      : failed(summary, latest.decided_at, latest.reason_codes);
  }

  if (walletEnabled === false) return unavailable("Paper Wallet is disabled.", true);
  if (!radar) return unavailable("No Radar record to evaluate.");
  if (radar.is_active) {
    return pending(
      "Still active on Radar with no recorded verdict and no Paper position.",
    );
  }
  return unavailable(
    "No longer active on Radar, never bought, and no verdict was recorded for it.",
    decisions !== null,
  );
}

/**
 * REX — Paper execution, strictly from the exhaustive positions record.
 *
 * BOUGHT is PASSED. Never FAILED — see the module header on why "attempted
 * and refused" cannot be attributed to one mint. Absence from the list,
 * however, is real: the endpoint is documented as "every simulated trade",
 * so a clean miss is the strongest available evidence that nothing happened.
 */
function deriveExecution(
  position: PaperPosition | null,
  walletEnabled: boolean | null,
  radar: RadarDetail | null,
): CaseStage {
  if (walletEnabled === null) return unavailable("Paper wallet could not be read.");
  if (position) {
    const closed = position.status !== "open";
    const summary = closed
      ? `Bought and closed — ${position.exit_reason ?? "exit"}${position.net_pnl_usd ? `, net ${money(position.net_pnl_usd)}` : ""}.`
      : "Bought — position open.";
    return passed(summary, position.opened_at);
  }
  if (!walletEnabled) return unavailable("Paper Wallet is disabled.", true);
  if (radar?.is_active) return pending("No execution yet — still active, could still be bought.");
  return unavailable("No Paper execution record for this mint.", true);
}

/* ── evidence rows ───────────────────────────────────────────────────── */

function buildEvidence(
  radar: RadarDetail | null,
  security: TokenSecurityEvaluations | null,
  position: PaperPosition | null,
): CaseEvidence[] {
  const rows: CaseEvidence[] = [];
  const strip: MarketStrip | null = radar?.market ?? null;

  rows.push({ label: "Opportunity score", value: radar ? radar.opportunity_score : null, source: "radar", group: "scoring" });
  rows.push({ label: "Confidence", value: radar ? radar.confidence : null, source: "radar", group: "scoring" });
  rows.push({ label: "Current MCAP", value: money(strip?.market_cap), when: "current", source: "radar.market", group: "market" });
  rows.push({
    label: "Current liquidity",
    value: money(strip?.liquidity_usd),
    when: "current",
    source: "radar.market",
    // Market depth. Deliberately in a different group from "Liquidity
    // security" below — the amount says nothing about whether it can be pulled.
    group: "market",
  });
  rows.push({ label: "24h volume", value: money(strip?.volume_24h), when: "current", source: "radar.market", group: "market" });
  rows.push({ label: "Venue", value: strip?.dex_name ?? null, source: "radar.market", group: "market" });

  // Read from the shared evaluator's own per-check verdicts rather than by
  // sniffing a reason code out of a list. A reason code is present only when
  // something is *wrong*, so its absence used to be rendered as "Not flagged"
  // — which reads as reassurance and was equally true of a token nobody had
  // looked at. The check's status distinguishes them.
  const checks = securityChecks(security);
  const statusWord: Record<string, string> = {
    PASS: "Revoked",
    FAIL: "Active",
    UNKNOWN: "Unknown",
    NOT_APPLICABLE: "Not applicable",
  };
  for (const [label, name] of [
    ["Mint authority", "MINT_AUTHORITY"],
    ["Freeze authority", "FREEZE_AUTHORITY"],
  ] as const) {
    const check = checks.find((c) => c.name === name);
    rows.push({
      label,
      value: check ? (statusWord[check.status] ?? check.status) : null,
      when: "checked",
      source: "token-security",
      group: "security",
    });
  }

  // Deliberately worded as a *security* state and never as "Locked" — see the
  // module header. The mechanism is carried on its own row rather than folded
  // into this one, because "verified" and "verified *how*" are different
  // claims and only the second one is checkable by a reader.
  const liquiditySecurity = checks.find((c) => c.name === "LIQUIDITY_SECURITY");
  rows.push({
    label: "Liquidity security",
    value: liquiditySecurity
      ? liquiditySecurity.status === "PASS"
        ? "Verified"
        : liquiditySecurity.status === "FAIL"
          ? "Failed"
          : "Unknown — not verified"
      : null,
    when: "checked",
    source: "token-security",
    group: "security",
  });
  rows.push({
    label: "Liquidity mechanism",
    value: liquidityMechanism(security),
    when: "checked",
    source: "token-security",
    group: "security",
  });

  const venue = checks.find((c) => c.name === "VENUE");
  rows.push({
    label: "Venue recognised",
    value: venue ? (venue.status === "PASS" ? "Yes" : (statusWord[venue.status] ?? venue.status)) : null,
    when: "checked",
    source: "token-security",
    group: "security",
  });

  rows.push({
    label: "Paper entry MCAP",
    value: money(num(position?.entry_market_cap)),
    when: "entry",
    source: "paper.positions",
    group: "paper",
  });
  rows.push({ label: "Paper opened", value: position?.opened_at ?? null, source: "paper.positions", group: "paper" });
  rows.push({
    label: "Paper current P/L",
    value: position ? pct(position.current_pct) : null,
    when: "current",
    source: "paper.positions",
    group: "paper",
  });

  return rows;
}

/* ── overall ─────────────────────────────────────────────────────────── */

function deriveOverall(stages: CaseStages): { state: CaseOverallState; current: keyof CaseStages } {
  // Execution first, and deliberately ahead of every judgement above it. If a
  // position exists, the token was bought — whatever Atlas concluded and
  // whatever the decision log says. That ordering is what lets a case file
  // read ATLAS FAILED / REX BOUGHT instead of quietly resolving the conflict
  // in favour of the tidier story. See the module header.
  if (stages.execution.status === "PASSED") {
    const closed = stages.execution.summary.includes("closed");
    return { state: closed ? "closed" : "bought", current: "execution" };
  }
  // Only reachable since HQ-6: before the decision log existed there was no
  // per-mint refusal to read, so nothing could ever be shown as rejected.
  if (stages.decision.status === "FAILED") return { state: "rejected", current: "decision" };
  if (stages.decision.status === "PENDING") return { state: "evaluating", current: "decision" };
  if (stages.scoring.status === "PENDING") return { state: "scoring", current: "scoring" };
  if (stages.discovery.status === "PASSED") return { state: "discovered", current: "discovery" };
  return { state: "unknown", current: "discovery" };
}

/* ── the adapter ─────────────────────────────────────────────────────── */

export function deriveCaseFile(mint: string, sources: Partial<CaseSources> = {}): TokenCaseFile {
  const s: CaseSources = {
    radar: { data: null, observedAt: null },
    safety: { data: null, observedAt: null },
    tokenSecurity: { data: null, observedAt: null },
    decisions: { data: null, observedAt: null },
    paperPositions: { data: null, observedAt: null },
    now: 0,
    ...sources,
  };

  const radar = fresh(s.radar, Infinity, s.now); // discovery/scoring/market never expire the record itself
  const security = fresh(s.tokenSecurity, STAGE_STALE_MS.safety * 4, s.now);
  // A recorded decision is a historical fact about a past pass — it does not
  // expire, and an old verdict is still the verdict that was reached.
  const decisions = fresh(s.decisions, Infinity, s.now);
  const positions = fresh(s.paperPositions, Infinity, s.now);

  const position = positions?.items.find((p) => p.mint_address === mint) ?? null;
  const walletEnabled = positions ? positions.enabled : null;

  const stages: CaseStages = {
    discovery: deriveDiscovery(radar),
    scoring: deriveScoring(radar, s.now),
    market: deriveMarket(radar, s.now),
    safety: deriveSafety(security, s.now),
    decision: deriveDecision(radar, decisions, position !== null, walletEnabled),
    execution: deriveExecution(position, walletEnabled, radar),
  };

  const { state, current } = deriveOverall(stages);
  const timestamps = [
    stages.discovery.timestamp,
    stages.scoring.timestamp,
    stages.market.timestamp,
    stages.safety.timestamp,
    stages.execution.timestamp,
  ].filter((t): t is string => t !== null);
  const lastUpdatedAt = timestamps.length > 0 ? timestamps.sort().at(-1)! : null;

  return {
    mint,
    symbol: radar?.symbol ?? position?.symbol ?? null,
    name: radar?.name ?? position?.name ?? null,
    imageUrl: radar?.image_url ?? position?.image_url ?? null,
    discoveredAt: radar?.first_detected_at ?? null,
    lastUpdatedAt,
    currentStage: current,
    overallState: state,
    stages,
    evidence: buildEvidence(radar, security, position),
  };
}

export const UNAVAILABLE_CASE_FILE_STAGES: CaseStages = {
  discovery: EMPTY_STAGE,
  scoring: EMPTY_STAGE,
  market: EMPTY_STAGE,
  safety: EMPTY_STAGE,
  decision: EMPTY_STAGE,
  execution: EMPTY_STAGE,
};
