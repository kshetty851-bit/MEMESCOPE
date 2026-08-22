import {
  STALE_AFTER_MS,
  fresh,
  isSecurityGated,
  type HqState,
  type Metric,
} from "./adapter";
import { EMPLOYEE_BY_ID, type EmployeeId } from "./employees";

/**
 * THE CONSOLIDATED HQ REPORT.
 *
 * What "Provide updated report" produces, and the one place the meeting's
 * dialogue and the report panel both read — so a bubble saying "queue looks
 * normal" and a panel section saying UNKNOWN can never appear in the same
 * second about the same queue.
 *
 * ── READ-ONLY, AND STRUCTURALLY SO ──────────────────────────────────────
 *
 * A pure function of `HqState`. No fetch, no write, no clock of its own, no
 * argument that could reach a backend. The report cannot buy, sell, change a
 * strategy, touch security or write operational data because nothing in this
 * module can do anything at all except return a value — which is a stronger
 * guarantee than a comment promising restraint.
 *
 * ── UNKNOWN IS AN ANSWER ────────────────────────────────────────────────
 *
 * Every line is a `Metric`, and `Metric.value === null` already means "no
 * source" everywhere else in HQ. This module keeps that contract rather than
 * inventing one: a missing figure renders NOT AVAILABLE, and there is no code
 * path that substitutes a zero, a last-known value or a plausible guess. The
 * executive summary is assembled from what is *present*; it never rounds a gap
 * up to a claim.
 *
 * That is also why the summary is built from counts of real readings rather
 * than from prose templates. "Nine departments reporting, one without a
 * source" is a fact about the readings. "Everything looks healthy" would be a
 * judgement this module has no standing to make.
 *
 * ── NOTHING HERE RECOMMENDS ─────────────────────────────────────────────
 *
 * `ACTION ITEMS` are derived only from departments that are themselves
 * reporting alert/error, and each one names the department and its own
 * sentence. There is no rule that turns a metric into advice, and no section
 * may ever say buy, sell, hold or consider — the same product rule the
 * analysts and explanations already live under.
 */

export interface ReportLine extends Metric {
  /** Set when this line is the reason an action item exists. */
  attention?: boolean;
}

export interface ReportSection {
  id: string;
  title: string;
  /** The employee whose desk owns this section, when one does. */
  owner?: EmployeeId;
  lines: ReportLine[];
  /** Present only when the whole section has no source at all. */
  unavailable?: string;
}

export interface HqReport {
  /** Epoch ms this report describes. The state's clock, never a fresh one. */
  observedAt: number;
  /** The office roll-up, carried so the dialogue quotes the same reading. */
  activityLabel: string;
  summary: string[];
  sections: ReportSection[];
  issues: ReportLine[];
  actions: string[];
}

/** How a null renders anywhere a string is required. */
export const NOT_AVAILABLE = "NOT AVAILABLE";

const ALERT_STATES = new Set(["alert", "error"]);

function lines(state: HqState, id: EmployeeId, labels?: string[]): ReportLine[] {
  const reading = state.employees[id];
  if (!reading) return [];
  if (!labels) return reading.metrics.map((metric) => ({ ...metric }));
  // Ordered by the caller's list, so a section reads in the order a person
  // would say it rather than in adapter order.
  return labels
    .map((label) => reading.metrics.find((metric) => metric.label === label))
    .filter((metric): metric is Metric => metric !== undefined)
    .map((metric) => ({ ...metric }));
}

/**
 * The Paper Wallet section, which is the one the brief enumerates by name.
 *
 * Read from the wallet payload rather than from Milo's panel metrics: the
 * panel carries what a desk shows at a glance, and the report asks for cash,
 * lineage equity and the holding rule as well. Same `fresh()` gate either way,
 * so a stale wallet blanks this section rather than ageing quietly.
 */
function paperSection(state: HqState): ReportSection {
  const wallet = fresh(state.sources.paperWallet, STALE_AFTER_MS.paper, state.now);
  const source = "paper.metrics";
  if (!wallet) {
    return {
      id: "paper",
      title: "PAPER WALLET",
      owner: "milo",
      lines: [],
      unavailable: "No current Paper Wallet reading.",
    };
  }
  const m = wallet.metrics;
  const holdRule = wallet.strategy?.rules?.find((rule) => rule.label === "Maximum hold");
  return {
    id: "paper",
    title: "PAPER WALLET",
    owner: "milo",
    lines: [
      {
        label: "Active generation",
        value: `Gen ${wallet.generation}`,
        source: "paper.generation",
      },
      { label: "Strategy", value: wallet.strategy?.id ?? null, source: "paper.strategy" },
      { label: "Available cash", value: m?.cash ?? null, source },
      {
        // Named for what it is. The figure is pooled across the capital
        // lineage, and calling it "equity" alone invited the reading that it
        // belongs to this generation's own trades.
        label: "Lineage equity",
        value: m?.equity ?? m?.known_partial_equity ?? null,
        source: m?.equity ? source : `${source} · partial, ${m?.unpriced_positions ?? 0} unpriced`,
      },
      { label: "Capital deployed", value: m?.invested_usd ?? null, source },
      { label: "Open positions", value: numeric(m?.open_positions), source },
      { label: "Realised P/L", value: m?.realised_pnl ?? null, source },
      { label: "Win rate", value: m?.win_rate_pct ?? null, source },
      { label: "Profit factor", value: m?.profit_factor ?? null, source },
      {
        label: "Security gate",
        value: wallet.strategy ? (isSecurityGated(wallet.strategy.id) ? "STRICT" : "NOT ENFORCED") : null,
        source: "paper.strategy",
        attention: wallet.strategy ? !isSecurityGated(wallet.strategy.id) : false,
      },
      {
        // The rule as the backend publishes it, never a build-time constant:
        // a frontend that hardcoded "6 hours" would keep saying so after the
        // rule changed, which is the failure the security gate just had.
        label: "HOLD-6H",
        value: holdRule?.value ?? null,
        source: "paper.strategy.rules",
      },
    ],
  };
}

function numeric(value: number | null | undefined): string | null {
  return typeof value === "number" && Number.isFinite(value) ? String(value) : null;
}

/**
 * Departments currently reporting a fault, as lines a reader can act on.
 *
 * Only alert and error qualify. `unknown` is deliberately excluded: Atlas has
 * no aggregate source by design, and a report that listed "no reading" as an
 * issue every single time would train a reader to skip the section that
 * matters.
 */
function issuesOf(state: HqState): ReportLine[] {
  return (Object.keys(state.employees) as EmployeeId[])
    .filter((id) => ALERT_STATES.has(state.employees[id]!.state))
    .map((id) => ({
      label: EMPLOYEE_BY_ID.get(id)?.name ?? id,
      value: state.employees[id]!.detail,
      source: `HQ · ${id}`,
      attention: true,
    }));
}

export function buildReport(state: HqState): HqReport {
  const sections: ReportSection[] = [
    {
      id: "health",
      title: "SYSTEM HEALTH",
      owner: "byte",
      lines: [
        { label: "Office activity", value: state.activity, source: "HQ roll-up" },
        ...lines(state, "byte"),
      ],
    },
    { id: "discovery", title: "RADAR / DISCOVERY", owner: "radar", lines: lines(state, "radar") },
    { id: "scoring", title: "SCORING", owner: "luna", lines: lines(state, "luna") },
    { id: "market", title: "MARKET & LIQUIDITY", owner: "dex", lines: lines(state, "dex") },
    { id: "security", title: "SECURITY / SEC-2", owner: "atlas", lines: lines(state, "atlas") },
    paperSection(state),
    { id: "execution", title: "EXECUTION / EXITS", owner: "rex", lines: lines(state, "rex") },
    { id: "queues", title: "QUEUES / INFRASTRUCTURE", owner: "echo", lines: lines(state, "echo") },
    { id: "performance", title: "PERFORMANCE", owner: "sage", lines: lines(state, "sage") },
  ];

  const issues = issuesOf(state);
  const readings = (Object.keys(state.employees) as EmployeeId[]).filter(
    (id) => state.employees[id]!.state !== "unknown",
  ).length;
  const unsourced = (Object.keys(state.employees) as EmployeeId[]).filter(
    (id) => !state.employees[id]!.sourced,
  ).length;

  return {
    observedAt: state.now,
    activityLabel: state.activity,
    // Counts of readings, not a verdict on them. See the module header.
    summary: [
      `Office activity reads ${state.activity}.`,
      `${readings} of ${Object.keys(state.employees).length} departments have a current reading.`,
      unsourced > 0
        ? `${unsourced} department${unsourced === 1 ? "" : "s"} ha${unsourced === 1 ? "s" : "ve"} no aggregate source and report${unsourced === 1 ? "s" : ""} UNKNOWN by design.`
        : "Every department has a source.",
      issues.length > 0
        ? `${issues.length} department${issues.length === 1 ? "" : "s"} reporting a fault.`
        : "No department is reporting a fault.",
    ],
    sections,
    issues,
    // Each action names a department and repeats its own sentence. Nothing
    // here is generated advice, and no action item can exist without a
    // department that is itself reporting a fault.
    actions: issues.map((issue) => `${issue.label}: ${issue.value ?? NOT_AVAILABLE}`),
  };
}

/* ── the meeting's words ─────────────────────────────────────────────── */

export interface DialogueLine {
  employee: EmployeeId;
  /** What appears in the bubble. Short enough to read before it fades. */
  text: string;
  /** The section this line summarises, so the panel can highlight along. */
  section: string;
}

/**
 * What each person says, built from the same report the panel renders.
 *
 * ── EVERY OPERATIONAL SENTENCE IS A QUOTED FIGURE ───────────────────────
 *
 * A line is assembled by picking the first line of that person's section that
 * actually has a value, and reading it back as `label: value`. There is no
 * template that produces a sentence without a figure behind it, so "Queue
 * looks normal" cannot be said about a queue nobody measured — the fallback is
 * `NO DATA`, in those words.
 *
 * That is stricter than it sounds and deliberately so. The brief offers
 * example lines like "Feeds stable", and those are exactly the sentences this
 * function refuses to generate: stable is a judgement, and the only judgement
 * HQ is entitled to make is the one the adapter already made when it set the
 * department's state.
 */
function firstAnswerable(section: ReportSection | undefined): ReportLine | null {
  if (!section) return null;
  return section.lines.find((line) => line.value !== null && line.value !== "") ?? null;
}

const NO_DATA = "NO DATA";

export function buildDialogue(report: HqReport): DialogueLine[] {
  const sectionOf = (id: string) => report.sections.find((section) => section.id === id);
  const speak = (employee: EmployeeId, sectionId: string): DialogueLine => {
    const section = sectionOf(sectionId);
    const line = firstAnswerable(section);
    return {
      employee,
      text: line ? `${line.label}: ${line.value}` : NO_DATA,
      section: sectionId,
    };
  };

  return [
    // Nova opens with the roll-up, which is a real reading, and closes with
    // counts of what was reported — never with a verdict on it.
    { employee: "nova", text: `Office activity: ${report.activityLabel}`, section: "health" },
    speak("radar", "discovery"),
    speak("luna", "scoring"),
    speak("dex", "market"),
    speak("atlas", "security"),
    speak("milo", "paper"),
    speak("rex", "execution"),
    speak("echo", "queues"),
    speak("byte", "health"),
    // Patch reports the reliability desk. There is no incident surface behind
    // this yet, so it says NO DATA — which is the truthful line for a desk
    // whose evidence does not exist, and the one that will start carrying real
    // incidents the moment the operations surface does.
    speak("patch", "incidents"),
    speak("sage", "performance"),
    {
      employee: "nova",
      text:
        report.issues.length > 0
          ? `${report.issues.length} department${report.issues.length === 1 ? "" : "s"} reporting a fault.`
          : "No department is reporting a fault.",
      section: "summary",
    },
  ];
}
