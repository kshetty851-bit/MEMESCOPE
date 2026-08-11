/**
 * THE LAUNCH SEQUENCE — one timeline, read by React and by CSS.
 *
 * The gate stopped being a form the moment an accepted code became a mission.
 * What follows an accepted code is a fixed, linear sequence, so it is written
 * here as data rather than as control flow scattered across three components:
 *
 *     approved → countdown ×5 → ignition → launching → flight → approach
 *     → unlock → enter
 *
 * Two consumers read this file and they must not disagree. React walks the
 * table with one timer per step. CSS runs the scene animations, and it gets
 * its durations from `launchDurations()` as custom properties rather than
 * restating the numbers in a stylesheet — a countdown whose lights finish
 * half a second after the digits reach one is the failure this prevents.
 *
 * Nothing here touches authentication. `AlphaAccess` still owns the unlock
 * request and the session cookie; this only decides what the sky does after
 * the server has already said yes.
 */

export type LaunchPhase =
  | "idle"
  | "approved"
  | "countdown"
  | "ignition"
  | "launching"
  | "flight"
  | "approach"
  | "unlock"
  | "enter";

/** What the access form itself reports back while it is still in charge. */
export type GatePhase = "idle" | "validating" | "denied";

/** Everything the landing page might be showing at a given moment. */
export type ScenePhase = LaunchPhase | GatePhase;

export type LaunchStep = {
  phase: LaunchPhase;
  /** How long this step holds before the next one begins. */
  ms: number;
  /** The digit on screen, for countdown steps only. */
  count?: number;
};

export const COUNTDOWN_FROM = 5;
export const COUNTDOWN_TICK = 700;

const countdown: LaunchStep[] = Array.from({ length: COUNTDOWN_FROM }, (_, index) => ({
  phase: "countdown" as const,
  ms: COUNTDOWN_TICK,
  count: COUNTDOWN_FROM - index,
}));

/**
 * The full cinematic. Ignition to entry is deliberately ~6.5s: long enough to
 * read as a journey, short enough that a tester who has seen it four times
 * today is not held hostage by it.
 */
export const LAUNCH_TIMELINE: readonly LaunchStep[] = [
  { phase: "approved", ms: 1300 },
  ...countdown,
  { phase: "ignition", ms: 700 },
  { phase: "launching", ms: 1500 },
  { phase: "flight", ms: 2300 },
  { phase: "approach", ms: 1100 },
  { phase: "unlock", ms: 900 },
  { phase: "enter", ms: 0 },
];

/**
 * Reduced motion gets the confirmation and the door, not the ride. This is the
 * whole accommodation: same states, same navigation, none of the travel.
 */
export const REDUCED_TIMELINE: readonly LaunchStep[] = [
  { phase: "approved", ms: 900 },
  { phase: "enter", ms: 0 },
];

const ORDER: readonly LaunchPhase[] = [
  "idle",
  "approved",
  "countdown",
  "ignition",
  "launching",
  "flight",
  "approach",
  "unlock",
  "enter",
];

/**
 * Whether the sequence has reached a mark and stayed there.
 *
 * The scene needs latching state — an engine lit at ignition is still lit
 * during flight — and CSS has no way to express "this attribute or any later
 * one". So the cumulative flags are computed here and written to the DOM as
 * plain boolean attributes.
 */
export function atOrAfter(phase: ScenePhase, mark: LaunchPhase): boolean {
  const index = ORDER.indexOf(phase as LaunchPhase);
  return index >= 0 && index >= ORDER.indexOf(mark);
}

function totalFor(phase: LaunchPhase): number {
  return LAUNCH_TIMELINE.filter((step) => step.phase === phase).reduce(
    (sum, step) => sum + step.ms,
    0,
  );
}

/** How long the rocket is in the air: lift-off through to the planet filling the frame. */
export const FLIGHT_MS = totalFor("launching") + totalFor("flight") + totalFor("approach");

/**
 * The timeline as CSS custom properties, applied to the scene root so every
 * keyframe animation can be timed off the same numbers React is stepping
 * through.
 */
export function launchDurations(): Record<string, string> {
  return {
    "--hu-countdown": `${totalFor("countdown")}ms`,
    "--hu-ignition": `${totalFor("ignition")}ms`,
    "--hu-approach": `${totalFor("approach")}ms`,
    "--hu-unlock": `${totalFor("unlock")}ms`,
    "--hu-flight": `${FLIGHT_MS}ms`,
  };
}
