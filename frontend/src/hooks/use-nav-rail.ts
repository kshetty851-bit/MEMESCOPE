"use client";

import { useCallback, useEffect, useSyncExternalStore } from "react";

/**
 * Rail expanded / collapsed.
 *
 * Deliberately modelled on `use-display-mode`: the state lives as a data
 * attribute on `<html>` and the width is resolved in CSS, so collapsing costs
 * one style recalculation rather than a re-render of the shell, and a reload
 * does not flash a 216px rail at someone who chose 56px.
 *
 * Following the existing pattern rather than inventing a second one is the
 * whole point — two mechanisms for "a persisted UI preference on the document
 * element" would be one too many.
 */

export type RailState = "expanded" | "collapsed";

const STORAGE_KEY = "memescope:rail";

const listeners = new Set<() => void>();

function current(): RailState {
  if (typeof document === "undefined") return "expanded";
  return document.documentElement.dataset.rail === "collapsed" ? "collapsed" : "expanded";
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function setRailState(state: RailState): void {
  document.documentElement.dataset.rail = state;
  try {
    window.localStorage.setItem(STORAGE_KEY, state);
  } catch {
    // Private browsing or a full quota. The choice still applies this session.
  }
  listeners.forEach((listener) => listener());
}

export function useNavRail() {
  const state = useSyncExternalStore(
    subscribe,
    current,
    () => "expanded" as RailState,
  );

  useEffect(() => {
    try {
      const stored = window.localStorage.getItem(STORAGE_KEY);
      if ((stored === "collapsed" || stored === "expanded") && current() !== stored) {
        setRailState(stored);
      }
    } catch {
      /* ignore */
    }
  }, []);

  const toggle = useCallback(() => {
    setRailState(current() === "collapsed" ? "expanded" : "collapsed");
  }, []);

  return { state, collapsed: state === "collapsed", toggle };
}

/** Applied before first paint, so the rail never resizes after hydration. */
export const RAIL_BOOT_SCRIPT = `(function(){try{var r=localStorage.getItem("${STORAGE_KEY}");document.documentElement.dataset.rail=r==="collapsed"?"collapsed":"expanded"}catch(e){document.documentElement.dataset.rail="expanded"}})()`;
