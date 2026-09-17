"use client";

import { useEffect, useRef, useState } from "react";

import { AUTO_HOLD_MS, FLOOR_SHOT, ROOM, sameTarget, type CameraTarget } from "@/lib/hq/camera";
import type { HqState } from "@/lib/hq/adapter";
import { EMPLOYEES, type EmployeeId } from "@/lib/hq/employees";

/**
 * WHERE THE CAMERA LOOKS, AND WHO DECIDES.
 *
 * Four sources, in a strict order that never changes:
 *
 *   1. the reader        — a manual selection holds until they clear it
 *   2. the dance floor   — while the music plays and the office is dancing
 *   3. a real reaction   — the camera visits, holds, and comes back
 *   4. the room          — the default, and where it always returns
 *
 * Reactions are not followed at all during the party, rather than merely
 * outranked: a reaction is framed on the reacting person's DESK, and during
 * the party every desk is empty. The first live run of the dance was exactly
 * that — a camera cutting between empty chairs while the whole office danced
 * out of shot.
 *
 * ── WHY THE READER ALWAYS WINS ──────────────────────────────────────────
 *
 * A camera that pulls away from what somebody chose to look at is a camera
 * fighting its user. So a manual selection has no timeout and cannot be
 * interrupted: while `manual` is set, nothing else moves the frame. Auto only
 * ever acts on an idle camera.
 *
 * ── WHAT COUNTS AS "DOING SOMETHING" ────────────────────────────────────
 *
 * Only a live `speech` on an employee's reading — which the adapter sets from
 * `react()`, and `react()` fires exclusively on a *witnessed change* in a
 * published figure. So the camera follows things that actually happened.
 *
 * It deliberately does NOT follow ambient routines. Those fire on a timer, and
 * a camera that pushed in on somebody walking to the coffee machine would
 * teach a reader that a close-up means something is happening — which would
 * then be false two thirds of the time, and worse, would make the one time it
 * mattered indistinguishable from the noise.
 *
 * ── REDUCED MOTION TURNS THE FOLLOWING OFF, NOT THE FRAMING ─────────────
 *
 * An unrequested camera move is exactly the motion a vestibular disorder
 * cannot tolerate, so auto-follow is disabled outright. Clicking a character
 * still frames them — that is information, and it arrives without travelling
 * because the CSS transition is off too.
 */
export interface CameraHandle {
  target: CameraTarget;
  /** Non-null while the reader has chosen somebody. Drives the dossier panel. */
  selected: EmployeeId | null;
  select: (employee: EmployeeId | null) => void;
  /** True when the camera moved on its own. Shown as a small "following" hint. */
  auto: boolean;
}

export function useCamera(state: HqState, follow: boolean, party = false): CameraHandle {
  const [manual, setManual] = useState<EmployeeId | null>(null);
  const [auto, setAuto] = useState<EmployeeId | null>(null);
  const lastSpeech = useRef<Partial<Record<EmployeeId, string>>>({});

  // Who is mid-reaction right now, if anyone. First match wins rather than a
  // scored "most important": two real reactions in the same tick is rare, and
  // a tiebreak nobody can predict is worse than a stable one.
  let reacting: EmployeeId | null = null;
  for (const employee of EMPLOYEES) {
    if (state.employees[employee.id]?.speech) {
      reacting = employee.id;
      break;
    }
  }

  /**
   * Trigger. Notices a *new* reaction and nothing else.
   *
   * Deliberately does not own the timer. The first version did both here, and
   * because `state` is in the dependency list — a fresh object on every tick of
   * the event meter — React ran the cleanup on each render, cleared the pending
   * timeout, then hit the "same speech, already handled" guard and returned
   * without setting a replacement. The camera arrived and never left. Splitting
   * the two means the hold is keyed on the subject alone.
   */
  useEffect(() => {
    if (!follow || manual || !reacting) return;
    const speech = state.employees[reacting]?.speech;
    if (lastSpeech.current[reacting] === speech) return;
    // Recorded even during the party, so the reaction that was happening when
    // the music started is not replayed the moment it stops.
    lastSpeech.current[reacting] = speech;
    if (!party) setAuto(reacting);
  }, [follow, manual, reacting, state, party]);

  // The music starting cancels any visit in progress: that desk is about to
  // be empty.
  useEffect(() => {
    if (party) setAuto(null);
  }, [party]);

  /**
   * The hold. Keyed on who the camera is visiting, so a re-render that changes
   * nothing about the visit cannot restart it.
   */
  useEffect(() => {
    if (!auto) return;
    const handle = window.setTimeout(() => setAuto(null), AUTO_HOLD_MS);
    return () => window.clearTimeout(handle);
  }, [auto]);

  // A manual selection cancels any visit in progress, so the two can never
  // both be live and disagree about the frame.
  function select(employee: EmployeeId | null) {
    setAuto(null);
    setManual(employee);
  }

  const who = manual ?? (follow && !party ? auto : null);
  const target: CameraTarget = who
    ? { kind: "desk", employee: who }
    : follow && party
      ? FLOOR_SHOT
      : ROOM;

  return {
    target,
    selected: manual,
    select,
    auto: !manual && auto !== null,
  };
}

/** Exported for the tests: two framings that mean the same thing. */
export { sameTarget };
