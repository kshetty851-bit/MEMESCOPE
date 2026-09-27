import { describe, expect, it } from "vitest";

import { flight } from "./sky-traffic";

describe("sky traffic", () => {
  it("crosses the whole screen, one side to the other, inside the sky", () => {
    for (let i = 0; i < 200; i++) {
      const s = flight(i, "rocket").style as Record<string, string>;
      const [fx, tx] = [parseFloat(s["--fx"]!), parseFloat(s["--tx"]!)];
      expect(Math.min(fx, tx)).toBe(-12);
      expect(Math.max(fx, tx)).toBe(112);
      for (const y of [parseFloat(s["--fy"]!), parseFloat(s["--ty"]!)]) {
        expect(y).toBeGreaterThanOrEqual(4);
        expect(y).toBeLessThanOrEqual(85);
      }
    }
  });
});
