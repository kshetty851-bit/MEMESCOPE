import type { Tile } from "./geometry";
import type { ZoneId } from "./zones";

/**
 * THE ROSTER.
 *
 * Ten people, each standing for one MEMESCOPE subsystem. Defined once, as
 * data, because the brief's requirement is explicit: employee information must
 * not be spread through UI components. The stage, the tablet zone view, the
 * mobile card list and the accessible description all read this array, so they
 * cannot disagree about who exists or what they do.
 *
 * WHAT IS DELIBERATELY ABSENT
 *
 * No metrics, no counts, no status. HQ-1 is a static shell and this file must
 * not grow a `tokensReviewed: 1284` field — an invented statistic is the one
 * failure this whole feature cannot survive. Live state arrives in HQ-3 from
 * the adapter, keyed by `id`, and is merged at render time.
 *
 * `systemResponsibility` is prose for a human reading a panel. It is not a
 * data source and nothing derives behaviour from it.
 */

export type EmployeeId =
  | "nova"
  | "radar"
  | "luna"
  | "dex"
  | "atlas"
  | "milo"
  | "rex"
  | "echo"
  | "byte"
  | "sage"
  // The reliability trio. Added when HQ stopped being a window onto MEMESCOPE
  // and started being able to act on it: somebody has to notice a component
  // has failed, somebody has to diagnose it, and somebody has to prove the
  // repair worked before it is believed. Those are three different jobs and
  // giving them to one person is how a system ends up marking its own homework.
  | "sentinel"
  | "patch"
  | "quinn";

/**
 * The normalised states from the plan. Declared now so the shell's types are
 * final, but HQ-1 renders every employee as `unknown` — nothing is measured
 * yet, and `idle` would read as "measured, and quiet".
 */
export type EmployeeState =
  | "unknown"
  | "offline"
  | "idle"
  | "working"
  | "busy"
  | "reviewing"
  | "success"
  | "alert"
  | "error"
  // Autonomy states. Each requires an open record on the backend to be shown —
  // `investigating` and `verifying` name a mission id, `incident` names an
  // incident. There is no path that reaches these three from a timer.
  | "investigating"
  | "verifying"
  | "incident";

/**
 * The org chart, which is not the floor plan.
 *
 * `zone` says which room a desk stands in; `department` says who somebody
 * belongs to. They agree for ten of the thirteen and disagree for Patch, whose
 * bench is in the Performance Lab because Operations had one free tile and
 * Sentinel needed it. Keeping them as separate fields is what stops a seating
 * accident from silently rewriting the org chart — §19 of the brief groups
 * people by department, and no amount of furniture should change that.
 */
export type DepartmentId =
  | "command"
  | "discovery"
  | "market"
  | "risk"
  | "portfolio"
  | "operations"
  | "infrastructure"
  | "research"
  | "qa";

export const DEPARTMENT_LABEL: Record<DepartmentId, string> = {
  command: "Command",
  discovery: "Discovery & Intelligence",
  market: "Market & Execution",
  risk: "Risk",
  portfolio: "Portfolio",
  operations: "Operations",
  infrastructure: "Infrastructure",
  research: "Performance & Research",
  qa: "Quality Assurance",
};

export interface Employee {
  id: EmployeeId;
  name: string;
  role: string;
  zone: ZoneId;
  /** Who they report with. Independent of which room the desk is in. */
  department: DepartmentId;
  /** Desk anchor, in tile coordinates. The person stands here. */
  desk: Tile;
  /** Which subsystem this person is. Shown in the panel; never used as data. */
  systemResponsibility: string;
  /**
   * How this person introduces themselves in public, in their own voice.
   *
   * Written for the homepage's crew section rather than for the HQ panel:
   * `systemResponsibility` is a list of subsystems, which is what an operator
   * needs and what a visitor bounces off. Both describe the same job.
   *
   * **Neither may make a claim.** These sentences say what a desk watches, not
   * how well it is going — the same rule every other string in HQ lives under.
   */
  whatIDo: string;
  /** The colleagues this desk actually hands work to, by id. */
  worksWith: EmployeeId[];
  /** Idle vocabulary, for HQ-4. Presentation only — never implies system state. */
  personality: string;
  /** Silhouette accessory that makes them recognisable without a label. */
  accessory: string;
  /**
   * Palette key, resolved to CSS custom properties in `hq.css`. A key rather
   * than a hex value so the theme stays in one place and dark/light and any
   * future high-contrast mode do not need this file edited.
   */
  palette: string;
}

export const EMPLOYEES: Employee[] = [
  {
    id: "nova",
    name: "Nova",
    role: "CEO / Commander",
    zone: "mission",
    department: "command",
    desk: { col: 8, row: 1 },
    systemResponsibility: "Overall system status, portfolio roll-up, daily brief",
    whatIDo:
      "Watches the whole platform, decides what needs attention, and pulls the team together when the picture has to be assembled in one place.",
    worksWith: ["radar","atlas","milo","sage"],
    personality: "Calm and observant. Patrols the floor, pauses at departments.",
    accessory: "tablet",
    palette: "indigo",
  },
  {
    id: "radar",
    name: "Radar",
    role: "Head of Discovery",
    zone: "floor",
    department: "discovery",
    desk: { col: 6, row: 3 },
    systemResponsibility: "Scanner, token discovery, Radar admission",
    whatIDo:
      "Watches the scanner for tokens that have just appeared, and keeps an eye on the ones that have started to move.",
    worksWith: ["luna","dex"],
    personality: "Energetic and fast. Leans into the feed, spins the dish.",
    accessory: "headset",
    palette: "cyan",
  },
  {
    id: "luna",
    name: "Luna",
    role: "Senior Token Analyst",
    zone: "floor",
    department: "discovery",
    desk: { col: 8, row: 3 },
    systemResponsibility: "Scoring, analyst orchestration, candidate evaluation",
    whatIDo:
      "Reads the evidence behind every score — signals, components and the reasons a token was ranked where it was.",
    worksWith: ["radar","dex","sage"],
    personality: "Focused and analytical. Reads, annotates, nods slowly.",
    accessory: "stylus",
    palette: "violet",
  },
  {
    id: "dex",
    name: "Dex",
    role: "Market Analyst",
    zone: "floor",
    department: "market",
    desk: { col: 10, row: 3 },
    systemResponsibility: "Market data, price, liquidity, volume, quote freshness",
    whatIDo:
      "Follows price, liquidity, volume and how fresh each quote is, so nothing is judged on a stale number.",
    worksWith: ["luna","rex","echo"],
    personality: "Fast multitasker. Head flicks between monitors. Coffee nearby.",
    accessory: "visor",
    palette: "amber",
  },
  {
    id: "atlas",
    name: "Atlas",
    role: "Chief Risk Officer",
    zone: "risk",
    department: "risk",
    desk: { col: 2, row: 4 },
    systemResponsibility:
      "Safety gate, liquidity security, mint and freeze authority, price impact",
    whatIDo:
      "Checks mint and freeze authority, the venue and the liquidity behind a token before any entry is allowed.",
    worksWith: ["rex","nova"],
    personality: "Serious and still. Deliberate scans. Rarely moves.",
    accessory: "shield",
    palette: "steel",
  },
  {
    id: "rex",
    name: "Rex",
    role: "Execution Specialist",
    zone: "floor",
    department: "market",
    desk: { col: 12, row: 4 },
    systemResponsibility: "Paper Wallet entries and exits; Real Wallet state display",
    whatIDo:
      "Watches Paper Wallet entries and exits, the execution quotes behind them and how each position actually closed.",
    worksWith: ["atlas","milo","dex"],
    personality: "Confident and fast. Drums fingers, rolls the chair back.",
    accessory: "wrist-terminal",
    palette: "crimson",
  },
  {
    id: "milo",
    name: "Milo",
    role: "Portfolio Manager",
    zone: "portfolio",
    department: "portfolio",
    desk: { col: 2, row: 8 },
    systemResponsibility: "Open positions, exposure, holding period, capital efficiency",
    whatIDo:
      "Tracks what capital is doing: open positions, exposure, holding periods and which generation is trading.",
    worksWith: ["rex","sage","nova"],
    personality: "Patient and strategic. Steps back from the wall, arms folded.",
    accessory: "clipboard",
    palette: "forest",
  },
  {
    id: "echo",
    name: "Echo",
    role: "Operations Manager",
    zone: "ops",
    department: "operations",
    desk: { col: 6, row: 8 },
    systemResponsibility: "Workers, queues, enrichment backlog, priority lane",
    whatIDo:
      "Keeps the enrichment queues moving and watches the priority lane for anything waiting longer than it should.",
    worksWith: ["dex","byte"],
    personality: "Organised and mobile. Walks between terminals, gestures at the board.",
    accessory: "tool-belt",
    palette: "orange",
  },
  {
    id: "byte",
    name: "Byte",
    role: "Infrastructure Engineer",
    zone: "ops",
    department: "infrastructure",
    desk: { col: 9, row: 8 },
    systemResponsibility: "Database, cache, RPC, WebSocket and API health",
    whatIDo:
      "Watches the database, cache, RPC, WebSocket and API — the parts that have to be up for anything else to be true.",
    worksWith: ["echo","nova"],
    personality: "Technical and slouched. Three mugs. Stretches, refills, occasionally naps.",
    accessory: "hoodie",
    palette: "lime",
  },
  {
    id: "sage",
    name: "Sage",
    role: "Performance Analyst",
    zone: "lab",
    department: "research",
    desk: { col: 13, row: 8 },
    systemResponsibility: "Track record, P&L, win rate, drawdown, strategy comparison",
    whatIDo:
      "Measures what the strategy actually did: track record, realised P&L, win rate and drawdown.",
    worksWith: ["milo","luna","nova"],
    personality: "Calm and patient. Slow scroll, chin on hand.",
    accessory: "glasses",
    palette: "teal",
  },
  {
    id: "sentinel",
    name: "Sentinel",
    role: "Production / SRE",
    zone: "ops",
    department: "infrastructure",
    // The one tile Operations had left. Everything else in this room is a
    // desk, a cabinet, the printer Sam services, or an authored walk route.
    desk: { col: 6, row: 9 },
    systemResponsibility:
      "Container, Redis, Postgres, Celery, scheduler, disk and queue health",
    whatIDo:
      "Watches the machinery the platform runs on — containers, broker, database, workers and disk — and raises an incident the moment one of them stops answering.",
    worksWith: ["byte", "patch", "nova"],
    personality: "Watchful and unhurried. Stands at the wall, scans, sits down again.",
    accessory: "visor",
    palette: "ice",
  },
  {
    id: "patch",
    name: "Patch",
    role: "Reliability Engineer",
    // Physically in the Performance Lab, because Operations had exactly one
    // free tile and Sentinel took it. `department` is what §19 cares about and
    // it still says infrastructure — real departments span rooms, and the
    // alternative was wedging a desk onto a walk route.
    zone: "lab",
    department: "infrastructure",
    desk: { col: 12, row: 9 },
    systemResponsibility:
      "Incident diagnosis, remediation execution, backend defect investigation",
    whatIDo:
      "Takes an open incident, works out which component actually failed, and either applies a permitted repair or writes up what a person needs to decide.",
    worksWith: ["sentinel", "byte", "quinn"],
    personality: "Methodical. Reads the evidence before touching anything.",
    accessory: "toolbox",
    palette: "rust",
  },
  {
    id: "quinn",
    name: "Quinn",
    role: "QA / Verification Engineer",
    zone: "lab",
    department: "qa",
    // The lab's north-east corner. (14,8) was legal but had one exit, south
    // into the Lounge — a verification desk should not have to walk through
    // the sofa to reach a meeting.
    desk: { col: 15, row: 7 },
    systemResponsibility:
      "Post-repair verification, protected-invariant checks, recovery confirmation",
    whatIDo:
      "Re-checks a component after a repair and confirms the protected trading rules are byte-for-byte what they were before it, so nothing is called fixed on hope.",
    worksWith: ["patch", "sentinel", "sage"],
    personality: "Sceptical by trade. Asks for the second reading.",
    accessory: "glasses",
    palette: "mint",
  },
];

export const EMPLOYEE_BY_ID = new Map<EmployeeId, Employee>(
  EMPLOYEES.map((employee) => [employee.id, employee]),
);

export function employeesInZone(zone: ZoneId): Employee[] {
  return EMPLOYEES.filter((employee) => employee.zone === zone);
}

/**
 * How a state should read to someone who cannot see colour, and what it is
 * called in an accessible name.
 *
 * `unknown` is first and is the HQ-1 default for every employee. It must never
 * present as healthy: no data is not the same as nothing happening, and the
 * green reading of an unmeasured system is the exact failure this product
 * cannot afford.
 */
export const STATE_LABEL: Record<EmployeeState, string> = {
  unknown: "No data",
  offline: "Offline",
  idle: "Idle",
  working: "Working",
  busy: "Busy",
  reviewing: "Reviewing",
  success: "Complete",
  alert: "Alert",
  error: "Error",
  investigating: "Investigating",
  verifying: "Verifying",
  incident: "Incident",
};

/** States that must never be styled as healthy. Asserted in tests. */
export const NON_HEALTHY_STATES: EmployeeState[] = [
  "unknown",
  "offline",
  "alert",
  "error",
  "incident",
];
