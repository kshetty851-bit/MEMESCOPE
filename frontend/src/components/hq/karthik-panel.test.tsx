import { render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { DeskInstruments } from "@/components/hq/desks";
import { HqStage } from "@/components/hq/hq-stage";
import { KarthikPanel } from "@/components/hq/karthik-panel";
import { deriveHqState, type Source } from "@/lib/hq/adapter";
import type { KarthikState, ScreenReading } from "@/lib/hq/karthik";

/**
 * THE PANEL, AND THE ONE THING IT MUST NEVER DO.
 *
 * Render a number for a wallet that does not exist. Every test below is some
 * version of that: an unmeasured screen shows its sentence, an absent figure
 * shows NOT AVAILABLE, an unscored experiment shows a dash rather than 0 or
 * 100, and the reader can tell "we looked and it is empty" from "we could not
 * look" without reading the source.
 */

// The stage reads `prefers-reduced-motion` on mount; jsdom has no
// `matchMedia`. Same stub the HQ suite uses.
beforeEach(() => {
  window.matchMedia = vi.fn().mockImplementation((query: string) => ({
    matches: false,
    media: query,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    addListener: vi.fn(),
    removeListener: vi.fn(),
    dispatchEvent: vi.fn(),
    onchange: null,
  }));
});

const NOW = 1_760_000_000_000;

function unmeasured(detail = "No Karthik Paper Wallet is designated."): ScreenReading {
  return { measured: false, detail, values: {}, rows: [] };
}

/** The real production shape today: the operator exists, the wallet does not. */
function unbound(over: Partial<KarthikState> = {}): KarthikState {
  const blank = unmeasured();
  return {
    binding: {
      state: "unbound",
      designated_strategy_id: "",
      detail: "No Karthik Paper Wallet is designated.",
      readable: false,
      needs_owner: false,
      wallet_id: null,
      strategy_version: null,
      generation: null,
      starting_balance: null,
      started_at: null,
      archived_at: null,
    },
    autonomy: "OBSERVE_ONLY",
    screens: {
      wallet: blank,
      feed: blank,
      positions: blank,
      targets: blank,
      health: {
        measured: true,
        detail: "healthy overall; 0 components unmeasured.",
        values: {
          overall: "healthy",
          database: "healthy",
          redis: "healthy",
          worker: "healthy",
          scheduler: "healthy",
          disk: "healthy",
          karthik_loop: "not running",
        },
        rows: [],
      },
      reports: blank,
    },
    accounting: blank,
    integrity: {
      score: null,
      band: "NOT MEASURED",
      headline: "No Karthik Paper Wallet is designated.",
      deductions: [
        {
          factor: "accounting_consistency",
          label: "Accounting consistency",
          penalty: 0,
          measured: false,
          detail: "No Karthik Paper Wallet is designated.",
        },
      ],
      unmeasured: 1,
    },
    incidents: [],
    recent: [],
    actions: [],
    allowlist: [
      {
        key: "karthik.quote_retry",
        summary: "Retry one idempotent quote retrieval.",
        precondition: "The quote request failed transiently.",
        reversible: true,
      },
    ],
    checks: [
      {
        key: "accounting_mismatch",
        label: "Cash plus open value does not reconcile with equity",
        rectification: "OWNER_REQUIRED",
        severity: "critical",
        detectable: true,
        gap: null,
      },
      {
        key: "dead_zero_fantasy_profit",
        label: "A dead token booked at a profit",
        rectification: "OBSERVE_ONLY",
        severity: "critical",
        detectable: false,
        gap: "Requires a liquidity reading at exit to say a price was unexecutable.",
      },
    ],
    reports: {
      daily: {
        window: "daily",
        since: null,
        until: new Date(NOW).toISOString(),
        measured: false,
        detail: "No Karthik Paper Wallet is designated.",
        starting_equity_usd: null,
        ending_equity_usd: null,
        pnl_usd: null,
        opportunities: null,
        entered: null,
        targets_hit: null,
        dead_zero: null,
        open_positions: null,
        closed_positions: null,
        best_trade: null,
        worst_trade: null,
        average_hold_seconds: null,
        target_hit_rate: null,
        dead_rate: null,
        cash_utilisation: null,
        bugs_detected: null,
        repairs_performed: null,
        owner_attention: null,
        integrity: null,
        daily_series: [],
      },
    },
    while_away: {
      since: null,
      until: new Date(NOW).toISOString(),
      measured: false,
      detail: "First visit on this device.",
      opportunities: null,
      new_trades: null,
      targets_hit: null,
      dead_positions: null,
      pnl_usd: null,
      biggest_winner: null,
      biggest_loss: null,
      bugs_found: null,
      bugs_fixed: null,
      owner_attention: null,
      integrity_score: null,
    },
    observed_at: new Date(NOW).toISOString(),
    ...over,
  };
}

function source(state: KarthikState | null): Source<KarthikState> {
  return { data: state, observedAt: state ? NOW : null };
}

const noop = () => {};

describe("the panel refuses to invent a wallet", () => {
  it("renders the reason on every unmeasured screen, never a zero", () => {
    const { container } = render(
      <KarthikPanel source={source(unbound())} now={NOW} onClose={noop} />,
    );
    const blanks = screen.getAllByTestId("karthik-unmeasured");
    expect(blanks.length).toBeGreaterThanOrEqual(4);
    for (const blank of blanks) {
      expect(blank.textContent).toContain("Not measured");
    }
    // The specific failure this whole feature exists to avoid.
    expect(container.textContent).not.toContain("$0.00");
  });

  it("shows a dash for an unscored experiment, not 0 and not 100", () => {
    render(<KarthikPanel source={source(unbound())} now={NOW} onClose={noop} />);
    const score = screen.getByTestId("karthik-integrity-score");
    expect(score.textContent).toBe("—");
    expect(score.textContent).not.toContain("0");
    expect(score.textContent).not.toContain("100");
  });

  it("says once, not twice, that there is no wallet", () => {
    // The overview's own screen already carries the sentence. A second copy in
    // the same card reads as a rendering bug rather than as emphasis.
    render(<KarthikPanel source={source(unbound())} now={NOW} onClose={noop} />);
    expect(screen.queryByTestId("karthik-binding-detail")).toBeNull();
    expect(screen.getByLabelText("Overview").textContent).toContain(
      "No Karthik Paper Wallet is designated",
    );
  });

  it("calls out a misconfigured binding as something only the owner can fix", () => {
    // Forbidden and missing bindings are not "waiting" — they are a variable
    // somebody has to correct, and they earn their own line.
    const misconfigured = unbound({
      binding: {
        ...unbound().binding,
        state: "forbidden",
        needs_owner: true,
        detail: "KARTHIK_WALLET_STRATEGY_ID names a wallet Karthik may not operate.",
      },
    });
    render(<KarthikPanel source={source(misconfigured)} now={NOW} onClose={noop} />);
    expect(screen.getByTestId("karthik-binding-detail").textContent).toContain(
      "may not operate",
    );
  });

  it("shows nothing rather than a stale reading when the source has aged out", () => {
    render(
      <KarthikPanel
        source={{ data: unbound(), observedAt: NOW - 10 * 60_000 }}
        now={NOW}
        onClose={noop}
      />,
    );
    expect(screen.queryByTestId("karthik-panel")).toBeNull();
    expect(screen.getByText(/No current reading/)).toBeTruthy();
  });

  it("reports infrastructure it genuinely measured, beside a loop that is not running", () => {
    // The honest mixed case: §26's shared probe answers, Karthik's own loop
    // does not exist yet, and both are shown as what they are.
    render(<KarthikPanel source={source(unbound())} now={NOW} onClose={noop} />);
    const health = screen.getByLabelText("System health");
    expect(within(health).getByText("not running")).toBeTruthy();
    expect(within(health).getAllByText("healthy").length).toBeGreaterThan(0);
  });
});

describe("the panel publishes its own limits", () => {
  it("names the autonomy mode and says what it means", () => {
    render(<KarthikPanel source={source(unbound())} now={NOW} onClose={noop} />);
    const authority = screen.getByLabelText("What Karthik is permitted to do");
    expect(authority.textContent).toContain("OBSERVE_ONLY");
    expect(authority.textContent).toContain("He executes nothing");
  });

  it("renders the allowlist the API published rather than a description of it", () => {
    render(<KarthikPanel source={source(unbound())} now={NOW} onClose={noop} />);
    expect(screen.getByText("karthik.quote_retry")).toBeTruthy();
  });

  it("shows the conditions it cannot yet check, and why", () => {
    render(<KarthikPanel source={source(unbound())} now={NOW} onClose={noop} />);
    const checks = screen.getByLabelText("What Karthik checks for");
    expect(within(checks).getAllByText("not checkable").length).toBe(1);
    expect(checks.textContent).toContain("Requires a liquidity reading at exit");
  });

  it("explains an empty action log instead of implying nothing went wrong", () => {
    render(<KarthikPanel source={source(unbound())} now={NOW} onClose={noop} />);
    expect(screen.getByLabelText("Action log").textContent).toContain(
      "nothing executes",
    );
  });

  it("distinguishes a first visit from a quiet one", () => {
    render(<KarthikPanel source={source(unbound())} now={NOW} onClose={noop} />);
    expect(
      screen.getByLabelText("What happened while you were away?").textContent,
    ).toContain("First visit on this device");
  });
});

describe("the panel renders a bound wallet's figures", () => {
  const bound = unbound({
    binding: {
      state: "bound",
      designated_strategy_id: "karthik_tr_125_nostop_v1",
      detail: "Operating generation 1 of karthik_tr_125_nostop_v1.",
      readable: true,
      needs_owner: false,
      wallet_id: "0000",
      strategy_version: "1.0.0",
      generation: 1,
      starting_balance: "1000",
      started_at: new Date(NOW - 86_400_000).toISOString(),
      archived_at: null,
    },
    screens: {
      ...unbound().screens,
      wallet: {
        measured: true,
        detail: "Derived from 3 position rows.",
        values: {
          starting_capital_usd: "1000",
          cash_usd: "1024.30",
          allocated_usd: "20",
          realised_pnl_usd: "44.30",
          unrealised_pnl_usd: null,
          open_positions: 2,
          closed_positions: 1,
        },
        rows: [],
      },
      positions: {
        measured: true,
        detail: "2 open.",
        rows: [
          {
            mint: "MintA",
            quantity: "100",
            entry_price: "1",
            current_price: "1.1",
            multiple: "1.1",
            target_price: "1.25",
            quote_age_seconds: 4,
            quote_stale: false,
          },
          {
            mint: "MintB",
            quantity: "50",
            entry_price: "2",
            current_price: null,
            multiple: null,
            target_price: "2.5",
            quote_age_seconds: null,
            quote_stale: true,
          },
        ],
        values: {},
      },
    },
    integrity: {
      score: 71,
      band: "DEGRADED",
      headline: "DEGRADED — quote and monitoring freshness is the largest deduction (18).",
      deductions: [
        {
          factor: "quote_freshness",
          label: "Quote and monitoring freshness",
          penalty: 18,
          measured: true,
          detail: "1 of 2 open positions priced from a stale quote.",
        },
      ],
      unmeasured: 0,
    },
  });

  it("formats money from the backend's own strings", () => {
    render(<KarthikPanel source={source(bound)} now={NOW} onClose={noop} />);
    const overview = screen.getByLabelText("Overview");
    expect(overview.textContent).toContain("$1,024.30");
  });

  it("marks an unpriced position NOT AVAILABLE and its quote STALE", () => {
    render(<KarthikPanel source={source(bound)} now={NOW} onClose={noop} />);
    const positions = screen.getByLabelText("Positions and targets");
    expect(positions.textContent).toContain("1.100x");
    expect(positions.textContent).toContain("NOT AVAILABLE");
    expect(positions.textContent).toContain("NO QUOTE");
  });

  it("shows the score with its band and the deduction that drove it", () => {
    render(<KarthikPanel source={source(bound)} now={NOW} onClose={noop} />);
    expect(screen.getByTestId("karthik-integrity-score").textContent).toBe("71 / 100");
    expect(screen.getByLabelText("Experiment integrity").textContent).toContain("−18");
  });

  it("still reports unrealised P&L as absent rather than as zero", () => {
    // An unpriced book is not a flat book, and this is the row where that
    // distinction is most tempting to lose.
    render(<KarthikPanel source={source(bound)} now={NOW} onClose={noop} />);
    expect(screen.getByLabelText("Overview").textContent).toContain("NOT AVAILABLE");
  });
});

describe("the room", () => {
  it("draws six screens on Karthik's bench, more than any other desk", () => {
    // `DeskInstruments`, not `Desk`: the slab is identical for everybody and
    // the instruments on it are the identity.
    const count = (theme: Parameters<typeof DeskInstruments>[0]["theme"]) => {
      const { container, unmount } = render(
        <svg>
          <DeskInstruments x={0} y={0} theme={theme} />
        </svg>,
      );
      const screens = container.querySelectorAll(".hq-screen").length;
      unmount();
      return screens;
    };
    expect(count("wallet-ops")).toBe(6);
    // Dex's four is the busiest desk on the trading floor.
    expect(count("wallet-ops")).toBeGreaterThan(count("market"));
  });

  it("signs the lab and lights it NO DATA before anything is measured", () => {
    const { container } = render(
      <HqStage focusedZone={null} onFocusZone={noop} onSelectEmployee={noop} density="full" />,
    );
    const sign = container.querySelector('[data-testid="karthik-signage"]');
    expect(sign).not.toBeNull();
    expect(sign!.textContent).toContain("Track Record Wallet Operations");
    expect(sign!.querySelector("[data-status]")!.getAttribute("data-status")).toBe("NO DATA");
  });

  it("lights the lab NEEDS OWNER when the reading says so, and only then", () => {
    const state = deriveHqState();
    const escalating = {
      ...state,
      employees: {
        ...state.employees,
        karthik: { ...state.employees.karthik, state: "incident" as const },
      },
    };
    const { container } = render(
      <HqStage
        focusedZone={null}
        onFocusZone={noop}
        onSelectEmployee={noop}
        density="full"
        state={escalating}
      />,
    );
    expect(
      container
        .querySelector('[data-testid="karthik-signage"] [data-status]')!
        .getAttribute("data-status"),
    ).toBe("NEEDS OWNER");
  });
});
