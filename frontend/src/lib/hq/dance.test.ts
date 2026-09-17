import { describe, expect, it } from "vitest";

import { isBlockedTile } from "@/lib/hq/ambient";
import {
  AT_THEIR_POST,
  BEAT_MS,
  CYCLE_MS,
  COUNTS,
  DANCE_LEGS,
  danceEpochMs,
  FLOOR,
  route,
  SPOTS,
} from "@/lib/hq/dance";
import { EMPLOYEES, EMPLOYEE_BY_ID } from "@/lib/hq/employees";
import { isInsideRoom } from "@/lib/hq/geometry";
import { BEAT_OFFSET_SECONDS, TEMPO_BPM } from "@/lib/space-audio";

const key = (t: { col: number; row: number }) => `${t.col},${t.row}`;

describe("the dance floor", () => {
  it("has everybody dance — on the floor, or at the one post nobody may leave", () => {
    const dancing = [...DANCE_LEGS.keys()].sort();
    expect(dancing).toEqual(EMPLOYEES.map((e) => e.id).sort());
    // The floor holds everyone but the vault's custodian.
    expect([...SPOTS.keys()].sort()).toEqual(
      EMPLOYEES.map((e) => e.id)
        .filter((id) => !AT_THEIR_POST.includes(id))
        .sort(),
    );
  });

  it("keeps the vault's custodian in the vault, dancing, and never walking", () => {
    // The vault is sealed to feet: every tile of it is blocked, so there is
    // no route out, and this is the office's existing rule rather than a gap.
    expect(AT_THEIR_POST).toEqual(["vault"]);
    expect(route("vault", { col: 16, row: 12 })).toBeNull();
    const leg = DANCE_LEGS.get("vault")!;
    for (const frame of [...leg.gather, ...leg.depart]) {
      expect(frame.tile, "vault left the vault").toBeUndefined();
    }
    expect(leg.gather.some((f) => f.pose === "dancing")).toBe(true);
  });

  it("leaves the two back corners empty, so the shape is symmetric", () => {
    const taken = new Set([...SPOTS.values()].map(key));
    expect(taken.has("16,12")).toBe(false);
    expect(taken.has("21,12")).toBe(false);
    expect(taken.size).toBe(16);
  });

  it("gives nobody the same spot as anybody else", () => {
    const spots = [...SPOTS.values()].map(key);
    expect(new Set(spots).size).toBe(spots.length);
  });

  it("keeps every spot on the floor, and the floor clear of furniture", () => {
    for (const [id, spot] of SPOTS) {
      expect(spot.col, id).toBeGreaterThanOrEqual(FLOOR.col);
      expect(spot.col, id).toBeLessThan(FLOOR.col + FLOOR.cols);
      expect(spot.row, id).toBeGreaterThanOrEqual(FLOOR.row);
      expect(spot.row, id).toBeLessThan(FLOOR.row + FLOOR.rows);
    }
    for (let col = FLOOR.col; col < FLOOR.col + FLOOR.cols; col += 1) {
      for (let row = FLOOR.row; row < FLOOR.row + FLOOR.rows; row += 1) {
        expect(isBlockedTile({ col, row }), `${col},${row}`).toBe(false);
      }
    }
  });

  it("puts the CEO in the front row", () => {
    const front = FLOOR.row + FLOOR.rows - 1;
    expect(SPOTS.get("nova")!.row).toBe(front);
  });

  it("sends the analysts, who come up from the south, to the front row", () => {
    const front = FLOOR.row + FLOOR.rows - 1;
    for (const id of ["anchor", "tempo", "sigma", "halt", "chorus"] as const) {
      expect(SPOTS.get(id)!.row, id).toBe(front);
    }
  });
});

describe("the walk to the floor", () => {
  it("reaches every spot from every desk", () => {
    for (const [id, spot] of SPOTS) {
      expect(route(id, spot), `${id} is walled in`).not.toBeNull();
    }
  });

  it("only ever takes one orthogonal step at a time, on walkable floor", () => {
    for (const [id, spot] of SPOTS) {
      const path = route(id, spot)!;
      let at = EMPLOYEE_BY_ID.get(id)!.desk;
      for (const step of path) {
        const distance = Math.abs(step.col - at.col) + Math.abs(step.row - at.row);
        expect(distance, `${id} jumps from ${key(at)} to ${key(step)}`).toBe(1);
        expect(isInsideRoom(step), `${id} leaves the building at ${key(step)}`).toBe(true);
        expect(isBlockedTile(step), `${id} walks through furniture at ${key(step)}`).toBe(false);
        at = step;
      }
      expect(key(at), `${id} stops short`).toBe(key(spot));
    }
  });

  it("never walks anyone through somebody else's desk", () => {
    const desks = new Map(EMPLOYEES.map((e) => [key(e.desk), e.id]));
    for (const [id, spot] of SPOTS) {
      for (const step of route(id, spot)!) {
        const owner = desks.get(key(step));
        expect(owner === undefined || owner === id, `${id} crosses ${owner}'s desk`).toBe(true);
      }
    }
  });

  it("never walks anyone through a dancer, on the way there or home", () => {
    // Simulated rather than asserted from the schedule: for every step anyone
    // takes, is somebody else already dancing on that tile at that moment?
    const spotOf = new Map([...SPOTS].map(([id, spot]) => [key(spot), id]));
    const legTimes = (frames: { hold: number; tile?: { col: number; row: number } }[]) => {
      let t = 0;
      return frames.map((f) => {
        const at = t;
        t += f.hold;
        return { at, until: t, tile: f.tile };
      });
    };

    // Arrivals: when does each dancer start standing on their spot?
    const arrivedAt = new Map(
      [...SPOTS.keys()].map((id) => {
        const g = DANCE_LEGS.get(id)!.gather;
        return [id, g.slice(0, -1).reduce((t, f) => t + f.hold, 0)];
      }),
    );
    for (const [id] of SPOTS) {
      const steps = legTimes(DANCE_LEGS.get(id)!.gather).slice(1, -1);
      for (const step of steps) {
        const other = step.tile && spotOf.get(key(step.tile));
        if (!other || other === id) continue;
        expect(
          arrivedAt.get(other)!,
          `${id} walks through ${other}, who is already dancing there`,
        ).toBeGreaterThanOrEqual(step.until);
      }
    }

    // Departures: when does each dancer step off their spot?
    const leftAt = new Map(
      [...SPOTS.keys()].map((id) => [id, DANCE_LEGS.get(id)!.depart[0]!.hold]),
    );
    for (const [id] of SPOTS) {
      const steps = legTimes(DANCE_LEGS.get(id)!.depart).slice(1, -1);
      for (const step of steps) {
        const other = step.tile && spotOf.get(key(step.tile));
        if (!other || other === id) continue;
        expect(
          leftAt.get(other)!,
          `${id} walks home through ${other}, who is still dancing`,
        ).toBeLessThanOrEqual(step.at);
      }
    }
  });

  it("ends every gather dancing on the spot, and every depart back at the desk", () => {
    for (const [id, leg] of DANCE_LEGS) {
      const last = leg.gather[leg.gather.length - 1]!;
      expect(last.pose, id).toBe("dancing");
      const spot = SPOTS.get(id);
      if (spot) expect(key(last.tile!), id).toBe(key(spot));
      expect(leg.depart[leg.depart.length - 1]!.tile, id).toBeUndefined();
    }
  });

  it("walks home along the way it came", () => {
    for (const [id, spot] of SPOTS) {
      const there = route(id, spot)!.map(key);
      const back = DANCE_LEGS.get(id)!.depart.filter((f) => f.tile && f.pose !== "dancing");
      expect(back.map((f) => key(f.tile!)), id).toEqual([...there].reverse().slice(1));
    }
  });
});

describe("the beat", () => {
  it("keeps time to the measured tempo, in eight counts", () => {
    expect(TEMPO_BPM).toBe(130);
    expect(BEAT_MS).toBeCloseTo(461.538, 2);
    expect(COUNTS).toBe(8);
    expect(CYCLE_MS).toBeCloseTo(3692.31, 1);
  });

  it("gives every dancer the same epoch at the same moment", () => {
    // One call per dancer would be seventeen answers; the epoch depends only on
    // the page clock and the track, which is what keeps them in step.
    expect(danceEpochMs(50_000, 12)).toBe(danceEpochMs(50_000, 12));
  });

  it("puts count one on a beat of the track", () => {
    // At the instant the track is exactly on its first beat, the animation must
    // be at its own start: epoch equals now.
    expect(danceEpochMs(80_000, BEAT_OFFSET_SECONDS)).toBeCloseTo(80_000, 6);
    // Ten seconds later in both clocks, the epoch has not moved.
    expect(danceEpochMs(90_000, BEAT_OFFSET_SECONDS + 10)).toBeCloseTo(80_000, 6);
  });

  it("follows the track when it stalls, rather than the wall clock", () => {
    // Two seconds pass on the page, but the track only advanced one (it was
    // buffering). The epoch moves forward by the second the track lost.
    const before = danceEpochMs(100_000, 20);
    const after = danceEpochMs(102_000, 21);
    expect(after - before).toBeCloseTo(1_000, 6);
  });
});

describe("how quickly the floor fills", () => {
  const arrival = (id: string) => {
    const leg = DANCE_LEGS.get(id as never)!;
    return leg.gather.slice(0, -1).reduce((t, f) => t + f.hold, 0);
  };
  const floor = [...SPOTS.keys()];

  it("gets the first dancer there within a few seconds of the music", () => {
    // The first version anchored every arrival to the longest walk in the
    // building, and nobody reached the floor for over ten seconds.
    expect(Math.min(...floor.map(arrival))).toBeLessThan(5_000);
  });

  it("never holds anyone at their desk longer than the formation needs", () => {
    // A dancer waits only when leaving at once would put them on the floor
    // ahead of someone who has to arrive first. The very first to arrive
    // never waits at all.
    const first = floor.reduce((a, b) => (arrival(a) <= arrival(b) ? a : b));
    const hold = DANCE_LEGS.get(first)!.gather[0]!.hold;
    expect(hold).toBeLessThanOrEqual(1);
  });
});
