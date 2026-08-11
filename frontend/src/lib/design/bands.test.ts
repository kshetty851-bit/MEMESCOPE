import { describe, expect, it } from "vitest";

import {
  RISK_BANDS,
  SCORE_BANDS,
  directionOf,
  num,
  riskBandFrom,
  scoreBandFromGrade,
} from "@/lib/design/bands";

describe("num", () => {
  it("parses decimal strings without losing the value", () => {
    expect(num("1234.5678")).toBe(1234.5678);
    expect(num("0.000000000123")).toBe(0.000000000123);
  });

  it("treats absence as null rather than zero", () => {
    // The whole product rests on this distinction: a price we do not have is
    // not a price of zero.
    expect(num(null)).toBeNull();
    expect(num(undefined)).toBeNull();
    expect(num("")).toBeNull();
  });

  it("keeps a real zero as zero", () => {
    expect(num("0")).toBe(0);
    expect(num(0)).toBe(0);
  });

  it("returns null for values that cannot be a figure", () => {
    expect(num("not a number")).toBeNull();
    expect(num(Number.NaN)).toBeNull();
    expect(num(Number.POSITIVE_INFINITY)).toBeNull();
  });
});

describe("scoreBandFromGrade", () => {
  it("maps every backend grade to a band", () => {
    expect(scoreBandFromGrade("critical")).toBe(SCORE_BANDS.critical);
    expect(scoreBandFromGrade("weak")).toBe(SCORE_BANDS.weak);
    expect(scoreBandFromGrade("watch")).toBe(SCORE_BANDS.watch);
    expect(scoreBandFromGrade("strong")).toBe(SCORE_BANDS.strong);
  });

  it("renames high_conviction to the elite band", () => {
    expect(scoreBandFromGrade("high_conviction")).toBe(SCORE_BANDS.elite);
  });

  it("returns null when there is no grade, never a default band", () => {
    expect(scoreBandFromGrade(null)).toBeNull();
    expect(scoreBandFromGrade(undefined)).toBeNull();
  });

  it("orders the bands so a comparison is meaningful", () => {
    expect(SCORE_BANDS.critical.rank).toBeLessThan(SCORE_BANDS.weak.rank);
    expect(SCORE_BANDS.weak.rank).toBeLessThan(SCORE_BANDS.watch.rank);
    expect(SCORE_BANDS.watch.rank).toBeLessThan(SCORE_BANDS.strong.rank);
    expect(SCORE_BANDS.strong.rank).toBeLessThan(SCORE_BANDS.elite.rank);
  });

  it("spends gold on exactly one band", () => {
    const gold = Object.values(SCORE_BANDS).filter(
      (band) => band.color === "var(--color-score-elite)",
    );
    expect(gold).toHaveLength(1);
    expect(gold[0]?.id).toBe("elite");
  });
});

describe("riskBandFrom", () => {
  it("maps the server's bands", () => {
    expect(riskBandFrom("low")).toBe(RISK_BANDS.low);
    expect(riskBandFrom("medium")).toBe(RISK_BANDS.medium);
    expect(riskBandFrom("high")).toBe(RISK_BANDS.high);
    expect(riskBandFrom("extreme")).toBe(RISK_BANDS.extreme);
  });

  it("is case-insensitive", () => {
    expect(riskBandFrom("EXTREME")).toBe(RISK_BANDS.extreme);
  });

  it("never resolves an absence to a band", () => {
    // Falling through to `extreme` would render an unassessed token as the
    // most dangerous thing on the page.
    expect(riskBandFrom(null)).toBeNull();
    expect(riskBandFrom(undefined)).toBeNull();
    expect(riskBandFrom("")).toBeNull();
    expect(riskBandFrom("unknown")).toBeNull();
  });

  it("gives every band a letter so colour is never the only carrier", () => {
    for (const band of Object.values(RISK_BANDS)) {
      expect(band.letter).toMatch(/^[A-Z]$/);
    }
    const letters = Object.values(RISK_BANDS).map((band) => band.letter);
    expect(new Set(letters).size).toBe(letters.length);
  });
});

describe("directionOf", () => {
  it("reads direction against a zero pivot", () => {
    expect(directionOf(4.2)).toBe("up");
    expect(directionOf(-4.2)).toBe("down");
    expect(directionOf(0)).toBe("flat");
  });

  it("reads multiples against a pivot of one", () => {
    // 1.0x is unchanged, which is the Radar's own convention.
    expect(directionOf(2.5, 1)).toBe("up");
    expect(directionOf(0.3, 1)).toBe("down");
    expect(directionOf(1, 1)).toBe("flat");
  });

  it("returns null for an unmeasured change rather than calling it flat", () => {
    expect(directionOf(null)).toBeNull();
    expect(directionOf(undefined)).toBeNull();
    expect(directionOf(Number.NaN)).toBeNull();
  });
});
