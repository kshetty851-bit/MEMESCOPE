import type { Pose } from "./characters";
import { EMPLOYEES, EMPLOYEE_BY_ID, type EmployeeId } from "./employees";
import { CONFERENCE_SEATS, FURNITURE_BLOCKED, LOUNGE_CHAIR_SEAT, SOFA_SEAT } from "./furniture";
import { GRID_COLS, isInsideRoom, type Tile } from "./geometry";
import { ZONE_BY_ID } from "./zones";

/**
 * AMBIENT PERSONALITY — THE DATA.
 *
 * HQ-3 makes the room feel inhabited. Nothing here is operational and nothing
 * here may ever become operational: an ambient routine is a *presentation*
 * layer that says "this is a staffed office", never "this subsystem is doing
 * work". The priority the plan sets is
 *
 *     REAL ALERT / REAL WORK  >  REAL NORMAL STATE  >  AMBIENT PERSONALITY
 *
 * and this file implements only the bottom rung. HQ-4 introduces the layers
 * above it, and the way it will do that is by refusing to schedule an ambient
 * routine for anyone whose real state is above `idle`. That is the reason this
 * file exports data and a pure picker rather than owning the render: an
 * ambient state that could not be *out-voted* would be a lie waiting to happen.
 *
 * ONE MECHANISM, NOT SIX
 *
 * Idle variation, walks to the break room, micro-interactions between
 * colleagues and the rare easter eggs are all the same thing: a short timeline
 * of poses, optionally at tiles away from the desk, optionally with a second
 * person playing along. So there is one type and one player, rather than an
 * idle system, a walk system, an interaction system and an egg system that
 * each need their own scheduling, their own cancellation and their own bugs.
 *
 * PEOPLE STAND BESIDE FURNITURE, NOT ON IT
 *
 * Every break-room destination is the tile next to its fixture rather than the
 * fixture's own tile. Employees paint after all furniture, so somebody sent to
 * the coffee machine's tile stands in front of the machine and hides it — the
 * walk then reads as a person crossing the room to look at a wall. One tile of
 * offset is the whole fix.
 *
 * WALKS ARE ROUTES, NOT PATHFINDING
 *
 * Every destination is reached through hand-authored waypoints. A* over a
 * sixteen-by-twelve grid would be more code, more runtime and more ways to
 * walk someone through a desk. Waypoints are data, so the tests can assert
 * that no frame stands inside the furniture and that nobody leaves the room —
 * checks that a pathfinder would need a simulation to make.
 */

/** The rare, harmless events. Deliberately few, and none of them is a claim. */
export type EggId = "doze" | "telescope" | "coffee-run";

/**
 * The frame every kind of actor shares: a pose name, an optional tile, a
 * duration. Employees narrow `pose` to the rig's `Pose` union; cats have a
 * vocabulary of their own. The scheduler plays either without knowing which.
 */
export interface ActorFrame {
  pose: string;
  tile?: Tile;
  hold: number;
  /** Something visibly carried — Maya's trolley, Sam's box. */
  carry?: "trolley" | "box";
  detail?: string;
  /**
   * A short line to show in a speech bubble above this actor.
   *
   * Separate from `detail`, which every routine already sets and which feeds
   * the personality panel. If a bubble were drawn for any frame carrying a
   * detail, the office would fill with floating text the moment anybody made
   * coffee. Speaking is a deliberate act, so it needs its own field.
   */
  speech?: string;
}

export interface AmbientFrame extends ActorFrame {
  pose: Pose;
  /** Drives a small extra CSS pose tweak. Easter eggs only. */
  egg?: EggId;
}

export interface AmbientRoutine {
  id: string;
  employee: EmployeeId;
  /** Relative pick frequency among that employee's routines. */
  weight: number;
  frames: AmbientFrame[];
  /**
   * Colleagues who play along — one for the old two-person interactions, up
   * to four for a conference meeting. Everyone listed must be free for the
   * routine to start, and everyone is released when the longest timeline
   * ends.
   */
  cast?: Array<{ employee: EmployeeId; frames: AmbientFrame[] }>;
  /**
   * A conference meeting. At most one runs at a time, it may exceed the
   * normal away-from-desk cap (it is its own bounded thing), and it is
   * suppressed outright while the office is at HIGH_ALERT — a room in
   * trouble does not hold a casual team sync.
   */
  meeting?: boolean;
  /** Skipped while the office is at HIGH_ALERT. Meetings imply this. */
  suppressOnAlert?: boolean;
  /**
   * Weight multiplier after dark, 0–1. The office quietens at night without
   * ever closing: fewer errands, no meetings, the same people at the same
   * desks.
   */
  nightFactor?: number;
}

/* ---------------------------------------------------------------------- */

/**
 * Tiles a walking employee must never stand on.
 *
 * Every desk, plus the row against the back wall. Derived from the roster
 * rather than restated, so moving a desk cannot silently open a route through
 * it — the test that checks routes reads the same list.
 */
export const BLOCKED_TILES: Tile[] = [
  ...EMPLOYEES.map((employee) => employee.desk),
  // The row against the back wall, across the whole expanded width.
  ...Array.from({ length: GRID_COLS }, (_, col) => ({ col, row: 0 })),
  // Furniture, the conference table, the glass wall, and every vault tile —
  // the vault is sealed to feet as well as to funds.
  ...FURNITURE_BLOCKED,
];

export function isBlockedTile(tile: Tile): boolean {
  return BLOCKED_TILES.some((blocked) => blocked.col === tile.col && blocked.row === tile.row);
}

/** Is this tile somewhere a person could legally stand? */
export function isWalkable(tile: Tile, walker: EmployeeId): boolean {
  if (!isInsideRoom(tile)) return false;
  const own = EMPLOYEE_BY_ID.get(walker)?.desk;
  if (own && own.col === tile.col && own.row === tile.row) return true;
  return !isBlockedTile(tile);
}

const PANTRY_RECT = ZONE_BY_ID.get("pantry")!.rect;
const LOUNGE_RECT = ZONE_BY_ID.get("lounge")!.rect;

function inRect(tile: Tile, rect: { col: number; row: number; cols: number; rows: number }) {
  return (
    tile.col >= rect.col &&
    tile.col < rect.col + rect.cols &&
    tile.row >= rect.row &&
    tile.row < rect.row + rect.rows
  );
}

/** The old break room is now two rooms; the occupancy cap covers both. */
export function isInBreakRoom(tile: Tile): boolean {
  return inRect(tile, PANTRY_RECT) || inRect(tile, LOUNGE_RECT);
}

export function visitsBreakRoom(routine: { frames: Array<{ tile?: Tile }> }): boolean {
  return routine.frames.some((frame) => frame.tile && isInBreakRoom(frame.tile));
}

/** Routines that move someone off their desk tile. Counted in the phase report. */
export function isWalk(routine: AmbientRoutine): boolean {
  return routine.frames.some((frame) => frame.tile !== undefined);
}

/* ---------------------------------------------------------------------- */

/** How long one walking step holds. Matches the CSS transition on `.hq-walker`. */
export const STEP_MS = 2600;

/**
 * Out, do a thing, come back.
 *
 * The last waypoint is the destination; the return is the same route reversed,
 * which is what keeps a walk off the furniture in both directions. Building
 * the frames rather than writing them out is not cleverness — a hand-written
 * return path is exactly where someone eventually drops a waypoint and walks
 * Byte diagonally through the server stack.
 */
function trip(
  waypoints: Tile[],
  activity: { pose: Pose; hold: number; egg?: EggId },
): AmbientFrame[] {
  const destination = waypoints[waypoints.length - 1]!;
  const out: AmbientFrame[] = waypoints.map((tile) => ({
    pose: "walking_short" as Pose,
    tile,
    hold: STEP_MS,
  }));
  const back: AmbientFrame[] = waypoints
    .slice(0, -1)
    .reverse()
    .map((tile) => ({ pose: "returning_to_desk" as Pose, tile, hold: STEP_MS }));

  return [
    ...out,
    { pose: activity.pose, tile: destination, hold: activity.hold, egg: activity.egg },
    ...back,
    // No tile: they are home. The routine ends and the character falls back to
    // their default pose.
    { pose: "returning_to_desk", hold: STEP_MS },
  ];
}

/* ---------------------------------------------------------------------- */

/**
 * THE ROSTER'S IDLE VOCABULARY.
 *
 * Each person's tendencies, from the brief. Weights are relative within one
 * employee: Atlas's stillness is a heavy weight on a long, motionless frame,
 * not a special case in the scheduler. Nobody is animated *often* — the
 * scheduler runs three people at a time out of ten, which is what an office
 * actually looks like.
 */
export const AMBIENT_ROUTINES: AmbientRoutine[] = [
  /* ---- Nova: standing overview, tablet, a short walk, rarely coffee ---- */
  { id: "nova-overview", employee: "nova", weight: 5, frames: [{ pose: "standing", hold: 9000 }] },
  { id: "nova-tablet", employee: "nova", weight: 4, frames: [{ pose: "holding_tablet", hold: 7000 }] },
  {
    id: "nova-board",
    employee: "nova",
    weight: 3,
    frames: [
      { pose: "walking_short", tile: { col: 10, row: 1 }, hold: STEP_MS },
      { pose: "holding_tablet", tile: { col: 10, row: 1 }, hold: 6500 },
      { pose: "returning_to_desk", hold: STEP_MS },
    ],
  },
  {
    // Nova visits a department. The only micro-interaction that involves a walk
    // across the room, because it is the one the director would actually make.
    id: "nova-visit",
    employee: "nova",
    weight: 2,
    frames: trip(
      [
        { col: 8, row: 2 },
        { col: 8, row: 6 },
        { col: 7, row: 7 },
      ],
      { pose: "talking_briefly", hold: 5200 },
    ),
    cast: [{
      employee: "echo",
      frames: [
        { pose: "standing", hold: STEP_MS * 3 },
        { pose: "talking_briefly", hold: 5200 },
        { pose: "standing", hold: 2000 },
      ],
    }],
  },
  {
    id: "nova-coffee",
    employee: "nova",
    weight: 1,
    frames: trip(
      [
        { col: 8, row: 2 },
        { col: 8, row: 6 },
        { col: 4, row: 6 },
        { col: 4, row: 9 },
        { col: 4, row: 11 },
        { col: 3, row: 11 },
      ],
      { pose: "coffee_idle", hold: 9000, egg: "coffee-run" },
    ),
  },

  /* ---- Radar: fast, leans into the feed, rarely stays away ------------- */
  { id: "radar-lean", employee: "radar", weight: 5, frames: [{ pose: "looking_at_screen", hold: 5000 }] },
  { id: "radar-headset", employee: "radar", weight: 4, frames: [{ pose: "talking_briefly", hold: 3200 }] },
  {
    id: "radar-screens",
    employee: "radar",
    weight: 4,
    frames: [
      { pose: "seated_working", hold: 2000 },
      { pose: "looking_at_screen", hold: 2400 },
      { pose: "seated_working", hold: 2000 },
    ],
  },
  {
    // Radar briefly shows Luna something. They sit two tiles apart, so this is
    // a gesture and a glance rather than a walk.
    id: "radar-luna",
    employee: "radar",
    weight: 2,
    frames: [
      { pose: "talking_briefly", hold: 3600 },
      { pose: "looking_at_screen", hold: 2400 },
    ],
    cast: [{
      employee: "luna",
      frames: [
        { pose: "looking_at_screen", hold: 3600 },
        { pose: "seated_reviewing", hold: 2400 },
      ],
    }],
  },
  {
    // Radar goes for water and comes straight back. Short on purpose.
    id: "radar-water",
    employee: "radar",
    weight: 1,
    frames: trip(
      [
        { col: 6, row: 6 },
        { col: 7, row: 7 },
        { col: 7, row: 11 },
        { col: 6, row: 11 },
      ],
      { pose: "coffee_idle", hold: 3600 },
    ),
  },
  {
    id: "radar-telescope",
    employee: "radar",
    weight: 1,
    frames: trip(
      [
        { col: 6, row: 2 },
        { col: 5, row: 1 },
        { col: 3, row: 1 },
      ],
      { pose: "standing", hold: 8000, egg: "telescope" },
    ),
  },

  /* ---- Luna: slow chart review, notes, stylus ------------------------- */
  { id: "luna-chart", employee: "luna", weight: 5, frames: [{ pose: "seated_reviewing", hold: 10000 }] },
  { id: "luna-notes", employee: "luna", weight: 3, frames: [{ pose: "seated_working", hold: 6000 }] },
  {
    id: "luna-stylus",
    employee: "luna",
    weight: 3,
    frames: [
      { pose: "looking_at_screen", hold: 3000 },
      { pose: "seated_working", hold: 3400 },
      { pose: "looking_at_screen", hold: 3000 },
    ],
  },

  /* ---- Dex: switches monitors, coffee, quick head turns --------------- */
  {
    id: "dex-switch",
    employee: "dex",
    weight: 5,
    frames: [
      { pose: "looking_at_screen", hold: 1900 },
      { pose: "seated_working", hold: 1900 },
      { pose: "looking_at_screen", hold: 1900 },
      { pose: "seated_working", hold: 1900 },
    ],
  },
  { id: "dex-coffee", employee: "dex", weight: 3, frames: [{ pose: "coffee_idle", hold: 4200 }] },
  {
    id: "dex-turns",
    employee: "dex",
    weight: 3,
    frames: [
      { pose: "seated_reviewing", hold: 1800 },
      { pose: "seated_working", hold: 2400 },
    ],
  },
  {
    id: "dex-water",
    employee: "dex",
    weight: 2,
    frames: trip(
      [
        { col: 10, row: 6 },
        { col: 7, row: 6 },
        { col: 7, row: 11 },
        { col: 6, row: 11 },
      ],
      { pose: "coffee_idle", hold: 8000 },
    ),
  },

  /* ---- Atlas: restrained. Heavy weight on stillness. ------------------ */
  { id: "atlas-checklist", employee: "atlas", weight: 8, frames: [{ pose: "seated_reviewing", hold: 14000 }] },
  {
    id: "atlas-scan",
    employee: "atlas",
    weight: 3,
    frames: [
      { pose: "seated_reviewing", hold: 3000 },
      { pose: "looking_at_screen", hold: 6000 },
      { pose: "seated_reviewing", hold: 3000 },
    ],
  },
  {
    // He does leave, once in a long while. "Rarely" is a weight, not an absence.
    id: "atlas-break",
    employee: "atlas",
    weight: 1,
    frames: trip(
      [
        { col: 2, row: 6 },
        { col: 4, row: 6 },
        { col: 4, row: 9 },
        { col: 4, row: 11 },
        { col: 3, row: 11 },
      ],
      { pose: "coffee_idle", hold: 5000 },
    ),
  },

  /* ---- Milo: portfolio wall, thoughtful pause, clipboard -------------- */
  {
    id: "milo-wall",
    employee: "milo",
    weight: 5,
    frames: [
      { pose: "standing", hold: 3200 },
      { pose: "holding_tablet", hold: 4200 },
      { pose: "standing", hold: 3200 },
    ],
  },
  {
    id: "milo-pause",
    employee: "milo",
    weight: 4,
    frames: [
      { pose: "holding_tablet", hold: 3000 },
      { pose: "standing", hold: 7000 },
    ],
  },
  {
    // Milo and Sage review the same board from opposite ends of the room. No
    // walk: they are eight tiles apart and a crossing would read as an errand.
    id: "milo-sage",
    employee: "milo",
    weight: 2,
    frames: [
      { pose: "standing", hold: 3000 },
      { pose: "talking_briefly", hold: 3600 },
    ],
    cast: [{
      employee: "sage",
      frames: [
        { pose: "seated_reviewing", hold: 3000 },
        { pose: "talking_briefly", hold: 3600 },
      ],
    }],
  },

  /* ---- Rex: terminal input, wrist check, restrained confidence -------- */
  { id: "rex-terminal", employee: "rex", weight: 5, frames: [{ pose: "seated_working", hold: 8000 }] },
  {
    id: "rex-wrist",
    employee: "rex",
    weight: 3,
    frames: [
      { pose: "seated_working", hold: 2200 },
      { pose: "seated_reviewing", hold: 3000 },
      { pose: "seated_working", hold: 2200 },
    ],
  },
  {
    id: "rex-focus",
    employee: "rex",
    weight: 3,
    frames: [
      { pose: "looking_at_screen", hold: 4000 },
      { pose: "seated_working", hold: 3000 },
    ],
  },
  {
    id: "rex-milo",
    employee: "rex",
    weight: 1,
    frames: [
      { pose: "talking_briefly", hold: 2800 },
      { pose: "seated_working", hold: 2400 },
    ],
    cast: [{
      employee: "milo",
      frames: [
        { pose: "talking_briefly", hold: 2800 },
        { pose: "standing", hold: 2400 },
      ],
    }],
  },

  /* ---- Echo: never at one terminal for long -------------------------- */
  {
    id: "echo-terminals",
    employee: "echo",
    weight: 5,
    frames: trip(
      [
        { col: 7, row: 7 },
        { col: 8, row: 7 },
      ],
      { pose: "holding_tablet", hold: 5000 },
    ),
  },
  { id: "echo-queue", employee: "echo", weight: 4, frames: [{ pose: "holding_tablet", hold: 6000 }] },
  {
    id: "echo-headset",
    employee: "echo",
    weight: 3,
    frames: [
      { pose: "talking_briefly", hold: 2600 },
      { pose: "standing", hold: 3000 },
      { pose: "talking_briefly", hold: 2600 },
    ],
  },
  {
    id: "echo-byte",
    employee: "echo",
    weight: 2,
    frames: trip(
      [
        { col: 7, row: 8 },
        { col: 8, row: 8 },
      ],
      { pose: "talking_briefly", hold: 4200 },
    ),
    cast: [{
      employee: "byte",
      frames: [
        { pose: "seated_working", hold: STEP_MS * 2 },
        { pose: "talking_briefly", hold: 4200 },
        { pose: "seated_working", hold: 2000 },
      ],
    }],
  },

  /* ---- Byte: types, server stack, coffee, tired stretch, naps --------- */
  { id: "byte-types", employee: "byte", weight: 5, frames: [{ pose: "seated_working", hold: 7000 }] },
  {
    id: "byte-servers",
    employee: "byte",
    weight: 3,
    frames: trip([{ col: 10, row: 7 }], { pose: "standing", hold: 5000 }),
  },
  {
    id: "byte-coffee",
    employee: "byte",
    weight: 3,
    frames: trip(
      [
        { col: 9, row: 9 },
        { col: 10, row: 10 },
        { col: 10, row: 11 },
      ],
      // Standing with a mug beside the sofa, not sitting on it: a seated pose
      // away from a desk would need a second seated rig for one animation.
      { pose: "coffee_idle", hold: 11000 },
    ),
  },
  {
    id: "byte-stretch",
    employee: "byte",
    weight: 2,
    frames: [
      { pose: "stretching", hold: 3000 },
      { pose: "seated_working", hold: 3000 },
    ],
  },
  {
    id: "byte-doze",
    employee: "byte",
    weight: 1,
    frames: [{ pose: "seated_reviewing", hold: 6500, egg: "doze" }],
  },

  /* ---- Sage: slow, analytical, occasionally looks out ---------------- */
  { id: "sage-charts", employee: "sage", weight: 5, frames: [{ pose: "seated_reviewing", hold: 11000 }] },
  {
    id: "sage-notes",
    employee: "sage",
    weight: 3,
    frames: [
      { pose: "seated_working", hold: 3400 },
      { pose: "seated_reviewing", hold: 5000 },
    ],
  },
  {
    id: "sage-slow",
    employee: "sage",
    weight: 3,
    frames: [
      { pose: "looking_at_screen", hold: 4000 },
      { pose: "seated_reviewing", hold: 5000 },
    ],
  },
  {
    id: "sage-window",
    employee: "sage",
    weight: 1,
    frames: trip(
      [
        { col: 13, row: 9 },
        { col: 13, row: 11 },
        { col: 14, row: 11 },
      ],
      { pose: "standing", hold: 7000 },
    ),
  },
];

/* ---------------------------------------------------------------------- */

/**
 * WALKING HELPERS FOR THE LONG TRIPS.
 *
 * The conference room and the deck live in the east wing, and reaching them
 * from the west desks is a fifteen-tile walk. Authoring each frame by hand at
 * that length is where a typo walks somebody through the vault, so the long
 * routes are assembled from named corridor segments that the collision tests
 * check once.
 */
const STEP: number = STEP_MS;

function walk(tiles: Tile[], pose: Pose = "walking_short"): AmbientFrame[] {
  return tiles.map((tile) => ({ pose, tile, hold: STEP }));
}

function walkHome(tiles: Tile[]): AmbientFrame[] {
  return [
    ...walk([...tiles].reverse(), "returning_to_desk"),
    { pose: "returning_to_desk", hold: STEP },
  ];
}

/** Column 9, the one clear north–south line through the trading floor. */
const SPINE_UP: Tile[] = [
  { col: 9, row: 5 },
  { col: 9, row: 4 },
  { col: 9, row: 3 },
  { col: 9, row: 2 },
];

/** Row 2 east of the spine, then up onto the row-1 corridor past the vault. */
const ROW2_EAST: Tile[] = [
  { col: 10, row: 2 },
  { col: 11, row: 2 },
  { col: 12, row: 2 },
  { col: 12, row: 1 },
];

/** Row 1 from the vault's shoulder to the conference doorway. */
const ROW1_TO_DOOR: Tile[] = [
  { col: 13, row: 1 },
  { col: 14, row: 1 },
  { col: 15, row: 1 },
  { col: 16, row: 1 },
  { col: 17, row: 1 },
];

/** Walkway tiles from a column to the spine's foot, heading east. */
function walkwayEast(fromCol: number): Tile[] {
  const tiles: Tile[] = [];
  for (let col = fromCol; col <= 9; col += 1) tiles.push({ col, row: 6 });
  return tiles;
}

/**
 * Desk to conference doorway, per participant. Authored, not solved: every
 * tile here is covered by the route-collision tests, and a change to the
 * floor plan fails a test rather than a person.
 */
const TO_CONFERENCE: Partial<Record<EmployeeId, Tile[]>> = {
  nova: [
    ...walk([]).map((f) => f.tile!),
    { col: 9, row: 1 },
    { col: 10, row: 1 },
    { col: 11, row: 1 },
    { col: 12, row: 1 },
    ...ROW1_TO_DOOR,
  ],
  radar: [
    { col: 6, row: 2 },
    { col: 7, row: 2 },
    { col: 8, row: 2 },
    { col: 9, row: 2 },
    ...ROW2_EAST,
    ...ROW1_TO_DOOR,
  ],
  luna: [
    { col: 8, row: 2 },
    { col: 9, row: 2 },
    ...ROW2_EAST,
    ...ROW1_TO_DOOR,
  ],
  dex: [{ col: 10, row: 2 }, { col: 11, row: 2 }, { col: 12, row: 2 }, { col: 12, row: 1 }, ...ROW1_TO_DOOR],
  milo: [
    { col: 2, row: 7 },
    { col: 2, row: 6 },
    ...walkwayEast(3),
    ...SPINE_UP,
    ...ROW2_EAST,
    ...ROW1_TO_DOOR,
  ],
  sage: [
    { col: 13, row: 7 },
    { col: 13, row: 6 },
    { col: 12, row: 6 },
    { col: 11, row: 6 },
    { col: 10, row: 6 },
    { col: 9, row: 6 },
    ...SPINE_UP,
    ...ROW2_EAST,
    ...ROW1_TO_DOOR,
  ],
  echo: [
    { col: 6, row: 7 },
    { col: 6, row: 6 },
    ...walkwayEast(7),
    ...SPINE_UP,
    ...ROW2_EAST,
    ...ROW1_TO_DOOR,
  ],
  byte: [{ col: 9, row: 7 }, { col: 9, row: 6 }, ...SPINE_UP, ...ROW2_EAST, ...ROW1_TO_DOOR],
  // Atlas and Rex were the two nobody ever invited: the ambient syncs are
  // three- and four-person, and neither was ever cast. The report meeting is
  // the whole company, so both need a route, authored to the same rule as the
  // rest — join the walkway, take the spine, then the row-1 corridor.
  atlas: [
    { col: 2, row: 5 },
    { col: 2, row: 6 },
    ...walkwayEast(3),
    ...SPINE_UP,
    ...ROW2_EAST,
    ...ROW1_TO_DOOR,
  ],
  rex: [
    { col: 12, row: 5 },
    { col: 12, row: 6 },
    { col: 11, row: 6 },
    { col: 10, row: 6 },
    { col: 9, row: 6 },
    ...SPINE_UP,
    ...ROW2_EAST,
    ...ROW1_TO_DOOR,
  ],
};

/**
 * Desk-to-conference routes, exported for the report meeting.
 *
 * The report meeting composes its own timelines rather than reusing `attend`
 * — it has a dialogue order, overflow standing positions and an open-ended
 * hold that the ambient syncs do not — but it must walk people along the
 * *same* authored tiles, because those are the ones the route-collision tests
 * cover. A second set of routes would be a second set of ways to walk
 * somebody through a desk.
 */
export const CONFERENCE_ROUTES: Readonly<Partial<Record<EmployeeId, Tile[]>>> = TO_CONFERENCE;

/** Doorway-to-seat approach, exported for the same reason. */
export function conferenceApproach(seat: Tile): Tile[] {
  return doorToSeat(seat);
}

/** From the doorway-adjacent tile (17,1) to a seat. */
function doorToSeat(seat: Tile): Tile[] {
  if (seat.row === 1) {
    const tiles: Tile[] = [];
    for (let col = 18; col <= seat.col; col += 1) tiles.push({ col, row: 1 });
    return tiles;
  }
  // South row: around the table's west end.
  const tiles: Tile[] = [
    { col: 17, row: 2 },
    { col: 17, row: 3 },
  ];
  for (let col = 18; col <= seat.col; col += 1) tiles.push({ col, row: 3 });
  return tiles;
}

/**
 * One participant's whole meeting timeline.
 *
 * A staggered wait at the desk, the walk, a seat, alternating listening and
 * speaking, then the walk home. The stagger keeps four people from moving in
 * lockstep, which reads as a fire drill rather than a meeting.
 */
function attend(
  employee: EmployeeId,
  seat: Tile,
  order: number,
  minutes: number,
  topic: string,
): AmbientFrame[] {
  const route = [...TO_CONFERENCE[employee]!, ...doorToSeat(seat)];
  const seatedMs = minutes * 60_000;
  const talk = Math.round(seatedMs / 4);
  return [
    { pose: "looking_at_screen", hold: 1200 + order * 1600 },
    ...walk(route),
    { pose: "seated_lounge", tile: seat, hold: talk, detail: topic },
    { pose: "seated_talk", tile: seat, hold: talk, detail: topic },
    { pose: "seated_lounge", tile: seat, hold: talk, detail: topic },
    { pose: "seated_talk", tile: seat, hold: talk, detail: topic },
    ...walkHome(route),
  ];
}

/**
 * A generic ambient meeting.
 *
 * Ambient means exactly that: these are the syncs any staffed office holds,
 * and their names say nothing operational. There is no "incident review", no
 * "emergency", no "winner celebration" — a meeting that claims a reason needs
 * a real, sourced reason, and that wiring belongs to a later phase with
 * evidence rules, not to the ambient layer.
 */
function meeting(
  id: string,
  weight: number,
  topic: string,
  attendees: Array<[EmployeeId, Tile]>,
  minutes = 1.2,
): AmbientRoutine {
  const [owner, ...others] = attendees;
  return {
    id,
    employee: owner![0],
    weight,
    meeting: true,
    suppressOnAlert: true,
    nightFactor: 0,
    frames: attend(owner![0], owner![1], 0, minutes, topic),
    cast: others.map(([employee, seat], index) => ({
      employee,
      frames: attend(employee, seat, index + 1, minutes, topic),
    })),
  };
}

const SEAT = CONFERENCE_SEATS;

export const MEETING_ROUTINES: AmbientRoutine[] = [
  meeting("meet-team", 2, "In the team sync.", [
    ["nova", SEAT[0]!],
    ["radar", SEAT[1]!],
    ["milo", SEAT[2]!],
    ["sage", SEAT[3]!],
  ]),
  meeting("meet-portfolio", 1.5, "Talking through the portfolio.", [
    ["nova", SEAT[0]!],
    ["milo", SEAT[1]!],
    ["sage", SEAT[2]!],
  ]),
  meeting("meet-discovery", 1.5, "Reviewing discovery together.", [
    ["radar", SEAT[0]!],
    ["luna", SEAT[1]!],
    ["dex", SEAT[3]!],
  ]),
  meeting("meet-ops", 1.5, "In the operations sync.", [
    ["echo", SEAT[0]!],
    ["byte", SEAT[1]!],
    ["nova", SEAT[2]!],
  ]),
];

/* ---------------------------------------------------------------------- */

/**
 * The world-expansion routines: the deck, the lounge and its sofa, and the
 * pantry's extra errand. Same machinery as everything above — a timeline of
 * poses at tiles — which is the entire reason the expansion could reuse the
 * scheduler instead of growing a second one.
 */
const DECK_TO_18: Tile[] = [
  { col: 12, row: 5 },
  { col: 12, row: 6 },
  { col: 13, row: 6 },
  { col: 14, row: 6 },
  { col: 15, row: 6 },
  { col: 16, row: 6 },
  { col: 17, row: 6 },
  { col: 18, row: 6 },
];

const LOUNGE_FROM_LAB: Tile[] = [
  { col: 13, row: 9 },
  { col: 13, row: 11 },
  { col: 12, row: 11 },
  { col: 11, row: 11 },
  { col: 10, row: 11 },
];

/** Milo's authored path to the lounge chair. */
const MILO_TO_LOUNGE: Tile[] = [
  { col: 2, row: 9 },
  { col: 3, row: 9 },
  { col: 4, row: 9 },
  { col: 4, row: 11 },
  { col: 5, row: 11 },
  { col: 6, row: 11 },
  { col: 7, row: 11 },
  { col: 8, row: 11 },
  { col: 9, row: 10 },
  { col: 10, row: 10 },
  { col: 11, row: 10 },
];

export const EXPANSION_ROUTINES: AmbientRoutine[] = [
  {
    // Rex steps out through the airlock. The one routine that uses the deck's
    // whole length, and the reason the airlock sits where the walkway ends.
    id: "rex-deck",
    employee: "rex",
    weight: 1,
    suppressOnAlert: true,
    nightFactor: 0.4,
    frames: [
      ...walk(DECK_TO_18),
      { pose: "standing", tile: { col: 18, row: 6 }, hold: 9_000, detail: "Out on the deck, watching the black." },
      ...walkHome(DECK_TO_18),
    ],
  },
  {
    id: "echo-deck",
    employee: "echo",
    weight: 1,
    suppressOnAlert: true,
    nightFactor: 0.4,
    frames: [
      ...walk([
        { col: 6, row: 7 },
        { col: 6, row: 6 },
        { col: 7, row: 6 },
        { col: 8, row: 6 },
        { col: 9, row: 6 },
        { col: 10, row: 6 },
        { col: 11, row: 6 },
        { col: 12, row: 6 },
        { col: 13, row: 6 },
        { col: 14, row: 6 },
        { col: 15, row: 6 },
        { col: 16, row: 6 },
        { col: 17, row: 6 },
      ]),
      { pose: "coffee_idle", tile: { col: 17, row: 6 }, hold: 8_000, detail: "Coffee on the deck." },
      ...walkHome([
        { col: 6, row: 7 },
        { col: 6, row: 6 },
        { col: 7, row: 6 },
        { col: 8, row: 6 },
        { col: 9, row: 6 },
        { col: 10, row: 6 },
        { col: 11, row: 6 },
        { col: 12, row: 6 },
        { col: 13, row: 6 },
        { col: 14, row: 6 },
        { col: 15, row: 6 },
        { col: 16, row: 6 },
        { col: 17, row: 6 },
      ]),
    ],
  },
  {
    // The sofa, at last. HQ-3 deferred proper sitting because the rig had no
    // lounge stance; now it does, and the seat is the cushion the sofa was
    // drawn with.
    id: "sage-sofa",
    employee: "sage",
    weight: 1.5,
    nightFactor: 0.6,
    frames: [
      ...walk(LOUNGE_FROM_LAB),
      { pose: "seated_lounge", tile: SOFA_SEAT, hold: 16_000, detail: "Reading on the lounge sofa." },
      ...walkHome(LOUNGE_FROM_LAB),
    ],
  },
  {
    id: "luna-sofa",
    employee: "luna",
    weight: 1,
    nightFactor: 0.5,
    frames: [
      ...walk([
        { col: 8, row: 4 },
        { col: 8, row: 5 },
        { col: 8, row: 6 },
        { col: 8, row: 7 },
        { col: 8, row: 8 },
        { col: 8, row: 9 },
        { col: 9, row: 9 },
        { col: 10, row: 10 },
        { col: 10, row: 11 },
      ]),
      { pose: "seated_lounge", tile: SOFA_SEAT, hold: 13_000, detail: "Reading notes away from the desk." },
      ...walkHome([
        { col: 8, row: 4 },
        { col: 8, row: 5 },
        { col: 8, row: 6 },
        { col: 8, row: 7 },
        { col: 8, row: 8 },
        { col: 8, row: 9 },
        { col: 9, row: 9 },
        { col: 10, row: 10 },
        { col: 10, row: 11 },
      ]),
    ],
  },
  {
    // Two colleagues in the lounge at once, talking — the deferred break-room
    // conversation. Both walk there on authored routes; nobody teleports.
    id: "lounge-chat",
    employee: "milo",
    weight: 0.8,
    suppressOnAlert: true,
    nightFactor: 0.3,
    frames: [
      ...walk(MILO_TO_LOUNGE),
      { pose: "seated_lounge", tile: LOUNGE_CHAIR_SEAT, hold: 6_000, detail: "A quiet chat in the lounge." },
      { pose: "seated_talk", tile: LOUNGE_CHAIR_SEAT, hold: 7_000, detail: "A quiet chat in the lounge." },
      { pose: "seated_lounge", tile: LOUNGE_CHAIR_SEAT, hold: 6_000, detail: "A quiet chat in the lounge." },
      ...walkHome(MILO_TO_LOUNGE),
    ],
    cast: [
      {
        employee: "sage",
        frames: [
          { pose: "seated_reviewing", hold: STEP * 2 },
          ...walk(LOUNGE_FROM_LAB),
          { pose: "seated_talk", tile: SOFA_SEAT, hold: 6_500, detail: "A quiet chat in the lounge." },
          { pose: "seated_lounge", tile: SOFA_SEAT, hold: 6_000, detail: "A quiet chat in the lounge." },
          { pose: "seated_talk", tile: SOFA_SEAT, hold: 6_000, detail: "A quiet chat in the lounge." },
          ...walkHome(LOUNGE_FROM_LAB),
        ],
      },
    ],
  },
  {
    id: "echo-refill",
    employee: "echo",
    weight: 1.5,
    frames: [
      ...walk([
        { col: 6, row: 7 },
        { col: 6, row: 6 },
        { col: 5, row: 6 },
        { col: 4, row: 6 },
        { col: 4, row: 9 },
        { col: 4, row: 11 },
        { col: 5, row: 11 },
      ]),
      { pose: "coffee_idle", tile: { col: 5, row: 11 }, hold: 5_000, detail: "Refilling the bottle at the cooler." },
      ...walkHome([
        { col: 6, row: 7 },
        { col: 6, row: 6 },
        { col: 5, row: 6 },
        { col: 4, row: 6 },
        { col: 4, row: 9 },
        { col: 4, row: 11 },
        { col: 5, row: 11 },
      ]),
    ],
  },
];

AMBIENT_ROUTINES.push(...EXPANSION_ROUTINES, ...MEETING_ROUTINES);

export const ROUTINES_BY_EMPLOYEE = new Map<EmployeeId, AmbientRoutine[]>(
  EMPLOYEES.map((employee) => [
    employee.id,
    AMBIENT_ROUTINES.filter((routine) => routine.employee === employee.id),
  ]),
);

/**
 * The pose sequence, as a string.
 *
 * Used by the differentiation test: the brief requires every employee to have
 * at least one idle behaviour nobody else has, and comparing signatures is the
 * only way to check that which does not depend on someone remembering to.
 */
export function poseSignature(routine: AmbientRoutine): string {
  return routine.frames.map((frame) => frame.pose).join(",");
}

/** Weighted pick. Pure, so the scheduler's randomness is injectable in tests. */
export function pickRoutine<T extends { weight: number }>(
  routines: T[],
  random: () => number,
): T | null {
  if (routines.length === 0) return null;
  const total = routines.reduce((sum, routine) => sum + routine.weight, 0);
  let cursor = random() * total;
  for (const routine of routines) {
    cursor -= routine.weight;
    if (cursor < 0) return routine;
  }
  return routines[routines.length - 1]!;
}

/* ---------------------------------------------------------------------- */

/**
 * TIME OF DAY.
 *
 * From the browser clock, because that is the only clock HQ has and asking the
 * backend for a timezone would be a request this route is not allowed to make.
 *
 * Crypto runs 24/7 and the room must say so: night is *darker*, never emptier.
 * Nothing about the phase changes who is at their desk or what any routine
 * does — it is a lighting change and nothing else.
 */
export type DayPhase = "day" | "evening" | "night";

export function phaseOfDay(hour: number): DayPhase {
  if (hour >= 6 && hour < 17) return "day";
  if (hour >= 17 && hour < 21) return "evening";
  return "night";
}

export const DAY_PHASES: DayPhase[] = ["day", "evening", "night"];
