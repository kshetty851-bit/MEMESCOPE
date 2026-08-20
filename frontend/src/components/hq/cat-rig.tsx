"use client";

import type { Cat, CatPose } from "@/lib/hq/cats";

/**
 * THE CAT RIG.
 *
 * One drawing, seven postures, two coats. Like the human rig it is parts and
 * poses rather than bespoke art per state — a body, a head with ears, a tail
 * and legs, recombined per posture — so both cats are one component and a
 * third cat would be a palette, not a project.
 *
 * The proportions are deliberately chunky: at the room's fit-scale a cat is
 * around twenty pixels long, and a realistic cat at that size is a smudge
 * with a tail. Big head, short body, thick tail — the reference image's
 * management-game logic, applied to the species the reference forgot.
 *
 * Nothing here is interactive at the SVG level; the stage wraps the sprite in
 * the same focusable anchor pattern the employees use, and the personality
 * panel is where the jokes live. The drawing is aria-hidden throughout.
 */

const BODY = "hq-cat-coat";
const BELLY = "hq-cat-belly";

export function CatSprite({ cat, pose }: { cat: Cat; pose: CatPose }) {
  return (
    <g
      className="hq-cat"
      data-cat={cat.id}
      data-pose={pose}
      style={
        {
          "--hq-cat": `var(--hq-cat-${cat.coat})`,
          "--hq-cat-belly": `var(--hq-cat-${cat.coat}-belly)`,
        } as React.CSSProperties
      }
      aria-hidden="true"
    >
      <ellipse className="hq-contact-shadow" cx={0} cy={1} rx={13} ry={3.6} />
      {renderPose(pose)}
    </g>
  );
}

function Tail({ d }: { d: string }) {
  return <path className={`${BODY} hq-cat-tail`} d={d} />;
}

function Head({ x, y, size = 6.5, asleep = false }: { x: number; y: number; size?: number; asleep?: boolean }) {
  return (
    <g>
      <path className={BODY} d={`M${x - size * 0.7} ${y - size * 0.55} l-2.4 -4 l3.4 1.2 Z`} />
      <path className={BODY} d={`M${x + size * 0.7} ${y - size * 0.55} l2.4 -4 l-3.4 1.2 Z`} />
      <circle className={BODY} cx={x} cy={y} r={size} />
      {asleep ? (
        <g className="hq-cat-eyes">
          <path className="hq-cat-eye-line" d={`M${x - 3.4} ${y - 0.5} q1.6 1.4 3 0`} />
          <path className="hq-cat-eye-line" d={`M${x + 0.6} ${y - 0.5} q1.6 1.4 3 0`} />
        </g>
      ) : (
        <g className="hq-cat-eyes">
          <ellipse className="hq-cat-eye" cx={x - 2.4} cy={y - 0.6} rx={1.1} ry={1.5} />
          <ellipse className="hq-cat-eye" cx={x + 2.4} cy={y - 0.6} rx={1.1} ry={1.5} />
        </g>
      )}
      <path className="hq-cat-nose" d={`M${x - 0.9} ${y + 1.6} l1.8 0 l-0.9 1.2 Z`} />
    </g>
  );
}

function renderPose(pose: CatPose) {
  switch (pose) {
    case "cat_walk":
      return (
        <g>
          <Tail d="M9 -7 q7 -2 8 -9 q-4 3 -10 4 Z" />
          <ellipse className={BODY} cx={0} cy={-7} rx={11} ry={5.5} />
          <rect className={BODY} x={-9} y={-4} width={3} height={5} rx={1.4} />
          <rect className={BODY} x={-3} y={-4} width={3} height={5} rx={1.4} />
          <rect className={BODY} x={3} y={-4} width={3} height={5} rx={1.4} />
          <Head x={-9} y={-12} />
        </g>
      );
    case "cat_sit":
      return (
        <g>
          <Tail d="M8 -3 q8 0 9 -7 q-5 2 -10 3 Z" />
          <path className={BODY} d="M-7 0 Q-9 -13 0 -14 Q9 -13 7 0 Z" />
          <ellipse className={BELLY} cx={0} cy={-4} rx={4} ry={5.5} />
          <Head x={0} y={-17} />
        </g>
      );
    case "cat_watch":
      // Sitting, head tipped up at the thing worth watching.
      return (
        <g>
          <Tail d="M8 -3 q9 -1 10 -8 q-5 2 -11 4 Z" />
          <path className={BODY} d="M-7 0 Q-9 -13 0 -14 Q9 -13 7 0 Z" />
          <ellipse className={BELLY} cx={0} cy={-4} rx={4} ry={5.5} />
          <g transform="rotate(-14 0 -17)">
            <Head x={0} y={-18} />
          </g>
        </g>
      );
    case "cat_sleep":
      return (
        <g>
          <ellipse className={BODY} cx={0} cy={-4.5} rx={11.5} ry={5} />
          <Tail d="M-10 -3 q-6 3 1 5 q6 1 8 -2 q-5 1 -9 -3 Z" />
          <Head x={7} y={-7} size={5.8} asleep />
        </g>
      );
    case "cat_stretch":
      // Front low, rear high: the whole-spine stretch.
      return (
        <g>
          <Tail d="M9 -12 q6 -4 6 -10 q-5 3 -9 6 Z" />
          <path className={BODY} d="M-11 -2 Q-6 -4 -2 -8 Q4 -14 9 -12 Q11 -8 8 -5 L6 0 L2 0 L1 -3 Q-4 -1 -7 0 L-11 0 Z" />
          <Head x={-11} y={-5} />
        </g>
      );
    case "cat_groom":
      // Sitting, head turned down to the flank.
      return (
        <g>
          <Tail d="M8 -3 q8 0 9 -7 q-5 2 -10 3 Z" />
          <path className={BODY} d="M-7 0 Q-9 -13 0 -14 Q9 -13 7 0 Z" />
          <ellipse className={BELLY} cx={0} cy={-4} rx={4} ry={5.5} />
          <g transform="rotate(38 0 -14)">
            <Head x={0} y={-15} size={6} asleep />
          </g>
        </g>
      );
    case "cat_pounce":
      // The crouch-and-spring. The only quick shape in the set.
      return (
        <g>
          <Tail d="M10 -10 q7 1 9 -6 q-6 0 -11 2 Z" />
          <path className={BODY} d="M-12 -1 Q-10 -9 -3 -9 Q6 -12 11 -8 Q12 -4 8 -2 L6 0 L-10 0 Z" />
          <rect className={BODY} x={-11} y={-3} width={3.4} height={4} rx={1.5} />
          <rect className={BODY} x={5} y={-3} width={3.4} height={4} rx={1.5} />
          <Head x={-9} y={-12} size={6.8} />
        </g>
      );
  }
}
