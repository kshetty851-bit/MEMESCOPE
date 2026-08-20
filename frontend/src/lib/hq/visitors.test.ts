import { describe, expect, it } from "vitest";

import { deriveHqState } from "@/lib/hq/adapter";
import { isWalkable } from "@/lib/hq/ambient";
import { actorClass } from "@/lib/hq/ambient-scheduler";
import { EMPLOYEES } from "@/lib/hq/employees";
import { isInsideRoom } from "@/lib/hq/geometry";
import { MAX_VISITORS, VISITORS, VISITOR_ROUTINES } from "@/lib/hq/visitors";

const key = (t: { col: number; row: number }) => `${t.col},${t.row}`;

describe("visitors are guests, not staff", () => {
  it("gives each one a department rather than a MEMESCOPE subsystem", () => {
    const subsystems = ["scanner", "scoring", "market", "paper", "wallet", "queue", "radar"];
    for (const visitor of VISITORS) {
      expect(visitor.from.length).toBeGreaterThan(0);
      for (const word of subsystems) {
        expect(visitor.from.toLowerCase()).not.toContain(word);
        expect(visitor.restingDetail.toLowerCase()).not.toContain(word);
      }
    }
  });

  it("is invisible to the operational layer", () => {
    // The same guarantee Maya, Sam and the cats have: HQ has ten readouts and
    // every one is sourced. An eleventh figure carrying a state would be the
    // first unsourced claim in the room.
    const state = deriveHqState();
    const ids = Object.keys(state.employees);
    for (const visitor of VISITORS) {
      expect(ids).not.toContain(visitor.id);
      expect(state.operational).not.toContain(visitor.id as never);
    }
  });

  it("is classed apart from every employee", () => {
    for (const visitor of VISITORS) {
      expect(actorClass(visitor.id)).toBe("visitor");
    }
    for (const employee of EMPLOYEES) {
      expect(actorClass(employee.id)).toBe("core");
    }
  });

  it("admits one at a time, as a counted cap", () => {
    expect(MAX_VISITORS).toBe(1);
  });

  it("covers the five departments the brief names", () => {
    expect(VISITORS.map((v) => v.from).sort()).toEqual([
      "Finance",
      "IT",
      "Management",
      "Operations",
      "Security",
    ]);
  });

  it("looks distinct from everyone else", () => {
    const looks = VISITORS.map((v) => `${v.look.outfit}/${v.look.accessory}/${v.look.palette}`);
    expect(new Set(looks).size).toBe(looks.length);
  });
});

describe("every visit is a real walk", () => {
  it("checks in at Reception before going anywhere", () => {
    for (const routine of VISITOR_ROUTINES) {
      const checkIn = routine.frames.findIndex((frame) =>
        (frame.detail ?? "").toLowerCase().includes("checking in"),
      );
      expect(checkIn, `${routine.id} never checks in`).toBeGreaterThanOrEqual(0);
      // And it happens before the conversation, not after.
      const talk = routine.frames.findIndex((frame) => frame.pose === "talking_briefly");
      expect(checkIn).toBeLessThan(talk);
    }
  });

  it("stands on walkable floor the whole way", () => {
    for (const routine of VISITOR_ROUTINES) {
      for (const frame of routine.frames) {
        if (!frame.tile) continue;
        if (!Number.isInteger(frame.tile.col) || !Number.isInteger(frame.tile.row)) continue;
        expect(
          isWalkable(frame.tile, routine.actor),
          `${routine.id} stands on blocked ${key(frame.tile)}`,
        ).toBe(true);
        expect(isInsideRoom(frame.tile), `${routine.id} leaves the building`).toBe(true);
      }
    }
  });

  it("walks one tile at a time", () => {
    for (const routine of VISITOR_ROUTINES) {
      const tiles = routine.frames.map((f) => f.tile).filter(Boolean) as Array<{
        col: number;
        row: number;
      }>;
      for (let i = 1; i < tiles.length; i += 1) {
        const step = Math.abs(tiles[i]!.col - tiles[i - 1]!.col) + Math.abs(tiles[i]!.row - tiles[i - 1]!.row);
        expect(step, `${routine.id} jumps ${key(tiles[i - 1]!)} → ${key(tiles[i]!)}`).toBeLessThanOrEqual(1);
      }
    }
  });

  it("leaves the building again", () => {
    for (const routine of VISITOR_ROUTINES) {
      expect(routine.frames.at(-1)!.pose).toBe("returning_to_desk");
      expect(routine.frames.at(-1)!.tile).toBeUndefined();
    }
  });

  it("never visits at night", () => {
    // Nobody from Finance comes up at three in the morning.
    for (const routine of VISITOR_ROUTINES) {
      expect(routine.nightFactor).toBe(0);
    }
  });

  it("says nothing operational", () => {
    for (const routine of VISITOR_ROUTINES) {
      const said = [
        ...routine.frames.map((f) => `${f.detail ?? ""} ${f.speech ?? ""}`),
        ...(routine.cast ?? []).flatMap((c) => c.frames.map((f) => `${f.detail ?? ""} ${f.speech ?? ""}`)),
      ]
        .join(" ")
        .toLowerCase();
      for (const word of ["token", "queue", "score", "position", "wallet", "trade", "liquidity"]) {
        expect(said, `${routine.id} said "${word}"`).not.toContain(word);
      }
    }
  });
});
