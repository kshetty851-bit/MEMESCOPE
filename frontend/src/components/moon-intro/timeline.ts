/**
 * THE MOON INTRO — one timeline, read by every layer.
 *
 * The master clock (moon-intro.tsx) turns elapsed seconds into a `Frame` and
 * hands the same frame to the cockpit (React/SVG), the space canvas and the
 * soundboard. Nothing else keeps time. Tune the ride here and only here.
 *
 * Moments inside a phase are written as FRACTIONS of that phase (0..1), so
 * stretching a phase moves its beats with it.
 */

export type IntroPhase =
  | "seatbelt" // blackout, hazard stripes, FASTEN YOUR SEATBELT -> SECURED
  | "cockpit" // struts, dashboard, overhead panel, HUD boot, switches
  | "ignition" // 3-2-1, throttle forward, gauges swing up
  | "warp" // star streaks + candle streaks, readouts racing
  | "approach" // flash out of warp, moon grows, reticle lock, asteroid near-miss
  | "landing" // surface fills view, dust, retro flare, thud, EAGLE HAS LANDED
  | "reveal" // canopy becomes LANDING CONSOLE, frame dollies past the camera
  | "done";

/** Seconds each phase lasts, in order. */
export type Timeline = ReadonlyArray<readonly [IntroPhase, number]>;

/**
 * The ride, 15s, played in full on every sign-in: Karthik asked for it slower
 * so every animation can be seen (2026-09-26; it was 10.8s, with a 2.5s cut
 * for a second visit in the same session). SKIP is there for when it isn't.
 */
export const TIMELINE: Timeline = [
  ["seatbelt", 1.8],
  ["cockpit", 2.2],
  ["ignition", 1.5],
  ["warp", 2.8],
  ["approach", 3.6],
  ["landing", 2.1],
  ["reveal", 1.0],
];

/** Reduced motion: a still cockpit fades in, then the door. 1.5s, no travel. */
export const REDUCED_TIMELINE: Timeline = [
  ["cockpit", 1.1],
  ["reveal", 0.4],
];

/** Where skip lands: the reveal, played in full. */
export const SKIP_TO: IntroPhase = "reveal";

/**
 * Moments inside a phase, as fractions of it. The clock fires each once as
 * `p` crosses it (sound + one-shot effects); renderers may also read them.
 */
export const MOMENTS = {
  seatbelt: { typeEnd: 0.55, buckle: 0.72, secured: 0.8 },
  cockpit: { lockIn: 0.45, hudBoot: 0.5, switches: [0.6, 0.7, 0.8, 0.9] as const },
  ignition: { beeps: [0.0, 0.33, 0.66] as const, throttle: 0.7 },
  warp: { velocity: [0, 0.25, 0.55, 0.85] as const },
  approach: { flash: 0.0, asteroids: 0.25, nearMiss: 0.34, repaired: 0.55, lock: 0.7 },
  landing: { retro: 0.25, touchdown: 0.55, eagle: 0.62 },
  reveal: { console: 0.0, dolly: 0.45 },
} as const;

/** Readouts during warp, stepped at `MOMENTS.warp.velocity`. */
export const WARP_READOUTS = {
  velocity: ["1x", "10x", "100x", "1000x"],
  mcap: ["$4.2K", "$69K", "$1M", "$420M"],
} as const;

export const SWITCHES = [
  ["DIAMOND HANDS", "ENGAGED"],
  ["PAPER HANDS", "DISABLED"],
  ["RUG SHIELD", "ARMED"],
  ["FOMO", "MAX"],
] as const;

export const RADIO = [
  "Houston, we have a pump.",
  "Dev wallet sold. Ignore it.",
  "Ser, the chart.",
] as const;

export const ASTEROID_LABELS = ["RUG", "HONEYPOT", "-99%"] as const;

/** Camera shake amplitude in px, by phase; one-shot kicks add to it. */
export const SHAKE = {
  base: { seatbelt: 0, cockpit: 0, ignition: 1.5, warp: 2.5, approach: 1, landing: 0.5, reveal: 0, done: 0 },
  lockIn: 4,
  nearMiss: 14,
  touchdown: 10,
} as const;

/** What every layer is handed, once per animation frame. */
export type Frame = {
  /** Seconds since the intro began (after any skip jump). */
  t: number;
  /** Seconds since the previous frame, clamped to 0.1. */
  dt: number;
  phase: IntroPhase;
  /** Progress through the current phase, 0..1. */
  p: number;
  /** Which cut is playing: shapes what a layer may skip. */
  mode: "full" | "reduced";
};

export function totalSeconds(timeline: Timeline): number {
  return timeline.reduce((sum, [, s]) => sum + s, 0);
}

/** The phase and progress at `t` seconds; past the end is `done`. */
export function phaseAt(timeline: Timeline, t: number): { phase: IntroPhase; p: number } {
  let start = 0;
  for (const [phase, seconds] of timeline) {
    if (t < start + seconds) return { phase, p: seconds > 0 ? (t - start) / seconds : 1 };
    start += seconds;
  }
  return { phase: "done", p: 1 };
}

/** When a phase begins on a timeline, or null if that cut skips it. */
export function phaseStart(timeline: Timeline, phase: IntroPhase): number | null {
  let start = 0;
  for (const [name, seconds] of timeline) {
    if (name === phase) return start;
    start += seconds;
  }
  return null;
}
