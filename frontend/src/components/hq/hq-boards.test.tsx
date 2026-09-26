import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ExecutionVault, MissionBoard, PerformanceLab } from "./hq-boards";
import { deriveHqState, type Source } from "@/lib/hq/adapter";
import type { ExecutionPosture, TokenSecuritySummary } from "@/lib/hq/pipeline";
import type { KarthikLabSummary } from "@/lib/hq/karthik-lab";

/**
 * The boards are where a summary could most easily lie: four true rows and a
 * missing one, averaged into a green headline. Every test here is a variation
 * on "does the absent case still read as absent".
 */

const NOW = 1_760_000_000_000;

function source<T>(data: T | null, observedAt: number | null = NOW, failed = false): Source<T> {
  return { data, observedAt, failed };
}

function posture(overrides: Partial<ExecutionPosture> = {}): ExecutionPosture {
  return {
    state: "LOCKED",
    detail: "Execution is disabled.",
    mode: "disabled",
    execution_enabled: false,
    autotrade_enabled: false,
    network: "devnet",
    kill_switches: [],
    active_kill_switches: 0,
    observed_at: new Date(NOW).toISOString(),
    sourced: true,
    ...overrides,
  };
}

function security(overrides: Partial<TokenSecuritySummary> = {}): TokenSecuritySummary {
  return {
    window_hours: 24, evaluator_version: "1.1.0", evaluated_recently: 60,
    verified_count: 53, failed_count: 0, unknown_count: 7, failures_by_reason: {},
    last_evaluation_at: new Date(NOW).toISOString(), total_evaluations: 400,
    source_state: "live", observed_at: new Date(NOW).toISOString(), ...overrides,
  };
}

function row(label: string) {
  return screen.getByText(label).closest("div")!.parentElement!;
}

describe("Execution Vault", () => {
  it("reports LOCKED when execution is disabled", () => {
    render(<ExecutionVault source={source(posture())} now={NOW} />);
    expect(screen.getByText("LOCKED")).toBeInTheDocument();
  });

  it("is UNKNOWN — never LOCKED — when the posture cannot be read", () => {
    // The dangerous default. "We could not check" must not read as "safe".
    render(<ExecutionVault source={source<ExecutionPosture>(null, null, true)} now={NOW} />);
    expect(screen.getByText("UNKNOWN")).toBeInTheDocument();
    expect(screen.queryByText("LOCKED")).not.toBeInTheDocument();
  });

  it("is UNKNOWN when the reading has aged past its window", () => {
    render(<ExecutionVault source={source(posture(), NOW - 10_000_000)} now={NOW} />);
    expect(screen.getByText("UNKNOWN")).toBeInTheDocument();
  });

  it("shows HALTED when a kill switch is active", () => {
    render(
      <ExecutionVault
        source={source(
          posture({
            state: "HALTED",
            active_kill_switches: 1,
            kill_switches: [
              { kind: "global", active: true, reason: "manual", activated_at: null },
            ],
          }),
        )}
        now={NOW}
      />,
    );
    expect(screen.getByText("HALTED")).toBeInTheDocument();
  });

  it("never renders a control that could change the posture", () => {
    const { container } = render(<ExecutionVault source={source(posture())} now={NOW} />);
    expect(container.querySelectorAll("button")).toHaveLength(0);
    expect(container.querySelectorAll("input")).toHaveLength(0);
  });

  it("shows every row even when unavailable, rather than hiding it", () => {
    // An omitted row reads as "nothing to worry about".
    render(<ExecutionVault source={source<ExecutionPosture>(null, null, true)} now={NOW} />);
    for (const label of ["Execution mode", "Execution enabled", "Autotrade", "Network"]) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
    expect(screen.getAllByText("No data").length).toBeGreaterThanOrEqual(4);
  });
});

describe("Mission Board", () => {
  it("renders one row per subsystem", () => {
    render(<MissionBoard state={deriveHqState({ now: NOW })} />);
    // "Market data", "Scoring" and "Track record" went with Luna, Dex and
    // Sage on 2026-09-08: three rows reading one `activity` source between
    // them. "Paper execution" went with Rex on 2026-09-24 — it is the Paper
    // Wallet row's. What each remaining row reports is a distinct measurement.
    for (const label of [
      "Scanner / discovery", "Enrichment queue", "Karthik's Lab", "Security gate",
    ]) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
  });

  it("reads UNKNOWN for every desk when nothing has been fetched", () => {
    render(<MissionBoard state={deriveHqState({ now: NOW })} />);
    expect(screen.getAllByText("UNKNOWN").length).toBeGreaterThanOrEqual(8);
  });
});

describe("Performance Lab", () => {
  // Karthik's Lab since 2026-09-26; it was the retired Paper Wallet before.
  const lab = (over: Partial<KarthikLabSummary> = {}): KarthikLabSummary => ({
    started_at: "2026-09-23T12:00:00Z",
    judge_at: "2026-10-23T12:00:00Z",
    capital_usd: "400",
    ticket_usd: "200",
    balance_usd: "777.80",
    pnl_usd: "377.80",
    pnl_pct: "94.45",
    trades: 125,
    wins: 118,
    rugs: 0,
    ...over,
  });

  it("shows Karthik's Lab as the lab publishes it", () => {
    render(<PerformanceLab lab={source(lab())} security={source(security())} now={NOW} />);
    expect(within(row("Balance")).getByText("$777.80")).toBeInTheDocument();
    expect(within(row("Profit")).getByText("$377.80")).toBeInTheDocument();
    expect(within(row("Return")).getByText("+94.45%")).toBeInTheDocument();
    expect(within(row("Win rate")).getByText("94.4%")).toBeInTheDocument();
    expect(within(row("Judged on")).getByText("23 Oct")).toBeInTheDocument();
  });

  it("counts rugs, and says what one is", () => {
    render(<PerformanceLab lab={source(lab({ rugs: 2 }))} security={source(security())} now={NOW} />);
    expect(within(row("Rugs")).getByText("2")).toBeInTheDocument();
  });

  it("reads No data throughout when the book could not be fetched", () => {
    render(
      <PerformanceLab
        lab={source<KarthikLabSummary>(null, null, true)}
        security={source<TokenSecuritySummary>(null, null, true)}
        now={NOW}
      />,
    );
    expect(screen.getAllByText("No data").length).toBeGreaterThanOrEqual(7);
  });

  it("counts security-blocked candidates from failed plus unverified", () => {
    render(
      <PerformanceLab
        lab={source(lab())}
        security={source(security({ failed_count: 2, unknown_count: 5 }))}
        now={NOW}
      />,
    );
    expect(within(row("Security-blocked candidates")).getByText("7")).toBeInTheDocument();
  });
});
