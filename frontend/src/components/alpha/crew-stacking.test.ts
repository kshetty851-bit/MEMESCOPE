import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

/**
 * The team section must paint above the fixed space background.
 *
 * `.home-universe` is `position: fixed; inset: 0; z-index: 0` and contains an
 * opaque canvas. A positioned element with `z-index: 0` paints above an
 * in-flow *static* block, and because it is fixed it re-covers the viewport at
 * every scroll offset — so a static section under it is invisible at all times
 * and cannot be scrolled clear.
 *
 * That is exactly what happened: the crew section shipped with correct markup,
 * correct data and ten cards, and was solid black on screen.
 *
 * ── WHY THIS IS A SOURCE TEST AND NOT A DOM TEST ────────────────────────
 *
 * Because a DOM test cannot catch it. The overlay is `pointer-events: none`,
 * so `elementFromPoint` over the heading returns `.crew-title` and every
 * hit-test, accessibility check and "is it in the document" assertion passes
 * while the pixels are black. jsdom has no compositor and would report the
 * same. The only durable guard is the declaration itself.
 */
/** Comments stripped first — the note explaining this bug mentions
 *  `z-index: 0`, and matching that would have the test grade the prose. */
const stripComments = (css: string) => css.replace(/\/\*[\s\S]*?\*\//g, "");

const CSS = stripComments(
  readFileSync(join(process.cwd(), "src/styles/globals.css"), "utf8"),
);

function block(selector: string): string {
  const start = CSS.indexOf(`\n${selector} {`);
  expect(start, `${selector} is missing from globals.css`).toBeGreaterThan(-1);
  return CSS.slice(start, CSS.indexOf("\n}", start));
}

describe("the homepage crew paints above the space background", () => {
  for (const selector of [".crew", ".crew-cta"]) {
    it(`gives ${selector} a stacking position`, () => {
      const rules = block(selector);
      // Static + z-auto is the exact combination that was invisible.
      expect(rules, `${selector} must not be statically positioned`).toMatch(
        /position:\s*relative/,
      );
      const z = rules.match(/z-index:\s*(\d+)/);
      expect(z, `${selector} needs an explicit z-index`).not.toBeNull();
      expect(Number(z![1])).toBeGreaterThan(0);
    });
  }

  it("keeps the background layer below them", () => {
    const universe = stripComments(
      readFileSync(join(process.cwd(), "src/styles/home-universe.css"), "utf8"),
    );
    const start = universe.indexOf(".home-universe {");
    const rules = universe.slice(start, universe.indexOf("}", start));
    expect(rules).toMatch(/position:\s*fixed/);
    const z = rules.match(/z-index:\s*(-?\d+)/);
    expect(z).not.toBeNull();
    // If the background ever climbs above the crew's z-index, the section goes
    // black again — and nothing else in the suite would notice.
    expect(Number(z![1])).toBeLessThan(10);
  });
});
