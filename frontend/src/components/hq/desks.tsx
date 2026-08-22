"use client";

import type { DeskTheme } from "@/lib/hq/characters";
import { TILE_H, TILE_W } from "@/lib/hq/geometry";

/**
 * DESKS THAT SAY WHAT SOMEONE DOES.
 *
 * Ten instrument clusters. A reader should be able to tell the risk desk from
 * the market desk with the people removed, because in a room this dense the
 * furniture carries as much identity as the figures do.
 *
 * ABSTRACT SHAPES, NEVER NUMBERS.
 *
 * Every screen here is bars, sweeps, grids and blocks. Not one renders a
 * figure, a percentage, a token symbol or a status word. A "+12.4%" drawn as
 * decoration on the most authoritative surface in the product would be a
 * fabricated operational claim, and it would be indistinguishable from a real
 * one once the adapter lands. The shapes are deliberately unreadable as data.
 *
 * These are placeholders in the honest sense: the geometry is final, the
 * content is empty, and HQ-5 onward fills specific panels with measured
 * values.
 */

const W = TILE_W * 0.44;
const H = TILE_H * 0.44;
/** Apparent thickness of the desk slab. Thin desks read as floor decals. */
const DESK_DEPTH = 19;

interface DeskProps {
  x: number;
  y: number;
  theme: DeskTheme;
}

/**
 * The desk surface, identical for everyone. Identity lives in what sits on it.
 *
 * A wood top on a grey pedestal, with the two visible faces at different
 * values so the slab has a lit side and a shadowed one. The pedestal is inset
 * from the top's footprint, which is what gives the desk an overhanging edge —
 * the cheapest cue that it is a piece of furniture rather than a coloured
 * quadrilateral lying on the carpet.
 */
export function Desk({ x, y, theme }: DeskProps) {
  const inset = 0.62;
  const pw = W * inset;
  const ph = H * inset;
  const legTop = y + H * 0.35;
  return (
    <g className="hq-desk" data-desk={theme}>
      <ellipse className="hq-prop-shadow" cx={x} cy={y + H + 8} rx={W * 1.02} ry={H * 0.72} />

      {/* Pedestal, set back under the overhang. */}
      <polygon
        className="hq-desk-side--dark"
        points={`${x - pw},${legTop} ${x},${legTop + ph} ${x},${legTop + ph + DESK_DEPTH + 8} ${x - pw},${legTop + DESK_DEPTH + 8}`}
      />
      <polygon
        className="hq-desk-side"
        points={`${x},${legTop + ph} ${x + pw},${legTop} ${x + pw},${legTop + DESK_DEPTH + 8} ${x},${legTop + ph + DESK_DEPTH + 8}`}
      />

      {/* The slab. Two faces plus a lighter front edge so the wood has a
          thickness you can see. */}
      <polygon
        className="hq-desk-edge"
        points={`${x - W},${y} ${x},${y + H} ${x},${y + H + DESK_DEPTH} ${x - W},${y + DESK_DEPTH}`}
      />
      <polygon
        className="hq-prop-wood-dark"
        points={`${x},${y + H} ${x + W},${y} ${x + W},${y + DESK_DEPTH} ${x},${y + H + DESK_DEPTH}`}
      />
      <polygon
        className="hq-desk-top"
        points={`${x},${y - H} ${x + W},${y} ${x},${y + H} ${x - W},${y}`}
      />

      {/* Everyone's desk carries the same working clutter — a keyboard, a
          mouse and a couple of sheets. Identity is the instrument cluster
          above; this is just evidence that somebody sits here. */}
      <polygon
        className="hq-keyboard"
        points={`${x - 20},${y + 4} ${x + 2},${y + 15} ${x + 20},${y + 6} ${x - 2},${y - 5}`}
      />
      <ellipse className="hq-mouse" cx={x + 27} cy={y + 3} rx={5} ry={3.2} />
      <polygon className="hq-paper" points={`${x - 34},${y - 4} ${x - 21},${y + 2.5} ${x - 30},${y + 7} ${x - 43},${y + 0.5}`} />
      <polygon className="hq-paper" points={`${x - 31},${y - 7} ${x - 19},${y - 1} ${x - 27},${y + 3} ${x - 39},${y - 3}`} />
    </g>
  );
}

/**
 * The instruments.
 *
 * Drawn above and behind the desk so they read as mounted displays rather than
 * as objects lying flat, which is what makes the room look like mission
 * control instead of an open-plan office.
 */
export function DeskInstruments({ x, y, theme }: DeskProps) {
  return (
    <g className="hq-instruments" data-instruments={theme} aria-hidden="true">
      {/* A monitor is a dark bezel, a stand and a foot. Without the shell the
          instrument cluster was a lit rectangle hanging in the air behind
          somebody's shoulder — legible as a diagram, not as a screen. */}
      <ellipse className="hq-prop-shadow" cx={x} cy={y - 3} rx={13} ry={5} />
      <ellipse className="hq-bezel" cx={x} cy={y - 5} rx={10} ry={4} />
      <rect className="hq-bezel" x={x - 3} y={y - 16} width={6} height={11} />
      <rect className="hq-bezel" x={x - 24} y={y - 48} width={48} height={33} rx={3} />
      <rect className="hq-screen-glass" x={x - 21.8} y={y - 45.8} width={43.6} height={28.6} rx={2} />
      {/* The instrument clusters were drawn for a desk with no monitor around
          them. Scaling the group is one transform; redrawing ten themes to fit
          a bezel would be ten chances to get one of them subtly wrong. */}
      <g transform={`translate(${x} ${y - 31}) scale(0.86) translate(${-x} ${-(y - 31)})`}>
        {renderTheme(theme, x, y - 20)}
      </g>
    </g>
  );
}

function renderTheme(theme: DeskTheme, x: number, y: number) {
  switch (theme) {
    /* Nova — one wide executive display, nothing else. Authority is emptiness. */
    case "mission":
      return (
        <g>
          <Panel x={x - 22} y={y - 26} w={44} h={22} />
          <line className="hq-ink" x1={x - 16} y1={y - 19} x2={x + 10} y2={y - 19} />
          <line className="hq-ink" x1={x - 16} y1={y - 14} x2={x + 4} y2={y - 14} />
          <line className="hq-ink" x1={x - 16} y1={y - 9} x2={x + 14} y2={y - 9} />
        </g>
      );

    /* Radar — a sweep. The only circular motif in the room. */
    case "discovery":
      return (
        <g>
          <Panel x={x - 20} y={y - 26} w={40} h={24} />
          <circle className="hq-ink" cx={x} cy={y - 14} r={8} fill="none" />
          <circle className="hq-ink" cx={x} cy={y - 14} r={4} fill="none" />
          <path className="hq-sweep" d={`M${x} ${y - 14} L${x + 8} ${y - 19}`} />
          {/* Two contacts, positioned asymmetrically so it reads as a live
              scope rather than a logo. */}
          <circle className="hq-blip" cx={x + 5} cy={y - 18} r={1.3} />
          <circle className="hq-blip" cx={x - 4} cy={y - 10} r={1.3} />
        </g>
      );

    /* Luna — one large chart and a scorecard slate. Reading, not monitoring. */
    case "analysis":
      return (
        <g>
          <Panel x={x - 22} y={y - 28} w={30} h={26} />
          <polyline
            className="hq-ink"
            fill="none"
            points={`${x - 17},${y - 8} ${x - 11},${y - 15} ${x - 5},${y - 12} ${x + 1},${y - 21} ${x + 4},${y - 18}`}
          />
          <Panel x={x + 11} y={y - 22} w={12} h={18} />
          {[0, 1, 2].map((i) => (
            <line key={i} className="hq-ink" x1={x + 14} y1={y - 18 + i * 4} x2={x + 20} y2={y - 18 + i * 4} />
          ))}
        </g>
      );

    /* Dex — four small screens. The busiest desk in the room. */
    case "market":
      return (
        <g>
          {(
            [
              [-23, -28],
              [-1, -28],
              [-23, -14],
              [-1, -14],
            ] as Array<readonly [number, number]>
          ).map(([dx, dy], i) => (
            <g key={i}>
              <Panel x={x + dx} y={y + dy} w={20} h={12} />
              <polyline
                className="hq-ink"
                fill="none"
                points={`${x + dx + 3},${y + dy + 9} ${x + dx + 7},${y + dy + 4} ${x + dx + 11},${y + dy + 7} ${x + dx + 16},${y + dy + 3}`}
              />
            </g>
          ))}
          <Mug x={x + 24} y={y - 4} />
        </g>
      );

    /* Atlas — two aligned monitors and a shield plate. Nothing else, ever. */
    case "risk":
      return (
        <g>
          <Panel x={x - 24} y={y - 26} w={22} h={20} />
          <Panel x={x + 2} y={y - 26} w={22} h={20} />
          {/* A grid of checks: rows of evaluations, no values. */}
          {[0, 1, 2].map((r) =>
            [0, 1, 2].map((c) => (
              <rect key={`${r}${c}`} className="hq-cell" x={x - 20 + c * 6} y={y - 22 + r * 5} width={4} height={3} />
            )),
          )}
          <path className="hq-shield" d={`M${x + 13} ${y - 21} l4 -2 l4 2 v5 q0 4 -4 6 q-4 -2 -4 -6 Z`} />
        </g>
      );

    /* Milo — a tall allocation wall. Blocks of capital, unlabelled. */
    case "portfolio":
      return (
        <g>
          <Panel x={x - 24} y={y - 34} w={48} h={30} />
          {(
            [
              [-20, 14],
              [-4, 9],
              [8, 12],
            ] as Array<readonly [number, number]>
          ).map(([dx, h], i) => (
            <rect key={i} className="hq-bar" x={x + dx} y={y - 8 - h} width={11} height={h} />
          ))}
          <line className="hq-ink" x1={x - 21} y1={y - 8} x2={x + 21} y2={y - 8} />
        </g>
      );

    /* Rex — one execution terminal, plainly marked as the paper one. */
    case "execution":
      return (
        <g>
          <Panel x={x - 22} y={y - 28} w={44} h={24} />
          {/* Two stacked entry rows and a wide action bar: a terminal shape,
              with no ticker and no direction. */}
          <rect className="hq-cell" x={x - 17} y={y - 23} width={34} height={4} />
          <rect className="hq-cell" x={x - 17} y={y - 17} width={22} height={4} />
          <rect className="hq-action" x={x - 17} y={y - 10} width={34} height={5} rx={1} />
          <text className="hq-desk-plate" x={x} y={y + 2}>
            PAPER
          </text>
        </g>
      );

    /* Echo — a queue board. Columns of pending work, no depths. */
    case "operations":
      return (
        <g>
          <Panel x={x - 24} y={y - 30} w={48} h={26} />
          {[0, 1, 2, 3].map((c) => (
            <g key={c}>
              <line className="hq-ink" x1={x - 18 + c * 12} y1={y - 26} x2={x - 18 + c * 12} y2={y - 8} />
              {Array.from({ length: 3 - (c % 2) }).map((_, r) => (
                <rect key={r} className="hq-cell" x={x - 21 + c * 12} y={y - 24 + r * 5} width={7} height={3} />
              ))}
            </g>
          ))}
        </g>
      );

    /* Byte — three terminals at angles, a server stack, cable spill. */
    case "infrastructure":
      return (
        <g>
          <Panel x={x - 26} y={y - 26} w={18} h={20} rotate={-8} />
          <Panel x={x - 6} y={y - 30} w={18} h={22} />
          <Panel x={x + 14} y={y - 26} w={16} h={20} rotate={9} />
          {[0, 1, 2, 3].map((i) => (
            <line key={i} className="hq-ink" x1={x - 3} y1={y - 25 + i * 4} x2={x + 7} y2={y - 25 + i * 4} />
          ))}
          {/* Server stack on the floor beside the desk. */}
          <rect className="hq-server" x={x + 22} y={y + 2} width={12} height={18} rx={1} />
          {[0, 1, 2].map((i) => (
            <line key={i} className="hq-ink" x1={x + 24} y1={y + 6 + i * 5} x2={x + 32} y2={y + 6 + i * 5} />
          ))}
          <Mug x={x - 28} y={y - 2} />
          <Mug x={x - 20} y={y + 1} />
        </g>
      );

    /* Sage — one wide historical chart and a notebook. Calm, horizontal. */
    case "performance":
      return (
        <g>
          <Panel x={x - 26} y={y - 30} w={52} h={26} />
          <polyline
            className="hq-ink"
            fill="none"
            points={`${x - 21},${y - 10} ${x - 14},${y - 16} ${x - 7},${y - 13} ${x},${y - 21} ${x + 7},${y - 18} ${x + 14},${y - 24} ${x + 21},${y - 22}`}
          />
          <line className="hq-ink" x1={x - 22} y1={y - 8} x2={x + 22} y2={y - 8} />
          <rect className="hq-notebook" x={x - 10} y={y + 1} width={20} height={5} rx={1} />
        </g>
      );

    /* Sentinel — a wall of small identical tiles. One per component watched.
       Uniform on purpose: a monitoring wall is legible because everything on
       it is the same size until one of them is not. Nothing here carries a
       colour, because a green tile drawn by a stylesheet would be a health
       claim made by furniture. */
    case "sentry":
      return (
        <g>
          <Panel x={x - 28} y={y - 32} w={56} h={24} />
          {[0, 1, 2, 3, 4, 5].map((i) => (
            <rect
              key={i}
              className="hq-server"
              x={x - 24 + (i % 3) * 17}
              y={y - 28 + Math.floor(i / 3) * 9}
              width={13}
              height={6}
              rx={1}
            />
          ))}
          {/* Pager on the desk, face up. The job is to be reachable. */}
          <rect className="hq-notebook" x={x + 12} y={y} width={9} height={6} rx={1.5} />
        </g>
      );

    /* Patch — one screen of stack trace, and the parts bin. A workbench, not
       a trading desk: the tell is that the tools are horizontal and out. */
    case "reliability":
      return (
        <g>
          <Panel x={x - 26} y={y - 30} w={34} h={24} />
          {[0, 1, 2, 3, 4].map((i) => (
            <line
              key={i}
              className="hq-ink"
              x1={x - 22}
              y1={y - 25 + i * 4}
              x2={x - 22 + [16, 24, 10, 20, 13][i]!}
              y2={y - 25 + i * 4}
            />
          ))}
          {/* Parts bin, lid off, three compartments. */}
          <rect className="hq-server" x={x + 12} y={y - 12} width={20} height={13} rx={1} />
          {[0, 1].map((i) => (
            <line key={i} className="hq-ink" x1={x + 18 + i * 6} y1={y - 11} x2={x + 18 + i * 6} y2={y - 2} />
          ))}
        </g>
      );

    /* Quinn — a checklist and a split before/after pane. Two panels the same
       size side by side is the whole idea of the job drawn in furniture. */
    case "verification":
      return (
        <g>
          <Panel x={x - 28} y={y - 30} w={26} h={24} />
          <Panel x={x} y={y - 30} w={26} h={24} />
          {[0, 1, 2, 3].map((i) => (
            <g key={i}>
              <line className="hq-ink" x1={x - 24} y1={y - 25 + i * 5} x2={x - 10} y2={y - 25 + i * 5} />
              <line className="hq-ink" x1={x + 4} y1={y - 25 + i * 5} x2={x + 18} y2={y - 25 + i * 5} />
            </g>
          ))}
          <rect className="hq-notebook" x={x - 8} y={y + 1} width={16} height={5} rx={1} />
        </g>
      );
  }
}

/* ---------------------------------------------------------------------- */

function Panel({
  x,
  y,
  w,
  h,
  rotate = 0,
}: {
  x: number;
  y: number;
  w: number;
  h: number;
  rotate?: number;
}) {
  return (
    <rect
      className="hq-screen"
      x={x}
      y={y}
      width={w}
      height={h}
      rx={2}
      transform={rotate ? `rotate(${rotate} ${x + w / 2} ${y + h / 2})` : undefined}
    />
  );
}

function Mug({ x, y }: { x: number; y: number }) {
  return (
    <g>
      <rect className="hq-mug" x={x} y={y} width={6} height={7} rx={1.5} />
      <path className="hq-ink" d={`M${x + 6} ${y + 2} q3 1.5 0 3`} fill="none" />
    </g>
  );
}
