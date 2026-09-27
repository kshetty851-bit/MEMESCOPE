import { describe, expect, it } from "vitest";

import { dubaiDate, halfDays, monthsSince } from "./journey";
import { mergeDays, plain } from "./journey-log";

describe("the journey's live dates", () => {
  it("counts whole months since the first commit, in Dubai", () => {
    const start = new Date("2026-07-27T00:00:00+04:00");
    expect(monthsSince(start, new Date("2026-09-26T19:59:00Z"))).toBe(1); // 26 Sep, 23:59 Dubai
    expect(monthsSince(start, new Date("2026-09-26T20:01:00Z"))).toBe(2); // 27 Sep, 00:01 Dubai
  });

  it("writes dates the way the section shows them", () => {
    expect(dubaiDate("2026-10-23T12:00:00+00:00")).toBe("23 OCT 2026");
    expect(dubaiDate("2026-09-26T21:00:00Z")).toBe("27 SEP 2026");
  });

  it("rounds the rule's age to the nearest half day", () => {
    const start = "2026-09-23T12:00:00Z";
    expect(halfDays(start, Date.parse("2026-09-28T00:00:00Z"))).toBe("~4½");
    expect(halfDays(start, Date.parse("2026-09-27T12:00:00Z"))).toBe("~4");
  });
});

describe("the day-by-day log", () => {
  it("reads a commit title in plain words", () => {
    expect(plain("feat(lab): the take-profit tournament (#12)")).toBe("The take-profit tournament");
    expect(plain("Karthik's Lab: dollars only (#151)")).toBe("Karthik's Lab: dollars only");
  });

  it("keeps the written words, and writes a new day from its own commits", () => {
    const rows = mergeDays([
      { date: "2026-10-02", commits: 4, titles: ["feat(x): a new grid (#170)", "fix(y): a bug"] },
      { date: "2026-09-27", commits: 11, titles: ["anything"] },
    ]);
    expect(rows[0]).toEqual({ date: "2026-10-02", commits: 4, words: "A new grid · A bug" });
    expect(rows[1]!.date).toBe("2026-09-27");
    expect(rows[1]!.commits).toBe(11);
    expect(rows[1]!.words).toMatch(/USER 1–10 wallets/);
    // A written day GitHub has not answered for yet still shows, without a count.
    expect(rows.find((r) => r.date === "2026-07-27")!.commits).toBeNull();
  });
});
