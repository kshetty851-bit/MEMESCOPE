import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type * as ApiClientModule from "@/lib/api-client";
import { api } from "@/lib/api-client";

import { KarthikLabPage } from "./page";
import type { KarthikBook } from "./types";

// Karthik, 2026-10-03: "in karthik lab only show as 50k pool". His Lab draws
// the Checkpoint at his book's $50k rule; HQ and the Real wallet keep $75k.

vi.mock("@/lib/api-client", async (importOriginal) => ({
  ...(await importOriginal<typeof ApiClientModule>()),
  api: { get: vi.fn(), post: vi.fn() },
}));

const book = {
  book: "KARTHIK_QUIET_5M", rule: "the quiet rule", hold_minutes: 5,
  started_at: "2026-09-23T12:00:00Z", judge_at: "2026-10-23T12:00:00Z",
  resized_at: "2026-10-03T12:30:00Z", previous_capital_usd: "100", previous_ticket_usd: "50",
  capital_usd: "500", ticket_usd: "50", balance_usd: "500", pnl_usd: "0", lowest_usd: "500",
  trades: 0, skipped: 0, busy_skipped: 0, one_at_a_time_since: null, wins: 0, rugs: 0,
  days: [], trades_list: [],
  whatif: { floors: [], sizes: [] },
} as unknown as KarthikBook;

vi.mock("./hooks", () => ({
  useKarthikBook: () => ({ data: book, isLoading: false, isError: false, refetch: vi.fn() }),
  usePumpfunDays: () => ({ data: undefined }),
  useWalletsProfit: () => ({ data: undefined }),
}));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

afterEach(() => vi.clearAllMocks());

describe("Karthik's Lab Checkpoint", () => {
  it("asks for the $50k pool rule, and only that", async () => {
    vi.mocked(api.get).mockReturnValue(new Promise(() => {}));
    render(<KarthikLabPage />, { wrapper });
    await waitFor(() => expect(screen.getByTestId("checkpoint")).toBeInTheDocument());
    const paths = vi.mocked(api.get).mock.calls.map(([p]) => p as string)
      .filter((p) => p.startsWith("/real-wallet/checkpoint"));
    expect(paths.sort()).toEqual([
      "/real-wallet/checkpoint/live?floor=50000", "/real-wallet/checkpoint?floor=50000"]);
    expect(screen.getByTestId("cp-bot-depth")).toHaveAccessibleName(
      "Diego (Depth): The pool holds at least $50,000");
  });
});
