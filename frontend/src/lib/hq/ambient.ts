import type { Emotion, Pose } from "./characters";
import { EMPLOYEES, EMPLOYEE_BY_ID, type EmployeeId } from "./employees";
import { CONFERENCE_SEATS, FURNITURE_BLOCKED, LOUNGE_CHAIR_SEAT } from "./furniture";
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
   * How this actor feels during this frame. Presentation only.
   *
   * On the same footing as `pose`: it describes the person, never the system.
   * The distinction matters more here than it looks, because these frames fire
   * on a timer — an angry face scheduled by a clock is exactly as unfounded as
   * a chatter line claiming the queue is deep. So the emotions that appear in
   * ambient routines are the ones a *social* situation motivates: losing a
   * frame of pool, winning one, being interrupted. Emotions that would read as
   * a verdict on MEMESCOPE reach the face only through `Transient`, which the
   * adapter owns and which has a reading behind it.
   */
  emotion?: Emotion;
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
    // Was "radar shows Luna something". Luna was retired 2026-09-08; Radar
    // keeps the beat alone rather than the floor losing a routine, because
    // every employee needs at least two and a room where nobody moves reads
    // as a freeze rather than as calm.
    id: "radar-reads",
    employee: "radar",
    weight: 2,
    frames: [
      { pose: "talking_briefly", hold: 3600 },
      { pose: "looking_at_screen", hold: 2400 },
    ],
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

  /* ---- Dex: switches monitors, coffee, quick head turns --------------- */

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

/** Column 9 southbound: the same clear line, walked the other way. */

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
  milo: [
    { col: 2, row: 7 },
    { col: 2, row: 6 },
    ...walkwayEast(3),
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
  // The reliability trio. Sentinel's route exists even though she does not
  // attend the briefing — see REPORT_STATIONS — because incident handling
  // walks her to Nova, and that walk has to use covered tiles like every
  // other. Her corner has exactly one exit, west into the Portfolio aisle.
  sentinel: [
    { col: 7, row: 9 },
    { col: 7, row: 8 },
    { col: 7, row: 7 },
    { col: 7, row: 6 },
    ...walkwayEast(8),
    ...SPINE_UP,
    ...ROW2_EAST,
    ...ROW1_TO_DOOR,
  ],
  patch: [
    { col: 12, row: 8 },
    { col: 12, row: 7 },
    { col: 12, row: 6 },
    { col: 11, row: 6 },
    { col: 10, row: 6 },
    { col: 9, row: 6 },
    ...SPINE_UP,
    ...ROW2_EAST,
    ...ROW1_TO_DOOR,
  ],
  quinn: [
    { col: 15, row: 6 },
    { col: 14, row: 6 },
    { col: 13, row: 6 },
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
  ]),
  meeting("meet-portfolio", 1.5, "Talking through the portfolio.", [
    ["nova", SEAT[0]!],
    ["milo", SEAT[1]!],
  ]),
  meeting("meet-discovery", 1.5, "Reviewing discovery together.", [
    ["radar", SEAT[0]!],
    // Luna and Dex retired 2026-09-08. Atlas takes the second chair: he is
    // who acts on what discovery finds, and a one-person meeting is not one.
    ["atlas", SEAT[1]!],
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

/* ---------------------------------------------------------------------- */

/**
 * THE CEO'S OWN ROUTINES.
 *
 * Nova already walked the floor. What she did not do is behave differently
 * from the nine people she runs, and the brief asks for that difference to be
 * visible without inventing authority the platform does not have.
 *
 * So the difference is *shape*, never content. Nova is the only one who
 * crosses the room to somebody else's desk unprompted; the only one whose
 * micro-interactions are two-sided by default; the only one who reads the
 * Mission Board rather than a monitor. Those are the observable habits of
 * somebody running the place.
 *
 * ── "ASSIGNING A TASK" IS A DRAWING ─────────────────────────────────────
 *
 * `nova-assign-*` shows Nova speaking to a specialist and the specialist
 * acknowledging. Nothing is scheduled, nothing is queued and no backend hears
 * about it — the exchange is two poses and two bubbles. The brief is explicit
 * that the CEO must not become an autonomous task system, and the guarantee
 * here is structural: this file exports frames. It has no client, no writer
 * and no reachable side effect, exactly like every other routine beside it.
 *
 * The lines are deliberately about *attention*, not instruction. "Take a look
 * when you can" is a manager talking. "Buy this" would be a trading decision
 * rendered as a cartoon, which is the one thing HQ may never draw.
 */
function novaAssign(
  id: string,
  target: EmployeeId,
  approach: Tile[],
  novaLine: string,
  reply: string,
): AmbientRoutine {
  const at = approach.at(-1)!;
  return {
    id,
    employee: "nova",
    // Light on purpose. Nova owns three of the four ambient meetings, so every
    // point of weight added here is meeting frequency taken away.
    weight: 0.8,
    suppressOnAlert: true,
    nightFactor: 0.2,
    frames: [
      ...walk(approach),
      { pose: "talking_briefly", tile: at, hold: 4_200, detail: "Speaking with the desk.", speech: novaLine },
      { pose: "standing", tile: at, hold: 2_600, detail: "Listening." },
      ...walkHome(approach),
    ],
    cast: [
      {
        employee: target,
        frames: [
          { pose: "standing", hold: STEP_MS * approach.length },
          { pose: "looking_at_screen", hold: 4_200, detail: "Being asked to take a look." },
          { pose: "talking_briefly", hold: 2_600, detail: "Acknowledging.", speech: reply },
          { pose: "seated_working", hold: 1_200 },
        ],
      },
    ],
  };
}

export const CEO_ROUTINES: AmbientRoutine[] = [
  novaAssign(
    "nova-assign-atlas",
    "atlas",
    // Along the row-1 corridor and down the west edge. (5,4) and (2,4) are
    // Atlas's own desk furniture; she stands beside it, not in it.
    [
      { col: 7, row: 1 },
      { col: 6, row: 1 },
      { col: 5, row: 1 },
      { col: 4, row: 1 },
      { col: 3, row: 1 },
      { col: 2, row: 1 },
      { col: 2, row: 2 },
      { col: 2, row: 3 },
    ],
    "Atlas, when you can.",
    "On it.",
  ),
  novaAssign(
    "nova-assign-rex",
    "rex",
    [
      { col: 9, row: 1 },
      { col: 10, row: 1 },
      { col: 11, row: 1 },
      { col: 12, row: 1 },
      { col: 12, row: 2 },
      { col: 12, row: 3 },
    ],
    "Rex, anything I should know?",
    "Standing by.",
  ),
  {
    // The CEO's version of reading the room: a slow lap of the Mission Board
    // and back. Longer holds than anybody else's idle — she is looking, not
    // working, and the difference should read at a glance.
    id: "nova-inspect",
    employee: "nova",
    weight: 1.2,
    nightFactor: 0.3,
    frames: [
      ...walk([
        { col: 9, row: 1 },
        { col: 10, row: 1 },
        { col: 11, row: 1 },
      ]),
      { pose: "standing", tile: { col: 11, row: 1 }, hold: 7_800, detail: "Reading the Mission Board." },
      { pose: "holding_tablet", tile: { col: 11, row: 1 }, hold: 5_400, detail: "Making a note from the board." },
      ...walkHome([
        { col: 9, row: 1 },
        { col: 10, row: 1 },
        { col: 11, row: 1 },
      ]),
    ],
  },
];

/**
 * THE OUTDOOR DECK, PROPERLY USED.
 *
 * Two kinds of break, both on the deck and nowhere else, and both written to
 * be unremarkable. The smoking one is adult staff on a break: they stand at
 * the railing, they finish, they come back. It is occasional (`weight` 0.6 —
 * the lowest in the file), suppressed at alert and rare at night, and it is
 * the only routine anywhere that carries `detail` mentioning it at all.
 *
 * Nothing about it is celebrated and nothing about it is hidden.
 */
/**
 * The deck's standing spots.
 *
 * (19,6) is blocked — the airlock frame stands there — so the rail positions
 * are (18,6), which `rex-deck` already uses, and (20,6) reached around it via
 * row 5. Both were guessed wrong first and caught by the furniture test, which
 * is the entire reason that test walks every frame of every routine.
 */
const DECK_EAST: Tile[] = [
  { col: 18, row: 5 },
  { col: 19, row: 5 },
  { col: 20, row: 5 },
  { col: 20, row: 6 },
];

/** Walkway row 6 from a column east to the deck. */
function walkwayToDeck(fromCol: number, toCol: number): Tile[] {
  const tiles: Tile[] = [];
  for (let col = fromCol; col <= toCol; col += 1) tiles.push({ col, row: 6 });
  return tiles;
}

function deckBreak(
  id: string,
  employee: EmployeeId,
  approach: Tile[],
  detail: string,
  weight: number,
): AmbientRoutine {
  const at = approach.at(-1)!;
  return {
    id,
    employee,
    weight,
    suppressOnAlert: true,
    nightFactor: 0.35,
    frames: [
      ...walk(approach),
      { pose: "standing", tile: at, hold: 8_400, detail },
      { pose: "stretching", tile: at, hold: 3_200, detail },
      { pose: "standing", tile: at, hold: 5_600, detail },
      ...walkHome(approach),
    ],
  };
}

export const BREAK_ROUTINES: AmbientRoutine[] = [
  deckBreak(
    "byte-smoke",
    "byte",
    [{ col: 9, row: 7 }, ...walkwayToDeck(9, 18), ...DECK_EAST],
    "On a smoking break at the deck railing.",
    0.6,
  ),
  deckBreak(
    "milo-air",
    "milo",
    [{ col: 2, row: 7 }, { col: 2, row: 6 }, ...walkwayEast(3), ...walkwayToDeck(10, 16)],
    "Out on the deck for some air.",
    1,
  ),
];

/* ---- the reliability trio ----------------------------------------------
 *
 * Written after the other ten, and constrained by a floor that was already
 * full: Sentinel's corner has one walkable neighbour and Patch's desk has two.
 * That is why these routines are shorter than Nova's tour of the building.
 * They are also, deliberately, the quietest idle vocabulary in the office —
 * two of these three people are only interesting when something is wrong, and
 * an idle animation that looks like work would be the exact lie HQ refuses.
 */
const RELIABILITY_ROUTINES: AmbientRoutine[] = [
  {
    // Standing, reading the wall, standing again. The pose sequence is the
    // distinctive one: nobody else in the cast stands *between* two readings.
    id: "sentinel-scan",
    employee: "sentinel",
    weight: 5,
    frames: [
      { pose: "standing", hold: 6000 },
      { pose: "looking_at_screen", hold: 7000 },
      { pose: "standing", hold: 4000 },
    ],
  },
  {
    id: "sentinel-stretch",
    employee: "sentinel",
    weight: 2,
    frames: [
      { pose: "stretching", hold: 2600 },
      { pose: "standing", hold: 5000 },
    ],
  },
  {
    // The one walk her corner allows: east past the printer and up to the
    // Operations bench.
    id: "sentinel-walk",
    employee: "sentinel",
    weight: 2,
    frames: trip(
      [
        { col: 7, row: 9 },
        { col: 7, row: 8 },
      ],
      { pose: "talking_briefly", hold: 4200 },
    ),
  },
  {
    id: "patch-work",
    employee: "patch",
    weight: 5,
    frames: [
      { pose: "seated_working", hold: 8000 },
      { pose: "seated_reviewing", hold: 5000 },
    ],
  },
  {
    id: "patch-think",
    employee: "patch",
    weight: 3,
    frames: [
      { pose: "seated_reviewing", hold: 6000 },
      { pose: "looking_at_screen", hold: 6500 },
      { pose: "seated_working", hold: 4000 },
    ],
  },
  {
    // North out of the lab, a word with whoever is on the walkway, and back.
    id: "patch-bench",
    employee: "patch",
    weight: 2,
    frames: trip(
      [
        { col: 12, row: 8 },
        { col: 12, row: 7 },
      ],
      { pose: "talking_briefly", hold: 4600 },
    ),
  },
  {
    id: "quinn-review",
    employee: "quinn",
    weight: 5,
    frames: [
      { pose: "seated_reviewing", hold: 9000 },
      { pose: "looking_at_screen", hold: 5500 },
    ],
  },
  {
    id: "quinn-recheck",
    employee: "quinn",
    weight: 3,
    frames: [
      { pose: "looking_at_screen", hold: 5000 },
      { pose: "seated_reviewing", hold: 6000 },
      { pose: "looking_at_screen", hold: 5000 },
    ],
  },
  {
    id: "quinn-stretch",
    employee: "quinn",
    weight: 2,
    frames: [
      { pose: "stretching", hold: 2400 },
      { pose: "seated_reviewing", hold: 6000 },
    ],
  },
];

/* ---- Karthik ------------------------------------------------------------
 *
 * The most active idle vocabulary in the office, which is what §6 asks for and
 * also what the job looks like: six screens, a keyboard, and something to
 * check on all of them. Nine routines against Nova's five.
 *
 * **None of these means anything.** Every frame below is presentation — a
 * `looking_at_screen` on Karthik says "this bench is staffed", never "a target
 * is about to fill". The routines that *do* correspond to real events are
 * `KARTHIK_EVENT_ROUTINES`, kept in a separate array precisely so the
 * scheduler cannot pick one at random: §6's closing rule is that no fake
 * business event may be generated to drive an animation, and the way to
 * guarantee that is to make the celebration unreachable from the dice.
 */

/** Desk (18,9) → the wall display's viewing tile. One step, inside the room. */
const KARTHIK_TO_DISPLAY: Tile[] = [{ col: 19, row: 9 }];

/** Desk → the counter at the lab's west wall. */
const KARTHIK_TO_COUNTER: Tile[] = [
  { col: 17, row: 9 },
  { col: 17, row: 8 },
];

/** Desk → beside Satoshi's bed. */
const KARTHIK_TO_CAT: Tile[] = [
  { col: 17, row: 10 },
  { col: 16, row: 10 },
];

/**
 * Desk → Nova, the long way, because it is the only way.
 *
 * North out of the lab onto the deck, west along the row-6 walkway, up the
 * column-9 spine and across to the tile Nova's visitors already use. Seventeen
 * waypoints is a genuinely long walk, and that is correct: Karthik Lab is at
 * the far south-east corner and an escalation to the CEO should read as
 * somebody crossing the whole building. It is also why this is an *event*
 * routine and not an ambient one — nobody makes that trip for no reason.
 */
const KARTHIK_TO_NOVA: Tile[] = [
  { col: 18, row: 8 },
  { col: 18, row: 7 },
  { col: 18, row: 6 },
  { col: 17, row: 6 },
  { col: 16, row: 6 },
  { col: 15, row: 6 },
  { col: 14, row: 6 },
  { col: 13, row: 6 },
  { col: 12, row: 6 },
  { col: 11, row: 6 },
  { col: 10, row: 6 },
  { col: 9, row: 6 },
  { col: 9, row: 5 },
  { col: 9, row: 4 },
  { col: 9, row: 3 },
  { col: 9, row: 2 },
  { col: 8, row: 2 },
];

const VAULT_ROUTINES: AmbientRoutine[] = [
  {
    // The signature behaviour, and deliberately the dullest in the building:
    // long holds and almost no motion. Every other desk fidgets, types or
    // walks; this one mostly does not move, which is what a person guarding a
    // shut door looks like and reads as stillness beside thirteen busy figures.
    id: "vault-watch",
    employee: "vault",
    weight: 7,
    frames: [{ pose: "seated_reviewing", hold: 14_000, detail: "Watching the door." }],
  },
  {
    id: "vault-ledger",
    employee: "vault",
    weight: 4,
    frames: [
      { pose: "looking_at_screen", hold: 5_200, detail: "Reading the posture panel." },
      { pose: "seated_reviewing", hold: 9_000, detail: "Sitting with it." },
    ],
  },
  {
    // The one time he stands: a slow check and straight back down. Rare weight
    // so it registers as an event rather than a habit.
    id: "vault-check",
    employee: "vault",
    weight: 2,
    frames: [
      { pose: "standing", hold: 2_600, detail: "Up, checking the room." },
      { pose: "seated_reviewing", hold: 11_000, detail: "Back down, watching." },
    ],
  },
];


/* ── Rafiq Analytics ──────────────────────────────────────────────────────
 *
 * Five desks in one row, so the routines are built to AVOID synchrony. Five
 * analysts sharing a pose vocabulary would pulse together like a row of
 * lights, which reads as a screensaver rather than as five people; the holds
 * are therefore all coprime-ish odd numbers and no two of them share a pose
 * sequence.
 *
 * All in-place. Nobody in this room walks: the office already has plenty of
 * traffic and the point of an analyst bullpen is that it is the still corner
 * of the floor.
 *
 * As everywhere else in this file, these fire on a TIMER. They must therefore
 * never claim anything about a strategy — a `detail` saying "checking a losing
 * trade" would be a business claim generated by a clock, which is the one
 * thing the whole ambient layer is forbidden to do. They say what a body is
 * doing and nothing more.
 */
const ANALYST_ROUTINES: AmbientRoutine[] = [
  // Anchor — deliberate, rereads before speaking.
  {
    id: "anchor-reading",
    employee: "anchor",
    weight: 6,
    frames: [{ pose: "seated_reviewing", hold: 9_100, detail: "Reading, not typing." }],
  },
  {
    // Anchor's own sequence: reads, leans in, reads again, THEN sits back and
    // stretches. The double return to the list is the tic — this desk goes
    // back to the record one more time than anybody else in the office does.
    id: "anchor-recheck",
    employee: "anchor",
    weight: 4,
    frames: [
      { pose: "seated_reviewing", hold: 4_300, detail: "Reading the trade list." },
      { pose: "looking_at_screen", hold: 3_100, detail: "Leaning in at the screen." },
      { pose: "seated_reviewing", hold: 5_700, detail: "Back to the list." },
      { pose: "stretching", hold: 2_500, detail: "A stretch, then still." },
    ],
  },
  // Tempo — quick, taps a rhythm, never still for long.
  {
    id: "tempo-working",
    employee: "tempo",
    weight: 6,
    frames: [{ pose: "seated_working", hold: 5_300, detail: "Working at the desk." }],
  },
  {
    id: "tempo-clock",
    employee: "tempo",
    weight: 5,
    frames: [
      { pose: "seated_working", hold: 2_900, detail: "Working at the desk." },
      { pose: "stretching", hold: 2_300, detail: "A stretch, then back." },
      { pose: "looking_at_screen", hold: 3_700, detail: "Checking the screen." },
    ],
  },
  // Sigma — slow, magnifies, will not be hurried.
  {
    id: "sigma-close-read",
    employee: "sigma",
    weight: 6,
    frames: [
      { pose: "looking_at_screen", hold: 6_100, detail: "Close on the screen." },
      { pose: "seated_reviewing", hold: 4_900, detail: "Sitting back with it." },
      { pose: "looking_at_screen", hold: 5_500, detail: "Close again." },
      { pose: "seated_reviewing", hold: 4_100, detail: "Sitting back." },
    ],
  },
  {
    id: "sigma-settled",
    employee: "sigma",
    weight: 4,
    frames: [{ pose: "looking_at_screen", hold: 11_300, detail: "Still, at the screen." }],
  },
  // Halt — watches one line. The stillest desk in the room.
  {
    id: "halt-watch",
    employee: "halt",
    weight: 7,
    frames: [{ pose: "seated_working", hold: 12_700, detail: "Watching the desk screen." }],
  },
  {
    id: "halt-up-and-down",
    employee: "halt",
    weight: 3,
    frames: [
      { pose: "seated_working", hold: 3_300, detail: "Watching the desk screen." },
      { pose: "standing", hold: 2_100, detail: "Half up, looking at the sheet." },
      { pose: "seated_working", hold: 6_300, detail: "Back down." },
    ],
  },
  // Chorus — reads the other four before their own. The only sociable desk here.
  {
    id: "chorus-along-the-row",
    employee: "chorus",
    weight: 6,
    frames: [
      { pose: "seated_reviewing", hold: 3_900, detail: "Reading the row's screens." },
      { pose: "talking_briefly", hold: 2_700, detail: "A word down the row." },
      { pose: "seated_reviewing", hold: 4_500, detail: "Back to reading." },
      { pose: "talking_briefly", hold: 2_300, detail: "A word the other way." },
    ],
  },
  {
    id: "chorus-waiting",
    employee: "chorus",
    weight: 4,
    frames: [
      { pose: "seated_reviewing", hold: 7_700, detail: "Waiting on the other desks." },
      { pose: "stretching", hold: 2_700, detail: "A stretch at the desk." },
    ],
  },
];

const KARTHIK_ROUTINES: AmbientRoutine[] = [
  {
    id: "karthik-typing",
    employee: "karthik",
    weight: 6,
    frames: [{ pose: "seated_working", hold: 7_400, detail: "At the bench, working." }],
  },
  {
    id: "karthik-monitors",
    employee: "karthik",
    weight: 5,
    frames: [
      { pose: "looking_at_screen", hold: 3_800, detail: "Reading the wallet screen." },
      { pose: "seated_working", hold: 3_200, detail: "At the bench, working." },
      { pose: "looking_at_screen", hold: 3_600, detail: "Reading the positions screen." },
    ],
  },
  {
    id: "karthik-focus",
    employee: "karthik",
    weight: 4,
    frames: [{ pose: "seated_reviewing", hold: 10_500, detail: "Reading closely, not typing." }],
  },
  {
    id: "karthik-feed",
    employee: "karthik",
    weight: 4,
    frames: [
      { pose: "looking_at_screen", hold: 6_800, detail: "Watching the Track Record feed." },
    ],
  },
  {
    id: "karthik-display",
    employee: "karthik",
    weight: 3,
    frames: [
      ...walk(KARTHIK_TO_DISPLAY),
      {
        pose: "standing",
        tile: { col: 19, row: 9 },
        hold: 7_200,
        detail: "At the wall display.",
      },
      ...walkHome(KARTHIK_TO_DISPLAY),
    ],
  },
  {
    id: "karthik-stretch",
    employee: "karthik",
    weight: 3,
    frames: [
      { pose: "stretching", hold: 3_400, detail: "Stretching at the bench." },
      { pose: "seated_working", hold: 4_000, detail: "At the bench, working." },
    ],
  },
  {
    id: "karthik-counter",
    employee: "karthik",
    weight: 2,
    suppressOnAlert: true,
    frames: [
      ...walk(KARTHIK_TO_COUNTER),
      {
        pose: "coffee_idle",
        tile: { col: 17, row: 8 },
        hold: 8_600,
        detail: "Coffee at the lab counter.",
      },
      ...walkHome(KARTHIK_TO_COUNTER),
    ],
  },
  {
    id: "karthik-satoshi",
    employee: "karthik",
    weight: 2,
    suppressOnAlert: true,
    frames: [
      ...walk(KARTHIK_TO_CAT),
      {
        pose: "tidying",
        tile: { col: 16, row: 10 },
        hold: 6_400,
        detail: "Crouched by the cat bed, petting Satoshi.",
      },
      ...walkHome(KARTHIK_TO_CAT),
    ],
  },
  {
    id: "karthik-report",
    employee: "karthik",
    weight: 2,
    frames: [
      { pose: "seated_reviewing", hold: 6_000, detail: "Writing up a report." },
      { pose: "seated_working", hold: 5_200, detail: "Writing up a report." },
    ],
  },
];

/**
 * THE ROUTINES A REAL EVENT DRIVES, AND NOTHING ELSE MAY.
 *
 * Deliberately **not** in `AMBIENT_ROUTINES`. The scheduler picks from that
 * array, so anything in it can fire on a timer — and a celebration that could
 * fire on a timer is a claim that a target hit, made by a dice roll. These are
 * reachable only through an explicit override driven by a reading the backend
 * published, which is the same mechanism `useReportMeeting` already uses to
 * stage the report meeting.
 *
 * Every one of them therefore stays unused until a Karthik wallet exists and
 * publishes an event. That is the intended state, not an unfinished one.
 */
export const KARTHIK_EVENT_ROUTINES: Record<string, AmbientRoutine> = {
  /** A real 1.25x fill. The only celebration in the office. */
  target_hit: {
    id: "karthik-target-hit",
    employee: "karthik",
    weight: 0,
    frames: [
      { pose: "standing", hold: 1_400, detail: "A target filled at 1.25x." },
      { pose: "stretching", hold: 1_200, detail: "Celebrating a target hit." },
      { pose: "standing", hold: 1_200, detail: "Celebrating a target hit." },
      { pose: "stretching", hold: 1_200, detail: "Celebrating a target hit." },
      { pose: "returning_to_desk", hold: STEP },
    ],
  },
  /** A new entry. He turns to the positions screen; that is all. */
  new_entry: {
    id: "karthik-new-entry",
    employee: "karthik",
    weight: 0,
    frames: [
      { pose: "looking_at_screen", hold: 5_200, detail: "A new Karthik position opened." },
    ],
  },
  /** A dead position. Concerned, not theatrical. */
  dead_zero: {
    id: "karthik-dead-zero",
    employee: "karthik",
    weight: 0,
    frames: [
      { pose: "seated_reviewing", hold: 7_000, detail: "Reviewing a position that went to zero." },
    ],
  },
  /** An open incident. Fast, head-down work at the health screen. */
  incident: {
    id: "karthik-incident",
    employee: "karthik",
    weight: 0,
    frames: [
      { pose: "looking_at_screen", hold: 3_000, detail: "Inspecting the system-health screen." },
      { pose: "seated_working", hold: 3_000, detail: "Working an open incident." },
      { pose: "looking_at_screen", hold: 3_000, detail: "Inspecting the system-health screen." },
      { pose: "seated_working", hold: 3_000, detail: "Working an open incident." },
    ],
  },
  /** A repair that succeeded. Back to work, and that is the whole reaction. */
  repaired: {
    id: "karthik-repaired",
    employee: "karthik",
    weight: 0,
    frames: [{ pose: "seated_working", hold: 5_000, detail: "Repair verified; back at the bench." }],
  },
  /** Something only the owner may decide. The long walk to Nova. */
  owner_required: {
    id: "karthik-escalate",
    employee: "karthik",
    weight: 0,
    frames: [
      ...walk(KARTHIK_TO_NOVA),
      {
        pose: "talking_briefly",
        tile: { col: 8, row: 2 },
        hold: 6_200,
        detail: "Escalating an owner-attention item to Nova.",
      },
      ...walkHome(KARTHIK_TO_NOVA),
    ],
    cast: [
      {
        employee: "nova",
        frames: [
          { pose: "standing", hold: STEP * KARTHIK_TO_NOVA.length },
          { pose: "talking_briefly", hold: 6_200 },
        ],
      },
    ],
  },
  /** A daily report is ready. He reads it at the wall display. */
  report_ready: {
    id: "karthik-report-ready",
    employee: "karthik",
    weight: 0,
    frames: [
      ...walk(KARTHIK_TO_DISPLAY),
      {
        pose: "standing",
        tile: { col: 19, row: 9 },
        hold: 8_000,
        detail: "Reading the day's report on the wall display.",
      },
      ...walkHome(KARTHIK_TO_DISPLAY),
    ],
  },
};

/* ---- the games corner ---------------------------------------------------
 *
 * Two tables, two rooms, and every match is two people. That is the point: a
 * game is the only thing in this office that *requires* a colleague, so it is
 * the only routine where the room shows a relationship rather than a person
 * with a job.
 *
 * ── WHAT THE EMOTIONS HERE ARE ALLOWED TO MEAN ──────────────────────────
 *
 * A match is a complete, self-contained reason to be pleased or annoyed. That
 * is what makes these the one place ambient routines may carry `happy`, `smug`
 * or `angry`: the frame that motivates the feeling is in the same timeline the
 * reader is watching. Nobody has to infer why Byte is grinning — he just won.
 *
 * The rule this must never cross is the one every ambient routine lives under:
 * these fire on a timer, so nothing here may be *about MEMESCOPE*. Losing at
 * pool is a person. Looking annoyed because the queue is deep would be a claim
 * a clock made up, and a test asserts no line or detail in this block mentions
 * the system.
 *
 * ── WHY NOBODY WINS ON THE SCOREBOARD ───────────────────────────────────
 *
 * There is no score anywhere — not on the table, not in a bubble. A displayed
 * 3-2 would be a fabricated fact of exactly the kind the rest of the room
 * refuses. What the routines show is the *shape* of a match: two people at a
 * table, a reaction, and back to work. Who won is left to the drawing.
 */

/** Beside the pool table, on its long sides. The ends stay clear — that is
 *  where a cue goes, and it is also the lane to the viewport. */
const POOL_NEAR: Tile = { col: 12, row: 11 };
const POOL_FAR: Tile = { col: 14, row: 11 };

/** Across the foosball table on the deck's northern strip. */
const FOOS_WEST: Tile = { col: 16, row: 4 };
const FOOS_EAST: Tile = { col: 18, row: 4 };

/**
 * One player's half of a match: walk over, play, react, walk back.
 *
 * Built rather than written out because a match is symmetric and a
 * hand-written second half is where the two players drift out of step — one
 * still swinging while the other has already walked away is the tell that a
 * "game" is two unrelated animations that happen to be adjacent.
 */
function match(
  approach: Tile[],
  at: Tile,
  play: Pose,
  outcome: { pose: Pose; emotion: Emotion; detail: string },
  playingDetail: string,
): AmbientFrame[] {
  return [
    ...walk(approach),
    { pose: play, tile: at, hold: 7_600, emotion: "neutral", detail: playingDetail },
    { pose: play, tile: at, hold: 6_800, emotion: "neutral", detail: playingDetail },
    { pose: outcome.pose, tile: at, hold: 4_200, emotion: outcome.emotion, detail: outcome.detail },
    ...walkHome(approach),
  ];
}

/**
 * Every route below was produced by breadth-first search over `isWalkable`
 * from the walker's own desk, not written by hand.
 *
 * Hand-authoring is what the rest of this file does and it is right for short
 * hops, but the games corner is in the far south-east and the first four
 * routes I wrote by eye each broke a different rule — one stood a player
 * inside the Performance Lab's bookshelf, one jumped two tiles because I had
 * misremembered which column Quinn sits in. The tests caught all of them,
 * which is the system working; searching the floor plan instead of guessing at
 * it is cheaper than being caught.
 */
const POOL_FROM_BYTE: Tile[] = [
  { col: 9, row: 9 },
  { col: 9, row: 10 },
  { col: 9, row: 11 },
  { col: 10, row: 11 },
  { col: 11, row: 11 },
  POOL_NEAR,
];

const POOL_FROM_PATCH: Tile[] = [
  { col: 13, row: 9 },
  { col: 13, row: 10 },
  { col: 14, row: 10 },
  POOL_FAR,
];

const POOL_FROM_QUINN: Tile[] = [
  { col: 15, row: 6 },
  { col: 14, row: 6 },
  { col: 13, row: 6 },
  { col: 13, row: 7 },
  { col: 13, row: 8 },
  { col: 13, row: 9 },
  { col: 13, row: 10 },
  { col: 14, row: 10 },
  POOL_FAR,
];

const FOOS_FROM_ECHO: Tile[] = [
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
  { col: 16, row: 5 },
  FOOS_WEST,
];

const FOOS_FROM_KARTHIK: Tile[] = [
  { col: 18, row: 8 },
  { col: 18, row: 7 },
  { col: 18, row: 6 },
  { col: 18, row: 5 },
  FOOS_EAST,
];

export const GAME_ROUTINES: AmbientRoutine[] = [
  {
    // Pool: Byte against Patch. Both are infrastructure, both are already in
    // the south of the building, and neither is somebody whose desk being
    // empty for four minutes would read as a subsystem going quiet.
    id: "pool-byte-patch",
    employee: "byte",
    weight: 1.1,
    suppressOnAlert: true,
    nightFactor: 1.3,
    frames: match(
      POOL_FROM_BYTE,
      POOL_NEAR,
      "cue_shot",
      { pose: "cheering", emotion: "happy", detail: "Won a frame of pool." },
      "Playing pool in the lounge.",
    ),
    cast: [
      {
        employee: "patch",
        frames: match(
          POOL_FROM_PATCH,
          POOL_FAR,
          "cue_shot",
          { pose: "standing", emotion: "sad", detail: "Lost a frame of pool." },
          "Playing pool in the lounge.",
        ),
      },
    ],
  },
  {
    // Quinn alone at the table between passes. The counterexample to "a game
    // needs two people": one person practising is a different, quieter picture
    // and it is the one that makes the corner look used rather than staged.
    id: "pool-quinn-practice",
    employee: "quinn",
    weight: 0.9,
    suppressOnAlert: true,
    nightFactor: 1.4,
    frames: [
      ...walk(POOL_FROM_QUINN),
      { pose: "cue_shot", tile: POOL_FAR, hold: 7_000, emotion: "neutral", detail: "Practising at the pool table." },
      { pose: "standing", tile: POOL_FAR, hold: 3_000, emotion: "smug", detail: "Potted it." },
      { pose: "cue_shot", tile: POOL_FAR, hold: 5_400, emotion: "neutral", detail: "Practising at the pool table." },
      ...walkHome(POOL_FROM_QUINN),
    ],
  },
  {
    // Foosball on the deck. Faster, noisier, and the only routine in the
    // office where two people are both moving at speed at the same time.
    id: "foosball-echo-karthik",
    employee: "echo",
    weight: 1.1,
    suppressOnAlert: true,
    frames: match(
      FOOS_FROM_ECHO,
      FOOS_WEST,
      "playing_table",
      { pose: "cheering", emotion: "happy", detail: "Won at foosball." },
      "Playing foosball on the deck.",
    ),
    cast: [
      {
        employee: "karthik",
        frames: match(
          FOOS_FROM_KARTHIK,
          FOOS_EAST,
          "playing_table",
          { pose: "standing", emotion: "angry", detail: "Lost at foosball, narrowly." },
          "Playing foosball on the deck.",
        ),
      },
    ],
  },
];

/* ---- people talking to each other ----------------------------------------
 *
 * The office already had micro-interactions, and every one of them was one
 * person walking somewhere and a colleague nodding. These are conversations
 * with a *shape*: somebody arrives with something, the other reacts, and the
 * feeling changes between the first frame and the last.
 *
 * ── THE ARGUMENT, AND WHY IT IS SAFE ────────────────────────────────────
 *
 * `atlas-rex-disagree` is the one routine in the building where two people are
 * angry at each other. It is also the most carefully bounded, for a reason
 * that is easy to miss: Atlas is the desk that refuses trades and Rex is the
 * desk that places them, so a reader who saw them arguing could reasonably
 * conclude something had gone wrong with a trade.
 *
 * Three things stop that. It is `suppressOnAlert`, so it can never play while
 * the office is actually in trouble — an argument during a real incident is
 * exactly the coincidence that would read as causation. It resolves: the last
 * two frames are both `neutral` and the detail says so, so nobody is left
 * frozen mid-row. And not one line or detail mentions a trade, a token, a
 * wallet or a number, which a test enforces across this whole block.
 *
 * What is left is two colleagues who disagree about something and get over it,
 * which is what an office looks like.
 */

/** Two people facing each other at a tile each, for the length of a talk. */
function conversation(
  at: Tile,
  beats: Array<{ pose: Pose; emotion: Emotion; hold: number; detail: string; speech?: string }>,
): AmbientFrame[] {
  return beats.map((beat) => ({
    pose: beat.pose,
    tile: at,
    hold: beat.hold,
    emotion: beat.emotion,
    detail: beat.detail,
    speech: beat.speech,
  }));
}

/** Rex's desk to the Risk Room's edge. BFS-verified, like the games routes. */
const REX_TO_RISK: Tile[] = [
  { col: 11, row: 4 },
  { col: 10, row: 4 },
  { col: 10, row: 5 },
  { col: 9, row: 5 },
  { col: 8, row: 5 },
  { col: 7, row: 5 },
  { col: 6, row: 5 },
  { col: 5, row: 5 },
  { col: 4, row: 5 },
  { col: 4, row: 4 },
];

const MILO_TO_SENTINEL: Tile[] = [
  { col: 3, row: 8 },
  { col: 4, row: 8 },
  { col: 5, row: 8 },
];

const NOVA_TO_BYTE: Tile[] = [
  { col: 8, row: 2 },
  { col: 8, row: 3 },
  { col: 8, row: 4 },
  { col: 8, row: 5 },
  { col: 8, row: 6 },
  { col: 8, row: 7 },
  { col: 9, row: 7 },
];

export const SOCIAL_ROUTINES: AmbientRoutine[] = [
  {
    // Rex walks to Atlas, and not the other way round.
    //
    // I wrote it the other way first and a test failed: Atlas is the stillest
    // figure in the office — `keeps Atlas still and Echo mobile` measures the
    // fraction of his frames that stay at his desk — and sending him across
    // the building to argue dropped him under the floor. The fix is also the
    // better scene. Atlas is the desk that refuses; people come to *him* to be
    // told no, and he does not chase anyone to say it.
    id: "rex-atlas-disagree",
    employee: "rex",
    weight: 0.7,
    suppressOnAlert: true,
    nightFactor: 0.3,
    frames: [
      ...walk(REX_TO_RISK),
      ...conversation({ col: 4, row: 4 }, [
        { pose: "talking_briefly", emotion: "angry", hold: 3_400, detail: "Arguing a call with Atlas.", speech: "It held last time." },
        { pose: "standing", emotion: "angry", hold: 2_600, detail: "Arguing a call with Atlas." },
        { pose: "talking_briefly", emotion: "neutral", hold: 3_200, detail: "Talking it through with Atlas.", speech: "Alright. Show me." },
        { pose: "standing", emotion: "happy", hold: 2_400, detail: "Sorted it out with Atlas." },
      ]),
      ...walkHome(REX_TO_RISK),
    ],
    cast: [
      {
        employee: "atlas",
        frames: [
          { pose: "seated_reviewing", hold: STEP * REX_TO_RISK.length, emotion: "neutral" },
          { pose: "standing", hold: 3_400, emotion: "neutral", detail: "Hearing Rex out." },
          { pose: "talking_briefly", hold: 2_600, emotion: "angry", detail: "Not persuaded.", speech: "No. Not like that." },
          { pose: "standing", hold: 3_200, emotion: "neutral", detail: "Hearing Rex out." },
          { pose: "seated_reviewing", hold: 2_400, emotion: "neutral", detail: "Back to the review." },
        ],
      },
    ],
  },
  {
    // Milo cheers Sentinel up. The counterweight to the argument: the office
    // needs somebody being kind in it or the only relationship on show is
    // conflict.
    id: "milo-sentinel-check-in",
    employee: "milo",
    weight: 1,
    suppressOnAlert: true,
    frames: [
      ...walk(MILO_TO_SENTINEL),
      ...conversation({ col: 5, row: 8 }, [
        { pose: "talking_briefly", emotion: "happy", hold: 3_800, detail: "Checking in on Sentinel.", speech: "Long one today?" },
        { pose: "standing", emotion: "happy", hold: 3_000, detail: "Checking in on Sentinel." },
      ]),
      ...walkHome(MILO_TO_SENTINEL),
    ],
    cast: [
      {
        employee: "sentinel",
        frames: [
          { pose: "standing", hold: STEP * MILO_TO_SENTINEL.length, emotion: "tired" },
          { pose: "standing", hold: 3_800, emotion: "tired", detail: "Halfway through a long shift." },
          { pose: "talking_briefly", hold: 3_000, emotion: "happy", detail: "Cheered up by Milo.", speech: "Getting there." },
        ],
      },
    ],
  },
  {
    // Nova notices somebody flagging. A director who only ever inspects is a
    // manager; one who occasionally just asks is a person.
    id: "nova-checks-on-byte",
    employee: "nova",
    weight: 0.9,
    suppressOnAlert: true,
    frames: [
      ...walk(NOVA_TO_BYTE),
      ...conversation({ col: 9, row: 7 }, [
        { pose: "talking_briefly", emotion: "happy", hold: 3_600, detail: "Asking Byte how it is going.", speech: "You alright?" },
        { pose: "standing", emotion: "neutral", hold: 2_800, detail: "Listening to Byte." },
      ]),
      ...walkHome(NOVA_TO_BYTE),
    ],
    cast: [
      {
        employee: "byte",
        frames: [
          { pose: "seated_working", hold: STEP * NOVA_TO_BYTE.length, emotion: "tired" },
          { pose: "talking_briefly", hold: 3_600, emotion: "tired", detail: "Third mug of the shift.", speech: "Third mug." },
          { pose: "seated_working", hold: 2_800, emotion: "happy", detail: "Back at it." },
        ],
      },
    ],
  },
];

AMBIENT_ROUTINES.push(
  ...RELIABILITY_ROUTINES,
  ...EXPANSION_ROUTINES,
  ...MEETING_ROUTINES,
  ...CEO_ROUTINES,
  ...BREAK_ROUTINES,
  ...VAULT_ROUTINES,
  ...KARTHIK_ROUTINES,
  ...ANALYST_ROUTINES,
  ...GAME_ROUTINES,
  ...SOCIAL_ROUTINES,
);

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
