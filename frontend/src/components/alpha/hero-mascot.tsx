"use client";

import type { CSSProperties } from "react";
import { useEffect, useRef, useState } from "react";

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
  const act = useFrogActs(state === "idle" && !compact);

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
            <FrogRig act={act} />
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

/*
 * THE FROG, ALIVE (Karthik, 2026-09-27: "animate the frog, move hands, legs,
 * expressions, make him do some stuff").
 *
 * The drawing is cut into puppet layers, each the full canvas size so they
 * stack exactly (`public/mascot/rig/`, cut by `frontend/scripts/cut-frog-rig.py`):
 * the body with the moving parts removed, the waving hand, the lower hand,
 * the tongue, and the motion marks. Drawn eyelids blink and wink over the
 * eyes. While the frog is idle it runs through a loose routine of acts — wave,
 * tongue out, a dance, a wink, a jump, a spin — each a CSS animation keyed on
 * `data-act`, with a pause between. The legs move with the body (a jump, a
 * bounce, a spin): the drawn feet are blended into the suit, and cutting them
 * would show. Nothing moves for a reader who asked for less motion.
 */

export type FrogAct = "rest" | "wave" | "tongue" | "dance" | "wink" | "jump" | "spin";

/** How long each act plays, in ms (its CSS animation runs this long). */
export const ACT_MS: Record<Exclude<FrogAct, "rest">, number> = {
  wave: 2400,
  tongue: 2200,
  dance: 2700,
  wink: 1000,
  jump: 1400,
  spin: 1600,
};

const ROUTINE: Exclude<FrogAct, "rest">[] = ["wave", "tongue", "dance", "wink", "jump", "wave", "spin", "tongue", "dance"];

function useFrogActs(active: boolean): FrogAct {
  const [act, setAct] = useState<FrogAct>("rest");
  useEffect(() => {
    if (!active || window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) {
      setAct("rest");
      return;
    }
    let timer = 0;
    let step = Math.floor(Math.random() * ROUTINE.length);
    const rest = () => {
      setAct("rest");
      timer = window.setTimeout(perform, 2200 + Math.random() * 2600);
    };
    const perform = () => {
      const next = ROUTINE[step++ % ROUTINE.length]!;
      setAct(next);
      timer = window.setTimeout(rest, ACT_MS[next]);
    };
    timer = window.setTimeout(perform, 1800);
    return () => window.clearTimeout(timer);
  }, [active]);
  return act;
}

const RIG = "/mascot/rig";
/** The eyes, in the drawing's own 1122 x 1402 pixel space. */
const EYES = [
  { id: "l", cx: 368, cy: 348, rx: 101, ry: 92 },
  { id: "r", cx: 660, cy: 272, rx: 79, ry: 86 },
] as const;

function FrogRig({ act }: { act: FrogAct }) {
  return (
    <div className="alpha-mascot__image frog-rig" data-act={act}>
      <div className="frog-rig__pose">
        {/* eslint-disable @next/next/no-img-element */}
        <img src={`${RIG}/body.webp`} alt="" width={1122} height={1402} fetchPriority="high"
             draggable={false} className="frog-rig__body" />
        <img src={`${RIG}/tongue.webp`} alt="" draggable={false} className="frog-rig__part frog-rig__tongue" />
        <img src={`${RIG}/hand-l.webp`} alt="" draggable={false} className="frog-rig__part frog-rig__hand-l" />
        <img src={`${RIG}/hand-r.webp`} alt="" draggable={false} className="frog-rig__part frog-rig__hand-r" />
        <img src={`${RIG}/marks-head.webp`} alt="" draggable={false} className="frog-rig__part frog-rig__marks" />
        <img src={`${RIG}/marks-hand.webp`} alt="" draggable={false} className="frog-rig__part frog-rig__marks" />
        <img src={`${RIG}/marks-feet.webp`} alt="" draggable={false} className="frog-rig__part frog-rig__marks" />
        {/* eslint-enable @next/next/no-img-element */}
        <svg className="frog-rig__part frog-rig__lids" viewBox="0 0 1122 1402" aria-hidden focusable="false">
          <defs>
            {EYES.map((e) => (
              <clipPath key={e.id} id={`frog-eye-${e.id}`}>
                <ellipse cx={e.cx} cy={e.cy} rx={e.rx} ry={e.ry} />
              </clipPath>
            ))}
          </defs>
          {EYES.map((e) => {
            const top = e.cy - e.ry - 10;
            const bottom = e.cy + e.ry + 12;
            const left = e.cx - e.rx - 10;
            const right = e.cx + e.rx + 10;
            return (
              <g key={e.id} clipPath={`url(#frog-eye-${e.id})`}>
                <g className={`frog-rig__lid frog-rig__lid--${e.id}`} style={{ "--lid": `${bottom - top}px` } as CSSProperties}>
                  <path d={`M${left} ${top} H${right} V${bottom - 18} Q${e.cx} ${bottom + 14} ${left} ${bottom - 18} Z`}
                        fill="#9dbb2b" />
                  <path d={`M${left} ${top} H${right} V${top + 30} H${left} Z`} fill="#aac932" />
                  <path d={`M${right} ${bottom - 18} Q${e.cx} ${bottom + 14} ${left} ${bottom - 18}`}
                        fill="none" stroke="#23211b" strokeWidth="9" strokeLinecap="round" />
                </g>
              </g>
            );
          })}
        </svg>
      </div>
    </div>
  );
}
