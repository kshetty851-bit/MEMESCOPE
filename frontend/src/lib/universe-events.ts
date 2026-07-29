/**
 * UNIVERSE EVENT BUS
 *
 * The background reacts to real blockchain activity. Pages that hold live data
 * emit events; the Universe subscribes once and renders them.
 *
 * A module-level emitter rather than React context on purpose: the Universe is
 * fixed behind every screen and must not re-render when a page updates, and a
 * context provider high enough to reach it would re-render the entire tree on
 * every discovery. This costs one subscription and zero renders above the
 * component that actually draws.
 */

export type UniverseEventType = "discovery" | "whale" | "elite" | "threat";

export interface UniverseEvent {
  type: UniverseEventType;
  /** Monotonic id so a repeated event of the same type still animates. */
  id: number;
  /** Optional label, surfaced in the Observatory Log. */
  detail?: string;
}

type Listener = (event: UniverseEvent) => void;

const listeners = new Set<Listener>();
let counter = 0;

export function emitUniverseEvent(type: UniverseEventType, detail?: string): UniverseEvent {
  counter += 1;
  const event: UniverseEvent = { type, id: counter, detail };
  listeners.forEach((listener) => listener(event));
  return event;
}

export function onUniverseEvent(listener: Listener): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/**
 * Ambient activity level, 0–1.
 *
 * Drives particle count, data-stream density and Core energy. Kept in a plain
 * module variable with a subscription rather than state: it changes on every
 * market tick and nothing above the Universe needs to re-render for it.
 */
let activity = 0.25;
const activityListeners = new Set<(value: number) => void>();

export function setUniverseActivity(value: number): void {
  const clamped = Math.max(0, Math.min(1, value));
  // Ignore imperceptible changes so a jittery feed does not thrash styles.
  if (Math.abs(clamped - activity) < 0.02) return;
  activity = clamped;
  activityListeners.forEach((listener) => listener(clamped));
}

export function getUniverseActivity(): number {
  return activity;
}

export function onUniverseActivity(listener: (value: number) => void): () => void {
  activityListeners.add(listener);
  return () => activityListeners.delete(listener);
}
