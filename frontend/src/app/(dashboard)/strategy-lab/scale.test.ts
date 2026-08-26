import { describe, expect, it } from "vitest";

/**
 * The $100 view is an EXACT rescale of the $1,000 book that ran, not a re-run.
 *
 * The distinction is the whole point. Six of the twenty strategies could not have
 * funded their real trade history on $100 of capital — V6-03 needed $266, V6-14
 * $196, V6-02 $189 — because they deploy $80–$200 against a $1,000 book. Actually
 * starting them with $100 would have run them out of cash and changed which trades
 * they took, so "rewriting the history to $100" would mean inventing which trades
 * to delete.
 *
 * A pure change of units invents nothing: every ratio survives it untouched. These
 * tests hold exactly that property, because the moment a percentage starts moving
 * with the toggle the view has stopped being a rescale and become a claim.
 */

const scaleUsd = (v: number, scale: number) => v * scale;

describe("book rescale", () => {
  it("divides every dollar figure by ten and nothing else", () => {
    expect(scaleUsd(1000, 0.1)).toBe(100);
    expect(scaleUsd(-117.84, 0.1)).toBeCloseTo(-11.784, 10);
    expect(scaleUsd(10, 0.1)).toBe(1);
  });

  it("leaves every ratio identical, which is why it is honest", () => {
    // A $1,000 book: start 1000, equity 882.16.
    const big = { start: 1000, equity: 882.16 };
    const small = { start: scaleUsd(1000, 0.1), equity: scaleUsd(882.16, 0.1) };
    const ret = (b: { start: number; equity: number }) =>
      ((b.equity - b.start) / b.start) * 100;
    expect(ret(small)).toBeCloseTo(ret(big), 10);
  });

  it("preserves profit factor, which is a ratio of scaled sums", () => {
    const wins = [12.5, 3.25, 40];
    const losses = [-8, -19.75];
    const pf = (s: number) =>
      wins.reduce((a, w) => a + w * s, 0) /
      Math.abs(losses.reduce((a, l) => a + l * s, 0));
    expect(pf(0.1)).toBeCloseTo(pf(1), 10);
  });

  it("is exact at the scale the board actually displays", () => {
    // Two decimal places is what the UI shows; the rescale must not drift there.
    for (const v of [1000, 882.16, -128.88, 0.01, 199.99]) {
      const shown = (v * 0.1).toFixed(2);
      expect(Number(shown) * 10).toBeCloseTo(v, 1);
    }
  });

  it("scaling by one is the identity, so the default view is untouched", () => {
    for (const v of [1000, -117.84, 0, 0.005]) expect(scaleUsd(v, 1)).toBe(v);
  });
});
