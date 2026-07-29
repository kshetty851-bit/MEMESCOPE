import { describe, expect, it } from "vitest";

import { cameraFor, cameraTransform, HOME } from "@/lib/camera";

describe("cameraFor", () => {
  it("frames the command centre at home", () => {
    expect(cameraFor("/command")).toEqual(HOME);
  });

  it("keeps unknown routes at home", () => {
    // Including the landing page: a first impression should not open on a
    // camera that has been swung somewhere for another view's benefit.
    expect(cameraFor("/")).toEqual(HOME);
    expect(cameraFor("/nowhere")).toEqual(HOME);
  });

  it.each([
    ["/feed", 1.05],
    ["/division", 1.08],
    ["/system", 1.02],
  ])("gives %s its own framing", (pathname, scale) => {
    expect(cameraFor(pathname).scale).toBe(scale);
  });

  it("applies the token framing to any mint", () => {
    const framing = cameraFor("/tokens/8kFboZiKNQ4jC8fyNAiCjm9YGV5qs99Ns7fCchdYpump");

    expect(framing).toEqual(cameraFor("/tokens"));
    // The closest the camera ever gets - a single object, examined.
    expect(framing.scale).toBe(1.12);
  });

  it("does not match a route that merely shares a prefix", () => {
    // `/systematic` is not `/system`, and matching it would swing the camera
    // on a route this table knows nothing about.
    expect(cameraFor("/systematic")).toEqual(HOME);
  });

  it("stays within the calm envelope §10 asks for", () => {
    // Guards the framings against drifting into a ride. Every position is a
    // few percent of translation and at most a 12% dolly.
    for (const pathname of ["/command", "/feed", "/division", "/system", "/tokens"]) {
      const { x, y, scale } = cameraFor(pathname);

      expect(Math.abs(x)).toBeLessThanOrEqual(4);
      expect(Math.abs(y)).toBeLessThanOrEqual(4);
      expect(scale).toBeGreaterThanOrEqual(1);
      expect(scale).toBeLessThanOrEqual(1.12);
    }
  });
});

describe("cameraTransform", () => {
  it("builds a composited transform", () => {
    // translate3d rather than translate: the z keeps it on its own layer, which
    // is the whole reason a route change costs nothing on the main thread.
    expect(cameraTransform({ x: 3, y: -2, scale: 1.08 })).toBe(
      "translate3d(3%, -2%, 0) scale(1.08)",
    );
  });
});
