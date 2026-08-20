"use client";

/**
 * THE THINGS THAT MAKE A ROOM A ROOM.
 *
 * A floor plan with desks on it is a diagram. What separates the reference
 * from a diagram is that its office is *inhabited by objects* — shelves with
 * books in them, a printer with a sheet coming out, a bin beside each desk, a
 * plant in a terracotta pot. None of it means anything. All of it is why the
 * picture reads as a place people work in.
 *
 * ONE PRIMITIVE, MANY PROPS
 *
 * Everything here is built from `IsoBox` — a top face and two side faces in
 * the same 2:1 projection the room uses. Drawing each prop bespoke would be
 * more code and would let one of them drift out of the projection, which is
 * the single most obvious way an isometric scene falls apart. The lit face,
 * the shadowed face and the top are three fills of one colour, so a palette
 * change carries every prop with it.
 *
 * WHAT IS DELIBERATELY NOT HERE
 *
 * No green bins and no red anything. The reference's bins are bright green and
 * they are the first thing your eye lands on; in a room where green means "this
 * subsystem is healthy" that would be a decorative object competing with an
 * operational claim, and the operational claim has to win. Status hues appear
 * in this file exactly nowhere.
 */

/** Props whose footprint sits on the floor. */
export type FloorProp =
  | "bookshelf"
  | "cabinet"
  | "printer"
  | "plant-large"
  | "plant-small"
  | "bin"
  | "server-rack"
  | "side-table"
  | "whiteboard"
  | "water-cooler"
  | "coffee-machine"
  // World-expansion kinds: the pantry's kitchen, the lounge's soft furniture,
  // the conference room, the deck, reception and facilities.
  | "fridge"
  | "counter-sink"
  | "counter-micro"
  | "snack-shelf"
  | "stool"
  | "sofa"
  | "lounge-chair"
  | "low-table"
  | "viewport"
  | "conference-table"
  | "conf-chair"
  | "bench"
  | "standing-table"
  | "supply-shelf"
  | "box-stack"
  | "restroom-doors"
  | "reception-counter"
  | "logo-stand"
  | "visitor-chair"
  | "security-gate"
  | "floor-mat";

/** Props that hang on a back wall. Drawn flat, in the wall's plane. */
export type WallProp = "art-space" | "art-chart" | "clock" | "sign" | "board";

/* ---------------------------------------------------------------------- */

/**
 * An isometric box.
 *
 * `w` is the half-width of the footprint in screen units; the footprint's
 * half-height is always half of that, because the room is a 2:1 diamond and
 * anything else would sit at a different angle from the floor it stands on.
 */
function IsoBox({
  x,
  y,
  w,
  h,
  top = "hq-prop-light",
  left = "hq-prop",
  right = "hq-prop-wood-dark",
}: {
  x: number;
  y: number;
  /** Half-width of the footprint. */
  w: number;
  /** Height, upward from the floor. */
  h: number;
  top?: string;
  left?: string;
  right?: string;
}) {
  const d = w / 2;
  return (
    <g>
      <polygon className={left} points={`${x - w},${y - h} ${x},${y - h + d} ${x},${y + d} ${x - w},${y}`} />
      <polygon className={right} points={`${x},${y - h + d} ${x + w},${y - h} ${x + w},${y} ${x},${y + d}`} />
      <polygon className={top} points={`${x},${y - h - d} ${x + w},${y - h} ${x},${y - h + d} ${x - w},${y - h}`} />
    </g>
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

/** The soft ellipse that stops a prop floating above the carpet. */
function Grounded({ x, y, w }: { x: number; y: number; w: number }) {
  return <ellipse className="hq-prop-shadow" cx={x} cy={y + w / 4} rx={w * 1.05} ry={w / 2.2} />;
}

/* ---------------------------------------------------------------------- */

export function OfficeProp({ x, y, kind }: { x: number; y: number; kind: FloorProp }) {
  return (
    <g className="hq-office-prop" data-prop={kind} aria-hidden="true">
      {renderProp(kind, x, y)}
    </g>
  );
}

function renderProp(kind: FloorProp, x: number, y: number) {
  switch (kind) {
    /* A wall of books. The single most useful prop in the reference: it fills
       vertical space, it is unmistakably an office, and its colour comes from
       the spines rather than from the furniture. */
    case "bookshelf":
      return (
        <g>
          <Grounded x={x} y={y} w={26} />
          <IsoBox
            x={x}
            y={y}
            w={26}
            h={58}
            top="hq-prop-light"
            left="hq-prop-wood"
            right="hq-prop-wood-dark"
          />
          {[0, 1, 2].map((shelf) => (
            <g key={shelf}>
              <polygon
                className="hq-shelf-back"
                points={`${x - 22},${y - 50 + shelf * 17} ${x - 1},${y - 39 + shelf * 17} ${x - 1},${y - 25 + shelf * 17} ${x - 22},${y - 36 + shelf * 17}`}
              />
              {[0, 1, 2, 3, 4].map((book) => (
                <rect
                  key={book}
                  className={`hq-book hq-book--${(shelf * 5 + book) % 6}`}
                  x={x - 20 + book * 4}
                  y={y - 48 + shelf * 17 + book * 2}
                  width={3}
                  height={11}
                  rx={0.5}
                />
              ))}
            </g>
          ))}
        </g>
      );

    /* Filing cabinet. Drawer lines and pull handles: two details, and without
       them it is a grey box. */
    case "cabinet":
      return (
        <g>
          <Grounded x={x} y={y} w={17} />
          <IsoBox x={x} y={y} w={17} h={30} top="hq-cabinet" left="hq-cabinet" right="hq-cabinet-dark" />
          {[0, 1, 2].map((drawer) => (
            <g key={drawer}>
              <polygon
                className="hq-cabinet-dark"
                points={`${x - 15},${y - 26 + drawer * 9} ${x - 1},${y - 19 + drawer * 9} ${x - 1},${y - 18 + drawer * 9} ${x - 15},${y - 25 + drawer * 9}`}
              />
              <rect className="hq-prop-light" x={x - 10} y={y - 24 + drawer * 9} width={5} height={1.6} rx={0.8} />
            </g>
          ))}
        </g>
      );

    /* Printer, mid-job. The sheet in the output tray is the whole joke. */
    case "printer":
      return (
        <g>
          <Grounded x={x} y={y} w={19} />
          <IsoBox x={x} y={y} w={19} h={20} top="hq-cabinet" left="hq-cabinet" right="hq-cabinet-dark" />
          <IsoBox x={x} y={y - 20} w={15} h={13} top="hq-white" left="hq-prop-light" right="hq-prop" />
          <rect className="hq-screen" x={x - 8} y={y - 30} width={7} height={3} rx={1} />
          <polygon className="hq-paper" points={`${x - 2},${y - 32} ${x + 13},${y - 39} ${x + 16},${y - 37} ${x + 1},${y - 30}`} />
        </g>
      );

    /* Big leafy plant. Five blades from one point reads as a monstera without
       drawing a monstera. */
    case "plant-large":
      return (
        <g>
          <Grounded x={x} y={y} w={13} />
          <IsoBox x={x} y={y} w={11} h={13} top="hq-pot" left="hq-pot" right="hq-pot-dark" />
          {[-34, -17, 0, 17, 34].map((angle, i) => (
            <ellipse
              key={i}
              className={i % 2 === 0 ? "hq-leaf" : "hq-leaf-dark"}
              cx={x}
              cy={y - 33}
              rx={5.5}
              ry={15}
              transform={`rotate(${angle} ${x} ${y - 15})`}
            />
          ))}
        </g>
      );

    case "plant-small":
      return (
        <g>
          <Grounded x={x} y={y} w={9} />
          <IsoBox x={x} y={y} w={8} h={9} top="hq-pot" left="hq-pot" right="hq-pot-dark" />
          {[-9, 0, 9].map((dx, i) => (
            <circle key={i} className={i === 1 ? "hq-leaf" : "hq-leaf-dark"} cx={x + dx} cy={y - 15 - (i % 2) * 4} r={7} />
          ))}
        </g>
      );

    /* Grey, not green. See the module header. */
    case "bin":
      return (
        <g>
          <Grounded x={x} y={y} w={7} />
          <polygon className="hq-bin" points={`${x - 6},${y - 13} ${x + 6},${y - 13} ${x + 4.5},${y} ${x - 4.5},${y}`} />
          <ellipse className="hq-bin-rim" cx={x} cy={y - 13} rx={6} ry={3} />
          <ellipse className="hq-bin-hole" cx={x} cy={y - 13} rx={4.4} ry={2} />
        </g>
      );

    /* Byte's stack. The lights are cyan and white, never green or red — a rack
       full of green LEDs beside a status system that uses green for "healthy"
       is a decorative object impersonating a measurement. */
    case "server-rack":
      return (
        <g>
          <Grounded x={x} y={y} w={18} />
          <IsoBox x={x} y={y} w={18} h={52} top="hq-server-top" left="hq-server" right="hq-server-dark" />
          {[0, 1, 2, 3, 4].map((unit) => (
            <g key={unit}>
              <polygon
                className="hq-server-dark"
                points={`${x - 15},${y - 46 + unit * 9} ${x - 1},${y - 39 + unit * 9} ${x - 1},${y - 34 + unit * 9} ${x - 15},${y - 41 + unit * 9}`}
              />
              <circle className="hq-led" cx={x - 12} cy={y - 42 + unit * 9} r={1.1} />
              <circle className="hq-led-dim" cx={x - 8.5} cy={y - 40.4 + unit * 9} r={1.1} />
            </g>
          ))}
          {/* Cable spill. Byte's desk is the one that is allowed to be untidy. */}
          <path className="hq-cable" d={`M${x + 14} ${y - 4} q10 6 4 14 q-6 8 6 10`} />
          <path className="hq-cable" d={`M${x + 16} ${y - 8} q14 4 6 16`} />
        </g>
      );

    case "side-table":
      return (
        <g>
          <Grounded x={x} y={y} w={14} />
          <IsoBox x={x} y={y} w={14} h={15} top="hq-prop-light" left="hq-prop-wood" right="hq-prop-wood-dark" />
        </g>
      );

    /* A standing whiteboard with a couple of strokes on it. Never a number:
       a figure drawn as decoration is indistinguishable from a measured one. */
    case "whiteboard":
      return (
        <g>
          <Grounded x={x} y={y} w={20} />
          <polygon className="hq-prop" points={`${x - 2},${y} ${x + 2},${y} ${x + 2},${y - 8} ${x - 2},${y - 8}`} />
          <polygon className="hq-white" points={`${x - 22},${y - 12} ${x + 22},${y - 22} ${x + 22},${y - 52} ${x - 22},${y - 42}`} />
          <polygon className="hq-prop" points={`${x - 22},${y - 42} ${x + 22},${y - 52} ${x + 22},${y - 54} ${x - 22},${y - 44}`} />
          <path className="hq-marker" d={`M${x - 16} ${y - 34} l14 -3 M${x - 16} ${y - 29} l24 -5 M${x - 16} ${y - 24} l10 -2`} />
        </g>
      );

    case "water-cooler":
      return (
        <g>
          <Grounded x={x} y={y} w={10} />
          <IsoBox x={x} y={y} w={10} h={26} top="hq-prop-light" left="hq-white" right="hq-prop" />
          <ellipse className="hq-water" cx={x} cy={y - 40} rx={9} ry={12} />
          <ellipse className="hq-water-light" cx={x - 3} cy={y - 44} rx={3} ry={5} />
          <rect className="hq-prop" x={x - 3} y={y - 22} width={6} height={4} rx={1} />
        </g>
      );

    case "coffee-machine":
      return (
        <g>
          <Grounded x={x} y={y} w={13} />
          <IsoBox x={x} y={y} w={13} h={16} top="hq-prop-light" left="hq-prop" right="hq-prop-wood-dark" />
          <IsoBox x={x} y={y - 20} w={11} h={20} top="hq-prop-light" left="hq-prop" right="hq-prop-wood-dark" />
          <rect className="hq-screen" x={x - 6} y={y - 36} width={8} height={4} rx={1} />
          <rect className="hq-mug" x={x - 3} y={y - 19} width={5} height={5} rx={1} />
          {/* Steam. The one prop in the room that moves on its own, and it is
              two arcs of opacity. */}
          <path className="hq-steam" d={`M${x - 1} ${y - 22} q3 -5 0 -9`} />
        </g>
      );

    /* ---- pantry ---------------------------------------------------------- */
    case "fridge":
      return (
        <g>
          <Grounded x={x} y={y} w={16} />
          <IsoBox x={x} y={y} w={16} h={52} top="hq-white" left="hq-white" right="hq-prop" />
          <polygon className="hq-prop" points={`${x - 13},${y - 30} ${x - 1},${y - 24} ${x - 1},${y - 22.5} ${x - 13},${y - 28.5}`} />
          <rect className="hq-prop" x={x - 11} y={y - 40} width={2} height={7} rx={1} />
        </g>
      );
    case "counter-sink":
      return (
        <g>
          <Grounded x={x} y={y} w={17} />
          <IsoBox x={x} y={y} w={17} h={22} top="hq-white" left="hq-prop-wood" right="hq-prop-wood-dark" />
          <ellipse className="hq-sink" cx={x} cy={y - 24} rx={7} ry={3.2} />
          <path className="hq-device-stroke" d={`M${x + 6} ${y - 26} q0 -6 -5 -6 l0 3`} />
        </g>
      );
    case "counter-micro":
      return (
        <g>
          <Grounded x={x} y={y} w={17} />
          <IsoBox x={x} y={y} w={17} h={22} top="hq-white" left="hq-prop-wood" right="hq-prop-wood-dark" />
          <IsoBox x={x - 2} y={y - 22} w={10} h={9} top="hq-prop-light" left="hq-prop" right="hq-prop-wood-dark" />
          <rect className="hq-screen" x={x - 9} y={y - 29} width={5} height={3.4} rx={0.8} />
          <Mug x={x + 8} y={y - 28} />
        </g>
      );
    case "snack-shelf":
      // The bookshelf's frame with tins and packets instead of spines.
      return (
        <g>
          <Grounded x={x} y={y} w={18} />
          <IsoBox x={x} y={y} w={18} h={40} top="hq-prop-light" left="hq-prop-wood" right="hq-prop-wood-dark" />
          {[0, 1].map((shelf) => (
            <g key={shelf}>
              <polygon
                className="hq-shelf-back"
                points={`${x - 15},${y - 33 + shelf * 15} ${x - 1},${y - 26 + shelf * 15} ${x - 1},${y - 15 + shelf * 15} ${x - 15},${y - 22 + shelf * 15}`}
              />
              {[0, 1, 2].map((item) => (
                <rect
                  key={item}
                  className={`hq-snack hq-snack--${(shelf * 3 + item) % 4}`}
                  x={x - 13 + item * 4.4}
                  y={y - 31 + shelf * 15 + item * 2.1}
                  width={3.4}
                  height={7}
                  rx={1}
                />
              ))}
            </g>
          ))}
        </g>
      );
    case "stool":
      return (
        <g>
          <Grounded x={x} y={y} w={7} />
          <rect className="hq-chair-stem" x={x - 1.5} y={y - 12} width={3} height={12} />
          <ellipse className="hq-chair" cx={x} cy={y - 13} rx={7} ry={3.6} />
        </g>
      );

    /* ---- lounge ------------------------------------------------------------
       The sofa and viewport lived in the old break room; they move here with
       real seats, because from this phase people actually sit on them. */
    case "sofa":
      return (
        <g>
          <Grounded x={x} y={y} w={38} />
          <polygon className="hq-sofa-side" points={`${x - 38},${y} ${x},${y + 18} ${x + 38},${y} ${x + 38},${y + 13} ${x},${y + 31} ${x - 38},${y + 13}`} />
          <polygon className="hq-sofa-seat" points={`${x - 38},${y} ${x},${y - 18} ${x + 38},${y} ${x},${y + 18}`} />
          <polygon className="hq-sofa-back" points={`${x - 38},${y - 2} ${x},${y - 20} ${x},${y - 34} ${x - 38},${y - 16}`} />
          <polygon className="hq-sofa-side" points={`${x + 30},${y - 4} ${x + 38},${y} ${x + 38},${y - 12} ${x + 30},${y - 16}`} />
        </g>
      );
    case "lounge-chair":
      return (
        <g>
          <Grounded x={x} y={y} w={18} />
          <polygon className="hq-sofa-side" points={`${x - 18},${y} ${x},${y + 9} ${x + 18},${y} ${x + 18},${y + 10} ${x},${y + 19} ${x - 18},${y + 10}`} />
          <polygon className="hq-sofa-seat" points={`${x - 18},${y} ${x},${y - 9} ${x + 18},${y} ${x},${y + 9}`} />
          <polygon className="hq-sofa-back" points={`${x - 18},${y - 1} ${x},${y - 10} ${x},${y - 24} ${x - 18},${y - 15}`} />
        </g>
      );
    case "low-table":
      return (
        <g>
          <Grounded x={x} y={y} w={13} />
          <IsoBox x={x} y={y} w={13} h={9} top="hq-prop-light" left="hq-prop-wood" right="hq-prop-wood-dark" />
          {/* Magazines. Reading matter, drawn too small to pretend to read. */}
          <polygon className="hq-paper" points={`${x - 6},${y - 11} ${x + 2},${y - 7} ${x - 2},${y - 5} ${x - 10},${y - 9}`} />
          <polygon className="hq-magazine" points={`${x - 2},${y - 12} ${x + 6},${y - 8} ${x + 2},${y - 6} ${x - 6},${y - 10}`} />
        </g>
      );
    case "viewport":
      return (
        <g>
          <rect className="hq-window hq-break-window" x={x - 40} y={y - 66} width={80} height={44} rx={20} />
          <circle className="hq-star" cx={x - 20} cy={y - 50} r={1.6} />
          <circle className="hq-star" cx={x + 9} cy={y - 39} r={1.3} />
          <circle className="hq-star" cx={x + 23} cy={y - 53} r={1.8} />
        </g>
      );

    /* ---- conference room --------------------------------------------------- */
    case "conference-table":
      // Three tiles of warm wood. Anchored on the middle tile; the papers and
      // cups say a room that gets used, and none of them carries a number.
      return (
        <g>
          <Grounded x={x} y={y} w={90} />
          <polygon className="hq-desk-edge" points={`${x - 96},${y - 20} ${x - 32},${y + 12} ${x - 32},${y + 26} ${x - 96},${y - 6}`} />
          <polygon className="hq-prop-wood-dark" points={`${x - 32},${y + 12} ${x + 96},${y - 52} ${x + 96},${y - 38} ${x - 32},${y + 26}`} />
          <polygon className="hq-desk-top" points={`${x - 96},${y - 20} ${x - 32},${y - 52} ${x + 32},${y - 84} ${x + 96},${y - 52} ${x + 32},${y + 12} ${x - 32},${y + 12}`} />
          <polygon className="hq-paper" points={`${x - 40},${y - 30} ${x - 28},${y - 24} ${x - 36},${y - 20} ${x - 48},${y - 26}`} />
          <polygon className="hq-paper" points={`${x + 10},${y - 52} ${x + 22},${y - 46} ${x + 14},${y - 42} ${x + 2},${y - 48}`} />
          <Mug x={x - 6} y={y - 40} />
          <Mug x={x + 40} y={y - 60} />
          <rect className="hq-notebook" x={x + 52} y={y - 48} width={12} height={6} rx={1} />
        </g>
      );
    case "conf-chair":
      // The conference chair pre-exists at the seat, so a meeting participant
      // sits on furniture that is already there — the rig draws no chair of
      // its own in the lounge stance.
      //
      // Drawn 1.3x its original geometry. It was built against a 1.0-scale
      // cast; the composition pass took the figures to 1.36, which left six
      // stools around a three-tile table and made the room read as a banquet
      // slab with doll furniture. Scaling the chair rather than shrinking the
      // table keeps the seats on their tiles.
      return (
        <g>
          <Grounded x={x} y={y} w={16} />
          <path className="hq-chair-back" d={`M-12 -4 L12 -4 L11 -26 Q11 -31 6 -31 L-6 -31 Q-11 -31 -11 -26 Z`} transform={`translate(${x} ${y}) scale(1.3)`} />
          <path className="hq-chair" d={`M-14 7 L14 7 L13 -4 L-13 -4 Z`} transform={`translate(${x} ${y}) scale(1.3)`} />
          <path className="hq-chair-stem" d={`M-2 7 L2 7 L3 13 L-3 13 Z`} transform={`translate(${x} ${y}) scale(1.3)`} />
        </g>
      );

    /* ---- outdoor deck ------------------------------------------------------ */
    case "bench":
      return (
        <g>
          <Grounded x={x} y={y} w={22} />
          <IsoBox x={x} y={y} w={22} h={12} top="hq-prop-light" left="hq-prop-wood" right="hq-prop-wood-dark" />
          <rect className="hq-metal-leg" x={x - 18} y={y - 4} width={3} height={6} />
          <rect className="hq-metal-leg" x={x + 15} y={y - 4} width={3} height={6} />
        </g>
      );
    case "standing-table":
      return (
        <g>
          <Grounded x={x} y={y} w={10} />
          <rect className="hq-chair-stem" x={x - 2} y={y - 34} width={4} height={34} />
          <ellipse className="hq-desk-top" cx={x} cy={y - 35} rx={12} ry={6} />
          <Mug x={x + 2} y={y - 41} />
        </g>
      );

    /* ---- facilities --------------------------------------------------------- */
    case "supply-shelf":
      return (
        <g>
          <Grounded x={x} y={y} w={20} />
          <IsoBox x={x} y={y} w={20} h={46} top="hq-prop-light" left="hq-metal" right="hq-metal-dark" />
          {[0, 1, 2].map((shelf) => (
            <g key={shelf}>
              <polygon
                className="hq-server-dark"
                points={`${x - 17},${y - 39 + shelf * 13} ${x - 1},${y - 31 + shelf * 13} ${x - 1},${y - 22 + shelf * 13} ${x - 17},${y - 30 + shelf * 13}`}
              />
              <rect className="hq-paper" x={x - 14} y={y - 36 + shelf * 13} width={5} height={5.5} rx={0.6} />
              <rect className="hq-snack--1" x={x - 8} y={y - 33 + shelf * 13} width={4.4} height={5.5} rx={0.6} />
            </g>
          ))}
        </g>
      );
    case "box-stack":
      return (
        <g>
          <Grounded x={x} y={y} w={15} />
          <IsoBox x={x} y={y} w={15} h={14} top="hq-box" left="hq-box" right="hq-box-dark" />
          <IsoBox x={x - 2} y={y - 14} w={11} h={11} top="hq-box" left="hq-box" right="hq-box-dark" />
          <path className="hq-device-stroke" d={`M${x - 8} ${y - 21} l9 4.5`} />
        </g>
      );

    /* ---- restrooms — signage only, no interiors ----------------------------- */
    case "restroom-doors":
      return (
        <g>
          <Grounded x={x} y={y} w={26} />
          <polygon className="hq-wall-inner" points={`${x - 28},${y - 2} ${x + 28},${y - 30} ${x + 28},${y - 76} ${x - 28},${y - 48}`} />
          <polygon className="hq-door" points={`${x - 20},${y - 8} ${x - 4},${y - 16} ${x - 4},${y - 52} ${x - 20},${y - 44}`} />
          <polygon className="hq-door" points={`${x + 4},${y - 20} ${x + 20},${y - 28} ${x + 20},${y - 64} ${x + 4},${y - 56}`} />
          <circle className="hq-device" cx={x - 6.5} cy={y - 32} r={1.4} />
          <circle className="hq-device" cx={x + 17.5} cy={y - 44} r={1.4} />
          <text className="hq-desk-plate" x={x} y={y - 70} transform={`rotate(-26.5 ${x} ${y - 70})`}>
            RESTROOMS
          </text>
        </g>
      );

    /* ---- reception ----------------------------------------------------------- */
    case "reception-counter":
      return (
        <g>
          <Grounded x={x} y={y} w={40} />
          <polygon className="hq-counter-front" points={`${x - 40},${y - 6} ${x + 8},${y + 18} ${x + 8},${y + 40} ${x - 40},${y + 16}`} />
          <polygon className="hq-counter-side" points={`${x + 8},${y + 18} ${x + 40},${y + 2} ${x + 40},${y + 24} ${x + 8},${y + 40}`} />
          <polygon className="hq-desk-top" points={`${x - 40},${y - 6} ${x + 8},${y - 30} ${x + 40},${y - 14} ${x + 8},${y + 18} ${x - 40},${y - 6}`} />
          <polygon className="hq-desk-top" points={`${x - 40},${y - 6} ${x - 8},${y - 22} ${x + 40},${y + 2} ${x + 8},${y + 18}`} />
          {/* The welcome board: a small dark screen. It greets; it reports
              nothing, because a fact drawn at reception would be a fact nobody
              measured. */}
          <rect className="hq-bezel" x={x - 6} y={y - 44} width={22} height={15} rx={2} />
          <rect className="hq-screen" x={x - 3.6} y={y - 41.6} width={17.2} height={10.2} rx={1.2} />
          <path className="hq-ink" d={`M${x} ${y - 38} l10 0 M${x} ${y - 35} l7 0`} />
          <polygon className="hq-paper" points={`${x - 26},${y - 12} ${x - 16},${y - 7} ${x - 22},${y - 4} ${x - 32},${y - 9}`} />
        </g>
      );
    case "logo-stand":
      // The company's name in the lobby, as bars of light on a dark stand —
      // the same mark the wall sign uses, at human height.
      return (
        <g>
          <Grounded x={x} y={y} w={14} />
          <IsoBox x={x} y={y} w={14} h={40} top="hq-server-top" left="hq-server" right="hq-server-dark" />
          {[0, 1, 2, 3].map((bar) => (
            <rect
              key={bar}
              className="hq-sign-bar"
              x={x - 11 + bar * 5}
              y={y - 34 + bar * 2.5 - (bar % 2 === 0 ? 0 : 3)}
              width={3}
              height={bar % 2 === 0 ? 12 : 9}
              rx={1}
            />
          ))}
        </g>
      );
    case "visitor-chair":
      return (
        <g>
          <Grounded x={x} y={y} w={12} />
          <path className="hq-chair-back" d={`M-11 -4 L11 -4 L10 -24 Q10 -28 6 -28 L-6 -28 Q-10 -28 -10 -24 Z`} transform={`translate(${x} ${y})`} />
          <path className="hq-chair" d={`M-13 6 L13 6 L12 -4 L-12 -4 Z`} transform={`translate(${x} ${y})`} />
          <rect className="hq-metal-leg" x={x - 10} y={y + 6} width={2.6} height={6} />
          <rect className="hq-metal-leg" x={x + 7.4} y={y + 6} width={2.6} height={6} />
        </g>
      );
    case "security-gate":
      return (
        <g>
          <Grounded x={x} y={y} w={22} />
          <IsoBox x={x - 14} y={y - 7} w={7} h={26} top="hq-white" left="hq-metal" right="hq-metal-dark" />
          <IsoBox x={x + 14} y={y + 7} w={7} h={26} top="hq-white" left="hq-metal" right="hq-metal-dark" />
          <circle className="hq-led" cx={x - 16} cy={y - 26} r={1.5} />
          <circle className="hq-led" cx={x + 12} cy={y - 12} r={1.5} />
        </g>
      );
    case "floor-mat":
      return (
        <g>
          <polygon className="hq-mat" points={`${x - 30},${y} ${x},${y - 15} ${x + 30},${y} ${x},${y + 15}`} />
          <polygon className="hq-mat-inner" points={`${x - 22},${y} ${x},${y - 11} ${x + 22},${y} ${x},${y + 11}`} />
        </g>
      );
  }
}

/* ---------------------------------------------------------------------- */

/**
 * Something hanging on a wall.
 *
 * The two back walls run in opposite screen directions: moving east along the
 * north wall goes right *and down*, moving south along the west wall goes left
 * and down. A frame drawn with the wrong one of those slants does not look
 * slightly off, it looks detached — it reads as floating in front of the wall
 * rather than hanging on it, which is exactly how the first version of this
 * failed.
 *
 * So the geometry is parametrised by the wall's own direction vector and
 * nothing else. `span` is measured in tiles along the wall; `height` is
 * straight up, because vertical is vertical in a parallel projection.
 */
export function WallDecor({
  x,
  y,
  kind,
  facing,
  span = 0.5,
  height = 28,
}: {
  /** Bottom near corner of the frame, on the wall. */
  x: number;
  y: number;
  kind: WallProp;
  facing: "north" | "west";
  /** Width along the wall, in tiles. */
  span?: number;
  height?: number;
}) {
  // East along the north wall; south along the west wall. Both descend.
  const ax = (facing === "north" ? 64 : -64) * span;
  const ay = 32 * span;

  const outer = `${x},${y} ${x + ax},${y + ay} ${x + ax},${y + ay - height} ${x},${y - height}`;

  // The mount inset, in the wall's own axes rather than in screen axes, so the
  // border stays an even width all the way round.
  const t = 0.14;
  const ix = x + ax * t;
  const iy = y + ay * t;
  const iax = ax * (1 - t * 2);
  const iay = ay * (1 - t * 2);
  const ih = height * 0.74;
  const lift = height * 0.13;
  const inner = `${ix},${iy - lift} ${ix + iax},${iy + iay - lift} ${ix + iax},${iy + iay - lift - ih} ${ix},${iy - lift - ih}`;

  const midX = ix + iax / 2;
  const midY = iy + iay / 2 - lift - ih / 2;

  const artClass =
    kind === "art-space"
      ? "hq-art-space"
      : kind === "art-chart"
        ? "hq-art-chart"
        : kind === "sign"
          ? "hq-art-sign"
          : "hq-white";

  return (
    <g className="hq-wall-decor" data-decor={kind} aria-hidden="true">
      <polygon className="hq-frame" points={outer} />
      <polygon className={artClass} points={inner} />

      {kind === "art-space" ? (
        <>
          <circle className="hq-art-planet" cx={midX} cy={midY + 2} r={ih * 0.28} />
          <circle className="hq-star" cx={midX - iax * 0.28} cy={midY - iay * 0.28 - ih * 0.28} r={1.2} />
          <circle className="hq-star" cx={midX + iax * 0.3} cy={midY + iay * 0.3 - ih * 0.22} r={1} />
          <circle className="hq-star" cx={midX + iax * 0.1} cy={midY + iay * 0.1 + ih * 0.3} r={0.9} />
        </>
      ) : null}

      {kind === "art-chart" ? (
        // A picture of a chart: no axis, no label, no number. An office has a
        // picture of a mountain; this office has a picture of a line going up.
        <path
          className="hq-art-line"
          d={`M${ix + iax * 0.14} ${iy + iay * 0.14 - lift - ih * 0.25}
              L${ix + iax * 0.4} ${iy + iay * 0.4 - lift - ih * 0.52}
              L${ix + iax * 0.6} ${iy + iay * 0.6 - lift - ih * 0.38}
              L${ix + iax * 0.86} ${iy + iay * 0.86 - lift - ih * 0.72}`}
        />
      ) : null}

      {kind === "sign" ? (
        // The company's name over Mission Control. Letterforms are five bars,
        // not text: a `<text>` element here would be caught by the room's
        // no-numerals rule and, more importantly, would be unreadable at this
        // size anyway.
        <g className="hq-sign-mark">
          {[0.14, 0.29, 0.44, 0.59, 0.74].map((at, i) => (
            <rect
              key={i}
              className="hq-sign-bar"
              x={ix + iax * at}
              y={iy + iay * at - lift - ih * 0.62}
              width={Math.abs(iax) * 0.06 + 2}
              height={ih * (i % 2 === 0 ? 0.42 : 0.3)}
              rx={1}
            />
          ))}
        </g>
      ) : null}
    </g>
  );
}
