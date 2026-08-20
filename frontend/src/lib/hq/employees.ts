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
  | "sage";

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
  | "error";

export interface Employee {
  id: EmployeeId;
  name: string;
  role: string;
  zone: ZoneId;
  /** Desk anchor, in tile coordinates. The person stands here. */
  desk: Tile;
  /** Which subsystem this person is. Shown in the panel; never used as data. */
  systemResponsibility: string;
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
    role: "Mission Director",
    zone: "mission",
    desk: { col: 8, row: 1 },
    systemResponsibility: "Overall system status, portfolio roll-up, daily brief",
    personality: "Calm and observant. Patrols the floor, pauses at departments.",
    accessory: "tablet",
    palette: "indigo",
  },
  {
    id: "radar",
    name: "Radar",
    role: "Head of Discovery",
    zone: "floor",
    desk: { col: 6, row: 3 },
    systemResponsibility: "Scanner, token discovery, Radar admission",
    personality: "Energetic and fast. Leans into the feed, spins the dish.",
    accessory: "headset",
    palette: "cyan",
  },
  {
    id: "luna",
    name: "Luna",
    role: "Senior Token Analyst",
    zone: "floor",
    desk: { col: 8, row: 3 },
    systemResponsibility: "Scoring, analyst orchestration, candidate evaluation",
    personality: "Focused and analytical. Reads, annotates, nods slowly.",
    accessory: "stylus",
    palette: "violet",
  },
  {
    id: "dex",
    name: "Dex",
    role: "Market Analyst",
    zone: "floor",
    desk: { col: 10, row: 3 },
    systemResponsibility: "Market data, price, liquidity, volume, quote freshness",
    personality: "Fast multitasker. Head flicks between monitors. Coffee nearby.",
    accessory: "visor",
    palette: "amber",
  },
  {
    id: "atlas",
    name: "Atlas",
    role: "Chief Risk Officer",
    zone: "risk",
    desk: { col: 2, row: 4 },
    systemResponsibility:
      "Safety gate, liquidity security, mint and freeze authority, price impact",
    personality: "Serious and still. Deliberate scans. Rarely moves.",
    accessory: "shield",
    palette: "steel",
  },
  {
    id: "rex",
    name: "Rex",
    role: "Execution Specialist",
    zone: "floor",
    desk: { col: 12, row: 4 },
    systemResponsibility: "Paper Wallet entries and exits; Real Wallet state display",
    personality: "Confident and fast. Drums fingers, rolls the chair back.",
    accessory: "wrist-terminal",
    palette: "crimson",
  },
  {
    id: "milo",
    name: "Milo",
    role: "Portfolio Manager",
    zone: "portfolio",
    desk: { col: 2, row: 8 },
    systemResponsibility: "Open positions, exposure, holding period, capital efficiency",
    personality: "Patient and strategic. Steps back from the wall, arms folded.",
    accessory: "clipboard",
    palette: "forest",
  },
  {
    id: "echo",
    name: "Echo",
    role: "Operations Manager",
    zone: "ops",
    desk: { col: 6, row: 8 },
    systemResponsibility: "Workers, queues, enrichment backlog, priority lane",
    personality: "Organised and mobile. Walks between terminals, gestures at the board.",
    accessory: "tool-belt",
    palette: "orange",
  },
  {
    id: "byte",
    name: "Byte",
    role: "Infrastructure Engineer",
    zone: "ops",
    desk: { col: 9, row: 8 },
    systemResponsibility: "Database, cache, RPC, WebSocket and API health",
    personality: "Technical and slouched. Three mugs. Stretches, refills, occasionally naps.",
    accessory: "hoodie",
    palette: "lime",
  },
  {
    id: "sage",
    name: "Sage",
    role: "Performance Analyst",
    zone: "lab",
    desk: { col: 13, row: 8 },
    systemResponsibility: "Track record, P&L, win rate, drawdown, strategy comparison",
    personality: "Calm and patient. Slow scroll, chin on hand.",
    accessory: "glasses",
    palette: "teal",
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
};

/** States that must never be styled as healthy. Asserted in tests. */
export const NON_HEALTHY_STATES: EmployeeState[] = [
  "unknown",
  "offline",
  "alert",
  "error",
];
