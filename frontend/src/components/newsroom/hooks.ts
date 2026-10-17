"use client";

import { useQuery } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { API_V1 } from "@/lib/env";

import type { Newsroom, Story } from "./types";

async function fetchNewsroom(): Promise<Newsroom> {
  const r = await fetch(`${API_V1}/newsroom`, { cache: "no-store" });
  if (!r.ok) throw new Error(`Newsroom unavailable (${r.status})`);
  return r.json();
}

/**
 * The live bundle, polled every minute. Numbers update in place; stories do
 * not: new ones wait behind `apply()` so nothing moves under the reader.
 */
export function useNewsroom() {
  const q = useQuery({ queryKey: ["newsroom"], queryFn: fetchNewsroom, refetchInterval: 60_000,
                       refetchIntervalInBackground: false, staleTime: 30_000, retry: 2 });
  const [held, setHeld] = useState<Story[] | null>(null);
  const fresh = q.data?.stories;
  useEffect(() => { if (fresh && held === null) setHeld(fresh); }, [fresh, held]);
  const pending = useMemo(() => {
    if (!fresh || !held) return 0;
    const seen = new Set(held.map((s) => s.id));
    return fresh.filter((s) => !seen.has(s.id)).length;
  }, [fresh, held]);
  const apply = useCallback(() => { if (fresh) setHeld(fresh); }, [fresh]);
  return { ...q, stories: held ?? fresh ?? [], pending, apply };
}

/** A clock that ticks every `ms`; components that show countdowns use 1 s. */
export function useNow(ms = 30_000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), ms);
    return () => clearInterval(t);
  }, [ms]);
  return now;
}

const VISIT = "np:last-visit";
export interface LastVisit { at: string; btc: number | null }

/** The previous visit (read once), and this one saved whenever the tab is left. */
export function useLastVisit(btc: number | null | undefined): LastVisit | null {
  // The visit before this session, frozen for the whole session: switching
  // tabs saves this visit's state but must not become "your last visit".
  const [prev] = useState<LastVisit | null>(() => {
    if (typeof window === "undefined") return null;
    try {
      const held = sessionStorage.getItem(VISIT);
      if (held !== null) return JSON.parse(held);
      const stored = localStorage.getItem(VISIT);
      sessionStorage.setItem(VISIT, stored ?? "null");
      return JSON.parse(stored || "null");
    } catch { return null; }
  });
  const latest = useRef(btc);
  latest.current = btc;
  useEffect(() => {
    const save = () => {
      try { localStorage.setItem(VISIT, JSON.stringify({ at: new Date().toISOString(), btc: latest.current ?? null })); } catch { /* private mode */ }
    };
    const onHide = () => { if (document.visibilityState === "hidden") save(); };
    document.addEventListener("visibilitychange", onHide);
    window.addEventListener("pagehide", save);
    return () => { document.removeEventListener("visibilitychange", onHide); window.removeEventListener("pagehide", save); };
  }, []);
  return prev;
}

const WATCH = "np:watchlist";
export function useWatchlist() {
  const [ids, setIds] = useState<string[]>([]);
  useEffect(() => {
    try { setIds(JSON.parse(localStorage.getItem(WATCH) || "[]")); } catch { setIds([]); }
  }, []);
  const toggle = useCallback((id: string) => {
    setIds((cur) => {
      const next = cur.includes(id) ? cur.filter((x) => x !== id) : [...cur, id].slice(-12);
      try { localStorage.setItem(WATCH, JSON.stringify(next)); } catch { /* private mode */ }
      return next;
    });
  }, []);
  return { ids, toggle, has: (id: string) => ids.includes(id) };
}

/** Adds `is-in` once when the element first enters the viewport. */
export function useRevealOnce<T extends HTMLElement>() {
  const ref = useRef<T | null>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el || typeof IntersectionObserver === "undefined") { el?.classList.add("is-in"); return; }
    const io = new IntersectionObserver((entries) => {
      for (const e of entries) if (e.isIntersecting) { e.target.classList.add("is-in"); io.disconnect(); }
    }, { rootMargin: "0px 0px -8% 0px" });
    io.observe(el);
    return () => io.disconnect();
  }, []);
  return ref;
}
