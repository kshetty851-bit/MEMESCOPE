import { describe, expect, it } from "vitest";

import { handAngles, zoneTime } from "./world-clocks";

describe("world clocks", () => {
  it("reads each zone's own time, daylight saving included", () => {
    const at = new Date("2026-10-04T18:30:15Z");
    expect(zoneTime("Asia/Dubai", at)).toMatchObject({ h: 22, m: 30, s: 15 });
    expect(zoneTime("America/New_York", at)).toMatchObject({ h: 14, m: 30, s: 15 }); // EDT
    expect(zoneTime("America/New_York", new Date("2026-12-04T18:30:15Z")).h).toBe(13); // EST
  });

  it("points the hands", () => {
    expect(handAngles(3, 0, 0)).toEqual({ hour: 90, minute: 0, second: 0 });
    expect(handAngles(15, 30, 30).hour).toBeCloseTo(105.25);
    expect(handAngles(0, 45, 15).second).toBe(90);
  });
});
