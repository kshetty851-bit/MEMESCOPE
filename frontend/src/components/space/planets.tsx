"use client";

/* eslint-disable @next/next/no-img-element */

import type { CSSProperties } from "react";
import { useEffect, useState } from "react";

import { cn } from "@/lib/utils";

/**
 * Cartoon planets drifting behind the homepage and the sign-in pages
 * (Karthik, 2026-09-25, from his own planet sheet). Each one wanders its own
 * patch of sky (see `plan`), picked at random on every visit; after that it is
 * pure CSS — transform only, no per-frame JavaScript. Decorative, behind every
 * word on the page.
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

/** A phone shows the first seven, at 0.6 size (the CSS below 640px). */
const PHONE = 640;

/**
 * NO TWO PLANETS EVER TOUCH (Karthik, 2026-09-27: "some planets colliding
 * with each other, I don't want that"). The screen is cut into a grid with a
 * cell per planet; each planet sits somewhere in its own cell and wanders only
 * inside it, so their paths cannot cross. Cells are shuffled every visit, so
 * the sky still looks different each time.
 */
export function plan(width: number, height: number): Orbit[] {
  const phone = width <= PHONE;
  const shown = phone ? PLANETS.slice(0, 7) : PLANETS;
  const scale = phone ? 0.6 : 1;
  const cols = Math.max(1, Math.round(Math.sqrt((shown.length * width) / height)));
  const rows = Math.ceil(shown.length / cols);
  const cellW = width / cols;
  const cellH = height / rows;
  const cells = Array.from({ length: cols * rows }, (_, i) => i).sort(() => Math.random() - 0.5);
  return shown.map((p, i) => {
    const size = p.size * scale;
    // Room to move without leaving the cell; half for where it sits, half to wander.
    const roomX = Math.max(0, (cellW - size) / 2 - 6);
    const roomY = Math.max(0, (cellH - size) / 2 - 6);
    const cell = cells[i]!;
    const cx = ((cell % cols) + 0.5) * cellW + between(-roomX, roomX) / 2;
    const cy = (Math.floor(cell / cols) + 0.5) * cellH + between(-roomY, roomY) / 2;
    const step = () => ({ x: `${between(-roomX, roomX) / 2}px`, y: `${between(-roomY, roomY) / 2}px` });
    const [w1, w2, w3] = [step(), step(), step()];
    const wander = between(38, 80);
    return {
      id: p.id,
      ringed: !!p.ringed,
      style: {
        "--size": p.size,
        "--x": `${cx - size / 2}px`,
        "--y": `${cy - size / 2}px`,
        "--x1": w1.x, "--y1": w1.y,
        "--x2": w2.x, "--y2": w2.y,
        "--x3": w3.x, "--y3": w3.y,
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
  useEffect(() => {
    const lay = () => setOrbits(plan(window.innerWidth, window.innerHeight));
    lay();
    // A new grid for a new window size, so cells never overlap after a resize.
    let timer = 0;
    const onResize = () => {
      window.clearTimeout(timer);
      timer = window.setTimeout(lay, 300);
    };
    window.addEventListener("resize", onResize);
    return () => {
      window.removeEventListener("resize", onResize);
      window.clearTimeout(timer);
    };
  }, []);
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
