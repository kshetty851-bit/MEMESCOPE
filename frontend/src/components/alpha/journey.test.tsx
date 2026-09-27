import { describe, expect, it } from "vitest";

import { dubaiDate, halfDays, monthsSince } from "./journey";

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
