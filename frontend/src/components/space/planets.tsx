"use client";

/* eslint-disable @next/next/no-img-element */

import type { CSSProperties } from "react";
import { useEffect, useState } from "react";

import { cn } from "@/lib/utils";

/**
 * Cartoon planets drifting behind the homepage and the sign-in pages
 * (Karthik, 2026-09-25, from his own planet sheet). Each one wanders its own
 * path, picked at random on every visit; after that it is pure CSS — transform
 * only, no per-frame JavaScript. Decorative, behind every word on the page.
 */
const PLANETS: ReadonlyArray<{ id: string; size: number; ringed?: boolean }> = [
  // The first seven are the ones a phone shows.
  { id: "ringed-blue", size: 132, ringed: true },
  { id: "giant-gold", size: 112 },
  { id: "earth", size: 86 },
  { id: "volcano-red", size: 94 },
  { id: "ringed-purple", size: 112, ringed: true },
  { id: "swirl-pink", size: 64 },
  { id: "moon-grey", size: 48 },
  { id: "banded-rainbow", size: 88 },
  { id: "ice-teal", size: 80 },
  { id: "ringed-green", size: 102, ringed: true },
  { id: "crater-orange", size: 70 },
  { id: "banded-peach", size: 72 },
  { id: "ringed-lime", size: 88, ringed: true },
  { id: "moon-blue", size: 42 },
  { id: "moons-grey", size: 56 },
  { id: "banded-small", size: 44 },
  { id: "rock-a", size: 26 },
  { id: "rock-b", size: 30 },
];

type Orbit = { id: string; ringed: boolean; style: CSSProperties };

function between(lo: number, hi: number): number {
  return lo + Math.random() * (hi - lo);
}

/** A start spread across the screen (one column each, shuffled, so they do
 *  not clump), three random waypoints, and a random pace. */
function plan(): Orbit[] {
  const columns = PLANETS.map((_, i) => i).sort(() => Math.random() - 0.5);
  return PLANETS.map((p, i) => {
    const wander = between(38, 80);
    return {
      id: p.id,
      ringed: !!p.ringed,
      style: {
        "--size": p.size,
        "--x": `${((columns[i]! + between(0.15, 0.85)) / PLANETS.length) * 100}%`,
        "--y": `${between(4, 88)}%`,
        "--x1": `${between(-16, 16)}vw`, "--y1": `${between(-14, 14)}vh`,
        "--x2": `${between(-16, 16)}vw`, "--y2": `${between(-14, 14)}vh`,
        "--x3": `${between(-16, 16)}vw`, "--y3": `${between(-14, 14)}vh`,
        "--wander": `${wander}s`,
        // Negative: each is already somewhere along its path on arrival.
        "--delay": `${-between(0, wander)}s`,
        "--spin": `${between(50, 120)}s`,
        "--spin-dir": Math.random() < 0.5 ? "normal" : "reverse",
      } as CSSProperties,
    };
  });
}

export function Planets({ className }: { className?: string }) {
  // Random on the client only, after mount: the server's render and the first
  // client render must be identical, so there is nothing to show until then.
  const [orbits, setOrbits] = useState<Orbit[] | null>(null);
  useEffect(() => setOrbits(plan()), []);
  if (!orbits) return null;

  return (
    <div className={cn("planets", className)} aria-hidden>
      {orbits.map((o) => (
        <div key={o.id} className="planets__body" style={o.style}>
          <img
            src={`/planets/${o.id}.webp`}
            alt=""
            draggable={false}
            className={cn("planets__img", o.ringed && "planets__img--ringed")}
          />
        </div>
      ))}
    </div>
  );
}
