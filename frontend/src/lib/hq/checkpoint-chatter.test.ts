import { describe, expect, it } from "vitest";

import { ROBOTS, type Checkpoint } from "@/lib/hq/checkpoint";
import { EMPLOYEES } from "@/lib/hq/employees";

import {
  LINE_TEMPLATES, MANAGER, TEAM_LEAD, award, banter, praiseBuy, praiseStop, reportLab, reportToday,
  reportWallets, scoldRug, solo, topStopper, voiceOf,
} from "./checkpoint-chatter";

const data: Checkpoint = {
  stopped_by: { repeat_rug_operator: 651, known_rug_money: 93, linked_to_recent_rug: 33 },
  safety_checked: 10, safety_allowed: 9, feed: [],
};

describe("the office's talk", () => {
  it("praises the person who really stopped the coin, by name and coin", () => {
    const i = ROBOTS.findIndex((r) => r.id === "recall");
    for (let seed = 0; seed < 40; seed++) {
      const line = praiseStop(i, "TVKJ", seed);
      expect(line.who).toBe("manager");
      expect(line.text).toContain("Rosa");
    }
    expect(praiseBuy("WINNY", 0).text).toContain("WINNY");
  });

  it("scolds only over a named rug and hands the award to the real top stopper", () => {
    expect(scoldRug("TVKJ", 1).text).toContain("TVKJ");
    expect(scoldRug("TVKJ", 1).mood).toBe("angry");
    expect(topStopper(data)).toEqual({ index: ROBOTS.findIndex((r) => r.id === "recall"), count: 651 });
    expect(award(data, 0)!.text).toContain("651");
    expect(award(undefined, 0)).toBeNull();
  });

  it("lets two neighbours from the same hall chat", () => {
    for (let seed = 0; seed < 60; seed++) {
      const [ask, answer] = banter(seed);
      expect(ask.who).not.toBe(answer.who);
      expect(ROBOTS[ask.who as number]!.stage).toBe(ROBOTS[answer.who as number]!.stage);
    }
  });

  it("gives the manager his own name and everyone a voice in range", () => {
    expect(EMPLOYEES.map((e) => e.name)).not.toContain(MANAGER.first);
    expect(ROBOTS.map((r) => r.first)).not.toContain(MANAGER.first);
    for (const who of [...ROBOTS.keys(), "manager" as const]) {
      const v = voiceOf(who);
      expect(v.pitch).toBeGreaterThan(0.5);
      expect(v.pitch).toBeLessThan(1.5);
    }
  });
});


describe("plenty to say", () => {
  it("has well over a hundred line templates, every one filled in", () => {
    expect(LINE_TEMPLATES).toBeGreaterThan(150);
    for (let seed = 0; seed < 300; seed++) {
      const [ask, answer] = banter(seed);
      for (const line of [ask, answer, solo(seed)]) {
        expect(line.text).not.toMatch(/[{}]/);
        expect(ROBOTS[line.who as number]).toBeDefined();
      }
    }
    for (let seed = 0; seed < 40; seed++) {
      expect(scoldRug("ADTF", seed).text).toContain("ADTF");
      expect(praiseBuy("WINNY", seed).text).toContain("WINNY");
    }
  });
});


describe("Layla reads out the money", () => {
  const lab = { started_at: "2026-09-30T20:00:00Z", capital_usd: "500", pnl_usd: "173.30",
                trades: 272, wins: 250, rugs: 8 };
  it("reads the lab's real figures, cheering a profit and rallying a loss", () => {
    const up = reportLab(lab, 0)!;
    expect(up.who).toBe("lead");
    expect(up.text).toContain("plus $173.30");
    expect(up.mood).toBe("happy");
    const down = reportLab({ ...lab, pnl_usd: "-12.5" }, 0)!;
    expect(down.text).toContain("minus $12.50");
    expect(down.mood).toBe("sad");
    expect(reportLab(undefined, 0)).toBeNull();
  });

  it("reads the real wallets only when they were given, and today only when it traded", () => {
    const rows = [
      { label: "Karthik", all_pnl_usd: "4.20", today_pnl_usd: "1.10", today_trades: 3, today_won: 2 },
      { label: "Paper 1", all_pnl_usd: "-2.00", today_pnl_usd: "0", today_trades: 0, today_won: 0 },
    ];
    expect(reportWallets(rows, 0)!.text).toContain("Karthik plus $4.20, Paper 1 minus $2.00");
    expect(reportToday(rows, 0)!.text).toContain("plus $1.10");
    expect(reportWallets(undefined, 0)).toBeNull();
    expect(reportToday([{ ...rows[0]!, today_trades: 0 }], 0)).toBeNull();
    expect([MANAGER.first, ...ROBOTS.map((r) => r.first)]).not.toContain(TEAM_LEAD.first);
    expect(EMPLOYEES.map((e) => e.name)).not.toContain(TEAM_LEAD.first);
  });
});
