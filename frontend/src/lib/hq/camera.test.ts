import { describe, expect, it } from "vitest";

import { ROOM, SCALE, VIEW, clamp, focalPoint, frame, sameTarget } from "./camera";
import { EMPLOYEES, EMPLOYEE_BY_ID } from "./employees";
import { ROOM_H, ROOM_W, toScreen } from "./geometry";

/**
 * THE CAMERA'S CONTRACT.
 *
 * Two properties matter and neither is "it looks nice": the default framing is
 * byte-for-byte what the room had before this existed, and no framing can ever
 * point outside the room.
 */

describe("the default framing changes nothing", () => {
  it("is the identity at room scale", () => {
    // The whole point: adding a camera must not move the picture that fourteen
    // screenshots and a dozen layout tests were written against.
    const f = frame(ROOM);
    expect(f.scale).toBe(1);
    expect(f.transform).toBe("translate(0.00 0.00) scale(1)");
  });

  it("returns to the identity from any other framing", () => {
    const away = frame({ kind: "desk", employee: "byte" });
    expect(away.transform).not.toBe(frame(ROOM).transform);
    expect(frame(ROOM).transform).toBe("translate(0.00 0.00) scale(1)");
  });
});

describe("the frame never leaves the room", () => {
  /**
   * The failure this prevents: closing on a corner desk with the subject dead
   * centre puts half the void outside the hull on screen. Every employee is
   * checked because the corners are exactly the ones a spot check misses.
   */
  it("keeps every desk's frame inside the floor", () => {
    for (const employee of EMPLOYEES) {
      const f = frame({ kind: "desk", employee: employee.id });
      const halfW = VIEW.width / (2 * f.scale);
      const halfH = VIEW.height / (2 * f.scale);
      expect(f.at.x - halfW, `${employee.id} shows void to the west`).toBeGreaterThanOrEqual(
        VIEW.x - 0.001,
      );
      expect(f.at.x + halfW, `${employee.id} shows void to the east`).toBeLessThanOrEqual(
        VIEW.x + VIEW.width + 0.001,
      );
      expect(f.at.y - halfH, `${employee.id} shows void above`).toBeGreaterThanOrEqual(
        VIEW.y - 0.001,
      );
      expect(f.at.y + halfH, `${employee.id} shows void below`).toBeLessThanOrEqual(
        VIEW.y + VIEW.height + 0.001,
      );
    }
  });

  it("collapses to the centre when the frame is bigger than the room", () => {
    // At scale 1 there is nothing to clamp, and a naive clamp inverts here —
    // min becomes greater than max and the result oscillates.
    const centred = clamp({ x: 0, y: 0 }, 1);
    expect(centred.x).toBeCloseTo(VIEW.x + VIEW.width / 2);
    expect(centred.y).toBeCloseTo(VIEW.y + VIEW.height / 2);
  });
});

describe("what the camera aims at", () => {
  it("aims above a desk tile, not at it", () => {
    // A figure is drawn upward from its tile, so centring on the tile frames
    // the character's feet and a lot of carpet.
    const desk = EMPLOYEE_BY_ID.get("nova")!.desk;
    const tile = toScreen(desk);
    const aim = focalPoint({ kind: "desk", employee: "nova" });
    expect(aim.y).toBeLessThan(tile.y);
  });

  it("falls back to the room for a target it cannot resolve", () => {
    // An id that no longer exists must not throw or aim at the origin.
    const stray = focalPoint({ kind: "desk", employee: "nobody" as never });
    expect(stray.x).toBeCloseTo(VIEW.x + VIEW.width / 2);
  });

  it("pushes in further on a desk than on a zone", () => {
    expect(SCALE.desk).toBeGreaterThan(SCALE.zone);
    expect(SCALE.zone).toBeGreaterThan(SCALE.room);
  });

  it("knows when two targets frame the same thing", () => {
    expect(sameTarget(ROOM, { kind: "room" })).toBe(true);
    expect(
      sameTarget({ kind: "desk", employee: "byte" }, { kind: "desk", employee: "byte" }),
    ).toBe(true);
    expect(
      sameTarget({ kind: "desk", employee: "byte" }, { kind: "desk", employee: "nova" }),
    ).toBe(false);
  });

  it("uses the room's real dimensions", () => {
    expect(VIEW.width).toBe(ROOM_W);
    expect(VIEW.height).toBeGreaterThan(ROOM_H);
  });
});
