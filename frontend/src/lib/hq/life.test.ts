import { describe, expect, it } from "vitest";

import { deriveHqState, type HqState } from "./adapter";
import {
  AMBIENT_ROUTINES,
  GAME_ROUTINES,
  SOCIAL_ROUTINES,
  isWalkable,
  ROUTINES_BY_EMPLOYEE,
} from "./ambient";
import { NEGATIVE_EMOTIONS, type Emotion } from "./characters";
import { EMPLOYEE_BY_ID, type EmployeeId } from "./employees";
import { FURNITURE } from "./furniture";
import { ideasFrom } from "./ideas";

/**
 * THE GAMES CORNER, THE FEELINGS, AND THE IDEAS BOARD.
 *
 * Three features that each add a way for the room to say something. The tests
 * that matter are the ones that stop any of them saying something untrue.
 */

const socialIds = new Set([...GAME_ROUTINES, ...SOCIAL_ROUTINES].map((r) => r.id));

function allFrames(routine: (typeof AMBIENT_ROUTINES)[number]) {
  return [...routine.frames, ...(routine.cast ?? []).flatMap((m) => m.frames)];
}

/* ── the rule everything here lives under ─────────────────────────────── */

describe("an emotion is about a person, never about MEMESCOPE", () => {
  /**
   * The headline check.
   *
   * Ambient routines fire on a timer. An angry face scheduled by a clock is
   * exactly as unfounded as a chatter line claiming the queue is deep — so the
   * negative emotions are confined to routines that *motivate* them in their
   * own timeline: losing a frame of pool, being disagreed with. Anywhere else,
   * a reader would have to invent the reason, and the reason they would invent
   * is "something is wrong with the system".
   */
  it("keeps anger and sadness inside the routines that explain them", () => {
    for (const routine of AMBIENT_ROUTINES) {
      if (socialIds.has(routine.id)) continue;
      for (const frame of allFrames(routine)) {
        const emotion = frame.emotion as Emotion | undefined;
        if (!emotion) continue;
        expect(
          NEGATIVE_EMOTIONS.has(emotion),
          `${routine.id} carries ${emotion} with nothing in the routine to explain it`,
        ).toBe(false);
      }
    }
  });

  it("says nothing about the system in any social line or detail", () => {
    // Same ban the chatter lines live under, applied to the new speech. A
    // match is a person; a queue, a wallet or a token is a claim.
    const forbidden =
      /\b(queue|wallet|token|position|trade|target|equity|profit|loss|score|worker|disk|redis|deploy|lab)\b/i;
    for (const routine of [...GAME_ROUTINES, ...SOCIAL_ROUTINES]) {
      for (const frame of allFrames(routine)) {
        for (const text of [frame.detail, frame.speech]) {
          if (!text) continue;
          expect(forbidden.test(text), `${routine.id}: "${text}"`).toBe(false);
        }
      }
    }
  });

  it("never leaves anybody frozen mid-argument", () => {
    // Every routine that reaches a negative emotion must resolve: the last
    // frame of every timeline in it is neutral or better. A character left
    // scowling at their desk for the rest of the session would become exactly
    // the ambient claim this whole file is guarding against.
    for (const routine of SOCIAL_ROUTINES) {
      const timelines = [routine.frames, ...(routine.cast ?? []).map((m) => m.frames)];
      for (const frames of timelines) {
        const last = frames[frames.length - 1]!;
        const emotion = (last.emotion ?? "neutral") as Emotion;
        expect(
          NEGATIVE_EMOTIONS.has(emotion),
          `${routine.id} ends on ${emotion}`,
        ).toBe(false);
      }
    }
  });

  it("suppresses every argument while the office is actually in trouble", () => {
    // An argument during a real incident is the coincidence that reads as
    // causation. The one routine where two people are angry at each other must
    // never be able to play over the top of a genuine alert.
    const argument = SOCIAL_ROUTINES.find((r) => r.id === "rex-atlas-disagree")!;
    expect(argument.suppressOnAlert).toBe(true);
  });
});

/* ── the games ────────────────────────────────────────────────────────── */

describe("the games corner", () => {
  it("has a table for each game, and players standing at both ends", () => {
    const kinds = FURNITURE.map((piece) => piece.kind);
    expect(kinds).toContain("pool-table");
    expect(kinds).toContain("foosball-table");

    for (const routine of GAME_ROUTINES) {
      const timelines = [routine.frames, ...(routine.cast ?? []).map((m) => m.frames)];
      for (const frames of timelines) {
        const playing = frames.filter(
          (f) => f.pose === "cue_shot" || f.pose === "playing_table",
        );
        expect(playing.length, `${routine.id} has a timeline that never plays`).toBeGreaterThan(0);
      }
    }
  });

  it("walks every player there on real floor, one tile at a time", () => {
    for (const routine of GAME_ROUTINES) {
      const casts: Array<[EmployeeId, typeof routine.frames]> = [
        [routine.employee, routine.frames],
        ...(routine.cast ?? []).map(
          (m) => [m.employee, m.frames] as [EmployeeId, typeof routine.frames],
        ),
      ];
      for (const [who, frames] of casts) {
        let previous = EMPLOYEE_BY_ID.get(who)!.desk;
        for (const frame of frames) {
          const tile = frame.tile ?? EMPLOYEE_BY_ID.get(who)!.desk;
          expect(
            isWalkable(tile, who),
            `${routine.id}: ${who} stands on ${tile.col},${tile.row}`,
          ).toBe(true);
          const step = Math.abs(tile.col - previous.col) + Math.abs(tile.row - previous.row);
          expect(step, `${routine.id}: ${who} jumps ${step} tiles`).toBeLessThanOrEqual(1);
          previous = tile;
        }
        expect(frames[frames.length - 1]!.tile, `${routine.id}: ${who} never gets back`).toBeUndefined();
      }
    }
  });

  it("keeps the lane past the pool table open", () => {
    // The table sits on row 11 and row 10 stays clear, because row 10 is how
    // anyone crosses the lounge to the viewport. A table on both rows would
    // wall the east end off from the rest of the room.
    for (const col of [12, 13, 14]) {
      expect(
        isWalkable({ col, row: 10 }, "nova"),
        `the lounge lane is blocked at ${col},10`,
      ).toBe(true);
    }
  });

  it("never plays a game while the office is at alert", () => {
    for (const routine of GAME_ROUTINES) {
      expect(routine.suppressOnAlert, `${routine.id} plays through an alert`).toBe(true);
    }
  });

  it("gives the two tables to different pairs, in different rooms", () => {
    // A games corner one pair ever uses is a prop. Two rooms means a game is a
    // reason to go somewhere, which is the point of putting them in a building.
    const pool = FURNITURE.find((p) => p.kind === "pool-table")!;
    const foos = FURNITURE.find((p) => p.kind === "foosball-table")!;
    expect(Math.abs(pool.tile.row - foos.tile.row)).toBeGreaterThan(4);
  });
});

/* ── the ideas board ──────────────────────────────────────────────────── */

describe("ideas from the floor", () => {
  it("raises nothing at all with no readings", () => {
    // The property that makes this honest. An empty office produces an empty
    // board — not generic advice, not a placeholder.
    expect(ideasFrom(deriveHqState())).toEqual([]);
  });

  function withOps(overrides: Record<string, unknown>): HqState {
    const health = {
      disk: { status: "healthy", percent_used: 20, warning_percent: 80, critical_percent: 90, measured: true, detail: "" },
      redis: { component: "redis", status: "healthy", detail: "", latency_ms: 1, measured: true },
      database: { component: "database", status: "healthy", detail: "", latency_ms: 1, measured: true },
      worker: { status: "healthy", nodes: [], replies: 1, measured: true, detail: "" },
      scheduler: { status: "healthy", last_beat: null, seconds_since_beat: 1, expected_within_seconds: 300, measured: true, detail: "" },
      queues: { status: "healthy", depths: {}, total: 0, measured: true, detail: "" },
      overall: "healthy",
      unmeasured: 0,
      environment: "test",
      version: "0",
      observed_at: new Date().toISOString(),
      ...overrides,
    };
    return deriveHqState({
      operations: {
        data: {
          health,
          incidents: [],
          recent: [],
          activity: [],
          allowlist: [{ key: "a", autonomy: "green", agent: "byte", summary: "", reversible: true }],
          autonomy_enabled: true,
          invariants: {},
        } as never,
        observedAt: Date.now(),
      },
      now: Date.now(),
    });
  }

  it("raises the disk only once it crosses its own warning line", () => {
    const quiet = ideasFrom(withOps({}));
    expect(quiet.find((i) => i.id === "disk-headroom")).toBeUndefined();

    const loud = ideasFrom(
      withOps({
        disk: { status: "degraded", percent_used: 84, warning_percent: 80, critical_percent: 90, measured: true, detail: "" },
      }),
    );
    const idea = loud.find((i) => i.id === "disk-headroom")!;
    expect(idea).toBeDefined();
    // The figure itself must be in the sentence, not a description of it.
    expect(idea.because).toContain("84%");
    expect(idea.urgency).toBe("soon");
  });

  it("escalates to now only past the critical line", () => {
    const critical = ideasFrom(
      withOps({
        disk: { status: "down", percent_used: 94, warning_percent: 80, critical_percent: 90, measured: true, detail: "" },
      }),
    );
    expect(critical.find((i) => i.id === "disk-headroom")!.urgency).toBe("now");
  });

  it("says nothing about a disk it could not read", () => {
    // The rule the whole product turns on: unmeasured is not zero and not fine.
    const unread = ideasFrom(
      withOps({
        disk: { status: "unknown", percent_used: null, warning_percent: 80, critical_percent: 90, measured: false, detail: "" },
      }),
    );
    expect(unread.find((i) => i.id === "disk-headroom")).toBeUndefined();
  });

  it("gives every idea a figure and the field it came from", () => {
    const ideas = ideasFrom(
      withOps({
        disk: { status: "degraded", percent_used: 84, warning_percent: 80, critical_percent: 90, measured: true, detail: "" },
        queues: { status: "degraded", depths: { enrich: 900 }, total: 900, measured: true, detail: "" },
      }),
    );
    expect(ideas.length).toBeGreaterThan(1);
    for (const idea of ideas) {
      expect(idea.source, `${idea.id} names no source`).toMatch(/·/);
      expect(idea.because.length, `${idea.id} has no evidence`).toBeGreaterThan(20);
      expect(EMPLOYEE_BY_ID.get(idea.from), `${idea.id} is from nobody`).toBeDefined();
      // An idea must be an instruction, not an observation.
      expect(idea.headline.length).toBeLessThan(70);
    }
  });

  it("orders the board by urgency, not by who spoke first", () => {
    const ideas = ideasFrom(
      withOps({
        disk: { status: "down", percent_used: 94, warning_percent: 80, critical_percent: 90, measured: true, detail: "" },
        queues: { status: "degraded", depths: { enrich: 600 }, total: 600, measured: true, detail: "" },
      }),
    );
    const rank = { now: 0, soon: 1, "worth doing": 2 } as const;
    for (let i = 1; i < ideas.length; i += 1) {
      expect(rank[ideas[i]!.urgency]).toBeGreaterThanOrEqual(rank[ideas[i - 1]!.urgency]);
    }
  });

  it("proposes no strategy, ever", () => {
    // Eight recorded no-edge findings say a cartoon character proposing a way
    // to make money would be inventing the one claim this research has most
    // expensively earned the right to refuse.
    const ideas = ideasFrom(
      withOps({
        disk: { status: "down", percent_used: 94, warning_percent: 80, critical_percent: 90, measured: true, detail: "" },
      }),
    );
    const banned = /\b(buy|sell|entry|exit|edge|alpha|profit|strategy|signal|momentum)\b/i;
    for (const idea of ideas) {
      expect(banned.test(idea.headline), `${idea.id}: ${idea.headline}`).toBe(false);
    }
  });
});

/* ── the room stayed a room ───────────────────────────────────────────── */

describe("the office still works", () => {
  it("gives everybody who plays a game their ordinary routines too", () => {
    for (const routine of GAME_ROUTINES) {
      const others = (ROUTINES_BY_EMPLOYEE.get(routine.employee) ?? []).filter(
        (r) => !socialIds.has(r.id),
      );
      expect(others.length, `${routine.employee} only ever plays`).toBeGreaterThanOrEqual(2);
    }
  });
});
