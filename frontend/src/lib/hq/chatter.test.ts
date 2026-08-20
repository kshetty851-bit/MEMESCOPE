import { describe, expect, it } from "vitest";

import { deriveHqState, react, witness, type HqWitness } from "@/lib/hq/adapter";
import { CHATTER, CHATTER_EVERY, MAX_CHATTER_LENGTH } from "@/lib/hq/chatter";
import { EMPLOYEES } from "@/lib/hq/employees";

/**
 * The line between what a timer may say and what only an observation may say.
 *
 * This is the file that keeps ambient life from becoming an unsourced status
 * display. If it ever goes green while a bubble says "feeds stable" on a
 * three-second interval, the whole HQ premise is gone.
 */

const OPERATIONAL_WORDS = [
  "queue",
  "feed",
  "token",
  "candidate",
  "liquidity",
  "score",
  "position",
  "capital",
  "security",
  "verified",
  "stable",
  "healthy",
  "normal",
  "alert",
  "market",
  "wallet",
  "trade",
  "profit",
  "loss",
  "exit",
];

describe("ambient chatter says nothing about the system", () => {
  it("mentions no subsystem, status or figure anywhere", () => {
    for (const entry of CHATTER) {
      for (const line of entry.lines) {
        const lower = line.toLowerCase();
        for (const word of OPERATIONAL_WORDS) {
          expect(lower, `${entry.actor} says "${line}"`).not.toContain(word);
        }
        expect(/\d/.test(line), `${entry.actor} quotes a number in "${line}"`).toBe(false);
      }
    }
  });

  it("keeps every line short enough to read in one glance", () => {
    for (const entry of CHATTER) {
      for (const line of entry.lines) {
        expect(line.length, `${entry.actor}: "${line}"`).toBeLessThanOrEqual(MAX_CHATTER_LENGTH);
      }
    }
  });

  it("gives all ten employees a voice", () => {
    const speakers = new Set(CHATTER.map((entry) => entry.actor));
    for (const employee of EMPLOYEES) {
      expect(speakers.has(employee.id), `${employee.id} never speaks`).toBe(true);
    }
  });

  it("stays sparse", () => {
    expect(CHATTER_EVERY).toBeGreaterThanOrEqual(2);
  });
});

function base(over: Partial<HqWitness> = {}): HqWitness {
  return {
    auditTotal: 10,
    openPositions: 3,
    lastCloseNet: "1.00",
    radarOpportunities: 100,
    lastDiscovery: "2026-08-20T10:00:00Z",
    lastScore: "2026-08-20T10:00:00Z",
    lastSnapshot: "2026-08-20T10:00:00Z",
    securityEvaluations: 5,
    queueDepth: 20,
    pipelineOverall: "healthy",
    ...over,
  };
}

describe("reactions fire on observed change and never on a timer", () => {
  const NOW = 1_760_000_000_000;

  it("says nothing at all when nothing moved", () => {
    expect(react(base(), base(), NOW)).toEqual({});
  });

  it("says nothing on the first observation, because there is no before", () => {
    expect(react(null, base(), NOW)).toEqual({});
  });

  it("wakes the right desk for each kind of change", () => {
    const cases: Array<[Partial<HqWitness>, string]> = [
      [{ lastDiscovery: "2026-08-20T10:01:00Z" }, "radar"],
      [{ lastScore: "2026-08-20T10:01:00Z" }, "luna"],
      [{ lastSnapshot: "2026-08-20T10:01:00Z" }, "dex"],
      [{ securityEvaluations: 6 }, "atlas"],
      [{ queueDepth: 21 }, "echo"],
      [{ pipelineOverall: "degraded" }, "byte"],
      [{ radarOpportunities: 101 }, "sage"],
      [{ auditTotal: 11 }, "rex"],
    ];
    for (const [change, who] of cases) {
      const out = react(base(), base(change), NOW);
      expect(Object.keys(out), JSON.stringify(change)).toContain(who);
    }
  });

  it("never claims a security verdict, only that an evaluation ran", () => {
    const out = react(base(), base({ securityEvaluations: 6 }), NOW);
    const said = `${out.atlas?.detail} ${out.atlas?.speech}`.toLowerCase();
    // "Verified" and "safe" are verdicts. Atlas's panel reports those from
    // evidence; a bubble must not.
    expect(said).not.toContain("verified");
    expect(said).not.toContain("safe");
    expect(said).not.toContain("passed");
  });

  it("only lets Nova speak for the platform roll-up", () => {
    expect(react(base(), base({ queueDepth: 99 }), NOW).nova).toBeUndefined();
    expect(react(base(), base({ lastDiscovery: "x" }), NOW).nova).toBeUndefined();
    expect(react(base(), base({ pipelineOverall: "degraded" }), NOW).nova).toBeDefined();
  });

  it("expires, so a bubble cannot outlive the change behind it", () => {
    const out = react(base(), base({ queueDepth: 21 }), NOW);
    expect(out.echo!.until).toBeGreaterThan(NOW);
    const live = deriveHqState({
      now: out.echo!.until + 1,
      transients: out,
    });
    expect(live.employees.echo.speech).toBeUndefined();
  });
});

describe("the witness reads only what the contract publishes", () => {
  it("reports nulls rather than zeros when there are no sources", () => {
    const seen = witness({});
    for (const value of Object.values(seen)) {
      expect(value).toBeNull();
    }
  });
});
