import fs from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

import { ANALYST_STRATEGY, deriveHqState, type RafiqAnalysis } from "@/lib/hq/adapter";
import { EMPLOYEES, EMPLOYEE_BY_ID } from "@/lib/hq/employees";

const NOW = 1_760_000_000_000;

function analysis(over: Partial<RafiqAnalysis> = {}): RafiqAnalysis {
  return {
    code: "A",
    lane: "hard_stop_guard",
    measured: true,
    detail: "Computed from this strategy's own position rows.",
    verdict: "$-424.22 realised over 56 settled trades, 30% of them profitable.",
    open_positions: 0,
    closed_positions: 56,
    figures: [{ label: "Realised P&L", value: "$-424.22", source: "exit_proceeds_usd" }],
    findings: [],
    ...over,
  };
}

function build(rows: RafiqAnalysis[] | null) {
  return deriveHqState({
    now: NOW,
    rafiqAnalysis:
      rows === null
        ? { data: null, observedAt: null, failed: true }
        : { data: rows, observedAt: NOW, failed: false },
  });
}

describe("the analytics wing", () => {
  it("agrees with the backend about who answers for which strategy", () => {
    // Two hardcoded maps, one in TypeScript and one in Python, and a desk
    // reporting the wrong strategy's book would look completely normal — the
    // figures would be real, the trades would be real, and they would belong
    // to somebody else. Nothing else in either codebase would catch it, so
    // the file is read as text and compared.
    const desk = fs.readFileSync(
      path.join(process.cwd(), "../backend/app/hq_ops/desk.py"),
      "utf8",
    );
    const block = desk.match(/ANALYSTS: dict\[str, str\] = \{([^}]*)\}/);
    expect(block, "ANALYSTS was renamed or removed in desk.py").not.toBeNull();

    const backend = Object.fromEntries(
      [...block![1].matchAll(/"(\w+)":\s*"(\w+)"/g)].map((m) => [m[1], m[2]]),
    );
    expect(backend).toEqual(ANALYST_STRATEGY);
  });

  it("puts exactly one analyst on each of the lab's five strategies", () => {
    expect(Object.values(ANALYST_STRATEGY).sort()).toEqual(["A", "B", "C", "D", "E"]);
    for (const id of Object.keys(ANALYST_STRATEGY)) {
      const who = EMPLOYEE_BY_ID.get(id as never);
      expect(who, `${id} is not on the roster`).toBeDefined();
      expect(who!.zone).toBe("rafiq");
    }
    // Nobody outside the wing is quietly given a strategy as a second hat.
    const inWing = EMPLOYEES.filter((e) => e.zone === "rafiq").map((e) => e.id);
    expect(inWing.sort()).toEqual(Object.keys(ANALYST_STRATEGY).sort());
  });

  it("reports every analyst as unread when the lab does not answer", () => {
    const state = build(null);
    for (const id of Object.keys(ANALYST_STRATEGY)) {
      const desk = state.employees[id as never];
      expect(desk.state, id).toBe("unknown");
      // Never a zero, never a flat book, never quiet-looking.
      expect(desk.metrics, id).toHaveLength(0);
    }
  });

  it("says a strategy that has never traded has not traded", () => {
    const state = build([
      analysis({
        code: "E",
        measured: false,
        detail: "This strategy has not opened a position yet.",
      }),
    ]);
    expect(state.employees.chorus.state).toBe("unknown");
    // The backend's sentence, not a second wording of it.
    expect(state.employees.chorus.detail).toBe(
      "This strategy has not opened a position yet.",
    );
  });

  it("distinguishes an unreachable lab from a lab missing an arm", () => {
    const missing = build([analysis({ code: "A" })]);
    expect(missing.employees.anchor.state).toBe("idle");
    // B..E were not in the payload. That is a different fact from the lab
    // being down, and it must not read the same.
    expect(missing.employees.tempo.detail).toContain("Strategy B");
    expect(missing.employees.tempo.detail).not.toEqual(build(null).employees.tempo.detail);
  });

  it("watches while the arm is holding, and is idle when it is flat", () => {
    // Deliberately NOT keyed to whether findings exist: a finding is a
    // standing property of a record rather than an event, so keying on it
    // would pin all five desks to one state for ever and peg the whole
    // office's activity meter along with them.
    const flat = build([analysis({ code: "A", open_positions: 0, findings: [
      { key: "asymmetry", headline: "h", evidence: "e", lever: "l", source: "s" },
    ] })]);
    expect(flat.employees.anchor.state).toBe("idle");

    const holding = build([analysis({ code: "A", open_positions: 3, findings: [] })]);
    expect(holding.employees.anchor.state).toBe("reviewing");
  });

  it("never paints a losing strategy as a fault", () => {
    // The lab exists to find out whether these rules lose money. A red desk
    // would be the office asserting a verdict the experiment has not reached,
    // and a green one would call a sample an achievement.
    for (const open of [0, 4]) {
      const state = build([
        analysis({ code: "A", open_positions: open, verdict: "$-424.22 realised" }),
      ]);
      expect(["alert", "error", "incident", "success"]).not.toContain(
        state.employees.anchor.state,
      );
    }
  });

  it("carries every figure through with the columns behind it", () => {
    const state = build([
      analysis({
        code: "A",
        figures: [
          { label: "Breakeven win rate", value: "53%", source: "avg_loss / (avg_win + avg_loss)" },
        ],
      }),
    ]);
    expect(state.employees.anchor.metrics).toEqual([
      { label: "Breakeven win rate", value: "53%", source: "avg_loss / (avg_win + avg_loss)" },
    ]);
  });
});
