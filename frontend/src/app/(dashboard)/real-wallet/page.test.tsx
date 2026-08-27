import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import RealWalletPage from "@/app/(dashboard)/real-wallet/page";
import { api } from "@/lib/api-client";

vi.mock("@/lib/api-client", () => ({ api: { get: vi.fn() } }));

function wrapper({ children }: { children: ReactNode }) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
}

/**
 * The status payload the page actually receives, in its locked posture.
 *
 * Shared by both rendering tests because the previous inline fixture had
 * drifted behind the page: `rpc`, `network` and `readiness` are always present
 * in the real response, and rendering without them threw before a single
 * assertion could run.
 */
function lockedStatus() {
  return {
    public_key: "PublicExecutionWalletAddress",
    address_valid: true,
    network: "devnet",
    rpc: {
      network: "devnet",
      verified: true,
      observed_genesis_hash: "EtWTRABZaYq6iMfeYKouRu166VU2xqa1wcaWoxPkrZBG",
      error: null,
    },
    sol_balance: 0,
    token_balances: [],
    balance_error: null,
    funding_status: "unfunded",
    mode: "disabled",
    execution_enabled: false,
    autotrade_enabled: false,
    signer_status: "not_available_to_api",
    live_submission_transport: "not_installed",
    safety_gate: "read_only_safety_gate_available",
    lock_state: "LOCKED",
    security_gate: {
      shared_with_paper: true,
      evaluator: "sec2_entry_policy",
      mandatory_checks: ["mint_authority", "freeze_authority"],
      max_evidence_age_seconds: 900,
    },
    program_allowlist: ["JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4"],
    readiness: {
      config_contract: {
        execution_settings_shared: true,
        mode: "disabled",
        execution_enabled: false,
        autotrade_enabled: false,
        safety_policy_version: "real_wallet_safety_v1",
      },
      transport: {
        envelope: "disabled",
        release_approved: false,
        production_transport_installed: false,
        submission_permitted: false,
        reasons: ["RELEASE_NOT_APPROVED"],
        allowed_hosts: ["api.jup.ag"],
        configured_host: "api.jup.ag",
      },
      order_validation: { evidence_recheck_installed: true, checks: ["taker"] },
      fee_accounting: {
        sol_price_provider: "jupiter",
        sol_price_source: null,
        sol_price_usd: null,
        sol_price_observed_at: null,
        sol_price_age_seconds: null,
        sol_price_fresh: false,
        max_age_seconds: 120,
        min_sol_fee_reserve: "0.01",
        priority_fee_sol: "0.0005",
        exit_fee_reserve_multiplier: 2,
        fee_accounting_ready: false,
        unavailable_reason: "sol_price_unavailable",
      },
    },
    limits: {
      entry_size_usd: null,
      entry_size_configured: false,
      max_trade_usd: "5",
      max_open_positions: 1,
      max_total_exposure_usd: "10",
      max_daily_notional_usd: "20",
      max_daily_trades: 4,
      max_daily_loss_usd: "10",
      max_balance_sol: "0.25",
      max_balance_lamports: 250000000,
      min_sol_fee_reserve: "0.01",
    },
    dry_run: { feature_enabled: false, decisions: [] },
    live_readiness: {
      open_real_positions: 0,
      unresolved_intents: [],
      kill_switches: [],
      kill_switch_history: [],
    },
    confirmed_lifecycle: {
      consecutive_execution_failures: 0,
      last_failure_reason: null,
      positions: [
        {
          id: "position-1",
          mint_address: "ConfirmedMintAddress",
          status: "CLOSED",
          quantity: "2.5",
          entry_actual_input_amount: "5",
          entry_actual_output_amount: "2.5",
          exit_actual_input_amount: "2.5",
          exit_actual_output_amount: "7.5",
          realised_gross_pnl_usd: "2.5",
          realised_net_pnl_usd: "2.5",
          opened_at: "2026-08-09T00:00:00Z",
          closed_at: "2026-08-09T00:01:00Z",
        },
      ],
    },
  };
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("RealWalletPage", () => {
  it("does not reveal execution wallet information after an authorization failure", async () => {
    vi.mocked(api.get).mockRejectedValue(new Error("forbidden"));
    render(<RealWalletPage />, { wrapper });
    await waitFor(() => expect(screen.getByText("Restricted")).toBeInTheDocument());
    expect(screen.queryByText("Public address")).not.toBeInTheDocument();
  });

  it("renders only public read-only wallet data", async () => {
    vi.mocked(api.get).mockResolvedValue(lockedStatus());
    render(<RealWalletPage />, { wrapper });
    await waitFor(() =>
      expect(screen.getByText("PublicExecutionWalletAddress")).toBeInTheDocument(),
    );
    expect(screen.getByText("Copy address")).toBeInTheDocument();
    expect(screen.getByText("Confirmed lifecycle ledger")).toBeInTheDocument();
    expect(screen.getByText("$2.5")).toBeInTheDocument();
    // Execution and autotrade each read DISABLED on their own status card.
    expect(screen.getAllByText("DISABLED").length).toBeGreaterThanOrEqual(2);
  });

  it("states the locked posture and the canary bounds without offering a way past them", async () => {
    vi.mocked(api.get).mockResolvedValue(lockedStatus());
    render(<RealWalletPage />, { wrapper });
    await waitFor(() =>
      expect(
        screen.getByText("LOCKED · NO REAL SUBMISSION IS POSSIBLE"),
      ).toBeInTheDocument(),
    );
    // An unconfigured entry size must read as a refusal, not as a blank.
    expect(screen.getByText("NOT CONFIGURED — entries refuse")).toBeInTheDocument();
    expect(screen.getByText(/0\.25 SOL \(250000000 lamports\)/)).toBeInTheDocument();
    expect(screen.getByText(/same SEC-2 evaluator/)).toBeInTheDocument();
    expect(
      screen.getByText("JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4"),
    ).toBeInTheDocument();
    // No *control* on this page may enable execution or widen a limit. Asserted
    // over interactive elements rather than page text, so the paragraph that
    // explains the property does not satisfy the test that checks it.
    const controls = [
      ...screen.queryAllByRole("button"),
      ...screen.queryAllByRole("checkbox"),
      ...screen.queryAllByRole("switch"),
    ].map((element) => element.textContent ?? "");
    expect(
      controls.filter((label) => /enable|arm|unlock|go live|mainnet/i.test(label)),
    ).toEqual([]);
  });
});
