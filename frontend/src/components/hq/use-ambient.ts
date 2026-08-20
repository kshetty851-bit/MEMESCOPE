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
export function useAmbient(
  enabled: boolean,
  operational: EmployeeId[],
  activity: OfficeActivity,
  phase: DayPhase,
): Partial<Record<ActorId, ActorFrame>> {
  const [frames, setFrames] = useState<Partial<Record<ActorId, ActorFrame>>>({});
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

  return frames;
}
