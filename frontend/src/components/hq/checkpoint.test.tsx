import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { EMPLOYEES } from "@/lib/hq/employees";
import { ROBOTS, robotIndexFor, stoppedBy, type Checkpoint } from "@/lib/hq/checkpoint";

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

describe("the thirty robots", () => {
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

describe("the Checkpoint office", () => {
  it("shows every robot, its count, the sleeper, and where the newest coin stopped", () => {
    render(<CheckpointOffice data={data} motionOverride={false}
                             now={Date.parse("2026-10-02T14:26:51Z")} />);
    for (const r of ROBOTS) expect(screen.getByTestId(`cp-bot-${r.id}`)).toBeInTheDocument();
    expect(screen.getByTestId("cp-bot-scale")).toHaveTextContent("48 stopped");
    expect(screen.getByTestId("cp-bot-purse")).toHaveTextContent("guard");
    expect(screen.getByTestId("cp-asleep")).toBeInTheDocument();
    // Without motion the newest coin sits where it ended: stopped by Tracer.
    expect(screen.getByTestId("cp-bot-tracer")).toHaveAttribute("data-state", "stop");
    expect(screen.getByTestId("cp-bot-tracer")).toHaveTextContent("STOP");
    expect(screen.getByTestId("cp-caption")).toHaveTextContent("ARROW stopped by Tracer · 10 min ago");
    expect(screen.getByTestId("checkpoint")).toHaveTextContent("1into the wallet");
    expect(screen.getByTestId("checkpoint")).toHaveTextContent("1in the rug bin");
  });

  it("says it is waiting before any coin has come through", () => {
    render(<CheckpointOffice data={{ ...data, feed: [] }} motionOverride={false} />);
    expect(screen.getByTestId("cp-caption")).toHaveTextContent("Waiting for the first coin");
  });
});
