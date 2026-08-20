/**
 * THE HQ TILE SYSTEM.
 *
 * One 16×12 grid, one projection, one place that knows how a tile becomes a
 * screen position. Every wall, desk, employee anchor and prop is placed in
 * *tile* coordinates and converted here — so moving the camera, changing the
 * tile size or reflowing the room for tablet is a change to this file and
 * nothing else.
 *
 * WHY PARALLEL PROJECTION AND NOT PERSPECTIVE
 *
 * A perspective camera makes the far side of the room smaller, which means a
 * desk's importance would depend on where it sits. In HQ every desk is a
 * subsystem and they are not ranked, so the projection must be uniform.
 * Parallel projection also has no depth divide, so a tile's screen position is
 * two multiplications and nothing can z-fight.
 *
 * THE MATH
 *
 * Standard 2:1 isometric. Moving one tile east goes right and down; moving one
 * tile south goes left and down. Half-width and half-height are the constants
 * that fall out of a 2:1 diamond:
 *
 *     screenX = (col - row) * (TILE_W / 2)
 *     screenY = (col + row) * (TILE_H / 2)
 *
 * At TILE_W 128 / TILE_H 64 a 22×14 room is 2304 wide and 1152 tall before any
 * scaling, which is why the stage scales to fit rather than the tiles changing
 * size — a fractional tile size produces seams between floor plates.
 *
 * PURE ON PURPOSE
 *
 * No DOM, no window, no React. The room's whole layout is therefore testable
 * as arithmetic, and a wrong desk position is a failing assertion rather than
 * something someone notices in a screenshot.
 */

/** Logical tile width. Not pixels — the stage scales the whole room. */
export const TILE_W = 128;
/** Logical tile height. Exactly half the width: a 2:1 isometric diamond. */
export const TILE_H = 64;

/**
 * 22×14 as of the world-expansion phase; 16×12 before it.
 *
 * The original footprint had no space for a conference room, a pantry distinct
 * from the lounge, a reception, or an exterior deck without squeezing them
 * into the walkways the walk routes depend on. The expansion is mathematical,
 * not visual: six new columns east (conference room over the exterior deck)
 * and two new rows south (facilities, restrooms, reception), with every
 * pre-existing zone, desk and authored route keeping its exact coordinates.
 *
 * The south-east corner of the new rectangle (cols 16–22, rows 8–14) is
 * deliberately covered by no zone: it renders as open space, which is what it
 * is — the deck juts out of the station hull and the lounge's viewport looks
 * over the same void.
 */
export const GRID_COLS = 22;
export const GRID_ROWS = 14;

/** Room extents in logical units, before the stage's fit-scale. */
export const ROOM_W = (GRID_COLS + GRID_ROWS) * (TILE_W / 2);
export const ROOM_H = (GRID_COLS + GRID_ROWS) * (TILE_H / 2);

export interface Tile {
  col: number;
  row: number;
}

export interface Point {
  x: number;
  y: number;
}

/**
 * Horizontal shift that puts the westernmost tile at x=0.
 *
 * The diamond's leftmost point is the *south-west* corner — tile
 * `(0, GRID_ROWS)` — which sits at `-GRID_ROWS * TILE_W / 2` before shifting.
 * So the offset is the row extent, not half the room width. Those two happen
 * to be equal only when the grid is square, which is exactly why the first
 * version of this looked right on a diagram and pushed the eastern tiles 64
 * units past the viewBox on a 16×12 grid.
 */
const X_ORIGIN = GRID_ROWS * (TILE_W / 2);

/** Tile → screen point, in logical units, origin at the room's west corner. */
export function toScreen({ col, row }: Tile): Point {
  return {
    x: (col - row) * (TILE_W / 2) + X_ORIGIN,
    y: (col + row) * (TILE_H / 2),
  };
}

/**
 * Paint order.
 *
 * In an isometric room a thing further south or east must paint over a thing
 * behind it. `col + row` is that ordering, scaled to leave room for layers
 * *within* one tile: a desk (0), a screen on the desk (1), a person at the
 * desk (2). Without the multiplier a person would sort equal to their own desk
 * and the browser would break the tie by DOM order, which is exactly the kind
 * of bug that only appears after a refactor moves a JSX line.
 */
export function depthOf({ col, row }: Tile, layer = 0): number {
  return (col + row) * 10 + layer;
}

/** Layer offsets for `depthOf`, so the numbers are named rather than magic. */
export const LAYER = {
  floor: 0,
  rug: 1,
  furniture: 2,
  desk: 3,
  prop: 4,
  screen: 5,
  employee: 6,
  overlay: 7,
} as const;

/**
 * Whether a tile is inside the room.
 *
 * Used by tests to assert no zone or anchor was placed outside the floor — a
 * mistake that renders as a desk floating in space and is easy to miss on a
 * dark background.
 */
export function isInsideRoom({ col, row }: Tile): boolean {
  return col >= 0 && col < GRID_COLS && row >= 0 && row < GRID_ROWS;
}

/**
 * A rectangular block of tiles, used by zones.
 *
 * Inclusive of the origin, exclusive of the far edge, like every other
 * half-open range in the codebase.
 */
export interface TileRect {
  col: number;
  row: number;
  cols: number;
  rows: number;
}

/** The four screen corners of a tile rect, for drawing a floor plate. */
export function rectCorners(rect: TileRect): [Point, Point, Point, Point] {
  const { col, row, cols, rows } = rect;
  return [
    toScreen({ col, row }),
    toScreen({ col: col + cols, row }),
    toScreen({ col: col + cols, row: row + rows }),
    toScreen({ col, row: row + rows }),
  ];
}

/** An SVG polygon `points` string for a tile rect's floor plate. */
export function rectPolygon(rect: TileRect): string {
  return rectCorners(rect)
    .map((point) => `${point.x},${point.y}`)
    .join(" ");
}

/** Centre of a tile rect, where a zone label or an anchor sits. */
export function rectCentre(rect: TileRect): Point {
  return toScreen({
    col: rect.col + rect.cols / 2,
    row: rect.row + rect.rows / 2,
  });
}

/** Do two rects overlap? Asserted in tests so zones cannot be laid on top of each other. */
export function rectsOverlap(a: TileRect, b: TileRect): boolean {
  return (
    a.col < b.col + b.cols &&
    b.col < a.col + a.cols &&
    a.row < b.row + b.rows &&
    b.row < a.row + a.rows
  );
}
