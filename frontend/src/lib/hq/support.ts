import type { ActorFrame } from "./ambient";
import { STEP_MS } from "./ambient";
import type { CharacterLook, Pose } from "./characters";
import type { Tile } from "./geometry";

/**
 * THE PEOPLE WHO KEEP THE OFFICE RUNNING.
 *
 * Maya cleans it and Sam fixes it. They are employees of the company, drawn
 * with the same care and the same rig as the core ten — and they are not, and
 * can never become, part of the operational roster. No backend state reaches
 * them, no reading of theirs reaches Nova, and `deriveHqState` does not know
 * they exist. A test enforces that last sentence literally, because the
 * moment a support character carries a system state, HQ has eleven readouts
 * and one of them is fiction.
 *
 * Their activity states — idle, walking, cleaning, maintenance — are animation
 * vocabulary. They describe what the drawing is doing, never what MEMESCOPE
 * is doing.
 *
 * Sam in particular is not infrastructure monitoring. Byte is. Sam checks
 * that the printer has paper and the gate opens; his detail strings are
 * written so none of them could be misread as a health claim, and the
 * vocabulary test covers his lines like everyone else's.
 */

export type SupportId = "maya" | "sam";

export interface SupportRoutine {
  id: string;
  actor: SupportId;
  weight: number;
  frames: ActorFrame[];
  suppressOnAlert?: boolean;
  nightFactor?: number;
}

export interface SupportNpc {
  id: SupportId;
  name: string;
  role: string;
  /** Where they idle between routines: the facilities room. */
  home: Tile;
  /** Shown while idle at home. */
  restingDetail: string;
  look: CharacterLook;
}

export const SUPPORT_STAFF: SupportNpc[] = [
  {
    id: "maya",
    name: "Maya",
    role: "Housekeeping",
    home: { col: 1, row: 13 },
    restingDetail: "By the housekeeping trolley in Facilities.",
    look: {
      id: "maya",
      bodyType: "compact",
      headShape: "oval",
      skinTone: "s4",
      hair: "wavy",
      hairTone: "h5",
      outfit: "utility",
      accessory: "duster",
      palette: "plum",
      defaultPose: "standing",
    },
  },
  {
    id: "sam",
    name: "Sam",
    role: "Facilities",
    home: { col: 2, row: 12 },
    restingDetail: "In Facilities, between jobs.",
    look: {
      id: "sam",
      bodyType: "broad",
      headShape: "round",
      skinTone: "s1",
      hair: "locs",
      hairTone: "h1",
      outfit: "field-jacket",
      accessory: "toolbox",
      palette: "khaki",
      defaultPose: "standing",
    },
  },
];

export const SUPPORT_BY_ID = new Map(SUPPORT_STAFF.map((npc) => [npc.id, npc]));
export const SUPPORT_IDS = SUPPORT_STAFF.map((npc) => npc.id);

/* ── routes ────────────────────────────────────────────────────────────── */

function go(tiles: Tile[], carry?: ActorFrame["carry"]): ActorFrame[] {
  const pose: Pose = "walking_short";
  return tiles.map((tile) => ({ pose, tile, hold: STEP_MS, carry }));
}

function back(tiles: Tile[], carry?: ActorFrame["carry"]): ActorFrame[] {
  const pose: Pose = "returning_to_desk";
  return [
    ...[...tiles].reverse().map((tile) => ({ pose, tile, hold: STEP_MS, carry })),
    { pose, hold: STEP_MS },
  ];
}

function job(tile: Tile, hold: number, detail: string): ActorFrame {
  const pose: Pose = "tidying";
  return { pose, tile, hold, detail };
}

/** Facilities out to the pantry corridor. Shared by most of Maya's rounds. */
const OUT_WEST: Tile[] = [
  { col: 2, row: 13 },
  { col: 3, row: 13 },
  { col: 4, row: 13 },
  { col: 5, row: 13 },
  { col: 5, row: 12 },
  { col: 5, row: 11 },
];

const UP_COL4: Tile[] = [
  { col: 4, row: 11 },
  { col: 4, row: 9 },
  { col: 4, row: 6 },
];

/**
 * Maya's rounds. Infrequent by weight: an office that is being cleaned
 * constantly reads as a cleaning simulator, and hers is a background
 * presence, not a main loop. The trolley travels only on the bin round —
 * wiping a counter does not need it.
 */
export const SUPPORT_ROUTINES: SupportRoutine[] = [
  {
    id: "maya-pantry",
    actor: "maya",
    weight: 2,
    nightFactor: 0.6,
    frames: [
      ...go([...OUT_WEST, { col: 4, row: 11 }, { col: 3, row: 11 }]),
      job({ col: 3, row: 11 }, 9_000, "Wiping down the pantry counter."),
      ...back([...OUT_WEST, { col: 4, row: 11 }, { col: 3, row: 11 }]),
    ],
  },
  {
    id: "maya-bins",
    actor: "maya",
    weight: 1.5,
    nightFactor: 0.6,
    frames: [
      ...go([...OUT_WEST, ...UP_COL4, { col: 5, row: 6 }, { col: 5, row: 5 }], "trolley"),
      job({ col: 5, row: 5 }, 8_000, "Emptying the office bins."),
      ...back([...OUT_WEST, ...UP_COL4, { col: 5, row: 6 }, { col: 5, row: 5 }], "trolley"),
    ],
  },
  {
    id: "maya-reception",
    actor: "maya",
    weight: 1.5,
    nightFactor: 0.4,
    frames: [
      ...go([
        { col: 2, row: 13 },
        { col: 3, row: 13 },
        { col: 4, row: 13 },
        { col: 5, row: 13 },
        { col: 6, row: 12 },
      ]),
      job({ col: 6, row: 12 }, 8_000, "Tidying reception."),
      ...back([
        { col: 2, row: 13 },
        { col: 3, row: 13 },
        { col: 4, row: 13 },
        { col: 5, row: 13 },
        { col: 6, row: 12 },
      ]),
    ],
  },
  {
    id: "maya-plants",
    actor: "maya",
    weight: 1,
    nightFactor: 0.3,
    frames: [
      ...go([
        ...OUT_WEST,
        { col: 6, row: 11 },
        { col: 7, row: 11 },
        { col: 8, row: 11 },
      ]),
      job({ col: 8, row: 11 }, 7_000, "Watering the lounge plants."),
      ...back([
        ...OUT_WEST,
        { col: 6, row: 11 },
        { col: 7, row: 11 },
        { col: 8, row: 11 },
      ]),
    ],
  },
  {
    // The long one: the conference table, after the room has seen use. Rare,
    // and mostly an evening job.
    id: "maya-conference",
    actor: "maya",
    weight: 0.7,
    suppressOnAlert: true,
    nightFactor: 1,
    frames: [
      ...go([
        ...OUT_WEST,
        ...UP_COL4,
        { col: 5, row: 6 },
        { col: 6, row: 6 },
        { col: 7, row: 6 },
        { col: 8, row: 6 },
        { col: 9, row: 6 },
        { col: 9, row: 5 },
        { col: 9, row: 4 },
        { col: 9, row: 3 },
        { col: 9, row: 2 },
        { col: 10, row: 2 },
        { col: 11, row: 2 },
        { col: 12, row: 2 },
        { col: 12, row: 1 },
        { col: 13, row: 1 },
        { col: 14, row: 1 },
        { col: 15, row: 1 },
        { col: 16, row: 1 },
        { col: 17, row: 1 },
        { col: 17, row: 2 },
      ]),
      job({ col: 17, row: 2 }, 10_000, "Cleaning the conference table."),
      ...back([
        ...OUT_WEST,
        ...UP_COL4,
        { col: 5, row: 6 },
        { col: 6, row: 6 },
        { col: 7, row: 6 },
        { col: 8, row: 6 },
        { col: 9, row: 6 },
        { col: 9, row: 5 },
        { col: 9, row: 4 },
        { col: 9, row: 3 },
        { col: 9, row: 2 },
        { col: 10, row: 2 },
        { col: 11, row: 2 },
        { col: 12, row: 2 },
        { col: 12, row: 1 },
        { col: 13, row: 1 },
        { col: 14, row: 1 },
        { col: 15, row: 1 },
        { col: 16, row: 1 },
        { col: 17, row: 1 },
        { col: 17, row: 2 },
      ]),
    ],
  },

  /* ---- Sam ------------------------------------------------------------- */
  {
    id: "sam-cooler",
    actor: "sam",
    weight: 1.5,
    nightFactor: 0.1,
    frames: [
      ...go([
        { col: 3, row: 12 },
        { col: 3, row: 11 },
        { col: 4, row: 11 },
        { col: 5, row: 11 },
      ]),
      job({ col: 5, row: 11 }, 8_000, "Giving the water cooler a once-over."),
      ...back([
        { col: 3, row: 12 },
        { col: 3, row: 11 },
        { col: 4, row: 11 },
        { col: 5, row: 11 },
      ]),
    ],
  },
  {
    id: "sam-printer",
    actor: "sam",
    weight: 1.5,
    nightFactor: 0.1,
    frames: [
      ...go([
        { col: 3, row: 12 },
        { col: 3, row: 11 },
        { col: 4, row: 11 },
        { col: 4, row: 9 },
        { col: 5, row: 8 },
      ]),
      job({ col: 5, row: 8 }, 8_000, "Topping up the printer's paper."),
      ...back([
        { col: 3, row: 12 },
        { col: 3, row: 11 },
        { col: 4, row: 11 },
        { col: 4, row: 9 },
        { col: 5, row: 8 },
      ]),
    ],
  },
  {
    // The rack's outside only. Byte owns what the rack is doing; Sam owns
    // whether its cables are tripping anybody.
    id: "sam-rack",
    actor: "sam",
    weight: 1,
    suppressOnAlert: true,
    nightFactor: 0.1,
    frames: [
      ...go([
        { col: 3, row: 12 },
        { col: 3, row: 11 },
        { col: 4, row: 11 },
        { col: 4, row: 9 },
        { col: 4, row: 6 },
        { col: 5, row: 6 },
        { col: 6, row: 6 },
        { col: 7, row: 6 },
        { col: 8, row: 6 },
        { col: 9, row: 6 },
        { col: 10, row: 6 },
        { col: 10, row: 7 },
        { col: 11, row: 8 },
      ]),
      job({ col: 11, row: 8 }, 8_000, "Tidying the cable spill behind the rack."),
      ...back([
        { col: 3, row: 12 },
        { col: 3, row: 11 },
        { col: 4, row: 11 },
        { col: 4, row: 9 },
        { col: 4, row: 6 },
        { col: 5, row: 6 },
        { col: 6, row: 6 },
        { col: 7, row: 6 },
        { col: 8, row: 6 },
        { col: 9, row: 6 },
        { col: 10, row: 6 },
        { col: 10, row: 7 },
        { col: 11, row: 8 },
      ]),
    ],
  },
  {
    id: "sam-gate",
    actor: "sam",
    weight: 1,
    nightFactor: 0.1,
    frames: [
      ...go([
        { col: 3, row: 13 },
        { col: 4, row: 13 },
        { col: 5, row: 13 },
        { col: 6, row: 12 },
        { col: 8, row: 12 },
        { col: 8, row: 13 },
        { col: 9, row: 13 },
        { col: 10, row: 13 },
        { col: 11, row: 13 },
      ]),
      job({ col: 11, row: 13 }, 7_000, "Testing the reception gate."),
      ...back([
        { col: 3, row: 13 },
        { col: 4, row: 13 },
        { col: 5, row: 13 },
        { col: 6, row: 12 },
        { col: 8, row: 12 },
        { col: 8, row: 13 },
        { col: 9, row: 13 },
        { col: 10, row: 13 },
        { col: 11, row: 13 },
      ]),
    ],
  },
  {
    id: "sam-box",
    actor: "sam",
    weight: 1,
    nightFactor: 0,
    frames: [
      ...go(
        [
          { col: 3, row: 13 },
          { col: 4, row: 13 },
          { col: 5, row: 13 },
          { col: 6, row: 12 },
          { col: 8, row: 12 },
          { col: 8, row: 13 },
        ],
        "box",
      ),
      job({ col: 8, row: 13 }, 6_000, "Dropping supplies at the front desk."),
      ...back([
        { col: 3, row: 13 },
        { col: 4, row: 13 },
        { col: 5, row: 13 },
        { col: 6, row: 12 },
        { col: 8, row: 12 },
        { col: 8, row: 13 },
      ]),
    ],
  },
];

export const SUPPORT_ROUTINES_BY_ACTOR = new Map<SupportId, SupportRoutine[]>(
  SUPPORT_IDS.map((id) => [id, SUPPORT_ROUTINES.filter((routine) => routine.actor === id)]),
);
