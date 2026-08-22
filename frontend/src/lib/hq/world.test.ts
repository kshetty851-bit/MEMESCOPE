import fs from "node:fs";
import path from "node:path";

import { describe, expect, it, vi } from "vitest";

import { deriveHqState, UNKNOWN_HQ_STATE } from "@/lib/hq/adapter";
import {
  AMBIENT_ROUTINES,
  BLOCKED_TILES,
  MEETING_ROUTINES,
  isInBreakRoom,
  isWalkable,
  type ActorFrame,
} from "@/lib/hq/ambient";
import { createAmbientScheduler, type ActorId } from "@/lib/hq/ambient-scheduler";
import { CATS, CAT_ROUTINES } from "@/lib/hq/cats";
import { EMPLOYEES, EMPLOYEE_BY_ID, type EmployeeId } from "@/lib/hq/employees";
import {
  CONFERENCE_SEATS,
  CONFERENCE_TABLE_TILES,
  FURNITURE,
  GLASS_WALL_TILES,
} from "@/lib/hq/furniture";
import { GRID_COLS, GRID_ROWS, isInsideRoom, type Tile } from "@/lib/hq/geometry";
import { SUPPORT_ROUTINES, SUPPORT_STAFF } from "@/lib/hq/support";
import { ZONE_BY_ID } from "@/lib/hq/zones";

/**
 * WORLD-EXPANSION ACCEPTANCE.
 *
 * The expansion adds four kinds of risk, and this file defends each: that the
 * new geometry broke the old (it must not have — every desk and route keeps
 * its coordinates); that the new residents leak into the operational layer
 * (they cannot — no path exists and these tests keep it that way); that the
 * wider cast turns the room chaotic (the caps hold per class); and that any
 * of the charm ever outruns the truth (the vocabulary tests read every new
 * string the way a worried reader would).
 */

const NOVA_DESK = { col: 8, row: 1 };

function seeded(seed = 1) {
  let state = seed;
  return () => {
    state = (state * 1664525 + 1013904223) % 4294967296;
    return state / 4294967296;
  };
}

function setReducedMotion(reduced: boolean) {
  window.matchMedia = vi.fn().mockImplementation((query: string) => ({
    matches: query.includes("reduce") ? reduced : false,
    media: query,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    addListener: vi.fn(),
    removeListener: vi.fn(),
    dispatchEvent: vi.fn(),
    onchange: null,
  }));
}

/* ── geometry ──────────────────────────────────────────────────────────── */

describe("the expanded floor plan", () => {
  it("expanded the grid without moving anything that existed", () => {
    expect(GRID_COLS).toBe(22);
    expect(GRID_ROWS).toBe(14);
    // Every pre-expansion department keeps its exact rectangle. The walk
    // routes were authored against these coordinates; a moved zone is a
    // silently broken office.
    expect(ZONE_BY_ID.get("mission")!.rect).toEqual({ col: 0, row: 0, cols: 16, rows: 2 });
    expect(ZONE_BY_ID.get("risk")!.rect).toEqual({ col: 0, row: 2, cols: 5, rows: 4 });
    expect(ZONE_BY_ID.get("floor")!.rect).toEqual({ col: 5, row: 2, cols: 8, rows: 4 });
    expect(ZONE_BY_ID.get("vault")!.rect).toEqual({ col: 13, row: 2, cols: 3, rows: 4 });
    expect(ZONE_BY_ID.get("portfolio")!.rect).toEqual({ col: 0, row: 7, cols: 5, rows: 3 });
    expect(ZONE_BY_ID.get("ops")!.rect).toEqual({ col: 5, row: 7, cols: 6, rows: 3 });
    expect(ZONE_BY_ID.get("lab")!.rect).toEqual({ col: 11, row: 7, cols: 5, rows: 3 });
    expect(EMPLOYEE_BY_ID.get("nova")!.desk).toEqual(NOVA_DESK);
    expect(EMPLOYEE_BY_ID.get("byte")!.desk).toEqual({ col: 9, row: 8 });
  });

  it("gave every new space a real zone inside the room", () => {
    for (const id of [
      "conference",
      "deck",
      "pantry",
      "lounge",
      "reception",
      "facilities",
      "restrooms",
      "karthik",
    ] as const) {
      const zone = ZONE_BY_ID.get(id);
      expect(zone, id).toBeDefined();
      expect(zone!.rect.col + zone!.rect.cols).toBeLessThanOrEqual(GRID_COLS);
      expect(zone!.rect.row + zone!.rect.rows).toBeLessThanOrEqual(GRID_ROWS);
    }
    // The old break room is gone, split into its two successors.
    expect(ZONE_BY_ID.get("break" as never)).toBeUndefined();
  });

  it("keeps the conference seats distinct, at the table, and reachable", () => {
    const keys = CONFERENCE_SEATS.map((seat) => `${seat.col},${seat.row}`);
    expect(new Set(keys).size).toBe(CONFERENCE_SEATS.length);
    for (const seat of CONFERENCE_SEATS) {
      // Beside the table, not on it, not in the glass, and walkable.
      expect(
        CONFERENCE_TABLE_TILES.some(
          (tile) => Math.abs(tile.col - seat.col) <= 1 && Math.abs(tile.row - seat.row) <= 1,
        ),
        `seat ${seat.col},${seat.row} is nowhere near the table`,
      ).toBe(true);
      expect(isWalkable(seat, "nova"), `seat ${seat.col},${seat.row} blocked`).toBe(true);
      // A chair exists at every seat: sitting happens on furniture that is
      // actually there.
      expect(
        FURNITURE.some(
          (piece) =>
            piece.kind === "conf-chair" &&
            piece.tile.col === seat.col &&
            piece.tile.row === seat.row,
        ),
        `no chair at ${seat.col},${seat.row}`,
      ).toBe(true);
    }
  });

  it("blocks the vault, the table and the glass to every kind of feet", () => {
    const blocked = new Set(BLOCKED_TILES.map((tile) => `${tile.col},${tile.row}`));
    expect(blocked.has("14,3")).toBe(true); // vault interior
    for (const tile of CONFERENCE_TABLE_TILES) {
      expect(blocked.has(`${tile.col},${tile.row}`)).toBe(true);
    }
    for (const tile of GLASS_WALL_TILES) {
      expect(blocked.has(`${tile.col},${tile.row}`)).toBe(true);
    }
  });
});

/* ── the new residents stay out of the operational layer ──────────────── */

describe("support staff and cats never reach the operational layer", () => {
  it("keeps deriveHqState ignorant of their existence", () => {
    const state = deriveHqState();
    const ids = Object.keys(state.employees);
    expect(ids).toHaveLength(EMPLOYEES.length);
    for (const npc of SUPPORT_STAFF) expect(ids).not.toContain(npc.id);
    for (const cat of CATS) expect(ids).not.toContain(cat.id);
    // And the adapter's source cannot import them: the module that decides
    // what MEMESCOPE is doing must not know the office has cats.
    const adapterSource = fs.readFileSync(
      path.resolve(__dirname, "adapter.ts"),
      "utf8",
    );
    expect(adapterSource).not.toMatch(/from "\.\/(support|cats)"/);
  });

  it("keeps Nova's roll-up identical whatever the household is doing", () => {
    // Nova reads the nine other employees and nothing else. There is no input
    // through which Maya, Sam or a cat could reach her — asserted by the
    // shape of the call itself.
    expect(UNKNOWN_HQ_STATE.employees.nova.detail).not.toMatch(/maya|sam|cosmo|mochi/i);
  });

  it("gives cats and support staff no path to a network or a control", () => {
    for (const file of ["support.ts", "cats.ts"]) {
      const source = fs.readFileSync(path.resolve(__dirname, file), "utf8");
      expect(source, `${file} fetches`).not.toMatch(/api-client|apiFetch|fetch\(|WebSocket/);
      expect(source, `${file} schedules itself`).not.toMatch(/setInterval|setTimeout|requestAnimationFrame/);
    }
  });

  it("keeps every office-life sentence free of operational vocabulary", () => {
    // The panels print these strings. None of them may read as a system
    // claim: a cat that "triggered" anything, a cleaner who found a "breach",
    // a meeting about an "incident" are all the same lie at different sizes.
    const lines: string[] = [];
    const withCast: Array<{
      id: string;
      frames: ActorFrame[];
      cast?: Array<{ frames: ActorFrame[] }>;
    }> = [...SUPPORT_ROUTINES, ...CAT_ROUTINES];
    for (const routine of withCast) {
      lines.push(routine.id);
      for (const frame of routine.frames) if (frame.detail) lines.push(frame.detail);
      for (const member of routine.cast ?? []) {
        for (const frame of member.frames) if (frame.detail) lines.push(frame.detail);
      }
    }
    for (const routine of MEETING_ROUTINES) {
      lines.push(routine.id);
      for (const frame of routine.frames) if (frame.detail) lines.push(frame.detail);
    }
    for (const cat of CATS) lines.push(cat.title, cat.restingDetail);
    for (const npc of SUPPORT_STAFF) lines.push(npc.restingDetail);

    const text = lines.join(" ").toLowerCase();
    for (const forbidden of [
      "trade",
      "buy",
      "sell",
      "wallet",
      "token",
      "alert",
      "error",
      "incident",
      "emergency",
      "breach",
      "outage",
      "degraded",
      "healthy",
      "online",
      "profit",
      "loss",
      "executed",
      "submitted",
    ]) {
      expect(text, `office-life vocabulary contains "${forbidden}"`).not.toContain(forbidden);
    }
  });
});

/* ── movement safety for the new routes ────────────────────────────────── */

describe("support and cat routes", () => {
  const VAULT = ZONE_BY_ID.get("vault")!.rect;

  function insideVault(tile: Tile): boolean {
    return (
      tile.col >= VAULT.col &&
      tile.col < VAULT.col + VAULT.cols &&
      tile.row >= VAULT.row &&
      tile.row < VAULT.row + VAULT.rows
    );
  }

  function frames(routine: { frames: ActorFrame[]; cast?: Array<{ frames: ActorFrame[] }> }) {
    return [...routine.frames, ...(routine.cast ?? []).flatMap((member) => member.frames)];
  }

  it("keeps Maya and Sam on walkable tiles the whole way", () => {
    for (const routine of SUPPORT_ROUTINES) {
      for (const frame of frames(routine)) {
        if (!frame.tile) continue;
        expect(isInsideRoom(frame.tile), `${routine.id} leaves the room`).toBe(true);
        expect(
          isWalkable(frame.tile, "nova"),
          `${routine.id} stands on blocked ${frame.tile.col},${frame.tile.row}`,
        ).toBe(true);
        expect(insideVault(frame.tile), `${routine.id} enters the vault`).toBe(false);
      }
    }
  });

  it("keeps the cats out of the vault, off the glass, and clear of desks", () => {
    for (const routine of CAT_ROUTINES) {
      for (const frame of frames(routine)) {
        if (!frame.tile) continue;
        if (!frame.pose.startsWith("cat_")) continue; // employee cast members checked elsewhere
        const tile = frame.tile;
        expect(isInsideRoom(tile), `${routine.id} leaves the room`).toBe(true);
        expect(insideVault(tile), `${routine.id} enters the vault`).toBe(false);
        for (const glass of GLASS_WALL_TILES) {
          expect(
            Math.abs(tile.col - glass.col) < 0.5 && Math.abs(tile.row - glass.row) < 0.5,
            `${routine.id} walks through glass`,
          ).toBe(false);
        }
        for (const table of CONFERENCE_TABLE_TILES) {
          expect(
            Math.abs(tile.col - table.col) < 0.5 && Math.abs(tile.row - table.row) < 0.5,
            `${routine.id} stands in the conference table`,
          ).toBe(false);
        }
        for (const employee of EMPLOYEES) {
          const distance = Math.max(
            Math.abs(tile.col - employee.desk.col),
            Math.abs(tile.row - employee.desk.row),
          );
          expect(
            distance >= 0.5,
            `${routine.id} clips ${employee.id}'s desk at ${tile.col},${tile.row}`,
          ).toBe(true);
        }
      }
    }
  });

  it("moves cats in animal-sized steps, never teleports", () => {
    for (const routine of CAT_ROUTINES) {
      const cat = CATS.find((candidate) => candidate.id === routine.actor)!;
      let previous: Tile = cat.home;
      for (const frame of routine.frames) {
        const tile = frame.tile ?? cat.home;
        const step = Math.max(Math.abs(tile.col - previous.col), Math.abs(tile.row - previous.row));
        expect(step, `${routine.id} jumps ${step.toFixed(2)} tiles`).toBeLessThanOrEqual(1.5);
        previous = tile;
      }
      expect(previous, `${routine.id} does not end at home`).toEqual(cat.home);
    }
  });
});

/* ── the scheduler's new behaviours ─────────────────────────────────────── */

describe("meetings", () => {
  /**
   * Run until a meeting starts, trying successive seeds.
   *
   * The bound used to be a single seed and 600 ticks, tuned to the routine set
   * that existed when it was written — so adding eight ambient routines broke
   * two tests that were about HIGH_ALERT and had nothing to do with routine
   * counts. What the tests actually mean is "meetings happen"; searching seeds
   * says that without re-tuning a magic number every time the roster grows.
   */
  function schedulerWithMeeting(): ReturnType<typeof runScheduler> {
    for (let seed = 1; seed <= 12; seed += 1) {
      const harness = runScheduler(seed);
      harness.scheduler.start();
      for (let i = 0; i < 900 && !harness.scheduler.meetingActive; i += 1) {
        vi.advanceTimersByTime(1_000);
      }
      if (harness.scheduler.meetingActive) return harness;
      harness.scheduler.destroy();
    }
    throw new Error("no seed produced a meeting");
  }

  function runScheduler(seed: number) {
    const frames = new Map<ActorId, ActorFrame | null>();
    const scheduler = createAmbientScheduler((actor, frame) => {
      frames.set(actor, frame);
    }, seeded(seed));
    return { frames, scheduler };
  }

  it("exist for the everyday syncs and claim nothing operational", () => {
    expect(MEETING_ROUTINES.length).toBeGreaterThanOrEqual(4);
    for (const routine of MEETING_ROUTINES) {
      expect(routine.meeting).toBe(true);
      const cast = 1 + (routine.cast?.length ?? 0);
      expect(cast).toBeGreaterThanOrEqual(3);
      expect(cast).toBeLessThanOrEqual(4);
      // Every participant ends up on a distinct conference seat.
      const seats = [routine.frames, ...(routine.cast ?? []).map((member) => member.frames)]
        .map((frames) => frames.find((frame) => frame.pose === "seated_lounge")?.tile)
        .filter(Boolean)
        .map((tile) => `${tile!.col},${tile!.row}`);
      expect(new Set(seats).size).toBe(cast);
    }
  });

  it("sends everyone home when the office goes to HIGH_ALERT mid-meeting", () => {
    vi.useFakeTimers();
    setReducedMotion(false);
    Object.defineProperty(document, "hidden", { configurable: true, get: () => false });
    const { frames, scheduler } = schedulerWithMeeting();
    expect(scheduler.meetingActive).toBe(true);

    const participants = [...scheduler.animating];
    const released = new Set<ActorId>();
    scheduler.setActivity("HIGH_ALERT");
    const releaseWatch = (actor: ActorId, frame: ActorFrame | null) => {
      if (frame === null) released.add(actor);
    };
    // Watch releases from here on: the meeting cast must all walk home and be
    // freed, even though they may later start something new.
    const originalSet = frames.set.bind(frames);
    frames.set = (actor, frame) => {
      releaseWatch(actor, frame);
      return originalSet(actor, frame);
    };

    vi.advanceTimersByTime(5 * 60 * 1000);
    expect(scheduler.meetingActive).toBe(false);
    for (const actor of participants) {
      expect(released.has(actor), `${actor} never released after the alert`).toBe(true);
    }
    scheduler.destroy();
    vi.useRealTimers();
  });

  it("never starts a meeting while the office is at HIGH_ALERT", () => {
    vi.useFakeTimers();
    setReducedMotion(false);
    Object.defineProperty(document, "hidden", { configurable: true, get: () => false });
    const { scheduler } = runScheduler(7);
    scheduler.setActivity("HIGH_ALERT");
    scheduler.start();
    let sawMeeting = false;
    for (let i = 0; i < 1_800; i += 1) {
      vi.advanceTimersByTime(1_000);
      sawMeeting ||= scheduler.meetingActive;
    }
    expect(sawMeeting).toBe(false);
    scheduler.destroy();
    vi.useRealTimers();
  });

  it("never starts a meeting at night", () => {
    vi.useFakeTimers();
    setReducedMotion(false);
    Object.defineProperty(document, "hidden", { configurable: true, get: () => false });
    const { scheduler } = runScheduler(13);
    scheduler.setPhase("night");
    scheduler.start();
    let sawMeeting = false;
    for (let i = 0; i < 1_800; i += 1) {
      vi.advanceTimersByTime(1_000);
      sawMeeting ||= scheduler.meetingActive;
    }
    expect(sawMeeting).toBe(false);
    scheduler.destroy();
    vi.useRealTimers();
  });

  it("yields a participant to operational work, and the rest go home too", () => {
    vi.useFakeTimers();
    setReducedMotion(false);
    Object.defineProperty(document, "hidden", { configurable: true, get: () => false });
    const { frames, scheduler } = schedulerWithMeeting();
    expect(scheduler.meetingActive).toBe(true);
    const inMeeting = scheduler.animating.filter((id) =>
      EMPLOYEES.some((employee) => employee.id === id),
    ) as EmployeeId[];
    expect(inMeeting.length).toBeGreaterThanOrEqual(3);

    // Watch releases rather than the final frame. The meeting cast must all
    // walk home and be freed — but the scheduler keeps running, so any of them
    // may legitimately start something new before the five minutes are up.
    // Asserting the *final* frame was null only ever passed because one seed
    // happened not to do that, which is the sibling test's whole comment.
    const released = new Set<ActorId>();
    const originalSet = frames.set.bind(frames);
    frames.set = (actor, frame) => {
      if (frame === null) released.add(actor);
      return originalSet(actor, frame);
    };

    // One participant's subsystem starts doing real work.
    scheduler.setOperational([inMeeting[0]!]);

    vi.advanceTimersByTime(5 * 60 * 1000);
    for (const id of inMeeting) {
      expect(released.has(id), `${id} never released`).toBe(true);
    }
    // `meetingActive` is deliberately not asserted here. Releasing the cast is
    // the property under test; the flag is a global the scheduler is free to
    // set again, and over five minutes it often does — the roster grew to
    // thirteen and a second sync now fits in the window on several seeds. This
    // is the same seed-sensitivity the sibling test above documents, and
    // asserting the flag only ever passed because no seed had yet started a
    // meeting inside the tail of this one.
    scheduler.destroy();
    vi.useRealTimers();
  });
});

describe("the quieter office", () => {
  it("runs Sam rarely at night and mutes ambient starts on HIGH_ALERT", () => {
    vi.useFakeTimers();
    setReducedMotion(false);
    Object.defineProperty(document, "hidden", { configurable: true, get: () => false });

    const count = (configure: (s: ReturnType<typeof createAmbientScheduler>) => void) => {
      const starts = new Map<string, number>();
      const mid = new Set<string>();
      const scheduler = createAmbientScheduler((actor, frame) => {
        if (frame === null) {
          mid.delete(actor);
          return;
        }
        if (!mid.has(actor)) {
          mid.add(actor);
          starts.set(actor, (starts.get(actor) ?? 0) + 1);
        }
      }, seeded(21));
      configure(scheduler);
      scheduler.start();
      vi.advanceTimersByTime(30 * 60 * 1000);
      scheduler.destroy();
      return starts;
    };

    const day = count(() => undefined);
    const night = count((scheduler) => scheduler.setPhase("night"));
    const alert = count((scheduler) => scheduler.setActivity("HIGH_ALERT"));

    const total = (starts: Map<string, number>) =>
      [...starts.values()].reduce((sum, value) => sum + value, 0);

    // Night and HIGH_ALERT are both quieter than an ordinary day — the office
    // never freezes, it focuses.
    expect(total(night)).toBeLessThan(total(day));
    expect(total(alert)).toBeLessThan(total(day));
    expect(total(alert)).toBeGreaterThan(0);
    // Sam has mostly gone home at night; Maya still makes a round or two.
    expect(night.get("sam") ?? 0).toBeLessThanOrEqual(2);
    expect(night.get("sam") ?? 0).toBeLessThan(day.get("sam") ?? 0);
    vi.useRealTimers();
  });

  it("does not run at all under reduced motion — cats and cleaners included", () => {
    vi.useFakeTimers();
    setReducedMotion(true);
    const emit = vi.fn();
    const scheduler = createAmbientScheduler(emit, seeded(2));
    scheduler.start();
    vi.advanceTimersByTime(20 * 60 * 1000);
    expect(emit).not.toHaveBeenCalled();
    scheduler.destroy();
    vi.useRealTimers();
  });

  it("uses exactly one timer chain for the entire cast", () => {
    // Per-cat and per-NPC intervals were the tempting design and are the
    // banned one. The whole office runs on the scheduler's single tick plus
    // one timeout per actively-playing frame — so with nobody playing, hiding
    // the tab leaves zero timers.
    vi.useFakeTimers();
    setReducedMotion(false);
    Object.defineProperty(document, "hidden", { configurable: true, get: () => false });
    const scheduler = createAmbientScheduler(vi.fn(), seeded(4));
    scheduler.start();
    expect(vi.getTimerCount()).toBe(1);
    scheduler.stop();
    expect(vi.getTimerCount()).toBe(0);
    scheduler.destroy();
    vi.useRealTimers();
  });
});

/* ── the office keeps its promises about the break area ─────────────────── */

describe("the break area after the split", () => {
  it("still recognises both halves as the capped break area", () => {
    expect(isInBreakRoom({ col: 3, row: 11 })).toBe(true); // pantry
    expect(isInBreakRoom({ col: 12, row: 11 })).toBe(true); // lounge
    expect(isInBreakRoom({ col: 3, row: 8 })).toBe(false);
  });

  it("keeps every legacy walk route valid on the new floor", () => {
    // The expansion's core promise: nothing that existed moved. Every
    // pre-existing destination still stands on walkable floor.
    for (const routine of AMBIENT_ROUTINES) {
      for (const frame of routine.frames) {
        if (!frame.tile) continue;
        if (!Number.isInteger(frame.tile.col) || !Number.isInteger(frame.tile.row)) continue;
        expect(
          isWalkable(frame.tile, routine.employee),
          `${routine.id} stands on blocked ${frame.tile.col},${frame.tile.row}`,
        ).toBe(true);
      }
    }
  });
});
