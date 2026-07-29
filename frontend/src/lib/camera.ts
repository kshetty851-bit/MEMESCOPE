/**
 * OBSERVATORY CAMERA
 *
 * Where the instrument is pointed for a given view. Moving between routes moves
 * the camera instead of cutting to a new sky, so the universe stays one
 * continuous place rather than a background that happens to be reused.
 *
 * Kept as a pure lookup with no React and no DOM so the framing decisions are
 * testable and live in one readable table rather than scattered through the
 * scene as magic numbers.
 *
 * The values are deliberately small. §10 of the master context asks for calm:
 * a few percent of translation and at most 12% of scale is enough to feel like
 * a different vantage point, while anything larger turns navigation into a
 * ride and starts fighting the interface for attention.
 */

export interface CameraPosition {
  /** Horizontal offset, percentage of viewport width. */
  x: number;
  /** Vertical offset, percentage of viewport height. */
  y: number;
  /** Dolly. 1 is the home position; larger is closer. */
  scale: number;
}

export const HOME: CameraPosition = { x: 0, y: 0, scale: 1 };

/**
 * Longest prefix wins, so `/tokens/{mint}` inherits the token framing without
 * needing an entry per mint.
 */
const POSITIONS: ReadonlyArray<readonly [string, CameraPosition]> = [
  // The default vantage: the whole field, nothing favoured.
  ["/command", HOME],
  // The scanner watches arrivals come up from the planet, so the camera sits
  // fractionally low and tightens.
  ["/feed", { x: 0, y: -2, scale: 1.05 }],
  // The division is the crew: push toward the station on the right.
  ["/division", { x: 3, y: 1, scale: 1.08 }],
  // Diagnostics wants context, not intimacy — pull wide.
  ["/system", { x: -2, y: 2, scale: 1.02 }],
  // A single token is the closest the camera ever gets: one object, examined.
  ["/tokens", { x: -1, y: -3, scale: 1.12 }],
];

/**
 * The camera position for a pathname. Unknown routes - including the landing
 * page - stay at home, which is the correct neutral for a first impression.
 */
export function cameraFor(pathname: string): CameraPosition {
  let best: CameraPosition = HOME;
  let bestLength = 0;

  for (const [prefix, position] of POSITIONS) {
    const matches = pathname === prefix || pathname.startsWith(`${prefix}/`);
    if (matches && prefix.length > bestLength) {
      best = position;
      bestLength = prefix.length;
    }
  }

  return best;
}

/** The composited transform for a camera position. */
export function cameraTransform({ x, y, scale }: CameraPosition): string {
  return `translate3d(${x}%, ${y}%, 0) scale(${scale})`;
}
