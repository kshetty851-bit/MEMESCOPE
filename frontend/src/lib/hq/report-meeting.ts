import { CONFERENCE_ROUTES, STEP_MS, conferenceApproach, type AmbientFrame } from "./ambient";
import { CONFERENCE_SEATS } from "./furniture";
import type { Tile } from "./geometry";
import type { EmployeeId } from "./employees";

/**
 * THE REPORT MEETING — CHOREOGRAPHY ONLY.
 *
 * "Provide updated report" calls the whole company into the conference room.
 * This module says where each of the ten stands and how they get there. It
 * says nothing about what they report: the words come from `report.ts`, which
 * reads real state, and the two are kept apart so that a change to the walk
 * can never quietly change a claim.
 *
 * ── SIX CHAIRS, TEN PEOPLE ──────────────────────────────────────────────
 *
 * The room is six tiles by four with a three-tile table in it, and it was
 * built for the ambient syncs, which cast three or four. Ten do not sit down.
 * Rather than grow the room — which would move furniture the floor-plan tests
 * pin, and make every other meeting look empty — four people stand: two at the
 * west end by the door, two at the east end. That is what a packed meeting
 * room looks like, and it is authored rather than solved so the tests can
 * check every position individually.
 *
 * The six seats go to the people whose sections carry the most figures; the
 * four standing positions go to the ones who report last. Nova takes the
 * centre-north seat and chairs from there.
 *
 * ── ARRIVAL ORDER IS THE COLLISION STRATEGY ─────────────────────────────
 *
 * The two west standing positions, (17,1) and (17,3), sit *on* the approach
 * the seated six walk along. So the seated six leave first and are in their
 * chairs before a stander sets off, and on the way out the standers go first.
 * Ordering is cheaper and more legible than a reservation system, and it is
 * the reason `gatherDelayMs` and `departDelayMs` exist rather than one stagger
 * constant.
 *
 * ── NOBODY TELEPORTS ────────────────────────────────────────────────────
 *
 * Every position is reached along `CONFERENCE_ROUTES` — the same authored
 * desk-to-door tiles the ambient meetings use and the route-collision tests
 * already cover — followed by an approach leg. There is no path here that is
 * not a sequence of single-tile steps, and a test asserts exactly that over
 * all ten timelines.
 */

/** Reporting order, and therefore speaking order. §10 of the brief. */
export const REPORT_ORDER: EmployeeId[] = [
  "nova",
  "radar",
  "luna",
  "dex",
  "atlas",
  "milo",
  "rex",
  "echo",
  "byte",
  "sage",
];

export interface Station {
  employee: EmployeeId;
  tile: Tile;
  /** Seated at the table, or standing against a wall. */
  seated: boolean;
}

/**
 * Where each of the ten is during the meeting.
 *
 * The four standing tiles are the only walkable non-seat tiles in the room:
 * (17,1) and (17,3) at the west end, (21,1) and (21,2) at the east. Row 0 is
 * the north wall, (16,2) and (16,3) are the glass, and (18..20, 2) is the
 * table — so this is not a preference, it is the room.
 */
export const REPORT_STATIONS: Station[] = [
  { employee: "nova", tile: CONFERENCE_SEATS[1]!, seated: true },
  { employee: "radar", tile: CONFERENCE_SEATS[0]!, seated: true },
  { employee: "luna", tile: CONFERENCE_SEATS[2]!, seated: true },
  { employee: "dex", tile: CONFERENCE_SEATS[3]!, seated: true },
  { employee: "atlas", tile: CONFERENCE_SEATS[4]!, seated: true },
  { employee: "milo", tile: CONFERENCE_SEATS[5]!, seated: true },
  { employee: "rex", tile: { col: 17, row: 1 }, seated: false },
  { employee: "echo", tile: { col: 21, row: 1 }, seated: false },
  { employee: "byte", tile: { col: 21, row: 2 }, seated: false },
  { employee: "sage", tile: { col: 17, row: 3 }, seated: false },
];

export const STATION_BY_EMPLOYEE = new Map<EmployeeId, Station>(
  REPORT_STATIONS.map((station) => [station.employee, station]),
);

/** Gap between one person setting off and the next. */
const STAGGER_MS = 900;
/** Tighter on the way out — the room empties, it does not evacuate. */
const DEPART_STAGGER_MS = 260;

/**
 * When each person leaves their desk.
 *
 * Seated first, in seating order, then the standers — see the header. The
 * standers' extra beat is the seated six's approach clearing the west tiles.
 */
export function gatherDelayMs(employee: EmployeeId): number {
  const index = REPORT_STATIONS.findIndex((station) => station.employee === employee);
  if (index < 0) return 0;
  const station = REPORT_STATIONS[index]!;
  return index * STAGGER_MS + (station.seated ? 0 : 2_600);
}

/**
 * On the way out the standers go first: they are between the seats and the door.
 *
 * Staggered *within* each group rather than by overall roster index, so the
 * seated offset cannot be overtaken by a late stander's stagger — which it was,
 * by 140ms, until a test said so.
 */
export function departDelayMs(employee: EmployeeId): number {
  const station = STATION_BY_EMPLOYEE.get(employee);
  if (!station) return 0;
  const group = REPORT_STATIONS.filter((item) => item.seated === station.seated);
  const within = group.findIndex((item) => item.employee === employee);
  const clearingTheDoor = group.length * DEPART_STAGGER_MS + STEP_MS;
  return (station.seated ? clearingTheDoor : 0) + within * DEPART_STAGGER_MS;
}

function routeTo(employee: EmployeeId, tile: Tile): Tile[] {
  const desk = CONFERENCE_ROUTES[employee];
  if (!desk) return [];
  // A stander stops at the doorway end of the corridor; a seated person
  // continues along the authored approach to their chair.
  const station = STATION_BY_EMPLOYEE.get(employee);
  if (station?.seated) return [...desk, ...conferenceApproach(tile)];
  return [...desk, ...standApproach(tile)];
}

/**
 * Doorway to a standing position.
 *
 * The corridor delivers everyone to (17,1). West standers are already there or
 * one step south of it; east standers cross the north row behind the seated
 * chairs, which is clear floor.
 */
function standApproach(tile: Tile): Tile[] {
  if (tile.col === 17) {
    const tiles: Tile[] = [];
    for (let row = 1; row <= tile.row; row += 1) tiles.push({ col: 17, row });
    return tiles;
  }
  const tiles: Tile[] = [];
  for (let col = 18; col <= 21; col += 1) tiles.push({ col, row: 1 });
  for (let row = 2; row <= tile.row; row += 1) tiles.push({ col: 21, row });
  return tiles;
}

export interface MeetingLeg {
  /** Frames that walk this person from their desk to their station. */
  gather: AmbientFrame[];
  /** Frames that walk them back. Played when the meeting ends. */
  depart: AmbientFrame[];
  /** How long `gather` takes, so the caller knows when everyone has arrived. */
  gatherMs: number;
}

function walkFrames(tiles: Tile[]): AmbientFrame[] {
  return tiles.map((tile) => ({ pose: "walking_short" as const, tile, hold: STEP_MS }));
}

/** The pose someone holds at their station while they are not speaking. */
export function listeningPose(employee: EmployeeId): AmbientFrame["pose"] {
  return STATION_BY_EMPLOYEE.get(employee)?.seated ? "seated_lounge" : "standing";
}

/** The pose someone holds while it is their turn. */
export function speakingPose(employee: EmployeeId): AmbientFrame["pose"] {
  return STATION_BY_EMPLOYEE.get(employee)?.seated ? "seated_talk" : "talking_briefly";
}

export function meetingLeg(employee: EmployeeId): MeetingLeg {
  const station = STATION_BY_EMPLOYEE.get(employee);
  if (!station) return { gather: [], depart: [], gatherMs: 0 };

  const route = routeTo(employee, station.tile);
  const wait = gatherDelayMs(employee);
  const gather: AmbientFrame[] = [
    // The wait is a frame rather than a timer so it is cancellable by the same
    // mechanism as everything else: a meeting called off mid-gather stops on a
    // frame boundary like any other routine.
    { pose: "looking_at_screen", hold: Math.max(1, wait) },
    ...walkFrames(route),
    { pose: listeningPose(employee), tile: station.tile, hold: STEP_MS },
  ];
  const depart: AmbientFrame[] = [
    { pose: listeningPose(employee), tile: station.tile, hold: Math.max(1, departDelayMs(employee)) },
    ...[...route].reverse().map((tile) => ({
      pose: "returning_to_desk" as const,
      tile,
      hold: STEP_MS,
    })),
    { pose: "returning_to_desk", hold: STEP_MS },
  ];

  return {
    gather,
    depart,
    gatherMs: gather.reduce((total, frame) => total + frame.hold, 0),
  };
}

/** Every leg, keyed by employee. Built once; the data is static. */
export const MEETING_LEGS = new Map<EmployeeId, MeetingLeg>(
  REPORT_ORDER.map((employee) => [employee, meetingLeg(employee)]),
);

/** How long until the last person is at their station. */
export const GATHER_MS = Math.max(...[...MEETING_LEGS.values()].map((leg) => leg.gatherMs));
