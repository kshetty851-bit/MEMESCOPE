"use client";

import { useCallback, useEffect, useSyncExternalStore } from "react";

/**
 * How much universe to run.
 *
 * Third preference to follow this exact pattern, after `use-display-mode` and
 * `use-nav-rail`: the value lives as a data attribute on `<html>`, CSS resolves
 * it, and a boot script applies it before first paint. Deliberately not a
 * fourth mechanism — one way to persist a UI preference is enough.
 *
 * It is also deliberately *not* a motion preference. `prefers-reduced-motion`
 * already governs whether anything moves, at the OS level, and `universe.css`
 * honours it unconditionally. This governs how much *scene* there is, which is
 * a taste question rather than an accessibility one, and the two compose: a
 * reduced-motion user on `full` gets the whole static sky with none of the
 * traffic.
 */

export type SpaceIntensity = "full" | "minimal" | "off";

const STORAGE_KEY = "memescope:space";

const listeners = new Set<() => void>();

function current(): SpaceIntensity {
  if (typeof document === "undefined") return "full";
  const value = document.documentElement.dataset.space;
  return value === "minimal" || value === "off" ? value : "full";
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function setSpaceIntensity(value: SpaceIntensity): void {
  document.documentElement.dataset.space = value;
  try {
    window.localStorage.setItem(STORAGE_KEY, value);
  } catch {
    // Private browsing or a full quota. The choice still applies this session.
  }
  listeners.forEach((listener) => listener());
}

export function useSpaceIntensity() {
  const intensity = useSyncExternalStore(
    subscribe,
    current,
    () => "full" as SpaceIntensity,
  );

  useEffect(() => {
    try {
      const stored = window.localStorage.getItem(STORAGE_KEY);
      if (
        (stored === "full" || stored === "minimal" || stored === "off") &&
        current() !== stored
      ) {
        setSpaceIntensity(stored);
      }
    } catch {
      /* ignore */
    }
  }, []);

  const set = useCallback((value: SpaceIntensity) => setSpaceIntensity(value), []);

  return { intensity, set };
}

/** Applied before first paint, so the sky never changes density after hydration. */
export const SPACE_BOOT_SCRIPT = `(function(){try{var s=localStorage.getItem("${STORAGE_KEY}");document.documentElement.dataset.space=(s==="minimal"||s==="off")?s:"full"}catch(e){document.documentElement.dataset.space="full"}})()`;
