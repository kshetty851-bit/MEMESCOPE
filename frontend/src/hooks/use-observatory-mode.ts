"use client";

import { useCallback, useEffect, useSyncExternalStore } from "react";

/**
 * OBSERVATORY / COMMAND
 *
 * Two ways to look at the same instrument. Observatory is the full atmosphere;
 * Command strips every non-informational effect for someone who keeps this
 * open all day. Functionality is identical in both — only ornament changes.
 *
 * The mode lives on `document.documentElement` as a data attribute rather than
 * in React state, so switching costs one style recalculation instead of
 * re-rendering the tree. A tiny external store keeps components in sync
 * without a provider wrapping the app.
 */

export type ObservatoryMode = "observatory" | "command";

const STORAGE_KEY = "memescope:mode";

const listeners = new Set<() => void>();

function currentMode(): ObservatoryMode {
  if (typeof document === "undefined") return "observatory";
  return document.documentElement.dataset.mode === "command" ? "command" : "observatory";
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function setObservatoryMode(mode: ObservatoryMode): void {
  document.documentElement.dataset.mode = mode;
  try {
    window.localStorage.setItem(STORAGE_KEY, mode);
  } catch {
    // Private browsing or a full quota — the mode still applies for this
    // session, it just will not survive a reload.
  }
  listeners.forEach((listener) => listener());
}

export function useObservatoryMode() {
  const mode = useSyncExternalStore(
    subscribe,
    currentMode,
    // Server render always assumes Observatory; the inline boot script in the
    // document head corrects it before first paint, so there is no flash.
    () => "observatory" as ObservatoryMode,
  );

  // Restore the persisted choice once on mount, in case the boot script was
  // stripped (older browsers, strict CSP) — belt and braces.
  useEffect(() => {
    try {
      const stored = window.localStorage.getItem(STORAGE_KEY);
      if (stored === "command" || stored === "observatory") {
        if (currentMode() !== stored) setObservatoryMode(stored);
      }
    } catch {
      /* ignore */
    }
  }, []);

  const toggle = useCallback(() => {
    setObservatoryMode(currentMode() === "command" ? "observatory" : "command");
  }, []);

  return { mode, toggle, setMode: setObservatoryMode };
}

/**
 * Runs before first paint to apply the stored mode, preventing a flash of
 * Observatory atmosphere for a user who chose Command.
 */
export const MODE_BOOT_SCRIPT = `(function(){try{var m=localStorage.getItem("${STORAGE_KEY}");document.documentElement.dataset.mode=m==="command"?"command":"observatory"}catch(e){document.documentElement.dataset.mode="observatory"}})()`;
