import { describe, expect, it } from "vitest";

import { ROBOTS, type Checkpoint } from "@/lib/hq/checkpoint";
import { EMPLOYEES } from "@/lib/hq/employees";

import {
  LINE_TEMPLATES, MANAGER, award, banter, praiseBuy, praiseStop, scoldRug, solo, topStopper,
  voiceOf,
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
