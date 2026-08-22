import { describe, expect, it } from "vitest";

import { isWalkable } from "@/lib/hq/ambient";
import { EMPLOYEES } from "@/lib/hq/employees";
import { CONFERENCE_SEATS } from "@/lib/hq/furniture";
import { isInsideRoom } from "@/lib/hq/geometry";
import {
  GATHER_MS,
  MEETING_LEGS,
  REPORT_ORDER,
  REPORT_STATIONS,
  departDelayMs,
  gatherDelayMs,
  listeningPose,
  speakingPose,
  HOLDS_THE_FLOOR,
} from "@/lib/hq/report-meeting";

const key = (tile: { col: number; row: number }) => `${tile.col},${tile.row}`;

describe("who attends", () => {
  it("accounts for every employee, in the room or on watch", () => {
    // The room holds eleven and the roster is thirteen, so this can no longer
    // be "everyone attends". What it must still be is "nobody is forgotten":
    // every employee is either walking to the conference room or deliberately
    // holding the floor, and no one is in both lists.
    expect([...REPORT_ORDER, ...HOLDS_THE_FLOOR].sort()).toEqual(
      [...EMPLOYEES.map((e) => e.id)].sort(),
    );
    for (const id of HOLDS_THE_FLOOR) {
      expect(REPORT_ORDER, `${id} is both in the room and on watch`).not.toContain(id);
    }
  });

  it("does not invite the cleaners, the caretaker or the cats", () => {
    // Maya, Sam, Cosmo and Mochi are not employees, and the type system is
    // the guarantee: REPORT_ORDER is EmployeeId[], which they are not members
    // of. This asserts the roster stayed that way.
    expect(REPORT_ORDER).toHaveLength(REPORT_STATIONS.length);
    for (const id of REPORT_ORDER) {
      expect(EMPLOYEES.some((employee) => employee.id === id)).toBe(true);
    }
  });

  it("gives every attendee exactly one station", () => {
    expect(REPORT_STATIONS).toHaveLength(REPORT_ORDER.length);
    const owners = REPORT_STATIONS.map((station) => station.employee);
    expect(new Set(owners).size).toBe(owners.length);
  });
});

describe("the room actually holds them", () => {
  it("puts nobody on top of anybody else", () => {
    const tiles = REPORT_STATIONS.map((station) => key(station.tile));
    expect(new Set(tiles).size).toBe(tiles.length);
  });

  it("seats six and stands five, because the table has six chairs", () => {
    const seated = REPORT_STATIONS.filter((station) => station.seated);
    expect(seated).toHaveLength(CONFERENCE_SEATS.length);
    expect(REPORT_STATIONS.filter((station) => !station.seated)).toHaveLength(5);
  });

  it("seats people only on real chairs", () => {
    const chairs = new Set(CONFERENCE_SEATS.map(key));
    for (const station of REPORT_STATIONS.filter((item) => item.seated)) {
      expect(chairs.has(key(station.tile)), `${station.employee} sits off-chair`).toBe(true);
    }
  });

  it("stands people on walkable floor, never in the table or the glass", () => {
    for (const station of REPORT_STATIONS.filter((item) => !item.seated)) {
      expect(
        isWalkable(station.tile, station.employee),
        `${station.employee} stands on blocked ${key(station.tile)}`,
      ).toBe(true);
    }
  });

  it("keeps everybody inside the conference room", () => {
    // cols 16–21, rows 0–3 is the room. Row 0 is its north wall.
    for (const station of REPORT_STATIONS) {
      expect(station.tile.col).toBeGreaterThanOrEqual(16);
      expect(station.tile.col).toBeLessThanOrEqual(21);
      expect(station.tile.row).toBeGreaterThanOrEqual(1);
      expect(station.tile.row).toBeLessThanOrEqual(3);
    }
  });

  it("leaves the doorway clear", () => {
    // (16,1) is the only way in. Somebody parked there is a fire exit blocked
    // and, more visibly, nine people who cannot get out when the panel closes.
    expect(REPORT_STATIONS.some((station) => key(station.tile) === "16,1")).toBe(false);
  });
});

describe("nobody teleports", () => {
  it("gives all ten a route", () => {
    for (const employee of REPORT_ORDER) {
      const leg = MEETING_LEGS.get(employee);
      expect(leg, `${employee} has no leg`).toBeDefined();
      // Atlas and Rex had no authored conference route before the report
      // meeting existed — the ambient syncs never cast either of them.
      expect(leg!.gather.length, `${employee} has an empty route`).toBeGreaterThan(2);
    }
  });

  it("walks one tile at a time, in a straight line", () => {
    for (const employee of REPORT_ORDER) {
      const leg = MEETING_LEGS.get(employee)!;
      for (const phase of [leg.gather, leg.depart]) {
        const tiles = phase.map((frame) => frame.tile).filter(Boolean) as Array<{
          col: number;
          row: number;
        }>;
        for (let i = 1; i < tiles.length; i += 1) {
          const dCol = Math.abs(tiles[i]!.col - tiles[i - 1]!.col);
          const dRow = Math.abs(tiles[i]!.row - tiles[i - 1]!.row);
          expect(
            dCol + dRow,
            `${employee} jumps ${key(tiles[i - 1]!)} → ${key(tiles[i]!)}`,
          ).toBeLessThanOrEqual(1);
        }
      }
    }
  });

  it("never steps through furniture, a wall or the vault", () => {
    for (const employee of REPORT_ORDER) {
      const leg = MEETING_LEGS.get(employee)!;
      for (const phase of [leg.gather, leg.depart]) {
        for (const frame of phase) {
          if (!frame.tile) continue;
          if (!Number.isInteger(frame.tile.col) || !Number.isInteger(frame.tile.row)) continue;
          const seated = REPORT_STATIONS.find(
            (station) => station.employee === employee && station.seated,
          );
          // A seated person's final tile is a chair, which is sittable rather
          // than walkable. Every other tile must be floor.
          if (seated && key(frame.tile) === key(seated.tile)) continue;
          expect(
            isWalkable(frame.tile, employee),
            `${employee} walks through ${key(frame.tile)}`,
          ).toBe(true);
        }
      }
    }
  });

  it("never leaves the room's footprint", () => {
    for (const employee of REPORT_ORDER) {
      for (const frame of MEETING_LEGS.get(employee)!.gather) {
        if (!frame.tile) continue;
        expect(isInsideRoom(frame.tile), `${employee} exits the building`).toBe(true);
      }
    }
  });

  it("ends the departure back at the desk, not at the table", () => {
    for (const employee of REPORT_ORDER) {
      const depart = MEETING_LEGS.get(employee)!.depart;
      expect(depart.at(-1)!.pose).toBe("returning_to_desk");
      // The last frame carries no tile: that is the rig's "you are home" frame.
      expect(depart.at(-1)!.tile).toBeUndefined();
    }
  });
});

describe("arrival order keeps the west end clear", () => {
  /**
   * Two standing positions sit on the seated six's approach. The ordering is
   * the whole collision strategy, so it is asserted rather than assumed.
   */
  it("sends every seated attendee off before any stander", () => {
    const lastSeated = Math.max(
      ...REPORT_STATIONS.filter((s) => s.seated).map((s) => gatherDelayMs(s.employee)),
    );
    const firstStander = Math.min(
      ...REPORT_STATIONS.filter((s) => !s.seated).map((s) => gatherDelayMs(s.employee)),
    );
    expect(firstStander).toBeGreaterThan(lastSeated);
  });

  it("sends the standers out first on the way home", () => {
    const lastStander = Math.max(
      ...REPORT_STATIONS.filter((s) => !s.seated).map((s) => departDelayMs(s.employee)),
    );
    const firstSeated = Math.min(
      ...REPORT_STATIONS.filter((s) => s.seated).map((s) => departDelayMs(s.employee)),
    );
    expect(lastStander).toBeLessThan(firstSeated);
  });

  it("knows when the last person is seated", () => {
    expect(GATHER_MS).toBeGreaterThan(0);
    for (const leg of MEETING_LEGS.values()) {
      expect(leg.gatherMs).toBeLessThanOrEqual(GATHER_MS);
    }
  });
});

describe("poses", () => {
  it("sits the seated and stands the standing, speaking or not", () => {
    for (const station of REPORT_STATIONS) {
      if (station.seated) {
        expect(listeningPose(station.employee)).toBe("seated_lounge");
        expect(speakingPose(station.employee)).toBe("seated_talk");
      } else {
        expect(listeningPose(station.employee)).toBe("standing");
        expect(speakingPose(station.employee)).toBe("talking_briefly");
      }
    }
  });
});
