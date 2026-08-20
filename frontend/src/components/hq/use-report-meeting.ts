"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import type { ActorFrame } from "@/lib/hq/ambient";
import type { ActorId, AmbientScheduler } from "@/lib/hq/ambient-scheduler";
import type { HqState } from "@/lib/hq/adapter";
import type { EmployeeId } from "@/lib/hq/employees";
import { buildDialogue, buildReport, type DialogueLine, type HqReport } from "@/lib/hq/report";
import {
  MEETING_LEGS,
  REPORT_ORDER,
  listeningPose,
  speakingPose,
  STATION_BY_EMPLOYEE,
} from "@/lib/hq/report-meeting";

/**
 * "PROVIDE UPDATED REPORT", AS A STATE MACHINE.
 *
 * ── PHASES ──────────────────────────────────────────────────────────────
 *
 *   idle      → nothing. The ambient office runs.
 *   settling  → the button was pressed. Ambient stops *starting* routines and
 *               anyone mid-walk finishes or yields along their own return leg.
 *               Nobody is snapped anywhere; this phase exists precisely so
 *               they are not.
 *   gathering → the ten walk to the conference room along authored routes.
 *   meeting   → they report, one at a time, in the order §10 sets.
 *   holding   → the meeting is over and the panel is open. Everyone stays put
 *               until the reader closes it, because a report whose subjects
 *               wandered off while it was being read looks like a bug.
 *   leaving   → back to their desks, then ambient resumes.
 *
 * ── ONE MEETING, EVER ───────────────────────────────────────────────────
 *
 * `phase !== "idle"` is the whole of the double-click guard, and it is checked
 * inside the callback rather than only on the button, so a second entry point
 * — a keyboard, a test, a future deep link — cannot start a second meeting.
 * `suspendForReport` is idempotent underneath it for the same reason.
 *
 * ── REDUCED MOTION AND MOBILE SKIP THE WALK, NOT THE REPORT ─────────────
 *
 * Both go straight to `holding` with the same report from the same state. The
 * information is the point; the choreography is the presentation of it, and
 * withholding the information from someone who asked for stillness would be
 * the accessibility failure, not the animation.
 *
 * ── IT CANNOT TRADE ─────────────────────────────────────────────────────
 *
 * The only inputs are an `HqState` and a scheduler ref. There is no fetch, no
 * mutation and no writable client here; `buildReport` is pure. The meeting
 * changes what is drawn and nothing else.
 */
export type MeetingPhase =
  | "idle"
  | "settling"
  | "gathering"
  | "meeting"
  | "holding"
  | "leaving";

/** How long each person's turn lasts. Long enough to read a short bubble. */
const TURN_MS = 3_400;

export interface ReportMeeting {
  phase: MeetingPhase;
  /** Non-null from the moment the report is built until it is closed. */
  report: HqReport | null;
  /** The line currently being spoken, if any. */
  speaking: DialogueLine | null;
  /** Every line said so far, for the transcript the panel shows. */
  said: DialogueLine[];
  /** True while the panel should be on screen. */
  panelOpen: boolean;
  start: () => void;
  refresh: () => void;
  close: () => void;
  /** True when the button must be disabled. */
  busy: boolean;
}

export function useReportMeeting(
  state: HqState,
  scheduler: React.MutableRefObject<AmbientScheduler | null>,
  setOverride: React.Dispatch<React.SetStateAction<Partial<Record<ActorId, ActorFrame>>>>,
  options: { animate: boolean },
): ReportMeeting {
  const [phase, setPhase] = useState<MeetingPhase>("idle");
  /**
   * The guard that actually holds, because `phase` does not.
   *
   * Three synchronous clicks all read the same `phase` from the same closure —
   * React has not re-rendered between them — so a state check let all three
   * through and started three meetings on top of each other. A ref is written
   * immediately, so the second call sees the first. Found by a test; the
   * browser hid it behind event-loop timing.
   */
  const runningRef = useRef(false);
  const [report, setReport] = useState<HqReport | null>(null);
  const [turn, setTurn] = useState(-1);
  const dialogueRef = useRef<DialogueLine[]>([]);
  const timers = useRef<Array<ReturnType<typeof setTimeout>>>([]);
  // The state is read at the moment the reader asks, not continuously: a
  // report that changed its own figures while being read would be unciteable.
  const stateRef = useRef(state);
  stateRef.current = state;

  const clearTimers = useCallback(() => {
    for (const handle of timers.current) clearTimeout(handle);
    timers.current = [];
  }, []);

  const after = useCallback((ms: number, run: () => void) => {
    timers.current.push(setTimeout(run, ms));
  }, []);

  /** Paint one frame per attendee, all at their stations. */
  const seatEveryone = useCallback(() => {
    const frames: Partial<Record<ActorId, ActorFrame>> = {};
    for (const employee of REPORT_ORDER) {
      const station = STATION_BY_EMPLOYEE.get(employee);
      if (!station) continue;
      frames[employee] = {
        pose: listeningPose(employee),
        tile: station.tile,
        hold: TURN_MS,
        detail: "In the report meeting.",
      };
    }
    setOverride(frames);
  }, [setOverride]);

  /** Walk everyone in, one authored frame at a time. */
  const playLeg = useCallback(
    (which: "gather" | "depart", done: () => void) => {
      let outstanding = REPORT_ORDER.length;
      const finishOne = () => {
        outstanding -= 1;
        if (outstanding === 0) done();
      };

      for (const employee of REPORT_ORDER) {
        const leg = MEETING_LEGS.get(employee);
        if (!leg) {
          finishOne();
          continue;
        }
        const steps = leg[which];
        let elapsed = 0;
        steps.forEach((frame, index) => {
          after(elapsed, () => {
            // Ten people walk at once and each has their own timer chain, so
            // every write has to be a merge onto whatever the other nine have
            // already painted. A snapshot captured outside the timeout goes
            // stale the moment somebody else takes a step.
            setOverride((current) => ({ ...current, [employee]: frame }));
            if (index === steps.length - 1) finishOne();
          });
          elapsed += frame.hold;
        });
        if (steps.length === 0) finishOne();
      }
    },
    [after, setOverride],
  );

  const start = useCallback(() => {
    // The guard lives here, not on the button: a second entry point must not
    // be able to start a second meeting.
    if (runningRef.current || phase !== "idle") return;
    runningRef.current = true;
    const built = buildReport(stateRef.current);
    dialogueRef.current = buildDialogue(built);
    setReport(built);
    setTurn(-1);

    if (!options.animate) {
      // Reduced motion or mobile: the report, without the walk.
      setPhase("holding");
      setTurn(dialogueRef.current.length - 1);
      return;
    }

    setPhase("settling");
    const engine = scheduler.current;
    const settled = engine ? engine.suspendForReport() : Promise.resolve();
    settled.then(() => {
      setPhase("gathering");
      playLeg("gather", () => {
        seatEveryone();
        setPhase("meeting");
        setTurn(0);
      });
    });
  }, [phase, options.animate, scheduler, playLeg, seatEveryone]);

  /** Every path back to idle goes through here, so the guard cannot leak. */
  const toIdle = useCallback(() => {
    runningRef.current = false;
    setOverride({});
    setReport(null);
    setPhase("idle");
    setTurn(-1);
    scheduler.current?.resumeAfterReport();
  }, [scheduler, setOverride]);

  /* One turn at a time, in order. */
  useEffect(() => {
    if (phase !== "meeting" || turn < 0) return;
    const dialogue = dialogueRef.current;
    if (turn >= dialogue.length) {
      setPhase("holding");
      return;
    }
    const line = dialogue[turn]!;
    const station = STATION_BY_EMPLOYEE.get(line.employee);
    if (station) {
      // Merged, not assigned: the other nine are still at their stations and
      // must stay there. Replacing the map dropped their frames and snapped
      // them home mid-sentence.
      setOverride((current) => ({
        ...current,
        [line.employee]: {
          pose: speakingPose(line.employee),
          tile: station.tile,
          hold: TURN_MS,
          detail: line.text,
          speech: line.text,
        },
      }));
    }
    const handle = setTimeout(() => {
      if (station) {
        setOverride((current) => ({
          ...current,
          [line.employee]: {
            pose: listeningPose(line.employee),
            tile: station.tile,
            hold: TURN_MS,
            detail: "In the report meeting.",
          },
        }));
      }
      setTurn((current) => current + 1);
    }, TURN_MS);
    return () => clearTimeout(handle);
  }, [phase, turn, setOverride]);

  const close = useCallback(() => {
    clearTimers();
    if (!options.animate || phase === "idle") {
      toIdle();
      return;
    }
    setPhase("leaving");
    playLeg("depart", toIdle);
  }, [clearTimers, options.animate, phase, playLeg, toIdle]);

  /** Rebuild the report from the state as it is now. Never re-runs the walk. */
  const refresh = useCallback(() => {
    const built = buildReport(stateRef.current);
    dialogueRef.current = buildDialogue(built);
    setReport(built);
  }, []);

  useEffect(() => clearTimers, [clearTimers]);

  const said = report ? dialogueRef.current.slice(0, Math.max(0, turn + 1)) : [];
  return {
    phase,
    report,
    speaking: phase === "meeting" && turn >= 0 ? (dialogueRef.current[turn] ?? null) : null,
    said,
    panelOpen: report !== null && (phase === "meeting" || phase === "holding"),
    start,
    refresh,
    close,
    busy: phase !== "idle",
  };
}

/** Exported for the panel's transcript ordering test. */
export const MEETING_TURN_MS = TURN_MS;
export type { EmployeeId, HqReport };
