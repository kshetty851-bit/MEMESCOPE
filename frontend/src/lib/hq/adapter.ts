import { EMPLOYEES, type EmployeeId, type EmployeeState } from "./employees";
import { EVENT_WINDOW_MS, emptyActivity, type EventActivity } from "./events";
import type {
  ExecutionPosture,
  PipelineHealth,
  TokenSecuritySummary,
} from "./pipeline";
import { OPEN_INCIDENT_STATUSES, type HqOperations, type Incident } from "./operations";
import type { KarthikState, ScreenReading } from "./karthik";
import type { PaperAudit, PaperPositions, PaperWallet } from "@/types/paper";
import type { RadarPerformance } from "@/types/radar";
import type { LiveStreamStatus } from "@/hooks/use-live-updates";

/**
 * THE HQ STATE ADAPTER.
 *
 * One pure function between MEMESCOPE's field names and the office. Everything
 * a character does, every number on a panel and the room's overall mood comes
 * out of `deriveHqState`, and nothing else in HQ is allowed to read a backend
 * field. That rule is the whole architecture: when `tracked_stale_count` gets
 * renamed, one file changes and one test suite proves the office still tells
 * the truth.
 *
 * ── THE RULE THAT OUTRANKS EVERY OTHER RULE ─────────────────────────────
 *
 * Missing, stale, failed and unrecognised all become UNKNOWN. Never idle,
 * never healthy, never success. There is no optimistic fallback anywhere in
 * this file and no `?? 0` standing in for a number nobody measured.
 *
 * This matters more here than in most places because HQ is *charming*. A room
 * full of calm cartoon people at their desks is a very persuasive way to say
 * "everything is fine", and it would say it just as convincingly with the
 * backend switched off. `fresh()` below is the single gate that stops it: a
 * source that failed, never arrived, or aged past its window returns `null`,
 * and every derivation starts by handling `null` first.
 *
 * ── WHERE THE THRESHOLDS COME FROM ──────────────────────────────────────
 *
 * Where the backend already classifies something, HQ reads its classification
 * and does no arithmetic — `scanner.status` decides whether Radar is alert or
 * not, and if the backend changes its mind about what "degraded" means, HQ
 * follows without an edit.
 *
 * Where the backend publishes a number but attaches no verdict — queue depth,
 * stale counts, event rates — HQ needs a threshold and there is nowhere honest
 * to get one from. Those live in `THRESHOLDS` below, in one block, labelled as
 * presentation-side. They decide how *animated* someone looks. They never
 * decide whether something is broken; that always comes from the backend or
 * from a count the backend published.
 *
 * ── WHAT THIS FUNCTION IS NOT ───────────────────────────────────────────
 *
 * It is not a decision-maker. No character here evaluates a token, judges a
 * position, or forms an opinion about strategy. HQ is an observability layer
 * wearing a cartoon; the moment a character's state depends on a judgement
 * MEMESCOPE did not itself publish, HQ is lying about a system people trade
 * with.
 */

/* ── sources ─────────────────────────────────────────────────────────── */

/**
 * One upstream reading, and everything needed to distrust it.
 *
 * `failed` and a null `data` are kept apart on purpose. "The request came back
 * with an error" and "nothing has been asked yet" produce the same UNKNOWN, but
 * they produce different *sentences*, and a reader deserves to know which.
 */
export interface Source<T> {
  data: T | null;
  /** Epoch ms the browser received this. `null` when nothing has arrived. */
  observedAt: number | null;
  /** The request ran and failed, as opposed to not having run. */
  failed?: boolean;
}

export const NO_SOURCE: Source<never> = { data: null, observedAt: null };

/**
 * How long a reading stays true.
 *
 * Each is several times its source's own poll interval, so a single missed
 * refetch does not blank the office, but a source that has genuinely stopped
 * arriving turns UNKNOWN rather than staying green forever. That last property
 * is the requirement; the exact numbers are a comfort setting.
 */
export const STALE_AFTER_MS = {
  /** Polled every 60s by `useHqState`. Three misses. */
  pipeline: 180_000,
  /** Paper endpoints poll at 120s. Three misses. */
  paper: 360_000,
  /** Radar performance polls at the radar cadence. */
  radar: 360_000,
  /**
   * Token security polls at 120s. Three misses.
   *
   * This is the *browser's* window on the summary request and is a separate
   * question from whether the evidence inside it is fresh — the backend
   * answers that itself in `source_state`, against each check's own
   * validity period. A summary that arrived a second ago can still be
   * reporting evidence hours old, and Atlas has to distinguish them.
   */
  tokenSecurity: 360_000,
  /** Posture polls at 120s. Three misses. */
  executionPosture: 360_000,
  /**
   * Operations polls at 45s. Four misses.
   *
   * Tighter than the rest, and deliberately so: this is the one source whose
   * whole purpose is to notice that something stopped. A stale infrastructure
   * reading is exactly the reading that must not be trusted, because the most
   * likely reason it went stale is the thing it would have reported.
   */
  operations: 180_000,
  /**
   * Karthik polls at 60s. Three misses.
   *
   * Slower than `operations` because it is not a liveness watch on the
   * platform — the infrastructure half of Karthik's health screen comes from
   * the same `hq_ops` probe, which has its own tighter window. What ages out
   * here is a wallet reading, and a wallet reading is worth the same three
   * misses every other wallet source gets.
   */
  karthik: 180_000,
} as const;

export interface HqSources {
  pipeline: Source<PipelineHealth>;
  paperWallet: Source<PaperWallet>;
  paperPositions: Source<PaperPositions>;
  paperAudit: Source<PaperAudit>;
  radarPerformance: Source<RadarPerformance>;
  /** `GET /token-security/summary`. Atlas's source. */
  tokenSecurity: Source<TokenSecuritySummary>;
  /** `GET /real-wallet-safety/execution-posture`. The Execution Vault. */
  executionPosture: Source<ExecutionPosture>;
  /** `GET /hq`. Infrastructure, incidents and the autonomous audit trail. */
  operations: Source<HqOperations>;
  /**
   * `GET /karthik`. The Karthik Paper Wallet, as its own operator reads it.
   *
   * A separate source from `paperWallet` and it must stay that way: they are
   * different wallets under different rules, and one figure crossing between
   * them would put the Original Paper Wallet's numbers on Karthik's screens.
   */
  karthik: Source<KarthikState>;
  /** Aggregated stream pressure. Never individual events. */
  activity: EventActivity;
  /**
   * The live stream's own state.
   *
   * Emphatically not a system-health signal: a browser that cannot hold a
   * socket open says nothing about whether MEMESCOPE is running. It is read by
   * exactly one employee — Byte, whose remit includes the WebSocket — and the
   * sentence he carries says the API is still answering when it is.
   */
  stream: LiveStreamStatus;
  /** Short-lived reactions to things that actually happened. */
  transients: Partial<Record<EmployeeId, Transient>>;
  /** Injected, so every derivation is a pure function of its inputs. */
  now: number;
}

/* ── output ──────────────────────────────────────────────────────────── */

export type OfficeActivity = "QUIET" | "NORMAL" | "BUSY" | "HIGH_ALERT" | "UNKNOWN";

/**
 * One line on an employee panel.
 *
 * A `null` value renders NOT AVAILABLE and never a dash that could be read as
 * zero. `source` names where the figure came from so a reader can go and check
 * it, which is the difference between a dashboard and a decoration.
 */
export interface Metric {
  label: string;
  value: string | null;
  source: string;
}

export interface EmployeeReading {
  state: EmployeeState;
  /** Why it reads that way, in one sentence. Always present. */
  detail: string;
  /** Present only while a real reaction is live. Drawn as a speech bubble. */
  speech?: string;
  metrics: Metric[];
  /** Epoch ms of the observation behind this reading. */
  observedAt: number | null;
  /**
   * Whether HQ has a source for this person at all.
   *
   * False for Atlas, whose aggregate safety data does not exist in any
   * endpoint. Both he and a failed Radar read UNKNOWN, but only one of them is
   * an incident, and Nova must not spend every day reporting a gap that is
   * already written down as a gap.
   */
  sourced: boolean;
}

export interface Transient {
  state: EmployeeState;
  detail: string;
  /** Epoch ms after which this reaction is over. */
  until: number;
  /**
   * A short line for a speech bubble over this person's head.
   *
   * Only a *reaction* carries one, never an ambient routine, and that is the
   * whole distinction: this fires because the adapter watched a number change,
   * so the sentence is traceable to an observation. Ambient chatter says
   * nothing about the system for exactly the opposite reason — see
   * `chatter.ts`.
   */
  speech?: string;
}

export interface HqState {
  employees: Record<EmployeeId, EmployeeReading>;
  activity: OfficeActivity;
  /**
   * Who is doing real work, and therefore whose ambient personality yields.
   *
   * The plan's priority order — alert/error, then real activity, then normal,
   * then ambient — is enforced by this list plus the scheduler that reads it.
   * Ambient is the only layer that can be interrupted, and it always is.
   */
  operational: EmployeeId[];
  /**
   * The raw readings, carried through unchanged.
   *
   * The boards need them because a board renders a *source* rather than an
   * employee — the Execution Vault has no desk and the Performance Lab shows
   * figures no character owns. They get the same `Source` wrapper everything
   * else does, so `fresh()` is still the single gate deciding what counts as
   * current, and a board cannot accidentally read past a stale window that
   * the room respects.
   */
  sources: HqSources;
  /** The clock the derivation used, so boards age their sources identically. */
  now: number;
}

/**
 * The strategy ids whose entries require a passing security evaluation.
 *
 * Compared against what `GET /paper` reports rather than assumed, so HQ says
 * "not enforced" on a deployment that has not cut over instead of describing
 * a gate that is not running.
 *
 * **A set, not one id, because the gate outlives any single generation.** This
 * was a lone string, and the HOLD-6H cutover made it stale the moment it
 * landed: the gate was strict and enforcing, and HQ reported "NOT ENFORCED"
 * because the id beside it had moved on. A gate that reports itself off while
 * it is on is worse than no board at all, and the failure repeats at every
 * cutover unless the successor can be added here.
 *
 * Mirrors the backend's `SECURITY_GATED_STRATEGY_IDS`. A retired generation
 * stays listed: it is still gated, and its wallet must not read as looser
 * after retirement than it was while live.
 */
export const SECURED_STRATEGY_IDS: ReadonlySet<string> = new Set([
  "trailing_stop_25_secured_v2",
  "trailing_stop_25_secured_hold6h_v3",
]);

/** Whether the strategy the backend reports enforces the entry gate. */
export function isSecurityGated(strategyId: string | null | undefined): boolean {
  return strategyId != null && SECURED_STRATEGY_IDS.has(strategyId);
}

/* ── thresholds ──────────────────────────────────────────────────────── */

/**
 * Presentation thresholds. Read the module header before adding one.
 *
 * Every value here answers "how animated should this person look", never "is
 * something wrong". The one exception is documented at its use site: Echo's
 * priority-lane alert mirrors the backend's own `HEALTH_TRACKED_STALE_SECONDS`
 * default, because a priority lane that has kept a tracked token waiting longer
 * than the backend's own staleness limit has failed at the one job the lane
 * exists to do. That constant is not published to the frontend, so it is
 * duplicated here and listed as a known gap.
 */
export const THRESHOLDS = {
  /** Arrivals per minute at which a desk reads as saturated rather than busy. */
  busyDiscovery: 12,
  busyMarket: 30,
  busyScore: 20,
  busyPaper: 6,
  /**
   * Distinct mints security-evaluated in the summary window before Atlas
   * reads as saturated rather than merely working. Presentation only: the
   * evaluator is capped at `TOKEN_SECURITY_MAX_PER_PASS` (25) per review
   * pass, so a sustained busy window is genuinely a lot of new candidates.
   */
  busyAtlas: 40,
  /** Unscored tokens that turn a scoring backlog into a busy analyst. */
  scoringBacklogBusy: 25,
  /** Seconds the oldest overdue normal-lane item has waited before "busy". */
  enrichmentWaitBusySeconds: 60,
  /** Mirrors the backend default for `HEALTH_TRACKED_STALE_SECONDS`. */
  priorityWaitAlertSeconds: 300,
  /** How long a reaction to a real event lasts. */
  reactionMs: 6_000,
} as const;

/* ── the gate ────────────────────────────────────────────────────────── */

/**
 * A source's data, or `null` if it cannot be trusted.
 *
 * The only way anything in this file reads an upstream value. Four ways to
 * fail, one return.
 */
export function fresh<T>(source: Source<T>, staleAfter: number, now: number): T | null {
  if (source.failed) return null;
  if (source.data === null || source.data === undefined) return null;
  if (source.observedAt === null) return null;
  if (now - source.observedAt > staleAfter) return null;
  return source.data;
}

/** Why a source is not readable, as a sentence. */
function absence(source: Source<unknown>, staleAfter: number, now: number, what: string): string {
  if (source.failed) return `${what} could not be read.`;
  if (source.data === null || source.observedAt === null) return `${what} has not been read yet.`;
  if (now - source.observedAt > staleAfter) {
    const age = Math.round((now - source.observedAt) / 1000);
    return `${what} is ${age}s old and no longer describes now.`;
  }
  return `${what} is unavailable.`;
}

function unknown(detail: string, metrics: Metric[] = [], sourced = true): EmployeeReading {
  return { state: "unknown", detail, metrics, observedAt: null, sourced };
}

function reading(
  state: EmployeeState,
  detail: string,
  metrics: Metric[],
  observedAt: number | null,
): EmployeeReading {
  return { state, detail, metrics, observedAt, sourced: true };
}

/** A metric whose backing data does not exist. Renders NOT AVAILABLE. */
function missing(label: string, source: string): Metric {
  return { label, value: null, source };
}

function num(value: number | null | undefined): string | null {
  return value === null || value === undefined ? null : String(value);
}

function seconds(value: number | null | undefined): string | null {
  return value === null || value === undefined ? null : `${Math.round(value)}s`;
}

function minutes(value: number | null | undefined): string | null {
  return value === null || value === undefined ? null : `${value.toFixed(1)} min`;
}

/** Events observed in the window, or `null` while the meter is still filling. */
function rate(activity: EventActivity, kind: keyof EventActivity["counts"]): number | null {
  const count = activity.counts[kind];
  if (count > 0) return count;
  return activity.settled ? 0 : null;
}

/* ── the adapter ─────────────────────────────────────────────────────── */

export function deriveHqState(sources: Partial<HqSources> = {}): HqState {
  const s: HqSources = {
    pipeline: NO_SOURCE,
    paperWallet: NO_SOURCE,
    paperPositions: NO_SOURCE,
    paperAudit: NO_SOURCE,
    radarPerformance: NO_SOURCE,
    tokenSecurity: NO_SOURCE,
    executionPosture: NO_SOURCE,
    operations: NO_SOURCE,
    karthik: NO_SOURCE,
    activity: emptyActivity(EVENT_WINDOW_MS),
    stream: "offline",
    transients: {},
    now: 0,
    ...sources,
  };

  const pipeline = fresh(s.pipeline, STALE_AFTER_MS.pipeline, s.now);
  const pipelineGone = absence(s.pipeline, STALE_AFTER_MS.pipeline, s.now, "Pipeline health");
  const pipelineAt = pipeline ? s.pipeline.observedAt : null;

  const operations = fresh(s.operations, STALE_AFTER_MS.operations, s.now);
  const operationsGone = absence(s.operations, STALE_AFTER_MS.operations, s.now, "Operations");
  const operationsAt = operations ? s.operations.observedAt : null;

  const karthik = fresh(s.karthik, STALE_AFTER_MS.karthik, s.now);
  const karthikGone = absence(s.karthik, STALE_AFTER_MS.karthik, s.now, "Karthik");
  const karthikAt = karthik ? s.karthik.observedAt : null;

  const employees = {
    radar: deriveRadar(s, pipeline, pipelineGone, pipelineAt),
    luna: deriveLuna(s, pipeline, pipelineGone, pipelineAt),
    dex: deriveDex(s, pipeline, pipelineGone, pipelineAt),
    atlas: deriveAtlas(s),
    milo: deriveMilo(s),
    rex: deriveRex(s),
    echo: deriveEcho(pipeline, pipelineGone, pipelineAt),
    byte: deriveByte(s, pipeline, pipelineGone, pipelineAt),
    sage: deriveSage(s),
    sentinel: deriveSentinel(operations, operationsGone, operationsAt),
    patch: derivePatch(operations, operationsGone, operationsAt),
    quinn: deriveQuinn(operations, operationsGone, operationsAt),
    vault: deriveVault(s),
    karthik: deriveKarthik(karthik, karthikGone, karthikAt),
    // Filled in below: Nova reads the others rather than the backend.
    nova: unknown("Waiting on the rest of the office."),
  } as Record<EmployeeId, EmployeeReading>;

  // Reactions apply last, and only over a base state that is not already
  // reporting a problem. A trade closing is not more important than the market
  // desk being down, and a celebration painted over an alert would be the
  // exact failure this whole layer exists to prevent.
  for (const [id, transient] of Object.entries(s.transients) as Array<
    [EmployeeId, Transient | undefined]
  >) {
    if (!transient || s.now >= transient.until) continue;
    const base = employees[id];
    if (!base.sourced) continue;
    if (OUTRANKS_REACTION.has(base.state)) continue;
    employees[id] = {
      ...base,
      state: transient.state,
      detail: transient.detail,
      // Carried onto the reading so the stage can draw it without reaching
      // back into `sources.transients` and re-deciding whether it expired.
      // One place decides what is live; everything downstream renders it.
      speech: transient.speech,
    };
  }

  employees.nova = deriveNova(employees, pipeline, pipelineGone, pipelineAt);

  return {
    employees,
    activity: deriveActivity(employees, pipeline),
    operational: EMPLOYEES.map((employee) => employee.id).filter((id) =>
      OPERATIONAL_STATES.has(employees[id].state),
    ),
    sources: s,
    now: s.now,
  };
}

/**
 * States a transient reaction may not paint over.
 *
 * Also the states that are themselves worth interrupting ambient personality
 * for, minus the transient ones — which is not a coincidence: both lists are
 * "this is a real problem" and "this is a real event", in that order.
 */
const OUTRANKS_REACTION = new Set<EmployeeState>(["alert", "error", "offline", "unknown"]);

/** Real activity. Ambient personality yields to all of it. */
export const OPERATIONAL_STATES = new Set<EmployeeState>([
  "working",
  "busy",
  "reviewing",
  "success",
  "alert",
  "error",
  "offline",
]);

/* ── per-employee ────────────────────────────────────────────────────── */

function deriveRadar(
  s: HqSources,
  pipeline: PipelineHealth | null,
  gone: string,
  at: number | null,
): EmployeeReading {
  if (!pipeline) return unknown(gone, radarMetrics(null, s.activity));
  const scanner = pipeline.scanner;
  const metrics = radarMetrics(pipeline, s.activity);

  if (scanner.status === "down") {
    return reading(
      "offline",
      scanner.failure_reason ?? "The scanner has published no state.",
      metrics,
      at,
    );
  }
  if (scanner.status === "degraded") {
    return reading(
      "alert",
      scanner.failure_reason ??
        `Scanner degraded — ${minutes(scanner.minutes_since_last_token) ?? "no token"} since the last discovery.`,
      metrics,
      at,
    );
  }

  const discoveries = rate(s.activity, "discovery");
  if (discoveries !== null && discoveries >= THRESHOLDS.busyDiscovery) {
    return reading("busy", `${discoveries} discoveries in the last minute.`, metrics, at);
  }
  // The backend's own "how long since the last token" rather than HQ's event
  // window: it is true from the first render, where an empty window is not.
  const since = scanner.minutes_since_last_token;
  if (since !== null && since < 1) {
    return reading("working", "A token was discovered in the last minute.", metrics, at);
  }
  if (discoveries !== null && discoveries > 0) {
    return reading("working", `${discoveries} discoveries in the last minute.`, metrics, at);
  }
  return reading(
    "idle",
    since === null
      ? "Scanner healthy. No discovery time reported."
      : `Scanner healthy. Last discovery ${minutes(since)} ago.`,
    metrics,
    at,
  );
}

function radarMetrics(pipeline: PipelineHealth | null, activity: EventActivity): Metric[] {
  const scanner = pipeline?.scanner;
  const discoveries = rate(activity, "discovery");
  return [
    { label: "Scanner stage", value: scanner?.status ?? null, source: "health/pipeline.scanner" },
    {
      label: "Since last discovery",
      value: minutes(scanner?.minutes_since_last_token),
      source: "health/pipeline.scanner",
    },
    {
      label: "Discovered in the last minute",
      value: num(discoveries),
      source: "live stream · token.discovered",
    },
    {
      label: "Reconnect attempts",
      value: num(scanner?.reconnect_attempts),
      source: "health/pipeline.scanner",
    },
  ];
}

function deriveLuna(
  s: HqSources,
  pipeline: PipelineHealth | null,
  gone: string,
  at: number | null,
): EmployeeReading {
  if (!pipeline) return unknown(gone, lunaMetrics(null, s.activity));
  const scoring = pipeline.scoring;
  const metrics = lunaMetrics(pipeline, s.activity);

  if (scoring.status === "down") {
    return reading("offline", "Scoring has produced nothing for long enough to read as down.", metrics, at);
  }
  if (scoring.status === "degraded") {
    return reading(
      "alert",
      `Scoring degraded — last score ${minutes(scoring.minutes_since_last_score) ?? "not reported"} ago.`,
      metrics,
      at,
    );
  }

  const scores = rate(s.activity, "score");
  if (
    (scores !== null && scores >= THRESHOLDS.busyScore) ||
    scoring.pending >= THRESHOLDS.scoringBacklogBusy
  ) {
    return reading(
      "busy",
      scores === null
        ? `${scoring.pending} tokens are awaiting a score.`
        : `${scoring.pending} tokens awaiting a score; ${scores} rescored in the last minute.`,
      metrics,
      at,
    );
  }
  if (scores !== null && scores > 0) {
    return reading("working", `${scores} scores changed in the last minute.`, metrics, at);
  }
  if (scoring.pending > 0) {
    // Work is queued but nothing has been scored in the window. Reviewing, not
    // working: something is in front of her that has not produced an answer.
    return reading("reviewing", `${scoring.pending} tokens are awaiting a score.`, metrics, at);
  }
  return reading("idle", "Scoring healthy with nothing queued.", metrics, at);
}

function lunaMetrics(pipeline: PipelineHealth | null, activity: EventActivity): Metric[] {
  const scoring = pipeline?.scoring;
  return [
    { label: "Scoring stage", value: scoring?.status ?? null, source: "health/pipeline.scoring" },
    { label: "Awaiting a score", value: num(scoring?.pending), source: "health/pipeline.scoring" },
    {
      label: "Since last score",
      value: minutes(scoring?.minutes_since_last_score),
      source: "health/pipeline.scoring",
    },
    {
      label: "Scores changed in the last minute",
      value: num(rate(activity, "score")),
      source: "live stream · score.changed",
    },
  ];
}

function deriveDex(
  s: HqSources,
  pipeline: PipelineHealth | null,
  gone: string,
  at: number | null,
): EmployeeReading {
  if (!pipeline) return unknown(gone, dexMetrics(null, s.activity));
  const market = pipeline.market_enrichment;
  const metrics = dexMetrics(pipeline, s.activity);

  if (market.status === "down") {
    return reading("offline", "Market enrichment has committed nothing for long enough to read as down.", metrics, at);
  }
  if (market.status === "degraded") {
    return reading(
      "alert",
      `Market enrichment degraded — last snapshot ${minutes(market.minutes_since_last_snapshot) ?? "not reported"} ago.`,
      metrics,
      at,
    );
  }
  // The stage can report healthy while the tokens on screen carry hour-old
  // prices: the backend classifies this stage purely on when *anything* last
  // landed, and publishes the stale count separately without letting it
  // degrade the status. A stale quote must never look healthy, so HQ reads the
  // count the backend already measured rather than inventing its own staleness.
  if (market.tracked_stale_count > 0) {
    return reading(
      "alert",
      `${market.tracked_stale_count} tracked tokens carry stale market data, worst ${seconds(market.tracked_freshness_worst_seconds) ?? "unknown"} old.`,
      metrics,
      at,
    );
  }

  const updates = rate(s.activity, "market");
  if (updates !== null && updates >= THRESHOLDS.busyMarket) {
    return reading("busy", `${updates} market updates in the last minute.`, metrics, at);
  }
  if (updates !== null && updates > 0) {
    return reading("working", `${updates} market updates in the last minute.`, metrics, at);
  }
  return reading("idle", "Market data fresh, nothing moving.", metrics, at);
}

function dexMetrics(pipeline: PipelineHealth | null, activity: EventActivity): Metric[] {
  const market = pipeline?.market_enrichment;
  return [
    {
      label: "Market stage",
      value: market?.status ?? null,
      source: "health/pipeline.market_enrichment",
    },
    {
      label: "Stale tracked tokens",
      value: num(market?.tracked_stale_count),
      source: "health/pipeline.market_enrichment",
    },
    {
      label: "Worst tracked freshness",
      value: seconds(market?.tracked_freshness_worst_seconds),
      source: "health/pipeline.market_enrichment",
    },
    {
      label: "Market updates in the last minute",
      value: num(rate(activity, "market")),
      source: "live stream · market.changed",
    },
  ];
}

/**
 * ATLAS — sourced, as of HQ-6.
 *
 * He was the one member of staff MEMESCOPE could not describe. There was no
 * aggregate of what had been reviewed, refused, or why, and the only per-mint
 * safety rows in the platform were written by the Real Wallet's dry-run
 * preview — so with the wallet disabled, the risk officer's entire department
 * was invisible. `GET /token-security/summary` is now a real source that does
 * not care whether any wallet is enabled.
 *
 * THE ONE THING THIS FUNCTION MUST NEVER DO
 *
 * Read zero failures as good news. `verified=0, failed=0, unknown=0` is the
 * response of a platform that has evaluated **nothing**, and it is
 * byte-identical to what a perfectly clean platform would report on the
 * counts alone. `source_state` is the field that separates them and it is
 * checked first, before any count is looked at. Atlas is never green because
 * his endpoint was empty, and never green because it failed.
 *
 * WHY UNKNOWN IS NOT AN ALERT
 *
 * `unknown_count` is high by construction in this phase — liquidity security
 * is genuinely unverified for every venue the platform trades (see
 * `app/security/evaluator.py`). That is a known, written-down gap in
 * observability, not an incident, so it does not raise him to `alert`. Only
 * a positively detected dangerous token does.
 */
function deriveAtlas(s: HqSources): EmployeeReading {
  const summary = fresh(s.tokenSecurity, STALE_AFTER_MS.tokenSecurity, s.now);
  if (!summary) {
    return unknown(
      absence(s.tokenSecurity, STALE_AFTER_MS.tokenSecurity, s.now, "Token security"),
      [
        missing("Reviewed (24h)", "token-security · summary"),
        missing("Verified", "token-security · summary"),
        missing("Rejected", "token-security · summary"),
        missing("Unknown", "token-security · summary"),
      ],
      // The endpoint exists now, so a failure to read it is a real incident
      // rather than the documented gap it used to be.
      true,
    );
  }

  const topReason = Object.entries(summary.failures_by_reason).sort(
    (a, b) => b[1] - a[1],
  )[0];
  const metrics: Metric[] = [
    {
      label: "Reviewed (24h)",
      value: num(summary.evaluated_recently),
      source: "token-security · summary",
    },
    { label: "Verified", value: num(summary.verified_count), source: "token-security · summary" },
    { label: "Rejected", value: num(summary.failed_count), source: "token-security · summary" },
    { label: "Unknown", value: num(summary.unknown_count), source: "token-security · summary" },
    {
      label: "Top rejection reason",
      value: topReason ? `${topReason[0]} (${topReason[1]})` : null,
      source: "token-security · summary",
    },
    {
      label: "Last evaluation",
      value: summary.last_evaluation_at,
      source: "token-security · summary",
    },
  ];

  // Checked before any count, and in this order on purpose.
  if (summary.source_state === "no_evaluations") {
    return unknown(
      "No token has been security-evaluated yet. Zero failures here means nothing has been checked, not that nothing is wrong.",
      metrics,
    );
  }
  if (summary.source_state === "stale") {
    return unknown(
      "The newest security evidence is older than its own validity window, so it no longer describes now.",
      metrics,
    );
  }

  const at = s.tokenSecurity.observedAt;
  if (summary.failed_count > 0) {
    return reading(
      "alert",
      `${summary.failed_count} of ${summary.evaluated_recently} tokens failed a security check${
        topReason ? ` — most often ${topReason[0]}` : ""
      }.`,
      metrics,
      at,
    );
  }
  if (summary.evaluated_recently >= THRESHOLDS.busyAtlas) {
    return reading(
      "busy",
      `${summary.evaluated_recently} tokens reviewed in the last ${summary.window_hours}h; none positively unsafe.`,
      metrics,
      at,
    );
  }
  if (summary.evaluated_recently === 0) {
    // The source is live and healthy and genuinely has nothing to report.
    // This is the only path to `idle`, and it requires a working endpoint.
    return reading("idle", "Nothing new to review in the window.", metrics, at);
  }
  return reading(
    "working",
    `${summary.evaluated_recently} tokens reviewed; ${summary.unknown_count} could not be fully verified.`,
    metrics,
    at,
  );
}

function deriveMilo(s: HqSources): EmployeeReading {
  const wallet = fresh(s.paperWallet, STALE_AFTER_MS.paper, s.now);
  const positions = fresh(s.paperPositions, STALE_AFTER_MS.paper, s.now);
  const metrics = miloMetrics(wallet, positions, s.activity);
  const at = wallet ? s.paperWallet.observedAt : s.paperPositions.observedAt;

  if (!wallet && !positions) {
    return unknown(absence(s.paperWallet, STALE_AFTER_MS.paper, s.now, "Paper wallet"), metrics);
  }
  if (wallet && !wallet.enabled) {
    return reading("offline", "Paper wallet is disabled.", metrics, at);
  }

  const open = wallet?.metrics.open_positions ?? positions?.items.length ?? null;
  if (open === null) return unknown("Open position count unavailable.", metrics);

  const changes = rate(s.activity, "paper");
  if (changes !== null && changes >= THRESHOLDS.busyPaper) {
    return reading("busy", `${open} open positions; ${changes} wallet changes in the last minute.`, metrics, at);
  }
  if (open > 0) {
    // Positions exist, so there is a portfolio to watch. Nothing here decides
    // whether any of them is stagnant — holding-period judgement belongs to the
    // strategy, and HQ will consume it when it publishes one.
    return reading("working", `${open} open positions.`, metrics, at);
  }
  return reading("idle", "No open positions.", metrics, at);
}

function miloMetrics(
  wallet: PaperWallet | null,
  positions: PaperPositions | null,
  activity: EventActivity,
): Metric[] {
  const m = wallet?.metrics;
  return [
    {
      label: "Open positions",
      value: num(m?.open_positions ?? positions?.items.length),
      source: "paper.metrics",
    },
    { label: "Invested", value: m?.invested_usd ?? null, source: "paper.metrics" },
    { label: "Open value", value: m?.open_value ?? null, source: "paper.metrics" },
    { label: "Unpriced positions", value: num(m?.unpriced_positions), source: "paper.metrics" },
    {
      label: "Generation",
      value: wallet ? `Gen ${wallet.generation}` : null,
      source: "paper.generation",
    },
    {
      // Read from the strategy the backend says is running, never from a
      // build-time constant: HQ must report the generation that is actually
      // trading, including on a deployment that has not cut over.
      label: "Entry security gate",
      value: wallet
        ? isSecurityGated(wallet.strategy?.id)
          ? "Strict"
          : "Not enforced"
        : null,
      source: "paper.strategy",
    },
    {
      label: "Wallet changes in the last minute",
      value: num(rate(activity, "paper")),
      source: "live stream · paper.changed",
    },
  ];
}

/**
 * REX — paper execution, and only paper.
 *
 * His desk is the simulator. `real_wallet.changed` is not read here, is not in
 * the event table, and has a test of its own: the distance between a simulated
 * fill and a real one is the most important thing this product communicates,
 * and a character who moves on both would erase it.
 *
 * He is idle by default and reacts only to evidence — a row appearing in the
 * permanent trade record, or an open position count that went up. Neither is an
 * event announcement; both are the data itself having changed.
 */
function deriveRex(s: HqSources): EmployeeReading {
  const wallet = fresh(s.paperWallet, STALE_AFTER_MS.paper, s.now);
  const audit = fresh(s.paperAudit, STALE_AFTER_MS.paper, s.now);
  const metrics = rexMetrics(wallet, audit);
  const at = s.paperWallet.observedAt;

  if (!wallet) {
    return unknown(absence(s.paperWallet, STALE_AFTER_MS.paper, s.now, "Paper wallet"), metrics);
  }
  if (!wallet.enabled) return reading("offline", "Paper wallet is disabled.", metrics, at);

  return reading("idle", "No paper execution recorded just now.", metrics, at);
}

function rexMetrics(wallet: PaperWallet | null, audit: PaperAudit | null): Metric[] {
  const m = wallet?.metrics;
  const last = audit?.items[0];
  return [
    // Fixed, and first. Everything else on this panel is about a simulator, and
    // the panel has to say so before it says anything else.
    { label: "Desk", value: "Paper — simulated execution", source: "HQ" },
    { label: "Closed positions", value: num(m?.closed_positions), source: "paper.metrics" },
    { label: "Realised P&L", value: m?.realised_pnl ?? null, source: "paper.metrics" },
    { label: "Last close", value: last?.exit_reason ?? null, source: "paper/audit" },
    { label: "Last close net", value: last?.net_return_usd ?? null, source: "paper/audit" },
  ];
}

function deriveEcho(
  pipeline: PipelineHealth | null,
  gone: string,
  at: number | null,
): EmployeeReading {
  if (!pipeline) return unknown(gone, echoMetrics(null));
  const market = pipeline.market_enrichment;
  const metrics = echoMetrics(pipeline);

  if (market.status === "down") {
    return reading("offline", "The enrichment stage is down; queues cannot be worked.", metrics, at);
  }
  if (market.dead_lettered > 0) {
    return reading("alert", `${market.dead_lettered} tokens are parked in the dead-letter set.`, metrics, at);
  }
  const priorityWait = market.oldest_priority_wait_seconds;
  if (priorityWait !== null && priorityWait >= THRESHOLDS.priorityWaitAlertSeconds) {
    return reading(
      "alert",
      `The priority lane has kept a token waiting ${seconds(priorityWait)}, past the backend's own staleness limit.`,
      metrics,
      at,
    );
  }
  if (market.status === "degraded") {
    return reading("alert", "Enrichment is degraded.", metrics, at);
  }

  const normalWait = market.oldest_normal_wait_seconds;
  if (
    market.queue_depth > 0 &&
    normalWait !== null &&
    normalWait >= THRESHOLDS.enrichmentWaitBusySeconds
  ) {
    return reading(
      "busy",
      `${market.queue_depth} tokens due, oldest waiting ${seconds(normalWait)}.`,
      metrics,
      at,
    );
  }
  if (market.queue_depth > 0) {
    return reading("working", `${market.queue_depth} tokens due for refresh.`, metrics, at);
  }
  return reading("idle", "Queues clear.", metrics, at);
}

function echoMetrics(pipeline: PipelineHealth | null): Metric[] {
  const market = pipeline?.market_enrichment;
  return [
    { label: "Queue depth", value: num(market?.queue_depth), source: "health/pipeline.market_enrichment" },
    {
      label: "Priority queue depth",
      value: num(market?.priority_queue_depth),
      source: "health/pipeline.market_enrichment",
    },
    { label: "Dead-lettered", value: num(market?.dead_lettered), source: "health/pipeline.market_enrichment" },
    {
      label: "Oldest priority wait",
      value: seconds(market?.oldest_priority_wait_seconds),
      source: "health/pipeline.market_enrichment",
    },
    {
      label: "Oldest normal wait",
      value: seconds(market?.oldest_normal_wait_seconds),
      source: "health/pipeline.market_enrichment",
    },
    missing("Worker pool", "not available — no worker introspection endpoint"),
  ];
}

/**
 * BYTE — what infrastructure truth actually exists.
 *
 * Two facts, both real: the API answered (the pipeline query returned), and
 * whether this browser is holding the event stream open. Database latency,
 * cache latency, RPC health and worker liveness are not published by any
 * endpoint, so they read NOT AVAILABLE rather than being inferred from
 * something adjacent.
 *
 * A dropped socket is Byte's alert and nobody else's, and his sentence says
 * the API is still answering — because a browser that cannot hold a WebSocket
 * open is not evidence that MEMESCOPE is down, and an office that treats those
 * as the same thing will cry wolf on every train tunnel.
 */
function deriveByte(
  s: HqSources,
  pipeline: PipelineHealth | null,
  gone: string,
  at: number | null,
): EmployeeReading {
  const metrics = byteMetrics(pipeline, s.stream);
  if (!pipeline) return unknown(gone, metrics);

  if (s.stream === "offline" || s.stream === "reconnecting") {
    return reading(
      "alert",
      `Live event stream ${s.stream}. The backend API is still answering; screens fall back to polling.`,
      metrics,
      at,
    );
  }
  return reading("idle", "API answering and the event stream is live.", metrics, at);
}

function byteMetrics(pipeline: PipelineHealth | null, stream: LiveStreamStatus): Metric[] {
  return [
    { label: "Live event stream", value: stream, source: "browser WebSocket" },
    {
      label: "API",
      value: pipeline ? "Answering" : null,
      source: "health/pipeline",
    },
    { label: "Environment", value: pipeline?.environment ?? null, source: "health/pipeline" },
    { label: "Version", value: pipeline?.version ?? null, source: "health/pipeline" },
    missing("Database latency", "not available — not published by /health/pipeline"),
    missing("Cache latency", "not available — not published by /health/pipeline"),
    missing("RPC health", "not available — Real Wallet scope"),
  ];
}

/* ── the reliability trio ─────────────────────────────────────────────
 *
 * These three read one source between them — `GET /hq` — and each takes the
 * slice of it their job actually covers. Sentinel reads component health,
 * Patch reads open incidents, Quinn reads what was verified.
 *
 * THE RULE THAT SHAPES ALL THREE
 *
 * None of them may look busy without a record behind it. Patch is
 * INVESTIGATING only while an incident row is open and assigned; Quinn is
 * VERIFYING only while an action carries a verification. The brief's §27 is
 * explicit and it is the reason this file exists: an animation implying Patch
 * repaired something Patch did not repair is the one failure this product
 * cannot survive.
 */

/** Open work, in the order a person would want it. */
function openIncidents(operations: HqOperations | null): Incident[] {
  if (!operations) return [];
  return operations.incidents.filter((incident) =>
    OPEN_INCIDENT_STATUSES.has(incident.status),
  );
}

function componentSummary(operations: HqOperations): string {
  const health = operations.health;
  const rows: Array<[string, string]> = [
    ["disk", health.disk.status],
    ["broker", health.redis.status],
    ["database", health.database.status],
    ["worker", health.worker.status],
    ["scheduler", health.scheduler.status],
    ["queues", health.queues.status],
  ];
  const bad = rows.filter(([, status]) => status === "down" || status === "degraded");
  if (bad.length === 0) return "All six components answered.";
  return bad.map(([name, status]) => `${name} ${status}`).join(", ");
}

function sentinelMetrics(operations: HqOperations | null): Metric[] {
  if (!operations) {
    return [
      missing("Disk", "not available — /hq did not answer"),
      missing("Broker", "not available — /hq did not answer"),
      missing("Database", "not available — /hq did not answer"),
      missing("Worker", "not available — /hq did not answer"),
      missing("Scheduler", "not available — /hq did not answer"),
      missing("Queue depth", "not available — /hq did not answer"),
    ];
  }
  const health = operations.health;
  return [
    {
      label: "Disk",
      value: health.disk.percent_used === null ? null : `${health.disk.percent_used}%`,
      source: "hq/operations",
    },
    {
      label: "Broker",
      value: health.redis.measured
        ? `${health.redis.status}${health.redis.latency_ms === null ? "" : ` · ${health.redis.latency_ms}ms`}`
        : null,
      source: "hq/operations",
    },
    {
      label: "Database",
      value: health.database.measured
        ? `${health.database.status}${health.database.latency_ms === null ? "" : ` · ${health.database.latency_ms}ms`}`
        : null,
      source: "hq/operations",
    },
    {
      label: "Workers answering",
      value: health.worker.measured ? String(health.worker.replies) : null,
      source: "hq/operations",
    },
    {
      label: "Last scheduler beat",
      value:
        health.scheduler.seconds_since_beat === null
          ? null
          : `${Math.round(health.scheduler.seconds_since_beat)}s ago`,
      source: "hq/operations",
    },
    {
      label: "Queue depth",
      value: health.queues.total === null ? null : String(health.queues.total),
      source: "hq/operations",
    },
  ];
}

/**
 * The Execution Vault's occupant.
 *
 * The room has had a footprint, a label and a source since HQ-1 and nobody in
 * it — correctly, while mainnet submission was refused by two code constants
 * and there was nothing to watch. Those were reviewed and turned off and the
 * wallet is funded, so the one room that can spend real money now has an
 * occupant.
 *
 * WHAT HE READS, AND WHAT HE REFUSES TO SAY
 *
 * `execution-posture` is the only source. It reports whether submission is
 * possible and which kill switches are armed — it does NOT report balances,
 * intents or trades, so this reading does not either. A custodian who appeared
 * to be watching positions he cannot see would be the exact failure the roster
 * file warns about.
 *
 * The tone is inverted against every other desk on purpose. Elsewhere "enabled"
 * is healthy; here a sealed vault is the good state and an open one is merely
 * *expected* once the operator has deliberately opened it. He never says
 * "healthy" about a wallet that can spend — he says what is true and lets the
 * reader decide whether that is what they intended.
 */
function deriveVault(s: HqSources): EmployeeReading {
  const posture = fresh(s.executionPosture, STALE_AFTER_MS.executionPosture, s.now);
  const metrics = vaultMetrics(posture);
  const at = s.executionPosture.observedAt;

  if (!posture) {
    return unknown(
      absence(s.executionPosture, STALE_AFTER_MS.executionPosture, s.now, "Execution posture"),
      metrics,
    );
  }

  const armed = posture.kill_switches?.filter((row) => row.active) ?? [];
  if (armed.length > 0) {
    // The loudest thing this desk can say. A kill switch is not a warning about
    // something that might happen; it is a barrier that has already fired.
    return reading(
      "error",
      `Kill switch armed: ${armed.map((row) => row.kind).join(", ")}. Nothing can be submitted.`,
      metrics,
      at,
    );
  }

  // The four real postures, each said plainly. Note that none of them is
  // `success`: this desk never congratulates a wallet for being able to spend.
  switch (posture.state) {
    case "HALTED":
      return reading(
        "error",
        posture.detail || "Execution halted. Nothing can be submitted.",
        metrics,
        at,
      );
    case "LOCKED":
      // The good state, and the quiet one. A sealed vault is the resting
      // posture this room was designed around.
      return reading(
        "idle",
        posture.detail || "Vault locked. No submission is possible.",
        metrics,
        at,
      );
    case "ARMED":
      // Every precondition is evaluated against real facts and submission is
      // still impossible. Reported as IDLE, not as a state of concern: armed is
      // the resting posture for as long as the operator wants it, and a desk
      // that looks worried for weeks teaches the room to ignore it. The metrics
      // still say ARMED for anyone reading the panel.
      return reading(
        "idle",
        posture.detail ||
          `Armed — rehearsing against real facts, submission still refused. Autotrade ${
            posture.autotrade_enabled ? "on" : "off"
          }.`,
        metrics,
        at,
      );
    case "UNLOCKED":
      // Stated as alert and never as success. The operator opened it on
      // purpose; this desk's job is to keep that a decision rather than letting
      // it become the background.
      return reading(
        "alert",
        posture.detail ||
          `Vault UNLOCKED — real submission is possible on ${posture.network ?? "an unread network"}.`,
        metrics,
        at,
      );
    default:
      return unknown(
        "The posture could not be read, so HQ cannot say whether execution is possible.",
        metrics,
      );
  }
}

function vaultMetrics(posture: ExecutionPosture | null): Metric[] {
  const armed = posture?.kill_switches?.filter((row) => row.active).length ?? null;
  return [
    // Fixed, and first. Everything else on this panel is about real money and
    // the panel has to say so before it says anything else.
    { label: "Desk", value: "Execution — REAL funds", source: "HQ" },
    { label: "Vault", value: posture?.state ?? null, source: "execution-posture" },
    { label: "Mode", value: posture?.mode ?? null, source: "execution-posture" },
    {
      label: "Network",
      value: posture?.network ?? null,
      source: "execution-posture",
    },
    {
      label: "Autotrade",
      value: posture ? (posture.autotrade_enabled ? "ON" : "off") : null,
      source: "execution-posture",
    },
    {
      label: "Kill switches armed",
      value: armed === null ? null : String(armed),
      source: "execution-posture",
    },
  ];
}

function deriveSentinel(
  operations: HqOperations | null,
  gone: string,
  at: number | null,
): EmployeeReading {
  const metrics = sentinelMetrics(operations);
  if (!operations) return unknown(gone, metrics);

  const health = operations.health;
  const open = openIncidents(operations).filter(
    (incident) => incident.kind === "incident",
  );
  const critical = open.filter((incident) => incident.severity === "critical");

  // An open incident and healthy components are not a contradiction: a
  // component can recover before the pass that closes its incident runs. But
  // "1 critical incident open: all six components answered" reads as one, so
  // the sentence names the incident and then says whether the thing it is
  // about has come back — which is the question a reader actually has.
  const recovered = (incident: Incident): boolean => {
    const component = incident.component as keyof typeof operations.health;
    const row = operations.health[component];
    return typeof row === "object" && row !== null && "status" in row
      ? row.status === "healthy"
      : false;
  };

  if (critical.length > 0) {
    const incident = critical[0]!;
    const tail = recovered(incident)
      ? `${incident.component} is answering again; awaiting close.`
      : componentSummary(operations);
    return reading(
      "incident",
      `${critical.length} critical incident${critical.length === 1 ? "" : "s"} open — ${incident.code}, ${incident.component}. ${tail}`,
      metrics,
      at,
    );
  }
  if (open.length > 0) {
    const incident = open[0]!;
    return reading(
      "alert",
      `${incident.code} open on ${incident.component}. ${componentSummary(operations)}`,
      metrics,
      at,
    );
  }
  // Nothing open, but that is only reassuring for what was actually measured.
  // Saying "all clear" while two probes failed is precisely the reassurance
  // this layer exists to withhold.
  if (health.unmeasured > 0) {
    return reading(
      "alert",
      `${6 - health.unmeasured} of 6 components measured. ${health.unmeasured} could not be read.`,
      metrics,
      at,
    );
  }
  // `idle`, not `working`, and for the same reason Byte is idle when the API
  // answers: watching is Sentinel's permanent condition, so treating it as
  // activity would make the office permanently NORMAL and put QUIET out of
  // reach forever. Idle here means measured and quiet, which is exactly what
  // six healthy components are.
  return reading("idle", componentSummary(operations), metrics, at);
}

function patchMetrics(operations: HqOperations | null): Metric[] {
  if (!operations) {
    return [
      missing("Open incidents", "not available — /hq did not answer"),
      missing("Repairs attempted", "not available — /hq did not answer"),
      missing("Permitted actions", "not available — /hq did not answer"),
    ];
  }
  const repairs = operations.activity.filter((action) => action.action !== "diagnostics.reprobe");
  const succeeded = repairs.filter((action) => action.outcome === "succeeded").length;
  return [
    {
      label: "Open incidents",
      value: String(openIncidents(operations).filter((i) => i.kind === "incident").length),
      source: "hq/incidents",
    },
    {
      label: "Repairs in the trail",
      value: `${succeeded} succeeded of ${repairs.length}`,
      source: "hq/actions",
    },
    {
      label: "Permitted actions",
      value: String(operations.allowlist.length),
      source: "hq/allowlist",
    },
    missing("Code changes", "not available — HQ has no repository write access"),
  ];
}

function derivePatch(
  operations: HqOperations | null,
  gone: string,
  at: number | null,
): EmployeeReading {
  const metrics = patchMetrics(operations);
  if (!operations) return unknown(gone, metrics);

  const mine = openIncidents(operations).filter((incident) => incident.kind === "incident");
  const escalated = mine.filter((incident) => incident.status === "awaiting_owner");
  const repairing = mine.filter((incident) => incident.status === "repairing");

  if (repairing.length > 0) {
    const incident = repairing[0]!;
    return reading(
      "investigating",
      `Repairing ${incident.code}: ${incident.component}.`,
      metrics,
      at,
    );
  }
  if (escalated.length > 0) {
    const incident = escalated[0]!;
    return reading(
      "alert",
      `${incident.code} escalated. ${incident.owner_rationale ?? "No permitted action remains."}`,
      metrics,
      at,
    );
  }
  if (mine.length > 0) {
    const incident = mine[0]!;
    return reading("investigating", `Holding ${incident.code}: ${incident.component}.`, metrics, at);
  }
  // Idle rather than working, and the distinction is the point: Patch has
  // nothing to do, which is a measured fact about an empty incident queue and
  // not a claim that anything is being repaired.
  return reading("idle", "No open incidents.", metrics, at);
}

function quinnMetrics(operations: HqOperations | null): Metric[] {
  if (!operations) {
    return [
      missing("Verifications", "not available — /hq did not answer"),
      missing("Protected rules", "not available — /hq did not answer"),
    ];
  }
  const verified = operations.activity.filter(
    (action) => Object.keys(action.verification ?? {}).length > 0,
  );
  const held = verified.filter((action) => {
    const invariants = (action.verification as { invariants?: { held?: boolean } }).invariants;
    return invariants?.held !== false;
  });
  return [
    {
      label: "Verified actions in the trail",
      value: String(verified.length),
      source: "hq/actions",
    },
    {
      label: "Protected rules intact",
      value: verified.length === 0 ? "No actions to check" : `${held.length} of ${verified.length}`,
      source: "hq/actions",
    },
    {
      label: "Policy fingerprint",
      value: operations.invariants.digest?.slice(0, 12) ?? null,
      source: "hq/invariants",
    },
    missing("Regression suite", "not available — HQ cannot run the test suite"),
  ];
}

function deriveQuinn(
  operations: HqOperations | null,
  gone: string,
  at: number | null,
): EmployeeReading {
  const metrics = quinnMetrics(operations);
  if (!operations) return unknown(gone, metrics);

  // A protected trading rule that moved outranks everything else Quinn could
  // be doing, and it is the only condition in this file that can put her into
  // an incident state.
  const violation = openIncidents(operations).find(
    (incident) => incident.signature === "invariants:changed",
  );
  if (violation) {
    return reading(
      "incident",
      `${violation.code}: a protected trading rule changed during an autonomous action.`,
      metrics,
      at,
    );
  }

  const verifying = openIncidents(operations).filter(
    (incident) => incident.status === "verifying",
  );
  if (verifying.length > 0) {
    const incident = verifying[0]!;
    return reading("verifying", `Confirming recovery on ${incident.code}.`, metrics, at);
  }

  return reading("idle", "No repair awaiting verification.", metrics, at);
}

function deriveSage(s: HqSources): EmployeeReading {
  const performance = fresh(s.radarPerformance, STALE_AFTER_MS.radar, s.now);
  const wallet = fresh(s.paperWallet, STALE_AFTER_MS.paper, s.now);
  const metrics = sageMetrics(performance, wallet);
  const at = s.radarPerformance.observedAt;

  if (!performance) {
    return unknown(absence(s.radarPerformance, STALE_AFTER_MS.radar, s.now, "Track record"), metrics);
  }
  return reading(
    "idle",
    `${performance.total_opportunities} opportunities on the permanent record.`,
    metrics,
    at,
  );
}

function sageMetrics(performance: RadarPerformance | null, wallet: PaperWallet | null): Metric[] {
  const m = wallet?.metrics;
  return [
    { label: "Opportunities tracked", value: num(performance?.total_opportunities), source: "radar/performance" },
    { label: "Active opportunities", value: num(performance?.active_opportunities), source: "radar/performance" },
    { label: "Reached 2x", value: performance?.success_rate ?? null, source: "radar/performance" },
    { label: "Paper win rate", value: m?.win_rate_pct ?? null, source: "paper.metrics" },
    { label: "Profit factor", value: m?.profit_factor ?? null, source: "paper.metrics" },
    { label: "Max drawdown", value: m?.max_drawdown_pct ?? null, source: "paper.metrics" },
  ];
}

/**
 * NOVA — the roll-up, from the office rather than from the API.
 *
 * She reads the nine readings above and nothing else. That is a design
 * requirement rather than an optimisation: a director who queried every
 * endpoint herself could disagree with her own staff, and a room where the
 * boss and the department report different things is worse than no room.
 *
 * She never reads healthy while something is unread. She also never treats
 * Atlas's documented absence as an incident — a permanent, written-down gap is
 * not news, and a Nova who reports it every day is a Nova nobody looks at.
 */
function deriveNova(
  employees: Record<EmployeeId, EmployeeReading>,
  pipeline: PipelineHealth | null,
  gone: string,
  at: number | null,
): EmployeeReading {
  const metrics: Metric[] = [
    { label: "Pipeline roll-up", value: pipeline?.overall ?? null, source: "health/pipeline.overall" },
  ];

  if (!pipeline) return unknown(gone, metrics);

  const others = (Object.keys(employees) as EmployeeId[]).filter((id) => id !== "nova");
  const readings = others.map((id) => employees[id]);
  const faults = readings.filter((r) => r.state === "error" || r.state === "offline").length;
  const alerts = readings.filter((r) => r.state === "alert").length;
  const unread = readings.filter((r) => r.sourced && r.state === "unknown").length;
  const busy = readings.filter((r) => r.state === "busy").length;
  const active = readings.filter(
    (r) => r.state === "working" || r.state === "busy" || r.state === "reviewing",
  ).length;

  metrics.push(
    { label: "Departments reporting a fault", value: String(faults + alerts), source: "HQ roll-up" },
    { label: "Departments with no reading", value: String(unread), source: "HQ roll-up" },
    { label: "Departments busy", value: String(busy), source: "HQ roll-up" },
  );

  if (faults + alerts >= 2) {
    return reading("alert", `${faults + alerts} departments are reporting a fault.`, metrics, at);
  }
  if (faults + alerts === 1) {
    return reading("reviewing", "One department is reporting a fault.", metrics, at);
  }
  if (unread > 0) {
    return reading("reviewing", `${unread} departments have no current reading.`, metrics, at);
  }
  if (busy >= 2) return reading("working", `${busy} departments are busy.`, metrics, at);
  if (active > 0) return reading("working", `${active} departments are working.`, metrics, at);
  return reading("idle", "All reporting departments are quiet.", metrics, at);
}

function deriveActivity(
  employees: Record<EmployeeId, EmployeeReading>,
  pipeline: PipelineHealth | null,
): OfficeActivity {
  // The pipeline is the one source without which the room knows almost nothing.
  // Without it, the honest answer about the office is that nobody has looked.
  if (!pipeline) return "UNKNOWN";

  const readings = Object.values(employees);
  const faults = readings.filter((r) => r.state === "error" || r.state === "offline").length;
  const alerts = readings.filter((r) => r.state === "alert").length;
  const busy = readings.filter((r) => r.state === "busy").length;
  const active = readings.filter(
    (r) => r.state === "working" || r.state === "busy" || r.state === "reviewing",
  ).length;

  if (faults > 0 || alerts >= 2) return "HIGH_ALERT";
  if (busy >= 2 || alerts === 1) return "BUSY";
  if (active > 0) return "NORMAL";
  return "QUIET";
}

/* ── reactions ───────────────────────────────────────────────────────── */

/**
 * The few numbers HQ watches for *change* rather than for value.
 *
 * A trade closing is not announced as such by anything: `paper.changed` fires
 * on every re-mark, fifteen times a minute, and carries no payload saying what
 * changed. The only honest evidence that a position closed is that the
 * permanent record grew a row. So HQ remembers these four numbers and reacts
 * to the difference.
 */
/* ── Karthik ─────────────────────────────────────────────────────────── */

/**
 * Karthik's metrics, which are almost entirely about *whether the experiment
 * is readable* rather than about what it earned.
 *
 * Every row names its source, like every other panel in HQ. A `null` value
 * renders NOT AVAILABLE rather than a dash, because a dash reads as zero and
 * the whole point of this desk is that it never rounds an unmeasured figure
 * up to a comfortable one.
 */
function karthikMetrics(state: KarthikState | null): Metric[] {
  const wallet = state?.screens.wallet;
  const positions = state?.screens.positions;
  const value = (reading: ScreenReading | undefined, key: string): string | null => {
    if (!reading?.measured) return null;
    const raw = reading.values[key];
    return raw === null || raw === undefined ? null : String(raw);
  };
  return [
    {
      label: "Wallet",
      value: state ? (state.binding.readable ? state.binding.detail : "NOT DESIGNATED") : null,
      source: "GET /karthik · binding.state",
    },
    {
      label: "Autonomy",
      value: state?.autonomy ?? null,
      source: "GET /karthik · autonomy",
    },
    {
      label: "Experiment integrity",
      value:
        state === null
          ? null
          : state.integrity.score === null
            ? state.integrity.band
            : `${state.integrity.score} / 100 — ${state.integrity.band}`,
      source: "GET /karthik · integrity.score",
    },
    {
      label: "Equity",
      value: value(wallet, "cash_usd"),
      source: "GET /karthik · screens.wallet",
    },
    {
      label: "Open positions",
      value: value(wallet, "open_positions") ?? (positions?.measured ? String(positions.rows.length) : null),
      source: "GET /karthik · screens.positions",
    },
    {
      label: "Needs owner",
      value: state ? String(state.incidents.filter((i) => i.kind === "karthik_approval").length) : null,
      source: "GET /karthik · incidents",
    },
  ];
}

/**
 * What Karthik's figure is doing, from what the backend actually published.
 *
 * The ordering is the brief's own priority: an owner-attention item outranks
 * an open incident, which outranks a degraded integrity score, which outranks
 * ordinary work. The one state deliberately *not* reachable from here is any
 * kind of success or celebration — that is a reaction to a real event, lives
 * in `react()`, and cannot be produced by a steady-state reading.
 *
 * An unbound wallet reads `unknown` with `sourced: true`. That combination is
 * exact and it matters: the endpoint answered, so this is not a gap in HQ's
 * plumbing that Nova should be reporting every day — it is a wallet that does
 * not exist yet, which is a fact about the deployment, not a fault.
 */
function deriveKarthik(
  state: KarthikState | null,
  gone: string,
  at: number | null,
): EmployeeReading {
  const metrics = karthikMetrics(state);
  if (!state) return unknown(gone, metrics);

  if (!state.binding.readable) {
    // `needs_owner` separates "the owner has not made the wallet yet" from
    // "the variable names a wallet Karthik is forbidden to read". The first is
    // waiting; the second is a misconfiguration somebody has to correct.
    //
    // `sourced: false` on the waiting case, and it is the important half of
    // this branch. Nova counts `sourced && unknown` as a department with no
    // current reading and says so — correctly, when a fetch failed. But an
    // unbound wallet is a gap that is *already written down*: the endpoint
    // answered, and its answer was "the owner has not created this wallet".
    // Reporting that to the CEO every day is exactly what the flag exists to
    // prevent, and it is the same reason Atlas carried it before he had an
    // endpoint of his own.
    return state.binding.needs_owner
      ? reading("alert", state.binding.detail, metrics, at)
      : unknown(state.binding.detail, metrics, false);
  }

  const owner = state.incidents.filter((incident) => incident.kind === "karthik_approval");
  if (owner.length > 0) {
    const first = owner[0]!;
    return reading(
      "incident",
      `${owner.length} item${owner.length === 1 ? "" : "s"} need the owner — ${first.code}, ${first.component}.`,
      metrics,
      at,
    );
  }

  const open = state.incidents.filter((incident) => incident.kind === "karthik_incident");
  if (open.length > 0) {
    const first = open[0]!;
    return reading("alert", `${first.code} open on ${first.component}.`, metrics, at);
  }

  if (state.integrity.score !== null && state.integrity.band !== "HEALTHY") {
    return reading("reviewing", state.integrity.headline, metrics, at);
  }

  const positions = state.screens.positions;
  return reading(
    "working",
    positions.measured
      ? `${positions.rows.length} open position${positions.rows.length === 1 ? "" : "s"} monitored. ${state.integrity.headline}`
      : state.integrity.headline,
    metrics,
    at,
  );
}

export interface HqWitness {
  auditTotal: number | null;
  openPositions: number | null;
  /** Net return of the newest closed trade, as the backend rendered it. */
  lastCloseNet: string | null;
  radarOpportunities: number | null;
  /* ── the pipeline's own marks of progress ──────────────────────────────
     Timestamps rather than counters, because that is what the health
     contract publishes. A changed `last_discovery` is the only evidence
     HQ has that discovery discovered something; it is exact, and it is
     the backend's own word rather than an inference from a rate. */
  lastDiscovery: string | null;
  lastScore: string | null;
  lastSnapshot: string | null;
  /** Cumulative, so a difference means an evaluation actually ran. */
  securityEvaluations: number | null;
  /** Moves in both directions; a change either way is the queue working. */
  queueDepth: number | null;
  /** The roll-up. A change here is worth Byte noticing and Nova hearing. */
  pipelineOverall: string | null;
  /* ── Karthik's wallet, watched for the events §18 reacts to ────────────
     Cumulative counters, so a *difference* is the evidence something
     happened. Reacting to a level rather than to a change would make Karthik
     celebrate continuously for as long as a target hit stayed in the total,
     which is the difference between an animation and a claim. */
  karthikTargetHits: number | null;
  karthikOpenPositions: number | null;
  karthikDeadPositions: number | null;
  karthikOpenIncidents: number | null;
  karthikOwnerItems: number | null;
}

export function witness(sources: Partial<HqSources>): HqWitness {
  const wallet = sources.paperWallet?.data ?? null;
  const audit = sources.paperAudit?.data ?? null;
  const performance = sources.radarPerformance?.data ?? null;
  const pipeline = sources.pipeline?.data ?? null;
  const security = sources.tokenSecurity?.data ?? null;
  const karthik = sources.karthik?.data ?? null;
  // Read from the lifetime report rather than the daily one: a daily counter
  // resets at midnight, and a counter that resets is a counter that looks like
  // it went *down*, which `react` would read as nothing happening and then as
  // a fresh hit the next time one landed.
  const lifetime = karthik?.reports?.lifetime ?? null;
  return {
    auditTotal: audit?.total ?? null,
    openPositions: wallet?.metrics.open_positions ?? null,
    lastCloseNet: audit?.items[0]?.net_return_usd ?? null,
    radarOpportunities: performance?.total_opportunities ?? null,
    lastDiscovery: pipeline?.scanner.last_discovery ?? null,
    lastScore: pipeline?.scoring.last_score ?? null,
    lastSnapshot: pipeline?.market_enrichment.last_snapshot ?? null,
    securityEvaluations: security?.total_evaluations ?? null,
    queueDepth: pipeline?.market_enrichment.queue_depth ?? null,
    pipelineOverall: pipeline?.overall ?? null,
    karthikTargetHits: lifetime?.targets_hit ?? null,
    karthikOpenPositions: lifetime?.open_positions ?? null,
    karthikDeadPositions: lifetime?.dead_zero ?? null,
    karthikOpenIncidents:
      karthik?.incidents.filter((incident) => incident.kind === "karthik_incident").length ?? null,
    karthikOwnerItems:
      karthik?.incidents.filter((incident) => incident.kind === "karthik_approval").length ?? null,
  };
}

/**
 * What changed, and who should notice.
 *
 * Restrained on purpose. A losing trade puts Rex in `reviewing`, not in any
 * kind of failure state — the simulator closing a position at a loss is the
 * strategy working, and dramatising it would be editorialising about a system
 * whose results people are trying to read honestly.
 */
export function react(
  previous: HqWitness | null,
  next: HqWitness,
  now: number,
): Partial<Record<EmployeeId, Transient>> {
  if (!previous) return {};
  const until = now + THRESHOLDS.reactionMs;
  const out: Partial<Record<EmployeeId, Transient>> = {};

  const closed =
    previous.auditTotal !== null &&
    next.auditTotal !== null &&
    next.auditTotal > previous.auditTotal;

  if (closed) {
    const net = Number(next.lastCloseNet);
    const profitable = next.lastCloseNet !== null && Number.isFinite(net) && net > 0;
    out.rex = profitable
      ? {
          state: "success",
          detail: "A paper position closed in profit.",
          until,
          speech: "Position closed.",
        }
      : {
          state: "reviewing",
          detail: "A paper position closed. Reviewing the result.",
          until,
          speech: "Reviewing the exit.",
        };
    out.milo = {
      state: "working",
      detail: "The portfolio changed — a position closed.",
      until,
      speech: "Capital updated.",
    };
  }

  const opened =
    previous.openPositions !== null &&
    next.openPositions !== null &&
    next.openPositions > previous.openPositions;

  /* ── Karthik, §18 ───────────────────────────────────────────────────
     Every branch below fires on a *rise in a counter the backend published*.
     None of them can fire from a timer, none of them can fire while the
     wallet is unbound — an unbound wallet reports `null` for all five, and a
     `null` on either side fails the comparison — and none of them invents the
     event it reacts to. §6's rule, expressed as the only arithmetic that can
     reach these lines. */
  const rose = (a: number | null, b: number | null): boolean =>
    a !== null && b !== null && b > a;

  if (rose(previous.karthikOwnerItems, next.karthikOwnerItems)) {
    // Outranks everything else Karthik could be doing: something has been
    // found that he is explicitly not allowed to fix.
    out.karthik = {
      state: "incident",
      detail: "An item needs the owner. Escalating.",
      until,
      speech: "This one needs you.",
    };
  } else if (rose(previous.karthikOpenIncidents, next.karthikOpenIncidents)) {
    out.karthik = {
      state: "alert",
      detail: "A new finding opened on the Karthik wallet.",
      until,
      speech: "Checking system health.",
    };
  } else if (rose(previous.karthikTargetHits, next.karthikTargetHits)) {
    // The office's only celebration, and the only thing that can produce it
    // is the lifetime target count going up.
    out.karthik = {
      state: "success",
      detail: "A Karthik position filled its 1.25x target.",
      until,
      speech: "Target hit.",
    };
  } else if (rose(previous.karthikDeadPositions, next.karthikDeadPositions)) {
    out.karthik = {
      state: "reviewing",
      detail: "A Karthik position went to zero. Reviewing it.",
      until,
    };
  } else if (rose(previous.karthikOpenPositions, next.karthikOpenPositions)) {
    out.karthik = {
      state: "working",
      detail: "A new Karthik position opened.",
      until,
      speech: "New entry.",
    };
  }

  if (opened && !closed) {
    out.rex = { state: "working", detail: "A paper position opened.", until, speech: "Entry filled." };
    out.milo = {
      state: "working",
      detail: "The portfolio changed — a position opened.",
      until,
      speech: "Capital updated.",
    };
  }

  const recorded =
    previous.radarOpportunities !== null &&
    next.radarOpportunities !== null &&
    next.radarOpportunities !== previous.radarOpportunities;

  if (recorded) {
    out.sage = {
      state: "working",
      detail: "The track record changed.",
      until,
      speech: "Track record updated.",
    };
  }

  /* ── the pipeline's own reactions ─────────────────────────────────────
     Each is a *changed* value, never a present one. `moved` is the only
     test any of these apply, so a reaction cannot fire on a source that
     has merely stayed the same — which is what stops a stale office from
     announcing news every sixty seconds. */
  const moved = <K extends keyof HqWitness>(key: K): boolean =>
    previous[key] !== null && next[key] !== null && previous[key] !== next[key];

  if (moved("lastDiscovery")) {
    out.radar = { state: "working", detail: "A token was discovered.", until, speech: "New candidate." };
  }
  if (moved("lastScore")) {
    out.luna = { state: "working", detail: "A score was recorded.", until, speech: "Score recorded." };
  }
  if (moved("lastSnapshot")) {
    out.dex = { state: "working", detail: "Market data was refreshed.", until, speech: "Market data in." };
  }
  if (moved("securityEvaluations")) {
    // Says an evaluation *ran*, never that it passed. The verdict is Atlas's
    // panel to report from evidence; a bubble that said "verified" would be a
    // safety claim made by a timer.
    out.atlas = {
      state: "reviewing",
      detail: "A security evaluation completed.",
      until,
      speech: "Evaluation complete.",
    };
  }
  if (moved("queueDepth")) {
    out.echo = { state: "working", detail: "The enrichment queue moved.", until, speech: "Queue moved." };
  }
  if (moved("pipelineOverall")) {
    const overall = String(next.pipelineOverall);
    out.byte = {
      state: overall === "healthy" ? "working" : "reviewing",
      detail: `The pipeline roll-up changed to ${overall}.`,
      until,
      speech: `Pipeline: ${overall}.`,
    };
    // Nova reacts to the roll-up and to nothing else. A director who
    // commented on every desk's every change would be noise; the overall
    // state of the platform is the one thing that is hers.
    out.nova = {
      state: overall === "healthy" ? "working" : "reviewing",
      detail: `System status changed to ${overall}.`,
      until,
      speech: "I need an update.",
    };
  }

  return out;
}

/** Everything unknown, nothing claimed. The state HQ renders before it knows. */
export const UNKNOWN_HQ_STATE: HqState = deriveHqState();
