import { describe, expect, it } from "vitest";

import { UNKNOWN_HQ_STATE, deriveHqState } from "@/lib/hq/adapter";
import { buildToday } from "@/lib/hq/today";

const NOW = Date.UTC(2026, 7, 20, 14, 30);
const TODAY = (h: number, m: number) => new Date(Date.UTC(2026, 7, 20, h, m)).toISOString();
const YESTERDAY = new Date(Date.UTC(2026, 7, 19, 22, 0)).toISOString();

function withAudit(items: unknown[]) {
  return deriveHqState({
    now: NOW,
    paperAudit: {
      data: { items, total: items.length, enabled: true, disclosure: "", observed_at: TODAY(14, 0) },
      observedAt: NOW,
    },
  } as never);
}

const trade = (over: Record<string, unknown> = {}) => ({
  mint_address: "So11111111111111111111111111111111111111112",
  symbol: "WIF",
  entry_at: TODAY(9, 12),
  exit_at: TODAY(11, 40),
  exit_reason: "stop",
  ...over,
});

describe("today at HQ", () => {
  it("is empty when there is no audit at all", () => {
    expect(buildToday(UNKNOWN_HQ_STATE)).toEqual([]);
  });

  it("lists an entry and an exit for one completed trade", () => {
    const events = buildToday(withAudit([trade()]));
    expect(events).toHaveLength(2);
    expect(events[0]!.label).toContain("Paper entry");
    expect(events[1]!.label).toContain("Paper exit");
    expect(events[1]!.label).toContain("stop");
  });

  it("reads down the day, oldest first", () => {
    const events = buildToday(
      withAudit([trade({ entry_at: TODAY(13, 0), exit_at: TODAY(13, 30) }), trade()]),
    );
    const times = events.map((event) => event.at);
    expect([...times].sort((a, b) => a - b)).toEqual(times);
  });

  it("drops anything from before midnight UTC", () => {
    // "Today" has to mean the same day the backend buckets by, or the list
    // and the daily returns beside it describe different days.
    const events = buildToday(withAudit([trade({ entry_at: YESTERDAY, exit_at: YESTERDAY })]));
    expect(events).toEqual([]);
  });

  it("keeps an exit whose entry was yesterday", () => {
    const events = buildToday(withAudit([trade({ entry_at: YESTERDAY, exit_at: TODAY(10, 0) })]));
    expect(events).toHaveLength(1);
    expect(events[0]!.label).toContain("Paper exit");
  });

  it("falls back to a short mint when a token has no symbol", () => {
    const events = buildToday(withAudit([trade({ symbol: null })]));
    expect(events[0]!.label).toContain("So11");
  });

  it("invents no event for desks that publish no event log", () => {
    // Discovery, scoring and market publish one latest timestamp each and no
    // history. A row claiming "18:42 Radar discovered a token" would be a
    // history fabricated from a scalar.
    const events = buildToday(withAudit([trade()]));
    for (const event of events) {
      expect(event.who).toBe("rex");
    }
  });

  it("passes no judgement on any trade", () => {
    const text = buildToday(withAudit([trade()]))
      .map((event) => event.label)
      .join(" ")
      .toLowerCase();
    for (const word of ["good", "bad", "win", "loss", "profit", "great", "poor"]) {
      expect(text).not.toContain(word);
    }
  });
});
