"use client";

import { useEffect, useRef, useState } from "react";

import type { ActorFrame } from "@/lib/hq/ambient";
import { createAmbientScheduler, type ActorId } from "@/lib/hq/ambient-scheduler";
import type { OfficeActivity } from "@/lib/hq/adapter";
import type { DayPhase } from "@/lib/hq/ambient";
import type { EmployeeId } from "@/lib/hq/employees";

/**
 * THE OFFICE'S LIFE, AS REACT STATE.
 *
 * Owned by the page rather than the stage since the world expansion, for one
 * reason: the personality panels. Clicking Mochi should say what Mochi is
 * doing, and only the owner of the frames can say — so the page runs the
 * scheduler, hands the frames to the stage to draw, and reads the same frames
 * for the panel text.
 *
 * `enabled` is a convenience, not the guarantee: the scheduler refuses to run
 * under reduced motion or a hidden tab whatever this hook passes. Mobile
 * passes `false` and the scheduler is never even created — the card stack
 * gets a still office and none of the machinery.
 */
export interface AmbientHandle {
  frames: Partial<Record<ActorId, ActorFrame>>;
  /**
   * The live scheduler, for the one caller that must take the floor from it.
   *
   * Exposed as a ref rather than returned directly because the report meeting
   * needs to *suspend* the ambient layer, and the alternative — a second
   * scheduler for meetings — is the thing this module's header refuses. The
   * ref is null on mobile and under reduced motion, where no scheduler is
   * created at all, so every caller has to handle its absence anyway.
   */
  scheduler: React.MutableRefObject<ReturnType<typeof createAmbientScheduler> | null>;
  /**
   * Frames the report meeting is driving. Painted over the ambient ones.
   *
   * The raw setter, so callers can pass an updater. That matters: the meeting
   * repaints one speaker at a time, and a plain assignment replaced the whole
   * map — which sent the other nine attendees back to their desks the instant
   * anybody opened their mouth.
   */
  setOverride: React.Dispatch<React.SetStateAction<Partial<Record<ActorId, ActorFrame>>>>;
}

export function useAmbient(
  enabled: boolean,
  operational: EmployeeId[],
  activity: OfficeActivity,
  phase: DayPhase,
): AmbientHandle {
  const [frames, setFrames] = useState<Partial<Record<ActorId, ActorFrame>>>({});
  const [override, setOverride] = useState<Partial<Record<ActorId, ActorFrame>>>({});
  const schedulerRef = useRef<ReturnType<typeof createAmbientScheduler> | null>(null);

  useEffect(() => {
    if (!enabled) return;
    const scheduler = createAmbientScheduler((actor, frame) => {
      setFrames((previous) => ({ ...previous, [actor]: frame ?? undefined }));
    });
    schedulerRef.current = scheduler;
    scheduler.start();
    return () => {
      scheduler.destroy();
      schedulerRef.current = null;
      setFrames({});
    };
  }, [enabled]);

  // Keyed on the joined list rather than the array: the adapter rebuilds it on
  // every derivation, so the identity changes every few seconds while the
  // membership almost never does.
  const key = operational.join(",");
  useEffect(() => {
    schedulerRef.current?.setOperational(key ? (key.split(",") as EmployeeId[]) : []);
  }, [key, enabled]);

  useEffect(() => {
    schedulerRef.current?.setActivity(activity);
  }, [activity, enabled]);

  useEffect(() => {
    schedulerRef.current?.setPhase(phase);
  }, [phase, enabled]);

  // The meeting's frames win where they exist. They only exist while the
  // scheduler is suspended, so this is a hand-off rather than a fight.
  const merged = Object.keys(override).length > 0 ? { ...frames, ...override } : frames;
  return { frames: merged, scheduler: schedulerRef, setOverride };
}
