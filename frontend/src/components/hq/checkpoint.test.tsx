import { act, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { EMPLOYEES } from "@/lib/hq/employees";
import {
  ROBOTS, robotIndexFor, stoppedBy, type Checkpoint, type LiveBelt,
} from "@/lib/hq/checkpoint";

import { CheckpointOffice } from "./checkpoint";

const data: Checkpoint = {
  stopped_by: {
    POSITION_TOO_LARGE_FOR_LIQUIDITY: 48, BUY_PRICE_IMPACT_TOO_HIGH: 34,
    SELL_PRICE_IMPACT_TOO_HIGH: 25, linked_to_recent_rug: 29,
  },
  safety_checked: 935,
  safety_allowed: 835,
  feed: [
    { kind: "stopped", symbol: "ARROW", at: "2026-10-02T14:16:51Z", code: "linked_to_recent_rug", rugged: true },
    { kind: "bought", symbol: "WINNY", at: "2026-10-02T14:00:00Z", code: null, rugged: null },
  ],
};

describe("the thirty checkers", () => {
  it("are thirty, with their own names, none an HQ employee's", () => {
    expect(ROBOTS).toHaveLength(30);
    const names = ROBOTS.map((r) => r.name.toLowerCase());
    expect(new Set(names).size).toBe(30);
    expect(new Set(ROBOTS.map((r) => r.id)).size).toBe(30);
    const staff = new Set(EMPLOYEES.map((e) => e.name.toLowerCase()));
    expect(names.filter((n) => staff.has(n))).toEqual([]);
    expect(ROBOTS.filter((r) => r.stage === "rule")).toHaveLength(7);
    expect(ROBOTS.filter((r) => r.stage === "gate")).toHaveLength(8);
    expect(ROBOTS.filter((r) => r.stage === "safety")).toHaveLength(15);
  });

  it("are thirty people with their own first names and a line for every stop", () => {
    const firsts = ROBOTS.map((r) => r.first.toLowerCase());
    expect(new Set(firsts).size).toBe(30);
    const staff = new Set([...EMPLOYEES.map((e) => e.name.toLowerCase()), "karthik", "walt"]);
    expect(firsts.filter((n) => staff.has(n))).toEqual([]);
    expect(ROBOTS.every((r) => r.stopLine.length > 0 && r.stopLine.length <= 40)).toBe(true);
  });

  it("each refusal code belongs to exactly one robot", () => {
    const codes = ROBOTS.flatMap((r) => r.codes);
    expect(new Set(codes).size).toBe(codes.length);
  });

  it("counts a robot's stops from its own codes, and none for an unrecorded guard", () => {
    const impact = ROBOTS.find((r) => r.id === "impact")!;
    expect(stoppedBy(impact, data)).toBe(59);
    expect(stoppedBy(ROBOTS.find((r) => r.id === "purse")!, data)).toBeNull();
  });

  it("sends a stopped coin to its robot and a bought one past all thirty", () => {
    expect(ROBOTS[robotIndexFor(data.feed[0]!)]!.name).toBe("Tracer");
    expect(robotIndexFor(data.feed[1]!)).toBe(29);
  });
});

describe("the Checkpoint office, live", () => {
  const live: LiveBelt = {
    now: "2026-10-02T19:10:00Z",
    coins: [
      { symbol: "NEWC", graduated_at: "2026-10-02T19:09:40Z", status: "checking", robot: "depth",
        code: null, note: "waiting for the pool to show" },
      { symbol: "SMOL", graduated_at: "2026-10-02T19:08:00Z", status: "stopped", robot: "depth",
        code: null, note: "pool $20,203, under $75,000" },
      { symbol: "RUGGO", graduated_at: "2026-10-02T19:06:00Z", status: "stopped", robot: null,
        code: "linked_to_recent_rug", note: "a rug block refused it" },
      { symbol: "HELD", graduated_at: "2026-10-02T19:05:00Z", status: "stopped", robot: null,
        code: null, note: "passed the rule; the wallet did not take it (reason not recorded)" },
      { symbol: "WINNY", graduated_at: "2026-10-02T19:01:00Z", status: "bought", robot: "wallet",
        code: null, note: "passed all 30 and was bought" },
    ],
  };
  const now = Date.parse("2026-10-02T19:10:00Z");

  it("puts each coin at the check its records reached", () => {
    render(<CheckpointOffice data={data} live={live} motionOverride={false} now={now} />);
    for (const r of ROBOTS) expect(screen.getByTestId(`cp-bot-${r.id}`)).toBeInTheDocument();
    // Depth is still waiting on one pool, and has stopped another this window.
    expect(screen.getByTestId("cp-bot-depth")).toHaveAttribute("data-state", "scan");
    expect(screen.getByTestId("cp-bot-depth")).toHaveTextContent("NEWC");
    expect(screen.getByTestId("cp-bot-depth")).toHaveTextContent("1");
    expect(screen.getByTestId("cp-bot-tracer")).toHaveTextContent("1");
    expect(screen.getByTestId("checkpoint")).toHaveTextContent("5 graduated in 10 min");
    expect(screen.getByTestId("checkpoint")).toHaveTextContent("1 being checked now");
  });

  it("lists the latest coins in plain words, naming no robot it cannot", () => {
    render(<CheckpointOffice data={data} live={live} motionOverride={false} now={now} />);
    const list = screen.getByTestId("cp-live-list");
    expect(list).toHaveTextContent("NEWCDiego · Depthwaiting for the pool to show20s ago");
    expect(list).toHaveTextContent("SMOLDiego · Depthpool $20,203, under $75,000");
    expect(list).toHaveTextContent("RUGGOTariq · Tracer");
    expect(list).toHaveTextContent("HELDWallet gatepassed the rule; the wallet did not take it");
    expect(list).toHaveTextContent("WINNYBoughtpassed all 30 and was bought");
    expect(screen.getByTestId("cp-bot-scale")).toHaveTextContent("48 stopped");
    expect(screen.getByTestId("cp-asleep")).toBeInTheDocument();
  });

  it("rolls a newly graduated coin in from Hatch to where its records put it", () => {
    vi.useFakeTimers();
    try {
      const first: LiveBelt = { now: live.now, coins: [live.coins[4]!] };
      const { rerender } = render(<CheckpointOffice data={data} live={first} motionOverride now={now} />);
      const arrived: LiveBelt = { now: live.now, coins: [
        { ...live.coins[2]!, graduated_at: "2026-10-02T19:09:59Z", symbol: "FRESH" }, live.coins[4]!] };
      rerender(<CheckpointOffice data={data} live={arrived} motionOverride now={now} />);
      expect(screen.getByTestId("cp-bot-hatch")).toHaveTextContent("FRESH");
      act(() => { vi.advanceTimersByTime(140 * 4); });
      // Tracer is the fifth robot: Hatch, Depth, Hush, Recall, Tracer.
      expect(screen.getByTestId("cp-bot-tracer")).toHaveTextContent("FRESH");
      expect(screen.getByTestId("cp-bot-tracer")).toHaveAttribute("data-state", "stop");
      expect(screen.getByTestId("cp-bot-tracer")).toHaveTextContent("STOP");
      expect(screen.getByTestId("cp-bubble-tracer")).toHaveTextContent(ROBOTS[4]!.stopLine);
    } finally {
      vi.useRealTimers();
    }
  });

  it("says it is waiting when nothing graduated lately", () => {
    render(<CheckpointOffice data={data} live={{ now: live.now, coins: [] }}
                             motionOverride={false} now={now} />);
    expect(screen.getByTestId("cp-live-list")).toHaveTextContent("waiting for the next one");
  });
});
