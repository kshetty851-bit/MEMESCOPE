import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, expect, it, vi } from "vitest";

import type * as ApiClientModule from "@/lib/api-client";
import { api } from "@/lib/api-client";

import { RafiqLabPage } from "./page";
import { PLAIN_RULES } from "./rules";
import type { RafiqStrategy } from "./types";

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

/** The current run, as prod serves it: A2-E2 re-armed beside G1. */
const BOOKS = [
  ["A2", "Gate only"],
  ["B2", "Fast and cheap, gated"],
  ["C2", "Partial exit"],
  ["D2", "No cap"],
  ["E2", "Strict"],
  ["G1", "Moonshot"],
] as const;

function book(code: string, name: string): RafiqStrategy {
  return {
    code,
    name,
    lane: code.toLowerCase(),
    question: "",
    take_profit_mult: null,
    stop_mult: "0.88",
    trailing_frac: null,
    max_hold_hours: "1",
    entry_threshold: "70",
    liquidity_derived_risk: false,
    daily_breaker: false,
    consensus_gate: false,
    enters: true,
    equity_floor: null,
    max_trades_per_day: null,
    gate: { min_liquidity_usd: "50000", min_market_cap_usd: "200000" },
    starting_equity: "1000",
    execution_cost_usd: "0",
    cash: "1000",
    equity: "1000",
    realised_pnl: "0",
    unrealised_pnl: "0",
    open_positions: 0,
    closed_trades: 0,
    wins: 0,
    losses: 0,
    gross_pnl_ex_fees: "0",
    mean_pnl_per_trade_net: null,
    mean_pnl_per_trade_gross: null,
    entries_rejected_by_gate: 0,
    rejection_reason_counts: {},
    equity_curve: ["1000"],
    activated_at: code === "G1" ? "2026-09-17T08:26:26Z" : "2026-09-17T08:53:55Z",
  };
}

afterEach(cleanup);

it("spells out every book's rules in plain words", async () => {
  vi.mocked(api.get).mockImplementation(async (path: string) =>
    path === "/labs/rafiq/status"
      ? {
          running: true,
          starting_equity: "1000",
          strategies: BOOKS.map(([code, name]) => book(code, name)),
        }
      : [],
  );

  render(<RafiqLabPage />, { wrapper });

  await screen.findByText("How each book trades, in plain words");
  for (const [code] of BOOKS) {
    const rules = PLAIN_RULES[code];
    expect(rules, `no plain rules for ${code}`).toBeDefined();
    expect(screen.getByText(rules?.idea ?? "")).toBeTruthy();
  }
  // Only G1's exits depend on their order.
  expect(screen.getAllByText("Sells (checked in this order)")).toHaveLength(1);
  expect(screen.getByText(/^6 strategies supplied by a collaborator/)).toBeTruthy();
});
