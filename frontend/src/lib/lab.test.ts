import { describe, expect, it } from "vitest";

import { EXIT_ORDER, sortLab } from "@/lib/paper";
import { bucket } from "@/components/paper/lab-charts";
import type { LabStrategy } from "@/types/paper";

/**
 * Strategy Lab presentation.
 *
 * Sorting reorders; it never re-scores. The rank the backend assigned is the
 * published one, and a second ranking computed here could disagree with the
 * findings served beside it.
 */

function strategy(overrides: Partial<LabStrategy> = {}): LabStrategy {
  return {
    id: "probe",
    name: "Probe",
    description: "",
    rules: [],
    is_baseline: false,
    invested: "8200",
    total_return_pct: "10.00",
    realised_return_pct: "5.00",
    open_share_pct: "20.00",
    baseline_difference_pct: "14.00",
    annualised_return_pct: null,
    annualised_unavailable_reason: "Not shown.",
    closed_count: 60,
    open_count: 20,
    win_rate_pct: "30.00",
    profit_factor: "1.20",
    average_win: "50.00",
    average_loss: "20.00",
    largest_winner: "100.00",
    largest_loser: "-50.00",
    max_drawdown_pct: "12.00",
    average_hold_hours: "20.00",
    average_peak_pct: "80.00",
    average_giveback_pct: "30.00",
    exits_by_reason: { target: 10, stop: 40, expiry: 10 },
    rank: 2,
    equity_curve: [],
    return_distribution: [],
    hold_distribution: [],
    ...overrides,
  };
}

describe("sortLab", () => {
  const a = strategy({ id: "a", rank: 1, total_return_pct: "50", max_drawdown_pct: "30", closed_count: 10 });
  const b = strategy({ id: "b", rank: 2, total_return_pct: "10", max_drawdown_pct: "2", closed_count: 90 });
  const c = strategy({ id: "c", rank: 3, total_return_pct: "-5", max_drawdown_pct: "15", closed_count: 50 });
  const rows = [a, b, c];

  it("does not mutate the table it was given", () => {
    const before = rows.map((row) => row.id);
    sortLab(rows, "total");
    expect(rows.map((row) => row.id)).toEqual(before);
  });

  it("defaults to the published rank", () => {
    expect(sortLab([c, a, b], "rank").map((row) => row.id)).toEqual(["a", "b", "c"]);
  });

  it("orders return best first", () => {
    expect(sortLab(rows, "total").map((row) => row.id)).toEqual(["a", "b", "c"]);
  });

  it("puts the smallest drawdown first, because a smaller fall is better", () => {
    expect(sortLab(rows, "drawdown").map((row) => row.id)).toEqual(["b", "c", "a"]);
  });

  it("sinks unmeasured values rather than ranking them as zero", () => {
    // A strategy that has closed nothing has not out-performed one that lost.
    const unmeasured = strategy({ id: "x", rank: 9, total_return_pct: null });
    expect(sortLab([unmeasured, c], "total").map((row) => row.id)).toEqual(["c", "x"]);
  });

  it("breaks ties on the published rank so the order is stable", () => {
    const first = strategy({ id: "p", rank: 1, total_return_pct: "10" });
    const second = strategy({ id: "q", rank: 4, total_return_pct: "10" });
    expect(sortLab([second, first], "total").map((row) => row.id)).toEqual(["p", "q"]);
  });
});

describe("EXIT_ORDER", () => {
  it("is fixed so columns line up between strategies", () => {
    expect([...EXIT_ORDER]).toEqual(["target", "stop", "expiry"]);
  });
});

describe("bucket", () => {
  it("returns nothing for an empty set rather than an empty chart", () => {
    expect(bucket([], 5, (a, b) => `${a}-${b}`)).toEqual([]);
  });

  it("collapses a single-valued set into one bucket", () => {
    // Six identical buckets, five of them empty, would imply a spread.
    expect(bucket([4, 4, 4], 6, (a) => `${a}`)).toEqual([{ label: "4", count: 3 }]);
  });

  it("counts every value exactly once", () => {
    const values = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10];
    const buckets = bucket(values, 4, (a, b) => `${a}-${b}`);
    expect(buckets.reduce((sum, item) => sum + item.count, 0)).toBe(values.length);
  });

  it("is deterministic, so a chart does not reshape between renders", () => {
    const values = [1, 5, 5, 9, 12];
    const label = (a: number, b: number) => `${a.toFixed(1)}-${b.toFixed(1)}`;
    expect(bucket(values, 4, label)).toEqual(bucket(values, 4, label));
  });
});
