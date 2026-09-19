import { describe, expect, it } from "vitest";

import { formatDate } from "./utils";
import { SITE_TIME_ZONE } from "./site-time";

// 12:00 UTC is 16:00 in Dubai (UTC+4, no daylight saving).
const NOON_UTC = new Date("2026-09-19T12:00:00Z");

describe("every clock on the site reads Dubai time", () => {
  it("defaults every Date formatter to Dubai", () => {
    expect(SITE_TIME_ZONE).toBe("Asia/Dubai");
    expect(NOON_UTC.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" }))
      .toBe("16:00");
    expect(NOON_UTC.toLocaleString("en-GB", { hour: "2-digit", minute: "2-digit" }))
      .toBe("16:00");
    // 22:00 UTC is already the next day in Dubai.
    expect(new Date("2026-09-19T22:00:00Z").toLocaleDateString("en-GB"))
      .toBe("20/09/2026");
  });

  it("keeps a zone a call names itself", () => {
    expect(NOON_UTC.toLocaleTimeString("en-GB", {
      hour: "2-digit", minute: "2-digit", timeZone: "UTC",
    })).toBe("12:00");
  });

  it("covers the shared formatter too", () => {
    expect(formatDate("2026-09-19T12:00:00Z")).toMatch(/\b(16:00|4:00\s?PM)/);
  });
});
