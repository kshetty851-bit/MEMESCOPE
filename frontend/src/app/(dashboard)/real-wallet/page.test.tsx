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
    vi.mocked(api.get).mockResolvedValue({
      public_key: "PublicExecutionWalletAddress",
      sol_balance: 0,
      balance_error: null,
      funding_status: "unfunded",
      mode: "disabled",
      execution_enabled: false,
      autotrade_enabled: false,
      signer_ready: false,
      live_submission_transport: "not_installed",
      safety_gate: "read_only_safety_gate_available",
      limits: {
        max_trade_usd: "5",
        max_open_positions: 1,
        max_total_exposure_usd: "10",
        max_daily_notional_usd: "20",
        max_daily_loss_usd: "10",
        min_sol_fee_reserve: "0.01",
      },
      dry_run: { feature_enabled: false, decisions: [] },
      live_readiness: { open_real_positions: 0, unresolved_intents: [], kill_switches: [] },
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
    });
    render(<RealWalletPage />, { wrapper });
    await waitFor(() =>
      expect(screen.getByText("PublicExecutionWalletAddress")).toBeInTheDocument(),
    );
    expect(screen.getAllByText("DISABLED")).toHaveLength(3);
    expect(screen.getByText("Copy address")).toBeInTheDocument();
    expect(screen.getByText("Confirmed lifecycle ledger")).toBeInTheDocument();
    expect(screen.getByText("$2.5")).toBeInTheDocument();
  });
});
