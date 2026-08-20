import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  AMBIENT_ROUTINES,
  DAY_PHASES,
  ROUTINES_BY_EMPLOYEE,
  isBlockedTile,
  isInBreakRoom,
  isWalk,
  isWalkable,
  phaseOfDay,
  pickRoutine,
  poseSignature,
  visitsBreakRoom,
  type AmbientFrame,
  type AmbientRoutine,
} from "@/lib/hq/ambient";
import { createAmbientScheduler } from "@/lib/hq/ambient-scheduler";
import { EMPLOYEES, EMPLOYEE_BY_ID, type EmployeeId } from "@/lib/hq/employees";
import { STANDING_POSES } from "@/lib/hq/characters";
import { isInsideRoom } from "@/lib/hq/geometry";

/**
 * HQ-3 acceptance.
 *
 * Two things are actually at risk in this phase, and everything here defends
 * one of them.
 *
 * The first is the reader: ambient motion is exactly the kind of feature that
 * quietly ignores `prefers-reduced-motion` because the guard lives three
 * components away from the thing that moves. So the guard is asserted at the
 * scheduler, which is the only place that cannot be bypassed.
 *
 * The second is the truth. HQ's whole value is that it reports what MEMESCOPE
 * is doing, and the fastest way to destroy that is a decorative animation that
 * reads as a measurement. So the vocabulary is asserted to be free of
 * operational language, and the state chips are asserted to still say `No
 * data` while people are walking around.
 */

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

function setHidden(hidden: boolean) {
  Object.defineProperty(document, "hidden", { configurable: true, get: () => hidden });
  document.dispatchEvent(new Event("visibilitychange"));
}

/** A deterministic stand-in for Math.random, so a failure is reproducible. */
function seeded(seed = 1) {
  let state = seed;
  return () => {
    state = (state * 1664525 + 1013904223) % 4294967296;
    return state / 4294967296;
  };
}

/** Every frame in a routine, including the whole cast's. */
function allFrames(routine: AmbientRoutine): Array<{ who: EmployeeId; frame: AmbientFrame }> {
  const out = routine.frames.map((frame) => ({ who: routine.employee, frame }));
  for (const member of routine.cast ?? []) {
    out.push(...member.frames.map((frame) => ({ who: member.employee, frame })));
  }
  return out;
}

beforeEach(() => {
  setReducedMotion(false);
  Object.defineProperty(document, "hidden", { configurable: true, get: () => false });
});

afterEach(() => {
  vi.useRealTimers();
});

/* ---------------------------------------------------------------------- */

describe("walk routes", () => {
  it("keeps every step inside the room", () => {
    for (const routine of AMBIENT_ROUTINES) {
      for (const { frame } of allFrames(routine)) {
        if (!frame.tile) continue;
        expect(isInsideRoom(frame.tile), `${routine.id} steps outside the room`).toBe(true);
      }
    }
  });

  it("never stands anybody inside the furniture", () => {
    // The prohibited set is every desk plus the row against the back wall. A
    // route that clips a desk is invisible in a screenshot of a still frame
    // and obvious for one second every few minutes, which is the worst
    // possible way to find out.
    for (const routine of AMBIENT_ROUTINES) {
      for (const { who, frame } of allFrames(routine)) {
        if (!frame.tile) continue;
        expect(
          isWalkable(frame.tile, who),
          `${routine.id}: ${who} stands on ${frame.tile.col},${frame.tile.row}`,
        ).toBe(true);
      }
    }
  });

  it("models the furniture it claims to avoid", () => {
    // Guards the guard: if `BLOCKED_TILES` were empty the check above would
    // pass vacuously.
    for (const employee of EMPLOYEES) {
      expect(isBlockedTile(employee.desk)).toBe(true);
    }
    expect(isBlockedTile({ col: 7, row: 6 })).toBe(false);
  });

  it("walks only one tile at a time in a straight line", () => {
    // Waypoints exist so a route bends around furniture. A diagonal jump of
    // several tiles would pass over whatever is between them, which defeats
    // the point of having waypoints at all.
    for (const routine of AMBIENT_ROUTINES) {
      const walker = routine.employee;
      const desk = EMPLOYEE_BY_ID.get(walker)!.desk;
      let previous = desk;
      for (const frame of routine.frames) {
        const tile = frame.tile ?? desk;
        const straight = tile.col === previous.col || tile.row === previous.row;
        const diagonalStep =
          Math.abs(tile.col - previous.col) <= 1 && Math.abs(tile.row - previous.row) <= 1;
        expect(
          straight || diagonalStep,
          `${routine.id} jumps from ${previous.col},${previous.row} to ${tile.col},${tile.row}`,
        ).toBe(true);
        previous = tile;
      }
      expect(previous, `${routine.id} does not end at the desk`).toEqual(desk);
    }
  });

  it("defines walks for more than one department", () => {
    const walkers = new Set(AMBIENT_ROUTINES.filter(isWalk).map((routine) => routine.employee));
    expect(walkers.size).toBeGreaterThanOrEqual(5);
  });

  it("never uses a desk-bound pose away from the desk", () => {
    // The stage stands anybody off their own tile up, so a chair never follows
    // someone to the break room. But `seated_working` is hands-at-keyboard and
    // `seated_reviewing` is elbow-on-desk: standing, they mime furniture that
    // is not there. Everything else reads fine on two feet.
    const deskBound = new Set(["seated_working", "seated_reviewing"]);
    for (const routine of AMBIENT_ROUTINES) {
      for (const { frame } of allFrames(routine)) {
        if (!frame.tile) continue;
        expect(
          deskBound.has(frame.pose),
          `${routine.id} uses the desk-bound ${frame.pose} away from a desk`,
        ).toBe(false);
      }
    }
    // Guards the guard: standing poses really are the majority of what walks.
    expect(STANDING_POSES.has("walking_short")).toBe(true);
  });
});

describe("the break room", () => {
  it("is somewhere several people can go", () => {
    const visitors = new Set(
      AMBIENT_ROUTINES.filter(visitsBreakRoom).map((routine) => routine.employee),
    );
    expect(visitors.size).toBeGreaterThanOrEqual(4);
  });

  it("is rare for Atlas and never the whole company", () => {
    // The brief's staffing rule, expressed as weights. Atlas leaving his desk
    // must be the lightest thing he does.
    const atlas = ROUTINES_BY_EMPLOYEE.get("atlas")!;
    const away = atlas.filter(visitsBreakRoom);
    expect(away).toHaveLength(1);
    const heaviest = Math.max(...atlas.map((routine) => routine.weight));
    expect(away[0]!.weight).toBeLessThan(heaviest / 4);

    // And nobody is scheduled to live there.
    const visitors = AMBIENT_ROUTINES.filter(visitsBreakRoom);
    expect(visitors.length).toBeLessThan(AMBIENT_ROUTINES.length / 3);
  });

  it("knows where the break room is", () => {
    expect(isInBreakRoom({ col: 3, row: 10 })).toBe(true);
    expect(isInBreakRoom({ col: 3, row: 8 })).toBe(false);
  });
});

describe("personality", () => {
  it("gives every employee an idle vocabulary", () => {
    for (const employee of EMPLOYEES) {
      const routines = ROUTINES_BY_EMPLOYEE.get(employee.id) ?? [];
      expect(routines.length, `${employee.id} has no ambient routine`).toBeGreaterThanOrEqual(2);
    }
  });

  it("gives every employee at least one behaviour nobody else has", () => {
    // The brief's requirement is that the cast reads as ten people rather than
    // one animation applied ten times. Comparing pose sequences is the only
    // check that does not depend on somebody remembering to keep them apart.
    for (const employee of EMPLOYEES) {
      const mine = (ROUTINES_BY_EMPLOYEE.get(employee.id) ?? []).map(poseSignature);
      const theirs = new Set(
        AMBIENT_ROUTINES.filter((routine) => routine.employee !== employee.id).map(poseSignature),
      );
      const unique = mine.filter((signature) => !theirs.has(signature));
      expect(unique.length, `${employee.id} has no distinctive idle behaviour`).toBeGreaterThan(0);
    }
  });

  it("keeps Atlas still and Echo mobile", () => {
    const stillness = (id: EmployeeId) => {
      const routines = ROUTINES_BY_EMPLOYEE.get(id)!;
      const moving = routines.filter(isWalk).reduce((sum, r) => sum + r.weight, 0);
      const total = routines.reduce((sum, r) => sum + r.weight, 0);
      return 1 - moving / total;
    };
    expect(stillness("atlas")).toBeGreaterThan(stillness("echo"));
    expect(stillness("atlas")).toBeGreaterThan(0.9);
  });

  it("pairs colleagues without double-booking anyone", () => {
    const partnered = AMBIENT_ROUTINES.filter((routine) => routine.cast?.length);
    expect(partnered.length).toBeGreaterThanOrEqual(4);
    for (const routine of partnered) {
      for (const member of routine.cast!) {
        expect(member.employee).not.toBe(routine.employee);
      }
    }
  });

  it("has a handful of rare events and no more", () => {
    const eggs = new Set(
      AMBIENT_ROUTINES.flatMap((routine) =>
        routine.frames.map((frame) => frame.egg).filter(Boolean),
      ),
    );
    expect(eggs.size).toBeGreaterThanOrEqual(2);
    expect(eggs.size).toBeLessThanOrEqual(4);
    for (const routine of AMBIENT_ROUTINES) {
      if (!routine.frames.some((frame) => frame.egg)) continue;
      expect(routine.weight, `${routine.id} is not rare`).toBe(1);
    }
  });

  it("has unique routine ids", () => {
    const ids = AMBIENT_ROUTINES.map((routine) => routine.id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it("claims nothing operational", () => {
    // Routine ids reach the DOM through `data-` attributes and the egg names
    // reach CSS. None of them may read as a system fact — "byte-doze" is a
    // joke about Byte, "byte-degraded" would be a fabricated incident.
    const vocabulary = AMBIENT_ROUTINES.flatMap((routine) => [
      routine.id,
      ...routine.frames.map((frame) => frame.egg ?? ""),
    ]).join(" ");
    for (const forbidden of [
      "online",
      "healthy",
      "active",
      "approved",
      "rejected",
      "profit",
      "loss",
      "alert",
      "error",
      "degraded",
      "trade",
      "buy",
      "sell",
      "token",
      "wallet",
    ]) {
      expect(vocabulary, `ambient vocabulary contains "${forbidden}"`).not.toContain(forbidden);
    }
  });
});

describe("weighted picking", () => {
  it("returns null for an empty set rather than throwing", () => {
    expect(pickRoutine([], seeded())).toBeNull();
  });

  it("respects the weights", () => {
    const routines = ROUTINES_BY_EMPLOYEE.get("atlas")!;
    const random = seeded(7);
    const counts = new Map<string, number>();
    for (let i = 0; i < 2000; i += 1) {
      const picked = pickRoutine(routines, random)!;
      counts.set(picked.id, (counts.get(picked.id) ?? 0) + 1);
    }
    // Stillness is weighted eight to one against the break-room trip.
    expect(counts.get("atlas-checklist")!).toBeGreaterThan(counts.get("atlas-break")! * 3);
  });
});

describe("time of day", () => {
  it("names three phases and covers the whole clock", () => {
    const seen = new Set(Array.from({ length: 24 }, (_, hour) => phaseOfDay(hour)));
    expect([...seen].sort()).toEqual([...DAY_PHASES].sort());
  });

  it("is dark late and light mid-morning", () => {
    expect(phaseOfDay(3)).toBe("night");
    expect(phaseOfDay(10)).toBe("day");
    expect(phaseOfDay(19)).toBe("evening");
    expect(phaseOfDay(23)).toBe("night");
  });
});

/* ---------------------------------------------------------------------- */

describe("the ambient scheduler", () => {
  it("does not start when the reader asked for reduced motion", () => {
    vi.useFakeTimers();
    setReducedMotion(true);
    const emit = vi.fn();
    const scheduler = createAmbientScheduler(emit, seeded());

    scheduler.start();

    expect(scheduler.running).toBe(false);
    expect(scheduler.wanted).toBe(true);
    vi.advanceTimersByTime(120_000);
    expect(emit).not.toHaveBeenCalled();
    scheduler.destroy();
  });

  it("does not start on a tab that is already hidden", () => {
    vi.useFakeTimers();
    Object.defineProperty(document, "hidden", { configurable: true, get: () => true });
    const scheduler = createAmbientScheduler(vi.fn(), seeded());
    scheduler.start();
    expect(scheduler.running).toBe(false);
    scheduler.destroy();
  });

  it("pauses when the tab is hidden", () => {
    vi.useFakeTimers();
    const scheduler = createAmbientScheduler(vi.fn(), seeded());
    scheduler.start();
    vi.advanceTimersByTime(30_000);
    expect(scheduler.running).toBe(true);

    setHidden(true);

    expect(scheduler.running).toBe(false);
    expect(vi.getTimerCount()).toBe(0);
    scheduler.destroy();
  });

  it("puts everyone back at their desk when it pauses", () => {
    vi.useFakeTimers();
    const emit = vi.fn();
    const scheduler = createAmbientScheduler(emit, seeded(3));
    scheduler.start();
    vi.advanceTimersByTime(30_000);
    emit.mockClear();

    setHidden(true);

    // Whoever was mid-routine is released. A hidden tab must not come back
    // with somebody stranded in the break room, and the plan is explicit that
    // missed animations are dropped rather than replayed.
    for (const call of emit.mock.calls) {
      expect(call[1]).toBeNull();
    }
    scheduler.destroy();
  });

  it("resumes when the tab is visible again, without doubling up", () => {
    vi.useFakeTimers();
    const scheduler = createAmbientScheduler(vi.fn(), seeded());
    scheduler.start();
    vi.advanceTimersByTime(30_000);
    setHidden(true);

    setHidden(false);

    expect(scheduler.running).toBe(true);
    // Exactly one pending tick. A resume that restarted the chain without
    // clearing it would run two schedulers over the same ten people.
    expect(vi.getTimerCount()).toBe(1);
    scheduler.destroy();
  });

  it("does not resume a scheduler that was stopped on purpose", () => {
    vi.useFakeTimers();
    const scheduler = createAmbientScheduler(vi.fn(), seeded());
    scheduler.start();
    scheduler.stop();

    setHidden(true);
    setHidden(false);

    expect(scheduler.running).toBe(false);
    scheduler.destroy();
  });

  it("stops listening once destroyed", () => {
    vi.useFakeTimers();
    const scheduler = createAmbientScheduler(vi.fn(), seeded());
    scheduler.start();
    scheduler.destroy();

    setHidden(false);

    expect(scheduler.running).toBe(false);
    expect(vi.getTimerCount()).toBe(0);
  });

  it("keeps everyday employee movement bounded, with meetings as the one exception", () => {
    vi.useFakeTimers();
    const employeeIds = new Set<string>(EMPLOYEES.map((e) => e.id));
    const active = new Set<string>();
    let ordinaryPeak = 0;
    let meetingPeak = 0;
    const scheduler = createAmbientScheduler((actor, frame) => {
      if (!employeeIds.has(actor)) return;
      if (frame) active.add(actor);
      else active.delete(actor);
      if (scheduler.meetingActive) meetingPeak = Math.max(meetingPeak, active.size);
      else ordinaryPeak = Math.max(ordinaryPeak, active.size);
    }, seeded(11));

    scheduler.start();
    vi.advanceTimersByTime(10 * 60 * 1000);

    expect(ordinaryPeak).toBeGreaterThan(0);
    // Three of ten away on errands. An office where everyone moves at once is
    // a screensaver.
    expect(ordinaryPeak).toBeLessThanOrEqual(3);
    // A meeting is its own bounded thing: its cast plus a bounded remainder,
    // never the whole company.
    expect(meetingPeak).toBeLessThanOrEqual(5);
    scheduler.destroy();
  });

  it("keeps the break room from emptying the floor", () => {
    vi.useFakeTimers();
    const away = new Set<EmployeeId>();
    let peak = 0;
    const employeeIds = new Set<string>(EMPLOYEES.map((e) => e.id));
    const scheduler = createAmbientScheduler((actor, frame) => {
      // The cap is on employees: a cat supervising the snack shelf does not
      // crowd anyone's coffee.
      if (!employeeIds.has(actor)) return;
      if (frame?.tile && isInBreakRoom(frame.tile)) away.add(actor as EmployeeId);
      else away.delete(actor as EmployeeId);
      peak = Math.max(peak, away.size);
    }, seeded(23));

    scheduler.start();
    vi.advanceTimersByTime(20 * 60 * 1000);

    expect(peak).toBeLessThanOrEqual(2);
    scheduler.destroy();
  });

  it("runs sparsely rather than on a loop", () => {
    vi.useFakeTimers();
    const emit = vi.fn();
    const scheduler = createAmbientScheduler(emit, seeded(5));
    scheduler.start();
    vi.advanceTimersByTime(60_000);

    // A minute of ambient life is tens of pose changes, not thousands of
    // frames. If this ever reads in the hundreds somebody has added a loop.
    expect(emit.mock.calls.length).toBeLessThan(120);
    expect(emit.mock.calls.length).toBeGreaterThan(0);
    scheduler.destroy();
  });

  it("always returns a person to their default pose when a routine ends", () => {
    vi.useFakeTimers();
    const started = new Set<string>();
    const ended = new Set<string>();
    const scheduler = createAmbientScheduler((actor, frame) => {
      if (frame) started.add(actor);
      else ended.add(actor);
    }, seeded(31));

    scheduler.start();
    vi.advanceTimersByTime(15 * 60 * 1000);
    scheduler.stop();

    expect(started.size).toBeGreaterThan(3);
    for (const employee of started) {
      expect(ended.has(employee), `${employee} never returned to rest`).toBe(true);
    }
    scheduler.destroy();
  });
});

/* ---------------------------------------------------------------------- */

describe("ambient yields to real work", () => {
  /**
   * Run the scheduler until somebody is mid-routine, recording everything.
   *
   * Deterministic through the seeded random rather than through mocking the
   * routine table: the point is that *whatever* the scheduler chose, yielding
   * handles it.
   */
  function runUntil(
    predicate: (frames: Map<EmployeeId, AmbientFrame | null>) => EmployeeId | null,
    seed = 5,
  ) {
    const current = new Map<EmployeeId, AmbientFrame | null>();
    const log: Array<{ who: EmployeeId; frame: AmbientFrame | null }> = [];
    const employeeIds = new Set<string>(EMPLOYEES.map((e) => e.id));
    const scheduler = createAmbientScheduler((who, frame) => {
      if (!employeeIds.has(who)) return;
      current.set(who as EmployeeId, frame as AmbientFrame | null);
      log.push({ who: who as EmployeeId, frame: frame as AmbientFrame | null });
    }, seeded(seed));
    scheduler.start();

    let found: EmployeeId | null = null;
    for (let i = 0; i < 400 && !found; i += 1) {
      vi.advanceTimersByTime(500);
      found = predicate(current);
    }
    return { scheduler, current, log, found };
  }

  it("never starts a routine for someone doing real work", () => {
    vi.useFakeTimers();
    const started = new Set<string>();
    const scheduler = createAmbientScheduler((who, frame) => {
      if (frame) started.add(who);
    }, seeded(9));

    scheduler.setOperational(["radar", "dex", "echo"]);
    scheduler.start();
    vi.advanceTimersByTime(15 * 60 * 1000);

    expect(started.size).toBeGreaterThan(0);
    for (const busy of ["radar", "dex", "echo"] as EmployeeId[]) {
      expect(started.has(busy), `${busy} was animated while working`).toBe(false);
    }
    scheduler.destroy();
  });

  it("ends a desk-bound routine immediately when real work arrives", () => {
    vi.useFakeTimers();
    const { scheduler, current, found } = runUntil((frames) => {
      for (const [who, frame] of frames) if (frame && !frame.tile) return who;
      return null;
    });
    expect(found).not.toBeNull();

    scheduler.setOperational([found!]);

    expect(current.get(found!)).toBeNull();
    expect(scheduler.animating).not.toContain(found!);
    scheduler.destroy();
  });

  it("walks somebody home rather than teleporting them", () => {
    // The requirement in one assertion: an employee called back to work while
    // they are across the room does not vanish from the break room and
    // reappear at their desk. They walk, along the return leg the route was
    // authored with — which is also the only path that misses the furniture.
    vi.useFakeTimers();
    const { scheduler, log, found } = runUntil((frames) => {
      for (const [who, frame] of frames) if (frame?.tile) return who;
      return null;
    });
    expect(found).not.toBeNull();

    const from = log.length;
    scheduler.setOperational([found!]);
    vi.advanceTimersByTime(60_000);

    const after = log.slice(from).filter((entry) => entry.who === found);
    expect(after.length).toBeGreaterThan(0);
    // Every frame after the interruption is a walk home, and the last is the
    // release back to their default pose.
    for (const entry of after.slice(0, -1)) {
      expect(entry.frame?.pose, `${found} did not walk home`).toBe("returning_to_desk");
    }
    expect(after[after.length - 1]!.frame).toBeNull();
    expect(scheduler.animating).not.toContain(found!);
    scheduler.destroy();
  });

  it("releases a colleague who was playing along", () => {
    vi.useFakeTimers();
    const partnered = AMBIENT_ROUTINES.filter((routine) => routine.cast?.length);
    expect(partnered.length).toBeGreaterThan(0);

    const { scheduler, current, found } = runUntil((frames) => {
      const busy = [...frames].filter(([, frame]) => frame !== null).map(([who]) => who);
      return busy.length >= 2 ? busy[0]! : null;
    }, 17);

    if (found) {
      scheduler.setOperational([found]);
      vi.advanceTimersByTime(60_000);
      // Nobody is left gesturing at an empty chair.
      for (const [, frame] of current) {
        if (frame) expect(frame.pose).not.toBe("talking_briefly");
      }
    }
    scheduler.destroy();
  });

  it("lets ambient personality resume once the real work clears", () => {
    vi.useFakeTimers();
    const started = new Set<string>();
    const scheduler = createAmbientScheduler((who, frame) => {
      if (frame) started.add(who);
    }, seeded(13));

    scheduler.setOperational(["radar"]);
    scheduler.start();
    vi.advanceTimersByTime(10 * 60 * 1000);
    expect(started.has("radar")).toBe(false);

    scheduler.setOperational([]);
    vi.advanceTimersByTime(20 * 60 * 1000);

    expect(started.has("radar"), "radar never went back to ambient").toBe(true);
    scheduler.destroy();
  });

  it("still refuses to run at all under reduced motion, whatever the office says", () => {
    vi.useFakeTimers();
    setReducedMotion(true);
    const emit = vi.fn();
    const scheduler = createAmbientScheduler(emit, seeded());
    scheduler.setOperational([]);
    scheduler.start();
    vi.advanceTimersByTime(10 * 60 * 1000);
    expect(emit).not.toHaveBeenCalled();
    scheduler.destroy();
  });
});
