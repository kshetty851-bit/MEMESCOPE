"use client";

import { useEffect } from "react";

/**
 * POINTER PARALLAX — one listener, one frame loop, zero React renders.
 *
 * The whole effect is two CSS custom properties written onto `<html>`:
 *
 *     --uv-px   -1 … 1   pointer offset from centre, horizontal
 *     --uv-py   -1 … 1   vertical
 *
 * Every layer in `universe.css` multiplies those by its own depth factor. So a
 * scene with twenty objects still costs **one** listener and **one** rAF, and
 * React never re-renders — the alternative (state per object, or a listener per
 * object) is the thing this exists to avoid.
 *
 * Deliberately switched off for:
 *
 *   - touch devices — there is no pointer to follow, and a phone should not be
 *     running a frame loop for decoration;
 *   - `prefers-reduced-motion` — parallax is vestibular motion, and among the
 *     most provoking kinds because it is coupled to the user's own hand;
 *   - `data-space="minimal"` and `"off"` — focus modes.
 *
 * Movement is intentionally tiny. The universe should breathe when the pointer
 * moves, not chase it.
 */

const MAX_HZ = 1000 / 60;

export function PointerParallax() {
  useEffect(() => {
    const root = document.documentElement;

    const coarse = window.matchMedia("(pointer: coarse)");
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)");

    let frame = 0;
    let last = 0;
    let targetX = 0;
    let targetY = 0;
    let currentX = 0;
    let currentY = 0;
    let running = false;

    const allowed = () =>
      !coarse.matches && !reduced.matches && root.dataset.space === "full";

    const tick = (now: number) => {
      if (now - last < MAX_HZ) {
        frame = requestAnimationFrame(tick);
        return;
      }
      last = now;

      // Ease toward the pointer rather than snapping to it. A hard follow reads
      // as the page being dragged; this reads as depth.
      currentX += (targetX - currentX) * 0.06;
      currentY += (targetY - currentY) * 0.06;

      root.style.setProperty("--uv-px", currentX.toFixed(4));
      root.style.setProperty("--uv-py", currentY.toFixed(4));

      // Stop the loop once it has effectively settled. An idle pointer should
      // not keep a frame callback alive behind a scrolling table.
      if (Math.abs(targetX - currentX) < 0.001 && Math.abs(targetY - currentY) < 0.001) {
        running = false;
        return;
      }
      frame = requestAnimationFrame(tick);
    };

    const start = () => {
      if (running) return;
      running = true;
      frame = requestAnimationFrame(tick);
    };

    const onPointerMove = (event: PointerEvent) => {
      if (!allowed()) return;
      targetX = (event.clientX / window.innerWidth) * 2 - 1;
      targetY = (event.clientY / window.innerHeight) * 2 - 1;
      start();
    };

    const settle = () => {
      targetX = 0;
      targetY = 0;
      start();
    };

    window.addEventListener("pointermove", onPointerMove, { passive: true });
    // Leaving the window returns the scene to centre instead of freezing it
    // mid-offset, which would read as a layout bug.
    window.addEventListener("pointerleave", settle);
    window.addEventListener("blur", settle);

    return () => {
      window.removeEventListener("pointermove", onPointerMove);
      window.removeEventListener("pointerleave", settle);
      window.removeEventListener("blur", settle);
      cancelAnimationFrame(frame);
      root.style.removeProperty("--uv-px");
      root.style.removeProperty("--uv-py");
    };
  }, []);

  return null;
}
