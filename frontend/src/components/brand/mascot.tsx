"use client";

import Image from "next/image";
import { useEffect, useState } from "react";

import { cn } from "@/lib/utils";

/**
 * The LETZMOON mascot — an astronaut adrift in the observation window.
 *
 * ## About the artwork
 *
 * The reference artwork supplied for this brief is a watermarked stock image.
 * A visible watermark is the licence being enforced, so it is not shipped and
 * it is not edited out — removing it is the infringement, not a step away from
 * one.
 *
 * What ships instead is the original vector below, drawn for LETZMOON. It is
 * also the better engineering answer: ~4 KB of inline SVG against a raster PNG,
 * no network request, crisp at every density, and every part of it addressable
 * by CSS so the visor, the body and the tether can move independently.
 *
 * ## Swapping in a licensed asset
 *
 * Drop the licensed file at `public/mascot.png` and it takes over
 * automatically — no code change. The vector stays as the fallback for the
 * moment before the image decodes, and for anyone who blocks images.
 *
 * ## Motion
 *
 * Six layered loops at deliberately co-prime durations (11s, 7s, 13s, 19s, 5s)
 * so they never resynchronise into an obvious pulse. Everything animates
 * `transform` or `opacity` only, which keeps the whole thing on the compositor
 * and off the main thread — the same rule the observatory scene follows.
 *
 * Under `prefers-reduced-motion` the mascot holds a single composed pose. It
 * does not merely slow down: for a vestibular trigger, slow drifting is the
 * problem rather than the fix.
 */
export function Mascot({
  size = 280,
  className,
  priority = false,
}: {
  size?: number;
  className?: string;
  priority?: boolean;
}) {
  const [hasArtwork, setHasArtwork] = useState(false);

  // Probe for the licensed asset rather than rendering an <Image> that 404s.
  // A broken image icon on the hero is worse than the vector it replaces.
  useEffect(() => {
    let cancelled = false;
    const probe = new window.Image();
    probe.src = "/mascot.png";
    probe.onload = () => {
      if (!cancelled) setHasArtwork(true);
    };
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div
      className={cn("lm-mascot pointer-events-none select-none", className)}
      style={{ width: size, height: size }}
      aria-hidden
    >
      <div className="lm-mascot__drift h-full w-full">
        <div className="lm-mascot__breathe h-full w-full">
          {hasArtwork ? (
            <Image
              src="/mascot.png"
              alt=""
              width={size}
              height={size}
              priority={priority}
              className="h-full w-full object-contain"
            />
          ) : (
            <AstronautVector />
          )}
        </div>
      </div>
    </div>
  );
}

/**
 * Original mark. Deliberately simple geometry — a helmet, a visor, a suit and
 * a chest unit — because at hero scale the silhouette is what reads, and at
 * 32px in a nav bar detail becomes mud.
 */
function AstronautVector() {
  return (
    <svg viewBox="0 0 200 200" fill="none" className="h-full w-full">
      <defs>
        <radialGradient id="lm-visor" cx="0.35" cy="0.3" r="0.8">
          <stop offset="0%" stopColor="oklch(0.35 0.09 268)" />
          <stop offset="55%" stopColor="oklch(0.18 0.05 268)" />
          <stop offset="100%" stopColor="oklch(0.11 0.03 268)" />
        </radialGradient>
        <linearGradient id="lm-suit" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="oklch(0.93 0.008 268)" />
          <stop offset="100%" stopColor="oklch(0.72 0.014 268)" />
        </linearGradient>
        <linearGradient id="lm-shimmer" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stopColor="white" stopOpacity="0" />
          <stop offset="45%" stopColor="white" stopOpacity="0.5" />
          <stop offset="60%" stopColor="white" stopOpacity="0" />
        </linearGradient>
      </defs>

      {/* Backpack */}
      <rect x="62" y="74" width="76" height="74" rx="22" fill="oklch(0.62 0.012 268)" />

      {/* Arms */}
      <rect x="34" y="88" width="30" height="60" rx="15" fill="url(#lm-suit)" />
      <rect x="136" y="88" width="30" height="60" rx="15" fill="url(#lm-suit)" />

      {/* Legs */}
      <rect x="72" y="140" width="24" height="46" rx="12" fill="url(#lm-suit)" />
      <rect x="104" y="140" width="24" height="46" rx="12" fill="url(#lm-suit)" />

      {/* Torso */}
      <rect x="60" y="80" width="80" height="72" rx="26" fill="url(#lm-suit)" />

      {/* Chest unit — the one place brand colour appears on the suit */}
      <rect x="80" y="98" width="40" height="30" rx="8" fill="oklch(0.2 0.04 268)" />
      <circle cx="90" cy="108" r="3.5" fill="var(--color-brand-secondary)" />
      <circle cx="102" cy="108" r="3.5" fill="var(--color-brand-accent)" />
      <rect x="86" y="117" width="28" height="3" rx="1.5" fill="var(--color-brand)" />

      {/* Helmet */}
      <circle cx="100" cy="62" r="46" fill="oklch(0.9 0.01 268)" />
      <circle cx="100" cy="62" r="38" fill="url(#lm-visor)" />

      {/* Visor shimmer — the only element that moves inside the figure */}
      <g className="lm-mascot__shimmer">
        <ellipse cx="86" cy="48" rx="15" ry="10" fill="url(#lm-shimmer)" transform="rotate(-28 86 48)" />
      </g>

      {/* Eyes. Blink is a scaleY on this group, so it costs nothing. */}
      <g className="lm-mascot__blink" style={{ transformOrigin: "100px 64px" }}>
        <circle cx="88" cy="64" r="6" fill="oklch(0.95 0.02 268)" />
        <circle cx="112" cy="64" r="6" fill="oklch(0.95 0.02 268)" />
        <circle cx="89" cy="65" r="2.6" fill="oklch(0.15 0.02 268)" />
        <circle cx="113" cy="65" r="2.6" fill="oklch(0.15 0.02 268)" />
      </g>

      {/* Helmet rim highlight */}
      <circle
        cx="100"
        cy="62"
        r="46"
        fill="none"
        stroke="var(--color-brand-accent)"
        strokeOpacity="0.35"
        strokeWidth="1.5"
      />
    </svg>
  );
}
