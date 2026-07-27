"use client";

import { useEffect, useState } from "react";

/**
 * Reduced motion is a hard requirement, not a nicety: this interface animates
 * constantly, and for a vestibular-sensitive user that is the difference
 * between a product and a hazard.
 *
 * CSS handles the ambient layer via a media query. This hook exists for the
 * cases CSS cannot reach — counting numbers, staggered reveals, canvas loops —
 * where the animation must not merely be fast but must not run at all.
 */
export function useReducedMotion(): boolean {
  const [reduced, setReduced] = useState(false);

  useEffect(() => {
    const query = window.matchMedia("(prefers-reduced-motion: reduce)");
    setReduced(query.matches);

    const onChange = (event: MediaQueryListEvent) => setReduced(event.matches);
    query.addEventListener("change", onChange);
    return () => query.removeEventListener("change", onChange);
  }, []);

  return reduced;
}
