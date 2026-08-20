"use client";

import { useEffect, useState } from "react";

import { phaseOfDay, type DayPhase } from "@/lib/hq/ambient";

/**
 * THE THREE THINGS EVERY HQ SURFACE NEEDS TO KNOW.
 *
 * Whether motion is allowed, whether the tab is visible, and what time it is.
 * Shared by the isometric stage and the mobile card stack so the two cannot
 * disagree — a phone showing a daylit room while the desktop shows night would
 * be a small bug with a very odd smell.
 *
 * These are deliberately *not* in `lib/hq`: they touch `window` and `document`
 * and belong with the components, so the pure layout and roster modules stay
 * testable as data.
 */

/**
 * Whether motion may run.
 *
 * Starts `false` and is raised only after the media query has been read, so
 * the window between first paint and hydration is still rather than animated.
 * A reader who asked for reduced motion never sees a frame of movement.
 */
export function useHqMotion(): boolean {
  const [allowed, setAllowed] = useState(false);

  useEffect(() => {
    const query = window.matchMedia("(prefers-reduced-motion: reduce)");
    const apply = () => setAllowed(!query.matches);
    apply();
    query.addEventListener("change", apply);
    return () => query.removeEventListener("change", apply);
  }, []);

  return allowed;
}

/** Halt everything when the tab is hidden. One listener for the whole surface. */
export function useHqPaused(): boolean {
  const [paused, setPaused] = useState(false);

  useEffect(() => {
    const onChange = () => setPaused(document.hidden);
    onChange();
    document.addEventListener("visibilitychange", onChange);
    return () => document.removeEventListener("visibilitychange", onChange);
  }, []);

  return paused;
}

/**
 * Day, evening or night, from the browser clock.
 *
 * Re-read every ten minutes. Not every second: the only thing that changes is
 * a lighting token, and the difference between a boundary landing at 17:00:03
 * and at 17:09:00 is invisible. A cheap timer that is almost always a no-op is
 * still a timer, and this one is the cheapest version that is correct.
 *
 * `day` until the first read, matching the server: the phase is a theme, and
 * flashing from night to day on hydration would be worse than a beat of the
 * wrong one.
 */
export function useDayPhase(): DayPhase {
  const [phase, setPhase] = useState<DayPhase>("day");

  useEffect(() => {
    const read = () => setPhase(phaseOfDay(new Date().getHours()));
    read();
    const handle = setInterval(read, 10 * 60 * 1000);
    return () => clearInterval(handle);
  }, []);

  return phase;
}
