"use client";

import { useMemo } from "react";

import { useReducedMotion } from "@/hooks/use-reduced-motion";
import { cn } from "@/lib/utils";

/**
 * The blockchain field: the living substrate behind every screen.
 *
 * A sparse constellation of nodes joined by hairlines, drifting slowly. Kept
 * deliberately faint (opacity ≤ 0.5) and masked at the edges — the moment a
 * background competes with a number on screen it has failed at its job.
 *
 * Node positions are generated once from a fixed seed so the field is stable
 * across renders and identical between server and client. A `Math.random()`
 * field would hydrate-mismatch and shimmer on every state change.
 */

function seeded(seed: number) {
  let state = seed;
  return () => {
    state = (state * 1664525 + 1013904223) % 4294967296;
    return state / 4294967296;
  };
}

interface Node {
  x: number;
  y: number;
  r: number;
  delay: number;
}

export function AmbientField({
  density = 26,
  className,
}: {
  density?: number;
  className?: string;
}) {
  const reduced = useReducedMotion();

  const { nodes, links } = useMemo(() => {
    const random = seeded(20260727);
    const generated: Node[] = Array.from({ length: density }, () => ({
      x: random() * 100,
      y: random() * 100,
      r: 0.9 + random() * 1.6,
      delay: random() * 8,
    }));

    // Join only genuinely near neighbours; a fully connected graph reads as
    // noise rather than a network.
    const edges: [Node, Node][] = [];
    for (let i = 0; i < generated.length; i += 1) {
      for (let j = i + 1; j < generated.length; j += 1) {
        const a = generated[i]!;
        const b = generated[j]!;
        const distance = Math.hypot(a.x - b.x, a.y - b.y);
        if (distance < 19) edges.push([a, b]);
      }
    }
    return { nodes: generated, links: edges };
  }, [density]);

  return (
    <div
      aria-hidden
      className={cn(
        // The entire field is atmosphere: Command mode removes it wholesale.
        "ambient pointer-events-none absolute inset-0 overflow-hidden",
        className,
      )}
    >
      <div className="grid-field absolute inset-0 opacity-40" />

      <svg
        viewBox="0 0 100 100"
        preserveAspectRatio="none"
        className={cn(
          "absolute inset-0 size-full opacity-50",
          !reduced && "ambient animate-[drift_24s_var(--ease-precise)_infinite]",
        )}
      >
        {links.map(([a, b], index) => (
          <line
            key={index}
            x1={a.x}
            y1={a.y}
            x2={b.x}
            y2={b.y}
            stroke="var(--color-plasma)"
            strokeWidth="0.08"
            opacity="0.25"
          />
        ))}
        {nodes.map((node, index) => (
          <circle
            key={index}
            cx={node.x}
            cy={node.y}
            r={node.r / 6}
            fill="var(--color-plasma)"
            opacity="0.7"
          >
            {!reduced && (
              <animate
                attributeName="opacity"
                values="0.2;0.8;0.2"
                dur="7s"
                begin={`${node.delay}s`}
                repeatCount="indefinite"
              />
            )}
          </circle>
        ))}
      </svg>

      {/* Vignette: pulls focus to the centre and stops the field reaching the
          edges of the viewport, where it would fight the chrome. */}
      <div className="absolute inset-0 bg-[radial-gradient(ellipse_60%_50%_at_50%_50%,transparent,var(--color-void)_85%)]" />
    </div>
  );
}
