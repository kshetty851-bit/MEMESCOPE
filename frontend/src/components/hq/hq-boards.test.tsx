import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ExecutionVault, MissionBoard, PerformanceLab } from "./hq-boards";
import { deriveHqState, type Source } from "@/lib/hq/adapter";
import type { ExecutionPosture, TokenSecuritySummary } from "@/lib/hq/pipeline";
import type { PaperWallet } from "@/types/paper";

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

function wallet(overrides: Record<string, unknown> = {}): PaperWallet {
  return {
    enabled: true,
    strategy: { id: "trailing_stop_25_secured_v2", name: "Trailing Stop 25% (security-gated)" },
    generation: 7,
    metrics: {
      starting_balance: "1000", cash: "13.76", equity: null, roi_pct: "1.38",
      return_usd: null, open_value: null, known_partial_equity: "13.76",
      invested_usd: "1400", unpriced_positions: 2, priced_positions: 12,
      open_positions: 14, closed_positions: 168, realised_pnl: "413.76",
      win_rate_pct: "31.40", average_win: null, average_loss: null,
      profit_factor: "1.15",
    },
    ...overrides,
  } as unknown as PaperWallet;
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
    for (const label of [
      "Scanner / discovery", "Market data", "Enrichment queue", "Scoring",
      "Paper Wallet", "Security gate", "Paper execution", "Track record",
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
  it("shows the active generation and that the gate is strict", () => {
    render(
      <PerformanceLab wallet={source(wallet())} security={source(security())} now={NOW} />,
    );
    expect(screen.getByText("Gen 7")).toBeInTheDocument();
    expect(screen.getByText("STRICT")).toBeInTheDocument();
  });

  it("says NOT ENFORCED for an ungated generation rather than staying silent", () => {
    render(
      <PerformanceLab
        wallet={source(wallet({ generation: 2, strategy: { id: "trailing_stop_25_v1", name: "Trailing Stop 25%" } }))}
        security={source(security())}
        now={NOW}
      />,
    );
    expect(screen.getByText("NOT ENFORCED")).toBeInTheDocument();
  });

  it("withholds equity rather than substituting cost when a holding is unpriced", () => {
    render(
      <PerformanceLab wallet={source(wallet())} security={source(security())} now={NOW} />,
    );
    expect(within(row("Equity")).getByText("No data")).toBeInTheDocument();
    // ...while cost, which is genuinely known, is shown.
    expect(screen.getByText("$1,400.00")).toBeInTheDocument();
  });

  it("reads No data throughout when the wallet could not be fetched", () => {
    render(
      <PerformanceLab
        wallet={source<PaperWallet>(null, null, true)}
        security={source<TokenSecuritySummary>(null, null, true)}
        now={NOW}
      />,
    );
    expect(screen.getAllByText("No data").length).toBeGreaterThanOrEqual(10);
  });

  it("counts security-blocked candidates from failed plus unverified", () => {
    render(
      <PerformanceLab
        wallet={source(wallet())}
        security={source(security({ failed_count: 2, unknown_count: 5 }))}
        now={NOW}
      />,
    );
    expect(within(row("Security-blocked candidates")).getByText("7")).toBeInTheDocument();
  });
});
