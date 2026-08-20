import { STEP_MS, type ActorFrame } from "./ambient";
import type { CharacterLook, Pose } from "./characters";
import type { EmployeeId } from "./employees";
import type { Tile } from "./geometry";

/**
 * PEOPLE FROM OTHER DEPARTMENTS.
 *
 * Somebody from Finance comes up about an invoice, somebody from IT comes to
 * look at a machine. They check in at Reception, walk to the desk they came
 * for, have a short exchange and leave the way they came in. That is the whole
 * feature.
 *
 * ── COSMETIC, AND STRUCTURALLY SO ───────────────────────────────────────
 *
 * A visitor is not a subsystem, has no state, and appears nowhere in
 * `deriveHqState` — exactly like Maya, Sam and the cats, and for the same
 * reason: HQ has ten readouts and every one of them is sourced. An eleventh
 * figure on the floor that *looked* operational would be the first unsourced
 * claim in the room.
 *
 * Their lines are small talk and their `detail` strings never mention a
 * subsystem. The vocabulary test walks them with everyone else.
 *
 * ── WHY THEY ARE BOUNDED, AND HARD ──────────────────────────────────────
 *
 * One visitor at a time, ever. Not a cap that is usually respected — the
 * scheduler counts the class and `MAX_VISITORS` is 1, so two cannot overlap.
 * A lobby that fills up is a different, worse office, and an unbounded
 * cosmetic actor is how an ambient layer starts costing frames.
 *
 * ── WHY THEY LOOK DIFFERENT ─────────────────────────────────────────────
 *
 * Distinct outfits, accessories and palettes, because a visitor who looked
 * like staff would read as an eleventh employee — which is precisely the
 * confusion the roster's whole design avoids. A lanyard and a coat say
 * "guest" faster than any label the stage could draw.
 */

export type VisitorId = "finance" | "it" | "security" | "operations" | "management";

export interface Visitor {
  id: VisitorId;
  name: string;
  /** The department they came from. Never a MEMESCOPE subsystem. */
  from: string;
  /** Shown on the personality panel while they are on the floor. */
  restingDetail: string;
  look: CharacterLook;
}

/**
 * The front door.
 *
 * Reception spans cols 6–21 on rows 12–13. (10,12) is the check-in spot in
 * front of the counter; the corridor north from there is how anyone reaches
 * the working floor.
 */
export const RECEPTION_DESK: Tile = { col: 10, row: 12 };
export const DOOR: Tile = { col: 13, row: 13 };

export const VISITORS: Visitor[] = [
  {
    id: "finance",
    name: "Priya",
    from: "Finance",
    restingDetail: "Visiting from Finance.",
    look: {
      id: "visitor-finance",
      bodyType: "slim",
      headShape: "oval",
      skinTone: "s4",
      hair: "bun",
      hairTone: "h5",
      outfit: "blazer",
      accessory: "clipboard",
      palette: "amber",
      defaultPose: "standing",
    },
  },
  {
    id: "it",
    name: "Kofi",
    from: "IT",
    restingDetail: "Visiting from IT.",
    look: {
      id: "visitor-it",
      bodyType: "compact",
      headShape: "round",
      skinTone: "s5",
      hair: "buzz",
      hairTone: "h4",
      outfit: "utility",
      accessory: "toolbox",
      palette: "cyan",
      defaultPose: "standing",
    },
  },
  {
    id: "security",
    name: "Dana",
    from: "Security",
    restingDetail: "Visiting from Security.",
    look: {
      id: "visitor-security",
      bodyType: "broad",
      headShape: "square",
      skinTone: "s2",
      hair: "cropped",
      hairTone: "h1",
      outfit: "long-coat",
      accessory: "shield-badge",
      palette: "indigo",
      defaultPose: "standing",
    },
  },
  {
    id: "operations",
    name: "Tomas",
    from: "Operations",
    restingDetail: "Visiting from Operations.",
    look: {
      id: "visitor-operations",
      bodyType: "tall",
      headShape: "oval",
      skinTone: "s3",
      hair: "wavy",
      hairTone: "h2",
      outfit: "vest",
      accessory: "clipboard",
      palette: "teal",
      defaultPose: "standing",
    },
  },
  {
    id: "management",
    name: "Iris",
    from: "Management",
    restingDetail: "Visiting from Management.",
    look: {
      id: "visitor-management",
      bodyType: "slim",
      headShape: "oval",
      skinTone: "s1",
      hair: "long-straight",
      hairTone: "h3",
      outfit: "long-coat",
      accessory: "tablet",
      palette: "rose",
      defaultPose: "standing",
    },
  },
];

export const VISITOR_BY_ID = new Map(VISITORS.map((visitor) => [visitor.id, visitor]));
export const VISITOR_IDS = VISITORS.map((visitor) => visitor.id);

/** Never more than one guest on the floor. See the module header. */
export const MAX_VISITORS = 1;

export interface VisitorRoutine {
  id: string;
  actor: VisitorId;
  weight: number;
  frames: ActorFrame[];
  /** The employee they came to see. */
  cast?: Array<{ actor: EmployeeId; frames: ActorFrame[] }>;
  suppressOnAlert?: boolean;
  nightFactor?: number;
}

function go(tiles: Tile[], pose: Pose = "walking_short"): ActorFrame[] {
  return tiles.map((tile) => ({ pose, tile, hold: STEP_MS }));
}

/**
 * Reception to the working floor.
 *
 * Up the reception hall, through the pantry corridor and onto the walkway,
 * which is the one route from the front door to every department. Authored, so
 * the route tests cover it like every other walk in the building.
 */
const LOBBY_TO_FLOOR: Tile[] = [
  DOOR,
  { col: 13, row: 12 },
  { col: 12, row: 12 },
  { col: 11, row: 12 },
  RECEPTION_DESK,
  { col: 10, row: 11 },
  { col: 10, row: 10 },
  { col: 9, row: 10 },
  { col: 9, row: 9 },
  { col: 8, row: 9 },
  { col: 8, row: 8 },
  { col: 8, row: 7 },
  { col: 8, row: 6 },
];

/**
 * One visit: in, check in, walk to a desk, a word, and back out.
 *
 * The check-in hold at the counter is what makes Reception mean something.
 * Without it a visitor is just a person walking diagonally across the office.
 */
/** Where `LOBBY_TO_FLOOR` reaches the counter. Derived, never hand-counted. */
const CHECK_IN_INDEX = LOBBY_TO_FLOOR.findIndex(
  (tile) => tile.col === RECEPTION_DESK.col && tile.row === RECEPTION_DESK.row,
);

function visit(
  id: string,
  actor: VisitorId,
  target: EmployeeId,
  approach: Tile[],
  greeting: string,
  reply: string,
): VisitorRoutine {
  const at = approach.at(-1)!;
  const route = [...LOBBY_TO_FLOOR, ...approach];
  return {
    id,
    actor,
    weight: 1,
    suppressOnAlert: true,
    nightFactor: 0,
    frames: [
      // Walk to the counter, *then* stand at it. Holding at the desk straight
      // after the door teleported the guest three tiles across the lobby —
      // which is the one thing every walk in this building may not do.
      ...go(LOBBY_TO_FLOOR.slice(0, CHECK_IN_INDEX + 1)),
      { pose: "standing", tile: RECEPTION_DESK, hold: 4_200, detail: "Checking in at Reception." },
      ...go(route.slice(CHECK_IN_INDEX + 1)),
      { pose: "talking_briefly", tile: at, hold: 4_600, detail: "Talking with the desk.", speech: greeting },
      { pose: "standing", tile: at, hold: 3_000, detail: "Listening." },
      ...go([...route].reverse(), "returning_to_desk"),
      { pose: "returning_to_desk", hold: STEP_MS },
    ],
    cast: [
      {
        actor: target,
        frames: [
          { pose: "seated_working", hold: STEP_MS * (route.length + 2) },
          { pose: "talking_briefly", hold: 4_600, detail: "Talking with a visitor.", speech: reply },
          { pose: "seated_working", hold: 3_000 },
        ],
      },
    ],
  };
}

export const VISITOR_ROUTINES: VisitorRoutine[] = [
  visit("visit-finance-milo", "finance", "milo", [{ col: 7, row: 6 }, { col: 6, row: 6 }, { col: 5, row: 6 }, { col: 4, row: 6 }, { col: 3, row: 6 }, { col: 2, row: 6 }, { col: 2, row: 7 }], "Got a minute?", "Sure."),
  visit("visit-it-byte", "it", "byte", [{ col: 9, row: 6 }, { col: 9, row: 7 }], "Here about the machine.", "Over here."),
  visit(
    "visit-security-atlas",
    "security",
    "atlas",
    // Row 5 is the only clear lane west: (6,3) is Radar's desk, (5,4) and
    // (2,4) are Atlas's own. The approach stops at (2,5), beside him.
    [
      { col: 8, row: 5 },
      { col: 7, row: 5 },
      { col: 6, row: 5 },
      { col: 5, row: 5 },
      { col: 4, row: 5 },
      { col: 3, row: 5 },
      { col: 2, row: 5 },
    ],
    "Badge renewals.",
    "Right, thanks.",
  ),
  visit("visit-ops-echo", "operations", "echo", [{ col: 7, row: 6 }, { col: 6, row: 6 }, { col: 6, row: 7 }], "Dropping this off.", "Appreciated."),
  visit(
    "visit-management-nova",
    "management",
    "nova",
    // Up column 9, not column 8: (8,3) is Luna's desk and (8,4) is hers.
    [{ col: 9, row: 6 }, { col: 9, row: 5 }, { col: 9, row: 4 }, { col: 9, row: 3 }, { col: 9, row: 2 }, { col: 9, row: 1 }],
    "Is she free?",
    "Come through.",
  ),
];
