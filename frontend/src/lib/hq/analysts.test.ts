import { describe, expect, it } from "vitest";

import { ANALYST_ORDER, deriveHqState, type RafiqAnalysis } from "@/lib/hq/adapter";
import { EMPLOYEES, EMPLOYEE_BY_ID } from "@/lib/hq/employees";

const NOW = 1_760_000_000_000;

function analysis(over: Partial<RafiqAnalysis> = {}): RafiqAnalysis {
  return {
    analyst: "anchor",
    code: "A2",
    lane: "hard_stop_guard",
    measured: true,
    detail: "Computed from this strategy's own position rows.",
    verdict: "$-165.87 realised over 69 settled trades, 54% of them profitable.",
    open_positions: 0,
    closed_positions: 69,
    figures: [{ label: "Realised P&L", value: "$-165.87", source: "exit_proceeds_usd" }],
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

const FIVE = ANALYST_ORDER.map((id, i) =>
  analysis({ analyst: id, code: `${"ABCDE"[i]}2` }),
);

describe("the analytics wing", () => {
  /**
   * THE REGRESSION TEST FOR THE OUTAGE.
   *
   * The old version of this file asserted that the TypeScript code-map equalled
   * the Python one. Both were hardcoded to A-E; when the lab shipped v2 with
   * A2-E2 the two copies still agreed with each other, the test stayed green,
   * and all five desks reported "No strategy 'A' is registered" on the live
   * site for a day. Agreement between two copies of a wrong answer is not a
   * check.
   *
   * The check below is BEHAVIOURAL on purpose. The first version of it scanned
   * the source for a pinned code and failed — on the comment above explaining
   * the bug. Grepping source matches the prose that warns about the thing as
   * readily as the thing. Feeding the adapter codes it has never seen proves
   * the same property and cannot be fooled by its own documentation.
   */
  it("lights every desk up whatever the lab calls its strategies today", () => {
    // The exact shape of the v2 cutover. Codes the browser has never heard of.
    for (const rows of [
      FIVE,
      ANALYST_ORDER.map((id, i) => analysis({ analyst: id, code: `v3-${i}` })),
    ]) {
      const state = build(rows);
      for (const id of ANALYST_ORDER) {
        expect(state.employees[id as never].state, id).not.toBe("unknown");
      }
    }
  });

  it("seats exactly the five analysts on the roster, in order", () => {
    for (const id of ANALYST_ORDER) {
      const who = EMPLOYEE_BY_ID.get(id as never);
      expect(who, `${id} is not on the roster`).toBeDefined();
      expect(who!.zone).toBe("rafiq");
    }
    const inWing = EMPLOYEES.filter((e) => e.zone === "rafiq").map((e) => e.id);
    expect(inWing).toEqual([...ANALYST_ORDER]);
  });

  it("reports every analyst as unread when the lab does not answer", () => {
    const state = build(null);
    for (const id of ANALYST_ORDER) {
      const desk = state.employees[id as never];
      expect(desk.state, id).toBe("unknown");
      expect(desk.metrics, id).toHaveLength(0);
    }
  });

  it("distinguishes an unreachable lab from a lab with fewer arms than desks", () => {
    const short = build([analysis({ analyst: "anchor", code: "A2" })]);
    expect(short.employees.anchor.state).toBe("idle");
    expect(short.employees.tempo.detail).not.toEqual(build(null).employees.tempo.detail);
    expect(short.employees.tempo.state).toBe("unknown");
  });

  it("says a strategy that has never traded has not traded", () => {
    const state = build([
      analysis({
        analyst: "chorus",
        code: "E2",
        measured: false,
        detail: "This strategy has not opened a position yet.",
      }),
    ]);
    expect(state.employees.chorus.state).toBe("unknown");
    expect(state.employees.chorus.detail).toBe("This strategy has not opened a position yet.");
  });

  it("watches while the arm is holding, and is idle when it is flat", () => {
    const flat = build([analysis({ analyst: "anchor", open_positions: 0 })]);
    expect(flat.employees.anchor.state).toBe("idle");
    const holding = build([analysis({ analyst: "anchor", open_positions: 3 })]);
    expect(holding.employees.anchor.state).toBe("reviewing");
  });

  it("never paints a losing strategy as a fault", () => {
    for (const open of [0, 4]) {
      const state = build([analysis({ analyst: "anchor", open_positions: open })]);
      expect(["alert", "error", "incident", "success"]).not.toContain(
        state.employees.anchor.state,
      );
    }
  });

  it("carries every figure through with the columns behind it", () => {
    const state = build([
      analysis({
        analyst: "anchor",
        figures: [
          { label: "Breakeven win rate", value: "67%", source: "avg_loss / (avg_win + avg_loss)" },
        ],
      }),
    ]);
    expect(state.employees.anchor.metrics).toEqual([
      { label: "Breakeven win rate", value: "67%", source: "avg_loss / (avg_win + avg_loss)" },
    ]);
  });
});
