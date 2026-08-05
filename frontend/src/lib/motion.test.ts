import { describe, expect, it } from "vitest";

import { describeMove, directionOf, rankDeltas } from "@/lib/motion";

/**
 * Motion logic.
 *
 * Everything that decides *whether* to animate is pure and tested here, so the
 * components only have to decide how. Most of these assert that motion stays
 * still: a flash that fires on a rounding artefact or a page load teaches the
 * eye to ignore the signal exactly when it starts carrying information.
 */

describe("directionOf", () => {
  it("names the direction of a real move", () => {
    expect(directionOf("10", "12")).toBe("up");
    expect(directionOf("12", "10")).toBe("down");
  });

  it("does not fire when nothing moved", () => {
    expect(directionOf("10", "10")).toBe("none");
  });

  it("does not fire on the first observation", () => {
    // A page load is not a price move. Flashing ten rows on arrival would
    // train the reader to ignore the flash.
    expect(directionOf(undefined, "10")).toBe("none");
    expect(directionOf(null, "10")).toBe("none");
  });

  it("does not fire when a value disappears", () => {
    // A token that stopped being priced has not gone down.
    expect(directionOf("10", null)).toBe("none");
  });

  it("compares the raw figure, not the rendered one", () => {
    // Both render as "$0.0000". Comparing formatted output would miss this.
    expect(directionOf("0.0000123", "0.0000456")).toBe("up");
  });

  it("ignores an unreadable value rather than guessing", () => {
    expect(directionOf("10", "not-a-number")).toBe("none");
    expect(directionOf("nonsense", "10")).toBe("none");
  });

  it("treats a differently-written equal value as unchanged", () => {
    expect(directionOf("10.0", "10.00")).toBe("none");
  });
});

describe("rankDeltas", () => {
  const before = ["a", "b", "c", "d"];

  it("reports places moved, positive for a climb", () => {
    const moved = rankDeltas(before, ["c", "a", "b", "d"]);
    expect(moved.get("c")).toBe(2); // 3rd -> 1st
    expect(moved.get("a")).toBe(-1);
    expect(moved.get("b")).toBe(-1);
  });

  it("says nothing about a row that held its place", () => {
    const moved = rankDeltas(before, ["c", "a", "b", "d"]);
    expect(moved.has("d")).toBe(false);
  });

  it("reports nothing at all for an unchanged ranking", () => {
    expect(rankDeltas(before, before).size).toBe(0);
  });

  it("does not treat a new arrival as a move", () => {
    // It came from nowhere, not from a rank — an arrow would claim it climbed.
    const moved = rankDeltas(before, ["new", "a", "b", "c"]);
    expect(moved.has("new")).toBe(false);
    expect(moved.get("a")).toBe(-1);
  });

  it("marks nothing on first paint", () => {
    expect(rankDeltas([], before).size).toBe(0);
  });

  it("ignores a row that left the list", () => {
    const moved = rankDeltas(before, ["a", "b"]);
    expect(moved.has("c")).toBe(false);
    expect(moved.has("d")).toBe(false);
  });
});

describe("describeMove", () => {
  it("spells the movement out for screen readers", () => {
    // Sighted readers get the arrow; this is the same fact through the other
    // channel, not a decoration.
    expect(describeMove(3)).toBe("climbed 3 places");
    expect(describeMove(-2)).toBe("fell 2 places");
  });

  it("agrees with itself in the singular", () => {
    expect(describeMove(1)).toBe("climbed 1 place");
    expect(describeMove(-1)).toBe("fell 1 place");
  });
});
