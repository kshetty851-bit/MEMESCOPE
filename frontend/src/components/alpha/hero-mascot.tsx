"use client";

import Image from "next/image";
import type { CSSProperties } from "react";
import { useEffect, useRef } from "react";

import { cn } from "@/lib/utils";

export type MascotState = "idle" | "denied" | "approved" | "watching";

/**
 * THE MEMESCOPE MASCOT.
 *
 * A 2D cartoon sticker, not a render. That changed what this component is
 * allowed to do: the previous mascot was a photographic figure held back with
 * saturation and contrast filters so it would not fight the headline, and it
 * carried a set of overlays — a fake blink, a rim reflection, an atmosphere
 * wash — calibrated pixel by pixel to that one photograph. None of that
 * survives the swap, and none of it is worth re-deriving. Flat art needs no
 * grading, and eyelids painted over drawn eyes on a guessed coordinate look
 * exactly like what they are.
 *
 * What is left is the part that made it feel alive rather than pasted on:
 * drift, breath, and a gaze that follows the pointer — plus the four states
 * the launch sequence actually needs it to hold.
 *
 *   idle      floating, breathing, watching the pointer
 *   denied    a short confused shake; nothing punitive, nothing repeated
 *   approved  two thumbs up
 *   watching  leans back and follows the rocket up, then clears the frame
 *
 * It is `aria-hidden` throughout. Every word the sequence says is said by the
 * overlay, in text.
 */
export function HeroMascot({
  state = "idle",
  compact = false,
}: {
  state?: MascotState;
  compact?: boolean;
}) {
  const mascotRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (compact || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;

    let frame = 0;
    const onMove = (event: PointerEvent) => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        const x = (event.clientX / window.innerWidth - 0.5) * 10;
        const y = (event.clientY / window.innerHeight - 0.5) * 8;
        // This is a decorative layer. Updating its custom properties directly
        // avoids rerendering the landing page for every pointer movement.
        mascotRef.current?.style.setProperty("--gaze-x", `${x}px`);
        mascotRef.current?.style.setProperty("--gaze-y", `${y}px`);
      });
    };

    window.addEventListener("pointermove", onMove, { passive: true });
    return () => {
      cancelAnimationFrame(frame);
      window.removeEventListener("pointermove", onMove);
    };
  }, [compact]);

  return (
    <div
      ref={mascotRef}
      data-state={state}
      className={cn(
        "alpha-mascot",
        compact ? "alpha-mascot--compact" : "alpha-mascot--hero",
      )}
      style={
        {
          "--gaze-x": "0px",
          "--gaze-y": "0px",
        } as CSSProperties
      }
      aria-hidden
    >
      <div className="alpha-mascot__drift">
        <div className="alpha-mascot__breathe">
          <div className="alpha-mascot__frame">
            <span className="alpha-mascot__shadow" />
            <span className="alpha-mascot__backlight" />
            <Image
              src="/mascot/frog-astronaut-2d.png"
              alt=""
              width={1122}
              height={1402}
              priority={!compact}
              sizes={compact ? "120px" : "(max-width: 1023px) 46vw, 34vw"}
              className="alpha-mascot__image"
            />
            {/* Placed on the drawn hands, so the reaction reads as the mascot
                doing something rather than as a badge floating beside it. */}
            <ThumbsUp className="alpha-mascot__thumb alpha-mascot__thumb--raised" />
            <ThumbsUp className="alpha-mascot__thumb alpha-mascot__thumb--low" />
          </div>
        </div>
      </div>
    </div>
  );
}

/*
   The silhouette is the whole job. The first version had a stubby 28-unit
   thumb on a tall rounded fist, and at the ~70px this renders at it read as a
   green bin rather than a gesture — the one shape in the sequence that has to
   be legible instantly was the one that wasn't.

   What changed: the thumb is half again as tall and clears the fist properly,
   the fist is shorter so the thumb dominates the silhouette, and the finger
   creases run across it so the curled fingers read at a glance.
*/
const THUMB = "M40 64V34a12 12 0 0 1 24 0v30";
const FIST =
  "M28 62h46a13 13 0 0 1 13 13v17a13 13 0 0 1-13 13H32a13 13 0 0 1-13-13V75a13 13 0 0 1 9-13z";
const CUFF = "M24 105h56a8 8 0 0 1 8 8v7H16v-7a8 8 0 0 1 8-8z";
const CREASES = "M34 79h42M34 92h42";

/**
 * The thumbs-up, drawn to the same rules as the mascot: flat fill, heavy dark
 * keyline, white sticker outline underneath. Two passes rather than
 * `paint-order`, which keeps the outline from thinning at the joins.
 */
function ThumbsUp({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 104 128"
      className={className}
      aria-hidden="true"
      focusable="false"
      xmlns="http://www.w3.org/2000/svg"
    >
      {/* Sticker outline. Thinner than the first pass — at 14 it swallowed the
          gap between thumb and fist and turned the whole glyph into a blob. */}
      <g
        fill="none"
        stroke="#f8f8f3"
        strokeWidth="9"
        strokeLinejoin="round"
        strokeLinecap="round"
      >
        <path d={THUMB} />
        <path d={FIST} />
        <path d={CUFF} />
      </g>
      <g stroke="#23211b" strokeWidth="5" strokeLinejoin="round" strokeLinecap="round">
        <path d={THUMB} fill="#a8c936" />
        <path d={FIST} fill="#a8c936" />
        <path d={CUFF} fill="#f2efe3" />
      </g>
      {/* Curled fingers, across the fist rather than down it. */}
      <path
        d={CREASES}
        fill="none"
        stroke="#23211b"
        strokeWidth="3.5"
        strokeLinecap="round"
        opacity="0.42"
      />
    </svg>
  );
}
