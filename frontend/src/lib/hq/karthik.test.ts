import fs from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

import { deriveHqState, react, type HqWitness } from "./adapter";
import {
  AMBIENT_ROUTINES,
  isWalkable,
  ROUTINES_BY_EMPLOYEE,
} from "./ambient";
import { CATS, CAT_ROUTINES } from "./cats";
import { CHARACTERS, SHAPE_AXES, sharedAxes } from "./characters";
import { EMPLOYEES, EMPLOYEE_BY_ID } from "./employees";
import { FURNITURE } from "./furniture";
import { GRID_COLS, GRID_ROWS, rectsOverlap } from "./geometry";
import { HOLDS_THE_FLOOR, REPORT_ORDER } from "./report-meeting";
import { ZONES, ZONE_BY_ID } from "./zones";

/**
 * KARTHIK — THE CONTRACT.
 *
 * The tests that would fail if the fourteenth desk ever stopped being what it
 * was built to be: one operator, one wallet, no authority over anything else,
 * and no animation that claims something the backend did not say.
 */

const SRC = path.join(process.cwd(), "src");
const read = (rel: string) => fs.readFileSync(path.join(SRC, rel), "utf8");

/* ── identity ────────────────────────────────────────────────────────── */

describe("Karthik is on the roster like everybody else", () => {
  it("has a roster entry, a character and a room", () => {
    const employee = EMPLOYEE_BY_ID.get("karthik");
    expect(employee).toBeDefined();
    expect(employee!.name).toBe("Karthik");
    expect(employee!.role).toBe("Founder");
    expect(employee!.zone).toBe("karthik");
    expect(employee!.department).toBe("karthik_lab");
    expect(CHARACTERS.karthik).toBeDefined();
    expect(ZONE_BY_ID.get("karthik")!.label).toBe("Karthik Lab");
  });

  it("is drawn from the shared rig, not from artwork of his own", () => {
    // The differentiation contract already asserts this for the whole cast;
    // this pins the *mechanism* for Karthik specifically, because a new
    // character is exactly when somebody is tempted to reach for an image.
    const rig = read("components/hq/character-rig.tsx");
    expect(rig).toContain('case "undercut"');
    expect(rig).toContain('case "track-jacket"');
    expect(rig).toContain('case "headphones"');
    expect(rig).not.toMatch(/<image/i);
  });

  it("is distinguishable from all thirteen others without colour", () => {
    for (const other of Object.values(CHARACTERS)) {
      if (other.id === "karthik") continue;
      const differing = SHAPE_AXES.length - sharedAxes(CHARACTERS.karthik, other).length;
      expect(differing, `karthik vs ${other.id}`).toBeGreaterThanOrEqual(3);
    }
  });

  it("has a palette token that actually resolves", () => {
    expect(read("styles/characters.css")).toContain(
      `--hq-${CHARACTERS.karthik.palette}:`,
    );
  });
});

/* ── the room, and what making it cost ───────────────────────────────── */

describe("Karthik Lab, and the deck it was carved from", () => {
  const lab = ZONE_BY_ID.get("karthik")!;
  const deck = ZONE_BY_ID.get("deck")!;

  it("sits inside the building and overlaps no other department", () => {
    expect(lab.rect.col + lab.rect.cols).toBeLessThanOrEqual(GRID_COLS);
    expect(lab.rect.row + lab.rect.rows).toBeLessThanOrEqual(GRID_ROWS);
    for (const zone of ZONES) {
      if (zone.id === "karthik") continue;
      expect(rectsOverlap(lab.rect, zone.rect), `karthik overlaps ${zone.id}`).toBe(false);
    }
  });

  it("reduced the break deck without removing it", () => {
    // The brief's actual requirement, as arithmetic: smaller than it was,
    // and still there. A future edit that deletes the deck to make room
    // fails here.
    const tiles = deck.rect.cols * deck.rect.rows;
    expect(tiles).toBeGreaterThan(0);
    expect(tiles).toBeLessThan(6 * 8);
    expect(deck.surface).toBe("deck");
  });

  it("kept every tile the break routines actually stand on", () => {
    // The deck lost rows 8-11 and nothing else. Every authored destination on
    // it — the smoking railing, the benches, the coffee spots — is at row 6 or
    // above, so the reduction cost no choreography at all. This is the check
    // that would have caught it if it had.
    const deckFrames = AMBIENT_ROUTINES.flatMap((routine) =>
      routine.frames
        .filter((frame) => frame.tile && frame.tile.col >= 16)
        .map((frame) => ({ id: routine.id, tile: frame.tile! })),
    );
    expect(deckFrames.length).toBeGreaterThan(0);
    for (const { id, tile } of deckFrames) {
      const insideDeck =
        tile.row >= deck.rect.row && tile.row < deck.rect.row + deck.rect.rows;
      const insideConference = tile.row < 4;
      const insideLab = tile.row >= lab.rect.row && tile.row < lab.rect.row + lab.rect.rows;
      expect(
        insideDeck || insideConference || insideLab,
        `${id} stands at ${tile.col},${tile.row}, which is no longer any room`,
      ).toBe(true);
    }
  });

  it("leaves the four tiles around Karthik's desk clear", () => {
    // Every authored route out of the lab starts on one of these. A prop on
    // any of them walls him in at his own bench.
    const desk = EMPLOYEE_BY_ID.get("karthik")!.desk;
    const neighbours: Array<readonly [number, number]> = [
      [0, -1],
      [0, 1],
      [-1, 0],
      [1, 0],
    ];
    for (const [dc, dr] of neighbours) {
      const tile = { col: desk.col + dc, row: desk.row + dr };
      expect(
        isWalkable(tile, "karthik"),
        `${tile.col},${tile.row} beside Karthik's desk is blocked`,
      ).toBe(true);
    }
  });

  it("furnishes the lab with the room the brief asks for", () => {
    const inLab = FURNITURE.filter(
      (piece) =>
        piece.tile.col >= lab.rect.col &&
        piece.tile.col < lab.rect.col + lab.rect.cols &&
        piece.tile.row >= lab.rect.row &&
        piece.tile.row < lab.rect.row + lab.rect.rows,
    ).map((piece) => piece.kind);
    expect(inLab).toContain("wall-display");
    expect(inLab).toContain("cat-bed");
    // The food and drink area.
    expect(inLab).toContain("counter-micro");
  });

});

/* ── routines ────────────────────────────────────────────────────────── */

describe("Karthik's routines, and the ones he is not allowed to pick", () => {
  const routines = ROUTINES_BY_EMPLOYEE.get("karthik") ?? [];

  it("gives him one of the busiest idle vocabularies in the office", () => {
    // §6 asks for one of the most active characters, not the single most: Nova
    // tours the building and Echo is permanently mid-errand, and beating them
    // by padding this list would be animation for its own sake.
    expect(routines.length).toBeGreaterThanOrEqual(8);
    const busiest = EMPLOYEES.map(
      (employee) => (ROUTINES_BY_EMPLOYEE.get(employee.id) ?? []).length,
    ).sort((a, b) => b - a);
    expect(routines.length).toBeGreaterThanOrEqual(busiest[2]!);
  });

  it("keeps every one of his frames on walkable floor", () => {
    for (const routine of routines) {
      for (const frame of [
        ...routine.frames,
        ...(routine.cast ?? []).flatMap((member) => member.frames),
      ]) {
        if (!frame.tile) continue;
        expect(
          isWalkable(frame.tile, routine.employee),
          `${routine.id} stands on blocked ${frame.tile.col},${frame.tile.row}`,
        ).toBe(true);
      }
    }
  });

  it("says nothing operational in any ambient frame", () => {
    // A detail line is drawn in the personality panel and, for speech, above
    // the figure. None of them may name a figure, a target or a wallet state.
    const forbidden = /\$|%|\btarget hit\b|\bprofit\b|\bequity\b|\d+\s*x\b/i;
    for (const routine of routines) {
      for (const frame of routine.frames) {
        for (const text of [frame.detail, frame.speech]) {
          if (!text) continue;
          expect(forbidden.test(text), `${routine.id}: "${text}"`).toBe(false);
        }
      }
    }
  });

  it("does not force him into the standing briefing", () => {
    // §20: the conference room seats eleven and eleven people already fill it.
    // He holds the floor instead, like Sentinel and Quinn.
    expect(REPORT_ORDER).not.toContain("karthik");
    expect(HOLDS_THE_FLOOR).toContain("karthik");
  });
});

/* ── Satoshi ─────────────────────────────────────────────────────────── */

describe("Satoshi", () => {
  it("is a cat, with a bed, and never an employee", () => {
    const satoshi = CATS.find((cat) => cat.id === "satoshi");
    expect(satoshi).toBeDefined();
    expect(EMPLOYEES.map((employee) => employee.id)).not.toContain("satoshi" as never);
    expect(
      FURNITURE.some((piece) => piece.kind === "cat-bed"),
      "no cat bed in the office",
    ).toBe(true);
  });

  it("has routines, and every one of them ends back in the bed", () => {
    const routines = CAT_ROUTINES.filter((routine) => routine.actor === "satoshi");
    expect(routines.length).toBeGreaterThanOrEqual(5);
    const home = CATS.find((cat) => cat.id === "satoshi")!.home;
    for (const routine of routines) {
      const last = routine.frames.at(-1)!;
      expect(last.tile ?? home, `${routine.id} does not end at home`).toEqual(home);
    }
  });

  it("cannot reach a trading decision, because nothing imports him", () => {
    // The architectural guarantee, restated for the third cat: the module that
    // decides what MEMESCOPE is doing must not know the office has cats.
    expect(read("lib/hq/adapter.ts")).not.toMatch(/from "\.\/cats"/);
    const state = deriveHqState();
    expect(Object.keys(state.employees)).not.toContain("satoshi");
  });
});

/* ── reactions ───────────────────────────────────────────────────────── */

describe("real events, and only real events", () => {
  const NOW = 1_760_000_000_000;

  function base(over: Partial<HqWitness> = {}): HqWitness {
    return {
      auditTotal: 10,
      openPositions: 3,
      lastCloseNet: "1.00",
      radarOpportunities: 100,
      lastDiscovery: "2026-08-20T10:00:00Z",
      lastScore: "2026-08-20T10:00:00Z",
      lastSnapshot: "2026-08-20T10:00:00Z",
      securityEvaluations: 5,
      queueDepth: 20,
      pipelineOverall: "healthy",
      karthikTrades: 125,
      karthikRugs: 0,
      karthikBalance: 777.8,
      ...over,
    };
  }

  it("reacts only when Karthik's Lab closed a trade", () => {
    expect(react(base(), base(), NOW).karthik).toBeUndefined();
    const green = react(base(), base({ karthikTrades: 126, karthikBalance: 779.1 }), NOW);
    expect(green.karthik?.state).toBe("success");
    const red = react(base(), base({ karthikTrades: 126, karthikBalance: 760 }), NOW);
    expect(red.karthik?.state).toBe("reviewing");
  });

  it("puts a rug above an ordinary close", () => {
    const rug = react(base(), base({ karthikTrades: 126, karthikRugs: 1, karthikBalance: 670 }), NOW);
    expect(rug.karthik?.state).toBe("reviewing");
    expect(rug.karthik?.detail).toContain("rug");
  });

  it("reacts to nothing on a first reading", () => {
    const unread = base({ karthikTrades: null, karthikRugs: null, karthikBalance: null });
    expect(react(unread, base(), NOW).karthik).toBeUndefined();
  });
});

/* ── isolation ───────────────────────────────────────────────────────── */

describe("Karthik reads his book and nothing else", () => {
  it("reads its own source and never the Original Paper Wallet's", () => {
    const adapter = read("lib/hq/adapter.ts");
    const derive = adapter.slice(
      adapter.indexOf("function deriveKarthik"),
      adapter.indexOf("export interface HqWitness"),
    );
    for (const foreign of [
      "paperWallet",
      "paperPositions",
      "paperAudit",
      "executionPosture",
      "radarPerformance",
    ]) {
      expect(derive, `deriveKarthik reads ${foreign}`).not.toContain(foreign);
    }
  });
});
