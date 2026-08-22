import fs from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

import { deriveHqState, react, type HqWitness } from "./adapter";
import {
  AMBIENT_ROUTINES,
  KARTHIK_EVENT_ROUTINES,
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
    expect(employee!.role).toBe("Paper Wallet Operator");
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
    for (const [dc, dr] of [
      [0, -1],
      [0, 1],
      [-1, 0],
      [1, 0],
    ]) {
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
    for (const routine of [...routines, ...Object.values(KARTHIK_EVENT_ROUTINES)]) {
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

  it("routes the escalation to Nova across real floor, and back", () => {
    const escalate = KARTHIK_EVENT_ROUTINES.owner_required;
    expect(escalate.frames.at(-1)!.tile).toBeUndefined(); // ends at his own desk
    const talking = escalate.frames.find((frame) => frame.pose === "talking_briefly");
    expect(talking).toBeDefined();
    // Beside Nova, not on her desk.
    const nova = EMPLOYEE_BY_ID.get("nova")!.desk;
    const distance = Math.max(
      Math.abs(talking!.tile!.col - nova.col),
      Math.abs(talking!.tile!.row - nova.row),
    );
    expect(distance).toBeGreaterThan(0);
    expect(distance).toBeLessThanOrEqual(2);
  });

  /**
   * THE RULE THAT MATTERS MOST IN THIS FILE.
   *
   * §6: no fake business event may be generated to drive an animation. The
   * scheduler picks from `AMBIENT_ROUTINES`; if a celebration were in there it
   * could fire on a timer, and a dance on a timer is a claim that a target
   * hit. So the check is structural — the event routines must not be reachable
   * from the array the dice read.
   */
  it("keeps every event reaction out of the scheduler's reach", () => {
    const schedulable = new Set(AMBIENT_ROUTINES.map((routine) => routine.id));
    for (const routine of Object.values(KARTHIK_EVENT_ROUTINES)) {
      expect(
        schedulable.has(routine.id),
        `${routine.id} can be picked at random`,
      ).toBe(false);
      // Weight zero as well, so even an accidental push into the array cannot
      // make one selectable.
      expect(routine.weight).toBe(0);
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
      karthikTargetHits: 2,
      karthikOpenPositions: 4,
      karthikDeadPositions: 1,
      karthikOpenIncidents: 0,
      karthikOwnerItems: 0,
      ...over,
    };
  }

  it("celebrates only when the published target count actually rose", () => {
    const quiet = react(base(), base(), NOW);
    expect(quiet.karthik).toBeUndefined();

    const hit = react(base(), base({ karthikTargetHits: 3 }), NOW);
    expect(hit.karthik?.state).toBe("success");
    expect(hit.karthik?.detail).toContain("1.25x");
  });

  it("cannot celebrate while the wallet is unbound", () => {
    // Unbound reports null for every counter, and a null on either side of the
    // comparison means no reaction can fire. This is the check that makes
    // "the room shows nothing because there is nothing" true rather than
    // hoped for.
    const unbound = base({
      karthikTargetHits: null,
      karthikOpenPositions: null,
      karthikDeadPositions: null,
      karthikOpenIncidents: null,
      karthikOwnerItems: null,
    });
    expect(react(unbound, unbound, NOW).karthik).toBeUndefined();
  });

  it("puts an owner-attention item above everything else he could be doing", () => {
    const both = react(
      base(),
      base({ karthikOwnerItems: 1, karthikTargetHits: 3 }),
      NOW,
    );
    expect(both.karthik?.state).toBe("incident");
  });

  it("reads the lifetime counters, not the daily ones", () => {
    // A daily counter resets at midnight, and a counter that resets looks like
    // it went down — which would swallow the next real hit.
    const source = read("lib/hq/adapter.ts");
    expect(source).toContain("reports?.lifetime");
  });
});

/* ── isolation ───────────────────────────────────────────────────────── */

describe("Karthik touches one wallet and no other", () => {
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

  it("renders its panel from the karthik source alone", () => {
    const panel = read("components/hq/karthik-panel.tsx");
    expect(panel).toContain('from "@/lib/hq/karthik"');
    for (const foreign of ["paper-wallet", "paperWallet", "strategy-lab", "real-wallet"]) {
      expect(panel, `the panel reads ${foreign}`).not.toContain(foreign);
    }
  });

  it("offers no control that could change anything", () => {
    // §14 and §23: no approve button, no repair button, no autonomy toggle.
    // Arming autonomy is an environment variable and a separate decision; a
    // switch here would make it a click.
    const panel = read("components/hq/karthik-panel.tsx");
    expect(panel).not.toMatch(/api\.(post|put|patch|delete)/);
    expect(panel).not.toMatch(/useMutation/);
  });
});
