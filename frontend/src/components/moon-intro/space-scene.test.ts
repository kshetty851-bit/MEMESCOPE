import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { STAR_COUNTS, createSpaceScene, groupSizes, moonScale } from "./space-scene";
import type { Frame, IntroPhase } from "./timeline";

// jsdom has no 2D canvas: every context method is a counted no-op.
let calls: Record<string, number>;
function mockContext() {
  const state: Record<string | symbol, unknown> = {};
  return new Proxy(state, {
    get(t, k) {
      if (k in t) return t[k];
      return () => {
        calls[String(k)] = (calls[String(k)] ?? 0) + 1;
        return String(k).startsWith("create") ? { addColorStop() {} } : undefined;
      };
    },
    set(t, k, v) {
      t[k] = v;
      return true;
    },
  });
}

const frame = (phase: IntroPhase, p: number, t = 1, mode: Frame["mode"] = "full", dt = 1 / 60): Frame => ({
  phase,
  p,
  t,
  dt,
  mode,
});

beforeEach(() => {
  calls = {};
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockImplementation(() => mockContext() as never);
});
afterEach(() => vi.restoreAllMocks());

const scene = (mobile = false) => createSpaceScene(document.createElement("canvas"), { mobile });

/** Stars drawn in one cockpit frame = rect() calls (one per star). */
function starsDrawn(s: ReturnType<typeof scene>) {
  const before = calls.rect ?? 0;
  s.update(frame("cockpit", 0.5));
  return (calls.rect ?? 0) - before;
}

describe("space scene quality", () => {
  it("draws the full high-tier starfield on desktop and the low tier on mobile", () => {
    expect(STAR_COUNTS.low).toBeLessThan(STAR_COUNTS.high);
    expect(groupSizes(STAR_COUNTS.high).reduce((a, b) => a + b)).toBe(STAR_COUNTS.high);
    const desktop = scene();
    expect(desktop.quality()).toBe("high");
    expect(starsDrawn(desktop)).toBe(STAR_COUNTS.high);
    const mobile = scene(true);
    expect(mobile.quality()).toBe("low");
    expect(starsDrawn(mobile)).toBe(STAR_COUNTS.low);
  });

  it("drops to low after 30 consecutive slow frames, not 29, and never climbs back", () => {
    const s = scene();
    let t = 0;
    const tick = (dt: number) => s.update(frame("cockpit", 0.5, (t += dt), "full", dt));
    for (let i = 0; i < 29; i++) tick(0.025);
    tick(0.01); // one fast frame resets the run
    for (let i = 0; i < 29; i++) tick(0.025);
    expect(s.quality()).toBe("high");
    tick(0.025);
    expect(s.quality()).toBe("low");
    for (let i = 0; i < 100; i++) tick(0.008);
    expect(s.quality()).toBe("low");
    expect(starsDrawn(s)).toBe(STAR_COUNTS.low);
  });
});

describe("moon scale", () => {
  it("starts as a dot, grows monotonically, ends at ~80% of the viewport", () => {
    expect(moonScale(0)).toBeLessThan(0.03);
    let prev = -1;
    for (let p = 0; p <= 1.0001; p += 0.01) {
      expect(moonScale(p)).toBeGreaterThan(prev);
      prev = moonScale(p);
    }
    expect(moonScale(1)).toBeCloseTo(0.8, 2);
  });
});

describe("update", () => {
  const phases: IntroPhase[] = ["seatbelt", "cockpit", "ignition", "warp", "approach", "landing", "reveal", "done"];

  it("renders every phase in every mode without throwing, incl. big t jumps", () => {
    for (const mode of ["full", "short", "reduced"] as const) {
      const s = scene();
      let t = 0;
      for (const ph of phases) for (let p = 0; p <= 1; p += 0.05) s.update(frame(ph, p, (t += 1 / 60), mode));
      expect(() => s.update(frame("reveal", 0.1, 9, mode))).not.toThrow(); // skip forward
      expect(() => s.update(frame("landing", 0.6, 2, mode))).not.toThrow(); // backwards
      s.resize();
      s.destroy();
      expect(() => s.update(frame("warp", 0.5, 3, mode))).not.toThrow();
    }
  });

  it("draws the moon in approach and streaks in warp", () => {
    const s = scene();
    s.update(frame("warp", 0.9));
    expect(calls.stroke).toBeGreaterThan(0);
    const before = calls.drawImage ?? 0;
    s.update(frame("approach", 0.8, 1.02));
    expect(calls.drawImage ?? 0).toBeGreaterThan(before);
  });

  it("reduced mode draws one still frame until resized", () => {
    const s = scene();
    s.update(frame("cockpit", 0, 0, "reduced"));
    const n = calls.fillRect ?? 0;
    s.update(frame("cockpit", 0.5, 0.5, "reduced"));
    s.update(frame("reveal", 0.5, 1.3, "reduced"));
    expect(calls.fillRect).toBe(n);
    s.resize();
    s.update(frame("reveal", 0.6, 1.35, "reduced"));
    expect(calls.fillRect).toBeGreaterThan(n);
  });
});
