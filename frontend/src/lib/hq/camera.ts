import { EMPLOYEE_BY_ID, type EmployeeId } from "./employees";
import { ROOM_H, ROOM_W, TILE_H, toScreen, type Point } from "./geometry";
import { ZONE_BY_ID, type ZoneId } from "./zones";

/**
 * THE CAMERA.
 *
 * The room has always been drawn at one fixed framing: the whole floor, from
 * far enough back that every department fits. That is the right *default* — it
 * is a floor plan and a floor plan has to show the floor — and it is a poor
 * way to look at any one person. At full-room scale a character is about forty
 * pixels tall, which is enough to tell fourteen silhouettes apart and not
 * nearly enough to see what one of them is doing.
 *
 * So the framing becomes a value. `room` is what it always was; `zone` pushes
 * in on one department; `desk` closes on a single person.
 *
 * ── WHY A TRANSFORM AND NOT THE viewBox ─────────────────────────────────
 *
 * A `viewBox` is the natural way to express a camera and the wrong way to
 * animate one: it is an attribute, not a style, so it does not transition, and
 * driving it per frame means re-rendering the whole scene on every tick of the
 * move. A transform on a group wrapping the scene expresses exactly the same
 * framing, transitions in CSS for free, and is composited rather than laid out.
 *
 * ── WHAT THIS IS NOT ────────────────────────────────────────────────────
 *
 * It is not a status light. Where the camera points must never be the only way
 * a reader learns something — the state chip, the panels and the accessible
 * description carry every operational fact, and they are text with a reading
 * behind them. A camera that pushed in on Byte would be a *worse* way of
 * saying "infrastructure is degraded" than the word next to his name, and if
 * it were ever the only way, a reader who had scrolled past would have missed
 * it. The camera decides what is comfortable to look at, nothing else.
 */

export type CameraTargetKind = "room" | "zone" | "desk";

export interface CameraTarget {
  kind: CameraTargetKind;
  /** Set for `zone`. */
  zone?: ZoneId;
  /** Set for `desk`. */
  employee?: EmployeeId;
}

export const ROOM: CameraTarget = { kind: "room" };

/**
 * How far in each framing pushes.
 *
 * Chosen against the figure rather than by eye: at `desk` scale a character is
 * roughly a sixth of the frame's height, which is about where a face becomes
 * readable at this rig's line weights. Past ~3 the floor plates start showing
 * their polygon edges, which is the ceiling this art style imposes.
 */
export const SCALE: Record<CameraTargetKind, number> = {
  room: 1,
  zone: 1.75,
  desk: 2.6,
};

/** The viewBox the stage declares. The camera works inside it. */
export const VIEW = {
  x: 0,
  y: -130,
  width: ROOM_W,
  height: ROOM_H + 130 + TILE_H,
} as const;

const CENTRE: Point = {
  x: VIEW.x + VIEW.width / 2,
  y: VIEW.y + VIEW.height / 2,
};

/**
 * Where a target sits, in room coordinates.
 *
 * A desk aims a little *above* the desk tile: the figure stands on it and is
 * drawn upward from it, so centring on the tile itself frames the character's
 * feet and a lot of floor.
 */
export function focalPoint(target: CameraTarget): Point {
  if (target.kind === "desk" && target.employee) {
    const employee = EMPLOYEE_BY_ID.get(target.employee);
    if (employee) {
      const at = toScreen(employee.desk);
      return { x: at.x, y: at.y - 52 };
    }
  }
  if (target.kind === "zone" && target.zone) {
    const zone = ZONE_BY_ID.get(target.zone);
    if (zone) {
      return toScreen({
        col: zone.rect.col + zone.rect.cols / 2,
        row: zone.rect.row + zone.rect.rows / 2,
      });
    }
  }
  return CENTRE;
}

/**
 * Keep the frame inside the room.
 *
 * Without this, closing on a corner desk fills half the screen with the void
 * outside the hull — the camera is centred on the target, and a target near an
 * edge has nothing on one side of it. Clamping trades "the subject is exactly
 * centred" for "the frame is full", which is the trade every real camera
 * operator makes.
 *
 * At scale 1 the visible rect is the whole viewBox and there is nothing to
 * clamp, so the arithmetic collapses to the centre on its own.
 */
export function clamp(point: Point, scale: number): Point {
  const halfW = VIEW.width / (2 * scale);
  const halfH = VIEW.height / (2 * scale);
  const minX = VIEW.x + halfW;
  const maxX = VIEW.x + VIEW.width - halfW;
  const minY = VIEW.y + halfH;
  const maxY = VIEW.y + VIEW.height - halfH;
  return {
    // `min > max` when the frame is wider than the room, which happens at
    // scale 1. Falling back to the centre is correct there and is also what
    // stops the clamp inverting into a jitter.
    x: minX > maxX ? CENTRE.x : Math.min(Math.max(point.x, minX), maxX),
    y: minY > maxY ? CENTRE.y : Math.min(Math.max(point.y, minY), maxY),
  };
}

export interface Framing {
  scale: number;
  /** What the camera is centred on, after clamping. */
  at: Point;
  /** Ready for the `transform` attribute on the camera group. */
  transform: string;
}

/** The framing for a target. Pure — the stage renders whatever this returns. */
export function frame(target: CameraTarget): Framing {
  const scale = SCALE[target.kind];
  const at = clamp(focalPoint(target), scale);
  // Translate so `at` lands on the viewBox centre, then scale about the origin.
  // Order matters: scale first in the string means the translate is in scaled
  // units, which is the classic way to get a camera that drifts as it zooms.
  const x = CENTRE.x - at.x * scale;
  const y = CENTRE.y - at.y * scale;
  return {
    scale,
    at,
    transform: `translate(${x.toFixed(2)} ${y.toFixed(2)}) scale(${scale})`,
  };
}

/** Two targets that frame the same thing. Used to avoid pointless moves. */
export function sameTarget(a: CameraTarget, b: CameraTarget): boolean {
  return a.kind === b.kind && a.zone === b.zone && a.employee === b.employee;
}

/**
 * How long the camera lingers on something it moved to by itself.
 *
 * Long enough to read a name and see a pose; short enough that a reader who
 * wanted the whole room is not held away from it. A manual selection has no
 * timeout at all — the reader is in charge until they say otherwise.
 */
export const AUTO_HOLD_MS = 7_000;

/** The glide. Matches the CSS transition on `.hq-camera`. */
export const GLIDE_MS = 900;
