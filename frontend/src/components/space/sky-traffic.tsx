"use client";

import type { CSSProperties } from "react";
import { useEffect, useState } from "react";

/**
 * SKY TRAFFIC (Karthik, 2026-09-27: "small rockets, satellites flying here and
 * there, also aliens"). One small craft crosses the sky every few seconds —
 * a rocket, a satellite or a flying saucer with an alien in it — on its own
 * random line, and never more than three at once, so the sky stays calm.
 * Each flight is one CSS animation on transform; nothing moves for a reader
 * who asked for less motion.
 */

type Kind = "rocket" | "satellite" | "ufo";
type Craft = { id: number; kind: Kind; style: CSSProperties };

const MAX_AT_ONCE = 3;

function between(lo: number, hi: number): number {
  return lo + Math.random() * (hi - lo);
}

export function flight(id: number, kind: Kind): Craft {
  const rightward = Math.random() < 0.5;
  const fy = between(8, 72);
  const ty = Math.min(85, Math.max(4, fy + between(-18, 18)));
  const fx = rightward ? -12 : 112;
  const tx = rightward ? 112 : -12;
  // Rockets point where they fly; the drawing points up.
  const angle = (Math.atan2((ty - fy) * 0.6, tx - fx) * 180) / Math.PI + 90;
  return {
    id,
    kind,
    style: {
      "--fx": `${fx}vw`, "--fy": `${fy}vh`, "--tx": `${tx}vw`, "--ty": `${ty}vh`,
      "--turn": `${angle}deg`,
      "--flip": rightward ? 1 : -1,
      "--dur": `${kind === "rocket" ? between(9, 14) : between(18, 28)}s`,
      "--size": `${kind === "ufo" ? between(66, 84) : kind === "rocket" ? between(46, 58) : between(56, 72)}px`,
    } as CSSProperties,
  };
}

export function SkyTraffic() {
  const [crafts, setCrafts] = useState<Craft[]>([]);

  useEffect(() => {
    if (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) return;
    let next = 0;
    let timer = 0;
    const kinds: Kind[] = ["rocket", "satellite", "ufo"];
    const launch = () => {
      setCrafts((now) =>
        now.length >= MAX_AT_ONCE
          ? now
          : [...now, flight(next++, kinds[Math.floor(Math.random() * kinds.length)]!)],
      );
      timer = window.setTimeout(launch, between(5000, 9000));
    };
    timer = window.setTimeout(launch, 1500);
    return () => window.clearTimeout(timer);
  }, []);

  const land = (id: number) => setCrafts((now) => now.filter((c) => c.id !== id));

  return (
    <div className="sky-traffic" aria-hidden>
      {crafts.map((c) => (
        <div
          key={c.id}
          className={`sky-craft sky-craft--${c.kind}`}
          style={c.style}
          onAnimationEnd={(e) => {
            if (e.target === e.currentTarget) land(c.id);
          }}
        >
          <div className="sky-craft__art">
            {c.kind === "rocket" ? <MiniRocket /> : c.kind === "satellite" ? <MiniSatellite /> : <Saucer />}
          </div>
        </div>
      ))}
    </div>
  );
}

function MiniRocket() {
  return (
    <svg viewBox="0 0 40 80" width="100%" height="100%">
      <path d="M20 2 C 30 14, 32 34, 30 54 L 10 54 C 8 34, 10 14, 20 2 Z" fill="#f2f4f8" />
      <path d="M20 2 C 26 9, 28 16, 29 22 L 11 22 C 12 16, 14 9, 20 2 Z" fill="#e5484d" />
      <circle cx="20" cy="33" r="6" fill="#4cc3ff" stroke="#9aa7bd" strokeWidth="2" />
      <path d="M10 42 L 2 58 L 10 54 Z M30 42 L 38 58 L 30 54 Z" fill="#e5484d" />
      <path className="sky-craft__flame" d="M13 54 C 14 66, 20 78, 20 78 C 20 78, 26 66, 27 54 Z" fill="#ffb347" />
      <path d="M16 54 C 17 62, 20 70, 20 70 C 20 70, 23 62, 24 54 Z" fill="#fff1b8" />
    </svg>
  );
}

function MiniSatellite() {
  return (
    <svg viewBox="0 0 80 40" width="100%" height="100%">
      <rect x="2" y="12" width="24" height="16" rx="2" fill="#3a6fd8" stroke="#9fc0ff" strokeWidth="1.5" />
      <path d="M8 12 V28 M14 12 V28 M20 12 V28" stroke="#9fc0ff" strokeWidth="1" />
      <rect x="54" y="12" width="24" height="16" rx="2" fill="#3a6fd8" stroke="#9fc0ff" strokeWidth="1.5" />
      <path d="M60 12 V28 M66 12 V28 M72 12 V28" stroke="#9fc0ff" strokeWidth="1" />
      <rect x="26" y="19" width="28" height="2" fill="#b8c2d6" />
      <rect x="31" y="10" width="18" height="20" rx="4" fill="#dfe5f0" stroke="#9aa7bd" strokeWidth="1.5" />
      <path d="M40 10 L 40 3" stroke="#9aa7bd" strokeWidth="1.5" />
      <circle className="sky-craft__blink" cx="40" cy="3" r="2.2" fill="#ff5d5d" />
    </svg>
  );
}

function Saucer() {
  return (
    <svg viewBox="0 0 80 60" width="100%" height="100%">
      <path className="sky-craft__beam" d="M28 40 L 18 60 L 62 60 L 52 40 Z" fill="rgb(160 255 190 / 0.18)" />
      {/* the alien, in its dome */}
      <path d="M24 30 C 24 14, 56 14, 56 30 Z" fill="rgb(180 230 255 / 0.35)" stroke="#bfe6ff" strokeWidth="1.5" />
      <ellipse cx="40" cy="25" rx="8" ry="7" fill="#7ee07a" />
      <path d="M34 19 L 31 12 M46 19 L 49 12" stroke="#7ee07a" strokeWidth="2" strokeLinecap="round" />
      <circle cx="31" cy="12" r="2" fill="#7ee07a" />
      <circle cx="49" cy="12" r="2" fill="#7ee07a" />
      <ellipse cx="37" cy="24" rx="2.2" ry="3" fill="#10202a" />
      <ellipse cx="43" cy="24" rx="2.2" ry="3" fill="#10202a" />
      <path d="M37 29 Q 40 31 43 29" stroke="#10202a" strokeWidth="1.2" fill="none" strokeLinecap="round" />
      {/* the saucer */}
      <ellipse cx="40" cy="34" rx="32" ry="9" fill="#9aa7bd" />
      <ellipse cx="40" cy="31" rx="30" ry="6" fill="#c7d0de" />
      <circle className="sky-craft__blink" cx="18" cy="36" r="2" fill="#ffd166" />
      <circle className="sky-craft__blink" cx="40" cy="39" r="2" fill="#7ee0ff" />
      <circle className="sky-craft__blink" cx="62" cy="36" r="2" fill="#ffd166" />
    </svg>
  );
}
