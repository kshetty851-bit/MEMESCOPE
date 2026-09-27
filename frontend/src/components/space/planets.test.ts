import { describe, expect, it } from "vitest";

import { plan } from "./planets";

const px = (v: unknown) => Number(String(v).replace("px", ""));

/** Every point a planet can reach: its spot plus the furthest wander step. */
function reach(o: ReturnType<typeof plan>[number], scale: number) {
  const s = o.style as Record<string, unknown>;
  const size = Number(s["--size"]) * scale;
  const xs = ["--x1", "--x2", "--x3"].map((k) => px(s[k]));
  const ys = ["--y1", "--y2", "--y3"].map((k) => px(s[k]));
  const x = px(s["--x"]);
  const y = px(s["--y"]);
  return {
    left: x + Math.min(0, ...xs), right: x + size + Math.max(0, ...xs),
    top: y + Math.min(0, ...ys), bottom: y + size + Math.max(0, ...ys),
  };
}

describe("planets never touch", () => {
  for (const [w, h, scale] of [[1440, 900, 1], [1024, 768, 1], [390, 844, 0.6]] as const) {
    it(`at ${w}x${h}, over many random skies`, () => {
      for (let run = 0; run < 200; run++) {
        const boxes = plan(w, h).map((o) => reach(o, scale));
        for (let i = 0; i < boxes.length; i++)
          for (let j = i + 1; j < boxes.length; j++) {
            const a = boxes[i]!;
            const b = boxes[j]!;
            const apart = a.right <= b.left || b.right <= a.left || a.bottom <= b.top || b.bottom <= a.top;
            expect(apart).toBe(true);
          }
      }
    });
  }
});
