/**
 * WHAT MOVES ON THE RADAR, AND WHY
 *
 * One authored moment: **the reorder**. The Radar's ranking *is* its opinion,
 * so a token climbing from #6 to #3 is the product changing its mind while
 * someone watches. That transition carries meaning and earns a real
 * transform. Everything else here is quiet feedback — a value arrived, and the
 * eye needs to know which one without hunting.
 *
 * What is deliberately *not* animated:
 *
 *  - **Peak, detected, and every historical figure.** They cannot change, so
 *    motion there would imply they might. The same rule the freshness layer
 *    follows.
 *  - **Score.** It moves on a fifteen-minute sweep, not on a tick; flashing it
 *    at poll cadence would suggest a liveness the model does not have.
 *  - **Anything on first paint.** Rows arrive already visible. A staggered
 *    entrance on every load is a page announcing itself, and this one has
 *    nothing to announce.
 *
 * Pure and framework-free: durations and easings resolve to the design
 * system's own tokens so motion cannot drift from the rest of the interface.
 */

/** Reads the project's tokens rather than restating them. */
export const MOTION = {
  /** Value changed. Fast enough to read as acknowledgement, not as latency. */
  flash: 180,
  /** A row moving to a new rank. Distance implies a longer arc. */
  reorder: 260,
  /** Leaving is quicker than arriving — an exit should not be dwelt on. */
  exit: 160,
  enter: 220,
  /** The design system's exponential ease-out. Never bounce. */
  ease: "var(--ease-instrument)",
} as const;

export type Direction = "up" | "down" | "none";

/**
 * Which way a numeric string moved.
 *
 * Takes the raw decimal strings the API serves — comparing formatted output
 * would miss a change too small to render and flash on a rounding artefact
 * that never happened.
 */
export function directionOf(
  previous: string | null | undefined,
  next: string | null | undefined,
): Direction {
  if (previous === null || previous === undefined) return "none";
  if (next === null || next === undefined) return "none";
  if (previous === next) return "none";

  const before = Number(previous);
  const after = Number(next);
  if (!Number.isFinite(before) || !Number.isFinite(after)) return "none";
  if (after === before) return "none";
  return after > before ? "up" : "down";
}

/**
 * Whether the viewer has asked for less motion.
 *
 * Checked in JS as well as CSS because the FLIP reorder is driven from script:
 * a transform applied imperatively would ignore the stylesheet's
 * `prefers-reduced-motion` block entirely.
 */
export function prefersReducedMotion(): boolean {
  if (typeof window === "undefined" || !window.matchMedia) return false;
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

/**
 * Rank movement between two orderings, keyed by identity.
 *
 * Returns places moved: positive is a climb. Used to label the change for
 * screen readers, which get the fact in words while sighted users get it as
 * movement — the same information through two channels rather than one channel
 * and a decoration.
 */
export function rankDeltas(
  previous: string[],
  next: string[],
): Map<string, number> {
  const before = new Map(previous.map((id, index) => [id, index]));
  const deltas = new Map<string, number>();

  next.forEach((id, index) => {
    const was = before.get(id);
    if (was === undefined) return; // New arrival: not a move.
    if (was !== index) deltas.set(id, was - index);
  });

  return deltas;
}

/** "climbed 3 places" / "fell 1 place". Screen-reader text, so it is spelled out. */
export function describeMove(delta: number): string {
  const places = Math.abs(delta);
  const noun = places === 1 ? "place" : "places";
  return delta > 0 ? `climbed ${places} ${noun}` : `fell ${places} ${noun}`;
}
