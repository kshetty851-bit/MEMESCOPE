import type { TileRect } from "./geometry";

/**
 * THE DEPARTMENTS.
 *
 * The room's geometry teaches the pipeline: the trading floor reads west to
 * east in journey order (discovery → analysis → market → execution), the risk
 * room sits behind glass beside it because it is the only department that can
 * *stop* that flow, and the vault adjoins execution as a separate sealed space.
 *
 * Laid out as data rather than JSX so the floor plan can be asserted — that
 * zones do not overlap, that every zone is inside the room, that every
 * employee anchor lands in its own department. A floor plan that is only
 * expressed as markup can only be checked by looking at it.
 */

export type ZoneId =
  | "mission"
  | "conference"
  | "risk"
  | "floor"
  | "vault"
  | "portfolio"
  | "ops"
  | "lab"
  | "deck"
  | "pantry"
  | "lounge"
  | "facilities"
  | "restrooms"
  | "reception"
  | "walkway";

export interface Zone {
  id: ZoneId;
  /** Shown on the stage. Kept short — the room is not a diagram. */
  label: string;
  /** One line, for the accessible description and the tablet/mobile cards. */
  summary: string;
  rect: TileRect;
  /**
   * Floor treatment. `plate` is the standard lit department floor; `glass`
   * carries the risk room's barrier; `sealed` is the vault; `walkway` is the
   * unlit connective floor nobody works on.
   */
  surface: "plate" | "glass" | "sealed" | "walkway" | "deck";
}

/**
 * 22 columns × 14 rows.
 *
 *      col →   0    2    4    6    8   10   12   14   16   18   20   22
 *  row 0     ┌─────────────── MISSION ───────────────┬─ CONFERENCE ──┐
 *      2     ├──── RISK ────┬──── TRADING FLOOR ──────┤   (glass)    │
 *      4     │              │                  ┌VAULT─┼──────────────┤
 *      6     ├──────────── WALKWAY ────────────┴──────┤ OUTDOOR DECK │
 *      7     ├── PORTFOLIO ─┬──── OPS ────┬─── LAB ───┤  (exterior)  │
 *      8     │              │             │           ├──────────────┘
 *     10     ├──── PANTRY ──────┬──────── LOUNGE ─────┤     (space)
 *     12     ├ FACIL ┬ RESTRMS ┬───── RECEPTION ──────┤
 *     14     └───────┴─────────┴───────────────────────
 *
 * The bottom-right block (cols 16–22, rows 8–14) belongs to no zone: it is
 * open space beyond the hull. The deck's south railing and the lounge's
 * viewport both look onto it.
 */
export const ZONES: Zone[] = [
  {
    id: "mission",
    label: "Mission Control",
    summary: "Overall system status and the mission board.",
    rect: { col: 0, row: 0, cols: 16, rows: 2 },
    surface: "plate",
  },
  {
    id: "risk",
    label: "Risk Room",
    summary: "Security and risk review, behind glass.",
    rect: { col: 0, row: 2, cols: 5, rows: 4 },
    surface: "glass",
  },
  {
    id: "floor",
    label: "Trading Floor",
    summary: "Discovery, analysis, market data and execution.",
    rect: { col: 5, row: 2, cols: 8, rows: 4 },
    surface: "plate",
  },
  {
    id: "vault",
    label: "Execution Vault",
    summary: "Real Wallet execution. Sealed unless explicitly enabled.",
    rect: { col: 13, row: 2, cols: 3, rows: 4 },
    surface: "sealed",
  },
  {
    id: "conference",
    label: "Conference Room",
    summary: "Glass-walled meeting room off Mission Control.",
    // Surface `plate`, not `glass`: the glass surface is the Risk Room's
    // translucent floor treatment, and under a conference table it read as a
    // hole in the station. This room's glass is its *walls*, drawn by the
    // stage; the floor is ordinary carpet.
    rect: { col: 16, row: 0, cols: 6, rows: 4 },
    surface: "plate",
  },
  {
    id: "deck",
    label: "Outdoor Break Deck",
    summary: "Exterior observation deck behind an airlock.",
    rect: { col: 16, row: 4, cols: 6, rows: 4 },
    surface: "deck",
  },
  {
    id: "walkway",
    label: "Walkway",
    summary: "Connective floor.",
    rect: { col: 0, row: 6, cols: 16, rows: 1 },
    surface: "walkway",
  },
  {
    id: "portfolio",
    label: "Portfolio",
    summary: "Open positions, exposure and holding periods.",
    rect: { col: 0, row: 7, cols: 5, rows: 3 },
    surface: "plate",
  },
  {
    id: "ops",
    label: "Operations & Tech",
    summary: "Queues, workers and infrastructure.",
    rect: { col: 5, row: 7, cols: 6, rows: 3 },
    surface: "plate",
  },
  {
    id: "lab",
    label: "Performance Lab",
    summary: "Track record and strategy analysis.",
    rect: { col: 11, row: 7, cols: 5, rows: 3 },
    surface: "plate",
  },
  {
    // The old break room, split in two. A kitchen and a quiet corner are
    // different rooms in any real office, and the split is what lets each
    // carry its own furniture and its own kind of routine.
    id: "pantry",
    label: "Pantry",
    summary: "Coffee, fridge and the kitchen counter.",
    rect: { col: 0, row: 10, cols: 8, rows: 2 },
    surface: "plate",
  },
  {
    id: "lounge",
    label: "Lounge",
    summary: "Sofa, reading chairs and the station viewport.",
    rect: { col: 8, row: 10, cols: 8, rows: 2 },
    surface: "plate",
  },
  {
    id: "facilities",
    label: "Facilities",
    summary: "Housekeeping and maintenance storage.",
    rect: { col: 0, row: 12, cols: 3, rows: 2 },
    surface: "walkway",
  },
  {
    // Signage and doors only. Interiors are neither rendered nor simulated.
    id: "restrooms",
    label: "Restrooms",
    summary: "Restroom corridor.",
    rect: { col: 3, row: 12, cols: 3, rows: 2 },
    surface: "walkway",
  },
  {
    id: "reception",
    label: "Reception",
    summary: "The front desk and the way in.",
    rect: { col: 6, row: 12, cols: 10, rows: 2 },
    surface: "plate",
  },
];

export const ZONE_BY_ID = new Map<ZoneId, Zone>(ZONES.map((zone) => [zone.id, zone]));

/** Zones a reader can focus. The walkway is floor, not a department. */
export const FOCUSABLE_ZONES = ZONES.filter((zone) => zone.id !== "walkway");
