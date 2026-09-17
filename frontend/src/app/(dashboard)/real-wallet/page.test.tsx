import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import RealWalletPage from "@/app/(dashboard)/real-wallet/page";
import type * as ApiClientModule from "@/lib/api-client";
import { ApiError, api } from "@/lib/api-client";
import { useAuthStore } from "@/stores/auth-store";

// `api` is mocked; `ApiError` is not. The page branches on the real error type.
vi.mock("@/lib/api-client", async (importOriginal) => ({
  ...(await importOriginal<typeof ApiClientModule>()),
  api: { get: vi.fn(), post: vi.fn() },
}));

function wrapper({ children }: { children: ReactNode }) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
}

const ADDRESS = "7WctMGpqz1tGkYStBBjJRMnmuh9uwJubYV2tL4pLwRr9";
const MINE = "FoHVQyJmv5AHPjccV3BWpMoKiMHLPkF5cfQdqo1nH5TN";

function status(overrides: Record<string, unknown> = {}) {
  return {
    public_key: ADDRESS,
    network: "mainnet",
    rpc: { verified: true, error: null },
    sol_balance: 0.0498,
    sol_price_usd: 97,
    sol_price_fresh: true,
    balance_usd: 4.83,
    token_balances: [],
    balance_error: null,
    withdrawal: { locked_to: MINE, configured: true, reason: null },
    mode: "live",
    execution_enabled: true,
    autotrade_enabled: true,
    limits: {
      entry_size_usd: "100",
      max_open_positions: 6,
      max_total_exposure_usd: "600",
      max_daily_trades: 100,
      max_daily_loss_usd: "30",
      balance_ceiling_enabled: false,
      max_balance_sol: "15",
      min_sol_fee_reserve: "0.01",
      exit_max_price_impact_pct: "50",
      max_slippage_bps: 300,
    },
    today: {
      realised_pnl_usd: "0",
      loss_limit_usd: "30",
      loss_limit_hit: false,
      buys: 0,
      buys_limit: 100,
      resets_at: "2026-09-17T00:00:00+00:00",
    },
    open_positions: 0,
    kill_switches: [],
    consecutive_execution_failures: 0,
    failures_before_kill_switch: 2,
    last_failure_reason: null,
    positions: [],
    ...overrides,
  };
}

const FIVE = {
  id: "G-B3-5M",
  name: "GRADUATION-B3-5MIN",
  paper_book: "B3_198k_5m",
  idea: "hold graduations for five minutes",
  pool_floor_usd: 198000,
  hold_minutes: 5,
  take_profit: false,
  stop_loss: false,
  max_signal_age_seconds: 60,
  ticket_usd: "100",
  min_ticket_usd: "56",
};
const FOUR = {
  ...FIVE,
  id: "G-B3-4M",
  name: "GRADUATION-B3-4MIN",
  paper_book: "B3_198k_4m",
  idea: "sell a minute sooner",
  hold_minutes: 4,
};

function autotrade(overrides: Record<string, unknown> = {}) {
  return {
    enabled: false,
    nominated_strategy: null,
    ticket_usd: null,
    started_at: null,
    started_by: null,
    stopped_at: null,
    stopped_by: null,
    can_start: false,
    strategy: FIVE,
    strategies: [FIVE, FOUR],
    ticket_choices: [
      ["100", "56"],
      ["50", "28"],
      ["25", "14"],
      ["20", "11.2"],
      ["10", "5.6"],
      ["5", "2.8"],
    ].map(([ticket_usd, min_usd]) => ({ ticket_usd, min_usd })),
    history: [],
    ...overrides,
  };
}

function check(key: string, owner: string, state: string, title: string, detail = "") {
  return { key, owner, status: state, title, detail, remediation: `How to fix ${key}.` };
}

function readiness(overrides: Record<string, unknown> = {}) {
  return {
    ready_to_fund: true,
    ready_to_trade: false,
    proven: false,
    min_trade_sol: "0.588",
    full_trade_sol: "1.041",
    checks: [
      check("wallet_configured", "OPERATOR", "PASS", "A dedicated execution wallet exists"),
      check(
        "wallet_funded", "OPERATOR", "BLOCKED", "The wallet can pay for a trade",
        "balance 0.0498 SOL; one trade needs 0.588 SOL",
      ),
      check("strategy_signals", "CODE", "PASS", "The strategy is sending buy signals",
        "last signal 12 min ago"),
      check("validated_strategy", "EVIDENCE", "BLOCKED", "The strategy is proven",
        "not proven — the Graduation Lab has not called it an edge"),
      check("real_round_trip", "EVIDENCE", "BLOCKED", "A real buy and sell have completed",
        "0 real round trip(s) settled"),
    ],
    ...overrides,
  };
}

function serve(
  data: { status?: unknown; autotrade?: unknown; readiness?: unknown } = {},
) {
  vi.mocked(api.get).mockImplementation(async (path: string) => {
    if (path === "/real-wallet/status") return data.status ?? status();
    if (path === "/real-wallet/autotrade") return data.autotrade ?? autotrade();
    if (path === "/real-wallet/funding-readiness") return data.readiness ?? readiness();
    throw new Error(`unexpected GET ${path}`);
  });
}

async function renderLoaded() {
  render(<RealWalletPage />, { wrapper });
  await waitFor(() => expect(screen.getByText(ADDRESS)).toBeInTheDocument());
}

function signInAsAdmin() {
  useAuthStore.setState({
    status: "authenticated",
    user: {
      id: "admin-1",
      email: "owner@example.com",
      display_name: "Owner",
      role: "admin",
      is_active: true,
      is_verified: true,
      last_login_at: null,
      created_at: new Date(0).toISOString(),
    },
  });
}

beforeEach(() => {
  useAuthStore.setState({ status: "unauthenticated", user: null });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("RealWalletPage without signing in", () => {
  it("opens straight onto the wallet — no entry screen, no sign-in wall", async () => {
    serve();
    await renderLoaded();
    expect(screen.queryByText(/fasten your seatbelt/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/session has expired/i)).not.toBeInTheDocument();
    expect(screen.getByText("0.049800")).toBeInTheDocument();
  });

  it("claims nothing about the wallet before it has been read", () => {
    vi.mocked(api.get).mockReturnValue(new Promise(() => {}));
    render(<RealWalletPage />, { wrapper });
    expect(screen.getByText("Reading the wallet…")).toBeInTheDocument();
    expect(screen.queryByText(/no wallet configured/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/would not trade yet/i)).not.toBeInTheDocument();
  });

  it("carries none of the retired panels", async () => {
    serve();
    await renderLoaded();
    for (const gone of [
      /manual devnet/i,
      /dry-run decisions/i,
      /program allowlist/i,
      /pre-mainnet readiness/i,
      /choose a strategy/i,
    ]) {
      expect(screen.queryByText(gone)).not.toBeInTheDocument();
    }
  });

  it("names the strategy the wallet trades, in plain words", async () => {
    serve();
    await renderLoaded();
    const card = screen.getByText("Strategy Start would trade").closest("section")!;
    expect(within(card).getByText("G-B3-5M")).toBeInTheDocument();
    expect(card.textContent).toContain("copies paper book B3_198k_5m");
    expect(card.textContent).toContain("at least $198,000");
    expect(card.textContent).toContain("exactly 5 minutes later");
    expect(card.textContent).toContain("never under $56");
    // Unproven is said, with a way to look.
    expect(card.textContent).toContain("Not proven yet");
    expect(within(card).getByRole("link", { name: /paper results/i })).toHaveAttribute(
      "href",
      "/graduation-lab",
    );
  });

  it("offers a sign-in link where Start would be, and Stop that works now", async () => {
    serve();
    await renderLoaded();
    const panel = screen.getByText("Trading").closest("section")!;
    expect(within(panel).queryByRole("button", { name: /^start/i })).toBeNull();
    expect(within(panel).getByRole("link", { name: /sign in to start/i })).toHaveAttribute(
      "href",
      "/login?next=/real-wallet",
    );
    const stop = within(panel).getByRole("button", { name: /^stop$/i });
    expect(stop).toBeEnabled();
  });

  it("stops at once, without an account or a typed reason", async () => {
    serve({ autotrade: autotrade({ enabled: true, nominated_strategy: "G-B3-5M" }) });
    vi.mocked(api.post).mockResolvedValue(autotrade());
    await renderLoaded();
    fireEvent.click(screen.getByRole("button", { name: /^stop$/i }));
    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith("/real-wallet/autotrade/stop", {
        reason: "stopped from the wallet page",
      }),
    );
  });
});

describe("RealWalletPage signed in as the administrator", () => {
  it("starts the wallet's strategy once a reason is given", async () => {
    signInAsAdmin();
    serve();
    vi.mocked(api.post).mockResolvedValue(autotrade({ enabled: true }));
    await renderLoaded();
    const panel = screen.getByText("Trading").closest("section")!;
    const start = within(panel).getByRole("button", { name: "Start G-B3-5M" });
    expect(start).toBeDisabled();

    fireEvent.change(within(panel).getByPlaceholderText(/reason/i), {
      target: { value: "funded, going live" },
    });
    expect(start).toBeEnabled();
    fireEvent.click(start);
    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith("/real-wallet/autotrade/start", {
        strategy_id: "G-B3-5M",
        reason: "funded, going live",
        ticket_usd: "100",
      }),
    );
  });

  it("starts the arm and the trade size picked, and describes them first", async () => {
    signInAsAdmin();
    serve();
    vi.mocked(api.post).mockResolvedValue(autotrade({ enabled: true }));
    await renderLoaded();
    const panel = screen.getByText("Trading").closest("section")!;
    fireEvent.click(within(panel).getByRole("button", { name: /B3_198k_4m/ }));
    fireEvent.click(within(panel).getByRole("button", { name: "$25" }));

    const card = screen.getByText("Strategy Start would trade").closest("section")!;
    expect(within(card).getByText("G-B3-4M")).toBeInTheDocument();
    expect(card.textContent).toContain("copies paper book B3_198k_4m");
    expect(card.textContent).toContain("exactly 4 minutes later");
    expect(card.textContent).toContain("$25 a trade");
    expect(card.textContent).toContain("never under $14");

    fireEvent.change(within(panel).getByPlaceholderText(/reason/i), {
      target: { value: "smaller bets" },
    });
    fireEvent.click(within(panel).getByRole("button", { name: "Start G-B3-4M" }));
    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith("/real-wallet/autotrade/start", {
        strategy_id: "G-B3-4M",
        reason: "smaller bets",
        ticket_usd: "25",
      }),
    );
  });

  it("shows what is running and will not change it until stopped", async () => {
    signInAsAdmin();
    serve({
      autotrade: autotrade({
        enabled: true,
        nominated_strategy: "G-B3-4M",
        ticket_usd: "25",
        strategy: { ...FOUR, ticket_usd: "25", min_ticket_usd: "14" },
      }),
    });
    await renderLoaded();
    const panel = screen.getByText("Trading").closest("section")!;
    expect(panel.textContent).toContain("ON — G-B3-4M · $25 a trade");
    expect(within(panel).getByRole("button", { name: "$25" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(within(panel).getByRole("button", { name: "$100" })).toBeDisabled();
    expect(panel.textContent).toContain("Stop first to change the arm or the size.");
    expect(screen.getByText("Strategy this wallet trades")).toBeInTheDocument();
  });

  it("cannot start twice", async () => {
    signInAsAdmin();
    serve({ autotrade: autotrade({ enabled: true, nominated_strategy: "G-B3-5M" }) });
    await renderLoaded();
    const panel = screen.getByText("Trading").closest("section")!;
    fireEvent.change(within(panel).getByPlaceholderText(/reason/i), {
      target: { value: "again" },
    });
    expect(within(panel).getByRole("button", { name: "Start G-B3-5M" })).toBeDisabled();
    expect(panel.textContent).toContain("ON — G-B3-5M");
  });
});

describe("RealWalletPage readiness", () => {
  it("answers fund, trade and proven, and says what is missing", async () => {
    serve();
    await renderLoaded();
    expect(screen.getByText("Ready to fund: YES")).toBeInTheDocument();
    expect(screen.getByText("Ready to trade: NO")).toBeInTheDocument();
    expect(screen.getByText("Strategy proven: NO")).toBeInTheDocument();
    expect(screen.getByText("The wallet can pay for a trade")).toBeInTheDocument();
    expect(screen.getByText(/one trade needs 0\.588 SOL/)).toBeInTheDocument();
    // Evidence is reported beside the verdicts, never hidden.
    expect(screen.getByText(/A real buy and sell have completed/)).toBeInTheDocument();
  });

  it("does not promise a buy the wallet cannot make", async () => {
    serve();
    await renderLoaded();
    const panel = screen.getByText("Trading").closest("section")!;
    expect(panel.textContent).toContain("Start would not buy yet");
    expect(panel.textContent).not.toContain("buys with real money");
  });

  it("says Start will trade once nothing is missing", async () => {
    serve({
      readiness: readiness({
        ready_to_trade: true,
        checks: [check("wallet_funded", "OPERATOR", "PASS", "The wallet can pay for a trade")],
      }),
    });
    await renderLoaded();
    expect(screen.getByText("Ready to trade: YES")).toBeInTheDocument();
    expect(screen.getByText(/pressing Start will trade real money/)).toBeInTheDocument();
    expect(screen.getByText("Trading").closest("section")!.textContent).toContain(
      "Start buys with real money from the next signal",
    );
  });

  it("puts the whole checklist one tap away", async () => {
    serve();
    await renderLoaded();
    fireEvent.click(screen.getByRole("button", { name: "Show all 5 checks" }));
    expect(screen.getByText("A dedicated execution wallet exists")).toBeInTheDocument();
  });

  it("tells the depositor how much a trade needs", async () => {
    serve();
    await renderLoaded();
    fireEvent.click(screen.getByRole("button", { name: /deposit/i }));
    const panel = screen.getByText("Deposit SOL").closest("div")!;
    expect(panel.textContent).toContain("One trade needs at least 0.588 SOL");
    expect(panel.textContent).toContain("a full $100 trade needs 1.041 SOL");
    expect(within(panel).getByText("Copy address")).toBeInTheDocument();
  });
});

describe("RealWalletPage trades and limits", () => {
  it("shows a sell in progress and a settled result", async () => {
    serve({
      status: status({
        open_positions: 1,
        positions: [
          {
            id: "p-open", mint_address: "OpenMint1111", symbol: "OPEN", status: "OPEN",
            strategy_id: "G-B3-5M", quantity: "10", cost_usd: "99", spent: "1.0206",
            received: null, realised_gross_pnl_usd: null, realised_net_pnl_usd: null,
            exit_reason: "time_exit_unpriced", exit_state: "blocked",
            opened_at: "2026-09-16T10:00:00Z", closed_at: null,
            entry_signature: "sig1", exit_signature: null,
          },
          {
            id: "p-closed", mint_address: "DoneMint2222", symbol: null, status: "CLOSED",
            strategy_id: "G-B3-5M", quantity: "10", cost_usd: "3.0075", spent: "0.030075",
            received: "0.029185068", realised_gross_pnl_usd: "-0.0889932",
            realised_net_pnl_usd: "-0.1099932", exit_reason: "time_0.0833h",
            exit_state: null, opened_at: "2026-09-16T09:00:00Z",
            closed_at: "2026-09-16T09:05:00Z", entry_signature: "sig2",
            exit_signature: "sig3",
          },
        ],
      }),
    });
    await renderLoaded();
    const table = screen.getByText("Real trades").closest("section")!;
    expect(table.textContent).toContain("sell refused — retrying");
    expect(table.textContent).toContain("sold on time");
    expect(table.textContent).toContain("0.0301 SOL");
    expect(table.textContent).toContain("0.0292 SOL");
    expect(table.textContent).toContain("−$0.11");
    expect(within(table).getByText("DoneMint")).toBeInTheDocument();
  });

  it("says so plainly when the daily loss limit has stopped buying", async () => {
    serve({
      status: status({
        today: {
          realised_pnl_usd: "-31.20", loss_limit_usd: "30", loss_limit_hit: true,
          buys: 12, buys_limit: 100, resets_at: "2026-09-17T00:00:00+00:00",
        },
      }),
    });
    await renderLoaded();
    expect(screen.getByText("−$31.20")).toBeInTheDocument();
    expect(screen.getByText(/Loss limit of \$30 reached — no new buys/)).toBeInTheDocument();
    expect(screen.getByText("12")).toBeInTheDocument();
  });

  it("puts an emergency stop at the top of the safety card", async () => {
    serve({
      status: status({
        kill_switches: [{
          kind: "consecutive_execution_failures", reason: "failure_threshold_reached",
          activated_at: null, activated_by: null,
        }],
        consecutive_execution_failures: 2,
      }),
    });
    await renderLoaded();
    expect(screen.getByText(/EMERGENCY STOP ON/)).toBeInTheDocument();
    expect(screen.getByText(/Failed sends in a row: 2 of 2/)).toBeInTheDocument();
  });

  it("asks for the site code, not an account, when the gate refuses", async () => {
    vi.mocked(api.get).mockRejectedValue(
      new ApiError(401, "alpha_access_required", "Alpha access is required."),
    );
    render(<RealWalletPage />, { wrapper });
    await waitFor(() =>
      expect(screen.getByText(/enter the site code on the home page/i)).toBeInTheDocument(),
    );
    expect(screen.queryByText(ADDRESS)).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /sign in/i })).toBeNull();
  });
});

describe("RealWalletPage withdrawal", () => {
  it("has no recipient field, only an amount, and shows the fixed destination", async () => {
    serve();
    await renderLoaded();
    fireEvent.click(screen.getByRole("button", { name: /^withdraw$/i }));
    const panel = screen.getByText("Withdraw SOL").closest("div")!;
    const inputs = Array.from(panel.querySelectorAll("input"));
    expect(inputs).toHaveLength(1);
    expect(inputs[0]?.placeholder).toBe("0.00");
    expect(panel.textContent).toContain("Locked destination");
    expect(panel.textContent).toContain(MINE);
  });

  it("says why the button is greyed", async () => {
    serve();
    await renderLoaded();
    fireEvent.click(screen.getByRole("button", { name: /^withdraw$/i }));
    const panel = screen.getByText("Withdraw SOL").closest("div")!;
    expect(panel.textContent).toContain("Enter an amount above zero");
  });

  it("arms first and says nothing has been sent", async () => {
    serve();
    await renderLoaded();
    fireEvent.click(screen.getByRole("button", { name: /^withdraw$/i }));
    const panel = screen.getByText("Withdraw SOL").closest("div")!;
    fireEvent.change(within(panel).getByPlaceholderText("0.00"), {
      target: { value: "0.001" },
    });
    fireEvent.click(within(panel).getByRole("button", { name: /^withdraw$/i }));
    expect(api.post).not.toHaveBeenCalled();
    expect(panel.textContent).toContain("Nothing has been sent yet");
    expect(within(panel).getByRole("button", { name: /confirm — send now/i })).toBeInTheDocument();
  });

  it("sends only on the explicit confirmation", async () => {
    serve();
    vi.mocked(api.post).mockResolvedValue({
      signature: "sigW", sol: "0.001", explorer: "https://solscan.io/tx/sigW",
      note: "Submitted once.",
    });
    await renderLoaded();
    fireEvent.click(screen.getByRole("button", { name: /^withdraw$/i }));
    const panel = screen.getByText("Withdraw SOL").closest("div")!;
    fireEvent.change(within(panel).getByPlaceholderText("0.00"), {
      target: { value: "0.001" },
    });
    fireEvent.click(within(panel).getByRole("button", { name: /^withdraw$/i }));
    fireEvent.click(within(panel).getByRole("button", { name: /confirm — send now/i }));
    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith("/real-wallet/withdraw", {
        sol_amount: "0.001",
        confirmation_phrase: "WITHDRAW_TO_MY_ADDRESS",
      }),
    );
  });

  it("offers nothing to press when no destination is nominated", async () => {
    serve({
      status: status({
        withdrawal: { locked_to: null, configured: false, reason: "not configured" },
      }),
    });
    await renderLoaded();
    fireEvent.click(screen.getByRole("button", { name: /^withdraw$/i }));
    expect(screen.getByText(/No destination is nominated/)).toBeInTheDocument();
    const panel = screen.getByText("Withdraw SOL").closest("div")!;
    expect(panel.querySelectorAll("input")).toHaveLength(0);
  });
});
