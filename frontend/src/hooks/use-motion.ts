"use client";

import { useEffect, useLayoutEffect, useRef, useState } from "react";

import {
  MOTION,
  directionOf,
  prefersReducedMotion,
  type Direction,
} from "@/lib/motion";

/**
 * The two hooks the Radar's motion needs, and no more.
 *
 * Both are driven from data the page already holds — no timers polling for
 * change, no observers on the DOM. A value moved or it did not.
 */

/**
 * Flash a direction when a value changes.
 *
 * Returns `"up"` or `"down"` for one `MOTION.flash` window, then clears. The
 * comparison is on the raw decimal string, so a change too small to render
 * does not flash and a rounding artefact never fires.
 *
 * Deliberately does **not** fire on first render. A page load is not a price
 * move, and lighting up ten rows on arrival would teach the eye to ignore the
 * signal exactly when it starts meaning something.
 */
export function useChangeFlash(value: string | null | undefined): Direction {
  const previous = useRef<string | null | undefined>(undefined);
  const seeded = useRef(false);
  const [flash, setFlash] = useState<Direction>("none");

  useEffect(() => {
    if (!seeded.current) {
      seeded.current = true;
      previous.current = value;
      return;
    }

    const direction = directionOf(previous.current, value);
    previous.current = value;
    if (direction === "none") return;

    setFlash(direction);
    const id = window.setTimeout(() => setFlash("none"), MOTION.flash);
    return () => window.clearTimeout(id);
  }, [value]);

  return flash;
}

/**
 * FLIP: move rows to their new rank from where they used to be.
 *
 * The list is re-rendered in its new order, then each row that moved is
 * transformed back to its old position and released. The browser animates a
 * transform rather than a layout property, so a reorder costs no reflow per
 * frame.
 *
 * Runs in `useLayoutEffect` because the correction must be applied before the
 * browser paints the new order — one frame of rows in their final position is
 * the jump this exists to prevent.
 *
 * Honours `prefers-reduced-motion` in script, not only in CSS: an imperative
 * transform would sail straight past the stylesheet's own block.
 */
export function useFlipOrder(keys: string[]) {
  const nodes = useRef(new Map<string, HTMLElement>());
  const positions = useRef(new Map<string, number>());

  const register = (key: string) => (node: HTMLElement | null) => {
    if (node) nodes.current.set(key, node);
    else nodes.current.delete(key);
  };

  useLayoutEffect(() => {
    const previous = positions.current;
    const next = new Map<string, number>();

    for (const [key, node] of nodes.current) {
      next.set(key, node.getBoundingClientRect().top);
    }

    if (previous.size > 0 && !prefersReducedMotion()) {
      for (const [key, node] of nodes.current) {
        const was = previous.get(key);
        const now = next.get(key);
        if (was === undefined || now === undefined) continue;

        const shift = was - now;
        // Sub-pixel drift is not a rank change; animating it would make a
        // resize look like the ranking moved.
        if (Math.abs(shift) < 1) continue;

        node.style.transition = "none";
        node.style.transform = `translateY(${shift}px)`;

        // Two frames: one for the browser to accept the offset, one to
        // release it. A single frame is coalesced and nothing animates.
        requestAnimationFrame(() => {
          requestAnimationFrame(() => {
            node.style.transition = `transform ${MOTION.reorder}ms ${MOTION.ease}`;
            node.style.transform = "";
          });
        });
      }
    }

    positions.current = next;
  }, [keys]);

  return register;
}
