"use client";

import { useCallback, useEffect, useSyncExternalStore } from "react";

/**
 * OBSERVATORY / COMMAND
 *
 * Two ways to look at the same instrument. Full carries the ambient depth;
 * Command strips every non-informational effect for someone who keeps this
 * open all day. Functionality is identical in both — only ornament changes.
 *
 * The mode lives on `document.documentElement` as a data attribute rather than
 * in React state, so switching costs one style recalculation instead of
 * re-rendering the tree. A tiny external store keeps components in sync
 * without a provider wrapping the app.
 */

export type DisplayMode = "full" | "compact";

const STORAGE_KEY = "memescope:mode";

const listeners = new Set<() => void>();

function currentMode(): DisplayMode {
  if (typeof document === "undefined") return "full";
  return document.documentElement.dataset.mode === "compact" ? "compact" : "full";
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function setDisplayMode(mode: DisplayMode): void {
  document.documentElement.dataset.mode = mode;
  try {
    window.localStorage.setItem(STORAGE_KEY, mode);
  } catch {
    // Private browsing or a full quota — the mode still applies for this
    // session, it just will not survive a reload.
  }
  listeners.forEach((listener) => listener());
}

export function useDisplayMode() {
  const mode = useSyncExternalStore(
    subscribe,
    currentMode,
    // Server render always assumes Full; the inline boot script in the
    // document head corrects it before first paint, so there is no flash.
    () => "full" as DisplayMode,
  );

  // Restore the persisted choice once on mount, in case the boot script was
  // stripped (older browsers, strict CSP) — belt and braces.
  useEffect(() => {
    try {
      const stored = window.localStorage.getItem(STORAGE_KEY);
      if (stored === "compact" || stored === "full") {
        if (currentMode() !== stored) setDisplayMode(stored);
      }
    } catch {
      /* ignore */
    }
  }, []);

  const toggle = useCallback(() => {
    setDisplayMode(currentMode() === "compact" ? "full" : "compact");
  }, []);

  return { mode, toggle, setMode: setDisplayMode };
}

/**
 * Runs before first paint to apply the stored mode, preventing a flash of
 * Full atmosphere for a user who chose Command.
 */
export const MODE_BOOT_SCRIPT = `(function(){try{var m=localStorage.getItem("${STORAGE_KEY}");document.documentElement.dataset.mode=m==="compact"?"compact":"full"}catch(e){document.documentElement.dataset.mode="full"}})()`;
