import type { AmbientFrame } from "./ambient";
import { isWalkable } from "./ambient";
import { EMPLOYEES, EMPLOYEE_BY_ID, type EmployeeId } from "./employees";
import type { Tile } from "./geometry";
import { BEAT_OFFSET_SECONDS, TEMPO_BPM } from "@/lib/space-audio";

/**
 * THE DANCE FLOOR.
 *
 * Karthik's request, 2026-09-17: when the music plays, everybody in HQ comes
 * down to the lobby and dances — crazy, but in step.
 *
 * ── WHAT THIS IS, AND WHAT IT IS NOT ────────────────────────────────────
 *
 * Presentation, triggered by a person pressing a button. It says nothing
 * about MEMESCOPE: a desk that is dancing is not a desk that is idle, and the
 * status each person carries is still drawn, unchanged, while they dance. The
 * report meeting set that precedent — it walks Patch away from a repair to
 * stand at a table — and this follows it rather than inventing a second rule.
 *
 * ── "IN STEP" IS TWO PROBLEMS ───────────────────────────────────────────
 *
 * In step with each other: sixteen people arrive on the floor at sixteen
 * different moments, so their CSS animations start at sixteen different times.
 * Identical keyframes would still leave them out of phase. The fix is to pin
 * every dance animation's `startTime` to ONE shared epoch — see `danceEpochMs`.
 *
 * In step with the music: that epoch is computed from where the track actually
 * is, not from when the button was pressed. A track that stalls to buffer
 * stops advancing; a clock started on the click would not.
 *
 * ── THE FLOOR ───────────────────────────────────────────────────────────
 *
 * Columns 16-21, rows 12-14: the east end of reception and the corridor in
 * front of it. The only clear rectangle in the building big enough for
 * everyone — six by three, eighteen spots, no furniture, nothing to step
 * round. Sixteen dancers take it; the two back corners stay empty, which
 * turns the block into a deliberate shape rather than a crowd with a gap.
 *
 * ── EVERYONE DANCES. ONE OF THEM DANCES AT THE POST. ────────────────────
 *
 * Vault's desk is inside the execution vault, and the vault is sealed to feet
 * as well as to funds: every tile of it is blocked, so there is no walk out,
 * and no Vault routine anywhere in the office has ever moved him. The report
 * meeting already respects that — Vault holds the floor. So does this. Vault
 * dances where he sits, on the same beat as the other sixteen, behind glass.
 */

export const FLOOR = { col: 16, row: 12, cols: 6, rows: 3 } as const;

/** The two back corners, left empty so the formation is symmetric. */
const EMPTY_SPOTS: readonly Tile[] = [
  { col: 16, row: 12 },
  { col: 21, row: 12 },
];

/** Dances at their own desk, in step, and never walks. See the header. */
export const AT_THEIR_POST: readonly EmployeeId[] = ["vault"];

/** Where the CEO dances: front row, near the middle. */
const LEAD_SPOT: Tile = { col: 18, row: 14 };

export const BEAT_MS = 60_000 / TEMPO_BPM;
/** One full routine is eight counts — a phrase, the way dancers count. */
export const COUNTS = 8;
export const CYCLE_MS = BEAT_MS * COUNTS;

/** Walking pace to the floor. The meeting's brisk pace, not the ambient stroll. */
export const STEP_MS = 620;
/** Gap between one dancer reaching the floor and the next. */
const ARRIVAL_GAP_MS = 260;

const key = (t: Tile) => `${t.col},${t.row}`;

/** Every spot, front row first, then middle, then back. */
function spotsFrontToBack(): Tile[] {
  const spots: Tile[] = [];
  for (let row = FLOOR.row + FLOOR.rows - 1; row >= FLOOR.row; row -= 1) {
    for (let col = FLOOR.col; col < FLOOR.col + FLOOR.cols; col += 1) {
      const spot = { col, row };
      if (!EMPTY_SPOTS.some((e) => key(e) === key(spot))) spots.push(spot);
    }
  }
  return spots;
}

/**
 * Who stands where.
 *
 * Nova leads. Everyone else is placed by where their desk is: the southern
 * desks take the front row and the northern ones the back, and within a row
 * west stays west. The point is that nobody has to walk THROUGH somebody who
 * is already dancing — the Rafiq analysts come up from the south, so they
 * fill the southern row, and the rest come down from the north behind them.
 */
function assign(): Map<EmployeeId, Tile> {
  const out = new Map<EmployeeId, Tile>([["nova", LEAD_SPOT]]);
  const open = spotsFrontToBack().filter((s) => key(s) !== key(LEAD_SPOT));
  const rest = EMPLOYEES.filter(
    (e) => e.id !== "nova" && !AT_THEIR_POST.includes(e.id),
  ).sort(
    (a, b) => b.desk.row - a.desk.row || a.desk.col - b.desk.col,
  );

  // Fill row by row. Within a row, dancers and spots are both sorted west to
  // east so the paths do not cross.
  let cursor = 0;
  for (let row = FLOOR.row + FLOOR.rows - 1; row >= FLOOR.row; row -= 1) {
    const spotsInRow = open.filter((s) => s.row === row).sort((a, b) => a.col - b.col);
    const group = rest
      .slice(cursor, cursor + spotsInRow.length)
      .sort((a, b) => a.desk.col - b.desk.col);
    group.forEach((e, i) => out.set(e.id, spotsInRow[i]!));
    cursor += spotsInRow.length;
  }
  return out;
}

export const SPOTS: ReadonlyMap<EmployeeId, Tile> = assign();

/**
 * The shortest walk from a desk to a spot, one orthogonal step at a time.
 *
 * `ambient.ts` hand-authors every route, and says why: waypoints are data, so
 * a test can check none of them passes through a desk. A breadth-first search
 * over `isWalkable` keeps that property by construction — it can only ever
 * step on a tile `isWalkable` allows — and its output is the same plain data
 * the tests read. What changed is the count: sixteen routes to one place is
 * where hand-authoring stops being the careful option and becomes the
 * error-prone one.
 *
 * Neighbours are tried in a fixed order, so the same office always produces
 * the same routes. Returns the steps AFTER the desk, or null if walled in.
 */
export function route(walker: EmployeeId, to: Tile): Tile[] | null {
  const from = EMPLOYEE_BY_ID.get(walker)?.desk;
  if (!from) return null;
  const goal = key(to);
  const previous = new Map<string, Tile | null>([[key(from), null]]);
  const queue: Tile[] = [from];

  while (queue.length > 0) {
    const here = queue.shift()!;
    if (key(here) === goal) {
      const path: Tile[] = [];
      for (let at: Tile | null = here; at && key(at) !== key(from); at = previous.get(key(at))!) {
        path.push(at);
      }
      return path.reverse();
    }
    for (const [dc, dr] of [
      [0, 1],
      [1, 0],
      [0, -1],
      [-1, 0],
    ] as const) {
      const next = { col: here.col + dc, row: here.row + dr };
      if (previous.has(key(next)) || !isWalkable(next, walker)) continue;
      previous.set(key(next), here);
      queue.push(next);
    }
  }
  return null;
}

export interface DanceLeg {
  /** Waits at the desk, walks to the spot, and starts dancing. */
  gather: AmbientFrame[];
  /** Keeps dancing for a moment, then walks home. */
  depart: AmbientFrame[];
}

const walk = (tiles: Tile[], pose: AmbientFrame["pose"]): AmbientFrame[] =>
  tiles.map((tile) => ({ pose, tile, hold: STEP_MS, emotion: "happy" }));

/**
 * The frame everyone holds while the music plays.
 *
 * `happy` is allowed here on the rule `ambient.ts` states for emotions: a face
 * describes the person, never the system, and the ones that may appear are the
 * ones a social moment motivates. Being at a dance party is that moment.
 */
const dancing = (hold: number, tile?: Tile): AmbientFrame => ({
  pose: "dancing",
  tile,
  hold,
  emotion: "happy",
  detail: "Dancing in the lobby.",
});

/**
 * Who has to be where before whom, read off the actual routes.
 *
 * X crosses Y when X's walk to the floor steps on Y's spot. Then X must arrive
 * before Y (or X walks through a dancer), and on the way home Y must leave
 * first (or X walks back through them).
 *
 * The first version assumed "front row first", and the routes say otherwise:
 * most people reach the floor along the corridor from the west, straight over
 * the two front-row spots at that end. Those have to fill LAST. Computing it
 * rather than assuming it is what keeps it right when a desk moves.
 */
export function crossings(paths: ReadonlyMap<EmployeeId, Tile[]>): Map<EmployeeId, Set<EmployeeId>> {
  const owner = new Map([...SPOTS].map(([id, spot]) => [key(spot), id]));
  const out = new Map<EmployeeId, Set<EmployeeId>>();
  for (const [id, path] of paths) {
    const crossed = new Set<EmployeeId>();
    for (const tile of path.slice(0, -1)) {
      const other = owner.get(key(tile));
      if (other && other !== id) crossed.add(other);
    }
    out.set(id, crossed);
  }
  return out;
}

/** Kahn's algorithm over "X before Y". Anything left in a cycle goes last. */
function topological(ids: EmployeeId[], before: Map<EmployeeId, Set<EmployeeId>>): EmployeeId[] {
  const incoming = new Map(ids.map((id) => [id, 0]));
  for (const targets of before.values()) {
    for (const t of targets) incoming.set(t, (incoming.get(t) ?? 0) + 1);
  }
  const ready = ids.filter((id) => incoming.get(id) === 0);
  const order: EmployeeId[] = [];
  while (ready.length > 0) {
    const id = ready.shift()!;
    order.push(id);
    for (const t of before.get(id) ?? []) {
      incoming.set(t, incoming.get(t)! - 1);
      if (incoming.get(t) === 0) ready.push(t);
    }
  }
  return [...order, ...ids.filter((id) => !order.includes(id))];
}

/**
 * Everyone's legs: each dancer arrives as early as their own walk allows,
 * but never before anyone who has to cross their spot to get to their own.
 */
function legs(): Map<EmployeeId, DanceLeg> {
  const ids = [...SPOTS.keys()];
  const paths = new Map(ids.map((id) => [id, route(id, SPOTS.get(id)!) ?? []]));
  const before = crossings(paths);

  const arrive = new Map<EmployeeId, number>();
  for (const id of topological(ids, before)) {
    let at = paths.get(id)!.length * STEP_MS;
    for (const [other, crossed] of before) {
      if (crossed.has(id) && arrive.has(other)) {
        at = Math.max(at, arrive.get(other)! + ARRIVAL_GAP_MS);
      }
    }
    arrive.set(id, at);
  }

  // Home is the same graph read backwards: whoever was crossed leaves first.
  const leave = new Map<EmployeeId, number>();
  const reversed = new Map<EmployeeId, Set<EmployeeId>>(ids.map((id) => [id, new Set()]));
  for (const [x, crossed] of before) for (const y of crossed) reversed.get(y)!.add(x);
  for (const id of topological(ids, reversed)) {
    let at = 0;
    for (const y of before.get(id) ?? []) {
      if (leave.has(y)) at = Math.max(at, leave.get(y)! + STEP_MS);
    }
    leave.set(id, at);
  }

  const out = new Map<EmployeeId, DanceLeg>();
  const floorLeaves = Math.max(...leave.values());
  for (const id of AT_THEIR_POST) {
    out.set(id, {
      // No tile anywhere: every frame is at the desk.
      gather: [
        { pose: "cheering", hold: STEP_MS, emotion: "happy" },
        { ...dancing(CYCLE_MS), detail: "Dancing at the vault door." },
      ],
      depart: [{ ...dancing(Math.max(1, floorLeaves)), detail: "Dancing at the vault door." }],
    });
  }
  for (const id of ids) {
    const path = paths.get(id)!;
    const spot = SPOTS.get(id)!;
    out.set(id, {
      gather: [
        // They hear it first. A beat of excitement at the desk, then off.
        { pose: "cheering", hold: Math.max(1, arrive.get(id)! - path.length * STEP_MS), emotion: "happy" },
        ...walk(path, "walking_short"),
        dancing(CYCLE_MS, spot),
      ],
      depart: [
        dancing(Math.max(1, leave.get(id)!), spot),
        ...walk([...path].reverse().slice(1), "returning_to_desk"),
        { pose: "returning_to_desk", hold: STEP_MS },
      ],
    });
  }
  return out;
}

export const DANCE_LEGS: ReadonlyMap<EmployeeId, DanceLeg> = legs();

/**
 * The moment every dance animation should treat as its start, on the
 * document timeline, given where the music is.
 *
 * Any start time works for an infinite animation; what matters is that all
 * of them share one, and that the one they share puts count 1 on a beat.
 * Beat 0 of the track is `BEAT_OFFSET_SECONDS` in, so that instant — mapped
 * onto the page's timeline — is the epoch.
 */
export function danceEpochMs(timelineNowMs: number, trackSeconds: number): number {
  return timelineNowMs - (trackSeconds - BEAT_OFFSET_SECONDS) * 1000;
}
