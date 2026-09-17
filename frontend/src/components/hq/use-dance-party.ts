"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { soundtrackPosition } from "@/hooks/use-space-audio";
import type { ActorFrame } from "@/lib/hq/ambient";
import type { ActorId, AmbientScheduler } from "@/lib/hq/ambient-scheduler";
import { DANCE_LEGS, danceEpochMs } from "@/lib/hq/dance";

/**
 * THE MUSIC BUTTON, AS A STATE MACHINE.
 *
 *   idle      → nothing. The ambient office runs.
 *   settling  → the music started. Ambient stops starting routines, and anyone
 *               mid-walk finishes first — nobody is snapped anywhere.
 *   gathering → everyone walks down to the lobby, front row first.
 *   dancing   → the routine, on the beat, until the music stops.
 *   leaving   → back to the desks, back row first. Then ambient resumes.
 *
 * Shaped exactly like `use-report-meeting`, and sharing its floor-clearing
 * with it, because the two want the same thing from the office: everybody
 * somewhere other than their desk, on purpose. They are mutually exclusive —
 * the office cannot hold a meeting and a dance at once — and the meeting has
 * right of way: a dance never starts while a report is open.
 *
 * ── REDUCED MOTION AND MOBILE GET NO DANCE AT ALL ───────────────────────
 *
 * The report meeting skips its walk but keeps its report, because the report
 * is information. A dance has no information in it. For someone who asked for
 * stillness, the correct dance is none, and the music still plays.
 */
export type DancePhase = "idle" | "settling" | "gathering" | "dancing" | "leaving";

/** How often the dancers are pulled back onto the beat. */
const SYNC_EVERY_MS = 500;

/**
 * How far a dancer may drift before being re-pinned.
 *
 * `audio.currentTime` advances in chunks, so an epoch computed from it wobbles
 * by a few milliseconds sample to sample. Re-pinning on every wobble would jog
 * the whole floor twice a second for nothing. A newly arrived dancer is off by
 * seconds, and a track that loops jumps by minutes; both clear this easily.
 */
const DRIFT_TOLERANCE_MS = 40;

interface PinnableAnimation {
  startTime: number | null | CSSNumberish;
  animationName?: string;
}

/**
 * Put every dance animation on one clock. Exported for the test.
 *
 * Only the three dance keyframe sets are touched, by name. Everything else
 * animating in the office — breathing, packets, cats — keeps its own time.
 */
export function pinToBeat(animations: Iterable<PinnableAnimation>, epochMs: number): number {
  const dancing = [...animations].filter((a) => a.animationName?.startsWith("hq-dance"));
  const offBeat = dancing.some((a) => {
    const current = typeof a.startTime === "number" ? a.startTime : null;
    return current === null || Math.abs(current - epochMs) >= DRIFT_TOLERANCE_MS;
  });
  if (!offBeat) return 0;
  // All of them, not just the one that drifted. Re-pinning only the stragglers
  // left the rest on whichever epoch they were pinned to earlier — each within
  // tolerance, but not the same one — and the floor ran 13ms apart. Measured
  // under a pixel, but "one clock" should mean one number.
  for (const animation of dancing) animation.startTime = epochMs;
  return dancing.length;
}

function syncToMusic(): void {
  if (typeof document === "undefined" || typeof document.getAnimations !== "function") return;
  const position = soundtrackPosition();
  const now = document.timeline?.currentTime;
  // Nothing playing, or a page with no timeline: leave them where they are
  // rather than pin them to a clock that is not running.
  if (position === null || typeof now !== "number") return;
  pinToBeat(document.getAnimations() as PinnableAnimation[], danceEpochMs(now, position));
}

export function useDanceParty(
  scheduler: React.MutableRefObject<AmbientScheduler | null>,
  setOverride: React.Dispatch<React.SetStateAction<Partial<Record<ActorId, ActorFrame>>>>,
  options: {
    /** Motion allowed and not on a phone. */
    animate: boolean;
    /** The music button's state. */
    musicOn: boolean;
    /** A dance never starts over an open report. */
    meetingIdle: boolean;
  },
): { phase: DancePhase; busy: boolean } {
  const { animate, musicOn, meetingIdle } = options;
  const [phase, setPhase] = useState<DancePhase>("idle");
  const timers = useRef<Array<ReturnType<typeof setTimeout>>>([]);
  // Bumped on every start and stop. A floor-clearing promise that resolves
  // after the music has already been switched off must not start a walk.
  const generation = useRef(0);

  const clearTimers = useCallback(() => {
    for (const handle of timers.current) clearTimeout(handle);
    timers.current = [];
  }, []);

  const playLeg = useCallback(
    (which: "gather" | "depart", done: () => void) => {
      const legs = [...DANCE_LEGS.entries()];
      let outstanding = legs.length;
      const finishOne = () => {
        outstanding -= 1;
        if (outstanding === 0) done();
      };
      for (const [employee, leg] of legs) {
        const frames = leg[which];
        let elapsed = 0;
        frames.forEach((frame, index) => {
          timers.current.push(
            setTimeout(() => {
              // Merged, never assigned: sixteen other timer chains are writing
              // to the same map, and a replaced map snaps them all home.
              setOverride((current) => ({ ...current, [employee]: frame }));
              if (index === frames.length - 1) finishOne();
            }, elapsed),
          );
          elapsed += frame.hold;
        });
        if (frames.length === 0) finishOne();
      }
    },
    [setOverride],
  );

  const start = useCallback(() => {
    const mine = ++generation.current;
    setPhase("settling");
    const settled = scheduler.current?.suspendForReport() ?? Promise.resolve();
    void settled.then(() => {
      if (mine !== generation.current) return;
      setPhase("gathering");
      playLeg("gather", () => {
        if (mine === generation.current) setPhase("dancing");
      });
    });
  }, [playLeg, scheduler]);

  const toIdle = useCallback(() => {
    clearTimers();
    setOverride({});
    setPhase("idle");
    scheduler.current?.resumeAfterReport();
  }, [clearTimers, scheduler, setOverride]);

  const stop = useCallback(() => {
    const mine = ++generation.current;
    clearTimers();
    setPhase("leaving");
    playLeg("depart", () => {
      if (mine === generation.current) toIdle();
    });
  }, [clearTimers, playLeg, toIdle]);

  // The whole trigger. The music button is the only way in or out.
  useEffect(() => {
    if (phase === "idle") {
      if (musicOn && animate && meetingIdle) start();
      return;
    }
    if (musicOn && animate) return;
    if (phase === "settling") {
      // The floor never cleared, so nobody left their desk: nothing to walk back.
      generation.current += 1;
      toIdle();
    } else if (phase === "gathering" || phase === "dancing") {
      stop();
    }
  }, [phase, musicOn, animate, meetingIdle, start, stop, toIdle]);

  // Keep the floor on the beat for as long as anyone is out there dancing.
  useEffect(() => {
    if (phase !== "gathering" && phase !== "dancing" && phase !== "leaving") return;
    syncToMusic();
    const handle = setInterval(syncToMusic, SYNC_EVERY_MS);
    return () => clearInterval(handle);
  }, [phase]);

  // Leaving the page mid-dance: no timer may fire into an unmounted office.
  useEffect(() => () => clearTimers(), [clearTimers]);

  return { phase, busy: phase !== "idle" };
}
